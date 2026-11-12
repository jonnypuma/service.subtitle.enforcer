# Changelog

## Version 2.4.0
- A show or movie can keep its own subtitle language
- Rules can be added from the playing title, search, or the library context menu, then changed or removed

## Version 2.3.1
- A subtitle embedded in the file is chosen before a sidecar of the same language

## Version 2.3.0
- Added Default language, the audio language marked default in the file
- TV show rules are chosen by search, and saved shows can be removed
- Show rules have their own Rules page

## Version 2.2.3
- Added a TMDB API key setting. An empty key uses the key from TMDBHelper

## Version 2.2.2
- Original language is checked against TMDBHelper. TMDBHelper wins when it disagrees with the file or the library

## Version 2.2.1
- Added Original language to each priority list. It follows the film's language, including when the audio is a dub

## Version 2.2.0
- A priority can follow Kodi's subtitle language, or a language name or code that is not in the list
- Trailers and extras are left unchanged
- Individual shows can be skipped, forced off, or given one language

## Version 2.1.1
- Fixed blank setting names in Kodi's settings screen

## Version 2.1.0
- Added an audio rule: forced subtitles, or no subtitles, when the audio is a language you understand
- Turns subtitles off when none of the priority languages are available
- Skips commentary, song, and signs tracks when a normal dialogue subtitle exists
- Optional on-screen message naming the subtitle that was chosen
- New icon and fanart

## Version 2.0.0
- Renamed the add-on to Subtitle Enforcer (`service.subtitle.enforcer`)
- Added five subtitle language priorities, applied when video playback starts
- Each language can allow hearing impaired (HI), SDH, and forced tracks
- Kept the seek-back behavior and made the wait and seek distance configurable
- Seek-back no longer runs when resuming in the middle of a file, or when the video cannot be seeked

## Version 1.1.1
- Fixed: removed provides line in addon.xml to prevent addon from appearing in Program addons and Services addons categories

## Version 1.1.0
- Fixed: Only applies subtitle fix to video playback, not audio/music
- Added: Icon and fanart support for addon display
- Improved: Better detection of video vs audio playback using isPlayingVideo()

## Version 1.0.0
- Initial release
- Waits 5 seconds after playback starts, then seeks back 1 second to fix subtitles
- Only triggers when playback starts near the beginning (first 2 seconds)
- Minimal interruption - only 1 second rewind instead of 5 seconds
- Silent background operation with logging support
