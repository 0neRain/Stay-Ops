const icon = (name, className = "icon") => {
  const icons = {
    home: '<path d="m3 11 9-8 9 8"/><path d="M5 10v10h14V10"/><path d="M9 20v-6h6v6"/>',
    arrow: '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
    back: '<path d="m15 18-6-6 6-6"/>',
    message: '<path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z"/><path d="M8 9h8M8 13h5"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/>',
    bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M10 21h4"/>',
    spark: '<path d="m12 3 1.25 3.75L17 8l-3.75 1.25L12 13l-1.25-3.75L7 8l3.75-1.25Z"/><path d="m5 15 .75 2.25L8 18l-2.25.75L5 21l-.75-2.25L2 18l2.25-.75Z"/><path d="m19 14 .6 1.4L21 16l-1.4.6L19 18l-.6-1.4L17 16l1.4-.6Z"/>',
    chevron: '<path d="m6 9 6 6 6-6"/>',
    pin: '<path d="M20 10c0 5-8 11-8 11S4 15 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    send: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    chart: '<path d="M4 19V9M10 19V5M16 19v-7M22 19H2"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21h-4v-.09A1.7 1.7 0 0 0 8.5 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3v-4h.09A1.7 1.7 0 0 0 4.6 8.5a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3h4v.09A1.7 1.7 0 0 0 15.5 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 9c.1.35.3.7.6 1 .3.2.7.4 1.1.4h.09v4h-.09A1.7 1.7 0 0 0 19.4 15Z"/>',
    logout: '<path d="M10 17l5-5-5-5M15 12H3"/><path d="M14 3h5a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-5"/>',
    shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/>',
    inbox: '<path d="M4 4h16v14H4Z"/><path d="m4 13 4-4h8l4 4M9 18v2h6v-2"/>',
    alert: '<path d="M10.3 2.9 1.8 17a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 2.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/>',
    left: '<path d="m15 18-6-6 6-6"/>',
    right: '<path d="m9 18 6-6-6-6"/>',
    close: '<path d="m18 6-12 12M6 6l12 12"/>',
  };
  return `<svg class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || ""}</svg>`;
};

const brand = (linked = true) => {
  const content = `<span class="brand-mark">${icon("home")}</span><span class="brand-name">StayOps</span>`;
  return linked ? `<a class="brand-lockup" href="/" data-link>${content}</a>` : `<div class="brand-lockup">${content}</div>`;
};

const app = document.querySelector("#app");
const state = {
  selectedThread: "maya",
  weekOffset: 0,
  notificationOpen: false,
  readNotifications: new Set(),
};

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

const homes = [
  {
    id: "harbor",
    name: "Harbor House",
    short: "Harbor",
    color: "#26766d",
    rooms: 3,
    guests: [
      { id: "maya", name: "Maya Chen", initials: "MC", dates: "Sep 14–18", time: "2m", preview: "The keypad isn’t accepting the code", unread: 2, handoff: true, avatar: "#d7e9e3" },
      { id: "jonas", name: "Jonas Berg", initials: "JB", dates: "Sep 19–22", time: "18m", preview: "Thanks, that worked perfectly!", unread: 0, handoff: false, avatar: "#dfe3ed" },
    ],
  },
  {
    id: "olive",
    name: "The Olive Loft",
    short: "Olive Loft",
    color: "#4778b9",
    rooms: 2,
    guests: [
      { id: "elena", name: "Elena Rossi", initials: "ER", dates: "Sep 13–16", time: "34m", preview: "Can we leave our bags after checkout?", unread: 1, handoff: true, avatar: "#f0ddcf" },
      { id: "sam", name: "Sam & Alex", initials: "SA", dates: "Sep 18–21", time: "1h", preview: "What’s the Wi-Fi password?", unread: 0, handoff: false, avatar: "#eadfcb" },
    ],
  },
  {
    id: "casa",
    name: "Casa Limone",
    short: "Casa Limone",
    color: "#875c8f",
    rooms: 4,
    guests: [
      { id: "noah", name: "Noah Williams", initials: "NW", dates: "Sep 15–20", time: "3h", preview: "We may arrive around midnight", unread: 0, handoff: false, avatar: "#e4d9e8" },
    ],
  },
];

const conversations = {
  maya: {
    status: "Needs handoff",
    handoff: true,
    reason: "Access issue · Guest is at the property",
    messages: [
      { from: "guest", text: "Hi! We’ve just arrived, but the keypad isn’t accepting the code from our check-in message.", time: "16:42" },
      { from: "ai", text: "I’m sorry you’re having trouble getting in. I’ve checked the arrival date, but I can’t safely issue or change an access code. I’m alerting the host now.", time: "16:43" },
      { from: "guest", text: "Okay, thank you. We’re waiting by the front door.", time: "16:45" },
    ],
  },
  jonas: {
    status: "AI active",
    handoff: false,
    messages: [
      { from: "guest", text: "Could you remind me where to leave the recycling?", time: "15:58" },
      { from: "ai", text: "Of course — the blue recycling bins are inside the courtyard, just past the side gate. Glass goes in the smaller green bin.", time: "15:58" },
      { from: "guest", text: "Thanks, that worked perfectly!", time: "16:26" },
    ],
  },
  elena: {
    status: "Needs handoff",
    handoff: true,
    reason: "Late checkout · Host decision required",
    messages: [
      { from: "guest", text: "Can we leave our bags somewhere after checkout tomorrow?", time: "16:08" },
      { from: "ai", text: "Late luggage storage isn’t available inside the apartment, but there’s a staffed storage point at Firenze Santa Maria Novella station, about 8 minutes away.", time: "16:09" },
    ],
  },
  sam: {
    status: "AI active",
    handoff: false,
    messages: [
      { from: "guest", text: "Hi, what’s the Wi-Fi password?", time: "15:20" },
      { from: "ai", text: "The network is OliveLoft_Guest. You’ll find the current password on the welcome card next to the coffee machine.", time: "15:20" },
    ],
  },
  noah: {
    status: "Awaiting guest",
    handoff: false,
    messages: [
      { from: "guest", text: "Our flight is delayed and we may arrive around midnight. Is that okay?", time: "13:12" },
      { from: "ai", text: "Yes, self check-in is available at any time after 3:00 PM. I’ve noted your expected arrival. Your access instructions will be active when you arrive.", time: "13:13" },
    ],
  },
};

const reservations = [
  { home: "harbor", guest: "Maya Chen", start: "2026-09-14", end: "2026-09-18", color: "teal", status: "In house" },
  { home: "harbor", guest: "Jonas Berg", start: "2026-09-19", end: "2026-09-22", color: "teal", status: "Upcoming" },
  { home: "olive", guest: "Elena Rossi", start: "2026-09-13", end: "2026-09-16", color: "blue", status: "In house" },
  { home: "olive", guest: "Sam & Alex", start: "2026-09-18", end: "2026-09-21", color: "blue", status: "Upcoming" },
  { home: "casa", guest: "Noah Williams", start: "2026-09-15", end: "2026-09-20", color: "plum", status: "Upcoming" },
];

const notifications = [
  { id: "access", thread: "maya", title: "Access issue needs you", detail: "Maya Chen is waiting outside Harbor House.", time: "2m" },
  { id: "refund", thread: "elena", title: "Review requested", detail: "A late-checkout request needs a host decision.", time: "28m" },
  { id: "resolved", thread: "jonas", title: "Handoff resolved", detail: "Recycling instructions were confirmed.", time: "1h" },
];

function navigate(path) {
  if (window.location.pathname !== path) history.pushState({}, "", path);
  renderRoute();
  window.scrollTo({ top: 0, behavior: "instant" });
}

function toast(message) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = message;
  document.querySelector("#toast-region").append(el);
  setTimeout(() => el.remove(), 3200);
}

function landingPage() {
  return `
    <a class="skip-link" href="#main">Skip to content</a>
    <div class="landing">
      <nav class="landing-nav" aria-label="Main navigation">
        ${brand()}
        <div class="nav-links"><a href="#product">Product</a><a href="#workflow">How it works</a></div>
        <div class="nav-actions"><a class="btn btn-ghost" href="/auth" data-link>Sign in</a><a class="btn btn-dark" href="/auth?mode=register" data-link>Get started ${icon("arrow", "icon icon-sm")}</a></div>
      </nav>
      <main id="main">
        <section class="hero">
          <div class="hero-copy">
            <span class="eyebrow">Human-supervised guest operations</span>
            <h1>Every guest.<br>Every home.<br><em>One calm place.</em></h1>
            <p class="hero-lede">StayOps keeps conversations moving, reservations visible, and the moments that need a human impossible to miss.</p>
            <div class="hero-actions">
              <a class="btn btn-primary" href="/auth?mode=register" data-link>Start free ${icon("arrow", "icon icon-sm")}</a>
              <a class="btn btn-outline" href="/dashboard" data-link>Preview the dashboard</a>
            </div>
            <div class="micro-proof"><span class="avatar-stack"><span class="mini-avatar">AM</span><span class="mini-avatar">LR</span><span class="mini-avatar">JK</span></span><span>Built for owners and property teams who stay close to the guest.</span></div>
          </div>
          <div class="hero-visual" aria-label="Preview of the guest operations inbox">
            <div class="hero-board">
              <div class="mock-topbar"><div class="mock-dots"><i></i><i></i><i></i></div><span class="mock-date">MON · SEP 14</span></div>
              <div class="mock-grid">
                <div class="mock-sidebar"><div class="mock-label">Guest inbox</div><div class="mock-home"><span class="home-dot"></span>Harbor House</div><div class="mock-guest active"><span class="mock-avatar">MC</span>Maya Chen</div><div class="mock-guest"><span class="mock-avatar">JB</span>Jonas Berg</div><div class="mock-home"><span class="home-dot" style="background:#4778b9"></span>Olive Loft</div><div class="mock-guest"><span class="mock-avatar">ER</span>Elena Rossi</div></div>
                <div class="mock-content"><div class="mock-content-head"><h3>Maya Chen</h3><span class="mock-status">NEEDS YOU</span></div><div class="mock-message">Hi! We’ve arrived, but the keypad isn’t accepting the code.</div><div class="mock-answer">I’m sorry you’re having trouble. I’m alerting the host now.</div></div>
              </div>
            </div>
            <div class="mock-handoff"><div class="mock-handoff-row"><span class="handoff-pulse"></span>Human handoff</div><p>Access issue at Harbor House. Guest is waiting at the property.</p></div>
          </div>
        </section>
        <section class="trust-row" aria-label="Product principles">
          <div class="trust-item"><strong>One inbox</strong><span>Conversations grouped by home</span></div>
          <div class="trust-item"><strong>Live context</strong><span>Stays and guest details together</span></div>
          <div class="trust-item"><strong>Human control</strong><span>Sensitive moments always handed off</span></div>
        </section>
        <section class="landing-section" id="product">
          <div class="section-heading"><div><span class="eyebrow">A focused workspace</span><h2>Know what’s happening before it becomes urgent.</h2></div><p>Move between each home’s guest conversations and reservation calendar without losing the context behind a message.</p></div>
          <div class="feature-grid" id="workflow">
            <article class="feature-card dark"><span class="feature-icon">${icon("message")}</span><h3>Guest chats, organized by home</h3><p>See every active conversation, stay detail, and AI-assisted response in a single, property-aware inbox.</p></article>
            <article class="feature-card"><span class="feature-icon">${icon("bell")}</span><h3>Handoffs that stand out</h3><p>Get a clear reason, urgency, and proposed next step when a guest needs a person.</p></article>
            <article class="feature-card"><span class="feature-icon">${icon("calendar")}</span><h3>Reservations in view</h3><p>Read occupancy across your homes at a glance and jump from a stay to its guest thread.</p></article>
            <article class="feature-card dark"><span class="feature-icon">${icon("shield")}</span><h3>AI with boundaries</h3><p>Routine questions move quickly. Refunds, access, safety, and uncertain answers stay under human control.</p></article>
          </div>
        </section>
        <section class="landing-cta"><h2>A quieter way to run guest support.</h2><a class="btn btn-primary" href="/auth?mode=register" data-link>Create your workspace ${icon("arrow", "icon icon-sm")}</a></section>
      </main>
      <footer class="landing-footer"><span>© 2026 StayOps</span><span>Thoughtful automation. Human judgment.</span></footer>
    </div>`;
}

function authPage() {
  const params = new URLSearchParams(window.location.search);
  const mode = params.get("mode") === "register" ? "register" : "login";
  return `
    <a class="skip-link" href="#auth-form">Skip to form</a>
    <main class="auth-page">
      <section class="auth-story">
        <div class="auth-brand">${brand()}</div>
        <div class="story-copy"><span class="eyebrow">Your day, clearly arranged</span><h1>Hospitality feels better when the busywork feels lighter.</h1><p>Keep your team close to every guest without living inside five different tools.</p></div>
        <blockquote class="story-quote">“The best operations software should feel like a calm pair of hands.”</blockquote>
      </section>
      <section class="auth-form-wrap">
        <div class="auth-card">
          <a href="/" data-link>${icon("back", "icon icon-sm")} Back to StayOps</a>
          <h2 id="auth-title">${mode === "register" ? "Create your workspace" : "Welcome back"}</h2>
          <p id="auth-subtitle">${mode === "register" ? "Start bringing your guest operations into focus." : "Sign in to manage your homes and guests."}</p>
          <div class="auth-tabs" role="tablist" aria-label="Authentication options">
            <button class="auth-tab ${mode === "login" ? "active" : ""}" role="tab" aria-selected="${mode === "login"}" data-auth-mode="login">Sign in</button>
            <button class="auth-tab ${mode === "register" ? "active" : ""}" role="tab" aria-selected="${mode === "register"}" data-auth-mode="register">Register</button>
          </div>
          <form class="auth-form" id="auth-form" data-mode="${mode}">
            ${mode === "register" ? `<div class="field"><label for="full-name">Full name</label><input id="full-name" name="full_name" autocomplete="name" placeholder="Alex Morgan" minlength="2" required></div><div class="field"><label for="organization">Organization</label><input id="organization" name="organization_name" autocomplete="organization" placeholder="North Coast Stays" minlength="2" required></div>` : ""}
            <div class="field"><label for="email">Email address</label><input id="email" name="email" type="email" autocomplete="email" placeholder="alex@northcoaststays.com" required></div>
            <div class="field"><div class="password-row"><label for="password">Password</label><span>${mode === "register" ? "12 characters minimum" : ""}</span></div><input id="password" name="password" type="password" autocomplete="${mode === "register" ? "new-password" : "current-password"}" placeholder="••••••••••••" ${mode === "register" ? 'minlength="12"' : ""} required></div>
            <div class="form-error" id="form-error" role="alert"></div>
            <button class="btn btn-primary auth-submit" type="submit">${mode === "register" ? "Create workspace" : "Sign in"} ${icon("arrow", "icon icon-sm")}</button>
          </form>
          <div class="auth-divider">or explore first</div>
          <a class="btn btn-outline demo-button" href="/dashboard" data-link>Preview with sample data</a>
          <p class="auth-terms">By continuing, you agree to keep guest data safe and use StayOps responsibly.</p>
        </div>
      </section>
    </main>`;
}

function getThread(id) {
  for (const home of homes) {
    const guest = home.guests.find((item) => item.id === id);
    if (guest) return { guest, home };
  }
  return { guest: homes[0].guests[0], home: homes[0] };
}

function homeGroups() {
  return homes.map((home) => `
    <section class="home-group" data-home="${home.id}">
      <button class="home-toggle" type="button" aria-expanded="true"><span class="home-dot" style="background:${home.color}"></span><strong>${home.name}</strong><span class="home-count">${home.guests.length}</span>${icon("chevron", "icon icon-sm chevron")}</button>
      <div class="thread-list">${home.guests.map((guest) => `
        <button class="thread-button ${guest.id === state.selectedThread ? "active" : ""}" type="button" data-thread="${guest.id}">
          <span class="avatar" style="--avatar:${guest.avatar}">${guest.initials}${guest.handoff ? '<i class="alert-dot"></i>' : ""}</span>
          <span class="thread-copy"><span class="thread-name-row"><span class="thread-name">${guest.name}</span><span class="thread-time">${guest.time}</span></span><span class="thread-preview">${guest.preview}</span></span>
          ${guest.unread ? `<span class="thread-unread">${guest.unread}</span>` : ""}
        </button>`).join("")}</div>
    </section>`).join("");
}

function chatContent() {
  const { guest, home } = getThread(state.selectedThread);
  const conversation = conversations[guest.id];
  return `
    <header class="chat-head">
      <span class="avatar" style="--avatar:${guest.avatar}">${guest.initials}</span>
      <div class="chat-head-copy"><h2>${guest.name}</h2><div class="guest-meta"><span>${icon("home", "icon icon-sm")} ${home.name}</span><span>${icon("calendar", "icon icon-sm")} ${guest.dates}</span></div></div>
      <span class="status-pill ${conversation.handoff ? "handoff" : ""}">${conversation.handoff ? icon("alert", "icon icon-sm") : ""}${conversation.status}</span>
    </header>
    <div class="handoff-banner ${conversation.handoff ? "show" : ""}">${icon("alert", "icon icon-sm")}<div><strong>Human response needed</strong>${conversation.reason || ""}</div></div>
    <div class="messages" id="messages"><div class="day-divider">Today</div>${conversation.messages.map((message) => `
      <div class="message-row ${message.from === "guest" ? "" : "outgoing"} ${message.from === "ai" ? "assistant-message" : ""}"><div class="message-bubble">${message.from === "ai" ? `<span class="ai-label">${icon("spark", "icon icon-sm")} StayOps AI</span>` : ""}<div>${escapeHtml(message.text)}</div><div class="message-time">${escapeHtml(message.time)}</div></div></div>`).join("")}</div>
    <form class="chat-composer" id="chat-form"><div class="composer-box"><textarea id="message-input" rows="1" maxlength="10000" aria-label="Reply to ${guest.name}" placeholder="Reply to ${guest.name.split(" ")[0]}…"></textarea><button class="send-button" type="submit" aria-label="Send message">${icon("send", "icon icon-sm")}</button></div><p class="composer-note">Replies are sent as you. Sensitive actions still require confirmation.</p></form>`;
}

const dateFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
function isoDate(date) { return date.toISOString().slice(0, 10); }
function addDays(date, days) { const copy = new Date(date); copy.setUTCDate(copy.getUTCDate() + days); return copy; }
function calendarContent() {
  const anchor = new Date(Date.UTC(2026, 8, 14));
  const start = addDays(anchor, state.weekOffset * 7);
  const end = addDays(start, 6);
  const visibleReservations = reservations.filter((item) => new Date(`${item.start}T00:00:00Z`) <= end && new Date(`${item.end}T00:00:00Z`) >= start);
  const inHouse = visibleReservations.filter((item) => item.status === "In house").length;
  return `
    <div class="calendar-head"><h2>Reservation calendar</h2><div class="calendar-controls"><button class="icon-button" id="prev-week" type="button" aria-label="Previous week">${icon("left", "icon icon-sm")}</button><span class="calendar-range">${dateFmt.format(start)} – ${dateFmt.format(end)}, ${end.getUTCFullYear()}</span><button class="icon-button" id="next-week" type="button" aria-label="Next week">${icon("right", "icon icon-sm")}</button></div></div>
    <div class="calendar-summary"><div class="summary-stat"><strong>${visibleReservations.length}</strong><span>Reservations</span></div><div class="summary-stat"><strong>${inHouse}</strong><span>In house</span></div><div class="summary-stat"><strong>${homes.length}</strong><span>Homes</span></div></div>
    <div class="schedule" aria-label="Reservations by home for ${dateFmt.format(start)} to ${dateFmt.format(end)}">
      <div class="schedule-grid"><div class="schedule-cell schedule-head-cell"></div>${Array.from({length: 7}, (_, i) => { const day = addDays(start, i); return `<div class="schedule-cell schedule-head-cell ${isoDate(day) === "2026-09-14" ? "today-col" : ""}">${day.toLocaleDateString("en-US", {weekday:"short", timeZone:"UTC"})}<strong>${day.getUTCDate()}</strong></div>`; }).join("")}
      ${homes.map((home) => {
        const bars = visibleReservations.filter((item) => item.home === home.id).map((item) => {
          const reservationStart = new Date(`${item.start}T00:00:00Z`);
          const reservationEnd = new Date(`${item.end}T00:00:00Z`);
          const startIndex = Math.max(0, Math.round((reservationStart - start) / 86400000));
          const endIndex = Math.min(7, Math.round((reservationEnd - start) / 86400000));
          return `<div class="booking-bar ${item.color}" style="grid-column:${startIndex + 1}/${Math.max(startIndex + 2, endIndex + 1)}"><strong>${item.guest}</strong><span>${item.status}</span></div>`;
        }).join("");
        return `<div class="schedule-property"><strong>${home.short}</strong><span>${home.rooms} rooms</span></div><div class="booking-row">${bars}</div>`;
      }).join("")}</div>
    </div>
    <div class="calendar-legend">${homes.map((home) => `<span class="legend-item"><span class="home-dot" style="background:${home.color}"></span>${home.name}</span>`).join("")}</div>`;
}

function notificationPanel() {
  return `<div class="notification-panel ${state.notificationOpen ? "open" : ""}" id="notification-panel"><div class="notification-head"><strong>Handoffs & updates</strong><button type="button" id="mark-read">Mark all read</button></div>${notifications.map((item) => `<button class="notification-item ${state.readNotifications.has(item.id) ? "read" : ""}" type="button" data-notification="${item.id}" data-thread="${item.thread}"><span class="notify-dot"></span><span class="notification-copy"><strong>${item.title}</strong><span>${item.detail}</span></span><span class="notification-time">${item.time}</span></button>`).join("")}</div>`;
}

function dashboardPage() {
  const savedUser = JSON.parse(localStorage.getItem("stayops_user") || "null");
  const initials = savedUser?.full_name ? savedUser.full_name.split(/\s+/).map((part) => part[0]).slice(0,2).join("").toUpperCase() : "AM";
  const unread = notifications.filter((item) => !state.readNotifications.has(item.id)).length;
  return `
    <a class="skip-link" href="#dashboard-content">Skip to dashboard</a>
    <div class="dashboard-page"><div class="dashboard-shell">
      <aside class="side-rail" aria-label="Dashboard navigation">${brand(false).replace('<span class="brand-name">StayOps</span>', "")}<nav class="rail-nav"><button class="rail-button active" aria-label="Guest inbox" title="Guest inbox">${icon("message")}</button><button class="rail-button" aria-label="Calendar" title="Calendar" data-scroll-calendar>${icon("calendar")}</button><button class="rail-button" aria-label="Analytics" title="Analytics">${icon("chart")}</button><button class="rail-button" aria-label="Settings" title="Settings">${icon("settings")}</button></nav><button class="rail-profile" id="logout-button" aria-label="Sign out" title="Sign out">${escapeHtml(initials)}</button></aside>
      <main class="dashboard-main" id="dashboard-content">
        <header class="dash-header"><div class="dash-header-title"><h1>Guest operations</h1><span class="workspace-badge">${savedUser ? "Live workspace" : "Preview mode"}</span></div><div class="header-actions"><span class="date-chip">${icon("calendar", "icon icon-sm")} Monday, Sep 14</span><div class="notification-wrap"><button class="icon-button" id="notification-button" type="button" aria-label="Open handoff notifications" aria-expanded="${state.notificationOpen}">${icon("bell")}${unread ? `<span class="notification-count">${unread}</span>` : ""}</button>${notificationPanel()}</div></div></header>
        <div class="dashboard-content">
          <aside class="inbox-pane"><div class="pane-title"><h2>Guest inbox</h2><span class="filter-label">All homes</span></div><div id="home-groups">${homeGroups()}</div></aside>
          <section class="chat-pane" id="chat-pane" aria-label="Guest conversation">${chatContent()}</section>
          <section class="calendar-pane" id="reservation-calendar" aria-label="Reservation calendar">${calendarContent()}</section>
        </div>
      </main>
    </div></div>`;
}

function renderRoute() {
  const path = window.location.pathname.replace(/\/$/, "") || "/";
  if (path === "/auth") app.innerHTML = authPage();
  else if (path === "/dashboard") app.innerHTML = dashboardPage();
  else app.innerHTML = landingPage();
  bindEvents(path);
  document.title = path === "/dashboard" ? "Guest Operations — StayOps" : path === "/auth" ? "Sign in — StayOps" : "StayOps — Guest operations, in one place";
}

function bindEvents(path) {
  document.querySelectorAll("[data-link]").forEach((link) => link.addEventListener("click", (event) => {
    if (link.origin === window.location.origin) { event.preventDefault(); navigate(link.pathname + link.search); }
  }));

  if (path === "/auth") {
    document.querySelectorAll("[data-auth-mode]").forEach((tab) => tab.addEventListener("click", () => navigate(`/auth?mode=${tab.dataset.authMode}`)));
    document.querySelector("#auth-form")?.addEventListener("submit", handleAuth);
  }

  if (path === "/dashboard") {
    document.querySelectorAll(".home-toggle").forEach((toggle) => toggle.addEventListener("click", () => {
      const group = toggle.closest(".home-group");
      group.classList.toggle("collapsed");
      toggle.setAttribute("aria-expanded", String(!group.classList.contains("collapsed")));
    }));
    document.querySelectorAll(".thread-button").forEach((button) => button.addEventListener("click", () => selectThread(button.dataset.thread)));
    document.querySelector("#chat-form")?.addEventListener("submit", handleMessage);
    document.querySelector("#notification-button")?.addEventListener("click", (event) => {
      if (event.target.closest(".notification-panel")) return;
      state.notificationOpen = !state.notificationOpen;
      renderRoute();
    });
    document.querySelector("#mark-read")?.addEventListener("click", (event) => {
      event.stopPropagation();
      notifications.forEach((item) => state.readNotifications.add(item.id));
      renderRoute();
    });
    document.querySelectorAll("[data-notification]").forEach((button) => button.addEventListener("click", (event) => {
      event.stopPropagation();
      state.readNotifications.add(button.dataset.notification);
      state.notificationOpen = false;
      state.selectedThread = button.dataset.thread;
      renderRoute();
    }));
    document.querySelector("#prev-week")?.addEventListener("click", () => { state.weekOffset -= 1; refreshCalendar(); });
    document.querySelector("#next-week")?.addEventListener("click", () => { state.weekOffset += 1; refreshCalendar(); });
    document.querySelector("[data-scroll-calendar]")?.addEventListener("click", () => document.querySelector("#reservation-calendar")?.scrollIntoView({ behavior: "smooth" }));
    document.querySelector("#logout-button")?.addEventListener("click", handleLogout);
    setTimeout(() => { const messages = document.querySelector("#messages"); if (messages) messages.scrollTop = messages.scrollHeight; }, 0);
  }
}

function selectThread(threadId) {
  state.selectedThread = threadId;
  document.querySelectorAll(".thread-button").forEach((button) => button.classList.toggle("active", button.dataset.thread === threadId));
  const chatPane = document.querySelector("#chat-pane");
  if (chatPane) { chatPane.innerHTML = chatContent(); document.querySelector("#chat-form")?.addEventListener("submit", handleMessage); }
  setTimeout(() => { const messages = document.querySelector("#messages"); if (messages) messages.scrollTop = messages.scrollHeight; }, 0);
}

function refreshCalendar() {
  const pane = document.querySelector("#reservation-calendar");
  if (pane) { pane.innerHTML = calendarContent(); document.querySelector("#prev-week")?.addEventListener("click", () => { state.weekOffset -= 1; refreshCalendar(); }); document.querySelector("#next-week")?.addEventListener("click", () => { state.weekOffset += 1; refreshCalendar(); }); }
}

function handleMessage(event) {
  event.preventDefault();
  const input = document.querySelector("#message-input");
  const text = input.value.trim();
  if (!text) return;
  const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  conversations[state.selectedThread].messages.push({ from: "human", text, time: now });
  input.value = "";
  selectThread(state.selectedThread);
  toast("Reply added to the conversation");
}

async function handleAuth(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const mode = form.dataset.mode;
  const submit = form.querySelector("button[type='submit']");
  const error = form.querySelector("#form-error");
  const data = Object.fromEntries(new FormData(form));
  submit.disabled = true;
  submit.textContent = mode === "register" ? "Creating workspace…" : "Signing in…";
  error.classList.remove("show");
  try {
    const response = await fetch(`/api/v1/auth/${mode}`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "We couldn’t complete that request.");
    localStorage.setItem("stayops_token", result.access_token);
    localStorage.setItem("stayops_user", JSON.stringify(result.user));
    navigate("/dashboard");
    toast(mode === "register" ? "Workspace created. Welcome to StayOps." : "Welcome back.");
  } catch (err) {
    error.textContent = err.message || "Unable to connect. Try again in a moment.";
    error.classList.add("show");
    submit.disabled = false;
    submit.innerHTML = `${mode === "register" ? "Create workspace" : "Sign in"} ${icon("arrow", "icon icon-sm")}`;
  }
}

async function handleLogout() {
  try { await fetch("/api/v1/auth/logout", { method: "POST", credentials: "include" }); } catch (_) { /* local sign-out still succeeds */ }
  localStorage.removeItem("stayops_token");
  localStorage.removeItem("stayops_user");
  navigate("/");
  toast("You’re signed out.");
}

window.addEventListener("popstate", renderRoute);
renderRoute();
