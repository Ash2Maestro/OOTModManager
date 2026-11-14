import unittest
from modmanager.updates import UpdateSource, select_release


SOURCE = UpdateSource("owner/repo", "wheel-v")


def release(version, prefix="wheel-v", **kwargs):
    return dict(tag_name=prefix + version,
                html_url="https://github.com/owner/repo/releases/tag/" + prefix + version, **kwargs)


class UpdatesTests(unittest.TestCase):
    def test_multiple_mods_and_numeric_order(self):
        result = select_release(SOURCE, "0.1.7", [release("0.1.9"), release("0.1.10"),
                                release("9.0.0", "shield-v")])
        self.assertEqual(result["version"], "0.1.10")
        self.assertEqual(result["compatibility"], "unverified")

    def test_channels_drafts_and_stable_order(self):
        releases = [release("0.2.0-beta.12", prerelease=True), release("0.1.8"),
                    release("8.0.0", draft=True)]
        self.assertEqual(select_release(SOURCE, "0.1.7", releases)["version"], "0.1.8")
        self.assertEqual(select_release(SOURCE, "0.1.7", releases, True)["version"], "0.2.0-beta.12")
        self.assertEqual(select_release(SOURCE, "0.2.0-beta.12", [release("0.2.0")], True)["status"], "available")

    def test_unknown_is_not_up_to_date(self):
        self.assertEqual(select_release(SOURCE, "0.1.7", [release("1.0.0", "shield-v")])["status"], "unknown")
        self.assertEqual(select_release(SOURCE, "0.1.7", [release("0.1.7")])["status"], "current")
        self.assertEqual(select_release(SOURCE, "0.1.7", [release("0.1.6")])["status"], "current")

    def test_invalid_sources_and_versions(self):
        with self.assertRaises(ValueError):
            UpdateSource("https://evil.example/repo", "v")
        with self.assertRaises(ValueError):
            select_release(SOURCE, "nightly", [])
