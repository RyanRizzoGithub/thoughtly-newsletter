"""
Thoughtly newsletter scraper.

Pulls every issue from the Kajabi newsletter archive and writes data/posts.json,
which the static reader page (index.html) renders inside the branded app.

Runs daily from .github/workflows/scrape.yml. Safe by design:
  - Already-scraped issues are reused; only new ones (plus the newest few, to
    catch edits) are fetched.
  - If the scrape returns far fewer issues than we already have, it aborts
    without writing, so a Kajabi layout change can't wipe the archive.

Usage:
  python scripts/scrape.py            # normal incremental run
  python scripts/scrape.py --full     # re-fetch every issue
"""

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# ── Config ──────────────────────────────────────────────────────────────
BASE = "https://www.bethoughtly.com"
ARCHIVE = f"{BASE}/newsletters/thoughtly-notes"
OUT = Path(__file__).resolve().parent.parent / "data" / "posts.json"

REFRESH_NEWEST = 5        # always re-fetch the newest N issues (catches edits)
MAX_PAGES = 50            # pagination safety cap
DELAY = 0.5               # seconds between requests, be polite
MIN_KEEP_RATIO = 0.8      # abort if new count < 80% of existing count

HEADERS = {"User-Agent": "ThoughtlyNewsletterReader/1.0 (+https://www.bethoughtly.com)"}

# Kajabi selectors (verified against live pages, Nov 2026)
SEL_TITLE = "h1.newsletter-post-body__title"
SEL_DATE = ".newsletter-post-body__date"
SEL_BODY = ".newsletter-post-body__content .focus-writer-content"

# Tags kept in the cleaned body. Everything else is unwrapped (text kept).
ALLOWED_TAGS = {
    "p", "h2", "h3", "h4", "strong", "b", "em", "i", "u", "a", "ul", "ol",
    "li", "blockquote", "br", "hr", "img", "figure", "figcaption",
}
ALLOWED_ATTRS = {"a": {"href"}, "img": {"src", "alt"}}
DROP_TAGS = {"script", "style", "iframe", "form", "input", "button", "noscript", "svg"}


# ── Fetching ────────────────────────────────────────────────────────────
session = requests.Session()
session.headers.update(HEADERS)


def get(url):
    for attempt in range(3):
        try:
            r = session.get(url, timeout=20)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            if attempt == 2:
                raise
            print(f"  retry {attempt + 1} for {url}: {e}")
            time.sleep(2 * (attempt + 1))


# ── Parsing ─────────────────────────────────────────────────────────────
def parse_archive_page(html):
    """Return issue URLs from one archive page, in page order."""
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    for a in soup.select("a[href]"):
        href = urljoin(BASE, a["href"])
        if "/newsletters/thoughtly-notes/posts/" in href:
            href = href.split("#")[0].split("?")[0]
            if href not in urls:
                urls.append(href)
    return urls


def slug_from_url(url):
    return urlparse(url).path.rstrip("/").split("/")[-1]


def parse_date(text):
    text = " ".join(text.split())
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def clean_body(node):
    """Strip Kajabi markup down to simple, safe reading HTML."""
    for t in node.find_all(DROP_TAGS):
        t.decompose()
    for h1 in node.find_all("h1"):
        h1.decompose()  # title is rendered separately
    for t in node.find_all(True):
        if t.name not in ALLOWED_TAGS:
            t.unwrap()
            continue
        keep = ALLOWED_ATTRS.get(t.name, set())
        t.attrs = {k: v for k, v in t.attrs.items() if k in keep}
        if t.name == "a" and t.get("href", "").lower().startswith("javascript:"):
            t.unwrap()
    # remove empty paragraphs
    for p in node.find_all("p"):
        if not p.get_text(strip=True) and not p.find("img"):
            p.decompose()
    html = node.decode_contents().strip()
    return re.sub(r"\n\s*\n+", "\n", html)


def make_excerpt(text, limit=160):
    text = " ".join(text.split())
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(".,;:")
    return cut + "..."


def parse_post(html, url):
    soup = BeautifulSoup(html, "html.parser")

    title_el = soup.select_one(SEL_TITLE)
    og = soup.find("meta", property="og:title")
    title = title_el.get_text(strip=True) if title_el else (og["content"] if og else "")

    date_el = soup.select_one(SEL_DATE)
    date = parse_date(date_el.get_text()) if date_el else None

    body_el = soup.select_one(SEL_BODY)
    if not body_el or not title:
        raise ValueError(f"Unexpected layout (title or body missing): {url}")

    body_html = clean_body(body_el)
    text = BeautifulSoup(body_html, "html.parser").get_text(" ")
    words = len(text.split())

    return {
        "slug": slug_from_url(url),
        "title": title,
        "date": date,
        "url": url,
        "excerpt": make_excerpt(text),
        "minutes": max(1, round(words / 230)),
        "html": body_html,
    }


# ── Main ────────────────────────────────────────────────────────────────
def collect_urls():
    urls = []
    for page in range(1, MAX_PAGES + 1):
        html = get(f"{ARCHIVE}?page={page}")
        if html is None:
            break
        found = [u for u in parse_archive_page(html) if u not in urls]
        print(f"page {page}: {len(found)} new")
        if not found:
            break
        urls.extend(found)
        time.sleep(DELAY)
    return urls


def main():
    full = "--full" in sys.argv

    existing = {}
    if OUT.exists():
        for p in json.loads(OUT.read_text(encoding="utf-8")).get("posts", []):
            existing[p["slug"]] = p

    urls = collect_urls()
    if not urls:
        sys.exit("No issues found on the archive. Layout may have changed. Aborting.")

    refresh = set(slug_from_url(u) for u in urls[:REFRESH_NEWEST])
    posts = []
    for url in urls:
        slug = slug_from_url(url)
        if not full and slug in existing and slug not in refresh:
            posts.append(existing[slug])
            continue
        print(f"fetch {slug}")
        html = get(url)
        if html is None:
            print(f"  404, skipping {slug}")
            continue
        posts.append(parse_post(html, url))
        time.sleep(DELAY)

    if existing and len(posts) < len(existing) * MIN_KEEP_RATIO:
        sys.exit(
            f"Only {len(posts)} issues scraped vs {len(existing)} on file. "
            "Refusing to overwrite. Check the archive layout."
        )

    posts.sort(key=lambda p: (p["date"] or "", p["slug"]), reverse=True)
    payload = {"source": ARCHIVE, "count": len(posts), "posts": posts}
    new_json = json.dumps(payload, ensure_ascii=False, indent=1)

    if OUT.exists() and OUT.read_text(encoding="utf-8") == new_json:
        print("No changes.")
        return

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(new_json, encoding="utf-8")
    print(f"Wrote {len(posts)} issues to {OUT}")


if __name__ == "__main__":
    main()
