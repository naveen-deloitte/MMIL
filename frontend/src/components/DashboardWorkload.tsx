import { useMemo } from "react";
import type { CaseListItem, CaseSummary } from "../types";

type MetricIcon = "cases" | "review" | "documents" | "sla";

interface DashboardKpiCardsProps {
  cases: CaseListItem[];
  activeStage: string;
  onSelectStage: (stage: string) => void;
}

interface UnderwritingQueueProps {
  cases: CaseListItem[];
  demoCase: CaseSummary | null;
  demoCaseError: string | null;
  search: string;
  stage: string;
  slaLabel: string;
  onSearchChange: (value: string) => void;
  onStageChange: (value: string) => void;
  onSlaLabelChange: (value: string) => void;
  onClearFilters: () => void;
  onOpen: (caseId: string) => void;
  onCreateCase: () => void;
}

const REVIEW_STAGE = "human_review";
const AWAITING_DOCUMENTS_STAGE = "awaiting_documents";

interface QueueRow {
  case: CaseSummary;
  isDemo: boolean;
}

const iconPaths: Record<MetricIcon, string> = {
  cases: "M4 7.5h16M6.5 4.5h11l1 3H5.5l1-3ZM5 7.5v12h14v-12M8 11h8M8 14.5h5",
  review: "M8 5.5h8M8 9.5h8M8 13.5h5M6 3.5h12a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2Z",
  documents: "M7 3.5h7l4 4v13H7a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2ZM14 3.5v5h5M8 12h7M8 15.5h7",
  sla: "M12 3.5v2M12 18.5v2M3.5 12h2M18.5 12h2M5.99 5.99l1.42 1.42M16.59 16.59l1.42 1.42M18.01 5.99l-1.42 1.42M7.41 16.59l-1.42 1.42M12 8v4l2.5 1.5",
};

function MetricIconView({ icon }: { icon: MetricIcon }) {
  return (
    <svg viewBox="0 0 24 24" className="workload-metric-icon" aria-hidden="true">
      <path d={iconPaths[icon]} />
    </svg>
  );
}

export function DashboardKpiCards({
  cases,
  activeStage,
  onSelectStage,
}: DashboardKpiCardsProps) {
  const reviewStageCount = cases.filter(({ case: item }) => item.workflow_stage === REVIEW_STAGE).length;
  const awaitingDocumentsCount = cases.filter(
    ({ case: item }) => item.workflow_stage === AWAITING_DOCUMENTS_STAGE,
  ).length;
  const casesWithSlaLabelCount = cases.filter(
    ({ case: item }) => item.sla_label.trim() && item.sla_label.trim().toLocaleLowerCase() !== "not set",
  ).length;

  const metrics: Array<{
    title: string;
    value: number;
    detail: string;
    icon: MetricIcon;
    stage?: string;
  }> = [
    {
      title: "Cases in workspace",
      value: cases.length,
      detail: "All cases returned by the case-list API.",
      icon: "cases",
    },
    {
      title: "Human review stage",
      value: reviewStageCount,
      detail: "Cases at human_review; reviewer assignment is not provided.",
      icon: "review",
      stage: REVIEW_STAGE,
    },
    {
      title: "Awaiting documents",
      value: awaitingDocumentsCount,
      detail: "Cases at awaiting_documents; not inferred from document count.",
      icon: "documents",
      stage: AWAITING_DOCUMENTS_STAGE,
    },
    {
      title: "Cases with SLA label",
      value: casesWithSlaLabelCount,
      detail: "Cases with SLA text; this is not an overdue count.",
      icon: "sla",
    },
  ];

  return (
    <section className="workload-kpi-grid" aria-label="Underwriting workload summary">
      {metrics.map((metric) => {
        const targetStage = metric.stage;
        const content = (
          <>
            <span className="workload-kpi-topline">
              <span className="workload-kpi-title">{metric.title}</span>
              <MetricIconView icon={metric.icon} />
            </span>
            <strong>{metric.value}</strong>
            <span className="workload-kpi-detail">{metric.detail}</span>
          </>
        );
        return targetStage ? (
          <button
            type="button"
            className={`workload-kpi ${activeStage === targetStage ? "selected" : ""}`}
            key={metric.title}
            aria-pressed={activeStage === targetStage}
            onClick={() => onSelectStage(activeStage === targetStage ? "all" : targetStage)}
          >
            {content}
          </button>
        ) : (
          <article className="workload-kpi" key={metric.title}>
            {content}
          </article>
        );
      })}
    </section>
  );
}

export function UnderwritingQueue({
  cases,
  demoCase,
  demoCaseError,
  search,
  stage,
  slaLabel,
  onSearchChange,
  onStageChange,
  onSlaLabelChange,
  onClearFilters,
  onOpen,
  onCreateCase,
}: UnderwritingQueueProps) {
  const queueCases = useMemo<QueueRow[]>(
    () => [
      ...cases.map(({ case: item }) => ({ case: item, isDemo: false })),
      ...(demoCase ? [{ case: demoCase, isDemo: true }] : []),
    ],
    [cases, demoCase],
  );
  const stages = [...new Set(queueCases.map(({ case: item }) => item.workflow_stage))].sort();
  const slaLabels = [...new Set(queueCases.map(({ case: item }) => item.sla_label).filter(Boolean))].sort();
  const hasFilters = Boolean(search.trim() || stage !== "all" || slaLabel !== "all");

  const visibleCases = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase();
    const filtered = queueCases.filter(({ case: item }) => {
      const matchesSearch = !needle || [
        item.applicant_display_name,
        item.external_case_id,
        item.proposal_number,
      ].some((value) => value.toLocaleLowerCase().includes(needle));
      const matchesStage = stage === "all" || item.workflow_stage === stage;
      const matchesSla = slaLabel === "all" || item.sla_label === slaLabel;
      return matchesSearch && matchesStage && matchesSla;
    });

    return filtered
      .map((item, index) => ({ item, index, priority: stagePriority(item.case.workflow_stage) }))
      .sort((left, right) => left.priority - right.priority || left.index - right.index)
      .map(({ item }) => item);
  }, [queueCases, search, slaLabel, stage]);

  return (
    <section className="underwriting-queue" aria-labelledby="underwriting-queue-title">
      <div className="underwriting-queue-heading">
        <div>
          <h2 id="underwriting-queue-title">Underwriting Queue</h2>
          <p>
            Cases returned by the API. Individual underwriter assignments are not included.
            {demoCase ? " The demo row is excluded from workload totals." : ""}
          </p>
        </div>
        <span className="queue-result-count">
          Showing <strong>{visibleCases.length}</strong> of <strong>{queueCases.length}</strong> cases
        </span>
      </div>

      {demoCaseError ? (
        <p className="queue-demo-message" role="status">Demo case unavailable: {demoCaseError}</p>
      ) : null}

      <div className="queue-filter-bar" aria-label="Filter underwriting cases">
        <label className="queue-search">
          <span className="visually-hidden">Search applicant, case ID, or proposal number</span>
          <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.8" cy="10.8" r="6.8" /><path d="m16 16 4.5 4.5" /></svg>
          <input
            aria-label="Search applicant, case ID, or proposal number"
            placeholder="Search applicant, case ID, or proposal"
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
          />
        </label>
        <label className="queue-filter-select">
          <span>Stage</span>
          <select aria-label="Filter by stage" value={stage} onChange={(event) => onStageChange(event.target.value)}>
            <option value="all">All stages</option>
            {stages.map((value) => <option key={value} value={value}>{formatStage(value)}</option>)}
          </select>
        </label>
        <label className="queue-filter-select">
          <span>SLA label</span>
          <select aria-label="Filter by SLA label" value={slaLabel} onChange={(event) => onSlaLabelChange(event.target.value)}>
            <option value="all">All SLA labels</option>
            {slaLabels.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        {hasFilters ? (
          <button type="button" className="clear-filters-button" onClick={onClearFilters}>
            Clear filters
          </button>
        ) : null}
      </div>

      <p className="queue-data-limitation">
        AI assessment status, specific next actions, and structured SLA priority are not included in the case-list API.
        The table labels those fields unavailable and displays the SLA label exactly as supplied.
      </p>

      {queueCases.length === 0 ? (
        <div className="queue-empty-state">
          <span className="queue-empty-icon" aria-hidden="true">—</span>
          <h3>No cases in this workspace yet</h3>
          <p>Create a case to start a source-linked underwriting review.</p>
          <button type="button" className="primary-button" onClick={onCreateCase}>Create a case</button>
        </div>
      ) : visibleCases.length === 0 ? (
        <div className="queue-empty-state" role="status">
          <h3>No cases match these filters</h3>
          <p>Try changing your search or clearing the selected filters.</p>
          <button type="button" className="secondary-button" onClick={onClearFilters}>Clear filters</button>
        </div>
      ) : (
        <div className="queue-table-scroll">
          <table className="underwriting-queue-table">
            <thead>
              <tr>
                <th scope="col">Applicant Name</th>
                <th scope="col">Case ID</th>
                <th scope="col">Proposal Number</th>
                <th scope="col">Product</th>
                <th scope="col">Current Stage</th>
                <th scope="col">AI Assessment Status</th>
                <th scope="col">Next Action</th>
                <th scope="col">SLA / Priority</th>
                <th scope="col">Action</th>
              </tr>
            </thead>
            <tbody>
              {visibleCases.map(({ case: item, isDemo }) => (
                <tr key={item.id} className={isDemo ? "demo-queue-row" : undefined}>
                  <td data-label="Applicant Name">
                    <strong className="applicant-name">{item.applicant_display_name}</strong>
                    {isDemo ? <span className="queue-demo-badge">Demo · simulated</span> : null}
                  </td>
                  <td data-label="Case ID"><span className="case-id-cell">{item.external_case_id}</span></td>
                  <td data-label="Proposal Number">{item.proposal_number}</td>
                  <td data-label="Product">{item.product_name}</td>
                  <td data-label="Current Stage">
                    <span className={`stage-indicator ${stageTone(item.workflow_stage)}`}>
                      <span aria-hidden="true" />
                      {formatStage(item.workflow_stage)}
                    </span>
                  </td>
                  <td data-label="AI Assessment Status"><span className="unavailable-cell">Not provided</span></td>
                  <td data-label="Next Action"><span className="unavailable-cell">Not provided</span></td>
                  <td data-label="SLA / Priority">
                    <span className="sla-label-cell">
                      {item.sla_label && item.sla_label.toLocaleLowerCase() !== "not set"
                        ? item.sla_label
                        : "Not provided"}
                    </span>
                  </td>
                  <td data-label="Action">
                    <button
                      type="button"
                      className="open-case-button"
                      aria-label={`${isDemo ? "Open demo case" : "Open case"} ${item.external_case_id}`}
                      onClick={() => onOpen(item.external_case_id)}
                    >
                      {isDemo ? "Open demo" : "Open case"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="queue-priority-note">
        Order uses explicit workflow stage only: human review, awaiting documents, then other stages.
        No overdue or approaching-SLA priority is inferred.
      </p>
    </section>
  );
}

function stagePriority(stage: string): number {
  if (stage === REVIEW_STAGE) return 0;
  if (stage === AWAITING_DOCUMENTS_STAGE) return 1;
  return 2;
}

function stageTone(stage: string): string {
  if (stage === REVIEW_STAGE) return "attention";
  if (stage === AWAITING_DOCUMENTS_STAGE) return "waiting";
  if (stage === "completed") return "complete";
  return "neutral";
}

function formatStage(stage: string): string {
  return stage.replaceAll("_", " ");
}
