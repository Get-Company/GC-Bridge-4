"""Explicit AdrNr consent, idempotent merges and the address-only follow-up."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.cache import caches
from django.test import SimpleTestCase, override_settings, RequestFactory

from customer.services.merge_ai import CustomerMergeAIService
from customer.test_merge_ai import CACHE, snapshot, state, plan, operation, SWC
from customer.views import customer_merge_ai_api


def multiple_snapshot(count=2):
    snap=snapshot();snap['records'][0]['fields'].update(defaultBillingAddressId='b'*32,defaultShippingAddressId='b'*32)
    for index in range(count-1):
        account=copy.deepcopy(snap['records'][0]);key=str(index+4)*32
        account.update(ref='sw:customer:'+key,number=str(950059+index));account['fields'].update(id=key,customerNumber=account['number'])
        snap['records'].append(account);snap['availability'][account['number']]={'sw':'found','dj':'not_found','mt':'not_applicable'}
    return snap


@override_settings(CACHES=CACHE)
class MergeFirstServiceTests(SimpleTestCase):
    def setUp(self):
        caches['customer_merge_ai'].clear();self.service=CustomerMergeAIService()
        self.search=state('search');self.search.update(id='e'*32,status='search_ready',snapshot=multiple_snapshot(3),numbers=['12196','950059','950060'])
        self.service.save(self.search)

    def confirm(self, **kwargs):
        return self.service.confirm_merge(owner=5,search_id=self.search['id'],source_ref='sw:customer:'+'4'*32,target_ref='sw:customer:'+SWC,**kwargs)

    @patch('customer.services.merge_ai.CustomerMergeAIService.enqueue')
    @patch('customer.services.merge_ai.CustomerMergeAIService.snapshot')
    @patch('customer.services.merge_ai.AIProviderService.structured_response')
    def test_confirmed_numbers_create_exact_merge_without_model_or_preemptive_reload(self, model, fresh, enqueue):
        result=self.confirm();queued=enqueue.call_args.args[0]
        self.assertEqual(result['workflow'],'merge_first');self.assertEqual(result['keep_number'],'12196')
        self.assertEqual(result['post_merge_numbers'],['12196','950060'])
        self.assertEqual(result['merge_selection'],{'source':'sw:customer:'+'4'*32,'target':'sw:customer:'+SWC})
        self.assertEqual(queued['phase'],'execute');self.assertIsNone(queued['jobs'])
        self.assertEqual(queued['proposals'][0]['operations'][0]['kind'],'merge_shopware')
        self.assertEqual(queued['snapshot'],self.search['snapshot']);self.assertEqual(len(queued['merge_operation_id']),32)
        model.assert_not_called();fresh.assert_not_called()

    @patch('customer.services.merge_ai.CustomerMergeAIService.enqueue')
    def test_repeated_confirmation_keeps_one_operation_id_and_never_requeues(self, enqueue):
        first=self.confirm();second=self.confirm()
        self.assertEqual(first['id'],second['id']);self.assertEqual(first['merge_operation_id'],second['merge_operation_id'])
        enqueue.assert_called_once()
        with self.assertRaisesRegex(ValueError,'andere Auswahl'):
            self.service.confirm_merge(owner=5,search_id=self.search['id'],source_ref='sw:customer:'+'5'*32,target_ref='sw:customer:'+SWC)
        enqueue.assert_called_once()

    @patch('customer.services.merge_ai.CustomerMergeAIService.enqueue')
    def test_pair_must_belong_to_owned_complete_search_and_be_distinct(self, enqueue):
        for owner,source,target in [(6,'sw:customer:'+'4'*32,'sw:customer:'+SWC),(5,'sw:customer:'+SWC,'sw:customer:'+SWC),(5,'sw:customer:invented','sw:customer:'+SWC)]:
            with self.assertRaises(ValueError):self.service.confirm_merge(owner=owner,search_id=self.search['id'],source_ref=source,target_ref=target)
        self.search['status']='loading';self.service.save(self.search)
        with self.assertRaisesRegex(ValueError,'Suche abwarten'):self.confirm()
        enqueue.assert_not_called()

    @patch('customer.services.merge_ai.CustomerMergeAIService.enqueue')
    def test_status_lookup_never_starts_or_resends_a_merge(self, enqueue):
        self.assertEqual(self.service.confirmed_merge(owner=5,search_id=self.search['id']),{'status':'not_submitted'})
        result=self.confirm();status=self.service.confirmed_merge(owner=5,search_id=self.search['id'])
        self.assertEqual(status['id'],result['id']);enqueue.assert_called_once()
        with self.assertRaises(ValueError):self.service.confirmed_merge(owner=6,search_id=self.search['id'])

    @patch('customer.services.merge_ai.CustomerMergeAIService.enqueue')
    @patch('customer.services.merge_ai.CustomerMergeAIService.provider',return_value=SimpleNamespace(pk=3,model_name='test'))
    def test_multiple_accounts_require_explicit_separate_choice_before_paid_analysis(self, provider, enqueue):
        with self.assertRaisesRegex(ValueError,'richtige und falsche AdrNr'):
            self.service.start(owner=5,numbers=self.search['numbers'],provider_id=3,search_id=self.search['id'])
        enqueue.assert_not_called()
        self.service.start(owner=5,numbers=self.search['numbers'],provider_id=3,search_id=self.search['id'],separate_accounts=True)
        queued=enqueue.call_args.args[0]
        self.assertTrue(queued['address_only']);self.assertTrue(queued['separate_accounts'])

    def test_followup_schema_and_validator_exclude_further_ai_merge_decisions(self):
        schema=self.service.response_schema(self.search['snapshot'],address_only=True)
        kinds=schema['properties']['proposals']['items']['properties']['operations']['items']['properties']['kind']['enum']
        self.assertNotIn('merge_shopware',kinds)
        proposal=plan([operation('merge_shopware','sw:customer:'+'4'*32,'sw:customer:'+SWC)])
        result=self.service.validate_result({'summary':'','proposals':[proposal]},self.search['snapshot'],address_only=True)
        self.assertTrue(result['proposals'][0]['blocked']);self.assertEqual(result['proposals'][0]['changes'],[])
        self.assertIn('merge_shopware',self.service.response_schema(self.search['snapshot'])['properties']['proposals']['items']['properties']['operations']['items']['properties']['kind']['enum'])

    @patch('customer.services.merge_ai.CustomerMergeAIService.enqueue')
    @patch('customer.services.merge_ai.CustomerMergeAIService.provider',return_value=SimpleNamespace(pk=3,model_name='test'))
    def test_revision_preserves_decision_to_keep_accounts_separate(self, provider, enqueue):
        previous=state();previous.update(status='ready',snapshot=self.search['snapshot'],numbers=self.search['numbers'],separate_accounts=True,proposals=[plan()])
        self.service.save(previous)
        self.service.start(owner=5,numbers=previous['numbers'],provider_id=3,previous_id=previous['id'],objection='Bitte die Lieferadresse prüfen.')
        self.assertTrue(enqueue.call_args.args[0]['separate_accounts'])

    @patch('customer.tasks.merge_ai_process.apply_async',side_effect=RuntimeError('Queue unavailable'))
    def test_failed_enqueue_is_recoverable_without_accidentally_resending(self, task):
        with self.assertRaisesRegex(ValueError,'Hintergrundauftrag'):self.confirm()
        result=self.service.confirmed_merge(owner=5,search_id=self.search['id'])
        self.assertEqual(result['status'],'failed')
        self.assertEqual(self.confirm()['id'],result['id']);task.assert_called_once()


class MergeFirstPermissionTests(SimpleTestCase):
    @patch('customer.services.merge_ai.CustomerMergeAIService')
    def test_merge_endpoint_requires_delete_permission(self, service):
        request=RequestFactory().post('/admin/customer-merge-ai/api/',data=json.dumps({'action':'merge','search_id':'e'*32,'source_ref':'source','target_ref':'target'}),content_type='application/json')
        request.user=MagicMock(pk=5);request.user.has_perm.side_effect=lambda perm:perm!='customer.delete_customer'
        response=customer_merge_ai_api(request)
        self.assertEqual(response.status_code,403);service.return_value.confirm_merge.assert_not_called()
