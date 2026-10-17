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
        gate = 'function updateStart()' + script.split('function updateStart()', 1)[1].split('function setBusy', 1)[0]
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
const esc=value=>String(value ?? '');
const spinner=()=>'<span>lädt</span>';
const loaderCell=()=>'Lädt';
const numbers=()=>[...new Set(searchErps.map(String))].sort();
const renderComparisonRow=()=>'';
function renderRows(){}
function renderMergeSection(){}
function setSearchButtonLoading(value){element('search-btn').disabled=value;}
const response=data=>({ok:true,json:async()=>data});
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const flush=()=>new Promise(resolve=>setImmediate(resolve));
let fetch=async()=>{throw new Error('Unexpected request');};
SEARCH_SCRIPT
GATE_SCRIPT
(async()=>{ASSERTIONS})().catch(error=>{console.error(error);process.exitCode=1;});
'''.replace('SEARCH_SCRIPT', search).replace('GATE_SCRIPT', gate).replace('ASSERTIONS', assertions)
        result = subprocess.run([shutil.which('node'), '-e', harness], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_slow_microtech_is_visible_and_blocks_ai_until_finished(self):
        self.run_js(r'''
element('search-customer-number').value='12196';
const resolve=deferred(), microtech=deferred();
fetch=async url=>url.includes('/resolve/')?resolve.promise:url.includes('/search-cell/')
 ?response({data:{id:'example'}}):microtech.promise;
const search=doSearch();
assert.equal($('start').disabled,true);
assert.match(element('search-progress').innerHTML,/Suche läuft/);
assert.equal(element('search-progress').attributes['aria-busy'],'true');
resolve.resolve(response({erp_nrs:['12196'],microtech_jobs:[{job_id:7}],
 search_summary:{microtech_candidates:1,microtech_candidate_numbers:['12196']}}));
await search;await flush();
assert.match(element('search-progress').innerHTML,/GraphQL-Abfrage läuft/);
assert.match($('status').textContent,/Microtech wird noch abgefragt/);
assert.equal($('start').disabled,true);
microtech.resolve(response({jobs:[{job_id:7,state:'succeeded',result_count:0,customers:[]}]}));
await flush();
assert.equal(getCellState('12196','microtech'),'not_found');
assert.match(element('search-progress').innerHTML,/Abgeschlossen · keine Treffer/);
assert.equal(element('search-progress').attributes['aria-busy'],'false');
assert.equal($('start').disabled,false);
assert.match($('status').textContent,/Du kannst jetzt/);
''')

    def test_microtech_finished_does_not_hide_pending_shopware(self):
        self.run_js(r'''
searchErps=['12196'];searchData={'12196':{django:{id:1}}};
searchProgress={microtech:{state:'succeeded',found:1},cellStates:{'12196':{shopware:'loading',django:'found'}}};
renderSearchProgress();
assert.match(element('search-progress').innerHTML,/Suche läuft/);
assert.equal($('start').disabled,true);
searchData['12196'].shopware={id:'sw'};setCellState('12196','shopware','found');
renderSearchProgress();assert.equal($('start').disabled,false);
providerReady=false;updateStart();assert.equal($('start').disabled,true);
''')

    def test_failed_or_incomplete_microtech_never_becomes_no_results(self):
        self.run_js(r'''
searchErps=['12196'];searchData={'12196':{shopware:{id:'sw'},django:{id:1}}};
searchProgress={microtech:{state:'pending'},microtechResultsPending:true,microtechCandidateNumbers:new Set(['12196']),cellStates:{'12196':{microtech:'pending'}}};
fetch=async()=>response({jobs:[]});
await addMicrotechResults([7],activeSearchId);
assert.equal($('start').disabled,true);
assert.equal(getCellState('12196','microtech'),'failed');
assert.match(element('search-progress').innerHTML,/Abfrage fehlgeschlagen/);
assert.doesNotMatch(element('search-progress').innerHTML,/Abgeschlossen · keine Treffer/);
''')

    def test_failed_submission_is_not_treated_as_skipped(self):
        self.run_js(r'''
element('search-customer-number').value='12196';
fetch=async url=>response(url.includes('/resolve/')
 ?{erp_nrs:['12196'],microtech_jobs:[],search_summary:{microtech_candidates:1}}
 :{data:{id:'test'}});
await doSearch();await flush();
assert.equal(searchProgress.microtech.state,'failed');
assert.equal($('start').disabled,true);
assert.match(element('search-progress').innerHTML,/Abfrage fehlgeschlagen/);
''')

    def test_no_matches_in_any_source_keeps_ai_disabled(self):
        self.run_js(r'''
searchErps=['12196'];searchData={'12196':{shopware:null,django:null}};
searchProgress={microtech:{state:'succeeded',found:0},cellStates:{}};
renderSearchProgress();assert.equal($('start').disabled,true);
assert.match($('status').textContent,/Keine Kunden gefunden/);
''')

    def test_earlier_search_response_cannot_replace_newer_results(self):
        self.run_js(r'''
element('search-customer-number').value='12196';
const old=deferred();let first=true;
fetch=async url=>url.includes('/resolve/')?(first?(first=false,old.promise):response({erp_nrs:['950059'],microtech_jobs:[]})):response({data:{id:'new'}});
const previous=doSearch();element('search-customer-number').value='950059';
await doSearch();await flush();
old.resolve(response({erp_nrs:['12196'],microtech_jobs:[]}));await previous;
assert.deepEqual(searchErps,['950059']);
assert.equal($('start').disabled,false);
''')
