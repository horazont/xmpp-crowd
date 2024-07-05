import asyncio
import functools
import logging

import aioxmpp.muc
import aioxmpp.stanza
import aioxmpp.structs

import aiofoomodules.context
import aiofoomodules.handlers
import aiofoomodules.utils


class MUCContext(aiofoomodules.context.AbstractMessageContext):
    def __init__(self, client, muc, related_occupant, related_stanza):
        super().__init__()
        self.client = client
        self.muc = muc
        self.related_stanza = related_stanza
        self.related_occupant = related_occupant

    def reply(self, body, use_nick=True):
        msg = aioxmpp.stanza.Message(
            type_="groupchat",
        )
        if use_nick:
            if self.related_occupant is not None:
                nick = self.related_occupant.nick
            else:
                nick = self.related_stanza.from_.resource
            aiofoomodules.context.set_body(msg, body, nick=nick)
        else:
            aiofoomodules.context.set_body(msg, body)

        self.muc.send_message(msg)

    def reply_direct(self, body):
        msg = aioxmpp.stanza.Message(
            to=self.related_occupant.conversation_jid,
            type_="chat",
        )
        aiofoomodules.context.set_body(msg, body)

        self.client.stream.enqueue_stanza(msg)


class MUC:
    def __init__(self, mucjid, nick, *,
                 bind=[],
                 filters=[],
                 max_queue_size=5):
        super().__init__()
        self._mucjid = mucjid
        self._nick = nick
        self._bind = list(bind)
        self._queue = asyncio.Queue(
            maxsize=max_queue_size
        )
        self._filters = list(filters)
        self.logger = logging.getLogger(__name__ + ".muc@" + str(self._mucjid))

    async def setup(self, main):
        self._client = main.client
        self._muc_service = self._client.summon(aioxmpp.muc.Service)
        self._room, future = self._muc_service.join(
            self._mucjid,
            self._nick,
            # do not request history
            history=aioxmpp.muc.xso.History(maxstanzas=0),
            autorejoin=True
        )
        future.add_done_callback(
            lambda _: self.logger.info("joined %s as %r",
                                       self._mucjid,
                                       self._nick)
        )

        self._room.on_message.connect(self._on_message)

        for bind in self._bind:
            await bind.setup(self._client)

        self._worker = asyncio.ensure_future(self._run())
        self._worker.add_done_callback(
            functools.partial(
                aiofoomodules.utils.log_future_failure,
                self.logger,
                name="worker task"
            )
        )

    async def _run(self):
        while True:
            ctx, message, tasks = await self._queue.get()
            for task in tasks:
                try:
                    await asyncio.wait_for(task, timeout=10)
                except Exception:
                    self.logger.exception(
                        "some handler failed to process message %r",
                        message,
                        exc_info=True,
                    )

    def _filter_message(self, message, member, source):
        for filter_func in self._filters:
            result = filter_func(self._room, message, member,  source)
            if result is True or result is False:
                return result
        return True

    def _on_message(self, message, member, source, **kwargs):
        if member is not None:
            if member == self._room.me:
                self.logger.debug("dropped message: is from self "
                                  "(via member object)")
                return
        elif message.from_ == self._room.me.conversation_jid:
            self.logger.debug("dropped message: is from self "
                              "(via jid)")
            return
        if not self._filter_message(message, member, source):
            self.logger.debug("dropped message: via filter chain (%s)",
                              message)
            return

        ctx = MUCContext(self._client, self._room,
                         member,
                         message)
        tasks = []

        try:
            for bind in self._bind:
                tasks.extend(bind.analyse_message(ctx, message))
        except aiofoomodules.handlers.MessageHandled:
            pass

        if len(tasks) == 0:
            return

        try:
            self._queue.put_nowait((ctx, message, tasks))
        except asyncio.QueueFull:
            self.logger.warning("queue overflow")
        else:
            self.logger.debug(
                "submitted %d tasks to worker; current queue size = %d",
                len(tasks), self._queue.qsize())

    def emit_message(self, body, nicks=None):
        msg = aioxmpp.Message(
            type_=aioxmpp.MessageType.GROUPCHAT,
        )
        aiofoomodules.context.set_body(msg, body, nick=nicks)
        self._room.send_message(msg)

    async def teardown(self):
        self._worker.cancel()
        await self._room.leave()
        self._client = None
