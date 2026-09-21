# CP-ABE Data-Anonymization Demo

A teaching skeleton for **data anonymization with ciphertext-policy attribute-based
encryption (CP-ABE)**.

A Vite + React dashboard signs users in and lets them query anonymized sample
records. Every record stores its **own ciphertext** together with the **access
policy** that ciphertext was encrypted under; the FastAPI backend decrypts a
record only when the caller's **attribute set** satisfies that policy, and refuses
the rest with an explanation instead of a value.

> **Status: no cryptography and no anonymization yet.** Access decisions are real
> (policies are parsed and evaluated), but the "ciphertext" is a documented
> placeholder (`crypto_backend: "stub"`). The API, the UI and the database schema
> are all shaped so that a real CP-ABE implementation drops into one file.

---

## 1. The model this demo is built around

| CP-ABE concept | Where it lives here |
|---|---|
| Attribute universe (`role:doctor`, `dept:cardiology`, `clearance:2`, `site:mercy-general`, `purpose:care`, `region:eu`) | `backend/app/seed.py` → `attribute_definitions` table, `GET /api/catalog/attributes` |
| User secret key material (an attribute set) | `user_attributes` table; re-read from the database on **every** request, not trusted from the token |
| Ciphertext bound to an access policy | `records.ciphertext_blob` + `records.policy` + `records.policy_hash` |
| The access policy language | `backend/app/services/policy.py` — `AND` / `OR` / `NOT` / parentheses over `category:value` attributes |
| Decryption that fails when the policy is not satisfied | `backend/app/services/cpabe.py` → `CiphertextBackend.decrypt()` returns `None` before any value is read |
| Key re-issue when attributes change | `PATCH /api/admin/users/{id}` (audited, before/after snapshot) |

**Two enforcement layers** — the difference matters and the demo shows both:

1. **RBAC (route level).** The JWT carries `roles`. `/api/audit` and `/api/admin/*`
   require `admin`. This is ordinary application authorisation.
2. **CP-ABE policy (record level).** The caller's *effective* attribute set is
   evaluated against each record's ciphertext policy. Roles do **not** grant record
   access, and attributes do **not** grant administrative access.

The frontend re-evaluates policies only to *explain* them (the "policy trace" and
the "why refused?" dialog). **Enforcement is server-side only**; nothing in the
browser is trusted.

---

## 2. Repository layout

```
cs442-project/
├── backend/
│   ├── app/
│   │   ├── main.py            FastAPI app, CORS, startup seeding
│   │   ├── config.py          settings from backend/.env (all defaults are dev-safe)
│   │   ├── db.py              SQLAlchemy engine/session
│   │   ├── models.py          users, attributes, datasets, fields, records, policies, audit log
│   │   ├── schemas.py         Pydantic request/response models
│   │   ├── security.py        bcrypt hashing + JWT (HS256) issuing/validation
│   │   ├── deps.py            `Principal` (identity + effective attribute set), role guards
│   │   ├── seed.py            attribute universe, 6 accounts, 3 datasets, 48 records, 8 policies
│   │   ├── services/
│   │   │   ├── policy.py      CP-ABE policy language: tokenizer, parser, evaluator, trace
│   │   │   ├── cpabe.py       CiphertextBackend protocol + StubCiphertextBackend  ← swap point
│   │   │   ├── access.py      per-attribute-set access summaries
│   │   │   └── audit.py       append-only audit trail
│   │   └── routers/           auth, catalog, datasets, query, audit, admin
│   ├── scripts/role_matrix_check.py    prints the whole role matrix (in-process or live)
│   ├── tests/                 pytest: policy unit tests + end-to-end API tests
│   └── requirements*.txt  .env.example  pytest.ini
└── frontend/
    └── src/
        ├── index.css          one custom daisyUI theme (`cpabe`, dark) - see §7
        ├── lib/               api client, auth context, types, formatting, a small data hook
        ├── components/        AppShell, AttributeChips, PolicyTrace, RecordTable, ... (14 files)
        └── pages/             SignIn, Dashboard (query console, my key, audit, accounts)
```

---

## 3. Quick start

Two terminals. The backend must be running first.

**Backend** (Python 3.13 from `uv`, SQLite, no external services):

```bash
cd backend
uv venv .venv                                   # or: python3 -m venv .venv
uv pip install --python .venv/bin/python -r requirements.txt -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --reload --port 8000
```

The database (`backend/app.db`) is created and seeded on first start. Interactive
API docs: <http://127.0.0.1:8000/docs>.

**Frontend** (Vite dev server, proxies `/api` to port 8000):

```bash
cd frontend
npm install
npm run dev
```

Open <http://127.0.0.1:5173> and sign in with any account from §4.

Configuration is optional: copy `backend/.env.example` to `backend/.env` if you
want a different `JWT_SECRET`, token lifetime, database URL, or to disable the
sample-account hints on the sign-in page.

---

## 4. Sample accounts and the role matrix

All sample content. The shared password is `demo1234` (the point of the exercise is
the attribute set behind each account, not the password).

| Account | Attribute set | Roles |
|---|---|---|
| `admin@demo.local` | `role:admin`, `clearance:3`, `purpose:audit` | admin |
| `dr.okafor@demo.local` | `role:doctor`, `dept:cardiology`, `site:mercy-general`, `clearance:2`, `purpose:care` | doctor |
| `dr.reyes@demo.local` | `role:doctor`, `dept:oncology`, `site:st-marys`, `clearance:2`, `purpose:care` | doctor |
| `researcher@demo.local` | `role:researcher`, `clearance:1`, `region:eu`, `purpose:research` | researcher |
| `auditor@demo.local` | `role:auditor`, `clearance:3`, `purpose:audit` | auditor |
| `pending@demo.local` | requested `role:researcher`, `region:us` | researcher (status **pending**) |

`granted > refused` per dataset, for the 48 seeded records:

| Account | `patient_demographics` | `lab_results` | `billing_claims` |
|---|---|---|---|
| admin | 20 > 0 | 16 > 0 | 12 > 0 |
| dr.okafor (cardiology) | 6 > 14 | 6 > 10 | 0 > 12 |
| dr.reyes (oncology) | 6 > 14 | 6 > 10 | 0 > 12 |
| researcher (EU, clearance 1) | 4 > 16 | 4 > 12 | 0 > 12 |
| auditor | 0 > 20 | 0 > 16 | 12 > 0 |
| pending | refused at sign-in | — | — |

Four rows in `patient_demographics` are encrypted under
`(role:doctor AND dept:radiology) OR role:admin` and **no seeded account holds
`dept:radiology`**. That is deliberate: they are the material for the live
attribute change in the next section.

Reproduce the table without a browser:
```bash
cd backend
.venv/bin/python scripts/role_matrix_check.py                       # in-process
.venv/bin/python scripts/role_matrix_check.py --base-url http://127.0.0.1:5173/api
```

---

## 5. Five-minute demo script

1. **Sign in as `auditor@demo.local`** → open the *Query console*, query
   `patient_demographics`. Every record is refused: the page shows the counts, the
   refused policies, the reason, and the attributes that would unlock them. No
   clinical values appear anywhere.
2. **Sign in as `dr.okafor@demo.local`** → the same dataset now returns 6
   cardiology rows. Expand a row's **Policy** button: the policy trace shows which
   leaves your attribute set satisfied. Query `billing_claims` and everything is
   refused again — the auditor's dataset is not his.
3. **Sign in as `admin@demo.local`** (or stay in the same browser) → *Accounts* →
   **Edit attributes** on Dr. Okafor → tick `dept:radiology` and save. The per-dataset
   counts in the list change immediately.
4. **Back in the console as Dr. Okafor** (his existing session is enough — the
   attribute set is re-read per request): `patient_demographics` now decrypts
   **10** rows instead of 6. He was granted an *attribute*, not a permission flag,
   and no dataset was touched.
5. **Sign in as `pending@demo.local`** → sign-in is refused with "pending
   administrator approval". As admin, approve the account in *Accounts* and it can
   sign in — and still decrypts nothing clinical, because it holds `region:us`
   while the research policies require `region:eu`.
6. **Audit trail** (admin) → every sign-in and every query above is listed with the
   attribute set that was used to decide. `attributes_change` entries carry the
   before/after attribute sets and the change note.

---

## 6. API reference

All endpoints are under `/api`. Everything except `/api/health`, `/api/auth/login`
and `/api/catalog/demo-accounts` needs `Authorization: Bearer <token>`.

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | backend, crypto backend id, whether encryption is real yet |
| POST | `/auth/login` | `{email, password}` → token + profile; 401 generic, 403 for pending/disabled |
| GET | `/auth/me` | profile **plus** the claims the server read from the token |
| POST | `/auth/logout` | audited; tokens are stateless so the client also discards it |
| GET | `/catalog/attributes` | the attribute universe, grouped by category |
| GET | `/catalog/policies` | every policy, its canonical form, hash, and record count |
| GET | `/catalog/demo-accounts` | sample accounts for the sign-in page (dev only) |
| GET | `/datasets` | datasets with `granted_count` / `denied_count` **for your attribute set** |
| GET | `/datasets/{id}` | fields with classification + anonymization rule, and policies |
| POST | `/query` | `{dataset_id, filters[], fields[], limit, offset}` → decrypted rows + refusal summary |
| GET | `/audit` | audit trail (admin) |
| GET | `/admin/users` | accounts, attribute sets, per-dataset access preview (admin) |
| PATCH | `/admin/users/{id}` | approve / disable / re-issue roles and attributes (admin, audited) |

The query response is the heart of the demo:

```jsonc
{
  "crypto_backend": "stub", "encrypted": false,
  "rows": [{ "record_key": "PT-1A2B3C4D5E", "values": { "...": "..." },
             "policy": "(role:doctor AND dept:cardiology) OR role:admin",
             "decision": { "granted": true, "reason": "satisfied by clause: ...",
                           "matched_attributes": ["dept:cardiology", "role:doctor"],
                           "missing_attributes": [] },
             "policy_tree": { "type": "or", "satisfied": true, "children": [ "..." ] },
             "ciphertext": { "backend": "stub", "encrypted": false,
                             "policy_hash": "…", "preview": "eyJhZ2VfYmFuZC…" } }],
  "denied": { "count": 14, "by_policy": [ { "policy": "...", "count": 6,
               "reason": "no clause satisfied: ...", "missing_attributes": ["dept:oncology"] } ] },
  "totals": { "scanned": 20, "granted": 6, "denied": 14, "matched": 6 },
  "audit_id": 42, "took_ms": 4, "notice": "…"
}
```

Notes on the contract:

- **Refused records are never returned**, not even partially: `denied` carries only
  counts, policies and reasons. `tests/test_api.py` asserts that no refused value
  text appears anywhere in the response body.
- **Filtering happens after decryption.** A CP-ABE deployment cannot filter
  ciphertext it may not open, so `totals.scanned` counts every record that had its
  policy evaluated and `totals.matched` counts the decrypted rows that then matched.
- Unknown filter fields, non-queryable fields (the direct identifiers), unknown
  columns and non-numeric `gte`/`lte` values are rejected with 422.

---

## 7. Frontend notes

- **Routing.** `/login` is public; `/dashboard` is behind `RequireAuth` and
  preserves the intended destination in `?next=`. The *Audit trail* and *Accounts*
  sections are hidden without the `admin` role — and the API refuses them regardless.
- **Session.** The token is kept in `localStorage` for demo convenience. This is a
  deliberate trade-off (it enables the "My key material" panel, which shows the
  claims the server read); a production build would prefer an httpOnly cookie.
- **Effective vs. session attributes.** `/auth/me` returns both. The panel shows
  them side by side because the difference is the point: an administrator can change
  an attribute set while a session is open.
- **Design system.** daisyUI 5 with Tailwind CSS 4, **one custom dark theme**
  (`cpabe`, defined in `frontend/src/index.css` via `@plugin "daisyui/theme"`), no
  theme switching, and Lucide icons. All styling is utility classes in markup — no
  authored CSS selectors, and no runtime-assembled daisyUI class names (state maps
  hold complete class strings).
- **The signature element** is the *policy trace*: every result row renders its
  ciphertext policy in monospace with a per-leaf trace, and the "why refused?"
  dialog maps your attributes onto that policy. Status is always colour **and** an
  icon **and** a word.
- The frontend was designed with the daisyUI **Blueprint** MCP workflow (setup →
  rules → creative direction → page architecture → component syntax → quality
  inspector). The quality inspection passes with zero findings.

---

## 8. What is **not** implemented (and where it plugs in)

Nothing below is faked or silently stubbed — every omission is stated in the API
responses and in the UI.

### 8.1 Real CP-ABE

`backend/app/services/cpabe.py` defines the seam:

```python
class CiphertextBackend(Protocol):
    def encrypt(self, values, policy) -> StoredCiphertext: ...
    def decrypt(self, ciphertext, attributes) -> DecryptionResult: ...
```

`StubCiphertextBackend` base64-encodes JSON, but it **evaluates the policy before
producing any value**, so the access-control behaviour is already correct. A real
backend implements the same two methods (master-key setup, per-attribute key
generation, access-tree/LSSS policy, pairing-based decryption) and is selected with
`CRYPTO_BACKEND=<name>`; no router, schema, UI or test needs to change. Candidate
libraries worth evaluating for the next phase (existence verified, not yet
assessed for suitability): `py-ecc` (pure Python, no build step), `bplib`/`petlib`
(OpenSSL pairings), `charm-crypto` (legacy, unlikely to build on Python 3.13).

The API already reports `crypto_backend` and `encrypted` everywhere, and the UI
shows a "placeholder ciphertext" badge, so the switch is visible when it happens.

### 8.2 Real anonymization

Field metadata exists and is displayed: `classification`
(`direct_identifier` / `quasi_identifier` / `sensitive` / `non_sensitive`) and
`anonymization_rule` (`none` / `suppress` / `mask` / `hash` / `generalize` /
`perturb`). The seeded values are *already* generalised sample data (age bands,
masked postal prefixes, hashed references) and `records.plaintext_source` holds the
pre-anonymization values for the future pipeline. **No transformation is performed
yet**, and the UI says so.

The intended shape: `plaintext_source → anonymize(fields, rules) → encrypt(policy)
→ ciphertext_blob`, with k-anonymity/ℓ-diversity and re-identification risk checks
(hence the `reidentification_flags` table placeholder) reporting before encryption.

### 8.3 Deliberate demo simplifications

| Simplification | Why | Production direction |
|---|---|---|
| `Base.metadata.create_all()` instead of migrations | one-command demo | Alembic |
| Placeholder ciphertext | cryptography is the follow-up phase | real CP-ABE |
| No registration endpoint; accounts are seeded and provisioned by an admin | keeps the attribute-authority story clear | admin-only provisioning, as in a real KDC |
| Bearer token in `localStorage` | makes the claims panel possible | httpOnly cookie + refresh/rotation |
| No HTTPS, no rate limiting, dev JWT secret allowed with a startup warning | local teaching environment | secrets manager, TLS, throttling |
| Access previews in the admin list are computed in Python per request | 6 accounts × 48 records | query-side policy indexing |

---

## 9. Tests and verification

```bash
cd backend && .venv/bin/python -m pytest            # 57 passed
cd frontend && npm run build                        # tsc -b && vite build
cd frontend && npm run lint                         # oxlint: 0 warnings, 0 errors
```

What the backend suite covers:

- **Policy language** (`tests/test_policy.py`, 24 tests): precedence (`AND` binds
  tighter than `OR`), parentheses, `NOT`/`!`, case and whitespace tolerance, leaf
  traces, denial reasons, canonical rendering, policy hashing, and 11 malformed
  policies.
- **End-to-end API** (`tests/test_api.py`, 33 tests): the full role matrix above
  as a parametrised assertion; that working but *unmatched* filters are reported
  honestly; that refusals leak **no** clinical text anywhere in the payload; RBAC
  guards on `/audit` and `/admin/*`; expired tokens; pending accounts; filter and
  column validation; pagination; audit entries; and the live attribute change
  (grant `dept:radiology` → 6 becomes 10 → restore).

Known verification gap: the daisyUI Blueprint quality inspection passed on source,
but **rendered UI review was unavailable** in this environment (no browser tool), so
layout at 390 px / 1440 px has not been visually confirmed. Run `npm run dev` and
check the drawer at a phone width and the wide tables at a desktop width.



