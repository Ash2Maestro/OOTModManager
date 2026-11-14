"""Explicit DLSS configuration, verified SDK inputs and isolated build environment."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path


def default_sdk():
    return str(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LongshotLauncher/ngx-sdk")


def prepare_options(settings, tools, python, run, read_only=False):
    if not settings.dlss:
        return {"dlss": False}
    if not settings.dlss_license:
        raise ValueError("Acceptez la licence NVIDIA dans les paramètres avant d'activer le DLSS.")
    from ..storage import digest, no_links
    script = Path(tools) / "scripts/ngx_sdk.py"
    if not script.is_file():
        raise ValueError("Ces outils Longshot ne prennent pas en charge l'installation du SDK DLSS.")
    spec = importlib.util.spec_from_file_location("hmb_ngx_sdk", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sdk = Path(settings.ngx_sdk or default_sdk()).resolve()
    no_links(sdk)
    platform = "windows" if os.name == "nt" else "linux"
    files = module.files(platform)
    def valid():
        for _, expected, relative in files:
            path = sdk / relative
            no_links(path)
            if not path.is_file() or digest(path) != expected:
                return False
        return True
    if not valid():
        if read_only:
            raise ValueError("Le SDK DLSS doit être téléchargé ou réparé avant la compilation.")
        run([python, "-I", "-B", str(script), "--accept-nvidia-license", "--platform", platform, str(sdk)])
        if not valid():
            raise ValueError("Le SDK DLSS téléchargé ne correspond pas aux empreintes attendues.")
    # Paths and license UI state are not compiler inputs. SDK content is.
    fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    runtimes = {Path(relative).name: expected for _, expected, relative in files
                if relative.startswith("runtime/")}
    return {"dlss": True, "sdk_fingerprint": fingerprint, "runtimes": runtimes}


def runtime_matches(report, game):
    options = report.get("build_options", {})
    if not options.get("dlss"):
        return True
    from ..storage import digest, no_links
    runtimes = options.get("runtimes", {})
    if not runtimes:
        return False
    for name, expected in runtimes.items():
        if Path(name).name != name:
            return False
        path = Path(game) / "ngx" / name
        no_links(path)
        if not path.is_file() or digest(path) != expected:
            return False
    return True


def environment(report):
    if not report.get("build_options", {}).get("dlss"):
        return {}
    if not report.get("nvidia_license_accepted") or not report.get("ngx_sdk"):
        raise ValueError("Configuration DLSS incomplète ou licence non acceptée.")
    return {"LONGSHOT_NGX_SDK": report["ngx_sdk"]}
