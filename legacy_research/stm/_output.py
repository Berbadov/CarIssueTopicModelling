"""
stm/_output.py
──────────────
Shared output writer for all three corpora.
Produces the 8 files consumed by generate_issue_knowledge*.py.

Column names are chosen to exactly match the R script outputs so that
the downstream LLM labeller scripts run unchanged.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .core import STM
from .effects import EffectEstimator
from .frex import label_topics


# ── Excel-safe string sanitiser ───────────────────────────────────────────────

import re as _re
_ILLEGAL_CHARS = _re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffe\uffff]"
)

def _sanitize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Replace Excel-illegal characters in all string columns."""
    df = df.copy()
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].apply(
            lambda v: _ILLEGAL_CHARS.sub("", str(v)) if isinstance(v, str) else v
        )
    return df


# ── Turkish outputs (no suffix) ───────────────────────────────────────────────

def write_outputs_turkish(
    stm: STM,
    df: pd.DataFrame,
    vocab: list[str],
    out_dir: Path,
    k_metrics: pd.DataFrame | None = None,
    k_summary: pd.DataFrame | None = None,
) -> None:
    """
    Write all Turkish STM outputs to data/processed/.
    Matches the file schema from R_code_STM.R sections 13–16.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    K = stm.K
    theta = stm.theta       # (D × K)
    beta = stm.beta         # (K × W)
    D = theta.shape[0]

    # ── Top terms ─────────────────────────────────────────────────────────────
    labels = label_topics(beta, vocab, n=15)
    top_terms_df = pd.DataFrame({
        "topic": range(1, K + 1),
        "terms_prob": [", ".join(row) for row in labels["prob"]],
        "terms_frex": [", ".join(row) for row in labels["frex"]],
    })
    top_terms_df["terms"] = top_terms_df["terms_frex"]

    # ── Gamma (long form, column names match R tidy(stmTopics)) ──────────────
    doc_names = df["doc_name"].tolist()
    gamma_rows = []
    for d, dname in enumerate(doc_names):
        for k in range(K):
            gamma_rows.append({"document": dname, "topic": k + 1, "gamma": float(theta[d, k])})
    gamma_full = pd.DataFrame(gamma_rows)

    # ── Dominant topic ────────────────────────────────────────────────────────
    dom_idx = theta.argmax(axis=1)  # 0-indexed
    dominant = pd.DataFrame({
        "doc_name": doc_names,
        "dominant_topic": dom_idx + 1,
        "topic_gamma": theta[np.arange(D), dom_idx],
    })

    # ── Gamma vectors (string "[0.xxx, ...]") ─────────────────────────────────
    gamma_vec = pd.DataFrame({
        "doc_name": doc_names,
        "gamma_vector": [
            "[" + ", ".join(f"{v:.6f}" for v in theta[d]) + "]"
            for d in range(D)
        ],
    })

    # ── Thread enriched ───────────────────────────────────────────────────────
    df_out = df.copy()
    df_out = df_out.merge(dominant, on="doc_name", how="left")

    # Derive year, displacement, fuel_type, mileage_bucket
    year_re = r"\b(200[0-9]|201[0-9]|202[0-4])\b"
    df_out["year"] = df_out.apply(
        lambda r: _extract_first(str(r["thread_name"]) + " " + str(r.get("txt", "")), year_re),
        axis=1,
    )
    df_out["displacement"] = df_out["engine_group"].str.extract(r"^([0-9]\.[0-9])")
    df_out["fuel_type"] = df_out["engine_group"].apply(_fuel_type_turkish)
    mileage_col = "mileage_mentioned" if "mileage_mentioned" in df_out.columns else "mileage_km"
    df_out["mileage_bucket"] = df_out[mileage_col].apply(_mileage_bucket_km)

    stm_thread_enriched = df_out.merge(gamma_vec, on="doc_name", how="left")[[
        "doc_name", "thread_name", "thread_url",
        "dominant_topic", "topic_gamma",
        "displacement", "fuel_type", "year",
        "mileage_km" if "mileage_km" in df_out.columns else "mileage_mentioned",
        "mileage_bucket", "engine_group", "technical_bucket",
        "chronic_score", "n_messages", "gamma_vector",
    ]]
    # Normalise mileage column name to mileage_km for enriched output
    if "mileage_mentioned" in stm_thread_enriched.columns:
        stm_thread_enriched = stm_thread_enriched.rename(
            columns={"mileage_mentioned": "mileage_km"}
        )

    # ── Engine effects ────────────────────────────────────────────────────────
    est = EffectEstimator(stm, df)
    effects_df = est.estimate("engine_group")
    effects_df["significant"] = (effects_df["ci_lower"] > 0) | (effects_df["ci_upper"] < 0)

    # ── Thread topic vectors ──────────────────────────────────────────────────
    thread_topic_vectors = df[["doc_name", "thread_name", "engine_group",
                               "mileage_mentioned" if "mileage_mentioned" in df.columns else "mileage_km",
                               "mileage_confidence"]].copy()
    thread_topic_vectors = thread_topic_vectors.merge(
        dominant[["doc_name", "dominant_topic"]], on="doc_name", how="left"
    ).merge(gamma_vec, on="doc_name", how="left")

    # ── LLM issue input ───────────────────────────────────────────────────────
    llm_input = _build_llm_input_turkish(
        top_terms_df, gamma_full, df, doc_names, K
    )

    # ── Write K metrics ───────────────────────────────────────────────────────
    if k_metrics is not None:
        k_metrics.to_csv(out_dir / "stm_k_metrics.csv", index=False)
    if k_summary is not None:
        k_summary.to_csv(out_dir / "stm_k_summary.csv", index=False)

    # ── Write CSVs ────────────────────────────────────────────────────────────
    top_terms_df[["topic", "terms_frex"]].to_csv(
        out_dir / "stm_top_terms_frex.csv", index=False
    )
    df_out.to_csv(out_dir / "stm_thread_topics.csv", index=False)
    thread_topic_vectors.to_csv(out_dir / "stm_thread_topic_vectors.csv", index=False)
    stm_thread_enriched.to_csv(out_dir / "stm_thread_enriched.csv", index=False)
    effects_df.to_csv(out_dir / "stm_topic_engine_effects.csv", index=False)
    llm_input.to_csv(out_dir / "llm_issue_input.csv", index=False)

    # ── Write xlsx (5 sheets matching R) ─────────────────────────────────────
    xlsx_path = out_dir / "stm_results.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as w:
        _sanitize_df(top_terms_df).to_excel(w, sheet_name="top_terms", index=False)
        _sanitize_df(gamma_full).to_excel(w, sheet_name="gamma_full", index=False)
        _sanitize_df(effects_df).to_excel(w, sheet_name="engine_effects", index=False)
        _sanitize_df(df_out).to_excel(w, sheet_name="thread_topics", index=False)
        _sanitize_df(thread_topic_vectors).to_excel(w, sheet_name="thread_topic_vectors", index=False)

    print(f"Turkish outputs written to {out_dir}")
    _print_files(out_dir, [
        "stm_results.xlsx", "stm_top_terms_frex.csv", "stm_thread_topics.csv",
        "stm_thread_topic_vectors.csv", "stm_thread_enriched.csv",
        "stm_topic_engine_effects.csv", "llm_issue_input.csv",
    ])


# ── UK outputs (_uk suffix) ───────────────────────────────────────────────────

def write_outputs_uk(
    stm: STM,
    df: pd.DataFrame,
    vocab: list[str],
    out_dir: Path,
    k_metrics: pd.DataFrame | None = None,
) -> None:
    """
    Write all UK STM outputs. Matches R_code_STM_uk.R section 13.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    K = stm.K
    theta = stm.theta  # (D × K)
    beta = stm.beta    # (K × W)
    D = theta.shape[0]
    doc_names = df["doc_name"].tolist()

    # ── Top terms ─────────────────────────────────────────────────────────────
    labels = label_topics(beta, vocab, n=15)
    top_terms_df = pd.DataFrame({
        "topic": range(1, K + 1),
        "terms_prob": [", ".join(row) for row in labels["prob"]],
        "terms_frex": [", ".join(row) for row in labels["frex"]],
    })

    # ── Gamma long form (doc_name, topic, gamma) ──────────────────────────────
    gamma_rows = []
    for d, dname in enumerate(doc_names):
        for k in range(K):
            gamma_rows.append({"doc_name": dname, "topic": k + 1, "gamma": float(theta[d, k])})
    gamma_long = pd.DataFrame(gamma_rows)

    # ── Dominant topic ────────────────────────────────────────────────────────
    dom_idx = theta.argmax(axis=1)
    thread_topics = pd.DataFrame({
        "doc_name": doc_names,
        "dominant_topic": dom_idx + 1,
        "gamma_dominant": theta[np.arange(D), dom_idx],
    })

    # ── Engine effects ────────────────────────────────────────────────────────
    est = EffectEstimator(stm, df)
    effects_df = est.estimate("engine_group")
    effects_df["significant"] = (effects_df["ci_lower"] > 0) | (effects_df["ci_upper"] < 0)

    # ── Thread enriched ───────────────────────────────────────────────────────
    thread_enriched = df.merge(thread_topics, on="doc_name", how="left")
    thread_enriched = thread_enriched.rename(
        columns={"mileage_mentioned": "mileage_miles"}
    ) if "mileage_mentioned" in thread_enriched.columns else thread_enriched

    # ── LLM input ─────────────────────────────────────────────────────────────
    prevalence_df = (
        gamma_long.groupby("topic")["gamma"].mean().reset_index()
        .rename(columns={"gamma": "prevalence_pct"})
    )
    prevalence_df["prevalence_pct"] = prevalence_df["prevalence_pct"] * 100

    chronic_by_topic = thread_enriched.merge(
        thread_topics[["doc_name", "dominant_topic"]], on="doc_name", how="left"
    ).groupby("dominant_topic")["chronic_score"].mean().reset_index()
    chronic_by_topic.columns = ["topic", "chronic_signal"]

    llm_input = (
        top_terms_df
        .merge(prevalence_df, on="topic", how="left")
        .merge(chronic_by_topic, on="topic", how="left")
    )

    # ── K metrics ─────────────────────────────────────────────────────────────
    if k_metrics is not None:
        k_metrics.to_csv(out_dir / "stm_k_metrics_uk.csv", index=False)

    # ── Write CSVs ────────────────────────────────────────────────────────────
    thread_enriched.to_csv(out_dir / "stm_thread_enriched_uk.csv", index=False)
    effects_df.to_csv(out_dir / "stm_topic_engine_effects_uk.csv", index=False)
    llm_input.to_csv(out_dir / "llm_issue_input_uk.csv", index=False)

    # ── Write xlsx (4 sheets matching R_code_STM_uk.R) ────────────────────────
    xlsx_path = out_dir / "stm_results_uk.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as w:
        _sanitize_df(top_terms_df).to_excel(w, sheet_name="top_terms", index=False)
        _sanitize_df(gamma_long).to_excel(w, sheet_name="gamma_full", index=False)
        _sanitize_df(thread_topics).to_excel(w, sheet_name="thread_topics", index=False)
        _sanitize_df(effects_df).to_excel(w, sheet_name="effects", index=False)

    print(f"UK outputs written to {out_dir}")
    _print_files(out_dir, [
        "stm_results_uk.xlsx", "stm_thread_enriched_uk.csv",
        "stm_topic_engine_effects_uk.csv", "llm_issue_input_uk.csv",
    ])


# ── Clio outputs (_clio suffix) ───────────────────────────────────────────────

def write_outputs_clio(
    stm: STM,
    df: pd.DataFrame,
    vocab: list[str],
    out_dir: Path,
    k_metrics: pd.DataFrame | None = None,
) -> None:
    """
    Write all Clio STM outputs. Matches R_code_STM_clio.R sections 310–487.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    K = stm.K
    theta = stm.theta  # (D × K)
    beta = stm.beta    # (K × W)
    D = theta.shape[0]
    doc_names = df["doc_name"].tolist()

    # ── Top terms ─────────────────────────────────────────────────────────────
    labels = label_topics(beta, vocab, n=15)
    top_terms_df = pd.DataFrame({
        "topic": range(1, K + 1),
        "terms_prob": [", ".join(row) for row in labels["prob"]],
        "terms_frex": [", ".join(row) for row in labels["frex"]],
    })

    # ── Gamma wide + long ─────────────────────────────────────────────────────
    gamma_wide = pd.DataFrame(
        theta,
        columns=[f"T{k+1}" for k in range(K)],
    )
    gamma_wide["doc_name"] = doc_names

    gamma_long_rows = []
    for d, dname in enumerate(doc_names):
        for k in range(K):
            gamma_long_rows.append({"document": dname, "doc_name": dname,
                                    "topic": k + 1, "gamma": float(theta[d, k])})
    gamma_long = pd.DataFrame(gamma_long_rows)

    # ── Dominant topic ────────────────────────────────────────────────────────
    dom_idx = theta.argmax(axis=1)
    dominant = pd.DataFrame({
        "doc_name": doc_names,
        "dominant_topic": dom_idx + 1,
        "topic_gamma": theta[np.arange(D), dom_idx],
    })

    # ── Gamma vectors ─────────────────────────────────────────────────────────
    gamma_vec = pd.DataFrame({
        "doc_name": doc_names,
        "gamma_vector": [
            "[" + ", ".join(f"{v:.6f}" for v in theta[d]) + "]"
            for d in range(D)
        ],
    })

    # ── Thread enriched ───────────────────────────────────────────────────────
    thread_enriched = df.merge(dominant, on="doc_name", how="left").merge(
        gamma_vec, on="doc_name", how="left"
    )

    # ── Engine effects (conditional) ─────────────────────────────────────────
    has_engine_var = df["engine_group"].nunique() > 1
    if has_engine_var:
        est = EffectEstimator(stm, df)
        effects_df = est.estimate("engine_group")
        effects_df["significant"] = (
            (effects_df["ci_lower"] > 0) | (effects_df["ci_upper"] < 0)
        )
    else:
        effects_df = pd.DataFrame(
            columns=["topic", "engine_group", "estimate", "ci_lower", "ci_upper", "significant"]
        )

    # ── LLM input ─────────────────────────────────────────────────────────────
    topic_prevalence = (
        gamma_long.groupby("topic")["gamma"].mean()
        .reset_index()
        .rename(columns={"gamma": "prevalence_pct"})
    )
    topic_prevalence["prevalence_pct"] = (topic_prevalence["prevalence_pct"] * 100).round(2)

    dom_counts = dominant.groupby("dominant_topic").size().reset_index(name="thread_count")
    dom_counts.columns = ["topic", "thread_count"]

    mileage_col = "mileage_km" if "mileage_km" in df.columns else "mileage_mentioned"
    topic_stats_rows = []
    for k in range(1, K + 1):
        gam_k = theta[:, k - 1]
        mask = gam_k > 0.3
        chronic_w = float(np.average(df["chronic_score"], weights=gam_k))
        ml = df[mileage_col][mask].dropna()
        n_ml = len(ml)
        topic_stats_rows.append({
            "topic": k,
            "chronic_signal": round(chronic_w, 3),
            "mileage_thread_count": n_ml,
            "mileage_median_km": int(ml.median()) if n_ml >= 5 else None,
            "mileage_p20_km": int(ml.quantile(0.2)) if n_ml >= 5 else None,
            "mileage_p80_km": int(ml.quantile(0.8)) if n_ml >= 5 else None,
        })
    topic_stats = pd.DataFrame(topic_stats_rows)

    llm_input = (
        top_terms_df
        .merge(topic_prevalence, on="topic", how="left")
        .merge(dom_counts, on="topic", how="left")
        .merge(topic_stats, on="topic", how="left")
    )
    llm_input["thread_count"] = llm_input["thread_count"].fillna(0).astype(int)
    llm_input["chronic_signal"] = llm_input["chronic_signal"].fillna(0)

    # ── K metrics ─────────────────────────────────────────────────────────────
    if k_metrics is not None:
        k_metrics.to_csv(out_dir / "stm_k_metrics_clio.csv", index=False)

    # ── Write CSVs ────────────────────────────────────────────────────────────
    top_terms_df[["topic", "terms_frex"]].to_csv(
        out_dir / "stm_top_terms_frex_clio.csv", index=False
    )
    thread_enriched.to_csv(out_dir / "stm_thread_enriched_clio.csv", index=False)
    dominant.to_csv(out_dir / "stm_thread_topics_clio.csv", index=False)
    gamma_wide.to_csv(out_dir / "stm_thread_topic_vectors_clio.csv", index=False)
    effects_df.to_csv(out_dir / "stm_topic_engine_effects_clio.csv", index=False)
    llm_input.to_csv(out_dir / "llm_issue_input_clio.csv", index=False)

    # ── Write xlsx (3 sheets matching R_code_STM_clio.R) ─────────────────────
    xlsx_path = out_dir / "stm_results_clio.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as w:
        _sanitize_df(top_terms_df).to_excel(w, sheet_name="top_terms", index=False)
        _sanitize_df(gamma_long).to_excel(w, sheet_name="gamma_full", index=False)
        _sanitize_df(thread_enriched).to_excel(w, sheet_name="thread_topics", index=False)

    print(f"Clio outputs written to {out_dir}")
    _print_files(out_dir, [
        "stm_results_clio.xlsx", "stm_top_terms_frex_clio.csv",
        "stm_thread_enriched_clio.csv", "stm_topic_engine_effects_clio.csv",
        "llm_issue_input_clio.csv",
    ])


# ── Shared helpers ────────────────────────────────────────────────────────────

def _build_llm_input_turkish(
    top_terms_df: pd.DataFrame,
    gamma_full: pd.DataFrame,
    df: pd.DataFrame,
    doc_names: list[str],
    K: int,
) -> pd.DataFrame:
    """Build llm_issue_input.csv for the Turkish corpus."""
    mileage_col = "mileage_mentioned" if "mileage_mentioned" in df.columns else "mileage_km"

    doc_meta = df[["doc_name", "technical_score", "chronic_score", mileage_col]].copy()
    doc_meta = doc_meta.rename(columns={mileage_col: "_mileage"})

    gf = gamma_full.rename(columns={"document": "doc_name"})
    gf = gf.merge(doc_meta, on="doc_name", how="left")

    gf["focus_weight"] = (gf["technical_score"] + 2 * gf["chronic_score"]).clip(lower=1)

    topic_prev = gf.groupby("topic").apply(
        lambda g: pd.Series({
            "prevalence": g["gamma"].mean(),
            "prevalence_tech": np.average(g["gamma"], weights=g["focus_weight"]),
            "technical_signal": np.average(g["technical_score"], weights=g["gamma"]),
            "chronic_signal": np.average(g["chronic_score"], weights=g["gamma"]),
        })
    ).reset_index()

    # Mileage stats for threads with gamma > 0.3
    mileage_rows = []
    for k in range(1, K + 1):
        sub = gf[(gf["topic"] == k) & (gf["gamma"] > 0.3) & gf["_mileage"].notna()]
        km = sub["_mileage"]
        mileage_rows.append({
            "topic": k,
            "min_km": km.quantile(0.2) if len(km) > 0 else None,
            "max_km": km.quantile(0.8) if len(km) > 0 else None,
            "avg_km": km.median() if len(km) > 0 else None,
        })
    topic_mileage = pd.DataFrame(mileage_rows)

    result = (
        top_terms_df[["topic", "terms_frex"]]
        .merge(topic_prev, on="topic", how="left")
        .merge(topic_mileage, on="topic", how="left")
    )

    result["prevalence_blended"] = (
        0.55 * result["prevalence"] + 0.45 * result["prevalence_tech"]
    )
    result["prevalence_pct"] = (result["prevalence_blended"] * 100).round(1)

    def _fmt_mileage(row: pd.Series) -> str:
        if pd.isna(row["min_km"]) or pd.isna(row["max_km"]):
            return "unknown"
        return f"{round(row['min_km'], -3):.0f} - {round(row['max_km'], -3):.0f} km"

    result["mileage_range"] = result.apply(_fmt_mileage, axis=1)
    return result


def _extract_first(text: str, pattern: str) -> int | None:
    import re
    m = re.search(pattern, text)
    return int(m.group(1)) if m else None


def _fuel_type_turkish(engine_group: str) -> str:
    if not engine_group:
        return "unknown"
    eg = str(engine_group).upper()
    if "TDI" in eg:
        return "diesel"
    if any(x in eg for x in ("TSI", "GTI", "GTE")):
        return "petrol"
    return "unknown"


def _mileage_bucket_km(km) -> str:
    if pd.isna(km):
        return "unknown"
    km = int(km)
    if km < 30000:   return "0-30k"
    if km < 60000:   return "30-60k"
    if km < 90000:   return "60-90k"
    if km < 120000:  return "90-120k"
    if km < 150000:  return "120-150k"
    if km < 180000:  return "150-180k"
    if km < 210000:  return "180-210k"
    return "210k+"


def _print_files(out_dir: Path, names: list[str]) -> None:
    for n in names:
        p = out_dir / n
        if p.exists():
            size_kb = p.stat().st_size / 1024
            print(f"  {n}  ({size_kb:.1f} KB)")
