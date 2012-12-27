import SympyComm
import os
import socket
import re

import foomodules.Base as Base

class Daemon(Base.XMPPObject):
    def __init__(self, executable):
        super().__init__()
        self.executable = executable
        self.childpid = 0
        self.sock = None

    def _kill_child(self):
        os.kill(self.childpid)
        os.waitpid(self.childpid, 0)
        self.childpid = 0
        self.sock = None

    def _spawn_child(self):
        self.sock, slavesock = socket.socketpair()
        pid = os.fork()
        if pid == 0:
            os.execv(self.executable, [self.executable, str(slavesock.fileno())])
        self.childpid = pid
        self.sock.settimeout(3)

    def _respawn_child(self):
        if self.childpid != 0:
            self._kill_child()
        self._spawn_child()

    def _xmpp_changed(self, old_value, new_value):
        if self.childpid != 0:
            self._kill_child()

        if new_value is not None:
            self._spawn_child()

        super()._xmpp_changed(old_value, new_value)

    def __call__(self, expr, unit):
        if self.sock is None:
            raise ValueError("Not connected to a child. This should not happen")

        SympyComm.send_calc(self.sock, unit, expr)
        self.sock.settimeout(3)
        try:
            return SympyComm.recv_result(self.sock)
        except socket.timeout:
            self._respawn_child()
            return False, "server side error: computation timed out"

class Calc(Base.MessageHandler):
    unit_regex = re.compile("^\s*(as|in)\s+(\S+)(.*)$")

    def __init__(self, daemon):
        super().__init__()
        self.daemon = daemon

    def __call__(self, msg, arguments, errorSink=None):
        m = self.unit_regex.match(arguments)
        if m is not None:
            unit = m.group(2).encode("ascii")
            expr = m.group(3).strip()
        else:
            unit = b"1"
            expr = arguments

        state, text = self.daemon(expr.encode("ascii"), unit)
        if not state:
            self.reply(msg, "computation failed: {}".format(text.decode("utf-8")))
        else:
            self.reply(msg, text.decode("utf-8"))
