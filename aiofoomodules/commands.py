import aioxmpp
import aioxmpp.forms

from .handlers import ArgparseCommandHandler

from . import argparse_types


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
