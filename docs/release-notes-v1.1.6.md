# v1.1.6 — Air+ cloud: AC2221 support, no blocking TLS call, allergen statistics

Follow-up to issue #16 (thanks @hencar74).

## Added

- **AC2221/13** (Air+ cloud type `Cobra`) is accepted by the Air+ cloud setup and
  uses the existing Unicorn register mapping. This was reported working on a
  real AC2221/13 (setup, sensors, on/off and all presets); I did not test it on
  a device. Cloud type and model are now matched as a pair, so `Cobra` is not
  accepted with an AC3220/AC3221 model or `Unicorn` with an AC2221.
- The device name is now per model: "Philips PureProtect 3200i (model)" for
  AC3220/AC3221 and "Philips Air Purifier (model)" for AC2221. The generic name
  is a placeholder until the exact Philips product name is confirmed.

## Fixed

- Home Assistant warned about a blocking call (`load_default_certs`) in the event
  loop when the MQTT connection was created. The SSL context is now built once
  in an executor and reused. Verified by a test that fails on the old code; I
  did not check the warning in a live Home Assistant.
- The allergen index sensor now has `state_class: measurement`, so Home Assistant
  draws a graph and records long-term statistics instead of a timeline.

## Known behaviour

- On the AC2221/13, preset Speed5 reports fan level 18 (the same as Turbo) and
  Medium reports 3. The `fan_level` sensor is ambiguous for Speed5; the preset
  itself is unambiguous. Documented in the README, not changed.

## Update

Update Philips Air+ to **v1.1.6** in HACS and restart Home Assistant once.
AC2221 users: remove nothing, add the device again through *Air+ cloud: email +
verification code*.
