# -*- coding: utf-8 -*-
"""
משלים לכרטיסים את מה שחסר במדריך: כתובת, שעות פתיחה, תמונה וקואורדינטות.
שני מקורות חינמיים, בלי מפתח ובלי הרשמה:
  1. Google Maps דרך דפדפן (Playwright) — כתובת, שעות, תמונה, קואורדינטות
  2. OpenStreetMap Nominatim — קואורדינטות למי שכבר יש לו כתובת
"""
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

import requests

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

DATA_PATH = Path(__file__).parent / "docs" / "data.json"
NOT_SET = "לא צוין"
BATCH = int(sys.argv[1]) if len(sys.argv) > 1 else 40
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

# וינה בלבד — כל תשובה שלא מצביעה על וינה נפסלת
VIENNA_RE = re.compile(r"\b(wien|vienna)\b|\b1\d{3}\b", re.I)
DISTRICT_NAMES = {
    1: "Innere Stadt", 2: "Leopoldstadt", 3: "Landstraße", 4: "Wieden",
    5: "Margareten", 6: "Mariahilf", 7: "Neubau", 8: "Josefstadt",
    9: "Alsergrund", 10: "Favoriten", 11: "Simmering", 12: "Meidling",
    13: "Hietzing", 14: "Penzing", 15: "Rudolfsheim-Fünfhaus",
    16: "Ottakring", 17: "Hernals", 18: "Währing", 19: "Döbling",
    20: "Brigittenau", 21: "Floridsdorf", 22: "Donaustadt", 23: "Liesing",
}


def normalize_postcode(address):
    """הכתובת האוסטרית נכתבת לפעמים A-1010 או A1010 — מיישרים ל-1010."""
    return re.sub(r"\bA-?(1\d{3})\b", r"\1", address or "")


def district_of(address):
    m = re.search(r"\b1(\d{2})0\b", normalize_postcode(address))
    if m:
        num = int(m.group(1))
        if 1 <= num <= 23:
            return num, DISTRICT_NAMES.get(num, NOT_SET)
    return None, NOT_SET


# ----------------------------------------------------------------- Nominatim
def geocode(address, cache):
    """קואורדינטות מ-OpenStreetMap. שנייה בין בקשות, כמו שהם מבקשים."""
    q = f"{normalize_postcode(address)}, Vienna, Austria"
    if q in cache:
        return cache[q]
    try:
        r = requests.get("https://nominatim.openstreetmap.org/search",
                         params={"q": q, "format": "json", "limit": 1,
                                 "countrycodes": "at"},
                         headers={"User-Agent": "timeout-vienna-personal/1.0"},
                         timeout=25)
        res = r.json()
        coords = [float(res[0]["lat"]), float(res[0]["lon"])] if res else None
    except Exception:
        coords = None
    cache[q] = coords
    time.sleep(1.1)
    return coords


# --------------------------------------------------------------- Google Maps
def scrape_place(page, name):
    """מחפש מקום בגוגל מפות ומחזיר מה שנמצא."""
    url = ("https://www.google.com/maps/search/" +
           urllib.parse.quote(f"{name}, Vienna, Austria") + "?hl=en&gl=at")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3500)

    # אם התקבלה רשימת תוצאות — נכנסים לראשונה
    try:
        h1 = page.locator("h1").first.inner_text(timeout=4000).strip()
    except Exception:
        h1 = ""
    if h1.lower() in ("results", "תוצאות"):
        try:
            page.locator("a.hfpxzc").first.click(timeout=6000)
            page.wait_for_timeout(3500)
        except Exception:
            return None

    out = {}
    try:
        out["fixed_name"] = page.locator("h1").first.inner_text(timeout=4000).strip()
    except Exception:
        return None

    # כתובת
    try:
        btn = page.locator('button[data-item-id="address"]').first
        out["address"] = btn.get_attribute("aria-label").split(":", 1)[-1].strip()
    except Exception:
        out["address"] = None

    # קואורדינטות — קודם מהמזהה המדויק שבכתובת ה-URL
    u = page.url
    m = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", u) or \
        re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", u)
    out["coords"] = [float(m.group(1)), float(m.group(2))] if m else None

    # שעות פתיחה — פותחים את טבלת השבוע ומרכיבים שורה קריאה
    out["hours"] = None
    try:
        page.locator('[aria-label*="Show open hours for the week"], '
                     'button[data-item-id="oh"]').first.click(timeout=4000)
        page.wait_for_timeout(1200)
    except Exception:
        pass
    try:
        rows = page.locator('table tr').all()[:7]
        parts = []
        for row in rows:
            cells = [c.strip() for c in row.inner_text(timeout=2000).split("	") if c.strip()]
            if len(cells) >= 2:
                parts.append(f"{cells[0][:3]} {cells[1]}")
        if parts:
            out["hours"] = " · ".join(parts)
    except Exception:
        pass

    # תמונה — רק תמונות מקום אמיתיות, לא אווטארים
    try:
        src = page.locator('button[jsaction*="heroHeaderImage"] img, '
                           'img[decoding="async"]').first.get_attribute("src", timeout=3000)
        if src and "/gps-proxy/" not in src and "/a-/" not in src and "/a/AC" not in src:
            out["photo"] = re.sub(r"=w\d+-h\d+.*$", "=w800-h500", src)
        else:
            out["photo"] = None
    except Exception:
        out["photo"] = None

    return out


def main():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    cards = data["cards"]
    cache = data.setdefault("geocache", {})

    todo = [c for c in cards
            if c.get("address") == NOT_SET or c.get("hours") == NOT_SET
            or not c.get("lat") or not c.get("photo")][:BATCH]
    print(f"{len(todo)} כרטיסים להשלמה מתוך {len(cards)}")

    if todo:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--lang=en-GB"])
            ctx = browser.new_context(user_agent=UA, locale="en-GB",
                                      viewport={"width": 1360, "height": 900})
            page = ctx.new_page()
            for i, card in enumerate(todo, 1):
                try:
                    got = scrape_place(page, card["name"])
                except Exception as e:
                    print(f"  {i:2d}. {card['name'][:34]:34s} שגיאה: {str(e)[:40]}")
                    continue
                if not got:
                    print(f"  {i:2d}. {card['name'][:34]:34s} לא נמצא")
                    continue

                addr = got.get("address") or ""
                if addr and not VIENNA_RE.search(addr):
                    print(f"  {i:2d}. {card['name'][:34]:34s} נפסל — לא בווינה ({addr[:30]})")
                    continue

                marks = []
                if addr and card.get("address") == NOT_SET:
                    card["address"] = addr
                    card["district"], card["district_name"] = district_of(addr)
                    marks.append("כתובת")
                if got.get("hours") and card.get("hours") == NOT_SET:
                    card["hours"] = got["hours"]
                    marks.append("שעות")
                if got.get("coords") and not card.get("lat"):
                    card["lat"], card["lon"] = got["coords"]
                    marks.append("מיקום")
                if got.get("photo") and not card.get("photo"):
                    card["photo"] = got["photo"]
                    marks.append("תמונה")
                if marks:
                    card["enriched_by"] = "google"
                print(f"  {i:2d}. {card['name'][:34]:34s} {', '.join(marks) or 'אין חדש'}")
                time.sleep(1.5)
            browser.close()

    # מי שיש לו כתובת ועדיין אין מיקום — דרך OpenStreetMap
    missing = [c for c in cards if c.get("address") != NOT_SET and not c.get("lat")]
    if missing:
        print(f"\nגאוקודינג ל-{len(missing)} מקומות דרך OpenStreetMap")
        for c in missing:
            coords = geocode(c["address"], cache)
            if coords:
                c["lat"], c["lon"] = coords
                print(f"  ✓ {c['name'][:40]}")

    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    withc = sum(1 for c in cards if c.get("lat"))
    witha = sum(1 for c in cards if c.get("address") != NOT_SET)
    print(f"\nסיכום: {witha}/{len(cards)} עם כתובת, {withc}/{len(cards)} עם מיקום במפה")


if __name__ == "__main__":
    main()
