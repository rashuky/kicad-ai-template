"""Product cost in PLN: what one complete unit costs, at the cheapest suppliers, and where to save.
usage: python tools/bom_cost.py [--units 1,5,10] [--detail 5] [--offline] [--refresh] [--no-board] [--project kicad/]
                               [--skip-shop TME]
       python tools/bom_cost.py --order out/order.csv [--out out]     (ad hoc order, written outside the repo)

Inputs (hand-kept, in bom/):
- purchase.csv: every part of a unit besides the JLCPCB board. Status: use (part of the product) or option
  (alternative, not counted, compared under "Where to save"). Function links an option to the part it can replace.
  Qty_per_unit is the amount one unit uses. Equipment rows are counted once, not per unit. Refs names schematic
  parts fitted by hand: they are left out of the JLCPCB board parts.
- shops.csv: shipping to Poland per shop, free-shipping threshold (gross), delivery time.
- orders.csv: placed JLCPCB orders. An Amount replaces the board estimate at that board count.

Product cost (default): for each batch size in --units, every use row is bought for the whole batch
(Qty_per_unit x units, rounded up to whole pieces), at the cheapest combination of shops including shipping. The
batch total divided by the units is the cost per unit. Outputs, committed so the cost history is in git:
- bom/cost.md: cost per unit per batch size, what is not counted yet, the most expensive items, where to save
  (cheaper options with their effect on the whole batch including shipping, batch size, prices to verify, board),
  every item with its supplier, distributor quotes, checks.
- bom/cost.xlsx: the same tables (needs openpyxl). bom/board_bom.csv: the priced board BOM at --detail boards.

Ad hoc order (--order FILE): a CSV with Item and Qty columns (Item = a part number, or the start of an Item name in
purchase.csv). Writes order.md and order.xlsx (shopping list per shop, links) and order_list.csv to --out (default out/,
git-ignored). Nothing in bom/ changes.

Updated on every run: JLCPCB board prices (no key), NBP exchange rates, distributor quotes from TME, Farnell PL,
Mouser and DigiKey PL by part number, then by the row's search words (tools/suppliers.py, API keys in bom/README.md).
Answers are cached in out/bom_cache.json for 7 days. --refresh ignores the cache, --offline uses it only.
"""
import argparse
import collections
import copy
import csv
import datetime
import html
import itertools
import math
import os
import sys
import time

import bom as bx
import suppliers as sp

BOM = os.path.join(bx.ROOT, "bom")
VAT = 1.23
JLC_FIXED_EST_USD = 100     # PCB, stencil, setup, assembly and shipping per JLCPCB order (EST, set from a real quote)
STALE_DAYS = 90
FX_FALLBACK = {"USD": 3.65, "EUR": 4.25}
STATUS = ("use", "option")
GROUPS = ["Board", "Modules", "Power", "Loads", "Sensors", "Wiring", "Mechanical", "Equipment"]   # Group values, edit per project
DISTRIBUTORS = list(sp.SEARCH)
NOT_COUNTED = ""            # parts not in purchase.csv yet, e.g. "enclosure (not designed yet)". Shown in cost.md
NO_SHOP = "shop not chosen"
SKIP = set()                                     # --skip-shop: shops left out of every order


def read(name):
    with open(os.path.join(BOM, name), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fnum(s):
    return float(s) if str(s).strip() else 0.0


def short(r):
    return r["Item"].split(",")[0]


def md(s):
    """Text for a Markdown table cell."""
    return html.unescape(str(s or "")).replace("|", "\\|").replace("\n", " ")


def units_label(u):
    return f"{u} unit" if u == 1 else f"{u} units"


def zl(x):
    return f"{x:,.2f}".replace(",", " ")


def nbp(cur):
    d = bx.http(f"https://api.nbp.pl/api/exchangerates/rates/a/{cur.lower()}/?format=json")
    return {"mid": d["rates"][0]["mid"], "date": d["rates"][0]["effectiveDate"]}


def rates(cache):
    fx, notes = {"PLN": 1.0}, []
    for cur in ("USD", "EUR"):
        r = cache.get(f"NBP:{cur}", lambda cur=cur: nbp(cur))
        fx[cur] = r.get("mid") or FX_FALLBACK[cur]
        notes.append(f"1 {cur} = {fx[cur]:.4f} PLN ({'NBP ' + r['date'] if 'mid' in r else 'fallback, ' + r.get('error', '')})")
    return fx, ", ".join(notes)


# ------------------------------------------------------------------ board
def board_lines(cache, hand_refs):
    rows, *_ = bx.read_schematic()
    lines = []
    for ln in bx.group(rows):
        refs = [r for r in ln["refs"] if r not in hand_refs]
        if ln["dnp"] or not refs:
            continue
        ln = dict(ln, refs=refs, qty=len(refs))
        if ln["lcsc"]:
            ln["jlc"] = cache.get(f"JLC:{ln['lcsc']}", lambda lcsc=ln["lcsc"]: bx.jlc(lcsc))
        lines.append(ln)
    return lines


def board_cost(lines, n, fx, orders):
    """Board per unit [PLN] for a batch of n boards: the placed order at that board count, else the estimate."""
    parts = sum((bx.jlc_line(ln, n) or (0, 0, 0))[2] for ln in lines)
    ext = sum(1 for ln in lines if (ln.get("jlc") or {}).get("library") == "extended")
    b = {"n": n, "parts_usd": parts, "ext": ext, "fixed_usd": JLC_FIXED_EST_USD,
         "pln": (parts + 3 * ext + JLC_FIXED_EST_USD) * VAT / n * fx["USD"],
         "unpriced": [ln for ln in lines if not (ln.get("jlc") or {}).get("breaks")]}
    order = next((o for o in orders if o["Shop"] == "JLCPCB" and o["Amount"].strip() and int(o["Boards"]) == n), None)
    if order:
        b["pln"] = fnum(order["Amount"]) * fx[order["Currency"]] / n
        b["src"] = f'order {order["Order"]}: {order["Amount"]} {order["Currency"]} / {n} boards'
    else:
        b["src"] = (f"EST: JLCPCB parts ${parts:.2f} (live) + {ext} extended lines x $3 + ${JLC_FIXED_EST_USD} PCB, "
                    f"assembly and shipping (EST), +23 % VAT, / {n} boards")
    return b


def write_board_csv(lines, n):
    with open(os.path.join(BOM, "board_bom.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["Refs", "Qty_per_board", "Value", "Footprint", "Manufacturer", "MPN", "LCSC", "JLC_library",
                    f"JLC_unit_USD_at_{n}_boards", "JLC_line_USD_per_board"])
        for ln in lines:
            j, jl = ln.get("jlc") or {}, bx.jlc_line(ln, n)
            w.writerow([" ".join(ln["refs"]), ln["qty"], ln["value"], ln["footprint"], ln["manufacturer"], ln["mpn"],
                        ln["lcsc"], j.get("library") or j.get("error", ""),
                        f"{jl[1]:.4f}" if jl else "", f"{jl[1] * ln['qty']:.4f}" if jl else ""])


# ------------------------------------------------------------------ parts
def quotes(cache, r, q, fx):
    """Best quote per distributor at quantity q, gross PLN. First by part number (a~b: equivalent numbers). When no
    distributor knows the part number, by the row's search words, keeping offers that hold every Must term."""
    found, how = {}, "not found"
    mpns = [m.strip() for m in r["MPN"].split("~") if m.strip()]

    def by_mpns(s, prefix=False):
        res = [sp.by_mpn(cache, s, m, r["Manufacturer"], prefix=prefix) for m in mpns]
        offers = [o for x in res for o in x.get("offers", [])]
        return {"offers": offers} if offers else res[0]

    if mpns:
        found, how = {s: by_mpns(s) for s in DISTRIBUTORS}, "part number"
        if not any("offers" in x for x in found.values()):    # no shop has the exact number: packaging variants
            found, how = {s: by_mpns(s, prefix=True) for s in DISTRIBUTORS}, "part prefix"
    if not any("offers" in x for x in found.values()):
        how = "not found"
        if r["Search"].strip():
            found = {s: sp.by_keywords(cache, s, r["Search"], r["Must"].split("|")) for s in DISTRIBUTORS}
            how = "search"
    r["match"] = how
    out = []
    for s, x in found.items():
        best = None
        for o in x.get("offers", []):
            if o["currency"] not in fx:
                continue
            oq, unit, line = bx.eu_order(q, o["breaks"], o["moq"], o["mult"])
            k = fx[o["currency"]] * VAT
            short_ = o["stock"] is not None and o["stock"] < oq
            c = {"shop": s, "qty": oq, "each": unit * k, "line": line * k, "stock": o["stock"], "link": o["url"],
                 "mpn": o["mpn"], "maker": o["maker"], "desc": o["desc"], "moq": o["moq"],
                 "error": "stock short" if short_ else "",
                 "check": f'{o["mpn"]} ({o["maker"]}): {o["desc"]}' if how != "part number" else ""}
            if best is None or (short_, c["line"], c["moq"]) < (bool(best["error"]), best["line"], best["moq"]):
                best = c                                 # in stock first, then the cheapest, then the smaller minimum
        out.append(best or {"shop": s, "error": x.get("error") or "no price"})
    return out


def load(cache, fx, qty_of):
    """purchase.csv rows with the CSV price in PLN, the quantity to buy (qty_of(row), 0 = not bought) and quotes."""
    rows, today = read("purchase.csv"), datetime.date.today()
    for i, r in enumerate(rows):
        r["_i"] = i                                  # row position, the key of an ad hoc order line
        r["qg"] = fnum(r["Qty_per_unit"])
        r["qn"] = qty_of(r)
        r["each"] = fnum(r["Price"]) * fx[r["Currency"]] if r["Price"].strip() and r["Currency"] in fx else None
        r["Shop"] = r["Shop"] or NO_SHOP                # no supplier named: a price estimate, no shipping counted
        r["src"], r["csv_shop"], r["csv_each"] = r["Price_src"], r["Shop"], r["each"]
        r["quotes"], r["match"], r["check"] = [], "", ""
        if r["qn"] and (r["MPN"].strip() or r["Search"].strip()):
            r["quotes"] = quotes(cache, r, r["qn"], fx)
        if any(x["shop"] == r["Shop"] and not x["error"] and not x["check"] for x in r["quotes"]):
            r["each"] = None                         # a live quote of the part from the same shop replaces the hand-kept price
        try:
            r["age"] = (today - datetime.date.fromisoformat(r["Price_date"])).days
        except ValueError:
            r["age"] = None
    return rows


def ship_cost(shops, shop, goods):
    if not shop or shop == NO_SHOP:              # no supplier named: a price estimate only
        return 0.0
    s = shops.get(shop)
    if s is None or goods <= 0:
        return None if s is None else 0.0
    return 0.0 if s["Free_from_PLN"].strip() and goods >= fnum(s["Free_from_PLN"]) else fnum(s["Shipping_PLN"])


def choose(rows, shops):
    """Pick the shop of every bought row (qn > 0) so that goods + shipping of the whole order is lowest.
    Candidates: the CSV shop at the CSV price and every distributor quote with enough stock.
    1. Every set of optional shops to open (shops of fixed rows are open anyway, there are only a few shops): each
       row takes its cheapest candidate among the open shops. The cheapest set wins.
    2. Single rows move to another candidate while that lowers the total (free-shipping thresholds)."""
    flex = []
    for r in rows:
        if not r["qn"]:
            continue
        cands = [{"shop": r["Shop"], "qty": r["qn"], "each": r["each"], "line": r["qn"] * r["each"], "link": r["Link"],
                  "src": r["Price_src"], "check": ""}] if r["each"] is not None and r["Shop"] not in SKIP else []
        cands += [dict(x, src=x["shop"] + (" search" if x["check"] else " API")) for x in r["quotes"]
                  if not x["error"] and x["shop"] not in SKIP]
        if cands and (len(cands) > 1 or r["each"] is None or r["Shop"] in SKIP):
            flex.append((r, cands))
        elif not cands:
            r["Shop"], r["check"] = "no source", f'no shop found{" besides " + r["Shop"] if r["Shop"] else ""}'
    base, ids = collections.Counter(), {id(r) for r, _ in flex}
    for r in rows:
        if r["qn"] and id(r) not in ids and r["Shop"] != "no source":
            base[r["Shop"]] += r["qn"] * (r["each"] or 0)
    if not flex:
        return

    def total(pick):
        goods = base.copy()
        for (_, cands), k in zip(flex, pick):
            goods[cands[k]["shop"]] += cands[k]["line"]
        ships = [ship_cost(shops, s, g) for s, g in goods.items()]
        return math.inf if None in ships else sum(goods.values()) + sum(ships)

    optional = sorted({c["shop"] for _, cands in flex for c in cands} - set(base))
    best, best_total = None, math.inf
    for n in range(len(optional) + 1):
        for extra in itertools.combinations(optional, n):
            open_ = set(base) | set(extra)
            pick = []
            for _, cands in flex:
                ks = [k for k, c in enumerate(cands) if c["shop"] in open_]
                if not ks:
                    break
                pick.append(min(ks, key=lambda k: cands[k]["line"]))
            else:
                t = total(pick)
                if t < best_total:
                    best, best_total = pick, t
    improved = best is not None
    while improved:                                  # single moves, e.g. to reach a free-shipping threshold
        improved = False
        for i, (_, cands) in enumerate(flex):
            for k in range(len(cands)):
                trial = best[:i] + [k] + best[i + 1:]
                t = total(trial)
                if t < best_total - 0.005:
                    best, best_total, improved = trial, t, True
    if best is None:
        missing = sorted({s for _, cands in flex for c in cands for s in [c["shop"]] if s not in shops} | set(base) - set(shops))
        print(f"  no shop combination priced: shops missing from shops.csv: {', '.join(missing)}")
        return
    for (r, cands), k in zip(flex, best):
        c = cands[k]
        r["Shop"], r["qn"], r["each"], r["Link"], r["src"] = c["shop"], c["qty"], c["each"], c["link"], c["src"]
        r["check"], r["pick_mpn"] = c["check"], c.get("mpn") or r["MPN"]


def plan(rows, shops):
    """The chosen order per shop: items, goods, shipping."""
    by = collections.OrderedDict()
    for r in rows:
        if r["qn"]:
            by.setdefault(r["Shop"], []).append(r)
    out = []
    for shop, items in by.items():
        goods = sum(r["qn"] * (r["each"] or 0) for r in items)
        s = shops.get(shop)
        out.append({"shop": shop, "items": items, "goods": goods, "ship": ship_cost(shops, shop, goods),
                    "delivery": s["Delivery"] if s else "", "ship_src": s["Src"] if s else ""})
    return out


def pick_mpn(r):
    return (r["check"].split(" (")[0] if r["check"] else (r.get("pick_mpn") or r["MPN"])).split("~")[0]


# ------------------------------------------------------------------ product cost
def batch(cache, fx, shops, units, lines, orders):
    """Cost of a batch of `units` units: every use row bought for the batch at the cheapest shop mix."""
    def qty(r):
        if r["Status"] != "use" or r["Group"] == "Equipment":
            return 0
        return math.ceil(fnum(r["Qty_per_unit"]) * units - 1e-9)

    rows = load(cache, fx, qty)
    choose(rows, shops)
    p = plan(rows, shops)
    groups = collections.OrderedDict((g, 0.0) for g in GROUPS if g != "Equipment")
    for r in rows:
        if r["qn"]:
            groups[r["Group"]] += r["qn"] * (r["each"] or 0) / units
    b = board_cost(lines, units, fx, orders) if lines is not None else None
    groups["Board"] += b["pln"] if b else 0
    ship = sum(x["ship"] or 0 for x in p) / units
    total = sum(x["goods"] + (x["ship"] or 0) for x in p)
    return {"units": units, "rows": rows, "plan": p, "groups": groups, "ship": ship, "board": b,
            "per_unit": sum(groups.values()) + ship, "total": total}


def options(cache, fx, shops, d):
    """Cheaper alternatives: each option row replaces the part in use with the same Function in the whole batch, the
    shops are chosen again, and the change of the batch total (goods and shipping) per unit is the saving."""
    units = d["units"]
    used = {r["Function"]: r["_i"] for r in d["rows"] if r["Status"] == "use" and r["qn"]}
    out = []
    for i, o in enumerate(read("purchase.csv")):
        if o["Status"] != "option" or o["Function"] not in used:
            continue
        drop = used[o["Function"]]

        def qty(r, i=i, drop=drop):
            if r["_i"] == i:
                return math.ceil(fnum(r["Qty_per_unit"]) * units - 1e-9)
            if r["_i"] == drop or r["Status"] != "use" or r["Group"] == "Equipment":
                return 0
            return math.ceil(fnum(r["Qty_per_unit"]) * units - 1e-9)

        rows = load(cache, fx, qty)
        choose(rows, shops)
        if any(r["Shop"] == "no source" for r in rows if r["_i"] == i):
            continue
        total = sum(x["goods"] + (x["ship"] or 0) for x in plan(rows, shops))
        r = next(r for r in rows if r["_i"] == i)
        u = next(r for r in d["rows"] if r["_i"] == drop)
        other = r["Shop"] != r["csv_shop"] and r["csv_shop"] != NO_SHOP
        notes = f'{r["Notes"]} (notes of the {r["csv_shop"]} offer)' if other else r["Notes"]
        out.append({"function": o["Function"], "now": short(u), "option": short(r), "mpn": pick_mpn(r),
                    "shop": r["Shop"], "link": r["Link"], "saving": (d["total"] - total) / units, "notes": notes})
    return sorted(out, key=lambda x: -x["saving"])


def checks(rows, b):
    out = []
    bad = [r["Item"] for r in rows if r["Status"] not in STATUS or r["Group"] not in GROUPS]
    out.append(("Status and group known", not bad, ", ".join(bad) or "all rows"))
    miss = [short(r) for r in rows if r["Status"] == "use" and r["Group"] != "Equipment" and r["each"] is None]
    out.append(("Parts with a price", not miss, ", ".join(miss) or "all"))
    nosrc = [short(r) for r in rows if r["Shop"] == "no source"]
    out.append(("Parts with a supplier", not nosrc, ", ".join(nosrc) or "all"))
    noshop = [short(r) for r in rows if r["qn"] and r["Shop"] == NO_SHOP]
    out.append(("Parts with a shop chosen (else no shipping is counted)", not noshop, ", ".join(noshop) or "all"))
    stale = [f'{short(r)} ({r["age"]} days)' for r in rows if r["Status"] == "use" and not r["src"].endswith((" API", " search"))
             and r["age"] is not None and r["age"] > STALE_DAYS]
    out.append((f"Hand-kept prices checked within {STALE_DAYS} days", not stale, ", ".join(stale) or "all"))
    miss_keys = sp.keys_missing()
    out.append(("Distributor API keys set", not miss_keys,
                f'missing: {", ".join(miss_keys)} (bom/README.md, "API keys")' if miss_keys else "all"))
    terms = [f'{short(r)}: {t}' for r in rows for t in sp.bad_terms(r["Must"].split("|"))]
    out.append(("Must terms valid", not terms, ", ".join(terms) or "all"))
    found = [f'{short(r)}: {r["check"]}' for r in rows if r["check"] and r["Shop"] != "no source"]
    out.append(("Parts found by search, not by part number (check them)", not found, " / ".join(found) or "none"))
    if b:
        out.append(("Board lines JLCPCB priced", not b["unpriced"],
                    ", ".join(",".join(ln["refs"]) for ln in b["unpriced"]) or "all"))
    return out


def quote_table(rows):
    """[item, qty, found by, CSV shop line, one cell per distributor, picked] for every row with quotes."""
    out = []
    for r in rows:
        if not r["quotes"]:
            continue
        csv_line = (zl(r["csv_each"] * r["qn"] if r["csv_each"] is not None else 0) + (f' ({r["csv_shop"]})' if r["csv_shop"] else "")
                    if r["csv_each"] is not None else "")
        cells = [zl(x["line"]) + (f' ({x["qty"]:g})' if x["qty"] != r["qn"] else "") if not x["error"]
                 else x["error"][:40] for x in r["quotes"]]
        out.append([short(r), f'{r["qn"]:g}', r["match"], csv_line, *cells, r["Shop"]])
    return out


def write_md(path, batches, detail, eq, opts, chk, fxnote, generated):
    d = batches[detail]
    units = list(batches)
    per = d["per_unit"]
    L = ["# Product cost estimate", "",
         f"Generated {generated} by `python tools/bom_cost.py`. Do not edit: change the CSV files in this folder and "
         "rerun. Gross prices (VAT included).", "", f"Rates: {fxnote}.", "",
         "Every part of a complete unit, bought for a batch of units at the cheapest combination of suppliers, shipping "
         "to Poland included and split over the batch. Parts you already own are counted too: this is the product cost.",
         "", "## Cost per unit", "",
         "| Group | " + " | ".join(f"{units_label(u)} [PLN]" for u in units) + " |",
         "|---|" + "---:|" * len(units)]
    for g in d["groups"]:
        L.append(f"| {g} | " + " | ".join(zl(batches[u]["groups"][g]) for u in units) + " |")
    L.append("| Shipping | " + " | ".join(zl(batches[u]["ship"]) for u in units) + " |")
    L.append("| **Total per unit** | " + " | ".join(f'**{zl(batches[u]["per_unit"])}**' for u in units) + " |")
    L += ["", f"- Equipment, once: {zl(sum(e[1] for e in eq))} zł ({', '.join(e[0] for e in eq) or 'none'}).",
          *([f"- Not counted yet: {NOT_COUNTED}."] if NOT_COUNTED else []),
          "- Board at 1 unit: the whole minimum JLCPCB order (5 PCBs, stencil, setup) carried by one board." if d["board"]
          else "- Board not computed (--no-board): the Board row holds only the hand-fitted parts.", ""]

    # most expensive items
    items = [(short(r), r["qn"] * (r["each"] or 0) / detail, r) for r in d["rows"] if r["qn"]]
    if d["board"]:
        items.append(("Board (JLCPCB PCB and assembly)", d["board"]["pln"], None))
    items.sort(key=lambda x: -x[1])
    L += [f"## Most expensive items ({detail} units)", "",
          "| # | Item | Supplier | Per unit [PLN] | Share [%] | Price |", "|---:|---|---|---:|---:|---|"]
    for i, (name, cost, r) in enumerate(items[:12], 1):
        src = r["src"] if r else ("order" if d["board"]["src"].startswith("order") else "EST")
        L.append(f'| {i} | {md(name)} | {md(r["Shop"] or "?") if r else "JLCPCB"} | {zl(cost)} | {100 * cost / per:.0f} | {md(src)} |')

    # where to save
    L += ["", f"## Where to save ({detail} units)", "", "### Cheaper options", ""]
    good = [o for o in opts if o["saving"] > 0.01]
    if good:
        L += ["| Part | Option | Supplier | Saving per unit [PLN] | Trade-off |", "|---|---|---|---:|---|"]
        L += [f'| {md(o["now"])} | [{md(o["option"])}]({o["link"]}) {md(o["mpn"])} | {md(o["shop"])} | {zl(o["saving"])} | {md(o["notes"])} |'
              if o["link"] else f'| {md(o["now"])} | {md(o["option"])} {md(o["mpn"])} | {md(o["shop"])} | {zl(o["saving"])} | {md(o["notes"])} |'
              for o in good]
    else:
        L.append("No listed option lowers the batch total.")
    L += ["", "Each option replaces the part in the whole batch and the shops are chosen again, so the saving includes "
          "shipping.", "",
          "### Batch size", "",
          "| Units | Per unit [PLN] | Board per unit [PLN] | Shipping per unit [PLN] |", "|---:|---:|---:|---:|"]
    L += [f'| {u} | {zl(batches[u]["per_unit"])} | {zl(batches[u]["groups"]["Board"])} | {zl(batches[u]["ship"])} |' for u in units]
    est = sorted(((short(r), r["qn"] * (r["each"] or 0) / detail) for r in d["rows"] if r["qn"] and r["src"] == "EST"),
                 key=lambda x: -x[1])
    L += ["", "### Prices to verify", "",
          f"Hand estimates (EST), {zl(sum(c for _, c in est))} zł per unit ({100 * sum(c for _, c in est) / per:.0f} %). "
          "A real price can move the total either way.", "",
          "| Item | Per unit [PLN] |", "|---|---:|"]
    L += [f"| {md(n)} | {zl(c)} |" for n, c in est]
    if d["board"]:
        b = d["board"]
        L += ["", "### Board", "", f"{zl(b['pln'])} zł per board. {b['src']}."]
        if not b["src"].startswith("order"):
            k = d["usd_pln"] * VAT / detail
            L += ["", f"- JLCPCB parts: {zl(b['parts_usd'] * k)} zł per board.",
                  f"- Extended-part fees: {b['ext']} lines x $3 per order = {zl(3 * b['ext'] * k)} zł per board. "
                  "Fewer extended lines or a larger batch lowers it.",
                  f"- PCB, assembly, shipping (EST): {zl(b['fixed_usd'] * k)} zł per board."]

    # all items
    L += ["", f"## All items ({detail} units)", "",
          "| Group | Item | Qty per unit | Supplier | Part number | Each [PLN] | Per unit [PLN] | Price |",
          "|---|---|---:|---|---|---:|---:|---|"]
    for r in sorted((r for r in d["rows"] if r["qn"]), key=lambda r: GROUPS.index(r["Group"]) if r["Group"] in GROUPS else 99):
        name = f'[{md(short(r))}]({r["Link"]})' if r["Link"] else md(short(r))
        flag = " (check)" if r["check"] and r["Shop"] != "no source" else ""
        L.append(f'| {r["Group"]} | {name}{flag} | {r["qg"]:g} | {md(r["Shop"])} | {md(pick_mpn(r))} | '
                 f'{zl(r["each"] or 0)} | {zl(r["qn"] * (r["each"] or 0) / detail)} | {md(r["src"])} |')
    qt = quote_table(d["rows"])
    if qt:
        L += ["", f"## Distributor quotes ({detail} units)", "",
              "Line totals [PLN] at the batch quantity (rounded-up quantity in brackets), cheapest in-stock variant per "
              "shop. Found by: the part number, a packaging variant of it, or the search words in purchase.csv.", "",
              "| Item | Qty | Found by | CSV price [PLN] | " + " | ".join(f"{x} [PLN]" for x in DISTRIBUTORS) + " | Picked |",
              "|---|---:|---|---:|" + "---:|" * len(DISTRIBUTORS) + "---|"]
        L += ["| " + " | ".join(md(c) for c in row) + " |" for row in qt]
    L += ["", "## Checks", "", "| Check | OK | Detail |", "|---|---|---|"]
    L += [f'| {name} | {"yes" if ok else "**no**"} | {md(detail_)} |' for name, ok, detail_ in chk]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L) + "\n")


def write_xlsx(path, batches, detail, eq, opts, chk, lines, fxnote, generated):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("  openpyxl missing (pip install openpyxl): cost.xlsx not written")
        return False
    head_fill = PatternFill("solid", fgColor="2F5597")

    def sheet(title, head, widths, first=False):
        ws = wb.active if first else wb.create_sheet(title)
        ws.title = title
        ws.append(head)
        for c in ws[1]:
            c.font, c.fill = Font(bold=True, color="FFFFFF"), head_fill
            c.alignment = Alignment(wrap_text=True, vertical="top")
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A2"
        return ws

    wb = Workbook()
    d, units = batches[detail], list(batches)
    ws = sheet("Cost per unit", ["Group", *(f"{units_label(u)} [PLN]" for u in units)], [28] + [14] * len(units), first=True)
    for g in d["groups"]:
        ws.append([g, *(round(batches[u]["groups"][g], 2) for u in units)])
    ws.append(["Shipping", *(round(batches[u]["ship"], 2) for u in units)])
    ws.append(["Total per unit", *(round(batches[u]["per_unit"], 2) for u in units)])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    ws.append([])
    ws.append([f"Equipment, once: {sum(e[1] for e in eq):.2f} zł"])
    ws.append([f"Generated {generated}. Gross prices. {fxnote}."])

    ws = sheet(f"Items {detail} units", ["Group", "Item", "Qty per unit", "Supplier", "Part number", "Each [PLN]",
                                         "Per unit [PLN]", "Price", "Link", "Check", "Notes"],
               [10, 45, 8, 16, 18, 10, 11, 12, 40, 40, 50])
    for r in d["rows"]:
        if r["qn"]:
            ws.append([r["Group"], r["Item"], r["qg"], r["Shop"], pick_mpn(r), round(r["each"] or 0, 2),
                       round(r["qn"] * (r["each"] or 0) / detail, 2), r["src"], r["Link"], r["check"], r["Notes"]])
            if r["Link"]:
                ws.cell(ws.max_row, 9).hyperlink = r["Link"]
    ws.auto_filter.ref = f"A1:K{ws.max_row}"

    ws = sheet("Cheaper options", ["Part", "Option", "Part number", "Supplier", "Saving per unit [PLN]", "Trade-off"],
               [30, 40, 18, 14, 12, 60])
    for o in opts:
        ws.append([o["now"], o["option"], o["mpn"], o["shop"], round(o["saving"], 2), o["notes"]])

    qt = quote_table(d["rows"])
    if qt:
        ws = sheet("Distributor quotes", ["Item", "Qty", "Found by", "CSV price [PLN]",
                                          *(f"{x} [PLN]" for x in DISTRIBUTORS), "Picked"],
                   [40, 6, 12, 18, 16, 16, 16, 16, 14])
        for row in qt:
            ws.append(row)
    if lines is not None:
        ws = sheet("Board BOM", ["Refs", "Qty per board", "Value", "Footprint", "Manufacturer", "MPN", "LCSC",
                                 "JLC library", "JLC stock", f"JLC unit [USD] at {detail} boards", "Line per board [USD]"],
                   [28, 8, 18, 22, 16, 22, 10, 10, 10, 12, 12])
        for ln in lines:
            j, jl = ln.get("jlc") or {}, bx.jlc_line(ln, detail)
            ws.append([" ".join(ln["refs"]), ln["qty"], ln["value"], ln["footprint"], ln["manufacturer"], ln["mpn"],
                       ln["lcsc"], j.get("library") or j.get("error", ""), j.get("stock"),
                       jl[1] if jl else None, round(jl[1] * ln["qty"], 4) if jl else None])
    ws = sheet("Checks", ["Check", "OK", "Detail"], [50, 6, 100])
    for name, ok, detail_ in chk:
        ws.append([name, "yes" if ok else "NO", detail_])
    try:
        wb.save(path)
    except PermissionError:
        print(f"  {os.path.basename(path)} is open in Excel: close it and rerun to update it")
        return False
    return True


# ------------------------------------------------------------------ ad hoc order
def read_order(path, rows):
    """Order lines (Item, Qty) matched to purchase.csv rows: a part number (any of a~b) or the start of an Item.
    Rows in use win over options with the same part number. Returns {row position: qty} and the unmatched keys."""
    want, missing = {}, []
    rows = sorted(enumerate(rows), key=lambda ir: ir[1]["Status"] != "use")
    rows = [dict(r, _i=i) for i, r in rows]
    with open(path, encoding="utf-8-sig") as f:
        for line in csv.DictReader(f):
            key, q = (line.get("Item") or "").strip(), fnum(line.get("Qty") or 0)
            if not key or not q:
                continue
            k = sp.norm(key)
            r = next((r for r in rows if k and k in {sp.norm(m) for m in r["MPN"].split("~") if m.strip()}), None) \
                or next((r for r in rows if r["Item"].lower().startswith(key.lower())), None)
            if r is None:
                missing.append(key)
            else:
                want[r["_i"]] = want.get(r["_i"], 0) + q
    return want, missing


def order_alternatives(cache, fx, rows):
    """Option rows with the same Function as an ordered part, priced for the same quantity (own offer or quotes).
    Shipping is not included: the order would change shops."""
    ordered = {r["Function"]: r for r in rows if r["qn"] and r["Status"] == "use"}
    opts = load(cache, fx, lambda r: (math.ceil(ordered[r["Function"]]["qn"]) if r["Status"] == "option"
                                     and r["Function"] in ordered else 0))
    out = []
    for o in opts:
        if not o["qn"]:
            continue
        cands = [(o["qn"] * o["each"], o["qn"], o["each"], o["Shop"], o["Link"], o["MPN"].split("~")[0])] \
            if o["each"] is not None and o["Shop"] != NO_SHOP else []
        cands += [(x["line"], x["qty"], x["each"], x["shop"], x["link"], x["mpn"]) for x in o["quotes"] if not x["error"]]
        if not cands:
            continue
        line, qty, each, shop, link, mpn = min(cands)
        u = ordered[o["Function"]]
        other = shop != o["Shop"] and o["Shop"] != NO_SHOP
        notes = f'{o["Notes"]} (notes of the {o["Shop"]} offer)' if other else o["Notes"]
        out.append({"for": short(u), "for_line": u["qn"] * (u["each"] or 0), "option": short(o), "shop": shop,
                    "qty": qty, "each": each, "line": line, "link": link, "mpn": mpn, "notes": notes})
    return out


def write_order_xlsx(path, p, total, generated, alts=()):
    """The shopping list as one sheet: a block per shop with its items, shipping and subtotal, links clickable."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
    except ImportError:
        print("  openpyxl missing (pip install openpyxl): order.xlsx not written")
        return
    wb = Workbook()
    ws = wb.active
    ws.title = "Order"
    head, sub = PatternFill("solid", fgColor="2F5597"), PatternFill("solid", fgColor="D9E1F2")
    ws.append(["Done", "Shop", "Qty", "Item", "Part number", "Each [PLN]", "Line [PLN]", "Link", "Check"])
    for c in ws[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), head
    for col, w in zip("ABCDEFGHI", (6, 22, 7, 50, 20, 11, 11, 45, 45)):
        ws.column_dimensions[col].width = w
    for x in p:
        for r in x["items"]:
            ws.append(["", x["shop"], r["qn"], short(r), pick_mpn(r), round(r["each"] or 0, 2),
                       round(r["qn"] * (r["each"] or 0), 2), r["Link"] or "", r["check"] or ""])
            if r["Link"]:
                c = ws.cell(ws.max_row, 8)
                c.hyperlink, c.font = r["Link"], Font(color="0563C1", underline="single")
        ship = x["ship"] if x["ship"] is not None else None
        ws.append(["", x["shop"], "", "Shipping" + (" (estimate)" if x["ship_src"] == "EST" else ""), "", "",
                   round(ship, 2) if ship is not None else "?"])
        ws.append(["", "", "", f'Subtotal {x["shop"]}', "", "", round(x["goods"] + (ship or 0), 2)])
        for c in ws[ws.max_row]:
            c.font, c.fill = Font(bold=True), sub
    ws.append([])
    ws.append(["", "", "", "Total including shipping", "", "", round(total, 2)])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True, size=12)
    if alts:
        ws.append([])
        ws.append(["", "Alternatives (not in the total, shipping not included)"])
        ws[ws.max_row][1].font = Font(bold=True)
        for a in alts:
            ws.append(["", a["shop"], a["qty"], f'{a["option"]} (instead of: {a["for"]}, {zl(a["for_line"])} zł)',
                       a["mpn"], round(a["each"], 2), round(a["line"], 2), a["link"] or "", a["notes"]])
            if a["link"]:
                c = ws.cell(ws.max_row, 8)
                c.hyperlink, c.font = a["link"], Font(color="0563C1", underline="single")
    ws.append([])
    ws.append(["", "", "", f"Generated {generated} by python tools/bom_cost.py --order. Gross prices."])
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    try:
        wb.save(path)
    except PermissionError:
        print(f"  {os.path.basename(path)} is open in Excel: close it and rerun to update it")


def write_order(out_dir, p, missing, generated, alts=()):
    os.makedirs(out_dir, exist_ok=True)
    total = sum(x["goods"] + (x["ship"] or 0) for x in p)
    L = ["# Shopping list", "",
         f"Generated {generated} by `python tools/bom_cost.py --order`. Gross prices. **Total {zl(total)} zł** including "
         "shipping.", "", "Items marked **check** were found by search: compare them with the notes before buying.", ""]
    if missing:
        L += [f"Not in bom/purchase.csv, left out: {', '.join(missing)}.", ""]
    for x in p:
        ship = "?" if x["ship"] is None else f'{zl(x["ship"])} zł' + (" (estimate)" if x["ship_src"] == "EST" else "")
        L += [f'## {x["shop"]}: {zl(x["goods"] + (x["ship"] or 0))} zł', "",
              f'Goods {zl(x["goods"])} zł, shipping {ship}, delivery {x["delivery"] or "?"}.', "",
              "| | Qty | Item | Part number | Price [PLN] |", "|---|---:|---|---|---:|"]
        for r in x["items"]:
            name = f'[{md(short(r))}]({r["Link"]})' if r["Link"] else md(short(r))
            flag = " **check**" if r["check"] and r["Shop"] != "no source" else (" (estimate)" if r["src"] == "EST" else "")
            L.append(f'| ☐ | {r["qn"]:g} | {name}{flag} | {md(pick_mpn(r))} | {zl(r["qn"] * (r["each"] or 0))} |')
        L.append("")
    if alts:
        L += ["## Alternatives", "", "Not in the total. Shipping not included: buying one would change the shops.", "",
              "| Instead of | Alternative | Shop | Qty | Each [PLN] | Line [PLN] | Notes |",
              "|---|---|---|---:|---:|---:|---|"]
        for a in alts:
            name = f'[{md(a["option"])}]({a["link"]})' if a["link"] else md(a["option"])
            L.append(f'| {md(a["for"])} ({zl(a["for_line"])} zł) | {name} {md(a["mpn"])} | {md(a["shop"])} | '
                     f'{a["qty"]:g} | {zl(a["each"])} | {zl(a["line"])} | {md(a["notes"])} |')
        L.append("")
    with open(os.path.join(out_dir, "order.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L))
    write_order_xlsx(os.path.join(out_dir, "order.xlsx"), p, total, generated, alts)
    with open(os.path.join(out_dir, "order_list.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["Shop", "Qty", "Item", "Part number", "Each [PLN]", "Line [PLN]", "Link"])
        for x in p:
            for r in x["items"]:
                w.writerow([x["shop"], f'{r["qn"]:g}', short(r), pick_mpn(r), f'{r["each"] or 0:.2f}',
                            f'{r["qn"] * (r["each"] or 0):.2f}', r["Link"]])
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--units", default="1,5,10", help="batch sizes the cost per unit is computed for")
    ap.add_argument("--detail", type=int, default=5, help="batch size for the item tables")
    ap.add_argument("--order", help="ad hoc order CSV (Item, Qty): writes a shopping list to --out instead")
    ap.add_argument("--out", default=os.path.join(bx.ROOT, "out"), help="folder for the --order outputs")
    ap.add_argument("--offline", action="store_true", help="use the cache only, no network")
    ap.add_argument("--refresh", action="store_true", help="ignore the cache")
    ap.add_argument("--no-board", action="store_true", help="skip the schematic and JLCPCB (no kicad-cli needed)")
    ap.add_argument("--project", help="project folder or .kicad_pro (default: the only project in the repo)")
    ap.add_argument("--skip-shop", action="append", default=[], help="leave this shop out (repeatable)")
    a = ap.parse_args()
    SKIP.update(a.skip_shop)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cache = bx.Cache(os.path.join(bx.ROOT, "out", "bom_cache.json"), a.offline, a.refresh)
    fx, fxnote = rates(cache)
    shops = {s["Shop"]: s for s in read("shops.csv")}
    generated = time.strftime("%Y-%m-%d")

    if a.order:
        want, missing = read_order(a.order, read("purchase.csv"))
        rows = load(cache, fx, lambda r: want.get(r["_i"], 0))
        cache.save()
        choose(rows, shops)
        alts = order_alternatives(cache, fx, rows)
        cache.save()
        total = write_order(a.out, plan(rows, shops), missing, generated, alts)
        print(f"order {zl(total)} zł: {os.path.join(a.out, 'order.xlsx')}, order.md, order_list.csv. {fxnote}")
        if missing:
            print(f"  not in purchase.csv: {', '.join(missing)}")
        return 0

    units = sorted({int(u) for u in a.units.split(",")} | {a.detail})
    hand = {x for r in read("purchase.csv") for x in r["Refs"].split()}
    if not a.no_board:
        bx.SCH, bx.KICAD_CLI = bx.find_root_sch(a.project), bx.kicad_cli()
    lines = None if a.no_board else board_lines(cache, hand)
    orders = read("orders.csv")
    batches = collections.OrderedDict((u, batch(cache, fx, shops, u, lines, orders)) for u in units)
    d = batches[a.detail]
    d["usd_pln"] = fx["USD"]
    opts = options(cache, fx, shops, d)
    cache.save()
    eq = [(short(r), r["qg"] * (r["each"] or 0)) for r in d["rows"] if r["Group"] == "Equipment" and r["Status"] == "use"]
    chk = checks(d["rows"], d["board"])

    write_md(os.path.join(BOM, "cost.md"), batches, a.detail, eq, opts, chk, fxnote, generated)
    files = ["bom/cost.md"]
    if lines is not None:
        write_board_csv(lines, a.detail)
        files.append("bom/board_bom.csv")
    if write_xlsx(os.path.join(BOM, "cost.xlsx"), batches, a.detail, eq, opts, chk, lines, fxnote, generated):
        files.append("bom/cost.xlsx")
    print("per unit: " + ", ".join(f'{units_label(u)} {zl(batches[u]["per_unit"])} zł' for u in units) + f". {fxnote}")
    for name, ok, detail_ in chk:
        print(f"  {'OK   ' if ok else 'CHECK'} {name}: {detail_[:110]}")
    print("  written: " + ", ".join(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
