#!/usr/bin/python3
from hub import HubBot
from sleekxmpp.exceptions import IqError
from sleekxmpp.xmlstream import ET

import subprocess
import re
import logging
import foomodules

class Foorl(HubBot):
    def __init__(self):
        self.config = foomodules.FoorlConfig("foorl_config")
        super(Foorl, self).__init__(self.config.localpart, self.config.resource, self.config.password)

    def sessionStart(self, event):
        super(Foorl, self).sessionStart(event)
        self.config.session_start(self)

    def sessionEnd(self, event):
        for hook in self.config.hooks.get("session_end", []):
            try:
                hook()
            except Exception as err:
                logging.exception(err)


    def reply(self, msg, content):
        if msg["type"] == "groupchat":
            self.send_message(msg["mucroom"], mbody=content, mtype="groupchat")
        else:
            self.send_message(msg["from"], mbody=content, mtype=msg["type"])

    def message(self, msg):
        self.config.dispatch(msg)

if __name__=="__main__":
    try:
        import setproctitle
        setproctitle.setproctitle("foorl")
    except ImportError:
        pass
    logging.basicConfig(level=logging.INFO,
                        format='%(levelname)-8s %(message)s')

    bot = Foorl()
    bot.run()
