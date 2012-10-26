import abc
import logging

import foomodules.Base as Base
import foomodules.URLLookup as URLLookup

class Pong(Base.MessageHandler):
    def __call__(self, msg, errorSink=None):
        if msg["body"].strip().lower() == "ping":
            self.reply(msg, "pong")
            return True


class IgnoreList(Base.MessageHandler):
    def __init__(self, message="I will ignore you.", **kwargs):
        super().__init__(**kwargs)
        self.message = message
        self.ignoredJids = set()

    def __call__(self, msg, errorSink=None):
        bare = str(msg["from"].bare)
        if bare in self.ignoredJids:
            return
        self.ignoredJids.add(bare)
        self.reply(msg, self.message)


class NumericDocumentMatcher(Base.MessageHandler):
    def __init__(self, document_regexes, url_lookup, **kwargs):
        super().__init__(**kwargs)
        self.document_regexes = document_regexes
        self.url_lookup = url_lookup

    def __call__(self, msg, errorSink=None):
        contents = msg["body"]

        for regex, document_format in self.document_regexes:
            for match in regex.finditer(contents):
                groups = match.groups()
                groupdict = match.groupdict()
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
            **kwargs):
        super().__init__(**kwargs)
        self.timeout = float(timeout)
        self.timeout_message = timeout_message
        self.abort = abort
        self.pending_acks = {}

    def _get_uid(self, jid):
        return "{0!r}.{1!s}".format(self, jid)

    def _syn(self, msg):
        jid = msg["from"]
        try:
            uid = self.pending_acks[str(jid)]
            self.xmpp.scheduler.remove(uid)
        except KeyError:
            uid = self._get_uid(jid)
            self.pending_acks[str(jid)] = uid

        self.xmpp.scheduler.add(
            uid,
            self.timeout,
            lambda: self._timeout(msg)
        )
        self.reply(msg, "SYN ACK")

    def _ack(self, msg):
        jid = msg["from"]
        try:
            uid = self.pending_acks[str(jid)]
        except KeyError:
            # no syn before
            return

        self.xmpp.scheduler.remove(uid)

    def _timeout(self, msg):
        self.prefixed_reply(msg, self.timeout_message)

    def __call__(self, msg, errorSink=None):
        body = msg["body"].strip().lower()
        if body == "syn":
            self._syn(msg)
            return self.abort
        elif body == "ack":
            self._ack(msg)
            return self.abort
        return False

