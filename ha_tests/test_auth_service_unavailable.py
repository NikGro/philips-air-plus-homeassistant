"""The auth layer separates an unreachable service from a rejected token.

Only an unreachable endpoint or a transient status may be retried. A 4xx that
rejects the credential must still send the user through re-authentication.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import pytest
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.philips_airplus import auth as auth_mod
from custom_components.philips_airplus.auth import (
    AuthenticationUnavailable,
    PhilipsAirplusAuth,
    _is_retryable_error,
)
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


def _auth() -> PhilipsAirplusAuth:
    return PhilipsAirplusAuth(
        None,
        AUTH_MODE_OAUTH,
        access_token="synthetic-access",
        refresh_token="synthetic-refresh",
        client_id="synthetic-client",
    )


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


def _session_with_a_malformed_body() -> Mock:
    """A 200 that declares JSON but cannot be decoded (captive portal, proxy)."""
    response = Mock(
        status=200,
        json=AsyncMock(side_effect=json.JSONDecodeError("Expecting value", "", 0)),
    )
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    session = Mock()
    session.get = Mock(return_value=response)
    session.post = Mock(return_value=response)
    return session


@pytest.mark.asyncio
async def test_initialize_propagates_unreachable_service():
    auth = _auth()
    with patch.object(
        auth_mod, "async_get_clientsession", return_value=_session_that_cannot_connect()
    ):
        with pytest.raises(AuthenticationUnavailable):
            await auth.initialize()


@pytest.mark.asyncio
async def test_initialize_defers_a_transient_server_error():
    """A 5xx from the device API is temporary, not a reason to re-authenticate."""
    auth = _auth()
    with patch.object(
        auth_mod, "async_get_clientsession", return_value=_session_answering(503)
    ):
        with pytest.raises(AuthenticationUnavailable):
            await auth.initialize()


@pytest.mark.asyncio
async def test_initialize_defers_a_malformed_body():
    """A 200 that declares JSON but cannot be decoded is not a credential problem."""
    auth = _auth()
    with patch.object(
        auth_mod,
        "async_get_clientsession",
        return_value=_session_with_a_malformed_body(),
    ):
        with pytest.raises(AuthenticationUnavailable):
            await auth.initialize()


@pytest.mark.asyncio
async def test_initialize_still_reports_a_rejected_token():
    """A 4xx answer is a real auth problem, so setup still demands reauth."""
    auth = _auth()
    with patch.object(
        auth_mod, "async_get_clientsession", return_value=_session_answering(403)
    ):
        assert await auth.initialize() is False


@pytest.mark.asyncio
async def test_refresh_token_propagates_unreachable_service():
    auth = _auth()
    implementation = Mock(async_refresh_token=AsyncMock(side_effect=UNREACHABLE))
    with patch.object(
        auth_mod, "PhilipsAirplusOAuth2Implementation", return_value=implementation
    ):
        with pytest.raises(AuthenticationUnavailable):
            await auth.refresh_access_token()
    # An unreachable service must not discard working credentials.
    assert auth.refresh_token == "synthetic-refresh"


@pytest.mark.asyncio
async def test_refresh_token_defers_a_transient_server_error():
    auth = _auth()
    with patch.object(
        auth_mod, "async_get_clientsession", return_value=_session_answering(500)
    ):
        with pytest.raises(AuthenticationUnavailable):
            await auth.refresh_access_token()
    assert auth.refresh_token == "synthetic-refresh"


@pytest.mark.asyncio
async def test_ensure_access_token_keeps_a_still_valid_token():
    """Refreshing early is an optimisation; a blip must not drop a valid token."""
    auth = _auth()
    auth.expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    auth.refresh_access_token = AsyncMock(
        side_effect=AuthenticationUnavailable("dns")
    )
    assert await auth.ensure_access_token() is True


@pytest.mark.asyncio
async def test_ensure_access_token_propagates_once_the_token_has_expired():
    auth = _auth()
    auth.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    auth.refresh_access_token = AsyncMock(
        side_effect=AuthenticationUnavailable("dns")
    )
    with pytest.raises(AuthenticationUnavailable):
        await auth.ensure_access_token()


def test_classifier_separates_retryable_from_rejected_credentials():
    """Pin the classification table: retryable vs. needs-the-user."""
    retryable = [
        aiohttp.ClientConnectionError("Cannot connect to host"),
        aiohttp.ContentTypeError(None, ()),
        asyncio.TimeoutError(),
        OSError("network unreachable"),
        json.JSONDecodeError("Expecting value", "", 0),
        UnicodeDecodeError("utf-8", b"\xdc", 0, 1, "invalid continuation byte"),
    ]
    rejected = [
        RuntimeError("Failed to fetch user ID: 403"),
        RuntimeError("Refresh token request failed: 400 - invalid_grant"),
    ]
    assert all(_is_retryable_error(ex) for ex in retryable)
    assert not any(_is_retryable_error(ex) for ex in rejected)


@pytest.mark.asyncio
async def test_update_defers_when_the_service_is_unreachable(tmp_path):
    """A poll must report an unavailable service, never trigger a reauth."""
    entry = ConfigEntry(
        domain=DOMAIN,
        title="Regression purifier",
        version=1,
        minor_version=1,
        data={
            CONF_AUTH_MODE: AUTH_MODE_OAUTH,
            CONF_ACCESS_TOKEN: "synthetic-access",
            CONF_REFRESH_TOKEN: "synthetic-refresh",
            CONF_TOKEN_EXPIRES_AT: 4102444800,
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
    coordinator = PhilipsAirplusDataCoordinator(HomeAssistant(str(tmp_path)), entry)
    coordinator._auth = Mock(
        ensure_access_token=AsyncMock(
            side_effect=AuthenticationUnavailable("service unreachable")
        )
    )
    coordinator._mqtt_client = Mock(is_connected=Mock(return_value=False))
    with pytest.raises(UpdateFailed) as failure:
        await coordinator._async_update_data()
    assert "service unreachable" in str(failure.value)
