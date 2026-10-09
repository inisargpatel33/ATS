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
