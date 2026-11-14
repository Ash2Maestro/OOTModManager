"""Read and migrate verified manager-owned preparations without modifying them."""
import json
from pathlib import Path
from .storage import no_links, inventory

REPORT = "hmb-report.json"


def normalize_report(report: dict) -> dict:
    """Read existing Longshot preparations without invalidating guest inventories.

    Only metadata keys change. Disk state is written by the normal successful
    operation, never by inspection. Hookshot preparations are not adopted.
    """
    result = dict(report)
    if "longshot" in result:
        result.setdefault("tools_path", result.pop("longshot"))
        result.setdefault("engine", "longshot")
    if "preserve_longshot_settings" in result:
        result.setdefault("preserve_runtime_settings", result.pop("preserve_longshot_settings"))
    return result


def load_prepared(workspace: Path) -> dict:
    no_links(workspace)
    report = normalize_report(json.loads((workspace / REPORT).read_text(encoding="utf-8")))
    if report.get("schema") != 1 or report.get("status") != "prepared":
        raise ValueError("Preparation absente ou incomplete")
    if Path(report["workspace"]).resolve() != workspace.resolve():
        raise ValueError("Le dossier prepare a ete deplace ; refaire la preparation pour garder des chemins coherents")
    for part, expected in report["inventory"].items():
        if part not in ("prepared", "addon") or inventory(workspace / part) != expected:
            raise ValueError("Les fichiers prepares ont change : %s" % part)
    return report
