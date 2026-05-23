const state = {
  scan: null,
  selections: new Map(), // groupKey -> { keeper, quarantine: Set }
  unresolvedQuarantine: new Set(), // paths selected from unresolved section
  tmdbOpen: new Set(), // unresolved item paths with TMDB search panel open
};

function apiErrorDetail(data, status) {
  if (status === 404 && data?.detail === "Not Found") {
    return "TMDB search API not found — stop and restart serve.py, then hard-refresh the page.";
  }
  const detail = data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
  }
  return "Request failed";
}

function formatBytes(n) {
  if (!n) return "—";
  const gb = n / (1024 ** 3);
  if (gb >= 1) return `${gb.toFixed(2)} GB`;
  const mb = n / (1024 ** 2);
  return `${mb.toFixed(0)} MB`;
}

function showMessage(text, type = "success") {
  const el = document.getElementById("message");
  el.textContent = text;
  el.className = `message show ${type}`;
  setTimeout(() => el.classList.remove("show"), 8000);
}

function normalizePath(p) {
  return String(p).replace(/\//g, "\\").toLowerCase();
}

function updateSummary() {
  const s = state.scan?.summary || {};
  document.getElementById("summary").innerHTML = `
    <span><strong>${s.total_items ?? 0}</strong> items scanned</span>
    <span><strong>${s.duplicate_groups ?? 0}</strong> duplicate groups</span>
    <span><strong>${s.duplicate_items ?? 0}</strong> items in duplicates</span>
    <span><strong>${s.unresolved ?? 0}</strong> unresolved</span>
  `;
}

function recalcSummary() {
  if (!state.scan) return;
  const groups = state.scan.duplicate_groups || [];
  state.scan.summary = {
    total_items: (state.scan.all_items || []).length,
    duplicate_groups: groups.length,
    duplicate_items: groups.reduce((n, g) => n + g.items.length, 0),
    unresolved: (state.scan.unresolved || []).length,
  };
}

function renderFromState() {
  if (!state.scan) return;
  updateSummary();
  document.getElementById("groups").innerHTML = groupsHtml();
  document.getElementById("unresolved").innerHTML = renderUnresolved(
    state.scan.unresolved || []
  );
  updateQuarantineButton();
}

function groupsHtml() {
  const groups = state.scan?.duplicate_groups || [];
  if (!groups.length) {
    return '<p class="empty-state">No duplicate groups</p>';
  }
  return groups.map(renderGroup).join("");
}

/** Remove successfully quarantined paths from in-memory scan and re-render. */
function applyQuarantineResults(results) {
  if (!state.scan || !results?.length) return 0;

  const removed = new Set();
  for (const r of results) {
    if (r.success && r.source) {
      removed.add(normalizePath(r.source));
    }
  }
  if (removed.size === 0) return 0;

  state.scan.unresolved = (state.scan.unresolved || []).filter(
    (i) => !removed.has(normalizePath(i.path))
  );
  for (const p of [...state.unresolvedQuarantine]) {
    if (removed.has(normalizePath(p))) {
      state.unresolvedQuarantine.delete(p);
    }
  }

  state.scan.duplicate_groups = (state.scan.duplicate_groups || [])
    .map((g) => ({
      ...g,
      items: g.items.filter((i) => !removed.has(normalizePath(i.path))),
    }))
    .filter((g) => g.items.length >= 2);

  state.scan.all_items = (state.scan.all_items || []).filter(
    (i) => !removed.has(normalizePath(i.path))
  );

  for (const key of [...state.selections.keys()]) {
    const stillExists = state.scan.duplicate_groups.some(
      (g) => g.group_key === key
    );
    if (!stillExists) {
      state.selections.delete(key);
    } else {
      const sel = state.selections.get(key);
      for (const p of [...sel.quarantine]) {
        if (removed.has(normalizePath(p))) {
          sel.quarantine.delete(p);
        }
      }
    }
  }

  recalcSummary();
  renderFromState();
  return removed.size;
}

function getGroupSelection(groupKey, items) {
  if (!state.selections.has(groupKey)) {
    const keeper = items.find((i) => i.suggested_keeper) || items[0];
    state.selections.set(groupKey, {
      keeper: keeper.path,
      quarantine: new Set(
        items.filter((i) => i.path !== keeper.path).map((i) => i.path)
      ),
    });
  }
  return state.selections.get(groupKey);
}

function updateQuarantineButton() {
  let count = state.unresolvedQuarantine.size;
  for (const sel of state.selections.values()) {
    count += sel.quarantine.size;
  }
  const btn = document.getElementById("btn-quarantine");
  btn.disabled = count === 0;
  btn.textContent =
    count === 0
      ? "Quarantine selected"
      : `Quarantine selected (${count})`;
}

function renderGroup(group) {
  const key = group.group_key;
  const items = group.items;
  const sel = getGroupSelection(key, items);

  const imdbLink = group.imdb_id
    ? `<a href="https://www.imdb.com/title/${group.imdb_id}/" target="_blank" rel="noopener">IMDB</a>`
    : "";

  const poster = group.poster_url
    ? `<img class="poster" src="${group.poster_url}" alt="" />`
    : `<div class="poster-placeholder">?</div>`;

  const rows = items
    .map((item) => {
      const isKeeper = sel.keeper === item.path;
      const isQuarantine = sel.quarantine.has(item.path);
      const confClass = `confidence-${item.confidence || "low"}`;
      const warn = item.multiple_videos_warning
        ? '<span class="warning-flag" title="Multiple video files in folder">⚠ multi-video</span>'
        : "";

      return `
        <tr data-path="${escapeAttr(item.path)}">
          <td>
            <input type="radio" name="keeper-${escapeAttr(key)}"
              value="${escapeAttr(item.path)}"
              ${isKeeper ? "checked" : ""}
              data-group="${escapeAttr(key)}" />
          </td>
          <td>
            <input type="checkbox" class="quarantine-cb"
              data-group="${escapeAttr(key)}"
              data-path="${escapeAttr(item.path)}"
              ${isQuarantine && !isKeeper ? "checked" : ""}
              ${isKeeper ? "disabled" : ""} />
          </td>
          <td class="path-cell">${escapeHtml(item.raw_name)}</td>
          <td>${escapeHtml(item.quality_hint || "—")}</td>
          <td>${formatBytes(item.size_bytes)}</td>
          <td class="${confClass}">${item.confidence}</td>
          <td>${warn}</td>
        </tr>
      `;
    })
    .join("");

  return `
    <div class="group-card" data-group="${escapeAttr(key)}">
      <div class="group-header">
        <span class="chevron">▼</span>
        ${poster}
        <div class="group-title">
          <h3>${escapeHtml(group.title || "Unknown")} ${group.year ? `(${group.year})` : ""}</h3>
          <div class="meta">
            <span class="badge badge-dupes">${items.length} copies</span>
            ${imdbLink}
            · TMDB ${group.tmdb_id || "—"}
          </div>
        </div>
      </div>
      <table class="items-table">
        <thead>
          <tr>
            <th>Keep</th>
            <th>Quarantine</th>
            <th>Name</th>
            <th>Quality</th>
            <th>Size</th>
            <th>Match</th>
            <th></th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function tmdbDuplicateBadge(dup) {
  if (!dup?.is_duplicate) {
    return '<span class="tmdb-badge tmdb-badge-unique">No other copies in library</span>';
  }
  const copies = dup.copies || [];
  const names = copies
    .slice(0, 3)
    .map((c) => escapeHtml(c.raw_name || c.path))
    .join(", ");
  const more =
    copies.length > 3 ? ` (+${copies.length - 3} more)` : "";
  const n = dup.existing_count ?? copies.length;
  return `<span class="tmdb-badge tmdb-badge-dup">Duplicate — ${n} other cop${n === 1 ? "y" : "ies"}: ${names}${more}</span>`;
}

function renderTmdbSearchPanel(item) {
  const open = state.tmdbOpen.has(item.path);
  const defaultQuery =
    item.parsed_title || item.raw_name?.replace(/\.[^.]+$/, "") || "";
  return `
    <tr class="tmdb-search-row ${open ? "" : "is-hidden"}" data-path="${escapeAttr(item.path)}">
      <td colspan="8">
        <div class="tmdb-search-panel">
          <div class="tmdb-search-form">
            <input type="text" class="tmdb-query" value="${escapeAttr(defaultQuery)}" placeholder="Search TMDB…" />
            <input type="number" class="tmdb-year" placeholder="Year" value="${item.parsed_year || ""}" min="1900" max="2100" />
            <button type="button" class="btn-secondary btn-tmdb-run" data-path="${escapeAttr(item.path)}">Search</button>
          </div>
          <div class="tmdb-results"></div>
        </div>
      </td>
    </tr>
  `;
}

function renderUnresolved(items) {
  if (!items.length) {
    return '<p class="empty-state">None</p>';
  }
  const rows = items
    .map((item) => {
      const checked = state.unresolvedQuarantine.has(item.path);
      return `
    <tr class="unresolved-row" data-path="${escapeAttr(item.path)}">
      <td>
        <input type="checkbox" class="unresolved-quarantine-cb"
          data-path="${escapeAttr(item.path)}"
          ${checked ? "checked" : ""} />
      </td>
      <td class="path-cell">${escapeHtml(item.path)}</td>
      <td>${escapeHtml(item.parsed_title || "—")}</td>
      <td>${item.parsed_year || "—"}</td>
      <td>${formatBytes(item.size_bytes)}</td>
      <td class="confidence-low">${item.confidence}</td>
      <td class="reason-cell">${escapeHtml(item.unresolved_reason || "—")}</td>
      <td>
        <button type="button" class="btn-secondary btn-tmdb-search" data-path="${escapeAttr(item.path)}">Search TMDB</button>
      </td>
    </tr>
    ${renderTmdbSearchPanel(item)}
  `;
    })
    .join("");

  const allChecked =
    items.length > 0 && items.every((i) => state.unresolvedQuarantine.has(i.path));

  return `
    <div class="unresolved-toolbar">
      <label class="select-all-label">
        <input type="checkbox" id="unresolved-select-all" ${allChecked ? "checked" : ""} />
        Select all (${items.length})
      </label>
    </div>
    <table class="items-table unresolved-table">
      <thead>
        <tr>
          <th>Quarantine</th>
          <th>Path</th>
          <th>Parsed title</th>
          <th>Year</th>
          <th>Size</th>
          <th>Match</th>
          <th>Why unresolved</th>
          <th>TMDB</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function renderTmdbResults(container, results, itemPath) {
  if (!results?.length) {
    container.innerHTML = '<p class="tmdb-no-results">No results on TMDB.</p>';
    return;
  }
  container.innerHTML = results
    .map(
      (r) => `
    <div class="tmdb-result">
      ${
        r.poster_url
          ? `<img class="tmdb-result-poster" src="${escapeAttr(r.poster_url)}" alt="" />`
          : '<div class="tmdb-result-poster-ph">?</div>'
      }
      <div class="tmdb-result-body">
        <div class="tmdb-result-title">
          <strong>${escapeHtml(r.title)}</strong>
          ${r.year ? `<span class="tmdb-result-year">(${r.year})</span>` : ""}
          <a href="https://www.themoviedb.org/movie/${r.tmdb_id}" target="_blank" rel="noopener" class="tmdb-link">TMDB</a>
        </div>
        ${tmdbDuplicateBadge(r.duplicate)}
        <button type="button" class="btn-secondary btn-tmdb-apply"
          data-tmdb-id="${r.tmdb_id}"
          data-path="${escapeAttr(itemPath)}">Use this match</button>
      </div>
    </div>
  `
    )
    .join("");
}

async function runTmdbSearch(itemPath) {
  const row = document.querySelector(
    `.tmdb-search-row[data-path="${CSS.escape(itemPath)}"]`
  );
  if (!row) return;
  const query = row.querySelector(".tmdb-query")?.value.trim();
  if (!query || query.length < 2) {
    showMessage("Enter at least 2 characters to search TMDB.", "error");
    return;
  }
  const yearRaw = row.querySelector(".tmdb-year")?.value;
  const year = yearRaw ? parseInt(yearRaw, 10) : null;
  const resultsEl = row.querySelector(".tmdb-results");
  resultsEl.innerHTML = '<p class="tmdb-loading">Searching TMDB…</p>';

  const params = new URLSearchParams({ q: query, item_path: itemPath });
  if (year && !Number.isNaN(year)) params.set("year", String(year));

  try {
    const res = await fetch(`/api/tmdb/search?${params}`);
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorDetail(data, res.status));
    renderTmdbResults(resultsEl, data.results, itemPath);
  } catch (err) {
    resultsEl.innerHTML = `<p class="tmdb-error">${escapeHtml(err.message)}</p>`;
  }
}

function toggleTmdbPanel(itemPath) {
  const row = document.querySelector(
    `.tmdb-search-row[data-path="${CSS.escape(itemPath)}"]`
  );
  if (!row) return;
  const opening = row.classList.contains("is-hidden");
  if (opening) {
    state.tmdbOpen.add(itemPath);
    row.classList.remove("is-hidden");
    if (!row.querySelector(".tmdb-results")?.innerHTML.trim()) {
      runTmdbSearch(itemPath);
    }
  } else {
    state.tmdbOpen.delete(itemPath);
    row.classList.add("is-hidden");
  }
}

async function applyTmdbMatch(itemPath, tmdbId) {
  const btn = document.querySelector(
    `.btn-tmdb-apply[data-path="${CSS.escape(itemPath)}"][data-tmdb-id="${tmdbId}"]`
  );
  if (btn) btn.disabled = true;
  try {
    const res = await fetch("/api/tmdb/apply-match", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_path: itemPath, tmdb_id: tmdbId }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorDetail(data, res.status));

    const rename = data.rename || {};
    if (rename.old_path && state.unresolvedQuarantine.has(rename.old_path)) {
      state.unresolvedQuarantine.delete(rename.old_path);
    }
    state.unresolvedQuarantine.delete(itemPath);
    state.tmdbOpen.delete(itemPath);
    if (rename.new_path) state.tmdbOpen.delete(rename.new_path);

    state.scan = data.scan;
    renderFromState();

    const dup = data.duplicate;
    let msg;
    if (dup?.is_duplicate || data.duplicate_group) {
      const n = (dup?.existing_count ?? 0) + 1;
      msg = `Matched to "${data.item?.title}" — duplicate (${n} copies in library).`;
    } else {
      msg = `Matched to "${data.item?.title}" — only copy in library.`;
    }
    if (rename.renamed) {
      msg += ` Renamed folder to "${rename.new_name}".`;
    }
    showMessage(msg);
  } catch (err) {
    showMessage(err.message, "error");
    if (btn) btn.disabled = false;
  }
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function escapeAttr(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;");
}

let eventsBound = false;

function bindStaticEvents() {
  if (eventsBound) return;
  eventsBound = true;

  document.getElementById("groups").addEventListener("change", (e) => {
    const groupKey = e.target.dataset.group;
    if (!groupKey) return;
    const sel = state.selections.get(groupKey);
    if (!sel) return;

    if (e.target.type === "radio") {
      sel.keeper = e.target.value;
      sel.quarantine.delete(sel.keeper);
      const group = state.scan.duplicate_groups.find((g) => g.group_key === groupKey);
      if (group) {
        group.items.forEach((item) => {
          if (item.path !== sel.keeper) sel.quarantine.add(item.path);
        });
      }
      const card = document.querySelector(`.group-card[data-group="${CSS.escape(groupKey)}"]`);
      card?.querySelectorAll(".quarantine-cb").forEach((cb) => {
        const p = cb.dataset.path;
        if (p === sel.keeper) {
          cb.checked = false;
          cb.disabled = true;
        } else {
          cb.disabled = false;
          cb.checked = sel.quarantine.has(p);
        }
      });
    }

    if (e.target.classList.contains("quarantine-cb")) {
      const path = e.target.dataset.path;
      if (e.target.checked) sel.quarantine.add(path);
      else sel.quarantine.delete(path);
    }

    updateQuarantineButton();
  });

  document.getElementById("groups").addEventListener("click", (e) => {
    const header = e.target.closest(".group-header");
    if (!header) return;
    if (e.target.closest("a, input, button")) return;
    header.closest(".group-card")?.classList.toggle("collapsed");
  });

  document.getElementById("unresolved").addEventListener("click", (e) => {
    if (e.target.classList.contains("btn-tmdb-search")) {
      toggleTmdbPanel(e.target.dataset.path);
      return;
    }
    if (e.target.classList.contains("btn-tmdb-run")) {
      runTmdbSearch(e.target.dataset.path);
      return;
    }
    if (e.target.classList.contains("btn-tmdb-apply")) {
      applyTmdbMatch(e.target.dataset.path, parseInt(e.target.dataset.tmdbId, 10));
    }
  });

  document.getElementById("unresolved").addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const panel = e.target.closest(".tmdb-search-panel");
    if (!panel) return;
    const row = panel.closest(".tmdb-search-row");
    if (!row) return;
    e.preventDefault();
    runTmdbSearch(row.dataset.path);
  });

  document.getElementById("unresolved").addEventListener("change", (e) => {
    if (e.target.id === "unresolved-select-all") {
      const items = state.scan?.unresolved || [];
      if (e.target.checked) {
        items.forEach((i) => state.unresolvedQuarantine.add(i.path));
      } else {
        state.unresolvedQuarantine.clear();
      }
      document.getElementById("unresolved").innerHTML = renderUnresolved(items);
      updateQuarantineButton();
      return;
    }

    if (e.target.classList.contains("unresolved-quarantine-cb")) {
      const path = e.target.dataset.path;
      if (e.target.checked) state.unresolvedQuarantine.add(path);
      else state.unresolvedQuarantine.delete(path);
      updateQuarantineButton();
    }
  });

  document.getElementById("btn-quarantine").addEventListener("click", openModal);
  document.getElementById("modal-cancel").addEventListener("click", closeModal);
  document.getElementById("modal-confirm").addEventListener("click", confirmQuarantine);
  document.getElementById("btn-rescan").addEventListener("click", triggerRescan);
  document.getElementById("btn-cancel-scan").addEventListener("click", cancelScan);
}

function collectQuarantinePaths() {
  const paths = [];
  const meta = [];
  for (const [groupKey, sel] of state.selections) {
    for (const p of sel.quarantine) {
      paths.push(p);
      const group = state.scan.duplicate_groups.find((g) => g.group_key === groupKey);
      meta.push({ path: p, tmdb_id: group?.tmdb_id, source: "duplicate" });
    }
  }
  for (const p of state.unresolvedQuarantine) {
    paths.push(p);
    meta.push({ path: p, tmdb_id: null, source: "unresolved" });
  }
  return { paths, meta };
}

function openModal() {
  const { paths } = collectQuarantinePaths();
  if (!paths.length) return;
  const ul = document.getElementById("modal-paths");
  ul.innerHTML = paths.map((p) => `<li>${escapeHtml(p)}</li>`).join("");
  document.getElementById("modal").classList.add("open");
}

function closeModal() {
  document.getElementById("modal").classList.remove("open");
}

async function confirmQuarantine() {
  const { paths, meta } = collectQuarantinePaths();
  closeModal();
  const tmdbId = meta[0]?.tmdb_id ?? null;

  try {
    const res = await fetch("/api/quarantine", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        quarantine_paths: paths,
        tmdb_id: tmdbId,
        note: "via web UI",
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Quarantine failed");

    const removed = applyQuarantineResults(data.results || []);
    let msg = `Moved ${data.moved} item(s) to quarantine.`;
    if (data.failed) msg += ` ${data.failed} failed.`;
    if (removed > 0) msg += ` Removed ${removed} from list.`;
    showMessage(msg);

    if (removed === 0 && data.moved > 0) {
      await loadScan();
    }
  } catch (err) {
    showMessage(err.message, "error");
  }
}

let scanPollInterval = null;
let scanUiActive = false;

function setScanningState(active) {
  const rescan = document.getElementById("btn-rescan");
  const cancel = document.getElementById("btn-cancel-scan");
  rescan.disabled = active;
  rescan.textContent = active ? "Scanning…" : "Rescan library";
  cancel.disabled = !active;
  cancel.classList.toggle("is-hidden", !active);
}

function showProgressPanel(show) {
  const panel = document.getElementById("scan-progress-panel");
  panel.classList.toggle("is-hidden", !show);
}

function renderScanProgress(prog) {
  const label = document.getElementById("scan-progress-label");
  const count = document.getElementById("scan-progress-count");
  const bar = document.getElementById("scan-progress-bar");
  const message = document.getElementById("scan-progress-message");

  if (!scanUiActive && (!prog || (!prog.running && prog.phase !== "done"))) {
    showProgressPanel(false);
    bar.classList.remove("indeterminate");
    return;
  }

  showProgressPanel(true);

  if (!prog) {
    label.textContent = "Starting scan…";
    count.textContent = "";
    bar.style.width = "0%";
    bar.classList.add("indeterminate");
    message.textContent = "";
    return;
  }

  label.textContent = prog.label || "Scanning…";

  const current = prog.current ?? 0;
  const total = prog.total ?? 0;
  if (total > 0) {
    count.textContent = `${current} / ${total}${
      prog.percent != null ? ` (${prog.percent}%)` : ""
    }`;
    const pct = prog.percent ?? Math.round((current / total) * 100);
    bar.style.width = `${Math.min(100, pct)}%`;
    bar.classList.remove("indeterminate");
  } else {
    count.textContent =
      prog.phase === "grouping" ? "Finishing…" : prog.running ? "…" : "";
    bar.style.width = prog.phase === "done" ? "100%" : "0%";
    bar.classList.toggle("indeterminate", prog.running && prog.phase !== "done");
  }

  message.textContent = prog.message || "";
  if (prog.phase === "error" && prog.error) {
    message.textContent = prog.error;
  }
  if (prog.phase === "cancelled") {
    message.textContent = "Scan was cancelled. Previous scan data is unchanged.";
  }
  if (prog.phase === "done" && prog.message) {
    message.textContent = prog.message;
  }
}

function stopScanPoll() {
  if (scanPollInterval) {
    clearInterval(scanPollInterval);
    scanPollInterval = null;
  }
}

async function pollScanStatus() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    const st = await res.json();
    const prog = st.progress;
    const running = st.rescan_running || (prog && prog.running);

    if (running || scanUiActive) {
      if (running) setScanningState(true);
      renderScanProgress(prog || { running: true, label: "Starting scan…" });
    }

    if (prog?.phase === "cancelled") {
      scanUiActive = false;
      stopScanPoll();
      setScanningState(false);
      renderScanProgress(prog);
      showMessage("Scan cancelled.");
      setTimeout(() => showProgressPanel(false), 2500);
      return;
    }

    if (prog?.phase === "error") {
      scanUiActive = false;
      stopScanPoll();
      setScanningState(false);
      renderScanProgress(prog);
      showMessage(prog.error || "Scan failed", "error");
      setTimeout(() => showProgressPanel(false), 4000);
      return;
    }

    if (!running && scanUiActive) {
      stopScanPoll();
      setScanningState(false);
      renderScanProgress(prog || { phase: "done", label: "Scan complete", running: false });
      if (st.scan_exists) {
        await loadScan();
        showMessage("Rescan complete.");
      }
      scanUiActive = false;
      setTimeout(() => showProgressPanel(false), 2500);
    }
  } catch (err) {
    console.error("Scan status poll failed:", err);
  }
}

function startScanPoll() {
  stopScanPoll();
  pollScanStatus();
  scanPollInterval = setInterval(pollScanStatus, 1000);
}

async function cancelScan() {
  const cancelBtn = document.getElementById("btn-cancel-scan");
  cancelBtn.disabled = true;
  try {
    const res = await fetch("/api/cancel-scan", { method: "POST" });
    const data = await res.json();
    if (data.status === "not_running") {
      showMessage("No scan is running.");
      scanUiActive = false;
      setScanningState(false);
      showProgressPanel(false);
      return;
    }
    if (data.progress) renderScanProgress(data.progress);
    scanUiActive = false;
    setScanningState(false);
    stopScanPoll();
    showMessage("Scan cancelled.");
    setTimeout(() => showProgressPanel(false), 2500);
  } catch (err) {
    showMessage(err.message, "error");
    cancelBtn.disabled = false;
  }
}

async function triggerRescan() {
  scanUiActive = true;
  setScanningState(true);
  renderScanProgress({ running: true, label: "Starting scan…", current: 0, total: 0 });
  try {
    const res = await fetch("/api/rescan", { method: "POST" });
    const data = await res.json();
    if (data.status === "already_running") {
      showMessage("A scan is already running.");
      if (data.progress) renderScanProgress(data.progress);
    } else if (data.progress) {
      renderScanProgress(data.progress);
    }
    startScanPoll();
  } catch (err) {
    scanUiActive = false;
    setScanningState(false);
    showProgressPanel(false);
    showMessage(err.message, "error");
  }
}

async function loadScan() {
  state.selections.clear();
  state.unresolvedQuarantine.clear();
  try {
    const res = await fetch("/api/scan");
    if (!res.ok) {
      if (res.status === 404) {
        document.getElementById("empty").style.display = "block";
        document.getElementById("content").style.display = "none";
        return;
      }
      throw new Error("Failed to load scan");
    }
    state.scan = await res.json();
    document.getElementById("empty").style.display = "none";
    document.getElementById("content").style.display = "block";

    renderFromState();
  } catch (err) {
    document.getElementById("empty").style.display = "block";
    document.getElementById("empty").innerHTML = `<p>${escapeHtml(err.message)}</p>`;
  }
}

async function checkInitialScanStatus() {
  try {
    const res = await fetch("/api/status");
    const st = await res.json();
    if (st.rescan_running || st.progress?.running) {
      scanUiActive = true;
      setScanningState(true);
      renderScanProgress(st.progress);
      startScanPoll();
    }
  } catch (_) {}
}

bindStaticEvents();
loadScan();
checkInitialScanStatus();
