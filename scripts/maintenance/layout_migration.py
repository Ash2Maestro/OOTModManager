"""Journaled, same-volume workspace moves for a development-layout migration.

This maintenance utility never deletes payloads. It is not run at app startup.
Only explicit JSON metadata files may be rewritten; binary/cache contents stay intact.
"""
import json
from pathlib import Path
import os


class LayoutMigration:
    def __init__(self, workspace: Path, journal: Path):
        self.workspace = workspace.resolve()
        self.journal = journal.resolve()
        self._inside(self.journal)
        self.state = json.loads(self.journal.read_text(encoding="utf-8")) if self.journal.exists() else {
            "schema": 1, "moves": [], "metadata": []}

    def _inside(self, path: Path) -> Path:
        resolved = path.resolve()
        if resolved == self.workspace or not resolved.is_relative_to(self.workspace):
            raise ValueError("Migration target outside the workspace: " + str(path))
        return resolved

    def _save(self):
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.journal.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.journal)

    def move(self, source: Path, destination: Path):
        source, destination = self._inside(source), self._inside(destination)
        if source == destination or destination.is_relative_to(source) or source.is_relative_to(destination):
            raise ValueError("Overlapping migration paths")
        if not source.exists():
            if any(row["source"] == str(source) and row["destination"] == str(destination)
                   for row in self.state["moves"]) and destination.exists():
                return
            raise FileNotFoundError(source)
        if destination.exists():
            raise FileExistsError(destination)
        if source.drive.casefold() != destination.drive.casefold():
            raise ValueError("Migration requires a same-volume rename")
        destination.parent.mkdir(parents=True, exist_ok=True)
        row = {"source": str(source), "destination": str(destination), "status": "pending"}
        self.state["moves"].append(row)
        self._save()
        source.rename(destination)
        row["status"] = "moved"
        self._save()

    def rewrite_json(self, path: Path, mappings: list[tuple[Path, Path]], *, external=False, updates=None):
        if not external:
            self._inside(path)
        original = path.read_bytes()
        value = json.loads(original.decode("utf-8-sig"))
        updated = rewrite_paths(value, mappings)
        if updates:
            updated.update(updates)
        if updated == value:
            return
        backup = self.journal.parent / "metadata-before" / (str(len(self.state["metadata"])) + ".json")
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(original)
        row = {"path": str(path), "backup": str(backup), "status": "pending"}
        self.state["metadata"].append(row)
        self._save()
        temporary = path.with_name(path.name + ".layout-migration.tmp")
        temporary.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(path)
        row["status"] = "rewritten"
        self._save()

    def rollback(self):
        """Restore metadata first, then reverse moves without overwriting a path."""
        for row in reversed(self.state.get("source_edits", [])):
            Path(row["path"]).write_bytes(Path(row["backup"]).read_bytes())
        for row in reversed(self.state["metadata"]):
            path = Path(row["path"])
            temporary = path.with_name(path.name + ".layout-rollback.tmp")
            temporary.write_bytes(Path(row["backup"]).read_bytes())
            temporary.replace(path)
        for row in reversed(self.state["moves"]):
            source, destination = Path(row["source"]), Path(row["destination"])
            if destination.exists():
                if source.exists():
                    raise FileExistsError(source)
                source.parent.mkdir(parents=True, exist_ok=True)
                destination.rename(source)
        self.state["rolled_back"] = True
        self._save()

    def write_source(self, path: Path, text: str):
        self._inside(path)
        original = path.read_bytes()
        if original == text.encode("utf-8"):
            return
        rows = self.state.setdefault("source_edits", [])
        if not any(row["path"] == str(path) for row in rows):
            backup = self.journal.parent / "source-before" / (str(len(rows)) + ".txt")
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(original)
            rows.append({"path": str(path), "backup": str(backup)})
            self._save()
        path.write_text(text, encoding="utf-8")


def rewrite_paths(value, mappings: list[tuple[Path, Path]]):
    """Replace complete absolute path prefixes, never hashes or relative inventories."""
    if isinstance(value, dict):
        return {key: rewrite_paths(item, mappings) for key, item in value.items()}
    if isinstance(value, list):
        return [rewrite_paths(item, mappings) for item in value]
    if isinstance(value, str):
        normalized = value.replace("/", os.sep).replace("\\", os.sep)
        for source, destination in sorted(mappings, key=lambda pair: len(str(pair[0])), reverse=True):
            prefix = str(source).replace("/", os.sep).replace("\\", os.sep)
            if normalized.casefold() == prefix.casefold():
                return str(destination)
            if normalized.casefold().startswith(prefix.casefold() + os.sep):
                return str(destination / normalized[len(prefix) + 1:])
    return value
