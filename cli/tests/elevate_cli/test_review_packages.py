import json
from pathlib import Path
from unittest.mock import Mock, patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from elevate_cli.review_packages import freeze_review, validate_review, register_artifacts, registered_artifacts
from elevate_cli.web_routes.admin_actions import create_admin_actions_router
from elevate_cli.data.dispatch import approve_action_run

@pytest.fixture
def manifest(tmp_path):
    landing = tmp_path / 'landing' / 'sample'; landing.mkdir(parents=True)
    (landing / 'index.html').write_text('<h1>Reviewed listing</h1>')
    p = tmp_path / 'launch-review.json'
    p.write_text(json.dumps({'version':1, 'mode':'publish', 'actions':[{'id':'publish_landing','label':'Publish landing','details':'https://listings.example/sample/'}], 'artifacts':[{'path':'landing/sample/index.html','name':'Landing page'}], 'trees':['landing']}))
    return p

def test_rejects_changed_images_and_added_public_files(manifest):
    review = freeze_review(manifest)
    validate_review(review, publishing=True)
    extra = manifest.parent/'landing/sample/unreviewed.txt'; extra.write_text('new public file')
    with pytest.raises(ValueError, match='changed'): validate_review(review, publishing=True)
    extra.unlink()
    (manifest.parent/'landing/sample/index.html').write_text('changed')
    with pytest.raises(ValueError, match='changed'): validate_review(review, publishing=True)

def test_draft_review_never_grants_publish_permission(manifest):
    doc = json.loads(manifest.read_text()); doc.update(mode='prepare',actions=[],requiredFields=['Launch timing']); manifest.write_text(json.dumps(doc))
    review = freeze_review(manifest)
    validate_review(review)
    with pytest.raises(ValueError, match='not permission'): validate_review(review,publishing=True)

def test_registered_artifacts_survive_session_continuation_and_dedupe(manifest):
    values={}; db=Mock(); db.get_meta.side_effect=lambda k:values.get(k); db.set_meta.side_effect=lambda k,v:values.update({k:v})
    register_artifacts(db, {'lineage_root_id':'original','active_session_id':'original'}, [{'path':str(manifest),'name':'Launch plan'}])
    register_artifacts(db, {'lineage_root_id':'original','active_session_id':'compressed'}, [{'path':str(manifest),'name':'Updated launch plan'}])
    found=registered_artifacts(db, {'lineage_root_id':'original','active_session_id':'compressed-again'})
    assert len(found)==1 and found[0]['name']=='Updated launch plan'

def test_approval_hands_off_exact_review_and_cancellation_never_dispatches(manifest):
    review=freeze_review(manifest)
    row={'status':'waiting_human','human_prompt_json':json.dumps({'reviewPackage':review}), 'payload_json':'{}'}
    conn=Mock()
    with patch('elevate_cli.data.dispatch._run_lookup', return_value=row), patch('elevate_cli.data.dispatch.dispatch_action_run_to_cron',return_value={'status':'running'}) as dispatch:
        assert approve_action_run(conn,'test')['status']=='running'
        sql_calls=conn.execute.call_args_list
        payloads=[json.loads(c.args[1][0]) for c in sql_calls if c.args[0].startswith('UPDATE admin_action_runs SET payload_json=')]
        assert payloads[0]['resumeExistingArtifacts']['reviewPackage']['versionHash']==review['versionHash']
        assert payloads[0]['resumeExistingArtifacts']['decision']['actions']==['publish_landing']
        dispatch.assert_called_once()
    # Dismiss still works if an old draft was deleted or changed.
    manifest.unlink()
    with patch('elevate_cli.data.dispatch._run_lookup', return_value=row), patch('elevate_cli.data.dispatch._select_action_run_with_registry'), patch('elevate_cli.data.dispatch._row_to_run',return_value={'status':'cancelled'}), patch('elevate_cli.data.dispatch.dispatch_action_run_to_cron') as dispatch:
        assert approve_action_run(conn,'test',approved=False)['status']=='cancelled'
        dispatch.assert_not_called()

def test_unapproved_changed_and_repeated_claims_are_rejected(manifest):
    review=freeze_review(manifest)
    prompt={'reviewPackage':review,'decision':{'approved':True,'versionHash':review['versionHash'],'actions':['publish_landing']}}
    row={'status':'running','human_prompt_json':json.dumps(prompt)}
    conn=Mock(); conn.__enter__=Mock(return_value=conn); conn.__exit__=Mock(return_value=False)
    def execute(sql, params):
        if sql.startswith('UPDATE admin_action_runs SET human_prompt_json='): row['human_prompt_json']=params[0]
        return Mock()
    conn.execute.side_effect=execute
    app=FastAPI();app.include_router(create_admin_actions_router(require_admin_setup_ready_for_launch=lambda:None,web_actor='test'))
    client=TestClient(app);url='/api/admin/action-runs/test/claim-review-action';body={'action':'publish_landing','runDir':str(manifest.parent)}
    with patch('elevate_cli.data.connect',return_value=conn),patch('elevate_cli.data.dispatch._run_lookup',return_value=row):
        assert client.post(url,json={**body,'action':'schedule_mailjet'}).status_code==409
        assert client.post(url,json=body).status_code==200
        assert client.post(url,json=body).status_code==409
        prompt['decision']['approved']=False;row['human_prompt_json']=json.dumps(prompt)
        assert client.post(url,json=body).status_code==409
        prompt['decision']['approved']=True;row['human_prompt_json']=json.dumps(prompt)
        (manifest.parent/'landing/sample/index.html').write_text('changed')
        assert client.post(url,json=body).status_code==409


def test_registered_inventory_does_not_rescan_chat_history(manifest):
    from elevate_cli.web_routes.session_details import create_session_detail_router
    import logging
    db=Mock();db.get_meta.return_value=json.dumps([{'path':str(manifest),'name':'Launch plan','registeredAt':1}])
    app=FastAPI()
    app.include_router(create_session_detail_router(get_session_db=lambda:db, open_in_file_manager=lambda p:None, session_reveal_target=lambda s:Path('.'), live_subagent_child_session_ids=lambda:set(), log=logging.getLogger(__name__)))
    with patch('elevate_cli.web_routes.session_details._resolve_active_session_or_404',return_value=('original','compressed',{'lineage_root_id':'original','active_session_id':'compressed'})), patch('elevate_cli.web_routes.session_details._load_session_messages',side_effect=AssertionError('registered previews must not load transcript')):
        response=TestClient(app).get('/api/sessions/original/artifacts')
        assert response.status_code==200, response.text
        assert response.json()['artifacts'][0]['name']=='Launch plan'


def test_explicit_recorded_approval_is_applied_without_a_second_prompt(manifest):
    from elevate_cli.review_packages import apply_recorded_review_authorization
    review=freeze_review(manifest)
    answer='Send the coming-soons now. Landing approved. Video later.'
    payload={'resumeExistingArtifacts':{'reviewPackage':review,'providedAnswers':{'Launch timing':answer}}}
    row={'status':'waiting_human','payload_json':json.dumps(payload),'human_prompt_json':'{}'}
    conn=Mock()
    with patch('elevate_cli.data.dispatch._run_lookup',return_value=row):
        result=apply_recorded_review_authorization(conn,'run',str(manifest),['publish_landing'],answer)
        assert result['status']=='running'
        assert result['decision']['actions']==['publish_landing']
        with pytest.raises(ValueError,match='exact recorded'):
            apply_recorded_review_authorization(conn,'run',str(manifest),['publish_landing'],'Invented approval')
        (manifest.parent/'landing/sample/index.html').write_text('changed content')
        with pytest.raises(ValueError,match='asset changed'):
            apply_recorded_review_authorization(conn,'run',str(manifest),['publish_landing'],answer)


def test_worker_result_cannot_reopen_the_same_approved_launch(manifest):
    from elevate_cli.review_packages import preserve_review_consent
    review=freeze_review(manifest);decision={'approved':True,'versionHash':review['versionHash'],'actions':['publish_landing']}
    payload={'resumeExistingArtifacts':{'reviewPackage':review,'decision':decision}}
    prompt,status=preserve_review_consent(payload,{}, {'title':'Approve landing again','requiredFields':[]},'waiting_human')
    assert status=='waiting_external'
    assert prompt['decision']==decision
    assert payload['reviewAuthorizations'][0]['actions']==['publish_landing']
    different={**review,'versionHash':'new-version'}
    _,status=preserve_review_consent(payload,{}, {'reviewPackage':different},'waiting_human')
    assert status=='waiting_human'
    _,status=preserve_review_consent(payload,{}, {'requiredFields':['Reconnect provider']},'waiting_human')
    assert status=='waiting_human'


def test_immediate_authorization_does_not_expire_during_provider_retries(manifest):
    doc=json.loads(manifest.read_text());doc['actions']=[{'id':'schedule_buffer','label':'Publish now','details':'Approved Forever posts','schedule':['immediate'],'destinations':['Forever']}]
    for name in ['posts.json','inputs.json']:(manifest.parent/name).write_text('{}')
    doc['files']=['posts.json','inputs.json'];manifest.write_text(json.dumps(doc))
    validate_review(freeze_review(manifest),publishing=True)
