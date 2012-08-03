#!/usr/bin/python3
from hub import HubBot
from sleekxmpp.xmlstream import ET
import sys, os
import subprocess

class Zombopull(HubBot):
    LOCALPART = "zombopull"
    PASSWORD = ""
    GIT_NODE = "git@"+HubBot.FEED
    
    def __init__(self):
        super(Zombopull, self).__init__(self.LOCALPART, "core", self.PASSWORD)
        self.switch, self.nick = self.addSwitch("bots", "zombopull")
        self.add_event_handler("pubsub_publish", self.pubsubPublish)

    def sessionStart(self, event):
        super(Zombopull, self).sessionStart(event)
        iq = self.pubsub.get_subscriptions(self.FEED, self.GIT_NODE)
        if len(iq["pubsub"]["subscriptions"]) == 0:
            self.pubsub.subscribe(self.FEED, self.GIT_NODE, bare=True)

    def docsSwitch(self, msg):
        pass

    def sendToSwitch(self, contents):
        self.send_message(mto=self.switch,
            mbody=contents,
            mtype="groupchat")

    def pubsubPublish(self, msg):
        item = msg["pubsub_event"]["items"]["item"].xml[0]
        repo = item.findtext("{http://hub.sotecware.net/xmpp/git-post-update}repository")
        if repo is None:
            print("Malformed git-post-update.")
        ref = item.findtext("{http://hub.sotecware.net/xmpp/git-post-update}ref")
        if ref is None:
            print("Malformed git-post-update.")

        ptr = (repo, ref.split("/")[2])
        self.sendToSwitch("received post-update at {0}/{1}".format(*ptr))
        if ptr in [("pyweb", "devel"), ("zombofant.net", "master")]:
            self._pull()

    def _pull(self):
        changes = False
        os.chdir("/var/www/net/zombofant/pyweb")
        out = subprocess.check_output(["git", "pull", "origin", "devel"]).decode()
        if not "Already up-to-date" in out:
            changes = True
            self.sendToSwitch("jonas: apache might need restart")
            for line in out.split("\n"):
                self.sendToSwitch(line)
        os.chdir("/var/www/net/zombofant/root")
        out = subprocess.check_output(["git", "pull", "origin", "master"]).decode()
        if not "Already up-to-date" in out:
            changes = True
            for line in out.split("\n"):
                self.sendToSwitch(line)
            subprocess.check_call(["touch", "site/sitemap.xml"])
        if changes:
            self.sendToSwitch("Changes to zombofant.net were made and applied.")
        else:
            self.sendToSwitch("Got post-update, but no changes present.")
        
    def authorizedSource(self, msg):
        origin = str(msg["from"].bare)
        if not origin in self.authorized:
            if not origin in self.blacklist:
                self.reply(msg, "You're not authorized.")
                self.blacklist.add(origin)
            return

    def messageMUC(self, msg):
        if msg["mucnick"] == self.nick:
            return
        contents = msg["body"].strip()
        if contents == "ping":
            self.reply(msg, "pong")
            return
        #if not self.authorizedSource(msg):
        #    return

    COMMANDS = {
    }

if __name__=="__main__":
    bot = Zombopull()
    bot.run()
    
