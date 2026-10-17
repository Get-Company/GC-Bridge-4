/* Read-only projections on the existing Bridge comparison matrix. No I/O. */
(() => {
  'use strict';
  const systemKeys={sw:'shopware',dj:'django',mt:'microtech'};
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function sources(snapshot) {
    const result={}, records=snapshot?.records||[];
    for(const number of Object.keys(snapshot?.availability||{})) result[number]={shopware:null,django:null,microtech:null};
    for(const record of records.filter(r=>r.kind==='customer')) {
      const f=structuredClone(record.fields), number=record.number;
      result[number] ||= {shopware:null,django:null,microtech:null};
      const addresses=records.filter(r=>r.kind==='address'&&r.parent===record.ref);
      const orders=records.filter(r=>r.kind==='order'&&r.parent===record.ref).map(r=>r.fields);
      let customer;
      if(record.system==='sw') customer={...f,addresses:addresses.map(a=>({...a.fields,
        salutation:a.fields.salutation?.displayName||a.fields.salutation||'',countryIso:a.fields.country?.iso||'',
        is_shipping:a.fields.id===f.defaultShippingAddressId,is_invoice:a.fields.id===f.defaultBillingAddressId,
        email:a.fields.email||f.email||'',_ref:a.ref,_changed:a.changed,_new:a.isNew})),orders};
      else if(record.system==='dj') customer={...f,addresses:addresses.map(a=>({...a.fields,_ref:a.ref,_changed:a.changed,_new:a.isNew})),orders};
      else customer={...f,erp_nr:f.customerNumber||number,name:f.name1||[f.firstName,f.lastName].filter(Boolean).join(' '),
        addresses:addresses.map(a=>({...a.fields,ans_nr:a.fields.addressSubNumber,postal_code:a.fields.zipCode,country_code:a.fields.country,
          is_shipping:a.fields.isDefaultShipping,is_invoice:a.fields.isDefaultBilling,_ref:a.ref,_changed:a.changed,
          contacts:records.filter(r=>r.kind==='contact'&&r.parent===a.ref).map(c=>({...c.fields,asp_nr:c.fields.contactNumber,
            first_name:c.fields.firstName,last_name:c.fields.lastName,is_default:c.fields.isDefault,_ref:c.ref,_changed:c.changed}))}))};
      customer._ref=record.ref;customer._changed=record.changed;customer._mergedInto=record.mergedInto;
      result[number][systemKeys[record.system]]=customer;
    }
    return result;
  }
  function project(snapshot, plan) {
    const output=structuredClone(snapshot), refs=new Map(output.records.map(r=>[r.ref,r]));
    if(!plan||plan.blocked) return output;
    for(const change of plan.changes) {
      const source=refs.get(change.source), target=refs.get(change.target);
      if(!source||!target)continue;
      source.changed=true;target.changed=true;
      if(change.kind.startsWith('link_'))Object.assign(target.fields,change.after);
      if(['set_billing','set_shipping'].includes(change.kind)) {
        const billing=change.kind==='set_billing',swKey=billing?'defaultBillingAddressId':'defaultShippingAddressId';
        for(const r of output.records.filter(r=>r.number===source.number)) {
          if(r.system==='dj'&&r.kind==='address'){const key=billing?'is_invoice':'is_shipping',next=r.ref===source.ref;r.changed ||= Boolean(r.fields[key])!==next;r.fields[key]=next;}
          if(r.system==='sw'&&r.kind==='customer'){r.fields[swKey]=source.fields.api_id;r.changed=true;}
          if(r.system==='mt'&&r.kind==='address'){const key=billing?'isDefaultBilling':'isDefaultShipping',next=r.fields.addressSubNumber===source.fields.erp_ans_nr;r.changed ||= Boolean(r.fields[key])!==next;r.fields[key]=next;}
        }
      }
      if(change.kind==='merge_shopware') {
        source.mergedInto=target.number;
        const sourceTime=Date.parse(source.fields.lastLogin||'')||0,targetTime=Date.parse(target.fields.lastLogin||'')||0;
        if(plan.merge_preview?plan.merge_preview.credentialSourceId===source.fields.id:sourceTime>targetTime) {target.fields.email=source.fields.email;target.fields.lastLogin=source.fields.lastLogin;target.loginFrom=source.number;}
        for(const r of output.records.filter(r=>r.parent===source.ref)){r.parent=target.ref;r.number=target.number;r.changed=true;if(r.kind==='address')r.fields.customerId=target.fields.id;}
        const djSource=output.records.find(r=>r.system==='dj'&&r.kind==='customer'&&r.number===source.number);
        const djTarget=output.records.find(r=>r.system==='dj'&&r.kind==='customer'&&r.number===target.number);
        if(djSource&&djTarget&&djSource.ref!==djTarget.ref) {
          djSource.mergedInto=target.number;djSource.changed=true;djTarget.changed=true;
          const targetAddresses=output.records.filter(r=>r.kind==='address'&&r.parent===djTarget.ref);
          for(const r of output.records.filter(r=>r.parent===djSource.ref)) {
            r.parent=djTarget.ref;r.number=djTarget.number;r.changed=true;
            if(r.kind==='address'){r.fields.customer_id=djTarget.fields.id;
              if(targetAddresses.some(a=>a.fields.is_invoice))r.fields.is_invoice=false;
              if(targetAddresses.some(a=>a.fields.is_shipping))r.fields.is_shipping=false;}
          }
        }
      }
      if(change.kind==='import_shopware_address') {
        let customer=output.records.find(r=>r.system==='dj'&&r.kind==='customer'&&r.number===source.number);
        if(!customer){customer={ref:'preview:customer:'+source.number,number:source.number,system:'dj',kind:'customer',fields:{erp_nr:source.number},changed:true};output.records.push(customer);}
        const f=source.fields,cf=customer.fields,fullName=[target.fields.firstName,target.fields.lastName].filter(Boolean).join(' ');
        Object.assign(cf,{name:target.fields.company||fullName||cf.name,email:target.fields.email||cf.email,api_id:target.fields.id});
        let address=output.records.find(r=>r.system==='dj'&&r.kind==='address'&&r.parent===customer.ref&&r.fields.api_id?.toLowerCase()===f.id.toLowerCase());
        if(!address){address={ref:'preview:address:'+source.ref,system:'dj',kind:'address',number:source.number,parent:customer.ref,isNew:true,fields:{id:'preview:'+source.ref}};output.records.push(address);}
        Object.assign(address.fields,{api_id:f.id,company:f.company||'',name1:f.company||[f.firstName,f.lastName].filter(Boolean).join(' '),name2:f.company?[f.firstName,f.lastName].filter(Boolean).join(' '):'',
          first_name:f.firstName,last_name:f.lastName,street:f.street,postal_code:f.zipcode,city:f.city,country_code:f.country?.iso,email:f.email||cf.email,
          is_invoice:f.id===target.fields.defaultBillingAddressId,is_shipping:f.id===target.fields.defaultShippingAddressId});address.changed=true;
        for(const other of output.records.filter(r=>r.kind==='address'&&r.parent===customer.ref&&r!==address)) {
          for(const role of ['is_invoice','is_shipping'])if(address.fields[role]&&other.fields[role]){other.fields[role]=false;other.changed=true;}
        }
      }
      if(change.kind==='export_django_address') {
        const customer=output.records.find(r=>r.system==='sw'&&r.kind==='customer'&&r.number===source.number);
        if(customer){const f=source.fields,id=f.api_id||'preview:new-address';
          let address=output.records.find(r=>r.system==='sw'&&r.kind==='address'&&r.parent===customer.ref&&r.fields.id?.toLowerCase()===id.toLowerCase());
          if(!address){address={ref:'preview:address:'+source.ref,system:'sw',kind:'address',number:source.number,parent:customer.ref,isNew:true,fields:{id}};output.records.push(address);}
          Object.assign(address.fields,{company:f.name2?f.name1:'',firstName:f.first_name||f.name1||'.',lastName:f.last_name||f.name2||'.',street:f.street||'.',zipcode:f.postal_code||'.',city:f.city||'.',country:{iso:f.country_code}});
          if(f.email)address.fields.email=f.email;address.changed=true;
          f.api_id=id;target.fields.api_id=customer.fields.id;
          if(f.is_invoice||!customer.fields.defaultBillingAddressId)customer.fields.defaultBillingAddressId=id;
          if(f.is_shipping||!customer.fields.defaultShippingAddressId)customer.fields.defaultShippingAddressId=id;
        }
      }
    }
    return output;
  }
  function render(snapshot, plan, before=false) {
    const projected=before?snapshot:project(snapshot,plan), data=sources(projected), original=sources(snapshot);
    const normal=(number,key)=>normalize(data[number]?.[key],key);
    const value=(value,changed=false)=>`<div class="comparison-value${changed?' customer-ai-changed':''}">${esc(value)||'<span class="comparison-empty">—</span>'}</div>`;
    const cards=(number,key,addresses)=>addresses.length?addresses.map(address=>{
      const raw=(data[number]?.[key]?.addresses||[]).find(a=>key==='microtech'?String(a.ans_nr)===String(address.microtechAddressNumber):String(a.id)===String(address.id));
      const changed=!before&&raw?._changed;
      const contacts=(address.contacts||[]).map(c=>`<div class="customer-ai-contact"><strong>${esc(c.name)||'Ansprechpartner'}</strong><span>AnsNr ${esc(address.microtechAddressNumber)} · AnspNr ${esc(c.microtechContactNumber)}</span>${c.email?`<span>${esc(c.email)}</span>`:''}</div>`).join('');
      return `<article class="comparison-address-card${changed?' customer-ai-changed':''}">${raw?._new?'<span class="customer-ai-change-tag">Neu</span>':''}${standardAddressBadges(address)}<strong>${esc(address.label||address.contactName)||'Anschrift'}</strong>${address.contactName&&address.contactName!==address.label?`<div>${esc(address.contactName)}</div>`:''}<div>${esc(address.street)}</div><div>${esc(address.zip)} ${esc(address.city)} ${esc(address.country)}</div>${address.email?`<div>${esc(address.email)}</div>`:''}${contacts}${changed?'<span class="customer-ai-change-tag">Vorgeschlagen</span>':''}</article>`;
    }).join(''):'<div class="comparison-address-empty">Keine zugeordnete Adresse</div>';
    const merge=plan?.operations?.find(op=>op.kind==='merge_shopware'),refs=new Map((snapshot?.records||[]).map(r=>[r.ref,r]));
    const mergeSummary=!before&&merge?`<div class="customer-ai-merge-flow"><strong>Kunde ${esc(refs.get(merge.source)?.number)} → Kunde ${esc(refs.get(merge.target)?.number)}</strong><span>${esc(plan.merge_preview?.addressesMoved??'—')} Adressen · ${esc(plan.merge_preview?.ordersMoved??'—')} Bestellungen übernehmen</span></div>`:'';
    return mergeSummary+Object.keys(data).sort().map(number=>{
      const row=(label,fn)=>comparisonRow(label,SYSTEMS.map(system=>fn(system.key,normal(number,system.key),data[number]?.[system.key])));
      const role=(key,customer,billing)=>{
        const addresses=(customer?.addresses||[]).filter(a=>billing?a.isBilling:a.isShipping);
        return addresses.map(a=>[a.label||a.contactName,a.street,[a.zip,a.city].filter(Boolean).join(' ')].filter(Boolean).join(' · ')).join(' / ');
      };
      let html=`<section class="customer-ai-customer"><h4>Kunde ${esc(number)}</h4><div class="comparison-matrix"><div class="comparison-matrix-corner">${before?'Ist-Zustand':'Vorschlag'}</div>${SYSTEMS.map(system=>`<div class="comparison-system-header">${esc(system.label)}</div>`).join('')}`;
      html+=row('Kunde',(key,c,raw)=>raw?raw._mergedInto?`<span class="customer-ai-removed">Zusammenführen → ${esc(raw._mergedInto)}</span>`:value(c.customerNr):value(''));
      html+=row('Name',(key,c)=>value(c?.name));
      html+=row('E-Mail / Zugang',(key,c)=>value(c?.email,!before&&c?.email!==normalize(original[number]?.[key],key)?.email));
      html+=row('Rechnung',(key,c)=>value(role(key,c,true),!before&&role(key,c,true)!==role(key,normalize(original[number]?.[key],key),true)));
      html+=row('Lieferung',(key,c)=>value(role(key,c,false),!before&&role(key,c,false)!==role(key,normalize(original[number]?.[key],key),false)));
      const groups=addressComparisonGroups(number,data);
      html+=comparisonSection('Adresszuordnungen');
      html+=groups.map(group=>comparisonRow(group.label,SYSTEMS.map(system=>cards(number,system.key,group[system.key])),{cellClass:'comparison-address-cell',labelClass:'comparison-address-label'})).join('');
      return html+'</div></section>';
    }).join('');
  }
  window.CustomerMergePreview={sources,project,render};
})();
