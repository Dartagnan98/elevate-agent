"""Preview server for the dashboard's Drips page.

Runs the real ``/api/drips`` router on an embedded Postgres under a scratch
``ELEVATE_HOME``, seeded with demo contacts spread across the segments, so the
page can be reviewed with content before a release. Pair it with the Vite
preview entry::

    ELEVATE_HOME=/tmp/elevate-drips-preview .venv/bin/python scripts/drips_preview_server.py
    cd web && npx vite --config vite.mock.config.ts
    open http://127.0.0.1:5179/mock-drips.html?theme=dark   # or theme=light

Never point this at a real ``ELEVATE_HOME``: it inserts demo contacts.
"""
import os, sys
from datetime import date, timedelta
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

from elevate_cli import data, drips_db
from elevate_cli.web_routes.drips import create_drips_router

app = FastAPI()
app.include_router(create_drips_router(web_actor="human:web"))


@app.get("/", response_class=HTMLResponse)
def index():
    return '<html><head><script>window.__ELEVATE_SESSION_TOKEN__="mock";window.__ELEVATE_DASHBOARD_EMBEDDED_CHAT__=false;</script></head><body></body></html>'


def seed():
    today = date.today()
    with drips_db.connect() as conn:
        try:
            conn.execute("INSERT INTO admin_setup_profile (id, license_name, brokerage_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                         ("mock", "Skyleigh McCallum", "eXp Realty", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"))
        except Exception as exc:
            print("identity seed skipped:", exc)
        people = [
            ("Tara Bourassa", "tara.bourassa@example.com", "(250) 555-0142", "buyer", "warm", 13, True, False, "said spring, pre-approved"),
            ("Priya Devi", "priya.devi@example.com", "(250) 555-0734", "buyer", "lukewarm", 29, True, True, "selling to buy, 4 to 5 months"),
            ("Mark Liu", "mark.liu@example.com", "(778) 555-0356", "buyer", "new", 2, True, False, "website sign-up"),
            ("Jordan Trent", "jordan.trent@example.com", "(250) 555-0211", "buyer", "hot", 4, True, False, "offer-ready, viewing Saturday"),
            ("Carol Chen", "carol.chen@example.com", "(250) 555-0188", "buyer", "bad_number", 9, True, False, "voicemail full x3"),
            ("Sam & Rosie Park", "park.family@example.com", "(604) 555-0612", "buyer", "long_term", 44, True, False, "next year, after the baby"),
            ("Linda Hayworth", "linda.hayworth@example.com", "(250) 555-0673", "listing", "soi", 74, False, False, "closed seller, Sahali"),
            ("Wayne Chorney", "wayne.chorney@example.com", "(250) 555-0468", "buyer", None, 0, False, False, None),
            ("Bonnie Gerrior", "bonnie.gerrior@example.com", "(250) 555-0509", "buyer", None, 0, False, False, None),
        ]
        for name, email, phone, ctype, seg, days_ago, buying, selling, note in people:
            c = data.upsert_contact(conn, display_name=name, primary_email=email, primary_phone=phone, type=ctype, source_key=f"mock:{email}")
            if seg:
                drips_db.set_contact_segment(conn, c["id"], seg, actor="human:web", note=note, buying=buying, selling=selling,
                                             start_date=today - timedelta(days=days_ago))
        drips_db.update_video(conn, "exploratory-tour", link="https://youtu.be/exploratory-tour-demo")
        drips_db.update_video(conn, "market-insight", link="https://youtu.be/market-insight-demo")
        summary = drips_db.run_engine(conn, today=today)
        print("engine:", summary)


if __name__ == "__main__":
    if not os.environ.get("ELEVATE_HOME"):
        sys.exit("set ELEVATE_HOME to a scratch directory first; this server seeds demo contacts")
    seed()
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "9119")), log_level="warning")
