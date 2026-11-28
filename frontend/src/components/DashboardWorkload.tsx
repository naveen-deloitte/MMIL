import { useEffect, useMemo, useState } from "react";
import type { CaseListItem, CaseSummary } from "../types";

type CaseStatus =
  | "new_assigned"
  | "under_review"
  | "resolved"
  | "pending"
  | "awaiting_information"
  | "escalated";
type StatusFilter = "all" | CaseStatus;
type SortColumn =
  | "case_id"
  | "applicant"
  | "product"
  | "assigned"
  | "status"
  | "priority"
  | "sla"
  | "updated";
type OptionalCaseMetadata = CaseSummary & {
  assigned_at?: string | null;
  resolved_at?: string | null;
  priority?: string | null;
  sla_status?: string | null;
  final_decision?: string | null;
  decision_date?: string | null;
  underwriter_subject?: string | null;
  decision_rationale?: string | null;
};

interface DashboardWorkloadProps {
  cases: CaseListItem[];
  demoCase: CaseSummary | null;
  demoCaseError: string | null;
  onOpen: (caseId: string) => void;
  onCreateCase: () => void;
  /** Opens the case's original proposal document. Optional so existing callers keep working. */
  onViewProposal?: (caseId: string) => void;
}

interface QueueRow {
  case: OptionalCaseMetadata;
  lastActivityAt: string | null;
  isDemo: boolean;
}

const KPI_STATUSES: Array<{
  status: CaseStatus;
  title: string;
}> = [
  { status: "new_assigned", title: "New / Assigned" },
  { status: "under_review", title: "Under Review" },
  { status: "resolved", title: "Resolved" },
  { status: "pending", title: "Pending" },
  { status: "awaiting_information", title: "Awaiting Information" },
];

const TABS: Array<{ status: StatusFilter; label: string }> = [
  { status: "all", label: "All" },
  { status: "new_assigned", label: "New / Assigned" },
  { status: "under_review", label: "Under Review" },
  { status: "resolved", label: "Resolved" },
  { status: "awaiting_information", label: "Awaiting Information" },
];

const PRIORITIES = ["High", "Medium", "Low"];
const SLA_STATUSES = ["On Track", "Due Soon", "Overdue"];
const PAGE_SIZES = [10, 25, 50];

function normalize(value: string): string {
  return value.trim().toLocaleLowerCase().replaceAll("-", "_").replaceAll(" ", "_");
}

function statusForStage(stage: string): CaseStatus {
  const normalized = normalize(stage);
  if (["new", "assigned", "new_assigned", "newly_assigned"].includes(normalized)) return "new_assigned";
  if (["human_review", "under_review", "underwriting_review", "underwriting_variance_review"].includes(normalized)) {
    return "under_review";
  }
  if (["resolved", "completed"].includes(normalized)) return "resolved";
  if (["pending", "pending_action"].includes(normalized)) return "pending";
  if (["awaiting_documents", "awaiting_information", "waiting_for_information"].includes(normalized)) {
    return "awaiting_information";
  }
  if (normalized.includes("hilt") || normalized.includes("escalat")) return "escalated";
  return "pending";
}

function kpiStatusForStage(stage: string): CaseStatus {
  const status = statusForStage(stage);
  return status === "escalated" ? "pending" : status;
}

function labelForStatus(status: CaseStatus): string {
  return {
    new_assigned: "New / Assigned",
    under_review: "Under Review",
    resolved: "Resolved",
    pending: "Pending",
    awaiting_information: "Awaiting Information",
    escalated: "HILT / Escalated",
  }[status];
}

function formatStage(stage: string): string {
  return stage.replaceAll("_", " ").replaceAll("-", " ");
}

function dateValue(value: string | null | undefined): string {
  if (!value) return "Not provided";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Not provided"
    : date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function formatDecision(value: string | null | undefined): string {
  if (!value) return "Not provided";
  const formatted = formatStage(value);
  return formatted.charAt(0).toLocaleUpperCase() + formatted.slice(1);
}

function dateKey(value: string | null | undefined): string {
  if (!value) return "";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "" : parsed.toISOString().slice(0, 10);
}

function compareText(left: string, right: string): number {
  return left.localeCompare(right, undefined, { numeric: true, sensitivity: "base" });
}

function optionalMetadata(item: CaseSummary): OptionalCaseMetadata {
  return item;
}

export function DashboardWorkload({
  cases,
  demoCase,
  demoCaseError,
  onOpen,
  onCreateCase,
  onViewProposal,
}: DashboardWorkloadProps) {
  const queueCases = useMemo<QueueRow[]>(
    () => [
      ...cases.map(({ case: item, last_activity_at }) => ({
        case: optionalMetadata(item),
        lastActivityAt: last_activity_at,
        isDemo: false,
      })),
      ...(demoCase
        ? [{ case: optionalMetadata(demoCase), lastActivityAt: null, isDemo: true }]
        : []),
    ],
    [cases, demoCase],
  );
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [excludeDemoForStatus, setExcludeDemoForStatus] = useState(false);
  const [product, setProduct] = useState("all");
  const [assignedFrom, setAssignedFrom] = useState("");
  const [assignedTo, setAssignedTo] = useState("");
  const [resolvedFrom, setResolvedFrom] = useState("");
  const [resolvedTo, setResolvedTo] = useState("");
  const [priority, setPriority] = useState("all");
  const [slaStatus, setSlaStatus] = useState("all");
  const [decision, setDecision] = useState("all");
  const [slaLabel, setSlaLabel] = useState("all");
  const [sortColumn, setSortColumn] = useState<SortColumn>("updated");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(PAGE_SIZES[0]);

  const realCases = useMemo(() => queueCases.filter((row) => !row.isDemo), [queueCases]);
  const products = useMemo(
    () => [...new Set(queueCases.map(({ case: item }) => item.product_name).filter(Boolean))].sort(compareText),
    [queueCases],
  );
  const slaLabels = useMemo(
    () => [...new Set(queueCases.map(({ case: item }) => item.sla_label).filter((value) => value && value.toLocaleLowerCase() !== "not set"))].sort(compareText),
    [queueCases],
  );
  const decisions = useMemo(
    () => [...new Set(queueCases.map(({ case: item }) => item.final_decision?.trim()).filter((value): value is string => Boolean(value)))].sort(compareText),
    [queueCases],
  );
  const hasAssignedDates = queueCases.some(({ case: item }) => Boolean(item.assigned_at));
  const hasResolvedDates = queueCases.some(({ case: item }) => Boolean(item.resolved_at));
  const hasPriorities = queueCases.some(({ case: item }) => Boolean(item.priority));
  const hasSlaStatuses = queueCases.some(({ case: item }) => Boolean(item.sla_status));

  const statusCounts = useMemo(() => {
    const counts = new Map<CaseStatus, number>();
    realCases.forEach(({ case: item }) => {
      const current = kpiStatusForStage(item.workflow_stage);
      counts.set(current, (counts.get(current) ?? 0) + 1);
    });
    return counts;
  }, [realCases]);

  const filteredCases = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase();
    const filtered = queueCases.filter(({ case: item, lastActivityAt, isDemo }) => {
      const currentStatus = statusForStage(item.workflow_stage);
      if (excludeDemoForStatus && isDemo) return false;
      if (status !== "all" && (excludeDemoForStatus
        ? kpiStatusForStage(item.workflow_stage) !== status
        : currentStatus !== status)) return false;
      if (needle && ![
        item.external_case_id,
        item.applicant_display_name,
        item.proposal_number,
      ].some((value) => value.toLocaleLowerCase().includes(needle))) return false;
      if (product !== "all" && item.product_name !== product) return false;
      if (slaLabel !== "all" && item.sla_label !== slaLabel) return false;
      if (priority !== "all" && normalize(item.priority ?? "") !== normalize(priority)) return false;
      if (slaStatus !== "all" && normalize(item.sla_status ?? "") !== normalize(slaStatus)) return false;
      if (decision !== "all" && item.final_decision !== decision) return false;

      const assignedDate = dateKey(item.assigned_at);
      const resolvedDate = dateKey(item.resolved_at);
      const assignedBoundsSelected = Boolean(assignedFrom || assignedTo);
      const resolvedBoundsSelected = Boolean(resolvedFrom || resolvedTo);
      if (assignedBoundsSelected && (!assignedDate || (assignedFrom && assignedDate < assignedFrom) || (assignedTo && assignedDate > assignedTo))) return false;
      if (resolvedBoundsSelected && (!resolvedDate || (resolvedFrom && resolvedDate < resolvedFrom) || (resolvedTo && resolvedDate > resolvedTo))) return false;
      return true;
    });

    return [...filtered].sort((left, right) => {
      const a = left.case;
      const b = right.case;
      let comparison = 0;
      switch (sortColumn) {
        case "case_id": comparison = compareText(a.external_case_id, b.external_case_id); break;
        case "applicant": comparison = compareText(a.applicant_display_name, b.applicant_display_name); break;
        case "product": comparison = compareText(a.product_name, b.product_name); break;
        case "assigned": comparison = compareText(a.assigned_at ?? "", b.assigned_at ?? ""); break;
        case "status": comparison = compareText(labelForStatus(statusForStage(a.workflow_stage)), labelForStatus(statusForStage(b.workflow_stage))); break;
        case "priority": comparison = compareText(a.priority ?? "", b.priority ?? ""); break;
        case "sla": comparison = compareText(a.sla_label ?? "", b.sla_label ?? ""); break;
        case "updated": comparison = compareText(left.lastActivityAt ?? "", right.lastActivityAt ?? ""); break;
      }
      return comparison === 0 ? 0 : sortDirection === "asc" ? comparison : -comparison;
    });
  }, [
    assignedFrom, assignedTo, decision, excludeDemoForStatus, product, priority, queueCases,
    resolvedFrom, resolvedTo, search, slaLabel, slaStatus, sortColumn, sortDirection, status,
  ]);

  useEffect(() => {
    setPage(0);
  }, [assignedFrom, assignedTo, decision, product, priority, resolvedFrom, resolvedTo, search, slaLabel, slaStatus, status]);

  const activeFilters = [
    search.trim(),
    status !== "all" ? status : "",
    product !== "all" ? product : "",
    assignedFrom,
    assignedTo,
    resolvedFrom,
    resolvedTo,
    priority !== "all" ? priority : "",
    slaStatus !== "all" ? slaStatus : "",
    decision !== "all" ? decision : "",
    slaLabel !== "all" ? slaLabel : "",
  ].filter(Boolean).length;
  const pageCount = Math.max(1, Math.ceil(filteredCases.length / pageSize));
  const pageCases = filteredCases.slice(page * pageSize, (page + 1) * pageSize);
  const firstResult = filteredCases.length ? page * pageSize + 1 : 0;
  const lastResult = Math.min((page + 1) * pageSize, filteredCases.length);

  function selectStatus(next: StatusFilter, fromKpi = false) {
    const clearingSelection = status === next;
    setStatus(clearingSelection ? "all" : next);
    setExcludeDemoForStatus(fromKpi && !clearingSelection && next !== "all");
  }

  function clearFilters() {
    setSearch("");
    setStatus("all");
    setExcludeDemoForStatus(false);
    setProduct("all");
    setAssignedFrom("");
    setAssignedTo("");
    setResolvedFrom("");
    setResolvedTo("");
    setPriority("all");
    setSlaStatus("all");
    setDecision("all");
    setSlaLabel("all");
  }

  function sortBy(column: SortColumn) {
    if (sortColumn === column) {
      setSortDirection((direction) => direction === "asc" ? "desc" : "asc");
      return;
    }
    setSortColumn(column);
    setSortDirection("asc");
  }

  function sortButton(column: SortColumn, label: string) {
    const active = sortColumn === column;
    return (
      <button
        type="button"
        className="queue-sort-button"
        aria-label={`Sort by ${label}`}
        aria-sort={active ? sortDirection === "asc" ? "ascending" : "descending" : "none"}
        onClick={() => sortBy(column)}
      >
        {label}<span aria-hidden="true">{active ? sortDirection === "asc" ? " ↑" : " ↓" : " ↕"}</span>
      </button>
    );
  }

  return (
    <>
      <section className="workload-overview" aria-label="Underwriting workload summary">
        <div className="workload-total">
          <div className="workload-total-heading">
            <span className="workload-kpi-title">Total Cases</span>
            <strong>{realCases.length}</strong>
          </div>
          <p>Cases available in your authorized case list</p>
        </div>
        <div className="workload-breakdown" aria-label="Case status breakdown">
          {KPI_STATUSES.map((metric) => {
            const selected = status === metric.status;
            return (
              <button
                type="button"
                className={`workload-status-row ${selected ? "selected" : ""}`}
                key={metric.status}
                aria-pressed={selected}
                onClick={() => selectStatus(metric.status, true)}
              >
                <span className={`workload-status-dot ${metric.status}`} aria-hidden="true" />
                <span>{metric.title}</span>
                <strong>{statusCounts.get(metric.status) ?? 0}</strong>
              </button>
            );
          })}
        </div>
      </section>

      <section className="underwriting-queue" aria-labelledby="underwriting-queue-title">
        <div className="underwriting-queue-heading">
          <div>
            <h2 id="underwriting-queue-title">My Cases</h2>
            <p>Cases available in your authorized case list. Status is derived from the existing workflow stage.</p>
          </div>
          <span className="queue-result-count">
            Showing <strong>{firstResult}–{lastResult}</strong> of <strong>{filteredCases.length}</strong> filtered cases
            <span className="queue-total-count"> · {queueCases.length} total</span>
          </span>
        </div>

        {demoCaseError ? <p className="queue-demo-message" role="status">Demo case unavailable: {demoCaseError}</p> : null}

        <label className="queue-search queue-main-search">
          <span className="visually-hidden">Search applicant, case ID, or policy/application number</span>
          <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.8" cy="10.8" r="6.8" /><path d="m16 16 4.5 4.5" /></svg>
          <input
            aria-label="Search applicant, case ID, or policy/application number"
            placeholder="Search case ID, applicant, or policy/application number"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>

        <div className="queue-status-tabs" role="tablist" aria-label="Filter cases by status">
          {TABS.map((tab) => (
            <button
              type="button"
              role="tab"
              aria-selected={status === tab.status}
              className={status === tab.status ? "active" : ""}
              key={tab.status}
              onClick={() => selectStatus(tab.status)}
            >
              {tab.label}<span>{tab.status === "all" ? queueCases.length : statusCounts.get(tab.status) ?? 0}</span>
            </button>
          ))}
        </div>

        <div className="queue-filter-toolbar">
          <label className="queue-page-size">
            Rows per page
            <select aria-label="Rows per page" value={pageSize} onChange={(event) => setPageSize(Number(event.target.value))}>
              {PAGE_SIZES.map((size) => <option value={size} key={size}>{size}</option>)}
            </select>
          </label>
          {activeFilters > 0 ? (
            <button type="button" className="clear-filters-button" onClick={clearFilters}>Clear all filters</button>
          ) : null}
        </div>

        {queueCases.length === 0 ? (
          <div className="queue-empty-state">
            <span className="queue-empty-icon" aria-hidden="true">—</span>
            <h3>No cases in this workspace yet</h3>
            <p>Create a case to start a source-linked underwriting review.</p>
            <button type="button" className="primary-button" onClick={onCreateCase}>Create a case</button>
          </div>
        ) : filteredCases.length === 0 ? (
          <div className="queue-empty-state" role="status">
            <h3>No cases match these filters</h3>
            <p>Try changing your search or clearing the selected filters.</p>
            <button type="button" className="secondary-button" onClick={clearFilters}>Clear all filters</button>
          </div>
        ) : (
          <div className="queue-table-scroll">
            <table className="underwriting-queue-table">
              <thead>
                <tr>
                  <th scope="col">{sortButton("case_id", "Case ID")}</th>
                  <th scope="col">{sortButton("applicant", "Applicant Name")}</th>
                  <th scope="col">{sortButton("product", "Product Type")}</th>
                  <th scope="col">{sortButton("assigned", "Assigned Date")}</th>
                  <th scope="col">{sortButton("status", "Current Status")}</th>
                  <th scope="col">{sortButton("sla", "SLA / Due Date")}</th>
                  <th scope="col">Action</th>
                </tr>
              </thead>
              <tbody>
                {pageCases.map(({ case: item, isDemo }) => {
                  const currentStatus = statusForStage(item.workflow_stage);
                  const resolved = currentStatus === "resolved";
                  return (
                    <tr key={item.id} className={isDemo ? "demo-queue-row" : undefined}>
                      <td data-label="Case ID"><span className="case-id-cell">{item.external_case_id}</span>{isDemo ? <span className="queue-demo-badge">Demo · simulated</span> : null}</td>
                      <td data-label="Applicant Name"><strong className="applicant-name">{item.applicant_display_name}</strong></td>
                      <td data-label="Product Type">{item.product_name}</td>
                      <td data-label="Assigned Date">{dateValue(item.assigned_at)}</td>
                      <td data-label="Current Status">
                        <span className={`stage-indicator ${currentStatus === "resolved" ? "complete" : currentStatus === "awaiting_information" ? "waiting" : currentStatus === "under_review" || currentStatus === "pending" ? "attention" : "neutral"}`}>
                          <span aria-hidden="true" />{labelForStatus(currentStatus)}
                        </span>
                      </td>
                      <td data-label="SLA / Due Date"><span className="sla-label-cell">{item.sla_label && item.sla_label.toLocaleLowerCase() !== "not set" ? item.sla_label : "Not provided"}</span></td>
                      <td data-label="Action">
                        <div className="queue-action-buttons">
                          <button
                            type="button"
                            className="open-case-button"
                            aria-label={`${resolved ? "View resolved case" : currentStatus === "under_review" ? "Continue review" : "View case"} ${item.external_case_id}`}
                            onClick={() => onOpen(item.external_case_id)}
                          >
                            {resolved ? "View case" : currentStatus === "under_review" ? "Continue review" : "View case"}
                          </button>
                          {!isDemo && onViewProposal ? (
                            <button
                              type="button"
                              className="view-proposal-button"
                              aria-label={`View proposal ${item.external_case_id}`}
                              onClick={() => onViewProposal(item.external_case_id)}
                            >
                              <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                                <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
                                <path d="M14 3v5h5M9 13h6M9 17h6" />
                              </svg>
                              View Proposal
                            </button>
                          ) : null}
                        </div>
                        {resolved ? (
                          <details className="resolved-decision-details">
                            <summary>Decision details</summary>
                            <dl>
                              <dt>Final decision</dt><dd>{formatDecision(item.final_decision)}</dd>
                              <dt>Decision date</dt><dd>{dateValue(item.decision_date ?? item.resolved_at)}</dd>
                              <dt>Underwriter</dt><dd>{item.underwriter_subject ?? "Not provided"}</dd>
                              {item.decision_rationale ? <><dt>Rationale</dt><dd>{item.decision_rationale}</dd></> : null}
                            </dl>
                          </details>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {filteredCases.length > 0 ? (
          <nav className="queue-pagination" aria-label="Cases pagination">
            <span>Showing {firstResult}–{lastResult} of {filteredCases.length}</span>
            <button type="button" className="secondary-button" onClick={() => setPage((current) => Math.max(0, current - 1))} disabled={page === 0}>Previous</button>
            <span>Page {page + 1} of {pageCount}</span>
            <button type="button" className="secondary-button" onClick={() => setPage((current) => Math.min(pageCount - 1, current + 1))} disabled={page >= pageCount - 1}>Next</button>
          </nav>
        ) : null}
      </section>
    </>
  );
}
