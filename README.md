# Subtitle Enforcer

**Project page:** [jonnypuma.github.io/#/service.subtitle.enforcer](https://jonnypuma.github.io/#/service.subtitle.enforcer) · **All add-ons and apps by jonnypuma:** [jonnypuma.github.io](https://jonnypuma.github.io/)

Kodi service add-on that turns on a preferred subtitle when playback starts. It can also seek backward a few seconds so embedded subtitles actually appear.

## What it does

On every video playback start:

1. Reads the subtitle tracks Kodi has found, including embedded tracks and sidecar files.
2. Walks your language list from priority 1 to priority 5.
3. Enables the first language that has an allowed track, and turns subtitles on.
4. If seek-back is enabled and the video started from the beginning, waits, then skips backward so Kodi redraws the subtitle.

Music playback is ignored. A resume in the middle of a file still gets the language choice, but it is not seeked.

## Language rules

Set up to five languages. Leave a priority on **Off** to skip it. Tick **I understand this language** for the languages you speak.

Each priority can also be:

- **Original language**, the first choice in the list. This is the film's own language. An audio track marked original is used first, then the original language stored in the library. A file with only one audio track uses that track. A dub that is currently playing is not treated as the original. TMDB is asked in the background for the film's language (and cached across episodes), and that answer wins if it disagrees with the file or the library. On **General**, **TMDB API key** is the key used for that lookup. Leave it empty to use the key from TMDBHelper. If the lookup cannot be made, the language TMDBHelper has already published for the playing item is used instead. `ja` and `Japanese` are treated as the same language. A regional match such as Chinese (Simplified) is kept when TMDB only says Chinese.
- **Default language** uses the audio track the file itself marks as default. That can be a dub. It is not the track you switched to, and it is not Kodi's interface language.
- **Kodi subtitle language**, which uses Settings → Player → Language → Preferred subtitle language. None skips that priority. Kodi's Default uses the interface language. Forced only selects a forced track in that language. Kodi's Original uses the same film language as Original language above.
- **Custom**, then type a name or code that is not in the list, such as `Welsh` or `cym`.

For each language:

- A normal full subtitle is always allowed.
- **Hearing impaired (HI)** prefers a hearing-impaired track when one exists.
- **SDH** prefers a track whose name says SDH.
- **Forced** prefers a forced track when one exists, while the audio is some other language.
- An unticked variant is never selected.
- If the ticked variant is missing, a normal subtitle for that same language is used.
- Commentary, song, and signs tracks are skipped when any priority has a normal dialogue subtitle. They are used only when nothing else matches. In forced-only mode, a signs track can still be chosen.
- A track inside the video is used before a sidecar of the same language. HI, SDH, and Forced then choose among those embedded tracks. A sidecar is used when the file has no usable embedded track for that language.

Kodi stores one hearing-impaired flag, shared by HI and SDH. Tracks named SDH follow the SDH box. Tracks named HI, or closed captions, follow the HI box. A track that is only flagged hearing-impaired, with neither HI nor SDH in the name, is used when either box is ticked.

## Audio

**When I understand the audio** applies only to languages you marked.

- **Use forced subtitles only** (the default): foreign audio gets a full subtitle from the priority list. Audio you understand gets a forced subtitle, or subtitles are turned off if there is no forced track.
- **Turn subtitles off**: audio you understand plays with no subtitles. Foreign audio still gets a full subtitle.
- **Choose a subtitle as usual**: the audio language is ignored.

**Turn subtitles off when nothing matches** is on by default. If none of the five languages exist, subtitles are disabled instead of leaving Kodi's current track on. This does nothing until at least one priority language is set.

## Rules

**Manage show rules** is the list of saved titles. **Add the title that is playing** links the show or movie that is already playing. **Search for a show or movie** looks in the Kodi library and on TMDB, then you pick the result. The choices are Default language, Original language, subtitles off, leave unchanged, Kodi's subtitle language, or one listed language.

In the library, **Set subtitle language for this title** links that movie or show. On an episode or season, it links the show. Select a saved rule to change its language or remove it.

A linked rule follows that show's library id, TMDB id, or IMDb id. A movie and a show that share a number stay separate. A file that has none of those still matches the same title and year, including a folder named `Dark (2017)`. `Dark` does not affect `Dark Matter`. Text rules saved in an older version are imported the first time the new list is used.

## Exceptions

Trailers and extras are left unchanged, including the seek-back. A trailer is a file whose name ends with "trailer", or a file inside a Trailers folder (including streaming URLs with query parameters). Extras are samples, featurettes, interviews, deleted scenes, and behind-the-scenes videos.

## On screen

**Show the chosen subtitle** is on by default. A short message names the track, or says that subtitles were turned off. Turn it off to keep playback quiet. The same lines are written to `kodi.log`.

## Seek back

This is the original Subtitle Sync Fixer behavior. Embedded subtitles sometimes stay invisible until you seek backward. The add-on waits (5 seconds by default), then seeks back (1 second by default). Both values can be changed. It only does this when playback starts in the first 2 seconds, and it skips live videos that cannot be seeked.

## Install

1. Zip the `service.subtitle.enforcer` folder, or copy it to the Kodi add-ons folder:
   - **Windows**: `%APPDATA%\Kodi\addons\`
   - **Linux**: `~/.kodi/addons/`
   - **macOS**: `~/Library/Application Support/Kodi/addons/`
   - **Android**: `/sdcard/Android/data/org.xbmc.kodi/files/.kodi/addons/`
2. In Kodi, use **Settings → Add-ons → Install from zip file**, or restart Kodi and enable **Subtitle Enforcer** under **My add-ons → Services**.

The add-on id is `service.subtitle.enforcer`. Disable the old Subtitle Sync Fixer service if it is still installed, or both will seek at the start of playback.

## Settings

**Settings → Add-ons → My add-ons → Services → Subtitle Enforcer → Configure**

- **General**: master switch, seek-back, the audio rule, turning subtitles off when nothing matches, the on-screen message, and the TMDB API key.
- **Languages**: priority 1 through 5. Each can be Original language, Default language, a listed language, Kodi's subtitle language, or a custom name or code, with “I understand this language”, HI, SDH, and Forced.
- **Rules**: give a show or movie its own subtitle language. Add the playing title, search, or change and remove a saved rule.
- **Exceptions**: skip trailers and skip extras.

Setting values apply to the next playback. Restart Kodi after installing or updating the add-on so it loads the new settings and service.

## Tests

From the add-on folder:

```
python -m unittest discover -s tests
```

## Logs

Enable debug logging only if you need more detail. Normal actions are written at info level and start with `Subtitle Enforcer`. Look in `kodi.log` for lines such as:

- `Subtitle streams: ...` shows what Kodi reported
- `Enabled priority 1 English: ...` shows the track that was selected
- `No subtitle matched the language priorities` means none of the tracks fit the rules

## Requirements

Kodi 19 (Matrix) or later.
