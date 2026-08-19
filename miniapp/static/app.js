// Freight Pilot Mini App — frontend logic.
// Talks to the FastAPI backend (miniapp/api.py) served from the same origin.

const API = ""; // same-origin, so relative paths work directly

// --- Telegram integration: pull the user's real theme colors into CSS vars,
// so the app matches whatever light/dark theme they're already using. ---
const tg = window.Telegram && window.Telegram.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
  const applyTheme = () => {
    const p = tg.themeParams || {};
    const root = document.documentElement.style;
    if (p.bg_color) root.setProperty("--tg-theme-bg-color", p.bg_color);
    if (p.secondary_bg_color) root.setProperty("--tg-theme-secondary-bg-color", p.secondary_bg_color);
    if (p.text_color) root.setProperty("--tg-theme-text-color", p.text_color);
    if (p.hint_color) root.setProperty("--tg-theme-hint-color", p.hint_color);
  };
  applyTheme();
  tg.onEvent("themeChanged", applyTheme);
}

// --- Simple session storage (survives reloads within the same WebView) ---
const session = {
  get token() { return localStorage.getItem("fp_token"); },
  set token(v) { v ? localStorage.setItem("fp_token", v) : localStorage.removeItem("fp_token"); },
  get role() { return localStorage.getItem("fp_role"); },
  set role(v) { v ? localStorage.setItem("fp_role", v) : localStorage.removeItem("fp_role"); },
  get companyName() { return localStorage.getItem("fp_company"); },
  set companyName(v) { v ? localStorage.setItem("fp_company", v) : localStorage.removeItem("fp_company"); },
};

async function api(path, options = {}) {
  const headers = options.headers || {};
  headers["Content-Type"] = "application/json";
  if (session.token) headers["Authorization"] = `Bearer ${session.token}`;
  const res = await fetch(API + path, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Something went wrong");
  return data;
}

const $ = (id) => document.getElementById(id);

function showScreen(name) {
  $("screen-login").classList.toggle("hidden", name !== "login");
  $("screen-dashboard").classList.toggle("hidden", name !== "dashboard");
}

// ---------------- Login screen ----------------
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("is-active"));
    tab.classList.add("is-active");
    const role = tab.dataset.role;
    $("form-owner").classList.toggle("hidden", role !== "owner");
    $("form-dispatcher").classList.toggle("hidden", role !== "dispatcher");
  });
});

$("form-owner").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("owner-error").textContent = "";
  try {
    const data = await api("/api/auth/owner", {
      method: "POST",
      body: JSON.stringify({ mc_number: $("owner-mc").value.trim(), password: $("owner-password").value }),
    });
    session.token = data.token;
    session.role = "owner";
    session.companyName = data.company_name;
    await enterDashboard();
  } catch (err) {
    $("owner-error").textContent = err.message;
  }
});

$("form-dispatcher").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("dispatcher-error").textContent = "";
  try {
    const data = await api("/api/auth/dispatcher", {
      method: "POST",
      body: JSON.stringify({
        username: $("dispatcher-username").value.trim(),
        password: $("dispatcher-password").value,
      }),
    });
    session.token = data.token;
    session.role = "dispatcher";
    session.companyName = "";
    await enterDashboard();
  } catch (err) {
    $("dispatcher-error").textContent = err.message;
  }
});

// ---------------- Dashboard screen ----------------
$("btn-logout").addEventListener("click", () => {
  session.token = null;
  session.role = null;
  session.companyName = null;
  showScreen("login");
});

async function enterDashboard() {
  $("dash-company").textContent = session.companyName || "Dispatcher access";
  $("dash-role").textContent = session.role === "owner" ? "Owner dashboard" : "Dispatcher dashboard";
  $("owner-only-section").classList.toggle("hidden", session.role !== "owner");

  await loadDrivers();
  showScreen("dashboard");
}

async function loadDrivers() {
  const drivers = await api("/api/drivers");

  const total = drivers.length;
  const active = drivers.filter((d) => d.subscription_active).length;
  const loads = drivers.reduce((sum, d) => sum + d.load_count, 0);
  $("stat-total").textContent = total;
  $("stat-active").textContent = active;
  $("stat-loads").textContent = loads;

  const list = $("driver-list");
  list.innerHTML = "";

  if (drivers.length === 0) {
    list.appendChild($("driver-empty"));
    return;
  }

  for (const driver of drivers) {
    const row = document.createElement("div");
    row.className = "driver-row";

    const dot = document.createElement("span");
    dot.className = `status-dot ${driver.subscription_active ? "on" : "off"}`;

    const info = document.createElement("div");
    info.className = "driver-info";
    const name = document.createElement("div");
    name.className = "driver-name";
    name.textContent = driver.full_name;
    const meta = document.createElement("div");
    meta.className = "driver-meta";
    meta.textContent = `#${driver.driver_bot_id} · ${driver.load_count} loads` +
      (driver.dispatcher_username ? ` · ${driver.dispatcher_username}` : "");
    info.append(name, meta);

    row.append(dot, info);

    // Only the owner can toggle a driver's subscription on/off.
    if (session.role === "owner") {
      const toggle = document.createElement("button");
      toggle.className = `toggle ${driver.subscription_active ? "is-on" : ""}`;
      toggle.addEventListener("click", async () => {
        const nextState = !driver.subscription_active;
        toggle.classList.toggle("is-on", nextState);
        dot.className = `status-dot ${nextState ? "on" : "off"}`;
        driver.subscription_active = nextState;
        try {
          await api(`/api/drivers/${driver.id}/subscription`, {
            method: "PATCH",
            body: JSON.stringify({ active: nextState }),
          });
          await loadDrivers(); // refresh the stat counters
        } catch (err) {
          alert(err.message);
        }
      });
      row.append(toggle);
    }

    list.appendChild(row);
  }
}

// ---------------- Add-dispatcher form (owner only) ----------------
$("form-add-dispatcher").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("add-dispatcher-error").textContent = "";
  $("add-dispatcher-success").classList.add("hidden");
  try {
    await api("/api/dispatchers", {
      method: "POST",
      body: JSON.stringify({
        username: $("new-dispatcher-username").value.trim(),
        password: $("new-dispatcher-password").value,
      }),
    });
    $("add-dispatcher-success").classList.remove("hidden");
    e.target.reset();
  } catch (err) {
    $("add-dispatcher-error").textContent = err.message;
  }
});

// ---------------- Boot ----------------
(async function init() {
  if (session.token) {
    try {
      await enterDashboard();
      return;
    } catch {
      session.token = null; // expired/invalid - fall through to login
    }
  }
  showScreen("login");
})();
