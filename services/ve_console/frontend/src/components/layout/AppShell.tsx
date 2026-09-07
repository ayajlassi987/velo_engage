import { useEffect, useState, type ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import type { SessionInfo } from "../../api/types";
import type { LiveStatus } from "../../hooks/useLiveRefresh";

interface Props {
  session: SessionInfo | null;
  title: string;
  subtitle: string;
  liveStatus: LiveStatus;
  children: ReactNode;
}

// Mirrors static/app.js's menuButton/scrim/Escape-key handling for the
// mobile nav drawer (toggles a "nav-open" class on <body>, same as the
// Jinja pages) so the identical CSS in theme.css produces identical
// behavior here.
export function AppShell({ session, title, subtitle, liveStatus, children }: Props) {
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => {
    document.body.classList.toggle("nav-open", navOpen);
  }, [navOpen]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setNavOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="app-shell">
      <Sidebar session={session} />
      <div className="sidebar-scrim" onClick={() => setNavOpen(false)} />
      <section className="workspace">
        <Topbar
          session={session}
          title={title}
          subtitle={subtitle}
          liveStatus={liveStatus}
          onMenuClick={() => setNavOpen((open) => !open)}
        />
        <main>{children}</main>
      </section>
    </div>
  );
}
