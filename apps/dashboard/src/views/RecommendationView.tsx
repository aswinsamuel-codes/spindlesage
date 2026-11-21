import { RecommendationPanel } from "../components/RecommendationPanel";
import { fmtDateTime } from "../format";
import { usePolling, useSession } from "../session";

export function RecommendationView({ recommendationId }: { recommendationId: string }) {
  const { client } = useSession();
  const { data, error } = usePolling(() => client.recommendation(recommendationId), `rec:${recommendationId}`, 0);

  if (error)
    return (
      <p className="error" role="alert">
        {error}
      </p>
    );
  if (!data) return <p className="muted">Loading…</p>;

  return (
    <>
      <a href={`#/machines/${encodeURIComponent(data.machine_id)}`}>← {data.machine_id}</a>
      <div>
        <h1>Recommendation for {data.machine_id}</h1>
        <p className="secondary">
          Requested by {data.requested_by} · {fmtDateTime(data.created_utc)} ·{" "}
          <span className="mono">{data.id}</span>
        </p>
      </div>
      <section className="card">
        <RecommendationPanel result={data.payload} approvals={data.approvals} recommendationId={data.id} />
      </section>
      {data.approvals.length > 0 && <a href="#/approvals">Go to approvals →</a>}
    </>
  );
}
