import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  CircleDashed,
  Clock3,
  Loader2,
  PauseCircle,
  XCircle,
} from "lucide-react";
import { words } from "../format";

const HOLD_MS = 8000;

/**
 * Signature move: a value that changed stays lit (alert yellow + NOW tag)
 * for a few seconds, like a gate change on a departure board.
 */
export function useHeldChange(key: string, value: unknown): boolean {
  const previous = useRef<Map<string, unknown>>(new Map());
  const changedAt = useRef<Map<string, number>>(new Map());
  const [, force] = useState(0);

  const serialized = JSON.stringify(value ?? null);
  const prior = previous.current.get(key);
  // The first real value after "no data yet" is an arrival, not a change.
  if (prior !== undefined && prior !== "null" && prior !== serialized) {
    changedAt.current.set(key, Date.now());
  }
  previous.current.set(key, serialized);

  const at = changedAt.current.get(key);
  const lit = at !== undefined && Date.now() - at < HOLD_MS;

  useEffect(() => {
    if (!lit || at === undefined) return;
    const timer = window.setTimeout(() => force((n) => n + 1), HOLD_MS - (Date.now() - at) + 20);
    return () => window.clearTimeout(timer);
  }, [lit, at]);

  return lit;
}

export function NowTag() {
  return <span className="now-tag">Now</span>;
}

type Tone = "ok" | "warn" | "bad" | "idle" | "run";

const STATE_TONE: Record<string, Tone> = {
  in_sync: "ok",
  completed: "ok",
  passed: "ok",
  ready: "ok",
  streaming: "run",
  full_load_completed: "ok",
  done: "ok",
  catching_up: "run",
  running: "run",
  full_load: "run",
  preparing: "run",
  loading: "run",
  freezing: "run",
  draining: "run",
  validating: "run",
  constraints: "run",
  waiting_for_full_load: "warn",
  pending: "idle",
  idle: "idle",
  not_started: "idle",
  rolled_back: "idle",
  failed: "bad",
  error: "bad",
  not_configured: "bad",
  cancelled: "bad",
  interrupted: "bad",
  not_ready: "bad",
};

const STATE_LABEL: Record<string, string> = {
  waiting_for_full_load: "Buffering",
  full_load_completed: "Loaded",
  completed: "Done",
  in_sync: "In sync",
  catching_up: "Catching up",
  not_configured: "Not configured",
  not_ready: "Not ready",
};

function toneIcon(tone: Tone, spinning: boolean) {
  const size = 15;
  switch (tone) {
    case "ok":
      return <CheckCircle2 size={size} aria-hidden />;
    case "bad":
      return <XCircle size={size} aria-hidden />;
    case "warn":
      return <Clock3 size={size} aria-hidden />;
    case "run":
      return spinning ? <Loader2 size={size} className="spin" aria-hidden /> : <CircleDashed size={size} aria-hidden />;
    default:
      return <PauseCircle size={size} aria-hidden />;
  }
}

export function StatusTag({ state, label }: { state: string | null | undefined; label?: string }) {
  const key = state ?? "idle";
  const tone = STATE_TONE[key] ?? "idle";
  return (
    <span className={`status status-${tone}`}>
      {toneIcon(tone, tone === "run")}
      <span>{label ?? STATE_LABEL[key] ?? words(key)}</span>
    </span>
  );
}

export function Panel({
  title,
  meta,
  children,
  className = "",
}: {
  title: string;
  meta?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <header className="panel-head">
        <h2>{title}</h2>
        {meta ? <div className="panel-meta">{meta}</div> : null}
      </header>
      <div className="panel-body">{children}</div>
    </section>
  );
}

export function Empty({ icon = "dashed", children }: { icon?: "dashed" | "ban" | "alert"; children: ReactNode }) {
  const Icon = icon === "ban" ? Ban : icon === "alert" ? AlertTriangle : CircleDashed;
  return (
    <div className="empty">
      <Icon size={18} aria-hidden />
      <p>{children}</p>
    </div>
  );
}

export function Fact({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="fact">
      <dt>{label}</dt>
      <dd>
        <span className="fig">{value}</span>
        {sub ? <span className="fact-sub">{sub}</span> : null}
      </dd>
    </div>
  );
}
