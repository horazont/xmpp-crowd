import logging
import re
import socket
import urllib
import http.client
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
WURSTBALL_RE = re.compile(r"^https?://(www\.)?wurstball\.de/[0-9]+/")

MAX_DOWNLOAD = 200*1024*1024  # 200 MiB


class DownloadError(Exception):
    pass


def _fetch_url(url, user_agent, referrer=None):
    headers = {
        "User-Agent": user_agent,
    }
    if referrer:
        headers["Referrer"] = referrer
    try:
        request = urllib.request.Request(url, headers=headers)
        response = urllib.request.urlopen(request, timeout=5)
        data = response.read(MAX_DOWNLOAD)
        if response.read(1):  # still more data
            raise DownloadError("over limit")
    except (socket.timeout,
            urllib.error.URLError,
            urllib.error.HTTPError) as err:
        logger.warn("Could not fetch url {!r}: {}".format(url, err))
        raise DownloadError from err

    mime_type = response.getheader("Content-Type")
    return data, mime_type


def _extract_og_tag(base_tag, tag_name):
    found = base_tag.find_next_sibling("meta", property=tag_name)
    if found is None:
        return None
    # reverse-check that the tag actually belongs to base
    actual_base = found.find_previous_sibling("meta",
                                              property=base_tag["property"])
    if actual_base is not base_tag:
        return None
    return found


def _extract_og_tag_contents(base_tag, tag_name, default=None):
    tag = _extract_og_tag(base_tag, tag_name)
    if tag is None:
        return default
    return tag["content"]


def _parse_og_video(root_tag):
    return {
        "video": root_tag["content"],
        "secure_url": _extract_og_tag_contents(
            root_tag,
            "og:video:secure_url"),
        "type": _extract_og_tag_contents(
            root_tag,
            "og:video:type"),
        "width": _extract_og_tag_contents(
            root_tag,
            "og:video:width"),
        "height": _extract_og_tag_contents(
            root_tag,
            "og:video:height"),
    }


def _parse_og_image(root_tag):
    return {
        "image": root_tag["content"],
        "width": _extract_og_tag_contents(
            root_tag,
            "og:image:width"),
        "height": _extract_og_tag_contents(
            root_tag,
            "og:image:height"),
    }


def _parse_opengraph(soup):
    objects = {}
    for tag in soup.head.find_all("meta", property="og:video"):
        objects.setdefault("videos", []).append(_parse_og_video(tag))
    for tag in soup.head.find_all("meta", property="og:image"):
        objects.setdefault("images", []).append(_parse_og_image(tag))
    return objects


def default_handler(metadata, user_agent=None):
    return {key: getattr(metadata, key) for key in
            ["original_url", "url", "title", "description",
             "human_readable_type", "mime_type"]}


def wurstball_handler(metadata, user_agent):
    if not WURSTBALL_RE.match(metadata.url):
        return None

    ret = default_handler(metadata)

    soup = BeautifulSoup(metadata.buf)
    img_url = soup.find(id="content-main").img["src"]

    try:
        img_data, mime_type = _fetch_url(img_url, user_agent,
                                         referrer=metadata.url)
    except DownloadError:
        return ret

    ret.update({"image_mime_type": mime_type,
                "image_buffer": img_data,
                "image_url": img_url,
                "title": None,
                "description": None})

    return ret


def imgur_handler(metadata, user_agent):
    if not metadata.url_parsed.netloc.endswith("imgur.com"):
        return None
    if not metadata.mime_type == "text/html":
        return None

    ret = opengraph_handler(metadata, user_agent)

    try:
        soup = BeautifulSoup(metadata.buf)
        ogdata = _parse_opengraph(soup)

        # first, find out if there are videos
        for item in ogdata.get("videos", []):
            try:
                if "shockwave-flash" in item["type"]:
                    continue
                url = item.get("secure_url", item["video"])
                type_ = item["type"]
            except KeyError:
                # something vital is missing, skip
                continue

            logger.debug("trying to fetch video from %r", url)

            try:
                video_data, mime_type = _fetch_url(url, user_agent,
                                                   metadata.url)
            except DownloadError:
                logger.warning("failed to fetch video from %r", url)
                continue

            ret.update({
                "image_mime_type": mime_type,
                "image_buffer": video_data,
                "image_url": url
            })
            return ret

    except:
        logger.exception("fubar")

    return None


def image_handler(metadata, user_agent):
    if not metadata.mime_type.startswith("image/"):
        return None

    ret = default_handler(metadata, user_agent)

    try:
        img_data = metadata.buf + metadata.response.read()
    except http.client.IncompleteRead as err:
        logger.warn("Could not download image: {}".format(err))
        return ret

    ret.update({"image_mime_type": metadata.mime_type,
                "image_buffer": img_data,
                "image_url": metadata.url})

    return ret


def video_handler(metadata, user_agent):
    if not metadata.mime_type.startswith("video/"):
        return None

    ret = default_handler(metadata, user_agent)

    try:
        img_data = metadata.buf + metadata.response.read()
    except http.client.IncompleteRead as err:
        logger.warn("Could not download image: {}".format(err))
        return ret

    ret.update({"image_mime_type": metadata.mime_type,
                "image_buffer": img_data,
                "image_url": metadata.url})

    return ret


def opengraph_handler(metadata, user_agent):
    if not metadata.mime_type == "text/html":
        return None

    # generic HTML parser to look for opengraph protocol images

    soup = BeautifulSoup(metadata.buf)

    kwargs = {}

    if soup.head is None:
        return None

    img_node = soup.head.find("meta", property="og:image")
    if img_node is not None:
        img_url = img_node["content"]
        if img_url.endswith("?fb"):  # special handling for imgur
            img_url = img_url[:-3]
        try:
            img_data, img_mime_type = _fetch_url(img_url, user_agent,
                                                 metadata.url)
        except DownloadError:
            return None
        kwargs.update({
            "image_url": img_url,
            "image_mime_type": img_mime_type,
            "image_buffer": img_data
        })

    descr_node = soup.head.find("meta", property="og:description")
    if descr_node is not None:
        kwargs["description"] = descr_node["content"] or None
    elif img_node is not None:
        # force description to None, to avoid nonsense description leaking from
        # the default handler
        kwargs["description"] = None

    ret = default_handler(metadata, user_agent)
    ret.update(kwargs)

    return ret
