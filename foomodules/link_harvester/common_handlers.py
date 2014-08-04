import logging
import re
import socket
import urllib
import http.client
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
WURSTBALL_RE = re.compile(r"^https?://(www\.)?wurstball\.de/[0-9]+/")


class DownloadError(Exception):
    pass


def _fetch_url(url):
    try:
        response = urllib.request.urlopen(url, timeout=5)
        data = response.read()
    except (socket.timeout,
            urllib.error.URLError,
            urllib.error.HTTPError) as err:
        logger.warn("Could not fetch url: {}".format(err))
        raise DownloadError from err

    mime_type = response.getheader("Content-Type")
    return data, mime_type


def default_handler(metadata):
    return {key: getattr(metadata, key) for key in
            ["original_url", "url", "title", "description",
             "human_readable_type", "mime_type"]}


def wurstball_handler(metadata):
    if not WURSTBALL_RE.match(metadata.url):
        return None

    ret = default_handler(metadata)

    soup = BeautifulSoup(metadata.buf)
    img_url = soup.find(id="content-main").img["src"]

    try:
        img_data, mime_type = _fetch_url(img_url)
    except DownloadError:
        return ret

    ret.update({"image_mime_type": mime_type,
                "image_buffer": img_data,
                "image_url": img_url,
                "title": None,
                "description": None})

    return ret


def image_handler(metadata):
    if not metadata.mime_type.startswith("image/"):
        return None

    ret = default_handler(metadata)

    try:
        img_data = metadata.buf + metadata.response.read()
    except http.client.IncompleteRead as err:
        logger.warn("Could not download image: {}".format(err))
        return ret

    ret.update({"image_mime_type": metadata.mime_type,
                "image_buffer": img_data,
                "image_url": metadata.url})

    return ret


def soup_handler(metadata):
    if not metadata.mime_type == "text/html":
        return None

    # Soups are difficult to detect as users can CNAME their own domain
    # names to their foo.soup.io domain, e.g. soup.leonweber.de.  Hence
    # we have to parse the HTML in order to determine whether this is a
    # soup site.  This makes us a rather expensive handler, so it should
    # be run as late as possible.

    bs = BeautifulSoup(metadata.buf)

    # check for soup icon
    try:
        if bs.find("div", id="soup").a["href"] != "http://www.soup.io":
            return None
    except (AttributeError, KeyError):
        return None

    # make sure there's a "back to front page" link (to ensure this
    # a page with a single post)
    if bs.body.find("div", id="maincontainer").find(
            "a", class_="back") is None:
        return None

    try:
        og_type = bs.find("meta", property="og:type")["content"]
    except KeyError:
        return None

    if og_type == "image":
        subhandler = _soup_image_handler
    elif og_type == "article":
        subhandler = _soup_article_handler
    else:
        return None

    kwargs = subhandler(bs)
    ret = default_handler(metadata)
    ret.update(kwargs)

    return ret


def _soup_image_handler(soup):
    img_url = soup.head.find("meta", property="og:image")["content"]

    try:
        img_data, img_mime_type = _fetch_url(img_url)
    except DownloadError:
        return {}

    desc = soup.head.find("meta", property="og:description")["content"] or None

    return {"description": desc,
            "image_url": img_url,
            "image_mime_type": img_mime_type,
            "image_buffer": img_data}


def _soup_article_handler(soup):
    # stub function, might later want to parse the html article, e.g.
    # <br> ⇒ \n\n, <ul><li> ⇒ •, etc.  Maybe even extract <img>s…

    desc = soup.head.find("meta", property="og:description")["content"] or None

    return {"description": desc}
