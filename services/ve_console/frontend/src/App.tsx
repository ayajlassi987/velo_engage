import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { OverviewPage } from "./pages/Overview";
import { OpportunitiesPage } from "./pages/Opportunities";
import { CampaignsPage } from "./pages/Campaigns";
import { CampaignDetailPage } from "./pages/CampaignDetail";
import { WhatsAppPage } from "./pages/WhatsApp";
import { MessageDetailPage } from "./pages/MessageDetail";
import { ClinicalSummariesPage } from "./pages/ClinicalSummaries";
import { BookingsPage } from "./pages/Bookings";
import { RevenuePage } from "./pages/Revenue";
import { HoldoutPage } from "./pages/Holdout";
import { ModelsPage } from "./pages/Models";
import { OperationsPage } from "./pages/Operations";

// Mounted under /app (see vite.config.ts's base + FastAPI's catch-all route
// in main.py). Every page here has a JSON /api/v1/* endpoint that reuses
// the exact same data-fetch function the original Jinja route calls (see
// main.py) — no business logic was duplicated migrating any of these.
export default function App() {
  return (
    <BrowserRouter basename="/app">
      <Routes>
        <Route path="/" element={<Navigate to="/overview" replace />} />
        <Route path="/overview" element={<OverviewPage />} />
        <Route path="/opportunities" element={<OpportunitiesPage />} />
        <Route path="/campaigns" element={<CampaignsPage />} />
        <Route path="/campaigns/:campaignId" element={<CampaignDetailPage />} />
        <Route path="/whatsapp" element={<WhatsAppPage />} />
        <Route path="/whatsapp/messages/:waMessageId" element={<MessageDetailPage />} />
        <Route path="/clinical-summaries" element={<ClinicalSummariesPage />} />
        <Route path="/bookings" element={<BookingsPage />} />
        <Route path="/revenue" element={<RevenuePage />} />
        <Route path="/holdout" element={<HoldoutPage />} />
        <Route path="/models" element={<ModelsPage />} />
        <Route path="/operations" element={<OperationsPage />} />
      </Routes>
    </BrowserRouter>
  );
}
