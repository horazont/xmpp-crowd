# a foomodule for simple polls
# Rene Kuettner <rene@bitkanal.net>
# 
# licensed under GPL version 2

from datetime import datetime, timedelta

import foomodules.Base as Base

# FIXME: global variables are evil
active_polls = {}

class Poll(object):
    def __init__(self, owner = (None, None), dt_start = datetime.now(), duration = 1,
                       topic = None, options = [], service_name = None):
        self.owner = owner
        self.dt_start = dt_start
        self.duration = duration
        self.topic = topic
        self.options = options
        self.service_name = service_name
        self.votes = {}

class Vote(Base.ArgparseCommand):

    # string templates
    ST_INDEX_HELP       = 'The index of the option you are voting for.'
    ST_NO_OPT_WITH_IDX  = 'There is no option with index {index} for this poll.'
    ST_VOTE_COUNTED     = '{user}: Thanks, vote counted!'
    ST_NO_ACTIVE_POLL   = 'No active poll in this room.'

    def __init__(self, timeout = 3, command_name = 'vote', maxlen = 64, **kwargs):
        super().__init__(command_name, **kwargs)
        self.timeout = timeout
        self.maxlen = maxlen
        self.argparse.add_argument(
            'index',
            type = int,
            help = self.ST_INDEX_HELP)

    def _call(self, msg, args, errorSink = None):
        mucname = msg.get_mucroom()
        user = msg.get_from()
        nick = msg.get_mucnick()
        selected_option = None
        # get vote for this room if available
        try:
            poll = active_polls[mucname]
            args.index = int(args.index)
            if args.index < 1 or args.index > len(poll.options):
                self.reply(msg, self.ST_NO_OPT_WITH_IDX.format(index = args.index))
                return
            poll.votes[user] = (nick, args.index - 1)
            reply = self.ST_VOTE_COUNTED
            selected_option = poll.options[args.index - 1]
        except KeyError:
            reply = self.ST_NO_ACTIVE_POLL
        self.reply(msg, reply.format(user = nick, opt = selected_option))
 
class PollCtl(Base.ArgparseCommand):

    ST_ARG_HELP_ACTION      = 'Poll management actions'
    ST_ARG_HELP_DURATION    = 'Duration of the poll in minutes (defaults to: 1)'
    ST_ARG_HELP_TOPIC       = 'The topic of the poll (e.g. a question)'
    ST_ARG_HELP_OPTIONS     = 'The options voters may choose from.'
    ST_ARG_HELP_START       = 'Start a new vote'
    ST_ARG_HELP_CANCEL      = 'Cancel an active poll'
    ST_ARG_HELP_STATUS      = 'Request poll status'
    ST_SHORT_USAGE          = 'Usage: !pollctl [-h] {start,cancel,status} ...'
    ST_POLL_ACTIVE          = 'There is already an active poll in this room!'
    ST_NO_ACTIVE_POLL       = 'There is no active poll in this room at the moment!'
    ST_INVALID_DURATION     = 'Poll duration must be in range [1, 60] ∌ {duration}!'
    ST_TOO_FEW_OPTIONS      = 'You have to specify at least 2 *different* options!'
    ST_TOO_MANY_OPTIONS     = 'You must not add more than 9 vote options!'
    ST_POLL_ANNOUNCEMENT    = ('{owner} has started a poll: "{topic}"\n'
                              '{options}'
                              'Use !vote <n> to place your vote within the next {t} minutes.')
    ST_POLL_OPTION          = '    [{index}] {option}\n'
    ST_CANCELED_BY_USER     = 'Poll has been canceled by {owner}.'
    ST_CANCELED_NO_VOTES    = 'Poll canceled. No votes have been placed!'
    ST_CANCEL_DENIED        = 'Only {owner} may cancel this poll!'
    ST_POLL_STATUS          = ('Active poll from {owner}: "{topic}"\n'
                              '{options}'
                              'Place your vote with "!vote <index>". {tm} mins and {ts} secs left.')
    ST_POLL_TIME_LEFT       = 'Current poll ends in {s} seconds!'
    ST_POLL_RESULTS         = ('{owner}\'s poll "{topic}" finished. '
                              'Results based on {count} votes:'
                              '{results}')
    ST_POLL_RESULT_BAR      = '\n    [{bar:░<10}] {perc:>3}% ({count:>2}) {option}'
    ST_POLL_RESULT_BAR_CHAR = '█'

    def __init__(self, timeout = 3, command_name = 'pollctl', maxlen = 256, **kwargs):
        super().__init__(command_name, **kwargs)
        self.timeout = timeout
        self.maxlen = maxlen
        subparsers = self.argparse.add_subparsers(
            dest='action',
            help=self.ST_ARG_HELP_ACTION
        )
        # arg parser for the start command
        parser_start = subparsers.add_parser('start', help = self.ST_ARG_HELP_START)
        parser_start.add_argument(
            '-d', '--duration',
            dest    = 'duration',
            default = 1,
            type    = int,
            help    = self.ST_ARG_HELP_DURATION
        )
        parser_start.add_argument('topic', help = self.ST_ARG_HELP_TOPIC)
        parser_start.add_argument('options', nargs = '+', help = self.ST_ARG_HELP_OPTIONS)
        # arg parser for the cancel command
        parser_cancel = subparsers.add_parser('cancel',
            help    = self.ST_ARG_HELP_CANCEL,
            aliases = [ 'stop', 'abort' ])
        # arg parser for the status command
        parser_status = subparsers.add_parser('status',
            help    = self.ST_ARG_HELP_OPTIONS,
            aliases = [ 'info' ])

    def _call(self, msg, args, errorSink=None):
        # select func name from dict to prevent arbitrary func names
        # to be called (this is just for sanity, since argparse ought
        # to only accept valid actions)
        try:
            func_name = {
                'start':    '_poll_start',
                'cancel':   '_poll_cancel',
                'stop':     '_poll_cancel',
                'abort':    '_poll_cancel',
                'status':   '_poll_status',
                'info':     '_poll_status',
            }[args.action]
            getattr(self, func_name)(msg, args, errorSink)
        except KeyError:
            self.reply(msg, self.ST_SHORT_USAGE)

    def _poll_start(self, msg, args, errorSink):
        mucname = msg.get_mucroom()
        if mucname in active_polls.keys():
            self.reply(msg, self.ST_POLL_ACTIVE)
            return
        args.duration = int(args.duration)
        args.options = list(set(args.options)) # remove dups
        # maybe we want to allow for longer vote durations
        # however, votes may block other votes in the channel
        if args.duration < 1 or args.duration > 60:
            self.reply(msg, self.ST_INVALID_DURATION.format(t=args.duration))
            return
        if len(args.options) < 2:
            self.reply(msg, self.ST_TOO_FEW_OPTIONS)
            return
        if len(args.options) > 9:
            self.reply(msg, self.ST_TOO_MANY_OPTIONS)
            return

        # create poll
        owner_info = (msg['mucnick'], msg['from'])
        active_polls[mucname] = Poll(
            owner           = owner_info,
            dt_start        = datetime.now(),
            duration        = args.duration,
            topic           = args.topic,
            options         = args.options,
            service_name    = '{muc}_poll_service'.format(muc=mucname))

        # schedule a service for this poll
        self.xmpp.scheduler.add(
            active_polls[mucname].service_name,
            10,
            self._on_poll_service,
            kwargs = { 'room': mucname, 'msg': msg },
            repeat = True)

        # tell everyone about the new poll
        options_str = ''
        for i in range(0, len(args.options)):
            options_str += self.ST_POLL_OPTION.format(
                index  = i + 1,
                option = args.options[i])
        self.reply(msg, self.ST_POLL_ANNOUNCEMENT.format(
            owner   = owner_info[0],
            topic   = args.topic,
            t       = args.duration,
            options = options_str))

    def _poll_cancel(self, msg, args, errorSink):
        user = msg.get_from()
        mucname = msg.get_mucroom()
        try:
            poll = active_polls[mucname]
            if poll.owner[1] == user:
                del active_polls[mucname]
                self.xmpp.scheduler.remove(poll.service_name)
                self.reply(msg, self.ST_CANCELED_BY_USER.format(owner=poll.owner[0]))
            else:
                self.reply(msg, self.ST_CANCEL_DENIED.format(owner=poll.owner[0]))
        except KeyError:
            self.reply(msg, self.ST_NO_ACTIVE_POLL)

    def _poll_status(self, msg, args, errorSink):
        mucname = msg.get_mucroom()
        try:
            poll = active_polls[mucname]
            delta_t = poll.dt_start + timedelta(minutes=poll.duration) - datetime.now()
            minutes_left = int(delta_t.total_seconds() / 60)
            seconds_left = int(delta_t.total_seconds() % 60)
            options_str = ''
            for i in range(0, len(poll.options)):
                options_str += self.ST_POLL_OPTION.format(
                    index   = i + 1,
                    option  = poll.options[i])
            self.reply(msg, self.ST_POLL_STATUS.format(
                owner   = poll.owner[0],
                topic   = poll.topic,
                tm      = minutes_left,
                ts      = seconds_left,
                count   = len(poll.votes.keys()),
                options = options_str))
        except KeyError:
            self.reply(msg, self.ST_NO_ACTIVE_POLL)
 
    def _on_poll_service(self, room=None, msg=None):
        poll = active_polls[room]
        delta_t = poll.dt_start + timedelta(minutes=poll.duration)
        seconds_left = (delta_t - datetime.now()).total_seconds()
        if seconds_left < 1:
            self._on_poll_finished(room, msg)
        if int(seconds_left) in range(24, 37):
            self.reply(msg, self.ST_POLL_TIME_LEFT.format(s=int(seconds_left)))

    def _on_poll_finished(self, room=None, msg=None):
        poll = active_polls[room]

        # remove poll and service
        del active_polls[room]
        self.xmpp.scheduler.remove(poll.service_name)

        vc = len(poll.votes)
        if vc < 1:
            self.reply(msg, self.ST_CANCELED_NO_VOTES)
            return
        results = []
        for i in range(0, len(poll.options)):
            results.append(0)
        for val in poll.votes.values():
            results[val[1]] += 1
        results_str = ''
        for i in range(0, len(poll.options)):
            pperc = results[i] / vc
            bar_width = int(pperc * 10)
            results_str += self.ST_POLL_RESULT_BAR.format(
                option  = poll.options[i],
                bar     = self.ST_POLL_RESULT_BAR_CHAR * bar_width,
                perc    = int(pperc * 100),
                count   = results[i])
        self.reply(msg, self.ST_POLL_RESULTS.format(
            owner   = poll.owner[0],
            topic   = poll.topic,
            count   = vc,
            results = results_str))
