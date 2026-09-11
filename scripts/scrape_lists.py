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
TARGET_PER_FORMAT = 400
TARGET_COMMANDER = 414
PER_EVENT = 24
PER_EVENT_COMMANDER = 32
MAX_PAGES = 20
MAX_PAGES_COMMANDER = 28
DATE_RANGE = "08/01/2026 - 09/30/2026"
COMMANDER_DATE_RANGE = "06/01/2026 - 09/30/2026"
COMMANDER_MONTHS = ("2026-06", "2026-07", "2026-08", "2026-09")
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


def parse_rows(html: str, cap: int = PER_EVENT):
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
        if len(uniq) >= cap:
            break
    return uniq


def search_url(fmt: str, page: int, *, name: str | None = None, goldfish_format: str | None = None, date_range: str | None = None) -> str:
    params = {
        "utf8": "✓",
        "tournament_search[name]": name if name is not None else ("duel commander" if fmt == "commander" else ""),
        "tournament_search[format]": goldfish_format if goldfish_format is not None else ("" if fmt == "commander" else fmt),
        "tournament_search[date_range]": date_range or (COMMANDER_DATE_RANGE if fmt == "commander" else DATE_RANGE),
        "commit": "Search",
        "page": str(page),
    }
    return "https://www.mtggoldfish.com/tournament_searches/create?" + urllib.parse.urlencode(params)


def in_window(date: str, fmt: str | None = None) -> bool:
    if not date:
        return False
    if fmt == "commander":
        return date[:7] in COMMANDER_MONTHS
    return date[:7] in ("2026-08", "2026-09")


def target_for(fmt: str) -> int:
    return TARGET_COMMANDER if fmt == "commander" else TARGET_PER_FORMAT


def _spread(subset: list, k: int) -> list:
    """Newest events first, round-robin so one challenge does not fill the cap."""
    if k <= 0 or not subset:
        return []
    by_event = defaultdict(list)
    for d in subset:
        by_event[d.get("event") or ""].append(d)
    for rows in by_event.values():
        rows.sort(key=lambda x: (x.get("date") or "", x.get("place") or ""), reverse=True)
    events = sorted(by_event, key=lambda e: by_event[e][0].get("date") or "", reverse=True)
    out, idx = [], {e: 0 for e in events}
    while len(out) < k:
        progressed = False
        for e in events:
            i = idx[e]
            if i < len(by_event[e]):
                out.append(by_event[e][i])
                idx[e] += 1
                progressed = True
                if len(out) >= k:
                    break
        if not progressed:
            break
    return out


def select_target(decks: list, n: int = TARGET_PER_FORMAT) -> list:
    """Keep a cap of lists per format. Commander may include June–July to fill +100."""
    by = defaultdict(list)
    seen = set()
    for d in decks:
        did = str(d.get("id"))
        fmt = d.get("format")
        if did in seen or fmt not in FORMATS or not in_window(d.get("date") or "", fmt):
            continue
        seen.add(did)
        by[fmt].append(d)
    out = []
    for fmt in FORMATS:
        cap = target_for(fmt)
        group = by.get(fmt, [])
        months = ("2026-09", "2026-08", "2026-07", "2026-06") if fmt == "commander" else ("2026-09", "2026-08")
        buckets = [[d for d in group if (d.get("date") or "").startswith(month)] for month in months]
        chosen, leftover = [], []
        remaining = cap
        for i, bucket in enumerate(buckets):
            if remaining <= 0:
                leftover.extend(bucket)
                continue
            take = min(len(bucket), remaining) if fmt == "commander" else min(cap // 2 if i < 2 else remaining, len(bucket), remaining)
            picked = _spread(bucket, take)
            chosen.extend(picked)
            leftover.extend([d for d in bucket if d not in picked])
            remaining = cap - len(chosen)
        leftover.sort(key=lambda x: x.get("date") or "", reverse=True)
        for d in leftover:
            if len(chosen) >= cap:
                break
            chosen.append(d)
        out.extend(chosen[:cap])
    out.sort(key=lambda x: (x.get("date") or "", str(x.get("id"))), reverse=True)
    return out


def discover(fmt: str):
    found = []
    seen = set()
    queries = [(None, None, None)]
    pages = MAX_PAGES_COMMANDER if fmt == "commander" else MAX_PAGES
    if fmt == "commander":
        queries = [
            ("duel commander", "", COMMANDER_DATE_RANGE),
            ("commander", "", COMMANDER_DATE_RANGE),
            ("", "commander", COMMANDER_DATE_RANGE),
        ]
    for name, goldfish_format, date_range in queries:
        for page in range(1, pages + 1):
            url = search_url(fmt, page, name=name, goldfish_format=goldfish_format, date_range=date_range)
            try:
                html = fetch(url)
            except Exception as e:
                print("search fail", fmt, page, e, flush=True)
                break
            rows = ROW_RE.findall(html)
            added = 0
            for date, tid, event_name in rows:
                event_name = re.sub(r"\s+", " ", event_name).strip()
                if tid in seen:
                    continue
                if SKIP_NAME.search(event_name):
                    continue
                if fmt == "commander" and "commander" not in event_name.lower() and "edh" not in event_name.lower():
                    continue
                seen.add(tid)
                found.append(
                    (
                        fmt,
                        f"https://www.mtggoldfish.com/tournament/{tid}",
                        event_name,
                        date,
                    )
                )
                added += 1
            print(f"  search {fmt} {name or goldfish_format or fmt} page {page}: {added} events", flush=True)
            if added == 0 or f"page={page + 1}" not in html:
                break
            time.sleep(0.2)
    return found


def fmt_count(existing, fmt: str) -> int:
    return sum(1 for d in existing if d.get("format") == fmt and in_window(d.get("date") or "", fmt))


def main():
    existing = json.loads(OUT.read_text()) if OUT.exists() else []
    have = {str(d.get("id")) for d in existing}
    added = 0
    for fmt in FORMATS:
        have_fmt = fmt_count(existing, fmt)
        need = target_for(fmt)
        if have_fmt >= need:
            print(f"{fmt}: already {have_fmt}, skip scrape", flush=True)
            continue
        print(f"{fmt}: discovering (have {have_fmt}, need {need})", flush=True)
        events = discover(fmt)
        print(f"{fmt}: {len(events)} events", flush=True)
        cap_rows = PER_EVENT_COMMANDER if fmt == "commander" else PER_EVENT
        for fmt_name, url, event, date in events:
            if fmt_count(existing, fmt) >= need:
                break
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
            rows = parse_rows(html, cap_rows)
            if not rows:
                continue
            new_here = 0
            for deck_id, arche, player, place in rows:
                if fmt_count(existing, fmt) >= need:
                    break
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
                print(f"  {event} {date}: +{new_here}/{len(rows)} now {fmt_count(existing, fmt)}", flush=True)
            time.sleep(0.12)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        json.dump(existing, OUT.open("w"), separators=(",", ":"))
    trimmed = select_target(existing)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    json.dump(trimmed, OUT.open("w"), separators=(",", ":"))
    counts = defaultdict(int)
    months = defaultdict(lambda: defaultdict(int))
    for d in trimmed:
        counts[d.get("format")] += 1
        months[d.get("format")][(d.get("date") or "")[:7]] += 1
    print("added", added, "kept", len(trimmed), dict(counts), flush=True)
    for fmt in FORMATS:
        print(f"  {fmt}: {dict(months[fmt])}", flush=True)


if __name__ == "__main__":
    main()
