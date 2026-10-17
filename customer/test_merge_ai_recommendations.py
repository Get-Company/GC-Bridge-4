"""Existing address mappings, shared exact copies, and SW6-owned roles."""
import copy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.cache import caches
from django.test import SimpleTestCase, override_settings

from customer.services.address_recommendations import AddressRecommendationService, BUSINESS_FIELDS
from customer.services.customer_merge import CustomerIdUpdateService, CustomerSyncDirectionService
from customer.services.merge_ai import CustomerMergeAIService, MAPPING_KINDS, fingerprint
from customer.test_merge_ai import CACHE, SWA, operation, plan, state
from customer.test_merge_ai_standard_addresses import duplicate_standard_snapshot


def recommendation_snapshot():
    snap = duplicate_standard_snapshot()
    for record in snap['records']:
        if record['system']=='dj' and record['kind']=='address':record['fields']['company']='Beispiel GmbH'
    contact = next(r for r in snap['records'] if r['kind'] == 'contact')
    contact['fields'].update(firstName='Nina', lastName='Beispiel')
    return snap


@override_settings(CACHES=CACHE)
class AddressRecommendationTests(SimpleTestCase):
    def setUp(self):
        caches['customer_merge_ai'].clear()
        self.service = CustomerMergeAIService()
        self.snap = recommendation_snapshot()

    def test_reported_conflict_maps_both_standards_to_same_real_contact_and_aligns_erp(self):
        original = copy.deepcopy(self.snap)
        p = AddressRecommendationService.proposals(self.snap)[0]
        validated = self.service.validate_result({'summary':'','proposals':[p]}, self.snap, mapping_only=True)['proposals'][0]
        self.assertEqual(validated['blocked'], '')
        changes = validated['changes']
        links = [c for c in changes if c['kind']=='link_microtech_address']
        self.assertEqual({c['target'] for c in links}, {'dj:address:3','dj:address:4'})
        self.assertTrue(all(c['after']['erp_ans_nr']==7 and c['after']['erp_asp_nr']==0 for c in links))
        self.assertEqual({c['kind'] for c in changes if c['kind'].startswith('set_')}, {'set_billing','set_shipping'})
        self.assertTrue(all(op['kind'] in MAPPING_KINDS for op in p['operations']))
        self.assertEqual(self.snap, original)

    def test_incompatible_contact_or_multiple_matches_is_not_guessed(self):
        for mode in ('person','multiple'):
            snap = copy.deepcopy(self.snap)
            if mode=='person':
                snap['records'][6]['fields']['lastName']='Anders'
            else:
                duplicate=copy.deepcopy(snap['records'][5]);duplicate['ref']='mt:address:12196:9';duplicate['fields']['addressSubNumber']=9;snap['records'].append(duplicate)
            self.assertEqual(AddressRecommendationService.proposals(snap), [])

    def test_shared_mapping_requires_all_business_fields_to_be_identical(self):
        p=plan([operation('link_microtech_address','mt:contact:12196:7:0','dj:address:3'),operation('link_microtech_address','mt:contact:12196:7:0','dj:address:4')])
        for field in ('department','phone','email','last_name','country_code'):
            snap=copy.deepcopy(self.snap)
            next(r for r in snap['records'] if r['ref']=='dj:address:4')['fields'][field]='Anders'
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'anderen Datensatz'):
                self.service.compile_plan(p,snap,mapping_only=True)

    def test_role_change_cannot_replace_customer_selected_shopware_standard(self):
        p=plan([operation('link_microtech_address','mt:address:12196:7','dj:address:3'),operation('set_shipping','dj:address:3','dj:customer:1')])
        with self.assertRaisesRegex(ValueError,'Shopware hat Vorrang'):
            self.service.compile_plan(p,self.snap,mapping_only=True)

    def test_mapping_mode_excludes_copies_consolidation_and_customer_merges(self):
        schema=self.service.response_schema(self.snap,mapping_only=True)
        kinds=schema['properties']['proposals']['items']['properties']['operations']['items']['properties']['kind']['enum']
        self.assertEqual(set(kinds),set(MAPPING_KINDS))
        self.assertEqual(schema['properties']['proposals']['maxItems'],1)
        for kind in ('import_shopware_address','export_django_address','consolidate_addresses','merge_shopware'):
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'nur Zuordnungen'):
                self.service.compile_plan(plan([operation(kind,'dj:address:3','dj:address:4')]),self.snap,mapping_only=True)

    @patch('customer.services.merge_ai.CustomerMergeAIService.provider')
    @patch('customer.services.merge_ai.AIProviderService.structured_response')
    @patch('customer.services.merge_ai.CustomerMergeAIService.snapshot')
    @patch('customer.services.merge_ai.CustomerMergeAIService.read_microtech')
    def test_analysis_uses_cached_sources_and_returns_real_confirmable_mapping(self,mt,fresh,model,provider):
        value=state();value.update(mapping_only=True,snapshot=self.snap,fingerprint=fingerprint(self.snap))
        self.service.save(value);model.return_value=({'summary':'','proposals':[plan([])]},{})
        self.service.process(value['id']);result=self.service.get(value['id'])
        self.assertEqual(result['status'],'ready');self.assertEqual(result['proposals'][0]['blocked'],'')
        self.assertTrue(result['proposals'][0]['operations']);self.assertTrue(result['approval_tokens'])
        self.assertEqual(len(result['proposals']),1)
        self.assertEqual(len(result['approval_tokens']),1)
        self.assertTrue(self.service.public(result)['mapping_only'])
        fresh.assert_not_called();mt.assert_not_called()
        self.assertIn('SW6 ist maßgeblich',model.call_args.kwargs['instructions'])

    @patch('microtech.services.microtech_connection')
    @patch('customer.services.customer_merge.transaction.atomic')
    @patch('customer.services.customer_merge.Address')
    @patch('customer.services.customer_merge.Customer')
    @patch('shopware.services.CustomerService')
    def test_alignment_preserves_shopware_and_its_distinct_local_role(self,sw,customers,addresses,atomic,mt):
        customer=MagicMock(pk=1,erp_nr='12196',api_id='a'*32)
        address=SimpleNamespace(pk=3,customer=customer,api_id='c'*32,erp_ans_nr=0)
        addresses.objects.select_related.return_value.filter.return_value.first.return_value=address
        customers.objects.select_for_update.return_value.filter.return_value.first.return_value=customer
        sw.return_value.get_by_customer_number.return_value={'data':[{'id':'a'*32,'defaultBillingAddressId':'c'*32,'addresses':[{'id':'c'*32}]}]}
        CustomerSyncDirectionService().set_address_default(erp_nr='12196',django_address_id=3,role='billing',follow_shopware=True)
        sw.return_value.update_customer.assert_not_called()
        mt.return_value.__enter__.return_value.update_customer.assert_called_once_with('12196',{'defaultBillingAddressNumber':0})
        customer.addresses.filter.assert_called_once_with(api_id__iexact='c'*32)

    @patch('microtech.services.microtech_connection')
    @patch('customer.services.customer_merge.Address')
    @patch('shopware.services.CustomerService')
    def test_changed_shopware_selection_blocks_before_any_remote_write(self,sw,addresses,mt):
        customer=SimpleNamespace(pk=1,erp_nr='12196',api_id='a'*32)
        addresses.objects.select_related.return_value.filter.return_value.first.return_value=SimpleNamespace(pk=3,customer=customer,api_id='c'*32,erp_ans_nr=0)
        sw.return_value.get_by_customer_number.return_value={'data':[{'id':'a'*32,'defaultBillingAddressId':'d'*32,'addresses':[{'id':'c'*32}]}]}
        with self.assertRaisesRegex(ValueError,'Shopware-Standardadresse wurde geändert'):
            CustomerSyncDirectionService().set_address_default(erp_nr='12196',django_address_id=3,role='billing',follow_shopware=True)
        mt.assert_not_called();sw.return_value.update_customer.assert_not_called()

    @patch('customer.services.customer_merge.Address')
    def test_shared_mapping_only_saves_exact_copies_and_clears_opaque_ids(self,model):
        f=next(r for r in self.snap['records'] if r['ref']=='dj:address:3')['fields']
        address=MagicMock(pk=3,customer=MagicMock(),erp_ans_nr=None,erp_asp_nr=None,**{k:f.get(k,'') for k in BUSINESS_FIELDS})
        other=SimpleNamespace(**{k:f.get(k,'') for k in BUSINESS_FIELDS})
        model.objects.select_related.return_value.filter.return_value.first.return_value=address
        matches=model.objects.filter.return_value.exclude.return_value.filter.return_value
        matches.first.return_value=other;matches.__iter__.return_value=iter([other])
        CustomerIdUpdateService().update_microtech_address_mapping(3,0,0,allow_identical=True)
        self.assertEqual((address.erp_ans_nr,address.erp_asp_nr),(0,0));self.assertIsNone(address.erp_combined_id)
        address.save.assert_called_once()
        address.save.reset_mock();other.last_name='Anders';matches.__iter__.return_value=iter([other])
        with self.assertRaisesRegex(ValueError,'bereits vergeben'):
            CustomerIdUpdateService().update_microtech_address_mapping(3,0,0,allow_identical=True)
        address.save.assert_not_called()

    @patch('customer.services.customer_sync.Address')
    def test_later_erp_refresh_preserves_both_shopware_rows_and_roles(self,model):
        from customer.services.customer_sync import CustomerSyncService
        address=MagicMock(pk=3,api_id='c'*32,is_invoice=True,is_shipping=False,street='Gartenweg 8')
        second=SimpleNamespace(pk=4,api_id='d'*32)
        qs=model.objects.filter.return_value
        qs.filter.return_value.first.return_value=address
        qs.filter.return_value.exclude.return_value.exclude.return_value=[address,second]
        result=CustomerSyncService()._upsert_local_address(customer=MagicMock(),ans_id=1,ans_nr=0,asp_id=2,asp_nr=0,
            defaults={'erp_ans_nr':0,'erp_asp_nr':0,'street':'Alte Straße','is_invoice':False,'is_shipping':True})
        self.assertEqual(result._shared_mapping_ids,[3,4])
        self.assertEqual(result.street,'Gartenweg 8')
        self.assertTrue(result.is_invoice);self.assertFalse(result.is_shipping)
        result.save.assert_called_once()

    def test_shopware_priority_also_applies_when_local_flags_are_stale(self):
        for record in self.snap['records']:
            if record['system']=='dj' and record['kind']=='address':
                record['fields'].update(is_invoice=record['ref']=='dj:address:2',is_shipping=False)
        preferences=self.service.standard_mapping_preferences(self.snap['records'],shopware_authoritative=True)
        self.assertEqual(preferences['dj:address:2'],['dj:address:3','dj:address:4'])
        p=AddressRecommendationService.proposals(self.snap)[0]
        self.assertEqual(self.service.validate_result({'summary':'','proposals':[p]},self.snap,mapping_only=True)['proposals'][0]['blocked'],'')

    def test_microtech_firma_in_name1_and_company_in_name2_is_a_supported_existing_address(self):
        for record in self.snap['records']:
            if record['system']=='mt' and record['kind']=='address':
                record['fields'].update(name1='Firma',name2='Beispiel GmbH')
        proposals=AddressRecommendationService.proposals(self.snap)
        self.assertTrue(proposals)
        changes=self.service.compile_plan(proposals[0],self.snap,mapping_only=True)
        self.assertEqual(len([c for c in changes if c['kind']=='link_microtech_address']),2)

    def test_wrong_existing_erp_mapping_is_corrected_before_standard_selection(self):
        for record in self.snap['records']:
            if record['ref']=='dj:address:3':record['fields'].update(erp_ans_nr=8,erp_asp_nr=None)
        proposal=AddressRecommendationService.proposals(self.snap)[0]
        changes=self.service.validate_result({'summary':'','proposals':[proposal]},self.snap,mapping_only=True)['proposals'][0]['changes']
        mapping=next(c for c in changes if c['kind']=='link_microtech_address' and c['target']=='dj:address:3')
        self.assertEqual(mapping['before']['erp_ans_nr'],8);self.assertEqual(mapping['after']['erp_ans_nr'],7)
        bad=plan([operation('set_billing','dj:address:3','dj:customer:1')])
        with self.assertRaisesRegex(ValueError,'Microtech-Anschrift entspricht nicht'):
            self.service.compile_plan(bad,self.snap,mapping_only=True)
