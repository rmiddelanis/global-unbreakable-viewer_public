#!/usr/bin/env python3
"""
build_data.py — preprocess baseline Unbreakable simulation outputs into a compact
JSON that the static `index.html` explorer can fetch.

Reads from   ./simulation_data/0_baseline/
Writes       ./data/explorer_data.json

Country-level headline numbers are taken verbatim from `simulation_outputs/results.csv`.
Per-quintile values are derived from `simulation_outputs/iah.csv` by replicating the
model's own aggregation pipeline:

    agg_to_event_level (population-share `n` weighting)
        -> average_over_rp (return-period probability weighting + FLOPROS protection)
        -> sum over hazards
        -> calc_risk_and_resilience_from_k_w

`average_over_rp` is copied verbatim from the model repo
(`unbreakable/misc/helpers.py`) so the annualisation matches the published results.
A validation step recomputes the country-level risk/resilience from `iah`+`macro`
and checks it against `results.csv`, which proves the quintile derivation is faithful.

Recovery duration is intentionally NOT emitted: it is not a column in the baseline
`results.csv`. Policy scenarios are likewise absent from 0_baseline (see DATA_AVAILABILITY.md).

Run with an environment that has pandas + numpy, e.g. the model's conda env:
    /Users/robin/miniconda3/envs/disaster_resilience/bin/python build_data.py
"""

import json
import os
from itertools import product

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(ROOT, "simulation_data", "0_baseline")
OUT_DIR = os.path.join(ROOT, "data")
OUT_FILE = os.path.join(OUT_DIR, "explorer_data.json")

ZERO_RP = 2  # natural protection level (settings.yml -> hazard_params.zero_rp)

EVENT_LEVEL = ["iso3", "hazard", "rp"]

INCOME_LABELS = {
    "LICs": "Low income",
    "LMICs": "Lower-middle income",
    "UMICs": "Upper-middle income",
    "HICs": "High income",
}
INCOME_ORDER = ["LICs", "LMICs", "UMICs", "HICs"]
REGION_LABELS = {
    "EAP": "East Asia & Pacific",
    "ECA": "Europe & Central Asia",
    "LAC": "Latin America & Caribbean",
    "MNA": "Middle East & North Africa",
    "NMA": "North America",
    "SAR": "South Asia",
    "SSA": "Sub-Saharan Africa",
}


# --------------------------------------------------------------------------------------
# average_over_rp — copied verbatim from unbreakable/misc/helpers.py (model repo) so the
# return-period annualisation exactly matches the published results.
# --------------------------------------------------------------------------------------
def average_over_rp(d_in, protection_=None, zero_rp=2):
    """Aggregate outputs over return periods, weighted by probabilities."""
    if isinstance(d_in, pd.Series):
        df_in = d_in.to_frame()
    else:
        df_in = d_in.copy()

    if 'rp' not in df_in.index.names:
        raise ValueError("Need index level 'rp' to average over return periods.")

    if zero_rp is not None:
        if zero_rp <= 0:
            raise ValueError("zero_rp should be > 0")
        elif zero_rp not in df_in.index.get_level_values('rp'):
            new_index = df_in.index.droplevel("rp").unique()
            new_index = pd.MultiIndex.from_arrays(
                [new_index.get_level_values(l) for l in range(new_index.nlevels)] + [[zero_rp] * len(new_index)],
                names=list(new_index.names) + ['rp']
            )
            new_rows = pd.DataFrame(0, index=new_index, columns=df_in.columns).reorder_levels(df_in.index.names)
            df_in = pd.concat([df_in, new_rows]).sort_index().copy()
        else:
            print(f"Warning: zero_rp={zero_rp} was provided for return period averaging, but return period is "
                  f"already in df_in. Ignoring zero_rp.")

    group_levels = [idxn for idxn in df_in.index.names if idxn != 'rp']

    if protection_ is not None:
        if isinstance(protection_, pd.DataFrame):
            protection = protection_.protection.copy().round(3)
        else:
            protection = protection_.copy().round(3)
        protection = protection[protection > zero_rp]

        common_index = protection.index.intersection(df_in.droplevel(list(np.setdiff1d(df_in.index.names, protection.index.names))).index.unique())
        protection = protection.loc[common_index]

        protected_index = protection.rename('rp').to_frame().set_index('rp', append=True).index
        missing_levels = list(set(df_in.index.names) - set(protected_index.names))
        for missing_level in missing_levels:
            protected_index = pd.MultiIndex.from_tuples(
                [(*t, m) for t, m in product(list(protected_index.to_flat_index()), list(df_in.index.get_level_values(missing_level).unique()))],
                names=list(protected_index.names) + [missing_level]
            )
        protected_index.reorder_levels(df_in.index.names)
        protected_levels = pd.DataFrame(np.nan, index=protected_index.difference(df_in.index), columns=df_in.columns)

        df_in = pd.concat([df_in, protected_levels]).sort_index()
        if group_levels:
            idx_order = df_in.index.names
            df_in = df_in.reset_index('rp').groupby(group_levels).apply(
                lambda g: g.reset_index().drop(columns=group_levels).set_index('rp').interpolate(method='index')
            ).reorder_levels(idx_order).sort_index()
        else:
            df_in = df_in.sort_index().interpolate(method='index')

        df_in = df_in[((df_in.reset_index('rp').rp - protection).fillna(0) >= 0).values]

    def calculate_rp_average(g):
        g_ = g.sort_index().copy()
        g_.loc[np.inf] = g_.iloc[-1]
        rp_weights = pd.Series(1 / g_.index, index=g_.index).diff(-1).loc[g.sort_index().index]
        return pd.DataFrame((g_.values[:-1] + g_.values[1:]) / 2, index=g.sort_index().index, columns=g_.columns).mul(rp_weights, axis=0).sum()

    res = df_in.groupby(group_levels, group_keys=False).apply(lambda g: calculate_rp_average(g.droplevel(group_levels)))
    res.loc[d_in.droplevel('rp').index.unique().difference(res.index)] = 0

    if isinstance(d_in, pd.Series):
        res.name = d_in.name
        res = res.squeeze()
    return res


# --------------------------------------------------------------------------------------
def load_inputs():
    results = pd.read_csv(os.path.join(BASE, "simulation_outputs", "results.csv"))
    iah = pd.read_csv(os.path.join(BASE, "simulation_outputs", "iah.csv"))
    macro = pd.read_csv(os.path.join(BASE, "simulation_outputs", "macro.csv"))
    haz_prot = pd.read_csv(os.path.join(BASE, "model_inputs", "scenario__hazard_protection.csv"))
    coverage = pd.read_csv(os.path.join(BASE, "model_inputs", "data_coverage.csv"))
    return results, iah, macro, haz_prot, coverage


def protection_frame(haz_prot):
    return haz_prot.set_index(["iso3", "hazard"])[["protection"]]


def annualise(event_df, protection):
    """average_over_rp then sum over hazard -> one row per remaining group key."""
    avg = average_over_rp(event_df, protection, zero_rp=ZERO_RP)
    keep = [n for n in avg.index.names if n != "hazard"]
    return avg.groupby(level=keep).sum()


def calc_risk(df, gdp_pc, eta):
    """Replicates calc_risk_and_resilience_from_k_w for the columns we surface."""
    w_prime = gdp_pc ** (-eta)
    out = pd.DataFrame(index=df.index)
    out["risk_to_wellbeing"] = (df["dw"] / w_prime) / gdp_pc
    out["risk_to_consumption"] = df["dc"] / gdp_pc
    out["resilience"] = (w_prime * df["dk"]) / df["dw"]
    out["risk_to_assets"] = out["resilience"] * out["risk_to_wellbeing"]
    return out


def country_meta(results):
    """gdp_pc_pp and income_elasticity_eta per country, indexed by iso3."""
    m = results.set_index("iso3")
    return m["gdp_pc_pp"], m["income_elasticity_eta"]


def validate_country_level(results, iah, macro, protection):
    """Recompute country risk/resilience from iah+macro; compare with results.csv."""
    gdp_pc, eta = country_meta(results)

    iah_idx = iah.set_index(EVENT_LEVEL)
    dw = (iah_idx["dw"] * iah_idx["n"]).groupby(level=EVENT_LEVEL).sum()
    dc = (iah_idx["dc"] * iah_idx["n"]).groupby(level=EVENT_LEVEL).sum()
    dk = macro.set_index(EVENT_LEVEL)["dk_ctry"]

    out = pd.concat({"dk": dk, "dw": dw, "dc": dc}, axis=1)
    out = annualise(out, protection)

    risk = calc_risk(out, gdp_pc.reindex(out.index), eta.reindex(out.index))
    ref = results.set_index("iso3")

    diffs = {}
    for col in ["risk_to_assets", "risk_to_wellbeing", "resilience"]:
        a = risk[col].reindex(ref.index)
        b = ref[col]
        rel = ((a - b).abs() / b.abs().clip(lower=1e-12))
        diffs[col] = float(rel.max())
    return diffs


def build_quintiles(iah, results, protection):
    """Per-quintile annualised risk/resilience + income share, indexed (iso3, income_cat)."""
    gdp_pc, eta = country_meta(results)

    level_q = ["iso3", "hazard", "rp", "income_cat"]
    iah_idx = iah.set_index(level_q)
    weighted = iah_idx[["dk", "dw", "dc"]].mul(iah_idx["n"], axis=0)
    event_q = weighted.groupby(level=level_q).sum()

    annual = annualise(event_q, protection)  # -> (iso3, income_cat)

    iso = annual.index.get_level_values("iso3")
    gdp = gdp_pc.reindex(iso).to_numpy()
    et = eta.reindex(iso).to_numpy()
    gdp = pd.Series(gdp, index=annual.index)
    et = pd.Series(et, index=annual.index)

    risk_q = calc_risk(annual, gdp, et)

    # income share is constant per (iso3, income_cat)
    share = iah.groupby(["iso3", "income_cat"])["income_share"].first()
    risk_q["income_share"] = share.reindex(risk_q.index)
    return risk_q


def coverage_counts(coverage):
    cols = [c for c in coverage.columns if c not in ("iso3", "name", "region", "income_group")]
    sub = coverage.set_index("iso3")[cols]
    n_imputed = (sub == "imputed").sum(axis=1)
    n_avail = (sub == "available").sum(axis=1)
    n_total = n_imputed + n_avail
    return n_imputed, n_total


def main():
    results, iah, macro, haz_prot, coverage = load_inputs()
    protection = protection_frame(haz_prot)

    print(f"Loaded {len(results)} countries from results.csv")

    diffs = validate_country_level(results, iah, macro, protection)
    print("Validation (max relative error vs results.csv):")
    for k, v in diffs.items():
        flag = "OK" if v < 0.01 else "WARN"
        print(f"  {k:20s} {v:.3e}  [{flag}]")

    quint = build_quintiles(iah, results, protection)
    n_imputed, n_total = coverage_counts(coverage)

    INCOME_CAT_TO_Q = {0.2: 1, 0.4: 2, 0.6: 3, 0.8: 4, 1.0: 5}

    countries = []
    for _, row in results.iterrows():
        iso = row["iso3"]
        qrows = []
        if iso in quint.index.get_level_values("iso3"):
            sub = quint.xs(iso, level="iso3")
            for income_cat, q in sorted(INCOME_CAT_TO_Q.items()):
                if income_cat in sub.index:
                    r = sub.loc[income_cat]
                    # Per-quintile risk decomposes exactly to the national totals
                    # (sum over quintiles == country value). Per-quintile "resilience"
                    # (riskAssets_q/riskWB_q) is omitted: it mixes a quintile's share of
                    # national asset vs well-being risk and is misleading next to the
                    # national aggregate.
                    qrows.append({
                        "q": q,
                        "incomeShare": float(r["income_share"]) * 100.0,
                        "riskWellbeing": float(r["risk_to_wellbeing"]) * 100.0,
                        "riskAssets": float(r["risk_to_assets"]) * 100.0,
                    })
        countries.append({
            "iso": iso,
            "name": row["name"],
            "region": row["region"],
            "regionLabel": REGION_LABELS.get(row["region"], row["region"]),
            "incomeGroup": row["income_group"],
            "incomeLabel": INCOME_LABELS.get(row["income_group"], row["income_group"]),
            "pop": None if pd.isna(row["pop"]) else float(row["pop"]),
            "gdppc": None if pd.isna(row["gdp_pc_pp"]) else float(row["gdp_pc_pp"]),
            "gnipc": None if pd.isna(row["gni_pc_pp"]) else float(row["gni_pc_pp"]),
            "gini": None if pd.isna(row["gini_index"]) else float(row["gini_index"]),
            # headline values taken verbatim from results.csv (risk fractions -> % GDP; resilience -> %)
            "riskAssets": float(row["risk_to_assets"]) * 100.0,
            "riskConsumption": float(row["risk_to_consumption"]) * 100.0,
            "riskWellbeing": float(row["risk_to_wellbeing"]) * 100.0,
            "resilience": float(row["resilience"]) * 100.0,
            "imputedInputs": int(n_imputed.get(iso, 0)),
            "totalInputs": int(n_total.get(iso, 0)),
            "quint": qrows,
        })

    payload = {
        "generatedFrom": "simulation_data/0_baseline",
        "framework": "Global Unbreakable model",
        "incomeOrder": INCOME_ORDER,
        "incomeLabels": INCOME_LABELS,
        "regionLabels": REGION_LABELS,
        "countries": countries,
        "meta": {
            "nCountries": len(countries),
            "hazards": sorted(macro["hazard"].unique().tolist()),
            "returnPeriods": sorted(macro["rp"].unique().tolist()),
            "notes": {
                "recovery": "Recovery duration is not a column in baseline results.csv; omitted.",
                "policies": "0_baseline contains no policy scenarios; policy panel is disabled.",
            },
        },
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_FILE, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    n_q = sum(1 for c in countries if c["quint"])
    print(f"Wrote {OUT_FILE}: {len(countries)} countries ({n_q} with quintile breakdown), "
          f"{os.path.getsize(OUT_FILE)/1024:.0f} KiB")


if __name__ == "__main__":
    main()
