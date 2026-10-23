# v1.1.2 — token-refresh reload fix and AC1715/11 LED switch

Follow-up to issue #5. It fixes the integration reload that every token refresh
caused. It does **not** claim that the remaining periodic outages are gone.

## Fixed

- Persisting a refreshed token no longer reloads the config entry. In a 48 h
  test by @Luke2105-Loft59 a single instance ran without reload while the
  connection generation advanced about 70 times (#7).

## Added

- LED switch for **AC1715/11** using the captured properties D03104 (on, value
  100) and D03105 (off, value 0), with an on/off icon and de/en/fr names
  (#8 by @Neubda, tests and translations in #10).
- The LED is **not** enabled for other models. Only AC1715/11 has captured
  traffic; whether D03104/D03105 are identical elsewhere is unverified. Owners
  of other models are welcome to report the values their LED button produces.

## Still open

- Luke's test showed 9 outages of about 2 minutes, 8 of them at a token refresh
  (`rc=7`, then the 120 s reconnect cooldown). PR #9 (bounded cooldown and one
  retry during a refresh) is **not part of this release** and awaits a real-world
  test.
- One outage without a refresh has a separate, unknown cause.

## Update

Update Philips Air+ to **v1.1.2** in HACS and restart Home Assistant once. No
configuration migration is needed. AC1715/11 owners find the new switch among
the device controls.
