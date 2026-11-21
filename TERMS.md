# Ableton Studio MCP — Privacy & data

_Last updated: 21 November 2026_

**In short: Ableton Studio MCP sends nothing anywhere.** Your music, your prompts and your Live set stay on your machine.

## What talks to what

- The MCP server talks to Ableton Live through the Remote Script on **127.0.0.1:9877** (your own computer). The socket listens on localhost only; `ABLETON_MCP_HOST` changes that, deliberately, for setups where Live runs on another machine.
- The server makes **no internet connection** of its own. (Your MCP client and `uv` download the package from GitHub when you install or update it.)

## Telemetry and dataset recording inherited from the original project

The original [ableton-mcp](https://github.com/ahujasid/ableton-mcp) can send anonymous usage telemetry and, with explicit consent, record sessions for a research dataset, to its maintainer's Supabase project. That code is still present in this repository but **inactive**:

- it only sends anything when `MCP_Server/config.py` holds Supabase credentials, and that file is **not part of this repository** (it is git-ignored and excluded from the package);
- without those credentials, **the consent question is never asked**, since nothing could be collected;
- `ABLETON_MCP_DISABLE_TELEMETRY=true` keeps everything off even if credentials were added.

If you build your own distribution and add credentials, you become responsible for the data you collect and for telling your users.

The original project's data terms apply only to the original `ableton-mcp` package, not to Ableton Studio MCP.

## Files Ableton Studio MCP may create on your machine

| File | Why |
|---|---|
| `~/Library/Application Support/AbletonMCP/customer_uuid.txt` (macOS; `%APPDATA%` on Windows, `~/.local/share` on Linux) | A random ID created by the inherited telemetry code. Never sent. You can delete it. |
| `~/.ableton-mcp/consent.json` | Only if a consent answer was ever recorded. |
| `<your Live project>/Samples/Recorded/…` | Takes recorded with `record_arrangement`, like any recording made in Live. Listening takes (`Claude – écoute …`) are deleted right after analysis unless you ask to keep them. |
| `<system temp folder>/ableton-mcp/*_spectrogram.png` | Spectrogram images of analysed takes; only the 20 most recent are kept. |
| `<User Library>/Remote Scripts/AbletonMCP/` | The Remote Script, installed by `ableton-studio-mcp-install-script` (the previous version is kept as `__init__.py.bak`). |

## Your music

Everything the tools create or change lives in your Live set and your files, and remains yours. Some tools are destructive (`delete_track`, `delete_scene`, `delete_clip`, `delete_arrangement_clip`): save your set before large experiments.

## Contact

Questions or concerns: [open an issue](https://github.com/cedrati/ableton-studio-mcp/issues) on GitHub.
