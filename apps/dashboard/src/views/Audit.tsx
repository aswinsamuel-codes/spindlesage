import type { AuditEvent, ChainCheck } from "../api";
import { Badge } from "../components/StatusBadge";
import { fmtDateTime } from "../format";
import { usePolling, useSession } from "../session";

function summarize(details: Record<string, unknown>): string {
  return Object.entries(details)
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(" · ");
}

export function AuditView() {
  const { client } = useSession();
  const { data, error } = usePolling<{ events: AuditEvent[]; chain: ChainCheck }>(async () => {
    const [events, chain] = await Promise.all([client.audit(500), client.verifyAudit()]);
    return { events, chain };
  }, "audit");

  return (
    <>
      <div className="spread">
        <div>
          <h1>Audit trail</h1>
          <p className="secondary">
            Append-only and hash-chained: each record includes the hash of the one before it.
          </p>
        </div>
        {data &&
          (data.chain.ok ? (
            <Badge tone="good" label={`Chain intact · ${data.chain.records} records`} />
          ) : (
            <Badge
              tone="critical"
              label={`Chain broken at record ${data.chain.first_broken_seq} (${data.chain.reason})`}
            />
          ))}
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {data && (
        <div className="card table-wrap">
          <table>
            <thead>
              <tr>
                <th className="num">#</th>
                <th>Time</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Details</th>
                <th>Hash</th>
              </tr>
            </thead>
            <tbody>
              {[...data.events].reverse().map((e) => (
                <tr key={e.seq}>
                  <td className="num">{e.seq}</td>
                  <td className="num" style={{ whiteSpace: "nowrap" }}>
                    {fmtDateTime(e.ts_utc)}
                  </td>
                  <td>
                    {e.actor} <span className="muted small">({e.actor_role})</span>
                  </td>
                  <td>
                    <span className="mono">{e.action}</span>
                    <br />
                    {e.subject_type === "recommendation" ? (
                      <a className="small mono" href={`#/recommendations/${e.subject_id}`}>
                        {e.subject_id.slice(0, 8)}
                      </a>
                    ) : (
                      <span className="small mono muted">{e.subject_id.slice(0, 8)}</span>
                    )}
                  </td>
                  <td className="small secondary">{summarize(e.details)}</td>
                  <td className="mono muted" title={e.hash}>
                    {e.hash.slice(0, 10)}…
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
