import abc
from datetime import datetime, timedelta

import foomodules.Base as Base

class LogFormat(object, metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def format_message_groupchat(self, msg):
        pass

    @abc.abstractmethod
    def format_presence(self, presence):
        pass

    @abc.abstractmethod
    def format_daychange(self, dt):
        pass

class IRSSILogFormat(LogFormat):
    def format_timestamp(self, timestamp=None):
        timestamp = timestamp or datetime.utcnow()
        return "{h:02d}:{m:02d}:{s:02d}".format(
            h=timestamp.hour,
            m=timestamp.minute,
            s=timestamp.second)

    def format_message_groupchat(self, msg):
        return "{time} < {nick}> {message}".format(
            time=self.format_timestamp(),
            nick=msg["from"].resource,
            message=msg["body"])

    def _format_leave(self, presence):
        return "{time} -!- {nick} has left the room".format(
            time=self.format_timestamp(),
            nick=presence["from"].resource)

    def _format_join(self, presence):
        return "{time} -!- {nick} has joined the room".format(
            time=self.format_timestamp(),
            nick=presence["from"].resource)

    def format_presence(self, presence):
        if presence["type"] == "unavailable":
            return self._format_leave(presence)
        else:
            return self._format_join(presence)

    def format_log_start(self):
        return "{time} -!- logging starts".format(
            time=self.format_timestamp())

    def format_daychange(self):
        dt = datetime.utcnow()
        return "Day changed to {year}-{month}-{day}".format(
            day=dt.day,
            month=dt.month,
            year=dt.year)

class LogToFile(Base.XMPPObject):
    def __init__(self,
                 logfile,
                 target_jid,
                 format,
                 **kwargs):
        super().__init__(**kwargs)
        self._logfile = open(logfile, "a")
        self._target_jid = target_jid
        self._format = format
        self._last_entry = None
        self._start_logging()

    def _log(self, text):
        curr_time = datetime.utcnow()
        if self._last_entry is not None:
            t1 = curr_time.day, curr_time.month, curr_time.year
            t2 = self._last_entry.day, self._last_entry.month, \
                 self._last_entry.year
            if t1 != t2:
                self._logfile.write(self._format.format_daychange() + "\n")
            self._last_entry = datetime.utcnow()
        self._logfile.write(text + "\n")
        self._logfile.flush()

    def _start_logging(self):
        self._log(self._format.format_log_start())

    def _xmpp_changed(self, old_value, new_value):
        super()._xmpp_changed(old_value, new_value)
        if old_value is not None:
            old_value.del_event_handler("presence", self.handle_presence)
            old_value.del_event_handler("groupchat_message", self.handle_message)
        if new_value is not None:
            new_value.add_event_handler("presence", self.handle_presence)
            new_value.add_event_handler("groupchat_message", self.handle_message)

    def handle_presence(self, presence):
        if presence["from"].bare == self._target_jid:
            self._presence(presence)

    def handle_message(self, msg):
        if msg["from"].bare == self._target_jid:
            self._message(msg)

    def _presence(self, presence):
        self._log(self._format.format_presence(presence))

    def _message(self, msg):
        self._log(self._format.format_message_groupchat(msg))
