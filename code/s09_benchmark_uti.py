"""Official-source benchmark for P1: UTI Nifty 50 Index Fund (Regular Plan, Growth), AMFI scheme code 100822.

Why this fund: AMFI's public NAV history (amfiindia.com, the same endpoint used in P3, personal non-commercial use)
covers it from 3-Apr-2006, so it spans the whole 2011-2025 study. The official Nifty 50 TRI needs licensed access.

What it measures: the NAV of an index fund that holds the Nifty 50 with the same weights, so its return is the TRI
minus the fund's expenses (regular plan, so higher than Direct plans). Expenses are NOT removed here: the gap to the
TRI is therefore understated by the fund's expense ratio (look up the scheme's current TER in its factsheet). Dividends
are reinvested in the Growth option.

Output: clean/benchmark_uti_nifty50_monthly_<date>.csv with month_end, nav (last NAV on or before month end),
ret_m (monthly return), plus checks against NIFTY50_PRICE (Upstox price index) and the cap-weighted member proxy.
"""
from __future__ import annotations

import glob
import json

import numpy as np
import pandas as pd

from common import RAW, latest, log, save

ITEM = "s09_benchmark_uti"
SCHEME = "100822"


def load_nav() -> pd.DataFrame:
    rows = []
    for f in sorted(glob.glob(str(RAW / "amfi_index" / "utinifty50_regular_*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        if "data" not in d:
            raise SystemExit(f"bad AMFI response in {f}: {d}")
        for g in d["data"]["nav_groups"]:
            if "Regular Plan" in g["nav_name"] and "Growth" in g["nav_name"]:
                rows += [(r["date"], float(r["nav"])) for r in g["historical_records"]]
    nav = pd.DataFrame(rows, columns=["date", "nav"]).drop_duplicates("date").sort_values("date")
    nav["date"] = pd.to_datetime(nav["date"])
    log(ITEM, "load NAV", f"scheme {SCHEME} (UTI Nifty 50 Index Fund, Regular Growth) {nav['date'].min().date()}..{nav['date'].max().date()}",
        rows_out=len(nav))
    return nav


def main() -> None:
    nav = load_nav().set_index("date")["nav"]
    me = pd.date_range(nav.index.min().to_period("M").to_timestamp("M"), "2026-09-30", freq="ME")
    m = nav.reindex(nav.index.union(me)).sort_index().ffill().reindex(me)
    out = pd.DataFrame({"month_end": me, "nav": m.values})
    out["ret_m"] = out["nav"] / out["nav"].shift() - 1
    out = out.dropna(subset=["ret_m"])
    log(ITEM, "monthly returns", "month-end NAV (last on or before month end), simple monthly return", rows_out=len(out))
    save(out, "benchmark_uti_nifty50_monthly")

    # checks
    ret = pd.read_csv(latest("returns_monthly_prowess"), parse_dates=["month_end"])
    px = ret[ret["kind"].str.startswith("benchmark")].pivot(index="month_end", columns="id", values="ret_m")["NIFTY50_PRICE"]
    uti = out.set_index("month_end")["ret_m"]
    q = pd.read_csv(latest("analysis_monthly_returns"), parse_dates=["month_end"]).set_index("month_end")["BENCH_proxy"]
    both = pd.concat([uti.rename("uti"), px.rename("price"), q.rename("proxy")], axis=1).dropna()
    corr = both.corr()
    print("\n=== benchmark checks, overlapping months", len(both), "===")
    print(corr.round(4).to_string())
    ann = both.mean() * 12
    print("annualised mean return:\n", ann.round(4).to_string())
    diff = (both["uti"] - both["price"]).mean() * 12
    print(f"UTI minus price index: {diff*100:.2f}%/yr (expected positive: dividends, roughly 1.3%/yr, less fund expenses)")
    print(f"UTI minus cap-weighted proxy: {(both['uti']-both['proxy']).mean()*12*100:.2f}%/yr")
    log(ITEM, "checks", f"corr(UTI,price)={corr.loc['uti','price']:.3f}; corr(UTI,proxy)={corr.loc['uti','proxy']:.3f}")


if __name__ == "__main__":
    main()
