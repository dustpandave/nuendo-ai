"""Generate the Nuendo MIDI Remote script from the template + protocol.

Usage:  python nuendo_script/build.py [output_dir]
Default output: nuendo_script/dist/Claude/Nuendo Bridge/Claude_Nuendo Bridge.js
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nuendo_mcp.protocol import script_config  # noqa: E402

VENDOR, DEVICE = "Claude", "Nuendo Bridge"
FILENAME = f"{VENDOR}_{DEVICE}.js"


def build(out_root: Path) -> Path:
    template = (ROOT / "nuendo_script" / "template.js").read_text()
    marker = "/*__CONFIG__*/ {}"
    if marker not in template:
        raise SystemExit("config marker missing from template.js")
    js = template.replace(marker, json.dumps(script_config(), indent=1))
    out_dir = out_root / VENDOR / DEVICE
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / FILENAME
    out.write_text(js)
    return out


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "nuendo_script" / "dist"
    print(build(root))
