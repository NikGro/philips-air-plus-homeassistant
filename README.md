# Philips Air+ Home Assistant Integration

Control Philips purifiers through the cloud, including **PureProtect 3200i
(AC3220/10 / AC3221)** using the Air+ app's device registry and AWS MQTT shadows.
The older Versuni DaConnect backend remains available for existing devices.

> This community fork is developed with AI assistance. The new AC3220/10
> backend is based on captured app traffic and a real read-only cloud shadow.
> Automated tests cover Home Assistant 2026.10.1; full control and long-term
> reconnection still need validation in a user's Home Assistant installation.

## What changed in v1.1.0?

Previous releases queried only DaConnect. A purifier visible in Air+ could
therefore be missing from the Home Assistant device picker. The new default
**Air+ cloud: email + verification code** queries `enduser/deviceList/` instead.
An AC3221 can be reported by this cloud as **AC3220/10**, type **Unicorn**.

The integration now provides:

- Email verification login, automatic cloud-token renewal and device selection.
- Cloud on/off and preset modes: Auto, Sleep, Medium, Turbo and Speed1–Speed5.
- PM2.5, allergen index, fan level, filter-cleaning and replacement-life sensors.
- MQTT reported-state updates with periodic reconciliation.
- Fresh signed MQTT credentials on every reconnect, with retry backoff.
- A cloud connection option that pauses activity and reloads the integration.

For this backend, power uses `D03102`, mode uses `D0310C`, and fan level uses
`D0310D`. Desired-state acknowledgments do not fabricate a physical state change.
Filter reset and standby-monitor commands are not exposed for Unicorn: their
meaning has not been verified. Older DaConnect models retain their existing
features and mappings in `models.yaml`.

## Installation and updating

1. In HACS, add `https://github.com/NikGro/philips-air-plus-homeassistant`
   as a custom repository with category **Integration**, if not already added.
2. Install or update **Philips Air+** to **v1.1.0**.
3. Restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration → Philips Air+**.
5. Choose **Air+ cloud: email + verification code (recommended)**.
6. Enter the account email used in the official Air+ app, then its six-digit
   email verification code. Select the purifier from the list.

**Upgrading an unsuccessful v1.0.x setup:** remove the old, unsuccessful
Philips Air+ configuration entry and add it again using the new **Air+ cloud**
option. Existing entries retain their original authentication/backend; installing
an update alone does not change a DaConnect entry into an Air+ cloud entry.
Keep working entries for older devices. No manual UUID, app installation on the
PC, packet capture or DevTools is needed for the new setup.

For manual installation, copy `custom_components/philips_airplus` into your
Home Assistant configuration's `custom_components` directory and restart.
The purifier must already be linked to the same account in the official Air+ app.

## Supported backends

| Setup option | Devices | Mapping |
| --- | --- | --- |
| Air+ cloud (recommended) | Unicorn AC3220/10 and AC3221 variants | Captured cloud registers in `airmatters_model.py` |
| DaConnect email verification | Older devices linked to the Versuni registry | `models.yaml` |
| OAuth PKCE (advanced) | Legacy Air+ OAuth accounts | `models.yaml` |

The existing DaConnect mappings include AC0650/10, AC0651/10, AC1715/11 and
AC1715/70. AC1715/10 compatibility depends on the model reported by that backend;
adding a mapping alone does not establish discovery or cloud compatibility.
For OAuth, follow the login URL and redirect instructions displayed by the setup
flow. This fallback uses the old registry and will not fix a missing Unicorn.

## Account storage and network requirements

The Air+ setup stores the account identifier and app signing value in the local
Home Assistant config entry. The signing value is loaded once from a pinned,
SHA-256-verified upstream research document; downloaded content is never executed.
The GitHub raw-content host must therefore be reachable during setup. Runtime
requests use Philips/Gigya HTTPS and the regional AWS IoT MQTT broker on port 443.
JWTs and signed MQTT URLs remain in memory and are not written to config entries
or logs. Protect Home Assistant configuration backups as account-sensitive data.

Tokens are renewed without another email code during normal operation. If the
account is rejected or the device is unlinked, Home Assistant requests
reauthentication. Use the original account for that device. A network outage
instead triggers a retry with fresh MQTT credentials.

## Troubleshooting

- **No device in the picker:** verify the selected option is **Air+ cloud**, and
  use the account where the purifier is visible in the official Air+ app.
- **Unsupported model:** the new backend currently supports the Unicorn AC32xx
  models above. Other cloud families need their own confirmed mappings.
- **Unavailable:** check connectivity to Philips and AWS IoT on port 443. The
  integration retries outages; it cannot make a physically disconnected purifier
  reconnect to Wi-Fi.
- **Controls are acknowledged but state stays unchanged:** the integration waits
  for the device's reported state, rather than assuming it obeyed a command.

The read-only Windows diagnostic and research notes remain available in
[the investigation document](docs/ac3221-cloud-investigation.md). Remove account
identifiers, JWTs, signed URLs and captures before sharing diagnostics. The exact
Google Home server-to-server interface and a downloadable firmware image have
not been established; this integration uses the confirmed Air+ app backend.

## Development

Offline diagnostics:

```sh
python -m unittest discover -s tests -v
pwsh -NoProfile -File tools/airplus_windows_probe.ps1 -OfflineSelfTest
```

Home Assistant protocol and integration tests (Python 3.14):

```sh
python -m pip install homeassistant==2026.10.1 paho-mqtt==2.1.0 pytest pytest-asyncio
python -m pytest -q ha_tests
```

Tests use synthetic account identifiers and mock transports; they do not send
commands to a real purifier. CI runs both suites.

## Credits and license

Fork of [ShorMeneses/philips-airplus-homeassistant](https://github.com/ShorMeneses/philips-airplus-homeassistant).
Thanks to the original contributors, including @vkostakos, @markusstephany,
@rgpublic, and @renaudallard for the legacy HomeID email-login work.
The new Air+ login uses the independently documented runtime signing protocol in
[kwesolowski/node-red-contrib-philips-airplus](https://github.com/kwesolowski/node-red-contrib-philips-airplus).
See [third-party notices](tools/THIRD_PARTY_NOTICE.md) and [LICENSE](LICENSE).
