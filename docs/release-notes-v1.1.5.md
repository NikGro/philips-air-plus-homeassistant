# v1.1.5 — remove deprecated Home Assistant constant

## Fixed

- Home Assistant warned that `CONCENTRATION_MICROGRAMS_PER_CUBIC_METER` is
  deprecated and will be removed in Home Assistant Core 2027.8. The PM2.5 sensor
  now uses `UnitOfDensity.MICROGRAMS_PER_CUBIC_METER`, with a fallback for older
  Home Assistant versions that do not have `UnitOfDensity`. The unit is
  unchanged (`µg/m³`), so history and statistics are unaffected. Reported by
  @Luke2105-Loft59.

## Still open

- Nothing new. See the v1.1.4 notes for the remaining open points.

## Update

Update Philips Air+ to **v1.1.5** in HACS and restart Home Assistant once.
