const BATTLE_ACCOUNT_STORAGE_KEY = "wenling.battle.account.v1";

const $ = (id) => document.getElementById(id);
let lobbyState = null;
let lobbyWaitLoopActive = false;
let lobbyHeartbeatLoopActive = false;
let lobbyLoading = false;
const BATTLE_HEARTBEAT_INTERVAL_MS = 10000;
const BATTLE_GENERATION_WRITE_PATHS = new Set([
  "/api/battle/heartbeat",
  "/api/battle/sit",
  "/api/battle/leave",
  "/api/battle/kick",
  "/api/battle/ready",
  "/api/battle/reset",
]);

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[ch]));
}

async function api(path) {
  const response = await fetch(path);
  const data = await readApiResponse(response);
  if (!response.ok || data.error || data.detail) {
    const detail = data.error || data.detail || response.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

async function post(path, body) {
  const payload = { ...(body || {}) };
  if (BATTLE_GENERATION_WRITE_PATHS.has(path) && payload.room_generation === undefined) {
    const generation = Number(lobbyState?.room_generation);
    if (!Number.isInteger(generation)) {
      throw new Error("房间状态尚未加载，请刷新后重试。");
    }
    payload.room_generation = generation;
  }
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await readApiResponse(response);
  if (!response.ok || data.error || data.detail) {
    const detail = data.error || data.detail || response.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
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

function accountValue() {
  return localStorage.getItem(BATTLE_ACCOUNT_STORAGE_KEY) || "";
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function battleStateQuery(path, since) {
  const params = new URLSearchParams();
  const account = accountValue();
  if (account) params.set("account", account);
  if (since !== null && since !== undefined) params.set("since", String(since));
  if (path.includes("/wait")) params.set("timeout", "20");
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

function setMessage(text, bad = false) {
  $("lobbyMessage").textContent = text || "";
  $("lobbyMessage").classList.toggle("bad", Boolean(bad));
}

function seatName(seat) {
  return ["下位", "右位", "上位", "左位"][seat] || String(seat);
}

async function loadState() {
  if (lobbyLoading) return;
  lobbyLoading = true;
  try {
    lobbyState = await api(battleStateQuery("/api/battle/state"));
    render();
  } finally {
    lobbyLoading = false;
  }
}

async function waitLobbyStateOnce() {
  if (lobbyLoading) {
    await delay(200);
    return;
  }
  lobbyLoading = true;
  try {
    const since = Number.isFinite(Number(lobbyState?.room_revision)) ? Number(lobbyState.room_revision) : null;
    lobbyState = await api(battleStateQuery("/api/battle/wait", since));
    render();
  } catch (error) {
    console.warn("battle lobby wait failed", error);
    await delay(1000);
  } finally {
    lobbyLoading = false;
  }
}

async function startLobbyWaitLoop() {
  if (lobbyWaitLoopActive) return;
  lobbyWaitLoopActive = true;
  while (lobbyWaitLoopActive) {
    await waitLobbyStateOnce();
  }
}

async function sendHeartbeat() {
  const account = accountValue();
  if (!account || !Number.isInteger(Number(lobbyState?.room_generation))) return;
  try {
    await post("/api/battle/heartbeat", { account });
  } catch (error) {
    console.warn("battle lobby heartbeat failed", error);
  }
}

async function startHeartbeatLoop() {
  if (lobbyHeartbeatLoopActive) return;
  lobbyHeartbeatLoopActive = true;
  while (lobbyHeartbeatLoopActive) {
    await sendHeartbeat();
    await delay(BATTLE_HEARTBEAT_INTERVAL_MS);
  }
}

function render() {
  const account = accountValue();
  if ($("lobbyAccountInput").value === "" && account) $("lobbyAccountInput").value = account;
  $("lobbyAccountTag").textContent = account ? `当前账号：${account}` : "未登录";
  const seats = lobbyState?.seats || [];
  const seated = seats.find((seat) => seat.account === account);
  const ready = Boolean(account && lobbyState?.ready_accounts?.includes(account));
  const hasHumanSeat = seats.some((seat) => Boolean(seat.account));

  $("lobbySeatGrid").innerHTML = seats.map((seat) => {
    const occupied = Boolean(seat.account);
    const mine = account && seat.account === account;
    const disabled = !account || (occupied && !mine) || (lobbyState?.game_started && lobbyState?.phase !== "round_over");
    const offline = occupied && seat.online === false && !seat.is_ai ? "（离线）" : "";
    const label = occupied
      ? `${seatName(seat.seat)}：${escapeHtml(seat.account)}${offline}${seat.ready ? "（已准备）" : ""}`
      : hasHumanSeat
        ? `${seatName(seat.seat)}：空闲（默认 ${escapeHtml(seat.effective_account || "AI")}）`
        : `${seatName(seat.seat)}：空闲（可入座）`;
    return `<button class="seat-pick ${mine ? "active" : ""}" data-seat="${seat.seat}" ${disabled ? "disabled" : ""}>${label}</button>`;
  }).join("");

  $("lobbySeatGrid").querySelectorAll(".seat-pick").forEach((button) => {
    button.addEventListener("click", () => sitSeat(Number(button.dataset.seat)));
  });

  const canKick = Boolean(account && seated);
  const kickTargets = seats.filter((seat) => seat.account && seat.account !== account && !seat.is_ai);
  const kickList = $("lobbyKickList");
  if (kickList) {
    kickList.innerHTML = canKick && kickTargets.length
      ? kickTargets.map((seat) => `
        <button class="lobby-kick-btn" type="button" data-account="${escapeHtml(seat.account)}">
          踢出 ${escapeHtml(seatName(seat.seat))} ${escapeHtml(seat.account)}
        </button>
      `).join("")
      : "";
    kickList.querySelectorAll(".lobby-kick-btn").forEach((button) => {
      button.addEventListener("click", () => kickPlayer(button.dataset.account || ""));
    });
  }

  $("lobbyReadyBtn").disabled = !seated;
  $("lobbyReadyBtn").classList.toggle("ready-off", ready);
  $("lobbyReadyBtn").classList.toggle("gold", !ready);
  $("lobbyReadyBtn").textContent = ready ? "已准备" : "准备";
  $("lobbyLeaveBtn").disabled = !seated || (lobbyState?.game_started && lobbyState?.phase !== "round_over");
  $("lobbyEnterBtn").disabled = !(lobbyState?.game_started && account && seated);
  $("lobbyStatus").innerHTML = `
    <div>状态：${lobbyState?.game_started ? (lobbyState.phase === "round_over" ? "本局结束，等待准备下一局" : "对局进行中") : "等待入座准备"}</div>
    <div>数据库：${escapeHtml(lobbyState?.db?.path || "")}</div>
  `;

  if (lobbyState?.game_started && account && seated) {
    window.location.href = "/battle";
  }
}

async function login(register = false) {
  const account = $("lobbyAccountInput").value.trim();
  if (!account) {
    setMessage("请输入账号名。", true);
    return;
  }
  try {
    const result = await post(register ? "/api/battle/register" : "/api/battle/login", { account });
    localStorage.setItem(BATTLE_ACCOUNT_STORAGE_KEY, result.account || account);
    await sendHeartbeat();
    setMessage(register ? "注册并登录成功。" : "登录成功。");
    await loadState();
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function sitSeat(seat) {
  const account = accountValue();
  if (!account) {
    setMessage("请先登录账号。", true);
    return;
  }
  try {
    lobbyState = await post("/api/battle/sit", { account, seat });
    setMessage("已入座。");
    render();
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function leaveSeat() {
  const account = accountValue();
  if (!account) return;
  try {
    lobbyState = await post("/api/battle/leave", { account });
    setMessage("已离座。");
    render();
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function kickPlayer(target) {
  const account = accountValue();
  if (!account || !target) return;
  try {
    lobbyState = await post("/api/battle/kick", { account, target });
    setMessage(`已踢出 ${target}`);
    render();
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function ready() {
  const account = accountValue();
  if (!account) {
    setMessage("请先登录账号。", true);
    return;
  }
  try {
    lobbyState = await post("/api/battle/ready", { account });
    setMessage(lobbyState?.ready_accounts?.includes(account) ? "已准备。" : "已取消准备。");
    render();
  } catch (error) {
    setMessage(error.message, true);
  }
}

function init() {
  $("lobbyAccountInput").value = accountValue();
  $("lobbyRegisterBtn").addEventListener("click", () => login(true));
  $("lobbyLoginBtn").addEventListener("click", () => login(false));
  $("lobbyReadyBtn").addEventListener("click", ready);
  $("lobbyLeaveBtn").addEventListener("click", leaveSeat);
  $("lobbyEnterBtn").addEventListener("click", () => { window.location.href = "/battle"; });
  loadState().catch((error) => setMessage(error.message, true));
  startLobbyWaitLoop().catch((error) => setMessage(error.message, true));
  startHeartbeatLoop().catch((error) => console.warn("battle lobby heartbeat loop stopped", error));
}

init();
