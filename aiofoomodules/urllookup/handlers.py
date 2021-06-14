import abc
import logging
import html.parser
import re

from bs4 import BeautifulSoup

import lxml.etree as etree

from enum import Enum

from aiofoomodules.utils import guess_encoding


class SizeApproximation(Enum):
    EXACT = 0
    GREATER_THAN = 1
    ANNOUNCED_BY_SERVER = 2


class Document:
    mime_type = None
    human_readable_type = None
    title = None
    description = None
    size = None
    size_approximation = SizeApproximation.EXACT
    encoding = None
    url = None
    original_url = None
    buf = None
    response = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.errors = []


class AbstractHandler(metaclass=abc.ABCMeta):
    def __init__(self, *, logger=None, **kwargs):
        super().__init__(**kwargs)
        if logger is not None:
            self.logger = logger
        else:
            self.logger = logging.getLogger(".".join([
                type(self).__module__,
                type(self).__qualname__,
            ]))

    @abc.abstractmethod
    async def __call__(self, document, processor, session):
        pass


class HTMLHandler(AbstractHandler):
    # XXX: before anyone shrieks in terror: we only use this if proper (X)HTML
    # parsing fails.

    title_re = re.compile(
        r"<\s*(\w+:)?title\s*>(.*?)<\s*/(\w+:)?title\s*>",
        re.S)
    meta_re = re.compile(
        r"<\s*(\w+:)?meta\s+(.*?)/?\s*>",
        re.S)

    xhtml_ns = "http://www.w3.org/1999/xhtml"
    xhtml_title = "{{{0}}}title".format(xhtml_ns)
    xhtml_meta = "{{{0}}}meta".format(xhtml_ns)

    charset_re = re.compile(
        br"""charset\s*=\s*("([^"]+?)"|'([^']+?)'|([^"']+))""")

    def __init__(self, *,
                 extract_description=True,
                 logger=None,
                 **kwargs):
        super().__init__(logger=logger, **kwargs)
        self._extract_description = extract_description

    def _should_extract_description(self, document):
        if self._extract_description is True:
            return True

        # TODO: add more match options

        return False

    def _parse_heuristic(self, contents):
        match = self.title_re.search(contents)
        if match:
            return match.group(2), ""
        else:
            return None, ""

    def _parse_xhtml(self, tree):
        try:
            title = next(tree.iter(self.xhtml_title)).text
        except StopIteration:
            title = None

        description = ""
        for node in tree.iter(self.xhtml_meta):
            if node.get("name", "").lower() == "description":
                description = node.get("content")
                break

        return title, description

    def _parse_html(self, tree):
        tag = tree.find("title")
        if not tag:
            title = None
        else:
            title = tag.text

        tag = tree.find("meta", attrs={"name": "description"})
        if not tag:
            descr = ""
        else:
            descr = tag["content"]

        return title, descr

    @classmethod
    def detect_encoding(cls, buf):
        m = cls.charset_re.search(buf)
        if m is not None:
            groups = m.groups()
            encoding_buffer = (groups[1] or groups[2] or groups[3])
            return encoding_buffer.decode()

        return None

    async def __call__(self, document, processor, session):
        if document.mime_type is not None:
            if document.mime_type[:2] not in [
                    ("text", "html"),
                    ("application", "xhtml+xml"),
                    ("application", "xml"),
                    ("text", "xml")]:
                self.logger.debug("skipping document with %r mime type",
                                  document.mime_type)
                return

        if document.encoding is None:
            document.encoding = self.detect_encoding(document.buf)

        contents = None
        title = None
        description = None

        if document.mime_type[:2] != ("text", "html"):
            # try xml
            try:
                document.xml_tree = etree.fromstring(document.buf)
                data = self._parse_xhtml(document.xml_tree)
            except (ValueError, etree.XMLSyntaxError) as err:
                document.errors.append(err)
                self.logger.warning(
                    "failed to parse as XHTML (content type is %r)",
                    document.mime_type,
                    exc_info=True)
            else:
                if data is None:
                    # not a XHTML document
                    return
                title, description = data

        if title is None and description is None:
            try:
                contents, encoding = guess_encoding(
                    document.buf,
                    document.encoding,
                )
            except ValueError as err:
                # no way out
                document.errors.append(err)
                self.logger.warning("failed to guess encoding", exc_info=True)
                return False

            document.encoding = encoding

            try:
                document.html_tree = BeautifulSoup(contents, "lxml")
            except html.parser.HTMLParser:
                pass
            else:
                title, description = self._parse_html(document.html_tree)

        if len(document.buf) < document.size or (
                title is None and description is None):
            title, description = self._parse_heuristic(contents)

        if description is not None:
            description = description.strip()
            if not description:
                description = None

        if title is not None:
            document.title = document.title or title
            if self._should_extract_description(document):
                document.description = document.description or description
            document.human_readable_type = "website"


class HandlerGroup(AbstractHandler):
    """
    A handler group is execute in the order of declaration.

    However, after the first handler returns a True result, the other handlers
    in the handler group are skipped.

    This can be used if one handler is more specific than other handlers, but
    both would normally match.

    It returns :data:`True` itself in that case. If no handler returns
    :data:`True`, :data:`None` is returned.
    """

    def __init__(self, children=[], *, logger=None, **kwargs):
        super().__init__(logger=logger, **kwargs)
        self._children = list(children)

    async def __call__(self, document, processor, session):
        for handler in self._children:
            result = await handler(document, processor, session)
            if result:
                return True


class OpenGraphHandler(AbstractHandler):
    async def __call__(self, document, processor, session):
        if not hasattr(document, "html_tree"):
            return

        title_el = document.html_tree.find("meta", property="og:title")
        try:
            title = (title_el or {})["content"]
        except KeyError:
            return

        description_el = document.html_tree.find("meta",
                                                 property="og:description")
        description = (description_el or {}).get("content")

        document.title = title
        document.description = description or document.description
        return True


class TweetHandler(AbstractHandler):
    TWEET_URL_RX = re.compile(
        r"https?://(mobile\.)?twitter\.com/(?P<suffix>[^/]+/status/(?P<id>[0-9]+))"
    )

    def _compose_name(self, fullname, username):
        if username is None and fullname is None:
            return None
        if fullname is None:
            return username
        if username is None:
            return fullname
        return "{} ({})".format(fullname, username)

    def _extract_mobile(self, html_tree, tweet_id):
        for div in html_tree.find_all("div", class_="tweet-text"):
            if div.get("data-id") == tweet_id:
                target_div = div
                break
        else:
            # could not find tweet
            return

        attribution = target_div.find_next("div", class_="attribution")
        fullname_span = attribution.find("span", class_="attr-fullname")
        username_span = attribution.find("span", class_="attr-username")

        name = self._compose_name(
            fullname_span.text if fullname_span is not None else None,
            username_span.text if username_span is not None else None,
        )

        return name, target_div

    def _extract_desktop(self, html_tree, tweet_id):
        for div in html_tree.find_all("div", class_="tweet"):
            if div["data-tweet-id"] == tweet_id:
                target_div = div
                break
        else:
            # could not find tweet
            return

        try:
            text_p = target_div.find_all("p", class_="tweet-text")[0]
        except ValueError:
            return None

        # fix up embedded picture URLs

        for link in text_p.find_all("a"):
            if link.get("data-pre-embedded") != "true":
                continue

            link.replace_with("")

        for img in div.find_all("img"):
            if "avatar" in img.get("class", []):
                continue
            text_p.append(" " + img.get("src", ""))

        fullname = div.get("data-name")
        username = div.get("data-screen-name")

        name = self._compose_name(fullname, username)

        return name, text_p

    async def __call__(self, document, processor, session):
        match = self.TWEET_URL_RX.match(str(document.url))

        if match is None:
            # don’t bother
            return

        new_url = "https://nitter.nixnet.services/" + match.groupdict()["suffix"]
        new_document = await processor.read_document(new_url, session)
        document.title = new_document.title
        document.description = new_document.description
        document.original_url = document.url
        document.url = new_url
        return True

        if not hasattr(document, "html_tree"):
            # can’t work with that
            return

        if match.group(1):
            # mobile link, rewrite to be non-mobile and retry
            url = str(document.url).replace("mobile.", "", 1)
            print("REWRITING:", document.url, "->", url)
            new_document = await processor.read_document(url, session)
            document.title = new_document.title
            document.description = new_document.description
            document.original_url = document.url
            document.url = url
            return True

        tweet_id = match.groupdict()["id"]

        info = self._extract_mobile(
            document.html_tree,
            tweet_id
        )
        if info is None:
            info = self._extract_desktop(
                document.html_tree,
                tweet_id
            )
        if info is None:
            return

        name, text_el = info

        for link in text_el.find_all("a"):
            replacement_url = link.get("data-url",
                                       link.get("data-expanded-url"))
            if replacement_url is not None:
                link.replace_with(replacement_url)

        if name is not None:
            document.title = "by {}".format(name)
        document.description = text_el.text.strip()
        document.human_readable_type = "tweet"

        return True


class PlainTextHandler(AbstractHandler):
    def __init__(self, max_length=360, **kwargs):
        super().__init__(**kwargs)
        self.max_length = max_length

    async def __call__(self, document, processor, session):
        if (document.mime_type is not None and
                document.mime_type[:2] != ("text", "plain")):
            return

        if len(document.buf) > self.max_length:
            return

        try:
            contents, encoding = guess_encoding(
                document.buf,
                document.encoding)
        except ValueError:
            return
        else:
            document.encoding = document.encoding

        contents = contents.strip()
        if not contents:
            return

        document.title = document.title or "short text"
        document.description = contents.strip()
