#!/usr/bin/python3
from hub import HubBot
import traceback
import sys, os
import select
import threading
import subprocess

class Branch(object):
    def __init__(self, branchName, docOutputPath, makeCall, submodules=[],
            sphinxOutDir="docs/sphinx/build/html",
            configureCall=["cmake", "."]):
        self.branchName = branchName
        self.docOutputPath = docOutputPath
        self.submodules = list(submodules)
        self.sphinxOutDir = sphinxOutDir
        self.makeCall = makeCall
        self.configureCall = configureCall
    
    def _fetchSubmodules(self, check_call):
        prevdir = os.getcwd()
        for submodule in self.submodules:
            os.chdir(os.path.join(prevdir, submodule))
            try:
                check_call(["git", "fetch", "origin"])
            finally:
                os.chdir(prevdir)

    def buildDocs(self, check_call):
        check_call(["git", "checkout", "origin/"+self.branchName])
        check_call(["git", "submodule", "init"])
        self._fetchSubmodules(check_call)
        check_call(["git", "submodule", "update"])
        try:
            check_call(["rm", "-rf", self.sphinxOutDir])
        except:
            pass
        if self.configureCall:
            check_call(self.configureCall)
        check_call(self.makeCall)
        try:
            check_call(["rm", "-rf", self.docOutputPath])
        except:
            pass
        check_call(["cp", "-r", os.path.abspath(self.sphinxOutDir), self.docOutputPath])
        

class Project(object):
    def __init__(self, *args, **kwargs):
        super(Project, self).__init__()
        self.branches = list(map(self.checkBranch, args))
        try:
            self.gitCheckoutPath = kwargs["checkoutPath"]
            self.cloneSource = kwargs["cloneSource"]
            self.triggers = kwargs.get("triggers", [])
        except KeyError as err:
            raise ValueError("Required parameter undefined: {0}".format(str(err)))

    def checkBranch(self, branch):
        if not isinstance(branch, Branch):
            raise TypeError("{0} only accepts Branches as arguments. (Got {1!r})".format(type(self).__name__, branch))
        return branch.branchName, branch

    def _submitBuf(self, buf, logFunc, force=False):
        if not b"\n" in buf:
            if force:
                logFunc(buf.decode().strip())
                return b""
            else:
                return buf

        split = buf.split(b"\n")
        for line in split[:-1]:
            line = line.decode().strip()
            if line:
                logFunc(line)
        return split[-1]

    def _loggedCheckCall(self, logFunc, call, *args, **kwargs):
        proc = subprocess.Popen(call, *args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        buffers = [b"", b""]
        rList = [proc.stdout, proc.stderr]
        while True:
            rs, _, _ = select.select(rList, [], [])
            for i, r in enumerate(reversed(rs)):
                read = r.readline()
                if len(read) == 0:
                    del rList[len(rs)-(i+1)]
                buffers[i] += read
                buffers[i] = self._submitBuf(buffers[i], logFunc)
            if len(rList) == 0:
                break
        for buf in buffers:
            self._submitBuf(buf, logFunc, True)
        retcode = proc.wait()
        if retcode != 0:
            raise subprocess.CalledProcessError("Process returned with error code {0}".format(retcode))
        del proc

    def rebuild(self, logFunc=None):
        if logFunc is not None:
            check_call = lambda *args, **kwargs: self._loggedCheckCall(logFunc, *args, **kwargs)
        else:
            check_call = subprocess.check_call
        dir = os.getcwd()
        try:
            if not os.path.isdir(self.gitCheckoutPath):
                os.makedirs(self.gitCheckoutPath)
                os.chdir(self.gitCheckoutPath)
                check_call(["git", "clone", "-q", self.cloneSource, "."])
            else:
                os.chdir(self.gitCheckoutPath)
                check_call(["git", "fetch", "origin"])
            
            for branchName, branch in self.branches:
                branch.buildDocs(check_call)
        finally:
            os.chdir(dir)

    @classmethod
    def declare(cls, name, *args, **kwargs):
        return (name, cls(*args, **kwargs))

class DocBot(HubBot):
    LOCALPART = "docbot"
    PASSWORD = ""
    GIT_NODE = "git@"+HubBot.FEED
    
    def __init__(self):
        super(DocBot, self).__init__(self.LOCALPART, "core", self.PASSWORD)
        self.switch, self.nick = self.addSwitch("docs", "docbot", self.docsSwitch)
        self.addSwitch("bots", "docbot")
        error = self.reloadConfig()
        if error:
            traceback.print_exception(*error)
            sys.exit(1)

        self.add_event_handler("pubsub_publish", self.pubsubPublish)

    def sessionStart(self, event):
        super(DocBot, self).sessionStart(event)
        iq = self.pubsub.get_subscriptions(self.FEED, self.GIT_NODE)
        if len(iq["pubsub"]["subscriptions"]) == 0:
            self.pubsub.subscribe(self.FEED, self.GIT_NODE, bare=True)
        self.send_message(mto=self.switch, mbody="", msubject="idle", mtype="groupchat")

    def reloadConfig(self):
        namespace = {}
        f = open("docbot_config.py", "r")
        conf = f.read()
        f.close()
        try:
            exec(conf, globals(), namespace)
        except Exception:
            return sys.exc_info()
        self.authorized = set(namespace.get("authorized", []))
        self.blacklist = set()
        self.projects = dict(namespace.get("projects", []))

        self.repoBranchMap = {}
        for name, project in self.projects.items():
            project.name = name
            for trigger in project.triggers:
                self.repoBranchMap[trigger] = project
        return None

    def docsSwitch(self, msg):
        pass

    def pubsubPublish(self, msg):
        item = msg["pubsub_event"]["items"]["item"].xml[0]
        repo = item.findtext("{http://hub.sotecware.net/xmpp/git-post-update}repository")
        if repo is None:
            print("Malformed git-post-update.")
        ref = item.findtext("{http://hub.sotecware.net/xmpp/git-post-update}ref")
        if ref is None:
            print("Malformed git-post-update.")

        triggerPtr = (repo, ref.split("/")[2])
        try:
            project = self.repoBranchMap[triggerPtr]
        except KeyError:
            print(triggerPtr)
            return
        self.rebuild(project)

    def formatException(self, exc_info):
        return "\n".join(traceback.format_exception(*sys.exc_info()))

    def replyException(self, msg, exc_info):
        self.reply(msg, self.formatException(exc_info))

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

    def message(self, msg):
        if msg["type"] == "groupchat":
            return

        contents = msg["body"]
        args = contents.split(" ")
        cmd = args[0]
        args = args[1:]
        handler = self.COMMANDS.get(cmd, None)
        if handler is not None:
            try:
                local = {"__func": handler, "__self": self, "__msg": msg}
                self.reply(msg, repr(eval("__func(__self, __msg, {0})".format(", ".join(args)), globals(), local)))
            except Exception:
                self.replyException(msg, sys.exc_info())
        else:
            self.reply(msg, "Unknown command: {0}".format(cmd))

    def rebuild(self, project):
        topic = "Rebuilding docs for {0}".format(project.name)
        self.send_message(mto=self.switch, mbody="", msubject=topic, mtype="groupchat")
        try:
            logFunc = lambda body: self.send_message(mto=self.switch, mbody=body, mtype="groupchat")
            logFunc(topic)
            project.rebuild(logFunc)
            logFunc("Done!")
        except Exception as err:
            self.send_message(mto=self.switch, mbody="jonas: Project {0} is broken, traceback follows".format(project.name), mtype="groupchat")
            self.send_message(mto=self.switch, mbody=self.formatException(err), mtype="groupchat")
            print("Exception during docbuild logged to muc.")
        finally:
            self.send_message(mto=self.switch, mbody="", msubject="idle", mtype="groupchat")

    def cmdRebuild(self, msg, projectName):
        project = self.projects.get(projectName, None)
        if not project:
            return "Unknown project: {0}".format(projectName)
        self.rebuild(project)
        return True

    def cmdReload(self, msg):
        result = self.reloadConfig()
        if result:
            self.replyException(msg, result)
        else:
            return True

    def cmdEcho(self, msg, *args):
        return " ".join((str(arg) for arg in args))

    COMMANDS = {
        "rebuild": cmdRebuild,
        "reload": cmdReload,
        "echo": cmdEcho
    }

if __name__=="__main__":
    docbot = DocBot()
    docbot.run()
    
