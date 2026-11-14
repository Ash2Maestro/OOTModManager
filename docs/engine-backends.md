# Engine backends

`src/core/modmanager/engines/base.py` defines the `EngineBackend` interface and
immutable request/layout dataclasses. The core owns planning, transactions,
library state and the UI protocol; the backend owns compiler/runtime conventions.

The contract covers tool discovery and validation, optional installation source
lookup, command/environment construction, progress parsing, loader audits,
installed-code observation, mod adaptations and cache identity. Methods receive
resolved request objects and callbacks rather than UI objects or global settings.
Commands are argument lists. Unsupported operations must fail explicitly.

Longshot implements these operations in `longshot.py` and focused helper modules.
Its launcher metadata is read-only. Source lookup matches the selected folder,
accepts only a unique existing NUP, and never falls back to an unrelated default
installation or a disk-wide scan.

To add an engine, implement the contract, register it in `_FACTORIES`, declare
only verified capabilities, and test its command, audit, cache and deployment
behavior. `tests/core/test_engine_boundary.py` demonstrates a test-only alternate
layout. A real game build and gameplay qualification are still required before
advertising support. The current preparation format remains specific to OOT
Remake Addons; this is not a universal game/mod format abstraction.
