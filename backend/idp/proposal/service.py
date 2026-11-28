"""Read-only proposal view for a case.

Every value carries its source so the underwriter can tell them apart:

* ``proposal_form``      what the applicant declared on the submitted proposal form;
* ``product_selection``  what the underwriter selected from the catalogue at case creation;
* ``product_catalogue``  how the insurer configured the product (benefits, riders);
* ``document_evidence``  values extracted from other uploaded documents; ``verified`` is true
                         only after a person reviewed the extracted value;
* ``ai_assessment``      the latest case assessment;
* ``underwriter_decision`` the recorded final decision;
* ``case_record``        case data such as proposal number and workflow stage.

Values are never merged or overwritten across sources. A value that no source provides is
returned as ``None`` and shown as "Not Available".
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from idp.assessment.service import final_terms, latest_assessment
from idp.models import Case, Document
from idp.products.catalogue import FREQUENCY_LABELS, ProductCatalogue
from idp.schemas import FieldOut
from idp.services.workspace import build_workspace, document_summary

PROPOSAL_DOCUMENT_TYPE = "proposal_form"
PAYMENTS_PER_YEAR = {"annual": 1, "half_yearly": 2, "quarterly": 4, "monthly": 12}
# Document evidence shown beside a declaration: (document_type, field_path).
DECLARATION_EVIDENCE: dict[str, list[tuple[str, str]]] = {
    "occupation": [("kyc_individual", "identity.occupation")],
    "annual_income": [("financial_document", "financial.annual_income")],
    "tobacco": [("medical_report", "lifestyle.tobacco")],
    "existing_cover": [("financial_document", "financial.existing_life_cover")],
    "medical_history": [("medical_report", "history.conditions")],
    "previous_insurance": [("financial_document", "financial.existing_policy_count")],
}


def _item(
    key: str,
    label: str,
    value: Any,
    source: str,
    *,
    kind: str = "text",
    currency: str | None = None,
    highlight: bool = False,
    note: str | None = None,
    citations: list[dict[str, Any]] | None = None,
    document_id: str | None = None,
    verified: bool | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "value": value,
        "kind": kind,
        "currency": currency,
        "source": source if value is not None else None,
        "highlight": highlight,
        "note": note,
        "citations": citations or [],
        "document_id": document_id,
        "verified": verified,
        "evidence": evidence or [],
    }


def _citations(field: FieldOut) -> list[dict[str, Any]]:
    return [
        {
            "document_id": c.document_id,
            "document_version": c.document_version,
            "page": c.page,
            "excerpt": c.excerpt,
        }
        for c in field.citations
    ]


def _usable(field: FieldOut) -> bool:
    return field.effective_value is not None and field.review_state not in {
        "rejected",
        "not_applicable",
    }


def _human_reviewed(field: FieldOut) -> bool:
    return field.latest_review is not None and field.latest_review.decision in {
        "accepted",
        "corrected",
    }


class _Fields:
    """Latest usable field per (document_type, field_path), newest document first."""

    def __init__(self, workspace: Any):
        self.documents = {doc.id: doc for doc in workspace.documents}
        order = {doc.id: index for index, doc in enumerate(workspace.documents)}  # newest first
        self.by_key: dict[tuple[str, str], FieldOut] = {}
        for field in sorted(workspace.fields, key=lambda f: order.get(f.document_id, 0)):
            document = self.documents.get(field.document_id)
            if document is None or not _usable(field):
                continue
            self.by_key.setdefault((document.document_type, field.field_path), field)

    def get(self, document_type: str, path: str) -> FieldOut | None:
        return self.by_key.get((document_type, path))

    def form(self, path: str) -> FieldOut | None:
        return self.get(PROPOSAL_DOCUMENT_TYPE, path)


def _form_item(
    fields: _Fields,
    key: str,
    label: str,
    path: str,
    *,
    kind: str = "text",
    currency: str | None = None,
    highlight: bool = False,
) -> dict[str, Any]:
    field = fields.form(path)
    if field is None:
        return _item(key, label, None, "proposal_form", kind=kind, currency=currency,
                     highlight=highlight)
    return _item(
        key,
        label,
        field.effective_value,
        "proposal_form",
        kind=kind,
        currency=currency,
        highlight=highlight,
        citations=_citations(field),
        document_id=field.document_id,
        note="Applicant declaration on the proposal form; not independently verified.",
    )


def _evidence_entries(fields: _Fields, key: str, currency: str | None) -> list[dict[str, Any]]:
    entries = []
    for document_type, path in DECLARATION_EVIDENCE.get(key, []):
        field = fields.get(document_type, path)
        if field is None:
            continue
        document = fields.documents.get(field.document_id)
        reviewed = _human_reviewed(field)
        entries.append(
            {
                "label": field.label,
                "value": field.effective_value,
                "unit": field.unit,
                "currency": currency if field.unit in {"INR", None} and field.data_type == "decimal" else None,
                "source": "document_evidence",
                "verified": reviewed,
                "status": "Reviewed by underwriter" if reviewed else "Extracted, not yet reviewed",
                "document_id": field.document_id,
                "document_type": document_type,
                "filename": document.filename if document else None,
                "citations": _citations(field),
            }
        )
    return entries


def proposal_document(session: Session, case: Case) -> tuple[Document | None, list[Document]]:
    """Return the original (first uploaded) proposal form and all proposal forms on the case."""
    documents = list(
        session.scalars(
            select(Document)
            .where(
                Document.case_id == case.id,
                Document.tenant_id == case.tenant_id,
                Document.document_type == PROPOSAL_DOCUMENT_TYPE,
            )
            .order_by(Document.created_at.asc(), Document.id.asc())
        )
    )
    return (documents[0] if documents else None), documents


def build_proposal_view(
    session: Session, *, case: Case, catalogue: ProductCatalogue
) -> dict[str, Any]:
    workspace = build_workspace(
        session, tenant_id=case.tenant_id, external_case_id=case.external_case_id
    )
    fields = _Fields(workspace)
    policy = dict(case.policy_details_json or {})
    currency = policy.get("currency") or "INR"
    quote = policy.get("indicative_quote") or {}
    quote_ok = quote.get("status") == "indicative" and quote.get("amount") is not None
    found = catalogue.get(policy["product_id"]) if policy.get("product_id") else None
    product = found[0] if found else None
    current_catalogue = found[1] if found else None
    selected_catalogue = policy.get("catalogue") or {}
    original, all_forms = proposal_document(session, case)
    decision = final_terms(session, case)
    assessment = latest_assessment(session, case)
    result = assessment.result_json if assessment else None

    # ------------------------------------------------------------ basic
    stated_number = fields.form("proposal.proposal_number")
    number_note = None
    number_evidence = []
    if stated_number is not None:
        number_evidence.append(
            {
                "label": "Proposal number on the proposal form",
                "value": stated_number.effective_value,
                "source": "proposal_form",
                "verified": False,
                "document_id": stated_number.document_id,
                "citations": _citations(stated_number),
            }
        )
        if str(stated_number.effective_value).strip().casefold() != case.proposal_number.casefold():
            number_note = "The proposal form states a different proposal number. Check the document."
    if decision["status"] == "recorded":
        status_value = f"Decision recorded: {str(decision['decision']).replace('_', ' ').title()}"
        status_source = "underwriter_decision"
    else:
        status_value = case.workflow_stage.replace("_", " ").capitalize()
        status_source = "case_record"
    basic = [
        _item("proposal_number", "Proposal number", case.proposal_number, "case_record",
              note=number_note, evidence=number_evidence),
        _item("insurer", "Insurance company", policy.get("insurer"), "product_selection"),
        _item("product_name", "Product name", policy.get("product_name") or case.product_name,
              "product_selection" if policy else "case_record"),
        _item("plan_name", "Plan option", policy.get("plan_name"), "product_selection"),
        _item("insurance_type", "Insurance type", policy.get("insurance_type"), "product_selection"),
        _form_item(fields, "proposal_date", "Proposal date", "proposal.proposal_date", kind="date"),
        _form_item(fields, "channel", "Application channel", "proposal.channel"),
        _item("proposal_status", "Proposal status", status_value, status_source),
        _item("uploaded_documents", "Uploaded documents", len(workspace.documents), "case_record",
              kind="number"),
    ]

    # --------------------------------------------------------- coverage
    frequency = policy.get("premium_frequency")
    per_year = PAYMENTS_PER_YEAR.get(frequency or "")
    instalment = quote.get("amount") if quote_ok else None
    annual = round(instalment * per_year, 2) if instalment is not None and per_year else None
    annual_note = None
    if annual is not None and per_year and per_year > 1:
        annual_note = (
            f"Annualised: {per_year} × {FREQUENCY_LABELS.get(frequency, frequency).lower()} "
            "instalments. Indicative catalogue premium, not an official insurer quote."
        )
    elif annual is not None:
        annual_note = "Indicative catalogue premium, not an official insurer quote."
    elif frequency == "single":
        annual_note = "Single premium product; there is no annual premium."
    elif policy:
        annual_note = "; ".join(quote.get("reasons") or ["No premium was calculated at case creation."])
    form_sa = fields.form("proposal.sum_assured")
    form_premium = fields.form("proposal.premium")
    breakdown = None
    if quote_ok and quote.get("amount_before_tax") is not None:
        breakdown = {
            "base": quote.get("amount_before_tax"),
            "tax": quote.get("tax_amount"),
            "total": quote.get("amount"),
            "frequency": frequency,
        }
    coverage = [
        _item(
            "sum_assured", "Proposed sum assured", policy.get("sum_assured"), "product_selection",
            kind="money", currency=currency, highlight=True,
            note="Selected at case creation. Never changed by the assessment.",
            evidence=[
                {
                    "label": "Sum assured on the proposal form",
                    "value": form_sa.effective_value,
                    "currency": currency,
                    "source": "proposal_form",
                    "verified": False,
                    "document_id": form_sa.document_id,
                    "citations": _citations(form_sa),
                }
            ] if form_sa else [],
        ),
        _item(
            "annual_premium", "Proposed annual premium", annual, "product_selection",
            kind="money", currency=currency, highlight=True, note=annual_note,
            evidence=[
                {
                    "label": "Premium on the proposal form",
                    "value": form_premium.effective_value,
                    "currency": currency,
                    "source": "proposal_form",
                    "verified": False,
                    "document_id": form_premium.document_id,
                    "citations": _citations(form_premium),
                }
            ] if form_premium else [],
        ),
        _item("instalment_premium", "Instalment premium", instalment, "product_selection",
              kind="money", currency=currency,
              note=f"{FREQUENCY_LABELS.get(frequency, frequency)} instalment (indicative)." if instalment is not None else None),
        _item("premium_frequency", "Premium frequency",
              FREQUENCY_LABELS.get(frequency, frequency) if frequency else None, "product_selection"),
        _item("policy_term", "Policy term", policy.get("policy_term"), "product_selection", kind="years"),
        _item("premium_payment_term", "Premium payment term", policy.get("premium_payment_term"),
              "product_selection", kind="years"),
        _form_item(fields, "payment_mode", "Payment mode", "proposal.payment_mode"),
        _item("premium_breakdown", "Premium breakdown", breakdown, "product_selection",
              kind="breakdown", currency=currency,
              note="Indicative calculation from the product catalogue." if breakdown else None),
    ]

    # ------------------------------------------------- assessed / final
    revised = (result or {}).get("revised_premium") or {}
    risk = (result or {}).get("risk_score") or {}
    recommendation = (result or {}).get("recommendation") or {}
    assessed = [
        _item(
            "ai_recommendation", "AI recommendation",
            recommendation.get("label") if recommendation.get("status") == "available" else None,
            "ai_assessment",
            note=f"Assessment version {assessment.version}." if assessment else "No assessment has been generated yet.",
        ),
        _item(
            "risk_score", "AI risk assessment",
            f"{risk.get('score')} / {risk.get('scale_max')} ({risk.get('band')})"
            if risk.get("status") == "assessed" else None,
            "ai_assessment",
            note=risk.get("reason") if risk.get("status") != "assessed" else
            ("Not an approved model." if not (risk.get("model") or {}).get("approved") else None),
        ),
        _item("revised_premium", "Revised premium", revised.get("amount"), "ai_assessment",
              kind="money", currency=currency,
              note=revised.get("reason") if revised.get("amount") is None else None),
        _item(
            "final_sum_assured", "Final approved sum assured",
            decision.get("approved_sum_assured") if decision["status"] == "recorded" else None,
            "underwriter_decision", kind="money", currency=currency,
            note=None if decision["status"] == "recorded" else "Recorded after the underwriter's decision.",
        ),
        _item(
            "final_premium", "Final approved premium",
            decision.get("applicable_premium") if decision["status"] == "recorded" else None,
            "underwriter_decision", kind="money", currency=currency,
            note=None if decision["status"] == "recorded" else "Recorded after the underwriter's decision.",
        ),
    ]

    # ---------------------------------------------------------- benefits
    riders_catalogue = None
    if product is not None and product.riders is not None:
        riders_catalogue = [r.name for r in product.riders] if product.riders else []
    benefits = [
        _item("cover_type", "Cover type", product.cover_type if product else None, "product_catalogue"),
        _item("death_benefit", "Death benefit", product.death_benefit if product else None,
              "product_catalogue"),
        _item("maturity_benefit", "Maturity benefit", product.maturity_benefit if product else None,
              "product_catalogue"),
        _item(
            "riders_available", "Riders and add-ons available",
            (", ".join(riders_catalogue) if riders_catalogue else "None offered")
            if riders_catalogue is not None else None,
            "product_catalogue",
        ),
        _form_item(fields, "riders_selected", "Riders and add-ons selected", "benefits.riders"),
        _form_item(fields, "rider_sum_assured", "Rider sum assured", "benefits.rider_sum_assured",
                   kind="money", currency=currency),
        _item(
            "additional_benefits", "Additional benefits",
            ("; ".join(product.additional_benefits) if product.additional_benefits else "None listed")
            if product is not None and product.additional_benefits is not None else None,
            "product_catalogue",
        ),
        _form_item(fields, "nominee", "Nominee", "benefits.nominee"),
    ]

    # ------------------------------------------------------ declarations
    rating = policy.get("rating_inputs") or {}
    declarations = []
    for key, label, path, kind in (
        ("occupation", "Occupation", "declarations.occupation", "text"),
        ("annual_income", "Annual income", "declarations.annual_income", "money"),
        ("tobacco", "Smoking / tobacco status", "declarations.tobacco", "text"),
        ("existing_cover", "Existing insurance coverage", "declarations.existing_cover", "money"),
        ("medical_history", "Declared medical history", "declarations.medical_history", "text"),
        ("previous_insurance", "Previous insurance details", "declarations.previous_insurance", "text"),
    ):
        item = _form_item(fields, key, label, path, kind=kind, currency=currency)
        item["evidence"] = _evidence_entries(fields, key, currency)
        if key == "tobacco" and rating.get("smoker") is not None:
            item["evidence"].append(
                {
                    "label": "Smoker status used for pricing",
                    "value": "Smoker" if rating["smoker"] else "Non-smoker",
                    "source": "product_selection",
                    "verified": False,
                    "citations": [],
                }
            )
        declarations.append(item)

    catalogue_note = None
    if current_catalogue is not None and selected_catalogue.get("catalogue_version") not in (
        None, current_catalogue.catalogue_version
    ):
        catalogue_note = (
            f"Benefits come from catalogue version {current_catalogue.catalogue_version}; the product "
            f"was selected under version {selected_catalogue.get('catalogue_version')}."
        )
    elif policy.get("product_id") and product is None:
        catalogue_note = "The selected product is no longer in the product catalogue."

    return {
        "case_id": case.external_case_id,
        "proposal_number": case.proposal_number,
        "has_product_selection": bool(policy.get("product_id")),
        "catalogue": {
            "is_demo": bool(selected_catalogue.get("is_demo") or (current_catalogue and current_catalogue.is_demo)),
            "catalogue_id": selected_catalogue.get("catalogue_id"),
            "catalogue_version": selected_catalogue.get("catalogue_version"),
            "note": catalogue_note,
        },
        "proposal_document": document_summary(session, original).model_dump(mode="json")
        if original else None,
        "proposal_document_count": len(all_forms),
        "sections": [
            {"id": "basic", "title": "Basic proposal information", "items": basic},
            {"id": "coverage", "title": "Coverage & premium details", "items": coverage},
            {"id": "assessed", "title": "Assessed and final terms", "items": assessed},
            {"id": "benefits", "title": "Policy benefits", "items": benefits},
            {"id": "declarations", "title": "Applicant declarations", "items": declarations},
        ],
    }
