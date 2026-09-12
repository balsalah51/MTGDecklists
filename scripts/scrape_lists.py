#!/usr/bin/env python3
"""Pull June–Sep 2026 public lists from MTGGoldfish into data/decks.json."""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from html import unescape as html_unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "decks.json"
UA = "Mozilla/5.0 (compatible; MTGDecklistsBot/1.0; +https://mtgdecklists.com)"
FORMATS = ("standard", "modern", "pioneer", "legacy", "vintage", "pauper", "commander")
TARGET_PER_FORMAT = 800
TARGET_COMMANDER = 828
PER_EVENT = 32
PER_EVENT_COMMANDER = 40
MAX_PAGES = 40
MAX_PAGES_COMMANDER = 44
DATE_RANGE = "06/01/2026 - 09/30/2026"
COMMANDER_DATE_RANGE = "05/01/2026 - 09/30/2026"
MONTHS = ("2026-06", "2026-07", "2026-08", "2026-09")
COMMANDER_MONTHS = ("2026-05", "2026-06", "2026-07", "2026-08", "2026-09")
MIN_LISTS_PER_COMMANDER = 5
MAX_NEW_LISTS_PER_COMMANDER = 8
NEW_COMMANDERS_TARGET = 200
PIN_COMMANDERS = ("Basim Ibn Ishaq",)
SCRYFALL_UA = "MTGDecklistsBot/1.0 (+https://mtgdecklists.com)"
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
    return date[:7] in MONTHS


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


def select_commanders(subset: list) -> list:
    """Keep every in-window Commander list; diversity comes from enrich_commanders()."""
    seen, out = set(), []
    for d in subset:
        i = str(d.get("id"))
        if i in seen:
            continue
        seen.add(i)
        out.append(d)
    return out


def select_target(decks: list, n: int = TARGET_PER_FORMAT) -> list:
    """Keep a cap of lists per format, round-robin across events so one league cannot fill the cap."""
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
        if fmt == "commander":
            out.extend(select_commanders(by.get(fmt, [])))
        else:
            out.extend(_spread(by.get(fmt, []), target_for(fmt)))
    out.sort(key=lambda x: (x.get("date") or "", str(x.get("id"))), reverse=True)
    return out


def slugify(text: str) -> str:
    text = html_unescape(text or "")
    text = text.replace("&", "and")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "list"


def has_commander(cards: list, commander: str) -> bool:
    names = [html_unescape(c.get("name") or "").lower() for c in cards or []]
    commander = html_unescape(commander or "")
    targets = []
    for part in re.split(r"\s*//\s*", commander):
        part = part.strip().lower()
        if part:
            targets.append(part)
            targets.append(part.split(",")[0].strip())
    for t in targets:
        if not t:
            continue
        for n in names:
            if not n:
                continue
            if len(t) <= 4:
                if t == n:
                    return True
            elif t == n or t in n or n in t:
                return True
    return False


def commander_count(existing: list) -> dict:
    counts = defaultdict(int)
    for d in existing:
        if d.get("format") == "commander":
            by = d.get("archetype") or "Unknown"
            counts[by] += 1
    return counts


def card_qty(cards: list) -> int:
    return sum(int(c.get("qty") or 0) for c in cards or [])


def goldfish_slugs(name: str) -> list[str]:
    primary = re.split(r"\s*//\s*", name)[0].strip()
    s = slugify(primary)
    return [f"commander-{s}", s]


def title_looks_like(title: str, commander: str) -> bool:
    t = html_unescape(title or "").lower()
    c = html_unescape(commander or "").lower()
    if not t or not c:
        return False
    if c in t or t in c:
        return True
    stop = {"the", "and", "of", "from", "god", "one", "for", "with"}
    tokens = [w for w in re.split(r"[^a-z0-9]+", c) if len(w) > 3 and w not in stop]
    if not tokens:
        tokens = [w for w in re.split(r"[^a-z0-9]+", c) if w and w not in stop]
    return any(tok in t for tok in tokens)


def parse_archetype_lists(html: str, commander: str | None = None) -> list[tuple[str, str, str]]:
    """Deck id, displayed name, player from the archetype's own table (last table on the page)."""
    tables = re.findall(r"<table[\s\S]*?</table>", html, re.I)
    if not tables:
        return []
    out, seen = [], []
    seen = set()
    blob = tables[-1]
    for tr in re.findall(r"<tr[\s\S]*?</tr>", blob, re.I):
        m = re.search(r'href="/deck/(\d+)#paper">([^<]+)', tr)
        if not m:
            m = re.search(r'href="/deck/(\d+)(?:#[^"]*)?"[^>]*>([^<]+)', tr)
        if not m:
            continue
        did, title = m.group(1), html_unescape(re.sub(r"\s+", " ", m.group(2)).strip())
        if did in seen:
            continue
        if commander and not title_looks_like(title, commander):
            continue
        pm = re.search(r'href="/player/([^"]+)"', tr)
        player = ""
        if pm:
            player = urllib.parse.unquote(pm.group(1)).replace("+", " ")
        else:
            cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>([\s\S]*?)</td>", tr)]
            if len(cells) > 1:
                player = re.sub(r"\s+", " ", cells[1]).strip()
        seen.add(did)
        out.append((did, title, player))
    if commander and len(out) < MIN_LISTS_PER_COMMANDER:
        # titles are often nicknames; keep the last table unfiltered and verify on download
        extra, seen2 = [], set(seen)
        for tr in re.findall(r"<tr[\s\S]*?</tr>", blob, re.I):
            m = re.search(r'href="/deck/(\d+)#paper">([^<]+)', tr)
            if not m:
                continue
            did, title = m.group(1), html_unescape(re.sub(r"\s+", " ", m.group(2)).strip())
            if did in seen2:
                continue
            seen2.add(did)
            extra.append((did, title, ""))
        out.extend(extra)
    return out


def fetch_archetype(name: str) -> str:
    last = None
    for slug in goldfish_slugs(name):
        url = f"https://www.mtggoldfish.com/archetype/{slug}"
        try:
            return fetch(url)
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (404, 410):
                continue
            raise
        except Exception as e:
            last = e
    if last:
        raise last
    raise RuntimeError(f"no archetype page for {name}")


def scryfall_commander_names(limit: int = 450) -> list[str]:
    names, url = [], "https://api.scryfall.com/cards/search?q=is%3Acommander&order=edhrec&unique=cards"
    while url and len(names) < limit:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": SCRYFALL_UA, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=40) as r:
            payload = json.loads(r.read().decode("utf-8", "replace"))
        for card in payload.get("data") or []:
            n = (card.get("name") or "").strip()
            if n and n not in names:
                names.append(n)
            if len(names) >= limit:
                break
        url = payload.get("next_page") if len(names) < limit else None
        time.sleep(0.08)
    return names


def save_decks(existing: list) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    json.dump(existing, OUT.open("w"), separators=(",", ":"))


def enrich_commanders(existing: list, have: set) -> tuple[list, set, int]:
    """Download at least 5 public lists for Basim plus 200 additional legends."""
    added = 0
    counts = commander_count(existing)
    before_names = set(counts)
    new_with_five = 0

    def need(name: str, want: int = MIN_LISTS_PER_COMMANDER) -> int:
        return max(0, want - counts.get(name, 0))

    def ingest(name: str, want: int) -> int:
        nonlocal added
        gap = need(name, want)
        if gap <= 0:
            return 0
        try:
            html = fetch_archetype(name)
        except Exception as err:
            print(f"  skip {name}: {err}", flush=True)
            return 0
        rows = parse_archetype_lists(html, name)
        got = 0
        attempts = 0
        for deck_id, _title, player in rows:
            if need(name, want) <= 0:
                break
            if attempts >= 14:
                break
            if deck_id in have:
                continue
            attempts += 1
            try:
                main, side = download_deck(deck_id)
                time.sleep(0.05)
            except Exception as err:
                print(f"   fail deck {deck_id} {err}", flush=True)
                continue
            cards = main + side
            if card_qty(main) < 90 or not has_commander(cards, name):
                continue
            existing.append({
                "id": deck_id,
                "format": "commander",
                "archetype": name,
                "player": player or "",
                "place": "",
                "event": "Goldfish public Commander list",
                "date": "2026-09-11",
                "source": f"https://www.mtggoldfish.com/deck/{deck_id}",
                "source_name": "MTGGoldfish",
                "main": main,
                "side": side,
            })
            have.add(deck_id)
            counts[name] += 1
            added += 1
            got += 1
        return got

    print("commanders: filling pinned legends and short lists", flush=True)
    for pin in PIN_COMMANDERS:
        got = ingest(pin, want=max(MIN_LISTS_PER_COMMANDER, 12))
        print(f"  pin {pin}: +{got} now {counts.get(pin, 0)}", flush=True)

    short = [n for n, c in sorted(counts.items()) if c < MIN_LISTS_PER_COMMANDER]
    for i, name in enumerate(short, start=1):
        got = ingest(name, MIN_LISTS_PER_COMMANDER)
        if got:
            print(f"  fill {name}: +{got} now {counts.get(name, 0)} ({i}/{len(short)})", flush=True)
        if i % 15 == 0:
            save_decks(existing)

    print("commanders: adding 200 new legends from Scryfall / Goldfish", flush=True)
    for name in scryfall_commander_names(480):
        if new_with_five >= NEW_COMMANDERS_TARGET:
            break
        if name in PIN_COMMANDERS:
            continue
        if name in before_names and counts.get(name, 0) >= MIN_LISTS_PER_COMMANDER:
            continue
        was_new = name not in before_names
        if not was_new:
            continue
        ingest(name, MIN_LISTS_PER_COMMANDER)
        if counts.get(name, 0) >= MIN_LISTS_PER_COMMANDER:
            new_with_five += 1
            print(f"  new {new_with_five}/{NEW_COMMANDERS_TARGET} {name}: {counts.get(name, 0)} lists", flush=True)
            if new_with_five % 5 == 0:
                save_decks(existing)
        else:
            print(f"  miss {name}: {counts.get(name, 0)} lists", flush=True)

    save_decks(existing)
    print(f"commanders enrich: +{added} lists, {new_with_five} new legends with {MIN_LISTS_PER_COMMANDER}+", flush=True)
    return existing, have, added


def discover(fmt: str):
    found = []
    seen = set()
    queries = [("", fmt, DATE_RANGE), (fmt, "", DATE_RANGE)]
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
    existing, have, extra = enrich_commanders(existing, have)
    added += extra
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
