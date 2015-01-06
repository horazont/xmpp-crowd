import foomodules.Base as Base

import argparse
import tweepy

class TwitlerCommand(Base.ArgparseCommand):

    def __init__(self, consumer_key, consumer_secret, access_key,
            access_secret, verify_credentials=True,
            command_name="twitler", **kwargs):
        super().__init__(command_name, **kwargs)

        self._subparsers = self.argparse.add_subparsers()
        self._available_commands = []

        parser = self._add_command('tweet', self._cmd_tweet)
        parser.add_argument('text', nargs=argparse.REMAINDER)

        parser = self._add_command('revoke', self._cmd_revoke)
        parser.add_argument('tweet_id', nargs=1, type=int)

        parser = self._add_command('status', self._cmd_status)

        # twitter setup
        auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
        auth.set_access_token(access_key, access_secret)
        self._twitter_api = tweepy.API(auth)
        if verify_credentials and not self._twitter_api.verify_credentials():
            raise ValueError('Invalid twitter credentials')

    def _add_command(self, command_name, command_func):
        parser = self._subparsers.add_parser(command_name)
        self._available_commands.append(command_name)
        parser.set_defaults(func=command_func)
        return parser

    def _call(self, msg, args, errorSink=None):
        if 'func' in args:
            try:
                args.func(msg, args, errorSink)
            except tweepy.error.TweepError:
                self.reply(msg, ("Access denied. "
                                 "Did we run into rate limiting?"))
        else:
            self.reply(msg,
                    "No command given. Try one of {commands}.".format(
                        commands=', '.join(self._available_commands)))
        return True

    def _twitter_get_user(self):
        return self._twitter_api.me()

    def _cmd_tweet(self, msg, args, errorSink=None):
        if len(args.text) < 1:
            self.reply(msg, "Cannot tweet *nothing*.")
        else:
            text = ' '.join(args.text)
            if len(text) > 140:
                self.reply(msg, ("Invalid message: Twitter requires "
                                 "messages to be no longer than 140 "
                                 "characters."))
            else:
                status = self._twitter_api.update_status(text)
                self.reply(msg, "Tweeted message with id {sid}.".format(
                    sid=status.id))

    def _cmd_revoke(self, msg, args, errorSink=None):
        self._twitter_api.destroy_status(args.tweet_id)
        self.reply(msg, "Message revoked.")

    def _cmd_status(self, msg, args, errorSink=None):
        user = self._twitter_get_user()
        self.reply(msg, ("This is {screen_name}. "
                         "I have {follower_count} followers and "
                         "{friend_count} friends.")
                         .format(
                             screen_name=user.screen_name,
                             follower_count=len(user.followers()),
                             friend_count=len(user.friends())))
        self.reply(msg, ("Current status with id {sid} is: {text}".format(
            sid=user.status.id,
            text=user.status.text)))