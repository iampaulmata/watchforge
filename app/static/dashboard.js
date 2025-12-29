const WARN_PCT = window.DASHBOARD_WARN_PCT || 80;

function formatTime(tsSeconds) {
  if (!tsSeconds) return "—";
  const d = new Date(tsSeconds * 1000);
  return d.toLocaleString();
}

function formatBytes(bytes) {
  if (bytes == null || Number.isNaN(Number(bytes))) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = Number(bytes);
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v >= 10 ? 0 : 1)} ${units[i]}`;
}

function formatPct(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `${Number(v).toFixed(1)}%`;
}

function clampPct(v) {
  const n = Number(v);
  if (Number.isNaN(n)) return null;
  return Math.max(0, Math.min(100, n));
}

function severityClass(pct) {
  const p = clampPct(pct);
  if (p == null) return "";
  if (p >= 95) return "danger";
  if (p >= WARN_PCT) return "warn";
  return "ok";
}

function setTextWithSeverity(el, text, pct) {
  if (!el) return;
  el.textContent = text;
  el.classList.remove("ok", "warn", "bad");
  const sev = severityClass(pct);
  if (sev === "danger") el.classList.add("bad");
  else if (sev === "warn") el.classList.add("warn");
  else if (sev === "ok") el.classList.add("ok");
}

function setBar(fillEl, pct) {
  if (!fillEl) return;
  const p = clampPct(pct);
  fillEl.style.width = (p == null ? 0 : p) + "%";
  fillEl.classList.remove("warn", "danger");
  if (p != null && p >= 95) fillEl.classList.add("danger");
  else if (p != null && p >= WARN_PCT) fillEl.classList.add("warn");
}

function setSummary(summary) {
  const text = document.getElementById("summary-text");
  const dot = document.getElementById("summary-dot");
  const pill = document.getElementById("summary-pill");

  const { total, up, down, checked_at } = summary;
  text.textContent = `${up}/${total} up • ${down} down • ${formatTime(checked_at)}`;

  dot.classList.remove("up", "down", "neutral");
  if (down > 0) dot.classList.add("down");
  else if (up === total && total > 0) dot.classList.add("up");
  else dot.classList.add("neutral");

  pill.title = `Last checked: ${formatTime(checked_at)}`;
  document.getElementById("footer-time").textContent = `Last update: ${formatTime(checked_at)}`;
}

function updateHealthCard(result) {
  const card = document.querySelector(`[data-service-id="${result.id}"]`);
  if (!card) return;

  const dot = card.querySelector("[data-dot]");
  const badge = card.querySelector("[data-badge]");
  const latency = card.querySelector("[data-latency]");
  const lastcheck = card.querySelector("[data-lastcheck]");
  const errorRow = card.querySelector("[data-error-row]");
  const errorText = card.querySelector("[data-error]");

  dot.classList.remove("up", "down", "neutral");
  badge.classList.remove("up", "down");

  if (result.ok) {
    dot.classList.add("up");
    badge.classList.add("up");
    badge.textContent = `UP${result.status_code ? " • " + result.status_code : ""}`;
    if (errorRow) errorRow.style.display = "none";
  } else {
    dot.classList.add("down");
    badge.classList.add("down");
    badge.textContent = `DOWN${result.status_code ? " • " + result.status_code : ""}`;
    if (errorRow) {
      errorRow.style.display = "";
      errorText.textContent = result.error || "Unknown error";
    }
  }

  latency.textContent = (result.latency_ms != null) ? `${result.latency_ms} ms` : "—";
  lastcheck.textContent = result.checked_at ? formatTime(result.checked_at) : "—";
}

async function fetchHealth() {
  const res = await fetch("/api/health", { cache: "no-store" });
  if (!res.ok) throw new Error(`Health HTTP ${res.status}`);
  const data = await res.json();

  setSummary(data.summary);
  for (const r of data.results) updateHealthCard(r);
}

/* -------- Host grouping -------- */

function groupCardsByHost() {
  const root = document.getElementById("cards-root");
  const cards = Array.from(root.querySelectorAll(".card"));

  // Build groups
  const groups = new Map(); // host -> [cards]
  for (const c of cards) {
    const host = (c.dataset.beszelHost || "Unknown").trim();
    if (!groups.has(host)) groups.set(host, []);
    groups.get(host).push(c);
  }

  // Clear root and rebuild sections
  root.innerHTML = "";

  // Sort hosts alphabetically for predictability
  const hosts = Array.from(groups.keys()).sort((a, b) => a.localeCompare(b));
  for (const host of hosts) {
    const section = document.createElement("section");
    section.className = "host-group";
    section.dataset.hostGroup = host;

    const header = document.createElement("div");
    header.className = "host-header";
    header.innerHTML = `
      <div class="host-title">
        <span class="host-badge">Host</span>
        <strong>${host}</strong>
      </div>
      <div class="host-kpis">
        <span class="kpi">CPU: <span class="mono" data-host-kpi-cpu>—</span></span>
        <span class="kpi">RAM: <span class="mono" data-host-kpi-ram>—</span></span>
      </div>
    `;

    const grid = document.createElement("div");
    grid.className = "host-grid";

    for (const c of groups.get(host)) grid.appendChild(c);

    section.appendChild(header);
    section.appendChild(grid);
    root.appendChild(section);
  }
}

/* -------- Metrics -------- */

function parseUptime(value) {
  // Best-effort:
  // - numeric seconds
  // - already-human strings like "Up 7 days"
  if (value == null) return null;
  if (typeof value === "string") return value;
  if (typeof value === "number") {
    const s = Math.max(0, Math.floor(value));
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (d > 0) return `Up ${d}d ${h}h`;
    if (h > 0) return `Up ${h}h ${m}m`;
    return `Up ${m}m`;
  }
  return null;
}

function updateMetricsCard(serviceId, system, container) {
  const card = document.querySelector(`[data-service-id="${serviceId}"]`);
  if (!card) return;

  const hostCpuEl = card.querySelector("[data-host-cpu]");
  const hostRamEl = card.querySelector("[data-host-ram]");
  const hostMemPctEl = card.querySelector("[data-host-mem-pct]");
  const hostMemBarEl = card.querySelector("[data-host-mem-bar]");

  const ctrStatusEl = card.querySelector("[data-ctr-status]");
  const ctrUptimeEl = card.querySelector("[data-ctr-uptime]");
  const ctrCpuEl = card.querySelector("[data-ctr-cpu]");
  const ctrRamEl = card.querySelector("[data-ctr-ram]");

  // Host CPU
  const cpu = system?.cpu;
  setTextWithSeverity(hostCpuEl, formatPct(cpu), cpu);

  // Host RAM used/total
  const mu = system?.mem_used;
  const mt = system?.mem_total;
  if (mu != null && mt != null) {
    hostRamEl.textContent = `${formatBytes(mu)} / ${formatBytes(mt)}`;
  } else {
    hostRamEl.textContent = "—";
  }

  // Host RAM percent (mp)
  const mp = system?.mem_percent;
  setTextWithSeverity(hostMemPctEl, (mp != null ? `${Number(mp).toFixed(1)}%` : "—"), mp);
  setBar(hostMemBarEl, mp);

  // Container state/health line
  ctrStatusEl.textContent = container?.state ?? "—";

  // Uptime (already a string like "Up 7 days")
  ctrUptimeEl.textContent = container?.uptime ?? "—";

  // Container RAM: Beszel containers.memory appears to be % in your instance
  const cMem = container?.mem_used;
  ctrRamEl.textContent = formatBytes(cMem);

  // Container CPU
  const cCpu = container?.cpu;
  setTextWithSeverity(ctrCpuEl, formatPct(cCpu), cCpu);}

function updateHostKpis(metricsResults) {
  // Build host-level KPIs (average CPU + RAM%) from the metrics we already have
  const hostAgg = new Map(); // host -> {cpuSum,count, mpSum, mpCount, memUsedSum, memTotalSum}
  for (const r of metricsResults) {
    const host = r.beszel_host;
    if (!hostAgg.has(host)) hostAgg.set(host, { cpuSum:0, cpuCount:0, mpSum:0, mpCount:0, mu:0, mt:0 });
    const agg = hostAgg.get(host);

    if (r.system?.cpu != null) { agg.cpuSum += Number(r.system.cpu); agg.cpuCount++; }
    if (r.system?.mem_percent != null) { agg.mpSum += Number(r.system.mem_percent); agg.mpCount++; }
    if (r.system?.mem_used != null) agg.mu += Number(r.system.mem_used);
    if (r.system?.mem_total != null) agg.mt += Number(r.system.mem_total);
  }

  document.querySelectorAll("[data-host-group]").forEach(section => {
    const host = section.dataset.hostGroup;
    const agg = hostAgg.get(host);
    const cpuEl = section.querySelector("[data-host-kpi-cpu]");
    const ramEl = section.querySelector("[data-host-kpi-ram]");
    if (!agg) return;

    const cpuAvg = agg.cpuCount ? (agg.cpuSum / agg.cpuCount) : null;
    cpuEl.textContent = formatPct(cpuAvg);

    // Prefer mem% if we have it; else compute from used/total
    let mp = agg.mpCount ? (agg.mpSum / agg.mpCount) : null;
    if (mp == null && agg.mt > 0) mp = (agg.mu / agg.mt) * 100.0;
    ramEl.textContent = mp == null ? "—" : `${mp.toFixed(1)}%`;
  });
}

async function fetchMetrics() {
  const res = await fetch("/api/metrics", { cache: "no-store" });
  if (!res.ok) throw new Error(`Metrics HTTP ${res.status}`);
  const data = await res.json();

  if (Array.isArray(data.results)) {
    for (const r of data.results) {
      updateMetricsCard(r.id, r.system, r.container);
    }
    updateHostKpis(data.results);
  }

  if (Array.isArray(data.errors) && data.errors.length) {
    console.warn("Beszel metric warnings:", data.errors);
  }
}

/* -------- Dozzle logs -------- */

function openDozzleLogs(dozzleBase, containerName) {
  const base = (dozzleBase || "").replace(/\/$/, "");
  if (!base || !containerName) return;
  const url = `${base}/show?name=${encodeURIComponent(containerName)}`;
  window.open(url, "_blank", "noopener");
}

document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-logs]");
  if (!btn) return;

  e.preventDefault();
  e.stopPropagation();

  const card = btn.closest(".card");
  if (!card) return;

  openDozzleLogs(card.dataset.dozzleBase, card.dataset.beszelContainer);
});

/* -------- Refresh loop -------- */

async function refreshAll() {
  try { await fetchHealth(); }
  catch (e) {
    const text = document.getElementById("summary-text");
    const dot = document.getElementById("summary-dot");
    text.textContent = `Health API error: ${e.message}`;
    dot.classList.remove("up", "down", "neutral");
    dot.classList.add("down");
    console.warn(e);
  }

  try { await fetchMetrics(); }
  catch (e) { console.warn("Metrics fetch failed:", e.message); }
}

document.getElementById("refresh-btn").addEventListener("click", refreshAll);

// Build host groups once on load (cards exist already)
groupCardsByHost();

// Initial load + polling
refreshAll();
setInterval(refreshAll, window.DASHBOARD_POLL_MS || 5000);

function applyThemePreview(tokens){
  const root = document.documentElement;
  Object.entries(tokens).forEach(([k,v])=>{
    root.style.setProperty(k, v);
  });
}
