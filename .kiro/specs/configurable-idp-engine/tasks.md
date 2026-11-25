# Configurable IDP Engine Implementation Tasks

> This task plan supersedes engine work formerly embedded in the MMIL page spec. The existing code is a local vertical prototype; tasks below migrate it without losing test coverage or provenance.

- [ ] 1. Establish the generic IDP contracts
  - [ ] 1.1 Replace MMIL/case terminology in core settings, package metadata, API title, and domain interfaces with Consumer, ExtractionRequest, ExternalReference, Document, and ExtractionResult.
    - Keep MMIL names only under the static consumer adapter.
    - _Requirements: 1.1, 1.2, 1.3_
  - [ ] 1.2 Extend the document-definition model with classification policy, extraction strategy, field descriptions, named normalizers/validators, prompt checksum/reference, UI hints, and bounded additional-fact policy.
    - Reject duplicate/incompatible/unbounded definitions and compute a canonical checksum.
    - _Requirements: 5.1, 5.2, 5.4_
  - [ ] 1.3 Expand medical schema `1.0.0` with report/sample identifiers/dates, medications, full configured vitals and laboratory groups, while preserving non-null citation requirements.
    - Do not encode diagnostic/loading/underwriting logic.
    - _Requirements: 8.2, 8.5, 9.1, 9.3_
  - [ ] 1.4 Define and check in the generic OpenAPI request, status, result, source-grant, type-list, and problem contracts under `/api/v1/idp`.
    - _Requirements: 1.1, 3.2, 11.1, 11.2, 11.3, 11.4_

- [ ] 2. Decouple persistence from the MMIL consumer
  - [ ] 2.1 Add Consumer and ExtractionRequest entities; change Document, job, run, page, field, idempotency, and audit ownership to consumer/tenant/extraction IDs.
    - Encrypt/hash the opaque external reference according to lookup needs.
    - _Requirements: 1.1, 1.2, 1.4, 12.4, 13.1_
  - [ ] 2.2 Add DocumentTypeDefinition lifecycle/checksum persistence and immutable historical lookup.
    - _Requirements: 5.2, 5.3, 5.4_
  - [ ] 2.3 Add AdditionalFact persistence, primary-field link/deduplication, citations, validations, and bounds.
    - _Requirements: 8.3, 8.4, 8.6, 9.1, 9.5_
  - [ ] 2.4 Split IDP processing audit from MMIL human-review records; remove Case and EvidenceReview from the final core schema only after adapter migration.
    - _Requirements: 1.3, 13.1, 13.2, 13.3_
  - [ ] 2.5 Add Alembic expand/contract migrations, `idp_dev` role/grants, conservative pools, and audit UPDATE/DELETE trigger tests for PostgreSQL 17.
    - _Requirements: 12.2, 13.2_

- [ ] 3. Implement S3 upload and source grants
  - [ ] 3.1 Add an ObjectStore interface and S3 implementation using the existing files bucket and generated `idp/dev/<tenant-hash>/<document-id>/...` keys.
    - Scope IAM/presigned methods; never put business names in keys.
    - _Requirements: 3.1, 3.2, 12.1, 12.4, 13.3_
  - [ ] 3.2 Implement create-upload and completion verification for S3 version, size, checksum/hash, media signature, parser, encryption, page, and pixel rules.
    - Keep local object storage for tests only.
    - _Requirements: 3.2, 3.3, 3.4_
  - [ ] 3.3 Preserve multi-key/content-hash idempotency under concurrent requests and add property tests.
    - _Requirements: 3.5_
  - [ ] 3.4 Implement authorized, five-minute, immutable-version source GET grants with no-store responses and redacted URL logging.
    - _Requirements: 11.4, 13.1, 13.3_

- [ ] 4. Implement dedicated SQS orchestration
  - [ ] 4.1 Add Queue interface plus SQS implementation for the new IDP queue; serialize only message version and opaque IDs.
    - Keep database/local queue adapter for tests.
    - _Requirements: 4.1, 13.3_
  - [ ] 4.2 Expand the lifecycle transition table and durable checkpoints for upload, scan, text, classify, extract, validate, review-required/completed, failure, cancellation.
    - _Requirements: 4.2, 4.3_
  - [ ] 4.3 Implement SQS visibility extension, delete-after-commit, bounded retries, three-receive DLQ, and audited bounded replay.
    - Add duplicate-delivery/crash recovery integration tests.
    - _Requirements: 4.3, 4.4, 4.5, 13.1_
  - [ ] 4.4 Add a transactional outbox/reconciliation path for DB/S3/SQS failure windows.
    - _Requirements: 4.3, 9.5_

- [ ] 5. Complete configurable classification and extraction
  - [ ] 5.1 Implement consumer-enabled type classification with scores, minimum/separation policy, explicit compatible override, and `type_selection_required`.
    - _Requirements: 6.1, 6.2, 6.3, 6.4_
  - [ ] 5.2 Refactor the existing native PyMuPDF/RapidOCR path behind shared typed interfaces and pin/record exact versions/timing/confidence.
    - Add scanned-PDF/image resource-limit tests at one-document concurrency.
    - _Requirements: 7.1, 7.2, 7.3, 13.5, 14.1_
  - [ ] 5.3 Implement model structured-output parsing for primary fields and additional facts with field/category allowlists, item limits, type checks, deduplication, and exact citation validation.
    - _Requirements: 8.1, 8.3, 8.4, 8.6, 9.1, 9.2, 9.4_
  - [ ] 5.4 Build nested `data` deterministically from authoritative flat fields and serialize complete classification/contract/run/issues metadata.
    - _Requirements: 9.5, 11.1, 11.2, 11.3_
  - [ ] 5.5 Add a second synthetic document type fixture and prove configuration-only processing without core pipeline edits.
    - _Requirements: 5.5, 14.3_

- [ ] 6. Align model and OCR providers to Launchpad services
  - [ ] 6.1 Rename the OpenAI-compatible adapter to explicit Azure/OpenAI configuration and require approved HTTPS endpoint, API version, deployment, region, and `externalProviderApproved` gate.
    - _Requirements: 10.1, 10.2, 10.5_
  - [ ] 6.2 Inject the existing OpenAI key into worker only; confirm API configuration cannot resolve/read it.
    - _Requirements: 10.3, 12.4_
  - [ ] 6.3 Disable Textract and Bedrock construction in Launchpad dev policy and retain future adapters behind explicit unsupported configuration.
    - _Requirements: 7.4, 10.1, 10.4_
  - [ ] 6.4 Add fake Azure contract tests for timeout, throttle, redirects, malformed output, unsupported facts, prompt injection, and no fallback; never send test documents to a live provider.
    - _Requirements: 8.5, 8.6, 10.2, 10.4, 10.5_

- [ ] 7. Implement private IDP API and BFF service context
  - [ ] 7.1 Implement `/api/v1/idp/extractions` create/complete/status/result/retry/source-url routes and document-type list/validate routes.
    - Keep old case routes only as a temporary compatibility adapter.
    - _Requirements: 1.1, 3.2, 4.1, 11.1, 11.4_
  - [ ] 7.2 Implement signed service-context verification with issuer/audience/consumer/tenant/subject/permissions/reference/expiry/nonce/correlation validation.
    - Strip and reject unsigned browser identity assertions in deployed mode.
    - _Requirements: 2.1, 2.2, 2.3, 2.4_
  - [ ] 7.3 Provide a thin Launchpad BFF client/route contract that authorizes MMIL and proxies generic responses without extraction logic.
    - This code must be merged in the owning Launchpad API repository when supplied.
    - _Requirements: 1.3, 2.1, 2.2_
  - [ ] 7.4 Add consumer/tenant/external-reference isolation and forged/expired/replayed context tests.
    - _Requirements: 1.4, 2.3, 2.4, 2.5_

- [ ] 8. Add the Launchpad-aligned CDK resources
  - [ ] 8.1 Obtain/import the actual Launchpad CDK source or reviewed outputs for VPC/subnets, API/RDS SGs, RDS/master secret, files bucket, KMS key, and private namespace.
    - Do not guess generated identifiers or use unavailable direct SSM reads.
    - _Requirements: 12.1, 12.3_
  - [ ] 8.2 Add `Launchpad-dev-Idp` API/worker ECS services, private discovery, dedicated SGs, IDP queue/DLQ, DB/service-auth secrets, log groups, dashboards, and alarms.
    - API 0.5 vCPU/1 GB; worker 1 vCPU/2 GB/concurrency one.
    - _Requirements: 2.5, 12.2, 13.4, 13.5_
  - [ ] 8.3 Add least-privilege API/worker/execution/migration role policies and IaC assertions proving no unrelated bucket/queue/Transcribe/model-key access.
    - _Requirements: 10.3, 12.4_
  - [ ] 8.4 Modify Launchpad API stack for service-auth secret and IDP SG egress; keep existing ALB/CloudFront/WAF/session ingress unchanged.
    - _Requirements: 2.1, 2.5, 12.1, 12.3_
  - [ ] 8.5 Use `ContainerImage.fromAsset`, ASCII SG descriptions, existing bootstrap roles, and safe stack outputs; validate synth/diff without deploying.
    - _Requirements: 12.5_

- [ ] 9. Convert the MMIL page into a pure consumer
  - [ ] 9.1 Change the frontend API module to consume generic IDP/BFF status/result/source-grant contracts and map medical paths only in presentation components.
    - Remove assumptions that the UI/API owns extraction persistence.
    - _Requirements: 1.3, 11.5_
  - [ ] 9.2 Render configured primary medical fields, applicable additional facts, missing/uncertain/conflict states, and run provenance without diagnosis or underwriting guidance.
    - _Requirements: 8.2, 8.3, 8.5, 11.1, 11.5_
  - [ ] 9.3 Preserve the mock-derived static layout and side-by-side citation viewer using IDP-issued immutable source URLs.
    - _Requirements: 11.4, 11.5_
  - [ ] 9.4 Move human review persistence to the MMIL/BFF boundary or keep it read-only until its owner contract is approved.
    - _Requirements: 1.3_

- [ ] 10. Verify and release the reusable engine
  - [ ] 10.1 Add unit/property tests for all correctness properties, especially service-context isolation, queue-body redaction, registry checksum, classification thresholds, facts bounds/deduplication, and grounding.
    - _Requirements: 2.3, 3.5, 4.3, 5.4, 6.2, 8.6, 9.2, 10.2, 13.3_
  - [ ] 10.2 Add S3/SQS/PostgreSQL integration tests for complete pipeline, duplicate delivery, visibility, crash, DLQ/replay, grants, audit trigger, and reconciliation.
    - _Requirements: 3.3, 4.1, 4.3, 4.4, 4.5, 9.5, 13.2_
  - [ ] 10.3 Build medical golden evaluation for native/scanned/rotated/table/adversarial documents and report per-field/classification/citation/additional-fact metrics.
    - _Requirements: 5.3, 6.1, 7.2, 8.2, 8.3_
  - [ ] 10.4 Run backend/frontend/IaC checks, OpenAPI compatibility, runtime/container/dependency scans, synthetic end-to-end BFF→IDP→UI smoke, and no-PHI telemetry scan.
    - _Requirements: 12.1–12.5, 13.1–13.5, 14.4_
  - [ ] 10.5 Update runbooks for provider outage, OCR limits, queue/DLQ, bad config/model, data exposure, restore/reconcile, retention/deletion, and rollback.
    - _Requirements: 4.5, 7.3, 10.4, 13.4_
