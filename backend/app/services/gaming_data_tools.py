"""Gaming data tools for AI agents (RAWG, IGDB, Steam).

These async helpers let an agent query live video-game databases while it
generates documents or analyses. Each public function:

- never raises: every failure (missing key, timeout, HTTP error, malformed
  payload) is returned as an explicit JSON dict such as
  ``{"error": "API unreachable", "status": 504}`` so the agent can adapt;
- ships with a Pydantic ``BaseModel`` input schema (``*Input`` classes below)
  whose JSON Schema can be used directly in agent ``tools`` declarations.

Import from the FastAPI app::

    from app.services.gaming_data_tools import (
        GAMING_TOOLS,
        get_steam_reviews,
        get_tool_json_schemas,
    )

Minimal route sketch::

    @app.post("/api/v1/tools/steam-reviews")
    async def steam_reviews(body: GetSteamReviewsInput):
        return await get_steam_reviews(app_id=body.app_id)
"""

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

RAWG_BASE_URL = "https://api.rawg.io/api"
IGDB_BASE_URL = "https://api.igdb.com/v4"
IGDB_GAME_FIELDS = (
    "name,slug,summary,genres.name,game_modes.name,themes.name,"
    "rating,rating_count,first_release_date"
)
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
STEAM_REVIEWS_URL = "https://store.steampowered.com/appreviews/{app_id}"

MAX_RESULTS = 10
TEXT_SNIPPET_LEN = 600


# ---------------------------------------------------------------------------
# Tool input schemas (Pydantic -> JSON Schema for agent `tools` declarations)
# ---------------------------------------------------------------------------


class SearchRawgGamesInput(BaseModel):
    """Input schema for the ``search_rawg_games`` tool.

    :param query: Free-text search terms, e.g. a game title, mood or hook
        ("zombie survival", "cozy farming sim").
    :param genre: Optional RAWG genre slug used as a filter, e.g. ``"action"``,
        ``"role-playing-games-rpg"`` or ``"strategy"``. Plain names such as
        "Role Playing" are slugified automatically.
    """

    query: str = Field(..., description="Free-text search terms (title, mood or hook).")
    genre: Optional[str] = Field(
        default=None,
        description="Optional RAWG genre slug filter, e.g. 'action' or 'strategy'.",
    )


class GetRawgGameDetailsInput(BaseModel):
    """Input schema for the ``get_rawg_game_details`` tool.

    :param slug: RAWG game slug, e.g. ``"dying-light"`` (the ``slug`` field
        from ``search_rawg_games`` results).
    """

    slug: str = Field(..., description="RAWG game slug, e.g. 'dying-light'.")


class GetIgdbMetadataInput(BaseModel):
    """Input schema for the ``get_igdb_metadata`` tool.

    :param theme: Main theme or setting to look up, e.g. ``"zombies"``,
        ``"cyberpunk"`` or ``"underwater exploration"``.
    :param mechanics: Optional gameplay mechanics to narrow the search, e.g.
        ``"base building"`` or ``"permadeath co-op"``.
    """

    theme: str = Field(
        ..., description="Main theme or setting, e.g. 'horror'. Mapped to IGDB themes when possible."
    )
    mechanics: Optional[str] = Field(
        default=None,
        description="Optional gameplay mechanics, e.g. 'base building'. Mapped to IGDB keywords / game modes when possible.",
    )


class GetSteamReviewsInput(BaseModel):
    """Input schema for the ``get_steam_reviews`` tool.

    :param app_id: Steam application id of the target game (the number in the
        store URL, e.g. ``413150`` for Stardew Valley). Must be >= 1.
    """

    app_id: int = Field(..., ge=1, description="Steam application id of the target game.")


# ---------------------------------------------------------------------------
# Internal plumbing
# ---------------------------------------------------------------------------


class _ToolError(Exception):
    """Internal control flow: carries an agent-facing ``{"error", "status"}`` payload."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.message = message
        self.status = status


def _snip(text: Any, limit: int = TEXT_SNIPPET_LEN) -> str:
    """Coerce to str and truncate long free text to bound agent token usage."""
    text = "" if text is None else str(text)
    return text if len(text) <= limit else text[:limit] + "…"


def _safe_json(response: httpx.Response, source: str) -> Any:
    try:
        return response.json()
    except ValueError:
        raise _ToolError(f"{source} returned invalid JSON.", 502)


def _check_http(response: httpx.Response, source: str, what_401: str) -> None:
    """Map HTTP failures to _ToolError; 401 gets a credentials-specific message."""
    code = response.status_code
    if code < 400:
        return
    if code == 401:
        raise _ToolError(f"Invalid credentials for {source} ({what_401}).", 401)
    if code == 429:
        raise _ToolError(f"{source} rate limit exceeded, retry later.", 429)
    raise _ToolError(f"{source} error {code}: {response.text[:200]}", code)


# ---------------------------------------------------------------------------
# RAWG — similar games + metadata (https://rawg.io/apidocs)
# ---------------------------------------------------------------------------


def _normalize_rawg_game(raw: Dict[str, Any]) -> Dict[str, Any]:
    genres = [g.get("name") for g in raw.get("genres", []) or [] if isinstance(g, dict)]
    platforms = [
        p.get("platform", {}).get("name")
        for p in raw.get("platforms", []) or []
        if isinstance(p, dict) and isinstance(p.get("platform"), dict)
    ]
    return {
        "name": raw.get("name"),
        "slug": raw.get("slug"),
        "released": raw.get("released"),
        "rating": raw.get("rating"),
        "ratings_count": raw.get("ratings_count"),
        "genres": [g for g in genres if g],
        "platforms": [p for p in platforms if p],
        "image": raw.get("background_image"),
    }


async def _search_rawg_games(query: str, genre: Optional[str]) -> Dict[str, Any]:
    api_key = os.getenv("RAWG_API_KEY", "")
    if not api_key:
        raise _ToolError("RAWG_API_KEY is not configured.", 401)
    # NOTE: no `ordering` param on purpose — RAWG sorts by search relevance
    # by default, and any explicit ordering (e.g. -rating) destroys it.
    params: Dict[str, Any] = {
        "key": api_key,
        "search": query,
        "page_size": MAX_RESULTS,
    }
    if genre:
        params["genres"] = genre.strip().lower().replace(" ", "-").replace("_", "-")
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.get(
                f"{RAWG_BASE_URL}/games", params=params, follow_redirects=True
            )
    except httpx.TimeoutException:
        raise _ToolError("RAWG API timed out.", 504)
    except httpx.RequestError as exc:
        raise _ToolError(f"RAWG API unreachable ({exc.__class__.__name__}).", 503)
    _check_http(response, "RAWG", "check RAWG_API_KEY")
    data = _safe_json(response, "RAWG")
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise _ToolError("RAWG response shape unexpected.", 502)
    games = [
        _normalize_rawg_game(g) for g in data["results"][:MAX_RESULTS] if isinstance(g, dict)
    ]
    return {"source": "rawg", "query": query, "count": len(games), "games": games}


async def search_rawg_games(query: str, genre: Optional[str] = None) -> Dict[str, Any]:
    """Search RAWG for similar games and their metadata.

    Never raises: failures are returned as ``{"error": ..., "status": ...}``.
    """
    try:
        return await _search_rawg_games(query, genre)
    except _ToolError as exc:
        return {"error": exc.message, "status": exc.status}
    except Exception:
        logger.exception("search_rawg_games: unexpected failure.")
        return {"error": "Unexpected internal error.", "status": 500}


async def _get_rawg_game_details(slug: str) -> Dict[str, Any]:
    api_key = os.getenv("RAWG_API_KEY", "")
    if not api_key:
        raise _ToolError("RAWG_API_KEY is not configured.", 401)
    if not isinstance(slug, str) or not slug.strip():
        raise _ToolError("slug must be a non-empty string.", 400)
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.get(
                f"{RAWG_BASE_URL}/games/{slug.strip()}",
                params={"key": api_key},
                follow_redirects=True,
            )
    except httpx.TimeoutException:
        raise _ToolError("RAWG API timed out.", 504)
    except httpx.RequestError as exc:
        raise _ToolError(f"RAWG API unreachable ({exc.__class__.__name__}).", 503)
    if response.status_code == 404:
        raise _ToolError(f"Unknown RAWG slug: {slug}.", 404)
    _check_http(response, "RAWG", "check RAWG_API_KEY")
    data = _safe_json(response, "RAWG")
    if not isinstance(data, dict):
        raise _ToolError("RAWG response shape unexpected.", 502)
    stores = []
    for store in data.get("stores", []) or []:
        if not isinstance(store, dict):
            continue
        info = store.get("store", {}) if isinstance(store.get("store"), dict) else {}
        stores.append({"name": info.get("name"), "url": store.get("url")})
    return {
        "source": "rawg",
        "name": data.get("name"),
        "slug": data.get("slug"),
        "website": data.get("website"),
        "description": _snip(data.get("description_raw") or data.get("description")),
        "stores": stores,
    }


async def get_rawg_game_details(slug: str) -> Dict[str, Any]:
    """Fetch full RAWG metadata (website, description, store links) for one game.

    Never raises: failures are returned as ``{"error": ..., "status": ...}``.
    """
    try:
        return await _get_rawg_game_details(slug)
    except _ToolError as exc:
        return {"error": exc.message, "status": exc.status}
    except Exception:
        logger.exception("get_rawg_game_details: unexpected failure.")
        return {"error": "Unexpected internal error.", "status": 500}


# ---------------------------------------------------------------------------
# IGDB (via Twitch) — gameplay references (https://api-docs.igdb.com)
# ---------------------------------------------------------------------------

_igdb_token_cache: Dict[str, Any] = {"access_token": None, "expires_at": 0.0}


def _clean_apicalypse(value: str) -> str:
    """Collapse whitespace and strip quotes so input cannot break the query."""
    return " ".join((value or "").split()).replace('"', "")


async def _get_igdb_token() -> str:
    """Fetch (and cache) a Twitch app access token for IGDB."""
    now = time.monotonic()
    if _igdb_token_cache["access_token"] and now < float(_igdb_token_cache["expires_at"]):
        return str(_igdb_token_cache["access_token"])
    client_id = os.getenv("TWITCH_CLIENT_ID", "")
    client_secret = os.getenv("TWITCH_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise _ToolError("TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET are not configured.", 401)
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.post(
                TWITCH_TOKEN_URL,
                params={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "client_credentials",
                },
                follow_redirects=True,
            )
    except httpx.TimeoutException:
        raise _ToolError("Twitch OAuth timed out.", 504)
    except httpx.RequestError as exc:
        raise _ToolError(f"Twitch OAuth unreachable ({exc.__class__.__name__}).", 503)
    _check_http(response, "Twitch OAuth", "check TWITCH_CLIENT_ID/SECRET")
    data = _safe_json(response, "Twitch OAuth")
    token = data.get("access_token") if isinstance(data, dict) else None
    if not token:
        raise _ToolError("Twitch OAuth returned no access token.", 502)
    expires_in = data.get("expires_in", 3600) if isinstance(data, dict) else 3600
    try:
        ttl = max(60, int(expires_in) - 60)
    except (TypeError, ValueError):
        ttl = 3540
    _igdb_token_cache["access_token"] = token
    _igdb_token_cache["expires_at"] = now + ttl
    return str(token)


def _normalize_igdb_game(raw: Dict[str, Any]) -> Dict[str, Any]:
    def names(items: Any, key: str = "name") -> List[str]:
        if not isinstance(items, list):
            return []
        return [i.get(key) for i in items if isinstance(i, dict) and i.get(key)]

    released: Optional[str] = None
    ts = raw.get("first_release_date")
    if isinstance(ts, (int, float)) and ts > 0:
        try:
            released = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            released = None
    return {
        "name": raw.get("name"),
        "slug": raw.get("slug"),
        "summary": _snip(raw.get("summary")),
        "genres": names(raw.get("genres")),
        "game_modes": names(raw.get("game_modes")),
        "themes": names(raw.get("themes")),
        "rating": raw.get("rating"),
        "rating_count": raw.get("rating_count"),
        "first_release_date": released,
    }


async def _igdb_post(client_id: str, token: str, endpoint: str, query: str) -> Any:
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.post(
                f"{IGDB_BASE_URL}/{endpoint}",
                content=query.encode("utf-8"),
                headers={
                    "Client-ID": client_id,
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                follow_redirects=True,
            )
    except httpx.TimeoutException:
        raise _ToolError("IGDB API timed out.", 504)
    except httpx.RequestError as exc:
        raise _ToolError(f"IGDB API unreachable ({exc.__class__.__name__}).", 503)
    if response.status_code == 401:
        _igdb_token_cache["access_token"] = None  # force a token refresh next call
    _check_http(response, "IGDB", "check TWITCH_CLIENT_ID/SECRET")
    return _safe_json(response, "IGDB")


async def _igdb_search(client_id: str, token: str, terms: str) -> List[Dict[str, Any]]:
    """Name search on /games (IGDB `search` matches game names)."""
    data = await _igdb_post(
        client_id, token, "games", f'search "{terms}"; fields {IGDB_GAME_FIELDS}; limit {MAX_RESULTS};'
    )
    if not isinstance(data, list):
        raise _ToolError("IGDB response shape unexpected.", 502)
    return [_normalize_igdb_game(g) for g in data[:MAX_RESULTS] if isinstance(g, dict)]


async def _resolve_igdb_ids(
    client_id: str, token: str, endpoint: str, term: str, max_ids: int, searchable: bool
) -> List[Dict[str, Any]]:
    """Resolve natural language to [{id, name}] via an IGDB reference endpoint.

    Tries the whole phrase first, then individual words; exact slug/name
    matches win over fuzzy first hits. Searchable endpoints (themes) use
    `search`; others (keywords, game_modes) use case-insensitive `~ *..*`.
    """
    cleaned = _clean_apicalypse(term)
    if not cleaned:
        return []
    stopwords = {
        "game", "games", "gaming", "video", "videos",
        "the", "and", "with", "for", "from", "new",
        "jeu", "jeux", "des", "les", "une", "dans", "pour", "avec", "sur",
    }
    candidates = [cleaned]
    words = [w for w in cleaned.split(" ") if len(w) >= 3 and w.lower() not in stopwords]
    if len(words) > 1:
        candidates.extend(words)
    seen: set = set()
    picks: List[Dict[str, Any]] = []
    for candidate in candidates:
        if len(picks) >= max_ids:
            break
        if searchable:
            query = f'search "{candidate}"; fields id,name,slug; limit 5;'
        else:
            query = f'where name ~ *"{candidate}"*; fields id,name,slug; limit 5;'
        data = await _igdb_post(client_id, token, endpoint, query)
        if not isinstance(data, list):
            continue
        rows = [r for r in data if isinstance(r, dict) and isinstance(r.get("id"), int)]
        slug = candidate.lower().replace(" ", "-")
        exact = [
            r
            for r in rows
            if str(r.get("slug", "")).lower() == slug
            or str(r.get("name", "")).lower() == candidate.lower()
        ]
        for row in exact or rows:
            if row["id"] not in seen:
                seen.add(row["id"])
                picks.append({"id": row["id"], "name": row.get("name") or row.get("slug")})
                if len(picks) >= max_ids:
                    break
        if picks and candidate == cleaned:
            break  # phrase hit: no need to try single words
    return picks


async def _igdb_metadata_with_token(
    client_id: str, token: str, theme: str, mechanics: Optional[str]
) -> Dict[str, Any]:
    async def try_resolve(
        endpoint: str, term: str, max_ids: int, searchable: bool
    ) -> List[Dict[str, Any]]:
        try:
            return await _resolve_igdb_ids(client_id, token, endpoint, term, max_ids, searchable)
        except _ToolError as exc:
            logger.warning(
                "IGDB %s resolution failed (%s); continuing without it.", endpoint, exc.message
            )
            return []

    filters: Dict[str, List[Dict[str, Any]]] = {}
    themes = await try_resolve("themes", theme or "", 1, True)
    if themes:
        filters["themes"] = themes
    if (mechanics or "").strip():
        keywords = await try_resolve("keywords", mechanics or "", 3, False)
        if keywords:
            filters["keywords"] = keywords
        modes = await try_resolve("game_modes", mechanics or "", 2, False)
        if modes:
            filters["game_modes"] = modes
    if filters:
        where = " & ".join(
            f"{group} = ({','.join(str(x['id']) for x in ids)})"
            for group, ids in filters.items()
        )
        data: Any = None
        try:
            data = await _igdb_post(
                client_id,
                token,
                "games",
                # sort by vote count, not average: surfaces mainstream references
            # instead of obscure 100%-rated entries.
            f"fields {IGDB_GAME_FIELDS}; where {where}; sort rating_count desc; limit {MAX_RESULTS};",
            )
        except _ToolError as exc:
            logger.warning("IGDB where-query failed (%s); falling back to name search.", exc.message)
        if isinstance(data, list):
            games = [_normalize_igdb_game(g) for g in data[:MAX_RESULTS] if isinstance(g, dict)]
            if games:
                return {
                    "source": "igdb",
                    "theme": theme,
                    "mechanics": mechanics,
                    "filters_used": filters,
                    "query_used": f"where {where}",
                    "count": len(games),
                    "games": games,
                }
    # Fallback: name search (combined terms, then theme alone).
    terms_full = _clean_apicalypse(f"{theme} {mechanics or ''}")
    games = await _igdb_search(client_id, token, terms_full)
    query_used = f'search "{terms_full}"'
    if not games and (mechanics or "").strip():
        terms_theme = _clean_apicalypse(theme)
        if terms_theme and terms_theme != terms_full:
            logger.info("IGDB: no hit for %r, retrying with %r.", terms_full, terms_theme)
            games = await _igdb_search(client_id, token, terms_theme)
            query_used = f'search "{terms_theme}"'
    return {
        "source": "igdb",
        "theme": theme,
        "mechanics": mechanics,
        "filters_used": filters,
        "query_used": query_used,
        "count": len(games),
        "games": games,
    }


async def _get_igdb_metadata(theme: str, mechanics: Optional[str]) -> Dict[str, Any]:
    token = await _get_igdb_token()
    client_id = os.getenv("TWITCH_CLIENT_ID", "")
    try:
        return await _igdb_metadata_with_token(client_id, token, theme, mechanics)
    except _ToolError as exc:
        if exc.status != 401:
            raise
        # Stale cached token: the cache was cleared above, so this fetches
        # a fresh one and retries the whole flow exactly once.
        token = await _get_igdb_token()
        return await _igdb_metadata_with_token(client_id, token, theme, mechanics)


async def get_igdb_metadata(theme: str, mechanics: Optional[str] = None) -> Dict[str, Any]:
    """Fetch IGDB gameplay references for a theme, optionally narrowed by mechanics.

    Never raises: failures are returned as ``{"error": ..., "status": ...}``.
    """
    try:
        return await _get_igdb_metadata(theme, mechanics)
    except _ToolError as exc:
        return {"error": exc.message, "status": exc.status}
    except Exception:
        logger.exception("get_igdb_metadata: unexpected failure.")
        return {"error": "Unexpected internal error.", "status": 500}


# ---------------------------------------------------------------------------
# Steam Web API — player reviews (no key required for public summaries)
# ---------------------------------------------------------------------------


async def _steam_get_json(
    client: httpx.AsyncClient, url: str, params: Dict[str, Any]
) -> Any:
    """GET JSON from Steam; raises _ToolError on transport/HTTP/content problems."""
    try:
        response = await client.get(
            url,
            params=params,
            headers={"Accept": "application/json"},
            follow_redirects=True,
        )
    except httpx.TimeoutException:
        raise _ToolError("Steam API timed out.", 504)
    except httpx.RequestError as exc:
        raise _ToolError(f"Steam API unreachable ({exc.__class__.__name__}).", 503)
    _check_http(response, "Steam", "no key required")
    content_type = str(response.headers.get("content-type", "") or "")
    if "text/html" in content_type:
        raise _ToolError("Steam returned an HTML page instead of JSON (bot filter).", 502)
    return _safe_json(response, "Steam")


async def _fetch_steam_appdetails(
    client: httpx.AsyncClient, app_id: int
) -> Optional[Dict[str, Any]]:
    """Fallback metadata when reviews are filtered; None when the app is unknown."""
    data = await _steam_get_json(
        client, "https://store.steampowered.com/api/appdetails", {"appids": app_id}
    )
    if not isinstance(data, dict):
        return None
    entry = data.get(str(app_id), {})
    if not isinstance(entry, dict) or not entry.get("success"):
        return None
    info = entry.get("data", {}) if isinstance(entry.get("data"), dict) else {}
    genres = [g.get("description") for g in info.get("genres", []) or [] if isinstance(g, dict)]
    price = info.get("price_overview", {}) if isinstance(info.get("price_overview"), dict) else {}
    recs = info.get("recommendations", {}) if isinstance(info.get("recommendations"), dict) else {}
    release = info.get("release_date", {}) if isinstance(info.get("release_date"), dict) else {}
    return {
        "name": info.get("name"),
        "short_description": _snip(info.get("short_description")),
        "genres": [g for g in genres if g],
        "recommendations_total": recs.get("total"),
        "price": price.get("final_formatted"),
        "release_date": release.get("date"),
        "image": info.get("header_image"),
    }


async def _get_steam_reviews(app_id: int) -> Dict[str, Any]:
    if not isinstance(app_id, int) or isinstance(app_id, bool) or app_id < 1:
        raise _ToolError("app_id must be a positive integer (see the Steam store URL).", 400)
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        try:
            data = await _steam_get_json(
                client,
                STEAM_REVIEWS_URL.format(app_id=app_id),
                {
                    "json": 1,
                    "language": "all",
                    "purchase_type": "all",
                    "filter": "all",
                    "num_per_page": 5,
                },
            )
        except _ToolError as reviews_error:
            # appreviews is aggressively filtered per IP; degrade to appdetails
            # metadata instead of failing outright.
            try:
                fallback = await _fetch_steam_appdetails(client, app_id)
            except _ToolError:
                raise reviews_error
            if fallback is None:
                raise reviews_error
            return {
                "source": "steam",
                "app_id": app_id,
                "summary": None,
                "sample_reviews": [],
                "reviews_blocked": True,
                "fallback": fallback,
                "note": (
                    "Steam blocked the reviews endpoint from this network "
                    f"({reviews_error.message}); metadata fallback used instead."
                ),
            }
    if not isinstance(data, dict) or not data.get("success"):
        raise _ToolError(f"No Steam reviews found for app_id {app_id}.", 404)
    summary = data.get("query_summary", {}) if isinstance(data.get("query_summary"), dict) else {}
    total_reviews = summary.get("total_reviews", 0) or 0
    total_positive = summary.get("total_positive", 0) or 0
    try:
        positive_pct = round(100 * float(total_positive) / float(total_reviews), 1)
    except (TypeError, ValueError, ZeroDivisionError):
        positive_pct = None
    sample: List[Dict[str, Any]] = []
    reviews = data.get("reviews", [])
    if isinstance(reviews, list):
        for review in reviews[:5]:
            if not isinstance(review, dict):
                continue
            author = review.get("author", {}) if isinstance(review.get("author"), dict) else {}
            minutes = author.get("playtime_forever", 0) or 0
            try:
                playtime_hours: Optional[float] = round(float(minutes) / 60, 1)
            except (TypeError, ValueError):
                playtime_hours = None
            sample.append(
                {
                    "recommended": review.get("voted_up"),
                    "playtime_hours": playtime_hours,
                    "text": _snip(review.get("review")),
                }
            )
    return {
        "source": "steam",
        "app_id": app_id,
        "summary": {
            "score_desc": summary.get("review_score_desc"),
            "score": summary.get("review_score"),
            "total_reviews": total_reviews,
            "positive_pct": positive_pct,
        },
        "sample_reviews": sample,
    }


async def get_steam_reviews(app_id: int) -> Dict[str, Any]:
    """Fetch player review sentiment and sample reviews for a Steam game.

    If Steam filters the reviews endpoint from this network, degrades to an
    explicit ``reviews_blocked`` payload with appdetails metadata fallback.
    Never raises: failures are returned as ``{"error": ..., "status": ...}``.
    """
    try:
        return await _get_steam_reviews(app_id)
    except _ToolError as exc:
        return {"error": exc.message, "status": exc.status}
    except Exception:
        logger.exception("get_steam_reviews: unexpected failure.")
        return {"error": "Unexpected internal error.", "status": 500}


# ---------------------------------------------------------------------------
# Agent tool registry
# ---------------------------------------------------------------------------

GAMING_TOOLS: Dict[str, Dict[str, Any]] = {
    "search_rawg_games": {
        "description": "Search the RAWG database for similar games and metadata.",
        "input_schema": SearchRawgGamesInput,
        "function": search_rawg_games,
    },
    "get_rawg_game_details": {
        "description": "Fetch full RAWG metadata (website, description, store links) for one game.",
        "input_schema": GetRawgGameDetailsInput,
        "function": get_rawg_game_details,
    },
    "get_igdb_metadata": {
        "description": "Fetch IGDB gameplay references for a theme and mechanics.",
        "input_schema": GetIgdbMetadataInput,
        "function": get_igdb_metadata,
    },
    "get_steam_reviews": {
        "description": "Fetch Steam player review sentiment and samples for a game.",
        "input_schema": GetSteamReviewsInput,
        "function": get_steam_reviews,
    },
}


def get_tool_json_schemas() -> Dict[str, Dict[str, Any]]:
    """Return ``{tool_name: JSON Schema}`` for agent ``tools`` declarations."""
    return {
        name: spec["input_schema"].model_json_schema() for name, spec in GAMING_TOOLS.items()
    }


# ---------------------------------------------------------------------------
# Required environment variables (add to backend/.env).
# `.env` files are already ignored by the root .gitignore -> no .gitignore
# change needed. Never commit real keys.
#
#   RAWG_API_KEY=...          Free key at https://rawg.io/apidocs
#   TWITCH_CLIENT_ID=...      Twitch dev console (https://dev.twitch.tv/console)
#   TWITCH_CLIENT_SECRET=...  Twitch dev console, same application as the ID
#
# Steam needs no key: public review summaries are unauthenticated.
# ---------------------------------------------------------------------------
