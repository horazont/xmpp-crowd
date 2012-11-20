#!/usr/bin/python3
from hub import HubBot
import traceback
import itertools
import sys
import os
import select
import threading
import subprocess
import tempfile

class Popen(subprocess.Popen):
    @classmethod
    def checked(cls, call, *args, **kwargs):
        proc = cls(call, *args, **kwargs)
        result = proc.communicate()
        retval = proc.wait()
        if retval != 0:
            raise subprocess.CalledProcessError(retval, " ".join(call))
        return result

    def __init__(self, call, *args, sink_line_call=None, **kwargs):
        if sink_line_call is not None:
            kwargs["stdout"] = subprocess.PIPE
            kwargs["stderr"] = subprocess.PIPE
        super().__init__(call, *args, **kwargs)
        self.sink_line_call = sink_line_call
        if sink_line_call is not None:
            sink_line_call("$ {cmd}".format(cmd=" ".join(call)).encode())

    def _submit_buffer(self, buf, force=False):
        if b"\n" not in buf:
            if force:
                self.sink_line_call(buf)
                return b""
            else:
                return buf

        split = buf.split(b"\n")
        for line in split[:-1]:
            self.sink_line_call(buf)
        return split[-1]

    def communicate(self):
        if self.sink_line_call is not None:
            rlist = set([self.stdout, self.stderr])

            buffers = {
                self.stdout: b"",
                self.stderr: b""
            }
            while True:
                rs, _, _ = select.select(rlist, [], [])
                for fd in rs:
                    fno = fd.fileno()
                    read = fd.readline()
                    if len(read) == 0:
                        rlist.remove(fd)
                        buf = buffers[fd]
                        if len(buf):
                            self._submit_buffer(buf, True)
                        del buffers[fd]
                        continue
                    buffers[fd] += read
                    buffers[fd] = self._submit_buffer(buffers[fd])
                if len(rlist) == 0:
                    break
            for buf in buffers:
                self._submit_buffer(buf, True)
            return None, None
        else:
            return super().communicate()

class WorkingDirectory:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.old_pwd = os.getcwd()
        os.chdir(self.path)
        return self.path

    def __exit__(self, exc_type, exc_value, traceback):
        os.chdir(self.old_pwd)
        del self.old_pwd
        return False

class Target:
    def __init__(self, name, branch):
        super().__init__()
        self.name = name
        self.branch = branch

    def __str__(self):
        return self.name

class Respawn(Target):
    class Forward:
        def __init__(self, to_jid, msg="respawn", mtype="chat", **kwargs):
            super().__init__(**kwargs)
            self.to_jid = to_jid
            self.msg = msg
            self.mtype = mtype

        def do_forward(self, xmpp):
            xmpp.send_message(
                mto=self.to_jid,
                mbody=self.msg,
                mtype=self.mtype
            )

    def __init__(self, name, xmpp,
            branch="master",
            forwards=[],
            **kwargs):
        super().__init__(name, branch, **kwargs)
        self.xmpp = xmpp
        self.forwards = forwards

    def build(self, log_func):
        xmpp = self.xmpp
        for forward in self.forwards:
            log_func("Sending respawn command to {0}".format(forward.to_jid).encode())
            forward.do_forward(xmpp)

        log_func("Respawning self".encode())
        xmpp.disconnect(reconnect=False, wait=True)
        try:
            os.execv(sys.argv[0], sys.argv)
        except:
            print("during execv")
            traceback.print_exc()
            raise

    def __str__(self):
        return "respawn {}".format(self.name)

class Execute(Target):
    def __init__(self, name, *commands,
            working_directory=None,
            branch="master",
            **kwargs):
        super().__init__(name, branch, **kwargs)
        self.working_directory = working_directory
        self.commands = commands

    def _do_build(self, log_func):
        def checked(*args, **kwargs):
            return Popen.checked(*args, sink_line_call=log_func, **kwargs)
        for command in self.commands:
            checked(command)

    def build(self, log_func):
        wd = self.working_directory or os.getcwd()
        with WorkingDirectory(wd):
            self._do_build(log_func)

class Pull(Execute):
    def __init__(self, name, repository_location, branch,
            after_pull_commands=[],
            remote_location=None):
        super().__init__(name, *after_pull_commands,
            working_directory=repository_location)
        self.remote_location = remote_location
        self.branch = branch

    def _do_build(self, log_func):
        def checked(*args, **kwargs):
            return Popen.checked(*args, sink_line_call=log_func, **kwargs)
        output = subprocess.check_output(["git", "stash"])
        stashed = b"No local changes to save\n" != output
        try:
            call = ["git", "pull", "--rebase"]
            if self.remote_location:
                call.extend(self.remote_location)
            checked(call)
        except subprocess.CalledProcessError:
            # pull failed, this is quite bad
            log_func("pull failed, trying to restore previous state.".encode())
            if stashed:
                log_func("NOTE: There is a stash which needs to be un-stashed!".encode())
            raise
        if stashed:
            checked(["git", "stash", "pop"])
        super()._do_build(log_func)
        output = subprocess.check_output(["git", "log", "--oneline", "HEAD^..HEAD"]).decode().strip()
        log_func("{0} is now at {1}".format(self.name, output).encode())

    def __str__(self):
        return "pull {0}".format(self.name)

class Build(Execute):
    def __init__(self, name, *args,
            submodules=[],
            commands=["make"],
            working_copy=None,
            **kwargs):
        super().__init__(name, *commands, **kwargs)
        self.submodules = submodules
        self.working_copy = working_copy

    def build_environment(self, log_func):
        return self.project.build_environment(
            log_func,
            self.branch,
            self.submodules,
            working_copy=self.working_copy
        )

    def _do_build(self, env):
        def checked(*args, **kwargs):
            return Popen.checked(*args, sink_line_call=env.log_func, **kwargs)

        for command in self.commands:
            checked(command)

    def build(self, log_func):
        with self.build_environment(log_func) as env:
            self._do_build(env)

    def __str__(self):
        return "build {0}".format(self.name)

class BuildAndMove(Build):
    def __init__(self, *args, move_to=None, move_from=None, **kwargs):
        super().__init__(*args, **kwargs)
        if not move_to:
            raise ValueError("Required parameter move_to missing or empty.")
        self.move_to = move_to
        self.move_from = move_from

    def _do_build(self, env):
        def checked(*args, **kwargs):
            return Popen.checked(*args, sink_line_call=env.log_func, **kwargs)

        super()._do_build(env)
        if self.move_from is not None:
            move_from = self.move_from.format(
                builddir=env.tmp_dir
            )
        else:
            move_from = env.tmp_dir
        checked(["rm", "-rf", self.move_to])
        checked(["mv", move_from, self.move_to])


class BuildEnvironment:
    def __init__(self, tmp_dir, repo_url, branch, submodules, log_func):
        self.tmp_dir_context = None
        self.tmp_dir = tmp_dir
        self.repo_url = repo_url
        self.branch = branch
        self.submodules = submodules
        self.log_func = log_func

    def __enter__(self):
        def checked(*args, **kwargs):
            return Popen.checked(*args, sink_line_call=self.log_func, **kwargs)

        if self.tmp_dir is None:
            self.tmp_dir_context = tempfile.TemporaryDirectory()
            self.tmp_dir = self.tmp_dir_context.name
        try:
            if not os.path.isdir(self.tmp_dir):
                os.makedirs(self.tmp_dir)
            os.chdir(self.tmp_dir)
            if os.path.isdir(os.path.join(self.tmp_dir, ".git")):
                checked(["git", "fetch", "origin"])
            else:
                checked(["git", "clone", self.repo_url, self.tmp_dir])

            checked(["git", "checkout", self.branch])
            checked(["git", "pull"])

            for submodule in self.submodules:
                checked(["git", "submodule", "init", submodule])
                checked(["git", "submodule", "update", submodule])
        except:
            if self.tmp_dir_context is not None:
                self.tmp_dir_context.cleanup()
            self.tmp_dir_context = None
            raise
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.tmp_dir_context is not None:
            self.tmp_dir_context.cleanup()
        return False


class Project:
    @classmethod
    def declare(cls, name, *args, **kwargs):
        return (name, cls(name, *args, **kwargs))

    def __init__(self, name, *builds,
            repository_url=None, pubsub_name=None, working_copy=None,
            **kwargs):
        super().__init__(**kwargs)
        self.name = name
        self.repository_url = repository_url
        self.pubsub_name = pubsub_name
        self.working_copy = working_copy
        self.builds = builds
        for build in self.builds:
            build.project = self

        if pubsub_name is not None:
            triggers = {}
            for build in self.builds:
                build_list = triggers.setdefault((self.pubsub_name, build.branch), [])
                build_list.append(build)
            self.triggers = triggers
        else:
            self.triggers = {}

    def build_environment(self, log_func, branch, submodules,
            working_copy=None):
        return BuildEnvironment(
            working_copy or self.working_copy,
            self.repository_url,
            branch,
            submodules,
            log_func
        )

    def __str__(self):
        return self.name

class BuildBot(HubBot):
    LOCALPART = "buildbot"
    NICK = "buildbot"
    PASSWORD = ""
    GIT_NODE = "git@"+HubBot.FEED
    CONFIG_FILE = "buildbot_config.py"
    IDLE_MESSAGE = "buildbot waiting for instructions"

    def __init__(self):
        super().__init__(self.LOCALPART, "core", self.PASSWORD)
        self.switch, self.nick = self.addSwitch("build", "buildbot", self.build_switch)
        self.bots_switch, _ = self.addSwitch("bots", "buildbot")
        error = self.reloadConfig()
        if error:
            traceback.print_exception(*error)
            sys.exit(1)

        self.add_event_handler("pubsub_publish", self.pubsubPublish)

    def sessionStart(self, event):
        super().sessionStart(event)
        iq = self.pubsub.get_subscriptions(self.FEED, self.GIT_NODE)
        if len(iq["pubsub"]["subscriptions"]) == 0:
            self.pubsub.subscribe(self.FEED, self.GIT_NODE, bare=True)
        self.send_message(mto=self.switch,
            mbody="",
            msubject=self.IDLE_MESSAGE,
            mtype="groupchat"
        )

    def reloadConfig(self):
        namespace = {}
        with open(self.CONFIG_FILE, "r") as f:
            conf = f.read()

        global_namespace = dict(globals())
        global_namespace["xmpp"] = self
        try:
            exec(conf, global_namespace, namespace)
        except Exception:
            return sys.exc_info()

        self.authorized = set(namespace.get("authorized", []))
        self.blacklist = set()
        self.projects = dict(namespace.get("projects", []))

        self.repobranch_map = {}
        for project in self.projects.values():
            for reprobranch, build in project.triggers.items():
                self.repobranch_map.setdefault(reprobranch, []).extend(build)

        return None

    def build_switch(self, msg):
        pass

    def pubsubPublish(self, msg):
        item = msg["pubsub_event"]["items"]["item"].xml[0]
        repo = item.findtext("{http://hub.sotecware.net/xmpp/git-post-update}repository")
        if repo is None:
            print("Malformed git-post-update.")
        ref = item.findtext("{http://hub.sotecware.net/xmpp/git-post-update}ref")
        if ref is None:
            print("Malformed git-post-update.")

        repobranch = (repo, ref.split("/")[2])
        try:
            builds = self.repobranch_map[repobranch]
        except KeyError:
            print(repobranch)
            return
        try:
            for build in builds:
                self.rebuild(build)
        except Exception as err:
            hint = "Project {0}, target {1!s} is broken, traceback logged to docs".format(
                build.project.name,
                build
            )
            self.send_message(
                mto=self.bots_switch,
                mbody="jonas: {0}".format(hint),
                mtype="groupchat"
            )
            self.send_message(
                mto=self.switch,
                mbody=self.formatException(err),
                mtype="groupchat"
            )
            print(hint)
        finally:
            self.send_message(
                mto=self.switch,
                mbody="",
                msubject=self.IDLE_MESSAGE,
                mtype="groupchat"
            )

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

    def rebuild(self, build):
        def log_func(msg):
            self.send_message(
                mto=self.switch,
                mbody=msg,
                mtype="groupchat"
            )
        def log_func_binary(buf):
            msg = buf.decode().strip()
            if msg:
                log_func(msg)
        project = build.project

        topic = "Running: {project!s} – {build!s}".format(
            project=project,
            build=build
        )
        self.send_message(mto=self.switch, mbody="", msubject=topic, mtype="groupchat")
        log_func(topic)
        build.build(log_func_binary)
        log_func("done.")

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
    try:
        import setproctitle
        setproctitle.setproctitle("constructor")
    except ImportError:
        pass
    buildbot = BuildBot()
    buildbot.run()

