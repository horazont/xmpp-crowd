import requests
import time

from datetime import timedelta, datetime

import foomodules.Base as Base


_LAST_REQUEST = None


def check_and_set_ratelimit():
    global _LAST_REQUEST
    if _LAST_REQUEST is None:
        return True
    now = time.monotonic()
    if now - _LAST_REQUEST < 0.8:
        return False
    _LAST_REQUEST = now
    return True


def long_ratelimit(dt=61):
    global _LAST_REQUEST
    _LAST_REQUEST = time.monotonic() + dt


WHITE = "♔"
BLACK = "♚"

COLOURMAP = {
    "white": WHITE,
    "black": BLACK,
}


class Games(Base.ArgparseCommand):
    def __init__(self, command_name="!games", **kwargs):
        super().__init__(command_name, **kwargs)

        def username(s):
            if any(c in "&?/ " for c in s):
                raise ValueError("not a valid user name")
            return s.casefold()

        self.argparse.add_argument(
            "user",
            metavar="USERNAME",
            type=username,
            help="User whose games to query"
        )

        self.argparse.add_argument(
            "--in-progress", "--playing",
            action="store_true",
            default=False,
            help="Limit to games in progress"
        )

        self.argparse.add_argument(
            "--rated",
            action="store_true",
            default=False,
            help="Limit to rated games"
        )

    def _format_analysis(self, analysis):
        return "{blunder}/{mistake}/{inaccuracy}".format(
            **analysis
        )

    def _call(self, msg, args, errorSink=None):
        if not check_and_set_ratelimit():
            self.reply(msg, "please wait a bit")
            return

        req = requests.get(
            "https://lichess.org/api/user/{}/games".format(
                args.user,
            )
        )

        if req.status_code == 429:
            self.reply(
                msg,
                "explicit rate limit from server, "
                "please wait at least one minute"
            )
            return
        elif req.status_code != 200:
            self.reply(
                msg,
                "{} {}".format(req.status_code, req.reason)
            )
            return

        # ♔♚

        items = []
        for game in req.json()["currentPageResults"]:
            uid1 = game["players"]["white"].get("userId", "anon")
            uid2 = game["players"]["black"].get("userId", "anon")

            if uid1 == args.user:
                vs = "{} vs. {} {}".format(WHITE, uid2, BLACK)
            elif uid2 == args.user:
                vs = "{} vs. {} {}".format(BLACK, uid1, WHITE)
            else:
                vs = "{} {} vs. {} {}".format(WHITE, uid1, uid2, BLACK)

            status = game["status"]

            misc = []
            if "winner" in game:
                misc.append("{} won".format(COLOURMAP[game["winner"]]))

            try:
                analysis = game["players"]["white"]["analysis"]
            except KeyError:
                pass
            else:
                misc.append("{} {}".format(
                    WHITE,
                    self._format_analysis(analysis))
                )

            try:
                analysis = game["players"]["black"]["analysis"]
            except KeyError:
                pass
            else:
                misc.append("{} {}".format(
                    BLACK,
                    self._format_analysis(analysis))
                )

            items.append(
                "{url} • {vs}, {status}, {variant} variant{misc}".format(
                    url="https://lichess.org/{}".format(game["id"]),
                    vs=vs,
                    status=status,
                    variant=game["variant"],
                    misc=(" "+", ".join(misc)) if misc else ""
                )
            )

        if items:
            self.reply(
                msg,
                "\n".join([""]+items)
            )
        else:
            self.reply(
                msg,
                "no games found"
            )
