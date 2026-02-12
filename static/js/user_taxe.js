(function(){
  const sid = (document.body.getAttribute('data-default-sid') || 'anon');
  const sidSpan = document.getElementById('sidSpan');
  if (sidSpan) sidSpan.textContent = sid;

  // Used by chat_widget.js
  window.getFormPayload = function(){
    const person = {
      cnp: (document.getElementById('cnp')||{}).value || '',
      nume: (document.getElementById('nume')||{}).value || '',
      prenume: (document.getElementById('prenume')||{}).value || '',
      email: (document.getElementById('email')||{}).value || '',
      telefon: (document.getElementById('telefon')||{}).value || '',
      adresa: (document.getElementById('adresa')||{}).value || ''
    };

    const app = {
      ui_context: 'taxe',
      program: 'TAXE'
    };

    return { person: person, application: app };
  };
})();
