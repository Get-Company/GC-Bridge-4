"""Run the real controller: consent -> verified merge -> fresh search -> proposals."""
import json
import shutil
import subprocess
from pathlib import Path
from unittest import skipUnless

from django.test import SimpleTestCase

from customer.test_merge_ai import plan
from customer.test_merge_ai_merge_first import multiple_snapshot

ROOT=Path(__file__).resolve().parents[1]


@skipUnless(shutil.which('node'),'Node is needed for controller checks')
class MergeFirstControllerTests(SimpleTestCase):
    def run_js(self,assertions,deny_target_creation=False,initial_snapshot=None,initial_plan=None,mapping_mode=False):
        harness=r'''
const assert=require('node:assert/strict');const denyTargetCreation=DENY_TARGET;const mappingReply=MAPPING_MODE;
const elements=new Map(),timers=[],requests=[],searches=[],rendered=[];
const element=id=>{
 if(!elements.has(id))elements.set(id,{value:'',innerHTML:'',textContent:'',hidden:false,disabled:false,open:false,dataset:{apiUrl:'/ai'},lastChild:{textContent:''},
  listeners:{},classList:{remove(){},toggle(name,value){this[name]=value;}},setAttribute(){},replaceChildren(){},append(option){this.value=String(option.value);},
  addEventListener(name,fn){this.listeners[name]=fn;},querySelectorAll(){return [];},querySelector(){return {scrollTop:0,addEventListener(){}};},
  showModal(){this.open=true;},close(){this.open=false;this.listeners.close?.();}});
 return elements.get(id);
};
const document={getElementById:element,createElement:()=>({}),addEventListener(){}};
const modal=element('customer-ai-dialog'),ui=id=>element('customer-ai-'+id);
const storage=new Map(),sessionStorage={getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)};
const setTimeout=fn=>(timers.push(fn),timers.length),clearTimeout=()=>{};
const CSRF='test';let swMergePending=null,searchErps=['12196','950059'],busySearch=false,searchFailure=false,remainingCount=1;
let searchProgress={cacheId:'search0',snapshot:SNAPSHOT};
const renderCustomerAIRecommendations=(snapshot,plan,before)=>rendered.push({snapshot,plan,before});
const CustomerMergePreview={render:(snapshot,plan,before)=>{rendered.push({snapshot,plan,before});return 'three-columns';}};
const customerAISearchReadiness=()=>({ready:!busySearch&&!searchFailure,message:searchFailure?'Suche unvollständig':'Geladen'});
async function doSearch(options){searches.push(options);if(searchFailure)return;searchProgress={cacheId:'search'+searches.length,snapshot:structuredClone(searchProgress.snapshot)};
 if(!lastMerge)return;
 const source=lastMerge.merge_selection.source;searchProgress.snapshot.records=searchProgress.snapshot.records.filter(r=>r.ref!==source&&r.parent!==source);
 searchErps=lastMerge.post_merge_numbers;}
const response=(data,ok=true)=>({ok,status:ok?200:400,json:async()=>structuredClone(data)});
const results=new Map();let mergeCount=0,analysisCount=0,lastMerge=null,mergeStatus='applied',loseMergeResponse=false,statusUnsubmitted=false,executeCount=0,addressStatus='applied',addressStatusCount=0;
let fetch=async(url,options)=>{
 const body=options?.body?JSON.parse(options.body):null;requests.push({url,body});
 if(body?.action==='merge'){
  mergeCount++;const source=searchProgress.snapshot.records.find(r=>r.ref===body.source_ref),target=searchProgress.snapshot.records.find(r=>r.ref===body.target_ref);
  lastMerge={id:'merge'+mergeCount,workflow:'merge_first',search_id:body.search_id,numbers:[...searchErps],snapshot:structuredClone(searchProgress.snapshot),
   merge_selection:{source:body.source_ref,target:body.target_ref},keep_number:target.number,post_merge_numbers:searchErps.filter(n=>n!==source.number),
   phase:'execute',status:mergeStatus,message:'Merge geprüft',proposals:[],version:1};
  results.set(lastMerge.id,lastMerge);if(loseMergeResponse)throw Error('connection lost');return response({...lastMerge,status:'loading'});
 }
 if(body?.action==='analyze'){
  analysisCount++;const run={mapping_only:mappingReply,id:'analysis'+analysisCount,phase:'analyze',status:'ready',search_id:body.search_id,numbers:[...searchErps],snapshot:structuredClone(searchProgress.snapshot),proposals:[PLAN],version:1,message:'Bereit',approval_tokens:['token']};
  results.set(run.id,run);return response({...run,status:'loading',proposals:null});
 }
 if(body?.action==='execute'){
  executeCount++;const r=results.get(body.run_id);Object.assign(r,{workflow:mappingReply?'mapping':'address_consolidation',phase:'execute',status:addressStatus,post_merge_numbers:[...searchErps],selected:0});
  return response({...r,status:'loading'});
 }
 if(body?.action==='address_merge_status'){
  addressStatusCount++;const r=results.get(body.run_id);r.status=addressStatus;return response({...r,status:'loading'});
 }
 if(body)throw Error('Unexpected POST '+body.action);
 if(url.includes('merge_search_id='))return response(statusUnsubmitted?{status:'not_submitted'}:lastMerge);
 if(url.includes('run_id='))return response(results.get(decodeURIComponent(url.split('run_id=')[1])));
 return response({providers:[{id:3,name:'Test',model:'Test'}],can_apply:true,can_merge:true,can_consolidate_addresses:true,can_change_order:true,can_create_merge_target:!denyTargetCreation});
};
CONTROLLER
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const click=async id=>{await ui(id).listeners.click?.();await flush();};
const choose=async(id,value)=>{ui(id).value=value;await ui(id).listeners.change?.();await flush();};
const tick=async()=>{assert.ok(timers.length,'expected polling');await timers.shift()();await flush();};
const source='sw:customer:'+'4'.repeat(32),target='sw:customer:'+'a'.repeat(32);
(async()=>{await flush();ASSERTIONS})().catch(error=>{console.error(error);process.exitCode=1;});
'''.replace('MAPPING_MODE',str(mapping_mode).lower()).replace('DENY_TARGET',str(deny_target_creation).lower()).replace('SNAPSHOT',json.dumps(initial_snapshot or multiple_snapshot(3))).replace('PLAN',json.dumps(initial_plan or {**plan(),'changes':[],'blocked':''})).replace('CONTROLLER',(ROOT/'customer/static/customer/js/merge_ai.js').read_text()).replace('ASSERTIONS',assertions)
        result=subprocess.run([shutil.which('node'),'-e',harness],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_main_view_has_no_explanatory_paragraph_and_the_direction_matches_the_pickers(self):
        template=(ROOT/'templates/admin/customer_merge_ai_dialog.html').read_text()
        self.assertNotIn('id="customer-ai-plan-reason"',template)
        self.assertLess(template.index('for="customer-ai-merge-source"'),template.index('for="customer-ai-merge-keep"'))

    def test_merge_is_explicit_then_fresh_data_is_analyzed_and_shown_without_prose(self):
        self.run_js(r'''
searchProgress.snapshot.records=searchProgress.snapshot.records.filter(r=>r.number!=='950060');
await click('start');assert.equal(analysisCount,0);assert.equal(ui('merge-stage').hidden,false);assert.equal(ui('apply').disabled,true);
await choose('merge-keep',target);assert.equal(ui('apply').disabled,true);
await choose('merge-source',source);assert.equal(ui('apply').disabled,false);
await click('apply');assert.equal(mergeCount,1);assert.equal(analysisCount,0);assert.equal(searches.length,0);
assert.equal(requests.find(r=>r.body?.action==='merge').body.target_ref,target);
await tick();assert.deepEqual(searches,[{customerNumbers:['12196']}]);assert.equal(analysisCount,1);
await tick();assert.equal(ui('merge-stage').hidden,true);assert.equal(ui('sidebar').hidden,false);
assert.ok(ui('choices').innerHTML.includes('data-plan="0"'));
assert.ok(rendered.at(-1).snapshot.records.every(r=>r.ref!==source));
assert.equal(ui('plan-reason').textContent,'');
assert.deepEqual(requests.filter(r=>r.body).map(r=>r.body.action),['merge','analyze']);
''')

    def test_three_accounts_keep_target_and_request_next_wrong_account_before_analysis(self):
        self.run_js(r'''
searchErps.push('950060');await click('start');await choose('merge-keep',target);await choose('merge-source',source);await click('apply');await tick();
assert.equal(mergeCount,1);assert.equal(analysisCount,0);assert.equal(ui('merge-stage').hidden,false);
assert.equal(ui('merge-keep').value,target);assert.equal(ui('merge-source').value,'');assert.equal(ui('apply').disabled,true);
await choose('merge-source','sw:customer:'+'5'.repeat(32));await click('apply');await tick();await tick();
assert.equal(mergeCount,2);assert.equal(analysisCount,1);
assert.deepEqual(searches.map(s=>s.customerNumbers),[['12196','950060'],['12196']]);
''')

    def test_uncertain_merge_never_triggers_reload_or_paid_analysis(self):
        self.run_js(r'''
mergeStatus='needs_review';await click('start');await choose('merge-keep',target);await choose('merge-source',source);await click('apply');await tick();
assert.equal(searches.length,0);assert.equal(analysisCount,0);assert.equal(ui('apply').hidden,true);assert.equal(ui('refresh').hidden,false);
''')

    def test_failure_after_merge_retries_loading_and_does_not_repeat_merge(self):
        self.run_js(r'''
searchProgress.snapshot.records=searchProgress.snapshot.records.filter(r=>r.number!=='950060');
await click('start');await choose('merge-keep',target);await choose('merge-source',source);await click('apply');
searchFailure=true;await tick();assert.equal(ui('retry').hidden,false);assert.equal(ui('retry').textContent,'Daten neu laden');
assert.equal(mergeCount,1);assert.equal(analysisCount,0);
searchFailure=false;await click('retry');await tick();assert.equal(mergeCount,1);assert.equal(analysisCount,1);
''')

    def test_lost_confirmation_response_recovers_status_without_posting_merge_twice(self):
        self.run_js(r'''
loseMergeResponse=true;await click('start');await choose('merge-keep',target);await choose('merge-source',source);await click('apply');
assert.equal(ui('refresh').hidden,false);await click('refresh');
assert.equal(mergeCount,1);assert.ok(requests.some(r=>r.url.includes('merge_search_id=')));
''')

    def test_unsubmitted_confirmation_requires_an_explicit_new_click(self):
        self.run_js(r'''
loseMergeResponse=true;statusUnsubmitted=true;await click('start');await choose('merge-keep',target);await choose('merge-source',source);await click('apply');await click('refresh');
assert.equal(mergeCount,1);assert.equal(analysisCount,0);assert.equal(ui('apply').hidden,false);assert.equal(ui('apply').disabled,false);
assert.ok(ui('error').textContent.includes('erneut bestätigen'));
''')

    def test_distinct_accounts_can_be_kept_separate_explicitly(self):
        self.run_js(r'''
await click('start');await click('merge-skip');assert.equal(mergeCount,0);assert.equal(analysisCount,1);
assert.equal(requests.find(r=>r.body?.action==='analyze').body.separate_accounts,true);
''')

    def test_analysis_locks_addresses_and_escape_until_the_result_arrives(self):
        self.run_js(r'''
await click('start');await click('merge-skip');
assert.equal(ui('content').inert,true);assert.equal(ui('merge-stage').inert,true);
assert.equal(element('customer-ai-manual').inert,true);assert.equal(element('customer-merge-search-form').inert,true);
let prevented=false;modal.listeners.cancel({preventDefault(){prevented=true;}});assert.equal(prevented,true);
assert.equal(ui('apply').disabled,true);
await tick();assert.equal(ui('content').inert,false);assert.equal(element('customer-ai-manual').inert,false);
assert.equal(element('customer-merge-search-form').inert,false);
prevented=false;modal.listeners.cancel({preventDefault(){prevented=true;}});assert.equal(prevented,false);
''')

    def test_missing_target_is_marked_and_requires_creation_permission(self):
        self.run_js(r'''
await click('start');await choose('merge-keep',source);await choose('merge-source',target);
assert.ok(ui('merge-direction').innerHTML.includes('GC-Bridge · wird angelegt'));
assert.equal(ui('apply').disabled,true);assert.ok(ui('merge-warning').textContent.includes('Keine Berechtigung'));
await click('apply');assert.equal(mergeCount,0);
''',deny_target_creation=True)

    def test_missing_target_can_be_confirmed_with_creation_permission(self):
        self.run_js(r'''
await click('start');await choose('merge-keep',source);await choose('merge-source',target);
assert.ok(ui('merge-direction').innerHTML.includes('GC-Bridge · wird angelegt'));
assert.equal(ui('apply').disabled,false);await click('apply');assert.equal(mergeCount,1);
''')

    def address_fixture(self):
        from customer.test_merge_ai_standard_addresses import duplicate_standard_snapshot
        from customer.test_address_consolidation import consolidation_plan
        from customer.services.merge_ai import CustomerMergeAIService
        snap=duplicate_standard_snapshot();proposal=consolidation_plan(snap)
        proposal.update(changes=CustomerMergeAIService().compile_plan(proposal,snap),blocked='')
        return dict(initial_snapshot=snap,initial_plan=proposal)

    def test_address_consolidation_is_confirmed_once_then_fresh_data_is_analyzed(self):
        self.run_js(r'''
searchErps=['12196'];await click('start');await tick();
assert.equal(ui('apply').textContent,'Adressen zusammenführen');assert.equal(ui('apply').disabled,false);
await click('apply');assert.equal(executeCount,1);assert.equal(searches.length,0);
await tick();assert.equal(executeCount,1);assert.deepEqual(searches,[{customerNumbers:['12196']}]);
assert.equal(analysisCount,2);assert.equal(ui('content').inert,true);
''',**self.address_fixture())

    def test_uncertain_address_merge_has_readonly_status_recovery_and_no_repeat(self):
        self.run_js(r'''
searchErps=['12196'];await click('start');await tick();addressStatus='needs_review';await click('apply');await tick();
assert.equal(executeCount,1);assert.equal(searches.length,0);assert.equal(analysisCount,1);
assert.equal(ui('refresh').hidden,false);addressStatus='applied';await click('refresh');
assert.equal(addressStatusCount,1);assert.equal(executeCount,1);await tick();
assert.equal(executeCount,1);assert.equal(searches.length,1);assert.equal(analysisCount,2);
''',**self.address_fixture())

    def test_mapping_recommendation_is_inline_and_confirming_refreshes_without_paid_reanalysis(self):
        from customer.test_merge_ai import snapshot
        self.run_js(r"""
await flush();searchErps=['12196'];ui('start').listeners.click();await flush();
assert.equal(requests.find(r=>r.body?.action==='analyze').body.mapping_only,true);
await tick();assert.equal(modal.open,false);assert.equal(ui('inline').hidden,false);
assert.equal(rendered.at(-1).before,false);
ui('inline-apply').listeners.click();await flush();assert.equal(executeCount,1);
assert.equal(modal.open,true);await tick();
assert.equal(searches.length,1);assert.equal(analysisCount,1);assert.equal(ui('inline').hidden,true);assert.equal(modal.open,false);
""",initial_snapshot=snapshot(),mapping_mode=True)

    def test_two_shopware_accounts_highlight_the_merge_area(self):
        self.run_js(r"""
await flush();assert.equal(ui('merge-hint').hidden,false);
assert.equal(element('sw-merge-section').classList['customer-ai-merge-needed'],true);
assert.equal(mergeCount,0);assert.equal(analysisCount,0);
""")

    def test_older_cached_alternatives_are_not_offered_and_correct_token_is_used(self):
        from customer.test_merge_ai import snapshot
        self.run_js(r"""
await flush();searchErps=['12196'];ui('start').listeners.click();await flush();
const saved=results.get('analysis1'),valid=saved.proposals[0];
saved.proposals=[{...valid,title:'Kundenzuordnung bestätigen',blocked:'Ungültige Zuordnung'},valid,{...valid,title:'Bestehende Adressen zuordnen'}];
saved.approval_tokens=['wrong','approved','unused'];
await tick();
assert.equal(ui('start').hidden,true);assert.equal(ui('inline-choices').innerHTML,'');
assert.deepEqual(rendered.at(-1).plan,valid);assert.equal(rendered.at(-1).before,false);
ui('inline-apply').listeners.click();await flush();
const confirm=requests.find(r=>r.body?.action==='execute').body;
assert.equal(confirm.index,1);assert.equal(confirm.preview_token,'approved');assert.equal(executeCount,1);
""",initial_snapshot=snapshot(),mapping_mode=True)
