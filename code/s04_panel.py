"""D/F + feature engineering + merged panel (ISIN x rebalance date) + combined monthly return file.

Point-in-time rule: a fiscal year is usable at rebalance t only if fy_end + 60 days <= t (SEBI LODR deadline;
announcement dates are NOT verified - see s03). Basis: consolidated if present for that FY, else standalone.

Definitions (all PROXIES forced by the fields Upstox exposes - no interest, D&A, debt, cash split):
  capital_employed = Total Assets - Current Liabilities
  ROCE_proxy       = Profit Before Tax / capital_employed          (true ROCE adds back interest -> proxy is LOWER
                                                                    for leveraged firms)
  ROE              = Profit After Tax / Equity Capital (Upstox "Equity Capital" = total shareholders' equity)
  DE_proxy         = Non-Current Liabilities / Equity Capital       (includes non-debt liabilities)
  shares_proxy     = TODAY's share count = standalone PAT/EPS of latest FY (see wide_fundamentals); EPS used is
                     eps_adj = PAT x owners_frac / shares_now (Upstox EPS history mixes split/bonus bases)
  mktcap           = price_at_rebalance (adjusted) x shares_proxy of latest usable FY
  PE               = price_at_rebalance / EPS_basic(latest usable FY);  earnings_yield = 1/PE
  EV/EBITDA        = NOT COMPUTABLE (no D&A, no debt, no cash split in balance sheet) -> column kept, all NaN
Features:
  Q (non-financials) = mean( z(avg ROCE_proxy over up to 3 usable FYs), -z(DE_proxy latest) )
  Q (financials)     = z(avg ROE over up to 3 usable FYs)   [banks/NBFCs/insurers scored separately: NIM, GNPA, CAR
                        unavailable from any accessible source]
  G = EPS CAGR between the oldest and latest usable FY (target 3 years; actual span reported in g_years);
      if base EPS <= 0 -> G = NaN and g_negative_base = True (counted in the log)
  L = number of usable FYs with ROCE_proxy > 15% (financials: ROE > 15%); l_window = years available (target 10)
  P = earnings_yield
  controls: log_mktcap, mom_12_1 (from s02)
Scoring per rebalance date: winsorize each raw feature at 1%/99% across the cross-section, then z-score within
sector if the sector has >= 3 non-null names, else within the whole universe. composite = equal-weight mean of
available z(Q), z(G), z(L), z(P) (n_components reported). No weight tuning.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from common import P1_CLEAN, latest, log, save

FIN = "Financial Services"
PAST_SECTOR = {  # analyst-assigned NSE macro sector for names not in the current Wikipedia constituent table
    "Aurobindo Pharma": "Healthcare", "BHEL": "Capital Goods", "Bharti Infratel": "Telecommunication",
    "Bosch India": "Automobile and Auto Components", "Britannia Industries": "Fast Moving Consumer Goods",
    "Divi's Laboratories": "Healthcare", "GAIL": "Oil, Gas & Consumable Fuels", "HDFC": FIN,
    "Hindustan Petroleum": "Oil, Gas & Consumable Fuels", "Idea Cellular": "Telecommunication",
    "Indiabulls Housing Finance": FIN, "Indian Oil Corporation": "Oil, Gas & Consumable Fuels", "IndusInd Bank": FIN,
    "LTIMindtree": "Information Technology", "Lupin": "Healthcare", "NMDC": "Metals & Mining", "Punjab National Bank": FIN,
    "Reliance Capital": FIN, "Reliance Communications": "Telecommunication", "Reliance Infrastructure": "Power",
    "Reliance Power": "Power", "Shree Cement": "Construction Materials", "Siemens India": "Capital Goods",
    "Steel Authority of India": "Metals & Mining", "Tata Power": "Power", "UPL": "Chemicals",
    "United Spirits": "Fast Moving Consumer Goods", "Vedanta": "Metals & Mining", "Yes Bank": FIN,
    "Zee Entertainment Enterprises": "Media, Entertainment & Publication", "ACC": "Construction Materials",
    "Ambuja Cements": "Construction Materials", "Bank of Baroda": FIN, "DLF": "Realty",
    "Jindal Steel & Power": "Metals & Mining", "Bharat Petroleum": "Oil, Gas & Consumable Fuels",
    "Hero MotoCorp": "Automobile and Auto Components", "Cairn India": "Oil, Gas & Consumable Fuels", "IDFC": FIN,
    "JP Associates": "Construction", "Ranbaxy Laboratories": "Healthcare", "Sterlite Industries": "Metals & Mining",
    "Wipro": "Information Technology", "IndusInd": FIN, "Tata Motors": "Automobile and Auto Components",
}
LINES = {"Profit Before Tax": "pbt", "Profit After Tax": "pat", "EPS - Basic": "eps", "Total Assets": "ta",
         "total_asset": "ta2", "Current Liabilities": "cl", "Non-Current Liabilities": "ncl", "Equity Capital": "equity",
         "Revenue": "revenue", "Tax": "tax", "Cash flow from Operations": "cfo", "Cash (End of the year)": "cash"}


def wide_fundamentals() -> pd.DataFrame:
    f = pd.read_csv(latest("fundamentals_long_raw"), parse_dates=["fy_end", "assumed_public_by"])
    f = f[f["line"].isin(LINES)]
    f["field"] = f["line"].map(LINES)
    w = f.pivot_table(index=["isin", "fy_end", "basis"], columns="field", values="value", aggfunc="first").reset_index()
    w["ta"] = w["ta"].fillna(w.get("ta2"))
    w["basis_rank"] = (w["basis"] == "standalone").astype(int)  # prefer consolidated
    w = w.sort_values(["isin", "fy_end", "basis_rank"]).drop_duplicates(["isin", "fy_end"])
    w["roce"] = w["pbt"] / (w["ta"] - w["cl"])
    w["roe"] = w["pat"] / w["equity"]
    w["de"] = w["ncl"] / w["equity"]
    # --- consistent per-share basis (Upstox EPS mixes pre/post split/bonus bases across years, verified on
    # RELIANCE FY23 98.59 vs FY24 51.45, BAJFINANCE FY24 236.89 vs FY25 26.89, HDFCBANK FY24 90.42 vs FY25 46.41).
    # shares_now  = standalone PAT / standalone EPS of the latest FY (no minority interest in standalone) - today's
    #               share base, the same base as Upstox's back-adjusted prices.
    # owners_frac = consolidated EPS x shares_now / consolidated PAT at the latest FY (strips minority interest),
    #               clipped to [0.5, 1.05] and assumed constant over FY22-FY26.
    # eps_adj(FY) = PAT(FY) x owners_frac / shares_now  -> growth = PAT growth (ignores issuance/buybacks: flagged).
    sa = f[(f["basis"] == "standalone") & f["field"].isin(["pat", "eps"])].pivot_table(
        index=["isin", "fy_end"], columns="field", values="value", aggfunc="first").reset_index()
    sa = sa[(sa["eps"] > 0) & (sa["pat"] > 0)].sort_values("fy_end").groupby("isin").tail(1)
    shares_now = (sa["pat"] / sa["eps"]).set_axis(sa["isin"])
    lastc = w.sort_values("fy_end").groupby("isin").tail(1).set_index("isin")
    frac = (lastc["eps"] * shares_now.reindex(lastc.index) / lastc["pat"]).clip(0.5, 1.05)
    frac = frac.where(lastc["basis"] == "consolidated", 1.0).fillna(1.0)
    w["shares_now"] = w["isin"].map(shares_now)
    w["shares_now"] = w["shares_now"].fillna(w["isin"].map((lastc["pat"] / lastc["eps"]).where(lastc["eps"] > 0)))
    w["owners_frac"] = w["isin"].map(frac)
    w["eps_adj"] = w["pat"] * w["owners_frac"] / w["shares_now"]
    w["shares"] = w["shares_now"]
    log("panel", "fundamentals_wide", "consolidated preferred; ROCE=PBT/(TA-CL); ROE=PAT/Equity; DE=NCL/Equity; "
        "eps_adj=PAT*owners_frac/shares_now (consistent share base)", len(f), len(w))
    return w


def winsor_z(df: pd.DataFrame, col: str) -> pd.Series:
    out = pd.Series(np.nan, index=df.index)
    for d, g in df.groupby("rebalance_date"):
        x = g[col].astype(float)
        if x.notna().sum() < 3:
            continue
        lo, hi = x.quantile([0.01, 0.99])
        x = x.clip(lo, hi)
        for sec, gs in g.groupby("sector"):
            idx = gs.index
            # A sector where every name has the same value (e.g. all IT firms at L = 10/10) has zero spread:
            # score them all 0 (average) instead of dividing by zero.
            if x[idx].notna().sum() >= 3:
                sd = x[idx].std(ddof=0)
                out[idx] = (x[idx] - x[idx].mean()) / sd if sd > 0 else (x[idx] * 0).where(x[idx].notna())
            else:
                out[idx] = (x[idx] - x.mean()) / x.std(ddof=0)
                df.loc[idx, f"{col}_z_scope"] = "universe"
        df.loc[df["rebalance_date"] == d, f"{col}_z_scope"] = df.loc[df["rebalance_date"] == d, f"{col}_z_scope"].fillna("sector")
    return out


def main() -> None:
    mem = pd.read_csv(latest("members"), parse_dates=["rebalance_date"])
    mem["sector"] = mem["sector_wiki"].fillna(mem["name"].map(PAST_SECTOR))
    mem["sector_source"] = np.where(mem["sector_wiki"].notna(), "Wikipedia current NSE sector (not point-in-time)",
                                    np.where(mem["sector"].notna(), "analyst-assigned NSE macro sector", "MISSING"))
    lq = pd.read_csv(latest("liquidity_momentum_at_rebalance"), parse_dates=["rebalance_date"])
    pan = mem.merge(lq, on=["rebalance_date", "isin"], how="left")
    pan["is_financial"] = pan["sector"] == FIN
    w = wide_fundamentals()
    rows = []
    neg_base = 0
    for i, r in pan.iterrows():
        g = w[(w["isin"] == r["isin"]) & (w["fy_end"] + pd.Timedelta(days=60) <= r["rebalance_date"])].sort_values("fy_end")
        rec = {"n_fy_usable": len(g), "latest_fy": g["fy_end"].iloc[-1].date() if len(g) else None}
        if len(g):
            last, last3 = g.iloc[-1], g.tail(3)
            rec.update(roce_avg3=last3["roce"].mean(), roe_avg3=last3["roe"].mean(), de=last["de"], eps=last["eps_adj"],
                       eps_reported=last["eps"], owners_frac=last["owners_frac"],
                       revenue=last["revenue"], pat=last["pat"], cfo=last.get("cfo"), shares_proxy=last["shares"],
                       cfo_to_pat=last.get("cfo") / last["pat"] if last["pat"] else np.nan, fund_basis=last["basis"])
            metric = g["roe"] if r["is_financial"] else g["roce"]
            rec["l_count"] = int((metric.tail(10) > 0.15).sum())
            rec["l_window"] = int(metric.tail(10).notna().sum())
            if len(g) >= 2:
                e0, e1, yrs = g["eps_adj"].iloc[0], g["eps_adj"].iloc[-1], (g["fy_end"].iloc[-1] - g["fy_end"].iloc[0]).days / 365.25
                rec["g_years"] = round(yrs, 1)
                if e0 <= 0:
                    rec["g_negative_base"] = True
                    neg_base += 1
                else:
                    rec["g_eps_cagr"] = (e1 / e0) ** (1 / yrs) - 1 if e1 > 0 else -1.0
        rows.append(rec)
    pan = pd.concat([pan, pd.DataFrame(rows, index=pan.index)], axis=1)
    pan["mktcap_cr"] = pan["price_at_rebalance"] * pan["shares_proxy"]
    pan["log_mktcap"] = np.log(pan["mktcap_cr"])
    pan["pe"] = pan["price_at_rebalance"] / pan["eps"]
    pan["earnings_yield"] = pan["eps"] / pan["price_at_rebalance"]
    pan["ev_ebitda"] = np.nan
    log("panel", "features", f"G negative-base cases: {neg_base}; EV/EBITDA not computable (no D&A/debt)")

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

    sec = pan.groupby(["rebalance_date", "sector"]).size().rename("n_in_sector").reset_index()
    pan = pan.merge(sec, on=["rebalance_date", "sector"], how="left")
    pan["sector_lt3_flag"] = pan["n_in_sector"] < 3
    cov = pan.groupby("rebalance_date").agg(members=("name", "size"), with_isin=("isin", "count"),
                                            with_price=("price_at_rebalance", "count"), with_fund=("latest_fy", "count"),
                                            with_composite=("qglp_composite", "count")).reset_index()
    log("panel", "coverage", cov.to_string(index=False).replace("\n", " | "))
    save(cov, "coverage_by_rebalance_date")
    save(pan, "panel")
    pan.to_parquet(str(latest("panel")).replace(".csv", ".parquet"), index=False)

    # combined monthly returns: stocks + benchmarks + IIMA factors + RF
    st = pd.read_csv(latest("returns_monthly_stocks"), parse_dates=["month_end"])
    st = st.rename(columns={"isin": "id"})[["month_end", "id", "ret_m"]].assign(kind="stock_price_return")
    bm = pd.read_csv(latest("returns_monthly_benchmarks"), parse_dates=["month_end"])
    bm = bm.rename(columns={"series": "id"})[["month_end", "id", "ret_m"]].assign(kind="benchmark_price_index")
    ff = pd.read_csv(sorted(P1_CLEAN.glob("item06_ff_factors_2*.csv"))[-1], parse_dates=["month_end"])
    fl = ff.melt(id_vars="month_end", value_vars=["MF", "SMB", "HML", "WML", "RF"], var_name="id", value_name="ret_m")
    fl["ret_m"] = fl["ret_m"] / 100
    fl["id"] = fl["id"].replace({"MF": "MKT_RF"})
    fl["kind"] = "factor_IIMA_release_2025-12"
    allr = pd.concat([st, bm, fl], ignore_index=True)
    allr = allr[allr["month_end"] >= "2010-01-31"]
    log("panel", "returns", "stocks (price ret), Nifty50/500 price-index ret, IIMA MKT_RF/SMB/HML/WML/RF (% -> decimal)", rows_out=len(allr))
    save(allr, "returns_monthly_all")
    allr.to_parquet(str(latest("returns_monthly_all")).replace(".csv", ".parquet"), index=False)


if __name__ == "__main__":
    main()
