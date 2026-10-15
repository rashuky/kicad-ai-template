# Routing plan

Signals are routed by script, group by group. **No board autorouter.** The maze helper only routes the measured maze nets (hybrid). Base: the locked critical copper (stage 3).
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
3. Power trees, to every supply pin, and a GND fan-out for every GND pin.
4. Buses.
5. Locals.
6. Maze nets (hybrid only, see below).
7. GND: fan-out vias, pours, stitching.
8. Metrics: `tools/pcb/route_metrics.py <new board> <previous board>`, table into the PR.

DRC after each group: no new errors, the unconnected count only goes down. The GND pour pieces on the pour layer do not grow.

## Maze nets (hybrid)
Picked by `route_metrics.py --candidates <hand board> <maze board>`: signal nets with hand length ≥ 80 mm and hand / maze ≥ 1.15, no power class. Rerun after a placement change.

| Net | Hand length [mm] | Maze length [mm] | Hand / maze |
|---|---|---|---|
| | | | |

Maze settings: pour layer cost _x_, keep-out boxes _(where, why)_.

## Metrics
| Criterion | Previous | This board | Better |
|---|---|---|---|
| | | | |

## Progress
| Step | State | Snapshot |
|---|---|---|

Decisions taken while routing:
- _Every deviation from the plan, with the reason._
