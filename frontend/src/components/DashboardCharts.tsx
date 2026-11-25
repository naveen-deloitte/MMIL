import type { CaseListItem } from "../types";

const DAY_MS = 24 * 60 * 60 * 1000;
const IDLE_DAYS = 7;

export type DashboardFilter = "review" | "awaiting_documents" | "idle";

export function matchesDashboardFilter(item: CaseListItem, filter: string, now = Date.now()): boolean {
  if (filter === "review") return item.case.workflow_stage === "human_review";
  if (filter === "awaiting_documents") return item.document_count === 0;
  if (filter === "idle") return now - new Date(item.last_activity_at).getTime() > IDLE_DAYS * DAY_MS;
  return true;
}

interface Tile {
  id: DashboardFilter;
  label: string;
  hint: string;
  count: number;
  tone: "warning" | "danger" | "neutral";
}

/** One row of status tiles. Each tile is a filter, so users click what they see instead of recalling it. */
export function DashboardCharts({
  cases,
  refreshedAt,
  activeFilter,
  onFilter,
}: {
  cases: CaseListItem[];
  refreshedAt: Date | null;
  activeFilter: string;
  onFilter: (filter: string) => void;
}) {
  const total = cases.length;
  const now = Date.now();
  const count = (filter: DashboardFilter) => cases.filter((item) => matchesDashboardFilter(item, filter, now)).length;
  const tiles: Tile[] = [
    { id: "review", label: "Need review", hint: "Fields flagged for a person to check", count: count("review"), tone: "warning" },
    { id: "awaiting_documents", label: "Awaiting documents", hint: "No document uploaded yet", count: count("awaiting_documents"), tone: "danger" },
    { id: "idle", label: `No activity in ${IDLE_DAYS}+ days`, hint: "May need a follow-up", count: count("idle"), tone: "neutral" },
  ];

  return (
    <section className="dashboard-status" aria-labelledby="dashboard-status-title">
      <div className="dashboard-status-heading">
        <h2 id="dashboard-status-title">{total} open case{total === 1 ? "" : "s"}</h2>
        {refreshedAt ? <small>Updated {refreshedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</small> : null}
      </div>
      <div className="status-tiles">
        {tiles.map((tile) => {
          const active = activeFilter === tile.id;
          const share = total ? Math.round((tile.count / total) * 100) : 0;
          const clear = tile.count === 0;
          return (
            <button
              type="button"
              key={tile.id}
              className={`status-tile ${clear ? "clear" : tile.tone} ${active ? "active" : ""}`}
              aria-pressed={active}
              onClick={() => onFilter(active ? "all" : tile.id)}
            >
              <span className="status-tile-label">{tile.label}</span>
              <strong>{tile.count}</strong>
              <span className="status-tile-bar" aria-hidden="true"><span style={{ width: `${share}%` }} /></span>
              <small>{clear ? "All clear" : `${share}% of open cases · ${tile.hint}`}</small>
            </button>
          );
        })}
      </div>
    </section>
  );
}
