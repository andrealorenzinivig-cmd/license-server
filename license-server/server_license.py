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

# ============================================================
# DATABASE SETUP
# ============================================================
def get_db():
    conn = sqlite3.connect("licenses.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS licenses (
            key         TEXT PRIMARY KEY,
            email       TEXT,
            created_at  TEXT,
            expires_at  TEXT,        -- NULL = lifetime
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

ADMIN_SECRET = "cambia-questa-password-admin"  # ← CAMBIA QUESTO!

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


@app.get("/api/admin/licenses")
def list_licenses(secret: str):
    if secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    conn = get_db()
    licenses = conn.execute("SELECT * FROM licenses").fetchall()
    conn.close()
    return [dict(l) for l in licenses]


@app.get("/")
def health():
    return {"status": "running", "service": "License Server"}
