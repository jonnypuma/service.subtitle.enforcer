# -*- coding: utf-8 -*-
"""Kodi addon, settings, JSON-RPC, and profile path helpers."""

import json
import os
import traceback

import xbmc
import xbmcaddon
import xbmcgui

ADDON_ID = "service.subtitle.enforcer"
try:
    ADDON = xbmcaddon.Addon(ADDON_ID)
except TypeError:
    ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo("name") or "Subtitle Enforcer"


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


def _info_label(name):
    try:
        return (xbmc.getInfoLabel(name) or "").strip()
    except Exception:
        return ""


def _flag(value):
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


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


def _clean_year(year):
    year = str(year or "").strip()
    if len(year) >= 4 and year[:4].isdigit():
        year = year[:4]
    if year.isdigit() and year != "0":
        return year
    return ""


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


def read_kodi_subtitle_setting():
    """Return Kodi's subtitle language, '' when it is unset, or None if unread."""
    result = json_call("Settings.GetSettingValue", {"setting": "locale.subtitlelanguage"})
    if isinstance(result, dict) and "value" in result:
        return str(result.get("value") or "").strip().lower()
    if isinstance(result, str):
        return result.strip().lower()
    return None


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
