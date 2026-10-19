"""DaConnect lifecycle regressions; all credentials and transports are synthetic."""
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch

from custom_components.philips_airplus import mqtt_client as mod


def wrapper():
    return mod.PhilipsAirplusMQTTClient('synthetic-device', 'synthetic-token', 'synthetic-signature')


class LifecycleRepro(unittest.TestCase):
    def test_shutdown_stops_underlying_client(self):
        owner = wrapper()
        client = Mock()
        owner._client = client
        owner._connected = True
        owner.shutdown()
        self.assertTrue(client.loop_stop.called, 'shutdown left the network loop running')
        self.assertTrue(client.disconnect.called, 'shutdown did not disconnect')
        self.assertFalse(owner._connected)
        self.assertIsNone(owner._client)

    def test_stale_connect_cannot_mark_current_client_connected(self):
        owner = wrapper()
        owner._client = Mock(name='current')
        stale = Mock(name='stale')
        callback = Mock()
        owner.set_connection_callback(callback)
        owner._on_connect(stale, None, {}, 0)
        self.assertFalse(owner._connected, 'old client set shared connected=True')
        callback.assert_not_called()

    def test_stale_disconnect_cannot_mark_current_client_disconnected(self):
        owner = wrapper()
        current = Mock(name='current')
        owner._client = current
        owner._connected = True
        callback = Mock()
        owner.set_connection_callback(callback)
        owner._on_disconnect(Mock(name='stale'), None, 7)
        self.assertTrue(owner._connected, 'old client set shared connected=False')
        self.assertIs(owner._client, current)
        callback.assert_not_called()

    def test_shutdown_suppresses_message_delivery(self):
        owner = wrapper()
        client = Mock()
        owner._client = client
        callback = Mock()
        owner.set_message_callback(callback)
        owner.shutdown()
        message = types.SimpleNamespace(payload=b'{"cn":"status","data":{}}')
        owner._on_message(client, None, message)
        callback.assert_not_called()

    def test_connect_in_cooldown_must_abort_after_shutdown(self):
        owner = wrapper()
        owner._last_disconnect_rc = 7
        owner._last_disconnect_time = time.time()
        owner._reconnect_attempts = 1
        fresh = Mock()
        fresh.connect.side_effect = lambda *a, **k: fresh.on_connect(fresh, None, {}, 0)
        entered, release = threading.Event(), threading.Event()
        def wait_in_cooldown(seconds):
            entered.set()
            release.wait(2)
            return owner._shutting_down
        result = []
        wait_patch = (patch.object(owner._shutdown_event, 'wait', side_effect=wait_in_cooldown)
                      if hasattr(owner, '_shutdown_event') else patch.object(mod.time, 'sleep', side_effect=wait_in_cooldown))
        with wait_patch, patch.object(mod.mqtt, 'Client', return_value=fresh):
            worker = threading.Thread(target=lambda: result.append(owner._blocking_connect(timeout=0.1)))
            worker.start()
            self.assertTrue(entered.wait(2))
            shutdown = threading.Thread(target=owner.shutdown)
            shutdown.start()
            deadline = time.monotonic() + 2
            while not owner._shutting_down and time.monotonic() < deadline:
                threading.Event().wait(0.001)
            release.set()
            worker.join(2)
            shutdown.join(2)
        self.assertFalse(worker.is_alive())
        self.assertFalse(shutdown.is_alive())
        self.assertFalse(fresh.connect.called, 'a new client connected after shutdown during cooldown')
        self.assertEqual(result, [False])

    def test_control_active_client_callbacks_work(self):
        owner = wrapper()
        current = Mock()
        owner._client = current
        callback = Mock()
        owner.set_connection_callback(callback)
        owner._on_connect(current, None, {}, 0)
        self.assertTrue(owner._connected)
        callback.assert_called_with(True)
        owner._on_disconnect(current, None, 7)
        self.assertFalse(owner._connected)
        current.disconnect.assert_called_once()
        current.loop_stop.assert_called_once()
        callback.assert_called_with(False)

    def test_control_connect_guard_rejects_second_attempt(self):
        owner = wrapper()
        owner._connecting = True
        with patch.object(mod.mqtt, 'Client') as constructor:
            self.assertFalse(owner._blocking_connect())
            constructor.assert_not_called()

    def test_real_paho_loop_stop_in_own_thread_sets_termination(self):
        # No networking: exercise actual pinned dependency's self-thread path.
        client = mod.mqtt.Client(mod.mqtt.CallbackAPIVersion.VERSION1)
        observations = []
        def callback_thread():
            client._thread = threading.current_thread()
            result = client.loop_stop()
            observations.append((result, client._thread_terminate))
        worker = threading.Thread(target=callback_thread)
        worker.start()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(observations, [(mod.mqtt.MQTT_ERR_SUCCESS, True)])




import asyncio
import pytest
from unittest.mock import AsyncMock
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from custom_components.philips_airplus.coordinator import PhilipsAirplusDataCoordinator
from custom_components.philips_airplus.const import (
    DOMAIN, CONF_AUTH_MODE, AUTH_MODE_EMAIL_OTP, CONF_DEVICE_ID,
    CONF_DEVICE_UUID, CONF_DEVICE_NAME, CONF_ACCESS_TOKEN,
)


def coordinator(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    entry = ConfigEntry(domain=DOMAIN, title='Synthetic', version=1, minor_version=1,
        unique_id='synthetic-device', source='user', options={}, discovery_keys={},
        subentries_data=[], data={CONF_AUTH_MODE: AUTH_MODE_EMAIL_OTP,
        CONF_DEVICE_ID: 'synthetic-device', CONF_DEVICE_UUID: 'synthetic-uuid',
        CONF_DEVICE_NAME: 'Synthetic', CONF_ACCESS_TOKEN: 'synthetic-token'})
    return PhilipsAirplusDataCoordinator(hass, entry)


@pytest.mark.asyncio
async def test_coordinator_shutdown_awaits_mqtt_and_disables_polling(tmp_path):
    owner = coordinator(tmp_path)
    owner._mqtt_client = Mock(async_shutdown=AsyncMock())
    task = asyncio.create_task(asyncio.sleep(60))
    owner._reconnect_task = task
    await owner.async_shutdown()
    owner._mqtt_client.async_shutdown.assert_awaited_once()
    assert task.done()
    assert owner._shutdown_requested


@pytest.mark.asyncio
async def test_coordinator_rejects_queued_callbacks_after_shutdown(tmp_path):
    owner = coordinator(tmp_path)
    owner._mqtt_client = wrapper()
    await owner.async_shutdown()
    owner.async_set_updated_data = Mock()
    with patch.object(owner.hass, 'async_create_task') as create:
        owner._on_mqtt_connection_in_loop(True)
        owner._on_mqtt_connection_in_loop(False)
        owner._on_mqtt_message_in_loop({'data': {'portName': 'Status', 'properties': {'synthetic': 1}}})
    create.assert_not_called()
    owner.async_set_updated_data.assert_not_called()
    assert owner._device_state == {}


@pytest.mark.asyncio
async def test_failed_refresh_notifies_reconnect_once_and_shutdown_never_does():
    owner = wrapper()
    callback = Mock()
    owner.set_connection_callback(callback)
    with patch.object(owner, 'async_connect', AsyncMock(return_value=False)):
        assert not await owner.async_update_credentials('new-synthetic', 'new-signature')
    callback.assert_called_once_with(False)
    callback.reset_mock()
    await owner.async_shutdown()
    assert not await owner.async_update_credentials('another-synthetic', 'another-signature')
    callback.assert_not_called()


@pytest.mark.asyncio
async def test_simultaneous_credential_refreshes_are_serialized():
    owner = wrapper()
    active = 0
    peak = 0
    async def connect():
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        owner._connected = True
        return True
    with patch.object(owner, 'async_connect', side_effect=connect):
        assert all(await asyncio.gather(
            owner.async_update_credentials('synthetic-a', 'sig-a'),
            owner.async_update_credentials('synthetic-b', 'sig-b')))
    assert peak == 1
    assert owner.access_token == 'synthetic-b'
    await owner.async_shutdown()


def test_teardown_failure_does_not_skip_loop_stop():
    owner = wrapper()
    client = Mock()
    client.disconnect.side_effect = OSError('synthetic failure')
    owner._client = client
    owner.shutdown()
    client.loop_stop.assert_called_once()
    assert not owner.is_connected()


def test_repeated_shutdown_is_idempotent():
    owner = wrapper()
    client = Mock()
    owner._client = client
    owner.shutdown()
    owner.shutdown()
    client.loop_stop.assert_called_once()
    client.disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_cancelled_shutdown_caller_cannot_bypass_transport_teardown(tmp_path):
    owner = coordinator(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    async def finish():
        entered.set()
        await release.wait()
    owner._mqtt_client = Mock(async_shutdown=AsyncMock(side_effect=finish))
    first = asyncio.create_task(owner.async_shutdown())
    await asyncio.wait_for(entered.wait(), 2)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    second = asyncio.create_task(owner.async_shutdown())
    await asyncio.sleep(0)
    assert not second.done(), 'another unload must await the still-running teardown'
    release.set()
    await asyncio.wait_for(second, 2)
    owner._mqtt_client.async_shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_shutdown_does_not_block_event_loop():
    owner = wrapper()
    entered, release = threading.Event(), threading.Event()
    client = Mock()
    def stop():
        entered.set()
        assert release.wait(2)
    client.loop_stop.side_effect = stop
    owner._client = client
    task = asyncio.create_task(owner.async_shutdown())
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
        await asyncio.wait_for(task, 2)


def test_failed_thread_join_blocks_replacement_and_retains_cleanup():
    owner = wrapper()
    old = Mock()
    old.loop_stop.side_effect = RuntimeError('synthetic join failure')
    owner._client = old
    with patch.object(mod.mqtt, 'Client') as constructor:
        assert not owner._blocking_connect(timeout=0.01)
        constructor.assert_not_called()
    old.loop_stop.side_effect = None
    owner.shutdown()
    assert old.loop_stop.call_count == 3
