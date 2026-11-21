# -*- coding: utf-8 -*-
"""Subtitle Enforcer service entry point and public API re-exports."""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from resources.lib.kodi import (
    ADDON,
    ADDON_ID,
    ADDON_NAME,
    _addon,
    _bool_setting,
    _int_setting,
    _string_setting,
    addon_profile_dir,
    disable_subtitles,
    get_can_seek,
    get_item_info,
    get_playback_state,
    get_video_player_id,
    gui_language_code,
    json_call,
    notify,
    read_kodi_subtitle_setting,
    rules_file,
    set_subtitle,
)
from resources.lib.languages import (
    LANGUAGE_CHOICES,
    LANGUAGES,
    choose_subtitle,
    classify,
    describe_stream,
    extra_kind,
    is_external_subtitle,
    language_matches,
    language_options,
    load_priorities,
    matching_understood,
    selection_message,
    spec_from_text,
    variant_score,
)
from resources.lib.matching import (
    default_language_text,
    original_language_pending,
    original_language_text,
    prefer_original_text,
    resolve_kodi_spec,
    resolve_priorities,
)
from resources.lib.rules import (
    candidate_titles,
    delete_show_rule,
    is_extra_path,
    is_trailer_path,
    legacy_shows_from_setting,
    library_titles,
    load_saved_shows,
    match_saved_show,
    match_show_info,
    match_show_rule,
    merge_show_hits,
    parse_show_rules,
    path_segments,
    path_stem,
    path_words,
    playback_rule_info,
    save_saved_shows,
    saved_show_label,
    search_tv_shows,
    show_hit_label,
    show_language_choices,
    show_override_priorities,
    show_query_matches,
    show_rule_key,
    title_match,
    upsert_show_rule,
)
from resources.lib.service import (
    RESUME_JUMP,
    STABLE_SECONDS,
    START_WINDOW,
    STREAM_POLL_INTERVAL,
    SUBTITLE_WAIT,
    SubtitleEnforcer,
    run_service,
)
from resources.lib.tmdb import (
    api_key_from_text,
    choose_tmdb_api_key,
    clear_tmdb_cache,
    lookup_tmdb_original_language,
    read_tmdbhelper_api_key,
    resolve_tmdb_api_key,
    tmdb_api_language,
    tmdb_api_pending,
    tmdb_item_identity,
    tmdb_item_query,
    tmdb_language_from_payload,
    tmdb_titles,
    tmdbhelper_installed,
    tmdbhelper_language,
    tmdbhelper_lookup_pending,
    tmdbhelper_matches_current_item,
    tmdbhelper_service_started,
)
from resources.lib.ui import (
    add_playing,
    context_hit,
    playing_hit,
    prompt_add_show,
    prompt_manage_shows,
    run_rules_action,
    run_rules_menu,
    set_rule_for_context,
)


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg in ("add_show", "manage_shows", "set_title"):
        run_rules_action(arg)
        return
    run_service()


if __name__ == "__main__":
    main()
