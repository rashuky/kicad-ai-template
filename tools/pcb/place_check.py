"""Proximity check (KiCad python): parts that must sit close to a pin, from a rules table.
usage: "C:/Program Files/KiCad/10.0/bin/python.exe" tools/pcb/place_check.py <board.kicad_pcb> [<rules.csv>] [--placement] [--all]

Rules: docs/place_rules.csv (default), one row per part group, from docs/layout_rules.md and the datasheets:
  parts        refs that must sit close, separated by spaces (e.g. "C104 C105")
  to           the ref they belong to (IC, connector). Empty: only the GND via check
  max_mm       largest centre distance between a pad of the part and a pad of `to` on the same net [mm]
  max_track_mm largest track path between those pads, through tracks and vias [mm]. Empty: not checked.
               A net joined by a pour instead of tracks passes when one filled zone of the net covers both pads
  gnd_via_mm   largest distance from each GND pad of the part to the nearest GND via [mm]. Empty: not checked
  to_pads      pad numbers of `to` to measure to (e.g. "2" for a cap at one of two supply pins). Empty: all pads
  nets         nets to check (globs, separated by spaces). Empty: every net the two share except GND
  why          the rule's source (datasheet section, layout_rules.md line)
Example rows:
  C3 C4,U1,,2.5,3,2,,buck datasheet 10.1: input caps at VIN / PGND
  C7,U2,24,3.5,4,1.5,,100 nF at VCCP pin 24 (to_pads: the cap belongs to one of two supply pins)
  C5,U1,,3,3,,/BOOT,boot cap: only the boot net (its other pad is SW)
  U5,J3,,7,15,1.5,/USB_*,ESD next to the connector pins, GND via at the pad
The track path runs between the first track points inside each pad, so it can be a little shorter than the centre distance.
--placement skips the track and via checks (board before routing). --all also prints the rows that pass.
Exits 1 if a rule fails. Run it after placement and as a routing chain step.
"""
import csv
import fnmatch
import heapq
import math
import os
import sys

import pcbnew

TO, MM = pcbnew.ToMM, pcbnew.FromMM
TOL = MM(0.01)                                   # a track end this close to another track joins it


def dist(a, b):
    a, b = [(v.x, v.y) if hasattr(v, "x") else v for v in (a, b)]
    return math.hypot(a[0] - b[0], a[1] - b[1])


def graph(b, net):
    """Track graph of one net: nodes are points [nm], edges track pieces and via joins."""
    segs = [((t.GetStart().x, t.GetStart().y), (t.GetEnd().x, t.GetEnd().y))
            for t in b.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T and t.GetNetname() == net]
    vias = [(v.GetPosition().x, v.GetPosition().y, v.GetWidth(pcbnew.F_Cu) / 2)
            for v in b.GetTracks() if v.Type() == pcbnew.PCB_VIA_T and v.GetNetname() == net]
    ends = {p for s in segs for p in s}
    pads = [p for f in b.GetFootprints() for p in f.Pads() if p.GetNetname() == net]
    adj = {}

    def edge(p, q, w):
        adj.setdefault(p, []).append((q, w))
        adj.setdefault(q, []).append((p, w))
    for a, c in segs:                            # split each segment at the track ends that touch it (T joins)
        L = dist(a, c)
        pts = [(0.0, a), (L, c)]
        for p in ends:
            if p in (a, c) or L == 0:
                continue
            u = ((p[0] - a[0]) * (c[0] - a[0]) + (p[1] - a[1]) * (c[1] - a[1])) / L
            if 0 < u < L and abs((p[0] - a[0]) * (c[1] - a[1]) - (p[1] - a[1]) * (c[0] - a[0])) / L < TOL:
                pts.append((u, p))
        for pd in pads:                          # a track that runs through a pad joins it there
            if L == 0:
                break
            m = pd.GetPosition()
            u = max(0.0, min(L, ((m.x - a[0]) * (c[0] - a[0]) + (m.y - a[1]) * (c[1] - a[1])) / L))
            p = (round(a[0] + (c[0] - a[0]) * u / L), round(a[1] + (c[1] - a[1]) * u / L))
            if 0 < u < L and pd.HitTest(pcbnew.VECTOR2I(*p)):
                pts.append((u, p))
        pts.sort()
        for (u0, p0), (u1, p1) in zip(pts, pts[1:]):
            edge(p0, p1, u1 - u0)
    for x, y, r in vias:                         # a via joins every track end inside its pad
        for p in ends:
            if dist(p, (x, y)) <= r:
                edge((x, y), p, 0.0)
    return adj


def track_path(adj, pads_a, pads_b):
    """Shortest track path [nm] from any pad in pads_a to any pad in pads_b, None if there is none."""
    hit = lambda pads, p: any(pd.HitTest(pcbnew.VECTOR2I(int(p[0]), int(p[1]))) for pd in pads)
    best = {p: 0.0 for p in adj if hit(pads_a, p)}
    q = [(0.0, p) for p in best]
    heapq.heapify(q)
    while q:
        d, p = heapq.heappop(q)
        if d > best.get(p, math.inf):
            continue
        if hit(pads_b, p):
            return d
        for n, w in adj[p]:
            if d + w < best.get(n, math.inf):
                best[n] = d + w
                heapq.heappush(q, (d + w, n))
    return None


def poured(b, net, pads):
    """One filled zone of the net covers every pad in pads."""
    for z in b.Zones():
        if z.GetIsRuleArea() or z.GetNetname() != net:
            continue
        if all(any(z.IsOnLayer(l) and z.HitTestFilledArea(l, pd.GetPosition()) for l in pd.GetLayerSet().Seq()) for pd in pads):
            return True
    return False


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    placement, show_all = "--placement" in sys.argv, "--all" in sys.argv
    path = args[0]
    rules = args[1] if len(args) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "place_rules.csv")
    b = pcbnew.LoadBoard(path)
    if not placement:
        pcbnew.ZONE_FILLER(b).Fill([z for z in b.Zones() if not z.GetIsRuleArea()])
    fp = {f.GetReference(): f for f in b.GetFootprints()}
    gnd_vias = [(v.GetPosition().x, v.GetPosition().y) for v in b.GetTracks()
                if v.Type() == pcbnew.PCB_VIA_T and v.GetNetname() == "GND"]
    graphs, rows, fails = {}, [], 0
    for r in csv.DictReader(open(rules, encoding="utf-8")):
        to = r["to"].strip()
        num = lambda k: float(r[k]) if r.get(k, "").strip() else None
        mx, mt, mg = num("max_mm"), num("max_track_mm"), num("gnd_via_mm")
        globs = r.get("nets", "").split()
        to_pads = set(r.get("to_pads", "").split())
        for ref in r["parts"].split():
            if ref not in fp or (to and to not in fp):
                rows.append((ref, to, "", "", "", "", "missing part")); fails += 1
                continue
            pads = list(fp[ref].Pads())
            if to:
                other = [p for p in fp[to].Pads() if not to_pads or p.GetNumber() in to_pads]
                nets = sorted({p.GetNetname() for p in pads} & {p.GetNetname() for p in other} - {"", "GND"})
                if globs:
                    nets = [n for n in nets if any(fnmatch.fnmatchcase(n, g) for g in globs)]
                if not nets:
                    rows.append((ref, to, "", "", "", "", "no shared net")); fails += 1
                for n in nets:
                    pa = [p for p in pads if p.GetNetname() == n]
                    pb = [p for p in other if p.GetNetname() == n]
                    d = min(TO(dist(p.GetPosition(), q.GetPosition())) for p in pa for q in pb)
                    bad = mx is not None and d > mx
                    tr = ""
                    if mt is not None and not placement:
                        adj = graphs.setdefault(n, graph(b, n))
                        t = track_path(adj, pa, pb)
                        if t is not None:
                            tr = f"{TO(t):.1f}"
                            bad |= TO(t) > mt
                        elif poured(b, n, pa + pb):
                            tr = "pour"
                        else:
                            tr = "no path"
                            bad = True
                    rows.append((ref, to, n, f"{d:.1f}", f"{mx:g}" if mx is not None else "", tr + (f" / {mt:g}" if mt is not None and tr else ""),
                                 "FAIL" if bad else "ok"))
                    fails += bad
            if mg is not None and not placement:
                for p in pads:
                    if p.GetNetname() != "GND":
                        continue
                    d = min((TO(dist(p.GetPosition(), v)) for v in gnd_vias), default=math.inf)
                    bad = d > mg
                    rows.append((ref, f"pad {p.GetNumber()}", "GND via", f"{d:.1f}", f"{mg:g}", "", "FAIL" if bad else "ok"))
                    fails += bad
    print("| Part | To | Net | Distance [mm] | Max [mm] | Track / max [mm] | Result |")
    print("|---|---|---|---|---|---|---|")
    for row in rows:
        if show_all or row[-1] != "ok":
            print("| " + " | ".join(row) + " |")
    if not rows:
        print(f"no rules in {rules}: add a row per part that must sit close to a pin")
    print(f"{len(rows)} checks, {fails} failed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
