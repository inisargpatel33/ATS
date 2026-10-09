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
4. Run the server using `uvicorn main:app --reload --port 8000` and access `http://127.0.0.1:8000/`.

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
4. A student sends `/start`, then replies with the exact batch name (for example
   `BCA-Sem3`). The backend stores the Telegram `chat_id` against that batch.
   Faculty can link with `/faculty <faculty_id>`.
5. Students can send `/next` (or “Where is my next lecture?”). Publishing a
   timetable notifies only its affected batches, and moving a timetable slot
   notifies only that slot's batch.

Telegram must be able to reach the deployed HTTPS endpoint. For local testing,
use an HTTPS tunnel such as ngrok or Cloudflare Tunnel. The webhook returns
quickly and processes the update in a FastAPI background task.
