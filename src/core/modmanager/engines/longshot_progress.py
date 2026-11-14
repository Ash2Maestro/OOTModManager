"""Translate Longshot build output into the manager progress schema."""
import re
from ..progress import Progress


class LongshotProgress(Progress):
    def feed(self, line: str) -> dict | None:
        line = line.strip()
        if not line.startswith(("@@", "Extraction originale", "Reconstruction de la variante", "Cache partage :")):
            return None
        if line.startswith("@@stage "):
            self.stage = line.split(maxsplit=2)[1]
            self.percent, self.eta = None, None
            self.detail = ""
        elif match := re.search(r"Extraction originale : (\d+)/(\d+) fichiers", line):
            done, total = map(int, match.groups())
            self.percent = min(100, done * 100 / total) if total else None
            self.detail = "%d / %d fichiers extraits" % (done, total)
        elif line.startswith("Reconstruction de la variante"):
            self.percent, self.eta, self.detail = None, None, "Reconstruction des fichiers du mod"
        elif line.startswith("@@progress "):
            try:
                self.percent = max(0.0, min(100.0, float(line.split()[1]) * 100))
            except (ValueError, IndexError):
                pass
        elif line.startswith("@@eta "):
            try:
                self.eta = max(0, int(line.split()[1]))
            except (ValueError, IndexError):
                pass
        elif line.startswith("@@plan "):
            try:
                pending, total = map(int, line.split()[1:3])
                self.detail = "%d fichiers à compiler · %d déjà en cache" % (pending, max(0, total - pending))
            except (ValueError, IndexError):
                pass
        elif line.startswith("Cache partage :"):
            self.detail = line
        elif line.startswith("@@file "):
            parts = line.split()
            if len(parts) >= 4:
                self.detail = parts[1] + (" — réutilisé du cache" if parts[-1] == "cached" else " — compilé")
        elif line.startswith("@@done"):
            self.percent, self.eta = 100, 0
            self.detail = "Installation terminée"
        return self.snapshot()
