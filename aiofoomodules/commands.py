import random
import re
import time
import typing

from datetime import timedelta

import aioxmpp
import aioxmpp.forms
import aioxmpp.ping
import aioxmpp.xso

from .handlers import AbstractCommandHandler, ArgparseCommandHandler

from . import argparse_types


@aioxmpp.IQ.as_payload_class
class _UptimeQuery(aioxmpp.xso.XSO):
    TAG = "jabber:iq:last", "query"

    seconds = aioxmpp.xso.Attr(
        "seconds",
        type_=aioxmpp.xso.Integer(),
        default=None,
    )

    message = aioxmpp.xso.Text(
        default=None,
    )


def _find_form(exts):
    for ext in exts:
        if ext.get_form_type() == "http://jabber.org/network/serverinfo":
            return ext


def _reverse_multimap(mapping):
    result = {}
    for key, values in mapping.items():
        for value in values:
            result.setdefault(value, []).append(key)

    return result


class ContactInfoCommand(ArgparseCommandHandler):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._parser.add_argument(
            "target",
            type=argparse_types.jid,
        )

    async def setup(self, client: aioxmpp.Client):
        self._disco_client = client.summon(aioxmpp.DiscoClient)

    async def _execute(self, ctx, args):
        try:
            info = await self._disco_client.query_info(args.target)
        except aioxmpp.errors.XMPPError as exc:
            ctx.reply(
                "failed to query {}: {}".format(
                    args.target, str(exc)
                )
            )
            return

        form = _find_form(info.exts)
        if not form:
            ctx.reply(
                "no contact information published for {}".format(args.target)
            )
            return

        reply = "\n".join(
            "{}: <{}>".format(
                field.var[:-len("-addresses")],
                ">, <".join(field.values),
            )
            for field in form.fields
            if field.var.endswith("-addresses") and field.values
        )

        ctx.reply("contact for {}:\n{}".format(args.target, reply))


class VersionCommand(ArgparseCommandHandler):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._parser.add_argument(
            "target",
            type=argparse_types.jid,
        )

    async def setup(self, client: aioxmpp.Client):
        self._client = client

    async def _execute(self, ctx, args):
        try:
            info = await aioxmpp.version.query_version(self._client.stream,
                                                       args.target)
        except aioxmpp.errors.XMPPError as exc:
            ctx.reply(
                "failed to query {}: {}".format(
                    args.target, str(exc)
                )
            )
            return

        ctx.reply("{} is running {} version {} on {}".format(
            args.target,
            info.name or "unknown",
            info.version or "unknown",
            info.os or "unknown",
        ))


class PingCommand(ArgparseCommandHandler):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._parser.add_argument(
            "target",
            type=argparse_types.jid,
        )

    async def setup(self, client: aioxmpp.Client):
        self._client = client

    async def _execute(self, ctx, args):
        t0 = time.monotonic()
        try:
            info = await aioxmpp.ping.ping(self._client.stream,
                                           args.target)
        except aioxmpp.errors.XMPPError as exc:
            t1 = time.monotonic()
            ctx.reply(
                "failed to ping {} (rtt {:.3f}s) {}".format(
                    args.target, t1 - t0, str(exc)
                )
            )
            return

        t1 = time.monotonic()

        ctx.reply("{}: rtt {:.3f}s".format(
            args.target,
            t1 - t0
        ))


class UptimeCommand(ArgparseCommandHandler):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._parser.add_argument(
            "target",
            type=argparse_types.jid,
        )

    async def setup(self, client: aioxmpp.Client):
        self._client = client

    async def _execute(self, ctx, args):
        try:
            uptime = await self._client.send(
                aioxmpp.IQ(
                    to=args.target,
                    type_=aioxmpp.IQType.GET,
                    payload=_UptimeQuery(),
                )
            )
        except aioxmpp.errors.XMPPError as exc:
            ctx.reply(
                "failed to query {}: {}".format(
                    args.target, str(exc),
                )
            )
            return

        if uptime.seconds is None:
            ctx.reply(
                "invalid reply from {} (@seconds is unset)".format(
                    args.target,
                )
            )
            return

        message = uptime.message
        running_for = timedelta(seconds=uptime.seconds)

        if message:
            ctx.reply("{}: {} ({})".format(
                args.target,
                message,
                running_for
            ))
        elif args.target.is_domain:
            ctx.reply("{}: up for {}".format(
                args.target,
                running_for,
            ))
        else:
            ctx.reply("{}: last activity {} ago".format(
                args.target,
                running_for,
            ))


class RollCommand(AbstractCommandHandler):
    _DICE_RX = re.compile("^((?P<amount>[0-9]+)?[wd])?(?P<faces>[0-9]+)$", re.I)

    def __init__(self, *, aliases={}, rng=None, **kwargs):
        super().__init__()
        self._aliases = aliases.copy()
        self._rng = rng or random.SystemRandom()

    class DiceSpec(typing.NamedTuple):
        amount: int
        faces: int

        def roll(self, rng):
            for i in range(self.amount):
                yield rng.randint(1, self.faces)

        @classmethod
        def fromstr(cls, s):
            m = RollCommand._DICE_RX.match(s.strip())
            if not m:
                raise ValueError("invalid dice spec: {!r}. expected XdY".format(
                    s
                ))
            info = m.groupdict()
            amount_s = info.get("amount")
            if amount_s is None:
                amount = 1
            else:
                amount = int(amount_s)
            faces = int(info["faces"])
            return cls(amount, faces)

    def _parse(self, s):
        try:
            return self._aliases[s]
        except KeyError:
            pass
        return [self.DiceSpec.fromstr(s)]

    def parse_message(self, ctx, arg0: str, args: str) -> typing.Coroutine:
        specs = []
        try:
            for arg in args.split():
                specs.extend(self._parse(arg))
        except ValueError as exc:
            ctx.reply(str(exc))
            return

        if not specs:
            ctx.reply("No dice!")
            return

        total_amount = sum(spec.amount for spec in specs)
        total_max = sum(spec.faces for spec in specs)
        if total_amount > 100 or total_max > 10000:
            ctx.reply("That’s too much.")
            return

        return self._execute(ctx, specs)

    async def _execute(self, ctx, ds: typing.Sequence[DiceSpec]):
        rolls = []
        for d in ds:
            rolls.extend(d.roll(self._rng))

        total = sum(rolls)

        ctx.reply("{} (sum: {})".format(
            " ".join(map(str, rolls)),
            total,
        ))
