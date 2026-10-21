"""Exercise entry update notifications with real Home Assistant dispatch."""
import asyncio
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
import pytest_asyncio
from homeassistant.config_entries import ConfigEntries, ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components import philips_airplus as integration
from custom_components.philips_airplus.const import (
    AUTH_MODE_AIRPLUS_CLOUD,
    AUTH_MODE_OAUTH,
    CONF_ACCESS_TOKEN,
    CONF_AUTH_MODE,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_DEVICE_UUID,
    CONF_ENABLE_MQTT,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
    DOMAIN,
)
from custom_components.philips_airplus.coordinator import PhilipsAirplusDataCoordinator


@pytest_asyncio.fixture
async def loaded_entry(tmp_path):
    """Use HA's real ConfigEntry manager; replace only network/platform I/O."""
    hass = HomeAssistant(str(tmp_path))
    hass.config_entries = ConfigEntries(hass, {})
    entry = ConfigEntry(
        domain=DOMAIN, title="Regression purifier", version=1, minor_version=1,
        data={CONF_AUTH_MODE: AUTH_MODE_OAUTH, CONF_ACCESS_TOKEN: "synthetic-old",
              CONF_DEVICE_ID: "synthetic-device", CONF_DEVICE_UUID: "synthetic-uuid",
              CONF_DEVICE_NAME: "Regression purifier"},
        options={CONF_ENABLE_MQTT: True}, source="user", unique_id="regression",
        discovery_keys=MappingProxyType({}), subentries_data=[],
    )
    hass.config_entries._entries[entry.entry_id] = entry
    # Persistence and platform loading are not part of this regression.
    hass.config_entries._async_schedule_save = Mock()
    hass.config_entries.async_reload = AsyncMock(return_value=True)
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    with (
        patch.object(integration.er, "async_get", return_value=Mock()),
        patch.object(integration.er, "async_entries_for_config_entry", return_value=[]),
        patch("custom_components.philips_airplus.auth.async_get_clientsession", return_value=Mock()),
        patch.object(PhilipsAirplusDataCoordinator, "async_config_entry_first_refresh", AsyncMock(return_value=True)),
    ):
        yield hass, entry
    await entry._async_process_on_unload(hass)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_token_refresh_keeps_coordinator_and_updates_mqtt_credentials(loaded_entry):
    """Token persistence must not unload the coordinator halfway through a refresh."""
    hass, entry = loaded_entry
    assert await integration.async_setup_entry(hass, entry)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator._connected = True
    mqtt = Mock(access_token="synthetic-old", async_shutdown=AsyncMock())
    mqtt.is_connected.return_value = True
    coordinator._mqtt_client = mqtt
    auth = SimpleNamespace(access_token="synthetic-old", signature="synthetic-signature", close=AsyncMock())
    coordinator._auth = auth
    cycle = 0

    async def refresh_token():
        nonlocal cycle
        cycle += 1
        auth.access_token = f"synthetic-access-{cycle}"
        auth.signature = f"synthetic-signature-{cycle}"
        await coordinator._on_token_refresh({
            "access_token": auth.access_token,
            "refresh_token": f"synthetic-refresh-{cycle}",
            "expires_at": cycle,
        })
        # Force HA to dispatch the update before MQTT credentials are changed.
        await hass.async_block_till_done()
        return True

    async def update_credentials(access_token, signature):
        mqtt.access_token = access_token
        mqtt.signature = signature
        return True

    auth.ensure_access_token = refresh_token
    mqtt.async_update_credentials = AsyncMock(side_effect=update_credentials)
    for _ in range(50):
        await coordinator._async_update_data()
        assert hass.data[DOMAIN][entry.entry_id] is coordinator
        assert not coordinator._stopping
        assert entry.data[CONF_ACCESS_TOKEN] == auth.access_token
        assert entry.data[CONF_REFRESH_TOKEN] == f"synthetic-refresh-{cycle}"
        assert entry.data[CONF_TOKEN_EXPIRES_AT] == cycle
    assert mqtt.async_update_credentials.await_count == 50
    assert mqtt.access_token == "synthetic-access-50"
    assert mqtt.signature == "synthetic-signature-50"
    hass.config_entries.async_reload.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mqtt_enabled", [True, False])
@pytest.mark.parametrize("auth_mode", [AUTH_MODE_OAUTH, AUTH_MODE_AIRPLUS_CLOUD])
async def test_data_only_updates_do_not_reload(loaded_entry, mqtt_enabled, auth_mode):
    hass, entry = loaded_entry
    hass.config_entries.async_update_entry(
        entry, options={CONF_ENABLE_MQTT: mqtt_enabled},
        data={**entry.data, CONF_AUTH_MODE: auth_mode},
    )
    with patch.object(integration, "AirCloudCoordinator") as cloud:
        cloud.return_value.async_config_entry_first_refresh = AsyncMock(return_value=True)
        assert await integration.async_setup_entry(hass, entry)
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_TOKEN_EXPIRES_AT: 123})
    await hass.async_block_till_done()
    hass.config_entries.async_reload.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_mqtt", [True, False])
async def test_real_options_change_still_reloads_once(loaded_entry, initial_mqtt):
    hass, entry = loaded_entry
    hass.config_entries.async_update_entry(entry, options={CONF_ENABLE_MQTT: initial_mqtt})
    assert await integration.async_setup_entry(hass, entry)
    hass.config_entries.async_update_entry(entry, options={CONF_ENABLE_MQTT: not initial_mqtt})
    await hass.async_block_till_done()
    hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)


@pytest.mark.asyncio
async def test_queued_token_update_does_not_duplicate_options_reload(loaded_entry):
    hass, entry = loaded_entry
    assert await integration.async_setup_entry(hass, entry)
    # Both notifications see the same, newly updated entry when dispatched.
    hass.config_entries.async_update_entry(entry, options={CONF_ENABLE_MQTT: False})
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_ACCESS_TOKEN: "synthetic-new"})
    await hass.async_block_till_done()
    hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)


@pytest.mark.asyncio
async def test_listener_removed_on_unload_and_rebased_on_next_setup(loaded_entry):
    hass, entry = loaded_entry
    assert await integration.async_setup_entry(hass, entry)
    assert len(entry.update_listeners) == 1
    await entry._async_process_on_unload(hass)
    assert not entry.update_listeners
    hass.config_entries.async_update_entry(entry, options={CONF_ENABLE_MQTT: False})
    await hass.async_block_till_done()
    assert await integration.async_setup_entry(hass, entry)
    assert len(entry.update_listeners) == 1
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_TOKEN_EXPIRES_AT: 99})
    await hass.async_block_till_done()
    hass.config_entries.async_reload.assert_not_awaited()
    hass.config_entries.async_update_entry(entry, options={CONF_ENABLE_MQTT: True})
    await hass.async_block_till_done()
    hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)


@pytest.mark.asyncio
async def test_token_callback_during_shutdown_does_not_persist_or_reload(loaded_entry):
    hass, entry = loaded_entry
    assert await integration.async_setup_entry(hass, entry)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    stopping = asyncio.Event()
    release = asyncio.Event()

    async def stop_transport():
        stopping.set()
        await release.wait()

    coordinator._mqtt_client = Mock(async_shutdown=AsyncMock(side_effect=stop_transport))
    coordinator._auth = SimpleNamespace(close=AsyncMock())
    original_data = dict(entry.data)
    shutdown = asyncio.create_task(coordinator.async_shutdown())
    try:
        await asyncio.wait_for(stopping.wait(), 2)
        await coordinator._on_token_refresh({
            "access_token": "synthetic-late", "refresh_token": "synthetic-late", "expires_at": 123,
        })
        await hass.async_block_till_done()
        assert dict(entry.data) == original_data
        hass.config_entries.async_reload.assert_not_awaited()
    finally:
        release.set()
        await asyncio.wait_for(shutdown, 2)
    coordinator._mqtt_client.async_shutdown.assert_awaited_once()
    coordinator._auth.close.assert_awaited_once()
