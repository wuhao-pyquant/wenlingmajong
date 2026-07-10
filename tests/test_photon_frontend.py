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

    def run_browser_probe(self, probe: str, **overrides: object) -> dict:
        config = {
            "page": "auth",
            "commonjs": False,
            "hidden": False,
            "webgl2": False,
            "canvas2dLimit": None,
            "coarse": False,
            "width": 1280,
            "injectThree": False,
            "failRendererAfter": None,
        }
        config.update(overrides)
        return self.run_node_json(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const config = {json.dumps(config)};
            let now = 0;
            let nextHandle = 1;
            let canvas2dCalls = 0;
            let rendererConstructs = 0;
            let timerError = null;
            const rafCallbacks = new Map();
            const timerCallbacks = new Map();
            const renderers = [];
            const pointLights = [];
            const documentListeners = new Map();
            const windowListeners = new Map();

            function addListener(registry, type, callback) {{
              if (!registry.has(type)) registry.set(type, new Set());
              registry.get(type).add(callback);
            }}

            function removeListener(registry, type, callback) {{
              registry.get(type)?.delete(callback);
            }}

            function dispatch(registry, type, event = {{type}}) {{
              for (const callback of [...(registry.get(type) || [])]) callback(event);
            }}

            function listenerCount() {{
              return [...documentListeners.values(), ...windowListeners.values()]
                .reduce((total, callbacks) => total + callbacks.size, 0);
            }}

            const canvasContext = {{
              clearRect() {{}}, beginPath() {{}}, arc() {{}}, fill() {{}},
              fillRect() {{}}, strokeRect() {{}}, fillText() {{}},
            }};

            function makeCanvas() {{
              const listeners = new Map();
              return {{
                width: 0,
                height: 0,
                removed: false,
                getContext(kind) {{
                  if (kind === 'webgl2') return config.webgl2 ? {{}} : null;
                  if (kind !== '2d') return null;
                  canvas2dCalls += 1;
                  if (config.canvas2dLimit !== null && canvas2dCalls > config.canvas2dLimit) return null;
                  return canvasContext;
                }},
                addEventListener(type, callback) {{ addListener(listeners, type, callback); }},
                removeEventListener(type, callback) {{ removeListener(listeners, type, callback); }},
                remove() {{ this.removed = true; }},
              }};
            }}

            const root = {{
              dataset: config.page === null ? {{}} : {{page: config.page}},
              clientWidth: 1280,
              clientHeight: 720,
              children: [],
              setAttribute(name, value) {{ this.attributes = {{...(this.attributes || {{}}), [name]: value}}; }},
              replaceChildren(...children) {{ this.children = children; }},
            }};

            const document = {{
              hidden: config.hidden,
              getElementById: (id) => id === 'photonSceneRoot' ? root : null,
              createElement: () => makeCanvas(),
              addEventListener(type, callback) {{ addListener(documentListeners, type, callback); }},
              removeEventListener(type, callback) {{ removeListener(documentListeners, type, callback); }},
            }};

            const window = {{
              innerWidth: config.width,
              devicePixelRatio: 2,
              matchMedia(query) {{
                return {{matches: query.includes('pointer') ? config.coarse : false}};
              }},
              requestAnimationFrame(callback) {{
                const handle = nextHandle++;
                rafCallbacks.set(handle, callback);
                return handle;
              }},
              cancelAnimationFrame(handle) {{ rafCallbacks.delete(handle); }},
              setTimeout(callback) {{
                const handle = nextHandle++;
                timerCallbacks.set(handle, callback);
                return handle;
              }},
              clearTimeout(handle) {{ timerCallbacks.delete(handle); }},
              addEventListener(type, callback) {{ addListener(windowListeners, type, callback); }},
              removeEventListener(type, callback) {{ removeListener(windowListeners, type, callback); }},
            }};

            function vector() {{
              return {{
                setCalls: 0,
                set(...values) {{ this.setCalls += 1; this.values = values; }},
              }};
            }}

            class Object3D {{
              constructor(geometry = null, material = null) {{
                this.geometry = geometry;
                this.material = material;
                this.children = [];
                this.position = vector();
                this.rotation = vector();
              }}
              add(...objects) {{ this.children.push(...objects); }}
            }}

            class Scene extends Object3D {{
              traverse(callback) {{
                const visit = (object) => {{
                  callback(object);
                  for (const child of object.children || []) visit(child);
                }};
                visit(this);
              }}
            }}
            class Group extends Object3D {{}}
            class Points extends Object3D {{}}
            class LineSegments extends Object3D {{}}
            class Mesh extends Object3D {{}}
            class AmbientLight extends Object3D {{}}
            class DirectionalLight extends Object3D {{}}
            class PointLight extends Object3D {{
              constructor(...args) {{
                super();
                this.args = args;
                pointLights.push(this);
              }}
            }}
            class PerspectiveCamera extends Object3D {{
              updateProjectionMatrix() {{}}
            }}
            class BufferAttribute {{
              constructor(array, itemSize) {{ this.array = array; this.itemSize = itemSize; }}
            }}
            class BufferGeometry {{
              constructor() {{ this.attributes = {{}}; }}
              setAttribute(name, attribute) {{ this.attributes[name] = attribute; }}
              setDrawRange() {{}}
              dispose() {{ this.disposed = true; }}
            }}
            class BoxGeometry extends BufferGeometry {{}}
            class Material {{
              constructor(properties = {{}}) {{ Object.assign(this, properties); }}
              dispose() {{ this.disposed = true; }}
            }}
            class CanvasTexture {{
              constructor(canvas) {{ this.canvas = canvas; this.isTexture = true; }}
              dispose() {{ this.disposed = true; }}
            }}
            class Clock {{ getElapsedTime() {{ return now / 1000; }} }}
            class WebGLRenderer {{
              constructor() {{
                rendererConstructs += 1;
                if (config.failRendererAfter !== null && rendererConstructs > config.failRendererAfter) {{
                  throw new Error('renderer rebuild failed');
                }}
                this.domElement = makeCanvas();
                this.loop = null;
                renderers.push(this);
              }}
              setPixelRatio() {{}}
              setClearColor() {{}}
              setSize() {{}}
              render() {{}}
              setAnimationLoop(callback) {{ this.loop = callback; }}
              dispose() {{ this.disposed = true; }}
            }}

            const THREE = {{
              WebGLRenderer, Scene, FogExp2: class {{}}, PerspectiveCamera,
              BufferGeometry, BufferAttribute, PointsMaterial: Material, Points,
              LineBasicMaterial: Material, LineSegments, AmbientLight,
              DirectionalLight, PointLight, CanvasTexture, Group, BoxGeometry,
              MeshStandardMaterial: Material, Mesh, Clock,
              SRGBColorSpace: 'srgb', AdditiveBlending: 'additive',
            }};

            function activeRendererLoops() {{
              return renderers.filter((renderer) => typeof renderer.loop === 'function').length;
            }}

            function advance(milliseconds) {{ now += milliseconds; }}

            function runRendererFrames(count, milliseconds = 16) {{
              for (let index = 0; index < count; index += 1) {{
                advance(milliseconds);
                for (const callback of renderers.map((renderer) => renderer.loop).filter(Boolean)) callback();
              }}
            }}

            function runTimers() {{
              const callbacks = [...timerCallbacks.values()];
              timerCallbacks.clear();
              for (const callback of callbacks) {{
                try {{ callback(); }} catch (error) {{ timerError = error.message; }}
              }}
            }}

            let source = fs.readFileSync('./static/photon_scene.js', 'utf8');
            if (config.injectThree) {{
              source = source.replace(
                'import("/vendor/three/three.module.min.js?v=0.185.1")',
                'Promise.resolve(globalThis.__THREE__)',
              );
            }}
            const sandbox = {{
              __THREE__: THREE,
              clearTimeout: window.clearTimeout,
              console,
              document,
              performance: {{now: () => now}},
              setTimeout: window.setTimeout,
              window,
            }};
            if (config.commonjs) sandbox.module = {{exports: {{}}}};

            (async () => {{
              vm.runInNewContext(source, sandbox);
              await Promise.resolve();
              await Promise.resolve();
              const result = await (async () => {{
                {probe}
              }})();
              console.log(JSON.stringify(result));
            }})().catch((error) => {{
              console.error(error.stack || error);
              process.exit(1);
            }});
            """
        )

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
              dataset: {page: 'auth'},
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
              console, document, performance, setTimeout, window,
            });
            console.log(JSON.stringify({mode: root.dataset.photonMode}));
            """
        )
        self.assertEqual(payload["mode"], "static")

    def test_runtime_requires_supported_page_marker(self) -> None:
        for page in (None, "battle"):
            with self.subTest(page=page):
                payload = self.run_browser_probe(
                    """
                    return {
                      mode: root.dataset.photonMode || null,
                      bridge: Boolean(window.WenlingPhotonScene),
                      rafCount: rafCallbacks.size,
                    };
                    """,
                    page=page,
                )
                self.assertEqual(
                    payload,
                    {"mode": None, "bridge": False, "rafCount": 0},
                )

    def test_commonjs_export_does_not_boot_browser_runtime(self) -> None:
        payload = self.run_browser_probe(
            """
            return {
              exports: Object.keys(sandbox.module.exports).sort(),
              mode: root.dataset.photonMode || null,
              bridge: Boolean(window.WenlingPhotonScene),
              rafCount: rafCallbacks.size,
              listenerCount: listenerCount(),
            };
            """,
            commonjs=True,
        )
        self.assertEqual(
            payload,
            {
                "exports": ["PHOTON_BUDGETS", "nextQuality", "selectInitialQuality"],
                "mode": None,
                "bridge": False,
                "rafCount": 0,
                "listenerCount": 0,
            },
        )

    def test_hidden_boot_stays_paused_and_visibility_restore_starts_one_loop(self) -> None:
        canvas = self.run_browser_probe(
            """
            const hiddenLoops = rafCallbacks.size;
            document.hidden = false;
            dispatch(documentListeners, 'visibilitychange');
            const visibleLoops = rafCallbacks.size;
            dispatch(documentListeners, 'visibilitychange');
            return {hiddenLoops, visibleLoops, repeatedVisibleLoops: rafCallbacks.size};
            """,
            hidden=True,
        )
        three = self.run_browser_probe(
            """
            const hiddenLoops = activeRendererLoops();
            document.hidden = false;
            dispatch(documentListeners, 'visibilitychange');
            const visibleLoops = activeRendererLoops();
            dispatch(documentListeners, 'visibilitychange');
            return {hiddenLoops, visibleLoops, repeatedVisibleLoops: activeRendererLoops()};
            """,
            hidden=True,
            webgl2=True,
            injectThree=True,
        )
        expected = {"hiddenLoops": 0, "visibleLoops": 1, "repeatedVisibleLoops": 1}
        self.assertEqual({"canvas": canvas, "three": three}, {"canvas": expected, "three": expected})

    def test_three_resume_resets_quality_sample_window(self) -> None:
        payload = self.run_browser_probe(
            """
            runRendererFrames(30, 16);
            document.hidden = true;
            dispatch(documentListeners, 'visibilitychange');
            advance(10000);
            document.hidden = false;
            dispatch(documentListeners, 'visibilitychange');
            runRendererFrames(1, 16);
            runTimers();
            return {quality: root.dataset.photonQuality, rendererConstructs};
            """,
            webgl2=True,
            injectThree=True,
        )
        self.assertEqual(payload, {"quality": "desktop", "rendererConstructs": 1})

    def test_failed_three_rebuild_degrades_through_canvas_to_static(self) -> None:
        canvas = self.run_browser_probe(
            """
            runRendererFrames(1, 2500);
            runTimers();
            return {mode: root.dataset.photonMode, quality: root.dataset.photonQuality, timerError};
            """,
            webgl2=True,
            injectThree=True,
            failRendererAfter=1,
        )
        static_mode = self.run_browser_probe(
            """
            runRendererFrames(1, 2500);
            runTimers();
            return {mode: root.dataset.photonMode, quality: root.dataset.photonQuality, timerError};
            """,
            webgl2=True,
            injectThree=True,
            failRendererAfter=1,
            canvas2dLimit=3,
        )
        self.assertEqual(
            {"canvas": canvas, "static": static_mode},
            {
                "canvas": {"mode": "canvas", "quality": "canvas", "timerError": None},
                "static": {"mode": "static", "quality": "static", "timerError": None},
            },
        )

    def test_point_light_topology_matches_quality_tiers(self) -> None:
        desktop = self.run_browser_probe(
            "return {setCalls: pointLights.map((light) => light.position.setCalls)};",
            webgl2=True,
            injectThree=True,
        )
        mobile = self.run_browser_probe(
            "return {setCalls: pointLights.map((light) => light.position.setCalls).sort()};",
            width=390,
            coarse=True,
            webgl2=True,
            injectThree=True,
        )
        low = self.run_browser_probe(
            """
            runRendererFrames(1, 2500);
            runTimers();
            return {setCalls: pointLights.slice(2).map((light) => light.position.setCalls)};
            """,
            webgl2=True,
            injectThree=True,
        )
        self.assertEqual(
            {"desktop": desktop["setCalls"], "mobile": mobile["setCalls"], "low": low["setCalls"]},
            {"desktop": [0, 0], "mobile": [0, 1], "low": [1]},
        )

    def test_destroy_clears_async_work_and_makes_bridge_inert(self) -> None:
        payload = self.run_browser_probe(
            """
            window.WenlingPhotonScene.playAuthSuccess();
            window.WenlingPhotonScene.notifyRoomChanges([{id: 1}]);
            const timersBeforeDestroy = timerCallbacks.size;
            window.WenlingPhotonScene.destroy();
            window.WenlingPhotonScene.playLobbyReveal();
            window.WenlingPhotonScene.notifyRoomChanges([{id: 2}]);
            window.WenlingPhotonScene.setStatus('ready');
            return {
              timersBeforeDestroy,
              timersAfterDestroy: timerCallbacks.size,
              transition: root.dataset.photonTransition || null,
              roomChanges: root.dataset.photonRoomChanges || null,
              status: root.dataset.photonStatus || null,
              listeners: listenerCount(),
              rafCount: rafCallbacks.size,
            };
            """
        )
        self.assertEqual(
            payload,
            {
                "timersBeforeDestroy": 2,
                "timersAfterDestroy": 0,
                "transition": None,
                "roomChanges": None,
                "status": None,
                "listeners": 0,
                "rafCount": 0,
            },
        )


if __name__ == "__main__":
    unittest.main()
