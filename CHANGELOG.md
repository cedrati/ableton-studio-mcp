# Changelog

Ableton Studio MCP by Olivier Cedrati ([cedrati/ableton-studio-mcp](https://github.com/cedrati/ableton-studio-mcp)). Versions 1.x were a fork of [ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp); 2.0 is an independent rewrite.

Since 2.0 one version number covers the server and the Live control surface; the server refuses a control surface of another version. After updating, run `ableton-studio-mcp install` and **restart Live**: re-selecting the control surface does not reload the code. (1.x versions below are the Remote Script version.)

## Unreleased

Server only: no new control surface, nothing to reinstall in Live.

### Added

- **Structured humanization**: variation that never repeats but stays even, instead of random noise. Random humanization moves every note independently; musicians drift with a long memory. These tools use irrational rotations n -> {n * theta + phase} ([docs/structured-humanization.md](docs/structured-humanization.md)).
  - `quasiperiodic_rhythm`: writes a pattern where hits fall when the rotation is inside a window. With the default density it is a Sturmian word (gaps of only two sizes, the infinite relative of a Euclidean rhythm): it seems to loop, then slowly slides. Velocities follow the rotation and never settle; `accent_role` adds a second pad only where the pattern slips against a near-period. Pads are found by role like `write_drum_pattern`. The reply gives the loop lengths that close almost seamlessly (`near_periods`) and how audible the loop point is (`seam_mismatch`). Checked in Live 12 on the 808 Core Kit: 8 bars, 78 hats, 4 rim accents, gaps of 1 and 2 steps.
  - `transform_clip` operation `humanize_structured`: timing, velocity and length moved by three rotations that are linearly independent over Q (so they don't move together), mixed with a slow quasi-periodic push and lay-back curve over `drift_bars`; notes of a chord move as one; another `phase` gives another take with the same character.
- The default rotation comes from the Cedra constant C = sqrt(3) + (3/2) sqrt(2) - 2, ln C ~ 0.617 ([cedrati/cedra](https://github.com/cedrati/cedra)), which starts like the golden ratio then drifts away from it; `golden` and `silver` are also available.

## 2.5.0

New control surface series, with new commands (`back_to_arrangement`, `delete_device`, `move_device`): run `ableton-studio-mcp install` and restart Live.

### Added

- **Back to Arrangement** (`back_to_arrangement`): once a track has played a Session clip, Live ignores its Arrangement clips until *Back to Arrangement* is pressed; stopping the transport doesn't reset it (measured in Live 12.4). The tool presses it, waits until Live has applied it, and names the tracks whose Session clips it stopped. `get_session_info` now reports `back_to_arranger`.
- **Delete and move devices** (`delete_device`, `move_device`, #84) on tracks, return tracks and the main track, replying with the new chain. Measured in Live 12.4: `move_device` counts the target position with the device still in the chain, so moving right is corrected by one.
- **`get_device_parameters` filters** (#85): `names` (exact or parts of names), `query` (substring) and `brief` (index, name, displayed value). Operator's full reply is about 56,000 characters; `query="Filter"` returns 9 of its 195 parameters.
- **Ratios as producers say them** (#86): `set_device_parameters` accepts `8`, `"8"`, `"8:1"`, `"8.00 : 1"` and `"inf : 1"` on parameters Live shows as `N : 1` (Compressor, Glue...), and picks the nearest value Live can show (`"10.00 : 1"` → `10.0 : 1`). A plain number inside the internal range still sets the raw value.

### Fixed

- **`listen_to_arrangement` could measure the wrong material** (#83). After auditioning scenes, tracks still overriding the Arrangement played Session clips during the take, and the report (LUFS, true peak, findings) described that instead of the Arrangement. It now goes back to the Arrangement first (`back_to_arrangement=true` by default; `false` keeps whatever plays and says so), reports what it stopped, and warns when a track's meter contradicts its Arrangement clips: silent where it has clips, sounding where it has none.
- `build_arrangement` warns when tracks still override the Arrangement it just built.

### Documentation

- README, package and registry descriptions now present **sound design** and **sampling** as features of their own: a *Sound design* row (presets, recipes, musical parameter values, auditioning, saved sounds) and a *Sampling* row (Simpler slicing, `chop_sample`) in the features table, examples for designing sounds and for taking an idea from a style to a finished track, and a FAQ answer on sound design.
- The *What's next* answer follows the roadmap: hearing a sound and reverse-engineering its patch (#82), A/B with reference tracks, learning a style from your own sets.
- The Remote Script badge and the `doctor` / `get_remote_script_info` check follow the version (they still said 2.3).
- The tagline and the GitHub description say the assistant can work alongside you in Live, not only in your place.

## 2.4.0

New control surface series (its code is unchanged): run `ableton-studio-mcp install` and restart Live.

Learned building a full track in Live 12.4 with the assistant.

### Added

- **Producer automation gestures** (`automation_gesture`): `delay_throw` (delay send up on the last beat of each phrase), `reverb_swell`, `filter_rise` / `filter_fall`, `drop_cut` (the breath before a drop), `stutter` (16th-note gate), `fade_in` / `fade_out`, drawn in a Session clip and aimed at the right parameter by themselves: the return named like a delay or a reverb, the track's filter (an Auto Filter first, then the synth's own; a high-pass cleaning the lows is skipped). Measured in Live: a clip envelope leaves its parameter where it ends and a clip without an envelope doesn't reset it, so after a cut the next section stayed silent; when a move ends away from the resting value, the track's other clips now get it held.
- **Chop a sample in one call** (`chop_sample`): loads it in a Simpler (adding one if needed), slices it (16 slices, or 64 grains for micro-sampling), warps it from the tempo in its file name and transposes it to the song's key from the key in its name (Splice-style names: `_127_`, `Fmin`, `D#m`), then writes a chop pattern: `hook` (the same grain at the same place every bar, a hook where a random grain on every hit would sound like noise, off-beat accents, ghost hits with a chance), `rearrange` or `stutter`. Checked in Live: a guitar loop named 122 BPM, D#m was warped over 32 beats and moved +2 semitones to F.

### Fixed

- **`build_arrangement` left sections silent.** A clip that didn't divide its section, or was longer than it, was skipped with only a warning. It is now placed once more and cropped at the section's end (measured in Live 12.4: an Arrangement clip takes the length of its loop brace once looping is off).
- **`build_arrangement` kept older clips.** A copy only overwrites where it lands, so a rebuild kept the previous build's clips where a track no longer played. The clips already in the range are now listed (`existing_clips`, also in a dry run) and deleted only with `clear=true`: deleting is the artist's call.
- **A groove could have no effect without anyone knowing.** A new set's global Groove amount is 0 %, where a clip's groove changes nothing; `set_clip_groove` now says so and how to raise it.

### Changed

- Development and the release build use Python 3.15 (`.python-version`); the tests also run on 3.10, 3.13 and 3.14, and the Docker image uses Python 3.15.

## 2.3.0

New control surface series: run `ableton-studio-mcp install` and restart Live.

### Added

- **Sound recipes** (`sound_recipes`, `design_sound`): sub, acid and reese bass, dub chord stab, pluck and warm pad on Drift, supersaw on Wavetable, FM bell on Operator: the device, parameter values as musical values, how to play the sound and what to listen for; applied in one undo step, with your own tweaks on top. Every recipe was applied in Live 12.4 without error.
- **Listen-and-tune loop** (`audition_sound`): plays a bass line, chords or an arpeggio on a track in an empty stretch after the song, records and analyses it like `listen_to_arrangement`, then removes everything it added (one undo step). In Live, a sub bass, a pad, a pluck and an acid bass came out clearly different (e.g. sub +29 dB below 60 Hz, pluck centred on the mids).

### Fixed

- **Listening and recording could capture the wrong passage.** Measured in Live 12.4: playback started by a script begins at Live's own start marker, not where `current_song_time` was set, and moving the playhead while recording splits the take. Recording now sets the passage as the punch-in/out range, starts playback, jumps one beat before the range and only then switches Arrangement Record on, so exactly the requested passage is recorded; loop and punch settings are put back. `start_playback` now plays from the playhead.
- **Undo of grouped actions** (a tool that records, or loads devices) now steps back until the set matches the fingerprint taken before the action, up to 32 of Live's steps; if that never happens, every step is redone and the action is reported as not undoable; it never undoes an earlier action. The fingerprint now includes the notes of MIDI clips.


New control surface series: run `ableton-studio-mcp install` and restart Live.

### Added: sound design

- **Read Live's presets** (`find_presets`, `read_preset`): about 10,000 native device and rack presets on a typical install (Core Library, packs, User Library), searched by name, device, category or library and read straight from their files without Live. A preset is shown as what differs from the device's default preset (Live ships one per device), in the device's own units, with its samples, and for racks the named macros and every chain with its devices.
- **Load a preset by name** (`load_preset`), found where Live's browser shows it (Core Library racks live under Sounds, Drum Racks under Drums…), with a targeted name search as a fallback.
- **Musical values** (`set_device_parameters`): "800 Hz", "2.5 kHz", "5 ms", "-6 dB", "-inf dB", "35 %", "+7 st", a named setting ("Bell") or a textual display ("1/16"). The internal value is found by searching the parameter's range until Live's own display matches, so it works for every native device without per-device tables. All values are checked before anything changes.
- **Save and reload designed sounds** (`save_sound`, `list_sounds`, `load_sound`) as JSON in `<User Library>/Ableton Studio MCP/Sounds/`, since Live's API cannot write `.adv` presets. Verified in Live: a Drift sound reloaded with all 66 parameters identical.

## 2.1.1

### Fixed

- **Undo of an action that loads a device.** In Live 12.4, loading a browser item closes the open undo step and records its own, so an action such as "new track, load Drift, set the tempo" spanned three of Live's undo steps and one `undo` only took back part of it. Each action is now recorded with a fingerprint of the set taken before it; undoing it steps back until the set matches that fingerprint (never further than the action itself), and redo replays the same steps. Undo logic moved to its own module (`undo.py`).


New control surface series: run `ableton-studio-mcp install` and restart Live.

### Added

- **Undo and redo** (#37): `undo` / `redo` tools (Live's own Undo, 1–50 steps) and `start_undo_group` / `end_undo_group` to make a whole request one step.
- **One undo step per change.** Measured in Live 12.4: Live merges every change a script makes into a single undo step, whatever the delay between them, so one Cmd+Z used to take back a whole session of edits. The control surface now wraps each change in its own step (closed even when the change fails or settles on a later tick), so Undo takes back exactly the last action.
- **Multi-change tools are one step:** `write_drum_pattern`, `write_progression`, `transform_clip`, `write_clip_evolution`, `build_arrangement`, `import_midi_file`, `load_drum_kit`, `simpler_sample` and `listen_to_arrangement` group their work.
- An undo group left open (server stopped, client gone) is closed after two minutes so it can't swallow later edits.

### Changed

- The server no longer tries to reach Live when it starts (up to 9 s when Live was unreachable): it starts at once and connects on the first tool call.

## 2.0.1

- **Listed in the official MCP Registry** as `io.github.cedrati/ableton-studio-mcp` (`server.json`); the release workflow publishes each version there after PyPI.
- **Server and control surface are compatible within a series** (2.0.x with 2.0.x) instead of requiring the exact same version, so a server-only release never asks you to reinstall the control surface or restart Live. `doctor` and `get_remote_script_info` report the series.
- Nothing changes in Live: the control surface stays 2.0.0.

## 2.0.0

Ableton Studio MCP becomes a project of its own. Everything that still came from the original ableton-mcp has been rewritten: the connection to Live, the installer, the tools' organisation and the whole Live control surface. What remains in common with ableton-mcp is 2.1 % of the lines, all generic (`from __future__ import …`, calls imposed by Live's API such as `song.start_playing()`, protocol field names). The copyright is now Olivier Cedrati's alone (MIT).

**Upgrading from 1.x:** run `ableton-studio-mcp install --remove-legacy`, restart Live and choose **AbletonStudioMCP** as the control surface instead of *AbletonMCP*. Tools, their names and parameters are unchanged.

### Changed

- **New names.** Python package `ableton_studio_mcp` (was `MCP_Server`); Live control surface **AbletonStudioMCP** (was *AbletonMCP*): select it again in Live's Control Surface settings. The `ableton-mcp` / `ableton-mcp-install-script` command aliases are gone.
- **New installer:** `ableton-studio-mcp install` (`ableton-studio-mcp-install-script` still works). It installs the control surface as a folder, swapped in only once fully copied, offers `--dry-run`, and reports the old *AbletonMCP* folder (`--remove-legacy` deletes it, since both use the same port). The `.bak` backup, `--legacy`, `--force` and `--sync-bundle` options are gone.
- **One copy of the control surface:** it lives inside the package (`ableton_studio_mcp/live_script/`) instead of a repository folder plus a bundled duplicate; a single version number is checked by the tests and the release workflow.
- `doctor` also warns when the old *AbletonMCP* control surface is still installed.
- Dockerfile and `smithery.yaml` rewritten for the new entry point.
- **Server core rewritten.** New connection to Live (`live.py`): one socket reopened automatically when Live restarts, a stale socket detected before use, one request at a time, per-command timeouts, and the control surface's version checked on every connection (replaces the old handshake module and its retry hook). Typed errors (Live unavailable, Live refused, control surface too old), each reported to the assistant as one clear line by the new `@tool` decorator (`app.py`).
- **Tools split by domain** into `ableton_studio_mcp/tools/` (session, tracks, clips, devices, browser, routing, listening, midi, theory, drums, evolution) instead of one 3,500-line `server.py`; tool descriptions rewritten. Same 92 tools with the same parameters. Tools no longer take the unused `ctx` argument.
- Error messages changed: "<tool> failed: <Live's reason>" instead of "Error <doing something>: …".
- CI now builds the package, installs it in a clean environment and checks that every tool and the control surface are inside (the `tools` subpackage was missing from the first 2.0 build).
- **Control surface rewritten** as a package of modules instead of one 4,100-line file (now 2,800 lines): a command registry replaces the 460-line `if/elif` dispatcher; each handler's signature is its contract (missing or unknown parameters are refused by name instead of silently defaulting to track 0 or 120 BPM) and the advertised capability list is generated from it; a new socket server; browser, snapshot, clip, note, track, session and device code written anew.
- **No more threads in the control surface, and much faster.** Live's embedded Python only lets background threads run when Live calls into Python (~10 times a second), so the socket thread of 1.x paid for several of those per request. The control surface now does everything on Live's main thread from `update_display`: non-blocking sockets, requests run and answered in the same pass, and a few milliseconds' wait for the next request of a sequence. Reads (`get_*`) are chained in one pass; after any change Live gets a display update of its own before the next command (changing the routing of a track created in the same pass crashed Live 12.4 during testing). Measured on the same set (Live 12.4, 3 tracks, 2 returns): session or track info 200 ms → under 1 ms, a write (tempo) 409 ms → 100 ms, full snapshot with notes and parameters 5.9 s → 0.23 s. This also means every command runs on the main thread, as Live's API requires (1.x ran reads on the socket thread).
- **Protocol 2: newline-delimited JSON** both ways (no more re-parsing the whole buffer after every packet). The server still talks to 1.x control surfaces, and the control surface still accepts 1.x servers.
- Stricter input checks: notes (pitch 0–127, positive duration, start ≥ 0, velocity clamped; a bad note is refused with its position and nothing is written), tempo 20–999, positive clip length, parameter values within the parameter's range, track insert positions, negative song positions.
- Snapshots no longer ask MIDI clips for warp markers, which filled Live's log with "Warp markers are only available for Audio Clips". Snapshot schema renamed `ableton_studio_mcp.snapshot/1`.
- Removed six commands nothing used (`get_browser_item`, `get_browser_categories`, `get_browser_items`, `load_instrument_or_effect` on the Live side, `inspect_rack`, `map_rack_magnitude`).
- Lint (ruff) in CI; 11 new tests for the control surface.
- 22 new robustness tests against a fake control surface on a real socket: Live closed or restarted, connection lost mid-request, timeouts, fragmented replies, outdated control surface, Live started after the server, parallel calls.

## Remote Script 1.17.0

First release published on PyPI: `uvx ableton-studio-mcp`.

### Changed

- **Renamed to Ableton Studio MCP** (`cedrati/ableton-studio-mcp`, standalone repository; the old URL redirects). Package `ableton-studio-mcp`; commands `ableton-studio-mcp` and `ableton-studio-mcp-install-script`, the former `ableton-mcp` / `ableton-mcp-install-script` kept as aliases.
- `TERMS.md` rewritten for this project: what talks to what, and the files the tools create.
- README links and banner use absolute URLs so they also work on PyPI.
- LICENSE lists Olivier Cedrati first and keeps the original copyright for the portions that come from ableton-mcp, in the standard MIT layout.

### Removed

- **Telemetry and data collection removed entirely.** The usage telemetry and the research-dataset recording inherited from the original project are gone: `telemetry.py`, the `dataset` package, the consent question, the Supabase dependency, the dataset tools (`set_dataset_consent`, `submit_intent`, `rate_last_action`, `prefer_candidate`, `reject_last_action`, `record_audition`) and the `user_prompt` argument every tool carried for telemetry. The Remote Script no longer installs listeners on every track and clip to log your edits in Live (`drain_passive_events` removed). Closes #34.

### Added

- **`ableton-studio-mcp doctor`:** checks Python, uv, the Remote Script installed in the User Library, the Control Surface setting in Live's preferences and the script actually running in Live, then prints what to fix (e.g. "the new script is installed but Live still runs the old one: restart Live"), with the Remote Script errors from Live's log when Live does not answer. Exit code 1 if something is broken. `ableton-studio-mcp --version` prints the version.
- **Release workflow:** pushing a `vX.Y.Z` tag checks the versions, runs the tests, builds and publishes the package to PyPI (trusted publishing) and creates the GitHub release.
- **`delete_locator`:** removes a locator by beat position or by name (refused if several locators share the name, listing their positions). Like `create_locator`, it waits for the playhead to reach the cue, toggles it off, waits until Live has removed it and restores the playhead; it refuses to run while playing.
- GitHub Actions CI: tests on Python 3.10, 3.12 and 3.13, and a check that the bundled Remote Script copy matches the source.

### Fixed

- `device_inventory` showed rack chain names as null.
- If Live was not running when the server started, tools that check the Remote Script kept refusing with "missing capability (loaded=None)" even after Live was opened. The server now checks the script version again on every new connection to Live and whenever the last check failed; if Live really is closed, the message says so instead of asking to reinstall the script.
- `listen_to_arrangement` left every take (and Live's `.asd` file) in the project's `Samples/Recorded` folder, about 25-35 MB per listen of a short piece. Takes are now deleted once analysed (`keep_audio=true` keeps them; only files named after the listening track are ever removed), and only the 20 most recent spectrogram images are kept in the temp folder.

## Remote Script 1.16.0

### Added

- **`device_inventory`:** everything loaded in the set (every device on tracks, return tracks and the main track, rack chains) with what each one is and what it is for, plus (optionally) the installed VST/VST3/AU plug-ins by vendor.
- **`device_knowledge`:** sheets for Live's native instruments, audio and MIDI effects and the Max for Live devices bundled with Live 12, summarised from the Live 12 manual (purpose, key parameters, electronic/techno uses, sidechain, tips), and descriptions of common plug-in families (Arturia V Collection emulations, Xfer, u-he, FabFilter, Valhalla, Plugin Alliance, Newfangled Audio, Elektron Overbridge...). It also records that Live 12's MIDI Tools (Transform/Generate) are not reachable from the API, and which server tools cover the same ground.
- **`get_device_info`** (Remote Script): Live's real device name (`class_display_name`, also added to every device listing), kind, latency, and the device-specific API below.
- **`set_device_sidechain`** (Remote Script): routes a Compressor's sidechain from another track and switches it on: kick-to-bass ducking without touching the interface. Live's API exposes sidechain routing on the Compressor only.
- **`plugin_presets`** (Remote Script): a plug-in's preset list and preset selection, as far as the plug-in exposes them to Live.
- **`simpler_sample`** (Remote Script): load a sample into Simpler, choose classic / one-shot / slicing, slice by transient, beat, region or manually, warp as N beats, crop, reverse.
- **`rack_variation`** (Remote Script): list, recall, store rack macro variations, randomize macros.
- **`set_drum_choke`** (Remote Script): put Drum Rack pads in a choke group (closed/open hi-hat).

### Verified in Live 12

Inventory of a set (Drum Rack with its 18 chains, Operator presets, return effects) and of 429 installed plug-ins from 46 vendors; a Compressor on the bass routed to the drum track (Post FX) with S/C On; closed and open hats choked together; an 85-second recording loaded into Simpler and sliced into 16 regions. Arturia Acid V (VST3) exposes a single "Default" preset and no parameters to Live until its parameters are configured in Live: plug-ins that keep presets in their own browser can't be browsed from the API.

## Server update: long-form evolution and arrangement (Remote Script unchanged, 1.15.0)

### Added

- **`write_clip_evolution`:** extends a MIDI loop to N bars (notes tiled, probability kept) and writes long automation curves on it: linear, exp (build-up), log, S-curve, swell, slow sine/triangle LFO, phrase steps, random walk, hold; per lane, on a device parameter or the mixer (volume, pan, sends), optionally over part of the clip.
- **Arrangement automation through Session clips:** Live's API cannot write Arrangement automation, but a Session clip's envelopes become track automation when the clip is copied to the Arrangement, checked by ear in Live 12 (a volume envelope plays as a −60 → −22 dBFS ramp in the Arrangement).
- **`build_arrangement`:** lays out the Arrangement from Session clips, section by section, from a template (`techno_dj` ≈ 208 bars with DJ intro/outro, `techno_64`, `minimal`, `house`) or custom sections; track roles from track names (kick, drums, hats, perc, rumble, bass, chords, pad, lead, vocal, fx), per-section clip variants (e.g. the automated build), clips tiled to fill each section, named locators, `dry_run` to preview.
- **`arrangement_overview`:** a map of the Arrangement, one character per block of bars per track.
- **`arrangement_templates`:** the templates (sections, bars, energy, roles, production tips) and curve shapes.

### Verified in Live 12

A 64-bar techno track (909 kit, acid bass, dub chords) built from 6 Session clips: bass filter opening over 16 bars (S-curve) and 16 bars (exp, with resonance), chords' reverb send and volume rising over the 8-bar build; 23 placements and 6 locators, overview matching the plan; listening showed the intended energy curve (intro −23 LUFS, build rising −20 → −15, peak −11).

## Remote Script 1.15.0

### Added

- **Drum programming (server):** `write_drum_pattern` programs a Drum Rack from a pattern library and/or per-role grids. Roles (kick, clap, closed/open hat, rim, ride, perc, shaker, toms, conga, cowbell...) are matched to pads by their names, in English and French; a similar free pad stands in for a missing role, missing ones are reported, and General MIDI notes are only used without a Drum Rack (they would hit empty pads). Grid language: `x` hit, `X` accent, `o` ghost, `2`-`4` ratchets, `?` 50 % and `*` 25 % chance (Live 12's per-note probability). Grids of any length cycle over the clip, so a 12-step loop drifts against 16-step bars. Euclidean layers, swing, fills every N bars (roll, drop, open-hat lift, ratchet, crash), probability ghost-hat variation, humanize.
- **`drum_patterns`:** 19 styles focused on electronic music (techno four-on-the-floor, rolling, hypnotic/polyrhythmic, minimal, dub, hard/industrial, acid, Detroit, classic and deep house, tech house, afro house, UK garage, breakbeat, electro, drum and bass, dubstep, trap, EBM) with tempo, swing and production notes; Euclidean rhythm generator (E(3,8) = tresillo).
- **`get_drum_map`** (Remote Script `get_drum_rack_map`): filled pads of a track's Drum Rack with their inferred roles.
- **Groove Pool** (Remote Script): `get_groove_pool`, `set_clip_groove`, `set_groove_params` (timing/random/velocity/quantization amounts and the global Groove amount).
- **Note probability** (Remote Script): `add_notes_to_clip` now writes `probability`, `velocity_deviation` and `release_velocity` through Live 11+'s extended note API; before, they were dropped.

### Verified in Live 12

808 Core Kit mapped by pad names (Bass Drum, Closed/Open Hi Hat, Hand Clap, Maracas, Cow Bell...), a 4-bar rolling techno pattern with a Euclidean percussion layer and a roll fill written and read back (128/128 notes), a minimal techno pattern read back with its 49 probability notes, a Groove Pool groove applied to the clip.

## Remote Script 1.14.0

### Added

- **Music theory knowledge (server):** `music_scales` lists ~50 scales and modes (church modes, harmonic/melodic minor and their modes, harmonic major, double harmonic, pentatonics, blues, bebop, symmetric, Japanese, gamelan, flamenco) with character, characteristic note and typical styles, or details one in a key: spelled notes, degrees, diatonic seventh chords with roman numerals and functions, relative modes, Live's scale name. `music_styles` gives a style sheet for 24 styles (baroque to synthwave): tempo, metre, scales, harmonic language, progressions, groove and swing, bass, melody, arrangement, accompaniment patterns, Live devices. `music_chord_ideas` suggests reharmonisations (tritone substitution, ii-V, relatives, borrowed chords).
- **`analyze_clip_music`:** key/mode detection (Krumhansl-Kessler profiles refined by scale coverage, tonic weight and harmony: a V7 points to its tonic, a final dominant is a half cadence; long held notes are capped so a Picardy third doesn't turn a minor piece major), chords per segment with roman numerals in a `basic` (triads and sevenths, for classical/pop/counterpoint) or `jazz` vocabulary, out-of-scale notes, range, rhythm and top-line motion.
- **`transform_clip`:** chains operations on a clip, in place or into an empty slot: transpose (chromatic or diatonic), change_mode, snap_to_scale, invert (chromatic or diatonic), retrograde, time_scale, quantize, swing, humanize, accent, articulate, fold_range, harmonize (diatonic parallel voices), arpeggiate, strum, voice_chords (close, drop 2, open, spread).
- **`write_progression`:** roman numerals (secondary dominants, borrowed chords, Neapolitan) or a style's progression, voiced with smooth voice leading and played with an accompaniment pattern (block, pulse, offbeat, arpeggios, Alberti bass, bossa, waltz, ballad, stabs), with a bass line.
- **Live's song scale (Remote Script):** `get_song_scale` / `set_song_scale` (root, scale, Scale Mode), mapping this server's scale names to Live's.
- **Parameter display (Remote Script):** `get_device_parameters` and `set_device_parameter` report Live's display string ("Bell", "1.56 kHz", "-6.0 dB") and, for list parameters, their value names, instead of bare normalised numbers.

### Verified in Live 12

Song scale set to C harmonic minor; a fugue analysed as C minor with its circle-of-fifths episode (iv-bVII-bIII-bVI) and V7-I ending; a jazz progression written in Bb (Imaj7-vi7-ii7-V7), re-voiced in drop 2, arpeggiated, swung into another slot and analysed back; EQ Eight filter types read as named values.

## Remote Script 1.13.0

### Added

- **Mix / master report (server, numpy):** `analyze_mix` measures a WAV/AIFF like a mastering engineer: loudness per ITU-R BS.1770 / EBU R128 (integrated with both gates, short-term and momentary maxima, loudness range per EBU Tech 3342), true peak (4x windowed-sinc oversampling around the loudest samples), PLR, crest factor, long-term spectrum in 1/3-octave bands as power spectral density (FFT-analyser convention: pink noise reads -3 dB/oct), tilt against a -4.5 dB/oct reference and the deviation of each region (sub, lows, low-mids, mids, high-mids, highs, air), narrow peaks with note names, stereo correlation and side/mid overall and per band (low-end mono), DC offset. Findings are ranked problème / attention / ok with fixes using Live's own devices (EQ Eight, Utility "Bass Mono", Limiter), against a delivery target: `streaming` (-14 LUFS), `club`, `classical`, `broadcast` (EBU -23), `podcast`.
- **Spectrogram image:** log-frequency spectrogram (20 Hz-20 kHz) with the short-term loudness curve and the target line, returned as an image the model can look at. PNG written without any imaging library.
- **`listen_to_arrangement`** returns that report and the spectrogram by default (`report="mix"`, `target=...`), plus every track's Live meter sampled during the take, so the report says which tracks carry the mix. `report="basic"` keeps the previous output.
- **`get_track_meters`** (Remote Script): output meters of every track, return track and the main track.
- `numpy` is now a dependency.

### Checked against reference signals

A 1 kHz sine at -23 dBFS on both channels reads -23.0 LUFS at 44.1 and 48 kHz (EBU Tech 3341 case 1); two 20 s plateaus 10 dB apart give a 10 LU loudness range; a fs/4 sine sampled 3 dB under its crest reads 0 dBTP true peak; pink noise reads -3 dB/oct.

### Why not Live's own meters

Spectrum, EQ Eight's analyser and Max for Live meters such as Flufs only draw their readings: no value is exposed to the API (Flufs' CSV export goes through a file dialog). The analysis therefore runs on the recorded master; those devices stay useful as on-screen meters for the user.

## Remote Script 1.12.0

### Added

- **Return and main tracks:** `load_instrument_or_effect`, `get_track_info`, `get_device_parameters` and `set_device_parameter` take `track_type` (`track`, `return`, `master`): one shared reverb on a return track, a limiter on the main track. The server only sends `track_type` to a script that advertises `return_master_devices`; an older one would act on the regular track with the same index.
- **Routing:** `get_track_routing` / `set_track_routing` read and set input/output routing type and channel and monitoring, matching the names Live shows (exact, else a unique substring). Types are written before channels, since the channels depend on the type. Return and main tracks only have an output.
- **Arrangement recording:** `record_arrangement` moves the playhead, turns Arrangement Record on, plays, and a watcher stops at the end position (or when playback is stopped by hand). `get_recording_status`, `stop_arrangement_recording`. `get_audio_clip_file` gives the file behind an audio clip.
- **Listening (server):** `listen_to_arrangement` records the main output on a temporary resampling track (finds the input by its localized name, e.g. "Rééchantillonnage"), disarms other tracks for the take, analyzes the file and deletes the track. `analyze_audio_file` measures any WAV/AIFF (PCM 8–32 bit, float 32/64): levels, clipping, loudness over time, silences, stereo correlation, low/mid/high balance.
- **MIDI files (server):** `import_midi_file` reads format 0/1 Standard MIDI Files without a dependency and imports them into a Session clip (created to fit, rounded to a bar) or an Arrangement clip, with track/channel filters and transposition. Notes on the same pitch and start in two voices are merged, as Live keeps one.
- Docs: plugins (VST/AU), User Library, Packs and the other browser roots were already reachable by path and URI; the tool descriptions now say so.

### Not possible from a Remote Script

Saving the set, exporting audio, creating group tracks and writing Arrangement (song) automation such as tempo are not exposed by Live's API. `listen_to_arrangement` stands in for an export when the goal is to check the result.

### Verified in Live 12

Loaded a convolution reverb on a return track and a limiter on the main track, set their parameters, browsed `plugins` and `user_library`, routed a MIDI track's input from another MIDI track (monitoring In) and back, imported a two-voice invention (458 notes sent, 457 kept by Live: two voices share one note, which led to the duplicate merge), and listened to an 85-second passage end to end (temporary track created, recorded, analyzed, deleted).

## Remote Script 1.11.0

### Added

- **Clip loop and markers:** `get_clip_loop` and `set_clip_loop` read and change the loop switch, the loop brace (`loop_start`, `loop_end`, or `loop_length`) and the start/end markers, on Session and Arrangement clips. Live refuses a start at or past the end at any moment, so the writes are ordered by the direction of the move, and both ranges are checked before anything is written. The reply gives the applied values and an `adjusted` entry for any value Live changed. Units are reported: beats, or seconds for an unwarped audio clip.
- A `playback` summary says what actually plays. Live 12.4.5 plays an unlooped clip from `loop_start` to `loop_end` and ignores a `start_marker` write on it, so start/end markers given for an unlooped clip are written to the loop brace (the reply says so).

### Fixed

- `set_clip_warp(original_bpm=…)` rounded the end marker down to a whole beat: a 16-beat drum loop 1 ms short at 140 BPM got its marker at beat 15. A file within 0.02 beat of a whole number of beats is now pinned to that beat (to the end of the file when it is a hair short, never past it), and the reply says so.

## Remote Script 1.10.0

### Added

- **Notes in Arrangement clips:** `get_clip_notes`, `add_notes_to_clip` and `clear_notes_from_clip` take `location="arrangement"`, with the clip index listed by `get_arrangement_clips`. Note times stay in clip beats; Arrangement replies add `arrangement_start`, `arrangement_end` and `start_marker` to place them in the song. Session calls are sent exactly as before.
- **`remove_notes`:** removes the notes that start in a time range and a pitch range, leaving the others, to rewrite one bar or one drum lane without clearing the clip.

### Safety

- The server only sends `location="arrangement"` to a Remote Script that advertises `arrangement_notes`: an older script would ignore it and edit the Session clip in the same slot.

### Fixed

- `clear_notes_from_clip` also removes notes past the clip's `length` (after its end marker or loop end were moved).

## Remote Script 1.9.0

### Added

New MCP tools and matching Remote Script commands. Each takes `location`: `session` (clip slot index) or `arrangement` (index as listed by `get_arrangement_clips`).

- **Warp:** `get_clip_warp`, `set_clip_warp` (warping, warp mode, pitch, gain), `edit_warp_markers` (Live 11+). `set_clip_warp(original_bpm=…)` conforms a loop to the song tempo: it turns warping on, keeps the first warp marker and pins the last whole beat of the file to its time at that tempo.
- **Clip automation:** `set_clip_automation` writes a clip envelope for a device parameter or a mixer control (volume, panning, sends), from points with linear ramps or held steps; an empty point list clears it. `get_clip_automation` samples an envelope back. Session clips only: Live 12 refuses clip automation on Arrangement clips from a script, and Arrangement automation lanes aren't reachable from its API.

### Internal

- `_resolve_clip()` resolves Session and Arrangement clips for the new commands.
- New tests in `tests/test_warp_automation.py` (fake Clip / AutomationEnvelope).

## Remote Script 1.8.2

### Fixed

- **Error messages:** refusals from Live (out-of-range index, master track can't be muted…) are no longer prefixed with `Communication error with Ableton:`, which suggested a connection problem. The server also keeps the socket open after such a refusal instead of dropping it and reconnecting. Real transport failures (timeout, lost connection, invalid response) are reported as before.
- **Master track name:** `get_session_info` reported the master as `"Master"` (hardcoded) while the mixer tools reported Live's actual name (`"Main"` in Live 12). It now reads the name from Live.

## Remote Script 1.8.1

### Fixed

Live applies some changes asynchronously: reading the state back right after a write returns the old value. Three commands were affected.

- **`set_arrangement_time`** reported the previous playhead position (e.g. asked for beat 16, replied "0.0"). It now replies once Live reports the playhead at the requested beat.
- **`create_locator`** failed with "Failed to create cue" unless the playhead was already at the target beat, because the cue was toggled at the old playhead position. It now waits for the playhead to arrive, creates the cue, waits for it to appear, names it, and restores the playhead. It now refuses to run while the transport is playing instead of misplacing the cue.
- **`load_instrument_or_effect`** replied "Devices on track:" with an empty list: the device chain was read before Live inserted the device, and the `new_devices` / `devices_after` fields the server expects were never sent. The reply now lists the new device(s). Loading the same device that is already on the track is detected as an in-place reload (Live keeps the device and resets its parameters).

When Live hasn't applied the change within the wait budget (1 s for the playhead, 5 s for a device load, 2 s for an in-place reload), the reply says so instead of reporting stale state.

### Internal

- Commands can now complete over several Live ticks (`_Deferred` + `_poll_until` in the Remote Script).
- New regression tests (`tests/test_async_live_state.py`) simulate Live applying writes one tick later.

## Remote Script 1.8.0

### Added

New MCP tools and matching Remote Script commands:

- **Mixer:** `set_track_volume`, `set_track_panning`, `set_track_send`, `set_track_mute`, `set_track_solo`, `set_track_arm`, on regular tracks, and (where it applies) return tracks and the master via `track_type`.
- **Tracks:** `duplicate_track`, `delete_track`.
- **Scenes:** `get_scenes`, `create_scene`, `set_scene_name`, `duplicate_scene`, `fire_scene`, `delete_scene`.
- **Arrangement:** `delete_arrangement_clip` (Live 11+).

See the [tool reference](README.md#tools-added-by-this-fork) for parameters.
