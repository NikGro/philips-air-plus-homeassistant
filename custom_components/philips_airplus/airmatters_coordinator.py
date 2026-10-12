"""Home Assistant coordinator for the observed Air+/Unicorn cloud protocol."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.dt import utcnow

from .airmatters import AirCloudAuthError, AirCloudClient, AirCloudError
from .airmatters_model import filter_info, model_config
from .airmatters_mqtt import AirCloudMQTT
from .const import (CONF_DEVICE_ID, CONF_DEVICE_NAME, CONF_DEVICE_UUID,
                    CONF_DEVICE_MODEL, CONF_DEVICE_TYPE, CONF_USER_ID,
                    CONF_SIGNING_KEY, PRESET_MODE_MANUAL, SCAN_INTERVAL)

_LOGGER = logging.getLogger(__name__)


class AirCloudCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(hass, _LOGGER, config_entry=entry, name=entry.title,
                         update_interval=SCAN_INTERVAL)
        self.entry = entry
        self.device_id = entry.data[CONF_DEVICE_ID]
        self.device_uuid = entry.data[CONF_DEVICE_UUID]
        self.device_name = entry.data[CONF_DEVICE_NAME]
        self._client = AirCloudClient(async_get_clientsession(hass),
            entry.data.get(CONF_USER_ID, ""), entry.data.get(CONF_SIGNING_KEY, ""))
        self._model_config = model_config(entry.data.get(CONF_DEVICE_MODEL, ""),
                                          entry.data.get(CONF_DEVICE_TYPE, ""))
        self._mqtt: AirCloudMQTT | None = None
        self._device_state: dict = {}
        self._online = False
        self._has_state = False
        self._closing = False
        self._connect_lock = asyncio.Lock()
        self._update_lock = asyncio.Lock()
        self._reconnect_task: asyncio.Task | None = None

    @property
    def device_state(self):
        return dict(self._device_state)

    @property
    def is_connected(self):
        return bool(not self._closing and self._online and self._has_state and
                    self._mqtt and self._mqtt.connected)

    def _snapshot(self):
        return {"device_state": dict(self._device_state), "filter_info": filter_info(self._device_state),
                "connected": self.is_connected, "last_update": utcnow()}

    def _state_received(self, transport, state):
        if self._closing or self._mqtt is not transport:
            return
        self._device_state = dict(state)
        self._has_state = True
        self.async_set_updated_data(self._snapshot())

    def _disconnected(self, transport):
        if self._closing or self._mqtt is not transport:
            return
        self._has_state = False
        self.async_update_listeners()
        self._schedule_reconnect()

    def _schedule_reconnect(self):
        if self._closing or (self._reconnect_task and not self._reconnect_task.done()):
            return
        self._reconnect_task = self.hass.async_create_background_task(self._reconnect(), "Air+ cloud reconnect")

    async def _reconnect(self):
        delay = 2
        while not self._closing:
            await asyncio.sleep(delay)
            try:
                async with self._update_lock:
                    await self._read_device_info()
                    await self._ensure_connection()
                    await self._mqtt.read()
                return
            except AirCloudAuthError:
                await self._drop_connection()
                self.entry.async_start_reauth(self.hass)
                return
            except AirCloudError:
                await self._drop_connection()
                delay = min(delay * 2, 60)
                _LOGGER.debug("Air+ cloud reconnect will retry")

    async def _drop_connection(self):
        async with self._connect_lock:
            await self._close_transport()

    async def _close_transport(self):
        transport, self._mqtt = self._mqtt, None
        self._has_state = False
        if transport:
            await transport.close()

    async def _ensure_connection(self):
        async with self._connect_lock:
            if self._closing:
                raise AirCloudError("Integration is unloading")
            if self._mqtt and self._mqtt.connected:
                return
            await self._close_transport()
            connection = await self._client.connection(self.device_id)
            transport = AirCloudMQTT(connection,
                lambda state: self._state_received(transport, state),
                lambda: self._disconnected(transport))
            self._mqtt = transport
            try:
                await transport.connect()
            except BaseException:
                await self._close_transport()
                raise

    async def _read_device_info(self):
        records = await self._client.devices()
        record = next((item for item in records if item["device_id"] == self.device_id), None)
        if record is None:
            raise AirCloudAuthError("Purifier is no longer linked to this account")
        info = record["device_info"]
        config = model_config(info.get("modelid", ""), info.get("type", ""))
        if not config:
            raise AirCloudError("Unsupported Air+ cloud model")
        self._model_config = config
        self._online = info.get("is_online") is True

    async def _async_setup(self):
        try:
            await self._read_device_info()
        except AirCloudAuthError as error:
            raise ConfigEntryAuthFailed(str(error)) from None
        except AirCloudError as error:
            raise UpdateFailed(str(error)) from None

    async def _async_update_data(self):
        async with self._update_lock:
            return await self._refresh_state()

    async def _refresh_state(self):
        try:
            await self._read_device_info()
            await self._ensure_connection()
            await self._mqtt.read()
            return self._snapshot()
        except AirCloudAuthError as error:
            await self._drop_connection()
            raise ConfigEntryAuthFailed(str(error)) from None
        except AirCloudError as error:
            await self._drop_connection()
            self._schedule_reconnect()
            raise UpdateFailed(str(error)) from None

    def _get_mode_name(self, value):
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            return PRESET_MODE_MANUAL
        return next((name for name, mode in self._model_config.get("modes", {}).items()
                     if mode == numeric), PRESET_MODE_MANUAL)

    async def _command(self, desired):
        if not self.is_connected:
            raise HomeAssistantError("Purifier is unavailable")
        try:
            await self._mqtt.update(desired)
        except AirCloudError as error:
            raise HomeAssistantError(str(error)) from None
        # Update acceptance is not a physical-state confirmation. Wait for
        # reported updates or reconciliation; never fabricate optimistic state.
        await self.async_request_refresh()
        return True

    async def set_power(self, enabled):
        return await self._command({"D03102": int(bool(enabled))})

    async def set_mode(self, mode):
        value = self._model_config.get("modes", {}).get(mode)
        if value is None:
            raise HomeAssistantError("Unsupported purifier mode")
        return await self._command({"D0310C": value})

    async def set_property(self, key, value):
        if key == "power":
            return await self.set_power(value)
        if key == "mode":
            return await self.set_mode(value)
        raise HomeAssistantError("Unverified purifier setting")

    async def reset_filter_clean(self):
        raise HomeAssistantError("Filter resets are not verified for this cloud backend")

    async def reset_filter_replace(self):
        raise HomeAssistantError("Filter resets are not verified for this cloud backend")

    async def async_shutdown(self):
        self._closing = True
        task, self._reconnect_task = self._reconnect_task, None
        if task and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self._drop_connection()
        await super().async_shutdown()
