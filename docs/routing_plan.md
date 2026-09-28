# Routing plan

Signals are routed by script, group by group. **No autorouter.** Base: the locked critical copper (stage 3).
Rules: `docs/layout_rules.md`, the project `.kicad_dru`.

![Routing corridors](img/routing_plan.png)

_Legend: colours per layer, numbers match the table. A corridor may move 1 to 2 mm when its group is routed._

## Layer rules
- **Top:** escapes, short local links, N-S runs, power trees.
- **Bottom:** long E-W runs and every crossing of top-layer power.
- **Vias:** signal 0.6/0.3 mm, never in pads.
- **Inner layers:** solid GND. Islands only where no bottom-layer signal crosses the edge.
- **Keep-outs:** mounting holes, rule areas.

## Groups and corridors
| # | Nets | Corridor | Layer |
|---|---|---|---|
| 1 | | | |

## Fine-pitch escapes
| IC | Pins | Nets | Escape (layer, direction, via position) |
|---|---|---|---|
| | | | |

## Order
1. Critical copper (done in stage 3).
2. Dense escapes.
3. Power trees.
4. Buses.
5. Locals.
6. GND: fan-out vias, pours, stitching.

DRC after each group: no new errors, the unconnected count only goes down.

## Progress
| Step | State | Snapshot |
|---|---|---|

Decisions taken while routing:
- _Every deviation from the plan, with the reason._
