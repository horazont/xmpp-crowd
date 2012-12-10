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
    warning_messages = [
        "Hey, I need a break please",
        "Sorry, I'm busy with guessing your root password",
        "It's so noisy in here, I could not properly understand you. Maybe wait until there's less stuff going on?",
        "Meh, I'm already running metasploit on your host, cannot do so many things at one time",
        "Please give me a break, I'm trying to factorize your SSH key in the other thread",
        "Please slow down a bit, I'm busy with factorizing your GPG key in a forked instance",
    ]

    def __init__(self, cmds_per_minute,
            warning_messages=None,
            **kwargs):
        self.cmds_per_minute = cmds_per_minute
        self.limit_dict = {}
        self.warning_messages = warning_messages or self.warning_messages
        kwargs.pop("do", None)
        super().__init__(10, do=[self._decrease])

    def _xmpp_changed(self, old_value, new_value):
        self.limit_dict = {}

    def _decrease(self):
        self.limit_dict = dict(
            (k, max(0, v-int(math.ceil(self.cmds_per_minute/6))))
            for k, v in self.limit_dict.items())

    @property
    def warning_message(self):
        return random.choice(self.warning_messages)

    def check_and_count(self, msg):
        rate_limit_key = str(msg["from"]), msg["type"]
        try:
            value = self.limit_dict[rate_limit_key]
            if value > self.cmds_per_minute:
                return False
            else:
                self.limit_dict[rate_limit_key] += 1
        except KeyError:
            self.limit_dict[rate_limit_key] = 1
        return True
