# v1.1.1 — DaConnect MQTT lifecycle fixes

Targets the AC1715/10 availability-flapping investigation in issue #5. This fixes
reproducible connection-management defects; it is **not yet proof** that the
reporter's complete periodic outage is resolved on real hardware.

## Fixed

- Shutdown now actually disconnects and joins the Paho network thread. Cleanup
  still runs after the permanent-shutdown flag is set.
- Retired-client connect, disconnect and message callbacks cannot change the
  current connection or deliver status after shutdown.
- Connect and teardown are serialized. A previous thread is joined before a
  replacement is started; failed teardown retains ownership for cleanup.
- Shutdown interrupts reconnect backoff/cooldown and the connection-result wait.
  Paho automatic reconnect is disabled: the coordinator owns retry policy.
- Credential refreshes are serialized and await teardown off HA's event loop.
- Coordinator unload stops scheduled polling, rejects already-queued callbacks
  and awaits reconnect/transport cleanup. Cancelling one unload caller cannot
  allow another caller to bypass unfinished teardown.
- Local random `instance` labels and connection `generation` numbers help trace
  lifecycle events without exposing the real MQTT client ID in those new lines.

The separate Air+ / Unicorn backend and device mappings are unchanged. No
configuration migration, device reset or filter reset is required.

## Update and test

1. Back up your HA configuration, update Philips Air+ to **v1.1.1** in HACS and
   **restart Home Assistant once**. A reload alone cannot reliably clean up
   threads left behind by the old version. Keep your existing **DaConnect** entry.
2. Check sensor updates and ordinary fan/preset controls. Do not reset filters
   for testing. After normal operation is established, reload the integration
   once or twice and check that updates resume normally.
3. Observe for **at least 2–3 hours, preferably overnight**, including normal
   token renewal. Record whether `unavailable` episodes and rc=7 bursts recur.
4. If needed, enable debug logging for
   `custom_components.philips_airplus.mqtt_client` and
   `custom_components.philips_airplus.coordinator` with `logger.set_level`.
   Capture the transition from stable operation to a failure, then restore info.
5. Report integration/HA versions, restart/reload times, duration of the test,
   availability symptoms and redacted lifecycle/refresh/reconnect excerpts.
   Preserve the new local instance/generation labels and timestamps. Remove
   tokens, signatures, account/device/client IDs, email addresses, serials,
   IP/MAC addresses, Authorization headers and signed URL queries before posting.

`rc=7` means connection lost; it does not by itself prove a duplicate-client-ID
collision. The token-refresh correlation in the original report remains
unconfirmed. Issue #5 stays open for real-installation feedback.

## Automated verification

- 34 HA/protocol tests with HA 2026.10.1 and paho-mqtt 2.1.0, including 18 new
  DaConnect tests; the original defects were demonstrated by failing tests.
- Real loopback Paho coverage exercises repeated wrapper reloads and overlapping
  credential-refresh requests, and verifies old threads are stopped.
- 10 offline diagnostic tests; GitHub Actions also runs the PowerShell self-test.
- The loopback fixture substitutes TCP for production WSS/TLS. It does not test
  Philips authentication, AWS disconnect policy or the physical purifier.

## Rollback

If this introduces a regression, select v1.1.0 through HACS Redownload and restart
HA. No config migration is performed, although the old lifecycle bugs will return.
