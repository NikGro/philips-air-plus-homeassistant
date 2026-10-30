"""Token expiry must not depend on the local time zone or DST changes."""
import asyncio
import os
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from custom_components.philips_airplus import auth as auth_mod
from custom_components.philips_airplus.auth import PhilipsAirplusAuth


@pytest.fixture(autouse=True)
def berlin_tz():
    old = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Berlin"
    time.tzset()
    yield
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()


def _auth():
    a = PhilipsAirplusAuth(None, "oauth", access_token="a", refresh_token="r", client_id="c")
    a.refresh_access_token = AsyncMock(return_value=True)
    return a


def _freeze(monkeypatch, utc_now):
    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return utc_now if tz else utc_now.astimezone().replace(tzinfo=None)

    monkeypatch.setattr(auth_mod, "datetime", FakeDT)


def test_expiry_is_timezone_aware():
    a = _auth()
    a.expires_at = None
    from custom_components.philips_airplus.auth import expiry_from_epoch

    assert expiry_from_epoch(1_800_000_000).tzinfo is not None


def test_refresh_triggers_across_autumn_dst_change(monkeypatch):
    # Token expires 01:26:47 UTC on 2026-10-25, i.e. 03:26:47 CEST. Berlin falls
    # back at 01:00 UTC, after which the same wall-clock value means 02:26:47 UTC.
    exp = datetime(2026, 10, 25, 1, 26, 47, tzinfo=timezone.utc)
    a = _auth()
    from custom_components.philips_airplus.auth import expiry_from_epoch

    a.expires_at = expiry_from_epoch(int(exp.timestamp()))
    # 01:27 UTC: token is expired, a refresh must happen
    _freeze(monkeypatch, datetime(2026, 10, 25, 1, 27, 0, tzinfo=timezone.utc))
    assert asyncio.run(a.ensure_access_token()) is True
    a.refresh_access_token.assert_awaited_once()


def test_no_refresh_when_token_still_valid(monkeypatch):
    exp = datetime(2026, 10, 25, 5, 0, 0, tzinfo=timezone.utc)
    a = _auth()
    from custom_components.philips_airplus.auth import expiry_from_epoch

    a.expires_at = expiry_from_epoch(int(exp.timestamp()))
    _freeze(monkeypatch, datetime(2026, 10, 25, 1, 0, 0, tzinfo=timezone.utc))
    assert asyncio.run(a.ensure_access_token()) is True
    a.refresh_access_token.assert_not_awaited()


def test_expires_at_roundtrips_as_epoch():
    from custom_components.philips_airplus.auth import expiry_from_epoch

    assert expiry_from_epoch(1_800_000_000).timestamp() == 1_800_000_000
