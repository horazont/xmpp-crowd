import foomodules.Base as Base

class Host(Base.MessageHandler):
    def __call__(self, msg, arguments, errorSink=None):
        print(arguments)
