"""DaConnect rejects one exact User-Agent with HTTP 403 (PR #15)."""
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.philips_airplus.api import PhilipsAirplusAPIError
from custom_components.philips_airplus.config_flow import PhilipsAirplusConfigFlow
from custom_components.philips_airplus.const import HTTP_USER_AGENT

REJECTED = "okhttp/4.12.0 (Android 14; Pixel 7)"


def test_user_agent_is_not_the_one_the_api_rejects():
    assert HTTP_USER_AGENT != REJECTED
    assert HTTP_USER_AGENT.startswith("okhttp/")


@pytest.mark.asyncio
async def test_email_otp_reports_cannot_connect_when_device_discovery_fails(tmp_path):
    flow = PhilipsAirplusConfigFlow(); flow.hass = HomeAssistant(str(tmp_path))
    flow._email = "test@example.com"; flow._vtoken = "verification"
    auth = Mock()
    auth.verify_otp = AsyncMock(return_value="session")
    auth.exchange_session_for_tokens = AsyncMock(return_value={"access_token": "synthetic"})
    auth.close = AsyncMock()
    client = Mock()
    client.list_devices = AsyncMock(side_effect=PhilipsAirplusAPIError("403"))
    client.close = AsyncMock()
    base = "custom_components.philips_airplus.config_flow."
    with patch(base + "EmailOTPAuth", return_value=auth), \
         patch(base + "PhilipsAirplusAPIClient", return_value=client):
        result = await flow.async_step_email_otp({"otp_code": "123456"})
    assert result["type"] == "form" and result["step_id"] == "email_otp"
    assert result["errors"] == {"base": "cannot_connect"}
