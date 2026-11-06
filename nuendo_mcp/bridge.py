"""MIDI connection to the Claude Bridge script running inside Nuendo."""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field

from . import protocol as P


@dataclass
class TrackState:
    name: str = ""
    values: dict = field(default_factory=dict)    # param -> 0..1
    displays: dict = field(default_factory=dict)  # param -> "−6.02 dB"

    def summary(self) -> dict:
        out: dict = {"name": self.name}
        for p, v in self.values.items():
            out[p.removeprefix("m")[:1].lower() + p.removeprefix("m")[1:]] = v
        for p, d in self.displays.items():
            out[p.removeprefix("m")[:1].lower() + p.removeprefix("m")[1:] + "Display"] = d
        return out


class NuendoState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.hello: dict | None = None
        self.last_event_at: float = 0.0
        self.position: str = ""
        self.transport: dict = {}
        self.selected = TrackState()
        self.bank = [TrackState() for _ in range(P.BANK_SIZE)]
        self.changed = threading.Condition(self.lock)

    def apply(self, ev: dict) -> None:
        with self.lock:
            self.last_event_at = time.time()
            t = ev.get("t")
            if t == "hello":
                self.hello = ev
            elif t == "pos":
                self.position = ev.get("v", "")
            elif t == "tr" and ev.get("f") == "value":
                self.transport[ev["p"]] = ev["v"]
            elif t in ("sel", "bank"):
                if t == "sel":
                    track = self.selected
                else:
                    i = ev.get("i", -1)
                    if not 0 <= i < len(self.bank):
                        return
                    track = self.bank[i]
                f, p, v = ev.get("f"), ev.get("p"), ev.get("v")
                if f == "title":
                    # every parameter reports the channel name; volume is canonical
                    if p in ("mVolume", "mMute") or not track.name:
                        track.name = v
                elif f == "value":
                    track.values[p] = v
                elif f == "display":
                    track.displays[p] = v
            self.changed.notify_all()

    def snapshot(self) -> dict:
        with self.lock:
            tracks = [
                {"slot": i, **t.summary()} for i, t in enumerate(self.bank) if t.name
            ]
            return {
                "connected": self.hello is not None,
                "secondsSinceLastEvent": round(time.time() - self.last_event_at, 1)
                if self.last_event_at else None,
                "position": self.position,
                "transport": {
                    "playing": bool(self.transport.get("mStart")),
                    "recording": bool(self.transport.get("mRecord")),
                    "cycle": bool(self.transport.get("mCycleActive")),
                    "metronome": bool(self.transport.get("mMetronomeActive")),
                },
                "selectedTrack": self.selected.summary(),
                "mixerBank": tracks,
            }


def _find_port(names: list[str], wanted: str) -> str | None:
    for n in names:
        if wanted.lower() in n.lower():
            return n
    return None


class Bridge:
    """Owns the two IAC ports. MIDI libraries are imported lazily so the
    rest of the package (MIDI file generation, tests) works without them."""

    def __init__(self) -> None:
        self.state = NuendoState()
        self.commands = P.load_commands()
        self._out = None
        self._in = None
        self._send_lock = threading.Lock()

    # ------------------------------------------------------------ connection
    def connect(self) -> None:
        if self._out is not None:
            return
        import mido  # noqa: WPS433

        outs, ins = mido.get_output_names(), mido.get_input_names()
        out_name = _find_port(outs, P.PORT_TO_NUENDO)
        in_name = _find_port(ins, P.PORT_FROM_NUENDO)
        if not out_name or not in_name:
            raise RuntimeError(
                "IAC buses not found. In Audio MIDI Setup > IAC Driver, enable "
                f"'Device is online' and add buses named '{P.PORT_TO_NUENDO}' and "
                f"'{P.PORT_FROM_NUENDO}'. Outputs seen: {outs}; inputs seen: {ins}"
            )
        self._out = mido.open_output(out_name)
        self._in = mido.open_input(in_name, callback=self._on_message)

    def _on_message(self, msg) -> None:
        if msg.type == "sysex":
            ev = P.decode_event(list(msg.data))
            if ev:
                self.state.apply(ev)

    def _send(self, msg) -> None:
        self.connect()
        with self._send_lock:
            self._out.send(msg)

    def _cc(self, channel: int, cc: int, value: int) -> None:
        import mido
        self._send(mido.Message("control_change", channel=channel, control=cc,
                                value=max(0, min(127, int(value)))))

    def _tap(self, channel: int, note: int) -> None:
        import mido
        self._send(mido.Message("note_on", channel=channel, note=note, velocity=127))
        time.sleep(0.03)
        self._send(mido.Message("note_off", channel=channel, note=note, velocity=0))

    # -------------------------------------------------------------- commands
    def find_command(self, query: str) -> int:
        q = query.strip().lower()
        if "/" in q:
            cat, name = (s.strip() for s in q.split("/", 1))
            for i, c in enumerate(self.commands):
                if c["cat"].lower() == cat and c["name"].lower() == name:
                    return i
        matches = [i for i, c in enumerate(self.commands) if c["name"].lower() == q]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            opts = ", ".join(f"{self.commands[i]['cat']}/{self.commands[i]['name']}" for i in matches)
            raise ValueError(f"'{query}' is ambiguous; use one of: {opts}")
        raise ValueError(f"Unknown command '{query}'. Use nuendo_list_commands to see options.")

    def run_command(self, query: str) -> dict:
        i = self.find_command(query)
        ch, note = P.command_address(i)
        self._tap(ch, note)
        return self.commands[i]

    def transport(self, param: str, on: bool) -> None:
        self._cc(P.TRANSPORT_CHANNEL, P.TRANSPORT[param], 127 if on else 0)

    def action(self, name: str) -> None:
        note, _ = P.ACTIONS[name]
        self._tap(P.ACTION_CHANNEL, note)

    # ------------------------------------------------------------ parameters
    def set_selected(self, param: str, value01: float) -> None:
        self._cc(P.SELECTED_CHANNEL, P.SELECTED[param], round(value01 * 127))

    def set_selected_cc(self, cc: int, value01: float) -> None:
        self._cc(P.SELECTED_CHANNEL, cc, round(value01 * 127))

    def set_bank(self, slot: int, param: str, value01: float) -> None:
        if not 0 <= slot < P.BANK_SIZE:
            raise ValueError(f"slot must be 0..{P.BANK_SIZE - 1}")
        self._cc(P.BANK[param], slot, round(value01 * 127))

    def resolve_slot(self, track: str | int) -> int:
        if isinstance(track, int) or (isinstance(track, str) and track.isdigit()):
            return int(track)
        q = str(track).strip().lower()
        with self.state.lock:
            names = [(i, t.name) for i, t in enumerate(self.state.bank) if t.name]
        for i, n in names:
            if n.lower() == q:
                return i
        partial = [(i, n) for i, n in names if q in n.lower()]
        if len(partial) == 1:
            return partial[0][0]
        if partial:
            raise ValueError(f"'{track}' matches several tracks: {[n for _, n in partial]}")
        raise ValueError(
            f"No track named '{track}' in the current mixer bank ({[n for _, n in names]}). "
            "Use nuendo_bank to page if the project has more than 32 channels."
        )

    # ---------------------------------------------------------- volume in dB
    def set_volume_db(self, target_db: float, slot: int | None = None, timeout: float = 0.25) -> str:
        """Binary-search the 7-bit fader value using Nuendo's own dB read-out."""
        lo, hi = 0, 127
        best = (None, 1e9, "")

        def read() -> tuple[float | None, str]:
            track = self.state.selected if slot is None else self.state.bank[slot]
            text = track.displays.get("mVolume", "")
            return parse_db(text), text

        while lo <= hi:
            mid = (lo + hi) // 2
            with self.state.lock:
                before = (self.state.selected if slot is None else self.state.bank[slot]).displays.get("mVolume")
            if slot is None:
                self._cc(P.SELECTED_CHANNEL, P.SELECTED["mVolume"], mid)
            else:
                self._cc(P.BANK["mVolume"], slot, mid)
            deadline = time.time() + timeout
            with self.state.changed:
                while time.time() < deadline:
                    cur = (self.state.selected if slot is None else self.state.bank[slot]).displays.get("mVolume")
                    if cur != before:
                        break
                    self.state.changed.wait(deadline - time.time())
            db, text = read()
            if db is None:
                break
            if abs(db - target_db) < best[1]:
                best = (mid, abs(db - target_db), text)
            if db < target_db:
                lo = mid + 1
            else:
                hi = mid - 1
        if best[0] is None:
            raise RuntimeError("No volume read-out from Nuendo; is the bridge script active?")
        if slot is None:
            self._cc(P.SELECTED_CHANNEL, P.SELECTED["mVolume"], best[0])
        else:
            self._cc(P.BANK["mVolume"], slot, best[0])
        return best[2]


_DB_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def parse_db(text: str) -> float | None:
    if not text:
        return None
    if "inf" in text.lower() or "∞" in text:
        return -200.0
    m = _DB_RE.search(text)
    return float(m.group().replace(",", ".")) if m else None
