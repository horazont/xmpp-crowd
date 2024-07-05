import asyncio

import aiofoomodules.handlers
from aiofoomodules.utils import get_simple_body


class Pong(aiofoomodules.handlers.AbstractHandler):
    RESPONSE_MAP = {
        "ping": "pong",
        "gnip": "gnop",
    }

    def analyse_message(self, ctx, message):
        body = get_simple_body(message).strip().lower()
        try:
            response = self.RESPONSE_MAP[body]
        except KeyError:
            pass
        else:
            yield self._reply(ctx, response)
            raise aiofoomodules.handlers.MessageHandled()

    async def _reply(self, ctx, response):
        ctx.reply(response)
