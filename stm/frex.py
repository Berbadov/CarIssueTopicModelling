"""
stm/frex.py
───────────
FREX (FRequency EXclusivity) scoring and top-term extraction.
Ports R's labelTopics(stm_model, n=15)$frex and $prob.

FREX balances how frequent a word is within a topic (frequency)
and how exclusive it is to that topic compared to other topics
(exclusivity). Higher FREX = better topic label.
"""

from __future__ import annotations

import numpy as np


def compute_frex(
    beta: np.ndarray,
    lambda_: float = 0.7,
    n_terms: int = 15,
) -> np.ndarray:
    """
    Compute FREX scores and return top-n word indices per topic.

    FREX formula (Roberts et al. 2016):
        frex[k,w] = 1 / (lambda / freq_ecdf[k,w] + (1-lambda) / excl_ecdf[k,w])

    where freq_ecdf[k,w] = empirical CDF of log(beta[k,w]) within topic k,
    and excl_ecdf[k,w] = empirical CDF of exclusivity within topic k.

    Exclusivity[k,w] = log(beta[k,w]) - log(sum_k' beta[k',w])
                     = log(beta[k,w] / sum_k' beta[k',w])

    Args:
        beta:    (K × W) topic-word probability matrix
        lambda_: weight on frequency component (0.7 default matches R stm)
        n_terms: number of top terms to return per topic

    Returns:
        frex_idx: (K × n_terms) array of word indices, sorted by FREX descending
    """
    K, W = beta.shape
    eps = 1e-12

    log_beta = np.log(beta + eps)  # (K × W)

    # Exclusivity: log of word-level conditional topic probability
    word_totals = np.log(beta.sum(axis=0) + eps)  # (W,)
    excl = log_beta - word_totals[np.newaxis, :]  # (K × W)

    # Empirical CDFs: rank / W within each topic row
    freq_ecdf = np.zeros_like(log_beta)
    excl_ecdf = np.zeros_like(excl)
    for k in range(K):
        freq_ecdf[k] = _ecdf_rank(log_beta[k])
        excl_ecdf[k] = _ecdf_rank(excl[k])

    # FREX = harmonic mean weighted by lambda
    freq_ecdf = np.clip(freq_ecdf, eps, None)
    excl_ecdf = np.clip(excl_ecdf, eps, None)
    frex = 1.0 / (lambda_ / freq_ecdf + (1.0 - lambda_) / excl_ecdf)

    # Return indices of top n_terms per topic (descending FREX)
    n_actual = min(n_terms, W)
    # argsort gives ascending; take last n_actual and reverse
    frex_idx = np.argsort(frex, axis=1)[:, -n_actual:][:, ::-1].copy()
    return frex_idx


def _ecdf_rank(arr: np.ndarray) -> np.ndarray:
    """Return empirical CDF rank for 1-D array: rank / n (1/n .. 1.0)."""
    n = len(arr)
    order = arr.argsort()
    ranks = np.empty(n, dtype=np.float64)
    ranks[order] = (np.arange(n) + 1) / n  # fractional rank
    return ranks


def compute_prob_top(beta: np.ndarray, n_terms: int = 15) -> np.ndarray:
    """
    Return indices of top n words by raw probability (beta) per topic.
    Mirrors R labelTopics()$prob.

    Returns:
        prob_idx: (K × n_terms) word index array, sorted descending by beta
    """
    n_actual = min(n_terms, beta.shape[1])
    return np.argsort(beta, axis=1)[:, -n_actual:][:, ::-1].copy()


def label_topics(
    beta: np.ndarray,
    vocab: list[str],
    n: int = 15,
    lambda_: float = 0.7,
) -> dict[str, np.ndarray]:
    """
    Extract top-n topic labels by FREX and PROB.

    Args:
        beta:  (K × W) topic-word probability matrix (numpy, CPU)
        vocab: list of W feature strings
        n:     number of terms per topic
        lambda_: FREX lambda parameter

    Returns:
        dict with:
          "prob":  (K × n) string array of top words by probability
          "frex":  (K × n) string array of top words by FREX score
          "prob_idx": (K × n) int array of word indices (prob)
          "frex_idx": (K × n) int array of word indices (frex)
    """
    vocab_arr = np.array(vocab)
    prob_idx = compute_prob_top(beta, n)
    frex_idx = compute_frex(beta, lambda_=lambda_, n_terms=n)

    prob_terms = vocab_arr[prob_idx]   # (K × n)
    frex_terms = vocab_arr[frex_idx]   # (K × n)

    return {
        "prob": prob_terms,
        "frex": frex_terms,
        "prob_idx": prob_idx,
        "frex_idx": frex_idx,
    }
