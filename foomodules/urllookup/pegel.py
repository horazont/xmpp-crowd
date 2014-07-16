# encoding=utf-8
import html.parser
import logging
import re

from bs4 import BeautifulSoup

from . import parsers


logger = logging.getLogger(__name__)

class PegelDocument(parsers.DocumentParser):
    pegel_re = re.compile("https?://www.umwelt.sachsen.de/de/wu/umwelt/lfug/lfug-internet/hwz/MP/[0-9]+/index.html")

    def __init__(self,
                 level_format="Pegel: {level} cm",
                 Q_format="Durchfluss: {Q} m³/s",
                 **kwargs):
        super().__init__(accepts=[
                             parsers.Accept("text/html", 1.0)
                         ])
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

    def fetch_metadata_into(self, metadata):
        if not self.pegel_re.match(metadata.url):
            return False
        print("matched")

        buffer_len = len(metadata.buf)

        buf = metadata.buf + metadata.response.read()

        if metadata.encoding is None:
            metadata.encoding = parsers.HTML.detect_encoding(metadata.buf)

        try:
            contents, _ = parsers.guess_encoding(
                metadata.buf,
                metadata.encoding)
        except Exception as err:
            logger.warn(err)
            return False

        try:
            tree = BeautifulSoup(contents)
        except html.parser.HTMLParseError:
            return False
        else:
            title, description = self._html(tree)

        if not title or not description:
            return False

        metadata.human_readable_type = "pegel document"
        metadata.title = title
        metadata.description = description

        return True
