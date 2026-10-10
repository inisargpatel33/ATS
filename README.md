# 🎓 SmartSched Uni - AI-Powered Academic Timetable Engine

**SmartSched Uni** is a full-stack SaaS platform designed to solve the University Timetabling Problem (an NP-Hard Constraint Satisfaction Problem) using an asynchronous AI scheduling engine to generate clash-free schedules while optimizing resources.

---

## 🌟 Why is this helpful?

Manually scheduling classes leads to human error and overworked faculty. SmartSched Uni acts as an intelligent command center that saves hundreds of hours, provides predictive resource management, and syncs timetables to calendar applications.

---

## 🚀 Key Features

- 🧠 **Asynchronous AI Engine:** Runs multiple scenarios in parallel as background tasks.
- 🛡️ **Pre-Flight Validation:** Alerts admins if a schedule is physically impossible before running computations.
- 🖱️ **Interactive Grid:** Drag-and-drop interface with real-time conflict validation.
- 💡 **Smart Slot Recommendations:** Suggests times, rooms, and professors to resolve bottlenecks.
- 📊 **Predictive Analytics:** Features workload distributions, health scores, and capacity warnings.
- 📅 **Calendar Sync:** Generates `.ics` files and integrates with messaging webhooks.

---

## 💻 Tech Stack

- **Backend:** Python 3.9+, FastAPI, Google OR-Tools (CP-SAT Solver), Psycopg2, Bcrypt.
- **Frontend:** HTML5, Vanilla JavaScript, Tailwind CSS, Chart.js.
- **Database:** PostgreSQL.

---

## ⚙️ Architecture & Setup

The system uses Constraint Programming to model scheduling constraints (no double-bookings, workload limits, room capacities, and block lectures).

To run locally:

1. Clone the repository and set up a virtual environment.
2. Install dependencies via `pip install -r requirements.txt`.
3. Configure your PostgreSQL database named `smartsched` and update the connection string.
4. Run the server using `uvicorn main:app --reload --port 8000` and access
   `http://127.0.0.1:8000/`. If port 8000 is already in use, run
   `uvicorn main:app --reload --port 8001` and use the matching URL.

## Telegram live communication

The Telegram integration is opt-in and routes every message by the subscription's
`role` and `target_id`; a student subscribed to one batch cannot receive another
batch's targeted alerts.

1. Create a bot with BotFather and set these environment variables (never commit
   the token):

   ```env
   TELEGRAM_BOT_TOKEN=your_bot_token
   TELEGRAM_WEBHOOK_SECRET=a-long-random-secret
   ```

2. Run the schema initialization so it creates `telegram_subscriptions` and
   `telegram_handshakes`.
3. From an authenticated admin session, configure the webhook:
   `POST /telegram/configure-webhook` with
   `{"public_url":"https://your-public-api.example.com"}`.
4. Add student records through the batch administration page with a PRN and name,
   or import a CSV containing `prn,name` columns. A student sends `/start`, selects
   **Student**, and replies with the registered PRN. The bot verifies the PRN,
   greets the student by name, and shows the student menu. An incorrect PRN is
   rejected without creating a subscription. Faculty records can include a
   four-digit `security_pin`; faculty members select **Faculty** and verify with
   `Faculty ID PIN` such as `12 8492`.
5. Verified students receive options for next lecture, today's classes, full week,
   and profile. **Full Week** sends a PDF timetable containing the same schedule
   fields shown in the timetable portal: day, time, subject, room, and faculty.
   Faculty can view their schedule, report leave, and claim substitution bounties.

Telegram must be able to reach the deployed HTTPS endpoint. For local testing,
use an HTTPS tunnel such as ngrok or Cloudflare Tunnel. The webhook returns
quickly and processes the update in a FastAPI background task.
