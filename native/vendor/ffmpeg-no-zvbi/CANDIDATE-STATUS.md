# FLUKE FFmpeg no-libzvbi candidate

Built from FFmpeg commit `51c4a23d74` as an LGPL shared Windows x64 build. `libzvbi`, GPL, nonfree, and autodetection are disabled. The candidate packages only the verified FFmpeg executables, their PE dependency closure, exact source archives/manifests, and license notices.

Validation evidence: `validation/synthetic-adapter-report.json`; complete config, encoder and muxer records are included. Windows system DLL imports are supplied by Windows. The GCC 16.2 source-only archive is intentionally fetched into the ignored local build cache by `native/scripts/prepare-converter-engines.ps1` because the archive exceeds GitHub's 100 MB blob limit; the pinned URL and SHA-256 are recorded in `source-manifest.json` and verified before packaging.
