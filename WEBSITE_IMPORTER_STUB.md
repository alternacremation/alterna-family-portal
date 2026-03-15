# Website importer stub for Alterna obituary listings

This bundle adds a website-side importer stub so a developer has both sides of the obituary handoff.

## What it does

The stub script:

- fetches a published memorial JSON payload from the portal
- caches memorial photos into a local website assets folder
- renders a static obituary HTML page in a simple Alterna-style layout
- updates a lightweight `obituary-listings.json` index file
- posts a publish acknowledgement back to the portal webhook

## Script

`python scripts/website_importer_stub.py`

## Environment variables

- `PORTAL_BASE`: portal base URL, default `http://127.0.0.1:5000`
- `MEMORIAL_SLUG`: memorial slug to import
- `IMPORT_OUTPUT_DIR`: where website files should be written
- `OBITUARY_WEBHOOK_SECRET`: shared secret for publish acknowledgement

## Output

For a slug like `jane-smith-a1b2c3`, the script writes:

- `website_import_output/jane-smith-a1b2c3/jane-smith-a1b2c3.html`
- `website_import_output/jane-smith-a1b2c3/jane-smith-a1b2c3.json`
- `website_import_output/jane-smith-a1b2c3/obituary-listings.json`
- `website_import_output/jane-smith-a1b2c3/assets/*`

## How a real developer would use this

1. Replace the static HTML write step with the real obituary CMS write step.
2. Replace the local `obituary-listings.json` with the website's real listings datastore.
3. Keep the photo caching pattern so memorial pages do not depend on long-term portal asset serving.
4. Keep the publish acknowledgement call so the portal can mark obituary handoff as completed.

## Why this is useful

It gives your developer a concrete reference implementation of:

- what fields arrive from the portal
- how they can be rendered on the public site
- how image caching should work
- how the acknowledgement loop should close
