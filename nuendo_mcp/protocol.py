"""MIDI protocol shared by the MCP server and the Nuendo MIDI Remote script.

The Nuendo script is *generated* from this file (see nuendo_script/build.py),
so the two sides can never drift apart.

Direction "to Nuendo"  (IAC bus "Claude to Nuendo"):
  ch 0-7   note on      -> key command #(ch*128 + note)        (commands.json order)
  ch 8     CC n         -> transport value (absolute, 127 = on)
  ch 8     note n       -> host action (next track, next bank...)
  ch 9     CC n         -> parameter of the *selected* track
  ch 10-15 CC i         -> parameter of mixer-bank channel i (0..BANK_SIZE-1)

Direction "from Nuendo" (IAC bus "Claude from Nuendo"):
  SysEx F0 7D 01 <payload> F7 where payload is a JSON string, each UTF-16
  code unit packed into three 7-bit bytes.
"""
from __future__ import annotations

import json
from pathlib import Path

PORT_TO_NUENDO = "Claude to Nuendo"
PORT_FROM_NUENDO = "Claude from Nuendo"

SYSEX_MANUFACTURER = 0x7D  # "non-commercial / educational" ID
SYSEX_EVENT = 0x01

COMMAND_CHANNELS = 8  # 8 * 128 = 1024 key-command slots
TRANSPORT_CHANNEL = 8
ACTION_CHANNEL = 8
SELECTED_CHANNEL = 9
BANK_SIZE = 32

# name -> CC on TRANSPORT_CHANNEL; key is the mTransport.mValue member in the API
TRANSPORT = {
    "mStart": 0,
    "mStop": 1,
    "mRecord": 2,
    "mCycleActive": 3,
    "mMetronomeActive": 4,
    "mRewind": 5,
    "mForward": 6,
}

# name -> note on ACTION_CHANNEL; value is a dotted path below page.mHostAccess
ACTIONS = {
    "nextTrack": (0, "mTrackSelection.mAction.mNextTrack"),
    "prevTrack": (1, "mTrackSelection.mAction.mPrevTrack"),
    "nextBank": (2, "BANK.mAction.mNextBank"),
    "prevBank": (3, "BANK.mAction.mPrevBank"),
    "resetBank": (4, "BANK.mAction.mResetBank"),
}

RESYNC_NOTE = 127  # note on ACTION_CHANNEL: script re-sends hello + all cached state

# parameter of the selected track -> CC on SELECTED_CHANNEL
SELECTED = {
    "mVolume": 0,
    "mPan": 1,
    "mMute": 2,
    "mSolo": 3,
    "mRecordEnable": 4,
    "mMonitorEnable": 5,
}
SELECTED_SEND_LEVEL_CC = 10  # +0..7  -> mSends.getByIndex(i).mLevel
SELECTED_SEND_ON_CC = 20     # +0..7  -> mSends.getByIndex(i).mOn
SELECTED_QC_CC = 30          # +0..7  -> mQuickControls.getByIndex(i)
NUM_SENDS = 8
NUM_QUICK_CONTROLS = 8

# bank parameter -> MIDI channel (CC number = bank slot index)
BANK = {
    "mVolume": 10,
    "mPan": 11,
    "mMute": 12,
    "mSolo": 13,
    "mSelected": 14,
    "mRecordEnable": 15,
}

COMMANDS_FILE = Path(__file__).with_name("commands.json")


def load_commands() -> list[dict]:
    """Key commands in slot order: [{"cat": "Edit", "name": "Undo", "help": ...}, ...]."""
    data = json.loads(COMMANDS_FILE.read_text())
    cmds = [c for group in data["groups"] for c in group["commands"]]
    if len(cmds) > COMMAND_CHANNELS * 128:
        raise ValueError("too many commands")
    return cmds


def command_address(index: int) -> tuple[int, int]:
    """Slot index -> (channel, note)."""
    return index // 128, index % 128


def script_config() -> dict:
    """Everything the generated JS needs."""
    return {
        "portIn": PORT_TO_NUENDO,
        "portOut": PORT_FROM_NUENDO,
        "sysex": [SYSEX_MANUFACTURER, SYSEX_EVENT],
        "commands": [[c["cat"], c["name"]] for c in load_commands()],
        "transportChannel": TRANSPORT_CHANNEL,
        "transport": TRANSPORT,
        "actionChannel": ACTION_CHANNEL,
        "actions": {k: list(v) for k, v in ACTIONS.items()},
        "resyncNote": RESYNC_NOTE,
        "selectedChannel": SELECTED_CHANNEL,
        "selected": SELECTED,
        "sendLevelCC": SELECTED_SEND_LEVEL_CC,
        "sendOnCC": SELECTED_SEND_ON_CC,
        "qcCC": SELECTED_QC_CC,
        "numSends": NUM_SENDS,
        "numQC": NUM_QUICK_CONTROLS,
        "bankSize": BANK_SIZE,
        "bank": BANK,
    }


# ---------------------------------------------------------------- sysex codec
def encode_event(obj: dict) -> list[int]:
    """Encode like the JS side does (used for tests and the simulator)."""
    s = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    data = [SYSEX_MANUFACTURER, SYSEX_EVENT]
    raw = s.encode("utf-16-le")
    for i in range(0, len(raw), 2):
        c = raw[i] | (raw[i + 1] << 8)
        data += [(c >> 14) & 0x7F, (c >> 7) & 0x7F, c & 0x7F]
    return data


def decode_event(data: list[int] | tuple[int, ...]) -> dict | None:
    """Decode SysEx data (without F0/F7). Returns None if it isn't ours."""
    if len(data) < 2 or data[0] != SYSEX_MANUFACTURER or data[1] != SYSEX_EVENT:
        return None
    body = data[2:]
    units = bytearray()
    for i in range(0, len(body) - 2, 3):
        c = (body[i] << 14) | (body[i + 1] << 7) | body[i + 2]
        units += bytes((c & 0xFF, (c >> 8) & 0xFF))
    try:
        return json.loads(units.decode("utf-16-le", errors="surrogatepass"))
    except (ValueError, UnicodeDecodeError):
        return None
