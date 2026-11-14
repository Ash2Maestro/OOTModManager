# Architecture

```text
Qt Quick UI -> Controller -> BackendClient -> JSON bridge -> manager core
                                                           |
                                                     EngineBackend
                                                           |
                                                        Longshot
```

- `src/ui/qml/`: presentation and interactions. Shared components own the theme
  and layout rules; QML does not operate on game files or assemble shell commands.
- `src/ui/cpp/`: models, settings, translation, assets and asynchronous process
  transport. `ApplicationPaths` resolves application data independently of sources.
- `src/bridge/worker.py`: one JSON request per process; newline-delimited
  `HMBGUI` events. It routes library and installation operations and validates
  their inputs. ZIP content is treated as data, never executable mod scripts.
- `src/core/manager_worker.py`: planning and orchestration. Prepared inputs,
  installed state and tool signatures determine whether work can be reused.
- `src/core/modmanager/`: preparation, signatures, storage, deployment
  transactions and build snapshots. Native changes use ownership checks and
  rollback; base RomFS, saves and game preferences are preserved.
- `src/core/modmanager/engines/`: compiler and runtime conventions behind a typed
  contract. Longshot is the only supported implementation.

Native Addons require verified preparation and may require compilation. Resource
overlays do not. A cached identical native build can be restored without invoking
the compiler. Supporting an engine does not imply every mod is compatible.

The source-path lookup is a separate read-only background request. Its response
must match the current installation and previous source value before prefill is
accepted, so a delayed result cannot replace a newer manual edit.

See [engine contracts](engine-backends.md), [storage](filesystem.md) and
[coding conventions](coding-style.md). Tests exercise both the real Longshot
conventions and a test-only alternate backend to verify the boundary.
