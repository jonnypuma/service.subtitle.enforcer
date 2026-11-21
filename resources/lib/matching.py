# -*- coding: utf-8 -*-
"""Priority resolution for original, default, and Kodi subtitle languages."""

import xbmc

from resources.lib.kodi import ADDON_NAME, _flag, _info_label, gui_language_code
from resources.lib.languages import LANGUAGES, _specs_agree, spec_from_text
from resources.lib.tmdb import (
    tmdb_api_language,
    tmdb_api_pending,
    tmdbhelper_language,
    tmdbhelper_lookup_pending,
)


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
