import { useCallback, useEffect, useRef, useState } from "react";
import type { Dashboard, PlatformConfig } from "./types";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  const text = await response.text();
  let body: unknown = {};
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = { detail: text };
  }
  if (!response.ok) {
    const detail = (body as { detail?: unknown }).detail;
    throw new Error(typeof detail === "string" ? detail : `${response.status} ${response.statusText}`);
  }
  return body as T;
}

const POLL_MS = 2000;

/** Polls the aggregated dashboard; one request in flight at a time. */
export function useDashboard() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const inFlight = useRef(false);

  const refresh = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      setData(await api<Dashboard>("/api/dashboard"));
      setError(null);
      setUpdatedAt(new Date());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, POLL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  return { data, error, updatedAt, refresh };
}

export function useConfig() {
  const [config, setConfig] = useState<PlatformConfig | null>(null);
  useEffect(() => {
    api<PlatformConfig>("/api/config").then(setConfig).catch(() => setConfig(null));
  }, []);
  return config;
}
