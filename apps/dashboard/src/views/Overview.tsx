import type { Machine, MachineStatus } from "../api";
import { AlarmBadge } from "../components/StatusBadge";
import { featureLabel, fmtDateTime, fmtNumber, powerKw, tempRise } from "../format";
import { usePolling, useSession } from "../session";

interface Row {
  machine: Machine;
  status: MachineStatus;
}

export function Overview() {
  const { client } = useSession();
  const { data, error, loading } = usePolling<Row[]>(async () => {
    const machines = await client.machines();
    const statuses = await Promise.all(machines.map((m) => client.status(m.machine_id)));
    return machines.map((machine, i) => ({ machine, status: statuses[i] }));
  }, "overview");

  const alarms = data?.filter((r) => r.status.anomaly?.alarm).length ?? 0;
  const pending = data?.reduce((sum, r) => sum + r.status.pending_approvals, 0) ?? 0;

  return (
    <>
      <div className="spread">
        <div>
          <h1>Machines</h1>
          <p className="secondary">
            {data
              ? `${data.length} machines · ${alarms} with an active anomaly alarm · ${pending} actions awaiting approval`
              : "Loading the cell…"}
          </p>
        </div>
        {pending > 0 && <a href="#/approvals">Review pending approvals →</a>}
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {loading && !data && <p className="muted">Loading…</p>}
      <div className="grid">
        {data?.map(({ machine, status }) => {
          const reading = status.latest_reading;
          const anomaly = status.anomaly;
          return (
            <a
              key={machine.machine_id}
              href={`#/machines/${encodeURIComponent(machine.machine_id)}`}
              style={{ textDecoration: "none", color: "inherit" }}
            >
              <article className={`card${anomaly?.alarm ? " alert" : ""}`}>
                <div className="spread">
                  <div>
                    <h2>{machine.name}</h2>
                    <span className="muted small mono">{machine.machine_id}</span>
                  </div>
                  <AlarmBadge alarm={anomaly ? anomaly.alarm : null} />
                </div>
                {anomaly?.alarm && anomaly.top_features[0] && (
                  <p style={{ margin: "8px 0 0" }}>
                    <strong>{featureLabel(anomaly.top_features[0].feature)}</strong> is{" "}
                    {fmtNumber(anomaly.top_features[0].exceedance_band_widths)} band widths{" "}
                    {anomaly.top_features[0].direction} normal.
                  </p>
                )}
                {reading ? (
                  <dl className="kv num">
                    <dt>Temperature rise</dt>
                    <dd>{fmtNumber(tempRise(reading))} K</dd>
                    <dt>Torque</dt>
                    <dd>{fmtNumber(reading.torque_nm)} Nm</dd>
                    <dt>Spindle speed</dt>
                    <dd>{fmtNumber(reading.rotational_speed_rpm, 0)} rpm</dd>
                    <dt>Cutting power</dt>
                    <dd>{fmtNumber(powerKw(reading), 2)} kW</dd>
                    <dt>Tool wear</dt>
                    <dd>{fmtNumber(reading.tool_wear_min, 0)} min</dd>
                  </dl>
                ) : (
                  <p className="muted">No telemetry received yet.</p>
                )}
                <p className="muted small" style={{ margin: "8px 0 0" }}>
                  {machine.location}
                  {reading && ` · last reading ${fmtDateTime(reading.timestamp)}`}
                  {status.pending_approvals > 0 && ` · ${status.pending_approvals} pending approval(s)`}
                </p>
              </article>
            </a>
          );
        })}
      </div>
    </>
  );
}
