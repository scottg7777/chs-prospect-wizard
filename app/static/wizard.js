/* CHS Practice Discovery wizard. No third-party code, no trackers. */
(() => {
  "use strict";
  const token = (location.pathname.split("/").filter(Boolean)[1] || "").trim();
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const card = $("#card");

  const STEPS = [
    { id: "welcome", name: "Welcome" },
    { id: "states", name: "Where you practice" },
    { id: "payers", name: "Insurance payers" },
    { id: "practice", name: "Practice details" },
    { id: "specialty", name: "Specialty & setup" },
    { id: "providers", name: "Your providers" },
    { id: "rcm", name: "Billing & timing" },
    { id: "contact", name: "Best way to reach you" },
    { id: "review", name: "Review" },
    { id: "done", name: "All set" },
  ];
  const CREDENTIALS = ["MD", "DO", "NP", "PMHNP", "PA", "CNM", "CRNA", "PhD", "PsyD", "LCSW", "LPC", "LMHC", "LMFT", "LCPC", "LADC / LCADC", "BCBA", "PT", "OT", "SLP", "DC", "DPM", "OD", "RD", "Other"];

  let INV = null, A = {}, LISTS = { states: {}, specialties: [], ehrs: [] };
  let step = 0, dirty = false, saveTimer = null, pendingTin = null, tinEditing = false;
  let payerData = null, payerKey = "", payerMap = {}, searchTimer = null;

  // ----------------------------------------------------------------- data helpers
  const parts = (p) => p.split(".");
  function get(path, obj = A) {
    return parts(path).reduce((o, k) => (o == null ? undefined : o[k]), obj);
  }
  function set(path, val) {
    const ks = parts(path);
    let o = A;
    ks.slice(0, -1).forEach((k, i) => {
      if (o[k] == null || typeof o[k] !== "object") o[k] = /^\d+$/.test(ks[i + 1]) ? [] : {};
      o = o[k];
    });
    o[ks[ks.length - 1]] = val;
  }
  const unsurePath = (path) => { const ks = parts(path); return [ks[0], "unsure", ks.slice(1).join("_") || "all"].join("."); };
  const isUnsure = (path) => !!get(unsurePath(path));
  const fid = (path) => "f-" + path.replace(/[^a-z0-9]/gi, "-");

  // ----------------------------------------------------------------- api + autosave
  async function api(method, path, body) {
    const r = await fetch(`/api/p/${encodeURIComponent(token)}${path}`, {
      method, credentials: "same-origin",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(data.detail || "Something went wrong."); e.status = r.status; throw e; }
    return data;
  }
  function payload() {
    const a = JSON.parse(JSON.stringify(A));
    a.practice = a.practice || {};
    delete a.practice.tin_on_file; delete a.practice.tin_masked;
    if (pendingTin !== null) { a.practice.tin = pendingTin; if (pendingTin === "") a.practice.tin_clear = true; }
    return { answers: a, step };
  }
  function setSave(cls, text) { const el = $("#save"); el.className = "save-state " + cls; $("#save-text").textContent = text; }
  function queueSave() { dirty = true; setSave("saving", "Saving…"); clearTimeout(saveTimer); saveTimer = setTimeout(saveNow, 700); }
  async function saveNow() {
    clearTimeout(saveTimer);
    if (!dirty) return;
    dirty = false;
    try {
      const r = await api("PUT", "/answers", payload());
      afterSave(r);
      setSave("saved", "Saved");
    } catch (e) {
      dirty = true;
      if (e.status === 404 || e.status === 410) return fatal(e.message);
      setSave("error", "Not saved yet, retrying…");
      saveTimer = setTimeout(saveNow, 4000);
    }
  }
  function afterSave(r) {
    if (pendingTin !== null) {
      A.practice = A.practice || {};
      A.practice.tin_on_file = r.answers.practice.tin_on_file;
      A.practice.tin_masked = r.answers.practice.tin_masked;
      pendingTin = null;
    }
    INV.status = r.status;
    if (r.warnings && r.warnings.length) toast(r.warnings[0], 5000);
  }
  window.addEventListener("beforeunload", (e) => { if (dirty) { saveNow(); e.preventDefault(); } });
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") saveNow(); });

  function toast(msg, ms = 2600) {
    const t = document.createElement("div");
    t.className = "toast"; t.textContent = msg; document.body.appendChild(t);
    setTimeout(() => t.remove(), ms);
  }
  function fatal(msg) {
    $("#nav").classList.add("hidden");
    card.innerHTML = `<div class="center"><div class="emoji">🔗</div><h1>Hmm, this link isn't working</h1><p class="lead">${esc(msg)}</p><p class="muted">For your security, each checklist link is personal and expires after a while. Your CHS contact can send a fresh one in seconds.</p></div>`;
  }

  // ----------------------------------------------------------------- UI builders
  function field(path, label, input, opts = {}) {
    const u = opts.unsure !== false && isUnsure(path);
    return `<div class="field" data-field="${path}">
      <div class="field-head"><label for="${fid(path)}">${label}</label>${opts.unsure === false ? "" : `<button type="button" class="unsure-toggle" data-unsure="${path}" aria-pressed="${u}">${u ? "✓ Not sure" : "Not sure"}</button>`}</div>
      ${input}${opts.hint ? `<div class="hint">${opts.hint}</div>` : ""}<div class="msg"></div>
      <div class="unsure-note ${u ? "" : "hidden"}">No problem, we'll sort this out together later.</div></div>`;
  }
  function text(path, o = {}) {
    return `<input id="${fid(path)}" type="${o.type || "text"}" data-bind="${path}" value="${esc(get(path) || "")}" placeholder="${esc(o.ph || "")}"${o.auto ? ` autocomplete="${o.auto}"` : ""}${o.mode ? ` inputmode="${o.mode}"` : ""}${o.max ? ` maxlength="${o.max}"` : ""}${isUnsure(o.unsurePath || path) ? " disabled" : ""}>`;
  }
  function choices(path, opts, o = {}) {
    const cur = get(path);
    const multi = !!o.multi;
    const on = (v) => (multi ? (cur || []).includes(v) : cur === v);
    const all = o.noUnsure ? opts : opts.concat([{ v: "unsure", label: o.unsureLabel || "Not sure yet", ico: "🤔", unsure: true }]);
    return `<div class="${o.chips ? "chips" : "choice-grid"}" role="group">` + all.map((x) =>
      `<button type="button" class="${o.chips ? "chip" : "choice"}${x.unsure ? " unsure" : ""}" data-${multi ? "multi" : "choice"}="${path}" data-value="${esc(x.v)}" aria-pressed="${on(x.v)}">${x.ico && !o.chips ? `<span class="ico">${x.ico}</span>` : ""}<span>${esc(x.label)}${x.sub ? `<small>${esc(x.sub)}</small>` : ""}</span></button>`).join("") + "</div>";
  }
  const head = (emoji, eyebrow, title, lead) => `<div class="emoji">${emoji}</div><p class="eyebrow">${eyebrow}</p><h1>${title}</h1>${lead ? `<p class="lead">${lead}</p>` : ""}`;

  // ----------------------------------------------------------------- steps
  const R = {};

  R.welcome = () => {
    const fn = INV.first_name ? `, ${esc(INV.first_name)}` : "";
    const back = INV.status === "in_progress" && step === 0 && (INV.current_step || 0) > 0;
    return `${head("👋", "Hi" + fn + "!", "Let's map out your practice together", `${esc(INV.rep_name)} at Continuant Healthcare Solutions put together this quick, guided checklist so we can prepare an accurate credentialing and billing quote${INV.practice_name ? ` for <strong>${esc(INV.practice_name)}</strong>` : ""}.`)}
      <div class="choice-grid">
        <div class="choice"><span class="ico">⏱️</span><span>About 5 minutes<small>One topic per screen</small></span></div>
        <div class="choice"><span class="ico">🤷</span><span>Nothing is required<small>Tap “Not sure” and keep going</small></span></div>
        <div class="choice"><span class="ico">💾</span><span>Saves as you go<small>Come back any time with the same link</small></span></div>
      </div>
      <div class="callout privacy"><strong>Your privacy:</strong> this is a private link made just for you, sent over an encrypted (HTTPS) connection. We only ask about your practice, never about patients, so please don't enter any patient information. Your answers are seen only by the CHS team preparing your quote, and your tax ID is stored encrypted.</div>
      <div class="mt"><button class="btn btn-primary" data-action="start" type="button">${back ? "Pick up where I left off" : "Let's go"} →</button>${back ? ` <button class="btn-link" data-action="restart" type="button">Start from the beginning</button>` : ""}</div>`;
  };

  R.states = () => {
    const sel = A.states || [];
    const names = LISTS.states;
    return `${head("🗺️", "Step 1", "Where do you practice?", "Pick every state where you see patients, including telehealth. We'll use this to show the insurance plans available to you.")}
      <div class="field"><input type="search" id="state-filter" placeholder="Type to filter states…" aria-label="Filter states"></div>
      <div class="state-grid" id="state-grid">${Object.entries(names).map(([k, n]) => `<button type="button" class="chip" data-state="${k}" aria-pressed="${sel.includes(k)}">${esc(n)}</button>`).join("")}</div>
      <div class="chips mt"><button type="button" class="chip unsure" data-action="states-unsure" aria-pressed="${!!A.states_unsure}">🤔 Not sure yet / still deciding</button></div>
      <p class="fun-fact" id="state-summary">${sel.length ? `Selected: ${sel.map((s) => esc(names[s])).join(", ")}` : "Tip: you can choose more than one."}</p>`;
  };

  function selectedPayers() { A.payers = A.payers || {}; A.payers.selected = A.payers.selected || {}; return A.payers.selected; }

  R.payers = () => {
    const sts = A.states || [];
    const sel = selectedPayers();
    let body;
    if (!sts.length) {
      body = `<div class="callout">You haven't picked a state yet, which is totally fine. <button class="btn-link" data-goto="states" type="button">Pick a state</button> to see a tailored list, or just tell us below which plans you're thinking about.</div>`;
    } else if (!payerData || payerKey !== sts.join(",")) {
      body = `<p class="muted">Finding the insurance plans for ${esc(sts.map((s) => LISTS.states[s]).join(", "))}…</p>`;
      loadPayers(sts);
    } else {
      const known = new Set();
      body = payerData.groups.map((g) => {
        const n = g.payers.filter((p) => sel[p.key]).length;
        g.payers.forEach((p) => known.add(p.key));
        return `<section class="group"><button class="group-head" type="button" data-action="toggle-group" aria-expanded="true">${groupIcon(g.group)} ${esc(g.group)}<span class="count">${n ? n + " selected" : g.payers.length + " options"}</span></button>
        <div class="group-body">${g.payers.map((p) => payerRow(p, sts.length > 1)).join("")}</div></section>`;
      }).join("");
      const extra = Object.entries(sel).filter(([k]) => !known.has(k));
      if (extra.length) body += `<section class="group"><button class="group-head" type="button" data-action="toggle-group">➕ Added by you<span class="count">${extra.length} selected</span></button><div class="group-body">${extra.map(([k, p]) => payerRow({ key: k, name: p.name, note: p.group === "Added by you" ? "Found in the Stedi payer network" : `From ${p.group}`, states: p.states || [] }, false)).join("")}</div></section>`;
      const mac = Object.entries(payerData.states).map(([s, i]) => `${esc(i.name)}: Medicare Part B is handled by ${esc(i.mac.contractor)} (Jurisdiction ${esc(i.mac.jurisdiction)})`).join(" · ");
      body = `<p class="fun-fact">${mac}</p>` + body;
    }
    return `${head("🏥", "Step 2", "Which insurance plans do you want to accept?", "Check all that apply. If you're already in network with a plan, let us know so we don't redo work.")}
      <div class="chips"><button type="button" class="chip unsure" data-action="payers-unsure" aria-pressed="${!!A.payers?.unsure}">🤔 Not sure which plans yet</button></div>
      <div id="payer-list">${body}</div>
      <h2>Don't see one?</h2>
      <div class="field searchbox"><input type="search" id="payer-q" placeholder="Search more plans by name (e.g. Ambetter, Molina)…" aria-label="Search payers" autocomplete="off"><div class="suggest hidden" id="payer-suggest"></div></div>
      ${field("payers.other", "Other plans or notes", `<textarea id="${fid("payers.other")}" data-bind="payers.other" placeholder="e.g. a local plan, workers' comp, or “we're thinking about Medicaid next year”">${esc(A.payers?.other || "")}</textarea>`, { unsure: false })}`;
  };
  const groupIcon = (g) => ({ "Government": "🏛️", "Medicaid managed care": "🤝", "Commercial": "💼", "Behavioral health & other": "🧠" }[g] || "📋");
  function payerRow(p, showStates) {
    const s = selectedPayers()[p.key];
    const nw = s ? s.in_network || "" : "";
    return `<div class="payer"><label class="payer-main"><input type="checkbox" data-payer="${esc(p.key)}" ${s ? "checked" : ""}><span><span class="payer-name">${esc(p.name)}</span>${showStates ? (p.states || []).map((x) => `<span class="badge">${esc(x)}</span>`).join("") : ""}${p.note ? `<div class="payer-note">${esc(p.note)}</div>` : ""}</span></label>
      ${s ? `<div class="innet">Already in network? <span class="seg">${[["yes", "Yes"], ["no", "No"], ["unsure", "Not sure"]].map(([v, l]) => `<button type="button" data-innet="${esc(p.key)}" data-value="${v}" aria-pressed="${nw === v}">${l}</button>`).join("")}</span></div>` : ""}</div>`;
  }
  async function loadPayers(sts) {
    try {
      const key = sts.join(",");
      const d = await api("GET", `/payers?states=${encodeURIComponent(key)}`);
      payerData = d; payerKey = key; payerMap = {};
      d.groups.forEach((g) => g.payers.forEach((p) => { payerMap[p.key] = { ...p, group: g.group }; }));
      if (STEPS[step].id === "payers") render(false);
    } catch (e) { $("#payer-list").innerHTML = `<div class="warnings">${esc(e.message)}</div>`; }
  }

  R.practice = () => {
    const p = A.practice || {};
    const tinOnFile = p.tin_on_file && !tinEditing;
    const tinInput = tinOnFile
      ? `<div class="chips"><span class="chip" aria-pressed="false">On file: ${esc(p.tin_masked || "")}</span><button type="button" class="btn btn-ghost btn-small" data-action="tin-change">Change</button></div>`
      : `<input id="${fid("practice.tin")}" type="text" inputmode="numeric" autocomplete="off" data-tin placeholder="12-3456789" maxlength="10"${isUnsure("practice.tin") ? " disabled" : ""}>`;
    const stOpts = `<option value="">State</option>` + Object.entries(LISTS.states).map(([k]) => `<option value="${k}"${get("practice.address.state") === k ? " selected" : ""}>${k}</option>`).join("");
    const addrDis = isUnsure("practice.address") ? " disabled" : "";
    return `${head("🏢", "Step 3", "Tell us about the practice", "These help us prepare enrollment paperwork. Skip anything you don't have handy.")}
      ${field("practice.legal_name", "Legal group name", text("practice.legal_name", { ph: "As registered with the IRS", auto: "organization" }))}
      ${field("practice.dba", "Doing business as (DBA)", text("practice.dba", { ph: "If different from the legal name" }))}
      <div class="row">
        ${field("practice.tin", "Tax ID (TIN / EIN)", tinInput, { hint: "9 digits. Stored encrypted and masked for our team." })}
        ${field("practice.group_npi", "Group NPI (Type 2)", `<input id="${fid("practice.group_npi")}" type="text" inputmode="numeric" maxlength="10" data-npi="practice.group_npi" value="${esc(p.group_npi || "")}" placeholder="10 digits"${isUnsure("practice.group_npi") ? " disabled" : ""}>`, { hint: "Optional. Don't have one yet? We can help." })}
      </div>
      ${field("practice.address", "Practice address", `<input type="text" id="${fid("practice.address")}" data-bind="practice.address.street" value="${esc(get("practice.address.street") || "")}" placeholder="Street address" autocomplete="street-address"${addrDis}>
        <div class="row-3 mt"><input type="text" data-bind="practice.address.city" value="${esc(get("practice.address.city") || "")}" placeholder="City" autocomplete="address-level2" aria-label="City"${addrDis}><select data-bind="practice.address.state" aria-label="State"${addrDis}>${stOpts}</select><input type="text" data-bind="practice.address.zip" value="${esc(get("practice.address.zip") || "")}" placeholder="ZIP" inputmode="numeric" maxlength="10" autocomplete="postal-code" aria-label="ZIP"${addrDis}></div>`, { hint: "Where patients are seen. Telehealth only? Use your business address." })}`;
  };

  R.specialty = () => {
    const tags = A.specialty?.specialties || [];
    const su = isUnsure("specialty.specialties");
    return `${head("🩺", "Step 4", "What kind of care do you provide?", "Start typing a specialty. Pick from the list or add your own words.")}
      ${field("specialty.specialties", "Specialty", `<div class="searchbox"><input type="search" id="spec-q" placeholder="e.g. Psychiatry, Family Medicine, Physical Therapy" autocomplete="off"${su ? " disabled" : ""}><div class="suggest hidden" id="spec-suggest"></div></div>
        <div class="tags">${tags.map((t, i) => `<span class="tag">${esc(t)}<button type="button" data-action="rm-spec" data-i="${i}" aria-label="Remove ${esc(t)}">✕</button></span>`).join("")}</div>`)}
      <h2>Is this a new or established practice?</h2>
      ${choices("specialty.practice_stage", [{ v: "new", label: "New practice", ico: "🌱", sub: "Opening soon or just opened" }, { v: "existing", label: "Established practice", ico: "🌳", sub: "Already seeing patients" }])}
      <h2>Solo or group?</h2>
      ${choices("specialty.practice_size", [{ v: "solo", label: "Solo", ico: "🙋" }, { v: "group", label: "Group", ico: "👥" }])}
      <h2>How do you see patients?</h2>
      ${choices("specialty.care_setting", [{ v: "in_person", label: "In person", ico: "🏠" }, { v: "telehealth", label: "Telehealth", ico: "💻" }, { v: "both", label: "Both", ico: "🔀" }])}`;
  };

  function ensureProviders() { A.providers = A.providers || {}; A.providers.list = A.providers.list || []; return A.providers; }
  R.providers = () => {
    const pv = ensureProviders();
    const cu = isUnsure("providers.count");
    return `${head("🧑‍⚕️", "Step 5", "Who will be seeing patients?", "Just names and credentials for now. No Social Security numbers or birthdates needed.")}
      ${field("providers.count", "How many providers need credentialing?", `<div class="stepper"><button type="button" data-action="count-dec" aria-label="Fewer"${cu ? " disabled" : ""}>−</button><output id="${fid("providers.count")}">${pv.count ?? "–"}</output><button type="button" data-action="count-inc" aria-label="More"${cu ? " disabled" : ""}>+</button></div>`, { hint: "Include any you plan to hire soon." })}
      <div id="prov-list">${pv.list.map((p, i) => provRow(p, i)).join("")}</div>
      <button type="button" class="btn btn-ghost" data-action="add-prov">＋ Add a provider</button>`;
  };
  function provRow(p, i) {
    const ini = (p.name || "").split(/\s+/).filter(Boolean).map((w) => w[0]).slice(0, 2).join("").toUpperCase() || i + 1;
    return `<div class="prov"><div class="prov-head"><div class="avatar">${esc(ini)}</div><strong>Provider ${i + 1}</strong><button type="button" class="btn-link prov-remove" data-action="rm-prov" data-i="${i}">Remove</button></div>
      <div class="row"><div class="field"><label for="pn${i}">Full name</label><input id="pn${i}" type="text" data-bind="providers.list.${i}.name" data-rerender-avatar="${i}" value="${esc(p.name || "")}" placeholder="First and last name"></div>
      <div class="field"><label for="pc${i}">Credential</label><select id="pc${i}" data-bind="providers.list.${i}.credential"><option value="">Choose…</option>${CREDENTIALS.map((c) => `<option${p.credential === c ? " selected" : ""}>${c}</option>`).join("")}<option value="unsure"${p.credential === "unsure" ? " selected" : ""}>Not sure</option></select></div></div>
      <div class="row"><div class="field"><label for="pi${i}">Individual NPI <span class="muted">(optional)</span></label><input id="pi${i}" type="text" inputmode="numeric" maxlength="10" data-npi="providers.list.${i}.npi" value="${esc(p.npi || "")}" placeholder="10 digits"><div class="msg"></div></div>
      <div class="field"><label>New to insurance credentialing?</label><div class="seg">${[["yes", "Yes"], ["no", "No"], ["unsure", "Not sure"]].map(([v, l]) => `<button type="button" data-seg="providers.list.${i}.new_to_credentialing" data-value="${v}" aria-pressed="${p.new_to_credentialing === v}">${l}</button>`).join("")}</div></div></div></div>`;
  }

  R.rcm = () => {
    const eu = isUnsure("rcm.ehr");
    return `${head("💳", "Step 6", "How do you handle billing today?", "Rough answers are perfect. This helps us size the right billing (RCM) plan.")}
      <h2>What can we help with?</h2>
      ${choices("rcm.services", [{ v: "credentialing", label: "Credentialing", ico: "📝", sub: "Getting in network with payers" }, { v: "rcm", label: "Billing / RCM", ico: "💵", sub: "Claims, payments, follow-up" }, { v: "consulting", label: "Consulting", ico: "🧭", sub: "Setup, strategy, compliance" }], { multi: true })}
      <h2>Current billing setup</h2>
      ${choices("rcm.billing_setup", [{ v: "in_house", label: "In-house staff", ico: "🏠" }, { v: "other_company", label: "Another billing company", ico: "🏢" }, { v: "none", label: "No billing yet", ico: "🆕" }])}
      <h2>Which EHR or practice management system?</h2>
      ${field("rcm.ehr", "EHR / PM system", `<div class="searchbox"><input type="search" id="${fid("rcm.ehr")}" data-bind="rcm.ehr" data-ehr value="${esc(A.rcm?.ehr || "")}" placeholder="e.g. Tebra, SimplePractice, athenahealth" autocomplete="off"${eu ? " disabled" : ""}><div class="suggest hidden" id="ehr-suggest"></div></div>`)}
      <h2>About how many claims a month?</h2>
      ${choices("rcm.monthly_claims", [["<100", "Under 100"], ["100-500", "100–500"], ["500-1500", "500–1,500"], ["1500-5000", "1,500–5,000"], ["5000+", "5,000+"], ["none_yet", "None yet"]].map(([v, l]) => ({ v, label: l })), { chips: true, unsureLabel: "🤔 Not sure" })}
      <h2>Roughly how much do you collect a month?</h2>
      ${choices("rcm.monthly_collections", [["<10k", "Under $10k"], ["10-50k", "$10k–$50k"], ["50-150k", "$50k–$150k"], ["150-500k", "$150k–$500k"], ["500k+", "$500k+"], ["none_yet", "None yet"]].map(([v, l]) => ({ v, label: l })), { chips: true, unsureLabel: "🤔 Not sure" })}
      <h2>When would you like to start?</h2>
      ${choices("rcm.go_live", [["asap", "ASAP"], ["1-3m", "1–3 months"], ["3-6m", "3–6 months"], ["6m+", "6+ months"]].map(([v, l]) => ({ v, label: l })), { chips: true, unsureLabel: "🤔 Not sure" })}`;
  };

  R.contact = () => `${head("📬", "Step 7", "How should we follow up?", "So we can send your quote to the right person.")}
      <div class="row">${field("contact.name", "Your name", text("contact.name", { auto: "name" }), { unsure: false })}${field("contact.title", "Role / title", text("contact.title", { ph: "e.g. Owner, Practice manager", auto: "organization-title" }), { unsure: false })}</div>
      <div class="row">${field("contact.email", "Email", text("contact.email", { type: "email", auto: "email", mode: "email" }), { unsure: false })}${field("contact.phone", "Phone", text("contact.phone", { type: "tel", auto: "tel", mode: "tel" }), { unsure: false })}</div>
      <h2>Preferred way to connect</h2>
      ${choices("contact.method", [["email", "Email"], ["phone", "Phone call"], ["text", "Text"], ["video", "Video call"]].map(([v, l]) => ({ v, label: l })), { chips: true, unsureLabel: "Any is fine" })}
      <h2>Best time to reach you</h2>
      ${choices("contact.best_time", [["mornings", "Mornings"], ["afternoons", "Afternoons"], ["evenings", "Evenings"]].map(([v, l]) => ({ v, label: l })), { chips: true, unsureLabel: "Anytime" })}
      <h2>Anything else we should know?</h2>
      ${field("contact.notes", "Questions, goals, or deadlines", `<textarea id="${fid("contact.notes")}" data-bind="contact.notes" placeholder="Anything on your mind. Please no patient information.">${esc(A.contact?.notes || "")}</textarea>`, { unsure: false })}`;

  const LABELS = {
    new: "New practice", existing: "Established practice", solo: "Solo", group: "Group", in_person: "In person", telehealth: "Telehealth", both: "In person & telehealth",
    credentialing: "Credentialing", rcm: "Billing / RCM", consulting: "Consulting", in_house: "In-house staff", other_company: "Another billing company", none: "No billing yet",
    none_yet: "None yet", asap: "ASAP", "1-3m": "1–3 months", "3-6m": "3–6 months", "6m+": "6+ months", unsure: "Not sure yet", email: "Email", phone: "Phone call", text: "Text", video: "Video call",
    mornings: "Mornings", afternoons: "Afternoons", evenings: "Evenings", yes: "Yes", no: "No",
  };
  const lab = (v) => (Array.isArray(v) ? v.map(lab).join(", ") : LABELS[v] || v);
  function kv(rows) {
    let skipped = 0;
    const html = rows.map(([k, v, path]) => {
      const u = path && isUnsure(path);
      const empty = v == null || v === "" || (Array.isArray(v) && !v.length);
      if (u || empty) skipped++;
      return `<dt>${k}</dt><dd>${u ? '<span class="skip-pill">Not sure</span>' : empty ? '<span class="skip-pill">Skipped</span>' : esc(lab(v))}</dd>`;
    }).join("");
    return { html: `<dl class="kv">${html}</dl>`, skipped };
  }
  R.review = () => {
    const pr = A.practice || {}, sp = A.specialty || {}, pv = A.providers || {}, rc = A.rcm || {}, c = A.contact || {};
    const sel = Object.values(A.payers?.selected || {});
    const addr = pr.address || {};
    const secs = [
      ["states", "🗺️ Where you practice", [["States", (A.states || []).map((s) => LISTS.states[s]), A.states_unsure ? "states" : null]]],
      ["payers", "🏥 Insurance plans", [["Selected", sel.map((p) => `${p.name}${p.in_network === "yes" ? " (in network)" : ""}`)], ["Other", A.payers?.other]]],
      ["practice", "🏢 Practice", [["Legal name", pr.legal_name, "practice.legal_name"], ["DBA", pr.dba, "practice.dba"], ["Tax ID", pendingTin ? "Saving…" : pr.tin_masked, "practice.tin"], ["Group NPI", pr.group_npi, "practice.group_npi"], ["Address", [addr.street, addr.city, addr.state, addr.zip].filter(Boolean).join(", "), "practice.address"]]],
      ["specialty", "🩺 Specialty & setup", [["Specialty", sp.specialties, "specialty.specialties"], ["Stage", sp.practice_stage], ["Size", sp.practice_size], ["Setting", sp.care_setting]]],
      ["providers", "🧑‍⚕️ Providers", [["How many", pv.count, "providers.count"], ["Names", (pv.list || []).filter((p) => p.name).map((p) => `${p.name}${p.credential && p.credential !== "unsure" ? ", " + p.credential : ""}`)]]],
      ["rcm", "💳 Billing & timing", [["Services", rc.services], ["Billing today", rc.billing_setup], ["EHR / PM", rc.ehr, "rcm.ehr"], ["Claims / month", rc.monthly_claims], ["Collections / month", rc.monthly_collections], ["Start", rc.go_live]]],
      ["contact", "📬 Contact", [["Name", c.name], ["Email", c.email], ["Phone", c.phone], ["Preferred", c.method], ["Best time", c.best_time]]],
    ];
    let skipped = 0;
    const html = secs.map(([id, title, rows]) => { const r = kv(rows); skipped += r.skipped; return `<div class="review-sec"><div class="head"><h3>${title}</h3><button type="button" class="btn btn-ghost btn-small" data-goto="${id}">Edit</button></div>${r.html}</div>`; }).join("");
    return `${head("✅", "Last step", "Here's what you shared", skipped ? `You left ${skipped} item${skipped === 1 ? "" : "s"} for later. That's completely fine, we'll fill in the gaps together.` : "Wow, you answered everything. Thank you!")}
      ${html}<div class="mt"><button class="btn btn-teal" type="button" data-action="submit">Send to ${esc(INV.rep_name)} 🚀</button></div>`;
  };

  R.done = () => `<div class="center">${head("🎉", "All set", `Thank you${INV.first_name ? ", " + esc(INV.first_name) : ""}!`, `Your answers are on their way to ${esc(INV.rep_name)}. We'll review them and follow up with your quote and next steps.`)}
      <div class="choice-grid"><div class="choice"><span class="ico">🔎</span><span>We review<small>Payers, providers and setup</small></span></div><div class="choice"><span class="ico">📄</span><span>You get a quote<small>Tailored to your practice</small></span></div><div class="choice"><span class="ico">🤝</span><span>We fill gaps together<small>Anything you skipped</small></span></div></div>
      <p class="mt muted">Need to change something? You can update your answers with the same link until ${esc(new Date(INV.expires_at).toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" }))}.</p>
      <button class="btn btn-ghost" type="button" data-action="edit">Edit my answers</button></div>`;

  // ----------------------------------------------------------------- render + navigation
  function render(scroll = true) {
    const s = STEPS[step];
    card.innerHTML = R[s.id]();
    card.classList.remove("card"); void card.offsetWidth; card.classList.add("card");
    const total = STEPS.length - 1;
    $("#bar").style.width = `${Math.round((step / total) * 100)}%`;
    $(".progress").setAttribute("aria-valuenow", Math.round((step / total) * 100));
    $("#step-name").textContent = s.name;
    $("#step-count").textContent = step > 0 && step < total - 1 ? `Step ${step} of ${total - 2}` : "";
    const nav = $("#nav");
    nav.classList.toggle("hidden", s.id === "welcome" || s.id === "done");
    $("#skip").classList.toggle("hidden", s.id === "review");
    $("#next").classList.toggle("hidden", s.id === "review");
    $("#next").textContent = s.id === "contact" ? "Review →" : "Next →";
    if (scroll) window.scrollTo({ top: 0, behavior: "smooth" });
    if (location.hash !== "#" + s.id) history.replaceState(null, "", "#" + s.id);
  }
  function go(n, opts = {}) {
    n = Math.max(0, Math.min(STEPS.length - 1, n));
    if (n === step && !opts.force) return;
    step = n;
    if (STEPS[n].id !== "done") { dirty = true; saveNow(); }
    if (opts.push !== false) history.pushState(null, "", "#" + STEPS[n].id);
    render();
  }
  window.addEventListener("popstate", () => {
    const i = STEPS.findIndex((s) => "#" + s.id === location.hash);
    if (i >= 0 && i !== step && STEPS[i].id !== "done") go(i, { push: false });
  });
  const cheers = { 2: "Nice! The hard part's done 🙌", 4: "Halfway there!", 6: "Almost there ✨" };
  $("#next").addEventListener("click", () => { if (cheers[step + 1]) toast(cheers[step + 1]); go(step + 1); });
  $("#back").addEventListener("click", () => go(step - 1));
  $("#skip").addEventListener("click", () => { A.skipped = A.skipped || {}; A.skipped[STEPS[step].id] = true; toast("Skipped for now, no problem."); go(step + 1); });

  // ----------------------------------------------------------------- events
  card.addEventListener("input", (e) => {
    const t = e.target;
    if (t.matches("[data-bind]")) {
      set(t.dataset.bind, t.value);
      if (t.dataset.rerenderAvatar !== undefined) {
        const av = t.closest(".prov").querySelector(".avatar");
        av.textContent = t.value.split(/\s+/).filter(Boolean).map((w) => w[0]).slice(0, 2).join("").toUpperCase() || +t.dataset.rerenderAvatar + 1;
      }
      queueSave();
    }
    if (t.matches("[data-tin]")) onTin(t);
    if (t.matches("[data-npi]")) onNpi(t);
    if (t.id === "state-filter") { const q = t.value.toLowerCase(); $$("#state-grid .chip").forEach((b) => b.classList.toggle("hidden", !b.textContent.toLowerCase().includes(q) && b.dataset.state.toLowerCase() !== q)); }
    if (t.id === "payer-q") { clearTimeout(searchTimer); searchTimer = setTimeout(() => payerSearch(t.value), 250); }
    if (t.id === "spec-q") specSuggest(t.value);
    if (t.matches("[data-ehr]")) ehrSuggest(t.value);
  });
  card.addEventListener("change", (e) => { const t = e.target; if (t.matches("select[data-bind]")) { set(t.dataset.bind, t.value); queueSave(); } if (t.matches("[data-payer]")) togglePayer(t.dataset.payer, t.checked); });
  card.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.id === "spec-q") { e.preventDefault(); addSpec(e.target.value); }
  });

  card.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    const d = b.dataset;
    if (d.unsure) return toggleUnsure(d.unsure, b);
    if (d.choice) { const cur = get(d.choice); set(d.choice, cur === d.value ? "" : d.value); queueSave(); return refreshPressed(`[data-choice="${d.choice}"]`, (x) => get(d.choice) === x.dataset.value); }
    if (d.multi) {
      let cur = (get(d.multi) || []).slice();
      if (cur.includes(d.value)) cur = cur.filter((v) => v !== d.value);
      else cur = d.value === "unsure" ? ["unsure"] : cur.filter((v) => v !== "unsure").concat([d.value]);
      set(d.multi, cur); queueSave();
      return refreshPressed(`[data-multi="${d.multi}"]`, (x) => cur.includes(x.dataset.value));
    }
    if (d.seg) { const cur = get(d.seg); set(d.seg, cur === d.value ? "" : d.value); queueSave(); return refreshPressed(`[data-seg="${d.seg}"]`, (x) => get(d.seg) === x.dataset.value); }
    if (d.state) return toggleState(d.state, b);
    if (d.innet) { const s = selectedPayers()[d.innet]; s.in_network = s.in_network === d.value ? "" : d.value; queueSave(); return refreshPressed(`[data-innet="${CSS.escape(d.innet)}"]`, (x) => s.in_network === x.dataset.value); }
    if (d.goto) return go(STEPS.findIndex((s) => s.id === d.goto));
    if (d.addpayer !== undefined) return addSearchedPayer(+d.addpayer);
    if (d.addspec !== undefined) return addSpec(d.addspec);
    if (d.setehr !== undefined) { set("rcm.ehr", d.setehr); queueSave(); const i = $("[data-ehr]"); i.value = d.setehr; $("#ehr-suggest").classList.add("hidden"); return; }
    switch (d.action) {
      case "start": return go(INV.status === "in_progress" && INV.current_step > 0 && INV.current_step < STEPS.length - 2 ? INV.current_step : 1);
      case "restart": return go(1);
      case "states-unsure": A.states_unsure = !A.states_unsure; queueSave(); b.setAttribute("aria-pressed", A.states_unsure); return;
      case "payers-unsure": A.payers = A.payers || {}; A.payers.unsure = !A.payers.unsure; queueSave(); b.setAttribute("aria-pressed", A.payers.unsure); return;
      case "toggle-group": { const body = b.nextElementSibling; const open = body.classList.toggle("hidden"); b.setAttribute("aria-expanded", !open); return; }
      case "tin-change": tinEditing = true; render(false); $("[data-tin]")?.focus(); return;
      case "rm-spec": A.specialty.specialties.splice(+d.i, 1); queueSave(); render(false); return;
      case "count-inc": { const pv = ensureProviders(); pv.count = Math.min(500, (pv.count || 0) + 1); while (pv.list.length < Math.min(pv.count, 25)) pv.list.push({}); queueSave(); render(false); return; }
      case "count-dec": { const pv = ensureProviders(); pv.count = Math.max(0, (pv.count || 0) - 1); queueSave(); $("#" + fid("providers.count")).textContent = pv.count; return; }
      case "add-prov": { const pv = ensureProviders(); pv.list.push({}); if ((pv.count || 0) < pv.list.length) pv.count = pv.list.length; queueSave(); render(false); $$("#prov-list .prov").pop().querySelector("input").focus(); return; }
      case "rm-prov": { const pv = ensureProviders(); pv.list.splice(+d.i, 1); queueSave(); render(false); return; }
      case "submit": return submit(b);
      case "edit": return go(1);
    }
  });
  function refreshPressed(sel, fn) { $$(sel, card).forEach((x) => x.setAttribute("aria-pressed", fn(x))); }

  function toggleUnsure(path, btn) {
    const up = unsurePath(path);
    const v = !get(up);
    set(up, v);
    queueSave();
    btn.setAttribute("aria-pressed", v);
    btn.textContent = v ? "✓ Not sure" : "Not sure";
    const f = btn.closest(".field");
    $$("input,select,textarea,.stepper button", f).forEach((i) => { i.disabled = v; });
    f.querySelector(".unsure-note").classList.toggle("hidden", !v);
  }
  function toggleState(st, b) {
    A.states = A.states || [];
    if (A.states.includes(st)) A.states = A.states.filter((x) => x !== st); else { A.states.push(st); A.states_unsure = false; $('[data-action="states-unsure"]').setAttribute("aria-pressed", "false"); }
    b.setAttribute("aria-pressed", A.states.includes(st));
    $("#state-summary").textContent = A.states.length ? "Selected: " + A.states.map((s) => LISTS.states[s]).join(", ") : "Tip: you can choose more than one.";
    queueSave();
  }
  function togglePayer(key, on) {
    const sel = selectedPayers();
    if (on) { const p = payerMap[key] || {}; sel[key] = { name: p.name, group: p.group, stedi_payer_id: p.stedi_payer_id, states: p.states || [], in_network: "" }; A.payers.unsure = false; }
    else delete sel[key];
    queueSave(); render(false);
  }
  let lastSearch = [];
  async function payerSearch(q) {
    const box = $("#payer-suggest");
    if (q.trim().length < 2) { box.classList.add("hidden"); return; }
    try {
      const r = await api("GET", `/payer-search?q=${encodeURIComponent(q)}&states=${encodeURIComponent((A.states || []).join(","))}`);
      lastSearch = r.results;
      box.innerHTML = r.results.length ? r.results.map((p, i) => `<button type="button" data-addpayer="${i}">${esc(p.name)} <span class="badge">${esc((p.states || []).slice(0, 3).join(" "))}</span></button>`).join("") : `<button type="button" disabled>No matches. Add it in the notes box below.</button>`;
      box.classList.remove("hidden");
    } catch (e) { box.classList.add("hidden"); }
  }
  function addSearchedPayer(i) {
    const p = lastSearch[i]; if (!p) return;
    selectedPayers()[p.key] = { name: p.name, group: "Added by you", stedi_payer_id: p.stedi_payer_id, states: p.states || [], in_network: "" };
    queueSave(); toast(`Added ${p.name}`); render(false);
  }
  function specSuggest(q) {
    const box = $("#spec-suggest"); q = q.trim();
    if (!q) { box.classList.add("hidden"); return; }
    const m = LISTS.specialties.filter((s) => s.toLowerCase().includes(q.toLowerCase())).slice(0, 8);
    const exact = m.some((s) => s.toLowerCase() === q.toLowerCase());
    box.innerHTML = m.map((s) => `<button type="button" data-addspec="${esc(s)}">${esc(s)}</button>`).join("") + (exact ? "" : `<button type="button" data-addspec="${esc(q)}">＋ Add “${esc(q)}”</button>`);
    box.classList.remove("hidden");
  }
  function addSpec(v) {
    v = (v || "").trim(); if (!v) return;
    A.specialty = A.specialty || {}; A.specialty.specialties = A.specialty.specialties || [];
    if (!A.specialty.specialties.includes(v)) A.specialty.specialties.push(v);
    queueSave(); render(false); $("#spec-q")?.focus();
  }
  function ehrSuggest(q) {
    const box = $("#ehr-suggest"); q = q.trim().toLowerCase();
    if (!q) { box.classList.add("hidden"); return; }
    const m = LISTS.ehrs.filter((s) => s.toLowerCase().includes(q)).slice(0, 8);
    if (!m.length) { box.classList.add("hidden"); return; }
    box.innerHTML = m.map((s) => `<button type="button" data-setehr="${esc(s)}">${esc(s)}</button>`).join("");
    box.classList.remove("hidden");
  }
  document.addEventListener("click", (e) => { if (!e.target.closest(".searchbox")) $$(".suggest").forEach((s) => s.classList.add("hidden")); });

  function onTin(t) {
    const d = t.value.replace(/\D/g, "").slice(0, 9);
    t.value = d.length > 2 ? `${d.slice(0, 2)}-${d.slice(2)}` : d;
    const msg = t.closest(".field").querySelector(".msg");
    if (d.length === 9 && !d.startsWith("00")) { pendingTin = d; msg.className = "msg ok"; msg.textContent = "✓ Looks good"; queueSave(); }
    else if (!d.length) { msg.textContent = ""; }
    else { msg.className = "msg bad"; msg.textContent = d.length < 9 ? `${9 - d.length} more digit${9 - d.length === 1 ? "" : "s"}` : "That doesn't look like a valid TIN"; }
  }
  function luhnNpi(n) {
    if (!/^\d{10}$/.test(n)) return false;
    const s = "80840" + n.slice(0, 9); let sum = 0;
    for (let i = 0; i < s.length; i++) { let d = +s[s.length - 1 - i]; if (i % 2 === 0) { d *= 2; if (d > 9) d -= 9; } sum += d; }
    return (10 - (sum % 10)) % 10 === +n[9];
  }
  function onNpi(t) {
    const d = t.value.replace(/\D/g, "").slice(0, 10); t.value = d;
    const msg = t.closest(".field").querySelector(".msg");
    if (!d) { set(t.dataset.npi, ""); msg.textContent = ""; queueSave(); return; }
    if (d.length < 10) { msg.className = "msg"; msg.textContent = `${10 - d.length} more digit${10 - d.length === 1 ? "" : "s"}`; return; }
    if (luhnNpi(d)) { set(t.dataset.npi, d); msg.className = "msg ok"; msg.textContent = "✓ Valid NPI format"; queueSave(); }
    else { set(t.dataset.npi, ""); msg.className = "msg bad"; msg.textContent = "Hmm, that NPI's check digit doesn't add up. Double-check it, or leave it for later."; queueSave(); }
  }

  async function submit(b) {
    b.disabled = true; b.textContent = "Sending…";
    clearTimeout(saveTimer);
    try {
      const r = await api("POST", "/submit", payload());
      dirty = false; afterSave(r); INV.status = "submitted"; setSave("saved", "Sent ✓");
      go(STEPS.length - 1); confetti();
    } catch (e) { b.disabled = false; b.textContent = "Try again"; toast(e.message, 4000); }
  }

  function confetti() {
    const c = $("#confetti"); c.classList.remove("hidden");
    const ctx = c.getContext("2d"); c.width = innerWidth; c.height = innerHeight;
    const colors = ["#0f8b8d", "#1d3557", "#3fb6a8", "#f2b705", "#e76f51", "#8ecae6"];
    const P = Array.from({ length: 170 }, () => ({ x: Math.random() * c.width, y: -20 - Math.random() * c.height * 0.5, r: 4 + Math.random() * 6, c: colors[(Math.random() * colors.length) | 0], vx: -2 + Math.random() * 4, vy: 2 + Math.random() * 4, a: Math.random() * 6, va: -0.2 + Math.random() * 0.4 }));
    const t0 = performance.now();
    (function frame(t) {
      ctx.clearRect(0, 0, c.width, c.height);
      P.forEach((p) => { p.x += p.vx; p.y += p.vy; p.vy += 0.05; p.a += p.va; ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.a); ctx.fillStyle = p.c; ctx.fillRect(-p.r / 2, -p.r / 2, p.r, p.r * 0.6); ctx.restore(); });
      if (t - t0 < 3200) requestAnimationFrame(frame); else c.classList.add("hidden");
    })(t0);
  }

  // ----------------------------------------------------------------- boot
  (async function boot() {
    if (!/^[A-Za-z0-9_-]{32,64}$/.test(token)) return fatal("This link is incomplete. Please copy the full link from your email.");
    try {
      const [inv, lists] = await Promise.all([api("GET", ""), fetch("/api/lists").then((r) => r.json())]);
      INV = inv; LISTS = lists; A = inv.answers || {};
      setSave("saved", inv.status === "not_started" ? "Your answers save automatically" : "Saved");
      const fromHash = STEPS.findIndex((s) => "#" + s.id === location.hash);
      if (inv.status === "submitted") step = STEPS.length - 1;
      else if (fromHash > 0 && fromHash < STEPS.length - 1) step = fromHash;
      else step = 0;
      render(false);
      if (inv.status === "in_progress" && step === 0 && inv.current_step > 0) toast("Welcome back! We saved your spot.");
    } catch (e) { fatal(e.message); }
  })();
})();
