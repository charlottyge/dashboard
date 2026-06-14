const LOCAL_PORTFOLIO_KEY = "a-share-dashboard-local-portfolio-v1";
const LOCAL_MARKDOWN_KEY = "a-share-dashboard-markdown-v1";

const tableLabels = {
  market_overview: "市场概览",
  market_sector_scan: "板块扫描",
  hot_board_front_core: "强板块中军 / 前排",
  market_temperature: "竞价温度",
  sector_strength: "竞价板块强度",
  yesterday_strong_lines: "昨日强线竞价",
  watchlist_portfolio_open: "自选 / 持仓竞价",
  sector_first_impact: "第一轮冲击板块",
  candidate_first_impact: "第一轮冲击候选",
  portfolio_first_impact: "持仓第一轮冲击",
  candidate_scores: "10:30 候选评分",
  watchlist_portfolio_actions: "10:30 自选 / 持仓处理",
  portfolio_extra: "持仓额外信息",
  morning_mainlines: "上午主线",
  candidate_morning_check: "上午候选检查",
  portfolio_morning_plan: "午后预案",
  sector_afternoon_change: "午后板块变化",
  candidate_afternoon_restart: "午后候选重启",
  portfolio_afternoon_status: "午后持仓状态",
  market_close_confirm: "尾盘市场确认",
  sector_close_confirm: "尾盘板块确认",
  candidate_close_confirm: "尾盘候选确认",
  portfolio_close_confirm: "尾盘持仓确认",
  final_market: "盘后市场",
  final_sectors: "盘后板块",
  final_stocks: "盘后个股",
  portfolio_final_review: "盘后持仓复盘",
  strategy_summary: "策略汇总",
  strategy_candidates: "策略候选",
  strategy_candidates_float_excluded: "流通股过滤",
  strategy_candidates_float_unavailable: "流通股不可用",
};

let siteData = null;
let activeDay = null;
let activeCheckpointId = null;
let activeView = "radar";

function value(input, fallback = "-") {
  return input === null || input === undefined || input === "" ? fallback : input;
}

function escapeHtml(input) {
  return String(value(input, ""))
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function tableTitle(table) {
  const key = table.name.replace(/\.csv$/i, "");
  return tableLabels[key] || table.name;
}

function renderMetrics(day) {
  const checkpoints = day?.checkpoints || [];
  const latest = checkpoints[checkpoints.length - 1] || {};
  const decision = latest.decision || {};
  const p0 = (decision.portfolio_priority || []).filter((item) => item.priority === "P0").length;
  const metrics = [
    ["时间点", checkpoints.length, "当前交易日已有扫描数量"],
    ["市场状态", value(decision.market_state), value(latest.label, "")],
    ["风险偏好", value(decision.risk_preference), p0 ? `${p0} 个 P0 持仓优先处理` : "无 P0 持仓"],
    ["数据错误", value(latest.summary?.error_count || 0), "来自最新 checkpoint summary"],
  ];
  document.getElementById("view-radar-metrics").innerHTML = metrics
    .map(
      ([label, number, note]) => `
        <div class="metric">
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(number)}</strong>
          <small>${escapeHtml(note)}</small>
        </div>
      `,
    )
    .join("");
}

function setupDateSelector() {
  const select = document.getElementById("date-select");
  const days = siteData.timeline_days || [];
  select.innerHTML = days.map((day) => `<option value="${escapeHtml(day.date)}">${escapeHtml(day.date)}</option>`).join("");
  select.addEventListener("change", () => selectDay(select.value));
  if (days.length) selectDay(days[0].date);
}

function setupViewTabs() {
  document.querySelectorAll(".view-tab").forEach((button) => {
    button.addEventListener("click", () => {
      activeView = button.dataset.view;
      renderViewTabs();
    });
  });
  renderViewTabs();
}

function renderViewTabs() {
  document.querySelectorAll(".view-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === activeView);
  });
  document.querySelectorAll(".app-view").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.viewPanel === activeView);
  });
}

function selectDay(date) {
  activeDay = (siteData.timeline_days || []).find((day) => day.date === date);
  activeCheckpointId = activeDay?.checkpoints?.[activeDay.checkpoints.length - 1]?.id || null;
  renderMetrics(activeDay);
  renderTimeline();
}

function renderTimeline() {
  const checkpoints = activeDay?.checkpoints || [];
  document.getElementById("timeline-subtitle").textContent = activeDay
    ? `${activeDay.date} · ${checkpoints.length} 个 checkpoint`
    : "没有可展示的 checkpoint。";
  document.getElementById("checkpoint-tabs").innerHTML = checkpoints
    .map(
      (item) => `
        <button class="checkpoint-tab ${item.id === activeCheckpointId ? "active" : ""}" data-id="${escapeHtml(item.id)}">
          <strong>${escapeHtml(item.label)}</strong>
          <span>${escapeHtml(item.decision?.risk_preference || "风险-")}</span>
        </button>
      `,
    )
    .join("");
  document.querySelectorAll(".checkpoint-tab").forEach((button) => {
    button.addEventListener("click", () => {
      activeCheckpointId = button.dataset.id;
      renderTimeline();
    });
  });
  const current = checkpoints.find((item) => item.id === activeCheckpointId) || checkpoints[0];
  renderCheckpoint(current);
}

function renderCheckpoint(checkpoint) {
  const target = document.getElementById("checkpoint-detail");
  if (!checkpoint) {
    target.innerHTML = '<p class="empty">当前日期没有扫描结果。</p>';
    return;
  }
  const decision = checkpoint.decision || {};
  target.innerHTML = `
    <div class="decision-layout">
      <section class="decision-main">
        <div class="state-line">
          <span>${escapeHtml(checkpoint.label)}</span>
          <strong>${escapeHtml(value(decision.market_state, "暂无市场状态"))}</strong>
          <small>${escapeHtml(checkpoint.directory)}</small>
        </div>
        <div class="pill-row">
          <span class="pill">风险偏好：${escapeHtml(value(decision.risk_preference))}</span>
          <span class="pill">fallback：${escapeHtml(decision.data_quality?.fallback_used ? "是" : "否")}</span>
          <span class="pill">错误：${escapeHtml(value(decision.data_quality?.error_count || checkpoint.summary?.error_count || 0))}</span>
        </div>
        ${renderDecisionLists(decision)}
      </section>
    </div>
  `;
  renderCheckpointTables(checkpoint);
}

function renderDecisionLists(decision) {
  return `
    <div class="decision-grid">
      ${renderItemList("市场情绪", buildMarketEmotionItems(decision), renderEmotionItem)}
      ${renderItemList("确认主线", decision.confirmed_mainlines, renderLineItem)}
      ${renderItemList("走弱方向", decision.weakening_mainlines, renderLineItem)}
      ${renderItemList("新改善方向", decision.new_improving_lines, renderLineItem)}
      ${renderItemList("第一轮冲击候选", firstImpactCandidates(), renderCandidateItem)}
      ${renderItemList("持仓优先级", decision.portfolio_priority, renderPortfolioPriority)}
      ${renderItemList("下一 checkpoint 看什么", decision.next_checkpoint_watch, renderWatchItem)}
    </div>
  `;
}

function currentCheckpoint() {
  const checkpoints = activeDay?.checkpoints || [];
  return checkpoints.find((item) => item.id === activeCheckpointId) || checkpoints[0];
}

function renderCheckpointTables(checkpoint) {
  const target = document.getElementById("checkpoint-tables");
  if (!target) return;
  document.getElementById("tables-subtitle").textContent = checkpoint
    ? `${checkpoint.label} · ${checkpoint.directory}`
    : "当前 checkpoint 的原始输出表。";
  target.innerHTML = checkpoint ? (checkpoint.tables || []).map(renderTable).join("") : '<p class="empty">暂无数据表。</p>';
}

function buildMarketEmotionItems(decision) {
  const quality = decision.data_quality || {};
  return [
    { label: "市场状态", value: value(decision.market_state, "暂无") },
    { label: "风险偏好", value: value(decision.risk_preference, "暂无") },
    { label: "数据质量", value: quality.fallback_used ? "部分 fallback" : "正常" },
    { label: "错误记录", value: value(quality.error_count, 0) },
  ];
}

function renderItemList(title, items, renderer) {
  const safeItems = Array.isArray(items) ? items : [];
  return `
    <div class="decision-box">
      <h3>${escapeHtml(title)}</h3>
      ${
        safeItems.length
          ? `<ul>${safeItems.slice(0, 8).map((item) => `<li>${renderer(item)}</li>`).join("")}</ul>`
          : '<p class="muted">暂无。</p>'
      }
    </div>
  `;
}

function renderLineItem(item) {
  const tags = [
    item.stage,
    item.rebound_type && item.rebound_type !== "none" ? item.rebound_type : "",
    item.crowding_signal && item.crowding_signal !== "normal" ? item.crowding_signal : "",
    item.two_day_acceleration ? "two_day_acceleration" : "",
  ].filter(Boolean);
  const structure = item.structure_state
    ? `结构：${item.structure_state}${item.structure_score !== undefined ? `(${item.structure_score})` : ""}`
    : "";
  return `
    <strong>${escapeHtml(item.name)}</strong>
    <span>${escapeHtml(tags.join(" · ") || item.theme_tier || item.intraday_state || "")}</span>
    ${structure ? `<b class="structure-note">${escapeHtml(structure)}</b>` : ""}
    <em>${escapeHtml(item.reason || "")}</em>
  `;
}

function renderEmotionItem(item) {
  return `<strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(item.value)}</span>`;
}

function firstImpactCandidates() {
  const checkpoint = currentCheckpoint();
  const tables = checkpoint?.tables || [];
  const preferred = tables.find((table) => table.name === "candidate_first_impact.csv");
  const fallback = tables.find((table) => table.name === "candidate_scores.csv" || table.name === "strategy_candidates.csv");
  const table = preferred || fallback;
  if (!table) return [];
  return (table.rows || []).slice(0, 8).map((row) => ({
    stock: row["股票"] || [row["name"], row["code"]].filter(Boolean).join(" ") || "-",
    sector: row["板块"] || row["匹配板块"] || row["sector"] || "",
    pct: row["当前涨幅"] || row["当前涨幅%"] || row["pct"] || "",
    reason: row["走势自然语言"] || row["命中原因"] || row["setup_pass_reasons"] || row["来源"] || "",
  }));
}

function renderCandidateItem(item) {
  return `<strong>${escapeHtml(item.stock)}</strong><span>${escapeHtml([item.sector, item.pct].filter(Boolean).join(" · "))}</span><em>${escapeHtml(item.reason)}</em>`;
}

function renderPortfolioPriority(item) {
  return `<strong>${escapeHtml(item.priority)} · ${escapeHtml(item.stock)}</strong><span>${escapeHtml(item.action_type || "")}</span><em>${escapeHtml(item.reason || "")}</em>`;
}

function renderWatchItem(item) {
  return `<strong>${escapeHtml(item)}</strong>`;
}

function renderTable(table) {
  const columns = table.columns || [];
  const rows = table.rows || [];
  if (!columns.length) {
    return `<div class="table-card"><h3>${escapeHtml(tableTitle(table))}</h3><p class="empty">表格为空。</p></div>`;
  }
  const visibleColumns = columns.slice(0, 16);
  const head = visibleColumns.map((column) => `<th>${escapeHtml(column)}</th>`).join("");
  const body = rows
    .map((row) => `<tr>${visibleColumns.map((column) => `<td>${escapeHtml(row[column])}</td>`).join("")}</tr>`)
    .join("");
  return `
    <div class="table-card">
      <h3>${escapeHtml(tableTitle(table))} · ${rows.length}/${table.row_count} 行</h3>
      <div class="table-scroll">
        <table>
          <thead><tr>${head}</tr></thead>
          <tbody>${body}</tbody>
        </table>
      </div>
    </div>
  `;
}

function localHoldings() {
  try {
    return JSON.parse(localStorage.getItem(LOCAL_PORTFOLIO_KEY) || "[]");
  } catch {
    return [];
  }
}

function saveLocalHoldings(rows) {
  localStorage.setItem(LOCAL_PORTFOLIO_KEY, JSON.stringify(rows));
}

function mergedHoldings() {
  const base = (siteData.portfolio?.base_holdings || []).map((row) => ({ ...row, source: "portfolio.md" }));
  const local = localHoldings().map((row) => ({ ...row, source: "前端保存" }));
  const byCode = new Map();
  for (const row of base) byCode.set(String(row.code || row.name), row);
  for (const row of local) byCode.set(String(row.code || row.name), row);
  return [...byCode.values()];
}

function setupPortfolio() {
  const meta = document.getElementById("portfolio-meta");
  meta.textContent = `portfolio.md：${value(siteData.portfolio?.modified, "未读取")} · 前端保存只存在当前浏览器`;
  document.getElementById("portfolio-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const row = {
      code: document.getElementById("holding-code").value.trim(),
      name: document.getElementById("holding-name").value.trim(),
      shares_total: document.getElementById("holding-shares").value,
      avg_cost: document.getElementById("holding-cost").value,
      note: document.getElementById("holding-note").value.trim(),
    };
    if (!row.code && !row.name) return;
    const rows = localHoldings().filter((item) => String(item.code || item.name) !== String(row.code || row.name));
    rows.push(row);
    saveLocalHoldings(rows);
    event.target.reset();
    renderPortfolio();
  });
  document.getElementById("clear-local-portfolio").addEventListener("click", () => {
    saveLocalHoldings([]);
    renderPortfolio();
  });
  renderPortfolio();
}

function renderPortfolio() {
  const rows = mergedHoldings();
  const table = {
    name: "portfolio_combined.csv",
    columns: ["source", "code", "name", "shares_total", "avg_cost", "current_snapshot", "last_add_price", "shares_added_recently", "note"],
    rows,
    row_count: rows.length,
  };
  document.getElementById("portfolio-table").innerHTML = renderTable(table);
}

function markdownItems() {
  try {
    return JSON.parse(localStorage.getItem(LOCAL_MARKDOWN_KEY) || "[]");
  } catch {
    return [];
  }
}

function saveMarkdownItems(items) {
  localStorage.setItem(LOCAL_MARKDOWN_KEY, JSON.stringify(items));
}

function currentMarkdownId() {
  return document.getElementById("markdown-id").value;
}

function createMarkdownItem() {
  const now = new Date().toISOString();
  return {
    id: `md-${Date.now()}`,
    title: "未命名笔记",
    body: "",
    created_at: now,
    updated_at: now,
  };
}

function setupMarkdown() {
  document.getElementById("new-markdown").addEventListener("click", () => {
    const item = createMarkdownItem();
    const items = [item, ...markdownItems()];
    saveMarkdownItems(items);
    loadMarkdownIntoEditor(item);
    renderMarkdownList();
  });
  document.getElementById("markdown-form").addEventListener("submit", (event) => {
    event.preventDefault();
    saveCurrentMarkdown();
  });
  document.getElementById("download-markdown").addEventListener("click", downloadCurrentMarkdown);
  document.getElementById("delete-markdown").addEventListener("click", deleteCurrentMarkdown);

  const items = markdownItems();
  if (items.length) {
    loadMarkdownIntoEditor(items[0]);
  } else {
    loadMarkdownIntoEditor(createMarkdownItem(), false);
  }
  renderMarkdownList();
}

function renderMarkdownList() {
  const items = markdownItems();
  const activeId = currentMarkdownId();
  document.getElementById("markdown-list").innerHTML = items.length
    ? items
        .map(
          (item) => `
            <button class="markdown-item ${item.id === activeId ? "active" : ""}" data-id="${escapeHtml(item.id)}">
              <strong>${escapeHtml(item.title || "未命名笔记")}</strong>
              <span>${escapeHtml(displayDate(item.updated_at || item.created_at))}</span>
            </button>
          `,
        )
        .join("")
    : '<p class="empty">还没有 Markdown 笔记。</p>';
  document.querySelectorAll(".markdown-item").forEach((button) => {
    button.addEventListener("click", () => {
      const item = markdownItems().find((entry) => entry.id === button.dataset.id);
      if (item) loadMarkdownIntoEditor(item);
      renderMarkdownList();
    });
  });
}

function loadMarkdownIntoEditor(item, persist = true) {
  document.getElementById("markdown-id").value = item.id;
  document.getElementById("markdown-title").value = item.title || "";
  document.getElementById("markdown-body").value = item.body || "";
  if (persist && !markdownItems().some((entry) => entry.id === item.id)) {
    saveMarkdownItems([item, ...markdownItems()]);
  }
}

function saveCurrentMarkdown() {
  const id = currentMarkdownId() || `md-${Date.now()}`;
  const now = new Date().toISOString();
  const title = document.getElementById("markdown-title").value.trim() || "未命名笔记";
  const body = document.getElementById("markdown-body").value;
  const items = markdownItems();
  const existing = items.find((item) => item.id === id);
  const next = {
    id,
    title,
    body,
    created_at: existing?.created_at || now,
    updated_at: now,
  };
  saveMarkdownItems([next, ...items.filter((item) => item.id !== id)]);
  loadMarkdownIntoEditor(next, false);
  renderMarkdownList();
}

function deleteCurrentMarkdown() {
  const id = currentMarkdownId();
  if (!id) return;
  const items = markdownItems().filter((item) => item.id !== id);
  saveMarkdownItems(items);
  loadMarkdownIntoEditor(items[0] || createMarkdownItem(), false);
  renderMarkdownList();
}

function downloadCurrentMarkdown() {
  const title = document.getElementById("markdown-title").value.trim() || "untitled";
  const body = document.getElementById("markdown-body").value;
  const filename = `${slugify(title)}.md`;
  const blob = new Blob([`# ${title}\n\n${body}\n`], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function slugify(value) {
  return String(value)
    .trim()
    .replace(/[\\/:*?"<>|]+/g, "-")
    .replace(/\s+/g, "-")
    .slice(0, 80) || "untitled";
}

function displayDate(value) {
  if (!value) return "-";
  return String(value).slice(0, 10);
}

function renderWeekly(weekly) {
  const meta = document.getElementById("weekly-meta");
  const link = document.getElementById("weekly-link");
  const preview = document.getElementById("weekly-preview");
  if (!weekly) {
    meta.textContent = "还没有周报。";
    link.style.display = "none";
    preview.innerHTML = '<p class="empty">暂无周报预览。</p>';
    return;
  }
  meta.textContent = `${weekly.name} · ${weekly.modified}`;
  link.href = weekly.published_path;
  preview.innerHTML = markdownPreview(weekly.text || "");
}

function markdownPreview(text) {
  const lines = text.split("\n");
  const html = [];
  let inTable = false;
  let tableRows = [];
  function flushTable() {
    if (!inTable) return;
    html.push(`<pre>${escapeHtml(tableRows.filter((line) => !/^\|\s*-/.test(line)).slice(0, 18).join("\n"))}</pre>`);
    inTable = false;
    tableRows = [];
  }
  for (const line of lines.slice(0, 220)) {
    if (line.startsWith("|")) {
      inTable = true;
      tableRows.push(line);
      continue;
    }
    flushTable();
    if (line.startsWith("### ")) html.push(`<h3>${escapeHtml(line.slice(4))}</h3>`);
    else if (line.startsWith("## ")) html.push(`<h2>${escapeHtml(line.slice(3))}</h2>`);
    else if (line.startsWith("# ")) html.push(`<h1>${escapeHtml(line.slice(2))}</h1>`);
    else if (line.trim()) html.push(`<p>${escapeHtml(line)}</p>`);
  }
  flushTable();
  return html.join("");
}

function renderFiles(files) {
  document.getElementById("recent-files").innerHTML = (files || [])
    .slice(0, 40)
    .map(
      (file) => `
        <div class="file-item">
          <strong>${escapeHtml(file.name)}</strong>
          <span>${escapeHtml(file.relative_path)}</span>
          <span>${escapeHtml(file.modified)} · ${Math.round(file.size / 1024)} KB</span>
        </div>
      `,
    )
    .join("");
}

async function main() {
  const response = await fetch("./data/site.json");
  siteData = await response.json();
  document.getElementById("generated-at").textContent = siteData.generated_at || "-";
  setupDateSelector();
  setupViewTabs();
  setupPortfolio();
  setupMarkdown();
  renderWeekly(siteData.latest_weekly);
  renderFiles(siteData.recent_exports);
}

main().catch((error) => {
  document.body.innerHTML = `<main><section class="section"><p class="empty">读取静态数据失败：${escapeHtml(error.message)}</p></section></main>`;
});
