from __future__ import unicode_literals
import socket
import struct

CALC_HEADER = struct.Struct(b"!LL")
RESULT_HEADER = struct.Struct(b"!?L")

def force_recv(sock, length):
    buf = sock.recv(length)
    while len(buf) < length:
        buf += sock.recv(length - len(buf))
    return buf

def force_send(sock, data):
    if sock.send(data) < len(data):
        raise ValueError("Failed to send all data")

def recv_calc(sock):
    header = force_recv(sock, CALC_HEADER.size)
    unitlen, exprlen = CALC_HEADER.unpack(header)
    unit = force_recv(sock, unitlen)
    expr = force_recv(sock, exprlen)

    return unit, expr

def recv_result(sock):
    header = force_recv(sock, RESULT_HEADER.size)
    state, textlen = RESULT_HEADER.unpack(header)
    text = force_recv(sock, textlen)
    return state, text

def send_result(sock, result):
    header = RESULT_HEADER.pack(True, len(result))
    force_send(sock, header)
    force_send(sock, result)

def send_error(sock, error_message):
    header = RESULT_HEADER.pack(False, len(error_message))
    force_send(sock, header)
    force_send(sock, error_message)

def send_calc(sock, unit, expr):
    header = CALC_HEADER.pack(len(unit), len(expr))
    force_send(sock, header)
    force_send(sock, unit)
    force_send(sock, expr)

