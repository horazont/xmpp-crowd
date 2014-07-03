#!/usr/bin/python3
from hub import HubBot
from datetime import datetime, timedelta
import math
import binascii
import traceback
import logging
import sys
import os
import lcdencode
import infomodules.utils
import infomodules.rrdsink
from sleekxmpp.exceptions import IqError, IqTimeout
from sleekxmpp.xmlstream import ET
from sleekxmpp import Iq, Message
from sleekxmpp.xmlstream import register_stanza_plugin, ElementBase, ET, JID

xmlns = "http://xmpp.zombofant.net/xmlns/public-transport"

class SafeCallback(object):
    @staticmethod
    def _default_error_handler(exc_type, exc_value, exc_traceback):
        print("During safe callback:")
        traceback.print_exception(exc_type, exc_value, exc_traceback)


    def __init__(self, callback, error_handler=None):
        self._callback = callback
        self._error_handler = error_handler if error_handler is not None \
            else self._default_error_handler

    def __call__(self, *args, **kwargs):
        try:
            return self._callback(*args, **kwargs)
        except:
            self._error_handler(*sys.exc_info())

class Departure(ElementBase):
    namespace = xmlns
    name = "departure"
    plugin_attrib = name
    interfaces = set()

class Data(ElementBase):
    namespace = xmlns
    name = "data"
    plugin_attrib = name
    interfaces = set()

class DepartureTime(ElementBase):
    namespace = xmlns
    name = "dt"
    plugin_attrib = name
    interfaces = set(("eta", "destination", "lane"))

    def get_eta(self):
        return float(self._get_attr("eta"))

    def set_eta(self, value):
        self._set_attr("eta", "{:d}".format(value))

register_stanza_plugin(Iq, Departure)
register_stanza_plugin(Departure, Data)
register_stanza_plugin(Data, DepartureTime, iterable=True)


class InfoBot(HubBot):
    longwordmap = {
        "partlycloud": "ptcld",
        "lightrain": "lrain",
        "lightrainsun": "lrmix",
        }

    SENSOR_NS = "http://xmpp.sotecware.net/xmlns/sensor"

    def __init__(self, config_file):
        self._config_file = config_file
        self.initialized = False

        error = self.reload_config()
        if error:
            traceback.print_exception(*error)
            sys.exit(1)

        self.initialized = True
        credentials = self.config_credentials
        self.notification_to = credentials.get("notify", None)

        self.hooks_setup = False

        super().__init__(
            credentials["localpart"],
            credentials.get("resource", "core"),
            credentials["password"]
            )
        del credentials["password"]

        nickname = credentials.get("nickname", credentials["localpart"])
        self.bots_switch, self.nick = self.addSwitch("bots", nickname)
        self.add_event_handler("presence", self.handle_presence)
        self._custom_temperature = None

    def reload_config(self):
        namespace = {}
        with open(self._config_file, "r") as f:
            conf = f.read()

        global_namespace = dict(globals())
        global_namespace["xmpp"] = self
        try:
            exec(conf, global_namespace, namespace)
        except Exception:
            return sys.exc_info()

        new_credentials = namespace.get("credentials", {})
        self.config_credentials = new_credentials
        self.departure = namespace.get("departure", None)
        self.weather = namespace.get("weather", None)
        self.lcd = namespace["lcd"]
        self.lcd_resource = namespace["lcd_resource"]
        self.lcd_full = self.lcd + "/" + self.lcd_resource
        self.authorized_jids = frozenset(namespace["authorized_jids"])
        self._sensors = {}
        self._lcd_away = False
        self._weather_buffer = None
        self._departure_buffers = []
        self._weather_data = None
        self._config_update_output = namespace.get("update_output")
        self._last_weather_update = None
        self._weather_timeout = namespace.get(
            "weather_timeout",
            timedelta(seconds=1800))

        return None

    def _notify(self, msg):
        self.send_message(
            mto=self.bots_switch,
            mbody="{notify}: {msg}".format(
                self.notification_to,
                msg),
            mtype="groupchat")

    def _format_weather_buffer(self, data):
        if data is not None:
            to_show = [("now", data[0]),
                       ("+6h", data[6]),
                       ("+9h", data[9])]

            timeline, templine, whichline = "", "", ""
            for i, (time, forecast) in enumerate(to_show):
                timeline += "{:5s}  ".format(time)

                if i == 0 and self._custom_temperature:
                    temp = self._custom_temperature
                else:
                    temp = forecast.temperature
                templine += "{:+5.1f}  ".format(temp)

                symbol = forecast.symbol.lower()

                whichline += "{:5s}  ".format(
                    self.longwordmap.get(symbol, symbol[:5])
                    )

            timeline = timeline[:20]
            templine = templine[:20]
            whichline = whichline[:20]
        else:
            timeline = " "*20
            templine = "{:^20s}".format("No weather data")
            whichline = " "*20


        localnow = datetime.utcnow() + timedelta(seconds=60*60)
        dateline = localnow.strftime("%H:%M") + "  "

        temps = [forecast.temperature for forecast in data
                 if forecast.temperature is not None]
        precp = [forecast.precipitation for forecast in data[:12]
                 if forecast.precipitation is not None]
        dateline += "<{:+3.0f} >{:+3.0f}".format(max(temps), min(temps))
        dateline += "  {:2.0f}".format(sum(precp))

        return dateline+timeline+templine+whichline

    @staticmethod
    def _error_buffer(msg):
        return " "*20 + "{:^20s}".format(msg) + " "*40

    @staticmethod
    def _extract_next_weather(forecast):
        now = datetime.utcnow()
        key = infomodules.utils.date_to_key(now)

        if key not in forecast or forecast[key].temperature is None:
            now += timedelta(seconds=3600)
            key = infomodules.utils.date_to_key(now)

        data = list(map(
                forecast.get,
                map(
                    infomodules.utils.date_to_key,
                    (now + timedelta(seconds=3600*i)
                    for i in range(0,25)))))
        return data

    def _update_weather(self):
        forecast = self.weather()
        if forecast is None:
            if (self._last_weather_update is not None
                    and (self._last_weather_update - datetime.utcnow()) > self._weather_timeout):
                self._weater_data = None
                self._notify("weather service unreachable")
            return
        data = self._extract_next_weather(forecast)
        self._weather_data = data
        self._last_weather_update = datetime.utcnow()

    @classmethod
    def _format_departure(cls, departure):
        return "{:2s} {:14s} {:2d}".format(
            departure[0][:2],
            departure[1][:14],
            departure[2])

    @classmethod
    def _format_departure_buffer(cls, block):
        return "".join(map(cls._format_departure, block))

    @classmethod
    def _format_departure_buffers(cls, departures):
        blocks = [departures[i*4:i*4+4]
                  for i in range(math.ceil(len(departures)/4))]
        return list(map(cls._format_departure_buffer, blocks))

    def _update_departures_and_lcd(self):
        departures = self.departure()
        #~ if departures is None:
            #~ self._departure_buffers = [
                #~ self._error_buffer("No data available"),
                #~ self._error_buffer("No data available"),
                #~ ]
        #~ else:
            #~ self._departure_buffers = self._format_departure_buffers(departures)
#~
        #~ self._update_lcd()

        request = self.Iq()
        for lane, dest, remaining_time in departures:
            dt = DepartureTime()
            dt['eta'] = int(remaining_time)
            dt['destination'] = dest
            dt['lane'] = lane
            request['departure']['data'].append(dt)

        request['to'] = 'hintd@hub.sotecware.net/devel-c'
        request['type'] = 'set'
        request.send(callback=lambda x: None)

    def _read_sensors(self):
        if self._lcd_away:
            return {}
        return {} # FIXME

        iq = self.make_iq_get(queryxmlns=self.SENSOR_NS, ito=self.lcd_full)
        try:
            result = iq.send(block=True, timeout=10)
        except IqTimeout:
            return {}
        except IqError:
            return {}

        query = result.xml.find("{{{}}}query".format(self.SENSOR_NS))
        if not query:
            return {}

        sensors = dict(self._sensors)
        sensor_tag = "{{{}}}sensor".format(self.SENSOR_NS)
        for child in query:
            if child.tag != sensor_tag:
                continue
            value = int(child.get("value")) / 16.0
            if -40 <= value <= 135:
                timestamp = datetime.utcnow()
                sensors.setdefault(child.get("serial"), []).append(
                    (timestamp, value))
            else:
                logging.warning("received possible bogus value from "
                                "sensor %s: %f",
                                child.get("serial"),
                                value)
        return sensors

    def _update_sensors(self):
        self._sensors = self._read_sensors()

    def _update_output(self):
        sensors = dict(self._sensors)
        self._sensors = dict()
        self._config_update_output(self, sensors)

    @staticmethod
    def _encode_for_lcd(data):
        return binascii.b2a_hex(data.replace("ß", "ss").encode("hd44780a00")).decode("ascii")

    def _write_lcd(self, command):
        # print("-> " + command)
        self.send_message(mto=self.lcd, mbody=command, mtype="chat")

    def _update_lcd(self):
        if self._lcd_away:
            return



        #~ self._weather_buffer = self._format_weather_buffer(self._weather_data)
        #~ # print(self._weather_buffer)
#~
        #~ for i, dep_page in enumerate(self._departure_buffers[:2]):
            #~ self._write_lcd("update page {} {}".format(i, self._encode_for_lcd(dep_page)))
#~
        #~ if self._weather_buffer is not None:
            #~ self._write_lcd("update page 2 {}".format(self._encode_for_lcd(self._weather_buffer)))


    def _error_handler(self, exc_type, exc_value, exc_traceback):
        traceback.print_exception(exc_type, exc_value, exc_traceback)

        body = "During callback: {!s}: {!s}. Traceback logged to stderr.".format(exc_type, exc_value)
        if self.notification_to is not None:
            body = "{}: {}".format(self.notification_to, body)

        self.send_message(
            mto=self.bots_switch,
            mbody=body,
            mtype="groupchat")

    def set_custom_temperature(self, value):
        self._custom_temperature = value

    def sessionStart(self, event):
        super().sessionStart(event)
        if not self.hooks_setup:
            self.scheduler.add(
                "update-sensors",
                5.0,
                SafeCallback(self._update_sensors,
                             error_handler=self._error_handler),
                repeat=True)
            self.scheduler.add(
                "update-output",
                15,
                SafeCallback(self._update_output,
                             error_handler=self._error_handler),
                repeat=True)
            self.hooks_setup = True
        self.update_all()

    def _format_text_weather(self, forecasts, index):
        precipitation = sum(forecast.precipitation
                            for forecast in forecasts[:index+1])
        forecast = forecasts[index]
        if index == 0 and self._custom_temperature is not None:
            T = self._custom_temperature
            tempnote = "†"
        else:
            T = forecast.temperature
            tempnote = ""
        return "{T:.1f}°C{tempnote}. Until then approx. {p:.1f} mm precipitation, {symbol} weather.".format(
            T=T,
            tempnote=tempnote,
            p=precipitation,
            symbol=forecast.symbol.lower().replace("partlycloud", "PARTYCLOUD"))

    def get_weather(self, orig_msg):
        forecast = self.weather()
        data = self._extract_next_weather(forecast)

        keys = [("now", 0),
                ("+3h", 3),
                ("+6h", 6),
                ("+9h", 9),
                ("+12h", 12)]

        lines = []
        for name, idx in keys:
            lines.append("{}: {}".format(
                    name,
                    self._format_text_weather(data, idx)
                    ))
        self.reply(orig_msg, "\n".join(lines))

    def messageMUC(self, msg):
        if msg["mucnick"] == self.nick:
            return
        contents = msg["body"].strip()
        if contents == "ping":
            self.reply(msg, "pong")
            return

    def message(self, msg):
        if not msg["from"].bare in self.authorized_jids:
            return

        body = msg["body"].strip()
        if body == "get_weather":
            self.get_weather(msg)
            return
        elif body == "get_sensors":
            self.reply(msg, repr(self._sensors))
            return
        elif body == "debug":
            self.reply(msg, repr(self._departure_buffers))
            self.reply(msg, repr(self._weather_buffer))
            self.reply(msg, repr(self._sensors))
            self.reply(
                msg,
                "custom temp: {!r}".format(self._custom_temperature))
            return
        elif body == "force_flush":
            self._update_output()
            return

    def handle_presence(self, pres):
        if pres["from"].bare == self.lcd:
            if pres["type"] == "available":
                print("lcd available")
                was_away = self._lcd_away
                self._lcd_away = False
                if was_away:
                    self.update_all()
            else:
                print("lcd went {}".format(pres["type"]))
                self._lcd_away = True
                self._sensors = {}

    def update_all(self):
        self._update_weather()
        self._update_departures_and_lcd()
        self._update_sensors()

if __name__=="__main__":
    try:
        import setproctitle
        setproctitle.setproctitle("infobot")
    except ImportError:
        pass
    logging.basicConfig(level=logging.INFO,
                        format='%(levelname)-8s %(message)s')

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

    bot = InfoBot(args.config_file)
    bot.run()
