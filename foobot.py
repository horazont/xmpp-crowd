#!/usr/bin/python3
import logging

from sleekxmpp import ClientXMPP
import time
import readline
import os
from subprocess import check_output, CalledProcessError
# from sleekxmpp.exceptions import IqError, IqTimeout

import re, os, socket
import urllib.request
import urllib.response
import urllib.parse
import urllib.error
import random
import netaddr
import math
import time
import html.parser
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

patterns = [
    ("lt", "<"),
    ("gt", ">"),
    ("copy", "ⓒ"),
    ("amp", "&")
]

for i, (search, replace) in enumerate(patterns):
    patterns[i] = ("&" + search + ";", replace)

def unescape(s):
    for search, replace in patterns:
        s = s.replace(search, replace)
    return s

MAX_BUFFER = 1048576

def readMax(fileLike, maxLength):  # 1 MByte
    buf = b''
    try:
        while len(buf) < maxLength:
            tmp = fileLike.read(maxLength - len(buf))
            if len(tmp) == 0:
                return buf
            buf += tmp
    except Exception as err:
        print(err)
    return buf

WORKING_DATA_FILE = "/tmp/foobot-working-data"

whitespaceRE = re.compile("\s\s+")
def normalize(s, eraseNewlines=True):
    if eraseNewlines:
        s = s.replace("\n", " ").replace("\r", " ")
    matches = list(whitespaceRE.finditer(s))
    matches.reverse()
    for match in matches:
        s = s[:match.start()] + " " + s[match.end():]
    return s
    
class URLNotAuthorized(Exception):
	pass

class FooBot(ClientXMPP):

    urlRE = re.compile("(https?)://[^/>\s]+(/[^>\s]+)?")
    encodingRE = re.compile("charset=([^ ]+)")
    docRE = re.compile("(rfc|xep|pep)(\s*|-)([0-9]+)", re.I)
    titleRE = re.compile("<\s*(\w+:)?title\s*>(.*?)<\s*/(\w+:)?title\s*>", re.S)
    commandRE = re.compile("^!(\w+)\s*(.*)$")

    blacklist = [
        lambda x: x.endswith("facebook.com"),
        lambda x: x.endswith("00001001.ch"),  # this is actually microsoft
        lambda x: x.endswith("bps.hrz.tu-chemnitz.de"),  # opal
    ]

    docMap = {
        "rfc": "https://tools.ietf.org/html/rfc{0}",
        "xep": "http://xmpp.org/extensions/xep-{0:04d}.html",
        "pep": "http://www.python.org/dev/peps/pep-{0:04d}/",
    }

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
    ]

    userAgent = "foorl/23.42"

    @staticmethod
    def formatBytes(byteCount):
        suffixes = ["", "ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi", "Yi"]
        dimension = min(int(math.log(byteCount, 1024)), len(suffixes)-1)
        suffix = suffixes[dimension]+"B"
        if dimension == 0:
            return "{0} {1}".format(byteCount, suffix)
        else:
            value = byteCount / (1 << (10*dimension))
            return "{0:.2f} {1}".format(value, suffix)

    @classmethod
    def formatSize(cls, contentLength):
        if contentLength is None or contentLength <= 0:
            return "unknown length"
        else:
            return cls.formatBytes(contentLength)

    def __init__(self, jid, password, rooms, nick, bimmelAt):
        ClientXMPP.__init__(self, jid, password)

        self.add_event_handler("session_start", self.session_start)
        self.add_event_handler("groupchat_message", self.groupchat_message)

        self.rooms, self.nick = rooms, nick
        self.bimmelAt = bimmelAt

        # If you wanted more functionality, here's how to register plugins:
        # self.register_plugin('xep_0030') # Service Discovery
        # self.register_plugin('xep_0199') # XMPP Ping

        # Here's how to access plugins once you've registered them:
        # self['xep_0030'].add_feature('echo_demo')

        # If you are working with an OpenFire server, you will
        # need to use a different SSL version:
        import ssl
        self.ssl_version = ssl.PROTOCOL_TLSv1
        self.bimmelCount = 0
        self.maxBimmel = None
        self.bimmeling = False

    def setupBimmel(self, runat, maxBimmel=None):
        now = datetime.utcnow()
        delay = (runat - now).total_seconds()
        self.scheduler.remove("bimmelkirche")
        if maxBimmel is not None:
            self.maxBimmel = maxBimmel
        self.scheduler.add(
            "bimmelkirche".format(self.bimmelCount),
            delay,
            self.bimmelkirche
        )
        print("next Bimmelkirche setup for {1} (in {0}s)".format(delay, runat))

    def setupNextBimmel(self):
        now = datetime.utcnow()
        if self.bimmeling and self.bimmelCount < self.maxBimmel:
            nextBimmel = now + timedelta(seconds=1)
            delay = 1
            self.bimmelCount += 1
        else:
            self.bimmeling = False
            nextBimmelRef = now
            if nextBimmelRef.hour >= 16:
                nextBimmelRef = nextBimmelRef + timedelta(days=1)
                nextBimmel = datetime(nextBimmelRef.year, nextBimmelRef.month, nextBimmelRef.day, 10, 00)
            elif nextBimmelRef.hour >= 10:
                nextBimmel = datetime(nextBimmelRef.year, nextBimmelRef.month, nextBimmelRef.day, 16, 00)
            else:
                nextBimmel = datetime(nextBimmelRef.year, nextBimmelRef.month, nextBimmelRef.day, 10, 00)
            self.maxBimmel = 4
            self.bimmelCount = 0

        self.setupBimmel(nextBimmel)

    def session_start(self, event):
        print("session_start")
        self.send_presence(ppriority=-1)
        self.muc = self.plugin["xep_0045"]

        print("joining...")
        for room in self.rooms:
            print(repr(self.muc.joinMUC(room, self.nick, wait=True)))
        print("ok!")
        self.setupNextBimmel()


    def reply(self, msg, content):
        self.send_message(msg["mucroom"], content, mtype="groupchat")

    def tryHardToDecode(self, buffer, encoding, last=False):
        try:
            return buffer.decode(encoding)
        except UnicodeDecodeError as err:
            if last:
                raise
            encoding, last = {
                "ascii": ("utf-8", False),
                "utf-8": ("latin1", True)
            }.get(encoding, ("ascii", False))
            return self.tryHardToDecode(buffer, encoding, last)

    def _fallbackTitle(self, contents):
        print("html parsing failed, falling back to regexp.")
        m = self.titleRE.search(contents)
        if m:
            title = m.group(2)
        else:
            title = None
        return title

    def processURL(self, source, fileLike, length, contentType, redirected, neededTime):
        if redirected:
            self.reply(source, "→ <{0}>".format(redirected))
        prefix = "{0:.2f}s, ".format(neededTime)
        superType, sep, subType = contentType.partition("/")
        if not sep:
            self.reply(source, "{1}link does not deliver valid content type: {0}".format(contentType, prefix))
            return
        subType, sep, suffix = subType.partition(";")
        encoding = "ascii"
        if sep:
            m = self.encodingRE.search(suffix)
            if m:
                print(m.groups())
                encoding = m.group(1)
        mimeType = (superType, subType)

        try:
            if length is not None and length < 256 and mimeType == ("text", "plain"):
                data = fileLike.read(length)
                data = self.tryHardToDecode(data, encoding)
                self.reply(source, "{0}short text/plain, {1}".format(prefix, self.formatSize(len(data))))
                self.reply(source, data)
                return

            if "html" in subType and ("application" in superType or "text" in superType):
                buffer = readMax(fileLike, min(MAX_BUFFER, length or MAX_BUFFER))
                pos = buffer.rfind(b">")
                if pos > 0:
                    buffer = buffer[:pos+1]
                print(buffer[-10:])
                contents = self.tryHardToDecode(buffer, encoding)
                try:
                    soup = BeautifulSoup(contents)
                except html.parser.HTMLParseError:
                    title = self._fallbackTitle(contents)
                    descr = None
                else:
                    tag = soup.find("title")
                    if not tag:
                        title = self._fallbackTitle(contents)
                    else:
                        title = normalize(tag.text.strip(), eraseNewlines=True).replace("&quot;", "\"")
                    tag = soup.find("meta", attrs={"name": "description"})
                    if not tag:
                        descr = None
                    else:
                        descr = normalize(tag["content"].strip(), eraseNewlines=True).replace("&quot;", "\"")
                self.reply(source, "{0}html document, {1}".format(prefix, self.formatSize(length)))
                self.reply(source, title or "(unknown title)")
                if descr is not None:
                    self.reply(source, descr)
                return
        except UnicodeError as err:
            self.reply(source, "{0} cannot decode: {1}".format(prefix, str(err)))
            prefix = ""

        readLength = min(MAX_BUFFER, length or MAX_BUFFER)
        data = fileLike.read(readLength)
        out = open(WORKING_DATA_FILE, "wb")
        out.write(data)
        out.close()
        result = check_output(["/usr/bin/file", "-b", WORKING_DATA_FILE]).decode().strip()
        os.unlink(WORKING_DATA_FILE)
        self.reply(source, "{3}, advertised type: {0}/{1}, {2}".format(superType, subType, self.formatSize(length), prefix))
        self.reply(source, "Actual type: {0}".format(result))
        
        # self.reply(source, "(cannot deal with that. Content-Type is {0})".format(contentType))

    def handleResponse(self, source, response, redirected, neededTime):
        print(response.code)
        transferEnc = response.headers["Transfer-Encoding"]
        #if transferEnc == "chunked":
        #    # oh dear.....
        #    iterable = ChunkedDecoder(response)
        #    contentLength = None
        #elif transferEnc is None:
        try:
            contentLength = int(response.headers["Content-Length"])
        except (NameError, KeyError, TypeError, ValueError):
            # self.send_message(self.room, "cannot check link; no or invalid Content-Length returned: {0}".format(response.headers.get("Content-Length", None)), mtype="groupchat")
            contentLength = None
#        else:
#            self.send_message(self.room, "cannot check link; unknown Transfer-Encoding: {0}".format(transferEnc))
        try:
            contentType = response.headers["Content-Type"]
        except (NameError, KeyError):
            self.send_message(self.room, "cannot check link; no content-type returned", mtype="groupchat")
            return False
        self.processURL(source, response, contentLength, contentType, redirected, neededTime)

    def checkAuthorized(self, family, addr):
        if family == socket.AF_INET:
            v4, port = addr
            ip = netaddr.IPAddress(v4)
            if ip == netaddr.IPAddress("127.0.0.1") or ip == netaddr.IPAddress("0.0.0.0"):
                return False
        elif family == socket.AF_INET6:
            v6 = addr[0]
            ip = netaddr.IPAddress(v6)
            if ip == netaddr.IPAddress("::1") or ip == netaddr.IPAddress("::"):
                return False
        else:
            return False
        return ip.is_unicast() and not ip.is_private()

    def checkURLAuthorized(self, url):
        try:
            parsed = urllib.parse.urlparse(url)
            host, sep, port = parsed.netloc.partition(":")
            if not port: port = None
            family, _, _, _, addr = socket.getaddrinfo(host, port or parsed.scheme)[0]
            if not self.checkAuthorized(family, addr):
                raise URLNotAuthorized("I am not authorized to give you information about that location.")
            reverseHost, _, _ = socket.gethostbyaddr(addr[0])
            for entry in self.blacklist:
                if entry(reverseHost):
                    raise URLNotAuthorized("I _refuse_ to visit that location for you.")
        except URLNotAuthorized:
            raise
        except Exception as err:
            print(err)
        return True

    def fullProcessURL(self, msg, url):
        try:
            self.checkURLAuthorized(url)
        except URLNotAuthorized as err:
            self.reply(msg, str(err))
            return
        request = urllib.request.Request(url, headers={
            "User-Agent": self.userAgent
        })
        print("opening url {0}".format(url))
        try:
            neededTime = time.time()
            f = urllib.request.urlopen(request, timeout=3)
            neededTime = time.time() - neededTime
        except Exception as err:
            self.reply(msg, "could not open url <{0!s}>: {2!s}".format(url, str(err), type(err).__name__))
            print(str(err))
            return
        newUrl = f.geturl()
        if newUrl != url:
            try:
                self.checkURLAuthorized(newUrl)
            except URLNotAuthorized as err:
                self.reply(msg, "Nice try: {0}".format(str(err)))
                return
        else:
            newUrl = None
        try:
            self.handleResponse(msg, f, newUrl, neededTime)
        finally:
            f.close()

    def groupchat_message(self, msg):
        if msg['mucnick'] == self.nick:
            return

        contents = msg['body']

        command = self.commandRE.match(contents)

        if command:
            commandName, argument = command.groups()
            commandFunc = self.commandMap.get(commandName, None)
            if commandFunc is not None:
                commandFunc(self, msg, argument)
        
        for url in self.urlRE.finditer(contents):
            url = url.group(0)
            self.fullProcessURL(msg, url)

        for doc in self.docRE.finditer(contents):
            docType = doc.group(1)
            docID = int(doc.group(3))
            
            url = self.docMap[docType.lower()].format(docID)
            try:
                request = urllib.request.Request(url, headers={
                    "User-Agent": self.userAgent
                })
                neededTime = time.time()
                f = urllib.request.urlopen(request, timeout=2)
                neededTime = time.time() - neededTime
            except urllib.error.HTTPError as err:
                if err.code == 404:
                    self.reply(msg, "The requested document does not exist.")
                else:
                    self.reply(msg, print(err))
            except Exception as err:
                self.reply(msg, "Could not retrieve the document ({0} at url <{1}>)".format(type(err).__name__, url))
                print(err)
            else:
                self.reply(msg, "<{0}>".format(url))
                self.handleResponse(msg, f, None, neededTime)

    def bimmelkirche(self):
        if self.bimmelAt is None:
            return
        self.bimmeling = True
        print(self.bimmelCount)
        if self.bimmelCount == 0:
            self.send_message(self.bimmelAt, "/me amok initialized! chaos ensues!", mtype="groupchat")
        if self.bimmelCount < self.maxBimmel:
            self.send_message(self.bimmelAt, ("ding" if self.bimmelCount % 2 == 0 else "dong"), mtype="groupchat")
        else:
            self.send_message(self.bimmelAt, "Ding Dong! The Abbot Is Dead!", mtype="groupchat")
            self.send_message(self.bimmelAt, check_output(["/usr/bin/ddate"]).decode().strip(), mtype="groupchat")
        self.setupNextBimmel()

    def say(self, msg, argument):
        self.reply(msg, argument)

    def whois(self, msg, argument):
        domain = argument.strip()
        if domain.lower() == "fnord":
            self.reply(msg, random.choice(self.fnordlist))
            return

    def host(self, msg, argument):
        domain = argument.strip()
        try:
            result = check_output(["/usr/bin/host", domain]).decode().strip()
            if len(result) == 0:
                self.reply(msg, "Domain is registered, but has no address records assigned.")
            else:
                self.reply(msg, result)
        except CalledProcessError:
            self.reply(msg, "Domain is not registered.")

    def schedulerTest(self, msg, argument):
        self.setupBimmel(datetime.utcnow(), 2)
    
    commandMap = {
        "say": say,
        "whois": whois,
        "host": host,
    }

if __name__ == '__main__':
    # Ideally use optparse or argparse to get JID,
    # password, and log level.

    logging.basicConfig(level=logging.ERROR,
                        format='%(levelname)-8s %(message)s')

    rooms = ["physiknerds@conference.zombofant.net", "quantenbrot@conference.zombofant.net"]
    xmpp = FooBot('foorl@hub.sotecware.net/sol', '', rooms, "foorl",
        rooms[0])
    xmpp.register_plugin("xep_0045")
    print("connecting")
    xmpp.connect()
    try:
        xmpp.process(block=True)
    finally:
        xmpp.disconnect()
    
