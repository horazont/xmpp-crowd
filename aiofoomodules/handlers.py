import abc
import argparse
import re
import shlex
import types
import typing

import aioxmpp

from .utils import get_simple_body


class MessageHandled(Exception):
    pass


class AbstractHandler(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def analyse_message(
            self, ctx,
            message: aioxmpp.Message) -> typing.Iterable[typing.Coroutine]:
        return None
        yield

    async def setup(self, client: aioxmpp.Client):
        pass


class AbstractCommandHandler(metaclass=abc.ABCMeta):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @abc.abstractmethod
    def parse_message(
            self,
            ctx,
            arg0: str,
            args: str) -> typing.Coroutine:
        return

    async def setup(self, client: aioxmpp.Client):
        pass


class _ArgparseError(Exception):
    pass


class _ArgumentParser(argparse.ArgumentParser):
    def exit(self, status=0, message=None):
        pass

    def error(self, message):
        raise _ArgparseError(message)


class ArgparseCommandHandler(AbstractCommandHandler):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._parser = _ArgumentParser()

    def parse_message(self, ctx, arg0: str, args: str) -> typing.Coroutine:
        try:
            args = self._parser.parse_args(shlex.split(args))
        except _ArgparseError as exc:
            ctx.reply_direct(str(exc))
            return
        except BaseException as exc:
            ctx.reply_direct("internal error")
            return

        return self._execute(ctx, args)

    @abc.abstractmethod
    async def _execute(self, ctx, args):
        pass


class CommandDispatcher(AbstractHandler):
    def __init__(self):
        super().__init__()
        self._commands = {}
        self._command_match = re.compile(r"^$")

    def _rebuild_re(self):
        self._command_match = re.compile("^({})$".format(
            "|".join(map(re.escape, self._commands.keys()))
        ), re.I)

    async def setup(self, client: aioxmpp.Client):
        for cmd_handler in self._commands.values():
            await cmd_handler.setup(client)

    def analyse_message(
            self, ctx,
            message: aioxmpp.Message) -> typing.Iterable[typing.Coroutine]:
        body = get_simple_body(message)
        cmd = body.split()[0]
        if not cmd:
            return

        cmd_match = self._command_match.match(cmd)
        if not cmd_match:
            return

        cmd_handler = self._commands[cmd]
        args = body[len(cmd)+1:]
        yield cmd_handler.parse_message(ctx, cmd, args)

    def register_command(self, arg0: str, handler: AbstractCommandHandler):
        if arg0 in self._commands:
            raise ValueError("command already registered: {!r}".format(arg0))

        self._commands[arg0] = handler
        self._rebuild_re()
