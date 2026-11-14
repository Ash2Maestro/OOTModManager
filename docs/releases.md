# Release pipeline

Set the public version in `VERSION.txt`, then run `Release.cmd`. For automation
without an interactive pause or folder opening:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Release.ps1 -NoOpen
```

The pipeline runs Python tests, builds Release binaries and runs C++ tests. It
assembles Qt, an app-local Visual C++ runtime, a private Python runtime, the
backend, translations and theme in a fresh staging directory. No source-checkout
data is copied. A manifest records payload sizes and SHA-256 hashes.

It checks archive integrity, extracts the Windows ZIP to a different directory,
then launches the bundled bridge and UI with empty temporary data in both English
and French. Only a fully validated artifact set is promoted to `releases/`.
The current development executable and game installation are not replaced.

Each run has a distinct output directory and a log under `build/release-logs/`.
An OS lock prevents simultaneous release runs and is released on interruption.
A failed check returns a nonzero exit status and does not publish an artifact set.
No upload, Git tag, release note generation from history or signing occurs.

Publish the Windows ZIP, corresponding source ZIP and `SHA256SUMS.txt` together.
The user extracts the complete Windows ZIP and runs `OOTModManager.exe` from a
writable folder. During updates, close the program, replace its program files,
and retain its `data/` folder.

The build is unsigned; hashes verify integrity, not publisher identity. Theme
redistribution restrictions are described in [third-party resources](third-party.md).
