"""Regression: local source exists, selected surviving Shopware customer does not."""
import copy
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import caches
from django.test import SimpleTestCase, override_settings

from customer.models import Address, Customer
from customer.services.merge_ai import CustomerMergeAIService, fingerprint
from customer.test_merge_ai import CACHE, plan, operation, state, SWC
from customer.test_merge_ai_merge_first import multiple_snapshot


@override_settings(CACHES=CACHE)
class MergeMissingTargetTests(SimpleTestCase):
    def setUp(self):
        caches['customer_merge_ai'].clear();self.service=CustomerMergeAIService()
        self.snap=multiple_snapshot(2)
        self.source=next(r for r in self.snap['records'] if r['ref']=='sw:customer:'+SWC)
        self.target=next(r for r in self.snap['records'] if r['ref']=='sw:customer:'+'4'*32)
        self.source['fields'].update(lastLogin='2026-10-17T08:00:00Z',email='source@example.com')
        self.target['fields'].update(firstName='Nina',lastName='Beispiel',email='target@example.com',lastLogin='2026-09-01T08:00:00Z',
            defaultBillingAddressId='f'*32,defaultShippingAddressId='e'*32,group={'name':'Firmenkunden','displayGross':False})
        for key,street in [('f','Büroweg 1'),('e','Lagerweg 2')]:
            self.snap['records'].append({'ref':'sw:address:'+key*32,'system':'sw','kind':'address','number':self.target['number'],'parent':self.target['ref'],
                'fields':{'id':key*32,'firstName':'Nina','lastName':'Beispiel','street':street,'zipcode':'12345','city':'Musterstadt','country':{'iso':'DE'}}})
        search=state('search');search.update(id='d'*32,snapshot=self.snap,numbers=['12196','950059'],status='search_ready');self.service.save(search)
        self.value=state('execute');self.value.update(snapshot=self.snap,fingerprint=fingerprint(self.snap),numbers=search['numbers'],selected=0,completed=[],merge_operation_id='9'*32,
            proposals=[plan([operation('merge_shopware',self.source['ref'],self.target['ref'])])],workflow='merge_first')
        self.expected=self.service.merge_expectation(self.snap,self.value['proposals'][0]['operations'][0]);self.value['merge_expected']=self.expected

    @patch('customer.services.merge_ai.CustomerMergeAIService.enqueue')
    def test_local_source_without_local_target_can_be_merged_after_explicit_permission(self, enqueue):
        kwargs=dict(owner=5,search_id='d'*32,source_ref=self.source['ref'],target_ref=self.target['ref'])
        with self.assertRaisesRegex(ValueError,'Anlegeberechtigungen'):self.service.confirm_merge(**kwargs)
        enqueue.assert_not_called()
        result=self.service.confirm_merge(**kwargs,allow_create_target=True)
        self.assertEqual(result['keep_number'],'950059');self.assertEqual(result['post_merge_numbers'],['950059'])
        self.assertFalse(enqueue.call_args.args[0]['proposals'][0]['blocked'])

    def test_conflicting_source_address_is_blocked_even_when_local_target_is_absent(self):
        next(r for r in self.snap['records'] if r['ref']=='dj:address:2')['fields']['api_id']='F'*32
        with self.assertRaisesRegex(ValueError,'überschneiden'):
            self.service.compile_plan(self.value['proposals'][0],self.snap)

    @patch('customer.services.merge_ai.Customer.objects.filter')
    @patch('customer.services.merge_ai.Address.objects.filter')
    @patch('customer.services.merge_ai.ShopwareCustomerMergeService')
    def test_duplicate_target_identity_outside_search_blocks_remote_merge(self, shop, addresses, customers):
        customers.return_value.exists.return_value=True;shop.return_value.preview.return_value={**self.expected,'previewToken':'signed'}
        with self.assertRaisesRegex(ValueError,'anders zugeordnet'):
            self.service.apply_merge(self.value)
        shop.return_value.merge.assert_not_called();addresses.assert_not_called()

    @patch('customer.services.merge_ai.Customer.objects.filter')
    @patch('customer.services.merge_ai.Address.objects.filter')
    @patch('customer.services.merge_ai.ShopwareCustomerMergeService')
    def test_address_already_owned_elsewhere_blocks_remote_merge(self, shop, addresses, customers):
        customers.return_value.exists.return_value=False;addresses.return_value.exists.return_value=True
        shop.return_value.preview.return_value={**self.expected,'previewToken':'signed'}
        with self.assertRaisesRegex(ValueError,'Zieladresse'):
            self.service.apply_merge(self.value)
        shop.return_value.merge.assert_not_called()
        self.assertIn('api_id__iexact',repr(addresses.call_args))

    @patch('django.contrib.admin.models.LogEntry.objects.log_actions')
    @patch.object(Customer,'save',autospec=True)
    @patch.object(Address,'save',autospec=True)
    @patch('customer.services.merge_ai.Address.objects.filter')
    @patch('customer.services.merge_ai.Customer.objects.filter')
    @patch('customer.services.merge_ai.Customer.objects.select_for_update')
    def test_target_and_own_addresses_preserve_roles_tax_mode_and_verified_login(self, locked, customers, addresses, save_address, save_customer, audit):
        locked.return_value.filter.return_value=[];addresses.return_value.exists.return_value=False
        created=[];imported=[]
        def store_customer(obj):obj.pk=41;created.append(obj)
        def store_address(obj):obj.pk=51+len(imported);imported.append(obj)
        save_customer.side_effect=store_customer;save_address.side_effect=store_address
        original=copy.deepcopy(self.snap)
        self.service.ensure_merge_target(self.value,self.source,self.target)
        customer=created[0];self.assertEqual(customer.erp_nr,'950059');self.assertEqual(customer.api_id,'4'*32)
        self.assertEqual(customer.name,'Nina Beispiel');self.assertEqual(customer.email,'source@example.com')
        self.assertFalse(customer.is_gross);self.assertEqual(customer.shopware_customer_group,'Firmenkunden')
        self.assertEqual(len(imported),2)
        self.assertEqual([(a.is_invoice,a.is_shipping) for a in imported],[(True,False),(False,True)])
        self.assertTrue(all(a.customer is customer and a.country_code=='DE' and a.erp_ans_id is None for a in imported))
        self.assertEqual(self.snap,original);audit.assert_called_once()
        # A status retry must never create the target or its addresses a second time.
        locked.return_value.filter.return_value=[customer]
        self.service.ensure_merge_target(self.value,self.source,self.target)
        self.assertEqual(save_customer.call_count,1);self.assertEqual(save_address.call_count,2)

    @patch('customer.services.merge_ai.Customer.objects.select_for_update')
    @patch.object(Customer,'save',autospec=True)
    def test_recovery_never_overwrites_a_different_local_identity(self, save, locked):
        locked.return_value.filter.return_value=[SimpleNamespace(erp_nr='950059',api_id='wrong')]
        with self.assertRaisesRegex(ValueError,'nicht mehr eindeutig'):
            self.service.ensure_merge_target(self.value,self.source,self.target)
        save.assert_not_called()

    @patch('customer.services.merge_ai.transaction.atomic')
    @patch('customer.services.merge_ai.CustomerMergeAIService.ensure_merge_target')
    @patch('customer.services.merge_ai.CustomerMergeAIService.audit')
    @patch('customer.services.merge_ai.Customer.objects.filter')
    def test_target_creation_and_cleanup_share_one_transaction_after_verified_merge(self, customers, audit, ensure, atomic):
        events=[];atomic.return_value.__enter__.side_effect=lambda:events.append('begin')
        atomic.return_value.__exit__.side_effect=lambda *args:events.append('end')
        ensure.side_effect=lambda *args:events.append('target')
        audit.side_effect=lambda *args:events.append('audit')
        class Cleanup:
            def cleanup_django_source_after_merge(self,**kwargs):events.append('cleanup');return {'status':'deleted'}
        self.service.finish_merge(self.value,Cleanup(),{**self.expected,'status':'merged'})
        self.assertEqual(events,['begin','target','cleanup','audit','end'])
        self.assertEqual(self.value['status'],'applied')

    @patch('customer.services.merge_ai.CustomerMergeAIService.ensure_merge_target')
    @patch('customer.services.merge_ai.ShopwareCustomerMergeService')
    def test_unverified_remote_result_never_creates_or_moves_local_records(self, shop, ensure):
        with self.assertRaisesRegex(ValueError,'nicht vollständig bestätigt'):
            self.service.finish_merge(self.value,shop.return_value,{**self.expected,'status':'not_found'})
        ensure.assert_not_called();shop.return_value.cleanup_django_source_after_merge.assert_not_called()

    @patch('django.contrib.auth.get_user_model')
    @patch('customer.services.merge_ai.CustomerMergeAIService.snapshot')
    @patch('customer.services.merge_ai.CustomerMergeAIService.apply_merge')
    def test_creation_permissions_are_rechecked_before_any_write(self, apply, fresh, users):
        users.return_value.objects.get.return_value.has_perms.return_value=False
        with self.assertRaisesRegex(ValueError,'Berechtigung'):self.service.apply(self.value,{})
        required=users.return_value.objects.get.return_value.has_perms.call_args.args[0]
        self.assertTrue({'customer.add_customer','customer.add_address'}<=required)
        fresh.assert_not_called();apply.assert_not_called()

    @patch('shopware.services.CustomerService')
    @patch('customer.services.merge_ai.CustomerMergeAIService.sw_collection',return_value=[])
    def test_customer_group_is_loaded_once_with_only_business_fields(self, collection, shop):
        shop.return_value._request_with_retry.return_value={'data':[{'id':'4'*32,'customerNumber':'950059','group':{'id':'group','name':'Firmenkunden','displayGross':False,'secret':'not-for-prompt'}}]}
        result=self.service.snapshot(['950059'],{},systems=('sw',))
        group=result['records'][0]['fields']['group']
        self.assertEqual(group,{'id':'group','name':'Firmenkunden','displayGross':False})
        payload=shop.return_value._request_with_retry.call_args.kwargs['payload']
        self.assertEqual(payload['associations'],{'group':{}})
        self.assertEqual(payload['includes']['customer_group'],['id','name','displayGross'])
        shop.return_value._request_with_retry.assert_called_once()

    @patch('customer.services.merge_ai.transaction.atomic')
    @patch('customer.services.merge_ai.CustomerMergeAIService.ensure_merge_target')
    @patch('customer.services.merge_ai.CustomerMergeAIService.audit')
    @patch('customer.services.merge_ai.Customer.objects.filter')
    def test_failed_local_commit_never_marks_merge_cleanup_complete(self, customers, audit, ensure, atomic):
        atomic.return_value.__exit__.side_effect=RuntimeError('Commit interrupted')
        class Cleanup:
            def cleanup_django_source_after_merge(self,**kwargs):return {'status':'deleted'}
        with self.assertRaisesRegex(RuntimeError,'Commit interrupted'):
            self.service.finish_merge(self.value,Cleanup(),{**self.expected,'status':'merged'})
        self.assertEqual(self.value['completed'],[])
        self.assertNotEqual(self.value['status'],'applied')
