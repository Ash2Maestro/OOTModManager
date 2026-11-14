"""Audit a prepared Addon through its explicitly selected recompilation engine."""
import argparse
from pathlib import Path
import sys

from modmanager.engines import engine_for_report
from modmanager.pipeline import load_prepared


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--tools", type=Path)
    args = parser.parse_args()
    try:
        workspace = args.workspace.resolve()
        report = load_prepared(workspace)
        tools = (args.tools or Path(report["tools_path"])).resolve()
        engine_for_report(report).audit_preparation(workspace, tools, report)
        return 0
    except (ValueError, OSError, ImportError) as error:
        print("Audit refuse : %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
