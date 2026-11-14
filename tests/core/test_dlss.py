import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from modmanager.engines.longshot_dlss import environment, prepare_options, runtime_matches
from modmanager.models import Settings
from modmanager.pipeline import build_command, run
from modmanager.reuse import native_key, native_files


class DlssTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.tools = self.root / "tools"
        (self.tools / "scripts").mkdir(parents=True)
        self.sdk = self.root / "sdk"
        self.specs = [("include/header.h", b"header"), ("lib/library.lib", b"library"),
                      ("runtime/nvngx_dlss.dll", b"runtime")]
        entries = [(name, hashlib.sha256(data).hexdigest(), name) for name, data in self.specs]
        (self.tools / "scripts/ngx_sdk.py").write_text("def files(platform):\n return " + repr(entries))
        self.settings = Settings(dlss=True, dlss_license=True, ngx_sdk=str(self.sdk))

    def populate(self):
        for name, data in self.specs:
            path = self.sdk / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def test_license_is_required_before_any_download(self):
        self.settings.dlss_license = False
        runner = Mock()
        with self.assertRaisesRegex(ValueError, "licence"):
            prepare_options(self.settings, self.tools, "python", runner)
        runner.assert_not_called()

    def test_cached_sdk_is_verified_and_reused_without_download(self):
        self.populate()
        runner = Mock()
        options = prepare_options(self.settings, self.tools, "python", runner)
        self.assertTrue(options["dlss"])
        self.assertEqual(len(options["sdk_fingerprint"]), 64)
        runner.assert_not_called()
        (self.sdk / "include/header.h").write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            prepare_options(self.settings, self.tools, "python", runner, read_only=True)
        runner.assert_not_called()

    def test_missing_sdk_is_fetched_only_after_recorded_consent(self):
        runner = Mock(side_effect=lambda args: self.populate())
        prepare_options(self.settings, self.tools, "python", runner)
        self.assertIn("--accept-nvidia-license", runner.call_args.args[0])

    def test_missing_or_modified_game_runtime_cannot_be_considered_ready(self):
        options = {"dlss": True, "runtimes": {"nvngx_dlss.dll": hashlib.sha256(b"runtime").hexdigest()}}
        report = {"build_options": options}
        self.assertFalse(runtime_matches(report,self.root))
        (self.root / "ngx").mkdir()
        (self.root / "ngx/nvngx_dlss.dll").write_bytes(b"runtime")
        self.assertTrue(runtime_matches(report,self.root))
        (self.root / "ngx/nvngx_dlss.dll").write_bytes(b"modified")
        self.assertFalse(runtime_matches(report,self.root))

    def test_disabled_dlss_does_not_depend_on_sdk_or_ambient_environment(self):
        self.settings.dlss = False
        runner = Mock()
        self.assertEqual(prepare_options(self.settings, self.tools, "python", runner), {"dlss": False})
        with patch.dict(os.environ, LONGSHOT_NGX_SDK="unwanted"), patch("modmanager.pipeline.subprocess.run") as process:
            run(["compiler"], self.root, environment=environment({}))
        self.assertNotIn("LONGSHOT_NGX_SDK", process.call_args.kwargs["env"])
        runner.assert_not_called()

    def test_build_command_and_environment_require_consistent_dlss_settings(self):
        report = dict(tools_path=str(self.tools),romfs="romfs",build_options={"dlss": True},
                      nvidia_license_accepted=True,ngx_sdk=str(self.sdk))
        command = build_command(self.root,report,2,"fr")
        self.assertIn("--fetch-ngx-sdk",command)
        self.assertIn("--accept-nvidia-license",command)
        self.assertEqual(environment(report),{"LONGSHOT_NGX_SDK":str(self.sdk)})
        report["nvidia_license_accepted"] = False
        with self.assertRaises(ValueError):
            build_command(self.root,report,2,None)

    def test_dlss_cache_is_separate_and_contains_nvidia_runtimes(self):
        (self.root / "prepared/exefs").mkdir(parents=True)
        (self.root / "prepared/exefs/main").write_bytes(b"guest")
        without = native_key(self.root,{},"tools","fr")
        with_dlss = native_key(self.root,{"build_options":{"dlss":True,"sdk_fingerprint":"one"}},"tools","fr")
        other_sdk = native_key(self.root,{"build_options":{"dlss":True,"sdk_fingerprint":"two"}},"tools","fr")
        self.assertEqual(len({without,with_dlss,other_sdk}),3)
        (self.root / "ngx").mkdir()
        (self.root / "ngx/nvngx_dlss.dll").write_bytes(b"runtime")
        (self.root / "longshot.exe").write_bytes(b"exe")
        (self.root / "image.bin").write_bytes(b"guest")
        self.assertIn("ngx/nvngx_dlss.dll",native_files(self.root))


if __name__ == "__main__":
    unittest.main()
