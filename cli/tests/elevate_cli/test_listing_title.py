import json
import pytest
import fitz
from elevate_cli.data import connect
from elevate_cli.data.deals import record_run_result, set_deal_toggle
from elevate_cli.data.dispatch import approve_action_run
from elevate_cli.listing_title import prepare_title_order, claim_title_order, ensure_title_preparation
from elevate_cli.mlc_handoff import title_identity_issues, listing_preparation_issues
from tests.elevate_cli.test_mlc_handoff import setup_runs, save_package, save_title_evidence

QUOTE = {'pid':'028-077-580','titleNumber':'CA7871214','totalCad':'13.37','quotedAt':'2026-01-01T00:00:00+00:00'}


def title_run(conn):
    deal,intake,docs = setup_runs(conn,'running')
    set_deal_toggle(conn,deal['id'],field='pid',value=QUOTE['pid'],actor='human:test',dispatch_events=False)
    return deal,intake,docs,prepare_title_order(conn,deal['id'],QUOTE)


def test_intake_queues_title_research_once_without_purchase_authority():
    with connect() as conn:
        deal,intake,_=setup_runs(conn)
        record_run_result(conn,deal['id'],intake['id'],status='succeeded')
        ident=ensure_title_preparation(conn,deal['id'],intake['id'])
        assert ident==ensure_title_preparation(conn,deal['id'],intake['id'])
        row=conn.execute('SELECT status,human_prompt_json FROM admin_action_runs WHERE id=?',(ident,)).fetchone()
        assert row['status']=='queued'
        assert not json.loads(row['human_prompt_json'] or '{}').get('decision')


def test_title_approval_is_exact_once_and_does_not_approve_mlc(monkeypatch):
    spawned=[]
    monkeypatch.setattr('elevate_cli.data.dispatch._admin_setup_dispatch_block_reason',lambda conn:None)
    monkeypatch.setattr('elevate_cli.data.dispatch._spawn_cron_job',lambda **kw: spawned.append(kw) or 'test-job')
    with connect() as conn:
        deal,_,docs,run=title_run(conn)
        q=run['humanPrompt']['titleOrder']
        assert prepare_title_order(conn,deal['id'],QUOTE)['id']==run['id']
        with pytest.raises(ValueError,match='not been approved'):
            claim_title_order(conn,run['id'],QUOTE)
        with pytest.raises(ValueError,match='changed'):
            approve_action_run(conn,run['id'],create_cron_job=False)
        result=approve_action_run(conn,run['id'],expected_title_order_hash=q['versionHash'])
        assert result['status']=='running'
        assert spawned[0]['action']['skillArgs']['mode']=='listing_intake_title'
        assert spawned[0]['agent_context']['currentRun']['humanPrompt']['decision']['titleOrderHash']==q['versionHash']
        assert 'documentVersionHash' not in result['humanPrompt']['decision']
        with pytest.raises(ValueError,match='price changed'):
            claim_title_order(conn,run['id'],dict(QUOTE,totalCad='14.00'))
        assert claim_title_order(conn,run['id'],QUOTE)['claimed'] is True
        with pytest.raises(ValueError,match='already started'):
            claim_title_order(conn,run['id'],QUOTE)
        assert conn.execute('SELECT status FROM admin_action_runs WHERE id=?',(docs['id'],)).fetchone()['status']=='running'


def test_changed_quote_and_changed_pid_require_new_consent():
    with connect() as conn:
        deal,_,_,run=title_run(conn)
        old=run['humanPrompt']['titleOrder']['versionHash']
        changed=prepare_title_order(conn,deal['id'],dict(QUOTE,totalCad='14.00'))
        assert changed['id']==run['id']
        with pytest.raises(ValueError,match='changed'):
            approve_action_run(conn,run['id'],expected_title_order_hash=old,create_cron_job=False)
        set_deal_toggle(conn,deal['id'],field='pid',value='000-000-001',actor='human:test',dispatch_events=False)
        with pytest.raises(ValueError,match='saved PID'):
            approve_action_run(conn,run['id'],expected_title_order_hash=changed['humanPrompt']['titleOrder']['versionHash'],create_cron_job=False)


def test_title_result_cannot_claim_success_without_title_and_preserves_purchase_claim(monkeypatch):
    notifications=[]
    monkeypatch.setattr('elevate_cli.notify_admin.notify_waiting_human',lambda *a,**k:notifications.append(1))
    with connect() as conn:
        deal,_,_,run=title_run(conn)
        approve_action_run(conn,run['id'],expected_title_order_hash=run['humanPrompt']['titleOrder']['versionHash'],create_cron_job=False)
        claim_title_order(conn,run['id'],QUOTE)
        result=record_run_result(conn,deal['id'],run['id'],status='succeeded')
        assert result['status']=='waiting_human'
        assert result['humanPrompt']['titleOrderClaim']
        assert result['humanPrompt']['approvalBlockedReason']
        assert not notifications
        with pytest.raises(ValueError,match='already started'):
            prepare_title_order(conn,deal['id'],dict(QUOTE,totalCad='14.00'))


def test_verified_title_resumes_drafts_without_approving_them(tmp_path,monkeypatch):
    monkeypatch.setattr('elevate_cli.notify_admin.notify_waiting_human',lambda *a,**k:None)
    with connect() as conn:
        deal,_,docs,run=title_run(conn)
        save_package(conn,deal['id'],tmp_path)
        record_run_result(conn,deal['id'],docs['id'],status='succeeded')
        save_title_evidence(conn,deal['id'],tmp_path)
        approve_action_run(conn,run['id'],expected_title_order_hash=run['humanPrompt']['titleOrder']['versionHash'],create_cron_job=False)
        result=record_run_result(conn,deal['id'],run['id'],status='succeeded')
        assert result['status']=='succeeded'
        docrun=conn.execute('SELECT status,human_prompt_json FROM admin_action_runs WHERE id=?',(docs['id'],)).fetchone()
        assert docrun['status']=='queued'
        assert not json.loads(docrun['human_prompt_json']).get('decision')


def test_title_owner_legal_spelling_and_actual_mlc_names_must_match(tmp_path):
    with connect() as conn:
        deal,_,_,_=title_run(conn)
        save_package(conn,deal['id'],tmp_path)
        save_title_evidence(conn,deal['id'],tmp_path)
        assert not listing_preparation_issues(conn,deal['id'])
        with fitz.open(tmp_path/'mlc.pdf') as pdf:
            page=pdf[0];w=next(page.widgets());w.field_value='Test Seler';w.update();pdf.saveIncr()
        assert any('full title-verified legal name' in i for i in listing_preparation_issues(conn,deal['id']))
        extra=json.loads(conn.execute('SELECT extra_toggles_json FROM deals WHERE id=?',(deal['id'],)).fetchone()['extra_toggles_json'])
        extra['listingTitleVerification']['registeredOwners']=['Test Seller','Another Owner']
        assert title_identity_issues(extra)
        extra['listingTitleVerification']['registeredOwners']=['Test Seler']
        assert title_identity_issues(extra)


def test_http_title_review_and_approval_routes_require_the_displayed_quote(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from elevate_cli.web_routes.admin_actions import create_admin_actions_router
    app=FastAPI()
    app.include_router(create_admin_actions_router(require_admin_setup_ready_for_launch=lambda:None,web_actor='human:test'))
    with connect() as conn:
        deal,_,_,_=title_run(conn)
    client=TestClient(app)
    response=client.post(f"/api/admin/deals/{deal['id']}/title-order-review",json=QUOTE)
    assert response.status_code==200,response.text
    run=response.json()
    rejected=client.post(f"/api/admin/action-runs/{run['id']}/approve",json={'approved':True,'runNow':False})
    assert rejected.status_code==400
    approved=client.post(f"/api/admin/action-runs/{run['id']}/approve",json={'approved':True,'runNow':False,'expectedTitleOrderHash':run['humanPrompt']['titleOrder']['versionHash']})
    assert approved.status_code==200,approved.text
    assert approved.json()['humanPrompt']['decision']['titleOrderHash']==run['humanPrompt']['titleOrder']['versionHash']
    claim=client.post(f"/api/admin/action-runs/{run['id']}/claim-title-order",json=QUOTE)
    assert claim.status_code==200,claim.text
    assert client.post(f"/api/admin/action-runs/{run['id']}/claim-title-order",json=QUOTE).status_code==409


def test_dismissed_pre_title_review_is_preserved_and_new_title_gets_fresh_preparation(tmp_path,monkeypatch):
    monkeypatch.setattr('elevate_cli.notify_admin.notify_waiting_human',lambda *a,**k:None)
    with connect() as conn:
        deal,_,docs,run=title_run(conn)
        save_package(conn,deal['id'],tmp_path)
        record_run_result(conn,deal['id'],docs['id'],status='succeeded')
        approve_action_run(conn,docs['id'],approved=False,create_cron_job=False)
        save_title_evidence(conn,deal['id'],tmp_path)
        approve_action_run(conn,run['id'],expected_title_order_hash=run['humanPrompt']['titleOrder']['versionHash'],create_cron_job=False)
        record_run_result(conn,deal['id'],run['id'],status='succeeded')
        assert conn.execute('SELECT status FROM admin_action_runs WHERE id=?',(docs['id'],)).fetchone()['status']=='cancelled'
        rows=conn.execute('SELECT id,status,payload_json FROM admin_action_runs WHERE deal_id=?',(deal['id'],)).fetchall()
        fresh=[r for r in rows if json.loads(r['payload_json'] or '{}').get('verifiedTitleRunId')==run['id']]
        assert len(fresh)==1 and fresh[0]['status']=='queued' and fresh[0]['id']!=docs['id']
