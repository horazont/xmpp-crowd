import requests
import time

from datetime import timedelta, datetime

import babel.dates

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


def _format_analysis(self, analysis):
    return "{blunder}/{mistake}/{inaccuracy}".format(
        **analysis
    )


class Game(Base.ArgparseCommand):
    def __init__(self, command_name="!game", **kwargs):
        super().__init__(command_name, **kwargs)

        def gameid(s):
            if any(c in "&?/ " for c in s):
                raise ValueError("not a valid game id")
            if len(s) > 256:
                raise ValueError("you can’t be serious")
            return s

        self.argparse.add_argument(
            "gameid",
            metavar="GAMEID",
            type=gameid,
            help="Game ID to query"
        )

    def _call(self, msg, args, errorSink=None):
        if not check_and_set_ratelimit():
            self.reply(msg, "please wait a bit")
            return

        url = "https://en.lichess.org/api/game/{}".format(
            args.gameid,
        )
        print(url)

        req = requests.get(
            url,
            params={
                "with_opening": "1",
                "with_analysis": "1",
                "with_moves": "1",
            }
        )

        if req.status_code == 429:
            self.reply(
                msg,
                "explicit rate limit from server, "
                "please wait at least one minute"
            )
            long_ratelimit()
            return
        elif req.status_code != 200:
            self.reply(
                msg,
                "{} {}".format(req.status_code, req.reason)
            )
            return

        game = req.json()
        now = datetime.utcnow()

        uid1 = game["players"]["white"].get("userId", "anon")
        uid2 = game["players"]["black"].get("userId", "anon")

        # if game["color"] == "white":
        #     vs = "{} vs. {} {}".format(WHITE, uid2, BLACK)
        # else:
        #     vs = "{} vs. {} {}".format(BLACK, uid1, WHITE)

        vs = "{} {} vs. {} {}".format(
            WHITE, uid1,
            BLACK, uid2
        )

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
                _format_analysis(analysis))
            )

        try:
            analysis = game["players"]["black"]["analysis"]
        except KeyError:
            pass
        else:
            misc.append("{} {}".format(
                BLACK,
                _format_analysis(analysis))
            )

        opening = game.get("opening", {}).get("name")
        if opening:
            misc.append(opening)

        if game.get("moves", ""):
            lastmove_pgn = game.get("moves").rsplit(" ", 1)[-1]

            lastmove = "never"
            try:
                lastmove_t = game["lastMoveAt"]
            except KeyError:
                pass
            else:
                try:
                    lastmove_t = datetime.utcfromtimestamp(
                        lastmove_t/1000
                    )
                except ValueError:
                    pass
                else:
                    lastmove = babel.dates.format_timedelta(
                        lastmove_t - now,
                        format="short",
                        locale="en_GB",
                        add_direction=True,
                    )

            misc.append("last move: {} ({})".format(
                lastmove_pgn,
                lastmove,
            ))

        self.reply(
            msg,
            "{url} • {vs}, {status}, {variant}, {speed}, "
            "{nturns} moves{misc}".format(
                url="https://lichess.org/{}".format(game["id"]),
                vs=vs,
                status=status,
                speed=game["speed"],
                variant=game["variant"],
                nturns=game["turns"],
                misc=(", "+", ".join(misc)) if misc else "",
            )
        )


class Games(Base.ArgparseCommand):
    def __init__(self, command_name="!games", **kwargs):
        super().__init__(command_name, **kwargs)

        def username(s):
            if any(c in "&?/ " for c in s):
                raise ValueError("not a valid user name")
            if len(s) > 256:
                raise ValueError("you can’t be serious")
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

        self.argparse.add_argument(
            "-n",
            dest="amount",
            type=int,
            default=3,
            help="Number of games to fetch (up to 10, default: 3)"
        )

    def _call(self, msg, args, errorSink=None):
        if not (1 <= args.amount <= 10):
            self.reply(msg, "invalid amount of games")
            return

        if not check_and_set_ratelimit():
            self.reply(msg, "please wait a bit")
            return

        req = requests.get(
            "https://en.lichess.org/api/user/{}/games".format(
                args.user,
            ),
            params={
                "playing": str(int(args.in_progress)),
                "rated": str(int(args.rated)),
                "nb": str(args.amount),
                "with_opening": "1",
                "with_analysis": "1",
            }
        )

        if req.status_code == 429:
            self.reply(
                msg,
                "explicit rate limit from server, "
                "please wait at least one minute"
            )
            long_ratelimit()
            return
        elif req.status_code != 200:
            self.reply(
                msg,
                "{} {}".format(req.status_code, req.reason)
            )
            return

        items = []
        now = datetime.utcnow()
        for game in req.json()["currentPageResults"]:
            uid1 = game["players"]["white"].get("userId", "anon")
            uid2 = game["players"]["black"].get("userId", "anon")

            # if game["color"] == "white":
            #     vs = "{} vs. {} {}".format(WHITE, uid2, BLACK)
            # else:
            #     vs = "{} vs. {} {}".format(BLACK, uid1, WHITE)

            vs = "{} {} vs. {} {}".format(
                WHITE, uid1,
                BLACK, uid2
            )

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
                    _format_analysis(analysis))
                )

            try:
                analysis = game["players"]["black"]["analysis"]
            except KeyError:
                pass
            else:
                misc.append("{} {}".format(
                    BLACK,
                    _format_analysis(analysis))
                )

            lastmove = "never"
            try:
                lastmove_t = game["lastMoveAt"]
            except KeyError:
                pass
            else:
                try:
                    lastmove_t = datetime.utcfromtimestamp(
                        lastmove_t/1000
                    )
                except ValueError:
                    pass
                else:
                    lastmove = babel.dates.format_timedelta(
                        now - lastmove_t,
                        format="short",
                        locale="en_GB",
                    )

            items.append(
                "{url} • {vs}, {status}, {variant} variant, "
                "{nturns} moves ({lastmove}){misc}".format(
                    url="https://lichess.org/{}".format(game["id"]),
                    vs=vs,
                    status=status,
                    variant=game["variant"],
                    nturns=game["turns"],
                    lastmove=lastmove,
                    misc=(", "+", ".join(misc)) if misc else ""
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
