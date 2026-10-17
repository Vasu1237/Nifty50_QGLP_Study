"""C - Annual fundamentals from the Upstox fundamentals API (only usable source found).

Endpoints (from Upstox's official JS SDK src/api/FundamentalsApi.js, tested 2026-10-15):
  /v2/fundamentals/{isin}/income-statement?type={consolidated|standalone}&time_period=yearly&fs=true
  /v2/fundamentals/{isin}/balance-sheet?type=...&fs=true
  /v2/fundamentals/{isin}/cash-flow?type=...&fs=true
  /v2/fundamentals/{isin}/profile        (current sector label)
LIMITATIONS (verified on RELIANCE, INFOSYS, HDFC BANK):
  * history = last 4 fiscal years only (Mar 2023 - Mar 2026) -> FY2008-FY2022 NOT available;
  * delisted/merged companies return empty statements (e.g. HDFC Ltd INE001A01036);
  * NO announcement dates. We apply SEBI LODR Reg. 33: audited annual results due within 60 days of FY end, so
    FY ending 31 Mar is assumed public by 30 May (<= 30 June rebalance). ASSUMPTION, not verified per company.
    Values are as currently displayed (latest restatement), not as originally reported.
  * no interest expense, depreciation, capex, debt or bank metrics (NIM, GNPA, CAR) are exposed.
Rate limit: 5 req/s, 450/min (Upstox documents 50/s, 500/min, 2000/30min). All responses cached.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from common import RAW, RateLimiter, cached_get, latest, log, save

BASE = "https://api.upstox.com/v2/fundamentals/{isin}/{ep}"
TOKEN = Path(r"C:\Users\DELL\Desktop\Derivatives_historical\upstox_access_token.txt")


def flatten(items, out, meta, parent=""):
    for it in items or []:
        name = it.get("particular") or it.get("category")
        for h in it.get("history", []):
            out.append({**meta, "line": f"{parent}{name}", "period": h.get("period"), "value": h.get("value")})
        for k in ("children", "sub_particulars", "items", "breakup"):
            if it.get(k):
                flatten(it[k], out, meta, f"{parent}{name} > ")


def main() -> None:
    mem = pd.read_csv(latest("members"))
    isins = sorted(mem.loc[mem["listed_today"], "isin"].dropna().unique()) + ["INE214T01019", "INE036A01016", "INE001A01036", "INE013A01015"]
    isins = sorted(set(isins))
    hdr = {"Authorization": f"Bearer {TOKEN.read_text().strip()}", "Accept": "application/json"}
    lim = RateLimiter((5, 1.0), (450, 60.0))
    rows, prof, empty = [], [], []
    for isin in isins:
        got = 0
        for basis in ("consolidated", "standalone"):
            for ep, q in (("income-statement", f"type={basis}&time_period=yearly&fs=true"),
                          ("balance-sheet", f"type={basis}&fs=true"), ("cash-flow", f"type={basis}&fs=true")):
                url = BASE.format(isin=isin, ep=ep) + "?" + q
                try:
                    d = json.loads(cached_get(url, RAW / "upstox_fund" / f"{isin}_{ep}_{basis}.json", hdr, lim))["data"]
                except Exception as e:  # noqa: BLE001
                    log("fundamentals", "error", f"{isin} {ep} {basis}: {str(e)[:80]}")
                    continue
                meta = {"isin": isin, "statement": ep, "basis": basis, "units": d.get("units_in"), "source": url.split("?")[0]}
                before = len(rows)
                flatten(d.get("full_statement"), rows, meta)
                if ep == "balance-sheet":
                    for h in d.get("history", []):
                        for k, v in h.items():
                            if k != "period":
                                rows.append({**meta, "line": k, "period": h["period"], "value": v})
                got += len(rows) - before
        try:
            p = json.loads(cached_get(BASE.format(isin=isin, ep="profile"), RAW / "upstox_fund" / f"{isin}_profile.json", hdr, lim))["data"]
            prof.append({"isin": isin, "sector_upstox": p.get("sector")})
        except Exception:  # noqa: BLE001
            prof.append({"isin": isin, "sector_upstox": None})
        if not got:
            empty.append(isin)
    df = pd.DataFrame(rows)
    df["fy_end"] = pd.to_datetime(df["period"], format="%b %Y") + pd.offsets.MonthEnd(0)
    df["assumed_public_by"] = df["fy_end"] + pd.Timedelta(days=60)
    df["announcement_date_verified"] = False
    log("fundamentals", "download", f"{len(isins)} ISINs; {len(df)} line-values; FY range {df.fy_end.min().date()}..{df.fy_end.max().date()}; "
        f"empty (no data): {empty}")
    save(df, "fundamentals_long_raw")
    save(pd.DataFrame(prof), "sector_upstox_current")


if __name__ == "__main__":
    main()
