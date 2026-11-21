import { useEffect, useId, useMemo, useRef, useState } from "react";
import { fmtNumber, fmtTime } from "../format";

export interface Point {
  t: Date;
  v: number;
}

interface Props {
  title: string;
  unit: string;
  points: Point[];
  digits?: number;
  height?: number;
}

const MARGIN = { top: 8, right: 12, bottom: 22, left: 44 };

function niceTicks(min: number, max: number, count = 3): number[] {
  if (min === max) return [min];
  const raw = (max - min) / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) ?? raw;
  const ticks = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) ticks.push(v);
  return ticks;
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(360);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(200, entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

/**
 * Single-series line chart: 2px line, hairline grid, crosshair + tooltip on
 * hover, arrow-key navigation when focused. The title names the series, so
 * there is no legend; the latest value is labelled directly.
 */
export function LineChart({ title, unit, points, digits = 1, height = 150 }: Props) {
  const [wrapRef, width] = useWidth<HTMLDivElement>();
  const [active, setActive] = useState<number | null>(null);
  const titleId = useId();

  const geometry = useMemo(() => {
    if (points.length === 0) return null;
    const values = points.map((p) => p.v);
    let min = Math.min(...values);
    let max = Math.max(...values);
    const pad = (max - min) * 0.1 || Math.abs(max) * 0.05 || 1;
    min -= pad;
    max += pad;
    const t0 = points[0].t.getTime();
    const t1 = points[points.length - 1].t.getTime() || t0 + 1;
    const innerW = width - MARGIN.left - MARGIN.right;
    const innerH = height - MARGIN.top - MARGIN.bottom;
    const x = (t: Date) => MARGIN.left + (t1 === t0 ? innerW / 2 : ((t.getTime() - t0) / (t1 - t0)) * innerW);
    const y = (v: number) => MARGIN.top + (1 - (v - min) / (max - min)) * innerH;
    const path = points.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join("");
    return { x, y, path, ticks: niceTicks(min, max), innerW, innerH };
  }, [points, width, height]);

  if (!geometry) {
    return (
      <div className="card">
        <h3>{title}</h3>
        <p className="muted">No readings yet.</p>
      </div>
    );
  }

  const latest = points[points.length - 1];
  const shown = active === null ? null : points[active];

  const nearestIndex = (clientX: number, rect: DOMRect) => {
    const px = clientX - rect.left;
    let best = 0;
    let bestDist = Infinity;
    points.forEach((p, i) => {
      const d = Math.abs(geometry.x(p.t) - px);
      if (d < bestDist) {
        bestDist = d;
        best = i;
      }
    });
    return best;
  };

  const onKey = (event: React.KeyboardEvent) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const step = event.key === "ArrowLeft" ? -1 : 1;
    setActive((i) => Math.min(points.length - 1, Math.max(0, (i ?? points.length - 1) + step)));
  };

  const xTicks = [points[0], points[Math.floor(points.length / 2)], latest];

  return (
    <div className="card">
      <div className="spread">
        <h3 id={titleId}>{title}</h3>
        <span className="secondary small num">
          latest <strong>{fmtNumber(latest.v, digits)}</strong> {unit}
        </span>
      </div>
      <div className="chart" ref={wrapRef}>
        <svg
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-labelledby={titleId}
          tabIndex={0}
          onKeyDown={onKey}
          onBlur={() => setActive(null)}
          onPointerMove={(e) => setActive(nearestIndex(e.clientX, e.currentTarget.getBoundingClientRect()))}
          onPointerLeave={() => setActive(null)}
        >
          {geometry.ticks.map((tick) => (
            <g key={tick}>
              <line
                x1={MARGIN.left}
                x2={width - MARGIN.right}
                y1={geometry.y(tick)}
                y2={geometry.y(tick)}
                stroke="var(--grid)"
                strokeWidth={1}
              />
              <text
                x={MARGIN.left - 6}
                y={geometry.y(tick)}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize={11}
                fill="var(--ink-muted)"
                className="num"
              >
                {fmtNumber(tick, Math.abs(tick) >= 100 ? 0 : digits)}
              </text>
            </g>
          ))}
          <line
            x1={MARGIN.left}
            x2={width - MARGIN.right}
            y1={height - MARGIN.bottom}
            y2={height - MARGIN.bottom}
            stroke="var(--axis)"
          />
          {xTicks.map((p, i) => (
            <text
              key={i}
              x={geometry.x(p.t)}
              y={height - 6}
              textAnchor={i === 0 ? "start" : i === 2 ? "end" : "middle"}
              fontSize={11}
              fill="var(--ink-muted)"
            >
              {fmtTime(p.t)}
            </text>
          ))}
          <path d={geometry.path} fill="none" stroke="var(--series-1)" strokeWidth={2} strokeLinejoin="round" />
          <circle
            cx={geometry.x(latest.t)}
            cy={geometry.y(latest.v)}
            r={4}
            fill="var(--series-1)"
            stroke="var(--surface)"
            strokeWidth={2}
          />
          {shown && (
            <g>
              <line
                x1={geometry.x(shown.t)}
                x2={geometry.x(shown.t)}
                y1={MARGIN.top}
                y2={height - MARGIN.bottom}
                stroke="var(--ink-muted)"
                strokeWidth={1}
              />
              <circle
                cx={geometry.x(shown.t)}
                cy={geometry.y(shown.v)}
                r={4}
                fill="var(--series-1)"
                stroke="var(--surface)"
                strokeWidth={2}
              />
            </g>
          )}
        </svg>
        {shown && (
          <div className="tooltip" style={{ left: geometry.x(shown.t), top: geometry.y(shown.v) }} role="status">
            <strong>
              {fmtNumber(shown.v, digits)} {unit}
            </strong>{" "}
            <span className="muted">{fmtTime(shown.t)} UTC</span>
          </div>
        )}
      </div>
    </div>
  );
}
