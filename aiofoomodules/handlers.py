import abc


class MessageHandled(Exception):
    pass


class AbstractHandler(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def analyse_message(self, ctx, message):
        return None
        yield
