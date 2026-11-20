# -*- coding: utf-8 -*-
"""
Subtitle Enforcer service add-on for Kodi.

When a video starts, enables the first available subtitle from up to five
language priorities. If the audio is a language the user understands, it can
instead use a forced subtitle or turn subtitles off. Each language can also
accept hearing impaired (HI), SDH, and forced tracks. Optionally seeks
backward after playback starts so Kodi draws embedded subtitles that stay
hidden until a manual seek.
"""

import json
import os
import re
import sys
import time
import traceback
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import xbmc
import xbmcaddon
import xbmcgui

ADDON_ID = "service.subtitle.enforcer"
try:
    ADDON = xbmcaddon.Addon(ADDON_ID)
except TypeError:
    ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo("name") or "Subtitle Enforcer"

# How long to wait for subtitle streams to show up and settle.
SUBTITLE_WAIT = 15.0
STABLE_SECONDS = 1.5
# Playback at or past this time is treated as a resume, not a fresh start.
START_WINDOW = 2.0
# A forward jump larger than this, before the seek runs, is a resume.
RESUME_JUMP = 10.0

# code, label, extra ISO codes, name stems, special matcher
# Codes are matched against the stream language. Stems are matched against
# the track name. Two-letter codes are not matched inside track names, so
# "HI" does not get treated as Hindi and "no" does not get treated as Norwegian.
_LANGUAGE_ROWS = (
    ("ara", "Arabic", "ar", "arabic", ""),
    ("bul", "Bulgarian", "bg", "bulgarian", ""),
    ("cat", "Catalan", "ca", "catalan", ""),
    ("chi", "Chinese", "zho zh", "chinese", ""),
    ("zhs", "Chinese (Simplified)", "zh-cn zh-sg zh-hans chs", "", "simplified"),
    ("zht", "Chinese (Traditional)", "zh-tw zh-hk zh-mo zh-hant cht", "", "traditional"),
    ("hrv", "Croatian", "hr", "croatian", ""),
    ("cze", "Czech", "ces cs", "czech", ""),
    ("dan", "Danish", "da", "danish", ""),
    ("dut", "Dutch", "nld nl", "dutch", ""),
    ("eng", "English", "en", "english", ""),
    ("est", "Estonian", "et", "estonian", ""),
    ("fin", "Finnish", "fi", "finnish", ""),
    ("fre", "French", "fra fr", "french", ""),
    ("ger", "German", "deu de", "german", ""),
    ("gre", "Greek", "ell el", "greek", ""),
    ("heb", "Hebrew", "he", "hebrew", ""),
    ("hin", "Hindi", "hi", "hindi", ""),
    ("hun", "Hungarian", "hu", "hungarian", ""),
    ("ice", "Icelandic", "isl is", "icelandic", ""),
    ("ind", "Indonesian", "id", "indonesian", ""),
    ("ita", "Italian", "it", "italian", ""),
    ("jpn", "Japanese", "ja", "japanese", ""),
    ("kor", "Korean", "ko", "korean", ""),
    ("lav", "Latvian", "lv", "latvian", ""),
    ("lit", "Lithuanian", "lt", "lithuanian", ""),
    ("may", "Malay", "msa ms", "malay", ""),
    ("nor", "Norwegian", "nob nno no", "norwegian", ""),
    ("per", "Persian", "fas fa", "persian|farsi", ""),
    ("pol", "Polish", "pl", "polish", ""),
    ("por", "Portuguese", "pt", "portuguese", ""),
    ("pob", "Portuguese (Brazil)", "pt-br pb", "", "brazilian"),
    ("rum", "Romanian", "ron ro", "romanian", ""),
    ("rus", "Russian", "ru", "russian", ""),
    ("srp", "Serbian", "sr", "serbian", ""),
    ("slo", "Slovak", "slk sk", "slovak", ""),
    ("slv", "Slovenian", "sl", "slovenian|slovene", ""),
    ("spa", "Spanish", "es", "spanish", ""),
    ("swe", "Swedish", "sv", "swedish", ""),
    ("tha", "Thai", "th", "thai", ""),
    ("tur", "Turkish", "tr", "turkish", ""),
    ("ukr", "Ukrainian", "uk", "ukrainian", ""),
    ("vie", "Vietnamese", "vi", "vietnamese", ""),
)

LANGUAGES = {}
LANGUAGE_CHOICES = []
for _code, _label, _extra, _names, _match in _LANGUAGE_ROWS:
    LANGUAGES[_code] = {
        "label": _label,
        "codes": frozenset([_code] + _extra.split()),
        "names": tuple(part for part in _names.split("|") if part),
        "match": _match,
    }
    LANGUAGE_CHOICES.append(_code)


def language_options():
    """Setting values in the same order as the language lists."""
    return [
        ("off", "Off"),
        ("original", "Original language"),
        ("default", "Default language"),
        ("kodi", "Kodi subtitle language"),
        ("custom", "Custom"),
    ] + [
        (code, LANGUAGES[code]["label"]) for code in LANGUAGE_CHOICES
    ]


def spec_from_text(text):
    """Build a language spec from a name or code, including ones not in the list."""
    raw = _normalize_language(text)
    if not raw or raw in ("off", "none", "custom", "kodi", "default", "original", "forced_only"):
        return None
    for code in LANGUAGE_CHOICES:
        spec = LANGUAGES[code]
        if (
            raw == code
            or raw in spec["codes"]
            or raw in spec["names"]
            or raw == spec["label"].lower()
        ):
            return spec
    codes = {raw}
    base = raw.split("-", 1)[0]
    if base and base != raw:
        codes.add(base)
    names = (raw,) if (" " in raw or len(raw) > 3) else ()
    label = (text or "").strip() or raw
    return {
        "label": label,
        "codes": frozenset(codes),
        "names": names,
        "match": "",
    }


def gui_language_code():
    formats = (
        getattr(xbmc, "ISO_639_2", None),
        getattr(xbmc, "ISO_639_1", None),
        getattr(xbmc, "ENGLISH_NAME", None),
    )
    for fmt in formats:
        if fmt is None:
            continue
        try:
            value = xbmc.getLanguage(fmt)
        except Exception:
            value = ""
        value = (value or "").strip()
        if value:
            return value
    return ""


def read_kodi_subtitle_setting():
    """Return Kodi's subtitle language, '' when it is unset, or None if unread."""
    result = json_call("Settings.GetSettingValue", {"setting": "locale.subtitlelanguage"})
    if isinstance(result, dict) and "value" in result:
        return str(result.get("value") or "").strip().lower()
    if isinstance(result, str):
        return result.strip().lower()
    return None


def _info_label(name):
    try:
        return (xbmc.getInfoLabel(name) or "").strip()
    except Exception:
        return ""


def _tmdb_property(name):
    return _info_label("Window(home).Property(TMDbHelper.Player.{0})".format(name))


def tmdbhelper_installed():
    try:
        return bool(xbmc.getCondVisibility("System.HasAddon(plugin.video.themoviedb.helper)"))
    except Exception:
        return False


def tmdbhelper_service_started():
    return _info_label("Window(home).Property(TMDbHelper.ServiceStarted)").lower() == "true"


def _specs_agree(left, right):
    """True when two specs are the same language, including zh and zh-CN."""
    if left is None or right is None:
        return False
    if left["label"].lower() == right["label"].lower():
        return True
    if left["codes"] & right["codes"]:
        return True
    if set(left["names"]) & set(right["names"]):
        return True
    for spec, other in ((left, right), (right, left)):
        for code in spec["codes"]:
            base = code.split("-", 1)[0]
            if base != code and base in other["codes"]:
                return True
    return False


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


_TMDB_API = "https://api.themoviedb.org/3"
_tmdb_cache = {"identity": None, "language": ""}
_tmdbhelper_key_cache = {"loaded": False, "key": ""}


def clear_tmdb_cache():
    _tmdb_cache["identity"] = None
    _tmdb_cache["language"] = ""
    _tmdbhelper_key_cache["loaded"] = False
    _tmdbhelper_key_cache["key"] = ""


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


def read_tmdbhelper_api_key():
    if _tmdbhelper_key_cache["loaded"]:
        return _tmdbhelper_key_cache["key"]
    key = _read_tmdbhelper_api_key_uncached()
    _tmdbhelper_key_cache["loaded"] = True
    _tmdbhelper_key_cache["key"] = key
    return key


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


def tmdb_api_pending():
    """True until the playing item can be looked up, when a TMDB key is available."""
    if not resolve_tmdb_api_key():
        return False
    return not tmdb_item_identity(tmdb_item_query())


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


def tmdb_api_language():
    """Original language from TMDB, looked up once per playing item."""
    key = resolve_tmdb_api_key()
    if not key:
        return ""
    item = tmdb_item_query()
    identity = tmdb_item_identity(item)
    if not identity:
        return ""
    if _tmdb_cache.get("identity") == identity:
        return _tmdb_cache.get("language") or ""
    language = lookup_tmdb_original_language(key, item)
    _tmdb_cache["identity"] = identity
    _tmdb_cache["language"] = language
    return language


def _file_original_language(audiostreams):
    """Language from the file or the Kodi library, before TMDBHelper is checked."""
    streams = []
    if isinstance(audiostreams, list):
        streams = [stream for stream in audiostreams if isinstance(stream, dict)]
    for stream in streams:
        if not _flag(stream.get("isoriginal")):
            continue
        text = (stream.get("language") or stream.get("name") or "").strip()
        if text:
            return text
    for label in ("VideoPlayer.OriginalLanguage", "ListItem.OriginalLanguage"):
        text = _info_label(label)
        if text:
            return text
    if len(streams) == 1:
        return (streams[0].get("language") or streams[0].get("name") or "").strip()
    return ""


def prefer_original_text(metadata, tmdb):
    """Use TMDBHelper when the two languages disagree. A regional match is kept."""
    metadata = (metadata or "").strip()
    tmdb = (tmdb or "").strip()
    if not tmdb:
        return metadata
    if not metadata:
        return tmdb
    meta_spec = spec_from_text(metadata)
    tmdb_spec = spec_from_text(tmdb)
    if meta_spec is not None and tmdb_spec is not None and _specs_agree(meta_spec, tmdb_spec):
        if meta_spec.get("match") and not tmdb_spec.get("match"):
            return metadata
        return tmdb
    xbmc.log(
        "{0}: Original language is {1} in local metadata and {2} from TMDB. Using TMDB.".format(
            ADDON_NAME, metadata, tmdb
        ),
        xbmc.LOGINFO,
    )
    return tmdb


def original_language_text(audiostreams):
    """Return the film's language, not the dubbed track that is playing.

    An audio track marked original is used first, then the library language,
    then a file with only one audio track. TMDB is checked against that
    result, and its language wins when the two disagree.
    """
    return prefer_original_text(
        _file_original_language(audiostreams),
        tmdb_api_language() or tmdbhelper_language(),
    )


def original_language_pending(audiostreams):
    """True until Kodi has reported an audio track with a language."""
    if not isinstance(audiostreams, list) or not audiostreams:
        return True
    for stream in audiostreams:
        if not isinstance(stream, dict):
            continue
        if _flag(stream.get("isoriginal")):
            return False
        if (stream.get("language") or stream.get("name") or "").strip():
            return False
    return True


def default_language_text(audiostreams):
    """Language of the audio track the file marks as default.

    This is the file's own default, not the track that happens to be playing
    and not Kodi's interface language.
    """
    streams = []
    if isinstance(audiostreams, list):
        streams = [stream for stream in audiostreams if isinstance(stream, dict)]
    for stream in streams:
        if not _flag(stream.get("isdefault")):
            continue
        text = (stream.get("language") or stream.get("name") or "").strip()
        if text:
            return text
    for stream in streams:
        text = (stream.get("language") or stream.get("name") or "").strip()
        if text:
            return text
    return ""


def resolve_kodi_spec(setting_value, audio, audiostreams):
    """Return (spec, forced_only) for Kodi's subtitle language. spec None skips it."""
    value = (setting_value or "").strip().lower()
    if value in ("", "none"):
        return None, False
    if value == "forced_only":
        return spec_from_text(gui_language_code()), True
    if value == "default":
        return spec_from_text(gui_language_code()), False
    if value == "original":
        return spec_from_text(original_language_text(audiostreams)), False
    return spec_from_text(value), False


def resolve_priorities(priorities, audio, audiostreams, kodi_setting, timed_out):
    """Return resolved priorities, whether to keep waiting, and a Kodi 'none' hit."""
    resolved = []
    explicit_none = False
    for pref in priorities:
        code = pref.get("code")
        force_only = bool(pref.get("force_only"))
        spec = None
        if code == "kodi":
            if kodi_setting is None and not timed_out:
                return [], True, False
            if kodi_setting is None:
                continue
            if kodi_setting in ("", "none"):
                explicit_none = True
                continue
            if kodi_setting == "original":
                code = "original"
            else:
                spec, forced = resolve_kodi_spec(kodi_setting, audio, audiostreams)
                force_only = forced or force_only
        if code == "original":
            if tmdb_api_pending() and not timed_out:
                return [], True, False
            api_language = tmdb_api_language()
            helper_language = "" if api_language else tmdbhelper_language()
            if not api_language and not helper_language and tmdbhelper_lookup_pending() and not timed_out:
                return [], True, False
            if (
                not api_language
                and not helper_language
                and original_language_pending(audiostreams)
                and not timed_out
            ):
                return [], True, False
            tmdb_lang = api_language or helper_language
            spec = spec_from_text(prefer_original_text(_file_original_language(audiostreams), tmdb_lang))
        elif code == "default":
            if original_language_pending(audiostreams) and not timed_out:
                return [], True, False
            spec = spec_from_text(default_language_text(audiostreams))
        elif spec is None and pref.get("spec"):
            spec = pref["spec"]
        elif spec is None and code == "custom":
            spec = spec_from_text(pref.get("custom"))
        elif spec is None:
            spec = LANGUAGES.get(code)
        if spec is None:
            continue
        item = dict(pref)
        item["spec"] = spec
        item["label"] = spec["label"]
        item["force_only"] = force_only
        resolved.append(item)
    return resolved, False, explicit_none


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


def path_segments(path):
    cleaned = (path or "").split("?", 1)[0].split("#", 1)[0]
    return [part.strip() for part in cleaned.replace("\\", "/").split("/") if part.strip()]


def path_stem(path):
    name = path_segments(path)[-1] if path_segments(path) else ""
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


def _clean_year(year):
    year = str(year or "").strip()
    if len(year) >= 4 and year[:4].isdigit():
        year = year[:4]
    if year.isdigit() and year != "0":
        return year
    return ""


def addon_profile_dir():
    override = os.environ.get("SUBTITLE_ENFORCER_PROFILE")
    if override:
        return override
    try:
        import xbmcvfs
        profile = ""
        try:
            profile = ADDON.getAddonInfo("profile") or ""
        except Exception:
            profile = ""
        target = profile or "special://profile/addon_data/{0}".format(ADDON_ID)
        translated = xbmcvfs.translatePath(target)
        if translated:
            return translated
    except Exception:
        pass
    return ""


def rules_file():
    folder = addon_profile_dir()
    if not folder:
        return ""
    return os.path.join(folder, "show_rules.json")


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


_shows_cache = {"path": "", "mtime_ns": None, "shows": []}


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


def _id_text(value):
    text = str(value or "").strip()
    if text.isdigit() and int(text) > 0:
        return str(int(text))
    return ""


def _imdb_id(value):
    text = str(value or "").strip()
    if len(text) > 2 and text[:2].lower() == "tt" and text[2:].isdigit():
        return "tt" + text[2:]
    return ""


def _media_kind(value):
    kind = str(value or "").strip().lower()
    if kind in ("episode", "season", "tv", "show", "tvshow"):
        return "tvshow"
    if kind == "movie":
        return "movie"
    return ""


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


def _token(text, word):
    return re.search(
        r"(?:^|[^a-z0-9])" + re.escape(word) + r"(?:[^a-z0-9]|$)",
        text,
    ) is not None


def _normalize_language(value):
    return (value or "").strip().lower().replace("_", "-")


def _stream_text(stream):
    language = _normalize_language(stream.get("language"))
    name = (stream.get("name") or "").strip().lower()
    return language, name


def _field_matches_codes(language, codes):
    if not language:
        return False
    if language in codes:
        return True
    base = language.split("-", 1)[0]
    return base != language and base in codes


def _name_has_code(name, codes):
    for code in codes:
        # Two-letter codes collide with tags such as HI and words such as "no".
        if len(code) < 3:
            continue
        if _token(name, code):
            return True
    return False


def _name_matches_stem(name, names):
    for stem in names:
        if (
            name == stem
            or name.startswith(stem + " ")
            or name.startswith(stem + "(")
            or name.startswith(stem + "[")
            or name.startswith(stem + "-")
            or name.startswith(stem + ":")
            or name.startswith(stem + ".")
        ):
            return True
    return False


def _is_simplified(language, name):
    if language in {"zhs", "zh-cn", "zh-sg", "zh-hans", "chs", "sc"}:
        return True
    if "hans" in language:
        return True
    return "simplified" in name or _token(name, "hans")


def _is_traditional(language, name):
    if language in {"zht", "zh-tw", "zh-hk", "zh-mo", "zh-hant", "cht", "tc"}:
        return True
    if "hant" in language:
        return True
    return "traditional" in name or _token(name, "hant")


def _is_brazilian(language, name):
    if language in {"pob", "pt-br", "pb", "por-br"}:
        return True
    return "brazil" in name


def language_matches(stream, spec):
    language, name = _stream_text(stream)
    kind = spec["match"]
    if kind == "simplified":
        return _is_simplified(language, name) or _name_has_code(name, spec["codes"])
    if kind == "traditional":
        return _is_traditional(language, name) or _name_has_code(name, spec["codes"])
    if kind == "brazilian":
        return _is_brazilian(language, name) or _name_has_code(name, spec["codes"])
    if _field_matches_codes(language, spec["codes"]) or language in spec["names"]:
        return True
    if _name_matches_stem(name, spec["names"]):
        return True
    return _name_has_code(name, spec["codes"])


def _flag(value):
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def classify(stream):
    """Return forced, named HI, named SDH, and the hearing-impaired flag.

    Kodi exposes one hearing-impaired flag for both HI and SDH. The track
    name is used to tell them apart. A flag with neither name is accepted
    by either checkbox.
    """
    _language, name = _stream_text(stream)
    forced = _flag(stream.get("isforced")) or _token(name, "forced")
    named_sdh = _token(name, "sdh") or "hard of hearing" in name or "hard-of-hearing" in name
    named_hi = (
        _token(name, "hi")
        or "hearing impaired" in name
        or "hearing-impaired" in name
        or "closed caption" in name
        or _token(name, "cc")
    )
    impaired = _flag(stream.get("isimpaired"))
    return forced, named_hi, named_sdh, impaired


def _short_label(name):
    # Filenames contain a dot and often include the movie title, so a word
    # like "song" or "signs" in the title is not a track type.
    return "." not in name and len(name) <= 48


def extra_kind(stream):
    """Commentary, songs, and signs tracks are a last resort.

    A signs track is still eligible immediately when forced subtitles are
    the goal, because those tracks are usually the forced signs.
    """
    _language, name = _stream_text(stream)
    if _token(name, "commentary") or _token(name, "commentaries"):
        return "commentary"
    signs_phrase = (
        "signs & songs" in name
        or "signs and songs" in name
        or "signs/songs" in name
    )
    if signs_phrase or (_token(name, "signs") and _short_label(name)):
        return "signs"
    if (
        _token(name, "lyrics")
        or _token(name, "karaoke")
        or "sing-along" in name
        or "sing along" in name
        or (_token(name, "songs") and (_short_label(name) or "(" in name or "[" in name))
        or (_token(name, "song") and _short_label(name))
    ):
        return "songs"
    return ""


def variant_score(forced, named_hi, named_sdh, impaired, pref):
    """Higher scores are preferred. None means the track is not allowed."""
    if forced and not pref["allow_forced"]:
        return None
    score = _hearing_score(named_hi, named_sdh, impaired, pref)
    if score is None:
        return None
    if forced and pref["allow_forced"]:
        score += 4
    return score


def _hearing_score(named_hi, named_sdh, impaired, pref):
    if named_sdh and not pref["allow_sdh"]:
        return None
    if named_hi and not pref["allow_hi"]:
        return None
    flag_only = impaired and not named_hi and not named_sdh
    if flag_only and not (pref["allow_hi"] or pref["allow_sdh"]):
        return None
    score = 0
    if named_hi and pref["allow_hi"]:
        score += 4
    if named_sdh and pref["allow_sdh"]:
        score += 4
    if flag_only and (pref["allow_hi"] or pref["allow_sdh"]):
        score += 4
    return score


_EXTERNAL_EXTENSIONS = {
    "ass",
    "idx",
    "pgs",
    "srt",
    "ssa",
    "sub",
    "sup",
    "vtt",
}


def is_external_subtitle(stream):
    """Sidecar tracks are named after the file. Embedded tracks use the container name."""
    name = (stream.get("name") or "").strip().lower()
    if "." not in name:
        return False
    return name.rsplit(".", 1)[-1] in _EXTERNAL_EXTENSIONS


def _consider(stream, pref, forced_only, allow_extras):
    kind = extra_kind(stream)
    if not allow_extras and kind in ("commentary", "songs"):
        return None
    if not allow_extras and kind == "signs" and not forced_only:
        return None
    forced, named_hi, named_sdh, impaired = classify(stream)
    if forced_only and not forced and kind != "signs":
        return None
    if forced_only:
        score = _hearing_score(named_hi, named_sdh, impaired, pref)
        if score is None:
            return None
        if forced:
            score += 1
    else:
        score = variant_score(forced, named_hi, named_sdh, impaired, pref)
        if score is None:
            return None
    if stream.get("index") is None:
        return None
    extra_rank = {"commentary": 3, "songs": 2, "signs": 1}.get(kind, 0)
    if forced_only and kind == "signs":
        extra_rank = 0
    external_rank = 1 if is_external_subtitle(stream) else 0
    default_rank = 0 if _flag(stream.get("isdefault")) else 1
    return (extra_rank, external_rank, -score, default_rank, int(stream["index"]), stream)


def _rank_priorities(streams, priorities, forced_only, allow_extras):
    for pref in priorities:
        spec = pref.get("spec") or LANGUAGES.get(pref["code"])
        if spec is None:
            continue
        slot_forced = bool(forced_only or pref.get("force_only"))
        ranked = []
        for stream in streams:
            if not isinstance(stream, dict) or not language_matches(stream, spec):
                continue
            ranked_item = _consider(stream, pref, slot_forced, allow_extras)
            if ranked_item is not None:
                ranked.append(ranked_item)
        if ranked:
            ranked.sort()
            return pref, ranked[0][-1]
    return None, None


def choose_subtitle(streams, priorities, forced_only=False):
    """Pick the best stream for the first priority that has one.

    Dialogue tracks win over commentary, songs, and signs. An embedded track
    wins over a sidecar of the same language. Those extras are used only when
    no priority has a dialogue track. Forced-only mode keeps signs in the
    first pass and ignores full subtitles.
    """
    found = _rank_priorities(streams, priorities, forced_only, False)
    if found[0] is not None:
        return found
    return _rank_priorities(streams, priorities, forced_only, True)


def matching_understood(audio, priorities):
    """Return the understood priority that matches the current audio, if any."""
    if not isinstance(audio, dict):
        return None
    for pref in priorities:
        if not pref.get("understand"):
            continue
        spec = pref.get("spec") or LANGUAGES.get(pref["code"])
        if spec is not None and language_matches(audio, spec):
            return pref
    return None


def selection_message(pref, stream):
    forced, named_hi, named_sdh, impaired = classify(stream)
    notes = []
    kind = extra_kind(stream)
    if forced:
        notes.append("forced")
    elif kind == "signs":
        notes.append("signs")
    if kind == "commentary":
        notes.append("commentary")
    elif kind == "songs":
        notes.append("songs")
    if named_sdh:
        notes.append("SDH")
    elif named_hi or impaired:
        notes.append("HI")
    if notes:
        return "{0} ({1})".format(pref["label"], ", ".join(notes))
    return pref["label"]


def describe_stream(stream):
    language = (stream.get("language") or "").strip() or "?"
    name = (stream.get("name") or "").strip()
    forced, named_hi, named_sdh, impaired = classify(stream)
    flags = []
    if _flag(stream.get("isdefault")):
        flags.append("default")
    if forced:
        flags.append("forced")
    if named_sdh:
        flags.append("SDH")
    elif named_hi:
        flags.append("HI")
    elif impaired:
        flags.append("hearing impaired")
    if not (forced or named_hi or named_sdh or impaired):
        flags.append("normal")
    title = name or language
    return "{0} [{1}, {2}]".format(title, language, ", ".join(flags))


def _addon():
    return ADDON


def _string_setting(setting_id, default=""):
    addon = _addon()
    try:
        value = addon.getSettingString(setting_id)
    except Exception:
        value = addon.getSetting(setting_id)
    if value is None:
        return default
    value = str(value).strip()
    return value or default


def _bool_setting(setting_id, default=False):
    addon = _addon()
    try:
        raw = addon.getSetting(setting_id)
    except Exception:
        raw = None
    if raw is not None:
        text = str(raw).strip().lower()
        if text:
            return text in {"1", "true", "yes"}
        return default
    try:
        return bool(addon.getSettingBool(setting_id))
    except Exception:
        return default


def _int_setting(setting_id, default, low, high):
    addon = _addon()
    try:
        value = int(addon.getSettingInt(setting_id))
    except Exception:
        try:
            value = int(addon.getSetting(setting_id))
        except Exception:
            return default
    if value < low or value > high:
        return default
    return value


def load_priorities():
    priorities = []
    for slot in range(1, 6):
        code = _string_setting("lang_{0}".format(slot), "off").lower()
        if code == "off" or (code not in LANGUAGES and code not in ("kodi", "custom", "original", "default")):
            continue
        custom = _string_setting("lang_{0}_custom".format(slot), "")
        if code == "kodi":
            label = "Kodi subtitle language"
        elif code == "original":
            label = "Original language"
        elif code == "default":
            label = "Default language"
        elif code == "custom":
            label = custom or "Custom"
        else:
            label = LANGUAGES[code]["label"]
        priorities.append({
            "slot": slot,
            "code": code,
            "label": label,
            "custom": custom,
            "allow_hi": _bool_setting("lang_{0}_hi".format(slot)),
            "allow_sdh": _bool_setting("lang_{0}_sdh".format(slot)),
            "allow_forced": _bool_setting("lang_{0}_forced".format(slot)),
            "understand": _bool_setting("lang_{0}_understand".format(slot)),
            "force_only": False,
        })
    return priorities


def json_call(method, params=None):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    raw = xbmc.executeJSONRPC(json.dumps(payload))
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("error"):
        return None
    return data.get("result")


def get_video_player_id():
    result = json_call("Player.GetActivePlayers")
    if not isinstance(result, list):
        return None
    for player in result:
        if isinstance(player, dict) and player.get("type") == "video":
            return player.get("playerid")
    return None


def get_item_info(playerid):
    properties = [
        "title",
        "showtitle",
        "file",
        "season",
        "episode",
        "year",
        "premiered",
        "uniqueid",
        "imdbnumber",
        "tvshowid",
        "id",
        "type",
    ]
    result = json_call("Player.GetItem", {"playerid": playerid, "properties": properties})
    if not isinstance(result, dict):
        result = json_call("Player.GetItem", {
            "playerid": playerid,
            "properties": ["title", "showtitle", "file", "season", "episode"],
        })
    if not isinstance(result, dict):
        return {}
    item = result.get("item")
    return item if isinstance(item, dict) else {}


def get_playback_state(playerid):
    """Return (subtitle streams, current audio, all audio streams).

    Streams is None when the player could not be read. An empty list means
    the player answered and has no subtitles yet.
    """
    result = json_call("Player.GetProperties", {
        "playerid": playerid,
        "properties": ["subtitles", "currentaudiostream", "audiostreams"],
    })
    if not isinstance(result, dict):
        return None, None, None
    streams = result.get("subtitles")
    if not isinstance(streams, list):
        streams = []
    audio = result.get("currentaudiostream")
    if not isinstance(audio, dict):
        audio = {}
    audiostreams = result.get("audiostreams")
    if not isinstance(audiostreams, list):
        audiostreams = []
    return streams, audio, audiostreams


def get_can_seek(playerid):
    result = json_call("Player.GetProperties", {
        "playerid": playerid,
        "properties": ["canseek"],
    })
    if not isinstance(result, dict):
        return False
    return bool(result.get("canseek"))


def disable_subtitles(player, playerid):
    result = json_call("Player.SetSubtitle", {
        "playerid": playerid,
        "subtitle": "off",
    })
    try:
        player.showSubtitles(False)
    except Exception:
        if result is None:
            return False
    return True


def notify(message):
    if not _bool_setting("notify", True):
        return
    icon = xbmcgui.NOTIFICATION_INFO
    try:
        path = _addon().getAddonInfo("icon")
        if path:
            icon = path
    except Exception:
        pass
    xbmcgui.Dialog().notification(ADDON_NAME, message, icon, 4000, False)


def set_subtitle(player, playerid, index):
    result = json_call("Player.SetSubtitle", {
        "playerid": playerid,
        "subtitle": int(index),
        "enable": True,
    })
    if result is None:
        return False
    try:
        player.showSubtitles(True)
    except Exception:
        xbmc.log(
            "{0}: Subtitle stream was set, but subtitles could not be shown\n{1}".format(
                ADDON_NAME, traceback.format_exc()
            ),
            xbmc.LOGERROR,
        )
    return True


def _signature(streams, audio):
    items = []
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        items.append((
            stream.get("index"),
            stream.get("language") or "",
            stream.get("name") or "",
            _flag(stream.get("isforced")),
            _flag(stream.get("isimpaired")),
        ))
    if not isinstance(audio, dict):
        audio = {}
    return (
        tuple(items),
        audio.get("language") or "",
        audio.get("name") or "",
        audio.get("index"),
    )


class SubtitleEnforcer(xbmc.Player):
    """Selects subtitles when video playback starts, then optionally seeks back."""

    def __init__(self):
        xbmc.Player.__init__(self)
        self._session_mark = 0.0
        self._seek_at = 0.0
        self._stopped = False
        self._enabled = None
        self._reset()
        xbmc.log("{0}: Service initialized".format(ADDON_NAME), xbmc.LOGINFO)

    def on_settings_changed(self):
        self._enabled = None
        self._priorities = None
        self._exception_checked = False
        clear_tmdb_cache()

    def _reset(self):
        self._pending = False
        self._active = False
        self._path = ""
        self._started = 0.0
        self._playerid = None
        self._subtitle_done = False
        self._sync_done = False
        self._refresh_done = False
        self._selected_late = False
        self._sync_wanted = None
        self._earliest_time = None
        self._time_seen_at = None
        self._last_sig = None
        self._sig_since = 0.0
        self._logged_streams = False
        self._not_playing_since = None
        self._subs_disabled = False
        self._ignore_audio_rule = False
        self._show_priorities = None
        self._priorities = None
        self._exception_checked = False
        clear_tmdb_cache()

    def onPlayBackStarted(self):
        try:
            self._request_session()
        except Exception:
            xbmc.log(
                "{0}: Error in onPlayBackStarted\n{1}".format(ADDON_NAME, traceback.format_exc()),
                xbmc.LOGERROR,
            )

    def onAVStarted(self):
        try:
            if not self._pending and not self._active:
                self._request_session()
        except Exception:
            xbmc.log(
                "{0}: Error in onAVStarted\n{1}".format(ADDON_NAME, traceback.format_exc()),
                xbmc.LOGERROR,
            )

    def onPlayBackStopped(self):
        self._stopped = True
        self._reset_if_idle()

    def onPlayBackEnded(self):
        self._stopped = True
        self._reset_if_idle()

    def onPlayBackError(self):
        self._stopped = True
        self._reset_if_idle()

    def _request_session(self):
        now = time.monotonic()
        try:
            path = self.getPlayingFile()
        except Exception:
            path = ""
        # seekTime() can emit another playback-start event. Ignore that echo
        # so a seek back into the first seconds cannot seek again forever.
        if self._seek_at and (now - self._seek_at) < 3.0 and (not path or path == self._path):
            self._stopped = False
            return
        # Same file still playing: Kodi repeated the start event, or the user
        # seeked. A real new playback sets _stopped, or has a different path.
        if self._stopped:
            self._stopped = False
        elif path and path == self._path and (self._pending or self._active):
            return
        elif not path and self._pending and (now - self._session_mark) < 1.0:
            return
        self._reset()
        self._pending = True
        self._path = path or ""
        self._session_mark = now

    def _reset_if_idle(self):
        try:
            if self.isPlaying():
                return
        except Exception:
            pass
        self._reset()

    def tick(self):
        if self._enabled is None:
            self._enabled = _bool_setting("enabled", True)
        if not self._enabled:
            self._pending = False
            self._active = False
            return

        self._promote()
        if not self._active:
            return

        try:
            playing_video = self.isPlayingVideo()
        except Exception:
            playing_video = False
        if not playing_video:
            if self._not_playing_since is None:
                self._not_playing_since = time.monotonic()
            elif time.monotonic() - self._not_playing_since > 0.7:
                self._reset()
            return

        self._not_playing_since = None
        current = self._observe_time()
        self._enforce()
        if current is not None:
            self._maybe_sync(current)
            self._maybe_refresh(current)

    def _promote(self):
        if not self._pending or self._active:
            return
        try:
            video = self.isPlayingVideo()
            playing = self.isPlaying()
        except Exception:
            return
        if video:
            self._activate()
            return
        age = time.monotonic() - self._session_mark
        if playing and age > 2.0:
            self._pending = False
            xbmc.log("{0}: Audio playback, nothing to do".format(ADDON_NAME), xbmc.LOGDEBUG)
        elif age > 8.0:
            self._pending = False

    def _activate(self):
        try:
            path = self.getPlayingFile()
        except Exception:
            path = ""
        if path:
            self._path = path
        self._pending = False
        self._active = True
        self._started = time.monotonic()
        self._playerid = None
        self._subtitle_done = False
        self._sync_done = False
        self._refresh_done = False
        self._selected_late = False
        self._sync_wanted = None
        self._earliest_time = None
        self._time_seen_at = None
        self._last_sig = None
        self._sig_since = 0.0
        self._logged_streams = False
        self._not_playing_since = None
        self._subs_disabled = False
        self._ignore_audio_rule = False
        self._show_priorities = None
        self._priorities = None
        self._exception_checked = False
        clear_tmdb_cache()
        name = self._path.replace("\\", "/").rsplit("/", 1)[-1] or "video"
        xbmc.log("{0}: Video playback started ({1})".format(ADDON_NAME, name), xbmc.LOGINFO)

    def _player_id(self):
        if self._playerid is not None:
            return self._playerid
        playerid = get_video_player_id()
        if playerid is not None:
            self._playerid = playerid
        return playerid

    def _observe_time(self):
        try:
            current = self.getTime()
        except Exception:
            return None
        now = time.monotonic()
        if self._earliest_time is None:
            self._earliest_time = current
            self._time_seen_at = now
        elif (
            not self._sync_done
            and current > self._earliest_time + RESUME_JUMP
        ):
            # Started at 0, then Kodi jumped to a resume point.
            self._sync_wanted = False
            self._earliest_time = current

        if self._sync_wanted is None:
            if current >= START_WINDOW:
                self._sync_wanted = False
            elif (
                self._time_seen_at is not None
                and now - self._time_seen_at >= 1.0
                and current < START_WINDOW
            ):
                self._sync_wanted = _bool_setting("sync_enabled", True)
        return current

    def _playback_names(self, playerid):
        item = get_item_info(playerid)
        path = item.get("file") or self._path or ""
        if not path:
            try:
                path = self.getPlayingFile()
            except Exception:
                path = self._path or ""
        showtitle = item.get("showtitle") or ""
        if not showtitle:
            try:
                showtitle = xbmc.getInfoLabel("VideoPlayer.TvShowTitle") or ""
            except Exception:
                showtitle = ""
        return path, showtitle

    def _apply_playback_exception(self, playerid, path, showtitle):
        if _bool_setting("skip_trailers", True) and is_trailer_path(path):
            self._skip("Skipped trailer")
            return True
        if _bool_setting("skip_extras", True) and is_extra_path(path):
            self._skip("Skipped extra")
            return True
        rules = load_saved_shows()
        action = match_show_info(playback_rule_info(playerid, path, showtitle), rules)
        if not action:
            return False
        override = show_override_priorities(action)
        if override == "skip":
            self._skip("Skipped show {0}".format(showtitle or path_stem(path) or "item"))
            return True
        if override == "off":
            self._turn_off(
                playerid,
                "Subtitles off for {0}".format(showtitle or path_stem(path) or "this show"),
                "Subtitles off for this show",
            )
            return True
        self._show_priorities = override
        self._ignore_audio_rule = True
        return False

    def _skip(self, message):
        self._subtitle_done = True
        self._subs_disabled = True
        self._sync_wanted = False
        xbmc.log("{0}: {1}".format(ADDON_NAME, message), xbmc.LOGINFO)

    def _enforce(self):
        if self._subtitle_done:
            return
        elapsed = time.monotonic() - self._started
        if self._priorities is None:
            self._priorities = load_priorities()
        priorities = self._priorities

        playerid = self._player_id()
        if playerid is None:
            if elapsed > SUBTITLE_WAIT:
                self._give_up("No video player was available for subtitle selection")
            return

        if not self._exception_checked:
            self._exception_checked = True
            path, showtitle = self._playback_names(playerid)
            if self._apply_playback_exception(playerid, path, showtitle):
                return
        if getattr(self, "_show_priorities", None) is not None:
            priorities = self._show_priorities

        if not priorities:
            self._subtitle_done = True
            return

        streams, audio, audiostreams = get_playback_state(playerid)
        if streams is None:
            if elapsed > SUBTITLE_WAIT:
                self._give_up("Subtitle streams could not be read")
            return
        if streams and not self._logged_streams:
            self._logged_streams = True
            audio_language = audio.get("language") or audio.get("name") or "unknown"
            xbmc.log(
                "{0}: Audio {1}. Subtitle streams: {2}".format(
                    ADDON_NAME, audio_language, _format_streams(streams)
                ),
                xbmc.LOGINFO,
            )

        signature = _signature(streams, audio)
        if signature != self._last_sig:
            self._last_sig = signature
            self._sig_since = time.monotonic()
        stable = (time.monotonic() - self._sig_since) >= STABLE_SECONDS
        timed_out = elapsed > SUBTITLE_WAIT
        if not stable and not timed_out:
            return

        kodi_setting = None
        if any(pref.get("code") == "kodi" for pref in priorities):
            kodi_setting = read_kodi_subtitle_setting()
        priorities, waiting, explicit_none = resolve_priorities(
            priorities, audio, audiostreams, kodi_setting, timed_out
        )
        if waiting:
            return
        if not priorities:
            if explicit_none:
                self._turn_off(
                    playerid,
                    "Subtitles off because Kodi's subtitle language is none",
                    "Subtitles off",
                )
            else:
                self._subtitle_done = True
            return

        audio_mode = "usual" if self._ignore_audio_rule else _string_setting("audio_mode", "forced").lower()
        if audio_mode not in ("usual", "off", "forced"):
            audio_mode = "usual"
        wants_audio_rule = audio_mode in ("off", "forced") and any(
            pref.get("understand") for pref in priorities
        )
        audio_known = bool(
            _normalize_language(audio.get("language")) or (audio.get("name") or "").strip()
        )
        if wants_audio_rule and not audio_known and not timed_out:
            return
        understood = matching_understood(audio, priorities)
        if understood is not None and audio_mode == "off":
            self._turn_off(
                playerid,
                "Subtitles off because the audio is {0}".format(understood["label"]),
                "Subtitles off, audio is {0}".format(understood["label"]),
            )
            return

        forced_only = understood is not None and audio_mode == "forced"
        if not streams:
            if timed_out:
                self._miss(playerid, forced_only, "No subtitle streams were found")
            return

        pref, stream = choose_subtitle(streams, priorities, forced_only)
        if pref is None:
            self._miss(
                playerid,
                forced_only,
                "No subtitle matched the language priorities. Available: {0}".format(
                    _format_streams(streams)
                ),
            )
            return

        if not set_subtitle(self, playerid, stream["index"]):
            self._playerid = None
            if timed_out:
                self._give_up("Failed to enable {0}".format(describe_stream(stream)))
            return

        self._subtitle_done = True
        self._selected_late = bool(self._sync_done)
        xbmc.log(
            "{0}: Enabled priority {1} {2}: {3}".format(
                ADDON_NAME,
                pref["slot"],
                pref["label"],
                describe_stream(stream),
            ),
            xbmc.LOGINFO,
        )
        notify(selection_message(pref, stream))

    def _turn_off(self, playerid, log_message, toast):
        disable_subtitles(self, playerid)
        self._subs_disabled = True
        self._subtitle_done = True
        self._sync_wanted = False
        xbmc.log("{0}: {1}".format(ADDON_NAME, log_message), xbmc.LOGINFO)
        notify(toast)

    def _miss(self, playerid, forced_only, log_message):
        if forced_only or _bool_setting("disable_on_miss", True):
            toast = (
                "Subtitles off, no forced subtitle"
                if forced_only
                else "Subtitles off, no preferred language"
            )
            self._turn_off(playerid, log_message, toast)
            return
        self._give_up(log_message)

    def _give_up(self, message):
        self._subtitle_done = True
        xbmc.log("{0}: {1}".format(ADDON_NAME, message), xbmc.LOGINFO)

    def _maybe_sync(self, current):
        if self._subs_disabled:
            self._sync_done = True
            return
        if not self._sync_wanted or self._sync_done:
            return
        wait = _int_setting("sync_wait", 5, 1, 30)
        if current < wait:
            return
        if self._do_seek(current):
            self._sync_done = True

    def _maybe_refresh(self, current):
        # Subtitles that appear only after the first seek still need one
        # backward seek before Kodi draws them.
        if not self._selected_late or self._refresh_done or not self._sync_wanted:
            return
        if self._do_seek(current):
            self._refresh_done = True

    def _do_seek(self, current):
        try:
            total = self.getTotalTime()
        except Exception:
            return False
        if total <= 0:
            xbmc.log(
                "{0}: Skipping seek because the video duration is unknown".format(ADDON_NAME),
                xbmc.LOGINFO,
            )
            return True

        playerid = self._player_id()
        if playerid is None:
            return False
        if not get_can_seek(playerid):
            xbmc.log(
                "{0}: Skipping seek because this video cannot be seeked".format(ADDON_NAME),
                xbmc.LOGINFO,
            )
            return True

        seek_back = _int_setting("sync_seek", 1, 1, 15)
        target = current - seek_back
        if target < 0:
            target = 0.0
        try:
            self._seek_at = time.monotonic()
            self.seekTime(target)
        except Exception:
            self._seek_at = 0.0
            xbmc.log(
                "{0}: Seek failed\n{1}".format(ADDON_NAME, traceback.format_exc()),
                xbmc.LOGERROR,
            )
            return False
        xbmc.log(
            "{0}: Sought back to {1:.1f}s".format(ADDON_NAME, target),
            xbmc.LOGINFO,
        )
        return True


def _format_streams(streams):
    shown = [stream for stream in streams if isinstance(stream, dict)]
    text = "; ".join(describe_stream(stream) for stream in shown[:30])
    extra = len(shown) - 30
    if extra > 0:
        text += "; +{0} more".format(extra)
    return text or "none"


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


def playback_rule_info(playerid, path, showtitle):
    """Show or movie identity for the video that is playing."""
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


def _rules_dialog():
    return xbmcgui.Dialog()


def _rules_notice(message):
    try:
        _rules_dialog().notification(ADDON_NAME, message, xbmcgui.NOTIFICATION_INFO, 4000, False)
    except Exception:
        xbmc.log("{0}: {1}".format(ADDON_NAME, message), xbmc.LOGINFO)


def _dialog_select(dialog, heading, labels):
    try:
        return dialog.select(heading, labels)
    except Exception:
        return -1


def _linked_hit(hit):
    return bool(
        _id_text(hit.get("tmdb_id"))
        or _imdb_id(hit.get("imdb"))
        or _id_text(hit.get("library_id"))
    )


def _pick_show_action(dialog, heading):
    choices = show_language_choices()
    index = _dialog_select(dialog, heading, [label for _code, label in choices])
    if index < 0:
        return None
    action = choices[index][0]
    if action != "custom":
        return action
    typed = dialog.input("Language name or code", type=getattr(xbmcgui, "INPUT_ALPHANUM", 0))
    typed = (typed or "").strip().lower()
    if not typed:
        return None
    if typed not in ("off", "default", "original", "kodi", "leave") and spec_from_text(typed) is None:
        _rules_notice("Unknown language")
        return None
    return typed


def _store_show(hit, action):
    shows = upsert_show_rule(load_saved_shows(), {
        "title": hit.get("title") or "",
        "year": hit.get("year") or "",
        "tmdb_id": hit.get("tmdb_id") or "",
        "imdb": hit.get("imdb") or "",
        "library_id": hit.get("library_id") or "",
        "mediatype": hit.get("mediatype") or "",
        "action": action,
    })
    saved = [show for show in shows if show_rule_key(show) == show_rule_key({
        "title": hit.get("title") or "",
        "year": hit.get("year") or "",
        "tmdb_id": hit.get("tmdb_id") or "",
        "imdb": hit.get("imdb") or "",
        "library_id": hit.get("library_id") or "",
        "mediatype": hit.get("mediatype") or "",
        "action": action,
    })]
    label = saved_show_label(saved[0]) if saved else (hit.get("title") or "")
    if save_saved_shows(shows):
        _rules_notice("Saved {0}".format(label))
    else:
        _rules_notice("Could not save {0}".format(hit.get("title") or "title"))


def _search_hits(query):
    query = " ".join(str(query or "").split())
    if len(query) < 2:
        _rules_notice("That title is empty.")
        return None
    hits = [
        hit for hit in search_tv_shows(query, library_titles(query), tmdb_titles(query))
        if _linked_hit(hit)
    ]
    return hits


def _choose_hit(dialog, query):
    hits = _search_hits(query)
    if hits is None:
        return None
    if not hits:
        _rules_notice("No matching show or movie.")
        return None
    index = _dialog_select(dialog, "Select the show or movie", [show_hit_label(hit) for hit in hits])
    if index < 0:
        return None
    return hits[index]


def _add_hit(dialog, hit):
    title = " ".join(str(hit.get("title") or "").split())
    if not title:
        _rules_notice("That title is empty.")
        return
    action = _pick_show_action(dialog, show_hit_label(dict(hit, title=title)))
    if action is None:
        return
    chosen = dict(hit)
    chosen["title"] = title
    _store_show(chosen, action)


def playing_hit():
    playerid = get_video_player_id()
    playing = False
    try:
        playing = xbmc.Player().isPlayingVideo()
    except Exception:
        playing = False
    if playerid is None or not playing:
        return None
    info = playback_rule_info(playerid, "", "")
    if info.get("mediatype") == "tvshow":
        title = info.get("showtitle") or ""
    else:
        title = info.get("title") or info.get("showtitle") or ""
    return {
        "title": title,
        "year": info.get("year") or "",
        "mediatype": info.get("mediatype") or "",
        "tmdb_id": info.get("tmdb") or "",
        "imdb": info.get("imdb") or "",
        "library_id": info.get("library_id") or "",
    }


def add_playing(dialog):
    hit = playing_hit()
    if not hit or not hit.get("title"):
        _rules_notice("Play a video, or search for the title.")
        return
    if _linked_hit(hit):
        _add_hit(dialog, hit)
        return
    chosen = _choose_hit(dialog, hit.get("title") or "")
    if chosen is not None:
        _add_hit(dialog, chosen)


def prompt_add_show():
    dialog = _rules_dialog()
    query = dialog.input("Show or movie title", type=getattr(xbmcgui, "INPUT_ALPHANUM", 0))
    chosen = _choose_hit(dialog, query)
    if chosen is not None:
        _add_hit(dialog, chosen)


def _edit_show(dialog, show):
    choice = _dialog_select(dialog, show.get("title") or "Show rule", ["Remove", "Change language"])
    if choice < 0:
        return
    if choice == 0:
        if dialog.yesno(ADDON_NAME, "Remove the rule for {0}?".format(show.get("title") or "this title")):
            shows = load_saved_shows()
            kept = [item for item in shows if show_rule_key(item) != show_rule_key(show)]
            if save_saved_shows(kept):
                _rules_notice("Removed {0}".format(show.get("title") or "title"))
            else:
                _rules_notice("Could not remove {0}".format(show.get("title") or "title"))
        return
    action = _pick_show_action(dialog, show.get("title") or "Language")
    if action is None:
        return
    _store_show(show, action)


def prompt_manage_shows():
    """Add the playing title, search, and change or remove a saved rule."""
    dialog = _rules_dialog()
    while True:
        shows = load_saved_shows()
        items = ["Add the title that is playing", "Search for a show or movie"]
        offset = len(items)
        items.extend(saved_show_label(show) for show in shows)
        remove_all = None
        if shows:
            remove_all = len(items)
            items.append("Remove all")
        choice = _dialog_select(dialog, "Show rules", items)
        if choice < 0:
            return
        if choice == 0:
            add_playing(dialog)
        elif choice == 1:
            prompt_add_show()
        elif remove_all is not None and choice == remove_all:
            if dialog.yesno(ADDON_NAME, "Remove every show rule?"):
                if save_saved_shows([]):
                    _rules_notice("Removed")
                else:
                    _rules_notice("Could not remove the saved rules")
        else:
            _edit_show(dialog, shows[choice - offset])


def _child_show_id(method, id_name, details_name, item_id):
    details = _library_details(method, id_name, details_name, item_id, ["tvshowid"])
    return _id_text(details.get("tvshowid"))


def context_hit():
    """The library show or movie the context menu was opened on."""
    dbtype = _info_label("ListItem.DBType").lower()
    dbid = _info_label("ListItem.DBID")
    show_id = _id_text(_info_label("ListItem.TvShowDBID"))
    properties = ["title", "year", "premiered", "uniqueid", "imdbnumber"]
    if dbtype == "episode" and not show_id:
        show_id = _child_show_id("VideoLibrary.GetEpisodeDetails", "episodeid", "episodedetails", dbid)
    elif dbtype == "season" and not show_id:
        show_id = _child_show_id("VideoLibrary.GetSeasonDetails", "seasonid", "seasondetails", dbid)
    if dbtype in ("episode", "season", "tvshow"):
        tvshow_lookup_id = show_id or (dbid if dbtype == "tvshow" else "")
        details = _library_details(
            "VideoLibrary.GetTVShowDetails",
            "tvshowid",
            "tvshowdetails",
            tvshow_lookup_id,
            properties,
        )
        if details:
            hit = _library_hit(details, "tvshow", "tvshowid")
            if show_id and not hit.get("library_id"):
                hit["library_id"] = show_id
            if hit.get("title"):
                return hit
    if dbtype == "movie":
        details = _library_details(
            "VideoLibrary.GetMovieDetails",
            "movieid",
            "moviedetails",
            dbid,
            properties,
        )
        if details:
            hit = _library_hit(details, "movie", "movieid")
            if hit.get("title"):
                return hit
    show = _info_label("ListItem.TvShowTitle")
    title = _info_label("ListItem.Title") or _info_label("ListItem.Label")
    year = _info_label("ListItem.Year") or _info_label("ListItem.Premiered")
    if dbtype in ("episode", "season", "tvshow"):
        name = show or title
        kind = "tvshow"
        tmdb = ""
        imdb = ""
        library_id = show_id
    elif dbtype == "movie":
        name = title or show
        kind = "movie"
        tmdb = _info_label("ListItem.UniqueID(tmdb)")
        imdb = _info_label("ListItem.UniqueID(imdb)") or _info_label("ListItem.IMDBNumber")
        library_id = dbid
    else:
        name = show or title
        kind = "tvshow" if show else ""
        tmdb = ""
        imdb = ""
        library_id = ""
    return {
        "title": name,
        "year": year,
        "mediatype": kind,
        "tmdb_id": tmdb,
        "imdb": imdb,
        "library_id": library_id,
    }


def set_rule_for_context():
    """Save a subtitle language for the show or movie focused in the library."""
    dialog = _rules_dialog()
    hit = context_hit()
    if hit.get("title") and _linked_hit(hit):
        _add_hit(dialog, hit)
        return
    chosen = _choose_hit(dialog, hit.get("title") or "")
    if chosen is not None:
        _add_hit(dialog, chosen)


def run_rules_action(arg):
    try:
        if arg == "add_show":
            prompt_add_show()
        elif arg == "manage_shows":
            prompt_manage_shows()
        elif arg == "set_title":
            set_rule_for_context()
    except Exception:
        xbmc.log(
            "{0}: Show rules failed\n{1}".format(ADDON_NAME, traceback.format_exc()),
            xbmc.LOGERROR,
        )


def run_rules_menu():
    prompt_manage_shows()


def service_is_running():
    try:
        return xbmcgui.Window(10000).getProperty("SubtitleEnforcer.Running") == "true"
    except Exception:
        return False


def mark_service_running(running):
    try:
        window = xbmcgui.Window(10000)
        if running:
            window.setProperty("SubtitleEnforcer.Running", "true")
        else:
            window.clearProperty("SubtitleEnforcer.Running")
    except Exception:
        pass


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg in ("add_show", "manage_shows", "set_title"):
        run_rules_action(arg)
        return
    if service_is_running():
        run_rules_menu()
        return
    mark_service_running(True)
    try:
        run_service()
    finally:
        mark_service_running(False)


class _ServiceMonitor(xbmc.Monitor):
    def __init__(self, player):
        xbmc.Monitor.__init__(self)
        self._player = player

    def onSettingsChanged(self):
        self._player.on_settings_changed()


def run_service():
    version = ADDON.getAddonInfo("version")
    xbmc.log("{0} {1}: Service starting".format(ADDON_NAME, version), xbmc.LOGINFO)
    player = SubtitleEnforcer()
    monitor = _ServiceMonitor(player)
    try:
        while not monitor.abortRequested():
            try:
                player.tick()
            except Exception:
                xbmc.log(
                    "{0}: Service tick failed\n{1}".format(ADDON_NAME, traceback.format_exc()),
                    xbmc.LOGERROR,
                )
            if monitor.waitForAbort(0.1):
                break
    except KeyboardInterrupt:
        pass
    finally:
        xbmc.log("{0}: Service stopped".format(ADDON_NAME), xbmc.LOGINFO)


if __name__ == "__main__":
    main()
