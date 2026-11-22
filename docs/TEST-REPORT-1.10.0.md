# Test report: Remote Script 1.10.0 (fork `cedrati/ableton-mcp`)

- **Date:** 2026-11-19
- **Branch tested:** `feat/arrangement-notes` @ `84743b8`
- **Environment:** Ableton Live 12.4.5 Suite, 120 BPM, 4 tracks + 2 returns
- **Method:** real calls through the MCP server running from the local clone. A MIDI track `TEST Arrangement Notes` (Wavetable) with an 8-beat Session clip (A3 C4 E4 G4 A4 G4 E4 C4), copied into the Arrangement at beats 0, 16 and 32.

## 1. Installation and version

| Check | Result |
|---|---|
| `get_remote_script_info`: `script_version` = `expected_version` = 1.10.0, `arrangement_notes` and `remove_notes` listed | ✅ |
| Unit tests | ✅ 109 passed |

## 2. Notes in Arrangement clips

| Tool | Test | Result |
|---|---|---|
| `get_clip_notes(location="arrangement")` | copy at beat 16 | ✅ 8 notes; `arrangement_start` 16, `arrangement_end` 24, `start_marker` 0, `looping` true. Live returns notes sorted by pitch, not time |
| `remove_notes` (time range) | copy at 16, beats 4–8 | ✅ 4 removed, 4 kept |
| `add_notes_to_clip(location="arrangement")` | 4 new notes in beats 4–8 of that copy | ✅ read back: bar 1 unchanged, bar 2 = C5 B4 G4 A4 |
| Isolation | read the copy at 0 and the Session clip | ✅ both still hold the 8 original notes |
| `remove_notes` (one pitch) | copy at 0, pitch 67 only | ✅ 2 removed, 6 kept |
| `clear_notes_from_clip(location="arrangement")` | copy at 32 | ✅ 8 cleared; the clip stays in place (0–8, 16–24, 32–40) |
| `get_clip_notes(location="arrangement")` | clip index 7 | ✅ "Arrangement clip index out of range (3 clips)" |

## 3. Notes

- Claude Code kept the 1.9.0 tool schemas for `get_clip_notes` and `add_notes_to_clip` (no `location` field) after the restart; the server accepted `location` anyway. Clients that validate strictly against a cached schema need their tool list refreshed.
- Not run in Live: the refusal of `location="arrangement"` by an older Remote Script (covered by unit tests: it would otherwise edit the Session clip in the same slot).
