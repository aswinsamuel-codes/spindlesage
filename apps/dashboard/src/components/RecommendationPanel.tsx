import { useEffect, useState } from "react";
import type { AgentResult, Approval } from "../api";
import { humanize } from "../format";
import { ApprovalBadge, Badge, RiskBadge, UrgencyBadge } from "./StatusBadge";

function Citations({
  ids,
  selected,
  onSelect,
}: {
  ids: string[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <span className="row" style={{ display: "inline-flex", gap: 4 }}>
      {ids.map((id) => (
        <button
          key={id}
          type="button"
          className="chip"
          aria-pressed={selected === id}
          onClick={() => onSelect(id)}
          title="Show this evidence"
        >
          {id}
        </button>
      ))}
    </span>
  );
}

function renderContent(content: Record<string, unknown>): string {
  if (typeof content.text === "string") return content.text;
  return JSON.stringify(content, null, 2);
}

/** Shows one agent result: findings and actions with their cited evidence. */
export function RecommendationPanel({
  result,
  approvals,
  recommendationId,
}: {
  result: AgentResult;
  approvals: Approval[];
  recommendationId?: string;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [scrollRequest, setScrollRequest] = useState(0);
  const rec = result.recommendation;
  const approvalFor = (index: number) => approvals.find((a) => a.action_index === index);
  const evidenceDomId = (id: string) => `evidence-${recommendationId ?? "new"}-${id}`;

  const select = (id: string) => {
    setSelected(id);
    setScrollRequest((n) => n + 1);
  };

  // Scroll after React has rendered the opened evidence list.
  useEffect(() => {
    if (selected === null) return;
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    document
      .getElementById(evidenceDomId(selected))
      ?.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "nearest" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scrollRequest]);

  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div className="row">
        <RiskBadge level={rec.risk_level} />
        <span className="secondary small">
          engine <strong>{result.engine}</strong> · {humanize(result.evidence.mode)} context · data as of{" "}
          {result.evidence.as_of.slice(0, 16).replace("T", " ")} UTC
        </span>
        {recommendationId && (
          <a className="small" href={`#/recommendations/${recommendationId}`}>
            Permalink
          </a>
        )}
      </div>
      {result.fallback_reason && (
        <p className="small" role="note">
          <Badge tone="warning" label="Fell back to rules" /> {result.primary_engine} could not be used:{" "}
          {result.fallback_reason}
        </p>
      )}
      <p style={{ margin: 0, fontSize: 15 }}>{rec.summary}</p>

      {rec.findings.length > 0 && (
        <div>
          <h3>Findings</h3>
          <ul>
            {rec.findings.map((f, i) => (
              <li key={i}>
                {f.statement} <Citations ids={f.evidence_ids} selected={selected} onSelect={select} />
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <h3>Proposed actions</h3>
        <p className="muted small" style={{ margin: "2px 0 8px" }}>
          Proposals only. Operational actions need a maintenance lead's approval.
        </p>
        <ul className="plain">
          {rec.actions.map((a, i) => {
            const approval = approvalFor(i);
            return (
              <li key={i} className="card" style={{ padding: 12 }}>
                <div className="row">
                  <strong>{humanize(a.action_type)}</strong>
                  <UrgencyBadge urgency={a.urgency} />
                  {approval ? <ApprovalBadge status={approval.status} /> : <Badge tone="neutral" label="No approval needed" />}
                </div>
                <p style={{ margin: "6px 0" }}>{a.description}</p>
                <Citations ids={a.evidence_ids} selected={selected} onSelect={select} />
              </li>
            );
          })}
        </ul>
      </div>

      {rec.uncertainties.length > 0 && (
        <div>
          <h3>Uncertainties</h3>
          <ul className="secondary">
            {rec.uncertainties.map((u, i) => (
              <li key={i}>{u}</li>
            ))}
          </ul>
        </div>
      )}

      <p className="small secondary" style={{ margin: 0 }}>
        Evidence guard:{" "}
        {result.guard.passed ? (
          <Badge tone="good" label="Passed" />
        ) : (
          <Badge tone="critical" label="Failed" />
        )}{" "}
        {result.guard.claims} claims, {result.guard.uncited_claims} uncited, {result.guard.unknown_citations} unknown
        citations
      </p>

      <details open={selected !== null}>
        <summary>Evidence ({result.evidence.items.length} items)</summary>
        <ul className="plain" style={{ marginTop: 8 }}>
          {result.evidence.items.map((e) => (
            <li
              key={e.evidence_id}
              id={evidenceDomId(e.evidence_id)}
              className="card"
              style={{
                padding: 10,
                borderColor: selected === e.evidence_id ? "var(--accent)" : undefined,
              }}
            >
              <div className="row">
                <span className="chip" style={{ cursor: "default" }}>
                  {e.evidence_id}
                </span>
                <strong>{e.title}</strong>
                <span className="muted small">{e.kind}</span>
              </div>
              <p className="muted small" style={{ margin: "4px 0" }}>
                {e.source}
              </p>
              <pre className="mono" style={{ whiteSpace: "pre-wrap", margin: 0, maxHeight: 220, overflow: "auto" }}>
                {renderContent(e.content)}
              </pre>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
