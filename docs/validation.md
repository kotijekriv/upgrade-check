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

## Native release-package check — October 9, 2026

QGIS 3.44.15 on macOS arm64, new isolated profile:

- Installed the final ZIP through the native **Install from ZIP** dialog; all seven installed files matched the package.
- Opened the addon from the Plugins menu and fetched live current/target indexes.
- Produced eight rows: four bundled components, this addon, and three explicitly labelled synthetic metadata-only fixtures. The fixtures were disabled and never imported.
- Exported the HTML report through the native Save dialog and checked its eight rows and escaped contents.
- Passed the 18 portable core tests. The initial public CI passed on Linux, Windows and macOS; those are core/package checks, not additional QGIS host tests.

Installable ZIP SHA-256: `5072a288e923f3399d7b2305e3f420fa973d32fab22042f4a0cb56d60ecb0043`.

The October 9 fixture profile is separate from the historical October 4 screenshot and samples. No user data or private projects were used.
