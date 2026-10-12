"""One AWS shadow connection, with no automatic reuse of signed WSS URLs."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
import secrets

import paho.mqtt.client as mqtt

from .airmatters import AirCloudError, CloudConnection


class AirCloudMQTT:
    def __init__(self, connection: CloudConnection, on_state: Callable[[dict], None],
                 on_disconnect: Callable[[], None], *, client_factory=mqtt.Client):
        self._connection = connection
        self._on_state = on_state
        self._on_disconnect = on_disconnect
        self._loop = asyncio.get_running_loop()
        self._closed = False
        self.connected = False
        self._reported: dict = {}
        self._version = -1
        self._pending: dict[str, tuple[str, asyncio.Future]] = {}
        self._ready = self._loop.create_future()
        self._client = client_factory(mqtt.CallbackAPIVersion.VERSION2,
            client_id=connection.client_id, transport="websockets", reconnect_on_failure=False)
        self._client.connect_timeout = 12
        self._client.tls_set()
        self._client.ws_set_options(path=connection.path)
        self._client.on_connect = self._connected_callback
        self._client.on_subscribe = self._subscribed_callback
        self._client.on_disconnect = self._disconnected_callback
        self._client.on_message = self._message_callback
        self._prefix = f"$aws/things/{connection.device_id}/shadow"
        self._subscribe_id: int | None = None

    def _dispatch(self, callback, *args):
        if not self._closed and not self._loop.is_closed():
            try:
                self._loop.call_soon_threadsafe(callback, *args)
            except RuntimeError:
                # HA may finish stopping between is_closed and scheduling.
                pass

    def _connected_callback(self, client, _userdata, _flags, reason, _properties):
        if reason.is_failure:
            self._dispatch(self._fail, "MQTT authentication rejected")
            return
        topics = [(self._prefix + suffix, 1) for suffix in
                  ("/get/accepted", "/get/rejected", "/update/documents",
                   "/update/accepted", "/update/rejected")]
        rc, self._subscribe_id = client.subscribe(topics)
        if rc != mqtt.MQTT_ERR_SUCCESS:
            self._dispatch(self._fail, "Shadow subscription failed")

    def _subscribed_callback(self, _client, _userdata, mid, reasons, _properties):
        if mid != self._subscribe_id:
            return
        if any(reason.is_failure for reason in reasons):
            self._dispatch(self._fail, "Shadow subscription rejected")
        else:
            self._dispatch(self._set_ready)

    def _set_ready(self):
        if self._closed:
            return
        self.connected = True
        if not self._ready.done():
            self._ready.set_result(None)

    def _disconnected_callback(self, _client, _userdata, _flags, _reason, _properties):
        self._dispatch(self._handle_disconnect)

    def _handle_disconnect(self):
        self.connected = False
        self._fail("Cloud MQTT connection lost")
        if not self._closed:
            self._on_disconnect()

    def _fail(self, message: str):
        if not self._ready.done():
            self._ready.set_exception(AirCloudError(message))
        for _, future in self._pending.values():
            if not future.done():
                future.set_exception(AirCloudError(message))

    def _message_callback(self, _client, _userdata, message):
        if len(message.payload) > 262144:
            return
        try:
            payload = json.loads(message.payload)
        except (ValueError, UnicodeError):
            return
        if isinstance(payload, dict):
            self._dispatch(self._handle_message, message.topic, payload)

    def _handle_message(self, topic: str, payload: dict):
        if self._closed:
            return
        prefix = self._prefix
        if topic not in {prefix + suffix for suffix in
                        ("/get/accepted", "/get/rejected", "/update/documents",
                         "/update/accepted", "/update/rejected")}:
            return
        token = payload.get("clientToken")
        pending = self._pending.get(token) if isinstance(token, str) else None
        if pending and topic == prefix + "/" + pending[0] + "/rejected":
            if not pending[1].done():
                pending[1].set_exception(AirCloudError("Shadow request rejected"))
            return
        if topic.endswith("/rejected"):
            return
        document = payload.get("current") if topic.endswith("/documents") else payload
        if not isinstance(document, dict):
            return
        state = document.get("state")
        reported = state.get("reported") if isinstance(state, dict) else None
        version = document.get("version")
        if isinstance(reported, dict) and isinstance(version, int) and not isinstance(version, bool) and version >= self._version:
            full = topic in (prefix + "/get/accepted", prefix + "/update/documents")
            if full:
                self._reported = {key: value for key, value in reported.items() if value is not None}
            else:
                self._reported = {**self._reported, **reported}
                self._reported = {key: value for key, value in self._reported.items() if value is not None}
            self._version = version
            self._on_state(dict(self._reported))
        # A desired-only acceptance acknowledges the command, not physical state.
        if pending and topic == prefix + "/" + pending[0] + "/accepted":
            if pending[0] == "get" and not isinstance(reported, dict):
                if not pending[1].done():
                    pending[1].set_exception(AirCloudError("Shadow reported state missing"))
            elif not pending[1].done():
                pending[1].set_result(dict(self._reported))

    async def connect(self):
        try:
            await asyncio.to_thread(self._client.connect, self._connection.host, 443, 60)
            self._client.loop_start()
            await asyncio.wait_for(asyncio.shield(self._ready), 20)
        except asyncio.CancelledError:
            await self.close()
            raise
        except Exception:
            await self.close()
            raise AirCloudError("Cloud MQTT connection failed") from None

    async def _request(self, action: str, state=None) -> dict:
        if not self.connected or self._closed:
            raise AirCloudError("Cloud MQTT is disconnected")
        token = secrets.token_hex(12)
        future = self._loop.create_future()
        self._pending[token] = (action, future)
        payload = {"clientToken": token}
        if state is not None:
            payload["state"] = {"desired": state}
        try:
            result = self._client.publish(self._prefix + "/" + action,
                json.dumps(payload, separators=(",", ":")), qos=1, retain=False)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                raise AirCloudError("Shadow publish failed")
            return await asyncio.wait_for(future, 20)
        except TimeoutError:
            raise AirCloudError("Shadow request timed out") from None
        finally:
            self._pending.pop(token, None)
            if not future.done():
                future.cancel()

    async def read(self) -> dict:
        return await self._request("get")

    async def update(self, desired: dict) -> dict:
        # Restrict writable fields to the observed purifier's power and mode.
        if not desired or set(desired) - {"D03102", "D0310C"}:
            raise AirCloudError("Unverified purifier command")
        if "D03102" in desired and (type(desired["D03102"]) is not int or desired["D03102"] not in (0, 1)):
            raise AirCloudError("Invalid power command")
        if "D0310C" in desired and (type(desired["D0310C"]) is not int or desired["D0310C"] not in (0, 1, 2, 3, 4, 5, 17, 18, 19)):
            raise AirCloudError("Invalid mode command")
        return await self._request("update", desired)

    async def close(self):
        if self._closed:
            return
        self._closed = True
        self.connected = False
        if not self._ready.done():
            self._ready.cancel()
        for _, future in self._pending.values():
            if not future.done():
                future.cancel()
        await asyncio.to_thread(self._client.disconnect)
        await asyncio.to_thread(self._client.loop_stop)
