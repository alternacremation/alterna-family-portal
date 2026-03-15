from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flask import (
    Flask,
    Response,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from werkzeug.datastructures import FileStorage
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "alterna_family_app.db"
UPLOAD_FOLDER = BASE_DIR / "uploads"
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "pdf", "doc", "docx", "heic"}
PUBLIC_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
STATUS_OPTIONS = ["New", "In Review", "Ready", "Completed"]
WIZARD_STEPS = [
    "Start here",
    "About you",
    "About the deceased",
    "Obituary & files",
    "Review",
]

app = Flask(__name__)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

app.config["SECRET_KEY"] = os.environ.get("ALTERNA_APP_SECRET", "dev-secret-change-me")
app.config["DATABASE"] = str(DATABASE)
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024
app.config["ADMIN_PASSWORD"] = os.environ.get("ALTERNA_ADMIN_PASSWORD", "alterna-demo")
app.config["ADMIN_USERNAME"] = os.environ.get("ALTERNA_ADMIN_USERNAME", "admin")
app.config["ADMIN_DISPLAY_NAME"] = os.environ.get("ALTERNA_ADMIN_DISPLAY_NAME", "Ashley")
app.config["PORTAL_BASE_URL"] = os.environ.get("ALTERNA_PORTAL_BASE_URL", "https://portal.alternacremation.ca")
app.config["MAIN_SITE_BASE_URL"] = os.environ.get("ALTERNA_MAIN_SITE_BASE_URL", "https://www.alternacremation.ca")
app.config["OBITUARY_WEBHOOK_SECRET"] = os.environ.get("ALTERNA_OBITUARY_WEBHOOK_SECRET", "demo-obituary-webhook")
app.config["SESSION_COOKIE_SECURE"] = env_bool("ALTERNA_SESSION_COOKIE_SECURE", True)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = os.environ.get("ALTERNA_SESSION_COOKIE_SAMESITE", "Lax")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception: Exception | None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def cleaned_phone(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def multiline_compact(value: str) -> str:
    return "\n".join(line.strip() for line in value.splitlines()).strip()


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def is_public_image(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in PUBLIC_IMAGE_EXTENSIONS


def make_portal_token() -> str:
    return secrets.token_urlsafe(18)


def make_memorial_slug(first_name: str, last_name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", f"{first_name}-{last_name}".lower()).strip("-") or "memorial"
    return f"{base}-{secrets.token_hex(3)}"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def generate_case_reference() -> str:
    return f"ALT-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def init_db() -> None:
    upload_folder = Path(app.config["UPLOAD_FOLDER"])
    upload_folder.mkdir(parents=True, exist_ok=True)
    schema = """
    CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        updated_at TEXT,
        case_reference TEXT NOT NULL,
        family_name TEXT NOT NULL,
        family_email TEXT NOT NULL,
        family_phone TEXT NOT NULL,
        relationship_to_deceased TEXT,
        intake_type TEXT,
        preplanning_for TEXT,
        will_status TEXT,
        executor_is_contact TEXT,
        executor_name TEXT,
        executor_phone TEXT,
        executor_email TEXT,
        portal_token TEXT,
        preferred_name TEXT,
        family_message TEXT,
        deceased_first_name TEXT NOT NULL,
        deceased_middle_name TEXT,
        deceased_last_name TEXT NOT NULL,
        deceased_gender TEXT,
        date_of_birth TEXT,
        date_of_death TEXT,
        place_of_death TEXT,
        birth_city TEXT,
        birth_region_country TEXT,
        citizenship TEXT,
        sin_last_four TEXT,
        marital_status TEXT,
        spouse_name TEXT,
        children_details TEXT,
        occupation TEXT,
        usual_residence TEXT,
        father_name TEXT,
        mother_name TEXT,
        mother_maiden_name TEXT,
        informant_name TEXT,
        informant_email TEXT,
        informant_phone TEXT,
        informant_address TEXT,
        disposition_type TEXT,
        obituary_style TEXT,
        obituary_headline TEXT,
        obituary_text TEXT,
        obituary_generated TEXT,
        obituary_tone TEXT,
        service_details TEXT,
        charity_requests TEXT,
        photo_notes TEXT,
        photo_deadline TEXT,
        staff_notes TEXT,
        signature_name TEXT,
        family_status_note TEXT,
        privacy_consent INTEGER NOT NULL DEFAULT 0,
        memorial_published INTEGER NOT NULL DEFAULT 0,
        memorial_slug TEXT,
        status TEXT NOT NULL DEFAULT 'New',
        progress_step TEXT NOT NULL DEFAULT 'Submitted'
    );

    CREATE TABLE IF NOT EXISTS uploads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        submission_id INTEGER NOT NULL,
        original_filename TEXT NOT NULL,
        stored_filename TEXT NOT NULL,
        uploaded_at TEXT NOT NULL,
        FOREIGN KEY (submission_id) REFERENCES submissions(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS family_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        submission_id INTEGER NOT NULL,
        sender_role TEXT NOT NULL,
        sender_name TEXT NOT NULL,
        message_text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (submission_id) REFERENCES submissions(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS staff_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        display_name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'admin',
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        last_login_at TEXT
    );

    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        actor_type TEXT NOT NULL,
        actor_name TEXT NOT NULL,
        action TEXT NOT NULL,
        submission_id INTEGER,
        detail_json TEXT,
        FOREIGN KEY (submission_id) REFERENCES submissions(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS integration_outbox (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        event_type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',
        target TEXT,
        submission_id INTEGER,
        payload_json TEXT NOT NULL,
        delivered_at TEXT,
        FOREIGN KEY (submission_id) REFERENCES submissions(id) ON DELETE SET NULL
    );
    """
    with closing(sqlite3.connect(app.config["DATABASE"])) as db:
        db.executescript(schema)
        columns = {row[1] for row in db.execute("PRAGMA table_info(submissions)").fetchall()}
        required_columns = {
            "updated_at": "ALTER TABLE submissions ADD COLUMN updated_at TEXT",
            "intake_type": "ALTER TABLE submissions ADD COLUMN intake_type TEXT",
            "preplanning_for": "ALTER TABLE submissions ADD COLUMN preplanning_for TEXT",
            "will_status": "ALTER TABLE submissions ADD COLUMN will_status TEXT",
            "executor_is_contact": "ALTER TABLE submissions ADD COLUMN executor_is_contact TEXT",
            "executor_name": "ALTER TABLE submissions ADD COLUMN executor_name TEXT",
            "executor_phone": "ALTER TABLE submissions ADD COLUMN executor_phone TEXT",
            "executor_email": "ALTER TABLE submissions ADD COLUMN executor_email TEXT",
            "portal_token": "ALTER TABLE submissions ADD COLUMN portal_token TEXT",
            "preferred_name": "ALTER TABLE submissions ADD COLUMN preferred_name TEXT",
            "family_message": "ALTER TABLE submissions ADD COLUMN family_message TEXT",
            "birth_city": "ALTER TABLE submissions ADD COLUMN birth_city TEXT",
            "birth_region_country": "ALTER TABLE submissions ADD COLUMN birth_region_country TEXT",
            "citizenship": "ALTER TABLE submissions ADD COLUMN citizenship TEXT",
            "children_details": "ALTER TABLE submissions ADD COLUMN children_details TEXT",
            "mother_maiden_name": "ALTER TABLE submissions ADD COLUMN mother_maiden_name TEXT",
            "informant_email": "ALTER TABLE submissions ADD COLUMN informant_email TEXT",
            "informant_phone": "ALTER TABLE submissions ADD COLUMN informant_phone TEXT",
            "informant_address": "ALTER TABLE submissions ADD COLUMN informant_address TEXT",
            "obituary_style": "ALTER TABLE submissions ADD COLUMN obituary_style TEXT",
            "obituary_generated": "ALTER TABLE submissions ADD COLUMN obituary_generated TEXT",
            "obituary_tone": "ALTER TABLE submissions ADD COLUMN obituary_tone TEXT",
            "photo_deadline": "ALTER TABLE submissions ADD COLUMN photo_deadline TEXT",
            "staff_notes": "ALTER TABLE submissions ADD COLUMN staff_notes TEXT",
            "signature_name": "ALTER TABLE submissions ADD COLUMN signature_name TEXT",
            "family_status_note": "ALTER TABLE submissions ADD COLUMN family_status_note TEXT",
            "memorial_published": "ALTER TABLE submissions ADD COLUMN memorial_published INTEGER NOT NULL DEFAULT 0",
            "memorial_slug": "ALTER TABLE submissions ADD COLUMN memorial_slug TEXT",
            "progress_step": "ALTER TABLE submissions ADD COLUMN progress_step TEXT NOT NULL DEFAULT 'Submitted'",
        }
        for column, statement in required_columns.items():
            if column not in columns:
                db.execute(statement)

        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_submissions_portal_token ON submissions(portal_token)")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_submissions_memorial_slug ON submissions(memorial_slug)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_outbox_status ON integration_outbox(status, created_at)")

        demo_username = app.config["ADMIN_USERNAME"]
        existing_user = db.execute(
            "SELECT id FROM staff_users WHERE username = ?", (demo_username,)
        ).fetchone()
        if existing_user is None:
            db.execute(
                """
                INSERT INTO staff_users (username, password_hash, display_name, role, is_active, created_at)
                VALUES (?, ?, ?, 'admin', 1, ?)
                """,
                (
                    demo_username,
                    generate_password_hash(app.config["ADMIN_PASSWORD"]),
                    app.config["ADMIN_DISPLAY_NAME"],
                    now_iso(),
                ),
            )
        db.commit()


@app.context_processor
def inject_globals() -> dict[str, Any]:
    try:
        count = submission_count()
        counts = status_counts()
    except sqlite3.OperationalError:
        count = 0
        counts = {status: 0 for status in STATUS_OPTIONS}
    return {
        "submission_count": count,
        "status_counts": counts,
        "admin_logged_in": bool(session.get("admin_authenticated")),
        "status_options": STATUS_OPTIONS,
        "wizard_steps": WIZARD_STEPS,
        "current_staff_name": session.get("staff_display_name", ""),
        "current_staff_role": session.get("staff_role", ""),
        "portal_base_url": app.config["PORTAL_BASE_URL"],
        "main_site_base_url": app.config["MAIN_SITE_BASE_URL"],
    }


def submission_count() -> int:
    row = get_db().execute("SELECT COUNT(*) AS count FROM submissions").fetchone()
    return int(row["count"])


def status_counts() -> dict[str, int]:
    rows = get_db().execute("SELECT status, COUNT(*) AS count FROM submissions GROUP BY status").fetchall()
    counts = {status: 0 for status in STATUS_OPTIONS}
    for row in rows:
        counts[row["status"]] = int(row["count"])
    return counts


def current_staff() -> dict[str, Any]:
    return {
        "id": session.get("staff_user_id"),
        "username": session.get("staff_username"),
        "display_name": session.get("staff_display_name"),
        "role": session.get("staff_role"),
    }


def is_admin() -> bool:
    return bool(session.get("admin_authenticated"))


def require_admin() -> Response | None:
    if not is_admin():
        flash("Please sign in to view the office dashboard.", "error")
        return redirect(url_for("admin_login", next=request.path))
    return None


def require_webhook_secret() -> bool:
    provided = request.headers.get("X-Alterna-Webhook-Secret", "")
    return secrets.compare_digest(provided, app.config["OBITUARY_WEBHOOK_SECRET"])


def audit(action: str, actor_type: str, actor_name: str, submission_id: int | None = None, detail: dict[str, Any] | None = None) -> None:
    get_db().execute(
        """
        INSERT INTO audit_log (created_at, actor_type, actor_name, action, submission_id, detail_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            now_iso(),
            actor_type,
            actor_name,
            action,
            submission_id,
            json.dumps(detail or {}, ensure_ascii=False),
        ),
    )
    get_db().commit()


def queue_integration_event(event_type: str, submission_id: int | None, payload: dict[str, Any], target: str = "") -> None:
    get_db().execute(
        """
        INSERT INTO integration_outbox (created_at, event_type, status, target, submission_id, payload_json)
        VALUES (?, ?, 'queued', ?, ?, ?)
        """,
        (now_iso(), event_type, target, submission_id, json.dumps(payload, ensure_ascii=False)),
    )
    get_db().commit()


def fetch_submission(submission_id: int) -> sqlite3.Row | None:
    return get_db().execute("SELECT * FROM submissions WHERE id = ?", (submission_id,)).fetchone()


def fetch_submission_by_token(token: str) -> sqlite3.Row | None:
    return get_db().execute("SELECT * FROM submissions WHERE portal_token = ?", (token,)).fetchone()


def fetch_uploads(submission_id: int) -> list[sqlite3.Row]:
    return get_db().execute(
        "SELECT * FROM uploads WHERE submission_id = ? ORDER BY id DESC", (submission_id,)
    ).fetchall()


def fetch_upload(upload_id: int) -> sqlite3.Row | None:
    return get_db().execute("SELECT * FROM uploads WHERE id = ?", (upload_id,)).fetchone()


def fetch_messages(submission_id: int) -> list[sqlite3.Row]:
    return get_db().execute(
        "SELECT * FROM family_messages WHERE submission_id = ? ORDER BY datetime(created_at) ASC, id ASC",
        (submission_id,),
    ).fetchall()


def fetch_audit_log(limit: int = 100) -> list[sqlite3.Row]:
    return get_db().execute(
        "SELECT * FROM audit_log ORDER BY datetime(created_at) DESC, id DESC LIMIT ?", (limit,)
    ).fetchall()


def fetch_outbox(limit: int = 100) -> list[sqlite3.Row]:
    return get_db().execute(
        "SELECT * FROM integration_outbox ORDER BY datetime(created_at) DESC, id DESC LIMIT ?", (limit,)
    ).fetchall()


def save_uploaded_files(files: list[FileStorage], submission_id: int) -> None:
    upload_root = Path(app.config["UPLOAD_FOLDER"])
    upload_root.mkdir(parents=True, exist_ok=True)
    db = get_db()
    added_files: list[str] = []
    for file in files:
        if not file or not file.filename:
            continue
        if not allowed_file(file.filename):
            continue
        original = secure_filename(file.filename)
        stored = f"{submission_id}-{secrets.token_hex(8)}-{original}"
        file.save(upload_root / stored)
        db.execute(
            """
            INSERT INTO uploads (submission_id, original_filename, stored_filename, uploaded_at)
            VALUES (?, ?, ?, ?)
            """,
            (submission_id, original, stored, now_iso()),
        )
        added_files.append(original)
    db.commit()
    if added_files:
        audit("files_uploaded", "staff" if is_admin() else "family", current_staff().get("display_name") or "Family", submission_id, {"files": added_files})


def add_message(submission_id: int, sender_role: str, sender_name: str, message_text: str) -> None:
    db = get_db()
    db.execute(
        """
        INSERT INTO family_messages (submission_id, sender_role, sender_name, message_text, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            submission_id,
            sender_role,
            sender_name,
            multiline_compact(message_text),
            now_iso(),
        ),
    )
    db.execute(
        "UPDATE submissions SET updated_at = ? WHERE id = ?",
        (now_iso(), submission_id),
    )
    db.commit()
    audit("message_added", sender_role, sender_name, submission_id, {"preview": message_text[:120]})


def generate_obituary(form: dict[str, str]) -> str:
    first_name = form.get("preferred_name") or form.get("deceased_first_name") or "Your loved one"
    legal_name = " ".join(
        part for part in [form.get("deceased_first_name"), form.get("deceased_middle_name"), form.get("deceased_last_name")] if part
    ).strip()
    date_of_death = form.get("date_of_death") or "recently"
    place_of_death = form.get("place_of_death") or ""
    date_of_birth = form.get("date_of_birth") or ""
    occupation = form.get("occupation") or ""
    spouse = form.get("spouse_name") or ""
    children = form.get("children_details") or ""
    service_details = form.get("service_details") or ""
    charity = form.get("charity_requests") or ""
    family_message = form.get("family_message") or ""
    style = (form.get("obituary_style") or form.get("obituary_tone") or "simple announcement").strip().lower()
    if style == "no obituary":
        return ""

    intro = f"{first_name} passed away"
    if place_of_death:
        intro += f" in {place_of_death}"
    if date_of_death:
        intro += f" on {date_of_death}"
    if date_of_birth:
        intro += f", born {date_of_birth}"
    intro += "."

    details: list[str] = [intro]
    if occupation:
        details.append(f"{first_name} was known for a life of hard work and dedication as {occupation}.")
    if spouse:
        details.append(f"{first_name} will be deeply missed by {spouse}.")
    if children:
        details.append(f"Loved ones include: {children}.")
    if family_message:
        details.append(family_message)
    if service_details:
        details.append(f"Service information: {service_details}.")
    if charity:
        details.append(f"In lieu of flowers, the family asks that consideration be given to {charity}.")

    if style.startswith("celebration"):
        details.append(f"{first_name} leaves behind many stories, laughs, and memories that will continue to be shared.")
    elif style.startswith("traditional"):
        details.append("The family is grateful for the support and kindness shown during this time.")
    else:
        details.append("Arrangements are in care of Alterna Cremation.")

    if legal_name and legal_name != first_name:
        details.insert(0, legal_name)
    return "\n\n".join(part.strip() for part in details if part.strip())


def submission_dict_from_form(form: Any) -> dict[str, Any]:
    return {
        "case_reference": form.get("case_reference", "").strip() or generate_case_reference(),
        "intake_type": form.get("intake_type", "").strip(),
        "preplanning_for": form.get("preplanning_for", "").strip(),
        "family_name": form.get("family_name", "").strip(),
        "family_email": form.get("family_email", "").strip(),
        "family_phone": cleaned_phone(form.get("family_phone", "")),
        "relationship_to_deceased": form.get("relationship_to_deceased", "").strip(),
        "will_status": form.get("will_status", "").strip(),
        "executor_is_contact": form.get("executor_is_contact", "").strip(),
        "executor_name": form.get("executor_name", "").strip(),
        "executor_phone": cleaned_phone(form.get("executor_phone", "")),
        "executor_email": form.get("executor_email", "").strip(),
        "preferred_name": form.get("preferred_name", "").strip(),
        "family_message": multiline_compact(form.get("family_message", "")),
        "deceased_first_name": form.get("deceased_first_name", "").strip(),
        "deceased_middle_name": form.get("deceased_middle_name", "").strip(),
        "deceased_last_name": form.get("deceased_last_name", "").strip(),
        "deceased_gender": form.get("deceased_gender", "").strip(),
        "date_of_birth": form.get("date_of_birth", "").strip(),
        "date_of_death": form.get("date_of_death", "").strip(),
        "place_of_death": form.get("place_of_death", "").strip(),
        "birth_city": form.get("birth_city", "").strip(),
        "birth_region_country": form.get("birth_region_country", "").strip(),
        "citizenship": form.get("citizenship", "").strip(),
        "sin_last_four": form.get("sin_last_four", "").strip(),
        "marital_status": form.get("marital_status", "").strip(),
        "spouse_name": form.get("spouse_name", "").strip(),
        "children_details": multiline_compact(form.get("children_details", "")),
        "occupation": form.get("occupation", "").strip(),
        "usual_residence": form.get("usual_residence", "").strip(),
        "father_name": form.get("father_name", "").strip(),
        "mother_name": form.get("mother_name", "").strip(),
        "mother_maiden_name": form.get("mother_maiden_name", "").strip(),
        "informant_name": form.get("informant_name", "").strip(),
        "informant_email": form.get("informant_email", "").strip(),
        "informant_phone": cleaned_phone(form.get("informant_phone", "")),
        "informant_address": multiline_compact(form.get("informant_address", "")),
        "disposition_type": form.get("disposition_type", "").strip(),
        "obituary_style": form.get("obituary_style", "").strip(),
        "obituary_headline": form.get("obituary_headline", "").strip(),
        "obituary_text": multiline_compact(form.get("obituary_text", "")),
        "obituary_tone": form.get("obituary_tone", "").strip(),
        "service_details": multiline_compact(form.get("service_details", "")),
        "charity_requests": multiline_compact(form.get("charity_requests", "")),
        "photo_notes": multiline_compact(form.get("photo_notes", "")),
        "photo_deadline": form.get("photo_deadline", "").strip(),
        "signature_name": form.get("signature_name", "").strip(),
        "privacy_consent": 1 if form.get("privacy_consent") == "on" else 0,
    }


def public_memorial_payload(row: sqlite3.Row) -> dict[str, Any]:
    uploads = [
        {
            "id": int(upload["id"]),
            "filename": upload["original_filename"],
            "url": url_for("memorial_asset", slug=row["memorial_slug"], upload_id=upload["id"], _external=False),
        }
        for upload in fetch_uploads(int(row["id"]))
        if is_public_image(upload["original_filename"])
    ]
    return {
        "case_reference": row["case_reference"],
        "memorial_slug": row["memorial_slug"],
        "name": " ".join(part for part in [row["deceased_first_name"], row["deceased_middle_name"], row["deceased_last_name"]] if part),
        "preferred_name": row["preferred_name"],
        "date_of_birth": row["date_of_birth"],
        "date_of_death": row["date_of_death"],
        "headline": row["obituary_headline"],
        "obituary": row["obituary_text"] or row["obituary_generated"],
        "service_details": row["service_details"],
        "charity_requests": row["charity_requests"],
        "photos": uploads,
        "published": bool(row["memorial_published"]),
        "portal_url": f"{app.config['PORTAL_BASE_URL']}/family/{row['portal_token']}",
        "canonical_site_url": f"{app.config['MAIN_SITE_BASE_URL']}/obituaries/{row['memorial_slug']}",
    }


def upsert_submission(form_data: dict[str, Any], existing_row: sqlite3.Row | None = None) -> int:
    db = get_db()
    now = now_iso()

    obituary_text = form_data["obituary_text"]
    obituary_generated = ""
    if form_data.get("obituary_style") and not obituary_text:
        obituary_generated = generate_obituary(form_data)
        obituary_text = obituary_generated

    if existing_row is None:
        portal_token = make_portal_token()
        memorial_slug = make_memorial_slug(form_data["deceased_first_name"], form_data["deceased_last_name"])
        cursor = db.execute(
            """
            INSERT INTO submissions (
                created_at, updated_at, case_reference, family_name, family_email, family_phone,
                relationship_to_deceased, intake_type, preplanning_for, will_status, executor_is_contact, executor_name, executor_phone, executor_email, portal_token, preferred_name, family_message,
                deceased_first_name, deceased_middle_name, deceased_last_name, deceased_gender,
                date_of_birth, date_of_death, place_of_death, birth_city, birth_region_country,
                citizenship, sin_last_four, marital_status, spouse_name, children_details,
                occupation, usual_residence, father_name, mother_name, mother_maiden_name,
                informant_name, informant_email, informant_phone, informant_address,
                disposition_type, obituary_style, obituary_headline, obituary_text, obituary_generated,
                obituary_tone, service_details, charity_requests, photo_notes, photo_deadline,
                signature_name, privacy_consent, memorial_published, memorial_slug,
                status, progress_step, family_status_note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                now,
                form_data["case_reference"],
                form_data["family_name"],
                form_data["family_email"],
                form_data["family_phone"],
                form_data["relationship_to_deceased"],
                form_data["intake_type"],
                form_data["preplanning_for"],
                form_data["will_status"],
                form_data["executor_is_contact"],
                form_data["executor_name"],
                form_data["executor_phone"],
                form_data["executor_email"],
                portal_token,
                form_data["preferred_name"],
                form_data["family_message"],
                form_data["deceased_first_name"],
                form_data["deceased_middle_name"],
                form_data["deceased_last_name"],
                form_data["deceased_gender"],
                form_data["date_of_birth"],
                form_data["date_of_death"],
                form_data["place_of_death"],
                form_data["birth_city"],
                form_data["birth_region_country"],
                form_data["citizenship"],
                form_data["sin_last_four"],
                form_data["marital_status"],
                form_data["spouse_name"],
                form_data["children_details"],
                form_data["occupation"],
                form_data["usual_residence"],
                form_data["father_name"],
                form_data["mother_name"],
                form_data["mother_maiden_name"],
                form_data["informant_name"],
                form_data["informant_email"],
                form_data["informant_phone"],
                form_data["informant_address"],
                form_data["disposition_type"],
                form_data["obituary_style"],
                form_data["obituary_headline"],
                obituary_text,
                obituary_generated,
                form_data["obituary_tone"],
                form_data["service_details"],
                form_data["charity_requests"],
                form_data["photo_notes"],
                form_data["photo_deadline"],
                form_data["signature_name"],
                form_data["privacy_consent"],
                0,
                memorial_slug,
                "New",
                "Submitted",
                "We have received your information and will review everything shortly.",
            ),
        )
        submission_id = int(cursor.lastrowid)
        db.commit()
        audit("submission_created", "family", form_data["family_name"] or "Family", submission_id, {"case_reference": form_data["case_reference"]})
        queue_integration_event(
            "family_portal_created",
            submission_id,
            {
                "case_reference": form_data["case_reference"],
                "family_name": form_data["family_name"],
                "family_email": form_data["family_email"],
                "portal_url": f"{app.config['PORTAL_BASE_URL']}/family/{portal_token}",
            },
            target="email-notification",
        )
        return submission_id

    db.execute(
        """
        UPDATE submissions SET
            updated_at = ?, case_reference = ?, family_name = ?, family_email = ?, family_phone = ?,
            relationship_to_deceased = ?, intake_type = ?, preplanning_for = ?, will_status = ?, executor_is_contact = ?, executor_name = ?, executor_phone = ?, executor_email = ?, preferred_name = ?, family_message = ?, deceased_first_name = ?,
            deceased_middle_name = ?, deceased_last_name = ?, deceased_gender = ?, date_of_birth = ?,
            date_of_death = ?, place_of_death = ?, birth_city = ?, birth_region_country = ?, citizenship = ?,
            sin_last_four = ?, marital_status = ?, spouse_name = ?, children_details = ?, occupation = ?,
            usual_residence = ?, father_name = ?, mother_name = ?, mother_maiden_name = ?,
            informant_name = ?, informant_email = ?, informant_phone = ?, informant_address = ?,
            disposition_type = ?, obituary_style = ?, obituary_headline = ?, obituary_text = ?,
            obituary_generated = ?, obituary_tone = ?, service_details = ?, charity_requests = ?,
            photo_notes = ?, photo_deadline = ?, signature_name = ?, privacy_consent = ?
        WHERE id = ?
        """,
        (
            now,
            form_data["case_reference"],
            form_data["family_name"],
            form_data["family_email"],
            form_data["family_phone"],
            form_data["relationship_to_deceased"],
            form_data["intake_type"],
            form_data["preplanning_for"],
            form_data["will_status"],
            form_data["executor_is_contact"],
            form_data["executor_name"],
            form_data["executor_phone"],
            form_data["executor_email"],
            form_data["preferred_name"],
            form_data["family_message"],
            form_data["deceased_first_name"],
            form_data["deceased_middle_name"],
            form_data["deceased_last_name"],
            form_data["deceased_gender"],
            form_data["date_of_birth"],
            form_data["date_of_death"],
            form_data["place_of_death"],
            form_data["birth_city"],
            form_data["birth_region_country"],
            form_data["citizenship"],
            form_data["sin_last_four"],
            form_data["marital_status"],
            form_data["spouse_name"],
            form_data["children_details"],
            form_data["occupation"],
            form_data["usual_residence"],
            form_data["father_name"],
            form_data["mother_name"],
            form_data["mother_maiden_name"],
            form_data["informant_name"],
            form_data["informant_email"],
            form_data["informant_phone"],
            form_data["informant_address"],
            form_data["disposition_type"],
            form_data["obituary_style"],
            form_data["obituary_headline"],
            obituary_text,
            obituary_generated,
            form_data["obituary_tone"],
            form_data["service_details"],
            form_data["charity_requests"],
            form_data["photo_notes"],
            form_data["photo_deadline"],
            form_data["signature_name"],
            form_data["privacy_consent"],
            int(existing_row["id"]),
        ),
    )
    db.commit()
    audit("submission_updated", "family" if not is_admin() else "staff", current_staff().get("display_name") or form_data["family_name"] or "Family", int(existing_row["id"]), {"case_reference": form_data["case_reference"]})
    return int(existing_row["id"])


def validate_submission(form_data: dict[str, Any]) -> list[str]:
    return []


def authenticate_staff(username: str, password: str) -> sqlite3.Row | None:
    row = get_db().execute(
        "SELECT * FROM staff_users WHERE username = ? AND is_active = 1", (username,)
    ).fetchone()
    if row is None:
        return None
    if check_password_hash(row["password_hash"], password):
        return row
    return None


@app.route("/healthz")
def healthz() -> Response:
    return jsonify({"ok": True, "service": "alterna-family-portal", "time": now_iso()})


@app.route("/readyz")
def readyz() -> Response:
    try:
        db = get_db()
        db.execute("SELECT 1").fetchone()
        uploads_ready = Path(app.config["UPLOAD_FOLDER"]).exists()
        return jsonify({"ok": True, "database": True, "uploads": uploads_ready})
    except sqlite3.Error as exc:
        return jsonify({"ok": False, "database": False, "error": str(exc)}), 503


@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.route("/submit", methods=["GET", "POST"])
def submit() -> Response | str:
    if request.method == "POST":
        form_data = submission_dict_from_form(request.form)
        missing = validate_submission(form_data)
        if missing:
            flash(f"Please complete the required fields: {', '.join(missing)}.", "error")
            return render_template("submit.html", form_data=request.form)
        try:
            submission_id = upsert_submission(form_data)
            save_uploaded_files(request.files.getlist("memorial_files"), submission_id)
            submission = fetch_submission(submission_id)
            flash("Thank you. Your information has been received.", "success")
            return redirect(url_for("thank_you", token=submission["portal_token"]))
        except Exception:
            app.logger.exception("Family intake submission failed")
            flash("Something went wrong while saving this test submission. Please try again.", "error")
            return render_template("submit.html", form_data=request.form), 200

    return render_template("submit.html", form_data={})


@app.route("/thank-you")
def thank_you() -> str:
    token = request.args.get("token", "")
    row = fetch_submission_by_token(token) if token else None
    return render_template("thank_you.html", row=row)


@app.route("/family/<token>", methods=["GET", "POST"])
def family_portal(token: str) -> Response | str:
    row = fetch_submission_by_token(token)
    if row is None:
        flash("That family portal could not be found.", "error")
        return redirect(url_for("index"))

    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "save_form":
            form_data = submission_dict_from_form(request.form)
            missing = validate_submission(form_data)
            if missing:
                flash(f"Please complete the required fields: {', '.join(missing)}.", "error")
            else:
                try:
                    upsert_submission(form_data, row)
                    save_uploaded_files(request.files.getlist("memorial_files"), int(row["id"]))
                    flash("Your information has been saved.", "success")
                except Exception:
                    app.logger.exception("Family portal save failed")
                    flash("Something went wrong while saving this test submission. Please try again.", "error")
        elif action == "message":
            message = request.form.get("message_text", "").strip()
            sender_name = request.form.get("sender_name", row["family_name"]).strip() or row["family_name"]
            if message:
                add_message(int(row["id"]), "family", sender_name, message)
                queue_integration_event(
                    "family_message_received",
                    int(row["id"]),
                    {"case_reference": row["case_reference"], "from": sender_name, "message_preview": message[:160]},
                    target="staff-notification",
                )
                flash("Your message was sent to Alterna.", "success")
            else:
                flash("Please enter a message before sending.", "error")
        return redirect(url_for("family_portal", token=token))

    row = fetch_submission_by_token(token)
    uploads = fetch_uploads(int(row["id"]))
    messages = fetch_messages(int(row["id"]))
    return render_template("family_portal.html", row=row, uploads=uploads, messages=messages)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login() -> str | Response:
    next_url = request.args.get("next") or url_for("admin")
    if request.method == "POST":
        username = request.form.get("username", "").strip() or app.config["ADMIN_USERNAME"]
        password = request.form.get("password", "")
        user = authenticate_staff(username, password)
        if user is not None:
            session["admin_authenticated"] = True
            session["staff_user_id"] = int(user["id"])
            session["staff_username"] = user["username"]
            session["staff_display_name"] = user["display_name"]
            session["staff_role"] = user["role"]
            get_db().execute(
                "UPDATE staff_users SET last_login_at = ? WHERE id = ?", (now_iso(), int(user["id"]))
            )
            get_db().commit()
            audit("staff_login", "staff", user["display_name"], None, {"username": user["username"]})
            flash("Signed in successfully.", "success")
            return redirect(request.form.get("next") or url_for("admin"))
        flash("Incorrect username or password.", "error")
    return render_template("login.html", next_url=next_url)


@app.route("/admin/logout")
def admin_logout() -> Response:
    if session.get("staff_display_name"):
        audit("staff_logout", "staff", session.get("staff_display_name", "Staff"))
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("index"))


@app.route("/admin")
def admin() -> Response | str:
    auth = require_admin()
    if auth is not None:
        return auth

    status_filter = request.args.get("status", "All")
    search = request.args.get("q", "").strip()
    db = get_db()
    query = """
        SELECT id, created_at, updated_at, case_reference, family_name, family_email,
               deceased_first_name, deceased_last_name, status, progress_step, memorial_published,
               portal_token, memorial_slug
        FROM submissions
        WHERE 1 = 1
    """
    params: list[Any] = []
    if status_filter != "All":
        query += " AND status = ?"
        params.append(status_filter)
    if search:
        like = f"%{search}%"
        query += " AND (case_reference LIKE ? OR family_name LIKE ? OR family_email LIKE ? OR deceased_first_name LIKE ? OR deceased_last_name LIKE ?)"
        params.extend([like, like, like, like, like])
    query += " ORDER BY datetime(updated_at) DESC, id DESC"
    rows = db.execute(query, params).fetchall()

    users = db.execute(
        "SELECT username, display_name, role, last_login_at FROM staff_users WHERE is_active = 1 ORDER BY username"
    ).fetchall()
    outbox = fetch_outbox(10)
    audit_rows = fetch_audit_log(10)
    return render_template("admin.html", rows=rows, active_status=status_filter, search=search, users=users, outbox=outbox, audit_rows=audit_rows)


@app.route("/admin/submission/<int:submission_id>")
def submission_detail(submission_id: int) -> Response | str:
    auth = require_admin()
    if auth is not None:
        return auth
    row = fetch_submission(submission_id)
    if row is None:
        flash("That submission could not be found.", "error")
        return redirect(url_for("admin"))
    uploads = fetch_uploads(submission_id)
    messages = fetch_messages(submission_id)
    return render_template("detail.html", row=row, uploads=uploads, messages=messages)


@app.route("/admin/submission/<int:submission_id>/update", methods=["POST"])
def update_submission(submission_id: int) -> Response:
    auth = require_admin()
    if auth is not None:
        return auth
    row = fetch_submission(submission_id)
    if row is None:
        flash("That submission could not be found.", "error")
        return redirect(url_for("admin"))

    status = request.form.get("status", row["status"])
    progress_step = request.form.get("progress_step", row["progress_step"])
    staff_notes = multiline_compact(request.form.get("staff_notes", row["staff_notes"] or ""))
    family_status_note = multiline_compact(
        request.form.get("family_status_note", row["family_status_note"] or "")
    )

    get_db().execute(
        """
        UPDATE submissions
        SET status = ?, progress_step = ?, staff_notes = ?, family_status_note = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            status,
            progress_step,
            staff_notes,
            family_status_note,
            now_iso(),
            submission_id,
        ),
    )
    get_db().commit()
    staff_name = current_staff().get("display_name") or "Alterna"
    audit("submission_status_updated", "staff", staff_name, submission_id, {"status": status, "progress_step": progress_step})
    queue_integration_event(
        "family_status_updated",
        submission_id,
        {
            "case_reference": row["case_reference"],
            "family_email": row["family_email"],
            "status": status,
            "progress_step": progress_step,
            "family_status_note": family_status_note,
        },
        target="family-email-update",
    )
    flash("Submission updated.", "success")
    return redirect(url_for("submission_detail", submission_id=submission_id))


@app.route("/admin/submission/<int:submission_id>/message", methods=["POST"])
def admin_message(submission_id: int) -> Response:
    auth = require_admin()
    if auth is not None:
        return auth
    row = fetch_submission(submission_id)
    if row is None:
        flash("That submission could not be found.", "error")
        return redirect(url_for("admin"))
    message = request.form.get("message_text", "").strip()
    if not message:
        flash("Please enter a message before sending.", "error")
        return redirect(url_for("submission_detail", submission_id=submission_id))
    sender_name = current_staff().get("display_name") or "Alterna"
    add_message(submission_id, "staff", sender_name, message)
    queue_integration_event(
        "staff_message_posted",
        submission_id,
        {"case_reference": row["case_reference"], "family_email": row["family_email"], "message_preview": message[:160]},
        target="family-email-update",
    )
    flash("Message added to family thread.", "success")
    return redirect(url_for("submission_detail", submission_id=submission_id))


@app.route("/admin/submission/<int:submission_id>/publish", methods=["POST"])
def publish_submission(submission_id: int) -> Response:
    auth = require_admin()
    if auth is not None:
        return auth
    row = fetch_submission(submission_id)
    if row is None:
        flash("That submission could not be found.", "error")
        return redirect(url_for("admin"))
    publish = 1 if request.form.get("publish") == "1" else 0
    get_db().execute(
        "UPDATE submissions SET memorial_published = ?, updated_at = ? WHERE id = ?",
        (publish, now_iso(), submission_id),
    )
    get_db().commit()
    fresh_row = fetch_submission(submission_id)
    if publish:
        payload = public_memorial_payload(fresh_row)
        queue_integration_event(
            "obituary_publish_requested",
            submission_id,
            payload,
            target=f"{app.config['MAIN_SITE_BASE_URL']}/api/alternacremation/memorial-import",
        )
        audit("memorial_published", "staff", current_staff().get("display_name") or "Alterna", submission_id, {"slug": fresh_row["memorial_slug"]})
    else:
        audit("memorial_unpublished", "staff", current_staff().get("display_name") or "Alterna", submission_id, {"slug": fresh_row["memorial_slug"]})
    flash("Memorial page status updated.", "success")
    return redirect(url_for("submission_detail", submission_id=submission_id))


@app.route("/admin/submission/<int:submission_id>/summary.pdf")
def submission_summary_pdf(submission_id: int) -> Response:
    auth = require_admin()
    if auth is not None:
        return auth
    row = fetch_submission(submission_id)
    if row is None:
        flash("That submission could not be found.", "error")
        return redirect(url_for("admin"))

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    y = height - 48

    def draw_line(text: str, size: int = 11, leading: int = 15, bold: bool = False) -> None:
        nonlocal y
        font = "Helvetica-Bold" if bold else "Helvetica"
        pdf.setFont(font, size)
        max_width = width - 96
        words = text.split()
        line = ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if stringWidth(candidate, font, size) <= max_width:
                line = candidate
            else:
                pdf.drawString(48, y, line)
                y -= leading
                line = word
                if y < 72:
                    pdf.showPage()
                    y = height - 48
                    pdf.setFont(font, size)
        if line:
            pdf.drawString(48, y, line)
            y -= leading
        if y < 72:
            pdf.showPage()
            y = height - 48

    draw_line("Alterna Family Portal Case Summary", size=16, leading=20, bold=True)
    draw_line(f"Case reference: {row['case_reference']}", bold=True)
    draw_line(f"Deceased: {row['deceased_first_name']} {row['deceased_last_name']}")
    draw_line(f"Family contact: {row['family_name']} | {row['family_email']} | {row['family_phone']}")
    draw_line(f"Status: {row['status']} | Progress: {row['progress_step']}")
    draw_line("")

    sections = [
        ("Vital statistics", [
            f"Preferred name: {row['preferred_name'] or ''}",
            f"Date of birth: {row['date_of_birth'] or ''}",
            f"Date of death: {row['date_of_death'] or ''}",
            f"Place of death: {row['place_of_death'] or ''}",
            f"Birth city: {row['birth_city'] or ''}",
            f"Birth province/country: {row['birth_region_country'] or ''}",
            f"Citizenship: {row['citizenship'] or ''}",
            f"Marital status: {row['marital_status'] or ''}",
            f"Spouse: {row['spouse_name'] or ''}",
            f"Children: {row['children_details'] or ''}",
            f"Father: {row['father_name'] or ''}",
            f"Mother: {row['mother_name'] or ''}",
            f"Mother maiden: {row['mother_maiden_name'] or ''}",
        ]),
        ("Informant", [
            f"Name: {row['informant_name'] or ''}",
            f"Email: {row['informant_email'] or ''}",
            f"Phone: {row['informant_phone'] or ''}",
            f"Address: {row['informant_address'] or ''}",
        ]),
        ("Obituary", [row['obituary_text'] or row['obituary_generated'] or 'No obituary draft provided.']),
        ("Internal notes", [row['staff_notes'] or 'No staff notes yet.']),
    ]
    for title, lines in sections:
        draw_line(title, size=13, leading=18, bold=True)
        for line in lines:
            for paragraph in str(line).splitlines() or [""]:
                draw_line(paragraph or " ")
        draw_line(" ")

    pdf.save()
    buffer.seek(0)
    filename = f"alterna-case-{submission_id}.pdf"
    return Response(
        buffer.read(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/admin/export.csv")
def export_csv() -> Response:
    auth = require_admin()
    if auth is not None:
        return auth
    db = get_db()
    rows = db.execute("SELECT * FROM submissions ORDER BY id DESC").fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    headers = [desc[0] for desc in db.execute("SELECT * FROM submissions LIMIT 1").description]
    writer.writerow(headers)
    for row in rows:
        writer.writerow([row[h] for h in headers])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=alterna-submissions.csv"},
    )


@app.route("/admin/export-vital.csv")
def export_vital_csv() -> Response:
    auth = require_admin()
    if auth is not None:
        return auth
    rows = get_db().execute(
        """
        SELECT case_reference, deceased_first_name, deceased_middle_name, deceased_last_name,
               date_of_birth, date_of_death, birth_city, birth_region_country, citizenship,
               father_name, mother_name, mother_maiden_name, informant_name, informant_email,
               informant_phone, informant_address
        FROM submissions ORDER BY id DESC
        """
    ).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(rows[0].keys() if rows else [
        "case_reference", "deceased_first_name", "deceased_middle_name", "deceased_last_name",
        "date_of_birth", "date_of_death", "birth_city", "birth_region_country", "citizenship",
        "father_name", "mother_name", "mother_maiden_name", "informant_name", "informant_email",
        "informant_phone", "informant_address"
    ])
    for row in rows:
        writer.writerow(list(row))
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=alterna-vital-statistics.csv"},
    )


@app.route("/admin/integrations/outbox.json")
def integration_outbox_json() -> Response:
    auth = require_admin()
    if auth is not None:
        return auth
    rows = [dict(row) | {"payload": json.loads(row["payload_json"])} for row in fetch_outbox(100)]
    return jsonify(rows)


@app.route("/uploads/<path:filename>")
def uploaded_file(filename: str) -> Response:
    auth = require_admin()
    if auth is not None:
        return auth
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=True)


@app.route("/memorial-assets/<slug>/<int:upload_id>")
def memorial_asset(slug: str, upload_id: int) -> Response:
    row = get_db().execute(
        "SELECT id FROM submissions WHERE memorial_slug = ? AND memorial_published = 1", (slug,)
    ).fetchone()
    if row is None:
        return Response(status=404)
    upload = fetch_upload(upload_id)
    if upload is None or int(upload["submission_id"]) != int(row["id"]):
        return Response(status=404)
    return send_from_directory(app.config["UPLOAD_FOLDER"], upload["stored_filename"])


@app.route("/memorial/<slug>")
def memorial_page(slug: str) -> Response | str:
    row = get_db().execute(
        "SELECT * FROM submissions WHERE memorial_slug = ? AND memorial_published = 1", (slug,)
    ).fetchone()
    if row is None:
        flash("That memorial page is not available.", "error")
        return redirect(url_for("index"))
    uploads = fetch_uploads(int(row["id"]))
    return render_template("memorial.html", row=row, uploads=uploads)


@app.route("/api/memorial/<slug>.json")
def memorial_json(slug: str) -> Response:
    row = get_db().execute(
        "SELECT * FROM submissions WHERE memorial_slug = ? AND memorial_published = 1", (slug,)
    ).fetchone()
    if row is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(public_memorial_payload(row))


@app.route("/api/webhooks/obituary-published", methods=["POST"])
def obituary_webhook_ack() -> Response:
    if not require_webhook_secret():
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    slug = data.get("memorial_slug") or data.get("slug")
    if not slug:
        return jsonify({"error": "missing_slug"}), 400
    row = get_db().execute("SELECT * FROM submissions WHERE memorial_slug = ?", (slug,)).fetchone()
    if row is None:
        return jsonify({"error": "not_found"}), 404
    queue_integration_event(
        "website_publish_acknowledged",
        int(row["id"]),
        data,
        target="portal-webhook",
    )
    audit("website_publish_acknowledged", "integration", "Website", int(row["id"]), data)
    return jsonify({"ok": True})


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
