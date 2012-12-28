#!/usr/bin/python2
import sympy
import socket
import io
import sympy.physics.units as u
import sympy.core.sympify

import SympyComm

if __name__ == "__main__":
    import sys
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "fd",
        type=int,
        help="File descriptor to listen for expressions on"
    )

    args = parser.parse_args()

    sock = socket.fromfd(args.fd, socket.AF_UNIX, socket.SOCK_STREAM)

    u.i = sympy.sqrt(-1)
    while True:
        unit, expr = SympyComm.recv_calc(sock)
        try:
            unit = sympy.sympify(unit, locals=u.__dict__)
        except Exception as err:
            SympyComm.send_error(sock, "could not sympify unit: {}".format(str(err)).encode("utf-8"))
            continue
        try:
            expr = sympy.sympify(expr, locals=u.__dict__)
        except Exception as err:
            SympyComm.send_error(sock, "could not sympify expression: {}".format(str(err)).encode("utf-8"))
            continue

        try:
            result = expr / unit
        except Exception as err:
            SympyComm.send_error(sock, b"during evaluation: "+str(err).encode("utf-8"))
        try:
            SympyComm.send_result(sock, str(float(result / unit)).encode("ascii"))
        except ValueError as err:
            SympyComm.send_result(sock, str(result).encode("ascii"))
        except Exception as err:
            SympyComm.send_error(sock, str(err).encode("utf-8"))

