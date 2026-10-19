"""MQTT client for Philips Air+ integration."""
from __future__ import annotations

import json
import logging
import random
import secrets
import string
import time
import asyncio
import ssl
import threading
from datetime import datetime
from typing import Any, Callable, Dict, Optional

import paho.mqtt.client as mqtt
from paho.mqtt.client import MQTTMessage

from .const import (
    KEEPALIVE,
    MQTT_HOST,
    MQTT_PATH,
    MQTT_PORT,
    PORT_CONTROL,
    PORT_FILTER_READ,
    PORT_FILTER_WRITE,
    PORT_STATUS,
    TOPIC_CONTROL_TEMPLATE,
    TOPIC_STATUS_TEMPLATE,
)

_LOGGER = logging.getLogger(__name__)


class PhilipsAirplusMQTTClient:
    """MQTT client for Philips Air+ communication."""

    def __init__(
        self,
        device_id: str,
        access_token: str,
        signature: str,
        client_id: Optional[str] = None,
        custom_authorizer_name: str = "CustomAuthorizer",
    ) -> None:
        """Initialize MQTT client."""
        self.device_id = device_id
        if not self.device_id.startswith('da-'):
            self.device_id = f"da-{self.device_id}"
        self.access_token = access_token
        self.signature = signature
        self.client_id = client_id or f"ha-{device_id}"
        self.custom_authorizer_name = custom_authorizer_name
        
        self._client: Optional[mqtt.Client] = None
        self._connected = False
        self._connecting = False
        self._last_disconnect_time: float = 0.0
        self._last_disconnect_rc: int = 0
        self._reconnect_attempts: int = 0
        self._reconnect_base: float = 1.0
        self._reconnect_max_backoff: float = 300.0
        self._rc7_cooldown: float = 120.0
        self._lock = threading.RLock()
        # Never hold the state lock while joining the Paho thread. Serialize
        # connect/teardown separately, so a replacement cannot overtake cleanup.
        self._operation_lock = threading.Lock()
        self._shutdown_event = threading.Event()
        self._connect_event = threading.Event()
        self._retired_client: Optional[mqtt.Client] = None
        self._credentials_lock = asyncio.Lock()
        self._instance = secrets.token_hex(4)
        self._generation = 0
        self._message_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self._connection_callback: Optional[Callable[[bool], None]] = None
        self._refreshing_credentials: bool = False  # Flag to maintain availability during credential refresh
        self._shutting_down: bool = False  # Suppress callbacks during shutdown
        
        self.outbound_topic = TOPIC_CONTROL_TEMPLATE.format(device_id=self.device_id)
        self.inbound_topic = TOPIC_STATUS_TEMPLATE.format(device_id=self.device_id)

        # Port names (defaults from const.py, overridable per model via configure_ports())
        self._port_status = PORT_STATUS
        self._port_control = PORT_CONTROL
        self._port_filter_read = PORT_FILTER_READ
        self._port_filter_write = PORT_FILTER_WRITE

    def configure_ports(self, ports: Dict[str, str]) -> None:
        """Update port names from model config."""
        self._port_status = ports.get("status", PORT_STATUS)
        self._port_control = ports.get("control", PORT_CONTROL)
        self._port_filter_read = ports.get("filter_read", PORT_FILTER_READ)
        self._port_filter_write = ports.get("filter_write", PORT_FILTER_WRITE)

    def set_message_callback(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Set callback for incoming messages."""
        self._message_callback = callback

    def set_connection_callback(self, callback: Callable[[bool], None]) -> None:
        """Set callback for connection status changes."""
        self._connection_callback = callback

    def _build_headers(self) -> Dict[str, str]:
        """Build WebSocket headers for authentication."""
        return {
            'x-amz-customauthorizer-name': self.custom_authorizer_name,
            'x-amz-customauthorizer-signature': self.signature,
            'tenant': 'da',
            'content-type': 'application/json',
            'token-header': f'Bearer {self.access_token.strip()}',
            'Sec-WebSocket-Protocol': 'mqtt',
        }

    def _is_current(self, client: mqtt.Client) -> bool:
        """Call with the state lock held."""
        return not self._shutting_down and client is self._client

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Dict[str, Any], rc: int) -> None:
        """Only the currently owned transport may change connection state."""
        with self._lock:
            if not self._is_current(client):
                return
            self._connected = rc == 0
            if self._connected:
                self._reconnect_attempts = 0
                self._last_disconnect_rc = 0
                self._last_disconnect_time = 0.0
                client.subscribe(self.inbound_topic, qos=0)
            _LOGGER.info("MQTT instance=%s generation=%d connected rc=%s",
                         self._instance, self._generation, rc)
            self._connect_event.set()
            if self._connection_callback:
                self._connection_callback(self._connected)

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: MQTTMessage) -> None:
        """Handle incoming MQTT messages.

        The AWS IoT broker may deliver multiple JSON payloads concatenated
        in a single WebSocket frame.  Use raw_decode to process every
        object in sequence instead of dropping the entire batch.
        """
        with self._lock:
            if not self._is_current(client):
                return
        try:
            payload = msg.payload.decode('utf-8')
            decoder = json.JSONDecoder()
            idx = 0
            while idx < len(payload):
                # Skip leading whitespace between objects
                while idx < len(payload) and payload[idx] in ' \t\n\r':
                    idx += 1
                if idx >= len(payload):
                    break
                try:
                    message_data, end = decoder.raw_decode(payload, idx)
                except json.JSONDecodeError:
                    # Single-object fallback for the common case
                    message_data = json.loads(payload[idx:])
                    end = len(payload)

                _LOGGER.debug("Received message: %s", message_data)

                with self._lock:
                    if not self._is_current(client):
                        return
                    if self._message_callback:
                        self._message_callback(message_data)

                idx = end

        except json.JSONDecodeError as ex:
            _LOGGER.error("Failed to decode MQTT message: %s", ex)
        except Exception as ex:
            _LOGGER.error("Error processing MQTT message: %s", ex)

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, rc: int) -> None:
        """Stop Paho retries; the coordinator alone owns reconnection."""
        with self._lock:
            if not self._is_current(client):
                return
            self._connected = False
            self._connect_event.set()
            if rc != 0:
                self._reconnect_attempts = min(self._reconnect_attempts + 1, 32)
                self._last_disconnect_time = time.time()
                self._last_disconnect_rc = rc
            _LOGGER.warning("MQTT instance=%s generation=%d disconnected rc=%s",
                            self._instance, self._generation, rc)
        # In Paho's thread loop_stop sets its termination flag without joining
        # itself. Retain ownership until the next teardown joins that thread.
        try:
            client.disconnect()
        except Exception:
            _LOGGER.debug("MQTT disconnect cleanup failed")
        try:
            client.loop_stop()
        except Exception:
            _LOGGER.debug("MQTT loop cleanup deferred to teardown")
        with self._lock:
            if (self._is_current(client) and self._connection_callback
                    and not self._refreshing_credentials):
                self._connection_callback(False)

    def _stop_current_client(self) -> None:
        """Detach callbacks first, then join outside the state lock.

        Requires _operation_lock. Retain a failed cleanup for a subsequent
        attempt rather than lose its reference and create a competing client.
        """
        with self._lock:
            client = self._retired_client or self._client
            self._client = None
            self._connected = False
            self._retired_client = client
        if client is None:
            return
        try:
            client.disconnect()
        except Exception:
            _LOGGER.debug("MQTT disconnect failed; still stopping network loop")
        # A failure to stop is deliberately propagated: never start a second
        # transport while the previous network loop might still be alive.
        client.loop_stop()
        self._retired_client = None
        _LOGGER.debug("MQTT instance=%s generation=%d transport stopped",
                      self._instance, self._generation)

    def _blocking_connect(self, timeout: float = 15.0) -> bool:
        """Connect exactly one transport; shutdown interrupts backoff/waiting."""
        with self._lock:
            if self._shutting_down or self._connecting:
                return False
            if self._connected:
                return True
            self._connecting = True
        try:
            with self._operation_lock:
                try:
                    self._stop_current_client()
                    if self._shutdown_event.is_set():
                        return False
                    if self._last_disconnect_time and self._last_disconnect_rc:
                        elapsed = time.time() - self._last_disconnect_time
                        backoff = min(self._reconnect_base * (2 ** max(
                            0, self._reconnect_attempts - 1)), self._reconnect_max_backoff)
                        if self._last_disconnect_rc == 7:
                            backoff = max(backoff, self._rc7_cooldown)
                        wait = max(0.0, backoff - elapsed)
                        if wait:
                            _LOGGER.warning("MQTT instance=%s reconnect cooldown %.1fs",
                                            self._instance, wait)
                            if self._shutdown_event.wait(wait):
                                return False
                    if self._shutdown_event.is_set():
                        return False
                    client = mqtt.Client(
                        client_id=self.client_id, transport='websockets',
                        protocol=mqtt.MQTTv311, reconnect_on_failure=False,
                    )
                    with self._lock:
                        self._client = client
                        self._generation += 1
                        self._connect_event.clear()
                    client.connect_timeout = timeout
                    client.ws_set_options(path=MQTT_PATH, headers=self._build_headers())
                    client.tls_set(tls_version=ssl.PROTOCOL_TLSv1_2)
                    client.on_connect = self._on_connect
                    client.on_message = self._on_message
                    client.on_disconnect = self._on_disconnect
                    if self._shutdown_event.is_set():
                        self._stop_current_client()
                        return False
                    _LOGGER.debug("MQTT instance=%s generation=%d connecting",
                                  self._instance, self._generation)
                    client.connect(MQTT_HOST, MQTT_PORT, keepalive=KEEPALIVE)
                    if not self._shutdown_event.is_set():
                        client.loop_start()
                        self._connect_event.wait(timeout)
                    with self._lock:
                        connected = self._is_current(client) and self._connected
                    if not connected:
                        self._stop_current_client()
                    return connected
                except Exception as ex:
                    # Network exception text may contain signed connection data.
                    _LOGGER.error("MQTT instance=%s connect failed (%s)",
                                  self._instance, type(ex).__name__)
                    try:
                        self._stop_current_client()
                    except Exception:
                        _LOGGER.error("MQTT instance=%s transport cleanup failed",
                                      self._instance)
                    return False
        finally:
            with self._lock:
                self._connecting = False

    async def async_connect(self) -> bool:
        """Run blocking network operations outside the event loop."""
        with self._lock:
            if self._shutting_down:
                return False
        return await asyncio.to_thread(self._blocking_connect)

    def _begin_shutdown(self) -> None:
        """Prevent callbacks and wake a worker before waiting for its lock."""
        with self._lock:
            self._shutting_down = True
            self._refreshing_credentials = False
            self._shutdown_event.set()
            self._connect_event.set()

    def shutdown(self) -> None:
        """Permanently stop and join all owned transports; safe to repeat."""
        self._begin_shutdown()
        self.disconnect()

    async def async_shutdown(self) -> None:
        """Stop without joining a network thread on HA's event loop."""
        self._begin_shutdown()
        await asyncio.to_thread(self.disconnect)

    def disconnect(self) -> None:
        """Serialize teardown with connection creation, including shutdown."""
        with self._operation_lock:
            self._stop_current_client()

    def is_connected(self) -> bool:
        """Maintain availability during refresh, never after shutdown."""
        with self._lock:
            return not self._shutting_down and (
                self._connected or self._refreshing_credentials)

    def _generate_correlation_id(self) -> str:
        """Generate a correlation ID for commands."""
        return ''.join(random.choices(string.hexdigits.lower(), k=8))

    def _get_timestamp(self) -> str:
        """Get current timestamp in ISO format."""
        return datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'

    def _build_command_payload(
        self,
        command_name: str,
        port_name: str,
        properties: Dict[str, Any]
    ) -> str:
        """Build command payload."""
        payload = {
            'cid': self._generate_correlation_id(),
            'time': self._get_timestamp(),
            'type': 'command',
            'cn': command_name,
            'ct': 'mobile',
            'data': {
                'portName': port_name,
                'properties': properties
            }
        }
        return json.dumps(payload, separators=(',', ':'))

    def set_mode(self, mode: int, raw_key: str) -> bool:
        """Set device mode using raw property key."""
        if not self._connected:
            _LOGGER.error("MQTT not connected")
            return False
        
        payload = self._build_command_payload(
            'setPort',
            self._port_control,
            {raw_key: mode}
        )
        
        _LOGGER.debug("Setting mode to %s using key %s", mode, raw_key)
        success = self._publish(payload)
        
        try:
            self.request_port_status(self._port_status)
        except Exception:
            pass
        
        return success

    def set_power(self, power_on: bool) -> bool:
        """Set power state via AWS IoT shadow update."""
        if not self._connected:
            _LOGGER.error("MQTT not connected")
            return False

        desired = {"state": {"desired": {"powerOn": power_on}}}
        shadow_payload = json.dumps(desired, separators=(',', ':'))
        success = self._publish(shadow_payload, topic=f"$aws/things/{self.device_id}/shadow/update")

        if success:
            self.request_port_status(self._port_status)

        return success

    def set_property(self, raw_key: str, value: Any) -> bool:
        """Set a single device property via the Control port."""
        if not self._connected:
            _LOGGER.error("MQTT not connected")
            return False

        payload = self._build_command_payload(
            'setPort',
            self._port_control,
            {raw_key: value},
        )

        _LOGGER.debug("Setting property %s to %s", raw_key, value)
        res = self._publish(payload)

        try:
            self.request_port_status(self._port_status)
        except Exception:
            pass

        return res

    def reset_filter_clean(self, raw_key: str, reset_value: int) -> bool:
        """Reset clean-filter maintenance timer.

        raw_key and reset_value come from the model config (filter_clean_reset_raw /
        filter_clean_reset_value), matching the official app's MQTT publish pattern.
        """
        if not self._connected:
            _LOGGER.error("MQTT not connected")
            return False

        payload = self._build_command_payload('setPort', self._port_filter_write, {raw_key: reset_value})
        _LOGGER.debug("Resetting clean-filter timer: %s = %s", raw_key, reset_value)
        success = self._publish(payload, qos=1)

        try:
            self.request_port_status(self._port_filter_read)
        except Exception:
            pass

        return success

    def reset_filter_replace(self, raw_key: str, reset_value: int) -> bool:
        """Reset replace-filter maintenance timer.

        raw_key and reset_value come from the model config (filter_replace_reset_raw /
        filter_replace_reset_value), matching the official app's MQTT publish pattern.
        """
        if not self._connected:
            _LOGGER.error("MQTT not connected")
            return False

        payload = self._build_command_payload('setPort', self._port_filter_write, {raw_key: reset_value})
        _LOGGER.debug("Resetting replace-filter timer: %s = %s", raw_key, reset_value)
        success = self._publish(payload, qos=1)

        try:
            self.request_port_status(self._port_filter_read)
        except Exception:
            pass

        return success

    def request_port_status(self, port_name: str) -> bool:
        """Request status for a specific port."""
        if not self._connected:
            _LOGGER.error("MQTT not connected")
            return False

        payload = self._build_command_payload(
            'getPort',
            port_name,
            {}
        )
        
        _LOGGER.debug("Requesting status for port %s", port_name)
        return self._publish(payload)

    def request_shadow_get(self) -> bool:
        """Request AWS IoT shadow get."""
        if not self._connected:
            _LOGGER.error("MQTT not connected")
            return False

        shadow_topic = f"$aws/things/{self.device_id}/shadow/get"
        _LOGGER.debug("Requesting shadow get")
        return self._publish('{}', topic=shadow_topic)

    def _publish(self, payload: str, topic: Optional[str] = None, qos: int = 0) -> bool:
        """Publish message to MQTT broker."""
        if not self._client or not self._connected:
            _LOGGER.error("MQTT client not connected")
            return False

        try:
            publish_topic = topic or self.outbound_topic
            result = self._client.publish(publish_topic, payload, qos=qos)
            
            if getattr(result, 'rc', None) == mqtt.MQTT_ERR_SUCCESS:
                _LOGGER.debug("Published to %s: %s", publish_topic, payload)
                return True
            else:
                _LOGGER.error("Failed to publish to %s: rc=%s", publish_topic, getattr(result, 'rc', None))
                return False
                
        except Exception as ex:
            _LOGGER.error("Error publishing message: %s", ex)
            return False

    async def async_update_credentials(self, access_token: str, signature: str) -> bool:
        """Serialize refreshes and await complete teardown before replacement."""
        async with self._credentials_lock:
            with self._lock:
                if self._shutting_down or self._connecting:
                    return False
                self.access_token = access_token
                self.signature = signature
                self._refreshing_credentials = True
            _LOGGER.debug("MQTT instance=%s refreshing credentials", self._instance)
            try:
                await asyncio.to_thread(self.disconnect)
                return await self.async_connect()
            finally:
                with self._lock:
                    self._refreshing_credentials = False
                    if (not self._shutting_down and not self._connected
                            and self._connection_callback):
                        self._connection_callback(False)
