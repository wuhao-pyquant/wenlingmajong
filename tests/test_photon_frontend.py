from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PhotonFrontendTests(unittest.TestCase):
    @staticmethod
    def css_at_rule_block(css: str, at_rule: str) -> str:
        start = css.index(at_rule)
        open_brace = css.index("{", start)
        depth = 0
        for index in range(open_brace, len(css)):
            if css[index] == "{":
                depth += 1
            elif css[index] == "}":
                depth -= 1
                if depth == 0:
                    return css[start:index + 1]
        raise AssertionError(f"Unterminated CSS at-rule: {at_rule}")

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

    def test_photon_entry_pages_share_the_final_cache_token(self) -> None:
        assets = (
            "/photon_lobby.css",
            "/photon_scene.js",
            "/battle_lobby.js",
        )
        for page in ("battle_login.html", "battle_lobby.html"):
            with self.subTest(page=page):
                html = (ROOT / "static" / page).read_text(encoding="utf-8")
                for asset in assets:
                    self.assertIn(f"{asset}?v=20260711-photon-4", html)
                self.assertNotIn("20260711-photon-3", html)
                self.assertNotIn("20260711-photon-2", html)
                self.assertNotIn("20260710-photon-1", html)

    def test_auth_page_reserves_text_free_photon_core_stage(self) -> None:
        html = (ROOT / "static" / "battle_login.html").read_text(encoding="utf-8")

        self.assertIn('<div class="photon-auth-visual" aria-hidden="true"></div>', html)
        for removed_copy in (
            "PHOTON GAME NETWORK",
            "连接牌桌",
            "进入对局",
            "温岭好友牌局 · ONLINE",
        ):
            self.assertNotIn(removed_copy, html)
        self.assertIn("温岭麻将", html)
        self.assertIn("SYSTEM ONLINE", html)

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

    def run_lobby_probe(self, probe: str) -> dict:
        source = r"""
            const fs = require('fs');
            const vm = require('vm');
            const fetchCalls = [];
            const pendingFetches = [];
            const intervals = [];
            const localValues = new Map([
              ['wenling.online.account.v1', 'alice'],
              ['wenling.online.token.v1', 'token'],
              ['wenling.online.role.v1', 'player'],
            ]);
            const sessionValues = new Map();
            let fetchMode = 'success';
            let navigationCount = 0;
            let navigationThrowsRemaining = 0;
            let roomPayload = {
              rooms: [{
                room_id: 'room-1', room_name: '1号桌', owner_account: 'alice',
                ai_policy: 'low', status: 'open', room_generation: 4,
                seats: [{account: 'alice', absolute_seat: 0}, {account: ''}, {account: ''}, {account: ''}],
                ready_accounts: [],
              }],
              max_rooms: 3,
            };

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
              const listeners = new Map();
              const attributes = new Map();
              return {
                id,
                dataset: {...dataset},
                attributes,
                classList: createClassList(),
                className: '',
                disabled: false,
                hidden: false,
                value: '',
                textContent: '',
                setAttribute(name, value) { attributes.set(name, String(value)); },
                getAttribute(name) { return attributes.get(name) || null; },
                addEventListener(type, callback) {
                  if (!listeners.has(type)) listeners.set(type, []);
                  listeners.get(type).push(callback);
                },
                dispatch(type, event = {}) {
                  event.target = this;
                  for (const callback of listeners.get(type) || []) callback(event);
                },
              };
            }

            const slots = Array.from({length: 3}, (_, index) => {
              const slot = createElement(`slot-${index}`, {slotIndex: String(index)});
              slot.innerHTML = '';
              return slot;
            });
            const grid = createElement('roomTableGrid');
            grid.querySelectorAll = (selector) => selector === '.room-table-slot' ? slots : [];
            const elements = {
              roomTableGrid: grid,
              currentAccountLabel: createElement('currentAccountLabel'),
              currentRoleLabel: createElement('currentRoleLabel'),
              adminEntry: createElement('adminEntry'),
              logoutBtn: createElement('logoutBtn'),
              roomAiPolicySelect: createElement('roomAiPolicySelect'),
              roomAiPolicyLow: createElement('roomAiPolicyLow', {aiPolicy: 'low'}),
              roomAiPolicyHigh: createElement('roomAiPolicyHigh', {aiPolicy: 'high'}),
              lobbyMessage: createElement('lobbyMessage'),
            };
            elements.roomAiPolicySelect.value = 'low';
            const policyButtons = [elements.roomAiPolicyLow, elements.roomAiPolicyHigh];

            const document = {
              body: {dataset: {}},
              getElementById(id) { return elements[id] || null; },
              querySelector() { return null; },
              querySelectorAll(selector) {
                if (selector === '[data-ai-policy]') return policyButtons;
                if (selector === '[data-auth-mode]') return [];
                return [];
              },
            };
            const location = {
              search: '',
              _href: '/battle-lobby',
              get href() { return this._href; },
              set href(value) {
                if (navigationThrowsRemaining > 0) {
                  navigationThrowsRemaining -= 1;
                  throw new Error('navigation blocked');
                }
                this._href = value;
                navigationCount += 1;
              },
            };
            const window = {
              location,
              WenlingPhotonScene: {notifyRoomChanges() {}, playLobbyReveal() {}, destroy() {}},
              addEventListener() {},
              setInterval(callback, delay) {
                intervals.push({callback, delay});
                return intervals.length;
              },
              clearInterval() {},
              setTimeout,
              clearTimeout,
            };
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
            function response(payload) {
              return {
                ok: true,
                status: 200,
                statusText: 'OK',
                text: async () => JSON.stringify(payload),
              };
            }
            function fetch(path, options = {}) {
              fetchCalls.push({path, method: options.method || 'GET', body: options.body || null});
              if (fetchMode === 'pending') {
                return new Promise((resolve, reject) => pendingFetches.push({path, resolve, reject}));
              }
              if (fetchMode === 'reject') return Promise.reject(new Error('network down'));
              if (path === '/api/lobby/rooms' && options.method === 'POST') {
                return Promise.resolve(response({room_id: 'created-room'}));
              }
              if (path === '/api/lobby/rooms') return Promise.resolve(response(roomPayload));
              return Promise.resolve(response({room_id: 'created-room'}));
            }

            function buttonState(slotIndex, className) {
              const html = slots[slotIndex].innerHTML || '';
              const match = html.match(new RegExp(`<button class="${className}"[^>]*>`));
              const tag = match ? match[0] : '';
              return {
                exists: Boolean(tag),
                disabled: /\sdisabled(?:\s|>)/.test(tag),
                busy: /aria-busy="true"/.test(tag),
                pending: /data-pending="true"/.test(tag),
              };
            }

            const sandbox = {
              URLSearchParams,
              console,
              document,
              fetch,
              localStorage,
              Promise,
              sessionStorage,
              setTimeout,
              clearTimeout,
              window,
            };
            sandbox.flush = async () => {
              for (let index = 0; index < 24; index += 1) await Promise.resolve();
            };
            sandbox.testState = {
              elements,
              slots,
              fetchCalls,
              intervals,
              buttonState,
              setRoomPayload(value) { roomPayload = value; },
              get roomPayload() { return roomPayload; },
              get navigationCount() { return navigationCount; },
              get fetchMode() { return fetchMode; },
              set fetchMode(value) { fetchMode = value; },
              failNextNavigation() { navigationThrowsRemaining += 1; },
              pendingPaths() { return pendingFetches.map((pending) => pending.path); },
              resolvePendingPath(path, payload) {
                const index = pendingFetches.findIndex((pending) => pending.path === path);
                if (index < 0) return false;
                const [pending] = pendingFetches.splice(index, 1);
                pending.resolve(response(payload));
                return true;
              },
              rejectPending(message) {
                for (const pending of pendingFetches.splice(0)) pending.reject(new Error(message));
              },
              resolvePending(payload = {room_id: 'created-room'}) {
                for (const pending of pendingFetches.splice(0)) pending.resolve(response(payload));
              },
            };

            vm.runInNewContext(fs.readFileSync('./static/battle_lobby.js', 'utf8'), sandbox);
            (async () => {
              try {
                await sandbox.flush();
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
        return self.run_node_json(source.replace("__PROBE__", probe))

    def test_lobby_ai_select_and_segments_stay_synchronized(self) -> None:
        payload = self.run_lobby_probe(
            """
            const {elements} = sandbox.testState;
            elements.roomAiPolicySelect.value = 'high';
            elements.roomAiPolicySelect.dispatch('change');
            const fromSelect = {
              low: elements.roomAiPolicyLow.getAttribute('aria-pressed'),
              high: elements.roomAiPolicyHigh.getAttribute('aria-pressed'),
            };
            elements.roomAiPolicyLow.dispatch('click');
            return {fromSelect, selectAfterButton: elements.roomAiPolicySelect.value};
            """
        )
        self.assertEqual(payload, {
            "result": {
                "fromSelect": {"low": "false", "high": "true"},
                "selectAfterButton": "low",
            },
            "error": None,
        })

    def test_lobby_ready_guard_persists_across_render_and_recovers(self) -> None:
        payload = self.run_lobby_probe(
            """
            const state = sandbox.testState;
            state.fetchCalls.length = 0;
            state.fetchMode = 'pending';
            const first = sandbox.toggleReady('room-1');
            const second = sandbox.toggleReady('room-1');
            await sandbox.flush();
            const during = state.buttonState(0, 'table-ready-btn');
            sandbox.renderTableSlots(state.roomPayload.rooms, state.roomPayload.max_rooms);
            const afterPollRender = state.buttonState(0, 'table-ready-btn');
            const readyPosts = state.fetchCalls.filter((call) => call.path.endsWith('/ready')).length;
            state.fetchMode = 'success';
            state.rejectPending('ready failed');
            await Promise.all([first, second]);
            await sandbox.flush();
            return {
              readyPosts,
              during,
              afterPollRender,
              afterFailure: state.buttonState(0, 'table-ready-btn'),
            };
            """
        )
        self.assertEqual(payload, {
            "result": {
                "readyPosts": 1,
                "during": {"exists": True, "disabled": True, "busy": True, "pending": True},
                "afterPollRender": {"exists": True, "disabled": True, "busy": True, "pending": True},
                "afterFailure": {"exists": True, "disabled": False, "busy": False, "pending": False},
            },
            "error": None,
        })

    def test_lobby_primary_guard_blocks_duplicates_and_recovers(self) -> None:
        failed = self.run_lobby_probe(
            """
            const state = sandbox.testState;
            state.setRoomPayload({rooms: [], max_rooms: 3});
            sandbox.renderTableSlots([], 3);
            state.fetchCalls.length = 0;
            state.fetchMode = 'pending';
            const first = sandbox.createOrJoinTable(0);
            const second = sandbox.createOrJoinTable(0);
            await sandbox.flush();
            const during = state.buttonState(0, 'room-primary-action');
            sandbox.renderTableSlots([], 3);
            const afterPollRender = state.buttonState(0, 'room-primary-action');
            const operationPosts = state.fetchCalls.filter((call) => call.method === 'POST').length;
            state.fetchMode = 'success';
            state.rejectPending('create failed');
            await Promise.all([first, second]);
            await sandbox.flush();
            return {
              operationPosts,
              during,
              afterPollRender,
              afterFailure: state.buttonState(0, 'room-primary-action'),
            };
            """
        )
        succeeded = self.run_lobby_probe(
            """
            const state = sandbox.testState;
            state.setRoomPayload({rooms: [], max_rooms: 3});
            sandbox.renderTableSlots([], 3);
            state.fetchCalls.length = 0;
            state.fetchMode = 'pending';
            const first = sandbox.createOrJoinTable(0);
            const second = sandbox.createOrJoinTable(0);
            await sandbox.flush();
            state.resolvePending({room_id: 'created-room'});
            await sandbox.flush();
            state.resolvePendingPath('/api/lobby/rooms', {rooms: [], max_rooms: 3});
            await Promise.all([first, second]);
            return {
              operationPosts: state.fetchCalls.filter((call) => call.method === 'POST').length,
              navigationCount: state.navigationCount,
            };
            """
        )
        self.assertEqual(failed, {
            "result": {
                "operationPosts": 1,
                "during": {"exists": True, "disabled": True, "busy": True, "pending": True},
                "afterPollRender": {"exists": True, "disabled": True, "busy": True, "pending": True},
                "afterFailure": {"exists": True, "disabled": False, "busy": False, "pending": False},
            },
            "error": None,
        })
        self.assertEqual(succeeded, {
            "result": {"operationPosts": 1, "navigationCount": 1},
            "error": None,
        })

    def test_lobby_mutation_waits_for_old_poll_then_guaranteed_fresh_load(self) -> None:
        payload = self.run_lobby_probe(
            """
            const state = sandbox.testState;
            const stale = state.roomPayload;
            const fresh = {
              rooms: [{...stale.rooms[0], ready_accounts: ['alice']}],
              max_rooms: 3,
            };
            state.fetchCalls.length = 0;
            state.fetchMode = 'pending';
            const oldPoll = sandbox.loadRooms();
            const mutation = sandbox.toggleReady('room-1');
            let mutationSettled = false;
            mutation.then(() => { mutationSettled = true; });
            await sandbox.flush();
            state.resolvePendingPath('/api/battle/room-1/ready', {});
            await sandbox.flush();
            const afterMutation = {
              settled: mutationSettled,
              pending: state.buttonState(0, 'table-ready-btn').pending,
              getCount: state.fetchCalls.filter((call) => call.path === '/api/lobby/rooms').length,
            };
            state.resolvePendingPath('/api/lobby/rooms', stale);
            await oldPoll;
            await sandbox.flush();
            const afterOldPoll = {
              settled: mutationSettled,
              pending: state.buttonState(0, 'table-ready-btn').pending,
              getCount: state.fetchCalls.filter((call) => call.path === '/api/lobby/rooms').length,
              pendingPaths: state.pendingPaths(),
            };
            state.resolvePendingPath('/api/lobby/rooms', fresh);
            await mutation;
            await sandbox.flush();
            return {
              afterMutation,
              afterOldPoll,
              finalPending: state.buttonState(0, 'table-ready-btn').pending,
              finalReady: state.slots[0].innerHTML.includes('取消准备'),
            };
            """
        )
        self.assertEqual(payload, {
            "result": {
                "afterMutation": {"settled": False, "pending": True, "getCount": 1},
                "afterOldPoll": {
                    "settled": False,
                    "pending": True,
                    "getCount": 2,
                    "pendingPaths": ["/api/lobby/rooms"],
                },
                "finalPending": False,
                "finalReady": True,
            },
            "error": None,
        })

    def test_lobby_primary_identity_follows_room_and_not_compacted_slot(self) -> None:
        joined = self.run_lobby_probe(
            """
            const state = sandbox.testState;
            const roomA = {
              room_id: 'room-a', room_name: 'A桌', owner_account: 'owner-a', ai_policy: 'low',
              status: 'open', room_generation: 1,
              seats: [{account: 'owner-a'}, {account: '', absolute_seat: 1}, {account: ''}, {account: ''}],
              ready_accounts: [],
            };
            const roomB = {
              room_id: 'room-b', room_name: 'B桌', owner_account: 'owner-b', ai_policy: 'low',
              status: 'open', room_generation: 2,
              seats: [{account: 'owner-b'}, {account: '', absolute_seat: 1}, {account: ''}, {account: ''}],
              ready_accounts: [],
            };
            state.setRoomPayload({rooms: [roomA, roomB], max_rooms: 3});
            sandbox.renderTableSlots([roomA, roomB], 3);
            state.fetchCalls.length = 0;
            state.fetchMode = 'pending';
            const joinA = sandbox.createOrJoinTable(0);
            await sandbox.flush();
            sandbox.renderTableSlots([roomB, roomA], 3);
            const afterReorder = [0, 1].map((index) => state.buttonState(index, 'room-primary-action').pending);
            const blockedA = sandbox.createOrJoinTable(1);
            const joinB = sandbox.createOrJoinTable(0);
            await sandbox.flush();
            const sitPaths = state.fetchCalls.filter((call) => call.path.endsWith('/sit')).map((call) => call.path);
            state.fetchMode = 'success';
            state.rejectPending('stop joins');
            await Promise.all([joinA, blockedA, joinB]);
            return {afterReorder, sitPaths};
            """
        )
        created = self.run_lobby_probe(
            """
            const state = sandbox.testState;
            const roomA = {
              room_id: 'room-a', room_name: 'A桌', owner_account: 'owner-a', ai_policy: 'low',
              status: 'open', room_generation: 1,
              seats: [{account: 'owner-a'}, {account: '', absolute_seat: 1}, {account: ''}, {account: ''}],
              ready_accounts: [],
            };
            const roomB = {...roomA, room_id: 'room-b', room_name: 'B桌', owner_account: 'owner-b'};
            const roomC = {...roomA, room_id: 'room-c', room_name: 'C桌', owner_account: 'owner-c'};
            state.setRoomPayload({rooms: [roomA, roomB], max_rooms: 3});
            sandbox.renderTableSlots([roomA, roomB], 3);
            state.fetchCalls.length = 0;
            state.fetchMode = 'pending';
            const createThird = sandbox.createOrJoinTable(2);
            await sandbox.flush();
            sandbox.renderTableSlots([roomA, roomB, roomC], 3);
            const compactedPending = state.buttonState(2, 'room-primary-action').pending;
            const joinC = sandbox.createOrJoinTable(2);
            await sandbox.flush();
            const operationPaths = state.fetchCalls.filter((call) => call.method === 'POST').map((call) => call.path);
            state.fetchMode = 'success';
            state.rejectPending('stop actions');
            await Promise.all([createThird, joinC]);
            return {compactedPending, operationPaths};
            """
        )
        self.assertEqual(joined, {
            "result": {
                "afterReorder": [False, True],
                "sitPaths": ["/api/battle/room-a/sit", "/api/battle/room-b/sit"],
            },
            "error": None,
        })
        self.assertEqual(created, {
            "result": {
                "compactedPending": False,
                "operationPaths": ["/api/lobby/rooms", "/api/battle/room-c/sit"],
            },
            "error": None,
        })

    def test_lobby_navigation_failure_rolls_back_and_allows_retry(self) -> None:
        payload = self.run_lobby_probe(
            """
            const state = sandbox.testState;
            state.setRoomPayload({rooms: [], max_rooms: 3});
            sandbox.renderTableSlots([], 3);
            state.fetchCalls.length = 0;
            state.failNextNavigation();
            await sandbox.createOrJoinTable(0);
            const afterFailure = {
              pending: state.buttonState(0, 'room-primary-action').pending,
              disabled: state.buttonState(0, 'room-primary-action').disabled,
              message: state.elements.lobbyMessage.textContent,
              postCount: state.fetchCalls.filter((call) => call.method === 'POST').length,
              navigationCount: state.navigationCount,
            };
            await sandbox.createOrJoinTable(0);
            return {
              afterFailure,
              finalPostCount: state.fetchCalls.filter((call) => call.method === 'POST').length,
              finalNavigationCount: state.navigationCount,
              href: window.location.href,
            };
            """
        )
        self.assertEqual(payload, {
            "result": {
                "afterFailure": {
                    "pending": False,
                    "disabled": False,
                    "message": "navigation blocked",
                    "postCount": 1,
                    "navigationCount": 0,
                },
                "finalPostCount": 2,
                "finalNavigationCount": 1,
                "href": "/battle?room_id=created-room",
            },
            "error": None,
        })

    def test_lobby_capacity_disables_and_blocks_out_of_range_slots(self) -> None:
        payload = self.run_lobby_probe(
            """
            const state = sandbox.testState;
            state.fetchCalls.length = 0;
            sandbox.renderTableSlots([], 1);
            const maxOne = [0, 1, 2].map((index) => state.buttonState(index, 'room-primary-action').disabled);
            await sandbox.createOrJoinTable(1);
            const callsAfterMaxOne = state.fetchCalls.length;
            sandbox.renderTableSlots([], 2);
            const maxTwo = [0, 1, 2].map((index) => state.buttonState(index, 'room-primary-action').disabled);
            await sandbox.createOrJoinTable(2);
            sandbox.renderTableSlots([], 9);
            const cappedThree = [0, 1, 2].map((index) => state.buttonState(index, 'room-primary-action').disabled);
            return {maxOne, maxTwo, cappedThree, totalCalls: state.fetchCalls.length, callsAfterMaxOne};
            """
        )
        self.assertEqual(payload, {
            "result": {
                "maxOne": [False, True, True],
                "maxTwo": [False, False, True],
                "cappedThree": [False, False, False],
                "totalCalls": 0,
                "callsAfterMaxOne": 0,
            },
            "error": None,
        })

    def test_lobby_phone_css_uses_one_contained_column(self) -> None:
        css = (ROOT / "static" / "photon_lobby.css").read_text(encoding="utf-8")
        phone = self.css_at_rule_block(css, "@media (max-width: 760px)")
        self.assertIn("@media (max-width: 760px)", phone)
        self.assertIn(".photon-lobby-page .photon-room-grid", phone)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", phone)
        self.assertIn(".photon-lobby-page .room-table-slot", phone)
        self.assertIn("min-width: 0", phone)
        self.assertIn("overflow: hidden", phone)
        self.assertIn(".photon-lobby-page .room-table-icon", phone)
        self.assertIn("max-width: 360px", phone)

    def test_auth_visual_stage_reserves_responsive_core_space(self) -> None:
        css = (ROOT / "static" / "photon_lobby.css").read_text(encoding="utf-8")

        self.assertIn(".photon-auth-page .photon-auth-visual", css)
        self.assertIn("min-height: clamp(320px, 62vh, 680px)", css)
        self.assertIn("grid-template-rows: minmax(240px, 1fr) auto", css)
        self.assertIn("min-height: clamp(240px, 38svh, 360px)", css)
        self.assertIn("min-height: 180px", css)

    def test_photon_css_separates_narrow_layout_from_coarse_touch_targets(self) -> None:
        css = (ROOT / "static" / "photon_lobby.css").read_text(encoding="utf-8")
        narrow = self.css_at_rule_block(css, "@media (max-width: 760px)")
        self.assertIn("@media (pointer: coarse) {", css)
        coarse = self.css_at_rule_block(css, "@media (pointer: coarse)")

        self.assertNotIn("@media (max-width: 760px), (pointer: coarse)", css)
        self.assertIn(".photon-auth-page .photon-auth-stage", narrow)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", narrow)
        self.assertIn(".photon-lobby-page .photon-room-grid", narrow)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", narrow)
        self.assertNotIn("grid-template-columns", coarse)

        for target in (
            ".photon-auth-page .photon-auth-tabs button",
            ".photon-auth-page .photon-primary-action",
            ".photon-lobby-page .photon-account-cluster a",
            ".photon-lobby-page .photon-account-cluster button",
            ".photon-lobby-page [data-ai-policy]",
            ".photon-lobby-page .room-primary-action",
            ".photon-lobby-page .table-ready-btn",
        ):
            self.assertIn(target, coarse)
        self.assertEqual(coarse.count("min-height: 44px"), 7)

    def test_photon_css_keeps_hidden_and_messages_readable(self) -> None:
        css = (ROOT / "static" / "photon_lobby.css").read_text(encoding="utf-8")
        hidden = ".photon-auth-page [hidden],\n.photon-lobby-page [hidden]"

        self.assertIn(hidden, css)
        self.assertIn("display: none !important", css[css.index(hidden):])
        self.assertGreater(css.index(hidden), css.index(".photon-lobby-page .photon-account-cluster a"))

        for expected in (
            ".photon-auth-page .photon-auth-status,",
            ".photon-lobby-page .photon-lobby-message",
            "data-photon-status=\"loading\"",
            "data-photon-status=\"success\"",
            "data-photon-status=\"error\"",
            "color: #dfffff",
            "color: #dbffe9",
            "color: #ffe1de",
            "background: rgba(3,15,18,.9)",
        ):
            self.assertIn(expected, css)

    def test_photon_css_keeps_auth_inline_messages_readable_for_every_state(self) -> None:
        css = (ROOT / "static" / "photon_lobby.css").read_text(encoding="utf-8")

        for expected in (
            ".photon-auth-page .photon-inline-message,",
            ".photon-auth-page .photon-inline-message.bad",
            "data-photon-status=\"loading\"] ~ .photon-auth-shell .photon-inline-message",
            "data-photon-status=\"success\"] ~ .photon-auth-shell .photon-inline-message",
            "data-photon-status=\"error\"] ~ .photon-auth-shell .photon-inline-message",
            "color: #dfffff",
            "color: #dbffe9",
            "color: #ffe1de",
            "background: rgba(3,15,18,.9)",
        ):
            self.assertIn(expected, css)

    def test_photon_css_uses_fixed_heading_sizes_without_viewport_font_scaling(self) -> None:
        css = (ROOT / "static" / "photon_lobby.css").read_text(encoding="utf-8")
        viewport_font_size = r"font-size:\s*[^;{}]*vw\b"

        self.assertNotIn(".photon-auth-page .photon-auth-copy", css)
        self.assertIn(".photon-lobby-page .photon-lobby-heading h1", css)
        self.assertIn("font-size: 56px", css)
        with self.assertRaises(AssertionError):
            self.assertNotRegex("font-size: 5vw", viewport_font_size)
        self.assertNotRegex(css, viewport_font_size)

    def test_photon_css_adds_scoped_accessible_responsive_state_polish(self) -> None:
        css = (ROOT / "static" / "photon_lobby.css").read_text(encoding="utf-8")

        for expected in (
            "@media (max-width: 760px)",
            "@media (pointer: coarse)",
            "@media (max-height: 520px) and (orientation: landscape)",
            ".photon-auth-page :is(button, input):focus-visible",
            ".photon-lobby-page :is(button, a):focus-visible",
            "outline: 3px solid #fff",
            ".photon-auth-page .photon-scene-root[data-photon-transition=\"auth-success\"]",
            ".photon-lobby-page .photon-scene-root[data-photon-transition=\"lobby-reveal\"]",
            ".photon-auth-page .photon-scene-root[data-photon-status=\"loading\"]",
            ".photon-auth-page .photon-scene-root[data-photon-status=\"error\"]",
            ".photon-lobby-page .photon-scene-root[data-photon-status=\"success\"]",
            "grid-template-columns: minmax(180px, .8fr) minmax(0, 1.2fr)",
            "overflow-y: auto",
            "box-sizing: border-box",
        ):
            self.assertIn(expected, css)

        self.assertNotIn("\n.photon-scene-root {", css)
        self.assertNotIn("\n.photon-scene-root canvas {", css)
        self.assertNotIn("letter-spacing: -", css)

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
            "reducedMotion": False,
            "width": 1280,
            "injectThree": False,
            "failRendererAfter": None,
            "failMaterialAfter": None,
            "failAfterTimerConstruction": False,
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
                return {{
                  matches: query.includes('pointer')
                    ? config.coarse
                    : query.includes('prefers-reduced-motion') && config.reducedMotion,
                }};
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
            const timers = [];
            class Timer {{
              constructor() {{
                this.previousTime = 0;
                this.currentTime = 0;
                this.startTime = now;
                this.elapsed = 0;
                this.delta = 0;
                this.updateCalls = 0;
                this.getElapsedCalls = 0;
                this.resetCalls = 0;
                this.disposeCalls = 0;
                this.calls = [];
                timers.push(this);
              }}
              update() {{
                this.calls.push('update');
                this.previousTime = this.currentTime;
                this.currentTime = now - this.startTime;
                this.delta = this.currentTime - this.previousTime;
                this.elapsed += this.delta;
                this.updateCalls += 1;
              }}
              getElapsed() {{
                this.calls.push('getElapsed');
                this.getElapsedCalls += 1;
                return this.elapsed / 1000;
              }}
              reset() {{
                this.calls.push('reset');
                this.currentTime = now - this.startTime;
                this.resetCalls += 1;
              }}
              dispose() {{ this.disposeCalls += 1; }}
            }}
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
              MeshStandardMaterial: Material, Mesh, Timer,
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
            if (config.failAfterTimerConstruction) {{
              source = source.replace(
                'timer = new THREE.Timer();',
                "timer = new THREE.Timer();\\n    throw new Error('timer construction follow-up failed');",
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

    def test_reduced_motion_transitions_resolve_without_timers(self) -> None:
        payload = self.run_browser_probe(
            """
            let authSettled = false;
            let lobbySettled = false;
            window.WenlingPhotonScene.playAuthSuccess().then(() => { authSettled = true; });
            window.WenlingPhotonScene.playLobbyReveal().then(() => { lobbySettled = true; });
            await Promise.resolve();
            return {
              mode: root.dataset.photonMode,
              timers: timerCallbacks.size,
              authSettled,
              lobbySettled,
              transition: root.dataset.photonTransition || null,
            };
            """,
            reducedMotion=True,
            webgl2=True,
            injectThree=True,
        )
        self.assertEqual(payload, {
            "mode": "static",
            "timers": 0,
            "authSettled": True,
            "lobbySettled": True,
            "transition": None,
        })

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

    def test_three_timer_accumulates_visible_frame_deltas_and_disposes_once(self) -> None:
        script = (ROOT / "static" / "photon_scene.js").read_text(encoding="utf-8")
        self.assertNotIn("new THREE.Clock", script)
        self.assertIn("new THREE.Timer", script)

        payload = self.run_browser_probe(
            """
            const timer = timers[0];
            runRendererFrames(2, 16);
            const elapsedBeforeHidden = timer.elapsed / 1000;
            document.hidden = true;
            dispatch(documentListeners, 'visibilitychange');
            advance(10000);
            document.hidden = false;
            dispatch(documentListeners, 'visibilitychange');
            runRendererFrames(1, 16);
            const elapsedAfterResume = timer.elapsed / 1000;
            const calls = timer.calls;
            const resetsAfterResume = timer.resetCalls;
            window.WenlingPhotonScene.destroy();
            window.WenlingPhotonScene.destroy();
            return {
              resetsAfterResume,
              elapsedBeforeHidden,
              elapsedAfterResume,
              calls,
              disposeCalls: timer.disposeCalls,
              listeners: listenerCount(),
            };
            """,
            webgl2=True,
            injectThree=True,
        )
        self.assertEqual(
            payload,
            {
                "resetsAfterResume": 2,
                "elapsedBeforeHidden": 0.032,
                "elapsedAfterResume": 0.048,
                "calls": [
                    "reset", "update", "getElapsed", "update", "getElapsed",
                    "reset", "update", "getElapsed",
                ],
                "disposeCalls": 1,
                "listeners": 0,
            },
        )

    def test_three_timer_disposes_after_construction_failure_before_layer_assignment(self) -> None:
        payload = self.run_browser_probe(
            """
            return {
              mode: root.dataset.photonMode,
              timerCount: timers.length,
              disposeCalls: timers[0]?.disposeCalls ?? 0,
            };
            """,
            webgl2=True,
            injectThree=True,
            failAfterTimerConstruction=True,
        )
        self.assertEqual(
            payload,
            {"mode": "canvas", "timerCount": 1, "disposeCalls": 1},
        )

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
