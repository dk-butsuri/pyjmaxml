import asyncio
import socket

import pytest


def test_outbound_connections_and_dns_are_blocked():
    with pytest.raises(AssertionError, match="forbidden"):
        socket.create_connection(("www.data.jma.go.jp", 443))
    with pytest.raises(AssertionError, match="forbidden"):
        socket.getaddrinfo("www.data.jma.go.jp", 443)
    with socket.socket() as sock, pytest.raises(AssertionError, match="forbidden"):
        sock.connect(("127.0.0.1", 9))


def test_socketpair_for_event_loops_is_allowed_and_guard_is_restored():
    left, right = socket.socketpair()
    with left, right:
        left.sendall(b"x")
        assert right.recv(1) == b"x"
    with socket.socket() as sock, pytest.raises(AssertionError, match="forbidden"):
        sock.connect(("127.0.0.1", 9))
    assert asyncio.run(asyncio.sleep(0, result="ok")) == "ok"
