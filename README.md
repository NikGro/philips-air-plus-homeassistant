# Philips Air+ Home Assistant Integration

> **Vibe-coded community project:** this fork is developed largely with AI
> assistance and has not been broadly tested on real hardware. Expect rough
> edges, back up your Home Assistant configuration and report problems with
> redacted logs. The new PureProtect cloud backend has automated tests and a
> verified read-only cloud connection; full control and long-term operation
> still need validation in a real Home Assistant installation.

Fork of [ShorMeneses/philips-airplus-homeassistant](https://github.com/ShorMeneses/philips-airplus-homeassistant),
with additional device support and a separate Air+ cloud connection for
**PureProtect 3200i (AC3220/10 / AC3221)**.

## Why two connection paths?

| Device | Setup option | Implementation |
| --- | --- | --- |
| AC1715/10, AC1715/11, AC1715/70, AC0650/10, AC0651/10 | **DaConnect: email + verification code (older devices)** | Original cloud/MQTT backend and mappings in `models.yaml` |
| PureProtect 3200i, reported as AC3220/10 / Unicorn | **Air+ cloud: email + verification code (recommended)** | Separate Air+ API, automatic token renewal and AWS MQTT shadows |

Adding a model to `models.yaml` is enough when discovery and the original MQTT
protocol already work. **AC1715/10** is such a case: its mapping matches the
upstream AC1715/11 configuration. **[@vraptunovich](https://github.com/vraptunovich) contributed this support in
[PR #1](https://github.com/NikGro/philips-air-plus-homeassistant/pull/1)** and
reported successful fan and sensor tests on a real device.

The PureProtect was absent from the original device registry, so a model entry
alone could not connect it. It needed a different login/token flow, device list,
MQTT credentials and message protocol. Both paths still use a simple email-code
setup; no packet capture, PC app or DevTools is required for email login.

## Install or update

1. Add `https://github.com/NikGro/philips-air-plus-homeassistant` in HACS as a
   custom repository, category **Integration**.
2. Install/update **Philips Air+** to [v1.1.1](https://github.com/NikGro/philips-air-plus-homeassistant/releases/tag/v1.1.1)
   and restart Home Assistant.
3. Open **Settings → Devices & services → Add integration → Philips Air+**.
4. Choose the device-specific option above, enter your Philips account email
   and its six-digit verification code, then select the linked purifier.

**Existing AC1715/10 entries:** keep the old email-login entry; updating and
restarting should load the added mapping. **Unsuccessful PureProtect entries
from v1.0.x:** remove that entry and add it again through **Air+ cloud**.
Existing entries retain their original backend when updated. OAuth PKCE remains
available as an advanced legacy alternative.

For manual installation, copy `custom_components/philips_airplus` into your
HA configuration's `custom_components` directory and restart. The purifier must
already be linked to the same account in the official app.

## Features and limits

Fan on/off and preset modes, PM2.5, fan level and filter-life sensors; allergen
index where supported. The new Air+ backend obtains fresh signed credentials on
reconnect and displays reported device state rather than assuming a command was
executed. Filter resets and standby monitoring are not exposed for Unicorn until
their commands are verified; legacy devices retain their configured features.

Air+ setup retrieves a signing value from a pinned, SHA-256-verified research
reference and stores it with the account identifier in the local HA config entry.
GitHub raw content must be reachable during setup; runtime uses Philips/Gigya
HTTPS and regional AWS IoT on port 443. This backend keeps JWTs and signed URLs
in memory. Treat configuration backups as account-sensitive.

## Testing and troubleshooting

For **AC1715/10**, use **DaConnect**, then check fan/preset controls and compare
sensor values with the official app. The new Air+ option currently supports
Unicorn AC32xx devices; an unsupported-model result there does not disprove the
AC1715 mapping. Filter resets are not needed for testing.

When reporting a problem, include the integration/HA versions, selected setup
option, exact error, and whether the device is missing from discovery, has no
entities, or has incorrect/unavailable values. For a short reproduction, set these
loggers to `debug` via **Developer tools → Actions → `logger.set_level`**, reload
and reproduce once, then restore `info`:

```yaml
action: logger.set_level
data:
  custom_components.philips_airplus.model_manager: debug
  custom_components.philips_airplus.coordinator: debug
  custom_components.philips_airplus.mqtt_client: debug
```

Useful excerpts include model identification (`ctn`), connection/entity errors
and relevant Config/Status/filter-port properties before/after one power or mode
change. **Redact account/device IDs, emails, serials, MAC/IP values, tokens,
Authorization/Signature headers, client IDs and signed URL queries.** Keep model
names, property keys and sensor/mode values.

See [AC1715/10 feedback and test instructions](https://github.com/NikGro/philips-air-plus-homeassistant/issues/2)
and [PureProtect research/read-only diagnostics](docs/ac3221-cloud-investigation.md).
The exact Google Home server interface and a firmware download are not established.

## Development and credits

CI runs 34 protocol/integration tests with Home Assistant 2026.10.1 and 10 offline
diagnostic tests, plus the PowerShell self-test. DaConnect regressions include
real Paho threads connected only to a loopback MQTT fixture; other tests use
synthetic identifiers and mock transports. They do not control a real purifier.
See [v1.1.1 lifecycle fixes and testing instructions](docs/release-notes-v1.1.1.md).

Thanks to **@ShorMeneses** for the original integration, **@vraptunovich** for
AC1715/10 support, @vkostakos, @markusstephany, @rgpublic and @renaudallard for
prior contributions. The new login also uses research from
[kwesolowski/node-red-contrib-philips-airplus](https://github.com/kwesolowski/node-red-contrib-philips-airplus).
See [third-party notices](tools/THIRD_PARTY_NOTICE.md) and [LICENSE](LICENSE).
