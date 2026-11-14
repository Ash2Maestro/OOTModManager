"""Explicit, resumable migration of existing snapshots; never modifies the game."""
import argparse
import json
from pathlib import Path

from modmanager.build_cache import migrate_cache


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--limit-mib", type=int, default=2048)
    args = parser.parse_args()
    result = migrate_cache(args.cache, args.limit_mib * 1024**2,
                           progress=lambda key: print("Build vérifié et migré : " + key[:12], flush=True))
    print(json.dumps(result), flush=True)
