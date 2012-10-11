from sleekxmpp import ClientXMPP

class HubBot(ClientXMPP):
    HUB = "hub.sotecware.net"
    SWITCH = "switch.hub.sotecware.net"
    FEED = "feed.hub.sotecware.net"

    def __init__(self, localpart, resource, password):
        jid = "{0}@{1}".format(localpart, self.HUB)
        if resource:
            jid += "/" + resource
        super().__init__(jid, password)

        self.register_plugin("xep_0004")  # dataforms
        self.register_plugin("xep_0045")  # muc
        self.register_plugin("xep_0060")  # pubsub -- let the fun begin

        self.add_event_handler("session_start", self.sessionStart)
        self.add_event_handler("session_end", self.sessionEnd)
        self.add_event_handler("groupchat_message", self.messageMUC)
        self.add_event_handler("message", self.message)

        self.muc = None
        self.pubsub = None
        self.dataforms = self.plugin["xep_0004"]

        self._switchHandlers = {}

        self._switches = []

    def _getSwitchJID(self, switch):
        return "{0}@{1}".format(switch, self.SWITCH)

    def _joinSwitch(self, switchTuple, wait=False):
        print("joining {0} as {1}".format(*switchTuple))
        self.muc.joinMUC(*switchTuple, wait=wait)

    def sessionStart(self, event):
        self.send_presence()
        self.get_roster()

        self.muc = self.plugin["xep_0045"]
        self.pubsub = self.plugin["xep_0060"]

        for switchTuple in self._switches:
            self._joinSwitch(switchTuple)

    def sessionEnd(self, event):
        pass

    def addSwitch(self, switch, nick, handler=None):
        if handler is not None:
            self.addSwitchHandler(switch, handler)
        switchTuple = (self._getSwitchJID(switch), nick)
        self._switches.append(switchTuple)
        if self.muc is not None:
            self._joinSwitch(switchTuple)
        return switchTuple

    def addSwitchHandler(self, room, handler):
        self._switchHandlers.setdefault(self._getSwitchJID(room), []).append(handler)

    def messageMUC(self, msg):
        muc = str(msg["from"].bare)
        handlers = self._switchHandlers.get(muc, [])
        for handler in handlers:
            handler(msg)

    def message(self, msg):
        pass

    def reply(self, msg, body):
        if msg["type"] == "groupchat":
            self.send_message(mtype="groupchat", mto=msg["from"].bare, mbody=body)
        else:
            self.send_message(mto=msg["from"], mbody=body)

    def run(self):
        self.connect()
        self.process(block=True)
