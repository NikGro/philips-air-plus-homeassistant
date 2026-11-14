"""A setup failure caused by an unreachable service must be retried.

These tests deliberately never import the exception added by the fix, so they
also run against the previous release and demonstrate the regression they guard
(there the entry raised ConfigEntryAuthFailed and never retried).
"""
import json
import pathlib
from types import MappingProxyType
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import pytest
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.philips_airplus import auth as auth_mod
from custom_components.philips_airplus.api import PhilipsAirplusDevice
from custom_components.philips_airplus.config_flow import PhilipsAirplusConfigFlow
from custom_components.philips_airplus.const import (
    AUTH_MODE_OAUTH,
    CONF_ACCESS_TOKEN,
    CONF_AUTH_MODE,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_DEVICE_UUID,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
    DOMAIN,
)
from custom_components.philips_airplus.coordinator import PhilipsAirplusDataCoordinator

UNREACHABLE = aiohttp.ClientConnectionError(
    "Cannot connect to host prod.eu-da.iot.versuni.com:443 ssl:default "
    "[Timeout while contacting DNS servers]"
)

# Far enough out that setup never tries to refresh the access token, so the
# failure happens where it did in production: fetching the user and signature.
FUTURE_EXPIRY = 4102444800  # 2100-01-01T00:00:00Z


def _session_that_cannot_connect() -> Mock:
    session = Mock()
    session.get = Mock(side_effect=UNREACHABLE)
    session.post = Mock(side_effect=UNREACHABLE)
    return session


def _session_answering(status: int) -> Mock:
    response = Mock(status=status, text=AsyncMock(return_value=""))
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    session = Mock()
    session.get = Mock(return_value=response)
    session.post = Mock(return_value=response)
    return session


def _coordinator(hass: HomeAssistant) -> PhilipsAirplusDataCoordinator:
    entry = ConfigEntry(
        domain=DOMAIN,
        title="Regression purifier",
        version=1,
        minor_version=1,
        data={
            CONF_AUTH_MODE: AUTH_MODE_OAUTH,
            CONF_ACCESS_TOKEN: "synthetic-access",
            CONF_REFRESH_TOKEN: "synthetic-refresh",
            CONF_TOKEN_EXPIRES_AT: FUTURE_EXPIRY,
            CONF_DEVICE_ID: "synthetic-device",
            CONF_DEVICE_UUID: "synthetic-uuid",
            CONF_DEVICE_NAME: "Regression purifier",
        },
        options={},
        source="user",
        unique_id="regression",
        state=ConfigEntryState.SETUP_IN_PROGRESS,
        discovery_keys=MappingProxyType({}),
        subentries_data=[],
    )
    return PhilipsAirplusDataCoordinator(hass, entry)


@pytest.mark.asyncio
async def test_setup_defers_when_service_is_unreachable(tmp_path):
    coordinator = _coordinator(HomeAssistant(str(tmp_path)))
    with patch.object(
        auth_mod, "async_get_clientsession", return_value=_session_that_cannot_connect()
    ):
        with pytest.raises(UpdateFailed):
            await coordinator._async_setup()


@pytest.mark.asyncio
async def test_unreachable_service_raises_not_ready_instead_of_auth_failed(tmp_path):
    coordinator = _coordinator(HomeAssistant(str(tmp_path)))
    with patch.object(
        auth_mod, "async_get_clientsession", return_value=_session_that_cannot_connect()
    ):
        with pytest.raises(ConfigEntryNotReady) as failure:
            await coordinator.async_config_entry_first_refresh()
    # The retryable cause is what Home Assistant keeps and schedules the retry for.
    assert isinstance(failure.value.__cause__, UpdateFailed)
    assert "unreachable" in str(failure.value.__cause__)


@pytest.mark.asyncio
async def test_rejected_token_still_raises_auth_failed(tmp_path):
    """The negative control: a genuinely bad token must keep asking for reauth."""
    coordinator = _coordinator(HomeAssistant(str(tmp_path)))
    with patch.object(
        auth_mod, "async_get_clientsession", return_value=_session_answering(403)
    ):
        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_setup()


@pytest.mark.asyncio
async def test_device_selection_reports_cannot_connect_when_api_is_unreachable(
    tmp_path,
):
    """The config flow must show an error, not leak the network exception."""
    flow = PhilipsAirplusConfigFlow()
    flow.hass = HomeAssistant(str(tmp_path))
    flow._devices = [
        PhilipsAirplusDevice(
            {"uuid": "synthetic-device", "name": "Purifier", "type": "manual"}
        )
    ]
    flow._access_token = "synthetic-access"
    flow._client_id = "synthetic-client"
    with patch.object(
        auth_mod, "async_get_clientsession", return_value=_session_that_cannot_connect()
    ):
        result = await flow.async_step_select_device({"device": "0"})
    assert result["type"] == "form"
    assert result["step_id"] == "select_device"
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.parametrize(
    "name",
    [
        "strings.json",
        "translations/en.json",
        "translations/de.json",
        "translations/fr.json",
    ],
)
def test_cannot_connect_is_translated_for_the_options_flow(name):
    """Home Assistant resolves options-flow errors under options.error only."""
    root = pathlib.Path(__file__).resolve().parents[1]
    data = json.loads((root / "custom_components/philips_airplus" / name).read_text())
    message = data["options"]["error"]["cannot_connect"]
    assert message and message != "cannot_connect"
