import abc
import logging

from datetime import datetime, timedelta

import foomodules.Base as Base
import foomodules.URLLookup as URLLookup

class Pong(Base.MessageHandler):
    def __call__(self, msg, errorSink=None):
        if msg["body"].strip().lower() == "ping":
            self.reply(msg, "pong")
            return True


class IgnoreList(Base.MessageHandler):
    def __init__(self, message="I will ignore you.",
                 initial=[], **kwargs):
        super().__init__(**kwargs)
        self.message = message
        self.ignoredJids = set(initial)

    def __call__(self, msg, errorSink=None):
        bare = str(msg["from"].bare)
        if bare in self.ignoredJids:
            return
        self.ignoredJids.add(bare)
        self.reply(msg, self.message)


class NumericDocumentMatcher(Base.MessageHandler):
    def __init__(self, document_regexes, url_lookup, **kwargs):
        super().__init__(**kwargs)
        self.document_regexes = list(map(self._complete_docex, document_regexes))
        self.url_lookup = url_lookup

    @staticmethod
    def _complete_docex(docex):
        if len(docex) == 2:
            return docex[0], docex[1], lambda x, y: (x, y)
        else:
            return docex

    def __call__(self, msg, errorSink=None):
        contents = msg["body"]

        for regex, document_format, converter in self.document_regexes:
            for match in regex.finditer(contents):
                groups = match.groups()
                groupdict = match.groupdict()
                groups, groupdict = converter(groups, groupdict)
                document_url = document_format.format(*groups, **groupdict)

                try:
                    iterable = iter(self.url_lookup.processURL(document_url))
                    first_line = next(iterable)
                    self.reply(msg, "<{0}>: {1}".format(document_url, first_line))
                    for line in iterable:
                        self.reply(msg, line)
                except URLLookup.URLLookupError as err:
                    self.reply(msg, "<{0}>: sorry, couldn't look it up: {1}".format(document_url, str(err)))
                    pass


class BroadcastMessage(Base.XMPPObject, metaclass=abc.ABCMeta):
    def __init__(self, targets, mtype="chat", **kwargs):
        super().__init__(**kwargs)
        self.targets = targets
        self.mtype = mtype

    @abc.abstractmethod
    def _get_message(self, target):
        pass

    def _send_message(self, target):
        text = self._get_message(target)
        logging.info("sending %s to %s with mtype %s", text, target, self.mtype)
        self.xmpp.send_message(target, text, mtype=self.mtype)

    def __call__(self):
        for target in self.targets:
            self._send_message(target)

class BroadcastDynamicMessage(BroadcastMessage):
    def __init__(self, targets, mgen, **kwargs):
        super().__init__(targets, **kwargs)
        self.mgen = mgen

    def _get_message(self, target):
        return self.mgen(target)

class BroadcastStaticMessage(BroadcastMessage):
    def __init__(self, targets, text, **kwargs):
        super().__init__(targets, **kwargs)
        self.text = text

    def _get_message(self, target):
        return self.text

class SYNACK(Base.MessageHandler):
    def __init__(self,
            timeout=10,
            timeout_message="handshake timed out",
            abort=True,
            send_rst=True,
            process_fin=True,
            **kwargs):
        super().__init__(**kwargs)
        self.timeout = float(timeout)
        self.timeout_message = timeout_message
        self.abort = abort
        self.pending_acks = {}
        self.process_fin = process_fin
        self.established = set()
        self.send_rst = send_rst

    def _get_uid(self, jid):
        return "{0!r}.{1!s}".format(self, jid)

    def _syn(self, msg):
        jid = msg["from"]
        try:
            uid, mode = self.pending_acks[str(jid)]
            self.xmpp.scheduler.remove(uid)
        except KeyError:
            uid = self._get_uid(jid)
            mode = "syn"
            self.pending_acks[str(jid)] = (uid, mode)

        if mode == "fin":
            self.reply(msg, "RST")
            del self.established[str(jid)]
            del self.pending_acks[str(jid)]
            return

        self.xmpp.scheduler.add(
            uid,
            self.timeout,
            lambda: self._timeout_syn(msg)
        )
        self.reply(msg, "SYN ACK")

    def _ack(self, msg):
        jid = msg["from"]
        jidstr = str(jid)
        try:
            uid, mode = self.pending_acks.pop(jidstr)
        except KeyError:
            if not jidstr in self.established:
                self.reply(msg, "RST")
            # no syn before
            return

        if mode == "rst":
            self.xmpp.scheduler.remove(uid)
            self.established.remove(jidstr)
        elif mode == "syn":
            self.xmpp.scheduler.remove(uid)
            if self.process_fin:
                self.established.add(jidstr)

    def _fin(self, msg):
        if not self.process_fin:
            return
        jid = msg["from"]
        if not jid in self.established:
            self.reply(msg, "RST")
            return

        uid = self._get_uid(jid)
        self.pending_acks[str(jid)] = uid, "rst"
        self.reply(msg, "FIN ACK")
        self.xmpp.scheduler.add(
            uid,
            self.timeout,
            lambda: self._timeout_fin(msg)
        )

    def _timeout_syn(self, msg):
        self.prefixed_reply(msg, self.timeout_message)
        del self.pending_acks[str(msg["from"])]

    def _timeout_fin(self, msg):
        self.reply(msg, "FIN ACK")

    def __call__(self, msg, errorSink=None):
        body = msg["body"].strip().lower()
        if body == "syn":
            self._syn(msg)
            return self.abort
        elif body == "ack":
            self._ack(msg)
            return self.abort
        elif body == "fin":
            self._fin(msg)
            return self.abort
        return False

class CTCP(Base.MessageHandler):
    def __init__(self,
            versionstr,
            dateformat="%a %d %b %Y %H:%M:%S UTC"):
        self._versionstr = versionstr
        self._dateformat = dateformat

    def __call__(self, msg, errorSink=None):
        if msg["mtype"] != "chat":
            return False

        body = msg["body"].strip()
        if not body.startswith("\u0001") or body.startswith("CTCP"):
            return False

        #body = body[5:]
        #if body.startswith("VERSION"):
        #    self.reply(msg, self._versionstr)
        #elif body.startswith("TIME"):
        #    self.reply(msg, datetime.utcnow().strftime(self._dateformat))
        #elif body.startswith("PING"):
        #    self.reply(msg, body)

        # Until we have found out on how to properly send NOTICEs, we'll
        # just ignore these messages

        return True
