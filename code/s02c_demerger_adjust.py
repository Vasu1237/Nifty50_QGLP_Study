"""Demerger adjustment of monthly returns for demergers inside a holding window (s02b review).

Upstox does NOT adjust prices for demergers: the parent's price simply drops on the ex-date, so the parent's price
return understates what a holder earned (the holder also receives the spun-off shares).
Method (standard holder-value approach; also how NSE treats indices, with a constant "dummy" price until listing):
  holder value per original parent share, from the ex-date on:
      V_t = P_parent_t + ratio x P_child_t
  P_child_t = implied price (parent cum-close - parent ex-date pre-open discovered price) until the child lists,
              then the child's market close.
  Months before the ex-month: V = P_parent (unchanged). ret_m = V_m / V_{m-1} - 1 from the ex-month onward.
  The spun-off shares are assumed HELD until the next rebalance (no sale, no reinvestment into the parent).
Output: returns_monthly_stocks gets ret_m (adjusted), ret_m_unadjusted and adj_note columns (rewritten in place).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from common import RAW, RateLimiter, TODAY, cached_get, latest, log, save

TOKEN = Path(r"C:\Users\DELL\Desktop\Derivatives_historical\upstox_access_token.txt")
URL = "https://api.upstox.com/v3/historical-candle/{key}/days/1/{to}/{frm}"
EVENTS = [
    {  # Tata Motors -> TMPV (parent, ISIN INE155A01022 retained) + Tata Motors Ltd (CV; listed 12-Nov-2025)
        "parent": "INE155A01022", "child": "INE1TAE01010", "ex_date": "2025-10-14", "ratio": 1.0,
        "parent_cum_close": 660.75, "parent_ex_preopen": 400.0,
        "source": "ratio 1:1 & record date 14-Oct-2025: company scheme as reported by Business Standard / Kotak Neo; "
                  "cum close 660.75 (13-Oct) and ex open 400.00 (14-Oct) from Upstox candles; "
                  "child listed 12-Nov-2025 at 335 (Upstox first candle open = 335.0, matches Business Standard)",
    },
]


def daily(isin: str, hdr: dict, lim: RateLimiter) -> pd.DataFrame:
    frm, to = "2025-01-01", TODAY
    d = json.loads(cached_get(URL.format(key=f"NSE_EQ%7C{isin}", to=to, frm=frm),
                              RAW / "upstox" / f"NSE_EQ_{isin}_{frm}_{to}_demerger.json", hdr, lim))
    c = pd.DataFrame(d["data"]["candles"], columns=["ts", "open", "high", "low", "close", "volume", "oi"])
    c["date"] = pd.to_datetime(c["ts"].str[:10])
    return c.sort_values("date")[["date", "open", "close"]]


def main() -> None:
    hdr = {"Authorization": f"Bearer {TOKEN.read_text().strip()}", "Accept": "application/json"}
    lim = RateLimiter((5, 1.0))
    m = pd.read_csv(latest("returns_monthly_stocks"), parse_dates=["month_end"])
    if "ret_m_unadjusted" not in m:
        m["ret_m_unadjusted"] = m["ret_m"]
        m["adj_note"] = ""
    for ev in EVENTS:
        ex = pd.Timestamp(ev["ex_date"])
        p, c = daily(ev["parent"], hdr, lim), daily(ev["child"], hdr, lim)
        # sanity: confirm the hard-coded cum close / ex open against the data
        cum = p.loc[p["date"] < ex, "close"].iloc[-1]
        exo = p.loc[p["date"] == ex, "open"].iloc[0]
        assert abs(cum - ev["parent_cum_close"]) < 0.01 and abs(exo - ev["parent_ex_preopen"]) < 0.01, (cum, exo)
        implied = ev["parent_cum_close"] - ev["parent_ex_preopen"]
        first_list = c["date"].min()
        cal = p[p["date"] >= ex][["date", "close"]].rename(columns={"close": "parent"})
        cal = cal.merge(c[["date", "close"]].rename(columns={"close": "child"}), on="date", how="left")
        cal.loc[cal["date"] < first_list, "child"] = implied
        cal["child"] = cal["child"].ffill()
        cal["V"] = cal["parent"] + ev["ratio"] * cal["child"]
        vme = cal.groupby(cal["date"].dt.to_period("M"))["V"].last()
        pre = p[p["date"] < ex].groupby(p["date"].dt.to_period("M"))["close"].last()
        pre = pre[pre.index < ex.to_period("M")]
        V = pd.concat([pre, vme]).sort_index()
        r = V.pct_change()
        sel = (m["isin"] == ev["parent"]) & (m["month_end"].dt.to_period("M") >= ex.to_period("M"))
        for i in m[sel].index:
            per = m.at[i, "month_end"].to_period("M")
            if per in r.index:
                m.at[i, "ret_m"] = r[per]
                m.at[i, "adj_note"] = f"demerger-adjusted: parent+{ev['ratio']}x child {ev['child']} (implied {implied:.2f} until {first_list.date()})"
        chg = m.loc[sel, ["month_end", "ret_m_unadjusted", "ret_m"]]
        log("demerger", "adjust", f"{ev['parent']} ex {ev['ex_date']}: implied child {implied:.2f}; first child close "
            f"{c['close'].iloc[0]} on {first_list.date()}; months adjusted {len(chg)}; "
            + "; ".join(f"{d.date()}: {a:.4f}->{b:.4f}" for d, a, b in chg.head(4).values))
        save(cal.assign(parent_isin=ev["parent"], child_isin=ev["child"]), f"demerger_holder_value_{ev['parent']}")
    save(m, "returns_monthly_stocks")


if __name__ == "__main__":
    main()
