"""All tests are offline, including the recorded-feed and HTTP adapter tests."""

import socket

import pytest


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Network access is forbidden in tests")

    real_connect = socket.socket.connect
    real_socketpair = socket.socketpair

    def local_socketpair(*args, **kwargs):
        # asyncio's event loop needs a self-pipe; on Windows socket.socketpair()
        # emulates it by connecting to a loopback listener it has just bound.
        socket.socket.connect = real_connect
        try:
            return real_socketpair(*args, **kwargs)
        finally:
            socket.socket.connect = blocked

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "socketpair", local_socketpair)
