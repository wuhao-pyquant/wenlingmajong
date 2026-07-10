from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PhotonFrontendTests(unittest.TestCase):
    def run_node_json(self, source: str) -> dict:
        completed = subprocess.run(
            ["node", "-e", source],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

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

    def test_quality_selection_and_downgrade_are_deterministic(self) -> None:
        payload = self.run_node_json(
            """
            const photon = require('./static/photon_scene.js');
            console.log(JSON.stringify({
              desktop: photon.selectInitialQuality({width: 1280, coarse: false, reducedMotion: false, webgl2: true}),
              mobile: photon.selectInitialQuality({width: 390, coarse: true, reducedMotion: false, webgl2: true}),
              canvas: photon.selectInitialQuality({width: 1280, coarse: false, reducedMotion: false, webgl2: false}),
              staticMode: photon.selectInitialQuality({width: 1280, coarse: false, reducedMotion: true, webgl2: true}),
              desktopDown: photon.nextQuality('desktop', 25),
              lowDown: photon.nextQuality('low', 33),
              desktopBudget: photon.PHOTON_BUDGETS.desktop,
              mobileBudget: photon.PHOTON_BUDGETS.mobile,
            }));
            """
        )
        self.assertEqual(payload["desktop"], "desktop")
        self.assertEqual(payload["mobile"], "mobile")
        self.assertEqual(payload["canvas"], "canvas")
        self.assertEqual(payload["staticMode"], "static")
        self.assertEqual(payload["desktopDown"], "low")
        self.assertEqual(payload["lowDown"], "canvas")
        self.assertEqual(payload["desktopBudget"]["particles"], 220)
        self.assertEqual(payload["desktopBudget"]["maxLinks"], 1100)
        self.assertEqual(payload["desktopBudget"]["pixelRatio"], 1.5)
        self.assertEqual(payload["mobileBudget"]["particles"], 110)
        self.assertEqual(payload["mobileBudget"]["maxLinks"], 420)
        self.assertEqual(payload["mobileBudget"]["pixelRatio"], 1.2)

    def test_scene_runtime_has_pause_dispose_and_fallback_contracts(self) -> None:
        script = (ROOT / "static" / "photon_scene.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "photon_lobby.css").read_text(encoding="utf-8")
        for expected in (
            "visibilitychange",
            "pagehide",
            "beforeunload",
            "webglcontextlost",
            "setAnimationLoop(null)",
            "renderer.dispose()",
            "startCanvasFallback",
            "WenlingPhotonScene",
            "data-photon-mode",
        ):
            self.assertIn(expected, script)
        self.assertIn(".photon-scene-root", css)
        self.assertIn("pointer-events: none", css)

    def test_canvas_context_failure_degrades_to_static(self) -> None:
        payload = self.run_node_json(
            """
            const fs = require('fs');
            const vm = require('vm');
            const root = {
              dataset: {},
              setAttribute() {},
              replaceChildren() {},
            };
            const document = {
              hidden: false,
              getElementById: () => root,
              createElement: () => ({getContext: () => null}),
              addEventListener() {},
              removeEventListener() {},
            };
            const window = {
              innerWidth: 1280,
              matchMedia: () => ({matches: false}),
              setTimeout,
              addEventListener() {},
              removeEventListener() {},
              requestAnimationFrame() { throw new Error('animation must not start'); },
            };
            vm.runInNewContext(fs.readFileSync('./static/photon_scene.js', 'utf8'), {
              console, document, module: {exports: {}}, performance, setTimeout, window,
            });
            console.log(JSON.stringify({mode: root.dataset.photonMode}));
            """
        )
        self.assertEqual(payload["mode"], "static")


if __name__ == "__main__":
    unittest.main()
