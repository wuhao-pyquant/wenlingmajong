from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PhotonFrontendTests(unittest.TestCase):
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

    def test_auth_page_uses_photon_stage_and_preserves_contract_ids(self) -> None:
        html = (ROOT / "static" / "battle_login.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "battle_lobby.js").read_text(encoding="utf-8")
        battle_html = (ROOT / "static" / "battle.html").read_text(encoding="utf-8")

        self.assertIn('class="standalone-page auth-only-page photon-auth-page"', html)
        self.assertIn('id="photonSceneRoot"', html)
        self.assertIn('data-page="auth"', html)
        self.assertIn('/photon_lobby.css?v=20260710-photon-1', html)
        self.assertIn('/photon_scene.js?v=20260710-photon-1', html)
        self.assertIn('role="tablist"', html)
        self.assertIn('data-auth-mode="login"', html)
        self.assertIn('data-auth-mode="register"', html)
        self.assertIn('id="loginAuthTab"', html)
        self.assertIn('id="registerAuthTab"', html)
        self.assertIn('aria-labelledby="loginAuthTab"', html)
        self.assertIn('aria-labelledby="registerAuthTab"', html)
        self.assertIn('tabindex="0"', html)
        self.assertIn('tabindex="-1"', html)
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

    def run_node_json(self, source: str) -> dict:
        completed = subprocess.run(
            ["node", "-e", source],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def run_auth_probe(self, probe: str, *, initial_token: str = "", bridge_kind: str = "missing") -> dict:
        source = """
            const fs = require('fs');
            const vm = require('vm');
            const initialToken = __INITIAL_TOKEN__;
            const bridgeKind = __BRIDGE_KIND__;
            const listeners = new Map();
            const timers = [];
            const fetchCalls = [];
            const pendingFetches = [];
            const unhandledRejections = [];
            const localValues = new Map();
            const sessionValues = new Map();
            let fetchMode = 'success';
            let navigationCount = 0;

            process.on('unhandledRejection', (error) => unhandledRejections.push(error.message));

            function createClassList() {
              const values = new Set();
              return {
                toggle(name, force) {
                  if (force) values.add(name); else values.delete(name);
                },
                contains(name) { return values.has(name); },
              };
            }

            function createElement(id, dataset = {}) {
              const elementListeners = new Map();
              const attributes = new Map();
              return {
                id,
                dataset: {...dataset},
                attributes,
                classList: createClassList(),
                disabled: false,
                hidden: false,
                value: '',
                type: 'text',
                placeholder: '',
                tabIndex: -1,
                focusCount: 0,
                textContent: '',
                setAttribute(name, value) {
                  attributes.set(name, String(value));
                  if (name === 'tabindex') this.tabIndex = Number(value);
                },
                getAttribute(name) { return attributes.get(name) || null; },
                addEventListener(type, callback) {
                  if (!elementListeners.has(type)) elementListeners.set(type, []);
                  elementListeners.get(type).push(callback);
                },
                dispatch(type, event = {}) {
                  event.target = this;
                  for (const callback of elementListeners.get(type) || []) callback(event);
                  return event;
                },
                focus() { this.focusCount += 1; },
              };
            }

            const elements = {
              loginAccountInput: createElement('loginAccountInput'),
              loginPasswordInput: createElement('loginPasswordInput'),
              loginBtn: createElement('loginBtn'),
              registerAccountInput: createElement('registerAccountInput'),
              registerPasswordInput: createElement('registerPasswordInput'),
              inviteCodeInput: createElement('inviteCodeInput'),
              registerBtn: createElement('registerBtn'),
              loginAuthPanel: createElement('loginAuthPanel'),
              registerAuthPanel: createElement('registerAuthPanel'),
              authStatusTitle: createElement('authStatusTitle'),
              authStatusDetail: createElement('authStatusDetail'),
              lobbyMessage: createElement('lobbyMessage'),
              authStatusCard: createElement('authStatusCard'),
              loginAuthTab: createElement('loginAuthTab', {authMode: 'login'}),
              registerAuthTab: createElement('registerAuthTab', {authMode: 'register'}),
            };
            elements.registerAuthPanel.hidden = true;
            const tabs = [elements.loginAuthTab, elements.registerAuthTab];

            const document = {
              body: {dataset: {}},
              getElementById(id) { return elements[id] || null; },
              querySelector(selector) {
                return selector.includes('photon-auth-status') || selector.includes('auth-status-card')
                  ? elements.authStatusCard
                  : null;
              },
              querySelectorAll(selector) {
                return selector === '[data-auth-mode]' ? tabs : [];
              },
              addEventListener() {},
            };

            const location = {
              search: '',
              _href: '/battle-login',
              get href() { return this._href; },
              set href(value) { this._href = value; navigationCount += 1; },
            };
            const window = {
              location,
              addEventListener() {},
              setTimeout(callback, delay) {
                timers.push({callback, delay});
                return timers.length;
              },
              clearTimeout() {},
            };

            function createBridge(kind) {
              if (kind === 'missing') return undefined;
              const call = (name) => () => {
                if (kind === 'sync-throw') throw new Error(`${name} exploded`);
                if (kind === 'async-reject') return Promise.reject(new Error(`${name} rejected`));
                return undefined;
              };
              return {
                setStatus: call('setStatus'),
                playAuthSuccess: call('playAuthSuccess'),
                destroy: call('destroy'),
              };
            }
            window.WenlingPhotonScene = createBridge(bridgeKind);

            function response(payload) {
              return {
                ok: true,
                status: 200,
                statusText: 'OK',
                text: async () => JSON.stringify(payload),
              };
            }
            function fetch(path, options) {
              fetchCalls.push({path, options});
              if (fetchMode === 'pending') {
                return new Promise((resolve, reject) => pendingFetches.push({resolve, reject}));
              }
              if (fetchMode === 'reject') return Promise.reject(new Error('network down'));
              return Promise.resolve(response(path === '/api/auth/me'
                ? {account: 'alice', role: 'player'}
                : {account: 'alice', role: 'player', session_token: 'fresh-token'}));
            }

            const localStorage = {
              getItem(key) { return localValues.get(key) || null; },
              setItem(key, value) { localValues.set(key, String(value)); },
              removeItem(key) { localValues.delete(key); },
            };
            const sessionStorage = {
              getItem(key) { return sessionValues.get(key) || null; },
              setItem(key, value) { sessionValues.set(key, String(value)); },
              removeItem(key) { sessionValues.delete(key); },
            };
            if (initialToken) localStorage.setItem('wenling.online.token.v1', initialToken);

            const sandbox = {
              URLSearchParams,
              console,
              document,
              fetch,
              localStorage,
              Promise,
              sessionStorage,
              window,
            };
            sandbox.flush = async () => {
              for (let index = 0; index < 16; index += 1) await Promise.resolve();
            };
            sandbox.fireTimers = (limit) => {
              const ready = timers.filter((timer) => timer.delay <= limit);
              for (const timer of ready) timer.callback();
            };
            sandbox.rejectPending = (message) => {
              for (const pending of pendingFetches.splice(0)) pending.reject(new Error(message));
            };
            sandbox.resolvePending = () => {
              for (const pending of pendingFetches.splice(0)) {
                pending.resolve(response({account: 'alice', role: 'player', session_token: 'fresh-token'}));
              }
            };
            sandbox.testState = {
              elements,
              fetchCalls,
              get navigationCount() { return navigationCount; },
              get fetchMode() { return fetchMode; },
              set fetchMode(value) { fetchMode = value; },
              timers,
              unhandledRejections,
              localValues,
              sessionValues,
            };

            vm.runInNewContext(fs.readFileSync('./static/battle_lobby.js', 'utf8'), sandbox);
            (async () => {
              try {
                const result = await (async () => {
                  __PROBE__
                })();
                await sandbox.flush();
                console.log(JSON.stringify({result, error: null}));
              } catch (error) {
                console.log(JSON.stringify({result: null, error: error.message}));
              }
            })();
        """
        source = source.replace("__INITIAL_TOKEN__", json.dumps(initial_token))
        source = source.replace("__BRIDGE_KIND__", json.dumps(bridge_kind))
        return self.run_node_json(source.replace("__PROBE__", probe))

    def test_auth_bridge_is_best_effort_and_navigation_is_bounded(self) -> None:
        bounded = self.run_auth_probe(
            """
            window.WenlingPhotonScene = {
              playAuthSuccess() { return new Promise(() => {}); },
              destroy() {},
            };
            const navigation = sandbox.navigateToLobby();
            const delay = sandbox.testState.timers[0]?.delay || null;
            sandbox.fireTimers(699);
            await sandbox.flush();
            const beforeCap = window.location.href;
            sandbox.fireTimers(700);
            await navigation;
            return {
              delay,
              beforeCap,
              afterCap: window.location.href,
              navigationCount: sandbox.testState.navigationCount,
            };
            """
        )
        sync = self.run_auth_probe(
            """
            window.WenlingPhotonScene = {
              setStatus() { throw new Error('status exploded'); },
              playAuthSuccess() { throw new Error('transition exploded'); },
              destroy() { throw new Error('destroy exploded'); },
            };
            sandbox.setAuthStatus('登录成功', 'ready');
            const navigation = sandbox.navigateToLobby();
            const delay = sandbox.testState.timers[0]?.delay || null;
            sandbox.fireTimers(700);
            await navigation;
            return {
              delay,
              href: window.location.href,
              navigationCount: sandbox.testState.navigationCount,
              transition: sandbox.testState.sessionValues.get('wenling.photon.auth_to_lobby.v1') || null,
            };
            """
        )
        async_reject = self.run_auth_probe(
            """
            window.WenlingPhotonScene = {
              setStatus() { return Promise.reject(new Error('status rejected')); },
              playAuthSuccess() { return Promise.reject(new Error('transition rejected')); },
              destroy() { return Promise.reject(new Error('destroy rejected')); },
            };
            sandbox.setAuthStatus('登录成功', 'ready');
            await sandbox.navigateToLobby();
            await sandbox.flush();
            return {
              href: window.location.href,
              navigationCount: sandbox.testState.navigationCount,
              unhandled: sandbox.testState.unhandledRejections,
            };
            """
        )
        self.assertEqual(sync, {
            "result": {
                "delay": 700,
                "href": "/battle-lobby",
                "navigationCount": 1,
                "transition": "1",
            },
            "error": None,
        })
        self.assertEqual(bounded, {
            "result": {
                "delay": 700,
                "beforeCap": "/battle-login",
                "afterCap": "/battle-lobby",
                "navigationCount": 1,
            },
            "error": None,
        })
        self.assertEqual(async_reject, {
            "result": {
                "href": "/battle-lobby",
                "navigationCount": 1,
                "unhandled": [],
            },
            "error": None,
        })

    def test_valid_session_survives_bridge_errors_during_initialization(self) -> None:
        payload = self.run_auth_probe(
            """
            await sandbox.flush();
            return {
              href: window.location.href,
              token: sandbox.testState.localValues.get('wenling.online.token.v1') || null,
              fetches: sandbox.testState.fetchCalls.map((call) => call.path),
            };
            """,
            initial_token="existing-token",
            bridge_kind="sync-throw",
        )
        self.assertEqual(payload, {
            "result": {
                "href": "/battle-lobby",
                "token": "existing-token",
                "fetches": ["/api/auth/me"],
            },
            "error": None,
        })

    def test_auth_submission_guard_blocks_duplicate_click_and_enter_then_recovers(self) -> None:
        payload = self.run_auth_probe(
            """
            const loginButton = sandbox.testState.elements.loginBtn;
            const password = sandbox.testState.elements.loginPasswordInput;
            sandbox.testState.fetchMode = 'pending';
            loginButton.dispatch('click');
            password.dispatch('keydown', {key: 'Enter', preventDefault() { this.prevented = true; }});
            loginButton.dispatch('click');
            const pending = {
              fetches: sandbox.testState.fetchCalls.length,
              disabled: loginButton.disabled,
              pending: loginButton.dataset.pending,
              busy: loginButton.getAttribute('aria-busy'),
            };
            sandbox.rejectPending('network down');
            await sandbox.flush();
            return {
              pending,
              recovered: {
                disabled: loginButton.disabled,
                pending: loginButton.dataset.pending,
                busy: loginButton.getAttribute('aria-busy'),
              },
            };
            """
        )
        self.assertEqual(payload, {
            "result": {
                "pending": {"fetches": 1, "disabled": True, "pending": "true", "busy": "true"},
                "recovered": {"disabled": False, "pending": "false", "busy": "false"},
            },
            "error": None,
        })

    def test_register_submission_guard_navigates_once_for_click_and_enter(self) -> None:
        payload = self.run_auth_probe(
            """
            const registerButton = sandbox.testState.elements.registerBtn;
            const invite = sandbox.testState.elements.inviteCodeInput;
            sandbox.testState.fetchMode = 'pending';
            registerButton.dispatch('click');
            invite.dispatch('keydown', {key: 'Enter', preventDefault() { this.prevented = true; }});
            registerButton.dispatch('click');
            const pending = {
              fetches: sandbox.testState.fetchCalls.length,
              disabled: registerButton.disabled,
              pending: registerButton.dataset.pending,
            };
            sandbox.resolvePending();
            await sandbox.flush();
            return {
              pending,
              href: window.location.href,
              navigationCount: sandbox.testState.navigationCount,
            };
            """
        )
        self.assertEqual(payload, {
            "result": {
                "pending": {"fetches": 1, "disabled": True, "pending": "true"},
                "href": "/battle-lobby",
                "navigationCount": 1,
            },
            "error": None,
        })

    def test_auth_tabs_use_roving_tabindex_and_keyboard_focus(self) -> None:
        payload = self.run_auth_probe(
            """
            const login = sandbox.testState.elements.loginAuthTab;
            const register = sandbox.testState.elements.registerAuthTab;
            const loginPanel = sandbox.testState.elements.loginAuthPanel;
            const registerPanel = sandbox.testState.elements.registerAuthPanel;
            const events = [];
            for (const [tab, key] of [[login, 'ArrowRight'], [register, 'Home'], [login, 'End'], [register, 'ArrowLeft']]) {
              tab.dispatch('keydown', {key, preventDefault() { events.push(key); }});
            }
            return {
              selected: [login.getAttribute('aria-selected'), register.getAttribute('aria-selected')],
              tabIndex: [login.tabIndex, register.tabIndex],
              hidden: [loginPanel.hidden, registerPanel.hidden],
              focus: [login.focusCount, register.focusCount],
              prevented: events,
            };
            """
        )
        self.assertEqual(payload, {
            "result": {
                "selected": ["true", "false"],
                "tabIndex": [0, -1],
                "hidden": [False, True],
                "focus": [2, 2],
                "prevented": ["ArrowRight", "Home", "End", "ArrowLeft"],
            },
            "error": None,
        })

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
            "failMaterialAfter": None,
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
            let materialConstructs = 0;
            let timerError = null;
            const rafCallbacks = new Map();
            const timerCallbacks = new Map();
            const canvases = [];
            const geometries = [];
            const materials = [];
            const textures = [];
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
              const canvas = {{
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
                dispatchEvent(event) {{ dispatch(listeners, event.type, event); }},
                listenerCount() {{
                  return [...listeners.values()].reduce((total, callbacks) => total + callbacks.size, 0);
                }},
                remove() {{ this.removed = true; }},
              }};
              canvases.push(canvas);
              return canvas;
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
              constructor() {{ this.attributes = {{}}; geometries.push(this); }}
              setAttribute(name, attribute) {{ this.attributes[name] = attribute; }}
              setDrawRange() {{}}
              dispose() {{ this.disposed = true; }}
            }}
            class BoxGeometry extends BufferGeometry {{}}
            class Material {{
              constructor(properties = {{}}) {{
                materialConstructs += 1;
                if (config.failMaterialAfter !== null && materialConstructs > config.failMaterialAfter) {{
                  throw new Error('material construction failed');
                }}
                Object.assign(this, properties);
                materials.push(this);
              }}
              dispose() {{ this.disposed = true; }}
            }}
            class CanvasTexture {{
              constructor(canvas) {{
                this.canvas = canvas;
                this.isTexture = true;
                textures.push(this);
              }}
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

    def test_partial_three_initialization_disposes_every_owned_resource(self) -> None:
        payload = self.run_browser_probe(
            """
            const renderer = renderers[0];
            return {
              mode: root.dataset.photonMode,
              rendererDisposed: Boolean(renderer?.disposed),
              rendererCanvasRemoved: Boolean(renderer?.domElement.removed),
              rendererCanvasListeners: renderer?.domElement.listenerCount() ?? -1,
              geometryCount: geometries.length,
              geometriesDisposed: geometries.every((resource) => resource.disposed),
              materialCount: materials.length,
              materialsDisposed: materials.every((resource) => resource.disposed),
              textureCount: textures.length,
              texturesDisposed: textures.every((resource) => resource.disposed),
            };
            """,
            webgl2=True,
            injectThree=True,
            failMaterialAfter=3,
        )
        self.assertEqual(
            payload,
            {
                "mode": "canvas",
                "rendererDisposed": True,
                "rendererCanvasRemoved": True,
                "rendererCanvasListeners": 0,
                "geometryCount": 3,
                "geometriesDisposed": True,
                "materialCount": 3,
                "materialsDisposed": True,
                "textureCount": 1,
                "texturesDisposed": True,
            },
        )

    def test_context_loss_cancels_stale_quality_rebuild(self) -> None:
        payload = self.run_browser_probe(
            """
            runRendererFrames(1, 2500);
            const queuedBeforeLoss = timerCallbacks.size;
            let prevented = false;
            renderers[0].domElement.dispatchEvent({
              type: 'webglcontextlost',
              preventDefault() { prevented = true; },
            });
            const modeAfterLoss = root.dataset.photonMode;
            runTimers();
            return {
              queuedBeforeLoss,
              prevented,
              modeAfterLoss,
              finalMode: root.dataset.photonMode,
              finalQuality: root.dataset.photonQuality,
              rendererConstructs,
              timerError,
            };
            """,
            webgl2=True,
            injectThree=True,
        )
        self.assertEqual(
            payload,
            {
                "queuedBeforeLoss": 1,
                "prevented": True,
                "modeAfterLoss": "canvas",
                "finalMode": "canvas",
                "finalQuality": "canvas",
                "rendererConstructs": 1,
                "timerError": None,
            },
        )

    def test_three_listener_ownership_returns_to_baseline_across_replacement(self) -> None:
        direct_destroy = self.run_browser_probe(
            """
            const beforeDestroy = {
              resize: windowListeners.get('resize')?.size || 0,
              contextLoss: renderers[0].domElement.listenerCount(),
            };
            window.WenlingPhotonScene.destroy();
            return {
              beforeDestroy,
              afterDestroy: {
                resize: windowListeners.get('resize')?.size || 0,
                contextLoss: renderers[0].domElement.listenerCount(),
              },
            };
            """,
            webgl2=True,
            injectThree=True,
        )

        replacement = self.run_browser_probe(
            """
            runRendererFrames(1, 2500);
            runTimers();
            const afterReplacement = {
              rendererCount: renderers.length,
              resize: windowListeners.get('resize')?.size || 0,
              oldContextLoss: renderers[0].domElement.listenerCount(),
              newContextLoss: renderers[1].domElement.listenerCount(),
            };
            window.WenlingPhotonScene.destroy();
            return {
              afterReplacement,
              afterDestroy: {
                resize: windowListeners.get('resize')?.size || 0,
                oldContextLoss: renderers[0].domElement.listenerCount(),
                newContextLoss: renderers[1].domElement.listenerCount(),
              },
            };
            """,
            webgl2=True,
            injectThree=True,
        )

        self.assertEqual(
            {"directDestroy": direct_destroy, "replacement": replacement},
            {
                "directDestroy": {
                    "beforeDestroy": {"resize": 1, "contextLoss": 1},
                    "afterDestroy": {"resize": 0, "contextLoss": 0},
                },
                "replacement": {
                    "afterReplacement": {
                        "rendererCount": 2,
                        "resize": 1,
                        "oldContextLoss": 0,
                        "newContextLoss": 1,
                    },
                    "afterDestroy": {
                        "resize": 0,
                        "oldContextLoss": 0,
                        "newContextLoss": 0,
                    },
                },
            },
        )


if __name__ == "__main__":
    unittest.main()
