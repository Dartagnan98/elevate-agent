import ast
import copy
import json
import logging
import os
import sys
import types
from pathlib import Path

import pytest
from elevate_cli.web_routes import kit_state as ks


class HTTPException(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code


@pytest.fixture
def routes(monkeypatch, tmp_path):
    state = {}
    class Conn:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, args):
            if sql.startswith('UPDATE deals'):
                state.clear(); state.update(json.loads(args[0]))
            return self
        def fetchone(self): return {'extra_toggles_json': json.dumps(state), 'listing_address': '123 Test Street'}
    data = types.ModuleType('elevate_cli.data'); data.connect = Conn
    monkeypatch.setitem(sys.modules, 'elevate_cli.data', data)
    ns = dict(kit_state=ks, kit_pdf=types.SimpleNamespace(version_path=ks.version_path), HTTPException=HTTPException, os=os, _log=logging.getLogger('test'), require_admin_setup_ready_for_launch=lambda: None, _cps_deal_facts=lambda _: {}, _user_site_env=lambda: {})
    original_expand = os.path.expanduser
    monkeypatch.setattr(os.path, 'expanduser', lambda path: str(tmp_path / path[2:]) if path.startswith('~/') else original_expand(path))
    source = Path(__file__).parents[2] / 'elevate_cli/web_routes/admin_deals.py'
    tree = ast.parse(source.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ('LISTING_STD', 'LISTING_WIRED', 'LISTING_RETIRED'):
                    try: ns[target.id] = ast.literal_eval(node.value)
                    except ValueError: pass
    ns['LISTING_STD_IDS'] = {d[0] for d in ns['LISTING_STD']}
    ns['_listing_toggles'] = lambda *args: copy.deepcopy(state)
    def save(conn, deal, toggles):
        state.clear(); state.update(copy.deepcopy(toggles))
    ns['_listing_save'] = save
    for name in ('post_admin_deal_build_offer_kit', 'post_admin_deal_build_listing_kit', 'post_admin_deal_listing_sign', 'post_offer_kit_draft_signatures'):
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
        node.decorator_list = []
        module = ast.parse('from __future__ import annotations')
        module.body.append(node)
        exec(compile(ast.fix_missing_locations(module), str(source), 'exec'), ns)
    return state, ns


def test_wizard_price_change_refreshes_automatic_fields(routes):
    state, ns = routes
    state['cpsPurchasePrice'] = '500000'
    build = ns['post_admin_deal_build_offer_kit']
    build('test')
    doc = state['offerKit']['documents'][0]
    assert doc['ready'] is False and doc['filePath'] == ''
    state['cpsPurchasePrice'] = '550000'
    build('test')
    assert state['offerKit']['documents'][0]['fields']['price'] == '550000'


@pytest.mark.parametrize('kit,docid,route', [('offerKit','cps-residential','post_admin_deal_build_offer_kit'), ('listingKit','mlc','post_admin_deal_build_listing_kit')])
def test_rebuild_keeps_stale_metadata(routes, kit, docid, route):
    state, ns = routes
    state[kit] = {'documents': [{'id':docid, 'generatedAt':'2026-09-01', 'editedAt':'2026-09-02', 'filePath':'/missing.pdf'}]}
    ns[route]('test')
    doc = next(d for d in state[kit]['documents'] if d['id']==docid)
    assert ks.stale(doc)
    assert doc['generatedAt'] == '2026-09-01'


def test_other_form_override_survives_rebuild(routes):
    state, ns = routes
    state['offerKit'] = {'documents': [{'id':'privacy-notice','fields':{'clientName':'Test Buyer'}}]}
    ns['post_admin_deal_build_offer_kit']('test')
    doc = next(d for d in state['offerKit']['documents'] if d['id']=='privacy-notice')
    assert doc['fields']['clientName'] == 'Test Buyer'


def test_manual_override_including_empty_is_preserved():
    prev = {'fields': {'price':'490000','deposit':''}, 'seededFields': {'price':'500000','deposit':'1000'}, 'fieldOverrides': {'price':'490000','deposit':''}}
    fields, _, _ = ks.seed_fields(prev, {'price':'550000','deposit':'2000'})
    assert fields == {'price':'490000','deposit':''}


def test_ambiguous_legacy_edits_require_confirmation():
    with pytest.raises(ValueError, match='Confirm'):
        ks.seed_fields({'fields':{'price':'490000'}}, {'price':'550000'})


@pytest.mark.parametrize('kit', ['offerKit','listingKit'])
def test_signing_checks_entire_exact_selection(tmp_path, kit):
    pdf = tmp_path/'draft.pdf'; pdf.write_bytes(b'test')
    doc = {'id':'privacy-notice','filePath':str(pdf),'status':'draft'}
    state = {kit:{'documents':[doc]}}
    assert ks.selected_documents(state, kit, ['privacy-notice']) == [doc]
    with pytest.raises(ValueError, match='Select'): ks.selected_documents(state, kit, [])
    with pytest.raises(ValueError, match='missing'): ks.selected_documents(state, kit, ['privacy-notice','unknown'])
    key = 'cpsKitForms' if kit == 'offerKit' else 'listingKitForms'
    state[key] = {'privacy-notice':False}
    with pytest.raises(ValueError, match='excluded'): ks.selected_documents(state, kit, ['privacy-notice'])
    state[key]['privacy-notice'] = True
    doc['editedAt'] = '2026-09-08'
    with pytest.raises(ValueError, match='Redraft'): ks.selected_documents(state, kit, ['privacy-notice'])
    doc.pop('editedAt'); pdf.unlink()
    with pytest.raises(ValueError, match='Draft'): ks.selected_documents(state, kit, ['privacy-notice'])


def test_source_revision_catches_agent_writes_and_field_changes():
    state = {'cpsPurchasePrice':'500000'}; doc = {'fields':{'price':'500000'}}
    doc['generatedInputHash'] = ks.input_hash(state, doc)
    assert not ks.stale(doc, state)
    state['cpsPurchasePrice']='550000'
    assert ks.stale(doc, state)
    state['cpsPurchasePrice']='500000'; doc['fields']['price']='490000'
    assert ks.stale(doc, state)


@pytest.mark.parametrize('kit,route', [('offerKit','post_offer_kit_draft_signatures'), ('listingKit','post_admin_deal_listing_sign')])
@pytest.mark.parametrize('preview_ok', [False, True])
def test_review_dispatch_requires_preview_and_always_waits(routes, tmp_path, monkeypatch, kit, route, preview_ok):
    import subprocess
    state, ns = routes
    pdf = tmp_path / 'source.pdf'; pdf.write_bytes(b'fixture')
    state[kit] = {'documents':[{'id':'privacy-notice','name':'Privacy','filePath':str(pdf),'status':'draft'}]}
    queued = []
    dispatch = types.ModuleType('elevate_cli.data.dispatch')
    def queue(conn, **kwargs):
        queued.append(kwargs)
        return {'id':'fixture-run'}
    dispatch.queue_action_run = queue
    monkeypatch.setitem(sys.modules, 'elevate_cli.data.dispatch', dispatch)
    def merge(command, **kwargs):
        if preview_ok: Path(command[3]).write_bytes(b'preview')
        return types.SimpleNamespace(returncode=0 if preview_ok else 1)
    monkeypatch.setattr(subprocess, 'run', merge)
    body = types.SimpleNamespace(docIds=['privacy-notice'])
    if preview_ok:
        result = ns[route]('test', body)
        assert result['draftFirst'] is True
        assert len(queued) == 1 and queued[0]['create_cron_job'] is False
    else:
        with pytest.raises(HTTPException) as exc: ns[route]('test', body)
        assert exc.value.status_code == 503
        assert not queued


def test_deposit_holder_flows_from_wizard_to_contract(routes):
    state, ns = routes
    state['cpsDepositHolder'] = 'Example Brokerage in trust'
    ns['post_admin_deal_build_offer_kit']('test')
    doc = state['offerKit']['documents'][0]
    assert doc['fields']['depositHolder'] == 'Example Brokerage in trust'
    state['cpsDepositHolder'] = 'Different Trust Holder'
    ns['post_admin_deal_build_offer_kit']('test')
    assert state['offerKit']['documents'][0]['fields']['depositHolder'] == 'Different Trust Holder'
