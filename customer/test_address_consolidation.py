import copy
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.cache import caches
from django.core.serializers.json import DjangoJSONEncoder
from django.test import SimpleTestCase, override_settings, RequestFactory

from customer.models import Address
from customer.services.address_consolidation import AddressConsolidationRejected, AddressConsolidationService
from customer.services.merge_ai import CustomerMergeAIService, fingerprint
from customer.test_merge_ai import CACHE, operation, plan, state
from customer.test_merge_ai_standard_addresses import duplicate_standard_snapshot
from customer.views import customer_merge_ai_api


def consolidation_plan(snap=None):
    return AddressConsolidationService.proposals(snap or duplicate_standard_snapshot())[0]


def consolidated_snapshot(snap, spec):
    result=copy.deepcopy(snap)
    removed={r['ref'] for r in spec['sw_sources']}
    result['records']=[r for r in result['records'] if r['system']=='sw' and r['ref'] not in removed]
    for r in result['records']:
        if r['ref']==spec['sw_customer']['ref']:r['fields'].update(spec['defaults'])
    return result


@override_settings(CACHES=CACHE)
class AddressConsolidationTests(SimpleTestCase):
    def setUp(self):
        caches['customer_merge_ai'].clear()
        self.snap=duplicate_standard_snapshot()
        self.service=AddressConsolidationService()
        self.ai=CustomerMergeAIService()
        self.proposal=consolidation_plan(self.snap)
        self.target=self.proposal['operations'][0]['target']
        self.spec=self.service.preview(self.snap,self.target)

    def test_selects_billing_survivor_and_all_exact_copies_without_question(self):
        self.assertEqual(self.target,'dj:address:3')
        self.assertEqual(self.proposal['questions'],[])
        self.assertEqual({r['fields']['id'] for r in self.spec['local_sources']},{2,4})
        self.assertEqual(len(self.spec['sw_sources']),2)
        self.assertEqual(self.spec['roles'],{'is_invoice':True,'is_shipping':True})
        self.assertEqual(set(self.spec['defaults'].values()),{'c'*32})
        original=copy.deepcopy(self.snap)
        changes=self.ai.compile_plan(self.proposal,self.snap)
        self.assertEqual(changes[0]['after']['Adresse'],self.target)
        self.assertEqual(self.snap,original)

    def test_never_combines_different_people_business_fields_or_metadata(self):
        for system,field,value in [('dj','last_name','Andere Person'),('dj','department','Andere Stelle'),
                                   ('sw','additionalAddressLine1','Andere Niederlassung'),('sw','hasMergeMetadata',True)]:
            with self.subTest(field=field):
                snap=copy.deepcopy(self.snap)
                record=next(r for r in snap['records'] if r['system']==system and r['kind']=='address')
                record['fields'][field]=value
                self.assertEqual(self.service.proposals(snap),[])

    def test_different_microtech_keys_block_instead_of_discarding_a_mapping(self):
        for key in ['erp_ans_nr','erp_asp_nr','erp_ans_id','erp_asp_id','erp_combined_id']:
            with self.subTest(key=key):
                snap=copy.deepcopy(self.snap)
                for r in snap['records']:
                    if r['ref']=='dj:address:3':r['fields'][key]=0 if key!='erp_combined_id' else 'one'
                    if r['ref']=='dj:address:4':r['fields'][key]=1 if key!='erp_combined_id' else 'two'
                self.assertEqual(self.service.proposals(snap),[])

    def test_compatible_postal_and_contact_zero_mapping_is_preserved(self):
        for r in self.snap['records']:
            if r['ref']=='dj:address:3':r['fields'].update(erp_ans_nr=0)
            if r['ref']=='dj:address:4':r['fields'].update(erp_ans_nr=0,erp_asp_nr=0)
        spec=self.service.preview(self.snap,'dj:address:3')
        self.assertEqual(spec['mapping']['erp_ans_nr'],0)
        self.assertEqual(spec['mapping']['erp_asp_nr'],0)

    def test_mixed_case_existing_shopware_mapping_keeps_the_canonical_remote_id(self):
        for record in self.snap['records']:
            if record['ref']==self.target:record['fields']['api_id']=record['fields']['api_id'].upper()
        spec=self.service.preview(self.snap,self.target)
        self.assertEqual(spec['keep_sw_id'],'c'*32)
        self.assertEqual(set(spec['defaults'].values()),{'c'*32})
        self.service.verify_shopware(spec,self.snap,consolidated_snapshot(self.snap,spec))

    def test_mixed_operations_or_wrong_source_are_blocked(self):
        bad=copy.deepcopy(self.proposal);bad['operations'].append(operation('link_customer','sw:customer:'+'a'*32,'dj:customer:1'))
        with self.assertRaisesRegex(ValueError,'einzelner'):self.ai.compile_plan(bad,self.snap)
        bad=copy.deepcopy(self.proposal);bad['operations'][0]['source']='mt:address:12196:7'
        with self.assertRaisesRegex(ValueError,'keine identische Kopie'):self.ai.compile_plan(bad,self.snap)

    def test_historical_order_references_are_counted_but_not_rewritten_in_preview(self):
        self.snap['records'].append({'ref':'dj:order:9','system':'dj','kind':'order','number':'12196','parent':'dj:customer:1',
            'fields':{'id':9,'billing_address_id':4,'shipping_address_id':2}})
        original=copy.deepcopy(self.snap)
        spec=self.service.preview(self.snap,self.target)
        self.assertEqual(spec['order_count'],1)
        self.assertEqual(spec['order_refs'][9]['customer_id'],1)
        self.assertEqual(self.snap,original)

    @patch('orders.models.Order.objects')
    @patch('customer.services.address_consolidation.Address.objects')
    def test_fresh_local_validation_accepts_encoded_dates_and_rejects_changed_orders(self, addresses, orders):
        now=datetime(2026,10,17,12,tzinfo=timezone.utc)
        rows=[]
        for record in [self.spec['target'],*self.spec['local_sources']]:
            row=copy.deepcopy(record['fields']);row['updated_at']=now;rows.append(row)
            record['fields']['updated_at']=json.loads(json.dumps(now,cls=DjangoJSONEncoder))
        addresses.filter.return_value.exclude.return_value.exists.return_value=False
        addresses.filter.return_value.values.return_value=rows
        orders.filter.return_value.values.return_value=[]
        self.service.preflight_local(self.spec)
        orders.filter.return_value.values.return_value=[{'id':99,'customer_id':42,'billing_address_id':2,'shipping_address_id':None}]
        with self.assertRaisesRegex(ValueError,'Bestellverweise'):self.service.preflight_local(self.spec)

    @patch('shopware.services.CustomerService')
    def test_remote_write_is_one_authenticated_request_with_defaults_and_deletes(self, shop):
        client=shop.return_value.client
        client.session.post.return_value=SimpleNamespace(status_code=200,json=lambda:{'deleted':{'customer_address':[]},'notFound':[]})
        self.service.execute_remote(self.spec)
        client.request_post.assert_not_called()
        client.session.post.assert_called_once()
        kwargs=client.session.post.call_args.kwargs
        payload=kwargs['json']
        self.assertEqual(payload['keep-defaults']['payload'][0]['defaultShippingAddressId'],'c'*32)
        self.assertEqual({r['id'] for r in payload['remove-copies']['payload']},{'b'*32,'d'*32})
        self.assertFalse(kwargs['follow_redirects'])

    @patch('shopware.services.CustomerService')
    def test_timeout_never_resends_or_leaks_the_remote_exception(self, shop):
        post=shop.return_value.client.session.post
        post.side_effect=RuntimeError('secret-token')
        with self.assertRaisesRegex(ValueError,'unklar') as error:self.service.execute_remote(self.spec)
        self.assertNotIn('secret-token',str(error.exception));post.assert_called_once()

    @patch('shopware.services.CustomerService')
    def test_explicit_rejection_and_unknown_server_failure_are_distinguished(self, shop):
        for status,exception in [(403,AddressConsolidationRejected),(503,ValueError)]:
            shop.return_value.client.session.post.return_value=SimpleNamespace(status_code=status)
            with self.assertRaises(exception):self.service.execute_remote(self.spec)
        self.assertEqual(shop.return_value.client.session.post.call_count,2)

    def test_readback_requires_survivor_defaults_and_unchanged_order_addresses(self):
        self.snap['records'].append({'ref':'sw:order:one','system':'sw','kind':'order','number':'12196','parent':'sw:customer:'+'a'*32,
            'fields':{'id':'one','billingAddress':{'street':'Historische Straße'}}})
        after=consolidated_snapshot(self.snap,self.spec)
        self.service.verify_shopware(self.spec,self.snap,after)
        for kind in ['defaults','survivor','history','not_deleted']:
            bad=copy.deepcopy(after)
            if kind=='defaults':next(r for r in bad['records'] if r['kind']=='customer')['fields']['defaultShippingAddressId']='d'*32
            if kind=='survivor':next(r for r in bad['records'] if r['ref']=='sw:address:'+'c'*32)['fields']['street']='Changed'
            if kind=='history':next(r for r in bad['records'] if r['kind']=='order')['fields']['billingAddress']['street']='Changed'
            if kind=='not_deleted':bad['records'].append(self.spec['sw_sources'][0])
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.service.verify_shopware(self.spec,self.snap,bad)

    @patch('customer.services.address_consolidation.transaction.atomic')
    @patch('orders.models.Order.objects')
    @patch('customer.services.address_consolidation.Customer.objects')
    @patch('customer.services.address_consolidation.Address.objects')
    def test_local_references_move_before_deletion_and_roles_and_mapping_commit_together(self, addresses, customers, orders, atomic):
        events=[]
        atomic.return_value.__enter__.side_effect=lambda:events.append('begin')
        atomic.return_value.__exit__.side_effect=lambda *args:events.append('commit')
        target=Address(**self.spec['target']['fields']);target.save=MagicMock(side_effect=lambda:events.append('save'))
        addresses.get.return_value=target;addresses.filter.return_value.exists.return_value=True
        addresses.filter.return_value.delete.side_effect=lambda:events.append('delete')
        orders.filter.return_value.update.side_effect=lambda **kwargs:events.append(next(iter(kwargs)))
        with patch.object(self.service,'preflight_local'):
            self.service.finish_local(self.spec,lambda obj:events.append('audit'))
        self.assertEqual(events,['begin','billing_address_id','shipping_address_id','audit','delete','save','commit'])
        self.assertTrue(target.is_invoice and target.is_shipping)

    @patch('customer.services.merge_ai.CustomerMergeAIService.enqueue')
    def test_confirmation_token_binds_the_group_and_followup_search_numbers(self, enqueue):
        value=state();value.update(snapshot=self.snap,status='ready',proposals=[self.proposal],approval_tokens=['token'])
        self.ai.save(value)
        with self.assertRaisesRegex(ValueError,'Bestätigung'):self.ai.phase(owner=5,run_id=value['id'],index=0,execute=True,token='wrong')
        enqueue.assert_not_called()
        result=self.ai.phase(owner=5,run_id=value['id'],index=0,execute=True,token='token')
        self.assertEqual(result['workflow'],'address_consolidation')
        self.assertEqual(result['post_merge_numbers'],['12196'])

    @patch('customer.services.merge_ai.CustomerMergeAIService')
    def test_api_requires_address_delete_permission_before_queueing(self, service):
        service.return_value.get.return_value={**state(), 'snapshot':self.snap,'proposals':[self.proposal]}
        request=RequestFactory().post('/ai/',json.dumps({'action':'execute','run_id':'c'*32,'index':0}),content_type='application/json')
        request.user=MagicMock(pk=5);request.user.has_perm.return_value=True
        request.user.has_perms.side_effect=lambda perms:'customer.delete_address' not in perms
        self.assertEqual(customer_merge_ai_api(request).status_code,403)
        service.return_value.phase.assert_not_called()

    @patch('django.contrib.auth.get_user_model')
    @patch('customer.services.merge_ai.CustomerMergeAIService.finish_address_consolidation')
    @patch('customer.services.merge_ai.CustomerMergeAIService.snapshot')
    @patch('customer.services.address_consolidation.AddressConsolidationService.execute_remote')
    def test_status_recovery_verifies_readback_without_repeating_remote_writes(self, execute, read, finish, users):
        users.return_value.objects.get.return_value=MagicMock(is_active=True,is_staff=True)
        value={**state(),'snapshot':self.snap,'workflow':'address_consolidation','proposals':[self.proposal],'selected':0}
        read.return_value=consolidated_snapshot(self.snap,self.spec)
        self.ai.recover_address_result(value)
        execute.assert_not_called();finish.assert_called_once()
        read.return_value=copy.deepcopy(self.snap)
        finish.reset_mock()
        with self.assertRaises(ValueError):self.ai.recover_address_result(value)
        execute.assert_not_called();finish.assert_not_called()

    @patch('django.contrib.auth.get_user_model')
    @patch('customer.services.merge_ai.CustomerMergeAIService.read_microtech',return_value={})
    @patch('customer.services.merge_ai.CustomerMergeAIService.snapshot')
    @patch.object(AddressConsolidationService,'preflight_local')
    @patch.object(AddressConsolidationService,'execute_remote')
    @patch.object(AddressConsolidationService,'finish_local')
    def test_local_failure_after_verified_remote_commit_needs_review_and_never_retries(self, finish, execute, preflight, read, mt, users):
        users.return_value.objects.get.return_value=MagicMock(is_active=True,is_staff=True)
        value=state('execute');value.update(snapshot=self.snap,fingerprint=fingerprint(self.snap),proposals=[self.proposal],selected=0,
            completed=[],workflow='address_consolidation')
        self.ai.save(value)
        read.side_effect=[self.snap,consolidated_snapshot(self.snap,self.spec)]
        finish.side_effect=RuntimeError('Lokale Transaktion fehlgeschlagen')
        self.ai.process(value['id']);self.ai.process(value['id'])
        result=self.ai.get(value['id'])
        self.assertEqual(result['status'],'needs_review');self.assertEqual(result['completed'],[])
        execute.assert_called_once();self.assertTrue(result['writes_started'])

    @patch('django.contrib.auth.get_user_model')
    @patch('customer.services.merge_ai.CustomerMergeAIService.read_microtech',return_value={})
    @patch('customer.services.merge_ai.CustomerMergeAIService.snapshot')
    @patch.object(AddressConsolidationService,'preflight_local')
    @patch.object(AddressConsolidationService,'execute_remote',side_effect=AddressConsolidationRejected('Abgelehnt'))
    @patch.object(AddressConsolidationService,'finish_local')
    def test_rejected_remote_transaction_does_not_proceed_to_local_deletion(self, finish, execute, preflight, read, mt, users):
        users.return_value.objects.get.return_value=MagicMock(is_active=True,is_staff=True)
        value=state('execute');value.update(snapshot=self.snap,fingerprint=fingerprint(self.snap),proposals=[self.proposal],selected=0,completed=[])
        read.return_value=self.snap;self.ai.save(value);self.ai.process(value['id'])
        result=self.ai.get(value['id']);self.assertEqual(result['status'],'failed');self.assertFalse(result['writes_started'])
        finish.assert_not_called();execute.assert_called_once()

    @patch('shopware.services.CustomerService')
    def test_snapshot_captures_only_metadata_presence_and_never_sends_unknown_custom_fields(self, shop):
        shop.return_value._request_with_retry.return_value={'data':[{'id':'a'*32,'attributes':{'customerNumber':'12196'}}]}
        with patch.object(self.ai,'sw_collection',side_effect=[[{'id':'c'*32,'street':'Gartenweg 8','customFields':{'private':'never-send-this'}}],[]]):
            snap=self.ai.snapshot(['12196'],{},systems=('sw',))
        address=next(r for r in snap['records'] if r['kind']=='address')
        self.assertTrue(address['fields']['hasMergeMetadata'])
        self.assertNotIn('never-send-this',json.dumps(snap));self.assertNotIn('customFields',address['fields'])

    @patch('customer.services.address_consolidation.transaction.atomic')
    @patch('orders.models.Order.objects')
    @patch('customer.services.address_consolidation.Customer.objects')
    @patch('customer.services.address_consolidation.Address.objects')
    def test_committed_local_receipt_makes_recovery_idempotent(self, addresses, customers, orders, atomic):
        target=Address(**self.spec['target']['fields']);target.is_invoice=True;target.is_shipping=True
        target.save=MagicMock();addresses.get.return_value=target;addresses.filter.return_value.exists.return_value=False
        audit=MagicMock()
        with patch.object(self.service,'preflight_local') as preflight:
            self.service.finish_local(self.spec,audit,lambda:True)
        preflight.assert_not_called();target.save.assert_not_called();audit.assert_not_called()
        addresses.filter.return_value.delete.assert_not_called()

    def test_conflicting_shopware_and_local_roles_do_not_get_silently_resolved(self):
        for r in self.snap['records']:
            if r['system']=='dj' and r['kind']=='address':r['fields']['is_shipping']=False
        self.assertEqual(self.service.proposals(self.snap),[])
