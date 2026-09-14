"""Behavioral tests against the account-scoped Postgres connection shim."""
import hashlib
import json
import pytest
from elevate_cli.data.connection import connect
from elevate_cli.data.deals import create_deal, get_deal, add_deal_attachment
from elevate_cli.data.dispatch import create_action
from elevate_cli import listing_triggers as lt

@pytest.fixture
def env(monkeypatch, tmp_path_factory):
    # Reuse one disposable cluster in this bounded suite, never the live account.
    if not hasattr(env, 'root'):
        env.root = tmp_path_factory.mktemp('listing-trigger-db')
    monkeypatch.setenv('ELEVATE_HOME', str(env.root))
    monkeypatch.setattr('elevate_cli.data.dispatch._request_agent_worker_wake', lambda **kw: None)
    monkeypatch.setattr('elevate_cli.data.deals._dispatch_safely', lambda *a, **kw: None)
    return env.root

@pytest.fixture
def deal(env):
    with connect() as conn:
        d = create_deal(conn, title='Trigger test', side='listing', province='bc', actor='test', dispatch_initial_stage=False)
        for stage in range(8):
            create_action(conn, name=f'{d["id"]}-{stage}', trigger='stage_entry', side='listing', to_stage=stage,
                          skill='real-estate-admin/cma', condition={'id': d['id']})
    return d

def request(source='request-1'):
    return {'sourceId': source, 'requestText': 'Prepare listing', 'userRequested': True, 'matchConfirmed': True}

def apply(deal, trigger, evidence=None, **kw):
    with connect() as conn:
        return lt.apply_listing_trigger(conn, deal['id'], trigger=trigger, evidence=evidence or request(), actor='test', **kw)

def at(deal, stage):
    with connect() as conn:
        conn.execute('UPDATE deals SET current_stage=? WHERE id=?', (stage, deal['id']))

def doc(deal, tmp_path, payload=b'signed test evidence'):
    p=tmp_path/'proof.pdf'; p.write_bytes(payload)
    with connect() as conn:
        a=add_deal_attachment(conn, deal['id'], kind='offer_pdf', file_path=str(p), actor='test')
    return {**request(), 'attachmentId': a['id'], 'sha256': hashlib.sha256(payload).hexdigest(),
            'fullySigned': True, 'currentContractConfirmed': True, 'contractId': 'contract-one',
            'verificationNotes': 'Test verifier inspected execution and parties', 'allConditionsRemoved': True}

@pytest.mark.parametrize('trigger,start,target', [('comps_requested',0,1), ('listing_prep_requested',0,2),
 ('platform_prep_requested',2,3), ('marketing_prep_requested',3,4), ('accepted_offer_requested',5,6),
 ('condition_removal_confirmed',6,7)])
def test_explicit_trigger_moves_and_queues(deal,trigger,start,target):
    at(deal,start)
    result=apply(deal,trigger,{**request(), 'allConditionsRemoved': True})
    assert result['deal']['currentStage']==target
    assert result['runs'] and all(r['status']=='queued' for r in result['runs'])
    again=apply(deal,trigger,{**request(), 'allConditionsRemoved': True})
    assert again['outcome']=='duplicate' and again['runs']==result['runs']

@pytest.mark.parametrize('field,value', [('userRequested',False),('userRequested','true'),('matchConfirmed',False),('sourceId','')])
def test_invalid_request_leaves_stage_unchanged(deal,field,value):
    with pytest.raises(ValueError): apply(deal,'listing_prep_requested',{**request(),field:value})
    with connect() as conn: assert get_deal(conn,deal['id'])['currentStage']==0

@pytest.mark.parametrize('trigger,start,target', [('signed_mlc_received',2,3),('signed_cps_received',5,6),('signed_removal_received',6,7)])
def test_verified_document_and_forwarded_duplicate(deal,tmp_path,trigger,start,target):
    at(deal,start); evidence=doc(deal,tmp_path)
    first=apply(deal,trigger,evidence)
    again=apply(deal,trigger,{**evidence,'sourceId':'forwarded-message'})
    assert first['deal']['currentStage']==target
    assert again['outcome']=='duplicate' and first['runs']==again['runs']

@pytest.mark.parametrize('field,value', [('fullySigned',False),('currentContractConfirmed',False),('sha256','wrong')])
def test_uncertain_or_changed_document_is_rejected(deal,tmp_path,field,value):
    at(deal,5); evidence=doc(deal,tmp_path)
    with pytest.raises(ValueError): apply(deal,'signed_cps_received',{**evidence,field:value})

def test_cross_deal_attachment_rejected(deal,tmp_path):
    evidence=doc(deal,tmp_path)
    with connect() as conn:
        other=create_deal(conn,title='Other',side='listing',province='bc',actor='test',current_stage=5,dispatch_initial_stage=False)
    with pytest.raises(ValueError,match='belong'): apply(other,'signed_cps_received',evidence)

def test_failed_dispatch_rolls_back_stage_and_event(deal,monkeypatch):
    def fail(*args,**kwargs): raise RuntimeError('queue unavailable')
    monkeypatch.setattr(lt,'evaluate',fail)
    with pytest.raises(RuntimeError): apply(deal,'listing_prep_requested')
    with connect() as conn:
        assert get_deal(conn,deal['id'])['currentStage']==0
        assert not conn.execute("SELECT id FROM deal_events WHERE deal_id=? AND kind='stage_transition'",(deal['id'],)).fetchall()

def test_no_configured_workflow_rolls_back(deal):
    with connect() as conn: conn.execute('UPDATE admin_action_registry SET enabled=0 WHERE name LIKE ?', (deal['id']+'-%',))
    with pytest.raises(ValueError,match='no enabled workflow'): apply(deal,'listing_prep_requested')

def test_late_photos_queue_one_continuation(deal,tmp_path):
    at(deal,4); evidence=doc(deal,tmp_path,b'photo bytes')
    first=apply(deal,'photos_received',evidence)
    again=apply(deal,'photos_received',{**evidence,'sourceId':'resend'})
    assert first['outcome']=='updated' and len(first['runs'])==1
    assert again['outcome']=='duplicate'

def test_old_document_does_not_regress(deal,tmp_path):
    at(deal,7)
    assert apply(deal,'signed_cps_received',doc(deal,tmp_path))['outcome']=='already_beyond_stage'

def test_partial_removal_does_not_advance(deal,tmp_path):
    at(deal,6)
    with pytest.raises(ValueError,match='partial'): apply(deal,'signed_removal_received',{**doc(deal,tmp_path),'allConditionsRemoved':False})

def test_activation_request_is_not_publication(deal):
    at(deal,4)
    first=apply(deal,'mls_activation_requested')
    assert first['deal']['currentStage']==5
    assert first['deal']['extraToggles']['listingActivationStatus']=='requested'
    assert len(first['runs'])==2

def test_publication_same_stage_is_deduped_by_mls(deal):
    at(deal,5)
    evidence={**request(), 'publicationVerified':True,'mlsNumber':'TEST-123','verificationNotes':'MLS readback'}
    first=apply(deal,'mls_live_verified',evidence)
    again=apply(deal,'mls_live_verified',{**evidence,'sourceId':'another-check'})
    assert first['deal']['extraToggles']['listingActivationStatus']=='verified_live'
    assert again['outcome']=='duplicate'

def test_document_review_queues_without_advancing(deal,tmp_path):
    evidence=doc(deal,tmp_path)
    with connect() as conn:
        first=lt.queue_document_review(conn,deal['id'],source_id='gmail-one',attachments=[evidence])
    with connect() as conn:
        second=lt.queue_document_review(conn,deal['id'],source_id='gmail-two',attachments=[evidence])
        assert get_deal(conn,deal['id'])['currentStage']==0
    assert first['outcome']=='queued' and second['outcome']=='duplicate'

def test_manual_move_dispatches_without_fabricating_checklist(deal):
    result=apply(deal,'manual_stage_move',to_stage=2)
    assert result['deal']['currentStage']==2 and result['runs']
    assert not result['deal']['extraToggles']

def test_concurrent_duplicate_request_dispatches_once(deal):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:apply(deal,'listing_prep_requested'),range(2)))
    assert sorted(r['outcome'] for r in results)==['duplicate','moved']
    assert results[0]['runs']==results[1]['runs']

def test_connection_is_postgres_and_test_account_isolated(env):
    with connect() as conn:
        assert type(conn._raw).__module__.startswith('psycopg')


def test_buyer_and_archived_deals_rejected(deal):
    with connect() as conn: conn.execute("UPDATE deals SET side='buyer' WHERE id=?",(deal['id'],))
    with pytest.raises(ValueError,match='BC listing'): apply(deal,'listing_prep_requested')
    with connect() as conn: conn.execute("UPDATE deals SET side='listing', status='archived' WHERE id=?",(deal['id'],))
    with pytest.raises(ValueError,match='inactive'): apply(deal,'listing_prep_requested')


def test_retry_preserves_run_id_and_only_retries_dispatch_failure(deal):
    first=apply(deal,'listing_prep_requested'); rid=first['runs'][0]['id']
    with connect() as conn:
        conn.execute("UPDATE admin_action_runs SET status='failed',payload_json=? WHERE id=?",(json.dumps({'dispatchError':{'message':'cron failed'}}),rid))
    again=apply(deal,'listing_prep_requested')
    assert again['runs']==[{'id':rid,'status':'queued'}]
    with connect() as conn:
        conn.execute("UPDATE admin_action_runs SET status='failed',payload_json='{}' WHERE id=?",(rid,))
    assert apply(deal,'listing_prep_requested')['runs']==[{'id':rid,'status':'failed'}]


def test_two_drainers_create_one_cron_job(deal,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from elevate_cli.data import dispatch
    first=apply(deal,'listing_prep_requested');rid=first['runs'][0]['id']; spawned=[]
    monkeypatch.setattr(dispatch,'_admin_setup_dispatch_block_reason',lambda conn:None)
    monkeypatch.setattr(dispatch,'_agent_run_context_for_prompt',lambda *args:{})
    def spawn(**kw):
        spawned.append(kw['run_id']); return 'test-cron-job'
    monkeypatch.setattr(dispatch,'_spawn_cron_job',spawn)
    def drain(_):
        with connect() as conn: return dispatch.dispatch_action_run_to_cron(conn,rid)
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(drain,range(2)))
    assert spawned==[rid]
    assert all(r['status']=='running' for r in results)

def test_signed_cps_after_verbal_acceptance_updates_existing_stage(deal,tmp_path):
    at(deal,6)
    result=apply(deal,'signed_cps_received',doc(deal,tmp_path))
    assert result['outcome']=='updated' and len(result['runs'])==1
    assert result['deal']['currentStage']==6


def test_cron_prompt_contains_evidence_and_actual_request(env,monkeypatch):
    from elevate_cli.data import dispatch
    import cron.jobs
    captured={}
    def create(**kwargs): captured.update(kwargs); return {'id':'test-job'}
    monkeypatch.setattr(cron.jobs,'create_job',create)
    result=dispatch._spawn_cron_job(action={'skill':'real-estate-admin/listing-activation','name':'Activation'},
        deal={'id':'test-deal','side':'listing','currentStage':5},run_id='test-run',callback_token='test-only',actor='test',
        payload={'listingTriggerEvidence':request(),'resumeExistingArtifacts':True})
    assert result=='test-job'
    assert 'request-1' in captured['prompt'] and 'Prepare listing' in captured['prompt']
    assert 'real-estate-admin/listing-activation' in captured['skills']

@pytest.fixture
def router_client(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from elevate_cli.web_routes.admin_deals import create_admin_deals_router
    app=FastAPI()
    app.include_router(create_admin_deals_router(require_admin_setup_ready_for_launch=lambda:None,
        admin_jurisdiction_config=lambda:{'province':'BC'},web_actor='human:test'))
    with TestClient(app) as client: yield client


def test_manual_http_move_queues_work(router_client,deal):
    response=router_client.post(f'/api/admin/deals/{deal["id"]}/move',json={'toStage':2})
    assert response.status_code==200, response.text
    assert response.json()['currentStage']==2
    with connect() as conn:
        rows=conn.execute('SELECT id FROM admin_action_runs WHERE deal_id=?',(deal['id'],)).fetchall()
        assert len(rows)==1


def test_trigger_http_retry_is_idempotent(router_client,deal):
    url=f'/api/admin/deals/{deal["id"]}/trigger'
    body={'trigger':'listing_prep_requested','evidence':request()}
    first=router_client.post(url,json=body); second=router_client.post(url,json=body)
    assert first.status_code==second.status_code==200
    assert second.json()['outcome']=='duplicate' and second.json()['runs']==first.json()['runs']


def test_trigger_http_queue_failure_is_visible_and_atomic(router_client,deal,monkeypatch):
    def fail(*a,**kw): raise RuntimeError('test outage')
    monkeypatch.setattr(lt,'evaluate',fail)
    response=router_client.post(f'/api/admin/deals/{deal["id"]}/trigger',json={'trigger':'listing_prep_requested','evidence':request()})
    assert response.status_code==500 and 'unchanged' in response.json()['detail']
    with connect() as conn: assert get_deal(conn,deal['id'])['currentStage']==0


def test_trigger_tool_uses_the_shared_service(deal,monkeypatch):
    monkeypatch.setattr('elevate_cli.access.is_entitlement_active',lambda *a,**kw:True)
    from tools.admin_deal_tool import _admin_deal_handler
    result=json.loads(_admin_deal_handler({'action':'trigger','deal_id':deal['id'],
        'trigger':'listing_prep_requested','evidence':request()}))
    assert result['success'] and result['deal']['currentStage']==2 and result['runs']

def test_writing_accepted_date_alone_cannot_advance_bc_listing(deal,monkeypatch):
    from elevate_cli.data import deals
    at(deal,5)
    with connect() as conn:
        snapshot=deals.get_deal(conn,deal['id'])
    monkeypatch.setattr(deals,'get_deal_context',lambda *args:{'deal':snapshot,'dealFlow':{'gate':{'canAdvance':True,'nextStage':6}}})
    with connect() as conn:
        updated=deals.set_deal_fields(conn,deal['id'],actor='test',fields={'offerAcceptedAt':'2026-09-09T00:00:00Z'})
        assert updated['currentStage']==5
