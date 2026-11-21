# -*- coding: utf-8 -*-
"""Path exception detection and per-show/movie subtitle rules."""

import json
import os
import re

import xbmc

from resources.lib.kodi import (
    ADDON_NAME,
    _clean_year,
    _id_text,
    _imdb_id,
    _info_label,
    _media_kind,
    _string_setting,
    get_item_info,
    json_call,
    rules_file,
)
from resources.lib.languages import LANGUAGE_CHOICES, LANGUAGES, spec_from_text

_EXTRA_DIRS = {
    "extra",
    "extras",
    "featurette",
    "featurettes",
    "interview",
    "interviews",
    "sample",
    "samples",
    "short",
    "shorts",
    "bonus",
    "behind the scenes",
    "behindthescenes",
    "deleted scenes",
    "deletedscenes",
}

_shows_cache = {"path": "", "mtime_ns": None, "shows": []}


def path_segments(path):
    cleaned = (path or "").split("?", 1)[0].split("#", 1)[0]
    return [part.strip() for part in cleaned.replace("\\", "/").split("/") if part.strip()]


def path_stem(path):
    segments = path_segments(path)
    name = segments[-1] if segments else ""
    if "." in name:
        name = name.rsplit(".", 1)[0]
    return name


def path_words(text):
    return [part for part in re.split(r"[^0-9a-z]+", (text or "").lower()) if part]


def is_trailer_path(path):
    segments = path_segments(path)
    if any(segment.lower() in ("trailer", "trailers") for segment in segments[:-1]):
        return True
    words = path_words(path_stem(path))
    return bool(words) and words[-1] in ("trailer", "trailers")


def is_extra_path(path):
    segments = path_segments(path)
    if any(segment.lower() in _EXTRA_DIRS for segment in segments[:-1]):
        return True
    stem = path_stem(path).lower().replace("_", " ").replace(".", " ").replace("-", " ")
    if any(phrase in stem for phrase in ("behind the scenes", "deleted scene", "deleted scenes")):
        return True
    words = path_words(path_stem(path))
    return bool(words) and words[-1] in ("sample", "featurette", "interview", "extra")


def parse_show_rules(text):
    """Parse 'Show = ger' lines. A bare name means leave that show alone."""
    rules = []
    for chunk in re.split(r"[\n;]+", text or ""):
        chunk = chunk.strip()
        if not chunk or chunk.startswith("#"):
            continue
        if "=" in chunk:
            name, action = chunk.split("=", 1)
            name = name.strip().lower()
            action = action.strip().lower() or "skip"
        else:
            name = chunk.lower()
            action = "skip"
        if name:
            rules.append((name, action))
    return rules


def _loose_title(text):
    return " ".join(path_words(text))


def title_match(rule, candidate):
    rule_name = _loose_title(rule)
    candidate_name = _loose_title(candidate)
    if not rule_name or not candidate_name:
        return False
    if candidate_name == rule_name:
        return True
    if candidate_name.startswith(rule_name + " "):
        rest = candidate_name[len(rule_name):].strip()
        if re.fullmatch(r"(19|20)\d{2}", rest):
            return True
    return False


def match_show_rule(showtitle, path, rules):
    """Match the library title, or a parent folder such as Show/Season/episode."""
    candidates = [showtitle]
    candidates.extend(path_segments(path)[:-1])
    for rule_name, action in rules:
        for candidate in candidates:
            if title_match(rule_name, candidate):
                return action
    return None


def legacy_shows_from_setting():
    """One-time import of the old Show rules text box."""
    shows = []
    for name, action in parse_show_rules(_string_setting("show_rules", "")):
        shows.append({
            "title": name,
            "action": action,
            "tmdb_id": "",
            "year": "",
        })
    return shows


def load_saved_shows():
    path = rules_file()
    if path and os.path.isfile(path):
        try:
            mtime_ns = os.stat(path).st_mtime_ns
        except OSError:
            mtime_ns = None
        if (
            _shows_cache["path"] == path
            and mtime_ns is not None
            and _shows_cache["mtime_ns"] == mtime_ns
        ):
            return list(_shows_cache["shows"])
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            xbmc.log("{0}: Could not read saved TV shows".format(ADDON_NAME), xbmc.LOGINFO)
            return []
        shows = data.get("shows") if isinstance(data, dict) else None
        if not isinstance(shows, list):
            return []
        cleaned = [
            show for show in shows
            if isinstance(show, dict) and (show.get("title") or "").strip()
        ]
        _shows_cache["path"] = path
        _shows_cache["mtime_ns"] = mtime_ns
        _shows_cache["shows"] = cleaned
        return list(cleaned)
    shows = legacy_shows_from_setting()
    save_saved_shows(shows)
    return shows


def save_saved_shows(shows):
    path = rules_file()
    if not path:
        return False
    folder = os.path.dirname(path)
    tmp_path = path + ".tmp"
    try:
        os.makedirs(folder, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump({"shows": shows}, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
        try:
            mtime_ns = os.stat(path).st_mtime_ns
        except OSError:
            mtime_ns = None
        _shows_cache["path"] = path
        _shows_cache["mtime_ns"] = mtime_ns
        _shows_cache["shows"] = list(shows)
        return True
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        xbmc.log("{0}: Could not save TV shows".format(ADDON_NAME), xbmc.LOGINFO)
        return False


def _normalize_show(show):
    if not isinstance(show, dict):
        return None
    title = " ".join(str(show.get("title") or "").split())
    if not title:
        return None
    entry = {
        "title": title,
        "action": (show.get("action") or "default").strip().lower(),
    }
    for field, value in (
        ("year", _clean_year(show.get("year"))),
        ("mediatype", _media_kind(show.get("mediatype"))),
        ("tmdb_id", _id_text(show.get("tmdb_id"))),
        ("imdb", _imdb_id(show.get("imdb"))),
        ("library_id", _id_text(show.get("library_id"))),
    ):
        if value:
            entry[field] = value
    return entry


def show_rule_key(show):
    """Identity used to replace one saved show or movie."""
    show = _normalize_show(show) or {}
    title = _loose_title(show.get("title"))
    kind = show.get("mediatype") or ""
    if show.get("tmdb_id") and kind:
        return "tmdb:{0}:{1}".format(kind, show["tmdb_id"])
    if show.get("imdb"):
        return "imdb:{0}".format(show["imdb"].lower())
    if show.get("library_id") and kind:
        return "library:{0}:{1}".format(kind, show["library_id"])
    if show.get("year"):
        return "title:{0}:{1}:{2}".format(kind, title, show["year"])
    if show.get("tmdb_id"):
        return "tmdb:{0}".format(show["tmdb_id"])
    return "name:{0}".format(title)


def _specific_show(show):
    return bool(show.get("tmdb_id") or show.get("imdb") or show.get("library_id") or show.get("year"))


def upsert_show_rule(shows, show):
    """Replace the saved rule with the same show, movie, or title."""
    entry = _normalize_show(show)
    if entry is None:
        return [_normalize_show(item) or item for item in shows or [] if _normalize_show(item)]
    existing = [item for item in (_normalize_show(row) for row in shows or []) if item]
    if not _specific_show(entry):
        same_name = [item for item in existing if _loose_title(item.get("title")) == _loose_title(entry["title"])]
        if len(same_name) == 1:
            for field in ("year", "mediatype", "tmdb_id", "imdb", "library_id"):
                if same_name[0].get(field) and not entry.get(field):
                    entry[field] = same_name[0][field]
            entry["title"] = same_name[0]["title"]
    key = show_rule_key(entry)
    kept = [item for item in existing if show_rule_key(item) != key]
    kept.append(entry)
    return kept


def delete_show_rule(shows, index):
    if index < 0 or index >= len(shows or []):
        return list(shows or [])
    return [show for number, show in enumerate(shows) if number != index]


def candidate_titles(info):
    """Show or movie names, plus parent folders. Episode titles are not included."""
    info = info or {}
    kind = info.get("mediatype") or ""
    showtitle = (info.get("showtitle") or "").strip()
    title = (info.get("title") or "").strip()
    titles = []
    if kind == "movie":
        if title:
            titles.append(title)
        if showtitle and showtitle not in titles:
            titles.append(showtitle)
    elif showtitle:
        titles.append(showtitle)
    elif title and kind != "tvshow":
        titles.append(title)
    for segment in path_segments(info.get("path"))[:-1]:
        if segment not in titles:
            titles.append(segment)
    return titles


def _kind_ok(show, info, allow_unknown):
    rule_type = show.get("mediatype") or ""
    info_type = info.get("mediatype") or ""
    if rule_type not in ("tvshow", "movie"):
        return True
    if info_type not in ("tvshow", "movie"):
        return allow_unknown
    return rule_type == info_type


def _ids_match(show, info):
    if not _kind_ok(show, info, False):
        return False
    if show.get("library_id") and str(info.get("library_id") or "") == str(show.get("library_id")):
        return True
    if show.get("tmdb_id") and str(info.get("tmdb") or "") == str(show.get("tmdb_id")):
        return True
    imdb = str(show.get("imdb") or "").lower()
    if imdb and imdb == str(info.get("imdb") or "").lower():
        return True
    return False


def _id_conflict(show, info):
    if show.get("tmdb_id") and info.get("tmdb") and str(show.get("tmdb_id")) != str(info.get("tmdb")):
        return True
    if show.get("imdb") and info.get("imdb") and str(show.get("imdb")).lower() != str(info.get("imdb")).lower():
        return True
    if (
        show.get("library_id")
        and info.get("library_id")
        and str(show.get("library_id")) != str(info.get("library_id"))
        and _kind_ok(show, info, False)
    ):
        return True
    return False


def _years_in_titles(rule_name, titles):
    wanted = _loose_title(rule_name)
    years = []
    for title in titles:
        candidate = _loose_title(title)
        if not wanted or not candidate.startswith(wanted + " "):
            continue
        rest = candidate[len(wanted):].strip()
        if re.fullmatch(r"(19|20)\d{2}", rest):
            years.append(rest)
    return years


def _title_matches_specific(show, info):
    if _id_conflict(show, info) or not _kind_ok(show, info, True):
        return False
    titles = candidate_titles(info)
    if not any(title_match(show.get("title"), title) for title in titles):
        return False
    year = str(show.get("year") or "")
    if not year:
        return True
    info_year = str(info.get("year") or "")
    if info_year:
        return info_year == year
    found = _years_in_titles(show.get("title"), titles)
    if found:
        return year in found
    return True


def match_show_info(info, shows):
    """A linked show or movie wins. A name with no link still matches that name."""
    normalized = [item for item in (_normalize_show(show) for show in shows or []) if item]
    specific = [show for show in normalized if _specific_show(show)]
    plain = [show for show in normalized if not _specific_show(show)]
    for show in specific:
        if _ids_match(show, info):
            return show.get("action") or ""
    titled = [show for show in specific if _title_matches_specific(show, info)]
    if len(titled) == 1:
        return titled[0].get("action") or ""
    if len(titled) > 1:
        return None
    for show in plain:
        for title in candidate_titles(info):
            if title_match(show.get("title"), title):
                return show.get("action") or ""
    return None


def match_saved_show(showtitle, path, shows, tmdb_id=""):
    """Match a saved show by TMDB id, library title, or a parent folder."""
    return match_show_info({
        "showtitle": showtitle or "",
        "title": "",
        "path": path or "",
        "year": "",
        "mediatype": "tvshow" if (showtitle or tmdb_id) else "",
        "tmdb": _id_text(tmdb_id),
        "imdb": "",
        "library_id": "",
    }, shows)


def show_query_matches(title, query):
    words = path_words(query)
    haystack = path_words(title)
    return bool(words) and all(word in haystack for word in words)


def merge_show_hits(library, tmdb, limit=40):
    """Library matches come first. The same title and year is listed once."""
    hits = []
    seen = set()
    for source, rows in (("Library", library or []), ("TMDB", tmdb or [])):
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = (row.get("title") or "").strip()
            if not title:
                continue
            year = _clean_year(row.get("year"))
            kind = _media_kind(row.get("mediatype"))
            key = (_loose_title(title), year, kind)
            if key in seen:
                continue
            seen.add(key)
            hits.append({
                "title": title,
                "year": year,
                "tmdb_id": _id_text(row.get("tmdb_id")),
                "imdb": _imdb_id(row.get("imdb")),
                "library_id": _id_text(row.get("library_id")),
                "mediatype": kind,
                "source": source,
            })
            if len(hits) >= limit:
                return hits
    return hits


def search_tv_shows(query, library, tmdb):
    if not path_words(query):
        return []

    def keep(rows):
        return [
            row for row in rows or []
            if isinstance(row, dict) and show_query_matches(row.get("title") or "", query)
        ]

    return merge_show_hits(keep(library), keep(tmdb))


def show_hit_label(hit):
    title = hit.get("title") or ""
    if hit.get("year"):
        title = "{0} ({1})".format(title, hit["year"])
    kind = {"tvshow": "TV", "movie": "Movie"}.get(hit.get("mediatype") or "")
    parts = [title]
    if kind:
        parts.append(kind)
    source = hit.get("source") or ""
    if source:
        parts.append(source)
    return " — ".join(part for part in parts if part)


def saved_show_label(show):
    names = {
        "off": "Subtitles off",
        "none": "Subtitles off",
        "disable": "Subtitles off",
        "default": "Default language",
        "original": "Original language",
        "kodi": "Kodi subtitle language",
        "skip": "Leave unchanged",
        "leave": "Leave unchanged",
        "ignore": "Leave unchanged",
    }
    action = (show.get("action") or "").strip().lower()
    if action in names:
        language = names[action]
    else:
        spec = spec_from_text(action)
        language = spec["label"] if spec is not None else action
    title = show.get("title") or ""
    if show.get("year") and show.get("year") not in title:
        title = "{0} ({1})".format(title, show["year"])
    kind = {"tvshow": "TV", "movie": "Movie"}.get(show.get("mediatype") or "")
    if kind:
        title = "{0} · {1}".format(title, kind)
    return "{0} — {1}".format(title, language)


def show_language_choices():
    return [
        ("default", "Default language"),
        ("original", "Original language"),
        ("off", "Subtitles off"),
        ("leave", "Leave unchanged"),
        ("kodi", "Kodi subtitle language"),
    ] + [
        (code, LANGUAGES[code]["label"]) for code in LANGUAGE_CHOICES
    ] + [
        ("custom", "Custom"),
    ]


def _one_show_priority(code, label):
    return [{
        "slot": 0,
        "code": code,
        "label": label,
        "allow_hi": False,
        "allow_sdh": False,
        "allow_forced": False,
        "understand": False,
        "custom": "",
        "force_only": False,
        "show_override": True,
    }]


def show_override_priorities(action):
    """Return 'skip', 'off', or a one-language priority list."""
    action = (action or "skip").strip().lower()
    if action in ("skip", "ignore", "leave", "unchanged"):
        return "skip"
    if action in ("off", "none", "disable"):
        return "off"
    if action == "original":
        return _one_show_priority("original", "Original language")
    if action == "default":
        return _one_show_priority("default", "Default language")
    if action == "kodi":
        return _one_show_priority("kodi", "Kodi subtitle language")
    spec = spec_from_text(action)
    if spec is None:
        return "skip"
    return [{
        "slot": 0,
        "code": "custom",
        "label": spec["label"],
        "spec": spec,
        "allow_hi": False,
        "allow_sdh": False,
        "allow_forced": False,
        "understand": False,
        "custom": action,
        "force_only": False,
        "show_override": True,
    }]


def _library_details(method, id_name, details_name, item_id, properties):
    item_id = _id_text(item_id)
    if not item_id:
        return {}
    result = json_call(method, {
        id_name: int(item_id),
        "properties": properties,
    })
    if not isinstance(result, dict):
        return {}
    details = result.get(details_name)
    return details if isinstance(details, dict) else {}


def _library_hit(item, mediatype, id_field):
    unique = item.get("uniqueid") if isinstance(item.get("uniqueid"), dict) else {}
    return {
        "title": item.get("title") or item.get("label") or "",
        "year": item.get("year") or item.get("premiered") or "",
        "tmdb_id": unique.get("tmdb") or "",
        "imdb": unique.get("imdb") or item.get("imdbnumber") or "",
        "library_id": item.get(id_field) or "",
        "mediatype": mediatype,
    }


def library_titles(query):
    """TV shows and movies in the Kodi library whose title contains the query."""
    query = " ".join(str(query or "").split())
    if len(query) < 2:
        return []
    filt = {"field": "title", "operator": "contains", "value": query}
    properties = ["title", "year", "premiered", "uniqueid", "imdbnumber"]
    limits = {"start": 0, "end": 25}
    shows = json_call("VideoLibrary.GetTVShows", {
        "filter": filt,
        "properties": properties,
        "limits": limits,
    })
    movies = json_call("VideoLibrary.GetMovies", {
        "filter": filt,
        "properties": properties,
        "limits": limits,
    })
    rows = []
    for item in (shows.get("tvshows") if isinstance(shows, dict) else []) or []:
        if isinstance(item, dict):
            rows.append(_library_hit(item, "tvshow", "tvshowid"))
    for item in (movies.get("movies") if isinstance(movies, dict) else []) or []:
        if isinstance(item, dict):
            rows.append(_library_hit(item, "movie", "movieid"))
    return rows


def playback_rule_info(playerid, path, showtitle, item=None):
    """Show or movie identity for the video that is playing."""
    if item is None:
        item = get_item_info(playerid) if playerid is not None else {}
    file_path = path or item.get("file") or ""
    title = (item.get("title") or _info_label("VideoPlayer.Title") or "").strip()
    show = (showtitle or item.get("showtitle") or _info_label("VideoPlayer.TvShowTitle") or "").strip()
    dbtype = str(item.get("type") or _info_label("VideoPlayer.DBType") or "").lower()
    unique = item.get("uniqueid") if isinstance(item.get("uniqueid"), dict) else {}
    imdb = _imdb_id(
        item.get("imdbnumber")
        or unique.get("imdb")
        or _info_label("VideoPlayer.IMDBNumber")
        or _info_label("VideoPlayer.UniqueID(imdb)")
    )
    year = _clean_year(item.get("year") or item.get("premiered") or _info_label("VideoPlayer.Year"))
    tmdb = ""
    library_id = ""
    detail_properties = ["title", "year", "premiered", "uniqueid", "imdbnumber"]
    if dbtype in ("episode", "season", "tvshow") or show:
        kind = "tvshow"
        library_id = _id_text(item.get("tvshowid") or _info_label("VideoPlayer.TvShowDBID"))
        if dbtype == "tvshow" and not library_id:
            library_id = _id_text(item.get("id") or _info_label("VideoPlayer.DBID"))
        details = _library_details(
            "VideoLibrary.GetTVShowDetails",
            "tvshowid",
            "tvshowdetails",
            library_id,
            detail_properties,
        )
        year = ""
        if details:
            show = (details.get("title") or show).strip()
            year = _clean_year(details.get("year") or details.get("premiered"))
            dunique = details.get("uniqueid") if isinstance(details.get("uniqueid"), dict) else {}
            tmdb = _id_text(dunique.get("tmdb"))
            imdb = _imdb_id(dunique.get("imdb") or details.get("imdbnumber")) or imdb
        if not tmdb:
            tmdb = _id_text(_info_label("VideoPlayer.UniqueID(tvshow.tmdb)"))
            if dbtype == "tvshow":
                tmdb = tmdb or _id_text(unique.get("tmdb"))
    elif dbtype == "movie":
        kind = "movie"
        library_id = _id_text(item.get("id") or _info_label("VideoPlayer.DBID"))
        details = _library_details(
            "VideoLibrary.GetMovieDetails",
            "movieid",
            "moviedetails",
            library_id,
            detail_properties,
        )
        if details:
            title = (details.get("title") or title).strip()
            year = _clean_year(details.get("year") or details.get("premiered")) or year
            dunique = details.get("uniqueid") if isinstance(details.get("uniqueid"), dict) else {}
            tmdb = _id_text(dunique.get("tmdb"))
            imdb = _imdb_id(dunique.get("imdb") or details.get("imdbnumber")) or imdb
        if not tmdb:
            tmdb = _id_text(unique.get("tmdb") or _info_label("VideoPlayer.UniqueID(tmdb)"))
    else:
        kind = ""
        tmdb = _id_text(unique.get("tmdb") or _info_label("VideoPlayer.UniqueID(tmdb)"))
    return {
        "showtitle": show,
        "title": title,
        "path": file_path,
        "year": year,
        "mediatype": kind,
        "tmdb": tmdb,
        "imdb": imdb,
        "library_id": library_id,
    }
