"""Turn musical ideas (chord symbols, note lists, drum grids) into .mid files."""
from __future__ import annotations

import re
from pathlib import Path

import mido

PPQ = 480
NOTE_NAMES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

# quality suffix -> semitones above root (longest suffixes matched first)
QUALITIES = {
    "": [0, 4, 7], "maj": [0, 4, 7], "M": [0, 4, 7],
    "m": [0, 3, 7], "min": [0, 3, 7], "-": [0, 3, 7],
    "dim": [0, 3, 6], "°": [0, 3, 6], "aug": [0, 4, 8], "+": [0, 4, 8],
    "sus2": [0, 2, 7], "sus4": [0, 5, 7], "sus": [0, 5, 7], "5": [0, 7],
    "6": [0, 4, 7, 9], "m6": [0, 3, 7, 9], "69": [0, 4, 7, 9, 14],
    "7": [0, 4, 7, 10], "maj7": [0, 4, 7, 11], "M7": [0, 4, 7, 11], "Δ": [0, 4, 7, 11],
    "m7": [0, 3, 7, 10], "min7": [0, 3, 7, 10], "-7": [0, 3, 7, 10],
    "mMaj7": [0, 3, 7, 11], "m7b5": [0, 3, 6, 10], "ø": [0, 3, 6, 10],
    "dim7": [0, 3, 6, 9], "°7": [0, 3, 6, 9], "7sus4": [0, 5, 7, 10],
    "add9": [0, 4, 7, 14], "madd9": [0, 3, 7, 14],
    "9": [0, 4, 7, 10, 14], "maj9": [0, 4, 7, 11, 14], "m9": [0, 3, 7, 10, 14],
    "7b9": [0, 4, 7, 10, 13], "7#9": [0, 4, 7, 10, 15],
    "11": [0, 4, 7, 10, 14, 17], "m11": [0, 3, 7, 10, 14, 17],
    "13": [0, 4, 7, 10, 14, 21], "maj13": [0, 4, 7, 11, 14, 21], "m13": [0, 3, 7, 10, 14, 21],
}
_QUALITY_KEYS = sorted(QUALITIES, key=len, reverse=True)

# General MIDI drum map (what most drum VSTs, incl. Groove Agent SE, follow)
GM_DRUMS = {
    "kick": 36, "snare": 38, "rim": 37, "clap": 39, "snare2": 40,
    "hat": 42, "hihat": 42, "closedhat": 42, "pedalhat": 44, "openhat": 46,
    "lowtom": 45, "midtom": 47, "hightom": 50, "floortom": 43,
    "crash": 49, "ride": 51, "ridebell": 53, "china": 52, "splash": 55,
    "tambourine": 54, "cowbell": 56, "shaker": 70, "conga": 63, "bongo": 60,
}


def note_number(n: int | str) -> int:
    """60, 'C4', 'F#3', 'Bb2' -> MIDI note (C4 = 60, Steinberg uses C3 = 60;
    pass 'C3' with octave_offset if you prefer that convention)."""
    if isinstance(n, int):
        return n
    m = re.fullmatch(r"([A-Ga-g])([#b]*)(-?\d+)", n.strip())
    if not m:
        raise ValueError(f"bad note name: {n}")
    pc = NOTE_NAMES[m.group(1).upper()] + m.group(2).count("#") - m.group(2).count("b")
    return 12 * (int(m.group(3)) + 1) + pc


def parse_chord(symbol: str) -> tuple[int, list[int], int | None]:
    """'F#m7b5/C' -> (root pitch class, intervals, bass pitch class or None)."""
    s = symbol.strip()
    bass = None
    if "/" in s:
        s, b = s.split("/", 1)
        mb = re.fullmatch(r"([A-Ga-g])([#b]?)", b.strip())
        if not mb:
            raise ValueError(f"bad bass note in {symbol}")
        bass = (NOTE_NAMES[mb.group(1).upper()] + {"#": 1, "b": -1, "": 0}[mb.group(2)]) % 12
    m = re.match(r"([A-Ga-g])([#b]?)", s)
    if not m:
        raise ValueError(f"bad chord symbol: {symbol}")
    root = (NOTE_NAMES[m.group(1).upper()] + {"#": 1, "b": -1, "": 0}[m.group(2)]) % 12
    rest = s[m.end():]
    for q in _QUALITY_KEYS:
        if rest == q:
            return root, list(QUALITIES[q]), bass
    raise ValueError(f"unknown chord quality '{rest}' in {symbol}")


def voice_chord(symbol: str, octave: int = 4, voicing: str = "close",
                prev: list[int] | None = None) -> list[int]:
    """Return MIDI notes. voicing: close | open | drop2 | smooth (voice-leads from prev)."""
    root, ivs, bass = parse_chord(symbol)
    base = 12 * (octave + 1) + root
    notes = [base + i for i in ivs]
    if voicing == "open" and len(notes) >= 3:
        notes = [notes[0]] + [n + 12 for n in notes[1::2]] + notes[2::2]
    elif voicing == "drop2" and len(notes) >= 4:
        top = sorted(notes)
        top[-2] -= 12
        notes = top
    elif voicing == "smooth" and prev:
        center = sum(prev) / len(prev)
        pcs = [(root + i) % 12 for i in ivs]
        best = None
        for r in range(len(pcs)):
            order = pcs[r:] + pcs[:r]
            for o in (octave - 1, octave, octave + 1):
                cand = [12 * (o + 1) + order[0]]
                for pc in order[1:]:
                    n = cand[-1] + 1
                    while n % 12 != pc:
                        n += 1
                    cand.append(n)
                cost = abs(sum(cand) / len(cand) - center) + (cand[-1] - cand[0]) * 0.3
                if best is None or cost < best[0]:
                    best = (cost, cand)
        notes = best[1]
    notes = sorted(set(notes))
    if bass is not None:
        b = 12 * octave + bass
        while b >= notes[0]:
            b -= 12
        notes = [b] + notes
    return notes


def _ticks(beats: float) -> int:
    return int(round(beats * PPQ))


def _track_from_events(name: str, channel: int, events: list[tuple[float, float, int, int]],
                       program: int | None = None) -> mido.MidiTrack:
    """events: (start_beat, length_beats, pitch, velocity)."""
    tr = mido.MidiTrack()
    tr.append(mido.MetaMessage("track_name", name=name, time=0))
    if program is not None:
        tr.append(mido.Message("program_change", channel=channel, program=program, time=0))
    msgs = []
    for start, length, pitch, vel in events:
        if not 0 <= pitch <= 127:
            continue
        msgs.append((_ticks(start), 1, mido.Message("note_on", channel=channel, note=pitch,
                                                     velocity=max(1, min(127, vel)))))
        msgs.append((_ticks(start + length), 0, mido.Message("note_off", channel=channel,
                                                              note=pitch, velocity=0)))
    msgs.sort(key=lambda m: (m[0], m[1]))  # note-offs before note-ons at same tick
    now = 0
    for t, _, msg in msgs:
        tr.append(msg.copy(time=t - now))
        now = t
    tr.append(mido.MetaMessage("end_of_track", time=0))
    return tr


def build_midi(
    path: str | Path,
    bpm: float = 120,
    time_signature: tuple[int, int] = (4, 4),
    chords: list[dict] | None = None,
    notes: list[dict] | None = None,
    drums: dict | None = None,
    name: str = "Claude idea",
) -> dict:
    """Write a type-1 MIDI file. Returns a short description of what was written.

    chords: [{"symbol": "Am7", "start": 0, "length": 4, "octave": 4,
              "voicing": "smooth", "velocity": 80, "rhythm": [0, 1.5, 3]?}]
       - start/length in beats; optional rhythm = list of beat offsets to re-strike
    notes:  [{"pitch": "E4" | 64, "start": 0, "length": 0.5, "velocity": 96}]
    drums:  {"steps_per_beat": 4, "bars": 2, "velocity": 100,
             "pattern": {"kick": "x...x...x...x...", "snare": "....x.......x..."}}
       - 'x' = hit, 'X' = accent, '.' or '-' = rest; pattern repeats to fill bars
    """
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    mid = mido.MidiFile(type=1, ticks_per_beat=PPQ)
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("track_name", name=name, time=0))
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    meta.append(mido.MetaMessage("time_signature", numerator=time_signature[0],
                                 denominator=time_signature[1], time=0))
    meta.append(mido.MetaMessage("end_of_track", time=0))
    mid.tracks.append(meta)
    summary: dict = {"file": str(path), "bpm": bpm, "tracks": []}
    total_beats = 0.0

    if chords:
        ev, prev = [], None
        for c in chords:
            pitches = voice_chord(c["symbol"], c.get("octave", 4), c.get("voicing", "smooth"), prev)
            prev = pitches
            start, length = float(c["start"]), float(c.get("length", 4))
            hits = c.get("rhythm") or [0]
            for k, off in enumerate(hits):
                end = hits[k + 1] if k + 1 < len(hits) else length
                for p in pitches:
                    ev.append((start + off, max(0.05, end - off - 0.02), p, int(c.get("velocity", 80))))
            total_beats = max(total_beats, start + length)
        mid.tracks.append(_track_from_events("Chords", 0, ev))
        summary["tracks"].append({"name": "Chords", "chords": [c["symbol"] for c in chords]})

    if notes:
        ev = []
        for n in notes:
            start, length = float(n["start"]), float(n.get("length", 1))
            ev.append((start, length, note_number(n["pitch"]), int(n.get("velocity", 96))))
            total_beats = max(total_beats, start + length)
        mid.tracks.append(_track_from_events(name, 1, ev))
        summary["tracks"].append({"name": name, "notes": len(ev)})

    if drums:
        spb = int(drums.get("steps_per_beat", 4))
        beats_per_bar = time_signature[0] * 4 / time_signature[1]
        bars = int(drums.get("bars", 1))
        total_steps = int(round(bars * beats_per_bar * spb))
        vel = int(drums.get("velocity", 100))
        ev = []
        for inst, pat in drums["pattern"].items():
            pitch = GM_DRUMS.get(inst.lower().replace(" ", "").replace("-", ""))
            if pitch is None and inst.isdigit():
                pitch = int(inst)
            elif pitch is None and re.fullmatch(r"[A-Ga-g][#b]?-?\d+", inst):
                pitch = note_number(inst)
            if pitch is None:
                raise ValueError(f"unknown drum '{inst}'. Known: {sorted(GM_DRUMS)}")
            steps = [ch for ch in pat if not ch.isspace() and ch != "|"]
            if not steps:
                continue
            for s in range(total_steps):
                ch = steps[s % len(steps)]
                if ch in "xXoO":
                    v = min(127, vel + 20) if ch in "XO" else vel
                    ev.append((s / spb, 1 / spb * 0.9, pitch, v))
        mid.tracks.append(_track_from_events("Drums", 9, ev))
        total_beats = max(total_beats, total_steps / spb)
        summary["tracks"].append({"name": "Drums", "hits": len(ev), "bars": bars})

    if len(mid.tracks) == 1:
        raise ValueError("nothing to write: give chords, notes or drums")
    mid.save(path)
    summary["lengthBeats"] = total_beats
    return summary
