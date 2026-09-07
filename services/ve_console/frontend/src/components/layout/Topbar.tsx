import { Link } from "react-router-dom";
import { Menu, HeartPulse, RefreshCw } from "lucide-react";
import type { SessionInfo } from "../../api/types";
import type { LiveStatus } from "../../hooks/useLiveRefresh";
import { formatDateTime } from "../../lib/format";

interface Props {
  session: SessionInfo | null;
  title: string;
  subtitle: string;
  liveStatus: LiveStatus;
  onMenuClick: () => void;
}

const STATUS_LABEL: Record<LiveStatus, string> = { live: "Live", syncing: "Syncing", offline: "Offline" };
const STATUS_CLASS: Record<LiveStatus, string> = { live: "", syncing: "syncing", offline: "offline" };

export function Topbar({ session, title, subtitle, liveStatus, onMenuClick }: Props) {
  const isAdmin = (session?.user.roles ?? []).includes("admin");
  const userInitials = (session?.user.name ?? "?").slice(0, 2).toUpperCase();

  return (
    <>
      <header className="topbar">
        <button className="icon-button mobile-menu" type="button" aria-label="Open navigation" onClick={onMenuClick}>
          <Menu />
        </button>
        <div className="breadcrumbs"><span>VeloDoc</span><span aria-hidden>›</span><strong>{title}</strong></div>
        <div className="topbar-actions">
          <span className={`live-state ${STATUS_CLASS[liveStatus]}`} title="Data refreshes every 15 seconds">
            <span></span><b>{STATUS_LABEL[liveStatus]}</b>
          </span>
          {isAdmin && (
            <Link className="icon-button" to="/operations" title="System status" aria-label="System status"><HeartPulse /></Link>
          )}
          <span className="user-avatar" title={session?.user.name ?? ""}>{userInitials}</span>
        </div>
      </header>
      <header className="page-heading">
        <div><h1>{title}</h1><p>{subtitle}</p></div>
        <div className="page-time"><RefreshCw /> Updated {formatDateTime(new Date().toISOString())} UTC</div>
      </header>
    </>
  );
}
