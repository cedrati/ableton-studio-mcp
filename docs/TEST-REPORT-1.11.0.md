# Test report: Remote Script 1.11.0 (fork `cedrati/ableton-mcp`)

- **Date:** 2026-11-19
- **Branch tested:** `feat/clip-loop` @ `191fae5`, then `feat/mixer-scenes` @ `5313403` after merging (§4)
- **Environment:** Ableton Live 12.4.5 Suite, 120 BPM, 4 tracks + 2 returns
- **Method:** real calls through the MCP server. A 16-beat MIDI clip, the Splice loop `TSP_SDG_131_bass_synth_status_Amin.wav` (7.328 s), and an Arrangement copy of the MIDI clip. Test tracks deleted at the end (set back to 4 tracks).

## 1. Installation and version

| Check | Result |
|---|---|
| `get_remote_script_info`: 1.11.0 on both sides, `get_clip_loop` / `set_clip_loop` listed | ✅ |
| Unit tests | ✅ 121 passed (after the fix) |

## 2. Results

| Test | Result |
|---|---|
| `get_clip_loop` on a new 16-beat clip | ✅ looping, brace 0–16, markers 0–16, units beats |
| `loop_start=0, loop_length=4` | ✅ brace 0–4 |
| Move the brace forward past its end: 0–4 → 8–12 | ✅ |
| Move it back: 8–12 → 4–8 | ✅ |
| Looping on, `start_marker` 6 (inside the brace), then 1 (before it) | ✅ both applied |
| `looping=false, start_marker=2, end_marker=6` | ❌ **finding 1**: end_marker applied, start_marker silently ignored (reported in `adjusted`) |
| Unlooped, `loop_start=2, loop_end=6` | ✅ plays 2–6: `start_marker` follows `loop_start`, `length` 4 |
| Unwarped audio (Live switched looping off with warping) | ✅ units seconds, end 7.328 s; brace 2 s–4 s applied |
| Warping back on | ⚠️ **finding 2**: values back in beats (2 s → 4.367 beats at the loop's 131 BPM), warp markers reset |
| Arrangement copy: `loop_start=4, loop_length=4` | ✅ brace 4–8, the clip still spans 0–16 in the song |
| `loop_start=8, loop_end=4` | ✅ refused before any write |
| `loop_end=500` on a MIDI clip | ✅ accepted (MIDI clips can be extended) |

## 3. Findings

1. **Unlooped clips play `loop_start` → `loop_end`.** With looping off, Live ignores a `start_marker` write without an error, mirrors `start_marker` from `loop_start`, and accepts an `end_marker` that changes nothing (the length stays `loop_end - loop_start`). Fix: when the clip is (or is being made) unlooped, start/end markers are written to `loop_start` / `loop_end` and the reply says so; giving markers and loop values together for such a clip is refused. `get_clip_loop` / `set_clip_loop` now return a `playback` summary: `{"starts_at", "repeats"}` when looping, `{"plays_once"}` when not.
2. **Turning warping off then on resets the warp markers** of an audio clip (Live behavior). Documented in the `set_clip_loop` description.

## 4. Re-run after merging (`5313403`)

Live loaded the script at 13:48:59, after its install at 13:45:26. Set restored afterwards (4 tracks, 120 BPM).

| Test | Result |
|---|---|
| `original_bpm=140` on the 140 BPM drum loop (6.856 s) in a 142 BPM set | ✅ end marker at beat **16** (was 15), pinned to the end of the file; reply: "The file ends 1.1 ms before beat 16" |
| Same reply | ✅ no "shadow marker can't be deleted" note any more |
| `looping=false, start_marker=2, end_marker=6` | ✅ plays 2–6 once (`playback.plays_once`), note explains the brace was written, no `adjusted` |
| Unlooped, `start_marker` + `loop_end` together | ✅ refused with the explanation |
| `looping=true`, brace 4–8, `start_marker=0` | ✅ `playback`: starts at 0, repeats 4–8 |

Every fix found while testing 1.9.0–1.11.0 has now been confirmed in Live, except the arrangement-automation question (§3 of the 1.9.0 report).
