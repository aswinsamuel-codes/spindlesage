// Status is never shown by colour alone: every badge has an icon and a label.

type Tone = "good" | "warning" | "serious" | "critical" | "neutral";

const ICONS: Record<Tone, string> = {
  good: "✓",
  warning: "!",
  serious: "!",
  critical: "▲",
  neutral: "•",
};

export function Badge({ tone, label, title }: { tone: Tone; label: string; title?: string }) {
  const color = tone === "neutral" ? "var(--ink-muted)" : `var(--${tone})`;
  return (
    <span className="badge" title={title}>
      <span aria-hidden="true" style={{ color, fontSize: 11, lineHeight: 1 }}>
        {ICONS[tone]}
      </span>
      <span>{label}</span>
    </span>
  );
}

export function AlarmBadge({ alarm }: { alarm: boolean | null }) {
  if (alarm === null) return <Badge tone="neutral" label="No data" />;
  return alarm ? <Badge tone="critical" label="Anomaly alarm" /> : <Badge tone="good" label="Normal" />;
}

const RISK: Record<string, [Tone, string]> = {
  high: ["critical", "High risk"],
  medium: ["serious", "Medium risk"],
  low: ["good", "Low risk"],
  unknown: ["warning", "Risk unknown"],
};

export function RiskBadge({ level }: { level: string }) {
  const [tone, label] = RISK[level] ?? ["neutral", level];
  return <Badge tone={tone} label={label} />;
}

const APPROVAL: Record<string, [Tone, string]> = {
  pending: ["warning", "Pending approval"],
  approved: ["good", "Approved"],
  rejected: ["neutral", "Rejected"],
  expired: ["neutral", "Expired"],
  completed: ["good", "Completed"],
};

export function ApprovalBadge({ status }: { status: string }) {
  const [tone, label] = APPROVAL[status] ?? ["neutral", status];
  return <Badge tone={tone} label={label} />;
}

const URGENCY: Record<string, [Tone, string]> = {
  immediate: ["critical", "Immediate"],
  next_stop: ["serious", "Next stop"],
  routine: ["neutral", "Routine"],
};

export function UrgencyBadge({ urgency }: { urgency: string }) {
  const [tone, label] = URGENCY[urgency] ?? ["neutral", urgency];
  return <Badge tone={tone} label={label} />;
}
