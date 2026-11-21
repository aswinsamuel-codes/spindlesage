// Formatting helpers. Times are shown in UTC because simulated telemetry
// carries UTC timestamps and the cell may be in another time zone than the viewer.

const timeFmt = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
const dateTimeFmt = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "UTC",
});

export const fmtTime = (iso: string | Date) => timeFmt.format(new Date(iso));
export const fmtDateTime = (iso: string | Date) => `${dateTimeFmt.format(new Date(iso))} UTC`;

export function fmtNumber(value: number, digits = 1): string {
  return value.toLocaleString("en-GB", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtRelative(iso: string, now: Date = new Date()): string {
  const minutes = Math.round((new Date(iso).getTime() - now.getTime()) / 60000);
  const abs = Math.abs(minutes);
  const text = abs < 60 ? `${abs} min` : abs < 48 * 60 ? `${Math.round(abs / 60)} h` : `${Math.round(abs / 1440)} d`;
  return minutes >= 0 ? `in ${text}` : `${text} ago`;
}

export const humanize = (value: string) => value.replace(/_/g, " ");

/** Derived signals shown on the dashboard, matching the agent's definitions. */
export const tempRise = (r: { process_temperature_k: number; air_temperature_k: number }) =>
  r.process_temperature_k - r.air_temperature_k;
export const powerKw = (r: { torque_nm: number; rotational_speed_rpm: number }) =>
  (r.torque_nm * r.rotational_speed_rpm * 2 * Math.PI) / 60 / 1000;

const FEATURE_LABELS: Record<string, string> = {
  air_temperature_k: "Air temperature",
  process_temperature_k: "Process temperature",
  rotational_speed_rpm: "Spindle speed",
  torque_nm: "Torque",
  tool_wear_min: "Tool wear",
  temp_rise_k: "Temperature rise over ambient",
  mech_power_w: "Cutting power",
};

export function featureLabel(feature: string): string {
  if (feature.endsWith("_log_rolling_std")) {
    const sensor = feature.replace("_log_rolling_std", "");
    return `${FEATURE_LABELS[sensor] ?? humanize(sensor)} variability`;
  }
  return FEATURE_LABELS[feature] ?? humanize(feature);
}
