# -*- coding: utf-8 -*-
"""Background playback service for Subtitle Enforcer."""

import time
import traceback

import xbmc

from resources.lib.kodi import (
    ADDON,
    ADDON_NAME,
    _bool_setting,
    _flag,
    _int_setting,
    _string_setting,
    disable_subtitles,
    get_can_seek,
    get_item_info,
    get_playback_state,
    get_video_player_id,
    notify,
    read_kodi_subtitle_setting,
    set_subtitle,
)
from resources.lib.languages import (
    _normalize_language,
    choose_subtitle,
    describe_stream,
    load_priorities,
    matching_understood,
    selection_message,
)
from resources.lib.matching import resolve_priorities
from resources.lib.rules import (
    is_extra_path,
    is_trailer_path,
    load_saved_shows,
    match_show_info,
    path_stem,
    playback_rule_info,
    show_override_priorities,
)
from resources.lib.tmdb import clear_tmdb_cache, clear_tmdb_session_failures

# How long to wait for subtitle streams to show up and settle.
SUBTITLE_WAIT = 15.0
STABLE_SECONDS = 1.5
# Playback at or past this time is treated as a resume, not a fresh start.
START_WINDOW = 2.0
# A forward jump larger than this, before the seek runs, is a resume.
RESUME_JUMP = 10.0
# How often to poll Player.GetProperties while waiting for streams to settle.
STREAM_POLL_INTERVAL = 0.25


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


def _format_streams(streams):
    shown = [stream for stream in streams if isinstance(stream, dict)]
    text = "; ".join(describe_stream(stream) for stream in shown[:30])
    extra = len(shown) - 30
    if extra > 0:
        text += "; +{0} more".format(extra)
    return text or "none"


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
        self._last_stream_poll = 0.0
        self._logged_streams = False
        self._not_playing_since = None
        self._subs_disabled = False
        self._ignore_audio_rule = False
        self._show_priorities = None
        self._priorities = None
        self._exception_checked = False
        clear_tmdb_session_failures()

    def _work_complete(self):
        if not self._active:
            return not self._pending
        if not self._subtitle_done:
            return False
        if self._sync_wanted is not False and not self._sync_done:
            return False
        if self._selected_late and not self._refresh_done:
            return False
        return True

    def recommended_wait(self):
        """Short poll interval while actively settling/seeking; longer when idle or done."""
        if self._enabled is False or self._work_complete():
            return 1.0
        return 0.1

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
        if not self._active or self._work_complete():
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
        self._last_stream_poll = 0.0
        self._logged_streams = False
        self._not_playing_since = None
        self._subs_disabled = False
        self._ignore_audio_rule = False
        self._show_priorities = None
        self._priorities = None
        self._exception_checked = False
        clear_tmdb_session_failures()
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
        return path, showtitle, item

    def _apply_playback_exception(self, playerid, path, showtitle, item=None):
        if _bool_setting("skip_trailers", True) and is_trailer_path(path):
            self._skip("Skipped trailer")
            return True
        if _bool_setting("skip_extras", True) and is_extra_path(path):
            self._skip("Skipped extra")
            return True
        rules = load_saved_shows()
        if not rules:
            return False
        action = match_show_info(playback_rule_info(playerid, path, showtitle, item=item), rules)
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
        now = time.monotonic()
        elapsed = now - self._started
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
            path, showtitle, item = self._playback_names(playerid)
            if self._apply_playback_exception(playerid, path, showtitle, item=item):
                return
        if getattr(self, "_show_priorities", None) is not None:
            priorities = self._show_priorities

        if not priorities:
            self._subtitle_done = True
            return

        timed_out = elapsed > SUBTITLE_WAIT
        if (
            self._last_stream_poll > 0.0
            and not timed_out
            and (now - self._last_stream_poll) < STREAM_POLL_INTERVAL
        ):
            return
        self._last_stream_poll = now

        streams, audio, audiostreams = get_playback_state(playerid)
        if streams is None:
            if timed_out:
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
            self._sig_since = now
        stable = (now - self._sig_since) >= STABLE_SECONDS
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
            if monitor.waitForAbort(player.recommended_wait()):
                break
    except KeyboardInterrupt:
        pass
    finally:
        xbmc.log("{0}: Service stopped".format(ADDON_NAME), xbmc.LOGINFO)
