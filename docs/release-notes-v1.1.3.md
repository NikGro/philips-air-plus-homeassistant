# v1.1.3 — shorter reconnect after token refresh

Follow-up to issue #5 and v1.1.2.

## Fixed

- After a token refresh the broker can answer the reconnect with `rc=7`. Until
  now the 120 s reconnect cooldown then kept the device `unavailable` for about
  two minutes. During a credential refresh the cooldown is now 5 s and exactly
  one immediate retry with the fresh credentials is allowed; the normal cooldown
  applies afterwards, so flapping protection is unchanged (#9).

## Field data

Test by @Luke2105-Loft59 with Debug logging, six HA restarts excluded:

- About 60 token refreshes in 48 h, 7 of them followed by `rc=7`. In 6 of 7 the
  5 s retry succeeded and the device never became unavailable. Before the change
  there were about 8 such outages in 48 h.
- Over about 6 days in total: one interruption of about 2 s and one of about
  2 minutes (28.10., no debug log, cause unconfirmed).

## Still open

- A second `rc=7` right after the retry still ends in the 120 s cooldown. A
  second, longer retry step has not been implemented or tested.
- One outage without a refresh has a separate, unknown cause.
- Token expiry is stored as naive local time. Around the autumn DST change
  (25.10.) a token was treated as valid one hour too long, which caused an
  outage of about 45 minutes. This is not fixed in this release.

## Update

Update Philips Air+ to **v1.1.3** in HACS and restart Home Assistant once. No
configuration migration is needed.
