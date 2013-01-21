#!/usr/bin/python3
from hub import HubBot
import ast
import urllib.request
import re
import lcdencode
import binascii
from datetime import datetime, timedelta

import lxml.etree as ET

class DVBBot(HubBot):
    DEPARTURE_URL = "http://widgets.vvo-online.de/abfahrtsmonitor/Abfahrten.do?ort=Dresden&hst={}"
    WEATHER_URL = "http://api.met.no/weatherapi/locationforecast/1.8/?lat={lat}&lon={lon}"
    LCD = "lcd@hub.sotecware.net"
    BRACES_RE = re.compile("\(.*?\)")
    USER_AGENT = "InfoLCD/1.0"
    ACCEPT_HEADER = "application/xml"

    def __init__(self, config_path):
        self._config_path = config_path
        self.initialized = False

        error = self.reloadConfig()
        if error:
            traceback.print_exception(*error)
            sys.exit(1)
        self.initialized = True

        credentials = self.config_credentials
        super().__init__(
            credentials["localpart"],
            credentials.get("resource", "core"),
            credentials["password"]
        )
        del credentials["password"]

        nickname = credentials["nickname"]
        self.bots_switch, self.nick = self.addSwitch("bots", nickname)
        self.add_event_handler("presence", self.handle_presence)

    def reloadConfig(self):
        namespace = {}
        with open(self._config_path, "r") as f:
            conf = f.read()

        global_namespace = dict(globals())
        global_namespace["xmpp"] = self
        try:
            exec(conf, global_namespace, namespace)
        except Exception:
            return sys.exc_info()

        new_credentials = namespace.get("credentials", {})
        self.config_credentials = new_credentials
        self.departure_url = self.DEPARTURE_URL.format(namespace["stop_name"])
        lon, lat = namespace["geo"]
        self.weather_url = self.WEATHER_URL.format(lat=lat, lon=lon)
        self._lcd_away = False

        return None

    def _httpRequest(self, url, lastModified=None):
        headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": self.ACCEPT_HEADER
        }
        request = urllib.request.Request(url, headers=headers)
        response = urllib.request.urlopen(url, timeout=3)
        return response

    def _getNextDepartures(self):
        f = self._httpRequest(self.departure_url)
        contents = f.read().decode()
        f.close()
        return ast.literal_eval(contents)

    def _getWeather(self):
        f = self._httpRequest(self.weather_url)
        contents = f.read().decode()
        f.close()

        doc = ET.fromstring(contents)
        print(doc)

    def _stripDest(self, dest):
        m = self.BRACES_RE.search(dest)
        if m:
            dest = dest[:m.start()] + dest[m.end():]
        return dest[:14]

    def _hexBuffer(self, buf):
        buf = binascii.b2a_hex(buf.encode("hd44780a00")).decode("ascii")
        return buf

    def _dataToBuffer(self, data):
        assert len(data) <= 4
        buf = ""
        for lane, dest, remaining in data:
            if len(dest) > 14:
                dest = self._stripDest(dest)
            buf += "{0:2s} {1:14s} {2:2s}".format(lane, dest, remaining)
        return self._hexBuffer(buf)

    def _infoBuffer(self):
        now = datetime.utcnow() + timedelta(seconds=60*60)
        date = now.strftime("%a, %d. %b, %H:%M")
        return self._hexBuffer("{0:20s}".format(date))

    def handle_presence(self, pres):
        if pres["from"].bare == self.LCD:
            if pres["type"] == "available":
                print("lcd available")
                was_away = self._lcd_away
                self._lcd_away = False
                if was_away:
                    self.update()
            else:
                print("lcd went {}".format(pres["type"]))
                self._lcd_away = True

    def sessionStart(self, event):
        super(DVBBot, self).sessionStart(event)
        self.scheduler.add(
            "update",
            30.0,
            self.update,
            repeat=True
        )
        self.update()

    def send_pages(self, pages):
        if self._lcd_away:
            return
        for i, page in enumerate(pages):
            self.writeLCD("update page {} {}".format(i, page))
        self.writeLCD("update page {} {}".format(i+1, self._infoBuffer()))

    def writeLCD(self, raw):
        self.send_message(mto=self.LCD, mbody=raw, mtype="chat")

    def messageMUC(self, msg):
        if msg["mucnick"] == self.nick:
            return
        contents = msg["body"].strip()
        if contents == "ping":
            self.reply(msg, "pong")
            return

    def message(self, msg):
        if str(msg["from"].bare) != self.LCD:
            return

        #~ self.send_message(
            #~ mto=self.switch,
            #~ mbody=msg["body"],
            #~ mtype="groupchat"
        #~ )

    def update(self):
        if self._lcd_away:
            # no need to update while LCD is away
            return
        data = self._getNextDepartures()[:8]  # we can take a max of 8 entries
        buffers = []
        while len(data) > 0:
            buffers.append(self._dataToBuffer(data[:4]))
            data = data[4:]
        self.buffers = buffers
        self.send_pages(buffers)


    COMMANDS = {
    }

if __name__=="__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c", "--config-file",
        default="dvbbot_config.py",
        help="Path to the config file to use.",
        dest="config_file"
    )

    args = parser.parse_args()
    del parser

    bot = DVBBot(args.config_file)
    bot.run()
