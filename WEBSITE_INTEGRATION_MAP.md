# Website integration map for AlternaCremation.ca

This document maps what the portal publishes to what the public website should render.

## Portal source endpoint

Each published memorial is available at:

`GET /api/memorial/<slug>.json`

## Suggested field mapping

| Portal JSON field | Website use |
|---|---|
| `memorial_slug` | obituary URL slug |
| `name` | obituary title |
| `preferred_name` | optional display subtitle |
| `date_of_birth` | life dates line |
| `date_of_death` | life dates line |
| `headline` | teaser or page heading |
| `obituary` | obituary body |
| `service_details` | service info block |
| `charity_requests` | donation or memorial gift block |
| `photos[]` | obituary gallery or hero image |
| `canonical_site_url` | public canonical URL |

## Example website rendering order

1. Name
2. Life dates
3. Headline, if present
4. Main obituary text
5. Service details
6. Charity requests
7. Photo gallery

## Example JSON shape

```json
{
  "memorial_slug": "jane-smith-a1b2c3",
  "name": "Jane Smith",
  "preferred_name": "Jane",
  "date_of_birth": "1942-05-01",
  "date_of_death": "2026-03-10",
  "headline": "In loving memory",
  "obituary": "Jane lived well and was deeply loved.",
  "service_details": "Private family gathering.",
  "charity_requests": "CancerCare Manitoba",
  "photos": [
    {
      "id": 7,
      "filename": "jane.jpg",
      "url": "/memorial-assets/jane-smith-a1b2c3/7"
    }
  ],
  "published": true,
  "portal_url": "https://portal.alternacremation.ca/family/example-token",
  "canonical_site_url": "https://www.alternacremation.ca/obituaries/jane-smith-a1b2c3"
}
```

## Publish acknowledgement

Once the website has imported the obituary successfully, it should POST back to:

`POST /api/webhooks/obituary-published`

Header:
- `X-Alterna-Webhook-Secret: <shared secret>`

Suggested payload:

```json
{
  "memorial_slug": "jane-smith-a1b2c3",
  "site_status": "published",
  "site_url": "https://www.alternacremation.ca/obituaries/jane-smith-a1b2c3"
}
```

## Recommended website-side rules

- do not publish unless `published` is true
- prefer `preferred_name` in the page intro, but keep legal `name` as the page title
- store the imported slug so republishing updates the same obituary instead of creating duplicates
- cache images after import so the site does not rely forever on portal file serving
