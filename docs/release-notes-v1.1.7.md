# v1.1.7 — DaConnect works again (User-Agent rejected with HTTP 403)

## Thanks

- **@autowert66**: found the DaConnect 403, reproduced it from two networks and
  sent the fix in PR #15.
- **@hencar74**: reported and tested the AC2221/13 on a real device (#16, v1.1.6),
  then confirmed the release on Home Assistant 2026.11.0 and named the product
  (Philips PureProtect Quiet 2200 Series).
- **@Luke2105-Loft59**: tested the reconnect fixes for the AC1715/10 over weeks
  with debug logs (#5, v1.1.3 to v1.1.5), and spotted the deprecated PM2.5 constant
  and the daylight-saving token problem.
- **@vraptunovich**, **@ShorMeneses** and earlier contributors are credited in the
  README.

## Fixed

- The DaConnect API (`prod.eu-da.iot.versuni.com`) answers HTTP 403 when the
  `User-Agent` is exactly `okhttp/4.12.0 (Android 14; Pixel 7)`, before it looks at
  the token. Every DaConnect request sent that string, so existing DaConnect
  entries went to `setup_error` ("Failed to initialize authentication") and new
  DaConnect setups failed at device discovery. The integration now sends
  `okhttp/4.12.0`. The reporter confirmed on an AC0651/10 that an existing entry
  recovered after the update and a restart, without logging in again.
- A failed device discovery in the DaConnect e-mail setup now shows
  "Unable to connect to Philips Air+ service" instead of "Unknown error occurred".
- The Air+ cloud path (PureProtect 3200i, AC2221) is not affected; it sends no
  `User-Agent`.

## Tests

- Two new regression tests cover the User-Agent and the setup error. Both fail on
  v1.1.6. The 403 itself depends on the Versuni servers and is not reproduced in
  CI; I did not check it against the live API.

## Update

Update Philips Air+ to **v1.1.7** in HACS and restart Home Assistant once.
DaConnect users with `setup_error` do not need to remove or re-add the device.
