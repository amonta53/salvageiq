// =========================================================
// script.js
// SalvageIQ front-end behavior
// =========================================================

const form        = document.getElementById("lookupForm");
const submitBtn   = document.getElementById("submitBtn");
const statusText  = document.getElementById("statusText");
const summary     = document.getElementById("summary");
const results     = document.getElementById("results");
const caveats     = document.getElementById("caveats");
const jobProgress = document.getElementById("jobProgress");

let _pollTimer = null;

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  _stopPolling();
  setLoading(true);
  clearOutput();

  const payload = buildPayload();

  try {
    const response = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Search failed.");
    }

    if (data.mode === "cache") {
      renderCacheBadge(data.cache_status, data.scraped_at);
      renderVehicle(data.vehicle);
      renderResults(data.items || []);
      setLoading(false);
      if (data.refresh_job_id) {
        _pollStatus(data.refresh_job_id, /* silent */ true);
      }
    } else {
      // mode === "job"
      renderVehicle(data.vehicle);
      _pollStatus(data.job_id, /* silent */ false);
    }

  } catch (error) {
    results.innerHTML = `<div class="alert alert-danger rounded-4">${escapeHtml(error.message)}</div>`;
    setLoading(false);
  }
});

// =========================================================
// Polling
// =========================================================

function _pollStatus(jobId, silent) {
  const INTERVAL_MS = 3000;

  async function tick() {
    try {
      const r = await fetch(`/api/jobs/${jobId}`);
      const job = await r.json();

      if (!silent) {
        renderJobProgress(job);
      }

      if (job.status === "completed") {
        _stopPolling();
        const r2 = await fetch(`/api/results/${job.result_set_id}`);
        const data = await r2.json();
        if (!silent) {
          hideJobProgress();
          renderCacheBadge("fresh", data.scraped_at);
          renderResults(data.items || []);
        }
        setLoading(false);

      } else if (job.status === "failed") {
        _stopPolling();
        if (!silent) {
          hideJobProgress();
          results.innerHTML = `<div class="alert alert-danger rounded-4">
            Scrape job failed: ${escapeHtml(job.error_message || "Unknown error.")}
          </div>`;
        }
        setLoading(false);
      }

    } catch (err) {
      // network blip — keep polling
      console.warn("Poll error:", err);
    }
  }

  tick();
  _pollTimer = setInterval(tick, INTERVAL_MS);
}

function _stopPolling() {
  if (_pollTimer !== null) {
    clearInterval(_pollTimer);
    _pollTimer = null;
  }
}

// =========================================================
// Build request payload
// =========================================================

function buildPayload() {
  const vin   = document.getElementById("vin").value.trim();
  const year  = document.getElementById("year").value.trim();
  const make  = document.getElementById("make").value.trim();
  const model = document.getElementById("model").value.trim();
  const trim  = document.getElementById("trim").value.trim();
  const topN  = Number(document.getElementById("topN").value || 10);

  return {
    vin:   vin   || null,
    year:  year  ? Number(year) : null,
    make:  make  || null,
    model: model || null,
    trim:  trim  || null,
    top_n: topN,
    max_pages_per_search: 2,
    window_days: 90,
  };
}

// =========================================================
// UI helpers
// =========================================================

function setLoading(isLoading) {
  submitBtn.disabled = isLoading;
  statusText.textContent = isLoading ? "Working..." : "";
}

function clearOutput() {
  summary.innerHTML   = "";
  results.innerHTML   = "";
  caveats.innerHTML   = "";
  jobProgress.innerHTML = "";
  jobProgress.classList.add("d-none");
}

function renderVehicle(v) {
  if (!v) return;
  summary.innerHTML = `
    <div class="alert alert-secondary rounded-4 mb-3">
      <strong>${escapeHtml(v.year)} ${escapeHtml(v.make)} ${escapeHtml(v.model)}</strong>
      ${v.trim ? `<span class="text-secondary ms-1">${escapeHtml(v.trim)}</span>` : ""}
      ${v.source === "nhtsa_vpic" ? `<span class="badge bg-info ms-2">VIN decoded</span>` : ""}
    </div>
  `;
}

function renderCacheBadge(cacheStatus, scrapedAt) {
  const labels = {
    fresh:        ["bg-success", "Fresh cache"],
    usable_stale: ["bg-warning text-dark", "Stale cache — refreshing"],
    expired:      ["bg-secondary", "Expired cache"],
  };
  const [cls, label] = labels[cacheStatus] || ["bg-secondary", cacheStatus];
  const age = scrapedAt ? ` <span class="ms-2 text-secondary small">scraped ${_relativeTime(scrapedAt)}</span>` : "";
  caveats.innerHTML = `
    <div class="d-flex align-items-center gap-2 mt-3">
      <span class="badge ${cls}">${label}</span>${age}
    </div>
  `;
}

function renderJobProgress(job) {
  jobProgress.classList.remove("d-none");
  const pct = job.progress_percent || 0;
  const msg = escapeHtml(job.progress_message || job.status);
  jobProgress.innerHTML = `
    <div class="card shadow-sm rounded-4 mb-4">
      <div class="card-body">
        <div class="d-flex justify-content-between mb-1">
          <span class="small fw-semibold">${msg}</span>
          <span class="small text-secondary">${pct}%</span>
        </div>
        <div class="progress" style="height:8px">
          <div class="progress-bar progress-bar-striped progress-bar-animated"
               role="progressbar"
               style="width:${pct}%"
               aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100">
          </div>
        </div>
      </div>
    </div>
  `;
}

function hideJobProgress() {
  jobProgress.classList.add("d-none");
  jobProgress.innerHTML = "";
}

function renderResults(items) {
  if (!items.length) {
    results.innerHTML = `<div class="alert alert-warning rounded-4">No ranked parts returned.</div>`;
    return;
  }

  const rows = items.map((item) => {
    const verdict    = item.recommendation || null;
    const badgeCls   = verdictBadge(verdict);
    const rankLabel  = item.vehicle_rank ?? item.rank ?? "";
    const partName   = item.part_name ?? item.part ?? "";
    const price      = item.median_price ?? item.median_sold_price;
    const net        = item.estimated_net_value;
    const str        = item.sell_through_rate ?? item.str;
    const conf       = item.confidence_score;
    const opp        = item.opportunity_score;
    const pullMins   = item.estimated_pull_minutes;
    const diff       = item.difficulty_score;

    const netCell = net !== null && net !== undefined
      ? `<span class="${net >= 75 ? "text-success fw-semibold" : net >= 25 ? "text-warning-emphasis" : "text-danger"}">${formatMoney(net)}</span>`
      : "";

    return `
      <tr>
        <td class="fw-semibold text-center">${escapeHtml(rankLabel)}</td>
        <td>${escapeHtml(partName)}</td>
        <td>${verdict ? `<span class="badge ${badgeCls}">${escapeHtml(verdict)}</span>` : ""}</td>
        <td>${formatMoney(price)}</td>
        <td>${netCell}</td>
        <td>${escapeHtml(item.sold_count)}</td>
        <td>${escapeHtml(item.active_count)}</td>
        <td>${formatPercent(str)}</td>
        <td>${pullMins != null ? `${pullMins} min` : ""}</td>
        <td>${diff != null ? _difficultyDots(diff) : ""}</td>
        <td>${escapeHtml(conf)}</td>
        <td class="fw-semibold">${escapeHtml(opp)}</td>
      </tr>
    `;
  }).join("");

  results.innerHTML = `
    <div class="card shadow-sm rounded-4">
      <div class="card-body p-0">
        <div class="table-responsive">
          <table class="table table-hover align-middle mb-0">
            <thead>
              <tr>
                <th class="text-center">#</th>
                <th>Part</th>
                <th>Verdict</th>
                <th>Median Price</th>
                <th>Est. Net</th>
                <th>Sold</th>
                <th>Active</th>
                <th>STR</th>
                <th>Pull Time</th>
                <th>Difficulty</th>
                <th>Confidence</th>
                <th>Opportunity</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>
    </div>
  `;
}

// =========================================================
// Formatters
// =========================================================

function _difficultyDots(score) {
  const filled = Math.round(score);
  return Array.from({ length: 5 }, (_, i) =>
    `<span class="${i < filled ? "dot-filled" : "dot-empty"}">●</span>`
  ).join("");
}

function verdictBadge(verdict) {
  if (!verdict) return "";
  const v = verdict.toLowerCase();
  if (v === "pull")  return "badge-pull";
  if (v === "maybe") return "badge-maybe";
  return "badge-skip";
}

function formatMoney(value) {
  const n = Number(value);
  if (Number.isNaN(n) || value === null || value === undefined) return "";
  return n.toLocaleString(undefined, { style: "currency", currency: "USD" });
}

function formatPercent(value) {
  const n = Number(value);
  if (Number.isNaN(n) || value === null || value === undefined) return "";
  return `${(n * 100).toFixed(1)}%`;
}

function escapeHtml(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function _relativeTime(isoString) {
  try {
    const diff = Date.now() - new Date(isoString).getTime();
    const mins  = Math.floor(diff / 60000);
    const hours = Math.floor(mins / 60);
    const days  = Math.floor(hours / 24);
    if (days  > 0) return `${days}d ago`;
    if (hours > 0) return `${hours}h ago`;
    if (mins  > 0) return `${mins}m ago`;
    return "just now";
  } catch {
    return "";
  }
}
