# Photon Auth and Lobby Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the login, invite-registration, and three-room lobby UI with the approved D "Photon Core" + G "Seamless Stage" + K "Showcase Motion" experience while leaving the battle page and gameplay behavior unchanged.

**Architecture:** Serve a pinned local Three.js ESM build and run it only behind `/battle-login` and `/battle-lobby`. Keep every form, room, seat, and command as normal DOM, expose a failure-tolerant `window.WenlingPhotonScene` bridge, and fall back from Three.js to Canvas 2D to a static CSS background. Existing auth, session, room API, and three-second polling logic remain in `battle_lobby.js`.

**Tech Stack:** Python 3.12 `unittest`, static HTML/CSS/JavaScript, Three.js `0.185.1` (MIT, vendored locally), Canvas 2D fallback, Android Gradle asset packaging, Codex in-app browser QA.

## Global Constraints

- Modify only login, registration, lobby presentation, their shared frontend controller, tests, dependency metadata, and static-asset packaging.
- Do not modify `static/battle.html`, `static/battle_app.js`, `static/battle_geometry_v7.css`, gameplay code, room services, auth APIs, or database code.
- Three.js must be loaded only by `battle_login.html` and `battle_lobby.html`; `/battle` must neither download nor initialize it.
- Pin `three` exactly to `0.185.1`, vendor the matching `three.module.min.js` and `three.core.min.js` ESM files plus their MIT license under `static/vendor/three/`, and never use a runtime CDN.
- Keep all existing DOM IDs used by `battle_lobby.js` and tests.
- Keep all existing API paths, bearer-token storage keys, room storage keys, and the 3000 ms lobby polling interval.
- Keep password copy `推荐密码1234`, the only accepted human password `1234`, and masked default invite code `WL1234`.
- Keep the room limit at three and room AI policy unified per room.
- Forms, buttons, room state, and seat labels remain DOM; the WebGL canvas uses `pointer-events: none`.
- Desktop Three.js budget: at most 220 particles, 1100 links, two moving point lights, three tiles, DPR at most 1.5.
- Mobile Three.js budget: at most 110 particles, 420 links, one moving and one static point light, DPR at most 1.2.
- Low Three.js budget: at most 60 particles, 160 links, one static light, DPR 1.0.
- Canvas fallback budget: at most 60 desktop particles or 36 mobile particles, DPR 1.0.
- Reduced-motion users get a static CSS background with no persistent Three.js or Canvas animation.
- Average frame time above 24 ms downgrades one Three.js tier; after another two-second sample, above 32 ms switches to Canvas 2D. Quality never rises during the same page visit.
- Auth success animation waits at most 700 ms before ordinary navigation.
- Android packaging must include `battle_lobby.html`, `photon_scene.js`, `photon_lobby.css`, and `vendor/three/**` without changing Android host UI or battle assets.

---

## File Structure

- Modify `package.json` and `package-lock.json`: record exact Three.js provenance as a development dependency.
- Create `static/vendor/three/three.module.min.js`: vendored Three.js ESM runtime.
- Create `static/vendor/three/three.core.min.js`: matching ESM core sibling imported by the runtime module.
- Create `static/vendor/three/LICENSE`: upstream MIT license.
- Create `static/photon_scene.js`: quality selection, Three.js scene, Canvas fallback, transitions, visibility lifecycle, and disposal.
- Create `static/photon_lobby.css`: all scoped auth/lobby layout, visual, responsive, focus, and reduced-motion rules.
- Modify `static/battle_login.html`: G seamless-stage auth DOM with login/register tabs.
- Modify `static/battle_lobby.html`: photon lobby toolbar and three semantic room articles.
- Modify `static/battle_lobby.js`: mode switching, defaults, failure-tolerant scene calls, valid room actions, room diffs, AI segmented control, and teardown before navigation.
- Create `tests/test_photon_frontend.py`: dependency, runtime, DOM, script, CSS, isolation, and Android packaging contracts.
- Modify `tests/test_online_server.py`: live static-resource and page-isolation HTTP assertions.
- Modify `tests/test_repository_boundaries.py`: Android runtime-asset boundary assertion.
- Modify `android-host/app/build.gradle.kts`: include the lobby and photon static assets.
- Modify `android-host/app/src/main/java/cn/wenling/mahjong/host/HostService.kt`: copy the same runtime asset roots on device.

## Task 1: Vendor Three.js and Preserve Runtime Packaging

**Files:**
- Create: `tests/test_photon_frontend.py`
- Create: `static/vendor/three/three.module.min.js`
- Create: `static/vendor/three/three.core.min.js`
- Create: `static/vendor/three/LICENSE`
- Modify: `package.json`
- Modify: `package-lock.json`
- Modify: `android-host/app/build.gradle.kts:8-24`
- Modify: `android-host/app/src/main/java/cn/wenling/mahjong/host/HostService.kt:498-513`
- Modify: `tests/test_repository_boundaries.py`

**Interfaces:**
- Consumes: npm package `three@0.185.1`, package shasum `63e9e241a17b101e211965121a017b4b4d8054ae`.
- Produces: browser import path `/vendor/three/three.module.min.js?v=0.185.1` and Android runtime copies of all photon assets.

- [ ] **Step 1: Write the failing vendor and Android packaging tests**

Create `tests/test_photon_frontend.py` with:

```python
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
        """Prove the module fails alone and imports only with its local sibling."""
        # Stage only three.module.min.js in a temporary ESM package, assert Node
        # reports the missing three.core.min.js import, then add the sibling and
        # assert importing the staged local module exposes THREE.Scene.

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
```

Add this method to `RepositoryBoundaryTests` in `tests/test_repository_boundaries.py`:

```python
    def test_android_runtime_web_assets_include_photon_lobby_dependencies(self) -> None:
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
        self.assertIn('"battle_lobby.html"', gradle)
        self.assertIn('"photon_scene.js"', gradle)
        self.assertIn('"photon_lobby.css"', gradle)
        self.assertIn('"vendor/three/**"', gradle)
        self.assertIn('"battle_lobby.html"', service)
        self.assertIn('"photon_scene.js"', service)
        self.assertIn('"photon_lobby.css"', service)
        self.assertIn('"vendor"', service)
```

- [ ] **Step 2: Run the tests and verify the expected RED state**

Run:

```powershell
$env:PYTHONPATH='src;packages/wenling_core'
.\.venv\Scripts\python.exe -m unittest tests.test_photon_frontend tests.test_repository_boundaries.RepositoryBoundaryTests.test_android_runtime_web_assets_include_photon_lobby_dependencies -v
```

Expected: FAIL because `devDependencies.three`, the vendor files, and Android photon asset entries do not exist.

- [ ] **Step 3: Pin Three.js and copy both runtime ESM files and the license**

Run:

```powershell
npm install --save-dev --save-exact three@0.185.1
New-Item -ItemType Directory -Force static\vendor\three | Out-Null
Copy-Item -LiteralPath node_modules\three\build\three.module.min.js -Destination static\vendor\three\three.module.min.js
Copy-Item -LiteralPath node_modules\three\build\three.core.min.js -Destination static\vendor\three\three.core.min.js
Copy-Item -LiteralPath node_modules\three\LICENSE -Destination static\vendor\three\LICENSE
```

Expected: `package-lock.json` records `three@0.185.1`; the vendored module is exactly 365,552 bytes; a real Node ESM import first fails without `three.core.min.js` and then succeeds with the matching local sibling.

- [ ] **Step 4: Add the runtime assets to both Android allowlists**

In `android-host/app/build.gradle.kts`, make the `include` call contain these additional entries next to the existing lobby assets:

```kotlin
            "battle_lobby.html",
            "photon_scene.js",
            "photon_lobby.css",
            "vendor/three/**",
```

In `HostService.kt`, make `STATIC_ASSET_ROOTS` contain:

```kotlin
            "battle_lobby.html",
            "photon_scene.js",
            "photon_lobby.css",
            "vendor",
```

Keep the existing `battle.html`, `battle_app.js`, `styles.css`, and `assets` entries unchanged.

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run:

```powershell
$env:PYTHONPATH='src;packages/wenling_core'
.\.venv\Scripts\python.exe -m unittest tests.test_photon_frontend tests.test_repository_boundaries.RepositoryBoundaryTests.test_android_runtime_web_assets_include_photon_lobby_dependencies -v
```

Expected: 4 tests pass.

- [ ] **Step 6: Commit the vendored dependency and packaging boundary**

```powershell
git add package.json package-lock.json static/vendor/three tests/test_photon_frontend.py tests/test_repository_boundaries.py android-host/app/build.gradle.kts android-host/app/src/main/java/cn/wenling/mahjong/host/HostService.kt
git commit -m "Vendor Three.js for photon lobby"
```

## Task 2: Build the Isolated Photon Scene Runtime

**Files:**
- Create: `static/photon_scene.js`
- Create: `static/photon_lobby.css`
- Modify: `tests/test_photon_frontend.py`

**Interfaces:**
- Consumes: `/vendor/three/three.module.min.js?v=0.185.1`, root element `#photonSceneRoot` with `data-page="auth|lobby"`.
- Produces: `window.WenlingPhotonScene.playAuthSuccess()`, `.playLobbyReveal()`, `.notifyRoomChanges(changes)`, `.setStatus(kind)`, and `.destroy()`.
- Produces for tests: CommonJS exports `PHOTON_BUDGETS`, `selectInitialQuality(environment)`, and `nextQuality(current, averageFrameMs)` when loaded under Node.

- [ ] **Step 1: Add failing quality and lifecycle tests**

Add these methods and helper to `tests/test_photon_frontend.py`:

```python
    def run_node_json(self, source: str) -> dict:
        completed = subprocess.run(
            ["node", "-e", source],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

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
```

- [ ] **Step 2: Run the runtime tests and verify RED**

Run:

```powershell
$env:PYTHONPATH='src;packages/wenling_core'
.\.venv\Scripts\python.exe -m unittest tests.test_photon_frontend.PhotonFrontendTests.test_quality_selection_and_downgrade_are_deterministic tests.test_photon_frontend.PhotonFrontendTests.test_scene_runtime_has_pause_dispose_and_fallback_contracts -v
```

Expected: FAIL because `photon_scene.js` and `photon_lobby.css` do not exist.

- [ ] **Step 3: Implement deterministic quality selection at the top of `photon_scene.js`**

Use this exact public core before browser-only initialization:

```javascript
(() => {
  "use strict";

  const PHOTON_BUDGETS = Object.freeze({
    desktop: Object.freeze({ particles: 220, maxLinks: 1100, movingLights: 2, pixelRatio: 1.5 }),
    mobile: Object.freeze({ particles: 110, maxLinks: 420, movingLights: 1, pixelRatio: 1.2 }),
    low: Object.freeze({ particles: 60, maxLinks: 160, movingLights: 0, pixelRatio: 1.0 }),
    canvas: Object.freeze({ particles: 60, mobileParticles: 36, maxLinks: 120, pixelRatio: 1.0 }),
    static: Object.freeze({ particles: 0, maxLinks: 0, movingLights: 0, pixelRatio: 1.0 }),
  });

  function selectInitialQuality({ width, coarse, reducedMotion, webgl2 }) {
    if (reducedMotion) return "static";
    if (!webgl2) return "canvas";
    return coarse || width <= 760 ? "mobile" : "desktop";
  }

  function nextQuality(current, averageFrameMs) {
    if ((current === "desktop" || current === "mobile") && averageFrameMs > 24) return "low";
    if (current === "low" && averageFrameMs > 32) return "canvas";
    return current;
  }

  const testExports = { PHOTON_BUDGETS, selectInitialQuality, nextQuality };
  if (typeof module !== "undefined" && module.exports) module.exports = testExports;
  if (typeof window === "undefined" || typeof document === "undefined") return;
```

Close the IIFE at the end of the file. This makes Node tests execute only pure functions and keeps browser initialization separate.

- [ ] **Step 4: Implement the browser controller, Three.js layer, and Canvas fallback**

Inside the same IIFE, use these exact state and lifecycle boundaries:

```javascript
  const root = document.getElementById("photonSceneRoot");
  if (!root) return;

  const disposers = [];
  let activeLayer = null;
  let destroyed = false;
  let effectBoostUntil = 0;

  function setRootMode(mode, quality = mode) {
    root.dataset.photonMode = mode;
    root.dataset.photonQuality = quality;
    root.setAttribute("data-photon-mode", mode);
  }

  function supportsWebGL2() {
    try {
      const canvas = document.createElement("canvas");
      return Boolean(canvas.getContext("webgl2"));
    } catch {
      return false;
    }
  }

  function wait(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  function sceneTransition(name, duration) {
    root.dataset.photonTransition = name;
    effectBoostUntil = performance.now() + duration;
    return wait(duration).finally(() => {
      if (root.dataset.photonTransition === name) delete root.dataset.photonTransition;
    });
  }

  function disposeActiveLayer() {
    if (!activeLayer) return;
    activeLayer.destroy();
    activeLayer = null;
  }

  function startStaticFallback() {
    disposeActiveLayer();
    setRootMode("static");
    root.replaceChildren();
  }
```

Implement `startCanvasFallback()` as a complete Canvas 2D layer with these fixed rules:

```javascript
  function startCanvasFallback() {
    disposeActiveLayer();
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d");
    const coarse = window.matchMedia("(pointer: coarse)").matches;
    const count = coarse ? PHOTON_BUDGETS.canvas.mobileParticles : PHOTON_BUDGETS.canvas.particles;
    const points = Array.from({ length: count }, (_, index) => ({
      x: Math.random(), y: Math.random(),
      vx: (Math.random() - 0.5) * 0.00018,
      vy: (Math.random() - 0.5) * 0.00018,
      radius: index % 9 === 0 ? 1.8 : 0.8,
    }));
    let frameId = 0;
    let running = true;

    function resize() {
      canvas.width = Math.max(1, Math.round(root.clientWidth));
      canvas.height = Math.max(1, Math.round(root.clientHeight));
    }

    function render() {
      if (!running || document.hidden) return;
      context.clearRect(0, 0, canvas.width, canvas.height);
      for (const point of points) {
        point.x = (point.x + point.vx + 1) % 1;
        point.y = (point.y + point.vy + 1) % 1;
        context.beginPath();
        context.arc(point.x * canvas.width, point.y * canvas.height, point.radius, 0, Math.PI * 2);
        context.fillStyle = "rgba(104, 245, 255, 0.62)";
        context.shadowBlur = point.radius > 1 ? 10 : 3;
        context.shadowColor = "#68f5ff";
        context.fill();
      }
      context.shadowBlur = 0;
      root.dataset.photonFrames = String(Number(root.dataset.photonFrames || "0") + 1);
      frameId = window.requestAnimationFrame(render);
    }

    function resume() {
      if (running && !frameId && !document.hidden) frameId = window.requestAnimationFrame(render);
    }

    resize();
    root.replaceChildren(canvas);
    setRootMode("canvas");
    frameId = window.requestAnimationFrame(render);
    window.addEventListener("resize", resize);

    activeLayer = {
      pause() { if (frameId) window.cancelAnimationFrame(frameId); frameId = 0; },
      resume,
      destroy() {
        running = false;
        if (frameId) window.cancelAnimationFrame(frameId);
        window.removeEventListener("resize", resize);
        canvas.remove();
      },
    };
  }
```

Implement `startThreeLayer(THREE, quality)` with these concrete objects and cleanup rules:

```javascript
  function startThreeLayer(THREE, quality) {
    disposeActiveLayer();
    const budget = PHOTON_BUDGETS[quality];
    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: quality === "desktop", powerPreference: "high-performance" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, budget.pixelRatio));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.setClearColor(0x04090b, 0);

    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x04090b, 0.065);
    const camera = new THREE.PerspectiveCamera(44, 1, 0.1, 80);
    camera.position.set(0, 0, 12);

    const particleGeometry = new THREE.BufferGeometry();
    const particlePositions = new Float32Array(budget.particles * 3);
    for (let i = 0; i < budget.particles; i += 1) {
      particlePositions[i * 3] = (Math.random() - 0.5) * 18;
      particlePositions[i * 3 + 1] = (Math.random() - 0.5) * 10;
      particlePositions[i * 3 + 2] = (Math.random() - 0.5) * 8;
    }
    particleGeometry.setAttribute("position", new THREE.BufferAttribute(particlePositions, 3));
    const particleMaterial = new THREE.PointsMaterial({ color: 0x68f5ff, size: quality === "mobile" ? 0.055 : 0.045, transparent: true, opacity: 0.8, blending: THREE.AdditiveBlending, depthWrite: false });
    const particles = new THREE.Points(particleGeometry, particleMaterial);
    scene.add(particles);

    const linkGeometry = new THREE.BufferGeometry();
    const linkPositions = new Float32Array(budget.maxLinks * 6);
    linkGeometry.setAttribute("position", new THREE.BufferAttribute(linkPositions, 3));
    linkGeometry.setDrawRange(0, 0);
    const linkMaterial = new THREE.LineBasicMaterial({ color: 0x4cb0be, transparent: true, opacity: 0.16, blending: THREE.AdditiveBlending });
    const links = new THREE.LineSegments(linkGeometry, linkMaterial);
    scene.add(links);

    const ambient = new THREE.AmbientLight(0x8fdde2, 0.42);
    const keyLight = new THREE.DirectionalLight(0xdfffff, 2.2);
    keyLight.position.set(3, 5, 7);
    scene.add(ambient, keyLight);
    const movingLights = Array.from({ length: budget.movingLights }, (_, index) => {
      const light = new THREE.PointLight(index ? 0xffb85c : 0x68f5ff, 24, 16, 2);
      scene.add(light);
      return light;
    });
```

Continue the same function with the complete tile, resize, link, animation, and downgrade implementation:

```javascript
    function tileTexture(glyph, glyphColor) {
      const canvas = document.createElement("canvas");
      canvas.width = 256;
      canvas.height = 320;
      const context = canvas.getContext("2d");
      context.fillStyle = "#eef9f6";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.strokeStyle = "#79dfe3";
      context.lineWidth = 10;
      context.strokeRect(12, 12, canvas.width - 24, canvas.height - 24);
      context.fillStyle = glyphColor;
      context.font = "900 154px sans-serif";
      context.textAlign = "center";
      context.textBaseline = "middle";
      context.fillText(glyph, canvas.width / 2, canvas.height / 2 + 5);
      const texture = new THREE.CanvasTexture(canvas);
      texture.colorSpace = THREE.SRGBColorSpace;
      return texture;
    }

    const tileGroup = new THREE.Group();
    tileGroup.position.set(root.dataset.page === "lobby" ? 2.5 : 2.1, 0.25, 0);
    const tileGeometry = new THREE.BoxGeometry(1.2, 1.6, 0.18);
    const glyphs = [
      ["發", "#167c61"],
      ["中", "#d44842"],
      ["白", "#173b3c"],
    ];
    const tiles = glyphs.map(([glyph, color], index) => {
      const front = new THREE.MeshStandardMaterial({ map: tileTexture(glyph, color), roughness: 0.36, metalness: 0.06 });
      const side = new THREE.MeshStandardMaterial({ color: 0xc9f6ef, roughness: 0.42, metalness: 0.08 });
      const back = new THREE.MeshStandardMaterial({ color: 0x123f3d, emissive: 0x0b5f61, emissiveIntensity: 0.22 });
      const mesh = new THREE.Mesh(tileGeometry, [side, side, side, side, front, back]);
      mesh.position.x = (index - 1) * 1.35;
      mesh.position.y = index === 1 ? 0.28 : 0;
      mesh.rotation.z = (index - 1) * 0.12;
      tileGroup.add(mesh);
      return mesh;
    });
    scene.add(tileGroup);

    const baseParticlePositions = particlePositions.slice();
    const clock = new THREE.Clock();
    let sampleStartedAt = performance.now();
    let sampledFrames = 0;
    let restartScheduled = false;

    function resize() {
      const width = Math.max(1, root.clientWidth);
      const height = Math.max(1, root.clientHeight);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    }

    function updateLinks() {
      let linkCount = 0;
      const thresholdSquared = 1.45 * 1.45;
      for (let left = 0; left < budget.particles && linkCount < budget.maxLinks; left += 1) {
        const lx = particlePositions[left * 3];
        const ly = particlePositions[left * 3 + 1];
        const lz = particlePositions[left * 3 + 2];
        for (let right = left + 1; right < budget.particles && linkCount < budget.maxLinks; right += 1) {
          const rx = particlePositions[right * 3];
          const ry = particlePositions[right * 3 + 1];
          const rz = particlePositions[right * 3 + 2];
          const dx = lx - rx;
          const dy = ly - ry;
          const dz = lz - rz;
          if (dx * dx + dy * dy + dz * dz > thresholdSquared) continue;
          const offset = linkCount * 6;
          linkPositions.set([lx, ly, lz, rx, ry, rz], offset);
          linkCount += 1;
        }
      }
      linkGeometry.attributes.position.needsUpdate = true;
      linkGeometry.setDrawRange(0, linkCount * 2);
    }

    function scheduleQualityChange(next) {
      if (restartScheduled || next === quality) return;
      restartScheduled = true;
      renderer.setAnimationLoop(null);
      window.setTimeout(() => {
        if (destroyed) return;
        if (next === "canvas") startCanvasFallback();
        else startThreeLayer(THREE, next);
      }, 0);
    }

    function renderFrame() {
      const elapsed = clock.getElapsedTime();
      const now = performance.now();
      const boosted = now < effectBoostUntil;
      for (let index = 0; index < budget.particles; index += 1) {
        const offset = index * 3;
        particlePositions[offset] = baseParticlePositions[offset] + Math.sin(elapsed * 0.22 + index * 0.7) * 0.055;
        particlePositions[offset + 1] = baseParticlePositions[offset + 1] + Math.cos(elapsed * 0.18 + index * 0.51) * 0.05;
      }
      particleGeometry.attributes.position.needsUpdate = true;
      particleMaterial.opacity = boosted ? 0.96 : 0.78;
      particles.rotation.y = elapsed * 0.014;
      updateLinks();

      tiles.forEach((tile, index) => {
        tile.position.y = (index === 1 ? 0.28 : 0) + Math.sin(elapsed * 1.1 + index * 1.7) * (boosted ? 0.13 : 0.07);
        tile.rotation.y = Math.sin(elapsed * 0.55 + index) * 0.17;
      });
      tileGroup.rotation.y = Math.sin(elapsed * 0.24) * 0.08;
      movingLights.forEach((light, index) => {
        light.position.set(Math.sin(elapsed * 0.6 + index * Math.PI) * 5, Math.cos(elapsed * 0.47 + index) * 3, 4);
      });

      renderer.render(scene, camera);
      root.dataset.photonFrames = String(Number(root.dataset.photonFrames || "0") + 1);
      sampledFrames += 1;
      const sampleElapsed = now - sampleStartedAt;
      if (sampleElapsed >= 2000) {
        const averageFrameMs = sampleElapsed / Math.max(1, sampledFrames);
        const next = nextQuality(quality, averageFrameMs);
        sampleStartedAt = now;
        sampledFrames = 0;
        scheduleQualityChange(next);
      }
    }

    function onContextLost(event) {
      event.preventDefault();
      if (!destroyed) startCanvasFallback();
    }

    root.replaceChildren(renderer.domElement);
    setRootMode("three", quality);
    resize();
    window.addEventListener("resize", resize);
    renderer.domElement.addEventListener("webglcontextlost", onContextLost);
```

The layer cleanup must execute this exact resource pattern:

```javascript
    activeLayer = {
      pause() { renderer.setAnimationLoop(null); },
      resume() { renderer.setAnimationLoop(renderFrame); },
      destroy() {
        renderer.setAnimationLoop(null);
        renderer.domElement.removeEventListener("webglcontextlost", onContextLost);
        window.removeEventListener("resize", resize);
        scene.traverse((object) => {
          object.geometry?.dispose?.();
          const materials = Array.isArray(object.material) ? object.material : [object.material];
          for (const material of materials) {
            if (!material) continue;
            for (const value of Object.values(material)) value?.isTexture && value.dispose();
            material.dispose?.();
          }
        });
        renderer.dispose();
        renderer.domElement.remove();
      },
    };
    renderer.setAnimationLoop(renderFrame);
  }
```

- [ ] **Step 5: Boot the correct mode and expose the failure-tolerant page bridge**

Finish `photon_scene.js` with:

```javascript
  async function boot() {
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const quality = selectInitialQuality({
      width: window.innerWidth,
      coarse: window.matchMedia("(pointer: coarse)").matches,
      reducedMotion,
      webgl2: supportsWebGL2(),
    });
    if (quality === "static") return startStaticFallback();
    if (quality === "canvas") return startCanvasFallback();
    try {
      const THREE = await import("/vendor/three/three.module.min.js?v=0.185.1");
      if (!destroyed) startThreeLayer(THREE, quality);
    } catch (error) {
      console.warn("photon scene unavailable; using canvas fallback", error);
      if (!destroyed) startCanvasFallback();
    }
  }

  function onVisibilityChange() {
    if (!activeLayer) return;
    if (document.hidden) activeLayer.pause();
    else activeLayer.resume();
  }

  function destroy() {
    if (destroyed) return;
    destroyed = true;
    disposeActiveLayer();
    document.removeEventListener("visibilitychange", onVisibilityChange);
    window.removeEventListener("pagehide", destroy);
    window.removeEventListener("beforeunload", destroy);
    for (const dispose of disposers.splice(0)) dispose();
  }

  window.WenlingPhotonScene = {
    playAuthSuccess: () => sceneTransition("auth-success", 650),
    playLobbyReveal: () => sceneTransition("lobby-reveal", 620),
    notifyRoomChanges(changes) {
      root.dataset.photonRoomChanges = JSON.stringify(changes || []);
      effectBoostUntil = performance.now() + 700;
      window.setTimeout(() => delete root.dataset.photonRoomChanges, 700);
    },
    setStatus(kind) { root.dataset.photonStatus = kind || "idle"; },
    destroy,
  };

  document.addEventListener("visibilitychange", onVisibilityChange);
  window.addEventListener("pagehide", destroy, { once: true });
  window.addEventListener("beforeunload", destroy, { once: true });
  boot();
})();
```

- [ ] **Step 6: Add the base isolated scene CSS**

Create `static/photon_lobby.css` with this base; later tasks append page layouts:

```css
.photon-auth-page,
.photon-lobby-page {
  min-height: 100vh;
  margin: 0;
  overflow-x: hidden;
  background: #04090b;
  color: #eaffff;
}

.photon-scene-root {
  position: fixed;
  z-index: 0;
  inset: 0;
  overflow: hidden;
  background: #04090b;
  pointer-events: none;
}

.photon-scene-root canvas {
  display: block;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.photon-auth-page > :not(.photon-scene-root),
.photon-lobby-page > :not(.photon-scene-root) {
  position: relative;
  z-index: 1;
}

@media (prefers-reduced-motion: reduce) {
  .photon-auth-page *,
  .photon-lobby-page * {
    scroll-behavior: auto !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 7: Run runtime tests and syntax checks**

Run:

```powershell
$env:PYTHONPATH='src;packages/wenling_core'
.\.venv\Scripts\python.exe -m unittest tests.test_photon_frontend -v
node --check static\photon_scene.js
```

Expected: 4 photon tests pass; Node exits 0.

- [ ] **Step 8: Commit the scene runtime**

```powershell
git add static/photon_scene.js static/photon_lobby.css tests/test_photon_frontend.py
git commit -m "Add isolated photon scene runtime"
```

## Task 3: Rebuild Login and Registration as the Seamless Auth Stage

**Files:**
- Modify: `static/battle_login.html`
- Modify: `static/battle_lobby.js:1-190,407-457`
- Modify: `static/photon_lobby.css`
- Modify: `tests/test_photon_frontend.py`
- Modify: `tests/test_online_server.py:120-160`

**Interfaces:**
- Consumes: `window.WenlingPhotonScene`, existing `/api/auth/login`, `/api/auth/register`, and local storage session keys.
- Produces: `setAuthMode(mode)`, `applyAuthDefaults()`, and `navigateToLobby({ animate })` inside `battle_lobby.js`.
- Preserves: `loginAccountInput`, `loginPasswordInput`, `loginBtn`, `registerAccountInput`, `registerPasswordInput`, `inviteCodeInput`, `registerBtn`, `authStatusTitle`, `authStatusDetail`, and `lobbyMessage`.

- [ ] **Step 1: Add failing auth DOM and behavior tests**

Add to `PhotonFrontendTests`:

```python
    def test_auth_page_uses_photon_stage_and_preserves_contract_ids(self) -> None:
        html = (ROOT / "static" / "battle_login.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "battle_lobby.js").read_text(encoding="utf-8")
        battle_html = (ROOT / "static" / "battle.html").read_text(encoding="utf-8")

        self.assertIn('class="standalone-page auth-only-page photon-auth-page"', html)
        self.assertIn('id="photonSceneRoot"', html)
        self.assertIn('data-page="auth"', html)
        self.assertIn('/photon_lobby.css?v=20260711-photon-4', html)
        self.assertIn('/photon_scene.js?v=20260711-photon-4', html)
        self.assertIn('role="tablist"', html)
        self.assertIn('data-auth-mode="login"', html)
        self.assertIn('data-auth-mode="register"', html)
        self.assertIn('id="loginAuthPanel"', html)
        self.assertIn('id="registerAuthPanel"', html)
        self.assertIn('class="photon-auth-panel photon-register-panel" role="tabpanel" hidden', html)
        for element_id in (
            "loginAccountInput", "loginPasswordInput", "loginBtn",
            "registerAccountInput", "registerPasswordInput", "inviteCodeInput", "registerBtn",
            "authStatusTitle", "authStatusDetail", "lobbyMessage",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertNotIn("photon_scene.js", battle_html)
        self.assertIn("function setAuthMode", script)
        self.assertIn("function applyAuthDefaults", script)
        self.assertIn("async function navigateToLobby", script)
        self.assertIn('invite.value = "WL1234"', script)
        self.assertIn('input.placeholder = "推荐密码1234"', script)
        self.assertIn('PHOTON_TRANSITION_KEY', script)
```

In `OnlineServerTests.test_task6_review_owner_controls_frontend_contract`, move the default-initialization assertions from `login_html` to the already loaded `lobby_app` because Task 3 removes the inline script:

```python
        self.assertIn('invite.type = "password"', lobby_app)
        self.assertIn('invite.value = "WL1234"', lobby_app)
```

Keep `self.assertIn("推荐密码1234", login_html)` and the `inviteCodeInput` ID assertion on the HTML.

- [ ] **Step 2: Run the auth contract test and verify RED**

Run:

```powershell
$env:PYTHONPATH='src;packages/wenling_core'
.\.venv\Scripts\python.exe -m unittest tests.test_photon_frontend.PhotonFrontendTests.test_auth_page_uses_photon_stage_and_preserves_contract_ids -v
```

Expected: FAIL because the photon auth structure and helper functions do not exist.

- [ ] **Step 3: Replace `battle_login.html` with the approved semantic layout**

Use this structure, preserving the Chinese copy and IDs:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no" />
    <title>温岭麻将 登录</title>
    <link rel="stylesheet" href="/styles.css?v=20260708-lobby-split-1" />
    <link rel="stylesheet" href="/photon_lobby.css?v=20260711-photon-4" />
  </head>
  <body class="standalone-page auth-only-page photon-auth-page">
    <div id="photonSceneRoot" class="photon-scene-root" data-page="auth" aria-hidden="true"></div>
    <main class="photon-auth-shell">
      <header class="photon-topbar">
        <a class="photon-brand" href="/battle-login" aria-label="温岭麻将登录页"><span>W</span><b>温岭麻将</b></a>
        <span class="photon-system-status"><i></i> SYSTEM ONLINE</span>
      </header>
      <section class="photon-auth-stage">
        <div class="photon-auth-visual" aria-hidden="true"></div>
        <section class="photon-auth-console" aria-label="账号入口">
          <div class="photon-auth-tabs" role="tablist" aria-label="账号操作">
            <button type="button" role="tab" data-auth-mode="login" aria-selected="true" aria-controls="loginAuthPanel">登录</button>
            <button type="button" role="tab" data-auth-mode="register" aria-selected="false" aria-controls="registerAuthPanel">邀请码注册</button>
          </div>
          <section class="photon-auth-status" aria-live="polite">
            <strong id="authStatusTitle">未登录</strong>
            <span id="authStatusDetail">请输入账号和密码。</span>
          </section>
          <section id="loginAuthPanel" class="photon-auth-panel" role="tabpanel">
            <label>用户名<input id="loginAccountInput" class="wide-input" autocomplete="username" /></label>
            <label>密码<input id="loginPasswordInput" class="wide-input" type="password" autocomplete="current-password" /></label>
            <button id="loginBtn" class="primary photon-primary-action" type="button">连接大厅</button>
          </section>
          <section id="registerAuthPanel" class="photon-auth-panel photon-register-panel" role="tabpanel" hidden>
            <label>用户名<input id="registerAccountInput" class="wide-input" maxlength="12" autocomplete="username" /></label>
            <label>密码<input id="registerPasswordInput" class="wide-input" type="password" autocomplete="new-password" /></label>
            <label>邀请码<input id="inviteCodeInput" class="wide-input invite-code-input" maxlength="6" autocomplete="off" /></label>
            <button id="registerBtn" class="gold photon-primary-action" type="button">注册并连接</button>
          </section>
          <p class="photon-password-hint">推荐密码1234</p>
          <div id="lobbyMessage" class="lobby-message photon-inline-message" aria-live="polite"></div>
        </section>
      </section>
    </main>
    <script src="/photon_scene.js?v=20260711-photon-4" defer></script>
    <script src="/battle_lobby.js?v=20260711-photon-4" defer></script>
  </body>
</html>
```

- [ ] **Step 4: Add auth defaults, mode switching, and bounded scene navigation**

Add near the storage keys in `battle_lobby.js`:

```javascript
const PHOTON_TRANSITION_KEY = "wenling.photon.auth_to_lobby.v1";

function applyAuthDefaults() {
  const invite = $("inviteCodeInput");
  if (invite) {
    invite.type = "password";
    invite.value = "WL1234";
  }
  ["loginPasswordInput", "registerPasswordInput"].forEach((id) => {
    const input = $(id);
    if (input) input.placeholder = "推荐密码1234";
  });
}

function setAuthMode(mode) {
  const registerMode = mode === "register";
  const loginPanel = $("loginAuthPanel");
  const registerPanel = $("registerAuthPanel");
  if (loginPanel) loginPanel.hidden = registerMode;
  if (registerPanel) registerPanel.hidden = !registerMode;
  document.querySelectorAll("[data-auth-mode]").forEach((button) => {
    button.setAttribute("aria-selected", String(button.dataset.authMode === mode));
  });
  document.body.dataset.authMode = registerMode ? "register" : "login";
}

function wait(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function navigateToLobby({ animate = true } = {}) {
  try {
    sessionStorage.setItem(PHOTON_TRANSITION_KEY, "1");
  } catch {
    // sessionStorage can be unavailable in hardened browser profiles.
  }
  if (animate) {
    const transition = window.WenlingPhotonScene?.playAuthSuccess?.();
    await Promise.race([Promise.resolve(transition).catch(() => undefined), wait(700)]);
  }
  window.WenlingPhotonScene?.destroy?.();
  window.location.href = "/battle-lobby";
}
```

At the end of `setAuthStatus`, add:

```javascript
  const statusCard = document.querySelector(".auth-status-card, .photon-auth-status");
  if (statusCard) statusCard.classList.toggle("bad", Boolean(bad));
  window.WenlingPhotonScene?.setStatus?.(bad ? "error" : title.includes("成功") ? "success" : "loading");
```

Replace the existing single-class `const card = document.querySelector(".auth-status-card")` block with the `statusCard` block above so the legacy and photon pages never apply conflicting error state updates.

Replace direct `/battle-lobby` assignments in `login()` and `register()` with:

```javascript
    await navigateToLobby();
```

In `bindAuthEvents()`, bind the tabs before form buttons:

```javascript
  document.querySelectorAll("[data-auth-mode]").forEach((button) => {
    button.addEventListener("click", () => setAuthMode(button.dataset.authMode || "login"));
  });
```

At the beginning of `initAuthPage()` call:

```javascript
  applyAuthDefaults();
  setAuthMode("login");
```

For a token that is already valid, call `await navigateToLobby({ animate: false })` instead of assigning `window.location.href` directly.

- [ ] **Step 5: Add the auth-stage CSS section**

Append an auth-only section to `photon_lobby.css` defining these scoped selectors:

```css
.photon-auth-page .photon-auth-shell { min-height: 100svh; padding: 24px clamp(18px, 4vw, 64px); display: grid; grid-template-rows: auto 1fr; }
.photon-auth-page .photon-topbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.photon-auth-page .photon-brand { display: inline-flex; align-items: center; gap: 10px; color: #eaffff; text-decoration: none; font-weight: 900; }
.photon-auth-page .photon-brand > span { display: grid; place-items: center; width: 36px; height: 36px; border: 1px solid #68f5ff; border-radius: 7px; color: #68f5ff; box-shadow: 0 0 22px rgba(104,245,255,.28); }
.photon-auth-page .photon-system-status { display: inline-flex; align-items: center; gap: 7px; color: #a9c4c5; font-size: 12px; font-weight: 800; }
.photon-auth-page .photon-system-status i { width: 7px; height: 7px; border-radius: 50%; background: #45e58c; box-shadow: 0 0 12px #45e58c; }
.photon-auth-page .photon-auth-stage { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(340px, .75fr); align-items: center; gap: clamp(24px, 5vw, 80px); }
.photon-auth-page .photon-auth-copy > span { color: #68f5ff; font-size: 12px; font-weight: 900; }
.photon-auth-page .photon-auth-copy h1 { margin: 12px 0; color: #fff; font-size: clamp(42px, 6vw, 84px); line-height: 1.02; letter-spacing: 0; }
.photon-auth-page .photon-auth-copy p { max-width: 520px; margin: 0; color: #9bb0b1; font-size: 16px; line-height: 1.7; }
.photon-auth-page .photon-auth-console { align-self: end; margin-bottom: 4vh; padding: 14px; border: 1px solid rgba(104,245,255,.26); border-radius: 8px; background: rgba(3,15,18,.84); box-shadow: 0 18px 54px rgba(0,0,0,.34), 0 0 30px rgba(104,245,255,.08); backdrop-filter: blur(16px); }
.photon-auth-page .photon-auth-tabs { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; padding: 4px; border: 1px solid rgba(104,245,255,.18); border-radius: 7px; }
.photon-auth-page .photon-auth-tabs button { min-height: 38px; border: 0; border-radius: 5px; background: transparent; color: #8ca3a4; font-weight: 800; }
.photon-auth-page .photon-auth-tabs button[aria-selected="true"] { background: rgba(104,245,255,.14); color: #dfffff; box-shadow: inset 0 0 0 1px rgba(104,245,255,.25); }
.photon-auth-page .photon-auth-status { display: grid; gap: 3px; min-height: 54px; padding: 12px 2px 6px; color: #a7bcbc; }
.photon-auth-page .photon-auth-status strong { color: #eaffff; }
.photon-auth-page .photon-auth-status.bad, .photon-auth-page .photon-auth-status.bad strong { color: #ff7771; }
.photon-auth-page .photon-auth-panel { display: grid; grid-template-columns: 1fr 1fr auto; gap: 8px; }
.photon-auth-page [hidden] { display: none !important; }
.photon-auth-page .photon-register-panel { grid-template-columns: 1fr 1fr 1fr auto; }
.photon-auth-page .photon-auth-panel label { display: grid; gap: 5px; color: #9eb1b2; font-size: 12px; font-weight: 800; }
.photon-auth-page .photon-auth-panel input { min-width: 0; height: 42px; border: 1px solid rgba(104,245,255,.18); border-radius: 5px; background: rgba(255,255,255,.035); color: #eaffff; }
.photon-auth-page .photon-primary-action { align-self: end; min-width: 112px; min-height: 42px; border-color: #68f5ff; background: #68f5ff; color: #061012; font-weight: 900; box-shadow: 0 0 20px rgba(104,245,255,.25); }
.photon-auth-page .photon-password-hint { margin: 9px 0 0; color: #819798; font-size: 11px; }
.photon-auth-page .photon-inline-message { min-height: 18px; margin-top: 4px; }
```

- [ ] **Step 6: Run auth and existing online frontend tests**

Run:

```powershell
$env:PYTHONPATH='src;packages/wenling_core'
.\.venv\Scripts\python.exe -m unittest tests.test_photon_frontend tests.test_online_server.OnlineServerTests.test_task6_review_owner_controls_frontend_contract tests.test_online_server.OnlineServerTests.test_online_pages_load_expected_scripts -v
node --check static\battle_lobby.js
```

Expected: 7 focused tests pass; Node exits 0.

- [ ] **Step 7: Commit the auth stage**

```powershell
git add static/battle_login.html static/battle_lobby.js static/photon_lobby.css tests/test_photon_frontend.py tests/test_online_server.py
git commit -m "Redesign photon login and registration"
```

## Task 4: Rebuild the Three-Room Lobby and Incremental Room Feedback

**Files:**
- Modify: `static/battle_lobby.html`
- Modify: `static/battle_lobby.js:198-472`
- Modify: `static/photon_lobby.css`
- Modify: `tests/test_photon_frontend.py`
- Modify: `tests/test_online_server.py`

**Interfaces:**
- Consumes: existing `loadRooms()`, `normalizeRoomSummary()`, `renderSeatDots()`, `createOrJoinTable()`, `toggleReady()`, and `window.WenlingPhotonScene`.
- Produces: `setRoomAiPolicy(value)`, `changedRoomSlots(previousRooms, nextRooms)`, semantic `.room-table-slot` articles, `.room-primary-action[data-slot-index]`, and `.table-ready-btn[data-room-id]`.
- Preserves: `currentAccountLabel`, `currentRoleLabel`, `adminEntry`, `logoutBtn`, `roomAiPolicySelect`, `lobbyMessage`, and `roomTableGrid`.

- [ ] **Step 1: Add failing lobby structure and incremental-update tests**

Add to `PhotonFrontendTests`:

```python
    def test_lobby_page_uses_semantic_room_articles_and_photon_updates(self) -> None:
        html = (ROOT / "static" / "battle_lobby.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "battle_lobby.js").read_text(encoding="utf-8")
        self.assertIn('class="standalone-page room-lobby-page photon-lobby-page"', html)
        self.assertIn('id="photonSceneRoot"', html)
        self.assertIn('data-page="lobby"', html)
        self.assertEqual(html.count('<article class="room-table-slot'), 3)
        self.assertIn('id="roomAiPolicyLow"', html)
        self.assertIn('id="roomAiPolicyHigh"', html)
        for element_id in (
            "currentAccountLabel", "currentRoleLabel", "adminEntry", "logoutBtn",
            "roomAiPolicySelect", "lobbyMessage", "roomTableGrid",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn("function changedRoomSlots", script)
        self.assertIn("function setRoomAiPolicy", script)
        self.assertIn("ready_accounts", script)
        self.assertIn("room-primary-action", script)
        self.assertIn("notifyRoomChanges", script)
        self.assertIn("playLobbyReveal", script)
        self.assertIn("window.setInterval", script)
        self.assertIn("3000", script)
        self.assertNotIn('slot.disabled = disabled', script)

    def test_lobby_markup_never_nests_ready_button_inside_room_button(self) -> None:
        html = (ROOT / "static" / "battle_lobby.html").read_text(encoding="utf-8")
        self.assertNotIn('<button class="room-table-slot', html)
        self.assertIn('<article class="room-table-slot', html)
```

Add this live static-resource test to `OnlineServerTests`:

```python
    def test_photon_assets_serve_for_remote_clients_and_battle_page_is_isolated(self) -> None:
        login_html = self.open_path("/battle-login").decode("utf-8")
        lobby_html = self.open_path("/battle-lobby").decode("utf-8")
        battle_html = self.open_path("/battle").decode("utf-8")
        self.assertIn("photon_scene.js", login_html)
        self.assertIn("photon_scene.js", lobby_html)
        self.assertNotIn("photon_scene.js", battle_html)
        self.assertNotIn("vendor/three", battle_html)

        for path in (
            "/photon_scene.js",
            "/photon_lobby.css",
            "/vendor/three/three.module.min.js",
            "/vendor/three/three.core.min.js",
            "/vendor/three/LICENSE",
        ):
            request = urllib.request.Request(
                self.base + path,
                headers={"X-Forwarded-For": "192.168.1.22"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                self.assertGreater(int(response.headers["Content-Length"]), 100)
                self.assertEqual(response.status, 200)
```

- [ ] **Step 2: Run the lobby tests and verify RED**

Run:

```powershell
$env:PYTHONPATH='src;packages/wenling_core'
.\.venv\Scripts\python.exe -m unittest tests.test_photon_frontend.PhotonFrontendTests.test_lobby_page_uses_semantic_room_articles_and_photon_updates tests.test_photon_frontend.PhotonFrontendTests.test_lobby_markup_never_nests_ready_button_inside_room_button tests.test_online_server.OnlineServerTests.test_photon_assets_serve_for_remote_clients_and_battle_page_is_isolated -v
```

Expected: FAIL because the page still uses three room buttons, has no AI segments or diff functions, and `/battle-lobby` does not yet load the photon assets.

- [ ] **Step 3: Replace `battle_lobby.html` with the photon room network**

Use this structure:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no" />
    <title>温岭麻将 选桌</title>
    <link rel="stylesheet" href="/styles.css?v=20260708-lobby-split-1" />
    <link rel="stylesheet" href="/photon_lobby.css?v=20260711-photon-4" />
  </head>
  <body class="standalone-page room-lobby-page photon-lobby-page">
    <div id="photonSceneRoot" class="photon-scene-root" data-page="lobby" aria-hidden="true"></div>
    <main class="photon-lobby-shell">
      <header class="photon-lobby-topbar">
        <a class="photon-brand" href="/battle-lobby" aria-label="温岭麻将选桌大厅"><span>W</span><b>温岭麻将</b></a>
        <div class="photon-account-cluster">
          <span class="photon-online-dot" aria-hidden="true"></span>
          <strong id="currentAccountLabel">未登录</strong>
          <span id="currentRoleLabel" class="tag"></span>
          <a id="adminEntry" href="/battle-admin" hidden>管理后台</a>
          <button id="logoutBtn" type="button">退出登录</button>
        </div>
      </header>
      <section class="photon-lobby-heading">
        <div><span>ROOM NETWORK / 3</span><h1>选择牌桌</h1><p>实时房间网络</p></div>
        <div class="photon-ai-control" aria-label="新房间 AI 等级">
          <span>新房间 AI</span>
          <div role="group" aria-label="AI 等级">
            <button id="roomAiPolicyLow" type="button" data-ai-policy="low" aria-pressed="true">低级</button>
            <button id="roomAiPolicyHigh" type="button" data-ai-policy="high" aria-pressed="false">高级</button>
          </div>
          <select id="roomAiPolicySelect" class="photon-native-select" tabindex="-1" aria-hidden="true">
            <option value="low">低级 AI</option><option value="high">高级 AI</option>
          </select>
        </div>
      </section>
      <div id="lobbyMessage" class="lobby-message photon-lobby-message" aria-live="polite"></div>
      <section class="room-table-grid photon-room-grid" id="roomTableGrid" aria-label="房间桌位">
        <article class="room-table-slot room-table-empty" data-slot-index="0"></article>
        <article class="room-table-slot room-table-empty" data-slot-index="1"></article>
        <article class="room-table-slot room-table-empty" data-slot-index="2"></article>
      </section>
    </main>
    <script src="/photon_scene.js?v=20260711-photon-4" defer></script>
    <script src="/battle_lobby.js?v=20260711-photon-4" defer></script>
  </body>
</html>
```

- [ ] **Step 4: Add room diffing and keep ready state in normalized summaries**

Add `ready_accounts` to `normalizeRoomSummary()`:

```javascript
    ready_accounts: Array.isArray(room?.ready_accounts) ? [...room.ready_accounts].sort() : [],
```

Add:

```javascript
function roomFingerprint(room) {
  return JSON.stringify(room ? normalizeRoomSummary(room) : null);
}

function changedRoomSlots(previousRooms, nextRooms) {
  return Array.from({ length: 3 }, (_, slotIndex) => ({
    slot_index: slotIndex,
    room_id: nextRooms[slotIndex]?.room_id || "",
    status: roomStatusValue(nextRooms[slotIndex]),
    changed: roomFingerprint(previousRooms[slotIndex]) !== roomFingerprint(nextRooms[slotIndex]),
  })).filter((entry) => entry.changed);
}
```

- [ ] **Step 5: Replace `renderTableSlots()` with semantic independent actions**

Use this complete rendering shape:

```javascript
function renderTableSlots(rooms, maxRooms) {
  const previousRooms = lastRooms;
  const nextRooms = Array.isArray(rooms) ? rooms.slice(0, 3) : [];
  const changes = changedRoomSlots(previousRooms, nextRooms);
  lastRooms = nextRooms;
  lastMaxRooms = Number(maxRooms) || 3;
  const grid = $("roomTableGrid");
  if (!grid) return;
  const slots = Array.from(grid.querySelectorAll(".room-table-slot"));
  slots.forEach((slot, index) => {
    const room = roomForSlot(index);
    const status = roomStatusValue(room);
    const mine = Boolean(accountSeat(room));
    const emptySeat = room ? firstEmptySeat(room) : null;
    const disabled = Boolean(room && status === "playing" && !mine) || Boolean(room && !emptySeat && !mine);
    const ready = Boolean(room && (room.ready_accounts || []).includes(accountValue()));
    slot.dataset.roomId = room?.room_id || "";
    slot.setAttribute("aria-disabled", String(disabled));
    slot.className = [
      "room-table-slot",
      room ? "room-table-active" : "room-table-empty",
      mine ? "room-table-mine" : "",
      disabled ? "room-table-disabled" : "",
      status ? `room-status-${status}` : "",
    ].filter(Boolean).join(" ");
    slot.innerHTML = `
      <header class="room-table-head">
        <span class="room-table-index">0${index + 1}</span>
        <strong>${escapeHtml(room?.room_name || `${index + 1}号桌`)}</strong>
        <span class="tag room-status-tag">${escapeHtml(room ? roomStatusLabel(room.status) : "空桌")}</span>
      </header>
      <div class="room-table-icon" aria-label="四个座位状态">
        <span class="room-table-felt" aria-hidden="true"></span>
        ${renderSeatDots(room)}
      </div>
      <div class="room-table-meta"><span>房主：${escapeHtml(room?.owner_account || "-")}</span><span>AI：${room?.ai_policy === "high" ? "高级" : "低级"}</span></div>
      <footer class="room-table-actions">
        <button class="room-primary-action" type="button" data-slot-index="${index}" ${disabled ? "disabled" : ""}>${tableActionText(room)}</button>
        ${mine ? `<button class="table-ready-btn" type="button" data-room-id="${escapeHtml(room.room_id)}">${ready ? "取消准备" : "准备"}</button>` : ""}
      </footer>`;
  });
  if (changes.length) window.WenlingPhotonScene?.notifyRoomChanges?.(changes);
}
```

- [ ] **Step 6: Bind independent room and AI actions and preserve lobby reveal**

Add:

```javascript
function setRoomAiPolicy(value) {
  const normalized = value === "high" ? "high" : "low";
  if ($("roomAiPolicySelect")) $("roomAiPolicySelect").value = normalized;
  document.querySelectorAll("[data-ai-policy]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.aiPolicy === normalized));
  });
}

function consumePhotonLobbyTransition() {
  try {
    const pending = sessionStorage.getItem(PHOTON_TRANSITION_KEY) === "1";
    sessionStorage.removeItem(PHOTON_TRANSITION_KEY);
    return pending;
  } catch {
    return false;
  }
}
```

Replace `bindLobbyEvents()` with event delegation for three explicit targets:

```javascript
function bindLobbyEvents() {
  if ($("logoutBtn")) $("logoutBtn").addEventListener("click", logout);
  document.querySelectorAll("[data-ai-policy]").forEach((button) => {
    button.addEventListener("click", () => setRoomAiPolicy(button.dataset.aiPolicy || "low"));
  });
  if ($("roomTableGrid")) {
    $("roomTableGrid").addEventListener("click", (event) => {
      const readyButton = event.target.closest(".table-ready-btn");
      if (readyButton) return void toggleReady(readyButton.dataset.roomId);
      const primaryButton = event.target.closest(".room-primary-action");
      if (!primaryButton || primaryButton.disabled) return;
      createOrJoinTable(Number(primaryButton.dataset.slotIndex || 0));
    });
  }
}
```

Replace `initLobbyPage()` with:

```javascript
async function initLobbyPage() {
  const revealFromAuth = consumePhotonLobbyTransition();
  bindLobbyEvents();
  setRoomAiPolicy($("roomAiPolicySelect")?.value || "low");
  updateSessionUi();
  await loadRooms();
  if (revealFromAuth) {
    await Promise.resolve(window.WenlingPhotonScene?.playLobbyReveal?.()).catch(() => undefined);
  }
  roomRefreshTimer = window.setInterval(() => {
    loadRooms().catch((error) => console.warn("room refresh failed", error));
  }, 3000);
}
```

Before navigation in `enterRoom()` and before redirect in `logout()`, call:

```javascript
  window.WenlingPhotonScene?.destroy?.();
```

- [ ] **Step 7: Add the lobby layout CSS section**

Append selectors for `.photon-lobby-page .photon-lobby-shell`, `.photon-lobby-topbar`, `.photon-account-cluster`, `.photon-lobby-heading`, `.photon-ai-control`, `.photon-room-grid`, `.room-table-slot`, `.room-table-icon`, `.room-table-felt`, `.room-table-seat`, `.room-table-actions`, `.room-primary-action`, and `.table-ready-btn`.

Use these fixed layout rules:

```css
.photon-lobby-page .photon-lobby-shell { width: min(1400px, calc(100vw - 40px)); min-height: 100svh; margin: 0 auto; padding: 22px 0 40px; }
.photon-lobby-page .photon-lobby-topbar { display: flex; align-items: center; justify-content: space-between; gap: 18px; min-height: 48px; }
.photon-lobby-page .photon-brand { display: inline-flex; align-items: center; gap: 10px; color: #eaffff; text-decoration: none; font-weight: 900; }
.photon-lobby-page .photon-brand > span { display: grid; place-items: center; width: 36px; height: 36px; border: 1px solid #68f5ff; border-radius: 7px; color: #68f5ff; box-shadow: 0 0 22px rgba(104,245,255,.28); }
.photon-lobby-page .photon-account-cluster { display: flex; align-items: center; gap: 9px; }
.photon-lobby-page .photon-account-cluster a, .photon-lobby-page .photon-account-cluster button { display: inline-flex; align-items: center; min-height: 36px; padding: 0 10px; border: 1px solid rgba(104,245,255,.2); border-radius: 5px; background: rgba(3,15,18,.74); color: #dfffff; text-decoration: none; }
.photon-lobby-page .photon-online-dot { width: 7px; height: 7px; border-radius: 50%; background: #45e58c; box-shadow: 0 0 12px #45e58c; }
.photon-lobby-page .photon-lobby-heading { display: flex; align-items: end; justify-content: space-between; gap: 24px; padding: clamp(34px, 7vh, 76px) 0 20px; }
.photon-lobby-page .photon-lobby-heading h1 { margin: 5px 0; color: #fff; font-size: clamp(36px, 5vw, 64px); letter-spacing: 0; }
.photon-lobby-page .photon-lobby-heading p { margin: 0; color: #90a6a7; }
.photon-lobby-page .photon-ai-control { display: grid; gap: 7px; min-width: 224px; }
.photon-lobby-page .photon-ai-control > div { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; padding: 4px; border: 1px solid rgba(104,245,255,.2); border-radius: 7px; background: rgba(3,15,18,.7); }
.photon-lobby-page [data-ai-policy] { min-height: 36px; border: 0; border-radius: 5px; background: transparent; color: #91a7a8; }
.photon-lobby-page [data-ai-policy][aria-pressed="true"] { background: rgba(104,245,255,.14); color: #eaffff; box-shadow: inset 0 0 0 1px rgba(104,245,255,.28); }
.photon-lobby-page .photon-native-select { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
.photon-lobby-page .photon-room-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.photon-lobby-page .room-table-slot { display: grid; grid-template-rows: auto minmax(220px, 1fr) auto auto; gap: 12px; min-height: 430px; padding: 15px; border: 1px solid rgba(104,245,255,.2); border-radius: 8px; background: rgba(3,16,19,.82); color: #eaffff; box-shadow: 0 18px 48px rgba(0,0,0,.3); backdrop-filter: blur(14px); }
.photon-lobby-page .room-table-mine { border-color: #68f5ff; box-shadow: 0 0 0 2px rgba(104,245,255,.12), 0 18px 52px rgba(0,0,0,.34); }
.photon-lobby-page .room-table-empty .room-status-tag { color: #aebabb; background: rgba(174,186,187,.12); }
.photon-lobby-page .room-status-open .room-status-tag, .photon-lobby-page .room-status-waiting .room-status-tag { color: #62e39d; background: rgba(69,229,140,.12); }
.photon-lobby-page .room-status-playing .room-status-tag, .photon-lobby-page .room-status-round_over .room-status-tag { color: #ffbf63; background: rgba(255,191,99,.12); }
.photon-lobby-page .room-status-closing .room-status-tag, .photon-lobby-page .room-status-closed .room-status-tag { color: #ee5a54; background: rgba(238,90,84,.12); }
.photon-lobby-page .room-table-head { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 9px; }
.photon-lobby-page .room-table-index { color: #68f5ff; font-size: 12px; font-weight: 900; }
.photon-lobby-page .room-status-tag { justify-self: end; }
.photon-lobby-page .room-table-icon { position: relative; min-height: 220px; }
.photon-lobby-page .room-table-felt { position: absolute; inset: 48px 52px; border: 7px solid #35484c; border-radius: 8px; background: #0f665a; box-shadow: inset 0 0 0 1px rgba(104,245,255,.22), 0 16px 34px rgba(0,0,0,.36); }
.photon-lobby-page .room-table-seat { position: absolute; display: grid; place-items: center; width: 78px; min-height: 47px; padding: 4px; border: 1px solid rgba(104,245,255,.22); border-radius: 6px; background: rgba(223,255,255,.92); color: #173b3c; }
.photon-lobby-page .room-table-seat b, .photon-lobby-page .room-table-seat em { display: block; max-width: 68px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-style: normal; }
.photon-lobby-page .room-table-seat.ready { border-color: #ffbf63; box-shadow: 0 0 14px rgba(255,191,99,.3); }
.photon-lobby-page .room-table-seat.mine { border-color: #68f5ff; box-shadow: 0 0 16px rgba(104,245,255,.4); }
.photon-lobby-page .room-table-seat:nth-of-type(2) { top: 0; left: 50%; transform: translateX(-50%); }
.photon-lobby-page .room-table-seat:nth-of-type(3) { top: 50%; right: 0; transform: translateY(-50%); }
.photon-lobby-page .room-table-seat:nth-of-type(4) { bottom: 0; left: 50%; transform: translateX(-50%); }
.photon-lobby-page .room-table-seat:nth-of-type(5) { top: 50%; left: 0; transform: translateY(-50%); }
.photon-lobby-page .room-table-meta { display: flex; justify-content: space-between; gap: 10px; color: #90a6a7; font-size: 13px; }
.photon-lobby-page .room-table-actions { display: grid; grid-template-columns: 1fr auto; gap: 8px; }
.photon-lobby-page .room-primary-action, .photon-lobby-page .table-ready-btn { min-height: 40px; border-radius: 5px; font-weight: 900; }
.photon-lobby-page .room-primary-action { border-color: #68f5ff; background: #68f5ff; color: #061012; }
.photon-lobby-page .table-ready-btn { border-color: #ffbf63; background: #ffbf63; color: #1f241a; }
.photon-lobby-page .room-primary-action:disabled { cursor: not-allowed; opacity: .42; }
```

- [ ] **Step 8: Run lobby and existing online tests**

Run:

```powershell
$env:PYTHONPATH='src;packages/wenling_core'
.\.venv\Scripts\python.exe -m unittest tests.test_photon_frontend tests.test_online_server.OnlineServerTests.test_task6_review_owner_controls_frontend_contract tests.test_online_server.OnlineServerTests.test_online_lobby_page_is_public_from_remote_clients tests.test_online_server.OnlineServerTests.test_photon_assets_serve_for_remote_clients_and_battle_page_is_isolated -v
node --check static\battle_lobby.js
```

Expected: 10 focused tests pass; Node exits 0.

- [ ] **Step 9: Commit the photon room lobby**

```powershell
git add static/battle_lobby.html static/battle_lobby.js static/photon_lobby.css tests/test_photon_frontend.py tests/test_online_server.py
git commit -m "Redesign photon room lobby"
```

## Task 5: Finish Responsive Layout, Accessibility, and Motion Polish

**Files:**
- Modify: `static/photon_lobby.css`
- Modify: `tests/test_photon_frontend.py`

**Interfaces:**
- Consumes: auth and lobby classes from Tasks 3 and 4.
- Produces: stable desktop, portrait-mobile, landscape-mobile, focus-visible, loading, error, transition, and reduced-motion states.

- [ ] **Step 1: Add failing responsive and isolation CSS tests**

Add to `PhotonFrontendTests`:

```python
    def test_photon_css_is_scoped_responsive_and_accessible(self) -> None:
        css = (ROOT / "static" / "photon_lobby.css").read_text(encoding="utf-8")
        for expected in (
            ".photon-auth-page",
            ".photon-lobby-page",
            "@media (max-width: 760px)",
            "(pointer: coarse)",
            "@media (max-height: 520px)",
            "@media (prefers-reduced-motion: reduce)",
            ":focus-visible",
            "minmax(0, 1fr)",
            "overflow-x: hidden",
            "data-photon-transition",
            "data-photon-status",
        ):
            self.assertIn(expected, css)
        self.assertNotIn(".battle-app-mode", css)
        self.assertNotIn("letter-spacing: -", css)
```

- [ ] **Step 2: Run the CSS contract and verify RED**

Run:

```powershell
$env:PYTHONPATH='src;packages/wenling_core'
.\.venv\Scripts\python.exe -m unittest tests.test_photon_frontend.PhotonFrontendTests.test_photon_css_is_scoped_responsive_and_accessible -v
```

Expected: FAIL until all responsive, state, and focus selectors exist.

- [ ] **Step 3: Add transition, status, focus, and stable-dimension states**

Append:

```css
.photon-auth-page button:focus-visible,
.photon-auth-page input:focus-visible,
.photon-lobby-page button:focus-visible,
.photon-lobby-page a:focus-visible {
  outline: 2px solid #fff;
  outline-offset: 3px;
}

.photon-scene-root[data-photon-transition="auth-success"] { filter: brightness(1.24); }
.photon-scene-root[data-photon-transition="lobby-reveal"] { filter: brightness(1.12); }
.photon-scene-root[data-photon-status="error"] { box-shadow: inset 0 0 90px rgba(238,78,72,.12); }
.photon-scene-root[data-photon-status="success"] { box-shadow: inset 0 0 90px rgba(69,229,140,.10); }

.photon-auth-page .photon-auth-console,
.photon-lobby-page .room-table-slot {
  transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease, opacity 180ms ease;
}

.photon-lobby-page .room-table-slot:hover {
  transform: translateY(-3px);
  border-color: rgba(104,245,255,.42);
}
```

- [ ] **Step 4: Add portrait and coarse-pointer rules**

Append:

```css
@media (max-width: 760px), (pointer: coarse) {
  .photon-auth-page .photon-auth-shell { min-height: 100svh; padding: 16px 14px max(14px, env(safe-area-inset-bottom)); }
  .photon-auth-page .photon-auth-stage { grid-template-columns: 1fr; align-content: space-between; gap: 18px; padding-top: 22px; }
  .photon-auth-page .photon-auth-copy h1 { font-size: 42px; }
  .photon-auth-page .photon-auth-copy p { font-size: 14px; }
  .photon-auth-page .photon-auth-console { align-self: end; width: 100%; margin: 0; }
  .photon-auth-page .photon-auth-panel, .photon-auth-page .photon-register-panel { grid-template-columns: 1fr; max-height: min(48svh, 420px); overflow-y: auto; }
  .photon-auth-page .photon-primary-action { width: 100%; }
  .photon-lobby-page .photon-lobby-shell { width: min(100% - 20px, 560px); padding: 12px 0 28px; }
  .photon-lobby-page .photon-lobby-topbar { align-items: flex-start; }
  .photon-lobby-page .photon-account-cluster { justify-content: flex-end; flex-wrap: wrap; }
  .photon-lobby-page .photon-lobby-heading { display: grid; padding: 28px 0 16px; }
  .photon-lobby-page .photon-lobby-heading h1 { font-size: 38px; }
  .photon-lobby-page .photon-ai-control { min-width: 0; width: 100%; }
  .photon-lobby-page .photon-room-grid { grid-template-columns: 1fr; gap: 12px; }
  .photon-lobby-page .room-table-slot { min-height: 390px; grid-template-rows: auto 210px auto auto; }
  .photon-lobby-page .room-primary-action, .photon-lobby-page .table-ready-btn { min-height: 44px; }
}
```

- [ ] **Step 5: Add landscape-phone containment**

Append:

```css
@media (max-height: 520px) and (orientation: landscape) {
  .photon-auth-page .photon-auth-shell { padding-top: 10px; padding-bottom: 10px; }
  .photon-auth-page .photon-topbar { min-height: 36px; }
  .photon-auth-page .photon-auth-stage { grid-template-columns: .8fr 1.2fr; align-items: end; gap: 14px; padding-top: 8px; }
  .photon-auth-page .photon-auth-copy h1 { font-size: 32px; }
  .photon-auth-page .photon-auth-copy p { display: none; }
  .photon-auth-page .photon-auth-console { max-height: calc(100svh - 62px); overflow-y: auto; }
  .photon-auth-page .photon-auth-panel, .photon-auth-page .photon-register-panel { grid-template-columns: repeat(2, minmax(0, 1fr)); max-height: none; }
  .photon-lobby-page .photon-lobby-heading { padding-top: 18px; }
  .photon-lobby-page .photon-room-grid { grid-template-columns: repeat(3, minmax(240px, 1fr)); overflow-x: auto; scroll-snap-type: x mandatory; }
  .photon-lobby-page .room-table-slot { min-height: 340px; scroll-snap-align: start; }
}
```

Landscape may scroll the room rail horizontally because each module remains touchable and readable; portrait and desktop must never scroll horizontally.

- [ ] **Step 6: Run CSS and frontend contracts**

Run:

```powershell
$env:PYTHONPATH='src;packages/wenling_core'
.\.venv\Scripts\python.exe -m unittest tests.test_photon_frontend -v
git diff --check
```

Expected: 8 photon tests pass; diff check exits 0.

- [ ] **Step 7: Commit responsive polish**

```powershell
git add static/photon_lobby.css tests/test_photon_frontend.py
git commit -m "Polish photon lobby responsiveness"
```

## Task 6: Verify HTTP Isolation, Browser Rendering, Android Packaging, and Regression Safety

**Files:**
- Test: `tests/test_online_server.py`
- Test: `tests/test_photon_frontend.py`
- Test: `tests/test_repository_boundaries.py`
- Verify only: `static/battle.html`, `static/battle_app.js`, `static/battle_geometry_v7.css`

**Interfaces:**
- Consumes: completed static pages and runtime assets.
- Produces: HTTP isolation coverage, desktop/mobile screenshots, nonblank scene evidence, functional auth/lobby evidence, Android APK asset evidence, and a clean full test run.

- [ ] **Step 1: Re-run the live HTTP isolation test added in Task 4**

Run:

```powershell
$env:PYTHONPATH='src;packages/wenling_core'
.\.venv\Scripts\python.exe -m unittest tests.test_online_server.OnlineServerTests.test_photon_assets_serve_for_remote_clients_and_battle_page_is_isolated -v
```

Expected: PASS. Stop execution if any page or local asset returns a failure; the failing URL identifies the owning task to reopen.

- [ ] **Step 2: Run focused and full automated verification**

Run:

```powershell
$env:PYTHONPATH='src;packages/wenling_core'
.\.venv\Scripts\python.exe -m unittest tests.test_photon_frontend tests.test_online_server tests.test_repository_boundaries -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check static\photon_scene.js
node --check static\battle_lobby.js
git diff --check
```

Expected: zero failures and zero syntax or diff errors.

- [ ] **Step 3: Prove battle source files are unchanged from the approved design base**

Run:

```powershell
git diff --exit-code a758440 -- static/battle.html static/battle_app.js static/battle_geometry_v7.css
```

Expected: no output and exit code 0.

- [ ] **Step 4: Start an isolated local QA server**

Run in PowerShell:

```powershell
$port = 8772
while (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue) { $port += 1 }
$env:WENLING_ADMIN_USERNAME = 'root'
$env:WENLING_ADMIN_PASSWORD = '1234'
$env:WENLING_INVITE_CODES = 'WL1234'
$server = Start-Process -FilePath '.\.venv\Scripts\python.exe' -ArgumentList @('-m','wenling_lan_host','--host','127.0.0.1','--port',"$port",'--data-dir','data/photon-qa') -WindowStyle Hidden -PassThru
$health = "http://127.0.0.1:$port/api/health"
Invoke-RestMethod $health
Write-Output "http://127.0.0.1:$port/battle-login"
```

Expected: JSON with `ok: true`. Keep `$server` and `$port` for cleanup and browser URLs.

- [ ] **Step 5: Verify desktop login, registration, transition, and lobby in the in-app browser**

Use the browser skill and set viewport `1280x720`.

Open the exact `battle-login` URL printed by Step 4, then verify in one bounded DOM evaluation:

```javascript
({
  mode: document.querySelector('#photonSceneRoot')?.dataset.photonMode,
  quality: document.querySelector('#photonSceneRoot')?.dataset.photonQuality,
  frames: Number(document.querySelector('#photonSceneRoot')?.dataset.photonFrames || 0),
  canvasCount: document.querySelectorAll('#photonSceneRoot canvas').length,
  overflow: document.documentElement.scrollWidth - innerWidth,
  registerHidden: document.querySelector('#registerAuthPanel')?.hidden,
})
```

Expected: mode `three`, quality `desktop` or `low`, frames greater than 5, canvas count 1, overflow at most 0, and register hidden true.

Click the unique `邀请码注册` tab, then verify `registerAuthPanel.hidden === false`, `inviteCodeInput.type === 'password'`, and `inviteCodeInput.value === 'WL1234'`.

Switch back to login, fill `root` and `1234`, submit, and wait for `/battle-lobby`. Verify exactly three `.room-table-slot` articles, visible admin entry, visible logout button, and no nested `.room-table-slot button .table-ready-btn` structure.

- [ ] **Step 6: Verify mobile portrait and landscape containment**

At `390x844`, reload login and lobby and verify:

```javascript
({
  overflow: document.documentElement.scrollWidth - innerWidth,
  inputs: Array.from(document.querySelectorAll('input')).map((input) => {
    const rect = input.getBoundingClientRect();
    return { id: input.id, width: rect.width, right: rect.right };
  }),
  roomWidths: Array.from(document.querySelectorAll('.room-table-slot')).map((room) => room.getBoundingClientRect().width),
})
```

Expected: overflow at most 0, every visible input right edge at or before viewport width, and every room width greater than 300 px.

At `844x390`, verify the auth console is fully reachable and the lobby uses the intended horizontal room rail without page-level vertical overlap. Reset viewport after QA.

- [ ] **Step 7: Save screenshots and perform a canvas-region pixel check**

Save screenshots from the browser session to:

- `data/photon-qa/desktop-login.png`
- `data/photon-qa/mobile-login.png`
- `data/photon-qa/desktop-lobby.png`

After obtaining the in-app browser `tab`, save each current viewport with the browser Node session:

```javascript
var photonFs = await import("node:fs/promises");
var photonPath = await import("node:path");
var photonQaDir = photonPath.join(nodeRepl.cwd, "data", "photon-qa");
await photonFs.mkdir(photonQaDir, { recursive: true });
await photonFs.writeFile(photonPath.join(photonQaDir, "desktop-login.png"), await tab.screenshot({ fullPage: false }));
```

Repeat the final `writeFile` call after switching to the portrait login viewport and after navigating to the desktop lobby, using `mobile-login.png` and `desktop-lobby.png` respectively.

Use the upper-right scene region, which contains WebGL tiles and no DOM form, for a pixel-variance check. Run:

```powershell
Add-Type -AssemblyName System.Drawing
$paths = @('data/photon-qa/desktop-login.png','data/photon-qa/mobile-login.png','data/photon-qa/desktop-lobby.png')
foreach ($path in $paths) {
  $bitmap = [System.Drawing.Bitmap]::FromFile((Resolve-Path $path))
  try {
    $values = New-Object System.Collections.Generic.List[int]
    $x0 = [int]($bitmap.Width * 0.55)
    $x1 = [int]($bitmap.Width * 0.95)
    $y0 = [int]($bitmap.Height * 0.08)
    $y1 = [int]($bitmap.Height * 0.58)
    for ($x = $x0; $x -lt $x1; $x += 12) {
      for ($y = $y0; $y -lt $y1; $y += 12) {
        $color = $bitmap.GetPixel($x, $y)
        $values.Add([int](0.2126 * $color.R + 0.7152 * $color.G + 0.0722 * $color.B))
      }
    }
    $range = ($values | Measure-Object -Maximum).Maximum - ($values | Measure-Object -Minimum).Minimum
    if ($range -lt 24) { throw "$path scene region is visually blank: luminance range $range" }
  } finally {
    $bitmap.Dispose()
  }
}
```

Expected: no exception; each scene region has luminance range at least 24. Visually inspect each screenshot for framing, overlap, readable Chinese text, and rendered Mahjong tiles.

- [ ] **Step 8: Verify battle navigation has no photon runtime**

Create or enter a room from the QA lobby, follow the room action into its generated `/battle` URL, and evaluate:

```javascript
({
  photonRoot: document.querySelectorAll('#photonSceneRoot').length,
  photonCanvas: document.querySelectorAll('.photon-scene-root canvas').length,
  photonApi: typeof window.WenlingPhotonScene,
  battleView: Boolean(document.querySelector('#gameView')),
})
```

Expected: `photonRoot` 0, `photonCanvas` 0, `photonApi` `undefined`, and `battleView` true.

- [ ] **Step 9: Build and inspect the Android phone APK**

Run:

```powershell
$env:JAVA_HOME = (Resolve-Path 'tools/android-build/jdk-extract/jdk-17.0.19+10').Path
$env:PATH = "$env:JAVA_HOME\bin;$env:PATH"
.\android-host\gradlew.bat -p android-host :app:assemblePhoneDebug
$apk = 'android-host/app/build/outputs/apk/phone/debug/app-phone-debug.apk'
jar tf $apk | Select-String 'assets/(battle_lobby.html|photon_scene.js|photon_lobby.css|vendor/three/three.module.min.js|vendor/three/three.core.min.js|vendor/three/LICENSE)'
```

Expected: Gradle reports `BUILD SUCCESSFUL`; all six asset paths appear in the APK listing.

- [ ] **Step 10: Stop the isolated QA server and confirm a clean working tree**

Run:

```powershell
Stop-Process -Id $server.Id
git status --short
```

Expected: no tracked changes. `data/photon-qa/` is ignored by `data/*` and must not be added.

## Final Verification Checklist

- [ ] `three@0.185.1` is exact in `package.json` and `package-lock.json`.
- [ ] The vendored module is local, 365,552 bytes, and accompanied by the MIT license.
- [ ] Login defaults to the login tab; registration is hidden until selected.
- [ ] Invite code is masked and prefilled with `WL1234`; password copy remains `推荐密码1234`.
- [ ] Auth success waits no more than 700 ms and never blocks navigation on scene failure.
- [ ] The lobby has exactly three semantic room articles and independent primary/ready actions.
- [ ] AI segmented buttons remain synchronized with `roomAiPolicySelect`.
- [ ] Polling remains 3000 ms and only changed rooms trigger scene feedback.
- [ ] Desktop, mobile portrait, and mobile landscape layouts meet their overflow expectations.
- [ ] Three.js, Canvas, and static modes follow the fixed budgets and downgrade rules.
- [ ] Hidden pages pause; page exit disposes resources.
- [ ] The battle page has no photon root, canvas, API, import, or source diff.
- [ ] Android APK includes every new lobby asset.
- [ ] Full Python tests, JS syntax checks, and `git diff --check` pass.
