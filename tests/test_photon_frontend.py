from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PhotonFrontendTests(unittest.TestCase):
    def test_three_vendor_is_pinned_and_local(self) -> None:
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        vendor = ROOT / "static" / "vendor" / "three" / "three.module.min.js"
        core_vendor = ROOT / "static" / "vendor" / "three" / "three.core.min.js"
        license_file = ROOT / "static" / "vendor" / "three" / "LICENSE"

        self.assertEqual(package["devDependencies"]["three"], "0.185.1")
        self.assertTrue(vendor.is_file())
        self.assertTrue(core_vendor.is_file())
        self.assertEqual(vendor.stat().st_size, 365_552)
        self.assertIn("MIT License", license_file.read_text(encoding="utf-8"))
        self.assertNotIn("cdn.", vendor.read_text(encoding="utf-8", errors="ignore"))

    def test_three_vendor_esm_import_requires_and_includes_core_sibling(self) -> None:
        vendor_dir = ROOT / "static" / "vendor" / "three"
        module = vendor_dir / "three.module.min.js"
        core = vendor_dir / "three.core.min.js"

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_dir = Path(temp_dir)
            (fixture_dir / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
            fixture_module = fixture_dir / module.name
            shutil.copy2(module, fixture_module)

            missing_sibling = subprocess.run(
                [
                    "node",
                    "--input-type=module",
                    "--eval",
                    "await import(process.argv[1])",
                    fixture_module.as_uri(),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(missing_sibling.returncode, 0)
            self.assertIn("three.core.min.js", missing_sibling.stderr)

            self.assertTrue(core.is_file())
            shutil.copy2(core, fixture_dir / core.name)
            imported = subprocess.run(
                [
                    "node",
                    "--input-type=module",
                    "--eval",
                    "const three = await import(process.argv[1]); if (typeof three.Scene !== 'function') process.exit(1)",
                    fixture_module.as_uri(),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(imported.returncode, 0, imported.stderr)

    def test_android_runtime_asset_lists_include_photon_dependencies(self) -> None:
        gradle = (ROOT / "android-host" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
        service = (
            ROOT
            / "android-host"
            / "app"
            / "src"
            / "main"
            / "java"
            / "cn"
            / "wenling"
            / "mahjong"
            / "host"
            / "HostService.kt"
        ).read_text(encoding="utf-8")

        for path in (
            "battle_lobby.html",
            "photon_scene.js",
            "photon_lobby.css",
            "vendor/three/**",
        ):
            self.assertIn(f'"{path}"', gradle)
        for root in (
            "battle_lobby.html",
            "photon_scene.js",
            "photon_lobby.css",
            "vendor",
        ):
            self.assertIn(f'"{root}"', service)


if __name__ == "__main__":
    unittest.main()
