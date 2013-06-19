import abc
from datetime import datetime, timedelta

import infomodules.utils

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

class Weather(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def __call__(self):
        """
        Get current forecast data. This may use a cache.

        Return the forecast data in a dictionary of the following
        format:

            {
                (year, month, day, hour): <Forecast instance>
            }
        """

    def get_current(self):
        """
        Get the most current forecast entry.

        Return the forecast as tuple of
        ``(date, <Forecast instance>)``. Date is set to the date for
        which the forecast actually applies (which might be in the past
        or in the future).
        """

        forecast = self()
        now = datetime.utcnow()
        key = infomodules.utils.date_to_key(now)

        if key not in forecast or forecast[key].temperature is None:
            now += timedelta(seconds=3600)
            key = infomodules.utils.date_to_key(now)

        now = datetime(now.year, now.month, now.day, now.hour)

        return (now, forecast[key])
