import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

from elevate_cli import source_connectors as sc
from elevate_cli.source_connector_modules.lofty_sync import _lofty_refresh_plan, sync_lofty_crm_source


def test_changed_profile_bypasses_fresh_cache_and_failures_rotate():
    jobs = [{"lead_id": str(i), "fingerprint": "new"} for i in range(3)]
    saved = {"fingerprints": {"0": "old", "1": "new", "2": "old"}, "attempted_at": {"0": "2026-09-10"}}
    fresh, selected, deferred = _lofty_refresh_plan(jobs, {"0", "1"}, saved, 1)
    assert fresh == {"1"}
    assert [j["lead_id"] for j in selected] == ["2"]
    assert deferred == 1


def test_bounded_sync_preserves_details_rotates_and_refreshes_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "get_source_root_info", lambda config=None: {"sourceRoot": str(tmp_path)})
    monkeypatch.setattr(sc, "_combined_env", lambda config: {"LOFTY_API_KEY": "test"})
    leads = [{"leadId": str(i), "firstName": "Test", "updateTime": 1} for i in range(3)]
    monkeypatch.setattr(sc, "_lofty_get", lambda *a, **kw: {"leads": leads})
    monkeypatch.setattr(sc, "_lofty_get_activities", lambda *a, **kw: [])
    monkeypatch.setattr(sc, "_lofty_get_tasks", lambda *a, **kw: [])
    calls = []
    def notes(lid, *a, **kw):
        calls.append(lid)
        return [{"id": "n" + lid, "content": "Preserved body " + lid}]
    monkeypatch.setattr(sc, "_lofty_get_notes", notes)
    phases = []
    monkeypatch.setattr(sc, "_walk_jsonl_into_pg", lambda path: phases.append((path / 'lead-events.jsonl').read_text()))
    cfg = {"integrations": {"crm": {"provider": "lofty", "sync": {"incremental_enrichment": True, "enrichment_workers": 1, "max_detail_leads_per_run": 1}}}}
    for expected in ["0", "1", "2"]:
        sync_lofty_crm_source(cfg)
        assert calls[-1] == expected
    assert len(calls) == 3
    assert 'Preserved body 0' in phases[2]  # retained in next run's phase 1
    sync_lofty_crm_source(cfg)
    assert len(calls) == 3
    leads[1]["updateTime"] = 2
    sync_lofty_crm_source(cfg)
    assert calls == ["0", "1", "2", "1"]
    checkpoint = json.loads((tmp_path / "crm/artifacts/enrichment_progress.json").read_text())
    assert len(checkpoint['events']) == 3
    assert checkpoint['status'] == 'complete'


def test_unchanged_stale_details_get_oldest_first():
    jobs = [{"lead_id": str(i), "fingerprint": "same"} for i in range(2)]
    saved = {"fingerprints": {"0": "same", "1": "same"}, "refreshed_at": {"0": "2026-09-10", "1": "2026-09-09"}}
    _, selected, deferred = _lofty_refresh_plan(jobs, set(), saved, 1)
    assert selected[0]["lead_id"] == "1"
    assert deferred == 1


def test_background_gate_serializes_processes_and_releases_after_exit(tmp_path):
    from elevate_cli import background_budget
    runner = str(Path(background_budget.__file__))
    marker = tmp_path / "busy"
    program = "import os,time,pathlib; p=pathlib.Path(__import__('sys').argv[1]); fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY); time.sleep(.1); os.close(fd); p.unlink()"
    command = [sys.executable, runner, '--lock', str(tmp_path/'gate.lock'), '--', sys.executable, '-c', program, str(marker)]
    procs = [subprocess.Popen(command) for _ in range(3)]
    assert [p.wait(timeout=10) for p in procs] == [0, 0, 0]
    # Failure of a holder must not strand the next job.
    assert subprocess.run(command[:-3]+['-c', 'raise SystemExit(4)'], timeout=5).returncode == 4
    assert subprocess.run(command, timeout=5).returncode == 0


def test_scheduler_uses_shared_gate_and_keeps_pack_job_identity(tmp_path, monkeypatch):
    import fcntl
    import time
    from cron import scheduler
    lock = tmp_path / 'background.lock'
    jobs = [dict(id='admin-job', name='Admin intake', pack_id='admin', deliver='local'),
            dict(id='leads-job', name='Lead intake', pack_id='leads', deliver='local')]
    seen = []
    monkeypatch.setattr(scheduler, '_get_lock_paths', lambda: (tmp_path, tmp_path/'tick.lock'))
    monkeypatch.setattr(scheduler, 'load_config', lambda: {'cron': {'max_parallel_jobs': 2}, 'background_jobs': {'lock_path': str(lock)}})
    monkeypatch.setattr(scheduler, 'get_due_jobs', lambda: jobs)
    for name in ['advance_next_run', 'save_job_output', '_deliver_result', 'mark_job_run', '_end_precreated_cron_session']:
        monkeypatch.setattr(scheduler, name, lambda *a, **kw: None)
    monkeypatch.setattr(scheduler, '_precreate_cron_session', lambda *a, **kw: False)
    def run(job, **kw):
        # A separate file description cannot acquire the same admission lock.
        with lock.open('a') as contender:
            try:
                fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                raise AssertionError('scheduler did not acquire the shared gate')
        seen.append(('start', job['id'], job['pack_id']))
        time.sleep(.03)
        seen.append(('end', job['id'], job['pack_id']))
        return True, 'output', 'response', None
    monkeypatch.setattr(scheduler, 'run_job', run)
    assert scheduler.tick(verbose=False) == 2
    assert [event[0] for event in seen] == ['start', 'end', 'start', 'end']
    assert {event[1:] for event in seen} == {('admin-job', 'admin'), ('leads-job', 'leads')}
