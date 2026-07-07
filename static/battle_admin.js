const ACCOUNT_KEY = "wenling.online.account.v1";
const TOKEN_KEY = "wenling.online.token.v1";
const ROLE_KEY = "wenling.online.role.v1";

const $ = (id) => document.getElementById(id);

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
    return localStorage.getItem(ROLE_KEY) || "";
  } catch {
    return "";
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

function setMessage(text, bad = false) {
  const box = $("adminMessage");
  if (!box) return;
  box.textContent = text || "";
  box.classList.toggle("bad", Boolean(bad));
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
  if (response.status === 401 || response.status === 403) {
    throw new Error(response.status === 403 ? "需要管理员权限。" : "请先登录管理员账号。");
  }
  if (!response.ok || data.error || data.detail) {
    const detail = data.error || data.detail || response.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    cache: "no-store",
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(tokenValue() ? { Authorization: `Bearer ${tokenValue()}` } : {}),
      ...(options.headers || {}),
    },
  });
  return readApiResponse(response);
}

async function post(path, body = {}) {
  return api(path, { method: "POST", body: JSON.stringify(body) });
}

function accountName(row) {
  return row.account || row.account_name || "";
}

function roleLabel(role) {
  if (role === "admin") return "管理员";
  if (role === "ai") return "AI";
  return "玩家";
}

function aiPolicyLabel(policy) {
  return String(policy || "").toLowerCase() === "high" ? "高级" : "低级";
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

function seatSummary(room) {
  const seats = Array.isArray(room?.seats) ? room.seats : [];
  if (!seats.length) return "空位";
  return seats.map((seat) => seat.account || seat.effective_account || "空位").join(" / ");
}

function renderAccounts(accounts) {
  $("accountList").innerHTML = (accounts || []).map((row) => {
    const name = accountName(row);
    const enabled = row.enabled !== false && row.enabled !== 0;
    const isAi = Boolean(row.is_ai);
    return `
      <article class="admin-item">
        <div class="admin-item-head">
          <strong>${escapeHtml(name)}</strong>
          <span class="tag">${enabled ? "启用" : "停用"}</span>
        </div>
        <div>角色：${escapeHtml(roleLabel(row.role))}${isAi ? " · 固定 AI" : ""}</div>
        <div class="room-card-actions">
          <button class="account-toggle-btn" data-account="${escapeHtml(name)}" data-action="${enabled ? "disable" : "enable"}" ${isAi ? "disabled" : ""} type="button">${enabled ? "停用" : "启用"}</button>
          <button class="account-reset-btn" data-account="${escapeHtml(name)}" ${isAi ? "disabled" : ""} type="button">重置密码</button>
        </div>
      </article>
    `;
  }).join("") || '<div class="online-empty">暂无账号。</div>';

  document.querySelectorAll(".account-toggle-btn").forEach((button) => {
    button.addEventListener("click", () => toggleAccount(button.dataset.account, button.dataset.action));
  });
  document.querySelectorAll(".account-reset-btn").forEach((button) => {
    button.addEventListener("click", () => resetPassword(button.dataset.account));
  });
}

function renderInviteCodes(codes) {
  $("inviteCodeList").innerHTML = (codes || []).map((row) => {
    const enabled = row.enabled !== false && row.enabled !== 0;
    const maxUses = row.max_uses ?? "不限";
    const used = row.used_count ?? row.uses ?? 0;
    return `
      <article class="admin-item">
        <div class="admin-item-head">
          <strong>${escapeHtml(row.code)}</strong>
          <span class="tag">${enabled ? "可用" : "停用"}</span>
        </div>
        <div>使用：${escapeHtml(used)} / ${escapeHtml(maxUses)}</div>
        <div>创建者：${escapeHtml(row.created_by || "-")}</div>
        <div class="room-card-actions">
          <button class="invite-disable-btn" data-code="${escapeHtml(row.code)}" ${enabled ? "" : "disabled"} type="button">停用</button>
        </div>
      </article>
    `;
  }).join("") || '<div class="online-empty">暂无邀请码。</div>';

  document.querySelectorAll(".invite-disable-btn").forEach((button) => {
    button.addEventListener("click", () => disableInviteCode(button.dataset.code));
  });
}

function renderPresence(visitors) {
  $("presenceList").innerHTML = (visitors || []).map((row) => `
    <article class="admin-item">
      <div class="admin-item-head">
        <strong>${escapeHtml(row.account || "匿名访客")}</strong>
        <span class="tag">${escapeHtml(row.room_id || "大厅")}</span>
      </div>
      <div>访客：${escapeHtml(row.visitor_id || "-")}</div>
      <div>座位：${escapeHtml(row.seat ?? "-")}</div>
    </article>
  `).join("") || '<div class="online-empty">暂无在线记录。</div>';
}

function renderRooms(rooms) {
  $("adminRoomList").innerHTML = (rooms || []).map((room) => `
    <article class="admin-item">
      <div class="admin-item-head">
        <strong>${escapeHtml(room.room_name || "温岭麻将房间")}</strong>
        <span class="tag">${escapeHtml(roomStatusLabel(room.status))}</span>
      </div>
      <div>房主：${escapeHtml(room.owner_account || "-")}</div>
      <div>房间 ID：${escapeHtml(room.room_id || "-")}</div>
      <div>座位：${escapeHtml(seatSummary(room))}</div>
      <div>统一 AI：${aiPolicyLabel(room.ai_policy)}</div>
      <div class="room-card-actions">
        <button class="warn admin-close-room-btn" data-room-id="${escapeHtml(room.room_id)}" data-room-name="${escapeHtml(room.room_name || room.room_id || "房间")}" type="button">关闭房间</button>
      </div>
    </article>
  `).join("") || '<div class="online-empty">暂无活跃房间。</div>';

  document.querySelectorAll(".admin-close-room-btn").forEach((button) => {
    button.addEventListener("click", () => closeRoom(button.dataset.roomId, button.dataset.roomName));
  });
}

async function loadAdminData() {
  const account = accountValue() || "未登录";
  const role = roleValue() === "admin" ? "管理员" : "非管理员";
  $("adminAccountLabel").textContent = `${account} · ${role}`;

  const [accounts, invites, presence, rooms] = await Promise.all([
    api("/api/admin/accounts"),
    api("/api/admin/invite-codes"),
    api("/api/admin/presence"),
    api("/api/admin/rooms"),
  ]);

  renderAccounts(accounts.accounts || []);
  renderInviteCodes(invites.invite_codes || []);
  renderPresence(presence.visitors || []);
  renderRooms(rooms.rooms || []);
}

async function refreshAdminData() {
  try {
    await loadAdminData();
    setMessage("已刷新。");
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function generateInviteCode() {
  const maxUsesRaw = $("inviteMaxUsesInput").value.trim();
  const body = {
    code: $("inviteCodeAdminInput").value.trim().toUpperCase(),
  };
  if (maxUsesRaw) body.max_uses = Number(maxUsesRaw);
  try {
    await post("/api/admin/invite-codes", body);
    $("inviteCodeAdminInput").value = "";
    $("inviteMaxUsesInput").value = "";
    setMessage("邀请码已生成。");
    await loadAdminData();
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function disableInviteCode(code) {
  if (!window.confirm(`确认停用邀请码 ${code}？`)) return;
  try {
    await post(`/api/admin/invite-codes/${encodeURIComponent(code)}/disable`, {});
    setMessage("邀请码已停用。");
    await loadAdminData();
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function toggleAccount(account, action) {
  const label = action === "disable" ? "停用" : "启用";
  if (!window.confirm(`确认${label}账号 ${account}？`)) return;
  try {
    await post(`/api/admin/accounts/${encodeURIComponent(account)}/${action}`, {});
    setMessage(`账号已${label}。`);
    await loadAdminData();
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function resetPassword(account) {
  const password = window.prompt(`输入 ${account} 的新密码`);
  if (!password) return;
  try {
    await post(`/api/admin/accounts/${encodeURIComponent(account)}/reset-password`, { password });
    setMessage("密码已重置。");
    await loadAdminData();
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function closeRoom(roomId, roomName) {
  if (!roomId) return;
  if (!window.confirm(`确认关闭房间「${roomName || roomId}」？`)) return;
  if (!window.confirm("关闭后本局作废，所有玩家都会回到大厅。继续关闭房间？")) return;
  try {
    await post(`/api/admin/rooms/${encodeURIComponent(roomId)}/close`, { confirm: "CLOSE_ROOM" });
    setMessage("房间已关闭。");
    await loadAdminData();
  } catch (error) {
    setMessage(error.message, true);
  }
}

function init() {
  if (!tokenValue()) {
    window.location.href = "/battle-login?notice=请先登录管理员账号。";
    return;
  }
  $("adminRefreshBtn").addEventListener("click", refreshAdminData);
  $("generateInviteBtn").addEventListener("click", generateInviteCode);
  refreshAdminData();
}

init();
