"""Sub-period check for the P1 results: does the signal pattern hold in 2011-2016 and 2017-2025 separately?

Uses the same definitions as s08 (holding months, quintiles, Fama-MacBeth slopes with 12 Newey-West lags).
Split at the rebalance: rebalances 2011-2016 (holdings Jul 2011 - Jun 2017) vs 2017-2025 (Jul 2017 - Jun 2026).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from common import latest, log, save
from s08_analysis import NW_LAGS, Q_COLS, holding_rebalance, nw_ols, pval

ITEM = "s11_subperiod"
SPLIT = pd.Timestamp("2017-06-30")


def main() -> None:
    panel = pd.read_csv(latest("panel_prowess"), parse_dates=["rebalance_date"])
    ret = pd.read_csv(latest("returns_monthly_prowess"), parse_dates=["month_end"])
    stocks = ret[ret["kind"].str.startswith("stock")].pivot(index="month_end", columns="id", values="ret_m").sort_index()
    qm = pd.read_csv(latest("analysis_monthly_returns"), parse_dates=["month_end"]).set_index("month_end")
    rbs = sorted(panel["rebalance_date"].unique())
    rb_of = {m: holding_rebalance(m, rbs) for m in stocks.index}
    rows = []
    for name, lo, hi in [("2011-2016", pd.Timestamp("2000-01-01"), SPLIT), ("2017-2025", SPLIT, pd.Timestamp("2099-01-01"))]:
        months = [m for m, r in rb_of.items() if r is not None and lo <= r < hi]
        ls = qm.loc[qm.index.isin(months), "LS_Q5_minus_Q1"].dropna()
        rows.append({"period": name, "test": "LS Q5-Q1 mean monthly", "value": ls.mean(), "t_NW": np.nan, "n": len(ls)})
        for k in Q_COLS + ["qglp_composite"]:
            s = {}
            for m in months:
                g = panel[panel["rebalance_date"] == rb_of[m]].dropna(subset=["isin"]).set_index("isin")
                g = g.assign(ret=stocks.loc[m].reindex(g.index)).dropna(subset=["ret", k])
                if len(g) >= 20:
                    b, _ = nw_ols(g["ret"], g[[k]])
                    s[m] = b[1]
            sr = pd.Series(s)
            b, se = nw_ols(sr, np.zeros((len(sr), 0)))
            rows.append({"period": name, "test": f"FM slope {k}", "value": b[0], "t_NW": b[0] / se[0], "n": len(sr)})
    out = pd.DataFrame(rows)
    out["p_NW"] = out["t_NW"].apply(lambda t: pval(t) if pd.notna(t) else np.nan)
    save(out, "analysis_subperiod")
    log(ITEM, "sub-period", "split at 2017 rebalance; FM slopes per month; NW 12 lags", rows_out=len(out))
    print(out.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
