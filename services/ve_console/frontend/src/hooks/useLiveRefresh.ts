import { useCallback, useEffect, useRef, useState } from "react";

export type LiveStatus = "live" | "syncing" | "offline";

// Mirrors static/app.js's refreshLiveData() exactly (15s interval, skips a
// tick while the tab is hidden or the user is mid-edit in a form field, and
// refreshes immediately when the tab becomes visible again) so pages
// migrated to React behave identically to the Jinja pages they replace.
export function useLiveRefresh<T>(fetchFn: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [status, setStatus] = useState<LiveStatus>("syncing");
  const fetchRef = useRef(fetchFn);
  fetchRef.current = fetchFn;

  const refresh = useCallback(async () => {
    const active = document.activeElement;
    const tag = active?.tagName;
    if (document.hidden || tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
    setStatus("syncing");
    try {
      const next = await fetchRef.current();
      setData(next);
      setStatus("live");
    } catch {
      setStatus("offline");
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = window.setInterval(refresh, 15000);
    const onVisible = () => {
      if (!document.hidden) refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refresh]);

  return { data, status };
}
