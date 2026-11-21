# Ableton Studio MCP — Privacy & data

_Last updated: 21 November 2026_

**In short: Ableton Studio MCP sends nothing anywhere.** Your music, your prompts and your Live set stay on your machine.

## What talks to what

- The MCP server talks to Ableton Live through the Remote Script on **127.0.0.1:9877** (your own computer). The socket listens on localhost only; `ABLETON_MCP_HOST` changes that, deliberately, for setups where Live runs on another machine.
- The server makes **no internet connection** of its own. (Your MCP client and `uv` download the package from GitHub when you install or update it.)

## No telemetry, no data collection

The original [ableton-mcp](https://github.com/ahujasid/ableton-mcp) can send anonymous usage telemetry and, with consent, record sessions for a research dataset. **Ableton Studio MCP has removed that code entirely** (since 1.17.0): no telemetry module, no dataset recorder, no consent question, no Supabase dependency, and the Remote Script no longer watches your edits in Live. Tools no longer take a `user_prompt` argument, so your requests are never passed to the server.

The original project's data terms apply only to the original `ableton-mcp` package, not to Ableton Studio MCP.

## Files Ableton Studio MCP may create on your machine

| File | Why |
|---|---|
| `<your Live project>/Samples/Recorded/…` | Takes recorded with `record_arrangement`, like any recording made in Live. Listening takes (`Claude – écoute …`) are deleted right after analysis unless you ask to keep them. |
| `<User Library>/Ableton Studio MCP/Sounds/<Device>/<Name>.json` | Sounds saved with `save_sound`: the device and its parameter values. Yours to keep, edit or delete. |
| `<system temp folder>/ableton-mcp/*_spectrogram.png` | Spectrogram images of analysed takes; only the 20 most recent are kept. |
| `<User Library>/Remote Scripts/AbletonStudioMCP/` | The Live control surface, installed by `ableton-studio-mcp install`. (Versions before 2.0 used an `AbletonMCP` folder; `ableton-studio-mcp install --remove-legacy` deletes it.) |

## Your music

Everything the tools create or change lives in your Live set and your files, and remains yours. Some tools are destructive (`delete_track`, `delete_scene`, `delete_clip`, `delete_arrangement_clip`): save your set before large experiments.

## Contact

Questions or concerns: [open an issue](https://github.com/cedrati/ableton-studio-mcp/issues) on GitHub.

## Leftovers from older versions

Versions before 1.17.0 could leave `~/Library/Application Support/AbletonMCP/customer_uuid.txt` (macOS; `%APPDATA%` on Windows, `~/.local/share` on Linux) and `~/.ableton-mcp/consent.json`. Nothing reads them any more; you can delete them.
