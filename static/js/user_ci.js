const qs = new URLSearchParams(location.search);
const sid = qs.get('sid') || (document.body?.dataset?.defaultSid) || 'anon';
document.getElementById('sidSpan').textContent = sid;
let selectedSlotId = null;


// Fix microseconds like 2025-10-19T04:29:49.510815Z (JS Date only supports ms)
function isoToDate(iso) {
  const s = String(iso).replace(
    /(\.\d{3})\d+(Z|[+-]\d{2}:\d{2})$/,
    '$1$2'
  );
  return new Date(s);
}

function formatWhen(iso, {
  locale = 'ro-RO',
  timeZone = 'Europe/Bucharest'
} = {}) {
  const d = isoToDate(iso);
  // dd.mm.yyyy, HH:MM (24h)
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone
  }).format(d);
}


/* Cache DOM refs explicitly (no implicit globals) */
const $ = (id) => document.getElementById(id);
const el = {
  cnp: $('cnp'), nume: $('nume'), prenume: $('prenume'),
  email: $('email'), telefon: $('telefon'), adresa: $('adresa'),
  docTip: $('docTip'),
  type: $('type'), elig: $('elig'),
  doc_cert: $('doc_cert'), doc_ci: $('doc_ci'), doc_addr: $('doc_addr'),
  file: $('file'), kind_hint: $('kind_hint'),
  uploads_list: $('uploads_list'),
  btnUpload: $('btnUpload'), btnValidate: $('btnValidate'),
  slotsBox: $('slotsBox'), valMsg: $('valMsg'),
  locSelect: $('loc'), slotSelect: $('slot'),
  btnCreateCase: $('btnCreateCase'), result: $('result'),
   row_doc_cert: $('row_doc_cert'),
    row_doc_addr: $('row_doc_addr'),
};

/* Defaults (used last) */
const defaults = {
  cnp: "1860903226868",
  nume: "Alin",
  prenume: "Stefanescu",
  email: "alin@fmi.unibuc.ro",
  telefon: "0754770829",
  adresa: "Bucuresti, sector 1, Str. Academiei nr 14, Fac. Matematica Informatica",
  docTip: "contract"
};

/* Apply values to inputs/selects */
function setVal(elm, val){
  if(!elm || val == null) return;
  if(elm.tagName === 'SELECT'){
    const exists = Array.from(elm.options).some(o => o.value === val);
    if(exists) elm.value = val;
  } else {
    elm.value = String(val);
  }
}

const prefill = defaults; // extend with URL/API/localStorage if desired
setVal(el.cnp, prefill.cnp);
setVal(el.nume, prefill.nume);
setVal(el.prenume, prefill.prenume);
setVal(el.email, prefill.email);
setVal(el.telefon, prefill.telefon);
setVal(el.adresa, prefill.adresa);
setVal(el.docTip, prefill.docTip);

/* Keep uploaded docs and recognized kinds */
const uploadedKinds = new Set();
const uploadItems = [];

/* Helper for eligibility and reason */
function applyEligibilityDocRules() {
  const elig = el.elig.value;
  const type = el.type.value;

  const needsCert = (elig === 'AGE_14' || elig === 'LOSS');
  const needsAddr = (elig === 'CHANGE_ADDR');

  // Hide/show rows
  if (el.row_doc_cert) el.row_doc_cert.style.display = needsCert ? '' : 'none';
  if (el.row_doc_addr) el.row_doc_addr.style.display = needsAddr ? '' : 'none';

  // VR (viza resedinta) forces eligibility CHANGE_ADDR and locks it
  if (type === 'VR') {
    el.elig.value = 'CHANGE_ADDR';
    el.elig.disabled = true;
  } else {
    el.elig.disabled = false;
  }

  // If user selected something and the rules were applied, enable the gate
    const eligGateOk = (el.type.value !== "None") &&   (el.elig.value !== 'None');
  if (eligGateOk) {
    setGate(true, gateApp);
  } else {
    setGate(false, gateApp);
  }
}

/* On eligibility/type change, apply rules */
el.type.addEventListener('change', applyEligibilityDocRules);
el.elig.addEventListener('change', applyEligibilityDocRules);

/* Determine required document kinds based on eligibility */
function requiredDocKinds() {
  const elig = el.elig.value;
  const type = el.type.value;
  const req = [];

  if (elig === 'AGE_14' || elig === 'LOSS') req.push('cert_nastere');
  if (elig === 'CHANGE_ADDR') req.push('dovada_adresa');
  if (type === 'VR') req.push('ci_veche'); // footprint needed

  return req;
}


/* Render uploaded list */
function renderUploads(items){
  const box = el.uploads_list;
  if(!items || !items.length){
    box.innerHTML = '<em>No files uploaded yet.</em>';
    return;
  }
  box.innerHTML = items.map(it=>{
    const img = it.thumb ? `<img src="${it.thumb}" class="thumb">` : '';
    const ocr = it.kind ? `[${it.kind}]` : '';
    const open = it.path ? `<a href="${it.path}" target="_blank">open</a>` : '';
    return `<div style="display:flex;align-items:center;margin:4px 0">${img}<span>${it.name} ${ocr} ${open}</span></div>`;
  }).join('');
}

/* Upload document with session awareness */
async function uploadDoc(){
  const f = el.file.files?.[0];
  const hint = el.kind_hint.value;
  if(!f){ alert('Choose a file first.'); return; }
  if(f.size > (10 * 1024 * 1024)){ alert('File too large (>10 MB).'); return; }

  const fd = new FormData();
  fd.append('file', f);
  fd.append('kind_hint', hint);
  fd.append('sid', sid);

  const resp = await fetch('/upload', { method:'POST', body: fd });
  if(!resp.ok){ alert('Upload failed: ' + await resp.text()); return; }

  const j = await resp.json();

  // After successful upload, DO NOT tick any boxes here.
  // Just refresh OCR state from server.
  await refreshDocsFromOCR();

  if(window.ChatWidget && typeof window.ChatWidget.sendSystem === 'function') {
    window.ChatWidget.sendSystem('__upload__');
    // Set a slight delay to allow chat to process upload event and force a re-check in the CI agent.
    setTimeout(() => window.ChatWidget.sendSystem('__ping__'), 300);
  }
  // el.btnValidate.click(); // no auto-validate; bot will offer autofill first
  el.file.value = '';
}


/* Build payload */
function makePayload(){
  const docs = [];
  if (recognizedKinds.has('cert_nastere')) docs.push({kind:'cert_nastere', status:'ok'});
  if (recognizedKinds.has('ci_veche'))     docs.push({kind:'ci_veche', status:'ok'});
  if (recognizedKinds.has('dovada_adresa'))docs.push({kind:'dovada_adresa', status:'ok'});

  return {
    session_id: sid,
    person: {
      cnp: el.cnp.value.trim(), nume: el.nume.value.trim(), prenume: el.prenume.value.trim(),
      email: el.email.value.trim(), telefon: el.telefon.value.trim(),
        adresa: el.adresa.value.trim(),
        domiciliu: { adresa: el.adresa.value.trim(), docTip: el.docTip.value }
    },
    application:
        {
            type_elig_confirmed: !gateApp.classList.contains('dim'),
            type: el.type.value, // CEI / CIS / CIP / VR
            program: 'CI',
            eligibility_reason: el.elig.value,
            docs }
  };
}

function renderSlotOptions(selectEl, slots, { withLocation = false } = {}) {
  // keep current selection if still present
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

  for (const s of slots) {
    const o = document.createElement('option');
    o.value = s.id;
    o.textContent = withLocation
      ? `${formatWhen(s.when)} — ${s.location_id}`
      : formatWhen(s.when);
    selectEl.appendChild(o);
  }

  // restore selection if possible
  if (prev && [...selectEl.options].some(o => o.value === prev)) {
    selectEl.value = prev;
  }
}

/* Set the gate for entering things */
const gateApp = document.getElementById('gateApp');
const gateEligType = document.getElementById('gateEligType');
const slotPicked = document.getElementById('slotPicked');
const btnUseSlot = document.getElementById('btnUseSlot');

function setGate(open, gateRef) {
  if (open) gateRef.classList.remove('dim');
  else gateRef.classList.add('dim');
}

/* Render slot options (you already have renderSlotOptions) */
async function fetchAndRenderSlots(locationId) {
  const r = await fetch(`/api/slots?location_id=${encodeURIComponent(locationId)}`);
  const slots = await r.json();
  renderSlotOptions(el.slotSelect, slots, { withLocation: false });
  // preselect the first slot for convenience
  if (el.slotSelect.options.length > 0 && !el.slotSelect.value) {
    el.slotSelect.value = el.slotSelect.options[0].value;
  }
}

/* Validate form */
el.btnValidate.onclick = async () => {

    if (gateApp.classList.contains('dim')) {
      toast?.('Alege Motiv si Tip cerere mai prima oara.', 'warn', 'Pasul 2 necesar');
      return;
        }

    // Check required docs based on eligibility and type
    const req = requiredDocKinds();
    const missingReq = req.filter(k => !recognizedKinds.has(k));
    if (missingReq.length) {
      el.valMsg.classList.remove('hidden');
      el.valMsg.className = 'err';
      el.valMsg.textContent = 'Lipsesc documente obligatorii: ' + missingReq.join(', ');
      return;
    }

  const payload = makePayload();
  const r = await fetch('/api/validate', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  });
  const j = await r.json();

  el.valMsg.classList.remove('hidden');

  if (!j.valid) {
    el.valMsg.className = 'err';
    el.valMsg.textContent = (j.errors || []).join(' • ');
    el.slotsBox.classList.add('hidden');
    return;
  }

  const missing = Array.isArray(j.missing) ? j.missing : [];
  if (missing.length) {
    el.valMsg.className = 'err';
    el.valMsg.innerHTML = `<div class="err" style="margin-top:6px">Missing: ${missing.join(', ')}</div>`;
    el.slotsBox.classList.add('hidden');
    return;
  }

  // No missing docs -> we’re done with this form, go to confirmation.
  el.valMsg.className = 'ok';
  el.valMsg.textContent = ' Mergem la confirmare…';

  // Redirect to confirmation (do NOT reset here; reset happens on Confirm)
  const target = `/confirm-ci?sid=${encodeURIComponent(sid)}`
    + (() => {
      try {
        const a = JSON.parse(sessionStorage.getItem('last_appt') || 'null');
        if (a && (a.when || a.location_id)) {
          const qp = `&appt_when=${encodeURIComponent(a.when||'')}&appt_loc=${encodeURIComponent(a.location_id||'')}`;
          return qp;
        }
      } catch(_) {}
      const ps = JSON.parse(sessionStorage.getItem('preselected_slot') || 'null');
      if (ps && (ps.when || ps.location_id)) {
        return `&appt_when=${encodeURIComponent(ps.when||'')}&appt_loc=${encodeURIComponent(ps.location_id||'')}`;
      }
      return '';
    })();
    setTimeout(() => { window.location.href = target; }, 400);
};



/* Create case & schedule */
if (el.btnCreateCase) {
  el.btnCreateCase.onclick = async () => {
    const payload = makePayload();
    const slotid = el.slotSelect.value;
    const rc = await fetch('/api/create_case', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    const c = await rc.json();
    if (!c.case_id) {
      el.result.textContent = JSON.stringify(c);
      return;
    }
    const rs = await fetch('/api/schedule', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({apptype: payload.application.type, slot_id: slotid, case_id: c.case_id})
    });
    const s = await rs.json();
    el.result.textContent = `Case ${c.case_id} scheduled: ${JSON.stringify(s)}`;

    const a = (s && s.appointment) ? s.appointment : null;
    if (a) {
      try {
        sessionStorage.setItem('last_appt', JSON.stringify(a));
      } catch (_) {
      }
    }
  };
}

el.btnUpload.onclick = uploadDoc;

/* --- Chat ↔ Form bridge: consume chat steps to update UI --- */
function highlightMissing(missing) {
  el.valMsg.classList.remove('hidden');
  if (missing && missing.length) {
    el.valMsg.className = 'err';
    el.valMsg.innerHTML = 'Lipsesc documente: ' + missing.join(', ');
  } else {
    el.valMsg.className = 'ok';
    el.valMsg.textContent = 'Toate documentele sunt in regula.';
  }
  // DO NOT tick/untick checkboxes here — OCR owns truth.
}

async function renderSlotsFromStep(slots) {
  if (!Array.isArray(slots)) return;
  el.slotsBox.classList.remove('hidden');
  renderSlotOptions(el.slotSelect, slots, { withLocation:false });
}

function showSchedulingResult(s) {
  el.result.textContent = 'Programare: ' + JSON.stringify(s);
}

window.addEventListener('chat-steps', (ev) => {
  const { steps } = ev.detail || {};
  if (!Array.isArray(steps)) return;

  for (const step of steps) {
    if (step.missing) {
      const list = step.missing;
      if (list.length) {
        toast(`Mai lipsesc: ${list.join(', ')}`, 'warn', 'Documente lipsa');
      } else {
        toast('Toate documentele sunt in regula.', 'ok', 'Validare');
      }
      // keep your existing UI highlights if you already do them:
      if (typeof highlightMissing === 'function') highlightMissing(list);
    }
    if (step.autofill && step.autofill.fields) {
      const f = step.autofill.fields || {};
      // Fill only what we have; keep user's manual edits otherwise.
      if (f.cnp && el.cnp) el.cnp.value = f.cnp;
      if (f.nume && el.nume) el.nume.value = f.nume;
      if (f.prenume && el.prenume) el.prenume.value = f.prenume;
      if (f.adresa && el.adresa) el.adresa.value = f.adresa;
      toast('Am completat automat câmpurile din OCR. Verifica si corecteaza daca e nevoie.', 'ok', 'Autofill');
    }
    if (step.slots) {
      toast(`Am gasit ${step.slots.length} sloturi`, 'info', 'Programari');
      if (typeof renderSlotsFromStep === 'function') renderSlotsFromStep(step.slots);
    }
    if (step.scheduling) {
      const a = step.scheduling.appointment || {};
      toast(`${a.when || ''} @ ${a.location_id || ''}`, 'ok', 'Programare creata');
      if (typeof showSchedulingResult === 'function') showSchedulingResult(step.scheduling);
    }
    if (step.toast) {
      // generic toast from backend sugar (explained below)
      const t = step.toast;
      toast(t.msg || '', t.type || 'info', t.title || '');
    }
  }
});

// ------------------ OCR / Upload integration ------------------
/* Keep OCR-recognized kinds ONLY (source of truth) */
  const recognizedKinds = new Set();

// Also refresh recognized docs after each upload (in case OCR ran server-side)
async function refreshDocsFromOCR(){
  const r = await fetch(`/uploads?session_id=${encodeURIComponent(sid)}`);
  if(!r.ok) return;
  const j = await r.json();

  // 1) Update OCR truth set
  recognizedKinds.clear();
  (j.recognized || []).forEach(k => recognizedKinds.add(k));

  toast(`OCR found ${recognizedKinds.size} document(s)`, 'info', 'OCR Update');

  // 2) Check the disabled checkboxes based ONLY on OCR
  el.doc_cert.checked = recognizedKinds.has('cert_nastere');
  el.doc_ci.checked   = recognizedKinds.has('ci_veche');
  el.doc_addr.checked = recognizedKinds.has('dovada_adresa');

  // 3) Render the upload list from server items
  const items = j.items || [];
  el.uploads_list.innerHTML = items.length
    ? items.map(it => {
        const ocrBadge = it.kind ? `[${it.kind}]` : '';
        return `<div style="margin:4px 0">${it.filename} ${ocrBadge}</div>`;
      }).join('')
    : '<em>No files uploaded yet.</em>';
}

/* Change location -> reload slots */
el.locSelect.onchange = async () => {
  await fetchAndRenderSlots(el.locSelect.value);
};

/* Use slot = unlock form (no reservation yet) */
btnUseSlot.onclick = () => {
  const id = el.slotSelect.value;
  if (!id) { alert('Choose a slot first'); return; }
  const opt = el.slotSelect.selectedOptions[0];
  // Build a lightweight object for display + later use
  selectedSlotId = id;
  const chosen = {
    id,
    when: opt ? opt.textContent : '',
    location_id: el.locSelect.value,
    sid
  };
  setGate(true, gateEligType);
  setGate(false, gateApp);
  slotPicked.textContent = `Selected: ${chosen.when} @ ${chosen.location_id}`;
  try { sessionStorage.setItem('preselected_slot', JSON.stringify(chosen)); } catch(_) {}
};


/* On load: show slots and keep form LOCKED */
document.addEventListener('DOMContentLoaded', async () => {
    await refreshDocsFromOCR();

  if(window.ChatWidget && typeof window.ChatWidget.sendSystem === 'function') {
    window.ChatWidget.sendSystem('Pentru inceput, selecteaza un slot de programare');
  }

    await fetchAndRenderSlots(el.locSelect.value);
    setGate(false, gateEligType); // locked at start
    // If user had a preselected slot (coming back), reflect it
    try {
    const ps = JSON.parse(sessionStorage.getItem('preselected_slot') || 'null');
    if (ps && ps.sid === sid) {
      el.locSelect.value = ps.location_id || el.locSelect.value;
      el.slotSelect.value = ps.id || el.slotSelect.value;
      slotPicked.textContent = `Selected: ${ps.when || ''} @ ${ps.location_id || ''}`;
      setGate(true, gateEligType);
      setGate(false, gateApp); // still locked until user selects app type and eligibility
    }
    } catch(_) {}
});


// Expose form state to the shared chat widget.
// The widget will attach this object as { person, application } in /api/chat.
window.getFormPayload = function () {
  // Keep the latest selected slot (also stored in sessionStorage)
  if (!selectedSlotId) {
    try {
      const pre = JSON.parse(sessionStorage.getItem('preselected_slot') || 'null');
      if (pre && pre.id) selectedSlotId = pre.id;
    } catch(_) {}
  }

  // Mirror the same payload shape used by the Validate/Create Case buttons.
  const payload = makePayload();

  // Add UI hints the chatbot can use.
  payload.application = payload.application || {};
  payload.application.ui_context = "ci";
  payload.application.selected_slot_id = selectedSlotId;
  payload.application.location_id = el.locSelect.value;

  return payload;
};
