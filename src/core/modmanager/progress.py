"""Engine-neutral progress state published to either desktop frontend."""
STAGES = {"read": "Lecture du jeu", "lift": "Traduction en code PC", "compile": "Compilation",
          "finish": "Installation et ressources", "prepare": "Préparation du mod",
          "audit": "Vérification", "configure": "Réglages du jeu"}


class Progress:
    """One stage at a time; unknown percentages remain unknown."""

    def __init__(self):
        self.stage = "audit"
        self.percent = None
        self.eta = None
        self.detail = ""

    def begin_stage(self, name: str) -> dict:
        self.stage = name
        self.percent = self.eta = None
        self.detail = ""
        return self.snapshot()

    def snapshot(self) -> dict:
        return {"stage": self.stage, "label": STAGES.get(self.stage, self.stage),
                "percent": self.percent, "eta": self.eta, "detail": self.detail}

    def feed(self, line: str) -> dict | None:
        """Backends override this parser; ordinary log lines need no UI update."""
        return None
