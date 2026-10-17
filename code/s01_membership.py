"""A - Point-in-time Nifty 50 membership on each 30 June 2011-2025.

Why not niftyindices.com: its terms (checked 2026-10-14) prohibit "systematic or automated data collection ...
without our express written consent"; NSE's terms prohibit it outright.
Source used: Wikipedia "NIFTY 50" article (CC BY-SA; MediaWiki raw endpoint, 1 request, cached), whose
"Index changes" table cites a niftyindices press release or a dated news report for every change, and whose
"Constituents" table gives the current list. Membership at date D is reconstructed BACKWARDS from the current list:
undo every change with effective date > D (remove the included name, add back the excluded one).
Validation: exactly 50 names must result at every rebalance date; any other count is logged as an error.
ISINs: Wikidata property P946 (ISIN) for each linked article (Wikidata API, CC0), cross-checked against the Upstox
instrument master; names with no resolvable ISIN are flagged, never guessed.
Weights: NOT available (they are only in niftyindices factsheets) - column left out.
"""
from __future__ import annotations

import json
import re
import urllib.parse

import pandas as pd

from common import P1_CLEAN, RAW, RateLimiter, cached_get, log, save

ITEM = "members"
WIKI = "https://en.wikipedia.org/w/index.php?title=NIFTY_50&action=raw"
REBAL = [pd.Timestamp(f"{y}-06-30") for y in range(2011, 2026)]
LINK = re.compile(r"\[\[([^|\]]+)(?:\|([^\]]+))?\]\]")


def cells(block: str) -> list[list[str]]:
    rows, cur = [], []
    for line in block.splitlines():
        line = line.strip()
        if line.startswith("|-") or line.startswith("|}"):
            if cur:
                rows.append(cur)
            cur = []
        elif line.startswith("|") and not line.startswith("|+"):
            cur.append(re.sub(r"<ref.*?(</ref>|/>)", "", line[1:]).strip())
    if cur:
        rows.append(cur)
    return rows


def link(s: str) -> tuple[str, str] | None:
    m = LINK.search(s)
    return (m.group(1).strip(), (m.group(2) or m.group(1)).strip()) if m else None


def strip_attr(s: str) -> tuple[int, str]:
    """'rowspan="3" |1 October 2010' -> (3, '1 October 2010')"""
    m = re.match(r'\s*rowspan="?(\d+)"?\s*\|(.*)', s)
    return (int(m.group(1)), m.group(2).strip()) if m else (1, s.strip())


def parse_changes(txt: str) -> pd.DataFrame:
    sec = txt.split("==Index changes==")[1].split("\n==")[0]
    out, carry_date = [], (0, None)
    for r in cells(sec):
        if len(r) < 2 or not link(r[0]) or not link(r[1]):
            continue
        exc, inc = link(r[0]), link(r[1])
        if len(r) >= 3 and re.search(r"\d{4}", r[2]):
            span, d = strip_attr(r[2])
            carry_date = (span - 1, d)
        else:
            span, d = carry_date
            carry_date = (span - 1, d)
        out.append({"excluded_title": exc[0], "excluded": exc[1], "included_title": inc[0], "included": inc[1],
                    "effective": pd.to_datetime(d, dayfirst=True)})
    return pd.DataFrame(out)


def parse_current(txt: str) -> pd.DataFrame:
    sec = txt.split("==Constituents==")[1].split("\n==")[0]
    asof = re.search(r"as of ([0-9]{1,2} \w+ \d{4})", sec)
    rows = []
    for r in cells(sec):
        if len(r) >= 4 and link(r[0]):
            t, n = link(r[0])
            rows.append({"title": t, "name": n, "symbol": r[1].strip(), "sector_wiki": r[2].strip(),
                         "date_added": re.sub(r"\{\{efn.*", "", r[3]).strip()})
    return pd.DataFrame(rows), (asof.group(1) if asof else None)


def wikidata_isin(titles: list[str]) -> dict[str, list[str]]:
    lim = RateLimiter((2, 1.0))
    out = {}
    for i in range(0, len(titles), 40):
        chunk = titles[i:i + 40]
        q = urllib.parse.urlencode({"action": "query", "prop": "pageprops", "ppprop": "wikibase_item", "redirects": 1,
                                    "titles": "|".join(chunk), "format": "json"})
        d = json.loads(cached_get(f"https://en.wikipedia.org/w/api.php?{q}", RAW / "wikipedia" / f"pageprops_{i}.json", limiter=lim))
        redir = {r["from"]: r["to"] for r in d["query"].get("redirects", [])}
        norm = {r["from"]: r["to"] for r in d["query"].get("normalized", [])}
        qid = {p["title"]: p.get("pageprops", {}).get("wikibase_item") for p in d["query"]["pages"].values()}
        ids = {t: qid.get(redir.get(norm.get(t, t), norm.get(t, t))) for t in chunk}
        q2 = urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(v for v in ids.values() if v),
                                     "props": "claims", "format": "json"})
        e = json.loads(cached_get(f"https://www.wikidata.org/w/api.php?{q2}", RAW / "wikidata" / f"isin_{i}.json", limiter=lim))
        for t, q in ids.items():
            claims = e.get("entities", {}).get(q, {}).get("claims", {}).get("P946", []) if q else []
            out[t] = [c["mainsnak"].get("datavalue", {}).get("value") for c in claims if c["mainsnak"].get("datavalue")]
    return out


def main() -> None:
    txt = cached_get(WIKI, RAW / "wikipedia" / "NIFTY_50_raw.wiki").decode("utf-8")
    ch = parse_changes(txt)
    cur, asof = parse_current(txt)
    log(ITEM, "parse", f"{len(ch)} changes ({ch.effective.min().date()}..{ch.effective.max().date()}); current list {len(cur)} names as of {asof}")
    save(ch, "index_changes")
    members = set(cur["title"])
    # current table already reflects changes up to 'asof'; apply later changes (e.g. 30 Sep 2026) forward
    asof_ts = pd.to_datetime(asof, dayfirst=True)
    for _, c in ch[ch.effective > asof_ts].iterrows():
        if c.included_title not in members:
            members = (members - {c.excluded_title}) | {c.included_title}
            log(ITEM, "forward", f"applied post-{asof} change {c.effective.date()}: -{c.excluded} +{c.included}")
    snaps = []
    state = set(members)
    for d in sorted(REBAL, reverse=True):
        state = set(members)
        for _, c in ch[ch.effective > d].sort_values("effective", ascending=False).iterrows():
            state.discard(c.included_title)
            state.add(c.excluded_title)
        n = len(state)
        log(ITEM, "count" if n == 50 else "COUNT_ERROR", f"{d.date()}: {n} members")
        snaps += [{"rebalance_date": d.date(), "title": t} for t in sorted(state)]
    m = pd.DataFrame(snaps)
    names = {**dict(zip(ch.excluded_title, ch.excluded)), **dict(zip(ch.included_title, ch.included)), **dict(zip(cur.title, cur.name))}
    m["name"] = m["title"].map(names)
    m = m.merge(cur[["title", "symbol", "sector_wiki"]], on="title", how="left")

    titles = sorted(set(m["title"]) | set(cur["title"]))
    isins = wikidata_isin(titles)
    mp = pd.read_csv(sorted(P1_CLEAN.glob("item11_isin_mapping_2*.csv"))[-1])
    live = set(mp["isin"])
    sym2isin = dict(zip(mp["nse_symbol"], mp["isin"]))

    # Manual overrides for titles with no Wikidata ISIN. Each ISIN was looked up by current NSE symbol in the
    # Upstox instrument master (name checked by eye) or, if absent from the master, accepted only if the Upstox
    # candle API returned prices for it. Renames keep the ISIN (Bharti Infratel->Indus Towers 2020;
    # Indiabulls Housing->Sammaan Capital). Names with no verifiable ISIN are deliberately left out (see log).
    OVERRIDE = {
        "IndusInd Bank": "INE095A01012", "Britannia Industries": "INE216A01030", "Divi's Laboratories": "INE361B01024",
        "LTIMindtree": "INE214T01019", "UPL (company)": "INE628A01036", "Shree Cement": "INE070A01015",
        "Bharti Infratel": "INE121J01017", "Zee Entertainment Enterprises": "INE256A01028",
        "Indiabulls": "INE148I01020", "Lupin Limited": "INE326A01037", "ACC (company)": "INE012A01025",
        "Ambuja Cements": "INE079A01024", "Robert Bosch GmbH": "INE323A01026",
        "National Mineral Development Corporation": "INE584A01023", "Punjab National Bank": "INE160A01022",
        "United Spirits": "INE854D01024", "Reliance Infrastructure": "INE036A01016", "Siemens": "INE003A01024",
        "Steel Authority of India": "INE114A01011", "Reliance Power": "INE614G01033",
        "Yes Bank": "INE528G01035",  # Wikidata lists pre-2017 ISIN INE528G01019; live ISIN after 2017 FV split
    }

    def pick(row):
        if row["title"] in OVERRIDE:
            return OVERRIDE[row["title"]], "manual override (Upstox master by symbol / candle API test)"
        cands = [i for i in isins.get(row["title"], []) if isinstance(i, str) and i.startswith("INE")]
        lv = [i for i in cands if i in live]
        if lv:
            return lv[0], "wikidata+upstox_live"
        if isinstance(row["symbol"], str) and row["symbol"] in sym2isin:
            return sym2isin[row["symbol"]], "symbol->upstox (current constituents)"
        if cands:
            return cands[0], "wikidata only (not in today's listings: delisted/merged/ISIN changed)"
        return None, "UNRESOLVED"
    res = m.apply(pick, axis=1, result_type="expand")
    m["isin"], m["isin_source"] = res[0], res[1]
    m["listed_today"] = m["isin"].isin(live)
    m["nse_symbol_today"] = m["isin"].map(dict(zip(mp["isin"], mp["nse_symbol"])))
    un = m.loc[m["isin"].isna(), "name"].unique()
    log(ITEM, "isin", f"resolved {m['isin'].notna().mean():.1%} of member-rows; unresolved: {list(un)}")
    save(m[["rebalance_date", "isin", "name", "nse_symbol_today", "symbol", "listed_today", "isin_source", "sector_wiki", "title"]]
         .rename(columns={"symbol": "symbol_wiki_current"}), ITEM)


if __name__ == "__main__":
    main()
