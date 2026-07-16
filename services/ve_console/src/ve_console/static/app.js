const sidebar = document.getElementById("sidebar");
const scrim = document.getElementById("sidebar-scrim");
const menuButton = document.getElementById("menu-button");

function closeMenu() {
  document.body.classList.remove("nav-open");
}

menuButton?.addEventListener("click", () => document.body.classList.toggle("nav-open"));
scrim?.addEventListener("click", closeMenu);
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeMenu();
});

function renderIcons() {
  if (window.lucide) window.lucide.createIcons({ attrs: { "stroke-width": 1.8 } });
}

function setLiveState(label, state = "") {
  const indicator = document.querySelector(".live-state");
  if (!indicator) return;
  indicator.classList.toggle("syncing", state === "syncing");
  indicator.classList.toggle("offline", state === "offline");
  const text = indicator.querySelector("b");
  if (text) text.textContent = label;
}

async function refreshLiveData() {
  if (document.hidden || ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;
  setLiveState("Syncing", "syncing");
  try {
    const response = await fetch(window.location.href, {
      headers: { "X-VE-Live-Refresh": "1" },
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`Refresh failed: ${response.status}`);
    const documentCopy = new DOMParser().parseFromString(await response.text(), "text/html");
    const currentMain = document.querySelector("main");
    const nextMain = documentCopy.querySelector("main");
    if (currentMain && nextMain) currentMain.replaceWith(nextMain);
    setLiveState("Live");
    renderIcons();
  } catch (error) {
    setLiveState("Offline", "offline");
  }
}

renderIcons();
window.setInterval(refreshLiveData, 15000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshLiveData();
});
