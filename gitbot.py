#!/usr/bin/python3
"""
Gitbot should be called from the repositories root path, which should be named
$reponame.git (default in gitolite). It takes the current cwd to determine the
repositories name. It takes the same arguments as the post-update hook of git
(surprise). So you can just symlink hooks/post-update to this file and set it
to be executable.
"""


from hub import HubBot
from sleekxmpp.exceptions import IqError
from sleekxmpp.xmlstream import ET
import logging, warnings

import os, select, sys, subprocess, socket

class GitBot(HubBot):
    LOCALPART = "gitolite"
    PASSWORD = ""
    PUBSUB = "git@"+HubBot.FEED

    xmlns = "http://hub.sotecware.net/xmpp/git-post-update"
    
    def __init__(self, repo, repoPath, refs):
        super(GitBot, self).__init__(self.LOCALPART, None, self.PASSWORD)
        self.repo = repo
        self.repoPath = repoPath
        self.refs = refs

    def _submit(self, repoName, refPath):
        tree = ET.Element("{{{0}}}git".format(self.xmlns))
        repo = ET.SubElement(tree, "{{{0}}}repository".format(self.xmlns))
        repo.text = repoName
        ref = ET.SubElement(tree, "{{{0}}}ref".format(self.xmlns))
        ref.text = refPath
        newRef = ET.SubElement(tree, "{{{0}}}new-ref".format(self.xmlns))
        self._refToETree(newRef, refPath)
        self.pubsub.publish(self.FEED, self.PUBSUB,
            payload=tree,
            block=True)

    def _personRefToETree(self, parent, nodeName, line):
        node = ET.SubElement(parent, "{{{0}}}{1}".format(self.xmlns, nodeName))
        components = line.split(" ")
        email = components[-3]
        name = " ".join(components[1:-3])
        node.text = name
        node.set("email", email)

    def _refToETree(self, parent, ref):
        output = subprocess.check_output(["git", "cat-file", "-p", ref]).decode().split("\n")
        for i, line in enumerate(output):
            line = line.strip()
            if line.startswith("parent "):
                commit = ET.SubElement(parent, "{{{0}}}parent".format(self.xmlns))
            elif line.startswith("author "):
                self._personRefToETree(parent, "author", line)
            elif line.startswith("committer "):
                self._personRefToETree(parent, "committer", line)
            elif not line:
                break
        message = ET.SubElement(parent, "{{{0}}}headline".format(self.xmlns))
        try:
            message.text = output[i+1]
        except IndexError:
            pass
    
    def sessionStart(self, event):
        super(GitBot, self).sessionStart(event)
        try:
            self.socket.setsockopt(socket.SOL_TCP, socket.TCP_NODELAY, 1)
        except Exception as err:
            warnings.warn(err)
        try:
            self.socket.setsockopt(socket.SOL_TCP, socket.TCP_CORK, 0)
        except Exception as err:
            warnings.warn(err)
        iq = self.pubsub.get_nodes(self.FEED)
        items = iq['disco_items']['items']
        for server, node, _ in items:
            if server == self.FEED and node == self.PUBSUB:
                break
        else:
            self.pubsub.create_node(self.FEED, self.PUBSUB)

        try:
            for ref in self.refs:
                self._submit(self.repo, ref)
            print("please be patient, but just kill me if I take longer than \
five seconds")
        finally:
            self.auto_reconnect = False
            self.disconnect(reconnect=False, wait=False)

    def poll(self):
        read, _, _ = select.select([self.fifo], [], [], 0.5)
        if len(read) > 0:
            repository, ref, newref = self.fifo.readline().split()
            
        

if __name__=="__main__":
    logging.basicConfig(level=logging.ERROR,
                        format='%(levelname)-8s %(message)s')

    repoPath = os.getcwd()
    if repoPath[-1:] == "/":
        repoPath = repoPath[:-1]
    repo, _ = os.path.splitext(os.path.basename(repoPath))
    refs = sys.argv[1:]
    bot = GitBot(repo, repoPath, refs)
    bot.run()
