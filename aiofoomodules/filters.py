def muc_ignore_nicknames(nicknames):
    def filter(conversation, message, member, source):
        if member is None:
            return
        if member.nick in nicknames:
            return False
    return filter
