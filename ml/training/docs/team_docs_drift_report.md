# Team Docs Drift Report — Role 4

**Date:** 1 November 2026 · **Author:** ML Training (Role 4)
**Trigger:** pulled `origin/main` (`136bc99`) and `origin/feat/role5-mlops`
(`3734d93`) into `feat/role4-paysim-ml-setup`.
**Question:** did the team decisions change in the conception/conventions, or do
the same issues remain?

**Short answer:** some decisions moved forward — R5 500k, `CASH_OUT`,
scale, and reason labels are now documented. But **three new/remaining
blockers** appeared:

1. the new `docs/conventions.md` §4 defines a **different `/predict` contract**
   from V2.2 §17.1/17.2 and the OpenAPI;
2. the current Role 5 branch changed the model to **11 features / 2 types**,
   contradicting V2.2 and the new conventions (all five types);
3. amount serialization and `request_id` are still contradictory.

---

## 1. What was pulled

| Branch | Head | Change |
|---|---|---|
| `origin/main` | `136bc99` | V2.1 → **V2.2** committed; `docs/conventions.md` rewritten as “V2.2 aligned” |
| `origin/feat/role5-mlops` | `3734d93` | Merge of main; includes `22d179a` — **11-feature / 2-type** serving change |
| `feat/role4-paysim-ml-setup` | `7fe90f4` | Merged `origin/main`; now contains V2.2 + new conventions; tests still 31/31 |

The committed V2.2 is byte-identical to the root V2.2
(`sha256 9670fca…`), so the conception itself did **not** add new decisions
beyond what Role 4 already audited. The new content is the rewritten
`docs/conventions.md`.

---

## 2. Issue-by-issue status

| Topic | V2.2 (main) | `docs/conventions.md` (main) | OpenAPI / role5 | Role 4 artifact | Verdict |
|---|---|---|---|---|---|
| **R5 threshold** | 500,000 provisional, to be validated | 500,000 provisional | 500,000 in policy examples | validates 500,000 → 1.322% review | **Documented, not formally accepted** |
| **Full-drain policy** | Demo trigger: whole balance = `REJECTED` | Same demo trigger; no product policy | — | model p≈0.99999 → R3 reject | **Still open** |
| **Amount serialization** | §11.1: **string** in JSON | §4: **numbers** (`1000.00`) | numbers (`double`) | model consumes numbers | **Still contradictory** |
| **Request ID** | `request_id` in request; **missing in response** | `transaction_id` in request **and** response | `request_id` in request+response | echoes the request ID it receives | **Still open; naming now conflicts** |
| **Request shape** | Nested: `schema_version`, `request_id`, `features{6}` | Flat: `transaction_id` + 6 fields | Nested, same as V2.2 | nested; parity fixture matches OpenAPI | **New conflict — conventions diverges from V2.2/OpenAPI** |
| **Response shape** | Nested: `schema_version`, `action`, `fraud_probability`, `uncertainty{…}`, `model{}`, `explanations[]`, `inference_ms` | Flat: `transaction_id`, `prediction`, `prediction_set`, `uncertainty{is_uncertain,score}`, `model_version`, `explanations{attribution,description}` | Nested, same as V2.2 | nested; E2E matches OpenAPI | **New conflict — conventions diverges from V2.2/OpenAPI** |
| **Model name** | `fraud-xgb` | `fraud-detector-v1.0` | `fraud-detector` | `fraud-detector` | **Still inconsistent; conventions leans correct** |
| **Uncertainty formula** | “definition owned by ML Serving” | No formula | `score` + `prediction_set` only | normalized entropy; empty-set floor 0.85; threshold 0.50 | **Still undefined in team docs** |
| **Transaction types** | §17.1: all five accepted; app sends two | §4: model trained on all five; app sends two | **role5 `22d179a`: only TRANSFER/CASH_OUT, 11 features** | 14 features / five categories | **New critical conflict** |
| **`CASH_OUT`** | Core | Core MUST | Core | in-scope | **Resolved** |
| **Scale / balances** | 1,000,000 initial; 10,000,000 max; R5 500k | Same | — | same | **Resolved** |
| **Reason labels / alert** | §22.2 describes the problem | §6 adds `reason`; alert on `MODEL_UNCERTAIN` only | serving already exposes finite reasons | report splits R4/R5 | **Resolved** |
| **MLflow ownership** | §2.2: “ML Serving + DevOps/MLOps” | Port table: MLflow server = **Role 3** | Role 5 currently loads/registers | handoff said Role 5 server | **Ambiguous; needs a named owner** |
| **Viz point count** | 5,000–10,000 precomputed | Not addressed | endpoint default/cap 2,000/10,000 | 2,000 shipped | **Still open** |
| **Feature-list freeze** | Says “by 25 Oct”; freeze 20 Dec | Not addressed | — | v1.2 frozen 29 Oct | **Stale date still in V2.2** |

---

## 3. The three blockers in detail

### Blocker A — `/predict` contract: conventions vs V2.2/OpenAPI

`docs/conventions.md` §4 says the contract is “100% frozen” but defines:

```json
{
  "transaction_id": "...",
  "type": "TRANSFER",
  "amount": 1000.00,
  "sender_old_balance": 5000.00,
  "sender_new_balance": 4000.00,
  "receiver_old_balance": 200.00,
  "receiver_new_balance": 1200.00
}
```

V2.2 §17.1 and the OpenAPI define:

```json
{
  "schema_version": "1.0",
  "request_id": "...",
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

The response differs too (flat `prediction`/`prediction_set`/`model_version`
vs nested `action`/`uncertainty`/`model`). Role 5's OpenAPI, FastAPI schemas,
and Role 4's parity fixture all follow V2.2, not the new conventions.

**Recommendation:** treat V2.2 §17.1/17.2 + the OpenAPI as normative and
rewrite conventions §4 to match. Otherwise every service built from the
conventions will fail against the implemented `/predict`.

**Owner:** Backend + Role 5. **Role 4 impact:** none if V2.2/OpenAPI wins;
a rewrite is needed if conventions wins.

---

### Blocker B — 11 vs 14 features (2 types vs 5 types)

Role 5 commit `22d179a` changed:

```python
TRANSACTION_TYPES = ["CASH_OUT", "TRANSFER"]   # 2 categories -> 11 transformed columns
```

and restricted `TransactionType` to two values. V2.2 §17.1 says ML Serving
**accepts all five** types; the new conventions says the model is **trained on
all 5** types (only app traffic is limited to two). Role 4's served model is trained on the app-valid two types, but the
encoder is pinned to **five categories**, so the signature is **14 features**
(9 numeric + 5 one-hot) and it can score all five.

Evidence: with Role 4's 14-feature `ml/common` overlaid on the current Role 5
branch, **23/25** serving tests pass; the two failures are exactly the parity
tests that assert 11 columns:

```
assert transformed.shape == (len(rows), 11)
E  assert (5, 14) == (5, 11)
```

The earlier “25/25” result was on the **pre-`22d179a`** Role 5 branch (14
features). It is no longer true for the current head.

**Decision required:** either

- **revert Role 5 to five categories / 14 features** (matches V2.2, the new
  conventions, and the delivered model) — recommended; or
- formally move to an 11-feature model: retrain/conformal/repackage on two
  categories, update V2.2 §17.1, the OpenAPI enum, and the parity fixture.

**Owner:** Role 5 + Role 4. **Impact:** without this, merging `ml/common`
breaks CI and the model loader.

---

### Blocker C — amount type and request ID still unresolved

- V2.2 §11.1: amounts are **strings** in JSON; §17.1/OpenAPI/conventions use
  **numbers**. The contradiction persists, and conventions now silently picks
  numbers.
- V2.2 response has **no `request_id`**; conventions invents `transaction_id`;
  the OpenAPI requires `request_id` in both request and response. The team has
  three names/shapes for the same correlation ID.

**Recommendation:** strings at the wallet/public API, numbers at `/predict`;
`request_id` (not `transaction_id`) echoed in the response. Document the
boundary in V2.2 §11.1/§17.2 and conventions §4.

**Owner:** Backend + Role 5.

---

## 4. Decisions that did move forward

| Decision | New status |
|---|---|
| R5 = 500,000 | Documented as the provisional default in V2.2 and conventions. Role 4's validation supports it (1.322% review). Still needs formal sign-off. |
| `CASH_OUT` | Core MUST in both V2.2 and conventions. |
| Monetary scale | 1,000,000 initial / 10,000,000 max / 500,000 R5, in both. |
| Reason labels | conventions §6 adds `reason` and restricts the uncertainty alert to `MODEL_UNCERTAIN`. |
| Health/ports | conventions documents `/health/live`, `/health/ready`, `/model-info`, `/viz/*`, ports 8000/5000/5432/9000. |

---

## 5. Still open (unchanged)

1. Full-drain product policy (demo reject vs review vs restrict).
2. Amount serialization (string vs number).
3. `request_id` / `transaction_id` in the response.
4. Model name (`fraud-xgb` vs `fraud-detector`).
5. Uncertainty-score formula/ownership.
6. MLflow server owner (Role 3 vs Role 5/shared).
7. Viz point count (5–10k vs 2k).
8. Feature-list freeze date (V2.2 still says 25 Oct).

---

## 6. Recommended actions

1. **Role 5:** revert `TRANSACTION_TYPES` to the five categories (14 features)
   or open a formal change request for 11 features. Do not merge `ml/common`
   until this is settled.
2. **Backend + Role 5:** rewrite `docs/conventions.md` §4 to the V2.2/OpenAPI
   nested request/response; keep `request_id`, add it to the response.
3. **Team:** pick `request_id` (recommended) vs `transaction_id`; pick string
   vs number at the public boundary; update V2.2 §11.1/§17.2 and OpenAPI
   together.
4. **Role 3 + Role 5:** name the MLflow server owner explicitly. V2.2 says
   shared “ML Serving + DevOps”; conventions says Role 3. Role 4's handoff
   needs a single owner for the server checklist.
5. **Role 4:** after (1) is resolved, rerun the serving suite and the six parity
   cases against the team stack; update the handoff verification log.

---

## 7. Verification commands used

```bash
git fetch --all --prune
git log --oneline origin/main -3
git diff origin/main...origin/feat/role4-paysim-ml-setup
git show origin/feat/role5-mlops:ml/common/schema.py | grep TRANSACTION_TYPES
git show origin/feat/role5-mlops:ml/serving/tests/test_feature_parity.py | grep "shape =="
# temporary worktree with Role 4's ml/common overlaid:
pytest ml/serving/tests -q
# -> 23 passed, 2 failed (11 vs 14 feature parity)
```
