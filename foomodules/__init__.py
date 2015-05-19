import importlib
import imp
import sys
import traceback
import itertools
import logging
import os
import math

import foomodules.Commands as Commands
import foomodules.Base as Base
import foomodules.urllookup as urllookup
import foomodules.Misc as Misc
import foomodules.InfoStore as InfoStore
import foomodules.Timers as Timers
import foomodules.GitLog as GitLog
import foomodules.SympyInterface as SympyInterface
import foomodules.Poll as Poll
import foomodules.Log as Log
import foomodules.CountDown as CountDown

logger = logging.getLogger(__name__)

class FoorlConfig(object):
    def __init__(self, import_name, import_path=None, **kwargs):
        super().__init__(**kwargs)
        self.rooms = frozenset()
        self.xmpp = None
        self.hooks = {}
        self.bindings = {}
        self.errorSink = None
        self.generic = []
        if import_path:
            import_path = os.path.abspath(import_path)
            logging.debug("Adding path %s to python path for config import", import_path)
            sys.path.insert(0, import_path)
        self.module = importlib.import_module(import_name)
        self.reload()

    def reload(self):
        oldRooms = self.rooms
        imp.reload(self.module)
        for hook in self.hooks.get("session_end", []):
            hook()
        for generic in self.generic:
            generic.XMPP = None
        self.errorSink = self.module.errorSink
        if self.xmpp:
            self.muc = self.xmpp["xep_0045"]
        else:
            self.muc = None

        if self.xmpp:
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
        self.generic = self.module.generic
        if self.xmpp is not None:
            self.propagateXMPP()
        for hook in self.hooks.get("session_start", []):
            hook()

    def session_start(self, xmpp):
        self.xmpp = xmpp
        self.reload()

    def propagateXMPP(self):
        for binding in itertools.chain(self.bindings.values(), self.generic):
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
                    logger.info("Dropping message from %s -- no matching binding", msg["from"])
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

    def __str__(self):
        return "{0}#{1}".format(self.fromJid, self.mtype)

class Bind(Base.MessageHandler):
    def __init__(self, *handlers, errorSink=None, ignoreSelf=True,
            debug_memory_use=False, **kwargs):
        super().__init__(**kwargs)
        self.handlers = handlers
        self.errorSink = errorSink
        self.xmpp = None
        self.ignoreSelf = ignoreSelf
        self.ourJid = None
        self.debug_memory_use = debug_memory_use

    def _xmpp_changed(self, old_value, new_value):
        for handler in self.handlers:
            handler.XMPP = new_value

    def dispatch(self, msg):
        mtype = msg["type"]
        if self.ignoreSelf and msg["from"] == self.ourJid:
            return
        if self.debug_memory_use:
            print("MEMDEBUG: before dispatch")
            import objgraph
            objgraph.show_growth()
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
        finally:
            if self.debug_memory_use:
                print("MEMDEBUG: after dispatch")
                import objgraph
                objgraph.show_growth()

class CommandListener(Base.PrefixListener):
    def __init__(self, commands, prefix="", verbose=False,
            **kwargs):
        super().__init__(prefix, **kwargs)
        self.commands = commands
        self.xmpp = None
        self.verbose = verbose

    def _xmpp_changed(self, old_value, new_value):
        for handler in self.commands.values():
            handler.XMPP = new_value

    def _prefix_matched(self, msg, contents, errorSink=None):
        command, sep, arguments = contents.partition(" ")

        try:
            handler = self.commands[command]
        except KeyError:
            if self.verbose:
                self.reply(msg, "I don't know what {0} should mean."\
                        .format(command))
            logger.info("Received unknown command %r from %s", command, str(msg["from"]))
            return False

        if not self.check_count_and_reply(msg):
            return False
        return handler(msg, arguments, errorSink=errorSink)
