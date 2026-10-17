"""Exercise read-only projections and the real, aligned three-column renderer."""
import json
import shutil
import subprocess
from pathlib import Path
from unittest import skipUnless

from django.test import SimpleTestCase

from customer.services.merge_ai import CustomerMergeAIService
from customer.test_merge_ai import snapshot, plan, operation, SWC

ROOT = Path(__file__).resolve().parents[1]


@skipUnless(shutil.which('node'), 'Node is needed for JavaScript regression checks')
class MergeAIPreviewTests(SimpleTestCase):
    def run_js(self, assertions, proposal=None, data=None):
        template=(ROOT/'templates/admin/customer_merge_ai.html').read_text()
        shared='function normalize'+template.split('function normalize',1)[1].split('function localAddressLabel',1)[0]
        shared+='function comparisonData'+template.split('function comparisonData',1)[1].split('function comparisonAddressActions',1)[0]
        shared+='function addressComparisonGroups'+template.split('function addressComparisonGroups',1)[1].split('function comparisonAddressCell',1)[0]
        snap=data or snapshot();proposal=proposal or plan()
        proposal['changes']=CustomerMergeAIService().compile_plan(proposal,snap)
        harness="""
const assert=require('node:assert/strict');
const window={},searchData={};
const SYSTEMS=[{key:'shopware',label:'SW6'},{key:'django',label:'GC-Bridge'},{key:'microtech',label:'Microtech'}];
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fetch=()=>{throw Error('A proposal must not reload data');};
"""+shared+(ROOT/'customer/static/customer/js/merge_ai_preview.js').read_text()
        harness+='\nconst preview=window.CustomerMergePreview,snap='+json.dumps(snap)+',plan='+json.dumps(proposal)+';\n'+assertions
        result=subprocess.run([shutil.which('node'),'-e',harness],text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_mapping_and_roles_are_projected_without_mutating_search(self):
        self.run_js("""
const original=structuredClone(snap),projected=preview.project(snap,plan);
assert.deepEqual(snap,original);
const sources=preview.sources(projected)['12196'];
assert.equal(sources.django.addresses[0].api_id,'b'.repeat(32));
assert.equal(sources.django.addresses[0].erp_ans_nr,7);
assert.equal(sources.django.addresses[0].is_shipping,true);
assert.equal(sources.shopware.addresses[0].is_shipping,true);
assert.equal(sources.microtech.addresses[0].is_shipping,true);
const html=preview.render(snap,plan),before=preview.render(snap,plan,true);
for(const text of ['SW6','GC-Bridge','Microtech','Gartenweg 8','Lieferadresse'])assert.ok(html.includes(text),text);
assert.ok(html.includes('customer-ai-changed'));assert.ok(!before.includes('customer-ai-changed'));
assert.doesNotMatch(html,/<(?:input|select|button)|onclick=/);
""")

    def test_contact_zero_mapping_aligns_all_three_systems(self):
        proposal=plan([operation('link_shopware_address','sw:address:'+'b'*32,'dj:address:2'),operation('link_microtech_address','mt:contact:12196:7:0','dj:address:2')])
        self.run_js("""
const projected=preview.sources(preview.project(snap,plan));
const groups=addressComparisonGroups('12196',projected);
assert.equal(groups.length,1);
for(const key of ['shopware','django','microtech'])assert.equal(groups[0][key].length,1,key);
assert.equal(groups[0].microtech[0].contacts[0].microtechContactNumber,0);
""",proposal)

    def test_duplicate_standard_addresses_keep_their_roles_when_both_are_linked(self):
        from customer.test_merge_ai_standard_addresses import duplicate_standard_snapshot, standard_plan
        self.run_js("""
const before=preview.sources(snap)['12196'],after=preview.sources(preview.project(snap,plan))['12196'];
for(const system of ['shopware','django','microtech']) {
  const roles=customer=>customer.addresses.map(a=>[a.id??a.ans_nr,a.is_invoice,a.is_shipping]);
  assert.deepEqual(roles(after[system]),roles(before[system]),system+' defaults must remain unchanged');
}
const addresses=after.django.addresses;
assert.equal(addresses.find(a=>a.is_invoice).erp_ans_nr,7);
assert.equal(addresses.find(a=>a.is_shipping).erp_asp_nr,0);
assert.equal(addresses.find(a=>a.id===2).erp_ans_nr,null);
const groups=addressComparisonGroups('12196',preview.sources(preview.project(snap,plan)));
for(const id of [3,4]) {
  const group=groups.find(g=>g.django.some(a=>a.id===id));
  assert.ok(group.microtech.length,'Standard address '+id+' must visibly align with Microtech');
}
assert.ok(preview.render(snap,plan).includes('Rechnungsadresse'));
""", standard_plan(), duplicate_standard_snapshot())

    def test_identical_billing_shipping_and_extra_copies_render_as_one_address(self):
        from customer.test_merge_ai_standard_addresses import duplicate_standard_snapshot, standard_plan
        self.run_js("""
const original=structuredClone(snap),html=preview.render(snap,plan);
assert.ok(html.includes('Rechnung &amp; Lieferung')||html.includes('Rechnung & Lieferung'));
assert.equal((html.match(/data-address-count="3"/g)||[]).length,2,'One combined card in SW6 and Bridge');
const combined=html.match(/<article data-address-count="3"[\\s\\S]*?<\\/article>/g);
for(const card of combined){assert.ok(card.includes('Rechnungsadresse'));assert.ok(card.includes('Lieferadresse'));assert.equal((card.match(/Gartenweg 8/g)||[]).length,1);}
for(const id of [2,3,4])assert.ok(html.includes('Bridge '+id),'All underlying mappings remain inspectable');
assert.equal((html.match(/comparison-address-card/g)||[]).length,4,'Two distinct physical ERP addresses, one SW6 and one Bridge card');
assert.deepEqual(snap,original);
""", standard_plan(), duplicate_standard_snapshot())

    def test_different_recipients_or_hidden_business_fields_are_not_visually_combined(self):
        from customer.test_merge_ai_standard_addresses import duplicate_standard_snapshot, standard_plan
        for system, field in [('dj','last_name'),('dj','department'),('sw','additionalAddressLine1')]:
            with self.subTest(system=system, field=field):
                snap=duplicate_standard_snapshot()
                record=next(r for r in snap['records'] if r['system']==system and r['kind']=='address')
                record['fields'][field]='Andere Abteilung'
                self.run_js("""
const html=preview.render(snap,plan);
assert.equal((html.match(/data-address-count="3"/g)||[]).length,0,'The differing copy and its real partner must stay separate');
assert.ok(html.includes('data-address-count="2"'),'Only the two identical standard copies combine');
""", standard_plan(), snap)

    def test_merge_keeps_target_roles_and_shows_server_selected_login(self):
        import copy
        snap=snapshot();snap['records'][0]['fields'].update(defaultBillingAddressId='b'*32,defaultShippingAddressId='b'*32)
        source=copy.deepcopy(snap['records'][0]);source.update(ref='sw:customer:'+'d'*32,number='950059');source['fields'].update(id='d'*32,email='new@example.com')
        address=copy.deepcopy(snap['records'][1]);address.update(ref='sw:address:'+'e'*32,number='950059',parent=source['ref']);address['fields']['id']='e'*32
        snap['records'] += [source,address]
        proposal=plan([operation('merge_shopware',source['ref'],'sw:customer:'+SWC)])
        proposal['merge_preview']={'credentialSourceId':'d'*32}
        self.run_js("""
const original=structuredClone(snap),data=preview.sources(preview.project(snap,plan));
assert.equal(data['12196'].shopware.email,'new@example.com');
assert.equal(data['12196'].shopware.defaultShippingAddressId,'b'.repeat(32));
assert.equal(data['12196'].shopware.addresses.length,2);
assert.equal(data['950059'].shopware._mergedInto,'12196');
assert.deepEqual(data['12196'].microtech,preview.sources(snap)['12196'].microtech);
assert.deepEqual(snap,original);
assert.ok(preview.render(snap,plan).includes('Zusammenführen → 12196'));
""",proposal,snap)

    def test_import_is_clearly_shown_as_new_and_values_are_escaped(self):
        snap=snapshot();snap['records'][1]['fields']['street']='<img src=x onerror=alert(1)>'
        proposal=plan([operation('import_shopware_address','sw:address:'+'b'*32,'sw:customer:'+SWC)])
        self.run_js("""
const html=preview.render(snap,plan);
assert.ok(html.includes('>Neu</span>'));
assert.ok(html.includes('&lt;img'));assert.ok(!html.includes('<img'));
assert.deepEqual(snap.records.filter(r=>r.kind==='address'&&r.system==='dj').length,1);
""",proposal,snap)

    def test_export_updates_existing_address_without_duplicate_and_preserves_target_role(self):
        snap=snapshot();snap['records'][0]['fields'].update(defaultBillingAddressId='b'*32,defaultShippingAddressId='b'*32)
        snap['records'][3]['fields'].update(api_id='b'*32,first_name='Nina',last_name='Beispiel',street='Neue Straße 5',country_code='DE')
        proposal=plan([operation('export_django_address','dj:address:2','dj:customer:1')])
        self.run_js("""
const data=preview.sources(preview.project(snap,plan))['12196'];
assert.equal(data.shopware.addresses.length,1);
assert.equal(data.shopware.addresses[0].street,'Neue Straße 5');
assert.equal(data.shopware.addresses[0].is_invoice,true);
assert.equal(data.shopware.addresses[0]._new,undefined);
""",proposal,snap)

    def test_import_updates_existing_address_and_customer_without_duplicate(self):
        snap=snapshot();snap['records'][0]['fields'].update(firstName='Nina',lastName='Beispiel',defaultShippingAddressId='b'*32)
        snap['records'][3]['fields']['api_id']='b'*32
        proposal=plan([operation('import_shopware_address','sw:address:'+'b'*32,'sw:customer:'+SWC)])
        self.run_js("""
const data=preview.sources(preview.project(snap,plan))['12196'];
assert.equal(data.django.addresses.length,1);
assert.equal(data.django.name,'Nina Beispiel');
assert.equal(data.django.addresses[0].name1,'');
assert.equal(data.django.addresses[0].is_shipping,true);
assert.equal(data.django.addresses[0]._new,undefined);
""",proposal,snap)
