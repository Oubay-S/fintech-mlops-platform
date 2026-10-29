# Feature List v1.2 — `/predict` Contract (PaySim / Wallet-Transfer Domain)

**Owner:** ML Training role · **Status:** Frozen v1.2 for consumers (Risk service, ML Serving) · **Date:** 29 October 2026
**Companion:** `APPLICATION_CONCEPTION_PLAN V2.2.md` (latest, 28 October 2026), §11.2, §11.6, §11.7, §17.1, §24.2.
**Supersedes:** v1.1 (27 October 2026). Changes: aligned with V2.2 — initial balance 1,000,000 / max transfer 10,000,000 / provisional R5 500,000; `CASH_OUT` core; all five `type` values accepted by ML Serving; serving-consistent balance check; temporal/destination robustness.
**Repo copy:** committed copy of the frozen contract; the working copy and the Role 4 conception audit live at the project root.

---

## 1. Design rule

The application sends **six raw fields** per transfer (exactly the `§17.1` payload). The ML service computes the derived ratios internally, using the shared preprocessing module (same code for training and serving). No account IDs, no `step`, no `isFlaggedFraud`, no post-decision information.

PaySim measured facts that shape this contract (see `DATASET_PROFILE.md`):

- 6,362,620 transactions; 8,213 frauds (0.129%); no missing values; no duplicate rows.
- Fraud only in `TRANSFER` (0.769%) and `CASH_OUT` (0.184%).
- **Near-deterministic label:** `amount == oldbalanceOrg` on TRANSFER/CASH_OUT selects 8,034 rows that are **100% fraud** and cover **97.82%** of all frauds.

---

## 2. Raw features provided by the application

| API field | Type | Definition | Dataset source | Application source | Required |
|---|---|---|---|---|---|
| `type` | enum: `TRANSFER`, `CASH_OUT`, `CASH_IN`, `PAYMENT`, `DEBIT` | Transaction type. V2.2 makes `CASH_OUT` **core** (withdraw cash to a cash agent); the app creates `TRANSFER` and `CASH_OUT`. `CASH_IN`, `PAYMENT`, `DEBIT` are not offered. ML Serving **accepts all five** (confirmed in V2.2 §17.1); the model is evaluated on the in-scope `TRANSFER` + `CASH_OUT` set. | `type` | transfer type | **M** |
| `amount` | decimal | Transfer amount | `amount` | `transfers.amount` | **M** |
| `sender_old_balance` | decimal | Sender wallet balance before the transfer | `oldbalanceOrg` | sender wallet balance | **M** |
| `sender_new_balance` | decimal | Sender wallet balance after the transfer (computed by the app before execution) | `newbalanceOrig` | sender balance − amount | **M** |
| `receiver_old_balance` | decimal | Receiver wallet balance before the transfer | `oldbalanceDest` | receiver wallet balance | **M** |
| `receiver_new_balance` | decimal | Receiver wallet balance after the transfer (computed by the app) | `newbalanceDest` | receiver balance + amount | **M** |

All six are mandatory; missing values are treated as an invalid request (unlike IEEE-CIS, PaySim has no missing data, so there is no "null category" policy).

---

## 3. Derived features (computed inside the ML service)

These are **not sent by the app**; the shared preprocessing module derives them from the six fields:

| Feature | Definition | Purpose |
|---|---|---|
| `balance_drain_ratio` | `amount / (sender_old_balance + 1)` | Captures the drain pattern |
| `receiver_gain_ratio` | `amount / (receiver_old_balance + 1)` | Captures the recipient-side effect |
| `sender_zero_after` | `sender_new_balance == 0` | Leak indicator (see §6) |
| `amount_equals_old_balance` | `amount == sender_old_balance` | Leak indicator (the trivial rule) |

Under the app's computed `sender_new_balance = sender_old_balance - amount`, `sender_zero_after` is equivalent to `amount_equals_old_balance` for `amount <= old`; the two flags are collinear and are kept for parity with the PaySim columns. The `+1` in both ratios is a zero-division guard, not a calibrated quantity.

The model pipeline applies the same definitions at training and serving; a parity test checks identical outputs for identical inputs.

---

## 4. Excluded features (and why)

| Excluded | Reason |
|---|---|
| `nameOrig`, `nameDest` | Account IDs; 99.85% of originators appear once, so they add no usable history; privacy risk |
| `step` | Not part of the application contract (the app has timestamps, but PaySim's step is relative simulation time and is not comparable) |
| `isFlaggedFraud` | Rule output — using it would leak the label |
| Receiver wallet age, recent transfer counts (mentioned as derivables in the backend's §24.2) | Not trainable on PaySim: no wallet age column, and originators are almost all unique. Documented deviation for the team |
| Any post-decision information | Leakage |

---

## 5. Proposed `/predict` payload (v1.0)

```json
{
  "schema_version": "1.0",
  "request_id": "uuid",
  "features": {
    "type": "TRANSFER",
    "amount": 1250.50,
    "sender_old_balance": 5000.00,
    "sender_new_balance": 3749.50,
    "receiver_old_balance": 100.00,
    "receiver_new_balance": 1350.50
  }
}
```

Amount fields are **JSON numbers** in this internal contract (float64). The public/domain API serializes amounts as strings (`DECIMAL(19,2)`); Risk converts the decimal strings to numbers before calling `/predict`. This boundary must be explicit in the conception and the OpenAPI (see the Role 4 conception audit, B-01).

The response contract is unchanged (backend conception §17.2): `schema_version`, `request_id` (echoed), `action` (suggestion only), `fraud_probability`, `uncertainty` (conformal prediction set, confidence level, score), `model` (name `fraud-detector`, version, stage), optional explanations, `inference_ms`.

---

## 6. Leakage and the trivial-rule problem (explicit policy)

The measured rule is a property of the simulator, not of a good model:

- `amount == oldbalanceOrg` on TRANSFER/CASH_OUT → **8,034 rows, 100% fraud, 97.82% of all frauds**.
- `newbalanceOrig == 0` → 98.1% fraud vs 56.7% non-fraud.
- Balance arithmetic is inconsistent on ~80% of rows.

**Rule baseline (mandatory in the report):** predicting fraud exactly when `amount == sender_old_balance` on TRANSFER/CASH_OUT gives **precision 1.000, recall 0.9782**. This is a baseline row in the benchmark, not a footnote.

**Hard subset (mandatory in the report):** on the 32 rule-negative frauds in the test set, the baseline model gets **recall 0.594** (19/32) with the original PaySim balances. When the test set is made **serving-consistent** (`sender_new_balance = sender_old_balance - amount`, `receiver_new_balance = receiver_old_balance + amount`), the headline ROC-AUC is unchanged (0.9992) but the hard-subset recall falls to **0.281** (9/32). The app computes both new balances, so the serving-consistent number is the honest one; the report must show both and the model should be retrained/evaluated on the serving-consistent view.

**Training policy:**

1. **Primary model** — trained on the six contract fields + the four derived ratios. Expected near-ceiling metrics. This is the model served (it matches the production contract).
2. **Restricted ablation** — the same pipeline with `sender_new_balance`, `receiver_new_balance`, `sender_zero_after`, `amount_equals_old_balance` removed. Important: this protocol still contains `amount` and `sender_old_balance`, which define the rule; a tree can approximate the equality boundary, so the LR-only probe is not sufficient. Add a **rule-blind** protocol (drop `sender_old_balance` or evaluate on rule-negative rows) and report the hard-subset table for every algorithm.
3. **In-scope evaluation** — primary metrics on `TRANSFER` + `CASH_OUT` (the traffic the app serves); all-five-types results are secondary. If `CASH_OUT` is not implemented, use `TRANSFER` only.
4. `isFlaggedFraud` is never used.
5. The report states clearly: *the near-perfect scores reflect the simulator's structure (single injected fraud pattern), not real-world fraud-detection capability*.
6. **Full-drain product note:** the contract model gives p ≈ 0.99999 to any full-balance transfer. V2.2's test strategy uses "whole balance to a new receiver" as the `REJECTED` demo case, and R3 rejects `{fraud}`, so a legitimate full drain is auto-rejected. The product must either restrict full-balance transfers, route full drains to review, serve the restricted model, or document the limitation (Role 4 conception audit, B-03; V2.2 does not resolve the legitimate-user case).

---

## 7. When `/predict` is called

Per the latest conception (§11.6 — one score at creation; no preview, no fingerprint, no freshness logic):

| Moment | Call | Notes |
|---|---|---|
| Direct transfer | One `/predict` at transfer creation | After Tx1 validation/hold; Risk is idempotent per transfer ID |
| Accepted payment request | One `/predict` when the transfer is created at accept | Payment requests are unscored before accept |
| Payer opens a payment request | No call | No preview, no risk information shown |
| Review decision by analyst | No call | The stored decision is used |
| Notifications / audit events | No call | — |
| Retry / stuck-transfer reconciler | No new ML call | Risk returns the stored decision for the same transfer ID |

There is no chargeback event in the wallet application (PaySim has no such concept).

**Retries:** a replayed request with the same `Idempotency-Key` returns the stored result; the Risk decision is idempotent per transfer ID, so a reconciler retry does not create a second ML call.

---

## 8. Missing values, validation and versioning

- All six fields are required and validated (numeric ranges, `sender_new_balance ≥ 0`, `receiver_new_balance ≥ 0`, probability response in [0, 1]).
- `sender_new_balance = sender_old_balance - amount` and `receiver_new_balance = receiver_old_balance + amount` are **computed by the app** before the call. The model must be evaluated on this serving-consistent arithmetic, not only on PaySim's inconsistent balances.
- Amounts are strings in the public/domain API (`DECIMAL(19,2)`) and numbers in the internal `/predict` contract (float64). Risk performs the conversion; the contract must state it explicitly.
- A contract change (new field or semantic change) bumps the `schema_version` and is announced one week ahead.
- The shared preprocessing module is the single implementation of §3; training and serving import the same code.

## 9. Evaluation protocol (summary; details in `ML_TRAINING_PLAN.md`)

- **Scale (V2.2):** initial balance **1,000,000.00**, `app.transfer.max-amount` **10,000,000.00**; raw PaySim magnitudes, **no rescale**. App-valid p99 is 968,420.
- **Primary metrics on the in-scope, app-valid subset**: `TRANSFER` + `CASH_OUT` (both core in V2.2), `amount > 0`, `amount <= sender_old_balance`. The app rejects the rest before ML.
- **The app-valid population is not the full PaySim population.** `available >= amount` removes ~90% of PaySim rows before ML; the app-valid test set is 56,349 rows with 1,636 frauds (**2.903%**), not 0.297%. Calibration and the review-rate target must use this prevalence.
- **Time-based holdout + destination-disjoint holdout.** Sender-disjoint is trivial on PaySim (99.85% of senders appear once); destination-disjoint is the meaningful generalization check. Implemented: temporal fraud 1.753% → 7.361%, review 1.093%, all 4,237 frauds caught; destination 0 overlap / 40,353 unseen receivers, review 1.329%, all 1,608 caught (`robustness_report.md`).
- **Class-conditional (Mondrian) conformal** on the app-valid set at **99%**. R5 is **provisional 500,000** (V2.2) and has been validated on XGBoost: at 99% + 500,000, **MODEL_UNCERTAIN 0.903% + AMOUNT_HIGH 0.451% → 1.354% review**, all 1,634 test frauds caught (0 missed), 0 legitimate rejected. The 5%-budget alternative **324,610** gives **3.906%** (0.903% + 3.003%), same frauds. Both are ≤5%; 500,000 is conservative, 324,610 uses more of the budget. Coverage: legit 99.10%, fraud 98.96%; the 17 uncovered frauds are R4 review (no auto-approval).
- **Report the rule baseline and the rule-negative hard subset** for every model, plus the serving-consistent variant. On the app-valid set the rule baseline is precision 1.000, recall 0.9829; the hard subset is 28 frauds, with recall 0.679 (raw) / 0.321 (serving-consistent). The headline ROC-AUC is a dataset property, not a model achievement.
- **Type:** ML Serving accepts all five values (V2.2 confirmed); the app sends `TRANSFER` + `CASH_OUT`; the model is evaluated on the two-type in-scope set.
- **Full-drain policy:** V2.2's test strategy uses a whole-balance transfer as the `REJECTED` case; the legitimate full-drain UX is still open. Decide before the demo (route to review, restrict, or document).

---

*Authoritative contract for the `/predict` payload in the PaySim variant. Consumed by Risk (producer) and ML Serving (forwarder); derived features are internal to the ML service.*
