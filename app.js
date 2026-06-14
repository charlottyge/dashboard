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

function byId(id) {
  return document.getElementById(id);
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
  const target = byId("view-radar-metrics") || byId("metrics");
  if (!target) return;
  target.innerHTML = metrics
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
  const select = byId("date-select");
  if (!select) return;
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
  const subtitle = byId("timeline-subtitle");
  if (subtitle) {
    subtitle.textContent = activeDay
      ? `${activeDay.date} · ${checkpoints.length} 个 checkpoint`
      : "没有可展示的 checkpoint。";
  }
  const tabs = byId("checkpoint-tabs");
  if (!tabs) return;
  tabs.innerHTML = checkpoints
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
  const target = byId("checkpoint-detail");
  if (!target) return;
  if (!checkpoint) {
    target.innerHTML = '<p class="empty">当前日期没有扫描结果。</p>';
    return;
  }
  const decision = checkpoint.decision || {};
  target.innerHTML = `
    ${renderActionBrief(checkpoint)}
    ${renderCandidateDashboard(checkpoint)}
  `;
  renderCheckpointTables(checkpoint);
  renderPortfolio();
}

function renderActionBrief(checkpoint) {
  const decision = checkpoint.decision || {};
  const demo = checkpoint.demo_analysis || {};
  return `
    <section class="brief brief-conclusion">
      <div class="brief-kicker">${escapeHtml(checkpoint.label)}</div>
      <h2>${escapeHtml(demo.headline || conclusionTitle(decision))}</h2>
      <p>${escapeHtml(demo.verdict || conclusionText(decision))}</p>
      <div class="pill-row">
        <span class="pill">风险偏好：${escapeHtml(value(decision.risk_preference))}</span>
        <span class="pill">主线状态：${escapeHtml(mainlineState(decision))}</span>
        <span class="pill">操作倾向：${escapeHtml(actionBias(decision))}</span>
      </div>
    </section>
    ${renderSkillDemoAnalysis(checkpoint)}
    <div class="brief-two-col">
      <section class="brief">
        <h3>现在最该看</h3>
        ${renderFocusList(decision)}
      </section>
      <section class="brief brief-risk">
        <h3>风险提醒 / 持仓优先级</h3>
        ${renderPortfolioBrief(decision)}
      </section>
    </div>
    <section class="brief">
      <h3>主线状态</h3>
      ${renderMainlineGroups(decision)}
    </section>
    <section class="brief">
      <h3>下一步观察</h3>
      ${renderNextWatch(decision)}
    </section>
  `;
}

function renderSkillDemoAnalysis(checkpoint) {
  const demo = checkpoint.demo_analysis;
  if (!demo) return "";
  return `
    <section class="brief skill-demo">
      <div class="skill-demo-head">
        <div>
          <span class="brief-kicker">Skill 实际流程</span>
          <h3>${escapeHtml(demo.stage || checkpoint.label)}</h3>
          <p>${escapeHtml(demo.goal || "")}</p>
        </div>
      </div>
      <div class="skill-demo-grid">
        ${renderDemoFileList("输入", demo.input_files)}
        ${renderDemoFileList("输出", demo.output_files)}
      </div>
      <div class="skill-demo-grid analysis">
        ${renderDemoBulletList("这个时点的分析", demo.analysis_points)}
        ${renderDemoBulletList("下一步验证", demo.next_questions)}
      </div>
      ${renderDemoNotes(demo.data_notes)}
    </section>
  `;
}

function renderDemoFileList(title, files) {
  const safeFiles = Array.isArray(files) ? files : [];
  return `
    <div class="demo-box">
      <h4>${escapeHtml(title)}</h4>
      ${
        safeFiles.length
          ? `<ul>${safeFiles
              .map(
                (file) => `
                  <li>
                    <strong>${escapeHtml(file.label || file.name)}</strong>
                    <span>${escapeHtml(file.rows)} 行 · ${escapeHtml(file.name)}</span>
                  </li>
                `,
              )
              .join("")}</ul>`
          : '<p class="muted">暂无。</p>'
      }
    </div>
  `;
}

function renderDemoBulletList(title, items) {
  const safeItems = Array.isArray(items) ? items : [];
  return `
    <div class="demo-box">
      <h4>${escapeHtml(title)}</h4>
      ${
        safeItems.length
          ? `<ol>${safeItems.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol>`
          : '<p class="muted">暂无。</p>'
      }
    </div>
  `;
}

function renderDemoNotes(items) {
  const notes = Array.isArray(items) ? items : [];
  if (!notes.length) return "";
  return `<div class="demo-notes">${notes.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>`;
}

function renderDecisionLists(decision) {
  return `
    <div class="decision-grid">
      ${renderItemList("市场情绪", buildMarketEmotionItems(decision), renderEmotionItem)}
      ${renderItemList("确认主线", decision.confirmed_mainlines, renderLineItem)}
      ${renderItemList("走弱方向", decision.weakening_mainlines, renderLineItem)}
      ${renderItemList("新改善方向", decision.new_improving_lines, renderLineItem)}
      ${renderItemList("持仓优先级", decision.portfolio_priority, renderPortfolioPriority)}
      ${renderItemList("下一 checkpoint 看什么", decision.next_checkpoint_watch, renderWatchItem)}
    </div>
  `;
}

function conclusionTitle(decision) {
  return `当前盘面：${value(decision.market_state, "暂无清晰主线")}`;
}

function conclusionText(decision) {
  const focus = (decision.confirmed_mainlines || []).slice(0, 3).map((item) => item.name);
  const weak = (decision.weakening_mainlines || []).slice(0, 3).map((item) => item.name);
  const parts = [];
  if (focus.length) parts.push(`${focus.join("、")}仍在前排，但需要看结构和中军承接。`);
  if (weak.length) parts.push(`${weak.join("、")}走弱或反抽失败，暂时不要当主攻。`);
  if (!parts.length) parts.push("当前没有足够明确的主线，先等下一 checkpoint 的排名、VWAP 和持仓风险信号。");
  parts.push(actionBias(decision) === "等确认" ? "当前适合观察承接，不适合盲目追涨。" : "当前可以继续跟踪强线，但仍以证伪条件为准。");
  return parts.join("");
}

function mainlineState(decision) {
  if ((decision.confirmed_mainlines || []).length && (decision.weakening_mainlines || []).length) return "分化";
  if ((decision.confirmed_mainlines || []).length) return "延续";
  if ((decision.new_improving_lines || []).length) return "切换观察";
  if ((decision.weakening_mainlines || []).length) return "走弱";
  return "不明朗";
}

function actionBias(decision) {
  if (decision.risk_preference === "低") return "等确认";
  if ((decision.do_not_chase || []).length >= 3) return "不追高";
  if ((decision.confirmed_mainlines || []).length) return "看承接";
  return "等待";
}

function renderFocusList(decision) {
  const items = (decision.confirmed_mainlines || []).slice(0, 5);
  if (!items.length) return '<p class="muted">暂无优先方向。</p>';
  return `<ol class="brief-list">${items.map((item) => `<li>${renderHumanLine(item, "focus")}</li>`).join("")}</ol>`;
}

function renderHumanLine(item, mode) {
  const label = humanStage(item);
  const explanation = lineExplanation(item, mode);
  const watch = lineWatch(item);
  return `
    <strong>${escapeHtml(item.name)}</strong>
    <span>${escapeHtml(label)}</span>
    <p>${escapeHtml(explanation)}</p>
    <em>看什么：${escapeHtml(watch)}</em>
  `;
}

function humanStage(item) {
  const map = {
    mainline_candidate: "主线候选",
    confirming: "确认中",
    high_crowding: "拥挤偏高",
    two_day_acceleration: "连续加速",
    rebound_only: "仅反抽",
    late_diffusion: "末端扩散",
    temperature_indicator: "温度计",
    defense_failed: "防守失效",
    downgraded: "已降级",
    watch: "观察",
  };
  const stage = map[item.stage] || item.stage || "观察";
  const structure = item.structure_state ? ` / ${item.structure_state}` : "";
  return `${stage}${structure}`;
}

function lineExplanation(item, mode) {
  if (mode === "weak") {
    if (item.rebound_type === "failed_rebound") return "旧方向反抽失败，今天不要再当主攻。";
    return "方向转弱或排名回落，先作为风险/温度计观察。";
  }
  if (item.crowding_signal === "high_crowding") return "涨幅或前排热度偏高，不能只看排名追。";
  if (item.structure_state === "结构待验证") return "排名靠前，但中军、前排、补涨结构还没完全确认。";
  if (item.structure_state === "结构健康") return "中军、前排和板块宽度较同步，值得继续观察承接。";
  return "仍在前排，下一步重点看是否能维持排名和 VWAP 承接。";
}

function lineWatch(item) {
  if (item.crowding_signal === "high_crowding") return "前排是否冲高回落，中军是否继续站稳 VWAP。";
  if (item.structure_state === "结构待验证") return "下一 checkpoint 是否仍在前 5/前 10，核心股是否站稳 VWAP。";
  return "排名不明显掉队，核心股不跌破 VWAP 或上午低点。";
}

function renderPortfolioBrief(decision) {
  const items = (decision.portfolio_priority || []).slice(0, 6);
  if (!items.length) return '<p class="muted">暂无持仓风险优先级。</p>';
  return `<div class="priority-list">${items.map(renderPriorityCard).join("")}</div>`;
}

function renderPriorityCard(item) {
  const detail = buildPortfolioInsight(item);
  const isP0 = detail.priority === "P0";
  return `
    <article class="priority-card ${isP0 ? "p0" : ""}">
      <div class="priority-topline">
        <strong>${escapeHtml(detail.label)}｜${escapeHtml(detail.stock)}</strong>
        <span>${escapeHtml(detail.type)}</span>
      </div>
      <p>状态：${escapeHtml(detail.status)}</p>
      <p>关键线：${escapeHtml(detail.lines)}</p>
      <p>动作：${escapeHtml(detail.action)}</p>
    </article>
  `;
}

function buildPortfolioInsight(item) {
  const row = findStockContextRow(item.stock);
  const stock = item.stock || row["股票"] || row.name || "-";
  const priority = item.priority || "P3";
  const current = row["当前价"] || row.current_price || "";
  const pct = row["当前涨幅"] || row.pct || row["收盘涨幅"] || "";
  const vwap = row["VWAP上/下"] || row["VWAP状态"] || (row.is_above_vwap === "True" ? "上" : row.is_above_vwap === "False" ? "下" : "");
  const drawdown = row["高点回撤%"] || row["今日高点回撤%"] || "";
  const relative = row.relative_strength_vs_sector || row["是否强于板块"] || "";
  const reason = item.reason && !String(item.reason).includes("按风险条件") ? item.reason : portfolioReasonFromRow(row, item);
  const label = priorityLabel(priority);
  const type = holdingTypeFromRow(row, item);
  const statusParts = [];
  if (reason) statusParts.push(reason);
  if (current) statusParts.push(`当前 ${current}`);
  if (pct) statusParts.push(`涨幅 ${pct}%`);
  if (vwap) statusParts.push(`VWAP ${vwap}`);
  if (drawdown) statusParts.push(`高点回撤 ${drawdown}%`);
  if (relative) statusParts.push(`相对板块 ${relative}`);
  return {
    stock,
    priority,
    label,
    type,
    status: statusParts.join("；") || "暂无明确触发条件，按下一 checkpoint 继续观察。",
    lines: portfolioLines(row, item),
    action: portfolioAction(row, item),
  };
}

function priorityLabel(priority) {
  const map = {
    P0: "P0｜必须处理",
    P1: "P1｜重点观察",
    P2: "P2｜正常持有",
    P3: "P3｜暂不关注",
  };
  return map[priority] || `${priority || "P3"}｜待确认`;
}

function holdingTypeFromRow(row, item) {
  const pct = num(row["当前涨幅"] || row.pct || row["收盘涨幅"]);
  const reason = `${item.reason || ""} ${row["日K形态"] || ""} ${row["走势自然语言"] || ""}`;
  if ((item.priority || "") === "P0" || pct < -3) return "亏损风险仓";
  if (pct >= 6 || reason.includes("强阳") || reason.includes("长上影")) return "高位利润仓";
  if (reason.includes("中线") || reason.includes("thesis")) return "中线观察仓";
  return "短线题材仓";
}

function portfolioReasonFromRow(row, item) {
  if (item.invalid_condition === "是") return "风险条件已触发或接近触发";
  if (row["VWAP上/下"] === "下" || row["VWAP状态"] === "下") return "跌到 VWAP 下方，需要确认是否修复";
  if (num(row["高点回撤%"] || row["今日高点回撤%"]) <= -4) return "冲高回落较明显，需要保护利润或降风险";
  if (row.relative_strength_vs_sector === "False" || row["是否强于板块"] === "否") return "弱于所属板块，逻辑线需要复核";
  return item.reason || "暂无明确触发条件";
}

function portfolioLines(row, item) {
  const trigger = item.trigger_price && !String(item.trigger_price).includes("按风险") ? item.trigger_price : "";
  const current = num(row["当前价"] || row.current_price || "");
  if (trigger) return `修复 VWAP｜风险 ${trigger}｜止损 计划失效线`;
  if (current) {
    const repair = (current * 1.015).toFixed(2);
    const risk = (current * 0.985).toFixed(2);
    const stop = (current * 0.965).toFixed(2);
    if ((item.priority || "") === "P0") return `修复 ${repair}｜风险 ${risk}｜止损 ${stop}`;
    if ((item.priority || "") === "P1") return `强势 ${repair}｜保护 ${risk}｜趋势 ${stop}`;
    return `观察 VWAP｜风险 ${risk}｜失效 ${stop}`;
  }
  return "修复 VWAP｜风险 上午低点｜止损 昨日低点 / 计划失效线";
}

function portfolioAction(row, item) {
  if (item.priority === "P0") return "下一 checkpoint 仍未修复就减仓；跌破止损线不再等待。";
  if (item.priority === "P1") return "重点观察修复线，站回继续看，跌破保护线先降风险。";
  if (item.priority === "P2") return "正常持有观察，尾盘复核 VWAP、板块强弱和逻辑线。";
  return "低优先级，暂不处理，只在尾盘或下个 checkpoint 复核。";
}

function findStockContextRow(stock) {
  const checkpoint = currentCheckpoint();
  const rows = (checkpoint?.tables || []).flatMap((table) => table.rows || []);
  const needle = normalizeStockKey(stock);
  if (!needle) return {};
  return rows.find((row) => {
    const key = normalizeStockKey(row["股票"] || `${row.name || ""} ${row.code || ""}`);
    return key && (key.includes(needle) || needle.includes(key));
  }) || {};
}

function normalizeStockKey(input) {
  return String(input || "").replace(/\s+/g, "").replace(/[^\u4e00-\u9fa5A-Za-z0-9*]/g, "");
}

function actionFromPriority(item) {
  if (item.priority === "P0") return "不补仓，若下一 checkpoint 仍未修复则降风险。";
  if (item.priority === "P1") return "高优先观察，等关键位或 VWAP 结果。";
  if (item.priority === "P2") return "正常持有观察，不因单点波动处理。";
  return "低优先级，暂不处理。";
}

function renderMainlineGroups(decision) {
  const strong = (decision.confirmed_mainlines || []).slice(0, 5);
  const weak = (decision.weakening_mainlines || []).slice(0, 5);
  const improving = (decision.new_improving_lines || []).slice(0, 5);
  return `
    <div class="mainline-groups">
      ${renderMainlineGroup("仍在走强", strong, "strong")}
      ${renderMainlineGroup("走弱 / 不再主攻", weak, "weak")}
      ${renderMainlineGroup("新改善方向", improving, "improving")}
    </div>
  `;
}

function renderMainlineGroup(title, items, mode) {
  if (!items.length) return `<div class="mainline-group"><h4>${escapeHtml(title)}</h4><p class="muted">暂无。</p></div>`;
  return `
    <div class="mainline-group">
      <h4>${escapeHtml(title)}</h4>
      <ul>${items.map((item) => `<li>${renderHumanLine(item, mode)}</li>`).join("")}</ul>
    </div>
  `;
}

function renderNextWatch(decision) {
  const watches = decision.next_checkpoint_watch || [];
  if (!watches.length) return '<p class="muted">暂无下一步观察。</p>';
  return `<ol class="next-watch">${watches.slice(0, 6).map((item) => `<li><strong>${escapeHtml(item)}</strong><p>确认：排名维持、核心股站稳 VWAP。证伪：跌出前排、前排冲高回落或持仓风险继续触发。</p></li>`).join("")}</ol>`;
}

function currentCheckpoint() {
  const checkpoints = activeDay?.checkpoints || [];
  return checkpoints.find((item) => item.id === activeCheckpointId) || checkpoints[0];
}

function renderCheckpointTables(checkpoint) {
  const target = byId("checkpoint-tables");
  if (!target) return;
  const subtitle = byId("tables-subtitle");
  if (subtitle) {
    subtitle.textContent = checkpoint
      ? `${checkpoint.label} · ${checkpoint.directory}`
      : "当前 checkpoint 的原始输出表。";
  }
  target.innerHTML = checkpoint ? (checkpoint.tables || []).map(renderTable).join("") : '<p class="empty">暂无数据表。</p>';
}

function buildMarketEmotionItems(decision) {
  const checkpoint = currentCheckpoint();
  const market = firstTableRow(checkpoint, "market_overview.csv");
  const sectors = tableRows(checkpoint, "market_sector_scan.csv");
  const amount = market["成交额预估"] || market["成交额"] || market["market_amount"] || "";
  const upDown = market["涨跌家数"] || market["up_down_count"] || "";
  const limit = market["涨停/跌停"] || market["limit_up_down_count"] || "";
  const pctParts = [
    market["上证"] ? `上证 ${market["上证"]}%` : "",
    market["创业板"] ? `创业板 ${market["创业板"]}%` : "",
    market["科创50"] ? `科创50 ${market["科创50"]}%` : "",
    market["指数涨幅"] ? `指数 ${market["指数涨幅"]}%` : "",
  ].filter(Boolean);
  const sectorDistribution = summarizeSectorDistribution(sectors);
  const score = marketEmotionScore({ pctParts, amount, upDown, limit, sectors, decision });
  const quality = decision.data_quality || {};
  return [
    { label: "市场状态", value: value(decision.market_state, "暂无") },
    { label: "市场涨幅", value: pctParts.join(" / ") || "-" },
    { label: "成交量", value: amount ? `${formatAmount(amount)} · ${amountPulse(amount)}` : "-" },
    { label: "涨跌数量", value: upDown || "-" },
    { label: "涨停 / 跌停", value: limit || "-" },
    { label: "市场情绪评分", value: score },
    { label: "市场板块分布", value: sectorDistribution },
    { label: "风险偏好", value: value(decision.risk_preference, "暂无") },
    { label: "数据质量", value: quality.fallback_used ? "部分 fallback" : "正常" },
  ];
}

function firstTableRow(checkpoint, tableName) {
  return tableRows(checkpoint, tableName)[0] || {};
}

function tableRows(checkpoint, tableName) {
  const table = (checkpoint?.tables || []).find((item) => item.name === tableName);
  return table?.rows || [];
}

function summarizeSectorDistribution(rows) {
  if (!rows.length) return "-";
  const top = rows.slice(0, 5).map((row) => {
    const name = row["板块"] || row["sector"] || "-";
    const pct = row["涨幅"] || row["板块涨幅"] || "";
    return pct === "" ? name : `${name} ${pct}%`;
  });
  return top.join(" / ");
}

function marketEmotionScore({ upDown, limit, sectors, decision }) {
  let score = 50;
  const [up, down] = parsePair(upDown);
  const [limitUp, limitDown] = parsePair(limit);
  if (up + down > 0) score += ((up - down) / (up + down)) * 25;
  score += Math.min(limitUp, 80) * 0.25;
  score -= Math.min(limitDown, 80) * 0.35;
  const strongSectors = sectors.filter((row) => num(row["涨幅"]) > 1).length;
  score += Math.min(strongSectors, 10);
  if (decision.data_quality?.fallback_used) score -= 5;
  return `${Math.max(0, Math.min(100, Math.round(score)))} / 100`;
}

function parsePair(value) {
  const matches = String(value || "").match(/-?\d+(\.\d+)?/g) || [];
  return [Number(matches[0] || 0), Number(matches[1] || 0)];
}

function num(value) {
  const parsed = Number(String(value || "").replace(/,/g, ""));
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatAmount(value) {
  const amount = num(value);
  if (!amount) return value;
  if (amount >= 1000000000000) return `${(amount / 1000000000000).toFixed(2)} 万亿`;
  if (amount >= 100000000) return `${(amount / 100000000).toFixed(0)} 亿`;
  return String(value);
}

function amountPulse(value) {
  const amount = num(value);
  if (!amount) return "成交未知";
  if (amount >= 1000000000000) return "成交放大";
  if (amount >= 800000000000) return "成交正常";
  return "成交缩小";
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

function candidateRowsForCheckpoint(checkpoint = currentCheckpoint()) {
  const tables = checkpoint?.tables || [];
  const candidateNames = [
    "candidate_first_impact.csv",
    "candidate_scores.csv",
    "candidate_morning_check.csv",
    "candidate_afternoon_restart.csv",
    "candidate_close_confirm.csv",
    "final_stocks.csv",
    "strategy_candidates.csv",
  ];
  const table = candidateNames.map((name) => tables.find((item) => item.name === name)).find(Boolean);
  if (!table) return { rows: [], source: "" };
  return {
    source: tableLabels[table.name.replace(/\.csv$/i, "")] || table.name,
    rows: table.rows || [],
  };
}

function firstImpactCandidates() {
  const { rows } = candidateRowsForCheckpoint();
  return rows.map((row) => ({
    stock: row["股票"] || [row["name"], row["code"]].filter(Boolean).join(" ") || "-",
    sector: row["板块"] || row["匹配板块"] || row["sector"] || "",
    pct: row["当前涨幅"] || row["当前涨幅%"] || row["pct"] || "",
    reason: row["走势自然语言"] || row["命中原因"] || row["setup_pass_reasons"] || row["来源"] || "",
  }));
}

function renderCandidateDashboard(checkpoint) {
  const { rows, source } = candidateRowsForCheckpoint(checkpoint);
  const items = rows.map(candidateInsight);
  return `
    <section class="candidate-dashboard">
      <div class="candidate-header">
        <div>
          <h3>候选 Dashboard</h3>
          <p>${escapeHtml(source || "当前时段候选")} · ${items.length} 条</p>
        </div>
      </div>
      ${
        items.length
          ? `<div class="candidate-grid">${items.map(renderCandidateCard).join("")}</div>`
          : '<p class="empty">当前时段没有候选表。</p>'
      }
    </section>
  `;
}

function renderCandidateCard(item) {
  return `
    <article class="candidate-card risk-${escapeHtml(item.riskLevel)}">
      <div class="candidate-topline">
        <strong>${escapeHtml(item.stock)}</strong>
        <b>${escapeHtml(item.riskLabel)}</b>
      </div>
      <span>${escapeHtml([item.sector, item.pct ? `${item.pct}%` : "", item.vwap ? `VWAP ${item.vwap}` : ""].filter(Boolean).join(" · "))}</span>
      <p>候选原因：${escapeHtml(item.reason)}</p>
      <p>板块：${escapeHtml(item.sector || "未匹配")}</p>
      <p>风险评估：${escapeHtml(item.riskText)}</p>
      <em>${escapeHtml(item.source || "候选")}</em>
    </article>
  `;
}

function candidateInsight(row) {
  const stock = row["股票"] || [row["name"], row["code"]].filter(Boolean).join(" ") || "-";
  const sector = row["板块"] || row["匹配板块"] || row["sector"] || "";
  const pct = row["当前涨幅"] || row["当前涨幅%"] || row["收盘涨幅"] || row["pct"] || "";
  const vwap = row["VWAP上/下"] || row["VWAP状态"] || "";
  const source = row["来源"] || row["来源(缩量回踩/放量突破/watchlist/portfolio)"] || row["策略"] || row["10:30来源"] || "";
  const reason = row["走势自然语言"] || row["命中原因"] || row["setup_pass_reasons"] || source || "当前时段候选";
  const risk = candidateRisk(row);
  return {
    stock,
    sector,
    pct,
    vwap,
    source,
    reason,
    riskLevel: risk.level,
    riskLabel: risk.label,
    riskText: risk.text,
  };
}

function candidateRisk(row) {
  const flags = [];
  const drawdown = num(row["高点回撤%"] || row["今日高点回撤%"]);
  const pct = num(row["当前涨幅"] || row["当前涨幅%"] || row["收盘涨幅"] || row["pct"]);
  const vwap = row["VWAP上/下"] || row["VWAP状态"] || "";
  const candle = row["日K形态"] || "";
  const source = row["来源"] || row["来源(缩量回踩/放量突破/watchlist/portfolio)"] || row["策略"] || "";
  const riskMark = row["风险标记"] || "";
  if (vwap === "下") flags.push("VWAP 下方，承接不足");
  if (drawdown <= -5) flags.push(`高点回撤 ${drawdown}%`);
  if (candle.includes("长上影")) flags.push("长上影，追高风险");
  if (pct >= 9) flags.push("涨幅接近涨停，不能追高");
  if (riskMark && riskMark !== "normal") flags.push(riskMark);
  if (source.includes("watchlist") && !source.includes("放量突破")) flags.push("自选观察，仍需触发条件");
  if (!flags.length) {
    return { level: "low", label: "风险低", text: "未见明显回撤或 VWAP 失守，继续看板块强度和成交确认。" };
  }
  const level = flags.length >= 2 || vwap === "下" || drawdown <= -5 ? "high" : "mid";
  return {
    level,
    label: level === "high" ? "风险高" : "风险中",
    text: flags.join("；"),
  };
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
  if (!byId("portfolio-form")) return;
  const meta = byId("portfolio-meta");
  if (meta) {
    meta.textContent = `portfolio.md：${value(siteData.portfolio?.modified, "未读取")} · 前端保存只存在当前浏览器`;
  }
  byId("portfolio-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const row = {
      code: byId("holding-code").value.trim(),
      name: byId("holding-name").value.trim(),
      shares_total: byId("holding-shares").value,
      avg_cost: byId("holding-cost").value,
      note: byId("holding-note").value.trim(),
    };
    if (!row.code && !row.name) return;
    const rows = localHoldings().filter((item) => String(item.code || item.name) !== String(row.code || row.name));
    rows.push(row);
    saveLocalHoldings(rows);
    event.target.reset();
    renderPortfolio();
  });
  byId("clear-local-portfolio")?.addEventListener("click", () => {
    saveLocalHoldings([]);
    renderPortfolio();
  });
  renderPortfolio();
}

function renderPortfolio() {
  const rows = mergedHoldings();
  const decision = currentCheckpoint()?.decision || {};
  const priorityItems = decision.portfolio_priority || [];
  const table = {
    name: "portfolio_combined.csv",
    columns: ["source", "code", "name", "shares_total", "avg_cost", "current_snapshot", "last_add_price", "shares_added_recently", "note"],
    rows,
    row_count: rows.length,
  };
  const target = byId("portfolio-table");
  if (target) {
    target.innerHTML = `
      <div class="portfolio-priority-panel">
        <h3>当前 checkpoint 持仓处理</h3>
        ${priorityItems.length ? `<div class="priority-list">${priorityItems.slice(0, 8).map(renderPriorityCard).join("")}</div>` : '<p class="empty">当前 checkpoint 暂无持仓优先级。</p>'}
      </div>
      ${renderTable(table)}
    `;
  }
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
  return byId("markdown-id")?.value || "";
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
  if (!byId("markdown-form")) return;
  byId("new-markdown")?.addEventListener("click", () => {
    const item = createMarkdownItem();
    const items = [item, ...markdownItems()];
    saveMarkdownItems(items);
    loadMarkdownIntoEditor(item);
    renderMarkdownList();
  });
  byId("markdown-form").addEventListener("submit", (event) => {
    event.preventDefault();
    saveCurrentMarkdown();
  });
  byId("download-markdown")?.addEventListener("click", downloadCurrentMarkdown);
  byId("delete-markdown")?.addEventListener("click", deleteCurrentMarkdown);

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
  const target = byId("markdown-list");
  if (!target) return;
  target.innerHTML = items.length
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
  if (byId("markdown-id")) byId("markdown-id").value = item.id;
  if (byId("markdown-title")) byId("markdown-title").value = item.title || "";
  if (byId("markdown-body")) byId("markdown-body").value = item.body || "";
  if (persist && !markdownItems().some((entry) => entry.id === item.id)) {
    saveMarkdownItems([item, ...markdownItems()]);
  }
}

function saveCurrentMarkdown() {
  const id = currentMarkdownId() || `md-${Date.now()}`;
  const now = new Date().toISOString();
  const title = byId("markdown-title")?.value.trim() || "未命名笔记";
  const body = byId("markdown-body")?.value || "";
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
  const title = byId("markdown-title")?.value.trim() || "untitled";
  const body = byId("markdown-body")?.value || "";
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
  const meta = byId("weekly-meta");
  const link = byId("weekly-link");
  const preview = byId("weekly-preview");
  if (!meta || !link || !preview) return;
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
  const target = byId("recent-files");
  if (!target) return;
  target.innerHTML = (files || [])
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
  if (byId("generated-at")) byId("generated-at").textContent = siteData.generated_at || "-";
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
