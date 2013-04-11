#!/usr/bin/python3
from hub import HubBot
import ast
import urllib.request
import re
import lcdencode
import binascii
import sys
from datetime import datetime, timedelta
from wsgiref.handlers import format_date_time
from calendar import timegm
import email.utils as eutils

import lxml.etree as ET

def to_timestamp(datetime):
    return timegm(datetime.utctimetuple())

def parse_http_date(httpdate):
    return datetime(*eutils.parsedate(httpdate)[:6])

def trunc_to_hour(dt):
    return datetime(dt.year, dt.month, dt.day, dt.hour)


class DVBBot(HubBot):
    DEPARTURE_URL = "http://widgets.vvo-online.de/abfahrtsmonitor/Abfahrten.do?ort=Dresden&hst={}"
    WEATHER_URL = "http://api.met.no/weatherapi/locationforecast/1.8/?lat={lat}&lon={lon}"
    LCD = "lcd@hub.sotecware.net"
    BRACES_RE = re.compile("\(.*?\)")
    USER_AGENT = "InfoLCD/1.0"
    ACCEPT_HEADER = "application/xml"

    longwordmap = {
        "partlycloud": "ptcld",
        "lightrain": "lrain"
        }

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
        self._weather_document = None
        self._weather_last_modified = None
        self._weather = None
        #sys.exit(1)
        self._lcd_away = False

        return None

    def _httpRequest(self, url, last_modified=None):
        headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": self.ACCEPT_HEADER
        }
        if last_modified is not None:
            headers["If-Modified-Since"] = format_date_time(to_timestamp(last_modified))
        request = urllib.request.Request(url, headers=headers)
        response = urllib.request.urlopen(url, timeout=3)
        return response

    def _getNextDepartures(self):
        f = self._httpRequest(self.departure_url)
        contents = f.read().decode()
        f.close()
        return ast.literal_eval(contents)

    def _update_weather_cache(self):
        try:
            f = self._httpRequest(self.weather_url, last_modified=self._weather_last_modified)
            contents = f.read().decode()
            f.close()
            self._weather_last_modified = parse_http_date(f.info()["Last-Modified"])
            self._weather_document = ET.fromstring(contents)
        except urllib.error.HTTPError as err:
            if err.code == 304:
                raise

    def _get_weather_cached(self):
        if self._weather_document is None:
            self._update_weather_cache()
        return self._weather_document

    def _forecast_by_date(self, tree, dt):
        todate = trunc_to_hour(dt).isoformat()
        fromdate = trunc_to_hour(dt - timedelta(seconds=3600*6+1)).isoformat()
        return tree.xpath("//time[@from='{}Z' and @from=@to]/location".format(todate)).pop(),\
               tree.xpath("//time[@from='{}Z' and @to='{}Z']/location".format(fromdate, todate)).pop()

    def _parse_forecast(self, locnodes):
        point, integrated = locnodes
        temp = float(point.find("temperature").get("value"))
        precipitation = float(integrated.find("precipitation").get("value"))
        kind = integrated.find("symbol").get("id").lower()

        return temp, precipitation, kind

    def _reparse_weather(self, doc):
        tree = ET.ElementTree(doc)
        now = datetime.utcnow()
        try:
            forecast = self._forecast_by_date(tree, now)
        except IndexError:
            now = now + timedelta(seconds=3601)
            forecast = self._forecast_by_date(tree, now)

        weather = [self._parse_forecast(forecast)]
        for offs in [6, 9]:
            forecast = self._forecast_by_date(tree, now + timedelta(seconds=offs*3600+1))
            weather.append(self._parse_forecast(forecast))

        return weather

    def _get_weather_buffer(self):
        doc = self._get_weather_cached()
        if doc is not None:
            self._weather = self._reparse_weather(doc)

        if self._weather is None:
            buf = "{:20s}no weather data".format("")
        else:
            temp_format = "{:+5.1f}  "
            kind_format = "{:5s}  "
            weather = self._weather
            temps = [node[0] for node in weather]
            kinds = [node[2] for node in weather]

            kind_names = [kind if len(kind) <= 5 else self.longwordmap.get(kind, kind[:5])
                          for kind in kinds]
            buf = "{:5s}  {:5s}  {:5s} ".format("now", "+6h", "+9h")
            buf += (temp_format*3)[:-1].format(*temps)
            buf += (kind_format*3)[:-1].format(*kind_names)
        return buf

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
        now = datetime.utcnow() + timedelta(seconds=120*60)
        date = now.strftime("%a, %d. %b, %H:%M")
        return self._hexBuffer("{0:20s}".format(date) + self._get_weather_buffer())

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
        self.scheduler.add(
            "update-weather",
            600.0,
            self._update_weather_cache,
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
        # print(raw)
        # if raw.startswith("update page "):
        #     print(raw.split(" ")[3])
        #     print("page contents: \n{}".format(binascii.a2b_hex(raw.split(" ")[3].strip().encode("ascii")).decode("hd44780a00")))
        self.send_message(mto=self.LCD, mbody=raw, mtype="chat")

    def messageMUC(self, msg):
        if msg["mucnick"] == self.nick:
            return
        contents = msg["body"].strip()
        if contents == "ping":
            self.reply(msg, "pong")
            return

    def message(self, msg):
        if str(msg["from"].bare) == self.LCD:
            self.send_message(
                mto=self.bots_switch,
                mbody="lcd said: {}".format(msg["body"]),
                mtype="groupchat"
            )

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
