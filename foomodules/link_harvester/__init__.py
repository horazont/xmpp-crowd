import logging

from datetime import datetime, timedelta

import foomodules.Base as Base
import foomodules.utils as utils

import sqlalchemy.exc
import sqlalchemy.orm.exc

import muclinks

logger = logging.getLogger(__name__)

class LinkHarvester(Base.XMPPObject):
    def __init__(self, controller, handlers, **kwargs):
        super().__init__(**kwargs)
        self.controller = controller
        self.handlers = handlers

    def submit(self, msg_context, metadata):
        posted = datetime.utcnow()
        mucjid = msg_context["from"].bare
        nick = msg_context["from"].resource

        senderjid = self.XMPP.muc.getJidProperty(
            mucjid, nick, 'jid')

        for handler in self.handlers:
            kwargs = handler(metadata)

            if kwargs is not None:
                break

        with self.controller.with_new_session() as ctx:
            ctx.post_link(
                mucjid,
                str(senderjid.bare),
                nick,
                timestamp=posted,
                **kwargs)

    def __call__(self, msg_context, metadata):
        try:
            self.submit(msg_context, metadata)
        except Exception as err:
            logging.warn("during first attempt: (%s) %s",
                         type(err).__name__,
                         err)
        else:
            return

        try:
            self.submit(msg_context, metadata)
        except Exception as err:
            logging.exception(err)
