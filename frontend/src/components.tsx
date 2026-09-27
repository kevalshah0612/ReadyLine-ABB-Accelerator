import { useState, type FormEvent, type ReactNode } from "react";
import { X, AlertCircle, LoaderCircle } from "lucide-react";
import type { Reading } from "./types";

export const date = (value?: string | null) =>
  value
    ? new Date(value).toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
export const money = (value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
export function Badge({ value }: { value: string }) {
  return <span className={`badge ${value}`}>{value.replaceAll("_", " ")}</span>;
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="error" role="alert">
      <AlertCircle size={18} />
      <span>{message}</span>
    </div>
  );
}
export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}
export function Modal({
  title,
  close,
  children,
}: {
  title: string;
  close: () => void;
  children: ReactNode;
}) {
  return (
    <dialog
      open
      className="modal"
      ref={(element) => {
        if (element && !element.hasAttribute("data-ready")) {
          element.removeAttribute("open");
          element.showModal();
          element.setAttribute("data-ready", "1");
        }
      }}
      onCancel={close}
    >
      <div className="modal-heading">
        <h2>{title}</h2>
        <button
          className="icon-button"
          onClick={close}
          aria-label="Close dialog"
        >
          <X />
        </button>
      </div>
      {children}
    </dialog>
  );
}
/** Shared form owns pending/error state; a failed mutation never looks successful. */
export function Form({
  onSubmit,
  children,
  label = "Save",
  disabled = false,
}: {
  onSubmit: (data: FormData) => Promise<void>;
  children: ReactNode;
  label?: string;
  disabled?: boolean;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const data = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      await onSubmit(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit}>
      {children}
      {error && <ErrorBox message={error} />}
      <button
        className="button primary"
        disabled={busy || disabled}
        type="submit"
      >
        {busy && <LoaderCircle size={16} className="spin" />}
        {busy ? "Working…" : label}
      </button>
    </form>
  );
}
export const text = (data: FormData, key: string) =>
  String(data.get(key) ?? "");
export const num = (data: FormData, key: string) => Number(data.get(key));

export function Trend({
  readings,
  limit,
}: {
  readings: Reading[];
  limit: number;
}) {
  if (!readings.length)
    return (
      <Empty title="No telemetry yet">
        Ingest timestamped readings to begin.
      </Empty>
    );
  const width = 680,
    height = 185,
    pad = 28,
    maximum = Math.max(limit * 1.25, ...readings.map((r) => r.vibration)) || 1;
  const first = new Date(readings[0].observed_at).getTime(),
    last = new Date(readings.at(-1)!.observed_at).getTime();
  const px = (r: Reading) =>
    pad +
    ((new Date(r.observed_at).getTime() - first) / (last - first || 1)) *
      (width - 2 * pad);
  const py = (v: number) => height - pad - (v / maximum) * (height - 2 * pad);
  const points = readings.map((r) => `${px(r)},${py(r.vibration)}`).join(" ");
  return (
    <>
      <svg
        className="trend"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${readings.length} vibration readings; latest ${readings.at(-1)!.vibration} millimeters per second; alert threshold ${limit}`}
      >
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line
              x1={pad}
              x2={width - pad}
              y1={py(maximum * f)}
              y2={py(maximum * f)}
              className="gridline"
            />
            <text x={0} y={py(maximum * f) + 4}>
              {(maximum * f).toFixed(1)}
            </text>
          </g>
        ))}
        <line
          x1={pad}
          x2={width - pad}
          y1={py(limit)}
          y2={py(limit)}
          className="threshold"
        />
        <polyline
          points={points}
          fill="none"
          stroke="var(--accent)"
          strokeWidth="2.5"
        />
        <circle
          cx={px(readings.at(-1)!)}
          cy={py(readings.at(-1)!.vibration)}
          r="4"
          fill="var(--accent)"
        />
      </svg>
      <div className="chart-labels">
        <span>{date(readings[0].observed_at)}</span>
        <span>Threshold {limit} mm/s</span>
        <span>{date(readings.at(-1)!.observed_at)}</span>
      </div>
    </>
  );
}
