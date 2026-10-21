# Token refresh must not reload the entry (unreleased)

## Scope and baseline

Development-branch fix for issue #5, based on the v1.1.1 commit `45c68df`
on `origin/master`. The manifest version remains 1.1.1; identify test builds by
branch and commit, not by the version displayed in Home Assistant. No versioned
release or deployment to a production installation is implied.

## Reproduction

Regression tests use real Home Assistant ConfigEntry update dispatch and a real
DaConnect coordinator. Cloud/network I/O, platform forwarding and the actual
reload operation are replaced with test doubles. With the original v1.1.1
listener, 50 forced token refreshes generated 50 unwanted reload calls.
Seven of the initial nine regression cases failed; two genuine-options-change
control cases passed. Queued options plus token notifications caused two reloads
for one options change.

## Change

Each loaded entry now has its own captured options snapshot. Pure data updates,
including renewed tokens and expiry timestamps, do not reload the entry. A real
options change updates the snapshot before awaiting reload, preventing queued
token notifications from duplicating that reload. The listener still registers
before disabled-entry early returns and is removed through async_on_unload.
Explicit re-authentication reloads in config_flow.py are unchanged.

## Verification

- Home Assistant 2026.10.1, Python 3.14, Paho 2.1.0: 44 HA/protocol tests passed.
- Home Assistant 2026.10.2, Python 3.14, Paho 2.1.0: 44 HA/protocol tests passed.
- Ten new regression cases cover 50 token refreshes through actual entry
  notifications; OAuth/cloud and MQTT enabled/disabled data-only updates;
  MQTT options changes in either direction; queued notifications; listener
  cleanup/re-registration; and a token callback during transport shutdown.
- The 50-cycle test verifies token persistence, MQTT credential-update calls,
  coordinator identity and zero reload calls; its MQTT transport is mocked.
- Existing real-Paho loopback/lifecycle tests are included in the full suite.
- HA HTTP application inheritance and the intentional Paho v1 API control test
  produce two deprecation warnings, not failures.

Run from the repository root with matching dependencies installed:

```sh
python -m pytest -q ha_tests
python -m unittest discover -s tests -v
python -m compileall -q custom_components ha_tests
```

## Still unverified

No real purifier was controlled, and no production Home Assistant installation
was modified. This demonstrates and fixes the reload trigger, not every reported
availability gap. A real-device observation across token renewals is still needed;
the reported 79-second outlier is not explained by these tests.
