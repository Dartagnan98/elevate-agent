import json, os, sys
sys.path.insert(0, "/Users/dartagnanpatricio/elevate-diag-trace/cli")
ISO = "/tmp/elevate-harden.GzsCa5"
TRACE = f"{ISO}/logs/compaction-trace.jsonl"

events = [json.loads(l) for l in open(TRACE) if l.strip()]
def count(ev): return sum(1 for e in events if e.get("event")==ev)

rotation = count("agent.session_rotation_start")+count("agent.session_rotation_done")+count("agent.preserved_context_inserted")+count("agent.compression_checkpoint_stored")
done = count("agent.compress_context_done")
persisted = count("agent.compaction_metadata_persisted")
noop = count("agent.compress_context_noop")

print("=== TRACE ASSERTIONS ===")
print(f"  compress_context_done (real compactions): {done}")
print(f"  compaction_metadata_persisted: {persisted}")
print(f"  compress_context_noop (cursor didn't advance, handled): {noop}")
print(f"  ROTATION-family events (must be 0): {rotation}  -> {'PASS' if rotation==0 else 'FAIL'}")

# sessions that compacted, from the done events
compacted_sids = [e.get("session_id") for e in events if e.get("event")=="agent.compaction_metadata_persisted"]
cursors = {e.get("session_id"): e.get("cursor") for e in events if e.get("event")=="agent.compaction_metadata_persisted"}
print(f"  compacted sessions: {compacted_sids}")

print("\n=== DB ASSERTIONS (isolated SQLite) ===")
os.environ["ELEVATE_HOME"] = ISO
from elevate_state import SessionDB
from pathlib import Path; db = SessionDB(db_path=Path(f"{ISO}/state.db"))
allpass = rotation==0 and done>=1 and persisted>=1
for sid in set(compacted_sids):
    if not sid: continue
    row = db.get_session(sid)
    msgs = db.get_messages(sid)
    cur = (row or {}).get("compaction_cursor")
    summ = (row or {}).get("compaction_summary")
    nmsg = len(msgs)
    cur_ok = bool(cur and cur>0)
    sum_ok = bool(summ)
    # monotonic: transcript rows must be >= the cursor (transcript never shrank below the compacted head)
    mono_ok = nmsg >= (cur or 0)
    print(f"  session {sid}: rows={nmsg} compaction_cursor={cur} summary_chars={len(summ or '')}")
    print(f"     cursor>0: {'PASS' if cur_ok else 'FAIL'} | summary persisted: {'PASS' if sum_ok else 'FAIL'} | rows>=cursor (transcript intact): {'PASS' if mono_ok else 'FAIL'}")
    allpass = allpass and cur_ok and sum_ok and mono_ok

print("\nBACKEND RESULT:", "PASS" if allpass else "FAIL")
