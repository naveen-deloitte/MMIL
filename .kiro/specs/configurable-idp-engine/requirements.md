# Configurable IDP Engine Requirements

## Scope

This is the authoritative specification for the reusable document-processing microservice. The MMIL medical page is a consumer and is specified separately under `medical-evidence-workbench`.

The engine extracts explicit document evidence. LLM output is a candidate source, not authority to infer missing facts. Every non-null primary field and additional fact requires source grounding.

## Glossary

- **Consumer**: An authorized application such as MMIL that submits documents and receives IDP results.
- **External reference**: An opaque consumer-owned correlation value; IDP does not interpret it as a case.
- **Primary field**: A stable configured path in a versioned document-type contract.
- **Additional fact**: Explicit relevant document content outside the primary contract, returned in a bounded generic list with citations.
- **Document-type definition**: Immutable versioned configuration for classification, fields, extraction, normalization, validation, prompting, and additional facts.
- **Service context**: Short-lived signed BFF-to-IDP identity containing consumer, tenant, actor, permissions, and allowed external reference.

## Requirement 1: Reusable consumer-neutral boundary

**User story:** As a platform owner, I want IDP independent of MMIL so that other applications and document families can use one engine.

### Acceptance criteria

1.1 WHEN a consumer creates an extraction, THE IDP SYSTEM SHALL accept consumer identity, tenant identity, an opaque external reference, file metadata, and an optional requested document type without requiring MMIL applicant, product, case-stage, or underwriting fields.

1.2 WHEN IDP stores or returns an extraction, THE IDP SYSTEM SHALL preserve the opaque external reference without interpreting its business meaning.

1.3 WHEN MMIL displays a result, THE IDP SYSTEM SHALL remain the source of extraction fields, facts, citations, schema version, and run metadata; the static UI SHALL not execute extraction logic.

1.4 WHEN a new consumer is added, THE IDP SYSTEM SHALL isolate its authentication policy, enabled document types, quotas, and tenant data from every other consumer.

## Requirement 2: Trusted service authorization

**User story:** As a security owner, I want the existing Launchpad session boundary to authorize browser work while IDP remains private.

### Acceptance criteria

2.1 WHEN the static UI calls an IDP browser route, THE LAUNCHPAD BFF SHALL validate the existing Cognito-backed session and consumer resource authorization before contacting IDP.

2.2 WHEN the BFF contacts IDP, THE BFF SHALL provide a signed, expiring service context containing issuer, audience/consumer, tenant, subject, permissions, permitted external reference, issued/expiry time, nonce, and correlation ID.

2.3 WHEN IDP receives a request, THE IDP SYSTEM SHALL validate signature, issuer, audience, expiry, nonce policy, tenant, permission, and external-reference scope and SHALL ignore unsigned browser-supplied identity headers.

2.4 IF service context is absent, invalid, expired, replayed where replay protection applies, or outside scope, THE IDP SYSTEM SHALL return a safe non-enumerating denial without resource metadata.

2.5 WHEN IDP is deployed in Launchpad dev, THE IDP API SHALL have no public ingress and SHALL accept network traffic only from the Launchpad API security group.

## Requirement 3: Immutable upload sessions

**User story:** As a consumer, I want large documents uploaded directly to protected object storage so that application tasks do not buffer full documents.

### Acceptance criteria

3.1 WHEN an authorized extraction is created, THE IDP SYSTEM SHALL generate the S3 key from tenant hash, document UUID, and immutable version without case names, applicant names, or original filenames.

3.2 WHEN an upload session is returned, THE IDP SYSTEM SHALL scope the pre-signed URL to one PUT method, object key/version intent, checksum/content-type conditions where supported, and a configured short expiry.

3.3 WHEN upload completion is reported, THE IDP SYSTEM SHALL verify S3 object/version existence, size, checksum/SHA-256, declared type, magic signature, parser readability, encryption status, page limit, and pixel limit before enqueueing.

3.4 IF validation fails, THE IDP SYSTEM SHALL keep the object quarantined, SHALL not enqueue extraction, and SHALL return a safe failure code.

3.5 WHEN the same consumer/tenant/idempotency key and content are replayed, THE IDP SYSTEM SHALL return the original extraction; IF content differs, THE IDP SYSTEM SHALL return 409 without changing the original mapping.

## Requirement 4: Durable asynchronous lifecycle

**User story:** As an operator, I want observable idempotent stages so that long OCR/model work survives duplicate delivery and worker failure.

### Acceptance criteria

4.1 WHEN an upload is verified, THE IDP SYSTEM SHALL send an IDs-only message to the dedicated IDP SQS queue and return without doing OCR/model work in the HTTP request.

4.2 WHEN processing executes, THE IDP SYSTEM SHALL persist only legal transitions among `created`, `uploading`, `uploaded`, `scanning`, `text_extraction`, `classifying`, `extracting`, `validating`, `review_required`, `completed`, `failed`, and `cancelled`.

4.3 WHEN SQS redelivers a message or a worker retries, THE IDP SYSTEM SHALL use unique constraints and stage checkpoints so one logical run/result is not duplicated.

4.4 WHEN work exceeds the current visibility window, THE IDP WORKER SHALL extend visibility; WHEN processing stops, it SHALL stop extending and delete only a successfully handled message.

4.5 IF three receives fail, THE IDP QUEUE SHALL move the IDs-only message to the dedicated DLQ; replay SHALL require an authorized audited operation.

## Requirement 5: Versioned configurable document types

**User story:** As a document-domain administrator, I want document behavior in validated configuration so that future types do not require orchestration code changes.

### Acceptance criteria

5.1 WHEN a definition is validated, THE IDP SYSTEM SHALL validate document type ID, semantic version, constraints, classification policy, extraction strategy, field paths/types/descriptions/units, requiredness, normalizers, validators, citation policy, prompt reference, UI hints, and additional-fact policy.

5.2 IF paths are duplicated, regex/normalizers are invalid, output is unbounded, a prompt is unversioned, or the definition is incompatible, THE IDP SYSTEM SHALL reject activation.

5.3 WHEN a definition moves through `draft`, `validated`, `evaluated`, `approved`, `active`, or `retired`, THE IDP SYSTEM SHALL record actor, timestamp, checksum, evaluation artifact, and prior state.

5.4 WHEN a run starts, THE IDP SYSTEM SHALL pin the active definition version and checksum; later configuration changes SHALL not change historical results.

5.5 WHEN a future document type is added, THE IDP SYSTEM SHALL require only configuration, a versioned prompt/structured schema, deterministic validators, a golden set, approval, and consumer display mapping, with no core pipeline/provider/storage code edit.

## Requirement 6: Classification

**User story:** As a consumer, I want IDP to choose the correct configured contract while exposing uncertainty.

### Acceptance criteria

6.1 WHEN no document type is requested, THE IDP SYSTEM SHALL classify only among enabled types for that consumer and record candidate scores, selected type/version, classifier/version, and confidence.

6.2 IF the top confidence is below the definition threshold or candidates are too close, THE IDP SYSTEM SHALL return `type_selection_required` and SHALL not extract against an arbitrary type.

6.3 WHEN an authorized consumer supplies a type, THE IDP SYSTEM SHALL validate that the type is enabled and compatible with the file; it SHALL record that the type was consumer-selected.

6.4 IF no type is supported, THE IDP SYSTEM SHALL return `unsupported_document_type` without a fabricated generic result.

## Requirement 7: Native text and OCR with available services

**User story:** As a consumer, I want scanned and native documents processed with explicit provenance.

### Acceptance criteria

7.1 WHEN a PDF page has usable native text, THE IDP SYSTEM SHALL prefer PyMuPDF text/blocks and SHALL not OCR that page unnecessarily.

7.2 WHEN a PDF page or image lacks usable text in Launchpad dev, THE IDP WORKER SHALL use the configured container RapidOCR adapter and record adapter/model version, confidence, dimensions, and timing.

7.3 IF a page exceeds pixel/time/memory limits or OCR is unavailable, THE IDP SYSTEM SHALL return a safe explicit failure/uncertainty and SHALL not invent text.

7.4 WHEN production OCR changes to a managed provider, THE IDP SYSTEM SHALL require a separately approved adapter, IAM permissions, region, data-flow review, and regression evaluation; no implicit fallback is allowed.

## Requirement 8: LLM-driven primary fields and complete grounded facts

**User story:** As a consumer, I want a document-specific response containing the configured important fields and other explicit details from the document.

### Acceptance criteria

8.1 WHEN an approved model is configured, THE IDP SYSTEM SHALL ask it for strict structured output containing only configured primary field candidates and bounded additional facts.

8.2 WHEN processing a medical report, THE IDP SYSTEM SHALL primarily extract the configured medical contract, including report identifiers/dates, body measurements, vitals, lifestyle/history, medication, cardiac tests, glucose/HbA1c, lipid, liver, kidney, and screening fields when explicitly present.

8.3 WHEN explicit relevant information is present but has no primary path, THE IDP SYSTEM SHALL return it as an additional fact with run-local ID, name, allowed category, source literal, typed value, confidence, and citations.

8.4 WHEN the same information appears as a primary field, THE IDP SYSTEM SHALL deduplicate or link the additional fact and SHALL not return contradictory duplicates silently.

8.5 WHEN content is missing or ambiguous, THE IDP SYSTEM SHALL return `not_found`, `uncertain`, or `conflict`; it SHALL not use an LLM assumption as a fact.

8.6 WHEN model output includes an unknown field/category, too many facts, unsupported type, hidden reasoning, instruction/tool request, or invalid citation, THE IDP SYSTEM SHALL reject that item or fail the run according to policy without publishing unsupported data.

## Requirement 9: Grounding and normalization

**User story:** As a downstream reviewer, I want every value traceable to the exact source.

### Acceptance criteria

9.1 WHEN a non-null field or fact is published, THE IDP SYSTEM SHALL include at least one citation to the same immutable document version, valid one-based page, exact retained excerpt, and bounding box when available.

9.2 IF the excerpt is not contained in retained page text or the page/version is invalid, THE IDP SYSTEM SHALL reject the item before result publication.

9.3 WHEN normalizing a value, THE IDP SYSTEM SHALL preserve the exact source literal separately and SHALL not silently convert units.

9.4 WHEN multiple explicit values apply to one singular field, THE IDP SYSTEM SHALL preserve candidates and emit a conflict rather than silently selecting one.

9.5 WHEN a result is published, THE IDP SYSTEM SHALL atomically store its run, fields, facts, issues, citations, and version metadata before exposing a terminal status.

## Requirement 10: Provider policy for Launchpad dev

**User story:** As a privacy/platform owner, I want model calls limited to the one available approved endpoint.

### Acceptance criteria

10.1 WHEN Launchpad dev starts, THE IDP SYSTEM SHALL allow only the configured Azure OpenAI/OpenAI-compatible provider and deterministic test provider; Bedrock/Claude and Textract SHALL be disabled because supplied runtime permissions do not include them.

10.2 IF `externalProviderApproved` is false, endpoint/deployment/API version/region is absent or unapproved, or the HTTPS endpoint is not allowlisted, THE IDP SYSTEM SHALL block model calls before document content leaves the worker.

10.3 WHEN the provider is used, THE IDP WORKER SHALL obtain the key from the existing named Secrets Manager secret; the IDP API SHALL not receive model-key permission.

10.4 WHEN a provider fails, THE IDP SYSTEM SHALL not automatically switch endpoint/model/provider; it SHALL record a safe retryable or terminal code.

10.5 WHEN document content is sent, THE IDP SYSTEM SHALL delimit it as untrusted, provide no tools, request no chain-of-thought, pin model/deployment/prompt/output schema, and record tokens/latency/cost.

## Requirement 11: Complete generic result contract

**User story:** As a consuming application, I want one stable response that I can render without knowing IDP internals.

### Acceptance criteria

11.1 WHEN a result is available, THE IDP SYSTEM SHALL return extraction/external reference/status, immutable document metadata, classification, document contract/version/checksum, nested primary data, authoritative flat fields, additional facts, issues, and run/OCR/provider metadata.

11.2 WHEN a field is absent, THE IDP SYSTEM SHALL represent absence in field status and SHALL not omit contract meaning ambiguously.

11.3 WHEN the result schema changes incompatibly, THE IDP SYSTEM SHALL use a new API or document-contract major version and preserve old run reproducibility.

11.4 WHEN a consumer asks for source access, THE IDP SYSTEM SHALL issue a short-lived method/object/version-specific URL after authorization and SHALL audit issuance without logging its query string.

11.5 WHEN the MMIL page maps a medical response, THE UI SHALL use configured field paths/status/citations and SHALL display primary fields and applicable additional facts without deriving medical or underwriting conclusions.

## Requirement 12: Launchpad resource alignment

**User story:** As the Launchpad platform owner, I want IDP to reuse shared infrastructure without inheriting broad business-service permissions.

### Acceptance criteria

12.1 WHEN the IDP dev stack is synthesized, THE STACK SHALL reuse the existing VPC/private-egress/data connectivity, KMS key, files bucket, RDS instance, BFF/session ingress, CloudFront/WAF, and CDK bootstrap.

12.2 WHEN the stack is synthesized, THE STACK SHALL create dedicated IDP API/worker service ownership, SQS queue/DLQ, DB schema/role/secret, service-auth secret, task roles, log groups, and alarms.

12.3 THE IDP STACK SHALL NOT create a second VPC/NAT/RDS/CloudFront/Cognito/public ALB or use an unrelated existing SQS queue.

12.4 WHEN IAM is synthesized, THE IDP API SHALL have only IDP-prefix S3/KMS, IDP queue-send, DB/service-auth access; THE IDP WORKER SHALL have only IDP-prefix S3/KMS, IDP queue-consume, DB, and approved model-secret access.

12.5 WHEN images build, CDK SHALL use `ContainerImage.fromAsset` and bootstrap roles; deployment SHALL not require direct ECR login.

## Requirement 13: Audit, privacy, and operations

**User story:** As an auditor/operator, I want traceable processing without health data in operational telemetry.

### Acceptance criteria

13.1 WHEN upload, source URL issuance, status/result access, processing stage, retry/DLQ replay, provider/config version, or config activation occurs, THE IDP SYSTEM SHALL append an audit event with opaque IDs and no document text/values.

13.2 WHEN the runtime role accesses `idp.audit_events`, THE DATABASE SHALL allow INSERT/SELECT only and SHALL block UPDATE/DELETE with grants and a trigger.

13.3 WHEN logs/metrics/traces/tags/queue messages are emitted, THE IDP SYSTEM SHALL exclude original filenames, MMIL case/applicant data, page text, extracted values, model payloads, pre-signed URLs, and secrets.

13.4 WHEN queue age, DLQ depth, extraction failure, OCR/model latency/throttling, or estimated cost crosses configured thresholds, THE PLATFORM SHALL alarm through existing CloudWatch operations.

13.5 WHEN worker resources are configured in dev, THE PLATFORM SHALL start at one-document concurrency, 1 vCPU, and 2 GB and SHALL change only after representative OCR/load measurement.

## Requirement 14: Shared package and extensibility proof

**User story:** As an engineer, I want API, worker, and CLI behavior to remain consistent and demonstrate configuration-only extension.

### Acceptance criteria

14.1 WHEN extraction runs through API worker or CLI, THE IDP SYSTEM SHALL call the same registry, text/OCR, provider, normalization, validation, and grounding services.

14.2 WHEN deterministic local extraction is used, THE IDP SYSTEM SHALL label it `deterministic-local` and SHALL not call it an AI result.

14.3 WHEN the first non-medical type is added, automated tests SHALL show that no core orchestration/provider/storage module changed.

14.4 WHEN CI runs, it SHALL validate OpenAPI compatibility, registry definitions, property/unit/integration tests, synthetic golden extraction, frontend mapping, IaC assertions, and dependency/container scans.
