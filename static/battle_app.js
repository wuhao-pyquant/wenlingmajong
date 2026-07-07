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
let transientActionNotice = "";
let transientActionNoticeTimer = null;
let recentBattleApiTimings = [];
let recentBattleClientErrors = [];
let voiceEnabled = true;
let speechQueue = [];
let speechActiveSince = 0;
let speechPendingTimer = null;
let currentBattleAccount = null;
let battleRoomSummary = null;
let battleRoomSummaryRefreshing = false;
const seatActionEffects = new Map();
const seatActionEffectTimers = new Map();

const $ = (id) => document.getElementById(id);
const APP_MODE = "battle";
const EXCEPTIONAL_LUCK_WIN_GIF_SRC = "/assets/q_dazed_drool_5s.gif";
const BATTLE_ACCOUNT_STORAGE_KEY = "wenling.online.account.v1";
const BATTLE_TOKEN_STORAGE_KEY = "wenling.online.token.v1";
const BATTLE_ROLE_STORAGE_KEY = "wenling.online.role.v1";
const BATTLE_ROOM_STORAGE_KEY = "wenling.online.room_id.v1";
const BATTLE_ROOM_SUMMARY_STORAGE_KEY = "wenling.online.room_summary.v1";
const BATTLE_AI_POLICY_STORAGE_KEY = "wenling.battle.ai_policy.v2";
const DISCARD_ZONE_LAYOUT_STORAGE_KEY = "wenling.discard.zone.layout.v3";
const DEFAULT_BATTLE_AI_POLICY = "low";
const BATTLE_AI_POLICY_OPTIONS = [
  ["low", "\u4f4e\u7ea7"],
  ["high", "\u9ad8\u7ea7"],
];
const SPEECH_MIN_AUDIBLE_MS = 300;
const BATTLE_HEARTBEAT_INTERVAL_MS = 10000;
const BATTLE_MOBILE_LOGICAL_WIDTH = 1500;
const BATTLE_TABLE_BASE_HEIGHT = 780;
const BATTLE_MOBILE_MIN_LOGICAL_HEIGHT = BATTLE_TABLE_BASE_HEIGHT;
const BATTLE_RIVER_NORMAL_LIMIT = 12;
const BATTLE_RIVER_DENSE_LIMIT = 15;
const BATTLE_PUBLIC_MELD_ROW_LIMIT = 10.45;
const BATTLE_PUBLIC_COMPACT_LIMIT = 20;
const BATTLE_PUBLIC_OVERFLOW_LIMIT = 26;
const BATTLE_TABLE_LAYOUT_MODE = "v7";
const BATTLE_DOM_V7_REMOTE_TILE_SCALE = 1;
const BATTLE_DOM_V7_PUBLIC_TILE_SCALE = 1;
const BATTLE_DOM_V7_RIVER_TILE_SCALE = 1;
const BATTLE_TABLE_RENDERER_MODE = (() => {
  try {
    return new URLSearchParams(window.location.search).get("renderer") === "dom" ? "dom" : "canvas";
  } catch {
    return "canvas";
  }
})();
const BATTLE_TABLE_TILE_RENDERER_MODE = (() => {
  try {
    return new URLSearchParams(window.location.search).get("tiles") === "canvas" ? "canvas" : "dom";
  } catch {
    return "dom";
  }
})();
const BATTLE_GENERATION_WRITE_PATHS = new Set([
  "heartbeat",
  "sit",
  "leave",
  "ready",
  "reset",
  "report-bug",
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
function normalizeBattleAiPolicy(value) {
  const key = String(value || "").trim().toLowerCase();
  if (key === "tile_efficiency" || key === "normal" || key === "medium") return "high";
  if (key === "low_latency" || key === "fast") return "low";
  if (key === "unlimited") return "high";
  return BATTLE_AI_POLICY_OPTIONS.some(([policy]) => policy === key) ? key : DEFAULT_BATTLE_AI_POLICY;
}

function battleAiPolicyOptionsHtml() {
  return BATTLE_AI_POLICY_OPTIONS
    .map(([value, label]) => `<option value="${value}">${label}</option>`)
    .join("");
}

function battleAiPolicyValue() {
  const select = $("battleAiPolicySelect");
  if (select) return normalizeBattleAiPolicy(select.value);
  try {
    return normalizeBattleAiPolicy(localStorage.getItem(BATTLE_AI_POLICY_STORAGE_KEY));
  } catch {
    return DEFAULT_BATTLE_AI_POLICY;
  }
}

function saveBattleAiPolicy() {
  const value = battleAiPolicyValue();
  try {
    localStorage.setItem(BATTLE_AI_POLICY_STORAGE_KEY, value);
  } catch {
    // Local storage can be unavailable in hardened browser profiles.
  }
  return value;
}

function restoreBattleAiPolicy() {
  const select = $("battleAiPolicySelect");
  if (!select) return;
  let value = state?.ai_policy || DEFAULT_BATTLE_AI_POLICY;
  try {
    value = localStorage.getItem(BATTLE_AI_POLICY_STORAGE_KEY) || value;
  } catch {
    // Local storage can be unavailable in hardened browser profiles.
  }
  select.value = normalizeBattleAiPolicy(value);
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

function battleTokenValue() {
  try {
    return localStorage.getItem(BATTLE_TOKEN_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function saveBattleToken(token) {
  try {
    if (token) localStorage.setItem(BATTLE_TOKEN_STORAGE_KEY, token);
    else localStorage.removeItem(BATTLE_TOKEN_STORAGE_KEY);
  } catch {
    // Local storage can be unavailable in hardened browser profiles.
  }
}

function battleRoomIdValue() {
  const fromUrl = new URLSearchParams(window.location.search).get("room_id");
  if (fromUrl) {
    try {
      localStorage.setItem(BATTLE_ROOM_STORAGE_KEY, fromUrl);
    } catch {
      // Local storage can be unavailable in hardened browser profiles.
    }
    return fromUrl;
  }
  try {
    return localStorage.getItem(BATTLE_ROOM_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function normalizeBattleRoomSummary(room) {
  if (!room) return null;
  return {
    room_id: String(room.room_id || ""),
    room_name: String(room.room_name || ""),
    owner_account: String(room.owner_account || ""),
    ai_policy: normalizeBattleAiPolicy(room.ai_policy || state?.ai_policy || DEFAULT_BATTLE_AI_POLICY),
    status: String(room.status || room.room_status || state?.room_status || ""),
    game_started: Boolean(room.game_started ?? state?.game_started),
    room_generation: room.room_generation ?? state?.room_generation ?? null,
    room_revision: room.room_revision ?? state?.room_revision ?? null,
    seats: Array.isArray(room.seats) ? room.seats : [],
  };
}

function saveBattleRoomSummary(room) {
  const summary = normalizeBattleRoomSummary(room);
  const roomId = battleRoomIdValue();
  if (!summary?.room_id || (roomId && summary.room_id !== roomId)) return null;
  battleRoomSummary = summary;
  try {
    localStorage.setItem(BATTLE_ROOM_SUMMARY_STORAGE_KEY, JSON.stringify(summary));
  } catch {
    // Local storage can be unavailable in hardened browser profiles.
  }
  return summary;
}

function loadBattleRoomSummary() {
  const roomId = battleRoomIdValue();
  try {
    const raw = localStorage.getItem(BATTLE_ROOM_SUMMARY_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || (roomId && parsed.room_id !== roomId)) return null;
    battleRoomSummary = normalizeBattleRoomSummary(parsed);
  } catch {
    battleRoomSummary = null;
  }
  return battleRoomSummary;
}

function mergeBattleRoomSummaryFromState(nextState) {
  if (!nextState) return;
  const roomId = battleRoomIdValue();
  const base = battleRoomSummary || loadBattleRoomSummary() || { room_id: roomId };
  saveBattleRoomSummary({
    ...base,
    room_id: roomId,
    ai_policy: nextState.ai_policy || base.ai_policy,
    status: nextState.room_status || base.status,
    game_started: nextState.game_started ?? base.game_started,
    room_generation: nextState.room_generation ?? base.room_generation,
    room_revision: nextState.room_revision ?? base.room_revision,
    seats: Array.isArray(nextState.seats) ? nextState.seats : base.seats,
  });
}

function battleRoomMetadata() {
  const summary = battleRoomSummary || loadBattleRoomSummary() || {};
  return {
    ...summary,
    room_id: battleRoomIdValue() || summary.room_id || "",
    ai_policy: normalizeBattleAiPolicy(state?.ai_policy || summary.ai_policy || DEFAULT_BATTLE_AI_POLICY),
    status: state?.room_status || summary.status || "",
    game_started: state?.game_started ?? Boolean(summary.game_started),
    room_generation: state?.room_generation ?? summary.room_generation ?? null,
    room_revision: state?.room_revision ?? summary.room_revision ?? null,
    seats: Array.isArray(state?.seats) ? state.seats : (Array.isArray(summary.seats) ? summary.seats : []),
  };
}

async function refreshBattleRoomSummary() {
  if (APP_MODE !== "battle" || battleRoomSummaryRefreshing || !battleTokenValue()) return battleRoomMetadata();
  const roomId = battleRoomIdValue();
  if (!roomId) return battleRoomMetadata();
  battleRoomSummaryRefreshing = true;
  try {
    const payload = await api("/api/lobby/rooms");
    const room = (payload.rooms || []).find((item) => String(item.room_id) === String(roomId));
    if (room) saveBattleRoomSummary(room);
    return battleRoomMetadata();
  } finally {
    battleRoomSummaryRefreshing = false;
  }
}

function redirectToBattleLobby(message) {
  const notice = message ? `?notice=${encodeURIComponent(message)}` : "";
  window.location.href = `/battle-login${notice}`;
}

function battleApiPath(action) {
  const roomId = battleRoomIdValue();
  if (!roomId) {
    redirectToBattleLobby("缺少房间 ID，请从大厅进入房间。");
    throw new Error("缺少房间 ID");
  }
  return `/api/battle/${encodeURIComponent(roomId)}/${action}`;
}

function battleActionFromPath(path) {
  const clean = String(path || "").split("?")[0];
  const parts = clean.split("/").filter(Boolean);
  return parts[0] === "api" && parts[1] === "battle" && parts.length >= 4 ? parts[3] : "";
}

function battleWaitQuery(since) {
  const params = new URLSearchParams();
  if (since !== null && since !== undefined) params.set("since", String(since));
  params.set("timeout", "12");
  return `?${params.toString()}`;
}

async function battleApi(path, options = {}) {
  return api(path, options);
}
async function post(path, payload = {}) {
  let body = { ...(payload || {}) };
  if (BATTLE_GENERATION_WRITE_PATHS.has(battleActionFromPath(path)) && body.room_generation === undefined) {
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
  const request = { cache: "no-store", ...options };
  const headers = new Headers(options.headers || {});
  if (request.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const sessionToken = battleTokenValue();
  if (sessionToken && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${sessionToken}`);
  }
  request.headers = headers;
  try {
    const response = await fetch(path, request);
    status = response.status;
    const data = await readApiResponse(response);
    if (response.status === 401) {
      saveBattleToken("");
      saveBattleAccount("");
      redirectToBattleLobby("登录已失效，请重新登录。");
    }
    if (!response.ok || data.error || data.detail) {
      const detail = data.error || data.detail || `请求失败：${response.status}`;
      if (
        APP_MODE === "battle" &&
        String(path).startsWith("/api/battle/") &&
        /room not found|closed|房间/.test(String(detail))
      ) {
        redirectToBattleLobby("房间不存在或已关闭，请重新选择房间。");
      }
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
  recentBattleApiTimings = recentBattleApiTimings.slice(-60);
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
  if (/^b[1-9]$/.test(value)) return `${rank}筒`;
  const honors = {
    east: "东",
    south: "南",
    west: "西",
    north: "北",
    zhong: "中",
    fa: "发",
    bai: "白",
  };
  return honors[value] || tileLabel(code);
}

function scheduleSpeechPump(delayMs = 0) {
  if (speechPendingTimer !== null) window.clearTimeout(speechPendingTimer);
  speechPendingTimer = window.setTimeout(() => {
    speechPendingTimer = null;
    pumpSpeechQueue();
  }, Math.max(0, delayMs));
}

function nativeSpeechBridge() {
  return window.AndroidSpeech && typeof window.AndroidSpeech.speak === "function" ? window.AndroidSpeech : null;
}

function playSpeechNow(text) {
  const nativeSpeech = nativeSpeechBridge();
  if (nativeSpeech) {
    speechActiveSince = Date.now();
    nativeSpeech.speak(text);
    return;
  }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "zh-CN";
  utterance.rate = 1.08;
  utterance.pitch = 1;
  utterance.onend = () => {
    if (speechQueue.length) scheduleSpeechPump(0);
  };
  utterance.onerror = () => {
    if (speechQueue.length) scheduleSpeechPump(0);
  };
  speechActiveSince = Date.now();
  window.speechSynthesis.speak(utterance);
}

function pumpSpeechQueue() {
  if (!voiceEnabled || !speechQueue.length || (!nativeSpeechBridge() && !("speechSynthesis" in window))) return;
  try {
    const elapsed = Date.now() - speechActiveSince;
    if (speechActiveSince > 0 && elapsed < SPEECH_MIN_AUDIBLE_MS) {
      scheduleSpeechPump(SPEECH_MIN_AUDIBLE_MS - elapsed);
      return;
    }
    const next = speechQueue.shift();
    if (next) playSpeechNow(next);
    if (speechQueue.length) scheduleSpeechPump(SPEECH_MIN_AUDIBLE_MS);
  } catch {
    voiceEnabled = false;
    speechQueue = [];
  }
}

function speak(text) {
  if (!voiceEnabled || !text || (!nativeSpeechBridge() && !("speechSynthesis" in window))) return;
  const value = String(text).trim();
  if (!value) return;
  speechQueue.push(value);
  pumpSpeechQueue();
}

function historyEventKey(entry) {
  if (!entry) return "";
  return `${entry.ts ?? ""}|${entry.event ?? ""}|${entry.message ?? ""}|${entry.tile ?? ""}|${entry.kind ?? ""}`;
}

function spokenTextForEvent(entry) {
  if (!entry) return "";
  if (entry.event === "discard" && entry.tile) return speechTileName(entry.tile);
  if (entry.event === "claim") {
    if (entry.kind === "chi") return "\u5403";
    if (entry.kind === "peng") return "\u78b0";
    if (entry.kind === "ming_gang") return "\u6760";
    if (entry.message?.includes("\u5403")) return "\u5403";
    if (entry.message?.includes("\u78b0")) return "\u78b0";
    if (entry.message?.includes("\u6760")) return "\u6760";
  }
  if (entry.event === "kong") return "\u6760";
  if (entry.event === "flower") return "\u8865\u82b1";
  if (entry.event === "win") return "\u80e1";
  return "";
}

function shouldAnimateSpokenAction(entry) {
  if (!entry || entry.event === "discard" || entry.event === "win") return false;
  return ["claim", "kong", "flower"].includes(entry.event);
}

function triggerSeatActionEffect(entry, text) {
  if (!shouldAnimateSpokenAction(entry) || !text) return;
  const seat = Number(entry.seat);
  if (!Number.isInteger(seat)) return;
  const key = historyEventKey(entry);
  seatActionEffects.set(seat, {
    key,
    text,
    kind: String(entry.kind || entry.event || "action"),
    expiresAt: Date.now() + 1000,
  });
  if (seatActionEffectTimers.has(seat)) {
    window.clearTimeout(seatActionEffectTimers.get(seat));
  }
  const timer = window.setTimeout(() => {
    const current = seatActionEffects.get(seat);
    if (current?.key === key) {
      seatActionEffects.delete(seat);
      if (state) {
        renderPlayers();
        renderTableCanvas();
        updateSelectedTileHighlights();
      }
    }
    seatActionEffectTimers.delete(seat);
  }, 1000);
  seatActionEffectTimers.set(seat, timer);
}

function seatActionEffectHtml(seat) {
  const effect = seatActionEffects.get(Number(seat));
  if (!effect) return "";
  if (effect.expiresAt <= Date.now()) {
    seatActionEffects.delete(Number(seat));
    return "";
  }
  return `<span class="seat-action-pop" data-action-kind="${escapeAttr(effect.kind)}">${escapeXml(effect.text)}</span>`;
}

function seatActionEffectAnchorHtml(player) {
  const pop = seatActionEffectHtml(player?.seat);
  if (!pop) return "";
  return `<span class="seat-action-anchor seat-action-${seatClass(player.seat)}" data-seat="${player.seat}">${pop}</span>`;
}

function announceNewHistory(previous, next) {
  if (activeView !== "game" || !previous || !next) return;
  const previousKeys = new Set((previous.history || []).map(historyEventKey));
  for (const entry of next.history || []) {
    if (previousKeys.has(historyEventKey(entry))) continue;
    const text = spokenTextForEvent(entry);
    if (text) {
      speak(text);
      triggerSeatActionEffect(entry, text);
    }
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
    const tiles = displayedHandTiles(human).tiles;
    const keys = new Set(tiles.map((code, index) => `${code}:${index}`));
    if (!keys.has(selectedDiscardKey)) {
      const replacementIndex = tiles.findIndex((code) => code === selectedDiscardTile);
      if (replacementIndex >= 0) {
        selectedDiscardKey = `${selectedDiscardTile}:${replacementIndex}`;
      } else {
        selectedDiscardTile = null;
        selectedDiscardKey = null;
      }
    }
  }
}

function clearTransientActionNotice() {
  transientActionNotice = "";
  if (transientActionNoticeTimer) {
    window.clearTimeout(transientActionNoticeTimer);
    transientActionNoticeTimer = null;
  }
}

function showTransientActionNotice(message, timeoutMs = 1400) {
  transientActionNotice = String(message || "");
  if (transientActionNoticeTimer) window.clearTimeout(transientActionNoticeTimer);
  transientActionNoticeTimer = window.setTimeout(() => {
    transientActionNotice = "";
    transientActionNoticeTimer = null;
    renderActionsV2();
  }, timeoutMs);
}

function isStaleBattleActionError(error) {
  const message = String(error?.message || error || "");
  return /閻樿埖鈧礁鍑￠弴瀛樻煀|瀹稿弶娲块弬鐨榞eneration|stale|pending|action_token|閸掗攱鏌婅ぐ鎾冲閻楀苯鐪悩鑸碘偓浜呴柌宥嗘煀闁瀚ㄩ崝銊ょ稊/i.test(message);
}

function sameActionIntent(left, right) {
  if (!left || !right || String(left.type || "") !== String(right.type || "")) return false;
  const type = String(left.type || "");
  if (left.tile !== undefined || right.tile !== undefined) {
    if (String(left.tile || "") !== String(right.tile || "")) return false;
  }
  if (type === "chi") {
    const leftTiles = Array.isArray(left.tiles) ? left.tiles.map(String) : [];
    const rightTiles = Array.isArray(right.tiles) ? right.tiles.map(String) : [];
    if (leftTiles.length !== rightTiles.length) return false;
    return leftTiles.every((tile, index) => tile === rightTiles[index]);
  }
  return true;
}

function currentLegalActionForIntent(action) {
  const legal = Array.isArray(state?.legal_actions) ? state.legal_actions : [];
  return legal.find((candidate) => sameActionIntent(action, candidate)) || null;
}

function cssEscapeValue(value) {
  if (window.CSS?.escape) return window.CSS.escape(String(value));
  return String(value).replace(/["\\]/g, "\\$&");
}

function updateSelectedTileHighlights() {
  document.querySelectorAll(".tile.tile-selected-match").forEach((tile) => {
    tile.classList.remove("tile-selected-match");
  });
  if (!selectedDiscardTile) return;
  const selector = `.table-world-layer .tile[data-tile="${cssEscapeValue(selectedDiscardTile)}"]`;
  document.querySelectorAll(selector).forEach((tile) => {
    tile.classList.add("tile-selected-match");
  });
}
function setGameState(next, { announce = true, force = false } = {}) {
  if (APP_MODE === "battle" && next?.room_status === "closed") {
    alert("房间已关闭，返回大厅。");
    redirectToBattleLobby("房间已关闭，请重新选择房间。");
    return false;
  }
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
  mergeBattleRoomSummaryFromState(next);
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
  if (!selectedDiscardTile) updateSelectedTileHighlights();
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
    <text x="42" y="82" text-anchor="middle" font-size="30" font-weight="900" fill="#c92d2d" font-family="serif">万</text>
  `;
}

function honorIcon(code) {
  const map = {
    east: ["东", "#171713"],
    south: ["南", "#171713"],
    west: ["西", "#171713"],
    north: ["北", "#171713"],
    zhong: ["中", "#bf2421"],
    fa: ["发", "#16804c"],
    bai: ["白", "#1e5c8a"],
  };
  const [label, color] = map[code] || [tileLabel(code), "#171713"];
  const frame = code === "bai"
    ? '<rect x="24" y="24" width="36" height="52" rx="6" fill="none" stroke="#1e5c8a" stroke-width="4"/>'
    : "";
  return `
    ${frame}
    <text x="42" y="60" text-anchor="middle" dominant-baseline="middle" font-size="42" font-weight="900" fill="${color}" font-family="serif">${label}</text>
  `;
}

function flowerIcon(code) {
  const rank = tileRank(code);
  const red = code.startsWith("rh");
  const color = red ? "#c52624" : "#171713";
  const accent = red ? "#f8e5e5" : "#e7eaeb";
  return `
    <text x="42" y="28" text-anchor="middle" font-size="13" font-weight="850" fill="${color}">${red ? "红花" : "白花"}</text>
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
    const marker = `${player.label}摸花：`;
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

function cssPixelNumber(element, property, fallback) {
  if (!element) return fallback;
  const raw = getComputedStyle(element).getPropertyValue(property).trim();
  const value = Number.parseFloat(raw);
  return Number.isFinite(value) ? value : fallback;
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

function meldDisplayEntries(meld, ownerSeat) {
  const entries = meldDisplayTiles(meld).map((code) => ({
    code,
    claimed: false,
    direction: null,
  }));
  if (meld?.type === "an_gang") return entries;

  const fromSeat = Number(meld?.from);
  const seat = Number(ownerSeat);
  if (!Number.isInteger(fromSeat) || !Number.isInteger(seat) || fromSeat === seat) return entries;
  const direction = ({ 1: "right", 2: "top", 3: "left" })[(fromSeat - seat + 4) % 4];
  if (!direction) return entries;

  const claimedIndex = entries.findIndex((entry) => entry.code === meld?.tile);
  if (claimedIndex < 0) return entries;
  const [claimed] = entries.splice(claimedIndex, 1);
  claimed.claimed = true;
  claimed.direction = direction;
  const displayIndex = direction === "left" ? 0 : direction === "top" ? 1 : entries.length;
  entries.splice(Math.min(displayIndex, entries.length), 0, claimed);
  return entries;
}

function meldDisplayHtml(meld, ownerSeat) {
  return meldDisplayEntries(meld, ownerSeat).map((entry) => {
    const classes = [
      entry.code === "*" ? "kong-hidden" : "",
      entry.claimed ? "claimed-discard" : "",
      entry.direction ? `claimed-from-${entry.direction}` : "",
    ].filter(Boolean).join(" ");
    const tile = tileHtml(entry.code, "small", classes);
    if (!entry.claimed) return tile;
    const slotClasses = [
      "claimed-discard-slot",
      entry.direction ? `claimed-from-${entry.direction}` : "",
    ].filter(Boolean).join(" ");
    return `<span class="${slotClasses}">${tile}</span>`;
  }).join("");
}

function meldDisplaySpanUnits(meld, ownerSeat) {
  return meldDisplayEntries(meld, ownerSeat).reduce((sum, entry) => (
    sum + (entry.claimed ? 1.34 : 1)
  ), 0);
}

function splitPublicMeldRows(melds, ownerSeat, options = {}) {
  const main = [];
  const overflow = [];
  let mainUnits = 0;
  let overflowUnits = 0;
  const rowLimit = BATTLE_PUBLIC_MELD_ROW_LIMIT;
  const maxMainCount = Math.max(1, Number(options.maxMainCount) || 2);
  for (const meld of melds || []) {
    const span = meldDisplaySpanUnits(meld, ownerSeat);
    const mainCanFit = !main.length || (
      main.length < maxMainCount
      && mainUnits + span <= rowLimit
    );
    if (mainCanFit) {
      main.push(meld);
      mainUnits += span;
    } else {
      overflow.push(meld);
      overflowUnits += span;
    }
  }
  return { main, overflow, mainUnits, overflowUnits };
}

function publicDensityFor(flowers, melds, totalUnits) {
  const flowerCount = Array.isArray(flowers) ? flowers.length : Number(flowers) || 0;
  const meldCount = Array.isArray(melds) ? melds.length : Number(melds) || 0;
  if (totalUnits > BATTLE_PUBLIC_OVERFLOW_LIMIT || flowerCount >= 9 || meldCount >= 5) {
    return "overflow";
  }
  if (totalUnits > BATTLE_PUBLIC_COMPACT_LIMIT || flowerCount >= 7) {
    return "compact";
  }
  return "normal";
}

function publicMaxMainMeldCount(density) {
  return density === "overflow" ? 3 : 2;
}

function publicMeldRowSpanUnits(melds, ownerSeat) {
  const rows = splitPublicMeldRows(melds, ownerSeat);
  return Math.max(rows.mainUnits, rows.overflowUnits);
}

function publicMeldTotalUnits(melds, ownerSeat) {
  return (melds || []).reduce((sum, meld) => sum + meldDisplaySpanUnits(meld, ownerSeat), 0);
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
  if (type === "hu") return "胡";
  if (type === "pass") return "过";
  if (type === "an_gang") return `暗杠 ${tileLabel(action.tile)}`;
  if (type === "bu_gang") return `补杠 ${tileLabel(action.tile)}`;
  if (type === "ming_gang") return `明杠 ${tileLabel(action.tile)}`;
  if (type === "peng") return `碰 ${tileLabel(action.tile)}`;
  if (type === "chi") return `吃 ${action.tiles.map(tileLabel).join(" ")}`;
  if (type === "discard") return `出 ${tileLabel(action.tile)}`;
  return type;
}

function actionIcon(action) {
  const type = action.type;
  if (type === "hu") return "胡";
  if (type === "pass") return "过";
  if (type === "peng") return "碰";
  if (type === "chi") return "吃";
  if (type.includes("gang")) return "杠";
  if (type === "discard") return "出";
  return "牌";
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
  if (type === "discard") return "出牌";
  return actionText(action);
}

function phaseText(phase) {
  if (phase === "turn") {
    const player = playerBySeat(state.current_player) || state.players[state.current_player];
    return player?.is_human ? "轮到你出牌" : `${player?.label || ""} 思考中`;
  }
  if (phase === "round_over") return state.win_type || "本局结束";
  if (phase === "deal") return "发牌中";
  return phase;
}
function renderGameHeader() {
  if (activeView !== "game" || !state) return;
  $("roundMeta").textContent = `第 ${state.round_no} 局 · ${phaseText(state.phase)}`;
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

function isLiveResponseDiscard(discardEvent) {
  const pending = state?.pending;
  if (!discardEvent || !pending || pending.kind !== "response_poll") return false;
  if (pending.response_kind && pending.response_kind !== "discard") return false;
  if (pending.tile && discardEvent.tile && String(pending.tile) !== String(discardEvent.tile)) return false;
  const pendingFrom = Number(pending.from);
  const discardSeat = Number(discardEvent.seat);
  if (Number.isInteger(pendingFrom) && Number.isInteger(discardSeat) && pendingFrom !== discardSeat) return false;
  return true;
}

function compactActionText(action) {
  if (!action) return "";
  if (action.type === "discard") return "";
  return actionText(action);
}

function actionFocusText() {
  const legal = state?.legal_actions || [];
  if (state?.phase === "round_over") return state?.settlement ? "查看结算" : "本局结束";
  if (!legal.length) return state?.current_player === 0 ? "等待出牌" : "AI 思考中";
  const priority = legal.map(compactActionText).filter(Boolean);
  if (priority.length) return priority.slice(0, 4).join(" / ");
  if (legal.some((action) => action.type === "discard")) return "请选择要出的牌";
  return "等待操作";
}

function currentSeatFocus() {
  const player = state?.players?.[state.current_player];
  if (!player || state?.phase === "round_over") return "本局结束";
  return player.is_human ? "轮到你出牌" : `${player.label} 思考中`;
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
  if (!box) return;
  box.innerHTML = "";
  box.hidden = true;
}

function seatName(index) {
  return ["东位", "南位", "西位", "北位"][index] || `${index}`;
}

function renderBattleShell() {
  const panel = $("battleLoginPanel");
  if (panel) {
    panel.hidden = true;
    panel.innerHTML = "";
  }
}

function renderBattleLobbyOnly() {
  if (APP_MODE === "battle" && state?.room_status === "closed") {
    alert("房间已关闭，返回大厅。");
    redirectToBattleLobby("房间已关闭，请重新选择房间。");
    return true;
  }
  if (APP_MODE === "battle" && state?.game_started && !humanPlayer() && !isBattleRoomOwner()) {
    redirectToBattleLobby("你不在这个房间的座位上，请重新进入房间。");
    return true;
  }
  renderBattleShell();
  if (state?.game_started) return false;
  if ($("players")) $("players").innerHTML = "";
  if ($("tableDiscards")) $("tableDiscards").innerHTML = "";
  if ($("tableCenterInfo")) $("tableCenterInfo").innerHTML = '<div class="center-wall-text">等待入座准备</div>';
  if ($("battleFocus")) $("battleFocus").hidden = true;
  if ($("settlementPopup")) {
    $("settlementPopup").classList.remove("visible");
    $("settlementPopup").innerHTML = "";
  }
  if ($("actionBar")) $("actionBar").innerHTML = '<span class="tag">请回大厅选择座位并准备</span>';
  if ($("hand")) $("hand").innerHTML = "";
  if ($("history")) $("history").innerHTML = "";
  if ($("analysis")) $("analysis").innerHTML = "";
  renderPlayerStatsModal();
  return true;
}

function roomRoundCount() {
  const value = Number(state?.room_round_count ?? state?.round_no ?? 0);
  return Number.isFinite(value) && value > 0 ? Math.trunc(value) : 0;
}

function playerSeatValueMatches(value, absoluteValue, player) {
  if (!player) return false;
  const relativeSeat = Number(player.seat);
  const absoluteSeat = Number(player.absolute_seat);
  const candidates = [value, absoluteValue]
    .map((item) => Number(item))
    .filter((item) => Number.isInteger(item));
  return candidates.some((item) =>
    item === relativeSeat || (Number.isInteger(absoluteSeat) && item === absoluteSeat)
  );
}

function playerBaoReason(player) {
  const liability = player?.bao_liability || player?.bao_reason;
  if (!liability) return "";
  if (typeof liability === "string") return liability;
  return liability.reason || "包牌风险";
}

function centerSeatHudHtml(seat, position) {
  const player = playerBySeat(seat);
  const wind = player ? seatWind(player) : seatWind(seat);
  const name = player?.name || player?.account || player?.label || "";
  const chips = player ? player.chips : "-";
  const active = player && Number(player.seat) === Number(state?.current_player) && state?.phase !== "round_over";
  const dealer = player && Number(player.seat) === Number(state?.dealer);
  const warningReason = player?.claim_warning?.reason || "吃碰后进入警示状态";
  const warning = player?.claim_warning
    ? `<span class="center-seat-status center-seat-warning" title="${escapeAttr(warningReason)}" aria-label="${escapeAttr(warningReason)}">2连</span>`
    : "";
  const baoReason = playerBaoReason(player);
  const bao = baoReason
    ? `<span class="center-seat-status center-seat-bao" title="${escapeAttr(baoReason)}" aria-label="${escapeAttr(baoReason)}">包</span>`
    : "";
  return `
    <div class="center-seat-card center-seat-card-${position} ${active ? "active" : ""}" data-dealer="${dealer ? "1" : "0"}" data-seat="${seat}" title="${escapeAttr(player?.name || "")}">
      <span class="center-seat-main">
        <span class="center-seat-wind">${escapeXml(wind)}</span>
        <span class="center-seat-chip">${escapeXml(chips)}</span>
        ${warning}
        ${bao}
      </span>
      <span class="center-seat-name">${escapeXml(name)}</span>
    </div>
  `;
}

function renderStatus() {
  renderGameHeader();
  const wallToDrawGame = state.wall_to_draw_game ?? state.wall_remaining ?? "-";
  const centerIndicatorMode = state.center_indicator_mode || (state.bao_phase ? "bao" : "de");
  const items = [
    ["庄家", playerBySeat(state.dealer)?.label || ""],
    ["牌墙", `${wallToDrawGame} 张`],
    ["包牌", state.bao_phase ? "已进入" : "未进入"],
    [centerIndicatorMode === "bao" ? "包牌指示" : "得分指示", centerIndicatorMode === "bao" ? "包" : tileLabel(state.de_indicator)],
    ["花牌", (state.flower_set || []).map(tileLabel).join("、")],
  ];
  const statusStrip = $("statusStrip");
  if (statusStrip) {
    statusStrip.innerHTML = items.map(([label, value]) => `
      <div class="status-item">
        <div class="status-label">${escapeXml(label)}</div>
        <div class="status-value">${escapeXml(value)}</div>
      </div>
    `).join("");
  }
  const center = $("tableCenterInfo");
  if (center) {
    const indicator = centerIndicatorMode === "bao" ? "包" : tileLabel(state.de_indicator);
    center.innerHTML = `
      <div class="center-hud-grid">
        ${centerSeatHudHtml(2, "top")}
        ${centerSeatHudHtml(3, "left")}
        <div class="center-core">
          <div class="center-room-count">余牌 <strong>${escapeXml(wallToDrawGame)}</strong></div>
          <div class="center-core-row">
            <div class="center-indicator-card">
              <span class="center-de-label">${escapeXml(centerIndicatorMode === "bao" ? "包牌" : "得牌")}</span>
              <span class="${centerIndicatorMode === "bao" ? "center-bao-mark" : "center-de-tile"}">${escapeXml(indicator || "-")}</span>
            </div>
            <div class="center-wall-remaining">
              <span>余牌</span>
              <strong>${escapeXml(wallToDrawGame)}</strong>
              <small>张</small>
            </div>
          </div>
        </div>
        ${centerSeatHudHtml(1, "right")}
        ${centerSeatHudHtml(0, "bottom")}
      </div>
    `;
  }
}

function pendingKindText(kind) {
  const labels = {
    response_poll: "响应",
    discard_hu: "点炮胡",
    rob_gang: "抢杠",
    ming_gang: "明杠",
    peng: "碰",
    chi: "吃",
    ai_turn: "AI 出牌",
  };
  return labels[kind] || kind || "等待";
}

function actionFeedbackLabel(action) {
  if (!action) return "操作";
  if (action.type === "discard") return `出 ${tileLabel(action.tile)}`;
  return actionButtonText(action, state?.legal_actions || []) || actionText(action);
}

function pendingWaitingText() {
  const pending = state?.pending;
  if (!pending) return "";
  const human = humanPlayer();
  const decided = human && Array.isArray(pending.decision_seats)
    && pending.decision_seats.map(Number).includes(Number(human.seat));
  if (decided) return "已提交，等待其他玩家或 AI";
  if (pending.kind === "ai_turn") return "AI 思考中";
  if (Array.isArray(pending.ai_candidates) && pending.ai_candidates.length) return "等待 AI 响应";
  if (pending.kind === "response_poll") return "等待玩家响应";
  return `等待 ${pendingKindText(pending.kind)}`;
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

function meldTiles(melds, ownerSeat) {
  return melds.map((meld) => `
    <span class="meld-set ${meld.type === "an_gang" ? "concealed-kong" : ""}" title="${meldTypeText(meld.type)} ${(meld.tiles || []).map(tileLabel).join(" ")}">
      ${meldDisplayHtml(meld, ownerSeat)}
      <span class="meld-type">${meldTypeText(meld.type)}</span>
    </span>
  `).join("");
}

function battleTableRendererState() {
  if (!state) return null;
  const removals = claimedDiscardRemovals();
  return {
    ...state,
    players: (state.players || []).map((player) => ({
      ...player,
      flowers: publicFlowersFor(player),
      visible_discards: visibleDiscardsFor(player, removals),
    })),
  };
}

function modelBlock(model, type, seat = undefined, predicate = null) {
  return (model?.blocks || []).find((block) => (
    block.type === type
    && (seat === undefined || Number(block.seat) === Number(seat))
    && (!predicate || predicate(block))
  )) || null;
}

function setImportantStyle(el, property, value) {
  if (!el || value === null || value === undefined || value === "") return;
  el.style.setProperty(property, String(value), "important");
}

function domV7ScaleFactors(tableEl, model) {
  const rect = tableEl?.getBoundingClientRect?.();
  const table = model?.config?.table || model?.table || {};
  return {
    sx: Math.max(0.01, ((rect?.width || table.width || 1) / Math.max(1, table.width || 1))),
    sy: Math.max(0.01, ((rect?.height || table.height || 1) / Math.max(1, table.height || 1))),
  };
}

function setDomV7PxVar(el, name, value, scale) {
  if (!el || !Number.isFinite(Number(value))) return;
  el.style.setProperty(name, `${Math.max(1, Number(value) * scale).toFixed(2)}px`);
}

function fitScaleToBox(contentW, contentH, boxW, boxH) {
  return Math.min(
    1,
    boxW > 0 ? boxW / Math.max(1, contentW) : 1,
    boxH > 0 ? boxH / Math.max(1, contentH) : 1
  );
}

function bestGridColsForBox(count, tileW, tileH, gap, boxW, boxH, fallbackCols = 6) {
  const total = Math.max(1, Math.trunc(Number(count) || 0));
  const safeTileW = Math.max(1, Number(tileW) || 1);
  const safeGap = Math.max(0, Number(gap) || 0);
  const safeBoxW = Math.max(1, Number(boxW) || 1);
  const fallback = Math.max(1, Math.min(total, Math.trunc(Number(fallbackCols) || 6)));
  const byWidth = Math.floor((safeBoxW + safeGap) / (safeTileW + safeGap));
  return Math.max(1, Math.min(total, Math.max(fallback, byWidth)));
}

function localSizeForModelBox(block, seat) {
  const bbox = block?.bbox || {};
  const vertical = Number(seat) === 1 || Number(seat) === 3;
  return vertical
    ? { w: Number(bbox.h) || 0, h: Number(bbox.w) || 0 }
    : { w: Number(bbox.w) || 0, h: Number(bbox.h) || 0 };
}

function rowUnitsWidth(units, tileW, gap) {
  const value = Math.max(0, Number(units) || 0);
  if (!value) return 0;
  return value * tileW + Math.max(0, Math.ceil(value) - 1) * gap;
}

function modelPercent(value, total) {
  const numerator = Number(value) || 0;
  const denominator = Math.max(1, Number(total) || 1);
  return `${((numerator / denominator) * 100).toFixed(4)}%`;
}

function modelSeatAngle(seat) {
  return [0, -90, 180, 90][Number(seat)] || 0;
}

function placeDomModelRect(el, bbox, table) {
  if (!el || !bbox || !table) return;
  el.classList.add("dom-v7-positioned");
  setImportantStyle(el, "position", "absolute");
  setImportantStyle(el, "inset", "auto");
  setImportantStyle(el, "left", modelPercent(bbox.x, table.width));
  setImportantStyle(el, "top", modelPercent(bbox.y, table.height));
  setImportantStyle(el, "right", "auto");
  setImportantStyle(el, "bottom", "auto");
  setImportantStyle(el, "width", modelPercent(bbox.w, table.width));
  setImportantStyle(el, "height", modelPercent(bbox.h, table.height));
  setImportantStyle(el, "transform", "none");
  setImportantStyle(el, "transform-origin", "center center");
}

function placeDomModelOrientedRect(el, bbox, table, angle) {
  if (!el || !bbox || !table) return;
  const normalized = Math.abs(Math.round(Number(angle) || 0)) % 180;
  const localW = normalized === 90 ? bbox.h : bbox.w;
  const localH = normalized === 90 ? bbox.w : bbox.h;
  const cx = bbox.x + bbox.w / 2;
  const cy = bbox.y + bbox.h / 2;
  el.classList.add("dom-v7-positioned");
  setImportantStyle(el, "position", "absolute");
  setImportantStyle(el, "inset", "auto");
  setImportantStyle(el, "left", modelPercent(cx, table.width));
  setImportantStyle(el, "top", modelPercent(cy, table.height));
  setImportantStyle(el, "right", "auto");
  setImportantStyle(el, "bottom", "auto");
  setImportantStyle(el, "width", modelPercent(localW, table.width));
  setImportantStyle(el, "height", modelPercent(localH, table.height));
  setImportantStyle(el, "transform", `translate(-50%, -50%) rotate(${Number(angle) || 0}deg)`);
  setImportantStyle(el, "transform-origin", "center center");
}

function normalizeDomInnerLayout(layout, fallbackAlign = "start") {
  const rawAlign = String(layout?.innerAlign || fallbackAlign || "start").toLowerCase();
  const innerAlign = rawAlign === "center" || rawAlign === "end" ? rawAlign : "start";
  const innerFlow = String(layout?.innerFlow || "forward").toLowerCase() === "reverse"
    ? "reverse"
    : "forward";
  return { innerAlign, innerFlow };
}

function cssMainAlign(innerAlign) {
  if (innerAlign === "center") return "center";
  if (innerAlign === "end") return "flex-end";
  return "flex-start";
}

function applyDomV7InnerLayout(el, block, fallbackAlign = "start") {
  if (!el) return;
  const layout = normalizeDomInnerLayout(block?.layout, fallbackAlign);
  el.dataset.innerAlign = layout.innerAlign;
  el.dataset.innerFlow = layout.innerFlow;
  setImportantStyle(el, "justify-content", cssMainAlign(layout.innerAlign));
  setImportantStyle(el, "align-items", "center");
  setImportantStyle(el, "flex-direction", layout.innerFlow === "reverse" ? "row-reverse" : "row");
  setImportantStyle(el, "overflow", "visible");
  setImportantStyle(el, "overflow-x", "visible");
  setImportantStyle(el, "overflow-y", "visible");
  if (el.classList?.contains("meld-row")) {
    el.querySelectorAll(".meld-set").forEach((set) => {
      setImportantStyle(set, "flex-direction", layout.innerFlow === "reverse" ? "row-reverse" : "row");
    });
  }
}

function applyDomV7GridLayout(gridEl, block, fallbackAlign = "center") {
  if (!gridEl) return;
  const layout = normalizeDomInnerLayout(block?.layout, fallbackAlign);
  gridEl.dataset.innerAlign = layout.innerAlign;
  gridEl.dataset.innerFlow = layout.innerFlow;
  const justify = layout.innerAlign === "center"
    ? "center"
    : layout.innerAlign === "end"
      ? "end"
      : "start";
  setImportantStyle(gridEl, "justify-content", justify);
  setImportantStyle(gridEl, "align-content", justify);
  setImportantStyle(gridEl, "direction", layout.innerFlow === "reverse" ? "rtl" : "ltr");
  setImportantStyle(gridEl, "overflow", "visible");
  setImportantStyle(gridEl, "overflow-x", "visible");
  setImportantStyle(gridEl, "overflow-y", "visible");
  setImportantStyle(gridEl, "position", "static");
  setImportantStyle(gridEl, "inset", "auto");
  setImportantStyle(gridEl, "left", "auto");
  setImportantStyle(gridEl, "top", "auto");
  setImportantStyle(gridEl, "right", "auto");
  setImportantStyle(gridEl, "bottom", "auto");
  setImportantStyle(gridEl, "transform", "none");
  setImportantStyle(gridEl, "transform-origin", "0 0");
  setImportantStyle(gridEl, "align-self", "flex-start");
  setImportantStyle(gridEl, "justify-self", "flex-start");
  setImportantStyle(gridEl, "margin", "0");
  setImportantStyle(gridEl, "width", "100%");
  setImportantStyle(gridEl, "height", "100%");
}

function setDomV7ScaleVars(tableEl, model) {
  if (!tableEl || !model?.config?.table) return;
  const cfg = model.config;
  setDomV7PxVar(tableEl, "--remote-tile-w", cfg.remoteHand.tileW * BATTLE_DOM_V7_REMOTE_TILE_SCALE, 1);
  setDomV7PxVar(tableEl, "--remote-tile-h", cfg.remoteHand.tileH * BATTLE_DOM_V7_REMOTE_TILE_SCALE, 1);
  setDomV7PxVar(tableEl, "--meld-tile-w", cfg.publicArea.tileW * BATTLE_DOM_V7_PUBLIC_TILE_SCALE, 1);
  setDomV7PxVar(tableEl, "--meld-tile-h", cfg.publicArea.tileH * BATTLE_DOM_V7_PUBLIC_TILE_SCALE, 1);
  setDomV7PxVar(tableEl, "--river-face-w", cfg.river.tileW * BATTLE_DOM_V7_RIVER_TILE_SCALE, 1);
  setDomV7PxVar(tableEl, "--river-face-h", cfg.river.tileH * BATTLE_DOM_V7_RIVER_TILE_SCALE, 1);
  setDomV7PxVar(tableEl, "--river-gap-x", cfg.river.gap, 1);
  setDomV7PxVar(tableEl, "--river-gap-y", cfg.river.gap, 1);
}

function setDomV7RiverVars(zone, river, model) {
  const tableEl = document.querySelector(".mahjong-table");
  if (!zone || !model?.config?.river || !tableEl) return;
  const denseScale = river?.mode === "dense" ? 0.9 : 1;
  const baseTileW = model.config.river.tileW * denseScale * BATTLE_DOM_V7_RIVER_TILE_SCALE;
  const baseTileH = model.config.river.tileH * denseScale * BATTLE_DOM_V7_RIVER_TILE_SCALE;
  const baseGap = model.config.river.gap;
  const local = localSizeForModelBox(river, river.seat);
  const visibleCount = Math.max(
    1,
    Number(zone.dataset.visibleCount)
      || Math.min(Number(river.discardCount) || 0, Number(river.visibleLimit) || 0)
      || Number(river.cols)
      || model.config.river.cols
      || 6
  );
  const cols = bestGridColsForBox(
    visibleCount,
    baseTileW,
    baseTileH,
    baseGap,
    local.w,
    local.h,
    Number(river.cols) || model.config.river.cols || 6
  );
  const rows = Math.max(1, Math.ceil(visibleCount / cols));
  const contentW = cols * baseTileW + Math.max(0, cols - 1) * baseGap;
  const contentH = rows * baseTileH + Math.max(0, rows - 1) * baseGap;
  const fitScale = fitScaleToBox(contentW, contentH, local.w, local.h);
  zone.style.setProperty("--river-cols", String(cols));
  setDomV7PxVar(zone, "--river-face-w", baseTileW * fitScale, 1);
  setDomV7PxVar(zone, "--river-face-h", baseTileH * fitScale, 1);
  setDomV7PxVar(zone, "--river-gap-x", baseGap * fitScale, 1);
  setDomV7PxVar(zone, "--river-gap-y", baseGap * fitScale, 1);
  zone.dataset.fitScale = fitScale.toFixed(4);
  zone.dataset.gridCols = String(cols);
  zone.dataset.gridRows = String(rows);
}

function setDomV7PublicVars(row, publicBlock, model, rowBlock = null) {
  const tableEl = document.querySelector(".mahjong-table");
  if (!row || !publicBlock?.metrics || !tableEl) return;
  const baseTileW = publicBlock.metrics.tileW * BATTLE_DOM_V7_PUBLIC_TILE_SCALE;
  const baseTileH = publicBlock.metrics.tileH * BATTLE_DOM_V7_PUBLIC_TILE_SCALE;
  const baseGap = publicBlock.metrics.gap;
  let contentW = rowBlock?.bbox?.w || publicBlock.metrics.width || 0;
  if (rowBlock?.type === "flowers") {
    const layout = publicBlock.metrics.flowerLayout || {};
    contentW = rowUnitsWidth(layout.rowUnits, baseTileW, baseGap);
  } else if (rowBlock?.type === "melds") {
    contentW = rowUnitsWidth(rowBlock.units, baseTileW, baseGap);
  }
  const local = rowBlock?.localBBox
    ? { w: Number(rowBlock.localBBox.w) || 0, h: Number(rowBlock.localBBox.h) || 0 }
    : localSizeForModelBox(rowBlock || publicBlock, publicBlock.seat);
  const fitScale = fitScaleToBox(contentW, baseTileH, local.w, local.h);
  setDomV7PxVar(row, "--meld-tile-w", baseTileW * fitScale, 1);
  setDomV7PxVar(row, "--meld-tile-h", baseTileH * fitScale, 1);
  setDomV7PxVar(row, "--meld-gap", baseGap * fitScale, 1);
  row.dataset.fitScale = fitScale.toFixed(4);
}

function setDomV7HandVars(row, handBlock, model) {
  if (!row || !handBlock?.metrics || !model?.config?.remoteHand) return;
  const baseTileW = Number(handBlock.metrics.tileW) || model.config.remoteHand.tileW;
  const baseTileH = Number(handBlock.metrics.tileH) || model.config.remoteHand.tileH;
  const baseStep = Number(handBlock.metrics.step) || baseTileW;
  const count = Math.max(1, Number(handBlock.tileCount) || model.config.remoteHand.maxTiles || 17);
  const contentW = baseTileW + Math.max(0, count - 1) * baseStep;
  const local = localSizeForModelBox(handBlock, handBlock.seat);
  const fitScale = fitScaleToBox(contentW, baseTileH, local.w, local.h);
  setDomV7PxVar(row, "--remote-tile-w", baseTileW * fitScale, 1);
  setDomV7PxVar(row, "--remote-tile-h", baseTileH * fitScale, 1);
  row.dataset.fitScale = fitScale.toFixed(4);
}

function applyDomV7Layout(model, options = {}) {
  const tableEl = document.querySelector(".mahjong-table");
  if (!tableEl || !model?.table) return;
  tableEl.dataset.domV7Layout = "model";
  tableEl.dataset.tableModelOk = model.ok ? "1" : "0";
  tableEl.dataset.tableModelDiagnostics = String(model.diagnostics?.length || 0);
  if (!options.keepCanvasCenter) tableEl.dataset.centerCanvas = "0";
  setDomV7ScaleVars(tableEl, model);

  const table = model.table;
  const world = $("tableWorld");
  if (world) {
    setImportantStyle(world, "inset", "auto");
    setImportantStyle(world, "left", "0");
    setImportantStyle(world, "right", "0");
    setImportantStyle(world, "top", "var(--battle-content-offset-y, 0px)");
    setImportantStyle(world, "bottom", "auto");
    setImportantStyle(world, "width", "100%");
    setImportantStyle(world, "height", "var(--battle-content-h, 100%)");
    setImportantStyle(world, "transform", "none");
    setImportantStyle(world, "transform-origin", "50% 50%");
  }

  const center = modelBlock(model, "center");
  if (center) placeDomModelRect($("tableCenterInfo"), center.bbox, table);

  for (const seat of [0, 1, 2, 3]) {
    const seatKey = seatClass(seat);
    const playerEl = document.querySelector(`.table-seat[data-seat="${seat}"]`);
    const angle = modelSeatAngle(seat);

    const river = modelBlock(model, "river", seat);
    const zone = document.querySelector(`.discard-${seatKey}`);
    if (river && zone) {
      placeDomModelOrientedRect(zone, river.bbox, table, angle);
      setImportantStyle(zone, "overflow", "visible");
      setImportantStyle(zone, "overflow-x", "visible");
      setImportantStyle(zone, "overflow-y", "visible");
      setDomV7RiverVars(zone, river, model);
      zone.dataset.modelMode = river.mode || "";
      const tiles = zone.querySelector(".discard-tiles");
      if (tiles) {
        setImportantStyle(tiles, "width", "100%");
        setImportantStyle(tiles, "height", "100%");
        applyDomV7GridLayout(tiles, river, "start");
      }
    }

    if (seat !== 0 && playerEl) {
      const hand = modelBlock(model, "hand", seat);
      const handRow = playerEl.querySelector(".seat-tile-row.concealed, .seat-tile-row.revealed-hand");
      if (hand && handRow) {
        placeDomModelOrientedRect(handRow, hand.bbox, table, angle);
        setDomV7HandVars(handRow, hand, model);
        applyDomV7InnerLayout(handRow, hand, "center");
        handRow.dataset.modelPose = hand.pose || hand.mode || "";
      }
    }

    if (playerEl) {
      const publicBlock = modelBlock(model, "public", seat);
      const flowers = modelBlock(model, "flowers", seat);
      const flowerRow = playerEl.querySelector(".flower-row");
      if (flowers && flowerRow) {
        placeDomModelOrientedRect(flowerRow, flowers.bbox, table, angle);
        setDomV7PublicVars(flowerRow, publicBlock, model, flowers);
        applyDomV7InnerLayout(flowerRow, flowers, "start");
      }

      const mainMelds = modelBlock(model, "melds", seat, (block) => block.row === "main");
      const mainRow = playerEl.querySelector(".meld-row-main");
      if (mainMelds && mainRow) {
        placeDomModelOrientedRect(mainRow, mainMelds.bbox, table, angle);
        setDomV7PublicVars(mainRow, publicBlock, model, mainMelds);
        applyDomV7InnerLayout(mainRow, mainMelds, "start");
      }

      const overflowMelds = modelBlock(model, "melds", seat, (block) => block.row === "overflow");
      const overflowRow = playerEl.querySelector(".meld-row-overflow");
      if (overflowMelds && overflowRow) {
        placeDomModelOrientedRect(overflowRow, overflowMelds.bbox, table, angle);
        setDomV7PublicVars(overflowRow, publicBlock, model, overflowMelds);
        applyDomV7InnerLayout(overflowRow, overflowMelds, "start");
      }
    }
  }
}

function applyDomV7FallbackLayout(rendererState, reason = "") {
  const table = document.querySelector(".mahjong-table");
  if (!table || !window.BattleTableModel?.createBattleTableModel) return false;
  table.dataset.renderer = "dom";
  table.dataset.tileRenderer = "dom";
  table.classList.add("dom-v7-tiles");
  table.dataset.geometry = BATTLE_TABLE_LAYOUT_MODE;
  table.dataset.centerCanvas = "0";
  if (reason) table.dataset.rendererFallback = reason;
  applyDomV7Layout(window.BattleTableModel.createBattleTableModel(rendererState));
  return true;
}

function renderTableCanvas() {
  const table = document.querySelector(".mahjong-table");
  if (!table) return;
  table.dataset.renderer = BATTLE_TABLE_RENDERER_MODE;
  table.dataset.tileRenderer = BATTLE_TABLE_RENDERER_MODE === "canvas"
    ? BATTLE_TABLE_TILE_RENDERER_MODE
    : "dom";
  table.dataset.geometry = BATTLE_TABLE_LAYOUT_MODE;
  table.classList.toggle("dom-v7-tiles", table.dataset.tileRenderer === "dom");
  const rendererState = battleTableRendererState();
  if (BATTLE_TABLE_RENDERER_MODE !== "canvas") {
    applyDomV7FallbackLayout(rendererState);
    return;
  }
  const canvas = $("tableCanvas");
  if (!canvas || !window.BattleTableRenderer || !window.BattleTableModel) {
    applyDomV7FallbackLayout(rendererState, "missing-canvas-renderer");
    return;
  }
  try {
    const useDomTiles = BATTLE_TABLE_TILE_RENDERER_MODE === "dom";
    const plan = window.BattleTableRenderer.render(canvas, rendererState, {
      tileNames,
      tileImagePaths,
      flatTable: true,
      drawTiles: !useDomTiles,
      drawCenter: false,
      supersampleDpr: 3,
      tableModelApi: window.BattleTableModel,
    });
    table.dataset.tableModelOk = plan?.ok ? "1" : "0";
    table.dataset.tableModelDiagnostics = String(plan?.diagnostics?.length || 0);
    table.dataset.centerCanvas = "0";
    table.dataset.canvasRenderMs = String(plan?.performance?.totalMs ?? "");
    table.dataset.canvasPlanMs = String(plan?.performance?.planMs ?? "");
    table.dataset.canvasDrawMs = String(plan?.performance?.drawMs ?? "");
    table.dataset.canvasFirstFrameMs = String(plan?.performance?.firstFrameMs ?? "");
    table.dataset.canvasCommandCount = String(plan?.performance?.commandCount ?? "");
    table.dataset.canvasHitBoxCount = String(plan?.performance?.hitBoxCount ?? "");
    table.dataset.canvasDrawCalls = String(plan?.performance?.canvasDrawCalls ?? "");
    applyDomV7Layout(plan?.model, { keepCanvasCenter: false });
    table.dataset.centerCanvas = "0";
  } catch (error) {
    recordBattleClientError("canvas-renderer", error);
    console.warn("battle canvas renderer failed", error);
    applyDomV7FallbackLayout(rendererState, "canvas-error");
  }
}

function meldSetHtml(meld, ownerSeat) {
  return `
    <span class="meld-set ${meld.type === "an_gang" ? "concealed-kong" : ""}" title="${meldTypeText(meld.type)} ${(meld.tiles || []).map(tileLabel).join(" ")}">
      ${meldDisplayHtml(meld, ownerSeat)}
      <span class="meld-type">${meldTypeText(meld.type)}</span>
    </span>
  `;
}

function rowCapacityStyle(count, units = count) {
  const rowCount = Math.max(1, Number(count) || 0);
  const rowUnits = Math.max(1, Number(units) || rowCount);
  return `style="--row-count:${rowCount};--row-units:${rowUnits.toFixed(2)};--row-gaps:${Math.max(0, rowCount - 1)}"`;
}

function publicMeldRows(melds, ownerSeat, density = "normal") {
  const { main, overflow, mainUnits, overflowUnits } = splitPublicMeldRows(melds, ownerSeat, {
    maxMainCount: publicMaxMainMeldCount(density),
  });
  return `
    <div class="seat-tile-row meld-row meld-row-overflow" data-row-units="${overflowUnits.toFixed(2)}" ${rowCapacityStyle(Math.ceil(overflowUnits), overflowUnits)}>${overflow.map((meld) => meldSetHtml(meld, ownerSeat)).join("")}</div>
    <div class="seat-tile-row meld-row meld-row-main" data-row-units="${mainUnits.toFixed(2)}" ${rowCapacityStyle(Math.ceil(mainUnits), mainUnits)}>${main.map((meld) => meldSetHtml(meld, ownerSeat)).join("")}</div>
  `;
}

function publicLayoutStats(player) {
  const flowers = publicFlowersFor(player);
  const melds = player.melds || [];
  const meldTotalUnits = publicMeldTotalUnits(melds, player.seat);
  const totalUnits = meldTotalUnits + flowers.length;
  const density = publicDensityFor(flowers, melds, totalUnits);
  const split = splitPublicMeldRows(melds, player.seat, {
    maxMainCount: publicMaxMainMeldCount(density),
  });
  const meldRowUnits = Math.max(split.mainUnits, split.overflowUnits);
  const maxUnits = Math.max(flowers.length, meldRowUnits);
  return {
    flowers,
    melds,
    meldUnits: meldRowUnits,
    meldTotalUnits,
    totalUnits,
    maxUnits,
    density,
  };
}

function claimedDiscardRemovals() {
  const removals = new Map();
  for (const claimer of state.players || []) {
    for (const meld of claimer.melds || []) {
      if (!["chi", "peng", "ming_gang", "bu_gang"].includes(meld.type)) continue;
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
  if (!document.body.classList.contains("discard-layout-debug")) return "";
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
  if (!box || !state?.players) return;
  const removals = claimedDiscardRemovals();
  const hist = state.history || [];
  let lastDiscardEvt = null;
  for (let i = hist.length - 1; i >= 0; i -= 1) {
    if (hist[i].event === "discard") { lastDiscardEvt = hist[i]; break; }
  }
  const lastDiscardSeat = lastDiscardEvt && Number.isInteger(Number(lastDiscardEvt.seat))
    ? Number(lastDiscardEvt.seat)
    : -1;
  box.innerHTML = state.players.map((player) => {
    const visibleDiscards = visibleDiscardsFor(player, removals);
    const visibleLimit = visibleDiscards.length > BATTLE_RIVER_NORMAL_LIMIT
      ? BATTLE_RIVER_DENSE_LIMIT
      : BATTLE_RIVER_NORMAL_LIMIT;
    const overflowCount = Math.max(0, visibleDiscards.length - visibleLimit);
    const displayDiscards = overflowCount ? visibleDiscards.slice(-visibleLimit) : visibleDiscards;
    const lastIdx = displayDiscards.length - 1;
    const isLatest = lastIdx >= 0 && player.seat === lastDiscardSeat && displayDiscards[lastIdx] === (lastDiscardEvt && lastDiscardEvt.tile);
    const isLiveLatest = isLatest && isLiveResponseDiscard(lastDiscardEvt);
    const riverDense = visibleDiscards.length > BATTLE_RIVER_NORMAL_LIMIT ? " river-dense" : "";
    const riverOverflow = overflowCount ? " river-overflow" : "";
    const riverMode = visibleDiscards.length > BATTLE_RIVER_NORMAL_LIMIT ? "dense" : "normal";
    const discards = displayDiscards.map((code, idx) =>
      tileHtml(code, "small", idx === lastIdx && isLiveLatest ? "discard-last discard-live-latest" : "")
    ).join("");
    const zoneKey = seatClass(player.seat);
    return `
      <div class="discard-zone discard-${zoneKey}${riverDense}${riverOverflow}" data-zone-key="${zoneKey}" data-river-mode="${riverMode}" data-discard-count="${visibleDiscards.length}" data-visible-count="${displayDiscards.length}" data-overflow-count="${overflowCount}" ${discardZonePositionStyle(zoneKey)}>
        <span class="discard-label">${seatWind(player)}</span>
        <div class="discard-tiles">${discards || `<span class="discard-empty">暂无弃牌</span>`}</div>
        ${overflowCount ? `<span class="discard-overflow-count">+${overflowCount}</span>` : ""}
      </div>
    `;
  }).join("");
  bindDiscardZoneDragging();
}

function winAnimationActive() {
  return state?.phase === "round_over"
    && state?.settlement?.winner !== null
    && state?.settlement?.winner !== undefined;
}

function winnerLuckScore() {
  const winnerSeat = Number(state?.settlement?.winner);
  if (!Number.isInteger(winnerSeat)) return null;
  const winner = playerBySeat(winnerSeat);
  const rows = Array.isArray(state?.settlement?.hand_luck)
    ? state.settlement.hand_luck
    : [];
  const matched = rows.find((row) => winner?.name && row?.account === winner.name)
    || rows.find((row) => Number(row?.seat) === winnerSeat)
    || rows[winnerSeat];
  const value = Number(matched?.luck_percentile);
  return Number.isFinite(value) ? value : null;
}

function usesExceptionalLuckAnimation() {
  const luck = winnerLuckScore();
  return luck !== null && luck >= 95;
}

function renderPlayers() {
  const winAnimating = winAnimationActive();
  const exceptionalLuckAnimating = winAnimating && usesExceptionalLuckAnimation();
  const panels = state.players.map((player) => {
    const active = player.seat === state.current_player && state.phase !== "round_over" ? "active" : "";
    const human = player.is_human ? "human" : "";
    const winner = state.phase === "round_over" && state.settlement?.winner === player.seat ? "winning-player" : "";
    const winActive = winner && winAnimating && !exceptionalLuckAnimating ? "win-animating" : "";
    const publicStats = publicLayoutStats(player);
    const meldRows = publicMeldRows(publicStats.melds, player.seat, publicStats.density);
    const flowers = publicStats.flowers.map((code) => tileHtml(code, "small")).join("");
    const handTiles = seatHandTiles(player);
    const opponentHandState = player.is_human
      ? ""
      : state.phase === "round_over"
        ? "opponent-hand-revealed"
        : "opponent-hand-standing";
    return `
      <article class="table-seat battle-seat-v7 ${seatClass(player.seat)} ${active} ${human} ${winner} ${winActive}" data-seat="${player.seat}" data-hand-state="${opponentHandState || "human"}" data-hand-count="${player.hand_count || 0}" data-flower-count="${publicStats.flowers.length}" data-meld-count="${publicStats.melds.length}" data-public-density="${publicStats.density}" style="--seat-public-units:${publicStats.maxUnits.toFixed(2)};--seat-meld-units:${publicStats.meldUnits.toFixed(2)};--seat-public-total-units:${publicStats.totalUnits.toFixed(2)};--seat-meld-total-units:${publicStats.meldTotalUnits.toFixed(2)};--seat-flower-count:${publicStats.flowers.length}">
        <div class="seat-surface">
          ${handTiles ? `<div class="seat-tile-row concealed revealed-hand ${opponentHandState}">${handTiles}</div>` : ""}
          <div class="seat-public-zone" data-public-density="${publicStats.density}" data-public-total-units="${publicStats.totalUnits.toFixed(2)}">
            <div class="seat-tile-row flower-row" data-row-units="${publicStats.flowers.length}" ${rowCapacityStyle(publicStats.flowers.length)}>${flowers}</div>
            <div class="seat-public-melds">
              ${meldRows}
            </div>
          </div>
        </div>
      </article>
    `;
  }).join("");
  const seatActionEffectsHtml = state.players.map(seatActionEffectAnchorHtml).join("");
  const winnerBurst = winAnimating
    ? exceptionalLuckAnimating
      ? `<div class="winner-burst winner-leizi-burst winner-${seatClass(state.settlement.winner)}" data-win-animation="exceptional-luck" aria-hidden="true"><img src="${EXCEPTIONAL_LUCK_WIN_GIF_SRC}" alt="" /></div>`
      : `<div class="winner-burst winner-${seatClass(state.settlement.winner)}" data-win-animation="normal" aria-hidden="true"><span>閼?/span></div>`
    : "";
  $("players").innerHTML = panels;
  const playerHud = $("playerHud");
  if (playerHud) {
    playerHud.innerHTML = seatActionEffectsHtml + winnerBurst;
  } else {
    $("players").insertAdjacentHTML("beforeend", seatActionEffectsHtml + winnerBurst);
  }
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

function settlementText(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function fallbackBaseDetails(player, score) {
  const rows = [];
  const flowers = publicFlowersFor(player);
  if (flowers.length) rows.push(`花牌 ${flowers.map(tileLabel).join("、")} +${flowers.length * 4} 分`);
  for (const meld of player.melds || []) {
    rows.push(`${meldTypeText(meld.type)} ${(meld.tiles || []).map(tileLabel).join("、")}`);
  }
  if (score?.plan?.length) rows.push(`胡牌计划 ${score.plan.join("、")}`);
  return rows;
}

function settlementDetailRows(player, score) {
  const baseItems = (score?.base_items || []).map((item) => detailItemText(item, "points", "分"));
  const fanItems = (score?.fan_items || []).map((item) => detailItemText(item, "fan", "番"));
  const base = baseItems.length ? baseItems : fallbackBaseDetails(player, score);
  const fan = fanItems.length ? fanItems : (score?.fan ? ["按结算番型计分"] : ["无额外番型"]);
  return { base, fan };
}

function settlementSeatLabel(seat) {
  if (seat === null || seat === undefined || Number.isNaN(Number(seat))) return "";
  return playerBySeat(Number(seat))?.label || `座位${seat}`;
}

function settlementWinBadge(settlement) {
  const winType = settlement?.win_type || state?.win_type || "胡";
  if (winType === "self_draw" || winType === "自摸") return "自摸";
  if (["rob_gang", "抢杠", "抢杠胡"].includes(winType)) return "抢杠胡";
  if (settlement?.discarder !== null && settlement?.discarder !== undefined) return "点炮胡";
  return winType;
}

function settlementWinSummary(settlement) {
  if (!settlement) return "查看结算";
  if (settlement.winner === null || settlement.winner === undefined) {
    return settlement.win_type || "流局";
  }
  const winnerLabel = settlementSeatLabel(settlement.winner);
  const badge = settlementWinBadge(settlement);
  const parts = [`${winnerLabel} ${badge}`];
  if (settlement.discarder !== null && settlement.discarder !== undefined) {
    parts.push(`放铳 ${settlementSeatLabel(settlement.discarder)}`);
  }
  if (settlement.win_tile) parts.push(`胡牌 ${tileLabel(settlement.win_tile)}`);
  return parts.join(" · ");
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
    const accountLuck = settlement.hand_luck?.find((item) => item?.account === player.name);
    const luck = accountLuck || settlement.hand_luck?.[scoreIndex];
    const luckScore = Number(luck?.luck_percentile);
    const luckText = Number.isFinite(luckScore) ? `${luckScore.toFixed(1)}` : "-";
    const deltaClass = Number(delta) >= 0 ? "score-good" : "score-bad";
    const isWinner = Number(settlement.winner) === scoreIndex;
    const isDiscarder = settlement.discarder !== null && settlement.discarder !== undefined && Number(settlement.discarder) === scoreIndex;
    const limitReason = score.limit_reason ? `<span class="settlement-limit">${settlementText(score.limit_reason)}</span>` : "";
    const winnerBadge = isWinner ? `<span class="settlement-win-badge">${settlementText(settlementWinBadge(settlement))}</span>` : "";
    const discarderBadge = isDiscarder ? `<span class="settlement-discarder-badge">閺€鍓у仏</span>` : "";
    return `
      <div class="settlement-row${isWinner ? " settlement-winner-row" : ""}${isDiscarder ? " settlement-discarder-row" : ""}">
        <div class="settlement-row-head">
          <strong>${settlementText(player.label)}${winnerBadge}${discarderBadge}</strong>
          <span>基础 ${score.base ?? "-"} · 番 ${score.fan ?? "-"} · 总分 ${score.total ?? "-"} ${limitReason}</span>
          <span class="settlement-luck">运气度 ${luckText}</span>
          <span class="${deltaClass}">${Number(delta) >= 0 ? "+" : ""}${delta}</span>
        </div>
        <div class="settlement-detail"><b>基础</b>${details.base.map((text) => `<span>${settlementText(text)}</span>`).join("")}</div>
        <div class="settlement-detail"><b>番型</b>${details.fan.map((text) => `<span>${settlementText(text)}</span>`).join("")}</div>
      </div>
    `;
  }).join("");
  const bao = settlement.bao;
  const baoBanner = bao
    ? `<div class="settlement-bao-banner">包赔：${settlementText(settlementSeatLabel(bao.seat))} · ${settlementText(bao.reason || "")}</div>`
    : "";
  popup.innerHTML = `
    <div class="settlement-popup-head">
      <strong>${settlementText(settlementWinSummary(settlement))}</strong>
      <span>筹码变化 ${settlementText(pointDeltas.join(" / ") || "")}</span>
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
    return {
      account: row.name,
      all,
      today: all,
      room: { luck_score: row.luck_score, luck_hands: row.rounds },
    };
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
    return Number.isFinite(value) ? value.toFixed(1) : "-";
  };
  const pairCell = (allStats, todayStats, key, formatter = statCell) => `${formatter(allStats, key)} / ${formatter(todayStats, key)}`;

  body.innerHTML = `
    <div class="player-stats-cards">
      ${displayRows.map((row) => {
        const allStats = row.stats?.all || emptyStats();
        const todayStats = row.stats?.today || emptyStats();
        const roomStats = row.stats?.room || { luck_score: null, luck_hands: 0 };
        return `
          <section class="player-stat-card">
            <div class="player-stat-summary">
              <div class="player-stat-player">
                <strong>${escapeXml(row.account || "-")}</strong>
                <span>${escapeXml(row.wind || "-")}</span>
              </div>
              <div class="player-stat-luck">
                <span>閺堫剚鍩ч梻纾嬬箥濮樻柨瀹?/span>
                <b>${escapeXml(luckText(roomStats))}</b>
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
              <div class="player-stat-luck-note">閹稿婀伴幋鍧楁？瀹告彃鐣幋鎰畱 ${Number(roomStats.luck_hands || 0)} 鐏炩偓閸欐牕閽╅崸鍥风幢瑜拌绨抽崗鎶芥４閹村潡妫块崥搴㈢闂嗚翰鈧?/div>
            </details>
          </section>
        `;
      }).join("")}
    </div>
    <div class="player-stats-note">閸欘亝妯夌粈鍝勭秼閸撳秶澧濈仦鈧稉顓犳畱 4 娑擃亞甯虹€硅绱辨潻鎰毜鎼达附妲搁張顒侇偧閹村潡妫挎潻鎰攽閺堢喖妫块惃鍕礋鐏炩偓楠炲啿娼庨敍灞藉従娴犳牞顕涢幆鍛瘻閳ユ粓鏆遍張?/ 娴犲﹥妫╅垾婵嗙潔缁€鎭掆偓?/div>
  `;
}

function renderActions() {
  const legal = state.legal_actions || [];
  const bar = $("actionBar");
  bar.innerHTML = "";
  if (state.phase === "round_over") {
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
    nextButton.textContent = APP_MODE === "battle" ? (ready ? "已准备" : "准备") : "新一局";
    nextButton.addEventListener("click", () => newRound(false));
    bar.appendChild(nextButton);
    return;
  }
  if (!legal.length) {
    if (state.pending?.deferred) return;
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
    span.textContent = "请选择要出的牌";
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
  if (transientActionNotice) {
    bar.innerHTML = `<span class="tag action-feedback">${escapeXml(transientActionNotice)}</span>`;
    return;
  }
  if (pendingActionFeedback) {
    bar.innerHTML = `<span class="tag action-feedback">${escapeXml(pendingActionFeedback.message)}</span>`;
    return;
  }
  if (state.phase === "round_over") {
    if (state.settlement) {
      const button = document.createElement("button");
      button.className = settlementHidden() ? "settlement-toggle" : "settlement-toggle gold";
      button.textContent = "结算";
      button.title = settlementWinSummary(state.settlement);
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
    const span = document.createElement("span");
    span.className = "tag";
    span.textContent = "双击出牌";
    bar.appendChild(span);
  }
}

function fitActiveHand(count, options = {}) {
  const table = document.querySelector(".mahjong-table");
  if (!table || !count) return;
  const handRow = $("hand");
  const tableLogicalWidth = Number(table.clientWidth) || BATTLE_MOBILE_LOGICAL_WIDTH;
  const frameInset = 8;
  const handFrameWidth = Math.max(1, tableLogicalWidth - frameInset * 2);
  const maxHandTiles = 17;
  const fixedTileGap = 2;
  const drawGapRatio = 0.15;
  const fixedTileW = Math.max(
    1,
    (handFrameWidth - ((maxHandTiles - 2) * fixedTileGap))
      / (maxHandTiles + drawGapRatio)
  );
  const hasNewDraw = options.hasNewDraw ?? Boolean($("hand")?.querySelector(".new-draw"));
  const drawGap = hasNewDraw ? Math.round(fixedTileW * drawGapRatio) : 0;
  const contentWidth = handFrameWidth;
  const leftReserve = 0;
  const rightReserve = 0;
  table.style.setProperty("--active-hand-safe-width", `${contentWidth.toFixed(2)}px`);
  table.style.setProperty("--active-left-public-w", `${leftReserve.toFixed(2)}px`);
  table.style.setProperty("--active-right-public-w", `${rightReserve.toFixed(2)}px`);
  table.style.setProperty("--active-tile-w", `${fixedTileW.toFixed(2)}px`);
  table.style.setProperty("--active-tile-h", `${(fixedTileW * 1.40625).toFixed(2)}px`);
  table.style.setProperty("--active-tile-gap", `${fixedTileGap.toFixed(2)}px`);
  table.style.setProperty("--active-draw-gap", `${drawGap.toFixed(2)}px`);
  table.dataset.activeHandSizing = "fixed-17-frame";
  if (handRow) {
    setImportantStyle(handRow, "justify-content", "center");
    setImportantStyle(handRow, "overflow-x", "visible");
    setImportantStyle(handRow, "overflow-y", "visible");
  }
}

function renderHandV2() {
  const human = humanPlayer();
  if (!human || !human.hand || !Object.keys(human.hand).length) {
    const hand = $("hand");
    if (hand) hand.innerHTML = "";
    selectedDiscardTile = null;
    selectedDiscardKey = null;
    updateSelectedTileHighlights();
    renderActionsV2();
    return;
  }
  const canDiscardNow = !busy && !pendingActionFeedback && !state.pending && state.phase === "turn" && state.current_player === human.seat;
  const legalDiscards = legalDiscardTiles();
  syncSelectedDiscardTile();
  const { tiles, drawnTile } = displayedHandTiles(human);
  fitActiveHand(tiles.length, { human, hasNewDraw: Boolean(drawnTile) });
  const validSelectionKeys = new Set(tiles.map((code, index) => `${code}:${index}`));
  if (selectedDiscardKey && !validSelectionKeys.has(selectedDiscardKey)) {
    const replacementIndex = tiles.findIndex((code) => code === selectedDiscardTile);
    if (replacementIndex >= 0 && legalDiscards.has(selectedDiscardTile)) {
      selectedDiscardKey = `${selectedDiscardTile}:${replacementIndex}`;
    } else {
      selectedDiscardKey = null;
      selectedDiscardTile = null;
    }
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
      const tile = el.dataset.tile;
      const same = selectedDiscardTile === tile;
      if (same) {
        sendAction({ type: "discard", tile });
        return;
      }
      selectedDiscardTile = tile;
      selectedDiscardKey = key;
      renderActionsV2();
      renderHandV2();
      updateSelectedTileHighlights();
    });
  });
  updateSelectedTileHighlights();
}

function renderAnalysis() {
  const box = $("analysis");
  if (!box) return;
  const settlement = state.settlement;
  const pointDeltas = settlement?.point_deltas || settlement?.deltas || [];
  const header = settlement ? `
    <div class="analysis-item">
      <div><strong>${escapeXml(settlement.win_type || "结算")}</strong>${settlement.reason ? ` · ${escapeXml(settlement.reason)}` : ""}</div>
      <div>筹码变化：${escapeXml(pointDeltas.join(" / ") || "")}</div>
    </div>
  ` : "";
  const rows = (state.analysis || []).slice().reverse().map((item) => {
    const cls = item.bad ? "score-bad" : "score-good";
    return `
      <div class="analysis-item">
        <div class="${cls}">${escapeXml(item.score)} 分 · ${escapeXml(item.chosen)}</div>
        <div>模型首选：${escapeXml(item.best || "无")}，${escapeXml(item.best_score ?? "-")}</div>
        <div>${escapeXml(item.reason || "")}</div>
        <div>${escapeXml(item.suggestion || "")}</div>
      </div>
    `;
  }).join("");
  box.innerHTML = header + (rows || `<div class="analysis-item">暂无决策记录。</div>`);
}
function render() {
  if (activeView === "game" && renderBattleLobbyOnly()) return;
  renderBattleShell();
  renderStatus();
  renderPendingCountdown();
  renderBattleFocus();
  renderPlayers();
  renderTableCanvas();
  renderActionsV2();
  renderHandV2();
  renderHistory();
  renderAnalysis();
  renderSettlementPopup();
  renderPlayerStatsModal();
  updateSelectedTileHighlights();
  updateBattleToolbarControls();
}

async function refresh() {
  const path = APP_MODE === "battle" || activeView === "game"
    ? battleApiPath("state")
    : "/api/state";
  if (setGameState(await api(path), { announce: false, force: true })) render();
}

async function stepGame() {
  if (steppingGame) return;
  steppingGame = true;
  try {
    const path = APP_MODE === "battle" || activeView === "game"
      ? battleApiPath("state")
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
    if (setGameState(await api(battleApiPath("state")), { announce: false })) render();
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
    const result = await api(`${battleApiPath("wait")}${battleWaitQuery(since)}`);
    if (setGameState(result, { announce: true })) render();
  } catch (error) {
    console.warn("battle wait failed", error);
    await delay(300);
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
      await delay(180);
    }
  }
}

async function sendBattleHeartbeat() {
  const account = battleAccountValue();
  if (!account || !Number.isInteger(Number(state?.room_generation))) return;
  try {
    await post(battleApiPath("heartbeat"), { account });
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
  try {
    const path = APP_MODE === "battle" || activeView === "game" ? battleApiPath("action") : "/api/action";
    const battlePath = path.includes("/battle/");
    let lastError = null;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      if (battlePath && attempt > 0) {
        try {
          await refresh();
        } catch (refreshError) {
          console.warn("battle stale refresh failed", refreshError);
        }
      }
      const currentAction = battlePath ? currentLegalActionForIntent(action) : action;
      if (!currentAction) {
        pendingActionFeedback = null;
        showTransientActionNotice("牌局已更新，请按当前画面重新选择动作");
        return;
      }
      pendingActionFeedback = {
        action: currentAction,
        room_generation: state?.room_generation,
        pending_id: state?.pending_id,
        action_token: state?.action_token || null,
        message: `已提交 ${actionFeedbackLabel(currentAction)}，等待服务器确认`,
      };
      renderActionsV2();
      renderHandV2();
      try {
        const payload = battlePath
          ? {
              account: battleAccountValue(),
              action: currentAction,
              action_token: state?.action_token || null,
              room_generation: state?.room_generation ?? null,
              pending_id: state?.pending_id ?? null,
            }
          : { action: currentAction };
        const next = await post(path, payload);
        pendingActionFeedback = null;
        setGameState(next);
        render();
        return;
      } catch (error) {
        lastError = error;
        pendingActionFeedback = null;
        if (!battlePath || !isStaleBattleActionError(error) || attempt > 0) {
          throw error;
        }
        console.warn("battle action stale; refreshing and retrying current action", error);
      }
    }
    if (lastError) throw lastError;
  } catch (error) {
    pendingActionFeedback = null;
    if (isStaleBattleActionError(error)) {
      showTransientActionNotice("牌局已更新，请按当前画面重新选择动作");
      try {
        await refresh();
      } catch (refreshError) {
        console.warn("battle stale refresh failed", refreshError);
      }
    } else {
      renderActionsV2();
      renderHandV2();
      alert(error.message);
    }
  } finally {
    busy = false;
    setBusy(false);
    renderActionsV2();
    renderHandV2();
    updateBattleToolbarControls();
  }
}

async function loginBattleAccount(account) {
  redirectToBattleLobby("请先在大厅登录并进入房间。");
}

async function sitBattleSeat(seat) {
  if (!battleAccountValue()) {
    alert("请先登录账号");
    return;
  }
  try {
    setGameState(await post(battleApiPath("sit"), { account: battleAccountValue(), seat }), { announce: false });
    render();
  } catch (error) {
    alert(error.message);
  }
}

async function leaveBattleSeat() {
  if (!battleAccountValue()) return;
  try {
    setGameState(await post(battleApiPath("leave"), { account: battleAccountValue() }), { announce: false });
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
  renderOwnerRoomControls();
  renderRoomDiagnostics();
  if (roomMenuOpen) {
    refreshBattleRoomSummary()
      .then(() => renderOwnerRoomControls())
      .catch((error) => console.warn("room summary refresh failed", error));
  }
}

function toggleRoomMenu() {
  setRoomMenuOpen(!roomMenuOpen);
}

async function exitBattleRoom() {
  const account = battleAccountValue();
  setRoomMenuOpen(false);
  if (account) {
    try {
      await post(battleApiPath("leave"), { account });
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
  const navigationEntries = typeof performance !== "undefined" && performance.getEntriesByType
    ? performance.getEntriesByType("navigation").slice(-1).map((entry) => ({
        type: entry.type,
        duration: Math.round(entry.duration || 0),
        dom_complete: Math.round(entry.domComplete || 0),
        load_event_end: Math.round(entry.loadEventEnd || 0),
        transfer_size: Math.round(entry.transferSize || 0),
      }))
    : [];
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
    performance: {
      now: typeof performance !== "undefined" ? Math.round(performance.now()) : null,
      navigation: navigationEntries,
      memory: (typeof performance !== "undefined" && performance.memory) ? {
        js_heap_size_limit: performance.memory.jsHeapSizeLimit,
        total_js_heap_size: performance.memory.totalJSHeapSize,
        used_js_heap_size: performance.memory.usedJSHeapSize,
      } : null,
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
    recent_api_timings: recentBattleApiTimings.slice(-60),
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
      $("bugReportRoundMeta").textContent = `第 ${state?.round_no ?? "-"} 局 · ${roundState}`;
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
  if (status) status.textContent = "正在保存完整牌局信息...";
  if (modalStatus) modalStatus.textContent = "正在保存完整牌局信息...";
  try {
    const result = await post(battleApiPath("report-bug"), {
      account: battleAccountValue(),
      note,
      client_context: bugReportClientContext(),
    });
    const reportPath = result.export_path || result.file_path || result.file_name || "";
    const savedText = `已保存，编号 ${result.report_id}${reportPath ? `，文件 ${reportPath}` : ""}`;
    if (status) status.textContent = savedText;
    if (modalStatus) modalStatus.textContent = savedText;
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
    const aiPolicy = saveBattleAiPolicy();
    setGameState(await post(battleApiPath("ready"), { account: battleAccountValue(), ai_policy: aiPolicy }), { announce: false });
    render();
  } catch (error) {
    alert(error.message);
  }
}

function isBattleRoomOwner() {
  const metadata = battleRoomMetadata();
  return Boolean(battleAccountValue() && metadata.owner_account && metadata.owner_account === battleAccountValue());
}

function isBattleActivePlay() {
  return Boolean(state?.game_started && state?.phase !== "round_over");
}

function setOwnerRoomMessage(message, bad = false) {
  const box = $("ownerRoomMessage");
  if (!box) return;
  box.textContent = message || "";
  box.classList.toggle("bad", Boolean(bad));
}

function ownerKickTargets() {
  const metadata = battleRoomMetadata();
  const owner = metadata.owner_account;
  return (metadata.seats || [])
    .map((seat) => ({
      account: String(seat?.account || "").trim(),
      label: `${seatName(Number(seat?.seat ?? seat?.absolute_seat ?? 0))} · ${seat?.account || ""}`,
      isAi: Boolean(seat?.is_ai),
    }))
    .filter((seat) => seat.account && seat.account !== owner && !seat.isAi);
}

function renderOwnerRoomControls() {
  const controls = $("ownerRoomControls");
  if (!controls) return;
  const owner = isBattleRoomOwner();
  controls.hidden = !owner;
  if (!owner) return;
  const metadata = battleRoomMetadata();
  const activePlay = isBattleActivePlay();
  const settingsBlock = $("ownerRoomSettingsBlock");
  const kickBlock = $("ownerRoomKickBlock");
  const aiSelect = $("ownerAiPolicySelect");
  const applyButton = $("ownerApplySettingsBtn");
  const kickSelect = $("ownerKickTargetSelect");
  const kickButton = $("ownerKickBtn");
  const closeButton = $("ownerCloseRoomBtn");
  if (settingsBlock) settingsBlock.hidden = activePlay;
  if (kickBlock) kickBlock.hidden = activePlay;
  if (aiSelect) aiSelect.value = normalizeBattleAiPolicy(metadata.ai_policy);
  if (applyButton) {
    applyButton.disabled = busy || activePlay;
    applyButton.title = activePlay ? "对局进行中不能修改 AI 设置" : "应用房间 AI 设置";
  }
  const targets = ownerKickTargets();
  if (kickSelect) {
    kickSelect.innerHTML = targets.length
      ? targets.map((target) => `<option value="${escapeAttr(target.account)}">${escapeXml(target.label)}</option>`).join("")
      : '<option value="">暂无可踢出的玩家</option>';
  }
  if (kickButton) {
    kickButton.disabled = busy || activePlay || !targets.length;
    kickButton.title = activePlay ? "对局进行中不能踢人" : "";
  }
  if (closeButton) {
    closeButton.disabled = busy;
    closeButton.title = "关闭整个房间";
  }
}

async function ownerApplyRoomSettings() {
  if (!isBattleRoomOwner() || isBattleActivePlay() || busy) return;
  const roomId = battleRoomIdValue();
  const aiPolicy = normalizeBattleAiPolicy($("ownerAiPolicySelect")?.value || DEFAULT_BATTLE_AI_POLICY);
  busy = true;
  setBusy(true);
  setOwnerRoomMessage("正在应用设置...");
  try {
    const summary = await post(`/api/lobby/rooms/${encodeURIComponent(roomId)}/settings`, { ai_policy: aiPolicy });
    saveBattleRoomSummary(summary);
    await refreshBattleRoomSummary();
    await refreshBattleState();
    setOwnerRoomMessage("AI 设置已更新。");
  } catch (error) {
    setOwnerRoomMessage(error.message, true);
  } finally {
    busy = false;
    setBusy(false);
    renderOwnerRoomControls();
  }
}

async function ownerKickRoomPlayer() {
  if (!isBattleRoomOwner() || isBattleActivePlay() || busy) return;
  const target = $("ownerKickTargetSelect")?.value || "";
  if (!target) return;
  if (!window.confirm(`确认将 ${target} 踢出房间？`)) return;
  const roomId = battleRoomIdValue();
  busy = true;
  setBusy(true);
  setOwnerRoomMessage("正在踢出玩家...");
  try {
    const result = await post(`/api/lobby/rooms/${encodeURIComponent(roomId)}/kick`, {
      target,
      room_generation: state?.room_generation,
    });
    setGameState(result, { announce: false });
    await refreshBattleRoomSummary();
    await refreshBattleState();
    render();
    setOwnerRoomMessage(`${target} 已离开房间。`);
  } catch (error) {
    setOwnerRoomMessage(error.message, true);
  } finally {
    busy = false;
    setBusy(false);
    renderOwnerRoomControls();
  }
}

async function ownerCloseBattleRoom() {
  if (!isBattleRoomOwner() || busy) return;
  if (!window.confirm("确认关闭整个房间？")) return;
  if (!window.confirm("关闭后本局作废，所有玩家会回到大厅。继续关闭？")) return;
  const roomId = battleRoomIdValue();
  busy = true;
  setBusy(true);
  setOwnerRoomMessage("正在关闭房间...");
  try {
    await post(`/api/lobby/rooms/${encodeURIComponent(roomId)}/close`, { confirm: "CLOSE_ROOM" });
    try {
      localStorage.removeItem(BATTLE_ROOM_STORAGE_KEY);
      localStorage.removeItem(BATTLE_ROOM_SUMMARY_STORAGE_KEY);
    } catch {
      // Local storage can be unavailable in hardened browser profiles.
    }
    redirectToBattleLobby("房间已关闭。");
  } catch (error) {
    setOwnerRoomMessage(error.message, true);
  } finally {
    busy = false;
    setBusy(false);
    renderOwnerRoomControls();
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
  renderOwnerRoomControls();
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
    bugReportButton.disabled = busy || !state?.game_started;
    bugReportButton.title = bugReportButton.disabled ? "当前没有可举报的牌局" : "保存当前牌局的诊断信息";
  }
  if (resetButton) {
    resetButton.hidden = false;
    resetButton.textContent = "重新换座";
    resetButton.disabled = busy || state?.phase !== "round_over";
    resetButton.title = resetButton.disabled ? "本局结算后才能重新换座" : "随机重排所有玩家座位";
  }
  renderOwnerRoomControls();
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

async function newRound() {
  if (busy) return;
  setRoomMenuOpen(false);
  busy = true;
  setBusy(true);
  try {
    const aiPolicy = saveBattleAiPolicy();
    setGameState(await post(battleApiPath("ready"), { account: battleAccountValue(), ai_policy: aiPolicy }), { announce: false });
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

async function reseatPlayers() {
  if (busy || state?.phase !== "round_over") return;
  setRoomMenuOpen(false);
  busy = true;
  setBusy(true);
  try {
    setGameState(await post(battleApiPath("reset"), {}), { announce: false });
    render();
  } catch (error) {
    alert(error.message);
  } finally {
    busy = false;
    setBusy(false);
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
  if ($("resetMatchBtn")) $("resetMatchBtn").textContent = "重新换座";
  updateBattleToolbarControls();
  if ($("trainingView")) $("trainingView").classList.remove("active");
  if ($("gameView")) $("gameView").classList.add("active");
  if ($("roundMeta")) $("roundMeta").textContent = "在线房间";
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
    const desktopW = Math.max(1, Math.round(rawW));
    const desktopH = Math.max(1, Math.round(rawH));
    const desktopInset = 16;
    const availableW = Math.max(1, desktopW - desktopInset * 2);
    const availableH = Math.max(1, desktopH - desktopInset * 2);
    const widthScale = Math.max(0.1, availableW / BATTLE_MOBILE_LOGICAL_WIDTH);
    const heightFitScale = Math.max(0.1, availableH / BATTLE_TABLE_BASE_HEIGHT);
    const desktopScale = Math.min(widthScale, heightFitScale);
    const desktopLogicalHeight = Math.max(
      BATTLE_TABLE_BASE_HEIGHT,
      Math.round((availableH / desktopScale) * 100) / 100
    );
    document.body.classList.add("battle-desktop-table");
    document.body.classList.remove("battle-mobile-portrait");
    document.documentElement.style.setProperty("--battle-desktop-scale", desktopScale.toFixed(4));
    document.documentElement.style.setProperty("--battle-desktop-table-w", `${BATTLE_MOBILE_LOGICAL_WIDTH}px`);
    document.documentElement.style.setProperty("--battle-desktop-table-h", `${desktopLogicalHeight}px`);
    document.documentElement.style.setProperty("--battle-desktop-content-h", `${BATTLE_TABLE_BASE_HEIGHT}px`);
    document.documentElement.style.setProperty("--battle-desktop-available-w", `${availableW}px`);
    document.documentElement.style.setProperty("--battle-desktop-available-h", `${availableH}px`);
    document.documentElement.style.setProperty("--battle-desktop-vw", `${desktopW}px`);
    document.documentElement.style.setProperty("--battle-desktop-vh", `${desktopH}px`);
    document.documentElement.style.removeProperty("--battle-mobile-scale");
    document.documentElement.style.removeProperty("--battle-mobile-table-w");
    document.documentElement.style.removeProperty("--battle-mobile-table-h");
    document.documentElement.style.removeProperty("--battle-mobile-content-h");
    document.documentElement.style.removeProperty("--battle-mobile-vw");
    document.documentElement.style.removeProperty("--battle-mobile-vh");
    document.documentElement.style.removeProperty("--battle-mobile-shell-w");
    document.documentElement.style.removeProperty("--battle-mobile-shell-h");
    fitActiveHand(document.querySelectorAll("#hand .tile").length);
    renderTableCanvas();
    return;
  }
  document.body.classList.remove("battle-desktop-table");
  document.documentElement.style.removeProperty("--battle-desktop-scale");
  document.documentElement.style.removeProperty("--battle-desktop-table-w");
  document.documentElement.style.removeProperty("--battle-desktop-table-h");
  document.documentElement.style.removeProperty("--battle-desktop-content-h");
  document.documentElement.style.removeProperty("--battle-desktop-available-w");
  document.documentElement.style.removeProperty("--battle-desktop-available-h");
  document.documentElement.style.removeProperty("--battle-desktop-vw");
  document.documentElement.style.removeProperty("--battle-desktop-vh");

  const visualW = Math.max(1, Math.round(rawW));
  const visualH = Math.max(1, Math.round(rawH));
  const portrait = visualH > visualW;
  document.body.classList.toggle("battle-mobile-portrait", portrait);
  const viewportW = portrait ? visualH : visualW;
  const viewportH = portrait ? visualW : visualH;
  const widthScale = Math.max(0.1, viewportW / BATTLE_MOBILE_LOGICAL_WIDTH);
  const heightFitScale = Math.max(0.1, viewportH / BATTLE_TABLE_BASE_HEIGHT);
  const scale = Math.min(widthScale, heightFitScale);
  const logicalH = Math.max(
    BATTLE_TABLE_BASE_HEIGHT,
    Math.round((viewportH / scale) * 100) / 100
  );
  document.documentElement.style.setProperty("--battle-mobile-scale", Math.max(0.1, scale).toFixed(4));
  document.documentElement.style.setProperty("--battle-mobile-table-w", `${BATTLE_MOBILE_LOGICAL_WIDTH}px`);
  document.documentElement.style.setProperty("--battle-mobile-table-h", `${logicalH}px`);
  document.documentElement.style.setProperty("--battle-mobile-content-h", `${BATTLE_TABLE_BASE_HEIGHT}px`);
  document.documentElement.style.setProperty("--battle-mobile-vw", `${visualW}px`);
  document.documentElement.style.setProperty("--battle-mobile-vh", `${visualH}px`);
  document.documentElement.style.setProperty("--battle-mobile-shell-w", `${viewportW}px`);
  document.documentElement.style.setProperty("--battle-mobile-shell-h", `${viewportH}px`);
  fitActiveHand(document.querySelectorAll("#hand .tile").length);
  renderTableCanvas();
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
  loadBattleRoomSummary();
  if (!battleTokenValue()) {
    window.location.href = "/battle-login";
    return;
  }
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
  if ($("ownerApplySettingsBtn")) $("ownerApplySettingsBtn").addEventListener("click", ownerApplyRoomSettings);
  if ($("ownerKickBtn")) $("ownerKickBtn").addEventListener("click", ownerKickRoomPlayer);
  if ($("ownerCloseRoomBtn")) $("ownerCloseRoomBtn").addEventListener("click", ownerCloseBattleRoom);
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
  if ($("newRoundBtn")) $("newRoundBtn").addEventListener("click", newRound);
  if ($("resetMatchBtn")) $("resetMatchBtn").addEventListener("click", reseatPlayers);
  await refreshBattleRoomSummary().catch((error) => console.warn("room summary refresh failed", error));
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
