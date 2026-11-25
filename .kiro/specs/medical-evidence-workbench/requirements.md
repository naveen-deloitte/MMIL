# MMIL Medical Evidence Consumer Requirements

## Scope

This specification covers only the static MMIL page that displays the reusable IDP engine response. The authoritative engine requirements are in `../configurable-idp-engine/requirements.md`.

The MMIL page does not extract, OCR, classify, prompt a model, normalize, validate citations, or store IDP results. It does not make or submit underwriting decisions. In this scope it is a **read-only evidence viewer**; human review persistence requires a separate MMIL-owned specification.

## Requirement 1: Focused static page

**User story:** As an MMIL reviewer, I want one focused medical-evidence page so that I can inspect the IDP response without unrelated prototype workflows.

### Acceptance criteria

1.1 WHEN an authorized user opens the page, THE MMIL UI SHALL display the mock-derived brand header, MMIL case context supplied by the BFF, processing progress, medical sub-tabs, and source-view controls.

1.2 WHEN the page renders, THE MMIL UI SHALL provide Summary, Vitals & BMI, Lab Results, Configured Checks, AI Extraction Summary, and Additional Facts views or sections based only on the IDP response.

1.3 THE MMIL UI SHALL omit the prototype dashboard, queue, financial/occupation/compliance/reinsurance, simulator, decision, Ask AI, claims, servicing, and policy-issuance controls.

1.4 IF a capability has no backed MMIL/BFF or IDP behavior, THE MMIL UI SHALL not display it as operational.

## Requirement 2: Existing Launchpad authorization boundary

**User story:** As a security owner, I want the page to use the deployed Launchpad session and BFF so that a static client never holds confidential credentials or asserts tenant access.

### Acceptance criteria

2.1 WHEN the browser requests IDP work, THE MMIL UI SHALL call same-origin `/api/v1/idp/*` BFF routes using the existing secure session.

2.2 THE MMIL UI SHALL NOT receive the Cognito app client secret, IDP service-auth secret, database credentials, model key, or AWS credentials.

2.3 IF the BFF denies the case/resource, THE MMIL UI SHALL display a non-enumerating access/not-found state and SHALL not attempt direct IDP or S3 discovery.

2.4 THE MMIL UI SHALL treat tenant, role, and external-reference values in browser state as display/context only; server authorization remains authoritative.

## Requirement 3: Extraction creation and status display

**User story:** As an MMIL reviewer, I want to submit a document and follow IDP status while extraction runs independently.

### Acceptance criteria

3.1 WHEN the user adds a document, THE MMIL UI SHALL request an IDP extraction/upload session through the BFF and upload only to the returned short-lived scoped URL.

3.2 WHEN upload finishes, THE MMIL UI SHALL notify the BFF/IDP completion endpoint and SHALL not run client-side extraction.

3.3 WHILE IDP status is nonterminal, THE MMIL UI SHALL poll the status contract with bounded frequency and announce meaningful stage changes.

3.4 IF IDP returns a safe failure code, THE MMIL UI SHALL display a safe mapped message and an authorized retry action only when the response permits retry.

3.5 WHEN the user changes tabs or opens source, THE MMIL UI SHALL preserve extraction ID, selected document/page, and active medical view.

## Requirement 4: Medical result mapping

**User story:** As an MMIL reviewer, I want every configured medical result shown in a familiar layout without the UI inventing values or interpretation.

### Acceptance criteria

4.1 WHEN a medical result arrives, THE MMIL UI SHALL map fields by IDP path/UI hint into Summary, Vitals & BMI, Lab Results, Configured Checks, and AI Extraction Summary.

4.2 WHEN a field is displayed, THE MMIL UI SHALL show its effective IDP value/source literal, unit, found/not-found/uncertain/conflict status, confidence, validation issues, and citations as supplied.

4.3 WHEN IDP returns `not_found`, `uncertain`, or `conflict`, THE MMIL UI SHALL preserve that state and SHALL not substitute mock/default/case values.

4.4 THE MMIL UI SHALL NOT compute BMI categories, lab interpretations, knockout decisions, loading, eligibility, diagnosis, or coverage recommendations from extracted values.

4.5 WHEN IDP returns contract/run metadata, THE MMIL UI SHALL display document type/schema/checksum and OCR/provider/deployment/prompt versions in the extraction summary.

## Requirement 5: Additional facts

**User story:** As an MMIL reviewer, I want explicit document details outside the primary medical schema visible so that the full IDP extraction can be inspected.

### Acceptance criteria

5.1 WHEN IDP returns additional facts, THE MMIL UI SHALL group them by the IDP-supplied allowed category and display name, value/literal, confidence, status, and citation.

5.2 THE MMIL UI SHALL visually distinguish additional facts from stable primary fields and SHALL state that their run-local IDs/labels are not a stable integration contract.

5.3 WHEN an additional fact links to a primary field, THE MMIL UI SHALL avoid presenting it as an unrelated duplicate.

5.4 THE MMIL UI SHALL not promote an additional fact into an MMIL primary field without a separately versioned IDP contract and consumer mapping change.

## Requirement 6: Side-by-side immutable source viewer

**User story:** As an MMIL reviewer, I want the actual uploaded document beside the extracted details so that I can verify IDP output efficiently.

### Acceptance criteria

6.1 WHEN the user selects **View source**, THE MMIL UI SHALL request an authorized short-lived source grant through the BFF and open a persistent source pane beside evidence on wide screens.

6.2 WHEN the user activates a field or fact citation, THE MMIL UI SHALL select the exact immutable document version, navigate to its one-based page where supported, and display the exact IDP citation excerpt.

6.3 THE MMIL UI SHALL never construct an S3 key/URL, reuse an expired grant silently, place the source URL in logs/analytics, or expose it outside the viewer.

6.4 IF preview is unsupported, THE MMIL UI SHALL offer the authorized short-lived download and a safe message without rendering active content.

6.5 WHEN the viewport is narrow, THE MMIL UI SHALL provide an explicit Evidence/Source switch with the same content and no horizontal overflow.

6.6 WHEN source is closed and reopened before grant expiry, THE MMIL UI SHALL preserve selected document/page; after expiry it SHALL request a new authorized grant.

## Requirement 7: Read-only consumer behavior

**User story:** As a platform owner, I want the static page to remain a presentation adapter so that the reusable engine and MMIL business workflows do not become coupled.

### Acceptance criteria

7.1 THE MMIL UI SHALL NOT persist candidate corrections, acceptance/rejection, model prompts, schemas, page text, or extraction results in browser storage.

7.2 THE MMIL UI SHALL NOT expose edit/accept/reject/not-applicable controls in this read-only scope.

7.3 IF MMIL later requires human review, THE SYSTEM SHALL implement it through a separate MMIL/BFF-owned versioned contract and SHALL preserve the immutable IDP result as its source.

7.4 WHEN the BFF returns an IDP result, THE MMIL UI SHALL not change field meaning, unit, status, confidence, or citation; presentation formatting may not alter the underlying response.

## Requirement 8: Accessibility, privacy, and responsive behavior

**User story:** As a keyboard, screen-reader, or mobile user, I want the full evidence/source workflow to remain usable without leaking sensitive data.

### Acceptance criteria

8.1 WHEN using only a keyboard, THE MMIL UI SHALL support upload, status, sub-view navigation, facts, source open/close, document selection, page controls, citation activation, and authorized download in logical focus order.

8.2 WHEN processing/status/source-grant state changes, THE MMIL UI SHALL announce concise messages through an appropriate live region.

8.3 WHEN controls and results render, THE MMIL UI SHALL provide programmatic names, visible focus, semantic headings/tables, and state text not dependent on color.

8.4 THE MMIL UI SHALL NOT send case/document/extracted values, source excerpts, source URLs, or filenames to third-party analytics, fonts, scripts, or error reporting.

8.5 WHEN reduced motion is requested, THE MMIL UI SHALL avoid nonessential animation.

## Requirement 9: Consumer contract verification

**User story:** As an integration owner, I want fixture-based contract tests so that IDP and MMIL can evolve independently.

### Acceptance criteria

9.1 WHEN a medical `1.x` result fixture is rendered, THE MMIL UI SHALL display all primary fields according to status and all non-duplicate additional facts.

9.2 WHEN fixture citations are activated, THE MMIL UI SHALL request/select the matching document/version/page/excerpt without changing the result.

9.3 WHEN unknown additive fields/fact categories arrive, THE MMIL UI SHALL preserve compatibility and show a safe generic section or ignore them according to documented policy without failing the page.

9.4 WHEN an incompatible document/API major version arrives, THE MMIL UI SHALL show an explicit unsupported-contract state rather than mis-map data.

9.5 WHEN frontend tests/build/accessibility checks pass, THE MMIL bundle SHALL remain deployable as static assets to the existing Launchpad web bucket.