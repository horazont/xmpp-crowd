import abc
import collections.abc


class AbstractMessageContext(metaclass=abc.ABCMeta):
    """
    The abstract message context provides a set of methods which are used by
    handlers to efficiently reply to requesters.
    """

    def _set_body(self, msg, body, *, nick=None):
        """
        Set the body of the :class:`aioxmpp.stanza.Message` `msg` to the given
        `body`.

        `body` may be a mapping, in which case the
        :attr:`~aioxmpp.stanza.Message.body` attribute of `msg` will be set to
        `body`. Otherwise, the attribute is left as it is, but its :data:`None`
        item is set to `body`.

        If `nick` is not :data:`None`, it is pre-pended to each value from
        the :attr:`~aioxmpp.stanza.Message.body` attriubte, separated with a
        colon from the actual body.
        """
        if isinstance(body, collections.abc.Mapping):
            msg.body = body
        else:
            msg.body[None] = body

        if nick is not None:
            for key in msg.body.keys():
                msg.body[key] = "{}: {}".format(
                    nick,
                    msg.body[key]
                )

    @abc.abstractmethod
    def reply(self, body, use_nick=True):
        """
        Reply with the given `body` (which can either be a string or a
        :class:`aioxmpp.structs.LanguageMap`).

        It is assumed that the reply is not private; if the context is a
        multi-user one, the reply will be broadcast to all users and optionally
        (if `use_nick` is true) prefixed with a handle referencing the user
        referred to by the context.
    """

    @abc.abstractmethod
    def reply_direct(self, body):
        """
        Reply with the given `body` (semantics being the same as for
        :meth:`reply`).

        The reply will always be directly sent to the user referred to by the
        context, bypassing any broadcasting medium if possible.
        """
