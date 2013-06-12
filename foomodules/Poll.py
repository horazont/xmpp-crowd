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
        self._votes = {}
        self._results = []

    def _recalc_results(self):
        self._results = [ [0, 0] for i in range(len(self.options)) ]
        vote_count = len(self.votes.keys())
        # are there any votes?
        if vote_count == 0:
            return
        # count votes for each option
        for user in self.votes.keys():
            index = self.votes[user][1]
            self._results[index][0] += 1
        # calculate percentage
        for i in range(0, len(self._results)):
            self._results[i][1] = self._results[i][0] / vote_count

    def set_vote(self, user, nick, index):
        self._votes[user] = (nick, index)
        self._recalc_results()

    def unset_vote(self, user):
        del self._votes[user]
        self._recalc_results()

    @property
    def votes(self):
        return self._votes

    @property
    def voters(self):
        return self._votes.keys()

    @property
    def results(self):
        return self._results

class Vote(Base.ArgparseCommand):

    # string templates
    ST_INDEX_HELP       = 'The index of the option you are voting for.'
    ST_NO_OPT_WITH_IDX  = 'There is no option with index {index} for this poll.'
    ST_VOTE_COUNTED     = 'Vote counted: {items}'
    ST_VOTE_WITHDRAWN   = 'Vote withdrawn: {items}'
    ST_NOT_VOTED        = 'You have not voted yet.'
    ST_VOTE_ITEM        = '[ {bar} {option} ({perc}%) ]'
    ST_VOTE_ITEM_SEP    = ', '
    ST_PERC_BARS        = '▁▂▃▄▅▆▇█'
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
        # get vote for this room if available
        try:
            poll = active_polls[mucname]
            args.index = int(args.index)

            if args.index == 0:
                # withdraw
                if user in poll.voters:
                    poll.unset_vote(user)
                    reply = self.ST_VOTE_WITHDRAWN
                else:
                    self.reply(msg, self.ST_NOT_VOTED)
                    return
            else:
                # vote
                if args.index < 1 or args.index > len(poll.options):
                    self.reply(msg, self.ST_NO_OPT_WITH_IDX.format(
                        index = args.index))
                    return
                poll.set_vote(user, nick, args.index - 1)
                reply = self.ST_VOTE_COUNTED

            vote_count = len(poll.votes.keys())
            items_list = []
            for i in range(0, len(poll.results)):
                bar_index = int((len(self.ST_PERC_BARS) - 1) * poll.results[i][1])
                items_list.append(self.ST_VOTE_ITEM.format(
                    bar     = list(self.ST_PERC_BARS)[bar_index],
                    perc    = int(poll.results[i][1] * 100),
                    index   = i + 1,
                    option  = poll.options[i]))
            self.reply(msg, reply.format(
                count   = vote_count,
                items   = self.ST_VOTE_ITEM_SEP.join(items_list)))
        except KeyError:
            self.reply(msg, self.ST_NO_ACTIVE_POLL)

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
    ST_POLL_ANNOUNCEMENT    = ('{owner} has started a poll ({t} min): "{topic}"\n'
                              '    {options}')
    ST_POLL_OPTION          = ' [{index}]: {option} '
    ST_CANCELED_BY_USER     = 'Poll has been canceled by {owner}.'
    ST_CANCELED_NO_VOTES    = 'Poll canceled. No votes have been placed!'
    ST_CANCEL_DENIED        = 'Only {owner} may cancel this poll!'
    ST_POLL_STATUS          = ('Active poll from {owner}: "{topic}"\n'
                              '    {options}\n'
                              'Place your vote with "!vote <index>". {tm} mins and {ts} secs left.')
    ST_POLL_TIME_LEFT       = 'Poll ends soon. Don\'t forget to vote!'
    ST_POLL_RESULTS         = ('{owner}\'s poll "{topic}" finished with {count} votes: '
                              '{results}')
    ST_POLL_RESULT_BAR      = '\n    {perc: >3}% ┤{bar:░<10}├ ({count: >2})  {option}'
    ST_POLL_RESULT_HBAR     = '█'

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
        self.subparsers.append(parser_start)
        parser_start.add_argument(
            '-d', '--duration',
            dest    = 'duration',
            default = 1,
            type    = int,
            help    = self.ST_ARG_HELP_DURATION)
        parser_start.add_argument('topic', help = self.ST_ARG_HELP_TOPIC)
        parser_start.add_argument('options', nargs = '+', help = self.ST_ARG_HELP_OPTIONS)
        # arg parser for the cancel command
        parser_cancel = subparsers.add_parser('cancel',
            help    = self.ST_ARG_HELP_CANCEL,
            aliases = [ 'stop', 'abort' ])
        self.subparsers.append(parser_cancel)
        # arg parser for the status command
        parser_status = subparsers.add_parser('status',
            help    = self.ST_ARG_HELP_STATUS,
            aliases = [ 'info' ])
        self.subparsers.append(parser_status)

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
            self.reply(msg, self.ST_INVALID_DURATION.format(duration=args.duration))
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

        vc = len(poll.votes.keys())
        if vc < 1:
            self.reply(msg, self.ST_CANCELED_NO_VOTES)
            return
        results_str = ''
        for i in range(0, len(poll.results)):
            bar_width = int(poll.results[i][1] * 10)
            results_str += self.ST_POLL_RESULT_BAR.format(
                option  = poll.options[i],
                bar     = self.ST_POLL_RESULT_HBAR * bar_width,
                perc    = int(poll.results[i][1] * 100),
                count   = poll.results[i][0])
        self.reply(msg, self.ST_POLL_RESULTS.format(
            owner   = poll.owner[0],
            topic   = poll.topic,
            count   = vc,
            results = results_str))
