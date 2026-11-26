# Configurable IDP Engine and MMIL Evidence Consumer

This repository has two explicit boundaries:

1. **Reusable IDP engine**: receives a document, classifies it, applies a versioned document-specific extraction contract, returns grounded primary fields plus bounded additional facts, and preserves source/run provenance.
2. **Static MMIL consumer**: displays a medical IDP result in the supplied mock-derived layout and opens the cited uploaded document beside it. It does not own extraction logic or IDP persistence.

The engine extracts explicit evidence. An LLM can propose candidates, but a value without a valid page/exact excerpt is not published. The system does not diagnose, rate, calculate loading, decide eligibility/coverage, or submit underwriting decisions.

## Specifications

Authoritative engine spec:

```text
.kiro/specs/configurable-idp-engine/
  requirements.md
  design.md
  tasks.md
```

Static MMIL consumer spec:

```text
.kiro/specs/medical-evidence-workbench/
  requirements.md
  design.md
  tasks.md
```

`plan.md`, `architecture.mmd`, and `aws-deployment-plan.md` describe the same separation and the supplied Launchpad dev resources.

## Current implementation status

The checked-in application is a **local vertical prototype** created before the engine/consumer boundary was clarified. It already demonstrates:

- secure PDF/JPEG/PNG/TIFF validation;
- immutable local object/hash checks;
- asynchronous worker states;
- native PDF text extraction with pypdf and replaceable OCR adapters (PyMuPDF renders scanned pages);
- a versioned medical field schema;
- deterministic extraction and strict citations;
- provider-neutral structured-output boundaries;
- persisted candidates/audit;
- a mock-derived React medical page and actual side-by-side PDF/image viewer;
- backend property/integration tests and frontend tests/build.

The current API/database still contains MMIL `Case` and human-review concepts and uses direct multipart upload/local queue/storage. The new engine task plan migrates those to `Consumer`, `ExtractionRequest`, generic `/api/v1/idp` contracts, S3/SQS/PostgreSQL, additional facts, and signed BFF service context. Do not deploy the current prototype as the reusable AWS service.

## Launchpad dev alignment

The target reuses:

- existing Launchpad VPC/private/data subnets, NAT, endpoints, and flow logs;
- existing data KMS key;
- `launchpad-dev-files` under generated `idp/dev/` keys;
- existing RDS PostgreSQL 17 instance with a new `idp` schema and `idp_dev` role;
- existing Cognito/session authorization through the Launchpad API BFF;
- existing ALB/regional WAF, CloudFront/CloudFront WAF, `/api/*` behavior, and static web bucket;
- existing OpenAI/Azure key secret for the IDP worker only after provider approval;
- existing CDK bootstrap and `ContainerImage.fromAsset` build path.

The target adds dedicated IDP API/worker services, queue/DLQ, task roles, DB/service-auth secrets, private discovery, log groups, dashboards, and alarms. It does not use unrelated Launchpad queues or broad existing task roles.

The supplied deployed Launchpad `infra/` source is not present in this workspace. Exact CDK integration remains blocked until that source or reviewed stack outputs/construct references are provided. No AWS deployment has been attempted.

## Available-service consequences

- **OCR:** The supplied roles have no Textract permissions. Dev uses PyMuPDF native text then containerized RapidOCR for image-only pages. Start the worker at 1 vCPU/2 GB and concurrency one.
- **LLM:** The only supplied model secret is OpenAI/Azure. The target adapter requires an approved HTTPS endpoint, API version, pinned deployment, region allowlist, and explicit provider approval. A secret name alone is not data-handling approval.
- **Bedrock/Claude:** Not active in this Launchpad dev design because the supplied permissions/services do not include Bedrock.
- **Auth:** The current Cognito app client is confidential, so the static SPA uses the existing Launchpad BFF/session. The private IDP API validates signed short-lived BFF service context.
- **Ingress:** HTTPS terminates at existing CloudFront. The dev ALB remains HTTP behind CloudFront; IDP itself has no public ingress.

## Local prototype setup

Prerequisites:

- Python 3.10+
- Node.js 22.12+ (Node 22 or 24 LTS recommended)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python .\sample-data\generate_medical_report.py
```

Optional local RapidOCR:

```powershell
python -m pip install -e ".[ocr]"
$env:IDP_OCR_PROVIDER = "rapidocr"
```

Use three terminals for the current local prototype. Start each command in its watch/development
mode; starting the API or worker without a watcher does not make an already-running process reload
when source files change:

```powershell
# API - reload when backend application code changes
.\.venv\Scripts\python.exe -m uvicorn idp.api.app:app --reload --reload-dir .\backend\idp --port 8001 --no-access-log

# Worker - watch backend Python files and restart the worker process
.\.venv\Scripts\python.exe -m watchfiles --filter python ".\.venv\Scripts\python.exe -m idp.worker" .\backend\idp

# Frontend - Vite HMR for UI source changes
Set-Location frontend
npm.cmd install
npm.cmd run dev
```

Open `http://localhost:5173` and upload `sample-data/synthetic-medical-report.pdf`.
The Vite server provides browser hot-module replacement. Do not use `vite preview` or a built
`dist/` folder for live UI editing. If services are already running without these watch commands,
stop and start them once in watch mode. Changes to `.env`, dependencies, or process-level settings
still require a manual restart. A worker reload can interrupt a document currently being processed,
so avoid editing backend code while a job is active during a demo.
The Vite development server proxies `/api` to `http://127.0.0.1:8001` by default. To use a
different local API port, set `IDP_API_PROXY_TARGET` before starting Vite, for example:

```powershell
$env:IDP_API_PROXY_TARGET = "http://127.0.0.1:8002"
npm.cmd run dev
```

Local uploads are stored under `sample-data/uploads/` by default. The API creates this
directory when it starts; uploaded documents are kept in its quarantine subfolders until the
worker completes the safety scan. Relative `IDP_OBJECT_ROOT` values are resolved from the
project root, so starting the API and worker from different terminals uses the same location.
Restart both after changing this setting. Failed uploads can be retried from **Documents** after
the worker is running with the same storage root.

With `IDP_OCR_PROVIDER=none`, native-text PDFs process and image-only documents fail safely. RapidOCR is a local/dev adapter, not approval for production use.

### Individual KYC form workflow

In an open case, select **Individual KYC** in the **Document type** control before choosing
**Add document**. The worker extracts configured personal, contact, next-of-kin, banking,
supporting-document, and consent fields, with source-page citations, then shows them in the KYC
review tabs. Fillable PDF form values are read locally alongside printed page text. Scanned images
require an OCR adapter.

KYC documents always use deterministic local extraction, even when an external model is configured
for medical reports. KYC identity and banking content is not sent to that provider. The **AI
Assistant** tab is a local, evidence-count summary; it does not verify identities, confirm bank
records, or make financial or eligibility decisions. The supplied blank form contains no applicant
values, so it will correctly show fields as not detected until a completed form is uploaded. Use
synthetic/de-identified values for local testing.

### Optional external LLM extraction (local development)

The local settings loader reads `.env` from the project root. External model use is disabled
by default and requires an explicitly allowlisted provider. Only use synthetic/de-identified
documents and an endpoint approved for the data being sent. The `.env` file is git-ignored;
never commit or share its API key.

Create `.env` from the example if needed, then edit it:

```powershell
if (-not (Test-Path .\.env)) { Copy-Item .\.env.example .\.env }
notepad .\.env
```

Replace the existing `IDP_EXTRACTION_PROVIDER=deterministic-local` and
`IDP_ALLOWED_PROVIDERS=deterministic-local` values with **one** provider configuration from
the external-provider examples in `.env.example`. For OpenAI-compatible providers, set
`IDP_MODEL_API_KEY`, `IDP_MODEL_ID`, and an HTTPS chat-completions `IDP_MODEL_ENDPOINT`.
Azure OpenAI additionally requires `IDP_MODEL_API_VERSION`; its endpoint includes the
deployment path. Set `IDP_EXTERNAL_PROVIDER_APPROVED=true` only after the endpoint/model
has been approved for this use.

For an OpenAI-compatible provider, the common names `OPENAI_BASE_URL`, `OPENAI_MODEL`, and
`OPENAI_API_KEY` are also accepted as aliases for `IDP_MODEL_ENDPOINT`, `IDP_MODEL_ID`, and
`IDP_MODEL_API_KEY`. `OPENAI_BASE_URL` may be a base URL (for example, ending in `/v1`) or a
full `/chat/completions` URL. This pipeline uses `OPENAI_MODEL`; `OPENAI_FAST_MODEL` is not
used because there is currently only one model call per document.

Restart both the API and worker from the project root so each loads the updated `.env`.
With an external LLM provider selected, the model is the extraction source: deterministic
regex extraction is not run. Before sending page text to the model, the worker locally masks
common labeled names, age/DOB, contact details, and medical/member/policy identifiers. Masking
preserves character positions so model citations can be mapped back to the original page text
and validated. This is a best-effort pattern-based safeguard, not guaranteed de-identification:
unlabeled names and unusual identifiers may remain. Do not send real patient data unless the
endpoint is approved and a suitable de-identification process has been validated for that data.

The model fills applicable configured fields and selects other explicit facts (up to the
document type's configured limit), which appear in the AI Selected Facts view. The application
validates output types and exact page/excerpt citations before saving results. An invalid
individual field or fact is rejected without discarding other valid, grounded findings. Invalid
AI narrative sections are isolated so valid extracted fields and other validated sections can
still be saved; safe rejection codes are recorded in the audit trail. Provider request, response
JSON, response schema, and citation failures are reported separately without storing raw model
responses. The UI shows confidence, page, and quoted source excerpt; model confidence is
self-reported and is not a calibrated probability. Results still require human review. The
`deterministic-local` provider remains available when no external model is configured.

The approved AI provider also produces a concise report summary, key medical findings, cited
vital observations, source-supported follow-up suggestions, lab values, and explicitly reported
screening factors. Lab and screening entries retain report citations and self-reported confidence.
Screening factors are evidence for reviewer verification only; the application does not compute
decline, loading, eligibility, or coverage actions. The AI must not diagnose, prescribe, or
recommend treatment changes. These items are stored with the extraction run and shown in
**AI Summary**, **Vitals**, **Lab Reports**, and **Knockout Checks**; they are not available for
`deterministic-local` runs.
If extracted medical evidence is present but the main response has no valid summary, the worker
makes a separate concise summary request and validates its exact source citations. Completed
external-provider runs that still have no summary can be reprocessed with **Generate AI summary**
in the Summary view; this resends the locally redacted page text to the configured provider.

The **Vitals** view always lists blood pressure, pulse/heart rate, respiratory rate, and body
temperature. It shows a report value and citation when extracted, otherwise it says the value
was not detected in that run. General adult reference ranges are informational only, vary by
individual context, and are not diagnostic thresholds.

## Current prototype CLI

```powershell
idp validate-config .\config\document-types\medical-report.v1.json
idp process .\sample-data\synthetic-medical-report.pdf .\var\standalone-result.json
```

Deterministic runs are labelled `deterministic-local`, never AI.

## Validation

Backend:

```powershell
.\.venv\Scripts\python.exe -m ruff check backend
.\.venv\Scripts\python.exe -m ruff format --check backend
.\.venv\Scripts\python.exe -m pytest
```

Frontend:

```powershell
cd frontend
npm test
npm run build
npm audit
```

OpenAPI prototype artifact:

```powershell
.\.venv\Scripts\python.exe scripts\export_openapi.py
```

The OpenAPI artifact must move to generic `/api/v1/idp` routes before Launchpad integration.

## Document configuration direction

The medical definition under `config/document-types/` is the initial contract. The generic target adds:

- classification thresholds and uncertainty policy;
- extraction strategy and versioned prompt/checksum;
- field descriptions, named normalizers/validators, and UI hints;
- bounded allowed additional-fact categories;
- draft/validated/evaluated/approved/active/retired lifecycle;
- golden-set approval per version.

A future type should need only its configuration, prompt/output schema, deterministic validation, golden set, approval, and consumer display mapping. Core orchestration/provider/storage code must remain unchanged.

## Security limitations of the local prototype

- `DevelopmentBasicScanner` only detects the standard EICAR test marker. It is not a production malware scanner.
- Local filesystem and SQLite adapters are for tests/development. Production configuration is fail-closed until S3/SQS/approved scanner adapters and PostgreSQL migrations are complete.
- Demo authentication is not a production IdP/BFF.
- External model processing stays blocked until endpoint/deployment/region and privacy/security/provider terms are approved.
- No architecture alone establishes legal or regulatory certification.

Use only synthetic/de-identified data until the gates in `plan.md` and `aws-deployment-plan.md` are complete.
