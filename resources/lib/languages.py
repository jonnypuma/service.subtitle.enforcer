# -*- coding: utf-8 -*-
"""Language definitions, stream classification, and subtitle selection."""

import re

from resources.lib.kodi import _bool_setting, _flag, _string_setting

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

_TOKEN_RE = re.compile(r"[a-z0-9]+")

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


def _normalize_language(value):
    return (value or "").strip().lower().replace("_", "-")


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


def _tokenize_words(text):
    return frozenset(_TOKEN_RE.findall((text or "").lower()))


def _token(text, word, words=None):
    if word.isalnum():
        return word in (words if words is not None else _tokenize_words(text))
    return re.search(
        r"(?:^|[^a-z0-9])" + re.escape(word) + r"(?:[^a-z0-9]|$)",
        text,
    ) is not None


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


def _name_has_code(name, codes, words=None):
    if words is None:
        words = _tokenize_words(name)
    for code in codes:
        # Two-letter codes collide with tags such as HI and words such as "no".
        if len(code) < 3:
            continue
        if _token(name, code, words):
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


def _is_simplified(language, name, words=None):
    if language in {"zhs", "zh-cn", "zh-sg", "zh-hans", "chs", "sc"}:
        return True
    if "hans" in language:
        return True
    return "simplified" in name or _token(name, "hans", words)


def _is_traditional(language, name, words=None):
    if language in {"zht", "zh-tw", "zh-hk", "zh-mo", "zh-hant", "cht", "tc"}:
        return True
    if "hant" in language:
        return True
    return "traditional" in name or _token(name, "hant", words)


def _is_brazilian(language, name):
    if language in {"pob", "pt-br", "pb", "por-br"}:
        return True
    return "brazil" in name


def language_matches(stream, spec, words=None):
    language, name = _stream_text(stream)
    if words is None and name:
        words = _tokenize_words(name)
    kind = spec["match"]
    if kind == "simplified":
        return _is_simplified(language, name, words) or _name_has_code(name, spec["codes"], words)
    if kind == "traditional":
        return _is_traditional(language, name, words) or _name_has_code(name, spec["codes"], words)
    if kind == "brazilian":
        return _is_brazilian(language, name) or _name_has_code(name, spec["codes"], words)
    if _field_matches_codes(language, spec["codes"]) or language in spec["names"]:
        return True
    if _name_matches_stem(name, spec["names"]):
        return True
    return _name_has_code(name, spec["codes"], words)


def classify(stream, words=None):
    """Return forced, named HI, named SDH, and the hearing-impaired flag.

    Kodi exposes one hearing-impaired flag for both HI and SDH. The track
    name is used to tell them apart. A flag with neither name is accepted
    by either checkbox.
    """
    _language, name = _stream_text(stream)
    if words is None and name:
        words = _tokenize_words(name)
    forced = _flag(stream.get("isforced")) or _token(name, "forced", words)
    named_sdh = _token(name, "sdh", words) or "hard of hearing" in name or "hard-of-hearing" in name
    named_hi = (
        _token(name, "hi", words)
        or "hearing impaired" in name
        or "hearing-impaired" in name
        or "closed caption" in name
        or _token(name, "cc", words)
    )
    impaired = _flag(stream.get("isimpaired"))
    return forced, named_hi, named_sdh, impaired


def _short_label(name):
    # Filenames contain a dot and often include the movie title, so a word
    # like "song" or "signs" in the title is not a track type.
    return "." not in name and len(name) <= 48


def extra_kind(stream, words=None):
    """Commentary, songs, and signs tracks are a last resort.

    A signs track is still eligible immediately when forced subtitles are
    the goal, because those tracks are usually the forced signs.
    """
    _language, name = _stream_text(stream)
    if words is None and name:
        words = _tokenize_words(name)
    if _token(name, "commentary", words) or _token(name, "commentaries", words):
        return "commentary"
    signs_phrase = (
        "signs & songs" in name
        or "signs and songs" in name
        or "signs/songs" in name
    )
    if signs_phrase or (_token(name, "signs", words) and _short_label(name)):
        return "signs"
    if (
        _token(name, "lyrics", words)
        or _token(name, "karaoke", words)
        or "sing-along" in name
        or "sing along" in name
        or (_token(name, "songs", words) and (_short_label(name) or "(" in name or "[" in name))
        or (_token(name, "song", words) and _short_label(name))
    ):
        return "songs"
    return ""


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


def is_external_subtitle(stream):
    """Sidecar tracks are named after the file. Embedded tracks use the container name."""
    name = (stream.get("name") or "").strip().lower()
    if "." not in name:
        return False
    return name.rsplit(".", 1)[-1] in _EXTERNAL_EXTENSIONS


def _consider(stream, pref, forced_only, allow_extras, words=None):
    kind = extra_kind(stream, words)
    if not allow_extras and kind in ("commentary", "songs"):
        return None
    if not allow_extras and kind == "signs" and not forced_only:
        return None
    forced, named_hi, named_sdh, impaired = classify(stream, words)
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


def _rank_priorities(streams, priorities, forced_only, allow_extras, tokenized):
    for pref in priorities:
        spec = pref.get("spec") or LANGUAGES.get(pref["code"])
        if spec is None:
            continue
        slot_forced = bool(forced_only or pref.get("force_only"))
        ranked = []
        for stream, words in tokenized:
            if not language_matches(stream, spec, words):
                continue
            ranked_item = _consider(stream, pref, slot_forced, allow_extras, words)
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
    tokenized = [
        (stream, _tokenize_words(stream.get("name")))
        for stream in streams
        if isinstance(stream, dict)
    ]
    found = _rank_priorities(streams, priorities, forced_only, False, tokenized)
    if found[0] is not None:
        return found
    return _rank_priorities(streams, priorities, forced_only, True, tokenized)


def matching_understood(audio, priorities):
    """Return the understood priority that matches the current audio, if any."""
    if not isinstance(audio, dict):
        return None
    words = _tokenize_words(audio.get("name"))
    for pref in priorities:
        if not pref.get("understand"):
            continue
        spec = pref.get("spec") or LANGUAGES.get(pref["code"])
        if spec is not None and language_matches(audio, spec, words):
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
