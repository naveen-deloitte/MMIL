# MMIL Medical Evidence Consumer Tasks

> This spec now covers only the static read-only consumer. Reusable extraction work belongs to `../configurable-idp-engine/tasks.md`.

- [ ] 1. Replace prototype contracts with the generic IDP consumer contract
  - [ ] 1.1 Generate frontend types/client bindings from the `/api/v1/idp` OpenAPI artifact for create, complete, status, result, retry, and source-grant routes.
    - Validate API/document-contract major versions.
    - _Requirements: 2.1, 3.1–3.4, 9.3, 9.4_
  - [ ] 1.2 Separate BFF-provided MMIL case display context from IDP extraction/result state and remove trusted browser tenant/role headers.
    - _Requirements: 2.1–2.4, 7.4_
  - [ ] 1.3 Remove direct case extraction/review API assumptions from the frontend module.
    - _Requirements: 1.4, 7.1–7.4_

- [ ] 2. Implement static IDP workflow states
  - [ ] 2.1 Create an extraction/upload session through the BFF, PUT to only the returned scoped URL, and complete through the BFF.
    - _Requirements: 3.1, 3.2_
  - [ ] 2.2 Poll bounded IDP status and map all stages, classification-selection, safe failures, and server-authorized retry.
    - Stop polling on unmount/terminal state.
    - _Requirements: 3.3, 3.4, 3.5_
  - [ ] 2.3 Add access-denied, unsupported-contract, upload validation, source-grant expiry, and preview fallback states.
    - _Requirements: 2.3, 6.3, 6.4, 6.6, 9.4_

- [ ] 3. Render medical primary fields without extraction logic
  - [ ] 3.1 Keep the mock-derived static header, case display context, progress strip, and focused medical tabs; omit every unrelated prototype control.
    - _Requirements: 1.1–1.4_
  - [ ] 3.2 Map IDP primary fields/UI hints into Summary, Vitals & BMI, Lab Results, Configured Checks, and AI Extraction Summary.
    - Preserve value/literal/unit/status/confidence/validation/citation exactly.
    - _Requirements: 4.1–4.5, 7.4_
  - [ ] 3.3 Remove BMI/lab/knockout/loading/diagnostic/underwriting calculations and all mock/default substitution.
    - _Requirements: 4.3, 4.4_
  - [ ] 3.4 Remove edit/accept/correct/reject/not-applicable controls and browser review persistence from this read-only scope.
    - _Requirements: 7.1, 7.2, 7.3_

- [ ] 4. Render complete additional facts
  - [ ] 4.1 Add an Additional Facts section grouped by IDP category with name, literal/value, state, confidence, and citation.
    - _Requirements: 5.1, 5.2_
  - [ ] 4.2 Deduplicate facts linked to primary fields and add safe generic handling for unknown additive fields/categories.
    - _Requirements: 5.3, 5.4, 9.3_

- [ ] 5. Convert source viewing to IDP source grants
  - [ ] 5.1 Request and retain source grants in component memory only; refresh after expiry and clear on case/extraction/logout changes.
    - _Requirements: 6.1, 6.3, 6.6, 7.1_
  - [ ] 5.2 Connect each field/fact citation to exact extraction/document/version/page/excerpt without changing result data or active medical context.
    - _Requirements: 3.5, 6.2_
  - [ ] 5.3 Preserve wide-screen split view and mobile Evidence/Source switch with PDF/JPEG/PNG preview and safe TIFF/unsupported download.
    - _Requirements: 6.1, 6.4, 6.5_

- [ ] 6. Enforce static-client privacy and accessibility
  - [ ] 6.1 Remove third-party font/script/analytics dependencies and verify no extracted data, filenames, excerpts, or grants enter URLs, logs, analytics, or browser storage.
    - _Requirements: 2.2, 6.3, 7.1, 8.4_
  - [ ] 6.2 Verify keyboard operation, semantic tabs/tables/status, live announcements, visible focus, focus return, mobile layout, and reduced motion.
    - _Requirements: 8.1, 8.2, 8.3, 8.5_

- [ ] 7. Verify and package the consumer
  - [ ] 7.1 Add fixture-based tests for exact pure mapping, absence preservation, facts distinction/deduplication, citations/grants, additive compatibility, and unsupported major versions.
    - _Requirements: 4.1–4.5, 5.1–5.4, 6.1–6.6, 9.1–9.4_
  - [ ] 7.2 Add state tests for upload/status/classification/failure/retry and assert no review/extraction logic controls exist.
    - _Requirements: 3.1–3.5, 7.1–7.4_
  - [ ] 7.3 Run frontend tests, TypeScript/static build, accessibility checks, dependency audit, and CSP review.
    - _Requirements: 8.1–8.5, 9.5_
  - [ ] 7.4 Supply static deployment instructions for the existing `launchpad-dev-web` bucket and synthetic BFF→IDP→UI smoke test.
    - _Requirements: 2.1, 9.5_
