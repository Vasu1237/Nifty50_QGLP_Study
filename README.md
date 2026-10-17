# Nifty 50 QGLP study – dataset (subfolder of P1 Data)

**Design (unchanged):** point-in-time Nifty 50, rebalanced each 30 June 2011–2025, 12-month holding, monthly returns, ISIN as the key.
**Run:** `python code/run_all.py`. The scripts reuse the Nifty 500 price pull in `..\clean\item01_prices_upstox_*.csv` and the IIMA factors in `..\clean\item06_*`.

**Current state (17-Oct-2026).** Fundamentals now come from the CMIE ProwessDX extract (`s06`, `s07`), which covers FY2005–FY2026 for all 90 members. The analysis (`s08`–`s11`) runs on that panel. Benchmark: the equal-weight average of the UTI and SBI Nifty 50 Index Fund NAV returns from AMFI (`s09`, `s12`), a proxy for the Nifty 50 TRI, net of fund fees. The official TRI needs licensed access and was not available. Survivorship: seven former members have no returns after exit; see `P1_results_2026-10-16.md`. Licensed Prowess data is in `clean/prowess_*` and `raw/prowess/`: do not publish it. Results: `P1_results_2026-10-16.md`. The earlier Upstox-only section below is kept for the audit trail; where it conflicts with this paragraph, this paragraph is correct.

## Files (`clean/`, all `<item>_<date>.csv`)
| File | Content |
|---|---|
| `members_*` / `index_changes_*` | **A.** Point-in-time membership (15 dates × 50) and the 70 index changes since 2005 |
| `prices_daily_members_*` | **B.** Daily adjusted OHLCV for all 83 member ISINs that have prices (Nifty 500 pull filtered, plus direct Upstox fetches) |
| `returns_monthly_all_*` (.csv/.parquet) | **Deliverable 3.** Monthly returns: stocks, Nifty 50/500 price index, IIMA MKT_RF/SMB/HML/WML/RF |
| `fundamentals_long_raw_*` | **C.** Every line value from the Upstox fundamentals API (consolidated and standalone) |
| `panel_*` (.csv/.parquet) | **Deliverable 2.** ISIN × rebalance date: membership, sector, price, ADTV, momentum, fundamentals, Q/G/L/P, composite |
| `liquidity_momentum_at_rebalance_*` | **E** plus the momentum control |
| `sector_upstox_current_*` | **F.** Upstox's current industry label (granular), kept for reference |
| `split_verification_*`, `suspect_jumps_reviewed_*` | Adjustment checks |
| `coverage_by_rebalance_date_*`, `data_dictionary_*`, `data_quality_*` | **Deliverables 4–5** (plus `data_quality_report_*.md`) |
| `logs/transformations.csv` | **Deliverable 6.** Every transformation; assumptions are in each script's docstring and listed below |

## Sources used and why
| Need | Source used | Why not the preferred source |
|---|---|---|
| Membership | Wikipedia "NIFTY 50" change table (CC BY-SA; each change cites a niftyindices press release or dated news). ISINs from Wikidata (CC0), the Upstox master, or Upstox candle tests | niftyindices.com and NSE terms prohibit automated collection |
| Prices | Upstox v3 candles | Bhavcopies (NSE) are under the same prohibition |
| Fundamentals (current) | CMIE ProwessDX, extract 130245 (`s06`, `s07`). Licensed to IIM Indore; do not publish |
| Fundamentals (superseded) | Upstox `/v2/fundamentals/{isin}/…` (found in Upstox's official SDK and tested) | No Bloomberg. NSE/BSE XBRL is under the same NSE terms. Screener's terms bar scraping. EDGAR covers only 5 ADR names, from FY2016, in USD/IFRS, with 20-F filing dates often after 30 June, so I tested it and left it out |
| Factors, RF | IIMA library (release 2025-12) | – |
| Benchmark (current) | UTI Nifty 50 Index Fund, Regular Growth, AMFI code 100822 (`s09`). Net of fund expenses, so it understates the TRI | Official TRI needs licensed access (LSEG). Check: 0.9996 monthly correlation with the Nifty 50 price index |
| Benchmark (superseded) | Upstox Nifty 50 / Nifty 500 **price** indices | The TRI download on niftyindices is barred; Upstox has no Nifty 50/500 TRI |

## Things I could not do (read before any analysis)
*Items 1, 2, 4, 5 and 8 below describe the earlier Upstox-only build. With Prowess data, fundamentals exist for FY2005–FY2026 and the panel scores all four components for 46–50 names per rebalance. Items 3, 6, 7 and 9 still apply.*
1. **Fundamentals exist only for FY2022–FY2026.** So Q, G, L, P and the composite exist only for the **2023, 2024 and 2025 rebalances** (49–50 names each). For 2011–2022 the panel has membership, price, liquidity and momentum only. The study as designed (2011–2025) needs FY2008–FY2021 data from a licensed source (Bloomberg, CMIE Prowess, Capitaline, ACE Equity).
2. **Announcement dates are not verified.** I assume SEBI LODR's 60-day deadline, so FY results are public by 30 May. Upstox values are the latest restated figures, not as first reported.
3. **Returns are price returns.** There's no dividend history (the Upstox corporate-actions endpoint returns only the latest action), and the benchmark is a price index, not the TRI.
4. **Proxies:** ROCE = PBT/(TA−CL), with no interest add-back; D/E = non-current liabilities / equity; EPS is put on today's share base (Upstox's EPS history mixes split bases, verified on Reliance, Bajaj Finance and HDFC Bank); market cap = adjusted price × today's share count, which ignores share issuance and buybacks.
5. **Not available at all:** EV/EBITDA, EBIT, interest, capex, debt, cash on the balance sheet, bank NIM/GNPA/CAR, and index weights. Financials are scored on ROE only.
6. **Survivorship:** 7 delisted names have no prices: Cairn India, IDFC, JP Associates, Ranbaxy and Sterlite (no verifiable ISIN), plus HDFC Ltd and Reliance Capital (ISIN known, but Upstox has no history). They are in the membership file but contribute no returns. That's 2–7 member-years missing per rebalance in 2011–2015, and 1 per year in 2016–2023 (HDFC Ltd).
7. **Sector is not point-in-time.** It uses Wikipedia's current NSE sector, and I assigned the sector myself for past members. Every year, 9–12 names sit in sectors with fewer than 3 members and are z-scored against the whole universe. Financial Services is 12 of 50 names.
8. **L is weak.** The window is at most 3 years, against the 10 in the design. G spans 1–2 years, against the 3 designed. One case had a negative base EPS (G = NaN); a negative ending EPS sets G to −100%.
9. **Factors end Dec 2025** (IIMA release 2025-12), so Jan–Sep 2026 has no factor data.
10. **Tata Motors demerger (14 Oct 2025): fixed** (`code/s02c_demerger_adjust.py`). From the ex-date, the return is on holder value = TMPV + 1 × the demerged CV share (ratio 1:1). The CV share is valued at the implied ₹260.75 (₹660.75 cum close − ₹400 ex-date discovered price) until it listed on 12 Nov 2025, then at its market price. The spun-off shares are assumed held until the next rebalance. Oct 2025 is now −1.4% instead of −39.7%. The original figures stay in `ret_m_unadjusted` and `adj_note`, and daily holder values are in `demerger_holder_value_INE155A01022_*.csv`. NMDC's +96% day on 27 Oct 2022 is still unexplained, but NMDC wasn't a member then.
