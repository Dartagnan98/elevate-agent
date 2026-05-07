from __future__ import annotations

import csv
import io

import pytest
from fastapi.testclient import TestClient

from elevate_cli.data import connect, import_listing_sheet_csv, list_deals
from elevate_cli.data.connection import _reset_schema_cache


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


@pytest.fixture
def client():
    from elevate_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN, app

    c = TestClient(app, headers={_SESSION_HEADER_NAME: _SESSION_TOKEN})
    yield c
    if hasattr(app.state, "bound_host"):
        del app.state.bound_host


HEADERS = [
    "Row ID",
    "Property Address",
    "Date Created",
    "Current Stage",
    "Google Drive Folder URL",
    "Signing Authority",
    "FINTRAC Form Type",
    "Politically Exposed Person?",
    "Listing Track",
    "Property Sub-Type",
    "Tenanted Property?",
    "Estate / Probate Status",
    "POA Signing?",
    "Corporate Seller?",
    "Client 1 Name",
    "Client 1 Email",
    "Client 1 Phone",
    "Lofty Contact URL",
    "Listing Price",
    "Commission Rate (%)",
    "Planned Go-Live Date",
    "Listing Type",
    "Has Suite?",
    "Stage 1 Complete ✓",
    "Documents Sent Date",
    "Title Ordered?",
    "Stage 2 Complete ✓",
    "Photos in Drive?",
    "Stage 3 Complete ✓",
    "MLS Listing URL",
    "Live Date (Actual)",
    "Stage 5 Complete ✓",
    "Offer Received Date",
    "Accepted Offer Date",
    "Deposit ROF Received Date",
    "Completion Date",
    "Moving Checklist Sent",
    "Stage 6 Complete ✓",
    "Subject Removal Date",
    "Subject Removal Form Sent",
    "Stage 7 Complete ✓",
    "Possession Date",
    "Stage 8 Complete ✓",
    "Sold Update Sent",
    "Review Requested",
    "Stage 9 Complete ✓",
    "Notes",
]


def _csv(rows: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["IDENTIFIERS", "", "", "STAGE 0"])
    writer.writerow(HEADERS)
    writer.writerow(["instructions"] * len(HEADERS))
    for row in rows:
        writer.writerow([row.get(header, "") for header in HEADERS])
    return buf.getvalue()


def test_import_listing_sheet_csv_types_rows_into_deals():
    csv_text = _csv([
        {
            "Row ID": "1",
            "Property Address": "17-750 Fortune Drive, Kamloops, BC",
            "Date Created": "2026-04-28",
            "Current Stage": "Stage 5 - Listing Live",
            "Google Drive Folder URL": "https://drive.google.com/folder",
            "Signing Authority": "Individual",
            "FINTRAC Form Type": "Standard",
            "Politically Exposed Person?": "No",
            "Listing Track": "MLS",
            "Property Sub-Type": "Mobile",
            "Tenanted Property?": "No",
            "Estate / Probate Status": "None",
            "POA Signing?": "No",
            "Corporate Seller?": "No",
            "Client 1 Name": "Jenna Hutchinson",
            "Client 1 Email": "jenna@example.com",
            "Lofty Contact URL": "https://app.lofty.com/contact/1145885890673237",
            "Listing Price": "$179,900",
            "Commission Rate (%)": "3.50%",
            "Planned Go-Live Date": "2026-03-07",
            "Listing Type": "Mobile",
            "Stage 1 Complete ✓": "TRUE",
            "Documents Sent Date": "2026-03-07",
            "Title Ordered?": "TRUE",
            "Stage 2 Complete ✓": "TRUE",
            "Photos in Drive?": "TRUE",
            "Stage 3 Complete ✓": "TRUE",
            "MLS Listing URL": "https://interiorrealtors.xposureapp.com/portal/listings/10378203",
            "Live Date (Actual)": "2026-03-07",
            "Stage 5 Complete ✓": "TRUE",
            "Notes": "Imported note.",
        }
    ])

    with connect() as conn:
        result = import_listing_sheet_csv(conn, csv_text, province="BC")
        deals = list_deals(conn, status=None)

    assert result["created"] == 1
    assert result["updated"] == 0
    assert len(deals) == 1
    deal = deals[0]
    assert deal["sourceKey"].endswith(":204411937:1")
    assert deal["title"] == "17-750 Fortune Drive, Kamloops, BC"
    assert deal["currentStage"] == 5
    assert deal["province"] == "BC"
    assert deal["loftyContactId"] == "1145885890673237"
    assert deal["pep"] is False
    assert deal["propertySubtype"] == "Mobile"
    assert deal["listPrice"] == 179900
    assert deal["commissionPct"] == 3.5
    assert deal["listingDate"] == "2026-03-07"
    assert deal["listingPublishedAt"] == "2026-03-07"
    assert deal["mlsNumber"] == "10378203"
    assert deal["extraToggles"]["sheet_stage_1_complete"] is True
    assert deal["extraToggles"]["sheet_documents_sent_date"] == "2026-03-07"
    assert deal["extraToggles"]["sheet_google_drive_folder_url"] == "https://drive.google.com/folder"


def test_import_listing_sheet_csv_reimport_updates_same_source_row():
    first = _csv([
        {
            "Row ID": "7",
            "Property Address": "610 Gleneagles Drive, Kamloops, BC",
            "Current Stage": "Stage 5 - Listing Live",
            "Listing Price": "$674,900",
            "Stage 5 Complete ✓": "TRUE",
        }
    ])
    second = _csv([
        {
            "Row ID": "7",
            "Property Address": "610 Gleneagles Drive, Kamloops, BC",
            "Current Stage": "Stage 7 - Subject Removal Complete",
            "Listing Price": "$674,900",
            "Accepted Offer Date": "2026-04-08",
            "Subject Removal Date": "2026-04-26",
            "Stage 7 Complete ✓": "TRUE",
        }
    ])

    with connect() as conn:
        import_listing_sheet_csv(conn, first, province="BC")
        result = import_listing_sheet_csv(conn, second, province="BC")
        deals = list_deals(conn, status=None)

    assert result["created"] == 0
    assert result["updated"] == 1
    assert len(deals) == 1
    assert deals[0]["currentStage"] == 7
    assert deals[0]["offerAcceptedAt"] == "2026-04-08"
    assert deals[0]["subjectRemovalDate"] == "2026-04-26"
    assert deals[0]["extraToggles"]["sheet_stage_7_complete"] is True


def test_sheet_import_endpoint_accepts_csv_text(client):
    csv_text = _csv([
        {
            "Row ID": "2",
            "Property Address": "B11-7155 Dallas Drive, Kamloops, BC",
            "Current Stage": "Stage 5 - Listing Live",
            "Listing Price": "$349,900",
            "Stage 5 Complete ✓": "TRUE",
        }
    ])

    resp = client.post(
        "/api/admin/deals/import-sheet",
        json={"csvText": csv_text, "province": "BC"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] == 1
    assert body["count"] == 1
    assert body["items"][0]["listPrice"] == 349900
