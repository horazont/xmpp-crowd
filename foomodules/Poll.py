# a foomodule for polls
# Rene Kuettner <rene@bitkanal.net>
# 
# licensed under GPL version 2

from datetime import datetime, timedelta

import foomodules.Base as Base

# FIXME: global variables are evil
active_polls = {}

class Poll(object):
    def __init__(self, owner=(None, None), dt_start=datetime.now(), duration=1,
                       topic=None, options=[], service_name=None):
        self.owner = owner
        self.dt_start = dt_start
        self.duration = duration
        self.topic = topic
        self.options = options
        self.service_name = service_name
        self.votes = {}

class Vote(Base.ArgparseCommand):
    def __init__(self, timeout=3, command_name='vote', maxlen=64, **kwargs):
        super().__init__(command_name, **kwargs)
        self.timeout = timeout
        self.maxlen = maxlen
        self.argparse.add_argument(
            'index',
            type=int,
            help='The index of the option you are voting for.',
        )

    def _call(self, msg, args, errorSink=None):
        mucname = msg['mucroom']
        user = msg['from']
        nick = msg['mucnick']
        selected_option = None
        # get vote for this room if available
        try:
            poll = active_polls[mucname]
            args.index = int(args.index)
            if args.index < 1 or args.index > len(poll.options):
                self.reply(
                    msg, 'There is no option with index {i} for this poll.'.format(
                    i=args.index
                ))
                return
            poll.votes[user] = (nick, args.index - 1)
            reply = '{user}: Thanks, your vote for "{opt}" has been counted!'
            selected_option = poll.options[args.index - 1]
        except KeyError:
            reply = 'No active poll in this room.'
        self.reply(msg, reply.format(user=nick, opt=selected_option))
 
class PollCtl(Base.ArgparseCommand):
    def __init__(self, timeout=3, command_name='pollctl', maxlen=256, **kwargs):
        super().__init__(command_name, **kwargs)
        self.timeout = timeout
        self.maxlen = maxlen
        subparsers = self.argparse.add_subparsers(
            dest='action',
            help='Poll supports the following actions:'
        )
        # arg parser for the start command
        parser_start = subparsers.add_parser('start', help='Start a new vote')
        parser_start.add_argument(
            '-d', '--duration',
            dest='duration',
            default=1,
            type=int,
            help='Duration of the poll in minutes (defaults to: 1)'
        )
        parser_start.add_argument(
            'topic',
            help='The topic of the poll (e.g. a question)'
        )
        parser_start.add_argument(
            'options',
            nargs='+',
            help='The options voters may choose from.',
        )
        # arg parser for the cancel command
        parser_cancel = subparsers.add_parser('cancel', help='Cancel an active poll')
        # arg parser for the status command
        parser_status = subparsers.add_parser('status', help='Request poll status')

    def _call(self, msg, args, errorSink=None):
        # select func name from dict to prevent arbitrary func names
        # to be called (this is just for sanity, since argparse ought
        # to only accept valid actions)
        func_name = {
            'start':    '_poll_start',
            'cancel':   '_poll_cancel',
            'status':   '_poll_status',
        }[args.action]
        getattr(self, func_name)(msg, args, errorSink)

    def _poll_start(self, msg, args, errorSink):
        mucname = msg['mucroom']
        if mucname in active_polls.keys():
            self.reply(msg, 'There is already an poll in this room!')
            return
        args.duration = int(args.duration)
        args.options = list(set(args.options)) # remove dups
        # maybe we want to allow for longer vote durations
        # however, votes may block other votes in the channel
        if args.duration < 1 or args.duration > 60:
            self.reply(msg, 'Poll duration must be in range [1, 60] ∌ {t}!'
                            .format(t=args.duration))
            return
        if len(args.options) < 2:
            self.reply(msg, 'You have to specify at least 2 *different* options!')
            return
        if len(args.options) > 9:
            self.reply(msg, 'You must not set more than 9 vote options!')
            return

        # create poll
        owner_info = (msg['mucnick'], msg['from'])
        active_polls[mucname] = Poll(
            owner=owner_info,
            dt_start=datetime.now(),
            duration=args.duration,
            topic=args.topic,
            options=args.options,
            service_name='{muc}_poll_service'.format(muc=mucname),
        )

        # schedule a service for this poll
        self.xmpp.scheduler.add(
            active_polls[mucname].service_name,
            10,
            self._on_poll_service,
            kwargs={ 'room': mucname, 'msg': msg },
            repeat=True,
        )

        # tell everyone about the new poll
        reply  = '*** User {owner} has started a public poll! ***\n'
        reply += 'Topic: "{topic}"\n'
        reply += 'You have {t} minute(s) to vote for one of the following options:\n'
        for i in range(0, len(args.options)):
            reply += '   {idx} ⇰ {txt}\n'.format(idx=i+1, txt=args.options[i])
        reply += 'Use !vote <n> to place your vote.\n'
        reply += 'Poll owner {owner} may cancel the poll using "!pollctl cancel".'
        self.reply(msg, reply.format(
            owner=owner_info[0],
            topic=args.topic,
            t=args.duration,
        ))

    def _poll_cancel(self, msg, args, errorSink):
        user = msg['from']
        mucname = msg['mucroom']
        try:
            poll = active_polls[mucname]
            if poll.owner[1] == user:
                del active_polls[mucname]
                self.xmpp.scheduler.remove(poll.service_name)
                self.reply(msg, 'Poll has been canceled by {owner}.'.format(
                    owner=poll.owner[0]
                ))
            else:
                self.reply(msg, 'Only {owner} may cancel this poll!'.format(
                    owner=poll.owner[0]
                ))
        except KeyError:
            self.reply(msg, 'No active poll found!')

    def _poll_status(self, msg, args, errorSink):
        mucname = msg['mucroom']
        try:
            poll = active_polls[mucname]
            delta_t = poll.dt_start + timedelta(minutes=poll.duration) - datetime.now()
            minutes_left = int(delta_t.total_seconds() / 60)
            seconds_left = int(delta_t.total_seconds() % 60)
            reply  = 'There is an active poll from {owner} in this room!\n'
            reply += 'Topic: {topic}\n'
            reply += 'You have {tm} minutes and {ts} seconds left to vote for one of:\n'
            for i in range(0, len(poll.options)):
                reply += '   {index} ⇰ {option}\n'.format(
                                index=i+1, option=poll.options[i])
            reply += '{count} votes have been placed so far. '
            reply += 'Place your vote with !vote <index>'
            self.reply(msg, reply.format(
                owner=poll.owner[0],
                topic=poll.topic,
                tm=minutes_left,
                ts=seconds_left,
                count=len(poll.votes.keys()),
            ))
        except KeyError:
            self.reply(msg, 'No active poll found!')
 
    def _on_poll_service(self, room=None, msg=None):
        poll = active_polls[room]
        delta_t = poll.dt_start + timedelta(minutes=poll.duration)
        seconds_left = (delta_t - datetime.now()).total_seconds()
        if seconds_left < 1:
            self._on_poll_finished(room, msg)
        if int(seconds_left) in range(24, 37):
            self.reply(msg, 'Current poll ends in {s} seconds!'.format(s=int(seconds_left)))

    def _on_poll_finished(self, room=None, msg=None):
        poll = active_polls[room]

        # remove poll and service
        del active_polls[room]
        self.xmpp.scheduler.remove(poll.service_name)

        vc = len(poll.votes)
        if vc < 1:
            self.reply(msg, 'Poll canceled. No votes have been placed!')
            return
        results = []
        for i in range(0, len(poll.options)):
            results.append(0)
        for val in poll.votes.values():
            results[val[1]] += 1
        reply  = 'Poll from {owner} finished!\n'
        reply += 'The topic was: {topic}\n'
        reply += 'These are the final results based on {count} votes:\n'
        winner_msg = None
        winner_perc = 0
        winner_count = 0
        for i in range(0, len(poll.options)):
            pperc = results[i] / vc
            bar_width = int(pperc * 10)
            reply += '   [{bar:<10}] {perc:>3}% ({count:>2}) {option}\n'.format(
                option=poll.options[i],
                bar="■"*bar_width,
                perc=int(pperc * 100),
                count=results[i])
            if pperc > winner_perc:
                winner_msg = poll.options[i]
                winner_perc = pperc
                winner_count = 1
            elif pperc == winner_perc:
                winner_count += 1
        if winner_count > 1:
            reply += '*** We have got a tie! No winner. ***'
        else:
            reply += '*** The winner is: {winner} ***'
        self.reply(msg, reply.format(
            owner=poll.owner[0],
            topic=poll.topic,
            count=vc,
            winner=winner_msg,
        ))
