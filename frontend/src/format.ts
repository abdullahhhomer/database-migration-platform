import type { TargetName } from "./types";

export const TARGETS: Record<TargetName, { label: string; role: string; short: string }> = {
  databricks: { label: "Databricks", role: "Lakehouse · bronze Delta tables", short: "DBX" },
  sqlserver: { label: "SQL Server", role: "Stand-in for Amazon RDS", short: "SQL" },
  mongodb: { label: "MongoDB", role: "Stand-in for DocumentDB", short: "MDB" },
};

export const TABLES = ["customers", "products", "orders", "order_items", "payments", "shipments", "returns"];

const nf = new Intl.NumberFormat("en-US");

export function num(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "–";
  return Number(value).toLocaleString("en-US", { maximumFractionDigits: digits });
}

export function compact(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (value >= 10_000) return `${(value / 1_000).toFixed(1)}k`;
  return nf.format(value);
}

export function bytes(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  const units = ["B", "KB", "MB", "GB"];
  let v = value;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(i ? 1 : 0)} ${units[i]}`;
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "–";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

export function clock(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso.endsWith("Z") || /[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  return d.toLocaleTimeString("en-GB", { hour12: false });
}

export function parseTime(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const d = new Date(iso.endsWith("Z") || /[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(d.getTime()) ? null : d.getTime();
}

export function words(value: string | null | undefined): string {
  return (value ?? "").replace(/_/g, " ");
}
