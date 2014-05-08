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

try:
    import pytz
except ImportError:
    # no timezone support
    pytz = None

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

class Host(Base.MessageHandler):
    def __call__(self, msg, arguments, errorSink=None):
        proc = subprocess.Popen(
            ["host", arguments],
            stdout=subprocess.PIPE
        )
        output, _ = proc.communicate()
        output = output.decode().strip()

        self.reply(msg, output)

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
            pingcmd + self.pingargs + [args.host],
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


class Date(Base.MessageHandler):
    def __init__(self, timezone, **kwargs):
        super().__init__(**kwargs)
        if pytz is None:
            logging.warn("Timezone support disabled, install pytz to enable.")
            self._timezone = None
        else:
            self._timezone = pytz.timezone(timezone)

    def _format_date(self, dt):
        return dt.strftime("%a %d %b %Y %H:%M:%S %Z")

    def __call__(self, msg, arguments, errorSink=None):
        if arguments.strip():
            return

        if pytz is not None:
            dt = datetime.now(pytz.UTC)
            if self._timezone is not None:
                dt = dt.astimezone(self._timezone)
        else:
            dt = datetime.utcnow()
        self.reply(msg, self._format_date(dt))

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

class DDate(Date):
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
