import abc
import asyncio
import contextlib
import errno
import ipaddress
import logging
import os
import re
import socket
import typing

try:
    import magic
except ImportError:
    magic = None

import mimeparse

from datetime import timedelta

import aiohttp

import aiofoomodules.handlers
from aiofoomodules.utils import (
    get_simple_body,
    ellipsise_text,
    format_byte_count,
)

from . import handlers


def is_html_mime_type(mime_type):
    return mime_type[:2] in [("text", "html"),
                             ("application", "xhtml+xml")]


class AbstractResponseFormatter(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def format_response(self, document, disambiguator=None):
        pass

    def _format_size(self, document):
        return "{approx}{}".format(
            format_byte_count(document.size),
            approx={
                handlers.SizeApproximation.GREATER_THAN: "≥",
                handlers.SizeApproximation.ANNOUNCED_BY_SERVER: "≈",
            }.get(document.size_approximation, "")
        )


class CompactResponseFormatter(AbstractResponseFormatter):
    def __init__(self, max_description_length=360, max_title_length=100):
        super().__init__()
        self.max_title_length = max_title_length
        self.max_description_length = max_description_length

    def format_response(self, document, disambiguator=None):
        parts = []

        if document.response.status != 200:
            parts.append("[{} {!r}] ".format(document.response.status,
                                             document.response.reason))

        if document.human_readable_type:
            parts.append(document.human_readable_type)
            if (document.size is not None and
                    not is_html_mime_type(document.mime_type)):
                parts.append(" ({})".format(self._format_size(document)))
        elif document.title:
            parts.append("{}".format(self._format_size(document)))

        if document.title is not None:
            parts.append(": ")
            parts.append(ellipsise_text(" ".join(document.title.split()),
                                        self.max_title_length))
            if document.description is not None:
                parts.append("\n")
                parts.append(ellipsise_text(
                    document.description.strip(),
                    self.max_description_length
                ))

        if parts and disambiguator is not None:
            parts.insert(0, "re <{}>: ".format(disambiguator))

        if parts:
            return ["".join(parts)]

        return []


class OnelineResponseFormatter(AbstractResponseFormatter):
    def __init__(self, max_title_length=100):
        super().__init__()
        self.max_title_length = max_title_length

    def format_response(self, document, disambiguator=None):
        parts = []

        if document.human_readable_type:
            parts.append(document.human_readable_type)
            if (document.size is not None and
                    not is_html_mime_type(document.mime_type)):
                parts.append(" ({})".format(self._format_size(document)))
        elif document.title:
            parts.append("{}".format(self._format_size(document)))

        if document.title is not None:
            parts.append(": ")
            parts.append(ellipsise_text(" ".join(document.title.split()),
                                        self.max_title_length))

        if parts and disambiguator is not None:
            parts.insert(0, "re <{}>: ".format(disambiguator))

        if parts:
            return ["".join(parts)]

        return []


class Connector(aiohttp.TCPConnector):
    def __init__(self, *, deny_networks=[], **kwargs):
        super().__init__(**kwargs)
        self._deny_networks = deny_networks

    def _allow_host(self, host):
        try:
            address = ipaddress.ip_address(host["host"])
        except ValueError:
            return False

        if any(address in network for network in self._deny_networks):
            return False

        return True

    async def _resolve_host(self, host, port, *args, **kwargs):
        results = await super()._resolve_host(host, port, *args, **kwargs)
        results = [
            hinfo
            for hinfo in results
            if self._allow_host(hinfo)
        ]
        if not results:
            raise PermissionError(errno.ENETUNREACH,
                                  os.strerror(errno.ENETUNREACH))
        return results


class URLProcessor:
    def __init__(self,
                 *,
                 deny_private=True,
                 handlers=[],
                 user_agent="aiofoorl/1.0",
                 max_prefetch=1024**2,
                 ssl_verify=True,
                 disable_magic=False,
                 disable_description_magic=False,
                 deny_networks=[],
                 **kwargs
                 ):
        super().__init__(**kwargs)

        self.logger = logging.getLogger(".".join([
            type(self).__module__,
            type(self).__qualname__,
        ]))

        self.deny_networks = list(deny_networks)
        if deny_private:
            self.deny_networks.append(ipaddress.ip_network("10.0.0.0/8"))
            self.deny_networks.append(ipaddress.ip_network("127.0.0.0/8"))
            self.deny_networks.append(ipaddress.ip_network("172.16.0.0/12"))
            self.deny_networks.append(ipaddress.ip_network("192.168.0.0/16"))
            self.deny_networks.append(ipaddress.ip_network("fc00::/7"))
            self.deny_networks.append(ipaddress.ip_network("fe80::/9"))
            self.deny_networks.append(ipaddress.ip_network("::1/128"))

        self.handlers = handlers
        self.user_agent = user_agent
        self.max_prefetch = max_prefetch
        self.ssl_verify = ssl_verify

        self.mime_magic = None
        self.description_magic = None

        if magic is not None and not disable_magic:
            self.mime_magic = magic.open(magic.MAGIC_MIME)
            if self.mime_magic.load() != 0:
                self.logger.warning("failed to load mime magic")
                self.mime_magic = None

            if not disable_description_magic:
                self.description_magic = magic.open(magic.MAGIC_NONE)
                if self.description_magic.load() != 0:
                    self.logger.warning("failed to load description magic")
                    self.description_magic = None

    def _make_connector(self):
        kwargs = {"deny_networks": self.deny_networks}
        if not self.ssl_verify:
            kwargs["verify_ssl"] = False
        return Connector(**kwargs)

    async def _get_basic_metadata(self, url, response, document):
        document.response = response
        try:
            document.buf = bytes(await response.content.readexactly(
                self.max_prefetch
            ))
        except asyncio.IncompleteReadError as exc:
            document.buf = exc.partial
        document.url = response.url
        document.original_url = url

        try:
            server_content_type = response.headers["Content-Type"]
        except KeyError:
            server_content_type = None

        if server_content_type is not None:
            server_content_type = mimeparse.parse_mime_type(
                server_content_type
            )

        if self.mime_magic is not None and document.buf is not None:
            local_content_type = self.mime_magic.buffer(document.buf)
        else:
            local_content_type = None

        if local_content_type is not None:
            local_content_type = mimeparse.parse_mime_type(local_content_type)

        document.mime_type = local_content_type or server_content_type

        if server_content_type is not None:
            document.encoding = server_content_type[2].get("charset")

        if document.encoding is None and local_content_type is not None:
            document.encoding = local_content_type[2].get("charset")

        if self.description_magic is not None:
            document.human_readable_type = self.description_magic.buffer(
                document.buf
            )

        if len(document.buf) < self.max_prefetch:
            self.logger.debug("exact size available (%d < %d)",
                              len(document.buf),
                              self.max_prefetch)
            document.size = len(document.buf)
        else:
            self.logger.debug("exact size unavailable (%d >= %d)",
                              len(document.buf),
                              self.max_prefetch)
            try:
                approx_size = int(response.headers["Content-Length"])
                approx_size_mode = \
                    handlers.SizeApproximation.ANNOUNCED_BY_SERVER
            except (KeyError, ValueError, TypeError):
                self.logger.debug(
                    "failed to understand Content-Length header",
                    exc_info=True
                )
                approx_size = len(document.buf)
                approx_size_mode = handlers.SizeApproximation.GREATER_THAN
            document.size = approx_size
            document.size_approximation = approx_size_mode

    async def _read_document(self, url, http_session):
        ""
        async with http_session.get(url) as response:
            document = handlers.Document()
            await self._get_basic_metadata(url, response, document)

            for handler in self.handlers:
                try:
                    await handler(document, self, http_session)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.logger.exception("handler %r failed at %r",
                                          handler, url)

            # handlers which download the full thing are supposed to update
            # the size_approximation
            if document.size_approximation != handlers.SizeApproximation.EXACT:
                self.logger.debug("closing connection to save bandwidth")
                response.close()

            return document

    async def read_document(self, url, http_session=None):
        ""
        if http_session is None:
            with self.make_session() as session:
                return (await self.read_document(url, http_session=session))

        return (await self._read_document(url, http_session=http_session))

    def make_session(self):
        return aiohttp.ClientSession(
            connector=self._make_connector(),
            headers={"User-Agent": self.user_agent}
        )


URL_RE = re.compile(
    r"([<\(\[\{{](?P<url_paren>{url})[>\)\]\}}]|(\W)(?P<url_nonword>{url})\3|(?P<url_name>{url}))".format(  # noqa:E501
        url=r"https?://\S+",
    ),
    re.I,
)


def default_url_finder(s: str) -> typing.Iterable[str]:
    for match in URL_RE.finditer(s):
        _, url = next(iter(filter(
            lambda x: x[1],
            match.groupdict().items()
        )))
        if '(' in url:
            url = url.rstrip(",>")
        else:
            url = url.rstrip(",)>")
        yield url


class URLLookup(aiofoomodules.handlers.AbstractHandler):
    def __init__(
            self,
            url_processor,
            *,
            timeout=timedelta(seconds=5),
            skip_keyword="@shutup",
            response_formatter=CompactResponseFormatter(),
            url_finder=default_url_finder,
            max_urls_per_post=5,
            silent_reject=False,
            **kwargs):
        super().__init__(**kwargs)

        self.logger = logging.getLogger(".".join([
            type(self).__module__,
            type(self).__qualname__,
        ]))

        self.url_processor = url_processor
        self.skip_keyword = skip_keyword
        self.formatter = response_formatter
        self.max_urls_per_post = max_urls_per_post
        self.timeout = timeout
        self.url_finder = url_finder
        self.silent_reject = silent_reject

    async def process_url(self, ctx, message, session, url, disambiguate):
        ""
        document = await self.url_processor.read_document(
            url,
            http_session=session
        )

        if disambiguate:
            disambiguator = str(url)
        else:
            disambiguator = None

        response_messages = self.formatter.format_response(
            document,
            disambiguator
        )

        return response_messages

    def _format_exc(self, exc):
        if isinstance(exc, aiohttp.ClientConnectorError):
            if exc.errno:
                return os.strerror(exc.errno)
        elif isinstance(exc, aiohttp.ClientError):
            return str(exc)
        return "internal error"

    async def process_urls(self, ctx, message, urls):
        ""
        async with self.url_processor.make_session() as session:
            futures = [
                asyncio.ensure_future(
                    asyncio.wait_for(
                        self.process_url(ctx, message, session, url,
                                         disambiguate=len(urls) > 1),
                        timeout=self.timeout.total_seconds(),
                    )
                )
                for url in urls
            ]
            await asyncio.wait(futures, return_when=asyncio.ALL_COMPLETED)
            for fut in futures:
                if fut.exception():
                    exc = fut.exception()
                    ctx.reply("request error: {}".format(
                        self._format_exc(exc)
                    ))
                    continue

                for line in fut.result():
                    ctx.reply(line, use_nick=False)

    async def reject(self, ctx, why):
        ctx.reply("won’t look that up: {}".format(why))

    def analyse_message(self, ctx, message):
        body = get_simple_body(message)
        if self.skip_keyword in body:
            return

        seen = set()
        urls = []
        for line in body.splitlines():
            line = line.strip()
            if line.startswith(">"):
                continue
            for url in self.url_finder(body):
                if url in seen:
                    continue
                seen.add(url)
                urls.append(url)

        if self.max_urls_per_post is not None:
            if len(urls) > self.max_urls_per_post:
                if not self.silent_reject:
                    yield self.reject(
                        ctx,
                        "too many URLs (use at most {})".format(
                            self.max_urls_per_post
                        ),
                    )
                return

        if urls:
            yield self.process_urls(ctx, message, urls)
