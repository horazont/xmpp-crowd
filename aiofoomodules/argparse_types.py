import aioxmpp


def jid(s):
    return aioxmpp.JID.fromstr(s)
