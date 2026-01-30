(function(){
  const params = new URLSearchParams(location.search);
  const sid = params.get('sid') || "{{ sid }}";
let selectedSlotId = null;

  console.log("sid =", sid);


  const el = {
    locSelect:   document.getElementById('loc'),
    slotSelect:  document.getElementById('slot'),
    btnUseSlot:  document.getElementById('btnUseSlot'),
    slotPicked:  document.getElementById('slotPicked'),
    gate:        document.getElementById('gate'),
    cnp:         document.getElementById('cnp'),
    telefon:     document.getElementById('telefon'),
    nume:        document.getElementById('nume'),
    prenume:     document.getElementById('prenume'),
    email:       document.getElementById('email'),
    adresa:      document.getElementById('adresa'),
    elig:        document.getElementById('elig'),
    program:     document.getElementById('program'),
    valMsg:      document.getElementById('valMsg'),
    file:        document.getElementById('file'),
    hint:        document.getElementById('docHint'),
    btnUpload:   document.getElementById('btnUpload'),
    uploads_list:document.getElementById('uploads_list'),
    btnValidate: document.getElementById('btnValidate'),
    btnCreate:   document.getElementById('btnCreateCase'),
  };

  // OCR truth (programmatically toggles checkboxes; inputs are disabled)
  const recognizedKinds = new Set();
  const gate = el.gate;

  function setGate(open) {
    if (open) {
      gate.classList.remove('dim');
      el.btnUpload.disabled = false;
    } else {
      gate.classList.add('dim');
      el.btnUpload.disabled = true;
    }
  }

  function renderSlotOptions(sel, slots) {
    sel.innerHTML = '';

    for (const s of slots) {
        const o = document.createElement('option');
        o.value = s.id;
        o.textContent = `${s.when} - ${s.location_id}`;
        sel.appendChild(o);
    }
  }

  async function fetchAndRenderSlots(locationId) {
    const r = await fetch(`/api/slots-social?location_id=${encodeURIComponent(locationId)}`);
    const slots = await r.json();
    renderSlotOptions(el.slotSelect, slots);
    if (el.slotSelect.options.length > 0 && !el.slotSelect.value) {
      el.slotSelect.value = el.slotSelect.options[0].value;
    }
  }

  let _ocrRefreshCount = 0;

  async function refreshDocsFromOCR(){
      _ocrRefreshCount++;
    console.log("refreshDocsFromOCR count =", _ocrRefreshCount);
    console.trace("refreshDocsFromOCR called from:");

    const r = await fetch(`/uploads?session_id=${encodeURIComponent(sid)}`);
    if(!r.ok) return;
    const j = await r.json();
    recognizedKinds.clear();
    (j.recognized || []).forEach(k => recognizedKinds.add(k));
    // Tick read-only boxes based on OCR
    document.getElementById('doc_cerere').checked = recognizedKinds.has('cerere_ajutor');
    document.getElementById('doc_ci').checked     = recognizedKinds.has('carte_identitate');
    document.getElementById('doc_venit').checked  = recognizedKinds.has('acte_venit');
    document.getElementById('doc_locuire').checked= recognizedKinds.has('acte_locuire');

    const items = j.items || [];
    el.uploads_list.innerHTML = items.length
      ? items.map(it => `<div style="margin:4px 0">${it.filename} ${it.kind?`[${it.kind}]`:''}</div>`).join('')
      : '<em>Niciun fisier incarcat.</em>';
  }

  async function uploadDoc(){
    const f = el.file.files[0];
    if(!f){ alert('Alege un fisier'); return; }
    const fd = new FormData();
    fd.append('file', f);
    const kind = (el.hint && el.hint.value) ? String(el.hint.value) : '';
    if(!kind){ alert('Select document type.'); return; }
    fd.append('kind_hint', kind);
    fd.append('sid', sid);
    const r = await fetch(`/local/uploads`, { method:'POST', body: fd });
    if(!r.ok){ alert('Eroare upload'); return; }
    el.file.value = '';
    await refreshDocsFromOCR();

    if(window.ChatWidget && typeof window.ChatWidget.sendSystem === 'function') {
      window.ChatWidget.sendSystem('am incarcat documentele');
    }
  }

  function makeDocsFromOCR(){
    const docs = [];
    if (recognizedKinds.has('cerere_ajutor')) docs.push({kind:'cerere_ajutor', status:'ok'});
    if (recognizedKinds.has('carte_identitate')) docs.push({kind:'carte_identitate', status:'ok'});
    if (recognizedKinds.has('acte_venit')) docs.push({kind:'acte_venit', status:'ok'});
    if (recognizedKinds.has('acte_locuire')) docs.push({kind:'acte_locuire', status:'ok'});
    if (recognizedKinds.has('acte_familie')) docs.push({kind:'acte_familie', status:'ok'});
    if (recognizedKinds.has('cont_bancar')) docs.push({kind:'cont_bancar', status:'ok'});
    return docs;
  }

  function makePayload(){
    return {
      session_id: sid,
      person: {
        cnp: el.cnp.value.trim(), nume: el.nume.value.trim(), prenume: el.prenume.value.trim(),
        email: el.email.value.trim(), telefon: el.telefon.value.trim(),
        domiciliu: { adresa: el.adresa.value.trim(), docTip: null }
      },
      application: {
        program: "AS",
        eligibility_reason: el.elig.value,
        docs: makeDocsFromOCR()
      }
    };
  }

  // Events
  el.locSelect.onchange = async () => { await fetchAndRenderSlots(el.locSelect.value); };
  el.btnUseSlot.onclick = () => {
    const id = el.slotSelect.value;
  selectedSlotId = id;
    if (!id) { alert('Alege mai intâi un slot'); return; }
    const opt = el.slotSelect.selectedOptions[0];
    const chosen = { id, when: opt ? opt.textContent : '', location_id: el.locSelect.value, sid };
    setGate(true);
    el.slotPicked.textContent = `Selectat: ${chosen.when} @ ${chosen.location_id}`;
    try { sessionStorage.setItem('preselected_slot', JSON.stringify(chosen)); } catch(_) {}
  };
  el.btnUpload.onclick = uploadDoc;

  el.btnValidate.onclick = async () => {
    if (el.gate.classList.contains('dim')) { alert('Alege un slot mai intâi'); return; }
    const payload = makePayload();
    const r = await fetch('/api/validate-social', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
    const j = await r.json();
    el.valMsg.classList.remove('hidden');

    if (!j.valid) {
      el.valMsg.className = 'err';
      el.valMsg.textContent = (j.errors || []).join(' • ');
      return;
    }
    if (j.missing && j.missing.length) {
      el.valMsg.className = 'err';
      el.valMsg.innerHTML = `Lipseste: ${j.missing.join(', ')}`;
      return;
    }
    // success -> go to confirmation
    el.valMsg.className = 'ok';
    el.valMsg.textContent = 'Validare reusita. Mergem la confirmare…';

    sessionStorage.setItem('last_decided_type', 'AS');
    const ps = JSON.parse(sessionStorage.getItem('preselected_slot') || 'null');
    const qp = ps ? `&appt_when=${encodeURIComponent(ps.when||'')}&appt_loc=${encodeURIComponent(ps.location_id||'')}` : '';
    setTimeout(()=>{ window.location.href = `/confirm-social?sid=${encodeURIComponent(sid)}${qp}`; }, 400);
  };

  el.btnCreate.onclick = async () => {
    if (el.gate.classList.contains('dim')) { alert('Alege un slot mai intâi'); return; }
    // Create case (program=AS)
    const payload = makePayload();
    const r1 = await fetch('/api/create_case_social', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
    const caseRes = await r1.json();
    // Reserve chosen slot (LOCAL social)
    const slot_id = el.slotSelect.value;
    const r2 = await fetch('/api/schedule-social', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({
      slot_id, cnp: payload.person.cnp
    })});
    const sch = await r2.json();
    const a = (sch && sch.appointment) ? sch.appointment : null;
    if (a) { try { sessionStorage.setItem('last_appt', JSON.stringify(a)); } catch(_) {} }
    // Go to confirmation
    const qp = a ? `&appt_when=${encodeURIComponent(a.when||'')}&appt_loc=${encodeURIComponent(a.location_id||'')}` : '';
    setTimeout(()=>{ window.location.href = `/confirm-social?sid=${encodeURIComponent(sid)}${qp}`; }, 400);
  };

  // Init
  document.addEventListener('DOMContentLoaded', async () => {
    await fetchAndRenderSlots(el.locSelect.value);
    // await refreshDocsFromOCR();

    if(window.ChatWidget && typeof window.ChatWidget.sendSystem === 'function') {
      window.ChatWidget.sendSystem('am incarcat documentele');
    }
    setGate(false);
    try {
      const ps = JSON.parse(sessionStorage.getItem('preselected_slot') || 'null');
      if (ps && ps.sid === sid) {
        el.locSelect.value = ps.location_id || el.locSelect.value;
        el.slotSelect.value = ps.id || el.slotSelect.value;
        el.slotPicked.textContent = `Selectat: ${ps.when || ''} @ ${ps.location_id || ''}`;
        setGate(true);
      }
    } catch(_) {}
  });
})();

  // React to backend "steps" broadcast by the embedded chat widget.
  window.addEventListener('chat-steps', (ev) => {
    const { steps } = ev.detail || {};
    if (!Array.isArray(steps)) return;
    for (const step of steps) {
      if (step.navigate?.url) {
        toast(`<a href="${step.navigate.url}">${step.navigate.label || step.navigate.url}</a>`, 'info', 'Navigare');
      }
      if (step.missing) {
        const list = step.missing || [];
        if (list.length) toast(`Mai lipsesc: ${list.join(', ')}`, 'warn', 'Documente lipsa');
        else toast('Toate documentele sunt in regula.', 'ok', 'Validare');
      }
      if (step.slots) {
        toast(`Am gasit ${step.slots.length} sloturi`, 'info', 'Programari');
        try { renderSlotOptions(el.slotSelect, step.slots); } catch(_) {}
      }
      if (step.scheduling) {
        const a = step.scheduling.appointment || {};
        toast(`Programare creata: ${a.when || ''}`, 'ok', 'Confirmare');
      }
    }
  });


// Expose form state to the shared chat widget.
window.getFormPayload = function () {
  if (!selectedSlotId) {
    try {
      const pre = JSON.parse(sessionStorage.getItem('preselected_slot') || 'null');
      if (pre && pre.id) selectedSlotId = pre.id;
    } catch(_) {}
  }

  const payload = makePayload();
  payload.application = payload.application || {};
  payload.application.ui_context = "social";
  payload.application.selected_slot_id = selectedSlotId;
  payload.application.location_id = el.locSelect.value;
  // 'program' is used by SchedulingAgent to show local slots in chat when needed
  payload.application.program = "AS";
  return payload;
};
