# v1.1.9 — PureProtect 3200 Series (AC3210/12)

Follow-up to issue #21. Thanks to **@anschuetz**, who reported the AC3210/12, found the
one-line cause and tested the change on a real device.

## Added

- The PureProtect 3200 Series (AC3210/12, Air+ cloud type `Unicorn`) can now be added with
  **Air+ cloud: email + verification code**. Before, setup stopped with `unsupported_model`.
  It uses the same register mapping as the 3200i.
- The device is named "Philips PureProtect 3200 Series (AC3210/12)". The 3200i models
  (AC3220, AC3221) keep their name. The name comes from the reporter and is not checked
  against a Philips source.

## Verification

- According to the reporter, v1.1.8 with this prefix added locally paired normally, sensor
  values matched the display, and power and the Auto/Sleep presets worked, with no errors in
  the log. Other AC3210 variants are not tested.
- Tests: the AC3210/12 + Unicorn pair is accepted and named; AC3210/12 with another cloud
  type and unknown 3200 prefixes are still rejected. The AC3210 tests fail on v1.1.8.
  80 HA tests pass.

## Thanks

- **@anschuetz**: AC3210/12 report, local test on a real device and the suggested change (#21).
- **@hencar74**: AC2221 report and tests (#16, v1.1.8).
- **@autowert66**: DaConnect 403 fix (PR #15, v1.1.7).
- **@Luke2105-Loft59**: long-running AC1715/10 tests, DST and deprecation findings (#5).
- **@vraptunovich**, **@ShorMeneses** and earlier contributors are credited in the README.

## Update

Update Philips Air+ to **v1.1.9** in HACS and restart Home Assistant once. Existing entries
are unchanged; add the AC3210 again via the Air+ cloud setup.
