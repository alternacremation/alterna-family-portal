from __future__ import annotations

import html
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PORTAL_BASE = os.environ.get("PORTAL_BASE", "http://127.0.0.1:5000")
OUTPUT_DIR = Path(os.environ.get("IMPORT_OUTPUT_DIR", "./website_import_output"))
WEBHOOK_SECRET = os.environ.get("OBITUARY_WEBHOOK_SECRET", "demo-obituary-webhook")


def sanitize_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug or "memorial"



def safe_text(value: Any) -> str:
    return html.escape(str(value or "").strip())



def format_life_dates(date_of_birth: str | None, date_of_death: str | None) -> str:
    left = (date_of_birth or "").strip()
    right = (date_of_death or "").strip()
    if left and right:
        return f"{left} to {right}"
    return left or right or ""



def split_paragraphs(value: str | None) -> list[str]:
    text = (value or "").strip()
    if not text:
        return []
    parts = [segment.strip() for segment in re.split(r"\n\s*\n", text) if segment.strip()]
    if parts:
        return parts
    return [text]



def build_listing_record(payload: dict[str, Any]) -> dict[str, Any]:
    slug = sanitize_slug(payload.get("memorial_slug") or payload.get("name") or "memorial")
    return {
        "slug": slug,
        "title": payload.get("name") or "Memorial",
        "preferred_name": payload.get("preferred_name") or payload.get("name") or "Memorial",
        "life_dates": format_life_dates(payload.get("date_of_birth"), payload.get("date_of_death")),
        "headline": payload.get("headline") or "",
        "obituary": payload.get("obituary") or "",
        "service_details": payload.get("service_details") or "",
        "charity_requests": payload.get("charity_requests") or "",
        "photos": payload.get("photos") or [],
        "canonical_site_url": payload.get("canonical_site_url") or "",
        "published": bool(payload.get("published")),
    }



def render_memorial_html(payload: dict[str, Any]) -> str:
    record = build_listing_record(payload)
    name = safe_text(record["title"])
    preferred_name = safe_text(record["preferred_name"])
    life_dates = safe_text(record["life_dates"])
    headline = safe_text(record["headline"])

    paragraphs = "\n".join(
        f"        <p>{safe_text(paragraph)}</p>" for paragraph in split_paragraphs(record["obituary"])
    ) or "        <p>No obituary text has been published yet.</p>"

    gallery = []
    for photo in record["photos"]:
        filename = safe_text(photo.get("filename") or "Photo")
        url = safe_text(photo.get("site_cached_url") or photo.get("cached_path") or photo.get("url") or "")
        if url:
            gallery.append(
                "\n".join(
                    [
                        '        <figure class="memorial-photo">',
                        f'          <img src="{url}" alt="{filename}">',
                        f'          <figcaption>{filename}</figcaption>',
                        "        </figure>",
                    ]
                )
            )
    gallery_html = "\n".join(gallery) or "        <p class=\"muted\">No memorial photos published.</p>"

    service_block = ""
    if record["service_details"]:
        service_block = (
            "\n    <section class=\"memorial-section\">\n"
            "      <h2>Service details</h2>\n"
            f"      <p>{safe_text(record['service_details'])}</p>\n"
            "    </section>"
        )

    charity_block = ""
    if record["charity_requests"]:
        charity_block = (
            "\n    <section class=\"memorial-section\">\n"
            "      <h2>Memorial donations</h2>\n"
            f"      <p>{safe_text(record['charity_requests'])}</p>\n"
            "    </section>"
        )

    canonical_url = safe_text(record["canonical_site_url"])
    canonical_tag = f'  <link rel="canonical" href="{canonical_url}">\n' if canonical_url else ""

    intro_name = f"<p class=\"preferred-name\">Also known as {preferred_name}</p>" if preferred_name and preferred_name != name else ""
    headline_html = f"    <p class=\"headline\">{headline}</p>\n" if headline else ""

    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
{canonical_tag}  <title>{name} | Alterna Cremation Obituaries</title>
  <style>
    body {{ font-family: Arial, Helvetica, sans-serif; background: #f6f8fb; color: #243342; margin: 0; }}
    .container {{ max-width: 860px; margin: 0 auto; padding: 32px 20px 48px; }}
    .card {{ background: white; border-radius: 16px; padding: 28px; box-shadow: 0 8px 24px rgba(25, 40, 60, 0.08); }}
    .brand {{ color: #607d98; text-transform: uppercase; letter-spacing: 0.08em; font-size: 12px; margin-bottom: 10px; }}
    h1 {{ margin: 0; font-size: 38px; line-height: 1.1; }}
    .life-dates {{ color: #607d98; font-size: 17px; margin: 10px 0 0; }}
    .preferred-name, .headline, .muted {{ color: #607d98; }}
    .memorial-section {{ margin-top: 28px; }}
    .memorial-section h2 {{ margin: 0 0 12px; font-size: 22px; }}
    .gallery {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; }}
    .memorial-photo {{ margin: 0; }}
    .memorial-photo img {{ width: 100%; height: 220px; object-fit: cover; border-radius: 12px; display: block; background: #edf1f6; }}
    .memorial-photo figcaption {{ font-size: 13px; color: #607d98; margin-top: 6px; }}
    p {{ line-height: 1.65; }}
  </style>
</head>
<body>
  <div class=\"container\">
    <div class=\"card\">
      <div class=\"brand\">Alterna Cremation</div>
      <h1>{name}</h1>
      <p class=\"life-dates\">{life_dates}</p>
      {intro_name}
{headline_html}    <section class=\"memorial-section\">
      <h2>Obituary</h2>
{paragraphs}
    </section>{service_block}{charity_block}
    <section class=\"memorial-section\">
      <h2>Photos</h2>
      <div class=\"gallery\">
{gallery_html}
      </div>
    </section>
    </div>
  </div>
</body>
</html>
"""



def fetch_memorial_payload(portal_base: str, slug: str) -> dict[str, Any]:
    url = f"{portal_base.rstrip('/')}/api/memorial/{sanitize_slug(slug)}.json"
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read().decode("utf-8"))



def download_photo(url: str, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response:
        destination.write_bytes(response.read())
    return destination.name



def cache_photo_assets(payload: dict[str, Any], output_dir: Path, portal_base: str) -> dict[str, Any]:
    photos = payload.get("photos") or []
    cached_photos: list[dict[str, Any]] = []
    photo_dir = output_dir / "assets"
    for index, photo in enumerate(photos, start=1):
        url = photo.get("url") or ""
        if not url:
            continue
        absolute_url = url if url.startswith("http") else f"{portal_base.rstrip('/')}{url}"
        suffix = Path(photo.get("filename") or f"photo-{index}.jpg").suffix or ".jpg"
        local_name = f"photo-{index}{suffix.lower()}"
        local_path = photo_dir / local_name
        try:
            download_photo(absolute_url, local_path)
            site_cached_url = f"assets/{local_name}"
        except urllib.error.URLError:
            site_cached_url = absolute_url
        cached = dict(photo)
        cached["cached_path"] = str(local_path)
        cached["site_cached_url"] = site_cached_url
        cached_photos.append(cached)

    payload = dict(payload)
    payload["photos"] = cached_photos
    return payload



def write_import_bundle(payload: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    record = build_listing_record(payload)
    slug = sanitize_slug(record["slug"])
    html_path = output_dir / f"{slug}.html"
    json_path = output_dir / f"{slug}.json"
    listing_index_path = output_dir / "obituary-listings.json"

    html_path.write_text(render_memorial_html(payload), encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    listings: list[dict[str, Any]] = []
    if listing_index_path.exists():
        try:
            listings = json.loads(listing_index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            listings = []

    updated = [item for item in listings if item.get("slug") != slug]
    updated.insert(0, {
        "slug": slug,
        "title": record["title"],
        "preferred_name": record["preferred_name"],
        "life_dates": record["life_dates"],
        "headline": record["headline"],
        "html_file": html_path.name,
    })
    listing_index_path.write_text(json.dumps(updated, indent=2, ensure_ascii=False), encoding="utf-8")

    return {"html": html_path, "json": json_path, "index": listing_index_path}



def acknowledge_publish(portal_base: str, slug: str, site_url: str) -> dict[str, Any]:
    url = f"{portal_base.rstrip('/')}/api/webhooks/obituary-published"
    payload = json.dumps(
        {"memorial_slug": sanitize_slug(slug), "site_status": "published", "site_url": site_url}
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Alterna-Webhook-Secret": WEBHOOK_SECRET,
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read().decode("utf-8"))



def main() -> None:
    slug = os.environ.get("MEMORIAL_SLUG", "example-slug")
    payload = fetch_memorial_payload(PORTAL_BASE, slug)
    enriched = cache_photo_assets(payload, OUTPUT_DIR / sanitize_slug(slug), PORTAL_BASE)
    paths = write_import_bundle(enriched, OUTPUT_DIR / sanitize_slug(slug))
    site_url = payload.get("canonical_site_url") or f"https://www.alternacremation.ca/obituaries/{sanitize_slug(slug)}"

    print("Imported memorial payload")
    print(json.dumps(enriched, indent=2, ensure_ascii=False))
    print()
    print("Generated website bundle")
    for key, path in paths.items():
        print(f"{key}: {path}")

    try:
        ack = acknowledge_publish(PORTAL_BASE, slug, site_url)
        print()
        print("Webhook acknowledgement result")
        print(json.dumps(ack, indent=2, ensure_ascii=False))
    except urllib.error.URLError as exc:
        print()
        print(f"Could not POST publish acknowledgement: {exc}")



if __name__ == "__main__":
    main()
