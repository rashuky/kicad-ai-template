"""Routing quality metrics (KiCad python), the last step of the routing chain.
usage: "C:/Program Files/KiCad/10.0/bin/python.exe" tools/pcb/route_metrics.py <board.kicad_pcb> [<board2> ...]
       ... tools/pcb/route_metrics.py --candidates <hand.kicad_pcb> <maze.kicad_pcb>

One column per board, plus the direction that is better. Criteria: README.md, "Routing quality".
Put the table in the PR, new board next to the previous one. Explain every criterion that gets worse.

--candidates compares a hand-routed board with a maze-routed copy of the same placement and lists the nets worth
handing to the maze in hybrid routing: long signal nets (hand length >= LONG mm, net class not in POWER_CLASSES)
whose hand route is at least DETOUR times the maze route. The list is board specific: rerun it after placement changes.

Net classes come from the netclass patterns in the .kicad_pro (pcbnew.LoadBoard does not apply them). Keep the
.kicad_pro next to each board under the same name, also for copies in a scratch folder. The script stops without it.
All zones are filled before measuring. A GND zone set to remove islands drops unconnected pieces, so the piece count
shows only pieces a GND via or pad still reaches (the rest shows as lost area).
"""
import fnmatch
import json
import math
import os
import sys

import pcbnew

TO = pcbnew.ToMM
GND = "GND"                                   # GND vias (stitching, fan-out) are wanted, so they are not counted
POUR_LAYER = pcbnew.B_Cu                      # the layer whose GND pour must stay in one piece
POWER_CLASSES = ("Power", "HighCurrent")      # net classes never handed to the maze (edit per project)
LONG, DETOUR = 80.0, 1.15                     # candidate rule: hand length [mm], hand / maze length ratio
MIN_LEN = 0.02                                # [mm] shorter segments have no direction
SLIVER = 1.0                                  # pour pieces below this area [mm²] are not counted
ROWS = [  # (key, label, better)
    ("vias", "Signal and power vias (no GND)", "lower"),
    ("segs", "Track segments", "lower"),
    ("off", "Segments off 0/45/90/135°", "lower"),
    ("sharp", "Bends sharper than 45°", "lower"),
    ("length", "Track length without GND [mm]", "lower"),
    ("blen", "Track length on the pour layer without GND [mm]", "lower"),
    ("pour", "Main GND pour piece on the pour layer [mm²]", "higher"),
    ("pieces", "GND pour pieces on the pour layer", "lower"),
]


def power_nets(path):
    """Test for nets in POWER_CLASSES, from the netclass patterns in the .kicad_pro next to the board."""
    pro = os.path.splitext(path)[0] + ".kicad_pro"
    if not os.path.exists(pro):
        sys.exit(f"{pro} missing: copy the .kicad_pro next to the board (net classes)")
    pats = json.load(open(pro, encoding="utf-8"))["net_settings"].get("netclass_patterns") or []
    return lambda nm: any(p["netclass"] in POWER_CLASSES and fnmatch.fnmatchcase(nm, p["pattern"]) for p in pats)


def angles(b, trk):
    """(segments off 0/45/90/135°, bends sharper than 45°). A bend is a joint of exactly two segments of one net on
    one layer, away from vias and pads. Segments shorter than MIN_LEN have no direction: no angle, no bend."""
    key = lambda p: (round(TO(p.x), 3), round(TO(p.y), 3))
    off, ends = 0, {}
    for t in trk:
        dx, dy = TO(t.GetEnd().x - t.GetStart().x), TO(t.GetEnd().y - t.GetStart().y)
        if math.hypot(dx, dy) >= MIN_LEN:
            a = math.degrees(math.atan2(dy, dx)) % 45
            off += min(a, 45 - a) > 0.5
        for p, q in ((t.GetStart(), t.GetEnd()), (t.GetEnd(), t.GetStart())):
            ends.setdefault((t.GetNetCode(), t.GetLayer(), key(p)), []).append(key(q))
    vias = {key(t.GetPosition()) for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T}
    pads = [p for f in b.GetFootprints() for p in f.Pads()]
    sharp = 0
    for (_, lay, pt), (fa, fc) in ((k, v) for k, v in ends.items() if len(v) == 2):
        u, v = (pt[0] - fa[0], pt[1] - fa[1]), (fc[0] - pt[0], fc[1] - pt[1])
        lu, lv = math.hypot(*u), math.hypot(*v)
        if pt in vias or lu < MIN_LEN or lv < MIN_LEN:
            continue
        c = (u[0] * v[0] + u[1] * v[1]) / (lu * lv)
        if math.degrees(math.acos(max(-1.0, min(1.0, c)))) > 46.0:
            at = pcbnew.VECTOR2I(pcbnew.FromMM(pt[0]), pcbnew.FromMM(pt[1]))
            sharp += not any(p.IsOnLayer(lay) and p.HitTest(at) for p in pads)
    return off, sharp


def metrics(path):
    power = power_nets(path)
    b = pcbnew.LoadBoard(path)
    trk = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T]   # arcs are not counted anywhere
    m = {
        "vias": sum(1 for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T and t.GetNetname() != GND),
        "segs": len(trk),
        "length": sum(TO(t.GetLength()) for t in trk if t.GetNetname() != GND),
        "blen": sum(TO(t.GetLength()) for t in trk if t.GetLayer() == POUR_LAYER and t.GetNetname() != GND),
    }
    m["off"], m["sharp"] = angles(b, trk)
    pcbnew.ZONE_FILLER(b).Fill([z for z in b.Zones() if not z.GetIsRuleArea()])   # all zones: priorities interact
    areas = []
    for z in b.Zones():
        if z.GetIsRuleArea() or z.GetNetname() != GND or not z.IsOnLayer(POUR_LAYER):
            continue
        p = z.GetFilledPolysList(POUR_LAYER)
        for i in range(p.OutlineCount()):
            areas.append((abs(p.Outline(i).Area()) - sum(abs(p.Hole(i, h).Area()) for h in range(p.HoleCount(i)))) / 1e12)
    m["pour"] = max(areas) if areas else 0.0
    m["pieces"] = sum(1 for a in areas if a >= SLIVER)
    nets = {}
    for t in b.GetTracks():
        n = nets.setdefault(t.GetNetname(), [0.0, 0, power(t.GetNetname())])
        if t.Type() == pcbnew.PCB_VIA_T:
            n[1] += 1
        elif t.Type() == pcbnew.PCB_TRACE_T:
            n[0] += TO(t.GetLength())
    m["nets"] = nets
    return m


def table(paths):
    ms = [metrics(p) for p in paths]
    names = [os.path.basename(p) for p in paths]
    if len(set(names)) < len(names):          # same file name: name the column by its folder
        names = [os.path.basename(os.path.dirname(os.path.abspath(p))) for p in paths]
    if len(set(names)) < len(names):          # same folder name too: the paths as given
        names = list(paths)
    print("| Criterion | " + " | ".join(names) + " | Better |")
    print("|---|" + "---|" * len(paths) + "---|")
    for key, label, better in ROWS:
        print(f"| {label} | " + " | ".join(f"{m[key]:.0f}" for m in ms) + f" | {better} |")


def candidates(hand, maze):
    h, z = metrics(hand)["nets"], metrics(maze)["nets"]
    print("| Net | Hand length [mm] (vias) | Maze length [mm] (vias) | Hand / maze |")
    print("|---|---|---|---|")
    for nm, (lh, vh, pwr) in sorted(h.items(), key=lambda kv: -kv[1][0]):
        if nm in ("", GND) or pwr or lh < LONG or nm not in z or z[nm][0] <= 0:
            continue
        r = lh / z[nm][0]
        if r >= DETOUR:
            print(f"| {nm} | {lh:.0f} ({vh}) | {z[nm][0]:.0f} ({z[nm][1]}) | {r:.2f} |")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")   # ² and ° on a non-UTF-8 Windows console
    args = sys.argv[1:]
    if not args or (args[0] == "--candidates" and len(args) != 3):
        sys.exit(__doc__)
    if args[0] == "--candidates":
        candidates(args[1], args[2])
    else:
        table(args)
