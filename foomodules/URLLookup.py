# encoding=utf-8
import re, functools, itertools, operator, time, math, os, socket
import urllib.request, urllib.response, urllib.error, urllib.parse
import heapq

import lxml.etree as ET

from fnmatch import fnmatch
from subprocess import check_output

from bs4 import BeautifulSoup

import foomodules.Base as Base

MAX_BUFFER = 1048576  # 1 MByte

def readMax(fileLike, maxLength, timeout=5, read_block_size=4096):
    start_time = time.time()
    buf = b''
    try:
        while len(buf) < maxLength:
            if time.time() - start_time >= timeout:
                return buf
            tmp = fileLike.read(min(read_block_size, maxLength - len(buf)))
            if len(tmp) == 0:
                return buf
            buf += tmp
    except Exception as err:
        print(err)
    return buf


def formatBytes(byteCount):
    suffixes = ["", "ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi", "Yi"]
    print(byteCount)
    dimension = min(int(math.log(byteCount, 1024)), len(suffixes)-1)
    suffix = suffixes[dimension]+"B"
    if dimension == 0:
        return "{0} {1}".format(byteCount, suffix)
    else:
        value = byteCount / (1 << (10*dimension))
        return "{0:.2f} {1}".format(value, suffix)


def guessEncoding(buf, authorative=None):
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
        print("guessing ... {0}".format(encoding))


whitespaceRE = re.compile("\s\s+")
def normalize(s, eraseNewlines=True):
    if eraseNewlines:
        s = s.replace("\n", " ").replace("\r", " ")
    matches = list(whitespaceRE.finditer(s))
    matches.reverse()
    for match in matches:
        s = s[:match.start()] + " " + s[match.end():]
    return s

control_character_filter = lambda x: ord(x) >= 32 or x == "\x0A" or x == "\x0D"
def cleanup_string(s):
    return "".join(filter(control_character_filter, s))


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


class HandlerBase(object):
    def __init__(self, accepts, **kwargs):
        super().__init__(**kwargs)
        self.accepts = list(accepts)

    def formatResponses(self, responses, **kwargs):
        for i, line in enumerate(responses):
            fmtLine = line.format(**kwargs).strip()
            if len(fmtLine) == 0 and i > 0:
                continue
            yield fmtLine


class PlainText(HandlerBase):
    def __init__(self,
            maxLength=256,
            shortResponseFormats=[
                "short plain text ({encoding}): {text}"
            ],
            defaultResponseFormats=[
                "plain text, {encoding}"
            ],
            errorResponseFormats=[
                "plain text, {encoding}, {error}"
            ],
            q=0.9,
            **kwargs):
        super().__init__([
            Accept("text/plain", q),
        ], **kwargs)
        self.maxLength = maxLength
        self.shortResponseFormats = shortResponseFormats
        self.defaultResponseFormats = defaultResponseFormats
        self.errorResponseFormats = errorResponseFormats

    def processResponse(self, response, no_description=False):
        if len(response.buf) < self.maxLength:
            try:
                text, encoding = guessEncoding(response.buf, response.encoding)
            except (UnicodeDecodeError, ValueError) as err:
                return iter(self.formatResponses(self.errorResponseFormats,
                            error=err,
                            encoding=response.encoding or "unknown"))
            return iter(self.formatResponses(self.shortResponseFormats,
                        text=text.strip(),
                        encoding=encoding))
        else:
            return iter(self.formatResponses(self.defaultResponseFormats,
                        encoding=response.encoding or "unknown"))


class HTMLDocument(HandlerBase):
    titleRE = re.compile("<\s*(\w+:)?title\s*>(.*?)<\s*/(\w+:)?title\s*>", re.S)
    metaRE = re.compile("<\s*(\w+:)?meta\s+(.*?)/?\s*>", re.S)

    xhtmlNS = "http://www.w3.org/1999/xhtml"
    xhtmlTitle = "{{{0}}}title".format(xhtmlNS)
    xhtmlMeta = "{{{0}}}meta".format(xhtmlNS)

    charsetRE = re.compile(
            br"""charset\s*=\s*("([^"]+?)"|'([^']+?)'|([^"']+))""")

    def __init__(self,
            descriptionBlacklist=[],
            responseFormats=[
                "html document: {title}",
                "{description}"
            ],
            **kwargs):
        super().__init__([
            Accept("text/html", 1.0),
            Accept("application/xhtml+xml", 0.9)
        ], **kwargs)
        self.responseFormats = responseFormats
        self.descriptionBlacklist = frozenset(descriptionBlacklist)

    def _heuristic(self, contents):
        titleMatch = self.titleRE.search(contents)
        if titleMatch:
            return titleMatch.group(2), ""
        else:
            return None, ""

    def _xhtml(self, tree):
        try:
            title = next(tree.iter(self.xhtmlTitle)).text
        except StopIteration:
            title = None

        description = ""
        for node in tree.iter(self.xhtmlMeta):
            if node.get("name").lower() == "description":
                description = node.get("content")
                break
        return title, description

    def _html(self, tree):
        tag = tree.find("title")
        if not tag:
            title = None
        else:
            title = tag.text.strip()
        tag = tree.find("meta", attrs={"name": "description"})
        if not tag:
            descr = ""
        else:
            descr = tag["content"].strip()

        if title is None:
            raise ValueError("no title")

        return title, descr

    def processResponse(self, response, no_description=False):
        bufferLen = len(response.buf)

        if response.encoding is None:
            # HTML spec
            m = self.charsetRE.search(response.buf)
            if m is not None:
                groups = m.groups()
                encoding = groups[1] or groups[2] or groups[3]
                response.encoding = encoding.decode("ascii")

        if bufferLen < response.contentLength:
            try:
                contents, _ = guessEncoding(response.buf, response.encoding)
            except Exception as err:
                return [str(err)]
            title, description = self._heuristic(contents)

        if response.mimeType == "text/html":
            try:
                contents, _ = guessEncoding(response.buf, response.encoding)
            except Exception as err:
                return [str(err)]
            try:
                tree = BeautifulSoup(contents)
            except html.parser.HTMLParseError:
                title, description = self._heuristic(contents)
            else:
                try:
                    title, description = self._html(tree)
                except:
                    title, description = self._heuristic(contents)
        else:
            tree = ET.ElementTree(ET.XML(response.buf))
            title, description = self._xhtml(tree)

        if title is None:
            title = "⟨unknown title⟩"
        title = cleanup_string(normalize(title, eraseNewlines=True))
        if description is None:
            description = ""
        else:
            # actually, amazon sometimes sends 0x1a characters, which is quite
            # odd and leads to not-wellformed kicks
            description = cleanup_string(normalize(description, eraseNewlines=True))

        if no_description or response.url.hostname in self.descriptionBlacklist:
            description = ""

        return iter(self.formatResponses(self.responseFormats,
                title=title or "Untitled Document",
                description=description))


class UnixFile(HandlerBase):
    def __init__(self,
            workingData="/tmp/foobot-working-data",
            **kwargs):
        super().__init__([
            Accept("*/*", 0.2)
        ], **kwargs)
        self.workingData = workingData

    def processResponse(self, response, no_description=True):
        out = open(self.workingData, "wb")
        out.write(response.buf)
        out.close()
        result = check_output(["/usr/bin/file", "-b", self.workingData]).decode().strip()
        os.unlink(self.workingData)
        yield result


class URLLookupError(Exception):
    pass


class URLLookup(Base.MessageHandler):
    urlRE = re.compile("(https?)://[^/>\s]+(/[^>\s]+)?", re.I)
    charsetRE = re.compile("charset=([^\s]+)", re.I)

    def __init__(self,
            denyPrivate=True,
            timeout=5,
            setAbort=True,
            noBotKeyword=None,
            handlers={},
            responseFormats=["{time:.2f} s, {size}, {plugin}"],
            userAgent="undisclosed",
            maxBuffer=MAX_BUFFER,
            showRedirects=False,
            cache_limit=32,
            no_description_keyword=None,
            **kwargs):
        super().__init__(**kwargs)
        if cache_limit > 0:
            self.cache = {}
            self.cache_heap = []
        self.cache_limit = cache_limit
        self.setAbort = setAbort
        self.denyPrivate = denyPrivate
        self.timeout = timeout
        self.noBotKeyword = noBotKeyword
        self.no_description_keyword = no_description_keyword
        self.handlers = handlers
        self.responseFormats = responseFormats
        self.userAgent = userAgent
        self.maxBuffer = maxBuffer
        self.showRedirects = showRedirects

        annotatedAccepts = [[(accept, handler) for accept in handler.accepts]
                            for handler in self.handlers]
        accepts = sorted(itertools.chain(*annotatedAccepts),
                        reverse=True, key=operator.itemgetter(0))
        self.acceptHeader = ", ".join(map(str,
                                map(operator.itemgetter(0), accepts)))
        self.mimeMap = {}
        globMap = {}
        for accept, handler in reversed(accepts):  # from low to high q
            mime = accept.mime
            if "*" in mime:
                globMap[mime] = handler
            else:
                self.mimeMap[mime] = handler
        self.globMap = sorted(((key, value) for key, value in globMap.items()),
                              reverse=True, key=operator.itemgetter(0))

    def bufferResponse(self, response, info):
        try:
            contentLength = int(info["Content-Length"])
        except (KeyError, TypeError):
            contentLength = None
        except ValueError as err:
            raise URLLookupError("Bad Content-Length header: {0}".format(err))
        response.contentLength = contentLength

        buf = readMax(response, min(self.maxBuffer,
                                    response.contentLength or self.maxBuffer))
        if len(buf) < self.maxBuffer and response.contentLength is None:
            response.contentLength = len(buf)  # good guess at least ;)
        response.buf = buf

    def annotateResponse(self, response):
        info = response.info()
        try:
            mimeType, sep, mimeInfo = info["Content-Type"].partition(";")
            m = self.charsetRE.search(mimeInfo)
            if m is not None:
                encoding = m.group(1)
            else:
                encoding = None
            mimeType = mimeType.strip()
        except KeyError:
            mimeType = "unknown/unknown"
            encoding = None

        try:
            response.handler = self.mimeMap[mimeType]
        except KeyError:
            print("fallback")
            for glob, handler in self.globMap:
                if fnmatch(mimeType, glob):
                    response.handler = handler
                    break
            else:
                raise URLLookupError("No handler for MIME type: {0}")

        response.mimeType = mimeType
        response.encoding = encoding
        self.bufferResponse(response, info)
        response.url = urllib.parse.urlparse(response.geturl())

    def _process_uncached_url(self, url, no_description=False):
        request = urllib.request.Request(url, headers={
            "User-Agent": self.userAgent,
            "Accept": self.acceptHeader
        })
        try:
            startTime = time.time()
            response = urllib.request.urlopen(request, timeout=self.timeout)
            timeTaken = time.time() - startTime
        except socket.timeout:
            raise URLLookupError("Timed out")
        except urllib.error.URLError as err:
            raise URLLookupError(err.reason)
        except Exception as err:
            raise URLLookupError(type(err).__name__)
        try:

            newURL = response.geturl()
            if newURL != url and self.showRedirects:
                yield "→ <{0}>".format(newURL)

            self.annotateResponse(response)

            if response.contentLength is not None:
                sizeFormatted = formatBytes(response.contentLength)
            else:
                sizeFormatted = "unknown size"

            responseIter = iter(response.handler.processResponse(response, no_description=no_description))
            firstLine = next(responseIter)
            for line in self.responseFormats:
                yield line.format(time=timeTaken,
                        size=sizeFormatted,
                        plugin=firstLine)
            for line in responseIter:
                yield line
        finally:
            response.close()
            del response.buf
            del response

    def processURL(self, url, no_cache=False, no_description=False):
        use_cache = not no_cache and self.cache_limit
        if use_cache:
            cache_url_parsed = list(urllib.parse.urlparse(url)[:5]) + [""]
            cache_url = urllib.parse.urlunparse(cache_url_parsed)
            try:
                line_iter = iter(self.cache[cache_url])
                first_line = next(line_iter)
                yield first_line + " [C]"
                for line in line_iter:
                    yield line
                return
            except KeyError:
                pass

        lines = self._process_uncached_url(url, no_description=no_description)
        if use_cache:
            while len(self.cache) >= self.cache_limit:
                timestamp, cached_url = heapq.heappop(self.cache_heap)
                del self.cache[cached_url]
            heapq.heappush(self.cache_heap, (time.time(), cache_url))
            lines = list(lines)
            self.cache[cache_url] = lines
        for line in lines:
            yield line

    def __call__(self, msg, errorSink=None):
        contents = msg["body"]
        if self.noBotKeyword and contents.startswith(self.noBotKeyword):
            return
        no_description = self.no_description_keyword is not None and contents.startswith(self.no_description_keyword)

        matchFound = False
        for match in self.urlRE.finditer(contents):
            matchFound = True
            try:
                for line in self.processURL(match.group(0), no_description=no_description):
                    self.reply(msg, line)
            except URLLookupError as err:
                self.reply(msg, "Could not open URL: {0!s}".format(err))

        return matchFound and self.setAbort

