# Storage layout

All development files live under the repository root. Generated and private
content is excluded through `.gitignore` and the packaging allowlist.

| Directory | Contents |
| --- | --- |
| `.tools/` | Qt SDK and development Python environments |
| `build/` | CMake outputs, test binaries and release logs |
| `dist/` | Optional deployed runtime for local development |
| `releases/` | Completed, validated release artifacts |
| `.local/` | Development application data |

## Application data

The UI resolves data paths in this order: explicit `--data`, portable marker
(`portable.flag`: `data/`), optional local `development.json` override, source
checkout (`.local/`), then Windows `%LOCALAPPDATA%/OOTModManager`.
No override file is needed for a normal clone. The Python worker receives the
selected root explicitly and passes it to children through `MOD_MANAGER_DATA`.

Within a data directory:

| Path | Purpose |
| --- | --- |
| `settings.json` | Manager preferences and selected paths |
| `library/` | Imported immutable packages and their catalog |
| `workspaces/<engine>/` | Verified preparations, inventories and reports |
| `cache/native-builds/<engine>/` | Compressed, deduplicated native build snapshots |
| `cache/compilation/<engine>/` | Compiler translation and object caches |
| `cache/downloads/` | Temporary update downloads |
| `logs/` | Diagnostic logs |

The library and preparations are persistent data, not disposable caches. Deleting
a cache loses its acceleration. Do not move or remove data during an operation.
Custom library and native-cache directories remain configurable.

This development machine also retains historical files under `.local/archive/`.
They are neither dependencies nor public documentation and are never packaged.
The consolidation journal preserves original metadata and records same-volume
moves; cache payloads were not copied or rebuilt.
