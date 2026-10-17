"""Deliverables 4 & 5: data dictionary and data-quality report for the Nifty 50 study."""
from __future__ import annotations

import pandas as pd

from common import ROOT, TODAY, latest, log, save

DICT = [  # field, unit, source, formula
    ("members.isin", "ISIN", "Wikidata P946 / Upstox master / candle-API test", "see isin_source"),
    ("members.rebalance_date", "date", "derived", "30 June 2011..2025"),
    ("members.sector_wiki", "NSE macro sector", "Wikipedia constituent table (current, not PIT)", ""),
    ("prices_daily_members.close", "INR, split/bonus adjusted", "Upstox v3 candles", "back-adjusted by Upstox"),
    ("returns_monthly_all.ret_m (stock)", "decimal, price return", "Upstox", "close_m/close_{m-1}-1; NaN across missing months"),
    ("returns_monthly_all.ret_m (NIFTY50_PRICE/NIFTY500_PRICE)", "decimal", "Upstox NSE_INDEX", "price index, NOT TRI"),
    ("returns_monthly_all.ret_m (MKT_RF,SMB,HML,WML,RF)", "decimal per month", "IIMA IFFM release 2025-12", "% /100; ends 2025-12"),
    ("panel.price_at_rebalance", "INR adjusted", "Upstox", "last close on/before 30 June"),
    ("panel.adtv_3m_inr", "INR/day", "Upstox", "mean(close*volume) over 63 trading days to rebalance, min 40 obs"),
    ("panel.mom_12_1", "decimal", "Upstox", "P(May-end)/P(prior June-end)-1"),
    ("panel.roce_avg3", "decimal", "Upstox fundamentals", "mean over <=3 usable FYs of PBT/(TotalAssets-CurrentLiab) [PROXY]"),
    ("panel.roe_avg3", "decimal", "Upstox fundamentals", "mean over <=3 usable FYs of PAT/Equity"),
    ("panel.de", "x", "Upstox fundamentals", "NonCurrentLiab/Equity [PROXY for debt/equity]"),
    ("panel.eps", "INR/share, today's share base", "Upstox fundamentals", "PAT*owners_frac/shares_now"),
    ("panel.shares_proxy", "crore shares", "Upstox fundamentals", "standalone PAT/EPS, latest FY"),
    ("panel.mktcap_cr", "INR crore", "derived", "price_at_rebalance*shares_proxy"),
    ("panel.pe / earnings_yield", "x / decimal", "derived", "price/eps ; eps/price"),
    ("panel.ev_ebitda", "x", "-", "NOT COMPUTABLE: no D&A/debt/cash split"),
    ("panel.g_eps_cagr", "decimal p.a.", "derived", "(eps_last/eps_first)^(1/g_years)-1; NaN if base<=0; -1 if end<=0"),
    ("panel.l_count / l_window", "count / years", "derived", "#FY with ROCE(fin: ROE)>15% / #FY available (target 10)"),
    ("panel.Q,G,L,P", "z-score", "derived", "winsorize 1/99 then z within sector (>=3 names) else universe"),
    ("panel.qglp_composite", "z", "derived", "equal-weight mean of available Q,G,L,P"),
]


def main() -> None:
    pan = pd.read_csv(latest("panel"), parse_dates=["rebalance_date"])
    rets = pd.read_csv(latest("returns_monthly_all"), parse_dates=["month_end"])
    cov = pd.read_csv(latest("coverage_by_rebalance_date"))
    dd = pd.DataFrame(DICT, columns=["field", "unit", "source", "formula"])
    covr = []
    for f in ["members.isin", "returns_monthly_all.ret_m (stock)"]:
        covr.append(f)
    dd["coverage"] = ""
    dd.loc[dd.field.str.startswith("panel.roce") | dd.field.str.startswith("panel.roe") | dd.field.str.contains("eps|mktcap|pe |Q,G|composite|de$|shares|l_count", regex=True),
           "coverage"] = "rebalances 2023-2025 only (FY2022-FY2026 available)"
    dd.loc[dd.field.str.contains("adtv|mom|price_at"), "coverage"] = "2011-2025 (listed ISINs)"
    dd.loc[dd.field.str.contains("MKT_RF"), "coverage"] = "2009-01..2025-12"
    k = rets.groupby("kind")["month_end"].agg(["min", "max"])
    for kind, r in k.iterrows():
        dd.loc[len(dd)] = [f"returns_monthly_all [{kind}]", "", "", "", f"{r['min'].date()}..{r['max'].date()}"]
    save(dd, "data_dictionary")

    q = []
    for _, r in cov.iterrows():
        q.append(["count per rebalance", r["rebalance_date"], f"{r['members']} members / {r['with_isin']} ISIN / {r['with_price']} price / "
                  f"{r['with_fund']} fundamentals / {r['with_composite']} composite"])
    miss = pan[pan["price_at_rebalance"].isna()][["rebalance_date", "name"]]
    q.append(["survivorship: member-years with NO price", len(miss), "; ".join(f"{d.date()} {n}" for d, n in miss.values)])
    q.append(["survivorship: delisted names not covered", 7, "Cairn India, IDFC, JP Associates, Ranbaxy, Sterlite (no ISIN/prices); "
              "HDFC Ltd, Reliance Capital (ISIN known, no Upstox data)"])
    q.append(["fundamentals history", "FY2022-FY2026 only", "FY2008-FY2021 unobtainable from permitted sources -> Q/G/L/P only for 2023-2025"])
    q.append(["announcement dates", "NOT verified", "SEBI LODR 60-day rule assumed (public by 30 May)"])
    q.append(["restated figures", "yes", "Upstox shows latest restated values; EPS mixes split bases (fixed via eps_adj)"])
    q.append(["proxied fields", "ROCE, D/E, EPS, shares, mktcap", "see dictionary"])
    q.append(["unavailable fields", "EV/EBITDA, EBIT, interest, capex, debt, cash(BS), NIM, GNPA, CAR, weights", ""])
    q.append(["total return", "NOT available", "stocks & benchmark are price returns (no dividend history; TRI not permitted)"])
    q.append(["factor end", "2025-12", "IIMA release 2025-12; Jan-Sep 2026 missing"])
    q.append(["demerger in holding window", "Tata Motors 2025-10-14: ADJUSTED", "holder value TMPV+1xTMCV (implied 260.75 until 12-Nov-2025 listing); see s02c"])
    sec = pan[pan["rebalance_date"] == pan["rebalance_date"].max()].groupby("sector").size()
    q.append(["sectors < 3 names (latest)", int((sec < 3).sum()), "; ".join(sec[sec < 3].index)])
    q.append(["G negative-base cases", int(pan.get("g_negative_base", pd.Series(dtype=bool)).fillna(False).sum()), "G=NaN"])
    q.append(["L window", "<=3 years (target 10)", "L nearly uninformative: few distinct values"])
    q.append(["missing values (panel)", "", "; ".join(f"{c}:{int(n)}" for c, n in pan.isna().sum().items() if n)])
    q.append(["duplicates (panel isin x date)", int(pan.dropna(subset=["isin"]).duplicated(["isin", "rebalance_date"]).sum()), ""])
    dq = pd.DataFrame(q, columns=["check", "value", "detail"])
    save(dq, "data_quality")
    md = [f"# Nifty 50 QGLP study - data-quality report ({TODAY})", "", "| check | value | detail |", "|---|---|---|"]
    md += [f"| {a} | {b} | {c} |" for a, b, c in dq.values]
    (ROOT / f"data_quality_report_{TODAY}.md").write_text("\n".join(md), encoding="utf-8")
    log("quality", "report", "written")


if __name__ == "__main__":
    main()
