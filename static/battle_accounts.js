const $ = (id) => document.getElementById(id);

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
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
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

function pct(value) {
  return value === null || value === undefined ? "-" : `${(Number(value) * 100).toFixed(1)}%`;
}

function num(value) {
  return value === null || value === undefined ? "-" : String(value);
}

function renderStat(stat) {
  return `
    <td>${num(stat.rounds)}</td>
    <td>${num(stat.avg_opening_shanten)}</td>
    <td>${num(stat.avg_de_draws)}</td>
    <td>${num(stat.avg_fan_flower_draws)}</td>
    <td>${pct(stat.normal_win_rate)}</td>
    <td>${pct(stat.leizi_win_rate)}</td>
  `;
}

async function loadAccounts() {
  const data = await api("/api/battle/accounts");
  $("adminDbInfo").innerHTML = `
    <div>SQLite 文件：${escapeHtml(data.db?.path || "")}</div>
    <div>表：${escapeHtml((data.db?.tables || []).join(" / "))}</div>
  `;
  const rows = (data.accounts || []).map((item) => {
    const all = item.stats?.all || {};
    const today = item.stats?.today || {};
    return `
      <tr>
        <td rowspan="2"><strong>${escapeHtml(item.account)}</strong>${item.is_ai ? '<span class="tag">AI</span>' : ""}</td>
        <td>长期</td>
        ${renderStat(all)}
      </tr>
      <tr>
        <td>今日</td>
        ${renderStat(today)}
      </tr>
    `;
  }).join("");
  $("adminAccounts").innerHTML = `
    <table class="player-stats-table account-admin-table">
      <thead>
        <tr>
          <th>账号</th>
          <th>周期</th>
          <th>局数</th>
          <th>起手向听</th>
          <th>摸得</th>
          <th>加番花</th>
          <th>普通胡率</th>
          <th>劣子胡率</th>
        </tr>
      </thead>
      <tbody>${rows || '<tr><td colspan="8">暂无账号</td></tr>'}</tbody>
    </table>
  `;
}

async function createAccount() {
  const account = $("adminAccountInput").value.trim();
  if (!account) return;
  await post("/api/battle/register", { account });
  $("adminAccountInput").value = "";
  await loadAccounts();
}

async function resetStats() {
  if (!window.confirm("确定要清空所有账号的长期和今日统计吗？账号本身会保留。")) return;
  await post("/api/battle/stats/reset", {});
  await loadAccounts();
}

function init() {
  $("adminCreateBtn").addEventListener("click", () => createAccount().catch((error) => alert(error.message)));
  $("adminRefreshBtn").addEventListener("click", () => loadAccounts().catch((error) => alert(error.message)));
  $("adminResetStatsBtn").addEventListener("click", () => resetStats().catch((error) => alert(error.message)));
  loadAccounts().catch((error) => {
    $("adminAccounts").innerHTML = `<div class="lobby-message bad">${escapeHtml(error.message)}</div>`;
  });
}

init();
