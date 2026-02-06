const qs = new URLSearchParams(location.search);
const sid = qs.get('sid') || (document.body?.dataset?.defaultSid) || 'anon';
document.getElementById('sidSpan').textContent = sid;
let selectedSlotId = null;
let _phase2WasOk = false;
let _phase1WasOk = false;

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
  file: $('file'),
    docHint: $('docHint'),
  uploads_list: $('uploads_list'),
  btnUseSlot: $('btnUseSlot'),
  btnUpload: $('btnUpload'), btnValidate: $('btnValidate'),
  slotsBox: $('slotsBox'), valMsg: $('valMsg'),
  locSelect: $('loc'), slotSelect: $('slot'),
  btnCreateCase: $('btnCreateCase'), result: $('result'),
   row_doc_cert: $('row_doc_cert'),
    row_doc_addr: $('row_doc_addr'),
  row_doc_ci: $('row_doc_ci')
};


// Install shared wizard step handler (typed + legacy steps)
if (typeof window.installWizardSteps === 'function') {
  window.installWizardSteps(
      cfg = {
          ids: { slotsBox: 'slotsBox', loc: 'loc', slot: 'slot', docSelect: 'docHint' },
          applyAutofill: (fields) => {
            // Map known fields into CI form
            try {
              if (fields.cnp && el.cnp) el.cnp.value = fields.cnp;
              if (fields.nume && el.nume) el.nume.value = fields.nume;
              if (fields.prenume && el.prenume) el.prenume.value = fields.prenume;
              if (fields.email && el.email) el.email.value = fields.email;
              if (fields.telefon && el.telefon) el.telefon.value = fields.telefon;
              if (fields.adresa && el.adresa) el.adresa.value = fields.adresa;
            } catch(_) {}
          }
      });
}
/* Defaults (used last) */
const defaults = {
  cnp: "1230903226868",
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


function hasSlotSelected() {
  return !!selectedSlotId;
}


/* Helper for eligibility and reason */
function applyEligibilityDocRules() {
  const elig = el.elig.value;
  const type = el.type.value;

  const needsCert = (elig === 'AGE_14' || elig === 'LOSS');
  const needsAddr = (elig === 'CHANGE_ADDR' || type === 'VR');
  const needsOldCI = (elig !== 'AGE_14');  // Only when AGE_14 it doesn't require ci_veche

  // Hide/show rows
  if (el.row_doc_cert) el.row_doc_cert.style.display = needsCert ? '' : 'none';
  if (el.row_doc_addr) el.row_doc_addr.style.display = needsAddr ? '' : 'none';
  if (el.row_doc_ci) el.row_doc_ci.style.display = needsOldCI ? '' : 'none';

  // VR (viza resedinta) forces eligibility CHANGE_ADDR and locks it
  if (type === 'VR') {
    const before = el.elig.value;
    el.elig.value = 'CHANGE_ADDR';
    el.elig.disabled = true;

    if (before !== 'CHANGE_ADDR' && window.ChatWidget?.sendSystem) {
      window.ChatWidget.sendSystem(
        'Pentru viza flotant, motivul este schimbare adresa. A fost setat automat.'
      );
    }
  }
  else {
    el.elig.disabled = false;
  }

  // If user selected something and the rules were applied, enable the gate
    const eligGateOk = (el.type.value !== "None") &&   (el.elig.value !== 'None');

  const phase2Ok = eligGateOk && hasSlotSelected();
  if (phase2Ok) {
    // Only notify the chatbot when we Enter Phase 2 (transition false -> true)
    if (!_phase2WasOk) {
      if (window.ChatWidget && typeof window.ChatWidget.sendSystem === 'function') {
        window.ChatWidget.sendSystem('__phase2_done__');
      }
    }
    setGate(true, gateApp);
  } else {
    setGate(false, gateApp);
  }

  _phase2WasOk = phase2Ok;
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
  if (elig !== 'AGE_14') req.push('ci_veche'); // footprint needed

  return req;
}

/* Upload document with session awareness */
async function uploadDoc(){
  const f = el.file.files?.[0];
  const kindHint = (el.docHint?.value || "auto").trim() || "auto";
  if(!f){ alert('Choose a file first.'); return; }
  if(f.size > (10 * 1024 * 1024)){ alert('File too large (>10 MB).'); return; }

  const fd = new FormData();
  fd.append('file', f);
  fd.append('docHint', kindHint);
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

// OCR recognized kinds (source of truth)
const recognizedKinds = new Set();


// OCR refresh (shared implementation)
const refreshDocsFromOCR = (typeof window.createOcrRefresher === 'function')
  ? window.createOcrRefresher({
      sid,
      uploadsUrl: '/uploads',
      recognizedKinds,
      uploadsListId: 'uploads_list',
      checkboxMap: {
        doc_cert: 'cert_nastere',
        doc_ci: 'ci_veche',
        doc_addr: 'dovada_adresa',
      },
      toastFn: window.toast
    })
  : async () => {};
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
            selected_slot_id: selectedSlotId,
            type_elig_confirmed: (el.type.value !== "None" && el.elig.value !== "None" && selectedSlotId),
            type: el.type.value, // CEI / CIS / CIP / VR
            program: 'carte_identitate',
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

  // default prompt option
  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = '— select a slot —';
  placeholder.disabled = true;
  placeholder.selected = true;
  selectEl.appendChild(placeholder);

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
  //   if (!selectedSlotId && el.slotSelect.options.length > 0) {
  //     el.slotSelect.value = el.slotSelect.options[0].value;
  //   }
}

// ------------------ Step 1: Use slot (unlock Step 2) ------------------
if (el.btnUseSlot) {
  el.btnUseSlot.onclick = async () => {
    const id = el.slotSelect?.value;
    if (!id) { alert('Choose a slot first'); return; }

    const opt = el.slotSelect.selectedOptions?.[0];

    selectedSlotId = id;

    const chosen = {
      id,
      when: opt ? opt.textContent : '',
      location_id: el.locSelect?.value || '',
      sid
    };

    // Unlock Step 2, keep Step 3 locked until type+elig gate is OK
    setGate(true, gateEligType);
    setGate(false, gateApp);

    if (slotPicked) slotPicked.textContent = `Selected: ${chosen.when} @ ${chosen.location_id}`;

    try { sessionStorage.setItem('preselected_slot', JSON.stringify(chosen)); } catch(_) {}

    // Tell backend we selected the slot (CI style)
    try {
      const payload = makePayload();
      const r = await fetch('/api/select_slot', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      const j = await r.json();
      const is_ok = !!j?.ok;

      // Send phase1 marker only once (transition)
      if (is_ok && !_phase1WasOk) {
        if (window.ChatWidget && typeof window.ChatWidget.sendSystem === 'function') {
          window.ChatWidget.sendSystem('__phase1_done__');
        }
        _phase1WasOk = true;
      }
    } catch (e) {
      // In demo, do not block UI if API fails.
      if (!_phase1WasOk && window.ChatWidget && typeof window.ChatWidget.sendSystem === 'function') {
        window.ChatWidget.sendSystem('__phase1_done__');
      }
      _phase1WasOk = true;
    }

    // Re-evaluate phase2 gate (type+elig + slot)
    if (typeof applyEligibilityDocRules === 'function') {
      applyEligibilityDocRules();
    }
  };
}


/* Validate form */
el.btnValidate.onclick = async () => {
    // ignore double clicks
    if (el.btnValidate.disabled) return;
    el.btnValidate.disabled = true;
    if (!selectedSlotId || el.type.value === "None" || el.elig.value === "None") {
      toast?.('Alege mai intai slot, apoi Motiv si Tip cerere.', 'warn', 'Pas necesar');
      el.btnValidate.disabled = false;
      return;
        }

    const oldText = el.btnValidate.textContent;
    el.btnValidate.textContent = 'Validating...';

    try{
        // Check required docs based on eligibility and type
        await refreshDocsFromOCR();
        const req = requiredDocKinds();
        const missingReq = req.filter(k => !recognizedKinds.has(k));
        if (missingReq.length) {
          el.valMsg.classList.remove('hidden');
          el.valMsg.className = 'err';
          el.valMsg.textContent = 'Lipsesc documente obligatorii: ' + missingReq.join(', ');
          el.btnValidate.disabled = false;
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
        el.btnValidate.disabled = false;
        return;
      }

      const missing = Array.isArray(j.missing) ? j.missing : [];
      if (missing.length) {
        el.valMsg.className = 'err';
        el.valMsg.innerHTML = `<div class="err" style="margin-top:6px">Missing: ${missing.join(', ')}</div>`;
        el.slotsBox.classList.add('hidden');
        el.btnValidate.disabled = false;
        return;
      }

      // No missing docs -> we’re done with this form, go to confirmation.
      el.valMsg.className = 'ok';
      el.valMsg.textContent = ' Mergem la confirmare...';

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
          el.btnValidate.disabled = false;
          return '';
        })();
        setTimeout(() => { window.location.href = target; }, 400);
    }
    finally {
        // If we are navigating away, no need to re-enable
        // but re-enabling is harmless if navigation is blocked.
        el.btnValidate.textContent = oldText;
        el.btnValidate.disabled = false;
    }
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
      const prevLoc = el.locSelect.value;
      el.locSelect.value = ps.location_id || el.locSelect.value;

      if (el.locSelect.value !== prevLoc) {
        await fetchAndRenderSlots(el.locSelect.value);
      }

      el.slotSelect.value = ps.id || el.slotSelect.value;
      slotPicked.textContent = `Selected: ${ps.when || ''} @ ${ps.location_id || ''}`;

      selectedSlotId = ps.id;
      setGate(true, gateEligType);
      setGate(false, gateApp); // still locked until user selects app type and eligibility

      applyEligibilityDocRules();
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
  payload.application.ui_context = "carte_identitate";
  payload.application.selected_slot_id = selectedSlotId;
  payload.application.location_id = el.locSelect.value;

  return payload;
};
