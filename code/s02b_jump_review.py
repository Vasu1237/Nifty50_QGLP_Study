"""Manual classification of every |daily return| > 40% found by s02 (analyst review; reasons are well-known public
events, recorded as judgement, not sourced figures). in_holding_window = the ISIN was a Nifty 50 member at the
30-June rebalance preceding the date, i.e. the jump enters the study's portfolio returns."""
import pandas as pd

from common import latest, log, save

REVIEW = {
    ("INE003A01024", "2025-04-07"): ("demerger", "Siemens Energy India demerged; parent price falls, spun-off value not in return"),
    ("INE095A01012", "2020-03-26"): ("genuine", "COVID-crash rebound"),
    ("INE155A01022", "2025-10-14"): ("demerger", "Tata Motors CV business demerged (TMCV); return understated on ex-date"),
    ("INE160A01022", "2017-10-25"): ("genuine", "PSU bank recapitalisation announcement"),
    ("INE205A01025", "2026-04-30"): ("demerger", "Vedanta multi-way demerger"),
    ("INE330H01018", "2018-05-17"): ("genuine", "distressed penny-stock move"),
    ("INE423A01024", "2015-06-03"): ("demerger", "Adani Enterprises 2015 scheme of arrangement"),
    ("INE528G01035", "2020-03-06"): ("genuine", "RBI moratorium / reconstruction"),
    ("INE528G01035", "2020-03-16"): ("genuine", "reconstruction scheme"),
    ("INE528G01035", "2020-03-17"): ("genuine", "reconstruction scheme"),
    ("INE584A01023", "2022-10-27"): ("CHECK", "NMDC Steel demerger period - +96% looks like an adjustment artefact; unverified"),
    ("INE669E01016", "2020-02-19"): ("genuine", "AGR-related move"),
}


def main():
    j = pd.read_csv(latest("suspect_jumps"), parse_dates=["date"])
    mem = pd.read_csv(latest("members"), parse_dates=["rebalance_date"])
    j["class"] = [REVIEW.get((i, str(d.date())), ("UNREVIEWED", ""))[0] for i, d in zip(j["isin"], j["date"])]
    j["note"] = [REVIEW.get((i, str(d.date())), ("", ""))[1] for i, d in zip(j["isin"], j["date"])]
    def held(r):
        reb = pd.Timestamp(f"{r["date"].year if r["date"].month > 6 else r["date"].year - 1}-06-30")
        return bool(((mem["isin"] == r["isin"]) & (mem.rebalance_date == reb)).any())
    j["in_holding_window"] = j.apply(held, axis=1)
    log("jumps", "review", f"{(j['class']=='demerger').sum()} demergers, {(j['class']=='CHECK').sum()} unexplained; "
        f"in a holding window: {j.loc[j.in_holding_window, ['isin','date','class']].values.tolist()}")
    save(j, "suspect_jumps_reviewed")


if __name__ == "__main__":
    main()
