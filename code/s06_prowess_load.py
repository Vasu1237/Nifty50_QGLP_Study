"""Load the CMIE ProwessDX extract (Specification 130245, request 1, vintage Sep 2026) into clean P1 tables.

Source: CMIE ProwessDX (IIM Indore subscription, licensed; not redistributable). The extract was built in the
ProwessDX web interface: company set "Nifty Companies Superset" (141 past and present Nifty members), 164 indicators
over 9 tables, INR million, ISO dates. It cost 2 Hits; a first identical submission errored and also cost 2 Hits.
Raw files: raw/prowess/spec130245_req1/tab<N>/ (pipe-delimited *_dat.txt plus *_map.txt with field labels and units).

Outputs (clean/):
  prowess_company_map          all 90 members -> Prowess co_code (ISIN match; 5 delisted names via NO_ISIN)
  prowess_fundamentals_annual  standalone (sa_) and consolidated (ca_) annual statements, FY2005-FY2026
  prowess_results_dates        first board meeting after each FY end that approved annual/Q4 results
  prowess_prices_daily         NSE close, NSE daily return (price relative), traded value, market cap, shares
  prowess_dividends            dividend declarations with NSE ex-dates
  prowess_adjustment_factors   NSE adjustment factors (splits, bonuses, rights)
  prowess_classification       history of Prowess industry / NIC classification (point-in-time sector)
  prowess_coverage             per-company coverage of every table
"""
from __future__ import annotations

import pandas as pd

from common import CLEAN, RAW, latest, log, save

SPEC = RAW / "prowess" / "spec130245_req1"
STAMP = "20261015_225326"
ITEM = "s06_prowess"
NO_ISIN = {  # membership name -> Prowess co_code (identity table)
    "Cairn India": 371877, "IDFC": 100709, "JP Associates": 108841,
    "Ranbaxy Laboratories": 193553, "Sterlite Industries": 236919,
}


def table(tab: int) -> pd.DataFrame:
    f = SPEC / f"tab{tab}" / f"130245_1_{tab}_{STAMP}_dat.txt"
    df = pd.read_csv(f, sep="|", na_values=["NA"], low_memory=False)
    df.columns = [c.strip() for c in df.columns]
    log(ITEM, f"read table {tab}", f.name, rows_out=len(df))
    return df


def keep(df: pd.DataFrame, code_col: str, codes: set[int], what: str) -> pd.DataFrame:
    out = df[df[code_col].isin(codes)].copy()
    log(ITEM, f"filter {what}", "keep the study members (drop other Nifty Superset names)", len(df), len(out))
    return out


def main() -> None:
    members = pd.read_csv(latest("members"), dtype=str)
    ident = table(5)
    ident["co_code"] = ident["co_code"].astype(int)
    # Members with no ISIN in our membership file (delisted before the ISIN sources cover them): take the ISIN
    # from Prowess, matched by name, checked against the Prowess identity table by hand.
    no_isin = members["isin"].isna()
    fill = members.loc[no_isin, "name"].map(NO_ISIN).map(ident.set_index("co_code")["isin_code_equity"])
    members.loc[no_isin, "isin"] = fill
    log(ITEM, "fill missing ISINs", f"{no_isin.sum()} member-rows via NO_ISIN name map; still missing={members['isin'].isna().sum()}",
        len(members), len(members))
    m85 = members.sort_values("rebalance_date").groupby("isin", as_index=False).agg(
        name=("name", "last"), first_rebalance=("rebalance_date", "min"), last_rebalance=("rebalance_date", "max"))

    cmap = m85.merge(ident.rename(columns={"isin_code_equity": "isin"}), on="isin", how="left")
    unmatched = cmap["co_code"].isna().sum()
    log(ITEM, "map ISIN -> co_code", f"exact ISIN match; unmatched={unmatched}", len(m85), len(cmap))
    if unmatched:
        raise SystemExit(f"{unmatched} member ISINs not found in Prowess identity table")
    cmap["co_code"] = cmap["co_code"].astype(int)
    save(cmap, "prowess_company_map")
    codes = set(cmap["co_code"])
    name_of = cmap.set_index("co_code")["isin"]

    # Annual statements: standalone + consolidated side by side on (co_code, fiscal year end).
    sa = keep(table(70), "sa_finance1_cocode", codes, "standalone annual")
    ca = keep(table(75), "ca_finance1_cocode", codes, "consolidated annual")
    sa = sa.rename(columns={"sa_finance1_cocode": "co_code", "sa_finance1_year": "fy_end"}).drop(columns="sa_company_name")
    ca = ca.rename(columns={"ca_finance1_cocode": "co_code", "ca_finance1_year": "fy_end"}).drop(columns="ca_company_name")
    fund = sa.merge(ca, on=["co_code", "fy_end"], how="outer")
    fund.insert(1, "isin", fund["co_code"].map(name_of))
    fund["fy_end"] = pd.to_datetime(fund["fy_end"])
    fund = fund.sort_values(["co_code", "fy_end"])
    log(ITEM, "merge SA+CA", "outer join on co_code, fy_end; units INR million unless stated in map files", len(sa) + len(ca), len(fund))
    save(fund, "prowess_fundamentals_annual")

    # Results dates: earliest board meeting within 180 days after FY end whose purpose covers audited/annual
    # accounts or quarterly results (Q4 is approved with the annual accounts).
    bm = keep(table(25), "boardmt_cocode", codes, "board meetings").rename(columns={"boardmt_cocode": "co_code"})
    bm["bm_date"] = pd.to_datetime(bm["bm_date"])
    bm = bm[bm["bm_abbv_purpose"].str.contains(r"\bAU\b|ACT|QTR|AUDIT", regex=True, na=False)]
    fy = fund[["co_code", "fy_end"]].drop_duplicates()
    cand = fy.merge(bm[["co_code", "bm_date", "bm_abbv_purpose"]], on="co_code")
    cand = cand[(cand["bm_date"] > cand["fy_end"]) & (cand["bm_date"] <= cand["fy_end"] + pd.Timedelta(days=180))]
    res = cand.sort_values("bm_date").groupby(["co_code", "fy_end"], as_index=False).first()
    res = fy.merge(res, on=["co_code", "fy_end"], how="left").rename(columns={"bm_date": "results_date"})
    res["lag_days"] = (res["results_date"] - res["fy_end"]).dt.days
    res.insert(1, "isin", res["co_code"].map(name_of))
    log(ITEM, "results dates", f"first AU/ACT/QTR board meeting within 180d of FY end; found {res['results_date'].notna().sum()} of {len(res)}",
        len(fy), len(res))
    save(res, "prowess_results_dates")

    px = keep(table(120), "co_code", codes, "daily trading data").drop(columns="company_name")
    px = px.rename(columns={"co_stkdate": "date"})
    px.insert(1, "isin", px["co_code"].map(name_of))
    save(px, "prowess_prices_daily")

    dv = keep(table(125), "dividend_cocode", codes, "dividends").rename(columns={"dividend_cocode": "co_code"})
    dv.insert(1, "isin", dv["co_code"].map(name_of))
    save(dv, "prowess_dividends")

    af = keep(table(130), "radjfact_cocode", codes, "adjustment factors").rename(columns={"radjfact_cocode": "co_code"})
    af = af[af["radj_exch"] == "NSE"]
    af.insert(1, "isin", af["co_code"].map(name_of))
    save(af, "prowess_adjustment_factors")

    cl = keep(table(7), "coprd_company_code", codes, "classification history").rename(columns={"coprd_company_code": "co_code"})
    cl.insert(1, "isin", cl["co_code"].map(name_of))
    save(cl, "prowess_classification")

    cap = keep(table(155), "chistory_cocode", codes, "changes in capital").rename(columns={"chistory_cocode": "co_code"})
    cap.insert(1, "isin", cap["co_code"].map(name_of))
    save(cap, "prowess_capital_changes")

    # Coverage: what each table offers for each of the 85 names.
    fy_ok = fund.assign(has_sa=fund["sa_total_income"].notna(), has_ca=fund["ca_total_income"].notna())
    cov = cmap[["isin", "co_code", "name", "first_rebalance", "last_rebalance", "nse_delist_date"]].copy()
    g = fy_ok.groupby("co_code")
    cov["sa_fy_first"] = cov["co_code"].map(fy_ok[fy_ok.has_sa].groupby("co_code")["fy_end"].min())
    cov["sa_fy_last"] = cov["co_code"].map(fy_ok[fy_ok.has_sa].groupby("co_code")["fy_end"].max())
    cov["sa_years"] = cov["co_code"].map(g["has_sa"].sum())
    cov["ca_years"] = cov["co_code"].map(g["has_ca"].sum())
    pxg = px[px["nse_closing_price"].notna()].groupby("co_code")["date"]
    cov["px_first"] = cov["co_code"].map(pxg.min())
    cov["px_last"] = cov["co_code"].map(pxg.max())
    cov["px_days"] = cov["co_code"].map(pxg.size())
    cov["results_dates"] = cov["co_code"].map(res.groupby("co_code")["results_date"].count())
    cov["dividends"] = cov["co_code"].map(dv.groupby("co_code").size()).fillna(0).astype(int)
    save(cov, "prowess_coverage")


if __name__ == "__main__":
    main()
