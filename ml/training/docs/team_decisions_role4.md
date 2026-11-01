# Team Decisions — Role 4 Hand-off

**Date:** 1 November 2026 · **Author:** ML Training (Role 4)
**Purpose:** a single page to unblock the demo/integration. Each item states the
question, the evidence, the options, and Role 4's recommendation. Nothing here
requires a model retrain unless explicitly stated.

**How to use it:** spend 20 minutes on the P0 items first; P1 can be settled in
the integration thread; P2 is housekeeping. Owners are named so the decision
does not bounce.

---

## 0. One-page summary

| ID | Decision | Owner | Recommendation | Priority | Team-doc status (1 Nov) |
|---|---|---|---|---|---|
| D1 | R5 high-amount threshold | Backend/Risk + Role 4 | **500,000** for the demo | **P0** | Documented as provisional; formal sign-off open |
| D2 | Full-drain product policy | Backend/Product + Risk | Keep R3 reject + document; review the UX before real users | **P0** | Still open |
| D3 | Amount serialization | Backend + Role 5 | Public API strings; `/predict` numbers (float64) | **P0** | Still contradictory |
| D4 | `request_id` / `transaction_id` | Role 5 + Backend | Use `request_id`; echo it | **P0** | Still open; conventions uses `transaction_id` |
| D5 | Model name | Team | `fraud-detector` (not `fraud-xgb`) | P1 | Conventions uses `fraud-detector-v1.0`; V2.2 still `fraud-xgb` |
| D6 | Uncertainty-score ownership/formula | Role 4 + Role 5 | Role 4 owns formula/q-hats; Role 5 serializes | P1 | Still undefined in team docs |
| D7 | MLflow server/registry ownership | Role 3 + Role 5 | Role 3 hosts the server; Role 5 registers/loads | P1 | V2.2 says shared; conventions says Role 3 |
| D8 | `CASH_OUT` / accepted type set | Backend | Accept all five; app sends TRANSFER + CASH_OUT | P1 | ✅ Resolved (core MUST) |
| D9 | App-valid definition / monetary scale | Backend + Role 4 | Confirm 1M / 10M / `available >= amount` | P1 | ✅ Scale resolved; filter confirmation open |
| D10 | Decision reasons / uncertainty alert | Backend + DevOps + Role 4 | Add `reason`; alert only on `MODEL_UNCERTAIN` | P2 | ✅ Resolved (conventions §6) |
| D11 | Viz point count | Role 4 + Role 5 | 2,000 for the demo; regenerate 5–10k later if needed | P2 | Still open |
| D12 | Audit fields / feature-freeze date | Backend + Role 4 | Store config hash; freeze 20 Dec | P2 | Still open (V2.2 still says 25 Oct) |
| **D13** | **`/predict` request/response shape** | **Backend + Role 5** | **Use V2.2 §17.1/17.2 + OpenAPI; rewrite conventions §4** | **P0** | **New conflict** |
| **D14** | **11 vs 14 transformed features** | **Role 5 + Role 4** | **Revert role5 to five categories (14)** | **P0** | **New critical conflict** |

> **New since the 1 Nov pull:** D13 and D14 are blocking. The main-branch
> V2.2 is byte-identical to the version Role 4 already audited; the rewritten
> `docs/conventions.md` introduced D13, and role5 commit `22d179a` introduced
> D14. See `TEAM_DOCS_DRIFT_REPORT.md` for the full evidence.

---

## P0 — decide before the demo

### D1. R5 high-amount threshold: 500,000 or 324,610?

**Question:** which `risk.policy.high-amount-threshold` do we ship?

**Evidence (final 3.11 model, app-valid test, 99% Mondrian):**

| R5 | Total review | Model-driven (R4) | Rule-driven (R5) | Frauds caught | Legit rejected |
|---:|---:|---:|---:|---:|---:|
| **500,000** | **1.322%** | 0.935% | 0.387% | 1,634/1,634 | 0 |
| 324,610 | 3.751% | 0.935% | 2.816% | 1,634/1,634 | 0 |

- 324,610 is the 5%-budget alternative (3.751% review in the final run); 500,000
  is conservative and leaves headroom for model uncertainty.
- R5 is **rule-driven**: it sends confident-legit, high-amount transfers to
  review. It is not a model-uncertainty threshold.
- The choice does not change the model or the fraud recall; it changes queue
  load only.

**Recommendation:** keep **500,000** for the demo (1.322% review), and revisit
after the first load test if the analyst queue is under-used. If product wants
the queue exercised more, 324,610 is the documented alternative.

**Team-doc status (1 Nov):** V2.2 and `docs/conventions.md` now both document
500,000 as the provisional default, so the implementation default is settled;
the formal “validated” sign-off is still open.

**Impact if changed:** only the R5 config value and the expected review share;
no retrain. Role 5 reads the value from `uncertainty_config.json` or the Risk
policy, not from code.

---

### D2. Full-drain product policy

**Question:** what should happen when a user transfers their **whole balance**?

**Evidence:** the contract model gives any full-balance transfer
`p ≈ 0.99999`, so R3 rejects it. `amount == sender_old_balance` is the PaySim
drain signature (100% fraud, ~98% of frauds). V2.2's demo uses a whole-balance
transfer to a new receiver as the `REJECTED` case. A **legitimate** user who
drains their own wallet is therefore rejected.

**Options:**

1. **Keep R3 reject and document it** — best fraud safety; the demo works as
   written; legitimate full-drain UX is a known limitation.
2. **Route `{fraud}` full drains to `PENDING_REVIEW`** — protects legitimate
   users, but moves the R3 share (2.869%) into the queue. Combined review would
   be ~**4.19%** (2.869 + 0.935 + 0.387), still under the 5% budget; frauds are
   reviewed instead of auto-rejected.
3. **Restrict full-balance transfers in the product** — clear UX, but a product
   change outside ML.
4. **Add a known-beneficiary/own-account exception** — not supported by PaySim;
   needs real data and a new feature; not for this demo.

**Recommendation:** for the demo, **option 1** (keep reject, document the
limitation). Before real users, decide between 1 and 2 with Risk; do not add an
ML exception without data.

**Owner:** Backend/Product + Risk. **Role 4 impact:** none for the demo; option
2 changes only the decision policy, not the model.

**Team-doc status (1 Nov):** `docs/conventions.md` §8 repeats the demo trigger
(whole balance → `REJECTED`); it still does not decide the legitimate-user UX.
The issue is unchanged.

---

### D3. Amount serialization: string or number?

**Question:** does `/predict` send `amount` as a JSON string (`"125.50"`) or a
number (`125.50`)?

**Evidence:** V2.2 §11.1 says amounts are `DECIMAL(19,2)` / `BigDecimal` and
**strings in JSON**; §17.1 and the OpenAPI `TransactionFeatures` use JSON
numbers (`number`, `double`). This is a live contradiction.

**Options:**

1. **Strings at the public/domain API, numbers at `/predict`** — respects the
   money-as-decimal rule for the wallet API, keeps the ML contract/OpenAPI
   unchanged. Role 5 parses to `float64` before `build_features`.
2. **Numbers everywhere** — simplest for ML, but weakens the public money
   contract and may introduce float representation in the wallet API.
3. **Strings everywhere** — consistent money handling, but the OpenAPI and the
   model contract must change; Role 5 parses before the model either way.

**Recommendation:** **option 1**. Amounts are 2-decimal and ≤10,000,000, so
`float64` is exact enough at the ML boundary; the string contract stays at the
wallet edge. Document the boundary in the conception and OpenAPI.

**Owner:** Backend + Role 5. **Role 4 impact:** none (the model consumes
numbers).

**Team-doc status (1 Nov):** `docs/conventions.md` §4 now uses numbers, which
**contradicts V2.2 §11.1 (strings)**. The contradiction is now explicit in two
team documents, not resolved.

---

### D4. `request_id` in the `/predict` response

**Question:** does the response echo `request_id`?

**Evidence:** the §17.2 example omits it; the OpenAPI `PredictResponse` requires
it; §17.3 treats a missing required field as R2 (`SERVICE_DEGRADED`). Without
it, logs/traces cannot correlate a decision to a transfer.

**Options:** echo it (recommended) or remove it from the OpenAPI required list
(not recommended).

**Recommendation:** **echo it**. It is the correlation ID for Risk, audit, and
the review queue.

**Owner:** Role 5 + Backend. **Role 4 impact:** none.

**Team-doc status (1 Nov):** V2.2 still omits the response ID; the new
conventions uses `transaction_id` in both request and response; the OpenAPI
uses `request_id`. Three names/shapes now exist. Pick `request_id` and update
all three.

---

## P1 — settle during integration

### D5. Model name: `fraud-detector` or `fraud-xgb`?

**Evidence:** V2.2 §17.2 example says `fraud-xgb`; the OpenAPI, Role 5 loader,
and local registry use `fraud-detector`.

**Recommendation:** **`fraud-detector`** — algorithm-agnostic, already wired in
the registry and serving config. Update the V2.2 example.

**Owner:** Team. **Impact:** a rename touches the registry, `MODEL_NAME` env,
OpenAPI examples, and the model-info response.

**Team-doc status (1 Nov):** conventions uses `fraud-detector-v1.0`; V2.2 still
says `fraud-xgb`; OpenAPI and the registry use `fraud-detector`. The direction
is clear, but V2.2 is still stale.

---

### D6. Who owns `uncertainty.score` and what is the formula?

**Question:** V2.2 says ML Serving owns the score definition; `docs/conventions.md`
says Role 4 owns the threshold. Which is it?

**What Role 4 delivers:** the conformal calibration (`q_hat_fraud`,
`q_hat_legit`, confidence 0.99), the prediction-set rule, and the scalar score
formula used in the package:

```
entropy = -[p log2 p + (1-p) log2 (1-p)]      # clipped to [0, 1]
score   = entropy                              # normally
score   = max(entropy, 0.85)                   # empty prediction set
```

The action threshold is `high_uncertainty_score_threshold = 0.50`, stored in
`uncertainty_config.json`.

**Recommendation:** **Role 4 owns the formula and q-hats; Role 5 owns the API
serialization** and uses the config value, not a hard-coded 0.50. Document the
formula and the 0.85 empty-set floor in the OpenAPI/conventions.

**Owner:** Role 4 + Role 5. **Impact:** if the formula changes, the package
fixture and the dashboards change; the model does not.

**Team-doc status (1 Nov):** V2.2 still says ML Serving owns the definition;
conventions adds `uncertainty.is_uncertain`/`score` but no formula. The team
docs still do not define the scalar; Role 4's artifact does.

---

### D7. MLflow server and registry ownership

**Question:** who runs the shared MLflow tracking server, backend store,
artifact store, and `@production` alias?

**Recommendation:** **Role 3 hosts the MLflow server** (Postgres + S3 + K8s,
matching `docs/conventions.md` §1); **Role 5 owns model registration/loading
and the FastAPI service**; Role 4 logs the champion, verifies the alias, and
runs parity. V2.2 §2.2 says “ML Serving + DevOps/MLOps”, so a shared split is
acceptable — but one person must own the server checklist.

**Minimum setup:** tracking URI, Postgres backend, MinIO/S3 artifact root,
`sqlalchemy==2.0.36`, `fraud-detector@production`, serving env
`MLFLOW_TRACKING_URI`/`MODEL_NAME`/`MODEL_ALIAS`.

**Impact:** until this exists, Role 4's local `mlruns/` is only a smoke-test
registry and Phase 9 uses a local Docker endpoint.

---

### D8. `CASH_OUT` and the accepted type set

**Question:** does the app implement `CASH_OUT`? Does `/predict` accept all five
types?

**Evidence:** V2.2 promotes `CASH_OUT` to **core** and says ML Serving accepts
all five types; the app sends `TRANSFER` + `CASH_OUT`. The model is trained and
evaluated on both. If `CASH_OUT` is not implemented, the in-scope population is
`TRANSFER` only and every headline number must be recomputed.

**Recommendation:** keep all five types at the API (forward compatibility) and
confirm the app ships `CASH_OUT`. If it does not, tell Role 4 **before the
demo** so the TRANSFER-only numbers replace the two-type numbers.

**Owner:** Backend. **Impact:** potentially a full re-run of the benchmark,
conformal, and robustness reports.

**Team-doc status (1 Nov):** **resolved** — `docs/conventions.md` §3 makes
`TRANSFER` and `CASH_OUT` core MUST; V2.2 §17.1 says the API accepts all five.
Keep the API at five types and the app at two. (Role 5's current 2-type enum
is D14, not this decision.)

---

### D9. App-valid definition and monetary scale

**Question:** confirm the backend validation and the V2.2 scale.

**Evidence:** V2.2 sets initial balance **1,000,000.00**, max transfer
**10,000,000.00**, no rescale. Role 4 defines app-valid as
`TRANSFER`/`CASH_OUT`, `amount > 0`, `amount <= sender_old_balance`; that keeps
281,759 rows / 8,168 frauds / **2.899%** and removes ~90% of PaySim rows.

**Recommendation:** confirm the validation order (available balance before ML)
and that holds/limits are included in `sender_old_balance`. If the app's
"available" differs from `oldbalanceOrg`, the serving population changes and
the calibration prior must be revisited.

**Team-doc status (1 Nov):** the scale (1,000,000 / 10,000,000 / 500,000) is
now documented identically in V2.2 §11.2 and conventions §3 — **resolved**.
Only the exact `available` definition/validation order needs backend
confirmation.

**Owner:** Backend + Role 4.

---

## P2 — housekeeping

### D10. Decision reasons and the “ML uncertainty” alert

**Question:** can the dashboard separate model uncertainty from the high-amount
rule?

**Evidence:** `PENDING_REVIEW` includes R4 (`MODEL_UNCERTAIN`), R5
(`AMOUNT_HIGH`), R1b (`TYPE_NOT_SCORED`), and R2 (`SERVICE_DEGRADED`). The
current “uncertain ratio” alert would fire on high-amount review traffic.

**Recommendation:** add a `reason` label to `fintech_decisions_total` (or use
Role 5's `ml_human_review_requests_total{reason}`) and alert only on
`MODEL_UNCERTAIN`/`SERVICE_DEGRADED`.

**Owner:** Backend + DevOps + Role 4 (validation).

**Team-doc status (1 Nov):** **resolved** — conventions §6 adds the `reason`
label and restricts the uncertainty alert to `MODEL_UNCERTAIN`. Backend/DevOps
only need to implement it.

### D11. Viz point count

**Evidence:** V2.2 §24.2/§21.4 say 5,000–10,000 points; the OpenAPI default is
2,000 and caps at 10,000. Role 4 ships 2,000 per method to match the endpoint
default.

**Recommendation:** keep 2,000 for the demo; regenerate at 5–10k later if the
frontend needs denser clouds (the endpoint can downsample).

**Owner:** Role 4 + Role 5.

### D12. Audit fields and feature-freeze date

**Recommendation:** store the model version **plus** the uncertainty-config
hash/confidence level with each decision (reproducibility); update the V2.2
“25 Oct” feature-list references to the actual freeze (v1.2, 29 Oct; team
freeze 20 Dec).

**Owner:** Backend + Role 4.

---

## New blockers from the 1 Nov pull

### D13. `/predict` request/response shape: conventions vs V2.2/OpenAPI

**Question:** which contract is normative?

**Evidence:** the new `docs/conventions.md` §4 defines a **flat** request
(`transaction_id` + six fields) and a **flat** response
(`prediction`, `prediction_set`, `model_version`, `explanations.attribution`).
V2.2 §17.1/17.2 and the OpenAPI define a **nested** request
(`schema_version`, `request_id`, `features{}`) and a **nested** response
(`action`, `uncertainty{}`, `model{}`, `explanations.contribution`,
`inference_ms`).

**Recommendation:** keep **V2.2 + OpenAPI** as normative (that is what Role 5
implements and what the parity fixture tests) and rewrite conventions §4 to
match. Do not build Risk against the conventions' flat shape.

**Owner:** Backend + Role 5. **Impact:** a contract rewrite, not a model change.

---

### D14. 11 vs 14 transformed features

**Question:** does the served model accept five types (14 features) or only
TRANSFER/CASH_OUT (11 features)?

**Evidence:** Role 5 commit `22d179a` set
`TRANSACTION_TYPES = ["CASH_OUT", "TRANSFER"]` and restricted the API enum to
two values. V2.2 §17.1 says ML Serving **accepts all five**; the new
conventions says the model is **trained on all five**. Role 4's model is
**14 features**. With Role 4's `ml/common` overlaid on the current Role 5
branch, **23/25** serving tests pass; the two failures assert 11 columns
(`(5, 14) != (5, 11)`).

**Recommendation:** **revert Role 5 to five categories / 14 features.** It
matches V2.2, the conventions, the delivered model, and the parity fixture.
If the team truly wants 11 features, Role 4 must retrain/recalibrate/repack
and V2.2 §17.1, the OpenAPI enum, and the fixture must change together.

**Owner:** Role 5 + Role 4. **Impact:** blocks merging `ml/common` and the
serving CI; no retrain if the revert wins.

---

## Already settled (no action needed)

| Item | Decision |
|---|---|
| Dataset / population | PaySim; primary app-valid `TRANSFER` + `CASH_OUT` |
| Served model | XGBoost, contract protocol, serving-consistent balances |
| Conformal | Mondrian 99%, `q_hat_fraud`/`q_hat_legit` in the artifact |
| Decision policy | R3 reject `{fraud}`, R4 review empty/both, R5 review `{legit}` + amount ≥ threshold, R6 approve |
| R5 default | 500,000 provisional, documented in V2.2 and conventions |
| `CASH_OUT` | Core MUST; app sends TRANSFER + CASH_OUT; API accepts all five (pending D14) |
| Monetary scale | 1,000,000 initial / 10,000,000 max / 500,000 R5 |
| Reason labels | `fintech_decisions_total{reason}`; alert only on `MODEL_UNCERTAIN` |
| Robustness | Temporal + destination-disjoint; all frauds caught in both |
| Features | Six contract fields + four derived; 10 raw / 14 transformed |
| Serving artifact | `models:/fraud-detector@production` + `uncertainty_config.json` |
| Viz | 2,000 points per method, OpenAPI `EmbeddingVizResponse` shape |

---

## Suggested 20-minute agenda

1. **D1 R5** (3 min) — pick 500k or 324,610.
2. **D2 full drain** (5 min) — demo policy vs real-user policy.
3. **D3/D4 contract** (5 min) — amount type, `request_id`.
4. **D7 MLflow** (4 min) — who stands up the server, what Role 4 gets back.
5. **D8/D9** (3 min) — `CASH_OUT`, app-valid/scale confirmation.

If D1/D2/D3/D4/D7 are settled, Role 4 can finish the handoff and start Phase 9
without waiting for the rest.
