# Third-party components

The manager's code is licensed under the root `LICENSE`. Source releases include
the C++/QML UI, Python core, JSON bridge, tests and build scripts.

- **Qt 6.8.3**, dynamically linked: license texts are in `licenses/`.
  Corresponding upstream sources:
  https://download.qt.io/archive/qt/6.8/6.8.3/single/
  Compatible DLLs and plugins can be replaced alongside the executable.
- **CPython 3.10**: runtime notices are included as `runtime/LICENSE.txt`.
  Reference sources: https://www.python.org/downloads/release/python-31011/
- **bsdiff4, lz4, Pillow, zstandard and zbic**: locked preparation versions are
  listed in `src/core/requirements.txt`. Their wheel metadata and licenses are
  retained under `runtime/site-packages/` in the portable package.
- **Visual C++ runtime**: redistributable DLLs from the build machine's Visual
  Studio installation are deployed app-locally.
- **Trusted Addon installer**: provenance and license are retained in
  `src/bridge/trusted/`; archive-provided installer scripts are never executed.

The Longshot toolchain, NVIDIA SDK, game dump and mods are not included.
The current theme contains game-derived images and fonts in `assets/`. These
resources are not licensed under the manager's code license. Their inclusion
does not grant redistribution rights. Resolve those rights or replace them with
redistributable resources before publishing the repository or a binary release.
