"""Real Paho lifecycle regression against an isolated loopback MQTT fixture.

The fixture substitutes TCP for cloud WSS/TLS; it tests thread ownership and
cleanup, not Philips authentication, AWS behavior or purifier firmware.
"""
import asyncio
import socket
import threading
from unittest.mock import Mock

import pytest
from custom_components.philips_airplus import mqtt_client as mod


def read_exact(conn, n):
    data = b''
    while len(data) < n:
        part = conn.recv(n - len(data))
        if not part:
            raise EOFError
        data += part
    return data


def read_packet(conn):
    header = read_exact(conn, 1)[0]
    size = 0
    multiplier = 1
    while True:
        digit = read_exact(conn, 1)[0]
        size += (digit & 127) * multiplier
        if not digit & 128:
            return header >> 4, read_exact(conn, size)
        multiplier *= 128


class LoopbackBroker:
    def __init__(self):
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(16)
        self.listener.settimeout(0.05)
        self.port = self.listener.getsockname()[1]
        self.stop = threading.Event()
        self.peers = []
        self.threads = []
        self.thread = threading.Thread(target=self.accept, daemon=True)

    def accept(self):
        while not self.stop.is_set():
            try:
                conn, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            self.peers.append(conn)
            worker = threading.Thread(target=self.serve, args=(conn,), daemon=True)
            self.threads.append(worker)
            worker.start()

    def serve(self, conn):
        try:
            while not self.stop.is_set():
                kind, body = read_packet(conn)
                if kind == 1:
                    conn.sendall(b'\x20\x02\x00\x00')
                elif kind == 8:
                    conn.sendall(b'\x90\x03' + body[:2] + b'\x00')
                elif kind == 12:
                    conn.sendall(b'\xd0\x00')
                elif kind == 14:
                    return
        except (EOFError, OSError):
            pass
        finally:
            conn.close()

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.listener.close()
        self.thread.join(2)
        for conn in self.peers:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        for worker in self.threads:
            worker.join(2)
        assert not self.thread.is_alive()
        assert not any(worker.is_alive() for worker in self.threads)


@pytest.mark.asyncio
@pytest.mark.filterwarnings('ignore:Callback API version 1 is deprecated:DeprecationWarning')
async def test_real_paho_reloads_and_concurrent_token_refresh_leave_no_old_threads(monkeypatch):
    real_client = mod.mqtt.Client
    clients, network_threads, retry_options = [], [], []
    def factory(*args, **kwargs):
        retry_options.append(kwargs.get('reconnect_on_failure'))
        kwargs['transport'] = 'tcp'
        client = real_client(*args, **kwargs)
        client.tls_set = Mock()
        client.ws_set_options = Mock()
        start = client.loop_start
        def record_start():
            result = start()
            network_threads.append(client._thread)
            return result
        client.loop_start = record_start
        clients.append(client)
        return client

    with LoopbackBroker() as broker:
        monkeypatch.setattr(mod, 'MQTT_HOST', '127.0.0.1')
        monkeypatch.setattr(mod, 'MQTT_PORT', broker.port)
        monkeypatch.setattr(mod.mqtt, 'Client', factory)
        for reload in range(3):
            owner = mod.PhilipsAirplusMQTTClient('synthetic', 'synthetic-token', 'synthetic-signature', client_id='synthetic_ha')
            messages = Mock()
            owner.set_message_callback(messages)
            try:
                assert await owner.async_connect()
                assert all(await asyncio.gather(
                    owner.async_update_credentials('synthetic-a', 'sig-a'),
                    owner.async_update_credentials('synthetic-b', 'sig-b')))
                # Both refresh operations must join the old thread first.
                assert sum(t.is_alive() for t in network_threads) == 1
            finally:
                await owner.async_shutdown()
            assert not any(t.is_alive() for t in network_threads)
            assert not owner.is_connected()
            for stale in clients:
                owner._on_connect(stale, None, {}, 0)
                owner._on_disconnect(stale, None, 7)
            assert not owner.is_connected()
        assert len(clients) == 9
        assert retry_options == [False] * 9
