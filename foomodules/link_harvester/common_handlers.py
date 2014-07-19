import re
import socket
import urllib
from bs4 import BeautifulSoup


def default_handler(metadata):
    return {key: getattr(metadata, key) for key in
            ["original_url", "url", "title", "description",
             "human_readable_type"]}

def wurstball_handler(metadata):
    wurstball_re = re.compile("^http[s]://wurstball.de/[0-9]+/")

    if wurstball_re.match(metadata.url) is None:
        return None

    ret = default_handler(metadata)

    soup = BeautifulSoup(metadata.buf)
    img_url = soup.find(id="content-main").img["src"]

    try:
        response = urllib.request.urlopen(img_url, timeout=5)
        img_data = response.read()
    except (socket.timeout,
            urllib.error.URLError,
            urllib.error.HTTPError):
        return ret

    mime_type = response.getheader("Content-Type")

    ret.update({"image_mime_type": mime_type,
                "image_buffer": img_data,
                "image_url": img_url})

    return ret
