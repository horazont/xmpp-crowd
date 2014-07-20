import logging
import re
import socket
import urllib
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
WURSTBALL_RE = re.compile(r"^https?://(www\.)?wurstball\.de/[0-9]+/")


def default_handler(metadata):
    return {key: getattr(metadata, key) for key in
            ["original_url", "url", "title", "description",
             "human_readable_type"]}


def wurstball_handler(metadata):
    if not WURSTBALL_RE.match(metadata.url):
        return None

    ret = default_handler(metadata)

    soup = BeautifulSoup(metadata.buf)
    img_url = soup.find(id="content-main").img["src"]

    try:
        response = urllib.request.urlopen(img_url, timeout=5)
        img_data = response.read()
    except (socket.timeout,
            urllib.error.URLError,
            urllib.error.HTTPError) as err:
        logger.warn("Could not download Wurstball image: {}".format(err))
        return ret

    mime_type = response.getheader("Content-Type")

    ret.update({"image_mime_type": mime_type,
                "image_buffer": img_data,
                "image_url": img_url})

    return ret
