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
import logging
import calendar
import abc
import smtplib
import sleekxmpp.exceptions

from datetime import datetime, timedelta

import email.message
import email.mime.text
import email.mime.multipart

from wsgiref.handlers import format_date_time

logger = logging.getLogger(__name__)

def smtp_insecure(host, port):
    return smtplib.SMTP(host, port)

def smtp_ssl(host, port):
    return smtplib.SMTP_SSL(host, port)

def smtp_starttls(host, port):
    smtp = smtplib.SMTP(host, port)
    smtp.starttls()
    return smtp

class MailSendConfig(metaclass=abc.ABCMeta):
    @classmethod
    def _mime_to_bytes(cls, mime):
        from io import StringIO
        from email.generator import Generator
        fp = StringIO()
        g = Generator(fp, mangle_from_=False)
        g.flatten(mime)
        return fp.getvalue()

    @abc.abstractmethod
    def send_mime_mail(self, mime_mail):
        pass

class MailSMTPConfig(MailSendConfig):

    SEC_NONE = smtp_insecure
    SEC_SSL = smtp_ssl
    SEC_STARTTLS = smtp_starttls

    def __init__(self, host, port, user, passwd, security=SEC_STARTTLS):
        self._host = host
        self._port = port
        self._user = user
        self._passwd = passwd
        self._security = security

    def send_mime_mail(self, mime_mail, tolist):
        smtp = self._security(self._host, self._port)
        if self._user is not None:
            smtp.login(self._user, self._passwd)

        mailbytes = self._mime_to_bytes(mime_mail)

        smtp.sendmail(
            mime_mail["From"],
            tolist,
            mailbytes)
        smtp.quit()


class MailConfig:
    def __init__(self,
                 mfrom,
                 sendconfig,
                 subject="[buildbot] {severity}: {project} -- {target}"):
        super().__init__()

        self._mfrom = mfrom
        self._sendconfig = sendconfig
        self._subject = subject

    def send_mail(self, lines, severity, project, target, tolist):
        mail = email.mime.multipart.MIMEMultipart()
        mail["To"] = ", ".join(tolist)
        mail["From"] = self._mfrom
        mail["Date"] = format_date_time(
            calendar.timegm(datetime.utcnow().utctimetuple()))
        mail["Subject"] = self._subject.format(
            severity=severity,
            project=project,
            target=target)

        text = """
Hello,

This is buildbot. This is a status notification for the job

    {project} / {target}

The job has the status: {severity}.

Please see the attached output log for details and take appropriate
action.""".format(
            severity=severity,
            project=project,
            target=target)

        mime_text = email.mime.text.MIMEText(
            text.encode("utf-8"), _charset="utf-8")
        mail.attach(mime_text)

        mime_log = email.mime.text.MIMEText(
            "\n".join(lines).encode("utf-8"), _charset="utf-8")
        mime_log.add_header(
            "Content-Disposition",
            "attachment",
            filename="job.log")
        mail.attach(mime_log)

        self._sendconfig.send_mime_mail(mail, tolist)

class Popen(subprocess.Popen):
    DEVNULLR = open("/dev/null", "r")

    @classmethod
    def checked(cls, call, *args, **kwargs):
        proc = cls(call, *args, **kwargs)
        result = proc.communicate()
        retval = proc.wait()
        if retval != 0:
            raise subprocess.CalledProcessError(retval, " ".join(call))
        return result

    def __init__(self, call, *args, sink_line_call=None, update_env={}, **kwargs):
        if sink_line_call is not None:
            kwargs["stdout"] = subprocess.PIPE
            kwargs["stderr"] = subprocess.PIPE
        if "stdin" not in kwargs:
            kwargs["stdin"] = self.DEVNULLR
        if update_env:
            env = os.environ
            env.update(update_env)
            kwargs["env"] = env
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
            # discard everything before the last carriage return
            line = line.split(b"\r")[-1]
            self.sink_line_call(line)
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
    initial_cwd = os.getcwd()

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
        self.cwd = os.getcwd()

    @classmethod
    def exec_respawn(cls, xmpp):
        xmpp.disconnect(reconnect=False, wait=True)
        try:
            os.chdir(cls.initial_cwd)
            os.execv(sys.argv[0], sys.argv)
        except:
            print("during execv")
            traceback.print_exc()
            raise

    def build(self, log_func):
        xmpp = self.xmpp
        for forward in self.forwards:
            log_func("Sending respawn command to {0}".format(forward.to_jid).encode())
            forward.do_forward(xmpp)

        log_func("Respawning self".encode())
        self.exec_respawn(xmpp)

    def __str__(self):
        return "respawn {}".format(self.name)

class Execute(Target):
    def __init__(self, name, *commands,
            working_directory=None,
            branch="master",
            update_env={},
            **kwargs):
        super().__init__(name, branch, **kwargs)
        self.working_directory = working_directory
        self.commands = commands
        self.update_env = update_env

    def _do_build(self, log_func):
        def checked(*args, **kwargs):
            return Popen.checked(*args, sink_line_call=log_func, **kwargs)
        for command in self.commands:
            checked(command, update_env=self.update_env)

    def build(self, log_func):
        wd = self.working_directory or os.getcwd()
        with WorkingDirectory(wd):
            self._do_build(log_func)

class Pull(Execute):
    class Mode:
        def __init__(self, remote_location, log_func):
            self.remote_location = remote_location
            self.log_func = log_func

        def checked(self, *args, **kwargs):
            return Popen.checked(*args, sink_line_call=self.log_func, **kwargs)

    class Rebase(Mode):
        def run(self):
            log_func, checked = self.log_func, self.checked

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


    class Merge(Mode):
        def run(self):
            log_func, checked = self.log_func, self.checked

            try:
                call = ["git", "pull"]
                if self.remote_location:
                    call.extend(self.remote_location)
                checked(call)
            except subprocess.CalledProcessError:
                # pull failed
                log_func("pull failed, repository remains unchanged")
                raise

    def __init__(self, name, repository_location, branch,
            after_pull_commands=[],
            remote_location=None,
            mode=Merge):
        super().__init__(name, *after_pull_commands,
            working_directory=repository_location)
        self.remote_location = remote_location
        self.branch = branch
        self.mode = mode

    def _do_build(self, log_func):
        self.mode(self.remote_location, log_func).run()
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
            pull=True,
            **kwargs):
        super().__init__(name, *commands, **kwargs)
        self.submodules = submodules
        self.working_copy = working_copy
        self.pull = pull

    def build_environment(self, log_func):
        return self.project.build_environment(
            log_func,
            self.branch,
            self.submodules,
            working_copy=self.working_copy,
            pull=self.pull
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
    def __init__(self, tmp_dir, repo_url, branch, submodules, log_func, pull=True):
        self.tmp_dir_context = None
        self.tmp_dir = tmp_dir
        self.repo_url = repo_url
        self.branch = branch
        self.submodules = submodules
        self.log_func = log_func
        self.pull = pull

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
            if self.pull:
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
            repository_url=None,
            pubsub_name=None,
            working_copy=None,
            mail_on_error=None,
            **kwargs):
        super().__init__(**kwargs)
        self.name = name
        self.repository_url = repository_url
        self.pubsub_name = pubsub_name
        self.working_copy = working_copy
        self.builds = builds
        self.mail_on_error = mail_on_error
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
                          working_copy=None,
                          **kwargs):
        return BuildEnvironment(
            working_copy or self.working_copy,
            self.repository_url,
            branch,
            submodules,
            log_func,
            **kwargs
        )

    def __str__(self):
        return self.name

class IOHandler:
    class IOCapture:
        def __init__(self, handler):
            self._handler = handler
            self._lines = []

        def _handle_line(self, line):
            self._lines.append(line)

        def __enter__(self):
            self._handler.add_line_hook(self._handle_line)
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self._handler.remove_line_hook(self._handle_line)

        @property
        def lines(self):
            return self._lines

    def __init__(self):
        self._line_hooks = []

    def add_line_hook(self, line_hook):
        self._line_hooks.append(line_hook)

    def remove_line_hook(self, line_hook):
        self._line_hooks.remove(line_hook)

    def capture(self):
        return self.IOCapture(self)

    def write_line(self, line):
        for hook in self._line_hooks:
            hook(line)

class BuildBot(HubBot):
    GIT_NODE = "git@"+HubBot.FEED
    IDLE_MESSAGE = "constructor waiting for instructions"

    config_credentials = {}

    nickname = "foo"

    def __init__(self, config_path):
        self._config_path = config_path
        self.initialized = False

        error = self.reloadConfig()
        if error:
            traceback.print_exception(*error)
            sys.exit(1)
        self.initialized = True

        credentials = self.config_credentials
        super().__init__(
            credentials["localpart"],
            credentials["resource"],
            credentials["password"]
        )
        del credentials["password"]

        nickname = credentials["nickname"]
        self.notification_to = credentials["notify"]
        self.switch, self.nick = self.addSwitch(credentials["channel"], nickname, self.build_switch)
        self.bots_switch, _ = self.addSwitch("bots", nickname)

        self.add_event_handler("pubsub_publish", self.pubsubPublish)
        self.output_handler = IOHandler()

    def _muc_output(self, line):
        self.send_message(
            mto=self.switch,
            mbody=line,
            mtype="groupchat"
        )

    def _setup_pubsub(self):
        try:
            iq = self.pubsub.get_subscriptions(self.FEED, self.GIT_NODE)
            if len(iq["pubsub"]["subscriptions"]) == 0:
                self.pubsub.subscribe(self.FEED, self.GIT_NODE, bare=True)
        except sleekxmpp.exceptions.IqError:
            # error'd
            self.send_message(
                mto=self.bots_switch,
                mbody="failed to setup pubsub link",
                mtype="groupchat"
            )
            # this is the return value for the scheduler (i.e. run
            # again)
            return True
        return False

    def sessionStart(self, event):
        super().sessionStart(event)
        if self._setup_pubsub():
            self.scheduler.add(
                "link-pubsub",
                60.0,
                self._setup_pubsub,
                repeat=True)

        self.send_message(mto=self.switch,
            mbody="",
            msubject=self.IDLE_MESSAGE,
            mtype="groupchat"
        )

    def reloadConfig(self):
        namespace = {}
        with open(self._config_path, "r") as f:
            conf = f.read()

        global_namespace = dict(globals())
        global_namespace["xmpp"] = self
        try:
            exec(conf, global_namespace, namespace)
        except Exception:
            return sys.exc_info()

        new_credentials = namespace.get("credentials", {})
        if "localpart" not in new_credentials or "password" not in new_credentials:
            raise ValueError("Both localpart and password must be present in credentials.")

        if "nickname" not in new_credentials:
            new_credentials["nickname"] = new_credentials["localpart"]

        if "resource" not in new_credentials:
            new_credentials["resource"] = "core"

        # don't respawn on new password -- it'll get updated on next connect
        # anyways
        cmp_creds_new = dict(new_credentials)
        del cmp_creds_new["password"]
        cmp_creds_old = dict(self.config_credentials)

        if cmp_creds_new != cmp_creds_old and self.initialized:
            logger.info("Respawning due to major config change")
            Respawn.exec_respawn(self)

        self.config_credentials = new_credentials

        self.authorized = set(namespace.get("authorized", []))
        self.blacklist = set()
        self.projects = dict(namespace.get("projects", []))

        # repobranch-map contains the following structure
        #
        # {(repo, branch) => {project => [builds]}}
        self.repobranch_map = {}
        for project in self.projects.values():
            for repobranch, builds in project.triggers.items():
                projectmap = self.repobranch_map.setdefault(
                    repobranch, {})
                projectmap[project] = list(builds)

        return None

    def build_switch(self, msg):
        pass

    def broadcast_error(self, msg, build, err):
        hint = "Project “{0}”, target “{1!s}” is broken, traceback logged to {2}".format(
            build.project.name,
            build,
            self.switch
        )
        self.send_message(
            mto=self.bots_switch,
            mbody="{1}: {0}".format(hint, self.notification_to),
            mtype="groupchat"
        )
        self.send_message(
            mto=self.switch,
            mbody=self.format_exception(err),
            mtype="groupchat"
        )
        print(hint)

    def mail_error(self, severity, project, build, err, output_lines):
        if project.mail_on_error is None:
            print("project doesn't have configured mail foo")
            return

        print("sending mail")
        mailconf, tolist = project.mail_on_error

        mailconf.send_mail(
            output_lines,
            severity,
            project.name,
            build.name,
            tolist)

    def rebuild_repo(self, msg, repo, branch):
        repobranch = (repo, branch)
        try:
            projects = self.repobranch_map[repobranch]
        except KeyError:
            raise

        for project, builds in projects.items():
            self.rebuild_project_subset(msg, project, builds)
        return True

    def rebuild_project_subset(self, msg, project, builds):
        try:
            for build in builds:
                with self.output_handler.capture() as capture:
                    self.rebuild(build)
        except subprocess.CalledProcessError as err:
            self.broadcast_error(msg, build, err)
            self.mail_error("failure", project, build, err, capture.lines)
            return False
        except Exception as err:
            self.broadcast_error(msg, build, err)
            self.mail_error("error", project, build, err, capture.lines)
            return False
        finally:
            self.send_message(
                mto=self.switch,
                mbody="",
                msubject=self.IDLE_MESSAGE,
                mtype="groupchat"
            )

    def pubsubPublish(self, msg):
        item = msg["pubsub_event"]["items"]["item"].xml[0]
        repo = item.findtext("{http://hub.sotecware.net/xmpp/git-post-update}repository")
        if repo is None:
            print("Malformed git-post-update.")
        ref = item.findtext("{http://hub.sotecware.net/xmpp/git-post-update}ref")
        if ref is None:
            print("Malformed git-post-update.")

        try:
            self.rebuild_repo(msg, repo, ref.split("/")[2])
        except KeyError:
            pass

    def format_exception(self, exc_info):
        return "\n".join(traceback.format_exception(*sys.exc_info()))

    def reply_exception(self, msg, exc_info):
        self.reply(msg, self.format_exception(exc_info))

    def authorizedSource(self, msg):
        origin = str(msg["from"].bare)
        if not origin in self.authorized:
            if not origin in self.blacklist:
                self.reply(msg, "You're not authorized.")
                self.blacklist.add(origin)
            return False
        return True

    def messageMUC(self, msg):
        if msg["mucnick"] == self.nick:
            return
        contents = msg["body"].strip()
        if contents == "ping":
            self.reply(msg, "pong")
            return

    def message(self, msg):
        if msg["type"] == "groupchat":
            return

        if not self.authorizedSource(msg):
            return

        contents = msg["body"]
        args = contents.split(" ", 1)
        cmd = args[0]
        args = args[1] if len(args) > 1 else ""
        handler = self.COMMANDS.get(cmd, None)
        if handler is not None:
            try:
                local = {"__func": handler, "__self": self, "__msg": msg}
                self.reply(msg, repr(eval("__func(__self, __msg, {0})".format(args), globals(), local)))
            except Exception:
                self.reply_exception(msg, sys.exc_info())
        else:
            self.reply(msg, "Unknown command: {0}".format(cmd))

    def rebuild(self, build):
        def log_func_binary(buf):
            if not isinstance(buf, str):
                buf = buf.decode(errors="replace")
            msg = buf.strip()
            if msg:
                self.output_handler.write_line(msg)
        project = build.project

        topic = "Running: {project!s} – {build!s}".format(
            project=project,
            build=build
        )
        self.send_message(mto=self.switch, mbody="", msubject=topic, mtype="groupchat")
        self.output_handler.write_line(topic)
        self.output_handler.add_line_hook(self._muc_output)
        try:
            build.build(log_func_binary)
            self.output_handler.write_line("done.")
        finally:
            self.output_handler.remove_line_hook(self._muc_output)

    def cmdRebuild(self, msg, projectName):
        project = self.projects.get(projectName, None)
        if not project:
            return "Unknown project: {0}".format(projectName)
        self.rebuild(project)
        return True

    def cmdReload(self, msg):
        result = self.reloadConfig()
        if result:
            self.reply_exception(msg, result)
        else:
            return True

    def cmdRebuildRepo(self, msg, repository, branch):
        try:
            self.rebuild_repo(msg, repository, branch)
        except KeyError:
            self.reply(msg, "Repository-branch combination not tracked: {}".format((repository, branch)))

    def cmdEcho(self, msg, *args):
        return " ".join((str(arg) for arg in args))

    COMMANDS = {
        "rebuild": cmdRebuild,
        "rebuild-repo": cmdRebuildRepo,
        "reload": cmdReload,
        "echo": cmdEcho
    }

if __name__=="__main__":
    try:
        import setproctitle
        setproctitle.setproctitle("constructor")
    except ImportError:
        pass

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c", "--config-file",
        default="buildbot_config.py",
        help="Path to the config file to use.",
        dest="config_file"
    )

    args = parser.parse_args()
    del parser

    buildbot = BuildBot(args.config_file)
    buildbot.run()

