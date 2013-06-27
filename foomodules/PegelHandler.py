# encoding=utf-8

import re

from foomodules.URLLookup import HTMLDocument, guessEncoding

import html.parser
from bs4 import BeautifulSoup

class PegelDocument(HTMLDocument):
    pegel_re = re.compile("https?://www.umwelt.sachsen.de/de/wu/umwelt/lfug/lfug-internet/hwz/MP/[0-9]+/index.html")

    def __init__(self,
            responseFormats=[
                "pegel document: {title}",
                "{description}"
            ],
            level_format="Pegel: {level} cm",
            Q_format="Durchfluss: {Q} m³/s",
            description_ellipsis="[…]",
            **kwargs):
        super().__init__(
            descriptionBlacklist=[],
            responseFormats=responseFormats,
            url_patterns=[self.pegel_re],
            **kwargs)
        self._level_format = level_format
        self._Q_format = Q_format

    def _html(self, tree):
        title = tree.select("span.titel")[0].text
        foo = tree.select("table tr > td > table.rahmen tr")
        tr = foo[1]
        tds = tr.select("td")

        try:
            level = float(tds[1].text.replace(",", "."))
        except ValueError:
            level = None

        try:
            Q = float(tds[2].text.replace(",", "."))
        except ValueError:
            Q = None

        items = []
        if level is not None:
            items.append(self._level_format.format(level=level))
        if Q is not None:
            items.append(self._Q_format.format(Q=Q))

        return title, "; ".join(items)

    def processResponse(self, response, no_description=False):
        bufferLen = len(response.buf)

        if response.encoding is None:
            # HTML spec
            m = self.charsetRE.search(response.buf)
            if m is not None:
                groups = m.groups()
                encoding = groups[1] or groups[2] or groups[3]
                response.encoding = encoding.decode("ascii")

        buf = response.buf + response.read()

        try:
            contents, _ = guessEncoding(response.buf, response.encoding)
        except Exception as err:
            return [str(err)]
        try:
            tree = BeautifulSoup(contents)
        except html.parser.HTMLParseError:
            title, description = self._heuristic(contents)
        else:
            #~ try:
            title, description = self._html(tree)
            #~ except:
                #~ title, description = self._heuristic(contents)

        return self.response_from_info(
            title, description, response,
            no_description=False)
