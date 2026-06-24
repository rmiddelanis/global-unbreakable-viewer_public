# Data availability — Unbreakable Explorer vs. `0_baseline` outputs

This note records which data the explorer needs, what is actually present in
`simulation_data/0_baseline`, and what is missing. The verification was done by reading the
baseline outputs and cross-checking against the model repository
(`/Users/robin/sync/git/UB-global-socioeconomic-resilience`).

The explorer (`index.html`) consumes only `data/explorer_data.json`, which is generated from the
baseline outputs by `build_data.py`. The build script **validates** itself by recomputing the
country-level risk/resilience from `iah.csv` + `macro.csv` and comparing against `results.csv`
(max relative error ≈ 1e-13 — i.e. an exact reproduction of the published pipeline).

## Coverage on the globe

- **132 countries** are simulated (`simulation_outputs/results.csv`). `THA` and `LUX` are
  explicitly excluded in `settings.yml` (`run_params.exclude_countries`); every other country in
  the world is simply not modelled.
- All **132 simulated countries are shown coloured** on the globe. Countries not covered by the
  simulation render **grey** and are non-interactive (tooltip: *"Not covered by the simulation"*).
- The prototype used the Natural Earth **110m** country set, which has **no polygon for 3 simulated
  countries** — Comoros (`COM`), Malta (`MLT`), Mauritius (`MUS`). The explorer therefore uses the
  vendored **50m** set (`data/ne_50m_admin_0_countries.json`), which covers all 132. Country
  matching is by `ISO_A3` with fallbacks `ADM0_A3` → `ISO_A3_EH` → `SOV_A3`.

## Present and wired up

| Variable (UI)             | Source field (`results.csv`) | Notes |
|---------------------------|------------------------------|-------|
| Risk to assets            | `risk_to_assets`             | fraction → shown ×100 as % GDP |
| Risk to consumption       | `risk_to_consumption`        | fraction → % GDP |
| Risk to well-being        | `risk_to_wellbeing`          | fraction → % GDP |
| Socio-economic resilience | `resilience`                 | = `risk_to_assets / risk_to_wellbeing`; ×100 as % |
| Context (income/region/pop/GDPpc/Gini) | `income_group`,`region`,`pop`,`gdp_pc_pp`,`gini_index` | region/income codes mapped to full labels |

**Per-quintile breakdown** (Q1 poorest … Q5 richest) is derived from `simulation_outputs/iah.csv`
by replicating the model's own aggregation (`agg_to_event_level` → `average_over_rp` with FLOPROS
protection from `scenario__hazard_protection.csv` → sum over hazards →
`calc_risk_and_resilience_from_k_w`). The surfaced quintile metrics — **income share**, **risk to
well-being**, **risk to assets** — each decompose *exactly* to the national total (the five bars
sum to the country value).

**Data-quality flags** come from `model_inputs/data_coverage.csv` (count of `imputed` vs.
`available` inputs per country), shown in the country panel footer.

**Available in `0_baseline` but not currently surfaced** (candidates for future panels): the full
hazard × return-period detail in `simulation_outputs/macro.csv` (`dk_ctry`, `fa`, `need`, `aid`),
the household-level `iah.csv` fields beyond what the quintile aggregation uses, the model inputs
(`scenario__*.csv`), and `tables/transfers_regression_lassoCV.tex`.

## Missing / flagged

- **Recovery duration (years).** Not a column in baseline `results.csv`. It is derivable from the
  per-household recovery rate `lambda_h` in `iah.csv` (the model computes `t_reco_95 =
  ln(1/0.05)/lambda_h` and a population/probability-weighted `t_reco_avg`, cf. `fig_4a`), but per
  the project owner this column will be **added to the country-level model output later**. The
  variable is therefore **omitted** from the explorer for now (not faked).

- **Policy simulations at the country level.** `0_baseline` contains **no policy scenarios** — all
  `policy_params` are neutral (= 1) in `settings.yml`, i.e. this is the no-policy baseline. The
  prototype's interactive policy sliders recomputed results with fabricated formulas; they have been
  **removed** and replaced with an explicit *"Policy scenarios unavailable"* notice in the country
  panel. Pre-defined fixed-policy results do exist in the model repository
  (`results/figures/fig_5.csv`: 8 policies such as *"reduce total exposure by 5%"*), but (a) they
  are not in this output directory and (b) they have no adjustable coverage, so they cannot back the
  prototype's slider UX. Enabling the panel requires running the model with the desired
  `policy_params` and loading those outputs alongside the baseline.

## Regenerating the data

```bash
# any environment with pandas + numpy, e.g. the model's conda env:
/Users/robin/miniconda3/envs/disaster_resilience/bin/python build_data.py
# serve (file:// blocks the fetches):
python3 -m http.server
# open http://localhost:8000/index.html
```
