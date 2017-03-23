import logging

import foomodules.Base as Base

logger = logging.getLogger(__name__)
xmlns = "http://hub.sotecware.net/xmpp/git-post-update"

class GitLog(Base.XMPPObject):
    REPOSITORY_NODE = "{{{0}}}repository".format(xmlns)
    REF_NODE = "{{{0}}}ref".format(xmlns)

    def __init__(self, pubsub_node, pubsub_host=None, hooks={}, **kwargs):
        super().__init__(**kwargs)
        self.pubsub_node = pubsub_node
        if not pubsub_host:
            self.pubsub_host = self.pubsub_node.split("@")[1]
        else:
            self.pubsub_host = pubsub_host
        self.hooks = dict(hooks)

    def _subscribe(self, xmpp):
        iq = xmpp.pubsub.get_subscriptions(self.pubsub_host, self.pubsub_node)
        if len(iq["pubsub"]["subscriptions"]) == 0:
            xmpp.pubsub.subscribe(self.pubsub_host, self.pubsub_node, bare=True)

    def _unsubscribe(self, xmpp):
        iq = xmpp.pubsub.get_subscriptions(self.pubsub_host, self.pubsub_node)
        for item in list(iq["pubsub"]["subscriptions"]):
            if item["node"] == self.pubsub_node:
                if item["subscription"] == 'unsubscribed':
                    return
                else:
                    break
        xmpp.pubsub.unsubscribe(self.pubsub_host, self.pubsub_node)

    def _xmpp_changed(self, old, new):
        super()._xmpp_changed(old, new)
        if old is not None:
            old.del_event_handler("pubsub_publish", self.pubsub_publish)
        if new is not None:
            new.add_event_handler("pubsub_publish", self.pubsub_publish)
            self._subscribe(new)

        for hook in self.hooks.values():
            hook.XMPP = new

    def pubsub_publish(self, node):
        item = node["pubsub_event"]["items"]["item"].xml[0]
        repo = item.findtext(self.REPOSITORY_NODE)
        if repo is None:
            logging.warn("Malformed git update: missing repository node")
        ref = item.findtext(self.REF_NODE)
        if ref is None:
            logging.warn("Malformed git update: missing ref node")

        repobranch = (repo, ref.split("/", 2)[-1])

        for key in (repobranch, (repo, None), None):
            try:
                hook = self.hooks[key]
            except KeyError:
                continue
            if hook(item, *repobranch):
                break

class CommitIgnore(Base.XMPPObject):
    def __call__(self, item, repo, branch):
        return True

class CommitNotify(Base.XMPPObject):
    HEADLINE_NODE = "{{{0}}}headline".format(xmlns)
    AUTHOR_NODE = "{{{0}}}author".format(xmlns)
    NEW_REF_NODE = "{{{0}}}new-ref".format(xmlns)

    DEFAULT_FORMAT = "{repo}:{branch} is now at {shortsha} (by {shortauthor}): {headline}"
    DEFAULT_DELETED_FORMAT = "{repo}/{branch} has been deleted"

    def __init__(self,
                 to_jids=[],
                 fmt=DEFAULT_FORMAT,
                 delfmt=DEFAULT_DELETED_FORMAT,
                 skip_others=False,
                 **kwargs):
        super().__init__(**kwargs)
        self.to_jids = list(to_jids)
        self.fmt = fmt
        self.delfmt = delfmt
        self.skip_others = skip_others

    def __call__(self, item, repo, branch):
        new_ref = item.find(self.NEW_REF_NODE)

        if new_ref is None:
            msg = self.delfmt.format(
                repo=repo,
                branch=branch)
        else:
            author = new_ref.findtext(self.AUTHOR_NODE)
            if author is not None:
                try:
                    words = author.split("<", 1)[0].strip().split(" ")
                except (ValueError, IndexError) as err:
                    shortauthor = "noshort"
                else:
                    shortauthor = "".join((word[0].upper() for word in words[:-1]))
                    shortauthor += words[-1][:2].upper()
            else:
                shortauthor = "unknown"

            sha = new_ref.get("sha")
            msg = self.fmt.format(
                repo=repo,
                branch=branch,
                headline=new_ref.findtext(self.HEADLINE_NODE),
                author="unknown author(!)",
                sha=sha,
                shortsha=sha[:8],
                shortauthor=shortauthor
            )

        for jid in self.to_jids:
            if not isinstance(jid, str) and hasattr(jid, "__iter__"):
                jid, mtype = jid
            else:
                mtype = "chat"
            self.XMPP.send_message(mto=jid, mbody=msg, mtype=mtype)

        return self.skip_others
