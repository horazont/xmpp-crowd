import foomodules.Base as Base

class Pong(Base.MessageHandler):
    def __call__(self, msg, errorSink=None):
        if msg["body"].strip().lower() == "ping":
            self.reply(msg, "pong")
            return True


class IgnoreList(Base.MessageHandler):
    def __init__(self, message="I will ignore you.", **kwargs):
        super().__init__(**kwargs)
        self.message = message
        self.ignoredJids = set()

    def __call__(self, msg, errorSink=None):
        bare = str(msg["from"].bare)
        if bare in self.ignoredJids:
            return
        self.ignoredJids.add(bare)
        self.reply(msg, self.message)

