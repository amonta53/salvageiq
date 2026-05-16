// =========================================================
// script.js
// SalvageIQ front-end behavior
// =========================================================

const form           = document.getElementById("lookupForm");
const submitBtn      = document.getElementById("submitBtn");
const statusText     = document.getElementById("statusText");
const summary        = document.getElementById("summary");
const results        = document.getElementById("results");
const caveats        = document.getElementById("caveats");
const jobProgress    = document.getElementById("jobProgress");
const historySection = document.getElementById("historySection");
const historyList    = document.getElementById("historyList");

// =========================================================
// Vehicle cascading selects (NHTSA vPIC)
// =========================================================

const yearEl     = document.getElementById("year");
const makeEl     = document.getElementById("make");
const modelEl    = document.getElementById("model");
const trimEl     = document.getElementById("trim");
const trimListEl = document.getElementById("trimOptions");

// Populate year options
(function populateYears() {
  const max = new Date().getFullYear() + 1;
  for (let y = max; y >= 1975; y--) {
    const opt = document.createElement("option");
    opt.value = y;
    opt.textContent = y;
    yearEl.appendChild(opt);
  }
})();

// Year change: reset model + trims but makes are already loaded
yearEl.addEventListener("change", () => {
  _resetSelect(modelEl, "— select make —", true);
  _clearTrims();
  if (makeEl.value && yearEl.value) loadModels(yearEl.value, makeEl.value);
});

makeEl.addEventListener("change", () => {
  _resetSelect(modelEl, "— select make —", true);
  _clearTrims();
  if (makeEl.value && yearEl.value) loadModels(yearEl.value, makeEl.value);
});

function _resetSelect(el, placeholder, disabled) {
  el.innerHTML = `<option value="">${placeholder}</option>`;
  el.disabled  = disabled;
}

function _clearTrims() {
  trimListEl.innerHTML = "";
  trimEl.value = "";
}

async function loadMakes() {
  makeEl.innerHTML = '<option value="">Loading makes…</option>';
  makeEl.disabled  = true;
  try {
    const r    = await fetch("/api/vehicles/makes");
    const data = await r.json();
    makeEl.innerHTML = '<option value="">— Make —</option>' +
      (data.makes || []).map(m => `<option value="${escapeHtml(m)}">${escapeHtml(m)}</option>`).join("");
    makeEl.disabled = false;
  } catch {
    makeEl.innerHTML = '<option value="">Error loading makes</option>';
  }
}

async function loadModels(year, make) {
  modelEl.innerHTML = '<option value="">Loading…</option>';
  modelEl.disabled  = true;
  _clearTrims();
  try {
    const r    = await fetch(`/api/vehicles/models?make=${encodeURIComponent(make)}&year=${year}`);
    const data = await r.json();
    const models = data.models || [];
    modelEl.innerHTML = '<option value="">— Model —</option>' +
      models.map(m => `<option value="${escapeHtml(m)}">${escapeHtml(m)}</option>`).join("");
    modelEl.disabled = false;
  } catch {
    modelEl.innerHTML = '<option value="">Error loading models</option>';
  }
}

modelEl.addEventListener("change", () => {
  _clearTrims();
  if (modelEl.value && makeEl.value && yearEl.value) {
    loadTrims(yearEl.value, makeEl.value, modelEl.value);
  }
});

async function loadTrims(year, make, model) {
  _clearTrims();
  try {
    const r    = await fetch(`/api/vehicles/trims?make=${encodeURIComponent(make)}&model=${encodeURIComponent(model)}&year=${year}`);
    const data = await r.json();
    const trims = data.trims || [];
    trimListEl.innerHTML = trims
      .map(t => `<option value="${escapeHtml(t)}">`)
      .join("");
  } catch {
    // non-fatal — trim field stays as free text
  }
}

// Set year/make/model selects programmatically (used by re-run from history)
// Makes are already loaded — just set make value, then load models + trims
async function setVehicleSelects(year, make, model) {
  yearEl.value = year || "";
  _clearTrims();
  if (make && makeEl.querySelector(`option[value="${CSS.escape(make)}"]`)) {
    makeEl.value = make;
    if (model && year) {
      await loadModels(year, make);
      modelEl.value = model;
      if (model) loadTrims(year, make, model);  // fire-and-forget, non-blocking
    }
  }
}

let _pollTimer    = null;
let _jobStartTime = null;

// =========================================================
// Settings
// =========================================================

async function loadSettings() {
  try {
    const r = await fetch("/api/settings");
    if (!r.ok) return;
    const s = await r.json();
    document.getElementById("laborRate").value   = s.labor_rate_per_hour ?? 25;
    document.getElementById("feePercent").value  = s.marketplace_fee_percent != null
      ? (s.marketplace_fee_percent * 100).toFixed(1)
      : 13;
    const riskEl = document.getElementById("riskTolerance");
    if (s.risk_tolerance) riskEl.value = s.risk_tolerance;
  } catch {
    // non-fatal — defaults remain
  }
}

document.getElementById("saveSettingsBtn").addEventListener("click", async () => {
  const statusEl = document.getElementById("settingsSaveStatus");
  const laborRate  = parseFloat(document.getElementById("laborRate").value);
  const feePercent = parseFloat(document.getElementById("feePercent").value);
  const risk       = document.getElementById("riskTolerance").value;

  if (Number.isNaN(laborRate) || Number.isNaN(feePercent)) {
    statusEl.textContent = "Invalid values.";
    return;
  }

  try {
    statusEl.textContent = "Saving...";
    const r = await fetch("/api/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        labor_rate_per_hour:     laborRate,
        marketplace_fee_percent: feePercent / 100,
        risk_tolerance:          risk,
      }),
    });
    if (!r.ok) throw new Error("Save failed.");
    statusEl.textContent = "Saved.";
    setTimeout(() => { statusEl.textContent = ""; }, 2000);
  } catch {
    statusEl.textContent = "Error saving.";
  }
});

// Fire all independent page-load fetches in parallel
Promise.all([loadSettings(), loadMakes(), loadHistory()]);

// =========================================================
// Search
// =========================================================

form.addEventListener("submit", (event) => {
  event.preventDefault();
  runSearch();
});

async function runSearch() {
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
      loadHistory();
      if (data.refresh_job_id) {
        _pollStatus(data.refresh_job_id, /* silent */ true);
      }
    } else {
      // mode === "job"
      renderVehicle(data.vehicle);
      _jobStartTime = Date.now();
      _pollStatus(data.job_id, /* silent */ false);
    }

  } catch (error) {
    results.innerHTML = `<div class="alert alert-danger rounded-4">${escapeHtml(error.message)}</div>`;
    setLoading(false);
  }
}

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
          loadHistory();
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
  _jobStartTime = null;
}

// =========================================================
// Build request payload
// =========================================================

function buildPayload() {
  const vin    = document.getElementById("vin").value.trim();
  const year   = document.getElementById("year").value.trim();
  const make   = document.getElementById("make").value.trim();
  const model  = document.getElementById("model").value.trim();
  const trim   = document.getElementById("trim").value.trim();
  const engine = document.getElementById("engine").value.trim();
  const topN   = Number(document.getElementById("topN").value || 10);

  return {
    vin:    vin    || null,
    year:   year   ? Number(year) : null,
    make:   make   || null,
    model:  model  || null,
    trim:   trim   || null,
    engine: engine || null,
    top_n:  topN,
    max_pages_per_search: 2,
    window_days: 90,
  };
}

// =========================================================
// History
// =========================================================

async function loadHistory() {
  try {
    const r = await fetch("/api/history");
    if (!r.ok) return;
    const data = await r.json();
    renderHistory(data.searches || []);
  } catch {
    // non-fatal
  }
}

function renderHistory(searches) {
  if (!searches.length) {
    historySection.style.display = "none";
    return;
  }

  historySection.style.display = "";

  const now = Date.now();

  historyList.innerHTML = searches.map((s) => {
    const vehicleLabel = [s.year, s.make, s.model, s.trim].filter(Boolean).join(" ");
    const age          = s.scraped_at ? _relativeTime(s.scraped_at) : "unknown";
    const expires      = s.cache_expires_at ? new Date(s.cache_expires_at).getTime() : 0;
    const isFresh      = expires > now;
    const badgeCls     = isFresh ? "bg-success" : "bg-secondary";
    const badgeLabel   = isFresh ? "Fresh" : "Stale";

    return `
      <div class="history-row d-flex align-items-center justify-content-between gap-3 py-2">
        <div class="d-flex align-items-center gap-2 flex-grow-1 min-w-0">
          <span class="fw-semibold text-truncate">${escapeHtml(vehicleLabel)}</span>
          <span class="badge ${badgeCls} flex-shrink-0">${badgeLabel}</span>
          <span class="text-secondary small flex-shrink-0">${age}</span>
        </div>
        <button class="btn btn-sm btn-outline-secondary flex-shrink-0"
                onclick="rerunSearch(${s.year}, ${escapeHtml(JSON.stringify(s.make))}, ${escapeHtml(JSON.stringify(s.model))})">
          Re-run
        </button>
      </div>
    `;
  }).join("");
}

async function rerunSearch(year, make, model) {
  document.getElementById("vin").value    = "";
  document.getElementById("trim").value   = "";
  document.getElementById("engine").value = "";
  await setVehicleSelects(year, make, model);
  runSearch();
}

// =========================================================
// VIN Scanner
// =========================================================

let _codeReader = null;
const scanModal = document.getElementById("scanModal");

document.getElementById("scanVinBtn").addEventListener("click", () => {
  bootstrap.Modal.getOrCreateInstance(scanModal).show();
});

scanModal.addEventListener("shown.bs.modal",  startScanner);
scanModal.addEventListener("hide.bs.modal",   stopScanner);

async function startScanner() {
  const video    = document.getElementById("scanVideo");
  const statusEl = document.getElementById("scanStatus");

  statusEl.textContent = "Starting camera…";

  if (typeof ZXing === "undefined") {
    statusEl.textContent = "Scanner library failed to load. Enter VIN manually.";
    return;
  }

  try {
    _codeReader = new ZXing.BrowserMultiFormatReader();
    statusEl.textContent = "Point camera at the VIN barcode…";

    await _codeReader.decodeFromVideoDevice(null, video, (result, err) => {
      if (!result) return;

      // Strip characters that can't appear in a VIN (I, O, Q)
      const text = result.getText().replace(/[^A-HJ-NPR-Z0-9]/gi, "").toUpperCase();

      if (text.length === 17) {
        document.getElementById("vin").value = text;
        stopScanner();
        bootstrap.Modal.getInstance(scanModal).hide();
      } else if (text.length > 3) {
        statusEl.textContent = `Read: ${text} — not a VIN, keep scanning`;
      }
    });

  } catch (err) {
    if (err.name === "NotAllowedError") {
      statusEl.textContent = "Camera permission denied. Enter VIN manually.";
    } else if (err.name === "NotFoundError") {
      statusEl.textContent = "No camera detected. Enter VIN manually.";
    } else {
      statusEl.textContent = `Camera error: ${err.message}`;
    }
  }
}

function stopScanner() {
  if (_codeReader) {
    _codeReader.reset();
    _codeReader = null;
  }
}

// =========================================================
// UI helpers
// =========================================================

function setLoading(isLoading) {
  submitBtn.disabled = isLoading;
  statusText.textContent = isLoading ? "Working..." : "";
}

function clearOutput() {
  summary.innerHTML     = "";
  results.innerHTML     = "";
  caveats.innerHTML     = "";
  jobProgress.innerHTML = "";
  jobProgress.classList.add("d-none");
}

function renderVehicle(v) {
  if (!v) return;

  const chips = [v.body_class, v.drive_type, v.engine, v.fuel_type]
    .filter(Boolean)
    .map(c => `<span class="vehicle-chip">${escapeHtml(c)}</span>`)
    .join("");

  const trimLine = v.trim || v.series
    ? `<span class="text-secondary ms-1">${escapeHtml([v.trim, v.series].filter(Boolean).join(" · "))}</span>`
    : "";

  summary.innerHTML = `
    <div class="alert alert-secondary rounded-4 mb-3">
      <div class="d-flex flex-wrap align-items-center gap-2">
        <strong>${escapeHtml(v.year)} ${escapeHtml(v.make)} ${escapeHtml(v.model)}</strong>
        ${trimLine}
        ${v.source === "nhtsa_vpic" ? `<span class="badge bg-info">VIN decoded</span>` : ""}
      </div>
      ${chips ? `<div class="mt-1 d-flex flex-wrap gap-1">${chips}</div>` : ""}
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
  const pct     = job.progress_percent || 0;
  const msg     = escapeHtml(job.progress_message || job.status);
  const elapsed = _jobStartTime ? _elapsedTime(_jobStartTime) : "";
  const elapsedHtml = elapsed
    ? `<span class="small text-secondary">${elapsed}</span>`
    : "";

  jobProgress.innerHTML = `
    <div class="card shadow-sm rounded-4 mb-4">
      <div class="card-body">
        <div class="d-flex justify-content-between align-items-center mb-1">
          <span class="small fw-semibold">${msg}</span>
          <div class="d-flex gap-3 align-items-center">
            ${elapsedHtml}
            <span class="small text-secondary">${pct}%</span>
          </div>
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
    const verdict   = item.recommendation || null;
    const badgeCls  = verdictBadge(verdict);
    const rankLabel = item.vehicle_rank ?? item.rank ?? "";
    const partName  = item.part_name ?? item.part ?? "";
    const price     = item.median_price ?? item.median_sold_price;
    const net       = item.estimated_net_value;
    const str       = item.sell_through_rate ?? item.str;
    const conf      = item.confidence_score;
    const opp       = item.opportunity_score;
    const pullMins  = item.estimated_pull_minutes;
    const diff      = item.difficulty_score;

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
        <td>${renderTrend(item.trend_direction, item.trend_pct)}</td>
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
                <th>Trend</th>
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

function renderTrend(direction, pct) {
  if (!direction || direction === "new") {
    return `<span class="trend-badge trend-new">— new</span>`;
  }
  const sign  = pct > 0 ? "+" : "";
  const label = pct !== null && pct !== undefined ? `${sign}${pct}%` : "";
  if (direction === "up")      return `<span class="trend-badge trend-up">↑ ${label}</span>`;
  if (direction === "down")    return `<span class="trend-badge trend-down">↓ ${label}</span>`;
  return `<span class="trend-badge trend-neutral">→ stable</span>`;
}

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
    const diff  = Date.now() - new Date(isoString).getTime();
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

function _elapsedTime(startMs) {
  const secs = Math.floor((Date.now() - startMs) / 1000);
  if (secs < 60) return `${secs}s`;
  return `${Math.floor(secs / 60)}m ${secs % 60}s`;
}
