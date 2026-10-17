/* Search snapshots and accepted plans remain owned by the server. */
(() => {
  'use strict';
  const panel=document.getElementById('customer-ai-panel');
  if(!panel)return;
  const api=panel.dataset.apiUrl, modal=document.getElementById('customer-ai-dialog');
  const $=id=>document.getElementById('customer-ai-'+id);
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let run=null, selected=0, before=false, busy=false, connectionLost=false;
  let canApply=false, canMerge=false, providerReady=false, providerMessage='KI-Zugang wird geprüft…';
  let pollTimer=null,generation=0,versions=[];
  const numbers=()=>[...new Set(searchErps.map(String))].sort();
  const searchId=()=>searchProgress?.cacheId||'';
  const sameSearch=()=>run?.search_id===searchId()&&JSON.stringify(run?.numbers)===JSON.stringify(numbers());
  const open=()=>{if(!modal.open)modal.showModal();};
  const error=message=>{$('error').textContent=message;};
  const progress=message=>{if($('progress').textContent!==message)$('progress').textContent=message;};
  const remember=()=>{try{sessionStorage.setItem('gc-customer-ai-run',run.id);}catch(_){}};
  function canAccept(plan) {
    if(!plan||plan.blocked||!plan.operations.length||plan.questions.length)return false;
    return plan.operations[0].kind==='merge_shopware'?canMerge:canApply||plan.operations.every(op=>op.kind==='link_customer');
  }
  function updateStart() {
    const search=customerAISearchReadiness(),size=numbers().length;
    $('start').lastChild.textContent=sameSearch()?'Vorschlag öffnen':'KI-Vorschlag anzeigen';
    $('start').disabled=!search.ready||!searchId()||!size||size>8||!providerReady||(busy&&!sameSearch());
    $('retry').disabled=busy||!search.ready||!searchId()||!providerReady;
    if(!search.ready)$('status').textContent=search.message;
    else if(size>8)$('status').textContent='Bitte die Suche auf höchstens acht Kunden eingrenzen.';
    else if(!providerReady)$('status').textContent=providerMessage;
    else if(!busy)$('status').textContent='Suchdaten geladen. Die KI verwendet diesen Datenstand · API-Abrechnung.';
    if(swMergePending)document.getElementById('customer-ai-manual').open=true;
  }
  function renderActivity() {
    const working=!connectionLost&&(busy||['loading','applying'].includes(run?.status));
    $('activity').dataset.working=String(working);
    $('spinner').hidden=!working;$('wait-hint').hidden=!working;
    $('refresh').hidden=working||(!connectionLost&&run?.status!=='needs_review');
    $('retry').hidden=run?.status!=='failed'||working||connectionLost;
    $('retry').textContent=run?.phase==='execute'?'Suche aktualisieren':'Erneut analysieren';
    $('apply').hidden=busy||working||connectionLost||!['ready','preview_ready'].includes(run?.status);
    $('apply').disabled=before||!canAccept(run?.proposals?.[selected]);
  }
  function setBusy(value) {
    busy=value;$('provider').disabled=value||!providerReady;
    for(const id of ['new','revise','before'])$(id).disabled=value;
    updateStart();renderActivity();
  }
  async function request(body,id) {
    let response;
    try {response=await fetch(id?`${api}?run_id=${encodeURIComponent(id)}`:api,body?{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':CSRF},body:JSON.stringify(body)}:{credentials:'same-origin'});}
    catch(_){throw new Error('Die Verbindung zur Bridge ist unterbrochen.');}
    let data;try{data=await response.json();}catch(_){throw new Error('Der Server hat keine lesbare Antwort geliefert.');}
    if(!response.ok||data.error)throw new Error(data.error||'Der Auftrag konnte nicht verarbeitet werden.');
    return data;
  }
  function recoverStatus(e) {
    connectionLost=true;error(e.message+' Bitte den Status prüfen.');progress('Aktueller Status nicht erreichbar.');setBusy(true);
  }
  async function config() {
    try {
      const data=await request();canApply=data.can_apply;canMerge=data.can_merge;
      $('provider').replaceChildren();
      for(const provider of data.providers){const option=document.createElement('option');option.value=provider.id;option.textContent=`${provider.name} · ${provider.model}`;$('provider').append(option);}
      providerReady=data.providers.length>0;
      if(!providerReady)providerMessage='Bitte einen aktiven OpenAI-Provider mit API-Schlüssel einrichten.';
      if(data.provider_admin_url){$('provider-settings').href=data.provider_admin_url;$('provider-settings').classList.remove('hidden');}
      updateStart();
      let id='';try{id=sessionStorage.getItem('gc-customer-ai-run')||'';}catch(_){}
      if(id)try{run=await request(null,id);selected=run.selected??0;render();
        if(['loading','applying','needs_review'].includes(run.status)){open();if(run.status!=='needs_review'){setBusy(true);schedulePoll();}}
      }catch(_){}
    }catch(e){providerMessage=e.message;providerReady=false;updateStart();}
  }
  async function start(revise=false) {
    if(busy)return;
    if(!customerAISearchReadiness().ready||!searchId()){error('Bitte zuerst die Kunden suchen.');return;}
    const objection=$('objection').value.trim();
    if(revise&&!objection){error('Bitte zuerst einen Einwand eingeben.');return;}
    const body={action:'analyze',numbers:numbers(),provider_id:Number($('provider').value),search_id:searchId()};
    if(revise&&run)Object.assign(body,{previous_id:run.id,objection});
    connectionLost=false;error('');open();setBusy(true);$('content').hidden=true;progress('Die KI bewertet die geladenen Suchdaten…');
    try {
      const previous=run;run=await request(body);
      if(revise&&previous?.proposals)versions=[...versions,previous].slice(-5);else versions=[];
      selected=0;before=false;$('objection').value='';$('revision').open=false;
      remember();render();schedulePoll();
    }catch(e){setBusy(false);progress('Die Analyse konnte nicht gestartet werden.');error(e.message);}
  }
  function schedulePoll() {clearTimeout(pollTimer);const seq=++generation;pollTimer=setTimeout(()=>poll(seq),1500);}
  async function poll(seq) {
    if(!run||seq!==generation)return;
    try {
      const data=await request(null,run.id);if(seq!==generation)return;
      run=data;connectionLost=false;render();
      if(['loading','applying'].includes(run.status))pollTimer=setTimeout(()=>poll(seq),1500);
      else{setBusy(false);render();remember();}
    }catch(e){recoverStatus(e);}
  }
  function concise(text) {return (String(text||'').match(/[^.!?]+[.!?]?(?:\s|$)/g)||[String(text||'')]).slice(0,2).join('').trim().slice(0,400);}
  function render() {
    if(!run)return;
    progress(busy||['loading','applying','failed','needs_review'].includes(run.status)?run.message:'');
    $('content').hidden=!run.proposals;
    if(['failed','needs_review'].includes(run.status))error(run.message);
    if(run.proposals){
      if(selected>=run.proposals.length)selected=0;
      $('choices').innerHTML=run.proposals.map((plan,index)=>`<button type="button" class="customer-ai-choice" data-plan="${index}" aria-pressed="${!before&&selected===index}">${escape(plan.title)}<span>${index===0?'Empfehlung':plan.certainty==='uncertain'?'Rückfrage':'Alternative'}</span></button>`).join('');
      for(const button of $('choices').querySelectorAll('[data-plan]')){button.disabled=busy;button.addEventListener('click',()=>{selected=Number(button.dataset.plan);before=false;render();modal.querySelector('.merge-dialog-body').scrollTop=0;});}
      $('before').setAttribute('aria-pressed',String(before));
      $('revise').disabled=busy||!['ready','preview_ready'].includes(run.status);
      $('versions').innerHTML=versions.map(version=>`<p>Version ${escape(version.version)} · ${escape(concise(version.summary))}</p>`).join('');
      renderPlan();
    }
    $('footer').textContent=run.status==='applied'?'Vorschlag übernommen. Beim Schließen wird die Suche aktualisiert.':run.status==='failed'&&run.phase==='execute'?'Bitte die Suche aktualisieren. Es wurde keine erneute Übernahme gestartet.':run.status==='failed'?'Erneut analysieren startet eine weitere kostenpflichtige API-Anfrage.':'Blau markiert: vorgeschlagene Änderungen. Vor dem Speichern wird der Datenstand erneut geprüft.';
    renderActivity();
  }
  function renderPlan() {
    const plan=run?.proposals?.[selected];if(!plan)return;
    $('plan-title').textContent=before?'Ist-Zustand':plan.title;
    $('mode').textContent=before?'Geladene Suchdaten':`Vorschlag ${selected+1}`;
    $('plan-reason').textContent=before?'':concise(plan.reason);
    $('blocked').textContent=plan.blocked||plan.questions.join(' ');
    $('diagram').innerHTML=CustomerMergePreview.render(run.snapshot,plan,before);
    const refs=new Map(run.snapshot.records.map(record=>[record.ref,record]));
    $('evidence').innerHTML=`<p>${escape(plan.reason)}</p>`+plan.evidence.map(e=>`<p><strong>${escape(e.field)}</strong> · ${escape(e.finding)}<br>${escape(refs.get(e.ref)?.fields[e.field]??'')}</p>`).join('');
  }
  async function accept() {
    if(busy||before||!canAccept(run?.proposals?.[selected]))return;
    error('');setBusy(true);progress('Die Daten werden vor dem Speichern geprüft…');
    try {
      if(!run.approval_tokens?.[selected])run=await request({action:'preview',run_id:run.id,index:selected});
      run=await request({action:'execute',run_id:run.id,index:selected,preview_token:run.approval_tokens?.[selected]||run.preview_token});
      remember();render();schedulePoll();
    }catch(e){recoverStatus(e);}
  }
  $('start').addEventListener('click',()=>{if($('start').disabled)return;if(sameSearch()){open();render();}else void start();});
  $('apply').addEventListener('click',()=>void accept());
  $('before').addEventListener('click',()=>{before=true;render();modal.querySelector('.merge-dialog-body').scrollTop=0;});
  $('new').addEventListener('click',()=>void start());
  $('revise').addEventListener('click',()=>void start(true));
  $('retry').addEventListener('click',()=>{if(run?.phase==='execute'){modal.close();void doSearch();}else void start();});
  $('provider').addEventListener('change',updateStart);
  $('refresh').addEventListener('click',async()=>{if(!run)return;connectionLost=false;error('');setBusy(true);progress('Status wird geprüft…');
    try{if(run.status==='needs_review'&&run.merge_operation_id){run=await request({action:'merge_status',run_id:run.id});remember();}void poll(++generation);}catch(e){recoverStatus(e);}
  });
  for(const button of modal.querySelectorAll('[data-customer-ai-close]'))button.addEventListener('click',()=>modal.close());
  modal.addEventListener('close',()=>{if(run?.status==='applied'){run=null;try{sessionStorage.removeItem('gc-customer-ai-run');}catch(_){}void doSearch();}});
  document.addEventListener('customer-merge-search-progress',updateStart);
  void config();
})();
