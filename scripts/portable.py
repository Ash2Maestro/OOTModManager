"""Assemble a relocatable Windows runtime from the build Python, without a venv.

Only the standard library and locked preparation dependencies are bundled. The
compiler and its Python remain external, supplied by the user's Longshot tools.
"""
from pathlib import Path
import json
import shutil
import subprocess
import zipfile


def assemble(root, destination, python):
    probe = subprocess.check_output([str(python), "-I", "-c",
        "import sys,json,site;print(json.dumps([sys.base_prefix,site.getsitepackages(),sys.version_info[:2]]))"], text=True)
    base, sites, version = json.loads(probe)
    if version != [3, 10]:
        raise ValueError("Portable runtime requires the locked CPython 3.10 x64 environment")
    base = Path(base)
    runtime = destination / "runtime"
    runtime.mkdir(parents=True)
    for name in ("python.exe", "python3.dll", "python310.dll", "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt"):
        if (base / name).is_file():
            shutil.copy2(base / name, runtime / name)
    for path in (base / "DLLs").iterdir():
        if path.suffix.lower() in (".dll", ".pyd") and "tkinter" not in path.name and not path.name.startswith(("tcl", "tk", "_test")):
            shutil.copy2(path, runtime / path.name)
    excluded = {"site-packages", "test", "tests", "__pycache__", "tkinter", "idlelib", "turtledemo", "ensurepip", "venv"}
    with zipfile.ZipFile(runtime / "python310.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((base / "Lib").rglob("*.py")):
            relative = path.relative_to(base / "Lib")
            if not excluded.intersection(relative.parts):
                archive.write(path, relative.as_posix())
    packages = runtime / "site-packages"
    packages.mkdir()
    dependencies = ("bsdiff4", "lz4", "PIL", "zstandard")
    for name in dependencies:
        source = next((Path(site) / name for site in sites if (Path(site) / name).is_dir()), None)
        if source is None:
            raise ValueError("Missing preparation dependency: " + name)
        shutil.copytree(source, packages / name, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    # Include wheel metadata, licenses and any vendored binary libraries.
    for site in sites:
        for path in Path(site).iterdir():
            if path.name.startswith(("bsdiff4-", "lz4-", "pillow-", "pillow.", "zstandard-", "zbic")):
                if path.is_dir():
                    shutil.copytree(path, packages / path.name, dirs_exist_ok=True)
                elif path.suffix == ".pyd":
                    shutil.copy2(path, packages / path.name)
    (runtime / "python310._pth").write_text(
        "python310.zip\n.\nsite-packages\n../src/core\n../src/bridge\n", encoding="ascii")
    engine = destination / "src/core"
    engine.mkdir(parents=True)
    source = root / "src/core"
    for folder in ("modmanager", "adapters"):
        shutil.copytree(source / folder, engine / folder,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for path in source.iterdir():
        if path.suffix == ".py" or path.name in ("LICENSE", "requirements.txt"):
            shutil.copy2(path, engine / path.name)
    subprocess.run([str(runtime / "python.exe"), "-I", "-B", "-c",
        "import bsdiff4,lz4.block,zstandard,zbic,PIL.Image,modmanager.pipeline,manager_worker; print('Portable engine imports OK')"], check=True)
    (destination / "portable.flag").write_text("", encoding="ascii")
