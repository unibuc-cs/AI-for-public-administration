// static/js/user_social.js
// Social aid (Ajutor Social) wizard UI aligned with user_ci principles.
//
// Wizard principles:
//  - Step 1/3: user selects a slot (required before anything else).
//  - Step 2/3: user selects eligibility (motiv) + confirms it AND keeps slot selected.
//  - Step 3/3: user uploads required docs (OCR is source of truth), then Validate -> Confirm.
//
// Note: keep messages without diacritics (demo requirement).

const qs = new URLSearchParams(location.search);
const sid = qs.get('sid') || (document.body?.dataset?.defaultSid) || 'anon';
document.getElementById('sidSpan') && (document.getElementById('sidSpan').textContent = sid);

let selectedSlotId = null;
let _phase1WasOk = false;
let _phase2WasOk = false;

/* Fix microseconds like 2025-10-19T04:29:49.510815Z (JS Date only supports ms) */
function isoToDate(iso) {
  const s = String(iso).replace(/(\.\d{3})\d+(Z|[+-]\d{2}:\d{2})$/, '$1$2');
  return new Date(s);
}

function formatWhen(iso, { locale = 'ro-RO', timeZone = 'Europe/Bucharest' } = {}) {
  const d = isoToDate(iso);
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false, timeZone
  }).format(d);
}

/* Cache DOM refs */
const $ = (id) => document.getElementById(id);
const el = {
  locSelect: $('loc'),
  slotSelect: $('slot'),
  btnUseSlot: $('btnUseSlot'),
  slotPicked: $('slotPicked'),
  slotSelectedStatusText: $('slotSelectedStatusText'),

  gateEligType: $('gateEligType'),
  gateApp: $('gateApp'),

  cnp: $('cnp'), telefon: $('telefon'), nume: $('nume'), prenume: $('prenume'),
  email: $('email'), adresa: $('adresa'),

  elig: $('elig'),
  valMsg: $('valMsg'),

  file: $('file'),
  hint: $('docHint'),
  btnUpload: $('btnUpload'),
  uploads_list: $('uploads_list'),

  doc_cerere: $('doc_cerere'),
  doc_ci: $('doc_ci'),
  doc_venit: $('doc_venit'),
  doc_locuire: $('doc_locuire'),

  btnValidate: $('btnValidate'),
  btnCreateCase: $('btnCreateCase'),
};


// Install shared wizard step handler (typed + legacy steps)
if (typeof window.installWizardSteps === 'function') {
  window.installWizardSteps({ ids: { slotsBox: 'slotsBox', loc: 'loc', slot: 'slot', docSelect: 'docHint' } });
}
/* Gates */
function setGate(open, gateRef) {
  if (!gateRef) return;
  if (open) gateRef.classList.remove('dim');
  else gateRef.classList.add('dim');
}

function hasSlotSelected() {
  return !!selectedSlotId;
}

/* OCR truth set */
const recognizedKinds = new Set();

function requiredDocKinds() {
  // Keep it simple for demo:
  return ['cerere_ajutor', 'carte_identitate', 'acte_venit', 'acte_locuire'];
}

/* Render slot options */
function renderSlotOptions(selectEl, slots) {
  const prev = selectEl.value;
  selectEl.innerHTML = '';

  if (!Array.isArray(slots) || slots.length === 0) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = '— no slots —';
    selectEl.appendChild(opt);
    selectEl.disabled = true;
    return;
  }

  selectEl.disabled = false;

  // Placeholder prompt
  const ph = document.createElement('option');
  ph.value = '';
  ph.textContent = '— select a slot —';
  ph.disabled = true;
  ph.selected = true;
  selectEl.appendChild(ph);

  for (const s of slots) {
    const o = document.createElement('option');
    o.value = s.id;
    const whenTxt = s.when ? formatWhen(s.when) : String(s.when || '');
    o.textContent = `${whenTxt} — ${s.location_id || ''}`;
    selectEl.appendChild(o);
  }

  // Restore previous selection if still present; otherwise keep placeholder
  if (prev && [...selectEl.options].some(o => o.value === prev)) {
    selectEl.value = prev;
  } else {
    selectEl.value = '';
  }
}

async function fetchAndRenderSlots(locationId) {
  const r = await fetch(`/api/slots-social?location_id=${encodeURIComponent(locationId)}`);
  const slots = await r.json();
  renderSlotOptions(el.slotSelect, slots);
}

/* Eligibility gate logic (Phase 2 = slot + elig selected) */
function applyEligibilityRules() {
  const eligOk = (el.elig.value !== 'None');
  const phase2Ok = eligOk && hasSlotSelected();

  if (phase2Ok) {
    // Notify only on transition false -> true
    if (!_phase2WasOk) {
      if (window.ChatWidget && typeof window.ChatWidget.sendSystem === 'function') {
        window.ChatWidget.sendSystem('__phase2_done__');
      }
    }
    setGate(true, el.gateApp);
  } else {
    setGate(false, el.gateApp);
  }

  _phase2WasOk = phase2Ok;
}

/* Sync UI from OCR (server is source of truth) */
async function refreshDocsFromOCR() {
  const r = await fetch(`/uploads?session_id=${encodeURIComponent(sid)}`);
  if (!r.ok) return;
  const j = await r.json();

  recognizedKinds.clear();
  (j.recognized || []).forEach(k => recognizedKinds.add(k));

  // Tick read-only boxes based ONLY on OCR results.
  if (el.doc_cerere) el.doc_cerere.checked = recognizedKinds.has('cerere_ajutor');
  if (el.doc_ci) el.doc_ci.checked = recognizedKinds.has('carte_identitate');
  if (el.doc_venit) el.doc_venit.checked = recognizedKinds.has('acte_venit');
  if (el.doc_locuire) el.doc_locuire.checked = recognizedKinds.has('acte_locuire');

  const items = j.items || [];
  if (el.uploads_list) {
    el.uploads_list.innerHTML = items.length
      ? items.map(it => {
          const badge = it.kind ? `[${it.kind}]` : '';
          return `<div style="margin:4px 0">${it.filename} ${badge}</div>`;
        }).join('')
      : '<em>No files uploaded yet.</em>';
  }
}

async function uploadDoc() {
  const f = el.file?.files?.[0];
  if (!f) { alert('Choose a file first.'); return; }
  const kind = (el.hint?.value || '').trim();
  if (!kind) { alert('Select document type first.'); return; }

  const fd = new FormData();
  fd.append('file', f);
  fd.append('docHint', kind);
  fd.append('sid', sid);

  // Align with CI: upload endpoint is /upload
  const resp = await fetch('/upload', { method: 'POST', body: fd });
  if (!resp.ok) { alert('Upload failed: ' + await resp.text()); return; }

  el.file.value = '';
  await refreshDocsFromOCR();

  if (window.ChatWidget && typeof window.ChatWidget.sendSystem === 'function') {
    window.ChatWidget.sendSystem('__upload__');
    setTimeout(() => window.ChatWidget.sendSystem('__ping__'), 300);
  }
}

/* Payload */
function makeDocsFromOCR() {
  const docs = [];
  if (recognizedKinds.has('cerere_ajutor')) docs.push({ kind: 'cerere_ajutor', status: 'ok' });
  if (recognizedKinds.has('carte_identitate')) docs.push({ kind: 'carte_identitate', status: 'ok' });
  if (recognizedKinds.has('acte_venit')) docs.push({ kind: 'acte_venit', status: 'ok' });
  if (recognizedKinds.has('acte_locuire')) docs.push({ kind: 'acte_locuire', status: 'ok' });
  return docs;
}

function makePayload() {
  return {
    session_id: sid,
    person: {
      cnp: el.cnp.value.trim(),
      nume: el.nume.value.trim(),
      prenume: el.prenume.value.trim(),
      email: el.email.value.trim(),
      telefon: el.telefon.value.trim(),
      adresa: el.adresa.value.trim(),
      domiciliu: { adresa: el.adresa.value.trim(), docTip: null }
    },
    application: {
      program: 'AS',
      selected_slot_id: selectedSlotId,
      eligibility_reason: el.elig.value,
      // Phase2 is slot+elig
      type_elig_confirmed: (el.elig.value !== 'None' && !!selectedSlotId),
      docs: makeDocsFromOCR(),
    }
  };
}

/* Validate */
el.btnValidate.onclick = async () => {
  if (el.btnValidate.disabled) return;
  el.btnValidate.disabled = true;

  if (!selectedSlotId) {
    alert('Choose a slot first.');
    el.btnValidate.disabled = false;
    return;
  }
  if (el.elig.value === 'None') {
    alert('Select eligibility (motiv) first.');
    el.btnValidate.disabled = false;
    return;
  }

  const oldText = el.btnValidate.textContent;
  el.btnValidate.textContent = 'Validating...';

  try {
    await refreshDocsFromOCR();

    // Client-side quick check (server still validates)
    const req = requiredDocKinds();
    const missingReq = req.filter(k => !recognizedKinds.has(k));
    if (missingReq.length) {
      el.valMsg.classList.remove('hidden');
      el.valMsg.className = 'err';
      el.valMsg.textContent = 'Missing required docs: ' + missingReq.join(', ');
      el.btnValidate.disabled = false;
      el.btnValidate.textContent = oldText;
      return;
    }

    const payload = makePayload();
    const r = await fetch('/api/validate-social', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const j = await r.json();

    el.valMsg.classList.remove('hidden');
    if (!j.valid) {
      el.valMsg.className = 'err';
      el.valMsg.textContent = (j.errors || []).join(' • ');
      return;
    }
    if (Array.isArray(j.missing) && j.missing.length) {
      el.valMsg.className = 'err';
      el.valMsg.textContent = 'Missing: ' + j.missing.join(', ');
      return;
    }

    el.valMsg.className = 'ok';
    el.valMsg.textContent = 'Ok. Going to confirmation...';

    // Confirm page uses the preselected slot display
    const ps = JSON.parse(sessionStorage.getItem('preselected_slot') || 'null');
    const qp = ps ? `&appt_when=${encodeURIComponent(ps.when||'')}&appt_loc=${encodeURIComponent(ps.location_id||'')}` : '';
    setTimeout(() => {
      window.location.href = `/confirm-social?sid=${encodeURIComponent(sid)}${qp}`;
    }, 400);
  } finally {
    el.btnValidate.textContent = oldText;
    el.btnValidate.disabled = false;
  }
};

/* Create case & schedule */
if (el.btnCreateCase) {
  el.btnCreateCase.onclick = async () => {
    if (el.gateApp.classList.contains('dim')) { alert('Complete Step 2 first.'); return; }

    const payload = makePayload();

    const r1 = await fetch('/api/create_case_social', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const caseRes = await r1.json();

    const slot_id = selectedSlotId || el.slotSelect.value;
    const r2 = await fetch('/api/schedule-social', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slot_id, cnp: payload.person.cnp })
    });
    const sch = await r2.json();

    const a = (sch && sch.appointment) ? sch.appointment : null;
    if (a) {
      try { sessionStorage.setItem('last_appt', JSON.stringify(a)); } catch (_) {}
    }

    const ps = JSON.parse(sessionStorage.getItem('preselected_slot') || 'null');
    const qp = ps ? `&appt_when=${encodeURIComponent(ps.when||'')}&appt_loc=${encodeURIComponent(ps.location_id||'')}` : '';
    setTimeout(() => {
      window.location.href = `/confirm-social?sid=${encodeURIComponent(sid)}${qp}`;
    }, 400);
  };
}

/* Events */
el.locSelect.onchange = async () => {
  selectedSlotId = null;
  setGate(false, el.gateEligType);
  setGate(false, el.gateApp);
  if (el.slotPicked) el.slotPicked.textContent = '';
  await fetchAndRenderSlots(el.locSelect.value);
  if (el.slotSelectedStatusText) el.slotSelectedStatusText.textContent = 'Select a slot from the list.';
};


el.slotSelect.onchange = () => {
  // User changed dropdown; do NOT unlock gates until they click "Use this slot".
  selectedSlotId = null;
  setGate(false, el.gateEligType);
  setGate(false, el.gateApp);
  _phase1WasOk = false; // allow re-enter if they pick and use again

  if (el.slotPicked) el.slotPicked.textContent = '';
  if (el.slotSelectedStatusText) {
    const has = !!el.slotSelect.value;
    el.slotSelectedStatusText.textContent = has
      ? 'Slot selected. Click "Use this slot" to continue.'
      : 'No slot selected yet.';
  }
};

el.btnUseSlot.onclick = async () => {
  const id = el.slotSelect.value;
  if (!id) { alert('Choose a slot first'); return; }
  const opt = el.slotSelect.selectedOptions[0];

  // Build a lightweight object for display + restore
  const chosen = {
    id,
    when: opt ? opt.textContent : '',
    location_id: el.locSelect.value,
    sid
  };

  // Persist UI choice for restore
  try { sessionStorage.setItem('preselected_slot', JSON.stringify(chosen)); } catch (_) {}

  // Mark selection
  selectedSlotId = id;

  // Step 1 -> unlock Step 2
  setGate(true, el.gateEligType);
  setGate(false, el.gateApp);

  if (el.slotPicked) el.slotPicked.textContent = `Selected: ${chosen.when} @ ${chosen.location_id}`;
  try { sessionStorage.setItem('preselected_slot', JSON.stringify(chosen)); } catch (_) {}

  // Re-evaluate Phase2 gate (slot+elig)
  applyEligibilityRules();
};

el.btnUpload.onclick = uploadDoc;
el.elig.addEventListener('change', applyEligibilityRules);

/* Init */
document.addEventListener('DOMContentLoaded', async () => {
  await refreshDocsFromOCR();
  await fetchAndRenderSlots(el.locSelect.value);
  if (el.slotSelectedStatusText) el.slotSelectedStatusText.textContent = 'Select a slot from the list.';

  // Locked at start
  setGate(false, el.gateEligType);
  setGate(false, el.gateApp);

  if (window.ChatWidget && typeof window.ChatWidget.sendSystem === 'function') {
    window.ChatWidget.sendSystem('Pentru inceput, selecteaza un slot de programare.');
  }

  // Restore preselected slot (if same sid)
  try {
    const ps = JSON.parse(sessionStorage.getItem('preselected_slot') || 'null');
    if (ps && ps.sid === sid) {
      const prevLoc = el.locSelect.value;
      el.locSelect.value = ps.location_id || el.locSelect.value;

      if (el.locSelect.value !== prevLoc) {
        await fetchAndRenderSlots(el.locSelect.value);
  if (el.slotSelectedStatusText) el.slotSelectedStatusText.textContent = 'Select a slot from the list.';
      }

      el.slotSelect.value = ps.id || el.slotSelect.value;
      if (el.slotPicked) el.slotPicked.textContent = `Selected: ${ps.when || ''} @ ${ps.location_id || ''}`;
      selectedSlotId = ps.id;
      _phase1WasOk = true;

      setGate(true, el.gateEligType);
      applyEligibilityRules();
    }
  } catch (_) {}
});

/* Expose form state to the shared chat widget */
window.getFormPayload = function () {
  if (!selectedSlotId) {
    try {
      const pre = JSON.parse(sessionStorage.getItem('preselected_slot') || 'null');
      if (pre && pre.id) selectedSlotId = pre.id;
    } catch (_) {}
  }

  const payload = makePayload();
  payload.application = payload.application || {};
  payload.application.ui_context = 'social';
  payload.application.selected_slot_id = selectedSlotId;
  payload.application.location_id = el.locSelect.value;
  payload.application.program = 'AS';
  return payload;
};
