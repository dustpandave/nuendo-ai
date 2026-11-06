"""nuendo-claude MCP server: lets Claude drive Nuendo 13 on macOS."""
from __future__ import annotations

import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Literal

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP

from . import mac
from . import protocol as P
from .bridge import Bridge
from .midi_gen import build_midi

WORK_DIR = Path(os.environ.get("NUENDO_CLAUDE_DIR", "~/Music/Nuendo Claude")).expanduser()
IMPORT_OPTIONS_DIALOG = os.environ.get("NUENDO_IMPORT_OPTIONS_DIALOG", "1") != "0"

mcp = FastMCP(
    "nuendo",
    instructions=(
        "Controls Steinberg Nuendo 13 through a MIDI Remote bridge script plus macOS UI "
        "automation. Call nuendo_status first to see tracks, selection and position. "
        "Tracks are addressed by name or mixer-bank slot (first 32 mixer channels; page "
        "with nuendo_bank). Placing audio/MIDI = select track, locate, import. "
        "Nothing here can read clip/event contents of the project; ask the user or use "
        "exports when you need that."
    ),
)
bridge = Bridge()


def _ok(**kw) -> dict:
    return {"ok": True, **kw}


def _wait_events(seconds: float = 0.25) -> None:
    time.sleep(seconds)


# ------------------------------------------------------------------ status
@mcp.tool()
def nuendo_status() -> dict:
    """Connection state, transport, cursor position, selected track and the
    names/levels of the channels in the current mixer bank (up to 32)."""
    try:
        bridge.connect()
    except Exception as e:  # noqa: BLE001
        return {"connected": False, "error": str(e)}
    snap = bridge.state.snapshot()
    if not snap["connected"] and not snap["mixerBank"]:
        snap["hint"] = ("No data from Nuendo yet. Check Studio > MIDI Remote shows "
                        "'Claude Nuendo Bridge' as active, and that its ports are the IAC buses.")
    return snap


# --------------------------------------------------------------- transport
TransportAction = Literal["play", "stop", "record", "cycle_on", "cycle_off",
                          "metronome_on", "metronome_off", "rewind", "forward", "return_to_zero"]


@mcp.tool()
def nuendo_transport(action: TransportAction) -> dict:
    """Start/stop/record, toggle cycle or click, rewind/forward, return to zero."""
    m = {
        "play": ("mStart", True), "stop": ("mStop", True), "record": ("mRecord", True),
        "cycle_on": ("mCycleActive", True), "cycle_off": ("mCycleActive", False),
        "metronome_on": ("mMetronomeActive", True), "metronome_off": ("mMetronomeActive", False),
    }
    if action in m:
        param, on = m[action]
        bridge.transport(param, on)
        if param in ("mStop", "mStart", "mRecord"):
            time.sleep(0.05)
            bridge.transport(param, False)  # release the "button"
    elif action in ("rewind", "forward"):
        param = "mRewind" if action == "rewind" else "mForward"
        bridge.transport(param, True)
        time.sleep(0.4)
        bridge.transport(param, False)
    else:
        bridge.run_command("Transport/Return to Zero")
    _wait_events()
    return _ok(transport=bridge.state.snapshot()["transport"], position=bridge.state.position)


@mcp.tool()
def nuendo_locate(position: str) -> dict:
    """Move the project cursor. `position` is typed into Nuendo's primary time
    display, so use its format: bars+beats like "17.1.1.0" (or just "17" for bar 17),
    or timecode "00:01:30:00" if the display is set to timecode."""
    pos = position.strip()
    if re.fullmatch(r"\d+", pos):
        pos = f"{pos}.1.1.0"
    bridge.run_command("Transport/Input Position")
    time.sleep(0.3)
    mac.focus()
    mac.type_into_focused_field(pos)
    _wait_events(0.3)
    return _ok(requested=pos, positionNow=bridge.state.position or "(no read-out)")


# ---------------------------------------------------------------- commands
@mcp.tool()
def nuendo_list_commands(filter: str = "") -> list[str]:
    """Key commands Claude can trigger, as 'Category/Name'. Optional substring filter."""
    f = filter.lower()
    return [f"{c['cat']}/{c['name']}" for c in bridge.commands
            if f in f"{c['cat']}/{c['name']}".lower()]


@mcp.tool()
def nuendo_command(command: str, repeat: int = 1) -> dict:
    """Trigger a Nuendo key command, e.g. "Edit/Split at Cursor", "Process/Normalize",
    "Add Track/Audio", "Edit/Undo". Acts on the current selection like pressing the
    shortcut would. Use nuendo_list_commands to discover names; for anything not in
    the list use nuendo_menu."""
    done = None
    for _ in range(max(1, min(repeat, 64))):
        done = bridge.run_command(command)
        time.sleep(0.08)
    return _ok(ran=f"{done['cat']}/{done['name']}", times=repeat)


@mcp.tool()
def nuendo_menu(path: list[str]) -> dict:
    """Click a Nuendo menu item by path, e.g. ["Audio", "Process", "Normalize..."] or
    ["Project", "Add Track", "Audio..."]. Names must match the menu exactly (including
    '...'); use nuendo_list_menu to look."""
    mac.click_menu(path)
    return _ok(clicked=" > ".join(path))


@mcp.tool()
def nuendo_list_menu(path: list[str] | None = None) -> list[str]:
    """List the items in a Nuendo menu. [] = the menu bar; ["Audio"] = the Audio menu;
    ["Audio", "Process"] = that submenu."""
    return mac.list_menu(path or [])


@mcp.tool()
def nuendo_keys(key: str, modifiers: list[Literal["command", "shift", "option", "control"]] | None = None,
                text: str | None = None) -> dict:
    """Send a keystroke to Nuendo (brings it to the front). `key` is a character or
    one of return/enter/escape/tab/delete/left/right/up/down/space. If `text` is given
    it is typed first (handy for dialogs Nuendo opens). Prefer nuendo_command."""
    mac.focus()
    if text:
        mac.keystroke(text)
    if key:
        mac.key(key, modifiers or [])
    return _ok()


# ------------------------------------------------------------------ tracks
@mcp.tool()
def nuendo_select_track(track: str | None = None,
                        direction: Literal["next", "previous"] | None = None) -> dict:
    """Select a track by name (case-insensitive, partial ok) or mixer-bank slot number,
    or step to the next/previous track."""
    if direction:
        bridge.action("nextTrack" if direction == "next" else "prevTrack")
    elif track is not None:
        slot = bridge.resolve_slot(track)
        bridge.set_bank(slot, "mSelected", 1.0)
    else:
        raise ValueError("give track or direction")
    _wait_events(0.3)
    return _ok(selected=bridge.state.selected.summary())


@mcp.tool()
def nuendo_bank(direction: Literal["next", "previous", "reset"]) -> dict:
    """Page the 32-channel mixer bank Claude can see (for bigger projects)."""
    bridge.action({"next": "nextBank", "previous": "prevBank", "reset": "resetBank"}[direction])
    _wait_events(0.4)
    return _ok(mixerBank=bridge.state.snapshot()["mixerBank"])


@mcp.tool()
def nuendo_set_track(
    track: str = "selected",
    volume_db: float | None = None,
    volume: float | None = None,
    pan: float | None = None,
    mute: bool | None = None,
    solo: bool | None = None,
    record_arm: bool | None = None,
    monitor: bool | None = None,
) -> dict:
    """Change mixer settings of a track ("selected", a name, or a bank slot).
    volume_db: target fader level in dB (searched using Nuendo's own read-out);
    volume: raw fader position 0..1; pan: -1 (L) .. 0 .. 1 (R)."""
    slot = None if track == "selected" else bridge.resolve_slot(track)

    def setp(param: str, v: float) -> None:
        if slot is None:
            bridge.set_selected(param, v)
        else:
            bridge.set_bank(slot, param, v)

    result: dict = {}
    if volume_db is not None:
        result["volume"] = bridge.set_volume_db(volume_db, slot)
    elif volume is not None:
        setp("mVolume", max(0.0, min(1.0, volume)))
    if pan is not None:
        setp("mPan", (max(-1.0, min(1.0, pan)) + 1) / 2)
    for param, v in (("mMute", mute), ("mSolo", solo), ("mRecordEnable", record_arm)):
        if v is not None:
            setp(param, 1.0 if v else 0.0)
    if monitor is not None:
        if slot is not None:
            raise ValueError("monitor can only be set on the selected track")
        bridge.set_selected("mMonitorEnable", 1.0 if monitor else 0.0)
    _wait_events()
    t = bridge.state.selected if slot is None else bridge.state.bank[slot]
    return _ok(track=t.summary(), **result)


@mcp.tool()
def nuendo_set_selected_sends_and_qc(
    send: int | None = None, send_level: float | None = None, send_on: bool | None = None,
    quick_control: int | None = None, quick_control_value: float | None = None,
) -> dict:
    """On the selected track: set send N (1-8) level 0..1 / on-off, or Quick Control N
    (1-8) to 0..1. Quick Controls map to whatever the user assigned (often plugin params)."""
    if send is not None:
        if not 1 <= send <= P.NUM_SENDS:
            raise ValueError("send must be 1..8")
        if send_level is not None:
            bridge.set_selected_cc(P.SELECTED_SEND_LEVEL_CC + send - 1, max(0, min(1, send_level)))
        if send_on is not None:
            bridge.set_selected_cc(P.SELECTED_SEND_ON_CC + send - 1, 1.0 if send_on else 0.0)
    if quick_control is not None and quick_control_value is not None:
        if not 1 <= quick_control <= P.NUM_QUICK_CONTROLS:
            raise ValueError("quick_control must be 1..8")
        bridge.set_selected_cc(P.SELECTED_QC_CC + quick_control - 1, max(0, min(1, quick_control_value)))
    _wait_events()
    return _ok(selected=bridge.state.selected.summary())


# ----------------------------------------------------------------- importing
def _fetch(source: str) -> Path:
    if re.match(r"https?://", source):
        dest_dir = WORK_DIR / "Downloads"
        dest_dir.mkdir(parents=True, exist_ok=True)
        name = Path(urllib.parse.urlparse(source).path).name or f"download_{int(time.time())}.wav"
        dest = dest_dir / name
        req = urllib.request.Request(source, headers={"User-Agent": "nuendo-claude"})
        with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
            while chunk := r.read(1 << 16):
                f.write(chunk)
        return dest
    p = Path(source).expanduser()
    if not p.exists():
        raise FileNotFoundError(p)
    return p.resolve()


def _place(path: Path, kind: Literal["audio", "midi"], track: str | None, position: str | None) -> dict:
    if track:
        nuendo_select_track(track=track)
    if position:
        nuendo_locate(position)
    if kind == "audio":
        bridge.run_command("File/Import Audio File")
    else:
        bridge.run_command("File/Import MIDI File")
    mac.focus()
    mac.choose_file_in_open_dialog(str(path))
    if kind == "audio" and IMPORT_OPTIONS_DIALOG:
        time.sleep(mac.DELAY * 1.5)
        mac.key("return")  # accept the Import Options dialog
    _wait_events(0.5)
    return _ok(imported=str(path), track=bridge.state.selected.name or None,
               position=bridge.state.position or position)


@mcp.tool()
def nuendo_import_audio(source: str, track: str | None = None, position: str | None = None) -> dict:
    """Put an audio file on the timeline. `source` is a local path or an http(s) URL
    (e.g. a Suno or Soundly download link; it is downloaded first). If `track` is given
    it is selected first; if `position` is given the cursor moves there first (same
    format as nuendo_locate). The file lands on the selected track at the cursor."""
    return _place(_fetch(source), "audio", track, position)


@mcp.tool()
def nuendo_create_midi(
    name: str,
    bpm: float = 120,
    time_signature: list[int] | None = None,
    chords: list[dict] | None = None,
    notes: list[dict] | None = None,
    drums: dict | None = None,
    import_to_nuendo: bool = True,
    position: str | None = None,
) -> dict:
    """Write a musical idea as a MIDI file and (by default) import it into Nuendo.

    chords: [{"symbol": "Am7", "start": 0, "length": 4, "octave": 4,
              "voicing": "smooth|close|open|drop2", "velocity": 80, "rhythm": [0, 2.5]}]
            start/length in beats from the clip start; rhythm = re-strike offsets.
    notes:  [{"pitch": "E4" or 64, "start": 0, "length": 0.5, "velocity": 96}] (C4 = 60)
    drums:  {"bars": 2, "steps_per_beat": 4,
             "pattern": {"kick": "x...x...x...x...", "snare": "....x.......x...",
                         "hat": "x.x.x.x.x.x.x.x."}}   GM drum map; X = accent.
    position: where to put it (moves the left locator & cursor there first).
    Nuendo's MIDI import places files per its MIDI File preferences; see README."""
    safe = re.sub(r"[^\w\- ]+", "", name).strip() or "idea"
    path = WORK_DIR / "MIDI" / f"{safe}_{time.strftime('%Y%m%d-%H%M%S')}.mid"
    ts = tuple(time_signature) if time_signature else (4, 4)
    summary = build_midi(path, bpm=bpm, time_signature=ts, chords=chords, notes=notes,
                         drums=drums, name=name)
    if import_to_nuendo:
        if position:
            pos = f"{position}.1.1.0" if re.fullmatch(r"\d+", position.strip()) else position
            bridge.run_command("Transport/Input Left Locator")
            time.sleep(0.3)
            mac.focus()
            mac.type_into_focused_field(pos)
            nuendo_locate(pos)
        summary["import"] = _place(path, "midi", None, None)
    return _ok(**summary)


def main() -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    mcp.run()


if __name__ == "__main__":
    main()
