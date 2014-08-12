import abc
import functools
import logging
import re
import subprocess

try:
    import magic
except ImportError:
    magic = None

import html.parser
from bs4 import BeautifulSoup

import lxml.etree as etree

logger = logging.getLogger(__name__)

def guess_encoding(buf, authorative=None):
    encoding = authorative or "utf-8"
    while True:
        try:
            return buf.decode(encoding), encoding
        except LookupError as err:
            raise ValueError(str(err))
        except UnicodeDecodeError as err:
            pass
        encoding = {
            authorative: "utf-8",
            "utf-8": "latin-1",
            "latin-1": None
        }[encoding]
        if encoding is None:
            # let it raise
            buf.decode(authorative or "utf-8")


@functools.total_ordering
class Accept(object):
    def __init__(self, mime, q=1.0):
        self.mime = mime
        self.q = q

    def __le__(self, other):
        try:
            if self.q == other.q:
                return self.mime <= other.mime
            else:
                return self.q <= other.q
        except AttributeError as err:
            return NotImplemented

    def __lt__(self, other):
        try:
            if self.q == other.q:
                return self.mime < other.mime
            else:
                return self.q < other.q
        except AttributeError as err:
            return NotImplemented

    def __eq__(self, other):
        try:
            return self.q == other.q and self.mime == other.mime
        except AttributeError as err:
            return NotImplemented

    def __str__(self):
        return "{0};q={1:.1f}".format(self.mime, self.q)

class Document:
    mime_type = None
    human_readable_type = None
    title = None
    description = None
    size = None
    encoding = None
    url = None

    override_format = None

    def __init__(self):
        super().__init__()
        self.errors = []

class DocumentParser(metaclass=abc.ABCMeta):
    def __init__(self, accepts, **kwargs):
        super().__init__(**kwargs)
        self.accepts = list(accepts)

    @abc.abstractmethod
    def fetch_metadata_into(self, metadata):
        """
        Complete the metadata on the given *metadata* object, using the
        :attr:`Document.buf` buffer containing an excerpt of the
        document. The implementation may use any attributes already set in the
        document, most notably :attr:`Document.encoding` and
        :attr:`Document.mime_type`, although these are not guaranteed to be
        non-:data:`None`.

        Return :data:`True` if metadata acquisition was entirely successful,
        :data:`False` otherwise (other plugins may take over then).

        .. note::

           Implementations must only override attributes which are set to
           :data:`None`, as they might being called to supplement the object
           with additional metadata, except if it *certainly* knows that this
           information is wrong (as e.g. possible by brute-force decoding and
           figuring out the actual :attr:`Document.encoding` value).

        """

class PlainText(DocumentParser):
    """
    Possibly show a small plain text object. If the text is too long to be
    shown, handling is passed on to different plugins.
    """

    def __init__(self,
                 max_excerpt_length=256,
                 q=0.9):
        super().__init__([
            Accept("text/plain", q)
        ])

        self.max_excerpt_length = max_excerpt_length

    def fetch_metadata_into(self, metadata):
        if len(metadata.buf) > self.max_excerpt_length:
            return False

        try:
            text, encoding = guess_encoding(
                metadata.buf,
                metadata.encoding)
        except ValueError as err:
            return False

        metadata.title = text
        metadata.description = text
        metadata.encoding = encoding
        metadata.human_readable_type = "plain text"

        return True


class HTML(DocumentParser):
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

    def __init__(self,
                 accepts=[
                     Accept("text/html", 1.0),
                     Accept("application/xhtml+xml", 0.9)
                 ],
                 description_blacklist=[],
                 **kwargs):
        super().__init__(list(accepts), **kwargs)
        self.description_blacklist = frozenset(description_blacklist)

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
            if node.get("name").lower() == "description":
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

    def fetch_metadata_into(self, metadata):
        if metadata.mime_type is not None and (
                not ("html" in metadata.mime_type
                     or "xml" in metadata.mime_type)):
            return False

        buffer_len = len(metadata.buf)

        if metadata.encoding is None:
            metadata.encoding = self.detect_encoding(metadata.buf)

        contents = None
        title = None
        description = None
        if metadata.mime_type != "text/html":
            # try xhtml
            try:
                tree = etree.fromstring(metadata.buf)
                title, description = self._parse_xhtml(tree)
            except ValueError as err:
                metadata.errors.append(err)
                logger.warn(err)

        if title is None and description is None:
            # try plain html
            try:
                contents, encoding = guess_encoding(
                    metadata.buf,
                    metadata.encoding)
            except ValueError as err:
                # we have to fail hard here, no way out
                metadata.errors.append(err)
                logger.warn(err)
                return False

            try:
                tree = BeautifulSoup(contents)
            except html.parser.HTMLParseError:
                pass
            else:
                try:
                    title, description = self._parse_html(tree)
                except ValueError as err:
                    pass

        if buffer_len < metadata.size or (
                title is None and description is None):
            title, description = self._parse_heuristic(contents)

        if title is not None:
            metadata.title = metadata.title or title
            if metadata.url_parsed.hostname in self.description_blacklist:
                metadata.description = ""
            else:
                metadata.description = metadata.description or description
            metadata.human_readable_type = "html document"

            return True

        return False


class File(DocumentParser):
    def __init__(self,
                 file_binary="file",
                 q=0.1,
                 **kwargs):
        super().__init__(
            [
                Accept("*/*", q)
            ],
            **kwargs)
        self.file_binary = file_binary

        self.magic = None
        if magic:
            self.magic = magic.open(magic.MAGIC_NONE)
            if self.magic.load() != 0:
                self.magic = None

    def fetch_metadata_into(self, metadata):
        if self.magic:
            metadata.human_readable_type = self.magic.buffer(metadata.buf)
        else:
            process = subprocess.Popen(
                [self.file_binary,
                 "-",
                 "-b"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
            output, error = process.communicate(metadata.buf)

            metadata.human_readable_type = output.decode().strip()

        return False
