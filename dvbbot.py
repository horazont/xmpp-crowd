#!/usr/bin/python3
from hub import HubBot
import ast, urllib.request, re
from datetime import datetime

class DVBBot(HubBot):
    LOCALPART = "dvbbot"
    PASSWORD = ""
    STOP = "" # your value here
    DEPARTURE_URL = "http://widgets.vvo-online.de/abfahrtsmonitor/Abfahrten.do?ort=Dresden&hst={0}".format(STOP)

    BRACES_RE = re.compile("\(.*?\)")

    LCD_CODING = {
        228: 0b11100001,
        246: 0b11101111,
        252: 0b11110101,
        223: 0b11100010
    }
    
    def __init__(self):
        super(DVBBot, self).__init__(self.LOCALPART, "core", self.PASSWORD)
        self.switch, self.nick = self.addSwitch("bots", "dvbbot")
        self.buffers = None
        self.currBuffer = -1

    def _getNextDepartures(self):
        f = urllib.request.urlopen(self.DEPARTURE_URL)
        contents = f.read().decode()
        f.close()
        return ast.literal_eval(contents)

    def _stripDest(self, dest):
        m = self.BRACES_RE.search(dest)
        if m:
            dest = dest[:m.start()] + dest[m.end():]
        return dest[:14]

    def _lcdOrd(self, v):
        return self.LCD_CODING.get(v, v)

    def _hexBuffer(self, buf):
        return "".join("{0:02x}".format(self._lcdOrd(ord(c))) for c in buf)

    def _dataToBuffer(self, data):
        assert len(data) <= 4
        buf = ""
        for lane, dest, remaining in data:
            if len(dest) > 14:
                dest = self._stripDest(dest)
            buf += "{0:2s} {1:14s} {2:2s}".format(lane, dest, remaining)
        return self._hexBuffer(buf)

    def _infoBuffer(self):
        now = datetime.utcnow()
        date = now.strftime("%a, %d. %b %Y")
        time = now.strftime("%H:%M")
        return self._hexBuffer("{0:20s}{1:20s}".format(date, time))

    def sessionStart(self, event):
        super(DVBBot, self).sessionStart(event)
        self.scheduler.add(
            "update",
            60.0,
            self.update,
            repeat=True
        )
        self.update()
        self.scheduler.add(
            "flip",
            10.0,
            self.flip,
            repeat=True
        )

    def flip(self):
        buffers, currBuffer = self.buffers, self.currBuffer + 1
        if buffers is None:
            self.writeLCD("clear")
            self.writeLCD("echo No data available.")
            return

        if len(buffers) <= currBuffer:
            buf = self._infoBuffer()
            currBuffer = -1
        else:
            buf = buffers[currBuffer]

        self.writeLCD("clear")
        self.writeLCD("hex "+buf)
        self.currBuffer = currBuffer

    def writeLCD(self, raw):
        self.send_message(mto="lcd@hub.sotecware.net", mbody=raw, mtype="chat")

    def messageMUC(self, msg):
        if msg["mucnick"] == self.nick:
            return
        contents = msg["body"].strip()
        if contents == "ping":
            self.reply(msg, "pong")
            return

    def update(self):
        data = self._getNextDepartures()[:8]  # we can take a max of 8 entries
        buffers = []
        while len(data) > 0:
            buffers.append(self._dataToBuffer(data[:4]))
            data = data[4:]
        self.buffers = buffers
        

    COMMANDS = {
    }

if __name__=="__main__":
    docbot = DVBBot()
    docbot.run()
    
