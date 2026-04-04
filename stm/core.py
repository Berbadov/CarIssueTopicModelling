"""
stm/core.py
───────────
Structural Topic Model — variational EM with PyTorch+CUDA acceleration.

Algorithm (Roberts, Stewart, Tingley 2016):
  Generative model:
    η_d ~ N(X_d @ γ, Σ)        document-level logistic-normal prior
    θ_d = softmax([η_d; 0])    topic proportions (K-simplex)
    z_dn ~ Cat(θ_d)            topic assignment per word
    w_dn ~ Cat(β_{z_dn})       word draw

  Variational approximation:
    q(η_d) = N(μ_d, diag(ν_d²))

  EM:
    E-step: update μ_d, ν_d² via Newton's method (per document, batched on GPU)
    M-step: update β (topic-word), γ (covariate coefficients), Σ (prior cov)

CUDA acceleration:
  • E-step Newton loop: batch of B docs × all their word positions in one
    scatter_add pass — replaces D serial Newton loops from the R script.
  • M-step β update: scatter_add accumulation over the full corpus —
    replaces R's Reduce("+", lapply(docs, ...)).
  • Spectral init SVD: runs on GPU via spectral.py.
"""

from __future__ import annotations

import re
from typing import Sequence

import numpy as np
import pandas as pd
import scipy.sparse as sp
import torch
import torch.nn.functional as F

from .spectral import spectral_init_beta


# ── Design matrix ─────────────────────────────────────────────────────────────

def build_design_matrix(
    metadata: pd.DataFrame,
    formula: str,
) -> tuple[np.ndarray, list[str]]:
    """
    Convert an R-style formula to a (D × p) float32 design matrix.

    Continuous columns are included as-is.
    Categorical columns are dummy-coded (drop_first=True, matching R model.matrix).
    Intercept column is always prepended.

    Returns:
        X:    (D × p) float32 numpy array
        cols: list of column names for interpretability
    """
    rhs = formula.split("~", 1)[1].strip()
    if rhs == "1":
        return (
            np.ones((len(metadata), 1), dtype=np.float32),
            ["(Intercept)"],
        )

    terms = [t.strip() for t in rhs.split("+")]
    parts: list[np.ndarray] = [np.ones((len(metadata), 1), dtype=np.float32)]
    col_names: list[str] = ["(Intercept)"]

    for term in terms:
        if term not in metadata.columns:
            print(f"  [design_matrix] Warning: term '{term}' not found in metadata — skipped")
            continue
        col = metadata[term]
        if pd.api.types.is_numeric_dtype(col):
            arr = col.fillna(0).values.reshape(-1, 1).astype(np.float32)
            parts.append(arr)
            col_names.append(term)
        else:
            dummies = pd.get_dummies(
                col.astype(str), prefix=term, drop_first=True, dtype=np.float32
            )
            parts.append(dummies.values)
            col_names.extend(dummies.columns.tolist())

    X = np.hstack(parts)
    return X, col_names


# ── Sparse CSR conversion ─────────────────────────────────────────────────────

def scipy_csr_to_torch(mat: sp.csr_matrix, device: torch.device) -> torch.Tensor:
    """Convert scipy CSR to torch sparse CSR tensor."""
    mat = mat.astype(np.float32)
    crow = torch.from_numpy(mat.indptr.astype(np.int32))
    col = torch.from_numpy(mat.indices.astype(np.int32))
    val = torch.from_numpy(mat.data.astype(np.float32))
    return torch.sparse_csr_tensor(crow, col, val, size=mat.shape, device=device)


# ── STM core class ────────────────────────────────────────────────────────────

class STM:
    """
    Structural Topic Model fitted via variational EM.

    Parameters
    ----------
    K : int
        Number of topics.
    device : str or torch.device
        "cuda" (default) or "cpu".
    max_em_its : int
        Maximum EM iterations (default 500, matching R default).
    em_convergence : float
        Stop when |ΔELBO / ELBO| < this threshold.
    newton_its : int
        Newton steps per document per E-step (default 5).
    sigma_prior : float
        Initial diagonal value for the prior covariance Σ.
    batch_size : int
        Documents per E-step batch. Auto-halved on CUDA OOM.
    verbose : bool
    seed : int
    """

    def __init__(
        self,
        K: int,
        device: str | torch.device = "cuda",
        max_em_its: int = 500,
        em_convergence: float = 1e-4,
        newton_its: int = 5,
        sigma_prior: float = 1.0,
        batch_size: int = 512,
        verbose: bool = True,
        seed: int = 42,
    ):
        self.K = K
        self.device = torch.device(device if torch.cuda.is_available() else "cpu")
        self.max_em_its = max_em_its
        self.em_convergence = em_convergence
        self.newton_its = newton_its
        self.sigma_prior = sigma_prior
        self.batch_size = batch_size
        self.verbose = verbose
        self.seed = seed

        if self.verbose:
            print(f"STM: K={K}, device={self.device}, max_em_its={max_em_its}")

        # Set after fit()
        self._beta_log: torch.Tensor | None = None   # (K × W)
        self._mu: torch.Tensor | None = None          # (D × K-1)
        self._nu_sq: torch.Tensor | None = None       # (D × K-1)
        self._gamma_cov: torch.Tensor | None = None   # (p × K-1)
        self._sigma_diag: torch.Tensor | None = None  # (K-1,)
        self._X: torch.Tensor | None = None           # (D × p)
        self._vocab: list[str] = []
        self._design_col_names: list[str] = []
        self.elbo_history: list[float] = []

    # ── Public fit API ────────────────────────────────────────────────────────

    def fit(
        self,
        count_matrix: sp.csr_matrix,
        vocab: list[str],
        metadata: pd.DataFrame,
        prevalence_formula: str,
    ) -> "STM":
        """
        Fit STM via spectral init + variational EM.

        Args:
            count_matrix: (D × W) scipy CSR, integer word counts
            vocab:        list of W feature strings
            metadata:     DataFrame with D rows (covariate columns)
            prevalence_formula: R-style formula string e.g. "~ engine_group + mileage_log"
        """
        torch.manual_seed(self.seed)
        D, W = count_matrix.shape
        K = self.K
        dev = self.device

        self._vocab = vocab

        # ── Design matrix ─────────────────────────────────────────────────────
        X_np, self._design_col_names = build_design_matrix(metadata, prevalence_formula)
        p = X_np.shape[1]
        X = torch.from_numpy(X_np).to(dev)  # (D × p)
        self._X = X

        if self.verbose:
            print(f"  Design matrix: {D} × {p}  (formula: {prevalence_formula})")

        # ── Document lengths ──────────────────────────────────────────────────
        n_d = torch.from_numpy(
            np.asarray(count_matrix.sum(axis=1)).ravel().astype(np.float32)
        ).to(dev)  # (D,)

        # ── Pre-compute COO representation sorted by document index ───────────
        # This lets us slice word data per batch without moving full matrix each time.
        coo = count_matrix.tocoo().astype(np.float32)
        sort_order = np.argsort(coo.row, kind="stable")
        doc_idx_sorted = torch.from_numpy(coo.row[sort_order].astype(np.int64)).to(dev)
        word_idx_sorted = torch.from_numpy(coo.col[sort_order].astype(np.int64)).to(dev)
        counts_sorted = torch.from_numpy(coo.data[sort_order]).to(dev)

        # indptr[d] = start of doc d in the sorted COO arrays
        indptr = torch.zeros(D + 1, dtype=torch.int64, device=dev)
        indptr.scatter_add_(
            0,
            (doc_idx_sorted + 1).clamp(max=D),
            torch.ones(len(doc_idx_sorted), dtype=torch.int64, device=dev),
        )
        indptr = indptr.cumsum(0)

        # ── Initialise beta via spectral method, then blend with uniform ────────
        if self.verbose:
            print("  Spectral initialisation…")
        beta_spec = spectral_init_beta(
            count_matrix, vocab, K, top_p=min(2000, W), seed=self.seed, device=dev
        )  # (K × W) log-probs
        # Blend 50/50 with uniform to smooth spectral peaks and stabilise EM.
        # Pure spectral can produce very peaked topics that cause Newton steps
        # to overshoot in the first few EM iterations.
        beta_uniform = torch.full((K, W), -float(np.log(W)), device=dev)
        log_half = float(np.log(0.5))
        beta_log = torch.logaddexp(
            beta_spec + log_half,
            beta_uniform + log_half,
        )  # log(0.5*exp(spec) + 0.5*uniform), still sums to 1 per row

        # ── Variational parameters ────────────────────────────────────────────
        # Warm-start mu from the spectral beta's implied document-topic affinities.
        # score[d, k] = Σ_w count[d,w] * beta_log[k,w]  (unnorm doc-topic affinity)
        # theta_init = softmax(score);  mu[d,k] = log θ_k - log θ_K   (for k < K)
        # This avoids the mode-collapse that occurs when mu=0 (uniform θ) causes
        # a dominant spectral topic to absorb all documents in the first Newton pass.
        with torch.no_grad():
            score = torch.zeros(D, K, device=dev)
            for batch_start in range(0, D, self.batch_size):
                batch_end = min(batch_start + self.batch_size, D)
                ptr_s = indptr[batch_start].item()
                ptr_e = indptr[batch_end].item()
                if ptr_s == ptr_e:
                    continue
                b_word = word_idx_sorted[ptr_s:ptr_e]
                b_cnt  = counts_sorted[ptr_s:ptr_e]
                b_dloc = doc_idx_sorted[ptr_s:ptr_e] - batch_start
                bw     = beta_log[:, b_word].T          # (N_b × K)
                score[batch_start:batch_end].scatter_add_(
                    0,
                    b_dloc.unsqueeze(1).expand(-1, K),
                    bw * b_cnt.unsqueeze(1),
                )
            theta_init = F.softmax(score, dim=1)          # (D × K)
            theta_init = theta_init.clamp(min=1e-6)       # avoid log(0)
            log_theta  = torch.log(theta_init)            # (D × K)
            mu_init    = log_theta[:, :K-1] - log_theta[:, K-1:K]  # (D × K-1)
        # Clamp warm-start logits to ±2.  Unclamped mu_init can reach ±7
        # for documents that strongly match one spectral topic, producing
        # near-one-hot phi in the first E-step → hyper-peaked beta after
        # the M-step → explosive Newton gradients in all subsequent steps.
        # ±2 corresponds to a max per-topic weight of ≈0.35, keeping the
        # initial assignments soft enough for EM to improve from.
        mu     = mu_init.clamp(-2.0, 2.0)
        nu_sq  = torch.ones(D, K - 1, device=dev)
        gamma_cov  = torch.zeros(p, K - 1, device=dev)
        sigma_diag = torch.full((K - 1,), self.sigma_prior, device=dev)

        prev_elbo: float | None = None
        best_elbo: float = -float("inf")
        best_state: dict | None = None
        no_improve_count: int = 0
        PATIENCE = 15  # stop if no improvement for this many consecutive iters

        # ── EM loop ───────────────────────────────────────────────────────────
        for em_it in range(1, self.max_em_its + 1):
            # ── E-step ────────────────────────────────────────────────────────
            mu, nu_sq, beta_num = self._estep(
                doc_idx_sorted, word_idx_sorted, counts_sorted, indptr,
                n_d, X, mu, nu_sq, gamma_cov, sigma_diag, beta_log,
                D, W,
            )

            # ── ELBO with pre-M-step parameters ───────────────────────────────
            # q_t was optimised against (beta_{t-1}, gamma_{t-1}, sigma_{t-1}).
            # Evaluating ELBO(q_t, theta_{t-1}) here gives a quantity that is
            # non-decreasing when the E-step improves q — the correct monotone
            # diagnostic.  Computing ELBO *after* the M-step mixes q_t with
            # theta_t (for which q_t was never optimised) and breaks monotonicity.
            elbo = self._compute_elbo(
                mu, nu_sq,
                doc_idx_sorted, word_idx_sorted, counts_sorted, indptr,
                X, gamma_cov, sigma_diag, beta_log, D, W,
            )

            self.elbo_history.append(elbo)
            if self.verbose:
                print(f"  EM {em_it:4d}: ELBO = {elbo:.4f}")

            # ── Convergence checks (before M-step so comparison is consistent) ─
            converged = False
            if prev_elbo is not None:
                rel_change = abs((elbo - prev_elbo) / (abs(prev_elbo) + 1e-10))
                if rel_change < self.em_convergence:
                    if self.verbose:
                        print(f"  Converged at iteration {em_it} (delta={rel_change:.2e})")
                    converged = True

            # ── M-step ────────────────────────────────────────────────────────
            # 1/K Dirichlet smoothing on beta: matches R's STM default and
            # prevents topics from collapsing to a handful of words after only
            # a few EM steps, which would otherwise cause explosive gradients
            # in the following E-step's Newton loop.
            beta_log = F.log_softmax(beta_num + 1.0 / K, dim=1)  # (K × W)
            gamma_cov, sigma_diag = self._mstep_prevalence(mu, X)

            # ── Track best consistent state (q_t, theta_t) ───────────────────
            # Save mu/nu_sq from E-step alongside the just-computed M-step
            # parameters so the stored state is internally consistent.
            if elbo > best_elbo:
                best_elbo = elbo
                best_state = {
                    "mu": mu.clone(), "nu_sq": nu_sq.clone(),
                    "beta_log": beta_log.clone(),
                    "gamma_cov": gamma_cov.clone(),
                    "sigma_diag": sigma_diag.clone(),
                }
                no_improve_count = 0
            else:
                no_improve_count += 1

            if converged:
                break
            if no_improve_count >= PATIENCE:
                if self.verbose:
                    print(f"  Early stop: no ELBO improvement for {PATIENCE} iterations.")
                break
            prev_elbo = elbo

        # ── Restore best parameters found during EM ───────────────────────────
        assert best_state is not None
        self._beta_log    = best_state["beta_log"]
        self._mu          = best_state["mu"]
        self._nu_sq       = best_state["nu_sq"]
        self._gamma_cov   = best_state["gamma_cov"]
        self._sigma_diag  = best_state["sigma_diag"]

        if self.verbose:
            print(f"  Fit complete. {len(self.elbo_history)} EM iterations. "
                  f"Best ELBO = {best_elbo:.4f}")

        return self

    # ── E-step ────────────────────────────────────────────────────────────────

    def _estep(
        self,
        doc_idx_sorted: torch.Tensor,   # (N,) document index for each word position
        word_idx_sorted: torch.Tensor,  # (N,) word index for each word position
        counts_sorted: torch.Tensor,    # (N,) count for each word position
        indptr: torch.Tensor,           # (D+1,) CSR-like pointers
        n_d: torch.Tensor,              # (D,) doc lengths
        X: torch.Tensor,                # (D × p)
        mu: torch.Tensor,               # (D × K-1)
        nu_sq: torch.Tensor,            # (D × K-1)
        gamma_cov: torch.Tensor,        # (p × K-1)
        sigma_diag: torch.Tensor,       # (K-1,)
        beta_log: torch.Tensor,         # (K × W)
        D: int,
        W: int,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Full E-step over all documents processed in batches.

        For each batch:
          1. Extract word positions from sorted COO
          2. Compute prior mean m_batch = X_batch @ gamma_cov
          3. Newton loop (newton_its steps):
             a. theta = softmax([mu_batch; 0])
             b. log_phi[n,k] = log_theta[doc_local[n],k] + beta_log[k, word[n]]
             c. phi = softmax(log_phi, dim=1)
             d. phi_marginal[d,k] = scatter_add(counts * phi, doc_local, dim=0)
             e. grad[k] = phi_marg[k] - n_d * theta[k] - (mu[k] - m[k]) / sigma[k]
             f. hess[k] = -n_d * theta[k]*(1-theta[k]) - 1/sigma[k]   (clamped < 0)
             g. mu -= grad / hess
             h. nu_sq = -0.5 / hess
          4. Final forward pass at converged mu_b → accumulate beta numerator

        Returns: updated mu, nu_sq, beta_num (K×W)
        ELBO is computed separately via _compute_elbo() after M-step.
        """
        K = self.K
        dev = self.device
        batch_size = self.batch_size

        mu_new = mu.clone()
        nu_sq_new = nu_sq.clone()
        beta_num = torch.zeros(K, W, device=dev)

        # Process docs in contiguous batches (they're sorted in COO by doc_idx)
        for batch_start in range(0, D, batch_size):
            batch_end = min(batch_start + batch_size, D)
            B = batch_end - batch_start

            # ── Extract batch word data from sorted COO ────────────────────
            ptr_start = indptr[batch_start].item()
            ptr_end = indptr[batch_end].item()

            if ptr_start == ptr_end:
                # All documents in this batch are empty — skip
                continue

            b_word_idx = word_idx_sorted[ptr_start:ptr_end]  # (N_b,)
            b_counts = counts_sorted[ptr_start:ptr_end]       # (N_b,)
            # Local document index within the batch (0..B-1)
            b_doc_local = doc_idx_sorted[ptr_start:ptr_end] - batch_start  # (N_b,)

            # ── Prior mean ────────────────────────────────────────────────
            X_batch = X[batch_start:batch_end, :]    # (B × p)
            m_batch = X_batch @ gamma_cov             # (B × K-1)

            # ── Batch variational parameters ──────────────────────────────
            mu_b = mu_new[batch_start:batch_end, :].clone()  # (B × K-1)

            # ── beta_log lookup for this batch's words (constant) ─────────
            # beta_word[n, k] = beta_log[k, word_n]  →  (N_b × K)
            beta_word = beta_log[:, b_word_idx].T  # (N_b × K)

            # ── Newton iterations (full K-1 × K-1 Hessian per document) ────
            # Using the full Hessian avoids instability from the diagonal
            # approximation (which ignores large cross-topic terms early in EM).
            n_d_b = n_d[batch_start:batch_end].unsqueeze(1)  # (B × 1)
            Km1 = K - 1
            I_km1 = torch.eye(Km1, device=dev)  # for regularisation

            for _ in range(self.newton_its):
                eta = torch.cat(
                    [mu_b, torch.zeros(B, 1, device=dev)], dim=1
                )  # (B × K)
                theta = F.softmax(eta, dim=1)  # (B × K)

                log_theta_flat = torch.log(theta + 1e-12)[b_doc_local, :]  # (N_b × K)
                log_phi = log_theta_flat + beta_word  # (N_b × K)
                log_phi = log_phi - log_phi.logsumexp(dim=1, keepdim=True)
                phi = log_phi.exp()

                phi_weighted = phi * b_counts.unsqueeze(1)  # (N_b × K)
                phi_marg = torch.zeros(B, K, device=dev)
                phi_marg.scatter_add_(
                    0,
                    b_doc_local.unsqueeze(1).expand(-1, K),
                    phi_weighted,
                )  # (B × K)

                theta_km1 = theta[:, :Km1]      # (B × Km1)
                phi_km1   = phi_marg[:, :Km1]   # (B × Km1)

                # Gradient of ELBO w.r.t. mu_b  (B × Km1)
                grad = (
                    phi_km1
                    - n_d_b * theta_km1
                    - (mu_b - m_batch) / sigma_diag.unsqueeze(0)
                )

                # Full Hessian: H[b,k,l] = -n_d[b]*(theta_k*delta_{kl} - theta_k*theta_l)
                #                         - delta_{kl}/sigma_k
                # = n_d[b] * (outer(theta_km1, theta_km1) - diag(theta_km1))
                #   - diag(1/sigma_diag)
                outer = torch.einsum('bi,bj->bij', theta_km1, theta_km1)   # (B×Km1×Km1)
                diag_t = torch.diag_embed(theta_km1)                        # (B×Km1×Km1)
                H = n_d_b.unsqueeze(2) * (outer - diag_t) \
                    - (1.0 / sigma_diag).unsqueeze(0).unsqueeze(0) * I_km1  # (B×Km1×Km1)
                # H is negative semi-definite; -H is positive semi-definite.
                # Add small ridge to -H for numerical stability.
                neg_H = -H + 1e-5 * I_km1   # (B×Km1×Km1) PD

                # Solve neg_H @ delta = grad  →  delta = (-H)^{-1} g = H^{-1}(-g)
                # Newton step for MAX: mu += H^{-1} g = (neg_H)^{-1} g
                delta = torch.linalg.solve(
                    neg_H, grad.unsqueeze(-1)
                ).squeeze(-1)  # (B × Km1)

                # Clamp step to ±1.0 in logit space to prevent Newton overshoot
                # when beta is peaked (concentrated topics create large gradients).
                mu_b = mu_b + delta.clamp(-1.0, 1.0)

            # Diagonal of nu_sq from diagonal Hessian (used for KL only)
            hess_diag = (
                -n_d_b * theta_km1 * (1.0 - theta_km1)
                - 1.0 / sigma_diag.unsqueeze(0)
            ).clamp(max=-1e-6)
            nu_sq_b = -0.5 / hess_diag  # (B × Km1), positive

            # ── Store updated variational params ──────────────────────────
            mu_new[batch_start:batch_end, :] = mu_b
            nu_sq_new[batch_start:batch_end, :] = nu_sq_b

            # ── Final forward pass: accumulate beta numerator ─────────────
            # Use the converged mu_b to get phi consistent with updated mu.
            eta_f = torch.cat([mu_b, torch.zeros(B, 1, device=dev)], dim=1)
            theta_f = F.softmax(eta_f, dim=1)
            log_theta_f = torch.log(theta_f + 1e-12)[b_doc_local, :]  # (N_b × K)
            log_phi_f = log_theta_f + beta_word
            log_phi_f = log_phi_f - log_phi_f.logsumexp(dim=1, keepdim=True)
            phi_f = log_phi_f.exp()
            phi_weighted_f = phi_f * b_counts.unsqueeze(1)  # (N_b × K)

            idx_expand = b_word_idx.unsqueeze(0).expand(K, -1)   # (K × N_b)
            beta_num.scatter_add_(1, idx_expand, phi_weighted_f.T)

        return mu_new, nu_sq_new, beta_num

    # ── ELBO computation (called after M-step for monotone monitoring) ─────────

    def _compute_elbo(
        self,
        mu: torch.Tensor,               # (D × K-1)
        nu_sq: torch.Tensor,            # (D × K-1)
        doc_idx_sorted: torch.Tensor,
        word_idx_sorted: torch.Tensor,
        counts_sorted: torch.Tensor,
        indptr: torch.Tensor,
        X: torch.Tensor,                # (D × p)
        gamma_cov: torch.Tensor,        # (p × K-1) — UPDATED
        sigma_diag: torch.Tensor,       # (K-1,)    — UPDATED
        beta_log: torch.Tensor,         # (K × W)   — UPDATED
        D: int,
        W: int,
    ) -> float:
        """
        Compute ELBO(q_t, theta_t) where both q and theta are from the same
        iteration (q = current mu/nu_sq, theta = just-updated beta/gamma/sigma).

        This is a lightweight forward pass: no Newton loop, just logsumexp per
        word position for the word log-likelihood, plus the KL formula.
        """
        K = self.K
        dev = self.device
        batch_size = self.batch_size

        total_word_ll: float = 0.0
        total_kl: float = 0.0

        for batch_start in range(0, D, batch_size):
            batch_end = min(batch_start + batch_size, D)
            B = batch_end - batch_start

            ptr_start = indptr[batch_start].item()
            ptr_end = indptr[batch_end].item()

            mu_b = mu[batch_start:batch_end, :]      # (B × K-1)
            nu_sq_b = nu_sq[batch_start:batch_end, :]  # (B × K-1)
            m_b = X[batch_start:batch_end, :] @ gamma_cov  # (B × K-1)

            # KL(q || p) with diagonal Gaussian q = N(mu, diag(nu_sq)),
            #                                   p = N(m,  diag(sigma))
            diff = mu_b - m_b
            kl = 0.5 * (
                (diff ** 2 / sigma_diag).sum(dim=1)
                + (nu_sq_b / sigma_diag).sum(dim=1)
                - (K - 1)
                + sigma_diag.log().sum()
                - (nu_sq_b + 1e-12).log().sum(dim=1)
            )  # (B,)
            total_kl += kl.sum().item()

            if ptr_start == ptr_end:
                continue  # empty-doc batch — KL still counted (0 word_ll)

            b_word_idx = word_idx_sorted[ptr_start:ptr_end]
            b_counts = counts_sorted[ptr_start:ptr_end]
            b_doc_local = doc_idx_sorted[ptr_start:ptr_end] - batch_start

            beta_word = beta_log[:, b_word_idx].T  # (N_b × K)

            eta_b = torch.cat([mu_b, torch.zeros(B, 1, device=dev)], dim=1)
            theta_b = F.softmax(eta_b, dim=1)  # (B × K)
            log_theta_flat = torch.log(theta_b + 1e-12)[b_doc_local, :]  # (N_b × K)

            # log p(w | theta, beta) = log Σ_k theta_k * beta_{kw}
            log_z = (log_theta_flat + beta_word).logsumexp(dim=1)  # (N_b,)
            total_word_ll += (b_counts * log_z).sum().item()

        return total_word_ll - total_kl

    # ── M-step prevalence ─────────────────────────────────────────────────────

    def _mstep_prevalence(
        self,
        mu: torch.Tensor,      # (D × K-1)
        X: torch.Tensor,       # (D × p)
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Update covariate regression coefficients γ and prior variance Σ.

        γ = (X'X)^{-1} X' μ   (multivariate OLS)
        Σ = diag( mean_d [(μ_d - X_d γ)^2] )
        """
        # Solve via least-squares for numerical stability
        gamma_cov = torch.linalg.lstsq(X, mu).solution  # (p × K-1)

        residuals = mu - X @ gamma_cov  # (D × K-1)
        # Mix empirical variance with the prior to prevent sigma collapsing to 0.
        # When OLS perfectly fits mu (R²≈1), residuals → 0 → sigma → 0 → tight prior
        # → KL explodes in the next E-step. Adding the sigma_prior as a floor via
        # a Bayesian mixture prevents this collapse while still allowing shrinkage.
        emp_var = (residuals ** 2).mean(dim=0)               # (K-1,)
        sigma_diag = (emp_var + self.sigma_prior).clamp(min=0.1) / 2.0  # (K-1,)

        return gamma_cov, sigma_diag

    # ── Public accessors ──────────────────────────────────────────────────────

    @property
    def theta(self) -> np.ndarray:
        """(D × K) document-topic proportion matrix."""
        if self._mu is None:
            raise RuntimeError("Call fit() first.")
        K = self.K
        dev = self.device
        mu = self._mu
        eta = torch.cat([mu, torch.zeros(mu.shape[0], 1, device=dev)], dim=1)
        return F.softmax(eta, dim=1).detach().cpu().numpy()

    @property
    def beta(self) -> np.ndarray:
        """(K × W) topic-word probability matrix."""
        if self._beta_log is None:
            raise RuntimeError("Call fit() first.")
        return self._beta_log.exp().detach().cpu().numpy()

    @property
    def gamma(self) -> np.ndarray:
        """(p × K-1) covariate coefficient matrix."""
        if self._gamma_cov is None:
            raise RuntimeError("Call fit() first.")
        return self._gamma_cov.detach().cpu().numpy()

    @property
    def sigma(self) -> np.ndarray:
        """(K-1,) prior variance diagonal."""
        if self._sigma_diag is None:
            raise RuntimeError("Call fit() first.")
        return self._sigma_diag.detach().cpu().numpy()

    @property
    def vocab(self) -> list[str]:
        return self._vocab

    @property
    def design_col_names(self) -> list[str]:
        return self._design_col_names

    def get_elbo(self) -> float:
        """Return the most recent ELBO value."""
        return self.elbo_history[-1] if self.elbo_history else float("nan")
