import argparse
import re

from datetime import datetime, timedelta

import foomodules.Base as Base
import foomodules.utils as utils

import hintmodules.weather.stanza as weather_stanza
import hintmodules.sensor.stanza as sensor_stanza
import hintmodules.weather.utils

OFFSET_RE = re.compile(
    r"^(\+|-)(([0-9]+)d)?\s*(([0-9]+)h)$",
    re.I)

formats = [
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d",
    "%H:%M:%S",
]

class Weather(Base.ArgparseCommand):
    BEARING_ARROWS = "↑↗→↘↓↙←↖"

    def __init__(self,
                 peer,
                 service_uri,
                 command_name="weather",
                 default_coords=None,
                 interval_pattern=[3, 3, 6, 6, 6],
                 **kwargs):
        super().__init__(command_name, **kwargs)

        self.uri = service_uri
        self.peer = peer
        self.interval_pattern = interval_pattern

        arg = self.argparse.add_argument(
            "-c", "--coords",
            dest="geocoords",
            metavar="LAT LON",
            nargs=2,
            help="Geocoordinates for which to retrieve a forecast. Specify as -c"
                 "lat lon"
        )

        if default_coords is not None:
            arg.default = default_coords
            arg.help += " [default: {}]".format(" ".join(map(str, arg.default)))

        self.argparse.add_argument(
            "-t", "--at", "--time",
            metavar="WHEN",
            dest="time",
            help="Time for which to retrieve a forecast. The date will be"
                 "truncated to a full hour (rounding towards the"
                 "future). [default: now]")

        self.argparse.formatter_class = argparse.RawDescriptionHelpFormatter

        now = datetime.utcnow()

        self.argparse.epilog = now.strftime("""
WHEN can either be an absolute timestamp in one of the following forms:

* %Y-%m-%dT%H:%M:%S
* %Y-%m-%dT%H:%M
* %Y-%m-%d
* %H:%M:%S

or a relative specifier (starting with a `+`) denoting the offset, for example:

* +1h (plus one hour)
* +1d2h (plus one day and two hours)
"""
        )

    def round_date(self, dt):
        if (dt.minute, dt.second, dt.microsecond) != (0, 0, 0):
            dt += timedelta(hours=1)

        return dt.replace(minute=0, second=0, microsecond=0)

    def rounded_now(self):
        return self.round_date(datetime.utcnow())

    def _call(self, msg, args, errorSink=None):
        try:
            lat, lon = args.geocoords
        except (ValueError, TypeError):
            self.reply(msg,
                       "specification of coordinates required, use -c LAT LON")
            return

        try:
            lat = float(lat)
            lon = float(lon)
        except ValueError as err:
            self.reply(msg,
                       str(err))
            return

        time = args.time
        if time is None:
            time = self.rounded_now()
        else:
            match = OFFSET_RE.match(time.strip())
            if match is not None:
                sign, _, days, _, hours = match.groups()
                sign = 1 if sign == "+" else -1

                days = int(days or 0) * sign
                hours = int(hours or 0) * sign

                time = self.rounded_now() + timedelta(
                    days=days,
                    hours=hours)
            else:
                for fmt in formats:
                    try:
                        time = self.round_date(datetime.strptime(time, fmt))
                    except ValueError:
                        pass
                    else:
                        break
                else:
                    self.reply(msg,
                               "could not parse time: {}".format(time))
                    return

        request = self.xmpp.Iq()
        request["to"] = self.peer
        request["type"] = "get"
        request["weather_data"]["location"]["lat"] = lat
        request["weather_data"]["location"]["lon"] = lon
        request["weather_data"]["from"] = self.uri

        start_time = time
        intervals = []
        for duration in self.interval_pattern:
            end_time = start_time + timedelta(hours=duration)

            interval_request = weather_stanza.Interval(
                start=start_time,
                end=end_time,
                parent=request["weather_data"]
            )
            interval_request["precipitation"]
            interval_request["wind_speed"]
            interval_request["wind_direction"]
            interval_request.append(
                weather_stanza.Temperature(
                    type=weather_stanza.Temperature.Type.Air))

            start_time = end_time

        request.send(
            callback=lambda stanza: self.got_reply(msg, stanza)
        )

    def got_reply(self, msg, response):
        data = response["weather_data"]

        values = []

        for interval in data:
            start_time = interval["start"]
            end_time = interval["end"]
            precipitation = interval["precipitation"]["value"]
            wind_speed = interval["wind_speed"]["value"]
            temperature = interval["substanzas"][0]["value"]
            wind_direction = interval["wind_direction"]["value"]

            values.append((
                start_time,
                end_time,
                temperature,
                precipitation,
                wind_speed,
                wind_direction))

        base_time = datetime.utcnow()

        for (start_time, end_time,
             temperature, precipitation, wind_speed, wind_direction) in values:

            start_offset = round(
                (start_time - base_time).total_seconds() / 3600)
            end_offset = round(
                (end_time - base_time).total_seconds() / 3600)

            timetag = "+{}h – +{}h".format(
                start_offset, end_offset)

            line = ("{timetag}: "
                    "{temp:.1f} °C, "
                    "{prec:.1f} mm precipitation, "
                    "{wind_speed:.1f} m/s {wind_bearing}").format(
                        timetag=timetag,
                        temp=hintmodules.weather.utils.kelvin_to_celsius(
                            temperature),
                        prec=precipitation,
                        wind_speed=wind_speed,
                        wind_bearing=self.BEARING_ARROWS[round(wind_direction/45.)])

            self.reply(msg, line)

        if not values:
            self.reply(msg, "sorry, hintbot could not give me any information")


class Sensor(Base.ArgparseCommand):
    def __init__(self,
                 peer,
                 command_name="sensor",
                 alias_map={},
                 whitelist_ids=None,
                 **kwargs):
        super().__init__(command_name, **kwargs)
        self.alias_map = dict(alias_map)
        self.peer = peer
        self.whitelist_ids = whitelist_ids

        self.argparse.add_argument(
            "-t", "--type",
            dest="type_",
            default="T",
            metavar="TYPE",
            help="Sensor type [default: T]"
        )
        self.argparse.add_argument(
            "sensor",
            metavar="ID",
            help="Either a hexadecimal sensor ID or a recognized sensor alias"
        )


    def _call(self, msg, args, errorSink=None):
        sensor_id = self.alias_map.get(args.sensor, args.sensor)
        sensor_type = args.type_

        iq = self.xmpp.Iq()
        iq["to"] = self.peer
        iq["type"] = "get"

        if self.whitelist_ids is None or sensor_id in self.whitelist_ids:
            request = sensor_stanza.Request(
                parent=iq["sensor_data"])
            request["sensor_id"] = sensor_id
            request["sensor_type"] = sensor_type

        iq.send(callback=lambda stanza: self.got_reply(msg, stanza))

    def got_reply(self, msg, stanza):
        try:
            point = next(iter(stanza["sensor_data"]))
        except StopIteration:
            point = None

        if point is None:
            self.reply(msg, "sorry, hintbot could not give me any information")
            return

        self.reply(msg, "{time!s} ago, sensor {sensor_id} read as {v} °C".format(
            time=datetime.utcnow() - point["time"],
            sensor_id=point["sensor_id"],
            v=point["value"]))
