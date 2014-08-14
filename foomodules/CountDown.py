import pickle
import sys

from datetime import datetime, timedelta

import babel.dates

import dateutil.parser

import pytz

import foomodules.Base as Base
import foomodules.urllookup as urllookup

def BabelDateFormatter(**kwargs):
    def formatter(delta):
        return babel.dates.format_datetime(delta, **kwargs)
    return formatter

def hour_date_formatter(delta):
    return "{:.3} h".format(delta.total_seconds()/3600)

class Event(object):
    def __init__(self, name, target_date):
        self.name = name
        self.target_date = dateutil.parser.parse(target_date)
        if self.target_date.tzinfo == None:
            self.target_date = self.target_date.replace(tzinfo=pytz.utc)

    def get_size(self):
        return  sys.getsizeof(self.name) + \
                sys.getsizeof(self.target_date) + \
                sys.getsizeof(self)

class EventStore(object):
    def __init__(self, data_filename,
            min_name_length=3,
            max_event_count=5,
            max_name_length=64):
        self.events = {}
        self.data_filename = data_filename
        self.min_name_length = int(min_name_length)
        self.max_event_count = int(max_event_count)
        self.max_name_length = int(max_name_length)

        self.try_load()

    def _check_name(self, name):
        if len(name) < self.min_name_length:
            raise ValueError("Names have to have a minimum length of"
                             " {0:d}".format(self.min_name_length))
        if self.max_name_length > 0 and len(name) > self.max_name_length:
            raise ValueError("Names have to have a maximum length of"
                             " {0:d}".format(self.max_name_length))

    def _check_limits(self):
        if self.max_event_count > 0 and len(self.events) > self.max_event_count:
            raise ValueError("Sorry, I cannot memorize more. You must allow me"
                             " to forget something else first.")

    def try_load(self):
        try:
            f = open(self.data_filename, "rb")
        except IOError:
            return
        with f:
            self.load(f)

    def load(self, filelike):
        self.events = pickle.load(filelike)

    def save(self):
        with open(self.data_filename, "wb") as f:
            pickle.dump(self.events, f)

    def add_event(self, name, target_date):
        self._check_limits()
        self._check_name(name)

        if name in self.events:
            raise KeyError(name)
        event = Event(name, target_date)
        self.events[name] = event

    def delete_event(self, event):
        del self.events[event.name]

    def rename_event(self, oldname, newname):
        event = self.events[oldname]
        del self.events[oldname]
        event.name = newname
        self.events[newname] = event

class CountDownCommand(Base.ArgparseCommand):
    CMD_ADD = "add"
    CMD_MOVE = "mv"
    CMD_DELETE = "rm"
    CMD_SAVE = "save"
    CMD_STATS = "stats"

    def __init__(self, store, command_name="cd",
                 disabled_commands=set(),
                 date_formatter=BabelDateFormatter(),
                 **kwargs):
        super().__init__(command_name, **kwargs)
        self.store = store
        self.date_formatter = date_formatter

        subparsers = self.argparse.add_subparsers(
            dest="action",
            help="Choose the action to execute"
        )

        self.disabled_commands = disabled_commands

        if self.CMD_ADD not in disabled_commands:
            # add command
            parser = subparsers.add_parser(
                "add",
                help="Store a new event in the system")
            parser.add_argument(
                "name",
                help="Descriptive name of the event to store")
            parser.add_argument(
                "target_date",
                help="Date of the event")
            parser.set_defaults(
                func=self._cmd_add)

        if self.CMD_MOVE not in disabled_commands:
            # move command
            parser = subparsers.add_parser(
                "move",
                help="Rename an event",
                aliases={"mv", "rename"})
            parser.add_argument("oldname")
            parser.add_argument("newname")
            parser.set_defaults(
                func=self._cmd_rename)

        if self.CMD_DELETE not in disabled_commands:
            # delete command
            parser = subparsers.add_parser(
                "rm",
                help="Remove an event",
                aliases={"delete", "remove"})
            parser.add_argument(
                "names",
                nargs="+",
                help="Name of the information to remove")
            parser.set_defaults(
                func=self._cmd_delete)

        if self.CMD_SAVE not in disabled_commands:
            parser = subparsers.add_parser(
                "save",
                help="Save all data stored in the eventstore.")
            parser.set_defaults(
                func=self._cmd_save)

        if self.CMD_STATS not in disabled_commands:
            parser = subparsers.add_parser(
                "stats",
                help="Print memory usage statistics.")
            parser.set_defaults(
                func=self._cmd_stats)

    def _call(self, msg, args, errorSink=None):
        if 'func' in args:
            args.func(msg, args, errorSink=errorSink)
        else:
            for event in self.store.events.values():
                now = datetime.utcnow()
                now = now.replace(tzinfo=pytz.utc)
                Δt = event.target_date - now
                if event.target_date > now:
                    preposition = "in"
                else:
                    Δt = -Δt
                    preposition = "since"

                self.reply(msg, "{} {} {} ".format(event.name,
                                                   preposition,
                                                   self.date_formatter(Δt)))
        return True

    def _cmd_add(self, msg, args, errorSink=None):
        try:
            self.store.add_event(args.name, args.target_date)
        except ValueError as err:
            self.reply(msg, "Sorry, {0}".format(err))
        except KeyError as err:
            self.reply(msg, "Sorry, that name is already assigned".format(err))

    def _cmd_delete(self, msg, args, errorSink=None):
        unknown = set()
        for name in args.names:
            event = self.store.events.get(name, None)
            if event is None:
                unknown.add(name)
                continue
            self.store.delete_event(event)

        if unknown:
            self.reply(
                msg,
                "Could not remove the following (unknown) information: "
                "{0}".format(", ".join(unknown)))

    def _cmd_rename(self, msg, args, errorSink=None):
        try:
            self.store.rename_event(args.oldname, args.newname)
        except KeyError:
            return

    def _cmd_save(self, msg, args, errorSink=None):
        self.store.save()
        self.reply(msg, "Successfully saved information")

    def _cmd_stats(self, msg, args, errorSink=None):
        event_memory = sum(map(Event.get_size, self.store.events.values()))

        self.reply(msg,
                   "eventstore statistics: {num_events} events consuming"
                   " {event_memory} memory.".format(
                       num_events=len(self.store.events),
                       event_memory=urllookup.format_bytes(event_memory)
                   ))
