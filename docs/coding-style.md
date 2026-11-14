# Coding conventions

- C++20: follow `.clang-format`; classes use PascalCase, methods camelCase and
  private members the `m_` prefix. Keep UI state changes in the controller and
  transport details in `BackendClient`.
- QML: format with the bundled `qmlformat`. Reuse themed components instead of
  duplicating visuals, dimensions or interaction rules across pages.
- Python 3.10: use descriptive snake_case names, type annotations at module
  boundaries and small functions with explicit inputs. Imports must not trigger
  installations, extraction, network requests or game writes.
- File operations: resolve and validate targets, reject links where required,
  use atomic metadata writes, and preserve ownership and rollback invariants.
- Processes: pass argument lists, not shell-generated command strings. Keep
  compiler work and disk-heavy operations off the UI thread.
- Engine conventions belong in a backend; shared orchestration must not import
  a concrete engine implementation. Backends are trusted bundled code.
- Tests should verify behavior and failure boundaries with temporary data.
  Do not use proprietary game files or user saves as test fixtures.

Run `Format.cmd`, the Python suite and the relevant C++ tests before submitting
a change. Keep generated files, local settings, game data and caches out of Git.
