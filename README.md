# Alterna Family Portal Production Starter

Flask production starter for Alterna Cremation that lets families submit vital statistics, obituary details, photos, and authorization online.

## Included in this build

- Alterna-branded family intake wizard
- Private family portal with progress tracking
- Vital statistics and informant collection
- Rules-based obituary draft helper
- Photo and document uploads
- Family and staff message thread
- Staff user accounts with hashed passwords
- Audit log for portal activity
- Staff dashboard with search, filters, and status updates
- One-click memorial publishing
- Public memorial page with public photo serving for published memorials
- Public memorial JSON feed for website integration
- Integration outbox for email or website publishing workflows
- Case summary PDF export
- Full CSV export and vital-statistics CSV export
- Dockerfile, Gunicorn config, environment templates, and staging compose file
- Health and readiness endpoints for monitoring
- Website integration map and sample import script

## Demo credentials

- Username: `admin`
- Password: `alterna-demo`

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then open `http://127.0.0.1:5000`.

## Production notes

This is now a stronger deployment starter, but it still is not a fully live production rollout. Before using real family data, it still needs:

- managed Postgres or another production database
- proper per-user staff account management UI
- encrypted backups
- privacy and legal review
- hosted file storage strategy
- real email or SMS delivery service
- real website-side memorial import endpoint
- penetration testing and operational hardening

## Integration approach for AlternaCremation.ca

When a memorial is published, the portal now creates a queued outbox event with memorial JSON. Your website can consume that event, or call the public feed directly:

- `GET /api/memorial/<slug>.json`
- `POST /api/webhooks/obituary-published` with `X-Alterna-Webhook-Secret`

That gives you a clean bridge between the family portal and your public obituary workflow.


## New deployment helpers in this version

- `docker-compose.staging.yml` for a quick staging stack
- `.env.staging.example` for portal staging variables
- `DEPLOY_STAGING.md` rollout checklist
- `WEBSITE_INTEGRATION_MAP.md` field map for obituary import
- `scripts/sample_memorial_import.py` tiny example website importer
- `GET /healthz` liveness endpoint
- `GET /readyz` readiness endpoint
