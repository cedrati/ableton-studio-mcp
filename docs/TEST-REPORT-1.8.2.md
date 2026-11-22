# Test report: Remote Script 1.8.2 (fork `cedrati/ableton-mcp`)

- **Date:** 2026-11-19
- **Branch tested:** `feat/mixer-scenes` @ `8d77407`
- **Environment:** Ableton Live 12 (master named "Main"), set with 4 tracks, 2 return tracks (A-Reverb, …), 8 scenes
- **Method:** real calls through the MCP server on a `MCP-TEST` track and a `MCP-TEST-SCENE` scene created for the test, then deleted. The user's set was restored to its initial state (4 tracks, 8 scenes, playhead at 0, master at 0 dB).

## 1. Installation and version

| Check | Result |
|---|---|
| `get_remote_script_info`: `script_version` = `expected_version` = 1.8.2, `up_to_date: true` | ✅ |
| Script installed in `~/Music/Ableton/User Library/Remote Scripts/AbletonMCP/` identical to `AbletonMCP_Remote_Script/__init__.py` | ✅ |
| Bundled copy `MCP_Server/bundled_ableton_remote_script/AbletonMCP_init.py` identical | ✅ |
| Unit tests (`uv run --with pytest pytest`) | ✅ 65 passed |

## 2. New tools (1.8.0)

### Mixer

| Tool | Test | Result |
|---|---|---|
| `set_track_volume` | test track → 0.6 | ✅ `-10.0 dB`, read back with `get_track_info` |
| `set_track_volume` (`track_type="master"`) | master → 0.85 | ✅ `0.0 dB`, name `Main` |
| `set_track_panning` | → -0.5 | ✅ `25L` |
| `set_track_send` | send 0 → 0.4 | ✅ `A-Reverb`, `-24.0 dB` |
| `set_track_mute` | test track on | ✅ |
| `set_track_mute` (`track_type="return"`) | return 0 on, then off | ✅ (`A-Reverb`) |
| `set_track_solo` | on, then off | ✅ |
| `set_track_arm` | on, then off | ✅ |

### Tracks

| Tool | Test | Result |
|---|---|---|
| `duplicate_track` | duplicate the test track (clips + Operator) | ✅ copy at index 5 with mixer settings, 2 clips and the device |
| `delete_track` | delete both test tracks | ✅ `track_count` back to 4 |

### Scenes

| Tool | Test | Result |
|---|---|---|
| `get_scenes` | list | ✅ |
| `create_scene` (`index=-1`) | append | ✅ index 8 |
| `set_scene_name` | `MCP-TEST-SCENE` | ✅ |
| `duplicate_scene` | duplicate scene 8 | ✅ index 9, clip duplicated into slot 9 |
| `fire_scene` | launch scene 9 | ✅ transport started (`is_playing: true`) |
| `delete_scene` | delete 9, then 8 | ✅ `scene_count` back to 8 |

### Arrangement

| Tool | Test | Result |
|---|---|---|
| `delete_arrangement_clip` | 2 clips placed at beats 0 and 8 → delete index 0 | ✅ the clip at beat 8 remains |

## 3. Async fixes (1.8.1)

| Fix | Test | Result |
|---|---|---|
| `set_arrangement_time` reports the new position | → 16 | ✅ "Playhead moved to beat 16.0" (previously reported 0.0) |
| `load_instrument_or_effect` lists the new devices | Operator on an empty track | ✅ "New devices: Operator" |
| Reloading the same device is detected | load Operator a second time | ✅ "reloads an identical device in place" message |
| `create_locator` | **not tested** | ⚠️ see §5 |

## 4. Fixes in 1.8.2

| Fix | Test | Result |
|---|---|---|
| Live refusals without the "Communication error" prefix | mute the master | ✅ `Error setting track mute: The master track cannot be muted` |
| | volume on track 99 | ✅ `Track index out of range` |
| | `fire_scene(42)` | ✅ `Scene index out of range (10 scenes)` |
| | `delete_arrangement_clip` index 5 | ✅ `Arrangement clip index out of range (1 clips)` |
| Connection kept after a refusal | immediate next call | ✅ no reconnection needed |
| Real master name in `get_session_info` | | ✅ `"Main"` |

## 5. Points to watch

- **`create_locator` not tested live:** no tool can delete a locator, so the test would have left a cue point in the set. Covered only by `tests/test_async_live_state.py`. Idea: add a `delete_locator` tool.
- **Undeclared capabilities:** `get_remote_script_info` does not list some commands that do work (`set_track_name`, `set_arrangement_time`, `stop_playback`, `get_browser_items_at_path`, `fire_clip`, `set_tempo`…). The `capabilities` list is incomplete.
- **Device type:** `get_track_info` returns `"type": "unknown"` for Operator (expected `instrument`). Minor, predates the fork.
- **Package version:** `pyproject.toml` is still at `1.4.5`, while the script went from 1.8.0 to 1.8.2.

## 6. GitHub state at test time (`cedrati/ableton-mcp`)

| Branch | Local | GitHub | State |
|---|---|---|---|
| `feat/mixer-scenes` | `8d77407` | `8d77407` | ✅ up to date, clean working tree |
| `main` (default branch) | `6f7b801` | `6f7b801` | ⚠️ did not contain `8d77407` (1.8.2), since fast-forwarded |
| `fix/async-live-state` | `eaf52de` | missing | local only, already included in `feat/mixer-scenes` |

No pull request was open, neither on the fork nor towards `ahujasid/ableton-mcp`.
