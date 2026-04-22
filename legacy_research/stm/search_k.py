"""
stm/search_k.py
───────────────
K-selection diagnostics — mirrors R's searchK().

For each candidate K, fits a full STM and computes:
  - exclusivity: mean FREX score across topics (higher = more exclusive topics)
  - semcoh: semantic coherence (higher = more coherent)
  - heldout: held-out token log-likelihood
  - bound: ELBO lower bound
  - em_its: number of EM iterations until convergence
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import scipy.sparse as sp

from .core import STM
from .frex import compute_frex


def search_k(
    count_matrix: sp.csr_matrix,
    vocab: list[str],
    metadata: pd.DataFrame,
    prevalence_formula: str,
    k_range: list[int],
    heldout_proportion: float = 0.1,
    seed: int = 42,
    max_em_its: int = 150,       # reduced for K-search speed
    verbose: bool = False,
    **stm_kwargs,
) -> pd.DataFrame:
    """
    Fit STM for each K in k_range and return diagnostic metrics.

    Args:
        count_matrix: (D × W) scipy CSR
        vocab:        list of W feature strings
        metadata:     DataFrame with D rows
        prevalence_formula: R-style formula
        k_range:      list of K values to evaluate
        heldout_proportion: fraction of tokens to hold out per document
        seed:         random seed for reproducibility
        max_em_its:   EM iterations per K (use fewer than final model)
        verbose:      print progress
        **stm_kwargs: passed to STM.__init__

    Returns:
        DataFrame with columns: K, exclusivity, semcoh, heldout, bound, em_its
    """
    rng = np.random.default_rng(seed)
    D, W = count_matrix.shape

    # ── Create held-out mask (10% of tokens per document) ────────────────────
    heldout_mask, train_matrix = _split_heldout(count_matrix, heldout_proportion, rng)

    rows: list[dict] = []

    for k in k_range:
        if verbose:
            print(f"  searchK: fitting K={k}…")

        stm = STM(
            K=k,
            max_em_its=max_em_its,
            verbose=False,
            seed=seed,
            **{kw: v for kw, v in stm_kwargs.items()
               if kw in ("device", "newton_its", "sigma_prior", "batch_size")},
        )
        stm.fit(train_matrix, vocab, metadata, prevalence_formula)

        beta = stm.beta    # (K × W)
        theta = stm.theta  # (D × K)

        excl = _exclusivity(beta)
        sc = _semantic_coherence(beta, train_matrix, vocab, n_top=10)
        ho = _heldout_ll(beta, theta, heldout_mask, count_matrix)
        bound = stm.get_elbo()
        em_its = len(stm.elbo_history)

        rows.append({
            "K": k,
            "exclusivity": excl,
            "semcoh": sc,
            "heldout": ho,
            "bound": bound,
            "em_its": em_its,
        })

        print(f"  K={k:3d}: excl={excl:.4f}, semcoh={sc:.1f}, "
              f"heldout={ho:.4f}, bound={bound:.1f}, its={em_its}")

    return pd.DataFrame(rows)


# ── Diagnostic metrics ────────────────────────────────────────────────────────

def _exclusivity(beta: np.ndarray, lambda_: float = 1.0, n_terms: int = 10) -> float:
    """
    Mean FREX exclusivity score across all topics (lambda=1 weights exclusivity only).
    """
    K, W = beta.shape
    eps = 1e-12
    log_beta = np.log(beta + eps)
    word_totals = np.log(beta.sum(axis=0) + eps)
    excl = log_beta - word_totals[np.newaxis, :]

    excl_ecdf = np.zeros_like(excl)
    for k in range(K):
        ranks = excl[k].argsort().argsort() + 1
        excl_ecdf[k] = ranks / W

    # For each topic, mean exclusivity ECDF of top-n terms by beta
    scores = []
    for k in range(K):
        top_idx = np.argsort(beta[k])[-n_terms:]
        scores.append(excl_ecdf[k, top_idx].mean())
    return float(np.mean(scores))


def _semantic_coherence(
    beta: np.ndarray,
    count_matrix: sp.csr_matrix,
    vocab: list[str],
    n_top: int = 10,
) -> float:
    """
    Mean semantic coherence across topics.
    SC(k) = Σ_{m>l} log(D(v_m, v_l) + 1) / log(D(v_l) + 1)
    where v_m, v_l are top words for topic k.
    """
    K, W = beta.shape
    D = count_matrix.shape[0]

    # Document frequencies
    doc_freq = np.asarray((count_matrix > 0).sum(axis=0)).ravel()  # (W,)

    # Co-document frequencies: build from top words
    sc_scores = []
    for k in range(K):
        top_idx = np.argsort(beta[k])[-n_top:]
        sc = 0.0
        for i in range(len(top_idx)):
            for j in range(i):
                wi = top_idx[i]
                wj = top_idx[j]
                # Co-occurrence count
                col_i = (count_matrix[:, wi] > 0).toarray().ravel()
                col_j = (count_matrix[:, wj] > 0).toarray().ravel()
                co = int((col_i & col_j).sum())
                dj = int(doc_freq[wj])
                sc += np.log((co + 1) / (dj + 1))
        sc_scores.append(sc)
    return float(np.mean(sc_scores))


def _heldout_ll(
    beta: np.ndarray,       # (K × W)
    theta: np.ndarray,      # (D × K)
    heldout_mask: np.ndarray,  # sparse (D × W) held-out counts
    count_matrix: sp.csr_matrix,
) -> float:
    """Held-out per-token log-likelihood."""
    # Predicted word probabilities: theta @ beta  (D × W)
    # For each held-out word, log p(w) = log(sum_k theta[d,k] * beta[k,w])
    D, W = count_matrix.shape
    eps = 1e-12

    total_ll = 0.0
    total_tokens = 0

    heldout_coo = sp.coo_matrix(heldout_mask)
    for d, w, cnt in zip(heldout_coo.row, heldout_coo.col, heldout_coo.data):
        p_w = float((theta[d] @ beta[:, w]).clip(eps))
        total_ll += cnt * np.log(p_w)
        total_tokens += cnt

    if total_tokens == 0:
        return float("nan")
    return total_ll / total_tokens


def _split_heldout(
    count_matrix: sp.csr_matrix,
    proportion: float,
    rng: np.random.Generator,
) -> tuple[sp.csr_matrix, sp.csr_matrix]:
    """
    Split each document's tokens: hold out `proportion` of tokens.
    Returns (heldout_matrix, train_matrix).
    """
    D, W = count_matrix.shape
    heldout_rows, heldout_cols, heldout_data = [], [], []
    train_rows, train_cols, train_data = [], [], []

    coo = count_matrix.tocoo()
    for d, w, cnt in zip(coo.row, coo.col, coo.data):
        n_held = max(0, round(cnt * proportion))
        n_train = cnt - n_held
        if n_held > 0:
            heldout_rows.append(d); heldout_cols.append(w); heldout_data.append(n_held)
        if n_train > 0:
            train_rows.append(d); train_cols.append(w); train_data.append(n_train)

    heldout = sp.csr_matrix(
        (heldout_data, (heldout_rows, heldout_cols)), shape=(D, W)
    )
    train = sp.csr_matrix(
        (train_data, (train_rows, train_cols)), shape=(D, W)
    )
    return heldout, train
