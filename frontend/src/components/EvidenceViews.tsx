import type {
  AdditionalFact,
  AiAnalysis,
  Citation,
  EvidenceField,
  GroundedStatement,
  KnockoutCheck,
  LabResult,
} from "../types";
import { confidenceLabel, formatValue } from "../format";

interface FieldActions {
  onCitation: (field: EvidenceField, citationIndex?: number) => void;
  onReview: (field: EvidenceField) => void;
}

function StateBadge({ field }: { field: EvidenceField }) {
  const state = field.extraction_status;
  return <span className={`status-badge status-${state}`}>{state.replaceAll("_", " ")}</span>;
}

function CitationPreview({ citation }: { citation: Citation }) {
  return (
    <div className="citation-preview">
      <span>Source citation · page {citation.page}</span>
      <blockquote>{citation.excerpt}</blockquote>
    </div>
  );
}

export function EvidenceRow({
  field,
  onCitation,
  onReview,
}: { field: EvidenceField } & FieldActions) {
  const hasValue = field.candidate_value !== null && field.candidate_value !== undefined;
  const shownValue = formatValue(field.effective_value);
  return (
    <article className={`evidence-row ${field.extraction_status === "uncertain" ? "pending" : ""}`}>
      <div className="evidence-value-block">
        <div className="evidence-label-line">
          <h4>{field.label}</h4>
          <StateBadge field={field} />
          <span className={`status-badge status-${field.review_state}`}>
            {field.review_state.replaceAll("_", " ")}
          </span>
        </div>
        <div className={hasValue ? "field-value" : "field-value missing"}>
          {shownValue}
          {hasValue && field.unit ? <span className="field-unit"> {field.unit}</span> : null}
        </div>
        <div className="field-meta">
          <span>{confidenceLabel(field.confidence)}</span>
          {field.validations.map((finding) => (
            <span className={`validation-${finding.severity}`} key={finding.code}>
              {finding.code.replaceAll("_", " ")}
            </span>
          ))}
        </div>
        {field.citations[0] ? <CitationPreview citation={field.citations[0]} /> : null}
      </div>
      <div className="field-actions">
        {field.review_state !== "not_reviewable" ? (
          <button className="text-button" type="button" onClick={() => onReview(field)}>
            {field.review_state === "pending" ? "Review" : "Update review"}
          </button>
        ) : null}
        {field.citations.length ? (
          <button className="text-button" type="button" onClick={() => onCitation(field, 0)}>
            Page {field.citations[0].page} source
          </button>
        ) : (
          <span className="no-source">No source</span>
        )}
      </div>
    </article>
  );
}

function EmptyEvidence() {
  return (
    <div className="empty-card">
      <div className="empty-icon" aria-hidden="true">DOC</div>
      <h3>No extracted evidence yet</h3>
      <p>Upload a synthetic medical PDF or image. A separate worker will publish grounded fields here.</p>
    </div>
  );
}

const vitalSignDefinitions = [
  {
    path: "observations.blood_pressure",
    label: "Blood pressure",
    description: "Systolic pressure while the heart beats and diastolic pressure while it rests.",
    reference: "Typical adult reference: about 90/60–120/80 mmHg.",
  },
  {
    path: "observations.pulse_bpm",
    label: "Pulse / heart rate",
    description: "Number of heart beats per minute at rest.",
    reference: "Typical resting adult reference: 60–100 bpm.",
  },
  {
    path: "observations.respiratory_rate_bpm",
    label: "Respiratory rate",
    description: "Number of breaths taken per minute.",
    reference: "Typical adult reference: 12–18 breaths/min; some references use up to 20.",
  },
  {
    path: "observations.body_temperature",
    label: "Body temperature",
    description: "Body heat, shown in the unit reported by the document.",
    reference: "Typical adult reference: 97.7–99.1°F (36.5–37.3°C).",
  },
] as const;

const summaryMetricDefinitions = [
  { path: "observations.bmi", label: "BMI", featured: true },
  { path: "observations.blood_pressure", label: "Blood pressure", featured: false },
  { path: "labs.hba1c", label: "HbA1c", featured: false },
] as const;

function SummaryMetricCard({
  label,
  field,
  featured,
  onCitation,
}: {
  label: string;
  field: EvidenceField | undefined;
  featured: boolean;
  onCitation: (field: EvidenceField, citationIndex?: number) => void;
}) {
  const rejected = field?.review_state === "rejected";
  const hasValue = !rejected
    && field?.effective_value !== null
    && field?.effective_value !== undefined;
  const value = rejected
    ? "Rejected in review"
    : hasValue
      ? formatValue(field?.effective_value)
      : "Not detected in this run";

  return (
    <article className={`summary-metric-card${featured ? " featured" : ""}`}>
      <div className="summary-metric-heading">
        <span>{label}</span>
        {field?.extraction_status === "uncertain" ? (
          <span className="status-badge status-uncertain">Needs review</span>
        ) : null}
      </div>
      <div className={`summary-metric-value${hasValue ? "" : " missing"}`}>
        <strong>{value}</strong>
        {hasValue && field?.unit ? <span>{field.unit}</span> : null}
      </div>
      <div className="summary-metric-footer">
        {field?.citations[0] ? (
          <>
            <span>Page {field.citations[0].page}</span>
            <button type="button" className="text-button" onClick={() => onCitation(field, 0)}>
              View source
            </button>
          </>
        ) : (
          <span>{field ? "No source citation" : "Not present in this run"}</span>
        )}
      </div>
    </article>
  );
}

export function SummaryView({
  fields,
  analysis,
  onAiCitation,
  canGenerateSummary,
  onGenerateSummary,
  ...actions
}: {
  fields: EvidenceField[];
  analysis: AiAnalysis | null;
  onAiCitation: (citation: Citation) => void;
  canGenerateSummary: boolean;
  onGenerateSummary: () => void;
} & FieldActions) {
  const found = fields.filter((field) => field.candidate_value !== null);
  const summaryFields = found.filter((field) => field.ui_section === "summary");
  return (
    <div role="tabpanel" aria-label="AI Summary" className="analysis-layout">
      <div className="summary-metric-grid" role="group" aria-label="Key reported values">
        {summaryMetricDefinitions.map((metric) => (
          <SummaryMetricCard
            key={metric.path}
            label={metric.label}
            featured={metric.featured}
            field={fields.find((field) => field.field_path === metric.path)}
            onCitation={actions.onCitation}
          />
        ))}
      </div>
      <section className="card-section">
        <div className="section-heading">
          <h3>AI Medical Assessment Summary</h3>
          {canGenerateSummary ? (
            <button type="button" className="secondary-button compact" onClick={onGenerateSummary}>
              Generate AI summary
            </button>
          ) : null}
        </div>
        {analysis?.summary ? (
          <GroundedStatement statement={analysis.summary} onCitation={onAiCitation} />
        ) : (
          <p className="quiet-message">An AI summary will appear after the report is processed by the configured AI provider.</p>
        )}
        <p className="analysis-disclaimer">
          AI-generated report observations are for review only. They are not a diagnosis or treatment plan.
        </p>
      </section>
      <section className="card-section">
        <div className="section-heading"><h3>Key medical findings</h3></div>
        {analysis?.key_medical_findings.length ? (
          <div className="analysis-statements">
            {analysis.key_medical_findings.map((statement, index) => (
              <GroundedStatement key={`${index}-${statement.text}`} statement={statement} onCitation={onAiCitation} />
            ))}
          </div>
        ) : (
          <p className="quiet-message">Key findings will appear here after AI analysis of the report.</p>
        )}
      </section>
      <section className="card-section">
        <div className="section-heading"><h3>Recommended follow-up</h3></div>
        {analysis?.recommendations.length ? (
          <div className="analysis-statements">
            {analysis.recommendations.map((statement, index) => (
              <GroundedStatement key={`${index}-${statement.text}`} statement={statement} onCitation={onAiCitation} />
            ))}
          </div>
        ) : (
          <p className="quiet-message">
            No report-supported follow-up was generated. Any follow-up should be discussed with a qualified clinician.
          </p>
        )}
      </section>
      <section className="card-section">
        <div className="section-heading">
          <div>
            <h3>Extracted medical evidence</h3>
            <p>Each non-null value remains linked to its immutable source.</p>
          </div>
        </div>
        {summaryFields.length ? (
          <div className="evidence-list">
            {summaryFields.map((field) => <EvidenceRow key={field.id} field={field} {...actions} />)}
          </div>
        ) : <p className="quiet-message">No additional summary fields were extracted from this report.</p>}
      </section>
    </div>
  );
}

export function LabReportsView({
  results,
  onCitation,
}: {
  results: LabResult[];
  onCitation: (citation: Citation) => void;
}) {
  if (!results.length) {
    return (
      <div className="empty-card" role="tabpanel" aria-label="Lab Reports">
        <div className="empty-icon" aria-hidden="true">LAB</div>
        <h3>No cited lab results available</h3>
        <p>AI-extracted lab values will appear here after the report is processed.</p>
      </div>
    );
  }
  const grouped = groupBy(results, (result) => result.category);
  return (
    <div role="tabpanel" aria-label="Lab Reports" className="lab-report-grid">
      {Object.entries(grouped).map(([category, items]) => (
        <section className="card-section" key={category}>
          <div className="section-heading">
            <h3>{category.replaceAll("_", " ")}</h3>
          </div>
          {items.map((result, index) => (
            <article className="lab-result" key={`${result.name}-${index}`}>
              <div className="lab-result-row">
                <span>{result.name}</span>
                <strong>{result.value}{result.unit ? ` ${result.unit}` : ""}</strong>
                <span>{result.reference_range ?? "Reference range not stated"}</span>
                <span className="lab-reported-flag">
                  {result.reported_flag ? `Report flag: ${result.reported_flag}` : "No report flag"}
                </span>
              </div>
              <div className="field-meta">
                <span>{confidenceLabel(result.confidence)}</span>
                {result.citations.map((citation, citationIndex) => (
                  <button
                    className="text-button"
                    key={`${citation.page}-${citationIndex}`}
                    type="button"
                    onClick={() => onCitation(citation)}
                  >
                    Page {citation.page} source
                  </button>
                ))}
              </div>
              {result.citations[0] ? <CitationPreview citation={result.citations[0]} /> : null}
            </article>
          ))}
        </section>
      ))}
    </div>
  );
}

export function KnockoutChecksView({
  checks,
  onCitation,
}: {
  checks: KnockoutCheck[];
  onCitation: (citation: Citation) => void;
}) {
  return (
    <div role="tabpanel" aria-label="Knockout Checks" className="checks-layout">
      <section className="card-section knockout-disclaimer">
        <div className="section-heading"><h3>Knockout checks</h3></div>
        <p>
          These are AI-extracted vital and screening findings for reviewer verification only.
          No decline, loading, eligibility, or coverage action is calculated.
        </p>
      </section>
      {checks.length ? checks.map((check, index) => (
        <article className="card-section knockout-card" key={`${check.factor}-${index}`}>
          <div className="section-heading">
            <h3>{check.factor}</h3>
            <span className="status-badge status-uncertain">Verify in source</span>
          </div>
          <p className="knockout-value">Reported value: <strong>{check.value}</strong></p>
          <div className="field-meta">
            <span>{confidenceLabel(check.confidence)}</span>
            {check.citations.map((citation, citationIndex) => (
              <button
                className="text-button"
                key={`${citation.page}-${citationIndex}`}
                type="button"
                onClick={() => onCitation(citation)}
              >
                Page {citation.page} source
              </button>
            ))}
          </div>
          {check.citations[0] ? <CitationPreview citation={check.citations[0]} /> : null}
        </article>
      )) : (
        <section className="card-section">
          <p className="quiet-message">No explicit vital or screening factors were extracted from this report.</p>
        </section>
      )}
    </div>
  );
}

export function VitalsView({
  fields,
  analysis,
  onAiCitation,
  ...actions
}: {
  fields: EvidenceField[];
  analysis: AiAnalysis | null;
  onAiCitation: (citation: Citation) => void;
} & FieldActions) {
  const vitalSignPaths = new Set<string>(vitalSignDefinitions.map((definition) => definition.path));
  const vitalFields = fields.filter((field) => field.ui_section === "vitals");
  const fieldsByPath = new Map(vitalFields.map((field) => [field.field_path, field]));
  const otherVitals = vitalFields.filter(
    (field) => field.candidate_value !== null && !vitalSignPaths.has(field.field_path),
  );
  const grouped = groupBy(otherVitals, (field) => field.ui_group);
  return (
    <div role="tabpanel" aria-label="Vitals" className="analysis-layout">
      <section className="card-section">
        <div className="section-heading"><h3>AI report observations</h3></div>
        {analysis?.vitals_summary ? (
          <GroundedStatement statement={analysis.vitals_summary} onCitation={onAiCitation} />
        ) : (
          <p className="quiet-message">AI observations about vitals and major report factors will appear after processing.</p>
        )}
        {analysis?.major_vital_factors.length ? (
          <div className="analysis-statements">
            {analysis.major_vital_factors.map((statement, index) => (
              <GroundedStatement key={`${index}-${statement.text}`} statement={statement} onCitation={onAiCitation} />
            ))}
          </div>
        ) : null}
      </section>
      <section className="card-section vital-signs-section">
        <div className="section-heading">
          <div>
            <h3>Primary vital signs</h3>
            <p>Report values are shown only when extracted; reference ranges are general adult context.</p>
          </div>
        </div>
        <div className="vital-sign-grid">
          {vitalSignDefinitions.map((definition) => {
            const field = fieldsByPath.get(definition.path);
            const hasValue = field !== undefined
              && field.candidate_value !== null
              && field.candidate_value !== undefined;
            const value = hasValue
              ? `${formatValue(field.candidate_value)}${field.unit ? ` ${field.unit}` : ""}`
              : field?.extraction_status === "uncertain"
                ? "Needs review"
                : "Not detected in this run";
            return (
              <article className="vital-sign-card" key={definition.path}>
                <h4>{definition.label}</h4>
                <p className="vital-sign-description">{definition.description}</p>
                <strong className={hasValue ? "vital-sign-value" : "vital-sign-value missing"}>
                  {value}
                </strong>
                <p className="vital-sign-reference">{definition.reference}</p>
                {field ? (
                  <div className="field-meta">
                    <span>{field.extraction_status.replaceAll("_", " ")}</span>
                    {hasValue ? <span>{confidenceLabel(field.confidence)}</span> : null}
                    {field.citations[0] ? (
                      <button
                        className="text-button"
                        type="button"
                        onClick={() => actions.onCitation(field, 0)}
                      >
                        Page {field.citations[0].page} source
                      </button>
                    ) : null}
                  </div>
                ) : null}
                {field?.citations[0] ? <CitationPreview citation={field.citations[0]} /> : null}
              </article>
            );
          })}
        </div>
        <p className="analysis-disclaimer">
          Reference ranges vary with age, health, and circumstances. They are not report results,
          diagnostic thresholds, or a substitute for clinical interpretation.
        </p>
      </section>
      {Object.entries(grouped).length ? (
        Object.entries(grouped).map(([group, items]) => (
          <section className="card-section" key={group}>
            <div className="section-heading">
              <div>
                <h3>{group}</h3>
                <p>Extracted values are linked to their source for reviewer confirmation.</p>
              </div>
            </div>
            {items.map((field) => <EvidenceRow key={field.id} field={field} {...actions} />)}
          </section>
        ))
      ) : (
        <section className="card-section">
          <div className="section-heading"><h3>Extracted vitals</h3></div>
          <p className="quiet-message">No structured vital fields were extracted from this report.</p>
        </section>
      )}
    </div>
  );
}

export function AdditionalFactsView({
  facts,
  onCitation,
}: {
  facts: AdditionalFact[];
  onCitation: (fact: AdditionalFact, citationIndex?: number) => void;
}) {
  if (!facts.length) {
    return (
      <div className="empty-card" role="tabpanel" aria-label="Additional facts">
        <div className="empty-icon" aria-hidden="true">AI</div>
        <h3>No additional facts returned</h3>
        <p>Report findings remain available in AI Summary and Vitals when present.</p>
      </div>
    );
  }
  const grouped = groupBy(facts, (fact) => fact.category);
  return (
    <div role="tabpanel" aria-label="Additional facts" className="section-grid">
      {Object.entries(grouped).map(([category, items]) => (
        <section className="card-section" key={category}>
          <div className="section-heading">
            <div>
              <h3>{category.replaceAll("_", " ")}</h3>
              <p>Run-local grounded details outside the stable primary field contract.</p>
            </div>
          </div>
          {items.map((fact) => (
            <article className="evidence-row" key={fact.id}>
              <div className="evidence-value-block">
                <div className="evidence-label-line">
                  <h4>{fact.name}</h4>
                  <span className={`status-badge status-${fact.extraction_status}`}>
                    additional fact
                  </span>
                </div>
                <div className="field-value">
                  {formatValue(fact.value)}
                  {fact.unit ? <span className="field-unit"> {fact.unit}</span> : null}
                </div>
                <div className="field-meta">
                  <span>{confidenceLabel(fact.confidence)}</span>
                  {fact.linked_field_path ? <span>Linked to {fact.linked_field_path}</span> : null}
                </div>
                {fact.citations[0] ? <CitationPreview citation={fact.citations[0]} /> : null}
              </div>
              <div className="field-actions">
                {fact.citations.length ? (
                  <button className="text-button" type="button" onClick={() => onCitation(fact, 0)}>
                    Page {fact.citations[0].page} source
                  </button>
                ) : <span className="no-source">No source</span>}
              </div>
            </article>
          ))}
        </section>
      ))}
    </div>
  );
}

function GroundedStatement({
  statement,
  onCitation,
}: {
  statement: GroundedStatement;
  onCitation: (citation: Citation) => void;
}) {
  return (
    <article className="analysis-statement">
      <p>{statement.text}</p>
      <div className="analysis-citations">
        {statement.citations.map((citation, index) => (
          <button
            className="text-button"
            key={`${citation.document_id}-${citation.page}-${index}`}
            type="button"
            onClick={() => onCitation(citation)}
          >
            Page {citation.page} source
          </button>
        ))}
      </div>
    </article>
  );
}

function groupBy<T>(items: T[], key: (item: T) => string): Record<string, T[]> {
  return items.reduce<Record<string, T[]>>((groups, item) => {
    const group = key(item);
    (groups[group] ??= []).push(item);
    return groups;
  }, {});
}
