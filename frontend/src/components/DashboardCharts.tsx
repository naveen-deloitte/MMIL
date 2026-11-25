import type { CaseListItem } from "../types";

interface Slice {
  label: string;
  value: number;
  color: string;
}

const STAGE_COLORS: Record<string, string> = {
  human_review: "#ad5f00",
  medical_review: "#0176d3",
  compliance_review: "#7b4fc9",
  completed: "#2e844a",
  sla_at_risk: "#c23934",
};
const FALLBACK_COLORS = ["#0176d3", "#2e844a", "#ad5f00", "#7b4fc9", "#c23934", "#0b8a8a", "#706e6b"];

const DAY_MS = 24 * 60 * 60 * 1000;

function humanize(value: string): string {
  const text = value.replaceAll("_", " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "Unspecified";
}

function percent(value: number, total: number): string {
  return total ? `${Math.round((value / total) * 100)}%` : "0%";
}

function stageSlices(cases: CaseListItem[]): Slice[] {
  const counts = new Map<string, number>();
  for (const { case: item } of cases) {
    const key = item.workflow_stage || "unspecified";
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([stage, value], index) => ({
      label: humanize(stage),
      value,
      color: STAGE_COLORS[stage] ?? FALLBACK_COLORS[index % FALLBACK_COLORS.length],
    }));
}

function Donut({ slices, total, centerLabel }: { slices: Slice[]; total: number; centerLabel: string }) {
  const radius = 42;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  const summary = slices.map((slice) => `${slice.label} ${slice.value}`).join(", ");
  return (
    <svg className="donut" viewBox="0 0 120 120" role="img" aria-label={`${centerLabel}: ${total}. ${summary}`}>
      <circle cx="60" cy="60" r={radius} fill="none" stroke="var(--gray-3)" strokeWidth="16" />
      {total > 0
        ? slices.map((slice) => {
            const length = (slice.value / total) * circumference;
            const circle = (
              <circle
                key={slice.label}
                cx="60"
                cy="60"
                r={radius}
                fill="none"
                stroke={slice.color}
                strokeWidth="16"
                strokeDasharray={`${length} ${circumference - length}`}
                strokeDashoffset={-offset}
                transform="rotate(-90 60 60)"
              />
            );
            offset += length;
            return circle;
          })
        : null}
      <text x="60" y="58" textAnchor="middle" className="donut-total">{total}</text>
      <text x="60" y="74" textAnchor="middle" className="donut-caption">{centerLabel}</text>
    </svg>
  );
}

function Legend({ slices, total }: { slices: Slice[]; total: number }) {
  return (
    <ul className="chart-legend">
      {slices.map((slice) => (
        <li key={slice.label}>
          <span className="legend-swatch" style={{ background: slice.color }} aria-hidden="true" />
          <span className="legend-label">{slice.label}</span>
          <strong>{slice.value}</strong>
          <small>{percent(slice.value, total)}</small>
        </li>
      ))}
    </ul>
  );
}

function BarList({ slices, total }: { slices: Slice[]; total: number }) {
  return (
    <ul className="bar-list">
      {slices.map((slice) => (
        <li key={slice.label}>
          <div className="bar-list-label">
            <span>{slice.label}</span>
            <strong>{slice.value} <small>{percent(slice.value, total)}</small></strong>
          </div>
          <div className="bar-track" aria-hidden="true">
            <span style={{ width: percent(slice.value, total), background: slice.color }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

export function DashboardCharts({ cases, refreshedAt }: { cases: CaseListItem[]; refreshedAt: Date | null }) {
  const total = cases.length;
  const stages = stageSlices(cases);
  const pendingReview = cases.filter(({ case: item }) => item.workflow_stage === "human_review").length;
  const totalDocuments = cases.reduce((sum, item) => sum + item.document_count, 0);
  const withDocuments = cases.filter((item) => item.document_count > 0).length;

  const now = Date.now();
  const age = (item: CaseListItem) => now - new Date(item.last_activity_at).getTime();
  const activity: Slice[] = [
    { label: "Last 24 hours", value: cases.filter((item) => age(item) <= DAY_MS).length, color: "var(--success)" },
    { label: "1–7 days", value: cases.filter((item) => age(item) > DAY_MS && age(item) <= 7 * DAY_MS).length, color: "var(--info)" },
    { label: "Over 7 days (idle)", value: cases.filter((item) => age(item) > 7 * DAY_MS).length, color: "var(--warning)" },
  ];
  const documents: Slice[] = [
    { label: "Documents received", value: withDocuments, color: "var(--success)" },
    { label: "Awaiting documents", value: total - withDocuments, color: "var(--brand)" },
  ];

  return (
    <section className="dashboard-charts" aria-label="Case status overview">
      <div className="system-status-bar" role="status">
        <span className={`status-dot ${pendingReview ? "warning" : "ok"}`} aria-hidden="true" />
        <strong>{pendingReview ? `${pendingReview} case${pendingReview === 1 ? "" : "s"} need${pendingReview === 1 ? "s" : ""} your review` : "No cases waiting for review"}</strong>
        <span>{total} open · {totalDocuments} document{totalDocuments === 1 ? "" : "s"} · {total - withDocuments} awaiting documents</span>
        {refreshedAt ? <small>Updated {refreshedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</small> : null}
      </div>

      <div className="chart-grid">
        <article className="chart-card">
          <header><h3>Cases by stage</h3><p>Where every open case sits right now</p></header>
          {total ? (
            <div className="donut-row">
              <Donut slices={stages} total={total} centerLabel="cases" />
              <Legend slices={stages} total={total} />
            </div>
          ) : <p className="chart-empty">No cases yet.</p>}
        </article>

        <article className="chart-card">
          <header><h3>Document coverage</h3><p>Cases with at least one uploaded document</p></header>
          {total ? (
            <div className="donut-row">
              <Donut slices={documents} total={total} centerLabel="cases" />
              <Legend slices={documents} total={total} />
            </div>
          ) : <p className="chart-empty">No cases yet.</p>}
        </article>

        <article className="chart-card">
          <header><h3>Recent activity</h3><p>Time since each case was last updated</p></header>
          {total ? <BarList slices={activity} total={total} /> : <p className="chart-empty">No cases yet.</p>}
        </article>
      </div>
    </section>
  );
}
