"""
stm/dfm.py
──────────
Text preprocessing and Document-Feature Matrix (DFM) builder.
Ports the quanteda-based preprocessing from R_code_STM*.R.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Callable, Literal

import numpy as np
import pandas as pd
import scipy.sparse as sp


# ── Mileage extraction ────────────────────────────────────────────────────────

def _to_int(s: str) -> int | None:
    cleaned = re.sub(r"[^0-9]", "", s)
    return int(cleaned) if cleaned else None


def extract_mileage_km(text: str) -> tuple[int | None, str]:
    """
    Extract km mileage from text.
    Returns (km_value, confidence) where confidence ∈ {"range","medium","high","none"}.
    Ports Turkish extract_mileage_info() from R_code_STM.R.
    """
    if not text or str(text).strip() == "":
        return None, "none"
    t = str(text).lower()

    # "30-40 bin km" → take lower bound
    m = re.search(
        r"\b(\d{1,3})\s*[-\u2013]\s*(\d{1,3})\s*(k|bin)\s*"
        r"(?:km|kilometre|kilometrede|kilometresi)?\b", t
    )
    if m:
        lo = _to_int(m.group(1))
        if lo is not None:
            return lo * 1000, "range"

    # "216k km", "125 bin km"
    m = re.search(
        r"\b(\d{1,3})\s*(k|bin)\s*(?:km|kilometre|kilometrede|kilometresi)?\b", t
    )
    if m:
        base = _to_int(m.group(1))
        if base is not None:
            return base * 1000, "medium"

    # "239890 km", "126.000 kilometrede"
    m = re.search(
        r"\b(\d{1,3}(?:[.,]\d{3})+|\d{4,})\s*"
        r"(?:km|kilometre|kilometrede|kilometresi)\b", t
    )
    if m:
        return _to_int(m.group(1)), "high"

    # "kilometre: 94450"
    m = re.search(
        r"\bkilometre(?:de|si|yi|ye)?\s*[:=]?\s*"
        r"(\d{1,3}(?:[.,]\d{3})+|\d{4,})\b", t
    )
    if m:
        return _to_int(m.group(1)), "high"

    # "mileage: 239890"
    m = re.search(r"\bmileage\s*[:=]?\s*(\d{1,3}(?:[.,]\d{3})+|\d{4,})\b", t)
    if m:
        return _to_int(m.group(1)), "high"

    return None, "none"


def extract_mileage_miles(text: str) -> tuple[int | None, str]:
    """
    Extract miles mileage from text.
    Returns (miles_value, confidence).
    Ports UK extract_mileage_info() from R_code_STM_uk.R.
    """
    if not text or str(text).strip() == "":
        return None, "none"
    t = str(text).lower()

    # "50k miles", "50k mls", "50k mi", "50K"
    m = re.search(r"\b(\d{1,3})\s*k\s*(?:miles?|mls?|mi)?\b", t)
    if m:
        base = _to_int(m.group(1))
        if base is not None:
            return base * 1000, "high"

    # "50,000 miles", "50000 miles"
    m = re.search(r"\b(\d{1,3}(?:[,]\d{3})+|\d{4,})\s*(?:miles?|mls?)\b", t)
    if m:
        val = _to_int(m.group(1))
        return val, "high"

    # "65000 on the clock"
    m = re.search(r"\b(\d{4,})\s+on\s+(?:the\s+)?clock\b", t)
    if m:
        return _to_int(m.group(1)), "medium"

    # "mileage: 65000"
    m = re.search(r"\bmileage\s*[:=]?\s*(\d{4,})\b", t)
    if m:
        return _to_int(m.group(1)), "medium"

    # km fallback → convert to miles
    m = re.search(r"\b(\d{1,3}(?:[.,]\d{3})+|\d{4,})\s*km\b", t)
    if m:
        km = _to_int(m.group(1))
        if km is not None:
            return int(km / 1.609), "low"

    return None, "none"


def extract_year(text: str) -> int | None:
    """Extract model year from text (1996–2026 range)."""
    if not text:
        return None
    m = re.search(r"\b(199[6-9]|200\d|201\d|202[0-6])\b", str(text).lower())
    return int(m.group(1)) if m else None


# ── Pattern matching ──────────────────────────────────────────────────────────

def _compile(raw: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in raw]


def count_pattern_hits(text: str, patterns: list[re.Pattern]) -> int:
    """Count how many patterns match in text."""
    if not text:
        return 0
    t = str(text).lower()
    return sum(1 for p in patterns if p.search(t))


# ── Thread aggregation ────────────────────────────────────────────────────────

def aggregate_threads(
    df_raw: pd.DataFrame,
    *,
    mileage_mode: Literal["km", "miles"],
    technical_patterns: list[re.Pattern],
    chronic_patterns: list[re.Pattern],
    cosmetic_patterns: list[re.Pattern],
    infotainment_patterns: list[re.Pattern],
    technical_reason_tags: list[str],
    engine_group_fn: Callable[[str | None], str],
    cosmetic_filter: bool = True,
    clio_mode: bool = False,
) -> pd.DataFrame:
    """
    Aggregate raw message-level df to one row per thread.

    Behaviour matches the R scripts exactly:
    - First post always kept; double-weighted (prepended) in final text
    - Subsequent posts kept only if low-cosmetic or carry technical content
    - Mileage extracted from first message that contains mileage info
    - Engine group collapsed via engine_group_fn
    - Cosmetic/infotainment dominated threads filtered out

    clio_mode=True uses simpler concatenation (no double-weighting) and
    applies an additional focus_score >= 2 filter, matching R_code_STM_clio.R.
    """
    extract_mileage = extract_mileage_km if mileage_mode == "km" else extract_mileage_miles
    mileage_col = "mileage_km" if clio_mode else "mileage_mentioned"

    reason_tag_re = re.compile(
        "|".join(re.escape(t) for t in technical_reason_tags), re.IGNORECASE
    )

    rows: list[dict] = []
    for (thread_name, thread_url), grp in df_raw.groupby(
        ["thread_name", "thread_url"], sort=False
    ):
        msgs = grp["message"].fillna("").tolist()
        reason = grp["reason"].iloc[0] if "reason" in grp.columns else None
        engine_code = str(grp["engine_code"].iloc[0]) if "engine_code" in grp.columns else "unknown"
        if not engine_code or engine_code == "nan":
            engine_code = "unknown"

        # ── Text assembly ─────────────────────────────────────────────────────
        if len(msgs) == 0:
            txt = ""
        elif clio_mode or len(msgs) == 1:
            txt = " ".join(msgs)
        else:
            # Non-clio multi-message: filter cosmetic follow-ups
            cosm = [count_pattern_hits(m, cosmetic_patterns) for m in msgs]
            tech = [count_pattern_hits(m, technical_patterns) for m in msgs]
            keep = [True] + [
                (cosm[i] < 2) and (tech[i] > 0 or cosm[i] == 0)
                for i in range(1, len(msgs))
            ]
            filtered = [m for m, k in zip(msgs, keep) if k] or [msgs[0]]
            # Double-weight first post (prepend once more)
            txt = " ".join([filtered[0]] + filtered)

        # ── Mileage ───────────────────────────────────────────────────────────
        mileage_val: int | None = None
        mileage_conf = "none"
        for msg in msgs:
            v, c = extract_mileage(msg)
            if v is not None:
                mileage_val = v
                mileage_conf = c
                break

        row: dict = {
            "thread_name": thread_name,
            "thread_url": thread_url,
            "txt": txt,
            "reason": reason,
            "engine_code": engine_code,
            mileage_col: mileage_val,
            "mileage_confidence": mileage_conf,
            "n_messages": len(msgs),
        }

        # Clio extras
        if "engine_spec" in grp.columns:
            es = grp["engine_spec"].iloc[0]
            row["engine_spec"] = str(es) if (es and str(es) != "nan") else "unknown"
        if "prod_year" in grp.columns:
            try:
                row["prod_year"] = int(grp["prod_year"].iloc[0])
            except (ValueError, TypeError):
                row["prod_year"] = None

        rows.append(row)

    df = pd.DataFrame(rows).reset_index(drop=True)

    # ── Score each thread ─────────────────────────────────────────────────────
    df["technical_score"] = df["txt"].apply(
        lambda t: count_pattern_hits(t, technical_patterns)
    )
    df["chronic_score"] = df["txt"].apply(
        lambda t: count_pattern_hits(t, chronic_patterns)
    )
    df["cosmetic_score"] = df["txt"].apply(
        lambda t: count_pattern_hits(t, cosmetic_patterns)
    )
    df["infotainment_score"] = df["txt"].apply(
        lambda t: count_pattern_hits(t, infotainment_patterns)
    )

    df["reason_technical_hint"] = df["reason"].fillna("").apply(
        lambda r: 1 if reason_tag_re.search(str(r)) else 0
    )

    df["focus_score"] = (
        df["technical_score"]
        + 2 * df["chronic_score"]
        + df["reason_technical_hint"]
        - df["cosmetic_score"].clip(upper=3)
    )

    df["technical_bucket"] = pd.Categorical(
        df["focus_score"].apply(
            lambda s: "high" if s >= 4 else ("medium" if s >= 2 else "low")
        ),
        categories=["low", "medium", "high"],
        ordered=True,
    )

    # ── Engine group ──────────────────────────────────────────────────────────
    df["engine_group"] = df["engine_code"].apply(engine_group_fn)

    # ── Noise filters ─────────────────────────────────────────────────────────
    n_before = len(df)

    if clio_mode:
        # Clio: filter low-focus first
        df = df[df["focus_score"] >= 2].copy()

    if cosmetic_filter:
        df = df[
            ~(
                (df["cosmetic_score"] > df["technical_score"].clip(lower=1))
                & (df["technical_score"] < 2)
            )
        ].copy()
        df = df[
            ~((df["infotainment_score"] > 3) & (df["technical_score"] < 1))
        ].copy()

    n_removed = n_before - len(df)
    print(
        f"Noise filter: removed {n_removed} threads "
        f"({n_before} -> {len(df)})"
    )

    # ── Engine group distribution ─────────────────────────────────────────────
    print("Engine group distribution:")
    print(df["engine_group"].value_counts().to_string())
    print("Technical bucket distribution:")
    print(df["technical_bucket"].value_counts().to_string())
    print(f"Threads (documents): {len(df)}")

    # ── Lowercase text + doc IDs ──────────────────────────────────────────────
    df["txt"] = df["txt"].str.lower()
    df = df.reset_index(drop=True)
    df["doc_id"] = range(1, len(df) + 1)
    df["doc_name"] = [f"doc_{i:05d}" for i in df["doc_id"]]

    return df


# ── Bigram detection ──────────────────────────────────────────────────────────

class BigramDetector:
    """
    Ports quanteda textstat_collocations(min_count=3, z>3).
    Uses Poisson-based z-score for bigram significance.
    """

    def __init__(self, min_count: int = 3, z_threshold: float = 3.0):
        self.min_count = min_count
        self.z_threshold = z_threshold
        self._bigrams: list[str] = []

    def fit(self, tokenized_docs: list[list[str]]) -> "BigramDetector":
        bigram_counts: Counter = Counter()
        unigram_counts: Counter = Counter()
        total_tokens = 0

        for tokens in tokenized_docs:
            for t in tokens:
                if t:
                    unigram_counts[t] += 1
            for i in range(len(tokens) - 1):
                if tokens[i] and tokens[i + 1]:
                    bigram_counts[(tokens[i], tokens[i + 1])] += 1
            total_tokens += len(tokens)

        N = max(total_tokens, 1)
        significant: list[tuple[str, float, int]] = []

        for (w1, w2), c_ab in bigram_counts.items():
            if c_ab < self.min_count:
                continue
            c_a = unigram_counts[w1]
            c_b = unigram_counts[w2]
            expected = (c_a / N) * (c_b / N) * N
            if expected <= 0:
                continue
            z = (c_ab - expected) / math.sqrt(max(expected, 1e-9))
            if z > self.z_threshold:
                significant.append((f"{w1} {w2}", z, c_ab))

        significant.sort(key=lambda x: -x[1])
        self._bigrams = [s[0] for s in significant]
        print(f"Significant bigrams (z>{self.z_threshold}): {len(self._bigrams)}")
        return self

    def significant_bigrams(self) -> list[str]:
        return list(self._bigrams)


# ── DFM builder ───────────────────────────────────────────────────────────────

def _simple_tokenize(text: str, keep_numbers: bool = True) -> list[str]:
    """
    Basic tokenisation: strip URLs, remove non-word chars, split on whitespace.
    Matches quanteda's tokens(remove_punct=TRUE, remove_symbols=TRUE, remove_url=TRUE).
    """
    text = str(text).lower()
    # Remove URLs
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)
    # Remove punctuation and symbols except hyphens within words (handled below)
    text = re.sub(r"[^\w\s-]", " ", text)
    text = re.sub(r"(?<!\w)-|-(?!\w)", " ", text)  # remove standalone hyphens
    tokens = text.split()
    if not keep_numbers:
        tokens = [t for t in tokens if not t.isdigit()]
    return tokens


class DFMBuilder:
    """
    Document-Feature Matrix builder matching the quanteda DFM pipeline.
    Produces a scipy.sparse.csr_matrix (D_kept × W) and vocabulary list.
    """

    def __init__(
        self,
        stopwords: list[str],
        min_termfreq: int = 2,
        min_docfreq: int = 1,
        max_docfreq_prop: float = 0.0,  # 0 = no upper limit
        min_charlen: int = 0,
        keep_numbers: bool = True,
    ):
        self.stopwords = {sw.lower() for sw in stopwords}
        self.min_termfreq = min_termfreq
        self.min_docfreq = min_docfreq
        self.max_docfreq_prop = max_docfreq_prop
        self.min_charlen = min_charlen
        self.keep_numbers = keep_numbers

    @staticmethod
    def _apply_compounds(
        tokens: list[str],
        compound_map: dict[tuple[str, ...], str],
    ) -> list[str]:
        """
        Scan token list for multi-word compound phrases and join them.
        Longer phrases take priority (greedy left-to-right).
        """
        if not compound_map:
            return tokens
        # Group phrases by length for efficiency (longest first)
        phrase_lengths = sorted({len(k) for k in compound_map}, reverse=True)
        result: list[str] = []
        i = 0
        while i < len(tokens):
            matched = False
            for length in phrase_lengths:
                if i + length <= len(tokens):
                    phrase = tuple(tokens[i : i + length])
                    if phrase in compound_map:
                        result.append(compound_map[phrase])
                        i += length
                        matched = True
                        break
            if not matched:
                result.append(tokens[i])
                i += 1
        return result

    def fit_transform(
        self,
        docs: list[str],
        compound_terms: list[str] | None = None,
        compound_dict: dict[str, list[str]] | None = None,
    ) -> tuple[sp.csr_matrix, list[str], list[int]]:
        """
        Tokenise, filter, and build a document-feature matrix.

        Args:
            docs: raw document strings
            compound_terms: list of "word1 word2" bigrams → joined as "word1_word2"
            compound_dict: {canonical_term: ["phrase1", "phrase2", ...]}
                           Used for the Turkish hardcoded compound dictionary.

        Returns:
            count_matrix: (D_kept × W) scipy csr_matrix
            vocab: list of feature strings (length W)
            kept_indices: indices into original docs list (non-empty rows kept)
        """
        D = len(docs)

        # Build compound lookup {phrase_tokens_tuple: canonical}
        compound_map: dict[tuple[str, ...], str] = {}
        if compound_terms:
            for phrase in compound_terms:
                toks = tuple(phrase.lower().split())
                if toks:
                    compound_map[toks] = phrase.lower().replace(" ", "_")
        if compound_dict:
            for canonical, phrases in compound_dict.items():
                for phrase in phrases:
                    toks = tuple(phrase.lower().split())
                    if toks:
                        compound_map[toks] = canonical.lower()

        # ── Tokenise all documents ────────────────────────────────────────────
        all_tokens: list[list[str]] = []
        for doc in docs:
            tokens = _simple_tokenize(doc, keep_numbers=self.keep_numbers)
            tokens = self._apply_compounds(tokens, compound_map)
            filtered = []
            for t in tokens:
                if t in self.stopwords:
                    continue
                if self.min_charlen > 0 and len(t) < self.min_charlen:
                    continue
                filtered.append(t)
            all_tokens.append(filtered)

        # ── Build vocabulary with frequency filters ───────────────────────────
        term_freq: Counter = Counter()
        doc_freq: Counter = Counter()
        for tokens in all_tokens:
            term_freq.update(tokens)
            doc_freq.update(set(tokens))

        vocab_set: set[str] = set()
        for term, tf in term_freq.items():
            if tf < self.min_termfreq:
                continue
            if self.min_docfreq > 1 and doc_freq[term] < self.min_docfreq:
                continue
            if self.max_docfreq_prop > 0 and doc_freq[term] / D > self.max_docfreq_prop:
                continue
            vocab_set.add(term)

        vocab = sorted(vocab_set)
        vocab_idx = {t: i for i, t in enumerate(vocab)}
        W = len(vocab)

        # ── Build sparse count matrix ─────────────────────────────────────────
        rows_list, cols_list, data_list = [], [], []
        for d_idx, tokens in enumerate(all_tokens):
            tok_counts = Counter(t for t in tokens if t in vocab_idx)
            for term, count in tok_counts.items():
                rows_list.append(d_idx)
                cols_list.append(vocab_idx[term])
                data_list.append(count)

        count_matrix = sp.csr_matrix(
            (data_list, (rows_list, cols_list)),
            shape=(D, W),
            dtype=np.int32,
        )

        # ── Remove empty documents (CRITICAL – mirrors R empty-row fix) ───────
        row_sums = np.asarray(count_matrix.sum(axis=1)).ravel()
        kept_indices = [i for i, s in enumerate(row_sums) if s > 0]
        count_matrix = count_matrix[kept_indices, :]

        print(
            f"DFM: {D} docs → {len(kept_indices)} non-empty | "
            f"vocab={W} | removed {D - len(kept_indices)} empty docs"
        )
        return count_matrix, vocab, kept_indices
