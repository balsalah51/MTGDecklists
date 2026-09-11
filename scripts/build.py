#!/usr/bin/env python3
"""Generate the static MTG Decklists site from scraped tournament lists."""
from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://mtgdecklists.com"
TODAY = "2026-09-11"
YEAR = "2026"
TARGET_PER_FORMAT = 800
TARGET_COMMANDER = 828
LIST_PAGE_SIZE = 80
DATE_WINDOW = "June–September 2026"

FORMATS = [
    {
        "slug": "standard",
        "name": "Standard",
        "short": "Rotating 60-card constructed",
        "flavor": "The living plane — today's cards, this year's story.",
        "blurb": "Standard is rotating 60-card constructed. The current pool is Wilds of Eldraine forward; there is no fall 2026 rotation. Store RCQs through November 29, 2026 are Standard. Lists on this site are public Challenge and league tables from June–September 2026.",
        "official": "https://magic.wizards.com/en/formats/standard",
        "popular": True,
        "art": "/img/art/lore-plains-citadel.jpg",
        "art_alt": "Original plains citadel illustration",
    },
    {
        "slug": "modern",
        "name": "Modern",
        "short": "Non-rotating from Eighth Edition on",
        "flavor": "A twenty-year library of staples, still being rewritten.",
        "blurb": "Modern is non-rotating constructed from Eighth Edition and Modern Horizons. It is the constructed format for the September–October 2026 Regional Championships. Lists here are public Challenge and league tables from June–September 2026.",
        "official": "https://magic.wizards.com/en/formats/modern",
        "popular": True,
        "art": "/img/art/art-flashback-mage.jpg",
        "art_alt": "Original flashback mage illustration",
    },
    {
        "slug": "pioneer",
        "name": "Pioneer",
        "short": "Return to Ravnica forward",
        "flavor": "Where the guilds still remember their first war.",
        "blurb": "Pioneer sits between Standard and Modern (Return to Ravnica forward). After the Cori-Steel Cutter ban, Izzet spells shells and green Badgermole Cub piles split the winner's metagame in August 2026. Lists here are public tables from June–September 2026.",
        "official": "https://magic.wizards.com/en/formats/pioneer",
        "popular": False,
        "art": "/img/art/lore-island-spires.jpg",
        "art_alt": "Original island spires illustration",
    },
    {
        "slug": "commander",
        "name": "Commander",
        "short": "100-card singleton, most-played format",
        "flavor": "One legend. Ninety-nine unique spells. A table of stories.",
        "blurb": "Commander is 100-card singleton led by a legendary creature. Tables here are public Duel Commander (1v1) leagues from May–September 2026. Color identity is the same rule used at a four-player Commander night. Open a commander page for every list of that legend.",
        "official": "https://magic.wizards.com/en/formats/commander",
        "popular": True,
        "art": "/img/art/lore-forest-cathedral.jpg",
        "art_alt": "Original forest cathedral illustration",
    },
    {
        "slug": "legacy",
        "name": "Legacy",
        "short": "Vintage-adjacent, banned list not restricted list",
        "flavor": "The eternal battlefield, minus what the ban list forbids.",
        "blurb": "Legacy is eternal constructed with a banned list. The Fantasticar was banned in Legacy on August 10, 2026.",
        "official": "https://magic.wizards.com/en/formats/legacy",
        "popular": False,
        "art": "/img/art/lore-swamp-lantern.jpg",
        "art_alt": "Original swamp lantern illustration",
    },
    {
        "slug": "vintage",
        "name": "Vintage",
        "short": "The original constructed format",
        "flavor": "Power is restricted, never forgotten.",
        "blurb": "Vintage uses a restricted list instead of a wide ban list. The Fantasticar was restricted in Vintage on August 10, 2026.",
        "official": "https://magic.wizards.com/en/formats/vintage",
        "popular": False,
        "art": "/img/art/art-crimson-bolt.jpg",
        "art_alt": "Original crimson bolt illustration",
    },
    {
        "slug": "pauper",
        "name": "Pauper",
        "short": "Commons only",
        "flavor": "The most democratic constructed format — commons only.",
        "blurb": "Pauper is constructed using only cards printed at common. Wizards also clarified Secret Lair Zeta commons legality in September 2026.",
        "official": "https://magic.wizards.com/en/formats/pauper",
        "popular": False,
        "art": "/img/art/art-goblin-scout.jpg",
        "art_alt": "Original goblin scout illustration",
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

COLOR_LORE = [
    {
        "code": "W", "name": "White", "pip": "mana-white.png",
        "art": "/img/art/lore-plains-citadel.jpg",
        "land": "Plains",
        "line": "Peace, order, and the open plains.",
        "body": "White magic builds communities, laws, and shining walls. It heals, protects, and asks a table to stand in the same light. On this site it shows up as soldiers, enchantments, and tidy mana bases.",
    },
    {
        "code": "U", "name": "Blue", "pip": "mana-blue.png",
        "art": "/img/art/lore-island-spires.jpg",
        "land": "Islands",
        "line": "Knowledge, patience, and the turning tide.",
        "body": "Blue magic wants another draw, another counter, another turn to think. Island lists on this site are the control seats, the tempo mages, and the flashback spells that replay yesterday.",
    },
    {
        "code": "B", "name": "Black", "pip": "mana-black.png",
        "art": "/img/art/lore-swamp-lantern.jpg",
        "land": "Swamps",
        "line": "Ambition, sacrifice, and the lantern in the fog.",
        "body": "Black magic pays life and cards for power. It is removal, tutors, and the quiet promise that someone else will lose first. Midrange and reanimator lists wear it well.",
    },
    {
        "code": "R", "name": "Red", "pip": "mana-red.png",
        "art": "/img/art/lore-mountain-forge.jpg",
        "land": "Mountains",
        "line": "Freedom, impulse, and the mountain's fire.",
        "body": "Red magic does not wait. It is goblin scouts, prowess triggers, and the bolt that ends a game before the other player finishes shuffling. Charming, loud, and often 1-drop deep.",
    },
    {
        "code": "G", "name": "Green", "pip": "mana-green.png",
        "art": "/img/art/lore-forest-cathedral.jpg",
        "land": "Forests",
        "line": "Growth, instinct, and the forest's strength.",
        "body": "Green magic wants more land, larger creatures, and a board that feels like a canopy. Landfall, elves, and ramp lists are its current dialect in Standard and beyond.",
    },
]

GUILD_LORE = [
    ("WU", "Azorius", "Law and structure. Azorius lists want the game to stay on script — counters, flyers, and a tidy end step."),
    ("UB", "Dimir", "Secrecy and information. Dimir midrange mills, trades, and always has one more answer in hand."),
    ("BR", "Rakdos", "Pleasure and pain. Rakdos wants to attack, discard, and turn life totals into a countdown."),
    ("RG", "Gruul", "Instinct and riot. Gruul is stompy creatures, extra lands, and a race the control player did not schedule."),
    ("GW", "Selesnya", "Community and growth. Selesnya tokens, enchantments, and go-wide boards that look like a festival."),
    ("WB", "Orzhov", "Debt and devotion. Orzhov drains, taxes, and turns every trade into a better rate."),
    ("UR", "Izzet", "Genius and impulse. Izzet spells, prowess, and the joy of a stacked trigger on turn three."),
    ("BG", "Golgari", "Life and decay. Golgari midrange is the graveyard as a second hand."),
    ("RW", "Boros", "Justice at a sprint. Boros energy, equipment, and the red-white wish to win this combat."),
    ("GU", "Simic", "Adaptation. Simic grows, draws, and mutates the board until the math is unfair."),
    ("WUB", "Esper", "The shard of control: white's law, blue's answers, black's cost."),
    ("UBR", "Grixis", "The shard of ambition: card advantage with a cruel streak."),
    ("BRG", "Jund", "The shard of survival: midrange that eats whatever is across the table."),
    ("RGW", "Naya", "The shard of the wild: big creatures and honest combat."),
    ("GWU", "Bant", "The shard of the citadel: value, blink, and a board that never quite dies."),
    ("WBG", "Abzan", "Endurance. Abzan is attrition, greasefang engines, and outlasting the loud decks."),
    ("URW", "Jeskai", "Cunning. Jeskai lessons, tempo, and the spell that is also a creature."),
    ("BGU", "Sultai", "Cunning from the swamp: graveyards, value, and a long game."),
    ("RWB", "Mardu", "Speed and sacrifice. Mardu wants the first strike and the last drain."),
    ("GUR", "Temur", "Elemental tempo: card draw strapped to a large green threat."),
]

ARTS = [
    ("/img/art/art-flashback-mage.jpg", "Original flashback mage illustration"),
    ("/img/art/art-goblin-scout.jpg", "Original goblin scout illustration"),
    ("/img/art/art-crimson-bolt.jpg", "Original crimson bolt illustration"),
    ("/img/art/lore-plains-citadel.jpg", "Original plains citadel illustration"),
    ("/img/art/lore-island-spires.jpg", "Original island spires illustration"),
    ("/img/art/lore-swamp-lantern.jpg", "Original swamp lantern illustration"),
    ("/img/art/lore-mountain-forge.jpg", "Original mountain forge illustration"),
    ("/img/art/lore-forest-cathedral.jpg", "Original forest cathedral illustration"),
]

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

BASICS = {
    "plains", "island", "swamp", "mountain", "forest", "wastes",
    "snow-covered plains", "snow-covered island", "snow-covered swamp",
    "snow-covered mountain", "snow-covered forest", "snow-covered wastes",
}
SCRYFALL_CACHE = ROOT / "data" / "scryfall_cards.json"
SCRYFALL_UA = "MTGDecklistsBot/1.0 (+https://mtgdecklists.com)"


def json_ld(data) -> str:
    return '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=True) + "</script>"


def breadcrumb_ld(parts: list[tuple[str, str]]) -> dict:
    items = [{"@type": "ListItem", "position": 1, "name": "Home", "item": SITE + "/"}]
    for i, (href, name) in enumerate(parts, start=2):
        node = {"@type": "ListItem", "position": i, "name": name}
        if href:
            node["item"] = SITE + href if href.startswith("/") else href
        items.append(node)
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items}


def website_ld() -> dict:
    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebSite",
                "name": "MTG Decklists",
                "url": SITE + "/",
                "description": "Public Magic: The Gathering decklists by format, with Commander, Standard, and Modern first.",
                "potentialAction": {
                    "@type": "SearchAction",
                    "target": SITE + "/search.html?q={search_term_string}",
                    "query-input": "required name=search_term_string",
                },
            },
            {
                "@type": "Organization",
                "name": "MTG Decklists",
                "url": SITE + "/",
                "logo": SITE + "/img/mtg-logo-192.png",
            },
        ],
    }


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


def head(title: str, desc: str, canonical: str, image="/img/mtg-banner-hero.jpg", extra="", og_type="website", image_alt="MTG Decklists original banner art") -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <script>
    (function(){{
      try {{
        var m = document.cookie.match(/(?:^|; )mtg-theme=(dark|light)/);
        var t = m ? m[1] : "light";
        document.documentElement.setAttribute("data-theme", t);
        document.documentElement.style.colorScheme = t;
      }} catch (err) {{}}
    }})();
  </script>
  <title>{e(title)}</title>
  <meta name="description" content="{e(desc)}" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@500;700;800&family=Source+Sans+3:ital,wght@0,400;0,600;0,700;0,800;1,400;1,600&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="/css/site.css?v=mtg-7" />
  <link rel="canonical" href="{e(canonical)}" />
  <meta name="google-adsense-account" content="ca-pub-1074015774205047" />
  <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-1074015774205047" crossorigin="anonymous"></script>
  <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1" />
  <meta name="theme-color" content="#9c1c28" />
  <link rel="icon" href="/img/mtg-logo-192.png" type="image/png" sizes="192x192" />
  <link rel="apple-touch-icon" href="/img/mtg-logo-192.png" sizes="192x192" />
  <link rel="manifest" href="/site.webmanifest" />
  <meta property="og:site_name" content="MTG Decklists" />
  <meta property="og:locale" content="en_US" />
  <meta property="og:type" content="{e(og_type)}" />
  <meta property="og:title" content="{e(title)}" />
  <meta property="og:description" content="{e(desc)}" />
  <meta property="og:url" content="{e(canonical)}" />
  <meta property="og:image" content="{e(abs_url(image))}" />
  <meta property="og:image:alt" content="{e(image_alt)}" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="{e(title)}" />
  <meta name="twitter:description" content="{e(desc)}" />
  <meta name="twitter:image" content="{e(abs_url(image))}" />
  {extra}
</head>
"""


def header(current="") -> str:
    def nav(href, label, key=""):
        cur = ' aria-current="page"' if current == key else ""
        return f'<a href="{href}"{cur}>{label}</a>'
    pips = "".join(
        f'<img src="/img/mana/{fn}" alt="" width="18" height="18" />'
        for _, _, fn, _ in COLORS
    )
    return f"""<body>
  <a class="skip-link" href="#main">Skip to lists</a>
  <div class="wrap">
    <header>
      <a class="brand" href="/">
        <img class="logo" src="/img/mtg-logo-192.png" width="56" height="56" alt="MTG Decklists" />
        <div>
          <p class="site-name">MTG Decklists</p>
          <div class="subtitle">Public constructed results · Commander · Standard · Modern</div>
        </div>
      </a>
      <button type="button" class="theme-toggle" id="theme-toggle" aria-pressed="false" aria-label="Switch to dark mode">
        <span data-theme-when="light">Dark mode</span>
        <span data-theme-when="dark">Light mode</span>
      </button>
      <nav aria-label="Primary">
        {nav("/tier-list.html", "Tier List", "tier")}
        {nav("/formats/", "Formats", "formats")}
        {nav("/commanders/", "Commanders", "commanders")}
        {nav("/format.html", "Rules", "rules")}
        {nav("/events.html", "Events", "events")}
        {nav("/guides/", "Guides", "guides")}
        {nav("/shop/", "Shop", "shop")}
        {nav("/search.html", "Search", "search")}
        <span class="muted" title="Discord coming soon">Discord</span>
      </nav>
      <div class="header-mana" aria-hidden="true">{pips}</div>
    </header>
"""


def footer() -> str:
    return f"""    <footer>
      <span class="footer-flavor">Public tournament tables, organized by format.</span>
      © <span id="year">{YEAR}</span> MTG Decklists — Fan site, not affiliated with Wizards of the Coast.
      Magic: The Gathering and related marks are trademarks of Wizards of the Coast LLC, used here under fair-use commentary.
      Sources: MTGGoldfish public tables · Magic.gg Metagame Mentor.
      <a href="/tier-list.html">Tier List</a> · <a href="/formats/">Formats</a> ·
      <a href="/commanders/">Commanders</a> ·
      <a href="/format.html">Rules</a> · <a href="/search.html">Search</a> · <a href="/shop/">Shop</a> ·
      <a href="/guides/">Guides</a> · <a href="/guides/methodology.html">Methodology</a> ·
      <a href="/guides/advertising.html">Ads</a> · <a href="/privacy.html">Privacy</a>
    </footer>
  </div>
  <script src="/js/site.js?v=mtg-4"></script>
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


def abs_url(path: str) -> str:
    if str(path).startswith(("http://", "https://")):
        return path
    return SITE + path


def is_skip_land_name(name: str) -> bool:
    n = unescape(name).lower().strip()
    if n in BASICS or n in LAND_PIPS:
        return True
    return bool(re.match(r"^(snow-covered )?(plains|island|swamp|mountain|forest|wastes)$", n))


def face_candidates(deck: dict) -> list[str]:
    arche = unescape(deck.get("archetype") or "").lower()
    parts = [p.strip() for p in re.split(r"\s*/\s*", arche) if p.strip()]
    scored = []
    for row in deck.get("main") or []:
        name = unescape(row.get("name") or "").strip()
        qty = int(row.get("qty") or 0)
        if not name or is_skip_land_name(name):
            continue
        ln = name.lower()
        score = qty
        if qty >= 4:
            score += 100
        elif qty == 3:
            score += 30
        elif qty == 2:
            score += 8
        if ln == arche or (arche and (ln in arche or arche in ln)):
            score += 90
        for part in parts:
            if part and (part == ln or part in ln or ln in part):
                score += 80
                break
        scored.append((score, qty, name))
    scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
    seen, out = set(), []
    for _, _, name in scored:
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
        if len(out) >= 8:
            break
    return out


def _scryfall_images(card: dict) -> dict:
    uris = card.get("image_uris") or {}
    if not uris:
        faces = card.get("card_faces") or []
        if faces:
            uris = faces[0].get("image_uris") or {}
    type_line = card.get("type_line") or ""
    if not type_line and card.get("card_faces"):
        type_line = card["card_faces"][0].get("type_line") or ""
    is_land = "Land" in type_line and "Creature" not in type_line
    return {
        "name": card.get("name") or "",
        "type_line": type_line,
        "land": is_land,
        "small": uris.get("small") or "",
        "normal": uris.get("normal") or "",
        "art_crop": uris.get("art_crop") or "",
    }


def load_scryfall(names: set[str]) -> dict:
    cache = {}
    if SCRYFALL_CACHE.exists():
        try:
            cache = json.loads(SCRYFALL_CACHE.read_text())
        except json.JSONDecodeError:
            cache = {}
    missing = [n for n in sorted(names) if n and n not in cache]
    if missing:
        print(f"scryfall: lookup {len(missing)} cards", flush=True)
        for i in range(0, len(missing), 75):
            chunk = missing[i:i + 75]
            body = json.dumps({"identifiers": [{"name": n} for n in chunk]}).encode()
            req = urllib.request.Request(
                "https://api.scryfall.com/cards/collection",
                data=body,
                headers={
                    "User-Agent": SCRYFALL_UA,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=40) as r:
                    payload = json.loads(r.read().decode("utf-8", "replace"))
            except Exception as err:
                print("scryfall fail", err, flush=True)
                time.sleep(0.4)
                continue
            cards = payload.get("data") or []
            for card in cards:
                info = _scryfall_images(card)
                keys = {card.get("name") or "", info.get("name") or ""}
                for face in card.get("card_faces") or []:
                    keys.add(face.get("name") or "")
                for key in keys:
                    if key:
                        cache[key] = info
            for ident in payload.get("not_found") or []:
                nm = ident.get("name") or ""
                if nm:
                    cache[nm] = {"name": nm, "land": True, "small": "", "normal": ""}
            by_lower = {k.lower(): v for k, v in cache.items() if k}
            for n in chunk:
                if n in cache:
                    continue
                hit = by_lower.get(n.lower())
                if not hit:
                    for key, info in cache.items():
                        if key and (n.lower() in key.lower() or key.lower().startswith(n.lower())):
                            hit = info
                            break
                cache[n] = hit or {"name": n, "land": False, "small": "", "normal": ""}
            time.sleep(0.12)
        SCRYFALL_CACHE.parent.mkdir(parents=True, exist_ok=True)
        SCRYFALL_CACHE.write_text(json.dumps(cache, indent=2, sort_keys=True))
    return cache


def assign_faces(decks: list[dict]) -> None:
    names = {n for d in decks for n in face_candidates(d)}
    catalog = load_scryfall(names)
    by_lower = {k.lower(): v for k, v in catalog.items() if k}
    for deck in decks:
        face = None
        for name in face_candidates(deck):
            info = catalog.get(name) or by_lower.get(name.lower())
            if not info or info.get("land") or not (info.get("small") or info.get("normal")):
                continue
            face = info
            break
        deck["face"] = face or {}
    print("  faces", sum(1 for d in decks if (d.get("face") or {}).get("small")), "of", len(decks), flush=True)


def art_for(deck, size: str = "small") -> tuple[str, str]:
    face = deck.get("face") or {}
    src = ""
    if size == "large":
        src = face.get("normal") or face.get("small") or face.get("art_crop") or ""
    else:
        src = face.get("small") or face.get("normal") or face.get("art_crop") or ""
    if src:
        return src, face.get("name") or "Card"
    key = str(deck.get("id") or "")
    try:
        n = int(key)
    except ValueError:
        n = abs(hash(key))
    return ARTS[n % 3]


def recent_item(deck: dict) -> str:
    art = art_for(deck, "small")
    colors = deck.get("colors") or ""
    alt = art[1] if not art[0].startswith("/img/art/") else ""
    arche = unescape(deck["archetype"])
    return f"""<a class="recent-item" href="{deck_url(deck)}" data-colors="{e(colors)}" data-archetype="{e(arche.lower())}">
  <img class="recent-leader" src="{e(art[0])}" alt="{e(alt)}" width="46" height="64" loading="lazy" decoding="async" />
  <div class="recent-copy">
    <div class="who">{e(arche)}</div>
    <div class="meta muted">{e(deck.get('player') or 'Unknown')} · {e(deck.get('place') or '')} · {e(deck['event'])}</div>
  </div>
  <div class="when">{e(deck['date'])}</div>
</a>"""


def date_window(fmt: str | None = None) -> str:
    if fmt == "commander":
        return "May–September 2026"
    return DATE_WINDOW


def archetype_url(fmt: str, name: str) -> str:
    return f"/archetypes/{fmt}-{slugify(name)}.html"


def format_stats(fmt_decks: list[dict]) -> dict:
    events = {d.get("event") for d in fmt_decks if d.get("event")}
    pilots = {d.get("player") for d in fmt_decks if d.get("player")}
    dates = [d.get("date") or "" for d in fmt_decks if d.get("date")]
    arche = {unescape(d.get("archetype") or "") for d in fmt_decks}
    return {
        "lists": len(fmt_decks),
        "events": len(events),
        "pilots": len(pilots),
        "archetypes": len(arche),
        "start": min(dates) if dates else "",
        "end": max(dates) if dates else "",
    }


def stats_bar(fmt_decks: list[dict]) -> str:
    s = format_stats(fmt_decks)
    span = f"{s['start']} – {s['end']}" if s["start"] else DATE_WINDOW
    cells = [
        (str(s["lists"]), "lists"),
        (str(s["events"]), "events"),
        (str(s["pilots"]), "pilots"),
        (str(s["archetypes"]), "archetypes"),
        (span, "sample"),
    ]
    bits = "".join(
        f'<div class="stat"><strong>{e(v)}</strong><span>{e(label)}</span></div>'
        for v, label in cells
    )
    return f'<div class="stat-bar" role="group" aria-label="Sample size">{bits}</div>'


def archetype_rank(fmt_decks: list[dict], min_n: int = 3, cap: int = 24) -> list[tuple[str, list[dict]]]:
    by = defaultdict(list)
    for d in fmt_decks:
        by[unescape(d.get("archetype") or "Unknown")].append(d)
    ranked = sorted(by.items(), key=lambda kv: (-len(kv[1]), kv[0].lower()))
    return [(name, rows) for name, rows in ranked if len(rows) >= min_n][:cap]


def metagame_table(fmt: dict, fmt_decks: list[dict]) -> str:
    total = len(fmt_decks) or 1
    rows = []
    for i, (name, group) in enumerate(archetype_rank(fmt_decks), 1):
        pct = 100.0 * len(group) / total
        sample = group[0]
        rows.append(
            f"""<tr>
              <td class="num">{i}</td>
              <td><a href="{archetype_url(fmt['slug'], name)}">{e(name)}</a></td>
              <td class="num">{len(group)}</td>
              <td class="num">{pct:.1f}%</td>
              <td class="muted">{e(sample.get('combo') or '')}</td>
            </tr>"""
        )
    if not rows:
        return ""
    return f"""
        <div class="section-title" style="margin-top:22px">
          <h2>Metagame snapshot</h2>
          <span class="muted">Share of {len(fmt_decks)} lists on this site</span>
        </div>
        <p class="muted">Counted from public tables, not from an official winner’s-metagame report. Open an archetype for every list of that name.</p>
        <div class="table-wrap"><table class="meta-table">
          <thead><tr><th>#</th><th>Archetype</th><th>Lists</th><th>Share</th><th>Colors</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table></div>"""


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


def cap_per_format(decks: list[dict], n: int | None = None) -> list[dict]:
    by = defaultdict(list)
    for d in decks:
        by[d["format"]].append(d)
    out = []
    for fmt in FMT_BY:
        cap = TARGET_COMMANDER if fmt == "commander" else TARGET_PER_FORMAT
        group = by.get(fmt, [])
        curated = [d for d in group if str(d.get("id") or "").startswith("mentor-")]
        rest = [d for d in group if not str(d.get("id") or "").startswith("mentor-")]
        chosen, seen = [], set()
        for d in curated + rest:
            key = d["id"]
            if key in seen:
                continue
            seen.add(key)
            chosen.append(d)
            if len(chosen) >= cap:
                break
        out.extend(chosen)
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
        format_tiles += f"""<a class="format-tile format-{e(fmt['slug'])}" href="/formats/{fmt['slug']}.html">
          <img class="format-tile-art" src="{e(fmt['art'])}" alt="" />
          <div class="format-tile-body">
            <div class="name">{e(fmt['name'])}</div>
            <p class="flavor">{e(fmt['flavor'])}</p>
            <div class="meta">{e(fmt['short'])}</div>
            <div class="meta">{n} recent lists</div>
          </div>
        </a>"""
    pie = ""
    for c in COLOR_LORE:
        pie += f"""<a class="pie-card pie-{e(c['code'].lower())}" href="/guides/colors.html#{e(c['name'].lower())}">
          <img src="{e(c['art'])}" alt="{e(c['art'].split('/')[-1].replace('-', ' ').replace('.jpg', ''))}" />
          <div class="pie-copy">
            <img class="pip" src="/img/mana/{e(c['pip'])}" alt="" />
            <h4>{e(c['name'])}</h4>
            <p>{e(c['line'])}</p>
          </div>
        </a>"""
    extra = json_ld(website_ld())
    return head(
        "MTG Decklists | Magic: The Gathering Commander, Standard, and Modern lists",
        "Public Magic: The Gathering decklists by format. Commander, Standard, and Modern first, then Pioneer, Legacy, Vintage, and Pauper. Color pie, guilds, and TCGplayer buy links on every list.",
        SITE + "/",
        extra=extra,
        image_alt="Original five-color pentagon banner with a flashback mage and goblin scout",
    ) + header("home") + f"""
    <main class="single home" id="main" role="main">
      <section class="home-splash" aria-label="MTG Decklists">
        <img class="home-splash-bg" src="/img/mtg-banner-hero.jpg" alt="Original MTG Decklists banner with a flashback mage, goblin scout, crimson bolt, and five-color pentagon" width="1400" height="636" fetchpriority="high" decoding="async">
        <div class="home-splash-veil" aria-hidden="true"></div>
        <div class="home-splash-art" aria-hidden="true">
          <img src="/img/art/art-flashback-mage.jpg" alt="" />
          <img src="/img/art/art-goblin-scout.jpg" alt="" />
          <img src="/img/art/art-crimson-bolt.jpg" alt="" />
        </div>
        <div class="home-splash-bar">
          <div>
            <p class="kicker">Public tables · sourced lists</p>
            <h1>Public Magic decklists, by format</h1>
            <p class="home-splash-formats">Commander · Standard · Modern</p>
          </div>
          <p>Every list is a sourced public table. Open a format for the metagame, then the lists.</p>
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
        <a class="home-big home-big-commanders" href="/commanders/">
          <span class="home-big-kicker">100-card singleton</span>
          <span class="home-big-title">Commanders</span>
          <span class="home-big-note">One page per legend — {sum(1 for d in decks if d['format']=='commander')} Duel Commander lists</span>
        </a>
        <a class="home-big home-big-leaders" href="#formats">
          <span class="home-big-kicker">Choose a format</span>
          <span class="home-big-title">Formats</span>
          <span class="home-big-note">Metagame snapshot, then every list in that format</span>
        </a>
        <a class="home-big home-big-tier" href="/tier-list.html">
          <span class="home-big-kicker">The metagame</span>
          <span class="home-big-title">Tier List</span>
          <span class="home-big-note">{DATE_WINDOW} metas by format</span>
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
        <label class="site-search-label" for="home-q">Search lists</label>
        <div class="site-search-row">
          <input id="home-q" type="search" name="q" placeholder="Brigid, Izzet, Landfall, Solitude…" aria-label="Search MTG decklists" />
          <button type="submit">Search</button>
        </div>
      </form>

      <section class="lore-pie" id="color-pie">
        <div class="lore-intro">
          <p class="home-leaders-kicker">The color pie</p>
          <h3>Five colors. Infinite lists.</h3>
          <p>White seeks peace. Blue seeks knowledge. Black seeks power. Red seeks freedom. Green seeks growth. Every list on this site is one of those philosophies, shuffled and sleeved.</p>
          <p class="flavor">Original landscapes stand in for plains, islands, swamps, mountains, and forests — not official card art.</p>
        </div>
        <div class="pie-grid">{pie}</div>
      </section>

      <section class="home-leaders-flow" id="formats">
        <div class="home-leaders-intro">
          <p class="home-leaders-kicker">Formats</p>
          <div class="home-leaders-intro-row">
            <div>
              <h3>Pick a format first</h3>
              <p>Commander, Standard, and Modern lead. Pioneer, Legacy, Vintage, and Pauper sit beside them. Each page opens on a counted metagame, then that format’s lists.</p>
            </div>
            <div class="home-leaders-links">
              <a href="/formats/">All format pages →</a>
              <a href="/commanders/">Commander legends →</a>
            </div>
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
        tiles += f"""<a class="leader-tile format-{e(fmt['slug'])}" href="/formats/{fmt['slug']}.html">
          <img src="{e(fmt['art'])}" alt="" />
          <div>
            <div class="name">{e(fmt['name'])}</div>
            <p class="flavor">{e(fmt['flavor'])}</p>
            <div class="meta">{e(fmt['short'])} · {n} lists</div>
          </div>
        </a>"""
    return head("MTG formats | MTG Decklists", "Standard, Modern, Pioneer, Commander, Legacy, Vintage, and Pauper — public lists, counted metagames, and sources.", f"{SITE}/formats/") + header("formats") + f"""
    <main class="single" id="main" role="main">
      {crumb(("/formats/", "Formats"))}
      <article class="card">
        <h1>Formats</h1>
        <p>Magic is organized by format. Open one to see a counted metagame from the public tables on this site, then every list in that sample.</p>
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
        <div class="section-title"><h3>The color pie</h3></div>
        <p class="flavor">White, blue, black, red, and green — five philosophies, counted from the lists below.</p>
        <p class="muted">Original mana marks for this site, not the official pentagon. Filter the tables by color.</p>
        <div class="mana-row">{''.join(chips)}</div>
        <div class="section-title" style="margin-top:22px"><h3>Most popular color combos</h3></div>
        <p class="muted">Guilds, shards, and wedges counted from the lists on this page.</p>
        <div class="combo-grid">{''.join(combos) or '<p class="muted">No constructed lists in this slice yet.</p>'}</div>
    """


def page_format(fmt: dict, decks: list[dict]) -> str:
    fmt_decks = [d for d in decks if d["format"] == fmt["slug"]]
    art = (fmt.get("art") or ARTS[0][0], fmt.get("art_alt") or "")
    items = "".join(recent_item(d) for d in fmt_decks)
    window = date_window(fmt["slug"])
    commander_hub = ""
    if fmt["slug"] == "commander":
        commander_hub = """
        <p><a href="/commanders/">Browse by commander</a> — one page per legend, with every public list we have for that name.</p>
        <p class="muted">These are Duel Commander (1v1) league tables. Color identity and the 100-card singleton rule are the same as a four-player Commander night. Partner commanders are listed under both names when the source reports them that way.</p>
        """
    extra = json_ld(breadcrumb_ld([("/formats/", "Formats"), (f"/formats/{fmt['slug']}.html", fmt["name"])])) + json_ld({
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": f"{fmt['name']} decklists",
        "url": f"{SITE}/formats/{fmt['slug']}.html",
        "description": fmt["blurb"],
        "numberOfItems": len(fmt_decks),
    })
    return head(
        f"{fmt['name']} decklists ({len(fmt_decks)}) | MTG Decklists",
        f"{fmt['name']} Magic: The Gathering lists from {window}: counted metagame, color identity, and TCGplayer buy links on every list.",
        f"{SITE}/formats/{fmt['slug']}.html",
        image=art[0],
        extra=extra,
        image_alt=art[1] or fmt["name"],
    ) + header("formats") + f"""
    <main class="single" id="main" role="main">
      {crumb(("/formats/", "Formats"), ("", fmt["name"]))}
      <article class="card format-page format-{e(fmt['slug'])}">
        <div class="format-masthead">
          <img src="{art[0]}" alt="{e(art[1])}" />
          <div>
            <p class="kicker">{e(fmt['short'])}</p>
            <h1>{e(fmt['name'])}</h1>
            <p class="lede">{e(fmt['blurb'])}</p>
          </div>
        </div>
        {stats_bar(fmt_decks)}
        {commander_hub}
        <p class="muted"><a href="{e(fmt['official'])}" target="_blank" rel="noopener">Official {e(fmt['name'])} rules</a> ·
        <a href="https://magic.wizards.com/en/news/announcements/banned-and-restricted-august-10-2026" target="_blank" rel="noopener">Aug 10, 2026 banned &amp; restricted</a> ·
        <a href="/guides/methodology.html">How we count</a></p>
        {metagame_table(fmt, fmt_decks)}
        {color_section(fmt_decks, fmt['slug'])}
        <div class="section-title" style="margin-top:28px">
          <h2>Lists</h2>
          <span class="muted">{len(fmt_decks)} from {e(window)}</span>
        </div>
        <div class="list-tools">
          <label class="list-filter-label" for="list-filter">Filter lists</label>
          <input id="list-filter" type="search" placeholder="Archetype, player, or event" autocomplete="off" />
        </div>
        <div class="filter-bar" aria-label="Filter by color">
          <button type="button" data-color="all">All</button>
          <button type="button" data-color="W">White</button>
          <button type="button" data-color="U">Blue</button>
          <button type="button" data-color="B">Black</button>
          <button type="button" data-color="R">Red</button>
          <button type="button" data-color="G">Green</button>
        </div>
        <div class="recent-list" data-page-size="{LIST_PAGE_SIZE}">{items or '<p class="muted">Lists for this format will land here as public tables post.</p>'}</div>
        <p class="muted" id="list-status"></p>
        <button type="button" class="list-more" hidden>Show more lists</button>
      </article>
    </main>
""" + footer()


def commander_groups(decks: list[dict]) -> list[tuple[str, list[dict]]]:
    cmd = [d for d in decks if d["format"] == "commander"]
    by = defaultdict(list)
    for d in cmd:
        by[d["archetype"]].append(d)
    ranked = sorted(by.items(), key=lambda kv: (-len(kv[1]), kv[0].lower()))
    return ranked[:200]


def commander_url(name: str) -> str:
    return f"/commanders/{slugify(name)}.html"


def page_commanders_index(decks: list[dict]) -> str:
    groups = commander_groups(decks)
    tiles = ""
    for name, rows in groups:
        sample = rows[0]
        art = art_for(sample, "small")
        colors = sample.get("colors") or ""
        tiles += f"""<a class="leader-tile" href="{commander_url(name)}">
          <img src="{e(art[0])}" alt="{e(art[1] if not art[0].startswith('/img/art/') else '')}" />
          <div>
            <div class="name">{e(name)}</div>
            <p class="flavor">{e(sample.get('combo') or '')} · {pip_html(colors)}</p>
            <div class="meta">{len(rows)} lists</div>
          </div>
        </a>"""
    extra = json_ld(breadcrumb_ld([("/commanders/", "Commanders")])) + json_ld({
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": "Commander legends",
        "url": SITE + "/commanders/",
        "numberOfItems": len(groups),
        "mainEntity": {
            "@type": "ItemList",
            "numberOfItems": len(groups),
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": i + 1,
                    "name": name,
                    "url": SITE + commander_url(name),
                }
                for i, (name, _rows) in enumerate(groups)
            ],
        },
    }) + json_ld({
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": "Is this EDH or Duel Commander?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "These lists are public Magic Online Duel Commander (1v1) league tables. The same 100-card singleton and color-identity rules apply at a four-player Commander night.",
                },
            },
            {
                "@type": "Question",
                "name": "How does a commander get a page on this site?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "Every unique legend that posted in the May–September 2026 tables we scraped gets a landing page with every list for that name.",
                },
            },
        ],
    })
    return head(
        "Commander decklists by legend | MTG Decklists",
        f"{len(groups)} Commander (EDH / Duel Commander) legends with public lists from May–September 2026. Color identity, recent tables, and TCGplayer buy links.",
        f"{SITE}/commanders/",
        extra=extra,
        image="/img/art/lore-forest-cathedral.jpg",
        image_alt="Original forest cathedral illustration",
    ) + header("commanders") + f"""
    <main class="single" id="main" role="main">
      {crumb(("/commanders/", "Commanders"))}
      <article class="card">
        <h1>Commanders</h1>
        <p>Every page is a commander that posted in public Duel Commander tables on this site. Open a legend for every list, color identity, and a buy link. The full sample is on the <a href="/formats/commander.html">Commander format page</a>.</p>
        <p class="muted">{len(groups)} legends · {sum(len(r) for _, r in groups)} lists</p>
        <div class="leader-grid commander-grid">{tiles}</div>
        <div class="faq" style="margin-top:28px">
          <details open><summary>Is this EDH or Duel Commander?</summary><p>Public Magic Online Duel Commander (1v1) league tables. Color identity and the 100-card singleton rule are the same as a four-player Commander night; the lists themselves are the 1v1 dialect.</p></details>
          <details><summary>How does a commander get a page?</summary><p>Every unique legend in the May–September 2026 tables on this site gets a landing page. Open a name to see every list, then buy the pile on TCGplayer.</p></details>
        </div>
      </article>
    </main>
""" + footer()


def page_commander(name: str, rows: list[dict]) -> str:
    sample = rows[0]
    art = art_for(sample, "large")
    colors = sample.get("colors") or ""
    combo = sample.get("combo") or combo_label(colors)
    items = "".join(recent_item(d) for d in rows)
    extra = json_ld(breadcrumb_ld([("/commanders/", "Commanders"), (commander_url(name), name)])) + json_ld({
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": f"{name} Commander decklists",
        "url": SITE + commander_url(name),
        "about": name,
        "numberOfItems": len(rows),
    })
    return head(
        f"{name} Commander decklists ({len(rows)}) | MTG Decklists",
        f"{name} is a {combo} Commander. {len(rows)} public Duel Commander lists from May–September 2026, with color identity and TCGplayer buy links.",
        SITE + commander_url(name),
        image=art[0],
        extra=extra,
        og_type="article",
        image_alt=art[1] or name,
    ) + header("commanders") + f"""
    <main class="single" id="main" role="main">
      {crumb(("/commanders/", "Commanders"), ("", name))}
      <article class="card">
        <img class="inline-art card-face" src="{e(art[0])}" alt="{e(art[1])}" />
        <p class="kicker">Commander · {e(combo)}</p>
        <h1>{e(name)}</h1>
        <p class="flavor">A 100-card singleton legend. Color identity {pip_html(colors)} {e(colors or 'C')}.</p>
        <p>{e(name)} posted {len(rows)} time{'s' if len(rows) != 1 else ''} in the public Duel Commander tables on this site. The same 100-card singleton rules apply at a four-player Commander night — these lists are the 1v1 league dialect of that format.</p>
        <p><a href="/formats/commander.html">All Commander lists</a> · <a href="/guides/commander.html">Commander guide</a></p>
        <div class="section-title" style="margin-top:22px"><h2>Recent lists</h2><span class="muted">{len(rows)}</span></div>
        <div class="recent-list" data-page-size="{LIST_PAGE_SIZE}">{items}</div>
        <p class="muted" id="list-status"></p>
        <button type="button" class="list-more" hidden>Show more lists</button>
      </article>
    </main>
""" + footer()


def page_archetype(fmt: dict, name: str, rows: list[dict]) -> str:
    sample = rows[0]
    art = art_for(sample, "large")
    total = len(rows)
    extra = json_ld(breadcrumb_ld([
        ("/formats/", "Formats"),
        (f"/formats/{fmt['slug']}.html", fmt["name"]),
        (archetype_url(fmt["slug"], name), name),
    ])) + json_ld({
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": f"{name} — {fmt['name']}",
        "url": SITE + archetype_url(fmt["slug"], name),
        "about": name,
        "numberOfItems": total,
    })
    return head(
        f"{name} {fmt['name']} decklists ({total}) | MTG Decklists",
        f"{total} public {fmt['name']} {name} lists from {date_window(fmt['slug'])}, with color identity and TCGplayer buy links.",
        SITE + archetype_url(fmt["slug"], name),
        image=art[0],
        extra=extra,
        image_alt=art[1] or name,
    ) + header("formats") + f"""
    <main class="single" id="main" role="main">
      {crumb(("/formats/", "Formats"), (f"/formats/{fmt['slug']}.html", fmt["name"]), ("", name))}
      <article class="card">
        <img class="inline-art card-face" src="{e(art[0])}" alt="{e(art[1])}" />
        <p class="kicker">{e(fmt['name'])} · {e(sample.get('combo') or '')}</p>
        <h1>{e(name)}</h1>
        <p>{e(name)} posted {total} time{'s' if total != 1 else ''} in the {e(fmt['name'])} sample on this site ({e(date_window(fmt['slug']))}).</p>
        {stats_bar(rows)}
        <p><a href="/formats/{e(fmt['slug'])}.html">All {e(fmt['name'])} lists</a></p>
        <div class="section-title" style="margin-top:22px"><h2>Lists</h2><span class="muted">{total}</span></div>
        <div class="recent-list" data-page-size="{LIST_PAGE_SIZE}">{''.join(recent_item(d) for d in rows)}</div>
        <p class="muted" id="list-status"></p>
        <button type="button" class="list-more" hidden>Show more lists</button>
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


def page_deck(deck: dict, related: list[dict] | None = None) -> str:
    art = art_for(deck, "large")
    card_class = "inline-art card-face" if not art[0].startswith("/img/art/") else "inline-art"
    all_cards = (deck.get("main") or []) + (deck.get("side") or [])
    buy = partner_mass(all_cards)
    fmt = FMT_BY[deck["format"]]
    arche = unescape(deck["archetype"])
    sibs = [d for d in (related or []) if d.get("id") != deck.get("id")][:6]
    related_html = ""
    if sibs:
        related_html = (
            '<div class="section-title" style="margin-top:28px"><h3>Same archetype</h3>'
            f'<a href="{archetype_url(deck["format"], arche)}">All {e(arche)} lists →</a></div>'
            f'<div class="recent-list">{"".join(recent_item(d) for d in sibs)}</div>'
        )
    extra = json_ld(breadcrumb_ld([
        ("/formats/", "Formats"),
        (f"/formats/{deck['format']}.html", fmt["name"]),
        (deck_url(deck), arche),
    ])) + json_ld({
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": f"{arche} — {deck.get('player') or 'list'}",
        "datePublished": deck.get("date") or TODAY,
        "dateModified": TODAY,
        "author": {"@type": "Person", "name": deck.get("player") or "Unknown"},
        "about": arche,
        "isPartOf": {"@type": "WebSite", "name": "MTG Decklists", "url": SITE + "/"},
    })
    arch_link = (
        f'<p><a href="{commander_url(arche)}">All {e(arche)} Commander lists</a></p>'
        if deck["format"] == "commander"
        else f'<p><a href="{archetype_url(deck["format"], arche)}">All {e(fmt["name"])} {e(arche)} lists</a></p>'
    )
    return head(
        f"{arche} decklist — {deck['player'] or 'list'} ({fmt['name']}) | MTG Decklists",
        f"{fmt['name']} {arche} by {deck['player'] or 'unknown'} from {deck['event']} on {deck['date']}. Full main deck and sideboard with TCGplayer buy links.",
        SITE + deck_url(deck),
        image=art[0],
        extra=extra,
        og_type="article",
        image_alt=art[1] or arche,
    ) + header("formats") + f"""
    <main class="single" id="main" role="main">
      {crumb(("/formats/", "Formats"), (f"/formats/{deck['format']}.html", fmt["name"]), ("", arche))}
      <article class="card">
        <img class="{card_class}" src="{e(art[0])}" alt="{e(art[1])}" />
        <h1>{e(arche)}</h1>
        <p>{e(fmt['name'])} · {e(deck['event'])} · {e(deck.get('place') or '')} · {e(deck['date'])}</p>
        <p><strong>{e(deck['player'] or 'Unknown pilot')}</strong> · {pip_html(deck.get('colors') or '')} {e(deck.get('combo') or '')}</p>
        {arch_link}
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
        {related_html}
        <p class="site-disclaimer">Public tournament table transcribed for news and commentary. Card images identify the list and come from Scryfall. Not affiliated with Wizards of the Coast. Banner art on this site is original, not official card art.</p>
      </article>
    </main>
""" + footer()


def page_shop(slug=None) -> str:
    if slug is None:
        cats = SHOP
        title = "Shop | Sleeves, dice, playmats, deck boxes | MTG Decklists"
        desc = "The same Amazon shop listings as One Piece Deck Base, with the same affiliate links, for sleeves, dice, playmats, and deck boxes."
        h = "Shop"
        intro = "Gear for the table — sleeves, dice, playmats, and boxes in the five colors. Same Amazon listings as One Piece Deck Base. Open Amazon for live price and stock."
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
    <main class="single" id="main" role="main">
      {crumbs}
      <article class="card">
        <h1>{e(h)}</h1>
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
    ("colors", "Colors and mana", "White, blue, black, red, and green — five philosophies of Magic. This site uses original mana marks, not the official pentagon."),
    ("color-pairs", "Color pairs", "The ten two-color guilds plus shards and wedges. Format pages rank the combos that are actually posting."),
    ("rcq", "Regional Championship Qualifiers", "Store RCQs run August 15–November 29, 2026 in Standard or Limited. Destination RCQs may use other constructed formats."),
    ("regional-championships", "Regional Championships", "Modern constructed, starting September 11, 2026. Top finishers earn Pro Tour 2027 invites."),
    ("pro-tour", "Pro Tour", "Pro Tour Nauctis is February 26–28, 2027 at MagicCon Denver (Nauctis Draft + Modern)."),
    ("banned-restricted", "Banned and restricted", "Latest tabletop changes posted August 10, 2026. Next announcement October 12, 2026."),
    ("mtg-arena", "MTG Arena", "Digital client. September qualifiers are The Hobbit Sealed. Arena Championship 13 is October 24–25, 2026 in Standard."),
    ("wizards-of-the-coast", "Wizards of the Coast", "Publisher of Magic. This fan site is not affiliated with WotC or Hasbro."),
    ("how-to-read-a-list", "How to read a decklist", "Main deck first, sideboard after the blank line. Buy links open TCGplayer with our affiliate tag."),
    ("methodology", "Methodology", "How this site counts lists: public tables, date windows, Duel Commander vs EDH, and what a metagame share means here."),
    ("affiliates", "Affiliate links", "Amazon Associates on shop gear. TCGplayer partner links on every card and Buy list button."),
    ("advertising", "Ads and ad networks", "Google AdSense is live. Nitro, Media.net, Playwire, and TCG affiliates are the next networks this site can apply for."),
    ("fair-use", "Fair use and trademarks", "Tournament reporting and commentary. Original illustrations stand in for Snapcaster-like, Goblin Guide-like, and Lightning Bolt-like art."),
]


def page_guides_index() -> str:
    items = "".join(
        f'<a class="item" href="/guides/{slug}.html"><div><div>{e(name)}</div><div class="muted">{e(blurb)}</div></div><div class="link">Open →</div></a>'
        for slug, name, blurb in GUIDES
    )
    return head("Magic: The Gathering guides | MTG Decklists", "Lore, formats, colors, events, and how this site uses affiliates.", f"{SITE}/guides/") + header("guides") + f"""
    <main class="single" id="main" role="main">
      {crumb(("/guides/", "Guides"))}
      <article class="card">
        <h1>Guides</h1>
        <p>Format notes, the color pie, organized play, and how this site counts lists and uses affiliates.</p>
        <div class="art-strip">
          <img src="/img/art/art-flashback-mage.jpg" alt="Original flashback mage" />
          <img src="/img/art/art-goblin-scout.jpg" alt="Original goblin scout" />
          <img src="/img/art/art-crimson-bolt.jpg" alt="Original crimson bolt" />
          <img src="/img/art/lore-forest-cathedral.jpg" alt="Original forest cathedral" />
        </div>
        <div class="list">{items}</div>
      </article>
    </main>
""" + footer()


def guide_extra(slug: str) -> str:
    if slug == "colors":
        cards = []
        for c in COLOR_LORE:
            cards.append(f"""<article class="lore-block" id="{e(c['name'].lower())}">
              <img src="{e(c['art'])}" alt="" />
              <div>
                <p class="kicker">{e(c['land'])}</p>
                <h3><img class="pip" src="/img/mana/{e(c['pip'])}" alt="" /> {e(c['name'])}</h3>
                <p class="flavor">{e(c['line'])}</p>
                <p>{e(c['body'])}</p>
              </div>
            </article>""")
        return "<div class='lore-stack'>" + "".join(cards) + "</div>"
    if slug == "color-pairs":
        bits = []
        for code, name, body in GUILD_LORE:
            bits.append(f"""<article class="combo-card lore-guild">
              {pip_html(code)}
              <div style="font-weight:800">{e(name)}</div>
              <div class="meta">{e(code)}</div>
              <p>{e(body)}</p>
            </article>""")
        return "<div class='combo-grid guild-lore'>" + "".join(bits) + "</div>"
    if slug in FMT_BY:
        fmt = FMT_BY[slug]
        more = ""
        if slug == "commander":
            more = '<p><a href="/commanders/">Browse Commander lists by legend</a> — one SEO page per commander on this site.</p>'
        return f"<p class='flavor'>{e(fmt.get('flavor') or '')}</p><p>{e(fmt['blurb'])}</p>{more}"
    if slug == "methodology":
        return """
        <div class="section-title"><h2>What we publish</h2></div>
        <p>This site republishes public constructed decklists for news and commentary. We do not run events and we do not claim official winner’s-metagame numbers unless a page cites Magic.gg Metagame Mentor.</p>
        <ul>
          <li><strong>Source.</strong> Magic Online Challenge, Challenge 32, and league tables hosted on MTGGoldfish, plus three Magic.gg Metagame Mentor consensus lists.</li>
          <li><strong>Date window.</strong> Constructed formats: June–September 2026. Commander: May–September 2026 Duel Commander leagues.</li>
          <li><strong>Cap.</strong> Up to 800 lists per constructed format and 828 Commander lists, spread across events so a single league cannot fill the sample.</li>
          <li><strong>Commander.</strong> Tables are Duel Commander (1v1). Color identity and 100-card singleton are the same rules as EDH; the lists themselves are the 1v1 dialect.</li>
        </ul>
        <div class="section-title" style="margin-top:22px"><h2>How share is counted</h2></div>
        <p>An archetype’s share on a format page is that name’s count divided by the number of lists on this site for that format. It is a sample of public tables, not a weighted winner’s metagame. Names follow the source (Goldfish’s deck title).</p>
        <p>Card images identify lists and come from Scryfall. Banner art is original and is not official Magic card art.</p>
        """
    if slug == "advertising":
        return """
        <div class="section-title"><h2>What is live today</h2></div>
        <ul>
          <li><strong>Google AdSense</strong> (publisher <code>ca-pub-1074015774205047</code>) — Auto ads on every page. No traffic minimum. Already in <code>ads.txt</code>.</li>
          <li><strong>Amazon Associates</strong> — Shop sleeves, dice, playmats, and boxes. Same short links as One Piece Deck Base.</li>
          <li><strong>TCGplayer partner</strong> — Every card and “Buy list” button. Partner <code>c/7670706/1780961/21018</code>.</li>
        </ul>
        <div class="section-title" style="margin-top:22px"><h2>Display networks this site can apply for</h2></div>
        <p>Do not paste a second display network over AdSense without that network’s approval. Most premium networks <em>replace</em> AdSense rather than stack with it.</p>
        <div class="list">
          <a class="item" href="https://nitropay.com/publishers/" target="_blank" rel="noopener"><div><div>Nitro (NitroPay)</div><div class="muted">Best TCG fit. Overwolf’s gaming network already serves Moxfield, Magicspoiler, and other tabletop fan sites. Apply when traffic is real; they handle gaming-safe ads and typically replace AdSense.</div></div><div class="link">Apply →</div></a>
          <a class="item" href="https://www.media.net/publishers/" target="_blank" rel="noopener"><div><div>Media.net</div><div class="muted">Yahoo/Bing contextual ads. No official traffic minimum. English-language, text-heavy pages. Can run as an AdSense alternative, not a stacked overlay.</div></div><div class="link">Apply →</div></a>
          <a class="item" href="https://www.playwire.com/publishers" target="_blank" rel="noopener"><div><div>Playwire</div><div class="muted">Gaming and entertainment header bidding. Strong for fan sites once sessions are steady. Replaces AdSense rather than stacking on top of it.</div></div><div class="link">Apply →</div></a>
          <a class="item" href="https://www.ezoic.com/" target="_blank" rel="noopener"><div><div>Ezoic</div><div class="muted">Header bidding + layout tests. Use when the site has steady sessions. Typically replaces AdSense rather than sitting beside it.</div></div><div class="link">Apply →</div></a>
          <a class="item" href="https://www.publift.com/" target="_blank" rel="noopener"><div><div>Publift / Setupad</div><div class="muted">Managed header bidding once pageviews grow. Higher RPM than raw AdSense; application required.</div></div><div class="link">Apply →</div></a>
        </div>
        <div class="section-title" style="margin-top:22px"><h2>TCG affiliates (no display ads)</h2></div>
        <ul>
          <li><a href="https://www.cardkingdom.com/affiliates" target="_blank" rel="noopener">Card Kingdom affiliates</a> — Paper singles. Complements TCGplayer.</li>
          <li><a href="https://www.coolstuffinc.com/" target="_blank" rel="noopener">CoolStuffInc</a> — Paper singles and sealed product.</li>
          <li><a href="https://partner.ebay.com/" target="_blank" rel="noopener">eBay Partner Network</a> — Singles and collections.</li>
        </ul>
        <p>After Nitro or Media.net approval, add their lines to <code>ads.txt</code> and a snippet in the site header. Until then, AdSense Auto ads plus the two affiliate programs are the stack.</p>
        <p class="muted">Skip popunder / push networks (Monetag, Adsterra pop, HilltopAds) — they hurt a fan TCG site’s reputation and AdSense standing.</p>
        <div class="section-title" style="margin-top:22px"><h2>What can sit next to AdSense</h2></div>
        <p>Google allows non-Google ads and affiliate links on the same page, as long as the page is still mostly content. Amazon Associates and TCGplayer are already stacked that way.</p>
        <p>Media.net can add separate display units next to Auto ads if placements do not overlap. Nitro, Ezoic, Playwire, and Publift replace Auto ads and keep Google demand inside their auction — do not paste a second display tag beside AdSense without that network’s approval.</p>
        """
    return ""


def page_guide(slug, name, blurb, decks) -> str:
    related = [d for d in decks if slug in (d["format"], slugify(d["archetype"]))][:8]
    rec = "".join(recent_item(d) for d in related) if related else ""
    if slug in FMT_BY:
        art = (FMT_BY[slug]["art"], FMT_BY[slug].get("art_alt") or "")
    elif slug == "colors":
        art = ("/img/art/lore-plains-citadel.jpg", "Original plains citadel illustration")
    elif slug == "color-pairs":
        art = ("/img/art/lore-island-spires.jpg", "Original island spires illustration")
    else:
        art = ARTS[hash(slug) % len(ARTS)]
    extra = guide_extra(slug)
    return head(f"{name} | MTG Decklists", blurb, f"{SITE}/guides/{slug}.html", image=art[0]) + header("guides") + f"""
    <main class="single" id="main" role="main">
      {crumb(("/guides/", "Guides"), ("", name))}
      <article class="card">
        <img class="inline-art" src="{art[0]}" alt="{e(art[1])}" />
        <h1>{e(name)}</h1>
        <p>{e(blurb)}</p>
        {extra}
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
    <main class="single" id="main" role="main">
      {crumb(("", "Events"))}
      <article class="card">
        <h1>Events and schedules</h1>
        <p class="flavor">The competitive calendar is the other half of the spellbook — RCQs, Regional Championships, and Arena weekends.</p>
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
    <main class="single" id="main" role="main">
      {crumb(("", "Rules"))}
      <article class="card policy">
        <h1>Formats and the banlist</h1>
        <img class="inline-art" src="/img/art/art-crimson-bolt.jpg" alt="Original crimson bolt illustration" />
        <p class="flavor">Every format is a different promise about which cards are legal — and which stories still get to be told.</p>
        <p>Lists on this site are public constructed tables from June–September 2026 unless a page says otherwise. Commander pages are Duel Commander leagues (May–September; still 100-card singleton). Pick a format first — lists are not mixed on the homepage.</p>
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
    <main class="single" id="main" role="main">
      {crumb(("", "Privacy Policy"))}
      <article class="card policy">
        <h1>Privacy Policy</h1>
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
          <p>We use a first-party cookie named <code>mtg-theme</code> to remember whether you chose light mode or dark mode on this site. It stores only the values <code>light</code> or <code>dark</code>, lasts up to one year, and is not used for advertising or tracking. You can delete it in your browser settings; the site will then default to light mode.</p>
          <p>We may also use cookies and similar tracking technologies to understand how visitors use the site and to support advertising if ads are enabled. You can disable cookies through your browser settings.</p>
        </section>
        <section>
          <h3>Advertising</h3>
          <p>This site displays advertisements served by Google AdSense (publisher <code>ca-pub-1074015774205047</code>). Google and its partners may use cookies to serve ads based on your prior visits. You can opt out of personalized advertising in Google's Ads Settings.</p>
          <p>We may later add a gaming-safe display network such as NitroPay or Media.net. Those networks would appear in <code>ads.txt</code> and on the <a href="/guides/advertising.html">ads and ad networks</a> page if they go live. We will not stack a second display network over AdSense without that network’s approval.</p>
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
          <p>MTG Decklists reports publicly posted tournament decklists and official event schedules for news, commentary, and education. Card names, format names, and event names are used to identify Magic: The Gathering products and organized play. List and deck-page thumbnails use publicly available card images (via Scryfall) to identify those lists. Banner and format illustrations on this site are newly created and are not official Magic card art. They are inspired by iconic card <em>ideas</em> (a flashback mage, a goblin mountain scout, a red lightning spell) without copying Wizards' artwork or the official mana pentagon.</p>
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
    <main class="single" id="main" role="main">
      {crumb(("", "Search"))}
      <article class="card">
        <h1>Search</h1>
        <p>Name a format, color, player, commander, or card. The index is built from the lists on this site.</p>
        <form class="site-search" method="get" action="/search.html" role="search">
          <label class="site-search-label" for="q">Search MTG decklists</label>
          <div class="site-search-row">
            <input id="q" type="search" name="q" placeholder="Brigid, Izzet, Landfall, Solitude…" />
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
        sample_by = {}
        for d in fmt_decks:
            sample_by.setdefault(d["archetype"], d)
        leaders = []
        for name, n in arche.most_common(6):
            sample = sample_by.get(name) or fmt_decks[0]
            art = art_for(sample, "small")
            alt = art[1] if not art[0].startswith("/img/art/") else ""
            leaders.append(
                f'<a class="tier-leader" href="{archetype_url(fmt["slug"], unescape(name))}"><img src="{e(art[0])}" alt="{e(alt)}" /><div class="name">{e(unescape(name))}</div><div class="meta">{n} lists</div></a>'
            )
        rows.append(
            f'<div class="tier-row tier-s format-{e(fmt["slug"])}"><div class="tier-label" title="{e(fmt["name"])}">{e(fmt["name"][:1])}</div><div class="tier-leaders">{"".join(leaders)}</div></div>'
        )
    return head(
        "MTG tier list by format | MTG Decklists",
        f"{DATE_WINDOW} Magic metagame snapshots by format, counted from lists on this site.",
        f"{SITE}/tier-list.html",
    ) + header("tier") + f"""
    <main class="single" id="main" role="main">
      {crumb(("", "Tier List"))}
      <article class="card">
        <h1>Tier list</h1>
        <p>Each row is a format. Counts are the public tables on this site, not an official winner’s-metagame report. Open an archetype for every list of that name.</p>
        <p class="muted">Portraits are a 4-of (or face card) from a recent list. Sample window: {DATE_WINDOW} (Commander May–September).</p>
        <div class="tier-board">{''.join(rows)}</div>
        <p class="muted" style="margin-top:16px">For Frank Karsten's official winner's-metagame numbers see
        <a href="https://magic.gg/news/metagame-mentor-the-top-standard-decks-for-september-2026s-rcqs" target="_blank" rel="noopener">Standard RCQ Mentor</a> and
        <a href="https://magic.gg/news/metagame-mentor-modern-with-the-hobbit" target="_blank" rel="noopener">Modern Mentor</a>.</p>
      </article>
    </main>
""" + footer()


def page_404() -> str:
    return head("Page not found | MTG Decklists", "That URL is not on MTG Decklists.", f"{SITE}/404.html") + header() + f"""
    <main class="single" id="main" role="main">
      <article class="card">
        <h1>Missing page</h1>
        <p>That URL is not on this site. Try <a href="/">home</a>, <a href="/commanders/">commanders</a>, <a href="/formats/">formats</a>, or <a href="/search.html">search</a>.</p>
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
    decks = cap_per_format(add_curated(load_decks()), TARGET_PER_FORMAT)
    decks = [d for d in decks if d.get("format") in FMT_BY]
    assign_faces(decks)
    write(ROOT / "index.html", page_index(decks))
    write(ROOT / "formats" / "index.html", page_formats_index(decks))
    for fmt in FORMATS:
        write(ROOT / "formats" / f"{fmt['slug']}.html", page_format(fmt, decks))
    keep_arch = set()
    arch_root = ROOT / "archetypes"
    for fmt in FORMATS:
        fmt_decks = [d for d in decks if d["format"] == fmt["slug"]]
        for name, rows in archetype_rank(fmt_decks):
            path = arch_root / f"{fmt['slug']}-{slugify(name)}.html"
            write(path, page_archetype(fmt, name, rows))
            keep_arch.add(path.resolve())
    if arch_root.exists():
        for path in arch_root.glob("*.html"):
            if path.resolve() not in keep_arch:
                path.unlink()
    write(ROOT / "commanders" / "index.html", page_commanders_index(decks))
    keep_cmd = set()
    for name, rows in commander_groups(decks):
        path = ROOT / "commanders" / f"{slugify(name)}.html"
        write(path, page_commander(name, rows))
        keep_cmd.add(path.resolve())
    cmd_root = ROOT / "commanders"
    if cmd_root.exists():
        for path in cmd_root.glob("*.html"):
            if path.name != "index.html" and path.resolve() not in keep_cmd:
                path.unlink()
    by_arch = defaultdict(list)
    for d in decks:
        by_arch[(d["format"], unescape(d.get("archetype") or ""))].append(d)
    keep_pages = set()
    for deck in decks:
        path = ROOT / "decklists" / deck["format"] / f"{deck['page_slug']}.html"
        write(path, page_deck(deck, by_arch.get((deck["format"], unescape(deck.get("archetype") or "")))))
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
    for fmt in FORMATS:
        fmt_decks = [d for d in decks if d["format"] == fmt["slug"]]
        for name, rows in archetype_rank(fmt_decks):
            index.append({
                "title": f"{name} — {fmt['name']}",
                "meta": f"{fmt['name']} · {len(rows)} lists",
                "url": archetype_url(fmt["slug"], name),
                "hay": f"{name} {fmt['name']} {fmt['slug']} {rows[0].get('combo') or ''}".lower(),
            })
    for name, rows in commander_groups(decks):
        index.append({
            "title": f"{name} Commander",
            "meta": f"Commander · {len(rows)} lists",
            "url": commander_url(name),
            "hay": f"{name} commander edh duel {rows[0].get('combo') or ''}".lower(),
        })
    index.append({
        "title": "Commanders",
        "meta": "Commander lists by legend",
        "url": "/commanders/",
        "hay": "commander edh duel commander legends",
    })
    for slug, name, blurb in GUIDES:
        index.append({
            "title": name,
            "meta": "Guide",
            "url": f"/guides/{slug}.html",
            "hay": f"{name} {blurb}".lower(),
        })
    write(ROOT / "data" / "search.json", json.dumps(index))

    urls = [
        f"{SITE}/", f"{SITE}/formats/", f"{SITE}/commanders/", f"{SITE}/shop/", f"{SITE}/guides/",
        f"{SITE}/events.html", f"{SITE}/format.html", f"{SITE}/privacy.html",
        f"{SITE}/search.html", f"{SITE}/tier-list.html",
    ]
    for fmt in FORMATS:
        urls.append(f"{SITE}/formats/{fmt['slug']}.html")
        fmt_decks = [d for d in decks if d["format"] == fmt["slug"]]
        for name, _rows in archetype_rank(fmt_decks):
            urls.append(SITE + archetype_url(fmt["slug"], name))
    for name, _rows in commander_groups(decks):
        urls.append(SITE + commander_url(name))
    for slug, *_ in SHOP:
        urls.append(f"{SITE}/shop/{slug}.html")
    for slug, *_ in GUIDES:
        urls.append(f"{SITE}/guides/{slug}.html")
    for d in decks:
        urls.append(SITE + deck_url(d))
    sitemap = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for i, u in enumerate(urls):
        pri = "1.0" if u == SITE + "/" else ("0.9" if "/formats/" in u or "/commanders" in u or "/archetypes/" in u else ("0.7" if "/guides/" in u else "0.6"))
        sitemap.append(f"<url><loc>{e(u)}</loc><lastmod>{TODAY}</lastmod><changefreq>weekly</changefreq><priority>{pri}</priority></url>")
    sitemap.append("</urlset>")
    write(ROOT / "sitemap.xml", "\n".join(sitemap))
    write(ROOT / "robots.txt", "User-agent: *\nAllow: /\nSitemap: https://mtgdecklists.com/sitemap.xml\n")
    write(ROOT / "ads.txt", "# Google AdSense (live). Add NitroPay / Media.net lines after approval.\ngoogle.com, pub-1074015774205047, DIRECT, f08c47fec0942fa0\n")
    write(ROOT / "site.webmanifest", json.dumps({
        "name": "MTG Decklists",
        "short_name": "MTG Lists",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#f3e6d2",
        "theme_color": "#9c1c28",
        "icons": [{"src": "/img/mtg-logo-192.png", "sizes": "192x192", "type": "image/png"}],
    }, indent=2))
    print(f"built {len(decks)} decks, {len(list((ROOT/'decklists').rglob('*.html')))} deck pages")


if __name__ == "__main__":
    main()
