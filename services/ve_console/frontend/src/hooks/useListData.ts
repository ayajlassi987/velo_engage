import { useSearchParams } from "react-router-dom";
import { useLiveRefresh } from "./useLiveRefresh";

// Filters live in the URL query string (exactly like the old list.html
// pages' GET-based filter form) so a filtered view stays a real, bookmark/
// shareable/refreshable URL — then re-fetched on the same 15s live-refresh
// cadence as every other page.
export function useListData<T>(fetchFn: (params: URLSearchParams) => Promise<T>) {
  const [searchParams, setSearchParams] = useSearchParams();
  const { data, status } = useLiveRefresh(() => fetchFn(searchParams));
  return { data, status, searchParams, setSearchParams };
}
