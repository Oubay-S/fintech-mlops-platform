# Dataset Decision — PaySim

**Date:** 21 October 2026 · **Owner:** ML Training role · **Status:** decided by the team

## Decision

Use **PaySim** (*Synthetic Financial Datasets For Fraud Detection*) as the project dataset. The application domain remains the wallet-transfer platform described in `APPLICATION_CONCEPTION_PLAN.md` (Option A).

## Why

- Team decision on 21 Oct 2026 (after the Option A vs Option B comparison; the IEEE-CIS plan is archived in the project root's `archive/` folder).
- The dataset's columns map 1:1 to the application's `/predict` contract: `type`, `amount`, sender/receiver balances before and after.
- Clean structure: 6,362,620 rows, 11 named columns, **0 missing values**, **0 duplicate rows**.
- Small enough to iterate fast; full Parquet cache is ~210 MB.

## Known limitations (must appear in the report)

1. **Near-deterministic label:** `amount == oldbalanceOrg` on TRANSFER/CASH_OUT selects 8,034 rows that are 100% fraud and cover 97.82% of all frauds. Expect near-perfect model scores.
2. **Broken balances:** the accounting identity holds on only ~20% of rows.
3. **No sender history:** 99.85% of `nameOrig` accounts appear once.
4. **Single fraud pattern:** account-draining takeover in two transaction types only.

## Mitigations

- **Restricted ablation:** retrain without the new-balance fields and the derived zero/equality indicators; report the performance drop.
- **Decision-level evaluation** against the R1–R6 policy (including the R5 high-amount review rule).
- **Calibration + conformal prediction** still implemented; expected few genuinely uncertain cases, reported as a finding.
- **Honest framing:** results demonstrate methodology on a controlled simulator, not real-world fraud-detection capability.

## References

- Kaggle: *Synthetic Financial Datasets For Fraud Detection* (`ealaxi/paysim1`).
- E. A. Lopez-Rojas, A. Elmir, S. Axelsson. *PaySim: A financial mobile money simulator for fraud detection.* EMSS 2016.
- Detailed profile: `DATASET_PROFILE.md`; contract: `FEATURE_LIST_V1.md`.
