"use strict";

const POLL_MS = 2000;
const TABLES = ["customers", "products", "orders", "order_items", "payments", "shipments", "returns"];
const TARGET_INFO = {
  databricks: { label: "Databricks", aws: "Lakehouse, bronze layer (Delta)" },
  sqlserver: { label: "SQL Server", aws: "stands in for Amazon RDS for SQL Server" },
  mongodb: { label: "MongoDB", aws: "stands in for Amazon DocumentDB" },
};
const CHECK_TYPES = [
  ["count", "Row count"],
  ["referential_integrity", "Foreign keys"],
  ["checksum", "Money checksum"],
  ["duplicates", "Duplicate keys"],
  ["sample", "Sampled rows"],
];

const $ = (id) => document.getElementById(id);
let latest = null;
let polling = false;

// ---------- formatting ----------
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function num(value, digits = 0) {
  if (value === null || value === undefined || value === "" || Number.isNaN(Number(value))) return "&ndash;";
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: digits });
}
function bytes(value) {
  if (value === null || value === undefined) return "&ndash;";
  const units = ["B", "KB", "MB", "GB"];
  let v = Number(value), i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(i ? 1 : 0)} ${units[i]}`;
}
function duration(seconds) {
  if (seconds === null || seconds === undefined) return "&ndash;";
  const s = Math.round(Number(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}
function pill(text, kind = "") {
  return `<span class="pill ${kind}">${esc(text)}</span>`;
}
function stateKind(state) {
  return {
    in_sync: "ok", completed: "ok", full_load_completed: "ok", ready: "ok", passed: "ok", streaming: "ok",
    catching_up: "warn", waiting_for_full_load: "warn", running: "warn", full_load: "warn", preparing: "warn",
    freezing: "warn", draining: "warn", validating: "warn", constraints: "warn", pending: "idle",
    error: "bad", failed: "bad", not_configured: "bad", cancelled: "bad", interrupted: "bad", not_ready: "bad",
  }[state] || "idle";
}
function metric(label, value) {
  return `<div class="metric"><div class="label">${esc(label)}</div><div class="value">${value}</div></div>`;
}
function hasError(part) {
  return !part || part.error;
}

// ---------- API ----------
async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const text = await response.text();
  let body;
  try { body = text ? JSON.parse(text) : {}; } catch { body = { detail: text }; }
  if (!response.ok) throw new Error(body.detail || `${response.status} ${response.statusText}`);
  return body;
}

function showMessage(text, isError = false) {
  const box = $("message");
  box.hidden = !text;
  box.textContent = text || "";
  box.className = `message${isError ? " error" : ""}`;
}

async function action(button, fn, successText) {
  button.disabled = true;
  try {
    await fn();
    showMessage(successText);
    await refresh();
  } catch (error) {
    showMessage(error.message, true);
  } finally {
    button.disabled = false;
  }
}

// ---------- renderers ----------
function renderHeader(d) {
  const control = d.control || {};
  $("pill-writes").outerHTML = `<span id="pill-writes" class="pill ${control.writes_frozen ? "bad" : "ok"}">writes: ${control.writes_frozen ? "frozen" : "live"}</span>`;
  const cutover = control.cutover_status || "not_started";
  $("pill-cutover").outerHTML = `<span id="pill-cutover" class="pill ${stateKind(cutover)}">cutover: ${esc(cutover.replace(/_/g, " "))}</span>`;
  $("updated").textContent = `updated ${new Date().toLocaleTimeString()}`;
}

function runTargets(d) {
  const run = d.migration && d.migration.run;
  if (run && run.targets) return run.targets.split(",").filter(Boolean);
  return Object.keys(TARGET_INFO);
}

function renderPipeline(d) {
  const source = hasError(d.source) ? {} : d.source;
  const cdc = hasError(d.cdc) ? { targets: {} } : d.cdc;
  const producer = cdc.producer || {};
  const slot = source.slot || {};

  const sourceCard = `
    <div class="card stage">
      <h2>Source <span class="aws">PostgreSQL 17 &middot; live</span></h2>
      <div class="metrics">
        ${metric("rows (approx.)", num(source.approx_rows))}
        ${metric("writes / s", num(source.writes_per_second, 1))}
        ${metric("CDC slot", slot.exists ? (slot.active ? "active" : "idle") : "missing")}
        ${metric("WAL not yet read", bytes(slot.lag_bytes))}
      </div>
      ${source.error || d.source?.error ? `<p class="muted small">${esc(d.source.error)}</p>` : ""}
    </div>`;

  const streamCard = `
    <div class="card stage">
      <h2>CDC stream <span class="aws">Kinesis (moto)</span></h2>
      <div class="metrics">
        ${metric("producer", producer.state ? pill(producer.state, stateKind(producer.state)) : pill("not started", "idle"))}
        ${metric("events / s", num(producer.events_per_second, 1))}
        ${metric("since run start", num(producer.since_run_start))}
        ${metric("total published", num(producer.events_published))}
      </div>
      ${producer.message ? `<p class="muted small">${esc(producer.message)}</p>` : ""}
    </div>`;

  const targets = runTargets(d).map((name) => {
    const t = cdc.targets[name] || {};
    const info = TARGET_INFO[name] || { label: name, aws: "" };
    return `
      <div class="target-card">
        <h3>${esc(info.label)} ${pill((t.state || "no status").replace(/_/g, " "), stateKind(t.state))}</h3>
        <div class="aws">${esc(info.aws)}</div>
        <div class="metrics">
          ${metric("backlog (events)", num(t.backlog))}
          ${metric("behind", t.seconds_behind === null || t.seconds_behind === undefined ? "&ndash;" : duration(t.seconds_behind))}
          ${metric("applied", num(t.events_applied))}
          ${metric("events / s", num(t.events_per_second, 1))}
        </div>
        ${t.message ? `<p class="muted small">${esc(t.message)}</p>` : ""}
      </div>`;
  }).join("");

  $("pipeline").innerHTML = `
    ${sourceCard}
    <div class="arrow">&rarr;</div>
    ${streamCard}
    <div class="arrow">&rarr;</div>
    <div class="card"><h2>Targets <span class="muted small">CDC appliers</span></h2><div class="targets">${targets}</div></div>`;
}

function renderJobs(d) {
  const m = d.migration;
  if (hasError(m) || !m.run) {
    $("jobs").innerHTML = `<p class="empty">No migration run yet. Pick targets and press <b>Start migration</b>.</p>`;
    $("timing").textContent = "";
    return;
  }
  const run = m.run, t = m.timing || {};
  $("timing").innerHTML = `run #${run.id} &middot; ${pill(run.status.replace(/_/g, " "), stateKind(run.status))} &middot; ${t.workers} worker(s) &middot; ${duration(t.elapsed_seconds)} &middot; ${num(t.rows_per_second)} rows/s`;

  const rows = m.jobs.map((j) => {
    const cls = j.status === "completed" ? "done" : j.status === "failed" ? "failed" : "";
    return `<tr title="${esc(j.error_message || "")}">
      <td>${esc(j.table_name)}</td>
      <td>${esc(TARGET_INFO[j.target]?.label || j.target)}</td>
      <td><div class="bar ${cls}"><span style="width:${Math.min(100, j.percent || 0)}%"></span></div></td>
      <td class="num">${num(j.migrated_rows)} / ${num(j.total_rows)}</td>
      <td class="num">${num(j.rows_per_second)}</td>
      <td class="num">${duration(j.seconds)}</td>
      <td>${pill(j.status, stateKind(j.status))}</td>
    </tr>`;
  }).join("");

  $("jobs").innerHTML = `
    <div class="scroll"><table>
      <thead><tr><th>Table</th><th>Target</th><th>Progress</th><th class="num">Rows</th><th class="num">Rows/s</th><th class="num">Time</th><th>Status</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
    ${run.error_message ? `<p class="failures">${esc(run.error_message)}</p>` : ""}`;
}

function renderTimeline(d) {
  const m = d.migration;
  const jobs = (!hasError(m) && m.jobs || []).filter((j) => j.started_at);
  if (!jobs.length) {
    $("timeline").innerHTML = `<p class="empty">Jobs appear here as they start.</p>`;
    return;
  }
  const spans = jobs.map((j) => {
    const start = new Date(j.started_at).getTime();
    return { j, start, end: start + (Number(j.seconds) || 0) * 1000 };
  });
  const t0 = Math.min(...spans.map((s) => s.start));
  const t1 = Math.max(...spans.map((s) => s.end), t0 + 1000);
  const width = t1 - t0;

  const rows = spans
    .sort((a, b) => a.start - b.start)
    .map(({ j, start, end }) => {
      const left = ((start - t0) / width) * 100;
      const w = Math.max(0.6, ((end - start) / width) * 100);
      return `<div class="tl-row">
        <div>${esc(j.table_name)} &rarr; ${esc(TARGET_INFO[j.target]?.label || j.target)}</div>
        <div class="tl-track"><div class="tl-bar ${esc(j.target)}" style="left:${left}%;width:${w}%" title="${duration(j.seconds)}"></div></div>
      </div>`;
    }).join("");

  $("timeline").innerHTML = `
    <div class="scroll">${rows}</div>
    <div class="tl-axis"><div></div><div><span>0s</span><span>${duration(width / 1000)}</span></div></div>
    <div class="legend">${Object.entries(TARGET_INFO).map(([k, v]) =>
      `<span><i class="tl-bar ${k}" style="position:static;display:inline-block"></i>${esc(v.label)}</span>`).join("")}</div>`;
}

function renderValidation(d) {
  const v = d.validation;
  if (!v || v.error) {
    $("validation").innerHTML = `<p class="empty">${v && v.error ? esc(v.error) : "No validation yet. Press <b>Validate now</b>."}</p>`;
    $("validation-meta").textContent = "";
    return;
  }
  $("validation-meta").innerHTML = `#${v.run_id} &middot; ${pill(v.status, stateKind(v.status))} &middot; ${v.passed_checks}/${v.total_checks} passed &middot; ${v.writes_frozen ? "frozen source" : "live source"}`;

  const targets = (v.targets || "").split(",").filter(Boolean);
  const cell = (target, type, table) => {
    const r = v.results.find((x) => x.target === target && x.check_type === type && x.table_name === table);
    if (!r) return `<td class="cell"></td>`;
    const tip = `${r.check_name}: source ${r.source_value ?? "-"} / target ${r.target_value ?? "-"}${r.details ? " - " + r.details : ""}`;
    return `<td class="cell" title="${esc(tip)}"><span class="dot ${r.status}"></span></td>`;
  };

  const body = targets.map((target) => {
    const connectivity = v.results.find((x) => x.target === target && x.check_type === "connectivity");
    if (connectivity) {
      return `<tr><td>${esc(TARGET_INFO[target]?.label || target)}</td><td colspan="${TABLES.length + 1}" class="failures">${esc(connectivity.details)}</td></tr>`;
    }
    return CHECK_TYPES
      .filter(([type]) => v.results.some((x) => x.target === target && x.check_type === type))
      .map(([type, label], i) => `<tr>
        <td>${i === 0 ? esc(TARGET_INFO[target]?.label || target) : ""}</td>
        <td class="muted">${esc(label)}</td>
        ${TABLES.map((table) => cell(target, type, table)).join("")}
      </tr>`).join("");
  }).join("");

  const failed = v.results.filter((r) => r.status !== "passed").slice(0, 12);
  $("validation").innerHTML = `
    <div class="scroll"><table class="vgrid">
      <thead><tr><th>Target</th><th>Check</th>${TABLES.map((t) => `<th class="cell">${esc(t.replace("_", " "))}</th>`).join("")}</tr></thead>
      <tbody>${body}</tbody>
    </table></div>
    ${failed.length ? `<ul class="failures">${failed.map((r) =>
      `<li><b>${esc(TARGET_INFO[r.target]?.label || r.target)}</b> ${esc(r.check_name)}: source ${esc(r.source_value ?? "-")}, target ${esc(r.target_value ?? "-")}${r.details ? " &middot; " + esc(r.details) : ""}</li>`).join("")}</ul>` : ""}`;
}

function renderReadiness(d) {
  const r = d.readiness;
  if (hasError(r)) {
    $("readiness").innerHTML = `<li class="muted">${esc(r && r.error)}</li>`;
    return;
  }
  const status = $("readiness-status");
  status.className = `pill ${r.status === "ready" ? "ok" : "bad"}`;
  status.textContent = r.status === "ready" ? "ready to cut over" : "not ready";

  $("readiness").innerHTML = r.conditions.map((c) => `
    <li class="${c.ok ? "ok" : "no"}"><span class="mark">${c.ok ? "&#10003;" : "&#10007;"}</span>
      <span>${esc(c.name)}</span><span class="detail">${esc(c.detail || "")}</span></li>`).join("");

  const events = (d.cutover && d.cutover.events) || [];
  $("cutover-log").innerHTML = events.length
    ? events.map((e) => `<li class="${e.status === "failed" ? "failed" : ""}"><b>${esc(e.step)}</b> ${esc(e.status)}${e.message ? " &middot; " + esc(e.message) : ""}</li>`).join("")
    : `<li class="muted">Cutover not started.</li>`;
}

function renderLanding(d) {
  const l = d.landing;
  if (hasError(l)) {
    $("landing").innerHTML = `<p class="empty">${esc(l && l.error)}</p>`;
    $("landing-meta").textContent = "";
    return;
  }
  $("landing-meta").textContent = `s3://${l.bucket}/${l.prefix}`;
  const rows = Object.entries(l.files_per_table || {})
    .map(([table, files]) => `<tr><td>${esc(table)}</td><td class="num">${num(files)}</td></tr>`).join("");
  $("landing").innerHTML = `
    <div class="metrics" style="margin-bottom:10px">
      ${metric("parquet files", num(l.files))}
      ${metric("size", bytes(l.bytes))}
    </div>
    ${rows ? `<table><thead><tr><th>Table</th><th class="num">Files</th></tr></thead><tbody>${rows}</tbody></table>`
           : `<p class="empty">The Databricks full load writes each batch here as Parquet (raw zone) before loading it.</p>`}`;
}

function renderHistory(d) {
  const runs = Array.isArray(d.history) ? d.history : [];
  if (!runs.length) {
    $("history").innerHTML = `<p class="empty">Finished runs are listed here with their timing.</p>`;
    return;
  }
  $("history").innerHTML = `
    <div class="scroll"><table>
      <thead><tr><th>Run</th><th>Targets</th><th class="num">Workers</th><th class="num">Rows</th><th class="num">Full load</th><th class="num">Rows/s</th><th>Status</th></tr></thead>
      <tbody>${runs.map((r) => `<tr>
        <td>#${r.id}</td>
        <td>${esc(r.targets.split(",").map((t) => TARGET_INFO[t]?.label || t).join(", "))}</td>
        <td class="num">${num(r.workers)}</td>
        <td class="num">${num(r.migrated_rows)}</td>
        <td class="num">${duration(r.seconds)}</td>
        <td class="num">${num(r.rows_per_second)}</td>
        <td>${pill(r.status.replace(/_/g, " "), stateKind(r.status))}</td>
      </tr>`).join("")}</tbody>
    </table></div>`;
}

function updateButtons(d) {
  const active = !hasError(d.migration) && d.migration.active;
  const cutoverActive = d.cutover && d.cutover.active;
  $("btn-start").disabled = active || cutoverActive;
  $("btn-resume").disabled = active;
  $("btn-cancel").disabled = !active;
  $("btn-cutover").disabled = active || cutoverActive;
  $("btn-rollback").disabled = cutoverActive;
}

// ---------- main loop ----------
async function refresh() {
  if (polling) return;
  polling = true;
  try {
    const d = await api("/api/dashboard");
    latest = d;
    for (const render of [renderHeader, renderPipeline, renderJobs, renderTimeline, renderValidation,
                          renderReadiness, renderLanding, renderHistory, updateButtons]) {
      try { render(d); } catch (error) { console.error(render.name, error); }
    }
  } catch (error) {
    $("updated").textContent = `backend unreachable: ${error.message}`;
  } finally {
    polling = false;
  }
}

async function init() {
  try {
    const config = await api("/api/config");
    $("workers").value = config.workers_default;
    $("target-picker").innerHTML = config.targets_available.map((t) => `
      <label><input type="checkbox" value="${esc(t)}" ${config.targets_default.includes(t) ? "checked" : ""}>
      ${esc(TARGET_INFO[t]?.label || t)}</label>`).join("");
  } catch (error) {
    showMessage(`Could not load configuration: ${error.message}`, true);
  }

  $("btn-start").onclick = (e) => action(e.target, () => {
    const targets = [...document.querySelectorAll("#target-picker input:checked")].map((i) => i.value);
    return api("/api/migration/start", {
      method: "POST",
      body: JSON.stringify({ targets, workers: Number($("workers").value) || 1, reset: true }),
    });
  }, "Migration started: full load running, CDC is buffering changes.");
  $("btn-resume").onclick = (e) => action(e.target, () => api("/api/migration/resume", { method: "POST" }), "Resuming from the last checkpoints.");
  $("btn-cancel").onclick = (e) => action(e.target, () => api("/api/migration/cancel", { method: "POST" }), "Cancelling after the current batches.");
  $("btn-validate").onclick = (e) => action(e.target, () => api("/api/validation/run", { method: "POST" }), "Validation finished.");
  $("btn-cutover").onclick = (e) => action(e.target, () => api("/api/cutover/start", { method: "POST" }), "Cutover runbook started.");
  $("btn-rollback").onclick = (e) => action(e.target, () => api("/api/cutover/rollback", { method: "POST" }), "Rolled back: writes are live again.");

  await refresh();
  setInterval(refresh, POLL_MS);
}

init();
