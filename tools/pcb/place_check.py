"""Proximity check (KiCad python): parts that must sit close to a pin, from a rules table.
usage: "C:/Program Files/KiCad/10.0/bin/python.exe" tools/pcb/place_check.py <board.kicad_pcb> [<rules.csv>] [--placement] [--all]

Rules: docs/place_rules.csv (default), one row per part group, from docs/layout_rules.md and the datasheets.
Columns, in header order:
  parts        refs that must sit close, separated by spaces (e.g. "C104 C105")
  to           the ref they belong to (IC, connector). Empty: only the GND via check
  to_pads      pad numbers of `to` to measure to (e.g. "8" for the cap at VIN1 of two VIN pins). Empty: all pads
  max_mm       largest centre distance between a pad of the part and a pad of `to` on the same net [mm]
  max_track_mm largest copper path between those pads [mm]: track length, vias and pour islands of the net count 0.
               Empty: not checked
  gnd_via_mm   largest track path from each GND pad of the part to a GND via [mm]. A pad that sits in a GND fill
               (thermal or solid) is measured by centre distance to the nearest GND via instead. Empty: not checked
  nets         nets to check (globs, separated by spaces). Empty: every net the two share except GND
  why          the rule's source (datasheet section, layout_rules.md line)
Example rows:
  C3,U1,8,2.5,3,2,,buck datasheet 10.1: input cap at VIN pin 8 / PGND
  C5,U1,,3,3,,/BOOT,boot cap: only the boot net (its other pad is SW)
  C7,U2,24,3.5,4,1.5,,100 nF at VCCP pin 24 (to_pads: one of two supply pins)
  U5,J3,,7,15,1.5,/USB_*,ESD next to the connector pins, GND via at the pad
  U1,,,,,2,,GND pins with a via at the pad
The copper graph keeps layers apart: tracks join at a shared end or T-join on the same layer, at a via (all its
layers), at a pad on the pad's layers, or through a fill island of the net on that layer.
--placement skips the track and via checks (board before routing). --all also prints the rows that pass.
Exits 1 if a rule fails or the arguments are wrong. Run it after placement and as a routing chain step.
"""
import csv
import fnmatch
import heapq
import math
import os
import sys

import pcbnew

TO, MM = pcbnew.ToMM, pcbnew.FromMM
GND = "GND"                                      # the ground net (edit per project)
TOL = MM(0.01)                                   # a track end this close to another track joins it
FLAGS = {"--placement", "--all"}


def dist(a, b):
    a, b = [(v.x, v.y) if hasattr(v, "x") else v for v in (a, b)]
    return math.hypot(a[0] - b[0], a[1] - b[1])


def graph(b, net, zones=True):
    """Copper graph of one net. Nodes: (x, y, layer) track points, ("via", i), ("pad", ref, number),
    ("zone", i, layer, outline). Edges: track pieces (their length), everything else 0."""
    trk = [t for t in b.GetTracks() if t.GetNetname() == net and t.Type() in (pcbnew.PCB_TRACE_T, pcbnew.PCB_ARC_T)]
    vias = [v for v in b.GetTracks() if v.Type() == pcbnew.PCB_VIA_T and v.GetNetname() == net]
    pads = [p for f in b.GetFootprints() for p in f.Pads() if p.GetNetname() == net]
    ends = {}                                    # layer -> track end points on it
    for t in trk:
        for p in ((t.GetStart().x, t.GetStart().y), (t.GetEnd().x, t.GetEnd().y)):
            ends.setdefault(t.GetLayer(), set()).add(p)
    adj = {}

    def edge(p, q, w):
        adj.setdefault(p, []).append((q, w))
        adj.setdefault(q, []).append((p, w))

    def pad_node(pd):
        return ("pad", pd.GetParentFootprint().GetReference(), pd.GetNumber())

    def via_node(i):
        return ("via", i)
    items = [(pd, pad_node(pd)) for pd in pads] + [(v, via_node(i)) for i, v in enumerate(vias)]
    for t in trk:
        lay, hw = t.GetLayer(), t.GetWidth() / 2
        a, c = (t.GetStart().x, t.GetStart().y), (t.GetEnd().x, t.GetEnd().y)
        L = dist(a, c)
        pts, joins = [(0.0, a), (L, c)], []
        if L > 0:
            for p in ends[lay]:                  # T joins: another track ends on this one's copper, same layer
                u = ((p[0] - a[0]) * (c[0] - a[0]) + (p[1] - a[1]) * (c[1] - a[1])) / L
                if 0 < u < L and abs((p[0] - a[0]) * (c[1] - a[1]) - (p[1] - a[1]) * (c[0] - a[0])) / L < max(TOL, hw):
                    pts.append((u, p))
        for it, node in items:                   # pads and vias whose copper touches this track on its layer
            if not it.IsOnLayer(lay):
                continue
            m = it.GetPosition()
            u = max(0.0, min(L, ((m.x - a[0]) * (c[0] - a[0]) + (m.y - a[1]) * (c[1] - a[1])) / L)) if L else 0.0
            if t.Type() == pcbnew.PCB_ARC_T:     # arcs: test the ends only
                u = 0.0 if dist(a, m) <= dist(c, m) else L
            p = (round(a[0] + (c[0] - a[0]) * u / L), round(a[1] + (c[1] - a[1]) * u / L)) if L else a
            if it.HitTest(pcbnew.VECTOR2I(*p), int(hw)):
                pts.append((u, p))
                joins.append((p, node))
        pts.sort()
        w = TO(t.GetLength()) / TO(L) if L else 1.0   # arcs: path length, not chord
        for (u0, p0), (u1, p1) in zip(pts, pts[1:]):
            edge((*p0, lay), (*p1, lay), (u1 - u0) * w)
        for p, node in joins:
            edge((*p, lay), node, 0.0)
    nodes = [n for n in adj if len(n) == 3 and isinstance(n[0], int)]
    for i, v in enumerate(vias):
        c, r = v.GetPosition(), v.GetWidth(pcbnew.F_Cu) / 2
        for pd in pads:                          # via in or touching a pad
            if pd.HitTest(c, int(r)):
                edge(("via", i), pad_node(pd), 0.0)
    if zones:
        for zi, z in enumerate(b.Zones()):
            if z.GetIsRuleArea() or z.GetNetname() != net:
                continue
            for lay in z.GetLayerSet().Seq():
                fill = z.GetFilledPolysList(lay)
                for k in range(fill.OutlineCount()):
                    ol, zn = fill.Outline(k), ("zone", zi, lay, k)
                    inside = lambda x, y: ol.PointInside(pcbnew.VECTOR2I(int(x), int(y)))
                    for n in nodes:
                        if n[2] == lay and inside(n[0], n[1]):
                            edge(zn, n, 0.0)
                    for i, v in enumerate(vias):
                        if v.IsOnLayer(lay) and inside(v.GetPosition().x, v.GetPosition().y):
                            edge(zn, ("via", i), 0.0)
                    for pd in pads:              # pad touches this island (thermal spokes leave the centre bare)
                        if pd.IsOnLayer(lay) and any(inside(*q) for q in pad_points(pd)):
                            edge(zn, pad_node(pd), 0.0)
    return adj


def pad_points(pd):
    """Centre and points just outside the pad edge (8 directions): a fill that reaches the pad covers one of them."""
    c, sz = pd.GetPosition(), pd.GetBoundingBox()
    hx, hy = sz.GetWidth() / 2 + MM(0.1), sz.GetHeight() / 2 + MM(0.1)
    return [(c.x, c.y)] + [(c.x + dx * hx, c.y + dy * hy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]


def shortest(adj, sources, done):
    """Shortest path [nm] from any source node to a node for which done(node) holds, None if there is none."""
    best = {s: 0.0 for s in sources if s in adj}
    q = [(0.0, i, s) for i, s in enumerate(best)]
    heapq.heapify(q)
    k = len(q)
    while q:
        d, _, p = heapq.heappop(q)
        if d > best.get(p, math.inf):
            continue
        if done(p):
            return d
        for n, w in adj[p]:
            if d + w < best.get(n, math.inf):
                best[n] = d + w
                k += 1
                heapq.heappush(q, (d + w, k, n))
    return None


def pad_id(pd):
    return ("pad", pd.GetParentFootprint().GetReference(), pd.GetNumber())


def main():
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args or set(flags) - FLAGS:
        sys.exit(__doc__)
    placement, show_all = "--placement" in flags, "--all" in flags
    path = args[0]
    rules = args[1] if len(args) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "place_rules.csv")
    if not os.path.exists(rules):
        sys.exit(f"no rules file {rules}")
    b = pcbnew.LoadBoard(path)
    if not placement:
        pcbnew.ZONE_FILLER(b).Fill([z for z in b.Zones() if not z.GetIsRuleArea()])
    fp = {f.GetReference(): f for f in b.GetFootprints()}
    graphs, rows, fails, n_rules = {}, [], 0, 0
    gnd_graph = None
    for r in csv.DictReader(open(rules, encoding="utf-8-sig", newline="")):
        n_rules += 1
        col = lambda k: (r.get(k) or "").strip()
        num = lambda k: float(col(k)) if col(k) else None
        to, mx, mt, mg = col("to"), num("max_mm"), num("max_track_mm"), num("gnd_via_mm")
        globs, to_pads = col("nets").split(), set(col("to_pads").split())
        for ref in col("parts").split():
            if ref not in fp or (to and to not in fp):
                rows.append((ref, to, "", "", "", "", "missing part"))
                fails += 1
                continue
            pads = list(fp[ref].Pads())
            if to:
                other = [p for p in fp[to].Pads() if not to_pads or p.GetNumber() in to_pads]
                nets = sorted({p.GetNetname() for p in pads} & {p.GetNetname() for p in other} - {"", GND})
                if globs:
                    nets = [n for n in nets if any(fnmatch.fnmatchcase(n, g) for g in globs)]
                if not nets:
                    rows.append((ref, to, "", "", "", "", "no shared net"))
                    fails += 1
                for n in nets:
                    pa = [p for p in pads if p.GetNetname() == n]
                    pb = [p for p in other if p.GetNetname() == n]
                    d = min(TO(dist(p.GetPosition(), q.GetPosition())) for p in pa for q in pb)
                    bad = mx is not None and d > mx
                    tr = ""
                    if mt is not None and not placement:
                        if n not in graphs:
                            graphs[n] = graph(b, n)
                        targets = {pad_id(p) for p in pb}
                        t = shortest(graphs[n], [pad_id(p) for p in pa], lambda node: node in targets)
                        if t is None:
                            tr, bad = "no path", True
                        else:
                            tr = f"{TO(t):.1f}"
                            bad |= TO(t) > mt
                    lim = f"{mx:g}" if mx is not None else ""
                    rows.append((ref, to, n, f"{d:.1f}", lim, tr + (f" / {mt:g}" if tr else ""), "FAIL" if bad else "ok"))
                    fails += bad
            if mg is not None and not placement:
                if gnd_graph is None:
                    gnd_graph = graph(b, GND, zones=False)
                    gnd_vias = [v.GetPosition() for v in b.GetTracks() if v.Type() == pcbnew.PCB_VIA_T and v.GetNetname() == GND]
                    gnd_zones = [z for z in b.Zones() if not z.GetIsRuleArea() and z.GetNetname() == GND]
                for p in pads:
                    if p.GetNetname() != GND:
                        continue
                    filled = any(z.IsOnLayer(l) and z.HitTestFilledArea(l, pcbnew.VECTOR2I(int(x), int(y)))
                                 for z in gnd_zones for l in p.GetLayerSet().Seq() for x, y in pad_points(p))
                    if filled:
                        d, how = min((TO(dist(p.GetPosition(), v)) for v in gnd_vias), default=math.inf), "fill"
                    else:
                        t = shortest(gnd_graph, [pad_id(p)], lambda node: node[0] == "via")
                        d, how = (math.inf, "no via path") if t is None else (TO(t), "track")
                    bad = d > mg
                    rows.append((ref, f"pad {p.GetNumber()}", f"GND via ({how})", f"{d:.1f}", f"{mg:g}", "", "FAIL" if bad else "ok"))
                    fails += bad
    if not n_rules:
        print(f"no rules in {rules}: add a row per part that must sit close to a pin")
    print("| Part | To | Net | Distance [mm] | Max [mm] | Track / max [mm] | Result |")
    print("|---|---|---|---|---|---|---|")
    for row in rows:
        if show_all or row[-1] != "ok":
            print("| " + " | ".join(row) + " |")
    print(f"{len(rows)} checks, {fails} failed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
