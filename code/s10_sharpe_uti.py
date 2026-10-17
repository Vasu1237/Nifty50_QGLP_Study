"""Block-bootstrap Sharpe test: quintile portfolios vs the average of UTI and SBI Nifty 50 index fund returns (s12).

Same method as s08 (12-month circular blocks, 5000 runs, seed 20261016), with the official-source benchmark in place
of the cap-weighted member proxy. Holding months are the same as in s08 (Jul 2011 - Jun 2026).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from common import latest, log, save

ITEM = "s10_sharpe_uti"
BOOT_REPS, BLOCK, SEED = 5000, 12, 20261016


def sharpe(x):
    return x.mean() / x.std(ddof=1)


def main() -> None:
    q = pd.read_csv(latest("analysis_monthly_returns"), parse_dates=["month_end"]).set_index("month_end")
    uti = pd.read_csv(latest("benchmark_avg_nifty50_monthly"), parse_dates=["month_end"]).set_index("month_end")["ret_m"]
    d = pd.concat([(q["Q5"] - q["RF"]).rename("q5"), (q["Q1"] - q["RF"]).rename("q1"),
                   (uti - q["RF"]).rename("bm"), q["LS_Q5_minus_Q1"].rename("ls")], axis=1).dropna()
    log(ITEM, "align", f"months with Q5, Q1, UTI benchmark and RF: {len(d)}", rows_out=len(d))

    rng = np.random.default_rng(SEED)
    n, nb = len(d), int(np.ceil(len(d) / BLOCK))
    res = {"q5_minus_bm": [], "q1_minus_bm": [], "ls_mean": []}
    for _ in range(BOOT_REPS):
        starts = rng.integers(0, n, nb)
        ix = np.concatenate([np.arange(s, s + BLOCK) % n for s in starts])[:n]
        s = d.iloc[ix]
        res["q5_minus_bm"].append(sharpe(s["q5"]) - sharpe(s["bm"]))
        res["q1_minus_bm"].append(sharpe(s["q1"]) - sharpe(s["bm"]))
        res["ls_mean"].append(s["ls"].mean())

    rows = []
    obs = {"q5_minus_bm": sharpe(d["q5"]) - sharpe(d["bm"]),
           "q1_minus_bm": sharpe(d["q1"]) - sharpe(d["bm"]),
           "ls_mean": d["ls"].mean()}
    for k in res:
        b = np.array(res[k])
        p = float(np.mean(np.abs(b - b.mean()) >= abs(obs[k])))
        rows.append({"test": k, "observed": obs[k], "ci95_low": np.percentile(b, 2.5),
                     "ci95_high": np.percentile(b, 97.5), "p_two_sided": p})
    out = pd.DataFrame(rows)
    save(out, "analysis_bootstrap_sharpe_uti")

    print("\n=== annualised Sharpe (excess of RF) ===")
    print(pd.Series({"Q5": sharpe(d["q5"]) * np.sqrt(12), "Q1": sharpe(d["q1"]) * np.sqrt(12),
                     "Benchmark (UTI+SBI avg)": sharpe(d["bm"]) * np.sqrt(12)}).round(3).to_string())
    print(f"\nmonths: {n}")
    print(out.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
