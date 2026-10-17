import copy
import json
import urllib.error
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.cache import caches
from django.test import SimpleTestCase, RequestFactory, override_settings

from ai.services.provider import AIProviderService
from customer.services.merge_ai import CustomerMergeAIService, SCHEMA, fingerprint
from customer.views import customer_merge_ai_api

CACHE = {
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
    'customer_merge_ai': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'merge-ai-tests'},
}
SWC = 'a' * 32
SWA = 'b' * 32


def snapshot():
    def record(system, kind, key, fields, parent=''):
        return {'ref': f'{system}:{kind}:{key}', 'system': system, 'kind': kind,
                'number': '12196', 'parent': parent, 'fields': fields}
    return {'availability': {'12196': {'sw': 'found', 'dj': 'found', 'mt': 'found'}}, 'records': [
        record('sw', 'customer', SWC, {'id': SWC, 'email': 'nina@example.com', 'customerNumber': '12196'}),
        record('sw', 'address', SWA, {'id': SWA, 'street': 'Gartenweg 8', 'city': 'Musterstadt'}, f'sw:customer:{SWC}'),
        record('dj', 'customer', '1', {'id': 1, 'erp_nr': '12196', 'api_id': SWC}),
        record('dj', 'address', '2', {'id': 2, 'customer_id': 1, 'api_id': '', 'erp_ans_nr': None, 'erp_asp_nr': None,
                                   'street': 'Gartenweg 8'}, 'dj:customer:1'),
        record('mt', 'customer', '12196', {'customerNumber': '12196'}),
        record('mt', 'address', '12196:7', {'addressSubNumber': 7, 'street': 'Gartenweg 8'}, 'mt:customer:12196'),
        record('mt', 'contact', '12196:7:0', {'addressSubNumber': 7, 'contactNumber': 0}, 'mt:address:12196:7'),
    ]}


def operation(kind, source, target):
    return {'kind': kind, 'source': source, 'target': target, 'reason': 'Belegt durch die vorhandenen Angaben.'}


def plan(operations=None):
    return {'title': 'Anschriften zuordnen', 'reason': 'Die Anschriften stimmen überein.', 'certainty': 'clear',
            'evidence': [{'ref': f'sw:address:{SWA}', 'field': 'street', 'finding': 'Gartenweg 8 ist in allen Systemen vorhanden.'}],
            'questions': [], 'operations': operations if operations is not None else [
                operation('link_shopware_address', f'sw:address:{SWA}', 'dj:address:2'),
                operation('link_microtech_address', 'mt:address:12196:7', 'dj:address:2'),
                operation('set_shipping', 'dj:address:2', 'dj:customer:1'),
            ]}


def state(phase='analyze'):
    snap = snapshot()
    return {'id': 'c' * 32, 'owner': 5, 'numbers': ['12196'], 'provider_id': 3, 'model': 'gpt-5-mini',
            'version': 1, 'phase': phase, 'status': 'loading', 'started': __import__('time').time(),
            'jobs': {}, 'snapshot': snap, 'fingerprint': fingerprint(snap), 'objection': '', 'previous': None}


@override_settings(CACHES=CACHE)
class MergeAIPlanTests(SimpleTestCase):
    def setUp(self):
        caches['customer_merge_ai'].clear()
        self.service = CustomerMergeAIService()

    def test_abstention_can_have_no_evidence_when_no_data_supports_a_decision(self):
        proposal = plan([])
        proposal.update(certainty='uncertain', evidence=[], questions=['Welche Person gehört zum Konto?'])
        result = self.service.validate_result({'summary': 'Rückfrage nötig', 'proposals': [proposal]}, snapshot())
        self.assertEqual(result['proposals'][0]['changes'], [])

    def test_writes_without_evidence_are_rejected(self):
        proposal = plan()
        proposal['evidence'] = []
        with self.assertRaisesRegex(ValueError, 'Belege'):
            self.service.validate_result({'summary': 'Zuordnung', 'proposals': [proposal]}, snapshot())

    def test_projected_mapping_allows_role_only_after_both_links(self):
        snap = snapshot()
        original = copy.deepcopy(snap)
        changes = self.service.compile_plan(plan(), snap)
        self.assertEqual(changes[2]['after']['SW6'], SWA)
        self.assertEqual(changes[2]['after']['Microtech AnsNr'], 7)
        self.assertEqual(snap, original)

    def test_default_without_complete_mapping_is_blocked(self):
        result = self.service.validate_result({'summary': 'Prüfen', 'proposals': [plan([plan()['operations'][-1]])]}, snapshot())
        self.assertIn('vollständige', result['proposals'][0]['blocked'])
        self.assertEqual(result['proposals'][0]['changes'], [])

    def test_contact_zero_is_valid_and_not_confused_with_no_contact(self):
        p = plan([operation('link_microtech_address', 'mt:contact:12196:7:0', 'dj:address:2')])
        change = self.service.compile_plan(p, snapshot())[0]
        self.assertEqual(change['after']['erp_asp_nr'], 0)

    def test_unknown_reference_cannot_be_applied(self):
        p = plan([operation('link_customer', 'sw:customer:invented', 'dj:customer:1')])
        result = self.service.validate_result({'summary': 'Prüfen', 'proposals': [p]}, snapshot())
        self.assertTrue(result['proposals'][0]['blocked'])

    def test_unsupported_write_is_blocked(self):
        p = plan([operation('delete_customer', f'sw:customer:{SWC}', 'dj:customer:1')])
        with self.assertRaises(ValueError): self.service.compile_plan(p, snapshot())

    def test_cross_customer_address_mapping_is_blocked(self):
        snap = snapshot()
        snap['records'][1]['number'] = '54321'
        with self.assertRaisesRegex(ValueError, 'verschiedenen Kundennummern'):
            self.service.compile_plan(plan(), snap)

    def test_invented_evidence_field_rejects_entire_response(self):
        p = plan(); p['evidence'][0]['field'] = 'password'
        with self.assertRaisesRegex(ValueError, 'Beleg'):
            self.service.validate_result({'summary': 'Prüfen', 'proposals': [p]}, snapshot())

    def test_questions_and_writes_are_not_accepted_together(self):
        p = plan(); p['questions'] = ['Ist das dieselbe Person?']
        with self.assertRaisesRegex(ValueError, 'ungeklärter'):
            self.service.validate_result({'summary': 'Prüfen', 'proposals': [p]}, snapshot())

    def test_uncertain_result_can_abstain(self):
        p = plan([]); p['certainty'] = 'uncertain'; p['questions'] = ['Ist die Identität bestätigt?']
        result = self.service.validate_result({'summary': 'Klärung nötig', 'proposals': [p]}, snapshot())
        self.assertEqual(result['proposals'][0]['operations'], [])

    def test_duplicate_role_assignment_is_blocked(self):
        p = plan(); p['operations'].append(p['operations'][-1].copy())
        with self.assertRaisesRegex(ValueError, 'doppelte'):
            self.service.compile_plan(p, snapshot())

    def test_address_mapping_cannot_collide_with_another_local_address(self):
        snap = snapshot(); other = copy.deepcopy(snap['records'][3]); other.update(ref='dj:address:99')
        other['fields'].update(id=99, api_id=SWA)
        snap['records'].append(other)
        with self.assertRaisesRegex(ValueError, 'bereits'):
            self.service.compile_plan(plan(), snap)

    def test_merge_must_be_a_single_distinct_customer_operation(self):
        snap = snapshot()
        extra = copy.deepcopy(snap['records'][0]); extra.update(ref='sw:customer:' + 'd'*32, number='950059')
        extra['fields']['id'] = 'd'*32; snap['records'].append(extra)
        merge = operation('merge_shopware', extra['ref'], snap['records'][0]['ref'])
        self.assertEqual(self.service.compile_plan(plan([merge]), snap)[0]['kind'], 'merge_shopware')
        with self.assertRaisesRegex(ValueError, 'einzigen Schritt'):
            self.service.compile_plan(plan([merge, plan()['operations'][0]]), snap)

    def test_import_and_export_are_standalone(self):
        p = plan([operation('import_shopware_address', f'sw:address:{SWA}', f'sw:customer:{SWC}')])
        self.assertEqual(len(self.service.compile_plan(p, snapshot())), 1)
        p['operations'].append(plan()['operations'][0])
        with self.assertRaisesRegex(ValueError, 'einzelner Schritt'):
            self.service.compile_plan(p, snapshot())

    def test_run_belongs_to_requesting_user(self):
        s = state(); self.service.save(s)
        self.assertEqual(self.service.get(s['id'], 5)['owner'], 5)
        with self.assertRaises(ValueError): self.service.get(s['id'], 6)

    def test_public_state_does_not_expose_internal_state(self):
        s = state(); s['api_key'] = 'secret'; s['previous'] = {'private': True}
        result = self.service.public(s)
        for key in ['owner', 'api_key', 'previous', 'jobs']:
            self.assertNotIn(key, result)

    @patch('customer.services.merge_ai.CustomerMergeAIService.enqueue')
    @patch('customer.services.merge_ai.CustomerMergeAIService.provider')
    def test_double_click_cannot_start_two_paid_analyses(self, provider, enqueue):
        provider.return_value = SimpleNamespace(pk=3, model_name='gpt-5-mini')
        search = state(); search.update(id='e'*32, phase='search', status='search_ready')
        self.service.save(search)
        self.service.start(owner=5, numbers=['12196'], provider_id=3, search_id=search['id'])
        with self.assertRaisesRegex(ValueError, 'bereits'):
            self.service.start(owner=5, numbers=['12196'], provider_id=3, search_id=search['id'])
        enqueue.assert_called_once()

    @patch('customer.services.merge_ai.CustomerMergeAIService.enqueue')
    def test_execution_requires_the_exact_review_token_and_selected_plan(self, enqueue):
        s = state(); s.update(status='preview_ready', proposals=[plan()], selected=0, preview_token='token', preview_at=__import__('time').time())
        self.service.save(s)
        with self.assertRaisesRegex(ValueError, 'Bestätigung'):
            self.service.phase(owner=5, run_id=s['id'], index=0, execute=True, token='wrong')
        enqueue.assert_not_called()

    @patch('django.contrib.auth.get_user_model')
    @patch('customer.services.merge_ai.AIProviderService.structured_response')
    @patch('customer.services.merge_ai.CustomerMergeAIService.snapshot')
    def test_changed_data_is_checked_only_when_accepted(self, snap, response, users):
        s = state('execute'); s.update(proposals=[plan()], selected=0)
        self.service.save(s)
        changed = snapshot(); changed['records'][1]['fields']['street'] = 'Andere Straße'
        snap.return_value = changed
        with patch.object(self.service, 'apply_steps') as apply:
            self.assertFalse(self.service.process(s['id']))
        apply.assert_not_called(); response.assert_not_called()
        self.assertEqual(self.service.get(s['id'])['status'], 'failed')

    @patch('customer.services.merge_ai.AIProviderService.structured_response')
    @patch('customer.services.merge_ai.CustomerMergeAIService.snapshot')
    def test_preview_has_no_paid_model_call(self, snap, response):
        s = state('preview'); s.update(proposals=[plan()], selected=0)
        self.service.save(s); snap.return_value = snapshot()
        self.assertFalse(self.service.process(s['id']))
        response.assert_not_called(); snap.assert_not_called()
        self.assertEqual(self.service.get(s['id'])['status'], 'preview_ready')
        self.assertTrue(self.service.get(s['id'])['preview_token'])

    @patch('customer.services.merge_ai.CustomerMergeAIService.snapshot')
    @patch('customer.services.merge_ai.CustomerMergeAIService.apply')
    def test_partial_failure_is_reported_and_is_never_retried(self, apply, snap):
        s = state('execute'); s.update(proposals=[plan()], selected=0)
        self.service.save(s); snap.return_value = snapshot()
        def interrupted(state, microtech):
            state['writes_started'] = True
            raise RuntimeError('Verbindung unterbrochen')
        apply.side_effect = interrupted
        self.service.process(s['id']); self.service.process(s['id'])
        self.assertEqual(apply.call_count, 1)
        self.assertEqual(self.service.get(s['id'])['status'], 'needs_review')

    @patch('customer.services.merge_ai.CustomerMergeAIService.provider')
    @patch('customer.services.merge_ai.AIProviderService.structured_response')
    @patch('customer.services.merge_ai.CustomerMergeAIService.snapshot')
    def test_completed_analysis_validates_before_releasing_plans(self, snap, response, provider):
        s=state(); self.service.save(s); snap.return_value=snapshot()
        response.return_value=({'summary':'Drei Adressen zuordnen', 'proposals':[plan()]}, {'total_tokens':100})
        self.service.process(s['id'])
        result=self.service.get(s['id'])
        self.assertEqual(result['status'],'ready')
        self.assertEqual(len(result['proposals'][0]['changes']),3)
        self.assertEqual(result['usage']['total_tokens'],100)
        snap.assert_not_called()

    def test_shopware_pagination_never_silently_truncates(self):
        sw=MagicMock()
        sw._request_with_retry.side_effect=[{'data':[{'id':str(n)} for n in range(100)],'total':101}, {'data':[{'id':'100'}],'total':101}]
        rows=self.service.sw_collection(sw,'/search/customer-address','customerId',SWC,'customer_address',('id',))
        self.assertEqual(len(rows),101)
        self.assertEqual(sw._request_with_retry.call_args.kwargs['payload']['page'],2)

    def test_incomplete_shopware_pagination_fails(self):
        sw=MagicMock(); sw._request_with_retry.return_value={'data':[],'total':1}
        with self.assertRaisesRegex(ValueError,'unvollständig'):
            self.service.sw_collection(sw,'/search/customer-address','customerId',SWC,'customer_address',('id',))


class MergeAIProviderTests(SimpleTestCase):
    def setUp(self):
        self.provider=SimpleNamespace(base_url='https://api.openai.com/v1',api_key='test-secret',is_active=True,model_name='gpt-5-mini',timeout_seconds=60)

    @patch('ai.services.provider.urllib.request.urlopen')
    def test_response_uses_schema_no_storage_and_no_temperature(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value=json.dumps({'status':'completed','output':[{'content':[{'type':'output_text','text':'{"summary":"OK","proposals":[]}'}]}],'usage':{'total_tokens':10}}).encode()
        result,usage=AIProviderService().structured_response(provider=self.provider,instructions='Rules',context={'records':[]},schema=SCHEMA)
        body=json.loads(urlopen.call_args.args[0].data)
        self.assertFalse(body['store']); self.assertNotIn('temperature',body); self.assertNotIn('tools',body)
        self.assertTrue(body['text']['format']['strict'])
        self.assertEqual(result['summary'],'OK'); self.assertEqual(usage['total_tokens'],10)

    @patch('ai.services.provider.urllib.request.urlopen')
    def test_missing_key_does_not_make_a_request(self, urlopen):
        self.provider.api_key=''
        with self.assertRaises(ValueError): AIProviderService().structured_response(provider=self.provider,instructions='',context={},schema=SCHEMA)
        urlopen.assert_not_called()

    @patch('ai.services.provider.urllib.request.urlopen')
    def test_other_endpoint_cannot_receive_customer_data_or_key(self, urlopen):
        self.provider.base_url='https://example.org/v1'
        with self.assertRaises(ValueError): AIProviderService().structured_response(provider=self.provider,instructions='',context={},schema=SCHEMA)
        urlopen.assert_not_called()

    @patch('ai.services.provider.urllib.request.urlopen')
    def test_upstream_error_never_exposes_body_and_is_not_retried(self, urlopen):
        from io import BytesIO
        urlopen.side_effect=urllib.error.HTTPError('https://api.openai.com',401,'Unauthorized',{},BytesIO(b'test-secret private response'))
        with self.assertRaisesRegex(RuntimeError,'API-Schlüssel') as error:
            AIProviderService().structured_response(provider=self.provider,instructions='',context={},schema=SCHEMA)
        self.assertNotIn('test-secret',str(error.exception)); self.assertEqual(urlopen.call_count,1)

    @patch('ai.services.provider.urllib.request.urlopen')
    def test_incomplete_response_cannot_become_a_plan(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value=b'{"status":"incomplete","output":[]}'
        with self.assertRaisesRegex(RuntimeError,'unvollständig'):
            AIProviderService().structured_response(provider=self.provider,instructions='',context={},schema=SCHEMA)


class MergeAIViewTests(SimpleTestCase):
    def request(self, body=None, permissions=True):
        r=RequestFactory().post('/admin/customer-merge-ai/api/',data=json.dumps(body or {}),content_type='application/json')
        r.user=MagicMock(pk=5); r.user.has_perm.return_value=permissions; r.user.has_perms.return_value=permissions
        return r

    @patch('customer.services.merge_ai.CustomerMergeAIService')
    def test_forbidden_user_cannot_start_a_job(self, service):
        response=customer_merge_ai_api(self.request({'action':'analyze'},False))
        self.assertEqual(response.status_code,403); service.assert_not_called()

    @patch('customer.services.merge_ai.CustomerMergeAIService')
    def test_browser_cannot_submit_a_plan_to_execute(self, service):
        service.return_value.get.return_value={'id':'c'*32,'proposals':[plan()]}
        service.return_value.phase.return_value={'status':'loading'}
        r=self.request({'action':'execute','run_id':'c'*32,'index':0,'preview_token':'token','operations':[{'kind':'delete_customer'}]})
        response=customer_merge_ai_api(r)
        self.assertEqual(response.status_code,202)
        self.assertNotIn('operations',service.return_value.phase.call_args.kwargs)

    @patch('customer.services.merge_ai.CustomerMergeAIService')
    def test_status_requires_ownership(self, service):
        r=RequestFactory().get('/admin/customer-merge-ai/api/',{'run_id':'c'*32})
        r.user=MagicMock(pk=5); r.user.has_perm.return_value=True
        service.return_value.get.side_effect=ValueError('Nicht gefunden')
        response=customer_merge_ai_api(r)
        self.assertEqual(response.status_code,400)
        service.return_value.get.assert_called_once_with('c'*32,5)


class MergeAIEvidenceSchemaTests(SimpleTestCase):
    def test_schema_accepts_exact_evidence_but_rejects_aliases_and_wrong_records(self):
        from jsonschema import Draft202012Validator
        snap = snapshot()
        schema = CustomerMergeAIService.response_schema(snap)
        validator = Draft202012Validator(schema)
        good = {'summary': 'Zuordnen', 'proposals': [plan()]}
        self.assertEqual(list(validator.iter_errors(good)), [])
        for ref, field in [
            (f'sw:address:{SWA}', 'fields.street'),
            (f'sw:address:{SWA}', 'Straße'),
            ('dj:customer:1', 'street'),
            ('dj:address:2', 'firstName'),
            ('sw:address:invented', 'street'),
        ]:
            bad = copy.deepcopy(good)
            bad['proposals'][0]['evidence'][0].update(ref=ref, field=field)
            self.assertTrue(list(validator.iter_errors(bad)), (ref, field))
        self.assertEqual(SCHEMA['properties']['proposals']['items']['properties']['evidence']['items']['properties']['field'], {'type': 'string'})

    def test_large_snapshot_stays_within_enum_limits_and_matches_exact_refs(self):
        from jsonschema import Draft202012Validator
        snap = {'records': [dict(ref=f'sw:order:{i:032x}', fields={'id': f'{i:032x}', 'orderNumber': str(i)}) for i in range(1000)]}
        schema = CustomerMergeAIService.response_schema(snap)
        branches = schema['properties']['proposals']['items']['properties']['evidence']['items']['anyOf']
        self.assertEqual(len(branches), 1)
        self.assertIn('pattern', branches[0]['properties']['ref'])
        evidence_validator = Draft202012Validator({'anyOf': branches})
        self.assertEqual(list(evidence_validator.iter_errors({'ref': snap['records'][-1]['ref'], 'field': 'orderNumber', 'finding': 'Bestellung vorhanden'})), [])
        self.assertTrue(list(evidence_validator.iter_errors({'ref': 'sw:order:invented', 'field': 'orderNumber', 'finding': 'Falsch'})))

    def test_records_with_same_fields_share_one_schema_branch(self):
        snap = snapshot()
        extra = copy.deepcopy(snap['records'][1]);extra['ref'] = 'sw:address:' + 'f'*32
        snap['records'].append(extra)
        branches = CustomerMergeAIService.response_schema(snap)['properties']['proposals']['items']['properties']['evidence']['items']['anyOf']
        group = next(b for b in branches if f'sw:address:{SWA}' in b['properties']['ref'].get('enum', []))
        self.assertIn(extra['ref'], group['properties']['ref']['enum'])
