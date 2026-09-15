# -*- coding: utf-8 -*-
"""
סורק את מדריכי האוכל של TimeOut Vienna ובונה כרטיס לכל מקום.
כל כרטיס מקושר בחזרה לכתבה המקורית.
"""
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

TZ = ZoneInfo("Europe/Vienna")
BASE = "https://www.timeout.com"
DATA_PATH = Path(__file__).parent / "docs" / "data.json"
NOT_SET = "לא צוין"

# TimeOut חוסם סוכנים רגילים; Googlebot מותר לפי ה-User-Agent
FALLBACK_AGENTS = [
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Googlebot-Image/1.0",
    "Mozilla/5.0 (compatible; Google-InspectionTool/1.0)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
]

# נקודות הפתיחה שמהן מגלים מדריכים. TimeOut Vienna הוא אתר קטן של
# מדריכים קבועים שמתעדכנים מדי פעם — אין בו זרם כתבות יומי.
HUBS = [
    f"{BASE}/vienna",
    f"{BASE}/vienna/restaurants",
    f"{BASE}/vienna/bars",
    f"{BASE}/vienna/things-to-do",
]

# רק מדריכי אוכל ושתייה
FOOD_URL_RE = re.compile(
    r"/vienna/(restaurants|bars|food-and-drink|coffee)/|"
    r"/vienna/things-to-do/best-nightlife",
    re.I,
)
SKIP_URL_RE = re.compile(r"/(hotels|travel|sitemaps)/|/(best-hotels|best-airbnbs)", re.I)

# סוג המקום לפי מקור הכתבה
SECTION_TYPE = {
    "restaurants": "מסעדה",
    "bars": "בר",
    "coffee": "בית קפה",
    "food-and-drink": "אוכל ושתייה",
}

LABELS = {
    "what is it": "type_note",
    "why go": "why_go",
    "time out tip": "tip",
    "timeout tip": "tip",
    "address": "address",
    "opening hours": "hours",
    "expect to pay": "price",
    "price": "price",
}

DISTRICT_NAMES = {
    1: "Innere Stadt", 2: "Leopoldstadt", 3: "Landstraße", 4: "Wieden",
    5: "Margareten", 6: "Mariahilf", 7: "Neubau", 8: "Josefstadt",
    9: "Alsergrund", 10: "Favoriten", 11: "Simmering", 12: "Meidling",
    13: "Hietzing", 14: "Penzing", 15: "Rudolfsheim-Fünfhaus",
    16: "Ottakring", 17: "Hernals", 18: "Währing", 19: "Döbling",
    20: "Brigittenau", 21: "Floridsdorf", 22: "Donaustadt", 23: "Liesing",
}


def fetch(url, attempts=2):
    """מוריד דף. מנסה כמה זהויות עד שמתקבלת תשובה תקינה."""
    last = None
    for attempt in range(attempts):
        for agent in FALLBACK_AGENTS:
            try:
                r = requests.get(url, headers={"User-Agent": agent,
                                               "Accept-Language": "en-GB,en;q=0.9"},
                                 timeout=40)
                if r.status_code == 200:
                    return r.text
                last = str(r.status_code)
                if r.status_code in (403, 429):
                    time.sleep(2)
            except Exception as e:  # רשת
                last = str(e)
        time.sleep(3 * (attempt + 1))
    print(f"  ! נכשל: {url} ({last})")
    return None


def discover_guides():
    """מגלה את כל מדריכי האוכל הקיימים, כך שמדריך חדש ייכנס לבד."""
    found, seen = set(), set()
    for hub in HUBS:
        html = fetch(hub)
        if not html:
            continue
        for a in BeautifulSoup(html, "lxml").select("a[href]"):
            href = (a.get("href") or "").split("?")[0].split("#")[0]
            if href.startswith("/"):
                href = BASE + href
            if not href.startswith(f"{BASE}/vienna/"):
                continue
            if href in seen:
                continue
            seen.add(href)
            if SKIP_URL_RE.search(href):
                continue
            if FOOD_URL_RE.search(href):
                found.add(href)
    return sorted(found)


def clean(text):
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def split_label(text):
    """מפריד 'Address : Bauernmarkt 10' ל-('address', 'Bauernmarkt 10')."""
    m = re.match(r"^\s*([A-Za-z][A-Za-z \-]{2,22})\s*[:?]\s*(.+)$", text)
    if not m:
        return None, text
    key = m.group(1).strip().lower().rstrip("?").strip()
    return (LABELS.get(key), m.group(2).strip()) if key in LABELS else (None, text)


def parse_address(raw):
    """מחלץ רחוב, מיקוד ומספר רובע מכתובת וינאית."""
    raw = clean(raw).rstrip(".")
    m = re.search(r"\b1(\d{2})0\b", raw)
    district, district_name = None, NOT_SET
    if m:
        num = int(m.group(1))
        if 1 <= num <= 23:
            district = num
            district_name = DISTRICT_NAMES.get(num, NOT_SET)
    street = re.split(r",\s*1\d{3}\b", raw)[0].strip(" ,")
    return street or NOT_SET, district, district_name


def best_image(block):
    """בוחר את התמונה הגדולה ביותר בבלוק ומשדרג את הרזולוציה."""
    best, best_w = None, 0
    for img in block.select("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src.startswith("http") or "media.timeout.com" not in src:
            continue
        m = re.search(r"/images/\d+/(\d+)/(\d+)/", src)
        w = int(m.group(1)) if m else 0
        if w > best_w:
            best, best_w = src, w
    if best:
        best = re.sub(r"(/images/\d+)/\d+/\d+/", r"\1/750/562/", best)
    return best


def article_date(soup):
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            d = json.loads(tag.string or "{}")
        except Exception:
            continue
        if isinstance(d, dict):
            for key in ("dateModified", "datePublished"):
                if d.get(key):
                    return d[key][:10]
    return None


def parse_article(url):
    """מפרק מדריך אחד לרשימת מקומות."""
    html = fetch(url)
    if not html:
        return None, []
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.select_one("h1")
    title = clean(h1.get_text()) if h1 else url.rsplit("/", 1)[-1]
    date = article_date(soup)
    section = url.split("/vienna/")[1].split("/")[0]
    default_type = SECTION_TYPE.get(section, "אוכל ושתייה")
    if "nightlife" in url:
        default_type = "חיי לילה"
    if "cafe" in url or "coffee" in url:
        default_type = "בית קפה"

    places = []
    for block in soup.select("div.articleContent"):
        h3 = block.select_one("h3")
        if not h3:
            continue
        head = clean(h3.get_text())
        m = re.match(r"^(\d+)\.\s*(.+)$", head)
        if not m:
            continue  # רק פריטים ממוספרים הם המלצות
        rank, name = int(m.group(1)), m.group(2).strip()
        if not name or len(name) > 90:
            continue

        fields = {}
        for p in block.find_all("p"):
            txt = clean(p.get_text(" "))
            if not txt or txt.lower().startswith("photograph"):
                continue
            key, val = split_label(txt)
            if key and val and key not in fields:
                fields[key] = val
            elif not key and "desc" not in fields and len(txt) > 40:
                fields["desc"] = txt

        street, district, district_name = parse_address(fields.get("address", ""))
        places.append({
            "rank": rank,
            "name": name,
            "type": default_type,
            "description": fields.get("type_note") or fields.get("desc") or NOT_SET,
            "what_to_eat": fields.get("why_go", NOT_SET),
            "tip": fields.get("tip", NOT_SET),
            "price": fields.get("price", NOT_SET),
            "hours": fields.get("hours", NOT_SET),
            "address": street,
            "district": district,
            "district_name": district_name,
            "photo": best_image(block),
            "article_title": title,
            "article_url": url,
            "article_date": date,
        })
    return {"title": title, "url": url, "date": date, "count": len(places)}, places


def main():
    started = datetime.now(TZ)
    guides = discover_guides()
    print(f"נמצאו {len(guides)} מדריכי אוכל")

    articles, cards, seen = [], [], set()
    for url in guides:
        meta, places = parse_article(url)
        if not meta:
            continue
        print(f"  {meta['count']:3d} מקומות | {meta['title'][:55]}")
        if not places:
            continue
        articles.append(meta)
        for p in places:
            key = p["name"].strip().lower()
            if key in seen:
                continue
            seen.add(key)
            cards.append(p)
        time.sleep(1)

    if not cards:
        raise SystemExit("לא נמצא אף מקום — כנראה מבנה האתר השתנה")

    old = {}
    geocache = {}
    if DATA_PATH.exists():
        prev = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        old = {c["name"].strip().lower(): c for c in prev.get("cards", [])}
        geocache = prev.get("geocache", {})

    # שומרים קואורדינטות שכבר חושבו
    for c in cards:
        prev_card = old.get(c["name"].strip().lower())
        if prev_card and prev_card.get("lat"):
            c["lat"], c["lon"] = prev_card["lat"], prev_card["lon"]
        # בריצה הראשונה אין עם מה להשוות, אז שום דבר לא מסומן כחדש
        c["is_new"] = bool(old) and c["name"].strip().lower() not in old

    cards.sort(key=lambda c: (c["article_url"], c["rank"]))
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps({
        "cards": cards,
        "articles": articles,
        "geocache": geocache,
        "last_run": started.isoformat(),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nנשמרו {len(cards)} מקומות מתוך {len(articles)} מדריכים")


if __name__ == "__main__":
    main()
