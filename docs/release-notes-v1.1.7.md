# v1.1.7 — DaConnect works again (User-Agent rejected with HTTP 403)

Thanks to **@autowert66** for finding the cause, reproducing it from two networks
and sending the fix in PR #15.

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
