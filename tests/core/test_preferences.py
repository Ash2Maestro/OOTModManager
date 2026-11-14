from pathlib import Path
import tempfile
import unittest
from modmanager.engines.longshot_preferences import canonical_language, apply_preferences, preferences_match
from modmanager.models import Settings


class PreferencesTests(unittest.TestCase):
    def test_french_alias_migrates_to_actual_game_code(self):
        self.assertEqual(canonical_language("fr-FR"), "fr")
        self.assertEqual(canonical_language("Français (France)"), "fr")
        self.assertEqual(Settings(language="fr-FR").language, "fr")
        with self.assertRaises(ValueError):
            canonical_language("unknown")

    def game(self, root):
        (root / ".hmb-owner.json").write_text("{}")
        (root / "prompts/ps5").mkdir(parents=True)
        (root / "image.bin").write_bytes(b"native image unchanged")
        (root / "longshot.exe").write_bytes(b"exe unchanged")
        (root / "language.txt").write_text("# languages\nfr-FR\n# en-US English\n")
        (root / "longshot_options.ini").write_text("output_res=3840x2160\nbutton_prompts=0\npad_a=2\nvolume=80\n")

    def test_runtime_changes_preserve_native_files_and_other_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp)
            self.game(game)
            self.assertTrue(apply_preferences(game, "fr-FR", 4))
            self.assertEqual((game / "language.txt").read_text(), "# languages\nfr\n# en-US English\n")
            self.assertEqual((game / "longshot_options.ini").read_text(), "output_res=3840x2160\nbutton_prompts=4\npad_a=2\nvolume=80\n")
            self.assertEqual((game / "image.bin").read_bytes(), b"native image unchanged")
            self.assertEqual((game / "longshot.exe").read_bytes(), b"exe unchanged")
            self.assertTrue(preferences_match(game, "fr", 4))
            self.assertFalse(apply_preferences(game, "fr", 4))

    def test_missing_prompt_assets_are_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp)
            (game / ".hmb-owner.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "absentes"):
                apply_preferences(game, "fr", 4)
            self.assertFalse((game / "language.txt").exists())

    def test_append_missing_prompt_key_and_keep_existing_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp)
            self.game(game)
            (game / "longshot_options.ini").write_text("volume=80\n")
            apply_preferences(game, "fr", 4)
            self.assertEqual((game / "longshot_options.ini").read_text(), "volume=80\nbutton_prompts=4\n")
