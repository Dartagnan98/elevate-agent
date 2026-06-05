# macOS SMS / iMessage Transport — Canonical Process & Repair Runbook

**This is the single source of truth for how Elevate decides and sends a phone
message on a Mac.** Anything Mac-specific that sends to a phone number MUST go
through `_messages_native_dispatch` in `elevate_cli/sender.py`. Do not hand-roll
osascript sends or pick a transport anywhere else — duplicate paths are how
Android leads silently got blue-bubbled into oblivion.

> If you are an AI/engineer debugging "messages going out as iMessage again" or
> "SMS not delivering," read this whole file first. The system uses a **private
> Apple API** that can break on a macOS update — that is expected and handled,
> not a bug to panic-rewrite. The repair steps are at the bottom.

---

## The decision tree (the base process)

For a recipient phone number, `_detect_preferred_transport(phone)` decides:

1. **Proven iMessage history** in `chat.db` (last successful outbound was
   `service=iMessage`, `error=0`, `is_sent=1`) → **iMessage**.
2. **Proven SMS/RCS history** → **SMS**. (RCS = Android; the Mac can *receive*
   RCS mirrored from a paired iPhone but **cannot send** it.)
3. **No history** (a cold/new outreach number) OR **chat.db unreadable** →
   ask Apple's **IDS** (the iPhone's blue/green check) via the
   `ids-capability` probe:
   - IDStatus `1` → **iMessage**
   - IDStatus `2` → **SMS**
   - `0`/unknown/unavailable → fall through to ↓
4. **Default** → **SMS** (tunable via `ELEVATE_OUTREACH_DEFAULT_TRANSPORT`,
   default `sms`). SMS reaches every phone, so a cold number always lands.

Then `_osa_send_via(phone, draft, service)` sends, **preferring the `imsg` CLI**
(`imsg send --service sms|imessage`) and falling back to osascript only when
`imsg` isn't installed.

## Why each choice was made (do NOT "simplify" these away)

- **SMS-first for cold numbers.** Outreach targets people with no history.
  iMessage to a non-Apple number **silently fails** — chat.db logs it as
  `error=22` ("Not Delivered") but the queue marks it "sent." SMS reaches
  iPhone *and* Android. Guessing iMessage is the failure mode; defaulting SMS
  cannot fail on delivery.
- **`imsg`, not osascript, for the actual send.** macOS Messages **silently
  re-routes** an osascript `send ... of (service whose service type = SMS)` to
  iMessage for any iMessage-capable handle — so "force SMS" via AppleScript
  never actually sent SMS. `imsg send --service sms` truly forces the carrier
  transport. `imsg` also carries its **own Full Disk Access**, so it works even
  when the host app process can't read chat.db.
- **IDS framework query, not `imsg whois`.** `imsg whois` (and the IMCore
  bridge) need **SIP disabled** — a non-starter. The `ids-capability` probe
  reads Apple's IDS status the same way Messages does, with **no SIP change and
  no injection**.
- **RCS → SMS.** Mac can't send RCS; SMS is what lands for those Android users.

## Components

| Piece | File | Role |
|---|---|---|
| Transport decision | `elevate_cli/sender.py` `_detect_preferred_transport` | the tree above |
| iMessage-capability probe | `tools/ids-capability.swift` → `~/.elevate/bin/ids-capability` | IDS blue/green for no-history numbers |
| Probe wrapper / on-demand build | `sender.py` `_ids_capability`, `_ids_capability_bin` | runs/builds the probe, parses JSON, never raises |
| Actual send | `sender.py` `_osa_send_via` → `_imsg_send_via` | `imsg send --service ...` (osascript fallback) |
| Delivery verify | `sender.py` `_verify_send_landed` | reads chat.db for error 22 |
| History source | `~/Library/Messages/chat.db` | proven past transport |
| IDS cache | `~/Library/IdentityServices/idstatuscache.plist` | what `ids-capability` reads; `com.apple.madrid` service = iMessage |

## Where it connects

Leads **Approve** → `update_source_task_state(action="approve")` flips the
`send_queue` row to `queued` and fires `sender.tick()` →
`dispatch_one(row)` → `get_dispatcher("sms")` = **`_messages_native_dispatch`** →
detection + `imsg` send. Same path for any phone/SMS-channel send.

---

## Liabilities & caveats (READ before changing anything)

1. **IDS is a PRIVATE Apple framework** (`IDSIDQueryController` in
   `IDS.framework`). It can change or vanish on any macOS update. When it does,
   `ids-capability` returns `unknown` / nonzero exit, and detection **falls back
   to the SMS default** — sending never breaks, you only lose the blue-bubble
   upgrade for cold iPhone numbers until the probe is fixed. **Treat a broken
   probe as "degrade to SMS," not an outage.**
2. **`imsg` is a third-party Homebrew tool** (`brew install imsg`), not bundled.
   On a Mac without it, `_osa_send_via` falls back to osascript (which has the
   silent-SMS→iMessage reroute problem). For full reliability on every account,
   `imsg` must be installed or bundled. Confirm with `which imsg`.
3. **Full Disk Access is per-process and flaky for app-spawned children.** The
   Elevate app has FDA, but its child Python sometimes can't read chat.db
   ("unable to open database file"). `imsg` and `ids-capability` carry their own
   FDA, which is why the send + the probe are routed through them rather than
   in-process chat.db reads.
4. **SIP must stay enabled.** We deliberately avoid every path that needs SIP
   off (Messages dylib injection, `imsg whois`, `imsg launch`). Never instruct a
   client to `csrutil disable`.
5. **`ELEVATE_SMS_DISPATCHER` must stay unset/`native`.** If set to `agent`, SMS
   routes to `_send_agent_dispatch`, whose LLM prompt (`_build_send_prompt`) is
   **hardcoded iMessage-only** and bypasses ALL of this detection. That prompt
   is a latent liability — if you ever enable the agent dispatcher for SMS, fix
   the prompt to use the transport from `_detect_preferred_transport` first.
6. **Carrier / compliance.** Cold SMS at volume from a personal number (via
   Text Message Forwarding) will get throttled or blocked — it looks like spam,
   and US/Canada A2P 10DLC rules require a registered number + opt-out. For real
   outreach volume the durable answer is a dedicated SMS provider, not
   Messages.app. This is a business decision, not a code fix.

---

## Repair runbook — "it's sending iMessage / not delivering again"

**Symptom:** cold or Android numbers go out as iMessage, or chat.db shows
`service=iMessage error=22` (not delivered) for them.

### 1. Is the probe still working?
```bash
~/.elevate/bin/ids-capability "tel:+17787163070"   # known Android → expect transport:"sms"
~/.elevate/bin/ids-capability "tel:+1<your-iphone>" # → expect transport:"imessage"
```
- Returns correct `transport` → IDS is fine; problem is elsewhere (go to step 3).
- Errors / `transport:"unknown"` for known numbers → **IDS API changed (likely a
  macOS update).** Go to step 2.

### 2. Fix the IDS probe after a macOS change
The probe calls private selectors on `IDSIDQueryController`. If macOS renamed
them, re-introspect and update `tools/ids-capability.swift`:
```bash
cat > /tmp/idsm.swift <<'SWIFT'
import Foundation
import ObjectiveC.runtime
dlopen("/System/Library/PrivateFrameworks/IDS.framework/IDS", RTLD_NOW)
let cls = NSClassFromString("IDSIDQueryController")!
var n: UInt32 = 0
let im = class_copyMethodList(cls, &n)!
for i in 0..<Int(n) {
  let s = NSStringFromSelector(method_getName(im[i]))
  if s.lowercased().contains("status") { print(s) }
}
SWIFT
swift /tmp/idsm.swift
```
Look for the current equivalents of
`_currentIDStatusForDestination:service:listenerID:` (sync cache read, returns
Int64) and `_refreshIDStatusForDestinations:service:listenerID:` (force live
lookup). Update the selectors in `ids-capability.swift`, then rebuild:
```bash
swiftc -O ~/elevate/cli/tools/ids-capability.swift -o ~/.elevate/bin/ids-capability
```
The iMessage service is `com.apple.madrid`; IDStatus `1`=iMessage, `2`=not.
You can also confirm raw data directly:
```bash
plutil -convert json -o - ~/Library/IdentityServices/idstatuscache.plist | \
  python3 -c "import sys,json;d=json.load(sys.stdin);print({k:v for k,v in d['com.apple.madrid'].items() if '7787163070' in k})"
```
If `IDS.framework` itself is gone/blocked, detection still falls back to SMS —
acceptable until fixed.

### 3. Is the send itself forcing SMS?
```bash
which imsg && imsg status        # basic send must say "Available"; SIP can stay enabled
imsg send --to "+1<test>" --text "test" --service sms --json
# then check chat.db for the result:
python3 - <<'PY'
import sqlite3,os
c=sqlite3.connect(f"file:{os.path.expanduser('~/Library/Messages/chat.db')}?mode=ro",uri=True)
print(c.execute("SELECT service,error,is_sent FROM message m JOIN handle h ON m.handle_id=h.ROWID WHERE h.id LIKE '%<test10digits>%' AND is_from_me=1 ORDER BY date DESC LIMIT 1").fetchone())
PY
```
Want `('SMS', 0, 1)`. If `imsg` is missing → `brew install imsg`. If the send
goes through `_send_agent_dispatch` instead (no `sender.osa_send`/`imsg_send`
log lines), check `ELEVATE_SMS_DISPATCHER` is unset (caveat 5).

### 4. Confirm the wiring end-to-end (no send)
```bash
cd ~/elevate/cli && .venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from elevate_cli.sender import _detect_preferred_transport as d, _format_phone as fp, _ids_capability_bin
print('probe bin:', _ids_capability_bin())
for n in ['7787163070','<your-iphone>','5875559921']:
    print(n, '->', d(fp(n)))"
```

### 5. Which process actually sent it
The Leads **Approve** tick runs inside the **dashboard** process (the app
bundle), NOT the launchd gateway. After editing `sender.py`, redeploy to the app
bundle and restart the dashboard, or the old code keeps sending:
```bash
cp ~/elevate/cli/elevate_cli/sender.py "$HOME/Applications/Elevate.app/Contents/Resources/cli/elevate_cli/sender.py"
osascript -e 'quit app "Elevate"'; sleep 2; pkill -f "elevate_cli.main dashboard"; open -a Elevate
```

---

## Quick reference
- Decision: `sender.py:_detect_preferred_transport`
- Probe source: `tools/ids-capability.swift` → `~/.elevate/bin/ids-capability`
- IDS service for iMessage: `com.apple.madrid` (IDStatus 1=iMessage, 2=SMS)
- Send: `imsg send --service sms|imessage` (own FDA, forces transport)
- Env: `ELEVATE_OUTREACH_DEFAULT_TRANSPORT` (default sms),
  `ELEVATE_IDS_CAPABILITY_BIN` (probe path override),
  `ELEVATE_SMS_DISPATCHER` (keep unset/native)
