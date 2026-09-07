import { NavLink } from "react-router-dom";
import {
  LayoutDashboard, ScanSearch, Send, MessageCircle, FileText,
  CalendarCheck, CircleDollarSign, Split, BrainCircuit, Activity,
  ChevronsUpDown, LogOut,
} from "lucide-react";
import type { SessionInfo } from "../../api/types";

function navClass({ isActive }: { isActive: boolean }) {
  return isActive ? "active" : "";
}

export function Sidebar({ session }: { session: SessionInfo | null }) {
  const roles = session?.user.roles ?? [];
  const isOwnerOrAdmin = roles.includes("owner") || roles.includes("admin");
  const isAdmin = roles.includes("admin");
  const clinicInitials = (session?.clinic.name ?? "").slice(0, 2).toUpperCase();
  const userInitials = (session?.user.name ?? "?").slice(0, 2).toUpperCase();

  return (
    <aside className="sidebar" id="sidebar">
      <a className="brand" href="/overview" aria-label="VeloDoc overview">
        <span className="brand-mark">VD</span>
        <span><strong>VeloDoc</strong><small>Clinic growth console</small></span>
      </a>

      <nav className="primary-nav" aria-label="Primary navigation">
        <span className="nav-label">Workspace</span>
        <NavLink to="/overview" className={navClass}><LayoutDashboard /><span>Overview</span></NavLink>
        <NavLink to="/opportunities" className={navClass}><ScanSearch /><span>Opportunities</span></NavLink>
        <NavLink to="/campaigns" className={navClass}><Send /><span>Campaigns</span></NavLink>
        <NavLink to="/whatsapp" className={navClass}><MessageCircle /><span>WhatsApp</span></NavLink>
        <NavLink to="/clinical-summaries" className={navClass}><FileText /><span>Clinical summaries</span></NavLink>

        <span className="nav-label">Measurement</span>
        <NavLink to="/bookings" className={navClass}><CalendarCheck /><span>Bookings</span></NavLink>
        {isOwnerOrAdmin && (
          <>
            <NavLink to="/revenue" className={navClass}><CircleDollarSign /><span>Revenue</span></NavLink>
            <NavLink to="/holdout" className={navClass}><Split /><span>Holdout</span></NavLink>
          </>
        )}

        {isAdmin && (
          <>
            <span className="nav-label">Platform</span>
            <NavLink to="/models" className={navClass}><BrainCircuit /><span>Models</span></NavLink>
            <NavLink to="/operations" className={navClass}><Activity /><span>Operations</span></NavLink>
          </>
        )}
      </nav>

      <div className="clinic-switcher">
        <span className="clinic-avatar">{clinicInitials}</span>
        <span><strong>{session?.clinic.name}</strong><small>{session?.clinic.id}</small></span>
        <ChevronsUpDown />
      </div>
      {session && (
        <div className="clinic-switcher" style={{ marginTop: 8 }}>
          <span className="clinic-avatar">{userInitials}</span>
          <span><strong>{session.user.name}</strong><small>{session.user.roles.join(", ")}</small></span>
          <a className="icon-button" href="/logout" title="Log out" aria-label="Log out"><LogOut /></a>
        </div>
      )}
    </aside>
  );
}
