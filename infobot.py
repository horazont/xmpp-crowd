#!/usr/bin/python3
from hub import HubBot

class InfoBot(HubBot):
    def __init__(self, config_file):
        self._config_file = config_file
        self.initialized = False

        error = self.reload_config()
        if error:
            traceback.print_exception(*error)
            sys.exit(1)

        self.initialized = True
        credentials = self.config_credentials

        super().__init__(
            credentials["localpart"],
            credentials.get("resource", "core"),
            credentials["password"]
            )
        del credentials["password"]

        nickname = credentials.get("nickname", credentials["localpart"])
        self.bots_switch, self.nick = self.addSwitch("bots", nickname)
        self.add_event_handler("presence", self.handle_presence)

    def reload_config(self):
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
        self.config_credentials = new_credentials
        self.departure_getter = namespace.get("departure", None)
        self.metno_url = namespace.get("metno_url", None)
        self._weather_document = None
        self._weather_last_modified = None
        self._weather = None
        self._sensors = {}
        #sys.exit(1)
        self._lcd_away = False

        return None
