/* The experimental page reuses the existing Bridge search and merge controller. */
(() => {
  'use strict';
  const panel = document.getElementById('customer-ai-panel');
  if (!panel) return;
  const api = panel.dataset.apiUrl;
  const modal = document.getElementById('customer-ai-dialog');
  const $ = id => document.getElementById('customer-ai-' + id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const display = value => value === null || value === undefined || value === '' ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value);
  const captions = {sw:'SW6', dj:'GC-Bridge', mt:'Microtech'};
  const labels = {api_id:'SW6-ID',erp_ans_nr:'Microtech AnsNr',erp_asp_nr:'Microtech AnspNr',erp_ans_id:'Microtech Anschrift-ID',erp_asp_id:'Microtech Ansprechpartner-ID',erp_combined_id:'Microtech Kombi-ID',id:'ID',customerNumber:'Kundennummer',erp_nr:'AdrNr',street:'Straße',zipcode:'PLZ',zipCode:'PLZ',postal_code:'PLZ',city:'Ort',company:'Firma',name:'Name',name1:'Name 1',name2:'Name 2',name3:'Name 3',email:'E-Mail',is_invoice:'Rechnungsadresse',is_shipping:'Lieferadresse',defaultBillingAddressId:'Rechnungsadresse SW6-ID',defaultShippingAddressId:'Lieferadresse SW6-ID',addressSubNumber:'AnsNr',contactNumber:'AnspNr'};
  let run = null, selected = 0, hovering = null, before = false, busy = false;
  let canApply = false, canMerge = false, pollTimer = null, generation = 0;
  let versions = [], retainedId = '', autoReviewKey = '', providerMessage = 'KI-Zugang wird geprüft…', providerReady = false;
  try { retainedId = sessionStorage.getItem('gc-customer-ai-run') || ''; } catch (_) { /* Optional recovery pointer only. */ }

  async function request(body, id) {
    const response = await fetch(id ? `${api}?run_id=${encodeURIComponent(id)}` : api, body ? {
      method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json','X-CSRFToken':CSRF}, body:JSON.stringify(body),
    } : {credentials:'same-origin'});
    let data;
    try { data = await response.json(); } catch (_) { throw new Error('Der Server hat keine lesbare Antwort geliefert. Bitte den Status prüfen.'); }
    if (!response.ok || data.error) throw new Error(data.error || 'Der KI-Auftrag konnte nicht verarbeitet werden.');
    return data;
  }
  function open() { if (!modal.open) modal.showModal(); }
  function error(message) { $('error').textContent = message; }
  function numbers() { return [...new Set(searchErps.map(String))].sort(); }
  function remember() { try { sessionStorage.setItem('gc-customer-ai-run', run.id); } catch (_) { /* Status remains available until page reload. */ } }
  function updateStart() {
    const size = numbers().length;
    const search = customerAISearchReadiness();
    $('start').lastChild.textContent = run && JSON.stringify(run.numbers) === JSON.stringify(numbers()) ? 'Vorschlag öffnen' : 'KI-Vorschlag anzeigen';
    if (swMergePending) document.getElementById('customer-ai-manual').open = true;
    $('start').disabled = !search.ready || !size || size > 8 || !providerReady || !$('provider').value || busy;
    if (!search.ready) $('status').textContent = search.message;
    else if (size > 8) $('status').textContent = 'Bitte die Suche auf höchstens acht Kunden eingrenzen, damit alle Daten vollständig analysiert werden.';
    else if (!providerReady || !$('provider').value) $('status').textContent = providerMessage;
    else if (!busy) $('status').textContent = search.message + ' Die Analyse wird über die API abgerechnet.';
  }
  function setBusy(value) {
    busy = value;
    $('provider').disabled = value || !$('provider').options.length;
    ['new','revise'].forEach(id => { $(id).disabled = value; });
    updateStart();
  }
  async function config() {
    try {
      const result = await request();
      canApply = result.can_apply; canMerge = result.can_merge;
      $('provider').replaceChildren();
      for (const p of result.providers) {
        const option = document.createElement('option'); option.value = String(p.id);
        option.textContent = `${p.name} · ${p.model}`; $('provider').append(option);
      }
      if (result.provider_admin_url) {
        $('provider-settings').href = result.provider_admin_url;
        $('provider-settings').classList.remove('hidden');
      }
      if (!result.providers.length) {
        providerMessage = 'Kein aktiver OpenAI-Provider mit API-Schlüssel vorhanden. Bitte unter KI-Provider einrichten.';
        $('provider').disabled = true;
      } else {
        $('status').textContent = 'API-Zugang vorhanden. Die Analyse wird über die API abgerechnet; übernommen wird erst nach deiner Bestätigung.';
        $('provider').disabled = false;
      }
      providerReady = result.providers.length > 0;
      updateStart();
      if (retainedId) {
        try {
          const restored = await request(null, retainedId);
          run = restored; selected = run.selected ?? 0;
          render();
          if (['loading','applying'].includes(run.status)) { setBusy(true); schedulePoll(); }
        } catch (_) { retainedId = ''; }
      }
    } catch (e) { providerReady = false; providerMessage = e.message; updateStart(); }
  }
  async function start(revise = false) {
    if (busy) return;
    if (!customerAISearchReadiness().ready) { error(customerAISearchReadiness().message); return; }
    const objection = $('objection').value.trim();
    if (revise && !objection) { error('Bitte zuerst einen Einwand formulieren.'); return; }
    const body = {action:'analyze', numbers:numbers(), provider_id:Number($('provider').value)};
    if (revise && run) Object.assign(body, {previous_id:run.id, objection});
    error(''); open(); setBusy(true); $('progress').textContent = 'Analyse wird gestartet…';
    try {
      const previous = run;
      const result = await request(body);
      if (previous?.proposals) versions.push(previous);
      versions = versions.slice(-5);
      run = result; selected = 0; hovering = null; before = false; autoReviewKey = '';
      $('objection').value = ''; $('revision').open = false;
      if (!revise) versions = [];
      remember(); render(); schedulePoll();
    } catch (e) { setBusy(false); error(e.message); }
  }
  function schedulePoll() {
    clearTimeout(pollTimer);
    const seq = ++generation;
    pollTimer = setTimeout(() => poll(seq), 1800);
  }
  async function poll(seq) {
    if (!run || seq !== generation) return;
    try {
      const result = await request(null, run.id);
      if (seq !== generation) return;
      run = result;
      render();
      if (['loading','applying'].includes(run.status)) pollTimer = setTimeout(() => poll(seq), 1800);
      else { setBusy(false); render(); remember(); }
    } catch (e) {
      // Never turn a status timeout into another paid request or another write.
      error(e.message + ' Es wird nichts automatisch erneut gesendet.');
      $('refresh').hidden = false; setBusy(true);
    }
  }
  function currentPlan() { return run?.proposals?.[hovering ?? selected]; }
  function canReview(plan) {
    if (!plan || plan.blocked || !plan.operations.length || plan.questions.length) return false;
    const merge = plan.operations[0].kind === 'merge_shopware';
    return merge ? canMerge : canApply || plan.operations.every(op => op.kind === 'link_customer');
  }
  function render() {
    if (!run) return;
    $('progress').textContent = `${run.message} ${run.version ? '· Version ' + run.version : ''}`;
    $('status').textContent = run.message;
    $('content').hidden = !run.proposals;
    $('refresh').hidden = !['loading','applying','needs_review'].includes(run.status);
    $('review').disabled = busy || !['ready','preview_ready'].includes(run.status) || !canReview(run.proposals?.[selected]);
    $('apply').hidden = run.status !== 'preview_ready' || run.selected !== selected || run.proposals?.[selected]?.operations[0]?.kind === 'merge_shopware';
    if (['failed','needs_review'].includes(run.status)) {
      error(run.message + (run.status === 'needs_review' ? ' Bereits bestätigte Einzelschritte können wirksam sein. Bitte die drei Systeme kontrollieren; den Auftrag nicht erneut ausführen.' : ''));
    }
    if (run.completed?.length) $('footer').textContent = `${run.completed.length} Schritt(e) bestätigt. ${run.current_step ? 'Zuletzt bearbeitet: ' + run.current_step.label + '.' : ''} Bitte den aktuellen Datenstand prüfen.`;
    else $('footer').textContent = run.status === 'preview_ready' && run.selected === selected ? 'Die Vorschau wurde mit frischen Daten geprüft. Mit der Übernahme werden die aufgeführten Änderungen ausgeführt.' : 'Die Analyse ändert keine Kundendaten. Historische Bestellanschriften bleiben erhalten.';
    if (!run.proposals) return;
    $('summary').textContent = run.summary;
    $('revise').disabled = busy || !['ready','preview_ready'].includes(run.status);
    if (selected >= run.proposals.length) selected = 0;
    const certainty = {clear:'Gut belegt',review:'Bitte fachlich prüfen',uncertain:'Rückfrage erforderlich'};
    $('choices').innerHTML = run.proposals.map((p,i) => `<button type="button" class="customer-ai-choice" data-plan="${i}" aria-pressed="${selected === i}">${i===0?'Empfehlung: ':''}${escape(p.title)}<span>${escape(certainty[p.certainty] || '')}</span>${p.blocked ? '<span>Technisch nicht freigegeben</span>' : ''}</button>`).join('');
    if (versions.length) {
      const history = document.createElement('details');
      history.innerHTML = '<summary class="text-xs">Frühere Versionen</summary>' + versions.map(v => `<div class="merge-comparison-note"><strong>Version ${escape(v.version)}</strong><br>${escape(v.summary)}${v.proposals.map(p=>`<p>${escape(p.title)}: ${escape(p.reason)}</p>`).join('')}</div>`).join('');
      $('choices').append(history);
    }
    $('choices').querySelectorAll('[data-plan]').forEach(button => {
      button.disabled = busy;
      button.addEventListener('mouseenter', () => { if (!busy) { hovering = Number(button.dataset.plan); renderPlan(); } });
      button.addEventListener('mouseleave', () => { hovering = null; renderPlan(); });
      button.addEventListener('click', () => {
        selected = Number(button.dataset.plan); hovering = null; before = false;
        render();
      });
    });
    renderPlan();
    prepareSelected();
  }
  function prepareSelected() {
    const plan = run?.proposals?.[selected];
    if (!modal.open || busy || !['ready','preview_ready'].includes(run?.status) || !canReview(plan)) return;
    if (plan.operations[0]?.kind === 'merge_shopware') return; // The established controller prepares its own binding preview.
    if (run.status === 'preview_ready' && run.selected === selected) return;
    const key = `${run.id}:${selected}`;
    if (autoReviewKey === key) return;
    autoReviewKey = key;
    queueMicrotask(() => { if (modal.open && !busy && `${run?.id}:${selected}` === key) void review(); });
  }
  function recordLabel(record) {
    if (!record) return 'Unbekannter Datensatz';
    const f = record.fields;
    const name = f.company || f.name || [f.name1,f.name2,f.name3].filter(Boolean).join(' / ') || [f.firstName || f.first_name,f.lastName || f.last_name].filter(Boolean).join(' ');
    const address = [f.street, [f.zipcode || f.zipCode || f.postal_code,f.city].filter(Boolean).join(' ')].filter(Boolean).join(', ');
    return [name || `${record.kind === 'customer' ? 'Kunde' : record.kind === 'contact' ? 'Ansprechpartner' : 'Adresse'} ${record.number}`, address].filter(Boolean).join(' · ');
  }
  function renderPlan() {
    const plan = currentPlan();
    if (!plan || !run.snapshot) return;
    $('plan-title').textContent = plan.title;
    $('plan-reason').textContent = plan.reason;
    $('questions').innerHTML = plan.questions.map(q=>`<p>${escape(q)}</p>`).join('');
    const merge = plan.operations.find(op=>op.kind==='merge_shopware');
    $('outcome').textContent = merge ? `Kunde ${run.snapshot.records.find(r=>r.ref===merge.target)?.number} bleibt erhalten; Kunde ${run.snapshot.records.find(r=>r.ref===merge.source)?.number} wird zusammengeführt.` : plan.operations.length ? 'Die Kundendatensätze bleiben getrennt. Geändert werden die unten gezeigten Adresszuordnungen.' : 'Keine Änderung empfohlen.';
    $('apply').disabled = busy || before || (hovering !== null && hovering !== selected);
    $('blocked').textContent = plan.blocked || (plan.questions.length ? 'Vor einer Änderung müssen die offenen Fragen geklärt werden.' : !plan.operations.length ? 'Dieser Vorschlag sieht keine Änderungen vor.' : '');
    $('preview-label').textContent = before ? 'Aktueller Datenstand' : hovering !== null && hovering !== selected ? 'Vorübergehende Hover-Vorschau' : 'Geplanter Zustand · Vorschlag festgehalten';
    $('before').textContent = before ? 'Vorschlag ansehen' : 'Ist-Zustand ansehen';
    $('before').setAttribute('aria-pressed', String(before));
    const records = structuredClone(run.snapshot.records);
    const byRef = new Map(records.map(r=>[r.ref,r]));
    const originalByRef = new Map(run.snapshot.records.map(r=>[r.ref,r]));
    const affected = new Set(), sources = new Set(), roles = new Map();
    if (!plan.blocked) for (const change of plan.changes) {
      affected.add(change.source); affected.add(change.target); sources.add(change.source);
      if (before) continue;
      const src = byRef.get(change.source), dst = byRef.get(change.target);
      if (!src || !dst) continue;
      if (change.kind.startsWith('link_')) Object.assign(dst.fields, change.after);
      if (change.kind === 'merge_shopware') { roles.set(src.ref,'Wird zusammengeführt / gelöscht'); roles.set(dst.ref,'Bleibt erhalten'); }
      if (['set_billing','set_shipping'].includes(change.kind)) {
        const billing = change.kind === 'set_billing', role = billing ? 'Rechnung' : 'Lieferung';
        const bool = billing ? 'is_invoice' : 'is_shipping';
        for (const r of records.filter(r=>r.number===src.number)) {
          if (r.system === 'dj' && r.kind === 'address') r.fields[bool] = r.fields.erp_ans_nr === src.fields.erp_ans_nr;
          if (r.system === 'sw' && r.kind === 'customer') r.fields[billing?'defaultBillingAddressId':'defaultShippingAddressId'] = src.fields.api_id;
          if (r.system === 'mt' && r.kind === 'address') r.fields[billing?'isDefaultBilling':'isDefaultShipping'] = r.fields.addressSubNumber === src.fields.erp_ans_nr;
          if ((r.system==='sw' && r.fields.id===src.fields.api_id) || (r.system==='mt' && r.kind==='address' && r.fields.addressSubNumber===src.fields.erp_ans_nr) || r.ref===src.ref) { affected.add(r.ref); }
        }
      }
    }
    if (!merge) renderOutcome(records, plan);
    const fieldsHtml = fields => `<dl class="customer-ai-fields">${Object.entries(fields).map(([k,v])=>`<div><dt>${escape(labels[k] || k)}</dt><dd>${escape(display(v))}</dd></div>`).join('')}</dl>`;
    $('diagram').innerHTML = ['sw','dj','mt'].map(system => `<section class="customer-ai-system"><h4>${captions[system]}</h4>${records.filter(r=>r.system===system && r.kind!=='order' && ($('all').checked || affected.has(r.ref) || r.kind==='customer' || !plan.changes.length)).map(r=>{
      const f=r.fields;
      const parent=byRef.get(r.parent);
      let badges=[];
      if (r.kind==='address') {
        if (f.is_invoice || f.isDefaultBilling || (r.system==='sw' && parent?.fields.defaultBillingAddressId===f.id)) badges.push('Rechnung');
        if (f.is_shipping || f.isDefaultShipping || (r.system==='sw' && parent?.fields.defaultShippingAddressId===f.id)) badges.push('Lieferung');
      }
      const orders=records.filter(o=>o.kind==='order' && o.parent===r.ref);
      return `<article class="customer-ai-record" data-ai-ref="${escape(r.ref)}" data-affected="${affected.has(r.ref)}" data-source="${sources.has(r.ref)}" data-role="${escape(roles.get(r.ref) || '')}"><strong>${escape(recordLabel(r))}</strong><div class="text-xs">${r.kind==='customer'?'Kundennummer':r.kind==='contact'?'Ansprechpartner zu Kunde':'Anschrift zu Kunde'} ${escape(r.number)}</div>${badges.map(b=>`<span class="customer-ai-pill">${b}</span>`).join('')}<details><summary>Details</summary><div class="text-xs">${escape(r.ref)}</div>${fieldsHtml(f)}</details>${orders.length?`<details><summary>${orders.length} Bestellungen</summary>${orders.map(o=>fieldsHtml(o.fields)).join('')}</details>`:''}</article>`;
    }).join('') || '<p class="merge-comparison-note">Kein Datensatz vorhanden.</p>'}</section>`).join('') + '<svg class="customer-ai-connectors" aria-hidden="true"></svg>';
    const valueList = data => Object.entries(data).map(([k,v])=>`${escape(labels[k]||k)}: ${escape(display(v))}`).join('<br>');
    $('steps').innerHTML = `<h3 class="text-sm font-semibold">${plan.changes.length} geplante Änderung(en)</h3>` + plan.changes.map((c,i)=>`<section class="customer-ai-step"><h4>${i+1}. ${escape(c.label)}</h4><p>${escape(changeDescription(c, byRef))}</p><details><summary>Technische Änderung im Detail</summary><dl><div><dt>Vorher</dt><dd>${valueList(c.before)}</dd></div><div><dt>Nachher</dt><dd>${valueList(c.after)}</dd></div></dl></details><p class="merge-comparison-note">${escape(c.reason)}</p></section>`).join('') + (plan.operations[0]?.kind==='merge_shopware'?'<p class="customer-ai-message customer-ai-warning">Nach dem Merge werden die Adresszuordnungen anhand des neuen Datenstands erneut analysiert. Die verbindliche Vorschau zeigt auch den künftigen Shopzugang.</p>':'');
    $('evidence').innerHTML = plan.evidence.map(e=>`<p><strong>${escape(captions[originalByRef.get(e.ref)?.system] || '')} · ${escape(labels[e.field]||e.field)}</strong><br>${escape(e.finding)}<br>${escape(e.ref)}: ${escape(display(originalByRef.get(e.ref)?.fields[e.field]))}</p>`).join('') + plan.questions.map(q=>`<p class="customer-ai-warning">Offene Frage: ${escape(q)}</p>`).join('');
    requestAnimationFrame(drawConnections);
  }
  function renderOutcome(records, plan) {
    const customers=records.filter(r=>r.system==='dj' && r.kind==='customer');
    const roleAddress=(items,customer,role)=>{
      const flag=role==='billing'?'is_invoice':'is_shipping';
      return items.filter(r=>r.system==='dj' && r.kind==='address' && r.parent===customer.ref && r.fields[flag]).map(recordLabel).join(' / ') || 'Keine Standardadresse hinterlegt';
    };
    const roles=customers.map(c=>{
      const rows=[['billing','Rechnung'],['shipping','Lieferung']].map(([role,label])=>{
        const original=roleAddress(run.snapshot.records,c,role), after=roleAddress(records,c,role);
        return `<div><strong>${label}:</strong> ${escape(after)}${original!==after?`<span class="customer-ai-previous">Bisher: ${escape(original)}</span>`:' <span class="text-xs">(unverändert)</span>'}</div>`;
      }).join('');
      return `<section><strong>Kunde ${escape(c.number)}</strong>${rows}</section>`;
    }).join('');
    const assignments=plan.operations.filter(op=>op.kind.startsWith('link_')).length;
    $('outcome').innerHTML = `<div class="customer-ai-outcome">${roles}<p>${assignments?`${assignments} Zuordnung(en) werden hergestellt. `:''}${plan.operations.length?'Die Kundenkonten bleiben erhalten.':'Keine Änderung empfohlen.'}</p></div>`;
  }
  function changeDescription(change, refs) {
    const source=refs.get(change.source), target=refs.get(change.target);
    const address=recordLabel(source);
    if (change.kind==='set_billing' || change.kind==='set_shipping') {
      const role=change.kind==='set_billing'?'Rechnungsadresse':'Lieferadresse';
      return `${role} für Kunde ${target.number}: ${address} · in allen drei Systemen`;
    }
    if (change.kind.startsWith('link_')) return `${captions[source.system]}: ${address} ↔ ${captions[target.system]}: ${recordLabel(target)}`;
    if (change.kind==='merge_shopware') return `Kunde ${source.number} wird in Kunde ${target.number} zusammengeführt. Kunde ${target.number} bleibt erhalten.`;
    return `${address} → ${captions[target.system]} · Kunde ${target.number}`;
  }
  function drawConnections() {
    const svg=$('diagram').querySelector('svg');
    if (!svg) return;
    svg.replaceChildren();
    const plan=currentPlan();
    if (before || !plan || plan.blocked || window.innerWidth<600) return;
    const diagram=$('diagram').getBoundingClientRect();
    const elements=new Map([...$('diagram').querySelectorAll('[data-ai-ref]')].map(e=>[e.dataset.aiRef,e]));
    for (const c of plan.changes.filter(c=>c.kind.startsWith('link_'))) {
      const a=elements.get(c.source)?.getBoundingClientRect(),b=elements.get(c.target)?.getBoundingClientRect();
      if (!a || !b || Math.abs(a.x-b.x)<10) continue;
      const forward=a.x<b.x;
      const x1=(forward?a.right:a.left)-diagram.left,y1=a.top-diagram.top+Math.min(a.height/2,35);
      const x2=(forward?b.left:b.right)-diagram.left,y2=b.top-diagram.top+Math.min(b.height/2,35);
      const path=document.createElementNS('http://www.w3.org/2000/svg','path');
      path.setAttribute('d',`M ${x1} ${y1} C ${(x1+x2)/2} ${y1}, ${(x1+x2)/2} ${y2}, ${x2} ${y2}`);
      svg.append(path);
    }
  }
  async function review() {
    if (busy || !run || !canReview(run.proposals[selected])) return;
    error(''); setBusy(true);
    try {
      run=await request({action:'preview',run_id:run.id,index:selected});
      remember(); render(); schedulePoll();
    } catch(e) { setBusy(false); error(e.message); }
  }
  async function apply() {
    if (busy || run?.status!=='preview_ready' || run.selected!==selected) return;
    error(''); setBusy(true);
    try {
      run=await request({action:'execute',run_id:run.id,index:selected,preview_token:run.preview_token});
      remember(); render(); schedulePoll();
    } catch(e) { setBusy(false); error(e.message); }
  }
  async function handOffMerge() {
    if (busy || !['ready','preview_ready'].includes(run?.status) || !canReview(run.proposals[selected])) return;
    const op=run.proposals[selected].operations[0];
    const refs=new Map(run.snapshot.records.map(r=>[r.ref,r]));
    if (op.kind!=='merge_shopware') return;
    const source=refs.get(op.source).fields.id,target=refs.get(op.target).fields.id;
    renderShopwareMergeSection();
    const keep=document.getElementById('sw-merge-keep'),remove=document.getElementById('sw-merge-delete');
    if (!keep || !remove || swMergePending) { error('Bitte zuerst den vorhandenen Merge-Vorgang prüfen oder die Suche aktualisieren.'); return; }
    keep.value=target; remove.value=source;
    if (keep.value!==target || remove.value!==source) { error('Die Suchauswahl hat sich geändert. Bitte neu suchen und analysieren.'); return; }
    invalidateShopwareMergePreview(); modal.close();
    await loadShopwareMergePreview();
  }
  // The existing merge dialog owns execution, idempotency and recovery of merges.
  const originalRender=render;
  render=()=>{
    originalRender();
    const merge=run?.proposals?.[selected]?.operations[0]?.kind==='merge_shopware';
    const prepared=run?.status==='preview_ready' && run.selected===selected;
    $('review').hidden = !merge && prepared;
    $('review').textContent=merge?'Zusammenführung prüfen':'Daten erneut prüfen';
    if (merge && ['ready','preview_ready'].includes(run.status) && canReview(run.proposals[selected])) $('review').disabled=busy;
  };
  $('start').addEventListener('click',()=>{ if ($('start').disabled) return; if (run && JSON.stringify(run.numbers)===JSON.stringify(numbers())) { open(); render(); } else void start(); });
  $('new').addEventListener('click',()=>void start());
  $('revise').addEventListener('click',()=>void start(true));
  $('provider').addEventListener('change',()=>{ updateStart(); });
  $('review').addEventListener('click',()=>{
    if (run?.proposals?.[selected]?.operations[0]?.kind==='merge_shopware') void handOffMerge();
    else void review();
  });
  $('apply').addEventListener('click',()=>void apply());
  $('all').addEventListener('change',renderPlan);
  $('before').addEventListener('click',()=>{before=!before;renderPlan();});
  $('refresh').addEventListener('click',()=>{if(run){error('');void poll(++generation);}});
  modal.querySelectorAll('[data-customer-ai-close]').forEach(b=>b.addEventListener('click',()=>modal.close()));
  modal.addEventListener('close',()=>{
    if (run?.status==='applied') {
      run=null; autoReviewKey='';
      try { sessionStorage.removeItem('gc-customer-ai-run'); } catch (_) {}
      void doSearch();
    }
  });
  modal.addEventListener('toggle',drawConnections);
  modal.addEventListener('click',event=>{if(event.target.tagName==='SUMMARY')requestAnimationFrame(drawConnections);});
  new ResizeObserver(()=>requestAnimationFrame(drawConnections)).observe($('diagram'));
  document.addEventListener('customer-merge-search-progress',updateStart);
  new MutationObserver(updateStart).observe(document.getElementById('results-rows'),{childList:true,subtree:true});
  void config();
})();
