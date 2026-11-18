import argparse
import csv
import json
import time
import re
import html
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
import os
import tempfile
from urllib.parse import urljoin, quote_plus, urlparse, urlunparse, parse_qsl, urlencode

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "ComedyEventCrawler/1.2 (+BeautifulSoup only)"
}

# Optional browser fallback. Normal runs stay requests/BeautifulSoup only; use
# --headless when a site injects event cards/ticket widgets with JavaScript.
USE_HEADLESS = False
HEADLESS_TIMEOUT_MS = 8000
HEADLESS_WAIT_MS = 800
SKIDDLE_SHOW_MORE_CLICKS = 6
HEADLESS_GOTO_WAIT_UNTIL = "domcontentloaded"  # networkidle often never happens on Wix/Squarespace/tracking-heavy sites

EVENT_PATHS = [
    "/events",
    "/event",
    "/comedy-club",
    "/comedy-club/",
    "/whats-on",
    "/what-s-on",
    "/whatson",
    "/calendar",
    "/comedy",
    "/shows",
    "/shows/",
    "/gigs",
    "/live",
    "/tickets",
    "/listings",
    "/schedule",
    # v3: common listing slugs (only probed when site navigation finds nothing better)
    "/all-shows",
    "/upcoming-shows",
    "/upcoming-events",
    "/comedy-nights",
    "/open-mic",
    "/tour-dates",
    "/programme",
]

EVENT_PAGE_KEYWORDS = (
    "event",
    "events",
    "whats-on",
    "what-s-on",
    "whatson",
    "shows",
    "gigs",
    "live",
    "tickets",
    "listings",
    "schedule",
    "calendar",
    "upcoming",
    "all-shows",
    "open-mic",
    "tour",
    "programme",
)

MAX_EVENT_PAGES_PER_VENUE = 5
MAX_EVENTS_PER_VENUE = 200  # v3: safety cap only; the date window does the real limiting (--max-events-per-venue)
IFRAME_LINK_LIMIT = 3
TICKET_LINK_LIMIT = 12
SOUP_HTML_CACHE = {}
SAFE_GET_CACHE = {}
SKIDDLE_DETAIL_CACHE = {}
SKIP_SKIDDLE_SEARCH = False

# ---------------------------------------------------------------------------
# v3 configuration (CLI overrides in run())
# ---------------------------------------------------------------------------
DEFAULT_DAYS_AHEAD = 365       # Rolling event window: UK today through next 365 days.
UK_TIMEZONE = "Europe/London"
START_DATE = None                 # set by configure_date_window(): today's UK date
END_DATE = None                   # set by configure_date_window(): inclusive end date
HEADLESS_MAX_EXPANSIONS = 6       # load-more / next / next-month clicks per rendered page
HEADLESS_READY_TIMEOUT_MS = 6000  # max wait for event elements to appear after load
PER_DOMAIN_DELAY_SECONDS = 0.5    # polite gap between requests to the same host
RESPECT_ROBOTS_TXT = True         # robots.txt is honoured; there is deliberately no CLI switch to disable it
LONG_RUNNING_DAYS = 14            # date ranges longer than this are vouchers/residencies, not performances
DIAGNOSTICS = None                # VenueDiagnostics for the venue being scraped
CURRENT_VENUE = {}                # venue row being scraped (classification/location context)
REVIEW_ROWS = []                  # rows for the optional diagnostics "Review" sheet

COMEDY_KEYWORDS = [
    "comedy",
    "stand up",
    "stand-up",
    "standup",
    "open mic",
    "comedian",
    "improv",
    "laugh",
]


# v3 note: these words are no longer substring-matched against everything.
# classify_event() uses whole-word, context-aware evidence (title vs event
# description, comedy wording, venue context). "tribute" alone is no longer an
# exclusion, so comedian tribute acts are kept while music tributes are not.
NON_COMEDY_EXCLUDE_KEYWORDS = [
    # Music / tribute / theatre that often appears on generic What's On pages
    "jazz", "folk", "choir", "orchestra", "candlelight", "abba", "tribute",
    "live music", "dj ", "band", "musical", "the mikado", "opera", "ballet",
    "pantomime", "panto", "dance workshop", "lindy hop", "swing dance",

    # Community / class / advice listings that are not comedy events
    "craft", "craft sessions", "warm welcome", "community café", "community cafe",
    "housing advice", "advice drop in", "drop-in", "tai chi", "yoga", "pilates",
    "zumba", "residents", "community hall", "community centre", "community center",
    "electronauts", "workshop", "auditions",

    # Nightclub/music events that can leak from multi-purpose venues and ticket providers
    "club night", "afterparty", "after party", "alldayer", "all dayer",
    "dj set", "djs", "rave", "garage night", "soul night", "goth alldayer",
    "converge uk", "world goth", "subdub", "moveonup", "live dj",
    "karaoke", "world cup screening", "free world cup screening",
    "england games", "football screening", "watch party",
]

GENERIC_BAD_TITLES = {
    "what's on", "whats on", "what’s on", "shows", "events", "upcoming events",
    "events search and views navigation", "more info", "search all our shows",
    "load more", "buy tickets", "tickets", "our top picks",
}

COMEDY_TITLE_HINTS = [
    "comedy", "stand up", "stand-up", "standup", "comedian", "open mic",
    "improv", "sketch", "fringe", "laugh", "jokes", "funny",
]

# Protocol for trusted comedy/ticket-source websites.
# Add future trusted ticket/source domains here rather than hard-coding broad
# crawl types. These trusted domains/venues can list shows by act name without
# repeating the word "comedy" in every title.
TRUSTED_COMEDY_DOMAINS = [
    "creaturescomedy.com",
    "justthetonic.com",
    "thetopsecretcomedyclub.co.uk",
    "fatsoma.com/p/hifi-comedy-sessions",
    "hilaritybites.co.uk",
    "universe.com/users/hilarity-bites",
]

TRUSTED_COMEDY_VENUE_HINTS = [
    "creatures comedy",
    "creatures comedy club",
    "lions den",
    "lions den manchester",
    "just the tonic",
    "birmingham comedy club",
    "carlisle comedy club",
    "leamington spa comedy club",
    "leicester comedy club",
    "manchester comedy club",
    "melton mowbray comedy club",
    "morecambe comedy club",
    "nottingham comedy club",
    "reading comedy club",
    "hifi comedy club",
    "the hifi comedy club",
    "hilarity bites",
    "hilarity bites comedy club",
]

# Protected trusted venues are dedicated comedy venues where real dated listings
# should not be rejected simply because the individual title does not repeat the
# word "comedy". These rows still have to pass the basic junk/navigation checks
# and still need a title + date.
PROTECTED_TRUSTED_COMEDY_DOMAINS = [
    "creaturescomedy.com",
    "hilaritybites.co.uk",
    "universe.com/users/hilarity-bites",
]

PROTECTED_TRUSTED_COMEDY_VENUE_HINTS = [
    "creatures of the night comedy club",
    "creatures comedy",
    "creatures comedy club",
    "hilarity bites",
    "hilarity bites comedy club",
]

# Broadway Cinema is multi-purpose, so only trust it when the listing/source is
# explicitly in a Just The Tonic context.
JUST_THE_TONIC_CONTEXT_VENUES = [
    "broadway cinema",
    "broadway cinema nottingham",
    "broadway cinema, nottingham",
]

# Venues/domains that should be exposed to the site's Featured filter.
# The frontend already supports show.featured and type == "tour"; the scraper
# now marks only these preferred venues as featured instead of setting every
# show's type to "tour".
FEATURED_COMEDY_VENUE_HINTS = [
    "creatures comedy",
    "creatures comedy club",
    "top secret comedy club",
    "the top secret comedy club",
    "the glee club glasgow",
    "glee club glasgow",
    "the glee glasgow",
    "glee glasgow",
    "the pleasance edinburgh",
    "pleasance edinburgh",
    "pleasance courtyard",
]

FEATURED_COMEDY_DOMAIN_HINTS = [
    "creaturescomedy.com",
    "thetopsecretcomedyclub.co.uk",
    "glee.co.uk/glasgow",
    "pleasance.co.uk",
]

POSTER_COMEDY_CONTEXT_HINTS = [
    "poster comedy",
    "postercomedy.club",
    "postercomedyclub.com",
    "poster comedy club",
    "poster comedy london",
]

POSTER_STRICT_COMEDY_HINTS = [
    "comedy", "stand up", "stand-up", "standup", "comedian",
    "open mic", "laugh", "jokes", "funny", "free comedy",
]

TRUSTED_SOURCE_TYPES = {
    "skiddle",
    "fatsoma",
    "fixr",
    "tickettailor",
    "topsecret",
    "komedia",
    "justthetonic",
    "hilaritybites",
    # Generic ticket-provider scrapes are still filtered for comedy relevance;
    # they are trusted enough to score well but not enough to bypass relevance.
    "eventbrite",
    "wegottickets",
    "seetickets",
    "ticketmaster",
    "spektrix",
    "dice",
    "universe",
    "billetto",
    "designmynight",
    "atgtickets",
    "trafalgartickets",
    "ticketsource",
    "ticketprovider",
}

# Eventbrite is very broad. It lists music/classes/community events as well as comedy,
# so it should not pass just because the wider venue page mentions comedy.
CAUTIOUS_TICKET_SOURCE_TYPES = {"eventbrite"}
CAUTIOUS_TICKET_DOMAINS = ["eventbrite."]

TICKET_DOMAINS = [
    "skiddle.com",
    "fatsoma.com",
    "fixr.co",
    "tickettailor.com",
    "justthetonic.com",
    "eventbrite.",
    "wegottickets.com",
    "seetickets.com",
    "ticketmaster.",
    "spektrix.com",
    "dice.fm",
    "universe.com",
    "billetto.",
    "designmynight.com",
    "atgtickets.com",
    "trafalgartickets.com",
    "ticketsource.",
]

HILARITY_BITES_UNIVERSE_URLS = [
    "https://www.universe.com/users/hilarity-bites-FDYX42",
]

BLOCKED_DOMAINS = [
    "facebook.com",
    "m.facebook.com",
    "instagram.com",
    "linktr.ee",
    "lnk.bio",
]

OUTPUT_FIELDS = [
    "title",
    "date",
    "time",
    "price",
    "end_date",
    "venue",
    "city",
    "state",
    "description",
    "ticket_url",
    "image",
    "source",
    "source_type",
    "confidence",
]


def clean_text(text):
    if not text:
        return ""
    text = html.unescape(str(text))
    text = re.sub(r"\s+", " ", text)
    return text.strip()




CITY_TO_REGION = {
    "luton": "East of England",
    "ellon": "Scotland",
    "broadstairs": "South East",
    "birchington": "South East",
    "herne bay": "South East",
    "wimborne": "South West",
    "llangollen": "Wales",
    "healeys": "South West",
    "clydebank": "Scotland",
    "stowmarket": "East of England",
    "memorial": "South East",
    "london": "London",
    "kingston upon thames": "London",
    "wallington": "London",
    "belfast": "Northern Ireland",
    "ballymena": "Northern Ireland",
    "bangor": "Northern Ireland",
    "antrim": "Northern Ireland",
    "newry": "Northern Ireland",
    "craigavon": "Northern Ireland",
    "portrush": "Northern Ireland",
    "londonderry": "Northern Ireland",
    "omagh": "Northern Ireland",
    "armagh": "Northern Ireland",
    "limavady": "Northern Ireland",
    "newtownards": "Northern Ireland",
    "banbridge": "Northern Ireland",
    "downpatrick": "Northern Ireland",
    "ballymoney": "Northern Ireland",
    "coleraine": "Northern Ireland",
    "maghera": "Northern Ireland",
    "ballycastle": "Northern Ireland",
    "newtownabbey": "Northern Ireland",
    "strabane": "Northern Ireland",
    "enniskillen": "Northern Ireland",
    "cookstown": "Northern Ireland",
    "dungannon": "Northern Ireland",
    "lisburn": "Northern Ireland",
    "larne": "Northern Ireland",
    "holywood": "Northern Ireland",
    "thurso": "Scotland",
    "wick": "Scotland",
    "aberdeen": "Scotland",
    "inverness": "Scotland",
    "stornoway": "Scotland",
    "glasgow": "Scotland",
    "edinburgh": "Scotland",
    "greenock": "Scotland",
    "inverurie": "Scotland",
    "banchory": "Scotland",
    "peterhead": "Scotland",
    "port glasgow": "Scotland",
    "muir of ord": "Scotland",
    "nairn": "Scotland",
    "elgin": "Scotland",
    "buckie": "Scotland",
    "strathpeffer": "Scotland",
    "orkney": "Scotland",
    "stromness": "Scotland",
    "portree": "Scotland",
    "kirkwall": "Scotland",
    "langholm": "Scotland",
    "dumfries": "Scotland",
    "gourock": "Scotland",
    "dunoon": "Scotland",
    "largs": "Scotland",
    "west kilbride": "Scotland",
    "saltcoats": "Scotland",
    "helensburgh": "Scotland",
    "troon": "Scotland",
    "kilmarnock": "Scotland",
    "prestwick": "Scotland",
    "ayr": "Scotland",
    "lockerbie": "Scotland",
    "castle douglas": "Scotland",
    "stranraer": "Scotland",
    "cumnock": "Scotland",
    "maybole": "Scotland",
    "falkirk": "Scotland",
    "stirling": "Scotland",
    "oban": "Scotland",
    "aviemore": "Scotland",
    "galashiels": "Scotland",
    "biggar": "Scotland",
    "livingston": "Scotland",
    "fort william": "Scotland",
    "hawick": "Scotland",
    "carluke": "Scotland",
    "newport": "Wales",
    "wrexham": "Wales",
    "denbigh": "Wales",
    "llandrindod wells": "Wales",
    "rhyl": "Wales",
    "deeside": "Wales",
    "mold": "Wales",
    "abergele": "Wales",
    "colwyn bay": "Wales",
    "holywell": "Wales",
    "ruthin": "Wales",
    "caernarfon": "Wales",
    "builth wells": "Wales",
    "llanidloes": "Wales",
    "machynlleth": "Wales",
    "newtown": "Wales",
    "abergavenny": "Wales",
    "pontypool": "Wales",
    "cwmbran": "Wales",
    "monmouth": "Wales",
    "crickhowell": "Wales",
    "abertillery": "Wales",
    "chepstow": "Wales",
    "milford haven": "Wales",
    "narberth": "Wales",
    "cardigan": "Wales",
    "swansea": "Wales",
    "newcastle": "North East",
    "newcastle upon tyne": "North East",
    "gateshead": "North East",
    "sunderland": "North East",
    "middlesbrough": "North East",
    "morpeth": "North East",
    "blyth": "North East",
    "alnwick": "North East",
    "south shields": "North East",
    "blackpool": "North West",
    "manchester": "North West",
    "chester": "North West",
    "carlisle": "North West",
    "northwich": "North West",
    "ellesmere port": "North West",
    "ulverston": "North West",
    "liverpool": "North West",
    "lytham saint annes": "North West",
    "barrow-in-furness": "North West",
    "poulton-le-fylde": "North West",
    "neston": "North West",
    "sandbach": "North West",
    "frodsham": "North West",
    "nantwich": "North West",
    "thornton-cleveleys": "North West",
    "lancashire": "North West",
    "fleetwood": "North West",
    "southport": "North West",
    "lancaster": "North West",
    "stockport": "North West",
    "dukinfield": "North West",
    "macclesfield": "North West",
    "crewe": "North West",
    "winsford": "North West",
    "middlewich": "North West",
    "morecambe": "North West",
    "millom": "North West",
    "wigton": "North West",
    "congleton": "North West",
    "leeds": "Yorkshire",
    "scarborough": "Yorkshire",
    "whitby": "Yorkshire",
    "sheffield": "Yorkshire",
    "york": "Yorkshire",
    "hull": "Yorkshire",
    "ripon": "Yorkshire",
    "birmingham": "West Midlands",
    "stoke-on-trent": "West Midlands",
    "shrewsbury": "West Midlands",
    "stafford": "West Midlands",
    "telford": "West Midlands",
    "wolverhampton": "West Midlands",
    "worcester": "West Midlands",
    "hereford": "West Midlands",
    "stratford-upon-avon": "West Midlands",
    "oswestry": "West Midlands",
    "market drayton": "West Midlands",
    "ludlow": "West Midlands",
    "stourport-on-severn": "West Midlands",
    "brierley hill": "West Midlands",
    "kidderminster": "West Midlands",
    "evesham": "West Midlands",
    "bromyard": "West Midlands",
    "much wenlock": "West Midlands",
    "bridgnorth": "West Midlands",
    "worcestershire": "West Midlands",
    "bewdley": "West Midlands",
    "dudley": "West Midlands",
    "malvern": "West Midlands",
    "warwick": "West Midlands",
    "leamington spa": "West Midlands",
    "lichfield": "West Midlands",
    "stone": "West Midlands",
    "staffordshire": "West Midlands",
    "newcastle-under-lyme": "West Midlands",
    "alcester": "West Midlands",
    "stourbridge": "West Midlands",
    "pant": "West Midlands",
    "ross-on-wye": "West Midlands",
    "nottingham": "East Midlands",
    "derby": "East Midlands",
    "chesterfield": "East Midlands",
    "leicester": "East Midlands",
    "melton mowbray": "East Midlands",
    "ashby-de-la-zouch": "East Midlands",
    "grantham": "East Midlands",
    "skegness": "East Midlands",
    "lincoln": "East Midlands",
    "coalville": "East Midlands",
    "stamford": "East Midlands",
    "spalding": "East Midlands",
    "boston": "East Midlands",
    "southwell": "East Midlands",
    "belper": "East Midlands",
    "stapleford": "East Midlands",
    "norwich": "East of England",
    "bury saint edmunds": "East of England",
    "cambridge": "East of England",
    "great yarmouth": "East of England",
    "newmarket": "East of England",
    "ely": "East of England",
    "thetford": "East of England",
    "southwold": "East of England",
    "lowestoft": "East of England",
    "diss": "East of England",
    "beccles": "East of England",
    "ipswich": "East of England",
    "dereham": "East of England",
    "rayleigh": "East of England",
    "king's lynn": "East of England",
    "saxmundham": "East of England",
    "attleborough": "East of England",
    "swaffham": "East of England",
    "woolpit": "East of England",
    "aldeburgh": "East of England",
    "southampton": "South East",
    "portsmouth": "South East",
    "southsea": "South East",
    "chichester": "South East",
    "folkestone": "South East",
    "bognor regis": "South East",
    "canterbury": "South East",
    "margate": "South East",
    "ramsgate": "South East",
    "dover": "South East",
    "fareham": "South East",
    "gosport": "South East",
    "petersfield": "South East",
    "newbury": "South East",
    "winchester": "South East",
    "eastleigh": "South East",
    "deal": "South East",
    "sandwich": "South East",
    "whitstable": "South East",
    "hythe": "South East",
    "hayling island": "South East",
    "arundel": "South East",
    "alresford": "South East",
    "ventnor": "South East",
    "ryde": "South East",
    "haslemere": "South East",
    "waterlooville": "South East",
    "horndean": "South East",
    "liss": "South East",
    "midhurst": "South East",
    "petworth": "South East",
    "fordingbridge": "South East",
    "shanklin": "South East",
    "lymington": "South East",
    "romsey": "South East",
    "sandown": "South East",
    "new milton": "South East",
    "bordon": "South East",
    "hampshire": "South East",
    "havant": "South East",
    "alton": "South East",
    "oxford": "South East",
    "banbury": "South East",
    "witney": "South East",
    "chipping norton": "South East",
    "hungerford": "South East",
    "wantage": "South East",
    "abingdon": "South East",
    "faringdon": "South East",
    "andover": "South East",
    "bristol": "South West",
    "plymouth": "South West",
    "bournemouth": "South West",
    "cheltenham": "South West",
    "bath": "South West",
    "torquay": "South West",
    "newquay": "South West",
    "truro": "South West",
    "falmouth": "South West",
    "saint austell": "South West",
    "penzance": "South West",
    "weston-super-mare": "South West",
    "frome": "South West",
    "swindon": "South West",
    "exeter": "South West",
    "redruth": "South West",
    "poole": "South West",
    "ferndown": "South West",
    "ringwood": "South West",
    "salisbury": "South West",
    "holsworthy": "South West",
    "helston": "South West",
    "tavistock": "South West",
    "penryn": "South West",
    "fowey": "South West",
    "bodmin": "South West",
    "launceston": "South West",
    "ivybridge": "South West",
    "kingsbridge": "South West",
    "saltash": "South West",
    "lifto": "South West",
    "torpoint": "South West",
    "calstock": "South West",
    "salcombe": "South West",
    "bridgwater": "South West",
    "burnham-on-sea": "South West",
    "wells": "South West",
    "clevedon": "South West",
    "cheddar": "South West",
    "warminster": "South West",
    "melksham": "South West",
    "corsham": "South West",
    "glastonbury": "South West",
    "chippenham": "South West",
    "wedmore": "South West",
    "dursley": "South West",
    "stonehouse": "South West",
    "moreton-in-marsh": "South West",
    "brixham": "South West",
    "dartmouth": "South West",
    "budleigh salterton": "South West",
    "stroud": "South West",
    "ilfracombe": "South West",
    "weymouth": "South West",
    "newton abbot": "South West",
    "teignmouth": "South West",
    "paignton": "South West",
    "gloucester": "South West",
    "cirencester": "South West",
    "tewkesbury": "South West",
    "devizes": "South West",
    "street": "South West",
    "blandford forum": "South West",
    "gillingham": "South West",
    "wareham": "South West"
}
REGION_SLUGS = {
    "London": "london",
    "Manchester": "manchester",
    "Birmingham": "birmingham",
    "Bristol": "bristol",
    "Leeds": "leeds",
    "North West": "north-west",
    "Yorkshire": "yorkshire",
    "West Midlands": "west-midlands",
    "South West": "south-west",
    "South East": "south-east",
    "East Midlands": "east-midlands",
    "East of England": "east-of-england",
    "North East": "north-east",
    "Scotland": "scotland",
    "Wales": "wales",
    "Northern Ireland": "northern-ireland"
}


def normalise_region_name(value):
    value = clean_text(value)
    if value.lower() in ('england', 'gb', 'uk', 'united kingdom'):
        return ""
    if not value:
        return ""
    compact = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    for label, slug in REGION_SLUGS.items():
        if compact == slug or value.lower() == label.lower():
            return label
    return value


def infer_region_from_city(city):
    key = clean_text(city).lower()
    key = re.sub(r"\s*\(.*?\)\s*", " ", key).strip()
    return CITY_TO_REGION.get(key, "") or EXTRA_CITY_TO_REGION.get(key, "")


def slugify_text(text):
    text = clean_text(text).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def looks_like_junk_url_value(value):
    value = clean_text(value).lower()
    if not value:
        return True
    if re.fullmatch(r"[0-9.+\- ()]+", value):
        return True
    if value in {
        "bar",
        "comedy club",
        "theater production",
        "theatre production",
        "performing arts theater",
        "performing arts theatre",
        "live music venue",
        "event venue",
        "restaurant",
        "pub",
        "community center",
        "community centre",
    }:
        return True
    if ";" in value:
        return True
    return False


def is_valid_source_url(url):
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        if not parsed.netloc:
            return False
        if "." not in parsed.netloc:
            return False
        return True
    except Exception:
        return False


def is_comedy(text):
    text = clean_text(text).lower()
    return any(k in text for k in COMEDY_KEYWORDS)


def looks_unrelated_non_comedy(title, description=""):
    """Context-aware non-comedy check (v3).

    Keywords are matched as whole words, 'tribute' is no longer an automatic
    exclusion (comedian tributes are comedy), and description words only count
    when nothing in the title/description says comedy.
    """
    cls = classify_event({"title": title, "description": description})
    return cls["category"] == CAT_NON_COMEDY and cls["reason"] != "no comedy evidence"



def has_comedy_title_hint(title):
    title = clean_text(title).lower()
    return any(k in title for k in COMEDY_TITLE_HINTS)


def is_generic_bad_title(title):
    title_clean = clean_text(title).lower().strip(" :-–—|")
    if not title_clean:
        return True
    if title_clean in GENERIC_BAD_TITLES:
        return True
    if len(title_clean) <= 3:
        return True
    if title_clean.startswith("apologies! we're currently"):
        return True
    return False



BAD_EVENT_TITLE_SUBSTRINGS = [
    "join the mailing list", "gift vouchers", "corporate enquiries", "group bookings",
    "contact -", "contact", "menu -", " - menu", "tickets on sale now",
    "christmas shows", "comedians -", "edinburgh fringe festival - menu",
    "our top picks", "reviews", "privacy policy", "terms", "accessibility",
]

MONTH_ONLY_TITLE_RE = re.compile(
    r"^(january|february|march|april|may|june|july|august|september|october|november|december)\b\s*[-–—:]",
    re.I,
)

DATE_ONLY_TITLE_RE = re.compile(
    r"^(?:mon|monday|tue|tuesday|wed|wednesday|thu|thursday|fri|friday|sat|saturday|sun|sunday),?\s+\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)"
    r"(?:\s+\d{4})?$",
    re.I,
)


def remove_emoji_and_symbols(text):
    """Remove display emoji while keeping normal punctuation, apostrophes and ampersands."""
    out = []
    for ch in str(text or ""):
        cat = unicodedata.category(ch)
        if cat in {"So", "Sk"}:
            continue
        out.append(ch)
    return "".join(out)


def looks_like_date_only_title(title):
    t = clean_text(title).strip(" -–—|:")
    if not t:
        return True
    if DATE_ONLY_TITLE_RE.match(t):
        return True
    if normalise_date(t) and len(t) <= 32 and not re.search(r"[A-Za-z]{2,}.*[A-Za-z]{2,}", re.sub(r"\b(mon|tue|wed|thu|fri|sat|sun|day|date)\b", "", t, flags=re.I)):
        return True
    return False


def is_skiddle_landing_or_brand_url(url):
    """True when a Skiddle URL is a venue/brand/listing page, not an event detail page."""
    try:
        parsed = urlparse(clean_text(url))
        host = parsed.netloc.lower()
        path = parsed.path.lower().strip("/")
        if "skiddle.com" not in host:
            return False
        if not path:
            return True
        parts = [p for p in path.split("/") if p]
        if parts and parts[0] in {"b", "search", "events", "clubs", "gigs"}:
            # /b/... brand pages and broad search/index pages are not event detail links.
            return True
        if parts and parts[0] == "whats-on" and len(parts) <= 3:
            # /whats-on/City/Venue/ is a venue listing. Event pages have an extra slug after that.
            return True
        return False
    except Exception:
        return False


def is_skiddle_event_url(url):
    """True for likely Skiddle event detail URLs, not venue listings or brand pages."""
    try:
        parsed = urlparse(clean_text(url))
        host = parsed.netloc.lower()
        path = parsed.path.lower().strip("/")
        if "skiddle.com" not in host:
            return False
        parts = [p for p in path.split("/") if p]
        if not parts:
            return False
        if parts[0] == "whats-on" and len(parts) >= 4:
            return True
        if parts[0] in {"e", "events"} and len(parts) >= 2:
            return True
        return False
    except Exception:
        return False


def looks_like_navigation_or_non_event_title(title, ticket_url=""):
    """Reject nav/menu/date/review links that can be pulled from whole-page JSON or headers."""
    t = clean_text(remove_emoji_and_symbols(title)).lower().strip(" -–—|:")
    url = clean_text(ticket_url).lower()
    if not t:
        return True
    if t in GENERIC_BAD_TITLES:
        return True
    if looks_like_date_only_title(t):
        return True
    if MONTH_ONLY_TITLE_RE.match(t):
        return True

    # Hard reject obvious site navigation / admin / index labels. These were the
    # source of bad Just The Tonic rows such as "Contact - Menu..." and
    # "Comedians - Menu..." getting into shows.json.
    nav_phrases = [
        "join the mailing list", "mailing list", "gift vouchers", "gift voucher", "gift of laughter",
        "corporate enquiries", "corporate comedy", "group bookings", "birthdays",
        "contact", "contact us", "privacy", "terms", "accessibility", "login",
        "promoter", "newsletter", "menu", "load more",
        "tickets on sale now", "book now", "our top picks", "reviews",
        "christmas shows", "apply to perform", "become a sponsor", "shopping cart",
    ]
    if any(phrase in t for phrase in nav_phrases):
        return True
    # v3: "comedians" and "sign up" used to be substring matches, which rejected
    # real titles such as "Open Mic for New Comedians" or "Open Mic - sign up 7pm".
    if re.match(r"^(?:comedians\s*(?:[-–—|:].*)?|sign\s*up\b.*|signup\b.*)$", t):
        return True
    # v3.1: page labels such as "What's On: Comedy Night Schedule"
    if re.match(r"^what[’']?s\s*on\b", t) or re.search(r"\b(?:schedule|listings|calendar)\s*$", t):
        return True

    # Keep real Edinburgh/Festival show detail pages, but reject the top-level
    # festival/navigation page as an event.
    if "edinburgh fringe festival" in t and "/shows/" not in url:
        return True

    # Just The Tonic events should be individual show detail URLs. The city,
    # comedians, contact, festival landing and this-month/next-month pages are
    # navigation/index pages, not event rows.
    if "justthetonic.com" in url or "justthetonic" in url:
        allowed_detail = "/shows/" in url or "edinburgh.justthetonic.com/event/" in url
        if not allowed_detail:
            return True

    if "skiddle.com" in url and is_skiddle_landing_or_brand_url(url):
        return True

    if "facebook.com/sharer" in url or "twitter.com/share" in url or "share?" in url:
        return True
    return False


def extract_names_from_comedy_club_title(title):
    """Turn 'Comedy Club with A, B & C (1st act...)' into 'A, B & C'."""
    t = clean_text(title)
    m = re.search(r"\bcomedy club\s+with\s+(.+)$", t, flags=re.I)
    if not m:
        return ""
    names = m.group(1)
    names = re.sub(r"\([^)]*\)", "", names)
    names = re.sub(r"\b(?:one|two|three|four)\s+more\s+guests?\s+TBC\b", "Guest TBC", names, flags=re.I)
    names = re.sub(r"\band\s+one\s+more\s+guest\s+TBC\b", "& Guest TBC", names, flags=re.I)
    names = re.sub(r"\s+", " ", names).strip(" ,-&")
    return names


def clean_display_title(raw_title, event=None):
    """Clean the title used in shows.json's legacy 'comedian' field.

    The frontend currently reads show.comedian, so the key stays the same, but
    the value is cleaned to be a short event/line-up label rather than menu/date
    text from the scraped page.
    """
    title = clean_text(remove_emoji_and_symbols(raw_title))
    title = title.replace("||", " | ")
    title = re.sub(r"\s+", " ", title).strip()

    # Best case: Fatsoma/HIFI style titles already contain a clean line-up after 'Comedy Club with'.
    lineup = extract_names_from_comedy_club_title(title)
    if lineup:
        return clean_text(lineup)

    # Remove menu/navigation text that sometimes gets attached to real JTT/event anchors.
    title = re.sub(r"\s+[-–—]\s+Menu\b.*$", "", title, flags=re.I)

    # Remove dates/times and operational text from titles.
    title = re.sub(r"\([^)]*(?:act|onstage|door|doors|entry|starts?|show start|pm|am)[^)]*\)", "", title, flags=re.I)
    title = re.sub(r"\b(?:door|doors|last entry|starts?)\s*[:]?\s*\d{1,2}[:.]\d{2}\b.*$", "", title, flags=re.I)
    title = re.sub(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:day)?[,]?\s+\d{1,2}(?:st|nd|rd|th)?\s+"
                   r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*(?:\s+\d{4})?\b", "", title, flags=re.I)
    title = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "", title)
    title = re.sub(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", "", title)
    title = re.sub(r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\b", "", title, flags=re.I)
    title = re.sub(r"\bReviews\b", "", title, flags=re.I)

    # JTT and similar detail titles: remove generic venue prefix but keep the act/show name.
    title = re.sub(r"^Just\s+the\s+Tonic\s+Comedy(?:\s+Club)?\s*[-–—]\s*[^-–—|]+\s*[-–—]\s*", "", title, flags=re.I)
    title = re.sub(r"\b(?:Tour Show|Comedy Club)\b\s*$", "", title, flags=re.I)
    title = re.sub(r"\s*[-–—|]\s*(?:Creatures|Just the Tonic)\s*(?:Comedy Club|Tour Show)?\s*$", "", title, flags=re.I)

    # Convert simple line-up separators to a cleaner label.
    # v3.1: "Ed Byrne - Tragedy Plus Time" keeps comedian + show ("Ed Byrne: Tragedy Plus Time")
    # instead of becoming a fake line-up "Ed Byrne, Tragedy Plus Time".
    if " - " in title and not re.search(r"\b(?:special|show|club|night|cabaret|festival)\b", title, re.I):
        dash_parts = [p.strip() for p in title.split(" - ") if p.strip()]
        act_first = looks_like_person_name(dash_parts[0]) or looks_like_double_act(dash_parts[0])
        name_list = len(dash_parts) >= 3 and all(looks_like_person_name(p) for p in dash_parts)
        if len(dash_parts) >= 2 and "," not in dash_parts[0] and act_first and not name_list:
            title = f"{dash_parts[0]}: {' - '.join(dash_parts[1:])}"
        else:
            title = title.replace(" - ", ", ")

    # Tidy known all-caps/Wix labels.
    if title.upper() == title and len(title) > 6:
        title = title.title()
    title = re.sub(r"\s*[:|,;-]+\s*$", "", title)
    title = re.sub(r"\s+", " ", title).strip(" -–—|,:;")
    # Avoid displaying "Comedy Club" in the legacy `comedian` field. If this
    # turns a venue/category label into a bad title, events_to_site_shows will
    # reject it below.
    if "comedy club" in title.lower():
        title = strip_comedy_club_from_display_label(title)
    return clean_text(title)



def looks_like_bad_site_show_label(label, tickets=""):
    """Final guard for the legacy shows.json `comedian` value.

    It should be a short show/line-up label, not a nav item, date, venue/category
    page, or generic "Comedy Club" page label.
    """
    label_clean = clean_text(remove_emoji_and_symbols(label)).strip()
    low = label_clean.lower().strip(" -–—|:")
    url = clean_text(tickets).lower()

    if looks_like_navigation_or_non_event_title(label_clean, tickets):
        return True
    if not low or len(low) < 4:
        return True

    # Do not let venue/category labels sit in the field that the site displays
    # as the show/comedian heading.
    venueish_patterns = [
        r"^[a-z .,'&-]+ comedy club$",
        r"^[a-z .,'&-]+ comedy club \d{1,2}/\d{1,2}/\d{2,4}$",
        r"^just the tonic(?: comedy club)?(?: - [a-z .,'&-]+)?$",
        r"^[a-z .,'&-]+ - menu\b",
    ]
    if any(re.match(p, low, flags=re.I) for p in venueish_patterns):
        return True

    # If the label still contains "Comedy Club", only allow it when it also has
    # a proper act/show signal. HIFI/Fatsoma lineups are already transformed to
    # just names before this point.
    if "comedy club" in low:
        allowed = any(k in low for k in ["special", "show", "night", "presents", "with ", ",", "&"])
        if not allowed:
            return True
        # Even when allowed, don't keep a city/category page label.
        if any(x in low for x in ["birmingham comedy club", "manchester comedy club", "reading comedy club", "leicester comedy club"]):
            if "/shows/" not in url:
                return True

    return False


def strip_comedy_club_from_display_label(label):
    """Remove leftover venue/category wording from labels displayed as `comedian`."""
    value = clean_text(label)
    # If a real line-up was extracted, this won't match; it mainly catches labels
    # like "Stoke Regent Theatre Comedy Club 13/06/26".
    value = re.sub(r"\bComedy Club\b", "", value, flags=re.I)
    value = re.sub(r"\s{2,}", " ", value).strip(" -–—|,:;")
    return clean_text(value)


def bad_event_image_url(image):
    lower = clean_text(image).lower()
    if not lower:
        return True
    bad_bits = [
        "/site/img/logo", "logo.png", "logo.svg", "favicon", "facebook", "sharer",
        "w_27", "h_27", "w_28", "h_28", "w_49", "h_48", "blur_2",
        "eventbrite.co.uk/e/_next/image", "/_next/static/media/map", "map.84ed7a7f",
        "organizer-card", "maps.gstatic", "googleapis.com/maps", "sprite", "icon",
        "skiddlebrands.imgix.net/brands", "/brands/", "brand-logo",
    ]
    return any(bit in lower for bit in bad_bits)


def image_from_srcset(srcset):
    if not srcset:
        return ""
    # Prefer the last candidate because it is usually the largest image.
    parts = [p.strip().split(" ")[0] for p in str(srcset).split(",") if p.strip()]
    return parts[-1] if parts else ""


def image_from_node(node, base_url):
    if not node:
        return ""
    for attr in ("src", "data-src", "data-original", "data-lazy-src", "data-image", "data-image-url", "content"):
        value = node.get(attr)
        if value:
            img = absolute_url(base_url, value)
            if img and not bad_event_image_url(img):
                return img
    for attr in ("srcset", "data-srcset"):
        value = image_from_srcset(node.get(attr))
        if value:
            img = absolute_url(base_url, value)
            if img and not bad_event_image_url(img):
                return img
    return ""


def extract_meta_image(soup, source_url):
    if not soup:
        return ""
    selectors = [
        'meta[property="og:image"]',
        'meta[name="og:image"]',
        'meta[property="twitter:image"]',
        'meta[name="twitter:image"]',
        'meta[itemprop="image"]',
        'link[rel="image_src"]',
    ]
    for sel in selectors:
        node = soup.select_one(sel)
        img = image_from_node(node, source_url)
        if img:
            return img
    return ""


def find_best_image_in_block(block, source_url, fallback_soup=None):
    if block:
        for img_node in block.select("img, source"):
            img = image_from_node(img_node, source_url)
            if img:
                return img
    return extract_meta_image(fallback_soup, source_url) if fallback_soup else ""


def is_cautious_ticket_provider_event(event):
    source_type = clean_text(event.get("source_type", "")).lower()
    url_text = f"{event.get('ticket_url','')} {event.get('source','')}".lower()
    return source_type in CAUTIOUS_TICKET_SOURCE_TYPES or any(domain in url_text for domain in CAUTIOUS_TICKET_DOMAINS)


def has_strong_comedy_signal_for_cautious_provider(event):
    """For broad providers like Eventbrite, trust only the event title, venue or URL.

    Description/page text can be polluted by a generic venue's wider listings, so
    it should not be enough to pass a non-comedy Eventbrite event.
    """
    title = clean_text(event.get("title", ""))
    venue = clean_text(event.get("venue", ""))
    url_text = f"{event.get('ticket_url','')} {event.get('source','')}"
    strong_text = f"{title} {venue} {url_text}"
    return (
        has_comedy_title_hint(title)
        or bool(OPEN_MIC_STRONG_RE.search(title))
        or is_trusted_comedy_context(event)
        or is_comedy(strong_text)
    )



def is_trusted_comedy_context(event):
    """Return True for specific trusted comedy domains/venues.

    This deliberately does not trust broad crawl/source types such as wix,
    embed, or creatures. It only trusts named domains and venue hints.
    """
    title = clean_text(event.get("title", "")).lower()
    description = clean_text(event.get("description", "")).lower()
    venue = clean_text(event.get("venue", "")).lower()
    ticket_url = clean_text(event.get("ticket_url", "")).lower()
    source = clean_text(event.get("source", "")).lower()
    url_text = f"{ticket_url} {source}"
    context_text = f"{title} {description} {venue} {url_text}"

    if any(domain in url_text for domain in TRUSTED_COMEDY_DOMAINS):
        return True

    if any(hint in venue for hint in TRUSTED_COMEDY_VENUE_HINTS):
        return True

    if any(hint in venue for hint in JUST_THE_TONIC_CONTEXT_VENUES):
        return "justthetonic" in url_text or "just the tonic" in context_text

    return False




def is_protected_trusted_comedy_event(event):
    """Allow real dated rows from protected trusted comedy venues.

    This is intentionally narrower than is_trusted_comedy_context(). It is for
    venues such as Creatures where the source/venue is comedy-only, but event
    titles may be act names, themed titles, or Skiddle labels without the word
    "comedy". The generic bad-title and navigation checks still run before this
    function is used.
    """
    title = clean_text(event.get("title", ""))
    date = clean_text(event.get("date", ""))
    if not title or not date:
        return False

    context = " ".join([
        title,
        clean_text(event.get("venue", "")),
        clean_text(event.get("city", "")),
        clean_text(event.get("source", "")),
        clean_text(event.get("source_type", "")),
        clean_text(event.get("ticket_url", "")),
    ]).lower()

    if any(domain in context for domain in PROTECTED_TRUSTED_COMEDY_DOMAINS):
        return True
    if any(hint in context for hint in PROTECTED_TRUSTED_COMEDY_VENUE_HINTS):
        return True
    return False


def is_featured_event(event):
    """Mark selected venue/source rows for the website Featured filter."""
    title = clean_text(event.get("title", "")).lower()
    venue = clean_text(event.get("venue", "")).lower()
    city = clean_text(event.get("city", "")).lower()
    source = clean_text(event.get("source", "")).lower()
    ticket_url = clean_text(event.get("ticket_url", "")).lower()
    context = f"{title} {venue} {city} {source} {ticket_url}"

    if any(domain in context for domain in FEATURED_COMEDY_DOMAIN_HINTS):
        # Avoid promoting generic Pleasance/Glee non-comedy rows just because the
        # parent site is featured. They still need a comedy signal unless they
        # are a dedicated comedy-club domain like Creatures/Top Secret.
        if "pleasance.co.uk" in context or "glee.co.uk" in context:
            return is_comedy(f"{title} {event.get('description','')} {ticket_url} {venue}")
        return True

    if "creatures comedy" in venue and city == "manchester":
        return True
    if "top secret" in venue and city == "london":
        return True
    if "glee" in venue and city == "glasgow":
        return is_comedy(f"{title} {event.get('description','')} {ticket_url} {venue}")
    if "pleasance" in venue and city == "edinburgh":
        return is_comedy(f"{title} {event.get('description','')} {ticket_url} {venue}")

    return any(hint in context for hint in FEATURED_COMEDY_VENUE_HINTS)


def is_poster_comedy_context(event):
    context = " ".join([
        clean_text(event.get("title", "")),
        clean_text(event.get("venue", "")),
        clean_text(event.get("description", "")),
        clean_text(event.get("source", "")),
        clean_text(event.get("ticket_url", "")),
    ]).lower()
    return any(hint in context for hint in POSTER_COMEDY_CONTEXT_HINTS)


def is_valid_poster_comedy_event(event):
    """Poster Comedy Club can appear via broad providers; require each row itself
    to be clearly comedy rather than trusting the organiser/venue name alone."""
    if not is_poster_comedy_context(event):
        return True

    title = clean_text(event.get("title", "")).lower()
    description = clean_text(event.get("description", "")).lower()
    source = clean_text(event.get("source", "")).lower()
    ticket_url = clean_text(event.get("ticket_url", "")).lower()
    text = f"{title} {description} {source} {ticket_url}"

    if looks_unrelated_non_comedy(title, description):
        return False

    # Reject operational/status rows and broad provider noise.
    if any(bad in text for bad in ["hiatus", "cancelled", "postponed", "loading", "all events", "view events", "view posts"]):
        return False

    return any(hint in text for hint in POSTER_STRICT_COMEDY_HINTS)

def is_relevant_comedy_event(event):
    """Final quality gate to stop generic venue pages importing non-comedy listings.

    v3: delegates to relevance_decision() and records rejections for the
    optional diagnostics report. Signature and return type are unchanged.
    """
    keep, reason = relevance_decision(event)
    if not keep:
        diag_event("rejected", detail=reason, event=event)
    return keep




# ===========================================================================
# UKCM v3 ENHANCEMENTS
# ---------------------------------------------------------------------------
# Everything below is additive. Existing function names, CLI arguments and the
# events.csv / shows.json schemas are unchanged. Helpers here are used by the
# existing functions further down (discovery, extraction, relevance, dedupe).
# ===========================================================================

# ---------------------------------------------------------------------------
# Date window (Task 4)
# ---------------------------------------------------------------------------
def uk_today():
    """Today's date in the UK (Europe/London), falling back to local time."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(UK_TIMEZONE)).date()
    except Exception:
        return datetime.now().date()


def configure_date_window(end_date_text=None, today=None):
    """Set the inclusive window [today (UK), end date]. Raises ValueError on bad input."""
    global START_DATE, END_DATE
    START_DATE = today or uk_today()
    end_value = clean_text(end_date_text) if end_date_text else (START_DATE + timedelta(days=DEFAULT_DAYS_AHEAD)).isoformat()
    try:
        END_DATE = datetime.strptime(end_value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"--end-date must be a real date in YYYY-MM-DD format, got {end_value!r}")
    if END_DATE < START_DATE:
        raise ValueError(f"--end-date {END_DATE} is before today's UK date {START_DATE}")
    return START_DATE, END_DATE


def window_start():
    return START_DATE or uk_today()


def window_end():
    if END_DATE:
        return END_DATE
    return window_start() + timedelta(days=DEFAULT_DAYS_AHEAD)


def parse_iso_date(value):
    """Return a datetime.date for a real YYYY-MM-DD value, else None."""
    value = clean_text(value)[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def date_window_status(date_str):
    """'ok', 'past', 'after_end' or 'invalid' for an event date string."""
    d = parse_iso_date(date_str)
    if not d:
        return "invalid"
    if d < window_start():
        return "past"
    if d > window_end():
        return "after_end"
    return "ok"


def date_in_window(date_str):
    return date_window_status(date_str) == "ok"


_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_MONTH_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_WEEKDAY_RE = r"(mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)"

# Ordered patterns: each returns (day, month, year_or_None, weekday_or_None)
_DATE_PATTERNS = [
    # Fri 16 Oct 2026 / 16 October 2026 / 16th Oct, 2026
    ("dmy_text", re.compile(r"(?:\b" + _WEEKDAY_RE + r"\b[,.]?\s+)?\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTH_RE + r"\b[,.]?\s+(\d{4})\b", re.I)),
    # December 16, 2026 / Fri, Dec 16 2026
    ("mdy_text", re.compile(r"(?:\b" + _WEEKDAY_RE + r"\b[,.]?\s+)?\b" + _MONTH_RE + r"\b\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I)),
    # 16/10/2026, 16.10.26, 16-10-2026 (UK day-first)
    ("dmy_num", re.compile(r"(?<![\d/.:-])(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?![\d/.:-])")),
    # Fri 16 Oct (no year)
    ("dm_text", re.compile(r"(?:\b" + _WEEKDAY_RE + r"\b[,.]?\s+)?\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTH_RE + r"\b(?![,.]?\s+\d{4})(?!\s*\d)", re.I)),
    # Fri, Oct 16 (no year)
    ("md_text", re.compile(r"(?:\b" + _WEEKDAY_RE + r"\b[,.]?\s+)?\b" + _MONTH_RE + r"\b\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?![,.]?\s+\d{4})(?!\s*[:.]\d)(?!\d)", re.I)),
]


def _safe_date(year, month, day):
    try:
        from datetime import date as _date
        return _date(int(year), int(month), int(day))
    except (ValueError, TypeError):
        return None


def _resolve_yearless(day, month, weekday, reference):
    """Pick the year for a yearless date, handling December/January rollovers.

    With a weekday we choose the nearby year whose calendar matches. Without a
    weekday, a date up to 90 days in the past is treated as already past (so a
    stale listing is filtered rather than silently pushed into next year).
    """
    candidates = []
    for year in (reference.year, reference.year + 1, reference.year - 1):
        d = _safe_date(year, month, day)
        if d:
            candidates.append(d)
    if not candidates:
        return None
    if weekday is not None:
        matching = [d for d in candidates if d.weekday() == weekday]
        if matching:
            # prefer the occurrence closest to the reference date
            return min(matching, key=lambda d: abs((d - reference).days))
    this_year = _safe_date(reference.year, month, day)
    if this_year is None:
        return _safe_date(reference.year + 1, month, day)
    if (reference - this_year).days > 90:
        return _safe_date(reference.year + 1, month, day) or this_year
    return this_year


def _match_to_date(kind, m, reference):
    groups = m.groups()
    if kind == "dmy_text":
        wd, day, mon, year = groups
        return _safe_date(year, _MONTHS[mon[:3].lower()], day)
    if kind == "mdy_text":
        wd, mon, day, year = groups
        return _safe_date(year, _MONTHS[mon[:3].lower()], day)
    if kind == "dmy_num":
        day, month, year = groups
        year = int(year)
        if year < 100:
            year += 2000
        return _safe_date(year, month, day)
    if kind == "dm_text":
        wd, day, mon = groups
        weekday = _WEEKDAYS.get(wd[:3].lower()) if wd else None
        return _resolve_yearless(int(day), _MONTHS[mon[:3].lower()], weekday, reference)
    if kind == "md_text":
        wd, mon, day = groups
        weekday = _WEEKDAYS.get(wd[:3].lower()) if wd else None
        return _resolve_yearless(int(day), _MONTHS[mon[:3].lower()], weekday, reference)
    return None


def find_dates_in_text(text, reference=None, limit=60):
    """Return [(position, date, explicit_year_bool)] for every real date in text."""
    text = clean_text(text)
    if not text:
        return []
    reference = reference or window_start()
    found = []
    taken = []
    # ISO first (validated). Times/timezones after the date are ignored.
    for m in re.finditer(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", text):
        d = _safe_date(m.group(1), m.group(2), m.group(3))
        if d:
            found.append((m.start(), d, True))
            taken.append((m.start(), m.end()))
    for kind, pattern in _DATE_PATTERNS:
        for m in pattern.finditer(text):
            if any(not (m.end() <= s or m.start() >= e) for s, e in taken):
                continue
            d = _match_to_date(kind, m, reference)
            if not d:
                continue
            found.append((m.start(), d, kind in {"dmy_text", "mdy_text", "dmy_num"}))
            taken.append((m.start(), m.end()))
            if len(found) >= limit:
                break
    found.sort(key=lambda x: x[0])
    return found


def extract_all_dates(text):
    """All ISO date strings found in text, in order of appearance (deduplicated)."""
    out = []
    for _, d, _ in find_dates_in_text(text):
        s = d.strftime("%Y-%m-%d")
        if s not in out:
            out.append(s)
    return out


def date_range_span_days(text):
    """Detect ranges like '03 Nov 2025, 06:44 – 03 Oct 2029' and return the span in days."""
    text = clean_text(text)
    dates = find_dates_in_text(text)
    explicit = [(pos, d) for pos, d, has_year in dates if has_year]
    for (p1, d1), (p2, d2) in zip(explicit, explicit[1:]):
        between = text[p1:p2]
        if re.search(r"[–—-]|\bto\b|\buntil\b|\btill\b", between[-40:], re.I) and d2 > d1:
            return (d2 - d1).days
    return 0


def parse_iso_datetime_local(value):
    """'2026-10-16T18:00:00Z' -> ('2026-10-16', '7:00PM') in UK time. Naive values are kept as-is."""
    value = clean_text(value)
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+\-]\d{2}:?\d{2})?$", value)
    if not m:
        return None
    date_part, hh, mm, tz = m.groups()
    if not parse_iso_date(date_part):
        return None
    if tz:
        try:
            from zoneinfo import ZoneInfo
            iso = value.replace("Z", "+00:00")
            if re.search(r"[+\-]\d{4}$", iso):
                iso = iso[:-2] + ":" + iso[-2:]
            dt = datetime.fromisoformat(iso).astimezone(ZoneInfo(UK_TIMEZONE))
            return dt.strftime("%Y-%m-%d"), normalise_time_label(dt.strftime("%H:%M"))
        except Exception:
            pass
    return date_part, normalise_time_label(f"{hh}:{mm}")


# ---------------------------------------------------------------------------
# Polite fetching: robots.txt, per-host spacing, access restrictions (Task 3)
# ---------------------------------------------------------------------------
ROBOTS_CACHE = {}
LAST_REQUEST_AT = {}
CRAWL_DELAY = {}


def _site_root(url):
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""


def robots_allows(url):
    """Respect robots.txt (RFC 9309 style). Unreachable 5xx robots => disallow; 4xx => allow."""
    if not RESPECT_ROBOTS_TXT:
        return True
    root = _site_root(url)
    if not root:
        return True
    parser = ROBOTS_CACHE.get(root)
    if parser is None:
        import urllib.robotparser
        parser = urllib.robotparser.RobotFileParser()
        try:
            r = requests.get(root + "/robots.txt", headers=HEADERS, timeout=6)
            if r.status_code == 200:
                parser.parse((r.text or "").splitlines())
            elif 500 <= r.status_code < 600:
                parser.parse(["User-agent: *", "Disallow: /"])
            else:
                parser.parse([])
        except Exception:
            parser.parse([])
        try:
            delay = parser.crawl_delay(HEADERS.get("User-Agent", "*"))
            if delay:
                CRAWL_DELAY[root] = min(float(delay), 10.0)
        except Exception:
            pass
        ROBOTS_CACHE[root] = parser
    try:
        return parser.can_fetch(HEADERS.get("User-Agent", "*"), url)
    except Exception:
        return True


def polite_wait(url):
    root = _site_root(url)
    if not root:
        return
    gap = max(PER_DOMAIN_DELAY_SECONDS, CRAWL_DELAY.get(root, 0))
    last = LAST_REQUEST_AT.get(root)
    if last is not None and gap > 0:
        wait = gap - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
    LAST_REQUEST_AT[root] = time.time()


def http_get(url, timeout=20):
    """Single entry point for plain HTTP fetches. Returns a Response (any status) or None.

    Never bypasses authentication or anti-bot responses: 401/403 are recorded
    as access restrictions and 429 is retried at most once after Retry-After.
    """
    if not robots_allows(url):
        diag_event("blocked_robots", url)
        return None
    polite_wait(url)
    diag_event("attempt", url)
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
    except Exception as exc:
        diag_event("error", url, f"request failed: {exc.__class__.__name__}")
        return None
    if r.status_code == 429:
        retry_after = 0
        try:
            retry_after = int(r.headers.get("Retry-After", "0"))
        except Exception:
            retry_after = 0
        if 0 < retry_after <= 15:
            time.sleep(retry_after)
            try:
                r = requests.get(url, headers=HEADERS, timeout=timeout)
            except Exception as exc:
                diag_event("error", url, f"request failed: {exc.__class__.__name__}")
                return None
        if r.status_code == 429:
            diag_event("error", url, "rate limited (429)")
    elif r.status_code in (401, 403):
        diag_event("error", url, f"access restricted ({r.status_code})")
    elif r.status_code >= 400:
        diag_event("error", url, f"HTTP {r.status_code}")
    return r


# ---------------------------------------------------------------------------
# Diagnostics (Task 7)
# ---------------------------------------------------------------------------
class VenueDiagnostics:
    def __init__(self, venue):
        self.venue = venue
        self.listing_pages = []
        self.pages_attempted = []
        self.pages_parsed = []
        self.detail_pages = 0
        self.pagination_pages = 0
        self.playwright_used = False
        self.js_not_loaded = False
        self.candidates = {}
        self.rejected = {}
        self.date_excluded = {}
        self.undated = set()
        self.duplicates_removed = 0
        self.location_flags = []
        self.errors = []
        self.blocked_robots = False
        self.accepted = []
        self.long_running_skipped = 0
        self.ambiguous_merges = 0
        self.cap_hit = ""

    def status(self):
        exceptions = [e for e in self.errors if e.startswith("exception:")]
        if exceptions:
            return "Scraper exception (" + exceptions[0][len("exception:"):].strip()[:120] + ")"
        if self.accepted:
            return "ok (safety cap reached)" if self.cap_hit else "ok"
        if self.blocked_robots and not self.pages_parsed:
            return "Blocked by robots.txt"
        if any("access restricted" in e for e in self.errors) and not self.pages_parsed:
            return "Access restricted (not bypassed)"
        if not self.pages_parsed:
            return "Request failed" if self.errors or self.pages_attempted else "No website fetched"
        if self.js_not_loaded and not self.candidates:
            return "JavaScript calendar not loaded" + ("" if self.playwright_used else " (run with --headless)")
        if not self.candidates:
            return "No event calendar discovered"
        relevant_dated = set(self.candidates) - set(self.rejected) - self.undated
        if not relevant_dated and self.rejected:
            return "No relevant comedy events (non-comedy listings only)"
        if self.date_excluded and not (relevant_dated - set(self.date_excluded)):
            return "All events past or outside date window"
        if self.undated and not relevant_dated:
            return "No valid event dates"
        if self.duplicates_removed:
            return "Duplicate-only results"
        return "No relevant comedy events"

    def row(self):
        v = self.venue
        cats = [clean_text((e.get("_classification") or {}).get("category", "")) for e in self.accepted]
        return {
            "venue": v.get("title", ""),
            "city": v.get("city", ""),
            "website": v.get("website", ""),
            "venue_confidence": v.get("venue_confidence", ""),
            "status": self.status(),
            "listing_page_found": self.listing_pages[0] if self.listing_pages else "",
            "listing_pages": " | ".join(self.listing_pages[:8]),
            "pages_attempted": len(self.pages_attempted),
            "pages_parsed": len(self.pages_parsed),
            "detail_pages_fetched": self.detail_pages,
            "pagination_pages_followed": self.pagination_pages,
            "playwright_required": "yes" if self.playwright_used else ("needed (not enabled)" if self.js_not_loaded else "no"),
            "candidate_events": len(self.candidates),
            "events_accepted": len(self.accepted),
            "rejected_by_relevance": len(self.rejected),
            "excluded_by_date": len(self.date_excluded),
            "undated_candidates": len(self.undated),
            "duplicates_removed": self.duplicates_removed,
            "ambiguous_time_matches_kept": self.ambiguous_merges,
            "open_mic_confirmed": cats.count("confirmed_open_mic"),
            "open_mic_probable": cats.count("probable_open_mic"),
            "open_mic_poetry": cats.count("poetry_open_mic"),
            "new_act_or_wip": cats.count("new_act_showcase"),
            "tour_or_solo_candidates": sum(1 for e in self.accepted if e.get("_tour")),
            "location_flags": " | ".join(sorted(set(self.location_flags)))[:500],
            "cap_reached": self.cap_hit,
            "errors": " | ".join(dedupe_ordered(self.errors))[:800],
        }


def _event_key(e):
    return (slugify_text(e.get("title", "")), clean_text(e.get("date", "")), canonical_event_url(e.get("ticket_url", "")))


def diag_event(kind, url="", detail="", event=None):
    d = DIAGNOSTICS
    if d is None:
        return
    if kind == "attempt":
        d.pages_attempted.append(url)
    elif kind == "parsed":
        if url not in d.pages_parsed:
            d.pages_parsed.append(url)
    elif kind == "error":
        d.errors.append(f"{detail}: {url}" if url else detail)
    elif kind == "blocked_robots":
        d.blocked_robots = True
        d.errors.append(f"blocked by robots.txt: {url}")
    elif kind == "listing":
        if url and url not in d.listing_pages:
            d.listing_pages.append(url)
    elif kind == "detail":
        d.detail_pages += 1
    elif kind == "pagination":
        d.pagination_pages += 1
    elif kind == "playwright":
        d.playwright_used = True
    elif kind == "js_not_loaded":
        d.js_not_loaded = True
    elif kind == "candidate" and event is not None:
        d.candidates[_event_key(event)] = event
    elif kind == "rejected" and event is not None:
        d.rejected[_event_key(event)] = detail
        add_review_row(event, "rejected", detail)
    elif kind == "date_excluded" and event is not None:
        d.date_excluded[_event_key(event)] = detail
    elif kind == "undated" and event is not None:
        d.undated.add(_event_key(event))
    elif kind == "location" and event is not None:
        d.location_flags.append(detail)
        add_review_row(event, "location", detail)
    elif kind == "cap":
        d.cap_hit = detail
    elif kind == "long_running":
        d.long_running_skipped += 1
    elif kind == "ambiguous_merge" and event is not None:
        d.ambiguous_merges += 1
        add_review_row(event, "ambiguous-duplicate", detail)


def add_review_row(event, kind, reason):
    venue = (DIAGNOSTICS.venue if DIAGNOSTICS else CURRENT_VENUE) or {}
    cls = event.get("_classification") or {}
    REVIEW_ROWS.append({
        "kind": kind,
        "reason": clean_text(reason),
        "classification": cls.get("category", ""),
        "signals": cls.get("signals", ""),
        "title": clean_text(event.get("title", "")),
        "date": clean_text(event.get("date", "")),
        "time": clean_text(event.get("time", "")),
        "venue": clean_text(event.get("venue", "")),
        "city": clean_text(event.get("city", "")),
        "source_type": clean_text(event.get("source_type", "")),
        "ticket_url": clean_text(event.get("ticket_url", "")),
        "scraped_from_venue": clean_text(venue.get("title", "")),
        "description": clean_text(event.get("description", ""))[:300],
    })


# ---------------------------------------------------------------------------
# First names used to recognise individual comedians in "Name: Show" titles
# (so club brands like "Brain Drain: All Kiwi Comedy" are not labelled tours).
# Source: NLTK Names Corpus 1.3, redistributed under its licence (README below),
# plus a short supplement of names common on the UK comedy circuit.
# Names Corpus, Version 1.3 (1994-03-29)
# Copyright (C) 1991 Mark Kantrowitz
# Additions by Bill Ross
#
# This corpus contains 5001 female names and 2943 male names, sorted
# alphabetically, one per line.
#
# You may use the lists of names for any purpose, so long as credit is
# given in any published work. You may also redistribute the list if you
# provide the recipients with a copy of this README file. The lists are
# not in the public domain (I retain the copyright on the lists) but are
# freely redistributable.  If you have any additions to the lists of
# names, I would appreciate receiving them.
#
# Mark Kantrowitz <mkant+@cs.cmu.edu>
# http://www-2.cs.cmu.edu/afs/cs/project/ai-repository/ai/areas/nlp/corpora/names/
# ---------------------------------------------------------------------------
FIRST_NAMES = frozenset((
    "aamir aaron abagael abagail abbe abbey abbi abbie abbot abbott abby abdel abdul abdulkarim abdullah abe abel "
    "abelard abigael abigail abigale abner abra abraham abram acacia ace ada adah adair adaline adam adams adara "
    "addie addis ade adel adela adelaide adele adelice adelina adelind adeline adella adelle adena adey adger adi "
    "adiana adina aditya adlai adnan adolf adolfo adolph adolphe adolpho adolphus adora adore adoree adorne adrea "
    "adria adriaens adrian adriana adriane adrianna adrianne adrick adrien adriena adrienne aeriel aeriela aeriell "
    "ag agace agamemnon agata agatha agathe aggi aggie aggy agna agnella agnes agnese agnesse agneta agnola "
    "agretha aguinaldo aguste agustin aharon ahir ahmad ahmed ahmet aida aidan aigneis aila aile ailee aileen "
    "ailene ailey aili ailina ailyn aime aimee aimil aina aindrea aine ainslee ainsley ainslie aisling ajai ajay "
    "al alaa alain alaine alameda alan alana alanah alane alanna alasdair alastair alayne albatros albert alberta "
    "albertina albertine alberto albina albrecht alden aldis aldo aldric aldrich aldus aldwin alec alecia aleck "
    "aleda aleece aleecia aleen alejandra alejandrina alejandro aleks aleksandrs alena alene alessandra alessandro "
    "aleta alethea alex alexa alexander alexandra alexandrina alexei alexi alexia alexina alexine alexis alf alfie "
    "alfonse alfonso alfonzo alford alfred alfreda alfredo algernon ali alia alic alica alice alicea alicia alida "
    "alidia alina aline alis alisa alisha alison alissa alister alisun alix aliza alla allah allan alleen allegra "
    "allen allene alley alli allianora allie allin allina allis allison allissa allsun ally allyce allyn allys "
    "allyson alma almeda almeria almeta almira almire aloise aloisia alonso alonzo aloysia aloysius alpa alphonse "
    "alphonso alston alta althea alton alun alvera alvin alvina alvinia alvira alwin alyce alyda alys alysa alyse "
    "alysia alyson alyss alyssa amabel amabelle amadeus amalea amalee amaleta amalia amalie amalita amalle amanda "
    "amandi amandie amandy amara amargo amata amber amberly ambros ambrose ambrosi ambrosia ambrosio ambrosius "
    "ambur ame amelia amelie amelina ameline amelita amery ami amie amity ammamaria amory amos amy ana anabel "
    "anabella anabelle anais analiese analise anallese anallise anastasia anastasie anastassia anatol anatola "
    "anatole anatollo anatoly andee anders andi andie andonis andra andre andrea andreana andreas andree andrei "
    "andrej andres andrew andrey andri andria andriana andriette andromache andromeda andros andrus andrzej andy "
    "anestassia anet anett anetta anette ange angel angela angele angelia angelica angelico angelika angelina "
    "angeline angelique angelita angelle angelo angie angil angus angy ania anica anissa anita anitra anja "
    "anjanette anjela ann ann-mari ann-marie anna anna-diana anna-diane anna-maria annabal annabel annabela "
    "annabell annabella annabelle annadiana annadiane annalee annalena annaliese annalisa annalise annalyse "
    "annamari annamaria annamarie anne anne-corinne anne-mar anne-marie annecorinne anneliese annelise annemarie "
    "annetta annette anni annice annie annissa annmaria annmarie annnora annora anny ansel ansell anselm anselma "
    "ansley anson anstice anthe anthea anthia anthony antin antoine antoinette anton antone antonella antonetta "
    "antoni antonia antonie antonietta antonin antonina antonino antonio antonius antony anurag anya aphrodite "
    "apollo apostolos appolonia april aprilette ara arabel arabela arabele arabella arabelle aram archibald "
    "archibold archie archon archy arda ardath ardeen ardelia ardelis ardella ardelle arden ardene ardenia ardine "
    "ardis ardith ardra ardyce ardys ardyth arel aretha ari ariadne ariana arianne aridatha arie ariel ariela "
    "ariella arielle aristotle arlana arlee arleen arlen arlena arlene arleta arlette arleyne arlie arliene arlina "
    "arlinda arline arlo arly arlyn arlyne armand armando armond armstrong arne arnie arnold arnoldo aron arron "
    "art arther arthur artie artur arturo arvie arvin arvind arvy aryn ash ashby ashely ashish ashlee ashleigh "
    "ashlen ashley ashli ashlie ashly ashton asia astra astrid astrix atalanta athena athene atlanta atlante aub "
    "aube aubert auberta aubine aubree aubrette aubrey aubrie aubry audi audie audra audre audrey audrie audry "
    "audrye audy augie august augusta auguste augustin augustina augustine augusto augustus aura aurea aurel "
    "aurelea aurelia aurelie auria aurie aurilia aurlie auroora aurora aurore austen austin austina austine ava "
    "ave aveline averell averil averill avery averyl avi avie avis aviva avivah avraham avram avril avrit avrom "
    "axel aylmer ayn aziz bab babara babette babita babs bailey bailie baillie baily baird baldwin bambi bambie "
    "bamby bancroft barb barbabas barbabra barbara barbara-anne barbaraanne barbe barbee barbette barbey barbi "
    "barbie barbra barby barclay bard barde bari barn barnabas barnabe barnaby barnard barnebas barnett barney "
    "barnie barny baron barr barret barrett barri barrie barris barron barry bart bartel barth barthel bartholemy "
    "bartholomeo bartholomeus bartholomew bartie bartlet bartlett bartolemo bartolomei bartolomeo barton barty "
    "bary basia basil batholomew bathsheba batsheva baxter bay bayard bea beale bealle bear bearnard beatrice "
    "beatrisa beatrix beatriz beau beaufort beauregard bebe becca beck becka becki beckie becky bee beilul beitris "
    "bekki bel bela belia belicia belinda belita bell bella bellamy bellanca belle bellina belva belvia ben "
    "bendite benedetta benedict benedicta benedikta benetta bengt benita benito benjamen benjamin benji benjie "
    "benjy benn bennet bennett benni bennie benny benoite benson bentley benton beowulf berchtold berenice beret "
    "berget berk berke berkeley berkie berkley berna bernadene bernadette bernadina bernadine bernard bernardina "
    "bernardine bernardo bernd bernelle bernete bernetta bernette bernhard berni bernice bernie bernita berny "
    "berri berrie berry bert berta berte bertha berthe berti bertie bertina bertine bertram bertrand berty beryl "
    "beryle bess bessie bessy beth bethanne bethany bethena bethina betsey betsy betta bette bette-ann betteann "
    "betteanne betti bettie bettina bettine betty bettye beulah bev beverie beverlee beverlie beverly bevvy bharat "
    "bianca bianka biddy bidget biff bill billi billie billy bing binky binni binnie binny bird birdie birgit "
    "birgitta bishop bjorn bjorne blaine blair blaire blake blakelee blakeley blanca blanch blancha blanche blare "
    "blayne blinni blinnie blinny bliss blisse blithe blondell blondelle blondie blondy blythe bo bob bobbette "
    "bobbi bobbie bobby bobette bobina bobine bobinette bogart bogdan boniface bonita bonnee bonni bonnie bonny "
    "boris boyce boyd brad braden bradford bradley bradly brady brana brandais brande brandea brandi brandice "
    "brandie brandise brandon brandy brant brea breanne brear bree breena bren brena brenda brendan brenn brenna "
    "brent bret brett brewer brewster bria brian briana brianna brianne brice bride bridget bridgett bridgette "
    "bridie brier brietta briggs brigid brigida brigit brigitta brigitte brina briney brinkley briny brit brita "
    "britaney britani briteny britney britni britt britta brittan brittany britte brittney brock broddie broddy "
    "broderic broderick brodie brody bronson brook brooke brooks bruce brunella brunhilda brunhilde bruno bryan "
    "bryana bryant bryce bryn bryna brynn brynna brynne bryon bubba buck bucky bud buddy buffy bunni bunnie bunny "
    "burgess burke burl burnaby burt burta burton buster butch butler byram byron cabrina cacilia cacilie caesar "
    "cain caitlin caitrin cal caldwell caleb calhoun calida calla calley calli callida callie cally calvin calypso "
    "cam camala camel camella camellia cameo cameron cami camila camile camilla camille cammi cammie cammy canada "
    "candace candi candice candida candide candie candis candra candy cappella caprice cara caralie caren carena "
    "caresa caressa caresse carey cari caria carie caril carilyn carin carina carine cariotta carissa carita "
    "caritta carl carla carlee carleen carleigh carlen carlena carlene carley carli carlie carlin carlina carline "
    "carlisle carlita carlo carlos carlota carlotta carlton carly carlye carlyle carlyn carlynn carlynne carma "
    "carmel carmela carmelia carmelina carmelita carmella carmelle carmen carmina carmine carmita carmon caro "
    "carol carol-jean carola carolan carolann carole carolee caroleen carolie carolin carolina caroline caroljean "
    "carolyn carolyne carolynn caron carree carri carrie carrissa carrol carroll carry carson carsten carter cary "
    "caryl caryn casandra case casey casi casia casie caspar casper cass cassandra cassandre cassandry cassaundra "
    "cassey cassi cassie cassondra cassy cat catarina cate caterina catha catharina catharine cathe cathee "
    "catherin catherina catherine cathi cathie cathleen cathlene cathrin cathrine cathryn cathy cathyleen cati "
    "catie catina catlaina catlee catlin catrina catriona caty cayla cecelia cecil cecile ceciley cecilia cecilla "
    "cecily ceil cele celene celesta celeste celestia celestina celestine celestyn celestyna celia celie celina "
    "celinda celine celinka celisse celle cesar cesya chad chadd chaddie chaddy chadwick chaim chalmers chan "
    "chance chancey chanda chandal chanderjit chandler chandra chane channa chantal chantalle charil charin "
    "chariot charis charissa charisse charita charity charla charlean charleen charlena charlene charles charleton "
    "charley charlie charline charlot charlott charlotta charlotte charlton charmain charmaine charmane charmian "
    "charmine charmion charo charyl chas chase chastity chaunce chauncey che chelsae chelsea chelsey chelsie "
    "chelsy chelton chen cher chere cherey cheri cherianne cherice cherida cherie cherilyn cherilynn cherin "
    "cherise cherish cherlyn cherri cherrita cherry chery cherye cheryl cheslie chester cheston chet chev "
    "chevalier chevy chiarra chickie chicky chip chiquita chloe chloette chloris chris chriss chrissa chrissie "
    "chrissy christ christa christabel christabella christabelle christal christalle christan christean christel "
    "christen christi christian christiana christiane christiano christie christin christina christine christof "
    "christofer christoph christophe christopher christorpher christos christy christyna chrisy chrysa chrysler "
    "chrystal chryste chrystel chuck churchill ciara cicely cicily ciel cilka cinda cindee cindelyn cinderella "
    "cindi cindie cindra cindy cinnamon cissie cissy clair claire clancy clara clarabelle clarance clare clarence "
    "claresta clareta claretta clarette clarey clari claribel clarice clarie clarinda clarine clarisa clarissa "
    "clarisse clarita clark clarke clary claude claudelle claudetta claudette claudia claudie claudina claudine "
    "claudio claudius claus clay clayborn clayborne claybourne clayton clea cleland clem clemence clemens clement "
    "clemente clementia clementina clementine clemmie clemmy cleo cleopatra clerissa cletus cleva cleveland cliff "
    "clifford clifton clint clinten clinton clio clive clo cloe cloris clotilda clovis clyde cob cobb cobbie cobby "
    "codee codi codie cody colbert cole coleen coleman colene coletta colette colin colleen collete collette "
    "collie collin colline collins colly con conan concettina conchita concordia conney conni connie connolly "
    "connor conny conrad conroy consolata constance constancia constancy constanta constantia constantin "
    "constantina constantine constantinos consuela consuelo conway cookie cooper cora corabel corabella corabelle "
    "coral coralie coraline coralyn corbin corby cordelia cordelie cordey cordie cordula cordy coreen corella "
    "corena corenda corene coretta corette corey cori corie corilla corina corine corinna corinne coriss corissa "
    "corky corliss corly cornela cornelia cornelius cornelle cornellis cornie corny correna correy corri corrianne "
    "corrie corrina corrine corrinne corry cortese cortney corwin cory cosetta cosette cosmo costa courtenay "
    "courtney craig crawford creighton cresa cris crissie crissy crista cristabel cristal cristen cristi cristie "
    "cristin cristina cristine cristionna cristopher cristy crysta crystal crystie curt curtice curtis cy cyb "
    "cybal cybel cybelle cybil cybill cyndi cyndy cynthea cynthia cynthie cynthy cyril cyrill cyrille cyrillus "
    "cyrus dabney dacey dacia dacie dacy dael daffi daffie daffy dafna dagmar dahlia daile daisey daisi daisie "
    "daisy dale dalenna dalia dalila dallas daloris dalton damara damaris damian damien damita damon dan dana dane "
    "danell danella danelle danette dani dania danica danice danie daniel daniela daniele daniella danielle danika "
    "danila danit danita danna danni dannie danny dannye dante danya danyelle danyette daphene daphna daphne dara "
    "darb darbie darby darcee darcey darci darcie darcy darda dareen darell darelle daren dari daria darian darice "
    "darien darin dario darius darla darleen darlene darline darrel darrell darren darrick darrin darryl darsey "
    "darsie darth darwin darya daryl daryle daryn dasha dasi dasie dasya datha daune dave daveen daveta davey "
    "david davida davidde davide davidson davie davin davina davine davis davita davon davoud davy dawn dawna "
    "dawson dayle dayna daz dea dean deana deane deanna deanne deb debbi debbie debbra debby debee debera debi "
    "debor debora deborah debra dede dedie dedra dee dee dee deeann deeanne deedee deena deerdre dehlia deidre "
    "deina deirdre del dela delaney delbert delcina delcine delia delila delilah delinda dell della delly delmar "
    "delora delores deloria deloris delphina delphine delphinia demeter demetra demetre demetri demetria demetris "
    "demetrius demosthenis dena deni denice denis denise denna denni dennie dennis denny deny denys denyse deonne "
    "derby derek derick derk derrek derrick derrin derrol derron deryl desaree desdemona desirae desiree desiri "
    "desmond desmund deva devan devi devin devina devinne devon devondra devonna devonne devora dew dewey dewitt "
    "dexter di diahann diamond dian diana diandra diane diane-marie dianemarie diann dianna dianne diannne dick "
    "dickey dickie didi dido diego diena dierdre dieter dietrich dillon dimitri dimitrios dimitris dimitrou "
    "dimitry dina dinah dinnie dinny dino dion dione dionis dionne dionysus dirk dita dix dixie dmitri dode dodi "
    "dodie dody doe doll dolley dolli dollie dolly dolora dolores dolorita doloritas dom domenic domenico dominic "
    "dominica dominick dominique don dona donal donald donella donelle donetta donia donica donielle donn donna "
    "donnajean donnamarie donni donnie donny donovan dora doralia doralin doralyn doralynn doralynne dorcas dore "
    "doreen dorelia dorella dorelle dorena dorene doretta dorette dorey dori doria dorian dorice dorie dorine "
    "doris dorisa dorise dorit dorita doro dorolice dorolisa dorotea doroteya dorothea dorothee dorothy dorree "
    "dorri dorrie dorris dorry dorthea dorthy dory dosi dot doti dotti dottie dotty doug douggie dougie douglas "
    "douglass douglis dov dove doyle drake drea drew dru dryke duane dudley duffie duffy dugan duke dulce dulcea "
    "dulci dulcia dulciana dulcie dulcine dulcinea dulcy dulsea dunc duncan dunstan durand durant durante durward "
    "dustin dusty dwain dwaine dwane dwayne dwight dyan dyana dyane dyann dyanna dyanne dylan dyna dynah dyson "
    "e'lane eada eadie eadith ealasaid earl earle eartha easter easton eba ebba eben ebeneser ebenezer eberhard "
    "ebonee ebony ed eda eddi eddie eddy ede edee edeline eden edgar edgardo edi edie edin edita edith editha "
    "edithe ediva edmond edmund edna edouard edsel eduard eduardo edward edwin edwina edy edyth edythe effie efram "
    "egbert ehud eileen eilis eimile eirena ekaterina elaina elaine elana elane elayne elbert elberta elbertina "
    "elbertine elden eldon eleanor eleanora eleanore electra elena elene eleni elenore eleonora eleonore elfie "
    "elfreda elfrida elfrieda elga eli elianora elianore elias elicia elie elihu elijah elinor elinore eliot "
    "eliott elisa elisabet elisabeth elisabetta elise elisha elissa elita eliza elizabet elizabeth elka elke ella "
    "elladine elle ellen ellene ellette elli ellie elliot elliott ellis ellissa ellsworth ellwood elly ellyn "
    "ellynn elmer elmira elmore elna elnar elnora elnore eloisa eloise elonore elora elric elroy elsa elsbeth else "
    "elsey elsi elsie elsinore elspeth elsy elton elva elvera elvin elvina elvira elvis elwin elwina elwira elwood "
    "elwyn ely elyn elyse elysee elysha elysia elyssa em ema emalee emalia emanuel emanuela emelda emelia emelina "
    "emeline emelita emelyne emera emerson emery emil emile emilee emili emilia emilie emiline emilio emily emlyn "
    "emlynn emlynne emma emmalee emmaline emmalyn emmalynn emmalynne emmanuel emmeline emmery emmet emmett emmey "
    "emmi emmie emmit emmott emmy emmye emogene emory emyle emylee ender endora engelbart engelbert englebart "
    "englebert engracia enid enoch enrica enrichetta enrico enrika enrique enriqueta enya eolanda eolande ephraim "
    "ephram ephrayim ephrem er eran erasmus erastus erda erek erena erhard erhart eric erica erich ericha erick "
    "ericka erik erika erin erina erinn erinna erl erma ermengarde ermentrude ermina erminia erminie erna ernaline "
    "ernest ernesta ernestine ernesto ernie ernst erny errol ertha ervin erwin eryn esau eshaan esma esmaria esme "
    "esmeralda esmerelda essa essie essy esta esteban estel estele estell estella estelle ester esther estrella "
    "estrellita ethan ethel ethelbert ethelda ethelin ethelind etheline ethelred ethelyn ethyl etienne etta etti "
    "ettie etty euclid eudora eugen eugene eugenia eugenie eugine eula eulalie eunice euphemia eustace eustacia ev "
    "eva evaleen evan evangelia evangelin evangelina evangeline evania evanne eve eveleen evelina eveline evelyn "
    "everard everett evette evey evie evita evonne evvie evvy evy ewan ewart eyde eydie ez ezechiel ezekiel ezra "
    "fabian fabio fabrianne fabrice fae faina fairfax faith fallon fan fanchette fanchon fancie fancy fanechka "
    "fania fanni fannie fanny fanya fara farah farand farica farley farra farrah farrand fatima faun faunie "
    "faustina faustine fawn fawna fawne fawnia fay faydra faye fayette fayina fayre fayth faythe fazeel federica "
    "federico fedora felecia felicdad felice felicia felicio felicity felicle felipa felipe felisha felita felix "
    "feliza fenelia feodora ferd ferdie ferdinand ferdinanda ferdinande ferdy fergus ferguson ferinand fern "
    "fernanda fernande fernandina fernando ferne fey fiann fianna fidel fidela fidelia fidelity fifi fifine "
    "filbert filia filide filip filipe filippa filmore fin fina finley finn fiona fionna fionnula fiorenze fitz "
    "fitzgerald flem fleming flemming fletch fletcher fleur fleurette flin flinn flint flipper flo flor flora "
    "florance flore florella florence florencia florentia florenza florette flori floria florian florice florida "
    "florie florina florinda floris florri florrie florry flory flossi flossie flossy flower floyd flynn fons "
    "fonsie fonz fonzie forbes ford forest forester forrest forrester forster fortuna fortune foster fowler fox "
    "fran france francene frances francesca francesco francesmary francine francis francisca francisco franciska "
    "francois francoise francyne frank frankie franklin franklyn franky franni frannie franny frans franz fraser "
    "frayda frazier fred freda freddi freddie freddy fredelia frederic frederica frederich frederick fredericka "
    "frederico frederik fredi fredia fredra fredric fredrick fredrika freeman freemon freida fremont french frieda "
    "friederike friedric friedrich friedrick fritz fulton fulvia fyodor gabbey gabbi gabbie gabe gabey gabi gabie "
    "gabriel gabriela gabriele gabriell gabriella gabrielle gabriellia gabriello gabrila gaby gae gael gail gale "
    "galen galina gallagher gamaliel garcia garcon gardener gardiner gardner garey garfield garfinkel garland "
    "garnet garnette garold garp garret garrett garrot garrott garry garth garv garvey garvin garvy garwin garwood "
    "gary gaspar gasper gaston gates gav gaven gavin gavra gavriel gavrielle gay gayla gayle gayleen gaylene "
    "gaynor gaz gearard geeta gelya gen gena gene geneva genevieve genevra genia genna genni gennie gennifer genny "
    "genovera genvieve geo geof geoff geoffrey geoffry georg george georgeanna georgeanne georgena georges "
    "georgeta georgetta georgette georgia georgiamay georgiana georgianna georgianne georgie georgina georgine "
    "georgy gera gerald geralda geraldina geraldine geraldo gerard gerda gere gerhard gerhardine gerhardt geri "
    "gerianna gerianne gerladina germain germaine germana gerold gerome gerrard gerri gerrie gerrilee gerrit gerry "
    "gershom gershon gert gerta gerti gertie gertrud gertruda gertrude gertrudis gerty giacinta giacomo gian giana "
    "giancarlo gianina gianna giavani gibb gideon giff giffard giffer giffie gifford giffy gigi gil gilbert "
    "gilberta gilberte gilbertina gilbertine gilberto gilburt gilda giles gill gillan gilles gilli gillian gillie "
    "gilligan gilly gina ginelle ginevra ginger ginni ginnie ginnifer ginny gino giordano giorgi giorgia giorgio "
    "giovanna giovanne giovanni gipsy giralda giraldo giraud gisela gisele gisella giselle gita giuseppe gizela "
    "glad gladi gladis gladys gleda glen glenda glenine glenn glenna glennie glennis glori gloria gloriana "
    "gloriane glorianna glory glyn glynda glynis glynn glynnis godard godart goddard goddart godfree godfrey "
    "godfry godiva godwin golda goldarina goldi goldia goldie goldina goldy gomer gonzales gonzalo goober goose "
    "gordan gordie gordon grace gracia gracie grady graehme graeme graham graig grant granville grata gratia "
    "gratiana gray grayce grazia gredel greer greg gregg greggory gregor gregorio gregory greta gretal gretchen "
    "grete gretel grethel gretna gretta grier griff griffin griffith griselda grissel griswold grove grover "
    "guendolen guenevere guenna guglielma gui guido guillaume guillema guillemette guillermo guinevere guinna "
    "gunilla gunner gunter gunther gunvor gus gusella gussi gussie gussy gusta gustaf gustav gustave gustavo "
    "gustavus gusti gustie gusty guthrey guthrie guthry guy guz gwen gwendolen gwendolin gwendolyn gweneth "
    "gwenette gwenn gwenneth gwenni gwennie gwenny gwenora gwenore gwyn gwyneth gwynne gypsy hadleigh hadley "
    "hadria hadrian hagan hagen hailee hailey haily hakeem hakim hal hale haleigh halette haley hali halie "
    "halimeda hall hallam halley halli hallie hally halvard ham hamel hamid hamil hamilton hamish hamlen hamlet "
    "hamlin hammad hamnet hamza han hana hanan hanford hank hanna hannah hanni hannibal hannie hannis hanny hans "
    "hans-peter hansel hanson happy harald harcourt hari harlan harland harlene harley harli harlie harlin harman "
    "harmon harmonia harmonie harmony harold harri harrie harriet harriett harrietta harriette harriot harriott "
    "harris harrison harrold harry hart hartley hartwell harv harvard harvey harvie harwell hasheem hashim haskel "
    "haskell hassan hastings hasty hatti hattie hatty haven havivah hayden haydon hayes hayley hayward haywood "
    "hazel heath heathcliff heather hebert hector heda hedda heddi heddie hedi hedvig hedwig hedy heida heide "
    "heidi heidie heinrich heinz helaina helaine helen helen-elizabeth helena helene helga helge helise hellene "
    "helli helmuth heloise helsa helyn henderson hendrick hendrik hendrika henka henri henrie henrieta henrietta "
    "henriette henrik henrique henry henryetta hephzibah herb herbert herbie herby hercule hercules herculie "
    "herman hermann hermia hermina hermine herminia hermione hermon hermy hernando herold herrick herrmann hersch "
    "herschel hersh hershel herta hertha herve hervey hester hesther hestia hetti hettie hetty hew hewe hewet "
    "hewett hewie hewitt heywood hezekiah higgins hilarie hilary hilbert hilda hildagard hildagarde hilde "
    "hildegaard hildegarde hildy hill hillard hillary hillel hillery hilliard hilliary hilton hinda hiralal hiram "
    "hiro hirsch hobart hodge hogan holley holli hollie hollis holly holly-anne hollyanne homer honey honor "
    "honoria hope horace horacio horatia horatio horatius horst hortense hortensia howard howie hoyt hubert hudson "
    "huey huge hugh hugo hulda humbert humphrey hunt hunter huntington huntlee huntley hurley husain husein "
    "hussein hy hyacinth hyacintha hyacinthe hyacinthia hyacinthie hyatt hyman hymie hynda iago iain ian ianthe "
    "ibbie ibby ibrahim ichabod ida idalia idalina idaline idell idelle idette iggie iggy ignace ignacio ignacius "
    "ignatius ignaz ignazio igor ike ikey ilana ileana ileane ilene ilise ilka illa ilona ilsa ilse ilysa ilyse "
    "ilyssa imelda immanuel imogen imogene imojean imran ina inci indira ines inesita inessa inez inga ingaberg "
    "ingaborg ingamar inge ingeberg ingeborg ingelbert ingemar inger inglebert ingmar ingram ingrid ingunna inigo "
    "inna ioana iolande iolanthe iona iormina ira irena irene irina iris irita irma irvin irvine irving irwin isa "
    "isaac isaak isabeau isabel isabelita isabella isabelle isador isadora isadore isahella isaiah iseabal ishmael "
    "isidora isidore isis ismail isobel israel issi issie issy istvan ivan ivett ivette ivie ivo ivonne ivor ivory "
    "ivy izaak izabel izak izzi izzy jabez jacenta jacinda jacinta jacintha jacinthe jack jackelyn jacki jackie "
    "jacklin jacklyn jackquelin jackqueline jackson jacky jaclin jaclyn jacob jacquelin jacqueline jacquelyn "
    "jacquelynn jacquenetta jacquenette jacques jacquetta jacquette jacqui jacquie jacynth jada jade jae jaime "
    "jaimie jaine jak jake jakob jaleh jamali james jameson jamey jami jamie jamima jammie jan jana janaya janaye "
    "jandy jane janean janeczka janeen janel janela janella janelle janene janenna janessa janet janeta janetta "
    "janette janeva janey jania janice janie janifer janina janine janis janith janka janna jannel jannelle janos "
    "janot janus jany jaquelin jaquelyn jaquenetta jaquenette jaquith jared jarrett jarvis jasmin jasmina jasmine "
    "jason jasper javier jay jayde jayme jaymee jayne jaynell jazmin jean jean-christophe jean-francois jean-lou "
    "jean-luc jean-marc jean-paul jean-pierre jeana jeane jeanelle jeanette jeanie jeanine jeanna jeanne jeannette "
    "jeannie jeannine jeb jed jedediah jef jeff jefferey jefferson jeffery jeffie jeffrey jeffry jefry jehanna "
    "jehu jelene jemie jemima jemimah jemmie jemmy jen jena jenda jenelle jenette jeni jenica jeniece jenifer "
    "jeniffer jenilee jenine jenn jenna jennee jennette jenni jennica jennie jennifer jennilee jennine jennings "
    "jenny jens jephthah jerald jeraldine jeralee jeramie jere jereme jeremiah jeremias jeremie jeremy jeri "
    "jermain jermaine jermayne jerold jerome jeromy jerri jerrie jerrilee jerrilyn jerrine jerrold jerrome jerry "
    "jerrylee jervis jerzy jess jessa jessalin jessalyn jessamine jessamyn jesse jessee jesselyn jessey jessi "
    "jessica jessie jessika jessy jesus jeth jethro jewel jewell jewelle jill jillana jillane jillayne jilleen "
    "jillene jilli jillian jillie jilly jim jimbo jimmie jimmy jinny jo jo ann jo-ann jo-anne joab joachim joan "
    "joana joane joanie joann joanna joanne joannes joao joaquin job jobey jobi jobie jobina joby jobye jobyna "
    "jocelin joceline jocelyn jocelyne jock jodee jodi jodie jody joe joel joela joelie joell joella joelle "
    "joellen joelly joellyn joelynn joete joey johan johann johanna johannah johannes john john-david john-patrick "
    "johnathan johnathon johnette johnna johnnie johnny johny joice jojo jolee joleen jolene joletta joli jolie "
    "joline joly jolyn jolynn jon jonah jonas jonathan jonathon jonell joni jonie jonis jonny jordain jordan "
    "jordana jordanna jordon jordy jorey jorge jori jorie jorrie jorry jory joscelin jose josee josef josefa "
    "josefina joselyn joseph josepha josephina josephine josephus josey josh joshua joshuah josi josiah josie "
    "joslyn josselyn josy jotham jourdan joy joya joyan joyann joyce joycelin joye joyous juan juana juanita jud "
    "judah judas judd jude judi judie judith juditha judson judy judye juergen jule julee jules juli julia julian "
    "juliana juliane juliann julianna julianne julie julienne juliet julieta julietta juliette julina juline julio "
    "julissa julita julius june junette junia junie junina justin justina justine justis jyoti kaari kacey kacie "
    "kacy kae kai kaia kaila kaile kailey kaiser kaitlin kaitlyn kaitlynn kaja kakalina kala kaleb kaleena kali "
    "kalie kalil kalila kalina kalinda kalindi kalle kalli kally kalman kalvin kam kameko kamila kamilah kamillah "
    "kandace kandy kane kania kanya kara kara-lynn karalee karalynn kare karee kareem karel karen karena kari "
    "karia karie karil karilynn karim karin karina karine kariotta karisa karissa karita karl karla karlee karleen "
    "karlen karlene karlie karlotta karlotte karly karlyn karmen karna karol karola karole karolina karoline "
    "karoly karon karrah karrie karry karsten kary karyl karylin karyn kasey kaspar kass kassandra kassey kassi "
    "kassia kassie kaster kat kata katalin kate katee katerina katerine katey kath katha katharina katharine "
    "katharyn kathe katheleen katherina katherine katheryn kathi kathie kathleen kathlene kathlin kathrine kathryn "
    "kathryne kathy kathye kati katie katina katine katinka katleen katlin katrina katrine katrinka katti kattie "
    "katuscha katusha katy katya kay kaycee kaye kayla kayle kaylee kayley kaylil kaylyn kee keefe keeley keelia "
    "keely keenan keene keil keith kelcey kelci kelcie kelcy kelila kellen kelley kelli kellia kellie kellina "
    "kellsie kelly kellyann kelsey kelsi kelsy kelvin kelwin kemah ken kendal kendall kendra kendre kendrick kenn "
    "kenna kennedy kenneth kenny kent kenton kenyon keren keri keriann kerianne kermie kermit kerri kerrie kerrill "
    "kerrin kerry kerstin kesley keslie kessia kessiah ketti kettie ketty kevan kevin kevina kevyn ki kia kiah "
    "kial kiele kiell kieran kiersten kikelia kiley kim kimball kimberlee kimberley kimberli kimberly kimberlyn "
    "kimbra kimmi kimmie kimmo kimmy kin kincaid king kingsley kingsly kingston kinna kip kipp kippie kippy kira "
    "kirbee kirbie kirby kiri kirk kirsten kirsteni kirsti kirstie kirstin kirstyn kissee kissiah kissie kit kitti "
    "kittie kitty kizzee kizzie klara klarika klarrisa klaus klee knox kojo konrad konstance konstantin konstanze "
    "koo kora koral koralle kordula kore korella koren koressa kori korie korney korrie korry kory kostas kourtney "
    "kraig kris krishna krissie krissy krista kristal kristan kriste kristel kristen kristi kristian kristien "
    "kristin kristina kristine kristopher kristos kristy kristyn krysta krystal krystalle krystle krystyna kumail "
    "kurt kurtis kyla kyle kylen kylie kylila kylynn kym kynthia kyrstin la lacee lacey lacie lacy ladonna "
    "laetitia laila laina lainey laird lamar lamb lambert lamont lana lance lancelot lane lanette laney langston "
    "lani lanie lanita lanna lanni lanny lara laraine lari larina larine larisa larissa lark larry lars laryssa "
    "latashia latia latisha latrena latrina laura lauraine laural lauralee laurance laure lauree laureen laurel "
    "laurella lauren laurena laurence laurene laurens laurent lauretta laurette lauri laurianne laurice laurie "
    "lauryn lavena laverna laverne lavina lavinia lavinie lawerence lawrence lawson lawton lay layla layne layney "
    "layton lazar lazare lazaro lazarus lazlo lea leah leandra leann leanna leanne leanor leanora lebbie leda lee "
    "leeann leeanne leela leelah leena leesa leese lefty legra leia leiah leif leigh leigha leighton leila leilah "
    "leisha lela lelah leland lelia lem lemar lemmie lemmy lemuel len lena lenard lenee lenette lenka lenna lennie "
    "lenny lenora lenore leo leodora leoine leola leoline leon leona leonanie leonard leonardo leone leonelle "
    "leonerd leonhard leonid leonidas leonie leonora leonore leontine leontyne leopold leora leorah leroy les "
    "leshia lesley lesli leslie lesly lester lesya leta lethia leticia letisha letitia letta letti lettie letty "
    "lev levi levin levon levy lew lewis lex leyla lezlie lia liam lian liana liane lianna lianne lib libbey libbi "
    "libbie libby licha lida lidia lil lila lilah lilas lilia lilian liliane lilias lilith lilla lilli lillian "
    "lillis lilllie lilly lily lilyan lin lina lincoln lind linda lindi lindie lindsay lindsey lindsy lindy linea "
    "linell linet linette linn linnea linnell linnet linnie linoel linus linzy lion lionel lionello liora liorah "
    "lira lisa lisabeth lisandra lisbeth lise lisetta lisette lisha lishe lissa lissi lissie lissy lita liuka "
    "livia liz liza lizabeth lizbeth lizette lizzie lizzy llewellyn lloyd locke lockwood loella logan lois loise "
    "lola lolande loleta lolita lolly lon lona lonee loni lonna lonni lonnie lonny lora lorain loraine loralee "
    "loralie loralyn loree loreen lorelei lorelle loren lorena lorene lorenza lorenzo loretta lorettalorna lorette "
    "lori loria lorianna lorianne lorie lorilee lorilyn lorinda lorine lorita lorna lorne lorraine lorrayne lorri "
    "lorrie lorrin lorry lory lothar lotta lotte lotti lottie lotty lou louella louie louis louisa louise "
    "louisette love lovell lowell luana luanna lucas luce luci lucia lucian luciana luciano lucie lucien lucienne "
    "lucila lucilia lucille lucina lucinda lucine lucio lucita lucius lucky lucretia lucy ludvig ludwig luella "
    "luelle luigi luis luisa luise lukas luke lula lulita lulu luna lura lurette lurleen lurlene lurline lusa lust "
    "luther lyda lydia lydie lyle lyn lynda lynde lyndel lyndell lyndon lyndsay lyndsey lyndsie lyndy lynea "
    "lynelle lynett lynette lynn lynna lynne lynnea lynnell lynnelle lynnet lynnett lynnette lynsey lysandra lyssa "
    "mab mabel mabelle mable mac mace mack mackenzie mada madalena madalyn maddalena maddi maddie maddy madel "
    "madelaine madeleine madelena madelene madelin madelina madeline madella madelle madelon madelyn madge madison "
    "madlen madlin madona madonna mady mae maegan mag magda magdaia magdalen magdalena magdalene maggee maggi "
    "maggie maggy magna magnum magnus mahala mahalia mahesh mahmoud mahmud maia maible maiga mair maire mairead "
    "maisey maisie maison major mala malanie malcah malcolm malena malia malina malinda malinde malissa malissia "
    "malka malkah mallissa mallorie mallory malorie malory malva malvina malynda mame mamie manda mandi mandie "
    "mandy manfred manish manny manon manuel manya mara marabel marc marcel marcela marcelia marcella marcelle "
    "marcellina marcelline marcello marcellus marcelo marchall marchelle marci marcia marcie marcile marcille "
    "marcio marco marcos marcus marcy mareah maren marena maressa marga margalit margalo margaret margareta "
    "margarete margaretha margarethe margaretta margarette margarita margaux marge margeaux margery marget "
    "margette margi margie margit marglerite margo margot margret marguerite margurite margy mari maria mariam "
    "marian mariana mariann marianna marianne maribel maribelle maribeth marice maridel marie marie-ann "
    "marie-jeanne marieann mariejeanne mariel mariele marielle mariellen marietta mariette marigold marijo marika "
    "marilee marilin marillin marilu marilyn marin marina marinna mario marion mariquilla maris marisa mariska "
    "marissa marit marita maritsa marius mariya marj marja marje marji marjie marjorie marjory marjy mark marketa "
    "marko markos markus marla marlane marleah marlee marleen marlena marlene marley marlie marlin marline marlo "
    "marlon marlow marlowe marlyn marmaduke marna marne marney marni marnia marnie marquita marrilee marris "
    "marrissa marry marsh marsha marshal marshall marsiella mart marta martainn martelle marten martguerita martha "
    "marthe marthena marti martica martie martin martina martino martita marty martyn martynne marv marve marven "
    "marvin marwin mary marya maryangelyn maryann maryanna maryanne marybelle marybeth maryellen maryjane maryjo "
    "maryl marylee marylin marylinda marylou marylynne maryrose marys marysa masai masha mason matelda mateo "
    "mathew mathias mathilda mathilde matias matilda matilde matt matteo matthaeus mattheus matthew matthias "
    "matthieu matthiew matthus matti mattias mattie matty maud maude maudie maura maure maureen maureene maurene "
    "maurice mauricio maurie maurine maurise maurita maurits mauritz maury mavis mavra mawaan max maxfield maxi "
    "maxie maxim maximilian maximilien maxine maxwell maxy may maya maybelle mayda maye mayer maynard maynord "
    "mayor mead meade meagan meaghan meara mechelle meg megan megen meggan meggi meggie meggy meghan meghann "
    "mehetabel mei meier meir meira mel mela melamie melania melanie melantha melany melba melesa melessa melicent "
    "melina melinda melinde melisa melisande melisandra melisenda melisent melissa melisse melita melitta mella "
    "melli mellicent mellie mellisa mellisent mellissa melloney melly melodee melodie melody melonie melony melosa "
    "melva melvin melvyn menard mendel mendie mercedes merci mercie mercy meredeth meredith meredithe merell "
    "meridel meridith meriel merilee merill merilyn meris merissa merl merla merle merlin merlina merline merna "
    "merola merralee merrel merrick merridie merrie merrielle merril merrile merrilee merrili merrill merrily "
    "merry mersey merv mervin merwin meryl meta meyer mia mic micaela micah michael michaela michaelina michaeline "
    "michaella michail michal michale micheal micheil michel michele michelina micheline michell michelle mick "
    "mickey micki mickie micky midge mignon mignonne miguel miguela miguelita mika mikael mikako mike mikel mikey "
    "mikhail mildred mildrid milena miles milicent milissent milka milli millicent millie millisent milly milo "
    "milt milton milzie mimi min mina minda mindy minerva minetta minette minna minni minnie minny minta miquela "
    "mira mirabel mirabella mirabelle miran miranda mireielle mireille mirella mirelle miriam mirilla mirna mischa "
    "misha missie missy misti misty mitch mitchael mitchel mitchell mitra mitzi mmarianne mo modesta modestia "
    "modestine modesty moe mohamad mohamed mohammad mohammed mohan moina moira moise moises moishe moll mollee "
    "molli mollie molly mommy mona monah monica monika monique monroe montague monte montgomery monty moore mora "
    "mordecai moreen morena morgan morgana morganica morganne morgen moria morissa morlee morley morly morna "
    "morrie morris morry morse mort morten mortie mortimer morton morty mose moselle moses moshe moss moya moyna "
    "moyra mozelle muffin mufi mufinella mugsy muhammad muire munmro munroe murdoch murdock mureil murial muriel "
    "murielle murphy murray mustafa myke myles mylo myna myra myrah myranda myriam myrilla myrle myrlene myrna "
    "myron myrta myrtia myrtice myrtie myrtle nabil nada nadean nadeen nadia nadine nadiya nady nadya nahum nalani "
    "nan nana nananne nance nancee nancey nanci nancie nancy nanete nanette nani nanice nanine nannette nanni "
    "nannie nanny nanon naoma naomi napoleon nara nari nariko nat nata natala natale natalee natalia natalie "
    "natalina nataline natalya natasha natassia nate nathalia nathalie nathan nathanael nathanial nathaniel "
    "nathanil natka natty neal neala neale neall nealon nealson nealy ned neda nedda neddie neddy nedi neel neely "
    "neil neila neile neilla neille nela nelia nelie nell nelle nelli nellie nelly nels nelsen nelson nena nerissa "
    "nerita nero neron nert nerta nerte nerti nertie nerty nessa nessi nessie nessy nesta nester nestor netta "
    "netti nettie nettle netty nev nevil nevile neville nevin nevins nevsa newton neysa niall niamh niccolo nichol "
    "nicholas nichole nicholle nichols nick nickey nicki nickie nickolas nicky nico nicol nicola nicolas nicole "
    "nicolea nicolette nicoli nicolina nicoline nicolle nidia niels nigel nike niki nikita nikki nikkie nikolai "
    "nikoletta nikolia nikos nil niles nils nilson nina ninetta ninette ninnetta ninnette ninon nisa nish nissa "
    "nisse nissie nissy nita nitin niven nixie noach noah noam noami noble noe noel noelani noell noella noelle "
    "noellyn noelyn noemi nola nolan nolana noland nolie nollie nomi nona nonah noni nonie nonna nonnah nora norah "
    "norbert norean noreen norene norina norine norm norma norman normand normie norri norrie norris norry "
    "northrop northrup norton norwood nova novelia nunzio nydia nyssa obadiah obadias oberon obie octavia octavius "
    "odele odelia odelinda odell odella odelle odessa odetta odette odie odilia odille odin odysseus ofelia ofella "
    "ofilia ola olaf olag ole oleg olenka olga olia olimpia olin olive oliver olivette olivia olivie olivier oliy "
    "olle ollie olly olva olwen olympe olympia olympie omar ondrea oneida onida onlea oona opal opalina opaline "
    "ophelia ophelie oprah ora oral oralee oralia oralie oralla oralle oran orazio orbadiah orel orelee orelia "
    "orelie orella orelle oren oreste oriana orin orion orlando orly orren orrin orsa orsola orson ortensia orton "
    "orville osbert osborn osborne osbourn osbourne oscar osgood osmond osmund ossie oswald oswell otes otha "
    "othelia othella othello othilia othilie otho otis ottilie otto owen ozzie ozzy pablo pace pacifica paco "
    "paddie paddy padraig page paige pail palmer paloma pam pamela pamelina pamella pammi pammie pammy pandora "
    "pansie pansy paola paolina paolo park parke parker parnell parrnell parry parsifal partha parwane pascal "
    "pascale pasquale pat pate patel paten patience patin paton patric patrica patrice patricia patricio patrick "
    "patrik patrizia patsy patti pattie patty paul paula paula-grace paule pauletta paulette pauli paulie paulina "
    "pauline paulita paulo pauly pavel pavia pavla pearce pearl pearla pearle pearline pedro peg pegeen peggi "
    "peggie peggy peirce pembroke pen penelopa penelope penn penni pennie penny penrod pepe pepi pepillo pepita "
    "pepito perceval percival percy peri peria perl perla perle perri perrine perry persis pet peta pete peter "
    "petey petr petra petrina petronella petronia petronilla petronille petunia peyter peyton phaedra phaidra "
    "phebe phedra phelia phil philbert philip philipa philippa philippe philippine philis phillida phillie phillip "
    "phillipe phillipp phillis philly philomena phineas phip phoebe phylis phyllida phyllis phyllys phylys pia "
    "pier pierce pierette pierre pierrette pierson piet pieter pietra pietro piggy pincas pinchas pincus piotr pip "
    "piper pippa pippy plato polly pollyanna pooh poppy porter portia poul powell praneetf prasad prasun prent "
    "prentice prentiss prescott preston price prince pris prisca priscella priscilla prissie pru prudence prudi "
    "prudy prue prunella pryce puff purcell putnam pyotr queada queenie quent quentin querida quiggly quigly "
    "quigman quill quillan quincey quincy quinlan quinn quint quinta quintana quintilla quintin quintina quinton "
    "quintus rab rabbi rabi rachael rachel rachele rachelle rad radcliffe rae raf rafa rafael rafaela rafaelia "
    "rafaelita rafe ragnar ragnhild rahal rahel rahul raimund raina raine rainer raj rajeev rakel raleigh ralf "
    "ralina ralph ram ramesh ramon ramona ramonda ramsay ramsey rana rand randa randal randall randee randell "
    "randene randi randie randolf randolph randy ranee rani rania ranice ranique ranna ransell ransom raoul "
    "raphael raphaela raquel raquela rasia rasla raul raven ravi ravil rawley ray raychel raye raymond raymund "
    "raymundo rayna raynard raynell rayner raynor rayshell rea reagan reba rebbecca rebe rebeca rebecca rebecka "
    "rebeka rebekah rebekkah red redford redmond ree reeba reece reed reena rees reese reeta reeva reg regan regen "
    "reggi reggie reggis reggy regina reginald reginauld regine reid reiko reilly reina reine reinhard reinhold "
    "rem remington remus remy rena renado renae renaldo renard renata renate renato renaud renault rene renee "
    "renel renell renelle renie rennie reta retha reube reuben reuven revkah rex rey reyna reynard reynold "
    "reynolds reza rhea rheba rheta rhett rhetta rhiamon rhianna rhianon rhod rhoda rhodia rhodie rhody rhona "
    "rhonda rhys ria riane riannon rianon ric rica ricard ricardo ricca riccardo rice rich richard richardo richie "
    "richmond richy rici rick rickard rickey ricki rickie ricky rik riki rikki riley rina rinaldo ripley risa "
    "rissa rita ritch ritchie riva rivalee rivi rivkah rivy ro roana roanna roanne roarke rob robb robbert robbi "
    "robbie robbin robby robbyn robena robenia robert roberta roberto robin robina robinet robinett robinetta "
    "robinette robinia robinson roby robyn roch rochell rochella rochelle rochester rochette rock rockwell rocky "
    "rod roda rodd roddie roddy roderic roderich roderick roderigo rodge rodger rodi rodie rodina rodney rodolfo "
    "rodolph rodolphe rodrick rodrigo rodrique rog roger rogers roice roisin roland rolando rolf rolfe rolland "
    "rollin rollins rollo rolph romain roman romeo romesh romola romona romonda romy ron rona ronald ronalda ronda "
    "ronen roni ronica ronna ronni ronnica ronnie ronny roobbie roosevelt rora rori rorie rory ros rosa rosabel "
    "rosabella rosabelle rosaleen rosalia rosalie rosalind rosalinda rosalinde rosaline rosalyn rosalynd rosamond "
    "rosamund rosana rosanna rosanne rosario roscoe rose roseann roseanna roseanne roselia roselin roseline "
    "rosella roselle roselyn rosemaria rosemarie rosemary rosemonde rosene rosetta rosette roshelle rosie rosina "
    "rosita roslyn rosmunda ross rosy roth rourke row rowe rowena rowland roxana roxane roxanna roxanne roxi roxie "
    "roxine roxy roy royal royce roz rozalie rozalin rozamond rozanna rozanne roze rozele rozella rozelle rozina "
    "rube ruben rubetta rubi rubia rubie rubin rubina ruby rudd ruddie ruddy rudie rudiger rudolf rudolfo rudolph "
    "rudy rudyard ruella rufe rufus rupert ruperta ruperto russ russel russell rustie rustin rusty rutger ruth "
    "ruthann ruthanne ruthe rutherford ruthi ruthie ruthy rutledge rutter ryan ryann rycca saba sabina sabine "
    "sabra sabrina sacha sada sadella sadie sajeela sal salem salim sallee salli sallie sally sallyann sallyanne "
    "salman salmon salome salomo salomon salomone salvador salvatore salvidor sam samantha samara samaria sammie "
    "sammy sampson samson samuel samuela samuele samuella sancho sande sander sanders sanderson sandi sandie "
    "sandor sandra sandro sandy sandye sanford sanson sansone sapphira sapphire sara sara-ann saraann sarah "
    "sarajane saree sarena sarene sarette sarge sargent sari sarina sarine sarita sascha sasha sashenka saudra "
    "saul sauncho saunder saunders saunderson saundra savina saw sawyer sawyere sax saxe saxon say sayer sayers "
    "sayre sayres scarface scarlet scarlett schroeder schuyler scot scott scotti scottie scotty seamus sean seana "
    "seann sebastian sebastiano sebastien secunda see seka sela selby selena selene selestina selia selie selig "
    "selina selinda seline sella selle selma sena sephira serena serene serge sergeant sergei sergent sergio seth "
    "seymour shadow shaina shaine shalna shalne shalom shamit shamus shana shanan shanda shandee shandie shandra "
    "shandy shane shani shanie shanna shannah shannan shannen shannon shanon shanta shantee shappi shara sharai "
    "shari sharia sharie sharity sharl sharla sharleen sharlene sharline sharna sharon sharona sharra sharron "
    "sharyl shaughn shaun shauna shaw shawn shawna shawnee shay shayla shaylah shaylyn shaylynn shayna shayne "
    "shazia shea sheba sheela sheelagh sheelah sheena sheeree sheff sheffie sheffield sheffy sheila sheila-kathryn "
    "sheilah sheilakathryn shel shela shelagh shelba shelbi shelby shelden sheldon shelia shell shelley shelli "
    "shellie shelly shelton shem shena shep shepard shepherd sheppard shepperd sher sheree sheri sheridan sherie "
    "sheril sherill sherilyn sherline sherlock sherlocke sherman sherri sherrie sherry sherwin sherwood sherwynd "
    "sherye sheryl shilpa shimon shina shir shira shirah shirl shirlee shirleen shirlene shirley shirline shlomo "
    "sholom shorty shoshana shoshanna shoshie shumeet shurlock shurlocke shurwood si sian siana sianna sib sibbie "
    "sibby sibeal sibel sibella sibelle sibilla sibley sibyl sibylla sibylle sid siddhartha sidnee sidney sidoney "
    "sidonia sidonnie siegfried siffre sig sigfrid sigfried sigmund sigrid sikisa silas sile sileas silva silvain "
    "silvan silvana silvano silvanus silvester silvia silvie silvio sim simeon simmonds simon simona simone "
    "simonette simonne sinclair sinclare sindee sindhu sinead siobhan sioux siouxie sisely sisile sissie sissy "
    "sivert siward skell skelly skip skipp skipper skippie skippy skipton sky skye skylar skyler slade slim sloan "
    "sloane sly smith smitty socrates sofia sofie sol solange sollie solly solomon somerset son sondra sonia sonja "
    "sonni sonnie sonnnie sonny sonya sooz sophey sophi sophia sophie sophronia sorcha sosanna sparky spence "
    "spencer spense spenser spike spiro spiros spud srinivas stace stacee stacey staci stacia stacie stacy stafani "
    "staffard stafford staford stan standford stanfield stanford stanislaw stanleigh stanley stanly stanton "
    "stanwood star starla starlene starlin starr stavros stearn stearne stefa stefan stefania stefanie stefano "
    "steff steffane steffen steffi steffie stella stepha stephan stephana stephani stephanie stephannie stephanus "
    "stephen stephenie stephi stephie stephine sterling stern sterne stesha stevana steve steven stevena stevie "
    "stevy stew steward stewart stig stillman stillmann sting stinky stirling stoddard storey storm stormi stormie "
    "stormy stu stuart sturgis sue sue-elle suellen sukey sukh suki sula sullivan sully sumner sunil sunny "
    "sunshine susan susana susanetta susann susanna susannah susanne susette susi susie sussi susy sutherland "
    "sutton suzan suzann suzanna suzanne suzetta suzette suzi suzie suzy suzzy sven swen sybil sybila sybilla "
    "sybille sybyl syd sydel sydelle sydney sylvan sylvester sylvia sylvie tab tabatha tabb tabbatha tabbi tabbie "
    "tabbitha tabby taber tabina tabitha tabor tad tadd taddeo taddeus tadeas tadiwa taffy tailor tait taite "
    "talbert talbot talia tallia tallie tally talya talyah tam tamar tamara tamarah tamarra tamas tamera tami "
    "tamiko tamma tammara tammi tammie tammy tamra tan tana tandi tandie tandy tani tania tann tanner tanney "
    "tannie tanny tansy tanya tara tarah tarik tarra tarrah tarrance tarrant taryn tarzan tasha tasia tate tatiana "
    "tatiania tatum tawnya tawsha taylor teador teane ted tedd tedda teddi teddie teddy tedi tedie tedman tedmund "
    "tedra tedrick teena tella temp temple templeton teodoor teodor teodora teodorico teodoro tera terence "
    "terencio teresa teresaanne terese teresina teresita teressa teri teriann terina terra terrance terrel terrell "
    "terrence terri terri-jo terrianne terrie terrill terry terrye tersina teryl terza tess tessa tessi tessie "
    "tessy tez thacher thad thaddeus thaddius thaddus thadeus thain thaine thalia thane tharen thatch thatcher "
    "thaxter thayne thea theada theadora thebault theda thedric thedrick thekla thelma theo theobald theodor "
    "theodora theodore theodoric theodosia theophyllus theresa theresa-marie therese theresina theresita theressa "
    "therine thia thibaud thibaut thom thomas thomasa thomasin thomasina thomasine thor thorn thorndike thornie "
    "thornton thorny thorpe thorstein thorsten thorvald thurstan thurston tia tiana tibold tiebold tiebout tiena "
    "tierney tiertza tiff tiffani tiffanie tiffany tiffi tiffie tiffy tilda tildi tildie tildy tiler tillie tilly "
    "tim timi timmi timmie timmy timothea timothee timotheus timothy tina tine tiphani tiphanie tiphany tirrell "
    "tish tisha tito titos titus tobe tobey tobi tobiah tobias tobie tobin tobit toby tobye tod todd toddie toddy "
    "toinette tom toma tomas tomasina tomasine tome tomi tomiko tomkin tomlin tommi tommie tommy toni tonia tonie "
    "tonnie tony tonya tootsie tore torey tori torie torin torr torrance torre torrence torrey torrie torrin torry "
    "tory tova tove town towney townie townsend towny trace tracee tracey traci tracie tracy traver travers travis "
    "tray tre tremain tremaine tremayne trenna trent trenton tresa trescha tressa trev trevar trever trevor trey "
    "tricia trina trip trish trisha trista tristan trix trixi trixie trixy troy truda trude trudey trudi trudie "
    "trudy trula truman tuck tucker tuckie tucky tudor tuesday tull tulley tully turner twila twyla ty tybalt tybi "
    "tybie tye tyler tymon tymothy tynan tyne tyrone tyrus tyson udale udall udell ugo ula ulberto uli ulick "
    "ulises ulla ulric ulrica ulrich ulrick ulrika ulrike ulysses umberto umeko una upton urbain urban urbano "
    "urbanus uri uriah uriel ursa ursala ursola urson ursula ursulina ursuline urzila uta vachel vaclav vail val "
    "valaree valaria valdemar vale valeda valencia valene valenka valentia valentin valentina valentine valera "
    "valeria valerie valery valerye valida valina valli vallie vally valma valry van vance vanda vanessa vania "
    "vanna vanni vannie vanny vanya vasili vasilis vasily vassili vassily vaughan vaughn veda velma velvet vena "
    "venita venkat ventura venus vera veradis vere verena verene verge vergil veriee verile verina verine verla "
    "vern verna verne vernen verney vernice vernon vernor veronica veronika veronike veronique vi vibhu vic vick "
    "vicki vickie vicky victor victoria vida vijay viki vikki vikkie vikky vilhelm vilhelmina vilma vin vina vince "
    "vincent vincents vinita vinni vinnie vinny vinod viola violante viole violet violetta violette virge virgie "
    "virgil virgilio virgina virginia virginie vita vite vitia vito vitoria vittoria viv viva vivi vivia vivian "
    "viviana vivianna vivianne vivie vivien viviene vivienne viviyan vivyan vivyanne vlad vladamir vladimir "
    "voltaire von vonni vonnie vonny wade wadsworth wain waine wainwright wait waite waiter wake wakefield wald "
    "waldemar walden waldo waldon waleed walker wallace wallache wallas wallie wallis wally walsh walt walter "
    "walther walton waly wanda wandie wandis waneta wang ward warde warden ware waring warner warren wash "
    "washington wat waverley waverly way waylan wayland waylen waylin waylon wayne web webb weber webster weidar "
    "weider welbie welby welch wells welsh wenda wendall wendel wendeline wendell wendi wendie wendy wenona "
    "wenonah werner wes wesley weslie west westbrook westbrooke westleigh westley weston weylin wheeler whit "
    "whitaker whitby whitman whitney whittaker wiatt wilber wilbert wilbur wilburn wilburt wilden wildon wileen "
    "wilek wiley wilfred wilfrid wilhelm wilhelmina wilhelmine wilie will willa willabella willamina willard "
    "willdon willem willetta willette willey willi william willie willis willmott willow willy willyt wilma wilmar "
    "wilmer wilmette wilona wilone wilow wilson wilt wilton win windham windy winfield winford winfred wini "
    "winifield winifred winn winna winnah winne winni winnie winnifred winny winona winonah winslow winston "
    "winthrop winton wit witold wittie witty wojciech wolf wolfgang wolfie wolfram wolfy woochang wood woodie "
    "woodman woodrow woody worden worth worthington worthy wren wrennie wright wyatan wyatt wye wylie wylma wyn "
    "wyndham wynn wynne wynnie wynny wynton xavier xaviera xena xenia xenos xerxes xever ximenes ximenez xylia "
    "xylina xymenes yaakov yacov yale yalonda yanaton yance yancey yancy yank yankee yard yardley yehudi yehudit "
    "yelena yetta yettie yetty yevette yigal yoko yolanda yolande yolane yolanthe yonina yoshi yoshiko yovonnda "
    "yule yuri yuriko yves yvette yvonne zabrina zach zacharia zachariah zacharias zacharie zachary zacherie "
    "zachery zack zackariah zahara zak zalman zandra zane zaneta zara zarah zared zaria zarla zary zea zeb "
    "zebadiah zebedee zebulen zebulon zechariah zed zedekiah zeke zelda zelig zelma zena zenia zerk zeus zia "
    "zilvia zippy zita zitella zoe zola zollie zolly zonda zondra zonnya zora zorah zorana zorina zorine zorro "
    "zsa zsa zsazsa zulema zuzana "
).split())


# ---------------------------------------------------------------------------
# Event classification (Tasks 1 and 6)
# ---------------------------------------------------------------------------
# Internal categories. They never change the shows.json `type` field; they are
# used for relevance decisions and exported in the optional diagnostics file.
CAT_CONFIRMED_OPEN_MIC = "confirmed_open_mic"
CAT_PROBABLE_OPEN_MIC = "probable_open_mic"
CAT_NEW_ACT = "new_act_showcase"
CAT_OTHER_COMEDY = "other_comedy"
CAT_UNCERTAIN = "uncertain"
CAT_NON_COMEDY = "non_comedy"
ACCEPTED_CATEGORIES = {CAT_CONFIRMED_OPEN_MIC, CAT_PROBABLE_OPEN_MIC, CAT_NEW_ACT, CAT_OTHER_COMEDY}
TOUR_TYPE_LABELS = {"tour", "solo_show"}   # internal labels that become shows.json type "tour"
CAT_POETRY_OPEN_MIC = "poetry_open_mic"
INCLUDE_POETRY_OPEN_MICS = True             # poetry / spoken-word open mics are listed and tagged open_mic
ACCEPTED_CATEGORIES = ACCEPTED_CATEGORIES | {CAT_POETRY_OPEN_MIC}
OPEN_MIC_CATEGORIES = {CAT_CONFIRMED_OPEN_MIC, CAT_POETRY_OPEN_MIC}   # -> shows.json open_mic: true

# New performers/new talent belong in the Open Mic filter. Work-in-progress,
# previews and scratch/new-material shows do not, even though the classifier
# uses CAT_NEW_ACT internally for both groups.
NEW_PERFORMER_RE = re.compile(
    r"\b(?:new[\s-]?acts?|new\s+comedians?|new\s+comics?|new\s+(?:comedy\s+)?talent|"
    r"emerging\s+(?:talent|comedians?|comics?|acts?)|newcomers?|"
    r"(?:new|emerging|student|graduate|graduation|beginners?)\s+(?:\w+\s+)?showcase)\b", re.I
)
NON_OPEN_MIC_NEW_MATERIAL_RE = re.compile(
    r"\b(?:new\s+material|scratch(?:\s+night)?|try[\s-]?outs?|work[\s-]?in[\s-]?progress|"
    r"w\.?i\.?p\.?|previews?|development\s+(?:night|show))\b", re.I
)

_rx = lambda p: re.compile(p, re.I)

STRONG_COMEDY_RE = _rx(
    r"\b(?:comedy|comedies|comedian|comedians|comedienne|comediennes|stand[\s-]?ups?|standups?|"
    r"improv|improvised\s+comedy|improvisation|sketch\s+(?:show|comedy|troupe|group))\b"
)
MEDIUM_COMEDY_RE = _rx(
    r"\b(?:comic|comics|jokes?|laughs?|laughter|laughing|funny|funniest|hilarious|headliners?|"
    r"compere|compered|line[\s-]?up|roast|panel\s+show|comedic|chuckles?|giggles?)\b"
)

OPEN_MIC_GENERIC_RE = _rx(r"\bopen[\s-]?(?:mic|mike|mics|mikes|microphone)s?\b|\bmic\s+nights?\b|\bopen[\s-]floor\b")
# Open-format wording that, together with comedy wording AND sign-up/participation
# wording, confirms an open mic even when the words "open mic" are absent.
OPEN_FORMAT_RE = _rx(
    r"\bopen\s+spots?\b|\bfirst[\s-]?timers?\b|\b(?:three|five|ten|3|5|10)[\s-]?(?:minute|min)\s+(?:spots?|slots?)\b"
    r"|\bsign[\s-]?up\s+(?:night|comedy|list)\b|\bbucket\s+(?:spots?|draw)\b|\bgong\s+show\b"
)
OPEN_MIC_STRONG_RE = _rx(
    r"\b(?:comedy|stand[\s-]?up|standup)\s+open[\s-]?(?:mic|mike)s?\b"
    r"|\bopen[\s-]?(?:mic|mike)s?\s+(?:comedy|stand[\s-]?up|standup)\b"
    r"|\bopen\s+stand[\s-]?up\s+spots?\b"
    r"|\bamateur\s+(?:stand[\s-]?up|comedy|comedians?|comics?)\b"
    r"|\bopen\s+sign[\s-]?ups?\s+(?:comedy|stand[\s-]?up)\b|\bcomedy\s+sign[\s-]?ups?\b"
    r"|\bbring\s+your\s+own\s+(?:jokes|five|5|material|five\s+minutes)\b"
    r"|\bbucket\s+(?:spots?|draw|night)\b"
    r"|\bfirst[\s-]?time(?:rs?)?\s+(?:comedians?|comics|stand[\s-]?ups?)\s+(?:welcome|night|spots?)\b"
)
PARTICIPATION_RE = _rx(
    r"\bsign[\s-]?ups?\b|\bsign\s+up\b|\bspots?\s+(?:available|left|open|are\s+available)\b"
    r"|\bbook\s+(?:a|your)\s+(?:spot|slot)\b|\bget\s+a\s+(?:spot|slot)\b|\bwant\s+to\s+perform\b"
    r"|\bfancy\s+(?:a\s+go|performing|trying)\b|\b(?:performers|acts|comedians|comics)\s+welcome\b"
    r"|\bopen\s+to\s+(?:all|any|new)\s+(?:comedians|comics|acts|performers)\b|\bnames?\s+in\s+the\s+(?:bucket|hat)\b"
    r"|\b(?:list|sign[\s-]?up\s+sheet)\s+on\s+the\s+night\b|\b(?:three|five|ten|3|5|10)[\s-]?(?:minute|min)\s+(?:spots?|slots?)\b"
    r"|\bemail\s+(?:us\s+)?(?:for|to\s+(?:book|get))\s+(?:a\s+)?(?:spot|slot)s?\b|\bfirst[\s-]?timers?\s+welcome\b"
    r"|\bbucket\s+(?:spots?|draw)\b|\bbring\s+your\s+own\b"
)
NEW_ACT_RE = _rx(
    r"\bnew\s+material\b|\bnew[\s-]acts?\b|\bnew\s+comedians?\b|\bnew\s+comics?\b|\bnew\s+(?:comedy\s+)?talent\b"
    r"|\bemerging\s+(?:talent|comedians?|comics?|acts?)\b|\bnewcomers?\b|\brising\s+(?:talent|stars?)\b"
    r"|\b(?:comedy\s+)?scratch(?:\s+night)?\b|\btry[\s-]?outs?\b|\bwork[\s-]?in[\s-]?progress\b|\bw\.?i\.?p\.?\b"
    r"|\b(?:fringe|edinburgh)\s+previews?\b|\bpreviews?\b|\bgong\s+show\b|\bcomedy\s+gong\b"
    r"|\b(?:new|emerging|student|course|graduate|graduation|beginners?)\s+(?:\w+\s+)?showcase\b"
    r"|\bdevelopment\s+(?:night|show)\b|\b(?:five|5)[\s-]?minute\s+(?:spots?|slots?)\b|\bfirst\s+gig\b"
)
TOUR_EXPLICIT_RE = _rx(
    r"\b(?:uk|national|world|ireland|scotland|arena|stadium)\s+tour\b|\bon\s+tour\b|\btour\s+20\d\d\b"
    r"|\b20\d\d\s+tour\b|\btour\s+(?:dates?|show)\b|\btouring\b|\bnew\s+tour\b|\btour\b"
)
NOT_TOUR_RE = _rx(
    r"\b(?:guided|ghost|walking|brewery|distillery|pub|backstage|heritage|castle|museum|bus|city|food|wine|gin|"
    r"whisky|studio|venue|virtual|mystery|history)\s+tours?\b|\btour\s+(?:guide|of\s+the)\b|\btour\s+de\b"
)
WIP_PREVIEW_RE = _rx(r"\bwork[\s-]?in[\s-]?progress\b|\bw\.?i\.?p\.?\b|\bpreviews?\b|\bfringe\s+preview\b|\bedinburgh\s+preview\b")
SOLO_SIGNAL_RE = _rx(
    r"\bstand[\s-]?up\s+special\b|\bsolo\s+show\b|\bone[\s-](?:wo)?man\s+show\b|\ban\s+evening\s+with\b"
    r"|\bhour\s+of\s+(?:stand[\s-]?up|comedy)\b|\bbrand\s+new\s+(?:stand[\s-]?up\s+)?show\b|\bnew\s+(?:stand[\s-]?up\s+)?show\b"
)
# "Firstname Surname: Show" / "FIRSTNAME SURNAME - Show" / "Firstname Surname – Show"
NAMED_ACT_SHOW_RE = re.compile(
    r"^\s*([A-Z][A-Za-z'’.\-]+(?:\s+(?:[A-Z][A-Za-z'’.\-]+|Mc[A-Z][a-z]+|O'[A-Z][a-z]+|de|van|von)){1,3})\s*(?::|–|—|\s-\s)\s*(.{3,})$"
)

NON_COMEDY_EVIDENCE = {
    "music": _rx(
        r"\blive\s+music\b|\bbands?\b|\bvocalists?\b|\bvocals\b|\bsingers?\b|\bsinger[\s-]songwriters?\b|\bsongwriters?\b"
        r"|\bsongs\b|\bgreatest\s+hits\b|\balbum\b|\bacoustic\b|\bguitar(?:ist)?s?\b|\bchoirs?\b|\borchestras?\b"
        r"|\bconcerts?\b|\bdj\b|\bdjs\b|\bdj\s+set\b|\bdisco\b|\bmotown\b|\bsoul\s+(?:night|music)\b|\bjazz\b|\bblues\b"
        r"|\bfolk\s+(?:music|night|club|session)\b|\bindie\b|\brock\s+(?:night|band|music)\b|\bmusicians?\b"
        r"|\bjam\s+(?:session|night)s?\b|\bkaraoke\b|\bsing[\s-]?along\b|\bopera\b|\bballet\b|\bdancers\b"
        r"|\bmusical\s+(?:evening|night|theatre)\b|\bthe\s+music\s+of\b|\bmusic\s+fans\b|\bboy[\s-]?band\b|\bpop\s+(?:hits|exports?|star)\b"
        r"|\bclub\s+night\b|\brave\b|\bafter[\s-]?party\b|\balldayer\b|\ball\s+dayer\b|\bgarage\s+night\b|\bgoth\b"
    ),
    "poetry": _rx(r"\bpoetry\b|\bpoets?\b|\bpoems?\b|\bspoken[\s-]word\b|\bpoetry\s+slam\b"),
    "theatre": _rx(
        r"\bpantomime\b|\bpanto\b|\ba\s+play\b|\bthe\s+play\b|\bstage\s+play\b|\bimmersive\s+theatre\b"
        r"|\bmusical\b(?!\s+comed)|\bbroadway\b|\bwest\s+end\s+musical\b"
    ),
    "variety": _rx(r"\bcabaret\b|\bburlesque\b|\bcircus\b|\bmagic\s+show\b|\bmagicians?\b|\bhypnotists?\b|\bdrag\s+(?:show|queen|brunch)\b"),
    "other": _rx(
        r"\bbingo\b|\bquiz(?:zes)?\b|\bfilm\s+(?:night|screening|club)s?\b|\bscreenings?\b|\bexhibitions?\b|\bcraft(?:s|\s+sessions?)?\b"
        r"|\bworkshops?\b|\blessons?\b|\byoga\b|\bpilates\b|\bzumba\b|\btai\s+chi\b"
        r"|\bfitness\b|\bbootcamp\b|\bfootball\b|\bworld\s+cup\b|\bwatch\s+party\b|\bdarts\b|\brace\s+night\b"
        r"|\bhousing\s+advice\b|\bdrop[\s-]in\b|\bwarm\s+welcome\b|\bcommunity\s+caf[eé]\b|\bauditions?\b"
        r"|\bgift\s+vouchers?\b|\bvouchers?\b|\bgift\s+cards?\b|\bresidents\b|\bcandlelight\b|\blindy\s+hop\b|\bswing\s+dance\b"
    ),
}
# Hard exclusions apply even when the title says comedy (e.g. "Comedy Writing Workshop", "Comedy Film Screening").
HARD_EXCLUDE_RE = _rx(
    r"\bkaraoke\b|\bfilm\s+(?:night|screening|club)s?\b|\bscreenings?\b|\bwatch\s+party\b|\bfootball\b|\bworld\s+cup\b"
    r"|\byoga\b|\bpilates\b|\bzumba\b|\btai\s+chi\b|\bfitness\b|\bbootcamp\b|\bworkshops?\b"
    r"|\b(?:comedy|stand[\s-]?up|improv|writing|beginners?|\d+[\s-]?week|evening|online)\s+courses?\b"
    r"|\b(?:comedy|stand[\s-]?up|improv|writing|dance|art|craft|fitness|cookery|drawing|painting)\s+class(?:es)?\b"
    r"|\bmasterclass(?:es)?\b|\blessons?\b|\bhousing\s+advice\b|\bwarm\s+welcome\b|\bcommunity\s+caf[eé]\b"
    r"|\bgift\s+vouchers?\b|\bvouchers?\b|\bgift\s+cards?\b|\bauditions?\b|\bexhibitions?\b"
)
HARD_EXCLUDE_EXCEPTION_RE = _rx(r"\bshowcase\b|\bgraduation\s+show\b|\bend\s+of\s+(?:course|term)\s+show\b")
MUSIC_OR_POETRY_KEYS = ("music", "poetry")


def _evidence(text):
    """Return {kind: [matched words]} for non-comedy evidence in text."""
    out = {}
    for kind, rx in NON_COMEDY_EVIDENCE.items():
        hits = sorted({m.group(0).lower() for m in rx.finditer(text)})
        if hits:
            out[kind] = hits
    return out


DESCRIPTION_SEEN = {}


def _description_key(desc):
    return re.sub(r"[^a-z0-9]+", " ", clean_text(desc).lower())[:240].strip()


def note_description(desc):
    key = _description_key(desc)
    if len(key) >= 60:
        DESCRIPTION_SEEN[key] = DESCRIPTION_SEEN.get(key, 0) + 1


def is_boilerplate_description(desc):
    """Organiser/brand blurbs repeated on 3+ events say nothing about one event."""
    key = _description_key(desc)
    return len(key) >= 60 and DESCRIPTION_SEEN.get(key, 0) >= 3


def _strip_place_names(text, event):
    names = set()
    venue = clean_text(event.get("venue", ""))
    for n in [venue, clean_text(event.get("_venue_title", ""))] + venue.split(" - "):
        n = clean_text(n)
        if len(n) >= 4:
            names.add(n)
    for n in sorted(names, key=len, reverse=True):
        text = re.sub(re.escape(n), " ", text, flags=re.I)
    return clean_text(text)


def event_specific_description(event):
    """Description text that plausibly belongs to this event only.

    Generic block extraction can capture whole-page text; only the first part
    of an over-long description is treated as event-specific. Repeated
    organiser blurbs and the venue's own name ("Comedy Lounge") are not
    evidence about the event itself.
    """
    desc = clean_text(event.get("description", ""))
    if is_boilerplate_description(desc):
        return ""
    title = clean_text(event.get("title", ""))
    if desc.lower().startswith(title.lower()):
        desc = desc[len(title):]
    desc = desc if len(desc) <= 1500 else desc[:600]
    return _strip_place_names(desc, event)


COMEDY_NAME_RE = _rx(r"\bcomedy\b|\bcomedians?\b|\bstand[\s-]?up\b|\bstandup\b|\bimprov\b|\blaughter\b|\blaughs\b|\bjokes\b")


def comedy_named_venue(event):
    """The venue's (or organiser's) OWN NAME says comedy: 'The Jesters Comedy Club',
    'Comedy Lounge - Stage Door', 'Breakneck Comedy'. The organiser name only counts
    for listings taken from that organiser's own website, so a Skiddle search made
    for a comedy club cannot vouch for some other pub's night. Google categories
    from the venue list are deliberately NOT used here."""
    if COMEDY_NAME_RE.search(clean_text(event.get("venue", ""))):
        return True
    organiser = clean_text(event.get("_venue_title", ""))
    if organiser and COMEDY_NAME_RE.search(organiser):
        site = clean_text(event.get("_venue_website", ""))
        src = clean_text(event.get("source", "")) or clean_text(event.get("ticket_url", ""))
        if site and src and _same_site(src, site):
            return True
    return False


def venue_comedy_context(event):
    """'protected', 'trusted', 'comedy_venue' or 'mixed' for the event's venue/source."""
    if is_protected_trusted_comedy_event(event):
        return "protected"
    if is_trusted_comedy_context(event):
        return "trusted"
    if comedy_named_venue(event):
        return "comedy_venue"
    confidence = clean_text(event.get("_venue_confidence", "")).lower()
    category = clean_text(event.get("_venue_category", "")).lower()
    venue_title = clean_text(event.get("_venue_title", "")).lower()
    if ("high" in confidence or "explicit comedy" in confidence) and ("comedy" in category or "comedy" in venue_title):
        return "comedy_venue"
    return "mixed"


def classify_event(event):
    """Classify an event using title, event-specific description, venue context,
    structured-data origin and participation wording. Returns a dict that is
    also cached on the event as event['_classification'].
    """
    title = clean_text(event.get("title", ""))
    desc = event_specific_description(event)
    both = f"{title}. {desc}"   # sentence break: no phrase may span title and description
    ctx = venue_comedy_context(event)
    extraction = clean_text(event.get("_extraction", ""))
    structured = extraction in {"card", "detail", "jsonld", "pagejson"}

    title_strong = bool(STRONG_COMEDY_RE.search(title))
    desc_strong = len(STRONG_COMEDY_RE.findall(desc))
    desc_medium = len(MEDIUM_COMEDY_RE.findall(desc))
    title_medium = bool(MEDIUM_COMEDY_RE.search(title))
    title_ev = _evidence(title)
    desc_ev = _evidence(desc)
    om_generic = bool(OPEN_MIC_GENERIC_RE.search(both))
    om_strong = bool(OPEN_MIC_STRONG_RE.search(both))
    open_format = bool(OPEN_FORMAT_RE.search(both))
    participation = bool(PARTICIPATION_RE.search(both))
    new_act = bool(NEW_ACT_RE.search(both))
    comedy_words = title_strong or desc_strong > 0
    comedy_ctx = ctx in {"protected", "trusted", "comedy_venue"}
    signals = []

    def result(category, reason, hard=False):
        tour = tour_signal(event, title, desc, category, comedy_words or comedy_ctx)
        out = {
            "category": category,
            "reason": reason,
            "hard": hard,
            "context": ctx,
            "tour": tour,
            "signals": ", ".join(signals)[:300],
        }
        event["_classification"] = out
        event["_tour"] = tour if category in ACCEPTED_CATEGORIES else ""
        return out

    if title_strong:
        signals.append("comedy word in title")
    if desc_strong:
        signals.append(f"{desc_strong} comedy word(s) in description")
    if om_generic:
        signals.append("open mic wording")
    if om_strong:
        signals.append("explicit comedy open-mic wording")
    if participation:
        signals.append("performer sign-up/participation wording")
    if new_act:
        signals.append("new-act/new-material/WIP wording")
    signals.append(f"venue context: {ctx}")

    # 1. Hard exclusions in the title (workshops, screenings, karaoke, vouchers...)
    hard = HARD_EXCLUDE_RE.search(title)
    if hard and not HARD_EXCLUDE_EXCEPTION_RE.search(title):
        signals.append(f"hard exclusion: {hard.group(0)}")
        return result(CAT_NON_COMEDY, f"not a comedy performance ({hard.group(0).lower()})", hard=True)

    music_poetry = {k: v for k, v in {**desc_ev, **title_ev}.items() if k in MUSIC_OR_POETRY_KEYS}

    # 2. Open mics
    has_music = "music" in title_ev or "music" in desc_ev
    has_poetry = "poetry" in title_ev or "poetry" in desc_ev
    poetry_ok = INCLUDE_POETRY_OPEN_MICS and has_poetry
    if om_generic or om_strong:
        if om_strong:
            if has_music and not title_strong and not poetry_ok:
                return result(CAT_PROBABLE_OPEN_MIC, "comedy open mic shared with music")
            return result(CAT_CONFIRMED_OPEN_MIC, "explicit comedy open-mic wording")
        if comedy_words:
            if poetry_ok:
                return result(CAT_CONFIRMED_OPEN_MIC, "open mic for comedians and poets")
            if has_music or has_poetry:
                return result(CAT_PROBABLE_OPEN_MIC, "mixed open mic that includes comedians")
            if participation or OPEN_MIC_GENERIC_RE.search(title):
                return result(CAT_CONFIRMED_OPEN_MIC, "open mic with comedy wording")
            return result(CAT_PROBABLE_OPEN_MIC, "open mic mentioned alongside comedy")
        if poetry_ok:
            return result(CAT_POETRY_OPEN_MIC, "poetry / spoken-word open mic")
        if music_poetry:
            signals.append("music/poetry evidence: " + ", ".join(sorted({w for v in music_poetry.values() for w in v}))[:120])
            return result(CAT_NON_COMEDY, "music open mic with no comedy or poetry element" if INCLUDE_POETRY_OPEN_MICS
                          else "music/poetry open mic with no comedy element")
        if ctx in {"protected", "trusted"}:
            # a curated comedy-only organiser supplies the comedy evidence
            return result(CAT_CONFIRMED_OPEN_MIC, "open mic run by a trusted comedy organiser/venue")
        if comedy_named_venue(event):
            return result(CAT_CONFIRMED_OPEN_MIC, "open mic at a venue/organiser whose own name says comedy")
        # Google-derived "comedy club" categories are too noisy (music pubs host
        # "Roots" open mics): without stand-up wording this goes to review.
        return result(CAT_UNCERTAIN, "open mic with no comedy evidence (needs review)")

    # 2b. Open-format nights without the words "open mic" (open spots, first-timers, 5-minute spots, sign-up nights)
    if open_format and comedy_words and participation and not music_poetry:
        return result(CAT_CONFIRMED_OPEN_MIC, "comedy night with open spots / sign-up wording")

    # 3. Title is clearly something else and there is no strong comedy in the title
    if title_ev and not title_strong:
        non_music_title = not any(k in title_ev for k in MUSIC_OR_POETRY_KEYS)
        named_act_show = bool(NAMED_ACT_SHOW_RE.match(title))
        if non_music_title and (desc_strong >= 2 or (named_act_show and (desc_strong >= 1 or comedy_ctx))):
            signals.append("title non-comedy word outweighed (named act / comedy description)")
        else:
            words = ", ".join(sorted({w for v in title_ev.values() for w in v}))
            return result(CAT_NON_COMEDY, f"non-comedy title ({words})")

    # 4. Description says it is music/poetry/theatre and nothing says comedy
    if desc_ev and not comedy_words:
        if not (comedy_ctx and ctx in {"protected", "trusted"}):
            words = ", ".join(sorted({w for v in desc_ev.values() for w in v}))[:120]
            return result(CAT_NON_COMEDY, f"non-comedy description ({words})")

    # 5. New material / new acts / WIP / previews
    if new_act and (comedy_words or comedy_ctx or title_medium):
        if participation and (comedy_words or comedy_ctx):
            return result(CAT_PROBABLE_OPEN_MIC, "new-act night with open sign-up wording")
        return result(CAT_NEW_ACT, "new-material / new-act / WIP showcase")

    # 6. Other comedy
    if comedy_words:
        return result(CAT_OTHER_COMEDY, "comedy wording in title/description")
    if comedy_ctx and ctx in {"protected", "trusted"}:
        return result(CAT_OTHER_COMEDY, "trusted comedy organiser/venue")
    if comedy_ctx and structured and not desc_ev and looks_like_act_or_show_title(title):
        return result(CAT_OTHER_COMEDY, "act/show name at a dedicated comedy venue")
    if (desc_medium >= 2 or (title_medium and desc_medium >= 1)) and not desc_ev:
        return result(CAT_OTHER_COMEDY, "several comedy cues (laughs/jokes/funny)")
    if title_medium or desc_medium:
        return result(CAT_UNCERTAIN, "weak comedy cues only (needs review)")
    return result(CAT_NON_COMEDY, "no comedy evidence")


def looks_like_act_or_show_title(title):
    """A named act / show title rather than a page label ('Contact', 'Gift Vouchers', 'Menu')."""
    t = clean_text(title)
    if len(t) < 4 or len(t) > 140:
        return False
    if looks_like_navigation_or_non_event_title(t):
        return False
    if is_generic_bad_title(t):
        return False
    words = re.findall(r"[A-Za-z][A-Za-z'’.\-]*", t)
    if not words:
        return False
    if len(words) == 1 and len(words[0]) < 5:
        return False
    return True


MIXED_BILL_RE = _rx(
    r"\bwith\b|\bline[\s-]?up\b|\bmixed\s+bill\b|\bshowcase\b|\bcomedy\s+club\b|\bclub\b|\bnight\b|\bpresents\b"
    r"|\ball[\s-]?dayer\b|\bfestival\b|\bgala\b|\b(?:and|&)\s+(?:friends|guests?|support)\b|\bsupport\s+acts?\b"
)
BRAND_WORD_RE = _rx(
    r"\b(?:comedy|comedians?|comic|laughs?|laughter|jokes?|funny|stand[\s-]?up|standup|improv|live|club|night|nights|"
    r"festival|fringe|presents|sessions?|showcase|special|cabaret|bingo|quiz|weekend|monday|tuesday|wednesday|thursday|"
    r"friday|saturday|sunday|christmas|halloween|new\s+year|unleashed|lounge|cellar|store|bar|pub|theatre|hall|tonic|"
    r"secret|creatures|hilarity|breakneck|tour|show|open|mic)\b"
)
PERSON_TOKEN_RE = re.compile(r"^(?:[A-Z][a-z'’.\-]+|[A-Z]{2,}|Mc[A-Z][a-z]+|O['’][A-Z][a-z]+|de|van|von|la|le|du)$")


def looks_like_person_name(text):
    """'Ed Byrne', 'KAREN DUNBAR', 'Rob Beckett': 2-4 name-like tokens, no club/brand
    words, and the first token is a known first name (FIRST_NAMES)."""
    text = clean_text(text)
    tokens = text.split()
    if not 2 <= len(tokens) <= 4:
        return False
    if BRAND_WORD_RE.search(text) or re.search(r"\d", text):
        return False
    if not all(PERSON_TOKEN_RE.match(t) for t in tokens):
        return False
    first = re.sub(r"[^a-z]", "", tokens[0].lower())
    return first in FIRST_NAMES


def _act_and_show(title):
    """Split 'Act: Show' / 'Act - Show' / 'Act – Show'. Returns (act, show_or_empty)."""
    parts = re.split(r"\s*(?::|–|—|\s-\s)\s*", clean_text(title), maxsplit=1)
    return (parts[0], parts[1]) if len(parts) == 2 else (parts[0], "")


def is_mixed_bill_title(title):
    """Club nights and line-ups: commas between names, 'with', 'line-up', 'showcase'...

    When the title is 'Act: Show', only the act part is inspected, so show names
    such as 'Bad at Quiz Shows, Good with Weirdos' are not mistaken for line-ups.
    """
    act, show = _act_and_show(title)
    scope = act if show else clean_text(title)
    if MIXED_BILL_RE.search(scope):
        return True
    return act.count(",") >= 1 or act.count("|") >= 1


def looks_like_double_act(text):
    parts = re.split(r"\s*(?:&|\band\b)\s*", clean_text(text), flags=re.I)
    return len(parts) == 2 and all(looks_like_person_name(p) for p in parts)


def tour_signal(event, title, desc, category, comedy_present):
    """Internal tour/solo label: 'tour', 'solo_show', 'wip_preview' or ''.

    shows.json `type` becomes 'tour' only for 'tour' and 'solo_show'. Mixed
    bills, club brands, open mics and generic WIP/preview nights never qualify.
    """
    if not comedy_present:
        return ""
    if OPEN_MIC_GENERIC_RE.search(title) or OPEN_MIC_STRONG_RE.search(f"{title} {desc}"):
        return ""
    if NOT_TOUR_RE.search(title) or NOT_TOUR_RE.search(desc[:400]):
        return ""
    if WIP_PREVIEW_RE.search(title):
        return "wip_preview"
    group_show = bool(re.search(r"\bimprov|\bimprovised\b|\btroupe\b|\bsketch\s+(?:group|troupe|show)\b|\bdouble\s+bill\b|\bmulti\s+offer\b|\bbundle\b", title, re.I))
    mixed = is_mixed_bill_title(title)
    act, show = _act_and_show(title)
    named_act = looks_like_person_name(act) or looks_like_double_act(act)
    single_act = (bool(show) and named_act) or looks_like_person_name(title)
    double_act = bool(re.match(r"^\s*[A-Z][\w'’.\-]+(?:\s+[A-Z][\w'’.\-]+){0,2}\s*(?:&|and)\s*[A-Z][\w'’.\-]+(?:\s+[A-Z][\w'’.\-]+){0,2}\b", title)) \
        and title.count(",") == 0 and not re.search(r"\bwith\b", title, re.I)
    if TOUR_EXPLICIT_RE.search(title) and not mixed:
        return "tour"
    if TOUR_EXPLICIT_RE.search(title) and double_act and title.count(",") == 0:
        return "tour"
    if mixed:
        return ""
    if single_act and TOUR_EXPLICIT_RE.search(desc[:600]):
        return "tour"
    if group_show:
        return ""
    if SOLO_SIGNAL_RE.search(title) or (single_act and SOLO_SIGNAL_RE.search(desc[:600])):
        return "solo_show"
    if show and named_act:
        return "solo_show"
    return ""


# ---------------------------------------------------------------------------
# Canonical URLs and ticket IDs (Task 5)
# ---------------------------------------------------------------------------
TRACKING_PARAM_RE = re.compile(
    r"^(?:utm_.*|fbclid|gclid|dclid|msclkid|mc_cid|mc_eid|_gl|_ga|igshid|si|ref|referrer|ref_src|source|"
    r"aff|affiliate|affid|sscid|cmp|campaign|trk|tracking|clickid|sharer|share|quote|text|mini)$",
    re.I,
)


def canonical_event_url(url):
    """Lower-case host without www., no tracking params/fragment/trailing slash."""
    url = clean_text(url)
    if not url or not url.lower().startswith("http"):
        return url.lower()
    try:
        p = urlparse(url)
        host = p.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not TRACKING_PARAM_RE.match(k)]
        path = re.sub(r"/{2,}", "/", p.path or "/")
        if len(path) > 1:
            path = path.rstrip("/")
        q = urlencode(sorted(query))
        return f"{host}{path}" + (f"?{q}" if q else "")
    except Exception:
        return url.lower()


def same_ticket_url(a, b):
    """True if two records point to the same actual booking link.

    Use the existing URL canonicalisation so www., tracking parameters, fragments
    and trailing slashes do not create false differences. Never consider a blank,
    placeholder or non-HTTP link a shared ticket link.
    """
    url_a = clean_text(a.get("ticket_url", ""))
    url_b = clean_text(b.get("ticket_url", ""))
    return (
        is_valid_source_url(url_a)
        and is_valid_source_url(url_b)
        and canonical_event_url(url_a) == canonical_event_url(url_b)
    )


_TICKET_ID_PATTERNS = [
    ("skiddle", re.compile(r"skiddle\.com/(?:e/(\d{5,})|whats-on/.+?/(\d{5,}))/?$", re.I)),
    ("eventbrite", re.compile(r"eventbrite\.[a-z.]+/e/(?:[^/?#]*-)?(?:tickets-)?(\d{9,})", re.I)),
    ("fatsoma", re.compile(r"fatsoma\.com/e/([a-z0-9]{5,})", re.I)),
    ("fixr", re.compile(r"fixr\.co/event/(?:[^/?#]*-)?(\d{6,})", re.I)),
    ("tickettailor", re.compile(r"tickettailor\.com/events/[^/]+/(\d{4,})", re.I)),
    ("wegottickets", re.compile(r"wegottickets\.com/(?:[^/]+/)?event/(\d{3,})", re.I)),
    ("dice", re.compile(r"dice\.fm/event/([a-z0-9][a-z0-9-]{5,})", re.I)),
    ("seetickets", re.compile(r"seetickets\.com/event/.+?/(\d{4,})", re.I)),
    ("ticketsource", re.compile(r"ticketsource\.[a-z.]+/(?:.+/)?e-([a-z0-9]{4,})", re.I)),
    ("universe", re.compile(r"universe\.com/events/(?:[^/?#]*-)?([A-Z0-9]{6,})(?:$|[/?#])")),
    ("ticketmaster", re.compile(r"ticketmaster\.[a-z.]+/(?:.+/)?event/([A-Z0-9]{8,})", re.I)),
    ("justthetonic", re.compile(r"justthetonic\.com/shows/([^/?#]+)", re.I)),
]

EVENT_DETAIL_PATH_RE = re.compile(
    r"/(?:events?|event-details|shows?|show-details|whats-on|what-s-on|product|products|performances?|gigs?|listings?|tickets?|e)/"
    r"([^/?#]{3,})(?:/[^/?#]*)?/?$",
    re.I,
)
NOT_DETAIL_SEGMENT_RE = re.compile(
    r"^(?:category|categories|tag|tags|page|feed|calendar|month|week|day|list|past|archive|ical|search|all|"
    r"upcoming|venue|venues|organiser|organizer|filter|type|genre|\d{4}|\d{4}-\d{2}|"
    # category / time-filter slugs used in menus (v3.1)
    r"comedy|stand-?up|music|live-music|theatre|theater|family|kids|children|film|films|cinema|dance|spoken-word|poetry|"
    r"cabaret|drag|magic|talks?|workshops?|classes|courses|exhibitions?|festivals?|gigs|live|whats-on|what-s-on|events|shows|"
    r"today|tonight|tomorrow|this-week|next-week|this-weekend|weekend|this-month|next-month|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*(?:-\d{4})?)$",
    re.I,
)


def ticket_event_id(url):
    """'provider:id' for event-specific ticket URLs, 'site:host/path' for event detail pages, else ''."""
    raw = clean_text(url)
    if not raw:
        return ""
    canon = canonical_event_url(raw)
    for provider, rx in _TICKET_ID_PATTERNS:
        m = rx.search(canon) or rx.search(raw)
        if m:
            value = next((g for g in m.groups() if g), "")
            if value:
                return f"{provider}:{value.lower()}"
    if is_event_detail_url(raw):
        return "site:" + canon
    return ""


def is_event_detail_url(url, base_url=""):
    """True for URLs that look like ONE event (/events/<slug>, /shows/<slug>, /product/<slug>...)."""
    url = clean_text(url)
    if not url or url.startswith("#") or url.lower().startswith(("mailto:", "tel:", "javascript:")):
        return False
    full = absolute_url(base_url, url) if base_url else url
    p = urlparse(full)
    if p.scheme not in {"http", "https"}:
        return False
    host = p.netloc.lower()
    if any(b in host for b in ["facebook.", "twitter.", "x.com", "instagram.", "linkedin.", "tiktok.", "youtube.", "google."]):
        return False
    if base_url:
        base_host = urlparse(base_url).netloc.lower().replace("www.", "")
        if host.replace("www.", "") != base_host and not any(d in full.lower() for d in TICKET_DOMAINS):
            return False
    if any(d in full.lower() for d in TICKET_DOMAINS):
        if "skiddle.com" in full.lower():
            return is_skiddle_event_url(full)
        return bool(re.search(r"/(?:e|event|events|shows?)/[^/?#]{4,}", p.path, re.I))
    m = EVENT_DETAIL_PATH_RE.search(p.path)
    if not m:
        return False
    segment = m.group(1)
    if NOT_DETAIL_SEGMENT_RE.match(segment):
        return False
    if re.search(r"\.(?:jpe?g|png|gif|webp|pdf|svg|css|js)$", p.path, re.I):
        return False
    return True


# ---------------------------------------------------------------------------
# Layered de-duplication (Task 5)
# ---------------------------------------------------------------------------
_TITLE_NOISE_RE = re.compile(
    r"\b(?:tickets?|buy|book(?:ing)?|now|live|presents|at|the|a|an|and|with|show|comedy\s+club|comedy|club|"
    r"stand[\s-]?up|night|evening|uk|tour|\d{4})\b",
    re.I,
)
PERFORMANCE_LABEL_RE = re.compile(
    r"\b(early|late|matinee|afternoon|evening|midnight|first|second|1st|2nd)\s+(?:show|performance|house)\b|\((early|late)\)",
    re.I,
)


def normalise_title_for_match(title, venue="", city=""):
    t = clean_text(remove_emoji_and_symbols(title)).lower()
    t = t.replace("*", "u").replace("&", " and ")
    t = re.split(r"\s*\|\|\s*", t)[0]
    for noise in [clean_text(venue).lower(), clean_text(city).lower()]:
        if noise and len(noise) > 3:
            t = t.replace(noise, " ")
    t = re.sub(r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b", " ", t)
    t = re.sub(r"\b\d{1,2}[:.]\d{2}\s*(?:am|pm)?\b|\b\d{1,2}\s*(?:am|pm)\b", " ", t)
    t = PERFORMANCE_LABEL_RE.sub(" ", t)
    t = _TITLE_NOISE_RE.sub(" ", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def performance_label(title):
    m = PERFORMANCE_LABEL_RE.search(clean_text(title))
    if not m:
        return ""
    label = (m.group(1) or m.group(2) or "").lower()
    return {"1st": "first", "2nd": "second"}.get(label, label)


def time_to_minutes(value):
    value = clean_text(value)
    if not value:
        return None
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*([AaPp][Mm])", value)
    if m:
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
        if h == 12:
            h = 0
        if ap == "pm":
            h += 12
        return h * 60 + mi
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", value)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    return None


def normalise_venue_for_match(venue):
    v = clean_text(venue).lower()
    v = re.sub(r"\b(?:the|comedy|club|bar|pub|theatre|theater|hall|centre|center|venue|ltd|limited|at)\b", " ", v)
    v = re.sub(r"[^a-z0-9]+", " ", v)
    return set(w for w in v.split() if len(w) > 1)


def venues_compatible(a, b):
    ca, cb = clean_text(a.get("city", "")).lower(), clean_text(b.get("city", "")).lower()
    if ca and cb and ca != cb:
        return False
    raw_a, raw_b = slugify_text(a.get("venue", "")), slugify_text(b.get("venue", ""))
    va, vb = normalise_venue_for_match(a.get("venue", "")), normalise_venue_for_match(b.get("venue", ""))
    if not va or not vb:
        if raw_a and raw_b:
            return raw_a == raw_b or raw_a in raw_b or raw_b in raw_a
        return bool(ca and cb and ca == cb)
    overlap = len(va & vb) / max(1, min(len(va), len(vb)))
    return overlap >= 0.5


def titles_match_strength(a, b):
    """2 = same normalised title, 1 = fuzzy match, 0 = different."""
    ta = normalise_title_for_match(a.get("title", ""), a.get("venue", ""), a.get("city", ""))
    tb = normalise_title_for_match(b.get("title", ""), b.get("venue", ""), b.get("city", ""))
    if not ta or not tb:
        return 0
    if ta == tb:
        return 2
    from difflib import SequenceMatcher
    if SequenceMatcher(None, ta, tb).ratio() >= 0.85:
        return 1
    wa, wb = set(ta.split()), set(tb.split())
    if min(len(wa), len(wb)) >= 2 and len(wa & wb) / min(len(wa), len(wb)) >= 0.8:
        return 1
    return 0


def _event_time_minutes(e):
    return time_to_minutes(e.get("time", ""))


def events_are_same_performance(a, b, ambiguous_check=None):
    """Conservative layered match. Never matches on title alone."""
    if not a.get("date") or a.get("date") != b.get("date"):
        return False, ""
    ta, tb = _event_time_minutes(a), _event_time_minutes(b)
    if ta is not None and tb is not None and ta != tb:
        return False, ""
    la, lb = performance_label(a.get("title", "")), performance_label(b.get("title", ""))
    if la != lb:
        return False, ""

    # An identical booking URL is stronger evidence than the scraped title or
    # venue label (one card may be labelled "More from this event organiser").
    # Keep different dates, cities and independently timed performances apart.
    if same_ticket_url(a, b):
        ca, cb = clean_text(a.get("city", "")).lower(), clean_text(b.get("city", "")).lower()
        if ca and cb and ca != cb:
            return False, ""
        if (ta is None or tb is None) and ambiguous_check and ambiguous_check(a, b):
            return False, "ambiguous"
        return True, "same booking URL"

    ida, idb = ticket_event_id(a.get("ticket_url", "")), ticket_event_id(b.get("ticket_url", ""))
    if ida and ida == idb:
        return True, "same event id"
    if not venues_compatible(a, b):
        return False, ""
    strength = titles_match_strength(a, b)
    if strength == 0:
        return False, ""
    if ta is not None and tb is not None:
        return True, "same title/date/venue/time" if strength == 2 else "fuzzy title + same date/venue/time"
    if strength < 2:
        return False, ""
    if ta is None and tb is None:
        return True, "same title/date/venue (no times)"
    # One side has a time and the other does not: only merge if that time is the
    # only performance of this show at this venue on this date.
    if ambiguous_check and ambiguous_check(a, b):
        return False, "ambiguous"
    return True, "same title/date/venue, time on one side only"


SOURCE_QUALITY = {
    "detail": 6, "jsonld": 6, "card": 5, "pagejson": 4, "skiddle": 4, "fatsoma": 4, "fixr": 4,
    "tickettailor": 4, "justthetonic": 5, "topsecret": 5, "hilaritybites": 5, "universe": 4,
    "eventbrite": 3, "wegottickets": 4, "site": 2, "sitejson": 3, "iframe": 3,
}


def event_quality(e):
    score = SOURCE_QUALITY.get(clean_text(e.get("_extraction", "")), 0) or SOURCE_QUALITY.get(clean_text(e.get("source_type", "")).lower(), 2)
    if e.get("time"):
        score += 1
    if ticket_event_id(e.get("ticket_url", "")):
        score += 2
    if e.get("image") and not bad_event_image_url(e.get("image", "")):
        score += 0.5
    if e.get("price"):
        score += 0.5
    return score


def _title_quality(e):
    t = clean_text(e.get("title", ""))
    score = 0
    if not t:
        return -99
    # Generic headings are sometimes scraped from a related-event card instead
    # of the actual show. They must not replace a real show title on merge.
    if re.search(r"\bmore\s+from\s+(?:this|the|an?)\s+(?:event\s+)?organi[sz]er\b|\bmore\s+events?\s+from\b", t, re.I):
        score -= 12
    if slugify_text(t) == slugify_text(e.get("venue", "")):
        score -= 4
    if re.search(r"\d{1,2}[:.]\d{2}|\b(?:mon|tue|wed|thu|fri|sat|sun)\w*\s+\d{1,2}\b|tickets?|\|\|", t, re.I):
        score -= 2
    if re.match(r"^(?:book(?:/information|\s+now)?|buy|more\s+info|tickets?|information|details|find\s+out\s+more)\b", t, re.I):
        score -= 3  # button text captured as a title
    if 6 <= len(t) <= 110:
        score += 1
    src = clean_text(e.get("source_type", "")).lower()
    if src in {"site", "sitejson", "topsecret", "justthetonic", "hilaritybites"} or e.get("_extraction") in {"card", "detail", "jsonld"}:
        score += 1.5  # official venue wording preferred
    return score


def merge_event_records(records):
    """Merge records describing the same performance, keeping the best of each field."""
    if len(records) == 1:
        return records[0]
    ranked = sorted(records, key=event_quality, reverse=True)
    best = dict(ranked[0])
    best_title_record = max(records, key=_title_quality)
    best["title"] = best_title_record.get("title", best.get("title", ""))
    timed = [r for r in ranked if r.get("time")]
    if timed:
        best["time"] = timed[0]["time"]
    specific = [r for r in records if ticket_event_id(r.get("ticket_url", ""))]
    if specific:
        providers = [r for r in specific if not ticket_event_id(r["ticket_url"]).startswith("site:")]
        best["ticket_url"] = (providers or specific)[0]["ticket_url"]
    venues = [clean_text(r.get("venue", "")) for r in ranked if clean_text(r.get("venue", ""))]
    if venues:
        with_room = [v for v in venues if " - " in v]
        best["venue"] = with_room[0] if with_room else venues[0]
    # When one ticket link was scraped as a generic organiser card and another
    # as the real event, use the venue paired with the clearly better title.
    # Leave the normal room/detail preference unchanged for ordinary merges.
    if all(same_ticket_url(records[0], r) for r in records[1:]):
        other_title_scores = [_title_quality(r) for r in records if r is not best_title_record]
        if (other_title_scores and
                _title_quality(best_title_record) - max(other_title_scores) >= 3 and
                clean_text(best_title_record.get("venue", ""))):
            best["venue"] = clean_text(best_title_record["venue"])
    for field in ("city", "state", "price"):
        if not clean_text(best.get(field, "")):
            for r in ranked:
                if clean_text(r.get(field, "")):
                    best[field] = r[field]
                    break
    images = [r.get("image", "") for r in ranked if r.get("image") and not bad_event_image_url(r.get("image", ""))]
    if images:
        best["image"] = images[0]
    descs = [clean_text(r.get("description", "")) for r in records if clean_text(r.get("description", ""))]
    good = [d for d in descs if len(d) <= 2000]
    specific = [d for d in good if not is_boilerplate_description(d)]
    if specific or good:
        best["description"] = max(specific or good, key=len)
    best["confidence"] = max(int(r.get("confidence", 0) or 0) for r in records)
    merged_from = []
    for r in records:
        merged_from.extend(r.get("_merged_from") or [f"{r.get('source_type', '')}:{r.get('ticket_url', '')}"])
    best["_merged_from"] = dedupe_ordered(merged_from)
    best.pop("_classification", None)
    return best


def layered_dedupe(events, record_stats=False):
    """Group records that are the same performance; keep separate performances apart."""
    if not events:
        return []
    by_date = {}
    for idx, e in enumerate(events):
        by_date.setdefault(clean_text(e.get("date", "")), []).append(idx)

    parent = list(range(len(events)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    ambiguous_pairs = []
    for date, idxs in by_date.items():
        if not date:
            # undated rows: only exact duplicates collapse
            seen = {}
            for i in idxs:
                e = events[i]
                key = (slugify_text(e.get("title", "")), slugify_text(e.get("venue", "")), canonical_event_url(e.get("ticket_url", "")))
                if key in seen:
                    parent[find(i)] = find(seen[key])
                else:
                    seen[key] = i
            continue

        def ambiguous(a, b, idxs=idxs):
            # A link may be shared across multiple timed performances. When a
            # record has no time, do not let it bridge two different shows.
            times = set()
            for k in idxs:
                c = events[k]
                if same_ticket_url(c, a) or (titles_match_strength(c, a) == 2 and venues_compatible(c, a)):
                    t = _event_time_minutes(c)
                    if t is not None:
                        times.add(t)
            return len(times) > 1

        for x in range(len(idxs)):
            for y in range(x + 1, len(idxs)):
                i, j = idxs[x], idxs[y]
                same, reason = events_are_same_performance(events[i], events[j], ambiguous)
                if same:
                    parent[find(j)] = find(i)
                elif reason == "ambiguous":
                    ambiguous_pairs.append((i, j))

    groups = {}
    order = []
    for i in range(len(events)):
        r = find(i)
        if r not in groups:
            groups[r] = []
            order.append(r)
        groups[r].append(events[i])
    out = [merge_event_records(groups[r]) for r in order]
    if record_stats and DIAGNOSTICS is not None:
        DIAGNOSTICS.duplicates_removed += len(events) - len(out)
        flagged = set()
        for i, j in ambiguous_pairs:
            for k in (i, j):
                if events[k].get("time") or k in flagged:
                    continue
                flagged.add(k)
                diag_event("ambiguous_merge", detail="no time given and several performances exist that day; kept separate", event=events[k])
    return out


# ---------------------------------------------------------------------------
# Location parsing (Task 2: Breakneck / Comedy Lounge Hull)
# ---------------------------------------------------------------------------
UK_POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b", re.I)
STREET_WORD_RE = re.compile(
    r"^\d|\b(?:st|street|road|rd|lane|ln|avenue|ave|place|pl|square|sq|terrace|row|way|close|drive|parade|walk|hill|gate|"
    r"crescent|court|wharf|quay|precinct|arcade|unit)\b\.?$",
    re.I,
)
COUNTRY_WORDS = {"uk", "united kingdom", "gb", "great britain", "england", "scotland", "wales", "northern ireland"}

# Towns seen on multi-location organiser listings that are missing from
# CITY_TO_REGION. Values are factual UK regions; extend as needed.
EXTRA_CITY_TO_REGION = {
    "aberfeldy": "Scotland", "aboyne": "Scotland", "airdrie": "Scotland", "airth": "Scotland", "alford": "Scotland",
    "alloa": "Scotland", "alyth": "Scotland", "anstruther": "Scotland", "arbroath": "Scotland", "auchenblae": "Scotland",
    "auchterarder": "Scotland", "aviemore": "Scotland", "ayr": "Scotland", "ballater": "Scotland", "balmedie": "Scotland",
    "banchory": "Scotland", "banff": "Scotland", "barrhead": "Scotland", "bathgate": "Scotland", "bearsden": "Scotland",
    "beith": "Scotland", "biggar": "Scotland", "bishopton": "Scotland", "blairgowrie": "Scotland", "boat of garten": "Scotland",
    "bo'ness": "Scotland", "braemar": "Scotland", "brechin": "Scotland", "bridge of weir": "Scotland", "broughty ferry": "Scotland",
    "broxburn": "Scotland", "buckie": "Scotland", "burntisland": "Scotland", "caldercruix": "Scotland", "campbeltown": "Scotland",
    "cardenden": "Scotland", "cardross": "Scotland", "carluke": "Scotland", "carnoustie": "Scotland", "castle douglas": "Scotland",
    "chryston": "Scotland", "coatbridge": "Scotland", "coupar angus": "Scotland", "cowdenbeath": "Scotland", "crail": "Scotland",
    "crieff": "Scotland", "cruden bay": "Scotland", "cumbernauld": "Scotland", "cupar": "Scotland", "dalkeith": "Scotland",
    "darvel": "Scotland", "dollar": "Scotland", "doune": "Scotland", "dufftown": "Scotland", "dumbarton": "Scotland",
    "dumfries": "Scotland", "dunbar": "Scotland", "dunblane": "Scotland", "dundee": "Scotland", "dunfermline": "Scotland",
    "dunlop": "Scotland", "dunoon": "Scotland", "east kilbride": "Scotland", "east linton": "Scotland", "edinburgh": "Scotland",
    "elgin": "Scotland", "ellon": "Scotland", "erskine": "Scotland", "eyemouth": "Scotland", "falkirk": "Scotland",
    "forfar": "Scotland", "forres": "Scotland", "fort augustus": "Scotland", "fort william": "Scotland", "fraserburgh": "Scotland",
    "galashiels": "Scotland", "gargunnock": "Scotland", "giffnock": "Scotland", "glasgow": "Scotland", "glenrothes": "Scotland",
    "gorebridge": "Scotland", "gourock": "Scotland", "grangemouth": "Scotland", "grantown-on-spey": "Scotland", "greenock": "Scotland",
    "hamilton": "Scotland", "hawick": "Scotland", "helensburgh": "Scotland", "hopeman": "Scotland", "huntly": "Scotland",
    "inchture": "Scotland", "inverbervie": "Scotland", "invergordon": "Scotland", "inverkeithing": "Scotland", "inverness": "Scotland",
    "inverurie": "Scotland", "irvine": "Scotland", "isle of skye": "Scotland", "jedburgh": "Scotland", "johnshaven": "Scotland",
    "keith": "Scotland", "kelty": "Scotland", "kemnay": "Scotland", "kilbarchan": "Scotland", "killearn": "Scotland",
    "kilmacolm": "Scotland", "kilmarnock": "Scotland", "kilmaurs": "Scotland", "kingswells": "Scotland", "kintore": "Scotland",
    "kirkcaldy": "Scotland", "kirkintilloch": "Scotland", "larbert": "Scotland", "laurencekirk": "Scotland", "leslie": "Scotland",
    "linlithgow": "Scotland", "livingston": "Scotland", "lochcarron": "Scotland", "lockerbie": "Scotland", "lossiemouth": "Scotland",
    "lumphanan": "Scotland", "luncarty": "Scotland", "markinch": "Scotland", "mauchline": "Scotland", "methil": "Scotland",
    "milnathort": "Scotland", "milngavie": "Scotland", "mintlaw": "Scotland", "moffat": "Scotland", "monikie": "Scotland",
    "montrose": "Scotland", "motherwell": "Scotland", "nairn": "Scotland", "new deer": "Scotland", "new pitsligo": "Scotland",
    "newport on tay": "Scotland", "newtonhill": "Scotland", "newton mearns": "Scotland", "newtonmore": "Scotland",
    "newton stewart": "Scotland", "north kessock": "Scotland", "oakley": "Scotland", "oldmeldrum": "Scotland", "paisley": "Scotland",
    "penicuik": "Scotland", "perth": "Scotland", "peterhead": "Scotland", "pitlochry": "Scotland", "pitmedden": "Scotland",
    "portlethen": "Scotland", "portobello": "Scotland", "portsoy": "Scotland", "queensferry": "Scotland", "rhu": "Scotland",
    "rosyth": "Scotland", "rothienorman": "Scotland", "rutherglen": "Scotland", "saltcoats": "Scotland", "scone": "Scotland",
    "selkirk": "Scotland", "shotts": "Scotland", "st andrews": "Scotland", "st fergus": "Scotland", "stirling": "Scotland",
    "stonehaven": "Scotland", "stranraer": "Scotland", "strathblane": "Scotland", "strathpeffer": "Scotland", "strichen": "Scotland",
    "tayport": "Scotland", "thurso": "Scotland", "tillicoultry": "Scotland", "torphins": "Scotland", "troon": "Scotland",
    "tullibody": "Scotland", "turriff": "Scotland", "wemyss bay": "Scotland", "west calder": "Scotland", "westhill": "Scotland",
    "west kilbride": "Scotland", "aberdeen": "Scotland", "berwick-upon-tweed": "North East", "hull": "Yorkshire",
}


def looks_like_street(part):
    part = clean_text(part)
    return bool(STREET_WORD_RE.search(part)) or bool(re.match(r"^\d", part))


def parse_address_line(text):
    """'Stage Door, 112-116 George St, Hull HU1 3AA, UK' -> {'place': 'Stage Door', 'city': 'Hull'}."""
    text = clean_text(text)
    if not text or "," not in text:
        return {}
    parts = [clean_text(p) for p in text.split(",") if clean_text(p)]
    parts = [p for p in parts if p.lower() not in COUNTRY_WORDS]
    if not parts:
        return {}
    city = ""
    for p in reversed(parts):
        m = UK_POSTCODE_RE.search(p)
        if m:
            candidate = clean_text(p[:m.start()])
            if candidate and not looks_like_street(candidate):
                city = candidate
            elif len(parts) >= 2:
                prev = parts[parts.index(p) - 1]
                if prev and not looks_like_street(prev):
                    city = prev
            break
    if not city and len(parts) >= 2 and not looks_like_street(parts[-1]) and len(parts[-1].split()) <= 4:
        city = parts[-1]
    place = parts[0] if parts and not looks_like_street(parts[0]) and parts[0] != city else ""
    return {"place": place, "city": city}


def compose_venue_name(parent, room):
    """Keep sub-venue/room names: 'Comedy Lounge' + 'Stage Door' -> 'Comedy Lounge - Stage Door'."""
    parent, room = clean_text(parent), clean_text(room)
    if not room or looks_like_street(room):
        return parent
    if not parent:
        return room
    pl, rl = parent.lower(), room.lower()
    if rl in pl:
        return parent
    if pl in rl:
        return room
    return f"{parent} - {room}"


def region_for_city(city):
    return infer_region_from_city(city)


def same_place(a, b):
    a, b = clean_text(a).lower(), clean_text(b).lower()
    if not a or not b:
        return False
    return a == b or a in b or b in a


# ---------------------------------------------------------------------------
# Listing-card extraction (Task 2)
# ---------------------------------------------------------------------------
CARD_JUNK_LINES = {
    "buy tickets", "buy ticket", "more info", "more information", "book now", "book", "tickets", "get tickets",
    "buy now", "quantity:", "quantity", "sold out!", "sold out", "ticket type:", "ticket type", "standard",
    "vip meet & greet", "price:", "price", "booking fee included", "show is not available in this quantity.",
    "remove", "subtotal", "close", "read more", "find out more", "details", "info", "share", "view event",
    "rsvp", "waiting list", "limited tickets", "load more", "shows", "#",
}
CARD_LABELS = {"venue", "location", "where", "doors", "door", "show", "starts", "start", "time", "when", "date", "price"}
TIME_24_RE = re.compile(r"^(?:[01]?\d|2[0-3])[:.][0-5]\d$")


def card_lines(node):
    lines = []
    for raw in node.get_text("\n").split("\n"):
        line = clean_text(raw)
        if line:
            lines.append(line)
    return lines


def _is_junk_line(line):
    low = clean_text(line).lower().strip(" :")
    if not low or low in CARD_JUNK_LINES:
        return True
    if low.startswith("http"):
        return True
    return False


def _line_is_date_only(line):
    l = clean_text(line)
    if not l:
        return False
    if re.fullmatch(r"(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?|\d{1,2}|\d{4}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*", l, re.I):
        return True
    stripped = re.sub(r"[,\s]+", " ", l)
    dates = find_dates_in_text(stripped)
    if dates:
        rest = stripped
        rest = re.sub(r"\d{1,2}[:.]\d{2}|\d{4}|(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*|\d{1,2}(?:st|nd|rd|th)?|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*|[–—\-,/:.@]|\bat\b|am|pm", " ", rest, flags=re.I)
        return not clean_text(rest)
    return False


def card_for_link(anchor, url_key, key_fn):
    """Largest ancestor of an event link that contains no OTHER event link."""
    best = anchor.parent
    node = anchor
    for _ in range(12):
        node = node.parent
        if node is None or node.name in {"body", "html", "[document]"}:
            break
        keys = set()
        for a in node.select("a[href]"):
            k = key_fn(a.get("href") or "")
            if k:
                keys.add(k)
            if len(keys) > 1:
                break
        if keys - {url_key}:
            break
        best = node
    return best


def parse_labelled_fields(lines):
    """Webflow-style label/value cards: venue / <venue> / <town> / doors / 19:00 / show / 19:30."""
    out = {}
    lowered = [l.lower().strip(" :") for l in lines]
    for i, label in enumerate(lowered):
        if label in {"venue", "location", "where"} and i + 1 < len(lines):
            venue = lines[i + 1]
            if venue.lower().strip(" :") not in CARD_LABELS:
                out["venue"] = venue
                if i + 2 < len(lines):
                    nxt = lines[i + 2]
                    if nxt.lower().strip(" :") not in CARD_LABELS and not _is_junk_line(nxt) and len(nxt) <= 40 \
                            and not re.search(r"\d", nxt) and not find_dates_in_text(nxt):
                        out["city"] = nxt
        if label in {"show", "starts", "start", "show time", "showtime"} and i + 1 < len(lines):
            value = lines[i + 1]
            if TIME_24_RE.match(value) or re.match(r"^\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm)$", value, re.I):
                out["time"] = normalise_time_label(value.replace(".", ":"))
        if label in {"doors", "door"} and i + 1 < len(lines):
            value = lines[i + 1]
            if TIME_24_RE.match(value) or re.match(r"^\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm)$", value, re.I):
                out["doors"] = normalise_time_label(value.replace(".", ":"))
    return out


def extract_card_time(lines, text):
    fields = parse_labelled_fields(lines)
    if fields.get("time"):
        return fields["time"]
    t = extract_performance_time(text)
    if t:
        return t
    # '16 Oct 2026, 19:00' (date line followed by a 24-hour time)
    m = re.search(r"\b\d{4}\b\s*,?\s*(?:at\s+)?((?:[01]?\d|2[0-3])[:.][0-5]\d)\b", text)
    if m:
        return normalise_time_label(m.group(1).replace(".", ":"))
    m = re.search(r"\b(?:starts?|show(?:\s*time)?|from)\s*:?\s*((?:[01]?\d|2[0-3])[:.][0-5]\d)\b", text, re.I)
    if m:
        return normalise_time_label(m.group(1).replace(".", ":"))
    return ""


def pick_card_date(text):
    """Prefer an explicit-year date; fall back to a yearless one. Skips long-running ranges."""
    dates = find_dates_in_text(text)
    if not dates:
        return ""
    explicit = [d for _, d, has_year in dates if has_year]
    chosen = explicit[0] if explicit else dates[0][1]
    return chosen.strftime("%Y-%m-%d")


def pick_card_title(card, lines, anchor_text):
    for h in card.select("h1, h2, h3, h4, h5, [data-hook*='title'], .event-title, .title"):
        t = clean_text(h.get_text(" ", strip=True))
        if t and not _is_junk_line(t) and not _line_is_date_only(t) and t.lower().strip(" :") not in CARD_LABELS:
            if not looks_like_navigation_or_non_event_title(t):
                return t
    at = clean_text(anchor_text)
    if at and not _is_junk_line(at) and len(at) >= 4 and not _line_is_date_only(at) and not looks_like_navigation_or_non_event_title(at):
        return at
    for i, line in enumerate(lines):
        if line.endswith("/") and len(line) > 3:
            return clean_text(line.rstrip("/"))
        if line.strip() == "/" and i > 0 and not _is_junk_line(lines[i - 1]) and not _line_is_date_only(lines[i - 1]):
            return lines[i - 1]
    for line in lines:
        if _is_junk_line(line) or _line_is_date_only(line) or line.lower().strip(" :") in CARD_LABELS:
            continue
        if len(line) >= 4:
            return line
    return ""


def pick_card_room(lines, title, card=None):
    """Wix lists show 'Title /' then the room/location name on the next line
    (the '/' may also be its own line, or the room may carry a data-hook)."""
    t = clean_text(title).lower()
    for i, line in enumerate(lines):
        is_title_slash = line.endswith("/") and clean_text(line.rstrip("/")).lower() == t
        is_bare_slash = line.strip() == "/" and i > 0 and clean_text(lines[i - 1]).lower() == t
        if (is_title_slash or is_bare_slash) and i + 1 < len(lines):
            room = lines[i + 1]
            if not _is_junk_line(room) and not _line_is_date_only(room):
                return room
    if card is not None:
        node = card.select_one("[data-hook*='location']")
        if node:
            text = clean_text(node.get_text(" ", strip=True))
            if text and "," not in text and len(text) <= 60:
                return text
    return ""


def card_subtitle(lines, title):
    """Line straight after the title on label-style cards (show name or support line-up)."""
    for i, line in enumerate(lines):
        if clean_text(line).lower() == clean_text(title).lower() and i + 1 < len(lines):
            nxt = lines[i + 1]
            if nxt.lower().strip(" :") in CARD_LABELS or _is_junk_line(nxt) or _line_is_date_only(nxt):
                return ""
            return nxt if len(nxt) <= 90 else ""
    return ""


def build_card_title(title, subtitle):
    if not subtitle:
        return title
    if "|" in subtitle:
        support = [clean_text(x) for x in subtitle.split("|") if clean_text(x)]
        return f"{title}, {', '.join(support)}"
    return f"{title}: {subtitle}"


def card_description(lines, title, exclude=()):
    skip = {clean_text(x).lower() for x in exclude if clean_text(x)}
    keep = []
    for line in lines:
        low = line.lower().strip(" :")
        if _is_junk_line(line) or _line_is_date_only(line) or low in CARD_LABELS or line.strip() == "/":
            continue
        if clean_text(line).lower() == clean_text(title).lower() or clean_text(line).lower() in skip:
            continue
        if UK_POSTCODE_RE.search(line) and "," in line:
            continue  # address line
        keep.append(line)
    return clean_text(" ".join(keep))[:1200]


CHROME_CLASS_RE = re.compile(r"(?:^|[\s_-])(?:nav|navbar|navigation|menu|header|footer|breadcrumbs?|site-header|site-footer|filters?)(?:$|[\s_-])", re.I)


def in_site_chrome(node):
    """True for links inside <nav>/<header>/<footer> or menu/filter containers."""
    for parent in node.parents:
        if parent is None or parent.name in (None, "[document]"):
            break
        if parent.name in {"nav", "header", "footer"}:
            return True
        role = (parent.get("role") or "").lower() if hasattr(parent, "get") else ""
        if role in {"navigation", "menubar", "banner", "contentinfo"}:
            return True
        classes = " ".join(parent.get("class") or []) if hasattr(parent, "get") else ""
        if classes and CHROME_CLASS_RE.search(classes):
            return True
    return False


def event_link_key(href, page_url):
    if not href:
        return ""
    full = absolute_url(page_url, href).split("#")[0]
    if not is_event_detail_url(full, page_url):
        return ""
    return canonical_event_url(full)


def extract_listing_cards(soup, page_url, venue_name, city, source_type="site"):
    """Parse event cards built around per-event links (Wix, Webflow, Squarespace,
    WordPress calendars and most bespoke 'What's On' pages).

    Returns (events, detail_links, undated_detail_links).
    """
    events = []
    detail_links = []
    undated_links = []
    if not soup:
        return events, detail_links, undated_links
    anchors = {}
    for a in soup.select("a[href]"):
        if in_site_chrome(a):
            continue  # navigation/header/footer links are never shows
        key = event_link_key(a.get("href") or "", page_url)
        if not key:
            continue
        anchors.setdefault(key, []).append(a)
    if not anchors:
        return events, detail_links, undated_links

    key_fn = lambda h: event_link_key(h, page_url)
    card_cities = set()
    parsed = []
    for key, link_nodes in anchors.items():
        anchor = link_nodes[0]
        full_url = absolute_url(page_url, anchor.get("href")).split("#")[0]
        detail_links.append(full_url)
        card = card_for_link(anchor, key, key_fn)
        lines = card_lines(card)
        text = clean_text(" ".join(lines))
        if not text:
            continue
        if date_range_span_days(text) > LONG_RUNNING_DAYS:
            diag_event("long_running")
            continue
        date = pick_card_date(text)
        if not date:
            undated_links.append(full_url)
            continue
        anchor_text = max((clean_text(n.get_text(" ", strip=True)) for n in link_nodes), key=len, default="")
        title = pick_card_title(card, lines, anchor_text)
        if not title:
            undated_links.append(full_url)
            continue
        fields = parse_labelled_fields(lines)
        if fields:
            title = build_card_title(title, card_subtitle(lines, title))
        room = pick_card_room(lines, title, card)
        address = ""
        for line in lines:
            if UK_POSTCODE_RE.search(line) and "," in line:
                address = line
                break
        addr = parse_address_line(address) if address else {}
        event_city = fields.get("city") or addr.get("city") or ""
        room_name = fields.get("venue") or room or addr.get("place") or ""
        if event_city:
            card_cities.add(event_city.lower())
        parsed.append({
            "title": title, "date": date, "url": full_url, "card": card, "lines": lines, "text": text,
            "time": extract_card_time(lines, text), "room": room_name, "city": event_city,
            "location_from_listing": bool(fields.get("venue") or room or address),
        })

    multi_location = len(card_cities) >= 2
    for item in parsed:
        event_city = item["city"]
        flag = ""
        if not event_city:
            if multi_location:
                flag = "location unclear on multi-location listing"
            event_city_out = city
        else:
            event_city_out = event_city
        if item["room"] and event_city and not same_place(event_city, city):
            venue_out = item["room"]  # a different town: the room IS the venue
        else:
            venue_out = compose_venue_name(venue_name, item["room"])
        description = card_description(item["lines"], item["title"], exclude=(item["room"], item["city"]))
        image = find_best_image_in_block(item["card"], page_url, soup)
        e = make_event(item["title"], item["date"], venue_out, event_city_out, description, item["url"], image, page_url, source_type)
        e["_extraction"] = "card"
        if item["time"]:
            e["time"] = item["time"]
        price = extract_price_label(item["text"])
        if price:
            e["price"] = price
        e["_location_source"] = "listing" if event_city else "venue_default"
        if flag:
            e["_location_flag"] = flag
            diag_event("location", detail=flag, event=e)
        events.append(e)
    return events, dedupe_ordered(detail_links), dedupe_ordered(undated_links)


# ---------------------------------------------------------------------------
# Event detail pages (Task 2)
# ---------------------------------------------------------------------------
def scrape_event_detail_page(url, venue_name, city, hint=None):
    """Extract one event from its own page (JSON-LD first, then visible HTML)."""
    soup = get_soup(url)
    if not soup:
        return []
    diag_event("detail", url)
    structured = extract_jsonld_events(soup, url, venue_name, city, "site")
    if structured:
        for e in structured:
            e["_extraction"] = "detail"
        return structured
    # A page linking to several other events is a listing/category page, not one show.
    own = canonical_event_url(url)
    other_events = {canonical_event_url(absolute_url(url, a.get("href") or "")) for a in soup.select("a[href]")
                    if not in_site_chrome(a) and is_event_detail_url(absolute_url(url, a.get("href") or ""), url)}
    other_events.discard(own)
    if len(other_events) >= 3:
        return []
    title = ""
    for sel in ["h1", "meta[property='og:title']", "title"]:
        node = soup.select_one(sel)
        if node:
            title = clean_text(node.get("content") if node.name == "meta" else node.get_text(" ", strip=True))
            title = re.sub(r"\s*[|–-]\s*[^|–-]{2,40}$", "", title) if sel == "title" else title
            if title:
                break
    main = soup.select_one("main, article, [role='main']") or soup.body or soup
    lines = card_lines(main)[:120]
    text = clean_text(" ".join(lines))
    date = ""
    for t in soup.select("time[datetime]"):
        parsed = parse_iso_datetime_local(t.get("datetime", "")) if "T" in (t.get("datetime") or "") else None
        date = parsed[0] if parsed else normalise_date(t.get("datetime", ""))
        if date:
            break
    if not date:
        date = pick_card_date(text)
    if hint and not date:
        date = hint.get("date", "")
    if not title and hint:
        title = hint.get("title", "")
    if not title or not date:
        return []
    meta_desc = soup.select_one("meta[name='description'], meta[property='og:description']")
    description = clean_text(meta_desc.get("content")) if meta_desc and meta_desc.get("content") else ""
    if len(description) < 80:
        description = card_description(lines, title)[:1200]
    address = next((l for l in lines if UK_POSTCODE_RE.search(l) and "," in l), "")
    addr = parse_address_line(address) if address else {}
    event_city = addr.get("city") or (hint or {}).get("city") or city
    venue_out = compose_venue_name(venue_name, addr.get("place", "")) if addr.get("place") else ((hint or {}).get("venue") or venue_name)
    image = extract_meta_image(soup, url)
    e = make_event(title, date, venue_out, event_city, description, url, image, url, "site")
    e["_extraction"] = "detail"
    t = extract_card_time(lines, text)
    if t:
        e["time"] = t
    price = extract_price_label(text)
    if price:
        e["price"] = price
    return [e]


def enrich_from_detail(event, venue_name, city):
    """Fill gaps (time/description/location) from the event's own page; listing date wins if detail has none."""
    url = event.get("ticket_url", "")
    if not url or not is_event_detail_url(url) or any(d in url.lower() for d in TICKET_DOMAINS):
        return event
    found = scrape_event_detail_page(url, venue_name, city, hint=event)
    if not found:
        return event
    d = found[0]
    if d.get("date") and d["date"] != event.get("date"):
        # trust the event's own page but keep the listing date if the page date is outside the window
        if not date_in_window(d["date"]):
            return event
    merged = merge_event_records([event, d])
    merged["_extraction"] = "detail"
    return merged


# ---------------------------------------------------------------------------
# Pagination and JavaScript detection (Tasks 2 and 3)
# ---------------------------------------------------------------------------
PAGINATION_TEXT_RE = re.compile(r"^(?:next(?:\s+page)?|next\s*[›»>]|[›»]|more\s+(?:events|shows)|older\s+posts|load\s+more)$", re.I)
PAGE_PARAM_RE = re.compile(r"(?:[?&](?:[a-z0-9_]*page|p|pg)=(\d+))|(?:/page/(\d+)/?$)", re.I)


def find_pagination_links(soup, page_url):
    links = []
    if not soup:
        return links
    base_host = urlparse(page_url).netloc.lower()
    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript"):
            continue
        full = absolute_url(page_url, href).split("#")[0]
        if urlparse(full).netloc.lower() != base_host or full == page_url:
            continue
        text = clean_text(a.get_text(" ", strip=True))
        rel = " ".join(a.get("rel") or []).lower()
        aria = clean_text(a.get("aria-label", "")).lower()
        if "next" in rel or PAGINATION_TEXT_RE.match(text) or aria.startswith("next"):
            if PAGE_PARAM_RE.search(full) or "next" in rel or "page" in full.lower():
                links.append(full)
    return dedupe_ordered(links)


CALENDAR_HINT_RE = re.compile(
    r"\bupcoming\s+(?:shows|events|gigs)\b|\bwhat'?s\s+on\b|\b\d+\s+upcoming\s+events\b|\bevents?\s+calendar\b"
    r"|\bloading\s+events\b|\bno\s+events\s+found\b|\bselect\s+a\s+date\b",
    re.I,
)
WIDGET_HINT_RE = re.compile(
    r"wix-events|events-widget|ticket-tailor|tickettailor|skiddle|fatsoma|eventbrite|spektrix|dice\.fm|"
    r"ticketsource|seetickets|data-hook=\"?ev|fullcalendar|tribe-events|calendar-widget|__next_data__|ng-version|data-reactroot",
    re.I,
)


def calendar_not_loaded(soup, html_text, events_found, page_url=""):
    """True when a page clearly promises listings but the static HTML has none."""
    if events_found or not soup:
        return False
    html_text = html_text or str(soup)[:400000]
    text = clean_text(soup.get_text(" ", strip=True))
    promised = bool(CALENDAR_HINT_RE.search(text))
    widget = bool(WIDGET_HINT_RE.search(html_text or "")) or looks_js_rendered_html(html_text or "")
    dated_links = 0
    for a in soup.select("a[href]"):
        if is_event_detail_url(absolute_url(page_url, a.get("href") or "") if page_url else (a.get("href") or ""), page_url):
            dated_links += 1
    few_dates = len(find_dates_in_text(text, limit=10)) < 2
    return promised and widget and few_dates and dated_links < 2


def plain_html_has_event_data(soup, page_url=""):
    if not soup:
        return False
    for script in soup.find_all("script", type="application/ld+json"):
        raw = (script.string or script.get_text() or "").lower()
        if "event" in raw and "startdate" in raw:
            return True
    text = clean_text(soup.get_text(" ", strip=True))
    links = sum(1 for a in soup.select("a[href]")
                if is_event_detail_url(absolute_url(page_url, a.get("href") or "") if page_url else (a.get("href") or ""), page_url))
    return links >= 3 and len(find_dates_in_text(text, limit=10)) >= 3


def page_dates_are_chronological(events):
    dates = [e.get("date") for e in events if e.get("date")]
    return len(dates) >= 2 and all(a <= b for a, b in zip(dates, dates[1:]))


# ---------------------------------------------------------------------------
# Relevance-ranked discovery with bounded budgets (Task 2)
# ---------------------------------------------------------------------------
LISTING_LABEL_SCORES = [
    (re.compile(r"\bwhat'?s\s*on\b|\bwhats[\s-]?on\b|\bwhat[’']s\s+on\b", re.I), 10),
    (re.compile(r"\bupcoming\s+(?:events|shows|gigs|comedy)\b|\ball\s+(?:our\s+)?shows\b|\bsearch\s+all\s+shows\b|\bview\s+all\s+(?:our\s+)?shows\b", re.I), 9),
    (re.compile(r"\bcomedy\s+(?:shows|nights?|club|events|listings|gigs)\b|\bstand[\s-]?up\s+(?:shows|nights?)\b", re.I), 9),
    (re.compile(r"\bopen[\s-]?mic", re.I), 8),
    (re.compile(r"\btour\s+(?:dates|shows)\b|\bon\s+tour\b|\bearly\s+shows\b|\blate\s+shows\b|\bshowcases?\b", re.I), 8),
    (re.compile(r"\bcalendar\b|\bdiary\b|\bprogramme\b|\bschedule\b|\bgig\s*guide\b|\blistings?\b", re.I), 7),
    (re.compile(r"\bevents\b|\bshows\b|\bgigs\b", re.I), 7),
    (re.compile(r"\bbuy\s+tickets\b|\bbook\s+tickets\b|\btickets\b", re.I), 5),
    (re.compile(r"\bcomedy\b|\bstand[\s-]?up\b", re.I), 5),
    (re.compile(r"\blive\b|\bentertainment\b", re.I), 3),
]
LISTING_PATH_SCORES = [
    (re.compile(r"/(?:what-?s-?on|whatson)(?:/|$)", re.I), 10),
    (re.compile(r"/(?:all-shows|upcoming-(?:shows|events)|comedy-(?:shows|nights?|events|club))(?:/|$)", re.I), 9),
    (re.compile(r"/(?:open-?mic\w*|tour-(?:dates|shows)\w*|early-shows|late-shows|\w+-comedy)(?:/|$)", re.I), 8),
    (re.compile(r"/(?:events?|shows?|gigs|calendar|listings?|programme|diary|schedule)(?:/|$)", re.I), 7),
    (re.compile(r"/comedy(?:/|$)", re.I), 6),
]
LISTING_PENALTY_RE = re.compile(
    r"\b(?:contact|about|privacy|terms|cookie|shop|merch(?:andise)?|gallery|blog|news|careers?|jobs?|faq|hire|"
    r"private\s+(?:hire|parties)|gift|vouchers?|log\s*in|login|sign\s*in|account|cart|basket|checkout|menu|food|drink|"
    r"opening\s+hours|accessibility|sponsor|volunteer|press|team|comedians|apply|newsletter|mailing\s+list|book\s+us|"
    r"corporate|weddings?|meetings?|conferences?)\b|/(?:shop|cart|checkout|account|blog|news|privacy|terms|"
    r"contact|faq|gallery|merch\w*|team|comedians|apply\w*|book-us|hire\w*|legals?|wp-admin|wp-login|feed)(?:/|$)",
    re.I,
)
GUESSED_PATH_SCORE = 2
DISCOVERED_DETAIL_LINKS = {}
VENUE_FETCH_BUDGET_USED = {}


def venue_tier(venue):
    venue = venue or {}
    context = f"{venue.get('title', '')} {venue.get('website', '')}".lower()
    hints = (TRUSTED_COMEDY_DOMAINS + PROTECTED_TRUSTED_COMEDY_DOMAINS + FEATURED_COMEDY_DOMAIN_HINTS
             + TRUSTED_COMEDY_VENUE_HINTS + PROTECTED_TRUSTED_COMEDY_VENUE_HINTS)
    if any(h in context for h in hints):
        return "trusted"
    conf = clean_text(venue.get("venue_confidence", "")).lower()
    if "high" in conf or "explicit comedy" in conf or clean_text(venue.get("crawl_type", "")).lower() in {"high", "trusted", "wix", "embed", "creatures"}:
        return "high"
    if "medium" in conf or not conf:
        return "medium"
    return "low"


def discovery_budget(venue=None):
    tier = venue_tier(venue if venue is not None else CURRENT_VENUE)
    base = max(1, int(MAX_EVENT_PAGES_PER_VENUE))
    budgets = {
        "trusted": {"pages": max(8, base + 3), "details": 60, "pagination": 8, "tickets": 40},
        "high": {"pages": base, "details": 30, "pagination": 6, "tickets": 30},
        "medium": {"pages": max(2, base - 2), "details": 12, "pagination": 3, "tickets": TICKET_LINK_LIMIT},
        "low": {"pages": 2, "details": 6, "pagination": 2, "tickets": 6},
    }
    out = dict(budgets[tier])
    out["tier"] = tier
    return out


def budget_take(kind, budget):
    used = VENUE_FETCH_BUDGET_USED.get(kind, 0)
    if used >= budget.get(kind, 0):
        return False
    VENUE_FETCH_BUDGET_USED[kind] = used + 1
    return True


def score_listing_link(full_url, label):
    label = clean_text(label)
    path = urlparse(full_url).path or "/"
    if LISTING_PENALTY_RE.search(label) or LISTING_PENALTY_RE.search(path):
        return 0
    if re.search(r"\.(?:pdf|jpe?g|png|gif|webp|svg|zip|docx?)$", path, re.I):
        return 0
    label_score = max((s for rx, s in LISTING_LABEL_SCORES if rx.search(label)), default=0)
    path_score = max((s for rx, s in LISTING_PATH_SCORES if rx.search(path)), default=0)
    if label_score and path_score:
        return max(label_score, path_score) + 2
    return max(label_score, path_score)


def known_listing_pages_for_venue(venue_name, city, website=""):
    """Hand-approved listing pages for venues whose calendars are not linked
    clearly from their homepage (same protocol as known_skiddle_listing_urls_for_venue)."""
    context = f"{venue_name} {city} {website}".lower()
    pages = []
    if "creaturescomedy.com" in context or ("creatures" in context and "manchester" in context):
        pages.extend([
            "https://www.creaturescomedy.com/what-s-on",
            "https://www.creaturescomedy.com/early-shows",
            "https://www.creaturescomedy.com/tour-shows-1",
        ])
    return dedupe_ordered(pages)


def _same_site(url, base_url):
    a = urlparse(url).netloc.lower().replace("www.", "")
    b = urlparse(base_url).netloc.lower().replace("www.", "")
    return bool(a) and a == b


def prioritised_ticket_links(soup, page_url, limit):
    links = extract_ticket_links(soup, page_url)
    specific = [l for l in links if ticket_event_id(l)]
    generic = [l for l in links if not ticket_event_id(l)]
    return (specific + generic)[:limit]


def extract_page_events(soup, page_url, venue_name, city, budget):
    """All extractors for one fetched page. Returns (events, undated_detail_links)."""
    events = []
    if not soup:
        return events, []
    events.extend(extract_jsonld_events(soup, page_url, venue_name, city, "site"))
    events.extend(extract_page_json_events(soup, page_url, venue_name, city, "sitejson"))
    cards, detail_links, undated_links = extract_listing_cards(soup, page_url, venue_name, city, "site")
    events.extend(cards)
    for iframe_url in extract_embedded_iframe_links(soup, page_url)[:IFRAME_LINK_LIMIT]:
        events.extend(scrape_iframe_src(iframe_url, venue_name, city))
    # The legacy block extractor is kept for pages without per-event cards. On
    # card pages it can mis-assign page-wide text (and the venue's own town) to
    # listings from other towns, so it is skipped there.
    if len(cards) < 2:
        events.extend(extract_generic_events(soup, page_url, venue_name, city, "site"))
    for link in prioritised_ticket_links(soup, page_url, budget.get("tickets", TICKET_LINK_LIMIT)):
        if not budget_take("tickets", budget):
            break
        events.extend(scrape_trusted_ticket_source(link, venue_name, city))
    return events, undated_links


def needs_detail_visit(event):
    if event.get("_extraction") != "card":
        return False
    url = event.get("ticket_url", "")
    if not url or any(d in url.lower() for d in TICKET_DOMAINS):
        return False
    if not date_in_window(event.get("date", "")):
        return False
    cls = event.get("_classification") or classify_event(event)
    if cls.get("category") == CAT_NON_COMEDY and cls.get("hard"):
        return False
    thin = len(clean_text(event.get("description", ""))) < 40
    return thin or not event.get("time") or cls.get("category") == CAT_UNCERTAIN


def enrich_events_with_details(events, venue_name, city, budget, undated_links=None):
    out = []
    for e in events:
        if needs_detail_visit(e) and budget_take("details", budget):
            e = enrich_from_detail(e, venue_name, city)
        out.append(e)
    covered = {canonical_event_url(e.get("ticket_url", "")) for e in out}
    for link in undated_links or []:
        if canonical_event_url(link) in covered:
            continue
        if any(d in link.lower() for d in TICKET_DOMAINS):
            continue  # ticket-provider pages are handled by scrape_trusted_ticket_source()
        if not budget_take("details", budget):
            break
        out.extend(scrape_event_detail_page(link, venue_name, city))
    return out


# ---------------------------------------------------------------------------
# Headless browser manager (Task 3) - one browser per run, reused for all pages
# ---------------------------------------------------------------------------
_PLAYWRIGHT = None
_BROWSER = None
_BROWSER_FAILED = False
LOAD_MORE_LABELS = [
    "load more", "show more events", "show more", "more events", "view more", "see more",
    "next month", "next", "›", "»", "next >",
]
_EVENT_CONTENT_JS = r"""() => {
  const hrefs = Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href') || '');
  const links = hrefs.filter(h => /\/(e|event|events|event-details|shows?|product|whats-on)\/[^\/?#]{3,}/i.test(h)).length;
  const times = document.querySelectorAll('time, [datetime]').length;
  const text = (document.body && document.body.innerText) || '';
  const dates = (text.match(/\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)/gi) || []).length;
  return links + times + dates;
}"""
_CLICK_MORE_JS = r"""(labels) => {
  const els = Array.from(document.querySelectorAll('button, [role="button"], a'));
  for (const el of els) {
    const t = ((el.innerText || '').trim() || (el.getAttribute('aria-label') || '').trim()).toLowerCase();
    if (!t || t.length > 40) continue;
    if (el.tagName === 'A') {
      const href = (el.getAttribute('href') || '').trim().toLowerCase();
      if (href && !href.startsWith('#') && !href.startsWith('javascript')) continue;
    }
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') continue;
    if (!labels.some(l => t === l || t.startsWith(l + ' ') || t === l + ' events')) continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    el.scrollIntoView({block: 'center'});
    el.click();
    return t;
  }
  return '';
}"""


def _headless_browser():
    global _PLAYWRIGHT, _BROWSER, _BROWSER_FAILED
    if _BROWSER is not None or _BROWSER_FAILED:
        return _BROWSER
    try:
        from playwright.sync_api import sync_playwright
        _PLAYWRIGHT = sync_playwright().start()
        _BROWSER = _PLAYWRIGHT.chromium.launch(headless=True)
        import atexit
        atexit.register(close_headless_browser)
    except Exception as exc:
        _BROWSER_FAILED = True
        _BROWSER = None
        print("  Headless fallback unavailable. Install with: pip install playwright && playwright install chromium")
        print("  Headless import/launch error:", exc)
    return _BROWSER


def close_headless_browser():
    global _PLAYWRIGHT, _BROWSER
    try:
        if _BROWSER is not None:
            _BROWSER.close()
    except Exception:
        pass
    try:
        if _PLAYWRIGHT is not None:
            _PLAYWRIGHT.stop()
    except Exception:
        pass
    _BROWSER = None
    _PLAYWRIGHT = None


def _wait_for_event_content(page, timeout_ms):
    """Wait until event-like elements stop increasing (or timeout), not a fixed pause."""
    deadline = time.time() + max(0.5, timeout_ms / 1000.0)
    last, stable = -1, 0
    while time.time() < deadline:
        try:
            count = page.evaluate(_EVENT_CONTENT_JS)
        except Exception:
            count = 0
        if count == last and count >= 3:
            stable += 1
            if stable >= 2:
                return count
        else:
            stable = 0
        last = count
        try:
            page.wait_for_timeout(300)
        except Exception:
            break
    return last


def _horizon_reached(html_text):
    """Chronological listing whose newest dates are already beyond the end date."""
    try:
        text = BeautifulSoup(html_text, "html.parser").get_text(" ")
    except Exception:
        return False
    dates = [d.strftime("%Y-%m-%d") for _, d, _ in find_dates_in_text(text, limit=400)]
    if len(dates) < 3:
        return False
    ascending = sum(1 for a, b in zip(dates, dates[1:]) if a <= b) / max(1, len(dates) - 1)
    return ascending >= 0.8 and dates[-1] > window_end().strftime("%Y-%m-%d")


def _event_link_set(html_text):
    return set(re.findall(r"href=[\"']([^\"']*/(?:e|event|events|event-details|shows?|product)/[^\"'?#]{3,})", html_text or "", re.I))


# ---------------------------------------------------------------------------
# Diagnostics export (Task 7)
# ---------------------------------------------------------------------------
def save_diagnostics(path, venue_diags, accepted_events, cross_source_duplicates=0):
    venue_rows = [d.row() for d in venue_diags]
    event_rows = []
    for e in accepted_events:
        cls = e.get("_classification") or classify_event(e)
        event_rows.append({
            "title": e.get("title", ""), "date": e.get("date", ""), "time": e.get("time", ""),
            "venue": e.get("venue", ""), "city": e.get("city", ""), "state": e.get("state", ""),
            "classification": cls.get("category", ""), "classification_reason": cls.get("reason", ""),
            "tour_or_solo": e.get("_tour", ""), "venue_context": cls.get("context", ""),
            "location_source": e.get("_location_source", ""), "location_flag": e.get("_location_flag", ""),
            "source_type": e.get("source_type", ""), "ticket_url": e.get("ticket_url", ""),
            "merged_from": " | ".join(e.get("_merged_from") or []),
        })
    seen = set()
    review_rows = []
    for r in REVIEW_ROWS:
        key = (r["kind"], r["title"].lower(), r["date"], r["venue"].lower(), r["ticket_url"], r["reason"])
        if key in seen:
            continue
        seen.add(key)
        review_rows.append(r)
    summary = [
        {"metric": "date window", "value": f"{window_start()} to {window_end()}"},
        {"metric": "venues scraped", "value": len(venue_rows)},
        {"metric": "venues returning events", "value": sum(1 for r in venue_rows if r["events_accepted"])},
        {"metric": "events accepted (final)", "value": len(accepted_events)},
        {"metric": "cross-source duplicates merged", "value": cross_source_duplicates},
        {"metric": "confirmed open mics", "value": sum(1 for r in event_rows if r["classification"] == CAT_CONFIRMED_OPEN_MIC)},
        {"metric": "probable open mics", "value": sum(1 for r in event_rows if r["classification"] == CAT_PROBABLE_OPEN_MIC)},
        {"metric": "poetry / spoken-word open mics", "value": sum(1 for r in event_rows if r["classification"] == CAT_POETRY_OPEN_MIC)},
        {"metric": "new-act / new-material / WIP", "value": sum(1 for r in event_rows if r["classification"] == CAT_NEW_ACT)},
        {"metric": "tour / solo candidates", "value": sum(1 for r in event_rows if r["tour_or_solo"])},
        {"metric": "rows needing review", "value": len(review_rows)},
    ]
    sheets = [("Summary", summary), ("Venues", venue_rows), ("Accepted events", event_rows), ("Review", review_rows)]
    if str(path).lower().endswith(".csv"):
        stem = str(path)[:-4]
        for name, rows in sheets:
            out = path if name == "Venues" else f"{stem}_{name.lower().replace(' ', '_')}.csv"
            if not rows:
                continue
            with open(out, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
        print(f"Saved diagnostics CSVs starting {path}")
        return
    try:
        from openpyxl import Workbook
    except ImportError:
        print("Could not save diagnostics Excel. Install openpyxl or use a .csv path.")
        return
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets:
        ws = wb.create_sheet(name)
        if not rows:
            ws.append(["(none)"])
            continue
        headers = list(rows[0].keys())
        ws.append(headers)
        for r in rows:
            ws.append([r.get(h, "") if not isinstance(r.get(h), (list, dict)) else json.dumps(r.get(h)) for h in headers])
        ws.freeze_panes = "A2"
    wb.save(path)
    print(f"Saved diagnostics workbook {path} ({len(venue_rows)} venues, {len(review_rows)} review rows)")


# ---------------------------------------------------------------------------
# v3 relevance / venue helpers
# ---------------------------------------------------------------------------
def relevance_decision(event):
    """Final quality gate (v3). Returns (keep, reason).

    Order: junk/navigation guards -> classifier (context-aware exclusions, open
    mic levels, new-act/WIP, venue context) -> protected venues -> cautious
    providers -> accepted categories -> the original acceptance rules.
    """
    title = event.get("title", "")
    description = event.get("description", "")
    source_type = event.get("source_type", "")

    if is_generic_bad_title(title):
        return False, "generic/bad title"
    if looks_like_navigation_or_non_event_title(title, event.get("ticket_url", "")):
        return False, "navigation / non-event title"
    if not is_valid_poster_comedy_event(event):
        return False, "poster comedy row not clearly comedy"

    cls = classify_event(event)
    if cls["category"] == CAT_NON_COMEDY and cls["reason"] != "no comedy evidence":
        return False, cls["reason"]
    if cls["category"] == CAT_UNCERTAIN and cls["reason"].startswith("open mic with no comedy"):
        return False, cls["reason"]

    if is_protected_trusted_comedy_event(event):
        return True, "protected comedy venue"

    if is_cautious_ticket_provider_event(event):
        if has_strong_comedy_signal_for_cautious_provider(event):
            return True, "broad provider: comedy signal in title/venue/url"
        return False, "broad provider (eventbrite): no strong comedy signal"

    if cls["category"] in ACCEPTED_CATEGORIES:
        return True, f"{cls['category']}: {cls['reason']}"

    combined = f"{title} {description}"
    if has_comedy_title_hint(title):
        return True, "comedy hint in title"
    if is_trusted_comedy_context(event):
        return True, "trusted comedy venue/domain"
    if source_type in TRUSTED_SOURCE_TYPES and is_comedy(combined):
        return True, "trusted ticket platform + comedy wording"
    return False, cls["reason"]


def read_venue_rows(path):
    """venues.csv (default) or an .xlsx export of it (first sheet)."""
    if str(path).lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = ws.iter_rows(values_only=True)
        header = [str(h).strip() if h is not None else "" for h in next(rows, [])]
        out = []
        for r in rows:
            out.append({header[i]: ("" if v is None else str(v)) for i, v in enumerate(r) if i < len(header) and header[i]})
        return out
    with open(path, newline="", encoding="utf-8-sig", errors="ignore") as f:
        return list(csv.DictReader(f))


def popular_override_value(value):
    v = clean_text(value).lower()
    if v in {"1", "true", "yes", "y", "popular"}:
        return True
    if v in {"0", "false", "no", "n", "not popular"}:
        return False
    return None




def safe_get(url, timeout=20):
    url = strip_tracking_params(url)
    cache_key = url.lower()
    if cache_key in SAFE_GET_CACHE:
        return SAFE_GET_CACHE[cache_key]
    r = http_get(url, timeout=timeout)
    if r is not None and r.status_code == 200:
        SAFE_GET_CACHE[cache_key] = r
        return r
    SAFE_GET_CACHE[cache_key] = None
    return None



def looks_js_rendered_html(html_text):
    """Heuristic for pages where cards are probably injected after page load."""
    if not html_text:
        return False
    lower = html_text.lower()
    js_framework = any(x in lower for x in [
        "wix-thunderbolt", "static.parastorage.com", "squarespace", "__next_data__",
        "data-reactroot", "ng-version", "vue", "window.__initial_state__",
        "eventbrite-widget", "skiddle", "fatsoma", "ticket-tailor", "spektrix",
    ])
    has_event_word = any(x in lower for x in ["event", "events", "whats-on", "what's on", "tickets", "shows"])
    visible_text = re.sub(r"<script[\s\S]*?</script>", " ", lower)
    visible_text = re.sub(r"<style[\s\S]*?</style>", " ", visible_text)
    visible_text = re.sub(r"<[^>]+>", " ", visible_text)
    visible_text = re.sub(r"\s+", " ", visible_text).strip()
    sparse_visible_page = len(visible_text) < 900
    return js_framework and (has_event_word or sparse_visible_page)


def get_soup_headless(url, timeout=20):
    """Optional Playwright fallback for JS-rendered pages (v3).

    Install with: pip install playwright && playwright install chromium
    It is only used when --headless is passed, so normal scraping remains light.

    v3 changes: one browser is launched per run and reused; robots.txt is
    respected; instead of a fixed pause we wait until event-like elements stop
    appearing; load-more / next / next-month controls are clicked (Skiddle
    "Show more events" included) until the listing passes the end date or the
    attempt limit is reached. Calendars that REPLACE content (next month) are
    captured as successive snapshots so earlier months are not lost.
    """
    url = strip_tracking_params(url)
    cache_key = "headless:" + url.lower()
    if cache_key in SOUP_HTML_CACHE:
        return BeautifulSoup(SOUP_HTML_CACHE[cache_key], "html.parser")
    if not USE_HEADLESS:
        return None
    if not robots_allows(url):
        diag_event("blocked_robots", url)
        return None
    browser = _headless_browser()
    if browser is None:
        return None
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    except Exception:
        PlaywrightTimeoutError = Exception

    context = None
    try:
        context = browser.new_context(user_agent=HEADERS.get("User-Agent"))
        try:
            context.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in {"image", "font", "media"}
                else route.continue_(),
            )
        except Exception:
            pass
        page = context.new_page()
        polite_wait(url)
        diag_event("playwright", url)
        try:
            page.goto(url, wait_until=HEADLESS_GOTO_WAIT_UNTIL, timeout=HEADLESS_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            print("  Headless timeout, using partial rendered HTML if available:", url)
        except Exception as exc:
            print("  Headless navigation warning:", url, str(exc))

        _wait_for_event_content(page, HEADLESS_READY_TIMEOUT_MS)
        snapshots = []
        try:
            snapshots.append(page.content())
        except Exception:
            pass
        max_clicks = SKIDDLE_SHOW_MORE_CLICKS if "skiddle.com" in url.lower() else HEADLESS_MAX_EXPANSIONS
        for _ in range(max_clicks):
            if snapshots and _horizon_reached(snapshots[-1]):
                break
            try:
                clicked = page.evaluate(_CLICK_MORE_JS, LOAD_MORE_LABELS)
            except Exception:
                clicked = ""
            if not clicked:
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(600)
                except Exception:
                    pass
            _wait_for_event_content(page, max(1500, HEADLESS_READY_TIMEOUT_MS // 2))
            try:
                html_now = page.content()
            except Exception:
                break
            before = _event_link_set(snapshots[-1]) if snapshots else set()
            after = _event_link_set(html_now)
            if not clicked and len(html_now) <= len(snapshots[-1] if snapshots else ""):
                break
            if before and not before.issubset(after):
                snapshots.append(html_now)      # content was replaced (next month): keep both
            else:
                if snapshots:
                    snapshots[-1] = html_now    # content was appended (load more)
                else:
                    snapshots.append(html_now)
            if after == before and not clicked:
                break

        if not snapshots:
            return None
        html_text = snapshots[0] if len(snapshots) == 1 else (
            "<html><body>" + "".join(f'<div class="ukcm-snapshot">{s}</div>' for s in snapshots) + "</body></html>"
        )
        SOUP_HTML_CACHE[cache_key] = html_text
        diag_event("parsed", url)
        return BeautifulSoup(html_text, "html.parser")
    except Exception as exc:
        print("  Headless fetch error:", url, str(exc))
        diag_event("error", url, f"headless error: {exc.__class__.__name__}")
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
    return None



def get_soup(url, timeout=20):
    url = strip_tracking_params(url)
    cache_key = "plain:" + url.lower()
    if cache_key in SOUP_HTML_CACHE:
        return BeautifulSoup(SOUP_HTML_CACHE[cache_key], "html.parser")
    r = SAFE_GET_CACHE.get(url.lower()) or http_get(url, timeout=timeout)
    if r is None:
        # request failed or robots.txt disallows: only try the browser for plain failures
        if USE_HEADLESS and robots_allows(url):
            return get_soup_headless(url, timeout=timeout)
        return None
    if r.status_code != 200:
        if r.status_code in (401, 403, 429):
            return None  # never bypass access restrictions
        return get_soup_headless(url, timeout=timeout)

    if not r.encoding or r.encoding == "ISO-8859-1":
        r.encoding = r.apparent_encoding
    text = r.text
    if not isinstance(text, str) or "\x00" in text:
        return None
    soup = BeautifulSoup(text, "html.parser")
    diag_event("parsed", url)

    # Only launch the browser when the plain HTML does not already carry events.
    if USE_HEADLESS and looks_js_rendered_html(text) and not plain_html_has_event_data(soup, url):
        rendered = get_soup_headless(url, timeout=timeout)
        if rendered:
            return rendered

    SOUP_HTML_CACHE[cache_key] = text
    return soup



def normalise_date(date_text, reference=None):
    """Return YYYY-MM-DD for the first real date in the text, else ''.

    v3: validates ISO dates (2026-02-30 is rejected), handles UK day-first
    numeric dates (31/12/2026, 31.12.26), '31 December 2026', 'December 31,
    2026', epoch timestamps, and yearless dates such as 'Fri 16 Oct' using the
    weekday to resolve December/January rollovers.
    """
    raw = clean_text(date_text)
    if not raw:
        return ""
    if re.fullmatch(r"\d{10}|\d{13}", raw):
        try:
            from datetime import timezone as _tz
            ts = int(raw) / (1000 if len(raw) == 13 else 1)
            d = datetime.fromtimestamp(ts, _tz.utc).date()
            if 2000 <= d.year <= 2100:
                return d.strftime("%Y-%m-%d")
        except Exception:
            pass
        return ""
    text = raw.replace("–", "-").replace("—", "-")
    iso = re.search(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", text)
    if iso:
        d = _safe_date(*iso.groups())
        if d:
            return d.strftime("%Y-%m-%d")
    found = find_dates_in_text(text, reference=reference or window_start())
    if not found:
        return ""
    explicit = [d for _, d, has_year in found if has_year]
    chosen = explicit[0] if explicit else found[0][1]
    return chosen.strftime("%Y-%m-%d")



def extract_date_from_text(text):
    """Shared date extractor for every venue/parser.

    Handles ISO dates, full UK dates, and short ticket-listing dates like
    "Sat 4 Jul" by delegating to normalise_date(). This generalises the
    Just The Tonic date behaviour to all venue scrapers.
    """
    return normalise_date(text)


def absolute_url(base, href):
    if not href:
        return ""
    return urljoin(base, href.strip())


def strip_tracking_params(url):
    """Remove common tracking query params so repeated URLs cache cleanly."""
    try:
        parsed = urlparse(url)
        keep = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            lk = key.lower()
            if lk.startswith("utm_") or lk in {"fbclid", "gclid", "mc_cid", "mc_eid"}:
                continue
            keep.append((key, value))
        return urlunparse(parsed._replace(query=urlencode(keep, doseq=True)))
    except Exception:
        return url



def normalise_time_label(value):
    value = clean_text(value)
    if not value:
        return ""
    value = value.replace(".", ":")
    value = re.sub(r"\s+", "", value)

    # 24-hour values from JSON-LD / app-state such as 19:00 or 19:00:00
    m24 = re.match(r"^(\d{1,2}):(\d{2})(?::\d{2})?$", value)
    if m24:
        hour = int(m24.group(1))
        minute = m24.group(2)
        suffix = "AM" if hour < 12 else "PM"
        hour12 = hour % 12 or 12
        return f"{hour12}:{minute}{suffix}"

    m = re.match(r"^(\d{1,2})(?::(\d{2}))?([AaPp][Mm])$", value)
    if not m:
        return clean_text(value)
    hour, minute, suffix = m.groups()
    return f"{int(hour)}:{minute or '00'}{suffix.upper()}"


def normalise_time_range_label(start_time, end_time):
    start_label = normalise_time_label(start_time)
    end_label = normalise_time_label(end_time)
    if start_label and end_label:
        return f"{start_label} til {end_label}"
    return start_label or end_label


def extract_time_from_datetime_value(value):
    """Extract a display time from ISO/RFC datetime values without losing AM/PM.

    v3: values carrying a timezone (Z or +01:00) are converted to UK time.
    """
    value = clean_text(value)
    if not value:
        return ""
    parsed = parse_iso_datetime_local(value)
    if parsed:
        return parsed[1]
    m = re.search(r"T(\d{1,2}:\d{2})(?::\d{2})?(?:\.\d+)?(?:Z|[+\-]\d{2}:?\d{2})?", value)
    if m:
        return normalise_time_label(m.group(1))
    return ""



def extract_performance_time(text):
    """Extract show/performance time for website cards.

    Handles Skiddle detail text such as "7:00pm til 8:00pm", plus the
    existing Top Secret/Fixr style "Starts: 7:30PM Doors: 7:00PM" text.
    """
    text = clean_text(text)
    if not text:
        return ""

    # Skiddle detail pages display this as e.g. "7:00pm til 8:00pm".
    range_pattern = re.compile(
        r"\b(\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm))\s*(?:til|till|until|to|\-|–|—)\s*(\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm))\b",
        flags=re.I,
    )
    m = range_pattern.search(text)
    if m:
        return normalise_time_range_label(m.group(1), m.group(2))

    preferred_patterns = [
        r"\b(?:starts?|show\s*time|performance\s*time|on\s*stage|onstage)\s*:?\s*(\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm))\b",
        r"\b(?:start\s*time|start)\s*:?\s*(\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm))\b",
    ]
    for pattern in preferred_patterns:
        m = re.search(pattern, text, flags=re.I)
        if m:
            return normalise_time_label(m.group(1))

    # JSON-LD/app data often contains ISO datetimes. Use these before generic fallback.
    iso_time = extract_time_from_datetime_value(text)
    if iso_time and iso_time != "12:00AM":
        return iso_time

    # Remove obvious door-time phrases before falling back to the first time.
    without_doors = re.sub(r"\bdoors?\s*:?\s*\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm)\b", " ", text, flags=re.I)
    m = re.search(r"\b(\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm))\b", without_doors, flags=re.I)
    if m:
        return normalise_time_label(m.group(1))

    return ""

def tidy_price_label(value):
    value = clean_text(value)
    value = re.sub(r"\s+", " ", value).strip(" |,;:-")
    value = re.sub(r"£\s+", "£", value)
    value = re.sub(r"\bfree\b", "FREE", value, flags=re.I)
    value = re.sub(r"\bconcessions\b", "Concessions", value, flags=re.I)
    value = re.sub(r"\b(?:\+\s*)?(?:bf|booking\s*fee|fees?)\b", "+ booking fee", value, flags=re.I)
    value = re.sub(r"\s*\+\s*booking fee", " + booking fee", value, flags=re.I)
    value = re.sub(r"\s{2,}", " ", value)
    return value


def extract_price_label(text):
    """Extract the clearest public ticket price label for website cards.

    Handles normal price strings and Skiddle-style text that may appear after
    the ticket widget renders, e.g. "tickets from £12.50 + booking fee".
    """
    text = clean_text(text)
    if not text:
        return ""

    pay_what = re.search(r"\bpay\s+what\s+(?:you\s+)?(?:want|can)\b", text, flags=re.I)
    if pay_what:
        return "Pay what you can"

    # Prefer prices near ticket/entry words if the page has multiple unrelated £ values.
    context_pattern = re.compile(
        r"(?:tickets?|entry|price|standard|advance|general\s+admission|from)\s*(?:from)?\s*[:\-–—]?\s*"
        r"((?:£\s*\d+(?:\.\d{1,2})?|FREE)"
        r"(?:\s*(?:\+\s*(?:bf|booking\s*fee|fees?)))?"
        r"(?:\s*(?:-|–|to)\s*£\s*\d+(?:\.\d{1,2})?)?"
        r"(?:\s+Concessions?\s*:?\s*(?:FREE|£\s*\d+(?:\.\d{1,2})?))?)",
        flags=re.I,
    )
    m = context_pattern.search(text)
    if m:
        return tidy_price_label(m.group(1))

    # Examples: £1, From £12, £12.50, £10 Concessions: £7, £1 Concessions: FREE, £16.50 +bf
    price_pattern = re.compile(
        r"((?:from\s*)?£\s*\d+(?:\.\d{1,2})?"
        r"(?:\s*(?:\+\s*(?:bf|booking\s*fee|fees?)))?"
        r"(?:\s*(?:-|–|to)\s*£\s*\d+(?:\.\d{1,2})?)?"
        r"(?:\s+Concessions?\s*:?\s*(?:FREE|£\s*\d+(?:\.\d{1,2})?))?)",
        flags=re.I,
    )
    prices = []
    seen = set()
    for match in price_pattern.finditer(text):
        value = tidy_price_label(match.group(1))
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            prices.append(value)
        if len(prices) >= 2:
            break

    if prices:
        return " / ".join(prices)

    if re.search(r"\bfree\b", text, flags=re.I):
        return "FREE"

    return ""


def is_skiddle_detail_url(url):
    return is_skiddle_event_url(url)


def extract_extra_text_from_scripts(soup, max_chars=350000):
    """Grab useful app-state text for prices/times that sit inside JS/JSON."""
    if not soup:
        return ""
    parts = []
    total = 0
    for script in soup.find_all("script"):
        raw = script.string or script.get_text() or ""
        if not raw:
            continue
        raw_l = raw.lower()
        if not any(k in raw_l for k in ["£", "price", "ticket", "startdate", "starttime", "event"]):
            continue
        snippet = raw[:60000]
        parts.append(snippet)
        total += len(snippet)
        if total >= max_chars:
            break
    return clean_text(" ".join(parts))


def scrape_skiddle_detail_fields(detail_url):
    """Fetch a Skiddle event detail page and pull time/price from rendered text.

    Price is sometimes injected after page load, so this benefits from running
    the scraper with --headless --headless-wait 3000 or higher.
    """
    detail_url = strip_tracking_params(clean_text(detail_url))
    if not is_skiddle_detail_url(detail_url):
        return {}
    cache_key = detail_url.lower()
    if cache_key in SKIDDLE_DETAIL_CACHE:
        return SKIDDLE_DETAIL_CACHE[cache_key]

    soup = get_soup(detail_url, timeout=20)
    if not soup:
        SKIDDLE_DETAIL_CACHE[cache_key] = {}
        return {}

    visible_text = clean_text(soup.get_text(" ", strip=True))
    script_text = extract_extra_text_from_scripts(soup)
    combined = clean_text(f"{visible_text} {script_text}")

    out = {
        "time": extract_performance_time(combined),
        "price": extract_price_label(combined),
    }

    # If JSON-LD/app state contains an ISO datetime, use it as a backup.
    if not out["time"]:
        for script in soup.find_all("script", type="application/ld+json"):
            raw = script.string or script.get_text() or ""
            try:
                data = json.loads(raw)
            except Exception:
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict):
                    start_value = clean_text(item.get("startDate", ""))
                    out["time"] = extract_time_from_datetime_value(start_value)
                    if out["time"]:
                        break
            if out["time"]:
                break

    SKIDDLE_DETAIL_CACHE[cache_key] = {k: v for k, v in out.items() if v}
    return SKIDDLE_DETAIL_CACHE[cache_key]


def enrich_skiddle_event(event):
    """Add Skiddle detail-page time/price without changing title/date/venue."""
    if not event or clean_text(event.get("source_type", "")).lower() != "skiddle":
        return event
    detail_url = clean_text(event.get("ticket_url", "")) or clean_text(event.get("source", ""))
    detail = scrape_skiddle_detail_fields(detail_url)
    if detail.get("time"):
        event["time"] = detail["time"]
    if detail.get("price"):
        event["price"] = detail["price"]
    return event

def make_event(title, date, venue, city, description, ticket_url, image, source, source_type):
    event = {
        "title": clean_text(title),
        "date": clean_text(date),
        "time": extract_performance_time(f"{title} {description} {ticket_url} {source}"),
        "price": extract_price_label(f"{title} {description} {ticket_url} {source}"),
        "end_date": "",
        "venue": clean_text(venue),
        "city": clean_text(city),
        "state": "",
        "description": clean_text(description),
        "ticket_url": clean_text(ticket_url),
        "image": clean_text(image),
        "source": clean_text(source),
        "source_type": clean_text(source_type),
        "confidence": 0,
    }
    event["confidence"] = confidence_score(event)
    # v3: internal context (underscore keys are never written to events.csv/shows.json)
    v = CURRENT_VENUE or {}
    if v:
        event["_venue_confidence"] = v.get("venue_confidence", "")
        event["_venue_category"] = v.get("category", "")
        event["_venue_title"] = v.get("title", "")
        event["_venue_city"] = v.get("city", "")
        event["_venue_website"] = v.get("website", "")
        override = popular_override_value(v.get("popular", ""))
        if override is not None:
            event["_popular_override"] = override
    note_description(event["description"])
    diag_event("candidate", event=event)
    return event



def confidence_score(event):
    score = 0
    if event.get("title"):
        score += 2
    if event.get("date"):
        score += 3
    if event.get("venue"):
        score += 1
    if event.get("city"):
        score += 1
    if event.get("ticket_url"):
        score += 2
    if event.get("image"):
        score += 1
    if event.get("description") and len(event["description"]) > 60:
        score += 1
    if event.get("source_type") in TRUSTED_SOURCE_TYPES:
        score += 2
    return score


def dedupe_events(events):
    """Layered de-duplication (v3).

    Merges records of the same performance from different sources (matching
    ticket URLs, canonical ticket IDs, normalised title + date + venue/city + time), keeps separate
    dates, cities and performance times apart, never merges on title alone, and
    keeps the best metadata from each merged record.
    """
    return layered_dedupe(events)



def row_value(row, *keys):
    for key in keys:
        if row.get(key):
            return clean_text(row.get(key))
    return ""


def load_venues(csv_file):
    venues = []

    for row in read_venue_rows(csv_file):
        title = row_value(row, "title", "Title", "name", "Name")
        city = row_value(row, "city", "City")
        state = row_value(row, "state", "State", "region", "Region")
        state = normalise_region_name(state) or infer_region_from_city(city)
        website = row_value(row, "website", "Website")
        url = row_value(row, "url", "URL")
        street = row_value(row, "street", "Street")
        confidence = row_value(row, "confidence", "Confidence")
        event_path = row_value(row, "event_path", "eventPath", "path")
        crawl_type = row_value(row, "crawl_type", "crawlType")
        category = row_value(row, "categoryName", "category", "Category", "categories_all")
        popular = row_value(row, "popular", "Popular")
        enabled = row_value(row, "enabled", "Enabled") or "1"

        if enabled.lower() in {"0", "false", "no"}:
            continue

        source_url = website or url
        if not source_url:
            continue

        source_url = source_url.strip()

        if looks_like_junk_url_value(source_url):
            continue

        if source_url.startswith("https://www.google.com/maps/search/"):
            continue

        if source_url and not source_url.startswith("http"):
            source_url = "https://" + source_url

        source_url = strip_tracking_params(source_url)

        if not is_valid_source_url(source_url):
            continue

        if any(b in source_url.lower() for b in BLOCKED_DOMAINS):
            continue

        venues.append({
            "title": title,
            "city": city,
            "state": state,
            "street": street,
            "website": source_url,
            "event_path": event_path,
            "crawl_type": crawl_type.lower(),
            "venue_confidence": confidence,
            "category": category,
            "popular": popular,
        })

    return venues



def find_event_page(base, forced_path=""):
    """Best listing page for a site (v3: relevance-ranked discovery, not first guessed path)."""
    for page in discover_event_pages(base, forced_path, max_pages=1):
        if canonical_event_url(page) != canonical_event_url(base):
            return page
    return base



def is_high_confidence_venue(venue):
    """Only crawl extra pages for venues we trust, to avoid scraping too broadly."""
    confidence = clean_text(venue.get("venue_confidence", "")).lower()
    crawl_type = clean_text(venue.get("crawl_type", "")).lower()
    website = clean_text(venue.get("website", "")).lower()

    if crawl_type in {"wix", "embed", "creatures", "high", "trusted"}:
        return True
    if "creaturescomedy.com" in website:
        return True
    if "high" in confidence or "explicit comedy" in confidence:
        return True
    return False


def discover_event_pages(base_url, forced_path="", max_pages=None):
    """Return a small, ranked, same-domain list of likely event listing pages (v3).

    1. Read the homepage navigation and score links by label/path ("What's On",
       "All Shows", "Open Mic", "Tour Dates", "Calendar"...), penalising shop,
       contact, blog, hire and similar pages.
    2. Discovered links are probed before guessed EVENT_PATHS; guesses are only
       tried when nothing good was discovered.
    3. One extra level: strong sub-listing links on the best listing page
       (e.g. Early Shows, Tour Shows) are added while budget remains.
    The homepage is returned last so it is still scraped. Event detail links
    seen on the way are remembered for the detail-page step.
    """
    if max_pages is None:
        max_pages = discovery_budget(CURRENT_VENUE)["pages"]
    candidates = {}

    def add(url, score):
        if not url:
            return
        full = absolute_url(base_url, url).split("#")[0]
        p = urlparse(full)
        if p.scheme not in {"http", "https"} or not _same_site(full, base_url):
            return
        key = canonical_event_url(full)
        if key == canonical_event_url(base_url):
            return
        if key not in candidates or candidates[key][0] < score:
            candidates[key] = (score, full)

    if forced_path:
        add(absolute_url(base_url, forced_path), 100)
    v = CURRENT_VENUE or {}
    for known in known_listing_pages_for_venue(v.get("title", ""), v.get("city", ""), base_url):
        if _same_site(known, base_url):
            add(known, 90)

    soup = get_soup(base_url, timeout=15)
    if soup:
        details = DISCOVERED_DETAIL_LINKS.setdefault(canonical_event_url(base_url), [])
        for a in soup.select("a[href]"):
            href = a.get("href") or ""
            full = absolute_url(base_url, href).split("#")[0]
            if is_event_detail_url(full, base_url):
                details.append(full)
                continue
            label = clean_text(a.get_text(" ", strip=True)) or clean_text(a.get("aria-label", "")) or clean_text(a.get("title", ""))
            score = score_listing_link(full, label)
            if score > 0:
                add(full, score)

    live = []
    strong_found = False

    def probe(items):
        nonlocal strong_found
        for score, url in items:
            if len(live) >= max_pages:
                return
            if safe_get(url, timeout=8):
                live.append(url)
                diag_event("listing", url)
                if score >= 6:
                    strong_found = True

    probe(sorted(candidates.values(), key=lambda x: -x[0]))

    # Depth 2: sub-listings linked from the best listing page.
    if live and len(live) < max_pages:
        top = get_soup(live[0], timeout=15)
        if top:
            extra = {}
            for a in top.select("a[href]"):
                full = absolute_url(live[0], a.get("href") or "").split("#")[0]
                if not _same_site(full, base_url) or is_event_detail_url(full, base_url):
                    continue
                key = canonical_event_url(full)
                if key in candidates or key == canonical_event_url(base_url):
                    continue
                score = score_listing_link(full, clean_text(a.get_text(" ", strip=True)))
                if score >= 6:
                    extra[key] = (score - 1, full)
            candidates.update(extra)
            probe(sorted(extra.values(), key=lambda x: -x[0]))

    # Guessed paths only when navigation gave us nothing convincing.
    if not strong_found and len(live) < max_pages:
        guessed = []
        for path in EVENT_PATHS:
            full = absolute_url(base_url, path)
            key = canonical_event_url(full)
            if key not in candidates:
                guessed.append((GUESSED_PATH_SCORE, full))
                candidates[key] = (GUESSED_PATH_SCORE, full)
        probe(guessed)

    pages = dedupe_ordered(live + [base_url])
    return pages



def limit_events(events, limit=None):
    """Keep venue output bounded (v3).

    Relevant events inside the date window come first, nearest dates first and
    higher-quality records preferred on the same date. Past events, events after
    --end-date and undated rows are dropped (and counted in diagnostics). The
    cap (MAX_EVENTS_PER_VENUE / --max-events-per-venue) is only a safety net.
    """
    limit = MAX_EVENTS_PER_VENUE if limit is None else limit
    kept = []
    for e in dedupe_events(events):
        if not is_relevant_comedy_event(e):
            continue
        status = date_window_status(e.get("date", ""))
        if status == "invalid":
            diag_event("undated", event=e)
            continue
        if status != "ok":
            diag_event("date_excluded", detail=status, event=e)
            continue
        kept.append(e)
    kept.sort(key=lambda e: (e.get("date", ""), -event_quality(e)))
    if len(kept) > limit:
        diag_event("cap", detail=f"kept {limit} of {len(kept)} in-window events")
    return kept[:limit]



def extract_jsonld_events(soup, source_url, venue_name, city, source_type):
    events = []

    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        raw = clean_text(raw)
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except Exception:
            continue

        items = data if isinstance(data, list) else [data]
        # v3: look inside @graph and ItemList, and accept ComedyEvent /
        # TheaterEvent / ["Event", ...] types rather than only "Event".
        flat = []
        for it in items:
            if isinstance(it, dict) and isinstance(it.get("@graph"), list):
                flat.extend(it["@graph"])
            elif isinstance(it, dict) and isinstance(it.get("itemListElement"), list):
                for el in it["itemListElement"]:
                    flat.append(el.get("item", el) if isinstance(el, dict) else el)
            else:
                flat.append(it)

        for item in flat:
            if not isinstance(item, dict):
                continue

            item_type = item.get("@type")
            type_list = item_type if isinstance(item_type, list) else [item_type]
            if not any(isinstance(t, str) and t.endswith("Event") for t in type_list):
                continue

            status = clean_text(item.get("eventStatus", "")).lower()
            if "cancelled" in status or "postponed" in status:
                continue

            title = clean_text(item.get("name", ""))
            description = clean_text(item.get("description", ""))
            start_raw = clean_text(item.get("startDate", ""))
            local = parse_iso_datetime_local(start_raw)
            date = local[0] if local else normalise_date(start_raw)
            end_raw = clean_text(item.get("endDate", ""))
            if date and end_raw:
                end_local = parse_iso_datetime_local(end_raw)
                end_date = parse_iso_date(end_local[0] if end_local else normalise_date(end_raw))
                start_date = parse_iso_date(date)
                if end_date and start_date and (end_date - start_date).days > LONG_RUNNING_DAYS:
                    diag_event("long_running")
                    continue

            ticket_url = clean_text(item.get("url", "")) or url_from_json(item.get("offers", ""), "") or source_url
            ticket_url = absolute_url(source_url, ticket_url)

            loc = item.get("location", {})
            if isinstance(loc, list):
                loc = loc[0] if loc else {}
            event_venue = venue_name
            event_city = city

            if isinstance(loc, dict):
                loc_name = clean_text(loc.get("name", ""))
                addr = loc.get("address", {})
                if isinstance(addr, dict):
                    event_city = clean_text(addr.get("addressLocality", "")) or city
                elif isinstance(addr, str):
                    event_city = parse_address_line(addr).get("city") or city
                own_site = _same_site(source_url, (CURRENT_VENUE or {}).get("website", "")) if CURRENT_VENUE else False
                if loc_name:
                    event_venue = compose_venue_name(venue_name, loc_name) if own_site else loc_name

            image = image_from_json(item.get("image", ""))
            image = absolute_url(source_url, image) if image else extract_meta_image(soup, source_url)

            if not title:
                continue
            # "Title || Venue" (Skiddle style): keep the show title only
            if "||" in title:
                head, _, tail = title.partition("||")
                loc_label = clean_text(loc.get("name", "")) if isinstance(loc, dict) else ""
                if clean_text(head) and (not loc_label or loc_label.lower() in tail.lower() or venue_name.lower() in tail.lower()):
                    title = clean_text(head)

            if not (is_comedy(title + " " + description) or "event" in source_url.lower()
                    or venue_tier(CURRENT_VENUE) in {"trusted", "high"}):
                continue

            e = make_event(title, date, event_venue, event_city, description, ticket_url, image, source_url, source_type)
            e["_extraction"] = "jsonld"
            if local and local[1] and local[1] != "12:00AM":
                e["time"] = local[1]
            offers = item.get("offers")
            offer = offers[0] if isinstance(offers, list) and offers else offers
            if isinstance(offer, dict) and offer.get("price") not in (None, ""):
                try:
                    amount = float(offer.get("price"))
                    e["price"] = "FREE" if amount == 0 else f"£{amount:.2f}".replace(".00", "")
                except (TypeError, ValueError):
                    pass
            if e["confidence"] >= 5:
                events.append(e)

    return events




def json_get(obj, *keys):
    if not isinstance(obj, dict):
        return ""
    for key in keys:
        if key in obj and obj.get(key) not in (None, ""):
            return obj.get(key)
    return ""


def json_to_text(value):
    if isinstance(value, (str, int, float)):
        return clean_text(value)
    if isinstance(value, list):
        return clean_text(" ".join(json_to_text(v) for v in value[:8]))
    if isinstance(value, dict):
        return clean_text(" ".join(json_to_text(value.get(k, "")) for k in ["name", "title", "description", "summary", "plainText"]))
    return ""


def image_from_json(value):
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, list):
        for item in value:
            img = image_from_json(item)
            if img:
                return img
    if isinstance(value, dict):
        for key in ("url", "src", "assetUrl", "uri", "contentUrl"):
            if value.get(key):
                return clean_text(value.get(key))
    return ""


def url_from_json(value, fallback=""):
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, dict):
        for key in ("url", "href", "ticketUrl", "externalUrl", "link", "permalink"):
            if value.get(key):
                return clean_text(value.get(key))
    if isinstance(value, list):
        for item in value:
            found = url_from_json(item, "")
            if found:
                return found
    return fallback


def json_event_from_obj(obj, source_url, venue_name, city, source_type):
    if not isinstance(obj, dict):
        return None

    type_value = obj.get("@type") or obj.get("type") or obj.get("contentType") or obj.get("itemType") or ""
    if isinstance(type_value, list):
        type_text = " ".join(str(x) for x in type_value).lower()
    else:
        type_text = str(type_value).lower()

    title = json_to_text(json_get(obj, "name", "title", "eventName", "headline", "label"))
    description = json_to_text(json_get(obj, "description", "summary", "excerpt", "body", "plainText"))
    raw_date = json_get(obj, "startDate", "start_date", "date", "datetime", "dateTime", "eventDate", "start", "startTime", "from")
    if not raw_date:
        # v3: nested schedules (e.g. Wix Events scheduling.config.startDate, {"dates": {"start": ...}})
        for outer, inner in (("scheduling", "config"), ("dates", ""), ("schedule", "")):
            node = obj.get(outer) if isinstance(obj, dict) else None
            if isinstance(node, dict) and inner:
                node = node.get(inner)
            if isinstance(node, dict):
                raw_date = json_get(node, "startDate", "start", "startDateTime", "date")
                if raw_date:
                    break
    local_dt = parse_iso_datetime_local(json_to_text(raw_date)) if raw_date else None
    date = local_dt[0] if local_dt else extract_date_from_text(json_to_text(raw_date) or json.dumps(obj, ensure_ascii=False)[:2000])

    # Avoid treating arbitrary config objects as events. They need an event-ish
    # type or at least a plausible title + date pair.
    looks_eventish = (
        "event" in type_text
        or "startdate" in " ".join(obj.keys()).lower()
        or "event" in " ".join(obj.keys()).lower()
        or (title and date and any(k in json.dumps(obj, ensure_ascii=False).lower() for k in ["ticket", "venue", "location", "event"]))
    )
    if not looks_eventish or not title or not date:
        return None

    loc = json_get(obj, "location", "venue", "place")
    event_venue = venue_name
    event_city = city
    if isinstance(loc, dict):
        event_venue = clean_text(loc.get("name") or loc.get("title") or venue_name) or venue_name
        addr = loc.get("address")
        if isinstance(addr, dict):
            event_city = clean_text(addr.get("addressLocality") or addr.get("city") or city) or city
        elif isinstance(addr, str) and not event_city:
            event_city = clean_text(addr)
    elif isinstance(loc, str):
        event_venue = clean_text(loc) or venue_name

    ticket_url = url_from_json(json_get(obj, "offers", "tickets", "ticket", "url", "href", "link", "permalink"), source_url)
    ticket_url = absolute_url(source_url, ticket_url)
    image = image_from_json(json_get(obj, "image", "thumbnail", "photo", "asset", "coverImage"))
    image = absolute_url(source_url, image) if image else ""

    e = make_event(title, date, event_venue, event_city, description, ticket_url or source_url, image, source_url, source_type)
    e["_extraction"] = "pagejson"
    if local_dt and local_dt[1] and local_dt[1] != "12:00AM":
        e["time"] = local_dt[1]
    return e if e["confidence"] >= 5 else None


def walk_json_events(data, source_url, venue_name, city, source_type, max_events=250):
    events = []
    seen_ids = set()

    def walk(value):
        if len(events) >= max_events:
            return
        if isinstance(value, dict):
            event = json_event_from_obj(value, source_url, venue_name, city, source_type)
            if event:
                key = (event.get("title"), event.get("date"), event.get("ticket_url"))
                if key not in seen_ids:
                    seen_ids.add(key)
                    events.append(event)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(data)
    return events


def extract_balanced_json_candidates(text_value, max_candidates=8):
    candidates = []
    text_value = text_value.strip()
    if not text_value:
        return candidates
    if text_value[0] in "[{":
        candidates.append(text_value)

    # Common page-data assignments: window.__INITIAL_STATE__ = {...};
    for pattern in [r"__NEXT_DATA__[^>]*>([\s\S]*?)</script>", r"=\s*({[\s\S]{50,}})\s*;?\s*$"]:
        m = re.search(pattern, text_value, re.I)
        if m:
            candidates.append(m.group(1))

    # Fallback: collect the first few balanced object/list chunks. This helps
    # Squarespace/Wix/React scripts where useful event data is inside page JSON.
    for opener, closer in [("{", "}"), ("[", "]")]:
        starts = [m.start() for m in re.finditer(re.escape(opener), text_value)]
        for start in starts[:30]:
            depth = 0
            in_str = False
            esc = False
            for i in range(start, min(len(text_value), start + 750000)):
                ch = text_value[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                else:
                    if ch == '"':
                        in_str = True
                    elif ch == opener:
                        depth += 1
                    elif ch == closer:
                        depth -= 1
                        if depth == 0:
                            chunk = text_value[start:i+1]
                            if len(chunk) > 40:
                                candidates.append(chunk)
                            break
            if len(candidates) >= max_candidates:
                return candidates[:max_candidates]
    return candidates[:max_candidates]


def parse_jsonish_payloads(raw):
    payloads = []
    raw = html.unescape(raw or "").strip()
    if not raw:
        return payloads
    raw = re.sub(r"^\s*<!--|-->\s*$", "", raw).strip()
    for candidate in extract_balanced_json_candidates(raw):
        candidate = candidate.strip().rstrip(";")
        try:
            payloads.append(json.loads(candidate))
            continue
        except Exception:
            pass
        # Some embedded payloads escape slashes/quotes once.
        # Do this narrowly instead of using .decode("unicode_escape"), because
        # random page JSON/JS can contain regex escapes like \S which trigger
        # DeprecationWarning/invalid-escape noise in newer Python versions.
        try:
            lightly_unescaped = (
                candidate
                .replace('\\/', '/')
                .replace('\\"', '"')
                .replace("\\'", "'")
            )
            if lightly_unescaped != candidate:
                payloads.append(json.loads(lightly_unescaped))
        except Exception:
            pass
    return payloads


def extract_page_json_events(soup, source_url, venue_name, city, source_type="sitejson"):
    """Extract event-like objects from page JSON beyond normal JSON-LD.

    This is useful for Squarespace, Wix, React/Next pages and provider widgets
    that put event cards into application/json or JS state instead of plain HTML.
    """
    events = []
    if not soup:
        return events

    for script in soup.find_all("script"):
        raw = script.string or script.get_text() or ""
        if not raw or len(raw) > 2000000:
            continue
        raw_l = raw.lower()
        script_type = (script.get("type") or "").lower()
        interesting = (
            "json" in script_type
            or "startdate" in raw_l
            or "event" in raw_l
            or "squarespace" in raw_l
            or "wix" in raw_l
            or "ticket" in raw_l
        )
        if not interesting:
            continue
        for payload in parse_jsonish_payloads(raw):
            events.extend(walk_json_events(payload, source_url, venue_name, city, source_type))

    return dedupe_events(events)


def extract_embedded_iframe_links(soup, source_url):
    links = set()

    for iframe in soup.select("iframe[src], iframe[data-src]"):
        src = iframe.get("src") or iframe.get("data-src") or ""
        full = absolute_url(source_url, src)
        if full:
            links.add(full)

    for iframe in soup.select("iframe[srcdoc]"):
        srcdoc = iframe.get("srcdoc", "")
        inner = BeautifulSoup(srcdoc, "html.parser")
        for a in inner.select("a[href]"):
            full = absolute_url(source_url, a.get("href"))
            if full:
                links.add(full)

    return sorted(links)


def extract_ticket_links(soup, source_url):
    links = set()

    for a in soup.select("a[href]"):
        href = absolute_url(source_url, a.get("href"))
        if not href:
            continue
        lower = href.lower()
        if any(domain in lower for domain in TICKET_DOMAINS):
            links.add(href)

    for link in extract_embedded_iframe_links(soup, source_url):
        lower = link.lower()
        if any(domain in lower for domain in TICKET_DOMAINS):
            links.add(link)

    return sorted(links)


def extract_generic_events(soup, source_url, venue_name, city, source_type="site"):
    events = []
    blocks = soup.select("article, li, .event, .event-card, .card, section, div")
    seen = set()

    for block in blocks:
        text = clean_text(block.get_text(" ", strip=True))
        if len(text) < 40:
            continue

        key = text[:250].lower()
        if key in seen:
            continue
        seen.add(key)

        if not is_comedy(text):
            continue

        title = ""
        for sel in ["h1", "h2", "h3", "h4", ".title", ".event-title", "strong", "a"]:
            node = block.select_one(sel)
            if node:
                title = clean_text(node.get_text(" ", strip=True))
                if title:
                    break

        if not title:
            continue

        # Shared date parser handles ISO, full dates and short dates like
        # "Sat 4 Jul". This generalises the Just The Tonic date handling.
        date = extract_date_from_text(text)

        first_link = block.select_one("a[href]")
        ticket_url = absolute_url(source_url, first_link.get("href")) if first_link else source_url

        image = find_best_image_in_block(block, source_url, soup)

        e = make_event(title, date, venue_name, city, text, ticket_url, image, source_url, source_type)
        if e["confidence"] >= 5 and is_relevant_comedy_event(e):
            events.append(e)

    return events


def clean_skiddle_listing_title(text, venue_name=""):
    """Turn a Skiddle list-row label into a readable event title."""
    value = clean_text(remove_emoji_and_symbols(text))
    value = re.sub(r"^Show Cancelled\s+", "", value, flags=re.I)
    value = re.sub(r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*\s+\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\w*\s+", "", value, flags=re.I)
    value = re.sub(r"\b18\s*\+\b", "", value, flags=re.I)
    value = re.sub(r"\b(?:buy|get) tickets?\b.*$", "", value, flags=re.I)
    value = re.sub(r"\bwaiting list\b.*$", "", value, flags=re.I)
    value = re.sub(r"\bFrom\s+\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm)\b.*$", "", value, flags=re.I)
    # Remove venue suffixes from labels such as "Title || Creatures Comedy Club".
    value = re.split(r"\s*\|\|\s*", value)[0]
    value = re.split(r"\s+at\s+" + re.escape(clean_text(venue_name)), value, flags=re.I)[0] if venue_name else value
    value = re.sub(r"\s+Creatures\s+(?:Comedy Club|Tour Show)\s*$", "", value, flags=re.I)
    value = re.sub(r"\s+Manchester\s*$", "", value, flags=re.I)
    return clean_text(value.strip(" -–—|,:;"))


def extract_skiddle_listing_events(soup, source_url, venue_name, city):
    """Parse Skiddle venue/search listing rows into individual event rows.

    This avoids treating Skiddle brand/listing pages as events and keeps direct
    event detail URLs for ticket links.
    """
    events = []
    seen = set()
    if not soup:
        return events

    for a in soup.select("a[href]"):
        href = absolute_url(source_url, a.get("href") or "").split("#")[0]
        if not is_skiddle_event_url(href):
            continue

        block = nearest_ancestor_with_date(a, max_depth=10) or a.parent or a
        text = clean_text(block.get_text(" ", strip=True))
        if len(text) < 25:
            text = clean_text(a.get_text(" ", strip=True))

        date = extract_date_from_text(text)
        if not date:
            continue

        title_source = clean_text(a.get_text(" ", strip=True)) or text
        # If the anchor text is only "buy tickets", use the surrounding card text.
        if title_source.lower() in {"buy tickets", "get tickets", "tickets", "waiting list"} or len(title_source) < 8:
            title_source = text

        title = clean_skiddle_listing_title(title_source, venue_name)
        if not title or looks_like_navigation_or_non_event_title(title, href):
            continue

        key = (href.lower(), date, slugify_text(title))
        if key in seen:
            continue
        seen.add(key)

        image = find_best_image_in_block(block, source_url, soup)
        e = make_event(title, date, venue_name, city, text, href, image, source_url, "skiddle")
        e = enrich_skiddle_event(e)
        if e["confidence"] >= 5:
            events.append(e)

    return events


def scrape_skiddle(url, venue_name, city):
    soup = get_soup(url)
    if not soup:
        return []

    events = []
    events.extend(extract_jsonld_events(soup, url, venue_name, city, "skiddle"))
    events.extend(extract_page_json_events(soup, url, venue_name, city, "skiddle"))
    events.extend(extract_skiddle_listing_events(soup, url, venue_name, city))

    # Reject Skiddle brand/venue/search pages that page JSON can expose as pseudo-events.
    events = [e for e in events if not is_skiddle_landing_or_brand_url(e.get("ticket_url", ""))]

    # If this is an individual Skiddle event page, enrich JSON-LD/page-data rows
    # from the rendered detail text before card parsing.
    events = [enrich_skiddle_event(e) for e in events]

    cards = soup.select("article, li, .eventlistitem, .search-result, .MuiCard-root, .vevent")
    for card in cards:
        text = clean_text(card.get_text(" ", strip=True))
        if len(text) < 20:
            continue

        title = ""
        for sel in ["h1", "h2", "h3", "h4", "strong", "a"]:
            node = card.select_one(sel)
            if node:
                title = clean_text(node.get_text(" ", strip=True))
                if title:
                    break

        if not title:
            continue

        # Shared date parser handles ISO, full dates and short dates like
        # "Sat 4 Jul". This generalises the Just The Tonic date handling.
        date = extract_date_from_text(text)

        link = card.select_one("a[href]")
        ticket_url = absolute_url(url, link.get("href")) if link else url
        if is_skiddle_landing_or_brand_url(ticket_url):
            continue
        if "skiddle.com" in ticket_url.lower() and not is_skiddle_event_url(ticket_url):
            continue

        image = find_best_image_in_block(card, url, soup)

        title = clean_skiddle_listing_title(title, venue_name) or title
        if title.lower().strip() == clean_text(city).lower().strip():
            continue

        e = make_event(title, date, venue_name, city, text, ticket_url, image, url, "skiddle")
        e = enrich_skiddle_event(e)
        if e["confidence"] >= 5:
            events.append(e)

    events = [enrich_skiddle_event(e) for e in events]
    events = [e for e in events if not is_skiddle_landing_or_brand_url(e.get("ticket_url", ""))]
    return dedupe_events(events)


def known_skiddle_listing_urls_for_venue(venue_name, city, website=""):
    """Return hand-approved Skiddle venue/listing URLs for known venues.

    These are only used for venues where the official site embeds Skiddle or
    the Skiddle venue page is known to be the best complete listing source.
    The URLs are scraped by the Skiddle parser, so the expensive scroll/show-more
    headless logic stays limited to Skiddle pages.
    """
    context = f"{venue_name} {city} {website}".lower()
    urls = []
    if "creatures" in context and "manchester" in context:
        urls.append("https://www.skiddle.com/whats-on/Manchester/Creatures-Comedy-Club/")
        # v3: the organiser page lists every Creatures brand event (all rooms/series).
        urls.append("https://www.skiddle.com/g/creatures-of-the-night-comedy-club/")
    return dedupe_ordered(urls)



def search_skiddle_for_venue(venue_name, city):
    q = quote_plus(f"{venue_name} {city}".strip())
    search_url = f"https://www.skiddle.com/search/?keyword={q}"
    return scrape_skiddle(search_url, venue_name, city)


def nearest_ancestor_with_date(node, max_depth=8):
    """Return the smallest parent block around a link that contains a parseable date."""
    best = node.parent if node else None
    current = node.parent if node else None
    for _ in range(max_depth):
        if not current:
            break
        text = clean_text(current.get_text(" ", strip=True))
        if text and extract_date_from_text(text):
            return current
        best = current
        current = current.parent
    return best


def fallback_dates_from_lines_for_title(soup, title):
    """Fatsoma organiser pages often render as title line followed by date line."""
    lines = [clean_text(line) for line in soup.get_text("\n").split("\n") if clean_text(line)] if soup else []
    title_low = clean_text(title).lower()
    for i, line in enumerate(lines):
        if clean_text(line).lower() == title_low or title_low in clean_text(line).lower():
            window = " ".join(lines[i:i+8])
            date = extract_date_from_text(window)
            if date:
                return date, window
    return "", ""



def compact_compare_text(value):
    return re.sub(r"[^a-z0-9]+", " ", clean_text(value).lower()).strip()


def find_fatsoma_event_href_for_title(soup, base_url, title):
    """Find the event detail URL matching a visible Fatsoma list title."""
    if not soup or not title:
        return base_url
    target = compact_compare_text(title)
    best = ""
    for a in soup.select("a[href]"):
        href = absolute_url(base_url, a.get("href"))
        if not href or ("/e/" not in href.lower() and "/events/" not in href.lower()):
            continue
        label = compact_compare_text(a.get_text(" ", strip=True))
        if not label:
            continue
        if label == target or target in label or label in target:
            return href
        if not best and target[:45] and target[:45] in label:
            best = href
    return best or base_url


def extract_fatsoma_current_event_rows_from_lines(soup, source_url, venue_name, city):
    """Parse Fatsoma organiser/profile pages from their visible text lines.

    Fatsoma profile pages can be awkward because event links and date text are
    not always wrapped in the same small HTML card. This parser reads the
    Current Events block line-by-line, pairs an event title with the nearest
    following date/location, and uses the matching /e/ link when present.
    """
    if not soup:
        return []

    raw_lines = [clean_text(x) for x in soup.get_text("\n").split("\n")]
    lines = [x for x in raw_lines if x]
    if not lines:
        return []

    start = 0
    end = len(lines)
    for i, line in enumerate(lines):
        if line.lower() == "current events":
            start = i + 1
            break
    for i in range(start, len(lines)):
        if lines[i].lower() in {"all posts", "about " + clean_text(venue_name).lower()} or lines[i].lower().startswith("about "):
            end = i
            break

    event_lines = lines[start:end]
    events = []
    seen_titles = set()

    month_names = {"january","february","march","april","may","june","july","august","september","october","november","december"}
    skip_titles = {
        "view events", "view posts", "events", "posts", "all", "current events",
        "follow", "become a rep", "loading", "tickets", "ok"
    }

    def looks_like_fatsoma_title(line, idx):
        low = line.lower().strip()
        if not low or low in skip_titles or low in month_names:
            return False
        if low.startswith("£") or "followers" in low or "reps" == low:
            return False
        if extract_date_from_text(line):
            return False
        # A title should have a date shortly after it in the Current Events section.
        window = event_lines[idx + 1: idx + 8]
        if not any(extract_date_from_text(w) for w in window):
            return False
        # Prefer rows with a comedy signal, or rows from a known comedy organiser profile.
        profile_is_comedy = "hifi-comedy-sessions" in source_url.lower() or "comedy" in clean_text(venue_name).lower()
        return has_comedy_title_hint(line) or profile_is_comedy or " comedy" in " ".join(window).lower()

    for i, line in enumerate(event_lines):
        if not looks_like_fatsoma_title(line, i):
            continue
        title = line
        title_key = compact_compare_text(title)
        if title_key in seen_titles:
            continue

        following = event_lines[i + 1: i + 10]
        date = ""
        description_parts = [title]
        event_venue = venue_name
        event_city = city
        for w in following:
            description_parts.append(w)
            if not date:
                date = extract_date_from_text(w)
            low = w.lower()
            if city and city.lower() in low and ("," in w or "club" in low or "venue" in low):
                # Fatsoma often displays "The HiFi Club, Leeds" on the next line.
                event_venue = clean_text(w.split(",")[0]) or venue_name
                event_city = city
        if not date:
            continue

        ticket_url = find_fatsoma_event_href_for_title(soup, source_url, title)
        image = extract_meta_image(soup, source_url)
        e = make_event(title, date, event_venue, event_city, " ".join(description_parts), ticket_url, image, source_url, "fatsoma")
        if e["confidence"] >= 5:
            events.append(e)
            seen_titles.add(title_key)

    return dedupe_events(events)

def scrape_fatsoma(url, venue_name, city):
    soup = get_soup(url)
    if not soup:
        return []

    events = []
    events.extend(extract_jsonld_events(soup, url, venue_name, city, "fatsoma"))
    events.extend(extract_page_json_events(soup, url, venue_name, city, "fatsoma"))
    events.extend(extract_fatsoma_current_event_rows_from_lines(soup, url, venue_name, city))

    for a in soup.select("a[href]"):
        href = absolute_url(url, a.get("href"))
        if not href:
            continue
        if "/events/" not in href.lower() and "/e/" not in href.lower():
            continue

        title = clean_text(a.get_text(" ", strip=True))
        if not title:
            continue

        block = nearest_ancestor_with_date(a, max_depth=10)
        parent_text = clean_text(block.get_text(" ", strip=True)) if block else title
        date = extract_date_from_text(parent_text)

        if not date:
            line_date, line_text = fallback_dates_from_lines_for_title(soup, title)
            date = line_date
            if line_text:
                parent_text = line_text

        image = find_best_image_in_block(block or a.parent, url, soup) if (block or a.parent) else extract_meta_image(soup, url)
        e = make_event(title, date, venue_name, city, parent_text, href, image, url, "fatsoma")
        if e["confidence"] >= 5:
            events.append(e)

    return dedupe_events(events)


def scrape_top_secret(url, venue_name, city, street_hint=""):
    soup = get_soup(url)
    if not soup:
        return []

    events = []

    for item in soup.select("li.event--item"):
        date_text = clean_text(item.select_one(".event-date").get_text(" ", strip=True) if item.select_one(".event-date") else "")
        date = normalise_date(date_text)

        title = clean_text(item.select_one(".event--details h3").get_text(" ", strip=True) if item.select_one(".event--details h3") else "")
        title = re.sub(r"\s+", " ", title).strip()

        venue_link = item.select_one(".event--details .venue a[href]")
        venue_label = clean_text(venue_link.get_text(" ", strip=True) if venue_link else "")
        if not venue_label:
            venue_label = street_hint or venue_name

        desc_parts = [
            clean_text(item.select_one(".event--time").get_text(" ", strip=True) if item.select_one(".event--time") else ""),
            clean_text(item.select_one(".event--price").get_text(" ", strip=True) if item.select_one(".event--price") else ""),
            clean_text(item.select_one(".bucket-message").get_text(" ", strip=True) if item.select_one(".bucket-message") else ""),
        ]
        description = " | ".join([p for p in desc_parts if p])

        ticket_url = ""
        cta_links = item.select(".event--ctas a[href]")
        for a in cta_links:
            href = absolute_url(url, a.get("href"))
            text = clean_text(a.get_text(" ", strip=True)).lower()
            if "fixr.co" in href.lower() or "ticket" in text or "book" in text or "more" in text:
                ticket_url = href
                if "fixr.co" in href.lower():
                    break

        img = item.select_one("img")
        image = absolute_url(url, img.get("src")) if img and img.get("src") else ""

        e = make_event(title, date, venue_label, city, description, ticket_url or url, image, url, "topsecret")
        if e["confidence"] >= 5:
            events.append(e)

    if not events:
        events.extend(scrape_top_secret_text_events(soup, url, venue_name, city, street_hint=street_hint))
        events.extend(extract_jsonld_events(soup, url, venue_name, city, "topsecret"))
        events.extend(extract_page_json_events(soup, url, venue_name, city, "topsecret"))
        events.extend(extract_generic_events(soup, url, venue_name, city, "topsecret"))

    return dedupe_events(events)




def scrape_top_secret_text_events(soup, url, venue_name, city, street_hint=""):
    """Fallback for current Top Secret pages where event rows are exposed as
    visible text/headings rather than the older li.event--item structure."""
    events = []
    if not soup:
        return events

    lines = [clean_text(line) for line in soup.get_text("\n").split("\n") if clean_text(line)]
    current_date = ""
    title_to_line_index = {}

    for i, line in enumerate(lines):
        parsed_date = normalise_date(line)
        if parsed_date and re.search(r"\b\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}\b", line, flags=re.I):
            current_date = parsed_date
            continue
        low = line.lower()
        if current_date and ("starts:" in " ".join(lines[i:i+5]).lower()) and (
            "stand up" in low or "comedy" in low or "laughter" in low or "top secret celebrity guest" in low
        ):
            title_to_line_index.setdefault(line, i)

    for title, i in title_to_line_index.items():
        window_lines = lines[i:i+8]
        description = " | ".join(window_lines[1:6])
        date = current_date
        # Walk backwards to the closest previous date for this specific title.
        for back in range(i, max(-1, i - 12), -1):
            possible = normalise_date(lines[back])
            if possible and re.search(r"\b\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}\b", lines[back], flags=re.I):
                date = possible
                break
        if not date:
            continue

        venue_label = street_hint or venue_name
        if any("23 kingsway" in x.lower() for x in window_lines):
            venue_label = "23 Kingsway"
        elif any("170 drury lane" in x.lower() for x in window_lines):
            venue_label = "170 Drury Lane"

        ticket_url = url
        image = extract_meta_image(soup, url)
        e = make_event(title, date, venue_label, city, description, ticket_url, image, url, "topsecret")
        if e["confidence"] >= 5:
            events.append(e)

    return dedupe_events(events)


def ticket_provider_source_type(url):
    lower = clean_text(url).lower()
    provider_map = [
        ("skiddle.com", "skiddle"),
        ("fatsoma.com", "fatsoma"),
        ("fixr.co", "fixr"),
        ("tickettailor.com", "tickettailor"),
        ("justthetonic.com", "justthetonic"),
        ("eventbrite.", "eventbrite"),
        ("wegottickets.com", "wegottickets"),
        ("seetickets.com", "seetickets"),
        ("ticketmaster.", "ticketmaster"),
        ("spektrix.com", "spektrix"),
        ("dice.fm", "dice"),
        ("universe.com", "universe"),
        ("billetto.", "billetto"),
        ("designmynight.com", "designmynight"),
        ("atgtickets.com", "atgtickets"),
        ("trafalgartickets.com", "trafalgartickets"),
        ("ticketsource.", "ticketsource"),
    ]
    for domain, provider in provider_map:
        if domain in lower:
            return provider
    return "ticketprovider"



def scrape_iframe_src(url, venue_name, city):
    """Scrape an embedded iframe/widget URL.

    This restores the iframe handler used by the Wix/embed and ticket-provider
    code paths. It deliberately reuses the normal provider dispatcher for known
    ticket domains, then falls back to JSON-LD/page JSON/generic card parsing
    for iframe/widget HTML.
    """
    events = []
    lower = clean_text(url).lower()

    # If the iframe itself is a known ticket-provider URL, use the provider
    # scraper directly. This avoids trying to parse provider widgets as plain
    # generic HTML when we have a better parser available.
    if any(domain in lower for domain in TICKET_DOMAINS):
        return scrape_trusted_ticket_source(url, venue_name, city)

    iframe_soup = get_soup(url)
    if not iframe_soup:
        return events

    source_type = ticket_provider_source_type(url) if any(domain in lower for domain in TICKET_DOMAINS) else "iframe"

    events.extend(extract_jsonld_events(iframe_soup, url, venue_name, city, source_type))
    events.extend(extract_page_json_events(iframe_soup, url, venue_name, city, source_type))
    events.extend(extract_generic_events(iframe_soup, url, venue_name, city, source_type))

    # Some widgets embed a second provider URL or expose direct booking links.
    for ticket_url in extract_ticket_links(iframe_soup, url)[:TICKET_LINK_LIMIT]:
        if ticket_url == url:
            continue
        events.extend(scrape_trusted_ticket_source(ticket_url, venue_name, city))

    # Follow one level of nested iframes, capped to avoid runaway crawls.
    for nested_url in extract_embedded_iframe_links(iframe_soup, url)[:2]:
        if nested_url == url:
            continue
        nested_lower = nested_url.lower()
        if any(domain in nested_lower for domain in TICKET_DOMAINS):
            events.extend(scrape_trusted_ticket_source(nested_url, venue_name, city))

    return limit_events(events)

def scrape_generic_ticket_provider(url, venue_name, city):
    url = strip_tracking_params(url).split("#")[0]
    """Directly scrape a ticket-provider page when no dedicated parser exists.

    Many venue sites only embed/link a provider widget. This follows that URL
    and pulls JSON-LD, page JSON, iframe content and any visible event card text.
    """
    provider = ticket_provider_source_type(url)
    soup = get_soup(url)
    if not soup:
        return []

    events = []
    events.extend(extract_jsonld_events(soup, url, venue_name, city, provider))
    events.extend(extract_page_json_events(soup, url, venue_name, city, provider))

    for iframe_url in extract_embedded_iframe_links(soup, url)[:IFRAME_LINK_LIMIT]:
        events.extend(scrape_iframe_src(iframe_url, venue_name, city))

    events.extend(extract_generic_events(soup, url, venue_name, city, provider))
    return limit_events(events)


def scrape_trusted_ticket_source(url, venue_name, city):
    """Dispatch known ticket/source URLs to dedicated or generic scrapers.

    Protocol: add future trusted ticket-source domains to TICKET_DOMAINS,
    TRUSTED_SOURCE_TYPES and ticket_provider_source_type(). If a provider needs
    special parsing, add a dedicated branch here; otherwise the generic provider
    parser follows JSON-LD/page JSON/visible event cards.
    """
    lower = clean_text(url).lower()
    if "skiddle.com" in lower:
        return scrape_skiddle(url, venue_name, city)
    if "fatsoma.com" in lower:
        return scrape_fatsoma(url, venue_name, city)
    if "justthetonic.com" in lower:
        return scrape_just_the_tonic_page(url, venue_name, city)
    if any(domain in lower for domain in TICKET_DOMAINS):
        return scrape_generic_ticket_provider(url, venue_name, city)
    return []


def scrape_wix_or_embed_site(url, venue_name, city, extra_pages=None):
    """Wix/embed sites: every page goes through the full v3 page pipeline
    (JSON-LD, page JSON, cards, iframes, ticket links, JS fallback, pagination,
    detail pages). Same inputs/outputs as before."""
    pages = extra_pages or [url]
    events = []
    for page_url in pages:
        events.extend(scrape_site_page(page_url, venue_name, city))
    return limit_events(events)



def clean_just_the_tonic_title(raw_title, city):
    title = clean_text(raw_title)
    title = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "", title)
    title = re.sub(
        r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*\s+\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*(?:\s+\d{4})?\b",
        "",
        title,
        flags=re.I,
    ).strip()
    city_clean = clean_text(city)
    if city_clean:
        # JTT anchor text can look like: "... Birmingham Birmingham Sat 4 Jul ...".
        # Compress duplicated trailing city names to one, then remove a single
        # trailing city only when the title already contains that city earlier.
        city_re = re.escape(city_clean)
        title = re.sub(rf"(\b{city_re}\b\s*){{2,}}$", city_clean, title, flags=re.I)
        if re.search(rf"\b{city_re}\b$", title, flags=re.I):
            before = re.sub(rf"\b{city_re}\b$", "", title, flags=re.I)
            if re.search(rf"\b{city_re}\b", before, flags=re.I):
                title = before
    return clean_text(title.strip(" -–—|"))


def get_nearest_event_block(anchor):
    """Find the smallest useful JTT listing block around an event link."""
    best = anchor.parent
    node = anchor.parent
    for _ in range(6):
        if not node:
            break
        text = clean_text(node.get_text(" ", strip=True))
        lower = text.lower()
        if len(text) > 40 and ("door" in lower or "starts" in lower or "book/information" in lower):
            return node
        best = node
        node = node.parent
    return best or anchor


def extract_lineup_from_jtt_block(block, main_href, city):
    names = []
    seen = set()
    city_l = clean_text(city).lower()
    bad = {
        "book/information", "book", "information", "june", "july", "august", "all",
        "gift vouchers", "christmas shows", "edinburgh fringe festival", "comedians",
        "corporate enquiries", "group bookings", "contact", "join the mailing list",
    }
    for a in block.select("a"):
        href = a.get("href") or ""
        txt = clean_text(a.get_text(" ", strip=True)).strip()
        low = txt.lower().strip(" :-–—|")
        if not txt or low in bad:
            continue
        if main_href and href == main_href:
            continue
        if "just the tonic" in low:
            continue
        if city_l and low == city_l:
            continue
        if re.search(r"\d{4}-\d{2}-\d{2}", low):
            continue
        if re.search(r"\b(?:mon|tue|wed|thu|fri|sat|sun)\w*\s+\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", low, re.I):
            continue
        key = slugify_text(txt)
        if key and key not in seen:
            seen.add(key)
            names.append(txt)
    return names[:6]


def scrape_just_the_tonic_page(url, venue_name, city):
    """Scrape a Just The Tonic page directly.

    Works for city pages and other JTT listing pages such as Edinburgh Fringe
    pages. The parser uses listing blocks containing title/date/times rather
    than a hard-coded city override.
    """
    soup = get_soup(url)
    if not soup:
        return []

    events = []
    events.extend(extract_jsonld_events(soup, url, venue_name, city, "justthetonic"))
    events.extend(extract_page_json_events(soup, url, venue_name, city, "justthetonic"))

    city_l = clean_text(city).lower()
    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        full_href = absolute_url(url, href)
        href_l = full_href.lower()
        # Just The Tonic navigation links live beside event listings and can inherit
        # dates from the page. Only treat actual show-detail links as event anchors.
        if "/shows/" not in href_l:
            continue
        anchor_text = clean_text(a.get_text(" ", strip=True))
        if not anchor_text:
            continue

        block = get_nearest_event_block(a)
        block_text = clean_text(block.get_text(" ", strip=True)) if block else anchor_text
        combined = f"{anchor_text} {block_text}"
        combined_l = combined.lower()

        if "just the tonic" not in combined_l:
            continue
        date = normalise_date(combined)
        if not date:
            continue

        title = clean_just_the_tonic_title(anchor_text, city)
        if not title or is_generic_bad_title(title):
            continue

        # Ignore navigation/header links such as "Birmingham Comedy Club" which
        # have no listing times around them.
        if not ("door" in combined_l or "starts" in combined_l or "book/information" in combined_l or re.search(r"\d{4}-\d{2}-\d{2}", combined_l)):
            continue

        lineup = extract_lineup_from_jtt_block(block, href, city) if block else []
        if lineup:
            # Prefer the performer line-up over long venue/date/menu text.
            if not any(name.lower() in title.lower() for name in lineup[:2]):
                title = f"{title} - {', '.join(lineup[:4])}"
        title = clean_display_title(title)
        if looks_like_navigation_or_non_event_title(title, full_href):
            continue

        img = block.select_one("img") if block else None
        image = ""
        if img:
            image = absolute_url(url, img.get("src") or img.get("data-src") or "")

        description = block_text
        ticket_url = full_href or url
        e = make_event(title, date, venue_name, city, description, ticket_url, image, url, "justthetonic")
        if e["confidence"] >= 5:
            events.append(e)

    return limit_events(events)

def scrape_site_page(page_url, venue_name, city):
    """Scrape this exact page without re-running /events or /whatson discovery.

    v3: plain HTTP first; structured data and event cards; JS fallback only
    when a calendar clearly failed to load; bounded static pagination that
    stops once a chronological listing passes --end-date; then event detail
    pages for cards that need them.
    """
    budget = discovery_budget(CURRENT_VENUE)
    soup = get_soup(page_url)
    if not soup:
        return []

    events, undated_links = extract_page_events(soup, page_url, venue_name, city, budget)
    raw_html = SOUP_HTML_CACHE.get("plain:" + strip_tracking_params(page_url).lower(), "")
    if calendar_not_loaded(soup, raw_html, events, page_url):
        rendered = get_soup_headless(page_url) if USE_HEADLESS else None
        if rendered is not None:
            more, more_links = extract_page_events(rendered, page_url, venue_name, city, budget)
            events.extend(more)
            undated_links.extend(more_links)
            soup = rendered
        if not events:
            diag_event("js_not_loaded", page_url)

    visited = {canonical_event_url(page_url)}
    page_events = list(events)
    current = soup
    for _ in range(budget["pagination"]):
        dated = [e for e in page_events if e.get("date")]
        end_text = window_end().strftime("%Y-%m-%d")
        if dated and all(e["date"] > end_text for e in dated):
            break
        if page_dates_are_chronological(dated) and dated[-1]["date"] > end_text:
            break
        nxt = [u for u in find_pagination_links(current, page_url) if canonical_event_url(u) not in visited]
        if not nxt:
            break
        next_url = nxt[0]
        visited.add(canonical_event_url(next_url))
        current = get_soup(next_url)
        if not current:
            break
        diag_event("pagination", next_url)
        page_events, more_links = extract_page_events(current, next_url, venue_name, city, budget)
        if not page_events:
            break
        events.extend(page_events)
        undated_links.extend(more_links)

    events = enrich_events_with_details(events, venue_name, city, budget, dedupe_ordered(undated_links))
    return dedupe_events(events)



def scrape_generic_site(base_url, venue_name, city, event_path=""):
    """v3: bounded, relevance-ranked crawl (was: one guessed page)."""
    budget = discovery_budget(CURRENT_VENUE)
    events = []
    for page_url in discover_event_pages(base_url, event_path, max_pages=budget["pages"]):
        events.extend(scrape_site_page(page_url, venue_name, city))
    return dedupe_events(events)



def scrape_hilarity_bites_site_page(url, venue_name, city):
    """Dedicated parser for Hilarity Bites WordPress/Event Calendar pages."""
    soup = get_soup(url)
    if not soup:
        return []

    events = []
    blocks = soup.select(
        ".tribe-events-calendar-list__event, .type-tribe_events, article, .hentry, .event"
    )
    seen = set()

    for block in blocks:
        text = clean_text(block.get_text(" ", strip=True))
        if len(text) < 50:
            continue
        if "hilarity bites" not in text.lower() and not is_comedy(text):
            continue

        date = extract_date_from_text(text)
        if not date:
            continue

        title = ""
        link_url = url
        for sel in [
            ".tribe-events-calendar-list__event-title a",
            ".entry-title a",
            "h1 a", "h2 a", "h3 a", "h2", "h3"
        ]:
            node = block.select_one(sel)
            if not node:
                continue
            title = clean_text(node.get_text(" ", strip=True))
            if node.name == "a" and node.get("href"):
                link_url = absolute_url(url, node.get("href"))
            elif node.find("a", href=True):
                link_url = absolute_url(url, node.find("a", href=True).get("href"))
            if title and not looks_like_date_only_title(title):
                break

        # The list title can be "Ripon, June 2nd 2026"; enrich it from the body
        # so the website card is useful.
        if not title or re.match(r"^[A-Za-z .'-]+,\s+[A-Za-z]+\s+\d{1,2}", title):
            m = re.search(r"Hilarity\s+Bites\s+(?:returns|comes)\s+to\s+(.+?)(?:,|\s+with|\s+featuring)", text, flags=re.I)
            if m:
                title = f"Hilarity Bites - {clean_text(m.group(1))}"
            else:
                # Fall back to the location/date label; it is still better than a blank row.
                title = clean_text(title) or "Hilarity Bites Comedy Club"

        price = extract_price_label(text)
        event_venue = venue_name or "Hilarity Bites Comedy Club"
        # Pull the specific venue name if available in The Events Calendar text.
        venue_node = block.select_one(".tribe-events-calendar-list__event-venue-title, .tribe-events-venue-details a")
        if venue_node:
            event_venue = clean_text(venue_node.get_text(" ", strip=True)) or event_venue

        key = (slugify_text(title), date, slugify_text(link_url))
        if key in seen:
            continue
        seen.add(key)

        image = find_best_image_in_block(block, url, soup)
        e = make_event(title, date, event_venue, city, text, link_url, image, url, "hilaritybites")
        if price:
            e["price"] = price
        if e["confidence"] >= 5:
            events.append(e)

    return dedupe_events(events)


def scrape_hilarity_bites(website, venue_name, city):
    """Scrape Hilarity Bites from its site plus the Universe organiser profile.

    The Hilarity Bites site is useful for titles/dates, but its /shows/ links can
    be index-style URLs. Universe is the stronger ticket source for buy links.
    """
    events = []
    # First use the supplied site and likely /shows/ page for descriptions/dates.
    for page_url in dedupe_ordered([website, absolute_url(website, "/shows/")]):
        events.extend(scrape_hilarity_bites_site_page(page_url, venue_name, city))
        events.extend(scrape_site_page(page_url, venue_name, city))

    # Then pull the ticket provider profile explicitly so direct ticket links win.
    for universe_url in HILARITY_BITES_UNIVERSE_URLS:
        events.extend(scrape_trusted_ticket_source(universe_url, venue_name, city))

    # Prefer Universe ticket URLs where duplicate title/date rows exist.
    by_key = {}
    for e in events:
        key = (slugify_text(e.get("title", "")), e.get("date", ""), slugify_text(e.get("city", city)))
        if not key[0] or not key[1]:
            continue
        old = by_key.get(key)
        if not old:
            by_key[key] = e
            continue
        old_ticket = clean_text(old.get("ticket_url", "")).lower()
        new_ticket = clean_text(e.get("ticket_url", "")).lower()
        if "universe.com" in new_ticket and "universe.com" not in old_ticket:
            by_key[key] = e
        elif int(e.get("confidence", 0) or 0) > int(old.get("confidence", 0) or 0):
            by_key[key] = e
    return list(by_key.values()) or events


def dedupe_ordered(values):
    out = []
    seen = set()
    for value in values:
        value = clean_text(value)
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def scrape_venue(venue):
    global CURRENT_VENUE
    CURRENT_VENUE = venue
    VENUE_FETCH_BUDGET_USED.clear()
    website = venue["website"]
    venue_name = venue["title"]
    city = venue["city"]
    street = venue.get("street", "")
    crawl_type = venue.get("crawl_type", "")

    url_lower = website.lower()
    events = []

    if crawl_type == "topsecret" or "thetopsecretcomedyclub.co.uk" in url_lower:
        events.extend(scrape_top_secret(website, venue_name, city, street_hint=street))

    elif "hilaritybites.co.uk" in url_lower or "hilarity bites" in venue_name.lower():
        events.extend(scrape_hilarity_bites(website, venue_name, city))

    elif "justthetonic.com" in url_lower:
        # Dedicated trusted-source parser. No venue URL override is used: this
        # scrapes the URL provided in venues.csv. Edinburgh/festival JTT shows
        # are included when those JTT URLs exist as their own venue rows, rather
        # than being accidentally imported into a different city's page.
        events.extend(scrape_just_the_tonic_page(website, venue_name, city))

    elif crawl_type in {"wix", "embed", "creatures"} or "creaturescomedy.com" in url_lower:
        # Wix/embed sites often hide events inside widgets, iframes, or a
        # separate What's On page. v3: ranked discovery plus hand-approved
        # listing pages; every page goes through the full page pipeline.
        if is_high_confidence_venue(venue):
            pages = discover_event_pages(website, venue.get("event_path", ""))
        else:
            pages = [website]
        events.extend(scrape_wix_or_embed_site(website, venue_name, city, extra_pages=pages))
        for skiddle_url in known_skiddle_listing_urls_for_venue(venue_name, city, website):
            events.extend(scrape_skiddle(skiddle_url, venue_name, city))

    elif crawl_type == "skiddle" or "skiddle.com" in url_lower:
        events.extend(scrape_skiddle(website, venue_name, city))

    elif crawl_type == "fatsoma" or "fatsoma.com" in url_lower:
        events.extend(scrape_fatsoma(website, venue_name, city))

    elif any(domain in url_lower for domain in TICKET_DOMAINS):
        # Direct ticket-provider URL in venues.csv. Scrape the provider page
        # itself rather than relying on the venue page embed.
        events.extend(scrape_trusted_ticket_source(website, venue_name, city))

    else:
        if is_high_confidence_venue(venue):
            for page_url in discover_event_pages(website, venue.get("event_path", "")):
                events.extend(scrape_site_page(page_url, venue_name, city))
        else:
            events.extend(scrape_generic_site(website, venue_name, city, venue.get("event_path", "")))

    # The HiFi website links to Fatsoma, and Fatsoma also has a dedicated comedy
    # organiser profile. Pull both profiles explicitly so the Leeds comedy rows are
    # not missed when the venue homepage only exposes old/static listings.
    venue_city_context = f"{venue_name} {city}".lower()
    if "hifi" in venue_city_context and "leeds" in venue_city_context:
        events.extend(scrape_fatsoma("https://www.fatsoma.com/p/hifi-club-leeds", venue_name, city))
        events.extend(scrape_fatsoma("https://www.fatsoma.com/p/hifi-comedy-sessions", venue_name, city))

    if not SKIP_SKIDDLE_SEARCH:
        events.extend(search_skiddle_for_venue(venue_name, city))

    # v3: only inherit the venue's region when the event is in the venue's own
    # town. Touring/multi-location organisers (e.g. Breakneck) keep the town on
    # each listing, and unknown regions are flagged instead of guessed.
    state = normalise_region_name(venue.get("state", "")) or infer_region_from_city(city)
    for event in events:
        if event.get("state"):
            continue
        event_city = clean_text(event.get("city", ""))
        if not event_city:
            event["city"] = city
            event["state"] = state
        elif same_place(event_city, city):
            event["state"] = state
        else:
            region = infer_region_from_city(event_city)
            event["state"] = region
            if not region:
                flag = f"region unknown for town '{event_city}'"
                event["_location_flag"] = event.get("_location_flag") or flag
                diag_event("location", detail=flag, event=event)

    events = layered_dedupe(events, record_stats=True)
    return limit_events(events)



SITE_OUTPUT_FIELDS = ["city", "state", "comedian", "venue", "date", "time", "price", "tickets", "type", "image", "featured"]
DEFAULT_SITE_IMAGE = "/images/default-comedy.jpg"


def clean_site_image(image):
    image = clean_text(image)
    if not image or bad_event_image_url(image):
        return DEFAULT_SITE_IMAGE
    if image.startswith("http") or image.startswith("data:image"):
        return image
    match = re.search(r"https?://[^'\"} ]+", image)
    if match and not bad_event_image_url(match.group(0)):
        return match.group(0)
    return DEFAULT_SITE_IMAGE



def get_featured_brand(event):
    """Return a display brand for events that should appear in Featured."""
    context = " ".join([
        clean_text(event.get("title", "")),
        clean_text(event.get("venue", "")),
        clean_text(event.get("city", "")),
        clean_text(event.get("source", "")),
        clean_text(event.get("source_type", "")),
        clean_text(event.get("ticket_url", "")),
    ]).lower()

    if "thetopsecretcomedyclub.co.uk" in context or "topsecret" in context:
        return "Top Secret Comedy Club"
    if "creaturescomedy.com" in context or "creatures comedy" in context:
        return "Creatures Comedy"
    if ("glee.co.uk/glasgow" in context or "glee glasgow" in context or "glee club glasgow" in context) and "glasgow" in context:
        return "The Glee Glasgow"
    if ("pleasance.co.uk" in context or "pleasance edinburgh" in context or "pleasance courtyard" in context) and "edinburgh" in context:
        return "The Pleasance Edinburgh"
    return ""


def display_venue_for_site(event):
    """Keep featured venue branding visible in shows.json.

    Top Secret pages expose venues as addresses such as 170 Drury Lane or
    23 Kingsway. That is useful address data, but the website Featured filter
    and venue cards need the brand name as well.
    """
    venue = clean_text(event.get("venue", ""))
    brand = get_featured_brand(event)

    if brand == "Top Secret Comedy Club":
        low = venue.lower()
        if "170 drury" in low:
            return "Top Secret Comedy Club - 170 Drury Lane"
        if "23 kingsway" in low:
            return "Top Secret Comedy Club - 23 Kingsway"
        return "Top Secret Comedy Club"

    if brand and brand.lower() not in venue.lower():
        return brand

    return venue


def clean_site_title_for_featured_brand(title, event):
    """Remove address suffixes from Top Secret titles after branding the venue."""
    title = clean_text(title)
    if get_featured_brand(event) == "Top Secret Comedy Club":
        title = re.sub(r"\s+170\s+Drury\s+Lane(?:\s*\(ground floor\))?\s*$", "", title, flags=re.I)
        title = re.sub(r"\s+23\s+Kingsway\s*$", "", title, flags=re.I)
    return clean_text(title)

def event_to_site_show(event):
    """Map scraper's internal event fields to the existing website schema.

    shows.js reads show.comedian, show.tickets, show.type, show.image, show.city,
    show.venue and show.date, so do not rename these keys. `featured` is extra
    metadata used by the Featured filter.

    v3.1 (master QA brief):
      * `type` is "tour" only for clearly advertised tours or individually
        identified solo/named-act shows. Featured no longer forces "tour", and
        mixed bills, open mics and generic WIP/preview nights stay "show".
      * `featured` / `featured_venue` are unchanged (curated venue rules).
      * New optional keys: `open_mic` (confirmed comedy open mics and, while INCLUDE_POETRY_OPEN_MICS is True, poetry/spoken-word open mics;
        only) and `popular` (written ONLY when an editorial override is set for
        the venue in venues.csv; otherwise the website's major-venue list decides).
    """
    featured = is_featured_event(event)
    featured_brand = get_featured_brand(event) if featured else ""
    display_title = clean_display_title(event.get("title", ""), event)
    display_title = clean_site_title_for_featured_brand(display_title, event)
    cls = classify_event(event)
    tour_label = event.get("_tour", "") if cls.get("category") in ACCEPTED_CATEGORIES else ""
    title_and_desc = f"{event.get('title', '')}. {event_specific_description(event)}"
    new_performer_night = (
        cls.get("category") == CAT_NEW_ACT
        and bool(NEW_PERFORMER_RE.search(title_and_desc))
        and not bool(NON_OPEN_MIC_NEW_MATERIAL_RE.search(title_and_desc))
    )
    is_wip = bool(NON_OPEN_MIC_NEW_MATERIAL_RE.search(title_and_desc))

    show = {
        "city": clean_text(event.get("city", "")),
        "state": normalise_region_name(event.get("state", "")) or infer_region_from_city(event.get("city", "")),
        "comedian": display_title,
        "venue": display_venue_for_site(event),
        "date": clean_text(event.get("date", "")),
        "time": clean_text(event.get("time", "")) or extract_performance_time(f"{event.get('title', '')} {event.get('description', '')}"),
        "price": clean_text(event.get("price", "")) or extract_price_label(f"{event.get('title', '')} {event.get('description', '')}"),
        "tickets": clean_text(event.get("ticket_url", "")) or clean_text(event.get("source", "")) or "#",
        "type": "tour" if tour_label in TOUR_TYPE_LABELS and not is_wip else "show",
        "image": clean_site_image(event.get("image", "")),
        "featured": featured,
        "featured_venue": featured_brand,
        "source_type": clean_text(event.get("source_type", "")),
        "open_mic": cls.get("category") in OPEN_MIC_CATEGORIES or new_performer_night,
    }
    override = event.get("_popular_override")
    if override is not None:
        show["popular"] = bool(override)
    return show



def events_to_site_shows(events):
    shows = []
    seen = set()
    for event in events:
        # v3: rows whose location could not be established are left out (see diagnostics)
        if "unclear" in clean_text(event.get("_location_flag", "")).lower():
            continue
        show = event_to_site_show(event)
        if not (show["comedian"] and show["venue"] and show["city"] and show["date"]):
            continue
        # v3: inclusive date window (today's UK date .. --end-date)
        if not date_in_window(show["date"]):
            continue
        if show["comedian"].strip().lower() == show["city"].strip().lower():
            continue
        if is_skiddle_landing_or_brand_url(show.get("tickets", "")):
            continue
        if looks_like_bad_site_show_label(show["comedian"], show.get("tickets", "")):
            continue

        # Remove any leftover "Comedy Club" wording after the final quality gate.
        show["comedian"] = strip_comedy_club_from_display_label(show["comedian"])
        if looks_like_bad_site_show_label(show["comedian"], show.get("tickets", "")):
            continue

        # v3: performance time is part of the key so early and late shows survive.
        key = (slugify_text(show["city"]), slugify_text(show["venue"]), show["date"],
               slugify_text(show["comedian"]), slugify_text(show.get("time", "")))
        if key in seen:
            continue
        seen.add(key)
        shows.append(show)

    # Keep Featured venues prominent when the JSON is consumed directly, while
    # leaving existing page-level date sorting intact where shows.js applies it.
    shows.sort(key=lambda s: (0 if s.get("featured") else 1, s.get("date", "9999-99-99"), s.get("city", ""), s.get("venue", "")))
    return shows



def save_zero_event_venues(venues, out_xlsx="zero_event_websites.xlsx", reasons=None):
    """Save venues that returned zero events to a separate Excel file.

    The first three columns (title, city, website) are unchanged. v3.1 adds the
    reason each venue returned nothing (request failure, robots/access, JS
    calendar, no dates, all past/outside window, non-comedy, duplicates,
    exception) plus page/candidate counts. `reasons` maps venue website -> dict.
    """
    try:
        from openpyxl import Workbook
    except ImportError:
        print("Could not save zero-event Excel. Install openpyxl with: pip install openpyxl")
        return

    reasons = reasons or {}
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Zero Events"
    sheet.append(["title", "city", "website", "reason", "pages_attempted", "pages_parsed",
                  "candidate_events", "rejected_by_relevance", "excluded_by_date", "errors"])

    for venue in venues:
        r = reasons.get(venue.get("website", "")) or {}
        sheet.append([
            venue.get("title", ""),
            venue.get("city", ""),
            venue.get("website", ""),
            r.get("status", "not diagnosed"),
            r.get("pages_attempted", ""),
            r.get("pages_parsed", ""),
            r.get("candidate_events", ""),
            r.get("rejected_by_relevance", ""),
            r.get("excluded_by_date", ""),
            r.get("errors", ""),
        ])

    workbook.save(out_xlsx)
    print(f"Saved {out_xlsx} with {len(venues)} zero-event websites")



def save_events(events, out_json="data/shows.json", allow_large_drop=False):
    """Publish ONE website-ready JSON file, never an intermediate events.csv.

    The replacement is atomic so a crash cannot leave a half-written JSON file.
    Existing large datasets are protected against unexpectedly tiny scrape runs.
    """
    in_window = [e for e in events if date_in_window(e.get("date", ""))]
    site_shows = events_to_site_shows(in_window)
    if not site_shows:
        raise SystemExit("STOPPED: no valid shows found. Existing shows.json was not changed.")

    destination = Path(out_json)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not allow_large_drop:
        try:
            existing = json.loads(destination.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SystemExit(f"STOPPED: cannot validate existing {destination}: {exc}") from exc
        if not isinstance(existing, list):
            raise SystemExit(f"STOPPED: existing {destination} is not a JSON array.")
        if len(existing) >= 100 and len(site_shows) < len(existing) * 0.2:
            raise SystemExit(
                f"STOPPED: only {len(site_shows):,} shows found vs {len(existing):,} in the existing file. "
                "This could be a partial scrape; existing shows.json was not changed. "
                "If this was a successful full scrape and you expect the drop, rerun with --allow-large-drop."
            )

    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent,
                                         prefix=".shows_", suffix=".tmp", delete=False) as temp:
            tmp_name = temp.name
            json.dump(site_shows, temp, ensure_ascii=False, indent=2)
            temp.write("\n")
        os.replace(tmp_name, destination)
    finally:
        if tmp_name and os.path.exists(tmp_name):
            os.unlink(tmp_name)
    print(f"Saved {len(site_shows):,} website-ready listings to {destination} (only output file)")



def parse_args():
    parser = argparse.ArgumentParser(description="Scrape comedy events from venues.csv")
    parser.add_argument("--venues", default="venues.csv", help="Input venues CSV (an .xlsx export also works)")
    parser.add_argument("--out-json", default="data/shows.json", help="Only output file: website-ready JSON (default data/shows.json)")
    parser.add_argument("--allow-large-drop", action="store_true", help="Allow replacing an existing shows.json after a major reduction in listing count")
    parser.add_argument("--only-domain", default="", help="Only scrape venues whose website contains this domain, e.g. creaturescomedy.com")
    parser.add_argument("--only-name", default="", help="Only scrape venues whose title contains this text, e.g. Creatures")
    parser.add_argument("--test-creatures", action="store_true", help="Shortcut for --only-domain creaturescomedy.com")
    parser.add_argument("--test-just-the-tonic", action="store_true", help="Shortcut for --only-domain justthetonic.com")
    parser.add_argument("--headless", action="store_true", help="Use optional Playwright browser fallback for JS-rendered pages/widgets")
    parser.add_argument("--limit", type=int, default=0, help="Only scrape the first N venues after any filters, useful for test crawls")
    parser.add_argument("--offset", type=int, default=0, help="Skip the first N venues after any filters, useful for batch test crawls")
    parser.add_argument("--delay", type=float, default=0.2, help="Seconds to pause between venues. Use 0.05-0.2 for tests.")
    parser.add_argument("--skip-skiddle-search", action="store_true", help="Skip the extra Skiddle search made for every venue. Much faster for test crawls.")
    parser.add_argument("--headless-timeout", type=int, default=8000, help="Playwright navigation timeout in milliseconds")
    parser.add_argument("--headless-wait", type=int, default=800, help="Extra wait after DOMContentLoaded in milliseconds")
    parser.add_argument("--skiddle-show-more-clicks", type=int, default=6, help="Maximum scroll/show-more attempts on Skiddle listing pages in headless mode")
    parser.add_argument("--max-pages", type=int, default=MAX_EVENT_PAGES_PER_VENUE, help="Max likely event pages checked per venue")
    # v3 options
    parser.add_argument("--end-date", default="", help="Latest event date YYYY-MM-DD; defaults to UK today plus 365 days")
    parser.add_argument("--max-events-per-venue", type=int, default=MAX_EVENTS_PER_VENUE, help="Safety cap on in-window events kept per venue")
    parser.add_argument("--diagnostics", default="", help="Optional diagnostics report path (.xlsx, or .csv for CSV files)")
    parser.add_argument("--today", default="", help=argparse.SUPPRESS)
    return parser.parse_args()



def run():
    global USE_HEADLESS, SKIP_SKIDDLE_SEARCH, HEADLESS_TIMEOUT_MS, HEADLESS_WAIT_MS, SKIDDLE_SHOW_MORE_CLICKS, MAX_EVENT_PAGES_PER_VENUE
    global MAX_EVENTS_PER_VENUE, DIAGNOSTICS, CURRENT_VENUE
    args = parse_args()
    USE_HEADLESS = bool(args.headless)
    SKIP_SKIDDLE_SEARCH = bool(args.skip_skiddle_search)
    HEADLESS_TIMEOUT_MS = int(args.headless_timeout)
    HEADLESS_WAIT_MS = int(args.headless_wait)
    SKIDDLE_SHOW_MORE_CLICKS = int(args.skiddle_show_more_clicks)
    MAX_EVENT_PAGES_PER_VENUE = max(1, int(args.max_pages))
    MAX_EVENTS_PER_VENUE = max(1, int(args.max_events_per_venue))
    try:
        configure_date_window(args.end_date, today=parse_iso_date(args.today) if args.today else None)
    except ValueError as exc:
        print("Error:", exc)
        raise SystemExit(2)
    print(f"Date window (UK): {window_start()} to {window_end()} inclusive")
    if USE_HEADLESS:
        print(f"Headless fallback enabled: wait_until={HEADLESS_GOTO_WAIT_UNTIL}, timeout={HEADLESS_TIMEOUT_MS}ms, wait={HEADLESS_WAIT_MS}ms, skiddle_show_more_clicks={SKIDDLE_SHOW_MORE_CLICKS}")
    if SKIP_SKIDDLE_SEARCH:
        print("Per-venue Skiddle search disabled for speed")
    venues = load_venues(args.venues)

    only_domain = (args.only_domain or "").lower().strip()
    only_name = (args.only_name or "").lower().strip()
    if args.test_creatures:
        only_domain = "creaturescomedy.com"
    if args.test_just_the_tonic:
        only_domain = "justthetonic.com"

    if only_domain:
        venues = [v for v in venues if only_domain in v.get("website", "").lower()]
    if only_name:
        venues = [v for v in venues if only_name in v.get("title", "").lower()]

    total_before_limit = len(venues)
    if args.offset and args.offset > 0:
        venues = venues[args.offset:]
    if args.limit and args.limit > 0:
        venues = venues[:args.limit]

    # Filtered/test crawls must not silently overwrite the live full-site JSON.
    if (args.limit or args.offset or only_domain or only_name) and Path(args.out_json).as_posix().lstrip("./") == "data/shows.json":
        raise SystemExit("STOPPED: filtered test crawl would overwrite data/shows.json. Use --out-json test_shows.json for tests.")

    if args.limit or args.offset:
        print("Loaded", total_before_limit, "venues before test limit/offset")
    print("Loaded", len(venues), "venues")

    all_events = []
    zero_event_venues = []
    venue_diags = []
    del REVIEW_ROWS[:]

    for idx, venue in enumerate(venues, start=1):
        print(f"[{idx}/{len(venues)}] Scraping {venue['title']} - {venue['website']}")
        DIAGNOSTICS = VenueDiagnostics(venue)
        CURRENT_VENUE = venue
        try:
            events = scrape_venue(venue)
            DIAGNOSTICS.accepted = list(events)
            print("  Found", len(events), "events")
            if len(events) == 0:
                zero_event_venues.append(venue)
            all_events.extend(events)
        except Exception as exc:
            print("  Error:", exc)
            DIAGNOSTICS.errors.append(f"exception: {exc.__class__.__name__}: {exc}")
            zero_event_venues.append(venue)
        venue_diags.append(DIAGNOSTICS)
        DIAGNOSTICS = None
        CURRENT_VENUE = {}
        if args.delay > 0:
            time.sleep(args.delay)

    close_headless_browser()

    before = len(all_events)
    all_events = dedupe_events(all_events)
    cross_source_duplicates = before - len(all_events)
    all_events.sort(key=lambda x: x.get("confidence", 0), reverse=True)

    filtered = [
        e for e in all_events
        if e.get("confidence", 0) >= 5 and e.get("title") and e.get("date") and e.get("venue") and e.get("city")
        and date_in_window(e.get("date", "")) and is_relevant_comedy_event(e)
        and "unclear" not in clean_text(e.get("_location_flag", "")).lower()
    ]

    print("Total raw events:", len(all_events))
    print("Cross-source duplicates merged:", cross_source_duplicates)
    print("Filtered events:", len(filtered))

    save_events(filtered, out_json=args.out_json, allow_large_drop=args.allow_large_drop)
    # Diagnostics are opt-in. Normal daily runs create ONLY data/shows.json.
    if args.diagnostics:
        save_diagnostics(args.diagnostics, venue_diags, filtered, cross_source_duplicates)



if __name__ == "__main__":
    run()
