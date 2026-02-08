// static/js/shared_wizard_steps.js
// Shared UI step handling for all wizard forms.
// Goal: reuse across many forms (CI, Social, future forms).
//
// Step schema (new):
//   { type: "toast|navigate|focus_field|open_section|highlight_missing_docs|hubgov_action", payload: {...} }
//
// No diacritics.

(function(){
  function _id(x){ return document.getElementById(x); }

  function _scroll(el){
    if (!el) return;
    try { el.scrollIntoView({behavior:'smooth', block:'center'}); } catch(_) {}
  }

  function _flash(el){
    if (!el) return;
    const prev = el.style.boxShadow;
    el.style.boxShadow = '0 0 0 3px rgba(59,130,246,0.45)';
    setTimeout(() => { el.style.boxShadow = prev; }, 1200);
  }

  function focusField(fieldId){
    const el = _id(fieldId);
    if (!el) return;
    _scroll(el);
    try { el.focus(); } catch(_) {}
    _flash(el);
  }

  function openSection(sectionId){
    const el = _id(sectionId);
    if (!el) return;
    _scroll(el);
    _flash(el);
  }

  function highlightMissingDocs(docSelectId, kinds){
    if (!Array.isArray(kinds) || kinds.length === 0) return;

    // toast summary
    if (window.toast) window.toast('Mai lipsesc: ' + kinds.join(', '), 'warn', 'Documente lipsa');

    // highlight select options if present
    const sel = _id(docSelectId || '') || _id('docHint')
    if (sel && sel.tagName === 'SELECT') {
      for (const opt of sel.options) opt.textContent = opt.textContent.replace(/^! /, '');
      const wanted = new Set(kinds);
      for (const opt of sel.options) {
        const v = String(opt.value || '').trim();
        if (wanted.has(v) && !String(opt.textContent||'').startsWith('! ')) {
          opt.textContent = '! ' + opt.textContent;
        }
      }
      _flash(sel);
    }
  }

  function handleHubGovAction(cfg, payload){
    const action = payload && payload.action ? payload.action : '';
    if (window.toast) window.toast('HubGov: ' + action, 'info', 'HubGov');

    // guide user to slots
    const slotsBoxId = (cfg && cfg.ids && cfg.ids.slotsBox) ? cfg.ids.slotsBox : 'slotsBox';
    const locId = (cfg && cfg.ids && cfg.ids.loc) ? cfg.ids.loc : 'loc';
    if (action === 'hubgov_slots' || action === 'hubgov_reserve') {
      openSection(slotsBoxId);
      focusField(locId);
    }
  }

  
function applyAutofill(cfg, fields){
  if (!fields || typeof fields !== 'object') return;
  // Allow per-page mapper to decide how to apply fields (keeps shared code generic)
  if (cfg && typeof cfg.applyAutofill === 'function') {
    try { cfg.applyAutofill(fields); } catch(_) {}
    return;
  }
  // Default: try to set by matching ids (cnp, nume, prenume, email, telefon, adresa)
  for (const k of Object.keys(fields)) {
    const el = _id(k);
    if (el && 'value' in el) el.value = String(fields[k] ?? '');
  }
}

function handleStep(cfg, step){
  if (!step || typeof step !== 'object' || !step.type) return;
  const t = step.type;
  const p = step.payload || {};

  if (t === 'toast') {
    if (window.toast) window.toast(p.message||'', p.level||'info', p.title||'');
    return;
  }
  if (t === 'navigate') {
    if (p.url) window.location.href = p.url;
    return;
  }
  if (t === 'focus_field') {
    if (p.field_id) focusField(p.field_id);
    return;
  }
  if (t === 'open_section') {
    if (p.section_id) openSection(p.section_id);
    return;
  }
  if (t === 'highlight_missing_docs') {
    const docSel = (cfg && cfg.ids && cfg.ids.docSelect) ? cfg.ids.docSelect : null;
    highlightMissingDocs(docSel, p.kinds || []);
    return;
  }
  if (t === 'hubgov_action') {
    handleHubGovAction(cfg, p);
    return;
  }
  if (t === 'autofill_apply') {
    applyAutofill(cfg, p.fields || {});    return;
  }
}

function install(cfg){
    cfg = cfg || {};
    window.WizardSteps = {
      handleStep: (s) => handleStep(cfg, s),
      focusField,
      openSection,
      highlightMissingDocs: (kinds) => {
        const docSel = (cfg.ids && cfg.ids.docSelect) ? cfg.ids.docSelect : null;
        highlightMissingDocs(docSel, kinds || []);
      }
    };

    window.addEventListener('chat-steps', (ev) => {
      const steps = (ev && ev.detail) ? ev.detail.steps : null;
      if (!Array.isArray(steps)) return;
      for (const s of steps) handleStep(cfg, s);
    });
  }

  window.installWizardSteps = install;

  
  window.createOcrRefresher = function createOcrRefresher(cfg) {
    cfg = cfg || {};
    const sid = cfg.sid || 'anon';
    const uploadsUrl = cfg.uploadsUrl || '/uploads';
    const recognizedKinds = cfg.recognizedKinds; // Set() recommended
    const uploadsListId = cfg.uploadsListId || null;

    // Option A (recommended): checkboxMap = { checkboxId: 'kind_name', ... }
    // Option B (legacy): docCheckboxIds + kindMap (cert/ci/addr)
    const checkboxMap = cfg.checkboxMap || null;
    const docCheckboxIds = cfg.docCheckboxIds || {};
    const kindMap = cfg.kindMap || { cert: 'cert_nastere', ci: 'ci_veche', addr: 'dovada_adresa' };

    const toastFn = cfg.toastFn || null;

    function _id(x) { return document.getElementById(x); }

    return async function refreshDocsFromOCR() {
      const url = `${uploadsUrl}?session_id=${encodeURIComponent(sid)}`;
      const r = await fetch(url);
      if (!r.ok) return;

      const j = await r.json();

      // 1) Update OCR truth set
      if (recognizedKinds && typeof recognizedKinds.clear === 'function') {
        recognizedKinds.clear();
        (j.recognized || []).forEach(k => recognizedKinds.add(k));
      }

      const has = (k) => {
        if (recognizedKinds && typeof recognizedKinds.has === 'function') return recognizedKinds.has(k);
        return Array.isArray(j.recognized) ? j.recognized.includes(k) : false;
      };

      // 2) Update read-only checkboxes based ONLY on OCR results.
      if (checkboxMap && typeof checkboxMap === 'object') {
        for (const [cbId, kind] of Object.entries(checkboxMap)) {
          const cb = _id(cbId);
          if (cb) cb.checked = has(kind);
        }
      } else {
        const certBox = _id(docCheckboxIds.cert || '');
        const ciBox   = _id(docCheckboxIds.ci || '');
        const addrBox = _id(docCheckboxIds.addr || '');

        if (certBox) certBox.checked = has(kindMap.cert);
        if (ciBox)   ciBox.checked   = has(kindMap.ci);
        if (addrBox) addrBox.checked = has(kindMap.addr);
      }

      // 3) Render upload list
      if (uploadsListId) {
        const listEl = _id(uploadsListId);
        if (listEl) {
          const items = j.items || [];
          listEl.innerHTML = items.length
            ? items.map(it => {
                const badge = it.kind ? `[${it.kind}]` : '';
                return `<div style="margin:4px 0">${it.filename} ${badge}</div>`;
              }).join('')
            : '<em>No files uploaded yet.</em>';
        }
      }

      // 4) Optional toast
      if (toastFn && recognizedKinds && recognizedKinds.size) {
        toastFn(`OCR found ${recognizedKinds.size} document(s)`, 'info', 'OCR Update');
      }
    };
  }; // end of   window.createOcrRefresher

})();
