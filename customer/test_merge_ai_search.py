"""Run the real search/controller JavaScript with delayed sources, without a DB."""
import shutil
import subprocess
from pathlib import Path
from unittest import skipUnless

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[1]


@skipUnless(shutil.which('node'), 'Node is needed for JavaScript regression checks')
class MergeAISearchProgressTest(SimpleTestCase):
    def test_progress_is_visible_outside_collapsed_manual_tools(self):
        template = (ROOT / 'templates/admin/customer_merge_ai.html').read_text().split('<script>', 1)[0]
        self.assertEqual(template.count('id="search-progress"'), 1)
        self.assertLess(template.index('id="results-area"'), template.index('id="search-progress"'))
        self.assertLess(template.index('id="search-progress"'), template.index('id="customer-ai-manual"'))

    def run_js(self, assertions):
        template = (ROOT / 'templates/admin/customer_merge_ai.html').read_text()
        search = template.split('/* ── search ─', 1)[1].split('const MICROTECH_JOB_TIMEOUT_MS', 1)[1]
        search = 'const MICROTECH_JOB_TIMEOUT_MS' + search.split('/* ── render rows', 1)[0]
        search = search.replace('startSearchFromOrderCustomer();', '')
        script = (ROOT / 'customer/static/customer/js/merge_ai.js').read_text()
        gate = 'function updateStart()' + script.split('function updateStart()', 1)[1].split('function renderActivity', 1)[0]
        harness = r'''
const assert = require('node:assert/strict');
let searchData={}, searchErps=[], activeSearchId=0, searchProgress=null;
let run=null, busy=false, swMergePending=null, providerReady=true, providerMessage='Provider fehlt';
const openAddressGroups=new Set(), visibleAddressGroupCounts=new Map();
const SYSTEMS=[{key:'shopware'},{key:'django'},{key:'microtech'}];
const elements=new Map();
const element=id=>{
 if(!elements.has(id)) elements.set(id,{value:'',innerHTML:'',textContent:'',disabled:false,
  lastChild:{textContent:''},attributes:{},classList:{remove(){}},
  setAttribute(key,value){this.attributes[key]=value;}});
 return elements.get(id);
};
const $=id=>element('customer-ai-'+id);
$('provider').value='3';
const document={getElementById:element,dispatchEvent(){updateStart();}};
class CustomEvent { constructor(name){this.type=name;} }
const window={location:{search:''}};
PREVIEW_SCRIPT
const CustomerMergePreview=window.CustomerMergePreview;
const sameSearch=()=>false;
const searchId=()=>searchProgress?.cacheId||'';
const esc=value=>String(value ?? '');
const spinner=()=>'<span>lädt</span>';
const loaderCell=()=>'Lädt';
const numbers=()=>[...new Set(searchErps.map(String))].sort();
const renderComparisonRow=()=>'';
function renderRows(){}
function renderMergeSection(){}
function renderShopwareMergeSection(){}
function setSearchButtonLoading(value){element('search-btn').disabled=value;}
const response=data=>({ok:true,json:async()=>data});
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const flush=()=>new Promise(resolve=>setImmediate(resolve));
let fetch=async()=>{throw new Error('Unexpected request');};
SEARCH_SCRIPT
delay=async()=>{};
GATE_SCRIPT
(async()=>{ASSERTIONS})().catch(error=>{console.error(error);process.exitCode=1;});
'''.replace('PREVIEW_SCRIPT', (ROOT/'customer/static/customer/js/merge_ai_preview.js').read_text()).replace('SEARCH_SCRIPT', search).replace('GATE_SCRIPT', gate).replace('ASSERTIONS', assertions)
        result = subprocess.run([shutil.which('node'), '-e', harness], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_slow_microtech_blocks_ai_and_reuses_one_loaded_snapshot(self):
        self.run_js(r"""
element('search-customer-number').value='12196';
const resolver=deferred(), microtech=deferred(), calls=[];
const snapshot={availability:{'12196':{sw:'found',dj:'not_found'}},records:[
 {ref:'sw:customer:a',system:'sw',kind:'customer',number:'12196',fields:{id:'a',customerNumber:'12196'}}]};
fetch=async url=>{calls.push(url);return url.includes('/resolve/')?resolver.promise:microtech.promise;};
const search=doSearch();
assert.equal($('start').disabled,true);
assert.match(element('search-progress').innerHTML,/Suche läuft/);
resolver.resolve(response({ai_search:{id:'cached',numbers:['12196'],status:'loading',snapshot,search_progress:{mt:'pending'}}}));
await flush();
assert.match(element('search-progress').innerHTML,/GraphQL-Abfrage läuft/);
assert.equal($('start').disabled,true);
microtech.resolve(response({id:'cached',numbers:['12196'],status:'search_ready',
 snapshot:{...snapshot,availability:{'12196':{sw:'found',dj:'not_found',mt:'not_found'}}},search_progress:{mt:'ready'}}));
await search;
assert.equal(getCellState('12196','microtech'),'not_found');
assert.match(element('search-progress').innerHTML,/Abgeschlossen · keine Treffer/);
assert.equal(element('search-progress').attributes['aria-busy'],'false');
assert.equal($('start').disabled,false);
assert.equal(searchId(),'cached');
assert.equal(calls.length,2);
assert.match(calls[0],/ai_search=1/);
assert.match(calls[1],/run_id=cached/);
assert.ok(calls.every(url=>!url.includes('search-cell')&&!url.includes('microtech-search-status')));
""")

    def test_failed_search_is_never_shown_as_no_results(self):
        self.run_js(r"""
element('search-customer-number').value='12196';
fetch=async()=>response({ai_search:{id:'cached',numbers:['12196'],status:'failed',message:'Microtech ist nicht erreichbar.',search_progress:{mt:'failed'}}});
await doSearch();
assert.equal($('start').disabled,true);
assert.match(element('search-progress').innerHTML,/Suche unvollständig/);
assert.match(element('search-progress').innerHTML,/Microtech ist nicht erreichbar/);
assert.equal(element('search-progress').attributes['aria-busy'],'false');
""")

    def test_resolution_failure_has_visible_error_and_no_spinner(self):
        self.run_js(r"""
element('search-customer-number').value='12196';
fetch=async()=>({ok:false,json:async()=>({error:'Suchabfrage konnte nicht gestartet werden.'})});
await doSearch();
assert.equal($('start').disabled,true);
assert.match(element('search-progress').innerHTML,/Suchabfrage konnte nicht gestartet/);
assert.equal(element('search-progress').attributes['aria-busy'],'false');
""")

    def test_empty_snapshot_keeps_ai_disabled(self):
        self.run_js(r"""
element('search-customer-number').value='12196';
fetch=async()=>response({ai_search:{id:'empty',numbers:[],status:'search_ready',snapshot:{records:[],availability:{}},search_progress:{mt:'not_applicable'}}});
await doSearch();assert.equal($('start').disabled,true);
assert.match($('status').textContent,/Keine Kunden gefunden/);
""")

    def test_earlier_response_cannot_replace_newer_search(self):
        self.run_js(r"""
element('search-customer-number').value='12196';
const old=deferred();let first=true;
const loaded={id:'new',numbers:['950059'],status:'search_ready',search_progress:{mt:'not_applicable'},snapshot:{
 availability:{'950059':{sw:'found',dj:'not_found',mt:'not_found'}},records:[{ref:'sw:customer:new',kind:'customer',system:'sw',number:'950059',fields:{id:'new'}}]}};
fetch=async()=>first?(first=false,old.promise):response({ai_search:loaded});
const previous=doSearch();element('search-customer-number').value='950059';
await doSearch();
old.resolve(response({ai_search:{id:'old',numbers:['12196'],status:'search_ready'}}));await previous;
assert.deepEqual(searchErps,['950059']);assert.equal(searchId(),'new');
assert.equal($('start').disabled,false);
providerReady=false;updateStart();assert.equal($('start').disabled,true);
""")
