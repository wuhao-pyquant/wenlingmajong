const tileOrder = [
  "m1","m2","m3","m4","m5","m6","m7","m8","m9",
  "t1","t2","t3","t4","t5","t6","t7","t8","t9",
  "b1","b2","b3","b4","b5","b6","b7","b8","b9",
  "east","south","west","north","zhong","fa","bai",
  "rh1","rh2","rh3","rh4","bh1","bh2","bh3","bh4"
];

let state = null;
let tileNames = {};
let busy = false;
let activeView = "game";
let dismissedSettlementKey = null;
let pendingResolveTimer = null;
let pendingCountdownTimer = null;
let resolvingPending = false;
let steppingGame = false;
let refreshingGame = false;
let battleWaitLoopActive = false;
let battleHeartbeatLoopActive = false;
let roomMenuOpen = false;
let selectedDiscardTile = null;
let selectedDiscardKey = null;
let pendingActionFeedback = null;
let recentBattleApiTimings = [];
let recentBattleClientErrors = [];
let voiceEnabled = true;
let lastWinAnimationKey = null;
let lastWinAnimationStartedAt = 0;
let currentBattleAccount = null;

const $ = (id) => document.getElementById(id);
const APP_MODE = "battle";
const LEIZI_WIN_GIF_SRC = "/assets/q_dazed_drool_5s.gif";
const BATTLE_ACCOUNT_STORAGE_KEY = "wenling.battle.account.v1";
const DISCARD_ZONE_LAYOUT_STORAGE_KEY = "wenling.discard.zone.layout.v3";
const DEFAULT_BATTLE_AI_POLICY = "tile_efficiency";
const BATTLE_HEARTBEAT_INTERVAL_MS = 10000;
const BATTLE_MOBILE_LOGICAL_WIDTH = 1500;
const BATTLE_MOBILE_MIN_LOGICAL_HEIGHT = 760;
const BATTLE_GENERATION_WRITE_PATHS = new Set([
  "/api/battle/heartbeat",
  "/api/battle/sit",
  "/api/battle/leave",
  "/api/battle/kick",
  "/api/battle/ready",
  "/api/battle/reset",
  "/api/battle/report-bug",
]);

function percentValue(value) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, Math.min(100, number)) : 0;
}

function formatNumber(value, digits = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : "-";
}

function percentText(value, digits = 1) {
  const number = Number(value);
  return Number.isFinite(number) ? `${(number * 100).toFixed(digits)}%` : "-";
}
function battleAiPolicyValue() {
  return DEFAULT_BATTLE_AI_POLICY;
}

function saveBattleAiPolicy() {
}

function restoreBattleAiPolicy() {
}

function battleAccountValue() {
  return String(currentBattleAccount || "").trim();
}

function saveBattleAccount(account) {
  currentBattleAccount = String(account || "").trim();
  try {
    if (currentBattleAccount) localStorage.setItem(BATTLE_ACCOUNT_STORAGE_KEY, currentBattleAccount);
    else localStorage.removeItem(BATTLE_ACCOUNT_STORAGE_KEY);
  } catch {
    // Local storage can be unavailable in hardened browser profiles.
  }
}

function restoreBattleAccount() {
  try {
    currentBattleAccount = localStorage.getItem(BATTLE_ACCOUNT_STORAGE_KEY) || "";
  } catch {
    currentBattleAccount = "";
  }
  if ($("battleAccountInput") && currentBattleAccount) {
    $("battleAccountInput").value = currentBattleAccount;
  }
}

function battleQuery() {
  const account = battleAccountValue();
  return account ? `?account=${encodeURIComponent(account)}` : "";
}

function battleWaitQuery(since) {
  const params = new URLSearchParams();
  const account = battleAccountValue();
  if (account) params.set("account", account);
  if (since !== null && since !== undefined) params.set("since", String(since));
  params.set("timeout", "20");
  return `?${params.toString()}`;
}

async function battleApi(path, options = {}) {
  return api(path, options);
}
async function post(path, payload = {}) {
  let body = { ...(payload || {}) };
  if (BATTLE_GENERATION_WRITE_PATHS.has(path) && body.room_generation === undefined) {
    const generation = Number(state?.room_generation);
    if (!Number.isInteger(generation)) {
      throw new Error("房间状态尚未加载，请刷新后重试。");
    }
    body.room_generation = generation;
  }
  return api(path, { method: "POST", body: JSON.stringify(body) });
}

async function readApiResponse(response) {
  const raw = await response.text();
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch {
    return { error: raw };
  }
}

async function api(path, options = {}) {
  const startedAt = typeof performance !== "undefined" ? performance.now() : Date.now();
  let status = 0;
  let ok = false;
  const request = { ...options };
  const headers = new Headers(options.headers || {});
  if (request.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  request.headers = headers;
  try {
    const response = await fetch(path, request);
    status = response.status;
    const data = await readApiResponse(response);
    if (!response.ok || data.error || data.detail) {
      const detail = data.error || data.detail || `请求失败：${response.status}`;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    ok = true;
    return data;
  } finally {
    recordBattleApiTiming(path, request.method || "GET", (typeof performance !== "undefined" ? performance.now() : Date.now()) - startedAt, status, ok);
  }
}

function recordBattleApiTiming(path, method, elapsedMs, status, ok) {
  if (APP_MODE !== "battle" || !String(path).startsWith("/api/battle/")) return;
  const url = String(path).split("?")[0];
  recentBattleApiTimings.push({
    path: url.replace("/api/battle/", ""),
    method: String(method || "GET").toUpperCase(),
    elapsed_ms: Math.round(Number(elapsedMs) || 0),
    status: status || 0,
    ok: Boolean(ok),
    ts: Date.now(),
  });
  recentBattleApiTimings = recentBattleApiTimings.slice(-8);
}
function tileLabel(code) {
  if (!code) return "";
  return tileNames[code] || code;
}

function speechTileName(code) {
  const value = String(code || "");
  const rank = value.match(/\d+/)?.[0] || "";
  if (/^m[1-9]$/.test(value)) return `${rank}万`;
  if (/^t[1-9]$/.test(value)) return `${rank}条`;
  if (/^b[1-9]$/.test(value)) return `${rank}饼`;
  const honors = {
    east: "东",
    south: "南",
    west: "西",
    north: "北",
    zhong: "中",
    fa: "发",
    bai: "白"
  };
  return honors[value] || tileLabel(code);
}

function speak(text) {
  if (!voiceEnabled || !text || !("speechSynthesis" in window)) return;
  try {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "zh-CN";
    utterance.rate = 1.08;
    utterance.pitch = 1;
    window.speechSynthesis.speak(utterance);
  } catch {
    voiceEnabled = false;
  }
}

function historyEventKey(entry) {
  if (!entry) return "";
  return `${entry.ts ?? ""}|${entry.event ?? ""}|${entry.message ?? ""}|${entry.tile ?? ""}|${entry.kind ?? ""}`;
}

function spokenTextForEvent(entry) {
  if (!entry) return "";
  if (entry.event === "discard" && entry.tile) return speechTileName(entry.tile);
  if (entry.event === "claim") {
    if (entry.kind === "chi") return "吃";
    if (entry.kind === "peng") return "碰";
    if (entry.kind === "ming_gang") return "杠";
    if (entry.message?.includes("吃")) return "吃";
    if (entry.message?.includes("碰")) return "碰";
    if (entry.message?.includes("杠")) return "杠";
  }
  if (entry.event === "kong") return "杠";
  if (entry.event === "flower") return "补花";
  if (entry.event === "win") return "胡";
  return "";
}

function announceNewHistory(previous, next) {
  if (activeView !== "game" || !previous || !next) return;
  const previousKeys = new Set((previous.history || []).map(historyEventKey));
  for (const entry of next.history || []) {
    if (previousKeys.has(historyEventKey(entry))) continue;
    const text = spokenTextForEvent(entry);
    if (text) speak(text);
  }
}

function legalDiscardTiles() {
  const human = humanPlayer();
  if (!state || state.pending || state.phase !== "turn" || !human || state.current_player !== human.seat) {
    return new Set();
  }
  return new Set((state?.legal_actions || [])
    .filter((action) => action.type === "discard")
    .map((action) => action.tile));
}

function displayedHandTiles(human) {
  const tiles = expandHand(human?.hand || {});
  let drawnTile = null;
  if (human?.last_draw && human.hand?.[human.last_draw] > 0) {
    const drawIndex = tiles.lastIndexOf(human.last_draw);
    if (drawIndex >= 0) {
      drawnTile = tiles.splice(drawIndex, 1)[0];
    }
  }
  if (drawnTile) tiles.push(drawnTile);
  return { tiles, drawnTile };
}

function syncSelectedDiscardTile() {
  const human = humanPlayer();
  if (!state || state.phase !== "turn" || !human || state.current_player !== human.seat) {
    selectedDiscardTile = null;
    selectedDiscardKey = null;
    return;
  }
  const legal = legalDiscardTiles();
  if (!selectedDiscardTile || !legal.has(selectedDiscardTile)) {
    selectedDiscardTile = null;
    selectedDiscardKey = null;
    return;
  }
  if (selectedDiscardKey) {
    const keys = new Set(displayedHandTiles(human).tiles.map((code, index) => `${code}:${index}`));
    if (!keys.has(selectedDiscardKey)) {
      selectedDiscardTile = null;
      selectedDiscardKey = null;
    }
  }
}
function setGameState(next, { announce = true, force = false } = {}) {
  if (
    APP_MODE === "battle" &&
    state &&
    next &&
    Number.isFinite(Number(state.room_revision)) &&
    Number.isFinite(Number(next.room_revision)) &&
    Number(next.room_revision) < Number(state.room_revision)
  ) {
    return false;
  }
  if (
    APP_MODE === "battle" &&
    state &&
    next &&
    Number.isFinite(Number(state.room_revision)) &&
    Number.isFinite(Number(next.room_revision)) &&
    Number(next.room_revision) === Number(state.room_revision) &&
    Number.isFinite(Number(state.event_seq)) &&
    Number.isFinite(Number(next.event_seq)) &&
    Number(next.event_seq) < Number(state.event_seq)
  ) {
    return false;
  }
  if (
    !force &&
    APP_MODE === "battle" &&
    state &&
    next &&
    state.account === next.account &&
    state.phase === next.phase &&
    state.game_started === next.game_started &&
    state.room_revision !== undefined &&
    next.room_revision !== undefined &&
    state.room_revision === next.room_revision &&
    state.event_seq === next.event_seq
  ) {
    return false;
  }
  const previous = state;
  state = next;
  if (
    APP_MODE === "battle" &&
    pendingActionFeedback &&
    previous &&
    (
      next.room_generation !== pendingActionFeedback.room_generation ||
      next.pending_id !== pendingActionFeedback.pending_id ||
      next.action_token !== pendingActionFeedback.action_token ||
      next.room_revision !== previous.room_revision ||
      next.event_seq !== previous.event_seq
    )
  ) {
    pendingActionFeedback = null;
  }
  syncSelectedDiscardTile();
  if (announce) announceNewHistory(previous, state);
  return true;
}

const tileImageCache = new Map();
const tileImagePaths = {
  bai: "/assets/mahjong-tiles/01-white-dragon.svg",
  fa: "/assets/mahjong-tiles/02-green-dragon.svg",
  zhong: "/assets/mahjong-tiles/03-red-dragon.svg",
  east: "/assets/mahjong-tiles/04-east-wind.svg",
  south: "/assets/mahjong-tiles/05-south-wind.svg",
  west: "/assets/mahjong-tiles/06-west-wind.svg",
  north: "/assets/mahjong-tiles/07-north-wind.svg",
  m1: "/assets/mahjong-tiles/08-characters-1.svg",
  m2: "/assets/mahjong-tiles/09-characters-2.svg",
  m3: "/assets/mahjong-tiles/10-characters-3.svg",
  m4: "/assets/mahjong-tiles/11-characters-4.svg",
  m5: "/assets/mahjong-tiles/12-characters-5.svg",
  m6: "/assets/mahjong-tiles/13-characters-6.svg",
  m7: "/assets/mahjong-tiles/14-characters-7.svg",
  m8: "/assets/mahjong-tiles/15-characters-8.svg",
  m9: "/assets/mahjong-tiles/16-characters-9.svg",
  b1: "/assets/mahjong-tiles/17-circles-1.svg",
  b2: "/assets/mahjong-tiles/18-circles-2.svg",
  b3: "/assets/mahjong-tiles/19-circles-3.svg",
  b4: "/assets/mahjong-tiles/20-circles-4.svg",
  b5: "/assets/mahjong-tiles/21-circles-5.svg",
  b6: "/assets/mahjong-tiles/22-circles-6.svg",
  b7: "/assets/mahjong-tiles/23-circles-7.svg",
  b8: "/assets/mahjong-tiles/24-circles-8.svg",
  b9: "/assets/mahjong-tiles/25-circles-9.svg",
  t1: "/assets/mahjong-tiles/26-bamboos-1.svg",
  t2: "/assets/mahjong-tiles/27-bamboos-2.svg",
  t3: "/assets/mahjong-tiles/28-bamboos-3.svg",
  t4: "/assets/mahjong-tiles/29-bamboos-4.svg",
  t5: "/assets/mahjong-tiles/30-bamboos-5.svg",
  t6: "/assets/mahjong-tiles/31-bamboos-6.svg",
  t7: "/assets/mahjong-tiles/32-bamboos-7.svg",
  t8: "/assets/mahjong-tiles/33-bamboos-8.svg",
  t9: "/assets/mahjong-tiles/34-bamboos-9.svg",
  bh1: "/assets/mahjong-tiles/35-spring.svg",
  bh2: "/assets/mahjong-tiles/36-summer.svg",
  bh3: "/assets/mahjong-tiles/37-autumn.svg",
  bh4: "/assets/mahjong-tiles/38-winter.svg",
  rh1: "/assets/mahjong-tiles/39-plum.svg",
  rh2: "/assets/mahjong-tiles/40-orchid.svg",
  rh3: "/assets/mahjong-tiles/41-chrysanthemum.svg",
  rh4: "/assets/mahjong-tiles/42-bamboo.svg"
};

function escapeXml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeAttr(value) {
  return String(value).replace(/&/g, "&amp;").replace(/"/g, "&quot;");
}

function tileRank(code) {
  const match = String(code).match(/\d+/);
  return match ? Number(match[0]) : 0;
}

function isNumberedSuit(code, suit) {
  return new RegExp(`^${suit}[1-9]$`).test(String(code));
}

function isFlowerTile(code) {
  return /^(rh|bh)[1-4]$/.test(String(code));
}

function pipPositions(rank) {
  const map = {
    1: [[42, 49]],
    2: [[30, 33], [54, 65]],
    3: [[28, 30], [42, 49], [56, 68]],
    4: [[28, 30], [56, 30], [28, 68], [56, 68]],
    5: [[28, 28], [56, 28], [42, 49], [28, 70], [56, 70]],
    6: [[28, 25], [56, 25], [28, 49], [56, 49], [28, 73], [56, 73]],
    7: [[42, 20], [28, 42], [56, 42], [28, 62], [56, 62], [28, 82], [56, 82]],
    8: [[28, 20], [56, 20], [28, 40], [56, 40], [28, 60], [56, 60], [28, 80], [56, 80]],
    9: [[25, 20], [42, 20], [59, 20], [25, 49], [42, 49], [59, 49], [25, 78], [42, 78], [59, 78]]
  };
  return map[rank] || [];
}

const bambooPositionsMap = {
  4: [[30, 35], [54, 35], [30, 72], [54, 72]],
  6: [[20, 32], [42, 32], [64, 32], [20, 68], [42, 68], [64, 68]],
  7: [[42, 20], [28, 42], [56, 42], [28, 62], [56, 62], [28, 82], [56, 82]],
  8: [[22, 22], [32, 38], [52, 38], [62, 22], [22, 62], [32, 78], [52, 78], [62, 62]]
};

function bambooPositions(rank) {
  return bambooPositionsMap[rank] || pipPositions(rank);
}

function circleIcon(rank) {
  return pipPositions(rank).map(([x, y]) => `
    <circle cx="${x}" cy="${y}" r="10.5" fill="#f7fbff" stroke="#174e86" stroke-width="2.5"/>
    <circle cx="${x}" cy="${y}" r="6.7" fill="none" stroke="#2679bf" stroke-width="2"/>
    <circle cx="${x}" cy="${y}" r="2.8" fill="#cf2f2f"/>
  `).join("");
}

function bambooIcon(rank) {
  if (rank === 1) {
    return `
      <g transform="translate(0 2)">
        <path d="M23 82 Q42 73 64 82" stroke="#70451b" stroke-width="2.4" stroke-linecap="round" fill="none"/>
        <path d="M37 59 C32 67 28 74 24 82" stroke="#19834a" stroke-width="4" stroke-linecap="round" fill="none"/>
        <path d="M45 61 C48 70 52 76 58 82" stroke="#19834a" stroke-width="3" stroke-linecap="round" fill="none"/>
        <ellipse cx="42" cy="53" rx="12" ry="15" fill="#188747"/>
        <ellipse cx="37" cy="53" rx="5" ry="10" fill="#0f6837" transform="rotate(-18 37 53)"/>
        <ellipse cx="47" cy="45" rx="7" ry="5" fill="#2a9b58" transform="rotate(22 47 45)"/>
        <circle cx="49" cy="31" r="8" fill="#188747"/>
        <path d="M43 32 C40 28 38 25 37 21" stroke="#c92d2d" stroke-width="2.4" stroke-linecap="round" fill="none"/>
        <circle cx="52" cy="29.5" r="2.5" fill="#fff"/>
        <circle cx="52.3" cy="29.5" r="1.2" fill="#101010"/>
        <path d="M56 31 L63 33.5 L56 37Z" fill="#d28a22"/>
        <line x1="39" y1="66" x2="36" y2="83" stroke="#d28a22" stroke-width="1.5"/>
        <line x1="45" y1="66" x2="46" y2="83" stroke="#d28a22" stroke-width="1.5"/>
      </g>
    `;
  }
  return bambooPositions(rank).map(([x, y], index) => bambooStemSvg(x, y, index, rank)).join("");
}

function bambooStemSvg(x, y, index, rank) {
  const isRedAccent = rank === 5 && index === 2;
  const main = isRedAccent ? "#cf2f2f" : "#158047";
  const dark = isRedAccent ? "#9f2323" : "#0e6235";
  const light = isRedAccent ? "#e26767" : "#35a966";
  return `
    <g transform="translate(${x} ${y})">
      <path d="M-5 -13 C-9 -7 -9 7 -5 13 C-2 16 2 16 5 13 C9 7 9 -7 5 -13 C2 -16 -2 -16 -5 -13Z" fill="rgba(0,0,0,0.08)"/>
      <path d="M-5.5 -14 C-8.8 -8 -8.8 8 -5.5 14 C-2.3 17 2.3 17 5.5 14 C8.8 8 8.8 -8 5.5 -14 C2.3 -17 -2.3 -17 -5.5 -14Z" fill="${main}" stroke="${dark}" stroke-width="1.1"/>
      <path d="M-2.5 -12 C-4 -6 -4 7 -2.2 12" stroke="${light}" stroke-width="2.2" stroke-linecap="round" opacity="0.72"/>
      <path d="M-6.5 -5.5 C-2.5 -3.5 2.5 -3.5 6.5 -5.5" stroke="${dark}" stroke-width="1.7" stroke-linecap="round" opacity="0.8"/>
      <path d="M-6.5 5.5 C-2.5 3.5 2.5 3.5 6.5 5.5" stroke="${dark}" stroke-width="1.7" stroke-linecap="round" opacity="0.8"/>
      <path d="M0 -14 L0 14" stroke="rgba(255,255,255,0.18)" stroke-width="1" stroke-linecap="round"/>
    </g>
  `;
}

function characterIcon(code) {
  const rank = tileRank(code);
  const numerals = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九"];
  return `
    <text x="42" y="46" text-anchor="middle" font-size="34" font-weight="850" fill="#202020" font-family="serif">${numerals[rank]}</text>
    <text x="42" y="82" text-anchor="middle" font-size="30" font-weight="900" fill="#c92d2d" font-family="serif">萬</text>
  `;
}

function honorIcon(code) {
  const map = {
    east: ["東", "#171713"],
    south: ["南", "#171713"],
    west: ["西", "#171713"],
    north: ["北", "#171713"],
    zhong: ["中", "#bf2421"],
    fa: ["發", "#16804c"],
    bai: ["白", "#1e5c8a"]
  };
  const [label, color] = map[code] || [tileLabel(code), "#171713"];
  const frame = code === "bai"
    ? `<rect x="21" y="26" width="42" height="46" rx="4" fill="none" stroke="#174e86" stroke-width="4"/>`
    : "";
  return `
    ${frame}
    <text x="42" y="69" text-anchor="middle" font-size="${code === "fa" ? 45 : 50}" font-weight="900" fill="${color}" font-family="serif">${label}</text>
  `;
}

function flowerIcon(code) {
  const rank = tileRank(code);
  const red = code.startsWith("rh");
  const color = red ? "#c52624" : "#171713";
  const accent = red ? "#f8e5e5" : "#e7eaeb";
  return `
    <text x="42" y="28" text-anchor="middle" font-size="13" font-weight="850" fill="${color}">${red ? "红花" : "黑花"}</text>
    <circle cx="42" cy="58" r="23" fill="${accent}" stroke="${color}" stroke-width="2.8"/>
    <path d="M42 40 C48 49 58 49 62 58 C52 59 49 69 42 77 C35 69 32 59 22 58 C26 49 34 49 42 40Z" fill="${red ? "#dc3a3a" : "#394148"}" opacity="0.18"/>
    <text x="42" y="72" text-anchor="middle" font-size="40" font-weight="900" fill="${color}" font-family="serif">${rank}</text>
  `;
}

function tileFrameSvg(code) {
  const accent = isNumberedSuit(code, "m") || code === "zhong" || code.startsWith?.("rh")
    ? "#c92d2d"
    : isNumberedSuit(code, "t") || code === "fa"
      ? "#177b45"
      : "#174e86";
  return `
    <rect x="2.5" y="2.5" width="79" height="99" rx="8" fill="#fffdf4" stroke="#d5c9ad" stroke-width="1.5"/>
    <rect x="6" y="6" width="72" height="92" rx="6" fill="none" stroke="#eee6d6" stroke-width="1"/>
    <path d="M11 18 H73" stroke="${accent}" stroke-width="1" opacity="0.08"/>
    <path d="M11 88 H73" stroke="${accent}" stroke-width="1" opacity="0.08"/>
  `;
}

function tileImageSrc(code) {
  if (!code || code === "*") return "";
  if (tileImageCache.has(code)) return tileImageCache.get(code);
  const src = tileImagePaths[code] || "";
  tileImageCache.set(code, src);
  return src;
}

function tileCodeByName(name) {
  return Object.entries(tileNames).find(([, label]) => label === name)?.[0] || null;
}

function publicFlowersFor(player) {
  const flowers = player.flowers || [];
  if (flowers.length && flowers.every((code) => code !== "*")) return flowers;

  const parsed = [];
  for (const entry of state.history || []) {
    if (entry.event !== "flower" || !entry.message) continue;
    const marker = `${player.label}补花：`;
    if (!entry.message.startsWith(marker)) continue;
    const names = entry.message.slice(marker.length).split("、").map((value) => value.trim()).filter(Boolean);
    for (const name of names) {
      const code = tileCodeByName(name);
      if (code) parsed.push(code);
    }
  }

  if (parsed.length >= player.flower_count) return parsed.slice(0, player.flower_count);
  return parsed.concat(Array.from({ length: Math.max(0, player.flower_count - parsed.length) }, () => "*"));
}

function tileHtml(code, size = "", extra = "") {
  const de = state?.de_set?.includes(code) ? "de" : "";
  const flower = isFlowerTile(code) ? "flower" : "";
  if (code === "*") return `<span class="tile back ${size} ${extra}" data-tile="*">?</span>`;
  const label = tileLabel(code);
  return `<span class="tile ${size} ${de} ${flower} ${extra}" data-tile="${escapeAttr(code)}" title="${escapeAttr(label)}"><img class="tile-img" src="${tileImageSrc(code)}" alt="${escapeAttr(label)}" /></span>`;
}

function meldDisplayTiles(meld) {
  const tiles = Array.isArray(meld?.tiles) ? meld.tiles : [];
  if (meld?.type === "an_gang" && tiles.length >= 4) {
    return ["*", tiles[1], tiles[2], "*"];
  }
  return tiles;
}

function expandHand(hand) {
  const tiles = [];
  for (const code of tileOrder) {
    const count = hand[code] || 0;
    for (let i = 0; i < count; i += 1) tiles.push(code);
  }
  return tiles;
}

function actionText(action) {
  const type = action.type;
  if (type === "hu") return "和";
  if (type === "pass") return "过";
  if (type === "an_gang") return `暗杠 ${tileLabel(action.tile)}`;
  if (type === "bu_gang") return `补杠 ${tileLabel(action.tile)}`;
  if (type === "ming_gang") return `明杠 ${tileLabel(action.tile)}`;
  if (type === "peng") return `碰 ${tileLabel(action.tile)}`;
  if (type === "chi") return `吃 ${action.tiles.map(tileLabel).join("、")}`;
  if (type === "discard") return `打 ${tileLabel(action.tile)}`;
  return type;
}

function actionIcon(action) {
  const type = action.type;
  if (type === "hu") return "和";
  if (type === "pass") return "过";
  if (type === "peng") return "碰";
  if (type === "chi") return "吃";
  if (type.includes("gang")) return "杠";
  if (type === "discard") return "打";
  return "令";
}

function actionButtonText(action, legalActions = []) {
  const type = action.type;
  if (type === "hu") return "胡";
  if (type === "pass") return "过";
  if (type === "peng") return "碰";
  if (type === "ming_gang") return "杠";
  if (type === "chi") return `吃 ${action.tiles.map(tileLabel).join(" ")}`;
  if (type === "an_gang" || type === "bu_gang") {
    const choices = legalActions.filter((item) => item.type === type);
    return choices.length > 1 ? `杠 ${tileLabel(action.tile)}` : "杠";
  }
  if (type && type.includes("gang")) return "杠";
  if (type === "discard") return "出";
  return actionText(action);
}

function phaseText(phase) {
  if (phase === "turn") {
    const player = playerBySeat(state.current_player) || state.players[state.current_player];
    return player?.is_human ? "轮到你" : `${player?.label || ""} 行牌`;
  }
  if (phase === "round_over") return state.win_type || "本局结束";
  if (phase === "deal") return "发牌";
  return phase;
}
function renderGameHeader() {
  if (activeView !== "game" || !state) return;
  $("roundMeta").textContent = `第 ${state.round_no} 局 · 当前 ${phaseText(state.phase)}`;
}

function latestEvent(type) {
  const history = state?.history || [];
  for (let i = history.length - 1; i >= 0; i -= 1) {
    if (history[i].event === type) return history[i];
  }
  return null;
}

function latestDiscardEvent() {
  return latestEvent("discard");
}

function compactActionText(action) {
  if (!action) return "";
  if (action.type === "discard") return "";
  return actionText(action);
}

function actionFocusText() {
  const legal = state?.legal_actions || [];
  if (state?.phase === "round_over") return state?.settlement ? "本局已结算" : "本局结束";
  if (!legal.length) return state?.current_player === 0 ? "等待摸牌" : "AI 正在思考";
  const priority = legal.map(compactActionText).filter(Boolean);
  if (priority.length) return priority.slice(0, 4).join(" / ");
  if (legal.some((action) => action.type === "discard")) return "点击下方手牌出牌";
  return "等待下一步";
}

function currentSeatFocus() {
  const player = state?.players?.[state.current_player];
  if (!player || state?.phase === "round_over") return "对局结束";
  return player.is_human ? "轮到你" : `${player.label} 行牌`;
}

function chipRankingRows() {
  return [...(state?.players || [])]
    .sort((a, b) => Number(b.chips || 0) - Number(a.chips || 0))
    .slice(0, 4)
    .map((player) => `
      <span class="${player.is_human ? "human-chip" : ""}">
        <b>${seatWind(player)}</b>${player.name || ""} ${player.chips}
      </span>
    `).join("");
}

function renderBattleFocus() {
  const box = $("battleFocus");
  if (box) {
    box.innerHTML = "";
    box.hidden = true;
  }
  return;
  if (!box || !state) return;
  const discard = latestDiscardEvent();
  const current = state.players?.[state.current_player];
  const isHumanTurn = state.phase !== "round_over" && current?.is_human;
  const focusClass = isHumanTurn ? "is-human-turn" : state.phase === "round_over" ? "is-round-over" : "is-ai-turn";
  const latestTile = discard?.tile ? tileHtml(discard.tile, "small", "focus-tile") : `<span class="focus-empty">暂无</span>`;
  const latestText = discard?.message ? escapeXml(discard.message) : "尚未出牌";
  const actionTextValue = actionFocusText();
  box.className = `battle-focus ${focusClass}`;
  box.innerHTML = `
    <div class="focus-kicker">${phaseText(state.phase)}</div>
    <div class="focus-main">
      <span class="focus-turn">${currentSeatFocus()}</span>
      <span class="focus-wall">牌墙 ${state.wall_remaining ?? "-"} 张</span>
    </div>
    <div class="focus-latest">
      <span>最新弃牌</span>
      ${latestTile}
      <strong>${latestText}</strong>
    </div>
    <div class="focus-action">
      <span>${isHumanTurn ? "你现在可以" : "当前重点"}</span>
      <strong>${actionTextValue}</strong>
    </div>
    <div class="focus-chips" aria-label="筹码排行">${chipRankingRows()}</div>
  `;
}

function seatName(index) {
  return ["下位", "右位", "上位", "左位"][index] || `${index}`;
}

function renderBattleShell() {
  const panel = $("battleLoginPanel");
  if (!panel || activeView !== "game" || APP_MODE === "battle") return;
  const account = battleAccountValue();
  const seats = state?.seats || [];
  const seated = seats.find((seat) => seat.account === account);
  const ready = Boolean(seated && state?.ready_accounts?.includes(account));
  const dbPath = state?.db?.path || "";
  const seatButtons = seats.map((seat) => {
    const occupied = Boolean(seat.account);
    const mine = account && seat.account === account;
    const label = occupied
      ? `${seatName(seat.seat)}：${escapeXml(seat.account)}${seat.ready ? "（已准备）" : ""}`
      : `${seatName(seat.seat)}：空闲（默认 ${escapeXml(seat.effective_account || "AI")}）`;
    const disabled = !account || (occupied && !mine) || (state?.game_started && state?.phase !== "round_over");
    return `<button class="seat-pick ${mine ? "active" : ""}" data-seat="${seat.seat}" ${disabled ? "disabled" : ""}>${label}</button>`;
  }).join("");
  panel.innerHTML = `
    <div class="battle-login-card">
      <div class="battle-login-row">
        <label>账号名 <input id="battleAccountInput" class="wide-input" type="text" value="${escapeAttr(account)}" placeholder="输入账号名即可登录" /></label>
        <button id="battleRegisterBtn" type="button">注册</button>
        <button id="battleLoginBtn" class="primary" type="button">${account ? "切换/登录" : "登录"}</button>
        ${account ? `<span class="tag">当前账号：${escapeXml(account)}</span>` : ""}
      </div>
      <div class="battle-seat-grid">${seatButtons}</div>
      <div class="battle-login-row">
        <button id="battleReadyBtn" class="${ready ? "ready-toggle ready-off" : "ready-toggle gold"}" type="button" ${!seated ? "disabled" : ""}>${ready ? "已准备" : (state?.phase === "round_over" ? "准备下一局" : "准备")}</button>
        <button id="battleLeaveBtn" type="button" ${!seated || (state?.game_started && state?.phase !== "round_over") ? "disabled" : ""}>离座</button>
        <span class="meta">数据库：${escapeXml(dbPath)}</span>
      </div>
    </div>
  `;
  const input = $("battleAccountInput");
  const register = $("battleRegisterBtn");
  const login = $("battleLoginBtn");
  if (register) register.addEventListener("click", () => registerBattleAccount(input?.value || ""));
  if (login) login.addEventListener("click", () => loginBattleAccount(input?.value || ""));
  panel.querySelectorAll(".seat-pick").forEach((button) => {
    button.addEventListener("click", () => sitBattleSeat(Number(button.dataset.seat)));
  });
  if ($("battleReadyBtn")) $("battleReadyBtn").addEventListener("click", readyBattleAccount);
  if ($("battleLeaveBtn")) $("battleLeaveBtn").addEventListener("click", leaveBattleSeat);
}

function renderBattleLobbyOnly() {
  if (APP_MODE === "battle" && state?.game_started && !humanPlayer()) {
    window.location.href = "/battle-login";
    return true;
  }
  if (APP_MODE === "battle" && !state?.game_started) {
    const account = battleAccountValue();
    const seated = Boolean(account && (state?.seats || []).some((seat) => seat.account === account));
    if (!seated) {
      window.location.href = "/battle-login";
      return true;
    }
    renderBattleShell();
    if ($("players")) $("players").innerHTML = "";
    if ($("tableDiscards")) $("tableDiscards").innerHTML = "";
    if ($("tableCenterInfo")) $("tableCenterInfo").innerHTML = `<div class="center-wall-text">等待准备</div>`;
    if ($("battleFocus")) $("battleFocus").hidden = true;
    if ($("settlementPopup")) {
      $("settlementPopup").classList.remove("visible");
      $("settlementPopup").innerHTML = "";
    }
    if ($("actionBar")) {
      const ready = Boolean(state?.ready_accounts?.includes(account));
      $("actionBar").innerHTML = ready ? `<span class="tag">已准备，等待其他玩家</span>` : "";
      const button = document.createElement("button");
      button.className = ready ? "ready-toggle ready-off" : "ready-toggle gold";
      button.textContent = ready ? "已准备" : "准备";
      button.addEventListener("click", () => newRound(false));
      $("actionBar").appendChild(button);
    }
    if ($("hand")) $("hand").innerHTML = "";
    if ($("history")) $("history").innerHTML = "";
    if ($("analysis")) $("analysis").innerHTML = "";
    renderPlayerStatsModal();
    updateBattleToolbarControls();
    return true;
  }
  renderBattleShell();
  if (state?.game_started) return false;
  if ($("players")) $("players").innerHTML = "";
  if ($("tableDiscards")) $("tableDiscards").innerHTML = "";
  if ($("tableCenterInfo")) $("tableCenterInfo").innerHTML = `<div class="center-wall-text">等待入座准备</div>`;
  if ($("battleFocus")) $("battleFocus").hidden = true;
  if ($("settlementPopup")) {
    $("settlementPopup").classList.remove("visible");
    $("settlementPopup").innerHTML = "";
  }
  if ($("actionBar")) $("actionBar").innerHTML = `<span class="tag">登录、入座并准备后开始游戏</span>`;
  if ($("hand")) $("hand").innerHTML = "";
  if ($("history")) $("history").innerHTML = "";
  if ($("analysis")) $("analysis").innerHTML = "";
  renderPlayerStatsModal();
  return true;
}

function renderStatus() {
  renderGameHeader();
  const wallToDrawGame = state.wall_to_draw_game ?? state.wall_remaining ?? "-";
  const centerIndicatorMode = state.center_indicator_mode || (state.bao_phase ? "bao" : "de");
  const items = [
    ["庄家", playerBySeat(state.dealer)?.label || ""],
    ["离黄牌", `${wallToDrawGame} 张`],
    ["阶段", state.bao_phase ? "包张" : "普通"],
    [centerIndicatorMode === "bao" ? "包" : "得", centerIndicatorMode === "bao" ? "包" : tileLabel(state.de_indicator)],
    ["花牌范围", state.flower_set.map(tileLabel).join("、")]
  ];
  const statusStrip = $("statusStrip");
  if (statusStrip) {
    statusStrip.innerHTML = items.map(([label, value]) => `
      <div class="status-item">
        <div class="status-label">${label}</div>
        <div class="status-value">${value}</div>
      </div>
    `).join("");
  }
  const center = $("tableCenterInfo");
  if (center) {
    const indicator = centerIndicatorMode === "bao"
      ? `<div class="center-bao-mark">包</div>`
      : `<div class="center-de-tile">${tileHtml(state.de_indicator, "small")}</div>`;
    center.innerHTML = `
      ${indicator}
      <div class="center-wall-count"><strong>${wallToDrawGame} 张</strong></div>
    `;
  }
  const centerDice = document.querySelector(".center-dice");
  if (centerDice) centerDice.textContent = seatWind(state.dealer);
  const phaseBanner = $("tablePhaseBanner");
  if (phaseBanner) {
    phaseBanner.innerHTML = `
      <span>${phaseText(state.phase)}</span>
      <strong>第 ${state.round_no} 局</strong>
    `;
  }
}

function pendingKindText(kind) {
  const labels = {
    response_poll: "response",
    discard_hu: "胡牌",
    rob_gang: "抢杠",
    ming_gang: "明杠",
    peng: "碰",
    chi: "吃"
  };
  return labels[kind] || kind || "响应";
}

function actionFeedbackLabel(action) {
  if (!action) return "动作";
  if (action.type === "discard") return `出 ${tileLabel(action.tile)}`;
  return actionButtonText(action, state?.legal_actions || []) || actionText(action);
}

function pendingWaitingText() {
  const pending = state?.pending;
  if (!pending) return "";
  const human = humanPlayer();
  const decided = human && Array.isArray(pending.decision_seats)
    && pending.decision_seats.map(Number).includes(Number(human.seat));
  if (decided) return "已提交，等待其他玩家/AI";
  if (pending.kind === "ai_turn") return "AI 正在思考";
  if (Array.isArray(pending.ai_candidates) && pending.ai_candidates.length) return "等待 AI 响应";
  if (pending.kind === "response_poll") return "等待响应结算";
  return `等待${pendingKindText(pending.kind)}`;
}

function clearPendingTimers() {
  if (pendingResolveTimer) {
    clearTimeout(pendingResolveTimer);
    pendingResolveTimer = null;
  }
  if (pendingCountdownTimer) {
    clearInterval(pendingCountdownTimer);
    pendingCountdownTimer = null;
  }
}

function renderPendingCountdown() {
  clearPendingTimers();
}

async function resolvePendingAfterCountdown() {
  if (busy || resolvingPending || !state?.pending?.deferred) return;
  const hasHumanResponse = Array.isArray(state.legal_actions) && state.legal_actions.length > 0;
  const hasAiResponse = Array.isArray(state.pending.ai_candidates) && state.pending.ai_candidates.length > 0;
  if (hasHumanResponse && !hasAiResponse) return;
  resolvingPending = true;
  try {
    setGameState(await post("/api/resolve_pending", {}));
    render();
  } catch (error) {
    console.warn(error);
    await refresh();
  } finally {
    resolvingPending = false;
  }
}

function seatClass(seat) {
  return ["seat-bottom", "seat-right", "seat-top", "seat-left"][seat] || "seat-side";
}

function playerBySeat(seat) {
  return (state?.players || []).find((player) => Number(player.seat) === Number(seat));
}

function humanPlayer() {
  return (state?.players || []).find((player) => player.is_human) || null;
}

function seatWind(seatOrPlayer) {
  const player = typeof seatOrPlayer === "object" ? seatOrPlayer : playerBySeat(seatOrPlayer);
  if (player?.wind) return player.wind;
  const seat = typeof seatOrPlayer === "object" ? Number(seatOrPlayer.seat) : Number(seatOrPlayer);
  return ["东", "南", "西", "北"][seat] || `${seat + 1}`;
}

function backTiles(count) {
  const visible = Math.max(0, Math.min(Number(count) || 0, 18));
  return Array.from({ length: visible }, () => `<span class="tile-back"></span>`).join("");
}

function seatHandTiles(player) {
  if (player.is_human) return "";
  const revealed = state.phase === "round_over" && player.hand && Object.keys(player.hand).length;
  if (revealed) {
    return expandHand(player.hand).map((code) => tileHtml(code, "small", "revealed")).join("");
  }
  return backTiles(player.hand_count);
}

function meldTypeText(type) {
  if (type === "peng") return "碰";
  if (type === "chi") return "吃";
  if (type === "ming_gang") return "明杠";
  if (type === "an_gang") return "暗杠";
  if (type === "bu_gang") return "补杠";
  return type || "副露";
}

function meldTiles(melds) {
  return melds.map((meld) => `
    <span class="meld-set ${meld.type === "an_gang" ? "concealed-kong" : ""}" title="${meldTypeText(meld.type)} ${(meld.tiles || []).map(tileLabel).join(" ")}">
      ${meldDisplayTiles(meld).map((code) => tileHtml(code, "small", code === "*" ? "kong-hidden" : "")).join("")}
      <span class="meld-type">${meldTypeText(meld.type)}</span>
    </span>
  `).join("");
}

function meldSetHtml(meld) {
  return `
    <span class="meld-set ${meld.type === "an_gang" ? "concealed-kong" : ""}" title="${meldTypeText(meld.type)} ${(meld.tiles || []).map(tileLabel).join(" ")}">
      ${meldDisplayTiles(meld).map((code) => tileHtml(code, "small", code === "*" ? "kong-hidden" : "")).join("")}
      <span class="meld-type">${meldTypeText(meld.type)}</span>
    </span>
  `;
}

function rowCapacityStyle(count) {
  const rowCount = Math.max(10, Number(count) || 0);
  return `style="--row-count:${rowCount};--row-gaps:${Math.max(0, rowCount - 1)}"`;
}

function publicMeldRows(melds) {
  const main = [];
  const overflow = [];
  let mainTiles = 0;
  let overflowTiles = 0;
  for (const meld of melds || []) {
    const tileCount = (meld.tiles || []).length;
    if (mainTiles + tileCount <= 10) {
      main.push(meld);
      mainTiles += tileCount;
    } else {
      overflow.push(meld);
      overflowTiles += tileCount;
    }
  }
  return `
    <div class="seat-tile-row meld-row meld-row-overflow" ${rowCapacityStyle(overflowTiles)}>${overflow.map(meldSetHtml).join("")}</div>
    <div class="seat-tile-row meld-row meld-row-main" ${rowCapacityStyle(mainTiles)}>${main.map(meldSetHtml).join("")}</div>
  `;
}

function claimedDiscardRemovals() {
  const removals = new Map();
  for (const claimer of state.players || []) {
    for (const meld of claimer.melds || []) {
      if (!["chi", "peng", "ming_gang"].includes(meld.type)) continue;
      const from = Number(meld.from);
      if (!Number.isInteger(from) || from === claimer.seat || !meld.tile) continue;
      if (!removals.has(from)) removals.set(from, { indices: new Set(), tiles: [] });
      const bucket = removals.get(from);
      const discardIndex = Number(meld.discard_index);
      if (Number.isInteger(discardIndex) && discardIndex >= 0) {
        bucket.indices.add(discardIndex);
      } else {
        bucket.tiles.push(meld.tile);
      }
    }
  }
  return removals;
}

function visibleDiscardsFor(player, removals) {
  const removal = removals.get(player.seat);
  if (!removal) return [...(player.discards || [])];
  const fallbackTiles = [...removal.tiles];
  return [...(player.discards || [])].filter((tile, idx) => {
    if (removal.indices.has(idx)) return false;
    const fallbackIndex = fallbackTiles.indexOf(tile);
    if (fallbackIndex >= 0) {
      fallbackTiles.splice(fallbackIndex, 1);
      return false;
    }
    return true;
  });
}

function readDiscardZoneLayout() {
  try {
    const parsed = JSON.parse(localStorage.getItem(DISCARD_ZONE_LAYOUT_STORAGE_KEY) || "{}");
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function saveDiscardZoneLayout(layout) {
  try {
    localStorage.setItem(DISCARD_ZONE_LAYOUT_STORAGE_KEY, JSON.stringify(layout));
  } catch {
    // Dragging still works for the current render when storage is unavailable.
  }
}

function discardZonePositionStyle(key) {
  const item = readDiscardZoneLayout()[key];
  if (!item || !Number.isFinite(item.left) || !Number.isFinite(item.top)) return "";
  return `style="left:${item.left}px;top:${item.top}px;right:auto"`;
}

function bindDiscardZoneDragging() {
  if (!document.body.classList.contains("discard-layout-debug")) return;
  const table = document.querySelector(".mahjong-table");
  if (!table) return;
  const layout = readDiscardZoneLayout();
  document.querySelectorAll(".discard-zone").forEach((zone) => {
    const key = zone.dataset.zoneKey;
    if (!key) return;
    zone.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      const computed = getComputedStyle(zone);
      const startLeft = Number.parseFloat(computed.left) || zone.offsetLeft || 0;
      const startTop = Number.parseFloat(computed.top) || zone.offsetTop || 0;
      const startX = event.clientX;
      const startY = event.clientY;
      zone.classList.add("dragging");
      zone.setPointerCapture?.(event.pointerId);

      const move = (moveEvent) => {
        const left = Math.round(startLeft + moveEvent.clientX - startX);
        const top = Math.round(startTop + moveEvent.clientY - startY);
        zone.style.left = `${left}px`;
        zone.style.top = `${top}px`;
        zone.style.right = "auto";
        layout[key] = { left, top };
      };

      const finish = () => {
        zone.classList.remove("dragging");
        zone.releasePointerCapture?.(event.pointerId);
        saveDiscardZoneLayout(layout);
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", finish);
        window.removeEventListener("pointercancel", finish);
      };

      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", finish);
      window.addEventListener("pointercancel", finish);
    });
  });
}

function renderDiscards() {
  const box = $("tableDiscards");
  if (!box) return;
  const removals = claimedDiscardRemovals();
  const hist = state.history || [];
  let lastDiscardEvt = null;
  for (let i = hist.length - 1; i >= 0; i--) {
    if (hist[i].event === "discard") { lastDiscardEvt = hist[i]; break; }
  }
  let lastDiscardSeat = -1;
  if (lastDiscardEvt && Number.isInteger(Number(lastDiscardEvt.seat))) {
    lastDiscardSeat = Number(lastDiscardEvt.seat);
  } else if (lastDiscardEvt && lastDiscardEvt.message) {
    const msg = lastDiscardEvt.message;
    if (msg.startsWith("东")) lastDiscardSeat = 0;
    else if (msg.startsWith("南")) lastDiscardSeat = 1;
    else if (msg.startsWith("西")) lastDiscardSeat = 2;
    else if (msg.startsWith("北")) lastDiscardSeat = 3;
  }
  box.innerHTML = state.players.map((player) => {
    const visibleDiscards = visibleDiscardsFor(player, removals);
    const lastIdx = visibleDiscards.length - 1;
    const isLatest = lastIdx >= 0 && player.seat === lastDiscardSeat && visibleDiscards[lastIdx] === (lastDiscardEvt && lastDiscardEvt.tile);
    const discards = visibleDiscards.map((code, idx) =>
      tileHtml(code, "small", idx === lastIdx && isLatest ? "discard-last" : "")
    ).join("");
    const zoneKey = seatClass(player.seat);
    return `
      <div class="discard-zone discard-${zoneKey}" data-zone-key="${zoneKey}" ${discardZonePositionStyle(zoneKey)}>
        <span class="discard-label">${seatWind(player)}</span>
        <div class="discard-tiles">${discards || `<span class="discard-empty">暂无弃牌</span>`}</div>
      </div>
    `;
  }).join("");
  bindDiscardZoneDragging();
}

function winAnimationActive() {
  if (state?.phase !== "round_over" || state?.settlement?.winner === null || state?.settlement?.winner === undefined) {
    lastWinAnimationKey = null;
    lastWinAnimationStartedAt = 0;
    return false;
  }
  const key = settlementKey();
  if (!key) return false;
  if (lastWinAnimationKey !== key) {
    lastWinAnimationKey = key;
    lastWinAnimationStartedAt = Date.now();
  }
  return Date.now() - lastWinAnimationStartedAt < 5000;
}

function isLeiziWinSettlement() {
  const winType = String(state?.settlement?.win_type || state?.win_type || "");
  return winType.includes("\u52a3\u5b50");
}

function renderPlayers() {
  const winAnimating = winAnimationActive();
  const leiziWinAnimating = winAnimating && isLeiziWinSettlement();
  const panels = state.players.map((player) => {
    const active = player.seat === state.current_player && state.phase !== "round_over" ? "active" : "";
    const human = player.is_human ? "human" : "";
    const winner = state.phase === "round_over" && state.settlement?.winner === player.seat ? "winning-player" : "";
    const winActive = winner && winAnimating && !leiziWinAnimating ? "win-animating" : "";
    const dealer = player.seat === state.dealer ? `<span class="seat-badge dealer">庄</span>` : "";
    const turn = active ? `<span class="seat-badge turn">行牌</span>` : "";
    const claimWarning = player.claim_warning ? `<span class="claim-warning-light" title="${escapeAttr(player.claim_warning.reason || "连续舍牌被同一人吃碰杠")}">警</span>` : "";
    const meldRows = publicMeldRows(player.melds || []);
    const flowers = publicFlowersFor(player).map((code) => tileHtml(code, "small")).join("");
    const handTiles = seatHandTiles(player);
    const roleLabel = player.is_human ? "你" : "AI";
    return `
      <article class="player-panel table-seat ${seatClass(player.seat)} ${active} ${human} ${winner} ${winActive}">
        <div class="player-head">
          <div class="seat-avatar">${seatWind(player)}</div>
          <div class="seat-meta">
            <div class="seat-name">${player.name || player.label}</div>
            <div class="seat-badges"><span class="seat-badge role">${roleLabel}</span>${dealer}${turn}${claimWarning}</div>
          </div>
          <span class="chip">${player.chips}</span>
        </div>
        <div class="seat-surface">
          ${handTiles ? `<div class="seat-tile-row concealed revealed-hand">${handTiles}</div>` : ""}
          ${meldRows}
          <div class="seat-tile-row flower-row" ${rowCapacityStyle(publicFlowersFor(player).length)}>${flowers}</div>
        </div>
        <div class="player-line">手牌 ${player.hand_count} · 花 ${player.flower_count}</div>
      </article>
    `;
  }).join("");
  const cornerHeads = state.players.map((player) => {
    const active = player.seat === state.current_player && state.phase !== "round_over" ? "active" : "";
    const human = player.is_human ? "human" : "";
    const dealerCorner = player.seat === state.dealer ? "dealer" : "";
    const winner = state.phase === "round_over" && state.settlement?.winner === player.seat ? "winning-player" : "";
    const winActive = winner && winAnimating && !leiziWinAnimating ? "win-animating" : "";
    const claimWarning = player.claim_warning ? `<span class="claim-warning-light corner-warning" title="${escapeAttr(player.claim_warning.reason || "连续舍牌被同一人吃碰杠")}">警</span>` : "";
    return `
      <div class="corner-player-head corner-${seatClass(player.seat)} ${active} ${human} ${dealerCorner} ${winner} ${winActive}">
        <span class="seat-avatar" title="${escapeAttr(player.name || player.label || "")}">${seatWind(player)}</span>
        <span class="corner-name">${escapeXml(player.name || "")}</span>
        <span class="chip">${player.chips}</span>
        ${claimWarning}
      </div>
    `;
  }).join("");
  const winnerBurst = winAnimating
    ? leiziWinAnimating
      ? `<div class="winner-burst winner-leizi-burst winner-${seatClass(state.settlement.winner)}" aria-hidden="true"><img src="${LEIZI_WIN_GIF_SRC}" alt="" /></div>`
      : `<div class="winner-burst winner-${seatClass(state.settlement.winner)}" aria-hidden="true"><span>胡</span></div>`
    : "";
  $("players").innerHTML = panels + cornerHeads + winnerBurst;
  renderDiscards();
}

function settlementKey() {
  if (!state?.settlement) return "";
  const deltas = state.settlement.point_deltas || state.settlement.deltas || [];
  return `${state.round_no}:${state.settlement.winner}:${state.settlement.win_type}:${deltas.join(",")}`;
}

function settlementHidden() {
  const key = settlementKey();
  return Boolean(key && dismissedSettlementKey === key);
}

function toggleSettlementPopup() {
  const key = settlementKey();
  if (!key) return;
  dismissedSettlementKey = dismissedSettlementKey === key ? null : key;
  renderActionsV2();
  renderSettlementPopup();
}

function detailItemText(item, valueKey, suffix) {
  if (!item) return "";
  if (typeof item === "string") return item;
  const value = item[valueKey];
  return `${item.label || ""}${value !== undefined ? ` +${value}${suffix}` : ""}`;
}

function fallbackBaseDetails(player, score) {
  const rows = [];
  const flowers = publicFlowersFor(player);
  if (flowers.length) rows.push(`花牌 ${flowers.map(tileLabel).join("、")} +${flowers.length * 4}和`);
  for (const meld of player.melds || []) {
    rows.push(`${meldTypeText(meld.type)} ${meld.tiles.map(tileLabel).join("、")}`);
  }
  if (score?.plan?.length) rows.push(`和牌组合 ${score.plan.join("、")}`);
  return rows;
}

function settlementDetailRows(player, score) {
  const baseItems = (score?.base_items || []).map((item) => detailItemText(item, "points", "和"));
  const fanItems = (score?.fan_items || []).map((item) => detailItemText(item, "fan", "番"));
  const base = baseItems.length ? baseItems : fallbackBaseDetails(player, score);
  const fan = fanItems.length ? fanItems : (score?.fan ? ["旧结算未返回番种明细，后端安全重启后会显示来源。"] : ["无额外番"]);
  return { base, fan };
}

function renderSettlementPopup() {
  const popup = $("settlementPopup");
  if (!popup) return;
  const settlement = state?.settlement;
  const key = settlementKey();
  if (state.phase !== "round_over" || !settlement || dismissedSettlementKey === key) {
    popup.classList.remove("visible");
    popup.innerHTML = "";
    return;
  }
  const pointDeltas = settlement.point_deltas || settlement.deltas || [];
  const rows = state.players.map((player) => {
    const scoreIndex = Number(player.seat);
    const score = settlement.scores?.[scoreIndex] || {};
    const details = settlementDetailRows(player, score);
    const delta = pointDeltas?.[scoreIndex] ?? 0;
    const deltaClass = Number(delta) >= 0 ? "score-good" : "score-bad";
    const limitReason = score.limit_reason ? `<span class="settlement-limit">${score.limit_reason}</span>` : "";
    return `
      <div class="settlement-row">
        <div class="settlement-row-head">
          <strong>${player.label}</strong>
          <span>底分 ${score.base ?? "-"} 点 番 ${score.fan ?? "-"} 番 总点 ${score.total ?? "-"} ${limitReason}</span>
          <span class="${deltaClass}">${Number(delta) >= 0 ? "+" : ""}${delta}</span>
        </div>
        <div class="settlement-detail"><b>牌点</b>${details.base.map((text) => `<span>${text}</span>`).join("")}</div>
        <div class="settlement-detail"><b>番数</b>${details.fan.map((text) => `<span>${text}</span>`).join("")}</div>
      </div>
    `;
  }).join("");
  const bao = settlement.bao;
  const baoBanner = bao
    ? `<div class="settlement-bao-banner">包牌：${playerBySeat(bao.seat)?.label || `座位${bao.seat}`} · ${bao.reason || ""}</div>`
    : "";
  popup.innerHTML = `
    <div class="settlement-popup-head">
      <strong>${settlement.win_type || state.win_type || "结算结果"}</strong>
      <span>筹码变化 ${pointDeltas.join(" / ") || ""}</span>
      <button id="settlementCloseBtn" type="button">关闭</button>
    </div>
    ${baoBanner}
    <div class="settlement-popup-body">${rows}</div>
  `;
  popup.classList.add("visible");
  const close = $("settlementCloseBtn");
  if (close) {
    close.addEventListener("click", () => {
      dismissedSettlementKey = key;
      popup.classList.remove("visible");
      popup.innerHTML = "";
      renderActionsV2();
    });
  }
}

function statNumber(value, digits = 2) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : "-";
}

function openPlayerStatsModal() {
  const modal = $("playerStatsModal");
  if (!modal) return;
  modal.hidden = false;
  renderPlayerStatsModal();
}

function closePlayerStatsModal() {
  const modal = $("playerStatsModal");
  if (!modal) return;
  modal.hidden = true;
}


function renderPlayerStatsModal() {
  const modal = $("playerStatsModal");
  const body = $("playerStatsBody");
  if (!modal || !body || modal.hidden) return;
  const rows = state?.player_stats || [];
  if (!rows.length) {
    body.innerHTML = `<div class="player-stats-empty">\u6682\u65e0\u7edf\u8ba1\u3002\u5b8c\u6210\u53d1\u724c\u540e\u4f1a\u5f00\u59cb\u8bb0\u5f55\u3002</div>`;
    return;
  }

  const emptyStats = () => ({
    rounds: 0,
    avg_opening_shanten: null,
    avg_de_draws: null,
    avg_fan_flower_draws: null,
    win_rate: null,
    normal_win_rate: null,
    leizi_win_rate: null,
    avg_win_turn: null,
    avg_win_points: null,
    wins: 0,
    normal_wins: 0,
    leizi_wins: 0,
    luck_score: null,
  });
  const normalized = rows.map((row) => {
    if (row.all || row.today) return row;
    const all = {
      ...emptyStats(),
      rounds: row.rounds,
      avg_opening_shanten: row.avg_opening_shanten,
      avg_de_draws: row.avg_de_draws,
      avg_fan_flower_draws: row.avg_fan_flower_draws,
      win_rate: row.win_rate,
      avg_win_turn: row.avg_win_turn,
      avg_win_points: row.avg_win_points,
      wins: row.wins,
      luck_score: row.luck_score,
    };
    return { account: row.name, all, today: all };
  });
  const statsByAccount = new Map(normalized.map((row) => [String(row.account || ""), row]));
  const currentPlayers = (state?.players || []).slice().sort((a, b) => Number(a.seat || 0) - Number(b.seat || 0));
  const displayRows = currentPlayers.length
    ? currentPlayers.map((player) => {
      const account = String(player.name || player.label || "");
      return {
        account,
        wind: player.wind || seatWind(player),
        stats: statsByAccount.get(account) || { account, all: emptyStats(), today: emptyStats() },
      };
    })
    : normalized.slice(0, 4).map((row) => ({ account: row.account || "-", wind: "-", stats: row }));

  const statCell = (stats, key, digits = 2) => statNumber(stats?.[key], digits);
  const rateCell = (stats, key) => {
    const value = Number(stats?.[key]);
    return Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "-";
  };
  const countCell = (stats, key) => `${Number(stats?.[key] || 0)}`;
  const luckText = (stats) => {
    const value = Number(stats?.luck_score);
    return Number.isFinite(value) ? value.toFixed(1) : "\u5f85\u5b9a";
  };
  const pairCell = (allStats, todayStats, key, formatter = statCell) => `${formatter(allStats, key)} / ${formatter(todayStats, key)}`;

  body.innerHTML = `
    <div class="player-stats-cards">
      ${displayRows.map((row) => {
        const allStats = row.stats?.all || emptyStats();
        const todayStats = row.stats?.today || emptyStats();
        return `
          <section class="player-stat-card">
            <div class="player-stat-summary">
              <div class="player-stat-player">
                <strong>${escapeXml(row.account || "-")}</strong>
                <span>${escapeXml(row.wind || "-")}</span>
              </div>
              <div class="player-stat-luck">
                <span>\u8fd0\u6c14\u5ea6</span>
                <b>${escapeXml(luckText(allStats))}</b>
              </div>
            </div>
            <details class="player-stat-details">
              <summary>\u8be6\u60c5</summary>
              <div class="player-stat-detail-grid">
                <span>\u7edf\u8ba1\u8303\u56f4</span><b>\u957f\u671f / \u4eca\u65e5</b>
                <span>\u5c40\u6570</span><b>${countCell(allStats, "rounds")} / ${countCell(todayStats, "rounds")}</b>
                <span>\u80e1\u724c\u7387</span><b>${pairCell(allStats, todayStats, "win_rate", rateCell)}</b>
                <span>\u666e\u901a\u80e1\u7387</span><b>${pairCell(allStats, todayStats, "normal_win_rate", rateCell)}</b>
                <span>\u52a3\u5b50\u80e1\u7387</span><b>${pairCell(allStats, todayStats, "leizi_win_rate", rateCell)}</b>
                <span>\u80e1\u724c\u5de1\u76ee</span><b>${pairCell(allStats, todayStats, "avg_win_turn")}</b>
                <span>\u80e1\u724c\u70b9\u6570</span><b>${pairCell(allStats, todayStats, "avg_win_points")}</b>
                <span>\u8d77\u624b\u5411\u542c</span><b>${pairCell(allStats, todayStats, "avg_opening_shanten")}</b>
                <span>\u6bcf\u5c40\u5f97\u724c</span><b>${pairCell(allStats, todayStats, "avg_de_draws")}</b>
                <span>\u6bcf\u5c40\u52a0\u756a\u82b1</span><b>${pairCell(allStats, todayStats, "avg_fan_flower_draws")}</b>
              </div>
              <div class="player-stat-luck-note">\u8fd0\u6c14\u5ea6\u7b97\u6cd5\u5f85\u8865\u5145\uff1b\u5f53\u524d\u53ea\u9884\u7559\u5165\u53e3\uff0c\u4e0d\u53c2\u4e0e\u8ba1\u7b97\u3002</div>
            </details>
          </section>
        `;
      }).join("")}
    </div>
    <div class="player-stats-note">\u53ea\u663e\u793a\u5f53\u524d\u724c\u5c40\u4e2d\u7684 4 \u4e2a\u73a9\u5bb6\uff1b\u8be6\u60c5\u9879\u6309\u201c\u957f\u671f / \u4eca\u65e5\u201d\u5c55\u793a\uff0c\u7edf\u8ba1\u7ed1\u5b9a\u8d26\u53f7\u540d\u3002</div>
  `;
}

function renderActions() {
  const legal = state.legal_actions || [];
  const bar = $("actionBar");
  bar.innerHTML = "";
  if (state.phase === "round_over") {
    const text = state.settlement?.winner === null
      ? `黄牌：${state.settlement?.reason || ""}`
      : `${playerBySeat(state.winner)?.label || ""} ${state.win_type}`;
    if (state.settlement) {
      const button = document.createElement("button");
      button.className = settlementHidden() ? "settlement-toggle" : "settlement-toggle gold";
      button.textContent = "结算";
      button.addEventListener("click", toggleSettlementPopup);
      bar.appendChild(button);
    }
    const nextButton = document.createElement("button");
    const ready = APP_MODE === "battle" && state?.ready_accounts?.includes(battleAccountValue());
    nextButton.className = APP_MODE === "battle" ? (ready ? "ready-toggle ready-off" : "ready-toggle gold") : "primary";
    nextButton.textContent = APP_MODE === "battle" ? (ready ? "已准备" : "准备") : "下一局";
    nextButton.addEventListener("click", () => newRound(false));
    bar.appendChild(nextButton);
    return;
  }
  if (!legal.length) {
    if (state.pending?.deferred) {
      return;
    }
    bar.innerHTML = `<span class="tag">${phaseText(state.phase)}</span>`;
    return;
  }
  const nonDiscard = legal.filter((action) => action.type !== "discard");
  for (const action of nonDiscard) {
    const button = document.createElement("button");
    button.innerHTML = `<span class="action-icon">${actionIcon(action)}</span><span>${actionText(action)}</span>`;
    button.className = action.type === "hu" ? "warn hu-action" : action.type.includes("gang") ? "gold" : "";
    button.addEventListener("click", () => sendAction(action));
    bar.appendChild(button);
  }
  if (legal.some((action) => action.type === "discard")) {
    const span = document.createElement("span");
    span.className = "tag";
    span.textContent = "请选择出牌";
    bar.appendChild(span);
  }
}

function renderHand() {
  const human = humanPlayer();
  if (!human) return;
  const legalDiscards = new Set((state.legal_actions || [])
    .filter((action) => action.type === "discard")
    .map((action) => action.tile));
  const tiles = expandHand(human.hand);
  let drawnTile = null;
  if (human.last_draw && human.hand[human.last_draw] > 0) {
    const drawIndex = tiles.lastIndexOf(human.last_draw);
    if (drawIndex >= 0) {
      drawnTile = tiles.splice(drawIndex, 1)[0];
    }
  }
  if (drawnTile) tiles.push(drawnTile);
  $("hand").innerHTML = tiles.map((code, index) => {
    const discardable = legalDiscards.has(code) ? "discardable" : "";
    const newDraw = drawnTile && index === tiles.length - 1 ? "new-draw" : "";
    return tileHtml(code, "", (discardable + " " + newDraw).trim());
  }).join("");
  $("hand").querySelectorAll(".discardable").forEach((el) => {
    el.addEventListener("click", () => sendAction({ type: "discard", tile: el.dataset.tile }));
  });
}

function renderHistory() {
  const box = $("history");
  if (!box) return;
  box.innerHTML = (state.history || []).slice().reverse().map((entry) => (
    `<div class="history-line">${entry.message}</div>`
  )).join("");
}

function renderActionsV2() {
  const legal = state.legal_actions || [];
  const bar = $("actionBar");
  bar.innerHTML = "";
  if (pendingActionFeedback) {
    bar.innerHTML = `<span class="tag action-feedback">${escapeXml(pendingActionFeedback.message)}</span>`;
    return;
  }
  if (state.phase === "round_over") {
    const text = state.settlement?.winner === null
      ? `榛勭墝锛?{state.settlement?.reason || ""}`
      : `${playerBySeat(state.winner)?.label || ""} ${state.win_type}`;
    if (state.settlement) {
      const button = document.createElement("button");
      button.className = settlementHidden() ? "settlement-toggle" : "settlement-toggle gold";
      button.textContent = "结算";
      button.addEventListener("click", toggleSettlementPopup);
      bar.appendChild(button);
    }
    const nextButton = document.createElement("button");
    const ready = state?.ready_accounts?.includes(battleAccountValue());
    nextButton.className = ready ? "ready-toggle ready-off" : "ready-toggle gold";
    nextButton.textContent = ready ? "已准备" : "准备";
    nextButton.addEventListener("click", () => newRound(false));
    bar.appendChild(nextButton);
    return;
  }
  if (!legal.length) {
    if (state.pending?.deferred) {
      const waiting = pendingWaitingText();
      bar.innerHTML = waiting ? `<span class="tag action-feedback">${escapeXml(waiting)}</span>` : "";
      return;
    }
    bar.innerHTML = `<span class="tag">${phaseText(state.phase)}</span>`;
    return;
  }
  syncSelectedDiscardTile();
  for (const action of legal.filter((item) => item.type !== "discard")) {
    const button = document.createElement("button");
    button.textContent = actionButtonText(action, legal);
    button.className = action.type === "hu" ? "warn hu-action" : action.type.includes("gang") ? "gold" : "";
    button.addEventListener("click", () => sendAction(action));
    bar.appendChild(button);
  }
  if (legal.some((action) => action.type === "discard")) {
    if (selectedDiscardTile) {
      const button = document.createElement("button");
      button.className = "discard-confirm";
      button.textContent = "出";
      button.addEventListener("click", () => sendAction({ type: "discard", tile: selectedDiscardTile }));
      bar.appendChild(button);
    } else {
      const span = document.createElement("span");
      span.className = "tag";
      span.textContent = "请选择一张手牌";
      bar.appendChild(span);
    }
  }
}

function renderHandV2() {
  const human = humanPlayer();
  if (!human || !human.hand || !Object.keys(human.hand).length) {
    const hand = $("hand");
    if (hand) hand.innerHTML = "";
    selectedDiscardTile = null;
    selectedDiscardKey = null;
    renderActionsV2();
    return;
  }
  const canDiscardNow = !busy && !pendingActionFeedback && !state.pending && state.phase === "turn" && state.current_player === human.seat;
  const legalDiscards = legalDiscardTiles();
  syncSelectedDiscardTile();
  const { tiles, drawnTile } = displayedHandTiles(human);
  const validSelectionKeys = new Set(tiles.map((code, index) => `${code}:${index}`));
  if (selectedDiscardKey && !validSelectionKeys.has(selectedDiscardKey)) {
    selectedDiscardKey = null;
    selectedDiscardTile = null;
  }
  $("hand").innerHTML = tiles.map((code, index) => {
    const discardable = canDiscardNow && legalDiscards.has(code) ? "discardable" : "";
    const newDraw = drawnTile && index === tiles.length - 1 ? "new-draw" : "";
    const key = `${code}:${index}`;
    const selected = discardable && selectedDiscardKey === key ? "selected-discard" : "";
    return tileHtml(code, "", (discardable + " " + newDraw + " " + selected).trim())
      .replace(" data-tile=", ` data-hand-key="${escapeAttr(key)}" data-tile=`);
  }).join("");
  $("hand").querySelectorAll(".discardable").forEach((el) => {
    el.addEventListener("click", () => {
      const key = el.dataset.handKey || "";
      const same = selectedDiscardKey === key;
      selectedDiscardTile = same ? null : el.dataset.tile;
      selectedDiscardKey = same ? null : key;
      renderActionsV2();
      renderHandV2();
    });
  });
}

function renderAnalysis() {
  const box = $("analysis");
  if (!box) return;
  const settlement = state.settlement;
  const pointDeltas = settlement?.point_deltas || settlement?.deltas || [];
  const header = settlement ? `
    <div class="analysis-item">
      <div><strong>${settlement.win_type}</strong>${settlement.reason ? ` · ${settlement.reason}` : ""}</div>
      <div>筹码变化：${pointDeltas.join(" / ") || ""}</div>
    </div>
  ` : "";
  const rows = (state.analysis || []).slice().reverse().map((item) => {
    const cls = item.bad ? "score-bad" : "score-good";
    return `
      <div class="analysis-item">
        <div class="${cls}">${item.score} 分 · ${item.chosen}</div>
        <div>模型首选：${item.best || "无"}（${item.best_score ?? "-"}）</div>
        <div>${item.reason}</div>
        <div>${item.suggestion}</div>
      </div>
    `;
  }).join("");
  box.innerHTML = header + (rows || `<div class="analysis-item">暂无人类决策记录。</div>`);
}
function render() {
  if (activeView === "game" && renderBattleLobbyOnly()) return;
  renderBattleShell();
  renderStatus();
  renderPendingCountdown();
  renderBattleFocus();
  renderPlayers();
  renderActionsV2();
  renderHandV2();
  renderHistory();
  renderAnalysis();
  renderSettlementPopup();
  renderPlayerStatsModal();
  updateBattleToolbarControls();
}

async function refresh() {
  const path = APP_MODE === "battle" || activeView === "game"
    ? `/api/battle/state${battleQuery()}`
    : "/api/state";
  if (setGameState(await api(path), { announce: false, force: true })) render();
}

async function stepGame() {
  if (steppingGame) return;
  steppingGame = true;
  try {
    const path = APP_MODE === "battle" || activeView === "game"
      ? `/api/battle/step${battleQuery()}`
      : "/api/step";
    if (setGameState(await api(path))) render();
  } finally {
    steppingGame = false;
  }
}

async function refreshBattleState() {
  if (APP_MODE !== "battle" || refreshingGame || steppingGame || resolvingPending) return;
  refreshingGame = true;
  try {
    if (setGameState(await api(`/api/battle/state${battleQuery()}`), { announce: false })) render();
  } finally {
    refreshingGame = false;
  }
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitBattleStateOnce() {
  if (APP_MODE !== "battle" || refreshingGame || steppingGame || resolvingPending) {
    await delay(200);
    return;
  }
  refreshingGame = true;
  try {
    const since = Number.isFinite(Number(state?.room_revision)) ? Number(state.room_revision) : null;
    const result = await api(`/api/battle/wait${battleWaitQuery(since)}`);
    if (setGameState(result, { announce: true })) render();
  } catch (error) {
    console.warn("battle wait failed", error);
    await delay(1000);
    await refreshBattleState();
  } finally {
    refreshingGame = false;
  }
}

async function startBattleWaitLoop() {
  if (battleWaitLoopActive) return;
  battleWaitLoopActive = true;
  while (APP_MODE === "battle" && battleWaitLoopActive) {
    if (shouldAutoStepGame()) {
      await waitBattleStateOnce();
    } else {
      await delay(500);
    }
  }
}

async function sendBattleHeartbeat() {
  const account = battleAccountValue();
  if (!account || !Number.isInteger(Number(state?.room_generation))) return;
  try {
    await post("/api/battle/heartbeat", { account });
  } catch (error) {
    console.warn("battle heartbeat failed", error);
  }
}

async function startBattleHeartbeatLoop() {
  if (battleHeartbeatLoopActive) return;
  battleHeartbeatLoopActive = true;
  while (APP_MODE === "battle" && battleHeartbeatLoopActive) {
    await sendBattleHeartbeat();
    await delay(BATTLE_HEARTBEAT_INTERVAL_MS);
  }
}

function shouldAutoStepGame() {
  return activeView === "game" || $("gameView")?.classList.contains("active");
}

function humanHasActionChoice() {
  if (!state || state.phase === "round_over") return false;
  const legal = state.legal_actions || [];
  if (!legal.length) return false;
  const human = humanPlayer();
  return Boolean(human);
}

async function sendAction(action) {
  if (busy || resolvingPending) return;
  clearPendingTimers();
  busy = true;
  setBusy(true);
  pendingActionFeedback = {
    action,
    room_generation: state?.room_generation,
    pending_id: state?.pending_id,
    action_token: state?.action_token || null,
    message: `已提交 ${actionFeedbackLabel(action)}，等待服务器确认`
  };
  renderActionsV2();
  renderHandV2();
  try {
    const path = APP_MODE === "battle" || activeView === "game" ? "/api/battle/action" : "/api/action";
    const payload = path.includes("/battle/")
      ? {
          account: battleAccountValue(),
          action,
          action_token: state?.action_token || null,
          room_generation: state?.room_generation ?? null,
          pending_id: state?.pending_id ?? null
        }
      : { action };
    const next = await post(path, payload);
    pendingActionFeedback = null;
    setGameState(next);
    render();
  } catch (error) {
    pendingActionFeedback = null;
    renderActionsV2();
    renderHandV2();
    alert(error.message);
  } finally {
    busy = false;
    setBusy(false);
    renderActionsV2();
    renderHandV2();
    updateBattleToolbarControls();
  }
}

async function loginBattleAccount(account) {
  const name = String(account || "").trim();
  if (!name) {
    alert("请输入账号名");
    return;
  }
  try {
    const result = await post("/api/battle/login", { account: name });
    saveBattleAccount(result.account || name);
    setGameState(await api(`/api/battle/state${battleQuery()}`), { announce: false });
    render();
  } catch (error) {
    alert(error.message);
  }
}

async function registerBattleAccount(account) {
  const name = String(account || "").trim();
  if (!name) {
    alert("请输入账号名");
    return;
  }
  try {
    const result = await post("/api/battle/register", { account: name });
    saveBattleAccount(result.account || name);
    setGameState(await api(`/api/battle/state${battleQuery()}`), { announce: false });
    render();
  } catch (error) {
    alert(error.message);
  }
}

async function sitBattleSeat(seat) {
  if (!battleAccountValue()) {
    alert("请先登录账号");
    return;
  }
  try {
    setGameState(await post("/api/battle/sit", { account: battleAccountValue(), seat }), { announce: false });
    render();
  } catch (error) {
    alert(error.message);
  }
}

async function leaveBattleSeat() {
  if (!battleAccountValue()) return;
  try {
    setGameState(await post("/api/battle/leave", { account: battleAccountValue() }), { announce: false });
    render();
  } catch (error) {
    alert(error.message);
  }
}

function setRoomMenuOpen(open) {
  roomMenuOpen = Boolean(open);
  const panel = $("roomMenuPanel");
  const button = $("roomMenuBtn");
  if (panel) panel.hidden = !roomMenuOpen;
  if (button) button.setAttribute("aria-expanded", roomMenuOpen ? "true" : "false");
  renderRoomDiagnostics();
}

function toggleRoomMenu() {
  setRoomMenuOpen(!roomMenuOpen);
}

async function exitBattleRoom() {
  const account = battleAccountValue();
  setRoomMenuOpen(false);
  if (account) {
    try {
      await post("/api/battle/leave", { account });
    } catch (error) {
      console.warn("leave battle room skipped", error);
    }
  }
  window.location.href = "/battle-login";
}

function recordBattleClientError(kind, value) {
  recentBattleClientErrors.push({
    ts: Date.now(),
    kind: String(kind || "error"),
    message: String(value?.stack || value?.message || value || "unknown client error").slice(0, 2000),
  });
  recentBattleClientErrors = recentBattleClientErrors.slice(-20);
}

function bugReportClientContext() {
  return {
    url: window.location.href,
    user_agent: navigator.userAgent,
    language: navigator.language,
    viewport: {
      inner_width: window.innerWidth,
      inner_height: window.innerHeight,
      visual_width: window.visualViewport?.width ?? null,
      visual_height: window.visualViewport?.height ?? null,
      device_pixel_ratio: window.devicePixelRatio,
      orientation: screen.orientation?.type || null,
    },
    document_visibility: document.visibilityState,
    state: {
      room_generation: state?.room_generation ?? null,
      room_revision: state?.room_revision ?? null,
      event_seq: state?.event_seq ?? null,
      round_no: state?.round_no ?? null,
      phase: state?.phase ?? null,
      current_player: state?.current_player ?? null,
      pending_id: state?.pending_id ?? null,
      pending_kind: state?.pending?.kind ?? null,
      wall_remaining: state?.wall_remaining ?? null,
    },
    recent_api_timings: recentBattleApiTimings.slice(-20),
    recent_client_errors: recentBattleClientErrors.slice(-20),
  };
}

function setBugReportModalOpen(open) {
  const modal = $("bugReportModal");
  if (!modal) return;
  modal.hidden = !open;
  if (open) {
    setRoomMenuOpen(false);
    if ($("bugReportRoundMeta")) {
      const roundState = state?.phase === "round_over" ? "已结束" : "进行中";
      $("bugReportRoundMeta").textContent = `当前第 ${state?.round_no ?? "-"} 局 · ${roundState}`;
    }
    if ($("bugReportModalStatus")) $("bugReportModalStatus").textContent = "";
    window.setTimeout(() => $("bugReportNote")?.focus(), 0);
  }
}

function openBattleBugReport() {
  if (busy || !battleAccountValue() || !state?.game_started) return;
  setBugReportModalOpen(true);
}

async function reportBattleBug(event) {
  event?.preventDefault();
  if (busy || !battleAccountValue() || !state?.game_started) return;
  const note = $("bugReportNote")?.value || "";
  const status = $("bugReportStatus");
  const modalStatus = $("bugReportModalStatus");
  busy = true;
  setBusy(true);
  if (status) status.textContent = "正在保存完整牌局信息…";
  if (modalStatus) modalStatus.textContent = "正在保存完整牌局信息…";
  try {
    const result = await post("/api/battle/report-bug", {
      account: battleAccountValue(),
      note,
      client_context: bugReportClientContext(),
    });
    if (status) status.textContent = `已保存，编号 ${result.report_id}`;
    if (modalStatus) modalStatus.textContent = `已保存，编号 ${result.report_id}`;
    if ($("bugReportNote")) $("bugReportNote").value = "";
    window.setTimeout(() => setBugReportModalOpen(false), 700);
  } catch (error) {
    recordBattleClientError("bug_report", error);
    if (status) status.textContent = `保存失败：${error.message}`;
    if (modalStatus) modalStatus.textContent = `保存失败：${error.message}`;
  } finally {
    busy = false;
    setBusy(false);
    updateBattleToolbarControls();
  }
}

async function readyBattleAccount() {
  if (!battleAccountValue()) {
    alert("请先登录账号");
    return;
  }
  try {
    saveBattleAiPolicy();
    setGameState(await post("/api/battle/ready", { account: battleAccountValue() }), { announce: false });
    render();
  } catch (error) {
    alert(error.message);
  }
}

function setBusy(value) {
  if ($("newRoundBtn")) $("newRoundBtn").disabled = value;
  if ($("resetMatchBtn")) $("resetMatchBtn").disabled = value;
  if ($("shuffleSeatsBtn")) $("shuffleSeatsBtn").disabled = value;
  if ($("exitRoomBtn")) $("exitRoomBtn").disabled = value;
  if ($("bugReportBtn")) $("bugReportBtn").disabled = value;
  document.querySelectorAll("#actionBar button").forEach((button) => {
    button.disabled = value;
  });
}

function updateBattleToolbarControls() {
  if (APP_MODE !== "battle") return;
  const resetButton = $("resetMatchBtn");
  const readyButton = $("newRoundBtn");
  const menu = $("roomMenu");
  const exitButton = $("exitRoomBtn");
  const bugReportButton = $("bugReportBtn");
  if (readyButton) readyButton.hidden = true;
  if (menu) menu.hidden = false;
  if (exitButton) exitButton.disabled = busy;
  if (bugReportButton) {
    bugReportButton.disabled = busy || !state?.game_started || state?.bug_report?.available === false;
    bugReportButton.title = bugReportButton.disabled ? "当前没有可举报的牌局" : "保存当前牌局的完整诊断信息";
  }
  if (resetButton) {
    resetButton.hidden = false;
    resetButton.textContent = "重置房间";
    resetButton.disabled = busy || state?.phase !== "round_over";
    resetButton.title = resetButton.disabled ? "本局结束后才能重置房间座次" : "随机重排当前人类玩家座次";
  }
  renderRoomDiagnostics();
}

function renderRoomDiagnostics() {
  if (APP_MODE !== "battle") return;
  const panel = $("roomMenuPanel");
  if (!panel) return;
  let box = $("roomDiagnostics");
  if (!box) {
    box = document.createElement("div");
    box.id = "roomDiagnostics";
    box.className = "room-diagnostics";
    panel.appendChild(box);
  }
  const runtime = state?.runtime || {};
  const apiRows = recentBattleApiTimings.slice(-5).reverse().map((item) => `
    <div class="${item.ok ? "" : "bad"}">
      <span>${escapeXml(item.method)} ${escapeXml(item.path)}</span>
      <b>${item.elapsed_ms}ms</b>
    </div>
  `).join("");
  const slowRows = (runtime.last_slow_events || []).slice(-3).reverse().map((item) => `
    <div class="bad">
      <span>${escapeXml(item.api || "-")} ${escapeXml(item.details?.event_type || "")}</span>
      <b>${formatNumber(item.processing_ms ?? item.elapsed_ms, 0)}ms</b>
    </div>
  `).join("");
  box.innerHTML = `
    <div class="room-diagnostics-title">运行诊断</div>
    <div class="room-diagnostics-grid">
      <span>队列</span><b>${Number(runtime.room_event_queue_length || 0)}</b>
      <span>执行中</span><b>${runtime.processing_room_event ? "是" : "否"}</b>
      <span>等待连接</span><b>${Number(runtime.waiter_count || 0)}</b>
      <span>AI 思考</span><b>${Number(runtime.ai_thinking_count || 0)}</b>
    </div>
    <div class="room-diagnostics-subtitle">最近请求</div>
    <div class="room-diagnostics-rows">${apiRows || "<div><span>暂无</span><b>-</b></div>"}</div>
    <div class="room-diagnostics-subtitle">服务端慢事件</div>
    <div class="room-diagnostics-rows">${slowRows || "<div><span>暂无</span><b>-</b></div>"}</div>
  `;
}

async function newRound(reset = false) {
  if (busy) return;
  setRoomMenuOpen(false);
  busy = true;
  setBusy(true);
  try {
    saveBattleAiPolicy();
    const endpoint = reset ? "/api/battle/reset" : "/api/battle/ready";
    setGameState(await post(endpoint, { account: battleAccountValue() }), { announce: false });
    render();
  } catch (error) {
    alert(error.message);
  } finally {
    busy = false;
    setBusy(false);
    renderActionsV2();
    renderHandV2();
    updateBattleToolbarControls();
  }
}
function applyAppMode() {
  document.body.classList.add("battle-app-mode");
  activeView = "game";
  if ($("battleLoginPanel")) $("battleLoginPanel").hidden = true;
  if ($("trainingTabBtn")) $("trainingTabBtn").hidden = true;
  if ($("gameTabBtn")) $("gameTabBtn").hidden = true;
  if ($("shuffleSeatsBtn")) $("shuffleSeatsBtn").hidden = true;
  if ($("newRoundBtn")) $("newRoundBtn").hidden = true;
  if ($("newRoundBtn")) $("newRoundBtn").textContent = "准备";
  if ($("resetMatchBtn")) $("resetMatchBtn").textContent = "重置房间";
  updateBattleToolbarControls();
  if ($("trainingView")) $("trainingView").classList.remove("active");
  if ($("gameView")) $("gameView").classList.add("active");
  if ($("roundMeta")) $("roundMeta").textContent = "人机对战";
}
function syncBattleMobileViewport() {
  if (APP_MODE !== "battle") return;
  const coarse = window.matchMedia ? window.matchMedia("(pointer: coarse)").matches : false;
  const viewport = window.visualViewport;
  const rawW = viewport?.width || window.innerWidth || document.documentElement.clientWidth || 0;
  const rawH = viewport?.height || window.innerHeight || document.documentElement.clientHeight || 0;
  const smallViewport = rawW <= 900 || rawH <= 520;
  const mobile = coarse || smallViewport;
  document.body.classList.toggle("battle-mobile-table", mobile);
  if (!mobile) {
    document.body.classList.remove("battle-mobile-portrait");
    document.documentElement.style.removeProperty("--battle-mobile-scale");
    document.documentElement.style.removeProperty("--battle-mobile-table-w");
    document.documentElement.style.removeProperty("--battle-mobile-table-h");
    document.documentElement.style.removeProperty("--battle-mobile-vw");
    document.documentElement.style.removeProperty("--battle-mobile-vh");
    document.documentElement.style.removeProperty("--battle-mobile-shell-w");
    document.documentElement.style.removeProperty("--battle-mobile-shell-h");
    return;
  }

  const visualW = Math.max(1, Math.round(rawW));
  const visualH = Math.max(1, Math.round(rawH));
  const portrait = visualH > visualW;
  document.body.classList.toggle("battle-mobile-portrait", portrait);
  const viewportW = portrait ? visualH : visualW;
  const viewportH = portrait ? visualW : visualH;
  let scale = viewportW / BATTLE_MOBILE_LOGICAL_WIDTH;
  let logicalH = viewportH / scale;
  if (logicalH < BATTLE_MOBILE_MIN_LOGICAL_HEIGHT) {
    logicalH = BATTLE_MOBILE_MIN_LOGICAL_HEIGHT;
    scale = viewportH / logicalH;
  }
  document.documentElement.style.setProperty("--battle-mobile-scale", Math.max(0.1, scale).toFixed(4));
  document.documentElement.style.setProperty("--battle-mobile-table-w", `${BATTLE_MOBILE_LOGICAL_WIDTH}px`);
  document.documentElement.style.setProperty("--battle-mobile-table-h", `${Math.round(logicalH)}px`);
  document.documentElement.style.setProperty("--battle-mobile-vw", `${visualW}px`);
  document.documentElement.style.setProperty("--battle-mobile-vh", `${visualH}px`);
  document.documentElement.style.setProperty("--battle-mobile-shell-w", `${viewportW}px`);
  document.documentElement.style.setProperty("--battle-mobile-shell-h", `${viewportH}px`);
}

function preventBattleViewportGesture(event) {
  if (APP_MODE !== "battle") return;
  event.preventDefault();
}

function bindBattleViewportLock() {
  if (APP_MODE !== "battle" || bindBattleViewportLock.bound) return;
  bindBattleViewportLock.bound = true;
  document.addEventListener("gesturestart", preventBattleViewportGesture, { passive: false });
  document.addEventListener("gesturechange", preventBattleViewportGesture, { passive: false });
  document.addEventListener("gestureend", preventBattleViewportGesture, { passive: false });
  document.addEventListener("touchmove", preventBattleViewportGesture, { passive: false });
}

function bindTileHover() {
  let hoveredCode = null;
  document.addEventListener("mouseover", function(e) {
    const tile = e.target.closest(".tile[data-tile]");
    if (!tile) {
      if (hoveredCode) {
        document.querySelectorAll(".tile.tile-hover-match").forEach(function(t) { t.classList.remove("tile-hover-match"); });
        hoveredCode = null;
      }
      return;
    }
    const code = tile.dataset.tile;
    if (code === hoveredCode) return;
    if (hoveredCode) {
      document.querySelectorAll(".tile.tile-hover-match").forEach(function(t) { t.classList.remove("tile-hover-match"); });
    }
    hoveredCode = code;
    var selector = ".tile[data-tile=\"" + code + "\"]";
    document.querySelectorAll(selector).forEach(function(t) { t.classList.add("tile-hover-match"); });
  });
}

async function initBattleApp() {
  restoreBattleAccount();
  applyAppMode();
  syncBattleMobileViewport();
  bindBattleViewportLock();
  window.addEventListener("resize", syncBattleMobileViewport);
  window.addEventListener("orientationchange", syncBattleMobileViewport);
  window.visualViewport?.addEventListener("resize", syncBattleMobileViewport);
  window.visualViewport?.addEventListener("scroll", syncBattleMobileViewport);
  bindTileHover();
  window.addEventListener("error", (event) => recordBattleClientError("error", event.error || event.message));
  window.addEventListener("unhandledrejection", (event) => recordBattleClientError("unhandledrejection", event.reason));
  if ($("playerStatsBtn")) $("playerStatsBtn").addEventListener("click", () => {
    setRoomMenuOpen(false);
    openPlayerStatsModal();
  });
  if ($("playerStatsCloseBtn")) $("playerStatsCloseBtn").addEventListener("click", closePlayerStatsModal);
  if ($("roomMenuBtn")) $("roomMenuBtn").addEventListener("click", (event) => {
    event.stopPropagation();
    toggleRoomMenu();
  });
  if ($("roomMenuPanel")) $("roomMenuPanel").addEventListener("click", (event) => event.stopPropagation());
  if ($("exitRoomBtn")) $("exitRoomBtn").addEventListener("click", exitBattleRoom);
  if ($("bugReportBtn")) $("bugReportBtn").addEventListener("click", openBattleBugReport);
  if ($("bugReportForm")) $("bugReportForm").addEventListener("submit", reportBattleBug);
  if ($("bugReportCancelBtn")) $("bugReportCancelBtn").addEventListener("click", () => setBugReportModalOpen(false));
  if ($("bugReportModal")) {
    $("bugReportModal").addEventListener("click", (event) => {
      if (event.target === $("bugReportModal")) setBugReportModalOpen(false);
    });
  }
  document.addEventListener("click", () => setRoomMenuOpen(false));
  if ($("playerStatsModal")) {
    $("playerStatsModal").addEventListener("click", (event) => {
      if (event.target === $("playerStatsModal")) closePlayerStatsModal();
    });
  }
  if ($("newRoundBtn")) $("newRoundBtn").addEventListener("click", () => newRound(false));
  if ($("resetMatchBtn")) $("resetMatchBtn").addEventListener("click", () => newRound(true));
  await refresh();
  startBattleWaitLoop().catch((error) => console.warn("battle wait loop stopped", error));
  startBattleHeartbeatLoop().catch((error) => console.warn("battle heartbeat loop stopped", error));
}

async function init() {
  tileNames = await api("/api/tiles");
  await initBattleApp();
}

init().catch((error) => {
  document.body.innerHTML = `<pre>${error.stack || error.message}</pre>`;
});
