import { useState } from "react";
import type { CreatedRecommendation, MachineDetail, MachineStatus, Reading, RecommendationSummary } from "../api";
import { LineChart, type Point } from "../components/LineChart";
import { RecommendationPanel } from "../components/RecommendationPanel";
import { AlarmBadge, RiskBadge } from "../components/StatusBadge";
import { featureLabel, fmtDateTime, fmtNumber, fmtTime, humanize, powerKw, tempRise } from "../format";
import { usePolling, useSession } from "../session";

const SERIES: { title: string; unit: string; digits: number; value: (r: Reading) => number }[] = [
  { title: "Temperature rise over ambient", unit: "K", digits: 1, value: tempRise },
  { title: "Process temperature", unit: "K", digits: 1, value: (r) => r.process_temperature_k },
  { title: "Torque", unit: "Nm", digits: 1, value: (r) => r.torque_nm },
  { title: "Spindle speed", unit: "rpm", digits: 0, value: (r) => r.rotational_speed_rpm },
  { title: "Cutting power", unit: "kW", digits: 2, value: powerKw },
  { title: "Tool wear", unit: "min", digits: 0, value: (r) => r.tool_wear_min },
];

interface Data {
  machine: MachineDetail;
  status: MachineStatus;
  readings: Reading[];
  recent: RecommendationSummary[];
}

export function MachineView({ machineId }: { machineId: string }) {
  const { client, can } = useSession();
  const [showTable, setShowTable] = useState(false);
  const [mode, setMode] = useState<"full" | "sensor_only">("full");
  const [busy, setBusy] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [created, setCreated] = useState<CreatedRecommendation | null>(null);

  const { data, error, reload } = usePolling<Data>(async () => {
    const [machine, status, telemetry, recent] = await Promise.all([
      client.machine(machineId),
      client.status(machineId),
      client.telemetry(machineId, 240),
      client.recommendations(machineId, 5),
    ]);
    return { machine, status, readings: telemetry.readings, recent };
  }, `machine:${machineId}`);

  const requestRecommendation = async () => {
    setBusy(true);
    setRequestError(null);
    try {
      setCreated(await client.recommend(machineId, mode));
      reload();
    } catch (err) {
      setRequestError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (error && !data)
    return (
      <p className="error" role="alert">
        {error}
      </p>
    );
  if (!data) return <p className="muted">Loading {machineId}…</p>;

  const { machine, status, readings, recent } = data;
  const anomaly = status.anomaly;

  return (
    <>
      <a href="#/">← All machines</a>
      <div className="spread">
        <div>
          <h1>{machine.name}</h1>
          <p className="secondary">
            <span className="mono">{machine.machine_id}</span> · {machine.model} · {machine.location}
          </p>
        </div>
        <AlarmBadge alarm={anomaly ? anomaly.alarm : null} />
      </div>

      {anomaly?.alarm && (
        <section className="card alert" aria-labelledby="alarm-heading">
          <h2 id="alarm-heading">Anomaly alarm</h2>
          <p className="secondary">
            Above the alarm threshold for {anomaly.consecutive_exceedances} consecutive readings. Signals furthest
            outside their normal range:
          </p>
          <ul>
            {anomaly.top_features.map((f) => (
              <li key={f.feature}>
                <strong>{featureLabel(f.feature)}</strong>: {fmtNumber(f.exceedance_band_widths)} band widths{" "}
                {f.direction} normal
              </li>
            ))}
          </ul>
        </section>
      )}

      {can("request_recommendation") && (
        <section className="card" aria-labelledby="ask-heading">
          <div className="spread">
            <div>
              <h2 id="ask-heading">Ask the agent</h2>
              <p className="secondary small">
                Gathers evidence, proposes actions with citations, and opens approval requests. Nothing is sent to
                the machine.
              </p>
            </div>
            <div className="row">
              <label htmlFor="mode" className="small secondary">
                Context
              </label>
              <select id="mode" value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
                <option value="full">Full (history, manuals, models)</option>
                <option value="sensor_only">Sensor readings only</option>
              </select>
              <button className="primary" onClick={requestRecommendation} disabled={busy}>
                {busy ? "Working…" : "Get recommendation"}
              </button>
            </div>
          </div>
          {requestError && (
            <p className="error" role="alert">
              {requestError}
            </p>
          )}
          {created && (
            <div style={{ marginTop: 12 }}>
              <RecommendationPanel
                result={created}
                approvals={created.approvals}
                recommendationId={created.recommendation_id}
              />
            </div>
          )}
        </section>
      )}

      <div className="spread">
        <h2>Telemetry, last {readings.length} readings</h2>
        <button onClick={() => setShowTable((s) => !s)} aria-pressed={showTable}>
          {showTable ? "Show charts" : "Show as table"}
        </button>
      </div>
      {showTable ? (
        <div className="card table-wrap">
          <table>
            <caption className="muted small" style={{ textAlign: "left" }}>
              Latest 30 readings, newest first (UTC)
            </caption>
            <thead>
              <tr>
                <th>Time</th>
                {SERIES.map((s) => (
                  <th key={s.title} className="num">
                    {s.title} ({s.unit})
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {readings
                .slice(-30)
                .reverse()
                .map((r) => (
                  <tr key={r.timestamp}>
                    <td className="num">{fmtTime(r.timestamp)}</td>
                    {SERIES.map((s) => (
                      <td key={s.title} className="num">
                        {fmtNumber(s.value(r), s.digits)}
                      </td>
                    ))}
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="grid charts">
          {SERIES.map((s) => {
            const points: Point[] = readings.map((r) => ({ t: new Date(r.timestamp), v: s.value(r) }));
            return <LineChart key={s.title} title={s.title} unit={s.unit} digits={s.digits} points={points} />;
          })}
        </div>
      )}

      <div className="grid">
        <section className="card" aria-labelledby="recent-heading">
          <h2 id="recent-heading">Recent recommendations</h2>
          {recent.length === 0 ? (
            <p className="muted">None yet.</p>
          ) : (
            <ul className="plain" style={{ marginTop: 8 }}>
              {recent.map((r) => (
                <li key={r.id}>
                  <div className="row">
                    <RiskBadge level={r.risk_level} />
                    <a href={`#/recommendations/${r.id}`}>{fmtDateTime(r.created_utc)}</a>
                    <span className="muted small">
                      {r.engine} · {humanize(r.mode)} · by {r.requested_by}
                    </span>
                  </div>
                  <p className="secondary small" style={{ margin: "4px 0 0" }}>
                    {r.summary}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="card" aria-labelledby="history-heading">
          <h2 id="history-heading">Maintenance history</h2>
          <p className="muted small">Synthetic records for the simulated cell.</p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Kind</th>
                  <th>Work</th>
                </tr>
              </thead>
              <tbody>
                {machine.maintenance_history.map((m) => (
                  <tr key={m.record_id}>
                    <td className="num">{m.date}</td>
                    <td>{m.kind}</td>
                    <td>
                      <strong>{m.component}</strong>: {m.description}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </>
  );
}
