/* Merge consent first; model proposals only reconcile the surviving addresses. */
(() => {
  'use strict';
  const panel=document.getElementById('customer-ai-panel');
  if(!panel)return;
  const api=panel.dataset.apiUrl, modal=document.getElementById('customer-ai-dialog');
  const $=id=>document.getElementById('customer-ai-'+id);
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let run=null, selected=0, before=false, busy=false, connectionLost=false;
  let mergeGate=null,continuing=false,continuationFailed=false,appliedRefresh='';
  let canApply=false, canMerge=false, canCreateMergeTarget=false, canConsolidate=false, canChangeOrder=false, providerReady=false, providerMessage='KI-Zugang wird geprüft…';
  let pollTimer=null,generation=0,versions=[];
  const numbers=()=>[...new Set(searchErps.map(String))].sort();
  const searchId=()=>searchProgress?.cacheId||'';
  const accounts=snapshot=>(snapshot?.records||[]).filter(r=>r.system==='sw'&&r.kind==='customer');
  const hasMultipleAccounts=()=>accounts(searchProgress?.snapshot).length>1;
  const sameSearch=()=>run?.search_id===searchId()&&JSON.stringify(run?.numbers)===JSON.stringify(numbers());
  const open=()=>{if(!modal.open)modal.showModal();};
  const error=message=>{$('error').textContent=message;};
  const progress=message=>{if($('progress').textContent!==message)$('progress').textContent=message;};
  const remember=()=>{try{sessionStorage.setItem('gc-customer-ai-run',run.id);}catch(_){}};
  const forget=()=>{try{sessionStorage.removeItem('gc-customer-ai-run');}catch(_){}};
  const continuesAfterMerge=()=>['merge_first','address_consolidation'].includes(run?.workflow);
  function canAccept(plan) {
    if(!plan||plan.blocked||!plan.operations.length||plan.questions.length)return false;
    if(plan.operations[0].kind==='consolidate_addresses')return canConsolidate&&(!(plan.changes?.[0]?.after?.Bestellverweise)||canChangeOrder);
    return plan.operations[0].kind==='merge_shopware'?canMerge:canApply||plan.operations.every(op=>op.kind==='link_customer');
  }
  function updateStart() {
    const search=customerAISearchReadiness(),size=numbers().length,multiple=hasMultipleAccounts();
    $('start').lastChild.textContent=sameSearch()?'Vorschlag öffnen':multiple?'Konten prüfen':'KI-Vorschlag anzeigen';
    $('start').disabled=!search.ready||!searchId()||!size||size>8||(!multiple&&!providerReady)||(busy&&!sameSearch());
    $('retry').disabled=busy;
    if(!search.ready)$('status').textContent=search.message;
    else if(size>8)$('status').textContent='Bitte die Suche auf höchstens acht Kunden eingrenzen.';
    else if(multiple&&!busy)$('status').textContent=`${accounts(searchProgress?.snapshot).length} Konten · zuerst richtige und falsche AdrNr auswählen`;
    else if(!providerReady)$('status').textContent=providerMessage;
    else if(!busy)$('status').textContent='Suchdaten geladen · KI-Analyse über API';
    const hint=$('merge-hint');
    if(hint)hint.hidden=!search.ready||!multiple;
    const mergeSection=document.getElementById('sw-merge-section');
    if(mergeSection)mergeSection.classList.toggle('customer-ai-merge-needed',search.ready&&multiple);
    if(!sameSearch()&&$('inline')){$('inline').hidden=true;const rows=document.getElementById('results-rows');if(rows)rows.dataset.aiDraft='false';}
    if(swMergePending)document.getElementById('customer-ai-manual').open=true;
  }
  function needsTargetCreation() {
    const target=accounts(mergeGate?.snapshot).find(r=>r.ref===mergeGate?.target);
    return !!target&&!mergeGate.snapshot.records.some(r=>r.system==='dj'&&r.kind==='customer'&&r.number===target.number);
  }
  function renderActivity() {
    const working=!connectionLost&&(busy||['loading','applying'].includes(run?.status));
    const locked=busy||['loading','applying'].includes(run?.status);
    modal.dataset.busy=String(locked);
    for(const element of [$('content'),$('merge-stage'),document.getElementById('customer-ai-manual'),document.getElementById('customer-merge-search-form'),$('inline'),$('merge-hint')]) {
      if(!element)continue;
      element.inert=locked;element.setAttribute('aria-busy',String(locked));
    }
    for(const button of modal.querySelectorAll('[data-customer-ai-close]'))button.disabled=working;
    $('activity').dataset.working=String(working);
    $('spinner').hidden=!working;$('wait-hint').hidden=!working;
    $('refresh').hidden=working||(!connectionLost&&run?.status!=='needs_review');
    $('retry').hidden=(!continuationFailed&&run?.status!=='failed')||working||connectionLost;
    $('retry').textContent=continuationFailed?'Daten neu laden':run?.phase==='execute'?'Suche aktualisieren':'Erneut analysieren';
    $('apply').textContent=mergeGate?'Merge bestätigen':run?.proposals?.[selected]?.operations?.[0]?.kind==='consolidate_addresses'?'Adressen zusammenführen':'Vorschlag akzeptieren';
    $('apply').hidden=busy||working||connectionLost||(mergeGate?!!run:!['ready','preview_ready'].includes(run?.status));
    $('apply').disabled=locked||(mergeGate?!canMerge||(needsTargetCreation()&&!canCreateMergeTarget)||!mergeGate.source||!mergeGate.target||mergeGate.source===mergeGate.target:before||!canAccept(run?.proposals?.[selected]));
  }
  function setBusy(value) {
    busy=value;$('provider').disabled=value||!providerReady;
    for(const id of ['new','revise','before','merge-keep','merge-source','merge-skip'])$(id).disabled=value;
    updateStart();renderActivity();
  }
  async function request(body,id,mergeSearchId) {
    let response;
    const url=id?`${api}?run_id=${encodeURIComponent(id)}`:mergeSearchId?`${api}?merge_search_id=${encodeURIComponent(mergeSearchId)}`:api;
    try {response=await fetch(url,body?{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':CSRF},body:JSON.stringify(body)}:{credentials:'same-origin'});}
    catch(_){throw new Error('Die Verbindung zur Bridge ist unterbrochen.');}
    let data;try{data=await response.json();}catch(_){throw new Error('Der Server hat keine lesbare Antwort geliefert.');}
    if(!response.ok||data.error){const e=new Error(data.error||'Der Auftrag konnte nicht verarbeitet werden.');e.status=response.status;throw e;}
    return data;
  }
  function recoverStatus(e) {
    connectionLost=true;error(e.message+' Bitte den Status prüfen.');progress('Aktueller Status nicht erreichbar.');setBusy(true);
  }
  function comparison(snapshot,plan=null,isBefore=true) {
    $('diagram').innerHTML=CustomerMergePreview.render(snapshot,plan,isBefore);
  }
  function showMergeGate(preferredTarget='') {
    run=null;before=true;connectionLost=false;continuationFailed=false;forget();
    mergeGate={search_id:searchId(),snapshot:searchProgress.snapshot,source:'',target:accounts(searchProgress.snapshot).find(r=>r.number===preferredTarget)?.ref||''};
    open();error('');progress('');setBusy(false);renderGate();
    modal.querySelector('.merge-dialog-body').scrollTop=0;
  }
  function renderGate() {
    if(!mergeGate)return;
    $('merge-stage').hidden=false;$('content').hidden=false;$('sidebar').hidden=true;
    $('layout').dataset.merge='true';$('explanation').hidden=true;
    const list=accounts(mergeGate.snapshot),option=r=>`<option value="${escape(r.ref)}">${escape(r.number)} · ${escape(r.fields.company||[r.fields.firstName,r.fields.lastName].filter(Boolean).join(' '))} · ${escape(r.fields.email||'')}</option>`;
    $('merge-keep').innerHTML='<option value="">Richtige AdrNr auswählen…</option>'+list.map(option).join('');
    $('merge-source').innerHTML='<option value="">Falsche AdrNr auswählen…</option>'+list.filter(r=>r.ref!==mergeGate.target).map(option).join('');
    $('merge-keep').value=mergeGate.target;$('merge-source').value=mergeGate.source;
    for(const id of ['merge-keep','merge-source','merge-skip'])$(id).disabled=busy||!!run;
    const card=(ref,label,kind)=>{const account=list.find(r=>r.ref===ref);return `<div class="customer-ai-account ${kind}"><span>${label}</span><strong>${account?escape(account.number):'—'}</strong>${account?`<span>${escape(account.fields.email||'')}</span>`:''}${kind==='customer-ai-account-target'&&needsTargetCreation()?'<span>GC-Bridge · wird angelegt</span>':''}</div>`;};
    $('merge-direction').innerHTML=card(mergeGate.source,'Falsche AdrNr','customer-ai-account-source')+'<span class="customer-ai-arrow" aria-hidden="true">→</span>'+card(mergeGate.target,'Richtige AdrNr · bleibt','customer-ai-account-target');
    $('merge-warning').textContent=!canMerge?'Keine Berechtigung zum Kundenmerge.':needsTargetCreation()&&!canCreateMergeTarget?'Keine Berechtigung zur Übernahme des Zielkunden in GC-Bridge.':'';
    $('plan-title').textContent='Ist-Zustand';$('mode').textContent=`${list.length} Konten`;$('blocked').textContent='';
    comparison(mergeGate.snapshot);
    $('footer').textContent=list.length>2?'Weitere Konten werden danach zugeordnet.':'Richtige AdrNr bleibt · falsches Shopkonto wird zusammengeführt';
    renderActivity();
  }
  function beginWorkflow() {
    if(hasMultipleAccounts())showMergeGate();else void start();
  }
  async function config() {
    try {
      const data=await request();canApply=data.can_apply;canMerge=data.can_merge;canCreateMergeTarget=!!data.can_create_merge_target;
      canConsolidate=!!data.can_consolidate_addresses;canChangeOrder=!!data.can_change_order;
      $('provider').replaceChildren();
      for(const provider of data.providers){const option=document.createElement('option');option.value=provider.id;option.textContent=`${provider.name} · ${provider.model}`;$('provider').append(option);}
      providerReady=data.providers.length>0;
      if(!providerReady)providerMessage='Bitte einen aktiven OpenAI-Provider mit API-Schlüssel einrichten.';
      if(data.provider_admin_url){$('provider-settings').href=data.provider_admin_url;$('provider-settings').classList.remove('hidden');}
      updateStart();
      let id='';try{id=sessionStorage.getItem('gc-customer-ai-run')||'';}catch(_){}
      if(id)try{
        const saved=await request(null,id);
        if(['merge_first','address_consolidation'].includes(saved.workflow)||['loading','applying','needs_review'].includes(saved.status)){
          run=saved;selected=run.selected??0;render();open();
          if(continuesAfterMerge()&&run.status==='applied')void continueAfterMerge();
          else if(['loading','applying'].includes(run.status)){setBusy(true);schedulePoll();}
        }
      }catch(_){}
    }catch(e){providerMessage=e.message;providerReady=false;updateStart();}
  }
  async function start(revise=false,separateAccounts=false) {
    if(busy)return false;
    if(!customerAISearchReadiness().ready||!searchId()){error('Bitte zuerst die Kunden suchen.');return false;}
    const objection=$('objection').value.trim();
    if(revise&&!objection){error('Bitte zuerst einen Einwand eingeben.');return false;}
    const body={action:'analyze',mapping_only:true,numbers:numbers(),provider_id:Number($('provider').value),search_id:searchId(),separate_accounts:separateAccounts};
    if(revise&&run)Object.assign(body,{previous_id:run.id,objection});
    mergeGate=null;connectionLost=false;continuationFailed=false;error('');open();setBusy(true);
    $('merge-stage').hidden=true;$('content').hidden=true;progress('Die KI prüft die Adresszuordnungen…');
    try {
      const previous=run;run=await request(body);
      if(revise&&previous?.proposals)versions=[...versions,previous].slice(-5);else versions=[];
      selected=0;before=false;$('objection').value='';$('revision').open=false;
      remember();render();schedulePoll();return true;
    }catch(e){setBusy(false);progress('Die Analyse konnte nicht gestartet werden.');error(e.message);return false;}
  }
  async function confirmMerge() {
    if(busy||!mergeGate||!canMerge||(needsTargetCreation()&&!canCreateMergeTarget)||!mergeGate.source||!mergeGate.target||mergeGate.source===mergeGate.target)return;
    error('');setBusy(true);renderGate();progress('Die bestätigten AdrNr werden vor dem Merge geprüft…');
    try {
      run=await request({action:'merge',search_id:mergeGate.search_id,source_ref:mergeGate.source,target_ref:mergeGate.target});
      remember();render();schedulePoll();
    }catch(e){
      if(e.status&&e.status<500){setBusy(false);progress('');error(e.message);renderGate();}
      else recoverStatus(e);
    }
  }
  async function continueAfterMerge() {
    if(continuing||!continuesAfterMerge()||run.status!=='applied')return;
    continuing=true;continuationFailed=false;mergeGate=null;const merged=run;
    connectionLost=false;error('');setBusy(true);$('merge-stage').hidden=true;$('content').hidden=true;progress('Merge abgeschlossen · Kundendaten werden neu geladen…');
    try {
      await doSearch({customerNumbers:merged.post_merge_numbers});
      if(!customerAISearchReadiness().ready)throw new Error(customerAISearchReadiness().message);
      setBusy(false);
      if(hasMultipleAccounts()&&merged.workflow==='merge_first')showMergeGate(merged.keep_number);
      else if(!await start(false,!!merged.separate_accounts))throw new Error($('error').textContent||'Die Adressanalyse konnte nicht gestartet werden.');
    }catch(e){run=merged;continuationFailed=true;setBusy(false);$('content').hidden=true;progress('Merge abgeschlossen');error(e.message);renderActivity();}
    finally{continuing=false;}
  }
  function schedulePoll() {clearTimeout(pollTimer);const seq=++generation;pollTimer=setTimeout(()=>poll(seq),1500);}
  async function poll(seq) {
    if(!run||seq!==generation)return;
    try {
      const data=await request(null,run.id);if(seq!==generation)return;
      run=data;connectionLost=false;render();
      if(['loading','applying'].includes(run.status))pollTimer=setTimeout(()=>poll(seq),1500);
      else{
        setBusy(false);render();remember();
        if(run.mapping_only&&run.status==='applied')await refreshAppliedMappings();
        else if(continuesAfterMerge()&&run.status==='applied'&&modal.open)await continueAfterMerge();
      }
    }catch(e){recoverStatus(e);}
  }
  async function refreshAppliedMappings() {
    if(appliedRefresh===run.id)return;
    const id=run.id;appliedRefresh=id;setBusy(true);progress('Zuordnungen übernommen · Vergleich wird aktualisiert…');
    try {
      await doSearch();
      if(!customerAISearchReadiness().ready)throw new Error(customerAISearchReadiness().message);
      setBusy(false);run=null;forget();$('inline').hidden=true;modal.close();
      $('status').textContent='Zuordnungen übernommen · aktueller Stand geladen';
    }catch(e){appliedRefresh='';setBusy(false);error('Zuordnungen übernommen. '+e.message);$('retry').hidden=false;}
  }
  function render() {
    if(!run)return;
    if(run.mapping_only&&run.status==='applied'){ $('content').hidden=true;progress('Zuordnungen übernommen');renderActivity();return; }
    if(run.mapping_only&&['ready','preview_ready'].includes(run.status)) {
      renderInline();renderActivity();if(modal.open)modal.close();return;
    }
    if($('inline'))$('inline').hidden=true;
    progress(busy||['loading','applying','failed','needs_review'].includes(run.status)?run.message:'');
    if(['failed','needs_review'].includes(run.status))error(run.message);
    if(run.workflow==='merge_first'){
      mergeGate={search_id:run.search_id,snapshot:run.snapshot,...run.merge_selection};renderGate();return;
    }
    $('merge-stage').hidden=true;$('sidebar').hidden=false;$('layout').dataset.merge='false';
    $('content').hidden=!run.snapshot;$('explanation').hidden=!run.proposals;
    if(run.proposals){
      if(selected>=run.proposals.length)selected=0;
      $('choices').innerHTML=run.proposals.map((plan,index)=>`<button type="button" class="customer-ai-choice" data-plan="${index}" aria-pressed="${!before&&selected===index}">${escape(plan.title)}<span>${index===0?'Empfehlung':plan.certainty==='uncertain'?'Rückfrage':'Alternative'}</span></button>`).join('');
      for(const button of $('choices').querySelectorAll('[data-plan]')){button.disabled=busy;button.addEventListener('click',()=>{selected=Number(button.dataset.plan);before=false;render();modal.querySelector('.merge-dialog-body').scrollTop=0;});}
      $('before').setAttribute('aria-pressed',String(before));
      $('revise').disabled=busy||!['ready','preview_ready'].includes(run.status);
      $('versions').innerHTML=versions.map(version=>`<p>Version ${escape(version.version)}</p>`).join('');
      renderPlan();
    }else{
      $('choices').innerHTML='';$('plan-title').textContent='Ist-Zustand';$('mode').textContent='Daten geladen';$('blocked').textContent='';comparison(run.snapshot);
    }
    $('footer').textContent=['loading','applying'].includes(run.status)?'':run.status==='applied'?'Vorschlag übernommen':run.status==='needs_review'?`${run.completed?.length||0} Änderungen bestätigt · Stand prüfen`:run.status==='failed'?'Auftrag fehlgeschlagen':'Blau = vorgeschlagene Änderung';
    renderActivity();
  }
  function renderInline() {
    const plan=run?.proposals?.[selected];if(!plan)return;
    $('inline').hidden=false;
    $('inline-choices').innerHTML='<button type="button" class="merge-button" data-inline-before aria-pressed="'+before+'">Ist-Zustand</button>'+run.proposals.map((p,index)=>`<button type="button" class="merge-button" data-inline-plan="${index}" aria-pressed="${!before&&selected===index}">${escape(index===0?'KI-Empfehlung':p.title)}</button>`).join('');
    $('inline-choices').querySelector('[data-inline-before]').addEventListener('click',()=>{before=true;renderInline();});
    for(const button of $('inline-choices').querySelectorAll('[data-inline-plan]'))button.addEventListener('click',()=>{selected=Number(button.dataset.inlinePlan);before=false;renderInline();});
    $('inline-apply').hidden=before;
    $('inline-apply').disabled=busy||!canAccept(plan);
    $('inline-blocked').textContent=plan.blocked||plan.questions.join(' ')||(!plan.operations.length?'Zuordnungen stimmen bereits überein.':before?'':'Orange = vorgeschlagene ID · noch nicht gespeichert');
    renderCustomerAIRecommendations(run.snapshot,plan,before);
  }
  function renderPlan() {
    const plan=run?.proposals?.[selected];if(!plan)return;
    $('plan-title').textContent=before?'Ist-Zustand':plan.title;
    $('mode').textContent=before?'Geladene Suchdaten':`Vorschlag ${selected+1}`;
    $('blocked').textContent=plan.blocked||plan.questions.join(' ');
    if(!plan.blocked&&plan.operations?.[0]?.kind==='consolidate_addresses'&&!canAccept(plan))$('blocked').textContent=!canConsolidate?'Keine Berechtigung zum Zusammenführen von Adressen.':'Keine Berechtigung zum Übernehmen der Bestellverweise.';
    comparison(run.snapshot,plan,before);
    const refs=new Map(run.snapshot.records.map(record=>[record.ref,record]));
    $('evidence').innerHTML=`<p>${escape(plan.reason)}</p>`+plan.evidence.map(e=>`<p><strong>${escape(e.field)}</strong> · ${escape(e.finding)}<br>${escape(refs.get(e.ref)?.fields[e.field]??'')}</p>`).join('');
  }
  async function accept() {
    if(mergeGate){await confirmMerge();return;}
    if(busy||before||!canAccept(run?.proposals?.[selected]))return;
    error('');open();setBusy(true);progress('Die Daten werden vor dem Speichern geprüft…');
    try {
      if(!run.approval_tokens?.[selected])run=await request({action:'preview',run_id:run.id,index:selected});
      run=await request({action:'execute',run_id:run.id,index:selected,preview_token:run.approval_tokens?.[selected]||run.preview_token});
      remember();render();schedulePoll();
    }catch(e){recoverStatus(e);}
  }
  if($('inline-apply'))$('inline-apply').addEventListener('click',()=>void accept());
  if($('inline-revise'))$('inline-revise').addEventListener('click',()=>{$('objection').value=$('inline-objection').value;void start(true);});
  if($('merge-open'))$('merge-open').addEventListener('click',()=>showMergeGate());
  $('start').addEventListener('click',()=>{if($('start').disabled)return;if(sameSearch()){if(!run.mapping_only||!['ready','preview_ready'].includes(run.status))open();render();if(continuesAfterMerge()&&run.status==='applied')void continueAfterMerge();}else beginWorkflow();});
  $('merge-keep').addEventListener('change',()=>{mergeGate.target=$('merge-keep').value;if(mergeGate.source===mergeGate.target)mergeGate.source='';renderGate();});
  $('merge-source').addEventListener('change',()=>{mergeGate.source=$('merge-source').value;renderGate();});
  $('merge-skip').addEventListener('click',()=>void start(false,true));
  $('apply').addEventListener('click',()=>void accept());
  $('before').addEventListener('click',()=>{before=true;render();modal.querySelector('.merge-dialog-body').scrollTop=0;});
  $('new').addEventListener('click',()=>void start(false,!!run?.separate_accounts));
  $('revise').addEventListener('click',()=>void start(true));
  $('retry').addEventListener('click',async()=>{
    if(run?.mapping_only&&run.status==='applied'){await refreshAppliedMappings();return;}
    if(continuationFailed){await continueAfterMerge();return;}
    if(run?.phase==='execute'){
      mergeGate=null;run=null;forget();$('merge-stage').hidden=true;$('content').hidden=true;error('');setBusy(true);progress('Kundendaten werden neu geladen…');
      await doSearch();setBusy(false);if(customerAISearchReadiness().ready)beginWorkflow();else error(customerAISearchReadiness().message);
    }else void start();
  });
  $('provider').addEventListener('change',updateStart);
  $('refresh').addEventListener('click',async()=>{
    connectionLost=false;error('');setBusy(true);progress('Status wird geprüft…');
    try{
      if(!run&&mergeGate){
        const status=await request(null,null,mergeGate.search_id);
        if(status.status==='not_submitted'){setBusy(false);renderGate();error('Keine Bestätigung gespeichert. Bitte den Merge erneut bestätigen.');return;}
        run=status;remember();
      }
      if(!run){setBusy(false);return;}
      if(run.status==='needs_review'&&run.workflow==='address_consolidation'){run=await request({action:'address_merge_status',run_id:run.id});remember();}
      if(run.status==='needs_review'&&run.merge_operation_id){run=await request({action:'merge_status',run_id:run.id});remember();}
      void poll(++generation);
    }catch(e){recoverStatus(e);}
  });
  for(const button of modal.querySelectorAll('[data-customer-ai-close]'))button.addEventListener('click',()=>modal.close());
  modal.addEventListener('cancel',event=>{if(!connectionLost&&(busy||['loading','applying'].includes(run?.status)))event.preventDefault();});
  modal.addEventListener('close',()=>{if(run?.status==='applied'&&!continuesAfterMerge()){run=null;forget();void doSearch();}});
  document.addEventListener('customer-merge-search-progress',updateStart);
  void config();
})();
