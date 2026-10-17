# Nifty 50 QGLP study - data-quality report (2026-10-17)

| check | value | detail |
|---|---|---|
| count per rebalance | 2011-06-30 | 50 members / 45 ISIN / 43 price / 0 fundamentals / 0 composite |
| count per rebalance | 2012-06-30 | 50 members / 45 ISIN / 44 price / 0 fundamentals / 0 composite |
| count per rebalance | 2013-06-30 | 50 members / 46 ISIN / 45 price / 0 fundamentals / 0 composite |
| count per rebalance | 2014-06-30 | 50 members / 48 ISIN / 47 price / 0 fundamentals / 0 composite |
| count per rebalance | 2015-06-30 | 50 members / 49 ISIN / 48 price / 0 fundamentals / 0 composite |
| count per rebalance | 2016-06-30 | 50 members / 50 ISIN / 49 price / 0 fundamentals / 0 composite |
| count per rebalance | 2017-06-30 | 50 members / 50 ISIN / 49 price / 0 fundamentals / 0 composite |
| count per rebalance | 2018-06-30 | 50 members / 50 ISIN / 49 price / 0 fundamentals / 0 composite |
| count per rebalance | 2019-06-30 | 50 members / 50 ISIN / 49 price / 0 fundamentals / 0 composite |
| count per rebalance | 2020-06-30 | 50 members / 50 ISIN / 49 price / 0 fundamentals / 0 composite |
| count per rebalance | 2021-06-30 | 50 members / 50 ISIN / 49 price / 0 fundamentals / 0 composite |
| count per rebalance | 2022-06-30 | 50 members / 50 ISIN / 49 price / 7 fundamentals / 3 composite |
| count per rebalance | 2023-06-30 | 50 members / 50 ISIN / 49 price / 49 fundamentals / 49 composite |
| count per rebalance | 2024-06-30 | 50 members / 50 ISIN / 50 price / 50 fundamentals / 50 composite |
| count per rebalance | 2025-06-30 | 50 members / 50 ISIN / 50 price / 50 fundamentals / 50 composite |
| survivorship: member-years with NO price | 31 | 2023-06-30 HDFC; 2022-06-30 HDFC; 2021-06-30 HDFC; 2020-06-30 HDFC; 2019-06-30 HDFC; 2018-06-30 HDFC; 2017-06-30 HDFC; 2016-06-30 HDFC; 2015-06-30 Cairn India; 2015-06-30 HDFC; 2014-06-30 Cairn India; 2014-06-30 HDFC; 2014-06-30 IDFC; 2013-06-30 Cairn India; 2013-06-30 HDFC; 2013-06-30 IDFC; 2013-06-30 JP Associates; 2013-06-30 Ranbaxy Laboratories; 2012-06-30 Cairn India; 2012-06-30 HDFC; 2012-06-30 IDFC; 2012-06-30 JP Associates; 2012-06-30 Ranbaxy Laboratories; 2012-06-30 Sterlite Industries; 2011-06-30 Cairn India; 2011-06-30 HDFC; 2011-06-30 IDFC; 2011-06-30 JP Associates; 2011-06-30 Ranbaxy Laboratories; 2011-06-30 Reliance Capital; 2011-06-30 Sterlite Industries |
| survivorship: delisted names not covered | 7 | Cairn India, IDFC, JP Associates, Ranbaxy, Sterlite (no ISIN/prices); HDFC Ltd, Reliance Capital (ISIN known, no Upstox data) |
| fundamentals history | FY2022-FY2026 only | FY2008-FY2021 unobtainable from permitted sources -> Q/G/L/P only for 2023-2025 |
| announcement dates | NOT verified | SEBI LODR 60-day rule assumed (public by 30 May) |
| restated figures | yes | Upstox shows latest restated values; EPS mixes split bases (fixed via eps_adj) |
| proxied fields | ROCE, D/E, EPS, shares, mktcap | see dictionary |
| unavailable fields | EV/EBITDA, EBIT, interest, capex, debt, cash(BS), NIM, GNPA, CAR, weights |  |
| total return | NOT available | stocks & benchmark are price returns (no dividend history; TRI not permitted) |
| factor end | 2025-12 | IIMA release 2025-12; Jan-Sep 2026 missing |
| demerger in holding window | Tata Motors 2025-10-14: ADJUSTED | holder value TMPV+1xTMCV (implied 260.75 until 12-Nov-2025 listing); see s02c |
| sectors < 3 names (latest) | 8 | Capital Goods; Construction; Construction Materials; Consumer Durables; Consumer Services; Power; Services; Telecommunication |
| G negative-base cases | 1 | G=NaN |
| L window | <=3 years (target 10) | L nearly uninformative: few distinct values |
| missing values (panel) |  | isin:17; nse_symbol_today:35; symbol_wiki_current:223; sector_wiki:223; price_at_rebalance:31; price_date:31; adtv_3m_inr:31; adtv_obs:17; mom_12_1:31; latest_fy:594; roce_avg3:617; roe_avg3:607; de:625; eps:599; eps_reported:599; owners_frac:594; revenue:634; pat:599; cfo:596; shares_proxy:594; cfo_to_pat:601; fund_basis:594; l_count:594; l_window:594; g_years:644; g_eps_cagr:657; g_negative_base:749; mktcap_cr:594; log_mktcap:594; pe:599; earnings_yield:599; ev_ebitda:750; q_raw_nonfin_roce:634; q_raw_nonfin_neg_de:634; q_raw_fin_roe:723; q_raw_nonfin_roce_z_scope:600; q_raw_nonfin_roce_z:634; q_raw_nonfin_neg_de_z_scope:600; q_raw_nonfin_neg_de_z:634; q_raw_fin_roe_z_scope:600; q_raw_fin_roe_z:723; g_eps_cagr_z_scope:650; g_eps_cagr_z:659; l_count_z_scope:550; l_count_z:598; earnings_yield_z_scope:600; earnings_yield_z:601; log_mktcap_z_scope:550; log_mktcap_z:594; mom_12_1_z:31; Q:607; G:659; L:598; P:601; qglp_composite:598 |
| duplicates (panel isin x date) | 0 |  |