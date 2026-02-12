(function(){
  const root = document.getElementById('chatwrap');
  const sid = root.getAttribute('data-sid') || 'anon';
  const ctx = (root.getAttribute('data-ui-context') || 'entry').toLowerCase();

  document.getElementById('chatsid').textContent = sid;

  const sub = document.getElementById('chatsub');
  if (ctx === 'carte_identitate') sub.textContent = 'Wizard for Identity Card (CI)';
  else if (ctx === 'social') sub.textContent = 'Wizard for Social Help (Ajutor Social)';
  else if (ctx === 'taxe') sub.textContent = 'Wizard for Taxes (Taxe si Impozite)';
  else if (ctx === 'operator') sub.textContent = 'Operator console assistant';
  else sub.textContent = 'Public assistant';

  const log = document.getElementById('chatlog');
  const input = document.getElementById('chatinput');
  const btn = document.getElementById('chatsend');

  function renderMiniMarkdown(s){
    const t = String(s || '');

    // escape HTML first (security)
    let out = t
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

    // **bold**
    out = out.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");

    // new lines
    out = out.replace(/\n/g, "<br>");

    return out;
  }


  function addMsg(role, text){
    const row = document.createElement('div');
    row.className = 'msgrow ' + (role === 'user' ? 'user' : 'bot');
    const bubble = document.createElement('div');
    bubble.className = 'bubble ' + (role === 'user' ? 'user' : 'bot');

    const t = String(text || '');
    const m = t.match(/(\/user-carte_identitate\?sid=[^\s]+|\/user-social\?sid=[^\s]+|\/user-taxe\?sid=[^\s]+)/);
    if (m){
      const url = m[0];
      const parts = t.split(url);
      bubble.innerHTML = renderMiniMarkdown(parts[0]);
      const a = document.createElement('a');
      a.href = url;
      a.className = 'chatlink';
      a.innerHTML = url;
      bubble.appendChild(a);
      bubble.appendChild(document.createTextNode(parts.slice(1).join(url)));
    } else {
      bubble.innerHTML = renderMiniMarkdown(t);
    }

    row.appendChild(bubble);
    log.appendChild(row);
    log.scrollTop = log.scrollHeight;
  }

  function hasAnyValue(obj){
    if (!obj || typeof obj !== 'object') return false;
    for (const k of Object.keys(obj)){
      const v = obj[k];
      if (v === null || v === undefined) continue;
      if (typeof v === 'string' && v.trim() !== '') return true;
      if (typeof v === 'number') return true;
      if (typeof v === 'object' && hasAnyValue(v)) return true;
    }
    return false;
  }

  function getPayload(text){
    let form = {};
    try {
      if (typeof window.getFormPayload === 'function') {
        form = window.getFormPayload() || {};
      }
    } catch (e) {}

    const app = (form.application && typeof form.application === 'object') ? form.application : {};
    if (!app.ui_context) app.ui_context = ctx;

    const payload = {
      session_id: sid,
      message: text,
      application: app,
    };

    if (hasAnyValue(form.person)) payload.person = form.person;

    return payload;
  }

  async function sendText(text, opts){
    const options = opts || {};
    const msg = String(text || '').trim();
    if (!msg) return;

    if (!options.silentUser) addMsg('user', msg);

    btn.disabled = true;

    try {
      const payload = getPayload(msg);
      const resp = await fetch('/api/chat', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      const data = await resp.json();

      if (!resp.ok){
        const err = (data && (data.detail || data.error)) || ('HTTP ' + resp.status);
        addMsg('bot', 'Error: ' + err);
        return;
      }

      addMsg('bot', data.reply || 'OK');

      if (data.steps && Array.isArray(data.steps) && data.steps.length){
        const ev = new CustomEvent('chat-steps', {detail: {steps: data.steps}});
        window.dispatchEvent(ev);
      }
    } catch (e){
      addMsg('bot', 'Communication error.');
    } finally {
      btn.disabled = false;
      input.focus();
    }
  }

  function send(){
    const msg = input.value.trim();
    if (!msg) return;
    input.value = '';
    return sendText(msg, {silentUser: false});
  }

  // Public API used by forms (e.g., after upload)
  window.ChatWidget = window.ChatWidget || {};
  window.ChatWidget.send = function(text){ return sendText(text, {silentUser: false}); };
  window.ChatWidget.sendSystem = function(text){ return sendText(text, {silentUser: true}); };

  btn.addEventListener('click', send);
  input.addEventListener('keydown', function(e){
    if (e.key === 'Enter' && !e.shiftKey){
      e.preventDefault();
      send();
    }
  });

  window.addEventListener('chat-steps', (ev) => {
    try {
      const steps = (ev.detail && ev.detail.steps) || [];
      for (const st of steps) {
        if (!st || st.type !== 'navigate') continue;
        const p = st.payload || {};
        const url = p.path || p.url;
        if (url) {
          window.location.href = url;
          return;
        }
      }
    } catch (e) {}
  });

  // Bootstrap:  first message should come from backend (language selection or welcome), so we trigger it by sending an empty message
  try {
    setTimeout(() => {
      sendText('__start__', {silentUser: true});
    }, 0)
  } catch(e) {}
})();
