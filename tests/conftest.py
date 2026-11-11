"""All tests are offline, including the recorded-feed and HTTP adapter tests."""

import socket

import pytest


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Network access is forbidden in tests")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
