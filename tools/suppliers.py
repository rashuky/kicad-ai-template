"""Distributor search for Poland: TME, Farnell (pl.farnell.com), Mouser, DigiKey (PL site). Used by bom_cost.py.

Every search returns a list of offers, one per orderable variant (cut tape, reel, pack):
  {shop, mpn, maker, desc, stock, moq, mult, breaks [(qty, unit net)], currency, url, part}

- by_mpn(): the part number, matched loosely (case, dashes, spaces and dots ignored: EEE-FK1E221P = EEEFK1E221P),
  from the same manufacturer. With prefix=True: a longer part number whose extra part is a packaging suffix
  (SHT40-CD1B-R3, -TR, -CT, -REEL), only from a named manufacturer.
- by_keywords(): a keyword search, kept only when the text of the offer (description, part number, maker) holds
  every required term. Terms are matched without spaces and case (20 V = 20V). A term with digits does not match
  inside a longer number (20V does not match 120V). "a~b" means a or b. ">=6A" means a value of at least 6 with the
  unit A in the description (ratings). Farnell and Mouser answer in Polish: give Polish alternatives where needed.

API keys (environment, setup in bom/README.md):
  TME_TOKEN, TME_SECRET, FARNELL_API_KEY, MOUSER_API_KEY, DIGIKEY_CLIENT_ID, DIGIKEY_CLIENT_SECRET
A shop without keys answers {"error": "no key"}.
"""
import base64
import html
import json
import os
import re
import time
import urllib.parse

from bom import http, num, same_maker

SHOPS = {"TME": ("TME_TOKEN", "TME_SECRET"), "Farnell": ("FARNELL_API_KEY",), "Mouser": ("MOUSER_API_KEY",),
         "DigiKey": ("DIGIKEY_CLIENT_ID", "DIGIKEY_CLIENT_SECRET")}
FARNELL_STORE = "pl.farnell.com"
RESULTS = 25
PACKAGING = re.compile(r"[-/#](R\d+|TR\w*|CT|REEL|T&R|BULK|TUBE|TRAY)", re.I)   # suffixes that only change the packaging


class NoKey(Exception):
    pass


def norm(s):
    """Part number or term for comparison: upper case, letters and digits only."""
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def squash(s):
    """Text for term matching: lower case, no whitespace."""
    return re.sub(r"\s+", "", (s or "").lower())


def key(*names):
    vals = [os.environ.get(n) for n in names]
    if not all(vals):
        raise NoKey()
    return vals


# ------------------------------------------------------------------ TME
_TME = {}


def _tme(path, params):
    """TME API v2 (tokens made after 14 May 2026 work only here): OAuth client credentials, then GET with a bearer token."""
    tok, sec = key("TME_TOKEN", "TME_SECRET")
    if _TME.get("exp", 0) < time.time() + 30:
        t = http("https://api.tme.eu/auth/token", b"grant_type=client_credentials",
                 {"Content-Type": "application/x-www-form-urlencoded",
                  "Authorization": "Basic " + base64.b64encode(f"{tok}:{sec}".encode()).decode()})
        _TME.update(token=t["access_token"], exp=time.time() + int(t.get("expires_in", 300)))
    d = http(f"https://api.tme.eu/{path}?" + urllib.parse.urlencode({"country": os.environ.get("TME_COUNTRY", "PL"), **params}, doseq=True),
             headers={"Authorization": "Bearer " + _TME["token"], "Accept-Language": "en"})
    if d.get("status") != "OK":
        raise RuntimeError(f'TME {d.get("status") or d.get("code")}')
    return d.get("data") or {}


def tme(query, mode):
    found = _tme("products/search", {"phrase": query[:40], "scope[]": "products", "limit": RESULTS})
    prods = ((found.get("products") or {}).get("elements") or [])[:RESULTS]
    if not prods:
        return []
    data = _tme("products/data", {"currency": "PLN", "scope[]": ["prices", "stock"],
                                  "symbols[]": [p["symbol"] for p in prods]})
    prices = {p["symbol"]: p for p in data.get("elements") or []}
    out = []
    for p in prods:
        pr = prices.get(p["symbol"]) or {}
        pl = pr.get("prices") or {}
        breaks = pl.get("elements") or []
        if not breaks:
            continue
        syms = p.get("manufacturer_symbols") or [p["symbol"]]
        net = 1 + (pl.get("tax") or {}).get("rate", 0) / 100 if pl.get("type") == "GROSS" else 1     # account set to gross
        out.append({"shop": "TME", "mpn": next((m for m in syms if norm(m) == norm(query)), syms[0]),
                    "maker": (p.get("manufacturer") or {}).get("name"), "desc": p.get("description") or "",
                    "stock": pr.get("stock_quantity"), "moq": p.get("minimal_amount") or 1,
                    "mult": p.get("multiples") or 1, "currency": "PLN", "part": p["symbol"],
                    "breaks": [(b["amount"], b["price"] / net) for b in breaks],
                    "url": "https://www.tme.eu/pl/details/" + urllib.parse.quote(p["symbol"].lower())})
    return out


# ------------------------------------------------------------------ Farnell
def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "x"


def farnell_url(p):
    """Farnell product links need maker, part number and description slugs before /dp/<order code>."""
    desc = (p.get("displayName") or "").split(" - ")[-1]
    return (f'https://{FARNELL_STORE}/{slug(p.get("vendorName") or p.get("brandName"))}/'
            f'{slug(p.get("translatedManufacturerPartNumber"))}/{slug(desc)[:60]}/dp/{p.get("sku")}')


def farnell(query, mode):
    (k,) = key("FARNELL_API_KEY")
    term = f"manuPartNum:{query}" if mode == "mpn" else f"any:{query}"
    d = http("https://api.element14.com/catalog/products?" + urllib.parse.urlencode({
        "term": term, "storeInfo.id": FARNELL_STORE, "resultsSettings.offset": 0,
        "resultsSettings.numberOfResults": RESULTS, "resultsSettings.responseGroup": "large,inventory",
        "callInfo.responseDataFormat": "json", "callInfo.apiKey": k}))
    if "Fault" in d:
        raise RuntimeError(f'Farnell {d["Fault"]}')
    ret = d.get("manufacturerPartNumberSearchReturn") or d.get("keywordSearchReturn") or {}
    out = []
    for p in ret.get("products") or []:
        if not p.get("prices") or (p.get("sku") or "").upper().endswith("RL"):    # RL: re-reel with a reeling fee
            continue
        pack = int(p.get("packSize") or 1)           # prices, stock and minimum count packs of packSize pieces
        st = (p.get("stock") or {}).get("level")
        out.append({"shop": "Farnell", "mpn": p.get("translatedManufacturerPartNumber"),
                    "maker": p.get("vendorName") or p.get("brandName"), "desc": html.unescape(p.get("displayName") or ""),
                    "stock": st * pack if st is not None else None,
                    "moq": int(p.get("translatedMinimumOrderQuality") or 1) * pack, "mult": pack, "currency": "PLN",
                    "part": p.get("sku"), "breaks": [(b["from"] * pack, b["cost"] / pack) for b in p["prices"]],
                    "url": farnell_url(p)})
    return out


# ------------------------------------------------------------------ Mouser
def mouser(query, mode):
    (k,) = key("MOUSER_API_KEY")
    if mode == "mpn":
        body = {"SearchByPartRequest": {"mouserPartNumber": query, "partSearchOptions": "None"}}
        url = "https://api.mouser.com/api/v1/search/partnumber"
    else:
        body = {"SearchByKeywordRequest": {"keyword": query, "records": RESULTS, "startingRecord": 0,
                                           "searchOptions": "InStock"}}
        url = "https://api.mouser.com/api/v1/search/keyword"
    d = http(f"{url}?apiKey={k}", json.dumps(body).encode(), {"Content-Type": "application/json"})
    if d.get("Errors"):
        raise RuntimeError(f'Mouser {d["Errors"][0].get("Message")}')
    out = []
    for p in (d.get("SearchResults") or {}).get("Parts") or []:
        pb = p.get("PriceBreaks") or []
        if not pb:
            continue
        avail = re.match(r"[\d\s\u00a0]*", p.get("Availability") or "").group(0)
        stock = num(p.get("AvailabilityInStock") or re.sub(r"\D", "", avail) or "0") or 0
        out.append({"shop": "Mouser", "mpn": p.get("ManufacturerPartNumber"), "maker": p.get("Manufacturer"),
                    "desc": html.unescape(p.get("Description") or ""), "stock": int(stock), "moq": int(p.get("Min") or 1),
                    "mult": int(p.get("Mult") or 1), "currency": pb[0].get("Currency", ""),
                    "part": p.get("MouserPartNumber"), "breaks": [(b["Quantity"], num(b["Price"])) for b in pb],
                    "url": p.get("ProductDetailUrl") or ""})
    return out


# ------------------------------------------------------------------ DigiKey
_DK = {}


def digikey(query, mode):
    cid, sec = key("DIGIKEY_CLIENT_ID", "DIGIKEY_CLIENT_SECRET")
    if _DK.get("exp", 0) < time.time() + 60:
        t = http("https://api.digikey.com/v1/oauth2/token", urllib.parse.urlencode(
            {"client_id": cid, "client_secret": sec, "grant_type": "client_credentials"}).encode(),
            {"Content-Type": "application/x-www-form-urlencoded"})
        _DK.update(token=t["access_token"], exp=time.time() + int(t.get("expires_in", 600)))
    d = http("https://api.digikey.com/products/v4/search/keyword", json.dumps({"Keywords": query, "Limit": RESULTS}).encode(),
             {"Content-Type": "application/json", "Authorization": "Bearer " + _DK["token"], "X-DIGIKEY-Client-Id": cid,
              "X-DIGIKEY-Locale-Site": "PL", "X-DIGIKEY-Locale-Language": "en", "X-DIGIKEY-Locale-Currency": "PLN"})
    cur = (d.get("SearchLocaleUsed") or {}).get("Currency") or "PLN"
    out, seen = [], set()
    for p in (d.get("ExactMatches") or []) + (d.get("Products") or []):
        desc = (p.get("Description") or {})
        for v in p.get("ProductVariations") or []:
            reel = "Digi-Reel" in ((v.get("PackageType") or {}).get("Name") or "")      # reeling fee not in the price
            if not v.get("StandardPricing") or v.get("MarketPlace") or reel or v.get("DigiKeyProductNumber") in seen:
                continue
            seen.add(v.get("DigiKeyProductNumber"))
            out.append({"shop": "DigiKey", "mpn": p.get("ManufacturerProductNumber"),
                        "maker": (p.get("Manufacturer") or {}).get("Name"),
                        "desc": html.unescape(f'{desc.get("ProductDescription") or ""} {desc.get("DetailedDescription") or ""}'.strip()),
                        "stock": v.get("QuantityAvailableforPackageType", p.get("QuantityAvailable")),
                        "moq": v.get("MinimumOrderQuantity") or 1, "mult": 1, "currency": cur,
                        "part": v.get("DigiKeyProductNumber"),
                        "breaks": [(b["BreakQuantity"], b["UnitPrice"]) for b in v["StandardPricing"]],
                        "url": p.get("ProductUrl") or ""})
    return out


SEARCH = {"TME": tme, "Farnell": farnell, "Mouser": mouser, "DigiKey": digikey}


# ------------------------------------------------------------------ matching
def run(cache, shop, query, mode):
    """Cached search. Returns {"offers": [...]} or {"error": ...}."""
    def fn():
        try:
            return {"offers": SEARCH[shop](query, mode)}
        except NoKey:
            return {"error": "no key"}
        except Exception as e:                      # one failed shop must not stop the run
            m = re.search(r"HTTP Error (\d+)", str(e))
            return {"error": f"HTTP {m.group(1)}" if m else f"{type(e).__name__}: {e}"[:80]}
    return cache.get(f"{shop}:{mode}:{query}", fn)


def packaging_variant(found, mpn):
    """found = mpn + a packaging suffix only (SHT40-CD1B + -R3). D2F-01L3 or D2F-01L-D3 are other parts of D2F-01L."""
    f, m = re.sub(r"\s", "", found or "").upper(), re.sub(r"\s", "", mpn).upper()
    return f.startswith(m) and bool(PACKAGING.fullmatch(f[len(m):]))


def by_mpn(cache, shop, mpn, maker, prefix=False):
    """Exact part number. With prefix=True (the caller does this only when no shop has the exact number) also the
    same number with a packaging suffix, from a named manufacturer. Those offers carry "prefix": True."""
    pool = []
    for mode in ("mpn", "kw") if shop in ("Farnell", "Mouser") else ("mpn",):   # part-number endpoints are strict
        r = run(cache, shop, mpn, mode)
        if "error" in r:
            return r
        pool += [o for o in r["offers"] if same_maker(maker, o["maker"])]
        exact = [o for o in pool if norm(o["mpn"]) == norm(mpn)]
        if exact:
            return {"offers": exact}
    longer = [dict(o, prefix=True) for o in pool if prefix and maker.strip() and packaging_variant(o["mpn"], mpn)]
    return {"offers": longer} if longer else {"error": "not found"}


MIN_TERM = re.compile(r">=\s*(\d+(?:\.\d+)?)\s*([A-Za-z]+)")


def bad_terms(must):
    """Terms that look like a minimum (>=...) but are not a number with a unit."""
    return [t for t in must if t.strip().startswith(">=") and not MIN_TERM.fullmatch(t.strip())]


def at_least(desc, term):
    """'>=6A': a number followed by the unit in the description is at least 6. 5.0 A fails, 6 A, 10A and 15 Amp pass.
    The part number is not read (PJ-006A is not 6 A)."""
    m = MIN_TERM.fullmatch(term.strip())
    if not m:
        return False
    unit = r"(?:a|amps?)" if m.group(2).lower() == "a" else re.escape(m.group(2))
    vals = re.findall(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*" + unit + r"(?![a-z])", desc or "", re.I)
    return any(float(v.replace(",", ".")) >= float(m.group(1)) for v in vals)


def has(text, alt):
    """alt inside text (lower case), spaces ignored (20V = 20 V). With digits, not inside a longer number: 20V is not
    in 120V, 2.5 not in 12.5. A dot or comma counts as part of a number only as a decimal mark (between digits)."""
    a = squash(alt)
    pat = r"\s*".join(re.escape(ch) for ch in a)
    if re.search(r"\d", a):
        pat = r"(?<!\d)(?<!\d[.,])" + pat + (r"(?!\d|[.,]\d)" if a[-1].isdigit() else "")
    return re.search(pat, text) is not None


def matches(offer, must):
    """Every term must hold: text (a~b = a or b), or a minimum value with a unit (>=6A, description only)."""
    text = " ".join(str(offer.get(k) or "") for k in ("desc", "mpn", "maker")).lower()
    return all(at_least(offer.get("desc"), term) if term.strip().startswith(">=") else
               any(has(text, alt) for alt in term.split("~")) for term in must if term.strip())


def by_keywords(cache, shop, query, must):
    r = run(cache, shop, query, "kw")
    if "error" in r:
        return r
    offers = [o for o in r["offers"] if matches(o, must) and (o["stock"] or 0) > 0]
    return {"offers": offers} if offers else {"error": "no match"}


def keys_missing():
    return [s for s, names in SHOPS.items() if not all(os.environ.get(n) for n in names)]
