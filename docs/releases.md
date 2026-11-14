# Release pipeline

## GitHub releases

Push the workflow and code to `main` once. On GitHub, open **Actions → Create
release → Run workflow** and select the branch to release. The version comes from
that commit's `VERSION.txt`; increase it before creating another release.

By default the workflow creates a **draft**. Review it under **Releases** and
click **Publish release** when ready. To publish immediately after validation,
enable the **publish** checkbox when starting the workflow.

GitHub provisions a Windows runner, downloads pinned dependencies, caches the Qt
SDK, and runs the same packaging checks used locally. UI qualification uses an
offscreen window and the Direct3D software renderer; it is not skipped. No game,
Longshot tools or personal cache is needed. Optional loader integration tests are
skipped when the external compiler is unavailable.

Only validated ZIPs reach the publishing job. It verifies their checksums and
creates a draft before uploading; direct publication happens after uploads
succeed. The tag targets the exact selected commit. Existing tags and drafts are
rejected instead of overwritten. A failed publication may leave a draft to review;
remove an incomplete draft and its tag, if present, before retrying that version.

The workflow uses GitHub's temporary token: read-only in the build job and
`contents: write` only in the release job. No personal token or account password is
required. Concurrent runs are serialized. Logs and validated artifacts are also
retained in the Actions run for seven days. A build failure creates no release.

## Local packaging

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
Local packaging performs no upload, Git tagging or signing.

Publish the Windows ZIP, corresponding source ZIP and `SHA256SUMS.txt` together.
The user extracts the complete Windows ZIP and runs `OOTModManager.exe` from a
writable folder. During updates, close the program, replace its program files,
and retain its `data/` folder.

The build is unsigned; hashes verify integrity, not publisher identity. Theme
redistribution restrictions are described in [third-party resources](third-party.md).
