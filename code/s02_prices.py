"""B/E/G - Prices, monthly returns, liquidity for every ISIN that was ever a Nifty 50 member (2011-2025), plus the
Nifty 50 / Nifty 500 PRICE indices.

Inputs:
  * P1 Data/clean/item01_prices_upstox_<date>.csv (Nifty 500 study pull: all NSE EQ-series stocks, 2010+)
    -> filtered to member ISINs (re-used, not re-downloaded).
  * Members missing from that file (BE-series, recently delisted, etc.) are fetched here directly from the Upstox v3
    candle API (NSE_EQ then BSE_EQ), cached in nifty50_study/raw/upstox/. Rate-limited to 5/s, 450/min.
Adjustment: Upstox daily candles are split/bonus back-adjusted (verified in P1 on RELIANCE 2017/2024 bonuses and here
  on a list of known events - see s02 log) but NOT dividend-adjusted. Upstox's corporate-actions endpoint only returns
  the most recent action per company, so a dividend history (needed for total return) could NOT be built:
  ALL STOCK RETURNS ARE PRICE RETURNS. Likewise the benchmark is the PRICE index (TRI download from niftyindices.com
  is not permitted by its terms; Upstox carries no Nifty 50/500 TRI).
Monthly return = month-end close / previous month-end close - 1 (last trading day in month).
ADTV_3m = mean of daily (close x volume) over the 63 trading days ending on/before the rebalance date
  (close x volume uses ADJUSTED close and ADJUSTED volume, whose product equals the unadjusted traded value).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from common import P1_CLEAN, RAW, TODAY, RateLimiter, cached_get, latest, log, save

URL = "https://api.upstox.com/v3/historical-candle/{key}/days/1/{to}/{frm}"
CHUNKS = [("2010-01-01", "2016-12-31"), ("2017-01-01", TODAY)]
TOKEN = Path(r"C:\Users\DELL\Desktop\Derivatives_historical\upstox_access_token.txt")
KNOWN_EVENTS = [  # (isin, ex-date, event) - public, well-known splits/bonuses used as spot checks
    ("INE009A01021", "2014-12-02", "Infosys 1:1 bonus"), ("INE009A01021", "2015-06-15", "Infosys 1:1 bonus"),
    ("INE467B01029", "2018-05-31", "TCS 1:1 bonus"), ("INE002A01018", "2017-09-07", "Reliance 1:1 bonus"),
    ("INE002A01018", "2024-10-28", "Reliance 1:1 bonus"), ("INE040A01034", "2019-09-19", "HDFC Bank 1:2 split"),
    ("INE296A01032", "2016-09-07", "Bajaj Finance 1:5 split"),
]


def fetch(isin: str, hdr: dict, lim: RateLimiter) -> pd.DataFrame:
    for seg in ("NSE_EQ", "BSE_EQ"):
        fr = []
        for frm, to in CHUNKS:
            key = f"{seg}|{isin}"
            try:
                d = json.loads(cached_get(URL.format(key=key.replace("|", "%7C"), to=to, frm=frm),
                                          RAW / "upstox" / f"{seg}_{isin}_{frm}_{to}.json", hdr, lim))
            except Exception:  # noqa: BLE001 - invalid key => try next segment
                fr = []
                break
            c = d.get("data", {}).get("candles", [])
            if c:
                fr.append(pd.DataFrame(c, columns=["ts", "open", "high", "low", "close", "volume", "oi"]))
        if fr:
            f = pd.concat(fr)
            f["date"] = pd.to_datetime(f["ts"].str[:10])
            f["isin"], f["source"] = isin, f"upstox direct {seg}"
            return f.drop(columns=["ts", "oi"])
    return pd.DataFrame()


def main() -> None:
    mem = pd.read_csv(latest("members"), parse_dates=["rebalance_date"])
    isins = sorted(mem["isin"].dropna().unique())
    p1 = sorted(P1_CLEAN.glob("item01_prices_upstox_2*.csv"))[-1]
    parts = []
    for ch in pd.read_csv(p1, parse_dates=["date"], chunksize=1_000_000):
        parts.append(ch[ch["isin"].isin(isins)])
    px = pd.concat(parts)
    px["source"] = f"P1 {p1.name}"
    have = set(px["isin"])
    log("prices", "filter_p1", f"{p1.name} -> {len(have)}/{len(isins)} member ISINs found", rows_out=len(px))
    tok = TOKEN.read_text().strip()
    hdr = {"Authorization": f"Bearer {tok}", "Accept": "application/json"}
    lim = RateLimiter((5, 1.0), (450, 60.0))
    extra, none = [], []
    for i in sorted(set(isins) - have):
        f = fetch(i, hdr, lim)
        (extra.append(f) if len(f) else none.append(i))
    if extra:
        px = pd.concat([px] + extra, ignore_index=True)
    log("prices", "direct_fetch", f"fetched {len(extra)} missing ISINs directly; no Upstox data for {none}")
    px = px.drop_duplicates(["isin", "date"]).sort_values(["isin", "date"])
    px = px[px["date"] >= "2010-01-01"]

    # benchmarks (price indices)
    bfr = []
    for name, key in (("NIFTY50_PRICE", "NSE_INDEX|Nifty 50"), ("NIFTY500_PRICE", "NSE_INDEX|Nifty 500")):
        for frm, to in CHUNKS:
            d = json.loads(cached_get(URL.format(key=key.replace("|", "%7C").replace(" ", "%20"), to=to, frm=frm),
                                      RAW / "upstox" / f"{name}_{frm}_{to}.json", hdr, lim))
            c = pd.DataFrame(d["data"]["candles"], columns=["ts", "open", "high", "low", "close", "volume", "oi"])
            c["series"] = name
            bfr.append(c)
    bm = pd.concat(bfr)
    bm["date"] = pd.to_datetime(bm["ts"].str[:10])
    bm = bm.drop_duplicates(["series", "date"]).sort_values(["series", "date"])

    # split checks
    px["ret_d"] = px.groupby("isin")["close"].pct_change()
    chk = []
    for isin, d, ev in KNOWN_EVENTS:
        w = px[(px["isin"] == isin) & (px["date"].between(pd.Timestamp(d) - pd.Timedelta(days=5), pd.Timestamp(d) + pd.Timedelta(days=5)))]
        mx = w["ret_d"].abs().max()
        chk.append({"isin": isin, "ex_date": d, "event": ev, "max_abs_daily_ret_pm5d": mx,
                    "verdict": "adjusted" if pd.notna(mx) and mx < 0.2 else ("NO DATA" if pd.isna(mx) else "CHECK")})
    jumps = px[px["ret_d"].abs() > 0.4][["isin", "date", "close", "ret_d", "source"]]
    log("prices", "split_check", f"known events: {[c['verdict'] for c in chk]}; other |daily ret|>40%: {len(jumps)} rows")
    save(pd.DataFrame(chk), "split_verification")
    save(jumps, "suspect_jumps")

    save(px[["date", "isin", "open", "high", "low", "close", "volume", "source"]], "prices_daily_members")
    save(bm[["date", "series", "open", "high", "low", "close"]], "benchmark_daily_price_index")

    # monthly
    px["month"] = px["date"].dt.to_period("M")
    m = px.groupby(["isin", "month"]).agg(close=("close", "last"), last_trade=("date", "last"),
                                          volume=("volume", "sum"), days=("date", "count")).reset_index()
    m["ret_m"] = m.groupby("isin")["close"].pct_change()
    gap = m.groupby("isin")["month"].diff().apply(lambda x: x.n if pd.notna(x) else 1)
    m.loc[gap > 1, "ret_m"] = np.nan  # don't span missing months
    m["month_end"] = m["month"].dt.to_timestamp("M")
    log("prices", "monthly", "last close in month; ret = close_t/close_{t-1}-1; set NaN if previous month missing", len(px), len(m))
    save(m[["month_end", "isin", "close", "ret_m", "volume", "days", "last_trade"]], "returns_monthly_stocks")
    bm["month"] = bm["date"].dt.to_period("M")
    b = bm.groupby(["series", "month"])["close"].last().reset_index()
    b["ret_m"] = b.groupby("series")["close"].pct_change()
    b["month_end"] = b["month"].dt.to_timestamp("M")
    save(b[["month_end", "series", "close", "ret_m"]], "returns_monthly_benchmarks")

    # liquidity + momentum + rebalance price per member-date
    px["value"] = px["close"] * px["volume"]
    rows = []
    for _, r in mem.dropna(subset=["isin"]).iterrows():
        d = r["rebalance_date"]
        s = px[(px["isin"] == r["isin"]) & (px["date"] <= d)].tail(63)
        mm = m[m["isin"] == r["isin"]].set_index("month_end")["close"]
        t1, t12 = (d - pd.offsets.MonthEnd(1)), (d - pd.offsets.MonthEnd(12))
        mom = mm.get(t1) / mm.get(t12) - 1 if t1 in mm and t12 in mm else np.nan
        rows.append({"rebalance_date": d.date(), "isin": r["isin"],
                     "price_at_rebalance": s["close"].iloc[-1] if len(s) else np.nan,
                     "price_date": s["date"].iloc[-1].date() if len(s) else None,
                     "adtv_3m_inr": s["value"].mean() if len(s) >= 40 else np.nan, "adtv_obs": len(s),
                     "mom_12_1": mom})
    lq = pd.DataFrame(rows)
    log("prices", "liquidity_momentum", "ADTV over 63 trading days to rebalance (min 40 obs); "
        "mom_12_1 = P(month-end t-1)/P(month-end t-12) - 1 using month-end closes (skips the rebalance month June)")
    save(lq, "liquidity_momentum_at_rebalance")


if __name__ == "__main__":
    main()
