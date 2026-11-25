# Launchpad-Aligned AWS Deployment Plan for the IDP Engine

## 1. Scope and current constraint

This plan targets the supplied Launchpad `dev` environment in the Mumbai region. It does not create a parallel VPC, public API, CloudFront distribution, Cognito user pool, database instance, KMS key, or general-purpose file bucket.

The deployed Launchpad CDK source referenced by the platform owner is **not present in this workspace**. Therefore this repository cannot safely mutate `Launchpad-dev-Network`, `Data`, `Auth`, `Workers`, `Api`, or `Web` by guessing generated physical IDs. The owning CDK repository must merge the integration changes below, or expose the listed stack outputs to an IDP extension stack.

No AWS deployment is executed by this work.

## 2. Target topology

```text
Browser
  |
  | HTTPS, existing session
  v
Existing CloudFront + CF WAF
  |
  | existing /api/* behavior
  v
Existing public ALB + regional WAF
  |
  v
Existing Launchpad API BFF
  |  validates session and MMIL authorization
  |  signs short-lived IDP service context
  v
Private IDP API ECS service
  |---- existing RDS PostgreSQL 17 / new idp schema + idp_dev role
  |---- existing launchpad-dev-files / idp/dev/... prefix
  |---- new launchpad-dev-idp SQS queue + DLQ
  v
Private IDP worker ECS service
  |---- PyMuPDF + container RapidOCR
  |---- approved Azure OpenAI endpoint through NAT
  |---- immutable result in RDS / derived artifact prefix

Static MMIL bundle remains in launchpad-dev-web and only displays IDP responses.
```

The private IDP API has no internet-facing listener. Browser calls stay on the existing origin and BFF. This avoids putting the existing confidential Cognito client secret in the SPA and keeps MMIL authorization outside the generic engine.

## 3. Stack changes

### 3.1 Reuse unchanged

| Existing stack/resource | IDP use |
|---|---|
| `CDKToolkit` in Mumbai and us-east-1 | Continue using the deployed bootstrap roles/assets. Keep the custom us-east-1 bootstrap version parameter. |
| `Launchpad-dev-Network` | Import VPC, private-egress subnets for ECS, isolated-data connectivity, NAT, endpoints, and flow logs. Do not create another NAT/VPC. |
| Data KMS key (`alias/launchpad-dev-data`) | Encrypt the IDP SQS queue/DLQ and existing files-bucket objects. |
| `launchpad-dev-files` | Store IDP originals/derived artifacts under generated `idp/dev/` keys. Existing CloudFront-origin CORS is sufficient for scoped browser PUT/GET URLs. |
| Existing PostgreSQL 17 instance | Create a separate `idp` schema and `idp_dev` login; do not put IDP tables in Launchpad application ownership. |
| Existing Cognito/session flow | Launchpad API BFF remains browser authentication and MMIL authorization boundary. |
| Existing ALB + regional WAF | Browser requests continue to the Launchpad API. No new listener or direct IDP target is required. |
| Existing CloudFront + CF WAF + web bucket | Host the MMIL static bundle and proxy `/api/*` as currently configured. |
| Existing OpenAI secret | IDP worker may read `launchpad/dev/openai-api-key` only after provider approval. |

### 3.2 New `Launchpad-dev-Idp` stack

The preferred ownership unit is a dedicated stack that accepts references from Network/Data/Api. If the current CDK application cannot expose references cross-stack, add equivalent constructs to the owning stacks while preserving the same resource ownership and policies.

| Resource | Configuration |
|---|---|
| ECS cluster | `launchpad-dev-idp`; Container Insights enabled. |
| API task definition/service | 0.5 vCPU, 1 GB; one dev task; private-egress subnets; no public IP; read-only root filesystem where compatible; non-root user; deployment circuit breaker and rollback. |
| Worker task definition/service | 1 vCPU, 2 GB; one dev task; private-egress; no ingress; one-document concurrency initially; circuit breaker/rollback. |
| Private service discovery | Service Connect or Cloud Map DNS name such as `api.idp.launchpad.local:8000`, resolvable by Launchpad API tasks only. |
| IDP API security group | Ingress 8000 only from the existing Launchpad API SG. Egress 5432 to RDS SG, 443 to AWS endpoints/NAT as required. |
| IDP worker security group | No ingress. Egress 5432 to RDS SG and 443 for S3/SQS/Secrets/KMS endpoints plus approved Azure endpoint through NAT. |
| Queue | `launchpad-dev-idp`, KMS encrypted, long polling, visibility timeout set from benchmark, IDs-only body. |
| DLQ | `launchpad-dev-idp-dlq`, KMS encrypted, 14-day retention, source redrive after three receives. |
| Runtime DB secret | Generated `IdpDbUserSecret`; username `idp_dev`, generated password. |
| Service-auth secret | Generated `IdpServiceAuthSecret`; used only to sign/verify short-lived BFF→IDP context. |
| Log groups | Separate `/launchpad/dev/idp/api` and `/launchpad/dev/idp/worker`, one-month dev retention, KMS if required by baseline. |
| Alarms/dashboard | Queue age/depth, DLQ count, API 5xx/latency, worker failure, OCR/model latency/throttling, extraction count, and estimated token cost. |

Do **not** put IDP messages on the existing `prototype`, `jira`, `index`, `archive_manifest`, `pdf_export`, `github_events`, `pr_review`, or `scheduled` queues. Their consumers, visibility settings, schemas, and operational ownership are unrelated.

### 3.3 Existing `Launchpad-dev-Api` changes

- Add a small `/api/v1/idp/*` BFF adapter. It validates the existing session and MMIL case access, then forwards the generic request to private IDP.
- Forward an opaque `external_reference`; do not send applicant/product details unless a configured extraction field requires document content that already contains them.
- Sign context with `IdpServiceAuthSecret`; include issuer/consumer, tenant, subject, roles, permitted external reference, issued/expiry time, request ID, and nonce.
- Add the service-auth secret to the API container through ECS secret injection. Do not expose it to the static bundle or logs.
- Permit API SG egress to IDP API SG on port 8000.
- Keep existing Transcribe permissions isolated to Launchpad. IDP roles receive no Transcribe permission.
- Proxy IDP problem details/status/result without duplicating extraction rules.

The BFF should return IDP-created pre-signed URLs to the browser rather than proxying large file bodies through 0.5-vCPU API tasks.

### 3.4 Existing `Launchpad-dev-Data` changes

- Export/import the files bucket, data key, RDS endpoint/port, RDS SG, and RDS master-secret ARN to the IDP stack using direct CDK references where possible.
- Create `IdpDbUserSecret` and pass it to the migration/API/worker task definitions.
- The IDP migration container connects with the master secret, creates/updates the `idp` schema and `idp_dev` role, grants runtime privileges, and exits.
- `idp_dev` receives CRUD only on IDP runtime tables and INSERT/SELECT only on `idp.audit_events`.
- Add an update/delete trigger to `idp.audit_events`, matching the existing Launchpad audit integrity pattern.
- Keep RDS private, single-AZ, 7-day backup in dev. Validate connection capacity on `db.t3.micro`; use small SQLAlchemy pools.

### 3.5 Existing `Launchpad-dev-Web` changes

No CloudFront behavior change is required because `/api/*` already reaches the Launchpad API. Build the MMIL static consumer and sync versioned assets to `launchpad-dev-web` using the deploying user's working S3 permission.

Verify the existing CSP continues to permit:

- same-origin scripts/styles/API calls;
- `frame-src` or `object-src` needed by the chosen source viewer;
- the `launchpad-dev-files` S3 endpoint for short-lived source/upload URLs;
- no broad arbitrary external origins.

The current CloudFront/WAF/TLS/SPA rewrite remains unchanged.

## 4. IAM design

### IDP API task role

| Service | Actions | Scope |
|---|---|---|
| S3 | `PutObject`, `GetObject`, `GetObjectVersion`, `HeadObject` equivalent; tightly limited list only if implementation requires it | `launchpad-dev-files/idp/dev/*` |
| SQS | `SendMessage`, `GetQueueAttributes`, `GetQueueUrl` | IDP queue only |
| KMS | Encrypt/decrypt/data-key operations required by S3/SQS SDK paths | Existing data key only, with service/resource conditions where feasible |
| Secrets Manager | `GetSecretValue` through ECS injection/runtime only | IDP DB and service-auth secrets |

No model key, Transcribe, recordings/design buckets, existing business queues, or broad `s3:DeleteObject`.

### IDP worker task role

| Service | Actions | Scope |
|---|---|---|
| SQS | Receive/delete/change visibility/get attributes; send only if replay/outbox requires | IDP queue and controlled DLQ path only |
| S3 | Read source versions; write derived artifacts/results; list only IDP prefix | `launchpad-dev-files/idp/dev/*` |
| KMS | Required cryptographic operations | Existing data key only |
| Secrets Manager | Read IDP DB secret and approved Azure OpenAI key | Two named secrets only |

Delete permission is excluded from normal processing. A future retention/deletion task gets a separate role and approval path.

### Execution roles

Execution roles pull CDK assets from the bootstrap ECR repository, write only their log groups, and inject only the secrets listed for each container. Images are built with `ecs.ContainerImage.fromAsset` because direct ECR login is denied for the deploying user.

### Migration container

Only the migration container receives the RDS master secret. Use ECS container dependency `SUCCESS` before API start. API and worker receive only `idp_dev` credentials.

## 5. S3 object and URL design

Generated key format:

```text
idp/dev/tenants/<tenant-hash>/documents/<document-uuid>/versions/<n>/original.<ext>
idp/dev/tenants/<tenant-hash>/documents/<document-uuid>/runs/<run-uuid>/pages.json.gz
idp/dev/tenants/<tenant-hash>/documents/<document-uuid>/runs/<run-uuid>/result.json
```

No tenant name, MMIL case ID, applicant name, or original filename appears in a key. Original filename remains encrypted metadata in PostgreSQL if needed for display.

Upload URL:

- PUT only, one key/version, 5–10 minute expiry.
- Require expected content type, checksum header, and size policy where the S3 signing flow supports it.
- Completion checks S3 version, content length, checksum/hash, and signature before queueing.

Source URL:

- GET only, exact immutable object version, 5 minute expiry.
- Issued only after BFF and IDP tenant/external-reference authorization.
- Content disposition uses sanitized display filename; active formats are never rendered.
- URL issuance is audited; query strings are not logged.

Bucket versioning, SSE-KMS, TLS-only, public-access block, and retain-on-stack-delete already meet the dev baseline. Retention/lifecycle remains an open product decision.

## 6. SQS and worker behavior

Message body contains no document text or business identifiers:

```json
{
  "message_version": 1,
  "job_id": "uuid",
  "extraction_id": "uuid",
  "document_id": "uuid",
  "correlation_id": "uuid"
}
```

- Standard queue delivery is at least once; DB uniqueness and stage checkpoints make consumers idempotent.
- Worker extends visibility while active and stops extension on completion/failure.
- Transient provider/OCR/database errors retry with bounded backoff; permanent signature/schema/citation errors fail without repeated model calls.
- After three receives, SQS moves the message to DLQ. Replay requires an audited operator action and bounded rate.
- Queue does not contain pre-signed URLs, tenant names, case IDs, filenames, text, or extracted values.

## 7. OCR and model configuration

### Dev OCR

The supplied IAM roles have no Textract actions. Use PyMuPDF native extraction, then RapidOCR ONNX in the worker for image-only pages.

- Start worker at 1 vCPU / 2 GB and concurrency one.
- Enforce 50 MB/200-page defaults, per-page pixel caps, rendering timeouts, and temporary-storage bounds.
- Record PyMuPDF/RapidOCR versions and page confidence.
- If benchmarks fail, request Textract as a separate architecture/IAM/privacy change. Do not add undeclared permissions to the current role.

### Dev LLM

Use an OpenAI-compatible/Azure OpenAI adapter only when all of these settings exist:

- approved HTTPS endpoint;
- API version;
- pinned deployment/snapshot;
- provider region on the approved-region list;
- `externalProviderApproved=true`;
- key injected from `launchpad/dev/openai-api-key` into worker only.

No Bedrock/Claude path is active because the supplied runtime roles and service inventory do not include Bedrock. Keep the provider interface replaceable, but fail closed for unconfigured providers and disable automatic fallback.

The worker's broad 443 NAT egress cannot enforce a domain by security group. Validate the endpoint against an application allowlist, do not follow cross-origin redirects, and alarm on unexpected destination/network behavior. A future egress proxy/firewall would improve this control.

## 8. Database and migrations

Core IDP tables live under PostgreSQL schema `idp`:

- `consumers`
- `extraction_requests`
- `documents`
- `upload_idempotency`
- `processing_jobs`
- `document_type_definitions`
- `extraction_runs`
- `document_pages`
- `extracted_fields`
- `additional_facts`
- `outbox_events`
- `audit_events`

Use Alembic expand/contract migrations. The migration container:

1. Takes an advisory migration lock.
2. Creates/updates role/schema/grants idempotently.
3. Runs migrations.
4. Verifies audit triggers and required extensions.
5. Seeds only configuration/consumer bootstrap data, never real documents.
6. Exits; API starts only on success.

Use conservative dev connection pools because the shared RDS instance is `db.t3.micro`: API pool two plus overflow one per task, worker pool one plus overflow one, migration one-off. Revisit after observing BFF and existing Launchpad use.

## 9. Container build and release

1. Build API and worker from one source image; use different commands/task roles. OCR models may use a dedicated worker stage/image if image size becomes excessive.
2. CDK uses `ContainerImage.fromAsset`. Keep `.dockerignore` strict so samples, `.venv`, local objects, test output, and the 1.1 MB reference HTML are not sent to Docker unnecessarily.
3. Run backend unit/property/contract tests, synthetic golden extraction, secret/dependency/container scan, and SBOM generation before synth.
4. Build the static MMIL consumer separately and run frontend tests/accessibility checks.
5. `cdk synth` and `cdk diff` through bootstrap roles. Review IAM, SG, queue, KMS, secret, and RDS changes.
6. Deploy IDP foundation and BFF adapter to dev. Upload only synthetic documents.
7. Run S3 → SQS → worker → result → BFF → static UI smoke flow.
8. Verify DLQ, queue age, failure/model/OCR latency, cost, and no-PHI-log checks.

The deploying user cannot directly log in to ECR or inspect several live resources, so stack outputs must expose safe operational identifiers such as cluster/service names, queue URL, log group names, and private discovery name. Do not output secret values, RDS passwords, object keys, or pre-signed URLs.

## 10. CDK stack contract

The owning Launchpad CDK application should pass constructs directly. If a separate repository must deploy the IDP extension, export/provide these values:

- VPC ID
- private-egress subnet IDs
- existing Launchpad API security-group ID
- RDS security-group ID, endpoint, port, and master-secret ARN
- files-bucket name/ARN
- data KMS key ARN
- OpenAI secret ARN/name
- existing API task/execution role IDs only if the BFF secret/network grants are applied cross-stack
- Cloud Map/private namespace ID if one exists
- stage, account, region

Avoid `Vpc.fromLookup` when the deploying identity/context cannot perform all EC2 describe calls. Prefer CloudFormation exports, SSM only where the deploy role can read it, or explicit reviewed context values. The user currently cannot call SSM directly, so CDK-managed cross-region references do not imply shell access.

## 11. Deployment command constraints

CloudShell requirements supplied by the platform owner remain:

- CDK CLI on Node 26.
- Install `libatomic` each CloudShell session.
- Use existing bootstrap roles in both regions.
- Use ASCII-only security-group descriptions.
- Prune Docker/build assets before large builds due storage limits.
- Do not attempt Aurora, ACM certificate import, or direct ECR login.

The repository deployment wrapper must default to synth/diff. Actual `dev` deployment requires an explicit execute flag and reviewed stack inputs. Production remains unsupported until a TLS origin path, multi-AZ/recovery targets, provider approval, scanner, retention, and full readiness review exist.

## 12. Acceptance gate

Dev integration is complete only when:

- The owning Launchpad CDK diff shows no second VPC/NAT/RDS/CloudFront/Cognito/public ALB.
- IDP has dedicated API/worker services, queue/DLQ, roles, DB role/schema, secrets, log groups, and alarms.
- Launchpad API can reach private IDP; no browser or internet path reaches IDP directly.
- API cannot read the model key. Worker cannot access unrelated queues/buckets/Transcribe.
- S3 keys and SQS bodies contain no MMIL/applicant/file names or raw values.
- Synthetic native PDF and scanned image flows return document-specific configured fields plus grounded additional facts.
- Citation source URLs are scoped, short-lived, and render side by side in the static UI.
- Cross-tenant, forged-context, duplicate-delivery, stale upload, DLQ/replay, provider timeout, and OCR resource tests pass.
- Runtime dependency/container scans have no unaccepted high/critical findings.
- No production or real-PHI claim is made from the dev architecture.
