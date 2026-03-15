# Alterna Family Portal staging guide

This bundle is set up so a developer or hosting provider can stand up a staging copy of the portal without changing app code.

## What staging should look like

Recommended URLs:
- `portal-staging.alternacremation.ca` for the family portal
- `staging.alternacremation.ca` for website integration testing

Recommended goals:
- verify family intake flow end to end
- verify staff login and dashboard workflow
- verify published memorial JSON feed
- verify obituary handoff into the website staging environment
- verify backups, uploads, cookies, and HTTPS

## Fastest local staging run

1. Copy `.env.staging.example` to `.env.staging`
2. Replace the demo secrets
3. Run:

```bash
docker compose -f docker-compose.staging.yml up --build
```

Then open `http://127.0.0.1:8000`.

## Minimum production-minded checks before putting staff on staging

- use HTTPS only
- change the default admin password
- set a long `ALTERNA_APP_SECRET`
- make sure uploads persist across container restarts
- confirm `/healthz` and `/readyz` are reachable to your uptime monitor
- block indexing on staging with robots rules or auth at the proxy
- never reuse the staging database for production

## Suggested proxy setup

Put Caddy, Nginx, or your platform router in front of the app.

Proxy these endpoints:
- `/` family and admin portal
- `/memorial/<slug>` public memorial page
- `/api/memorial/<slug>.json` site integration feed
- `/api/webhooks/obituary-published` website callback
- `/healthz` and `/readyz` monitoring

## Suggested rollout order

1. Bring up portal staging
2. Test family submission on phone and desktop
3. Publish a memorial in staging
4. Have the website staging environment import the memorial JSON
5. Confirm website acknowledges publish with webhook callback
6. Test staff edits after publication
7. Freeze the field map and only then prepare production

## Things this package still does not do by itself

- real DNS
- real TLS certificates
- external email or SMS delivery
- website-side CMS publishing
- security review or privacy law review

Those pieces still need a real host or developer.
