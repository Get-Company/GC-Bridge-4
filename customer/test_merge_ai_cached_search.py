import copy
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import caches
from django.test import SimpleTestCase, override_settings

from customer.services.merge_ai import CustomerMergeAIService, fingerprint
from customer.test_merge_ai import CACHE, snapshot, plan, operation, state, SWC


@override_settings(CACHES=CACHE)
class MergeAICachedSearchTests(SimpleTestCase):
    def setUp(self):
        caches['customer_merge_ai'].clear()
        self.service = CustomerMergeAIService()

    def loaded_search(self, owner=5):
        value=state();value.update(id='e'*32,owner=owner,phase='search',status='search_ready',loaded_at='2026-10-17T10:00:00+00:00')
        self.service.save(value)
        return value

    @patch('customer.services.merge_ai.CustomerMergeAIService.provider')
    @patch('customer.services.merge_ai.CustomerMergeAIService.enqueue')
    @patch('customer.services.merge_ai.AIProviderService.structured_response')
    @patch('customer.services.merge_ai.CustomerMergeAIService.snapshot')
    @patch('customer.services.merge_ai.CustomerMergeAIService.read_microtech')
    def test_analysis_uses_only_owned_loaded_snapshot(self, mt, fresh, model, enqueue, provider):
        source=self.loaded_search();provider.return_value=SimpleNamespace(pk=3,model_name='test')
        self.service.start(owner=5,numbers=['12196'],provider_id=3,search_id=source['id'])
        queued=enqueue.call_args.args[0];self.service.save(queued)
        model.return_value=({'summary':'Zuordnen','proposals':[plan()]},{'total_tokens':42})
        self.service.process(queued['id'])
        fresh.assert_not_called();mt.assert_not_called()
        self.assertEqual(model.call_args.kwargs['context']['snapshot'],source['snapshot'])
        self.assertEqual(self.service.get(queued['id'])['status'],'ready')
        self.assertEqual(len(self.service.get(queued['id'])['approval_tokens']),1)

    @patch('customer.services.merge_ai.CustomerMergeAIService.provider')
    @patch('customer.services.merge_ai.CustomerMergeAIService.enqueue')
    def test_analyze_rejects_other_owner_or_changed_selection(self, enqueue, provider):
        source=self.loaded_search(owner=6)
        with self.assertRaises(ValueError):self.service.start(owner=5,numbers=['12196'],provider_id=3,search_id=source['id'])
        source=self.loaded_search()
        with self.assertRaises(ValueError):self.service.start(owner=5,numbers=['99999'],provider_id=3,search_id=source['id'])
        enqueue.assert_not_called()

    @patch('customer.services.merge_ai.CustomerMergeAIService.provider')
    @patch('customer.services.merge_ai.CustomerMergeAIService.enqueue')
    def test_revision_keeps_previous_snapshot_without_source_reads(self, enqueue, provider):
        previous=state();previous.update(status='ready',proposals=[plan()],search_id='e'*32)
        self.service.save(previous)
        self.service.start(owner=5,numbers=['12196'],provider_id=3,previous_id=previous['id'],objection='Lieferadresse bitte beachten.')
        queued=enqueue.call_args.args[0]
        self.assertEqual(queued['snapshot'],previous['snapshot'])
        self.assertEqual(queued['search_id'],'e'*32)
        self.assertEqual(queued['version'],2)

    @patch('microtech.models.MicrotechGraphQLJob.objects.filter')
    @patch('customer.services.merge_ai.CustomerMergeAIService.enqueue')
    def test_search_binds_the_jobs_already_started_by_resolution(self, enqueue, jobs):
        jobs.return_value=[SimpleNamespace(pk=7,request_payload={'customerNumber':'12196'},context={'source':'customer_merge_search'})]
        self.service.begin_search(owner=5,numbers=['12196'],microtech_jobs=[{'job_id':7}])
        self.assertEqual(enqueue.call_args.args[0]['jobs'],{'12196':7})
        jobs.return_value=[]
        with self.assertRaisesRegex(ValueError,'Microtech'):
            self.service.begin_search(owner=5,numbers=['12196'],microtech_jobs=[{'job_id':7}])

    @patch('customer.services.merge_ai.CustomerMergeAIService.read_microtech')
    @patch('customer.services.merge_ai.CustomerMergeAIService.snapshot')
    def test_pending_search_does_not_reload_already_loaded_sources(self, fresh, mt):
        snap=snapshot();local=copy.deepcopy(snap);remote=copy.deepcopy(snap)
        local['records']=[r for r in snap['records'] if r['system']!='mt'];local['availability']={'12196':{'sw':'found','dj':'found'}}
        remote['records']=[r for r in snap['records'] if r['system']=='mt'];remote['availability']={'12196':{'mt':'found'}}
        fresh.side_effect=[local,remote];mt.side_effect=[None,{'12196':{}}]
        search=state('search');search.pop('snapshot');search.update(jobs={'12196':7},search_progress={})
        self.service.save(search)
        self.assertTrue(self.service.process(search['id']))
        self.assertFalse(self.service.process(search['id']))
        self.assertEqual(fresh.call_count,2)
        self.assertEqual(fresh.call_args_list[0].kwargs['systems'],('sw','dj'))
        self.assertEqual(fresh.call_args_list[1].kwargs['systems'],('mt',))
        result=self.service.get(search['id']);self.assertEqual(result['status'],'search_ready')
        self.assertEqual(result['snapshot']['records'],sorted(snap['records'],key=lambda r:r['ref']))

    @patch('customer.services.merge_ai.CustomerMergeAIService.enqueue')
    @patch('customer.services.merge_ai.CustomerMergeAIService.snapshot')
    def test_cached_preview_has_no_reload_or_background_job(self, fresh, enqueue):
        value=state();value.update(status='ready',proposals=[plan()]);self.service.save(value)
        result=self.service.phase(owner=5,run_id=value['id'],index=0)
        self.assertEqual(result['status'],'preview_ready')
        self.assertEqual(result['preview_token'],result['approval_tokens'][0])
        fresh.assert_not_called();enqueue.assert_not_called()

    @patch('customer.services.merge_ai.CustomerMergeAIService.enqueue')
    def test_accept_from_ready_queues_fresh_check_only_after_confirmation(self, enqueue):
        value=state();value.update(status='ready',proposals=[plan()],approval_tokens=['accepted-token'])
        self.service.save(value)
        result=self.service.phase(owner=5,run_id=value['id'],index=0,execute=True,token='accepted-token')
        self.assertEqual(result['phase'],'execute');self.assertEqual(result['status'],'loading')
        self.assertIsNone(enqueue.call_args.args[0]['jobs'])

    @patch('django.contrib.auth.get_user_model')
    @patch('customer.services.merge_ai.CustomerMergeAIService.read_microtech',return_value={})
    @patch('customer.services.merge_ai.CustomerMergeAIService.snapshot')
    @patch('customer.services.merge_ai.CustomerMergeAIService.apply_steps')
    def test_save_checks_sources_once_before_applying(self, apply, fresh, mt, users):
        value=state('execute');value.update(selected=0,proposals=[plan()]);self.service.save(value)
        fresh.return_value=snapshot()
        self.service.process(value['id'])
        fresh.assert_called_once();mt.assert_called_once();apply.assert_called_once()
        self.assertEqual(self.service.get(value['id'])['status'],'applied')

    def merge_state(self):
        snap=snapshot();snap['records'][0]['fields'].update(defaultBillingAddressId='b'*32,defaultShippingAddressId='b'*32)
        source=copy.deepcopy(snap['records'][0]);source.update(ref='sw:customer:'+'d'*32,number='950059');source['fields']['id']='d'*32
        snap['records'].append(source)
        proposal=plan([operation('merge_shopware',source['ref'],'sw:customer:'+SWC)])
        value=state('execute');value.update(snapshot=snap,fingerprint=fingerprint(snap),selected=0,proposals=[proposal],merge_operation_id='f'*32,completed=[])
        return value

    @patch('customer.services.merge_ai.ShopwareCustomerMergeService')
    def test_changed_authoritative_merge_plan_stops_before_writes(self, service):
        value=self.merge_state();service.return_value.preview.return_value={'credentialSourceId':'wrong'}
        with self.assertRaisesRegex(ValueError,'weicht'):
            self.service.apply_merge(value)
        service.return_value.merge.assert_not_called()
        self.assertFalse(value.get('writes_started',False))

    @patch('customer.services.merge_ai.ShopwareCustomerMergeService')
    def test_merge_preserves_operation_id_and_uses_verified_plugin(self, service):
        value=self.merge_state();expected=self.service.merge_expectation(value['snapshot'],value['proposals'][0]['operations'][0])
        service.return_value.preview.return_value={**expected,'previewToken':'signed'}
        with patch.object(self.service,'finish_merge') as finish:
            self.service.apply_merge(value)
        service.return_value.merge.assert_called_once_with(operation_id='f'*32,preview_token='signed',delete_sw_id='d'*32,keep_sw_id=SWC)
        self.assertTrue(self.service.get(value['id'])['writes_started'])
        finish.assert_called_once()

    @patch('django.contrib.auth.get_user_model')
    @patch('customer.services.merge_ai.ShopwareCustomerMergeService')
    def test_unknown_merge_status_is_read_back_without_resending(self, service, users):
        value=self.merge_state();value.update(status='needs_review',merge_expected={},writes_started=True)
        service.return_value.status.return_value={'status':'not_found'}
        self.service.recover_merge_result(value)
        self.assertEqual(value['status'],'needs_review')
        service.return_value.merge.assert_not_called()
        service.return_value.status.assert_called_once_with(operation_id='f'*32)

    @patch('django.contrib.auth.get_user_model')
    @patch('customer.services.merge_ai.CustomerMergeAIService.snapshot')
    @patch('customer.services.merge_ai.CustomerMergeAIService.apply_steps')
    def test_revoked_permission_stops_before_source_reads_or_writes(self, apply, fresh, users):
        users.return_value.objects.get.return_value.has_perms.return_value=False
        value=state('execute');value.update(selected=0,proposals=[plan()]);self.service.save(value)
        self.service.process(value['id'])
        self.assertEqual(self.service.get(value['id'])['status'],'failed')
        fresh.assert_not_called();apply.assert_not_called()

    def test_local_merge_conflicts_block_plan_before_remote_writes(self):
        value=self.merge_state();snap=value['snapshot']
        local=copy.deepcopy(next(r for r in snap['records'] if r['ref']=='dj:customer:1'))
        local.update(ref='dj:customer:3',number='950059');local['fields'].update(id=3,api_id='d'*32)
        address=copy.deepcopy(next(r for r in snap['records'] if r['ref']=='dj:address:2'))
        address.update(ref='dj:address:4',number='950059',parent=local['ref']);address['fields'].update(id=4,api_id='b'*32)
        next(r for r in snap['records'] if r['ref']=='dj:address:2')['fields']['api_id']='b'*32
        snap['records'] += [local,address]
        with self.assertRaisesRegex(ValueError,'überschneiden'):
            self.service.compile_plan(value['proposals'][0],snap)
