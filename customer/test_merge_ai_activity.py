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
        activity = 'function renderActivity()' + script.split('function renderActivity()', 1)[1].split('function progressMessage', 1)[0]
        harness = r'''
const assert=require('node:assert/strict');
const elements=new Map();
const $=id=>{if(!elements.has(id))elements.set(id,{hidden:false,dataset:{}});return elements.get(id);};
let busy=true,connectionLost=false,run=null,selected=0;
ACTIVITY
renderActivity();
assert.equal($('spinner').hidden,false);
assert.equal($('wait-hint').hidden,false);
for(const id of ['refresh','review','apply','retry'])assert.equal($(id).hidden,true,id);
run={status:'loading'};busy=false;renderActivity();
assert.equal($('spinner').hidden,false);
run.status='ready';renderActivity();assert.equal($('spinner').hidden,true);
run.status='applying';renderActivity();assert.equal($('spinner').hidden,false);
connectionLost=true;busy=true;renderActivity();
assert.equal($('spinner').hidden,true);
assert.equal($('refresh').hidden,false);
assert.equal($('apply').hidden,true);
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
