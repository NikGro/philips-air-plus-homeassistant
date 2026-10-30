# v1.1.4 — token expiry independent of time zone and DST

Follow-up to issue #5 and v1.1.3.

## Fixed

- The token expiry was kept as naive local time (`datetime.now()` and
  `datetime.fromtimestamp()`). When the clocks went back on 25 Oct 2026 a token
  that expired at 01:26:47 UTC (03:26:47 CEST) was still treated as valid for
  another hour, so the integration kept using an expired token and the device
  was unavailable for about 45 minutes (reported by @Luke2105-Loft59).
- Expiry is now an aware UTC datetime everywhere (token refresh, restoring the
  stored expiry in the coordinator, config flow and e-mail login). The stored
  value stays a Unix epoch, so existing config entries need no migration.
- Regression tests simulate the autumn change in the Europe/Berlin time zone.

## Still open

- A signature 401 or `rc=7` after the expiry is not yet turned into an immediate
  forced refresh. With correct expiry handling this should no longer be needed
  for the DST case, but it is not implemented or tested.
- A second `rc=7` right after the retry from v1.1.3 still ends in the 120 s
  cooldown, and one outage without a refresh has an unknown cause.

## Update

Update Philips Air+ to **v1.1.4** in HACS and restart Home Assistant once.
