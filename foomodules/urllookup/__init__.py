import logging
import math
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from datetime import datetime, timedelta

import foomodules.Base as Base

from .parsers import *

logger = logging.getLogger(__name__)

def read_up_to(f, max_length, timeout=5, read_block_size=4096):
    start_time = time.time()
    parts = []
    remaining = max_length
    try:
        while remaining > 0:
            if time.time() - start_time >= timeout:
                break
            read_part = f.read(min(read_block_size, remaining))
            if len(read_part) == 0:
                break
            parts.append(read_part)
            remaining -= len(read_part)
    except Exception as err:
        logger.warn("%s", err)

    return b"".join(parts)

def ellipsize_text(text, max_len, ellipsis="[…]"):
    if len(text) < max_len:
        return text
    part_len = max_len // 2
    return text[:part_len] + ellipsis + text[-part_len:]

def format_bytes(byte_count):
    suffixes = ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi", "Yi"]
    dimension = min(int(math.log(byte_count, 1024)), len(suffixes)-1)
    suffix = suffixes[dimension]+"B"
    if dimension == 0:
        return "{0} {1}".format(byte_count, suffix)
    else:
        value = byte_count / (1 << (10*dimension))
        return "{0:.2f} {1}".format(value, suffix)


class URLLookupError(Exception):
    pass

class URLLookup(Base.MessageHandler):
    url_re = re.compile("(https?)://[^/>\s]+(/[^>\s]+)?", re.I)
    charset_re = re.compile("charset\s*=\s*([^\s]+)", re.I)


    def __init__(self,
                 deny_private=True,
                 timeout=5,
                 set_abort=True,
                 skip_keyword="@shutup",
                 handlers=[],
                 response_formatter=None,
                 user_agent="foobot/1.0",
                 max_buffer=1024**2,
                 pre_hooks=[],
                 post_hooks=[],
                 description_limit=360,
                 **kwargs):
        super().__init__(**kwargs)

        self.deny_private = deny_private
        self.timeout = timeout
        self.set_abort = set_abort
        self.skip_keyword = skip_keyword
        self.user_agent = user_agent
        self.max_buffer = max_buffer

        self.accept_header = ", ".join(
            str(accept)
            for handler in handlers for accept in handler.accepts
        )

        self._handlers = handlers or []
        self.pre_hooks = pre_hooks
        self.post_hooks = post_hooks
        self.response_formatter = response_formatter or self.default_formatter
        self.description_limit = description_limit

    def prepare_metadata(self, url, response):
        metadata = Document()
        headers = response.info()

        try:
            mime_type, _, mime_info = headers["Content-Type"].partition(";")
            m = self.charset_re.search(mime_info)
            if m is not None:
                metadata.encoding = m.group(1)

            metadata.mime_type = mime_type
        except (AttributeError, KeyError, TypeError) as err:
            pass

        try:
            content_length = int(headers["Content-Length"])
        except (KeyError, TypeError) as err:
            content_length = None
            logger.warn("%s", err)
        except ValueError as err:
            raise URLLookupError(
                "bad content-length header: {}".format(err)
            )

        metadata.size = content_length
        metadata.buf = read_up_to(
            response,
            self.max_buffer)

        if metadata.size is None:
            metadata.size = len(metadata.buf)

        metadata.url = url
        metadata.url_parsed = urllib.parse.urlparse(metadata.url)

        metadata.response = response

        return metadata

    def fill_metadata(self, metadata):
        for handler in self._handlers:
            finished = handler.fetch_metadata_into(metadata)
            if finished:
                break

    def document_from_url(self, msg_context, url):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": self.accept_header,
            }
        )

        try:
            start_time = datetime.utcnow()
            response = urllib.request.urlopen(
                request,
                timeout=self.timeout)
        except (socket.timeout,
                urllib.error.URLError,
                urllib.error.HTTPError) as err:
            raise URLLookupError(str("connection error")) from err
        except Exception as err:
            raise URLLookupError(str("unknown error")) from err

        try:
            url = response.geturl()
            metadata = self.prepare_metadata(url, response)
            time_taken = datetime.utcnow() - start_time

            for hook in self.pre_hooks:
                try:
                    hook(msg_context, metadata)
                except Exception as err:
                    logger.warn("while executing pre_hook: %s", err)

            self.fill_metadata(metadata)

            for hook in self.post_hooks:
                try:
                    hook(msg_context, metadata)
                except Exception as err:
                    logger.warn("while executing post_hook: %s", err)

        finally:
            response.close()

        metadata._lookup_time = time_taken
        metadata.title = (metadata.title or "").strip()
        metadata.description = (metadata.description or "").strip()

        return metadata

    def default_formatter(self, metadata):
        title = metadata.title or None
        description = metadata.description or None

        line = []
        line.append(
            "{:.1f} s".format(metadata._lookup_time.total_seconds()))
        if metadata.size is not None:
            line.append(format_bytes(metadata.size))
        if metadata.human_readable_type:
            line.append(metadata.human_readable_type)

        line = ", ".join(line)
        if metadata.title:
            line += ": "+metadata.title

        yield line
        if metadata.description is not None:
            yield ellipsize_text(metadata.description, self.description_limit)

    def format_reply_to_url(self, msg_context, url):
        try:
            metadata = self.document_from_url(msg_context, url)
        except URLLookupError as err:
            ctx = err.__context__
            cause = " ({})".format(ctx) if ctx is not None else ""
            yield "could not open url {url}: {err}{cause}".format(
                url=ellipsize_text(url, 64),
                err=err,
                cause=cause)
            return

        yield from self.response_formatter(metadata)

    def extract_urls(self, msg):
        return [
            match.group(0)
            for match in self.url_re.finditer(msg["body"])
        ]

    def __call__(self, msg, errorSink=None):
        contents = msg["body"].strip()
        if self.skip_keyword and contents.startswith(self.skip_keyword):
            return

        urls = self.extract_urls(msg)
        for i, url in enumerate(urls):
            prefix = "" if len(urls) == 1 else "{}. ".format(i+1)

            for line in self.format_reply_to_url(msg, url):
                self.reply(msg, prefix + line)

        return bool(urls) and self.set_abort
