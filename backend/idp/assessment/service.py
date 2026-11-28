"""Case-level underwriting assessment.

Combines results the platform already produces (document extraction, the per-document AI
analysis, evidence reviews, HILT exceptions and identity matching) with configurable underwriting
rules. It makes no new AI or provider calls.

Separation of values:
* ``proposed_terms`` comes only from the product selected when the case was created. It is copied,
  never recalculated or overwritten.
* ``risk_score``, ``recommendation``, ``recommended_terms`` and ``revised_premium`` are assessment
  outputs. Each is "not available" unless an approved, configured source produced it.
* Final underwriter-approved terms live in the existing underwriting decision records and are
  never written by the assessment.

The recommendation only ever routes work ("refer", "review"). It never approves or declines.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from idp.assessment.rules import Rule, RuleSet, compare, load_rule_set, score_band
from idp.audit import append_audit
from idp.config import Settings
from idp.models import Case, CaseAssessment, UnderwritingDecision
from idp.schemas import FieldOut, WorkspaceOut

logger = logging.getLogger(__name__)

ENGINE_VERSION = "case-assessment-1.0.0"
DISCLAIMER = (
    "Decision support only. The assessment routes work to the underwriter; it never approves or "
    "declines an application. The underwriter records the final decision."
)
EXPECTED_EVIDENCE = (
    ("kyc_individual", "Individual KYC form"),
    ("medical_report", "Medical report"),
    ("financial_document", "Financial document"),
)
IDENTITY_TYPES = ("aadhaar_card", "pan_card")
# Sensitive bank identifiers are not repeated in the assessment.
EXCLUDED_FINANCIAL_PATHS = {"bank_details.account_number", "bank_details.bvn"}
NOT_AVAILABLE = "not_available"


def _usable(field: FieldOut) -> bool:
    return field.effective_value is not None and field.review_state not in {
        "rejected",
        "not_applicable",
    }


def _citations(items: list[Any]) -> list[dict[str, Any]]:
    out = []
    for item in items:
        data = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        out.append(
            {
                "document_id": data["document_id"],
                "document_version": data["document_version"],
                "page": data["page"],
                "excerpt": data["excerpt"],
            }
        )
    return out


class _Context:
    def __init__(self, workspace: WorkspaceOut, identity: Any | None):
        self.workspace = workspace
        self.identity = identity
        self.documents = {doc.id: doc for doc in workspace.documents}
        self.policy = workspace.case.policy_details or None
        self.fields = [f for f in workspace.fields if _usable(f)]
        self.analyses = [
            (run.document_id, run.ai_analysis) for run in workspace.runs if run.ai_analysis is not None
        ]

    def evidence(self, field: FieldOut, *, value: Any | None = None) -> dict[str, Any]:
        document = self.documents.get(field.document_id)
        return {
            "label": field.label,
            "field_path": field.field_path,
            "value": field.effective_value if value is None else value,
            "unit": field.unit,
            "review_state": field.review_state,
            "document_id": field.document_id,
            "document_type": document.document_type if document else None,
            "filename": document.filename if document else None,
            "citations": _citations(field.citations),
        }

    def fields_at(self, path: str, document_types: tuple[str, ...] | None = None) -> list[FieldOut]:
        return [
            field
            for field in self.fields
            if field.field_path == path
            and (
                document_types is None
                or (self.documents.get(field.document_id) is not None
                    and self.documents[field.document_id].document_type in document_types)
            )
        ]

    def first_number(self, path: str) -> tuple[float | None, FieldOut | None]:
        for field in self.fields_at(path):
            try:
                return float(field.effective_value), field
            except (TypeError, ValueError):
                continue
        return None, None


# ------------------------------------------------------------------- sections


def _proposed_terms(ctx: _Context) -> dict[str, Any]:
    case = ctx.workspace.case
    policy = ctx.policy
    if not policy:
        return {
            "status": NOT_AVAILABLE,
            "reason": "The case was created without a catalogue product, so proposed terms were not captured.",
            "product_name": case.product_name,
            "source": "case_record",
        }
    quote = policy.get("indicative_quote") or {}
    premium_known = quote.get("status") == "indicative" and quote.get("amount") is not None
    return {
        "status": "captured",
        "source": "case_product_selection",
        "product_id": policy.get("product_id"),
        "product_name": policy.get("product_name") or case.product_name,
        "insurer": policy.get("insurer"),
        "insurance_type": policy.get("insurance_type"),
        "plan_name": policy.get("plan_name"),
        "currency": policy.get("currency"),
        "sum_assured": policy.get("sum_assured"),
        "premium": quote.get("amount") if premium_known else None,
        "premium_status": "indicative" if premium_known else NOT_AVAILABLE,
        "premium_basis": "Indicative catalogue premium, not an official insurer quote."
        if premium_known
        else "; ".join(quote.get("reasons") or ["No premium was calculated at case creation."]),
        "premium_frequency": policy.get("premium_frequency"),
        "policy_term": policy.get("policy_term"),
        "premium_payment_term": policy.get("premium_payment_term"),
        "rating_inputs": policy.get("rating_inputs") or {},
        "catalogue": policy.get("catalogue"),
    }


def _applicant(ctx: _Context) -> list[dict[str, Any]]:
    types = ("kyc_individual", *IDENTITY_TYPES)
    items = []
    for field in ctx.fields:
        document = ctx.documents.get(field.document_id)
        if document is None or document.document_type not in types:
            continue
        if field.ui_section not in {"identity", "contact"} or not field.citations:
            continue
        items.append(ctx.evidence(field))
    return items


def _medical(ctx: _Context) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for document_id, analysis in ctx.analyses:
        document = ctx.documents.get(document_id)
        filename = document.filename if document else None
        for statement in analysis.key_medical_findings:
            if statement.citations:
                findings.append(
                    {
                        "kind": "ai_finding",
                        "text": statement.text,
                        "document_id": document_id,
                        "filename": filename,
                        "citations": _citations(statement.citations),
                    }
                )
        for check in analysis.knockout_checks:
            if check.citations:
                findings.append(
                    {
                        "kind": "knockout_check",
                        "text": f"{check.factor}: {check.value}",
                        "document_id": document_id,
                        "filename": filename,
                        "confidence": check.confidence,
                        "citations": _citations(check.citations),
                    }
                )
        for lab in analysis.lab_results:
            flag = (lab.reported_flag or "").strip().upper()
            if lab.citations and flag and flag not in {"—", "-", "N", "NORMAL"}:
                findings.append(
                    {
                        "kind": "flagged_lab",
                        "text": f"{lab.name} {lab.value}{(' ' + lab.unit) if lab.unit else ''} "
                        f"(reported flag {flag}; reference {lab.reference_range or 'not stated'})",
                        "document_id": document_id,
                        "filename": filename,
                        "citations": _citations(lab.citations),
                    }
                )
    return findings


def _financial(ctx: _Context) -> dict[str, Any]:
    evidence = []
    for field in ctx.fields:
        document = ctx.documents.get(field.document_id)
        if document is None or not field.citations or field.field_path in EXCLUDED_FINANCIAL_PATHS:
            continue
        if document.document_type == "financial_document" or field.ui_section == "bank_details":
            evidence.append(ctx.evidence(field))
    proposed = (ctx.policy or {}).get("sum_assured")
    currency = (ctx.policy or {}).get("currency")
    existing, existing_field = ctx.first_number("financial.existing_life_cover")
    income, income_field = ctx.first_number("financial.annual_income")
    total = proposed + existing if proposed is not None and existing is not None else None
    multiple = None
    if income and income > 0 and proposed is not None:
        multiple = round((proposed + (existing or 0)) / income, 2)
    return {
        "evidence": evidence,
        "exposure": {
            "currency": currency,
            "proposed_sum_assured": proposed,
            "existing_cover": {
                "status": "declared" if existing is not None else NOT_AVAILABLE,
                "amount": existing,
                "reason": None
                if existing is not None
                else "No existing insurance cover is stated in the uploaded documents.",
                "citations": _citations(existing_field.citations) if existing_field else [],
            },
            "total_exposure": total,
            "annual_income": {
                "status": "stated" if income is not None else NOT_AVAILABLE,
                "amount": income,
                "citations": _citations(income_field.citations) if income_field else [],
            },
            "cover_to_income_multiple": multiple,
            "multiple_includes_existing_cover": existing is not None,
        },
    }


# ---------------------------------------------------------------------- rules


def _evaluate(rule: Rule, ctx: _Context, financial: dict[str, Any]) -> dict[str, Any]:
    base = {
        "rule_id": rule.rule_id,
        "title": rule.title,
        "category": rule.category,
        "outcome": rule.outcome,
        "points": rule.points,
        "rationale": rule.rationale,
    }

    def result(status: str, reason: str, evidence: list[dict[str, Any]] | None = None):
        return {**base, "status": status, "reason": reason, "evidence": evidence or []}

    source = rule.source
    if source.type == "field":
        fields = [f for f in ctx.fields_at(source.field_path or "") if f.citations]
        if not fields:
            return result("not_evaluable", f"No reviewed or extracted value for {source.field_path}.")
        hits, checked = [], 0
        for field in fields:
            value = field.effective_value
            if source.component and isinstance(value, dict):
                value = value.get(source.component)
            try:
                matched = compare(rule.operator, value, rule.value)
            except (TypeError, ValueError):
                continue
            checked += 1
            if matched:
                hits.append(ctx.evidence(field, value=value if source.component else None))
        if not checked:
            return result("not_evaluable", "The extracted value could not be compared.")
        if hits:
            return result("triggered", rule.rationale, hits)
        return result("not_triggered", "The extracted value does not meet the rule condition.")

    if source.type == "lab_flags":
        labs = [lab for _, analysis in ctx.analyses for lab in analysis.lab_results]
        if not labs:
            return result("not_evaluable", "No AI-extracted lab results are available.")
        flags = {flag.upper() for flag in source.flags or []}
        flagged = []
        for document_id, analysis in ctx.analyses:
            for lab in analysis.lab_results:
                if (lab.reported_flag or "").strip().upper() in flags and lab.citations:
                    flagged.append(
                        {
                            "label": lab.name,
                            "value": f"{lab.value} {lab.unit or ''}".strip(),
                            "document_id": document_id,
                            "citations": _citations(lab.citations),
                        }
                    )
        if compare(rule.operator, len(flagged), rule.value):
            return result("triggered", f"{len(flagged)} lab values are flagged by the report.", flagged)
        return result("not_triggered", f"{len(flagged)} lab values are flagged by the report.")

    if source.type == "proposal":
        value = (ctx.policy or {}).get(source.key or "")
        if value is None:
            return result("not_evaluable", "The proposed policy value was not captured.")
        evidence = [
            {
                "label": f"Proposed {str(source.key).replace('_', ' ')}",
                "value": value,
                "source": "case_product_selection",
                "citations": [],
            }
        ]
        if compare(rule.operator, value, rule.value):
            return result("triggered", rule.rationale, evidence)
        return result("not_triggered", "The proposed value is within the rule limit.")

    if source.type == "cover_to_income":
        exposure = financial["exposure"]
        multiple = exposure["cover_to_income_multiple"]
        if multiple is None:
            return result(
                "not_evaluable",
                "Needs both a proposed sum assured and a stated annual income.",
            )
        evidence = [
            {
                "label": "Annual income",
                "value": exposure["annual_income"]["amount"],
                "citations": exposure["annual_income"]["citations"],
            },
            {
                "label": "Proposed sum assured",
                "value": exposure["proposed_sum_assured"],
                "source": "case_product_selection",
                "citations": [],
            },
        ]
        if exposure["existing_cover"]["amount"] is not None:
            evidence.append(
                {
                    "label": "Existing cover",
                    "value": exposure["existing_cover"]["amount"],
                    "citations": exposure["existing_cover"]["citations"],
                }
            )
        suffix = "" if exposure["multiple_includes_existing_cover"] else " Existing cover is not stated."
        if compare(rule.operator, multiple, rule.value):
            return result("triggered", f"Cover is {multiple}x annual income.{suffix}", evidence)
        return result("not_triggered", f"Cover is {multiple}x annual income.{suffix}")

    # identity_match
    identity = ctx.identity
    if identity is None or identity.match_status in {"not_available", "not_applicable"}:
        return result("not_evaluable", "No identity documents could be compared with the KYC form.")
    if compare(rule.operator, identity.match_status, rule.value):
        evidence = []
        cited = {
            f.field_path: f
            for doc in identity.documents
            for f in doc.fields
            if f.citations and f.effective_value is not None
        }
        paths = {
            "full_name": "identity.full_name",
            "date_of_birth": "identity.date_of_birth",
            "gender": "identity.gender",
            "address": "identity.address",
        }
        for row in identity.matches:
            if row.match_status != "mismatch":
                continue
            source_field = cited.get(paths.get(row.field, ""))
            evidence.append(
                {
                    "label": row.label,
                    "value": f"KYC: {row.kyc_value or '—'} | Aadhaar: {row.aadhaar_value or '—'} | "
                    f"PAN: {row.pan_value or '—'}",
                    "explanation": row.explanation,
                    "citations": _citations(source_field.citations) if source_field else [],
                }
            )
        return result("triggered", rule.rationale, evidence)
    return result("not_triggered", f"Identity comparison status is {identity.match_status}.")


def _recommendation(
    rules: RuleSet | None, results: list[dict[str, Any]], ctx: _Context, pending_hilt: int
) -> dict[str, Any]:
    common = {
        "disclaimer": DISCLAIMER,
        "pending_hilt_exceptions": pending_hilt,
        "automatic_decision": False,
    }
    if rules is None:
        return {
            **common,
            "status": NOT_AVAILABLE,
            "code": None,
            "label": "Not available",
            "reason": "No underwriting rule set is configured.",
        }
    processed = [d for d in ctx.workspace.documents if d.status in {"completed", "review_required"}]
    if not processed:
        return {
            **common,
            "status": NOT_AVAILABLE,
            "code": "insufficient_evidence",
            "label": "Awaiting evidence",
            "reason": "No documents have been processed yet.",
            "rule_set": {"id": rules.rule_set_id, "version": rules.version, "is_demo": rules.is_demo},
        }
    refer = [r for r in results if r["status"] == "triggered" and r["outcome"] == "refer"]
    advisory = [r for r in results if r["status"] == "triggered" and r["outcome"] == "advisory"]
    not_evaluable = [r for r in results if r["status"] == "not_evaluable"]
    if refer:
        code, label = "refer_to_underwriter", "Refer to underwriter"
        reason = "; ".join(r["title"] for r in refer)
    elif advisory:
        code, label = "review_highlighted_findings", "Review highlighted findings"
        reason = "; ".join(r["title"] for r in advisory)
    else:
        code, label = "no_adverse_rule_triggered", "No adverse rule triggered"
        reason = "None of the evaluated rules were triggered. This is not an approval."
    if not reason.endswith("."):
        reason += "."
    if not_evaluable:
        reason += f" {len(not_evaluable)} rule(s) could not be evaluated for lack of evidence."
    if pending_hilt:
        reason += f" {pending_hilt} HILT exception(s) are still open."
    return {
        **common,
        "status": "available",
        "code": code,
        "label": label,
        "reason": reason.strip(),
        "triggered_rule_ids": [r["rule_id"] for r in refer + advisory],
        "rule_set": {"id": rules.rule_set_id, "version": rules.version, "is_demo": rules.is_demo},
    }


def _risk_score(rules: RuleSet | None, results: list[dict[str, Any]]) -> dict[str, Any]:
    scoring = rules.risk_scoring if rules else None
    if scoring is None:
        return {
            "status": "not_assessed",
            "score": None,
            "reason": "No risk assessment model is configured.",
        }
    evaluated = [r for r in results if r["status"] in {"triggered", "not_triggered"}]
    if not evaluated:
        return {
            "status": "not_assessed",
            "score": None,
            "reason": "No rule could be evaluated with the available evidence.",
            "model": {"id": scoring.model_id, "version": scoring.version},
        }
    points = sum(r["points"] for r in results if r["status"] == "triggered")
    score = max(scoring.scale_min, min(scoring.scale_max, scoring.scale_min + points))
    band = score_band(scoring, score)
    return {
        "status": "assessed",
        "score": score,
        "scale_min": scoring.scale_min,
        "scale_max": scoring.scale_max,
        "band": band.label,
        "interpretation": band.interpretation,
        "method": scoring.method,
        "evaluated_rules": len(evaluated),
        "total_rules": len(results),
        "model": {
            "id": scoring.model_id,
            "version": scoring.version,
            "approved": scoring.approved,
            "is_demo": bool(rules and rules.is_demo),
        },
    }


def _issues(ctx: _Context, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    present = {doc.document_type for doc in ctx.workspace.documents}
    for document_type, label in EXPECTED_EVIDENCE:
        if document_type not in present:
            issues.append(
                {
                    "category": "missing_evidence",
                    "severity": "info",
                    "message": f"No {label.lower()} has been uploaded.",
                }
            )
    if not present.intersection(IDENTITY_TYPES):
        issues.append(
            {
                "category": "missing_evidence",
                "severity": "info",
                "message": "No Aadhaar or PAN document has been uploaded.",
            }
        )
    for exception in ctx.workspace.case_review.exceptions:
        if exception.status != "pending":
            continue
        issues.append(
            {
                "category": "hilt_exception",
                "severity": exception.severity,
                "message": f"{exception.title}"
                + (f": {exception.message}" if exception.message else ""),
                "field_ids": list(exception.field_ids),
                "document_ids": list(exception.document_ids),
            }
        )
    if ctx.identity is not None:
        for issue in ctx.identity.issues:
            if issue.category in {"data_mismatch", "invalid_format", "verification_failed"}:
                issues.append(
                    {
                        "category": f"identity_{issue.category}",
                        "severity": issue.severity,
                        "message": issue.message,
                    }
                )
    for rule in results:
        if rule["status"] == "not_evaluable":
            issues.append(
                {
                    "category": "rule_not_evaluable",
                    "severity": "info",
                    "message": f"{rule['title']}: {rule['reason']}",
                }
            )
    return issues


# ------------------------------------------------------------------ build/persist


def compute_assessment(
    session: Session, *, case: Case, settings: Settings
) -> tuple[dict[str, Any], RuleSet | None]:
    from idp.identity.service import build_identity_summary
    from idp.services.workspace import build_workspace

    workspace = build_workspace(
        session, tenant_id=case.tenant_id, external_case_id=case.external_case_id
    )
    try:
        identity = build_identity_summary(
            session, case=case, tenant_id=case.tenant_id, settings=settings
        )
    except Exception:  # identity data is optional input
        logger.warning("Identity summary unavailable for assessment case_id=%s", case.id)
        identity = None
    rules = load_rule_set(settings.underwriting_rules_path)
    ctx = _Context(workspace, identity)
    financial = _financial(ctx)
    results = [_evaluate(rule, ctx, financial) for rule in (rules.rules if rules else [])]
    pending_hilt = sum(e.status == "pending" for e in workspace.case_review.exceptions)
    result = {
        "engine_version": ENGINE_VERSION,
        "inputs": {
            "documents": [
                {
                    "id": d.id,
                    "type": d.document_type,
                    "status": d.status,
                    "filename": d.filename,
                }
                for d in workspace.documents
            ],
            "processed_documents": sum(
                d.status in {"completed", "review_required"} for d in workspace.documents
            ),
            "ai_analyses": len(ctx.analyses),
            "rule_set": (
                {
                    "id": rules.rule_set_id,
                    "version": rules.version,
                    "checksum": rules.checksum,
                    "is_demo": rules.is_demo,
                    "source": rules.source,
                }
                if rules
                else None
            ),
        },
        "proposed_terms": _proposed_terms(ctx),
        "applicant": _applicant(ctx),
        "medical_findings": _medical(ctx),
        "financial": financial,
        "rule_results": results,
        "hilt": {
            "pending": pending_hilt,
            "open_flags": workspace.case_review.open_flags,
        },
        "issues": _issues(ctx, results),
        "recommendation": _recommendation(rules, results, ctx, pending_hilt),
        "risk_score": _risk_score(rules, results),
        "recommended_terms": {
            "status": NOT_AVAILABLE,
            "reason": "No authorized rule for recommended terms is configured.",
        },
        "revised_premium": {
            "status": NOT_AVAILABLE,
            "amount": None,
            "reason": "No authorized insurer pricing rule for a revised premium is configured.",
        },
        "disclaimer": DISCLAIMER,
    }
    return result, rules


def fingerprint(result: dict[str, Any]) -> str:
    raw = json.dumps(result, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def latest_assessment(session: Session, case: Case) -> CaseAssessment | None:
    return session.scalar(
        select(CaseAssessment)
        .where(CaseAssessment.case_id == case.id, CaseAssessment.tenant_id == case.tenant_id)
        .order_by(CaseAssessment.version.desc())
        .limit(1)
    )


def refresh_case_assessment(
    session: Session,
    *,
    case: Case,
    settings: Settings,
    actor: str,
    correlation_id: str,
    trigger: str,
) -> tuple[CaseAssessment, bool]:
    """Store a new assessment version when its inputs changed. Returns (assessment, created)."""
    session.flush()
    result, rules = compute_assessment(session, case=case, settings=settings)
    digest = fingerprint(result)
    latest = latest_assessment(session, case)
    if latest is not None and latest.fingerprint == digest:
        return latest, False
    version = (
        session.scalar(
            select(func.max(CaseAssessment.version)).where(CaseAssessment.case_id == case.id)
        )
        or 0
    ) + 1
    assessment = CaseAssessment(
        tenant_id=case.tenant_id,
        case_id=case.id,
        version=version,
        fingerprint=digest,
        trigger=trigger,
        engine_version=ENGINE_VERSION,
        rule_set_id=rules.rule_set_id if rules else None,
        rule_set_version=rules.version if rules else None,
        result_json=result,
        created_by=actor,
        correlation_id=correlation_id,
    )
    session.add(assessment)
    session.flush()
    append_audit(
        session,
        tenant_id=case.tenant_id,
        case_id=case.id,
        actor_subject=actor,
        action="case.assessment_generated",
        outcome="success",
        correlation_id=correlation_id,
        metadata={
            "assessment_version": version,
            "reason": trigger,
            "recommendation": result["recommendation"].get("code") or "not_available",
            "status": result["risk_score"]["status"],
            "result_count": sum(r["status"] == "triggered" for r in result["rule_results"]),
        },
    )
    return assessment, True


def safe_refresh(
    session: Session, *, case: Case, settings: Settings, actor: str, correlation_id: str, trigger: str
) -> None:
    """Refresh without letting an assessment problem fail the user's main action."""
    try:
        with session.begin_nested():
            refresh_case_assessment(
                session,
                case=case,
                settings=settings,
                actor=actor,
                correlation_id=correlation_id,
                trigger=trigger,
            )
    except Exception as exc:
        logger.warning(
            "Case assessment refresh failed case_id=%s trigger=%s exception_type=%s",
            case.id,
            trigger,
            type(exc).__name__,
        )


def final_terms(session: Session, case: Case) -> dict[str, Any]:
    decision = session.scalar(
        select(UnderwritingDecision)
        .where(UnderwritingDecision.case_id == case.id, UnderwritingDecision.tenant_id == case.tenant_id)
        .order_by(UnderwritingDecision.decided_at.desc(), UnderwritingDecision.id.desc())
        .limit(1)
    )
    if decision is None:
        return {"status": "not_recorded", "reason": "No underwriting decision has been recorded."}
    return {
        "status": "recorded",
        "decision": decision.decision,
        "approved_sum_assured": float(decision.approved_sum_assured)
        if decision.approved_sum_assured is not None
        else None,
        "applicable_premium": float(decision.applicable_premium)
        if decision.applicable_premium is not None
        else None,
        "additional_terms": decision.additional_terms,
        "underwriter_subject": decision.underwriter_subject,
        "decided_at": decision.decided_at.isoformat(),
    }


def assessment_view(session: Session, *, case: Case, settings: Settings) -> dict[str, Any]:
    latest = latest_assessment(session, case)
    current, rules = compute_assessment(session, case=case, settings=settings)
    versions = list(
        session.scalars(
            select(CaseAssessment)
            .where(CaseAssessment.case_id == case.id, CaseAssessment.tenant_id == case.tenant_id)
            .order_by(CaseAssessment.version.desc())
        )
    )
    return {
        "case_id": case.external_case_id,
        "rules_configured": rules is not None,
        "stale": latest is None or latest.fingerprint != fingerprint(current),
        "latest": _version_out(latest) if latest else None,
        "versions": [
            {
                "version": item.version,
                "created_at": item.created_at,
                "trigger": item.trigger,
                "created_by": item.created_by,
                "recommendation": (item.result_json.get("recommendation") or {}).get("code"),
                "risk_score": (item.result_json.get("risk_score") or {}).get("score"),
            }
            for item in versions
        ],
        "final_terms": final_terms(session, case),
    }


def _version_out(item: CaseAssessment) -> dict[str, Any]:
    return {
        "version": item.version,
        "created_at": item.created_at,
        "trigger": item.trigger,
        "created_by": item.created_by,
        "engine_version": item.engine_version,
        "fingerprint": item.fingerprint,
        "result": item.result_json,
    }


def assessment_version(session: Session, *, case: Case, version: int) -> dict[str, Any] | None:
    item = session.scalar(
        select(CaseAssessment).where(
            CaseAssessment.case_id == case.id,
            CaseAssessment.tenant_id == case.tenant_id,
            CaseAssessment.version == version,
        )
    )
    return _version_out(item) if item else None
