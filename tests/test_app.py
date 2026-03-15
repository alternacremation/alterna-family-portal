from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import app, init_db


@pytest.fixture()
def client():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        upload_path = Path(tmp) / "uploads"
        app.config.update(
            TESTING=True,
            DATABASE=str(db_path),
            UPLOAD_FOLDER=str(upload_path),
            WTF_CSRF_ENABLED=False,
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="alterna-demo",
            ADMIN_DISPLAY_NAME="Ashley",
            OBITUARY_WEBHOOK_SECRET="testing-secret",
        )
        with app.app_context():
            init_db()
        with app.test_client() as client:
            yield client


def sign_in(client, username="admin", password="alterna-demo"):
    return client.post(
        "/admin/login",
        data={"username": username, "password": password, "next": "/admin"},
        follow_redirects=True,
    )


def create_submission(client, **extra):
    data = {
        "case_reference": "ALT-1002",
        "family_name": "Ashley Newton",
        "family_email": "ashley@example.com",
        "family_phone": "204-555-1212",
        "relationship_to_deceased": "Daughter",
        "deceased_first_name": "Jane",
        "deceased_last_name": "Smith",
        "informant_name": "Ashley Newton",
        "signature_name": "Ashley Newton",
        "privacy_consent": "on",
    }
    data.update(extra)
    return client.post("/submit", data=data, follow_redirects=False)


def test_home_page_loads(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Alterna Cremation Family Portal" in response.data
    assert b"All required fields are turned off" in response.data


def test_submit_accepts_blank_testing_submission(client):
    response = client.post("/submit", data={}, follow_redirects=False)
    assert response.status_code == 302
    assert "/thank-you?token=" in response.headers["Location"]


def test_submit_page_has_new_intake_language(client):
    response = client.get("/submit")
    assert b"Yes, a death has occurred" in response.data
    assert b"No, a death has not occurred, I am pre-planning" in response.data
    assert b"Are you pre-planning for yourself or someone else?" in response.data
    assert b"Is there a will?" in response.data
    assert b"Same person as above" in response.data
    assert b"Sex" in response.data


def test_submit_accepts_without_consent(client):
    response = client.post(
        "/submit",
        data={
            "family_email": "ashley@example.com",
            "deceased_first_name": "John",
            "deceased_last_name": "Smith",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/thank-you?token=" in response.headers["Location"]


def test_admin_requires_login(client):
    response = client.get("/admin", follow_redirects=True)
    assert response.status_code == 200
    assert b"Staff sign in" in response.data


def test_staff_login_requires_username_and_password(client):
    response = sign_in(client)
    assert response.status_code == 200
    assert b"Signed in successfully." in response.data
    assert b"Ashley, admin" in response.data


def test_successful_submission_redirects_to_portal(client):
    response = create_submission(client)
    assert response.status_code == 302
    assert "/thank-you?token=" in response.headers["Location"]


def test_dashboard_lists_submission_and_portal(client):
    create_submission(client)
    sign_in(client)
    dashboard = client.get("/admin")
    assert b"ALT-1002" in dashboard.data
    assert b"Jane Smith" in dashboard.data
    assert b"Open portal" in dashboard.data
    assert b"Integration outbox" in dashboard.data


def test_auto_obituary_generation_visible_in_detail(client):
    create_submission(
        client,
        obituary_style="Traditional obituary",
        family_message="She loved her garden and her grandchildren.",
        service_details="Private family gathering.",
        charity_requests="CancerCare Manitoba",
    )
    sign_in(client)
    detail = client.get("/admin/submission/1")
    assert b"She loved her garden and her grandchildren." in detail.data
    assert b"CancerCare Manitoba" in detail.data


def test_file_upload_and_status_update(client):
    client.post(
        "/submit",
        data={
            "case_reference": "ALT-1004",
            "family_name": "Family Contact",
            "family_email": "family@example.com",
            "family_phone": "204-555-3333",
            "deceased_first_name": "Mary",
            "deceased_last_name": "Jones",
            "informant_name": "Family Contact",
            "signature_name": "Family Contact",
            "privacy_consent": "on",
            "memorial_files": (io.BytesIO(b"fake image bytes"), "photo.jpg"),
        },
        content_type="multipart/form-data",
    )
    sign_in(client)
    detail = client.get("/admin/submission/1")
    assert b"photo.jpg" in detail.data

    updated = client.post(
        "/admin/submission/1/update",
        data={
            "status": "In Review",
            "progress_step": "Drafting obituary",
            "staff_notes": "Waiting on final family approval.",
            "family_status_note": "We are reviewing the obituary draft for you.",
        },
        follow_redirects=True,
    )
    assert b"Submission updated." in updated.data
    assert b"In Review" in updated.data
    assert b"Waiting on final family approval." in updated.data


def test_family_portal_message_thread_works(client):
    create_submission(client)
    sign_in(client)
    dashboard = client.get("/admin")
    assert b"Open portal" in dashboard.data

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(dashboard.data, "html.parser")
    portal_href = next(a["href"] for a in soup.find_all("a") if "/family/" in a.get("href", ""))

    client.post(
        portal_href,
        data={"action": "message", "sender_name": "Ashley", "message_text": "Can I send one more photo?"},
        follow_redirects=True,
    )
    detail = client.get("/admin/submission/1")
    assert b"Can I send one more photo?" in detail.data


def test_publish_memorial_page_and_json_feed(client):
    create_submission(client, obituary_text="Jane lived well and was deeply loved.")
    sign_in(client)
    detail = client.get("/admin/submission/1")
    assert b"Approve and publish" in detail.data

    client.post("/admin/submission/1/publish", data={"publish": "1"}, follow_redirects=True)
    detail_after = client.get("/admin/submission/1")
    assert b"View memorial" in detail_after.data
    assert b"Memorial JSON" in detail_after.data

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(detail_after.data, "html.parser")
    memorial_json_href = next(a["href"] for a in soup.find_all("a") if "/api/memorial/" in a.get("href", ""))
    memorial_json = client.get(memorial_json_href)
    assert memorial_json.status_code == 200
    assert memorial_json.json["obituary"] == "Jane lived well and was deeply loved."


def test_summary_pdf_and_csv_exports(client):
    create_submission(client, obituary_text="Jane lived well and was deeply loved.")
    sign_in(client)
    pdf = client.get("/admin/submission/1/summary.pdf")
    assert pdf.status_code == 200
    assert pdf.mimetype == "application/pdf"

    csv_response = client.get("/admin/export.csv")
    assert csv_response.status_code == 200
    assert b"ALT-1002" in csv_response.data

    vital_csv = client.get("/admin/export-vital.csv")
    assert vital_csv.status_code == 200
    assert b"case_reference" in vital_csv.data


def test_published_memorial_asset_is_public(client):
    client.post(
        "/submit",
        data={
            "case_reference": "ALT-2001",
            "family_name": "Family Contact",
            "family_email": "family@example.com",
            "family_phone": "204-555-7777",
            "deceased_first_name": "Ava",
            "deceased_last_name": "Stone",
            "informant_name": "Family Contact",
            "signature_name": "Family Contact",
            "privacy_consent": "on",
            "obituary_text": "Ava was loved.",
            "memorial_files": (io.BytesIO(b"fake image bytes"), "ava.jpg"),
        },
        content_type="multipart/form-data",
    )
    sign_in(client)
    client.post("/admin/submission/1/publish", data={"publish": "1"}, follow_redirects=True)
    detail = client.get("/admin/submission/1")
    assert b"View memorial" in detail.data

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(detail.data, "html.parser")
    memorial_href = next(a["href"] for a in soup.find_all("a") if "/memorial/" in a.get("href", ""))
    public_page = client.get(memorial_href)
    assert public_page.status_code == 200
    assert b"Ava was loved." in public_page.data
    assert b"/memorial-assets/" in public_page.data


def test_no_obituary_style_does_not_generate_text(client):
    create_submission(client, obituary_style="No obituary")
    sign_in(client)
    detail = client.get("/admin/submission/1")
    assert b"No obituary draft provided yet." in detail.data


def test_integration_outbox_and_webhook_ack(client):
    create_submission(client, obituary_text="Jane lived well and was deeply loved.")
    sign_in(client)
    client.post("/admin/submission/1/publish", data={"publish": "1"}, follow_redirects=True)

    outbox = client.get("/admin/integrations/outbox.json")
    assert outbox.status_code == 200
    assert any(item["event_type"] == "obituary_publish_requested" for item in outbox.json)

    slug = next(item["payload"]["memorial_slug"] for item in outbox.json if item["event_type"] == "obituary_publish_requested")
    ack = client.post(
        "/api/webhooks/obituary-published",
        json={"memorial_slug": slug, "site_status": "published"},
        headers={"X-Alterna-Webhook-Secret": "testing-secret"},
    )
    assert ack.status_code == 200
    assert ack.json["ok"] is True


def test_readme_and_deployment_files_exist(client):
    root = PROJECT_ROOT
    assert (root / ".env.example").exists()
    assert (root / "Dockerfile").exists()
    assert (root / "gunicorn.conf.py").exists()


def test_health_endpoints(client):
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json["ok"] is True

    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json["ok"] is True
    assert ready.json["database"] is True


def test_staging_and_integration_docs_exist(client):
    root = PROJECT_ROOT
    assert (root / "docker-compose.staging.yml").exists()
    assert (root / ".env.staging.example").exists()
    assert (root / "DEPLOY_STAGING.md").exists()
    assert (root / "WEBSITE_INTEGRATION_MAP.md").exists()
    assert (root / "scripts" / "sample_memorial_import.py").exists()


def test_website_importer_stub_files_exist(client):
    root = PROJECT_ROOT
    assert (root / "scripts" / "website_importer_stub.py").exists()
    assert (root / "WEBSITE_IMPORTER_STUB.md").exists()


def test_website_importer_stub_render_and_bundle(tmp_path):
    from scripts.website_importer_stub import build_listing_record, render_memorial_html, write_import_bundle

    payload = {
        "memorial_slug": "jane-smith-a1b2c3",
        "name": "Jane Smith",
        "preferred_name": "Jane",
        "date_of_birth": "1942-05-01",
        "date_of_death": "2026-03-10",
        "headline": "In loving memory",
        "obituary": "Jane lived well and was deeply loved.\n\nShe adored her family.",
        "service_details": "Private family gathering.",
        "charity_requests": "CancerCare Manitoba",
        "photos": [{"filename": "jane.jpg", "site_cached_url": "assets/photo-1.jpg"}],
        "published": True,
        "canonical_site_url": "https://www.alternacremation.ca/obituaries/jane-smith-a1b2c3",
    }

    record = build_listing_record(payload)
    assert record["slug"] == "jane-smith-a1b2c3"
    assert record["life_dates"] == "1942-05-01 to 2026-03-10"

    html = render_memorial_html(payload)
    assert "Jane Smith | Alterna Cremation Obituaries" in html
    assert "CancerCare Manitoba" in html
    assert "assets/photo-1.jpg" in html

    paths = write_import_bundle(payload, tmp_path)
    assert paths["html"].exists()
    assert paths["json"].exists()
    assert paths["index"].exists()
    assert "jane-smith-a1b2c3.html" in paths["index"].read_text(encoding="utf-8")
