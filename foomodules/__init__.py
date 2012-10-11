import importlib, imp
import sys, traceback
import foomodules.Commands as Commands
import foomodules.Base as Base
import foomodules.URLLookup as URLLookup
import foomodules.Misc as Misc
import foomodules.InfoStore as InfoStore

class FoorlConfig(object):
    def __init__(self, xmpp, importPath, **kwargs):
        super().__init__(**kwargs)
        self.xmpp = xmpp
        self.rooms = frozenset()
        self.bindings = {}
        self.errorSink = None
        self.module = importlib.import_module(importPath)
        self.reload()

    def reload(self):
        oldRooms = self.rooms
        imp.reload(self.module)
        self.errorSink = self.module.errorSink
        self.muc = self.xmpp["xep_0045"]

        newRooms = frozenset(self.module.rooms)
        self.rooms = newRooms
        toPart = oldRooms - newRooms
        for room, nick in toPart:
            self.leaveRoom(room)
        toJoin = newRooms - oldRooms
        for room, nick in toJoin:
            self.joinRoom(room, nick)

        self.bindings = self.module.bindings
        self.hooks = self.module.hooks
        self.localpart = self.module.localpart
        self.resource = self.module.resource
        self.password = self.module.password
        self.propagateXMPP()

    def propagateXMPP(self):
        for binding in self.bindings.values():
            binding.XMPP = self.xmpp

    def leaveRoom(self, room):
        self.muc.leaveMUC(room)

    def joinRoom(self, room, nick):
        self.muc.joinMUC(room, nick)

    def dispatch(self, msg):
        mtype = msg["type"]
        key = Binding(msg["from"], mtype=mtype)
        try:
            binding = self.bindings[key]
        except KeyError:
            key = Binding(msg["from"].bare, mtype=mtype)
            try:
                binding = self.bindings[key]
            except KeyError:
                key = None
                try:
                    binding = self.bindings[key]
                except KeyError:
                    return

        if mtype == "groupchat":
            binding.ourJid = self.muc.getOurJidInRoom(msg["from"].bare)
        else:
            binding.ourJid = self.xmpp.boundjid

        try:
            binding.dispatch(msg)
        except Exception as err:
            if self.errorSink is not None:
                traceback.print_exc()
                self.errorSink.submit(self.xmpp, err, msg)
            else:
                raise


class ErrorLog(Base.MessageHandler):
    def __init__(self, to=None, **kwargs):
        super().__init__(**kwargs)
        self.to = to

    def submit(self, xmpp, err, origMsg):
        self.xmpp = xmpp
        self.reply(origMsg, "{0}: {1}".format(type(err).__name__, err),
            overrideTo=self.to)


class Binding(object):
    def __init__(self, fromJid, mtype="chat", **kwargs):
        super().__init__(**kwargs)
        self.fromJid = str(fromJid)
        self.mtype = str(mtype)

    def __eq__(self, other):
        try:
            return self.fromJid == other.fromJid and self.mtype == other.mtype
        except AttributeError:
            return NotImplemented

    def __ne__(self, other):
        result = self.__eq__(other)
        return result if result is NotImplemented else not result

    def __hash__(self):
        return hash(self.fromJid) ^ hash(self.mtype)


class Bind(object):
    def __init__(self, *handlers, errorSink=None, ignoreSelf=True, **kwargs):
        super().__init__(**kwargs)
        self.handlers = handlers
        self.errorSink = errorSink
        self.xmpp = None
        self.ignoreSelf = True
        self.ourJid = None

    @property
    def XMPP(self):
        return self.xmpp

    @XMPP.setter
    def XMPP(self, value):
        self.xmpp = value
        for handler in self.handlers:
            handler.XMPP = value

    def dispatch(self, msg):
        mtype = msg["type"]
        if self.ignoreSelf and msg["from"] == self.ourJid:
            return
        try:
            for handler in self.handlers:
                abort = handler(msg, errorSink=self.errorSink)
                if abort:
                    break
        except Exception as err:
            if self.errorSink is not None:
                self.errorSink.submit(self.xmpp, err, msg)
            else:
                raise



class CommandListener(Base.PrefixListener):
    def __init__(self, commands, prefix="", verbose=False, **kwargs):
        super().__init__(prefix, **kwargs)
        self.commands = commands
        self.xmpp = None
        self.verbose = verbose

    @property
    def XMPP(self):
        return self.xmpp

    @XMPP.setter
    def XMPP(self, value):
        self.xmpp = value
        for handler in self.commands.values():
            handler.XMPP = value

    def _prefix_matched(self, msg, contents, errorSink=None):
        command, sep, arguments = contents.partition(" ")

        try:
            handler = self.commands[command]
        except KeyError:
            if self.verbose:
                self.reply(msg, "I don't know what {0} should mean."\
                        .format(command))
            return

        handler(msg, arguments, errorSink=errorSink)

