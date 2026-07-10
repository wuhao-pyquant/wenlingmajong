const ACCOUNT_KEY = "wenling.online.account.v1";
const TOKEN_KEY = "wenling.online.token.v1";
const ROLE_KEY = "wenling.online.role.v1";
const ROOM_KEY = "wenling.online.room_id.v1";
const ROOM_SUMMARY_KEY = "wenling.online.room_summary.v1";
const PHOTON_TRANSITION_KEY = "wenling.photon.auth_to_lobby.v1";

const $ = (id) => document.getElementById(id);
const isAuthPage = Boolean($("loginBtn") || $("registerBtn"));
const isLobbyPage = Boolean($("roomTableGrid"));
let roomRefreshTimer = null;
let loadingRooms = false;
let lastRooms = [];
let lastMaxRooms = 3;
let authSubmissionPending = false;
let authNavigationStarted = false;

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

function setAuthMode(mode, { focus = false } = {}) {
  const selectedMode = mode === "register" ? "register" : "login";
  const registerMode = selectedMode === "register";
  const loginPanel = $("loginAuthPanel");
  const registerPanel = $("registerAuthPanel");
  if (loginPanel) loginPanel.hidden = registerMode;
  if (registerPanel) registerPanel.hidden = !registerMode;
  document.querySelectorAll("[data-auth-mode]").forEach((button) => {
    const selected = button.dataset.authMode === selectedMode;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
    if (focus && selected) button.focus();
  });
  document.body.dataset.authMode = selectedMode;
}

function handleAuthTabKeydown(event, button) {
  const tabs = Array.from(document.querySelectorAll("[data-auth-mode]"));
  const currentIndex = tabs.indexOf(button);
  if (currentIndex < 0) return;
  let nextIndex = null;
  if (event.key === "ArrowLeft") nextIndex = (currentIndex + tabs.length - 1) % tabs.length;
  if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % tabs.length;
  if (event.key === "Home") nextIndex = 0;
  if (event.key === "End") nextIndex = tabs.length - 1;
  if (nextIndex === null) return;
  event.preventDefault();
  setAuthMode(tabs[nextIndex].dataset.authMode || "login", { focus: true });
}

function wait(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function navigateToLobby({ animate = true } = {}) {
  if (authNavigationStarted) return;
  authNavigationStarted = true;
  try {
    sessionStorage.setItem(PHOTON_TRANSITION_KEY, "1");
  } catch {
    // sessionStorage can be unavailable in hardened browser profiles.
  }
  if (animate) {
    await Promise.race([photonBridgeCall("playAuthSuccess"), wait(700)]);
  }
  void photonBridgeCall("destroy");
  window.location.href = "/battle-lobby";
}

function photonBridgeCall(method, ...args) {
  try {
    return Promise.resolve(window.WenlingPhotonScene?.[method]?.(...args)).catch(() => undefined);
  } catch {
    return Promise.resolve(undefined);
  }
}

function setAuthPending(button, pending) {
  if (!button) return;
  button.disabled = pending;
  button.dataset.pending = String(pending);
  button.setAttribute("aria-busy", String(pending));
  button.classList.toggle("pending", pending);
}

function beginAuthSubmission(button) {
  if (authSubmissionPending || authNavigationStarted) return false;
  authSubmissionPending = true;
  setAuthPending(button, true);
  return true;
}

function finishAuthSubmission(button) {
  if (authNavigationStarted) return;
  authSubmissionPending = false;
  setAuthPending(button, false);
}

function tokenValue() {
  try {
    return localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

function accountValue() {
  try {
    return localStorage.getItem(ACCOUNT_KEY) || "";
  } catch {
    return "";
  }
}

function roleValue() {
  try {
    return localStorage.getItem(ROLE_KEY) || "player";
  } catch {
    return "player";
  }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[ch]));
}

async function readApiResponse(response) {
  const raw = await response.text();
  let data = {};
  if (raw) {
    try {
      data = JSON.parse(raw);
    } catch {
      data = { error: raw };
    }
  }
  if (response.status === 401) clearSession();
  if (!response.ok || data.error || data.detail) {
    const detail = data.error || data.detail || response.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

async function api(path, options = {}) {
  const token = tokenValue();
  const response = await fetch(path, {
    cache: "no-store",
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });
  return readApiResponse(response);
}

async function post(path, body = {}) {
  return api(path, { method: "POST", body: JSON.stringify(body) });
}

function setSession(payload) {
  const account = payload.account || payload.account_name || "";
  const role = payload.role || "player";
  try {
    localStorage.setItem(ACCOUNT_KEY, account);
    localStorage.setItem(ROLE_KEY, role);
    localStorage.setItem(TOKEN_KEY, payload.session_token || "");
  } catch {
    // localStorage can be unavailable in hardened browser profiles.
  }
}

function clearSession() {
  try {
    localStorage.removeItem(ACCOUNT_KEY);
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(ROLE_KEY);
    localStorage.removeItem(ROOM_KEY);
    localStorage.removeItem(ROOM_SUMMARY_KEY);
  } catch {
    // localStorage can be unavailable in hardened browser profiles.
  }
}

function setMessage(text, bad = false) {
  const box = $("lobbyMessage");
  if (box) {
    box.textContent = text || "";
    box.classList.toggle("bad", Boolean(bad));
  }
  const statusTitle = $("authStatusTitle");
  const statusDetail = $("authStatusDetail");
  if (statusTitle && text) {
    statusTitle.textContent = bad ? "操作失败" : "状态更新";
    statusDetail.textContent = text;
  }
}

function setAuthStatus(title, detail, bad = false) {
  const statusTitle = $("authStatusTitle");
  const statusDetail = $("authStatusDetail");
  if (statusTitle) statusTitle.textContent = title;
  if (statusDetail) statusDetail.textContent = detail;
  const statusCard = document.querySelector(".auth-status-card, .photon-auth-status");
  if (statusCard) statusCard.classList.toggle("bad", Boolean(bad));
  void photonBridgeCall("setStatus", bad ? "error" : title.includes("成功") ? "success" : "loading");
}

function readNoticeFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const notice = params.get("notice");
  if (notice) {
    setMessage(notice);
    setAuthStatus("需要登录", notice);
  }
}

function updateSessionUi() {
  const account = accountValue();
  const role = roleValue();
  if ($("currentAccountLabel")) $("currentAccountLabel").textContent = account || "未登录";
  if ($("currentRoleLabel")) $("currentRoleLabel").textContent = account ? (role === "admin" ? "管理员" : "玩家") : "";
  if ($("logoutBtn")) $("logoutBtn").disabled = !tokenValue();
  const adminEntry = $("adminEntry");
  if (adminEntry) adminEntry.hidden = role !== "admin" || !tokenValue();
}

async function login() {
  const button = $("loginBtn");
  if (!beginAuthSubmission(button)) return;
  try {
    setAuthStatus("正在登录", "正在验证账号密码。");
    const payload = await post("/api/auth/login", {
      account: $("loginAccountInput").value.trim(),
      password: $("loginPasswordInput").value,
    });
    setSession(payload);
    setAuthStatus("登录成功", "正在进入选桌大厅。");
    await navigateToLobby();
  } catch (error) {
    setAuthStatus("登录失败", error.message, true);
    setMessage(error.message, true);
  } finally {
    finishAuthSubmission(button);
  }
}

async function register() {
  const button = $("registerBtn");
  if (!beginAuthSubmission(button)) return;
  try {
    setAuthStatus("正在注册", "正在验证邀请码并创建账号。");
    const payload = await post("/api/auth/register", {
      account: $("registerAccountInput").value.trim(),
      password: $("registerPasswordInput").value,
      invite_code: $("inviteCodeInput").value.trim().toUpperCase(),
    });
    setSession(payload);
    setAuthStatus("注册成功", "账号已登录，正在进入选桌大厅。");
    await navigateToLobby();
  } catch (error) {
    setAuthStatus("注册失败", error.message, true);
    setMessage(error.message, true);
  } finally {
    finishAuthSubmission(button);
  }
}

function roomStatusValue(room) {
  return String(room?.status || room?.room_status || "").trim().toLowerCase();
}

function roomStatusLabel(status) {
  const key = String(status || "").toLowerCase();
  if (key === "open" || key === "waiting") return "等待中";
  if (key === "playing") return "对局中";
  if (key === "round_over") return "结算中";
  if (key === "closing") return "关闭中";
  if (key === "closed") return "已关闭";
  return status || "未知";
}

function normalizeRoomSummary(room) {
  return {
    room_id: room?.room_id || "",
    room_name: room?.room_name || "",
    owner_account: room?.owner_account || "",
    ai_policy: room?.ai_policy || "low",
    status: room?.status || room?.room_status || "",
    room_generation: room?.room_generation ?? null,
    room_revision: room?.room_revision ?? null,
    game_started: Boolean(room?.game_started),
    seats: Array.isArray(room?.seats) ? room.seats : [],
    ready_accounts: Array.isArray(room?.ready_accounts) ? [...room.ready_accounts].sort() : [],
  };
}

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

function saveRoomSummary(room) {
  if (!room?.room_id) return;
  try {
    localStorage.setItem(ROOM_SUMMARY_KEY, JSON.stringify(normalizeRoomSummary(room)));
  } catch {
    // localStorage can be unavailable in hardened browser profiles.
  }
}

function saveRoomId(roomId) {
  try {
    localStorage.setItem(ROOM_KEY, roomId || "");
  } catch {
    // localStorage can be unavailable in hardened browser profiles.
  }
}

function accountSeat(room, account = accountValue()) {
  return (room?.seats || []).find((seat) => seat?.account === account) || null;
}

function firstEmptySeat(room) {
  return (room?.seats || []).find((seat) => !seat?.account) || null;
}

function roomForSlot(index) {
  return lastRooms[index] || null;
}

async function loadRooms() {
  updateSessionUi();
  if (!tokenValue()) {
    window.location.href = "/battle-login?notice=" + encodeURIComponent("请先登录账号。");
    return;
  }
  if (loadingRooms) return;
  loadingRooms = true;
  try {
    const payload = await api("/api/lobby/rooms");
    renderTableSlots(payload.rooms || [], payload.max_rooms || 3);
  } catch (error) {
    setMessage(error.message, true);
    if (String(error.message || "").toLowerCase().includes("login")) {
      window.location.href = "/battle-login?notice=" + encodeURIComponent("登录已失效，请重新登录。");
    }
  } finally {
    loadingRooms = false;
    updateSessionUi();
  }
}

function renderSeatDots(room) {
  const seats = Array.isArray(room?.seats) ? room.seats : [];
  const labels = ["东", "南", "西", "北"];
  return labels.map((label, index) => {
    const seat = seats[index] || {};
    const account = seat.account || "";
    const ready = Boolean(seat.ready || (room?.ready_accounts || []).includes(account));
    const mine = account && account === accountValue();
    const className = [
      "room-table-seat",
      account ? "filled" : "empty",
      ready ? "ready" : "",
      mine ? "mine" : "",
    ].filter(Boolean).join(" ");
    return `<span class="${className}" title="${escapeHtml(account || "空位")}"><b>${label}</b><em>${escapeHtml(account || "空位")}</em></span>`;
  }).join("");
}

function tableActionText(room) {
  if (!room) return "点击创建";
  const mine = accountSeat(room);
  if (mine) return "进入对战";
  if (roomStatusValue(room) === "playing") return "对局中";
  if (!firstEmptySeat(room)) return "已满座";
  return "点击入座";
}

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
  if (changes.length) void photonBridgeCall("notifyRoomChanges", changes);
}

async function createOrJoinTable(slotIndex) {
  if (!tokenValue()) {
    window.location.href = "/battle-login?notice=" + encodeURIComponent("请先登录账号。");
    return;
  }
  const room = roomForSlot(slotIndex);
  try {
    if (!room) {
      if (lastRooms.length >= lastMaxRooms) {
        setMessage("当前房间数量已满。", true);
        return;
      }
      const created = await post("/api/lobby/rooms", {
        room_name: `${slotIndex + 1}号桌`,
        ai_policy: $("roomAiPolicySelect")?.value || "low",
      });
      enterRoom(created.room_id, created);
      return;
    }
    const mine = accountSeat(room);
    if (mine) {
      enterRoom(room.room_id, room);
      return;
    }
    if (roomStatusValue(room) === "playing") {
      setMessage("该桌已经开局，未落座玩家不能中途加入。", true);
      return;
    }
    const targetSeat = firstEmptySeat(room);
    if (!targetSeat) {
      setMessage("该桌已经满座。", true);
      return;
    }
    const seated = await post(`/api/battle/${encodeURIComponent(room.room_id)}/sit`, {
      seat: targetSeat.absolute_seat ?? targetSeat.seat ?? 0,
      room_generation: room.room_generation,
    });
    enterRoom(room.room_id, { ...room, ...seated, room_id: room.room_id });
  } catch (error) {
    setMessage(error.message, true);
    await loadRooms();
  }
}

async function toggleReady(roomId) {
  const room = lastRooms.find((item) => String(item.room_id) === String(roomId));
  if (!room) return;
  try {
    await post(`/api/battle/${encodeURIComponent(roomId)}/ready`, {
      room_generation: room.room_generation,
    });
    await loadRooms();
  } catch (error) {
    setMessage(error.message, true);
  }
}

function enterRoom(roomId, room = null) {
  if (!roomId) return;
  saveRoomId(roomId);
  if (room) saveRoomSummary(room);
  void photonBridgeCall("destroy");
  window.location.href = `/battle?room_id=${encodeURIComponent(roomId)}`;
}

async function logout() {
  try {
    if (tokenValue()) await post("/api/auth/logout", {});
  } catch (error) {
    console.warn("logout failed", error);
  } finally {
    clearSession();
    void photonBridgeCall("destroy");
    window.location.href = "/battle-login?notice=" + encodeURIComponent("已退出登录。");
  }
}

function bindAuthEvents() {
  document.querySelectorAll("[data-auth-mode]").forEach((button) => {
    button.addEventListener("click", () => setAuthMode(button.dataset.authMode || "login"));
    button.addEventListener("keydown", (event) => handleAuthTabKeydown(event, button));
  });
  if ($("loginBtn")) $("loginBtn").addEventListener("click", login);
  if ($("registerBtn")) $("registerBtn").addEventListener("click", register);
  ["loginAccountInput", "loginPasswordInput"].forEach((id) => {
    if ($(id)) {
      $(id).addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          login();
        }
      });
    }
  });
  ["registerAccountInput", "registerPasswordInput", "inviteCodeInput"].forEach((id) => {
    if ($(id)) {
      $(id).addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          register();
        }
      });
    }
  });
}

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

async function initAuthPage() {
  applyAuthDefaults();
  setAuthMode("login");
  readNoticeFromUrl();
  bindAuthEvents();
  if (tokenValue()) {
    try {
      const me = await api("/api/auth/me");
      setSession({ ...me, session_token: tokenValue() });
      setAuthStatus("已登录", "正在进入选桌大厅。");
      await navigateToLobby({ animate: false });
    } catch {
      clearSession();
    }
  }
}

async function initLobbyPage() {
  const revealFromAuth = consumePhotonLobbyTransition();
  bindLobbyEvents();
  setRoomAiPolicy($("roomAiPolicySelect")?.value || "low");
  updateSessionUi();
  await loadRooms();
  if (revealFromAuth) {
    await photonBridgeCall("playLobbyReveal");
  }
  roomRefreshTimer = window.setInterval(() => {
    loadRooms().catch((error) => console.warn("room refresh failed", error));
  }, 3000);
}

async function init() {
  if (isAuthPage) await initAuthPage();
  if (isLobbyPage) await initLobbyPage();
}

window.addEventListener("pagehide", () => {
  if (roomRefreshTimer) window.clearInterval(roomRefreshTimer);
});

init().catch((error) => setMessage(error.message, true));
