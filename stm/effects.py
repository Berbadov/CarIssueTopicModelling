"""
stm/effects.py
──────────────
estimateEffect equivalent: compute topic prevalence per covariate level.

Mirrors R's estimateEffect(formula, stmobj, metadata, uncertainty="Global").
For each level of a categorical covariate, we predict the mean topic proportion
when that covariate is set to that level and all other covariates are held at
their observed means/modes.

Simulation-based CIs: perturb γ by sampling from its posterior approximation
N(γ, (X'X)^{-1} ⊗ diag(σ)), repeat n_sims times, report 2.5th/97.5th pctiles.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import scipy.linalg as la
import torch
import torch.nn.functional as F


class EffectEstimator:
    """
    Estimate the effect of a categorical covariate on topic prevalence.

    Usage:
        est = EffectEstimator(stm_model, metadata)
        effects_df = est.estimate("engine_group")
    """

    def __init__(
        self,
        stm_model,          # fitted STM instance
        metadata: pd.DataFrame,
        n_sims: int = 500,
        seed: int = 42,
    ):
        self.stm = stm_model
        self.metadata = metadata.reset_index(drop=True)
        self.n_sims = n_sims
        self.rng = np.random.default_rng(seed)

        # Pull fitted params to CPU numpy
        self._gamma = stm_model.gamma           # (p × K-1)
        self._sigma = stm_model.sigma           # (K-1,)
        self._X = stm_model._X.detach().cpu().numpy()  # (D × p)
        self._K = stm_model.K
        self._col_names = stm_model.design_col_names   # list[str]

    # ── Public API ────────────────────────────────────────────────────────────

    def estimate(
        self,
        covariate: str,
        topics: list[int] | None = None,
    ) -> pd.DataFrame:
        """
        Estimate expected topic proportion for each level of `covariate`.

        Returns DataFrame with columns:
            topic, {covariate}, estimate, ci_lower, ci_upper, significant
        where `significant` = CI does not straddle zero (relative to mean).
        """
        if covariate not in self.metadata.columns:
            raise ValueError(f"Covariate '{covariate}' not found in metadata.")

        K = self._K
        topics_use = list(topics) if topics else list(range(1, K + 1))

        levels = sorted(self.metadata[covariate].dropna().unique().tolist())

        # Posterior covariance of γ via (X'X)^{-1} ⊗ diag(σ)
        XtX = self._X.T @ self._X  # (p × p)
        try:
            XtX_inv = la.inv(XtX + 1e-6 * np.eye(XtX.shape[0]))
        except la.LinAlgError:
            XtX_inv = la.pinv(XtX)

        rows: list[dict] = []

        for level in levels:
            # Build counterfactual design matrix: set covariate to `level`,
            # all other continuous cols at mean, other categoricals at mode.
            X_cf = self._build_counterfactual(covariate, str(level))  # (D × p)

            # Point estimate: predict theta using current γ
            m_cf = X_cf @ self._gamma              # (D × K-1)
            theta_cf = self._theta_from_mu(m_cf)   # (D × K)
            mean_theta = theta_cf.mean(axis=0)     # (K,)

            # Simulation for CI: perturb γ
            sim_means = np.zeros((self.n_sims, K))
            for s in range(self.n_sims):
                gamma_sim = self._sample_gamma(XtX_inv)  # (p × K-1)
                m_s = X_cf @ gamma_sim
                theta_s = self._theta_from_mu(m_s)
                sim_means[s] = theta_s.mean(axis=0)

            ci_lo = np.percentile(sim_means, 2.5, axis=0)
            ci_hi = np.percentile(sim_means, 97.5, axis=0)

            for topic in topics_use:
                k = topic - 1  # 0-indexed
                rows.append({
                    "topic": topic,
                    covariate: level,
                    "estimate": float(mean_theta[k]),
                    "ci_lower": float(ci_lo[k]),
                    "ci_upper": float(ci_hi[k]),
                    "significant": bool(ci_lo[k] > 0 or ci_hi[k] < 0),
                })

        return pd.DataFrame(rows)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _theta_from_mu(self, mu: np.ndarray) -> np.ndarray:
        """Convert (D × K-1) variational mean to (D × K) topic proportions."""
        D, Km1 = mu.shape
        eta = np.concatenate([mu, np.zeros((D, 1))], axis=1)  # (D × K)
        # Stable softmax
        eta = eta - eta.max(axis=1, keepdims=True)
        exp_eta = np.exp(eta)
        return exp_eta / exp_eta.sum(axis=1, keepdims=True)

    def _build_counterfactual(self, covariate: str, level: str) -> np.ndarray:
        """
        Build design matrix where `covariate` is fixed to `level` and
        all other columns are kept at their observed values.

        Instead of re-running pd.get_dummies (which would drop categories
        absent in the counterfactual data and produce the wrong number of
        columns), we start from the original X matrix and zero-out / set
        the covariate's indicator columns directly.
        """
        X_cf = self._X.copy()  # (D × p), numpy float32

        col = self.metadata[covariate]
        is_numeric = pd.api.types.is_numeric_dtype(col)

        if is_numeric:
            # Find the column index for this covariate name
            col_idx = [i for i, c in enumerate(self._col_names) if c == covariate]
            if col_idx:
                X_cf[:, col_idx[0]] = float(level)
        else:
            # Identify all design-matrix columns belonging to this covariate
            # e.g. covariate="engine_group" → cols "engine_group_MK7", ...
            prefix = covariate + "_"
            cov_col_indices = [
                i for i, c in enumerate(self._col_names) if c.startswith(prefix)
            ]
            if cov_col_indices:
                # Zero out all covariate columns first
                X_cf[:, cov_col_indices] = 0.0
                # Set the target level's indicator column to 1 (if not the dropped baseline)
                target_col = prefix + str(level)
                for i, c in enumerate(self._col_names):
                    if c == target_col:
                        X_cf[:, i] = 1.0
                        break
                # If target_col not found, this is the baseline (dropped) level → all zeros ✓

        return X_cf

    def _reconstruct_formula(self) -> str:
        """Reconstruct a formula string from design column names."""
        # col_names[0] is "(Intercept)"; others are "term" or "term_level"
        # Extract unique term names by stripping dummy suffixes
        terms: list[str] = []
        seen: set[str] = set()
        for col in self._col_names[1:]:
            # "engine_group_MK7" → base term is "engine_group"
            # "mileage_log" → stays as-is
            parts = col.split("_")
            # Find longest prefix that matches a metadata column
            for i in range(len(parts), 0, -1):
                candidate = "_".join(parts[:i])
                if candidate in self.metadata.columns and candidate not in seen:
                    terms.append(candidate)
                    seen.add(candidate)
                    break
        if not terms:
            return "~ 1"
        return "~ " + " + ".join(terms)

    def _sample_gamma(self, XtX_inv: np.ndarray) -> np.ndarray:
        """
        Sample γ from approximate posterior N(γ_hat, (X'X)^{-1} ⊗ diag(σ)).
        Returns (p × K-1) perturbed gamma.
        """
        p = self._gamma.shape[0]
        Km1 = self._gamma.shape[1]
        # For each k, sample p-dimensional perturbation
        sigma_sqrt = np.sqrt(self._sigma)  # (K-1,)
        gamma_sim = self._gamma.copy()
        try:
            L = la.cholesky(XtX_inv, lower=True)
            for k in range(Km1):
                z = self.rng.standard_normal(p)
                gamma_sim[:, k] = self._gamma[:, k] + sigma_sqrt[k] * (L @ z)
        except la.LinAlgError:
            # Fallback: independent noise
            noise = self.rng.standard_normal(self._gamma.shape)
            gamma_sim = self._gamma + 0.01 * noise
        return gamma_sim
