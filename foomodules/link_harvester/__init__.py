import logging

from datetime import datetime, timedelta

import foomodules.Base as Base
import foomodules.utils as utils

import sqlalchemy.exc
import sqlalchemy.orm.exc

import muclinks
import muclinks.model

logger = logging.getLogger(__name__)

class LinkHarvester(Base.XMPPObject):
    def __init__(self, controller, handlers, *,
                 repost_harvested_link_domains=[],
                 repost_url_template=None,
                 **kwargs):
        super().__init__(**kwargs)
        self.controller = controller
        self.handlers = handlers
        self.repost_harvested_link_domains = \
            list(repost_harvested_link_domains)
        self.repost_url_template = repost_url_template

    def _post_link_if_repost_domain(self, msg_context, document, metadata):
        if document.media is None or document.media.blob is None:
            return

        if metadata.url_parsed.netloc not in self.repost_harvested_link_domains:
            return

        if self.repost_url_template is None:
            logger.warn("cannot repost link without repost_url_template!")
            return

        url_hash = document.media.blob.url_hash

        url = self.repost_url_template(
            media_hash=base64.urlsafe_b64encode(
                url_hash
            ).rstrip(b"=").decode("ascii")
        )

        self.reply(msg_context, url)

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
            document = ctx.post_link(
                mucjid,
                str(senderjid.bare),
                nick,
                timestamp=posted,
                **kwargs)

            try:
                self._post_link_if_repost_domain(msg_context, document, metadata)
            except Exception as err:
                logger.warn("failed to repost link: %r", err)

    def __call__(self, msg_context, metadata):
        try:
            self.submit(msg_context, metadata)
        except Exception as err:
            logger.warn("during first attempt: (%s) %s",
                         type(err).__name__,
                         err)
        else:
            return

        try:
            self.submit(msg_context, metadata)
        except Exception as err:
            logger.exception(err)


class AuthTokenSupplier(Base.ArgparseCommand):
    def __init__(self,
                 controller,
                 url_format,
                 command_name="!auth",
                 **kwargs):
        super().__init__(command_name, **kwargs)
        self.controller = controller
        self.url_format = url_format

    def __call__(self, msg, arguments, errorSink=None):
        is_muc = msg["type"] == "groupchat"
        is_muc = is_muc or str(msg["from"].bare) in [
            roomjid
            for roomjid, _ in self.XMPP.config.rooms]

        if is_muc:
            senderjid = self.XMPP.muc.getJidProperty(
                msg["from"].bare,
                msg["from"].resource,
                'jid')
        else:
            senderjid = msg["from"]

        senderjid = str(senderjid.bare)

        if not senderjid:
            self.reply(msg, "could not determine your JID")
            return

        sendernick = msg["from"].resource

        with self.controller.with_new_session() as ctx:
            account = ctx.get_account_for_jid(
                senderjid,
                nick=sendernick)
            if account is None:
                self.reply(msg,
                           "no account for this jid: {}".format(
                               senderjid))
                return

            if is_muc:
                muc_id = muclinks.ensure_muc(ctx.session, str(msg["from"].bare)).id
            else:
                muc_id = 0
            key = ctx.create_ota_key(account)

        self.reply(
            msg,
            self.url_format.format(
                key=muclinks.model.key_to_str(key),
                muc_id=muc_id),
            overrideMType="chat")
