---
name: plan-routing
description: Plan and route a placed PCB without an autorouter. Corridors and layers per signal group in docs/routing_plan.md with a snapshot, then routing by script group by group with DRC after each. Use after placement and critical copper are done.
---

# Plan and route a PCB

**Never run an autorouter.** Every group is planned, then drawn by script.

## 1. Plan (then stop for the user's approval)
1. Dump the unrouted nets with their pad positions (KiCad python) and render the placed board (`pcb_render`).
2. Group the nets: power trees, each bus, the escapes of each fine-pitch IC, locals, GND.
3. Per group: corridor (a band on the board), layer, where it changes layer. One direction per outer layer (e.g. top N-S, bottom E-W).
4. Walk every crossing between groups. Two groups on the same layer must not cross. List each hop.
5. Fine-pitch ICs: a pin table with side, layer, direction and via position for every pin. Vias under the body in staggered columns work well for TSSOP and QFN.
6. Inner-layer islands only where no outer-layer signal crosses their edge.
7. Keep-outs: mounting holes, rule areas, voids in the planes.
8. Write `docs/routing_plan.md` (template in `docs/`). Draw the corridors with `tools/pcb/plan_overlay.py` into `docs/img/routing_plan.png`.
9. Review agent on the plan (crossings, missing nets, keep-outs). Fix, commit, PR. **Wait for the user to say start.**

## 2. Route
- One script chain, rerunnable from the placed board: the first script clears all tracks. Every item is locked.
- Order: dense escapes, power trees, buses, locals, GND (fan-out vias, pours, stitching, a via in every pour island).
- Explicit coordinates where the geometry is simple. Where a group is a knot (pin order reversed, many crossings), use `tools/pcb/maze.py` with a box, a net order, allowed layers and keep-out boxes that you choose. Draw fixed stubs out of fine-pitch ICs first so the helper starts from the planned exits.
- After each group: `tools/pcb/drc_summary.py` (0 errors, unconnected only goes down), a look at a render, commit, review agent. Fix its findings before the next group.
- Snapshots (`tools/pcb/snapshot.py`, then `pcb_render`) after the escapes, after the buses and at the end, into `docs/img/`. Update the Progress table and log every deviation from the plan.

## 3. Done when
DRC 0 errors, 0 unconnected, parity 0, zones filled, silkscreen findings no worse than before routing.
