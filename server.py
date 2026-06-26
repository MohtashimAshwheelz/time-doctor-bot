"""
Time Doctor + Odoo Web Dashboard
Run:  python server.py
Open: http://localhost:5000
"""

from flask import Flask, render_template, request, jsonify, Response
import json
import os
import queue
import threading
import time
import xmlrpc.client
import requests as _req
from datetime import datetime, date, timedelta
from pathlib import Path

app = Flask(__name__)
app.secret_key = "td-odoo-dashboard-secret"

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR        = Path(__file__).parent
CONFIG_FILE     = BASE_DIR / "config.json"
TD_MAPPING_FILE = BASE_DIR / "td_name_mapping.json"

DEFAULT_CONFIG = {
    "odoo_host": "", "odoo_db": "", "odoo_user": "", "odoo_pass": "",
    "company_id": 0, "company_name": "All Companies",
    "td_email": "", "td_pass": "", "td_token": "",
    "td_company": "aTUbMi6uG2kPZzUD",
    "green_instance": "", "green_token": "",
    "schedule_hour": "5", "schedule_minute": "0",
    "auto_run_today": True, "watch_interval": 5,
    "custom_note": "", "audit_custom_note": "",
}

TD_COMPANY_ID = "aTUbMi6uG2kPZzUD"

BUSINESS_MODELS = [
    "purchase.order","account.move","account.payment",
    "sale.order","stock.picking","stock.inventory",
    "mrp.production","hr.employee","hr.payslip",
    "hr.payslip.run","hr.attendance","hr.leave",
    "res.partner","product.template","project.task",
]

MODEL_LABELS = {
    "purchase.order":    "Purchase Orders",
    "account.move":      "Invoices/Accounting",
    "account.payment":   "Payments",
    "sale.order":        "Sales Orders",
    "stock.picking":     "Stock Transfers",
    "stock.inventory":   "Inventory",
    "mrp.production":    "Manufacturing",
    "hr.employee":       "HR Employees",
    "hr.payslip":        "Payslips",
    "hr.payslip.run":    "Payslip Batches",
    "hr.attendance":     "Attendance",
    "hr.leave":          "Leaves",
    "res.partner":       "Contacts",
    "product.template":  "Products",
    "project.task":      "Project Tasks",
}

SYS_LOGINS = {"odoobot","__system__","public user","administrator","portal","odoo bot","admin"}

# ── In-memory session state ───────────────────────────────────────────────────
_state = {
    "td_token":        None,
    "td_id_name":      {},
    "td_name_id":      {},
    "audit_users":     [],
    "td_stats_by_id":  {},
    "td_user_ids":     [],
    "td_stats_raw":    {},
    "td_last_date":    None,
    "mapping_all_odoo": None,
    "td_rows":         [],
    "td_groups":       [],
    "td_user_groups":  {},
}

# SSE log queue (multiple clients share same queue via broadcast)
_log_clients = []
_log_lock    = threading.Lock()

def push_log(msg, tag="info"):
    ts  = datetime.now().strftime("%H:%M:%S")
    evt = json.dumps({"msg": msg, "tag": tag, "ts": ts})
    with _log_lock:
        dead = []
        for q in _log_clients:
            try:
                q.put_nowait(evt)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _log_clients.remove(q)

# ── Config helpers ────────────────────────────────────────────────────────────
def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

def load_td_mapping():
    try:
        if TD_MAPPING_FILE.exists():
            with open(TD_MAPPING_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_td_mapping(mapping):
    with open(TD_MAPPING_FILE, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)

# ── Odoo helpers ──────────────────────────────────────────────────────────────
def odoo_auth(cfg):
    host = cfg.get("odoo_host","").strip().rstrip("/")
    if not host:
        raise Exception("Odoo host not configured")
    if not host.startswith("http"):
        host = "https://" + host
    common = xmlrpc.client.ServerProxy(host + "/xmlrpc/2/common")
    uid = common.authenticate(cfg["odoo_db"], cfg["odoo_user"], cfg["odoo_pass"], {})
    if not uid:
        raise Exception("Odoo authentication failed — check credentials")
    models = xmlrpc.client.ServerProxy(host + "/xmlrpc/2/object")
    return uid, models, host

# ── TD helpers ────────────────────────────────────────────────────────────────
def fmt_sec(s):
    if not s or s <= 0:
        return "0h 00m"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"

def td_login_api(email, pwd):
    r = _req.post(
        "https://api2.timedoctor.com/api/1.0/authorization/login",
        json={"email": email, "password": pwd, "permissions": "write"},
        timeout=20)
    if r.status_code != 200:
        raise ValueError(f"TD login HTTP {r.status_code}: {r.text[:200]}")
    tok = r.json().get("data", {}).get("token", "")
    if not tok:
        raise ValueError("No token in TD response")
    return tok

def td_fetch_users(tok):
    r = _req.get(
        "https://api2.timedoctor.com/api/1.0/users",
        params={"company": TD_COMPANY_ID, "token": tok,
                "detail": "basic", "limit": 200, "page": 0,
                "deleted": 0, "sort": "name"},
        timeout=20)
    if r.status_code == 401:
        raise PermissionError("token_expired")
    r.raise_for_status()
    return r.json().get("data", [])

def td_fetch_groups(tok):
    try:
        r = _req.get(
            "https://api2.timedoctor.com/api/1.0/groups",
            params={"company": TD_COMPANY_ID, "token": tok},
            timeout=15)
        if r.status_code == 200:
            return r.json().get("data", [])
    except Exception:
        pass
    return []

def td_fetch_stats(tok, user_ids, dt_from, dt_to):
    stats = {}
    for i in range(0, len(user_ids), 20):
        batch = user_ids[i:i+20]
        r = _req.get(
            "https://api2.timedoctor.com/api/1.1/stats/total",
            params={"company": TD_COMPANY_ID, "token": tok,
                    "from": dt_from, "to": dt_to,
                    "fields": "userId,totalSec,activeSec,idleSec,idleMins,idleMinsRatio,meeting,unprod",
                    "group-by": "userId", "limit": 200,
                    "user": ",".join(batch)},
            timeout=20)
        if r.status_code == 200:
            for rec in r.json().get("data", []):
                uid = rec.get("userId", "")
                if uid:
                    stats[uid] = rec
    return stats

# ══════════════════════════════════════════════════════════════════════════════
# Routes — static
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")

# ══════════════════════════════════════════════════════════════════════════════
# SSE log stream
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/stream/logs")
def stream_logs():
    q = queue.Queue(maxsize=200)
    with _log_lock:
        _log_clients.append(q)

    def generate():
        try:
            while True:
                try:
                    evt = q.get(timeout=20)
                    yield f"data: {evt}\n\n"
                except queue.Empty:
                    yield "data: {\"ping\":1}\n\n"
                except Exception:
                    break
        except GeneratorExit:
            pass
        finally:
            with _log_lock:
                if q in _log_clients:
                    _log_clients.remove(q)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})

# ══════════════════════════════════════════════════════════════════════════════
# Config API
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/config", methods=["GET"])
def api_get_config():
    cfg = load_config()
    # Never send passwords to frontend
    safe = {k: v for k, v in cfg.items()
            if k not in ("odoo_pass", "td_pass", "td_token", "green_token")}
    safe["has_odoo_pass"] = bool(cfg.get("odoo_pass"))
    safe["has_td_token"]  = bool(cfg.get("td_token"))
    safe["td_token_hint"] = ("…" + cfg["td_token"][-6:]) if cfg.get("td_token") else ""
    return jsonify(safe)

@app.route("/api/config", methods=["POST"])
def api_save_config():
    data = request.get_json(force=True)
    cfg  = load_config()
    for k in ("odoo_host","odoo_db","odoo_user","odoo_pass",
              "td_email","td_pass","company_id","company_name"):
        if k in data and data[k] != "":
            cfg[k] = data[k]
    save_config(cfg)
    return jsonify({"ok": True})

# ══════════════════════════════════════════════════════════════════════════════
# Odoo API
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/odoo/test", methods=["POST"])
def api_odoo_test():
    data = request.get_json(force=True) or {}
    cfg  = load_config()
    # Allow caller to override credentials for "test before save"
    for k in ("odoo_host","odoo_db","odoo_user","odoo_pass"):
        if data.get(k):
            cfg[k] = data[k]
    try:
        uid, models, host = odoo_auth(cfg)
        return jsonify({"ok": True, "uid": uid, "host": host})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

@app.route("/api/odoo/companies", methods=["GET"])
def api_odoo_companies():
    cfg = load_config()
    try:
        uid, models, host = odoo_auth(cfg)
        cos = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
            "res.company", "search_read", [[]], {"fields": ["id","name"], "order": "name asc"})
        return jsonify({"ok": True, "companies": cos})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

@app.route("/api/odoo/load-users", methods=["POST"])
def api_odoo_load_users():
    data     = request.get_json(force=True) or {}
    sel_date = data.get("date", date.today().strftime("%Y-%m-%d"))
    cfg      = load_config()

    def _run():
        push_log(f"Connecting to {cfg.get('odoo_host','(not set)')}...", "info")
        try:
            uid, models, host = odoo_auth(cfg)
            push_log(f"Authenticated (UID {uid})", "ok")

            ds = sel_date
            ns = (datetime.strptime(sel_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

            messages = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
                "mail.message", "search_read",
                [[["date",">=",ds+" 00:00:00"],
                  ["date","<", ns+" 00:00:00"],
                  ["author_id","!=",False],
                  ["model","in",BUSINESS_MODELS]]],
                {"fields":["author_id","model","record_name","res_id","date"],
                 "limit":5000, "order":"date asc"})

            push_log(f"Found {len(messages)} chatter entries", "ok")

            # Resolve missing record names
            missing_by_model = {}
            for m in messages:
                if not m.get("record_name") and m.get("res_id") and m.get("model"):
                    mod = m["model"]
                    missing_by_model.setdefault(mod, set()).add(m["res_id"])

            name_cache = {}
            for mod, res_ids in missing_by_model.items():
                try:
                    results = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
                        mod, "name_get", [list(res_ids)])
                    for rid, nm in results:
                        name_cache[(mod, rid)] = nm
                except Exception:
                    pass

            for m in messages:
                if not m.get("record_name") and m.get("res_id") and m.get("model"):
                    resolved = name_cache.get((m["model"], m["res_id"]))
                    m["record_name"] = resolved or (m["model"].split(".")[-1].upper() + " #" + str(m["res_id"]))

            # Map authors to users
            author_pids = list({m["author_id"][0] for m in messages
                                if m.get("author_id") and isinstance(m["author_id"],(list,tuple))})
            all_users = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
                "res.users","search_read",
                [[["partner_id","in",author_pids]]],
                {"fields":["id","name","partner_id","login"]})
            partner_to_user = {u["partner_id"][0]: (u["id"], u["name"], u.get("login",""))
                               for u in all_users
                               if u.get("partner_id") and isinstance(u["partner_id"],(list,tuple))}

            user_counts, user_names, user_logins, user_models = {}, {}, {}, {}
            u_by_model, u_raw_entries = {}, {}

            for m in messages:
                author = m.get("author_id")
                if not author or not isinstance(author,(list,tuple)):
                    continue
                pid = author[0]
                if pid in partner_to_user:
                    uid_v, uname, ulogin = partner_to_user[pid]
                else:
                    uid_v, uname, ulogin = pid, author[1], ""

                user_counts[uid_v]  = user_counts.get(uid_v, 0) + 1
                user_names[uid_v]   = uname
                user_logins[uid_v]  = ulogin

                mk  = m.get("model","")
                lbl = MODEL_LABELS.get(mk, mk.replace("."," ").title() if mk else "General")
                rec = m.get("record_name","") or ""

                raw_dt = m.get("date","") or ""
                if raw_dt:
                    try:
                        utc_dt = datetime.strptime(raw_dt[:19], "%Y-%m-%d %H:%M:%S")
                        pkt_dt = utc_dt + timedelta(hours=5)
                        dt = pkt_dt.strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        dt = raw_dt[:16].replace("T"," ")
                else:
                    dt = ""

                u_by_model.setdefault(uid_v, {})
                if lbl not in u_by_model[uid_v]:
                    u_by_model[uid_v][lbl] = {"count":0,"records":[],"seen":set(),"entries":[]}
                g = u_by_model[uid_v][lbl]
                g["count"] += 1
                g["entries"].append({"time": dt, "rec": rec})
                if rec and rec not in g["seen"]:
                    g["seen"].add(rec); g["records"].append(rec)

                u_raw_entries.setdefault(uid_v, []).append(
                    {"time": dt, "model": lbl, "rec": rec})

            audit_users = []
            for uid_v in sorted(user_counts, key=lambda x: -user_counts[x]):
                by_m = u_by_model.get(uid_v, {})
                # convert sets to lists for JSON
                by_m_clean = {k: {**v, "seen": list(v.get("seen",set()))}
                              for k, v in by_m.items()}
                audit_users.append({
                    "id":         uid_v,
                    "name":       user_names[uid_v],
                    "login":      user_logins.get(uid_v,""),
                    "count":      user_counts[uid_v],
                    "modules":    ", ".join(sorted({
                                    MODEL_LABELS.get(k, k) for k in
                                    (u_by_model.get(uid_v) or {})})),
                    "by_model":   by_m_clean,
                    "raw_entries": u_raw_entries.get(uid_v,[]),
                })

            _state["audit_users"] = audit_users
            push_log(f"Found {len(audit_users)} active user(s) on {sel_date}", "ok")

        except Exception as e:
            push_log("ERROR: " + str(e), "err")

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "started": True})

@app.route("/api/odoo/users-result", methods=["GET"])
def api_odoo_users_result():
    return jsonify({"users": _state["audit_users"]})

# ══════════════════════════════════════════════════════════════════════════════
# TimeDoctor API
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/td/login", methods=["POST"])
def api_td_login():
    data  = request.get_json(force=True) or {}
    email = data.get("email","").strip()
    pwd   = data.get("password","").strip()
    if not email or not pwd:
        return jsonify({"ok": False, "error": "Email and password required"}), 400

    def _run():
        push_log("TD: Logging in via API...", "info")
        try:
            tok = td_login_api(email, pwd)
            cfg = load_config()
            cfg["td_email"] = email
            cfg["td_pass"]  = pwd
            cfg["td_token"] = tok
            save_config(cfg)
            _state["td_token"] = tok
            push_log("TimeDoctor: API login successful", "ok")
            push_log(f"TD_TOKEN:{tok}", "_td_token_")
        except Exception as e:
            push_log("TD login error: " + str(e), "err")

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "started": True})

@app.route("/api/td/fetch", methods=["POST"])
def api_td_fetch():
    data     = request.get_json(force=True) or {}
    sel_date = data.get("date", date.today().strftime("%Y-%m-%d"))
    tok      = _state.get("td_token") or load_config().get("td_token","")
    if not tok:
        return jsonify({"ok": False, "error": "Not logged in to TimeDoctor"}), 400

    def _run():
        push_log(f"TD: Fetching stats for {sel_date}...", "info")
        try:
            nonlocal tok
            _sel_dt = datetime.strptime(sel_date, "%Y-%m-%d")
            dt_from = (_sel_dt - timedelta(days=1)).strftime("%Y-%m-%d") + "T19:00:00"
            dt_to   = _sel_dt.strftime("%Y-%m-%d") + "T19:00:00"
            push_log(f"TD: UTC range {dt_from} → {dt_to}", "info")

            push_log("TD: Fetching user list...", "info")
            try:
                users = td_fetch_users(tok)
            except PermissionError:
                push_log("TD: Token expired — re-logging in...", "warn")
                cfg = load_config()
                tok = td_login_api(cfg.get("td_email",""), cfg.get("td_pass",""))
                cfg["td_token"] = tok
                save_config(cfg)
                _state["td_token"] = tok
                users = td_fetch_users(tok)

            push_log(f"TD: {len(users)} users found", "ok")
            if not users:
                push_log("TD: No users found.", "warn")
                return

            id_name = {u.get("id",""): u.get("name","") for u in users}
            _state["td_id_name"]  = id_name
            _state["td_name_id"]  = {v: k for k, v in id_name.items() if v}
            _state["td_last_date"]= sel_date

            user_ids = [u.get("id","") for u in users if u.get("id")]

            # Fetch groups
            groups_data = td_fetch_groups(tok)
            _state["td_groups"] = groups_data
            group_id_name = {str(g.get("id","")): g.get("name","") for g in groups_data}
            user_groups = {}
            for u in users:
                uid_u = u.get("id","")
                gid = u.get("groupId") or u.get("group") or ""
                if isinstance(gid, dict):
                    gid = gid.get("id","")
                user_groups[uid_u] = group_id_name.get(str(gid), "")
            _state["td_user_groups"] = user_groups
            if groups_data:
                push_log(f"TD: {len(groups_data)} group(s) loaded", "info")

            push_log(f"TD: Fetching stats...", "info")
            stats = td_fetch_stats(tok, user_ids, dt_from, dt_to)
            push_log(f"TD: {len(stats)} stat records fetched", "ok")

            _state["td_user_ids"]  = user_ids
            _state["td_stats_raw"] = stats

            # Build combined rows
            odoo_counts        = {}
            odoo_counts_by_email = {}
            for u in _state.get("audit_users", []):
                odoo_counts[u.get("name","")] = u.get("count", 0)
                lg = (u.get("login") or "").strip().lower()
                if lg:
                    odoo_counts_by_email[lg] = u.get("count", 0)

            td_mapping = load_td_mapping()
            rows = []
            stats_by_id = {}

            for uid in user_ids:
                name     = id_name.get(uid, uid)
                rec      = stats.get(uid, {})
                worked_s = rec.get("totalSec", 0) or 0
                active_s = rec.get("activeSec", 0) or 0
                idle_mins   = rec.get("idleMins", 0) or 0
                nonprod     = rec.get("unprod", 0) or 0
                idle_pct_raw = rec.get("idleMinsRatio", None)
                if idle_pct_raw is not None:
                    idle_pct = round(float(idle_pct_raw) * 100)
                elif worked_s > 0:
                    idle_pct = round(idle_mins * 100 / (worked_s // 60)) if worked_s > 0 else 0
                else:
                    idle_pct = 0

                stats_by_id[uid] = {
                    "worked_s": worked_s, "active_s": active_s,
                    "idle_mins": idle_mins, "nonprod_s": nonprod,
                }

                odoo_act = odoo_counts.get(name, None)
                if odoo_act is None:
                    mapped_email = td_mapping.get(name, "").strip().lower()
                    odoo_act = odoo_counts_by_email.get(mapped_email, "—") if mapped_email else "—"

                odoo_status = (str(odoo_act) + " actions") if isinstance(odoo_act, int) else "Not in Odoo"
                tag = ("absent" if worked_s == 0
                       else "danger" if idle_pct > 40 or nonprod > 3600
                       else "warn"   if idle_pct > 20 or nonprod > 1800
                       else "good")

                rows.append({
                    "name":       name,
                    "role":       "",
                    "odoo_act":   str(odoo_act) if isinstance(odoo_act, int) else "—",
                    "odoo_status":odoo_status,
                    "hours":      fmt_sec(worked_s),
                    "active":     fmt_sec(active_s),
                    "idle":       f"{idle_mins}m ({idle_pct}%)",
                    "nonprod":    fmt_sec(nonprod),
                    "tag":        tag,
                    "worked_s":   worked_s,
                    "active_s":   active_s,
                    "idle_min":   idle_mins,
                    "nonprod_s":  nonprod,
                    "idle_pct":   idle_pct,
                    "group":      user_groups.get(uid, ""),
                    "td_uid":     uid,
                })

            rows.sort(key=lambda r: -r["worked_s"])
            _state["td_rows"]       = rows
            _state["td_stats_by_id"]= stats_by_id

            active_c = [r["name"] for r in rows if r["tag"] != "absent"]
            danger_c = [r["name"] for r in rows if r["tag"] == "danger"]
            push_log(f"TimeDoctor: {len(rows)} records for {sel_date}", "ok")
            push_log(f"Active: {len(active_c)}, Absent: {len(rows)-len(active_c)}", "info")
            if danger_c:
                push_log("High idle/nonprod: " + ", ".join(danger_c[:5]), "warn")

            push_log("TD_ROWS_READY", "_refresh_")

        except Exception as e:
            push_log("TD fetch error: " + str(e), "err")

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "started": True})

@app.route("/api/td/rows", methods=["GET"])
def api_td_rows():
    return jsonify({
        "rows":     _state.get("td_rows", []),
        "date":     _state.get("td_last_date",""),
        "total":    len(_state.get("td_rows",[])),
    })

@app.route("/api/td/rebuild", methods=["POST"])
def api_td_rebuild():
    """Rebuild combined report with fresh mapping (after link/unlink)."""
    user_ids = _state.get("td_user_ids",[])
    stats    = _state.get("td_stats_raw",{})
    id_name  = _state.get("td_id_name",{})
    if not user_ids:
        return jsonify({"ok": False, "error": "No TD data cached — fetch first"})

    odoo_counts, odoo_counts_by_email = {}, {}
    for u in _state.get("audit_users",[]):
        odoo_counts[u.get("name","")] = u.get("count", 0)
        lg = (u.get("login") or "").strip().lower()
        if lg:
            odoo_counts_by_email[lg] = u.get("count", 0)

    td_mapping = load_td_mapping()
    user_groups = _state.get("td_user_groups", {})
    rows = []
    for uid in user_ids:
        name     = id_name.get(uid, uid)
        rec      = stats.get(uid, {})
        worked_s = rec.get("totalSec", 0) or 0
        active_s = rec.get("activeSec", 0) or 0
        idle_mins   = rec.get("idleMins", 0) or 0
        nonprod     = rec.get("unprod", 0) or 0
        idle_pct_raw = rec.get("idleMinsRatio", None)
        idle_pct = round(float(idle_pct_raw) * 100) if idle_pct_raw is not None else 0

        odoo_act = odoo_counts.get(name, None)
        if odoo_act is None:
            mapped_email = td_mapping.get(name, "").strip().lower()
            odoo_act = odoo_counts_by_email.get(mapped_email, "—") if mapped_email else "—"

        tag = ("absent" if worked_s == 0
               else "danger" if idle_pct > 40 or nonprod > 3600
               else "warn"   if idle_pct > 20 or nonprod > 1800
               else "good")

        rows.append({
            "name": name, "role": "",
            "odoo_act": str(odoo_act) if isinstance(odoo_act, int) else "—",
            "odoo_status": (str(odoo_act) + " actions") if isinstance(odoo_act, int) else "Not in Odoo",
            "hours": fmt_sec(worked_s), "active": fmt_sec(active_s),
            "idle": f"{idle_mins}m ({idle_pct}%)",
            "nonprod": fmt_sec(nonprod),
            "tag": tag, "worked_s": worked_s,
            "active_s": active_s, "idle_min": idle_mins,
            "nonprod_s": nonprod, "idle_pct": idle_pct,
            "group":    user_groups.get(uid, ""),
            "td_uid":   uid,
        })

    rows.sort(key=lambda r: -r["worked_s"])
    _state["td_rows"] = rows
    return jsonify({"ok": True, "rows": rows})

# ══════════════════════════════════════════════════════════════════════════════
# User Mapping API
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/mapping", methods=["GET"])
def api_get_mapping():
    return jsonify(load_td_mapping())

@app.route("/api/mapping/link", methods=["POST"])
def api_mapping_link():
    data      = request.get_json(force=True) or {}
    td_name   = data.get("td_name","").strip()
    odoo_login= data.get("odoo_login","").strip()
    if not td_name or not odoo_login:
        return jsonify({"ok": False, "error": "td_name and odoo_login required"}), 400
    mapping = load_td_mapping()
    mapping[td_name] = odoo_login
    save_td_mapping(mapping)
    push_log(f"Linked: {td_name} -> {odoo_login}", "ok")
    return jsonify({"ok": True, "mapping": mapping})

@app.route("/api/mapping/unlink", methods=["POST"])
def api_mapping_unlink():
    data    = request.get_json(force=True) or {}
    td_name = data.get("td_name","").strip()
    if not td_name:
        return jsonify({"ok": False, "error": "td_name required"}), 400
    mapping = load_td_mapping()
    mapping.pop(td_name, None)
    save_td_mapping(mapping)
    push_log(f"Unlinked: {td_name}", "warn")
    return jsonify({"ok": True, "mapping": mapping})

@app.route("/api/mapping/odoo-users", methods=["GET"])
def api_mapping_odoo_users():
    """Load all active Odoo users for mapping (not just audit-day users)."""
    cfg = load_config()

    def _run():
        push_log("Loading all Odoo users...", "info")
        try:
            uid, models, host = odoo_auth(cfg)
            all_u = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
                "res.users","search_read",
                [[["active","=",True],["share","=",False]]],
                {"fields":["id","name","login"],"limit":1000})
            filtered = [u for u in all_u
                        if (u.get("login","") or "").strip().lower() not in SYS_LOGINS]
            _state["mapping_all_odoo"] = filtered
            push_log(f"Loaded {len(filtered)} Odoo users.", "ok")
            push_log("ODOO_USERS_READY", "_refresh_")
        except Exception as e:
            push_log("Odoo load error: " + str(e), "err")

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "started": True})

@app.route("/api/mapping/odoo-users-result", methods=["GET"])
def api_mapping_odoo_users_result():
    all_odoo = _state.get("mapping_all_odoo")
    if all_odoo is None:
        # Fall back to audit_users
        users = [u for u in _state.get("audit_users",[])
                 if (u.get("login","") or "").strip().lower() not in SYS_LOGINS]
    else:
        users = all_odoo
    return jsonify({"users": users})

@app.route("/api/mapping/td-users", methods=["GET"])
def api_mapping_td_users():
    id_name = _state.get("td_id_name", {})
    names = sorted([n for n in id_name.values()
                    if n.strip() and n.strip().lower() not in SYS_LOGINS])
    return jsonify({"users": names})

# ══════════════════════════════════════════════════════════════════════════════
# Groups + Employee detail API
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/td/groups", methods=["GET"])
def api_td_groups():
    groups = _state.get("td_groups", [])
    return jsonify({"groups": groups})

@app.route("/api/td/employee", methods=["GET"])
def api_td_employee():
    name = request.args.get("name","").strip()
    rows = _state.get("td_rows", [])
    row  = next((r for r in rows if r["name"] == name), None)
    if not row:
        return jsonify({"ok": False, "error": "Employee not found"}), 404

    td_mapping  = load_td_mapping()
    odoo_login  = td_mapping.get(name,"").strip().lower()
    odoo_user   = None
    for u in _state.get("audit_users",[]):
        ul = (u.get("login","") or "").strip().lower()
        if ul and ul == odoo_login:
            odoo_user = u; break
    if not odoo_user:
        for u in _state.get("audit_users",[]):
            if u.get("name","") == name:
                odoo_user = u; break

    return jsonify({
        "ok":   True,
        "row":  row,
        "date": _state.get("td_last_date",""),
        "odoo": odoo_user,
    })

# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import webbrowser
    print("=" * 55)
    print("  Time Doctor + Odoo Dashboard")
    print("  http://localhost:5000")
    print("=" * 55)
    port = int(os.environ.get("PORT", 5000))
    if port == 5000:
        threading.Timer(1.2, lambda: webbrowser.open("http://localhost:5000")).start()
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
