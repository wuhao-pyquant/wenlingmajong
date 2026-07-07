const ACCOUNT_KEY = "wenling.online.account.v1";
const TOKEN_KEY = "wenling.online.token.v1";
const ROLE_KEY = "wenling.online.role.v1";
const ROOM_KEY = "wenling.online.room_id.v1";
const ROOM_SUMMARY_KEY = "wenling.online.room_summary.v1";

const $ = (id) => document.getElementById(id);
let roomRefreshTimer = null;
let loadingRooms = false;
let lastRooms = [];
let lastMaxRooms = 3;

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
    // Hardened browser profiles can block localStorage.
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
    // Hardened browser profiles can block localStorage.
  }
}

function roomStatusValue(room) {
  return String(room?.status || room?.room_status || "").trim().toLowerCase();
}

function activeOwnedRoom(rooms = lastRooms) {
  const account = accountValue();
  if (!account) return null;
  return (rooms || []).find((room) => (
    room?.owner_account === account && roomStatusValue(room) !== "closed"
  )) || null;
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
  };
}

function saveRoomSummary(room) {
  if (!room?.room_id) return;
  try {
    localStorage.setItem(ROOM_SUMMARY_KEY, JSON.stringify(normalizeRoomSummary(room)));
  } catch {
    // Hardened browser profiles can block localStorage.
  }
}

function ensureCreateRoomNotice() {
  let box = $("createRoomNotice");
  if (box) return box;
  const createRow = $("createRoomBtn")?.closest(".online-room-create-row") || $("createRoomBtn")?.parentElement;
  if (!createRow) return null;
  box = document.createElement("div");
  box.id = "createRoomNotice";
  box.className = "create-room-notice";
  createRow.insertAdjacentElement("afterend", box);
  return box;
}

function updateCreateRoomAvailability(rooms = lastRooms, maxRooms = lastMaxRooms) {
  const createButton = $("createRoomBtn");
  if (!createButton) return;
  const notice = ensureCreateRoomNotice();
  const token = tokenValue();
  const owned = activeOwnedRoom(rooms);
  const roomLimitReached = (rooms || []).length >= maxRooms;
  createButton.disabled = !token || Boolean(owned) || roomLimitReached;
  if (!token) {
    createButton.title = "请先登录账号";
    if (notice) notice.textContent = "";
  } else if (owned) {
    createButton.title = "你已经拥有一个进行中的房间";
    if (notice) notice.textContent = `你已创建房间「${owned.room_name || owned.room_id}」，请先进入或关闭该房间。`;
  } else if (roomLimitReached) {
    createButton.title = "当前房间数量已满";
    if (notice) notice.textContent = "当前房间数量已满，暂时不能创建新房间。";
  } else {
    createButton.title = "";
    if (notice) notice.textContent = "";
  }
}

function setMessage(text, bad = false) {
  const box = $("lobbyMessage");
  if (!box) return;
  box.textContent = text || "";
  box.classList.toggle("bad", Boolean(bad));
}

function updateSessionUi() {
  const account = accountValue();
  const role = roleValue();
  $("currentAccountLabel").textContent = account || "未登录";
  $("currentRoleLabel").textContent = account ? (role === "admin" ? "管理员" : "玩家") : "";
  $("logoutBtn").disabled = !tokenValue();
  updateCreateRoomAvailability();
  const adminEntry = $("adminEntry");
  if (adminEntry) adminEntry.hidden = role !== "admin" || !tokenValue();
}

async function login() {
  try {
    const payload = await post("/api/auth/login", {
      account: $("loginAccountInput").value.trim(),
      password: $("loginPasswordInput").value,
    });
    setSession(payload);
    setMessage("登录成功。");
    await loadRooms();
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function register() {
  try {
    const payload = await post("/api/auth/register", {
      account: $("registerAccountInput").value.trim(),
      password: $("registerPasswordInput").value,
      invite_code: $("inviteCodeInput").value.trim().toUpperCase(),
    });
    setSession(payload);
    setMessage("注册成功，已登录。");
    await loadRooms();
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function loadRooms() {
  updateSessionUi();
  if (!tokenValue()) {
    $("roomList").innerHTML = '<div class="online-empty">请先登录账号。</div>';
    return;
  }
  if (loadingRooms) return;
  loadingRooms = true;
  try {
    const payload = await api("/api/lobby/rooms");
    renderRooms(payload.rooms || [], payload.max_rooms || 3);
  } catch (error) {
    $("roomList").innerHTML = "";
    setMessage(error.message, true);
  } finally {
    loadingRooms = false;
    updateSessionUi();
  }
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

function renderRooms(rooms, maxRooms) {
  lastRooms = Array.isArray(rooms) ? rooms.slice() : [];
  lastMaxRooms = Number(maxRooms) || 3;
  updateCreateRoomAvailability(lastRooms, lastMaxRooms);
  if (!rooms.length) {
    $("roomList").innerHTML = '<div class="online-empty">暂无房间。</div>';
    return;
  }
  $("roomList").innerHTML = rooms.map((room) => {
    const seats = (room.seats || [])
      .map((seat) => seat.account || seat.effective_account || "空位")
      .join(" / ");
    const mine = room.owner_account === accountValue();
    return `
      <article class="online-room-card" data-room-id="${escapeHtml(room.room_id)}">
        <div class="room-card-head">
          <strong>${escapeHtml(room.room_name || "温岭麻将房间")}</strong>
          <span class="tag">${escapeHtml(roomStatusLabel(room.status))}</span>
        </div>
        <div>房主：${escapeHtml(room.owner_account || "-")}</div>
        <div>座位：${escapeHtml(seats || "空位")}</div>
        <div>AI：${room.ai_policy === "high" ? "高级" : "低级"}</div>
        <div class="room-card-actions">
          <button class="primary enter-room-btn" data-room-id="${escapeHtml(room.room_id)}" type="button">进入房间</button>
          ${mine ? `<button class="close-room-btn" data-room-id="${escapeHtml(room.room_id)}" type="button">关闭房间</button>` : ""}
        </div>
      </article>
    `;
  }).join("");
  document.querySelectorAll(".enter-room-btn").forEach((button) => {
    button.addEventListener("click", () => {
      const room = lastRooms.find((item) => String(item.room_id) === String(button.dataset.roomId));
      enterRoom(button.dataset.roomId, room);
    });
  });
  document.querySelectorAll(".close-room-btn").forEach((button) => {
    button.addEventListener("click", () => closeRoom(button.dataset.roomId));
  });
}

async function createRoom() {
  try {
    const room = await post("/api/lobby/rooms", {
      room_name: $("roomNameInput").value.trim(),
      ai_policy: $("roomAiPolicySelect").value,
    });
    enterRoom(room.room_id, room);
  } catch (error) {
    setMessage(error.message, true);
  }
}

function enterRoom(roomId, room = null) {
  if (!roomId) return;
  try {
    localStorage.setItem(ROOM_KEY, roomId);
    if (room) saveRoomSummary(room);
  } catch {
    // Hardened browser profiles can block localStorage.
  }
  window.location.href = `/battle?room_id=${encodeURIComponent(roomId)}`;
}

async function closeRoom(roomId) {
  if (!window.confirm("确认关闭整个房间？")) return;
  if (!window.confirm("关闭后本局作废，所有玩家会回到大厅。继续关闭？")) return;
  try {
    await post(`/api/lobby/rooms/${encodeURIComponent(roomId)}/close`, { confirm: "CLOSE_ROOM" });
    setMessage("房间已关闭。");
    await loadRooms();
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function logout() {
  try {
    if (tokenValue()) await post("/api/auth/logout", {});
  } catch (error) {
    console.warn("logout failed", error);
  } finally {
    clearSession();
    setMessage("已退出登录。");
    await loadRooms();
  }
}

function readNoticeFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const notice = params.get("notice");
  if (notice) setMessage(notice);
}

function bindEvents() {
  $("loginBtn").addEventListener("click", login);
  $("registerBtn").addEventListener("click", register);
  $("logoutBtn").addEventListener("click", logout);
  $("createRoomBtn").addEventListener("click", createRoom);
  ["loginAccountInput", "loginPasswordInput"].forEach((id) => {
    $(id).addEventListener("keydown", (event) => {
      if (event.key === "Enter") login();
    });
  });
  ["registerAccountInput", "registerPasswordInput", "inviteCodeInput"].forEach((id) => {
    $(id).addEventListener("keydown", (event) => {
      if (event.key === "Enter") register();
    });
  });
}

async function init() {
  bindEvents();
  readNoticeFromUrl();
  await loadRooms();
  roomRefreshTimer = window.setInterval(() => {
    loadRooms().catch((error) => console.warn("room refresh failed", error));
  }, 5000);
}

window.addEventListener("pagehide", () => {
  if (roomRefreshTimer) window.clearInterval(roomRefreshTimer);
});

init().catch((error) => setMessage(error.message, true));
