import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from windows import package_release
import setup_claude
from times_gate import runtime


class RuntimeTests(unittest.TestCase):
    def test_source_paths_stay_in_project(self):
        with patch.object(runtime.sys,"frozen",False,create=True), patch.dict(os.environ,{},clear=True):
            self.assertEqual(runtime.app_root(),Path(runtime.__file__).resolve().parents[1])
            self.assertEqual(runtime.data_root(),runtime.app_root())

    def test_frozen_data_is_separate_from_executable_and_internal_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch.object(runtime.sys,"frozen",True,create=True), \
                 patch.object(runtime.sys,"executable",str(root/"Program/TimesGate.exe")), \
                 patch.dict(os.environ,{"LOCALAPPDATA":str(root/"Profile")},clear=True):
                self.assertEqual(runtime.app_root(),root/"Program")
                self.assertEqual(runtime.data_root(),root/"Profile/TimesGateAI")
                with patch.dict(os.environ,{"TIMES_GATE_DATA_DIR":str(root/"Custom data")}):
                    self.assertEqual(runtime.data_root(),root/"Custom data")


class BridgePackagingTests(unittest.TestCase):
    def command(self,root):
        root.mkdir(parents=True,exist_ok=True)
        (root/"TimesGateCLI.exe").touch()
        with patch.object(setup_claude.sys,"frozen",True,create=True), patch.object(setup_claude,"ROOT",root):
            return setup_claude.bridge_command()

    def test_encoded_command_handles_unicode_spaces_and_shell_characters(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/"Türkçe O'Brien $folder"
            command=self.command(root)
            decoded=setup_claude.decoded_command(command)
            self.assertTrue(setup_claude.is_bridge(command))
            self.assertIn(root.as_posix().replace("'","''")+"/TimesGateCLI.exe",decoded)
            self.assertIn("[Console]::In.ReadToEnd()",decoded)
            self.assertNotIn("Türkçe",command)

    def test_relocating_packaged_bridge_keeps_original_and_uninstalls(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            settings=root/"settings.json"
            backup=root/"data/install.json"
            original={"theme":"dark","statusLine":{"type":"command","command":"echo ORIGINAL","padding":2}}
            settings.write_text(json.dumps(original),encoding="utf-8")
            first=self.command(root/"Old location")
            second=self.command(root/"New location")
            self.assertTrue(setup_claude.install(settings,backup,first))
            self.assertFalse(setup_claude.install(settings,backup,first))
            self.assertTrue(setup_claude.install(settings,backup,second))
            self.assertEqual(json.loads(backup.read_text())["original_statusLine"],original["statusLine"])
            self.assertTrue(setup_claude.install(settings,backup,second,remove=True))
            self.assertEqual(json.loads(settings.read_text()),original)


class DistributionTests(unittest.TestCase):
    def fixture(self,root):
        bundle=root/"dist/TimesGateAI"
        (bundle/"_internal").mkdir(parents=True)
        for name in ("TimesGate.exe","TimesGateCLI.exe","_internal/python313.dll"):
            (bundle/name).write_bytes(b"runtime")
        (root/"windows").mkdir()
        (root/"windows/PORTABLE-README.txt").write_text("Instructions")
        (root/"config.local.json").write_text("PRIVATE CONFIG")
        (root/"secrets.local.json").write_text("PRIVATE TOKEN")
        return bundle

    def test_package_contains_only_runtime_and_instructions(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            self.fixture(root)
            with patch.object(package_release,"ROOT",root), patch("builtins.print"):
                package_release.package()
            with zipfile.ZipFile(root/"releases/TimesGateAI-Windows-x64.zip") as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(set(archive.namelist()),{"TimesGateAI/TimesGate.exe","TimesGateAI/TimesGateCLI.exe",
                    "TimesGateAI/_internal/python313.dll","TimesGateAI/README.txt"})
            self.assertTrue((root/"releases/TimesGateAI-Windows-x64.zip.sha256").is_file())

    def test_personal_data_accidentally_in_bundle_blocks_release(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            bundle=self.fixture(root)
            private=bundle/"_internal/output/telemetry.json"
            private.parent.mkdir()
            private.write_text("PRIVATE")
            with patch.object(package_release,"ROOT",root), self.assertRaisesRegex(ValueError,"Personal data"):
                package_release.package()
            self.assertFalse((root/"releases/TimesGateAI-Windows-x64.zip").exists())


if __name__=="__main__":
    unittest.main()
