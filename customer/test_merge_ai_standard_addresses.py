"""Regression for identical extra, billing and shipping records after a merge."""
import copy
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import caches
from django.test import SimpleTestCase, override_settings

from customer.services.merge_ai import CustomerMergeAIService, fingerprint
from customer.test_merge_ai import CACHE, SWA, SWC, operation, plan, snapshot, state


def duplicate_standard_snapshot():
    # Synthetic equivalent of the reported case; no production customer data.
    snap = snapshot()
    extra = snap['records'][3]
    extra['fields'].update(api_id=SWA, name1='Beispiel GmbH', first_name='Nina', last_name='Beispiel',
                           postal_code='12345', city='Musterstadt', is_invoice=False, is_shipping=False)
    for key, role, swid in [(3, 'is_invoice', 'c' * 32), (4, 'is_shipping', 'd' * 32)]:
        address = copy.deepcopy(extra)
        address['ref'] = f'dj:address:{key}'
        address['fields'].update(id=key, api_id=swid, **{role: True})
        shop = copy.deepcopy(snap['records'][1])
        shop.update(ref='sw:address:' + swid)
        shop['fields'].update(id=swid)
        snap['records'] += [address, shop]
    snap['records'][0]['fields'].update(defaultBillingAddressId='c' * 32, defaultShippingAddressId='d' * 32)
    for r in snap['records']:
        if r['system'] == 'sw' and r['kind'] == 'address':
            r['fields'].update(company='Beispiel GmbH', firstName='Nina', lastName='Beispiel', zipcode='12345', city='Musterstadt')
    snap['records'][5]['fields'].update(name1='Beispiel GmbH', zipCode='12345', city='Musterstadt')
    # The ERP uses a different physical address as its default. Mapping must
    # not silently resolve that conflict by rewriting any standard roles.
    snap['records'][5]['fields'].update(isDefaultBilling=False, isDefaultShipping=False)
    other = copy.deepcopy(snap['records'][5])
    other.update(ref='mt:address:12196:8')
    other['fields'].update(addressSubNumber=8, street='Marktstraße 3', isDefaultBilling=True, isDefaultShipping=True)
    snap['records'].append(other)
    return snap


def standard_plan():
    return plan([
        operation('link_microtech_address', 'mt:address:12196:7', 'dj:address:3'),
        operation('link_microtech_address', 'mt:contact:12196:7:0', 'dj:address:4'),
    ])


@override_settings(CACHES=CACHE)
class MergeAIStandardAddressTests(SimpleTestCase):
    def setUp(self):
        caches['customer_merge_ai'].clear()
        self.service = CustomerMergeAIService()
        self.snap = duplicate_standard_snapshot()

    def test_reported_extra_address_choice_is_blocked_without_any_role_change(self):
        p = plan([
            operation('link_microtech_address', 'mt:address:12196:7', 'dj:address:2'),
            operation('link_microtech_address', 'mt:contact:12196:7:0', 'dj:address:2'),
        ])
        result = self.service.validate_result({'summary': 'Zuordnen', 'proposals': [p]}, self.snap)
        self.assertIn('identische Rechnungs-/Lieferadresse', result['proposals'][0]['blocked'])
        self.assertEqual(result['proposals'][0]['changes'], [])

    def test_both_existing_roles_can_be_mapped_with_distinct_real_microtech_keys(self):
        original = copy.deepcopy(self.snap)
        changes = self.service.compile_plan(standard_plan(), self.snap)
        self.assertEqual([c['target'] for c in changes], ['dj:address:3', 'dj:address:4'])
        self.assertEqual(changes[0]['after']['erp_ans_nr'], 7)
        self.assertIsNone(changes[0]['after']['erp_asp_nr'])
        self.assertEqual(changes[1]['after']['erp_asp_nr'], 0)
        self.assertEqual(self.snap, original)
        self.assertTrue(all(c['kind'] == 'link_microtech_address' for c in changes))

    def test_priority_requires_equal_person_company_and_all_business_fields(self):
        for field, value in [('first_name', 'Andere Person'), ('company', 'Andere GmbH'),
                             ('department', 'Zweigstelle'), ('email', 'andere@example.com'),
                             ('postal_code', '54321'), ('phone', '123456')]:
            with self.subTest(field=field):
                snap = copy.deepcopy(self.snap)
                snap['records'][3]['fields'][field] = value
                self.assertEqual(self.service.standard_mapping_preferences(snap['records']), {})
                self.service.compile_plan(plan([operation('link_microtech_address', 'mt:address:12196:7', 'dj:address:2')]), snap)

    def test_existing_associations_including_zero_are_not_reallocated(self):
        for key in ('erp_ans_nr', 'erp_asp_nr', 'erp_ans_id', 'erp_asp_id', 'erp_combined_id'):
            with self.subTest(key=key):
                snap = copy.deepcopy(self.snap)
                for r in snap['records']:
                    if r['ref'] in ('dj:address:3', 'dj:address:4'):
                        r['fields'][key] = 'existing' if key == 'erp_combined_id' else 0
                self.assertEqual(self.service.standard_mapping_preferences(snap['records']), {})

    def test_incomplete_or_different_customer_addresses_are_not_equivalent(self):
        for change in ('missing_city', 'different_customer', 'missing_name'):
            snap = copy.deepcopy(self.snap)
            for r in snap['records']:
                if r['ref'] not in ('dj:address:3', 'dj:address:4'):
                    continue
                if change == 'missing_city': r['fields']['city'] = ''
                if change == 'different_customer': r['parent'] = 'dj:customer:99'
                if change == 'missing_name':
                    for k in ('name1', 'first_name', 'last_name'): r['fields'][k] = ''
            self.assertEqual(self.service.standard_mapping_preferences(snap['records']), {})

    @patch('customer.services.merge_ai.CustomerMergeAIService.enqueue')
    def test_old_review_token_does_not_bypass_the_new_selection_rule(self, enqueue):
        value = state()
        value.update(status='ready', snapshot=self.snap, approval_tokens=['token'],
                     proposals=[plan([operation('link_microtech_address', 'mt:address:12196:7', 'dj:address:2')])])
        self.service.save(value)
        with self.assertRaisesRegex(ValueError, 'Rechnungs-/Lieferadresse'):
            self.service.phase(owner=5, run_id=value['id'], index=0, execute=True, token='token')
        enqueue.assert_not_called()

    @patch('customer.services.merge_ai.CustomerMergeAIService.provider', return_value=SimpleNamespace())
    @patch('customer.services.merge_ai.AIProviderService.structured_response')
    @patch('customer.services.merge_ai.CustomerMergeAIService.snapshot')
    @patch('customer.services.merge_ai.CustomerMergeAIService.read_microtech')
    def test_model_receives_standard_candidates_from_the_existing_snapshot(self, mt, fresh, model, provider):
        value = state()
        value.update(snapshot=self.snap, fingerprint=fingerprint(self.snap))
        self.service.save(value)
        model.return_value = ({'summary': 'Zuordnen', 'proposals': [standard_plan()]}, {})
        self.service.process(value['id'])
        context = model.call_args.kwargs['context']
        self.assertEqual(context['standard_mapping_preferences'], {'dj:address:2': ['dj:address:3', 'dj:address:4']})
        self.assertEqual(context['snapshot'], self.snap)
        self.assertEqual(self.service.get(value['id'])['status'], 'ready')
        self.assertFalse(self.service.get(value['id'])['proposals'][0]['blocked'])
        fresh.assert_not_called()
        mt.assert_not_called()
