import { useState } from "react";
import type { Approval, ApprovalStatus } from "../api";
import { ApprovalBadge, UrgencyBadge } from "../components/StatusBadge";
import { fmtDateTime, fmtRelative, humanize } from "../format";
import { usePolling, useSession } from "../session";

const TABS: ApprovalStatus[] = ["pending", "approved", "completed", "rejected", "expired"];

function ApprovalCard({ approval, onChanged }: { approval: Approval; onChanged: () => void }) {
  const { client, me, can } = useSession();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ownRequest = approval.requested_by === me.user_id;
  const canDecide = approval.status === "pending" && can("decide_approval");
  const canComplete = approval.status === "approved" && can("complete_action");
  const noteId = `note-${approval.id}`;

  const act = async (verb: "approve" | "reject" | "complete") => {
    setBusy(true);
    setError(null);
    try {
      await client.decide(approval.id, verb, note.trim() || undefined);
      setNote("");
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="card">
      <div className="spread">
        <div className="row">
          <strong>{humanize(approval.action_type)}</strong>
          <span className="mono muted">{approval.machine_id}</span>
          <UrgencyBadge urgency={approval.urgency} />
        </div>
        <ApprovalBadge status={approval.status} />
      </div>
      <p style={{ margin: "8px 0" }}>{approval.description}</p>
      <p className="muted small" style={{ margin: 0 }}>
        Requested by {approval.requested_by} · {fmtDateTime(approval.created_utc)}
        {approval.status === "pending" && ` · expires ${fmtRelative(approval.expires_utc)}`} ·{" "}
        <a href={`#/recommendations/${approval.recommendation_id}`}>evidence and reasoning</a>
      </p>
      {approval.decided_by && (
        <p className="small secondary" style={{ margin: "4px 0 0" }}>
          {humanize(approval.status === "completed" ? "approved" : approval.status)} by {approval.decided_by}
          {approval.decision_note && `: "${approval.decision_note}"`}
        </p>
      )}
      {approval.completed_by && (
        <p className="small secondary" style={{ margin: "4px 0 0" }}>
          Completed by {approval.completed_by}
          {approval.completion_note && `: "${approval.completion_note}"`}
        </p>
      )}

      {(canDecide || canComplete) && (
        <div style={{ marginTop: 10, display: "grid", gap: 8 }}>
          {canDecide && ownRequest ? (
            <p className="small secondary" role="note">
              You requested this recommendation, so another maintenance lead must decide (four-eyes rule).
            </p>
          ) : (
            <>
              <label htmlFor={noteId} className="small secondary">
                {canDecide
                  ? approval.action_type === "request_stop"
                    ? "Note (required for both approving and rejecting a stop request)"
                    : "Note (required when rejecting)"
                  : "Completion note (what was found and done)"}
              </label>
              <textarea id={noteId} rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
              <div className="row">
                {canDecide && (
                  <>
                    <button className="primary" disabled={busy} onClick={() => act("approve")}>
                      Approve
                    </button>
                    <button className="danger" disabled={busy} onClick={() => act("reject")}>
                      Reject
                    </button>
                  </>
                )}
                {canComplete && (
                  <button className="primary" disabled={busy} onClick={() => act("complete")}>
                    Mark completed
                  </button>
                )}
              </div>
            </>
          )}
          {error && (
            <p className="error small" role="alert">
              {error}
            </p>
          )}
        </div>
      )}
    </li>
  );
}

export function ApprovalsView() {
  const { client, can } = useSession();
  const [tab, setTab] = useState<ApprovalStatus>("pending");
  const { data, error, reload } = usePolling(() => client.approvals(tab), `approvals:${tab}`);

  return (
    <>
      <div>
        <h1>Approvals</h1>
        <p className="secondary">
          {can("decide_approval")
            ? "Review each proposed action and its evidence before approving."
            : "Only maintenance leads can approve or reject. You can follow progress here."}
        </p>
      </div>
      <div className="tabs" role="group" aria-label="Filter by status">
        {TABS.map((t) => (
          <button key={t} aria-pressed={tab === t} onClick={() => setTab(t)}>
            {humanize(t)}
          </button>
        ))}
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {data && data.length === 0 && <p className="muted">Nothing {humanize(tab)}.</p>}
      <ul className="plain">
        {data?.map((a) => (
          <ApprovalCard key={a.id} approval={a} onChanged={reload} />
        ))}
      </ul>
    </>
  );
}
