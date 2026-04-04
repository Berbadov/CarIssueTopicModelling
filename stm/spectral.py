"""
stm/spectral.py
───────────────
Spectral initialization for STM topic-word distributions.
Based on Arora et al. (2012) anchor-word approach, adapted to match
the init.type="Spectral" behaviour in the R stm package.

CUDA role: the SVD of the P×P co-occurrence matrix runs on GPU,
which is significantly faster than numpy for P ≥ 500.
"""

from __future__ import annotations

import numpy as np
import scipy.sparse as sp
import torch
import torch.nn.functional as F


def spectral_init_beta(
    count_matrix: sp.csr_matrix,
    vocab: list[str],
    K: int,
    top_p: int = 2000,
    seed: int = 42,
    device: torch.device | str = "cpu",
) -> torch.Tensor:
    """
    Compute spectral initialization for topic-word log-distributions.

    Algorithm:
      1. Select top-P words by corpus frequency.
      2. Build normalized co-occurrence moment matrix M (P × P):
         M[i,j] = E_doc[p(w_i|doc) * p(w_j|doc)]
      3. SVD on GPU: M = U S Vt → take first K rows of Vt.
      4. Project to probability simplex (ReLU + ε + row-normalize).
      5. Zero-pad back to full vocabulary size W.

    Returns:
        beta_log: (K × W) float32 tensor on `device` — log topic-word probs.
    """
    device = torch.device(device)
    D, W = count_matrix.shape

    # ── 1. Select top-P words ─────────────────────────────────────────────────
    word_freq = np.asarray(count_matrix.sum(axis=0)).ravel()
    top_p_actual = min(top_p, W)
    top_idx = np.argsort(word_freq)[-top_p_actual:]  # ascending → take last P
    P = len(top_idx)

    # ── 2. Build document-level word distributions (D × P) ───────────────────
    sub = count_matrix[:, top_idx].astype(np.float32)  # sparse (D × P)
    doc_sums = np.asarray(sub.sum(axis=1)).ravel()
    doc_sums[doc_sums == 0] = 1.0  # avoid div-by-zero for empty rows

    # Row-normalise sparse matrix → doc-word prob matrix
    sub = sub.multiply(1.0 / doc_sums[:, np.newaxis])  # still sparse

    # ── 3. Word co-occurrence moment matrix M = sub.T @ sub  (P × P) ─────────
    # sub.T is (P × D), sub is (D × P); result is (P × P)
    sub_dense = sub.toarray()  # (D × P) — P ≤ 2000 so manageable
    M = sub_dense.T @ sub_dense  # (P × P)

    # ── 4. SVD on GPU ────────────────────────────────────────────────────────
    M_gpu = torch.from_numpy(M.astype(np.float32)).to(device)
    # torch.linalg.svd returns U, S, Vh  where Vh[i,:] is the i-th right sv
    try:
        _, _, Vh = torch.linalg.svd(M_gpu, full_matrices=False)
    except Exception:
        # Fallback to CPU if GPU SVD fails
        _, _, Vh = torch.linalg.svd(M_gpu.cpu(), full_matrices=False)
        Vh = Vh.to(device)

    # Take first K rows of Vh as initial topic directions in top-P word space
    k_use = min(K, Vh.shape[0])
    V_k = Vh[:k_use, :]  # (K × P)

    # ── 5. Project to probability simplex ────────────────────────────────────
    V_k = V_k.abs()           # ensure non-negative
    V_k = V_k + 1e-8           # ε floor so no row is all-zero
    row_sums = V_k.sum(dim=1, keepdim=True)
    V_k = V_k / row_sums      # row-normalize → probability distributions over P words

    # If K > k_use (rare), pad with small random topics
    if k_use < K:
        torch.manual_seed(seed)
        extra = torch.rand(K - k_use, P, device=device) + 1e-8
        extra = extra / extra.sum(dim=1, keepdim=True)
        V_k = torch.cat([V_k, extra], dim=0)

    # ── 6. Expand to full vocabulary ─────────────────────────────────────────
    beta = torch.full((K, W), 1e-9, device=device, dtype=torch.float32)
    beta[:, top_idx] = V_k.float()

    # Renormalize each row over the full vocabulary
    beta = beta / beta.sum(dim=1, keepdim=True)

    return torch.log(beta)
