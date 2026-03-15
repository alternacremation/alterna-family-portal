from __future__ import annotations

import json
import os
import urllib.request

PORTAL_BASE = os.environ.get("PORTAL_BASE", "http://127.0.0.1:5000")
SLUG = os.environ.get("MEMORIAL_SLUG", "example-slug")

url = f"{PORTAL_BASE}/api/memorial/{SLUG}.json"
with urllib.request.urlopen(url) as response:
    payload = json.loads(response.read().decode("utf-8"))

print("Imported memorial payload")
print(json.dumps(payload, indent=2, ensure_ascii=False))
print()
print("Suggested website page fields")
print("Title:", payload.get("name"))
print("Intro name:", payload.get("preferred_name") or payload.get("name"))
print("Obituary:", payload.get("obituary"))
