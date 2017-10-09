#!/usr/bin/python3
import asyncio
import functools
import logging
import runpy
import signal

import aioxmpp.muc
import aioxmpp.node
import aioxmpp.security_layer


init_globals = {
    "certificate_verifier_factory":
    aioxmpp.security_layer.PKIXCertificateVerifier,
    "components": [],
}


class Main:
    def __init__(self, loop, args):
        super().__init__()
        self._loop = loop
        self._logger = logging.getLogger("main")

        self._config = runpy.run_path(
            args.config_file,
            init_globals=init_globals
        )

        self._client = aioxmpp.node.PresenceManagedClient(
            jid=self._config["jid"],
            security_layer=aioxmpp.make_security_layer(
                self._config["password"],
                pin_store=self._config.get("pin_store", None),
                pin_type=self._config.get(
                    "pin_type",
                    aioxmpp.security_layer.PinType.CERTIFICATE
                ),
            ),
        )
        self._muc = self._client.summon(aioxmpp.muc.Service)

    @property
    def client(self):
        return self._client

    async def main(self):
        ""
        interrupt = asyncio.Event()
        self._loop.add_signal_handler(
            signal.SIGTERM,
            interrupt.set
        )

        self._loop.add_signal_handler(
            signal.SIGINT,
            interrupt.set
        )

        futures = []
        for component in self._config["components"]:
            futures.append(asyncio.ensure_future(component.setup(self)))

        async with self._client.connected():
            await asyncio.gather(*futures)
            self._logger.info("setup complete")

            await interrupt.wait()

            futures = []
            for component in self._config["components"]:
                futures.append(asyncio.ensure_future(
                    component.teardown()
                ))

            await asyncio.gather(*futures)
            self._logger.info("shutdown complete")

    def run(self):
        self._loop.run_until_complete(self.main())


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c", "--config-file",
        metavar="PYFILE",
        default="foorl_config.py",
        help="Path to a .py which is used to configure foorl. "
        "(default: foorl_config.py)"
    )

    parser.add_argument(
        "-v", "--verbose",
        dest="verbosity",
        action="count",
        default=0,
        help="Incresae verbosity (up to -vvv)"
    )

    args = parser.parse_args()

    logging.basicConfig(
        level={
            0: logging.ERROR,
            1: logging.WARNING,
            2: logging.INFO,
        }.get(args.verbosity, logging.DEBUG),
    )

    loop = asyncio.get_event_loop()
    main = Main(loop, args)
    try:
        main.run()
    finally:
        loop.close()
