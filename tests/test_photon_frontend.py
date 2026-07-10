from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PhotonFrontendTests(unittest.TestCase):
    def test_three_vendor_is_pinned_and_local(self) -> None:
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        vendor = ROOT / "static" / "vendor" / "three" / "three.module.min.js"
        license_file = ROOT / "static" / "vendor" / "three" / "LICENSE"

        self.assertEqual(package["devDependencies"]["three"], "0.185.1")
        self.assertTrue(vendor.is_file())
        self.assertEqual(vendor.stat().st_size, 365_552)
        self.assertIn("MIT License", license_file.read_text(encoding="utf-8"))
        self.assertNotIn("cdn.", vendor.read_text(encoding="utf-8", errors="ignore"))

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
