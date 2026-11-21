# -*- coding: utf-8 -*-
"""Interactive dialogs and context menu handlers for per-title subtitle rules."""

import traceback

import xbmc
import xbmcgui

from resources.lib.kodi import ADDON_NAME, _id_text, _imdb_id, _info_label, get_video_player_id
from resources.lib.languages import spec_from_text
from resources.lib.rules import (
    _library_details,
    _library_hit,
    library_titles,
    load_saved_shows,
    playback_rule_info,
    save_saved_shows,
    saved_show_label,
    search_tv_shows,
    show_hit_label,
    show_language_choices,
    show_rule_key,
    upsert_show_rule,
)
from resources.lib.tmdb import tmdb_titles


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
