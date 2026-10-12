"""Analytics engine for the Pagoda turnaround app.

Pure functions, no Streamlit imports, so the same code runs in the app, in tests and in a notebook.

Pipeline:  Statista workbook -> tidy market table -> validation checks -> market diagnostics
           -> forecast backtest -> driver-based profit model -> Monte Carlo simulation
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import numpy as np
import pandas as pd
from openpyxl import load_workbook
from scipy import stats

HIST_END = 2025                      # last year treated as history; later years are Statista's forecast
SEED = 20261006
N_TRIALS = 20_000
FIXED_SHARE = 0.5                    # assumed fixed share of operating costs
SEG_ORDER = ["Bananas", "Apples & Pears", "Other Fresh Fruits", "Citrus Fruits", "Berries & Grapes"]
FOOTER = ("Most recent update:", "Sources", "Notes")
REQUIRED_SHEETS = ["Revenue", "Volume", "Price", "Sales Channels", "Global Comparison", "Key Market Indicators"]


# --------------------------------------------------------------------------- 1. load
def read_blocks(source: str | Path | IO[bytes], sheet: str) -> dict[str, pd.DataFrame]:
    """Split one Statista sheet into its stacked tables: {title: DataFrame[row label x year]}."""
    ws = load_workbook(source, data_only=True)[sheet]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    blocks, i = {}, 0
    while i < len(rows) - 1:
        title, nxt = rows[i][0], rows[i + 1]
        is_header = nxt[0] in ("", None) and len(nxt) > 1 and str(nxt[1]).isdigit()
        if isinstance(title, str) and title.strip() and is_header:
            cols = [k for k, y in enumerate(nxt) if k > 0 and str(y).isdigit()]      # year columns only
            years = [int(nxt[k]) for k in cols]
            j, labels, values = i + 2, [], []
            while j < len(rows) and rows[j][0] not in FOOTER + ("", None):
                labels.append(rows[j][0]); values.append([rows[j][k] for k in cols]); j += 1
            meta = {}
            while j < len(rows) and rows[j][0] in FOOTER:
                meta[rows[j][0].rstrip(":")] = rows[j][1]; j += 1
            df = pd.DataFrame(values, index=labels, columns=years).apply(pd.to_numeric, errors="coerce")
            df.attrs.update(meta)
            blocks[title.strip()] = df
            i = j
        else:
            i += 1
    return blocks


@dataclass
class Market:
    raw: dict                 # sheet -> {table title -> DataFrame}
    long: pd.DataFrame        # tidy: segment, year, status, metric, value
    wide: pd.DataFrame        # index (segment, year), one column per metric
    years: list
    hist: list
    fcst: list
    segs: list

    def table(self, metric: str) -> pd.DataFrame:
        return self.wide[metric].unstack("year")

    @property
    def total(self) -> pd.DataFrame:
        return self.wide.loc["Total"]

    @property
    def population(self) -> pd.Series:      # billions, implied by revenue / revenue per capita
        return (self.wide.revenue_usd_bn / self.wide.revenue_per_capita_usd).unstack("year").loc["Total"]


def load_market(source) -> Market:
    if hasattr(source, "seek"):
        source.seek(0)
    names = load_workbook(source, read_only=True).sheetnames
    missing = [s for s in REQUIRED_SHEETS if s not in names]
    if missing:
        raise ValueError(f"Workbook is missing sheet(s): {', '.join(missing)}. Expected a Statista Market Insights export.")
    raw = {}
    for s in REQUIRED_SHEETS:
        if hasattr(source, "seek"):
            source.seek(0)
        raw[s] = read_blocks(source, s)

    def to_long(df, metric):
        out = df.rename_axis("segment").reset_index().melt(id_vars="segment", var_name="year", value_name="value")
        out["metric"] = metric
        return out

    long = pd.concat([
        to_long(raw["Revenue"]["REVENUE in billion USD (US$)"], "revenue_usd_bn"),
        to_long(raw["Volume"]["VOLUME in billion kilograms"], "volume_bn_kg"),
        to_long(raw["Price"]["PRICE PER UNIT in USD (US$)"].rename(index={"Average": "Total"}), "price_usd_per_kg"),
        to_long(raw["Revenue"]["AVERAGE REVENUE PER CAPITA in USD (US$)"], "revenue_per_capita_usd"),
        to_long(raw["Volume"]["AVERAGE VOLUME PER CAPITA in kilograms"], "volume_per_capita_kg"),
    ], ignore_index=True)
    long["year"] = long.year.astype(int)
    long["status"] = np.where(long.year <= HIST_END, "history", "statista_forecast")
    long = long[["segment", "year", "status", "metric", "value"]].sort_values(["metric", "segment", "year"]).reset_index(drop=True)
    wide = long.pivot(index=["segment", "year"], columns="metric", values="value").sort_index()
    years = sorted(long.year.unique().tolist())
    segs = [s for s in SEG_ORDER if s in wide.index.get_level_values(0)]
    return Market(raw, long, wide, years, [y for y in years if y <= HIST_END], [y for y in years if y > HIST_END], segs)


def inventory(mk: Market) -> pd.DataFrame:
    return pd.DataFrame([dict(sheet=s, table=t, series=len(df), first_year=int(df.columns.min()), last_year=int(df.columns.max()),
                              updated=df.attrs.get("Most recent update"), missing_cells=int(df.isna().sum().sum()))
                         for s, blocks in mk.raw.items() for t, df in blocks.items()])


# --------------------------------------------------------------------------- 2. validate
def online_series(mk: Market) -> tuple[pd.DataFrame, pd.DataFrame]:
    ch = mk.raw["Sales Channels"]["ONLINE REVENUE SHARE in percent"]
    return ch[ch.index == "Online"].reset_index(drop=True), ch[ch.index == "Offline"].reset_index(drop=True)


def channel_summary(mk: Market) -> pd.DataFrame:
    online, _ = online_series(mk)
    t = online.T
    return pd.DataFrame({"lowest": t.min(axis=1), "median": t.median(axis=1), "highest": t.max(axis=1)}).rename_axis("year")


def quality_checks(mk: Market) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (data-quality log, outlier table)."""
    dq = []
    def log(check, result, detail, action):
        dq.append(dict(check=check, result=result, detail=detail, action=action))

    rev, vol, prc = mk.table("revenue_usd_bn"), mk.table("volume_bn_kg"), mk.table("price_usd_per_kg")
    segs = mk.segs
    for name, w in [("Revenue: segments sum to total", rev), ("Volume: segments sum to total", vol)]:
        gap = (w.loc[segs].sum() - w.loc["Total"]).abs().max()
        log(name, "pass" if gap <= 0.03 else "FLAG", f"largest gap {gap:.3f} bn", "none")

    rel = ((rev / vol - prc) / prc).abs()
    log("Price: revenue / volume equals price per kg", "pass" if rel.max().max() < 0.01 else "FLAG",
        f"largest relative gap {rel.max().max():.2%} ({rel.max(axis=1).idxmax()})", "none")

    pop = (mk.wide.revenue_usd_bn / mk.wide.revenue_per_capita_usd).unstack("year")
    spread = ((pop.max() - pop.min()) / pop.loc["Total"]).max()
    log("Per capita: one implied population across tables", "pass" if spread < 0.01 else "FLAG",
        f"spread across segments up to {spread:.2%}; implied population {pop.loc['Total', mk.years[0]]:.3f}bn ({mk.years[0]}), "
        f"{pop.loc['Total', HIST_END]:.3f}bn ({HIST_END})", "implied population reused as a forecast driver")

    for name, key, sheet, w in [("Revenue", "REVENUE CHANGE in percent", "Revenue", rev), ("Volume", "VOLUME CHANGE in percent", "Volume", vol)]:
        published = mk.raw[sheet][key].dropna(axis=1, how="all")
        prev, cur = w.shift(axis=1).loc[published.index, published.columns], w.loc[published.index, published.columns]
        lo = ((cur - 0.005) / (prev + 0.005) - 1) * 100 - 0.05
        hi = ((cur + 0.005) / (prev - 0.005) - 1) * 100 + 0.05
        outside = int(((published < lo) | (published > hi)).sum().sum())
        log(f"{name}: published growth consistent with published levels", "pass" if outside == 0 else "FLAG",
            f"{outside} of {published.size} growth rates fall outside the range rounding allows", "none")

    online, offline = online_series(mk)
    pairs = [(i, j) for i in online.index for j in offline.index if ((online.loc[i] + offline.loc[j] - 100).abs() < 0.25).all()]
    log("Sales channels: online + offline = 100", "pass" if len(pairs) == len(online) else "FLAG",
        f"{len(pairs)} of {len(online)} online series have a matching offline series", "none")

    # outlier scan: robust z-score on year-over-year changes
    flags = []
    for metric in ["revenue_usd_bn", "volume_bn_kg", "price_usd_per_kg"]:
        g = mk.table(metric).pct_change(axis=1).dropna(axis=1, how="all") * 100
        med = g.median(axis=1); mad = g.sub(med, axis=0).abs().median(axis=1) * 1.4826
        z = g.sub(med, axis=0).div(mad, axis=0)
        for (seg, yr), zval in z.stack().items():
            if abs(zval) > 6:
                flags.append(dict(metric=metric, segment=seg, year=int(yr), yoy_pct=round(g.loc[seg, yr], 1), robust_z=round(zval, 1)))
    outliers = pd.DataFrame(flags, columns=["metric", "segment", "year", "yoy_pct", "robust_z"]).sort_values(["segment", "metric", "year"]).reset_index(drop=True)
    yoy = prc.pct_change(axis=1) * 100
    for seg, yrs, action in [("Berries & Grapes", (2020, 2021), "segment analysed on revenue only"),
                             ("Total", (2030, 2031), "Statista forecast for 2030-31 treated as lower confidence")]:
        hit = outliers[(outliers.segment == seg) & (outliers.metric == "price_usd_per_kg") & outliers.year.isin(yrs)]
        if len(hit) and all(y in yoy.columns for y in yrs):
            log(f"Outlier scan: {seg} price, {yrs[0]}-{yrs[1]}", "FLAG",
                f"price change {yoy.loc[seg, yrs[0]]:+.1f}% and {yoy.loc[seg, yrs[1]]:+.1f}% against a series median of {yoy.loc[seg].median():+.1f}%", action)

    # can the unlabelled channel rows be matched to segments? (one row must be the revenue-weighted mean of five others)
    rev_h = rev[[c for c in online.columns if c in rev.columns]]
    best = np.inf
    for total_row in online.index:
        others = [i for i in online.index if i != total_row]
        for perm in itertools.permutations(others):
            weighted = sum(rev_h.loc[s] * online.loc[p, rev_h.columns] for s, p in zip(segs, perm)) / rev_h.loc["Total"]
            best = min(best, float((weighted - online.loc[total_row, rev_h.columns]).abs().mean()))
    recoverable = best < 0.1
    log("Sales channels: row labels", "pass" if recoverable else "FLAG",
        f"{len(online)} unlabelled online series; best label assignment misses by {best:.2f} pt on average",
        "none" if recoverable else "only the label-free pattern (range and median) is reported; re-export from Statista with labels")
    jumps = online.T.diff().abs()
    jmax = jumps.stack().idxmax()
    if jumps.max().max() > 10:
        log("Sales channels: series continuity", "FLAG", f"one series jumps {online.T.diff().loc[jmax[0], jmax[1]]:+.1f} pt in {jmax[0]}", "series not used individually")

    kmi = mk.raw["Key Market Indicators"]
    fx = kmi["EXCHANGE RATES"].loc["CNY (CN¥)"]
    steps = fx.loc[2021:2030].diff().dropna()
    credit = kmi["BUSINESS CYCLE"].loc["Domestic Credit (% of GDP) in percent"]
    if (steps < 0).all() or credit.get(2024, 0) > 1000:
        log("Key Market Indicators: values after 2020 are projections", "FLAG",
            f"CNY per USD falls every year from {fx[2021]:.2f} (2021) to {fx[2030]:.2f} (2030); Domestic Credit reads {credit[2024]:,.0f}% of GDP",
            "sheet used only for the currency conversion, with a sensitivity rate")
    return pd.DataFrame(dq), outliers


# --------------------------------------------------------------------------- 3. diagnostics
def cagr(series: pd.Series, y0: int, y1: int) -> float:
    return (series[y1] / series[y0]) ** (1 / (y1 - y0)) - 1


def decomposition(mk: Market) -> pd.DataFrame:
    """Average annual log growth of revenue split into price and volume (and volume into population and per-capita)."""
    tot, pop, y_first, y_last = mk.total, mk.population, mk.years[0], mk.years[-1]
    def one(y0, y1):
        n = y1 - y0
        f = lambda s: np.log(s[y1] / s[y0]) / n * 100
        return dict(revenue=f(tot.revenue_usd_bn), volume=f(tot.volume_bn_kg), price=f(tot.price_usd_per_kg),
                    population=f(pop), volume_per_capita=f(tot.volume_per_capita_kg))
    d = pd.DataFrame({f"History {y_first}-{HIST_END}": one(y_first, HIST_END), f"Statista forecast {HIST_END}-{y_last}": one(HIST_END, y_last)}).T
    d["volume_share_pct"] = d.volume / d.revenue * 100
    return d


def segment_table(mk: Market) -> pd.DataFrame:
    rev, vol, prc, y0, y1 = mk.table("revenue_usd_bn"), mk.table("volume_bn_kg"), mk.table("price_usd_per_kg"), mk.years[0], mk.years[-1]
    t = pd.DataFrame({
        "revenue_usd_bn": rev.loc[mk.segs, HIST_END],
        "share_start_pct": rev.loc[mk.segs, y0] / rev.loc["Total", y0] * 100,
        "share_now_pct": rev.loc[mk.segs, HIST_END] / rev.loc["Total", HIST_END] * 100,
        "revenue_cagr_pct": [cagr(rev.loc[s], y0, HIST_END) * 100 for s in mk.segs],
        "volume_cagr_pct": [cagr(vol.loc[s], y0, HIST_END) * 100 for s in mk.segs],
        "price_usd_kg": prc.loc[mk.segs, HIST_END],
        "statista_cagr_pct": [cagr(rev.loc[s], HIST_END, y1) * 100 for s in mk.segs],
    })
    t["share_change_pt"] = t.share_now_pct - t.share_start_pct
    if "Berries & Grapes" in t.index:
        t.loc["Berries & Grapes", "volume_cagr_pct"] = np.nan      # series break in 2020-21
    return t.rename_axis("segment")


def global_position(mk: Market) -> pd.DataFrame:
    gc = mk.raw["Global Comparison"]["REVENUE COMPARISON in billion USD (US$)"]
    world, rank = gc.sum(), gc.rank(ascending=False, method="min")
    yrs = [mk.years[0], HIST_END, mk.years[-1]]
    return pd.DataFrame({"china_usd_bn": gc.loc["China"], "all_countries_usd_bn": world, "china_share_pct": gc.loc["China"] / world * 100,
                         "china_rank": rank.loc["China"], "largest_market": gc.idxmax()}).loc[yrs].rename_axis("year")


def workbook_fx(mk: Market) -> pd.Series:
    return mk.raw["Key Market Indicators"]["EXCHANGE RATES"].loc["CNY (CN¥)"]


def load_company(facts_csv, plan_csv) -> tuple[pd.DataFrame, pd.DataFrame]:
    facts = pd.read_csv(facts_csv, dtype={"year": str})
    plan = pd.read_csv(plan_csv).set_index("year")
    return facts, plan


def fact(facts: pd.DataFrame, metric: str) -> pd.Series:
    """Annual series for one metric, indexed by integer year."""
    f = facts[(facts.metric == metric) & facts.year.str.fullmatch(r"\d{4}")]
    return pd.Series(f.value.values, index=f.year.astype(int).values, name=metric).sort_index()


def forecast_track_record(facts: pd.DataFrame, forecasts_csv) -> pd.DataFrame:
    """Past analyst forecasts against reported actuals: the only evidence on how far, and which way, a plan for Pagoda misses."""
    f = pd.read_csv(forecasts_csv)
    rev, npf, gm = fact(facts, "revenue"), fact(facts, "net_profit_attributable"), fact(facts, "gross_margin")
    f["revenue_actual"] = f.year.map(rev); f["revenue_error_pct"] = (f.revenue_actual / f.revenue - 1) * 100
    f["net_profit_actual"] = f.year.map(npf); f["net_profit_error"] = f.net_profit_actual - f.net_profit
    f["gross_margin_actual"] = f.year.map(gm); f["gross_margin_error_pt"] = f.gross_margin_actual - f.gross_margin
    return f


def tri_cdf(x, lo, mode, hi):
    """Share of a triangular distribution below x."""
    if x <= lo: return 0.0
    if x >= hi: return 1.0
    return (x - lo) ** 2 / ((hi - lo) * (mode - lo)) if x <= mode else 1 - (hi - x) ** 2 / ((hi - lo) * (hi - mode))


def first_half_2026_check(model: "Model", facts: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Where did 1H26 actuals (CICC, 7 Sep 2026) land in the simulator's 2026 ranges? Returns (table, headline figures)."""
    F = lambda period, metric: float(facts[(facts.year == period) & (facts.metric == metric)].value.iloc[0])
    n, d = make_ranges(model, "neutral"), make_ranges(model, "downside")
    pct = lambda r, k, x: tri_cdf(x, r[k]["low"][0], r[k]["mode"][0], r[k]["high"][0]) * 100
    gm, adds, sps = F("1H26", "gross_margin_half_cicc") / 100, F("1H26", "stores_franchise_network_period_end") - model.base["stores_end"], F("1H26", "daily_sales_per_store_growth_yoy") / 100
    p = model.plan
    t = pd.DataFrame([
        dict(driver="Gross margin", plan_2026=p.gross_margin.iloc[0] * 100, first_half_2026=gm * 100, pct_neutral=pct(n, "gm", gm), pct_downside=pct(d, "gm", gm),
             note=f"{F('1H26', 'gross_margin_excluding_alliance'):.1f}% excluding the Seven-Star alliance (CICC estimate)"),
        dict(driver="Net store openings", plan_2026=p.store_adds.iloc[0], first_half_2026=adds, pct_neutral=pct(n, "store_adds", adds), pct_downside=pct(d, "store_adds", adds),
             note="six months only, against full-year ranges"),
        dict(driver="Sales per store growth", plan_2026=p.rps_growth.iloc[0] * 100, first_half_2026=sps * 100, pct_neutral=pct(n, "rps_growth", sps), pct_downside=pct(d, "rps_growth", sps),
             note="store-level daily sales, not Pagoda revenue per store"),
    ]).set_index("driver")
    rev, rev25, alliance = F("1H26", "revenue_half"), F("1H25", "revenue_half"), F("1H26", "seven_star_alliance_revenue")
    head = dict(revenue=rev, revenue_growth=rev / rev25 - 1, alliance=alliance, alliance_share=alliance / rev, core_growth=(rev - alliance) / rev25 - 1,
                net_profit=F("1H26", "net_profit_half"), adj_net_profit=F("1H26", "adjusted_net_profit_half"), gross_margin=gm,
                gm_core=F("1H26", "gross_margin_excluding_alliance") / 100, stores=F("1H26", "stores_franchise_network_period_end"))
    return t, head


def share_table(mk: Market, facts: pd.DataFrame, fx_alt: float = 7.2) -> pd.DataFrame:
    """Pagoda revenue against the market. A proxy: mostly wholesale revenue against a retail market."""
    pg, fx, tot = fact(facts, "revenue"), workbook_fx(mk), mk.total.revenue_usd_bn
    pg = pg[[y for y in pg.index if y in tot.index]]
    s = pd.DataFrame({"pagoda_rmb_mn": pg, "market_usd_bn": tot[pg.index], "fx_workbook": fx[pg.index]})
    s["share_proxy_pct"] = s.pagoda_rmb_mn / s.fx_workbook / 1000 / s.market_usd_bn * 100
    s["share_proxy_alt_fx_pct"] = s.pagoda_rmb_mn / fx_alt / 1000 / s.market_usd_bn * 100
    base = s.index.min()
    s["pagoda_index"] = s.pagoda_rmb_mn / s.pagoda_rmb_mn[base] * 100
    s["market_index"] = s.market_usd_bn / s.market_usd_bn[base] * 100
    return s.rename_axis("year")


# --------------------------------------------------------------------------- 4. forecasting
def f_drift(y, h):
    return y[-1] + (y[-1] - y[0]) / (len(y) - 1) * np.arange(1, h + 1)

def f_loglinear(y, h):
    t = np.arange(len(y)); b, a = np.polyfit(t, np.log(y), 1)
    return np.exp(a + b * (len(y) - 1 + np.arange(1, h + 1)))

def f_holt(y, h, alpha=0.8, beta=0.2):
    level, trend = y[0], y[1] - y[0]
    for v in y[1:]:
        prev = level
        level = alpha * v + (1 - alpha) * (level + trend)
        trend = beta * (level - prev) + (1 - beta) * trend
    return level + trend * np.arange(1, h + 1)

def f_combination(y, h):
    return (f_drift(y, h) + f_loglinear(y, h)) / 2


def backtest(mk: Market, first_origin: int = 2021, max_h: int = 2) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rolling-origin evaluation on the total and every segment. Returns (summary by method, every forecast)."""
    pop, rec = mk.population, []
    for seg in ["Total"] + mk.segs:
        y_all = mk.wide.loc[seg].revenue_usd_bn
        for origin in range(first_origin, HIST_END):
            train = [y for y in mk.hist if y <= origin]; h = min(max_h, HIST_END - origin)
            y = y_all[train].values
            driver = (f_loglinear(pop[train].values, h) * f_loglinear(mk.wide.loc[seg].volume_per_capita_kg[train].values, h)
                      * f_loglinear(mk.wide.loc[seg].price_usd_per_kg[train].values, h))
            preds = {"Drift": f_drift(y, h), "Log-linear trend": f_loglinear(y, h), "Holt (fixed)": f_holt(y, h),
                     "Driver model": driver, "Combination": f_combination(y, h)}
            for m, p in preds.items():
                for k in range(h):
                    actual = y_all[origin + k + 1]
                    rec.append(dict(segment=seg, origin=origin, horizon=k + 1, target_year=origin + k + 1, method=m,
                                    forecast=p[k], actual=actual, error_pct=(p[k] / actual - 1) * 100))
    bt = pd.DataFrame(rec); bt["abs_error_pct"] = bt.error_pct.abs()
    summ = bt.groupby("method").agg(forecasts=("abs_error_pct", "size"), mape_pct=("abs_error_pct", "mean"),
                                    worst_pct=("abs_error_pct", "max"), bias_pct=("error_pct", "mean")).sort_values("mape_pct")
    by_h = bt.pivot_table(index="method", columns="horizon", values="abs_error_pct", aggfunc="mean").add_prefix("mape_h")
    return summ.join(by_h), bt


def market_forecast(mk: Market) -> pd.DataFrame:
    y = mk.total.revenue_usd_bn[mk.hist].values; h = len(mk.fcst)
    fc = pd.DataFrame({"statista": mk.total.revenue_usd_bn[mk.fcst].values, "this_study": f_combination(y, h),
                       "linear_path": f_drift(y, h), "exponential_path": f_loglinear(y, h)}, index=pd.Index(mk.fcst, name="year"))
    fc["statista_vs_study_pct"] = (fc.statista / fc.this_study - 1) * 100
    fc["inside_envelope"] = (fc.statista >= fc.linear_path) & (fc.statista <= fc.exponential_path)
    return fc


# --------------------------------------------------------------------------- 5. profit model and simulation
DRIVERS = ["store_adds", "rps_growth", "gm", "direct_growth", "opex_mult", "other_cost"]
LABEL = dict(store_adds="Net store openings", rps_growth="Revenue per store growth", gm="Gross margin",
             direct_growth="Direct (B2B) sales growth", opex_mult="Operating cost vs plan", other_cost="Other net costs")
HALF_WIDTH = dict(store_adds=250, rps_growth=0.04, gm=0.025, direct_growth=0.20, opex_mult=0.05, other_cost=0.003)
EVIDENCE = {
    "store_adds": "2025: 656 net closures, of which first half 741 closures and second half 85 openings. Plan: +268, +378, +510.",
    "rps_growth": "2024: about -10%. 2025: flat. Second half of 2025: +1.8% year on year. Plan: +2% a year.",
    "gm": "2021: 11.2%. 2023: 11.5%. FY2025: 7.3%. Second half of 2025: about 10%. Analyst forecasts missed by 0.5 to 5.5 points, always low. Plan: 10.2%, 11.0%, 11.5%.",
    "direct_growth": "2024: +22%. 2025: -5%. Plan: +30%, +20%, +15%.",
    "opex_mult": "The selling-expense ratio rose in both 2024 and 2025.",
    "other_cost": "Finance costs, tax and other items. Backed out of the plan at 0.5-0.7% of revenue; 2024-25 actuals about 0.8-1.2%.",
}


@dataclass
class Model:
    base: dict                # 2025 starting point
    plan: pd.DataFrame        # analyst plan with derived driver paths
    years: list

    @property
    def mode(self) -> dict:
        p = self.plan
        return dict(store_adds=p.store_adds.values, rps_growth=p.rps_growth.values, gm=p.gross_margin.values,
                    direct_growth=p.direct_growth.values, opex_mult=np.ones(len(p)), other_cost=p.other_cost.values)


def build_model(facts: pd.DataFrame, plan: pd.DataFrame) -> Model:
    """Calibrate the driver model to the analyst plan (Galaxy Securities, April 2026)."""
    y0 = HIST_END
    get = lambda m: float(fact(facts, m)[y0])
    base = dict(year=y0, stores_end=get("stores_franchise_network_year_end"), rev_per_store=get("revenue_per_network_store"),
                direct=get("revenue_direct_sales"), other_lines=get("revenue_self_operated") + get("revenue_online") + get("revenue_other"),
                revenue=get("revenue"))
    p = plan.copy()
    p["store_adds"] = p.stores_end.diff().fillna(p.stores_end.iloc[0] - base["stores_end"])
    p["rps_growth"] = p.rev_per_store.pct_change().fillna(p.rev_per_store.iloc[0] / base["rev_per_store"] - 1)
    p["direct_growth"] = p.direct_sales.pct_change().fillna(p.direct_sales.iloc[0] / base["direct"] - 1)
    p["other_lines"] = p.self_operated + p.online + p.other
    p["opex"] = (p.selling + p.admin_rd) * p.revenue
    p["other_cost"] = p.gross_margin - p.selling - p.admin_rd - p.net_profit / p.revenue      # backed out so the model reproduces the plan
    p["breakeven_gm"] = p.opex / p.revenue + p.other_cost
    return Model(base, p, p.index.tolist())


def profit_model(model: Model, store_adds, rps_growth, gm, direct_growth, opex_mult, other_cost, fixed_share=FIXED_SHARE) -> dict:
    """Inputs: arrays of shape (n_trials, n_years). Output arrays in RMB mn.

    network revenue = average stores in the year x revenue per store
    revenue         = network revenue + direct sales + other lines
    operating costs = planned cost x efficiency x [fixed share + (1 - fixed share) x revenue / planned revenue]
    net profit      = revenue x gross margin - operating costs - revenue x other net costs
    """
    a = [np.atleast_2d(np.asarray(x, float)) for x in (store_adds, rps_growth, gm, direct_growth, opex_mult, other_cost)]
    store_adds, rps_growth, gm, direct_growth, opex_mult, other_cost = a
    b, p = model.base, model.plan
    stores_end = b["stores_end"] + np.cumsum(store_adds, axis=1)
    stores_open = np.column_stack([np.full(len(stores_end), b["stores_end"]), stores_end[:, :-1]])
    network = (stores_open + stores_end) / 2 * b["rev_per_store"] * np.cumprod(1 + rps_growth, axis=1)
    direct = b["direct"] * np.cumprod(1 + direct_growth, axis=1)
    revenue = network + direct + p.other_lines.values
    opex = p.opex.values * opex_mult * (fixed_share + (1 - fixed_share) * revenue / p.revenue.values)
    return dict(revenue=revenue, net_profit=revenue * gm - opex - revenue * other_cost, stores_end=stores_end, network=network, direct=direct, opex=opex)


def calibration(model: Model) -> pd.DataFrame:
    out = profit_model(model, **model.mode)
    c = pd.DataFrame({"plan_revenue": model.plan.revenue, "model_revenue": out["revenue"][0],
                      "plan_net_profit": model.plan.net_profit, "model_net_profit": out["net_profit"][0]})
    c["revenue_gap_pct"] = (c.model_revenue / c.plan_revenue - 1) * 100
    c["net_profit_gap"] = c.model_net_profit - c.plan_net_profit
    return c


def make_ranges(model: Model, belief: str = "neutral", width: float = 1.0, shift: dict | None = None) -> dict:
    """Triangular (low, mode, high) per driver and year. Mode is always the plan, plus any user shift.

    neutral  : symmetric, sized from how far each driver moved in 2024-25
    downside : wide below the plan, narrow above it (both analyst revisions on record went down)
    """
    m, n = model.mode, len(model.years)
    if belief == "neutral":
        r = {d: dict(low=m[d] - HALF_WIDTH[d] * width, mode=m[d].copy(), high=m[d] + HALF_WIDTH[d] * width) for d in DRIVERS}
    else:
        ramp = lambda a, b: np.linspace(a, b, n)
        lo_hi = dict(store_adds=(ramp(-200, 0), ramp(400, 700)), rps_growth=(np.full(n, -0.04), np.full(n, 0.05)),
                     gm=(ramp(0.075, 0.085), m["gm"] + 0.008), direct_growth=(np.array([-0.05] + [0.0] * (n - 1)), np.round(m["direct_growth"] + 0.10, 2)),
                     opex_mult=(np.full(n, 0.95), np.full(n, 1.10)), other_cost=(m["other_cost"] - 0.0025, m["other_cost"] + 0.0065))
        r = {d: dict(low=np.asarray(lo_hi[d][0], float), mode=m[d].copy(), high=np.asarray(lo_hi[d][1], float)) for d in DRIVERS}
    for d, s in (shift or {}).items():
        if s:
            r[d] = {k: v + s for k, v in r[d].items()}
    return r


def tri_ppf(u, low, mode, high):
    """Inverse CDF of the triangular distribution."""
    u, low, mode, high = np.broadcast_arrays(u, low, mode, high)
    span = high - low; cut = (mode - low) / span
    return np.where(u < cut, low + np.sqrt(u * span * (mode - low)), high - np.sqrt((1 - u) * span * (high - mode)))


def draw_inputs(u, ranges) -> dict:
    return {d: tri_ppf(u[:, k, :], ranges[d]["low"], ranges[d]["mode"], ranges[d]["high"]) for k, d in enumerate(DRIVERS)}


def simulate(model: Model, ranges: dict, n: int = N_TRIALS, seed: int = SEED, rho: float = 0.0,
             fixed_share: float = FIXED_SHARE, persistent: bool = True) -> dict:
    """Monte Carlo over the six drivers.
    rho        : correlation between revenue-per-store growth and gross margin (Gaussian copula)
    persistent : one draw per driver reused in every year (True) or a fresh draw each year (False)
    """
    rng = np.random.default_rng(seed); ny = len(model.years)
    z = rng.standard_normal((n, len(DRIVERS), 1 if persistent else ny))
    i, j = DRIVERS.index("rps_growth"), DRIVERS.index("gm")
    z[:, j] = rho * z[:, i] + np.sqrt(1 - rho ** 2) * z[:, j]
    u = np.broadcast_to(stats.norm.cdf(z), (n, len(DRIVERS), ny))
    res = profit_model(model, **draw_inputs(u, ranges), fixed_share=fixed_share)
    res["u"] = u
    return res


def summarise(model: Model, sim: dict) -> pd.DataFrame:
    q = lambda a, p: np.percentile(a, p, axis=0)
    return pd.DataFrame({
        "plan_revenue": model.plan.revenue.values, "revenue_p10": q(sim["revenue"], 10), "revenue_median": q(sim["revenue"], 50), "revenue_p90": q(sim["revenue"], 90),
        "plan_net_profit": model.plan.net_profit.values, "net_profit_p10": q(sim["net_profit"], 10), "net_profit_median": q(sim["net_profit"], 50),
        "net_profit_p90": q(sim["net_profit"], 90), "prob_profit_pct": (sim["net_profit"] > 0).mean(axis=0) * 100,
    }, index=pd.Index(model.years, name="year"))


def tornado(model: Model, ranges: dict, sim: dict | None = None, year_idx: int = 1, fixed_share: float = FIXED_SHARE) -> tuple[float, pd.DataFrame]:
    """One-at-a-time swing in one year's net profit when a driver moves to its 10th / 90th percentile."""
    ny = len(model.years)
    u_mode = np.array([[(ranges[d]["mode"][year_idx] - ranges[d]["low"][year_idx]) / (ranges[d]["high"][year_idx] - ranges[d]["low"][year_idx]) for d in DRIVERS]])
    at = lambda u: profit_model(model, **draw_inputs(np.repeat(u[:, :, None], ny, axis=2), ranges), fixed_share=fixed_share)["net_profit"][0, year_idx]
    base, rows = at(u_mode), []
    for k, d in enumerate(DRIVERS):
        lo, hi = u_mode.copy(), u_mode.copy(); lo[0, k], hi[0, k] = 0.10, 0.90
        v_lo, v_hi = at(lo), at(hi)
        row = dict(driver=LABEL[d], downside=min(v_lo, v_hi) - base, upside=max(v_lo, v_hi) - base, swing=abs(v_hi - v_lo))
        if sim is not None:
            row["rank_corr"] = stats.spearmanr(sim["u"][:, k, 0], sim["net_profit"][:, year_idx]).statistic
        rows.append(row)
    t = pd.DataFrame(rows).set_index("driver").sort_values("swing", ascending=False)
    if sim is not None:
        t["share_of_variance_pct"] = t.rank_corr ** 2 / (t.rank_corr ** 2).sum() * 100
    return float(base), t


def lever_values(model: Model, year_idx: int = 1) -> dict:
    """Effect on one year's net profit of a change made in the first plan year, everything else at plan."""
    def run(**override):
        inp = {k: np.array(v, float).copy() for k, v in model.mode.items()}
        for k, (idx, delta) in override.items():
            inp[k][idx] += delta
        return profit_model(model, **inp)["net_profit"][0, year_idx]
    base = run()
    d_gm, d_store, d_rps = run(gm=(slice(None), 0.01)) - base, (run(store_adds=(0, 100)) - base) / 100, run(rps_growth=(0, 0.01)) - base
    return {"gm_point": d_gm, "store_100": d_store * 100, "rps_point": d_rps, "stores_per_gm_point": d_gm / d_store}


def robustness(model: Model) -> pd.DataFrame:
    def one(label, belief="neutral", width=1.0, **kw):
        r = make_ranges(model, belief, width); s = simulate(model, r, **kw); cum = s["net_profit"].sum(axis=1)
        row = dict(scenario=label, **{f"p_{y}": (s["net_profit"][:, k] > 0).mean() * 100 for k, y in enumerate(model.years)},
                   p_cumulative=(cum > 0).mean() * 100, median_cumulative=np.median(cum))
        if kw.get("persistent", True):
            _, t = tornado(model, r, s, fixed_share=kw.get("fixed_share", FIXED_SHARE))
            row["top_driver"] = f"{t.share_of_variance_pct.idxmax()} ({t.share_of_variance_pct.max():.0f}%)"
        else:
            row["top_driver"] = "not ranked"
        return row
    return pd.DataFrame([
        one("Neutral base (costs 50% fixed, no correlation, carry-over)"),
        one("Operating costs 25% fixed", fixed_share=0.25),
        one("Operating costs 75% fixed", fixed_share=0.75),
        one("Price cuts trade margin for sales (correlation -0.5)", rho=-0.5),
        one("Strong demand lifts both (correlation +0.5)", rho=0.5),
        one("Fresh draw every year (no carry-over)", persistent=False),
        one("Neutral ranges 50% wider", width=1.5),
        one("Neutral ranges 50% narrower", width=0.5),
        one("Downside-leaning ranges", belief="downside"),
    ]).set_index("scenario")
