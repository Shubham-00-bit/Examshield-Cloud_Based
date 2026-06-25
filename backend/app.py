"""
ExamShield Backend v4
- JWT + device fingerprint auth
- SQLite database (questions, students, batches all in DB)
- UTC time fix
- Email/password login (no roll number for hash lookup)
- Batch system with auto CSV generation
- Built-in DB admin panel
"""

import os, json, hashlib, random, csv, smtplib, secrets, sqlite3, io
import jwt as pyjwt
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps

import pandas as pd
from flask import (Flask, request, jsonify, session,
                   send_from_directory, g, send_file)
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from web3 import Web3

# ══════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════
app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
CORS(app, supports_credentials=True)

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR     = os.path.join(BASE_DIR, "data")
UPLOAD_DIR   = os.path.join(BASE_DIR, "uploads")
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")
DB_PATH      = os.path.join(DATA_DIR, "examshield.db")
CONTRACT_JSON= os.path.join(BASE_DIR, "..", "build", "contracts", "ExamRegistry.json")

os.makedirs(DATA_DIR,   exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

JWT_SECRET      = secrets.token_hex(32)
JWT_EXPIRY_HOURS= 8
DB_ADMIN_PASS   = "dbadmin123"   # change this

SMTP_HOST     = "smtp-relay.brevo.com"
SMTP_PORT     = 587
SMTP_USER     = "a782c9001@smtp-brevo.com"
SMTP_PASSWORD = "s8OSxQMq9DgjX4rw"
SMTP_FROM     = "narutouzumaki150820001@gmail.com"
# ══════════════════════════════════════════════════
#  DATABASE
# ══════════════════════════════════════════════════
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db: db.close()

def init_db():
    with app.app_context():
        db = get_db()
        db.executescript("""
        CREATE TABLE IF NOT EXISTS university (
            id         INTEGER PRIMARY KEY,
            username   TEXT UNIQUE NOT NULL,
            password   TEXT NOT NULL,
            name       TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now','utc'))
        );

        CREATE TABLE IF NOT EXISTS exams (
            id             INTEGER PRIMARY KEY,
            exam_type      TEXT UNIQUE NOT NULL,
            file_hash      TEXT,
            question_count INTEGER DEFAULT 0,
            created_at     TEXT DEFAULT (datetime('now','utc'))
        );

        CREATE TABLE IF NOT EXISTS questions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_type     TEXT NOT NULL,
            question      TEXT NOT NULL,
            option_a      TEXT NOT NULL,
            option_b      TEXT NOT NULL,
            option_c      TEXT NOT NULL,
            option_d      TEXT NOT NULL,
            correct_answer TEXT NOT NULL,
            subject       TEXT DEFAULT '',
            created_at    TEXT DEFAULT (datetime('now','utc'))
        );

        CREATE TABLE IF NOT EXISTS batches (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_type  TEXT NOT NULL,
            batch_name TEXT NOT NULL,
            start_time TEXT NOT NULL,
            duration   INTEGER NOT NULL DEFAULT 180,
            capacity   INTEGER NOT NULL DEFAULT 100,
            created_at TEXT DEFAULT (datetime('now','utc'))
        );

        CREATE TABLE IF NOT EXISTS students (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            name               TEXT NOT NULL,
            email              TEXT NOT NULL,
            password           TEXT NOT NULL,
            exam_type          TEXT NOT NULL,
            batch_id           INTEGER,
            paper_hash         TEXT UNIQUE NOT NULL,
            device_fingerprint TEXT,
            registered_at      TEXT DEFAULT (datetime('now','utc')),
            UNIQUE(email, exam_type),
            FOREIGN KEY(batch_id) REFERENCES batches(id)
        );

        -- Migrate: drop roll_number if it exists (safe re-run)
        CREATE TABLE IF NOT EXISTS students_migrated (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            name               TEXT NOT NULL,
            email              TEXT NOT NULL,
            password           TEXT NOT NULL,
            exam_type          TEXT NOT NULL,
            batch_id           INTEGER,
            paper_hash         TEXT UNIQUE NOT NULL,
            device_fingerprint TEXT,
            registered_at      TEXT DEFAULT (datetime('now','utc')),
            UNIQUE(email, exam_type),
            FOREIGN KEY(batch_id) REFERENCES batches(id)
        );

        CREATE TABLE IF NOT EXISTS logs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            action     TEXT NOT NULL,
            detail     TEXT,
            ip         TEXT,
            timestamp  TEXT DEFAULT (datetime('now','utc'))
        );

        CREATE TABLE IF NOT EXISTS exam_sessions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id   INTEGER UNIQUE NOT NULL,
            started_at   TEXT NOT NULL,
            submitted_at TEXT,
            answers      TEXT,
            FOREIGN KEY(student_id) REFERENCES students(id)
        );

        CREATE TABLE IF NOT EXISTS results (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id   INTEGER UNIQUE NOT NULL,
            batch_id     INTEGER NOT NULL,
            exam_type    TEXT NOT NULL,
            score        INTEGER DEFAULT 0,
            total        INTEGER DEFAULT 0,
            percentage   REAL DEFAULT 0,
            result_hash  TEXT UNIQUE NOT NULL,
            published_at TEXT DEFAULT (datetime('now','utc')),
            FOREIGN KEY(student_id) REFERENCES students(id),
            FOREIGN KEY(batch_id) REFERENCES batches(id)
        );
        """)

        # Default university account
        # Default university account
        if not db.execute("SELECT id FROM university WHERE username='admin'").fetchone():
            db.execute("INSERT INTO university (username,password,name) VALUES (?,?,?)",
                ("admin", generate_password_hash("admin123"), "Default University"))
        db.commit()

        # Migration: remove roll_number column if it exists
        cols = [r[1] for r in db.execute("PRAGMA table_info(students)").fetchall()]
        if "roll_number" in cols:
            db.execute("PRAGMA foreign_keys=OFF")
            db.executescript("""
                PRAGMA foreign_keys=OFF;
                CREATE TABLE IF NOT EXISTS students_new (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    name               TEXT NOT NULL,
                    email              TEXT NOT NULL,
                    password           TEXT NOT NULL,
                    exam_type          TEXT NOT NULL,
                    batch_id           INTEGER,
                    paper_hash         TEXT UNIQUE NOT NULL,
                    device_fingerprint TEXT,
                    registered_at      TEXT DEFAULT (datetime('now','utc')),
                    UNIQUE(email, exam_type),
                    FOREIGN KEY(batch_id) REFERENCES batches(id)
                );
                INSERT OR IGNORE INTO students_new
                    SELECT id,name,email,password,exam_type,
                           batch_id,paper_hash,device_fingerprint,registered_at
                    FROM students;
                DROP TABLE students;
                ALTER TABLE students_new RENAME TO students;
                PRAGMA foreign_keys=ON;
            """)
            print("[MIGRATION] roll_number removed from students table")

# ══════════════════════════════════════════════════
#  JWT HELPERS
# ══════════════════════════════════════════════════
def make_token(payload: dict, hours=JWT_EXPIRY_HOURS):
    payload["exp"] = datetime.now(timezone.utc) + timedelta(hours=hours)
    return pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")

def read_token(token: str):
    return pyjwt.decode(token, JWT_SECRET, algorithms=["HS256"])

def get_bearer():
    h = request.headers.get("Authorization","")
    return h[7:] if h.startswith("Bearer ") else None

# ══════════════════════════════════════════════════
#  AUTH DECORATORS
# ══════════════════════════════════════════════════
def university_required(f):
    @wraps(f)
    def dec(*a,**kw):
        token = get_bearer()
        if not token:
            return jsonify({"error":"Login required"}), 401
        try:
            data = read_token(token)
            if data.get("role") != "university":
                return jsonify({"error":"Unauthorized"}), 403
            g.uni = data
        except pyjwt.ExpiredSignatureError:
            return jsonify({"error":"Session expired"}), 401
        except pyjwt.InvalidTokenError:
            return jsonify({"error":"Invalid token"}), 401
        return f(*a,**kw)
    return dec

def student_required(f):
    @wraps(f)
    def dec(*a,**kw):
        token = get_bearer()
        if not token:
            return jsonify({"error":"Login required"}), 401
        try:
            data = read_token(token)
            if data.get("role") != "student":
                return jsonify({"error":"Unauthorized"}), 403
            # Device check
            fp = make_fp(
                request.headers.get("X-UA",""),
                request.headers.get("X-Screen",""),
                request.remote_addr
            )
            if data.get("device_fp") != fp:
                log_event(data.get("student_id"), "DEVICE_MISMATCH",
                          f"Expected {data.get('device_fp','')[:12]} got {fp[:12]}")
                return jsonify({"error":"Device mismatch — use your registered device"}), 403
            g.student = data
        except pyjwt.ExpiredSignatureError:
            return jsonify({"error":"Session expired"}), 401
        except pyjwt.InvalidTokenError:
            return jsonify({"error":"Invalid token"}), 401
        return f(*a,**kw)
    return dec

def db_admin_required(f):
    @wraps(f)
    def dec(*a,**kw):
        if not session.get("db_admin"):
            return jsonify({"error":"DB admin login required"}), 401
        return f(*a,**kw)
    return dec

# ══════════════════════════════════════════════════
#  BLOCKCHAIN
# ══════════════════════════════════════════════════
w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:7545"))

def get_contract():
    try:
        with open(CONTRACT_JSON) as f:
            art = json.load(f)
        nets = art.get("networks",{})
        if not nets: return None
        addr = list(nets.values())[-1]["address"]
        return w3.eth.contract(address=addr, abi=art["abi"])
    except Exception as e:
        print(f"[CONTRACT] {e}")
        return None

# ══════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════
def now_utc():
    return datetime.now(timezone.utc)

IST = timezone(timedelta(hours=5, minutes=30))

def parse_utc(s):
    dt = datetime.fromisoformat(str(s))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)            # ← correct: naive input is IST
    return dt.astimezone(timezone.utc)
def make_fp(ua, screen, ip):
    return hashlib.sha256(f"{ua}|{screen}|{ip}".encode()).hexdigest()

def make_paper_hash(name, email, exam_type):
    raw = f"{name}|{email}|{exam_type}|{secrets.token_hex(16)}"
    return hashlib.sha256(raw.encode()).hexdigest()

def make_result_hash(student_id, batch_id, score, total, submitted_at):
    raw = f"{student_id}|{batch_id}|{score}|{total}|{submitted_at}|{secrets.token_hex(8)}"
    return hashlib.sha256(raw.encode()).hexdigest()

def log_event(student_id, action, detail=None):
    try:
        db = get_db()
        db.execute("INSERT INTO logs(student_id,action,detail,ip) VALUES(?,?,?,?)",
                   (student_id, action, detail, request.remote_addr))
        db.commit()
    except: pass

def get_shuffled_questions(exam_type, paper_hash):
    db        = get_db()
    rows      = db.execute(
        "SELECT * FROM questions WHERE exam_type=?", (exam_type,)
    ).fetchall()
    questions = [dict(r) for r in rows]
    seed      = int(paper_hash[:8], 16)
    rng       = random.Random(seed)
    rng.shuffle(questions)
    return [{
        "id":       q["id"],
        "question": q["question"],
        "option_a": q["option_a"],
        "option_b": q["option_b"],
        "option_c": q["option_c"],
        "option_d": q["option_d"],
        "subject":  q["subject"],
    } for q in questions]

def send_email(to, name, exam_type, batch_name, start_time):
    """Registration confirmation email."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"ExamShield — {exam_type} Registration Confirmed"
        msg["From"]    = SMTP_FROM
        msg["To"]      = to
        html = f"""
        <div style="font-family:sans-serif;max-width:600px;margin:auto;
                    padding:32px;border:1px solid #e2e8f0;border-radius:12px">
          <h2 style="color:#1e3a5f">ExamShield — You're Registered! ✅</h2>
          <p>Hello <strong>{name}</strong>,</p>
          <p>Your registration for <strong>{exam_type}</strong> is confirmed.</p>
          <p>Batch: <strong>{batch_name}</strong></p>
          <p>Exam Time: <strong>{start_time} IST</strong></p>
          <hr/>
          <p style="color:#dc2626;font-size:13px">
            Login with your email and password on exam day.<br/>
            You must use the same device you registered from.
          </p>
        </div>"""
        msg.attach(MIMEText(html,"html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASSWORD)
            s.sendmail(SMTP_FROM, to, msg.as_string())
        return True
    except Exception as e:
        print(f"[EMAIL-REGISTER] {e}")
        return False

def send_exam_reminder(to, name, exam_type, batch_name, start_time):
    """Pre-exam reminder email sent ~10-15 min before exam."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"ExamShield — {exam_type} starts in ~10 minutes!"
        msg["From"]    = SMTP_FROM
        msg["To"]      = to
        html = f"""
        <div style="font-family:sans-serif;max-width:600px;margin:auto;
                    padding:32px;border:2px solid #f59e0b;border-radius:12px">
          <h2 style="color:#b45309">⏰ Your {exam_type} Exam Starts Soon!</h2>
          <p>Hello <strong>{name}</strong>,</p>
          <p>Your exam <strong>{batch_name}</strong> begins at <strong>{start_time} IST</strong>.</p>
          <p style="color:#dc2626;font-weight:600">Please login now from your registered device and be ready.</p>
          <hr/>
          <p style="font-size:13px;color:#6b7280">
            Do not switch devices. Make sure your internet connection is stable.
          </p>
        </div>"""
        msg.attach(MIMEText(html,"html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASSWORD)
            s.sendmail(SMTP_FROM, to, msg.as_string())
        return True
    except Exception as e:
        print(f"[EMAIL-REMINDER] {e}")
        return False

def send_result_email(to, name, exam_type, score, total, percentage, result_hash):
    """Result published email with score and immutable hash."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"ExamShield — Your {exam_type} Result is Published"
        msg["From"]    = SMTP_FROM
        msg["To"]      = to
        grade_color = "#059669" if percentage >= 50 else "#dc2626"
        html = f"""
        <div style="font-family:sans-serif;max-width:600px;margin:auto;
                    padding:32px;border:1px solid #e2e8f0;border-radius:12px">
          <h2 style="color:#1e3a5f">📊 {exam_type} Result Published</h2>
          <p>Hello <strong>{name}</strong>,</p>
          <div style="background:#f8fafc;border-radius:10px;padding:20px;margin:20px 0;text-align:center">
            <div style="font-size:48px;font-weight:800;color:{grade_color}">{score}/{total}</div>
            <div style="font-size:20px;color:{grade_color}">{percentage:.1f}%</div>
          </div>
          <hr/>
          <p style="font-size:12px;color:#6b7280">
            Result Hash (immutable proof on blockchain):<br/>
            <code style="background:#f1f5f9;padding:4px 8px;border-radius:4px;font-size:11px">{result_hash}</code>
          </p>
        </div>"""
        msg.attach(MIMEText(html,"html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASSWORD)
            s.sendmail(SMTP_FROM, to, msg.as_string())
        return True
    except Exception as e:
        print(f"[EMAIL-RESULT] {e}")
        return False

# ══════════════════════════════════════════════════
#  UNIVERSITY AUTH
# ══════════════════════════════════════════════════
@app.route("/api/university/login", methods=["POST"])
def university_login():
    d  = request.json or {}
    db = get_db()
    row= db.execute("SELECT * FROM university WHERE username=?",
                    (d.get("username",""),)).fetchone()
    if not row or not check_password_hash(row["password"], d.get("password","")):
        return jsonify({"error":"Invalid credentials"}), 401
    token = make_token({"role":"university","username":row["username"],"name":row["name"]})
    return jsonify({"success":True,"token":token,"name":row["name"]})

@app.route("/api/university/logout", methods=["POST"])
def university_logout():
    return jsonify({"success":True})

# ══════════════════════════════════════════════════
#  UNIVERSITY — MCQ UPLOAD (CSV → DB)
# ══════════════════════════════════════════════════
@app.route("/api/university/upload-mcq", methods=["POST"])
@university_required
def upload_mcq():
    exam_type = request.form.get("exam_type","").upper()
    if exam_type not in ("NEET","JEE"):
        return jsonify({"error":"exam_type must be NEET or JEE"}), 400
    if "file" not in request.files:
        return jsonify({"error":"No file"}), 400
    file = request.files["file"]
    if not file.filename.endswith(".csv"):
        return jsonify({"error":"CSV only"}), 400

    try:
        df = pd.read_csv(file)
        df.columns = df.columns.str.lower().str.strip()
        required = {"question","option_a","option_b","option_c","option_d","correct_answer"}
        missing  = required - set(df.columns)
        if missing:
            return jsonify({"error":f"Missing columns: {missing}"}), 400
        if "subject" not in df.columns:
            df["subject"] = ""

        file_hash = hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()

        db = get_db()
        # Clear old questions for this exam type
        db.execute("DELETE FROM questions WHERE exam_type=?", (exam_type,))

        # Insert all questions
        for _, row in df.iterrows():
            db.execute("""
                INSERT INTO questions
                    (exam_type,question,option_a,option_b,option_c,option_d,
                     correct_answer,subject)
                VALUES (?,?,?,?,?,?,?,?)
            """, (exam_type, row["question"], row["option_a"], row["option_b"],
                  row["option_c"], row["option_d"], row["correct_answer"],
                  row.get("subject","")))

        # Update exam record
        db.execute("""
            INSERT INTO exams (exam_type, file_hash, question_count)
            VALUES (?,?,?)
            ON CONFLICT(exam_type) DO UPDATE SET
                file_hash=excluded.file_hash,
                question_count=excluded.question_count
        """, (exam_type, file_hash, len(df)))
        db.commit()

        # Store on blockchain
        try:
            contract = get_contract()
            if contract and w3.is_connected():
                contract.functions.createExam(
                    exam_type, 0, 0, file_hash
                ).transact({"from": w3.eth.accounts[0]})
        except Exception as e:
            print(f"[BLOCKCHAIN] {e}")

        return jsonify({
            "success":True,
            "exam_type":exam_type,
            "question_count":len(df),
            "file_hash":file_hash,
            "message":f"{len(df)} questions stored in database for {exam_type}",
        })
    except Exception as e:
        return jsonify({"error":str(e)}), 500

# ══════════════════════════════════════════════════
#  UNIVERSITY — BATCH MANAGEMENT
# ══════════════════════════════════════════════════
@app.route("/api/university/batches", methods=["POST"])
@university_required
def create_batch():
    d          = request.json or {}
    exam_type  = d.get("exam_type","").upper()
    batch_name = d.get("batch_name","").strip()
    start_time = d.get("start_time","")
    duration   = int(d.get("duration_minutes", 180))
    capacity   = int(d.get("capacity", 100))

    if exam_type not in ("NEET","JEE"):
        return jsonify({"error":"Invalid exam type"}), 400
    if not batch_name or not start_time:
        return jsonify({"error":"batch_name and start_time required"}), 400

    db   = get_db()
    exam = db.execute("SELECT id FROM exams WHERE exam_type=?",(exam_type,)).fetchone()
    if not exam:
        return jsonify({"error":"Upload MCQ for this exam type first"}), 400

    try:
        dt_utc = parse_utc(start_time).isoformat()
    except:
        return jsonify({"error":"Invalid date format"}), 400

    db.execute("""
        INSERT INTO batches (exam_type,batch_name,start_time,duration,capacity)
        VALUES (?,?,?,?,?)
    """, (exam_type, batch_name, dt_utc, duration, capacity))
    db.commit()
    return jsonify({"success":True,"message":f"Batch '{batch_name}' created"})

@app.route("/api/university/batches/<exam_type>", methods=["GET"])
@university_required
def get_batches_admin(exam_type):
    db   = get_db()
    rows = db.execute("""
        SELECT b.*, COUNT(s.id) as enrolled
        FROM batches b
        LEFT JOIN students s ON s.batch_id=b.id
        WHERE b.exam_type=?
        GROUP BY b.id ORDER BY b.start_time
    """, (exam_type.upper(),)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/university/batches/<int:bid>", methods=["DELETE"])
@university_required
def delete_batch(bid):
    db  = get_db()
    cnt = db.execute("SELECT COUNT(*) as c FROM students WHERE batch_id=?",(bid,)).fetchone()["c"]
    if cnt > 0:
        return jsonify({"error":f"Cannot delete — {cnt} students enrolled"}), 400
    db.execute("DELETE FROM batches WHERE id=?",(bid,))
    db.commit()
    return jsonify({"success":True})

@app.route("/api/university/batches/<int:bid>/csv", methods=["GET"])
@university_required
def download_batch_csv(bid):
    """Download batch CSV: name,email,batch_name,exam_time,paper_hash"""
    db    = get_db()
    batch = db.execute("SELECT * FROM batches WHERE id=?",(bid,)).fetchone()
    if not batch:
        return jsonify({"error":"Batch not found"}), 404
    students = db.execute("""
        SELECT s.name, s.email,
               b.batch_name, b.start_time, s.paper_hash
        FROM students s
        JOIN batches b ON b.id=s.batch_id
        WHERE s.batch_id=?
        ORDER BY s.name
    """, (bid,)).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["name","email","batch_name","exam_time","paper_hash"])
    for s in students:
        writer.writerow([s["name"],s["email"],
                         s["batch_name"],s["start_time"],s["paper_hash"]])
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"batch_{bid}_{batch['batch_name'].replace(' ','_')}.csv"
    )

@app.route("/api/university/stats", methods=["GET"])
@university_required
def university_stats():
    db    = get_db()
    stats = {}
    for et in ("NEET","JEE"):
        exam    = db.execute("SELECT * FROM exams WHERE exam_type=?",(et,)).fetchone()
        total   = db.execute("SELECT COUNT(*) as c FROM students WHERE exam_type=?",(et,)).fetchone()["c"]
        batches = db.execute("SELECT COUNT(*) as c FROM batches WHERE exam_type=?",(et,)).fetchone()["c"]
        stats[et] = {
            "total_registered": total,
            "batch_count":      batches,
            "exam_uploaded":    exam is not None,
            "question_count":   exam["question_count"] if exam else 0,
        }
    return jsonify(stats)

@app.route("/api/university/students/<exam_type>", methods=["GET"])
@university_required
def get_students(exam_type):
    db   = get_db()
    rows = db.execute("""
        SELECT s.id,s.name,s.email,s.exam_type,
               s.paper_hash,s.registered_at,
               b.batch_name,b.start_time as batch_time
        FROM students s
        LEFT JOIN batches b ON b.id=s.batch_id
        WHERE s.exam_type=?
        ORDER BY s.registered_at DESC
    """, (exam_type.upper(),)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/university/logs", methods=["GET"])
@university_required
def get_logs():
    db   = get_db()
    rows = db.execute("""
        SELECT l.*,s.name,s.exam_type
        FROM logs l
        LEFT JOIN students s ON s.id=l.student_id
        ORDER BY l.timestamp DESC LIMIT 300
    """).fetchall()
    return jsonify([dict(r) for r in rows])

# ══════════════════════════════════════════════════
#  PUBLIC — BATCH SLOTS FOR SIGNUP
# ══════════════════════════════════════════════════
@app.route("/api/batches/<exam_type>", methods=["GET"])
def public_batches(exam_type):
    db   = get_db()
    rows = db.execute("""
        SELECT b.id,b.batch_name,b.start_time,b.duration,
               b.capacity, COUNT(s.id) as enrolled
        FROM batches b
        LEFT JOIN students s ON s.batch_id=b.id
        WHERE b.exam_type=?
        GROUP BY b.id ORDER BY b.start_time
    """, (exam_type.upper(),)).fetchall()
    result = []
    now    = now_utc()
    for r in rows:
        d = dict(r)
        start = parse_utc(d["start_time"])
        # Hide batch from candidate portal if started more than 15 min ago
        if now > start + timedelta(minutes=15):
            continue
        d["slots_left"] = d["capacity"] - d["enrolled"]
        d["is_full"]    = d["enrolled"] >= d["capacity"]
        result.append(d)
    return jsonify(result)

# ══════════════════════════════════════════════════
#  CANDIDATE SIGNUP
# ══════════════════════════════════════════════════
@app.route("/api/candidate/signup", methods=["POST"])
def candidate_signup():
    d           = request.json or {}
    name        = d.get("name","").strip()
    email       = d.get("email","").strip().lower()
    exam_type   = d.get("exam_type","").upper()
    password    = d.get("password","")
    batch_id    = d.get("batch_id")

    if not all([name,email,exam_type,password,batch_id]):
        return jsonify({"error":"All fields required including batch"}), 400
    if exam_type not in ("NEET","JEE"):
        return jsonify({"error":"Invalid exam type"}), 400
    if len(password) < 6:
        return jsonify({"error":"Password min 6 characters"}), 400

    db = get_db()

    exam = db.execute("SELECT id FROM exams WHERE exam_type=?",(exam_type,)).fetchone()
    if not exam:
        return jsonify({"error":"Exam not configured yet"}), 400

    batch = db.execute("""
        SELECT b.*, COUNT(s.id) as enrolled
        FROM batches b LEFT JOIN students s ON s.batch_id=b.id
        WHERE b.id=? AND b.exam_type=? GROUP BY b.id
    """, (batch_id, exam_type)).fetchone()
    if not batch:
        return jsonify({"error":"Invalid batch"}), 400
    if batch["enrolled"] >= batch["capacity"]:
        return jsonify({"error":"Batch full — choose another slot"}), 400

    if db.execute("SELECT id FROM students WHERE email=? AND exam_type=?",
                  (email,exam_type)).fetchone():
        return jsonify({"error":"Email already registered for this exam"}), 409

    paper_hash = make_paper_hash(name,email,exam_type)
    db.execute("""
        INSERT INTO students
            (name,email,password,exam_type,batch_id,paper_hash)
        VALUES (?,?,?,?,?,?)
    """, (name,email,generate_password_hash(password),
          exam_type,batch_id,paper_hash))

    sid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    log_event(sid,"SIGNUP",f"{exam_type} batch {batch['batch_name']}")
    db.commit()

    send_email(email,name,exam_type,batch["batch_name"],batch["start_time"])

    return jsonify({
        "success":True,
        "message":f"Registered! Confirmation sent to {email}",
        "batch_name":batch["batch_name"],
        "start_time":batch["start_time"],
    })

# ══════════════════════════════════════════════════
#  CANDIDATE LOGIN
# ══════════════════════════════════════════════════
@app.route("/api/candidate/login", methods=["POST"])
def candidate_login():
    d         = request.json or {}
    email     = d.get("email","").strip().lower()
    password  = d.get("password","")
    exam_type = d.get("exam_type","").upper()
    ua        = d.get("user_agent", request.headers.get("User-Agent",""))
    screen    = d.get("screen_info","")

    if not all([email,password,exam_type]):
        return jsonify({"error":"Email, password and exam type required"}), 400

    db  = get_db()
    row = db.execute("""
        SELECT s.*,b.batch_name,b.start_time,b.duration
        FROM students s
        LEFT JOIN batches b ON b.id=s.batch_id
        WHERE s.email=? AND s.exam_type=?
    """, (email,exam_type)).fetchone()

    if not row:
        return jsonify({"error":"Email not registered for this exam"}), 404
    if not check_password_hash(row["password"], password):
        log_event(row["id"],"LOGIN_FAIL","Wrong password")
        return jsonify({"error":"Incorrect password"}), 401

    # Device fingerprint
    fp = make_fp(ua, screen, request.remote_addr)
    if row["device_fingerprint"] is None:
        # First login — bind device
        db.execute("UPDATE students SET device_fingerprint=? WHERE id=?",(fp,row["id"]))
        db.commit()
    elif row["device_fingerprint"] != fp:
        log_event(row["id"],"DEVICE_MISMATCH",request.remote_addr)
        return jsonify({
            "error":"Access denied — use your registered device. Contact admin if issue persists."
        }), 403

    log_event(row["id"],"LOGIN",request.remote_addr)

    token = make_token({
        "role":       "student",
        "student_id": row["id"],
        "email":      email,
        "exam_type":  exam_type,
        "name":       row["name"],
        "device_fp":  fp,
    })

    return jsonify({
        "success":    True,
        "token":      token,
        "name":       row["name"],
        "exam_type":  exam_type,
        "batch_name": row["batch_name"],
        "start_time": row["start_time"],
        "duration":   row["duration"],
    })

# ══════════════════════════════════════════════════
#  CANDIDATE EXAM
# ══════════════════════════════════════════════════
@app.route("/api/candidate/exam-status", methods=["GET"])
@student_required
def exam_status():
    db  = get_db()
    sid = g.student["student_id"]
    row = db.execute("""
        SELECT s.*,b.start_time,b.duration,b.batch_name
        FROM students s JOIN batches b ON b.id=s.batch_id
        WHERE s.id=?
    """, (sid,)).fetchone()
    if not row: return jsonify({"error":"Not found"}), 404

    now   = now_utc()
    start = parse_utc(row["start_time"])
    end   = start + timedelta(minutes=row["duration"])

    sub = db.execute("SELECT submitted_at FROM exam_sessions WHERE student_id=?",(sid,)).fetchone()

    if   now < start: status = "before"
    elif now > end:   status = "after"
    else:             status = "during"

    return jsonify({
        "name":                row["name"],
        "exam_type":           row["exam_type"],
        "batch_name":          row["batch_name"],
        "start_time":          row["start_time"],
        "duration":            row["duration"],
        "server_time":         now.isoformat(),
        "status":              status,
        "seconds_until_start": max(0,int((start-now).total_seconds())) if status=="before" else 0,
        "seconds_remaining":   max(0,int((end-now).total_seconds()))   if status=="during" else 0,
        "submitted":           sub is not None and sub["submitted_at"] is not None,
    })

@app.route("/api/candidate/access-paper", methods=["POST"])
@student_required
def access_paper():
    db  = get_db()
    sid = g.student["student_id"]
    et  = g.student["exam_type"]

    row = db.execute("""
        SELECT s.*,b.start_time,b.duration
        FROM students s JOIN batches b ON b.id=s.batch_id
        WHERE s.id=?
    """, (sid,)).fetchone()
    if not row: return jsonify({"error":"Not found"}), 404

    now   = now_utc()
    start = parse_utc(row["start_time"])
    end   = start + timedelta(minutes=row["duration"])

    if now < start:
        return jsonify({"error":"Exam not started yet",
                        "starts_in_seconds":int((start-now).total_seconds())}), 403
    if now > end:
        return jsonify({"error":"Exam window closed"}), 403

    ex = db.execute("SELECT * FROM exam_sessions WHERE student_id=?",(sid,)).fetchone()
    if ex and ex["submitted_at"]:
        return jsonify({"error":"Already submitted"}), 403
    if not ex:
        db.execute("INSERT INTO exam_sessions(student_id,started_at) VALUES(?,?)",
                   (sid, now.isoformat()))
        db.commit()
        log_event(sid,"EXAM_START",et)

    questions = get_shuffled_questions(et, row["paper_hash"])
    return jsonify({
        "success":True,
        "student_name":    row["name"],
        "exam_type":       et,
        "questions":       questions,
        "question_count":  len(questions),
        "duration_minutes":row["duration"],
        "seconds_remaining":max(0,int((end-now).total_seconds())),
    })

@app.route("/api/candidate/submit", methods=["POST"])
@student_required
def submit_exam():
    db      = get_db()
    sid     = g.student["student_id"]
    answers = (request.json or {}).get("answers",{})

    row = db.execute("""
        SELECT s.*,b.start_time,b.duration
        FROM students s JOIN batches b ON b.id=s.batch_id WHERE s.id=?
    """, (sid,)).fetchone()

    now = now_utc()
    end = parse_utc(row["start_time"]) + timedelta(minutes=row["duration"])
    if now > end:
        return jsonify({"error":"Exam window closed"}), 403

    ex = db.execute("SELECT * FROM exam_sessions WHERE student_id=?",(sid,)).fetchone()
    if ex and ex["submitted_at"]:
        return jsonify({"error":"Already submitted"}), 400

    if ex:
        db.execute("UPDATE exam_sessions SET submitted_at=?,answers=? WHERE student_id=?",
                   (now.isoformat(), json.dumps(answers), sid))
    else:
        db.execute("""INSERT INTO exam_sessions
                      (student_id,started_at,submitted_at,answers)
                      VALUES(?,?,?,?)""",
                   (sid,now.isoformat(),now.isoformat(),json.dumps(answers)))
    db.commit()
    log_event(sid,"EXAM_SUBMIT",f"{len(answers)} answers")
    return jsonify({"success":True,"submitted_at":now.isoformat(),"answers_count":len(answers)})

# ══════════════════════════════════════════════════
#  EXAM REMINDER — called by a cron job or scheduler
# ══════════════════════════════════════════════════
@app.route("/api/university/send-reminders/<int:bid>", methods=["POST"])
@university_required
def send_batch_reminders(bid):
    db    = get_db()
    batch = db.execute("SELECT * FROM batches WHERE id=?",(bid,)).fetchone()
    if not batch: return jsonify({"error":"Batch not found"}), 404
    students = db.execute(
        "SELECT name,email FROM students WHERE batch_id=?",(bid,)
    ).fetchall()
    sent = 0
    for s in students:
        if send_exam_reminder(s["email"],s["name"],batch["exam_type"],
                              batch["batch_name"],batch["start_time"]):
            sent += 1
    return jsonify({"success":True,"sent":sent,"total":len(students)})

# ══════════════════════════════════════════════════
#  EXAM SESSIONS — enriched with student info
# ══════════════════════════════════════════════════
@app.route("/api/university/exam-sessions/<exam_type>", methods=["GET"])
@university_required
def get_exam_sessions(exam_type):
    db   = get_db()
    rows = db.execute("""
        SELECT es.id, es.student_id, es.started_at, es.submitted_at, es.answers,
               s.name, s.email, s.paper_hash, s.batch_id,
               b.batch_name, b.exam_type
        FROM exam_sessions es
        JOIN students s ON s.id = es.student_id
        JOIN batches b ON b.id = s.batch_id
        WHERE b.exam_type = ?
        ORDER BY es.submitted_at DESC
    """, (exam_type.upper(),)).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["answers_count"] = len(json.loads(d["answers"] or "{}"))
        result.append(d)
    return jsonify(result)

# ══════════════════════════════════════════════════
#  RESULTS — Grade & Publish
# ══════════════════════════════════════════════════
@app.route("/api/university/grade-batch/<int:bid>", methods=["POST"])
@university_required
def grade_batch(bid):
    """Grade all submitted sessions in a batch against correct answers."""
    db    = get_db()
    batch = db.execute("SELECT * FROM batches WHERE id=?",(bid,)).fetchone()
    if not batch: return jsonify({"error":"Batch not found"}), 404

    # Get all questions with correct answers for this exam type
    questions = db.execute(
        "SELECT id, correct_answer FROM questions WHERE exam_type=?",
        (batch["exam_type"],)
    ).fetchall()
    correct_map = {str(q["id"]): q["correct_answer"].strip().lower() for q in questions}

    # Get all submitted sessions for this batch
    sessions = db.execute("""
        SELECT es.student_id, es.answers, es.submitted_at
        FROM exam_sessions es
        JOIN students s ON s.id = es.student_id
        WHERE s.batch_id = ? AND es.submitted_at IS NOT NULL
    """, (bid,)).fetchall()

    graded = []
    for ses in sessions:
        student_answers = json.loads(ses["answers"] or "{}")
        score = 0
        total = len(correct_map)
        # student answers are stored as {question_index: option_letter}
        # We need to map index back to question id
        # Get shuffled question order for this student
        student = db.execute("SELECT paper_hash FROM students WHERE id=?",(ses["student_id"],)).fetchone()
        shuffled = get_shuffled_questions(batch["exam_type"], student["paper_hash"])
        for idx_str, chosen in student_answers.items():
            idx = int(idx_str)
            if idx < len(shuffled):
                qid  = str(shuffled[idx]["id"])
                correct = correct_map.get(qid,"")
                if chosen.lower() == correct:
                    score += 1

        percentage  = round((score / total * 100), 2) if total > 0 else 0
        result_hash = make_result_hash(ses["student_id"], bid, score, total, ses["submitted_at"])

        # Upsert result
        db.execute("""
            INSERT INTO results (student_id, batch_id, exam_type, score, total, percentage, result_hash)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(student_id) DO UPDATE SET
                score=excluded.score, total=excluded.total,
                percentage=excluded.percentage, result_hash=excluded.result_hash,
                published_at=excluded.published_at
        """, (ses["student_id"], bid, batch["exam_type"], score, total, percentage, result_hash))

        graded.append({"student_id": ses["student_id"], "score": score, "total": total, "percentage": percentage})

    db.commit()
    return jsonify({"success":True,"graded":len(graded),"results":graded})

@app.route("/api/university/publish-results/<int:bid>", methods=["POST"])
@university_required
def publish_results(bid):
    """Email results to all students in a batch."""
    db    = get_db()
    batch = db.execute("SELECT * FROM batches WHERE id=?",(bid,)).fetchone()
    if not batch: return jsonify({"error":"Batch not found"}), 404

    rows = db.execute("""
        SELECT r.score, r.total, r.percentage, r.result_hash,
               s.name, s.email, r.exam_type
        FROM results r
        JOIN students s ON s.id = r.student_id
        WHERE r.batch_id = ?
    """, (bid,)).fetchall()

    if not rows:
        return jsonify({"error":"Grade the batch first before publishing"}), 400

    sent = 0
    for r in rows:
        if send_result_email(r["email"], r["name"], r["exam_type"],
                             r["score"], r["total"], r["percentage"], r["result_hash"]):
            sent += 1

    return jsonify({"success":True,"sent":sent,"total":len(rows)})

@app.route("/api/university/results/<exam_type>", methods=["GET"])
@university_required
def get_results(exam_type):
    db   = get_db()
    rows = db.execute("""
        SELECT r.*, s.name, s.email, b.batch_name
        FROM results r
        JOIN students s ON s.id = r.student_id
        JOIN batches b ON b.id = r.batch_id
        WHERE r.exam_type = ?
        ORDER BY r.percentage DESC
    """, (exam_type.upper(),)).fetchall()
    return jsonify([dict(r) for r in rows])

# ══════════════════════════════════════════════════
#  DB ADMIN — Separate password, full DB access
# ══════════════════════════════════════════════════
@app.route("/api/dbadmin/login", methods=["POST"])
def dbadmin_login():
    d = request.json or {}
    if d.get("password") != DB_ADMIN_PASS:
        return jsonify({"error":"Wrong DB admin password"}), 401
    session["db_admin"] = True
    return jsonify({"success":True})

@app.route("/api/dbadmin/logout", methods=["POST"])
def dbadmin_logout():
    session.pop("db_admin",None)
    return jsonify({"success":True})

@app.route("/api/dbadmin/tables", methods=["GET"])
@db_admin_required
def dbadmin_tables():
    db   = get_db()
    rows = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return jsonify([r["name"] for r in rows])

@app.route("/api/dbadmin/table/<name>", methods=["GET"])
@db_admin_required
def dbadmin_table(name):
    # Whitelist tables
    allowed = {"university","exams","questions","batches",
               "students","logs","exam_sessions","results"}
    if name not in allowed:
        return jsonify({"error":"Not allowed"}), 403
    db   = get_db()
    rows = db.execute(f"SELECT * FROM {name} ORDER BY id DESC LIMIT 500").fetchall()
    cols = [d[0] for d in db.execute(f"SELECT * FROM {name} LIMIT 1").description or []]
    return jsonify({"columns":cols,"rows":[dict(r) for r in rows]})

@app.route("/api/dbadmin/questions", methods=["POST"])
@db_admin_required
def dbadmin_add_question():
    d = request.json or {}
    required = ["exam_type","question","option_a","option_b",
                "option_c","option_d","correct_answer"]
    if not all(d.get(k) for k in required):
        return jsonify({"error":"All question fields required"}), 400
    db = get_db()
    db.execute("""
        INSERT INTO questions
            (exam_type,question,option_a,option_b,option_c,
             option_d,correct_answer,subject)
        VALUES (?,?,?,?,?,?,?,?)
    """, (d["exam_type"].upper(), d["question"], d["option_a"],
          d["option_b"], d["option_c"], d["option_d"],
          d["correct_answer"], d.get("subject","")))
    # Update question count
    count = db.execute("SELECT COUNT(*) as c FROM questions WHERE exam_type=?",
                       (d["exam_type"].upper(),)).fetchone()["c"]
    db.execute("UPDATE exams SET question_count=? WHERE exam_type=?",
               (count, d["exam_type"].upper()))
    db.commit()
    return jsonify({"success":True,"message":"Question added"})

@app.route("/api/dbadmin/questions/<int:qid>", methods=["PUT"])
@db_admin_required
def dbadmin_edit_question(qid):
    d  = request.json or {}
    db = get_db()
    db.execute("""
        UPDATE questions SET
            question=?,option_a=?,option_b=?,option_c=?,
            option_d=?,correct_answer=?,subject=?
        WHERE id=?
    """, (d.get("question"), d.get("option_a"), d.get("option_b"),
          d.get("option_c"), d.get("option_d"), d.get("correct_answer"),
          d.get("subject",""), qid))
    db.commit()
    return jsonify({"success":True})

@app.route("/api/dbadmin/questions/<int:qid>", methods=["DELETE"])
@db_admin_required
def dbadmin_delete_question(qid):
    db = get_db()
    row= db.execute("SELECT exam_type FROM questions WHERE id=?",(qid,)).fetchone()
    if not row: return jsonify({"error":"Not found"}), 404
    db.execute("DELETE FROM questions WHERE id=?",(qid,))
    count = db.execute("SELECT COUNT(*) as c FROM questions WHERE exam_type=?",
                       (row["exam_type"],)).fetchone()["c"]
    db.execute("UPDATE exams SET question_count=? WHERE exam_type=?",
               (count,row["exam_type"]))
    db.commit()
    return jsonify({"success":True})

@app.route("/api/dbadmin/sql", methods=["POST"])
@db_admin_required
def dbadmin_sql():
    """Run raw SELECT queries only."""
    d     = request.json or {}
    query = d.get("query","").strip()
    if not query.upper().startswith("SELECT"):
        return jsonify({"error":"Only SELECT queries allowed"}), 400
    try:
        db   = get_db()
        rows = db.execute(query).fetchall()
        cols = [desc[0] for desc in db.execute(query).description]
        return jsonify({"columns":cols,"rows":[dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"error":str(e)}), 400

# ══════════════════════════════════════════════════
#  STATIC
# ══════════════════════════════════════════════════

@app.route("/health")
def health():
    return {"status": "ok"}, 200

@app.route("/")
def landing():
    return send_from_directory(os.path.join(FRONTEND_DIR,"landing"),"index.html")

@app.route("/university")
def university_portal():
    return send_from_directory(os.path.join(FRONTEND_DIR,"university"),"index.html")

@app.route("/candidate")
def candidate_portal():
    return send_from_directory(os.path.join(FRONTEND_DIR,"candidate"),"index.html")

@app.route("/dbadmin")
def db_admin_portal():
    return send_from_directory(os.path.join(FRONTEND_DIR,"dbadmin"),"index.html")

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(FRONTEND_DIR, path)

# ══════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════
if __name__ == "__main__":
    init_db()
    print("="*50)
    print("ExamShield v4")
    print(f"Ganache : {w3.is_connected()}")
    print(f"DB      : {DB_PATH}")
    print(f"DB Admin: http://localhost:5000/dbadmin")
    print("="*50)
    app.run(debug=True, port=5000)
