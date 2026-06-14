const titles = {
  intraday: ["盘中决策", "按 checkpoint 运行市场扫描、候选股和持仓/观察池处理。"],
  strategy: ["策略包扫描", "运行首板次日策略包，并保留流通股过滤后的结果。"],
  weekly: ["周末板块轮动", "生成板块估值、四象限、季节性主题和个股观察池周报。"],
  reports: ["报告中心", "查看最近生成的 Markdown、CSV 和 JSON。"],
  settings: ["迁移与配置", "启动、备份和恢复这个本地工具。"],
};

let activeJob = null;
let pollTimer = null;

function today() {
  return new Date().toISOString().slice(0, 10);
}

function setDefaults() {
  for (const id of ["intraday-date", "strategy-date", "weekly-date"]) {
    document.getElementById(id).value = today();
  }
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok || data.error) {
    throw new Error(data.error || response.statusText);
  }
  return data;
}

function switchView(name) {
  document.querySelectorAll(".nav").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
  document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
  document.getElementById("view-title").textContent = titles[name][0];
  document.getElementById("view-subtitle").textContent = titles[name][1];
  if (name === "reports") loadReports();
}

async function loadStatus() {
  const status = await api("/api/status");
  const ok = status.scripts_ready && status.rotation_ready;
  document.getElementById("status-pill").textContent = ok ? "脚本就绪" : "配置待检查";
  document.getElementById("settings-status").innerHTML = `
    <table>
      <tr><th>项目</th><th>路径</th></tr>
      <tr><td>工具目录</td><td>${status.toolkit_root}</td></tr>
      <tr><td>盘中脚本</td><td>${status.intraday_scripts}</td></tr>
      <tr><td>周报项目</td><td>${status.rotation_dir}</td></tr>
      <tr><td>导出目录</td><td>${status.config.intraday_export_root}</td></tr>
    </table>
  `;
}

function log(message) {
  document.getElementById("job-output").textContent = message;
}

async function startJob(endpoint, payload) {
  const data = await api(endpoint, { method: "POST", body: JSON.stringify(payload) });
  activeJob = data.job.id;
  log(`任务已启动：${activeJob}\n${data.job.command.join(" ")}`);
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(pollJob, 1200);
  await pollJob();
}

async function pollJob() {
  if (!activeJob) return;
  const data = await api(`/api/jobs/${activeJob}`);
  const job = data.job;
  if (!job) return;
  const header = `[${job.status}] ${job.kind} ${job.id}\n${job.command.join(" ")}\n\n`;
  log(header + (job.output || ""));
  if (job.status === "completed" || job.status === "failed") {
    clearInterval(pollTimer);
    pollTimer = null;
    loadReports();
  }
}

async function loadReports() {
  const data = await api("/api/reports");
  const files = [...data.weekly_reports, ...data.intraday_exports].slice(0, 140);
  const list = document.getElementById("report-list");
  if (!files.length) {
    list.innerHTML = "<p>还没有报告文件。</p>";
    return;
  }
  list.innerHTML = files
    .map(
      (file) => `
        <button class="file-item" data-path="${encodeURIComponent(file.path)}">
          <strong>${file.name}</strong>
          <span>${file.relative_path}</span>
          <span>${file.modified} · ${Math.round(file.size / 1024)} KB</span>
        </button>
      `,
    )
    .join("");
  list.querySelectorAll(".file-item").forEach((button) => {
    button.addEventListener("click", () => previewFile(decodeURIComponent(button.dataset.path)));
  });
}

async function previewFile(path) {
  const data = await api(`/api/preview?path=${encodeURIComponent(path)}`);
  const preview = document.getElementById("preview");
  if (data.type === "csv") {
    const head = data.columns.map((col) => `<th>${escapeHtml(col)}</th>`).join("");
    const rows = data.rows
      .map((row) => `<tr>${data.columns.map((col) => `<td>${escapeHtml(row[col] ?? "")}</td>`).join("")}</tr>`)
      .join("");
    preview.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table>`;
  } else {
    preview.innerHTML = `<pre>${escapeHtml(data.text)}</pre>`;
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function bindEvents() {
  document.querySelectorAll(".nav").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
  document.getElementById("refresh-reports").addEventListener("click", loadReports);
  document.getElementById("clear-output").addEventListener("click", () => log("尚未运行任务。"));

  document.getElementById("run-intraday").addEventListener("click", () => {
    startJob("/api/run/intraday", {
      date: document.getElementById("intraday-date").value,
      checkpoint: document.getElementById("intraday-checkpoint").value,
      pool: document.getElementById("intraday-pool").value,
      limit: Number(document.getElementById("intraday-limit").value || 0),
    }).catch((error) => log(error.message));
  });

  document.getElementById("run-strategy").addEventListener("click", () => {
    startJob("/api/run/strategy", {
      date: document.getElementById("strategy-date").value,
      checkpoint: document.getElementById("strategy-checkpoint").value,
      max_float_shares: Number(document.getElementById("strategy-float").value || 0),
      limit: Number(document.getElementById("strategy-limit").value || 0),
    }).catch((error) => log(error.message));
  });

  document.getElementById("run-weekly").addEventListener("click", () => {
    startJob("/api/run/weekly", {
      as_of: document.getElementById("weekly-date").value,
      force_refresh: document.getElementById("weekly-force").checked,
      skip_daily_fetch: document.getElementById("weekly-skip-daily").checked,
    }).catch((error) => log(error.message));
  });
}

setDefaults();
bindEvents();
loadStatus().catch((error) => {
  document.getElementById("status-pill").textContent = "状态读取失败";
  log(error.message);
});
loadReports().catch(() => {});
