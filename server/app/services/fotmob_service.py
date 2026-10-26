"""FotMob Match Ingestion and Real-Time Sync Service."""

import asyncio
from datetime import UTC, datetime
import json
import logging
import re
import urllib.request

logger = logging.getLogger("fotmob_service")

# In-memory cache: match_id -> (timestamp, data)
_CACHE: dict[str, tuple[float, dict]] = {}
CACHE_TTL_LIVE = 15.0      # 15 seconds for live matches
CACHE_TTL_DEFAULT = 300.0  # 5 minutes for upcoming/finished matches


def extract_match_id(url_or_code: str) -> str:
    """Extract numeric or slug match ID from user input (URL, hash fragment, or ID)."""
    cleaned = str(url_or_code).strip()
    # Check for #1234567 fragment
    hash_match = re.search(r"#(\d+)", cleaned)
    if hash_match:
        return hash_match.group(1)
    
    # Check for /match/1234567 or /matches/.../1234567
    url_num_match = re.search(r"/match(?:es)?/.*?(\d+)(?:[/?#]|$)", cleaned)
    if url_num_match:
        return url_num_match.group(1)
        
    # Check if entire string is numeric
    if cleaned.isdigit():
        return cleaned
        
    # Check if URL ends with an alphanumeric slug like 8jn7yo80
    slug_match = re.search(r"/matches/[^/]+/([a-zA-Z0-9]+)", cleaned)
    if slug_match:
        return slug_match.group(1)
        
    return cleaned


def _fetch_fotmob_raw(match_id: str) -> dict:
    """Fetch raw Next.js page state from FotMob."""
    target_url = f"https://www.fotmob.com/match/{match_id}"
    req = urllib.request.Request(
        target_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    
    with urllib.request.urlopen(req, timeout=10) as resp:
        html = resp.read().decode("utf-8", errors="ignore")
        
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
    if not m:
        raise ValueError(f"Could not find FotMob page state for match ID {match_id}")
        
    data = json.loads(m.group(1))
    return data.get("props", {}).get("pageProps", {})


def parse_fotmob_data(match_id: str, props: dict) -> dict:
    """Normalize FotMob pageProps into our internal event schema."""
    general = props.get("general", {})
    header = props.get("header", {})
    teams = header.get("teams", [])
    status_dict = header.get("status", {})
    content = props.get("content", {})
    
    # Home & Away Teams
    home_name = "Home Team"
    away_name = "Away Team"
    home_id = ""
    away_id = ""
    score_home = "0"
    score_away = "0"
    
    if len(teams) >= 2:
        home_name = teams[0].get("name", "Home Team")
        away_name = teams[1].get("name", "Away Team")
        home_id = str(teams[0].get("id", ""))
        away_id = str(teams[1].get("id", ""))
        score_home = str(teams[0].get("score", 0))
        score_away = str(teams[1].get("score", 0))
    elif general.get("homeTeam") and general.get("awayTeam"):
        home_name = general["homeTeam"].get("name", "Home Team")
        away_name = general["awayTeam"].get("name", "Away Team")
        home_id = str(general["homeTeam"].get("id", ""))
        away_id = str(general["awayTeam"].get("id", ""))
        
    # Badges (FotMob CDN)
    home_badge = f"https://images.fotmob.com/image_resources/logo/teamlogo/{home_id}.png" if home_id else ""
    away_badge = f"https://images.fotmob.com/image_resources/logo/teamlogo/{away_id}.png" if away_id else ""
    
    # League & Title
    league = general.get("leagueName") or general.get("parentLeagueName") or "Football"
    title = f"{home_name} vs {away_name}"
    
    # Scheduled Time
    scheduled_utc = general.get("matchTimeUTCDate") or status_dict.get("utcTime")
    if not scheduled_utc:
        scheduled_utc = datetime.now(UTC).isoformat()
        
    # Match Status & Live Minute
    started = status_dict.get("started", general.get("started", False))
    finished = status_dict.get("finished", general.get("finished", False))
    cancelled = status_dict.get("cancelled", False)
    
    live_minute = ""
    if cancelled:
        status = "cancelled"
    elif finished:
        status = "finished"
        live_minute = "FT"
    elif started:
        status = "live"
        live_time = status_dict.get("liveTime", {})
        if isinstance(live_time, dict):
            short_time = live_time.get("short") or live_time.get("long") or ""
            live_minute = str(short_time)
        elif isinstance(live_time, str):
            live_minute = live_time
        if not live_minute:
            live_minute = "LIVE"
    else:
        status = "upcoming"
        
    # Rich details for client / stats overview
    rich_details = {
        "matchId": match_id,
        "round": general.get("matchRound", ""),
        "coverage": general.get("coverageLevel", ""),
        "teamColors": general.get("teamColors", {}),
        "events": header.get("events"),
        "matchFacts": content.get("matchFacts"),
        "stats": content.get("stats"),
        "lineup": content.get("lineup"),
        "h2h": content.get("h2h"),
        "table": content.get("table"),
    }
    
    return {
        "fotmob_match_id": match_id,
        "title": title,
        "category": "Football",
        "league": league,
        "team_home": home_name,
        "team_away": away_name,
        "team_home_badge": home_badge,
        "team_away_badge": away_badge,
        "scheduled_at": scheduled_utc,
        "status": status,
        "score_home": score_home,
        "score_away": score_away,
        "live_minute": live_minute,
        "rich_details": rich_details,
    }


async def get_fotmob_match_details(url_or_code: str, force_refresh: bool = False) -> dict:
    """Fetch and parse FotMob match with asynchronous executor and in-memory TTL caching."""
    match_id = extract_match_id(url_or_code)
    now = asyncio.get_event_loop().time()
    
    if not force_refresh and match_id in _CACHE:
        cached_time, cached_data = _CACHE[match_id]
        ttl = CACHE_TTL_LIVE if cached_data.get("status") == "live" else CACHE_TTL_DEFAULT
        if now - cached_time < ttl:
            return cached_data
            
    loop = asyncio.get_running_loop()
    raw_props = await loop.run_in_executor(None, _fetch_fotmob_raw, match_id)
    parsed = parse_fotmob_data(match_id, raw_props)
    
    _CACHE[match_id] = (now, parsed)
    return parsed
