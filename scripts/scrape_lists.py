#!/usr/bin/env python3
"""Pull Aug–Sep 2026 public lists from MTGGoldfish into data/decks.json."""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "decks.json"
UA = "Mozilla/5.0 (compatible; MTGDecklistsBot/1.0; +https://mtgdecklists.com)"
FORMATS = ("standard", "modern", "pioneer", "legacy", "vintage", "pauper", "commander")
PER_EVENT = 40
MAX_PAGES = 8
DATE_RANGE = "08/01/2026 - 09/07/2026"
SKIP_NAME = re.compile(r"\b(limited|draft|sealed|cube)\b", re.I)
ROW_RE = re.compile(
    r"<tr>\s*<td>(\d{4}-\d{2}-\d{2})</td>\s*<td>\s*<a href=\"/tournament/(\d+)\">([^<]+)</a>",
    re.I,
)


def fetch(url: str, retries: int = 4) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (404, 410):
                raise
            time.sleep(1.5 * (attempt + 1))
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last


def download_deck(deck_id: str):
    txt = fetch(f"https://www.mtggoldfish.com/deck/download/{deck_id}")
    main, side = [], []
    bucket = main
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            if main and bucket is main:
                bucket = side
            continue
        m = re.match(r"^(\d+)\s+(.+)$", line)
        if not m:
            continue
        bucket.append({"qty": int(m.group(1)), "name": m.group(2).strip()})
    return main, side


def parse_rows(html: str):
    rows = []
    for tr in re.findall(r"<tr[\s\S]*?</tr>", html, re.I):
        dids = re.findall(r'href="/deck/(\d+)', tr)
        if not dids:
            continue
        dm = re.search(r'href="/deck/\d+[^"]*"[^>]*>([^<]+)', tr)
        name = re.sub(r"\s+", " ", dm.group(1)).strip() if dm else "Unknown"
        texts = [re.sub(r"<[^>]+>", "", t).strip() for t in re.findall(r"<td[^>]*>([\s\S]*?)</td>", tr)]
        place = texts[0] if texts else ""
        player = ""
        for c in texts:
            c = re.sub(r"\s+", " ", c).strip()
            if c and c not in (place, name) and not c.startswith("$") and "tix" not in c.lower():
                if re.search(r"[A-Za-z]", c) and len(c) < 40:
                    player = c
                    break
        rows.append((dids[0], name, player, place))
    seen, uniq = set(), []
    for r in rows:
        if r[0] in seen:
            continue
        seen.add(r[0])
        uniq.append(r)
        if len(uniq) >= PER_EVENT:
            break
    return uniq


def search_url(fmt: str, page: int) -> str:
    params = {
        "utf8": "✓",
        "tournament_search[name]": "duel commander" if fmt == "commander" else "",
        "tournament_search[format]": "" if fmt == "commander" else fmt,
        "tournament_search[date_range]": DATE_RANGE,
        "commit": "Search",
        "page": str(page),
    }
    return "https://www.mtggoldfish.com/tournament_searches/create?" + urllib.parse.urlencode(params)


def discover(fmt: str):
    found = []
    seen = set()
    for page in range(1, MAX_PAGES + 1):
        url = search_url(fmt, page)
        try:
            html = fetch(url)
        except Exception as e:
            print("search fail", fmt, page, e, flush=True)
            break
        rows = ROW_RE.findall(html)
        added = 0
        for date, tid, name in rows:
            name = re.sub(r"\s+", " ", name).strip()
            if tid in seen:
                continue
            if SKIP_NAME.search(name):
                continue
            if fmt == "commander" and "commander" not in name.lower():
                continue
            seen.add(tid)
            found.append(
                (
                    fmt,
                    f"https://www.mtggoldfish.com/tournament/{tid}",
                    name,
                    date,
                )
            )
            added += 1
        print(f"  search {fmt} page {page}: {added} events", flush=True)
        if added == 0 or f"page={page + 1}" not in html:
            break
        time.sleep(0.2)
    return found


def main():
    existing = json.loads(OUT.read_text()) if OUT.exists() else []
    have = {str(d.get("id")) for d in existing}
    added = 0
    for fmt in FORMATS:
        print(f"{fmt}: discovering", flush=True)
        events = discover(fmt)
        print(f"{fmt}: {len(events)} events", flush=True)
        for fmt_name, url, event, date in events:
            try:
                html = fetch(url)
            except urllib.error.HTTPError as e:
                if e.code in (404, 410):
                    continue
                print("  fail", url, e, flush=True)
                continue
            except Exception as e:
                print("  fail", url, e, flush=True)
                continue
            rows = parse_rows(html)
            if not rows:
                continue
            new_here = 0
            for deck_id, arche, player, place in rows:
                if deck_id in have:
                    continue
                try:
                    main, side = download_deck(deck_id)
                    time.sleep(0.06)
                except Exception as e:
                    print("   fail deck", deck_id, e, flush=True)
                    continue
                if not main:
                    continue
                existing.append({
                    "id": deck_id,
                    "format": fmt_name,
                    "archetype": arche,
                    "player": player,
                    "place": place,
                    "event": event,
                    "date": date,
                    "source": url,
                    "source_name": "MTGGoldfish",
                    "main": main,
                    "side": side,
                })
                have.add(deck_id)
                added += 1
                new_here += 1
            if new_here:
                print(f"  {event} {date}: +{new_here}/{len(rows)}", flush=True)
            time.sleep(0.12)
        # checkpoint per format so a later fail does not lose work
        OUT.parent.mkdir(parents=True, exist_ok=True)
        json.dump(existing, OUT.open("w"), indent=2)
    counts = defaultdict(int)
    for d in existing:
        counts[d.get("format")] += 1
    print("added", added, "total", len(existing), dict(counts), flush=True)


if __name__ == "__main__":
    main()
