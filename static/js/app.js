/* Shared helpers + result panel rendering (vanilla JS, no frameworks). */
"use strict";

const API = {
  async get(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
    return r.json();
  },
  async post(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
    return r.json();
  },
};

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function statusClass(status) {
  return "status-" + String(status || "VERIFY").toLowerCase();
}
function statusBadge(status) {
  const color = String(status || "").toLowerCase();
  const cls = color === "confirmed" ? "badge-green" : color === "verify" ? "badge-orange" : color === "conflict" ? "badge-red" : "badge-gray";
  return `<span class="badge ${cls}">${esc(status)}</span>`;
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
}

/* ------------------------------------------------------------------ */
/* Result panel                                                       */
/* ------------------------------------------------------------------ */

function renderResult(result, container) {
  if (!container) return;
  container.innerHTML = "";

  const summary = result.summary || {};
  const head = document.createElement("div");
  head.className = "row mb";
  head.innerHTML = `
    <h2 style="margin:0">ANALYSIS RESULT</h2>
    <span class="right">
      <span class="badge badge-green">${summary.confirmed || 0} CONFIRMED</span>
      <span class="badge badge-orange">${summary.verify || 0} VERIFY</span>
      <span class="badge badge-red">${summary.conflicts || 0} CONFLICT</span>
    </span>`;
  container.appendChild(head);

  // Image warning
  if (result.source_type === "image") {
    const info = document.createElement("div");
    info.className = "info-box";
    info.innerHTML = `<b>Image-derived analysis.</b> Values were extracted by the local vision model and run through the
      deterministic M-Code engine. Always verify extracted wording against the original BOL before entering anything into Tenet/EBS.`;
    container.appendChild(info);
  }

  // Conflicts
  (result.conflicts || []).forEach((c) => {
    const box = document.createElement("div");
    box.className = "conflict-box";
    box.innerHTML = `<b>⚠ CONFLICT DETECTED</b><br>${esc(c.message)}<br>
      <span class="small">Sources: ${esc((c.phrases || []).join(" | "))}</span>`;
    container.appendChild(box);
  });

  // Warnings
  (result.warnings || []).forEach((w) => {
    const box = document.createElement("div");
    box.className = "warn-box";
    box.innerHTML = `⚠ ${esc(w)}`;
    container.appendChild(box);
  });

  // NOT DETECTED rows
  (result.not_detected || []).forEach((nd) => {
    const box = document.createElement("div");
    box.className = "info-box";
    box.innerHTML = `<b>${esc(nd.label)}:</b> ${statusBadge(nd.status)}<br><span class="small">${esc(nd.note)}</span>`;
    container.appendChild(box);
  });

  // Entries table
  if (result.entries && result.entries.length) {
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `<h2>DETECTED CODES</h2>`;
    const table = document.createElement("table");
    table.innerHTML = `
      <thead><tr>
        <th>Code</th><th>Meaning</th><th>Value</th><th>Status</th><th>Why this code</th><th></th>
      </tr></thead><tbody></tbody>`;
    const tbody = table.querySelector("tbody");
    result.entries.forEach((e) => {
      const tr = document.createElement("tr");
      const traceHtml = `
        <div class="trace">
          <div><b>Source:</b> ${esc(e.source_text || "")}</div>
          <div><b>Matched trigger:</b> ${esc(e.matched_trigger || "")}</div>
          <div><b>Rule source:</b> ${esc(e.rule_source || "")}</div>
          <div><b>Confidence:</b> ${esc(e.confidence || "")}</div>
          ${e.note ? `<div><b>Note:</b> ${esc(e.note)}</div>` : ""}
        </div>`;
      tr.innerHTML = `
        <td><span class="code-chip">${esc(e.code)}</span></td>
        <td>${esc(e.meaning || "")}<br><span class="small">${esc(e.category || "")}</span></td>
        <td class="mono">${esc(e.value || "")}</td>
        <td>${statusBadge(e.status)}</td>
        <td>${traceHtml}</td>
        <td><button class="btn btn-ghost btn-sm" data-copy="${esc(e.code)} ${esc(e.value || "")}">COPY</button></td>`;
      tbody.appendChild(tr);
    });
    card.appendChild(table);
    container.appendChild(card);
  } else {
    const box = document.createElement("div");
    box.className = "info-box";
    box.innerHTML = "No M-Codes were matched from this input. Check the VERIFY/NOT DETECTED messages above.";
    container.appendChild(box);
  }

  // Payment panel
  if (result.payment) {
    const p = result.payment;
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `<h2>PAYMENT</h2>
      <div class="row">
        <b style="font-size:15px">${p.term ? esc(p.term) : "—"}</b>
        ${p.status === "CONFIRMED" ? '<span class="badge badge-green">EXPLICITLY PRINTED</span>' : statusBadge(p.status)}
        ${p.status === "CONFIRMED" ? "" : '<span class="badge badge-orange">VERIFY WITH TRAINER</span>'}
      </div>
      <div class="trace mt"><b>Source:</b> ${esc(p.source_text || "none")} &nbsp; <b>Rule source:</b> ${esc(p.rule_source)}</div>
      <p class="small mt">${esc(p.note || "")}</p>`;
    container.appendChild(card);
  }

  // Description panel
  if (result.description) {
    const d = result.description;
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `<h2>DESCRIPTION</h2>
      <div class="row">
        <span>FLUSH: ${d.flush ? "yes" : "no"}</span>
        <span>NMFC: ${d.nmfc ? esc(d.nmfc) : "—"}</span>
        <span>CLASS: ${d.class ? esc(d.class) : "—"}</span>
        <span>R LINE: ${d.r_line ? "yes" : "—"}</span>
        <span>RDG: ${d.rdg ? "yes" : "—"}</span>
        <span class="right">${statusBadge(d.status)}</span>
      </div>
      <p class="small mt">${esc(d.note || "")}</p>`;
    container.appendChild(card);
  }

  // Suggested Tenet/EBS entries
  if (result.suggested_entries && result.suggested_entries.length) {
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `<div class="row"><h2 style="margin:0">SUGGESTED TENET/EBS ENTRIES</h2>
      <button class="btn btn-green btn-sm right" id="copy-all">COPY ALL</button></div>
      <p class="small mb">Copy-friendly. This assistant never enters data into production systems.</p>
      <div class="suggested" id="suggested-block"></div>`;
    container.appendChild(card);
    const block = card.querySelector("#suggested-block");
    result.suggested_entries.forEach((s) => {
      const row = document.createElement("div");
      row.className = "srow";
      row.innerHTML = `<span class="scode">${esc(s.code)}</span><span class="sval">${esc(s.value)}</span>
        ${s.status !== "CONFIRMED" ? statusBadge(s.status) : ""}
        <button class="btn btn-ghost btn-sm copy-btn" data-copy="${esc(s.code)}\t${esc(s.value)}">COPY</button>`;
      block.appendChild(row);
    });
    const copyAll = card.querySelector("#copy-all");
    copyAll.addEventListener("click", () => {
      const text = result.suggested_entries.map((s) => `${s.code}\t${s.value}`).join("\n");
      copyText(text).then(() => { copyAll.textContent = "COPIED ✓"; setTimeout(() => (copyAll.textContent = "COPY ALL"), 1500); });
    });
  }

  // Local bindings for copy buttons
  container.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", () => {
      copyText(btn.dataset.copy).then(() => {
        const old = btn.textContent;
        btn.textContent = "COPIED ✓";
        setTimeout(() => (btn.textContent = old), 1500);
      });
    });
  });

  container.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ------------------------------------------------------------------ */
/* Search UI (shared by search page + master page)                    */
/* ------------------------------------------------------------------ */

function renderSearchResults(results, container) {
  container.innerHTML = "";
  if (!results.length) {
    container.innerHTML = `<div class="info-box">No matching M-Codes. Try a trigger phrase, meaning, or partial code.</div>`;
    return;
  }
  results.forEach((r) => {
    const div = document.createElement("div");
    div.className = "result";
    div.innerHTML = `
      <div class="row">
        <span class="code-chip" style="font-size:15px">${esc(r.code)}</span>
        <b>${esc(r.meaning)}</b>
        <span class="right"><span class="badge badge-blue">${esc(r.category)}</span></span>
      </div>
      ${r.triggers && r.triggers.length ? `<div class="small mt">Trigger phrases: ${r.triggers.map(esc).join(", ")}</div>` : ""}
      ${r.example ? `<div class="small">Example: ${esc(r.example)}</div>` : ""}`;
    container.appendChild(div);
  });
}

/* Init: highlight active nav */
document.addEventListener("DOMContentLoaded", () => {
  const page = document.body.dataset.page;
  if (page) {
    document.querySelectorAll(".nav a").forEach((a) => {
      if (a.dataset.nav === page) a.classList.add("active");
    });
  }
});