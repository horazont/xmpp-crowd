import binascii
import errno
import random
import subprocess
import sys
import os
import re
import socket
import argparse
from datetime import datetime, timedelta, date
import ipaddress
import logging
import calendar
import html
import json
import itertools

import requests

try:
    import pytz
except ImportError:
    # no timezone support
    pytz = None

try:
    import babel
    import babel.dates
except ImportError:
    # no timezone support
    from types import SimpleNamespace
    babel = SimpleNamespace()
    babel.dates = None

import foomodules.Base as Base
import foomodules.utils as utils
import foomodules.polylib as polylib

class Say(Base.MessageHandler):
    def __init__(self, variableTo=False, **kwargs):
        super().__init__(**kwargs)
        self.variableTo = variableTo

    def __call__(self, msg, arguments, errorSink=None):
        if self.variableTo:
            try:
                to, mtype, body = arguments.split(" ", 2)
            except ValueError as err:
                raise ValueError("Too few arguments: {0}".format(str(err)))
        else:
            if msg["type"] == "groupchat":
                to = msg["from"].bare
            else:
                to = msg["from"]
            body = arguments
            mtype = None
        self.reply(msg, body, overrideTo=to, overrideMType=mtype)


class Fnord(Base.MessageHandler):
    fnordlist = [
        "Fnord ist verdampfter Kräutertee - ohne die Kräuter",
        "Fnord ist ein wirklich, wirklich hoher Berg",
        "Fnord ist der Ort wohin die Socken nach der Wäsche verschwinden",
        "Fnord ist das Gerät der Zahnärzte für schwierige Patienten",
        "Fnord ist der Eimer, wo sie die unbenutzen Serifen von Helvetica lagern",
        "Fnord ist das Echo der Stille",
        "Fnord ist Pacman ohne die Punkte",
        "Fnord ist eine Reihe von nervigen elektronischen Nachrichten",
        "Fnord ist das Yin ohne das Yang",
        "Fnord ist die Verkaufssteuer auf die Fröhlichkeit",
        "Fnord ist die Seriennummer auf deiner Cornflakes-Packung",
        "Fnord ist die Quelle aller Nullbits in deinem Computer",
        "Fnord ist der Grund, warum Lisp so viele Klammern hat",
        "Fnord ist weder ein Partikel noch eine Welle",
        "Fnord ist die kleinste Zahl grösser Null",
        "Fnord ist der Grund, warum Ärzte wollen, dass du hustest",
        "Fnord ist der unbenutzte Münzeinwurf am Spielautomaten",
        "Fnord ist der Klang einer einzelnen klatschenden Hand",
        "Fnord ist die Ignosekunde bevor du die Löschtaste im falschen Dokument drückst",
        "Fnord ist wenn du Nachts an der roten Ampel stehst",
        "Fnord ist das Gefühl in deinem Kopf, wenn du die Luft zu lange hältst",
        "Fnord ist die leeren Seiten am Ende deines Buches",
        "Fnord ist der kleine grüne Stein in deinem Schuh",
        "Fnord ist was du denkst wenn du nicht weisst was du denkst",
        "Fnord ist die Farbe die nur der Blinde sieht",
        "Fnord ist Morgens spät und Abends früh",
        "Fnord ist wo die Busse sich verstecken in der Nacht",
        "Fnord ist der Raum zwischen den Pixeln auf deinem Bildschirm",
        "Fnord ist das Pfeifen in deinem Ohr",
        "Fnord ist das pelzige Gefühl auf deinen Zähnen am nächsten Tag",
        "Fnord ist die Angst und ist die Erleichterung und ist die Angst",
        "Fnord schläft nie",
        "Fnord ist xand.",
    ]

    def __call__(self, msg, arguments, errorSink=None):
        if len(arguments.strip()) > 0:
            return
        self.reply(msg, random.choice(self.fnordlist))
        return True

class Host(Base.ArgparseCommand):
    def __init__(self, command_name="!host", **kwargs):
        super().__init__(command_name, **kwargs)
        self.argparse.add_argument(
            "hostname",
            metavar="HOST",
            help="Hostname to look up")

    def _call(self, msg, args, errorSink=None):
        proc = subprocess.Popen(
            ["host", "--", args.hostname],
            stdout=subprocess.PIPE
        )
        output, _ = proc.communicate()
        output = output.decode().strip()

        if proc.returncode == 0 and not output:
            self.reply(msg,
                       "{} has no matching records".format(args.hostname))
        else:
            self.reply(msg, output)

class LDNSRRSig(Base.ArgparseCommand):
    def __init__(self, command_name="!rrsig", **kwargs):
        super().__init__(command_name, **kwargs)
        self.argparse.add_argument(
            "domain",
            help="Domain to look up")
        self.argparse.add_argument(
            "record_type",
            metavar="type",
            default="SOA",
            nargs="?",
            help="query for RRSIG(<type>), defaults to SOA")

    def _call(self, msg, args, errorSink=None):
        proc = subprocess.Popen(
            ["ldns-rrsig", args.domain, args.record_type],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        stdout, stderr = proc.communicate()
        stdout = stdout.decode().strip() if stdout else ""
        stderr = stderr.decode().strip().strip("* ") if stderr else ""

        self.reply(msg, stdout + stderr)

class Uptime(Base.MessageHandler):
    def __init__(self, show_users=False, **kwargs):
        super().__init__(**kwargs)
        self._show_users = show_users

    def __call__(self, msg, arguments, errorSink=None):
        if arguments.strip():
            return
        proc = subprocess.Popen(
            ["uptime"],
            stdout=subprocess.PIPE
        )
        output, _ = proc.communicate()
        output = output.decode().strip()

        if not self._show_users:
            output = re.sub("[0-9]+ users, ", "", output)

        self.reply(msg, output)

class Reload(Base.MessageHandler):
    def __call__(self, msg, arguments, errorSink=None):
        if arguments.strip():
            return
        self.xmpp.config.reload()


class REPL(Base.MessageHandler):
    def __call__(self, msg, arguments, errorSink=None):
        if arguments.strip():
            return
        import code
        namespace = dict(locals())
        namespace["xmpp"] = self.XMPP
        self.reply(msg, "Dropping into repl shell -- don't expect any further interaction until termination of shell access")
        code.InteractiveConsole(namespace).interact("REPL shell as requested")


class Respawn(Base.MessageHandler):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.argv = list(sys.argv)
        self.cwd = os.getcwd()

    def __call__(self, msg, arguments, errorSink=None):
        if arguments.strip():
            return
        print("disconnecting for respawn")
        self.XMPP.disconnect(reconnect=False, wait=True)
        print("preparing and running execv")
        os.chdir(self.cwd)
        os.execv(self.argv[0], self.argv)


class Peek(Base.ArgparseCommand):
    def __init__(self, timeout=3, command_name="peek", maxlen=256, **kwargs):
        super().__init__(command_name, **kwargs)
        self.timeout = timeout
        self.maxlen = maxlen
        self.argparse.add_argument(
            "-u", "--udp",
            action="store_true",
            dest="udp",
            default=False,
            help="Use UDP instead of TCP",
        )
        self.argparse.add_argument(
            "-6", "--ipv6",
            action="store_true",
            dest="ipv6",
            default=False,
            help="Use IPv6 sockets to connect to target"
        )
        self.argparse.add_argument(
            "host",
            help="Host or IP to connect to"
        )
        self.argparse.add_argument(
            "port",
            type=int,
            help="TCP/UDP port to connect to"
        )

    def recvline(self, sock):
        buf = b""
        while b"\n" not in buf and len(buf) < self.maxlen:
            try:
                data = sock.recv(1024)
                if len(data) == 0:
                    break  # this should not happen in non-blocking mode, but...
                buf += data
            except socket.error as err:
                if err.errno == errno.EAGAIN:
                    print("EAGAIN")
                    break
                raise
        return buf.split(b"\n", 1)[0]

    def _is_ipv6(self, host):
        try:
            return ipaddress.ip_address(host).version == 6
        except ValueError: # host is probably a hostname
            return False


    def _call(self, msg, args, errorSink=None):
        v6 = True if args.ipv6 else self._is_ipv6(args.host)
        fam = socket.AF_INET6 if v6 else socket.AF_INET

        typ = socket.SOCK_DGRAM if args.udp else socket.SOCK_STREAM
        sock = socket.socket(fam, typ, 0)
        sock.settimeout(self.timeout)
        try:
            sock.connect((args.host, args.port))
        except socket.error as err:
            self.reply(msg, "connect error: {0!s}".format(err))
            return
        try:
            try:
                buf = self.recvline(sock)
            except socket.timeout as err:
                self.reply(msg, "error: didn't receive any data in time")
                return
        finally:
            sock.close()

        if not buf:
            self.reply(msg, "error: nothing received before first newline")
            return

        try:
            reply = buf.decode("utf-8").strip()
            if utils.evil_string(reply):
                reply = None
        except UnicodeDecodeError as err:
            reply = None

        if reply is None:
            reply = "hexdump: {0}".format(binascii.b2a_hex(buf).decode("ascii"))
        else:
            hoststr = "[{}]".format(args.host) if self._is_ipv6(args.host) else args.host
            reply = "{host}:{port} says: {0}".format(reply, host=hoststr,
                port=args.port)

        self.reply(msg, reply)


class Ping(Base.ArgparseCommand):
    packetline = re.compile("([0-9]+) packets transmitted, ([0-9]+) received(.*), ([0-9]+)% packet loss, time ([0-9]+)ms")
    rttline = re.compile("rtt min/avg/max/mdev = (([0-9.]+/){3}([0-9.]+)) ms")

    def __init__(self, count=4, interval=0.5, command_name="ping", **kwargs):
        super().__init__(command_name, **kwargs)
        self.argparse.add_argument(
            "-6", "--ipv6",
            action="store_true",
            dest="ipv6",
            default=False,
            help="Use ping6 instead of ping"
        )
        self.argparse.add_argument(
            "--alot",
            action="store_true",
            dest="alot",
            help="Send more pings"
        )
        self.argparse.add_argument(
            "host",
            help="Host which is to be pinged"
        )
        self.pingargs = [
            "-q",
            "-i{0:f}".format(interval)
        ]

    def _call(self, msg, args, errorSink=None):
        pingcmd = ["ping6" if args.ipv6 else "ping"]
        if args.alot:
            count = 20
        else:
            count = 5
        pingcmd.append("-c{0:d}".format(count))
        proc = subprocess.Popen(
            pingcmd + self.pingargs + ["--", args.host],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE
        )
        out, err = proc.communicate()
        if proc.wait() != 0:
            message = err.decode().strip()
            if not message:
                self.reply(msg, "unknown error, timeout/blocked?")
            else:
                self.reply(msg, "error: {0}".format(message))
        else:
            lines = out.decode().strip().split("\n")
            packetinfo = self.packetline.match(lines[3])
            rttinfo = self.rttline.match(lines[4])
            if not packetinfo or not rttinfo:
                self.reply(msg, "unknown error, unable to parse ping output, dumping to stdout")
                print(out.decode())
            else:
                packetinfo = packetinfo.groups()
                rttinfo = rttinfo.group(1).split("/")
                try:
                    message = "{host}: {recv}/{sent} pckts., {loss}% loss, rtt ↓/-/↑/↕ = {rttmin}/{rttavg}/{rttmax}/{rttmdev}, time {time}ms".format(
                        host=args.host,
                        sent=int(packetinfo[0]),
                        recv=int(packetinfo[1]),
                        loss=int(packetinfo[3]),
                        rttmin=rttinfo[0],
                        rttavg=rttinfo[1],
                        rttmax=rttinfo[2],
                        rttmdev=rttinfo[3],
                        time=int(packetinfo[4])
                    )
                except ValueError:
                    self.reply(msg, "malformatted ping output, dumping to stdout")
                    print(out.decode())
                    return
                self.reply(
                    msg,
                    message
                )

class Roll(Base.MessageHandler):
    rollex_base = "([0-9]*)[dW]([0-9]+)"
    rollex_all = re.compile("^(({0}\s+)*{0})(\s+(each\s+)?\w+\s+([0-9]+))?\s*$".format(rollex_base), re.I)
    rollex = re.compile(rollex_base, re.I)

    def _too_much(self, msg):
        self.reply(msg, "yeah, right, I'll go and rob a die factory")

    def __call__(self, msg, arguments, errorSink=None):
        matched = self.rollex_all.match(arguments)
        if not matched:
            self.reply(msg, "usage: XdY rolls a dY X times")
            return

        results = []
        die = matched.group(1)
        for match in self.rollex.finditer(die):
            if len(results) > 4000:
                self._too_much()
                return
            count, dice = match.groups()
            count = int(count) if count else 1
            dice = int(dice)
            if count < 1:
                self.reply(msg, "thats not a reasonable count: {}".format(count))
                return
            if dice <= 1:
                self.reply(msg, "thats not a reasonable die: {}".format(dice))
                return
            if count > 1000 or len(results) > 1000:
                self._too_much(msg)
                return
            results.extend(random.randint(1, dice) for i in range(count))

        against = matched.group(9)
        each = matched.group(8)
        suffix = ""
        print(repr(against))
        if against:
            against = int(against)
            if against >= sum(results):
                suffix = ": passed"
            else:
                suffix = ": failed"

        self.reply(msg, "results: {}, sum = {}{}".format(
            " ".join("{}".format(result) for result in results),
            sum(results),
            suffix
        ))

class Dig(Base.ArgparseCommand):
    def __init__(self, command_name="dig", **kwargs):
        super().__init__(command_name, **kwargs)
        self.argparse.add_argument(
            "-s", "--server", "--at",
            default=None,
            help="Server to ask for the record",
            dest="at"
        )
        self.argparse.add_argument(
            "kind",
            metavar="RECTYPE",
            nargs="?",
            default=None,
            type=lambda x: x.upper(),
            choices=["SRV", "A", "AAAA", "CNAME", "MX", "SOA", "TXT",
                "SPF", "NS", "SSHFP", "NSEC", "NSEC3", "DNSKEY", "RRSIG",
                "DS", "TLSA", "PTR"],
            help="Record kind to ask for"
        )
        self.argparse.add_argument(
            "name",
            metavar="NAME",
            help="Record name to look up"
        )

    def _call(self, msg, args, errorSink=None):
        userargs = [args.name]
        kindstr = ""
        if args.kind is not None:
            kindstr = " ({})".format(args.kind)
            userargs.insert(0, args.kind)
        atstr = ""
        if args.at is not None:
            atstr = "@"+args.at
            userargs.append(atstr)

        if any(arg.startswith("+") for arg in userargs):
            self.reply(msg, "nice try")
            return

        call = ["dig", "+time=2", "+short"] + userargs

        proc = subprocess.Popen(
            call,
            stdout=subprocess.PIPE
        )
        stdout, _ = proc.communicate()
        if proc.wait() != 0:
            self.reply(msg, stdout.decode().strip(";").strip())
            return

        results = list(filter(bool, stdout.decode().strip().split("\n")))

        if results:
            resultstr = ", ".join(results)
        else:
            resultstr = "no records"
        self.reply(msg, "{host}{at}{kind}: {results}".format(
            host=args.name,
            at=atstr,
            kind=kindstr,
            results=resultstr
        ))

# info on current CalendarWeek
class CW(Base.MessageHandler):
    def __call__(self, msg, arguments, errorSink=None):
        if arguments.strip():
            return
        current_date = date.today()
        current_cw = current_date.isocalendar()[1]
        current_year = current_date.year
        paritystr = ""
        if (current_cw % 2) == 0:
            paritystr = "even"
        else:
            paritystr = "odd"

        self.reply(msg, "Current week is week #{cw} in {year}, which is {parity}.".format(
            cw=current_cw,
            year=current_year,
            parity=paritystr
        ))


class Redirect(Base.MessageHandler):
    def __init__(self, new_name, **kwargs):
        super().__init__(**kwargs)
        self._new_name = new_name

    def __call__(self, msg, arguments, errorSink=None):
        self.reply(
            msg,
            "I don't know that. Did you mean: {} {}".format(
                self._new_name, arguments))


class Date(Base.ArgparseCommand):
    @staticmethod
    def to_timezone(s):
        try:
            return pytz.timezone(s)
        except pytz.exceptions.UnknownTimeZoneError as err:
            raise ValueError("no such time zone: {}".format(err))

    def __init__(self, command_name="!date",
                 timezone=None,
                 locale=None, **kwargs):
        super().__init__(command_name, **kwargs)
        if pytz is None:
            logging.warn("Timezone support disabled, install pytz to enable.")
            self.argparse.set_defaults(timezone=None)
        else:
            if timezone is None:
                timezone = pytz.UTC
            else:
                timezone = pytz.timezone(timezone)
            self.argparse.add_argument(
                "timezone",
                nargs="?",
                default=timezone,
                type=self.to_timezone,
                help="Timezone (default is {}). Examples: "
                "Europe/Berlin, US/Eastern, ETC/GMT+2".format(timezone)
            )

        if babel.dates is None:
            logging.warn("Localization support is disabled, "
                         "install babel to enable.")
            self.argparse.set_defaults(locale=None)
        else:
            if locale is None:
                locale = babel.default_locale()
            self.argparse.add_argument(
                "-l", "--lang", "--locale",
                default=locale,
                dest="locale",
                help="Locale for the output (default is {}). Examples: "
                "en_GB, de_DE".format(locale)
            )
            self.argparse.add_argument(
                "-f", "--format",
                choices={"short", "long", "medium", "full"},
                default="full",
                help="Format of the output (default is full)."
            )

    def _format_date(self, dt):
        return dt.strftime("%a %d %b %Y %H:%M:%S %Z")

    def _call(self, msg, args, errorSink=None):
        if args.timezone is not None:
            dt = datetime.now(args.timezone)
        else:
            dt = datetime.utcnow()

        if args.locale is not None:
            text = babel.dates.format_datetime(
                dt,
                locale=args.locale,
                format=args.format
            )
        else:
            text = self._format_date(dt)

        self.reply(msg, text)

class DiscordianDateTime:
    ST_TIBS_DAY = "St. Tib’s Day"

    HOLIDAYS = [
        "Mungday",
        "Chaoflux",
        "Mojoday",
        "Discoflux",
        "Syaday",
        "Confuflux",
        "Zaraday",
        "Bureflux",
        "Maladay",
        "Afflux",
    ]

    SEASONS = [
        "Chaos",
        "Discord",
        "Confusion",
        "Bureaucracy",
        "The Aftermath",
    ]

    WEEKDAYS = [
        "Sweetmorn",
        "Boomtime",
        "Pungenday",
        "Prickle-Prickle",
        "Setting Orange",
    ]

    yold = None
    seasonname = None
    season = None
    weekday = None
    weekdayname = None
    day = None
    hour = None
    minute = None
    second = None

    def __init__(self, dt):
        y, m, d = dt.year, dt.month, dt.day

        self.yold = y + 1166
        self.hour = dt.hour
        self.minute = dt.minute
        self.second = dt.second

        if (m, d) == (2, 29):
            self.weekdayname = self.ST_TIBS_DAY
        else:
            # this is ugly. if you know something better, tell me
            day_of_year = int(dt.strftime("%j"))

            if calendar.isleap(y):
                # 60th is St. Tib's Day
                if day_of_year > 60:
                    day_of_year -= 1

            season = int((day_of_year-1) / 73)
            self.season = season+1
            self.seasonname = self.SEASONS[season]

            self.day = (day_of_year-1) % 73 + 1

            self.weekday = (day_of_year-1) % 5 + 1
            if self.day == 5 or self.day == 50:
                # holiday
                offs = 1 if self.day == 50 else 0
                holidayidx = season*2 + offs
                self.weekdayname = self.HOLIDAYS[holidayidx]
            else:
                self.weekdayname = self.WEEKDAYS[self.weekday-1]

class DDate(Base.MessageHandler):
    @staticmethod
    def _cardinal_number(num):
        suffixes = {
            "1": "st",
            "2": "nd",
            "3": "rd"
        }
        exceptions = {11, 12, 13}
        if num in exceptions:
            return "{:d}th".format(num)

        num = str(num)
        num += suffixes.get(num[-1], "th")
        return num

    def __init__(self, timezone, **kwargs):
        super().__init__(**kwargs)
        if pytz is None:
            self._timezone = None
        else:
            self._timezone = pytz.timezone(timezone)

    def _format_date(self, dt):
        ddt = DiscordianDateTime(dt)
        if ddt.day is None:
            return "Today is {weekdayname} in the YOLD {yold:04d}".format(
                weekdayname=ddt.weekdayname,
                yold=ddt.yold)
        else:
            return "Today is {weekdayname}, the {card} day of {seasonname} in the YOLD {yold}".format(
                weekdayname=ddt.weekdayname,
                card=self._cardinal_number(ddt.day),
                seasonname=ddt.seasonname,
                yold=ddt.yold)

    def __call__(self, msg, arguments, errorSink=None):
        if arguments.strip():
            return

        if pytz is not None:
            dt = datetime.now(pytz.UTC)
            if self._timezone is not None:
                dt = self._timezone.normalize(dt)
        else:
            dt = datetime.utcnow()

        self.reply(msg, self._format_date(dt))


class Poly(Base.MessageHandler):
    divex = re.compile(r"^\s*(.*?)\s+mod\s+(.*?)\s+in\s+GF\(([0-9]+)\)\[(\w)\]\s*$", re.I)
    supunmap = {v: k for k, v in polylib.supmap.items()}

    def __init__(self, degree_limit=1024, **kwargs):
        super().__init__(**kwargs)
        self.degree_limit = degree_limit

    def _parse_coeff(self, cstr, var):
        coefficient, _, exponent = cstr.partition(var)
        if _ != var:
            try:
                return int(cstr), 0
            except ValueError:
                raise ValueError("Not a valid coefficient for a polynome in"
                                 " {var}: {}".format(cstr, var=var))
        if exponent.startswith("^"):
            # usual format, strip braces if there are any
            exponent = exponent[1:].replace("{", "").replace("}", "")
        else:
            # unicode format
            exponent = "".join(map(lambda x: self.supunmap.get(x, x), exponent))
        if not exponent:
            exponent = 1
        else:
            exponent = int(exponent)
        if not coefficient:
            coefficient = 1
        else:
            coefficient = int(coefficient)
        return coefficient, exponent

    def _parse_poly(self, pstr, var):
        # this removes spaces
        pstr = "".join(map(str.strip, pstr))
        summands = pstr.split("+")

        coefficients = list(map(lambda x: self._parse_coeff(x, var), summands))

        cs = [0]*(max(degree for _, degree in coefficients)+1)
        for value, degree in coefficients:
            if degree < 0:
                raise ValueError("Negative exponents are invalid for "
                                 "polynomials.")
            if self.degree_limit is not None and degree > self.degree_limit:
                raise ValueError("Polynomial out of supported range. "
                                 "Maximum degree is {}".format(
                                    self.degree_limit))
            cs[degree] = value
        return cs

    def _parse_instruction(self, s):
        match = self.divex.match(s)
        if match is None:
            raise ValueError("Could not parse command")
        poly1 = match.group(1)
        poly2 = match.group(2)
        instruction = "mod"#match.group(2)
        p = int(match.group(3))
        var = match.group(4)

        cs1 = self._parse_poly(poly1, var)
        cs2 = self._parse_poly(poly2, var)

        field = polylib.IntField(p)
        p1 = polylib.FieldPoly(field, cs1)
        p2 = polylib.FieldPoly(field, cs2)

        return p1, instruction, p2

    def __call__(self, msg, arguments, errorSink=None):
        if not arguments.strip():
            return

        try:
            p1, _, p2 = self._parse_instruction(arguments)
        except ValueError as err:
            self.reply(msg,
                "could not parse your request: {}. please use format: "
                "poly1 mod poly2 in GF(p)[x]".format(err))
            return

        try:
            d, r = divmod(p1, p2)
        except ZeroDivisionError:
            self.reply(msg, "division by zero")
            return

        self.reply(msg,
            "{a} // {b} = {d}; remainder: {r}".format(
                a=p1,
                b=p2,
                d=d,
                r=r))


class Porn(Base.ArgparseCommand):
    ORIENTATIONS = {
        "straight": "s",
        "gay": "g",
        "tranny": "t",
        "shemale": "t",
        "g": "g",
        "s": "s",
        "t": "t"
    }

    COUNTRIES = {
        "de": "de",
        "us": "us",
        "in": "in",
        "ca": "ca",
        "fr": "fr",
        "it": "it",
        "mx": "mx"
    }

    def __init__(self, command_name="!porn",
                 cache_lifetime=None,
                 max_amount=24,
                 **kwargs):
        super().__init__(command_name, **kwargs)

        self.cache_lifetime = cache_lifetime
        self.max_amount = max_amount

        self.argparse.add_argument(
            "-c", "--country",
            choices=set(self.COUNTRIES),
            default=None,
            help="Filter by country code")
        self.argparse.add_argument(
            "-n", "--amount",
            type=int,
            default=10,
            help="Number of items to show at once (max: {})".format(
                max_amount))
        self.argparse.add_argument(
            "orientation",
            choices=set(self.ORIENTATIONS),
            nargs="?",
            default=None,
            help="Filter by orientation")

        self._cache = {}
        self._cache_timestamp = None

    def _fetch_n_from_cache(self, orientation, country, n):
        cache_key = (orientation, country)
        try:
            items, timestamp = self._cache[cache_key]
        except KeyError:
            return []

        if     (self.cache_lifetime is not None and
                timestamp + self.cache_lifetime < datetime.utcnow()):
            del self._cache[cache_key]
            return []

        result = items[:n]
        if len(items) > n:
            self._cache[cache_key] = items[n:], timestamp
        else:
            del self._cache[cache_key]

        return result

    def _fetch_n(self, orientation, country, n):
        items = self._fetch_n_from_cache(orientation, country, n)
        found = 1  # force the loop into at least one iteration
        while len(items) < n and found > 0:
            params = {}
            if orientation:
                params["orientation"] = orientation
            if country:
                params["country"] = country

            req = requests.get("http://www.pornmd.com/getliveterms",
                               params=params)
            self._cache[orientation, country] = req.json(), datetime.utcnow()

            new_items = self._fetch_n_from_cache(orientation, country, n)
            found = len(new_items)
            items.extend(new_items)

        return items

    def _fix_the_mess(self, s):
        return html.unescape(s).replace(r'\"', '"').replace(r"\'", "'")

    def _call(self, msg, args, errorSink=None):
        entries = self._fetch_n(args.orientation, args.country,
                                max(1, min(args.amount, self.max_amount))
        )
        if not entries:
            self.reply(msg, "No data currently")
        else:
            self.reply(msg, ", ".join(self._fix_the_mess(entry["keyword"])
                                      for entry in entries))


class DWDWarnings(Base.ArgparseCommand):
    if pytz:
        TZ = pytz.timezone("Europe/Berlin")
        UTC = pytz.UTC

    def __init__(self, default_region_match, command_name="!warnings",
                 language="de_DE",
                 cache_timeout=timedelta(seconds=300),
                 **kwargs):
        super().__init__(command_name, **kwargs)

        self.argparse.add_argument(
            "region",
            nargs="?",
            default=default_region_match,
            help="Region to search in",
        )

        self.argparse.add_argument(
            "-l", "--date-locale",
            default=language,
            help="Locale to use for timestamps and relative time deltas",
            metavar="LOCALE",
        )

        self.argparse.add_argument(
            "-t", "--timezone",
            default=self.TZ,
            type=pytz.timezone,
            help="Time zone to use for absolute timestamps",
            metavar="TZ",
        )

        self.argparse.set_defaults(mode="mixed")
        group = self.argparse.add_mutually_exclusive_group()
        group.add_argument(
            "-a", "--absolute",
            action="store_const",
            dest="mode",
            const="absolute",
            help="Show absolute timestamps only",
        )

        group.add_argument(
            "-r", "--relative",
            action="store_const",
            dest="mode",
            const="relative",
            help="Show relative time deltas only",
        )

        group.add_argument(
            "-m", "--mixed",
            action="store_const",
            dest="mode",
            const="mixed",
            help="Show mixed timestamps (default)",
        )

        self.argparse.add_argument(
            "-f", "--full",
            default=False,
            action="store_true",
            help="Show full instructions from DWD",
        )

        self.argparse.add_argument(
            "-F", "--flush",
            default=False,
            action="store_true",
            help="Flush the cache before querying (expensive and slow, use rarely)"
        )

        self._cache_timestamp = None
        self._cache = {}
        self._cache_timeout = cache_timeout

    def _fetch_raw(self, flush=False):
        if (self._cache_timestamp is not None and not flush
                and datetime.utcnow() - self._cache_timestamp < self._cache_timeout):
            return self._cache

        req = requests.get(
            "http://www.dwd.de/DWD/warnungen/warnapp/json/warnings.json",
            headers={
                "User-Agent": "foorl/1.0"
            }
        )
        data = req.text
        data = data[data.find("{"):data.rfind("}")+1]
        data = json.loads(data)

        self._cache = data
        self._cache_timestamp = datetime.utcnow()

        return data

    def _query(self, region_name_match, flush=False):
        data = self._fetch_raw(flush=flush)

        region_name_match = region_name_match.casefold()
        matching_warnings = [
            warning
            for warning_list in data["vorabInformation"].values()
            for warning in warning_list
            if region_name_match in warning["regionName"].casefold()
        ]

        for w in matching_warnings:
            w["is_preliminary"] = True

        matching_warnings += [
            warning
            for warning_list in data["warnings"].values()
            for warning in warning_list
            if region_name_match in warning["regionName"].casefold()
        ]

        return matching_warnings

    def _format_semishort_datetime(self, dt, locale):
        return "{}, {}".format(
            babel.dates.format_datetime(dt, format="long", locale=locale),
            babel.dates.format_time(dt, format="short", locale=locale),
        )

    def _format_absolute_time_range(self, start, end, locale, timezone):
        start = timezone.normalize(start)
        if end is None:
            return "{}:".format(
                babel.dates.format_datetime(start, locale=locale),
            )

        end = timezone.normalize(end)

        if start.tzinfo != end.tzinfo or start.date() != end.date():
            # full format
            return "{} – {}:".format(
                babel.dates.format_datetime(start, locale=locale),
                babel.dates.format_datetime(end, locale=locale),
            )

        return "{}, {} – {}:".format(
            babel.dates.format_date(start, locale=locale),
            babel.dates.format_time(start, locale=locale),
            babel.dates.format_time(end, locale=locale),
        )

    def _format_mixed_time_range(self, start, end, locale, timezone):
        now = self.UTC.localize(datetime.utcnow())
        now_tz = timezone.normalize(now)
        starting_in = start - now
        start_tz = timezone.normalize(start)
        if end is None:
            return "{} ({}):".format(
                babel.dates.format_timedelta(starting_in,
                                             add_direction=True,
                                             locale=locale),
                self._format_semishort_datetime(
                    start_tz,
                    locale=locale
                ),
            )

        end_tz = timezone.normalize(end)

        if (start_tz.tzinfo != end_tz.tzinfo or
                start_tz.date() != end_tz.date()):
            # full format
            absolute_range = "{} – {}:".format(
                self.format_semishort_datetime(
                    start_tz,
                    locale=locale,
                ),
                self.format_semishort_datetime(
                    end_tz,
                    locale=locale
                ),
            )

        elif start_tz.date() != now_tz.date():
            absolute_range = "{}, {} – {}:".format(
                babel.dates.format_date(start_tz,
                                        locale=locale),
                babel.dates.format_time(start_tz,
                                        format="short",
                                        locale=locale),
                babel.dates.format_time(end_tz,
                                        format="short",
                                        locale=locale),
            )

        else:
            absolute_range = "{} – {}".format(
                babel.dates.format_time(start_tz,
                                        format="short",
                                        locale=locale),
                babel.dates.format_time(end_tz,
                                        format="short",
                                        locale=locale),
            )

        runs_for = end - start

        return "{}: {} ({})".format(
            babel.dates.format_timedelta(
                starting_in,
                add_direction=True,
                locale=locale,
            ),
            babel.dates.format_timedelta(
                runs_for,
                locale=locale,
            ),
            absolute_range,
        )

    def _format_relative_time_range(self, start, end, locale):
        now = self.UTC.localize(datetime.utcnow())
        starting_in = start - now
        if end is None:
            return "{}:".format(
                babel.dates.format_timedelta(
                    starting_in,
                    add_direction=True,
                    locale=locale,
                )
            )

        runs_for = end - start

        return "{}: {}".format(
            babel.dates.format_timedelta(
                starting_in,
                add_direction=True,
                locale=locale,
            ),
            babel.dates.format_timedelta(
                runs_for,
                locale=locale,
            )
        )

    def _format_warning(self, warning,
                        timezone, date_locale, mode, full,
                        has_actual):
        start_dt = self.UTC.localize(
            datetime.utcfromtimestamp(warning["start"]/1000)
        )

        if warning["end"] is not None:
            end_dt = self.UTC.localize(
                datetime.utcfromtimestamp(warning["end"]/1000)
            )
        else:
            end_dt = None

        if mode == "relative":
            time_range = self._format_relative_time_range(
                start_dt,
                end_dt,
                date_locale,
            )
        elif mode == "absolute":
            time_range = self._format_absolute_time_range(
                start_dt,
                end_dt,
                date_locale,
                timezone)
        else:
            time_range = self._format_mixed_time_range(
                start_dt,
                end_dt,
                date_locale,
                timezone)

        result = "{} {}".format(
            time_range,
            warning["event"],
        )
        if full and (not has_actual or not warning.get("is_preliminary", False)):
            parts = [
                result,
            ]
            # if warning["headline"]:
            #     parts.append(warning["headline"])
            if warning.get("description"):
                parts.append(warning["description"])
            if (warning["instruction"] and
                    not warning.get("is_preliminary", False)):
                parts.append(warning["instruction"])
            if len(parts) > 1:
                parts.append("")
            result = "\n".join(parts)

        return result

    def _call(self, msg, args, errorSink=None):
        if len(args.region) >= 1023:
            self.reply(msg, "just no.")
            return

        region = " ".join(args.region.split())

        if len(region) <= 2:
            self.reply(msg, "won’t search for {!r}".format(region))
            return

        warnings = self._query(region, flush=args.flush)
        warnings.sort(key=lambda x: x["regionName"])

        if not warnings:
            self.reply(
                msg,
                "no warnings whose region matches {!r}".format(
                    region
                )
            )
            return

        grouped_warnings = [
            (region, list(region_warnings))
            for region, region_warnings in itertools.groupby(
                    warnings, lambda x: x["regionName"])
        ]

        if len(grouped_warnings) > 4:
            random.shuffle(grouped_warnings)
            show = grouped_warnings[:10]
            reply = "too many regions match: {}".format(", ".join(
                region for region, _ in show
            ))
            if len(grouped_warnings) > 10:
                reply += " and {} more".format(len(grouped_warnings) - 10)
            self.reply(msg, reply)
            return

        for region, region_warnings in grouped_warnings:
            has_actual = any(not warning.get("is_preliminary", False)
                             for warning in region_warnings)

            reply = "\n".join(
                self._format_warning(warning,
                                     args.timezone,
                                     args.date_locale,
                                     args.mode,
                                     args.full,
                                     has_actual)
                for warning in region_warnings
            ).strip()

            self.reply(msg, "{}\n{}".format(region, reply))
