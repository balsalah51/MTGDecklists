#!/usr/bin/env python3
"""Generate the static MTG Decklists site from scraped tournament lists."""
from __future__ import annotations

import html
import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://mtgdecklists.com"
TODAY = "2026-09-07"
YEAR = "2026"

FORMATS = [
    {
        "slug": "standard",
        "name": "Standard",
        "short": "Rotating 60-card constructed",
        "blurb": "Current Standard uses Wilds of Eldraine forward. There is no fall 2026 rotation; the next rotation is with Nauctis: The Sunken Realm in early 2027. Store RCQs through November 29 are Standard constructed.",
        "official": "https://magic.wizards.com/en/formats/standard",
        "popular": True,
    },
    {
        "slug": "modern",
        "name": "Modern",
        "short": "Non-rotating from Eighth Edition on",
        "blurb": "Modern is the constructed format for the September–October 2026 Regional Championships that feed the first Pro Tour of 2027. Spotlight: The Hobbit in Dallas (Sept 4–6) was Modern.",
        "official": "https://magic.wizards.com/en/formats/modern",
        "popular": True,
    },
    {
        "slug": "pioneer",
        "name": "Pioneer",
        "short": "Return to Ravnica forward",
        "blurb": "Pioneer sits between Standard and Modern. After the Cori-Steel Cutter ban, Izzet spells shells and green Badgermole Cub piles split the winner's metagame in August 2026.",
        "official": "https://magic.wizards.com/en/formats/pioneer",
        "popular": False,
    },
    {
        "slug": "commander",
        "name": "Commander",
        "short": "100-card singleton, most-played format",
        "blurb": "Commander (EDH) is the most popular way to play Magic. Lists here are recent Duel Commander league tables from August–September 2026, plus the same 100-card singleton rules used at Commander night.",
        "official": "https://magic.wizards.com/en/formats/commander",
        "popular": True,
    },
    {
        "slug": "legacy",
        "name": "Legacy",
        "short": "Vintage-adjacent, banned list not restricted list",
        "blurb": "Legacy is eternal constructed with a banned list. The Fantasticar was banned in Legacy on August 10, 2026.",
        "official": "https://magic.wizards.com/en/formats/legacy",
        "popular": False,
    },
    {
        "slug": "vintage",
        "name": "Vintage",
        "short": "The original constructed format",
        "blurb": "Vintage uses a restricted list instead of a wide ban list. The Fantasticar was restricted in Vintage on August 10, 2026.",
        "official": "https://magic.wizards.com/en/formats/vintage",
        "popular": False,
    },
    {
        "slug": "pauper",
        "name": "Pauper",
        "short": "Commons only",
        "blurb": "Pauper is constructed using only cards printed at common. Wizards also clarified Secret Lair Zeta commons legality in September 2026.",
        "official": "https://magic.wizards.com/en/formats/pauper",
        "popular": False,
    },
]
FMT_BY = {f["slug"]: f for f in FORMATS}

COLORS = [
    ("W", "White", "mana-white.png", "#f3e6b8"),
    ("U", "Blue", "mana-blue.png", "#6ea8d8"),
    ("B", "Black", "mana-black.png", "#3a3a3a"),
    ("R", "Red", "mana-red.png", "#c4452d"),
    ("G", "Green", "mana-green.png", "#3f8f4a"),
]
COLOR_NAME = {c: n for c, n, *_ in COLORS}

GUILD = {
    "WU": "Azorius", "UB": "Dimir", "BR": "Rakdos", "RG": "Gruul", "GW": "Selesnya",
    "WB": "Orzhov", "UR": "Izzet", "BG": "Golgari", "RW": "Boros", "GU": "Simic",
    "WUB": "Esper", "UBR": "Grixis", "BRG": "Jund", "RGW": "Naya", "GWU": "Bant",
    "WBG": "Abzan", "URW": "Jeskai", "BGU": "Sultai", "RWB": "Mardu", "GUR": "Temur",
    "W": "Mono-White", "U": "Mono-Blue", "B": "Mono-Black", "R": "Mono-Red", "G": "Mono-Green",
    "WUBR": "4-color", "WUBG": "4-color", "WURG": "4-color", "WBRG": "4-color", "UBRG": "4-color",
    "WUBRG": "Five-color",
}

ARCHETYPE_COLORS = [
    (r"azorius", "WU"), (r"dimir", "UB"), (r"rakdos", "BR"), (r"gruul", "RG"),
    (r"selesnya", "GW"), (r"orzhov", "WB"), (r"izzet|\bur\b", "UR"), (r"golgari", "BG"),
    (r"boros", "RW"), (r"simic", "GU"), (r"esper", "WUB"), (r"grixis", "UBR"),
    (r"jund", "BRG"), (r"naya", "RGW"), (r"bant", "GWU"), (r"abzan", "WBG"),
    (r"jeskai", "URW"), (r"sultai", "BGU"), (r"mardu", "RWB"), (r"temur", "GUR"),
    (r"mono-?white|\bw\b", "W"), (r"mono-?blue|\bu\b", "U"), (r"mono-?black", "B"),
    (r"mono-?red|\bmono red", "R"), (r"mono-?green", "G"),
    (r"4c|four-color|four color", "WUBR"), (r"domain|five|wubrg", "WUBRG"),
    (r"eldrazi|tron|affinity|belcher", "C"),
]

LAND_PIPS = {
    "plains": "W", "island": "U", "swamp": "B", "mountain": "R", "forest": "G",
    "snow-covered plains": "W", "snow-covered island": "U", "snow-covered swamp": "B",
    "snow-covered mountain": "R", "snow-covered forest": "G",
    "hallowed fountain": "WU", "watery grave": "UB", "blood crypt": "BR",
    "stomping ground": "RG", "temple garden": "GW", "godless shrine": "WB",
    "steam vents": "UR", "overgrown tomb": "BG", "sacred foundry": "RW",
    "breeding pool": "GU", "flooded strand": "WU", "polluted delta": "UB",
    "bloodstained mire": "BR", "wooded foothills": "RG", "windswept heath": "GW",
    "marsh flats": "WB", "scalding tarn": "UR", "verdant catacombs": "BG",
    "arid mesa": "RW", "misty rainforest": "GU", "gloomlake verge": "UB",
    "riverpyre verge": "UR", "floodfarm verge": "WU", "bleachbone verge": "WB",
    "hushwood verge": "GW", "spirebluff canal": "UR", "concealed courtyard": "WB",
    "inspiring vantage": "RW", "botanical sanctum": "GU", "blooming marsh": "BG",
}

SHOP = [
    ("sleeves", "Sleeves", "Standard 63×88 mm Dragon Shield packs plus hard toploaders for singles.", [
        ("Dragon Shield Matte Jet", "100 standard-size sleeves (63×88 mm). Black matte finish. Fits a sleeved 60-card MTG deck plus extras.", "https://amzn.to/4qFzNrw", "sleeve-jet.jpg"),
        ("Dragon Shield Dual Matte Red / Gold", "100 standard-size Dual Matte sleeves. Red face, gold back (ART15065).", "https://amzn.to/46s2YVu", "sleeve-red-gold.jpg"),
        ("Dragon Shield Dual Matte Soul", "100 standard-size Dual Matte sleeves. Metallic purple Dual Soul (ART15062).", "https://amzn.to/4wMuTKw", "sleeve-soul.jpg"),
        ("Dragon Shield Matte Midnight Blue", "100 standard-size matte sleeves. Midnight Blue finish. Fits a sleeved 60-card MTG deck plus extras.", "https://amzn.to/4hSoJoD", "sleeve-midnight.jpg"),
        ("Dragon Shield Dual Matte Cobalt / Silver", "100 standard-size Dual Matte sleeves. Cobalt face, silver back.", "https://amzn.to/4wNVOFR", "sleeve-cobalt-silver.jpg"),
        ("Dragon Shield Matte Amethyst", "100 standard-size matte sleeves. Amethyst purple finish.", "https://amzn.to/3SSyuZM", "sleeve-amethyst.jpg"),
        ("Hard plastic toploaders (3×4, 200-pack)", "Rigid 3×4 in. holders for singles, trades, and binder extras. Not for in-game play.", "https://amzn.to/4ixZmZn", "sleeve-toploaders.jpg"),
    ]),
    ("dice", "Dice", "Life counters, a licensed tin, and a cheap acrylic D6 set.", [
        ("Power counter dice (+1000 / −1000)", "32-piece set of +1000 to +6000 and −1000 to −6000 counters. Works as extra dice at an MTG table.", "https://amzn.to/46pbKUi", "dice-power.jpg"),
        ("Official One Piece Premium Dice Set", "Licensed dice in a collectible Monkey D. Luffy tin. Same shop listing as One Piece Deck Base.", "https://amzn.to/4xEOaiF", "dice-luffy.jpg"),
        ("Yiotfandoll 16 mm D6 (blue / black)", "10 acrylic 16 mm six-siders. A cheap table set for life totals or Commander tax.", "https://amzn.to/4gQtpdA", "dice-acrylic.jpg"),
    ]),
    ("playmats", "Playmats", "A custom mat with bag and a skeleton playmat set.", [
        ("Custom TCG playmat with bag", "Personalized playmat with play-zone options and a non-slip surface. Ships with a mat bag.", "https://amzn.to/4hWBnD9", "playmat-custom.jpg"),
        ("One Piece skeleton playmat set", "14×24 in. playmat with two skull dice and a storage bag. Same affiliate listing as OPDB.", "https://amzn.to/4ypjUbx", "playmat-skeleton.jpg"),
    ]),
    ("deck-boxes", "Deck boxes", "Magnetic boxes for sleeved constructed and Commander lists.", [
        ("Wanted poster deck box", "Wanted-poster themed box with commander display. Holds about 120 singles or 100 double-sleeved cards.", "https://amzn.to/4xuKTlW", "deckbox-wanted.jpg"),
        ("4-pack magnetic deck boxes", "Four magnetic boxes. Each holds 100+ double-sleeved cards — enough for several Standard lists.", "https://amzn.to/3SSyyJ0", "deckbox-4pack.jpg"),
        ("MAKHISTORY Commander deck box", "Magnetic deck case with dice tray, 35pt holder, and two dividers. Fits 100+ double-sleeved cards.", "https://amzn.to/4gVNBuw", "deckbox-makhistory.jpg"),
        ("UAONO Commander deck box", "Magnetic commander box. Fits 100 double-sleeved cards and a toploader.", "https://amzn.to/4zVuIzE", "deckbox-uaono.jpg"),
    ]),
    ("extras", "Table extras", "Small gear for long events.", [
        ("Koonie USB desk fan", "Small quiet USB fan for long events. Strong airflow, adjustable, folds for the bag.", "https://amzn.to/4cc2lD5", "extra-desk-fan.jpg"),
    ]),
]

ARTS = [
    ("/img/art/art-flashback-mage.jpg", "Original flashback mage illustration"),
    ("/img/art/art-goblin-scout.jpg", "Original goblin scout illustration"),
    ("/img/art/art-crimson-bolt.jpg", "Original crimson bolt illustration"),
]


def e(text) -> str:
    return html.escape(str(text or ""), quote=True)


def unescape(text: str) -> str:
    return html.unescape(text or "").replace("&#39;", "'")


def slugify(text: str) -> str:
    text = unescape(text).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "list"


def identity_from_cards(cards) -> str:
    pips = set()
    for row in cards or []:
        name = unescape(row.get("name", "")).lower()
        if name in LAND_PIPS:
            pips.update(LAND_PIPS[name])
            continue
        for land, code in LAND_PIPS.items():
            if name.endswith(land) or land in name:
                pips.update(code)
    order = "WUBRG"
    return "".join(c for c in order if c in pips)


def identity_from_archetype(name: str) -> str:
    n = unescape(name).lower()
    for pat, code in ARCHETYPE_COLORS:
        if re.search(pat, n):
            return code
    return ""


def combo_label(code: str) -> str:
    if not code or code == "C":
        return "Colorless"
    return GUILD.get(code) or (" / ".join(COLOR_NAME[c] for c in code if c in COLOR_NAME) or code)


def pip_html(code: str) -> str:
    if not code or code == "C":
        return ""
    bits = []
    for c, name, fn, _ in COLORS:
        if c in code:
            bits.append(f'<img src="/img/mana/{fn}" alt="{e(name)} mana" width="22" height="22" />')
    return '<span class="combo-pips">' + "".join(bits) + "</span>"


def deck_url(deck: dict) -> str:
    return f"/decklists/{deck['format']}/{deck['page_slug']}.html"


def partner_card(name: str) -> str:
    dest = "https://www.tcgplayer.com/search/magic/product?q=" + html.escape(name, quote=False)
    # We'll output already-escaped href via JS mostly; static fallback:
    from urllib.parse import quote
    u = "https://www.tcgplayer.com/search/magic/product?q=" + quote(name) + "&productLineName=magic"
    partner = "https://partner.tcgplayer.com/c/7670706/1780961/21018?u=" + quote(u, safe="")
    return partner


def partner_mass(cards) -> str:
    from urllib.parse import quote
    lines = []
    seen = set()
    for row in cards or []:
        name = unescape(row.get("name", "")).strip()
        qty = row.get("qty")
        if not name or name in seen:
            continue
        seen.add(name)
        lines.append(f"{qty} {name}")
    dest = "https://www.tcgplayer.com/massentry?productline=Magic&c=" + quote("||".join(lines), safe="")
    return "https://partner.tcgplayer.com/c/7670706/1780961/21018?u=" + quote(dest, safe="")


def head(title: str, desc: str, canonical: str, image="/img/mtg-banner-hero.jpg", extra="") -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>{e(title)}</title>
  <meta name="description" content="{e(desc)}" />
  <link rel="stylesheet" href="/css/site.css?v=mtg-1" />
  <link rel="canonical" href="{e(canonical)}" />
  <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1" />
  <meta name="theme-color" content="#9c1c28" />
  <link rel="icon" href="/img/mtg-logo-192.png" type="image/png" sizes="192x192" />
  <link rel="apple-touch-icon" href="/img/mtg-logo-192.png" sizes="192x192" />
  <link rel="manifest" href="/site.webmanifest" />
  <meta property="og:site_name" content="MTG Decklists" />
  <meta property="og:locale" content="en_US" />
  <meta property="og:type" content="website" />
  <meta property="og:title" content="{e(title)}" />
  <meta property="og:description" content="{e(desc)}" />
  <meta property="og:url" content="{e(canonical)}" />
  <meta property="og:image" content="{SITE}{image}" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="{e(title)}" />
  <meta name="twitter:description" content="{e(desc)}" />
  <meta name="twitter:image" content="{SITE}{image}" />
  {extra}
</head>
"""


def header(current="") -> str:
    def nav(href, label, key=""):
        cur = ' aria-current="page"' if current == key else ""
        return f'<a href="{href}"{cur}>{label}</a>'
    return f"""<body>
  <div class="wrap">
    <header>
      <a class="brand" href="/">
        <img class="logo" src="/img/mtg-logo-192.png" width="56" height="56" alt="MTG Decklists" />
        <div>
          <h1>MTG Decklists</h1>
          <div class="subtitle">Commander · Standard · Modern</div>
        </div>
      </a>
      <nav aria-label="Primary">
        {nav("/tier-list.html", "Tier List", "tier")}
        {nav("/formats/", "Formats", "formats")}
        {nav("/format.html", "Rules", "rules")}
        {nav("/events.html", "Events", "events")}
        {nav("/guides/", "Guides", "guides")}
        {nav("/shop/", "Shop", "shop")}
        {nav("/search.html", "Search", "search")}
        <span class="muted" title="Discord coming soon">Discord</span>
      </nav>
    </header>
"""


def footer() -> str:
    return f"""    <footer>
      © <span id="year">{YEAR}</span> MTG Decklists — Fan site, not affiliated with Wizards of the Coast.
      Magic: The Gathering and related marks are trademarks of Wizards of the Coast LLC, used here under fair-use commentary.
      <a href="/tier-list.html">Tier List</a> · <a href="/formats/">Formats</a> ·
      <a href="/format.html">Rules</a> · <a href="/search.html">Search</a> · <a href="/shop/">Shop</a> ·
      <a href="/guides/">Guides</a> · <a href="/privacy.html">Privacy</a> · <span>Discord</span>
    </footer>
  </div>
  <script src="/js/site.js?v=mtg-1"></script>
  <script src="/js/tcgplayer.js?v=mtg-1"></script>
</body>
</html>
"""


def crumb(*parts) -> str:
    bits = ['<a href="/">Home</a>']
    for href, label in parts:
        if href:
            bits.append(f'<a href="{href}">{e(label)}</a>')
        else:
            bits.append(e(label))
    return '<div class="crumb">' + " / ".join(bits) + "</div>"


def amazon_line() -> str:
    return '<p class="amazon-disclosure-line">As an Amazon Associate I earn from qualifying purchases. TCGplayer links are affiliate links.</p>'


def art_for(deck) -> tuple[str, str]:
    key = str(deck.get("id") or "")
    try:
        n = int(key)
    except ValueError:
        n = abs(hash(key))
    return ARTS[n % 3]


def recent_item(deck: dict) -> str:
    art = art_for(deck)
    colors = deck.get("colors") or ""
    return f"""<a class="recent-item" href="{deck_url(deck)}" data-colors="{e(colors)}">
  <img class="recent-leader" src="{art[0]}" alt="" />
  <div class="recent-copy">
    <div class="who">{e(unescape(deck['archetype']))}</div>
    <div class="meta muted">{e(deck.get('player') or 'Unknown')} · {e(deck.get('place') or '')} · {e(deck['event'])}</div>
  </div>
  <div class="when">{e(deck['date'])}</div>
</a>"""


def shop_card(name, note, url, img) -> str:
    return f"""<article class="shop-card">
  <a class="shop-photo-link" href="{e(url)}" target="_blank" rel="sponsored noopener noreferrer">
    <img class="shop-photo" src="/img/shop/{e(img)}" alt="{e(name)}" />
  </a>
  <div style="font-weight:800">{e(name)}</div>
  <p class="shop-note">{e(note)}</p>
  <a class="shop-buy" href="{e(url)}" target="_blank" rel="sponsored noopener noreferrer">View on Amazon</a>
</article>"""


def load_decks() -> list[dict]:
    raw = json.loads((ROOT / "data" / "decks.json").read_text())
    seen = set()
    out = []
    for d in raw:
        d["archetype"] = unescape(d.get("archetype") or "Unknown")
        d["player"] = unescape(d.get("player") or "")
        d["place"] = unescape(d.get("place") or "")
        d["event"] = unescape(d.get("event") or "")
        for row in d.get("main") or []:
            row["name"] = unescape(row.get("name") or "")
        for row in d.get("side") or []:
            row["name"] = unescape(row.get("name") or "")
        colors = identity_from_cards(d.get("main")) or identity_from_archetype(d["archetype"])
        d["colors"] = colors
        d["combo"] = combo_label(colors)
        slug = f"{slugify(d['archetype'])}-{d['id']}"
        d["page_slug"] = slug
        if d.get("format") not in FMT_BY:
            continue
        key = d["id"]
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    out.sort(key=lambda x: (x["date"], x.get("place") or ""), reverse=True)
    return out


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def page_index(decks: list[dict]) -> str:
    format_tiles = ""
    counts = Counter(d["format"] for d in decks)
    for fmt in FORMATS:
        n = counts.get(fmt["slug"], 0)
        format_tiles += f"""<a class="format-tile" href="/formats/{fmt['slug']}.html">
          <div class="name">{e(fmt['name'])}</div>
          <div class="meta">{e(fmt['short'])}</div>
          <div class="meta">{n} recent lists</div>
        </a>"""
    extra = """<script type="application/ld+json">{"@context":"https://schema.org","@type":"WebSite","name":"MTG Decklists","url":"https://mtgdecklists.com/","potentialAction":{"@type":"SearchAction","target":"https://mtgdecklists.com/search.html?q={search_term_string}","query-input":"required name=search_term_string"}}</script>"""
    return head(
        "MTG Decklists | Magic: The Gathering lists by format",
        "Magic: The Gathering decklists organized by format. Commander, Standard, and Modern on the banner; colors and recent tournament lists on every format page.",
        SITE + "/",
        extra=extra,
    ) + header("home") + f"""
    <main class="single home" role="main">
      <section class="home-splash" aria-label="MTG Decklists">
        <img class="home-splash-bg" src="/img/mtg-banner-hero.jpg" alt="Original MTG Decklists banner with a flashback mage, goblin scout, and crimson bolt" width="1400" height="636" fetchpriority="high" decoding="async">
        <div class="home-splash-art" aria-hidden="true">
          <img src="/img/art/art-flashback-mage.jpg" alt="" />
          <img src="/img/art/art-goblin-scout.jpg" alt="" />
          <img src="/img/art/art-crimson-bolt.jpg" alt="" />
        </div>
        <div class="home-splash-bar">
          <div>
            <h2>MTG Decklists</h2>
            <p class="home-splash-formats">Commander · Standard · Modern</p>
          </div>
          <p>Pick a format first. Colors, popular color combos, and that format's August–September 2026 lists live on the format page.</p>
        </div>
      </section>

      <a class="events-banner" id="events" href="/events.html">
        <div>
          <div class="kicker">Official Wizards / Magic.gg</div>
          <div class="title">Events and schedules</div>
          <div class="muted" style="color:rgba(255,255,255,0.82);margin-top:4px">RCQs, Regional Championships, Arena, and Spotlight weekends</div>
        </div>
        <div class="go">Official calendar →</div>
      </a>

      <nav class="home-big3" aria-label="Main sections">
        <a class="home-big home-big-tier" href="/tier-list.html">
          <span class="home-big-title">Tier List</span>
          <span class="home-big-note">August–September 2026 metas by format</span>
        </a>
        <a class="home-big home-big-leaders" href="#formats">
          <span class="home-big-title">Formats</span>
          <span class="home-big-note">Click a format, then see that format's lists</span>
        </a>
        <a class="home-big home-big-shop" href="/shop/">
          <span class="home-big-title">Shop</span>
          <span class="home-big-note">Sleeves, dice, playmats, and deck boxes</span>
        </a>
        <div class="discord-placeholder" role="note">
          <span class="home-big-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="28" height="28" fill="currentColor"><path d="M19.3 5.2A17.4 17.4 0 0 0 14.9 4l-.2.4a15.2 15.2 0 0 1 3.6 1.1c-3.3-1.5-6.6-1.5-9.8 0 .4-.2.9-.4 1.3-.6l-.2-.4A17.3 17.3 0 0 0 4.7 5.2C1.9 9.4 1.1 13.5 1.5 17.5a17.7 17.7 0 0 0 5.4 2.7l.7-1.1a11.5 11.5 0 0 1-2.1-1l.2-.1c1.6.7 3.3 1.2 5.1 1.2s3.5-.4 5.1-1.2l.2.1a11.5 11.5 0 0 1-2.1 1l.7 1.1a17.7 17.7 0 0 0 5.4-2.7c.5-4.6-.7-8.7-3.8-12.3ZM8.8 14.8c-1 0-1.9-.9-1.9-2s.8-2 1.9-2 1.9.9 1.9 2-.8 2-1.9 2Zm6.4 0c-1 0-1.9-.9-1.9-2s.8-2 1.9-2 1.9.9 1.9 2-.8 2-1.9 2Z"/></svg>
          </span>
          <div>
            <div class="home-big-title">Discord</div>
            <div class="home-big-note">Placeholder — invite coming soon. No link yet.</div>
          </div>
        </div>
      </nav>

      <form class="site-search home-search" method="get" action="/search.html" role="search">
        <label class="site-search-label" for="home-q">Search MTG decklists</label>
        <div class="site-search-row">
          <input id="home-q" type="search" name="q" placeholder="Format, color, player, archetype, or card" aria-label="Search MTG decklists" />
          <button type="submit">Search</button>
        </div>
      </form>

      <section class="home-leaders-flow" id="formats">
        <div class="home-leaders-intro">
          <p class="home-leaders-kicker">The formats</p>
          <div class="home-leaders-intro-row">
            <div>
              <h3>Formats</h3>
              <p>Pick a format first. Each format page opens on colors and popular color combos, then that format's recent lists.</p>
            </div>
            <a href="/formats/">All format pages →</a>
          </div>
        </div>
        <div class="card home-panel">
          <div class="format-grid">{format_tiles}</div>
        </div>
      </section>

      <p class="site-disclaimer">MTG Decklists is a fan site. Card names and tournament results are reported for commentary and news reporting. Original illustrations on this site are not official Magic: The Gathering card art. Not affiliated with Wizards of the Coast LLC.</p>
      {amazon_line()}
    </main>
""" + footer()


def page_formats_index(decks: list[dict]) -> str:
    counts = Counter(d["format"] for d in decks)
    tiles = ""
    for fmt in FORMATS:
        n = counts.get(fmt["slug"], 0)
        tiles += f"""<a class="leader-tile" href="/formats/{fmt['slug']}.html">
          <img src="{ARTS[hash(fmt['slug']) % 3][0]}" alt="" />
          <div><div class="name">{e(fmt['name'])}</div><div class="meta">{e(fmt['short'])} · {n} lists</div></div>
        </a>"""
    return head("MTG formats | MTG Decklists", "Iconic Magic: The Gathering formats with recent tournament lists.", f"{SITE}/formats/") + header("formats") + f"""
    <main class="single" role="main">
      {crumb(("/formats/", "Formats"))}
      <article class="card">
        <h2>Formats</h2>
        <p>Magic is organized by format. Commander, Standard, and Modern are the three most-played right now; Pioneer, Legacy, Vintage, and Pauper sit beside them. Open a format to see its lists.</p>
        <div class="leader-grid">{tiles}</div>
      </article>
    </main>
""" + footer()


def color_section(fmt_decks: list[dict], slug: str) -> str:
    color_counts = Counter()
    combo_counts = Counter()
    for d in fmt_decks:
        code = d.get("colors") or ""
        for c in code:
            if c in "WUBRG":
                color_counts[c] += 1
        if code:
            combo_counts[code] += 1
    chips = []
    for c, name, fn, _ in COLORS:
        n = color_counts.get(c, 0)
        chips.append(f"""<a class="mana-chip" href="/formats/{slug}.html?color={c}" style="--tile:var(--accent)">
          <img src="/img/mana/{fn}" alt="{e(name)}" />
          <span>{e(name)}</span>
          <span class="muted">{n}</span>
        </a>""")
    combos = []
    for code, n in combo_counts.most_common(10):
        combos.append(f"""<a class="combo-card" href="/formats/{slug}.html?color={code[0] if code and code[0] in 'WUBRG' else 'all'}">
          {pip_html(code)}
          <div style="font-weight:800">{e(combo_label(code))}</div>
          <div class="meta">{n} lists · {e(code or 'C')}</div>
        </a>""")
    return f"""
        <div class="section-title"><h3>Colors</h3></div>
        <p class="muted">Unique mana marks for White, Blue, Black, Red, and Green. Filter the lists below.</p>
        <div class="mana-row">{''.join(chips)}</div>
        <div class="section-title" style="margin-top:22px"><h3>Most popular color combos</h3></div>
        <p class="muted">Counted from August–September 2026 lists on this page.</p>
        <div class="combo-grid">{''.join(combos) or '<p class="muted">No constructed lists in this slice yet.</p>'}</div>
    """


def page_format(fmt: dict, decks: list[dict]) -> str:
    fmt_decks = [d for d in decks if d["format"] == fmt["slug"]]
    shown = fmt_decks[:120]
    art = ARTS[hash(fmt["slug"]) % 3]
    items = "".join(recent_item(d) for d in shown)
    more = ""
    if len(fmt_decks) > len(shown):
        more = f" · showing the latest {len(shown)} — search this format for older tables"
    return head(
        f"{fmt['name']} decklists | MTG Decklists",
        f"{fmt['name']} Magic: The Gathering lists from August and September 2026, with colors, popular color combos, and TCGPlayer buy links.",
        f"{SITE}/formats/{fmt['slug']}.html",
        image=art[0],
    ) + header("formats") + f"""
    <main class="single" role="main">
      {crumb(("/formats/", "Formats"), ("", fmt["name"]))}
      <article class="card">
        <img class="inline-art" src="{art[0]}" alt="{e(art[1])}" />
        <h2>{e(fmt['name'])}</h2>
        <p>{e(fmt['blurb'])}</p>
        <p class="muted"><a href="{e(fmt['official'])}" target="_blank" rel="noopener">Official {e(fmt['name'])} page</a> ·
        <a href="https://magic.wizards.com/en/news/announcements/banned-and-restricted-august-10-2026" target="_blank" rel="noopener">Aug 10, 2026 banned &amp; restricted</a></p>
        {color_section(fmt_decks, fmt['slug'])}
        <div class="section-title" style="margin-top:28px">
          <h3>Recent lists</h3>
          <span class="muted">{len(fmt_decks)} from Aug–Sep 2026{more}</span>
        </div>
        <div class="filter-bar" aria-label="Filter by color">
          <button type="button" data-color="all">All</button>
          <button type="button" data-color="W">White</button>
          <button type="button" data-color="U">Blue</button>
          <button type="button" data-color="B">Black</button>
          <button type="button" data-color="R">Red</button>
          <button type="button" data-color="G">Green</button>
        </div>
        <div class="recent-list">{items or '<p class="muted">Lists for this format will land here as public tables post. Until then, use the official events links above.</p>'}</div>
      </article>
    </main>
""" + footer()


def card_lines(cards, heading) -> str:
    if not cards:
        return ""
    lines = []
    for row in cards:
        name = unescape(row["name"])
        qty = row["qty"]
        href = partner_card(name)
        lines.append(f"""<li class="text-line">
          <span class="qty">{qty}</span>
          <span class="card-title">{e(name)}</span>
          <a class="buy-tcg-inline" href="{e(href)}" target="_blank" rel="noopener nofollow sponsored">Buy</a>
        </li>""")
    return f"<div><h4>{e(heading)}</h4><ul class='text-lines'>{''.join(lines)}</ul></div>"


def page_deck(deck: dict) -> str:
    art = art_for(deck)
    all_cards = (deck.get("main") or []) + (deck.get("side") or [])
    buy = partner_mass(all_cards)
    fmt = FMT_BY[deck["format"]]
    return head(
        f"{deck['archetype']} — {deck['player'] or 'list'} ({fmt['name']}) | MTG Decklists",
        f"{fmt['name']} {deck['archetype']} by {deck['player'] or 'unknown'} from {deck['event']} on {deck['date']}.",
        SITE + deck_url(deck),
        image=art[0],
    ) + header("formats") + f"""
    <main class="single" role="main">
      {crumb(("/formats/", "Formats"), (f"/formats/{deck['format']}.html", fmt["name"]), ("", deck["archetype"]))}
      <article class="card">
        <img class="inline-art" src="{art[0]}" alt="{e(art[1])}" />
        <h2>{e(deck['archetype'])}</h2>
        <p class="muted">{e(fmt['name'])} · {e(deck['event'])} · {e(deck['place'] or '')} · {e(deck['date'])}</p>
        <p><strong>{e(deck['player'] or 'Unknown pilot')}</strong> · {pip_html(deck.get('colors') or '')} {e(deck.get('combo') or '')}</p>
        <div class="buy-row">
          <a class="buy-tcg" data-buy-deck href="{e(buy)}" target="_blank" rel="noopener nofollow sponsored">Buy list on TCGplayer</a>
          <button class="copy-sim" type="button" data-copy-deck>Copy list</button>
          <a class="home-ghost" href="{e(deck['source'])}" target="_blank" rel="noopener">Source: {e(deck.get('source_name') or 'public table')}</a>
        </div>
        <p class="muted" style="margin-top:10px">Affiliate link. We may earn a commission if you buy after clicking TCGplayer. Price is the same.</p>
        <div class="text-deck">
          <div class="text-deck-cols">
            {card_lines(deck.get('main'), "Main deck")}
            {card_lines(deck.get('side'), "Sideboard")}
          </div>
        </div>
        <p class="site-disclaimer">Public tournament table transcribed for news and commentary. Not affiliated with Wizards of the Coast. Original site art is not official card art.</p>
      </article>
    </main>
""" + footer()


def page_shop(slug=None) -> str:
    if slug is None:
        cats = SHOP
        title = "Shop | Sleeves, dice, playmats, deck boxes | MTG Decklists"
        desc = "The same Amazon shop listings as One Piece Deck Base, with the same affiliate links, for sleeves, dice, playmats, and deck boxes."
        h = "Shop"
        intro = "Sleeves, dice, playmats, deck boxes, and a table extra. Same products and affiliate short links as One Piece Deck Base. Open Amazon for live price and stock."
        crumbs = crumb(("/shop/", "Shop"))
        path = "/shop/"
    else:
        cats = [c for c in SHOP if c[0] == slug]
        name = cats[0][1]
        title = f"{name} | MTG Decklists shop"
        desc = cats[0][2]
        h = name
        intro = cats[0][2] + " Open Amazon for live price and stock."
        crumbs = crumb(("/shop/", "Shop"), ("", name))
        path = f"/shop/{slug}.html"
    blocks = []
    for cat_slug, name, note, products in cats:
        more = f'<a href="/shop/{cat_slug}.html">All {e(name.lower())} →</a>' if slug is None else ""
        cards = "".join(shop_card(*p) for p in products)
        blocks.append(f"""
        <div class="section-title" style="margin-top:28px"><h3>{e(name)}</h3>{more}</div>
        <p class="muted">{e(note)}</p>
        <div class="shop-grid">{cards}</div>""")
    also = "".join(
        f'<a class="item" href="/shop/{c[0]}.html"><div><div>{e(c[1])}</div><div class="muted">Amazon shop · table gear</div></div><div class="link">Open →</div></a>'
        for c in SHOP
    )
    return head(title, desc, SITE + path) + header("shop") + f"""
    <main class="single" role="main">
      {crumbs}
      <article class="card">
        <h2>{e(h)}</h2>
        <p>{e(intro)}</p>
        {''.join(blocks)}
        <div class="section-title" style="margin-top:28px"><h3>Also in the shop</h3></div>
        <div class="list">{also}
          <a class="item" href="/formats/"><div><div>Format decklists</div><div class="muted">60-card and Commander lists</div></div><div class="link">Open →</div></a>
        </div>
        {amazon_line()}
      </article>
    </main>
""" + footer()


GUIDES = [
    ("magic-the-gathering", "Magic: The Gathering", "The trading-card game published by Wizards of the Coast. This site tracks public constructed lists by format."),
    ("standard", "Standard", "Rotating 60-card constructed. Current pool is Wilds of Eldraine forward; next rotation is with Nauctis in early 2027."),
    ("modern", "Modern", "Non-rotating constructed from Eighth Edition and Modern Horizons sets. Regional Championships starting September 11, 2026 are Modern."),
    ("pioneer", "Pioneer", "Constructed from Return to Ravnica forward. Izzet spells and green Cub decks led Pioneer after the August 2026 bans."),
    ("commander", "Commander", "100-card singleton led by a legendary creature. The most popular way to play Magic in 2026."),
    ("legacy", "Legacy", "Eternal constructed with a banned list. The Fantasticar was banned on August 10, 2026."),
    ("vintage", "Vintage", "Eternal constructed with a restricted list. The Fantasticar was restricted on August 10, 2026."),
    ("pauper", "Pauper", "Commons-only constructed. Watch Secret Lair common legality notes from Wizards."),
    ("colors", "Colors and mana", "White, blue, black, red, and green. This site uses original mana marks, not the official pentagon."),
    ("color-pairs", "Color pairs", "The ten two-color guilds plus shards and wedges. Format pages rank the combos that are actually posting."),
    ("rcq", "Regional Championship Qualifiers", "Store RCQs run August 15–November 29, 2026 in Standard or Limited. Destination RCQs may use other constructed formats."),
    ("regional-championships", "Regional Championships", "Modern constructed, starting September 11, 2026. Top finishers earn Pro Tour 2027 invites."),
    ("pro-tour", "Pro Tour", "Pro Tour Nauctis is February 26–28, 2027 at MagicCon Denver (Nauctis Draft + Modern)."),
    ("banned-restricted", "Banned and restricted", "Latest tabletop changes posted August 10, 2026. Next announcement October 12, 2026."),
    ("mtg-arena", "MTG Arena", "Digital client. September qualifiers are The Hobbit Sealed. Arena Championship 13 is October 24–25, 2026 in Standard."),
    ("wizards-of-the-coast", "Wizards of the Coast", "Publisher of Magic. This fan site is not affiliated with WotC or Hasbro."),
    ("how-to-read-a-list", "How to read a decklist", "Main deck first, sideboard after the blank line. Buy links open TCGplayer with our affiliate tag."),
    ("affiliates", "Affiliate links", "Amazon Associates on shop gear. TCGplayer partner links on every card and Buy list button."),
    ("fair-use", "Fair use and trademarks", "Tournament reporting and commentary. Original illustrations stand in for Snapcaster-like, Goblin Guide-like, and Lightning Bolt-like art."),
]


def page_guides_index() -> str:
    items = "".join(
        f'<a class="item" href="/guides/{slug}.html"><div><div>{e(name)}</div><div class="muted">{e(blurb)}</div></div><div class="link">Open →</div></a>'
        for slug, name, blurb in GUIDES
    )
    return head("Magic: The Gathering guides | MTG Decklists", "Topic pages that point back to format lists on this site.", f"{SITE}/guides/") + header("guides") + f"""
    <main class="single" role="main">
      {crumb(("/guides/", "Guides"))}
      <article class="card">
        <h2>Magic: The Gathering guides</h2>
        <p>Topic pages for formats, events, colors, and how this site uses affiliates — the same idea as OPDB guides, rewritten for Magic.</p>
        <div class="art-strip">
          <img src="/img/art/art-flashback-mage.jpg" alt="Original flashback mage" />
          <img src="/img/art/art-goblin-scout.jpg" alt="Original goblin scout" />
          <img src="/img/art/art-crimson-bolt.jpg" alt="Original crimson bolt" />
        </div>
        <div class="list">{items}</div>
      </article>
    </main>
""" + footer()


def page_guide(slug, name, blurb, decks) -> str:
    related = [d for d in decks if slug in (d["format"], slugify(d["archetype"]))][:8]
    rec = "".join(recent_item(d) for d in related) if related else ""
    art = ARTS[hash(slug) % 3]
    return head(f"{name} | MTG Decklists", blurb, f"{SITE}/guides/{slug}.html") + header("guides") + f"""
    <main class="single" role="main">
      {crumb(("/guides/", "Guides"), ("", name))}
      <article class="card">
        <img class="inline-art" src="{art[0]}" alt="{e(art[1])}" />
        <h2>{e(name)}</h2>
        <p>{e(blurb)}</p>
        <p>Lists live on the <a href="/formats/">format pages</a>. Shop gear uses the same Amazon short links as One Piece Deck Base. Card buy buttons use the same TCGplayer partner ID.</p>
        <p><a href="/format.html">Rules and banlist notes</a> · <a href="/events.html">Events</a> · <a href="/privacy.html">Privacy and disclaimer</a></p>
        {('<div class="section-title"><h3>Related lists</h3></div><div class="recent-list">'+rec+'</div>') if rec else ''}
      </article>
    </main>
""" + footer()


def page_events() -> str:
    return head(
        "MTG events and schedules | MTG Decklists",
        "Official Magic event calendar: RCQs, Regional Championships, Arena, and Spotlight weekends in 2026.",
        f"{SITE}/events.html",
    ) + header("events") + f"""
    <main class="single" role="main">
      {crumb(("", "Events"))}
      <article class="card">
        <h2>Events and schedules</h2>
        <p>These are official Wizards / Magic.gg links. We do not run events.</p>
        <div class="list">
          <a class="item" href="https://magic.wizards.com/en/news/announcements/banned-and-restricted-august-10-2026" target="_blank" rel="noopener"><div><div>Banned &amp; restricted — August 10, 2026</div><div class="muted">magic.wizards.com</div></div><div class="link">Official →</div></a>
          <a class="item" href="https://magic.gg/news/play-update-2026-27-round-2-regional-championship-promos-and-qualifiers" target="_blank" rel="noopener"><div><div>RCQs Aug 15–Nov 29, 2026</div><div class="muted">Store Standard or Limited · Magic.gg play update</div></div><div class="link">Official →</div></a>
          <a class="item" href="https://magic.gg/news/play-update-2026-27-round-2-regional-championship-promos-and-qualifiers" target="_blank" rel="noopener"><div><div>Regional Championships (Modern)</div><div class="muted">Starts Sept 11, 2026 — Baltimore, Hangzhou, then October sites</div></div><div class="link">Official →</div></a>
          <a class="item" href="https://magic.wizards.com/en/news/mtg-arena/the-hobbit-event-schedule" target="_blank" rel="noopener"><div><div>Arena: The Hobbit schedule</div><div class="muted">Premier Draft through Sept 29 · Sealed qualifiers Sept 12–20</div></div><div class="link">Official →</div></a>
          <a class="item" href="https://magic.gg/news/metagame-mentor-the-top-standard-decks-for-september-2026s-rcqs" target="_blank" rel="noopener"><div><div>Metagame Mentor: Standard RCQs</div><div class="muted">Frank Karsten, September 3, 2026</div></div><div class="link">Official →</div></a>
          <a class="item" href="https://magic.gg/news/metagame-mentor-modern-with-the-hobbit" target="_blank" rel="noopener"><div><div>Metagame Mentor: Modern + The Hobbit</div><div class="muted">August 27, 2026</div></div><div class="link">Official →</div></a>
          <a class="item" href="https://magic.wizards.com/en/formats" target="_blank" rel="noopener"><div><div>Official format hub</div><div class="muted">magic.wizards.com/en/formats</div></div><div class="link">Official →</div></a>
        </div>
        <div class="meta-strip">
          <div class="kicker">Regional Championship sites (Modern)</div>
          <ul>
            <li>Sept 11–13 — Hangzhou (Kadou) · Baltimore (Star City Games)</li>
            <li>Oct 2–4 — Ottawa (Face to Face) · Yokohama (BIG MAGIC)</li>
            <li>Oct 9–11 — Los Angeles · Ghent · Mexico City</li>
            <li>Oct 23–25 — Buenos Aires · Sydney</li>
          </ul>
          <p>Arena Championship 13 is Standard, October 24–25, 2026. Pro Tour Nauctis is February 26–28, 2027 at MagicCon Denver.</p>
        </div>
      </article>
    </main>
""" + footer()


def page_rules() -> str:
    return head(
        "MTG format rules and banlist | MTG Decklists",
        "How Standard, Modern, Pioneer, Commander, Legacy, Vintage, and Pauper work, plus the August 10, 2026 banned and restricted changes.",
        f"{SITE}/format.html",
    ) + header("rules") + f"""
    <main class="single" role="main">
      {crumb(("", "Rules"))}
      <article class="card policy">
        <h2>Formats and the banlist</h2>
        <img class="inline-art" src="/img/art/art-crimson-bolt.jpg" alt="Original crimson bolt illustration" />
        <p>Lists on this site are public constructed tables from August and September 2026 unless a page says otherwise. Commander pages are Duel Commander leagues (still 100-card singleton). Pick a format first — lists are not mixed on the homepage.</p>
        <section>
          <h3>August 10, 2026 changes</h3>
          <p>From the official <a href="https://magic.wizards.com/en/news/announcements/banned-and-restricted-august-10-2026" target="_blank" rel="noopener">banned and restricted announcement</a>:</p>
          <ul>
            <li><strong>Standard:</strong> Badgermole Cub, Stormchaser's Talent, and Gran-Gran banned.</li>
            <li><strong>Legacy:</strong> The Fantasticar banned.</li>
            <li><strong>Vintage:</strong> The Fantasticar restricted.</li>
          </ul>
          <p>Next announcement: October 12, 2026.</p>
        </section>
        <section>
          <h3>Format FAQ</h3>
          <div class="faq">
            <details open><summary>What are the three most popular formats right now?</summary><p>Commander, Standard, and Modern — those names sit on the second line of the site banner.</p></details>
            <details><summary>Where do the decklists come from?</summary><p>Public Magic Online Challenge/League tables hosted on MTGGoldfish, plus official Magic.gg Metagame Mentor aggregates. Each list page links the source.</p></details>
            <details><summary>Do buy links use affiliates?</summary><p>Yes. Shop gear uses the same Amazon Associates short links as One Piece Deck Base. Every card and “Buy list” button uses TCGplayer partner <code>c/7670706/1780961/21018</code>.</p></details>
          </div>
        </section>
      </article>
    </main>
""" + footer()


def page_privacy() -> str:
    return head(
        "Privacy Policy | MTG Decklists",
        "Privacy policy for MTG Decklists: cookies, analytics, advertising, affiliates, fair use, and Wizards of the Coast disclaimer.",
        f"{SITE}/privacy.html",
    ) + header() + f"""
    <main class="single" role="main">
      {crumb(("", "Privacy Policy"))}
      <article class="card policy">
        <h2>Privacy Policy</h2>
        <p>Last updated: September 7, 2026</p>
        <p>MTG Decklists ("we," "us," or "this site") respects your privacy. This Privacy Policy explains what information we collect when you visit mtgdecklists.com, how we use it, and the choices you have.</p>
        <section>
          <h3>Information We Collect</h3>
          <p><strong>Automatically collected information:</strong> Like most websites, we automatically collect certain information when you visit, including your IP address, browser type, device type, pages viewed, and time spent on the site. This is collected through cookies, log files, and similar technologies.</p>
          <p><strong>Information you provide:</strong> If you join our Discord (when an invite is posted) or contact us directly, any information you share there is subject to that platform's own privacy policy, not this one.</p>
          <p>We do not require account creation or collect personal information such as your name, email address, or payment details through this site.</p>
        </section>
        <section>
          <h3>Cookies</h3>
          <p>We use cookies and similar tracking technologies to understand how visitors use the site, remember basic preferences, and support advertising if ads are enabled. You can disable cookies through your browser settings.</p>
        </section>
        <section>
          <h3>Advertising</h3>
          <p>This site may display advertisements served by third-party providers, including Google AdSense. Google and its partners may use cookies to serve ads based on your prior visits. You can opt out of personalized advertising in Google's Ads Settings.</p>
        </section>
        <section>
          <h3>Affiliate partnerships</h3>
          <p>Some links on this site are affiliate links. If you buy through them, we may earn a commission. That does not change the price you pay.</p>
          <p><strong>Amazon.</strong> We are an Amazon Associate. The Shop links to Amazon for sleeves, dice, playmats, deck boxes, and table extras — the same products and short links as One Piece Deck Base — and we earn from qualifying purchases.</p>
          <p><strong>TCGplayer.</strong> We are a TCGplayer affiliate. Buy links on decklists go to TCGplayer, and we may earn a commission if you purchase after clicking them.</p>
        </section>
        <section>
          <h3>Analytics</h3>
          <p>We may use third-party analytics services (such as Google Analytics) to understand site traffic. This data is used in aggregate and is not used to personally identify you.</p>
        </section>
        <section>
          <h3>Children's Privacy</h3>
          <p>This site is not directed at children under 13, and we do not knowingly collect personal information from children under 13.</p>
        </section>
        <section>
          <h3>Third-Party Links</h3>
          <p>Our site links to third-party content, including tournament results, retailers, and (when posted) Discord. We are not responsible for the privacy practices of these external sites.</p>
        </section>
        <section>
          <h3>Fair use and trademarks</h3>
          <p>MTG Decklists reports publicly posted tournament decklists and official event schedules for news, commentary, and education. Card names, format names, and event names are used to identify Magic: The Gathering products and organized play. Original illustrations on this site are newly created and are not official Magic card art. They are inspired by iconic card <em>ideas</em> (a flashback mage, a goblin mountain scout, a red lightning spell) without copying Wizards' artwork or the official mana pentagon.</p>
          <p>Magic: The Gathering, Magic, and associated logos and mana symbols are trademarks of Wizards of the Coast LLC, a subsidiary of Hasbro, Inc. This site is not affiliated with, endorsed by, or sponsored by Wizards of the Coast, Hasbro, or any official organized-play partner.</p>
        </section>
        <section>
          <h3>Changes to This Policy</h3>
          <p>We may update this Privacy Policy from time to time. Changes will be posted on this page with an updated "Last updated" date.</p>
        </section>
        <section>
          <h3>Contact Us</h3>
          <p>If you have questions about this Privacy Policy, you can reach us through our Discord once an invite is posted. The Discord control in the header is a placeholder without a link for now.</p>
          <p>MTG Decklists is a fan site and is not affiliated with Wizards of the Coast.</p>
        </section>
      </article>
    </main>
""" + footer()


def page_search() -> str:
    return head("Search MTG decklists | MTG Decklists", "Search formats, colors, players, archetypes, and cards.", f"{SITE}/search.html") + header("search") + f"""
    <main class="single" role="main">
      {crumb(("", "Search"))}
      <article class="card">
        <h2>Search</h2>
        <form class="site-search" method="get" action="/search.html" role="search">
          <label class="site-search-label" for="q">Search MTG decklists</label>
          <div class="site-search-row">
            <input id="q" type="search" name="q" placeholder="Izzet, Landfall, Solitude, Baltimore…" />
            <button type="submit">Search</button>
          </div>
        </form>
        <p class="muted" id="search-status"></p>
        <div class="list" id="search-results"></div>
      </article>
    </main>
""" + footer()


def page_tier(decks: list[dict]) -> str:
    rows = []
    for fmt in FORMATS:
        fmt_decks = [d for d in decks if d["format"] == fmt["slug"]]
        arche = Counter(d["archetype"] for d in fmt_decks)
        if not arche:
            continue
        leaders = "".join(
            f'<a class="tier-leader" href="/formats/{fmt["slug"]}.html"><img src="{ARTS[i % 3][0]}" alt="" /><div class="name">{e(name)}</div><div class="meta">{n} lists</div></a>'
            for i, (name, n) in enumerate(arche.most_common(6))
        )
        rows.append(f'<div class="tier-row tier-s"><div class="tier-label">{e(fmt["name"][:1])}</div><div class="tier-leaders">{leaders}</div></div>')
    return head(
        "MTG tier list by format | MTG Decklists",
        "August–September 2026 Magic metagame snapshots by format, counted from lists on this site.",
        f"{SITE}/tier-list.html",
    ) + header("tier") + f"""
    <main class="single" role="main">
      {crumb(("", "Tier List"))}
      <article class="card">
        <h2>Tier list</h2>
        <p>Not a single global ranking. Each row is a format. Pictures are original site art, not official cards. Counts are from public Aug–Sep 2026 tables on this site.</p>
        <div class="tier-board">{''.join(rows)}</div>
        <p class="muted" style="margin-top:16px">For Frank Karsten's official winner's-metagame numbers see
        <a href="https://magic.gg/news/metagame-mentor-the-top-standard-decks-for-september-2026s-rcqs" target="_blank" rel="noopener">Standard RCQ Mentor</a> and
        <a href="https://magic.gg/news/metagame-mentor-modern-with-the-hobbit" target="_blank" rel="noopener">Modern Mentor</a>.</p>
      </article>
    </main>
""" + footer()


def page_404() -> str:
    return head("Page not found | MTG Decklists", "That URL is not on MTG Decklists.", f"{SITE}/404.html") + header() + f"""
    <main class="single" role="main">
      <article class="card">
        <h2>Missing page</h2>
        <p>Try <a href="/">home</a>, <a href="/formats/">formats</a>, or <a href="/search.html">search</a>.</p>
      </article>
    </main>
""" + footer()


def add_curated(decks: list[dict]) -> list[dict]:
    """Consensus lists from Magic.gg Metagame Mentor articles (Aug/Sep 2026)."""
    curated = [
        {
            "id": "mentor-std-landfall",
            "format": "standard",
            "archetype": "Mono-Green Landfall",
            "player": "Metagame Mentor aggregate",
            "place": "27.8% winner's meta",
            "event": "Magic.gg Standard RCQ primer",
            "date": "2026-09-03",
            "source": "https://magic.gg/news/metagame-mentor-the-top-standard-decks-for-september-2026s-rcqs",
            "source_name": "Magic.gg",
            "main": _parse("14 Forest 4 Escape Tunnel 4 Fabled Passage 4 Llanowar Elves 4 Sazh's Chocobo 4 Earthbender Ascension 4 Icetill Explorer 4 Mightform Harmonizer 4 Esper Origins 3 Ba Sing Se 3 Sapling Nursery 2 Meltstrider's Resolve 2 Shared Roots 1 Demolition Field 1 Keen-Eyed Curator 1 Surrak, Elusive Hunter 1 Lumbering Worldwagon"),
            "side": _parse("4 Mossborn Hydra 2 Torpor Orb 2 Meltstrider's Resolve 2 Surrak, Elusive Hunter 2 Warg Tactics 1 Keen-Eyed Curator 1 Sapling Nursery 1 Leatherhead, Swamp Stalker"),
        },
        {
            "id": "mentor-std-dimir",
            "format": "standard",
            "archetype": "Dimir Midrange",
            "player": "Metagame Mentor aggregate",
            "place": "12.1% winner's meta",
            "event": "Magic.gg Standard RCQ primer",
            "date": "2026-09-03",
            "source": "https://magic.gg/news/metagame-mentor-the-top-standard-decks-for-september-2026s-rcqs",
            "source_name": "Magic.gg",
            "main": _parse("4 Gloomlake Verge 4 Island 4 Swamp 4 Watery Grave 4 Enduring Curiosity 4 Floodpits Drowner 4 Spyglass Siren 4 Requiting Hex 4 Kaito, Bane of Nightmares 4 Dream Beavers 3 Hidden Lair 2 Restless Reef 2 The Wondrous Wasp 2 Bitter Triumph 2 Shoot the Sheriff 2 We Say Thee Nay! 2 Soulstone Sanctuary 2 Tishana's Tidebinder 1 Spell Pierce 1 Wan Shi Tong, Librarian 1 Spell Snare"),
            "side": _parse("4 Duress 2 Strategic Betrayal 2 Flashfreeze 2 Annul 2 Raven Eagle 1 Wan Shi Tong, Librarian 1 Spell Snare 1 Day of Black Sun"),
        },
        {
            "id": "mentor-mod-goryo",
            "format": "modern",
            "archetype": "Esper Goryo's",
            "player": "Metagame Mentor aggregate",
            "place": "11.0% winner's meta",
            "event": "Magic.gg Modern + The Hobbit",
            "date": "2026-08-27",
            "source": "https://magic.gg/news/metagame-mentor-modern-with-the-hobbit",
            "source_name": "Magic.gg",
            "main": _parse("4 Flooded Strand 4 Marsh Flats 4 Polluted Delta 4 Atraxa, Grand Unifier 4 Psychic Frog 4 Solitude 4 Ephemerate 4 Goryo's Vengeance 4 Quantum Riddler 3 Faithful Mending 3 Thoughtseize 2 Force of Negation 2 Prismatic Ending 2 Griselbrand 1 Godless Shrine 1 Hallowed Fountain 1 Meticulous Archive 1 Shadowy Backstreet 1 Undercity Sewers 1 Watery Grave 1 Island 1 Plains 1 Swamp 1 March of Otherworldly Light 1 Breeding Pool 1 Teferi, Time Raveler"),
            "side": _parse("3 Consign to Memory 3 Wrath of the Skies 3 Mystical Dispute 2 Clarion Conqueror 1 Teferi, Time Raveler 1 Nihil Spellbomb 1 Surgical Extraction 1 Spell Snare"),
        },
    ]
    for d in curated:
        d["colors"] = identity_from_cards(d["main"]) or identity_from_archetype(d["archetype"])
        d["combo"] = combo_label(d["colors"])
        d["page_slug"] = f"{slugify(d['archetype'])}-{d['id']}"
        decks.append(d)
    decks.sort(key=lambda x: x["date"], reverse=True)
    return decks


def _parse(blob: str) -> list[dict]:
    out = []
    for m in re.finditer(r"(\d+)\s+(.+?)(?=\s+\d+\s+|$)", blob.strip()):
        out.append({"qty": int(m.group(1)), "name": m.group(2).strip()})
    return out


def main() -> None:
    decks = add_curated(load_decks())
    decks = [d for d in decks if d.get("format") in FMT_BY]
    write(ROOT / "index.html", page_index(decks))
    write(ROOT / "formats" / "index.html", page_formats_index(decks))
    for fmt in FORMATS:
        write(ROOT / "formats" / f"{fmt['slug']}.html", page_format(fmt, decks))
    keep_pages = set()
    for deck in decks:
        path = ROOT / "decklists" / deck["format"] / f"{deck['page_slug']}.html"
        write(path, page_deck(deck))
        keep_pages.add(path.resolve())
    deck_root = ROOT / "decklists"
    if deck_root.exists():
        for path in deck_root.rglob("*.html"):
            if path.resolve() not in keep_pages:
                path.unlink()
        limited = deck_root / "limited"
        if limited.exists():
            for path in limited.rglob("*"):
                if path.is_file():
                    path.unlink()
            limited.rmdir()
    for stale in (ROOT / "formats" / "limited.html", ROOT / "guides" / "limited.html"):
        if stale.exists():
            stale.unlink()
    write(ROOT / "shop" / "index.html", page_shop())
    for slug, *_ in SHOP:
        write(ROOT / "shop" / f"{slug}.html", page_shop(slug))
    write(ROOT / "guides" / "index.html", page_guides_index())
    for slug, name, blurb in GUIDES:
        write(ROOT / "guides" / f"{slug}.html", page_guide(slug, name, blurb, decks))
    write(ROOT / "events.html", page_events())
    write(ROOT / "format.html", page_rules())
    write(ROOT / "privacy.html", page_privacy())
    write(ROOT / "search.html", page_search())
    write(ROOT / "tier-list.html", page_tier(decks))
    write(ROOT / "404.html", page_404())

    index = []
    for d in decks:
        hay = " ".join([
            d["archetype"], d.get("player") or "", d.get("event") or "", d["format"],
            d.get("combo") or "", " ".join(c["name"] for c in (d.get("main") or [])[:12]),
        ]).lower()
        index.append({
            "title": f"{d['archetype']} — {d.get('player') or 'list'}",
            "meta": f"{FMT_BY[d['format']]['name']} · {d['event']} · {d['date']}",
            "url": deck_url(d),
            "hay": hay,
        })
    for fmt in FORMATS:
        index.append({
            "title": f"{fmt['name']} format",
            "meta": fmt["short"],
            "url": f"/formats/{fmt['slug']}.html",
            "hay": f"{fmt['name']} {fmt['short']} {fmt['blurb']}".lower(),
        })
    write(ROOT / "data" / "search.json", json.dumps(index))

    urls = [
        f"{SITE}/", f"{SITE}/formats/", f"{SITE}/shop/", f"{SITE}/guides/",
        f"{SITE}/events.html", f"{SITE}/format.html", f"{SITE}/privacy.html",
        f"{SITE}/search.html", f"{SITE}/tier-list.html",
    ]
    for fmt in FORMATS:
        urls.append(f"{SITE}/formats/{fmt['slug']}.html")
    for d in decks:
        urls.append(SITE + deck_url(d))
    sitemap = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        sitemap.append(f"<url><loc>{e(u)}</loc><lastmod>{TODAY}</lastmod></url>")
    sitemap.append("</urlset>")
    write(ROOT / "sitemap.xml", "\n".join(sitemap))
    write(ROOT / "robots.txt", "User-agent: *\nAllow: /\nSitemap: https://mtgdecklists.com/sitemap.xml\n")
    write(ROOT / "site.webmanifest", json.dumps({
        "name": "MTG Decklists",
        "short_name": "MTG Lists",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#f6f3ef",
        "theme_color": "#9c1c28",
        "icons": [{"src": "/img/mtg-logo-192.png", "sizes": "192x192", "type": "image/png"}],
    }, indent=2))
    print(f"built {len(decks)} decks, {len(list((ROOT/'decklists').rglob('*.html')))} deck pages")


if __name__ == "__main__":
    main()
