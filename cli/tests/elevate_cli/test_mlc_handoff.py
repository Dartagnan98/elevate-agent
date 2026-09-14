import json
import hashlib
import pytest
import fitz
from elevate_cli.data import connect, create_deal, create_action
from elevate_cli.data.deals import record_run_result, list_deal_events, set_deal_toggle
from elevate_cli.data.dispatch import _insert_run
from elevate_cli.mlc_handoff import resume_documents_after_intake, document_review_prompt


def setup_runs(conn, document_status='skipped'):
    deal=create_deal(conn,title='Ellis listing',side='listing',current_stage=2,actor='human:test',dispatch_initial_stage=False)
    event=list_deal_events(conn,deal['id'])[0]['id']
    runs=[]
    for mode,status in [('intake','running'),('documents',document_status)]:
        action=create_action(conn,name=mode,trigger='manual',skill='real-estate-admin/mlc',skill_args={'mode':mode},side='listing',enabled=False)
        runs.append(_insert_run(conn,registry_id=action['id'],deal_id=deal['id'],deal_event_id=event,payload={'toStage':2},status=status))
    return deal, runs[0], runs[1]


def save_title_evidence(conn, deal_id, tmp_path):
    title = tmp_path/'title.pdf'
    with fitz.open() as pdf:
        pdf.new_page().insert_text((30,30),'Registered owner: Test Seller'); pdf.save(title)
    values = {'sellerLegalNames':['Test Seller'], 'sellerMailingAddress':'10 Test Road, Town, BC V1Y 1Z9',
              'pid':'028-077-580','listingBrokerageRetained':'3% of sale price',
              'listingTitleVerification':{'filePath':str(title),'sha256':hashlib.sha256(title.read_bytes()).hexdigest(),
                'searchedAt':'2026-09-11','pid':'028-077-580','registeredOwners':['Test Seller'],
                'matchedSellerNames':['Test Seller'],'ownerMatch':True,'status':'verified'}}
    for key,value in values.items():
        set_deal_toggle(conn,deal_id,field=key,value=value,actor='human:test',dispatch_events=False)


def test_intake_completion_resumes_skipped_documents_once_with_mode_preserved():
    with connect() as conn:
        deal,intake,skipped=setup_runs(conn)
        record_run_result(conn,deal['id'],intake['id'],status='succeeded',idempotency_key='complete-intake')
        resumed=resume_documents_after_intake(conn,deal['id'],intake['id'])
        assert resumed and resumed != skipped['id']
        record_run_result(conn,deal['id'],intake['id'],status='succeeded',idempotency_key='complete-intake')
        rows=conn.execute('SELECT r.status,r.payload_json,a.skill_args_json FROM admin_action_runs r JOIN admin_action_registry a ON a.id=r.registry_id WHERE r.deal_id=?',(deal['id'],)).fetchall()
        assert len([r for r in rows if json.loads(r['skill_args_json'] or '{}').get('mode') in ('intake','documents')])==3
        queued=[r for r in rows if r['status']=='queued' and json.loads(r['skill_args_json'] or '{}').get('mode')=='documents']
        assert len(queued)==1
        assert json.loads(queued[0]['skill_args_json'])['mode']=='documents'
        assert json.loads(queued[0]['payload_json'])['sourceIntakeRunId']==intake['id']


def test_active_document_run_is_not_duplicated():
    with connect() as conn:
        deal,intake,documents=setup_runs(conn,'running')
        record_run_result(conn,deal['id'],intake['id'],status='succeeded')
        assert resume_documents_after_intake(conn,deal['id'],intake['id'])==documents['id']
        assert conn.execute('SELECT COUNT(*) AS n FROM admin_action_runs WHERE deal_id=?',(deal['id'],)).fetchone()['n']==3


def test_document_success_requires_real_kit_files_and_becomes_review(tmp_path,monkeypatch):
    monkeypatch.setattr('elevate_cli.notify_admin.notify_waiting_human',lambda *a,**k:None)
    pdf=tmp_path/'mlc.pdf'
    with fitz.open() as writer:
        writer.new_page(); writer.save(pdf)
    with connect() as conn:
        deal,intake,documents=setup_runs(conn,'running')
        absent=document_review_prompt(conn,deal['id'],documents['id'])
        assert absent['actionLabel']=='Retry preparation'
        set_deal_toggle(conn,deal['id'],field='listingKitForms',value={'dorts':False,'pnc':False,'pds':False},actor='human:test',dispatch_events=False)
        save_package(conn,deal['id'],tmp_path,('mlc',))
        save_title_evidence(conn, deal['id'], tmp_path)
        result=record_run_result(conn,deal['id'],documents['id'],status='succeeded')
        assert result['status']=='waiting_human'
        assert [d['id'] for d in result['humanPrompt']['documentReview']['documents']]==['mlc']
        prompt=dict(result['humanPrompt'],decision={'approved':True,'documentVersionHash':result['humanPrompt']['documentReview']['versionHash']})
        assert document_review_prompt(conn,deal['id'],documents['id'],prompt) is None


def save_package(conn, deal_id, tmp_path, ids=('mlc','dorts','pnc','pds')):
    docs=[]
    for ident in ids:
        path=tmp_path/f'{ident}.pdf'
        with fitz.open() as pdf:
            page=pdf.new_page(); page.insert_text((30,30), ident)
            if ident == 'mlc':
                for i,name in enumerate(('txtseller1','txtsellersig1')):
                    w=fitz.Widget(); w.field_name=name; w.field_type=fitz.PDF_WIDGET_TYPE_TEXT
                    w.rect=fitz.Rect(30,60+i*40,260,85+i*40); w.field_value='Test Seller'; page.add_widget(w)
            pdf.save(path)
        docs.append({'id':ident,'name':ident.upper(),'ready':True,'filePath':str(path)})
    set_deal_toggle(conn,deal_id,field='listingKit',value={'documents':docs},actor='human:test',dispatch_events=False)


def test_default_forms_cannot_be_silently_missing(tmp_path):
    with connect() as conn:
        deal,intake,run=setup_runs(conn,'running')
        save_package(conn,deal['id'],tmp_path,('mlc',))
        assert document_review_prompt(conn,deal['id'],run['id'])['actionLabel']=='Retry preparation'
        save_package(conn,deal['id'],tmp_path)
        prompt=document_review_prompt(conn,deal['id'],run['id'])
        assert len(prompt['documentReview']['documents'])==4


@pytest.mark.parametrize('change',['bytes','inputs','missing','invalid','selection'])
def test_changed_package_cannot_use_old_approval(tmp_path,change):
    from elevate_cli.mlc_handoff import validate_document_review
    with connect() as conn:
        deal,intake,run=setup_runs(conn,'running')
        save_package(conn,deal['id'],tmp_path)
        prompt=document_review_prompt(conn,deal['id'],run['id'])
        prompt['decision']={'approved':True,'documentVersionHash':prompt['documentReview']['versionHash']}
        if change=='bytes':
            with fitz.open() as pdf:
                pdf.new_page().insert_text((30,30),'Changed contract');pdf.save(tmp_path/'mlc.pdf')
        elif change=='inputs':
            set_deal_toggle(conn,deal['id'],field='listingCommission',value='New terms',actor='human:test',dispatch_events=False)
        elif change=='selection':
            set_deal_toggle(conn,deal['id'],field='listingKitForms',value={'pds-no-disclosure':True},actor='human:test',dispatch_events=False)
        elif change=='missing':
            (tmp_path/'pds.pdf').unlink()
        else:
            (tmp_path/'pds.pdf').write_text('Not a PDF')
        with pytest.raises(ValueError,match='changed or are incomplete'):
            validate_document_review(conn,deal['id'],prompt['documentReview'])
        assert document_review_prompt(conn,deal['id'],run['id'],prompt) is not None


def test_approval_api_records_exact_version_and_rejects_regeneration(tmp_path,monkeypatch):
    from elevate_cli.data.dispatch import approve_action_run
    monkeypatch.setattr('elevate_cli.notify_admin.notify_waiting_human',lambda *a,**k:None)
    with connect() as conn:
        deal,intake,run=setup_runs(conn,'running')
        save_package(conn,deal['id'],tmp_path)
        save_title_evidence(conn,deal['id'],tmp_path)
        result=record_run_result(conn,deal['id'],run['id'],status='succeeded')
        approved=approve_action_run(conn,run['id'],create_cron_job=False)
        assert approved['humanPrompt']['decision']['documentVersionHash']==result['humanPrompt']['documentReview']['versionHash']
        save_package(conn,deal['id'],tmp_path)
        # Changed PDF bytes require another review even on the same run.
        with fitz.open() as pdf:
            pdf.new_page().insert_text((30,30),'Revised');pdf.save(tmp_path/'mlc.pdf')
        changed=record_run_result(conn,deal['id'],run['id'],status='succeeded')
        assert changed['status']=='waiting_human'
        assert changed['humanPrompt']['documentReview']['versionHash']!=result['humanPrompt']['documentReview']['versionHash']


def test_title_is_required_and_changed_sellers_cannot_reuse_ownership_check(tmp_path):
    from elevate_cli.mlc_handoff import validate_document_review
    with connect() as conn:
        deal,intake,run=setup_runs(conn,'running')
        save_package(conn,deal['id'],tmp_path)
        prompt=document_review_prompt(conn,deal['id'],run['id'])
        assert len(prompt['documentReview']['documents'])==4
        assert 'current LTSA title' in prompt['approvalBlockedReason']
        with pytest.raises(ValueError,match='current LTSA title'):
            validate_document_review(conn,deal['id'],prompt['documentReview'])
        save_title_evidence(conn,deal['id'],tmp_path)
        prompt=document_review_prompt(conn,deal['id'],run['id'])
        assert 'approvalBlockedReason' not in prompt
        validate_document_review(conn,deal['id'],prompt['documentReview'])
        set_deal_toggle(conn,deal['id'],field='sellerLegalNames',value=['Different Seller'],actor='human:test',dispatch_events=False)
        assert 'reconcile all sellers' in document_review_prompt(conn,deal['id'],run['id'])['approvalBlockedReason']
        (tmp_path/'title.pdf').write_bytes(b'changed title')
        assert 'current LTSA title' in document_review_prompt(conn,deal['id'],run['id'])['approvalBlockedReason']


def test_listing_sign_cannot_bypass_title_preparation(tmp_path):
    from fastapi import HTTPException
    from elevate_cli.web_routes.admin_deals import create_admin_deals_router, _KitSignBody
    with connect() as conn:
        deal,_,_=setup_runs(conn,'running')
        save_package(conn,deal['id'],tmp_path)
    router=create_admin_deals_router(require_admin_setup_ready_for_launch=lambda:None,admin_jurisdiction_config=lambda:{'province':'BC'},web_actor='human:test')
    route=next(r.endpoint for r in router.routes if r.name=='post_admin_deal_listing_sign')
    with pytest.raises(HTTPException) as error:
        route(deal['id'],_KitSignBody(docIds=['mlc']))
    assert error.value.status_code==409
    assert 'current LTSA title' in error.value.detail
    with connect() as conn:
        assert conn.execute('SELECT COUNT(*) AS n FROM admin_action_runs WHERE deal_id=?',(deal['id'],)).fetchone()['n']==2
