from datetime import datetime, timedelta
import infomodules.utils

import lxml.etree as ET

class Forecast(object):
    temperature = None
    symbol = None
    precipitation = None

    def __init__(self, *args, temp=None, symbol=None, prec=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.temperature = temp
        self.symbol = symbol
        self.precipitation = prec

    def __repr__(self):
        return "Forecast(temp={!r}, symbol={!r}, prec={!r})".format(
            self.temperature,
            self.symbol,
            self.precipitation)

class Weather(object):
    URL = "http://api.met.no/weatherapi/locationforecast/1.8/?lat={lat}&lon={lon}"
    MAX_AGE = timedelta(seconds=60*30)

    @staticmethod
    def get_forecast_attr(locnode, attrname, default=None, valuename="value"):
        try:
            return locnode.find(attrname).get(valuename)
        except AttributeError:
            return default

    def __init__(self, lat, lon, user_agent="Weather/1.0"):
        self.url = self.URL.format(lat=lat, lon=lon)
        self.user_agent = user_agent
        self.cached_data = None
        self.cached_timestamp = None

    def _get_raw_xml(self):
        response, timestamp = infomodules.utils.http_request(
            self.url,
            user_agent=self.user_agent,
            accept="application/xml")

        try:
            contents = response.read().decode()
            return contents, timestamp
        finally:
            response.close()

    def parse_xml(self, tree):
        forecasts = {}
        for forecast in tree.xpath("//time[@datatype='forecast' and @from=@to]"):
            date = datetime.strptime(forecast.get("from"), "%Y-%m-%dT%H:00:00Z")
            key = infomodules.utils.date_to_key(date)

            locnode = forecast.find("location")
            data = Forecast()
            data.temperature = float(self.get_forecast_attr(locnode, "temperature", default=data.temperature))

            forecasts[key] = data

        for integrated in tree.xpath("//time[@datatype='forecast' and @from!=@to]"):
            date = datetime.strptime(integrated.get("from"), "%Y-%m-%dT%H:00:00Z")
            date2 = datetime.strptime(integrated.get("to"), "%Y-%m-%dT%H:00:00Z")
            if date2 - date > timedelta(seconds=3600):
                continue
            key = infomodules.utils.date_to_key(date)

            locnode = integrated.find("location")
            data = forecasts.setdefault(key, Forecast())
            data.precipitation = float(self.get_forecast_attr(locnode, "precipitation", default=data.precipitation))
            data.symbol = self.get_forecast_attr(locnode, "symbol", default=data.symbol, valuename="id")

        return forecasts


    def get_data(self):
        try:
            xml, timestamp = self._get_raw_xml()
        except urllib.error.HTTPError as err:
            if err.code == 304:
                return self.cached_data
            raise
        except socket.timeout as err:
            return self.cached_data
        except urllib.error.URLError as err:
            return self.cached_data

        self.cached_data = self.parse_xml(ET.ElementTree(ET.fromstring(xml)))
        self.cached_timestamp = timestamp
        return self.cached_data

    def __call__(self):
        return self.get_data()
