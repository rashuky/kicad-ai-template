"""Routing quality metrics (KiCad python), the last step of the routing chain.
usage: "C:/Program Files/KiCad/10.0/bin/python.exe" tools/pcb/route_metrics.py <board.kicad_pcb> [<board2> ...]
       ... tools/pcb/route_metrics.py --candidates <hand.kicad_pcb> <maze.kicad_pcb>

One column per board, plus the direction that is better. Criteria: README.md, "Routing quality".
Put the table in the PR, new board next to the previous one. Explain every criterion that gets worse.

--candidates compares a hand-routed board with a maze-routed copy of the same placement and lists the nets worth
handing to the maze in hybrid routing: long signal nets (hand length >= LONG mm, net class not in POWER_CLASSES)
whose hand route is at least DETOUR times the maze route. The list is board specific: rerun it after placement changes.
"""
import math
import os
import sys

import pcbnew

TO = pcbnew.ToMM
B = pcbnew.B_Cu
GND = "GND"                                   # GND vias (stitching, fan-out) are wanted, so they are not counted
POUR_LAYER = B                                # the layer whose GND pour must stay in one piece
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
    ("blen", "Track length on the pour layer [mm]", "lower"),
    ("pour", "Main GND pour piece on the pour layer [mm²]", "higher"),
    ("pieces", "GND pour pieces on the pour layer", "lower"),
]


def angles(b, trk):
    """(segments off 0/45/90/135°, bends sharper than 45°). A bend is a joint of exactly two segments of one net on
    one layer, away from vias and pads. Segments shorter than MIN_LEN have no visible direction and are skipped."""
    key = lambda p: (round(TO(p.x), 3), round(TO(p.y), 3))
    off, ends = 0, {}
    for t in trk:
        dx, dy = TO(t.GetEnd().x - t.GetStart().x), TO(t.GetEnd().y - t.GetStart().y)
        if math.hypot(dx, dy) < MIN_LEN:
            continue
        a = math.degrees(math.atan2(dy, dx)) % 45
        off += min(a, 45 - a) > 0.5
        for p, q in ((t.GetStart(), t.GetEnd()), (t.GetEnd(), t.GetStart())):
            ends.setdefault((t.GetNetCode(), t.GetLayer(), key(p)), []).append(key(q))
    blocked = {key(t.GetPosition()) for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T}
    pads = [p for f in b.GetFootprints() for p in f.Pads()]
    sharp = 0
    for (_, lay, pt), (fa, fc) in ((k, v) for k, v in ends.items() if len(v) == 2):
        if pt in blocked:
            continue
        u, v = (pt[0] - fa[0], pt[1] - fa[1]), (fc[0] - pt[0], fc[1] - pt[1])
        c = (u[0] * v[0] + u[1] * v[1]) / (math.hypot(*u) * math.hypot(*v))
        if math.degrees(math.acos(max(-1.0, min(1.0, c)))) > 46.0:
            at = pcbnew.VECTOR2I(pcbnew.FromMM(pt[0]), pcbnew.FromMM(pt[1]))
            sharp += not any(p.IsOnLayer(lay) and p.HitTest(at) for p in pads)
    return off, sharp


def metrics(path):
    b = pcbnew.LoadBoard(path)
    trk = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T]
    m = {
        "vias": sum(1 for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T and t.GetNetname() != GND),
        "segs": len(trk),
        "length": sum(TO(t.GetLength()) for t in trk if t.GetNetname() != GND),
        "blen": sum(TO(t.GetLength()) for t in trk if t.GetLayer() == POUR_LAYER),
    }
    m["off"], m["sharp"] = angles(b, trk)
    z = [z_ for z_ in b.Zones() if not z_.GetIsRuleArea() and z_.GetNetname() == GND and z_.IsOnLayer(POUR_LAYER)]
    pcbnew.ZONE_FILLER(b).Fill(z)
    areas = [abs(p.Outline(i).Area()) / 1e12 for z_ in z for p in [z_.GetFilledPolysList(POUR_LAYER)]
             for i in range(p.OutlineCount())]
    m["pour"] = max(areas) if areas else 0.0
    m["pieces"] = sum(1 for a in areas if a >= SLIVER)
    nets = {}
    for t in b.GetTracks():
        n = nets.setdefault(t.GetNetname(), [0.0, 0, t.GetNetClassName()])
        if t.Type() == pcbnew.PCB_VIA_T:
            n[1] += 1
        else:
            n[0] += TO(t.GetLength())
    m["nets"] = nets
    return m


def table(paths):
    ms = [metrics(p) for p in paths]
    names = [os.path.basename(p) for p in paths]
    if len(set(names)) < len(names):          # same file name in several folders: name the column by its folder
        names = [os.path.basename(os.path.dirname(os.path.abspath(p))) for p in paths]
    print("| Criterion | " + " | ".join(names) + " | Better |")
    print("|---|" + "---|" * len(paths) + "---|")
    for key, label, better in ROWS:
        print(f"| {label} | " + " | ".join(f"{m[key]:.0f}" for m in ms) + f" | {better} |")


def candidates(hand, maze):
    h, z = metrics(hand)["nets"], metrics(maze)["nets"]
    print("| Net | Hand length [mm] (vias) | Maze length [mm] (vias) | Hand / maze |")
    print("|---|---|---|---|")
    for nm, (lh, vh, cls) in sorted(h.items(), key=lambda kv: -kv[1][0]):
        if nm in ("", GND) or cls in POWER_CLASSES or lh < LONG or nm not in z or z[nm][0] <= 0:
            continue
        r = lh / z[nm][0]
        if r >= DETOUR:
            print(f"| {nm} | {lh:.0f} ({vh}) | {z[nm][0]:.0f} ({z[nm][1]}) | {r:.2f} |")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    if args[0] == "--candidates":
        candidates(args[1], args[2])
    else:
        table(args)
