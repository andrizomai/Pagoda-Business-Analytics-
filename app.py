"""Pagoda Turnaround Simulator: MSBA capstone proof of concept.

Run locally:   streamlit run app.py
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import analytics as an

ROOT = Path(__file__).parent
DATA = ROOT / "data"
BUNDLED = DATA / "statista_fresh_fruits_china.xlsx"

st.set_page_config(page_title="Pagoda Turnaround Simulator", page_icon="🍊", layout="wide")

# ----------------------------------------------------------------------------- style
BLUE, ORANGE, RED, INK, INK2, MUTED, GRID = "#2a78d6", "#eb6834", "#e34948", "#111a15", "#4b554e", "#7d857f", "#e1e0d9"

def style(chart: alt.Chart, height: int = 300) -> alt.Chart:
    return (chart.properties(height=height)
            .configure_view(stroke=None)
            .configure_axis(grid=True, gridColor=GRID, domainColor="#c3c8c0", tickColor="#c3c8c0", labelColor=MUTED, titleColor=INK2,
                            labelFontSize=12, titleFontSize=12, titleFontWeight="normal")
            .configure_axisX(grid=False)
            .configure_legend(orient="top", title=None, labelColor=INK2, labelFontSize=12, symbolStrokeWidth=2)
            .configure(background="transparent"))

LEG = alt.Legend(orient="top", title=None, labelColor=INK2, labelFontSize=12, symbolStrokeWidth=2, labelLimit=260)

def show(chart: alt.Chart, height: int = 300):
    st.altair_chart(style(chart, height), width="stretch", theme=None)

def pct_text(p: float) -> str:
    return ">99%" if p > 99.5 else "<1%" if p < 0.5 else f"{p:.0f}%"

st.markdown("""
<style>
  .block-container {padding-top: 3.6rem; max-width: 1240px;}
  h1 {letter-spacing: -0.02em; line-height: 1.1;}
  [data-testid="stMetricValue"] {font-size: 2rem; font-weight: 700; letter-spacing: -0.02em;}
  [data-testid="stMetricLabel"] p {font-weight: 600;}
  .eyebrow {font-size: .75rem; letter-spacing: .09em; text-transform: uppercase; color: #1c6a49; font-weight: 700; margin-bottom: -.4rem;}
  .note {color: #4b554e; font-size: .9rem;}
  .verdict {border-left: 4px solid #1c6a49; padding: .2rem 0 .2rem 1rem; margin: .4rem 0 1rem; font-size: 1.05rem;}
</style>""", unsafe_allow_html=True)


# ----------------------------------------------------------------------------- data
@st.cache_resource(show_spinner="Reading the Statista workbook…")
def get_market(digest: str | None, payload: bytes | None) -> an.Market:
    return an.load_market(io.BytesIO(payload) if payload else BUNDLED)

def drive_download_url(url: str) -> str:
    """Turn a Google Drive share link into a direct-download link; other links pass through."""
    import re
    m = re.search(r"/d/([\w-]+)", url) or re.search(r"[?&]id=([\w-]+)", url)
    return f"https://drive.google.com/uc?export=download&id={m.group(1)}" if "drive.google.com" in url and m else url

@st.cache_resource(show_spinner="Loading the stored Statista workbook…")
def fetch_stored_workbook(url: str) -> bytes | None:
    """Download the workbook from a private link kept in Streamlit secrets (never in the repo)."""
    import urllib.request
    try:
        with urllib.request.urlopen(drive_download_url(url), timeout=30) as r:
            data = r.read()
        return data if data[:2] == b"PK" else None   # an .xlsx is a zip file; anything else is an error page
    except Exception:
        return None

def stored_workbook_url() -> str | None:
    try:
        return st.secrets.get("STATISTA_URL")
    except Exception:                                # no secrets configured
        return None

@st.cache_resource
def get_company():
    facts, plan = an.load_company(DATA / "pagoda_facts.csv", DATA / "analyst_plan.csv")
    return facts, plan, an.build_model(facts, plan)

@st.cache_data(show_spinner="Running validation checks…")
def get_checks(digest):            # digest only keys the cache
    return an.quality_checks(mk)

@st.cache_data(show_spinner="Back-testing forecast methods…")
def get_forecast(digest):
    summ, detail = an.backtest(mk)
    return summ, detail, an.market_forecast(mk)

@st.cache_data(show_spinner="Running robustness scenarios…")
def get_robustness():
    return an.robustness(model)

@st.cache_data(show_spinner=False, max_entries=48)
def run_sim(belief, gm, stores, rps, opex, fixed, rho, persistent, n):
    ranges = an.make_ranges(model, belief, shift=dict(gm=gm / 100, store_adds=stores, rps_growth=rps / 100, opex_mult=opex / 100))
    sim = an.simulate(model, ranges, n=n, rho=rho, fixed_share=fixed / 100, persistent=persistent)
    base, tor = an.tornado(model, ranges, sim if persistent else None, fixed_share=fixed / 100)
    return an.summarise(model, sim), sim["net_profit"], sim["revenue"], tor, base


with st.sidebar:
    st.markdown("### Data")
    up = st.file_uploader("Refresh with a new Statista export (.xlsx)", type="xlsx",
                          help="Statista Market Insights > Fresh Fruits > China > download as XLSX. The app re-runs every check and chart on the new file.")
    payload = up.getvalue() if up else None
    stored = False
    if payload is None and not BUNDLED.exists():
        url = stored_workbook_url()
        payload = fetch_stored_workbook(url) if url else None
        stored = payload is not None
        if payload is None:
            st.error("No market data found. Upload the Statista export to start."
                     + (" The stored copy could not be downloaded; check the STATISTA_URL secret and the file's sharing setting." if url else ""))
            st.stop()
    digest = hashlib.md5(payload).hexdigest() if payload else "bundled"
    try:
        mk = get_market(digest, payload)
        source_label = (up.name if up else "Stored Statista export (accessed 13 Aug 2026)" if stored
                        else "Bundled export (accessed 13 Aug 2026)")
    except Exception as e:                       # bad upload: say why, fall back
        st.error(f"Could not read that workbook: {e}")
        if not BUNDLED.exists():
            st.stop()
        mk, digest, source_label = get_market("bundled", None), "bundled", "Bundled export (upload failed)"
    st.caption(f"Market data: {source_label}")
    fx_alt = st.number_input("Currency check: CNY per USD", 6.0, 8.5, 7.2, 0.1,
                             help="The workbook's own exchange-rate series is a projection. The share comparison is repeated at this rate.")
    st.markdown("### About")
    st.caption("MSBA capstone proof of concept. Market figures are Statista model estimates. Company figures are transcribed from four "
               "broker reports with page references (see the Data and method tab). Probabilities depend on the uncertainty ranges shown in the simulator.")

facts, plan, model = get_company()
tot, Y0, Y1 = mk.total, mk.years[0], mk.years[-1]
share = an.share_table(mk, facts, fx_alt)
levers = an.lever_values(model)
decomp = an.decomposition(mk)
bt_summary, bt_detail, fc = get_forecast(digest)
dq, outliers = get_checks(digest)
base_res = {b: run_sim(b, 0.0, 0, 0.0, 0, 50, 0.0, True, an.N_TRIALS)[0] for b in ("neutral", "downside")}
PY = model.years

# ----------------------------------------------------------------------------- header
st.markdown('<div class="eyebrow">MSBA capstone · analytics proof of concept · 百果园 2411.HK</div>', unsafe_allow_html=True)
st.title("The fruit market grew. Pagoda did not. The way back is gross margin.")
m_up = share.market_index.iloc[-1] - 100; p_chg = share.pagoda_index.iloc[-1] - 100
st.markdown(f"China's fresh-fruit retail market is up **{m_up:.0f}%** since {share.index[0]} in Statista's data, while Pagoda's revenue is "
            f"**{'down' if p_chg < 0 else 'up'} {abs(p_chg):.0f}%** and the company has lost money for two years. This app tests the market assumption, "
            f"then simulates {PY[0]} to {PY[-1]} to find how likely a return to profit is and which lever moves it.")

c = st.columns(4)
c[0].metric(f"Market, {an.HIST_END}", f"${tot.revenue_usd_bn[an.HIST_END]:.0f}bn", f"{an.cagr(tot.revenue_usd_bn, Y0, an.HIST_END):.1%} a year since {Y0}", delta_color="off", delta_arrow="off")
c[1].metric("Pagoda revenue as share of market", f"{share.share_proxy_pct.iloc[-1]:.1f}%", f"{share.share_proxy_pct.iloc[-1] - share.share_proxy_pct.iloc[0]:+.1f} pt since {share.index[0]}")
c[2].metric(f"Margin needed to break even, {PY[0]}", f"{model.plan.breakeven_gm.iloc[0]:.1%}", f"plan assumes {model.plan.gross_margin.iloc[0]:.1%}", delta_color="off", delta_arrow="off")
c[3].metric("One point of gross margin equals", f"~{round(levers['stores_per_gm_point'], -1):,.0f} stores", f"network has {model.base['stores_end']:,.0f}", delta_color="off", delta_arrow="off")

tab_over, tab_mkt, tab_fc, tab_sim, tab_case, tab_data = st.tabs(
    ["Overview", "Market diagnostic", "Forecast check", "Turnaround simulator", "Business case", "Data and method"])

# ----------------------------------------------------------------------------- overview
with tab_over:
    left, right = st.columns(2)
    with left:
        st.subheader("Pagoda fell behind a growing market")
        st.caption(f"Revenue index, {share.index[0]} = 100. Market in USD, Pagoda in RMB.")
        idx_years = [y for y in mk.hist if y >= share.index[0]]
        mline = pd.DataFrame({"year": idx_years, "series": "China fresh-fruit market", "value": (tot.revenue_usd_bn[idx_years] / tot.revenue_usd_bn[share.index[0]] * 100).values})
        pline = pd.DataFrame({"year": share.index, "series": "Pagoda revenue", "value": share.pagoda_index.values})
        d = pd.concat([mline, pline])
        base = alt.Chart(d).encode(x=alt.X("year:O", title=None, axis=alt.Axis(labelAngle=0)),
                                   y=alt.Y("value:Q", title=None, scale=alt.Scale(zero=False, nice=True)),
                                   color=alt.Color("series:N", scale=alt.Scale(domain=["China fresh-fruit market", "Pagoda revenue"], range=[BLUE, ORANGE]), legend=LEG),
                                   tooltip=[alt.Tooltip("year:O"), alt.Tooltip("series:N"), alt.Tooltip("value:Q", format=".0f", title="index")])
        last = d[d.year == d.year.max()]
        labels = alt.Chart(last).mark_text(align="left", dx=8, fontWeight=600, color=INK).encode(x="year:O", y="value:Q", text=alt.Text("value:Q", format=".0f"))
        show(base.mark_line(strokeWidth=2) + base.mark_point(size=50, filled=True, opacity=1) + labels)
        g_p, g_m = an.cagr(share.pagoda_rmb_mn, share.index[0], 2023), an.cagr(tot.revenue_usd_bn, share.index[0], 2023)
        st.markdown(f"<div class='note'>Pagoda was already lagging before the 2024 crisis: {g_p:.1%} a year from {share.index[0]} to 2023 against {g_m:.1%} for the market. "
                    f"The share figure is a proxy, since most of Pagoda's revenue is wholesale to franchisees.</div>", unsafe_allow_html=True)
    with right:
        st.subheader(f"Chance of a net profit, {PY[0]} to {PY[-1]}")
        st.caption("20,000 simulated futures around the analyst plan, under two views of how far to trust it.")
        odds = pd.concat([pd.DataFrame({"year": PY, "view": "Plan as likely beaten as missed", "p": base_res["neutral"].prob_profit_pct.values}),
                          pd.DataFrame({"year": PY, "view": "Plan is the best case", "p": base_res["downside"].prob_profit_pct.values})])
        odds["label"] = odds.p.map(pct_text)
        bars = alt.Chart(odds).encode(x=alt.X("year:O", title=None, axis=alt.Axis(labelAngle=0)), xOffset="view:N",
                                      y=alt.Y("p:Q", title="% of trials ending in profit", scale=alt.Scale(domain=[0, 100])),
                                      color=alt.Color("view:N", scale=alt.Scale(domain=["Plan as likely beaten as missed", "Plan is the best case"], range=[BLUE, ORANGE]), legend=LEG),
                                      tooltip=[alt.Tooltip("year:O"), alt.Tooltip("view:N"), alt.Tooltip("p:Q", format=".1f", title="% profit")])
        show(bars.mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=26) + bars.mark_text(dy=-8, color=INK, fontWeight=600).encode(text="label:N", color=alt.value(INK)))
        st.markdown(f"<div class='note'>{PY[0]} is a breakeven year at best: {pct_text(base_res['neutral'].prob_profit_pct.iloc[0])} if the plan is unbiased, "
                    f"{pct_text(base_res['downside'].prob_profit_pct.iloc[0])} if it is the best case, as the plans for 2023, 2024 and 2025 turned out to be.</div>", unsafe_allow_html=True)

    st.subheader("What the analysis says")
    tor_n = run_sim("neutral", 0.0, 0, 0.0, 0, 50, 0.0, True, an.N_TRIALS)[3]
    h1_tbl, h1 = an.first_half_2026_check(model, facts)
    gm_share = tor_n.share_of_variance_pct["Gross margin"]
    st.markdown(f"""
1. **The market is not the problem.** It grew {an.cagr(tot.revenue_usd_bn, Y0, an.HIST_END):.1%} a year from {Y0} to {an.HIST_END}, about {decomp.volume_share_pct.iloc[0]:.0f}% of it from volume, and an independent forecast agrees with Statista's to within {abs(fc.statista_vs_study_pct.iloc[-1]):.0f}% in {Y1}.
2. **Pagoda's position in the market roughly halved**, from {share.share_proxy_pct.iloc[0]:.1f}% to {share.share_proxy_pct.iloc[-1]:.1f}% of market revenue.
3. **Gross margin is the lever.** It carries about {gm_share:.0f}% of the variation in {PY[1]} profit. One point of margin is worth about RMB {levers['gm_point']:.0f} mn; 100 net new stores are worth about RMB {levers['store_100']:.0f} mn.
4. **The first half of 2026 moved the margin lever first.** Gross margin reached {h1['gross_margin']:.1%} ({h1['gm_core']:.1%} excluding the new Seven-Star alliance), above the plan and every past forecast, and Pagoda earned RMB {h1['net_profit']:.0f} mn, more than the plan's full year. CICC attributes the gain to product-mix optimisation.
5. **Analytics should go where the margin is.** First pricing and grade mix, since analysts attribute the margin fall to the move to value pricing. Then procurement. Demand forecasting is the enabler for both; store spoilage lands mainly on franchisees, who buy the fruit from Pagoda. All three need Pagoda's internal sales, pricing and waste data, which is the scale-up step.
""")

# ----------------------------------------------------------------------------- market
with tab_mkt:
    a, b = st.columns(2)
    with a:
        st.subheader("Where growth comes from")
        st.caption("Average yearly growth in log points, split into volume and price.")
        dd = decomp[["volume", "price"]].rename(columns={"volume": "Volume", "price": "Price"}).reset_index(names="period").melt("period", var_name="part", value_name="points")
        dd["order"] = dd.part.map({"Volume": 0, "Price": 1})
        bars = alt.Chart(dd).mark_bar(size=34, stroke="#ffffff", strokeWidth=2).encode(
            y=alt.Y("period:N", title=None, sort=None), x=alt.X("points:Q", title="log points a year", stack="zero"),
            color=alt.Color("part:N", scale=alt.Scale(domain=["Volume", "Price"], range=[BLUE, ORANGE]), legend=LEG), order="order:Q",
            tooltip=[alt.Tooltip("period:N"), alt.Tooltip("part:N"), alt.Tooltip("points:Q", format=".2f")])
        show(bars, 170)
        st.markdown(f"<div class='note'>Per-person consumption at home rose from {tot.volume_per_capita_kg[Y0]:.1f} kg to {tot.volume_per_capita_kg[an.HIST_END]:.1f} kg. "
                    f"Statista's forecast has volume growth slowing to {decomp.volume.iloc[1]:.1f} points and price carrying more.</div>", unsafe_allow_html=True)
        st.subheader("Online share of fresh-fruit revenue")
        st.caption("Range across the six series in the export. Their segment labels were lost, so only the common pattern is shown.")
        ch = an.channel_summary(mk).reset_index()
        band = alt.Chart(ch).mark_area(color=BLUE, opacity=0.14).encode(x=alt.X("year:O", title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("lowest:Q", title="% of revenue"), y2="highest:Q")
        med = alt.Chart(ch).mark_line(color=BLUE, strokeWidth=2, point=alt.OverlayMarkDef(size=40, filled=True, color=BLUE)).encode(
            x="year:O", y="median:Q", tooltip=[alt.Tooltip("year:O"), alt.Tooltip("lowest:Q", format=".1f"), alt.Tooltip("median:Q", format=".1f"), alt.Tooltip("highest:Q", format=".1f")])
        show(band + med, 230)
    with b:
        seg = an.segment_table(mk)
        st.subheader(f"Growth by segment, {Y0} to {an.HIST_END}")
        st.caption("Revenue CAGR, %. The line marks the total market.")
        sb = seg.reset_index().sort_values("revenue_cagr_pct", ascending=False)
        mkt_rate = an.cagr(tot.revenue_usd_bn, Y0, an.HIST_END) * 100
        bars = alt.Chart(sb).mark_bar(size=20, color=BLUE, cornerRadiusTopRight=4, cornerRadiusBottomRight=4).encode(
            y=alt.Y("segment:N", sort=None, title=None), x=alt.X("revenue_cagr_pct:Q", title="% a year"),
            tooltip=[alt.Tooltip("segment:N"), alt.Tooltip("revenue_cagr_pct:Q", format=".1f", title="CAGR %"), alt.Tooltip("revenue_usd_bn:Q", format=".1f", title=f"{an.HIST_END} USD bn")])
        txt = alt.Chart(sb).mark_text(align="left", dx=5, color=INK).encode(y=alt.Y("segment:N", sort=None), x="revenue_cagr_pct:Q", text=alt.Text("revenue_cagr_pct:Q", format=".1f"))
        rule = alt.Chart(pd.DataFrame({"x": [mkt_rate]})).mark_rule(color=INK2).encode(x="x:Q")
        show(bars + txt + rule, 200)
        st.dataframe(seg[["revenue_usd_bn", "share_now_pct", "share_change_pt", "price_usd_kg", "statista_cagr_pct"]].rename(columns={
            "revenue_usd_bn": f"Revenue {an.HIST_END}, USD bn", "share_now_pct": "Share, %", "share_change_pt": f"Share change since {Y0}, pt",
            "price_usd_kg": "Price, USD/kg", "statista_cagr_pct": f"Statista CAGR to {Y1}, %"}).style.format("{:.1f}"), width="stretch")
        gp = an.global_position(mk)
        st.markdown(f"<div class='note'>Segment growth sits in a narrow band, which is typical of modelled market data. Globally, China ranks "
                    f"{int(gp.china_rank[an.HIST_END])} of {len(mk.raw['Global Comparison']['REVENUE COMPARISON in billion USD (US$)'])} countries, behind "
                    f"{gp.largest_market[an.HIST_END]}, with {gp.china_share_pct[an.HIST_END]:.0f}% of the total.</div>", unsafe_allow_html=True)

    st.subheader("Pagoda against the market")
    st.dataframe(share.rename(columns={"pagoda_rmb_mn": "Pagoda revenue, RMB mn", "market_usd_bn": "Market, USD bn", "fx_workbook": "CNY per USD (workbook)",
                                       "share_proxy_pct": "Share proxy, %", "share_proxy_alt_fx_pct": f"Share proxy at {fx_alt:.1f}, %",
                                       "pagoda_index": "Pagoda index", "market_index": "Market index"})
                 .style.format({"Pagoda revenue, RMB mn": "{:,.0f}", "Market, USD bn": "{:.1f}", "CNY per USD (workbook)": "{:.2f}", "Share proxy, %": "{:.2f}",
                                f"Share proxy at {fx_alt:.1f}, %": "{:.2f}", "Pagoda index": "{:.0f}", "Market index": "{:.0f}"}), width="stretch")
    held = share.share_proxy_pct[2023] / 100 * tot.revenue_usd_bn[an.HIST_END] * 1000 * share.fx_workbook[an.HIST_END]
    st.markdown(f"<div class='note'>Had Pagoda held its 2023 share proxy, {an.HIST_END} revenue would have been about RMB {held:,.0f} mn against the actual "
                f"{share.pagoda_rmb_mn[an.HIST_END]:,.0f} mn. The 2019 figure is approximate and 2022 is derived from reported growth.</div>", unsafe_allow_html=True)

# ----------------------------------------------------------------------------- forecast
with tab_fc:
    st.subheader("Does Statista's forecast survive an independent check?")
    st.markdown(f"<div class='verdict'>Yes. Statista's path stays between a linear and an exponential continuation of history in "
                f"{'every year' if fc.inside_envelope.all() else f'{int(fc.inside_envelope.sum())} of {len(fc)} years'}, and ends at "
                f"${fc.statista.iloc[-1]:.0f}bn in {Y1} against ${fc.this_study.iloc[-1]:.0f}bn in this study.</div>", unsafe_allow_html=True)
    a, b = st.columns([3, 2])
    with a:
        hist = pd.DataFrame({"year": mk.hist, "series": "History", "value": tot.revenue_usd_bn[mk.hist].values})
        join = lambda col, name: pd.DataFrame({"year": [an.HIST_END] + mk.fcst, "series": name, "value": [tot.revenue_usd_bn[an.HIST_END]] + fc[col].tolist()})
        lines = pd.concat([hist, join("this_study", "This study"), join("statista", "Statista")])
        env = fc.reset_index()[["year", "linear_path", "exponential_path"]]
        band = alt.Chart(env).mark_area(color=BLUE, opacity=0.13).encode(x=alt.X("year:O", title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("linear_path:Q", title="USD bn"), y2="exponential_path:Q",
                                                                         tooltip=[alt.Tooltip("year:O"), alt.Tooltip("linear_path:Q", format=".1f", title="linear"), alt.Tooltip("exponential_path:Q", format=".1f", title="exponential")])
        ln = alt.Chart(lines).encode(x=alt.X("year:O", sort=mk.years), y="value:Q",
                                     color=alt.Color("series:N", scale=alt.Scale(domain=["History", "This study", "Statista"], range=[INK, BLUE, ORANGE]), legend=LEG),
                                     tooltip=[alt.Tooltip("year:O"), alt.Tooltip("series:N"), alt.Tooltip("value:Q", format=".1f", title="USD bn")])
        show(band + ln.mark_line(strokeWidth=2) + ln.mark_point(size=40, filled=True, opacity=1), 340)
        st.caption("Shaded: range between linear and exponential growth. It expresses disagreement between two defensible models, not a statistical interval; "
                   "eight annual observations cannot support one at a six-year horizon.")
    with b:
        st.markdown("**Rolling-origin backtest**")
        st.caption(f"Train to year T, forecast T+1 and T+2, move T forward. Origins 2021 to {an.HIST_END - 1}, total market and five segments: {int(bt_summary.forecasts.iloc[0])} forecasts per method.")
        st.dataframe(bt_summary.rename(columns={"mape_pct": "Mean error, %", "bias_pct": "Bias, %", "worst_pct": "Worst, %", "mape_h1": "1 yr", "mape_h2": "2 yr"})
                     [["Mean error, %", "Bias, %", "1 yr", "2 yr", "Worst, %"]].style.format("{:+.2f}", subset=["Bias, %"]).format("{:.2f}", subset=["Mean error, %", "1 yr", "2 yr", "Worst, %"])
                     .highlight_min(subset=["Mean error, %"], color="#dfeee6"), width="stretch")
        st.markdown("<div class='note'><b>Why simple methods.</b> With eight annual points, models with many parameters would fit noise. "
                    "Constant-rate methods overshoot and constant-increment methods undershoot; averaging the two cancels most of both biases. "
                    "Errors here are a lower bound, because the history is itself a smoothed model output.</div>", unsafe_allow_html=True)
    with st.expander("Forecast table and every backtest forecast"):
        st.dataframe(fc.style.format({c_: "{:.1f}" for c_ in ["statista", "this_study", "linear_path", "exponential_path", "statista_vs_study_pct"]}), width="stretch")
        st.dataframe(bt_detail.style.format({"forecast": "{:.2f}", "actual": "{:.2f}", "error_pct": "{:+.2f}", "abs_error_pct": "{:.2f}"}), width="stretch", height=260)

# ----------------------------------------------------------------------------- simulator
DEFAULTS = dict(sl_gm=0.0, sl_stores=0, sl_rps=0.0, sl_opex=0, sl_fixed=50, sl_rho=0.0, sl_carry=True)
def reset():
    for k, v in DEFAULTS.items():
        st.session_state[k] = v

with tab_sim:
    st.subheader(f"Turnaround simulator, {PY[0]} to {PY[-1]}")
    cal = an.calibration(model)
    st.markdown(f"The model rebuilds profit from six drivers. Given the analysts' own inputs it reproduces their forecast to within "
                f"{cal.revenue_gap_pct.abs().max():.1f}% on revenue and RMB {cal.net_profit_gap.abs().max():.0f} mn on profit. Each run draws {an.N_TRIALS:,} possible futures "
                f"around that plan. Move the sliders to shift the most likely outcome away from the plan.")
    h1_tbl, h1 = an.first_half_2026_check(model, facts)
    st.info(f"**First-half 2026 results are in** (CICC, 7 Sep 2026). Gross margin {h1['gross_margin']:.1%}, at the {h1_tbl.loc['Gross margin', 'pct_neutral']:.0f}th percentile of the neutral range "
            f"and above the whole 'best case' range. Net profit RMB {h1['net_profit']:+.0f} mn against a full-year plan of {model.plan.net_profit.iloc[0]:+.0f}. "
            f"{h1['alliance_share']:.0%} of revenue came from the new Seven-Star alliance, which this model does not include. The ranges below are unchanged so results stay comparable.", icon="📌")
    with st.expander("First half of 2026 against the simulator's 2026 assumptions"):
        st.dataframe(h1_tbl.rename(columns={"plan_2026": "Plan 2026", "first_half_2026": "1H26 actual", "pct_neutral": "Percentile, neutral range", "pct_downside": "Percentile, best-case range", "note": "Note"})
                     .style.format({"Plan 2026": "{:,.1f}", "1H26 actual": "{:,.1f}", "Percentile, neutral range": "{:.0f}", "Percentile, best-case range": "{:.0f}"}), width="stretch")
        st.caption(f"Revenue {h1['revenue']:,.0f} (+{h1['revenue_growth']:.1%} year on year), of which the alliance {h1['alliance']:,.0f}; excluding it, revenue changed {h1['core_growth']:+.1%}. "
                   "Stores: 4,752 at end-June, already past the full-year plan of 4,728. Source: CICC 2026 pp.1, 4.")
    ctl, out = st.columns([1, 2.2], gap="large")
    with ctl:
        belief_label = st.radio("How far do you trust the analyst plan?", ["As likely beaten as missed", "It is the best case"], key="belief",
                                help="First option: symmetric ranges sized from how far each driver moved in 2024-25 and from past forecast misses. Second: wide below the plan, narrow above it, because every analyst forecast on record came in too high.")
        belief = "neutral" if belief_label.startswith("As") else "downside"
        gm = st.slider("Gross margin against plan, pt", -3.0, 2.0, 0.0, 0.1, key="sl_gm", help="Plan: 10.2%, 11.0%, 11.5%. Second half of 2025: about 10%.")
        stores = st.slider("Net store openings against plan, per year", -500, 300, 0, 10, key="sl_stores", help="Plan: +268, +378, +510. 2025: 656 net closures.")
        rps = st.slider("Revenue per store growth against plan, pt", -6.0, 4.0, 0.0, 0.5, key="sl_rps", help="Plan: +2% a year. 2024: about -10%. 2025: flat.")
        opex = st.slider("Operating costs against plan, %", -10, 15, 0, 1, key="sl_opex", help="Selling, administrative and R&D costs. Plan: 9.5% of revenue in 2026.")
        with st.expander("Model assumptions"):
            fixed = st.slider("Share of operating costs that is fixed, %", 0, 100, 50, 5, key="sl_fixed", help="An assumption. Higher means a revenue miss hurts profit more.")
            rho = st.slider("Correlation: sales per store and gross margin", -0.8, 0.8, 0.0, 0.1, key="sl_rho",
                            help="Negative: price cuts buy sales at the cost of margin. Positive: strong demand lifts both.")
            carry = st.toggle("A bad year carries over to the next", True, key="sl_carry", help="On: one draw per driver for all years. Off: a fresh draw each year.")
        st.button("Reset to plan", on_click=reset)

    res, npv, revv, tor, tor_base = run_sim(belief, gm, stores, rps, opex, fixed, rho, carry, an.N_TRIALS)
    with out:
        cols = st.columns(len(PY))
        for k, y in enumerate(PY):
            p = res.prob_profit_pct[y]
            verdict = "Likely" if p >= 75 else "Toss-up" if p >= 40 else "Unlikely"
            cols[k].metric(f"{y}: chance of profit", pct_text(p), verdict, delta_color="normal" if p >= 75 else "inverse" if p < 40 else "off", delta_arrow="off")
            cols[k].caption(f"Median {res.net_profit_median[y]:+,.0f} mn · plan {res.plan_net_profit[y]:+,.0f} mn")
        cum = npv.sum(axis=1)
        st.caption(f"Three-year total: median RMB {np.median(cum):+,.0f} mn, positive in {pct_text((cum > 0).mean() * 100)} of trials. Plan: {model.plan.net_profit.sum():+,.0f} mn.")

        year = st.radio("Year shown", PY, horizontal=True, key="hist_year", label_visibility="collapsed")
        k = PY.index(year); x = npv[:, k]; planv = float(model.plan.net_profit[year])
        lo, hi = min(np.percentile(x, 0.5), planv, 0), max(np.percentile(x, 99.5), planv, 0)
        step = float(max(5, np.ceil((hi - lo) / 30 / 5) * 5)); edges = np.arange(np.floor(lo / step) * step, np.ceil(hi / step) * step + step, step)
        cnt, _ = np.histogram(np.clip(x, edges[0], edges[-1] - 1e-9), bins=edges)
        hd = pd.DataFrame({"lo": edges[:-1] + step * 0.06, "hi": edges[1:] - step * 0.06, "range": [f"{a:+,.0f} to {b:+,.0f}" for a, b in zip(edges[:-1], edges[1:])], "share": cnt / len(x) * 100})
        hd["result"] = np.where(edges[:-1] + step / 2 >= 0, "Profit", "Loss")
        hd = hd[hd.share > 0].assign(zero=0.0)
        bars = alt.Chart(hd).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
            x=alt.X("lo:Q", title="Net profit, RMB mn", scale=alt.Scale(domain=[float(edges[0]), float(edges[-1])], nice=False)), x2="hi:Q", y=alt.Y("share:Q", title="% of trials"), y2="zero:Q",
            color=alt.Color("result:N", scale=alt.Scale(domain=["Profit", "Loss"], range=[BLUE, RED]), legend=LEG),
            tooltip=[alt.Tooltip("range:N", title="RMB mn"), alt.Tooltip("share:Q", format=".1f", title="% of trials")])
        zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color=INK).encode(x="x:Q")
        prule = alt.Chart(pd.DataFrame({"x": [planv], "t": ["analyst plan"]})).mark_rule(color=INK2, strokeDash=[4, 3], strokeWidth=1.5).encode(x="x:Q", tooltip=[alt.Tooltip("x:Q", title="analyst plan")])
        ptxt = alt.Chart(pd.DataFrame({"x": [planv], "y": [hd.share.max()], "t": ["plan"]})).mark_text(align="left", dx=5, dy=-2, color=INK2).encode(x="x:Q", y="y:Q", text="t:N")
        st.markdown(f"**Net profit in {year}: {pct_text(res.prob_profit_pct[year])} of trials end in profit**")
        show(bars + zero + prule + ptxt, 260)

        a, b = st.columns(2)
        with a:
            st.markdown(f"**Which driver moves {PY[1]} profit most**")
            st.caption("Change in net profit when one driver moves to its 10th or 90th percentile and the rest stay put. RMB mn.")
            td = tor.reset_index().melt("driver", ["downside", "upside"], var_name="end", value_name="change")
            td["end"] = td.end.map({"downside": "Unfavourable", "upside": "Favourable"})
            tb = alt.Chart(td).mark_bar(size=16).encode(y=alt.Y("driver:N", sort=tor.index.tolist(), title=None, axis=alt.Axis(labelLimit=190)), x=alt.X("change:Q", title=None),
                                                        color=alt.Color("end:N", scale=alt.Scale(domain=["Unfavourable", "Favourable"], range=[RED, BLUE]), legend=LEG),
                                                        tooltip=[alt.Tooltip("driver:N"), alt.Tooltip("end:N"), alt.Tooltip("change:Q", format="+.0f", title="RMB mn")])
            show(tb + alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color=INK).encode(x="x:Q"), 230)
        with b:
            st.markdown("**Profit path against the plan**")
            st.caption("Median with the 10th to 90th percentile range. RMB mn.")
            path = res.reset_index()
            band = alt.Chart(path).mark_area(color=BLUE, opacity=0.14).encode(x=alt.X("year:O", title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("net_profit_p10:Q", title=None), y2="net_profit_p90:Q")
            pl = pd.concat([pd.DataFrame({"year": PY, "series": "Simulated median", "value": res.net_profit_median.values}),
                            pd.DataFrame({"year": PY, "series": "Analyst plan", "value": res.plan_net_profit.values})])
            ln = alt.Chart(pl).encode(x="year:O", y="value:Q", color=alt.Color("series:N", scale=alt.Scale(domain=["Simulated median", "Analyst plan"], range=[BLUE, INK2]), legend=LEG),
                                      strokeDash=alt.StrokeDash("series:N", scale=alt.Scale(domain=["Simulated median", "Analyst plan"], range=[[1, 0], [4, 3]]), legend=None),
                                      tooltip=[alt.Tooltip("year:O"), alt.Tooltip("series:N"), alt.Tooltip("value:Q", format="+,.0f", title="RMB mn")])
            show(band + ln.mark_line(strokeWidth=2) + ln.mark_point(size=40, filled=True, opacity=1) + alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=INK).encode(y="y:Q"), 230)

        with st.expander("How far off have analyst forecasts been?"):
            tr = an.forecast_track_record(facts, DATA / "analyst_forecasts.csv")
            st.caption(f"Revenue came in below forecast in {(tr.revenue_error_pct < 0).sum()} of {len(tr)} cases (mean {tr.revenue_error_pct.mean():.0f}%). "
                       f"Gross margin came in below in {(tr.gross_margin_error_pt < 0).sum()} of {len(tr)} (mean {tr.gross_margin_error_pt.mean():+.1f} pt). "
                       "This is why the gross-margin range is wide and why the 'best case' view is offered.")
            st.dataframe(tr[["forecast", "made", "year", "horizon", "revenue", "revenue_actual", "revenue_error_pct", "net_profit", "net_profit_actual", "gross_margin", "gross_margin_actual", "gross_margin_error_pt"]]
                         .rename(columns={"forecast": "Forecast by", "made": "Made", "year": "For", "horizon": "Horizon", "revenue": "Revenue forecast", "revenue_actual": "Actual", "revenue_error_pct": "Miss, %",
                                          "net_profit": "Net profit forecast", "net_profit_actual": "Actual ", "gross_margin": "Margin forecast, %", "gross_margin_actual": "Actual, %", "gross_margin_error_pt": "Miss, pt"})
                         .style.format({"Revenue forecast": "{:,.0f}", "Actual": "{:,.0f}", "Miss, %": "{:+.0f}", "Net profit forecast": "{:+,.0f}", "Actual ": "{:+,.0f}", "Margin forecast, %": "{:.1f}", "Actual, %": "{:.1f}", "Miss, pt": "{:+.1f}"}),
                         width="stretch", hide_index=True)
        with st.expander("Numbers behind the charts"):
            t = res.copy(); t["prob_profit_pct"] = t.prob_profit_pct.round(1)
            st.dataframe(t.T.style.format("{:,.1f}"), width="stretch")
            rng = an.make_ranges(model, belief, shift=dict(gm=gm / 100, store_adds=stores, rps_growth=rps / 100, opex_mult=opex / 100))
            fmt = dict(store_adds=lambda v: f"{v:+,.0f}", rps_growth=lambda v: f"{v:+.1%}", gm=lambda v: f"{v:.1%}", direct_growth=lambda v: f"{v:+.0%}", opex_mult=lambda v: f"{v:.0%}", other_cost=lambda v: f"{v:.2%}")
            st.markdown("**Uncertainty ranges in use** (low · most likely · high)")
            st.dataframe(pd.DataFrame({str(y): {an.LABEL[d]: " · ".join(fmt[d](rng[d][key][i]) for key in ("low", "mode", "high")) for d in an.DRIVERS} for i, y in enumerate(PY)})
                         .assign(**{"Evidence the range leans on": [an.EVIDENCE[d] for d in an.DRIVERS]}), width="stretch")

    st.divider()
    st.subheader("Do the conclusions survive different assumptions?")
    rob = get_robustness()
    st.caption(f"Probability of a net profit under each variant, at plan, {an.N_TRIALS:,} trials each.")
    st.dataframe(rob.rename(columns={**{f"p_{y}": str(y) for y in PY}, "p_cumulative": "3-year total positive", "median_cumulative": "Median 3-year profit, RMB mn", "top_driver": f"Top driver of {PY[1]} profit"})
                 .style.format({**{str(y): pct_text for y in PY}, "3-year total positive": pct_text, "Median 3-year profit, RMB mn": "{:+,.0f}"}), width="stretch")
    st.markdown(f"<div class='note'>The {PY[0]} probability runs from {rob[f'p_{PY[0]}'].min():.0f}% to {rob[f'p_{PY[0]}'].max():.0f}% depending mainly on how far the plan is trusted. "
                f"The ranking of levers does not change: gross margin comes first in every variant where drivers can be ranked.</div>", unsafe_allow_html=True)

# ----------------------------------------------------------------------------- business case
with tab_case:
    st.subheader("Business case for a margin analytics programme")
    st.warning("The cost and gain inputs below are placeholders, not estimates. Replace them with figures you can source before quoting any result.", icon="⚠️")
    a, b = st.columns([1, 2], gap="large")
    with a:
        gain = st.slider("Gross margin gain once fully ramped, pt", 0.0, 2.0, 0.3, 0.05, help="What the programme adds to gross margin. Needs a benchmark or a pilot.")
        ramp = [st.slider(f"Share of that gain reached in {y}, %", 0, 100, v, 5) for y, v in zip(PY, [30, 70, 100])]
        build = st.number_input("One-off build cost, RMB mn", 0.0, 500.0, 20.0, 1.0)
        runc = st.number_input("Running cost per year, RMB mn", 0.0, 200.0, 8.0, 1.0)
        rate = st.slider("Discount rate, %", 0.0, 20.0, 8.0, 0.5)
        basis = st.radio("Revenue basis", ["Analyst plan", "Simulated median (current simulator settings)"], help="The gain applies to revenue; choose which revenue path to use.")
    with b:
        revp = model.plan.revenue.values if basis.startswith("Analyst") else res.revenue_median.values
        benefit = revp * gain / 100 * np.array(ramp) / 100
        net = benefit - runc
        disc = np.array([(1 + rate / 100) ** -(i + 1) for i in range(len(PY))])
        npv_case = float((net * disc).sum() - build)
        cumflow = np.cumsum(net) - build
        payback = next((PY[i] for i, v in enumerate(cumflow) if v >= 0), None)
        be_gain = (runc + build / len(PY)) / (revp.mean() / 100)
        m = st.columns(4)
        m[0].metric(f"NPV {PY[0]}-{str(PY[-1])[2:]}, RMB mn", f"{npv_case:+,.0f}")
        m[1].metric("Benefit per cost", f"{benefit.sum() / (build + runc * len(PY)):.1f}x" if build + runc > 0 else "n/a")
        m[2].metric("Pays back in", str(payback) if payback else f"after {PY[-1]}")
        m[3].metric("Break-even gain", f"{be_gain:.2f} pt", help="Average margin gain that covers running cost plus the build cost spread over the period.")
        cf = pd.DataFrame({"year": [f"{PY[0]} build"] + [str(y) for y in PY], "Benefit": [0.0] + benefit.tolist(), "Cost": [-build] + [-runc] * len(PY)}).melt("year", var_name="flow", value_name="rmb_mn")
        bars = alt.Chart(cf).mark_bar(size=30, stroke="#ffffff", strokeWidth=2).encode(x=alt.X("year:N", sort=None, title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("rmb_mn:Q", title="RMB mn"),
                                                                              color=alt.Color("flow:N", scale=alt.Scale(domain=["Benefit", "Cost"], range=[BLUE, RED]), legend=LEG),
                                                                              tooltip=[alt.Tooltip("year:N"), alt.Tooltip("flow:N"), alt.Tooltip("rmb_mn:Q", format="+,.1f", title="RMB mn")])
        show(bars + alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=INK).encode(y="y:Q"), 250)
        lifted = run_sim(belief, gm + gain * ramp[0] / 100, stores, rps, opex, fixed, rho, carry, an.N_TRIALS)[0]
        st.markdown(f"**Effect on the odds.** With the first-year gain of {gain * ramp[0] / 100:.2f} pt, the chance of a {PY[0]} profit moves from "
                    f"{pct_text(res.prob_profit_pct[PY[0]])} to {pct_text(lifted.prob_profit_pct[PY[0]])} under the current simulator settings.")
        st.markdown(f"<div class='note'><b>What is solid here:</b> each tenth of a point of gross margin is worth about RMB {revp[0] / 1000:,.1f} mn a year at {PY[0]} revenue. "
                    f"<b>What is not:</b> the size of the gain an analytics programme can deliver at Pagoda. That needs a published benchmark or a store pilot, and belongs in the report as a range.</div>", unsafe_allow_html=True)

# ----------------------------------------------------------------------------- data and method
with tab_data:
    st.subheader("How the app works")
    st.graphviz_chart("""
    digraph G { rankdir=LR; bgcolor="transparent"; node [shape=box, style="rounded,filled", fillcolor="#ffffff", color="#c3c8c0", fontname="Helvetica", fontsize=11, margin="0.18,0.1"]; edge [color="#7d857f", arrowsize=0.7];
      src1 [label="Statista export\\n(.xlsx, 6 sheets)"]; src2 [label="Company facts\\n(broker reports, CSV\\nwith page references)"]; src3 [label="Analyst plan\\n(CSV)"];
      load [label="Loader\\nsplits stacked tables,\\ntidy long format"]; check [label="Validation\\nidentities, rounding,\\noutlier scan"]; diag [label="Diagnostics\\nprice / volume,\\nsegments, share"];
      fcst [label="Forecast check\\nrolling-origin backtest,\\ncombination forecast"]; model [label="Profit model\\n6 drivers, calibrated\\nto the plan"]; sim [label="Monte Carlo\\n20,000 trials,\\nsensitivity"]; ui [label="This app\\ncharts, sliders,\\nbusiness case", fillcolor="#dfeee6", color="#1c6a49"];
      src1 -> load -> check -> diag -> ui; load -> fcst -> ui; src2 -> diag; src2 -> model; src3 -> model -> sim -> ui; }
    """)
    st.caption("`analytics.py` holds every calculation as plain functions with no interface code, so the same engine runs here, in the notebook and in the tests. "
               "Uploading a new Statista export in the sidebar re-runs the whole pipeline.")
    a, b = st.columns([3, 2])
    with a:
        st.subheader("Data-quality log")
        st.caption(f"{(dq.result == 'pass').sum()} checks passed, {(dq.result == 'FLAG').sum()} items flagged, on: {source_label}")
        st.dataframe(dq.rename(columns={"check": "Check", "result": "Result", "detail": "What was found", "action": "What was done"})
                     .style.map(lambda v: "background-color: #dfeee6; font-weight: 600" if v == "pass" else "background-color: #fde9d9; font-weight: 600" if v == "FLAG" else "", subset=["Result"]),
                     width="stretch", hide_index=True, height=460)
    with b:
        st.subheader("Workbook inventory")
        inv = an.inventory(mk)
        st.caption(f"{len(inv)} tables, {int(inv.series.sum())} series.")
        st.dataframe(inv, width="stretch", hide_index=True, height=460)
    st.subheader("Assumption register")
    reg = pd.read_csv(DATA / "assumption_register.csv").fillna("")
    st.caption("Every assumption the analysis depends on. Sourced: transcribed from a document. Derived: calculated from sourced values. Judgement: the author's choice. Placeholder: not an estimate. "
               + ", ".join(f"{k}: {v}" for k, v in reg.basis.value_counts().items()) + ".")
    st.dataframe(reg, width="stretch", hide_index=True, height=420)
    st.subheader("Company facts and where each one comes from")
    st.dataframe(facts.fillna(""), width="stretch", hide_index=True, height=300)
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Limits")
        st.markdown("""
- **The probabilities are conditional** on the ranges chosen, which are judgements anchored on two years of history.
- **Market data is modelled**, smooth by construction, and covers at-home retail only.
- **Company data is second-hand**, from four broker reports whose firms all have ties to Pagoda. Check it against Pagoda's annual reports before citing.
- **Stores are one pool.** City tier and store format are not modelled.
- **The Seven-Star alliance is not modelled.** It was 14% of first-half 2026 revenue at a lower margin.
- **The business-case tab uses placeholder costs.**""")
    with c2:
        st.subheader("Responsible use")
        st.markdown("""
- **Franchisees carry the risk.** Report franchisee profitability next to company profitability before using this to plan closures or wholesale pricing.
- **Margin analytics can become pressure** on growers or unfair pricing for shoppers. Set rules for acceptable use first.
- **Less spoilage is a public good** and should be measured, not only the margin.
- **No personal data is used.** Member-level analytics would fall under China's Personal Information Protection Law.""")
    st.subheader("Sources")
    st.markdown("""
- Statista Market Insights. 2026. *Fresh Fruits - China*. Accessed August 13, 2026. https://www.statista.com/outlook/cmo/food/fruits-nuts/fresh-fruits/china/?currency=USD
- Xu, Zhuonan, and Jierui Wang. 2025. *Pagoda Industrial (Group): 2024 Losses Totaled Rmb386mn Due to Weak Consumer Spending and Product Strategy Adjustment*. China International Capital Corporation, April 4, 2025.
- Liu, Guangyi, and Xiaoying Peng. 2026. *百果园集团 (2411.HK): 水果连锁龙头，扬帆再次起航*. China Galaxy Securities, April 10, 2026.
- Wong, Joseph. 2023. *Shenzhen Pagoda (2411 HK): Sowing the Franchiser's Seed*. CMB International Global Markets, March 3, 2023.
- Xu, Zhuonan, Jierui Wang, and Yi Ding. 2026. *Pagoda Industrial (Group): Main Business Recovering in 1H26; Cooperation under Seven-Star Convention Alliance Advancing*. China International Capital Corporation, September 7, 2026.
""")
