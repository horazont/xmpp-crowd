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


def opengraph_handler(metadata):
    if not metadata.mime_type == "text/html":
        return None

    # generic HTML parser to look for opengraph protocol images

    soup = BeautifulSoup(metadata.buf)

    kwargs = {}

    img_node = soup.head.find("meta", property="og:image")
    if img_node is not None:
        img_url = img_node["content"]
        try:
            img_data, img_mime_type = _fetch_url(img_url)
        except DownloadError:
            return {}
        kwargs.update({
            "image_url": img_url,
            "image_mime_type": img_mime_type,
            "image_buffer": img_data
        })

    descr_node = soup.head.find("meta", property="og:description")
    if descr_node is not None:
        kwargs["description"] = descr_node["content"] or None
    else if img_node is not None:
        # force description to None, to avoid nonsense description leaking from
        # the default handler
        kwargs["description"] = None

    ret = default_handler(metadata)
    ret.update(kwargs)

    return ret
