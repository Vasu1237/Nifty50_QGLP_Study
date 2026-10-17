"""QGLP panel (member x 30-June rebalance, 2011-2025) rebuilt on CMIE ProwessDX data (s06 outputs).

Same design as s04 (features, scoring, sectors); the Upstox proxies are replaced by the measures they stood in for.

Point-in-time rule: a fiscal year is usable at rebalance t only if its annual results were announced on or before t
(Prowess board-meeting date, s06 prowess_results_dates). If no meeting was found, fall back to fy_end + 60 days
(SEBI LODR deadline) and flag it in `pit_fallback_years`.
Basis: consolidated if the company reports it for that FY, else standalone (column fund_basis).

Definitions (INR million unless stated):
  capital_employed = net worth + debt
  ROCE             = (PBT + interest expense) / capital_employed
  ROE              = owners' PAT / net worth
  D/E              = debt / net worth
  owners' PAT      = consolidated: consolidated basic EPS x (standalone PAT / standalone basic EPS), i.e. EPS times
                     the share count implied by the same Prowess EPS base, which strips minority interest;
                     standalone: PAT. If the implied share count can't be formed, consolidated PAT is used (flagged).
  shares_today     = paid-up equity shares at FY end, scaled to today's base by dividing by every NSE split/bonus
                     adjustment factor dated after the FY end (Prowess adjustment factors: XB, FV, XDB, ...).
  EPS              = owners' PAT / shares_today (one share base for all years, so growth isn't distorted by splits)
  market cap       = Prowess NSE market capitalisation on the last trading day on or before the rebalance date
  earnings yield   = owners' PAT (latest usable FY) / market cap;  PE = 1 / earnings yield
  EV/EBITDA        = (market cap + debt - cash and bank) / PBDITA   (reported, not scored)
  mom_12_1         = total return from the prior 30 June to 31 May (skips June), from Prowess NSE daily returns
  ADTV             = mean NSE traded value over the last 63 trading days, minimum 40 observations
Features (unchanged from s04):
  Q non-financials = mean( z(3-year average ROCE), z(-D/E latest) );  Q financials = z(3-year average ROE)
  G = EPS CAGR between the oldest and latest usable FY in a 3-year window (span in g_years); base EPS <= 0 -> NaN
  L = number of usable FYs (max 10) with ROCE > 15% (financials: ROE > 15%); l_window = years available
  P = earnings yield
Scoring: per rebalance date winsorize at 1%/99%, z-score within sector if the sector has >= 3 names, else universe;
composite = equal-weight mean of available z(Q), z(G), z(L), z(P).
Bank metrics (NIM, CAR, gross NPA) are carried as columns for financials but not scored: adding them would change
the agreed design.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from common import P1_CLEAN, latest, log, save
from s04_panel import FIN, PAST_SECTOR, winsor_z

ITEM = "panel_prowess"
SPLIT_TYPES = {"XB", "FV", "XBSS", "XDB", "XDBO", "SSXB", "XOSS", "XDSS"}  # change the share count; XR/XA don't


def load(name: str, **kw) -> pd.DataFrame:
    return pd.read_csv(latest(name), **kw)


def fundamentals() -> pd.DataFrame:
    f = load("prowess_fundamentals_annual", parse_dates=["fy_end"])
    has_ca = f["ca_total_income"].notna() & f["ca_net_worth"].notna()
    out = f[["co_code", "isin", "fy_end"]].copy()
    out["fund_basis"] = np.where(has_ca, "consolidated", "standalone")
    for c in ["total_income", "sales", "pat", "pbt", "pbdita", "interest_exp", "net_worth", "debt", "cash_n_st_bank_bal",
              "cf_net_frm_op_activity", "cf_purchase_fixed_ast", "basic_eps", "net_int_margin", "bd_cap_adeq_ratio_series",
              "bd_gross_npa_closing_bal"]:
        out[c] = np.where(has_ca, f.get(f"ca_{c}"), f.get(f"sa_{c}"))
    implied_sh = f["sa_pat"] / f["sa_basic_eps"]
    owners_ca = f["ca_basic_eps"] * implied_sh
    ok = has_ca & (f["sa_basic_eps"].abs() > 0) & owners_ca.notna()
    out["owners_pat"] = np.where(has_ca, np.where(ok, owners_ca, f["ca_pat"]), f["sa_pat"])
    out["owners_pat_fallback"] = has_ca & ~ok
    out["shares_fy"] = f["sa_paidup_equity_shares_in_lakhs"] * 1e5

    af = load("prowess_adjustment_factors", parse_dates=["radjfact_date"])
    af = af[af["radj_type"].isin(SPLIT_TYPES)]

    def to_today(row) -> float:
        fac = af.loc[(af["co_code"] == row["co_code"]) & (af["radjfact_date"] > row["fy_end"]), "radj_factor"]
        return row["shares_fy"] / fac.prod() if len(fac) else row["shares_fy"]

    out["shares_today"] = out.apply(to_today, axis=1)
    out["eps"] = out["owners_pat"] * 1e6 / out["shares_today"]
    out["cap_employed"] = out["net_worth"] + out["debt"].fillna(0)
    out["roce"] = (out["pbt"] + out["interest_exp"].fillna(0)) / out["cap_employed"]
    out["roe"] = out["owners_pat"] / out["net_worth"]
    out["de"] = out["debt"].fillna(0) / out["net_worth"]
    neg_nw = (out["net_worth"] <= 0).sum()
    out.loc[out["net_worth"] <= 0, ["roce", "roe", "de"]] = np.nan
    log(ITEM, "fundamentals", f"consolidated preferred; owners' PAT fallback rows={int(out['owners_pat_fallback'].sum())}; "
        f"net worth <= 0 rows set to NaN={neg_nw}; split/bonus factors applied={len(af)}", len(f), len(out))

    out["fund_source"] = "prowess"

    # Insurers (HDFC Life, SBI Life) have no rows in the Prowess annual tables (insurance accounts use a different
    # format). Fall back to the Upstox fundamentals from s03 (FY2022+ only): owners' PAT, net worth (ROE) and EPS on
    # Upstox's consistent share base. ROCE, D/E and EV/EBITDA don't apply to insurers and stay NaN.
    from s04_panel import wide_fundamentals
    cmap = load("prowess_company_map")
    missing = cmap[~cmap["co_code"].isin(out["co_code"])]
    up = wide_fundamentals()
    up = up[up["isin"].isin(missing["isin"])].merge(missing[["isin", "co_code"]], on="isin")
    if len(up):
        crore_to_mn = 10.0  # Upstox values are in INR crore
        fb = pd.DataFrame({"co_code": up["co_code"], "isin": up["isin"], "fy_end": up["fy_end"], "fund_basis": up["basis"],
                           "owners_pat": up["pat"] * up["owners_frac"] * crore_to_mn, "net_worth": up["equity"] * crore_to_mn,
                           "eps": up["eps_adj"], "fund_source": "upstox_fallback"})
        fb["roe"] = fb["owners_pat"] / fb["net_worth"]
        fb["sales"] = up["revenue"].values * crore_to_mn
        out = pd.concat([out, fb], ignore_index=True)
        log(ITEM, "insurer fallback", f"Upstox fundamentals for {missing['name'].tolist()} (FY2022+, ROE/EPS only)",
            len(missing), len(fb))

    rd = load("prowess_results_dates", parse_dates=["fy_end", "results_date"])
    out = out.merge(rd[["co_code", "fy_end", "results_date"]], on=["co_code", "fy_end"], how="left")
    out["pit_fallback"] = out["results_date"].isna()
    out["usable_from"] = out["results_date"].fillna(out["fy_end"] + pd.Timedelta(days=60))
    return out


def market() -> tuple[pd.DataFrame, pd.DataFrame]:
    px = load("prowess_prices_daily", usecols=["co_code", "isin", "date", "nse_closing_price", "nse_returns",
                                                "nse_traded_val", "nse_market_cap"], parse_dates=["date"])
    px = px.sort_values(["co_code", "date"])
    bad = (px["nse_returns"] <= 0) | (px["nse_returns"] > 3)
    px.loc[bad, "nse_returns"] = np.nan
    log(ITEM, "daily returns", f"Prowess NSE total-return relatives; implausible (<=0 or >3x) set NaN: {int(bad.sum())}", len(px), len(px))
    # Tata Motors demerger (record date 14-Oct-2025): Prowess returns treat the ex-date drop as a loss. From that
    # day use the holder-value series from s02c (TMPV + 1 TMCV share, TMCV at the implied Rs 260.75 until it listed
    # on 12-Nov-2025). These returns are price-only: dividends after the demerger are not added.
    hv = pd.read_csv(latest("demerger_holder_value_INE155A01022"), parse_dates=["date"]).sort_values("date")
    tm = px["isin"] == hv["parent_isin"].iloc[0]
    prev_close = px.loc[tm & (px["date"] < hv["date"].iloc[0]), "nse_closing_price"].iloc[-1]
    rel = hv.set_index("date")["V"] / hv["V"].shift().set_axis(hv["date"])
    rel.iloc[0] = hv["V"].iloc[0] / prev_close
    sel = tm & px["date"].isin(rel.index)
    px.loc[sel, "nse_returns"] = px.loc[sel, "date"].map(rel).values
    log(ITEM, "demerger adjust", f"Tata Motors daily returns from {hv['date'].iloc[0].date()} replaced by holder-value relatives",
        int(sel.sum()), int(sel.sum()))
    px["month_end"] = px["date"] + pd.offsets.MonthEnd(0)
    m = px.groupby(["co_code", "isin", "month_end"]).agg(gross=("nse_returns", "prod"), n=("nse_returns", "count")).reset_index()
    m = m[m["n"] > 0]
    m["ret_m"] = m["gross"] - 1
    log(ITEM, "monthly returns", "product of daily NSE total-return relatives within each calendar month", len(px), len(m))
    return px, m


def main() -> None:
    mem = load("members", parse_dates=["rebalance_date"])
    cmap = load("prowess_company_map")
    nm = cmap.set_index("name")["isin"]
    mem["isin"] = mem["isin"].fillna(mem["name"].map(nm))
    mem["sector"] = mem["sector_wiki"].fillna(mem["name"].map(PAST_SECTOR))
    mem["is_financial"] = mem["sector"] == FIN
    mem = mem.merge(cmap[["isin", "co_code"]], on="isin", how="left")
    log(ITEM, "members", f"member-rows without Prowess code={int(mem['co_code'].isna().sum())}", len(mem), len(mem))

    fu = fundamentals()
    px, mret = market()
    rows = []
    for _, r in mem.iterrows():
        t, cc = r["rebalance_date"], r["co_code"]
        rec: dict = {}
        p = px[(px["co_code"] == cc) & (px["date"] <= t)]
        if len(p) and (t - p["date"].iloc[-1]).days <= 10:
            last = p.iloc[-1]
            rec.update(px_date=last["date"].date(), price_at_rebalance=last["nse_closing_price"], mktcap_inr_mn=last["nse_market_cap"])
            tail = p["nse_traded_val"].tail(63)
            rec["adtv_3m_inr_mn"] = tail.mean() if tail.notna().sum() >= 40 else np.nan
            win = p[(p["date"] > t - pd.DateOffset(years=1)) & (p["date"] <= t - pd.DateOffset(months=1) + pd.offsets.MonthEnd(0))]
            if win["nse_returns"].notna().sum() >= 200:
                rec["mom_12_1"] = win["nse_returns"].prod() - 1
        g = fu[(fu["co_code"] == cc) & (fu["usable_from"] <= t)].sort_values("fy_end")
        rec["n_fy_usable"] = len(g)
        if len(g):
            last, last3 = g.iloc[-1], g.tail(3)
            rec.update(latest_fy=last["fy_end"].date(), fund_basis=last["fund_basis"], fund_source=last["fund_source"], results_date=last["results_date"],
                       pit_fallback_years=int(g.tail(10)["pit_fallback"].sum()),
                       roce_avg3=last3["roce"].mean(), roe_avg3=last3["roe"].mean(), de=last["de"], eps=last["eps"],
                       owners_pat=last["owners_pat"], sales=last["sales"], pbdita=last["pbdita"], debt=last["debt"],
                       cash=last["cash_n_st_bank_bal"], cfo_to_pat=last["cf_net_frm_op_activity"] / last["owners_pat"]
                       if last["owners_pat"] else np.nan, nim=last["net_int_margin"], car=last["bd_cap_adeq_ratio_series"],
                       gross_npa=last["bd_gross_npa_closing_bal"])
            metric = (g["roe"] if r["is_financial"] else g["roce"]).tail(10)
            rec["l_window"] = int(metric.notna().sum())
            rec["l_count"] = int((metric > 0.15).sum()) if rec["l_window"] else np.nan
            gw = g[g["fy_end"] >= last["fy_end"] - pd.DateOffset(years=3)]
            if len(gw) >= 2:
                e0, e1 = gw["eps"].iloc[0], gw["eps"].iloc[-1]
                yrs = (gw["fy_end"].iloc[-1] - gw["fy_end"].iloc[0]).days / 365.25
                rec["g_years"] = round(yrs, 1)
                if e0 <= 0:
                    rec["g_negative_base"] = True
                else:
                    rec["g_eps_cagr"] = (e1 / e0) ** (1 / yrs) - 1 if e1 > 0 else -1.0
        rows.append(rec)
    pan = pd.concat([mem.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    pan["earnings_yield"] = pan["owners_pat"] / pan["mktcap_inr_mn"]
    pan["pe"] = 1 / pan["earnings_yield"]
    pan["ev_ebitda"] = (pan["mktcap_inr_mn"] + pan["debt"].fillna(0) - pan["cash"].fillna(0)) / pan["pbdita"]
    pan.loc[pan["is_financial"] | (pan["pbdita"] <= 0), "ev_ebitda"] = np.nan
    pan["log_mktcap"] = np.log(pan["mktcap_inr_mn"])
    log(ITEM, "features", f"G negative-base cases={int(pan.get('g_negative_base', pd.Series(dtype=bool)).fillna(False).sum())}; "
        f"rows using fy_end+60d fallback in last 10y={int((pan['pit_fallback_years'] > 0).sum())}")

    pan["q_raw_nonfin_roce"] = np.where(~pan["is_financial"], pan["roce_avg3"], np.nan)
    pan["q_raw_nonfin_neg_de"] = np.where(~pan["is_financial"], -pan["de"], np.nan)
    pan["q_raw_fin_roe"] = np.where(pan["is_financial"], pan["roe_avg3"], np.nan)
    for c in ["q_raw_nonfin_roce", "q_raw_nonfin_neg_de", "q_raw_fin_roe", "g_eps_cagr", "l_count", "earnings_yield", "log_mktcap", "mom_12_1"]:
        pan[f"{c}_z"] = winsor_z(pan, c)
    pan["Q"] = np.where(pan["is_financial"], pan["q_raw_fin_roe_z"], pan[["q_raw_nonfin_roce_z", "q_raw_nonfin_neg_de_z"]].mean(axis=1))
    pan["G"], pan["L"], pan["P"] = pan["g_eps_cagr_z"], pan["l_count_z"], pan["earnings_yield_z"]
    pan["n_components"] = pan[["Q", "G", "L", "P"]].notna().sum(axis=1)
    pan["qglp_composite"] = pan[["Q", "G", "L", "P"]].mean(axis=1)
    pan.loc[pan["n_components"] == 0, "qglp_composite"] = np.nan

    cov = pan.groupby("rebalance_date").agg(members=("name", "size"), with_price=("price_at_rebalance", "count"),
                                            with_fund=("latest_fy", "count"), with_all4=("n_components", lambda s: int((s == 4).sum())),
                                            with_composite=("qglp_composite", "count")).reset_index()
    log(ITEM, "coverage", cov.to_string(index=False).replace("\n", " | "))
    save(cov, "coverage_prowess_by_rebalance")
    save(pan, ITEM)

    # Monthly returns: Prowess stock total returns + existing benchmark price indices + IIMA factors.
    st = mret.rename(columns={"isin": "id"})[["month_end", "id", "ret_m"]].assign(kind="stock_total_return_prowess")
    bm = load("returns_monthly_benchmarks", parse_dates=["month_end"]).rename(columns={"series": "id"})
    bm = bm[["month_end", "id", "ret_m"]].assign(kind="benchmark_price_index")
    ff = pd.read_csv(sorted(P1_CLEAN.glob("item06_ff_factors_2*.csv"))[-1], parse_dates=["month_end"])
    fl = ff.melt(id_vars="month_end", value_vars=["MF", "SMB", "HML", "WML", "RF"], var_name="id", value_name="ret_m")
    fl["ret_m"] = fl["ret_m"] / 100
    fl["id"] = fl["id"].replace({"MF": "MKT_RF"})
    fl["kind"] = "factor_IIMA_release_2025-12"
    allr = pd.concat([st, bm, fl], ignore_index=True)
    allr = allr[allr["month_end"] >= "2010-01-31"]
    save(allr, "returns_monthly_prowess")


if __name__ == "__main__":
    main()
