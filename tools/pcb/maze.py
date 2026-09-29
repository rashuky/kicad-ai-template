"""Corridor maze helper for tight spots, called from a routing script (KiCad python + numpy).

Not an autorouter for the board: the caller picks the net order, the region (a box), the layers, the terminals
and the via cost. This module only finds the exact path inside that box on a 0.1 mm grid (A*, 8 directions,
F.Cu / B.Cu), clear of every other-net item, and draws it as locked tracks and vias.

Run with KiCad's python (pcbnew, numpy). From a routing script:
    sys.path.insert(0, "tools/pcb"); import maze
    ok = maze.connect(board, "/SDA", [(x1, y1, (pcbnew.F_Cu,)), (x2, y2, (pcbnew.F_Cu, pcbnew.B_Cu))],
                      (x0, y0, x1, y1), layers=(pcbnew.F_Cu, pcbnew.B_Cu), via_cost=3.0, forbid=[], clearance=0.2)
Terminals are joined in order as a tree. Returns False if no path fits (then change the box, order or layers).
"""
import heapq
import math
from array import array

import numpy as np
import pcbnew

MM, TO = pcbnew.FromMM, pcbnew.ToMM
F, B = pcbnew.F_Cu, pcbnew.B_Cu
LAYERS = (F, B)
G0 = 0.1                      # default grid step
CLR = 0.2                     # board clearance (default, override per call with clearance=)
GND_NET = "GND"               # its fill reflows around new copper, so it is not an obstacle
MARGIN = 0.03                 # rounding margin on top of the clearance


class Maze:
    def __init__(self, board, region, width=0.2, via_d=0.6, via_h=0.3, step=G0):
        self.b = board
        self.g = step
        self.x0, self.y0, self.x1, self.y1 = region
        self.nx = int(round((self.x1 - self.x0) / self.g)) + 1
        self.ny = int(round((self.y1 - self.y0) / self.g)) + 1
        self.w, self.vd, self.vh = width, via_d, via_h
        xs = self.x0 + np.arange(self.nx) * self.g
        ys = self.y0 + np.arange(self.ny) * self.g
        self.X, self.Y = np.meshgrid(xs, ys, indexing="xy")        # [iy, ix]

    # ------------------------------------------------------------------ obstacle maps
    def _dist_seg(self, ax, ay, bx, by, sl):
        X, Y = self.X[sl], self.Y[sl]
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        t = np.zeros_like(X) if L == 0 else np.clip(((X - ax) * dx + (Y - ay) * dy) / L, 0, 1)
        return np.hypot(X - (ax + t * dx), Y - (ay + t * dy))

    def _slice(self, x0, y0, x1, y1, grow):
        i0 = max(0, int(math.floor((x0 - grow - self.x0) / self.g)))
        i1 = min(self.nx, int(math.ceil((x1 + grow - self.x0) / self.g)) + 1)
        j0 = max(0, int(math.floor((y0 - grow - self.y0) / self.g)))
        j1 = min(self.ny, int(math.ceil((y1 + grow - self.y0) / self.g)) + 1)
        if i0 >= i1 or j0 >= j1:
            return None
        return (slice(j0, j1), slice(i0, i1))

    def build(self, netname, clr_to=None):
        """Distance-to-nearest-other-net-copper maps per layer (edge distance, mm), capped at 5 mm.
        clr_to: {other net: clearance} for nets that need more than the board clearance (FB vs SW)."""
        self.net = netname
        clr_to = clr_to or {}
        d = {l: np.full((self.ny, self.nx), 5.0) for l in LAYERS}
        own = {l: np.zeros((self.ny, self.nx), bool) for l in LAYERS}
        dvia = np.full((self.ny, self.nx), 5.0)          # vias only: own-net SMD pads (no via in pad), inner tracks
        grow = 1.5

        def put(layer, sl, dist, is_own, other=None):
            if other in clr_to:
                dist = dist - (clr_to[other] - CLR)
            if is_own:
                own[layer][sl] |= dist <= 0
            else:
                d[layer][sl] = np.minimum(d[layer][sl], dist)

        for fp in self.b.GetFootprints():
            for p in fp.Pads():
                bb = p.GetBoundingBox()
                x0, y0, x1, y1 = TO(bb.GetLeft()), TO(bb.GetTop()), TO(bb.GetRight()), TO(bb.GetBottom())
                sl = self._slice(x0, y0, x1, y1, grow)
                if sl is None:
                    continue
                X, Y = self.X[sl], self.Y[sl]
                if p.GetShape(F) == pcbnew.PAD_SHAPE_CIRCLE:
                    cx, cy, r = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2
                    dist = np.hypot(X - cx, Y - cy) - r
                else:
                    dist = np.hypot(np.maximum(np.maximum(x0 - X, X - x1), 0), np.maximum(np.maximum(y0 - Y, Y - y1), 0))
                is_own = p.GetNetname() == netname
                if is_own and p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
                    dvia[sl] = np.minimum(dvia[sl], dist)
                for l in LAYERS:
                    if p.IsOnLayer(l):
                        put(l, sl, dist, is_own, p.GetNetname())
                if p.GetDrillSizeX() > 0 and not is_own:              # holes block both layers
                    for l in LAYERS:
                        put(l, sl, dist, False)
        for t in self.b.GetTracks():
            is_own = t.GetNetname() == netname
            if t.Type() == pcbnew.PCB_VIA_T:
                cx, cy, r = TO(t.GetPosition().x), TO(t.GetPosition().y), TO(t.GetWidth(F)) / 2
                sl = self._slice(cx - r, cy - r, cx + r, cy + r, grow)
                if sl is None:
                    continue
                dist = np.hypot(self.X[sl] - cx, self.Y[sl] - cy) - r
                for l in LAYERS:
                    put(l, sl, dist, is_own, t.GetNetname())
            else:
                l = t.GetLayer()
                if l not in LAYERS:
                    if not is_own:                                    # In1 / In2 tracks block vias
                        ax, ay, bx, by = TO(t.GetStart().x), TO(t.GetStart().y), TO(t.GetEnd().x), TO(t.GetEnd().y)
                        hw = TO(t.GetWidth()) / 2
                        sl = self._slice(min(ax, bx), min(ay, by), max(ax, bx), max(ay, by), grow + hw)
                        if sl is not None:
                            dvia[sl] = np.minimum(dvia[sl], self._dist_seg(ax, ay, bx, by, sl) - hw)
                    continue
                ax, ay, bx, by = TO(t.GetStart().x), TO(t.GetStart().y), TO(t.GetEnd().x), TO(t.GetEnd().y)
                hw = TO(t.GetWidth()) / 2
                sl = self._slice(min(ax, bx), min(ay, by), max(ax, bx), max(ay, by), grow + hw)
                if sl is None:
                    continue
                put(l, sl, self._dist_seg(ax, ay, bx, by, sl) - hw, is_own, t.GetNetname())
        for z in self.b.Zones():
            bb = z.GetBoundingBox()
            sl = self._slice(TO(bb.GetLeft()), TO(bb.GetTop()), TO(bb.GetRight()), TO(bb.GetBottom()), 0.5)
            if sl is None:
                continue
            for l in LAYERS:
                if not z.IsOnLayer(l):
                    continue
                keep = z.GetIsRuleArea() and z.GetDoNotAllowTracks()
                if not keep and (z.GetIsRuleArea() or z.GetNetname() in (GND_NET, netname)):
                    continue                                          # GND fill flows around new copper
                reach = MM(CLR + self.vd / 2 + MARGIN)          # anything closer than this is marked as touching
                ys, xs = np.nonzero(np.ones_like(self.X[sl], bool))
                for jj, ii in zip(ys, xs):
                    j, i = jj + sl[0].start, ii + sl[1].start
                    pt = pcbnew.VECTOR2I(MM(float(self.X[j, i])), MM(float(self.Y[j, i])))
                    if keep:
                        near = z.Outline().Collide(pt, reach)
                    else:
                        near = z.HitTestFilledArea(l, pt, reach)
                    if near:
                        d[l][j, i] = 0.0
        self.d, self.own = d, own
        self.free_t = {l: d[l] >= CLR + self.w / 2 + MARGIN for l in LAYERS}
        self.free_v = d[F] >= CLR + self.vd / 2 + MARGIN
        self.free_v &= d[B] >= CLR + self.vd / 2 + MARGIN
        self.free_v &= dvia >= CLR + self.vd / 2 + MARGIN

    # ------------------------------------------------------------------ search
    def cell(self, x, y):
        return int(round((y - self.y0) / self.g)), int(round((x - self.x0) / self.g))

    def route(self, terminals, layers=(F, B), via_cost=3.0, layer_cost=None, forbid=(), hv=True):
        """terminals: list of (x, y, layerset). Connects them in order as a tree. Returns list of paths.
        forbid: boxes (x0, y0, x1, y1, layer) the path must not enter."""
        layer_cost = layer_cost or {F: 1.0, B: 1.0}
        self.hv = hv
        free = {l: self.free_t[l].copy() for l in layers}
        for fx0, fy0, fx1, fy1, fl in forbid:
            if fl in free:
                j0, i0 = self.cell(fx0, fy0); j1, i1 = self.cell(fx1, fy1)
                free[fl][max(j0, 0):j1 + 1, max(i0, 0):i1 + 1] = False
        self.exact = {}
        for x, y, ls in terminals:
            self.exact[self.cell(x, y)] = (x, y)
        tree = set()
        for x, y, ls in terminals[:1]:
            j, i = self.cell(x, y)
            for l in ls:
                if l in free:
                    tree.add((l, j, i))
        paths = []
        for x, y, ls in terminals[1:]:
            tj, ti = self.cell(x, y)
            goal = {(l, tj, ti) for l in ls if l in free}
            path = self._astar(tree, goal, free, via_cost, layer_cost, (tj, ti))
            if path is None:
                return None
            paths.append(path)
            tree |= set(path)
        return paths

    def _astar(self, starts, goals, free, via_cost, layer_cost, target):
        """A* over (layer, j, i, direction). A change of direction costs TURN, so paths come out as few long
        straight runs instead of staircases. State arrays are flat Python arrays (fast scalar access)."""
        TURN = 0.6
        W = 1.2                       # weighted Manhattan bound: not admissible, paths up to ~20 % longer, much faster
        tj, ti = target
        nx, ny = self.nx, self.ny
        lays = list(free)
        li = {l: n for n, l in enumerate(lays)}
        ncell = ny * nx
        fr = [bytes(free[l].astype(np.uint8).ravel()) for l in lays]
        fv = bytes(self.free_v.astype(np.uint8).ravel())
        size = len(lays) * ncell * 9
        gbest = array("d", [math.inf]) * size
        came = array("q", [-1]) * size
        g = self.g
        goalset = {li[l] * ncell + j * nx + i for l, j, i in goals if l in li}
        steps = []
        for k, (dj, di, c) in enumerate([(0, 1, 1.0), (1, 0, 1.0), (0, -1, 1.0), (-1, 0, 1.0),
                                         (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142)]):
            steps.append((k, dj, di, c))
        cost = {}
        for l in lays:
            for k, dj, di, c in steps:
                kk = 1.0
                if self.hv:                   # plan layer rules: F.Cu runs N-S, B.Cu runs E-W, diagonals only short
                    if dj and di:
                        kk = 1.8
                    elif (l == F and di) or (l == B and dj):
                        kk = 2.2
                cost[li[l], k] = c * kk * g * layer_cost[l]
        openl = []
        for l, j, i in starts:
            if l in li:
                s_ = ((li[l] * ncell + j * nx + i) * 9) + 8
                gbest[s_] = 0.0
                heapq.heappush(openl, (W * g * (abs(j - tj) + abs(i - ti)), 0.0, s_))
        while openl:
            _, gc, st = heapq.heappop(openl)
            if gc > gbest[st]:
                continue
            cellid, d = divmod(st, 9)
            a, rest = divmod(cellid, ncell)
            j, i = divmod(rest, nx)
            if cellid in goalset:
                out, cur = [], st
                while cur >= 0:
                    cid = cur // 9
                    aa, rr = divmod(cid, ncell)
                    out.append((lays[aa], rr // nx, rr % nx))
                    cur = came[cur]
                return out[::-1]
            fa = fr[a]
            base = a * ncell
            for k, dj, di, c in steps:
                nj, ni = j + dj, i + di
                if nj < 0 or nj >= ny or ni < 0 or ni >= nx:
                    continue
                nc = base + nj * nx + ni
                if not fa[nj * nx + ni] and nc not in goalset:
                    continue
                if dj and di and not (fa[j * nx + ni] and fa[nj * nx + i]):   # no corner cutting
                    continue
                ng = gc + cost[a, k] + (TURN if d != 8 and d != k else 0.0)
                ns = nc * 9 + k
                if ng < gbest[ns]:
                    gbest[ns] = ng; came[ns] = st
                    heapq.heappush(openl, (ng + W * g * (abs(nj - tj) + abs(ni - ti)), ng, ns))
            if fv[j * nx + i]:
                for b2 in range(len(lays)):
                    nc = b2 * ncell + j * nx + i
                    if b2 == a or not (fr[b2][j * nx + i] or nc in goalset):
                        continue
                    ng = gc + via_cost
                    ns = nc * 9 + 8
                    if ng < gbest[ns]:
                        gbest[ns] = ng; came[ns] = st
                        heapq.heappush(openl, (ng + W * g * (abs(j - tj) + abs(i - ti)), ng, ns))
        return None

    # ------------------------------------------------------------------ output
    def draw(self, paths, netname):
        n = self.b.FindNet(netname)
        for path in paths:
            # split into same-layer runs of grid cells, place vias at layer changes
            run = [path[0]]
            for p in path[1:]:
                if p[0] != run[-1][0]:
                    self._seg(run, n)
                    x, y = self._xy(p)
                    v = pcbnew.PCB_VIA(self.b)
                    v.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
                    v.SetWidth(F, MM(self.vd)); v.SetDrill(MM(self.vh)); v.SetNet(n); v.SetLocked(True)
                    self.b.Add(v)
                    run = [p]
                else:
                    run.append(p)
            self._seg(run, n)

    def _xy(self, cell):
        """Grid cell to mm, snapped to the exact terminal coordinate when the cell is a terminal."""
        l, j, i = cell
        return self.exact.get((j, i), (self.x0 + i * self.g, self.y0 + j * self.g))

    def _seg(self, run, n):
        if len(run) < 2:
            return
        keep = [run[0]]                                  # keep only the cells where the grid step changes
        for a, b_, c in zip(run, run[1:], run[2:]):
            if (b_[1] - a[1], b_[2] - a[2]) != (c[1] - b_[1], c[2] - b_[2]):
                keep.append(b_)
        keep.append(run[-1])
        for c1, c2 in zip(keep, keep[1:]):
            (x1, y1), (x2, y2) = self._xy(c1), self._xy(c2)
            t = pcbnew.PCB_TRACK(self.b)
            t.SetStart(pcbnew.VECTOR2I(MM(x1), MM(y1))); t.SetEnd(pcbnew.VECTOR2I(MM(x2), MM(y2)))
            t.SetWidth(MM(self.w)); t.SetLayer(c1[0]); t.SetNet(n); t.SetLocked(True)
            self.b.Add(t)


def connect(board, netname, terminals, region, **kw):
    """Build the maps for one net, route, draw. Returns True on success."""
    global CLR
    CLR = kw.pop("clearance", CLR)
    width = kw.pop("width", 0.2)
    step = kw.pop("step", G0)
    m = Maze(board, region, width=width, step=step)
    m.build(netname, kw.pop("clr_to", None))
    paths = m.route(terminals, **kw)
    if paths is None:
        return False
    m.draw(paths, netname)
    return True
