#!/usr/bin/env python3
"""Add 1,000 public decklists from each major Magic deck site.

MTGGoldfish is already in data/decks.json (well over 1,000). This script adds
Moxfield, Archidekt, MTGTop8, Deckstats, and every public AetherHub metagame
list it can reach. Card names and quantities only — images stay on Scryfall.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html import unescape as html_unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "decks.json"
TARGET = 1000
UA = "Mozilla/5.0 (compatible; MTGDecklistsBot/1.0; +https://mtgdecklists.com)"
FORMATS = ("standard", "modern", "pioneer", "legacy", "vintage", "pauper", "commander")
# Spread each 1,000-list pull across formats. Short formats spill into the rest.
QUOTA = {
    "standard": 160,
    "modern": 160,
    "pioneer": 140,
    "legacy": 140,
    "vintage": 80,
    "pauper": 80,
    "commander": 240,
}


class Limiter:
    def __init__(self, gap: float):
        self.gap = gap
        self.lock = threading.Lock()
        self.next_at = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            if now < self.next_at:
                time.sleep(self.next_at - now)
            self.next_at = time.monotonic() + self.gap


def fetch(url: str, limiter: Limiter | None = None, retries: int = 4, accept: str = "*/*") -> bytes:
    if limiter:
        limiter.wait()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (404, 410, 400):
                raise
            time.sleep(1.2 * (attempt + 1))
        except Exception as e:
            last = e
            time.sleep(1.2 * (attempt + 1))
    raise last


def fetch_text(url: str, limiter: Limiter | None = None) -> str:
    raw = fetch(url, limiter)
    return raw.decode("utf-8", "replace")


def fetch_json(url: str, limiter: Limiter | None = None):
    return json.loads(fetch_text(url, limiter))


def iso_date(value: str | None) -> str:
    if not value:
        return "2026-10-07"
    value = value.strip()
    if re.match(r"\d{4}-\d{2}-\d{2}", value):
        return value[:10]
    m = re.match(r"(\d{2})/(\d{2})/(\d{2})", value)
    if m:
        dd, mm, yy = m.groups()
        year = 2000 + int(yy)
        return f"{year:04d}-{int(mm):02d}-{int(dd):02d}"
    return "2026-10-07"


def unix_date(value) -> str:
    try:
        return datetime.fromtimestamp(int(value), timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return "2026-10-07"


def clean_name(text: str) -> str:
    text = html_unescape(text or "")
    text = text.replace("\\/", "/")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^[\+\-\s]+", "", text)
    return text


def map_format(label: str) -> str | None:
    n = (label or "").lower()
    if any(k in n for k in ("commander", "edh", "duel")):
        return "commander"
    if "pauper" in n:
        return "pauper"
    if "vintage" in n:
        return "vintage"
    if "legacy" in n:
        return "legacy"
    if "pioneer" in n:
        return "pioneer"
    if "modern" in n:
        return "modern"
    if "standard" in n and "future" not in n:
        return "standard"
    return None


def qty_sum(cards: list) -> int:
    return sum(int(c.get("qty") or 0) for c in cards)


def acceptable(fmt: str, main: list) -> bool:
    n = qty_sum(main)
    if fmt == "commander":
        return n >= 90
    return n >= 40


def parse_list_text(text: str) -> tuple[list, list]:
    main, side = [], []
    bucket = main
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        if line.lower() in {"sideboard", "sb"}:
            bucket = side
            continue
        m = re.match(r"^(\d+)\s+(?:\[[^\]]*\]\s*)?(.+)$", line)
        if not m:
            if main and bucket is main:
                bucket = side
            continue
        name = clean_name(m.group(2))
        name = re.sub(r"\s+#.*$", "", name).strip()
        if name:
            bucket.append({"qty": int(m.group(1)), "name": name})
    return main, side


class Store:
    def __init__(self):
        self.decks = json.loads(OUT.read_text()) if OUT.exists() else []
        self.ids = {str(d.get("id")) for d in self.decks}
        self.by_source = Counter(d.get("source_name") or "" for d in self.decks)
        self.lock = threading.Lock()

    def add(self, row: dict) -> bool:
        with self.lock:
            if row["id"] in self.ids:
                return False
            self.ids.add(row["id"])
            self.decks.append(row)
            self.by_source[row["source_name"]] += 1
            return True

    def save(self) -> None:
        with self.lock:
            OUT.write_text(json.dumps(self.decks, separators=(",", ":")))

    def source_count(self, name: str) -> int:
        with self.lock:
            return self.by_source[name]


def take_quota(candidates: list[tuple[str, object]]) -> list:
    """candidates are (format, payload). Keep QUOTA per format, then fill to TARGET."""
    buckets = defaultdict(list)
    for fmt, payload in candidates:
        if fmt in FORMATS:
            buckets[fmt].append(payload)
    chosen = []
    used = set()

    def push(fmt: str, limit: int) -> None:
        for payload in buckets[fmt]:
            if len(chosen) >= TARGET:
                return
            key = id(payload)
            if key in used:
                continue
            have = sum(1 for f, _ in chosen if f == fmt)
            if have >= limit:
                return
            used.add(key)
            chosen.append((fmt, payload))

    for fmt, n in QUOTA.items():
        push(fmt, n)
    for fmt in FORMATS:
        push(fmt, TARGET)
    return chosen[:TARGET]


def scrape_moxfield(store: Store) -> int:
    name = "Moxfield"
    if store.source_count(name) >= TARGET:
        print(f"{name}: already {store.source_count(name)}", flush=True)
        return 0
    limiter = Limiter(0.08)
    found = []
    seen = set()
    per_fmt_pages = {"vintage": 2, "pauper": 2, "pioneer": 3, "legacy": 3, "standard": 3, "modern": 3, "commander": 4}
    for fmt, pages in per_fmt_pages.items():
        for page in range(1, pages + 1):
            url = (
                "https://api.moxfield.com/v2/decks/search?pageNumber="
                f"{page}&pageSize=100&sortType=updated&sortDirection=Descending&fmt={fmt}"
            )
            try:
                payload = fetch_json(url, limiter)
            except Exception as e:
                print(f"  moxfield search {fmt} p{page} {e}", flush=True)
                break
            rows = payload.get("data") or []
            if not rows:
                break
            for row in rows:
                if (row.get("format") or "").lower() != fmt:
                    continue
                pid = row.get("publicId")
                if not pid or pid in seen:
                    continue
                if int(row.get("mainboardCount") or 0) < (90 if fmt == "commander" else 40):
                    continue
                seen.add(pid)
                author = ""
                authors = row.get("authors") or []
                if authors:
                    author = authors[0].get("displayName") or authors[0].get("userName") or ""
                commanders = list((row.get("commanders") or {}).keys()) if isinstance(row.get("commanders"), dict) else []
                found.append((fmt, {
                    "publicId": pid,
                    "title": row.get("name") or "Untitled",
                    "author": author,
                    "date": iso_date(row.get("lastUpdatedAtUtc") or row.get("createdAtUtc")),
                    "commanders": commanders,
                    "url": row.get("publicUrl") or f"https://moxfield.com/decks/{pid}",
                }))
            print(f"  moxfield {fmt} page {page}: pool {len(found)}", flush=True)
    chosen = take_quota(found)
    added = 0

    def one(item):
        fmt, meta = item
        detail = fetch_json(f"https://api.moxfield.com/v2/decks/all/{meta['publicId']}", limiter)
        main = board_cards(detail.get("mainboard"))
        for extra in (detail.get("commanders"), detail.get("companions")):
            for card in board_cards(extra):
                if card["name"] not in {c["name"] for c in main}:
                    main.insert(0, card)
        side = board_cards(detail.get("sideboard"))
        return fmt, meta, main, side

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(one, item) for item in chosen]
        for fut in as_completed(futures):
            try:
                fmt, meta, main, side = fut.result()
            except Exception as e:
                print(f"  moxfield deck fail {e}", flush=True)
                continue
            if not acceptable(fmt, main):
                continue
            commanders = meta["commanders"] or [c["name"] for c in main[:1] if fmt == "commander"]
            archetype = commanders[0] if fmt == "commander" and commanders else clean_name(meta["title"])
            row = {
                "id": f"mox-{meta['publicId']}",
                "format": fmt,
                "archetype": archetype,
                "player": meta["author"],
                "place": "",
                "event": f"Moxfield public {fmt} list",
                "date": meta["date"],
                "source": meta["url"],
                "source_name": name,
                "main": main,
                "side": side,
            }
            if store.add(row):
                added += 1
                if added % 100 == 0:
                    store.save()
                    print(f"  moxfield saved {added}", flush=True)
    store.save()
    print(f"{name}: +{added} now {store.source_count(name)}", flush=True)
    return added


def board_cards(board) -> list:
    out = []
    if not isinstance(board, dict):
        return out
    for key, row in board.items():
        if not isinstance(row, dict):
            continue
        qty = int(row.get("quantity") or 0)
        card = row.get("card") or {}
        nm = clean_name(card.get("name") or key)
        if qty and nm:
            out.append({"qty": qty, "name": nm})
    return out


def scrape_archidekt(store: Store) -> int:
    name = "Archidekt"
    if store.source_count(name) >= TARGET:
        print(f"{name}: already {store.source_count(name)}", flush=True)
        return 0
    limiter = Limiter(0.08)
    fmt_ids = {
        "standard": 1,
        "modern": 2,
        "commander": 3,
        "legacy": 4,
        "vintage": 5,
        "pauper": 6,
        "pioneer": 15,
    }
    found = []
    seen = set()
    pages_for = {"commander": 6, "standard": 4, "modern": 4, "pioneer": 4, "legacy": 4, "vintage": 3, "pauper": 3}
    for fmt, fid in fmt_ids.items():
        for page in range(1, pages_for[fmt] + 1):
            url = (
                "https://archidekt.com/api/decks/v3/"
                f"?pageSize=60&page={page}&orderBy=-viewCount&deckFormat={fid}"
            )
            try:
                payload = fetch_json(url, limiter)
            except Exception as e:
                print(f"  archidekt search {fmt} p{page} {e}", flush=True)
                break
            rows = payload.get("results") or []
            if not rows:
                break
            for row in rows:
                if row.get("private") or row.get("unlisted") or row.get("theorycrafted"):
                    continue
                if row.get("deckFormat") not in (None, fid):
                    continue
                size = int(row.get("size") or 0)
                if size < (90 if fmt == "commander" else 60):
                    continue
                did = row.get("id")
                if not did or did in seen:
                    continue
                seen.add(did)
                owner = (row.get("owner") or {}).get("username") or ""
                found.append((fmt, {
                    "id": did,
                    "title": row.get("name") or "Untitled",
                    "author": owner,
                    "date": iso_date(row.get("updatedAt") or row.get("createdAt")),
                }))
            print(f"  archidekt {fmt} page {page}: pool {len(found)}", flush=True)
            if not payload.get("next"):
                break
    chosen = take_quota(found)
    added = 0

    def one(item):
        fmt, meta = item
        detail = fetch_json(f"https://archidekt.com/api/decks/{meta['id']}/", limiter)
        main, side = [], []
        commanders = []
        for row in detail.get("cards") or []:
            card = row.get("card") or {}
            oracle = card.get("oracleCard") or {}
            nm = clean_name(oracle.get("name") or "")
            if not nm:
                continue
            qty = int(row.get("quantity") or 0)
            if qty <= 0:
                continue
            cats = " ".join(row.get("categories") or []).lower()
            entry = {"qty": qty, "name": nm}
            if "maybe" in cats:
                continue
            if "side" in cats:
                side.append(entry)
            else:
                main.append(entry)
            if "commander" in cats or row.get("companion"):
                commanders.append(nm)
        return fmt, meta, main, side, commanders

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(one, item) for item in chosen]
        for fut in as_completed(futures):
            try:
                fmt, meta, main, side, commanders = fut.result()
            except Exception as e:
                print(f"  archidekt deck fail {e}", flush=True)
                continue
            if not acceptable(fmt, main):
                continue
            archetype = commanders[0] if fmt == "commander" and commanders else clean_name(meta["title"])
            row = {
                "id": f"arch-{meta['id']}",
                "format": fmt,
                "archetype": archetype,
                "player": meta["author"],
                "place": "",
                "event": f"Archidekt public {fmt} list",
                "date": meta["date"],
                "source": f"https://archidekt.com/decks/{meta['id']}",
                "source_name": name,
                "main": main,
                "side": side,
            }
            if store.add(row):
                added += 1
                if added % 100 == 0:
                    store.save()
                    print(f"  archidekt saved {added}", flush=True)
    store.save()
    print(f"{name}: +{added} now {store.source_count(name)}", flush=True)
    return added


def scrape_top8(store: Store) -> int:
    name = "MTGTop8"
    if store.source_count(name) >= TARGET:
        print(f"{name}: already {store.source_count(name)}", flush=True)
        return 0
    limiter = Limiter(0.1)
    codes = {
        "standard": "ST",
        "modern": "MO",
        "pioneer": "PI",
        "legacy": "LE",
        "vintage": "VI",
        "pauper": "PAU",
        "commander": "EDH",
    }
    found = []
    seen_decks = set()
    for fmt, code in codes.items():
        try:
            html = fetch_text(f"https://www.mtgtop8.com/format?f={code}", limiter)
        except Exception as e:
            print(f"  top8 format {fmt} {e}", flush=True)
            continue
        events = []
        seen_e = set()
        for eid, title in re.findall(r"href=event\?e=(\d+)[^>]*>([^<]+)</a>", html):
            title = clean_name(title)
            if eid in seen_e or title in {"@", ""}:
                continue
            seen_e.add(eid)
            events.append((eid, title))
        print(f"  top8 {fmt}: {len(events)} events", flush=True)
        # Newest events are listed first. A handful of them cover the quota.
        need = QUOTA[fmt] + 30
        got_fmt = 0
        for eid, title in events:
            if got_fmt >= need:
                break
            try:
                page = fetch_text(f"https://www.mtgtop8.com/event?e={eid}&f={code}", limiter)
            except Exception as e:
                print(f"  top8 event {eid} {e}", flush=True)
                continue
            dates = re.findall(r"\d{2}/\d{2}/\d{2}", page)
            date = iso_date(dates[0] if dates else "")
            parts = re.split(r'<div class=(?:chosen_tr|hover_tr)', page)
            for part in parts[1:]:
                deck_m = re.search(r"[?&]d=(\d+)[^>]*>([^<]+)</a>", part)
                if not deck_m:
                    continue
                did, arche = deck_m.group(1), clean_name(deck_m.group(2))
                if did in seen_decks or arche in {"", "&rarr;"}:
                    continue
                seen_decks.add(did)
                place_m = re.search(r'class=S14>(\d+)<', part)
                player_m = re.search(r'class=player[^>]*>([^<]+)</a>', part)
                found.append((fmt, {
                    "id": did,
                    "title": arche,
                    "player": clean_name(player_m.group(1)) if player_m else "",
                    "place": place_m.group(1) if place_m else "",
                    "event": title,
                    "date": date,
                    "event_id": eid,
                }))
                got_fmt += 1
        print(f"  top8 {fmt} pool now {len(found)}", flush=True)
    chosen = take_quota(found)
    added = 0

    def one(item):
        fmt, meta = item
        text = fetch_text(f"https://www.mtgtop8.com/mtgo?d={meta['id']}", limiter)
        main, side = parse_list_text(text)
        return fmt, meta, main, side

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(one, item) for item in chosen]
        for fut in as_completed(futures):
            try:
                fmt, meta, main, side = fut.result()
            except Exception as e:
                print(f"  top8 deck fail {e}", flush=True)
                continue
            if not acceptable(fmt, main):
                continue
            row = {
                "id": f"top8-{meta['id']}",
                "format": fmt,
                "archetype": meta["title"] or "Unknown",
                "player": meta["player"],
                "place": meta["place"],
                "event": meta["event"],
                "date": meta["date"],
                "source": f"https://www.mtgtop8.com/event?e={meta['event_id']}&d={meta['id']}",
                "source_name": name,
                "main": main,
                "side": side,
            }
            if store.add(row):
                added += 1
                if added % 100 == 0:
                    store.save()
                    print(f"  top8 saved {added}", flush=True)
    store.save()
    print(f"{name}: +{added} now {store.source_count(name)}", flush=True)
    return added


def scrape_deckstats(store: Store) -> int:
    name = "Deckstats"
    if store.source_count(name) >= TARGET:
        print(f"{name}: already {store.source_count(name)}", flush=True)
        return 0
    limiter = Limiter(0.04)
    urls = []
    for site in (
        "https://deckstats.net/sitemaps/sitemap-decks-fresh-00.xml",
        "https://deckstats.net/sitemaps/sitemap-decks-qualified-00.xml",
    ):
        xml = fetch_text(site, limiter)
        urls.extend(re.findall(r"<loc>([^<]+)</loc>", xml))
    print(f"  deckstats urls {len(urls)}", flush=True)
    added = 0
    scanned = 0
    fmt_got = Counter()
    commander_cap = 650
    lock = threading.Lock()

    def one(url: str):
        html = fetch_text(url, limiter)
        m = re.search(r'<script[^>]*type="application/json"[^>]*>([\s\S]*?)</script>', html)
        if not m:
            return None
        data = json.loads(m.group(1))
        props = data.get("props") or {}
        deck = props.get("deck") or {}
        if deck.get("visibility") not in (None, "public") and deck.get("is_public") is False:
            return None
        fmt = map_format(deck.get("format_display_name") or deck.get("format_name") or "")
        if not fmt:
            return None
        main, side = [], []
        commander = ""
        for entry in props.get("entries") or []:
            zone = (entry.get("zone") or "").lower()
            if zone in {"maybeboard", "tokens", "sideboard"} and zone != "sideboard":
                if zone == "maybeboard" or zone == "tokens":
                    continue
            nm = clean_name(entry.get("name") or "")
            qty = int(entry.get("amount") or 0)
            if not nm or qty <= 0:
                continue
            card = {"qty": qty, "name": nm}
            if zone == "sideboard":
                side.append(card)
            else:
                main.append(card)
            if entry.get("is_commander") or zone == "commander":
                commander = commander or nm
        return fmt, deck, main, side, commander, url

    for start in range(0, min(len(urls), 2400), 120):
        if added >= TARGET:
            break
        batch = urls[start:start + 120]
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(one, url) for url in batch]
            for fut in as_completed(futures):
                scanned += 1
                try:
                    result = fut.result()
                except Exception:
                    result = None
                if not result:
                    continue
                fmt, deck, main, side, commander, url = result
                if not acceptable(fmt, main):
                    continue
                with lock:
                    if added >= TARGET:
                        continue
                    if fmt == "commander" and fmt_got["commander"] >= commander_cap and added < TARGET:
                        continue
                    archetype = commander if fmt == "commander" and commander else clean_name(deck.get("name") or "Untitled")
                    archetype = re.sub(r"^\+?\s*commander:\s*", "", archetype, flags=re.I).strip() or archetype
                    row = {
                        "id": f"ds-{deck.get('idsdeck') or url.rstrip('/').split('/')[-1].split('-')[0]}",
                        "format": fmt,
                        "archetype": archetype,
                        "player": deck.get("owner_name") or "",
                        "place": "",
                        "event": "Deckstats public list",
                        "date": unix_date(deck.get("updated") or deck.get("added")),
                        "source": url,
                        "source_name": name,
                        "main": main,
                        "side": side,
                    }
                    if store.add(row):
                        added += 1
                        fmt_got[fmt] += 1
                        if added % 100 == 0:
                            store.save()
                            print(f"  deckstats saved {added} scanned {scanned} {dict(fmt_got)}", flush=True)
        # If commander filled its cap and other formats are scarce, allow more commander
        # once we have scanned a wide slice of the sitemap.
        if scanned >= 1200 and added < TARGET:
            commander_cap = TARGET
        print(f"  deckstats chunk {start} added {added} scanned {scanned}", flush=True)
    store.save()
    print(f"{name}: +{added} scanned {scanned} {dict(fmt_got)} now {store.source_count(name)}", flush=True)
    return added


def scrape_aetherhub(store: Store) -> int:
    name = "AetherHub"
    if store.source_count(name) >= TARGET:
        print(f"{name}: already {store.source_count(name)}", flush=True)
        return 0
    limiter = Limiter(0.08)
    paths = [
        ("/Metagame/Standard", "standard"),
        ("/Metagame/Traditional-Standard", "standard"),
        ("/Metagame/Standard-BO1", "standard"),
        ("/Metagame/Standard-Events", "standard"),
        ("/Metagame/Modern", "modern"),
        ("/Metagame/Pioneer", "pioneer"),
        ("/Metagame/Legacy", "legacy"),
        ("/Metagame/Vintage", "vintage"),
        ("/Metagame/Pauper", "pauper"),
        ("/Metagame/Commander", "commander"),
        ("/Events/", "standard"),
        ("/Decks/Standard/", "standard"),
        ("/Decks/Modern/", "modern"),
        ("/Decks/Pioneer/", "pioneer"),
        ("/Decks/Legacy/", "legacy"),
        ("/Decks/Vintage/", "vintage"),
        ("/Decks/Pauper/", "pauper"),
        ("/Decks/Commander/", "commander"),
    ]
    found = {}
    for path, fmt in paths:
        for suffix in ("", "?days=7", "?days=60", "?days=90"):
            url = "https://aetherhub.com" + path + suffix
            try:
                html = fetch_text(url, limiter)
            except Exception as e:
                print(f"  aetherhub {url} {e}", flush=True)
                continue
            for slug, did in re.findall(r"/Deck/([A-Za-z0-9\-]+)-(\d+)", html):
                if slug.lower() in {"builder", "mydecks", "edit"}:
                    continue
                found.setdefault(did, (fmt, slug))
            # Follow event pages linked from the events index once.
            if path == "/Events/":
                for href in set(re.findall(r'href="(/Events/[^"]+)"', html)):
                    if href.rstrip("/") == "/Events":
                        continue
                    try:
                        sub = fetch_text("https://aetherhub.com" + href, limiter)
                    except Exception:
                        continue
                    for slug, did in re.findall(r"/Deck/([A-Za-z0-9\-]+)-(\d+)", sub):
                        found.setdefault(did, ("standard", slug))
    print(f"  aetherhub unique public decks {len(found)}", flush=True)
    added = 0

    def one(item):
        did, (fmt, slug) = item
        text = fetch_text(f"https://aetherhub.com/Deck/MtgoDeckExport/{did}", limiter)
        main, side = parse_list_text(text)
        title = slug.replace("-", " ").title()
        source = f"https://aetherhub.com/Deck/{slug}-{did}"
        return did, fmt, title, source, main, side

    items = list(found.items())[:TARGET]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(one, item) for item in items]
        for fut in as_completed(futures):
            try:
                did, fmt, title, source, main, side = fut.result()
            except Exception as e:
                print(f"  aetherhub deck fail {e}", flush=True)
                continue
            if not acceptable(fmt, main):
                continue
            row = {
                "id": f"ah-{did}",
                "format": fmt,
                "archetype": title or "Unknown",
                "player": "",
                "place": "",
                "event": "AetherHub public metagame list",
                "date": "2026-10-07",
                "source": source if "/Deck/" in source else f"https://aetherhub.com/Deck/{did}",
                "source_name": name,
                "main": main,
                "side": side,
            }
            # Prefer a stable deck URL.
            row["source"] = source
            if store.add(row):
                added += 1
                if added % 50 == 0:
                    store.save()
                    print(f"  aetherhub saved {added}", flush=True)
    store.save()
    print(f"{name}: +{added} now {store.source_count(name)}", flush=True)
    return added


def main() -> None:
    store = Store()
    print("start", dict(store.by_source), flush=True)
    for fn in (scrape_moxfield, scrape_archidekt, scrape_top8, scrape_deckstats, scrape_aetherhub):
        try:
            fn(store)
        except Exception as e:
            print(f"SITE FAIL {fn.__name__}: {e}", flush=True)
            store.save()
    counts = Counter(d.get("source_name") or "" for d in store.decks)
    formats = Counter(d.get("format") or "" for d in store.decks)
    print("DONE", len(store.decks), dict(counts), dict(formats), flush=True)


if __name__ == "__main__":
    main()
