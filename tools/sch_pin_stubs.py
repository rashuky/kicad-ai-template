"""Pin-stub rule check (CLAUDE.md, Editing rules): every pin starts with a straight wire of at least one grid step
along its own direction. Bends, junction dots, power symbols and other pins attach at the end of that stub.

usage: python tools/sch_pin_stubs.py [project folder, .kicad_pro or root .kicad_sch] [grid_mm]
Uses kschlint from tools/kicad-sch-lint, or from KSCHLINT_PATH.
Findings per pin: pin-on-pin, junction-on-pin, pin-on-wire-middle, several-wires-at-pin, bend-at-pin, stub-too-short,
no-stub (label on the pin tip, no wire). Power symbol and PWR_FLAG pins are exempt: they sit at the end of a stub.
Reused sheets are checked once. Exit code 1 when anything is found."""
import collections, math, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.environ.get("KSCHLINT_PATH", os.path.join(ROOT, "tools", "kicad-sch-lint")))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from sch_check import find_root_sch  # noqa: E402
from kschlint.model import load_project
from kschlint.scene import build

GRID = float(sys.argv[2]) if len(sys.argv) > 2 else 1.27


def same(a, b, t=1e-3):
    return abs(a[0] - b[0]) < t and abs(a[1] - b[1]) < t


def inside(p, a, b, t=1e-3):
    if same(p, a) or same(p, b):
        return False
    cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
    if abs(cross) > t:
        return False
    return min(a[0], b[0]) - t <= p[0] <= max(a[0], b[0]) + t and min(a[1], b[1]) - t <= p[1] <= max(a[1], b[1]) + t


arg = sys.argv[1] if len(sys.argv) > 1 else None
proj = load_project(arg if arg and arg.endswith(".kicad_sch") else find_root_sch(arg))
seen = set()
count = collections.Counter()
rows = []
for page in proj.pages:
    if page.sch.path in seen:          # reused sheets: check the file once
        continue
    seen.add(page.sch.path)
    sc = build(page)
    segs = [s for s in sc.wires if s.kind == "wire"]
    for p in sc.pins:
        tip = (p.x, p.y)
        ref = page.ref(p.symbol)
        why = []
        # pin touching another symbol's pin directly (incl. power symbols)
        if any(q.symbol is not p.symbol and same(tip, (q.x, q.y)) for q in sc.pins):
            if not p.symbol.is_power:
                why.append("pin-on-pin")
        if p.symbol.is_power:
            pass
        else:
            if any(same(tip, j) for j in sc.junctions):
                why.append("junction-on-pin")
            if any(inside(tip, s.a, s.b) for s in segs):
                why.append("pin-on-wire-middle")
            ends = [s for s in segs if same(tip, s.a) or same(tip, s.b)]
            if len(ends) > 1:
                why.append("several-wires-at-pin")
            if (not ends and not why and not any(same(tip, nc) for nc in sc.no_connects)
                    and not any(q.symbol is not p.symbol and same(tip, (q.x, q.y)) for q in sc.pins)):
                why.append("no-stub")  # a label sits right on the pin tip, or nothing is attached
            d = (p.x - p.ex, p.y - p.ey)
            n = math.hypot(*d)
            seen_bend = False
            for s in ends:
                far = s.b if same(tip, s.a) else s.a
                v = (far[0] - tip[0], far[1] - tip[1])
                L = math.hypot(*v)
                if n < 1e-6 or L < 1e-6:
                    continue
                cos = (v[0] * d[0] + v[1] * d[1]) / (L * n)
                if cos < 0.999:
                    if not seen_bend:
                        why.append("bend-at-pin")
                    seen_bend = True
                elif L < GRID - 1e-3:
                    why.append("stub-too-short")
        for w in why:
            count[(os.path.basename(page.sch.path), w)] += 1
            rows.append((os.path.basename(page.sch.path), ref, p.number, w))
for r in rows:
    print(*r)
print("---")
for k, v in sorted(count.items()):
    print(k[0], k[1], v)
print("total", sum(count.values()))
sys.exit(1 if count else 0)
