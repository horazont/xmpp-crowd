
from datetime import datetime, timedelta

import foomodules.Base as Base

active_polls = {}

class PollModel(object):
    def __init__(self, owner=None, dt_start=datetime.now(), duration=1, topic=None, options=[]):
        self.owner = owner
        self.dt_start = dt_start
        self.duration = duration
        self.topic = topic
        self.options = options
        self.votes = {}

class Vote(Base.ArgparseCommand):
    def __init__(self, timeout=3, command_name="vote", maxlen=64, **kwargs):
        super().__init__(command_name, **kwargs)
        self.timeout = timeout
        self.maxlen = maxlen
        self.argparse.add_argument(
            "index",
            nargs="?",
            help="The index of the option you are voting for.",
        )

    def _call(self, msg, args, errorSink=None):
        mucname = msg.get_mucroom()
        jid = msg.get_from()
        nick = msg.get_mucnick()
        # get vote for this room if available
        try:
            poll = active_polls[mucname]
            if args.index is not None:
                args.index = int(args.index)
                if args.index < 1 or args.index > len(poll.options):
                    self.reply(msg, "There is no option with index {t} for this poll. Try !vote".format(i=args.index))
                    return
                poll.votes[jid] = (nick, args.index - 1)
                reply = "{user}: Your vote for option {i} has been counted!".format(user=nick, i=args.index)
            else:
                delta_t = poll.dt_start + timedelta(minutes=poll.duration) - datetime.now()
                minutes_left = int(delta_t.total_seconds() / 60)
                seconds_left = int(delta_t.total_seconds() % 60)
                reply  = "There is an active poll from {owner} in this room!\n".format(owner=poll.owner[0])
                reply += "Topic: {topic}\n".format(topic=poll.topic)
                reply += "You have {tm} minutes and {ts} seconds left to vote for one of:\n".format(tm=minutes_left, ts=seconds_left)
                for i in range(0, len(poll.options)):
                    reply += "    {index}: {option}\n".format(index=i+1, option=poll.options[i])
                reply += "{count} votes have been placed so far. ".format(count=len(poll.votes.keys()))
                reply += "Place your vote with !vote <index>"
        except KeyError:
            reply = "No active poll in this room. You may start one with !startpoll."
        self.reply(msg, reply)
 
class StartPoll(Base.ArgparseCommand):
    def __init__(self, timeout=3, command_name="startpoll", maxlen=256, **kwargs):
        super().__init__(command_name, **kwargs)
        self.timeout = timeout
        self.maxlen = maxlen
        #self.argparse.add_argument(     
        #    "-p", "--publiconly",
        #    action="store_true",
        #    dest="public",
        #    default=False,
        #    help="Do not allow secret votes.",
        #)
        self.argparse.add_argument(
            "-d", "--duration",
            dest="duration",
            default=1,
            help="Duration of the poll in minutes (defaults to: 1)"
        )
        self.argparse.add_argument(
            "topic",
            help="The topic of the poll (e.g. a question)"
        )
        self.argparse.add_argument(
            "options",
            nargs="+",
            help="The options voters may choose from.",
        )

    def _call(self, msg, args, errorSink=None):
        mucname = msg.get_mucroom()
        if mucname in active_polls.keys():
            self.reply(msg, "There is already an active poll for this room. See !vote or !stoppoll")
            return
        args.duration = int(args.duration)
        # maybe we want to allow for longer vote durations
        # however, votes may block other votes in the channel
        if args.duration < 1 or args.duration > 60:
            self.reply(msg, "Poll duration must be in range [1, 60] ∌ {t}".format(t=args.duration))
            return
        if len(args.options) < 2:
            self.reply(msg, "You have to specify at least 2 options to choose from ;)")
            return
        if len(args.options) > 9:
            self.reply(msg, "You must not set more than 9 vote options!")
            return

        owner_info = (msg.get_mucnick(), msg.get_from())
        poll = PollModel(owner=owner_info, dt_start=datetime.now(), duration=args.duration,
                         topic=args.topic, options=args.options)
        active_polls[mucname] = poll

        # schedule events related to this vote
        self.xmpp.scheduler.add("{muc}_finish".format(muc=mucname), args.duration * 60, self._on_finish)

        reply  = "User {the_owner} has started a poll!\n".format(the_owner=owner_info[0])
        reply += "Topic: {the_topic}\n".format(the_topic=args.topic)
        reply += "You have {t} minute(s) to vote for one of the following options:\n".format(t=args.duration)
        for i in range(0, len(args.options)):
            reply += "   {index}: {option_text}\n".format(index=i+1, option_text=args.options[i])
        reply += "Use !vote <n> to place your vote. {owner} may cancel the poll with !stoppoll".format(owner=owner_info[0])

        self.reply(msg, reply)

    def _on_finish(self):
        polls_to_del = []
        for key in active_polls.keys():
            poll = active_polls[key]
            finish_t = poll.dt_start + timedelta(minutes=poll.duration)
            if (finish_t - datetime.now()).total_seconds() <= 0:
                polls_to_del.append(key)
                vc = len(poll.votes)
                if vc < 1:
                    body = "Poll from {owner} canceled. No votes have been placed!".format(owner=poll.owner[0])
                    self.xmpp.send_message(mtype="groupchat", mto=key, mbody=body)
                    continue
                results = []
                for i in range(0, len(poll.options)):
                    results.append(0)
                for val in poll.votes.values():
                    results[val[1]] += 1
                msg  = "Poll from {owner} finished!\n".format(owner=poll.owner[0])
                msg += "The topic was: {topic}\n".format(topic=poll.topic)
                msg += "These are the final results based on {count} votes:\n".format(count=vc)
                winner_msg = None
                winner_perc = 0
                for i in range(0, len(poll.options)):
                    pperc = results[i] / vc
                    bar_width = int(pperc * 10)
                    msg += "   {index}: [{bar:<10}] {perc:>3}% ({count:>2}) {option}\n".format(
                        index=i+1, option=poll.options[i], bar="■"*bar_width,
                        perc=int(pperc * 100), count=results[i])
                    if pperc > winner_perc:
                        winner_msg = poll.options[i]
                msg += "*** The winner is: {winner} ***\n".format(winner=winner_msg)
                self.xmpp.send_message(mtype="groupchat", mto=key, mbody=msg)
        for key in polls_to_del:
            del active_polls[key]

class StopPoll(Base.MessageHandler):
    def __call__(self, msg, arguments, errorSink=None):
        if arguments.strip():
            return
        user = msg.get_from()
        mucname = msg.get_mucroom()
        try:
            poll = active_polls[mucname]
            if poll.owner[1] == user:
                del active_polls[mucname]
                self.reply(msg, "Poll has been canceled by creator.")
            else:
                self.reply(msg, "You are not the creator of the current poll!")
        except KeyError:
            self.reply(msg, "No active poll found! You may want to start one with !startpoll")

