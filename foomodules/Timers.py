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
