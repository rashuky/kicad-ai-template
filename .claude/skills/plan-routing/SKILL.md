---
name: plan-routing
description: Plan and route a placed PCB without an autorouter. Corridors and layers per signal group in docs/routing_plan.md with a snapshot, then routing by script group by group with DRC after each. Use after placement and critical copper are done.
---

# Plan and route a PCB

**Never run a board autorouter.** Every group is planned, then drawn by script. The maze helper only runs inside a box you give it, or on the nets the hybrid rule picks (section 3).

## 1. Plan (then stop for the user's approval)
1. Dump the unrouted nets with their pad positions (KiCad python) and render the placed board (`pcb_render`).
2. Group the nets: power trees, each bus, the escapes of each fine-pitch IC, locals, GND. A power tree lists every supply pin it feeds (ESD VCC pins, pull-up rails, sensor rails), not just the big loads. Plan a GND fan-out path for every GND pin.
3. Per group: corridor (a band on the board), layer, where it changes layer. One direction per outer layer (e.g. top N-S, bottom E-W).
4. Walk every crossing between groups. Two groups on the same layer must not cross. List each hop.
5. Fine-pitch ICs: a pin table with side, layer, direction and via position for every pin. Vias under the body in staggered columns work well for TSSOP and QFN.
6. Inner-layer islands only where no outer-layer signal crosses their edge.
7. Keep-outs: mounting holes, rule areas, voids in the planes.
8. Interchangeable channels (ESD arrays, buffers): pick the pin order against the connector so the bus does not cross itself.
9. The edge bands (between the outline and the first row of parts) are often the only free corridor for long runs. Reserve them in the plan.
10. Write `docs/routing_plan.md` (template in `docs/`). Draw the corridors with `tools/pcb/plan_overlay.py` into `docs/img/routing_plan.png`.
11. Review agent on the plan (crossings, missing nets, keep-outs). Fix, commit, PR. **Wait for the user to say start.**

## 2. Route
- One script chain, rerunnable from the placed board: the first script clears all tracks. Every item is locked.
- Order: dense escapes, power trees, buses, locals, hybrid maze nets, GND (fan-out vias, pours, stitching, a via in every pour island).
- Explicit coordinates where the geometry is simple. Where a group is a knot (pin order reversed, many crossings), use `tools/pcb/maze.py` with a box, a net order, allowed layers and keep-out boxes that you choose. Draw fixed stubs out of fine-pitch ICs first so the helper starts from the planned exits.
- Order inside it: power trees reach every supply pin and every GND pin has its fan-out before any signal block is drawn. Signal blocks drawn first box them in.
- Hand blocks assert their anchor pad positions first: coordinates are absolute, so a placement change must fail loudly.
- After each group: `tools/pcb/drc_summary.py` (0 errors, unconnected only goes down), the GND pour pieces on the pour layer (`tools/pcb/route_metrics.py`, the count must not grow), a look at a render, commit, review agent. Fix its findings before the next group.
- Pour split: move one track at a time off the pour layer (to an inner layer), refill and measure the gain. The tracks with the biggest gain go to the signal layer or get a short hop.
- Before the metrics: `tools/pcb/place_check.py <board>` (decoupling, boot, FB, sense filters, ESD: pad distance, track path, GND via). It must pass.
- The last chain step is `tools/pcb/route_metrics.py <new board> <previous board>`. The table goes in the PR.
- Snapshots (`tools/pcb/snapshot.py`, then `pcb_render`) after the escapes, after the buses and at the end, into `docs/img/`. Update the Progress table and log every deviation from the plan.

## 3. Hybrid pass (optional, after the hand version passes)
1. Build a maze copy from the same placed board (`ROUTE_MODE=maze`: escapes only, the maze routes the rest). It is a measuring copy, never committed.
2. `route_metrics.py --candidates <hand board> <maze board>` lists the long signal nets the hand route detours on. Only those go to the maze in `ROUTE_MODE=hybrid`. The list is board specific.
3. Maze step: pour layer cost raised, keep-out boxes for local rules, each maze net checked by its own copper islands (DRC can miss an open net). The script fails on any open link.
4. Compare hand and hybrid with `route_metrics.py` (one column each). Keep the hybrid only if it wins on the table. Hand and hybrid are each a stacked PR.

## 4. Done when
DRC 0 errors, 0 unconnected, parity 0, zones filled, silkscreen findings no worse than before routing, metrics table in the PR.
