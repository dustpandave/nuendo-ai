import json
import subprocess
from pathlib import Path

import mido
import pytest

from nuendo_mcp import protocol as P
from nuendo_mcp.bridge import Bridge, parse_db
from nuendo_mcp.midi_gen import build_midi, note_number, parse_chord, voice_chord

ROOT = Path(__file__).resolve().parent.parent


def test_sysex_roundtrip_unicode():
    ev = {"t": "bank", "i": 3, "p": "mVolume", "f": "title", "v": "Vöcals — Lead 🎤"}
    data = P.encode_event(ev)
    assert all(0 <= b < 128 for b in data)
    assert P.decode_event(data) == ev


def test_decode_ignores_foreign_sysex():
    assert P.decode_event([0x43, 0x10, 0x00]) is None


def test_state_tracks_bank_and_selection():
    b = Bridge()
    for ev in [
        {"t": "hello"},
        {"t": "bank", "i": 0, "p": "mVolume", "f": "title", "v": "Kick"},
        {"t": "bank", "i": 1, "p": "mVolume", "f": "title", "v": "Bass DI"},
        {"t": "bank", "i": 1, "p": "mMute", "f": "value", "v": 1},
        {"t": "sel", "p": "mVolume", "f": "display", "v": "-6.02 dB"},
        {"t": "tr", "p": "mStart", "f": "value", "v": 1},
        {"t": "pos", "v": "17. 1. 1. 0"},
    ]:
        b.state.apply(ev)
    snap = b.state.snapshot()
    assert snap["connected"] and snap["transport"]["playing"]
    assert [t["name"] for t in snap["mixerBank"]] == ["Kick", "Bass DI"]
    assert snap["mixerBank"][1]["mute"] == 1
    assert snap["selectedTrack"]["volumeDisplay"] == "-6.02 dB"
    assert b.resolve_slot("bass") == 1
    assert b.resolve_slot("0") == 0
    with pytest.raises(ValueError):
        b.resolve_slot("strings")


def test_commands_resolve():
    b = Bridge()
    assert b.commands[b.find_command("Edit/Undo")]["name"] == "Undo"
    assert b.commands[b.find_command("split at cursor")]["cat"] == "Edit"
    with pytest.raises(ValueError):
        b.find_command("Make It Sound Good")
    names = [f"{c['cat']}/{c['name']}" for c in b.commands]
    assert len(names) == len(set(names)), "duplicate commands"


def test_parse_db():
    assert parse_db("-6.02 dB") == -6.02
    assert parse_db("0,00 dB") == 0.0
    assert parse_db("-∞") == -200.0
    assert parse_db("") is None


def test_chords():
    assert parse_chord("F#m7b5/C") == (6, [0, 3, 6, 10], 0)
    assert voice_chord("C", 4, "close") == [60, 64, 67]
    assert voice_chord("Am7", 3, "close") == [57, 60, 64, 67]
    g = voice_chord("G", 4, "smooth", prev=[60, 64, 67])
    assert sorted(n % 12 for n in g) == [2, 7, 11] and max(g) - min(g) <= 12
    assert note_number("C4") == 60 and note_number("Bb2") == 46


def test_build_midi(tmp_path):
    out = tmp_path / "idea.mid"
    s = build_midi(out, bpm=92,
                   chords=[{"symbol": "Am7", "start": 0, "length": 4},
                           {"symbol": "Dm9", "start": 4, "length": 4, "rhythm": [0, 2.5]}],
                   notes=[{"pitch": "E4", "start": 0, "length": 1}],
                   drums={"bars": 2, "pattern": {"kick": "x...x...x...x...", "snare": "....X......."}})
    mid = mido.MidiFile(out)
    assert len(mid.tracks) == 4
    assert abs(mid.length - 2 * 4 * 60 / 92) < 0.5
    assert s["tracks"][2]["hits"] == 8 + 3  # kick 4/bar; 12-step snare cycles over 32 steps


def test_generated_script_runs_in_mock_host(tmp_path):
    import sys
    sys.path.insert(0, str(ROOT))
    from nuendo_script.build import build
    js = build(tmp_path)
    r = subprocess.run(["node", str(ROOT / "tests" / "mock_host.js"), str(js)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    info = json.loads(r.stdout)
    assert info["commands"] == len(P.load_commands())
    assert info["actionBindings"] == len(P.ACTIONS)
    hello = info["helloSysex"]
    assert hello[0] == 0xF0 and hello[-1] == 0xF7
    assert P.decode_event(hello[1:-1])["t"] == "hello"


def test_outgoing_midi_addresses(monkeypatch):
    sent = []

    class FakeOut:
        def send(self, m):
            sent.append(m)

    b = Bridge()
    b._out = FakeOut()
    monkeypatch.setattr("time.sleep", lambda s: None)
    b.state.apply({"t": "bank", "i": 5, "p": "mVolume", "f": "title", "v": "Pads"})
    cmd = b.run_command("Edit/Undo")
    idx = b.commands.index(cmd)
    assert (sent[0].type, sent[0].channel, sent[0].note) == ("note_on", idx // 128, idx % 128)
    sent.clear()
    b.set_bank(b.resolve_slot("pads"), "mMute", 1.0)
    assert (sent[0].channel, sent[0].control, sent[0].value) == (P.BANK["mMute"], 5, 127)
    sent.clear()
    b.set_selected("mPan", 0.5)
    assert (sent[0].channel, sent[0].control, sent[0].value) == (P.SELECTED_CHANNEL, P.SELECTED["mPan"], 64)
