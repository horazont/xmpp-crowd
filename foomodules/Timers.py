import foomodules.Base as Base

import logging
import random
import time
import itertools
from datetime import datetime, timedelta

class Timer(Base.XMPPObject):
    def __init__(self, do=[], **kwargs):
        super().__init__(**kwargs)
        self._do = do
        self._uid = str(self)+str(time.time())+str(random.randint(0, 65535))

    def _xmpp_changed(self, old_value, new_value):
        for cmd in filter(lambda x: isinstance(x, Base.XMPPObject), self._do):
            cmd.XMPP = new_value

class RepeatingTimer(Timer):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._loaded = False

    def _xmpp_changed(self, old_value, new_value):
        super()._xmpp_changed(old_value, new_value)
        if old_value is not None and self._loaded:
            old_value.scheduler.remove(self._uid)
            self._loaded = False
        if new_value is not None:
            self._load()

    def _load(self):
        delay = (self._calc_next_trigger() - datetime.utcnow()).total_seconds()
        logging.info("repeating timer loaded with Δt=%.4fs", delay)
        self.XMPP.scheduler.add(
            self._uid,
            delay,
            self._on_timer
        )
        self._loaded = True

    def _on_timer(self):
        for cmd in self._do:
            cmd()


class EachDay(RepeatingTimer):
    def __init__(self, at=(0, 0, 0), **kwargs):
        self._at = tuple((v for v in itertools.chain(at, itertools.repeat(0, 4-len(at)))))
        super().__init__(**kwargs)

    def _calc_next_trigger(self):
        date = datetime.utcnow()
        hms = (date.hour, date.minute, date.second)
        if hms >= self._at:
            date += timedelta(days=1)
        return datetime(date.year, date.month, date.day, *self._at)

class EveryInterval(RepeatingTimer):
    def __init__(self, interval, **kwargs):
        self.seconds = interval
        super().__init__(**kwargs)

    def _calc_next_trigger(self):
        return datetime.utcnow() + timedelta(seconds=self.seconds)


class RateLimitService(EveryInterval):
    def __init__(self, cmds_per_minute,
            warning_message="Hey, I need a break, please.",
            **kwargs):
        self.cmds_per_minute = cmds_per_minute
        self.limit_dict = {}
        self.warning_message = warning_message
        kwargs.pop("do", None)
        super().__init__(10, do=[self._decrease])

    def _xmpp_changed(self, old_value, new_value):
        self.limit_dict = {}

    def _decrease(self):
        self.limit_dict = dict(
            (k, max(0, v-int(math.ceil(self.cmds_per_minute/6))))
            for k, v in self.limit_dict.items())

    def check_and_count(self, msg):
        rate_limit_key = str(msg["from"]), msg["type"]
        try:
            value = self.rate_limit_map[rate_limit_key]
            if value > self.cmds_per_minute:
                return False
            else:
                self.rate_limit_map[rate_limit_key] += 1
        except KeyError:
            self.rate_limit_map[rate_limit_key] = 1
        return True
