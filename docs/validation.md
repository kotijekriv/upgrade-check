# Validation scope

The portable test suite covers comparison and report behavior. CI runs it on Linux, macOS and Windows; those jobs do not run the QGIS interface.

## Historical native check — October 4, 2026

QGIS **3.44.15-Solothurn**, macOS arm64, dedicated test profile:

- Installed the addon using QGIS's **Install from ZIP**.
- Fetched the live official plugin indexes and produced a report.
- Saved HTML and JSON through the native interface.
- Checked current-profile inventory, target changes clearing old results, input rejection, failed requests, cancellation and an immediately triggered timeout callback.
- Verified that installed plugin metadata was not modified.

The demo screenshot and example reports in this repository come from that session. The profile contained four official third-party packages, this addon, bundled components and a deliberately seeded missing reference. This is test data, not a user's private profile.

## Limits

Windows and Linux QGIS hosts and the QGIS 4 interface are untested. No plugin in the report was executed under its target version. No measured time saving, customer result or successful outside use is claimed. A passing comparison test does not prove migration safety.

The final downloaded release package receives a separate installation and export check before release handoff; its result is recorded here once completed.
