"""DataNexus Pro backend API. Production secrets and admin roles are server-side only."""
from __future__ import annotations
import os, sqlite3, secrets, hashlib, hmac, time, json, csv, io, logging, shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import Flask, request, jsonify, session, g, send_file, send_from_directory, abort
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("DNX_DATABASE_PATH", ROOT / "data" / "datanexus.sqlite3"))
BACKUP_DIR = Path(os.environ.get("DNX_BACKUP_DIR", ROOT / "backups"))
ROLES = {"Owner", "Developer", "Admin", "Staff", "Customer"}
app = Flask(__name__)
secret = os.environ.get("DNX_SECRET_KEY")
if not secret or len(secret) < 32:
    # Refuse to start with an unsafe implicit secret in production.
    if os.environ.get("DNX_ENV", "development") == "production":
        raise RuntimeError("DNX_SECRET_KEY must be set to a random value of at least 32 characters")
    secret = os.environ.setdefault("DNX_SECRET_KEY", secrets.token_urlsafe(48))
app.secret_key = secret
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
                  SESSION_COOKIE_SECURE=os.environ.get("DNX_COOKIE_SECURE", "0") == "1",
                  PERMANENT_SESSION_LIFETIME=timedelta(minutes=int(os.environ.get("DNX_SESSION_MINUTES", "60"))),
                  MAX_CONTENT_LENGTH=2 * 1024 * 1024)
logging.basicConfig(level=os.environ.get("DNX_LOG_LEVEL", "INFO"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL, email TEXT NOT NULL DEFAULT '', password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('Owner','Developer','Admin','Staff','Customer')), disabled INTEGER NOT NULL DEFAULT 0, mfa_secret TEXT, mfa_enabled INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, last_login TEXT);
CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id TEXT, actor_name TEXT, action TEXT NOT NULL, target TEXT, ip TEXT, created_at TEXT NOT NULL, detail_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS application_logs(id INTEGER PRIMARY KEY AUTOINCREMENT, level TEXT NOT NULL, message TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'backend', created_at TEXT NOT NULL, request_id TEXT);
CREATE TABLE IF NOT EXISTS feature_flags(name TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0, description TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS announcements(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, body TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, created_by TEXT);
CREATE TABLE IF NOT EXISTS releases(id INTEGER PRIMARY KEY AUTOINCREMENT, version TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '', deployed_at TEXT, status TEXT NOT NULL DEFAULT 'recorded', created_at TEXT NOT NULL, created_by TEXT);
CREATE TABLE IF NOT EXISTS backups(id TEXT PRIMARY KEY, filename TEXT NOT NULL, size_bytes INTEGER NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL, status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS integration_status(name TEXT PRIMARY KEY, configured INTEGER NOT NULL DEFAULT 0, last_check TEXT, status TEXT NOT NULL DEFAULT 'not_configured', safe_detail TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT);
CREATE TABLE IF NOT EXISTS webhooks(id TEXT PRIMARY KEY, name TEXT NOT NULL, endpoint TEXT NOT NULL, secret_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS api_events(id INTEGER PRIMARY KEY AUTOINCREMENT, method TEXT NOT NULL, path TEXT NOT NULL, status INTEGER NOT NULL, duration_ms INTEGER NOT NULL, created_at TEXT NOT NULL, actor_id TEXT);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_app_logs_created ON application_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_api_events_created ON api_events(created_at);
"""

def now(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c=sqlite3.connect(DB_PATH, timeout=10); c.row_factory=sqlite3.Row; c.execute("PRAGMA foreign_keys=ON"); c.execute("PRAGMA journal_mode=WAL"); return c

def init_db():
    with connect() as c:
        c.executescript(SCHEMA)
        # MFA is disabled in this edition; clear legacy enrollment on existing databases.
        c.execute("UPDATE users SET mfa_enabled=0, mfa_secret=NULL WHERE mfa_enabled<>0 OR mfa_secret IS NOT NULL")
        c.execute("INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(1,?)", (now(),))
        for name,desc in [("maintenance_mode","Show maintenance banner and restrict normal access"),("live_tracking","Enable live tracking integration"),("public_signup","Allow public self-registration")]:
            c.execute("INSERT OR IGNORE INTO feature_flags(name,enabled,description,updated_at) VALUES(?,0,?,?)",(name,desc,now()))
        for name in ["email","maps","tracking","webhooks","push"]:
            c.execute("INSERT OR IGNORE INTO integration_status(name,configured,status,safe_detail) VALUES(?,0,'not_configured','Provider credentials or endpoint not configured')",(name,))
init_db()

def audit(action, target=None, detail=None):
    u=getattr(g,"user",None)
    with connect() as c: c.execute("INSERT INTO audit_logs(actor_id,actor_name,action,target,ip,created_at,detail_json) VALUES(?,?,?,?,?,?,?)",(u["id"] if u else None,u["username"] if u else "system",action,target,request.remote_addr,now(),json.dumps(detail or {},separators=(",",":"))))

def role_required(*roles):
    def deco(fn):
        @wraps(fn)
        def inner(*a,**kw):
            uid=session.get("uid")
            if not uid: return jsonify(error="Authentication required"),401
            with connect() as c: u=c.execute("SELECT * FROM users WHERE id=? AND disabled=0",(uid,)).fetchone()
            if not u: session.clear(); return jsonify(error="Session expired or account disabled"),401
            g.user=u
            if u["role"] not in roles: return jsonify(error="Insufficient server-side permissions"),403
            return fn(*a,**kw)
        return inner
    return deco

def owner_or_dev(fn): return role_required("Owner","Developer")(fn)
def owner_only(fn): return role_required("Owner")(fn)

def origin_guard():
    if request.method in {"POST","PUT","PATCH","DELETE"}:
        origin=request.headers.get("Origin")
        if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
            return jsonify(error="Cross-origin request rejected"),403
    return None

@app.before_request
def before():
    g.started=time.monotonic()
    if request.path.startswith("/api/"):
        denied=origin_guard()
        if denied: return denied

@app.after_request
def after(resp):
    if request.path.startswith("/api/") and request.path != "/api/health":
        try:
            with connect() as c: c.execute("INSERT INTO api_events(method,path,status,duration_ms,created_at,actor_id) VALUES(?,?,?,?,?,?)",(request.method,request.path,resp.status_code,int((time.monotonic()-getattr(g,'started',time.monotonic()))*1000),now(),session.get("uid")))
        except Exception: app.logger.exception("Unable to record API event")
    resp.headers["X-Content-Type-Options"]="nosniff"; resp.headers["Referrer-Policy"]="same-origin"; resp.headers["Cache-Control"]="no-store"
    return resp

@app.errorhandler(HTTPException)
def handle_http_error(e):
    return jsonify(error=e.description), e.code

@app.errorhandler(Exception)
def handle_error(e):
    app.logger.exception("Unhandled request error")
    with connect() as c: c.execute("INSERT INTO application_logs(level,message,source,created_at) VALUES('error',?,'backend',?)",(type(e).__name__,now()))
    return jsonify(error="Internal server error"),500

@app.get("/api/health")
def health():
    try:
        with connect() as c: c.execute("SELECT 1").fetchone(); version=c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        return jsonify(status="ok",database="reachable",schema_version=version,server_time=now())
    except Exception: return jsonify(status="degraded",database="unavailable"),503

@app.post("/api/auth/login")
def login():
    d=request.get_json(silent=True) or {}; username=str(d.get("username"," ")).strip().lower(); password=str(d.get("password",""))
    # Simple persistent per-IP/account throttle, intentionally not exposing whether username exists.
    key=hashlib.sha256((request.remote_addr or ""+username).encode()).hexdigest()
    with connect() as c:
        recent=c.execute("SELECT COUNT(*) n FROM audit_logs WHERE action='login_failed' AND ip=? AND created_at > ?",(request.remote_addr, (datetime.now(timezone.utc)-timedelta(minutes=15)).isoformat())).fetchone()["n"]
        if recent>=10: return jsonify(error="Too many attempts. Try again later."),429
        u=c.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
        ok=bool(u and not u["disabled"] and check_password_hash(u["password_hash"],password))
        if not ok:
            c.execute("INSERT INTO audit_logs(actor_name,action,ip,created_at) VALUES(?,?,?,?)",(username,"login_failed",request.remote_addr,now()))
            return jsonify(error="Invalid username or password"),401
        session.clear(); session["uid"]=u["id"]; session.permanent=True
        c.execute("UPDATE users SET last_login=? WHERE id=?",(now(),u["id"]))
    g.user=u; audit("login_success",u["id"]); return jsonify(user={"id":u["id"],"username":u["username"],"display_name":u["display_name"],"role":u["role"],"mfa_enabled":False})

@app.post("/api/auth/logout")
def logout(): audit("logout"); session.clear(); return jsonify(ok=True)
@app.get("/api/auth/me")
@role_required(*ROLES)
def me(): return jsonify(user={"id":g.user["id"],"username":g.user["username"],"display_name":g.user["display_name"],"role":g.user["role"],"mfa_enabled":bool(g.user["mfa_enabled"])})

@app.get("/api/admin/overview")
@owner_or_dev
def overview():
    with connect() as c:
        users=c.execute("SELECT COUNT(*) FROM users").fetchone()[0]; disabled=c.execute("SELECT COUNT(*) FROM users WHERE disabled=1").fetchone()[0]
        errors=c.execute("SELECT COUNT(*) FROM application_logs WHERE level='error' AND created_at> ?",((datetime.now(timezone.utc)-timedelta(hours=24)).isoformat(),)).fetchone()[0]
        events=c.execute("SELECT COUNT(*),COALESCE(AVG(duration_ms),0) FROM api_events WHERE created_at> ?",((datetime.now(timezone.utc)-timedelta(hours=24)).isoformat(),)).fetchone()
        flags=c.execute("SELECT name,enabled,description FROM feature_flags").fetchall()
    return jsonify(users=users,disabled_users=disabled,errors_24h=errors,api_requests_24h=events[0],avg_api_ms=round(events[1],2),feature_flags=[dict(x) for x in flags],data_source="server database")

@app.get("/api/admin/users")
@owner_or_dev
def list_users():
    with connect() as c: rows=c.execute("SELECT id,username,display_name,email,role,disabled,mfa_enabled,created_at,last_login FROM users ORDER BY created_at DESC LIMIT 500").fetchall()
    return jsonify(users=[dict(x) for x in rows])
@app.patch("/api/admin/users/<uid>")
@owner_or_dev
def change_user(uid):
    d=request.get_json(silent=True) or {}; allowed={"role","disabled"};
    if set(d)-allowed: return jsonify(error="Unsupported fields"),400
    with connect() as c:
        target=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
        if not target:return jsonify(error="User not found"),404
        if "role" in d:
            if d["role"] not in ROLES:return jsonify(error="Invalid role"),400
            if d["role"]=="Owner" and g.user["role"]!="Owner":return jsonify(error="Only an Owner may grant the Owner role"),403
            if target["role"]=="Owner" and d["role"]!="Owner" and c.execute("SELECT COUNT(*) FROM users WHERE role='Owner' AND disabled=0").fetchone()[0]<=1:return jsonify(error="Cannot demote the last active Owner"),409
            c.execute("UPDATE users SET role=? WHERE id=?",(d["role"],uid))
        if "disabled" in d:c.execute("UPDATE users SET disabled=? WHERE id=?",(1 if d["disabled"] else 0,uid))
    audit("user_updated",uid,{"fields":list(d.keys())});return jsonify(ok=True)

@app.get("/api/admin/logs")
@owner_or_dev
def logs():
    limit=max(1,min(500,int(request.args.get("limit","100"))))
    with connect() as c: rows=c.execute("SELECT id,level,message,source,created_at,request_id FROM application_logs ORDER BY id DESC LIMIT ?",(limit,)).fetchall()
    return jsonify(logs=[dict(x) for x in rows])
@app.get("/api/admin/audit")
@owner_or_dev
def audit_list():
    limit=max(1,min(500,int(request.args.get("limit","100"))))
    with connect() as c: rows=c.execute("SELECT id,actor_name,action,target,ip,created_at,detail_json FROM audit_logs ORDER BY id DESC LIMIT ?",(limit,)).fetchall()
    return jsonify(events=[dict(x) for x in rows])
@app.get("/api/admin/diagnostics")
@owner_or_dev
def diagnostics():
    with connect() as c:
        db_bytes=DB_PATH.stat().st_size if DB_PATH.exists() else 0
        return jsonify(database={"reachable":True,"file_bytes":db_bytes,"schema_version":c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]},runtime={"python":os.sys.version.split()[0],"environment":os.environ.get("DNX_ENV","development")},integrations=integration_data(c))
def integration_data(c):return [dict(x) for x in c.execute("SELECT name,configured,last_check,status,safe_detail FROM integration_status ORDER BY name").fetchall()]
@app.get("/api/admin/database")
@owner_only
def database_info():
    with connect() as c: return jsonify(engine="sqlite",path="[redacted]",integrity=c.execute("PRAGMA integrity_check").fetchone()[0],schema_version=c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0],migrations=[dict(x) for x in c.execute("SELECT version,applied_at FROM schema_migrations ORDER BY version").fetchall()])
@app.post("/api/admin/backups")
@owner_only
def backup_create():
    d=request.get_json(silent=True) or {}
    if d.get("action")!="create":return jsonify(error="Only action=create is supported here"),400
    BACKUP_DIR.mkdir(parents=True,exist_ok=True); bid=secrets.token_hex(8); dest=BACKUP_DIR/("datanexus-"+bid+".sqlite3")
    try:
        src=connect(); out=sqlite3.connect(dest); src.backup(out); out.close(); src.close()
        size=dest.stat().st_size
        with connect() as c:c.execute("INSERT INTO backups(id,filename,size_bytes,created_at,created_by,status) VALUES(?,?,?,?,?,'verified')",(bid,dest.name,size,now(),g.user["id"]))
        audit("backup_created",bid,{"size_bytes":size});return jsonify(id=bid,size_bytes=size,status="verified",created_at=now()),201
    except Exception:
        app.logger.exception("Backup failed");
        if dest.exists():dest.unlink()
        with connect() as c:c.execute("INSERT INTO application_logs(level,message,source,created_at) VALUES('error','Backup failed','backup',?)",(now(),))
        return jsonify(error="Backup failed; no success recorded"),500
@app.get("/api/admin/backups")
@owner_only
def backup_list():
    with connect() as c: rows=c.execute("SELECT id,filename,size_bytes,created_at,created_by,status FROM backups ORDER BY created_at DESC LIMIT 100").fetchall()
    return jsonify(backups=[dict(x) for x in rows])
@app.post("/api/admin/restore")
@owner_only
def restore_disabled():
    # Deliberately no HTTP restore. Restores can replace production data; use the documented offline CLI workflow.
    audit("restore_endpoint_denied")
    return jsonify(error="Online restore is disabled. Use the protected maintenance-window CLI procedure in DEPLOYMENT.md."),405
@app.get("/api/admin/integrations")
@owner_or_dev
def integrations():
    with connect() as c:return jsonify(integrations=integration_data(c),note="Provider calls are not simulated; not_configured means no provider credentials or health probe is active")
@app.get("/api/admin/flags")
@owner_or_dev
def get_flags():
    with connect() as c:return jsonify(flags=[dict(x) for x in c.execute("SELECT name,enabled,description,updated_at FROM feature_flags").fetchall()])
@app.patch("/api/admin/flags/<name>")
@owner_only
def set_flag(name):
    d=request.get_json(silent=True) or {}
    if not isinstance(d.get("enabled"),bool):return jsonify(error="enabled must be boolean"),400
    with connect() as c:
        cur=c.execute("UPDATE feature_flags SET enabled=?,updated_at=? WHERE name=?",(int(d["enabled"]),now(),name))
        if not cur.rowcount:return jsonify(error="Unknown feature flag"),404
    audit("feature_flag_changed",name,{"enabled":d["enabled"]});return jsonify(ok=True)
@app.post("/api/admin/announcements")
@owner_only
def announcement_create():
    d=request.get_json(silent=True) or {}; title=str(d.get("title"," ")).strip(); body=str(d.get("body"," ")).strip()
    if not title or not body or len(title)>120 or len(body)>2000:return jsonify(error="Title/body required; title ≤120 and body ≤2000 chars"),400
    with connect() as c:c.execute("INSERT INTO announcements(title,body,created_at,created_by) VALUES(?,?,?,?)",(title,body,now(),g.user["id"]))
    audit("announcement_created",title);return jsonify(ok=True),201
@app.get("/api/admin/releases")
@owner_or_dev
def releases_get():
    with connect() as c:return jsonify(releases=[dict(x) for x in c.execute("SELECT id,version,notes,deployed_at,status,created_at,created_by FROM releases ORDER BY id DESC LIMIT 100").fetchall()])
@app.post("/api/admin/releases")
@owner_only
def releases_add():
    d=request.get_json(silent=True) or {}; v=str(d.get("version"," ")).strip(); notes=str(d.get("notes",""))[:3000]
    if not v or len(v)>40:return jsonify(error="Valid version required"),400
    with connect() as c:c.execute("INSERT INTO releases(version,notes,status,created_at,created_by) VALUES(?,?,'recorded',?,?)",(v,notes,now(),g.user["id"]))
    audit("release_recorded",v);return jsonify(ok=True,note="Release recorded as metadata only; no deployment or rollback executed"),201
@app.get("/api/admin/export")
@owner_only
def export_data():
    with connect() as c:
        obj={t:[dict(x) for x in c.execute("SELECT * FROM "+t).fetchall()] for t in ["users","audit_logs","application_logs","feature_flags","announcements","releases","backups","integration_status","settings"]}
    obj["users"]=[{k:v for k,v in u.items() if k not in ("password_hash","mfa_secret")} for u in obj["users"]]
    audit("admin_export",None,{"tables":list(obj.keys())})
    return jsonify(exported_at=now(),data=obj)
@app.get("/api/admin/settings")
@owner_only
def settings_get():
    with connect() as c:return jsonify(settings=[dict(x) for x in c.execute("SELECT key,value_json,updated_at,updated_by FROM settings").fetchall()])
@app.put("/api/admin/settings/<key>")
@owner_only
def settings_put(key):
    d=request.get_json(silent=True) or {}
    if len(key)>80 or "value" not in d:return jsonify(error="Setting key/value required"),400
    with connect() as c:c.execute("INSERT INTO settings(key,value_json,updated_at,updated_by) VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at,updated_by=excluded.updated_by",(key,json.dumps(d["value"]),now(),g.user["id"]))
    audit("setting_changed",key);return jsonify(ok=True)

@app.cli.command("create-owner")
def create_owner():
    """Create the first Owner using interactive input; no default password is shipped."""
    import getpass
    username=input("Owner username: ").strip().lower(); name=input("Display name: ").strip(); email=input("Email (optional): ").strip(); password=getpass.getpass("Strong password: ")
    if len(username)<3 or len(password)<12: raise SystemExit("Username must be 3+ chars and password 12+ chars")
    with connect() as c:
        if c.execute("SELECT COUNT(*) FROM users WHERE role='Owner'").fetchone()[0]:raise SystemExit("An Owner already exists")
        uid=secrets.token_hex(16); c.execute("INSERT INTO users(id,username,display_name,email,password_hash,role,created_at) VALUES(?,?,?,?,?,'Owner',?)",(uid,username,name,email,generate_password_hash(password),now()))
    print("Owner created. MFA is disabled in this edition; configure HTTPS and secure cookies before production use.")


@app.cli.command("set-password")
def set_password():
    """Set/reset a user's password interactively without putting it in source or shell history."""
    import getpass
    username=input("Account username: ").strip().lower()
    password=getpass.getpass("New password (12+ characters): ")
    confirm=getpass.getpass("Confirm new password: ")
    if len(password)<12 or password != confirm:
        raise SystemExit("Passwords must match and be at least 12 characters.")
    with connect() as c:
        u=c.execute("SELECT id FROM users WHERE username=?",(username,)).fetchone()
        if not u: raise SystemExit("No account found with that username.")
        c.execute("UPDATE users SET password_hash=?,mfa_enabled=0,mfa_secret=NULL WHERE id=?",(generate_password_hash(password),u["id"]))
    print("Password updated. Existing sessions may remain valid until they expire; sign out and sign back in.")


@app.cli.command("set-owner")
def set_owner():
    """Create or update the Owner account from DNX_OWNER_USER / DNX_OWNER_PASS env vars (password is never stored in source)."""
    username=os.environ.get("DNX_OWNER_USER","").strip().lower(); password=os.environ.get("DNX_OWNER_PASS","")
    if len(username)<3 or len(password)<12: raise SystemExit("Set DNX_OWNER_USER (3+ chars) and DNX_OWNER_PASS (12+ chars) first.")
    with connect() as c:
        o=c.execute("SELECT id FROM users WHERE role='Owner' ORDER BY created_at LIMIT 1").fetchone()
        clash=c.execute("SELECT id FROM users WHERE username=?",(username,)).fetchone()
        if clash and (not o or clash["id"]!=o["id"]): raise SystemExit("That username already belongs to another account.")
        h=generate_password_hash(password)
        if o: c.execute("UPDATE users SET username=?,password_hash=?,disabled=0,mfa_enabled=0,mfa_secret=NULL WHERE id=?",(username,h,o["id"]))
        else: c.execute("INSERT INTO users(id,username,display_name,email,password_hash,role,created_at) VALUES(?,?,?,?,?,'Owner',?)",(secrets.token_hex(16),username,"Owner","",h,now()))
    print("Owner account ready. Sign in with username '%s'."%username)


@app.get("/")
def frontend_index():
    return send_from_directory(ROOT, "index.html")

@app.get("/<path:asset>")
def frontend_asset(asset):
    # Serve only known public app assets; never expose server/, data/, backups/, or dotfiles.
    allowed = asset in {"sw.js", "manifest.webmanifest", "favicon.ico"} or asset.startswith(("css/", "js/", "icons/"))
    if not allowed or asset.startswith(".") or ".." in Path(asset).parts:
        abort(404)
    return send_from_directory(ROOT, asset)

if __name__ == "__main__": app.run(host="127.0.0.1",port=int(os.environ.get("PORT","5000")),debug=False)
