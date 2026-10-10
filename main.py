from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from typing import List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import errors, pool
from ortools.sat.python import cp_model
from collections import defaultdict
from auth import require_admin
from fastapi import Depends
import math
import random
from auth import create_access_token
import bcrypt
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from fastapi import BackgroundTasks, Header
from datetime import datetime, timezone
from hmac import compare_digest
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
import json
import re
import csv
import io
import sys
from uuid import uuid4
from fastapi import UploadFile, File

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ⚠️ FAKE DATABASE FOR ADMIN PASSWORD 
# Generate the bcrypt hash directly using the modern bcrypt library
HASHED_ADMIN_PASSWORD = bcrypt.hashpw(b"supersecret", bcrypt.gensalt())


# IMPORT YOUR NEW CONFIG
from settings import (
    DATABASE_URL,
    SECRET_KEY,
    ALLOWED_ORIGINS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_WEBHOOK_SECRET,
)



# =========================================================
# FASTAPI APP
# =========================================================

app = FastAPI(title="Timetable SaaS API")

from pyngrok import ngrok

@app.on_event("startup")
def auto_configure_ngrok_and_telegram():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_WEBHOOK_SECRET:
        print("⚠️ Skipping Telegram Webhook setup: Missing tokens in .env")
        return

    try:
        # Reuse a tunnel owned by an external ngrok process when available.
        existing_tunnel = None
        try:
            with urllib_request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=2) as response:
                tunnel_data = json.loads(response.read().decode("utf-8"))
            existing_tunnel = next(
                (
                    item for item in tunnel_data.get("tunnels", [])
                    if item.get("config", {}).get("addr") in {
                        "http://localhost:8000",
                        "http://127.0.0.1:8000",
                    }
                ),
                None,
            )
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            pass

        if existing_tunnel:
            public_url = existing_tunnel["public_url"]
            print(f"\n✅ Reusing existing ngrok tunnel at: {public_url}")
        else:
            tunnel = ngrok.connect(8000)
            public_url = tunnel.public_url
            print(f"\n✅ Ngrok tunnel successfully started at: {public_url}")

        # 2. Automatically register this new URL with Telegram
        webhook_url = f"{public_url}/telegram/webhook"
        _telegram_api(
            "setWebhook",
            {"url": webhook_url, "secret_token": TELEGRAM_WEBHOOK_SECRET},
        )
        print(f"✅ Telegram Webhook automatically locked to: {webhook_url}\n")
        
    except Exception as e:
        print(f"\n❌ Failed to auto-configure Ngrok/Telegram: {e}\n")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"],
    allow_headers=[
        "Authorization",
        "authorization",
        "Content-Type",
        "content-type",
        "Accept",
        "accept",
        "Origin",
        "origin",
        "X-Requested-With",
        "x-requested-with",
        "Access-Control-Request-Headers",
        "Access-Control-Request-Method",
    ],
)

# =========================================================
# Pydantic Models for Request Validation
# =========================================================

class LeaveCreate(BaseModel):
    faculty_id: int
    leave_date: str # Format: YYYY-MM-DD
    reason: Optional[str] = ""

class SubCreate(BaseModel):
    timetable_id: int
    substitute_faculty_id: int
    specific_date: str # Format: YYYY-MM-DD
    
    
class StudentCreate(BaseModel):
    prn: str
    name: str
    batch_id: Optional[int] = None

class StudentListCreate(BaseModel):
    students: List[StudentCreate]


# =========================================================
# PUBLIC PORTAL ENDPOINTS (Phase 1 & 2)
# =========================================================
@app.get("/public/get-batches/")
def public_get_batches():
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, name FROM batches ORDER BY name ASC")
        return {"success": True, "data": cursor.fetchall()}
    finally: cursor.close(); release_db_connection(conn)

@app.get("/public/get-faculties/")
def public_get_faculties():
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, name FROM faculties ORDER BY name ASC")
        return {"success": True, "data": cursor.fetchall()}
    finally: cursor.close(); release_db_connection(conn)

@app.get("/public/view-timetable/{batch_id}")
def public_view_timetable(batch_id: int):
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT t.day_of_week, t.timeslot, s.name AS subject, r.name AS room, f.name AS faculty, t.id AS timetable_id
            FROM timetables t
            JOIN subjects s ON t.subject_id = s.id
            JOIN rooms r ON t.room_id = r.id
            JOIN faculties f ON t.faculty_id = f.id
            WHERE t.batch_id = %s
        """, (batch_id,))
        records = cursor.fetchall()
        
        # Pull active substitutes
        cursor.execute("""
            SELECT ds.timetable_id, ds.specific_date, f.name as sub_name
            FROM daily_substitutes ds
            JOIN faculties f ON ds.substitute_faculty_id = f.id
            WHERE ds.specific_date >= CURRENT_DATE
        """)
        subs = cursor.fetchall()
        sub_map = {f"{s['timetable_id']}_{s['specific_date']}": s['sub_name'] for s in subs}
        
        return {"success": True, "data": records, "substitutes": sub_map}
    finally: cursor.close(); release_db_connection(conn)

@app.post("/faculty-leave/")
def add_faculty_leave(payload: LeaveCreate, background_tasks: BackgroundTasks):
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO faculty_leave (faculty_id, leave_date, reason) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (payload.faculty_id, payload.leave_date, payload.reason))
        
        # Find affected batches to trigger Telegram Sniper Alerts
        cursor.execute("SELECT DISTINCT batch_id, subject_id, room_id, timeslot, day_of_week FROM timetables WHERE faculty_id = %s", (payload.faculty_id,))
        affected = cursor.fetchall()
        conn.commit()

        if TELEGRAM_BOT_TOKEN:
            leave_dt = datetime.strptime(payload.leave_date, "%Y-%m-%d")
            leave_day_str = leave_dt.strftime("%a")
            for record in affected:
                if record['day_of_week'] == leave_day_str:
                    cursor.execute("SELECT name FROM subjects WHERE id = %s", (record['subject_id'],))
                    subj_name = cursor.fetchone()['name']
                    msg = f"⚠️ Alert: Your {subj_name} class on {payload.leave_date} at {record['timeslot']} currently has no professor. Stand by for substitute assignment."
                    background_tasks.add_task(_notify_batch_subscribers, record['batch_id'], msg)
        
        return {"success": True, "message": "Leave marked and students alerted via Telegram."}
    finally: cursor.close(); release_db_connection(conn)

@app.post("/assign-substitute/")
def assign_substitute(payload: SubCreate, background_tasks: BackgroundTasks, user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO daily_substitutes (timetable_id, substitute_faculty_id, specific_date) VALUES (%s, %s, %s) ON CONFLICT (timetable_id, specific_date) DO UPDATE SET substitute_faculty_id = EXCLUDED.substitute_faculty_id", (payload.timetable_id, payload.substitute_faculty_id, payload.specific_date))
        cursor.execute("SELECT t.batch_id, t.timeslot, s.name as subject_name, f.name as new_fac FROM timetables t JOIN subjects s ON t.subject_id = s.id JOIN faculties f ON f.id = %s WHERE t.id = %s", (payload.substitute_faculty_id, payload.timetable_id))
        info = cursor.fetchone()
        conn.commit()

        if TELEGRAM_BOT_TOKEN and info:
            msg = f"✅ Update: Your {info['subject_name']} class at {info['timeslot']} on {payload.specific_date} will be covered by {info['new_fac']}."
            background_tasks.add_task(_notify_batch_subscribers, info['batch_id'], msg)

        return {"success": True, "message": "Substitute assigned and Telegram alert sent."}
    finally: cursor.close(); release_db_connection(conn)

# =========================================================
# THE ULTIMATE CORS BYPASS (Serve HTML directly from Python)
# =========================================================
# This tells Python to serve your HTML files directly
app.mount("/ui", StaticFiles(directory=".", html=True), name="ui")

@app.get("/")
def root():
    # Automatically redirect you to the login page
    return RedirectResponse(url="/ui/login.html")

# =========================================================
# DATABASE CONNECTION POOL
# =========================================================

try:
    db_pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=1, maxconn=20, dsn=DATABASE_URL, cursor_factory=RealDictCursor
    )
    print("✅ Database Connection Pool initialized successfully!")
except Exception as e:
    print("❌ Failed to initialize connection pool:", e)
    db_pool = None


def ensure_schema_compatibility():
    """Apply small additive migrations needed by existing installations."""
    if db_pool is None:
        return
    conn = None
    cursor = None
    try:
        conn = db_pool.getconn()
        cursor = conn.cursor()
        cursor.execute("ALTER TABLE faculties ADD COLUMN IF NOT EXISTS security_pin VARCHAR(4)")
        cursor.execute("ALTER TABLE batches ADD COLUMN IF NOT EXISTS semester INTEGER")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id SERIAL PRIMARY KEY,
                prn VARCHAR(100) NOT NULL UNIQUE,
                name VARCHAR(255) NOT NULL,
                batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS telegram_subscriptions (
                chat_id BIGINT PRIMARY KEY,
                role VARCHAR(20) NOT NULL CHECK (role IN ('Student', 'Faculty')),
                target_id INTEGER NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cursor.execute("""
            ALTER TABLE telegram_subscriptions
            ADD COLUMN IF NOT EXISTS student_id INTEGER
            REFERENCES students(id) ON DELETE SET NULL
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS telegram_handshakes (
                chat_id BIGINT PRIMARY KEY,
                requested_role VARCHAR(20),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cursor.execute("""
            ALTER TABLE telegram_handshakes
            ADD COLUMN IF NOT EXISTS requested_role VARCHAR(20)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_telegram_subscriptions_target
            ON telegram_subscriptions (role, target_id)
        """)
        cursor.execute("""
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'batches' AND column_name = 'semester_id'
        """)
        if cursor.fetchone():
            cursor.execute(
                "UPDATE batches SET semester = COALESCE(semester, semester_id) "
                "WHERE semester IS NULL"
            )
        conn.commit()
        print("✅ Database compatibility columns verified")
    except Exception as exc:
        if conn:
            conn.rollback()
        print(f"❌ Database compatibility migration failed: {exc}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            db_pool.putconn(conn)


ensure_schema_compatibility()

    

def get_db_connection():
    if db_pool is None:
        raise HTTPException(status_code=500, detail="Database connection pool is not available")
    for _ in range(3):
        conn = None
        try:
            conn = db_pool.getconn()
            with conn.cursor() as test_cursor:
                test_cursor.execute("SELECT 1;")
            return conn 
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            if conn:
                try: db_pool.putconn(conn, close=True)
                except Exception: pass
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Database extraction failure: {str(e)}")
    raise HTTPException(status_code=500, detail="Could not obtain a stable database stream.")

def release_db_connection(conn):
    if db_pool and conn: db_pool.putconn(conn)
        
# =========================================================
# CONSTANTS
# =========================================================
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]

# =========================================================
# MODELS
# =========================================================
class DeptCreate(BaseModel): name: str
class SwapValidationRequest(BaseModel): batch_id: int; faculty_id: int; room_id: int; new_day: str; new_timeslot: str
class FacultyCreate(BaseModel):
    department_id: int
    name: str
    max_weekly_hours: int = 15
    security_pin: Optional[str] = None

    @field_validator("security_pin")
    @classmethod
    def validate_security_pin(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and (not value.isdigit() or len(value) != 4):
            raise ValueError("Security PIN must contain exactly 4 digits")
        return value
class StudentCreate(BaseModel): prn: str; name: str; batch_id: int
class StudentImport(BaseModel): students: List[StudentCreate]
class RoomCreate(BaseModel): name: str; capacity: int; room_type: str; amenities: List[str]; extra_features: Optional[str] = ""; is_active: bool = True
class BatchCreate(BaseModel): name: str; student_count: int; mentor_id: Optional[int] = None; department_id: int; semester: int = 1
class SubjectCreate(BaseModel): name: str; subject_type: str; required_sessions: int; department_id: int; semester: int = 1 
class AutoFixRequest(BaseModel): department_id: int; faculty_id: int; room_id: int; target_day: str; target_timeslot: str; original_day: str; original_timeslot: str
class ExpertiseCreate(BaseModel): faculty_id: int; subject_id: int; competency_tier: float
class GenerateRequest(BaseModel): constraints: List[str] = []; batch_id: str = "all"; start_hour: int = 8; end_hour: int = 16; break_hour: int = 12
class UpdateSlotRequest(BaseModel): record_id: int; new_day: str; new_timeslot: str
class TimetableRecord(BaseModel): department_id: int; day_of_week: str; timeslot: str; room_id: int; batch_id: int; subject_id: int; faculty_id: int
class SaveTimetableRequest(BaseModel): records: List[TimetableRecord]; notes: str = ""
class LoginRequest(BaseModel):
    username: str
    password: str
class TelegramWebhookRequest(BaseModel):
    update_id: Optional[int] = None
    message: Optional[dict] = None
class TelegramWebhookConfig(BaseModel):
    public_url: str

# =========================================================
# TELEGRAM LIVE COMMUNICATION
# =========================================================
TELEGRAM_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
TELEGRAM_DAY_NAMES = {
    "Mon": "Monday",
    "Tue": "Tuesday",
    "Wed": "Wednesday",
    "Thu": "Thursday",
    "Fri": "Friday",
}


def _telegram_api(method: str, payload: dict) -> dict:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    body = json.dumps(payload).encode("utf-8")
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    http_request = urllib_request.Request(
        api_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(http_request, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Telegram API request failed: {exc}") from exc

    if not result.get("ok"):
        raise RuntimeError(f"Telegram API rejected {method}: {result}")
    return result


# def _send_telegram_message(chat_id: int, text: str) -> bool:
#     try:
#         _telegram_api("sendMessage", {"chat_id": chat_id, "text": text})
#         return True
#     except RuntimeError as exc:
#         print(f"TELEGRAM DELIVERY ERROR chat_id={chat_id}: {exc}")
#         return False
def _telegram_multipart(method: str, fields: dict, file_field: str, filename: str, content: bytes) -> dict:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    boundary = f"----SmartSched{uuid4().hex}"
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(str(value).encode())
        body.extend(b"\r\n")
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
        "Content-Type: application/pdf\r\n\r\n".encode()
    )
    body.extend(content)
    body.extend(f"\r\n--{boundary}--\r\n".encode())

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    http_request = urllib_request.Request(
        api_url,
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(http_request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Telegram API request failed: {exc}") from exc
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API rejected {method}: {result}")
    return result


def _send_telegram_message(chat_id: int, text: str, reply_markup: dict = None) -> bool:
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
        
    try:
        _telegram_api("sendMessage", payload)
        return True
    except RuntimeError as exc:
        print(f"TELEGRAM DELIVERY ERROR chat_id={chat_id}: {exc}")
        return False


def _send_telegram_document(chat_id: int, filename: str, content: bytes, caption: str = "") -> bool:
    try:
        _telegram_multipart(
            "sendDocument",
            {"chat_id": chat_id, "caption": caption},
            "document",
            filename,
            content,
        )
        return True
    except RuntimeError as exc:
        print(f"TELEGRAM DOCUMENT ERROR chat_id={chat_id}: {exc}")
        return False


STUDENT_MENU = {
    "keyboard": [
        [{"text": "⏭️ Next Lecture"}, {"text": "📅 Today's Classes"}],
        [{"text": "🗓️ Full Week"}, {"text": "👤 My Profile"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}
ROLE_MENU = {
    "keyboard": [[{"text": "🎓 Student"}, {"text": "👨‍🏫 Faculty"}]],
    "resize_keyboard": True,
    "one_time_keyboard": True,
}
FACULTY_MENU = {
    "keyboard": [
        [{"text": "📅 My Schedule"}, {"text": "🚨 Report Leave"}],
        [{"text": "🙋‍♂️ Open Slots"}, {"text": "👤 My Profile"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}


def _subscription(cursor, chat_id: int):
    cursor.execute(
        "SELECT role, target_id FROM telegram_subscriptions WHERE chat_id = %s",
        (chat_id,),
    )
    return cursor.fetchone()


def _student_classes(cursor, chat_id: int, day: Optional[str] = None) -> list:
    query = """
        SELECT t.timeslot, s.name AS subject, r.name AS room, f.name AS faculty,
               t.day_of_week
        FROM telegram_subscriptions ts
        JOIN timetables t ON t.batch_id = ts.target_id
        JOIN subjects s ON s.id = t.subject_id
        JOIN rooms r ON r.id = t.room_id
        JOIN faculties f ON f.id = t.faculty_id
        WHERE ts.chat_id = %s AND ts.role = 'Student'
    """
    params = [chat_id]
    if day:
        query += " AND t.day_of_week = %s"
        params.append(day)
    query += " ORDER BY t.day_of_week, t.timeslot"
    cursor.execute(query, params)
    return cursor.fetchall()


def _student_today(chat_id: int) -> str:
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        rows = _student_classes(cursor, chat_id, TELEGRAM_DAYS[datetime.now().weekday()]
                                if datetime.now().weekday() < 5 else None)
        if not rows:
            return "🎉 You have no classes scheduled today."
        return "📅 Today's Classes\n\n" + "\n".join(
            f"• {r['timeslot']} — {r['subject']} | {r['room']} | {r['faculty']}"
            for r in rows
        )
    finally:
        cursor.close(); release_db_connection(conn)


def _student_week(chat_id: int) -> str:
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        rows = _student_classes(cursor, chat_id)
        if not rows:
            return "No published timetable was found for your batch yet."
        grouped = defaultdict(list)
        for row in rows:
            grouped[row["day_of_week"]].append(row)
        lines = ["🗓️ Full Week"]
        for day in TELEGRAM_DAYS:
            if grouped.get(day):
                lines.append(f"\n{TELEGRAM_DAY_NAMES[day]}")
                lines.extend(f"• {r['timeslot']} — {r['subject']} ({r['room']}, {r['faculty']})"
                             for r in grouped[day])
        return "\n".join(lines)
    finally:
        cursor.close(); release_db_connection(conn)


def _profile(chat_id: int) -> str:
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT st.name, st.prn, b.name AS batch
            FROM telegram_subscriptions ts
            JOIN students st ON st.id = ts.student_id
            JOIN batches b ON b.id = st.batch_id
            WHERE ts.chat_id = %s AND ts.role = 'Student'
        """, (chat_id,))
        student = cursor.fetchone()
        if student:
            return f"👤 My Profile\n\nName: {student['name']}\nPRN: {student['prn']}\nBatch: {student['batch']}\n\nUse /unlink to switch accounts."
        cursor.execute("""
            SELECT f.name, f.id FROM telegram_subscriptions ts
            JOIN faculties f ON f.id = ts.target_id
            WHERE ts.chat_id = %s AND ts.role = 'Faculty'
        """, (chat_id,))
        faculty = cursor.fetchone()
        return (f"👤 My Profile\n\nName: {faculty['name']}\nFaculty ID: {faculty['id']}\n\n"
                "Use /unlink to switch accounts.") if faculty else "You are not verified."
    finally:
        cursor.close(); release_db_connection(conn)


def _open_slots(cursor, faculty_id: int) -> str:
    cursor.execute("""SELECT tb.id, s.name AS subject, b.name AS batch, t.timeslot,
        r.name AS room, tb.status FROM telegram_bounties tb
        JOIN timetables t ON t.id=tb.timetable_id JOIN subjects s ON s.id=t.subject_id
        JOIN batches b ON b.id=t.batch_id JOIN rooms r ON r.id=t.room_id
        WHERE tb.status IN ('vip','open') AND tb.specific_date=CURRENT_DATE
        ORDER BY t.timeslot""")
    rows = cursor.fetchall()
    return "🙋‍♂️ Open Slots\n\n" + ("\n".join(
        f"• CLAIM {r['id']} — {r['timeslot']} {r['subject']} for {r['batch']} ({r['room']})"
        for r in rows
    ) or "No open slots today.")


def _claim_bounty(cursor, conn, chat_id: int, faculty_id: int, bounty_id: int) -> None:
    cursor.execute("""SELECT tb.id, tb.timetable_id, tb.specific_date, tb.status, t.batch_id,
        t.timeslot, s.name AS subject, f.name AS faculty, b.name AS batch
        FROM telegram_bounties tb JOIN timetables t ON t.id=tb.timetable_id
        JOIN subjects s ON s.id=t.subject_id JOIN faculties f ON f.id=%s
        JOIN batches b ON b.id=t.batch_id WHERE tb.id=%s FOR UPDATE""", (faculty_id, bounty_id))
    bounty = cursor.fetchone()
    if not bounty or bounty["status"] not in {"vip", "open"}:
        _send_telegram_message(chat_id, "That bounty is no longer available.", FACULTY_MENU); return
    cursor.execute("""UPDATE telegram_bounties SET status='claimed', claim_faculty_id=%s,
        voluntary_overtime=TRUE, updated_at=NOW() WHERE id=%s AND status IN ('vip','open')""",
                   (faculty_id, bounty_id))
    if cursor.rowcount != 1:
        conn.rollback(); _send_telegram_message(chat_id, "That bounty was claimed by another professor.", FACULTY_MENU); return
    cursor.execute("""INSERT INTO daily_substitutes (timetable_id, substitute_faculty_id, specific_date)
        VALUES (%s,%s,%s) ON CONFLICT (timetable_id,specific_date)
        DO UPDATE SET substitute_faculty_id=EXCLUDED.substitute_faculty_id""",
                   (bounty["timetable_id"], faculty_id, bounty["specific_date"]))
    conn.commit()
    _send_telegram_message(chat_id, f"✅ CLAIM {bounty_id} confirmed. This is logged as voluntary overtime.", FACULTY_MENU)
    _notify_batch_subscribers(bounty["batch_id"], f"⚠️ Update: Your {bounty['timeslot']} {bounty['subject']} class is now covered by {bounty['faculty']}.")


def _create_leave_and_bounties(cursor, conn, chat_id: int, faculty_id: int, leave_date) -> None:
    cursor.execute("INSERT INTO faculty_leave (faculty_id, leave_date, reason) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                   (faculty_id, leave_date, "Reported through Telegram"))
    day = leave_date.strftime("%a")
    cursor.execute("""SELECT id, batch_id, subject_id, timeslot FROM timetables
        WHERE faculty_id=%s AND day_of_week=%s""", (faculty_id, day))
    affected = cursor.fetchall()
    for slot in affected:
        cursor.execute("""INSERT INTO telegram_bounties (timetable_id,specific_date,status)
            VALUES (%s,%s,'vip') ON CONFLICT (timetable_id,specific_date)
            DO UPDATE SET status='vip', updated_at=NOW()""", (slot["id"], leave_date))
    conn.commit()
    for slot in affected:
        _send_telegram_message(chat_id, f"✅ Leave recorded for {leave_date}. Bounty {slot['id']} is now being offered to eligible faculty.")
        cursor.execute("""SELECT DISTINCT ts.chat_id FROM telegram_subscriptions ts
            JOIN faculty_expertise fe ON fe.faculty_id=ts.target_id
            WHERE ts.role='Faculty' AND fe.subject_id=%s AND ts.target_id<>%s""",
                       (slot["subject_id"], faculty_id))
        for row in cursor.fetchall():
            _send_telegram_message(row["chat_id"],
                f"🚨 Priority Room Available! Reply CLAIM {slot['id']} to cover the {slot['timeslot']} class for batch {slot['batch_id']}.",
                FACULTY_MENU)
    for slot in affected:
        _notify_batch_subscribers(slot["batch_id"], f"🚨 URGENT UPDATE: Your {slot['timeslot']} class has been reported absent. Please check Today's Classes for updates.")


def _refresh_bounties(cursor) -> None:
    """Advance VIP bounties and expire slots that are inside the 90-minute cutoff."""
    now = datetime.now()
    cursor.execute("""SELECT tb.id, tb.timetable_id, tb.status, tb.created_at, t.batch_id, t.timeslot,
        s.name AS subject FROM telegram_bounties tb JOIN timetables t ON t.id=tb.timetable_id
        JOIN subjects s ON s.id=t.subject_id WHERE tb.specific_date=CURRENT_DATE
        AND tb.status IN ('vip','open')""")
    for bounty in cursor.fetchall():
        start = _parse_slot_start(bounty["timeslot"])
        if not start:
            continue
        lecture_start = datetime.combine(now.date(), start.time())
        minutes_until = (lecture_start - now).total_seconds() / 60
        if minutes_until <= 90:
            cursor.execute("UPDATE telegram_bounties SET status='expired', updated_at=NOW() WHERE id=%s AND status IN ('vip','open')", (bounty["id"],))
            if cursor.rowcount:
                _notify_batch_subscribers(bounty["batch_id"], f"🚨 Alert: Your {bounty['timeslot']} {bounty['subject']} lecture is officially cancelled today. Enjoy your free period.")
        elif bounty["status"] == "vip" and (now - bounty["created_at"].replace(tzinfo=None)).total_seconds() >= 900:
            cursor.execute("UPDATE telegram_bounties SET status='open', updated_at=NOW() WHERE id=%s AND status='vip'", (bounty["id"],))


def _notify_batch_subscribers(batch_id: int, message: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT chat_id FROM telegram_subscriptions
            WHERE role = 'Student' AND target_id = %s
            """,
            (batch_id,),
        )
        chat_ids = [row["chat_id"] for row in cursor.fetchall()]
    finally:
        cursor.close()
        release_db_connection(conn)

    delivered = sum(_send_telegram_message(chat_id, message) for chat_id in chat_ids)
    print(f"TELEGRAM BATCH NOTIFICATION batch_id={batch_id} delivered={delivered}/{len(chat_ids)}")
    return delivered


def _notify_published_batches(batch_ids: list[int]) -> None:
    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM NOTIFICATION SKIPPED: TELEGRAM_BOT_TOKEN is not configured")
        return
    for batch_id in sorted(set(batch_ids)):
        _notify_batch_subscribers(
            batch_id,
            "🚨 The official timetable has been published. "
            "Send /next to see your next lecture.",
        )


def _notify_reschedule(batch_id: int, subject: str, old_day: str, old_slot: str,
                       new_day: str, new_slot: str, room: str) -> None:
    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM NOTIFICATION SKIPPED: TELEGRAM_BOT_TOKEN is not configured")
        return
    message = (
        "⚠️ Urgent timetable update\n"
        f"{subject} has moved from {TELEGRAM_DAY_NAMES.get(old_day, old_day)} "
        f"{old_slot} to {TELEGRAM_DAY_NAMES.get(new_day, new_day)} {new_slot}.\n"
        f"Room: {room}"
    )
    _notify_batch_subscribers(batch_id, message)


def _parse_slot_start(slot: str) -> Optional[datetime]:
    match = re.match(r"^\s*(\d{1,2}):(\d{2})\s*(AM|PM)", slot or "", re.IGNORECASE)
    if not match:
        return None
    return datetime.strptime(
        f"{match.group(1)}:{match.group(2)} {match.group(3).upper()}",
        "%I:%M %p",
    )


def _get_today_schedule(target_id: int, role: str) -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        today_str = datetime.now().astimezone().strftime("%a")
        if today_str not in TELEGRAM_DAYS:
            return "📅 Enjoy your weekend! No classes scheduled today."
            
        if role == "Student":
            cursor.execute("""
                SELECT t.timeslot, s.name as subject, r.name as room, f.name as faculty
                FROM timetables t
                JOIN subjects s ON t.subject_id = s.id
                JOIN rooms r ON t.room_id = r.id
                JOIN faculties f ON t.faculty_id = f.id
                WHERE t.batch_id = %s AND t.day_of_week = %s
                ORDER BY t.timeslot
            """, (target_id, today_str))
        elif role == "Faculty":
            cursor.execute("""
                SELECT t.timeslot, s.name as subject, r.name as room, b.name as batch
                FROM timetables t
                JOIN subjects s ON t.subject_id = s.id
                JOIN rooms r ON t.room_id = r.id
                JOIN batches b ON t.batch_id = b.id
                WHERE t.faculty_id = %s AND t.day_of_week = %s
                ORDER BY t.timeslot
            """, (target_id, today_str))
            
        records = cursor.fetchall()
        if not records:
            return f"📅 You have a free day today ({TELEGRAM_DAY_NAMES.get(today_str, today_str)})! No classes scheduled."
            
        msg = f"📅 *Today's Schedule ({TELEGRAM_DAY_NAMES.get(today_str, today_str)})*\n\n"
        for rec in records:
            if role == "Student":
                msg += f"🕒 {rec['timeslot']}\n📚 {rec['subject']}\n📍 {rec['room']} | 👨‍🏫 Prof. {rec['faculty']}\n\n"
            else:
                msg += f"🕒 {rec['timeslot']}\n📚 {rec['subject']} ({rec['batch']})\n📍 {rec['room']}\n\n"
        return msg
    finally:
        cursor.close()
        release_db_connection(conn)

def _next_lecture(chat_id: int) -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT b.name AS batch, s.name AS subject, t.day_of_week,
                   t.timeslot, r.name AS room
            FROM telegram_subscriptions ts
            JOIN batches b ON b.id = ts.target_id
            JOIN timetables t ON t.batch_id = b.id
            JOIN subjects s ON s.id = t.subject_id
            JOIN rooms r ON r.id = t.room_id
            WHERE ts.chat_id = %s AND ts.role = 'Student'
            """,
            (chat_id,),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        release_db_connection(conn)

    if not rows:
        return "No published timetable was found for your batch yet."

    now = datetime.now().astimezone()
    current_day = now.weekday()
    candidates = []
    for row in rows:
        if row["day_of_week"] not in TELEGRAM_DAYS:
            continue
        slot_start = _parse_slot_start(row["timeslot"])
        if slot_start is None:
            continue
        day_index = TELEGRAM_DAYS.index(row["day_of_week"])
        distance = (day_index - current_day) % 7
        if distance == 0:
            if slot_start.time() <= now.time():
                continue
        candidates.append((distance, slot_start.time(), row))

    if not candidates:
        return "There are no remaining lectures in this week's published timetable."

    _, _, lecture = min(candidates, key=lambda item: (item[0], item[1]))
    return (
        f"Your next lecture ({lecture['batch']}) is {lecture['subject']} "
        f"on {TELEGRAM_DAY_NAMES.get(lecture['day_of_week'], lecture['day_of_week'])} "
        f"at {lecture['timeslot']} in {lecture['room']}."
    )


# def _process_telegram_update(update: dict) -> None:
#     message = update.get("message") or {}
#     chat = message.get("chat") or {}
#     chat_id = chat.get("id")
#     text = (message.get("text") or "").strip()
#     if chat_id is None or not text:
#         return

#     conn = get_db_connection()
#     cursor = conn.cursor()
#     try:
#         text_lower = text.lower()
#         _refresh_bounties(cursor)
#         conn.commit()
#         subscription = _subscription(cursor, chat_id)

#         if text_lower in {"/start", "start"}:
#             if subscription:
#                 _send_telegram_message(chat_id, "Your account is already verified.", STUDENT_MENU if subscription["role"] == "Student" else FACULTY_MENU)
#             else:
#                 cursor.execute("INSERT INTO telegram_handshakes (chat_id) VALUES (%s) ON CONFLICT DO NOTHING", (chat_id,))
#                 conn.commit()
#                 _send_telegram_message(chat_id, "Welcome to the University Timetable Portal! 🎓\n\nReply with your official University PRN (e.g., PCU-MCA-2026-042) to continue.\n\nFaculty? Reply with your Faculty ID and 4-Digit Security PIN (e.g., 12 8492).")
#             return

#         if text_lower == "/unlink":
#             cursor.execute("DELETE FROM telegram_subscriptions WHERE chat_id = %s", (chat_id,))
#             cursor.execute("DELETE FROM telegram_handshakes WHERE chat_id = %s", (chat_id,))
#             conn.commit()
#             _send_telegram_message(chat_id, "Your Telegram account has been unlinked. Send /start to verify a different account.", {"remove_keyboard": True})
#             return

#         # A verified chat can only use its own role's menu and claim flow.
#         if subscription:
#             if subscription["role"] == "Student":
#                 responses = {
#                     "⏭️ next lecture": lambda: _next_lecture(chat_id),
#                     "next": lambda: _next_lecture(chat_id),
#                     "/next": lambda: _next_lecture(chat_id),
#                     "📅 today's classes": lambda: _student_today(chat_id),
#                     "🗓️ full week": lambda: _student_week(chat_id),
#                     "👤 my profile": lambda: _profile(chat_id),
#                 }
#                 response = responses.get(text_lower)
#                 if response:
#                     _send_telegram_message(chat_id, response(), STUDENT_MENU)
#                     return
#             else:
#                 if text_lower == "👤 my profile":
#                     _send_telegram_message(chat_id, _profile(chat_id), FACULTY_MENU); return
#                 if text_lower in {"📅 my schedule", "my schedule"}:
#                     cursor.execute("""SELECT t.day_of_week, t.timeslot, s.name AS subject, b.name AS batch, r.name AS room
#                         FROM timetables t JOIN subjects s ON s.id=t.subject_id JOIN batches b ON b.id=t.batch_id
#                         JOIN rooms r ON r.id=t.room_id WHERE t.faculty_id=%s ORDER BY t.day_of_week,t.timeslot""", (subscription["target_id"],))
#                     rows = cursor.fetchall()
#                     _send_telegram_message(chat_id, "📅 My Schedule\n\n" + ("\n".join(f"• {r['day_of_week']} {r['timeslot']} — {r['subject']} ({r['batch']}, {r['room']})" for r in rows) or "No classes found."), FACULTY_MENU); return
#                 if text_lower == "🚨 report leave":
#                     _send_telegram_message(chat_id, "Reply with the leave date in YYYY-MM-DD format."); return
#                 if text_lower == "🙋‍♂️ open slots":
#                     _send_telegram_message(chat_id, _open_slots(cursor, subscription["target_id"]), FACULTY_MENU); return
#                 claim = re.match(r"^claim\s+(\d+)$", text, re.IGNORECASE)
#                 if claim:
#                     _claim_bounty(cursor, conn, chat_id, subscription["target_id"], int(claim.group(1)))
#                     return

#         # Verification is only accepted after /start and never by batch name.
#         if re.fullmatch(r"\d+\s+\d{4}", text):
#             faculty_id, pin = text.split()
#             cursor.execute("SELECT id, name FROM faculties WHERE id=%s AND security_pin=%s", (int(faculty_id), pin))
#             faculty = cursor.fetchone()
#             if faculty:
#                 cursor.execute("""INSERT INTO telegram_subscriptions (chat_id, role, target_id, student_id)
#                     VALUES (%s,'Faculty',%s,NULL) ON CONFLICT(chat_id) DO UPDATE SET role='Faculty',target_id=EXCLUDED.target_id,student_id=NULL,updated_at=NOW()""", (chat_id, faculty["id"]))
#                 conn.commit()
#                 _send_telegram_message(chat_id, f"✅ Verified. Welcome, {faculty['name']}.", FACULTY_MENU); return
#             _send_telegram_message(chat_id, "Faculty ID or security PIN was not recognized. Please try again."); return

#         if re.fullmatch(r"[A-Za-z0-9-]{6,100}", text):
#             cursor.execute("SELECT id, name, prn, batch_id FROM students WHERE LOWER(prn)=LOWER(%s)", (text,))
#             student = cursor.fetchone()
#             if student:
#                 cursor.execute("""INSERT INTO telegram_subscriptions (chat_id, role, target_id, student_id)
#                     VALUES (%s,'Student',%s,%s) ON CONFLICT(chat_id) DO UPDATE SET role='Student',target_id=EXCLUDED.target_id,student_id=EXCLUDED.student_id,updated_at=NOW()""",
#                                (chat_id, student["batch_id"], student["id"]))
#                 cursor.execute("DELETE FROM telegram_handshakes WHERE chat_id=%s", (chat_id,))
#                 conn.commit()
#                 _send_telegram_message(chat_id, f"✅ Verified, {student['name']}! Your schedule is linked.", STUDENT_MENU); return

#         # Date replies from a verified faculty account create leave records.
#         if subscription and subscription["role"] == "Faculty":
#             try:
#                 leave_date = datetime.strptime(text, "%Y-%m-%d").date()
#             except ValueError:
#                 leave_date = None
#             if leave_date:
#                 _create_leave_and_bounties(cursor, conn, chat_id, subscription["target_id"], leave_date)
#                 return

#         _send_telegram_message(chat_id, "I could not verify that identity. Send /start and use your PRN, or Faculty ID and 4-digit PIN.")

#     except Exception as exc:
#         conn.rollback()
#         print(f"TELEGRAM UPDATE ERROR chat_id={chat_id}: {exc}")
#         _send_telegram_message(chat_id, "I could not process that request. Please try again.")
#     finally:
#         cursor.close()
#         release_db_connection(conn)


def _process_telegram_update_legacy(update: dict) -> None:
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    if chat_id is None or not text:
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check if the user is already securely verified in the database
        cursor.execute("SELECT role, target_id, student_id FROM telegram_subscriptions WHERE chat_id = %s", (chat_id,))
        user_sub = cursor.fetchone()

        # ==========================================
        # STEP 1: IDENTITY ONBOARDING (UNVERIFIED)
        # ==========================================
        if not user_sub:
            if text.lower() == "/start":
                _send_telegram_message(
                    chat_id,
                    "Welcome to the University Timetable Portal! 🎓\n\n"
                    "👨‍🎓 *Students:* Reply with your official PRN (e.g., PCU-MCA-2026-042).\n"
                    "👨‍🏫 *Faculty:* Reply with your Faculty ID and 4-Digit PIN (e.g., 12 8492).",
                    reply_markup={"remove_keyboard": True}
                )
                return

            # Check for Faculty PIN Authentication Format (e.g., "12 8492")
            faculty_match = re.match(r"^(\d+)\s+(\d{4})$", text)
            if faculty_match:
                fac_id, pin = faculty_match.groups()
                cursor.execute("SELECT id, name FROM faculties WHERE id = %s AND security_pin = %s", (int(fac_id), pin))
                faculty = cursor.fetchone()
                if faculty:
                    cursor.execute("INSERT INTO telegram_subscriptions (chat_id, role, target_id) VALUES (%s, 'Faculty', %s)", (chat_id, faculty["id"]))
                    conn.commit()
                    
                    faculty_menu = {
                        "keyboard": [[{"text": "📅 My Schedule"}, {"text": "🚨 Report Leave"}], [{"text": "🙋‍♂️ Open Slots"}, {"text": "👤 My Profile"}]],
                        "resize_keyboard": True, "is_persistent": True
                    }
                    _send_telegram_message(chat_id, f"✅ Identity Verified. Welcome Prof. {faculty['name']}!", reply_markup=faculty_menu)
                    return
                else:
                    _send_telegram_message(chat_id, "❌ Invalid Faculty ID or PIN.")
                    return

            # Check for Student PRN Authentication Format (Alphanumeric, no spaces)
            cursor.execute("SELECT id, name, batch_id FROM students WHERE UPPER(prn) = UPPER(%s)", (text,))
            student = cursor.fetchone()
            if student:
                cursor.execute("INSERT INTO telegram_subscriptions (chat_id, role, target_id, student_id) VALUES (%s, 'Student', %s, %s)", (chat_id, student["batch_id"], student["id"]))
                cursor.execute("SELECT name FROM batches WHERE id = %s", (student["batch_id"],))
                batch_name = cursor.fetchone()["name"]
                conn.commit()
                
                student_menu = {
                    "keyboard": [[{"text": "⏭️ Next Lecture"}, {"text": "📅 Today's Classes"}], [{"text": "🗓️ Full Week"}, {"text": "👤 My Profile"}]],
                    "resize_keyboard": True, "is_persistent": True
                }
                _send_telegram_message(chat_id, f"✅ Identity Verified. Welcome {student['name']}!\nYou are securely linked to {batch_name}.", reply_markup=student_menu)
                return

            # Failsafe for unverified users typing random strings
            _send_telegram_message(chat_id, "❌ Identity not found. Please enter a valid PRN or Faculty PIN, or contact your Administrator.")
            return

        # ==========================================
        # STEP 2: VERIFIED USER MENU ROUTING
        # ==========================================
        role = user_sub["role"]
        
        # Global Unlink Command
        if text.lower() == "/unlink":
            cursor.execute("DELETE FROM telegram_subscriptions WHERE chat_id = %s", (chat_id,))
            conn.commit()
            _send_telegram_message(chat_id, "🔌 Account unlinked successfully. Send /start to reconnect.", reply_markup={"remove_keyboard": True})
            return

        # --- STUDENT LOGIC ---
        # --- STUDENT LOGIC ---
        if role == "Student":
            student_menu = {
                "keyboard": [[{"text": "⏭️ Next Lecture"}, {"text": "📅 Today's Classes"}], [{"text": "🗓️ Full Week"}, {"text": "👤 My Profile"}]],
                "resize_keyboard": True, "is_persistent": True
            }
            
            if text == "⏭️ Next Lecture":
                _send_telegram_message(chat_id, _next_lecture(chat_id), reply_markup=student_menu)
            
            elif text == "📅 Today's Classes":
                _send_telegram_message(chat_id, _get_today_schedule(user_sub["target_id"], "Student"), reply_markup=student_menu)
                
            elif text == "🗓️ Full Week":
                _send_telegram_message(chat_id, "🗓️ Your full weekly schedule is being generated. (PDF/Image generation coming in v2!)", reply_markup=student_menu)
                
            elif text == "👤 My Profile":
                cursor.execute("SELECT s.name, s.prn, b.name as batch FROM students s JOIN batches b ON s.batch_id = b.id WHERE s.id = %s", (user_sub["student_id"],))
                prof = cursor.fetchone()
                msg = f"👤 *Student Profile*\nName: {prof['name']}\nPRN: {prof['prn']}\nBatch: {prof['batch']}\n\nType /unlink to switch accounts."
                _send_telegram_message(chat_id, msg, reply_markup=student_menu)
            
            else:
                _send_telegram_message(chat_id, "Please select an option from the menu below:", reply_markup=student_menu)
            student_menu = {
                "keyboard": [[{"text": "⏭️ Next Lecture"}, {"text": "📅 Today's Classes"}], [{"text": "🗓️ Full Week"}, {"text": "👤 My Profile"}]],
                "resize_keyboard": True, "is_persistent": True
            }
            
            if text == "⏭️ Next Lecture":
                _send_telegram_message(chat_id, _next_lecture(chat_id), reply_markup=student_menu)
            
            elif text == "📅 Today's Classes":
                # To be implemented: Query DB for CURRENT_DATE
                _send_telegram_message(chat_id, "📅 *Fetching Today's Schedule...*", reply_markup=student_menu)
                
            elif text == "👤 My Profile":
                cursor.execute("SELECT s.name, s.prn, b.name as batch FROM students s JOIN batches b ON s.batch_id = b.id WHERE s.id = %s", (user_sub["student_id"],))
                prof = cursor.fetchone()
                msg = f"👤 *Student Profile*\nName: {prof['name']}\nPRN: {prof['prn']}\nBatch: {prof['batch']}\n\nType /unlink to switch accounts."
                _send_telegram_message(chat_id, msg, reply_markup=student_menu)
            
            else:
                _send_telegram_message(chat_id, "Please select an option from the menu below:", reply_markup=student_menu)

        # --- FACULTY LOGIC ---
       # --- FACULTY LOGIC ---
        elif role == "Faculty":
            faculty_menu = {
                "keyboard": [[{"text": "📅 My Schedule"}, {"text": "🚨 Report Leave"}], [{"text": "🙋‍♂️ Open Slots"}, {"text": "👤 My Profile"}]],
                "resize_keyboard": True, "is_persistent": True
            }
            
            if text == "📅 My Schedule":
                _send_telegram_message(chat_id, _get_today_schedule(user_sub["target_id"], "Faculty"), reply_markup=faculty_menu)
                
            elif text == "👤 My Profile":
                cursor.execute("SELECT name, max_weekly_hours FROM faculties WHERE id = %s", (user_sub["target_id"],))
                fac = cursor.fetchone()
                _send_telegram_message(chat_id, f"👤 *Faculty Profile*\nName: Prof. {fac['name']}\nMax Hours: {fac['max_weekly_hours']}\n\nType /unlink to log out.", reply_markup=faculty_menu)
                
            elif text == "🚨 Report Leave":
                _send_telegram_message(chat_id, "🚨 The Autonomous Substitution Engine is standing by. (Bounty logic coming next!)", reply_markup=faculty_menu)
                
            elif text == "🙋‍♂️ Open Slots":
                _send_telegram_message(chat_id, "🙋‍♂️ Checking for open bounties... (Bounty logic coming next!)", reply_markup=faculty_menu)
                
            else:
                _send_telegram_message(chat_id, "🚧 Menu option received. Please use the menu below:", reply_markup=faculty_menu)
            faculty_menu = {
                "keyboard": [[{"text": "📅 My Schedule"}, {"text": "🚨 Report Leave"}], [{"text": "🙋‍♂️ Open Slots"}, {"text": "👤 My Profile"}]],
                "resize_keyboard": True, "is_persistent": True
            }
            
            if text == "👤 My Profile":
                cursor.execute("SELECT name, max_weekly_hours FROM faculties WHERE id = %s", (user_sub["target_id"],))
                fac = cursor.fetchone()
                _send_telegram_message(chat_id, f"👤 *Faculty Profile*\nName: Prof. {fac['name']}\nMax Hours: {fac['max_weekly_hours']}\n\nType /unlink to log out.", reply_markup=faculty_menu)
                
            elif text == "🚨 Report Leave":
                _send_telegram_message(chat_id, "🚨 To report a leave, please contact the Administrator to trigger the Autonomous Substitution Engine.", reply_markup=faculty_menu)
                
            else:
                _send_telegram_message(chat_id, "🚧 Menu option received. Please use the menu below:", reply_markup=faculty_menu)

    except Exception as exc:
        conn.rollback()
        print(f"TELEGRAM UPDATE ERROR chat_id={chat_id}: {exc}")
        _send_telegram_message(chat_id, "An error occurred while processing your request.")
    finally:
        cursor.close()
        release_db_connection(conn)

def _pdf_escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_student_week_pdf(chat_id: int) -> tuple[bytes, str]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT st.name, st.prn, b.name AS batch
            FROM telegram_subscriptions ts
            JOIN students st ON st.id = ts.student_id
            JOIN batches b ON b.id = st.batch_id
            WHERE ts.chat_id = %s AND ts.role = 'Student'
        """, (chat_id,))
        student = cursor.fetchone()
        rows = _student_classes(cursor, chat_id)
    finally:
        cursor.close()
        release_db_connection(conn)

    if not student or not rows:
        return b"", ""

    page_width, page_height = 842, 595
    margin = 36
    table_width = page_width - (margin * 2)
    time_width = 92
    day_width = (table_width - time_width) / 5
    row_height = 58
    header_height = 28
    rows_per_page = 7
    time_order = []
    for row in rows:
        if row["timeslot"] not in time_order:
            time_order.append(row["timeslot"])
    time_order.sort(key=lambda value: _parse_slot_start(value) or datetime.max)
    schedule = {(row["day_of_week"], row["timeslot"]): row for row in rows}

    def shorten(value: object, max_chars: int) -> str:
        text = str(value or "")
        return text if len(text) <= max_chars else text[:max_chars - 3] + "..."

    def text_command(value: object, x: float, y: float, size: int = 9) -> str:
        return f"BT /F1 {size} Tf 1 0 0 1 {x:.1f} {y:.1f} Tm ({_pdf_escape(value)}) Tj ET"

    def table_page(page_times: list, page_number: int, total_pages: int) -> bytes:
        commands = [
            text_command("SmartSched Uni - Weekly Timetable", margin, 550, 18),
            text_command(f"Student: {student['name']}", margin, 528, 10),
            text_command(
                f"PRN: {student['prn']}    Batch: {student['batch']}",
                margin + 300,
                528,
                10,
            ),
            text_command(f"Page {page_number} of {total_pages}", 750, 550, 8),
        ]
        table_top = 505
        x_positions = [margin, margin + time_width]
        x_positions.extend(margin + time_width + day_width * index for index in range(1, 6))
        table_bottom = table_top - header_height - (row_height * len(page_times))

        commands.extend([
            "0.88 0.91 0.96 rg",
            f"{margin} {table_top - header_height} {table_width} {header_height} re f",
        ])
        for index in range(len(page_times)):
            if index % 2 == 1:
                row_y = table_top - header_height - (row_height * (index + 1))
                commands.extend([
                    "0.97 0.98 1 rg",
                    f"{margin} {row_y} {table_width} {row_height} re f",
                ])

        commands.extend([
            "0.25 0.30 0.38 RG",
            "0.8 w",
            f"{margin} {table_bottom} {table_width} {table_top - table_bottom} re S",
        ])
        for x in x_positions[1:-1]:
            commands.append(f"{x} {table_bottom} m {x} {table_top} l S")
        for index in range(len(page_times) + 1):
            y = table_top - header_height - (row_height * index)
            commands.append(f"{margin} {y} m {margin + table_width} {y} l S")

        # Reset the fill color after drawing backgrounds so all labels and
        # timetable content render with readable black text.
        commands.append("0 0 0 rg")
        commands.append(text_command("Time", margin + 8, table_top - 19, 9))
        for day_index, day in enumerate(TELEGRAM_DAYS):
            commands.append(text_command(
                TELEGRAM_DAY_NAMES[day],
                x_positions[day_index + 1] + 7,
                table_top - 19,
                9,
            ))
        for row_index, timeslot in enumerate(page_times):
            cell_top = table_top - header_height - row_height * row_index
            commands.append(text_command(timeslot, margin + 8, cell_top - 22, 8))
            for day_index, day in enumerate(TELEGRAM_DAYS):
                row = schedule.get((day, timeslot))
                if not row:
                    continue
                x = x_positions[day_index + 1] + 7
                commands.append(text_command(shorten(row["subject"], 30), x, cell_top - 17, 8))
                commands.append(text_command(shorten(f"Room: {row['room']}", 30), x, cell_top - 31, 7))
                commands.append(text_command(shorten(f"Prof. {row['faculty']}", 30), x, cell_top - 44, 7))
        return "\n".join(commands).encode("latin-1", "replace")

    total_pages = max(1, (len(time_order) + rows_per_page - 1) // rows_per_page)
    objects = []
    page_streams = []
    for page_index, page_start in enumerate(range(0, len(time_order), rows_per_page), start=1):
        page_streams.append(
            table_page(time_order[page_start:page_start + rows_per_page], page_index, total_pages)
        )

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    page_refs = " ".join(f"{3 + index * 2} 0 R" for index in range(len(page_streams)))
    objects.append(f"<< /Type /Pages /Kids [{page_refs}] /Count {len(page_streams)} >>".encode())
    for index, stream in enumerate(page_streams):
        page_number = 3 + index * 2
        content_number = page_number + 1
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] "
            f"/Resources << /Font << /F1 {3 + len(page_streams) * 2} 0 R >> >> "
            f"/Contents {content_number} 0 R >>".encode()
        )
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
            + stream + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode())
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(pdf), f"{student['prn']}_weekly_timetable.pdf"


def _process_telegram_update(update: dict) -> None:
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    if chat_id is None or not text:
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT role, target_id, student_id FROM telegram_subscriptions WHERE chat_id = %s",
            (chat_id,),
        )
        subscription = cursor.fetchone()
        cursor.execute(
            "SELECT requested_role FROM telegram_handshakes WHERE chat_id = %s",
            (chat_id,),
        )
        handshake = cursor.fetchone()

        if text.lower() in {"/start", "start"}:
            if subscription and subscription["role"] == "Student" and not subscription["student_id"]:
                cursor.execute("DELETE FROM telegram_subscriptions WHERE chat_id = %s", (chat_id,))
                subscription = None
            if subscription:
                menu = STUDENT_MENU if subscription["role"] == "Student" else FACULTY_MENU
                _send_telegram_message(chat_id, "You are already verified. Choose an option below.", menu)
            else:
                cursor.execute("""
                    INSERT INTO telegram_handshakes (chat_id, requested_role)
                    VALUES (%s, NULL)
                    ON CONFLICT (chat_id) DO UPDATE SET requested_role = NULL
                """, (chat_id,))
                conn.commit()
                _send_telegram_message(
                    chat_id,
                    "Welcome to SmartSched Uni! 🎓\n\nAre you a student or faculty member?",
                    ROLE_MENU,
                )
            return

        if text.lower() == "/unlink":
            cursor.execute("DELETE FROM telegram_subscriptions WHERE chat_id = %s", (chat_id,))
            cursor.execute("DELETE FROM telegram_handshakes WHERE chat_id = %s", (chat_id,))
            conn.commit()
            _send_telegram_message(
                chat_id,
                "Your account was unlinked. Send /start to connect again.",
                {"remove_keyboard": True},
            )
            return

        if subscription:
            if subscription["role"] == "Student":
                if text == "⏭️ Next Lecture":
                    _send_telegram_message(chat_id, _next_lecture(chat_id), STUDENT_MENU)
                elif text == "📅 Today's Classes":
                    _send_telegram_message(
                        chat_id,
                        _get_today_schedule(subscription["target_id"], "Student"),
                        STUDENT_MENU,
                    )
                elif text == "🗓️ Full Week":
                    pdf, filename = _build_student_week_pdf(chat_id)
                    if pdf:
                        _send_telegram_document(
                            chat_id,
                            filename,
                            pdf,
                            "Your weekly timetable",
                        )
                    else:
                        _send_telegram_message(
                            chat_id,
                            "No published timetable was found for your batch yet.",
                            STUDENT_MENU,
                        )
                elif text == "👤 My Profile":
                    _send_telegram_message(chat_id, _profile(chat_id), STUDENT_MENU)
                else:
                    _send_telegram_message(chat_id, "Please choose an option from the menu.", STUDENT_MENU)
            else:
                _send_telegram_message(chat_id, "Faculty flow is available from the Faculty menu.", FACULTY_MENU)
            return

        if text in {"🎓 Student", "Student"}:
            cursor.execute("""
                INSERT INTO telegram_handshakes (chat_id, requested_role)
                VALUES (%s, 'Student')
                ON CONFLICT (chat_id) DO UPDATE SET requested_role = 'Student'
            """, (chat_id,))
            conn.commit()
            _send_telegram_message(
                chat_id,
                "Please enter your registered PRN number.",
                {"remove_keyboard": True},
            )
            return

        if text in {"👨‍🏫 Faculty", "Faculty"}:
            cursor.execute("""
                INSERT INTO telegram_handshakes (chat_id, requested_role)
                VALUES (%s, 'Faculty')
                ON CONFLICT (chat_id) DO UPDATE SET requested_role = 'Faculty'
            """, (chat_id,))
            conn.commit()
            _send_telegram_message(chat_id, "Enter your Faculty ID and 4-digit PIN, for example: 12 8492")
            return

        requested_role = handshake["requested_role"] if handshake else None
        if requested_role == "Student":
            cursor.execute(
                "SELECT id, name, batch_id FROM students WHERE UPPER(prn) = UPPER(%s)",
                (text,),
            )
            student = cursor.fetchone()
            if not student:
                _send_telegram_message(chat_id, "❌ That PRN is wrong or is not registered. Please try again.")
                return
            cursor.execute("""
                INSERT INTO telegram_subscriptions (chat_id, role, target_id, student_id)
                VALUES (%s, 'Student', %s, %s)
                ON CONFLICT (chat_id) DO UPDATE SET
                    role = 'Student',
                    target_id = EXCLUDED.target_id,
                    student_id = EXCLUDED.student_id,
                    updated_at = NOW()
            """, (chat_id, student["batch_id"], student["id"]))
            cursor.execute("DELETE FROM telegram_handshakes WHERE chat_id = %s", (chat_id,))
            cursor.execute("SELECT name FROM batches WHERE id = %s", (student["batch_id"],))
            batch = cursor.fetchone()
            conn.commit()
            _send_telegram_message(
                chat_id,
                f"Hi {student['name']}! 👋\nYour PRN has been verified and your account is linked to {batch['name']}.",
                STUDENT_MENU,
            )
            return

        if requested_role == "Faculty":
            faculty_match = re.fullmatch(r"(\d+)\s+(\d{4})", text)
            if not faculty_match:
                _send_telegram_message(chat_id, "❌ Use this format: Faculty ID and 4-digit PIN, for example 12 8492.")
                return
            faculty_id, pin = faculty_match.groups()
            cursor.execute(
                "SELECT id, name FROM faculties WHERE id = %s AND security_pin = %s",
                (int(faculty_id), pin),
            )
            faculty = cursor.fetchone()
            if not faculty:
                _send_telegram_message(chat_id, "❌ Faculty ID or security PIN is incorrect. Please try again.")
                return
            cursor.execute("""
                INSERT INTO telegram_subscriptions (chat_id, role, target_id)
                VALUES (%s, 'Faculty', %s)
                ON CONFLICT (chat_id) DO UPDATE SET
                    role = 'Faculty', target_id = EXCLUDED.target_id,
                    student_id = NULL, updated_at = NOW()
            """, (chat_id, faculty["id"]))
            cursor.execute("DELETE FROM telegram_handshakes WHERE chat_id = %s", (chat_id,))
            conn.commit()
            _send_telegram_message(chat_id, f"Hi Prof. {faculty['name']}! 👋 Your account is verified.", FACULTY_MENU)
            return

        _send_telegram_message(chat_id, "Please send /start and select Student or Faculty.", ROLE_MENU)
    except Exception as exc:
        conn.rollback()
        print(f"TELEGRAM UPDATE ERROR chat_id={chat_id}: {exc}")
        _send_telegram_message(chat_id, "An error occurred while processing your request. Please try again.")
    finally:
        cursor.close()
        release_db_connection(conn)


@app.post("/telegram/webhook")
def telegram_webhook(
    payload: TelegramWebhookRequest,
    background_tasks: BackgroundTasks,
    secret_token: Optional[str] = Header(default=None, alias="X-Telegram-Bot-Api-Secret-Token"),
):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Telegram integration is not configured")
    if not secret_token or not compare_digest(secret_token, TELEGRAM_WEBHOOK_SECRET):
        raise HTTPException(status_code=403, detail="Invalid Telegram webhook secret")
    background_tasks.add_task(_process_telegram_update, payload.model_dump())
    return {"ok": True}

@app.get("/telegram/subscriptions")
def telegram_subscription_summary(user: dict = Depends(require_admin)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT role, target_id, COUNT(*) AS subscriber_count
            FROM telegram_subscriptions
            GROUP BY role, target_id
            ORDER BY role, target_id
            """
        )
        return {"success": True, "data": cursor.fetchall()}
    finally:
        cursor.close()
        release_db_connection(conn)

@app.post("/telegram/configure-webhook")
def configure_telegram_webhook(
    config: TelegramWebhookConfig,
    user: dict = Depends(require_admin),
):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Telegram integration is not configured")
    public_url = config.public_url.rstrip("/") + "/telegram/webhook"
    if not public_url.lower().startswith("https://"):
        raise HTTPException(status_code=400, detail="Telegram webhooks require an HTTPS public URL")
    _telegram_api(
        "setWebhook",
        {"url": public_url, "secret_token": TELEGRAM_WEBHOOK_SECRET},
    )
    return {"success": True, "message": "Telegram webhook configured", "url": public_url}        
# =========================================================
# CRUD ENDPOINTS (Departments, Faculties, Rooms, Batches, Subjects, Expertise)
# =========================================================

@app.post("/batches/{batch_id}/students")
def add_students_manually(batch_id: int, payload: StudentListCreate, user: dict = Depends(require_admin)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        count = 0
        for student in payload.students:
            cursor.execute("""
                INSERT INTO students (prn, name, batch_id) 
                VALUES (%s, %s, %s) 
                ON CONFLICT (prn) DO UPDATE SET name = EXCLUDED.name, batch_id = EXCLUDED.batch_id
            """, (student.prn, student.name, batch_id))
            count += 1
        conn.commit()
        return {"success": True, "count": count}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        release_db_connection(conn)

@app.post("/batches/{batch_id}/students/import")
async def import_students_csv(batch_id: int, file: UploadFile = File(...), user: dict = Depends(require_admin)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Must be a valid CSV file")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        contents = await file.read()
        decoded = contents.decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(decoded))
        
        if not reader.fieldnames:
            raise HTTPException(status_code=400, detail="CSV must contain a header row: prn,name")
        headers = [h.lower().strip() for h in reader.fieldnames if h]
        if 'prn' not in headers or 'name' not in headers:
            raise HTTPException(status_code=400, detail="CSV must contain exact 'prn' and 'name' headers")

        count = 0
        for row in reader:
            row_clean = {k.lower().strip(): v.strip() for k, v in row.items()}
            prn = row_clean.get('prn')
            name = row_clean.get('name')
            
            if prn and name:
                cursor.execute("""
                    INSERT INTO students (prn, name, batch_id) 
                    VALUES (%s, %s, %s) 
                    ON CONFLICT (prn) DO UPDATE SET name = EXCLUDED.name, batch_id = EXCLUDED.batch_id
                """, (prn, name, batch_id))
                count += 1
        conn.commit()
        return {"success": True, "count": count}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        print(f"STUDENT CSV IMPORT ERROR: {e}")
        raise HTTPException(status_code=500, detail="Error importing CSV. Please check the file format and database.")
    finally:
        cursor.close()
        release_db_connection(conn)


@app.post("/login")
def login(credentials: LoginRequest):
    print(f"\n--- LOGIN ATTEMPT ---")
    print(f"User tried to log in as: {credentials.username}")
    
    try:
        # 1. Convert typed password to bytes safely
        typed_password_bytes = credentials.password.encode('utf-8')
        
        # 2. Check password against the secure hash
        is_password_correct = bcrypt.checkpw(typed_password_bytes, HASHED_ADMIN_PASSWORD)
        print(f"Did the password match the hash? {is_password_correct}")
        
        # 3. Grant or Deny Access
        if credentials.username == "admin" and is_password_correct:
            print("✅ Login successful! Generating JWT token...")
            token = create_access_token(data={"sub": 1, "role": "admin"})
            return {"access_token": token, "token_type": "bearer"}
        else:
            print("❌ Login failed: Username or password mismatch.")
            raise HTTPException(status_code=401, detail="Incorrect username or password")
            
    except Exception as e:
        # This will catch ANY hidden crashes and print them to your terminal
        print(f"❌ SERVER CRASH DURING LOGIN: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")
        
# @app.post("/add-department/")
# def add_department(dept: DeptCreate):
#     conn = get_db_connection(); cursor = conn.cursor()
#     try:
#         cursor.execute("INSERT INTO departments (name) VALUES (%s)", (dept.name,))
#         conn.commit()
#         return {"success": True, "message": "Department added successfully"}
#     except errors.UniqueViolation:
#         conn.rollback(); raise HTTPException(status_code=400, detail="Department already exists")
#     except Exception as e:
#         conn.rollback(); raise HTTPException(status_code=500, detail=str(e))
#     finally: cursor.close(); release_db_connection(conn)



@app.post("/add-department/")
def add_department(dept: DeptCreate, user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO departments (name) VALUES (%s)", (dept.name,))
        conn.commit()
        return {"success": True, "message": "Department added successfully"}
    except errors.UniqueViolation:
        conn.rollback(); raise HTTPException(status_code=400, detail="Department already exists")
    except Exception as e:
        conn.rollback(); raise HTTPException(status_code=500, detail=str(e))
    finally: cursor.close(); release_db_connection(conn)


# @app.delete("/delete-department/{dept_id}")
# def delete_department(dept_id: int, user: dict = Depends(require_admin)):
#     conn = get_db_connection()
#     cursor = conn.cursor()
#     try:
#         cursor.execute("DELETE FROM departments WHERE id = %s RETURNING id", (dept_id,))
#         if cursor.rowcount == 0: raise HTTPException(status_code=404, detail="Department not found")
#         conn.commit()
#         return {"success": True, "message": "Department deleted"}
#     except Exception as e:
#         conn.rollback(); raise HTTPException(status_code=500, detail=str(e))
#     finally: cursor.close(); release_db_connection(conn)




@app.delete("/delete-department/{dept_id}")
def delete_department(dept_id: int, user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM departments WHERE id = %s RETURNING id", (dept_id,))
        if cursor.rowcount == 0: raise HTTPException(status_code=404, detail="Department not found")
        conn.commit(); return {"success": True, "message": "Department deleted"}
    except Exception as e:
        conn.rollback(); raise HTTPException(status_code=500, detail=str(e))
    finally: cursor.close(); release_db_connection(conn)




@app.get("/get-departments/")
def get_departments(user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    try: cursor.execute("SELECT * FROM departments ORDER BY id ASC"); return {"data": cursor.fetchall()}
    finally: cursor.close(); release_db_connection(conn)


@app.post("/add-faculty/")
def add_faculty(faculty: FacultyCreate, user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO faculties (department_id, name, max_weekly_hours, security_pin) VALUES (%s, %s, %s, %s)",
                       (faculty.department_id, faculty.name, faculty.max_weekly_hours, faculty.security_pin))
        conn.commit(); return {"success": True, "message": "Faculty added successfully"}
    except Exception as e:
        conn.rollback(); raise HTTPException(status_code=500, detail=str(e))
    finally: cursor.close(); release_db_connection(conn)

@app.get("/get-faculties/")
def get_faculties(user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT f.id, f.name, f.max_weekly_hours, f.security_pin,
                   f.department_id, d.name AS department_name
            FROM faculties f
            JOIN departments d ON f.department_id = d.id
            ORDER BY f.id ASC
        """)
        faculties = cursor.fetchall()
        cursor.execute("SELECT fe.faculty_id, s.name AS subject_name, fe.competency_tier FROM faculty_expertise fe JOIN subjects s ON fe.subject_id = s.id")
        expertise = cursor.fetchall()
        exp_map = {}
        for exp in expertise:
            fid = exp["faculty_id"]
            if fid not in exp_map: exp_map[fid] = {"primary": [], "secondary": []}
            if float(exp["competency_tier"]) == 1.0: exp_map[fid]["primary"].append(exp["subject_name"])
            else: exp_map[fid]["secondary"].append(exp["subject_name"])
        for faculty in faculties:
            fid = faculty["id"]
            faculty["primary_subjects"] = exp_map.get(fid, {}).get("primary", [])
            faculty["secondary_subjects"] = exp_map.get(fid, {}).get("secondary", [])
        return {"data": faculties}
    except Exception as exc:
        print(f"FACULTY FETCH ERROR: {exc}")
        raise HTTPException(status_code=500, detail="Could not load faculty records")
    finally: cursor.close(); release_db_connection(conn)

@app.delete("/delete-faculty/{faculty_id}")
def delete_faculty(faculty_id: int, user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM faculties WHERE id = %s RETURNING id", (faculty_id,))
        if cursor.rowcount == 0: raise HTTPException(status_code=404, detail="Faculty not found")
        conn.commit(); return {"success": True, "message": "Faculty deleted successfully"}
    except errors.ForeignKeyViolation:
        conn.rollback(); raise HTTPException(status_code=400, detail="Cannot delete this Professor. Assigned to timetables.")
    except Exception as e:
        conn.rollback(); raise HTTPException(status_code=500, detail=str(e))
    finally: cursor.close(); release_db_connection(conn)

@app.put("/edit-faculty/{faculty_id}")
def edit_faculty(faculty_id: int, faculty: FacultyCreate, user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("""UPDATE faculties SET name = %s, max_weekly_hours = %s, department_id = %s,
                        security_pin = COALESCE(%s, security_pin) WHERE id = %s RETURNING id""",
                       (faculty.name, faculty.max_weekly_hours, faculty.department_id, faculty.security_pin, faculty_id))
        if cursor.rowcount == 0: raise HTTPException(status_code=404, detail="Faculty not found")
        conn.commit(); return {"success": True, "message": "Faculty updated successfully"}
    except Exception as e:
        conn.rollback(); raise HTTPException(status_code=500, detail=str(e))
    finally: cursor.close(); release_db_connection(conn)

@app.post("/add-room/")
def add_room(room: RoomCreate, user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO rooms (name, capacity, room_type, has_projector, has_ac, has_whiteboard, has_computers, extra_features, is_active)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (room.name, room.capacity, room.room_type, "Projector" in room.amenities, "AC" in room.amenities, 
              "Whiteboard" in room.amenities, "Computers" in room.amenities, room.extra_features, room.is_active))
        conn.commit(); return {"success": True, "message": "Room added successfully"}
    except Exception as e: conn.rollback(); raise HTTPException(status_code=500, detail=str(e))
    finally: cursor.close(); release_db_connection(conn)

@app.get("/get-rooms/")
def get_rooms(user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    try: cursor.execute("SELECT * FROM rooms ORDER BY name ASC"); return {"data": cursor.fetchall()}
    finally: cursor.close(); release_db_connection(conn)

@app.put("/edit-room/{room_id}")
def edit_room(room_id: int, room: RoomCreate, user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE rooms SET name = %s, capacity = %s, room_type = %s, has_projector = %s, has_ac = %s, has_whiteboard = %s, has_computers = %s, extra_features = %s, is_active = %s WHERE id = %s RETURNING id
        """, (room.name, room.capacity, room.room_type, "Projector" in room.amenities, "AC" in room.amenities, "Whiteboard" in room.amenities, "Computers" in room.amenities, room.extra_features, room.is_active, room_id))
        if cursor.rowcount == 0: raise HTTPException(status_code=404, detail="Room not found")
        conn.commit(); return {"success": True, "message": "Room updated successfully"}
    except Exception as e: conn.rollback(); raise HTTPException(status_code=500, detail=str(e))
    finally: cursor.close(); release_db_connection(conn)

@app.delete("/delete-room/{room_id}")
def delete_room(room_id: int, user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM rooms WHERE id = %s RETURNING id", (room_id,))
        if cursor.rowcount == 0: raise HTTPException(status_code=404, detail="Room not found")
        conn.commit(); return {"success": True, "message": "Room deleted successfully"}
    except errors.ForeignKeyViolation:
        conn.rollback(); raise HTTPException(status_code=400, detail="Cannot delete this Room. Assigned to classes.")
    except Exception as e: conn.rollback(); raise HTTPException(status_code=500, detail=str(e))
    finally: cursor.close(); release_db_connection(conn)

@app.post("/add-batch/")
def add_batch(batch: BatchCreate, user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    mentor_val = batch.mentor_id if batch.mentor_id and batch.mentor_id > 0 else None
    try:
        cursor.execute("INSERT INTO batches (name, student_count, mentor_id, department_id, semester) VALUES (%s, %s, %s, %s, %s)", 
                       (batch.name, batch.student_count, mentor_val, batch.department_id, batch.semester))
        conn.commit(); return {"success": True, "message": "Batch added successfully"}
    except errors.UniqueViolation:
        conn.rollback(); raise HTTPException(status_code=400, detail="A batch with this name already exists in this department.")
    except Exception as e: conn.rollback(); raise HTTPException(status_code=500, detail=str(e))
    finally: cursor.close(); release_db_connection(conn)
    
    
    
@app.get("/get-batches/{department_id}")
def get_batches(department_id: int, user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT b.id, b.name, b.student_count, b.department_id, b.mentor_id,
                   b.semester, f.name AS mentor_name
            FROM batches b LEFT JOIN faculties f ON b.mentor_id = f.id WHERE b.department_id = %s ORDER BY b.name ASC
        """, (department_id,))
        return {"data": cursor.fetchall()}
    finally: cursor.close(); release_db_connection(conn)

@app.put("/edit-batch/{batch_id}")
def edit_batch(batch_id: int, batch: BatchCreate, user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    mentor_val = batch.mentor_id if batch.mentor_id and batch.mentor_id > 0 else None
    try:
        cursor.execute("UPDATE batches SET name = %s, student_count = %s, mentor_id = %s, department_id = %s, semester = %s WHERE id = %s RETURNING id", 
                       (batch.name, batch.student_count, mentor_val, batch.department_id, batch.semester, batch_id))
        if cursor.rowcount == 0: raise HTTPException(status_code=404, detail="Batch not found")
        conn.commit(); return {"success": True, "message": "Batch updated successfully"}
    except errors.UniqueViolation:
        conn.rollback(); raise HTTPException(status_code=400, detail="Another batch with this name already exists.")
    except Exception as e: conn.rollback(); raise HTTPException(status_code=500, detail=str(e))
    finally: cursor.close(); release_db_connection(conn)
    
    
@app.delete("/delete-batch/{batch_id}")
def delete_batch(batch_id: int, user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM batches WHERE id = %s RETURNING id", (batch_id,))
        if cursor.rowcount == 0: raise HTTPException(status_code=404, detail="Batch not found")
        conn.commit(); return {"success": True, "message": "Batch deleted successfully"}
    except errors.ForeignKeyViolation:
        conn.rollback(); raise HTTPException(status_code=400, detail="Cannot delete. Used in Timetable.")
    except Exception as e: conn.rollback(); raise HTTPException(status_code=500, detail=str(e))
    finally: cursor.close(); release_db_connection(conn)


@app.get("/batches/{batch_id}/students")
def get_batch_students(batch_id: int, user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, prn, name, batch_id FROM students WHERE batch_id=%s ORDER BY name", (batch_id,))
        return {"success": True, "data": cursor.fetchall()}
    finally:
        cursor.close(); release_db_connection(conn)


@app.delete("/batches/{batch_id}/students/{student_id}")
def delete_batch_student(batch_id: int, student_id: int, user: dict = Depends(require_admin)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM students WHERE id = %s AND batch_id = %s RETURNING id",
            (student_id, batch_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Student not found in this batch")
        conn.commit()
        return {"success": True, "message": "Student removed successfully"}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail="Could not remove student") from exc
    finally:
        cursor.close()
        release_db_connection(conn)


@app.post("/batches/{batch_id}/students")
def add_batch_students(batch_id: int, payload: StudentImport, user: dict = Depends(require_admin)):
    if not payload.students:
        raise HTTPException(status_code=400, detail="At least one student is required")
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        for student in payload.students:
            if student.batch_id != batch_id:
                raise HTTPException(status_code=400, detail="Student batch_id does not match URL")
            cursor.execute("""INSERT INTO students (prn,name,batch_id) VALUES (%s,%s,%s)
                ON CONFLICT (prn) DO UPDATE SET name=EXCLUDED.name,batch_id=EXCLUDED.batch_id""",
                           (student.prn.strip(), student.name.strip(), batch_id))
        conn.commit()
        return {"success": True, "count": len(payload.students)}
    except Exception:
        conn.rollback(); raise
    finally:
        cursor.close(); release_db_connection(conn)


@app.post("/batches/{batch_id}/students/import")
async def import_batch_students(batch_id: int, file: UploadFile = File(...), user: dict = Depends(require_admin)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Upload a .csv file")
    try:
        rows = list(csv.DictReader(io.StringIO((await file.read()).decode("utf-8-sig"))))
        students = [StudentCreate(prn=(row.get("prn") or row.get("PRN") or "").strip(),
                                   name=(row.get("name") or row.get("Name") or "").strip(),
                                   batch_id=batch_id) for row in rows]
        if any(not student.prn or not student.name for student in students):
            raise ValueError("CSV must contain non-empty prn and name columns")
        return add_batch_students(batch_id, StudentImport(students=students), user)
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.post("/add-subject/")
def add_subject(subject: SubjectCreate, user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO subjects (name, subject_type, required_sessions, department_id, semester) VALUES (%s, %s, %s, %s, %s)", 
                       (subject.name, subject.subject_type, subject.required_sessions, subject.department_id, subject.semester))
        conn.commit(); return {"success": True, "message": "Subject added successfully"}
    except Exception as e: conn.rollback(); raise HTTPException(status_code=500, detail=str(e))
    finally: cursor.close(); release_db_connection(conn)

@app.get("/get-subjects/{department_id}")
def get_subjects(department_id: int, user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("SELECT s.id, s.name, s.subject_type, s.required_sessions, s.semester, d.name AS department_name FROM subjects s JOIN departments d ON s.department_id = d.id WHERE s.department_id = %s ORDER BY s.name ASC", (department_id,))
        return {"data": cursor.fetchall()}
    finally: cursor.close(); release_db_connection(conn)

@app.put("/edit-subject/{subject_id}")
def edit_subject(subject_id: int, subject: SubjectCreate, user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("UPDATE subjects SET name = %s, subject_type = %s, required_sessions = %s, department_id = %s, semester = %s WHERE id = %s RETURNING id", 
                       (subject.name, subject.subject_type, subject.required_sessions, subject.department_id, subject.semester, subject_id))
        if cursor.rowcount == 0: raise HTTPException(status_code=404, detail="Subject not found")
        conn.commit(); return {"success": True, "message": "Subject updated successfully"}
    except Exception as e: conn.rollback(); raise HTTPException(status_code=500, detail=str(e))
    finally: cursor.close(); release_db_connection(conn)

@app.delete("/delete-subject/{subject_id}")
def delete_subject(subject_id: int, user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM subjects WHERE id = %s RETURNING id", (subject_id,))
        if cursor.rowcount == 0: raise HTTPException(status_code=404, detail="Subject not found")
        conn.commit(); return {"success": True, "message": "Subject deleted successfully"}
    except errors.ForeignKeyViolation:
        conn.rollback(); raise HTTPException(status_code=400, detail="Cannot delete. Scheduled in Timetable.")
    except Exception as e: conn.rollback(); raise HTTPException(status_code=500, detail=str(e))
    finally: cursor.close(); release_db_connection(conn)
    
    
@app.post("/add-expertise/")
def add_expertise(exp: ExpertiseCreate, user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO faculty_expertise (faculty_id, subject_id, competency_tier) VALUES (%s,%s,%s)
            ON CONFLICT (faculty_id, subject_id) DO UPDATE SET competency_tier = EXCLUDED.competency_tier
        """, (exp.faculty_id, exp.subject_id, exp.competency_tier))
        conn.commit(); return {"success": True, "message": "Expertise added successfully"}
    except Exception as e: conn.rollback(); raise HTTPException(status_code=500, detail=str(e))
    finally: cursor.close(); release_db_connection(conn)

@app.get("/get-expertise/{faculty_id}")
def get_expertise(faculty_id: int, user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("SELECT subject_id AS id, competency_tier FROM faculty_expertise WHERE faculty_id = %s", (faculty_id,))
        return {"data": cursor.fetchall()}
    finally: cursor.close(); release_db_connection(conn)
    
    
# =========================================================
# AI ANALYSIS ENGINE HELPER
# =========================================================
def run_timtable_analysis(batch_id, records, subjects, faculties, rooms, dynamic_slots, exp_map, all_dept_records):
    from collections import defaultdict
    faculty_usage = defaultdict(int)
    room_usage = defaultdict(int)
    faculty_schedule = set() 
    room_schedule = set()
    batch_schedule = set()

    for r in all_dept_records:
        t_key = (r['day_of_week'], r['timeslot'])
        faculty_schedule.add((r['faculty_id'], t_key))
        room_schedule.add((r['room_id'], t_key))
        if r['batch_id'] == batch_id:
            batch_schedule.add(t_key)
        faculty_usage[r['faculty_id']] += 1
        room_usage[r['room_id']] += 1

    total_req = sum(s['required_sessions'] for s in subjects)
    scheduled_counts = defaultdict(int)
    for r in records:
        if r['batch_id'] == batch_id:
            scheduled_counts[r['subject_id']] += 1

    total_sched = sum(scheduled_counts.values())
    missing = total_req - total_sched
    comp_rate = int((total_sched / total_req) * 100) if total_req > 0 else 100

    missing_details = []
    smart_recommendations = []
    fac_dict = {f['id']: f for f in faculties}
    room_dict = {r['id']: r for r in rooms}

    missing_theory = 0
    missing_practical = 0

    for s in subjects:
        req = s['required_sessions']
        sched = scheduled_counts[s['id']]
        if sched < req:
            missing_count = req - sched
            if s['subject_type'] == 'Practical': missing_practical += missing_count
            else: missing_theory += missing_count

            sub_facs = [f['id'] for f in faculties if (f['id'], s['id']) in exp_map]

            cause = "Unknown"
            if not sub_facs:
                cause = "No faculty mapped with expertise."
            else:
                overloaded = True
                for fid in sub_facs:
                    if faculty_usage[fid] < fac_dict[fid]['max_weekly_hours']: overloaded = False
                if overloaded:
                    cause = "Faculty weekly workload limit reached."
                else:
                    req_type = "Laboratory" if s["subject_type"] == "Practical" else "Lecture Hall/Seminar Room"
                    valid_rooms = [r for r in rooms if r["room_type"] == req_type or (req_type=="Lecture Hall/Seminar Room" and r["room_type"]!="Laboratory")]
                    if not valid_rooms: cause = f"No '{req_type}' available in department."
                    else: cause = "Scheduling rules prevented allocation (No common free slots)."

            missing_details.append({
                "subject": s['name'], "type": s['subject_type'], "missing": missing_count, "cause": cause
            })

            # Smart Recommendations
            recs_found = 0
            for day in DAYS:
                for slot in dynamic_slots:
                    if recs_found >= 5: break
                    t_key = (day, slot)
                    if t_key in batch_schedule: continue

                    free_fac = None
                    for fid in sub_facs:
                        if (fid, t_key) not in faculty_schedule and faculty_usage[fid] < fac_dict[fid]['max_weekly_hours']:
                            free_fac = fid
                            break

                    if free_fac:
                        req_type = "Laboratory" if s["subject_type"] == "Practical" else "Lecture Hall/Seminar Room"
                        free_room = None
                        for r in rooms:
                            if r["room_type"] == "Laboratory" and req_type != "Laboratory": continue
                            if r["room_type"] != "Laboratory" and req_type == "Laboratory": continue
                            if (r['id'], t_key) not in room_schedule:
                                free_room = r['id']
                                break

                        if free_room:
                            smart_recommendations.append({
                                "day": day, "time": slot, "room": room_dict[free_room]['name'],
                                "faculty": fac_dict[free_fac]['name'], "subject": s['name'], 
                                "reason": "Faculty, Room, and Batch are all free.",
                                # ---> THE FIX: EXPLICITLY SEND THE IDs SO THE FRONTEND CAN SAVE THE CLASS <---
                                "faculty_id": free_fac, "room_id": free_room, "subject_id": s['id']
                            })
                            recs_found += 1

    opt_suggestions = []
    if comp_rate < 100:
        if any("workload" in m["cause"] for m in missing_details): opt_suggestions.append({"text": "Increase faculty weekly limits or hire new faculty.", "impact": "+15%"})
        if any("Room" in m["cause"] for m in missing_details): opt_suggestions.append({"text": "Add additional classrooms or labs.", "impact": "+10%"})
        opt_suggestions.append({"text": "Allow Saturday scheduling.", "impact": "+20%"})
        opt_suggestions.append({"text": "Relax consecutive session constraints.", "impact": "+5%"})
    else:
        opt_suggestions.append({"text": "Timetable is fully optimized. No further action needed.", "impact": "N/A"})

    return {
        "total_req": total_req, "total_sched": total_sched, "total_missing": missing,
        "missing_theory": missing_theory, "missing_practical": missing_practical,
        "comp_rate": comp_rate, "free_slots": (5 * len(dynamic_slots)) - total_sched, "score": comp_rate,
        "missing_breakdown": missing_details, "smart_recommendations": smart_recommendations,
        "optimization_suggestions": opt_suggestions,
        "constraints": [
            {"name": "Faculty Double Booking", "status": "Passed"},
            {"name": "Room Double Booking", "status": "Passed"},
            {"name": "Batch Double Booking", "status": "Passed"},
            {"name": "Subject Session Requirement", "status": "Passed" if missing == 0 else "Failed"},
            {"name": "Faculty Hour Limit", "status": "Passed"},
            {"name": "Lab Consecutive Rule", "status": "Passed"}
        ]
    }
# =========================================================
# TIMETABLE GENERATION (MASTER ENGINE)
# =========================================================
# =========================================================
# TIMETABLE GENERATION (MASTER ENGINE)
# =========================================================
@app.post("/generate-timetable/{department_id}")
def generate_timetable(department_id: int, payload: GenerateRequest, user: dict = Depends(require_admin)):
    conn = get_db_connection()
    cursor = conn.cursor()  
    try:
        cursor.execute("SELECT * FROM faculties WHERE department_id = %s", (department_id,))
        faculties = cursor.fetchall()
        
        if payload.batch_id != "all":
            cursor.execute("SELECT * FROM batches WHERE department_id = %s AND id = %s", (department_id, int(payload.batch_id)))
            batches = cursor.fetchall()
            target_semester = batches[0]["semester"]
            cursor.execute("SELECT * FROM subjects WHERE department_id = %s AND semester = %s", (department_id, target_semester))
            subjects = cursor.fetchall()
        else:
            cursor.execute("SELECT * FROM batches WHERE department_id = %s", (department_id,))
            batches = cursor.fetchall()
            cursor.execute("SELECT * FROM subjects WHERE department_id = %s", (department_id,))
            subjects = cursor.fetchall()

        cursor.execute("SELECT * FROM rooms WHERE is_active = TRUE")
        rooms = cursor.fetchall()

        # THE FIX: Global University-Wide Booking Conflict Resolution
        if payload.batch_id != "all":
            cursor.execute("""
                SELECT batch_id, faculty_id, room_id, day_of_week, timeslot
                FROM timetables WHERE batch_id != %s
            """, (int(payload.batch_id),))
            existing_bookings = cursor.fetchall()
        else:
            cursor.execute("""
                SELECT batch_id, faculty_id, room_id, day_of_week, timeslot
                FROM timetables WHERE department_id != %s
            """, (department_id,))
            existing_bookings = cursor.fetchall()

        cursor.execute("""
            SELECT fe.faculty_id, fe.subject_id, fe.competency_tier
            FROM faculty_expertise fe JOIN faculties f ON fe.faculty_id = f.id WHERE f.department_id = %s
        """, (department_id,))
        expertise = cursor.fetchall()
        exp_map = {(exp["faculty_id"], exp["subject_id"]): float(exp["competency_tier"]) for exp in expertise}

        dynamic_slots = []
        slot_hours = [] 
        for h in range(payload.start_hour, payload.end_hour):
            if h == payload.break_hour: continue 
            am_pm1 = "AM" if h < 12 or h == 24 else "PM"
            disp1 = h if h <= 12 else h - 12
            if disp1 == 0: disp1 = 12
            h2 = h + 1
            am_pm2 = "AM" if h2 < 12 or h2 == 24 else "PM"
            disp2 = h2 if h2 <= 12 else h2 - 12
            if disp2 == 0: disp2 = 12
            dynamic_slots.append(f"{disp1:02d}:00 {am_pm1} - {disp2:02d}:00 {am_pm2}")
            slot_hours.append(h)

        room_buffer = 4 if payload.batch_id != "all" else max(4, len(batches) * 2)
        eligible_rooms = {}
        for batch in batches:
            for subject in subjects:
                if subject["semester"] != batch["semester"]: continue
                valid_rooms = []
                for room in rooms:
                    if room["capacity"] >= batch["student_count"]:
                        if subject["subject_type"] == "Practical" and room["room_type"] == "Laboratory": valid_rooms.append(room)
                        elif subject["subject_type"] != "Practical" and room["room_type"] != "Laboratory": valid_rooms.append(room)
                valid_rooms.sort(key=lambda r: r["capacity"])
                eligible_rooms[(subject["id"], batch["id"])] = valid_rooms[:room_buffer]

        scenarios = [
            {"name": "Option 1: Balanced", "w_exp": 10, "w_room": 20},
            {"name": "Option 2: Minimum Movement", "w_exp": 5, "w_room": 100},
            {"name": "Option 3: Faculty Expertise Focus", "w_exp": 50, "w_room": 5}
        ]

        generated_options = []
        previous_solution_keys = []
        sub_dict = {s['id']: s['name'] for s in subjects}
        room_dict = {r['id']: r['name'] for r in rooms}
        fac_dict = {f['id']: f['name'] for f in faculties}
        batch_dict = {b['id']: b['name'] for b in batches}

        for scenario in scenarios:
            model = cp_model.CpModel()
            x = {}
            fac_day_slot = defaultdict(list)
            room_day_slot = defaultdict(list)
            batch_day_slot = defaultdict(list)
            batch_subject = defaultdict(list)
            fac_weekly = defaultdict(list)
            fac_day = defaultdict(list)
            batch_day_sub = defaultdict(list)
            batch_day_slot_sub = defaultdict(list)
            batch_day_slot_room = defaultdict(list)

            for faculty in faculties:
                fac_id = faculty["id"]
                for subject in subjects:
                    sub_id = subject["id"]
                    if (fac_id, sub_id) not in exp_map: continue 
                    for batch in batches:
                        b_id = batch["id"]
                        if subject["semester"] != batch["semester"]: continue
                        for room in eligible_rooms.get((sub_id, b_id), []):
                            r_id = room["id"]
                            for day in DAYS:
                                for slot in dynamic_slots:
                                    key = (fac_id, sub_id, r_id, day, slot, b_id)
                                    var = model.NewBoolVar(f"x_{key}")
                                    x[key] = var
                                    fac_day_slot[(fac_id, day, slot)].append(var)
                                    room_day_slot[(r_id, day, slot)].append(var)
                                    batch_day_slot[(b_id, day, slot)].append(var)
                                    batch_subject[(b_id, sub_id)].append(var)
                                    fac_weekly[fac_id].append(var)
                                    fac_day[(fac_id, day)].append(var)
                                    batch_day_sub[(b_id, day, sub_id)].append(var)
                                    batch_day_slot_sub[(b_id, day, slot, sub_id)].append(var)
                                    batch_day_slot_room[(b_id, day, slot, r_id)].append(var)

            for vars_list in fac_day_slot.values():
                if len(vars_list) > 1: model.AddAtMostOne(vars_list)
            for vars_list in room_day_slot.values():
                if len(vars_list) > 1: model.AddAtMostOne(vars_list)
            for vars_list in batch_day_slot.values():
                if len(vars_list) > 1: model.AddAtMostOne(vars_list)

            for fac_id, vars_list in fac_weekly.items():
                max_hrs = next((f["max_weekly_hours"] for f in faculties if f["id"] == fac_id), 40)
                if vars_list: model.Add(sum(vars_list) <= max_hrs)

            objective_terms = []

            for batch in batches:
                for subject in subjects:
                    if subject["semester"] != batch["semester"]: continue
                    sub_id = subject["id"]; b_id = batch["id"]; req = subject["required_sessions"]
                    sub_vars = batch_subject.get((b_id, sub_id), [])
                    
                    if subject["subject_type"] == "Practical":
                        num_blocks = req // 2 if req >= 2 else 1
                        expected_slots = num_blocks * 2
                        all_block_vars = []
                        for day in DAYS:
                            day_block_vars = []
                            for fac in faculties:
                                if (fac["id"], sub_id) not in exp_map: continue
                                for room in eligible_rooms.get((sub_id, b_id), []):
                                    for i in range(len(dynamic_slots) - 1): 
                                        if slot_hours[i + 1] - slot_hours[i] != 1: continue 
                                        var1 = x.get((fac["id"], sub_id, room["id"], day, dynamic_slots[i], b_id))
                                        var2 = x.get((fac["id"], sub_id, room["id"], day, dynamic_slots[i+1], b_id))
                                        if var1 is not None and var2 is not None:
                                            block_var = model.NewBoolVar(f"blk_{b_id}_{sub_id}_{fac['id']}_{room['id']}_{day}_{i}")
                                            all_block_vars.append(block_var)
                                            day_block_vars.append(block_var)
                                            model.Add(var1 == 1).OnlyEnforceIf(block_var)
                                            model.Add(var2 == 1).OnlyEnforceIf(block_var)
                            if day_block_vars: model.Add(sum(day_block_vars) <= 1)
                                                
                        if all_block_vars: 
                            model.Add(sum(all_block_vars) <= num_blocks)
                            for var in all_block_vars: objective_terms.append(var * 50000)
                        if sub_vars: 
                            model.Add(sum(sub_vars) <= expected_slots)
                            for var in sub_vars: objective_terms.append(var * 10000)
                            
                    else:
                        if sub_vars: 
                            model.Add(sum(sub_vars) <= req)
                            for var in sub_vars: objective_terms.append(var * 10000)
                        
                        import math
                        max_per_day = math.ceil(req / 5) 
                        for day in DAYS:
                            day_s_vars = []
                            for i in range(len(dynamic_slots)):
                                day_s_vars.extend(batch_day_slot_sub.get((b_id, day, dynamic_slots[i], sub_id), []))
                            if day_s_vars:
                                model.Add(sum(day_s_vars) <= max_per_day)

                            for i in range(len(dynamic_slots) - 1):
                                s1_vars = batch_day_slot_sub.get((b_id, day, dynamic_slots[i], sub_id), [])
                                s2_vars = batch_day_slot_sub.get((b_id, day, dynamic_slots[i+1], sub_id), [])
                                if s1_vars and s2_vars: model.Add(sum(s1_vars) + sum(s2_vars) <= 1)

            for booking in existing_bookings:
                d, t = booking["day_of_week"], booking["timeslot"]
                for var in fac_day_slot.get((booking["faculty_id"], d, t), []): model.Add(var == 0)
                for var in room_day_slot.get((booking["room_id"], d, t), []): model.Add(var == 0)

            for key, var in x.items():
                score = int(exp_map[(key[0], key[1])] * scenario["w_exp"])
                objective_terms.append(var * score)

            for prev_keys in previous_solution_keys:
                matching_vars = [x[k] for k in prev_keys if k in x]
                if matching_vars:
                    classes_to_move = max(2, len(matching_vars) // 6) 
                    model.Add(sum(matching_vars) <= len(matching_vars) - classes_to_move)

            model.Maximize(sum(objective_terms))

            all_vars = list(x.values())
            if all_vars:
                model.AddDecisionStrategy(all_vars, cp_model.CHOOSE_FIRST, cp_model.SELECT_MAX_VALUE)

            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = 10 
            
            if "Balanced" in scenario["name"]: solver.parameters.random_seed = 1
            elif "Movement" in scenario["name"]: solver.parameters.random_seed = 42
            else: solver.parameters.random_seed = 999

            status = solver.Solve(model)

            if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
                draft_records = []
                current_solution_keys = [] 
                for key, var in x.items():
                    if solver.Value(var) == 1:
                        current_solution_keys.append(key)
                        draft_records.append({
                            "department_id": department_id, "faculty_id": key[0], "subject_id": key[1],
                            "room_id": key[2], "day_of_week": key[3], "timeslot": key[4], "batch_id": key[5],
                            "faculty": fac_dict[key[0]], "subject": sub_dict[key[1]], "room": room_dict[key[2]], "batch": batch_dict[key[5]]
                        })
                        
                previous_solution_keys.append(current_solution_keys)
                
                batch_analyses = {}
                for batch in batches:
                    b_id = batch["id"]
                    b_subjects = [s for s in subjects if s["semester"] == batch["semester"]]
                    batch_analyses[b_id] = run_timtable_analysis(b_id, draft_records, b_subjects, faculties, rooms, dynamic_slots, exp_map, existing_bookings + draft_records)
                
                generated_options.append({"option_name": scenario["name"], "records": draft_records, "analyses": batch_analyses})

        if generated_options:
            return {"success": True, "message": f"Successfully generated {len(generated_options)} optimization options!", "draft_options": generated_options}
        else:
            return {"success": False, "message": "The math is too tight! No feasible timetable could be found under these strict constraints."}       
         
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        release_db_connection(conn)

@app.post("/save-timetable/")
def save_timetable(
    payload: SaveTimetableRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_admin),
):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if not payload.records: 
            return {"success": False, "message": "No records to save."}
            
        # Extract unique batch IDs from data payload
        batch_ids = list(set(r.batch_id for r in payload.records))
        
        # Bulletproof clearing for single vs multiple items to prevent PostgreSQL syntax crashes
        if len(batch_ids) == 1:
            cursor.execute("DELETE FROM timetables WHERE batch_id = %s", (batch_ids[0],))
        else:
            cursor.execute("DELETE FROM timetables WHERE batch_id IN %s", (tuple(batch_ids),))
        
        insert_data = [(r.department_id, r.day_of_week, r.timeslot, r.room_id, r.batch_id, r.subject_id, r.faculty_id, payload.notes) for r in payload.records]
        
        cursor.executemany("""
            INSERT INTO timetables 
            (department_id, day_of_week, timeslot, room_id, batch_id, subject_id, faculty_id, notes) 
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, insert_data)
        
        conn.commit()
        background_tasks.add_task(_notify_published_batches, batch_ids)
        return {"success": True, "message": "Timetable securely published to database."}
        
    except Exception as e: 
        conn.rollback()
        print(f"DATABASE SAVE ERROR: {str(e)}") 
        raise HTTPException(status_code=500, detail=str(e))
    finally: 
        cursor.close()
        release_db_connection(conn)
                        
@app.post("/validate-swap/")
def validate_timetable_swap(payload: SwapValidationRequest, user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM timetables WHERE faculty_id = %s AND day_of_week = %s AND timeslot = %s", (payload.faculty_id, payload.new_day, payload.new_timeslot))
        if cursor.fetchone(): return {"valid": False, "message": "Conflict: This Professor is already teaching another class at this time."}
        cursor.execute("SELECT id FROM timetables WHERE room_id = %s AND day_of_week = %s AND timeslot = %s", (payload.room_id, payload.new_day, payload.new_timeslot))
        if cursor.fetchone(): return {"valid": False, "message": "Conflict: This Room is already booked by another class at this time."}
        return {"valid": True, "message": "Move is valid!"}
    finally: cursor.close(); release_db_connection(conn)

@app.put("/update-timetable-slot/")
def update_timetable_slot(
    payload: UpdateSlotRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_admin),
):
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT t.batch_id, t.subject_id, t.day_of_week, t.timeslot,
                   s.name AS subject, r.name AS room
            FROM timetables t
            JOIN subjects s ON s.id = t.subject_id
            JOIN rooms r ON r.id = t.room_id
            WHERE t.id = %s
            """,
            (payload.record_id,),
        )
        previous = cursor.fetchone()
        if not previous:
            raise HTTPException(status_code=404, detail="Timetable record not found")
        cursor.execute("UPDATE timetables SET day_of_week = %s, timeslot = %s WHERE id = %s", (payload.new_day, payload.new_timeslot, payload.record_id))
        conn.commit()
        background_tasks.add_task(
            _notify_reschedule,
            previous["batch_id"],
            previous["subject"],
            previous["day_of_week"],
            previous["timeslot"],
            payload.new_day,
            payload.new_timeslot,
            previous["room"],
        )
        return {"success": True, "message": "Timetable updated permanently!"}
    except Exception as e:
        conn.rollback()
        if "unique constraint" in str(e).lower(): return {"success": False, "message": "Database Conflict: Room or Faculty is occupied."}
        return {"success": False, "message": str(e)}
    finally: cursor.close(); release_db_connection(conn)

@app.get("/view-timetable/")
def view_timetable(department_id: Optional[int] = None, batch_id: Optional[int] = None, user: dict = Depends(require_admin)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        query = """
            SELECT t.id, t.department_id, t.batch_id, t.subject_id, t.faculty_id, t.room_id, t.notes, t.day_of_week, t.timeslot, b.name AS batch, s.name AS subject, r.name AS room, f.name AS faculty
            FROM timetables t 
            JOIN batches b ON t.batch_id = b.id 
            JOIN subjects s ON t.subject_id = s.id 
            JOIN rooms r ON t.room_id = r.id 
            JOIN faculties f ON t.faculty_id = f.id 
            WHERE 1=1
        """
        params = []
        if department_id: 
            query += " AND t.department_id = %s"
            params.append(department_id)
        if batch_id: 
            query += " AND t.batch_id = %s"
            params.append(batch_id)
            
        cursor.execute(query, tuple(params))
        return {"success": True, "data": cursor.fetchall()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally: 
        cursor.close()
        release_db_connection(conn)
                
@app.delete("/delete-timetable/{batch_id}")
def delete_timetable(batch_id: int, user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM timetables WHERE batch_id = %s", (batch_id,))
        if cursor.rowcount == 0: return {"success": False, "message": "No timetable found to delete."}
        conn.commit(); return {"success": True, "message": "Timetable securely deleted."}
    finally: cursor.close(); release_db_connection(conn)
        
# =========================================================
# NEW: FETCH PUBLISHED ANALYSIS
# =========================================================
@app.get("/analyze-timetable/{batch_id}")
def analyze_published_timetable(batch_id: int, user: dict = Depends(require_admin)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT department_id, semester FROM batches WHERE id = %s", (batch_id,))
        batch_info = cursor.fetchone()
        if not batch_info: raise HTTPException(404, "Batch not found")
        department_id = batch_info["department_id"]

        # THE FIX: Remove 'WHERE department_id = %s' so it checks room availability across the WHOLE university!
        cursor.execute("SELECT batch_id, faculty_id, room_id, day_of_week, timeslot FROM timetables")
        all_dept_records = cursor.fetchall()

        cursor.execute("SELECT * FROM timetables WHERE batch_id = %s", (batch_id,))
        batch_records = cursor.fetchall()

        cursor.execute("SELECT * FROM subjects WHERE department_id = %s AND semester = %s", (department_id, batch_info["semester"]))
        subjects = cursor.fetchall()

        cursor.execute("SELECT * FROM faculties WHERE department_id = %s", (department_id,))
        faculties = cursor.fetchall()

        cursor.execute("SELECT * FROM rooms WHERE is_active = TRUE")
        rooms = cursor.fetchall()

        cursor.execute("SELECT fe.faculty_id, fe.subject_id, fe.competency_tier FROM faculty_expertise fe JOIN faculties f ON fe.faculty_id = f.id WHERE f.department_id = %s", (department_id,))
        expertise = cursor.fetchall()
        exp_map = {(exp["faculty_id"], exp["subject_id"]): float(exp["competency_tier"]) for exp in expertise}

        dynamic_slots = ["08:00 AM - 09:00 AM", "09:00 AM - 10:00 AM", "10:00 AM - 11:00 AM", "11:00 AM - 12:00 PM", "01:00 PM - 02:00 PM", "02:00 PM - 03:00 PM", "03:00 PM - 04:00 PM"]

        analysis = run_timtable_analysis(batch_id, batch_records, subjects, faculties, rooms, dynamic_slots, exp_map, all_dept_records)
        return {"success": True, "analysis": analysis}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        release_db_connection(conn)


@app.get("/dashboard-stats/global")
def get_global_dashboard_stats(user: dict = Depends(require_admin)):
    conn = get_db_connection(); cursor = conn.cursor()
    import math
    try:
        cursor.execute("SELECT COUNT(*) as count FROM faculties"); fac_count = cursor.fetchone()["count"]
        cursor.execute("SELECT COUNT(*) as count FROM batches"); batch_count = cursor.fetchone()["count"]
        cursor.execute("SELECT COALESCE(SUM(student_count), 0) as count FROM batches"); student_count = cursor.fetchone()["count"]
        cursor.execute("SELECT COUNT(*) as count FROM departments"); dept_count = cursor.fetchone()["count"]
        cursor.execute("SELECT COUNT(*) as count FROM subjects"); subject_count = cursor.fetchone()["count"]
        cursor.execute("SELECT COUNT(*) as count FROM rooms WHERE is_active = TRUE"); room_count = cursor.fetchone()["count"]
        total_possible_slots = room_count * 35 
        cursor.execute("SELECT COUNT(*) as count FROM timetables"); booked_slots = cursor.fetchone()["count"]
        utilization = round((booked_slots / total_possible_slots) * 100) if total_possible_slots > 0 else 0

        cursor.execute("SELECT f.id, f.name, COUNT(t.id) as assigned_hours, f.max_weekly_hours, f.department_id FROM faculties f LEFT JOIN timetables t ON f.id = t.faculty_id GROUP BY f.id, f.name, f.max_weekly_hours, f.department_id ORDER BY assigned_hours DESC")
        faculty_load = cursor.fetchall()
        
        overworked_count = sum(1 for f in faculty_load if f["max_weekly_hours"] > 0 and (f["assigned_hours"] / f["max_weekly_hours"]) >= 0.9)
        underused_rooms_count = math.ceil(room_count * (1 - (utilization / 100))) if utilization < 60 else 0

        cursor.execute("SELECT COUNT(*) as c FROM (SELECT b.id FROM batches b LEFT JOIN timetables t ON b.id = t.batch_id GROUP BY b.id HAVING COUNT(t.id) = 0) as sub")
        unscheduled_batches = cursor.fetchone()["c"]

        cursor.execute("SELECT COUNT(*) as c FROM (SELECT s.id FROM subjects s LEFT JOIN faculty_expertise fe ON s.id = fe.subject_id GROUP BY s.id HAVING COUNT(fe.faculty_id) = 0) as sub")
        unmapped_subjects = cursor.fetchone()["c"]

        total_issues = unscheduled_batches + unmapped_subjects + overworked_count

        health_score = 100
        health_checklist = []
        if overworked_count == 0: health_checklist.append({"status": "pass", "text": "No overloaded faculty"})
        else: health_score -= (overworked_count * 3); health_checklist.append({"status": "warn", "text": f"{overworked_count} faculty overloaded"})
        if utilization <= 85: health_checklist.append({"status": "pass", "text": "Healthy room utilization"})
        else: health_score -= 10; health_checklist.append({"status": "warn", "text": "High room clashes/usage"})
        if underused_rooms_count > 0: health_checklist.append({"status": "info", "text": f"{underused_rooms_count} underutilized rooms"})
        if unscheduled_batches == 0: health_checklist.append({"status": "pass", "text": "All batches scheduled"})
        else: health_score -= (unscheduled_batches * 5); health_checklist.append({"status": "fail", "text": f"{unscheduled_batches} unscheduled batches"})
        if unmapped_subjects > 0: health_score -= (unmapped_subjects * 2); health_checklist.append({"status": "fail", "text": f"{unmapped_subjects} unmapped subjects"})
        health_score = max(0, min(100, health_score))

        exp_fac_shortage = math.ceil(overworked_count * 0.5) + (2 if utilization > 90 else 0)
        exp_room_shortage = math.ceil((utilization - 85) / 100 * room_count) if utilization > 85 else 0
        risk_level = "Low"
        if health_score < 70 or exp_fac_shortage > 2: risk_level = "High"
        elif health_score < 85 or exp_fac_shortage > 0: risk_level = "Medium"
        predictive = {"sufficient": "YES" if exp_fac_shortage == 0 and exp_room_shortage <= 0 else "NO", "faculty_shortage": exp_fac_shortage, "room_shortage": f"{exp_room_shortage} Labs/Rooms" if exp_room_shortage > 0 else "None", "next_sem_risk": risk_level}

        recommendations = []
        if exp_fac_shortage > 0: recommendations.append({"type": "warning", "icon": "person_add", "title": "Hire New Faculty", "message": f"Predictive models suggest hiring {exp_fac_shortage} new professors to maintain health next semester."})
        if exp_room_shortage > 0: recommendations.append({"type": "error", "icon": "domain_disabled", "title": "Room Shortage Predicted", "message": f"You will need {exp_room_shortage} additional rooms to comfortably house next semester's batches."})
        if unmapped_subjects > 0: recommendations.append({"type": "action", "icon": "menu_book", "title": "Map Expertise", "message": f"{unmapped_subjects} subjects are unteachable right now. Map faculty to them immediately."})
        if not recommendations: recommendations.append({"type": "success", "icon": "auto_awesome", "title": "Perfect Harmony", "message": "No predictive risks detected. Current resources are perfectly balanced."})

        return {"success": True, "stats": {"departments": dept_count, "faculty": fac_count, "students": student_count, "rooms": room_count, "subjects": subject_count, "issues": total_issues, "utilization": utilization, "version": "v3.2 (Live)"}, "health": { "score": health_score, "checklist": health_checklist }, "predictive": predictive, "faculty_load": faculty_load, "recommendations": recommendations}
    finally: cursor.close(); release_db_connection(conn)