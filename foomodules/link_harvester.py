import logging

from datetime import datetime, timedelta

import foomodules.Base as Base
import foomodules.utils as utils

import sqlalchemy.exc
import sqlalchemy.orm.exc

import muclinks

logger = logging.getLogger(__name__)

class LinkHarvester(Base.XMPPObject):
    def __init__(self, Session, **kwargs):
        super().__init__(**kwargs)
        self.Session = Session

    def _get_muc_in_session(self, session, mucjid):
        try:
            return session.query(muclinks.MUC).filter(
                muclinks.MUC.jid == str(mucjid)).one()
        except sqlalchemy.orm.exc.NoResultFound:
            try:
                muc = muclinks.MUC(mucjid)
                session.add(muc)
                session.commit()
                return muc
            except sqlalchemy.exc.IntegrityError:
                return session.query(muclinks.MUC).filter(
                    muclinks.MUC.jid == str(mucjid)).one()

    def submit_into_session(self, session, msg_context, metadata):
        posted = datetime.utcnow()
        mucjid = msg_context["from"].bare
        nick = msg_context["from"].resource

        sender_jid = self.XMPP.muc.getJidProperty(
            mucjid, nick, 'jid')

        muc = self._get_muc_in_session(session, mucjid)

        link = muclinks.Link(
            muc,
            posted,
            sender_jid.bare,
            nick,
            metadata.url,
            metadata.title,
            metadata.description,
            metadata.human_readable_type,
            metadata.mime_type)
        session.add(link)
        session.commit()

    def submit(self, msg_context, metadata):
        session = self.Session()
        try:
            self.submit_into_session(session, msg_context, metadata)
        finally:
            session.close()

    def __call__(self, msg_context, metadata):
        try:
            self.submit(msg_context, metadata)
        except Exception as err:
            logging.warn("during first attempt: %s", err)
        else:
            return

        try:
            self.submit(msg_context, metadata)
        except Exception as err:
            logging.error("during second attempt (giving up): %s", err)
