# FLUKE whole-app update gate

## Current design

The in-app updater checks FLUKE GitHub Releases for versions `0.1.2` and later, downloads the matching `FLUKE-<version>-Setup.exe.sha256` sidecar and installer over HTTPS, and keeps the installer only after its size, PE signature, sidecar filename, and SHA-256 agree. Downloads stay under `%LOCALAPPDATA%\FLUKE\Updates\<release-tag>`. Interrupted or cancelled downloads remove `.part` files. The app can install only when it is running from a version directory with a root launcher; old flat installs remain download-only.

## Side-by-side recovery contract

`installer/FLUKE.iss` installs the app payload into `{app}\versions\{#AppVersion}` and writes a completion marker only after the file phase finishes. The root `FLUKE.exe` is a small launcher and is installed only when absent, so later updates do not replace the recovery entrypoint. User SQLite data remains outside the version directories.

The launcher ignores directories without the completion marker, health-checks the candidate with a temporary SQLite database, atomically updates `active.json` only after that check, and records `previousVersion`. If the first real process exits immediately or a later launch fails its health check, the previous ready version is selected. `--rollback` provides a one-step manual switch.

## Evidence gate before claiming release readiness

### Preview.3 evidence boundary

The preview.3 candidate has a successful isolated production-layout install, completion marker, root launcher, `active.json`, matching installed executable hash, and an installed health-check SQLite database with `PRAGMA integrity_check=ok`. The official preview.3 asset was downloaded through the updater helper into an isolated cache, received at the declared size, matched the sidecar SHA-256, passed the Windows PE check, and left no `.part` files. The same downloaded asset was then passed to the real application update bridge and switched the QA root from `0.1.1` to `0.1.2`; a forced termination of a QA Inno process left `active.json` on `0.1.1`, and the external SQLite database remained readable. A deliberately bad candidate also failed first-start health checking without displacing the old ready version.

The implementation uses the side-by-side design above. Preview.3 may expose automatic installation only from that rollback-safe layout; flat `D:\FLUKE` installs remain download-only. For every future build, repeat success, cancellation, disk-full, forced termination during installation, failed first launch, restart, and rollback in an isolated Windows environment. Keep user data outside the versioned program payload and confirm it remains readable after both update and rollback. This preview evidence does not replace real-user-data, default-Windows-GUI, or Stage 7 parallel-observation acceptance.

The release listing now has a bounded official-page fallback: when the unauthenticated GitHub API returns HTTP 403 or 429, the updater reads `releases.atom`, validates each supported tag through GitHub's `expanded_assets` page, and obtains exact asset sizes through official HTTPS `HEAD` requests. It still requires the exact GitHub download path, sidecar filename, SHA-256, PE, and download-size checks before retaining an installer.

The SHA-256 sidecar detects a damaged or mismatched download; because the installer is not Authenticode-signed, it does not independently prove who published the sidecar.
