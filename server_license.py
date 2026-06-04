"""
SERVER DI LICENZE - Backend minimalista
Stack: Python + FastAPI + SQLite
Deploy gratuito su: Railway, Render, o Fly.io

Installazione:
    pip install fastapi uvicorn

Avvio:
    uvicorn server_license:app --host 0.0.0.0 --port 8000
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, timedelta
import sqlite3
import secrets
import string

app = FastAPI(title="License Server")
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# DATABASE SETUP
# ============================================================
def get_db():
    conn = sqlite3.connect("/data/licenses.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS licenses (
            key         TEXT PRIMARY KEY,
            email       TEXT,
            created_at  TEXT,
            expires_at  TEXT,
            max_seats   INTEGER DEFAULT 1,
            active_seats INTEGER DEFAULT 0,
            is_active   INTEGER DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS activations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            license_key TEXT,
            machine_id  TEXT,
            activated_at TEXT,
            last_seen   TEXT,
            UNIQUE(license_key, machine_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS synced_data (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id  TEXT,
            license_key TEXT,
            synced_at   TEXT,
            rows_count  INTEGER,
            data        TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ============================================================
# MODELLI
# ============================================================
class ActivateRequest(BaseModel):
    license_key: str
    machine_id: str

class DeactivateRequest(BaseModel):
    machine_id: str

class CreateLicenseRequest(BaseModel):
    email: str
    days_valid: int = 0       # 0 = lifetime
    max_seats: int = 1
    secret: str               # Password admin

ADMIN_SECRET = "Nonmispammare96"  # ← CAMBIA QUESTO!

# ============================================================
# GENERATORE DI CHIAVI
# ============================================================
def generate_key() -> str:
    chars = string.ascii_uppercase + string.digits
    groups = [''.join(secrets.choice(chars) for _ in range(4)) for _ in range(4)]
    return '-'.join(groups)

# ============================================================
# ENDPOINTS
# ============================================================

@app.post("/api/activate")
def activate(req: ActivateRequest):
    conn = get_db()
    
    # 1. Controlla se la licenza esiste
    lic = conn.execute(
        "SELECT * FROM licenses WHERE key = ?", (req.license_key,)
    ).fetchone()
    
    if not lic:
        conn.close()
        return {"status": "INVALID_KEY"}
    
    if not lic["is_active"]:
        conn.close()
        return {"status": "INVALID_KEY"}
    
    # 2. Controlla scadenza
    if lic["expires_at"]:
        if datetime.fromisoformat(lic["expires_at"]) < datetime.now():
            conn.close()
            return {"status": "EXPIRED"}
    
    # 3. Controlla se questa macchina è già attivata (= riapertura normale)
    existing = conn.execute(
        "SELECT * FROM activations WHERE license_key = ? AND machine_id = ?",
        (req.license_key, req.machine_id)
    ).fetchone()
    
    if existing:
        # Aggiorna last_seen e approva
        conn.execute(
            "UPDATE activations SET last_seen = ? WHERE license_key = ? AND machine_id = ?",
            (datetime.now().isoformat(), req.license_key, req.machine_id)
        )
        conn.commit()
        conn.close()
        return {"status": "OK", "message": "Already activated on this machine"}
    
    # 4. Controlla se ha ancora posti disponibili
    if lic["active_seats"] >= lic["max_seats"]:
        conn.close()
        return {"status": "ALREADY_ACTIVATED", "message": "Max seats reached"}
    
    # 5. Nuova attivazione
    conn.execute(
        "INSERT INTO activations (license_key, machine_id, activated_at, last_seen) VALUES (?,?,?,?)",
        (req.license_key, req.machine_id, datetime.now().isoformat(), datetime.now().isoformat())
    )
    conn.execute(
        "UPDATE licenses SET active_seats = active_seats + 1 WHERE key = ?",
        (req.license_key,)
    )
    conn.commit()
    conn.close()
    return {"status": "OK", "message": "Activated successfully"}


@app.post("/api/deactivate")
def deactivate(req: DeactivateRequest):
    conn = get_db()
    activation = conn.execute(
        "SELECT * FROM activations WHERE machine_id = ?", (req.machine_id,)
    ).fetchone()
    
    if activation:
        conn.execute(
            "DELETE FROM activations WHERE machine_id = ?", (req.machine_id,)
        )
        conn.execute(
            "UPDATE licenses SET active_seats = active_seats - 1 WHERE key = ?",
            (activation["license_key"],)
        )
        conn.commit()
    
    conn.close()
    return {"status": "OK"}


@app.post("/api/admin/create-license")
def create_license(req: CreateLicenseRequest):
    if req.secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    key = generate_key()
    expires = None
    if req.days_valid > 0:
        expires = (datetime.now() + timedelta(days=req.days_valid)).isoformat()
    
    conn = get_db()
    conn.execute(
        "INSERT INTO licenses (key, email, created_at, expires_at, max_seats) VALUES (?,?,?,?,?)",
        (key, req.email, datetime.now().isoformat(), expires, req.max_seats)
    )
    conn.commit()
    conn.close()
    
    return {
        "status": "OK",
        "license_key": key,
        "email": req.email,
        "expires_at": expires or "never",
        "max_seats": req.max_seats
    }







@app.delete("/api/admin/synced-data/{sync_id}")
def delete_sync(sync_id: int, secret: str):
    if secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Unauthorized")
    conn = get_db()
    conn.execute("DELETE FROM synced_data WHERE id = ?", (sync_id,))
    conn.commit()
    conn.close()
    return {"status": "OK", "deleted": sync_id}



@app.get("/api/admin/synced-data")
def get_synced_data(secret: str):
    if secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Unauthorized")
    conn = get_db()
    rows = conn.execute("SELECT * FROM synced_data ORDER BY synced_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]






@app.get("/api/admin/licenses")
def list_licenses(secret: str):
    if secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    conn = get_db()
    licenses = conn.execute("SELECT * FROM licenses").fetchall()
    conn.close()
    return [dict(l) for l in licenses]


@app.delete("/api/admin/license/{license_key}")
def delete_license(license_key: str, secret: str):
    if secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Unauthorized")
    conn = get_db()
    conn.execute("DELETE FROM activations WHERE license_key = ?", (license_key,))
    conn.execute("DELETE FROM licenses WHERE key = ?", (license_key,))
    conn.commit()
    conn.close()
    return {"status": "OK", "deleted": license_key}

@app.post("/api/admin/license/{license_key}/disable")
def disable_license(license_key: str, secret: str):
    if secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Unauthorized")
    conn = get_db()
    conn.execute("UPDATE licenses SET is_active = 0 WHERE key = ?", (license_key,))
    conn.commit()
    conn.close()
    return {"status": "OK", "disabled": license_key}

@app.post("/api/admin/license/{license_key}/enable")
def enable_license(license_key: str, secret: str):
    if secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Unauthorized")
    conn = get_db()
    conn.execute("UPDATE licenses SET is_active = 1 WHERE key = ?", (license_key,))
    conn.commit()
    conn.close()
    return {"status": "OK", "enabled": license_key}

@app.delete("/api/admin/license/{license_key}/activations")
def reset_activations(license_key: str, secret: str):
    if secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Unauthorized")
    conn = get_db()
    conn.execute("DELETE FROM activations WHERE license_key = ?", (license_key,))
    conn.execute("UPDATE licenses SET active_seats = 0 WHERE key = ?", (license_key,))
    conn.commit()
    conn.close()
    return {"status": "OK", "reset": license_key}














import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fastapi import Request as FastAPIRequest

@app.post("/api/data/sync")
async def sync_data(request: FastAPIRequest):
    try:
        body = await request.json()
    except:
        body = {}
    
    machine_id = str(body.get("machine_id", ""))
    license_key = str(body.get("license_key", ""))
    rows_count = int(body.get("rows_count", 0))
    data = str(body.get("data", ""))
    
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS synced_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id TEXT,
            license_key TEXT,
            synced_at TEXT,
            rows_count INTEGER,
            data TEXT
        )
    """)
    conn.execute(
        "INSERT INTO synced_data (machine_id, license_key, synced_at, rows_count, data) VALUES (?,?,?,?,?)",
        (machine_id, license_key, datetime.now().isoformat(), rows_count, data)
    )
    conn.commit()
    conn.close()
    return {"status": "OK"}









@app.post("/api/admin/pun")
async def update_pun(request: FastAPIRequest, secret: str):
    if secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Unauthorized")
    body = await request.json()
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pun_data (
            id INTEGER PRIMARY KEY,
            mensili TEXT,
            giornalieri TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("DELETE FROM pun_data")
    conn.execute(
        "INSERT INTO pun_data (id, mensili, giornalieri, updated_at) VALUES (1, ?, ?, ?)",
        (body.get("mensili", ""), body.get("giornalieri", ""), datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
    return {"status": "OK"}

@app.get("/api/pun")
def get_pun():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pun_data (
            id INTEGER PRIMARY KEY,
            mensili TEXT,
            giornalieri TEXT,
            updated_at TEXT
        )
    """)
    row = conn.execute("SELECT * FROM pun_data WHERE id=1").fetchone()
    conn.close()
    if not row:
        return {"mensili": "", "giornalieri": "", "updated_at": ""}
    return dict(row)








@app.get("/api/version")
def get_version():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_version (
            id INTEGER PRIMARY KEY,
            version TEXT,
            download_url TEXT,
            note TEXT,
            updated_at TEXT
        )
    """)
    row = conn.execute("SELECT * FROM app_version WHERE id=1").fetchone()
    conn.close()
    if not row:
        return {"version": "1.0", "download_url": "", "note": "", "updated_at": ""}
    return dict(row)

@app.post("/api/admin/version")
async def update_version(request: FastAPIRequest, secret: str):
    if secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Unauthorized")
    body = await request.json()
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_version (
            id INTEGER PRIMARY KEY,
            version TEXT,
            download_url TEXT,
            note TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("DELETE FROM app_version")
    conn.execute(
        "INSERT INTO app_version (id, version, download_url, note, updated_at) VALUES (1, ?, ?, ?, ?)",
        (body.get("version", "1.0"), body.get("download_url", ""), body.get("note", ""), datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
    return {"status": "OK"}






