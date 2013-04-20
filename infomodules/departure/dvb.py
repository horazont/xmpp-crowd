import ast
from datetime import datetime, timedelta
import socket
import warnings
import urllib.error

import infomodules.utils

class Departure(object):
    URL = "http://widgets.vvo-online.de/abfahrtsmonitor/Abfahrten.do?ort=Dresden&hst={}"
    MAX_AGE = timedelta(seconds=30)

    def __init__(self, stop_name, user_agent="Departure/1.0"):
        self.url = self.URL.format(stop_name)
        self.user_agent = user_agent
        self.cached_data = None
        self.cached_timestamp = None

    def parse_data(self, s):
        struct = ast.literal_eval(s)
        return [(route, dest, (int(time) if len(time) else 0))
                for route, dest, time
                in struct]

    def get_departure_data(self):
        try:
            response, timestamp = infomodules.utils.http_request(
                self.url,
                user_agent=self.user_agent,
                accept="text/html")  # sic: the api returns plaintext, but Content-Type: text/html

            try:
                contents = response.read().decode()
            finally:
                response.close()
        except socket.timeout as err:
            if self.cached_timestamp is not None and self.cached_data is not None:
                if self.cached_timestamp - datetime.utcnow() <= self.MAX_AGE:
                    return self.cached_data
            raise
        except urllib.error.HTTPError as err:
            if err.code == 304:
                return self.cached_data
            raise

        self.cached_data = self.parse_data(contents)
        self.cached_timestamp = timestamp
        return self.cached_data

    def __call__(self):
        try:
            data = self.get_departure_data()
        except (socket.timeout, urllib.error.URLError, urllib.error.HTTPError) as err:
            warnings.warn(err)
            return None
        data.sort(key=lambda x: x[2])
        return data
