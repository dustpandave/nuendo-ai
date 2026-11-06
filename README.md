# nuendo-claude

Let Claude work inside **Nuendo 13** on macOS: run edits, mix, select tracks, move the cursor, write MIDI ideas, and drop audio from **Suno** or **Soundly** straight onto the timeline.

```
Claude ──MCP──▶ nuendo-mcp (this repo, runs on your Mac)
                   │  IAC bus "Claude to Nuendo"   ──▶  Claude Bridge (MIDI Remote script in Nuendo)
                   │  IAC bus "Claude from Nuendo" ◀──  track names, levels, transport, position
                   └─ macOS UI automation ──▶ menus, import dialog, typing positions
Suno MCP / Soundly MCP ──▶ audio file or URL ──▶ nuendo_import_audio
```

## What it can and can't do

| Works | Notes |
|---|---|
| Transport, cycle, click, locate to bar/timecode | locate types into Nuendo's position field |
| ~140 key commands (split, duplicate, normalize, quantize, add track, bounce…) | `nuendo_command`; easy to add more |
| Any menu item | `nuendo_menu` / `nuendo_list_menu` |
| Select tracks by name, set volume (in dB), pan, mute, solo, arm, sends, quick controls | first 32 mixer channels, pageable |
| Import audio (local file or URL) on a chosen track at a chosen position | via the Import dialog |
| Place a whole cue sheet of sounds (e.g. Soundly results) at specific times | `nuendo_place_sounds` |
| Generate MIDI: chord progressions, melodies/basslines, drum grids, then import | |
| Read: track names, levels, mute/solo, selection, transport, cursor position | |
| ❌ Read events/clips/plugins inside the project | Nuendo has no API for this. Tell Claude, or export (MIDI / track list) |

## Setup (about 10 minutes)

### 1. IAC MIDI buses
1. Open **Audio MIDI Setup** → *Window* → **Show MIDI Studio** → double-click **IAC Driver**.
2. Tick **Device is online**.
3. Add two ports (`+`) named exactly **`Claude to Nuendo`** and **`Claude from Nuendo`**.

### 2. Install
```bash
git clone https://github.com/dustpandave/nuendo-ai.git ~/nuendo-ai
```
```bash
cd ~/nuendo-ai && ./scripts/install.sh
```
This installs the Python environment (via `uv`) and copies the bridge script to
`~/Documents/Steinberg/Nuendo/MIDI Remote/Driver Scripts/Local/Claude/Nuendo Bridge/`.

### 3. Nuendo
1. **Studio → MIDI Remote Manager → Scripts → Reload Scripts**. "Claude – Nuendo Bridge" should appear and detect the IAC ports automatically.
   If it doesn't: in the lower-zone *MIDI Remote* tab click **+**, choose vendor *Claude*, model *Nuendo Bridge*, input `Claude to Nuendo`, output `Claude from Nuendo`.
2. **Studio → Studio Setup → MIDI Port Setup**: untick **In 'All MIDI Inputs'** for both Claude ports, so control messages never record onto your MIDI tracks.
3. Optional but recommended: in *Preferences → Editing → Audio*, set **On Import Audio Files** to the behaviour you want (copy to project folder, etc.) so the Import Options dialog doesn't need answering. Then set `NUENDO_IMPORT_OPTIONS_DIALOG=0` in the MCP config below.

### 4. macOS permissions
**System Settings → Privacy & Security → Accessibility**: enable **Claude** (and/or **Terminal** if you use Claude Code). This is needed for menus, the import dialog and typing positions.

### 5. Connect Claude
**Claude Desktop**: *Settings → Developer → Edit Config* and add:
```json
{
  "mcpServers": {
    "nuendo": {
      "command": "/Users/YOU/nuendo-ai/.venv/bin/nuendo-mcp",
      "env": { "NUENDO_IMPORT_OPTIONS_DIALOG": "1" }
    }
  }
}
```
**Claude Code**:
```bash
claude mcp add nuendo -- ~/nuendo-ai/.venv/bin/nuendo-mcp
```
### Soundly (recommended)
[soundly-mcp](https://github.com/1800doublegee/soundly-mcp) lets Claude search your **local** Soundly library. Install it with the MCP library pinned to v1 (it doesn't work with v2 yet):
```bash
git clone https://github.com/1800doublegee/soundly-mcp.git ~/soundly-mcp
```
```bash
cd ~/soundly-mcp && uv tool install . --with "mcp<2"
```
Then add it next to `nuendo` in the config: `"soundly": { "command": "/Users/YOU/.local/bin/soundly-mcp" }`.
Ask things like *"Design a heavy metal door slam at 00:01:12:00 on SFX 1–3"*. Claude searches Soundly, shows a cue sheet, and places the layers with `nuendo_place_sounds`.

Keep your Suno MCP server configured alongside it too. Claude chains them: generate or search, get a file or URL, then `nuendo_import_audio`.

Restart Claude and ask: *"What's in my Nuendo session?"*

## First test
1. *"Check the Nuendo connection"* → should list your track names.
2. *"Select the Bass track and set it to -8 dB"*
3. *"Go to bar 9 and write a 4-bar Am–F–C–G progression at 96 BPM"*
4. *"Find a vinyl crackle in Soundly and put it on the FX track at bar 1"*

## Tuning
| Env var | Default | |
|---|---|---|
| `NUENDO_UI_DELAY` | `0.6` | seconds between dialog steps; raise if imports misfire |
| `NUENDO_IMPORT_OPTIONS_DIALOG` | `1` | `0` if you disabled the Import Options dialog |
| `NUENDO_CLAUDE_DIR` | `~/Music/Nuendo Claude` | where downloads and generated MIDI go |
| `NUENDO_PROCESS` | auto | process name if auto-detect fails (e.g. `Nuendo 13`) |

### Adding key commands
Edit `nuendo_mcp/commands.json` (category and name exactly as in *Edit → Key Commands*), append to the `custom` group, then re-run `./scripts/install.sh` and reload scripts in Nuendo. Names that don't exist in your Nuendo do nothing. If one of the built-ins doesn't fire, check its exact spelling in the Key Commands dialog and correct it.

### MIDI import position
Nuendo places imported MIDI files according to its MIDI File preferences. If ideas land at the project start instead of the cursor, check *Preferences → MIDI → MIDI File* for an import-at-locator/cursor option. `nuendo_create_midi` sets both the left locator and the cursor to the requested position, so either setting works.

## Troubleshooting
- **"IAC buses not found"**: check the exact bus names and that *Device is online* is ticked.
- **Status shows no tracks**: the script isn't active. Look in the *MIDI Remote* tab; the script console (MIDI Remote Manager → Scripts → *Script Console*) shows errors.
- **Menus / import do nothing**: Accessibility permission is missing, or `NUENDO_UI_DELAY` needs to be higher.
- **Track not found**: only the current 32-channel mixer bank is visible; ask Claude to page with `nuendo_bank`.

## Development
```bash
uv run pytest
```
The MIDI Remote script is generated from `nuendo_script/template.js` + `nuendo_mcp/protocol.py`, so the MIDI mapping is defined in one place. Tests run the generated script against a mock of the MIDI Remote API (`tests/mock_host.js`).
