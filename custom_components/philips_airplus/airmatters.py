"""Air+ account API, independent of the older Versuni DaConnect registry.

Signing reference: the pinned node-red-contrib-philips-airplus runtime
capture. The app signing value is obtained once during setup and kept in the
private config entry; it is not embedded in this integration or logged.
"""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import math
import re
import time
from typing import Any

import aiohttp

AIR_URL = "https://www.api.air.philips.com/"
GIGYA_URL = "https://cdc.accounts.home.id/"
APP_ID = "9fd505fa9c7111e9a1e3061302926720"
GIGYA_KEY = "4_JGZWlP8eQHpEqkvQElolbA"
SIGNING_SOURCE = (
    "https://raw.githubusercontent.com/kwesolowski/node-red-contrib-philips-airplus/"
    "acbffa3683e728512dde7da824184586d3f4f9f9/docs/api-reverse-engineered.md"
)
SIGNING_SOURCE_SHA256 = "2015948594b31cae4f432e5cbd59ae3a34ceb908ad2e7634e449c32df76c384b"
TIMEOUT = aiohttp.ClientTimeout(total=12)
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}")


class AirCloudError(Exception):
    """Sanitized, retryable cloud error; never contains response bodies."""


class AirCloudAuthError(AirCloudError):
    """Authentication or account ownership needs the user's attention."""


def java_urlencode(value: str) -> str:
    result = []
    for byte in value.encode("utf-8"):
        if 48 <= byte <= 57 or 65 <= byte <= 90 or 97 <= byte <= 122 or byte in b"-._*":
            result.append(chr(byte))
        else:
            result.append("+" if byte == 32 else f"%{byte:02X}")
    return "".join(result)


def sign_request(timestamp: str, username: str, secret: str) -> str:
    canonical = f"app_id={APP_ID}&timestamp={timestamp}&username={java_urlencode(username)}"
    inner = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return hmac.new(username.encode(), inner.encode(), hashlib.sha256).hexdigest()


def token_expiry(token: str) -> float:
    """Read only a token issued by our HTTPS API, for refresh scheduling."""
    try:
        encoded = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        expiry = claims["exp"]
        if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or not math.isfinite(expiry):
            raise ValueError
        return float(expiry)
    except (IndexError, KeyError, ValueError, TypeError):
        raise AirCloudError("Cloud token expiry is invalid") from None


async def _request(session: aiohttp.ClientSession, url: str, *, body=None, headers=None, form=False) -> dict:
    kwargs = {"headers": {"Accept": "application/json", **(headers or {})},
              "timeout": TIMEOUT, "allow_redirects": False}
    if body is not None:
        kwargs["data" if form else "json"] = body
    try:
        async with session.request("POST" if body is not None else "GET", url, **kwargs) as response:
            if response.status in (401, 403):
                raise AirCloudAuthError("Cloud authentication rejected")
            if response.status != 200:
                raise AirCloudError(f"Cloud HTTP {response.status}")
            data = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError):
        raise AirCloudError("Cloud request failed") from None
    if not isinstance(data, dict):
        raise AirCloudError("Unexpected cloud response")
    return data


async def load_signing_key(session: aiohttp.ClientSession) -> str:
    """Fetch and verify a pinned reference; never execute downloaded content."""
    try:
        async with session.get(SIGNING_SOURCE, timeout=TIMEOUT, allow_redirects=False) as response:
            if response.status != 200:
                raise AirCloudError("Login preparation unavailable")
            content = bytearray()
            async for chunk in response.content.iter_chunked(8192):
                content.extend(chunk)
                if len(content) > 32768:
                    raise AirCloudError("Login preparation reference is too large")
    except (aiohttp.ClientError, TimeoutError):
        raise AirCloudError("Login preparation unavailable") from None
    if len(content) > 32768 or hashlib.sha256(content).hexdigest() != SIGNING_SOURCE_SHA256:
        raise AirCloudError("Login preparation reference failed verification")
    match = re.search(rb"(?m)^\*\*Secret Key\*\*: `(a_[A-Za-z0-9]{32})`\r?$", content)
    if match is None:
        raise AirCloudError("Login preparation reference is invalid")
    return match[1].decode("ascii")


class AirCloudOTP:
    def __init__(self, session: aiohttp.ClientSession):
        self._session = session

    async def send(self, email: str) -> str:
        data = await _request(self._session, GIGYA_URL + "accounts.auth.otp.email.sendCode",
                              body={"email": email, "apiKey": GIGYA_KEY, "format": "json"}, form=True)
        if data.get("errorCode") != 0 or not isinstance(data.get("vToken"), str) or not data["vToken"]:
            raise AirCloudAuthError("Verification code request rejected")
        return data["vToken"]

    async def verify(self, email: str, code: str, verification: str) -> str:
        if not re.fullmatch(r"[0-9]{6}", code):
            raise AirCloudAuthError("Verification code must contain six digits")
        data = await _request(self._session, GIGYA_URL + "accounts.auth.otp.email.login",
                              body={"email": email, "code": code, "vToken": verification,
                                    "apiKey": GIGYA_KEY, "format": "json"}, form=True)
        uid = data.get("UID")
        if data.get("errorCode") != 0 or not isinstance(uid, str) or not IDENTIFIER.fullmatch(uid):
            raise AirCloudAuthError("Verification code rejected")
        return uid


@dataclass(frozen=True)
class CloudConnection:
    host: str
    path: str = field(repr=False)
    client_id: str = field(repr=False)
    device_id: str = field(repr=False)


def parse_connection(data: dict, device_id: str) -> CloudConnection:
    if data.get("device_id") != device_id:
        raise AirCloudAuthError("MQTT device does not match the account selection")
    host, path, client_id = (data.get(key) for key in ("endpoint", "path", "client_id"))
    if not isinstance(host, str) or not re.fullmatch(r"[a-z0-9-]+-ats\.iot\.[a-z0-9-]+\.amazonaws\.com", host):
        raise AirCloudError("Unexpected MQTT broker")
    if not isinstance(path, str) or not path.startswith("/mqtt?") or len(path) > 8192 or "\r" in path or "\n" in path:
        raise AirCloudError("Invalid signed MQTT path")
    if not isinstance(client_id, str) or not IDENTIFIER.fullmatch(client_id):
        raise AirCloudError("Invalid MQTT client ID")
    return CloudConnection(host, path, client_id, device_id)


class AirCloudClient:
    def __init__(self, session: aiohttp.ClientSession, uid: str, signing_key: str, *, clock=time.time):
        if not isinstance(uid, str) or not IDENTIFIER.fullmatch(uid) or not isinstance(signing_key, str) or not re.fullmatch(r"a_[A-Za-z0-9]{32}", signing_key):
            raise AirCloudAuthError("Missing Air+ account configuration")
        self._session, self._uid, self._key = session, uid, signing_key
        self._clock = clock
        self._token: str | None = None
        self._expires_at = 0.0
        self._token_lock = asyncio.Lock()
        self._own_ids: set[str] = set()

    @staticmethod
    def _check(data: dict):
        meta = data.get("meta")
        code = meta.get("code") if isinstance(meta, dict) else None
        if code in (10001, 10002):
            raise AirCloudAuthError("Air+ account authentication rejected")
        if code != 0:
            raise AirCloudError("Air+ API rejected request")
        return data.get("data")

    async def ensure_token(self) -> str:
        async with self._token_lock:
            if self._token and self._expires_at > self._clock() + 900:
                return self._token
            server = self._check(await _request(self._session, AIR_URL + "device/serverTime/"))
            if isinstance(server, str):
                try:
                    server = json.loads(server)
                except ValueError:
                    raise AirCloudError("Invalid cloud clock") from None
            timestamp = server.get("timestamp2") if isinstance(server, dict) else None
            if not isinstance(timestamp, (str, int)) or not re.fullmatch(r"[0-9]{1,20}", str(timestamp)):
                raise AirCloudError("Invalid cloud clock")
            timestamp, username = str(timestamp), "PHILIPS:" + self._uid
            data = self._check(await _request(self._session, AIR_URL + "enduser/v2/getToken/",
                body={"app_id": APP_ID, "username": username, "timestamp": timestamp},
                headers={"Signature": sign_request(timestamp, username, self._key)}))
            token = data.get("token") if isinstance(data, dict) else None
            if not isinstance(token, str) or not token:
                raise AirCloudError("Air+ token missing")
            expires_at = token_expiry(token)
            if expires_at <= self._clock():
                raise AirCloudError("Air+ issued an expired token")
            self._token, self._expires_at = token, expires_at
            return token

    async def _authenticated(self, path: str, *, body=None):
        token = await self.ensure_token()
        for attempt in range(2):
            try:
                return self._check(await _request(self._session, AIR_URL + path, body=body,
                                                 headers={"Authorization": "jwt " + token}))
            except AirCloudAuthError:
                if attempt:
                    raise
                if self._token == token:
                    self._expires_at = 0
                token = await self.ensure_token()
        raise AirCloudAuthError("Cloud authentication rejected")

    async def devices(self) -> list[dict[str, Any]]:
        data = await self._authenticated("enduser/deviceList/")
        if not isinstance(data, list):
            raise AirCloudError("Unexpected device list")
        for record in data:
            if not isinstance(record, dict) or not isinstance(record.get("device_id"), str) or not IDENTIFIER.fullmatch(record["device_id"]) or not isinstance(record.get("device_info"), dict):
                raise AirCloudError("Invalid device record")
        self._own_ids = {record["device_id"] for record in data}
        return data

    async def connection(self, device_id: str) -> CloudConnection:
        if device_id not in self._own_ids:
            await self.devices()
        if device_id not in self._own_ids:
            raise AirCloudAuthError("Selected purifier is not in this account")
        # Signed URLs are fetched for each connection and are never cached.
        data = await self._authenticated("enduser/v2/mqttInfo/", body={"device_id": [device_id]})
        entries = data.get("mqttinfos") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            raise AirCloudError("MQTT metadata missing")
        matched = [item for item in entries if isinstance(item, dict) and item.get("device_id") == device_id]
        if len(matched) != 1:
            raise AirCloudError("MQTT device metadata missing")
        return parse_connection(matched[0], device_id)
