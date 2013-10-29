import abc
from datetime import datetime, timedelta

import foomodules.Base as Base

class LogFormat(object, metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def format_message_groupchat(self, msg):
        pass

    @abc.abstractmethod
    def format_daychange(self, dt):
        pass

    @abc.abstractmethod
    def format_nickchange(self, oldnick, newnick, presence):
        pass

    @abc.abstractmethod
    def format_join(self, presence):
        pass

    @abc.abstractmethod
    def format_leave(self, presence):
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

    def format_leave(self, presence):
        return "{time} -!- {nick} has left the room".format(
            time=self.format_timestamp(),
            nick=presence["from"].resource)

    def format_join(self, presence):
        return "{time} -!- {nick} has joined the room".format(
            time=self.format_timestamp(),
            nick=presence["from"].resource)

    def format_log_start(self):
        return "{time} -!- logging starts".format(
            time=self.format_timestamp())

    def format_daychange(self):
        dt = datetime.utcnow()
        return "Day changed to {year}-{month}-{day}".format(
            day=dt.day,
            month=dt.month,
            year=dt.year)

    def format_nickchange(self, oldnick, newnick, presence):
        return "{time} -!- {oldnick} is now known as {newnick}".format(
            time=self.format_timestamp(),
            oldnick=oldnick,
            newnick=newnick)

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
        self._known_nicks = set()

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
            old_value.del_event_handler("muc::{}::presence".format(self._target_jid), self.handle_presence)
            old_value.del_event_handler("muc::{}::message".format(self._target_jid), self.handle_message)
        if new_value is not None:
            new_value.add_event_handler("muc::{}::presence".format(self._target_jid), self.handle_presence)
            new_value.add_event_handler("muc::{}::message".format(self._target_jid), self.handle_message)

    def handle_presence(self, presence):
        curr_nick = presence['from'].resource
        item = presence.xml.find('{{{0}}}x/{{{0}}}item'.format('http://jabber.org/protocol/muc#user'))
        new_nick = item.get('nick')
        if curr_nick != new_nick and new_nick is not None:
            self._log(self._format.format_nickchange(curr_nick, new_nick, presence))
            try:
                self._known_nicks.remove(curr_nick)
            except KeyError:
                pass
            self._known_nicks.add(new_nick)
        else:
            if presence['type'] == 'unavailable':
                self._log(self._format.format_leave(presence))
            elif curr_nick not in self._known_nicks:
                self._known_nicks.add(curr_nick)
                self._log(self._format.format_join(presence))

    def handle_message(self, msg):
        self._log(self._format.format_message_groupchat(msg))
