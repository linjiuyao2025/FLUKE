# FLUKE whole-app update gate

## Current design

The in-app updater checks FLUKE GitHub Releases for versions `0.1.2` and later, downloads the matching `FLUKE-<version>-Setup.exe.sha256` sidecar and installer over HTTPS, and keeps the installer only after its size, PE signature, sidecar filename, and SHA-256 agree. Downloads stay under `%LOCALAPPDATA%\FLUKE\Updates\<release-tag>`. Interrupted or cancelled downloads remove `.part` files. The app can install only when it is running from a version directory with a root launcher; old flat installs remain download-only.

## Side-by-side recovery contract

`installer/FLUKE.iss` installs the app payload into `{app}\versions\{#AppVersion}` and writes a completion marker only after the file phase finishes. The root `FLUKE.exe` is a small launcher and is installed only when absent, so later updates do not replace the recovery entrypoint. User SQLite data remains outside the version directories.

The launcher ignores directories without the completion marker, health-checks the candidate with a temporary SQLite database, atomically updates `active.json` only after that check, and records `previousVersion`. If the first real process exits immediately or a later launch fails its health check, the previous ready version is selected. `--rollback` provides a one-step manual switch.

## Evidence gate before claiming release readiness

### Preview.2 evidence boundary

The preview.2 candidate has a successful isolated production-layout install, completion marker, root launcher, `active.json`, matching installed executable hash, and an installed health-check SQLite database with `PRAGMA integrity_check=ok`. Source-focused tests cover cancellation, disk-full, forced termination, failed first launch, restart selection, rollback, and external SQLite preservation. This is not yet evidence of a complete public-asset automatic install/restart/failure-recovery run; keep the automatic-install UI gated until that isolated sequence is independently recorded.

The implementation uses the side-by-side design above. Before enabling the button for a build, verify success, cancellation, disk-full, forced termination during installation, failed first launch, restart, and rollback in an isolated Windows environment. Keep user data outside the versioned program payload and confirm it remains readable after both update and rollback. Do not treat the source tests as proof of installed-app acceptance.

The SHA-256 sidecar detects a damaged or mismatched download; because the installer is not Authenticode-signed, it does not independently prove who published the sidecar.
