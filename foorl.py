#!/usr/bin/python3
from hub import HubBot
from sleekxmpp.exceptions import IqError
from sleekxmpp.xmlstream import ET

import subprocess, re

class Foorl(HubBot):
    LOCALPART = "foorl"
    PASSWORD = ""
    GIT_NODE = "git@"+HubBot.FEED
    USER_AGENT = "foorl/23.42"

    def __init__(self):
        super(Foorl, self).__init__(self.LOCALPART, "fnord", self.PASSWORD)
        self.rooms = ["physiknerds@conference.zombofant.net"]
        self.switch, self.nick = self.addSwitch("bots", "foorl")
        self.patterns = [
            (re.compile("^!(\w+)\s*([^\n]+)\s*$"),
                    self.matchCommand),
            (re.compile("(rfc|xep|pep)(\s*|-)([0-9]+)", re.I),
                    self.matchDocument),
            (re.compile("(https?)://[^/>\s]+(/[^>\s]+)?", re.I),
                    self.matchURL)
        ]
    
        self.commandMap = {
            "say": self.cmdSay,
            "whois": self.cmdWhois,
            "host": self.cmdHost,
        }

    def sessionStart(self, event):
        super(Foorl, self).sessionStart(event)
        for room in self.rooms:
            self.muc.joinMUC(room, self.nick)
            
    def reply(self, msg, content):
        if msg["type"] == "groupchat":
            self.send_message(msg["mucroom"], mbody=content, mtype="groupchat")
        else:
            self.send_message(msg["from"], mbody=content, mtype=msg["type"])

    def messageMUC(self, msg):
        if msg["mucnick"] == self.nick:
            return
        contents = msg["body"].strip()
        if contents == "ping":
            self.reply(msg, "pong")
            return

        for pattern, handler in self.patterns:
            doBreak = False
            for match in pattern.finditer(contents):
                if match:
                    if handler(msg, match):
                        doBreak = True
                        break
            if doBreak:
                break

    def matchCommand(self, msg, match):
        cmd, args = match.groups()
        try:
            handler = self.commandMap[cmd]
        except KeyError:
            return False
        try:
            handler(msg, args)
        finally:
            return True

    def matchDocument(self, msg, match):
        pass

    def matchURL(self, msg, match):
        pass

    def cmdSay(self, msg, args):
        self.reply(msg, args)

    def cmdWhois(self, msg, args):
        pass

    def cmdHost(self, msg, args):
        pass

if __name__=="__main__":
    bot = Foorl()
    bot.run()
