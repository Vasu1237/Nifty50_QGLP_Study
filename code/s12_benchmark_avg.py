"""Benchmark for P1: equal-weight average of the monthly returns of two AMFI-listed Nifty 50 index funds.

  UTI Nifty 50 Index Fund, Regular Growth (AMFI 100822)  - from s09
  SBI Nifty Index Fund, Regular Growth (AMFI 102272)     - downloaded 17-Oct-2026 (raw/amfi_index/sbinifty50_*)

Both track the Nifty 50 with near-identical holdings and report NAVs net of their own fees. Averaging the two halves
the idiosyncratic fee and tracking differences. The series is a proxy for the Nifty 50 TRI (net of about 0.2-1.0%/yr
of fees), not the official index.
"""
from __future__ import annotations

import glob
import json

import pandas as pd

from common import RAW, latest, log, save

ITEM = "s12_benchmark_avg"


def nav_series(prefix: str) -> pd.Series:
    rows = []
    for f in sorted(glob.glob(str(RAW / "amfi_index" / f"{prefix}_regular_*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        rows += [(r["date"], float(r["nav"])) for g in d["data"]["nav_groups"] for r in g["historical_records"]]
    s = pd.Series(dict(rows))
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def month_end_returns(s: pd.Series, me: pd.DatetimeIndex) -> pd.Series:
    lvl = s.reindex(s.index.union(me)).sort_index().ffill().reindex(me)
    return lvl.pct_change()


def main() -> None:
    me = pd.date_range("2006-04-30", "2026-09-30", freq="ME")
    uti = month_end_returns(nav_series("utinifty50"), me).rename("uti")
    sbi = month_end_returns(nav_series("sbinifty50"), me).rename("sbi")
    both = pd.concat([uti, sbi], axis=1).dropna()
    avg = both.mean(axis=1).rename("ret_m")
    out = pd.DataFrame({"month_end": avg.index, "ret_m": avg.values, "uti_ret": both["uti"].values,
                        "sbi_ret": both["sbi"].values})
    log(ITEM, "average", f"equal-weight UTI and SBI monthly returns; {len(out)} months", rows_out=len(out))
    save(out, "benchmark_avg_nifty50_monthly")

    print(f"corr UTI vs SBI {both.corr().iloc[0,1]:.4f}; annualised avg {avg.mean()*12:.4f}; "
          f"UTI {both['uti'].mean()*12:.4f}; SBI {both['sbi'].mean()*12:.4f}")


if __name__ == "__main__":
    main()
