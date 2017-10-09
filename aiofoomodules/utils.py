import asyncio
import math

import aioxmpp.structs


def get_simple_body(message):
    return message.body.lookup([
        aioxmpp.structs.LanguageRange.fromstr("en"),
        aioxmpp.structs.LanguageRange.fromstr("de"),
        aioxmpp.structs.LanguageRange.fromstr("*"),
    ])


def log_future_failure(logger, fut, name=None):
    name = name or repr(fut)
    try:
        result = fut.result()
    except asyncio.CancelledError:
        pass
    except:
        logger.exception("critical %s failed",
                         name)
    else:
        logger.debug("critical %s returned non-None result: %r",
                     name,
                     result)


def ellipsise_text(text, max_length, ellipsis="[…]"):
    if len(text) < max_length:
        return text
    part_len = max_length // 2
    return text[:part_len] + ellipsis + text[-part_len:]


def format_byte_count(nbytes, *, decimals=None):
    ORDER_NAMES = [
        "ki",
        "Mi",
        "Gi",
        "Ti",
    ]

    if nbytes == 0:
        order = 0
    else:
        order = math.floor(math.log(nbytes, 1024))

    if order == 0:
        return "{} B".format(nbytes)
    else:
        rounded = nbytes / (1024**order)
        if decimals is None:
            decimals = max(round(2-math.log(rounded, 10)), 0)

        return "{{:.{decimals}f}} {{}}B".format(
            decimals=decimals,
        ).format(
            rounded,
            ORDER_NAMES[order-1]
        )


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
