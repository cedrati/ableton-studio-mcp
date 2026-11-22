# Test report: Remote Script 1.9.0 (fork `cedrati/ableton-mcp`)

- **Date:** 2026-11-19
- **Branch tested:** `feat/warp-automation` @ `45b89df` (first pass), then `014a8e7` (second pass, §5)
- **Environment:** Ableton Live 12.4.5 Suite, 120 BPM, 4 tracks + 2 returns (A-Reverb, …)
- **Method:** real calls through the MCP server, running from the local clone. Test material: an audio track with `TSP_SDG_131_bass_synth_status_Amin.wav` (Splice, 131 BPM, 7.328 s) in slots 0 and 1, a MIDI track `Wavetable Test` with Wavetable and a 16-beat clip, and copies of both clips in the Arrangement at beat 0.

## 1. Installation and version

| Check | Result |
|---|---|
| `get_remote_script_info`: `script_version` = `expected_version` = 1.9.0, 5 new capabilities listed | ✅ |
| First call after Live's restart | ⚠️ "Could not connect to Ableton" once, OK on retry (Live was still starting) |
| Unit tests | ✅ 94 passed (after all fixes) |

## 2. Warp

| Tool | Test | Result |
|---|---|---|
| `get_clip_warp` | freshly imported Splice loop | ✅ Live had auto-warped it correctly: markers 0 → 0 s, 16 → 7.328 s (= 131 BPM), plus a hidden marker at 16.03125 |
| `set_clip_warp` | `complex_pro`, pitch −2 st +15 ct, gain 0.5 | ✅ read back, gain `4.00 dB` |
| `set_clip_warp` | `warp_mode="rex"` on a WAV | ✅ refused: not available (lists the 6 available modes) |
| `set_clip_warp` | `warping=false`, then `true` | ✅ |
| `set_clip_warp` | `original_bpm=131` | ❌ **bug 1**, see §4 |
| `edit_warp_markers` | move the marker at 16 by −0.5, then back by +0.5 | ✅ hidden marker follows (15.53125, then 16.03125) |
| `edit_warp_markers` (`add`) | n/a | not run: same cause as bug 1, fixed |
| `get_clip_warp` (`location="arrangement"`) | copy of the loop in the Arrangement | ✅ warp settings and markers carried over |
| `set_clip_warp` | on a MIDI clip | ✅ refused: "Warp settings only apply to audio clips" |
| `get_clip_warp` | empty slot 7 | ✅ "No clip in slot 7 of track 4" |

## 3. Clip automation

| Tool | Test | Result |
|---|---|---|
| `set_clip_automation` | Wavetable `Flt 1 Freq`, linear 0.2 → 0.9 over beats 0–12, held to 16 | ✅ 49 steps written |
| `get_clip_automation` | read at 1/16 resolution | ✅ ramp 0.2 → 0.9 in 0.0146 steps, 0.9 held to the end. ⚠️ **bug 2** at boundaries, see §4 |
| `set_clip_automation` (mixer, `step`) | audio clip volume: 0.85, 0.5 at beat 8, 1.4 at beat 12 | ✅ 1.4 clamped to 1.0 and reported |
| `set_clip_automation` (`send:0`) | 0 → 0.6 over 16 beats, resolution 1 | ✅ `A-Reverb`, 16 steps |
| `get_clip_automation` | panning, not automated | ✅ `has_envelope: false` |
| `set_clip_automation` (`location="arrangement"`) | MIDI clip copied to the Arrangement | ❌ Live: "Not a session clip or parameter belongs to another track." **Limit 3**, see §4 |
| `get_clip_automation` (`location="arrangement"`) | Arrangement copies of the automated clips | ✅ reads, `has_envelope: false`: `duplicate_to_arrangement` doesn't copy the clip envelope into the clip |
| `set_clip_automation` | parameter index 500 | ✅ "Parameter index out of range (93 parameters)" |
| `set_clip_automation` | `send:9` | ✅ "Send index out of range (2 sends)" |

## 4. Problems found and fixed

1. **`add_warp_marker` refuses a dict.** Live's Python API raised `No registered converter was able to produce a C++ rvalue of type NApiHelpers::TWarpMarker from this Python object of type dict` (Max for Live accepts a dict; Python doesn't). Worse, the other markers had already been removed, so the clip was left with only its first marker. Fixes:
   - markers are built as `Live.Clip.WarpMarker` objects. The constructor's argument names aren't documented, so keywords are tried, then both positional orders, and the object's own `beat_time` / `sample_time` are checked so the two can't be swapped;
   - every marker is built, and every check done, before the clip is touched;
   - if Live refuses the new end marker, the removed markers are put back and the error says how many.
2. **`get_clip_automation` read the previous step on boundaries.** Live's `value_at_time()` is left-continuous: at beat 0 it returned the parameter's value before automation (1.0 instead of 0.2), and at beat 12 the step before 0.9. Samples are now read 0.0001 beat after each time.
3. **No clip automation on Arrangement clips.** It's a limit of Live's API, not a bug. `set_clip_automation` now refuses `location="arrangement"` up front with an explanation, and the tool description, README and CHANGELOG say Session clips only.

## 5. Second pass in Live (`014a8e7`)

The set was restored by Live's restart; the test tracks were recreated, then deleted at the end (set back to 4 tracks).

| Tool | Test | Result |
|---|---|---|
| `set_clip_warp(original_bpm=131)` | freshly imported loop | ✅ markers 0 → 0 s, 16 → 7.32824 s (131 BPM exactly) |
| `set_clip_warp(original_bpm=131)` | after moving the end marker to beat 15 (mis-warped clip) | ✅ back to 16 → 7.32824 s |
| `set_clip_warp(original_bpm=131, warp_mode="complex")` | clip with a middle marker at 8 | ✅ middle marker removed, mode Complex |
| `edit_warp_markers` (`add` with `sample_time`) | beat 8 = 3.6641 s | ✅ |
| `edit_warp_markers` (`add` without `sample_time`) | beat 4 | ❌ **finding 4**, clip left untouched ✅ |
| `get_clip_automation` | linear 0.2 → 0.9 over 0–12 | ✅ exact: 0.2 at beat 0, 0.3167 at 2 … 0.9 at 12, held to 16 |
| `set_clip_automation(location="arrangement")` | n/a | ✅ refused up front with the explanation |

### Findings and fixes (not re-run in Live; covered by unit tests)

4. **`Live.Clip.WarpMarker` signature** (from Live's error message): `__init__(double sample_time, double beat_time)`, **both required**. A marker can't be created from a beat alone, so `edit_warp_markers` now requires `sample_time` and refuses before touching the clip. The constructor is called with these keyword names, and the object's times are still checked.
5. **Shadow marker.** Live keeps a marker 1/32 beat after the last one ("The shadow marker can't be deleted"). Conforming no longer tries to remove it, so its reply no longer carries that note.

## 6. Still open

- [ ] Whether `duplicate_to_arrangement` turns a Session clip envelope into Arrangement track automation: the API can't tell (`automation_state` is 1 either way). To check by eye in the Arrangement's automation lane.
- [ ] Re-run §5 rows 1 and 4 after installing the final script (only the keyword call and the shadow-marker skip changed).
