# Pagoda turnaround analytics

MSBA capstone, analytics workbook and proof of concept. Subject: Pagoda (百果园, 2411.HK), China's largest fruit retail chain.

**Business question.** China's fresh-fruit retail market keeps growing in Statista's data, yet Pagoda's revenue fell 9.8% in 2024 and 20.4% in 2025 and the company moved from profit to loss. Is the problem the market or the company, and which operating lever matters most for getting back to profit?

**Live app:** https://uachi5phdhmmtiftbuvaii.streamlit.app/

The notebook, the app and the written report use the same data files and the same calculations: the app's engine (`analytics.py`) reproduces 106 of the notebook's published values exactly, and every chart in the report is a file in `figures/` produced by the notebook.

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://uachi5phdhmmtiftbuvaii.streamlit.app/) [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/andrizomai/Pagoda-Business-Analytics-/blob/main/pagoda_capstone_analytics_(MSBA).ipynb)

## What is here

| Path | What it is |
|---|---|
| `pagoda_capstone_analytics_(MSBA).ipynb` | The analysis, end to end: data understanding, preparation and validation, exploratory analysis, forecast backtest, Monte Carlo turnaround simulator, first-half 2026 check, business case and assumption register. Saved with outputs, so it can be read without running. |
| `app.py`, `analytics.py` | The proof of concept as an interactive Streamlit app. `analytics.py` is the calculation engine; `app.py` is the interface. |
| `data/pagoda_facts.csv` | Company figures with a source and page for each value. |
| `data/analyst_plan.csv` | The analyst forecast used to calibrate the model. |
| `data/analyst_forecasts.csv` | Past analyst forecasts, used to size the uncertainty. |
| `data/assumption_register.csv` | Every assumption with its basis and source. |
| `data/pilot_cost.csv` | Line-by-line cost of the proposed 6-month pilot, with the basis for each line. |
| `figures/` | Every chart in the report (`fig0` to `fig8`), produced by the notebook. |
| `requirements.txt` | Python packages for the app and notebook. |

## Running the notebook

Click the Colab badge, then *Runtime > Run all*. The first code cell asks you to upload the Statista export.

**The market data is not in this repository.** It is a licensed Statista Market Insights export (*Fresh Fruits - China*, https://www.statista.com/outlook/cmo/food/fruits-nuts/fresh-fruits/china/?currency=USD, downloaded as XLSX). With Statista access, download it and upload it when asked. Without it, the saved outputs in the notebook show the author's run.

## Running the app

```bash
pip install -r requirements.txt
streamlit run app.py
```

Or open the live app above. If the Statista file is not stored privately for the app (see below), upload the same export in the sidebar.

**Storing the workbook for the live app.** Add `STATISTA_URL = "<private Google Drive link>"` under the app's Settings > Secrets on Streamlit Cloud. The link stays out of this public repository.

## Headline results

- The market grew 9.8% a year from 2018 to 2025; about 70% of that was volume.
- Pagoda's revenue as a share of the market roughly halved between 2019 and 2025.
- Statista's forecast is consistent with an independent, back-tested forecast (USD 176bn against 175bn in 2031).
- Analyst forecasts for Pagoda have missed low every time: revenue by 11% to 28% and gross margin by 0.5 to 5.5 points across four forecasts.
- Breakeven gross margin for 2026 is 10.0% against 10.2% in the analyst plan. The chance of a 2026 profit is about 56% if the plan is unbiased and about 14% if it is the best case.
- Gross margin carries 92% of the variation in 2027 profit (80% if the plan is the best case) and is the top driver in every robustness test. One point of margin is worth about RMB 98 mn of 2027 profit, as much as about 1,040 additional stores.
- Recommendation: one margin engine covering pricing and grade mix, procurement and product mix, and store ordering and markdowns. Store spoilage falls mainly on franchisees, so demand forecasting is the enabler.
- The ask: a 6-month pilot in about 100 stores across two regions, about RMB 2.0 mn, gated at +0.1 pt of margin with a +0.3 pt target. Rolled out network-wide it pays back at about 0.02 pt; +0.3 pt is worth about RMB 26 mn a year.
- First-half 2026 results (reported September 2026) are the first out-of-sample test: gross margin reached 12.2%, at the 98th percentile of the neutral range and above the whole best-case range, attributed to product-mix optimisation. 14% of revenue came from the new Seven-Star alliance, which the model does not yet include.

These probabilities depend on uncertainty ranges that are judgements anchored on 2024-25 history. The ranking of levers is the robust result.

## Sources

- Statista Market Insights. 2026. *Fresh Fruits - China*. Accessed August 13, 2026.
- Xu, Zhuonan, and Jierui Wang. 2025. *Pagoda Industrial (Group): 2024 Losses Totaled Rmb386mn Due to Weak Consumer Spending and Product Strategy Adjustment*. China International Capital Corporation, April 4, 2025.
- Liu, Guangyi, and Xiaoying Peng. 2026. *百果园集团 (2411.HK): 水果连锁龙头，扬帆再次起航*. China Galaxy Securities, April 10, 2026.
- Wong, Joseph. 2023. *Shenzhen Pagoda (2411 HK): Sowing the Franchiser's Seed*. CMB International Global Markets, March 3, 2023.
- Xu, Zhuonan, Jierui Wang, and Yi Ding. 2026. *Pagoda Industrial (Group): Main Business Recovering in 1H26; Cooperation under Seven-Star Convention Alliance Advancing*. China International Capital Corporation, September 7, 2026.
- Pagoda (Shenzhen Pagoda Industrial (Group) Corporation Limited). 2026b. *Interim Report 2026*. Hong Kong Exchanges and Clearing, September 25, 2026.
- Levels.fyi. 2026; Payscale. 2025. Salary benchmarks for the pilot cost. Accessed October 12, 2026.

Company figures are transcribed from the four broker reports, whose firms all have ties to Pagoda, and should be checked against Pagoda's annual reports on HKEXnews.
