"""P1 analysis on the ProwessDX panel (s07 outputs).

Design (unchanged from the agreed P1 design):
  - Universe: Nifty 50 members at each 30-June rebalance, 2011-2025 (point-in-time).
  - Signals (known at the rebalance): Q, G, L, P, composite, log market cap, 12-1 momentum.
  - Portfolios: equal-weight quintiles on the composite, held for 12 months (July to June), then re-formed.
  - Benchmark: cap-weighted proxy of the same members (weights = market cap at rebalance). The official Nifty 50
    TRI is not available, see README; the NIFTY50_PRICE index (price only) is used as a check.
  - Tests: four-factor alpha (IIMA MKT-RF, SMB, HML, WML) with Newey-West (12 lags) on the quintiles and long-short;
    Fama-MacBeth cross-sectional regressions; block-bootstrap Sharpe comparison vs the benchmark proxy;
    Holm correction across the family of QGLP tests.

No look-ahead: scores use only fiscal years whose results were announced by the rebalance date (s07), prices and
market caps are the last close on or before 30 June, momentum uses data to 31 May. Factors end Dec 2025, so alpha
regressions run to Dec 2025; the holding windows and bootstrap run to Jun 2026.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from common import latest, log, save

ITEM = "s08_analysis"
NW_LAGS = 12  # holding period is 12 months, so monthly returns overlap by up to 12
BOOT_REPS = 5000
BLOCK = 12
SEED = 20261016
FACTORS = ["MKT_RF", "SMB", "HML", "WML"]
Q_COLS = ["Q", "G", "L", "P"]


def nw_ols(y, X, lags=NW_LAGS):
    """OLS with a constant and Newey-West standard errors. Returns (coefs, se) with the constant first."""
    y = np.asarray(y, float)
    X = np.asarray(X, float)
    if X.ndim == 1:
        X = X[:, None]
    X = np.column_stack([np.ones(len(y)), X])
    xtx_inv = np.linalg.inv(X.T @ X)
    b = xtx_inv @ X.T @ y
    e = y - X @ b
    S = (X * e[:, None]).T @ (X * e[:, None])
    for lag in range(1, lags + 1):
        w = 1 - lag / (lags + 1)
        G = (X[lag:] * e[lag:, None]).T @ (X[:-lag] * e[:-lag, None])
        S += w * (G + G.T)
    V = xtx_inv @ S @ xtx_inv
    return b, np.sqrt(np.diag(V))


def pval(t):
    return math.erfc(abs(t) / math.sqrt(2))  # normal approximation (T is 100+ months)


def holding_rebalance(m, rbs):
    for r in sorted(rbs, reverse=True):
        if r < m <= r + pd.DateOffset(months=12):
            return r
    return None


def main() -> None:
    rng = np.random.default_rng(SEED)
    panel = pd.read_csv(latest("panel_prowess"), parse_dates=["rebalance_date"])
    ret = pd.read_csv(latest("returns_monthly_prowess"), parse_dates=["month_end"])
    stocks = ret[ret["kind"].str.startswith("stock")].pivot(index="month_end", columns="id", values="ret_m").sort_index()
    fac = ret[ret["kind"].str.startswith("factor")].pivot(index="month_end", columns="id", values="ret_m").sort_index()
    idx = ret[ret["kind"].str.startswith("benchmark")].pivot(index="month_end", columns="id", values="ret_m").sort_index()
    rbs = sorted(panel["rebalance_date"].unique())
    log(ITEM, "inputs", f"panel {panel.shape}, stock months {stocks.shape}, factor months {fac.shape}", len(panel), len(panel))

    # ---- holding-window assignment -------------------------------------------------------------
    months = stocks.index
    rb_of = pd.Series({m: holding_rebalance(m, rbs) for m in months})
    hold_months = rb_of.dropna().index

    # ---- cap-weighted benchmark proxy and quintile portfolios ---------------------------------
    bench, quint_rows, mret = [], [], []
    for m in hold_months:
        r = rb_of[m]
        g = panel[panel["rebalance_date"] == r].dropna(subset=["isin", "mktcap_inr_mn"])
        rets = stocks.loc[m, [i for i in g["isin"] if i in stocks.columns]].dropna()
        w = g.set_index("isin").loc[rets.index, "mktcap_inr_mn"]
        bench.append((m, float((rets * w / w.sum()).sum())))
        comp = g.set_index("isin")["qglp_composite"].dropna()
        comp = comp[comp.index.isin(rets.index)]
        if len(comp) >= 10:
            qlab = pd.qcut(comp.rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
            for q in range(1, 6):
                names = qlab[qlab == q].index
                quint_rows.append((m, q, float(rets[names].mean())))
    bench = pd.Series(dict(bench), name="bench")
    quint = pd.DataFrame(quint_rows, columns=["month_end", "q", "ret"]).pivot(index="month_end", columns="q", values="ret")
    quint.columns = [f"Q{c}" for c in quint.columns]
    quint["LS_Q5_minus_Q1"] = quint["Q5"] - quint["Q1"]
    quint["BENCH_proxy"] = bench
    quint["RF"] = fac["RF"].reindex(quint.index)
    save(quint.reset_index(), "analysis_monthly_returns")

    # benchmark check against the Nifty 50 price index (price only, so expect the proxy to run about 1%/yr higher)
    chk = pd.concat([bench, idx["NIFTY50_PRICE"]], axis=1).dropna()
    corr = chk.corr().iloc[0, 1]
    gap = (chk.iloc[:, 0] - chk.iloc[:, 1]).mean() * 12
    log(ITEM, "benchmark check", f"proxy vs NIFTY50_PRICE: monthly corr={corr:.3f}; mean gap={gap*100:.2f}%/yr (expected ~ dividend yield)")

    # ---- performance summary ------------------------------------------------------------------
    rf = quint["RF"]
    rows = []
    for c in ["Q1", "Q2", "Q3", "Q4", "Q5", "LS_Q5_minus_Q1", "BENCH_proxy"]:
        x = quint[c] - (0 if c.startswith("LS") else rf)
        x = x.dropna()
        ann_m, ann_s = x.mean() * 12, x.std(ddof=1) * np.sqrt(12)
        rows.append({"portfolio": c, "n_months": len(x), "ann_excess_return": ann_m, "ann_vol": ann_s,
                     "sharpe": ann_m / ann_s if ann_s else np.nan})
    perf = pd.DataFrame(rows)
    save(perf, "analysis_performance_summary")

    # ---- four-factor alpha (factor sample ends Dec 2025) -----------------------------------------
    alpha_rows = []
    fmask = quint.index <= fac.index.max()
    for c in ["Q1", "Q2", "Q3", "Q4", "Q5", "LS_Q5_minus_Q1", "BENCH_proxy"]:
        y = quint[c] - (0 if c.startswith("LS") else rf)
        d = pd.concat([y.rename("y"), fac[FACTORS]], axis=1).reindex(quint.index).dropna()
        b, se = nw_ols(d["y"], d[FACTORS])
        alpha_rows.append({"portfolio": c, "n_months": len(d), "alpha_ann": b[0] * 12, "alpha_t_NW": b[0] / se[0],
                           "alpha_p": pval(b[0] / se[0]), **{f"beta_{f}": b[i + 1] for i, f in enumerate(FACTORS)},
                           **{f"t_{f}": b[i + 1] / se[i + 1] for i, f in enumerate(FACTORS)}})
    alpha = pd.DataFrame(alpha_rows)
    save(alpha, "analysis_four_factor_alpha")

    # ---- Fama-MacBeth ---------------------------------------------------------------------------
    fm_rows = []
    slopes = {k: [] for k in Q_COLS + ["qglp_composite", "joint"]}
    for m in hold_months:
        r = rb_of[m]
        g = panel[panel["rebalance_date"] == r].copy()
        g = g.dropna(subset=["isin"]).set_index("isin")
        y = stocks.loc[m].reindex(g.index)
        g = g.assign(ret=y).dropna(subset=["ret"])
        for k in Q_COLS + ["qglp_composite"]:
            d = g.dropna(subset=[k])
            if len(d) >= 20:
                b, _ = nw_ols(d["ret"], d[[k]])
                slopes[k].append((m, b[1]))
        d = g.dropna(subset=Q_COLS + ["log_mktcap", "mom_12_1"])
        if len(d) >= 30:
            b, _ = nw_ols(d["ret"], d[Q_COLS + ["log_mktcap", "mom_12_1"]])
            slopes["joint"].append((m, b))
    for k in Q_COLS + ["qglp_composite"]:
        s = pd.Series(dict(slopes[k]))
        b, se = nw_ols(s, np.zeros((len(s), 0)))
        fm_rows.append({"signal": k, "months": len(s), "mean_slope_per_month": b[0], "t_NW": b[0] / se[0],
                        "p": pval(b[0] / se[0])})
    jb = np.array([v for _, v in slopes["joint"]])
    names = Q_COLS + ["log_mktcap", "mom_12_1"]
    for i, n in enumerate(["const"] + names):
        b, se = nw_ols(jb[:, i], np.zeros((len(jb), 0)))
        fm_rows.append({"signal": f"joint:{n}", "months": len(jb), "mean_slope_per_month": b[0], "t_NW": b[0] / se[0],
                        "p": pval(b[0] / se[0])})
    fm = pd.DataFrame(fm_rows)
    save(fm, "analysis_fama_macbeth")

    # ---- block bootstrap: Sharpe of Q5 vs benchmark proxy, and L/S mean -------------------------
    d = pd.concat([(quint["Q5"] - rf).rename("q5"), (quint["BENCH_proxy"] - rf).rename("bm"),
                   quint["LS_Q5_minus_Q1"].rename("ls")], axis=1).dropna()
    n, nb = len(d), int(np.ceil(len(d) / BLOCK))
    diffs, ls_means = [], []
    for _ in range(BOOT_REPS):
        starts = rng.integers(0, n, nb)
        ix = np.concatenate([(np.arange(s, s + BLOCK) % n) for s in starts])[:n]
        sample = d.iloc[ix]
        sh = lambda x: x.mean() / x.std(ddof=1)
        diffs.append(sh(sample["q5"]) - sh(sample["bm"]))
        ls_means.append(sample["ls"].mean())
    diffs = np.array(diffs)
    ls_means = np.array(ls_means)
    obs_diff = d["q5"].mean() / d["q5"].std(ddof=1) - d["bm"].mean() / d["bm"].std(ddof=1)
    obs_ls = d["ls"].mean()
    # p-value for "Q5 Sharpe equals benchmark Sharpe": centre the bootstrap distribution at zero
    p_sh = float(np.mean(np.abs(diffs - diffs.mean()) >= abs(obs_diff)))
    # p-value for "L/S mean is zero": centre at zero
    p_ls = float(np.mean(np.abs(ls_means - ls_means.mean()) >= abs(obs_ls)))
    boot = pd.DataFrame([
        {"test": "Sharpe(Q5 excess) - Sharpe(benchmark proxy)", "observed": obs_diff,
         "ci95_low": np.percentile(diffs, 2.5), "ci95_high": np.percentile(diffs, 97.5), "p_two_sided": p_sh},
        {"test": "mean monthly return, Q5 minus Q1", "observed": obs_ls,
         "ci95_low": np.percentile(ls_means, 2.5), "ci95_high": np.percentile(ls_means, 97.5), "p_two_sided": p_ls},
    ])
    save(boot, "analysis_bootstrap")

    # ---- multiple testing: Holm across the QGLP family --------------------------------------------
    fam = []
    for _, r in fm[fm["signal"].isin(Q_COLS + ["qglp_composite"])].iterrows():
        fam.append((f"FM slope: {r['signal']}", r["p"]))
    ls_alpha = alpha[alpha["portfolio"] == "LS_Q5_minus_Q1"].iloc[0]
    fam.append(("4F alpha: Q5 minus Q1", ls_alpha["alpha_p"]))
    fam.append(("Sharpe: Q5 vs benchmark", p_sh))
    fam.sort(key=lambda t: t[1])
    m_tests = len(fam)
    holm, running = [], 0.0
    for i, (name, p) in enumerate(fam):
        adj = min(1.0, (m_tests - i) * p)
        running = max(running, adj)
        holm.append({"test": name, "p_raw": p, "p_holm": running, "reject_5pct": running < 0.05})
    mt = pd.DataFrame(holm)
    save(mt, "analysis_multiple_testing_holm")

    print("\n=== performance (annualised, excess of RF) ===")
    print(perf.round(3).to_string(index=False))
    print("\n=== four-factor alpha (NW 12 lags) ===")
    print(alpha[["portfolio", "n_months", "alpha_ann", "alpha_t_NW", "alpha_p"]].round(4).to_string(index=False))
    print("\n=== Fama-MacBeth (monthly slope, NW t) ===")
    print(fm.round(4).to_string(index=False))
    print("\n=== bootstrap ===")
    print(boot.round(4).to_string(index=False))
    print("\n=== Holm ===")
    print(mt.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
