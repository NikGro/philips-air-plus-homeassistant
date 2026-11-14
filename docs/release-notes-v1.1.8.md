# v1.1.8 — product name and model in the device selection (AC2221)

Follow-up to issue #16. Thanks to **@hencar74**, who named the product and asked for the
model in the device list after testing v1.1.6 on a real device.

## Changed

- The AC2221 (Air+ cloud type `Cobra`) is now named "Philips PureProtect Quiet 2200 Series (AC2221/13)".
  The name comes from the reporter and is not checked against a Philips source.
- In the Air+ cloud setup the device list shows the model instead of the internal cloud
  type: "Livingroom (AC2221/13)" instead of "Livingroom (Cobra)". A device without a model
  falls back to the type. DaConnect and OAuth setups still show the type.

## Tests

- Three new tests: product name, model label with fallback, and unchanged labels for the
  other setup methods. The two relevant ones fail on v1.1.7. 77 HA tests pass.

## Thanks

- **@hencar74**: AC2221 report, real-device tests, confirmation of v1.1.6, product name and
  the model-label suggestion (#16).
- **@autowert66**: DaConnect 403 fix (PR #15, v1.1.7).
- **@Luke2105-Loft59**: long-running AC1715/10 tests, DST and deprecation findings (#5).
- **@vraptunovich**, **@ShorMeneses** and earlier contributors are credited in the README.

## Update

Update Philips Air+ to **v1.1.8** in HACS and restart Home Assistant once. Existing entries
keep their old device name until the device is re-added; new setups use the new name.
