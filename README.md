# 🌟 Flowline — Modern Queue & Appointment SaaS for Service Businesses
A fully independent, real-world software product that unifies walk-ins, appointments, and real-time queue management.  
Not a tutorial project — a complete SaaS system built from scratch.

---

# 🚨 Flowline solves this
- 📅 **Unified timeline** — scheduled appointments and spontaneous walk-ins appear together on a live FullCalendar timeline  
- 📱 **QR check-in** — customers scan a QR code at the entrance, join the queue, and see their position & wait time in real time  
- ⏱️ **Dynamic wait-time calculation** — based on active appointments, service durations, and queue length  
- 📧 **Automated reminders** — email & SMS reminders (SMS planned) at 1 week, 1 day, and 3 hours before appointments  
- ⚡ **Instant updates** — every status change is broadcast across all devices via WebSockets  

---

# 🛠️ Tech Stack
| Layer | Technology |
|-------|------------|
| 🐍 Backend | Python, Flask, Flask-Login, Flask-Bcrypt |
| ⚡ Realtime | Flask-SocketIO (WebSockets) |
| 🗄️ Database | SQLite + SQLAlchemy ORM |
| 🎨 Frontend | HTML, Tailwind CSS, JavaScript |
| 📆 Calendar | FullCalendar.js |
| 📧 Email | smtplib, HTML emails |
| 🔒 Auth | Session-based authentication with bcrypt |

---

# ✨ Features

## 👑 For the salon owner
- 🗓️ Unified timeline — appointments + walk-ins in one FullCalendar view, drag-and-drop rescheduling  
- 👥 Live queue dashboard — who is waiting, who is being served, average wait time  
- ➕ Walk-in management — add customers manually or let them self-register via QR code  
- 🔔 No-show prevention — automated reminders at 1 week, 1 day, and 3 hours  
- ✅ Smart status tracking — pending → confirmed → in progress → completed / no-show  
- ⚙️ Settings — change email/password with verification codes, manage services, delete account   

## 👤 For the customer
- 📲 QR check-in — scan, enter name & service, join instantly  
- 👀 Live queue position — real-time position & estimated wait time on mobile  

## 🚧 Planned (Premium tier)
- 💳 Stripe deposit for no-show protection  
- 📱 SMS notifications via Twilio  
- 👥 Multi-staff support  
- 📊 Analytics dashboard  
- 🔁 Customer reactivation 

---

# 🏗️ Development Process

## Phase 1 — Core Scheduling  
Basic Flask routes, SQLite schema, FullCalendar drag-and-drop (eventDrop, eventResize), conflict detection, and appointment status logic.

## Phase 2 — Walk-in Queue Algorithm  
Designed a dynamic queue system:  
`build_timeline()` and `find_free_slot()` compute the earliest available slot for each walk-in based on active appointments and queued customers.

## Phase 3 — Real-time Updates  
Integrated Flask-SocketIO with provider-specific rooms.  
Solved race conditions between HTTP load and WebSocket connection on page refresh.

## Phase 4 — Authentication & Security  
Email verification (4-digit code, 5-minute expiry), bcrypt hashing, Flask-Login session management.

## Phase 5 — SQLAlchemy ORM Migration  
Migrated from raw SQL to a relational ORM schema.  
Separated provider data into multiple tables for structure + GDPR compliance.  
Handled lazy loading, connection pooling, timezone-aware datetimes.

## Phase 6 — Settings & Onboarding  
Google-style settings page with tabbed navigation.  
Onboarding requires providers to set up at least one service before accessing the dashboard.

## Phase 7 — Final Polish (current)  
Once all logic is complete:  
- **AI-generated CSS & UI polish** to give Flowline a modern SaaS look  
- Backend, database architecture, and product logic remain fully hand-built  
- AI handles only the visual styling (Tailwind optimization, layout, spacing, UI consistency)

---

# 📚 What I Learned
- Full-stack architecture  
- Real-time systems (WebSockets)  
- Relational database design  
- Timezone handling (UTC storage, naive vs. aware)  
- SQLAlchemy ORM (relationships)  
- Authentication security  
- Product thinking (competitor analysis: Fresha, Booksy)

---

# 🎯 Mission
Provide small service businesses with a tool that is:

- simple enough to use on day one  
- powerful enough to replace their existing workflow  
- affordable enough for single-chair barbershops  

Not another enterprise platform with a 60-page onboarding guide — a focused tool that solves real problems.

---

# 📊 Project Status
| Feature | Status |
|--------|--------|
| Appointment scheduling | ✅ Done |
| Walk-in queue management | ✅ Done |
| Real-time WebSocket updates | ✅ Done |
| Email verification flows | ✅ Done |
| Settings page | ✅ Done |
| SQLAlchemy ORM migration | ✅ Done |
| Onboarding flow | ✅ Done |
| QR self-registration | 🚧 In progress |
| SMS reminders | 📋 Planned |
| Analytics dashboard | 📋 Planned |
| Multi-staff support | 📋 Planned |

---

# 🔧 Installation
```bash
git clone https://github.com/Shxyex/flowline.git
cd flowline/myPersonalProject
pip install -r requirements.txt

