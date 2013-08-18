import subprocess
import logging

import infomodules.utils as utils

logger = logging.getLogger("rrdsink")

class RRDToolError(Exception):
    pass

class UnknownRRDToolResponse(RRDToolError):
    pass

class RRDServer(object):
    def __init__(self):
        self._rrd = None

    def _require_rrd(self):
        if self._rrd is not None:
            retcode = self._rrd.poll()
            if retcode is None:
                # child up & running
                return self._rrd
            else:
                logger.warning("rrdtool slave disappeared: %d", retcode)
                self._rrd = None

        self._rrd = subprocess.Popen(
            ["rrdtool", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE)

        return self._rrd

    def send_command(self, cmdbytes):
        rrd = self._require_rrd()

        logging.debug("rrdtool << %s", cmdbytes.decode("ascii"))

        rrd.stdin.write(cmdbytes + b"\n")
        rrd.stdin.flush()
        response = rrd.stdout.readline().decode("ascii")
        logger.debug("rrdtool >> %s", response[3:].strip())
        if response.startswith("OK"):
            return
        elif response.startswith("ERROR"):
            raise RRDToolError(response[6:])
        else:
            raise UnknownRRDToolResponse(response)

    def update_ds_with_timestamp(self, rrdfile, ds_name, timestamp,
                                 value):
        args = ["update", rrdfile,
                "--template", ds_name,
                "{!s}:{}".format(utils.to_timestamp(timestamp), value),
               ]
        self.send_command(" ".join(args).encode("ascii"))

    def update_with_timestamps(self,
            rrdfile,
            data):
        args = ["update", rrdfile, "--template"]
        args.append(":".join(ds_name for ds_name, _, _ in data))
        args.append("--")

        for _, timestamp, value in data:
            this_arg = "N" if timestamp is None else \
                           str(utils.to_timestamp(timestamp))

            this_arg += ":{}".format(value)
            args.append(this_arg)

        self.send_command(" ".join(args).encode("ascii"))
