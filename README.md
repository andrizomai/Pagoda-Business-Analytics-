# Pagoda turnaround analytics

MSBA capstone, analytics workbook and proof of concept. Subject: Pagoda (百果园, 2411.HK), China's largest fruit retail chain.

**Business question.** China's fresh-fruit retail market keeps growing in Statista's data, yet Pagoda's revenue fell 9.8% in 2024 and 20.4% in 2025 and the company moved from profit to loss. Is the problem the market or the company, and which operating lever matters most for getting back to profit?

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/andrizomai/Pagoda-Business-Analytics-/blob/main/pagoda_capstone_analytics.ipynb)

## What is here

| Path | What it is |
|---|---|
| `pagoda_capstone_analytics.ipynb` | The analysis, end to end: data understanding, preparation and validation, exploratory analysis, forecast backtest, Monte Carlo turnaround simulator, value figures. Saved with outputs, so it can be read without running. |
| `streamlit_app/` | The proof of concept as an interactive app. `analytics.py` is the calculation engine; `app.py` is the interface. |
| `streamlit_app/data/` | Company figures with a source and page for each value, the analyst forecast used to calibrate the model, past analyst forecasts used to size the uncertainty, and the assumption register (every assumption with its basis and source). |
| `figures/` | The six charts produced by the notebook. |

## Running the notebook

Click the Colab badge, then *Runtime > Run all*. The first code cell asks you to upload the Statista export.

**The market data is not in this repository.** It is a licensed Statista Market Insights export (*Fresh Fruits - China*, https://www.statista.com/outlook/cmo/food/fruits-nuts/fresh-fruits/china/?currency=USD, downloaded as XLSX). With Statista access, download it and upload it when asked. Without it, the saved outputs in the notebook show the author's run.

## Running the app

```bash
pip install -r requirements.txt
cd streamlit_app
streamlit run app.py
```

Upload the same Statista export in the sidebar.

## Headline results

- The market grew 9.8% a year from 2018 to 2025; about 70% of that was volume.
- Pagoda's revenue as a share of the market roughly halved between 2019 and 2025.
- Statista's forecast is consistent with an independent, back-tested forecast (USD 176bn against 175bn in 2031).
- Analyst forecasts for Pagoda have missed low every time: revenue by 11% to 28% and gross margin by 0.5 to 5.5 points across four forecasts.
- Breakeven gross margin for 2026 is 10.0% against 10.2% in the analyst plan. The chance of a 2026 profit is about 56% if the plan is unbiased and about 14% if it is the best case.
- Gross margin carries 80% to 92% of the variation in 2027 profit. One point of margin is worth about as much profit as 1,040 additional stores.
- The margin lever is pricing and grade mix first, then procurement; demand forecasting is the enabler, since store spoilage falls mainly on franchisees.
- First-half 2026 results (reported September 2026) are the first out-of-sample test: gross margin reached 12.2%, at the 98th percentile of the neutral range and above the whole best-case range, attributed to product-mix optimisation. 14% of revenue came from the new Seven-Star alliance, which the model does not yet include.

These probabilities depend on uncertainty ranges that are judgements anchored on 2024-25 history. The ranking of levers is the robust result.

## Sources

- Statista Market Insights. 2026. *Fresh Fruits - China*. Accessed August 13, 2026.
- Xu, Zhuonan, and Jierui Wang. 2025. *Pagoda Industrial (Group): 2024 Losses Totaled Rmb386mn Due to Weak Consumer Spending and Product Strategy Adjustment*. China International Capital Corporation, April 4, 2025.
- Liu, Guangyi, and Xiaoying Peng. 2026. *百果园集团 (2411.HK): 水果连锁龙头，扬帆再次起航*. China Galaxy Securities, April 10, 2026.
- Wong, Joseph. 2023. *Shenzhen Pagoda (2411 HK): Sowing the Franchiser's Seed*. CMB International Global Markets, March 3, 2023.
- Xu, Zhuonan, Jierui Wang, and Yi Ding. 2026. *Pagoda Industrial (Group): Main Business Recovering in 1H26; Cooperation under Seven-Star Convention Alliance Advancing*. China International Capital Corporation, September 7, 2026.

Company figures are transcribed from the four broker reports, whose firms all have ties to Pagoda, and should be checked against Pagoda's annual reports on HKEXnews.
