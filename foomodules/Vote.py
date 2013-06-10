
from datetime import datetime, timedelta

import foomodules.Base as Base

current_votes = {}

class VoteModel(object):
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
            vote = current_votes[mucname]
            if args.index is not None:
                args.index = int(args.index)
                if args.index < 1 or args.index > len(vote.options):
                    self.reply(msg, "There is no option with index {t} for this vote.".format(i=args.index))
                    return
                vote.votes[jid] = (nick, args.index)
                reply = "{user}: Your vote for option {i} has been counted!".format(user=nick, i=args.index)
            else:
                delta_t = vote.dt_start + timedelta(0, 0, 0, 0, vote.duration) - datetime.now()
                minutes_left = int(delta_t.total_seconds() / 60)
                seconds_left = int(delta_t.total_seconds() % 60)
                reply  = "There is an active vote from {owner} in this room!\n".format(owner=vote.owner[0])
                reply += "Topic: {topic}\n".format(topic=vote.topic)
                reply += "You have {tm} minutes and {ts} seconds left to vote for one of:\n".format(tm=minutes_left, ts=seconds_left)
                for i in range(0, len(vote.options)):
                    reply += "    {index}: {option}\n".format(index=i+1, option=vote.options[i])
                reply += "{count} votes have been placed so far. ".format(count=len(vote.votes.keys()))
                reply += "Place your vote with !vote <index>"
        except KeyError:
            reply = "No active vote in this room. You may start one with !startvote."
        self.reply(msg, reply)
 
class StartVote(Base.ArgparseCommand):
    def __init__(self, timeout=3, command_name="startvote", maxlen=256, **kwargs):
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
            help="Duration of the vote in minutes (defaults to: 1)"
        )
        self.argparse.add_argument(
            "topic",
            help="The topic of the vote (e.g. a question)"
        )
        self.argparse.add_argument(
            "options",
            nargs="+",
            help="The options voters may choose from.",
        )

    def _call(self, msg, args, errorSink=None):
        mucname = msg.get_mucroom()
        if mucname in current_votes.keys():
            self.reply(msg, "There is already an active vote for this room. See !vote or !stopvote")
            return
        args.duration = int(args.duration)
        # maybe we want to allow for longer vote durations
        # however, votes may block other votes in the channel
        if args.duration < 1 or args.duration > 60:
            self.reply(msg, "Vote duration must be in range [1, 60] ∌ {t}".format(t=args.duration))
            return
        if len(args.options) < 2:
            self.reply(msg, "You have to specify at least 2 options to vote from ;)")
            return
        if len(args.options) > 9:
            self.reply(msg, "You must not set more than 9 vote options!")
            return

        owner_info = (msg.get_mucnick(), msg.get_from())
        vote = VoteModel(owner=owner_info, dt_start=datetime.now(), duration=args.duration, topic=args.topic, options=args.options)
        current_votes[mucname] = vote

        reply  = "User {the_owner} has started a vote!\n".format(the_owner=owner_info[0])
        reply += "Topic: {the_topic}\n".format(the_topic=args.topic)
        reply += "You have {t} minute(s) to vote for one of the following options:\n".format(t=args.duration)
        for i in range(0, len(args.options)):
            reply += "   {index}: {option_text}\n".format(index=i+1, option_text=args.options[i])
        reply += "Use !vote <n> to place your vote."

        self.reply(msg, reply)

class StopVote(Base.MessageHandler):
    def __call__(self, msg, arguments, errorSink=None):
        if arguments.strip():
            return
        user = msg.get_from()
        mucname = msg.get_mucroom()
        try:
            vote = current_votes[mucname]
            if vote.owner[1] == user:
                del current_votes[mucname]
                self.reply(msg, "Vote has been canceled by creator.")
            else:
                self.reply(msg, "You are not the creator of the current vote!")
        except KeyError:
            self.reply(msg, "No active vote found! You may want to start one with !startvote")

