# OOTModManager

A Windows mod manager for **Ocarina of Time Remake**, currently supporting the
[Longshot](https://git.magicbean.dev/MagicBeanDev/Longshot) recompilation engine.
The interface uses C++20 and Qt Quick; a private Python backend handles mod
preparation, validation and installation.

## Using the application

Download the Windows ZIP from the repository's Releases page, extract the entire
archive into a writable folder, and run **OOTModManager.exe**. Qt, Python and the
required application runtimes are included.

1. Select your existing Longshot game installation in Settings.
2. Select the matching **LongshotBuilder/tools** directory. The original NUP is
   filled in automatically when Longshot records an existing source; otherwise,
   choose it manually.
3. Import or drag and drop an **Addon ZIP**, select its entry, and install it.

The manager uses one game installation and reuses compatible builds instead of
compiling everything for every change. Removing an entry from the library and
uninstalling it from the game are separate operations. Individual removal and
restoring vanilla are available. Game settings and saves are preserved.

Longshot is the only supported engine. Mod compatibility is validated against the
supported formats and code paths; arbitrary mods are not guaranteed to work.
The game, original NUP, Longshot toolchain and mods are **not** distributed here.

## Building from source

Prerequisites:

- Windows x64.
- Visual Studio with **Desktop development with C++**, MSVC and a Windows SDK.
- **Python 3.10 x64**, available as `python` on PATH.

```powershell
git clone <repository-url> OOTModManager
cd OOTModManager
.\Build.cmd -Setup
.\Launch.cmd
```

`Build.cmd -Setup` creates local Python environments, installs pinned dependencies,
downloads Qt 6.8.3, then builds and runs the C++ tests. Subsequent builds only need
`Build.cmd`. Dependency downloads require an internet connection; `.tools/` is
local and is never committed. `Launch.cmd -Demo` opens a read-only demonstration.

Run the Python tests with:

```powershell
.\.tools\engine-python\Scripts\python.exe -B scripts/test.py
```

Set `LONGSHOT_TOOLS` to an installed `LongshotBuilder/tools` directory to enable
the optional loader integration tests. Tests use synthetic binaries and temporary
data, not your game. `Format.cmd` formats the maintained C++ and QML files.

## Creating a release

On GitHub, use **Actions → Create release → Run workflow**. The workflow builds
and tests the selected commit, then creates a draft release with the ZIPs and
checksums. Enable **publish** to publish immediately after validation. Set a new
version in `VERSION.txt` and push it before releasing; existing versions are not
overwritten. No personal token is required.

For local packaging, update `VERSION.txt`, then double-click **Release.cmd**. It runs the tests, builds
the application, packages its dependencies and theme, and checks the extracted
program from a different directory in both interface languages.

On success, it opens a new directory under `releases/` containing the Windows ZIP,
matching source ZIP and `SHA256SUMS.txt`. Publish these files together as a GitHub
Release. This command does not upload files or create Git tags. Existing releases
are never overwritten. See [release details](docs/releases.md).

## Repository layout

| Path | Purpose |
| --- | --- |
| `src/ui/` | Native C++ controller and QML interface |
| `src/bridge/` | JSON protocol and Addon ZIP library |
| `src/core/` | Preparation, transactions, caches and engine backends |
| `tests/` | C++, bridge and core tests |
| `assets/`, `i18n/`, `licenses/` | Theme, translations and dependency notices |
| `scripts/`, `docs/` | Development tools and technical documentation |
| `.tools/` | Downloaded SDKs and development dependencies; ignored |
| `.local/` | Local settings, library, preparations, caches and logs; ignored |
| `build/`, `dist/`, `releases/` | Generated application builds and packages; ignored |

A source checkout keeps development data in `.local/`. The portable application
keeps user data in `data/` next to its executable. Neither is part of the source
repository or release payload. See [storage](docs/filesystem.md) and
[architecture](docs/architecture.md).

## License and third-party resources

The manager's code is licensed under [GPL-3.0](LICENSE). Dependency notices and
source references are documented in [third-party resources](docs/third-party.md).
The current theme includes game-derived images and fonts, which are not covered
by the code license. Their redistribution rights must be resolved before public
distribution, or they must be replaced with redistributable assets.
