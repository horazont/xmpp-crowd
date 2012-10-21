import foomodules.Base as Base
import foomodules.URLLookup as URLLookup

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


class NumericDocumentMatcher(Base.MessageHandler):
    def __init__(self, document_regexes, url_lookup, **kwargs):
        super().__init__(**kwargs)
        self.document_regexes = document_regexes
        self.url_lookup = url_lookup

    def __call__(self, msg, errorSink=None):
        contents = msg["body"]

        for regex, document_format in self.document_regexes:
            for match in regex.finditer(contents):
                groups = match.groups()
                groupdict = match.groupdict()
                document_url = document_format.format(*groups, **groupdict)

                try:
                    iterable = iter(self.url_lookup.processURL(document_url))
                    first_line = next(iterable)
                    self.reply(msg, "<{0}>: {1}".format(document_url, first_line))
                    for line in iterable:
                        self.reply(msg, line)
                except URLLookup.URLLookupError as err:
                    self.reply(msg, "<{0}>: sorry, couldn't look it up: {1}".format(document_url, str(err)))
                    pass

