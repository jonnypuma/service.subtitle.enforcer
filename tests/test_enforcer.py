# -*- coding: utf-8 -*-
"""Unit tests for subtitle selection, TMDB checks, and TV show rules."""
import json
import os
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SETTINGS = {}
xbmc = types.ModuleType("xbmc")
xbmc.LOGDEBUG = xbmc.LOGINFO = xbmc.LOGERROR = 0
xbmc.ISO_639_2 = 1
xbmc.log = lambda *args, **kwargs: None
xbmc.getLanguage = lambda fmt: "eng"
xbmc.getInfoLabel = lambda name: ""
xbmc.getCondVisibility = lambda expr: False
xbmc.Player = object
xbmc.Monitor = object
xbmc.executeJSONRPC = lambda payload: ""
gui = types.ModuleType("xbmcgui")
gui.INPUT_ALPHANUM = 0
gui.NOTIFICATION_INFO = "info"
addon_mod = types.ModuleType("xbmcaddon")


class Addon(object):
    def __init__(self, addon_id=None):
        self.addon_id = addon_id

    def getAddonInfo(self, key):
        return ""

    def getSetting(self, key):
        return SETTINGS.get(key, "")

    def getSettingString(self, key):
        return SETTINGS.get(key, "")

    def getSettingBool(self, key):
        return False

    def getSettingInt(self, key):
        return 0


addon_mod.Addon = Addon
sys.modules["xbmc"] = xbmc
sys.modules["xbmcgui"] = gui
sys.modules["xbmcaddon"] = addon_mod

import default


def audio(language, default=False, original=False):
    return {"language": language, "name": "", "isdefault": default, "isoriginal": original}


def subtitle(index, language, name=""):
    return {
        "index": index,
        "language": language,
        "name": name,
        "isforced": False,
        "isimpaired": False,
        "isdefault": False,
    }


def pref(code, spec=None):
    return {
        "slot": 1,
        "code": code,
        "label": code,
        "spec": spec,
        "custom": "",
        "allow_hi": False,
        "allow_sdh": False,
        "allow_forced": False,
        "understand": False,
        "force_only": False,
    }


def chosen(streams, priorities):
    found, item = default.choose_subtitle(streams, priorities, False)
    if found is None:
        return None
    return item["index"]


class LanguageTests(unittest.TestCase):
    def test_file_default_ignores_the_original_and_a_later_track(self):
        streams = [audio("jpn", original=True), audio("eng", default=True)]
        self.assertEqual(default.default_language_text(streams), "eng")
        resolved, waiting, _explicit = default.resolve_priorities(
            [pref("default")], {}, streams, None, False
        )
        self.assertFalse(waiting)
        self.assertEqual(resolved[0]["label"], "English")

    def test_original_ignores_the_file_default(self):
        streams = [audio("eng", default=True), audio("jpn", original=True)]
        resolved, waiting, _explicit = default.resolve_priorities(
            [pref("original")], {}, streams, None, False
        )
        self.assertFalse(waiting)
        self.assertEqual(resolved[0]["label"], "Japanese")

    def test_kodi_default_is_the_interface_language(self):
        streams = [audio("jpn", default=True)]
        resolved, waiting, _explicit = default.resolve_priorities(
            [pref("kodi")], {}, streams, "default", False
        )
        self.assertFalse(waiting)
        self.assertEqual(resolved[0]["label"], "English")

    def test_first_audio_is_the_file_default_when_none_is_flagged(self):
        self.assertEqual(
            default.default_language_text([audio("ger"), audio("eng")]),
            "ger",
        )

    def test_default_waits_until_audio_exists(self):
        resolved, waiting, _explicit = default.resolve_priorities(
            [pref("default")], {}, [], None, False
        )
        self.assertTrue(waiting)
        self.assertEqual(resolved, [])

    def test_tmdb_wins_when_it_disagrees_with_the_file(self):
        self.assertEqual(default.prefer_original_text("eng", "ja"), "ja")

    def test_japanese_codes_are_the_same_language(self):
        self.assertEqual(default.prefer_original_text("jpn", "ja"), "ja")

    def test_regional_chinese_is_kept_when_tmdb_says_chinese(self):
        self.assertEqual(default.prefer_original_text("zh-cn", "zh"), "zh-cn")

    def test_empty_api_key_uses_the_helper_key(self):
        self.assertEqual(default.choose_tmdb_api_key("", "helper-key"), "helper-key")
        self.assertEqual(default.choose_tmdb_api_key("own-key", "helper-key"), "own-key")

    def test_embedded_track_beats_a_default_sidecar(self):
        eng = pref("eng", default.LANGUAGES["eng"])
        sidecar = subtitle(0, "eng", "Movie.eng.srt")
        sidecar["isdefault"] = True
        embedded = subtitle(3, "eng", "English")
        self.assertFalse(default.is_external_subtitle(embedded))
        self.assertTrue(default.is_external_subtitle(subtitle(1, "eng", "Movie.ENG.SRT")))
        self.assertEqual(chosen([sidecar, embedded], [eng]), 3)
        self.assertEqual(chosen([sidecar], [eng]), 0)
        hearing = pref("eng", default.LANGUAGES["eng"])
        hearing["allow_hi"] = True
        external_hi = subtitle(0, "eng", "Movie.eng.hi.srt")
        embedded_hi = subtitle(2, "eng", "English HI")
        self.assertEqual(chosen([external_hi, embedded, embedded_hi], [hearing]), 2)
        commentary = subtitle(4, "eng", "Commentary")
        self.assertEqual(chosen([commentary, sidecar], [eng]), 0)

    def test_dialogue_beats_commentary_and_song_titles_are_not_songs(self):
        eng = pref("eng", default.LANGUAGES["eng"])
        streams = [
            subtitle(0, "eng", "Commentary"),
            subtitle(1, "eng", "English"),
        ]
        self.assertEqual(chosen(streams, [eng]), 1)
        self.assertEqual(default.extra_kind(subtitle(2, "eng", "Song of the Sea.eng.srt")), "")

    def test_show_override_default_is_its_own_choice(self):
        self.assertEqual(default.show_override_priorities("default")[0]["code"], "default")

    def test_custom_language_and_hearing_tags_are_not_languages(self):
        spec = default.spec_from_text("cym")
        self.assertIsNotNone(spec)
        self.assertEqual(default.show_override_priorities("cym")[0]["code"], "custom")
        self.assertFalse(default.language_matches(subtitle(0, "", "HI"), default.LANGUAGES["hin"]))
        self.assertFalse(default.language_matches(subtitle(0, "", "no"), default.LANGUAGES["nor"]))

    def test_two_unflagged_audio_tracks_are_not_the_original(self):
        streams = [audio("eng"), audio("jpn")]
        resolved, waiting, _explicit = default.resolve_priorities(
            [pref("original")], {}, streams, None, False
        )
        self.assertFalse(waiting)
        self.assertEqual(resolved, [])


class PathTests(unittest.TestCase):
    def test_trailer_park_boys_is_not_a_trailer(self):
        self.assertFalse(default.is_trailer_path(r"D:\Shows\Trailer.Park.Boys.S01E01.mkv"))
        self.assertTrue(default.is_trailer_path(r"D:\Movies\The.Matrix-trailer.mkv"))
        self.assertTrue(default.is_trailer_path(r"D:\Movies\Trailers\teaser.mkv"))

    def test_extras_folder_is_an_extra_and_a_feature_is_not(self):
        self.assertTrue(default.is_extra_path(r"D:\Movies\Film\Extras\interview.mkv"))
        self.assertFalse(default.is_extra_path(r"D:\Movies\Film.mkv"))

    def test_url_query_string_does_not_break_trailer_or_extra_detection(self):
        self.assertTrue(default.is_trailer_path("https://example.com/Film-trailer.mkv?v=1.2"))
        self.assertTrue(default.is_extra_path("https://example.com/Extras/featurette.mp4?token=abc.def"))


class ShowRuleTests(unittest.TestCase):
    def setUp(self):
        self.profile = tempfile.TemporaryDirectory()
        os.environ["SUBTITLE_ENFORCER_PROFILE"] = self.profile.name
        SETTINGS.clear()

    def tearDown(self):
        os.environ.pop("SUBTITLE_ENFORCER_PROFILE", None)
        self.profile.cleanup()

    def test_old_text_rules_import_once(self):
        SETTINGS["show_rules"] = "Bluey = off; Dark = German"
        shows = default.load_saved_shows()
        self.assertEqual([show["title"] for show in shows], ["bluey", "dark"])
        self.assertEqual(shows[1]["action"], "german")
        SETTINGS["show_rules"] = "Dark Matter = eng"
        again = default.load_saved_shows()
        self.assertEqual([show["title"] for show in again], ["bluey", "dark"])

    def test_search_lists_both_shows_but_a_saved_dark_does_not_match_dark_matter(self):
        hits = default.search_tv_shows(
            "dark",
            [{"title": "Dark", "year": "2017", "tmdb_id": "70523"}],
            [{"title": "Dark Matter", "year": "2024", "tmdb_id": "1"}],
        )
        self.assertEqual([hit["title"] for hit in hits], ["Dark", "Dark Matter"])
        saved = default.upsert_show_rule([], {
            "title": hits[0]["title"],
            "year": hits[0]["year"],
            "tmdb_id": hits[0]["tmdb_id"],
            "action": "default",
        })
        self.assertIsNone(default.match_saved_show("Dark Matter", "", saved, ""))
        self.assertEqual(
            default.match_saved_show(
                "",
                r"D:\TV\Dark (2017)\Season 1\e01.mkv",
                saved,
                "",
            ),
            "default",
        )
        self.assertEqual(default.match_saved_show("Wrong title", "", saved, "70523"), "default")

    def test_manage_replaces_and_deletes_a_saved_show(self):
        shows = default.upsert_show_rule([], {
            "title": "Dark",
            "year": "2017",
            "tmdb_id": "70523",
            "action": "ger",
        })
        shows = default.upsert_show_rule(shows, {
            "title": "Dark",
            "year": "2017",
            "tmdb_id": "70523",
            "action": "default",
        })
        self.assertEqual(len(shows), 1)
        self.assertEqual(shows[0]["action"], "default")
        self.assertEqual(default.saved_show_label(shows[0]), "Dark (2017) — Default language")
        default.save_saved_shows(shows)
        default.save_saved_shows(default.delete_show_rule(default.load_saved_shows(), 0))
        self.assertEqual(default.load_saved_shows(), [])

    def test_a_movie_and_a_show_keep_separate_rules(self):
        shows = default.upsert_show_rule([], {
            "title": "Dark",
            "year": "2017",
            "tmdb_id": "70523",
            "mediatype": "tvshow",
            "action": "default",
        })
        shows = default.upsert_show_rule(shows, {
            "title": "Dark",
            "year": "2017",
            "tmdb_id": "70523",
            "mediatype": "movie",
            "action": "eng",
        })
        self.assertEqual(len(shows), 2)
        episode = {
            "showtitle": "Something",
            "title": "Episode",
            "path": "",
            "year": "2019",
            "mediatype": "tvshow",
            "tmdb": "70523",
            "imdb": "",
            "library_id": "",
        }
        film = {
            "showtitle": "",
            "title": "Something else",
            "path": "",
            "year": "",
            "mediatype": "movie",
            "tmdb": "70523",
            "imdb": "",
            "library_id": "",
        }
        self.assertEqual(default.match_show_info(episode, shows), "default")
        self.assertEqual(default.match_show_info(film, shows), "eng")
        self.assertEqual(default.show_override_priorities("leave"), "skip")
        self.assertIn("leave", [code for code, _label in default.show_language_choices()])

    def test_two_saved_years_are_not_guessed(self):
        rules = [
            {"title": "Dark", "year": "2017", "tmdb_id": "1", "mediatype": "tvshow", "action": "ger"},
            {"title": "Dark", "year": "2018", "tmdb_id": "2", "mediatype": "tvshow", "action": "eng"},
        ]
        info = {
            "showtitle": "Dark",
            "title": "",
            "path": "",
            "year": "",
            "mediatype": "tvshow",
            "tmdb": "",
            "imdb": "",
            "library_id": "",
        }
        self.assertIsNone(default.match_show_info(info, rules))
        info["year"] = "2017"
        self.assertEqual(default.match_show_info(info, rules), "ger")
        hits = default.search_tv_shows(
            "dark",
            [{"title": "Dark", "year": "2017", "tmdb_id": "1", "mediatype": "tvshow", "library_id": "4"}],
            [{"title": "Dark", "year": "2016", "tmdb_id": "2", "mediatype": "movie"}],
        )
        self.assertEqual([hit["mediatype"] for hit in hits], ["tvshow", "movie"])

    def test_episode_title_is_excluded_from_candidate_titles(self):
        titles = default.candidate_titles({
            "mediatype": "tvshow",
            "showtitle": "",
            "title": "Pilot",
            "path": r"D:\TV\Dark\Season 1\S01E01.mkv",
        })
        self.assertNotIn("Pilot", titles)
        self.assertIn("Dark", titles)

    def test_language_for_a_show_starts_with_default(self):
        self.assertEqual(default.show_language_choices()[0], ("default", "Default language"))


class Response(object):
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TmdbLookupTests(unittest.TestCase):
    def test_source_reader_ignores_an_empty_key(self):
        self.assertEqual(default.api_key_from_text("API_KEY = ''"), "")
        self.assertEqual(
            default.api_key_from_text("API_KEY = '0123456789abcdef0123456789abcdef'"),
            "0123456789abcdef0123456789abcdef",
        )

    def test_movie_episode_and_search_requests(self):
        calls = []

        def opener(request, timeout=5):
            calls.append(request.full_url)
            if "/movie/550" in request.full_url:
                return Response({"original_language": "en"})
            if "/find/" in request.full_url:
                return Response({"tv_episode_results": [{"show_id": 42}]})
            if request.full_url.split("?", 1)[0].endswith("/tv/42"):
                return Response({"original_language": "ko"})
            if "/search/movie" in request.full_url:
                return Response({"results": [{"original_language": "ko"}]})
            if "/search/tv" in request.full_url:
                return Response({"results": [{"original_language": "de"}]})
            raise AssertionError(request.full_url)

        movie = default.lookup_tmdb_original_language(
            "v3-key",
            {"kind": "movie", "tmdb_id": "550"},
            opener,
        )
        episode = default.lookup_tmdb_original_language(
            "v3-key",
            {"kind": "tv", "imdb": "tt0944947", "title": "Game of Thrones"},
            opener,
        )
        searched = default.lookup_tmdb_original_language(
            "v3-key",
            {"kind": "movie", "title": "Parasite", "year": "2019"},
            opener,
        )
        show = default.lookup_tmdb_original_language(
            "v3-key",
            {"kind": "tv", "title": "Dark", "year": "2017"},
            opener,
        )
        self.assertEqual((movie, episode, searched, show), ("en", "ko", "ko", "de"))
        self.assertIn("/movie/550?", calls[0])
        self.assertIn("api_key=v3-key", calls[0])
        self.assertIn("/find/tt0944947", calls[1])
        self.assertTrue(calls[2].split("?", 1)[0].endswith("/tv/42"))
        self.assertIn("/search/movie", calls[3])
        self.assertIn("year=2019", calls[3])
        self.assertIn("/search/tv", calls[4])
        self.assertNotIn("year=", calls[4])

    def test_read_token_is_a_bearer_header(self):
        seen = {}

        def opener(request, timeout=5):
            seen["url"] = request.full_url
            seen["authorization"] = request.get_header("Authorization")
            return Response({"original_language": "fr"})

        language = default.lookup_tmdb_original_language(
            "eyJhbGciOiJIUzI1NiJ9.payload.sig",
            {"kind": "movie", "tmdb_id": "550"},
            opener,
        )
        self.assertEqual(language, "fr")
        self.assertNotIn("api_key=", seen["url"])
        self.assertTrue(seen["authorization"].startswith("Bearer eyJ"))


class SettingsTests(unittest.TestCase):
    def test_picker_and_rules_page(self):
        tree = ET.parse(os.path.join(ROOT, "resources", "settings.xml"))
        labels = []
        for options in tree.iter("options"):
            row = [option.attrib.get("label") for option in list(options)]
            if "Original language" in row:
                labels.append(row[:4])
        self.assertEqual(
            labels,
            [["Off", "Original language", "Default language", "Kodi subtitle language"]] * 5,
        )
        ids = [node.attrib.get("id") for node in tree.iter("setting")]
        self.assertNotIn("show_rules", ids)
        categories = [node.attrib.get("id") for node in tree.iter("category")]
        self.assertIn("rules", categories)
        self.assertIn("exceptions", categories)
        self.assertLess(categories.index("rules"), categories.index("exceptions"))

    def test_bool_setting_respects_true_default_when_unset(self):
        SETTINGS.clear()
        self.assertTrue(default._bool_setting("enabled", True))
        SETTINGS["enabled"] = "false"
        self.assertFalse(default._bool_setting("enabled", True))
        SETTINGS.clear()

    def test_context_hit_does_not_pass_episode_dbid_as_tvshowid(self):
        orig_info = xbmc.getInfoLabel
        orig_rpc = xbmc.executeJSONRPC
        rpc_calls = []

        def fake_info(name):
            return {
                "ListItem.DBType": "episode",
                "ListItem.DBID": "99",
                "ListItem.TvShowTitle": "Dark",
            }.get(name, "")

        def fake_rpc(payload):
            data = json.loads(payload)
            rpc_calls.append(data)
            return json.dumps({"result": {}})

        xbmc.getInfoLabel = fake_info
        xbmc.executeJSONRPC = fake_rpc
        try:
            hit = default.context_hit()
        finally:
            xbmc.getInfoLabel = orig_info
            xbmc.executeJSONRPC = orig_rpc

        tvshow_calls = [c for c in rpc_calls if c.get("method") == "VideoLibrary.GetTVShowDetails"]
        self.assertEqual(tvshow_calls, [])
        self.assertEqual(hit["title"], "Dark")

    def test_tmdb_item_query_ignores_stale_tmdbhelper_id(self):
        orig_info = xbmc.getInfoLabel
        orig_vis = xbmc.getCondVisibility

        def fake_info(name):
            return {
                "VideoPlayer.Title": "Actual Movie",
                "Window(home).Property(TMDbHelper.Player.title)": "Previous Movie",
                "Window(home).Property(TMDbHelper.Player.tmdb_id)": "12345",
            }.get(name, "")

        xbmc.getInfoLabel = fake_info
        xbmc.getCondVisibility = lambda expr: True
        try:
            query = default.tmdb_item_query()
        finally:
            xbmc.getInfoLabel = orig_info
            xbmc.getCondVisibility = orig_vis

        self.assertEqual(query["tmdb_id"], "")


if __name__ == "__main__":
    unittest.main()
