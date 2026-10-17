"""Exercise the real modal's busy/recovery controls without a database."""
import shutil
import subprocess
from pathlib import Path
from unittest import skipUnless

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[1]


@skipUnless(shutil.which('node'), 'Node is needed for JavaScript regression checks')
class MergeAIActivityTest(SimpleTestCase):
    def test_spinner_tracks_work_and_status_recovery_is_exceptional(self):
        script = (ROOT / 'customer/static/customer/js/merge_ai.js').read_text()
        activity = 'function renderActivity()' + script.split('function renderActivity()', 1)[1].split('function setBusy', 1)[0]
        harness = r'''
const assert=require('node:assert/strict');
const elements=new Map();
const $=id=>{if(!elements.has(id))elements.set(id,{hidden:false,dataset:{},setAttribute(k,v){this[k]=v;}});return elements.get(id);};
const closeButtons=[{},{}],modal={dataset:{},querySelectorAll:()=>closeButtons};
const document={getElementById:id=>$(id)};
let busy=true,connectionLost=false,run=null,selected=0,before=false,mergeGate=null,continuationFailed=false,canCreateMergeTarget=false;const needsTargetCreation=()=>false;const canAccept=()=>false;
ACTIVITY
renderActivity();
assert.equal($('spinner').hidden,false);
assert.equal($('wait-hint').hidden,false);
for(const id of ['refresh','apply','retry'])assert.equal($(id).hidden,true,id);
for(const id of ['content','merge-stage','customer-ai-manual','customer-merge-search-form','inline','merge-hint'])assert.equal($(id).inert,true,id);
assert.ok(closeButtons.every(button=>button.disabled));assert.equal($('apply').disabled,true);
run={status:'loading'};busy=false;renderActivity();
assert.equal($('spinner').hidden,false);
run.status='ready';renderActivity();assert.equal($('spinner').hidden,true);
assert.equal($('content').inert,false);assert.ok(closeButtons.every(button=>!button.disabled));
run.status='applying';renderActivity();assert.equal($('spinner').hidden,false);
connectionLost=true;busy=true;renderActivity();
assert.equal($('spinner').hidden,true);
assert.equal($('refresh').hidden,false);
assert.equal($('apply').hidden,true);
assert.equal($('content').inert,true);assert.ok(closeButtons.every(button=>!button.disabled));
connectionLost=false;run.status='failed';busy=false;renderActivity();
assert.equal($('spinner').hidden,true);
assert.equal($('retry').hidden,false);
assert.equal($('refresh').hidden,true);
run.status='needs_review';renderActivity();
assert.equal($('refresh').hidden,false);
assert.equal($('retry').hidden,true);
'''.replace('ACTIVITY', activity)
        result = subprocess.run([shutil.which('node'), '-e', harness], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
