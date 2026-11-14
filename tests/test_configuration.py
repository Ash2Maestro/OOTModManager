"""Invalid settings must fail before a game operation or asset subprocess."""
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/bridge"))
from configuration import directory, game_directory, appearance_available, build_inputs


class ConfigurationTests(unittest.TestCase):
    def test_blank_path_does_not_mean_current_directory(self):
        for value in ("", " ", None):
            with self.assertRaisesRegex(ValueError, "non renseigné"):
                directory(value, "Dossier du jeu")

    def test_existing_unrelated_directory_is_not_a_game(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = SimpleNamespace(game_dir=folder, engine="longshot")
            with self.assertRaisesRegex(ValueError, "exécutable reconnu"):
                game_directory(settings)
            self.assertEqual(list(Path(folder).iterdir()), [])
            (Path(folder) / "longshot.exe").touch()
            self.assertEqual(game_directory(settings), Path(folder))

    def test_missing_directory_and_file_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            for path in (Path(folder) / "absent", Path(folder) / "file"):
                if path.name == "file":
                    path.touch()
                with self.assertRaisesRegex(ValueError, "introuvable"):
                    directory(str(path), "Dossier")

    def test_unconfigured_startup_skips_asset_extraction(self):
        self.assertFalse(appearance_available(SimpleNamespace(game_dir="", tools_path="")))

    def test_build_requires_tools_before_accessing_source(self):
        with self.assertRaisesRegex(ValueError, "outils du moteur.*non renseigné"):
            build_inputs(SimpleNamespace(tools_path="", source=""))

    def test_build_requires_builder_python_and_existing_source(self):
        with tempfile.TemporaryDirectory() as folder, patch("modmanager.engines.longshot.LongshotBackend.validate_tools"):
            tools = Path(folder)
            settings = SimpleNamespace(tools_path=folder, source="", engine="longshot")
            with self.assertRaisesRegex(ValueError, "python/python.exe"):
                build_inputs(settings)
            (tools / "python").mkdir()
            (tools / "python/python.exe").touch()
            with self.assertRaisesRegex(ValueError, "Source du jeu non renseignée"):
                build_inputs(settings)
            settings.source = str(tools / "missing.nup")
            with self.assertRaisesRegex(ValueError, "Source du jeu introuvable"):
                build_inputs(settings)
