# Configurable Intelligent Document Processing Engine — Product and Engineering Plan

## 1. Authoritative architecture decision

The primary product is a reusable **Intelligent Document Processing (IDP) engine**. It accepts a document plus tenant/application context, classifies the document, extracts a versioned document-specific contract, returns additional grounded facts, and preserves page-level provenance. It is not an MMIL underwriting application.

The MMIL medical-evidence page is one static consumer of the IDP response. It may arrange medical fields into Summary, Vitals & BMI, Lab Results, Configured Checks, and AI Extraction Summary and display the uploaded document beside them. It does not contain extraction logic, prompts, schema rules, OCR logic, or an independent evidence store.

This decision supersedes case-workbench coupling in earlier revisions of this plan:

- IDP uses neutral terms such as `ExtractionRequest`, `Consumer`, `ExternalReference`, `Document`, and `ExtractionResult`.
- MMIL case IDs, applicant names, products, workflow stages, review panels, and styling belong to the consumer/BFF layer.
- The stable integration boundary is the versioned IDP API and result contract.
- New document families are added through validated configuration, prompts/evaluations, and UI mapping at the consumer. They do not require a new extraction engine.

## 2. Purpose and scope

Build a multi-tenant, asynchronous document extraction microservice with these capabilities:

- Receive PDF, JPEG, PNG, and TIFF documents through an authorized upload session.
- Preserve an immutable source version and content hash.
- Extract native text first and OCR image-only pages.
- Classify against enabled document-type configurations.
- Use an approved LLM deployment to propose schema-constrained candidates and additional source-backed facts.
- Validate every non-null result against retained page text and citations.
- Return one document-specific response containing typed configured fields, additional facts, uncertainty, validation findings, and complete run metadata.
- Support new document types by adding versioned configuration and a document-specific golden set.
- Expose the same application pipeline to HTTP workers and a standalone Python package/CLI.

### Focused MVP

- Reusable IDP API and worker.
- Medical report document type version `1.0.0` as the first configured contract.
- Generic `additional_facts` output for explicit document details outside the primary field contract.
- Native PDF extraction and containerized OCR for scanned pages/images in the Launchpad dev environment.
- Approved Azure OpenAI/OpenAI-compatible provider adapter, gated by explicit endpoint, deployment, region/data-handling approval, and the existing Secrets Manager key.
- Deterministic local provider for tests only, always identified as `deterministic-local`.
- S3 upload/result artifact storage, SQS processing, PostgreSQL metadata/results, and append-only audit.
- MMIL static medical page as a read-only presentation and human-review consumer, including side-by-side source viewing.

### Explicitly out of scope for this release

- Dashboard, queues, financial/occupation/compliance/reinsurance underwriting, simulator, decision cockpit, Ask AI, policy issuance, claims, and servicing workflows from the reference mock.
- Diagnosis, treatment advice, underwriting eligibility, risk rating, loading, coverage, or autonomous decisions.
- Sending health data to an external model before provider/data residency/retention/contract approval.
- Using the existing Launchpad `prototype`, `index`, `pdf_export`, or other unrelated queues for IDP jobs.
- Reusing broad Launchpad API/worker task roles for IDP. IDP receives dedicated least-privilege roles.
- Textract or Bedrock in the current Launchpad dev path. The supplied IAM permissions include neither service.
- Deploying the undeployed `Launchpad-dev-Preview` stack.

## 3. System boundaries

### IDP owns

- Consumer registration and tenant-scoped service authorization.
- Upload session creation and immutable document identity.
- File signature/size/page/pixel/encryption validation and quarantine state.
- Job state, idempotency, retry, DLQ correlation, and stage metrics.
- Native text extraction, OCR adapter selection, classification, schema registry, prompts, model routing, normalization, validation, and citation verification.
- Versioned extraction results and additional facts.
- Source-document access grants and IDP audit events.
- Standalone processing package/CLI.

### MMIL consumer owns

- Cognito/session login and end-user authorization to an MMIL case.
- Mapping an MMIL case to an opaque IDP `external_reference`.
- Upload interaction and polling the IDP job through the Launchpad API BFF.
- Presentation labels, tabs, cards, filters, side-by-side document viewing, and human review UX.
- Any MMIL-specific accepted-evidence record or downstream case workflow.

### Launchpad API BFF owns

The existing Launchpad API remains the browser-facing authentication boundary because the deployed Cognito client is confidential and the static SPA cannot safely hold its client secret. The BFF:

1. Validates the existing Cognito-backed session and MMIL case authorization.
2. Calls the private IDP API with a short-lived signed service context containing consumer, tenant, subject, roles, and opaque external reference.
3. Proxies the IDP response without reimplementing extraction or changing field meaning.
4. Returns pre-signed upload/source URLs generated by IDP where required.

A dedicated IDP service-auth secret is shared only with the Launchpad API and IDP API tasks. Browser-supplied identity headers are never trusted.

## 4. Primary workflow

1. The MMIL static page asks the Launchpad API BFF to create an extraction for an authorized case and file metadata.
2. The BFF calls `POST /api/v1/idp/extractions` on the private IDP API with tenant/consumer context.
3. IDP validates the request, creates an immutable extraction/document identity, writes an S3 object key under the IDP prefix, and returns a short-lived scoped PUT URL.
4. The browser uploads directly to the existing encrypted files bucket. Its current CORS rule permits the deployed CloudFront origin.
5. The browser calls the BFF completion route. IDP verifies S3 version, size, media signature, and SHA-256, then sends an IDs-only message to the IDP SQS queue.
6. The IDP worker scans/validates the source, extracts native page text, OCRs pages with insufficient text, and classifies the document against enabled definitions.
7. The selected extraction strategy sends only approved content to one allowlisted model. The model proposes configured fields and additional facts. Document content is untrusted data and cannot change tools, provider, schema, tenant, or destination.
8. IDP normalizes values and rejects every unsupported result. Each non-null value/fact must cite the same immutable document version, a valid page, and an exact retained excerpt.
9. IDP stores the immutable run and result, updates status to `review_required` or `completed`, and emits redacted audit/metrics.
10. The static UI polls through the BFF and renders the IDP response. Selecting a citation requests a short-lived GET URL and displays the source beside the field.
11. Human decisions remain in the MMIL consumer contract unless a generic IDP review module is enabled. IDP extraction candidates are never silently converted into underwriting decisions.

## 5. Functional requirements and acceptance

| ID | Requirement | Acceptance |
|---|---|---|
| IDP-FR-01 | Consumer-neutral request | Core endpoints contain no MMIL applicant, product, or workflow fields. They accept tenant/consumer identity from trusted service context and an opaque external reference. |
| IDP-FR-02 | Secure upload session | Reject unauthorized, oversized, unsupported, signature-mismatched, encrypted, corrupt, over-page, or over-pixel uploads. Verify S3 object version/size/hash before enqueue. |
| IDP-FR-03 | Idempotency | The same consumer/tenant/idempotency key and content resolves to one extraction. Reuse with different content returns 409. Same-hash duplicate uploads may resolve to the existing immutable document with a recorded key mapping. |
| IDP-FR-04 | Async lifecycle | States are `created`, `uploading`, `uploaded`, `scanning`, `text_extraction`, `classifying`, `extracting`, `validating`, `review_required`, `completed`, `failed`, or `cancelled`. SQS retries do not duplicate runs/results. |
| IDP-FR-05 | Configurable types | A versioned definition controls classifier hints, accepted media/page constraints, primary fields, types, descriptions, units, requiredness, normalizers, validators, citation policy, prompt reference, and consumer UI hints. Invalid definitions cannot activate. |
| IDP-FR-06 | Medical primary contract | Medical `1.0.0` includes report date, patient/document identifiers where permitted, height, weight, BMI, blood pressure, pulse, tobacco, alcohol, conditions/history, family history, medications, ECG/TMT, glucose/HbA1c, lipid, liver, kidney, and screening fields. Missing fields are explicit. |
| IDP-FR-07 | Complete grounded response | Return configured fields plus `additional_facts` for explicit relevant details not represented by the primary schema. Each fact has a stable run-local ID, name, category, typed/literal value, confidence, and citation. No citation means no non-null fact. |
| IDP-FR-08 | LLM extraction | In an approved environment, the configured LLM proposes candidates under a strict structured-output contract. “LLM extraction” never means unsupported assumption or inference; values must be explicitly grounded in the document. |
| IDP-FR-09 | OCR | Prefer native PDF text. OCR scanned pages/images with the configured container OCR adapter in Launchpad dev. Record engine/version/page confidence. Fail explicitly when OCR is unavailable or resource limits are exceeded. |
| IDP-FR-10 | Document-specific result | Result identifies detected/requested document type, classification confidence, schema version, extraction status, nested primary data, flat fields, additional facts, missing/uncertain/conflicting fields, citations, and run/provider metadata. |
| IDP-FR-11 | Extensibility | Adding a future type requires configuration, prompt/schema version, validation, golden documents, thresholds, and activation approval; no edits to orchestration/provider/storage code. |
| IDP-FR-12 | Tenant isolation | Every extraction, object key, queue message, DB query, source URL, and result is tenant/consumer scoped and denied by default. |
| IDP-FR-13 | Audit/privacy | Upload, processing, provider/schema/model version, source access, retry, result access, and configuration activation are append-only audited without document text or extracted values. |
| IDP-FR-14 | API/CLI parity | Worker, HTTP service, and CLI call the same typed extraction pipeline and document registry. |
| IDP-FR-15 | MMIL presentation | The static MMIL UI renders IDP results without its own extraction logic and can select the cited original/document page side by side. |

## 6. Configurable document-type contract

A document type is code-reviewed configuration, not a free-form runtime prompt. Definitions are immutable once activated.

```json
{
  "document_type": "medical_report",
  "schema_version": "1.0.0",
  "display_name": "Medical report",
  "classification": {
    "hints": ["medical examination report", "laboratory results"],
    "minimum_confidence": 0.80,
    "on_uncertain": "require_type_selection"
  },
  "constraints": {
    "media_types": ["application/pdf", "image/jpeg", "image/png", "image/tiff"],
    "max_pages": 200
  },
  "extraction": {
    "strategy": "llm_with_deterministic_validation",
    "prompt_version": "medical-report-1.0.0",
    "capture_additional_facts": true
  },
  "fields": [
    {
      "path": "observations.blood_pressure",
      "label": "Blood pressure",
      "description": "Explicit systolic and diastolic observation",
      "data_type": "measurement_pair",
      "unit": "mmHg",
      "required": false,
      "citations_required": true,
      "ui": {"section": "vitals", "group": "Vitals"},
      "normalizers": ["trim", "measurement_pair"],
      "validators": ["type"]
    }
  ],
  "additional_facts": {
    "enabled": true,
    "allowed_categories": ["medication", "history", "observation", "laboratory", "note"],
    "citations_required": true,
    "max_items": 100
  }
}
```

### Configuration lifecycle

`draft → validated → evaluated → approved → active → retired`

- Activation pins configuration checksum, schema, prompt, provider policy, and golden-set report.
- Existing extraction runs always resolve their historical version/checksum.
- Breaking primary-contract changes require a new major schema version.
- Additional facts never become stable primary fields automatically. Frequently used facts are promoted only through a reviewed schema version.

## 7. Generic API contract

Browser traffic reaches these logical routes through the Launchpad BFF. The private IDP service exposes the same paths and accepts only signed service context.

| Method and route | Purpose |
|---|---|
| `POST /api/v1/idp/extractions` | Create an extraction and scoped upload session. Request contains file metadata, optional requested document type, opaque external reference, and idempotency key. |
| `POST /api/v1/idp/extractions/{extraction_id}/complete` | Verify immutable S3 upload and enqueue the IDs-only SQS message. |
| `GET /api/v1/idp/extractions/{extraction_id}` | Return safe status, classification, stage timestamps, attempt count, and failure code. |
| `GET /api/v1/idp/extractions/{extraction_id}/result` | Return the complete versioned document-specific extraction response. |
| `POST /api/v1/idp/extractions/{extraction_id}/retry` | Requeue an eligible failed extraction idempotently. |
| `POST /api/v1/idp/extractions/{extraction_id}/source-url` | Return a short-lived scoped GET URL for an authorized immutable source version. |
| `GET /api/v1/idp/document-types` | Return enabled type IDs and active versions; no prompts or secrets. |
| `POST /api/v1/idp/document-types/validate` | Administrator/CI validation of a draft definition. Activation remains a controlled deployment action for MVP. |
| `GET /api/v1/idp/health/live` | Process liveness. |
| `GET /api/v1/idp/health/ready` | DB/S3/SQS/config dependency readiness without secret disclosure. |

### Result shape

```json
{
  "extraction_id": "ext_...",
  "external_reference": "opaque-consumer-reference",
  "status": "review_required",
  "document": {
    "id": "doc_...",
    "version": 1,
    "sha256": "...",
    "media_type": "application/pdf",
    "page_count": 12
  },
  "classification": {
    "requested_type": null,
    "detected_type": "medical_report",
    "confidence": 0.97,
    "state": "classified"
  },
  "contract": {
    "document_type": "medical_report",
    "schema_version": "1.0.0",
    "configuration_checksum": "sha256:..."
  },
  "data": {
    "observations": {
      "blood_pressure": {"systolic": 128, "diastolic": 82}
    },
    "labs": {"hba1c": 5.4}
  },
  "fields": [
    {
      "path": "labs.hba1c",
      "source_literal": "5.4",
      "value": 5.4,
      "unit": "%",
      "status": "found",
      "confidence": 0.96,
      "citations": [{"document_version": 1, "page": 4, "excerpt": "HbA1c 5.4 %", "bbox": null}]
    }
  ],
  "additional_facts": [
    {
      "id": "fact_...",
      "name": "Medication",
      "category": "medication",
      "source_literal": "Amlodipine 5 mg once daily",
      "value": "Amlodipine 5 mg once daily",
      "confidence": 0.92,
      "citations": [{"document_version": 1, "page": 2, "excerpt": "Medication: Amlodipine 5 mg once daily"}]
    }
  ],
  "issues": [],
  "run": {
    "run_id": "run_...",
    "ocr_engine": "rapidocr",
    "ocr_version": "...",
    "provider": "azure-openai",
    "model_deployment": "approved-pinned-deployment",
    "prompt_version": "medical-report-1.0.0",
    "started_at": "...",
    "completed_at": "..."
  }
}
```

The nested `data` object is convenient for consumers. The flat `fields` list is authoritative for status, provenance, and review. The response does not return hidden chain-of-thought or model rationale.

## 8. Launchpad dev deployment mapping

Target: AWS account and Mumbai region supplied by the platform owner, environment `dev`.

### Reuse unchanged

- `Launchpad-dev-Network`: VPC, two-AZ subnets, NAT, S3/Secrets Manager/KMS/SQS/ECR/Logs endpoints, and flow logs.
- `Launchpad-dev-Data`: existing data KMS key and `launchpad-dev-files` bucket.
- RDS PostgreSQL 17 instance, with a new IDP schema/database role rather than broad use of `launchpad_dev`.
- `Launchpad-dev-Auth`: existing user pool/session flow at the Launchpad BFF.
- Existing public ALB, regional WAF, CloudFront distribution, CloudFront WAF, and `/api/*` behavior for browser-to-BFF traffic.
- Existing `launchpad/dev/openai-api-key` only after provider approval; only the IDP worker may read it.
- CDK bootstrap and `ContainerImage.fromAsset`, because the deploying user cannot call `ecr:GetAuthorizationToken`.

### Add as IDP-specific resources

Prefer a separate `Launchpad-dev-Idp` nested/application stack, or equivalent constructs in the owning Launchpad stacks:

| Resource | Dev design |
|---|---|
| ECS cluster | `launchpad-dev-idp`, Container Insights enabled. A separate cluster makes ownership and scaling explicit. |
| IDP API service | 1 Fargate task, 0.5 vCPU / 1 GB, private-egress subnets, no public IP, circuit breaker/rollback. Ingress 8000 only from the existing Launchpad API security group through private service discovery. |
| IDP worker service | 1 Fargate task initially, **1 vCPU / 2 GB** because local OCR and PDF rasterization are memory-sensitive. Private-egress, no ingress, circuit breaker/rollback. Benchmark before reducing. |
| Queue | `launchpad-dev-idp` plus `launchpad-dev-idp-dlq`, KMS encrypted, IDs-only messages, 14-day DLQ retention, redrive after 3 receives, visibility timeout based on measured max document time. Do not use the ten existing business queues. |
| S3 namespace | Existing `launchpad-dev-files` bucket under generated `idp/dev/<tenant-hash>/<document-id>/...` keys. No case names or filenames in keys. Lifecycle/retention requires product approval. |
| Database | New `idp` schema and `idp_dev` role on the existing PostgreSQL 17 instance. Runtime CRUD only on IDP tables; audit table INSERT/SELECT only plus update/delete trigger. Migration container uses the existing master secret only during startup. |
| Secrets | New generated `IdpDbUserSecret` and `IdpServiceAuthSecret`; reuse OpenAI key secret for worker only. Do not give the API model-key access. |
| Discovery | Private ECS Service Connect/Cloud Map name for Launchpad API → IDP API. Security-group ingress is source-SG scoped. |
| Logs/alarms | Separate API/worker log groups, one-month dev retention, queue age/depth, DLQ, extraction failure, OCR/model latency, throttling, and cost metrics. No document text/values. |

### Required changes to existing Launchpad owners

Because the deployed `infra/` source is not present in this workspace, these changes must be merged into the owning repository rather than guessed from physical IDs:

1. Add BFF routes for `/api/v1/idp/*` that preserve the existing browser session authorization and proxy to the private IDP service.
2. Grant the Launchpad API task read access to `IdpServiceAuthSecret` and network egress to the IDP API security group on port 8000.
3. Import/reuse the VPC, private-egress subnets, data-subnet RDS security group, KMS key, files bucket, RDS master/app secrets, API security group, and user pool through stack references/outputs.
4. Build IDP API/worker images with `ContainerImage.fromAsset`; do not require direct `docker login`.
5. Deploy the MMIL static bundle to the existing `launchpad-dev-web` bucket. Existing CloudFront `/api/*`, SPA rewrite, WAF, TLS, and response headers remain in force.

### Permissions

**IDP API task role**

- S3: generated-prefix `PutObject` only for pre-signed upload, `GetObject` only for authorized source URL/result validation, and minimal list/head permissions on the files bucket IDP prefix.
- SQS: `SendMessage`, `GetQueueAttributes`, `GetQueueUrl` on the IDP queue only.
- KMS: only operations required for the IDP S3 prefix and queue.
- Secrets: runtime DB secret and IDP service-auth secret only.
- No OpenAI key, Transcribe, unrelated buckets, or existing queues.

**IDP worker task role**

- SQS consume/delete/change-visibility/send on IDP queue/DLQ only.
- S3 read immutable originals and write IDP derived artifacts/results under the IDP prefix. Delete only if an approved retention job requires it.
- KMS for those resources.
- Secrets: IDP DB secret and approved OpenAI key only.
- HTTPS egress through NAT. Because the supplied platform has no domain-filtering egress proxy, application endpoint allowlisting and monitoring are mandatory and the residual egress risk is documented.

**Migration container**

- Read RDS master and IDP runtime secrets.
- Run Alembic and role/schema grants, then exit successfully before API starts.
- The API/worker never receive the master secret.

## 9. OCR and model strategy for available services

### OCR

The supplied roles do not include Textract, so Launchpad dev uses:

1. PyMuPDF native text and page blocks.
2. Quality threshold per page.
3. RapidOCR/ONNX inside the worker for image-only pages and images.
4. Recorded OCR version/confidence and strict pixel/page/time/resource limits.

The worker starts at 1 vCPU / 2 GB and processes one document concurrently until benchmarks show safe higher concurrency. If local OCR misses quality/SLO gates, adding Textract requires a separate platform approval and IAM/data-flow change; it is not silently enabled.

### LLM

The only supplied model secret is Azure OpenAI/OpenAI-compatible. Dev configuration therefore supports one explicit provider:

- Endpoint, API version, deployment/snapshot, and provider region are deployment configuration.
- Key comes from `launchpad/dev/openai-api-key` through Secrets Manager.
- `external_provider_approved=false` blocks document calls until privacy/security approval is recorded.
- No fallback to Bedrock/Claude or another endpoint.
- Structured output includes configured field candidates and bounded additional facts.
- Every response is parsed, type-checked, allowlisted by field/category, and citation-verified before persistence.
- Temperature is zero, tools are absent, and documents are delimited as untrusted input.

Provider access does not justify unsupported “LLM assumptions.” The engine extracts explicit evidence and reports uncertainty; it does not invent missing medical values.

## 10. Data model

- `Consumer`: stable ID, tenant policy, auth audience, enabled types, quotas.
- `ExtractionRequest`: consumer/tenant, opaque external reference, idempotency mapping, requested/detected type, lifecycle, timestamps, safe failure code.
- `Document`: immutable S3 key/version, SHA-256, media type, size, pages, quarantine/clean state, retention class.
- `UploadIdempotency`: consumer/tenant/key, content hash, extraction/document IDs.
- `ProcessingJob`: extraction/document IDs, stage, attempt, lease/SQS receipt metadata, timestamps, correlation ID.
- `DocumentTypeDefinition`: version/checksum/status, constraints, fields, additional-fact policy, prompt/evaluation references.
- `ExtractionRun`: document/config/provider/model/prompt/OCR versions, status, latency/tokens/cost.
- `DocumentPage`: sensitive retained text/blocks and OCR provenance.
- `ExtractedField`: configured path, literal, normalized typed value, unit, status, confidence, citations, validations.
- `AdditionalFact`: run-local ID, name/category, literal/typed value, confidence, citations, validations.
- `AuditEvent`: append-only actor/service action metadata without content/values.

MMIL `Case` and `EvidenceReview` are consumer entities and should move out of the reusable IDP schema. A generic review extension may be defined later, but it cannot encode underwriting semantics.

## 11. Security, privacy, and safety

- Health and insurance documents are sensitive. Complete DPDP/insurance/customer reviews, provider terms, region, retention, deletion, incident, and data-residency approvals before real data.
- Browser identity terminates at the Launchpad BFF. IDP accepts only signed, expiring service context from allowlisted consumers and checks tenant/external-reference ownership on every operation.
- SQS messages contain opaque IDs only. S3 keys contain generated/hash segments only. No PHI in URLs, logs, metrics, traces, tags, task environment values, or audit metadata.
- Use existing KMS encryption for S3, SQS, and RDS. Keep RDS isolated and tasks private.
- Validate file signatures and parser limits, reject encryption/corruption, malware-scan through an approved production control, isolate parsers, and never render active content.
- Pre-signed URLs are short-lived, method-specific, object/version-specific, tenant-authorized, and audited when issued.
- Model content is untrusted and cannot invoke tools. Validate exact excerpts against retained pages and reject unsupported provider output atomically.
- Human consumers own interpretation and action. IDP returns extraction evidence only.

## 12. Test and release strategy

1. **Registry contract:** valid/invalid configuration, semantic version/checksum, activation lifecycle, breaking-change detection, prompt/model pinning.
2. **File pipeline:** supported signatures, spoofing, encryption, malformed/adversarial files, page/pixel/decompression/time limits, content hash, S3 version verification.
3. **Classification:** per-type confusion matrix, uncertain threshold, explicit type override authorization, unsupported type behavior.
4. **Extraction:** field-by-field precision/recall and citation correctness on synthetic/de-identified golden sets. Evaluate additional-fact relevance and duplication separately.
5. **Provider:** fake contract tests, malformed JSON, unsupported field/fact, prompt injection, timeout, throttling, endpoint allowlist, approval gate, no fallback.
6. **Async/AWS:** S3 completion → IDP SQS → worker → RDS/result, retries/DLQ, visibility extension, duplicate delivery, worker crash/recovery, S3/RDS reconciliation.
7. **Isolation/auth:** forged BFF headers, expired signatures, tenant/consumer/external-reference cross-access, pre-signed URL scope/expiry.
8. **MMIL consumer:** exact response mapping, empty/uncertain/conflict states, polling, side-by-side citation navigation, authorized source URL, accessibility/responsive behavior.
9. **Operational:** 0.5/1 GB API and 1/2 GB worker load, OCR memory, queue saturation, RDS `db.t3.micro` connections, model quota/cost, backup/restore.
10. **Release:** build with CDK `fromAsset`, synth/diff through bootstrap roles, non-PHI smoke data, explicit deployment approval, circuit-breaker rollback, and dashboard verification.

## 13. Spec-driven delivery phases

| Phase | Deliverables | Exit gate |
|---|---|---|
| 0. Boundary and approvals | IDP/consumer/BFF ownership, data classification, Azure endpoint/deployment/region/terms, OCR benchmark data, retention, threat model. | Platform, product, security/privacy, and document-domain owners approve. |
| 1. Engine contracts | Generic OpenAPI, request/result/status state machine, document registry schema, additional-fact contract, signed service-context contract. | Contract tests and representative medical examples approved. |
| 2. Launchpad integration foundation | IDP ECS/API/worker, dedicated queue/DLQ/roles/secrets, IDP DB schema/role, files-prefix policies, private discovery, BFF proxy. | Nonprod deploy; no public direct IDP access; cross-tenant tests pass. |
| 3. Ingestion and OCR | Pre-signed upload, S3 verification, quarantine/scan interface, native text, RapidOCR, limits/retries. | Native/scanned/image matrix and replay/DLQ tests pass within worker resources. |
| 4. Configurable LLM extraction | Registry lifecycle, medical definition, Azure adapter, primary fields, additional facts, citation/type validation, metrics. | Provider approval and medical golden-set thresholds pass. |
| 5. MMIL consumer | Static focused page maps IDP result and source URLs; no extraction/business logic. | End-to-end upload → IDP response → side-by-side evidence display passes. |
| 6. Hardening | Audit DB restrictions, restore/runbooks, cost/latency alarms, retention/deletion, penetration/privacy testing. | Dev readiness review and controlled pilot approval. |
| 7. New document type | Add one type only through config/prompt/evaluation/UI mapping. | Demonstrates no core-engine code change and meets its own golden thresholds. |

## 14. Decisions and blockers before deployment

Resolved:

- The IDP engine is the reusable product; MMIL is a static consumer.
- Reuse Launchpad network, KMS, files bucket, RDS instance, browser auth/BFF, CloudFront, WAF, and bootstrap.
- Add dedicated IDP ECS services, queue/DLQ, roles, DB role/schema, and secrets.
- Do not use Textract/Bedrock with the supplied permissions.
- Use local container OCR in dev and Azure OpenAI only under an explicit approval gate.
- Use the existing BFF/session boundary instead of exposing the private IDP API directly to the static SPA.

Still required:

1. Provide the actual deployed Launchpad `infra/` source or exported construct IDs/outputs so changes can be merged without guessing VPC subnet, SG, listener/service, RDS, secret, and key references.
2. Confirm the Launchpad API BFF code location and its current signed-session/organization authorization model.
3. Confirm the Azure OpenAI endpoint, API version, pinned deployment, region, model capabilities/context limits, PHI/data-retention approval, and quota. A secret name alone is not approval.
4. Approve RapidOCR for dev and benchmark 1 vCPU / 2 GB against representative scanned documents; identify the production malware scanner.
5. Confirm S3 IDP-prefix retention/deletion/version behavior and whether a dedicated bucket is required by policy.
6. Confirm RDS connection headroom on the single-AZ `db.t3.micro`; use conservative pools and consider a larger instance if API/worker/BFF load requires it.
7. Confirm whether human review remains entirely in MMIL or should later become a generic optional IDP module.
8. Supply at least one additional future document family and golden set to prove configuration-only extensibility.
