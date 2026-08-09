const byId = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(
  /[&<>"']/g,
  (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character],
);

const STATUS_ZH = {
  accepted: "已接受",
  active: "进行中",
  blocked: "受阻",
  clean: "干净",
  complete: "已完成",
  completed: "已完成",
  critical: "严重",
  degraded: "降级",
  dismissed: "已忽略",
  failed: "失败",
  green: "正常",
  healthy: "健康",
  initialized: "已初始化",
  in_progress: "进行中",
  offline: "未启用",
  open: "待处理",
  pending: "等待中",
  planned: "已规划",
  provisional: "临时证据",
  recommended: "建议采用",
  red: "异常",
  rejected: "已拒绝",
  stable: "稳定",
  supported: "支持",
  unknown: "未知",
  verified: "已验证",
  yellow: "需关注",
};

const PHASE_ZH = {
  charter: "目标定义",
  discovery: "调研",
  design: "方案设计",
  implementation: "实现",
  validation: "验证",
  communication: "结果整理",
  "hardware-integration": "硬件集成",
};

function translateStatus(value) {
  const raw = String(value || "unknown");
  return STATUS_ZH[raw.toLowerCase()] || raw;
}

function statusClass(value = "") {
  const raw = String(value).toLowerCase();
  if (/pass|complete|supported|green|verified|active|clean|healthy|accepted|stable|calibrated/.test(raw)) {
    return "green";
  }
  if (/fail|reject|blocked|red|stop|critical|overdue|degrad|open-circuit/.test(raw)) {
    return "red";
  }
  return "yellow";
}

function label(record, fallback = "未命名事项") {
  return record.public_label
    || record.name
    || record.semantic_name
    || record.title
    || record.purpose
    || record.slug
    || fallback;
}

function item(title, description, metadata = "", right = "") {
  return `
    <article class="item">
      <div class="row">
        <div class="name">${escapeHtml(title)}</div>
        <div>${right}</div>
      </div>
      ${description ? `<div class="desc">${escapeHtml(description)}</div>` : ""}
      ${metadata ? `<div class="meta">${escapeHtml(metadata)}</div>` : ""}
    </article>`;
}

function formatBytes(value) {
  let number = Number(value || 0);
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let index = 0;
  while (number >= 1024 && index < units.length - 1) {
    number /= 1024;
    index += 1;
  }
  return `${number.toFixed(index ? 1 : 0)} ${units[index]}`;
}

function formatMoney(value) {
  if (value === null || value === undefined) return "—";
  return Number(value).toFixed(2);
}

function formatTime(value) {
  if (!value) return "未记录";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString("zh-CN");
}

function renderHeader(data) {
  const status = data.status || {};
  byId("title").textContent = data.meta?.title || "ResearchOps 项目看板";
  byId("objective").textContent = status.objective || "尚未登记项目目标";
  byId("phase").innerHTML = `阶段：<b>${escapeHtml(PHASE_ZH[status.phase] || status.phase || "未知")}</b>`;
  byId("health").innerHTML = `健康度：<b class="${statusClass(status.health)}">${escapeHtml(translateStatus(status.health))}</b>`;
  byId("updated").textContent = `更新时间：${formatTime(data.meta?.updated_at)}`;
  byId("gate").textContent = status.next_gate || "尚未定义下一道验证关口";
}

function renderStatus(data) {
  const status = data.status || {};
  const intake = data.onboarding || {};
  const inference = intake.inference || {};
  const inventory = intake.inventory || {};
  const memory = data.memory || {};
  const layers = (memory.layers || []).map((row) => `${row.layer}: ${row.count}`).join(" · ");
  const progress = Math.max(0, Math.min(100, Number(status.progress || 0)));

  byId("status").innerHTML = [
    item("当前工作重点", status.focus || "尚未设置", `负责人：${status.owner || "未指定"}`),
    item(
      "项目接入状态",
      `模式：${intake.adoption_mode || "未记录"}；推断阶段：${PHASE_ZH[inference.phase] || inference.phase || status.phase || "未知"}；置信度：${inference.confidence ?? "—"}`,
      `${inventory.file_count || 0} 个文件已扫描 · ${intake.requires_agent_review ? "仍需代理审阅" : "初始化完成"}`,
    ),
    item(
      "项目记忆",
      memory.available ? `${memory.active || 0} 条有效记忆` : "尚未初始化，可选功能",
      memory.available ? `${layers || "暂无分层"} · 上次同步 ${formatTime(memory.last_sync?.completed_at)}` : "不影响代码、实验和硬件主闭环",
    ),
    item("当前阻塞或不确定性", status.blocking_uncertainty || "没有登记阻塞项", `ResearchOps ${data.meta?.suite_version || "—"}`),
    item(
      "总体进度",
      `${progress}%（这是项目登记值，不替代逐项验收）`,
      "进度只有在证据和下一道关口更新时才应变化",
      `<span class="score">${progress}%</span><div class="bar"><i style="width:${progress}%"></i></div>`,
    ),
  ].join("");
}

function renderActions(data) {
  const archivedStatuses = new Set(["complete", "completed", "dismissed"]);
  const actions = (data.human_actions || []).filter(
    (entry) => !entry.archived
      && !archivedStatuses.has(String(entry.status || "open").toLowerCase()),
  );
  byId("actions-count").textContent = `${actions.length} 项`;
  byId("actions").innerHTML = actions.map((entry) => item(
    label(entry),
    entry.detail || "完成后请通知代理，以便继续自动验证。",
    `优先级：${entry.priority || "normal"} · 负责人：${entry.owner || "human"} · 状态：${translateStatus(entry.status || "open")}`,
    `<span class="${statusClass(entry.priority === "high" ? "red" : "yellow")}">●</span>`,
  )).join("") || item("目前无需人工介入", "代理仍有可以自主完成的工作。", "如果出现新的硬件或权限操作，会在这里明确列出。", '<span class="green">●</span>');
}

function renderExperiments(data) {
  const experiments = data.experiments || [];
  byId("experiments-count").textContent = `${experiments.length} 项`;
  if (!experiments.length) {
    byId("experiments").innerHTML = item("尚无登记实验", "实验启动后会显示目的、状态、结果和工件位置。");
    return;
  }
  byId("experiments").innerHTML = `
    <table>
      <thead><tr><th>实验</th><th>目的/阻塞</th><th>状态</th><th>结果</th><th>路径</th></tr></thead>
      <tbody>${experiments.map((entry) => `
        <tr>
          <td>${escapeHtml(label(entry))}</td>
          <td>${escapeHtml(entry.purpose || entry.summary || entry.blocker || "—")}</td>
          <td class="${statusClass(entry.status)}">${escapeHtml(translateStatus(entry.status || "unknown"))}</td>
          <td>${escapeHtml(entry.result || "尚无结果")}</td>
          <td><code>${escapeHtml(entry.path || "—")}</code></td>
        </tr>`).join("")}</tbody>
    </table>`;
}

function renderEvidence(data) {
  const evidence = data.evidence || [];
  byId("evidence-count").textContent = `${evidence.length} 条`;
  byId("evidence").innerHTML = evidence.map((entry) => item(
    label(entry),
    entry.summary || "该条目已经登记，但尚未补充详细摘要。",
    `状态：${translateStatus(entry.status)} · 类型：${entry.kind || "证据"}`,
    `<span class="${statusClass(entry.status)}">${escapeHtml(entry.coverage ?? "●")}</span>`,
  )).join("") || item("尚未登记证据", "需要通过证据协议绑定测试、数据、工件或硬件观测。", "没有登记不代表结论已被否定，只代表当前不能证明。", '<span class="yellow">●</span>');
}

function renderIntelligence(data) {
  const intelligence = data.model_intelligence || {};
  const decisions = intelligence.recent_decisions || [];
  const outcomes = intelligence.recent_outcomes || [];
  const models = intelligence.model_summary || [];
  const warmup = intelligence.warmup || [];
  const endpoints = intelligence.endpoint_health || [];
  byId("intelligence-count").textContent = intelligence.available ? `${models.length} 个模型` : "未启用";

  if (!intelligence.available) {
    byId("intelligence").innerHTML = item(
      "模型调度数据库未初始化",
      "这项能力是可选的；不影响当前项目代码、训练或硬件实验。",
      "初始化后才会展示模型偏好、成本、质量、漂移与端点健康。",
    );
    return;
  }

  let html = "";
  const recent = decisions[0]?.summary_json || decisions[0] || {};
  if (recent.primary) {
    html += item(
      "当前推荐执行配置",
      recent.primary.model_id || recent.selected_arm_id || "—",
      (recent.visible_reason || []).join(" · ") || "未记录推荐理由",
      `<span class="score">${escapeHtml(recent.primary.uncertainty || "")}</span>`,
    );
  }
  html += outcomes.slice(0, 3).map((entry) => {
    const task = entry.task_json || {};
    return item(
      task.objective || `${task.operation || "工作单元"} · ${entry.work_unit_id || entry.task_id || "—"}`,
      `${entry.execution_arm_id} · ${entry.accepted ? "结果已接受" : "结果未接受"} · 已验证进展 ${Math.round(100 * Number(entry.verified_progress || 0))}%`,
      `成本 ${formatMoney(entry.cost_amount)} ${entry.currency || ""} · 质量 ${Number(entry.quality || 0).toFixed(2)} · ${formatTime(entry.occurred_at)}`,
      `<span class="${statusClass(entry.accepted ? "accepted" : "failed")}">${entry.accepted ? "✓" : "!"}</span>`,
    );
  }).join("");
  html += warmup.slice(0, 4).map((entry) => item(
    `${entry.execution_arm_id} · ${entry.operation}`,
    `项目适配进度 ${Math.round(100 * Number(entry.calibration_progress || entry.rootedness || 0))}%`,
    `${translateStatus(entry.status)} · 本地样本 ${entry.local_observations || 0} · 继承等效样本 ${entry.inherited_equivalent_observations || 0}`,
    `<span class="${statusClass(entry.status)}">${escapeHtml(translateStatus(entry.status))}</span>`,
  )).join("");
  html += models.slice(0, 4).map((entry) => item(
    entry.execution_arm_id,
    `成功率 ${entry.success == null ? "—" : Number(entry.success).toFixed(2)} · 已验证进展 ${entry.verified_progress == null ? "—" : Number(entry.verified_progress).toFixed(2)} · ${entry.observations || 0} 条观测`,
    `成本中位数 ${formatMoney(entry.cost_median)} ${entry.currency || ""} · 质量 ${entry.quality == null ? "—" : Number(entry.quality).toFixed(2)} · 漂移 ${entry.drift_status || "未知"}`,
  )).join("");
  html += endpoints.slice(0, 3).map((entry) => item(
    `服务端点 ${entry.endpoint_id}`,
    `成功率 ${Number(entry.success_rate || 0).toFixed(2)} · 平均延迟 ${Number(entry.latency_mean || 0).toFixed(1)} 秒`,
    `最近观测：${formatTime(entry.last_seen)}`,
    `<span class="${statusClass((entry.success_rate || 0) >= 0.85 ? "healthy" : (entry.success_rate || 0) >= 0.55 ? "degraded" : "open-circuit")}">●</span>`,
  )).join("");
  byId("intelligence").innerHTML = html;
}

function renderRoutes(data) {
  const routes = data.routes || [];
  byId("routes-count").textContent = `${routes.length} 条`;
  byId("routes").innerHTML = routes.map((entry) => item(
    label(entry),
    entry.hypothesis || entry.summary || "尚未记录可证伪假设。",
    `状态：${translateStatus(entry.status)} · 停止条件：${entry.kill_criterion || "未定义"}`,
    `<span class="score">${escapeHtml(entry.score ?? "—")}</span>`,
  )).join("") || item("目前没有候选路线", "需要比较多个可证伪方案时再启用路线评估；不要为了填满页面而保留无价值分支。");
}

function renderDecisions(data) {
  const entries = [...(data.decisions || []), ...(data.risks || [])];
  byId("decisions-count").textContent = `${entries.length} 项`;
  byId("decisions").innerHTML = entries.map((entry) => item(
    label(entry),
    entry.rationale || entry.mitigation || "尚未补充理由或缓解措施。",
    `状态/严重度：${translateStatus(entry.status || entry.severity)} · 负责人：${entry.owner || "未指定"}`,
  )).join("") || item("尚无登记决策或风险", "重要取舍应记录理由；可恢复的小实现不必制造额外流程负担。");
}

function renderStorage(data) {
  const storage = data.storage || {};
  const worktrees = storage.worktrees || [];
  byId("storage-count").textContent = formatBytes(storage.total_bytes || 0);
  byId("storage").innerHTML = item(
    "工件空间概览",
    `总计 ${formatBytes(storage.total_bytes || 0)}；候选清理 ${formatBytes(storage.cleanup_candidate_bytes || 0)}`,
    `${storage.large_files || 0} 个大文件 · 上次扫描 ${formatTime(storage.last_scan)}`,
  ) + worktrees.map((entry) => item(
    entry.name || entry.path,
    entry.purpose || "未记录用途",
    `${translateStatus(entry.status)} · 租约到期 ${entry.lease_expires || "—"}`,
    `<span class="${statusClass(entry.status)}">${escapeHtml(entry.dirty ? "有未提交改动" : "干净")}</span>`,
  )).join("");
}

function renderSecondary(data) {
  const proposals = data.capability_proposals || [];
  byId("proposals-count").textContent = `${proposals.filter((entry) => !["dismissed", "completed"].includes(entry.status)).length} 项`;
  byId("proposals").innerHTML = proposals.map((entry) => item(
    `${entry.skill || "能力"}${entry.mode ? ` / ${entry.mode}` : ""}`,
    entry.benefit || entry.reason || "尚未补充收益说明。",
    `${translateStatus(entry.status || "recommended")} · 审批：${entry.approval || "需要"}`,
    `<span class="${statusClass(entry.status === "approved" ? "green" : entry.activation === "explicit_only" ? "red" : "yellow")}">${escapeHtml(entry.context_cost || "")}</span>`,
  )).join("") || item("没有待处理建议", "当前没有需要额外授权的新能力或安全措施。", "这不代表所有项目风险已经关闭。");

  const hygiene = data.hygiene || {};
  const hygieneItems = hygiene.items || [];
  byId("hygiene-count").textContent = `${hygiene.open_items || 0} 项`;
  byId("hygiene").innerHTML = item(
    "仓库状态摘要",
    `${hygiene.open_items || 0} 个待审项；${hygiene.bare_public_ids || 0} 个裸露内部标识`,
    `${hygiene.temporary_tests || 0} 个临时测试 · 上次扫描 ${formatTime(hygiene.last_scan)}`,
  ) + hygieneItems.map((entry) => item(
    label(entry),
    entry.detail || "未记录细节",
    `${entry.kind || "检查项"} · ${translateStatus(entry.status || "open")}`,
    `<span class="${statusClass(entry.severity || entry.status)}">●</span>`,
  )).join("");

  const literature = data.literature || {};
  const literatureItems = literature.items || [];
  byId("literature-count").textContent = `${literature.included || 0}/${literature.screened || 0}`;
  byId("literature").innerHTML = item(
    "资料筛选进度",
    `已筛选 ${literature.screened || 0} 篇；纳入 ${literature.included || 0} 篇`,
    `${literature.queries || 0} 组检索式`,
  ) + literatureItems.map((entry) => item(
    label(entry),
    entry.relevance || "尚未记录与本项目的关系。",
    `${entry.year || "年份未知"} · ${translateStatus(entry.status)}`,
  )).join("");

  const logs = data.logs || [];
  byId("logs-count").textContent = `${logs.length} 条`;
  byId("logs").innerHTML = logs.map((entry) => item(
    entry.event || entry.text || "未命名事件",
    entry.detail || "",
    `${formatTime(entry.at)} · 执行者：${entry.actor || "未知"}`,
  )).join("") || item("尚无关键记录", "这里只保留影响决策的摘要，不保存大段终端输出。", "原始证据应由工件路径和哈希引用。");
}

function render(data) {
  renderHeader(data);
  renderStatus(data);
  renderActions(data);
  renderExperiments(data);
  renderEvidence(data);
  renderIntelligence(data);
  renderRoutes(data);
  renderDecisions(data);
  renderStorage(data);
  renderSecondary(data);
}

async function refresh() {
  try {
    const response = await fetch(`view.json?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    render(await response.json());
    byId("error").style.display = "none";
  } catch (error) {
    byId("error").style.display = "block";
    byId("error").textContent = `无法加载项目状态：${error}。请确认 Dashboard 服务仍在运行。`;
  }
}

refresh();
setInterval(refresh, 10000);
