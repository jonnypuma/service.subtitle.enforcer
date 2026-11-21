# -*- coding: utf-8 -*-
"""TMDB and TMDBHelper integration for original-language lookup and title search."""

import json
import os
import re
import threading
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import xbmc
import xbmcaddon

from resources.lib.kodi import ADDON_NAME, _info_label, _string_setting
from resources.lib.rules import title_match

_TMDB_API = "https://api.themoviedb.org/3"
_TMDB_CACHE_MAX = 64

_tmdb_lock = threading.Lock()
_tmdb_cache = {}
_tmdb_failed = set()
_tmdb_inflight = set()
_tmdbhelper_key_cache = {"loaded": False, "key": ""}


def clear_tmdb_cache():
    with _tmdb_lock:
        _tmdb_cache.clear()
        _tmdb_failed.clear()
        _tmdb_inflight.clear()
    _tmdbhelper_key_cache["loaded"] = False
    _tmdbhelper_key_cache["key"] = ""


def clear_tmdb_session_failures():
    with _tmdb_lock:
        _tmdb_failed.clear()


def _tmdb_property(name):
    return _info_label("Window(home).Property(TMDbHelper.Player.{0})".format(name))


def tmdbhelper_installed():
    try:
        return bool(xbmc.getCondVisibility("System.HasAddon(plugin.video.themoviedb.helper)"))
    except Exception:
        return False


def tmdbhelper_service_started():
    return _info_label("Window(home).Property(TMDbHelper.ServiceStarted)").lower() == "true"


def tmdbhelper_matches_current_item():
    """True when the player properties belong to the video that is playing."""
    helper_ids = [
        _tmdb_property("tmdb_id"),
        _tmdb_property("tvshow.tmdb_id"),
    ]
    playing_ids = [
        _info_label("VideoPlayer.UniqueID(tmdb)"),
        _info_label("VideoPlayer.UniqueID(tvshow.tmdb)"),
    ]
    if any(value and value in playing_ids for value in helper_ids):
        return True
    helper_titles = [
        _tmdb_property("title"),
        _tmdb_property("Title"),
        _tmdb_property("tvshowtitle"),
        _tmdb_property("TvShowTitle"),
    ]
    playing_titles = [
        _info_label("VideoPlayer.Title"),
        _info_label("VideoPlayer.TvShowTitle"),
    ]
    for title in helper_titles:
        if not title:
            continue
        for playing in playing_titles:
            if playing and (title_match(title, playing) or title_match(playing, title)):
                return True
    return False


def tmdbhelper_language():
    """Original language TMDBHelper has published for this playing item."""
    if not tmdbhelper_installed() or not tmdbhelper_matches_current_item():
        return ""
    return _tmdb_property("original_language")


def tmdbhelper_lookup_pending():
    """True while TMDBHelper is running and has not identified this item yet."""
    if not tmdbhelper_installed() or not tmdbhelper_service_started():
        return False
    return not tmdbhelper_matches_current_item()


def choose_tmdb_api_key(own, helper):
    """Use the entered key, or TMDBHelper's key when that field is empty."""
    own = (own or "").strip()
    if own:
        return own
    return (helper or "").strip()


def api_key_from_text(text):
    """Read TMDBHelper's project API key from its installed source."""
    match = re.search(r"API_KEY\s*=\s*['\"]([A-Za-z0-9]{16,})['\"]", text or "")
    if not match:
        return ""
    return match.group(1)


def _read_tmdbhelper_api_key_uncached():
    if not tmdbhelper_installed():
        return ""
    try:
        helper = xbmcaddon.Addon("plugin.video.themoviedb.helper")
    except Exception:
        return ""
    for setting_id in ("tmdb_apikey", "tmdb_api_key", "apikey"):
        try:
            value = helper.getSetting(setting_id)
        except Exception:
            value = ""
        value = (value or "").strip()
        if value:
            return value
    folder = ""
    try:
        folder = helper.getAddonInfo("path") or ""
    except Exception:
        folder = ""
    candidates = [
        os.path.join(folder, "resources", "tmdbhelper", "lib", "api", "api_keys", "tmdb.py"),
        os.path.join(folder, "resources", "lib", "api", "api_keys", "tmdb.py"),
    ]
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                key = api_key_from_text(handle.read())
        except Exception:
            key = ""
        if key:
            return key
    return ""


def read_tmdbhelper_api_key():
    if _tmdbhelper_key_cache["loaded"]:
        return _tmdbhelper_key_cache["key"]
    key = _read_tmdbhelper_api_key_uncached()
    _tmdbhelper_key_cache["loaded"] = True
    _tmdbhelper_key_cache["key"] = key
    return key


def resolve_tmdb_api_key():
    return choose_tmdb_api_key(_string_setting("tmdb_api_key", ""), read_tmdbhelper_api_key())


def tmdb_item_query():
    """Identify the playing film well enough to ask TMDB for its language."""
    show = _info_label("VideoPlayer.TvShowTitle")
    title = _info_label("VideoPlayer.Title")
    year = _info_label("VideoPlayer.Year")
    if not (year.isdigit() and year != "0"):
        year = ""
    imdb = _info_label("VideoPlayer.IMDBNumber") or _info_label("VideoPlayer.UniqueID(imdb)")
    if not imdb.lower().startswith("tt"):
        imdb = ""
    helper_matches = tmdbhelper_matches_current_item()
    if show:
        tmdb_id = _info_label("VideoPlayer.UniqueID(tvshow.tmdb)")
        if not tmdb_id and helper_matches:
            tmdb_id = _tmdb_property("tvshow.tmdb_id")
        return {"kind": "tv", "tmdb_id": tmdb_id, "imdb": imdb, "title": show, "year": ""}
    tmdb_id = _info_label("VideoPlayer.UniqueID(tmdb)")
    if not tmdb_id and helper_matches:
        tmdb_id = _tmdb_property("tmdb_id")
    return {"kind": "movie", "tmdb_id": tmdb_id, "imdb": imdb, "title": title, "year": year}


def tmdb_item_identity(item):
    if not isinstance(item, dict):
        return ""
    tmdb_id = str(item.get("tmdb_id") or "").strip()
    imdb = str(item.get("imdb") or "").strip()
    title = str(item.get("title") or "").strip()
    if tmdb_id:
        return "{0}:{1}".format(item.get("kind") or "movie", tmdb_id)
    if imdb:
        return "imdb:{0}".format(imdb)
    if title:
        return "{0}:{1}:{2}".format(item.get("kind") or "movie", title.lower(), item.get("year") or "")
    return ""


def tmdb_language_from_payload(payload, kind):
    """Return (language, show id to look up next)."""
    if not isinstance(payload, dict):
        return "", ""
    if payload.get("original_language") and "results" not in payload and "movie_results" not in payload:
        return str(payload.get("original_language") or ""), ""
    movies = payload.get("movie_results") or []
    shows = payload.get("tv_results") or []
    episodes = payload.get("tv_episode_results") or []
    if "movie_results" in payload or "tv_results" in payload or "tv_episode_results" in payload:
        if kind != "tv" and movies:
            return str(movies[0].get("original_language") or ""), ""
        if shows:
            return str(shows[0].get("original_language") or ""), ""
        if movies:
            return str(movies[0].get("original_language") or ""), ""
        if episodes and episodes[0].get("show_id"):
            return "", str(episodes[0].get("show_id"))
        return "", ""
    results = payload.get("results")
    if isinstance(results, list) and results:
        return str(results[0].get("original_language") or ""), ""
    return "", ""


def _tmdb_get(key, path, params, opener):
    query = dict(params or {})
    headers = {"Accept": "application/json", "User-Agent": "SubtitleEnforcer"}
    if key.startswith("eyJ"):
        headers["Authorization"] = "Bearer " + key
    else:
        query["api_key"] = key
    url = _TMDB_API + path + "?" + urlencode(query)
    request = Request(url, headers=headers)
    with opener(request, timeout=5) as response:
        raw = response.read()
    data = json.loads(raw.decode("utf-8"))
    return data if isinstance(data, dict) else {}


def lookup_tmdb_original_language(key, item, opener=None):
    """Ask TMDB for the original language. The API key is never logged."""
    if not key or not tmdb_item_identity(item):
        return ""
    open_url = opener or urlopen
    kind = item.get("kind") or "movie"
    tmdb_id = str(item.get("tmdb_id") or "").strip()
    imdb = str(item.get("imdb") or "").strip()
    try:
        if tmdb_id.isdigit():
            path = "/tv/{0}".format(tmdb_id) if kind == "tv" else "/movie/{0}".format(tmdb_id)
            payload = _tmdb_get(key, path, {}, open_url)
        elif imdb:
            payload = _tmdb_get(key, "/find/{0}".format(imdb), {"external_source": "imdb_id"}, open_url)
        else:
            params = {"query": item.get("title") or ""}
            if kind == "tv":
                path = "/search/tv"
            else:
                path = "/search/movie"
                if item.get("year"):
                    params["year"] = item["year"]
            payload = _tmdb_get(key, path, params, open_url)
        language, show_id = tmdb_language_from_payload(payload, kind)
        if not language and show_id.isdigit():
            payload = _tmdb_get(key, "/tv/{0}".format(show_id), {}, open_url)
            language = str(payload.get("original_language") or "")
        return language
    except Exception:
        xbmc.log(
            "{0}: TMDB lookup failed".format(ADDON_NAME),
            xbmc.LOGINFO,
        )
        return ""


def _store_tmdb_result(identity, language):
    with _tmdb_lock:
        _tmdb_inflight.discard(identity)
        if language:
            if identity in _tmdb_cache:
                del _tmdb_cache[identity]
            elif len(_tmdb_cache) >= _TMDB_CACHE_MAX:
                oldest = next(iter(_tmdb_cache))
                del _tmdb_cache[oldest]
            _tmdb_cache[identity] = language
            _tmdb_failed.discard(identity)
        else:
            _tmdb_failed.add(identity)


def _start_tmdb_lookup(key, item, identity):
    with _tmdb_lock:
        if identity in _tmdb_cache or identity in _tmdb_failed or identity in _tmdb_inflight:
            return
        _tmdb_inflight.add(identity)

    def _worker():
        language = lookup_tmdb_original_language(key, item)
        _store_tmdb_result(identity, language)

    thread = threading.Thread(target=_worker, name="SubtitleEnforcerTMDB", daemon=True)
    thread.start()


def tmdb_api_pending():
    """True until the playing item's TMDB lookup has finished, when a key is available."""
    key = resolve_tmdb_api_key()
    if not key:
        return False
    item = tmdb_item_query()
    identity = tmdb_item_identity(item)
    if not identity:
        return True
    with _tmdb_lock:
        if identity in _tmdb_cache or identity in _tmdb_failed:
            return False
    _start_tmdb_lookup(key, item, identity)
    return True


def tmdb_api_language():
    """Original language from TMDB cache, starting a background lookup if needed."""
    key = resolve_tmdb_api_key()
    if not key:
        return ""
    item = tmdb_item_query()
    identity = tmdb_item_identity(item)
    if not identity:
        return ""
    with _tmdb_lock:
        if identity in _tmdb_cache:
            return _tmdb_cache[identity]
        if identity in _tmdb_failed:
            return ""
    _start_tmdb_lookup(key, item, identity)
    return ""


def tmdb_titles(query):
    key = resolve_tmdb_api_key()
    query = " ".join(str(query or "").split())
    if not key or len(query) < 2:
        return []
    found = []
    searches = (
        ("tvshow", "/search/tv", ("name", "original_name"), "first_air_date"),
        ("movie", "/search/movie", ("title", "original_title"), "release_date"),
    )
    for kind, path, names, date_key in searches:
        try:
            payload = _tmdb_get(key, path, {"query": query}, urlopen)
        except Exception:
            xbmc.log("{0}: Title search failed".format(ADDON_NAME), xbmc.LOGINFO)
            continue
        for item in (payload.get("results") or [])[:20]:
            if not isinstance(item, dict):
                continue
            title = ""
            for name in names:
                title = str(item.get(name) or "").strip()
                if title:
                    break
            if not title or not item.get("id"):
                continue
            found.append({
                "title": title,
                "year": item.get(date_key) or "",
                "tmdb_id": item.get("id") or "",
                "mediatype": kind,
            })
            if len(found) >= 30:
                return found
    return found
