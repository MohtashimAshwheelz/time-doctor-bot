"""
Odoo -> WhatsApp Bot  v5.4
Light theme - white cards - blue accents - sidebar navigation
Pure tkinter - no external UI dependencies
"""

import tkinter as tk
from tkinter import ttk, scrolledtext
from tkcalendar import DateEntry
import threading
import json
import os
import re
import sys
import time
import xmlrpc.client
import schedule
import requests
import base64
from datetime import datetime, date, timedelta
from pathlib import Path
try:
    from rapidfuzz import fuzz, process as rfprocess
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False
try:
    import anthropic as _anthropic_sdk
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.chrome.service import Service as ChromeService
    HAS_SELENIUM = True
    # Try webdriver-manager for automatic chromedriver
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        HAS_WDM = True
    except ImportError:
        HAS_WDM = False
except ImportError:
    HAS_SELENIUM = False
    HAS_WDM = False

# ── Inlined fuel + GPS integration (formerly fuel_module.py / gps_module.py)
# Merged into main.py so updates only require touching one file.
# Style preserved: classes, helpers, config keys identical to module versions.

import queue   # used by FuelMixin OTP dialog

# ── Fuel integration (was fuel_module.py) ─────────────────────────
# ─────────────────────────────────────────────────────────────────────────
# CONFIG KEYS  (saved alongside zeeta_erp_* in config.json)
# ─────────────────────────────────────────────────────────────────────────
CFG_FUEL_URL      = "fuel_url"
CFG_FUEL_USER     = "fuel_user"
CFG_FUEL_PASS     = "fuel_pass"        # NOW SAVED — OTP gates real access
CFG_FUEL_LIST_URL = "fuel_list_url"
CFG_FUEL_OTP      = "fuel_otp"          # persisted only if user checks box
CFG_FUEL_OTP_PERSIST = "fuel_otp_persist"   # bool: save OTP across sessions


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────
def _fuel_parse_num(s):
    if s is None:
        return 0.0
    s = str(s).strip().replace(",", "")
    m = re.search(r"([-+]?\d+(?:\.\d+)?)", s)
    if not m:
        return 0.0
    try:
        return float(m.group(1))
    except ValueError:
        return 0.0


def _fuel_month_bounds(any_date):
    first = any_date.replace(day=1)
    if first.month == 12:
        nxt = first.replace(year=first.year + 1, month=1)
    else:
        nxt = first.replace(month=first.month + 1)
    last = nxt - timedelta(days=1)
    return first, last


def _fuel_normalize_plate(p):
    if not p:
        return ""
    s = str(p).strip().upper()
    for ch in (" ", "-", "_", "/", ".", "·"):
        s = s.replace(ch, "")
    return s


# ─────────────────────────────────────────────────────────────────────────
# Mixin class
# ─────────────────────────────────────────────────────────────────────────
class FuelMixin:

    # ─────────────────────────────────────────────────────────────────────
    # 1. UI — credentials block (Password is NOW saved; OTP gates access)
    # ─────────────────────────────────────────────────────────────────────
    def build_fuel_credentials_block(self, parent_frame, C):
        cfg = load_config()

        wrap = tk.Frame(parent_frame, bg=C["white"], bd=1, relief="solid",
                        highlightbackground=C["border"])
        wrap.pack(fill="x", padx=14, pady=(8, 4))

        tk.Label(wrap, text="Fuel Website (with OTP)",
                 font=("Segoe UI", 10, "bold"),
                 bg=C["white"], fg=C["text"]).grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 2),
            columnspan=2)

        # URL
        tk.Label(wrap, text="Login URL", font=("Segoe UI", 9),
                 bg=C["white"], fg=C["text2"]).grid(
            row=1, column=0, sticky="w", padx=12, pady=2)
        self.fuel_url_var = tk.StringVar(value=cfg.get(CFG_FUEL_URL, ""))
        tk.Entry(wrap, textvariable=self.fuel_url_var,
                 width=50, font=("Segoe UI", 9),
                 bg=C["input"], fg=C["text"], bd=1, relief="solid").grid(
            row=1, column=1, sticky="ew", padx=12, pady=2)

        # Username
        tk.Label(wrap, text="Username", font=("Segoe UI", 9),
                 bg=C["white"], fg=C["text2"]).grid(
            row=2, column=0, sticky="w", padx=12, pady=2)
        self.fuel_user_var = tk.StringVar(value=cfg.get(CFG_FUEL_USER, ""))
        tk.Entry(wrap, textvariable=self.fuel_user_var,
                 width=50, font=("Segoe UI", 9),
                 bg=C["input"], fg=C["text"], bd=1, relief="solid").grid(
            row=2, column=1, sticky="ew", padx=12, pady=2)

        # Password (NOW persisted — OTP gates real access)
        tk.Label(wrap, text="Password", font=("Segoe UI", 9),
                 bg=C["white"], fg=C["text2"]).grid(
            row=3, column=0, sticky="w", padx=12, pady=2)
        self.fuel_pass_var = tk.StringVar(value=cfg.get(CFG_FUEL_PASS, ""))
        tk.Entry(wrap, textvariable=self.fuel_pass_var,
                 show="•", width=50, font=("Segoe UI", 9),
                 bg=C["input"], fg=C["text"], bd=1, relief="solid").grid(
            row=3, column=1, sticky="ew", padx=12, pady=2)
        tk.Label(wrap,
                 text="Password is saved — the website's OTP is the real "
                      "session secret. OTP is requested each fetch.",
                 font=("Segoe UI", 8, "italic"),
                 bg=C["white"], fg=C["text3"]).grid(
            row=4, column=1, sticky="w", padx=12, pady=(0, 2))

        # OTP row — session-only by default, persist with checkbox
        # Initial value comes from config only if persist flag is on.
        tk.Label(wrap, text="OTP",
                 font=("Segoe UI", 9),
                 bg=C["white"], fg=C["text2"]).grid(
            row=5, column=0, sticky="w", padx=12, pady=2)
        otp_row = tk.Frame(wrap, bg=C["white"])
        otp_row.grid(row=5, column=1, sticky="ew",
                     padx=12, pady=2)
        _persist_init = bool(
            cfg.get(CFG_FUEL_OTP_PERSIST, False))
        _otp_init = (cfg.get(CFG_FUEL_OTP, "")
                     if _persist_init else "")
        self.fuel_otp_var = tk.StringVar(
            value=_otp_init)
        self.fuel_otp_persist_var = tk.BooleanVar(
            value=_persist_init)
        otp_entry = tk.Entry(otp_row,
            textvariable=self.fuel_otp_var,
            width=22,
            font=("Consolas", 11),
            bg=C["input"], fg=C["text"],
            bd=1, relief="solid")
        otp_entry.pack(side="left", padx=(0, 8))

        def _use_otp():
            v = self.fuel_otp_var.get().strip()
            # Strip spaces / dashes some emails include
            v = "".join(ch for ch in v if ch.isdigit())
            self.fuel_otp_var.set(v)
            if not v:
                self._vt_log(
                    "OTP field empty — fetch will fall back to "
                    "popup if Aldrees asks.", "warn")
                self._fuel_otp_pending = None
                return
            # Stash for the next fetch
            self._fuel_otp_pending = v
            # If persist checkbox is on, save to config too
            if self.fuel_otp_persist_var.get():
                cfg_now = load_config()
                cfg_now[CFG_FUEL_OTP] = v
                cfg_now[CFG_FUEL_OTP_PERSIST] = True
                save_config(cfg_now)
                self._vt_log(
                    "OTP saved (persisted). Click Fetch within "
                    "5 min before it expires.", "ok")
            else:
                # Clear any stale persisted OTP
                cfg_now = load_config()
                if cfg_now.get(CFG_FUEL_OTP):
                    cfg_now[CFG_FUEL_OTP] = ""
                    cfg_now[CFG_FUEL_OTP_PERSIST] = False
                    save_config(cfg_now)
                self._vt_log(
                    "OTP loaded for this session. Click Fetch "
                    "within 5 min.", "ok")

        tk.Button(otp_row, text="Use this OTP",
                  command=_use_otp,
                  bg=C["accent_l"], fg=C["accent"],
                  font=("Segoe UI", 9, "bold"),
                  bd=0, padx=10, pady=3,
                  cursor="hand2").pack(side="left")
        tk.Checkbutton(otp_row,
                  text="Persist (insecure)",
                  variable=self.fuel_otp_persist_var,
                  bg=C["white"], fg=C["text3"],
                  font=("Segoe UI", 8),
                  activebackground=C["white"],
                  selectcolor=C["white"]).pack(
            side="left", padx=(10, 0))

        tk.Label(wrap,
                 text="OTPs expire in ~5 min. Type the code from email, "
                      "click 'Use this OTP', then Fetch. Persist box "
                      "saves to config.json — note that OTP is useless "
                      "after expiry anyway.",
                 font=("Segoe UI", 8, "italic"),
                 bg=C["white"], fg=C["text3"]).grid(
            row=6, column=1, sticky="w", padx=12, pady=(0, 2))

        # Optional refills list URL
        tk.Label(wrap, text="Refills List URL",
                 font=("Segoe UI", 9),
                 bg=C["white"], fg=C["text2"]).grid(
            row=7, column=0, sticky="w", padx=12, pady=2)
        self.fuel_list_url_var = tk.StringVar(
            value=cfg.get(CFG_FUEL_LIST_URL, ""))
        tk.Entry(wrap, textvariable=self.fuel_list_url_var,
                 width=50, font=("Segoe UI", 9),
                 bg=C["input"], fg=C["text"], bd=1, relief="solid").grid(
            row=7, column=1, sticky="ew", padx=12, pady=2)
        tk.Label(wrap,
                 text="(Optional — paste the actual refills/transactions "
                      "page URL if site auto-route fails)",
                 font=("Segoe UI", 8, "italic"),
                 bg=C["white"], fg=C["text3"]).grid(
            row=8, column=1, sticky="w", padx=12, pady=(0, 2))

        # Save button
        def _save():
            cfg = load_config()
            cfg[CFG_FUEL_URL]      = self.fuel_url_var.get().strip()
            cfg[CFG_FUEL_USER]     = self.fuel_user_var.get().strip()
            cfg[CFG_FUEL_PASS]     = self.fuel_pass_var.get()
            cfg[CFG_FUEL_LIST_URL] = self.fuel_list_url_var.get().strip()
            save_config(cfg)
            self._vt_log("Fuel website settings saved (incl. password).",
                         "ok")

        tk.Button(wrap, text="Save Fuel Settings",
                  command=_save,
                  bg=C["accent"], fg=C["white"],
                  font=("Segoe UI", 9, "bold"),
                  bd=0, padx=14, pady=4,
                  cursor="hand2").grid(
            row=9, column=1, sticky="e", padx=12, pady=(6, 10))

        wrap.columnconfigure(1, weight=1)
        return wrap

    # ─────────────────────────────────────────────────────────────────────
    # 2. OTP MODAL DIALOG — opens on UI thread, returns OTP via queue
    # ─────────────────────────────────────────────────────────────────────
    def _fuel_prompt_otp(self, attempt=1):
        """
        Show a modal dialog asking for the OTP code. Called from the
        scraper thread; uses self.after() to render on the UI thread and
        blocks via a queue until the user submits or cancels.
        Returns: str (the OTP) or None if user cancelled / timed out.

        SHORT-CIRCUIT: If the user has pre-entered an OTP in the Vehicle
        Tracker UI ("OTP" field + "Use this OTP" button), use that on the
        first attempt instead of popping a modal. Subsequent attempts
        (rejected codes) fall through to the modal so the user can correct.
        """
        # First-attempt: try the pre-entered OTP if present
        if attempt == 1:
            pending = getattr(
                self, "_fuel_otp_pending", None)
            if pending:
                # Consume it so the next fetch doesn't reuse stale code
                self._fuel_otp_pending = None
                # Best-effort: clear the UI field too (on UI thread)
                try:
                    self.after(0, lambda:
                        self.fuel_otp_var.set("")
                        if hasattr(self, "fuel_otp_var")
                        else None)
                except Exception:
                    pass
                self.after(0, lambda v=pending: self._vt_log(
                    "Fuel: using pre-entered OTP ("
                    + str(len(v)) + " digits)", "info"))
                return pending
        result_q = queue.Queue()

        def _show_dialog():

            dlg = tk.Toplevel(self)
            dlg.title("Fuel Website — OTP Required")
            dlg.configure(bg=C["white"])
            dlg.resizable(False, False)
            dlg.transient(self)
            dlg.grab_set()
            dlg.protocol("WM_DELETE_WINDOW",
                          lambda: (result_q.put(None), dlg.destroy()))

            self.update_idletasks()
            try:
                px = self.winfo_rootx() + self.winfo_width() // 2
                py = self.winfo_rooty() + self.winfo_height() // 2
                dlg.geometry("+" + str(px - 200) + "+" + str(py - 110))
            except Exception:
                pass

            tk.Label(dlg,
                     text="🔐  OTP Required",
                     font=("Segoe UI", 13, "bold"),
                     bg=C["white"], fg=C["text"]).pack(
                anchor="w", padx=20, pady=(18, 4))

            if attempt > 1:
                msg = ("Previous OTP was rejected.\n"
                       "Check your email for the latest code and try "
                       "again.")
            else:
                msg = ("Check your email for the Aldrees OTP code.\n"
                       "Enter it below and click Submit.")
            tk.Label(dlg, text=msg,
                     font=("Segoe UI", 9),
                     bg=C["white"], fg=C["text2"],
                     justify="left").pack(
                anchor="w", padx=20, pady=(0, 12))

            otp_var = tk.StringVar()
            entry = tk.Entry(dlg, textvariable=otp_var,
                             font=("Consolas", 16),
                             bg=C["input"], fg=C["text"],
                             bd=1, relief="solid",
                             justify="center", width=14)
            entry.pack(padx=20, pady=(0, 4))
            entry.focus_set()

            err_lbl = tk.Label(dlg, text="",
                               font=("Segoe UI", 8),
                               bg=C["white"], fg=C["red"])
            err_lbl.pack(padx=20, pady=(0, 8))

            def _submit():
                v = otp_var.get().strip()
                v = re.sub(r"[^\d]", "", v)
                if not v:
                    err_lbl.config(text="Please enter the OTP code.")
                    return
                result_q.put(v)
                dlg.destroy()

            def _cancel():
                result_q.put(None)
                dlg.destroy()

            btn_row = tk.Frame(dlg, bg=C["white"])
            btn_row.pack(fill="x", padx=20, pady=(4, 18))

            tk.Button(btn_row, text="Cancel",
                      command=_cancel,
                      bg=C["input"], fg=C["text2"],
                      font=("Segoe UI", 9),
                      bd=0, padx=14, pady=6,
                      cursor="hand2").pack(side="right", padx=(8, 0))
            tk.Button(btn_row, text="Submit OTP",
                      command=_submit,
                      bg=C["accent"], fg=C["white"],
                      font=("Segoe UI", 9, "bold"),
                      bd=0, padx=14, pady=6,
                      cursor="hand2").pack(side="right")

            entry.bind("<Return>", lambda e: _submit())

        if threading.current_thread() is threading.main_thread():
            _show_dialog()
        else:
            self.after(0, _show_dialog)

        try:
            return result_q.get(timeout=300)
        except queue.Empty:
            return None

    # ─────────────────────────────────────────────────────────────────────
    # 3. SCRAPE — Aldrees WAIE login (user + pass + OTP same page)
    # ─────────────────────────────────────────────────────────────────────
    def fuel_fetch_refills(self, df, dt_end):
        cfg = load_config()

        url      = (cfg.get(CFG_FUEL_URL, "")  or "").strip().rstrip("/")
        user     = (cfg.get(CFG_FUEL_USER, "") or "").strip()
        pwd      = cfg.get(CFG_FUEL_PASS, "") or ""
        list_url = (cfg.get(CFG_FUEL_LIST_URL, "") or "").strip()

        # Fall back to live entry if config empty
        if not pwd and hasattr(self, "fuel_pass_var"):
            try:
                pwd = self.fuel_pass_var.get()
            except Exception:
                pass

        if not url or not user or not pwd:
            self._vt_log(
                "Fuel: credentials missing — fill URL, username, password "
                "and click Save Fuel Settings.", "warn")
            return None

        try:
            df_dt = datetime.strptime(df, "%Y-%m-%d").date()
            dt_dt = datetime.strptime(dt_end, "%Y-%m-%d").date()
        except ValueError:
            self._vt_log("Fuel: invalid date format.", "err")
            return None

        m_first, m_last = _fuel_month_bounds(df_dt)
        scrape_from = min(df_dt, m_first)
        scrape_to   = max(dt_dt, m_last)

        self._vt_log(
            "Fuel: scraping " + scrape_from.strftime("%Y-%m-%d") +
            " → " + scrape_to.strftime("%Y-%m-%d") + " ...", "info")

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self._vt_log("Playwright not installed — fuel scrape skipped.",
                         "err")
            return None

        raw_records = []

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                ctx = browser.new_context(
                    viewport={"width": 1400, "height": 900})
                page = ctx.new_page()

                # ── Step 1: Open login page ──────────────────────────────
                self._vt_log("Fuel: opening " + url, "info")
                try:
                    page.goto(url, wait_until="networkidle",
                              timeout=45000)
                except Exception as ex:
                    self._vt_log("Fuel: cannot reach site — " +
                                 str(ex)[:120], "err")
                    browser.close()
                    return None

                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass

                # ── Step 2: Locate username/password/OTP fields ──────────
                user_selectors = [
                    'input[name="username"]',
                    'input[name="UserName"]',
                    'input[name="Username"]',
                    'input[name="Email"]',
                    'input[name="email"]',
                    'input[id*="username" i]',
                    'input[id*="UserName"]',
                    'input[id*="Email"]',
                    'input[type="email"]',
                    'input[placeholder*="user" i]',
                    'input[placeholder*="email" i]',
                ]
                pass_selectors = [
                    'input[name="password"]',
                    'input[name="Password"]',
                    'input[id*="password" i]',
                    'input[id*="Password"]',
                    'input[type="password"]',
                ]
                otp_selectors = [
                    'input[name="otp" i]',
                    'input[name="OTP"]',
                    'input[name="code" i]',
                    'input[name="verificationCode"]',
                    'input[id*="otp" i]',
                    'input[id*="OTP"]',
                    'input[id*="code" i]',
                    'input[id*="verification" i]',
                    'input[placeholder*="otp" i]',
                    'input[placeholder*="code" i]',
                    'input[placeholder*="verification" i]',
                    'input[autocomplete="one-time-code"]',
                    'input[inputmode="numeric"]',
                ]

                user_filled = False
                pass_filled = False
                otp_selector_used = None

                for sel in user_selectors:
                    try:
                        if page.locator(sel).count() > 0:
                            page.fill(sel, user)
                            user_filled = True
                            self._vt_log("Fuel: username filled (" +
                                         sel + ")", "info")
                            break
                    except Exception:
                        continue

                for sel in pass_selectors:
                    try:
                        if page.locator(sel).count() > 0:
                            page.fill(sel, pwd)
                            pass_filled = True
                            self._vt_log("Fuel: password filled (" +
                                         sel + ")", "info")
                            break
                    except Exception:
                        continue

                for sel in otp_selectors:
                    try:
                        if page.locator(sel).count() > 0:
                            try:
                                if page.locator(sel).first.is_visible():
                                    otp_selector_used = sel
                                    break
                            except Exception:
                                otp_selector_used = sel
                                break
                    except Exception:
                        continue

                if not (user_filled and pass_filled):
                    self._vt_log(
                        "Fuel: could not find both username and password "
                        "fields. The site may have changed.", "err")
                    browser.close()
                    return None

                # ── Step 3: Prompt user for OTP ──────────────────────────
                if otp_selector_used:
                    self._vt_log(
                        "Fuel: OTP field detected — prompting user...",
                        "info")
                else:
                    self._vt_log(
                        "Fuel: no OTP field on first page; will prompt "
                        "anyway in case site shows OTP post-submit.",
                        "info")

                # OTP retry loop
                logged_in = False
                attempt = 1
                max_attempts = 3
                while attempt <= max_attempts:
                    otp_code = self._fuel_prompt_otp(attempt=attempt)
                    if otp_code is None:
                        self._vt_log(
                            "Fuel: user cancelled OTP prompt.", "warn")
                        browser.close()
                        return None

                    # Fill OTP if field is on the same page
                    if otp_selector_used:
                        try:
                            page.fill(otp_selector_used, otp_code)
                            self._vt_log(
                                "Fuel: OTP entered, submitting...",
                                "info")
                        except Exception as ex:
                            self._vt_log("Fuel: fill OTP failed: " +
                                         str(ex)[:80], "err")
                            browser.close()
                            return None

                    # Submit
                    submitted = False
                    for btn_sel in [
                        'button[type="submit"]',
                        'input[type="submit"]',
                        'button:has-text("Login")',
                        'button:has-text("Sign in")',
                        'button:has-text("Submit")',
                        'button:has-text("Verify")',
                        'button:has-text("تسجيل")',
                        'button:has-text("دخول")',
                    ]:
                        try:
                            if page.locator(btn_sel).count() > 0:
                                page.locator(btn_sel).first.click()
                                submitted = True
                                break
                        except Exception:
                            continue
                    if not submitted:
                        try:
                            if otp_selector_used:
                                page.locator(otp_selector_used).press(
                                    "Enter")
                            else:
                                page.locator(pass_selectors[0]).press(
                                    "Enter")
                            submitted = True
                        except Exception:
                            pass

                    if not submitted:
                        self._vt_log("Fuel: no submit button found.",
                                     "err")
                        browser.close()
                        return None

                    try:
                        page.wait_for_load_state(
                            "networkidle", timeout=30000)
                    except Exception:
                        pass

                    # Check outcome
                    pg_text = (page.content() or "").lower()
                    otp_fail = False
                    for marker in [
                        "invalid otp", "incorrect otp", "wrong otp",
                        "invalid code", "incorrect code",
                        "verification failed", "otp expired",
                        "invalid verification",
                    ]:
                        if marker in pg_text:
                            otp_fail = True
                            break
                    if otp_fail:
                        self._vt_log(
                            "Fuel: OTP rejected (" + str(attempt) +
                            "/" + str(max_attempts) + ").", "warn")
                        attempt += 1
                        continue

                    if ("invalid" in pg_text and
                            ("password" in pg_text or "user" in pg_text)):
                        self._vt_log(
                            "Fuel: username/password rejected.", "err")
                        browser.close()
                        return None

                    has_pwd = False
                    try:
                        has_pwd = (page.locator(
                            'input[type="password"]').count() > 0)
                    except Exception:
                        pass
                    if has_pwd and "logout" not in pg_text:
                        self._vt_log(
                            "Fuel: still on login page after submit (" +
                            str(attempt) + "). Probably wrong OTP.",
                            "warn")
                        attempt += 1
                        continue

                    self._vt_log("Fuel: login OK.", "ok")
                    logged_in = True
                    break

                if not logged_in:
                    self._vt_log(
                        "Fuel: " + str(max_attempts) + " OTP attempts "
                        "failed — aborting.", "err")
                    browser.close()
                    return None

                # ── Step 4: Navigate to refills page ─────────────────────
                if list_url:
                    target = list_url
                else:
                    base = re.match(r"^(https?://[^/]+)", page.url)
                    base = base.group(1) if base else url
                    target = base + "/Fleet/transactions"

                self._vt_log("Fuel: opening refills page " + target,
                             "info")
                try:
                    page.goto(target, wait_until="networkidle",
                              timeout=45000)
                except Exception as ex:
                    self._vt_log(
                        "Fuel: refills nav failed (" +
                        str(ex)[:80] + ") — using current page.",
                        "warn")

                # ── Step 5: Set date filter ──────────────────────────────
                df_str = scrape_from.strftime("%Y-%m-%d")
                dt_str = scrape_to.strftime("%Y-%m-%d")
                for from_sel, to_sel in [
                    ('input[name="date_from"]',  'input[name="date_to"]'),
                    ('input[name="from_date"]',  'input[name="to_date"]'),
                    ('input[name="start_date"]', 'input[name="end_date"]'),
                    ('input[name="DateFrom"]',   'input[name="DateTo"]'),
                    ('input[name="fromDate"]',   'input[name="toDate"]'),
                    ('#date_from',               '#date_to'),
                    ('#fromDate',                '#toDate'),
                ]:
                    try:
                        if (page.locator(from_sel).count() > 0 and
                                page.locator(to_sel).count() > 0):
                            page.fill(from_sel, df_str)
                            page.fill(to_sel, dt_str)
                            for btn in [
                                'button:has-text("Search")',
                                'button:has-text("Filter")',
                                'button:has-text("Apply")',
                                'button:has-text("Show")',
                                'button[type="submit"]',
                            ]:
                                try:
                                    if page.locator(btn).count() > 0:
                                        page.locator(btn).first.click()
                                        break
                                except Exception:
                                    pass
                            page.wait_for_load_state(
                                "networkidle", timeout=20000)
                            break
                    except Exception:
                        continue

                # ── Step 6: Extract table ────────────────────────────────
                extract_js = r"""() => {
                    const tables = Array.from(
                        document.querySelectorAll('table'));
                    if (!tables.length) return {error: 'no tables'};
                    const wantHeaders = [
                        'plate','vehicle','registration','reg no',
                        'litres','liters','litre','liter','quantity','qty',
                        'amount','sar','cost','total','price',
                        'date','time','transaction'
                    ];
                    let best = null, bestScore = -1;
                    tables.forEach(t => {
                        const ths = Array.from(t.querySelectorAll(
                            'thead th, thead td, tr:first-child th'));
                        const headers = ths.map(h =>
                            (h.innerText||'').trim().toLowerCase());
                        let score = 0;
                        wantHeaders.forEach(w => {
                            if (headers.some(h => h.includes(w))) score++;
                        });
                        const rows = t.querySelectorAll('tbody tr, tr');
                        score += Math.min(rows.length, 50) * 0.01;
                        if (score > bestScore) {
                            bestScore = score; best = t;
                        }
                    });
                    if (!best || bestScore < 2)
                        return {error: 'no suitable table'};
                    const ths = Array.from(best.querySelectorAll(
                        'thead th, thead td, tr:first-child th, tr:first-child td'));
                    const headers = ths.map(h =>
                        (h.innerText||'').trim().toLowerCase());
                    const findCol = (...keys) => {
                        for (let k of keys) {
                            const i = headers.findIndex(h => h.includes(k));
                            if (i >= 0) return i;
                        }
                        return -1;
                    };
                    const idxDate = findCol('date','time','transaction');
                    const idxPlate = findCol(
                        'plate','vehicle','registration','reg');
                    const idxLitres = findCol(
                        'litre','liter','quantity','qty');
                    const idxAmount = findCol(
                        'amount','sar','cost','total','price');
                    const idxLoc = findCol(
                        'station','pump','location','site');
                    const out = [];
                    const rows = best.querySelectorAll('tbody tr, tr');
                    rows.forEach((r, i) => {
                        if (i === 0 && headers.length) return;
                        const cells = Array.from(
                            r.querySelectorAll('td'));
                        if (!cells.length) return;
                        const get = j => (j >= 0 && cells[j]) ?
                            (cells[j].innerText||'').trim() : '';
                        out.push({
                            date: get(idxDate),
                            plate: get(idxPlate),
                            litres: get(idxLitres),
                            amount: get(idxAmount),
                            location: get(idxLoc),
                        });
                    });
                    return {headers: headers, rows: out};
                }"""
                try:
                    result = page.evaluate(extract_js)
                except Exception as ex:
                    self._vt_log("Fuel: table extract failed: " +
                                 str(ex)[:120], "err")
                    browser.close()
                    return None

                browser.close()

                if not result or "error" in result:
                    self._vt_log(
                        "Fuel: " + (result.get("error", "no data")
                                    if result else "no result") +
                        " — set the Refills List URL manually.", "err")
                    return None

                rows = result.get("rows", [])
                self._vt_log(
                    "Fuel: " + str(len(rows)) +
                    " refill rows extracted.", "ok")

                for r in rows:
                    plate_raw = (r.get("plate", "") or "").strip()
                    if not plate_raw:
                        continue
                    date_raw = (r.get("date", "") or "").strip()
                    dts = None
                    for fmt in (
                        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                        "%Y-%m-%d", "%d/%m/%Y %H:%M",
                        "%d/%m/%Y", "%d-%m-%Y",
                        "%m/%d/%Y", "%d %b %Y", "%d %B %Y",
                    ):
                        try:
                            dts = datetime.strptime(date_raw, fmt)
                            break
                        except ValueError:
                            continue
                    if dts is None:
                        continue
                    raw_records.append({
                        "date":      dts,
                        "plate_raw": plate_raw,
                        "plate_norm": _fuel_normalize_plate(plate_raw),
                        "litres":    _fuel_parse_num(r.get("litres", "")),
                        "sar":       _fuel_parse_num(r.get("amount", "")),
                        "location":  (r.get("location", "") or "").strip(),
                    })

        except Exception as ex:
            self._vt_log("Fuel: scrape error — " + str(ex)[:200], "err")
            return None

        # Aggregate
        range_agg = {}
        month_agg = {}
        for rec in raw_records:
            d = rec["date"].date()
            pn = rec["plate_norm"]
            if not pn:
                continue
            if df_dt <= d <= dt_dt:
                a = range_agg.setdefault(
                    pn, {"count": 0, "litres": 0.0, "sar": 0.0,
                         "plate_raw": rec["plate_raw"]})
                a["count"]  += 1
                a["litres"] += rec["litres"]
                a["sar"]    += rec["sar"]
            if m_first <= d <= m_last:
                a = month_agg.setdefault(
                    pn, {"count": 0, "litres": 0.0, "sar": 0.0,
                         "plate_raw": rec["plate_raw"]})
                a["count"]  += 1
                a["litres"] += rec["litres"]
                a["sar"]    += rec["sar"]

        return {
            "range":       range_agg,
            "month":       month_agg,
            "raw":         raw_records,
            "month_label": m_first.strftime("%B %Y"),
            "df":          df_dt,
            "dt":          dt_dt,
            "m_first":     m_first,
            "m_last":      m_last,
        }

    # ─────────────────────────────────────────────────────────────────────
    # 4. MERGE
    # ─────────────────────────────────────────────────────────────────────
    def fuel_merge_into_plate_agg(self, plate_agg, fuel_data):
        if not fuel_data:
            for plate, agg in plate_agg.items():
                agg.setdefault("fuel_refill_count", 0)
                agg.setdefault("fuel_month_litres", 0.0)
                agg.setdefault("fuel_month_sar",    0.0)
                agg.setdefault("fuel_only", False)
            return plate_agg

        range_agg = fuel_data.get("range", {})
        month_agg = fuel_data.get("month", {})

        norm_to_existing = {
            _fuel_normalize_plate(p): p for p in plate_agg.keys()}

        for plate, agg in plate_agg.items():
            pn = _fuel_normalize_plate(plate)
            r = range_agg.get(pn)
            m = month_agg.get(pn)
            agg["fuel_refill_count"] = (r["count"] if r else 0)
            agg["fuel_month_litres"] = (m["litres"] if m else 0.0)
            agg["fuel_month_sar"]    = (m["sar"]    if m else 0.0)
            agg["fuel_only"]         = False

        added = 0
        for pn, m in month_agg.items():
            if pn in norm_to_existing:
                continue
            plate_label = m.get("plate_raw") or pn
            r = range_agg.get(pn)
            plate_agg[plate_label] = {
                "trips":             [],
                "v_type":            self._vt_plate_types.get(
                                         plate_label, "—"),
                "n_closed":          0,
                "n_open":            0,
                "n_nodata":          0,
                "work_s":            0,
                "idle_s":            0,
                "idle_segs":         [],
                "util":              0,
                "dispatch_util":     0,
                "cal_util":          0,
                "total_amt":         0.0,
                "total_km":          0.0,
                "fuel_refill_count": (r["count"] if r else 0),
                "fuel_month_litres": m["litres"],
                "fuel_month_sar":    m["sar"],
                "fuel_only":         True,
            }
            added += 1

        if added:
            self._vt_log(
                "Fuel: " + str(added) +
                " vehicle(s) had refills but no trips — added as "
                "[FUEL ONLY] rows.", "info")

        return plate_agg


# ─────────────────────────────────────────────────────────────────────────
# Column formatters
# ─────────────────────────────────────────────────────────────────────────
def fuel_format_refill_count(n):
    return str(int(n)) if n else "—"


def fuel_format_month_total(litres, sar):
    if not litres and not sar:
        return "—"
    return ("{:,.0f}".format(litres or 0) + " L / " +
            "{:,.0f}".format(sar or 0))


# ── GPS integration (was gps_module.py) ───────────────────────────
# ─────────────────────────────────────────────────────────────────────────
# CONFIG KEYS  (saved alongside zeeta_erp_* and fuel_* in config.json)
# ─────────────────────────────────────────────────────────────────────────
CFG_GPS_URL         = "gps_url"
CFG_GPS_USER        = "gps_user"
CFG_GPS_REPORT_URL  = "gps_report_url"   # optional override

# Default tolerances for marking a vehicle as "Mismatch"
DEFAULT_TIME_TOLERANCE_MIN = 30   # 30 minutes
DEFAULT_KM_TOLERANCE_PCT   = 10   # 10% of Zeeta km


# ─────────────────────────────────────────────────────────────────────────
# Helpers — duplicated from fuel_module so this file stands alone
# ─────────────────────────────────────────────────────────────────────────
def _gps_parse_num(s):
    if s is None:
        return 0.0
    s = str(s).strip().replace(",", "")
    m = re.search(r"([-+]?\d+(?:\.\d+)?)", s)
    if not m:
        return 0.0
    try:
        return float(m.group(1))
    except ValueError:
        return 0.0


def _gps_normalize_plate(p):
    if not p:
        return ""
    s = str(p).strip().upper()
    for ch in (" ", "-", "_", "/", ".", "·"):
        s = s.replace(ch, "")
    return s


def _gps_parse_duration(s):
    """
    Parse a duration string into total seconds.
    Handles formats like '5h 23m', '5:23:00', '323 min', '5.5h'.
    """
    if not s:
        return 0
    s = str(s).strip().lower()
    if not s:
        return 0
    # 'HH:MM:SS' or 'HH:MM'
    if ":" in s:
        parts = s.split(":")
        try:
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
            sec = int(parts[2]) if len(parts) > 2 else 0
            return h * 3600 + m * 60 + sec
        except ValueError:
            pass
    # '5h 23m'
    h = re.search(r"(\d+(?:\.\d+)?)\s*h", s)
    m = re.search(r"(\d+(?:\.\d+)?)\s*m(?!s)", s)  # not 'ms'
    if h or m:
        return int((float(h.group(1)) if h else 0) * 3600 +
                   (float(m.group(1)) if m else 0) * 60)
    # 'NNN min' / 'NNN minutes'
    if "min" in s:
        n = _gps_parse_num(s)
        return int(n * 60)
    # Plain number — assume hours if small, seconds if huge
    n = _gps_parse_num(s)
    if n < 100:
        return int(n * 3600)
    return int(n)


def _gps_fmt_duration(secs):
    """Match main.py's vehicle-tracker fmt: '5h 23m'."""
    if not secs:
        return "0h 00m"
    secs = int(secs)
    h = secs // 3600
    m = (secs % 3600) // 60
    return str(h) + "h " + str(m).zfill(2) + "m"


# ─────────────────────────────────────────────────────────────────────────
# Mixin class — add to App via subclassing alongside FuelMixin
# ─────────────────────────────────────────────────────────────────────────
class GpsMixin:
    """
    Methods to mix into the App class in main.py.

    To integrate: change
        class App(tk.Tk, FuelMixin):
    to
        class App(tk.Tk, FuelMixin, GpsMixin):
    and apply the splices in PATCH_INSTRUCTIONS_GPS.md.
    """

    # ─────────────────────────────────────────────────────────────────────
    # 1. UI — credentials block
    # ─────────────────────────────────────────────────────────────────────
    def build_gps_credentials_block(self, parent_frame, C):
        """
        Render a small credentials form for the GPS tracking site.
        Mirrors build_fuel_credentials_block exactly in style.
        """
        cfg = load_config()

        wrap = tk.Frame(parent_frame, bg=C["white"], bd=1, relief="solid",
                        highlightbackground=C["border"])
        wrap.pack(fill="x", padx=14, pady=(8, 4))

        tk.Label(wrap, text="GPS Tracking (Arabitra / Ctrack)",
                 font=("Segoe UI", 10, "bold"),
                 bg=C["white"], fg=C["text"]).grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 2),
            columnspan=2)

        # URL
        tk.Label(wrap, text="Login URL", font=("Segoe UI", 9),
                 bg=C["white"], fg=C["text2"]).grid(
            row=1, column=0, sticky="w", padx=12, pady=2)
        self.gps_url_var = tk.StringVar(
            value=cfg.get(CFG_GPS_URL, "https://arabitra.net/"))
        tk.Entry(wrap, textvariable=self.gps_url_var,
                 width=50, font=("Segoe UI", 9),
                 bg=C["input"], fg=C["text"], bd=1, relief="solid").grid(
            row=1, column=1, sticky="ew", padx=12, pady=2)

        # Username
        tk.Label(wrap, text="Username", font=("Segoe UI", 9),
                 bg=C["white"], fg=C["text2"]).grid(
            row=2, column=0, sticky="w", padx=12, pady=2)
        self.gps_user_var = tk.StringVar(value=cfg.get(CFG_GPS_USER, ""))
        tk.Entry(wrap, textvariable=self.gps_user_var,
                 width=50, font=("Segoe UI", 9),
                 bg=C["input"], fg=C["text"], bd=1, relief="solid").grid(
            row=2, column=1, sticky="ew", padx=12, pady=2)

        # Password (NOT saved)
        tk.Label(wrap, text="Password", font=("Segoe UI", 9),
                 bg=C["white"], fg=C["text2"]).grid(
            row=3, column=0, sticky="w", padx=12, pady=2)
        self.gps_pass_var = tk.StringVar(value="")
        tk.Entry(wrap, textvariable=self.gps_pass_var,
                 show="•", width=50, font=("Segoe UI", 9),
                 bg=C["input"], fg=C["text"], bd=1, relief="solid").grid(
            row=3, column=1, sticky="ew", padx=12, pady=2)
        tk.Label(wrap,
                 text="Password is never saved — type each session",
                 font=("Segoe UI", 8, "italic"),
                 bg=C["white"], fg=C["text3"]).grid(
            row=4, column=1, sticky="w", padx=12, pady=(0, 2))

        # Optional report URL override
        tk.Label(wrap, text="Report URL",
                 font=("Segoe UI", 9),
                 bg=C["white"], fg=C["text2"]).grid(
            row=5, column=0, sticky="w", padx=12, pady=2)
        self.gps_report_url_var = tk.StringVar(
            value=cfg.get(CFG_GPS_REPORT_URL, ""))
        tk.Entry(wrap, textvariable=self.gps_report_url_var,
                 width=50, font=("Segoe UI", 9),
                 bg=C["input"], fg=C["text"], bd=1, relief="solid").grid(
            row=5, column=1, sticky="ew", padx=12, pady=2)
        tk.Label(wrap,
                 text="(Optional — leave empty for auto-detect of "
                      "trip/working-hours report)",
                 font=("Segoe UI", 8, "italic"),
                 bg=C["white"], fg=C["text3"]).grid(
            row=6, column=1, sticky="w", padx=12, pady=(0, 2))

        # Save button
        def _save():
            cfg = load_config()
            cfg[CFG_GPS_URL]        = self.gps_url_var.get().strip()
            cfg[CFG_GPS_USER]       = self.gps_user_var.get().strip()
            cfg[CFG_GPS_REPORT_URL] = self.gps_report_url_var.get().strip()
            save_config(cfg)
            self._vt_log("GPS tracking settings saved.", "ok")

        tk.Button(wrap, text="Save GPS Settings",
                  command=_save,
                  bg=C["accent"], fg=C["white"],
                  font=("Segoe UI", 9, "bold"),
                  bd=0, padx=14, pady=4,
                  cursor="hand2").grid(
            row=7, column=1, sticky="e", padx=12, pady=(6, 10))

        wrap.columnconfigure(1, weight=1)
        return wrap

    # ─────────────────────────────────────────────────────────────────────
    # 2. SCRAPE — fetch GPS working/idle/km per vehicle for date range
    # ─────────────────────────────────────────────────────────────────────
    def gps_fetch_activity(self, df, dt_end):
        """
        Scrape Arabitra (Ctrack) for per-vehicle activity in [df, dt_end].

        Returns dict:
        {
          "vehicles": {
             plate_norm: {
               "plate_raw": "ABC 1234",
               "working_s": 234500,    # engine-on hours in seconds
               "idle_s":    18900,     # idle (engine on, not moving)
               "km":        1420.5,    # GPS-measured km
               "trips": [               # ignition-on / off events
                  {"start": dt, "end": dt, "km": 145.2,
                   "idle_s": 2400, "max_speed": 87},
                  ...
               ],
             }
          }
        }
        Returns None on failure.
        """
        cfg = load_config()

        url  = (cfg.get(CFG_GPS_URL, "")  or "").strip().rstrip("/")
        user = (cfg.get(CFG_GPS_USER, "") or "").strip()
        pwd  = (getattr(self, "gps_pass_var", None).get().strip()
                if hasattr(self, "gps_pass_var") else "")
        report_url = (cfg.get(CFG_GPS_REPORT_URL, "") or "").strip()

        if not url or not user or not pwd:
            self._vt_log(
                "GPS: credentials missing — fill URL, username and "
                "password in GPS Tracking settings.", "warn")
            return None

        try:
            df_dt = datetime.strptime(df, "%Y-%m-%d").date()
            dt_dt = datetime.strptime(dt_end, "%Y-%m-%d").date()
        except ValueError:
            self._vt_log("GPS: invalid date format.", "err")
            return None

        self._vt_log(
            "GPS: scraping Arabitra " + df + " → " + dt_end + " ...",
            "info")

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self._vt_log("Playwright not installed — GPS scrape skipped.",
                         "err")
            return None

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                # Larger viewport — Ctrack reports are wide tables
                ctx = browser.new_context(
                    viewport={"width": 1600, "height": 900})
                page = ctx.new_page()

                # ── Step 1: Login ─────────────────────────────────────────
                self._vt_log("GPS: opening login page...", "info")
                try:
                    page.goto(url, wait_until="networkidle",
                              timeout=45000)
                except Exception as ex:
                    self._vt_log("GPS: cannot reach " + url +
                                 " — " + str(ex)[:120], "err")
                    browser.close()
                    return None

                # Arabitra.net selectors (modern login page) +
                # Ctrack-Online selectors (legacy portal) +
                # generic fallback
                login_ok = False
                for u_sel, p_sel, btn_sel in [
                    # arabitra.net (modern)
                    ('input[name="username"]',
                     'input[name="password"]',
                     'button[type="submit"]'),
                    ('input[name="email"]',
                     'input[name="password"]',
                     'button[type="submit"]'),
                    # Ctrack Online (legacy ASP.NET — uses ID attributes)
                    ('input[id*="UserName"]',
                     'input[id*="Password"]',
                     'input[type="submit"]'),
                    ('input[id*="txtUsername"]',
                     'input[id*="txtPassword"]',
                     'input[id*="btnLogin"]'),
                    # Generic fallbacks
                    ('input[type="text"]',
                     'input[type="password"]',
                     'button[type="submit"]'),
                    ('#username', '#password',
                     'button, input[type="submit"]'),
                ]:
                    try:
                        if (page.locator(u_sel).count() > 0 and
                                page.locator(p_sel).count() > 0):
                            page.fill(u_sel, user)
                            page.fill(p_sel, pwd)
                            try:
                                if page.locator(btn_sel).count() > 0:
                                    page.locator(btn_sel).first.click()
                                else:
                                    page.locator(p_sel).press("Enter")
                            except Exception:
                                page.locator(p_sel).press("Enter")
                            page.wait_for_load_state(
                                "networkidle", timeout=30000)
                            login_ok = True
                            break
                    except Exception:
                        continue

                if not login_ok:
                    self._vt_log("GPS: login form not found at " + url,
                                 "err")
                    browser.close()
                    return None

                # Detect login failure
                pg_lower = (page.content() or "").lower()
                fail_markers = ["invalid", "incorrect", "wrong password",
                                "login failed"]
                if any(m in pg_lower for m in fail_markers) and \
                   "logout" not in pg_lower:
                    self._vt_log("GPS: login rejected (bad credentials).",
                                 "err")
                    browser.close()
                    return None

                self._vt_log("GPS: login OK.", "ok")

                # ── Step 2: Navigate to a usable report ───────────────────
                # Order of preference:
                #   1. User-supplied report URL
                #   2. Ctrack "Trip Summary" report (best — has per-trip
                #      working time, distance, idle)
                #   3. "Working Hours" / "Activity" report
                #   4. "Vehicle Summary" dashboard
                report_targets = []
                if report_url:
                    report_targets.append(report_url)

                # Ctrack-Online standard report URLs (best-effort)
                # The common path pattern is /Online/Reports/<name>.aspx
                # We try a few of the most useful for cross-check
                base_match = re.match(r"^(https?://[^/]+)", page.url)
                base = base_match.group(1) if base_match else url
                for path in (
                    "/Online/Reports/TripSummary.aspx",
                    "/Online/Reports/TripDetailsReport.aspx",
                    "/Online/Reports/SummaryUsageReport.aspx",
                    "/Online/Reports/WorkingHours.aspx",
                    "/Online/Reports/IdleReport.aspx",
                    "/reports/trip-summary",
                    "/reports/working-hours",
                    "/reports/activity",
                    "/reports",
                ):
                    report_targets.append(base + path)

                report_html = None
                report_used = None
                for tgt in report_targets:
                    try:
                        self._vt_log("GPS: trying " + tgt, "info")
                        page.goto(tgt, wait_until="networkidle",
                                  timeout=30000)
                        # Heuristic: page has a date range form +
                        # contains plate-like content
                        c = (page.content() or "").lower()
                        if ("date" in c and
                                ("plate" in c or "vehicle" in c or
                                 "registration" in c) and
                                "report" in c):
                            report_html = page.content()
                            report_used = tgt
                            self._vt_log("GPS: report page reachable: " +
                                         tgt, "ok")
                            break
                    except Exception:
                        continue

                if not report_html:
                    self._vt_log(
                        "GPS: no report page reachable. Set 'Report URL' "
                        "manually in GPS Tracking settings to your "
                        "Trip Summary or Working Hours report URL.",
                        "warn")
                    browser.close()
                    return None

                # ── Step 3: Set date range on the report form ────────────
                df_str = df_dt.strftime("%Y-%m-%d")
                dt_str = dt_dt.strftime("%Y-%m-%d")
                # Also try a couple of other common formats
                df_alt = df_dt.strftime("%d/%m/%Y")
                dt_alt = dt_dt.strftime("%d/%m/%Y")

                date_set_ok = False
                for from_sel, to_sel in [
                    # Ctrack-Online ASP.NET
                    ('input[id*="DateFrom"]', 'input[id*="DateTo"]'),
                    ('input[id*="dateFrom"]', 'input[id*="dateTo"]'),
                    ('input[id*="StartDate"]','input[id*="EndDate"]'),
                    # Generic
                    ('input[name="date_from"]',  'input[name="date_to"]'),
                    ('input[name="from_date"]',  'input[name="to_date"]'),
                    ('input[name="start_date"]', 'input[name="end_date"]'),
                    ('#date_from',               '#date_to'),
                    ('#startDate',               '#endDate'),
                ]:
                    try:
                        if (page.locator(from_sel).count() > 0 and
                                page.locator(to_sel).count() > 0):
                            # Try ISO first
                            try:
                                page.fill(from_sel, df_str)
                                page.fill(to_sel, dt_str)
                            except Exception:
                                page.fill(from_sel, df_alt)
                                page.fill(to_sel, dt_alt)
                            # Submit
                            for btn in [
                                'input[id*="btnRun"]',
                                'input[id*="btnSubmit"]',
                                'button:has-text("Run")',
                                'button:has-text("Generate")',
                                'button:has-text("Search")',
                                'button:has-text("Apply")',
                                'button[type="submit"]',
                                'input[type="submit"]',
                            ]:
                                try:
                                    if page.locator(btn).count() > 0:
                                        page.locator(btn).first.click()
                                        break
                                except Exception:
                                    pass
                            page.wait_for_load_state(
                                "networkidle", timeout=45000)
                            date_set_ok = True
                            break
                    except Exception:
                        continue

                if not date_set_ok:
                    self._vt_log(
                        "GPS: could not locate date inputs on report page "
                        "— extracting whatever's currently shown.",
                        "warn")

                # ── Step 4: Extract the report table ──────────────────────
                extract_js = r"""() => {
                    const tables = Array.from(
                        document.querySelectorAll('table'));
                    if (!tables.length) return {error: 'no tables'};

                    const wantHeaders = [
                        'plate','vehicle','registration','reg no','asset',
                        'date','start','end','from','to',
                        'distance','km','mileage','odometer',
                        'duration','time','hours','engine',
                        'idle','idling','stopped',
                        'speed','max speed',
                        'driver','journey','trip',
                    ];

                    let best = null, bestScore = -1;
                    tables.forEach(t => {
                        const ths = Array.from(t.querySelectorAll(
                            'thead th, thead td, tr:first-child th'));
                        const headers = ths.map(h =>
                            (h.innerText||'').trim().toLowerCase());
                        let score = 0;
                        wantHeaders.forEach(w => {
                            if (headers.some(h => h.includes(w))) score++;
                        });
                        const rows = t.querySelectorAll('tbody tr, tr');
                        score += Math.min(rows.length, 200) * 0.005;
                        if (score > bestScore) {
                            bestScore = score; best = t;
                        }
                    });
                    if (!best || bestScore < 2) {
                        return {error: 'no suitable table'};
                    }

                    const ths = Array.from(best.querySelectorAll(
                        'thead th, thead td, tr:first-child th, tr:first-child td'));
                    const headers = ths.map(h =>
                        (h.innerText||'').trim().toLowerCase());

                    const findCol = (...keys) => {
                        for (let k of keys) {
                            const i = headers.findIndex(h => h.includes(k));
                            if (i >= 0) return i;
                        }
                        return -1;
                    };
                    const idxPlate    = findCol(
                        'plate','registration','reg','vehicle','asset');
                    const idxStart    = findCol(
                        'start','from','depart','begin');
                    const idxEnd      = findCol(
                        'end','to','arrive','finish');
                    const idxDistance = findCol(
                        'distance','km','mileage','odometer');
                    const idxDuration = findCol(
                        'duration','total time','engine','running');
                    const idxIdle     = findCol(
                        'idle','idling','stopped');
                    const idxMaxSpeed = findCol(
                        'max speed','top speed');
                    const idxDate     = findCol('date');

                    const out = [];
                    const rows = best.querySelectorAll(
                        'tbody tr, tr');
                    rows.forEach((r, i) => {
                        if (i === 0 && headers.length) return;
                        const cells = Array.from(
                            r.querySelectorAll('td'));
                        if (!cells.length) return;
                        const get = j => (j >= 0 && cells[j]) ?
                            (cells[j].innerText||'').trim() : '';
                        out.push({
                            plate:    get(idxPlate),
                            date:     get(idxDate),
                            start:    get(idxStart),
                            end:      get(idxEnd),
                            distance: get(idxDistance),
                            duration: get(idxDuration),
                            idle:     get(idxIdle),
                            max_speed: get(idxMaxSpeed),
                        });
                    });
                    return {headers: headers, rows: out,
                            url: window.location.href};
                }"""
                try:
                    result = page.evaluate(extract_js)
                except Exception as ex:
                    self._vt_log(
                        "GPS: table extract failed — " + str(ex)[:120],
                        "err")
                    browser.close()
                    return None

                browser.close()

                if not result or "error" in result:
                    self._vt_log(
                        "GPS: " + (result.get("error", "no data")
                                   if result else "no result"),
                        "err")
                    return None

                rows = result.get("rows", [])
                self._vt_log(
                    "GPS: " + str(len(rows)) + " activity rows extracted.",
                    "ok")

        except Exception as ex:
            self._vt_log("GPS: scrape error — " + str(ex)[:200], "err")
            return None

        # ── Step 5: Aggregate per-vehicle ────────────────────────────────
        vehicles = {}

        def _try_parse_dt(s):
            for fmt in (
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
                "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M",
                "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
            ):
                try:
                    return datetime.strptime(s, fmt)
                except ValueError:
                    continue
            return None

        for r in rows:
            plate_raw = (r.get("plate", "") or "").strip()
            if not plate_raw:
                continue
            pn = _gps_normalize_plate(plate_raw)
            if not pn:
                continue

            # Filter to date range — try start-time, fall back to date
            dt_start = _try_parse_dt(r.get("start", ""))
            if dt_start is None:
                # Try combining 'date' + 'start' as time
                _d = (r.get("date", "") or "").strip()
                _t = (r.get("start", "") or "").strip()
                if _d and _t:
                    dt_start = _try_parse_dt(_d + " " + _t)
            dt_end_t = _try_parse_dt(r.get("end", ""))

            # If we have any timestamp, check it's in range
            if dt_start:
                if not (df_dt <= dt_start.date() <= dt_dt):
                    continue

            distance = _gps_parse_num(r.get("distance", ""))
            duration_s = _gps_parse_duration(r.get("duration", ""))
            idle_s     = _gps_parse_duration(r.get("idle", ""))
            max_speed  = _gps_parse_num(r.get("max_speed", ""))

            v = vehicles.setdefault(pn, {
                "plate_raw": plate_raw,
                "working_s": 0,
                "idle_s":    0,
                "km":        0.0,
                "trips":     [],
            })
            v["working_s"] += duration_s
            v["idle_s"]    += idle_s
            v["km"]        += distance
            v["trips"].append({
                "start":     dt_start,
                "end":       dt_end_t,
                "km":        distance,
                "duration_s":duration_s,
                "idle_s":    idle_s,
                "max_speed": max_speed,
            })

        self._vt_log(
            "GPS: aggregated " + str(len(vehicles)) + " vehicles.",
            "ok")

        return {
            "vehicles": vehicles,
            "df":       df_dt,
            "dt":       dt_dt,
        }

    # ─────────────────────────────────────────────────────────────────────
    # 3. MERGE — combine GPS data with plate_agg, compute discrepancy
    # ─────────────────────────────────────────────────────────────────────
    def gps_merge_into_plate_agg(self, plate_agg, gps_data,
                                  time_tol_min=DEFAULT_TIME_TOLERANCE_MIN,
                                  km_tol_pct=DEFAULT_KM_TOLERANCE_PCT):
        """
        Mutates plate_agg in place to add GPS fields per plate.

        Adds:
          v["gps_working_s"]  — engine-on seconds from GPS
          v["gps_idle_s"]     — idle seconds from GPS
          v["gps_km"]         — GPS-measured km
          v["gps_trips"]      — per-trip GPS records (for drilldown)
          v["discrepancy_s"]  — Zeeta working_s minus GPS working_s
          v["discrepancy_km"] — Zeeta total_km minus GPS km
          v["mismatch"]       — bool: outside tolerance
          v["ghost"]          — bool: GPS activity but no Zeeta trips

        Plates with GPS activity but no Zeeta trips are added as
        "ghost" rows.
        """
        # Always seed defaults so _vt_populate doesn't crash
        for plate, agg in plate_agg.items():
            agg.setdefault("gps_working_s",  0)
            agg.setdefault("gps_idle_s",     0)
            agg.setdefault("gps_km",         0.0)
            agg.setdefault("gps_trips",      [])
            agg.setdefault("discrepancy_s",  0)
            agg.setdefault("discrepancy_km", 0.0)
            agg.setdefault("mismatch",       False)
            agg.setdefault("ghost",          False)

        if not gps_data:
            return plate_agg

        gps_v = gps_data.get("vehicles", {})
        norm_to_existing = {
            _gps_normalize_plate(p): p for p in plate_agg.keys()}

        # 1) Annotate existing plates
        n_mismatch = 0
        for plate, agg in plate_agg.items():
            pn = _gps_normalize_plate(plate)
            g = gps_v.get(pn)
            if not g:
                continue
            agg["gps_working_s"] = g["working_s"]
            agg["gps_idle_s"]    = g["idle_s"]
            agg["gps_km"]        = g["km"]
            agg["gps_trips"]     = g["trips"]

            zeeta_work_s = agg.get("work_s", 0)
            zeeta_km     = agg.get("total_km", 0) or 0
            agg["discrepancy_s"]  = zeeta_work_s - g["working_s"]
            agg["discrepancy_km"] = zeeta_km - g["km"]

            # Mismatch flag — only meaningful if both sides have data
            time_off = abs(agg["discrepancy_s"]) > (time_tol_min * 60)
            if zeeta_km > 0 and g["km"] > 0:
                km_pct_off = abs(agg["discrepancy_km"]) / zeeta_km * 100
                km_off = km_pct_off > km_tol_pct
            else:
                km_off = False
            if (zeeta_work_s > 0 or g["working_s"] > 0) and \
               (time_off or km_off):
                agg["mismatch"] = True
                n_mismatch += 1

        # 2) Add ghost rows: GPS activity, no Zeeta trips
        added = 0
        for pn, g in gps_v.items():
            if pn in norm_to_existing:
                continue
            if g["working_s"] <= 0 and g["km"] <= 0:
                continue
            plate_label = g.get("plate_raw") or pn
            plate_agg[plate_label] = {
                "trips":             [],
                "v_type":            self._vt_plate_types.get(
                                         plate_label, "—"),
                "n_closed":          0,
                "n_open":            0,
                "n_nodata":          0,
                "work_s":            0,
                "idle_s":            0,
                "idle_segs":         [],
                "util":              0,
                "dispatch_util":     0,
                "cal_util":          0,
                "total_amt":         0.0,
                "total_km":          0.0,
                # Fuel module fields (defaults if fuel module loaded too)
                "fuel_refill_count": 0,
                "fuel_month_litres": 0.0,
                "fuel_month_sar":    0.0,
                "fuel_only":         False,
                # GPS fields
                "gps_working_s":  g["working_s"],
                "gps_idle_s":     g["idle_s"],
                "gps_km":         g["km"],
                "gps_trips":      g["trips"],
                "discrepancy_s":  -g["working_s"],
                "discrepancy_km": -g["km"],
                "mismatch":       True,
                "ghost":          True,
            }
            added += 1

        if n_mismatch:
            self._vt_log(
                "GPS: " + str(n_mismatch) +
                " vehicle(s) flagged as MISMATCH (Zeeta vs GPS).",
                "warn")
        if added:
            self._vt_log(
                "GPS: " + str(added) +
                " vehicle(s) had GPS activity but no Zeeta trips — "
                "added as [GHOST ACTIVITY] rows.", "warn")

        return plate_agg

    # ─────────────────────────────────────────────────────────────────────
    # 4. DRILLDOWN — render per-trip cross-check inside an existing popup
    # ─────────────────────────────────────────────────────────────────────
    def gps_render_drilldown_section(self, parent_frame, plate_data, C):
        """
        Render a per-trip Zeeta vs GPS cross-check section inside the
        drilldown popup. Call this from your existing _vt_drilldown
        method, passing in the popup's parent frame.
        """
        gps_trips = plate_data.get("gps_trips", []) or []

        wrap = tk.Frame(parent_frame, bg=C["white"])
        wrap.pack(fill="both", expand=True, padx=14, pady=(8, 8))

        tk.Label(wrap, text="GPS Cross-Check (Arabitra)",
                 font=("Segoe UI", 10, "bold"),
                 bg=C["white"], fg=C["text"]).pack(
            anchor="w", padx=2, pady=(4, 4))

        if not gps_trips:
            tk.Label(wrap,
                     text="No GPS data available for this vehicle "
                          "in this date range.",
                     font=("Segoe UI", 9, "italic"),
                     bg=C["white"], fg=C["text3"]).pack(
                anchor="w", padx=2, pady=4)
            return

        # Summary line
        gws = plate_data.get("gps_working_s", 0)
        gis = plate_data.get("gps_idle_s", 0)
        gkm = plate_data.get("gps_km", 0)
        zws = plate_data.get("work_s", 0)
        zkm = plate_data.get("total_km", 0)
        disc_s  = plate_data.get("discrepancy_s", 0)
        disc_km = plate_data.get("discrepancy_km", 0)

        summary_lines = [
            "Zeeta working : " + _gps_fmt_duration(zws) +
            "    GPS working : " + _gps_fmt_duration(gws) +
            "    Diff : " + (("+" if disc_s >= 0 else "") +
                              _gps_fmt_duration(abs(disc_s))) +
            (" ⚠" if abs(disc_s) > DEFAULT_TIME_TOLERANCE_MIN * 60
             else ""),
            "Zeeta KM      : {:,.0f}".format(zkm) +
            "       GPS KM      : {:,.0f}".format(gkm) +
            "       Diff : " +
            (("+" if disc_km >= 0 else "") +
             "{:,.0f}".format(abs(disc_km))),
            "GPS idle in range : " + _gps_fmt_duration(gis),
        ]
        for line in summary_lines:
            tk.Label(wrap, text=line,
                     font=("Consolas", 9),
                     bg=C["white"], fg=C["text2"]).pack(
                anchor="w", padx=2)

        # Trip table
        tk.Label(wrap, text="Per-trip detail",
                 font=("Segoe UI", 9, "bold"),
                 bg=C["white"], fg=C["text2"]).pack(
            anchor="w", padx=2, pady=(8, 2))

        cols = ("start", "end", "km", "duration", "idle", "max_speed")
        labels = [
            ("start",     "Start",          150),
            ("end",       "End",            150),
            ("km",        "KM",              80),
            ("duration",  "Engine-on time",  120),
            ("idle",      "Idle",            100),
            ("max_speed", "Max speed",       100),
        ]
        outer = tk.Frame(wrap, bg=C["border"], padx=1, pady=1)
        outer.pack(fill="both", expand=True, pady=(2, 0))

        tree = ttk.Treeview(outer, columns=cols,
                             show="headings", height=8)
        for cid, txt, w in labels:
            tree.heading(cid, text=txt)
            tree.column(cid, width=w, anchor="center")

        def _fmt_dt(d):
            if not d:
                return "—"
            return d.strftime("%Y-%m-%d %H:%M")

        for t in sorted(gps_trips,
                         key=lambda x: x.get("start") or
                                       datetime.min):
            tree.insert("", "end", values=(
                _fmt_dt(t.get("start")),
                _fmt_dt(t.get("end")),
                "{:,.1f}".format(t.get("km", 0) or 0),
                _gps_fmt_duration(t.get("duration_s", 0)),
                _gps_fmt_duration(t.get("idle_s", 0)),
                "{:,.0f}".format(t.get("max_speed", 0) or 0)
                + " km/h",
            ))

        vsb = ttk.Scrollbar(outer, orient="vertical",
                             command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)


# ─────────────────────────────────────────────────────────────────────────
# Standalone formatters for the new tree columns
# ─────────────────────────────────────────────────────────────────────────
def gps_format_working(secs):
    if not secs:
        return "—"
    return _gps_fmt_duration(secs)


def gps_format_discrepancy(disc_s):
    """E.g. +1h 23m / -45m / —"""
    if disc_s == 0 or disc_s is None:
        return "—"
    sign = "+" if disc_s > 0 else "-"
    return sign + _gps_fmt_duration(abs(disc_s))

HAS_FUEL_MODULE = True
HAS_GPS_MODULE  = True

# ── HR MODE ──────────────────────────────────────────────────────────
# When True, only Audit Log + Settings + Debug Console are shown in the
# sidebar; all other modules (Purchase Orders, POS, Vehicle Tracker,
# Sales, etc.) are hidden. Uses a separate config file so HR's
# credentials are isolated from the operational bot.
HR_MODE = (
    "--hr" in sys.argv
    or os.environ.get("HR_MODE") == "1"
)

BASE_DIR    = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
CONFIG_FILE = BASE_DIR / ("hr_config.json" if HR_MODE else "config.json")
TEMP_DIR    = BASE_DIR / "temp_pdfs"
TEMP_DIR.mkdir(exist_ok=True)
MAPPING_FILE = BASE_DIR / "product_mapping.json"
QUEUE_FILE   = BASE_DIR / "pending_review.json"
SALES_TRACKER_FILE  = BASE_DIR / "sales_tracker.json"
_TD_MAPPING_FILE    = BASE_DIR / "td_name_mapping.json"
ZEETA_SALES_URL     = "https://c.zeetacargo.com/backend/reports/sales-report"

def load_td_mapping():
    """Return dict: TD display name -> Odoo login email."""
    try:
        if _TD_MAPPING_FILE.exists():
            with open(_TD_MAPPING_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_td_mapping(mapping):
    with open(_TD_MAPPING_FILE, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)


# ── Sales reminder tracker (passive log) ──────────────────────────────────────
# Records who was first reminded about which (coordinator|client|service) tuple.
# Auto-loaded on startup, auto-saved after every successful send.
# Purely a recording mechanism — does NOT change send behavior. The data file
# (sales_tracker.json) can be consumed externally (Excel, scripts, etc.) to
# build follow-up workflows.
def _sales_tracker_key(coord, client, service):
    """Build the canonical key: 'Coordinator|Client|Service'."""
    return (str(coord or "").strip()
            + "|" + str(client or "").strip()
            + "|" + str(service or "").strip())


def _sales_tracker_load():
    """Read sales_tracker.json. Returns {} if missing or unreadable."""
    try:
        if not SALES_TRACKER_FILE.exists():
            return {}
        with open(SALES_TRACKER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def _sales_tracker_save(data):
    """Write tracker dict to sales_tracker.json. Silent on error."""
    try:
        with open(SALES_TRACKER_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def _sales_tracker_record(coord, client, service, today_iso=None):
    """Record a successful reminder send. Updates last_reminded always,
    first_reminded only if missing. Returns True if file was written.

    today_iso: optional "YYYY-MM-DD" string. Defaults to today.
    """
    from datetime import date as _D
    if not today_iso:
        today_iso = _D.today().strftime("%Y-%m-%d")
    key = _sales_tracker_key(coord, client, service)
    data = _sales_tracker_load()
    rec = data.get(key) or {}
    rec["coordinator"] = str(coord or "").strip()
    rec["client"]      = str(client or "").strip()
    rec["service"]     = str(service or "").strip()
    if not rec.get("first_reminded"):
        rec["first_reminded"] = today_iso
    rec["last_reminded"] = today_iso
    data[key] = rec
    return _sales_tracker_save(data)


# ── Sales tracker helpers ─────────────────────────────────────────────────────
import random as _random, string as _string, collections as _collections

def sales_get_saudi_holidays(year):
    h = set()
    h.add(__import__("datetime").date(year, 9, 23))
    h.add(__import__("datetime").date(year, 2, 22))
    for base, count in [
        (date(2026,3,30),3),(date(2026,6,6),3),
        (date(2027,3,20),3),(date(2027,5,27),3),
        (date(2028,3, 9),3),(date(2028,5,15),3),
    ]:
        for i in range(count): h.add(base + timedelta(days=i))
    return h

def sales_is_working_day(d):
    if d.weekday() == 4: return False          # Friday off in KSA
    return d not in sales_get_saudi_holidays(d.year)

def sales_parse_num(t):
    try: return float(t.replace(",","").strip() or "0")
    except: return 0.0

# ── Sales Reminder message templates ──────────────────────────────────────────
# Each template: name -> {"subject": str, "body": str}.
# Body uses placeholders: {name}, {date}, {subject}, {client_list}, {note}
# All 3 defaults have the ASHWheelz Sales Management footer REMOVED per request.
DEFAULT_SALES_TEMPLATES = {
    "English — Standard": {
        "subject": "Sales Follow-Up Required",
        "body": (
            "{subject} — {date}\n"
            "\n"
            "Hi {name},\n"
            "\n"
            "Below are your clients below sales forecast, "
            "sorted by priority:\n"
            "\n"
            "{client_list}\n"
            "{note}\n"
            "\n"
            "— {name}"
        ),
    },
    "English — Urgent": {
        "subject": "URGENT — IMMEDIATE ACTION REQUIRED",
        "body": (
            "{subject}\n"
            "Date: {date}\n"
            "\n"
            "{name},\n"
            "\n"
            "The following clients are critically behind forecast. "
            "This requires your immediate attention before end of day.\n"
            "\n"
            "{client_list}\n"
            "{note}\n"
            "\n"
            "Please revert with your action plan within the next 2 hours.\n"
            "\n"
            "— {name}"
        ),
    },
    "English — Friendly": {
        "subject": "Gentle reminder — clients needing attention",
        "body": (
            "{subject}\n"
            "{date}\n"
            "\n"
            "Hi {name},\n"
            "\n"
            "Hope your day is going well. Just a quick nudge — these "
            "clients could use some follow-up today:\n"
            "\n"
            "{client_list}\n"
            "{note}\n"
            "\n"
            "Let me know if you need any support.\n"
            "\n"
            "— {name}"
        ),
    },
}


def sales_render_template(template, name, date_str, client_list, note):
    """
    Render a template dict ({"subject","body"}) into a message string.
    On any error, returns None so caller can fall back to hardcoded format.
    """
    try:
        subj = (template or {}).get("subject", "") or ""
        body = (template or {}).get("body", "") or ""
        if not body:
            return None
        return body.format(
            name=name or "",
            date=date_str or "",
            subject=subj,
            client_list=client_list or "",
            note=note or "",
        )
    except Exception:
        return None


def sales_build_msg(name, clients, reminder_map,
                    custom_note="", template=None):
    """
    Build coordinator reminder message.
    Clients sorted: zero-actual first, then descending % behind.

    If `template` is a dict {"subject", "body"}, use it.
    Otherwise fall back to the hardcoded legacy format (backward compatible).
    """
    today_full = date.today().strftime("%B %d, %Y")

    # Sort: zero actual first (100% gap), then descending pct
    sorted_clients = sorted(
        clients,
        key=lambda c: (0 if c["actual"] == 0 else 1, -c["pct"])
    )

    # Build the client_list block used in all templates
    client_lines = []
    for c in sorted_clients:
        rnum = reminder_map[c["key"]]
        r_tag = "" if rnum == 1 else "  [FOLLOW-UP]" if rnum == 2 else "  [URGENT]"
        zero_tag = "  *** ZERO SALES ***" if c["actual"] == 0 else ""
        client_lines += [
            "* " + c["client"] + " — " + c["service"] + " Service" +
            zero_tag + r_tag,
            "  Forecast : " + format(int(c["suppose"]), ",") + " SAR",
            "  Actual   : " + format(int(c["actual"]),  ",") + " SAR",
            "  Gap      : " + format(int(c["gap"]),     ",") +
            " SAR  (" + str(c["pct"]) + "% behind)",
            "",
        ]
    client_list_str = "\n".join(client_lines).rstrip()

    note = (custom_note.strip() if custom_note and custom_note.strip()
            else "Please take immediate action and update me by end of day.")

    # Try template first
    if template:
        rendered = sales_render_template(
            template, name, today_full, client_list_str, note)
        if rendered:
            return rendered

    # Fallback: legacy hardcoded format (used if no template or render fails)
    max_r = max(reminder_map[c["key"]] for c in clients) if clients else 1
    if max_r == 1:
        subject = "Sales Follow-Up Required"
    elif max_r == 2:
        subject = "FOLLOW-UP REMINDER"
    else:
        subject = "URGENT — FINAL ESCALATION"

    lines = [
        subject + " — " + today_full,
        "",
        "Hi " + name + ",",
        "",
        "Below are your clients below sales forecast, sorted by priority:",
        "",
        client_list_str,
        "",
        note,
        "",
        "— " + name,
    ]
    return "\n".join(lines)

DEFAULT_CONFIG = {
    "odoo_host":        "",
    "odoo_db":          "",
    "odoo_user":        "",
    "odoo_pass":        "",
    "green_instance":   "",
    "green_token":      "",
    "schedule_hour":    "5",
    "schedule_minute":  "0",
    "auto_run_today":   True,
    "company_id":       0,
    "company_name":     "All Companies",
    "watch_interval":   5,
    "last_po_sent":     [],
    "custom_note":      "Please confirm receipt of this order.",
    "audit_custom_note":"Please review your activity log for today.",
    # Audit Log message templates
    "audit_templates":         None,
    "audit_template_selected": "Standard",
    # Zeeta ERP Sales & Activities login (password base64-encoded)
    "zeeta_cargo_user":     "",
    "zeeta_cargo_pass_b64": "",
    # Sales Reminder message templates (user-editable via dropdown + dialog)
    "sales_templates":         None,   # None = falls back to DEFAULT_SALES_TEMPLATES
    "sales_template_selected": "English — Standard",
    # POS Sync module — QuickBill scraper
    "pos_api_url":          "https://quickbill.mealwheelz.com",
    "pos_api_key":          "",
    "quickbill_email":      "",
    "quickbill_password":   "",
    "quickbill_branch":     "all",      # "all" or a restaurant _id from QuickBill
    "quickbill_branch_name": "All Branches",
    "anthropic_key":        "",
    "sim_auto_threshold":   85,
    "sim_reject_threshold": 40,
    "use_claude_matching":  True,
    "notify_on_review":     True,
    "notify_phone":         "",
}

C = {
    "page":     "#f4f6fa",
    "white":    "#ffffff",
    "sidebar":  "#ffffff",
    "topbar":   "#ffffff",
    "border":   "#e8ecf4",
    "border2":  "#c5d8ff",
    "input":    "#f7f9fc",
    "input2":   "#f0f5ff",
    "accent":   "#2563eb",
    "accent_l": "#e8f0ff",
    "text":     "#1a2540",
    "text2":    "#374060",
    "text3":    "#6b7a99",
    "text4":    "#9aa5be",
    "text5":    "#c4cad8",
    "green":    "#15803d",
    "green_l":  "#dcfce7",
    "amber":    "#92400e",
    "amber_l":  "#fef3c7",
    "red":      "#b91c1c",
    "red_l":    "#fee2e2",
    "cyan":     "#0369a1",
    "cyan_l":   "#e0f2fe",
    "wa":       "#15803d",
    "wa_l":     "#dcfce7",
    "log_bg":   "#ffffff",
    "log_ts":   "#c4cad8",
}

# ── TimeDoctor office-hour rules (PKT, all times PKT-local) ───────────────────
# Idle DURING office hours is real idle (deduct lunch). Idle OUTSIDE office hours
# is voluntary/extra working time and should NOT be counted as idle. This is
# central to fair productivity measurement for the Pakistan team.
_TD_OFFICE_START_H  = 10    # 10:00 PKT
_TD_OFFICE_START_M  = 0
_TD_OFFICE_END_H    = 18    # 18:00 PKT
_TD_OFFICE_END_M    = 0
_TD_LUNCH_START_H   = 14
_TD_LUNCH_START_M   = 30    # 14:30 PKT
_TD_LUNCH_END_H     = 15
_TD_LUNCH_END_M     = 30    # 15:30 PKT
# Working days: weekday() index — Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
# Sat–Thu means Friday (4) is OFF.
_TD_OFF_DAYS = {4}


def _td_overlap_seconds(seg_start, seg_end, win_start, win_end):
    """Seconds of overlap between [seg_start, seg_end] and [win_start, win_end]."""
    s = seg_start if seg_start > win_start else win_start
    e = seg_end if seg_end < win_end else win_end
    if e <= s:
        return 0
    return int((e - s).total_seconds())


def _td_office_window(sel_date_obj):
    """Return (office_start_dt, office_end_dt, lunch_start_dt, lunch_end_dt)
    for the given date. If selected day is OFF (Fri), all windows are zero-width
    so all activity counts as extra and no idle is counted.

    sel_date_obj: a datetime.date (or datetime, will be normalized to date).
    """
    from datetime import datetime as _dt2, date as _d2
    if isinstance(sel_date_obj, _dt2):
        d = sel_date_obj.date()
    else:
        d = sel_date_obj
    if d.weekday() in _TD_OFF_DAYS:
        # Zero-width window — no office hours on this day
        z = _dt2.combine(d, _dt2.min.time())
        return z, z, z, z
    os_dt = _dt2(d.year, d.month, d.day,
                 _TD_OFFICE_START_H, _TD_OFFICE_START_M)
    oe_dt = _dt2(d.year, d.month, d.day,
                 _TD_OFFICE_END_H, _TD_OFFICE_END_M)
    ls_dt = _dt2(d.year, d.month, d.day,
                 _TD_LUNCH_START_H, _TD_LUNCH_START_M)
    le_dt = _dt2(d.year, d.month, d.day,
                 _TD_LUNCH_END_H, _TD_LUNCH_END_M)
    return os_dt, oe_dt, ls_dt, le_dt


# ── TimeDoctor non-productive blocklist (case-insensitive substring match) ────
# Matched against event['title'] and event['value'].
# LinkedIn is EXCLUDED (treated as productive for sales coordinators).
_TD_BLOCKLIST = (
    # Entertainment / streaming
    "netflix", "youtube", "hulu", "primevideo", "disneyplus",
    "spotify", "twitch", "soundcloud",
    # Social (LinkedIn deliberately excluded)
    "facebook", "instagram", "twitter.com", "x.com", "tiktok",
    "reddit", "snapchat", "pinterest",
    # Piracy / free streaming
    "1337x", "123movies", "1flix", "thepiratebay", "rarbg",
    "torrent", "putlocker", "9anime", "fmovies", "soap2day",
    "yesmovies", "movies4u",
    # Games
    "steam", "epicgames", "roblox", "valorant", "minecraft",
    "league of legends", "fortnite",
    # News / distraction
    "cnn.com", "bbc.com", "dawn.com", "geo.tv",
    "bleacherreport", "espn.com",
    # Adult
    "pornhub", "xvideos", "xhamster",
)

# ── TimeDoctor productive-activity groups (first match wins) ──────────────────
# Ordered specific → generic. Each tuple: (group_name, display_color, keywords).
# Applied ONLY to events that passed the blocklist filter above.
_TD_GROUPS = (
    ("ERP", "#2563eb", (
        "odoo", "zeetacargo", "ashwheelz", "quickbill",
        "c.zeeta", "zeeta erp", "xmlrpc",
    )),
    ("Communication", "#0369a1", (
        "outlook", "gmail", "whatsapp", "teams", "slack",
        "zoom", "skype", "webex", "telegram",
        "mail.google", "messenger",
    )),
    ("Code / Dev", "#7c3aed", (
        "visual studio code", "vscode", "code.exe",
        "github", "gitlab", "bitbucket",
        "terminal", "powershell", "cmd.exe",
        "pycharm", "intellij", "sublime", "notepad++",
    )),
    ("Documents", "#15803d", (
        "excel", "word", "powerpoint", "onedrive", "sharepoint",
        "pdf", "acrobat", "adobe reader", "foxit",
        "docs.google", "sheets.google", "slides.google",
        "drive.google",
    )),
    ("Web — work related", "#92400e", (
        "linkedin", "wikipedia", "stackoverflow", "stack exchange",
        "chatgpt", "claude.ai", "anthropic", "gemini.google",
        "perplexity", "google.com/search", "bing.com/search",
        "duckduckgo", "chatbot",
    )),
    ("Browser", "#c4cad8", (
        "google chrome", "mozilla firefox", "microsoft edge",
        "opera", "brave",
    )),
    # "Other" is the implicit fallback bucket — no keywords, catches the rest.
)

def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

def odoo_auth(cfg):
    host = cfg["odoo_host"].strip().rstrip("/")
    if not host:
        raise Exception("Odoo URL not configured — open Settings and fill in Host, Database, Username, Password, then click Save.")
    if not host.startswith("http"):
        host = "https://" + host
    common = xmlrpc.client.ServerProxy(host + "/xmlrpc/2/common")
    uid = common.authenticate(cfg["odoo_db"], cfg["odoo_user"], cfg["odoo_pass"], {})
    if not uid:
        raise Exception("Odoo auth failed -- check credentials.")
    models = xmlrpc.client.ServerProxy(host + "/xmlrpc/2/object")
    return uid, models, host

def fetch_companies(cfg):
    uid, models, host = odoo_auth(cfg)
    cos = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
        "res.company", "search_read", [[]], {"fields": ["id","name"], "order": "name asc"})
    return uid, models, host, cos

def fetch_pos_for_date(cfg, target_date, log):
    uid, models, host = odoo_auth(cfg)
    log("Authenticated (UID " + str(uid) + ")", "ok")
    ds = target_date.strftime("%Y-%m-%d")
    ns = (target_date + timedelta(days=1)).strftime("%Y-%m-%d")
    domain = [
        ["state", "in", ["purchase", "done"]],
        ["date_order", ">=", ds + " 00:00:00"],
        ["date_order", "<",  ns + " 00:00:00"],
    ]
    cid = cfg.get("company_id", 0)
    if cid:
        domain.append(["company_id", "=", cid])
        log("Company: " + cfg.get("company_name", str(cid)), "info")
    else:
        log("Company: All", "info")
    orders = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
        "purchase.order", "search_read", [domain],
        {"fields": ["name","partner_id","amount_total","currency_id",
                    "date_approve","date_order","state","partner_ref",
                    "date_planned","order_line"], "limit": 500})
    log("Found " + str(len(orders)) + " PO(s) for " + ds, "ok")
    all_line_ids = []
    for o in orders:
        all_line_ids += o.get("order_line", [])
    lines_data = {}
    if all_line_ids:
        lines_en = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
            "purchase.order.line", "search_read",
            [[["id","in",all_line_ids]]],
            {"fields": ["id","order_id","product_id","name","product_qty","product_uom"]})
        try:
            lines_ur = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
                "purchase.order.line", "search_read",
                [[["id","in",all_line_ids]]],
                {"fields": ["id","product_id"], "context": {"lang": "ur_PK"}})
            ur_names = {lu["id"]: (lu["product_id"][1] if lu.get("product_id") and lu["product_id"] else "") for lu in lines_ur}
        except:
            ur_names = {}
        for l in lines_en:
            l["_product_ur"] = ur_names.get(l["id"], "")
            oid = l["order_id"][0]
            if oid not in lines_data:
                lines_data[oid] = []
            lines_data[oid].append(l)
    for o in orders:
        o["_lines"] = lines_data.get(o["id"], [])
    return orders, uid, models, host

def get_vendor_phone(cfg, uid, models, partner_id):
    ps = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
        "res.partner", "search_read", [[["id","=",partner_id]]],
        {"fields": ["name","phone","mobile"], "limit": 1})
    if not ps:
        return None, None
    p = ps[0]
    phone = p.get("mobile") or p.get("phone") or ""
    return p.get("name","Unknown"), phone.strip()

def download_po_pdf(cfg, host, po_id, po_name, log):
    try:
        session = requests.Session()
        auth_resp = session.post(host + "/web/session/authenticate", json={
            "jsonrpc":"2.0","method":"call","id":1,
            "params":{"db":cfg["odoo_db"],"login":cfg["odoo_user"],"password":cfg["odoo_pass"]}
        }, timeout=30)
        if not auth_resp.json().get("result", {}).get("uid"):
            raise Exception("Session login failed")
        try:
            uid2, models2, _ = odoo_auth(cfg)
            atts = models2.execute_kw(cfg["odoo_db"], uid2, cfg["odoo_pass"],
                "ir.attachment", "search_read",
                [[["res_model","=","purchase.order"],["res_id","=",po_id],
                  ["mimetype","in",["application/pdf","application/octet-stream"]]]],
                {"fields": ["id","name","datas"], "order": "id desc", "limit": 5})
            for att in atts:
                if att.get("datas"):
                    raw = base64.b64decode(att["datas"])
                    if len(raw) > 500:
                        safe = po_name.replace("/","-").replace("\\","-")
                        path = TEMP_DIR / (safe + ".pdf")
                        path.write_bytes(raw)
                        log("PDF: " + path.name + " (" + str(len(raw)//1024) + "KB)", "ok")
                        return str(path)
        except:
            pass
        pr = session.get(host + "/report/pdf/purchase.report_purchaseorder/" + str(po_id), timeout=60)
        if pr.status_code == 200 and len(pr.content) > 500:
            safe = po_name.replace("/","-").replace("\\","-")
            path = TEMP_DIR / (safe + ".pdf")
            path.write_bytes(pr.content)
            log("PDF: " + path.name + " (" + str(len(pr.content)//1024) + "KB)", "ok")
            return str(path)
        raise Exception("HTTP " + str(pr.status_code))
    except Exception as e:
        log("PDF failed: " + str(e), "warn")
        return None

def format_po_message(po, vendor_name, target_date, custom_note=""):
    ds  = target_date.strftime("%d %B %Y")
    ref = po.get("partner_ref") or "-"
    pln = (po.get("date_planned") or "-")[:10]
    lines = po.get("_lines", [])
    msg  = "Purchase Order Notification\n\n"
    msg += "Dear " + vendor_name + ",\n\n"
    msg += "PO Number:     " + po["name"] + "\n"
    msg += "Date:          " + ds + "\n"
    msg += "Your Ref:      " + ref + "\n"
    msg += "Delivery Date: " + pln + "\n"
    msg += "Status:        Confirmed\n\n"
    if lines:
        msg += "Order Details:\n" + "-" * 30 + "\n"
        for i, line in enumerate(lines, 1):
            pid_val = line.get("product_id")
            en = pid_val[1] if pid_val and isinstance(pid_val, (list,tuple)) else "Unknown Product"
            if len(en) > 40: en = en[:40] + "..."
            ur = line.get("_product_ur","")
            qty = line.get("product_qty", 0)
            uom = line.get("product_uom",[None,""])[1] if line.get("product_uom") else ""
            msg += str(i) + ". " + en
            if ur and ur != en: msg += " / " + ur
            msg += "\n   Qty: " + "{:,.2f}".format(qty) + " " + uom + "\n"
        msg += "-" * 30 + "\n"
    if custom_note and custom_note.strip():
        msg += "\n" + custom_note.strip()
    return msg

def test_green_api(cfg):
    inst  = cfg["green_instance"].strip()
    token = cfg["green_token"].strip()
    r = requests.get("https://api.green-api.com/waInstance" + inst + "/getStateInstance/" + token, timeout=15)
    return r.json().get("stateInstance","unknown")

def send_whatsapp_green(cfg, phone, message, pdf_path, log):
    inst  = cfg["green_instance"].strip()
    token = cfg["green_token"].strip()
    if not inst or not token:
        raise Exception("Green API not configured")
    base  = "https://api.green-api.com/waInstance" + inst
    phone = phone.replace(" ","").replace("-","").replace("(","").replace(")","").replace("+","")
    if phone.startswith("00"): phone = phone[2:]
    chat_id = phone + "@c.us"
    r = requests.post(base + "/sendMessage/" + token,
        json={"chatId": chat_id, "message": message}, timeout=30)
    if r.status_code != 200:
        raise Exception("Send failed HTTP " + str(r.status_code))
    log("Sent to +" + phone, "ok")
    if pdf_path and os.path.exists(pdf_path):
        with open(pdf_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        r2 = requests.post(base + "/sendFileByUpload/" + token,
            json={"chatId": chat_id, "file": b64,
                  "fileName": os.path.basename(pdf_path), "caption": "Purchase Order PDF"}, timeout=60)
        if r2.status_code == 200:
            log("PDF sent", "ok")

def run_job(cfg, target_date, log):
    log("=" * 44, "info")
    log("Job: " + target_date.strftime("%d %B %Y"), "info")
    log("=" * 44, "info")
    try:
        orders, uid, models, host = fetch_pos_for_date(cfg, target_date, log)
        if not orders:
            log("No POs found.", "warn"); return
        ok = skip = fail = 0
        for po in orders:
            name = po["name"]
            pid  = po["partner_id"][0] if po.get("partner_id") and isinstance(po["partner_id"], (list,tuple)) else None
            log("-- " + name + " --", "info")
            if not pid:
                log("No vendor -- skipping", "warn"); skip += 1; continue
            vname, phone = get_vendor_phone(cfg, uid, models, pid)
            if not phone:
                log("No phone for " + str(vname) + " -- skipping", "warn"); skip += 1; continue
            log(str(vname) + " | +" + phone, "info")
            pdf = download_po_pdf(cfg, host, po["id"], name, log)
            msg = format_po_message(po, vname, target_date, cfg.get("custom_note",""))
            try:
                send_whatsapp_green(cfg, phone, msg, pdf, log)
                ok += 1
            except Exception as e:
                log("ERROR: " + str(e), "err"); fail += 1
            if pdf and os.path.exists(pdf): os.remove(pdf)
            time.sleep(2)
        log("Done  Sent:" + str(ok) + "  Skip:" + str(skip) + "  Fail:" + str(fail), "ok")
    except Exception as e:
        log("ERROR: " + str(e), "err")

def get_recent_confirmed_pos(cfg, log):
    uid, models, host = odoo_auth(cfg)
    minutes = int(cfg.get("watch_interval", 5)) * 2
    since = (datetime.utcnow() - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
    domain = [["state","in",["purchase","done"]],["date_order",">=",since]]
    cid = cfg.get("company_id", 0)
    if cid: domain.append(["company_id","=",cid])
    orders = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
        "purchase.order", "search_read", [domain],
        {"fields": ["name","partner_id","amount_total","currency_id",
                    "date_order","state","partner_ref","date_planned","order_line"], "limit": 200})
    sent = cfg.get("last_po_sent", [])
    return [o for o in orders if o["name"] not in sent], uid, models, host

def run_watch_job(cfg, log):
    try:
        new_orders, uid, models, host = get_recent_confirmed_pos(cfg, log)
        if not new_orders: return
        sent = list(cfg.get("last_po_sent",[]))
        ok = fail = skip = 0
        for po in new_orders:
            name = po["name"]
            pid  = po["partner_id"][0] if po.get("partner_id") and isinstance(po["partner_id"], (list,tuple)) else None
            log("Watch: " + name, "info")
            if not pid:
                sent.append(name); skip += 1; continue
            vname, phone = get_vendor_phone(cfg, uid, models, pid)
            if not phone:
                log("No phone -- skip", "warn"); sent.append(name); skip += 1; continue
            log(str(vname) + " | +" + phone, "info")
            pdf = download_po_pdf(cfg, host, po["id"], name, log)
            msg = format_po_message(po, vname, datetime.now().date(), cfg.get("custom_note",""))
            try:
                send_whatsapp_green(cfg, phone, msg, pdf, log); ok += 1
            except Exception as e:
                log("ERROR: " + str(e), "err"); fail += 1
            if pdf and os.path.exists(pdf): os.remove(pdf)
            sent.append(name)
            cfg["last_po_sent"] = sent[-500:]
            save_config(cfg)
            time.sleep(2)
        if ok or fail:
            log("Watch done  Sent:" + str(ok) + "  Fail:" + str(fail), "ok")
    except Exception as e:
        log("Watch ERROR: " + str(e), "err")

MODEL_LABELS = {
    "purchase.order":"Purchase Order","sale.order":"Sale Order",
    "stock.picking":"Inventory / Transfer","account.move":"Invoice / Journal Entry",
    "stock.inventory":"Stock Adjustment","mrp.production":"Manufacturing Order",
    "hr.attendance":"Attendance","res.partner":"Contact",
    "product.product":"Product","product.template":"Product Template",
}

def fetch_audit_logs(cfg, target_date, log):
    """Fetch activity from mail.message across all business modules."""
    uid, models, host = odoo_auth(cfg)
    log("Audit: Authenticated (UID " + str(uid) + ")", "ok")
    ds = target_date.strftime("%Y-%m-%d")
    ns = (target_date + timedelta(days=1)).strftime("%Y-%m-%d")
    log("Fetching activity for " + ds + " (all companies)...", "info")

    BUSINESS_MODELS = [
        "purchase.order","account.move","account.payment",
        "sale.order","stock.picking","stock.inventory",
        "mrp.production","hr.employee","hr.payslip",
        "hr.payslip.run","hr.attendance","hr.leave",
        "res.partner","product.template","project.task",
    ]

    messages = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
        "mail.message", "search_read",
        [[["date",">=",ds+" 00:00:00"],
          ["date","<", ns+" 00:00:00"],
          ["author_id","!=",False],
          ["model","in",BUSINESS_MODELS]]],
        {"fields": ["id","author_id","model","res_id","record_name","date"],
         "limit": 5000})

    log("Found " + str(len(messages)) + " activity entries", "ok")

    # author_id is res.partner — map to res.users for proper identity
    author_partner_ids = list({m["author_id"][0] for m in messages
                                if m.get("author_id") and isinstance(m["author_id"],(list,tuple))})
    all_users = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
        "res.users","search_read",
        [[["partner_id","in",author_partner_ids]]],
        {"fields":["id","name","partner_id"]})
    partner_to_user = {u["partner_id"][0]: (u["id"], u["name"])
                       for u in all_users
                       if u.get("partner_id") and isinstance(u["partner_id"],(list,tuple))}

    by_user = {}
    for m in messages:
        author = m.get("author_id")
        if not author or not isinstance(author,(list,tuple)): continue
        partner_id = author[0]
        if partner_id in partner_to_user:
            uid_val, uname = partner_to_user[partner_id]
        else:
            uid_val = partner_id
            uname   = author[1]
        model = m.get("model","")
        label = MODEL_LABELS.get(model, model.replace("."," ").title() if model else "General")
        rec   = m.get("record_name") or ("ID " + str(m.get("res_id","")))
        if uid_val not in by_user:
            by_user[uid_val] = {"name": uname, "by_model": {}}
        bm = by_user[uid_val]["by_model"]
        if label not in bm:
            bm[label] = {"count": 0, "records": [], "seen": set()}
        grp = bm[label]
        grp["count"] += 1
        if rec and rec not in grp["seen"]:
            grp["seen"].add(rec)
            grp["records"].append(rec)

    if not by_user:
        log("No activity found for this date.", "warn")
        return [], uid, models, host

    # Get phone numbers via partner_id
    all_partner_ids = list({uid_val for uid_val in by_user
                            if uid_val not in [u[0] for u in partner_to_user.values()]})
    # Also get partners for all users
    user_ids = list(by_user.keys())
    res_users2 = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
        "res.users","search_read",[[["id","in",user_ids]]],
        {"fields":["id","partner_id"]})
    uid_to_pid = {u["id"]: u["partner_id"][0] for u in res_users2
                  if u.get("partner_id") and isinstance(u["partner_id"],(list,tuple))}
    # For users matched via partner_to_user, their partner is already known
    for partner_id, (uid_val, uname) in partner_to_user.items():
        if uid_val not in uid_to_pid:
            uid_to_pid[uid_val] = partner_id
    pids = list(set(uid_to_pid.values()))
    partners = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
        "res.partner","search_read",[[["id","in",pids]]],
        {"fields":["id","phone","mobile"]})
    phone_by_pid = {p["id"]:(p.get("mobile") or p.get("phone") or "") for p in partners}

    results = []
    for uid_val, data in by_user.items():
        pid   = uid_to_pid.get(uid_val)
        phone = phone_by_pid.get(pid,"").strip() if pid else ""
        total = sum(g["count"] for g in data["by_model"].values())
        results.append({
            "author_id":   uid_val,
            "author_name": data["name"],
            "phone":       phone,
            "by_model":    data["by_model"],
            "total":       total,
            "entries":     [],
        })
    results.sort(key=lambda x: -x["total"])
    log(str(len(results)) + " user(s) active on " + ds, "ok")
    return results, uid, models, host

# ── Audit Log message templates ───────────────────────────────────────────────
# User-editable via dropdown + Edit dialog on Audit Log page.
# Body uses placeholders: {name}, {date}, {total}, {model_breakdown}, {note}
DEFAULT_AUDIT_TEMPLATES = {
    "Standard": {
        "subject": "Activity Summary",
        "body": (
            "{subject}\n"
            "\n"
            "User:  {name}\n"
            "Date:  {date}\n"
            "Total: {total} entries\n"
            "------------------------------\n"
            "\n"
            "{model_breakdown}\n"
            "------------------------------\n"
            "{note}"
        ),
    },
    "Urgent": {
        "subject": "ACTIVITY REVIEW REQUIRED",
        "body": (
            "{subject}\n"
            "\n"
            "{name},\n"
            "Your activity for {date} is logged below ({total} entries).\n"
            "Please review immediately and confirm any discrepancies.\n"
            "\n"
            "{model_breakdown}\n"
            "{note}"
        ),
    },
    "Friendly": {
        "subject": "Your activity recap",
        "body": (
            "{subject} for {date}\n"
            "\n"
            "Hi {name},\n"
            "\n"
            "Here's a quick recap of your work today — {total} entries logged.\n"
            "\n"
            "{model_breakdown}\n"
            "{note}\n"
            "\n"
            "Thanks for the great work!"
        ),
    },
    "Custom": {
        "subject": "Custom subject here",
        "body": (
            "Hi {name},\n"
            "\n"
            "Your activity on {date}:\n"
            "{model_breakdown}\n"
            "\n"
            "{note}"
        ),
    },
}


def audit_render_template(template, name, date_str, total,
                            model_breakdown, note):
    """Render an audit template dict into a final message string.
    Returns None on any error so caller can fall back to legacy format."""
    try:
        subj = (template or {}).get("subject", "") or ""
        body = (template or {}).get("body", "") or ""
        if not body:
            return None
        return body.format(
            name=name or "",
            date=date_str or "",
            total=total if total is not None else "",
            subject=subj,
            model_breakdown=model_breakdown or "",
            note=note or "",
        )
    except Exception:
        return None


def format_audit_message(user_data, target_date, custom_note="",
                           template=None):
    ds    = target_date.strftime("%d %B %Y")
    name  = user_data["author_name"]
    total = user_data.get("total", 0)
    by_model = user_data.get("by_model", {})

    # Build the model_breakdown block (used in template) and legacy lines
    bd_lines = []
    for label, grp in by_model.items():
        count   = grp["count"]
        records = grp["records"]
        bd_lines.append(label + ":  " + str(count) + " entries")
        for rec in records:
            bd_lines.append("  # " + rec)
        bd_lines.append("")
    model_breakdown = "\n".join(bd_lines).rstrip()

    note = (custom_note.strip() if custom_note and custom_note.strip()
            else "")

    # Try template first
    if template:
        rendered = audit_render_template(
            template, name, ds, total, model_breakdown, note)
        if rendered:
            return rendered

    # Fallback: legacy hardcoded format (original behavior)
    lines = []
    lines.append("Activity Summary")
    lines.append("")
    lines.append("User:  " + name)
    lines.append("Date:  " + ds)
    lines.append("Total: " + str(total) + " entries")
    lines.append("-" * 30)
    lines.append("")
    lines.append(model_breakdown)
    lines.append("")
    lines.append("-" * 30)
    if note:
        lines.append(note)
    return "\n".join(lines)

def run_audit_job_filtered(cfg, target_date, log, selected_users=None):
    """Run audit job — if selected_users provided, only send to those users."""
    log("=" * 44, "info")
    log("Audit: " + target_date.strftime("%d %B %Y"), "info")
    log("=" * 44, "info")
    try:
        result = fetch_audit_logs(cfg, target_date, log)
        if not result or not result[0]:
            log("No activity found.", "warn"); return
        users_data, uid, models, host = result

        # Filter to selected users if provided
        if selected_users:
            selected_ids = {u["pid"] for u in selected_users}
            users_data = [u for u in users_data if u["author_id"] in selected_ids]
            log("Filtered to " + str(len(users_data)) + " selected user(s)", "info")

        if not users_data:
            log("None of the selected users had activity on this date.", "warn"); return

        # Resolve selected template from config
        _audit_tpls = cfg.get("audit_templates") or DEFAULT_AUDIT_TEMPLATES
        _sel_name = cfg.get("audit_template_selected", "Standard")
        _audit_tpl = _audit_tpls.get(_sel_name)
        if _audit_tpl:
            log("Using template: " + _sel_name, "info")

        ok = skip = fail = 0
        for user in users_data:
            name  = user["author_name"]
            phone = user["phone"]
            n_entries = user.get("total", 0) or 0
            log("-- " + name + " (" + str(n_entries) + " entries) --", "info")
            if n_entries <= 0:
                log("No Odoo entries on this date -- skipping", "warn")
                skip += 1; continue
            if not phone:
                log("No phone -- skipping", "warn"); skip += 1; continue
            msg = format_audit_message(user, target_date,
                                        cfg.get("audit_custom_note",""),
                                        template=_audit_tpl)
            _msg_len = len(msg or "")
            _msg_preview = (msg or "")[:140].replace("\n", " | ")
            log("Msg: " + str(_msg_len) + " chars · " + _msg_preview, "info")
            if _msg_len < 60:
                log("WARN: message suspiciously short — may be missing data",
                    "warn")
            try:
                send_whatsapp_green(cfg, phone, msg, None, log); ok += 1
            except Exception as e:
                log("ERROR: " + str(e), "err"); fail += 1
            time.sleep(2)
        log("Audit done  Sent:"+str(ok)+"  Skip:"+str(skip)+"  Fail:"+str(fail), "ok")
    except Exception as e:
        log("Audit ERROR: " + str(e), "err")


def run_audit_job(cfg, target_date, log):
    log("=" * 44, "info")
    log("Audit: " + target_date.strftime("%d %B %Y"), "info")
    log("=" * 44, "info")
    try:
        result = fetch_audit_logs(cfg, target_date, log)
        if not result or not result[0]:
            log("No activity found.", "warn"); return
        users_data, uid, models, host = result

        # Resolve selected template
        _audit_tpls = cfg.get("audit_templates") or DEFAULT_AUDIT_TEMPLATES
        _sel_name = cfg.get("audit_template_selected", "Standard")
        _audit_tpl = _audit_tpls.get(_sel_name)
        if _audit_tpl:
            log("Using template: " + _sel_name, "info")

        ok = skip = fail = 0
        for user in users_data:
            name = user["author_name"]; phone = user["phone"]
            n_entries = user.get("total", 0) or 0
            log("-- " + name + " (" + str(n_entries) + " entries) --", "info")
            if n_entries <= 0:
                log("No Odoo entries on this date -- skipping", "warn")
                skip += 1; continue
            if not phone:
                log("No phone -- skipping", "warn"); skip += 1; continue
            msg = format_audit_message(user, target_date,
                                        cfg.get("audit_custom_note",""),
                                        template=_audit_tpl)
            _msg_len = len(msg or "")
            _msg_preview = (msg or "")[:140].replace("\n", " | ")
            log("Msg: " + str(_msg_len) + " chars · " + _msg_preview, "info")
            if _msg_len < 60:
                log("WARN: message suspiciously short — may be missing data",
                    "warn")
            try:
                send_whatsapp_green(cfg, phone, msg, None, log); ok += 1
            except Exception as e:
                log("ERROR: " + str(e), "err"); fail += 1
            time.sleep(2)
        log("Audit done  Sent:"+str(ok)+"  Skip:"+str(skip)+"  Fail:"+str(fail), "ok")
    except Exception as e:
        log("Audit ERROR: " + str(e), "err")

# ══════════════════════════════════════════════════════════════════════════════
#  POS SYNC MODULE  —  backend helpers
# ══════════════════════════════════════════════════════════════════════════════

# ── Mapping DB ────────────────────────────────────────────────────────────────
def pos_load_mappings():
    if MAPPING_FILE.exists():
        with open(MAPPING_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}

def pos_save_mapping(pos_name, odoo_id, odoo_name):
    db = pos_load_mappings()
    db[pos_name.strip().lower()] = {
        "odoo_product_id":   odoo_id,
        "odoo_product_name": odoo_name,
        "confirmed_at":      datetime.now().isoformat()
    }
    with open(MAPPING_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

def pos_lookup_mapping(pos_name):
    return pos_load_mappings().get(pos_name.strip().lower())

def pos_load_queue():
    if QUEUE_FILE.exists():
        with open(QUEUE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []

def pos_save_queue(q):
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(q, f, indent=2, ensure_ascii=False)

def pos_add_to_queue(item):
    q = pos_load_queue()
    existing = [x["pos_name"].strip().lower() for x in q]
    if item["pos_name"].strip().lower() not in existing:
        q.append({**item, "queued_at": datetime.now().isoformat()})
        pos_save_queue(q)

def pos_remove_from_queue(pos_name):
    q = [x for x in pos_load_queue()
         if x["pos_name"].strip().lower() != pos_name.strip().lower()]
    pos_save_queue(q)

# ── Odoo product catalog ──────────────────────────────────────────────────────
def pos_get_odoo_products(cfg, uid, models):
    return models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
        "product.product", "search_read",
        [[["active","=",True]]],
        {"fields": ["id","name","default_code","categ_id"], "limit": 5000})

def pos_create_sale(cfg, uid, models, order_ref, lines, log):
    order_id = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
        "sale.order", "create", [{
            "name":       order_ref,
            "partner_id": 1,
            "order_line": [(0, 0, {
                "product_id":      l["product_id"],
                "product_uom_qty": l["qty"],
                "price_unit":      l["unit_price"],
            }) for l in lines]
        }])
    log("Odoo sale.order id=" + str(order_id) + "  ref=" + order_ref, "ok")
    return order_id

# ── POS API fetch ─────────────────────────────────────────────────────────────
QUICKBILL_URL = "https://quickbill.mealwheelz.com"

def _qb_get_session(email, password, log):
    """
    Login to QuickBill using Playwright to capture the HttpOnly session cookie,
    then return a requests.Session with that cookie injected.
    Falls back to pure requests if Playwright not available.
    """
    # Try Playwright first (handles HttpOnly cookies correctly)
    try:
        from playwright.sync_api import sync_playwright
        import os

        # When frozen as .exe, Playwright browsers must be installed
        # in a permanent location. Point to user's home Playwright cache.
        pw_browsers = os.path.join(os.path.expanduser("~"), "AppData", "Local",
                                   "ms-playwright")
        if os.path.exists(pw_browsers):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = pw_browsers
        else:
            # Standard install location
            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",
                                  os.path.join(os.path.expanduser("~"),
                                               "AppData", "Local", "ms-playwright"))

        log("QuickBill: logging in via Playwright...", "info")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx     = browser.new_context()
            page    = ctx.new_page()

            page.goto(QUICKBILL_URL + "/signin", wait_until="networkidle",
                      timeout=30000)
            log("QuickBill: signin page loaded — url=" + page.url, "info")

            # Fill email — try multiple selectors (Ant Design / plain HTML)
            for sel in ["input[name='email']", "input[type='email']",
                        "input[placeholder*='mail' i]", "input#email"]:
                try:
                    if page.locator(sel).count() > 0:
                        page.locator(sel).first.fill(email)
                        log("QuickBill: filled email via " + sel, "info")
                        break
                except Exception:
                    continue

            # Fill password
            for sel in ["input[type='password']", "input[name='password']",
                        "input[placeholder*='pass' i]", "input#password"]:
                try:
                    if page.locator(sel).count() > 0:
                        page.locator(sel).first.fill(password)
                        log("QuickBill: filled password via " + sel, "info")
                        break
                except Exception:
                    continue

            # Submit
            for sel in ["button[type='submit']", "input[type='submit']",
                        "button:has-text('Sign in')", "button:has-text('Login')",
                        "button:has-text('Log in')"]:
                try:
                    if page.locator(sel).count() > 0:
                        page.locator(sel).first.click()
                        log("QuickBill: clicked submit via " + sel, "info")
                        break
                except Exception:
                    continue

            # Wait for redirect away from signin
            try:
                page.wait_for_url(lambda u: "signin" not in u, timeout=20000)
                log("QuickBill: Playwright login OK  url=" + page.url, "ok")
            except Exception:
                # May already be redirected — check current URL
                if "signin" in page.url:
                    log("QuickBill: still on signin page — wrong credentials?", "warn")
                else:
                    log("QuickBill: redirected to " + page.url, "ok")

            # Extract ALL cookies including HttpOnly
            pw_cookies = ctx.cookies()
            log("QuickBill: captured " + str(len(pw_cookies)) + " cookies", "ok")
            browser.close()

        # Build requests session with the cookies
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/122.0 Safari/537.36",
            "Accept": "application/json",
            "Referer": QUICKBILL_URL,
        })
        for c in pw_cookies:
            session.cookies.set(c["name"], c["value"],
                                domain=c.get("domain",""),
                                path=c.get("path","/"))
        cookie_names = [c["name"] for c in pw_cookies]
        log("QuickBill: cookies captured = " + str(cookie_names), "ok")
        return session

    except ImportError:
        log("QuickBill: Playwright not installed — trying requests fallback", "warn")
        log("QuickBill: run: pip install playwright && playwright install chromium", "warn")
    except Exception as e:
        log("QuickBill: Playwright error: " + str(e), "warn")

    # Fallback: pure requests + NextAuth flow
    log("QuickBill: trying NextAuth HTTP login...", "info")
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 Chrome/122.0 Safari/537.36",
        "Accept": "application/json, text/html, */*",
        "Referer": QUICKBILL_URL + "/signin",
        "Origin":  QUICKBILL_URL,
    })

    # Get CSRF token
    csrf_token = ""
    try:
        r = session.get(QUICKBILL_URL + "/api/auth/csrf", timeout=15)
        if r.status_code == 200:
            csrf_token = r.json().get("csrfToken", "")
            log("QuickBill: CSRF obtained", "ok")
    except Exception as e:
        log("QuickBill: CSRF error: " + str(e), "warn")

    # POST to NextAuth signin
    try:
        r = session.post(
            QUICKBILL_URL + "/api/auth/signin/credentials",
            data={
                "email": email, "password": password,
                "csrfToken": csrf_token,
                "callbackUrl": QUICKBILL_URL + "/sales-report",
                "json": "true",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "application/json"},
            timeout=20, allow_redirects=True,
        )
        log("QuickBill: signin → " + str(r.status_code), "info")
        log("QuickBill: cookies = " + str(list(session.cookies.keys())), "info")
    except Exception as e:
        log("QuickBill: signin error: " + str(e), "warn")

    return session

def _qb_fetch_orders_page(session, target_date, log):
    """
    Try multiple QuickBill orders page URLs and return HTML content.
    """
    ds = target_date.strftime("%Y-%m-%d")
    urls_to_try = [
        QUICKBILL_URL + "/orders?date=" + ds,
        QUICKBILL_URL + "/orders-management?date=" + ds,
        QUICKBILL_URL + "/orders",
        QUICKBILL_URL + "/orders-management",
        QUICKBILL_URL + "/dashboard",
        QUICKBILL_URL + "/",
    ]
    for url in urls_to_try:
        try:
            r = session.get(url, timeout=20)
            log("QuickBill: GET " + url + " → " + str(r.status_code), "info")
            if r.status_code == 200 and "signin" not in r.url:
                html = r.text
                # Save for inspection
                (BASE_DIR / "quickbill_orders_page.html").write_text(
                    html, encoding="utf-8")
                log("QuickBill: orders page saved to quickbill_orders_page.html", "ok")
                return html, url
        except Exception as e:
            log("QuickBill: " + url + " error: " + str(e), "warn")
    return "", ""

def _qb_try_api_endpoints(session, target_date, log, branch_id="all"):
    """
    Fetch orders from QuickBill /api/reports endpoint (confirmed via Network tab).
    Uses UTC date range for the target day and size=1000 to fetch all orders.
    branch_id: "all" fetches all branches, or pass a restaurant _id to filter.
    Returns list of orders if found, else empty list.
    """
    # Build start/end for the target date (midnight-to-midnight)
    start_dt = datetime.combine(target_date, datetime.min.time())
    end_dt   = datetime.combine(target_date, datetime.max.time())
    # Format as the UTC string the API expects
    start_str = start_dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
    end_str   = end_dt.strftime("%a, %d %b %Y %H:%M:%S GMT")

    # Branch filter: QuickBill uses restaurant name string in the filter param
    # (no separate restaurant ID endpoint exists)
    restaurant_param = branch_id if branch_id and branch_id != "all" else "all"

    ep = ("/api/reports?"
          "startDate=" + requests.utils.quote(start_str) +
          "&endDate=" + requests.utils.quote(end_str) +
          "&orderType=all&restaurant=" + requests.utils.quote(restaurant_param) +
          "&selectedUser=all"
          "&paymentMethod=all&isCancelled=null"
          "&page=1&size=1000&searchQuery=")

    branch_label = branch_id if branch_id != "all" else "All Branches"
    log("QuickBill: GET /api/reports for " + target_date.strftime("%Y-%m-%d") +
        "  branch=" + branch_label, "info")
    try:
        r = session.get(QUICKBILL_URL + ep, timeout=30,
                       headers={"Accept": "application/json"})
        log("QuickBill: /api/reports → " + str(r.status_code), "info")
        if r.status_code == 200:
            content_type = r.headers.get("content-type", "")
            if "html" in content_type or r.text.strip().startswith("<"):
                log("QuickBill: /api/reports returned HTML (not authenticated)", "warn")
                return []
            data = r.json()
            keys = list(data.keys()) if isinstance(data, dict) else "list"
            log("QuickBill: response keys = " + str(keys), "info")
            # Save raw response for inspection
            (BASE_DIR / "quickbill_api_response.json").write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8")
            log("QuickBill: saved to quickbill_api_response.json", "ok")
            # Parse using confirmed QuickBill salesData structure
            orders = _qb_parse_salesdata(data, target_date, log)
            if orders:
                return orders
            log("QuickBill: response received but no orders parsed — "
                "check quickbill_api_response.json", "warn")
        else:
            log("QuickBill: /api/reports returned " + str(r.status_code), "warn")
    except Exception as e:
        log("QuickBill: /api/reports error: " + str(e), "warn")
    return []


def _qb_parse_salesdata(data, target_date, log):
    """
    Parse the confirmed QuickBill /api/reports response.
    salesData items have \\r\\n-separated product names and quantities.
    """
    orders = []
    sales = data.get("salesData", [])
    if not sales:
        log("QuickBill: salesData is empty or missing", "warn")
        return []

    for entry in sales:
        if not isinstance(entry, dict):
            continue
        # Skip cancelled orders
        if entry.get("isCancelled"):
            continue

        order_id  = str(entry.get("orderId", ""))
        order_ref = "QB-" + order_id if order_id else "QB-" + entry.get("_id", "")[:8]
        total     = float(entry.get("totalSale", 0))
        customer  = (entry.get("customerName") or
                     entry.get("resturant") or "QuickBill")
        # Clean up "0" placeholder customer names
        if customer in ("0", "", "null", "None"):
            customer = entry.get("resturant", "QuickBill")

        # Parse \r\n-separated products and quantities
        raw_products = str(entry.get("product", "")).split("\r\n")
        raw_qtys     = str(entry.get("quantity", "")).split("\r\n")
        raw_products = [p.strip() for p in raw_products if p.strip()]
        raw_qtys     = [q.strip() for q in raw_qtys if q.strip()]

        items = []
        for i, prod_name in enumerate(raw_products):
            qty = 1.0
            if i < len(raw_qtys):
                try:
                    qty = float(raw_qtys[i])
                except ValueError:
                    qty = 1.0
            # Unit price not available per-line; set 0 — sync job uses Odoo mapping
            items.append({
                "name":       prod_name,
                "qty":        qty,
                "unit_price": 0,
            })

        # If no items could be parsed, create a single-line fallback
        if not items and total > 0:
            items = [{"name": order_ref, "qty": 1, "unit_price": total}]

        # Detect order type: delivery / takeaway / dine-in
        raw_type = str(entry.get("orderType") or entry.get("order_type") or
                       entry.get("type") or entry.get("channel") or "").lower().strip()
        if any(x in raw_type for x in ["delivery","deliver"]):
            order_type = "Delivery"
        elif any(x in raw_type for x in ["takeaway","take away","take_away","takeout","pickup"]):
            order_type = "Takeaway"
        elif any(x in raw_type for x in ["dine","table","sit","in"]):
            order_type = "Dine-in"
        else:
            order_type = raw_type.title() if raw_type else "Unknown"

        # Parse time for peak hour analysis
        raw_date = entry.get("date","") or entry.get("createdAt","") or ""
        order_hour = None
        if raw_date:
            try:
                from datetime import timezone as _tz
                dt_parsed = datetime.strptime(raw_date[:19].replace("T"," "), "%Y-%m-%d %H:%M:%S")
                dt_pkt = dt_parsed + timedelta(hours=5)  # UTC→PKT
                order_hour = dt_pkt.hour
            except:
                pass

        orders.append({
            "order_ref":  order_ref,
            "customer":   customer,
            "total":      total,
            "items":      items,
            "cashier":    entry.get("cashier", ""),
            "method":     entry.get("method", ""),
            "date":       entry.get("date", ""),
            "branch":     entry.get("resturant", ""),
            "order_type": order_type,
            "hour":       order_hour,
        })

    log("QuickBill: parsed " + str(len(orders)) + " orders from /api/reports "
        "(total: Rs." + str(data.get("totalSales", 0)) + ")", "ok")
    return orders


def qb_fetch_branches(cfg, log):
    """
    Get list of branches with their MongoDB _id by reading salesData.
    Each salesData entry has 'resturant' (name) and 'restaurantId' or
    similar field. We scan all entries and map name → id.
    Falls back to name-only if no ID field found (API will return 500
    when filtering by name, so branch filter won't work in that case).
    """
    email    = cfg.get("quickbill_email","").strip()
    password = cfg.get("quickbill_password","").strip()
    if not email or not password:
        log("QuickBill: credentials not set", "warn")
        return []
    try:
        session = _qb_get_session(email, password, log)

        from datetime import date as _date
        today    = _date.today()
        week_ago = today - timedelta(days=7)
        start_str = datetime.combine(week_ago,
            datetime.min.time()).strftime("%a, %d %b %Y %H:%M:%S GMT")
        end_str   = datetime.combine(today,
            datetime.max.time()).strftime("%a, %d %b %Y %H:%M:%S GMT")

        ep = ("/api/reports?"
              "startDate=" + requests.utils.quote(start_str) +
              "&endDate="  + requests.utils.quote(end_str) +
              "&orderType=all&restaurant=all&selectedUser=all"
              "&paymentMethod=all&isCancelled=null"
              "&page=1&size=500&searchQuery=")

        r = session.get(QUICKBILL_URL + ep, timeout=30,
                        headers={"Accept": "application/json"})
        log("QuickBill: branch discovery → " + str(r.status_code), "info")

        if r.status_code != 200:
            log("QuickBill: could not fetch branch list", "warn")
            return []

        ct = r.headers.get("content-type","")
        if "html" in ct or r.text.strip().startswith("<"):
            log("QuickBill: branch discovery returned HTML (auth issue)", "warn")
            return []

        data  = r.json()
        sales = data.get("salesData", [])

        # Save one raw entry for inspection so we can find the ID field
        if sales:
            (BASE_DIR / "quickbill_branch_entry.json").write_text(
                json.dumps(sales[0], indent=2, ensure_ascii=False),
                encoding="utf-8")
            log("QuickBill: sample entry saved to quickbill_branch_entry.json", "info")

        # Try to find the restaurant ID field name
        # Common possibilities in MongoDB-backed APIs:
        id_field_candidates = [
            "restaurantId", "restaurant_id", "restaurant",
            "branchId", "branch_id", "restaurantObjectId",
        ]

        seen   = {}   # name → _id
        for entry in sales:
            if not isinstance(entry, dict): continue
            name = str(entry.get("resturant","")).strip()
            if not name or name in ("0","null","None",""): continue
            if name in seen: continue

            # Try to find a MongoDB ObjectId (24-hex chars) for this restaurant
            rid = None
            for field in id_field_candidates:
                val = str(entry.get(field,"")).strip()
                if len(val) == 24 and all(c in "0123456789abcdef" for c in val.lower()):
                    rid = val
                    break

            seen[name] = rid  # None if no ID field found

        result = []
        for name, rid in sorted(seen.items()):
            if rid:
                result.append({"_id": rid,  "name": name})
                log("  Branch: " + name + "  id=" + rid, "info")
            else:
                # No ID found — store name as fallback, mark as unresolved
                result.append({"_id": "__NAME__:" + name, "name": name})
                log("  Branch: " + name + "  (no ID found — all-branches only)", "warn")

        log("QuickBill: " + str(len(result)) + " branch(es) found", "ok")
        return result

    except Exception as e:
        log("QuickBill: branch fetch error: " + str(e), "warn")
        return []


def _qb_parse_api_response(data, log):
    """Parse a JSON API response into standard order format (legacy fallback)."""
    orders = []
    try:
        # Handle list response
        if isinstance(data, list):
            raw_orders = data
        elif isinstance(data, dict):
            # Try common wrapper keys
            for key in ["orders","data","results","items","records"]:
                if key in data:
                    raw_orders = data[key]
                    break
            else:
                raw_orders = []

        for o in raw_orders:
            if not isinstance(o, dict): continue
            ref   = (o.get("order_ref") or o.get("id") or
                     o.get("order_id") or o.get("reference") or
                     "QB-" + str(len(orders)+1))
            total = float(o.get("total") or o.get("amount") or
                          o.get("grand_total") or 0)
            customer = (o.get("customer") or o.get("customer_name") or
                        o.get("table") or "QuickBill")
            # Parse items
            raw_items = (o.get("items") or o.get("order_lines") or
                         o.get("products") or [])
            items = []
            for it in raw_items:
                if not isinstance(it, dict): continue
                name  = (it.get("name") or it.get("product_name") or
                         it.get("item_name") or "Item")
                qty   = float(it.get("qty") or it.get("quantity") or 1)
                price = float(it.get("unit_price") or it.get("price") or
                              it.get("rate") or 0)
                items.append({"name": name, "qty": qty, "unit_price": price})
            if not items and total > 0:
                items = [{"name": str(ref), "qty": 1, "unit_price": total}]
            orders.append({"order_ref": str(ref), "customer": str(customer),
                           "total": total, "items": items})
        log("QuickBill: parsed " + str(len(orders)) + " orders from API", "ok")
    except Exception as e:
        log("QuickBill: API parse error: " + str(e), "warn")
    return orders

def _qb_parse_html_orders(html, target_date, log):
    """Parse orders from HTML page using simple string parsing (no BS4 needed)."""
    import re
    orders = []
    ds = target_date.strftime("%Y-%m-%d")

    # Find table rows
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE)
    log("QuickBill: HTML rows found = " + str(len(rows)), "info")

    for row in rows:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL | re.IGNORECASE)
        if len(cells) < 2: continue
        # Strip tags from cell text
        texts = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
        texts = [t for t in texts if t]
        if not texts: continue

        ref   = texts[0] if texts else "QB-" + str(len(orders)+1)
        total = 0.0
        for t in reversed(texts):
            try:
                total = float(t.replace(",","").replace("Rs","")
                               .replace("PKR","").replace("₨","").strip())
                if total > 0: break
            except Exception:
                continue

        orders.append({
            "order_ref": ref,
            "customer":  "QuickBill",
            "total":     total,
            "items":     [{"name": ref, "qty": 1, "unit_price": total}]
        })

    return orders

def pos_fetch_orders(cfg, target_date, log):
    """
    Fetch QuickBill orders using direct HTTP requests (no Selenium/Chrome needed).
    Falls back to demo data if credentials missing.
    """
    email    = cfg.get("quickbill_email","").strip()
    password = cfg.get("quickbill_password","").strip()

    if not email or not password:
        log("QuickBill credentials not set — using demo data", "warn")
        return pos_demo_orders(target_date)

    log("QuickBill: connecting via HTTP session...", "info")
    try:
        # Step 1: Authenticate
        session = _qb_get_session(email, password, log)

        # Step 2: Try direct JSON API endpoints first (fastest)
        branch_id = cfg.get("quickbill_branch", "all")
        branch_name = cfg.get("quickbill_branch_name", "All Branches")
        log("QuickBill: branch filter = " + branch_name, "info")
        orders = _qb_try_api_endpoints(session, target_date, log, branch_id)
        if orders:
            return orders

        # Step 3: Fetch the orders HTML page and parse it
        html, page_url = _qb_fetch_orders_page(session, target_date, log)
        if html:
            orders = _qb_parse_html_orders(html, target_date, log)
            if orders:
                return orders
            log("QuickBill: HTML parsed but no orders found", "warn")
            log("QuickBill: check quickbill_orders_page.html to see page structure", "warn")
        else:
            log("QuickBill: could not load any orders page", "err")
            log("QuickBill: check quickbill_orders_page.html for debug info", "warn")

        return []

    except Exception as e:
        log("QuickBill error: " + str(e), "err")
        log("Falling back to demo data", "warn")
        return pos_demo_orders(target_date)

def pos_demo_orders(target_date):
    return [
        {"order_ref": "QB-DEMO-001", "customer": "Walk-in", "total": 48.50,
         "items": [
             {"name": "Grilled Chkn Wrap",  "qty": 2, "unit_price": 12.0},
             {"name": "mango lassi",         "qty": 1, "unit_price": 3.5},
             {"name": "Frnch Fries Reg",     "qty": 2, "unit_price": 4.5},
         ]},
        {"order_ref": "QB-DEMO-002", "customer": "Table 5", "total": 35.00,
         "items": [
             {"name": "beef shawurma",       "qty": 1, "unit_price": 18.0},
             {"name": "choc lava cake",      "qty": 1, "unit_price": 8.0},
             {"name": "orange juise fresh",  "qty": 2, "unit_price": 4.5},
         ]},
    ]

# ── Similarity engine ─────────────────────────────────────────────────────────
def pos_match_product(pos_name, odoo_products, cfg, log):
    """Returns (action, odoo_id, odoo_name, score, source, reason)"""
    auto_t   = int(cfg.get("sim_auto_threshold",   85))
    reject_t = int(cfg.get("sim_reject_threshold", 40))

    cached = pos_lookup_mapping(pos_name)
    if cached:
        oid   = cached["odoo_product_id"]
        oname = cached["odoo_product_name"]
        if oid == -1:
            return ("skip", None, None, 100, "cache", "Marked unknown")
        return ("auto", oid, oname, 100, "cache", "Confirmed mapping")

    if not HAS_RAPIDFUZZ:
        return ("review", None, None, 0, "none", "rapidfuzz not installed")

    odoo_names = [p["name"] for p in odoo_products]
    best = rfprocess.extractOne(pos_name, odoo_names, scorer=fuzz.WRatio, score_cutoff=0)
    if not best:
        return ("unknown", None, None, 0, "fuzzy", "Empty catalog")

    matched_name, score, idx = best
    matched = odoo_products[idx]

    if score >= auto_t:
        return ("auto", matched["id"], matched["name"], score, "fuzzy",
                "Score " + str(round(score,1)) + " >= " + str(auto_t))

    if score >= reject_t and cfg.get("use_claude_matching") and HAS_ANTHROPIC:
        return pos_claude_match(pos_name, odoo_products, matched, score, cfg, log)

    action = "review" if score >= reject_t else "unknown"
    return (action,
            matched["id"] if score >= reject_t else None,
            matched["name"] if score >= reject_t else None,
            score, "fuzzy", "Score " + str(round(score,1)))

def pos_claude_match(pos_name, odoo_products, fuzzy_match, fuzzy_score, cfg, log):
    api_key = cfg.get("anthropic_key","").strip()
    if not api_key:
        return ("review", fuzzy_match["id"], fuzzy_match["name"],
                fuzzy_score, "fuzzy", "No Claude key")
    odoo_names = [p["name"] for p in odoo_products]
    candidates = rfprocess.extract(pos_name, odoo_names, scorer=fuzz.WRatio, limit=5)
    cand_str   = "\n".join([str(i+1)+". "+n+" (score: "+str(round(s))+"):"
                            for i,(n,s,_) in enumerate(candidates)])
    prompt = ('Match restaurant POS name to Odoo catalog.\n'
              'POS: "' + pos_name + '"\nCandidates:\n' + cand_str + '\n\n'
              'Reply ONLY:\nMATCH: <name or NONE>\nCONFIDENCE: <HIGH|MEDIUM|LOW>\nREASON: <one line>')
    try:
        client   = _anthropic_sdk.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514", max_tokens=120,
            messages=[{"role":"user","content":prompt}])
        reply = response.content[0].text.strip()
        log("Claude: " + reply.replace("\n"," | "), "info")
        parts = {l.split(":")[0].strip(): ":".join(l.split(":")[1:]).strip()
                 for l in reply.splitlines() if ":" in l}
        mname = parts.get("MATCH","NONE").strip()
        conf  = parts.get("CONFIDENCE","LOW").upper()
        reason= parts.get("REASON","")
        if mname.upper() == "NONE":
            return ("unknown", None, None, 0, "claude", reason)
        found = next((p for p in odoo_products
                      if p["name"].strip().lower()==mname.strip().lower()), fuzzy_match)
        cscore = {"HIGH":92,"MEDIUM":72,"LOW":52}.get(conf, 60)
        action = "auto" if conf=="HIGH" else "review"
        return (action, found["id"], found["name"], cscore, "claude",
                "Claude "+conf+": "+reason)
    except Exception as e:
        log("Claude error: " + str(e), "warn")
        return ("review", fuzzy_match["id"], fuzzy_match["name"],
                fuzzy_score, "fuzzy", "Claude failed")

# ── Main POS sync job ─────────────────────────────────────────────────────────
def sync_products_to_odoo(cfg, log):
    """
    Collect all unique products ever sold in QuickBill (last 90 days),
    then create any missing ones in Odoo as draft product.template records
    with can_be_sold=True, type='consu' (consumable / service).
    Already-existing products (matched by name, case-insensitive) are skipped.
    """
    log("=" * 44, "info")
    log("QuickBill → Odoo Product Import", "info")
    log("=" * 44, "info")

    email       = cfg.get("quickbill_email","").strip()
    password    = cfg.get("quickbill_password","").strip()
    branch_id   = cfg.get("quickbill_branch", "all")
    branch_name = cfg.get("quickbill_branch_name", "All Branches")

    if not email or not password:
        log("QuickBill credentials not set", "err"); return

    # ── Step 1: Login to QuickBill ────────────────────────────────────────────
    try:
        session = _qb_get_session(email, password, log)
        log("QuickBill authenticated", "ok")
    except Exception as e:
        log("QuickBill login failed: " + str(e), "err"); return

    # ── Step 2: Fetch 90 days of sales in weekly chunks ───────────────────────
    log("Fetching product list  branch=" + branch_name + " (last 90 days)...", "info")
    all_product_names = set()
    from datetime import date as _date
    today = _date.today()
    restaurant_param = branch_id if branch_id != "all" else "all"

    for weeks_back in range(13):          # 13 × 7 = 91 days
        chunk_end   = today - timedelta(days=weeks_back * 7)
        chunk_start = today - timedelta(days=weeks_back * 7 + 6)
        try:
            start_str = datetime.combine(chunk_start,
                datetime.min.time()).strftime("%a, %d %b %Y %H:%M:%S GMT")
            end_str   = datetime.combine(chunk_end,
                datetime.max.time()).strftime("%a, %d %b %Y %H:%M:%S GMT")
            ep = ("/api/reports?"
                  "startDate=" + requests.utils.quote(start_str) +
                  "&endDate="   + requests.utils.quote(end_str) +
                  "&orderType=all&restaurant=" + requests.utils.quote(restaurant_param) +
                  "&selectedUser=all&paymentMethod=all&isCancelled=null"
                  "&page=1&size=2000&searchQuery=")
            r = session.get(QUICKBILL_URL + ep, timeout=30,
                            headers={"Accept": "application/json"})
            if r.status_code == 200:
                ct = r.headers.get("content-type","")
                if "html" not in ct and not r.text.strip().startswith("<"):
                    data  = r.json()
                    sales = data.get("salesData", [])
                    for entry in sales:
                        if entry.get("isCancelled"): continue
                        raw = str(entry.get("product",""))
                        for p in raw.split("\r\n"):
                            p = p.strip()
                            if p and p not in ("0","null","None",""):
                                all_product_names.add(p)
        except Exception as e:
            log("Chunk week-" + str(weeks_back) + " error: " + str(e), "warn")

    if not all_product_names:
        log("No products found in QuickBill data", "warn"); return

    log("QuickBill unique products found: " + str(len(all_product_names)), "ok")

    # ── Step 3: Connect to Odoo ───────────────────────────────────────────────
    try:
        uid, models, host = odoo_auth(cfg)
        log("Odoo authenticated  UID=" + str(uid), "ok")
    except Exception as e:
        log("Odoo auth failed: " + str(e), "err"); return

    # ── Step 4: Load existing Odoo products ───────────────────────────────────
    try:
        existing = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
            "product.template", "search_read",
            [[["active","=",True]]],
            {"fields": ["id","name"], "limit": 10000})
        existing_lower = {p["name"].strip().lower() for p in existing}
        log("Odoo existing products: " + str(len(existing_lower)), "info")
    except Exception as e:
        log("Odoo product fetch failed: " + str(e), "err"); return

    # ── Step 5: Find products missing from Odoo ───────────────────────────────
    to_create = sorted([n for n in all_product_names
                        if n.strip().lower() not in existing_lower])
    log("Products to create: " + str(len(to_create)), "info")

    if not to_create:
        log("All QuickBill products already exist in Odoo ✓", "ok")
        return

    # ── Step 6: Create missing products in Odoo (draft = sale_ok=True) ────────
    created = 0
    failed  = 0
    for name in to_create:
        try:
            models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
                "product.template", "create", [{
                    "name":          name,
                    "type":          "consu",   # consumable (most common for food)
                    "sale_ok":       True,       # can be sold
                    "purchase_ok":   False,      # not purchased via PO
                    "active":        True,
                    "description":   "Imported from QuickBill POS — " + branch_name,
                }])
            created += 1
            log("  ✓ Created: " + name, "ok")
        except Exception as e:
            failed += 1
            log("  ✗ Failed: " + name + " — " + str(e), "err")

    # ── Summary ───────────────────────────────────────────────────────────────
    log("─" * 44, "info")
    log("Product import complete", "ok")
    log("  Created:  " + str(created), "ok")
    log("  Skipped:  " + str(len(existing_lower)), "info")
    log("  Failed:   " + str(failed), "warn" if failed else "info")
    log("Check Odoo → Inventory → Products to review new items.", "info")


def _compute_pos_summary(orders):
    """Compute summary stats from orders list."""
    total    = sum(o.get("total",0) for o in orders)
    delivery = sum(1 for o in orders if o.get("order_type","") == "Delivery")
    takeaway = sum(1 for o in orders if o.get("order_type","") == "Takeaway")
    dinein   = sum(1 for o in orders if o.get("order_type","") == "Dine-in")
    hour_counts = {}
    for o in orders:
        h = o.get("hour")
        if h is not None:
            hour_counts[h] = hour_counts.get(h,0) + 1
    peak_hour = max(hour_counts, key=hour_counts.get) if hour_counts else None
    return {"total": total, "delivery": delivery, "takeaway": takeaway,
            "dinein": dinein, "orders": len(orders), "peak_hour": peak_hour,
            "hour_counts": hour_counts}


def run_pos_sync_job(cfg, target_date, log):
    log("=" * 44, "info")
    log("POS Sync: " + target_date.strftime("%d %B %Y"), "info")
    log("=" * 44, "info")
    try:
        orders = pos_fetch_orders(cfg, target_date, log)
        if not orders:
            log("No POS orders found.", "warn"); return

        uid, models, host = odoo_auth(cfg)
        log("Odoo authenticated  UID=" + str(uid), "ok")
        odoo_products = pos_get_odoo_products(cfg, uid, models)
        log("Loaded " + str(len(odoo_products)) + " Odoo products", "ok")

        stats = {"auto":0,"review":0,"unknown":0,"skip":0,"orders_ok":0}

        for order in orders:
            ref   = order.get("order_ref","POS-"+str(int(time.time())))
            items = order.get("items",[])
            total = order.get("total",0)
            log("── "+ref+"  ("+str(len(items))+" items  total="+str(total)+")", "info")
            resolved = []
            for item in items:
                pname = item.get("name","").strip()
                qty   = float(item.get("qty",1))
                price = float(item.get("unit_price",0))
                if not pname: continue
                action, oid, oname, score, source, reason = pos_match_product(
                    pname, odoo_products, cfg, log)
                sc = str(round(score,1))
                if action == "auto":
                    if source not in ("cache",):
                        pos_save_mapping(pname, oid, oname)
                    resolved.append({"product_id":oid,"qty":qty,"unit_price":price})
                    stats["auto"] += 1
                    log("  ✓ AUTO  '"+pname+"' → '"+str(oname)+"'  s="+sc+" ["+source+"]","ok")
                elif action == "review":
                    pos_add_to_queue({"pos_name":pname,"odoo_product_id":oid,
                                      "odoo_product_name":oname,"score":score,
                                      "reasoning":reason,"pending_orders":[ref]})
                    stats["review"] += 1
                    log("  ? QUEUE '"+pname+"' → '"+str(oname)+"'  s="+sc,"warn")
                elif action == "skip":
                    stats["skip"] += 1
                    log("  – SKIP  '"+pname+"'","warn")
                else:
                    pos_add_to_queue({"pos_name":pname,"odoo_product_id":None,
                                      "odoo_product_name":None,"score":score,
                                      "reasoning":reason,"pending_orders":[ref]})
                    stats["unknown"] += 1
                    log("  ✗ UNK   '"+pname+"'  no match","err")

            if resolved:
                try:
                    pos_create_sale(cfg, uid, models, ref, resolved, log)
                    stats["orders_ok"] += 1
                except Exception as e:
                    log("Odoo write failed "+ref+": "+str(e), "err")
            else:
                log("  "+ref+" — no confirmed lines, skipped","warn")

        q_count = len(pos_load_queue())
        log("─"*44,"info")
        log("Done  Auto:"+str(stats["auto"])+"  Review:"+str(stats["review"])+
            "  Unk:"+str(stats["unknown"])+"  OdooRecs:"+str(stats["orders_ok"]),"ok")
        if stats["review"]+stats["unknown"] > 0:
            log("► "+str(q_count)+" item(s) pending — go to POS Sync → Review tab","warn")
            if cfg.get("notify_on_review") and cfg.get("notify_phone"):
                msg = ("POS Sync Alert\n\n"+str(stats["review"]+stats["unknown"])+
                       " product(s) need confirmation.\nOpen POS Sync Bot → Review tab.")
                send_whatsapp_green(cfg, cfg["notify_phone"], msg, None, log)
    except Exception as e:
        log("POS SYNC ERROR: " + str(e), "err")

# ══════════════════════════════════════════════════════════════════════════════
#  GUI  —  Light Theme
# ══════════════════════════════════════════════════════════════════════════════
class App(tk.Tk, FuelMixin, GpsMixin):
    def __init__(self):
        super().__init__()
        self.cfg        = load_config()
        self.running    = False
        self.sched_th   = None
        self._companies = []
        # In HR mode, start on Audit Log page; otherwise default to PO
        self._cur_page  = "audit" if HR_MODE else "po"
        self._pos_queue_items = []
        self._pos_odoo_products = []
        if HR_MODE:
            self.title("HR Audit Bot")
        else:
            self.title("Odoo Bot v5.4")
        self.resizable(True, True)
        self.minsize(900, 600)
        # Start maximized so all content is visible
        try:
            self.state("zoomed")          # Windows maximize
        except Exception:
            self.geometry("1280x800")     # Fallback for other OS
        self.configure(bg=C["page"])
        self._style()
        self._build_ui()
        self._load_fields()
        self._show_page("dashboard")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _add_tree_search(self, parent, tree, placeholder="Search name..."):
        """Add a search bar above a treeview that filters rows by name (column #0)."""
        import tkinter as tk
        sf = tk.Frame(parent, bg=C["page"])
        sf.pack(fill="x", padx=0, pady=(0,2))
        tk.Label(sf, text="🔍", font=("Segoe UI",9),
                 bg=C["page"], fg=C["text4"]).pack(side="left", padx=(4,2))
        var = tk.StringVar()
        entry = tk.Entry(sf, textvariable=var, font=("Segoe UI",9),
                         bg=C["input"], fg=C["text"], relief="flat",
                         insertbackground=C["text"], bd=4)
        entry.pack(side="left", fill="x", expand=True, padx=(0,4), pady=2)
        entry.insert(0, placeholder)
        entry.config(fg=C["text4"])

        def _focus_in(e):
            if entry.get() == placeholder:
                entry.delete(0, "end")
                entry.config(fg=C["text"])
        def _focus_out(e):
            if not entry.get():
                entry.insert(0, placeholder)
                entry.config(fg=C["text4"])
        entry.bind("<FocusIn>", _focus_in)
        entry.bind("<FocusOut>", _focus_out)

        # Store all rows for filtering
        tree._all_rows = []
        tree._search_var = var

        # Use a separate flag to distinguish filter-delete vs populate-delete
        tree._all_rows = []
        tree._filtering = False

        def _filter(*args):
            q = var.get().strip().lower()
            if q == placeholder.lower(): q = ""
            saved = list(tree._all_rows)   # save before delete
            tree._filtering = True
            for ch in tree.get_children():
                _orig_delete(ch)
            tree._filtering = False
            tree._all_rows = saved         # restore after delete
            for row in saved:
                name = row[0].lower()
                if not q or q in name:
                    _orig_insert("", "end", text=row[0],
                                 values=row[1:-1], tags=(row[-1],))
        var.trace_add("write", _filter)

        # Patch insert to also store in _all_rows (only during populate, not filter)
        _orig_insert = tree.insert
        def _patched_insert(parent_id, pos, iid=None, **kw):
            result = _orig_insert(parent_id, pos, iid=iid, **kw)
            if parent_id == "" and not tree._filtering:
                text = kw.get("text", "")
                values = kw.get("values", ())
                tags = kw.get("tags", ("",))
                tag = tags[0] if tags else ""
                tree._all_rows.append((text,) + tuple(values) + (tag,))
            return result
        tree.insert = _patched_insert

        # Patch delete to clear _all_rows only during populate (not filter)
        _orig_delete = tree.delete
        def _patched_delete(*items):
            if not tree._filtering:
                tree._all_rows = []
            _orig_delete(*items)
        tree.delete = _patched_delete

        # Column click sorting
        def _sort_col(col, reverse):
            children = tree.get_children("")
            data = [(tree.set(k, col) if col != "#0" else tree.item(k)["text"], k)
                    for k in children]
            try:
                data.sort(key=lambda x: float(x[0].replace("%","").replace("h","").replace("m","").split("(")[0].strip() or 0), reverse=reverse)
            except Exception:
                data.sort(key=lambda x: x[0].lower(), reverse=reverse)
            for i, (_, k) in enumerate(data):
                tree.move(k, "", i)
            tree.heading(col, command=lambda: _sort_col(col, not reverse))

        for col in [c for c in tree["columns"]] + ["#0"]:
            tree.heading(col, command=lambda c=col: _sort_col(c, False))

        return sf, entry

    def _make_scrollable(self, page):
        """Wrap a page frame in a Canvas+Scrollbar so content scrolls vertically.
        Returns the inner frame where widgets should be placed."""
        canvas = tk.Canvas(page, bg=C["page"], highlightthickness=0)
        vsb    = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=C["page"])
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_resize(e):
            canvas.itemconfig(win_id, width=e.width)
        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        inner.bind("<Configure>", _on_configure)
        canvas.bind("<Configure>", _on_canvas_resize)
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        return inner

    def _style(self):
        s = ttk.Style()
        s.theme_use("default")
        s.configure("TProgressbar", troughcolor=C["border"], background=C["accent"],
                    thickness=4, borderwidth=0)
        s.configure("TCombobox", fieldbackground=C["input2"], background=C["input2"],
                    foreground=C["accent"], borderwidth=1, relief="flat")

    def _build_ui(self):
        # Title bar
        tb = tk.Frame(self, bg=C["white"], height=44)
        tb.pack(fill="x"); tb.pack_propagate(False)
        tk.Frame(tb, bg="#e8f0ff", width=28, height=28).place(x=12, y=8)
        tk.Label(tb, text="📦", font=("Segoe UI Emoji",14), bg=C["white"]).place(x=14, y=9)
        tk.Label(tb, text="Odoo Bot", font=("Segoe UI",11,"bold"),
                 bg=C["white"], fg=C["text"]).place(x=48, y=12)
        tk.Label(tb, text="v5.4", font=("Segoe UI",9),
                 bg=C["accent_l"], fg=C["accent"]).place(x=122, y=14)
        self.lbl_status = tk.Label(tb, text="● Idle", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"])
        self.lbl_status.pack(side="right", padx=16)
        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        body = tk.Frame(self, bg=C["page"])
        body.pack(fill="both", expand=True)

        # Sidebar
        sb = tk.Frame(body, bg=C["sidebar"], width=195)
        sb.pack(side="left", fill="y"); sb.pack_propagate(False)
        tk.Frame(body, bg=C["border"], width=1).pack(side="left", fill="y")
        self._build_sidebar(sb)

        # Main
        self.main = tk.Frame(body, bg=C["page"])
        self.main.pack(side="left", fill="both", expand=True)

        self.pages = {}
        self._build_dashboard_page()
        self._build_reports_page()
        self._build_settings_page()

    # ── Reload App ───────────────────────────────────────────────────────────
    def _reload_app(self):
        """Restart the application — works for both .py and frozen .exe."""
        import sys, os, subprocess
        try:
            if getattr(sys, "frozen", False):
                # Running as compiled exe (PyInstaller)
                exe = sys.executable          # path to the .exe itself
                self.destroy()
                subprocess.Popen([exe])
            else:
                # Running as plain Python script
                self.destroy()
                subprocess.Popen([sys.executable] + sys.argv)
        except Exception as e:
            # Last resort — just close, user reopens manually
            from tkinter import messagebox
            messagebox.showinfo("Reload",
                "Could not auto-restart.\nPlease close and reopen the app manually.\n\n"
                "Error: " + str(e))
            self.destroy()

    # ── Debug Console page ────────────────────────────────────────────────────
    def _build_debug_page(self):
        page = tk.Frame(self.main, bg=C["page"])
        self.pages["debug"] = page

        # Topbar — fixed, never scrolls
        tp = tk.Frame(page, bg=C["topbar"], height=44)
        tp.pack(fill="x"); tp.pack_propagate(False)
        tk.Label(tp, text="  🐛 Debug Console", font=("Segoe UI",12,"bold"),
                 bg=C["topbar"], fg=C["text"]).pack(side="left", pady=10)
        tk.Label(tp, text="Live Python — runs inside the app",
                 font=("Segoe UI",9), bg=C["topbar"], fg=C["text4"]
                 ).pack(side="left", padx=(10,0))
        tk.Button(tp, text="🔁 Reload App",
                  command=self._reload_app,
                  font=("Segoe UI",9,"bold"),
                  bg=C["accent_l"], fg=C["accent"],
                  relief="flat", bd=0, padx=12, pady=4, cursor="hand2"
                  ).pack(side="right", padx=12, pady=8)
        tk.Frame(page, bg=C["border"], height=1).pack(fill="x")

        # ── Split pane: editor top, output bottom, draggable divider ─────────
        pane = tk.PanedWindow(page, orient="vertical",
                              bg=C["border"], sashwidth=5,
                              sashrelief="flat", bd=0)
        pane.pack(fill="both", expand=True, padx=0, pady=0)

        # TOP PANE — editor
        top_pane = tk.Frame(pane, bg=C["page"])
        pane.add(top_pane, minsize=120)

        editor_outer = tk.Frame(top_pane, bg=C["border"], padx=1, pady=1)
        editor_outer.pack(fill="both", expand=True, padx=10, pady=(8,0))
        editor_inner = tk.Frame(editor_outer, bg="#1e1e2e")
        editor_inner.pack(fill="both", expand=True)

        ed_hdr = tk.Frame(editor_inner, bg="#1e1e2e", padx=10, pady=5)
        ed_hdr.pack(fill="x")
        tk.Label(ed_hdr, text="Code  (Ctrl+Enter to run)",
                 font=("Segoe UI",9,"bold"), bg="#1e1e2e", fg="#cdd6f4"
                 ).pack(side="left")

        # Snippet presets
        presets = [
            ("ERP session?",
             "sess = getattr(app, '_zerp_session', None)\nprint('ERP session:', sess)"),
            ("TD cookies?",
             "c = getattr(app, '_td_playwright_cookies', None)\nprint('TD cookies:', len(c) if c else None)"),
            ("Config",
             "import json\nprint(json.dumps(load_config(), indent=2))"),
            ("Clear output", ""),
        ]
        preset_row = tk.Frame(ed_hdr, bg="#1e1e2e")
        preset_row.pack(side="right")
        tk.Label(preset_row, text="Presets:",
                 font=("Segoe UI",8), bg="#1e1e2e", fg="#6c7086").pack(side="left", padx=(0,4))

        self._debug_editor = None  # will be set below

        def _load_preset(code):
            self._debug_editor.delete("1.0", "end")
            self._debug_editor.insert("1.0", code)

        for label, code in presets:
            tk.Button(preset_row, text=label,
                      command=lambda c=code: _load_preset(c),
                      font=("Segoe UI",8), bg="#313244", fg="#cdd6f4",
                      relief="flat", bd=0, padx=6, pady=2, cursor="hand2"
                      ).pack(side="left", padx=2)

        # Code text widget
        code_frame = tk.Frame(editor_inner, bg="#1e1e2e")
        code_frame.pack(fill="both", expand=True, padx=0, pady=0)

        # Line numbers
        self._debug_linenos = tk.Text(code_frame, width=3,
                 font=("Consolas",11), bg="#181825", fg="#6c7086",
                 relief="flat", bd=0, state="disabled",
                 padx=4, pady=6, selectbackground="#181825")
        self._debug_linenos.pack(side="left", fill="y")

        self._debug_editor = tk.Text(code_frame, height=10,
                 font=("Consolas",11), bg="#1e1e2e", fg="#cdd6f4",
                 insertbackground="#cba6f7", relief="flat", bd=0,
                 padx=10, pady=6,
                 selectbackground="#313244", selectforeground="#cdd6f4",
                 undo=True, wrap="none")
        ed_vsb = tk.Scrollbar(code_frame, orient="vertical",
                              command=self._debug_editor.yview, bg="#1e1e2e")
        self._debug_editor.configure(yscrollcommand=ed_vsb.set)
        ed_vsb.pack(side="right", fill="y")
        self._debug_editor.pack(side="left", fill="both", expand=True)

        # Syntax highlight colours mapping
        self._debug_editor.tag_configure("kw",      foreground="#cba6f7")
        self._debug_editor.tag_configure("string",  foreground="#a6e3a1")
        self._debug_editor.tag_configure("comment", foreground="#6c7086", font=("Consolas",11,"italic"))
        self._debug_editor.tag_configure("number",  foreground="#fab387")
        self._debug_editor.tag_configure("builtin", foreground="#89dceb")

        # Insert starter snippet
        starter = (
            "# 'app' = the running App instance\n"
            "# 'load_config' / 'save_config' available\n"
            "# Example:\n"
            "print('Hello from debug console!')\n"
            "print('ERP session:', getattr(app, '_zerp_session', None))\n"
        )
        self._debug_editor.insert("1.0", starter)

        def _update_linenos(e=None):
            lines = int(self._debug_editor.index("end-1c").split(".")[0])
            self._debug_linenos.config(state="normal")
            self._debug_linenos.delete("1.0","end")
            self._debug_linenos.insert("1.0", "\n".join(str(i) for i in range(1, lines+1)))
            self._debug_linenos.config(state="disabled")

        self._debug_editor.bind("<KeyRelease>", _update_linenos)
        _update_linenos()

        # Ctrl+Enter runs code
        self._debug_editor.bind("<Control-Return>", lambda e: self._debug_run())

        # ── Bottom pane — output ──────────────────────────────────────────────
        bot_pane = tk.Frame(pane, bg=C["page"])
        pane.add(bot_pane, minsize=120)

        # Button bar — fixed at top of bottom pane, always visible
        btn_row = tk.Frame(bot_pane, bg="#181825", padx=8, pady=5)
        btn_row.pack(fill="x", side="top")
        tk.Button(btn_row, text="▶  Run  (Ctrl+Enter)",
                  command=self._debug_run,
                  font=("Segoe UI",9,"bold"),
                  bg="#a6e3a1", fg="#1e1e2e",
                  relief="flat", bd=0, padx=12, pady=4, cursor="hand2"
                  ).pack(side="left")
        tk.Button(btn_row, text="Clear Code",
                  command=lambda: self._debug_editor.delete("1.0","end"),
                  font=("Segoe UI",9), bg="#313244", fg="#cdd6f4",
                  relief="flat", bd=0, padx=8, pady=4, cursor="hand2"
                  ).pack(side="left", padx=(6,0))
        tk.Button(btn_row, text="Clear Output",
                  command=lambda: [self._debug_out.config(state="normal"),
                                   self._debug_out.delete("1.0","end"),
                                   self._debug_out.config(state="disabled")],
                  font=("Segoe UI",9), bg="#313244", fg="#cdd6f4",
                  relief="flat", bd=0, padx=8, pady=4, cursor="hand2"
                  ).pack(side="left", padx=(4,0))
        tk.Button(btn_row, text="⬇ Install Chromium",
                  command=self._debug_install_chromium,
                  font=("Segoe UI",9,"bold"), bg="#1d4ed8", fg="#bfdbfe",
                  relief="flat", bd=0, padx=10, pady=4, cursor="hand2"
                  ).pack(side="right")
        tk.Label(btn_row, text="Ctrl+Enter = Run",
                 font=("Segoe UI",8), bg="#181825", fg="#45475a"
                 ).pack(side="right", padx=(0,10))

        out_outer = tk.Frame(bot_pane, bg=C["border"], padx=1, pady=1)
        out_outer.pack(fill="both", expand=True, padx=10, pady=(0,8))
        out_inner = tk.Frame(out_outer, bg="#11111b")
        out_inner.pack(fill="both", expand=True)

        out_hdr = tk.Frame(out_inner, bg="#11111b", padx=10, pady=5)
        out_hdr.pack(fill="x")
        tk.Label(out_hdr, text="Output", font=("Segoe UI",9,"bold"),
                 bg="#11111b", fg="#6c7086").pack(side="left")
        self._debug_out_status = tk.Label(out_hdr, text="Ready",
                 font=("Segoe UI",8), bg="#11111b", fg="#6c7086")
        self._debug_out_status.pack(side="right")

        self._debug_out = tk.Text(out_inner,
                 font=("Consolas",10), bg="#11111b", fg="#cdd6f4",
                 relief="flat", bd=0, padx=10, pady=6,
                 state="disabled", wrap="none")
        out_vsb = tk.Scrollbar(out_inner, orient="vertical",
                               command=self._debug_out.yview, bg="#11111b")
        out_hsb = tk.Scrollbar(out_inner, orient="horizontal",
                               command=self._debug_out.xview, bg="#11111b")
        self._debug_out.configure(yscrollcommand=out_vsb.set,
                                   xscrollcommand=out_hsb.set)
        out_vsb.pack(side="right", fill="y")
        out_hsb.pack(side="bottom", fill="x")
        self._debug_out.pack(fill="both", expand=True)

        # Output colour tags
        self._debug_out.tag_configure("ok",    foreground="#a6e3a1")
        self._debug_out.tag_configure("err",   foreground="#f38ba8")

        # Set initial sash position after window is drawn (55% editor / 45% output)
        def _set_sash():
            total = pane.winfo_height()
            if total > 100:
                pane.sash_place(0, 0, int(total * 0.55))
        page.after(200, _set_sash)
        self._debug_out.tag_configure("info",  foreground="#89b4fa")
        self._debug_out.tag_configure("ts",    foreground="#45475a")

    def _debug_install_chromium(self):
        """Install Playwright Chromium browser to permanent location."""
        import os, shutil, subprocess, threading

        pw_path = os.path.join(os.path.expanduser("~"),
                               "AppData", "Local", "ms-playwright")
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = pw_path

        def _write(text, tag="info"):
            self._debug_out.config(state="normal")
            self._debug_out.insert("end", text + "\n", tag)
            self._debug_out.see("end")
            self._debug_out.config(state="disabled")

        def _install():
            self.after(0, lambda: _write("Installing Chromium to: " + pw_path, "info"))
            py = shutil.which("python") or shutil.which("python3") or shutil.which("py")
            if not py:
                self.after(0, lambda: _write(
                    "Python not found in PATH!\n"
                    "Open CMD and run:\n"
                    "  pip install playwright\n"
                    "  playwright install chromium", "err"))
                return
            self.after(0, lambda: _write("Using Python: " + py, "info"))
            try:
                env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=pw_path)
                r = subprocess.run(
                    [py, "-m", "playwright", "install", "chromium"],
                    capture_output=True, text=True, timeout=180, env=env)
                if r.stdout:
                    self.after(0, lambda s=r.stdout[:300]: _write(s, "ok"))
                if r.stderr:
                    self.after(0, lambda s=r.stderr[:300]: _write(s, "warn"))
                if r.returncode == 0:
                    self.after(0, lambda: _write(
                        "✓ Chromium installed! Fetch ERP Activity should work now.", "ok"))
                else:
                    self.after(0, lambda c=r.returncode: _write(
                        "Install failed (code " + str(c) + ")\n"
                        "Try running in CMD: playwright install chromium", "err"))
            except subprocess.TimeoutExpired:
                self.after(0, lambda: _write("Timeout — run manually in CMD", "err"))
            except Exception as e:
                self.after(0, lambda e=str(e): _write("Error: " + e, "err"))

        threading.Thread(target=_install, daemon=True).start()

    def _debug_run(self):
        """Execute code in the debug editor with app in scope."""
        code = self._debug_editor.get("1.0", "end-1c").strip()
        if not code:
            return
        from datetime import datetime as _dtnow
        import io, traceback

        ts = _dtnow.now().strftime("%H:%M:%S")

        def _write(text, tag="info"):
            self._debug_out.config(state="normal")
            self._debug_out.insert("end", text, tag)
            self._debug_out.see("end")
            self._debug_out.config(state="disabled")

        _write("[" + ts + "] Running...\n", "ts")

        # Redirect stdout
        old_stdout = __import__("sys").stdout
        old_stderr = __import__("sys").stderr
        buf = io.StringIO()
        __import__("sys").stdout = buf
        __import__("sys").stderr = buf

        try:
            exec(code, {
                "app":         self,
                "load_config": load_config,
                "save_config": save_config,
                "C":           C,
                "tk":          tk,
                "ttk":         ttk,
                "__builtins__": __builtins__,
            })
            output = buf.getvalue()
            __import__("sys").stdout = old_stdout
            __import__("sys").stderr = old_stderr
            if output:
                _write(output, "ok")
            else:
                _write("✓ Done (no output)\n", "ok")
            self._debug_out_status.config(text="✓ OK", fg="#a6e3a1")
        except BaseException:
            # Catch BaseException (not just Exception) so SystemExit /
            # KeyboardInterrupt from pasted code can't kill the app.
            __import__("sys").stdout = old_stdout
            __import__("sys").stderr = old_stderr
            captured = buf.getvalue()
            if captured:
                _write(captured, "info")
            err_text = traceback.format_exc()
            _write(err_text, "err")
            self._debug_out_status.config(text="✗ Error", fg="#f38ba8")

    def _build_sidebar(self, sb):
        # Logo (changes based on mode)
        logo = tk.Frame(sb, bg=C["sidebar"], pady=14)
        logo.pack(fill="x", padx=14)
        row = tk.Frame(logo, bg=C["sidebar"])
        row.pack(fill="x")
        ico = tk.Frame(row, bg=C["accent_l"], width=38, height=38)
        ico.pack(side="left"); ico.pack_propagate(False)
        _logo_icon = "👥" if HR_MODE else "📦"
        tk.Label(ico, text=_logo_icon, font=("Segoe UI Emoji",16),
                 bg=C["accent_l"]).pack(expand=True)
        info = tk.Frame(row, bg=C["sidebar"])
        info.pack(side="left", padx=(10,0))
        _logo_title = "HR Audit Bot" if HR_MODE else "Odoo Bot"
        _logo_sub = "v5.4 — HR Edition" if HR_MODE else "v5.4 — Green API"
        tk.Label(info, text=_logo_title, font=("Segoe UI",12,"bold"),
                 bg=C["sidebar"], fg=C["text"]).pack(anchor="w")
        tk.Label(info, text=_logo_sub, font=("Segoe UI",8),
                 bg=C["sidebar"], fg=C["text4"]).pack(anchor="w")
        tk.Frame(sb, bg=C["border"], height=1).pack(fill="x")

        self._nav_items = {}
        self._mk_nav_sec(sb, "NAVIGATION")
        self._nav_items["dashboard"] = self._mk_nav(sb, "🏠", "Dashboard",  "dashboard")
        self._nav_items["reports"]   = self._mk_nav(sb, "📊", "Reports",    "reports")
        self._nav_items["settings"]  = self._mk_nav(sb, "⚙️", "Settings",   "settings")

        # Footer
        tk.Frame(sb, bg=C["border"], height=1).pack(side="bottom", fill="x")
        ft = tk.Frame(sb, bg=C["sidebar"], pady=12)
        ft.pack(side="bottom", fill="x", padx=14)

        # Reload button
        tk.Button(ft, text="🔁  Reload App",
                  command=self._reload_app,
                  font=("Segoe UI",9,"bold"),
                  bg="#eef3ff", fg=C["accent"],
                  relief="flat", bd=0, padx=10, pady=5,
                  cursor="hand2",
                  activebackground=C["accent"], activeforeground="white"
                  ).pack(fill="x", pady=(0,8))

        tk.Label(ft, text="STATUS", font=("Segoe UI",8,"bold"),
                 bg=C["sidebar"], fg=C["text5"]).pack(anchor="w")
        self.sb_status = tk.Label(ft, text="● Idle", font=("Segoe UI",9,"bold"),
                 bg=C["sidebar"], fg=C["text4"])
        self.sb_status.pack(anchor="w", pady=(3,0))
        self.sb_queue_badge = tk.Label(ft, text="", font=("Segoe UI",8),
                 bg=C["amber_l"], fg=C["amber"])
        self.sb_queue_badge.pack(anchor="w", pady=(4,0))

    def _mk_nav_sec(self, sb, text):
        tk.Label(sb, text=text, font=("Segoe UI",8,"bold"),
                 bg=C["sidebar"], fg=C["text5"]).pack(
                 anchor="w", padx=16, pady=(12,2))

    def _mk_nav(self, sb, icon, text, page, muted=False):
        outer = tk.Frame(sb, bg=C["sidebar"])
        outer.pack(fill="x")
        bar   = tk.Frame(outer, bg=C["sidebar"], width=3)
        bar.pack(side="left", fill="y")
        inner = tk.Frame(outer, bg=C["sidebar"])
        inner.pack(side="left", fill="x", expand=True)
        row = tk.Frame(inner, bg=C["sidebar"], pady=9)
        row.pack(fill="x", padx=12)
        tk.Label(row, text=icon, font=("Segoe UI Emoji",13),
                 bg=C["sidebar"]).pack(side="left")
        lbl = tk.Label(row, text=" " + text, font=("Segoe UI",10),
                 bg=C["sidebar"], fg=C["text4"] if muted else C["text3"])
        lbl.pack(side="left")

        def _click(e=None):
            self._show_page(page)
        for w in [outer, inner, row, lbl]:
            w.bind("<Button-1>", _click)
            w.bind("<Enter>", lambda e, o=outer, i=inner, r=row, l=lbl:
                   [w.config(bg="#f8faff") for w in [o,i,r,l]])
            w.bind("<Leave>", lambda e, o=outer, i=inner, r=row, l=lbl, p=page:
                   None if self._cur_page == p else
                   [w.config(bg=C["sidebar"]) for w in [o,i,r,l]])
        return (outer, inner, row, lbl, bar)

    def _show_page(self, page):
        self._cur_page = page
        for name, widgets in self._nav_items.items():
            outer, inner, row, lbl, bar = widgets
            if name == page:
                for w in [outer,inner,row,lbl]: w.config(bg="#eef3ff")
                lbl.config(fg=C["accent"], font=("Segoe UI",10,"bold"))
                bar.config(bg=C["accent"])
            else:
                for w in [outer,inner,row,lbl]: w.config(bg=C["sidebar"])
                lbl.config(fg=C["text3"], font=("Segoe UI",10))
                bar.config(bg=C["sidebar"])
        for name, frame in self.pages.items():
            frame.pack(fill="both", expand=True) if name == page else frame.pack_forget()
        if page == "settings":
            fn = getattr(self, "_mapping_page_refresh", None)
            if fn: fn()

    # ── Dashboard Page ────────────────────────────────────────────────────────
    def _build_dashboard_page(self):
        page = tk.Frame(self.main, bg=C["page"])
        self.pages["dashboard"] = page

        tp = tk.Frame(page, bg=C["topbar"], height=44)
        tp.pack(fill="x"); tp.pack_propagate(False)
        tk.Label(tp, text="  Dashboard", font=("Segoe UI",12,"bold"),
                 bg=C["topbar"], fg=C["text"]).pack(side="left", pady=10)
        tk.Frame(page, bg=C["border"], height=1).pack(fill="x")

        _dc = tk.Canvas(page, bg=C["page"], highlightthickness=0)
        _dvs = ttk.Scrollbar(page, orient="vertical", command=_dc.yview)
        _dhs = ttk.Scrollbar(page, orient="horizontal", command=_dc.xview)
        _dc.configure(yscrollcommand=_dvs.set, xscrollcommand=_dhs.set)
        _dhs.pack(side="bottom", fill="x")
        _dvs.pack(side="right", fill="y")
        _dc.pack(side="left", fill="both", expand=True)
        _di = tk.Frame(_dc, bg=C["page"])
        _dw = _dc.create_window((0, 0), window=_di, anchor="nw")
        _di.bind("<Configure>", lambda e: _dc.configure(scrollregion=_dc.bbox("all")))
        _dc.bind("<Configure>", lambda e: _dc.itemconfig(_dw,
                 width=max(_di.winfo_reqwidth(), e.width)))
        _dc.bind_all("<MouseWheel>", lambda e: _dc.yview_scroll(
                     int(-1*(e.delta/120)), "units"))
        page = _di

        # Status + date card row
        cr = tk.Frame(page, bg=C["page"])
        cr.pack(fill="x", padx=14, pady=(12,0))
        cr.columnconfigure(0, weight=1)
        cr.columnconfigure(1, weight=1)

        c1 = self._card(cr, "Report Date", "#2563eb", 0, 0)
        tk.Label(c1, text="Select Date", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w", pady=(0,3))
        self.audit_date = DateEntry(c1, width=16, font=("Segoe UI",10),
                                     date_pattern="dd/mm/yyyy",
                                     background=C["accent"], foreground="white",
                                     headersbackground=C["accent"],
                                     headersforeground="white",
                                     selectbackground=C["accent"])
        self.audit_date.pack(fill="x", pady=(0,10))
        self.audit_date.set_date(date.today())
        btn_row1 = tk.Frame(c1, bg=C["white"])
        btn_row1.pack(fill="x")
        tk.Button(btn_row1, text="Load Odoo Users", command=self._load_audit_users,
                  font=("Segoe UI",9,"bold"), bg=C["accent_l"], fg=C["accent"],
                  relief="flat", bd=0, padx=10, pady=5, cursor="hand2",
                  activebackground=C["accent"], activeforeground="white"
                  ).pack(side="left", padx=(0,6))
        tk.Button(btn_row1, text="Fetch TD Data", command=self._td_fetch,
                  font=("Segoe UI",9,"bold"), bg="#ede9fe", fg="#5b21b6",
                  relief="flat", bd=0, padx=10, pady=5, cursor="hand2",
                  activebackground="#5b21b6", activeforeground="white"
                  ).pack(side="left")
        tk.Button(c1, text="⬇ Download PDF Report", command=self._td_download_pdf,
                  font=("Segoe UI",9,"bold"), bg="#f0fdf4", fg="#166534",
                  relief="flat", bd=0, pady=5, cursor="hand2"
                  ).pack(fill="x", pady=(6,0))

        c2 = self._card(cr, "Quick Navigation", "#0f766e", 0, 1)
        tk.Label(c2, text="Use Reports page to send WhatsApp reminders and view\n"
                          "per-user entry breakdowns.",
                 font=("Segoe UI",9), bg=C["white"], fg=C["text4"],
                 justify="left", wraplength=200).pack(anchor="w", pady=(0,10))
        tk.Button(c2, text="→ Go to Reports",
                  command=lambda: self._show_page("reports"),
                  font=("Segoe UI",9,"bold"), bg=C["green_l"], fg=C["green"],
                  relief="flat", bd=0, pady=5, cursor="hand2"
                  ).pack(fill="x", pady=(0,4))
        tk.Button(c2, text="→ Go to Settings",
                  command=lambda: self._show_page("settings"),
                  font=("Segoe UI",9,"bold"), bg=C["accent_l"], fg=C["accent"],
                  relief="flat", bd=0, pady=5, cursor="hand2"
                  ).pack(fill="x")

        self._current_detail_user = None

        # Combined Report table
        td_outer = tk.Frame(page, bg=C["border"], padx=1, pady=1)
        td_outer.pack(fill="x", padx=14, pady=(8,0))
        td_inner = tk.Frame(td_outer, bg=C["white"])
        td_inner.pack(fill="both", expand=True)
        td_hdr = tk.Frame(td_inner, bg=C["white"], padx=10, pady=6)
        td_hdr.pack(fill="x")
        dot_td = tk.Frame(td_hdr, bg="#7c3aed", width=8, height=8)
        dot_td.pack(side="left", pady=3); dot_td.pack_propagate(False)
        tk.Frame(td_hdr, bg=C["border"], width=1, height=14).pack(side="left", padx=6)
        tk.Label(td_hdr, text="Combined Report — Odoo Actions + TimeDoctor Hours",
                 font=("Segoe UI",9,"bold"), bg=C["white"], fg=C["text"]).pack(side="left")
        tk.Label(td_hdr, text="Odoo", font=("Segoe UI",8,"bold"),
                 bg=C["accent_l"], fg=C["accent"], padx=6, pady=2
                 ).pack(side="right", padx=(4,0))
        tk.Label(td_hdr, text="+", font=("Segoe UI",8),
                 bg=C["white"], fg=C["text4"]).pack(side="right", padx=2)
        tk.Label(td_hdr, text="TimeDoctor", font=("Segoe UI",8,"bold"),
                 bg="#ede9fe", fg="#5b21b6", padx=6, pady=2).pack(side="right")
        tk.Frame(td_inner, bg=C["border"], height=1).pack(fill="x")
        style2 = ttk.Style()
        style2.configure("TD.Treeview", font=("Segoe UI",9), rowheight=20,
                         background=C["input"], fieldbackground=C["input"],
                         foreground=C["text2"])
        style2.configure("TD.Treeview.Heading", font=("Segoe UI",8,"bold"))
        self.td_tree = ttk.Treeview(td_inner, style="TD.Treeview",
                                     columns=("odoo_actions","odoo_status","hours",
                                              "active","idle_pct","nonprod"),
                                     show="tree headings", height=14)
        for col, txt, w, anchor in [
            ("odoo_actions", "Odoo Actions",        100, "center"),
            ("odoo_status",  "Odoo Status",          90, "center"),
            ("hours",        "Hours Worked",         95, "center"),
            ("active",       "Active Time",          85, "center"),
            ("idle_pct",     "Idle (mins %)",        110, "center"),
            ("nonprod",      "Non-Productive Time", 140, "center"),
        ]:
            self.td_tree.heading(col, text=txt)
            self.td_tree.column(col, width=w, anchor=anchor, stretch=False)
        self.td_tree.column("#0", width=140, stretch=False)
        self.td_tree.heading("#0", text="Employee")
        td_vsb = ttk.Scrollbar(td_inner, orient="vertical", command=self.td_tree.yview)
        self.td_tree.configure(yscrollcommand=td_vsb.set)
        td_vsb.pack(side="right", fill="y")
        self._add_tree_search(td_inner, self.td_tree, "Search employee...")
        self.td_tree.pack(fill="both", expand=True)
        self.td_tree.tag_configure("good",   background=C["green_l"],  foreground=C["green"])
        self.td_tree.tag_configure("warn",   background=C["amber_l"],  foreground=C["amber"])
        self.td_tree.tag_configure("danger", background=C["red_l"],    foreground=C["red"])
        self.td_tree.tag_configure("absent", background=C["input"],    foreground=C["text4"])
        self.td_tree.tag_configure("normal", background=C["input"],    foreground=C["text2"])
        style2.configure("TD.Treeview.Heading", background=C["accent_l"], foreground=C["accent"])
        self.td_tree.insert("", "end", text="-- Click 'Fetch TD Data' to load --",
                             values=("","","","","",""), tags=("normal",))
        self.td_tree.bind("<Double-1>", self._td_idle_drilldown)

        self.audit_progress = ttk.Progressbar(page, mode="indeterminate",
                                               style="TProgressbar")
        self.audit_progress.pack(fill="x", padx=14, pady=(8,4))
        self.audit_log_box = self._log_panel(page, "dashboard")

    # ── Reports Page ──────────────────────────────────────────────────────────
    def _build_reports_page(self):
        page = tk.Frame(self.main, bg=C["page"])
        self.pages["reports"] = page

        tp = tk.Frame(page, bg=C["topbar"], height=44)
        tp.pack(fill="x"); tp.pack_propagate(False)
        tk.Label(tp, text="  Reports", font=("Segoe UI",12,"bold"),
                 bg=C["topbar"], fg=C["text"]).pack(side="left", pady=10)
        tk.Frame(page, bg=C["border"], height=1).pack(fill="x")

        _rc = tk.Canvas(page, bg=C["page"], highlightthickness=0)
        _rvs = ttk.Scrollbar(page, orient="vertical", command=_rc.yview)
        _rhs = ttk.Scrollbar(page, orient="horizontal", command=_rc.xview)
        _rc.configure(yscrollcommand=_rvs.set, xscrollcommand=_rhs.set)
        _rhs.pack(side="bottom", fill="x")
        _rvs.pack(side="right", fill="y")
        _rc.pack(side="left", fill="both", expand=True)
        _ri = tk.Frame(_rc, bg=C["page"])
        _rw = _rc.create_window((0, 0), window=_ri, anchor="nw")
        _ri.bind("<Configure>", lambda e: _rc.configure(scrollregion=_rc.bbox("all")))
        _rc.bind("<Configure>", lambda e: _rc.itemconfig(_rw,
                 width=max(_ri.winfo_reqwidth(), e.width)))
        _rc.bind_all("<MouseWheel>", lambda e: _rc.yview_scroll(
                     int(-1*(e.delta/120)), "units"))
        page = _ri

        cr = tk.Frame(page, bg=C["page"])
        cr.pack(fill="x", padx=14, pady=(12,0))
        cr.columnconfigure(0, weight=0, minsize=220)
        cr.columnconfigure(1, weight=1)

        # Card 1 — Audit Settings
        c1 = self._card(cr, "Audit Settings", "#7c3aed", 0, 0)
        tk.Label(c1, text="Custom Note (appended to reminder)",
                 font=("Segoe UI",9), bg=C["white"], fg=C["text4"]).pack(anchor="w", pady=(0,2))
        self.audit_note_text = tk.Text(c1, font=("Consolas",9), bg=C["input"],
                                        fg=C["text2"], insertbackground=C["accent"],
                                        relief="flat", bd=0, height=2, wrap="word",
                                        highlightthickness=1, highlightbackground=C["border"])
        self.audit_note_text.pack(fill="x")
        tk.Label(c1, text="Message Template",
                 font=("Segoe UI",9,"bold"), bg=C["white"], fg=C["text"]).pack(anchor="w", pady=(8,2))
        _cfg_a = load_config()
        _saved_a = _cfg_a.get("audit_templates") or {}
        if not _saved_a:
            _saved_a = {k: dict(v) for k, v in DEFAULT_AUDIT_TEMPLATES.items()}
        self._audit_templates = _saved_a
        _sel_a = _cfg_a.get("audit_template_selected", "Standard")
        if _sel_a not in _saved_a:
            _sel_a = next(iter(_saved_a.keys()), "Standard")
        tpl_row = tk.Frame(c1, bg=C["white"])
        tpl_row.pack(fill="x", pady=(0,4))
        self.audit_tpl_var = tk.StringVar(value=_sel_a)
        self.audit_tpl_dropdown = ttk.Combobox(
            tpl_row, textvariable=self.audit_tpl_var,
            values=list(_saved_a.keys()), state="readonly",
            font=("Segoe UI",9), width=18)
        self.audit_tpl_dropdown.pack(side="left", padx=(0,4))
        self.audit_tpl_dropdown.bind("<<ComboboxSelected>>", self._audit_on_template_change)
        tk.Button(tpl_row, text="Edit", command=self._audit_edit_templates,
                  font=("Segoe UI",8), bg=C["input"], fg=C["text2"], bd=0,
                  padx=8, pady=2, cursor="hand2").pack(side="left", padx=2)
        tk.Button(tpl_row, text="Preview", command=self._audit_preview_template,
                  font=("Segoe UI",8,"bold"), bg=C["accent_l"], fg=C["accent"], bd=0,
                  padx=8, pady=2, cursor="hand2").pack(side="left", padx=2)

        # Card 2 — User selector
        c2 = self._card(cr, "Odoo Users", "#0f766e", 0, 1)
        tk.Label(c2, text="Click Load to fetch users active on the selected date.",
                 font=("Segoe UI",8), bg=C["white"], fg=C["text4"],
                 wraplength=200, justify="left").pack(anchor="w", pady=(0,6))
        tk.Button(c2, text="Load Active Users for Date",
                  command=self._load_audit_users,
                  font=("Segoe UI",9,"bold"), bg=C["accent_l"], fg=C["accent"],
                  relief="flat", bd=0, pady=5, cursor="hand2",
                  activebackground=C["accent"], activeforeground="white"
                  ).pack(fill="x", pady=(0,6))
        tk.Label(c2, text="Active users on selected date (Ctrl+click):",
                 font=("Segoe UI",8), bg=C["white"], fg=C["text4"]).pack(anchor="w", pady=(0,2))
        lb_frame = tk.Frame(c2, bg=C["border"], padx=1, pady=1)
        lb_frame.pack(fill="both", expand=True)
        self.audit_user_lb = tk.Listbox(lb_frame, font=("Segoe UI",9),
                                         bg=C["input"], fg=C["text2"],
                                         selectbackground=C["accent"],
                                         selectforeground="white",
                                         relief="flat", bd=0,
                                         selectmode=tk.MULTIPLE, height=7,
                                         activestyle="none")
        self.audit_user_lb.pack(fill="both", expand=True, padx=4, pady=4)
        self.audit_user_lb.insert("end", "-- Click Load Users first --")
        sb2 = tk.Frame(c2, bg=C["white"])
        sb2.pack(fill="x", pady=(4,0))
        tk.Button(sb2, text="Select All", command=self._audit_select_all,
                  font=("Segoe UI",8), bg=C["green_l"], fg=C["green"],
                  relief="flat", bd=0, padx=8, pady=3, cursor="hand2"
                  ).pack(side="left", padx=(0,4))
        tk.Button(sb2, text="Clear All", command=self._audit_clear_all,
                  font=("Segoe UI",8), bg=C["red_l"], fg=C["red"],
                  relief="flat", bd=0, padx=8, pady=3, cursor="hand2"
                  ).pack(side="left")
        self.audit_sel_lbl = tk.Label(sb2, text="0 selected",
                 font=("Segoe UI",8), bg=C["white"], fg=C["text4"])
        self.audit_sel_lbl.pack(side="right")
        self.audit_user_lb.bind("<<ListboxSelect>>", self._on_audit_user_select)

        # Entry breakdown + non-active panel
        mid_row = tk.Frame(page, bg=C["page"])
        mid_row.pack(fill="both", expand=True, padx=14, pady=(8,0))
        mid_row.columnconfigure(0, weight=1)
        mid_row.columnconfigure(1, weight=0, minsize=260)
        mid_row.rowconfigure(0, weight=1)

        bd_outer = tk.Frame(mid_row, bg=C["border"], padx=1, pady=1)
        bd_outer.grid(row=0, column=0, sticky="nsew", padx=(0,5))
        bd_inner = tk.Frame(bd_outer, bg=C["white"])
        bd_inner.pack(fill="both", expand=True)
        det_hdr = tk.Frame(bd_inner, bg=C["white"], padx=10, pady=6)
        det_hdr.pack(fill="x")
        dot_bd = tk.Frame(det_hdr, bg="#7c3aed", width=8, height=8)
        dot_bd.pack(side="left", pady=3); dot_bd.pack_propagate(False)
        tk.Frame(det_hdr, bg=C["border"], width=1, height=14).pack(side="left", padx=6)
        tk.Label(det_hdr, text="Entry breakdown (click user in list above)",
                 font=("Segoe UI",9,"bold"), bg=C["white"], fg=C["text"]).pack(side="left")
        self.det_view_var = tk.StringVar(value="grouped")
        tk.Radiobutton(det_hdr, text="By module function", variable=self.det_view_var,
                       value="modfunc", font=("Segoe UI",8), bg=C["white"],
                       fg="#7c3aed", selectcolor=C["white"],
                       command=self._refresh_audit_detail).pack(side="right", padx=(4,0))
        tk.Radiobutton(det_hdr, text="By module", variable=self.det_view_var,
                       value="grouped", font=("Segoe UI",8), bg=C["white"],
                       fg=C["accent"], selectcolor=C["white"],
                       command=self._refresh_audit_detail).pack(side="right", padx=(4,0))
        tk.Radiobutton(det_hdr, text="By time", variable=self.det_view_var,
                       value="timeline", font=("Segoe UI",8), bg=C["white"],
                       fg=C["text3"], selectcolor=C["white"],
                       command=self._refresh_audit_detail).pack(side="right")
        tk.Frame(det_hdr, bg=C["border"], width=1, height=14).pack(side="right", padx=(8,0))
        tk.Button(det_hdr, text="Unfold All", command=self._audit_unfold_all,
                  font=("Segoe UI",8,"bold"), bg=C["green_l"], fg=C["green"],
                  relief="flat", bd=0, padx=8, pady=2, cursor="hand2"
                  ).pack(side="right", padx=(0,4))
        tk.Button(det_hdr, text="Fold All", command=self._audit_fold_all,
                  font=("Segoe UI",8,"bold"), bg=C["input"], fg=C["text3"],
                  relief="flat", bd=0, padx=8, pady=2, cursor="hand2"
                  ).pack(side="right", padx=(0,2))
        tk.Frame(bd_inner, bg=C["border"], height=1).pack(fill="x")
        det_f = tk.Frame(bd_inner, bg=C["input"])
        det_f.pack(fill="both", expand=True)
        style = ttk.Style()
        style.configure("Audit.Treeview", font=("Consolas",8), rowheight=18,
                        background=C["input"], fieldbackground=C["input"],
                        foreground=C["text2"])
        style.configure("Audit.Treeview.Heading", font=("Segoe UI",8,"bold"),
                        background=C["accent_l"], foreground=C["accent"])
        self.audit_tree = ttk.Treeview(det_f, style="Audit.Treeview",
                                        columns=("date","time","detail"),
                                        show="tree headings", height=10)
        self.audit_tree.heading("#0",     text="Module / Record")
        self.audit_tree.heading("date",   text="Date")
        self.audit_tree.heading("time",   text="Time (PKT)")
        self.audit_tree.heading("detail", text="Document Type")
        self.audit_tree.column("#0",     width=260, stretch=True)
        self.audit_tree.column("date",   width=90,  stretch=False)
        self.audit_tree.column("time",   width=70,  stretch=False)
        self.audit_tree.column("detail", width=180, stretch=True)
        vsb2 = ttk.Scrollbar(det_f, orient="vertical", command=self.audit_tree.yview)
        self.audit_tree.configure(yscrollcommand=vsb2.set)
        vsb2.pack(side="right", fill="y")
        self.audit_tree.pack(fill="both", expand=True)
        self.audit_tree.tag_configure("module",  foreground=C["accent"],
                                       font=("Segoe UI",8,"bold"), background=C["accent_l"])
        self.audit_tree.tag_configure("modfunc", foreground="#5b21b6",
                                       font=("Segoe UI",8,"bold"), background="#ede9fe")
        self.audit_tree.tag_configure("record",     foreground=C["text2"])
        self.audit_tree.tag_configure("fnentry",    foreground=C["text3"], background="#faf9ff")
        self.audit_tree.tag_configure("time_entry", foreground=C["text3"])

        na_outer = tk.Frame(mid_row, bg=C["border"], padx=1, pady=1)
        na_outer.grid(row=0, column=1, sticky="nsew")
        na_inner = tk.Frame(na_outer, bg=C["white"])
        na_inner.pack(fill="both", expand=True)
        na_hdr = tk.Frame(na_inner, bg=C["white"], padx=10, pady=6)
        na_hdr.pack(fill="x")
        dot_na = tk.Frame(na_hdr, bg=C["red"], width=8, height=8)
        dot_na.pack(side="left", pady=3); dot_na.pack_propagate(False)
        tk.Frame(na_hdr, bg=C["border"], width=1, height=14).pack(side="left", padx=6)
        tk.Label(na_hdr, text="Non-active today",
                 font=("Segoe UI",9,"bold"), bg=C["white"], fg=C["text"]).pack(side="left")
        tk.Frame(na_inner, bg=C["border"], height=1).pack(fill="x")
        tk.Label(na_inner, text="Active last 7 days — absent today (Ctrl+click)",
                 font=("Segoe UI",8), bg=C["white"], fg=C["text4"],
                 pady=4).pack(anchor="w", padx=10)
        na_lf = tk.Frame(na_inner, bg=C["border"], padx=1, pady=1)
        na_lf.pack(fill="both", expand=True, padx=8, pady=(0,4))
        self.na_listbox = tk.Listbox(na_lf, font=("Segoe UI",9),
                                      bg=C["input"], fg=C["text2"],
                                      selectbackground=C["red_l"],
                                      selectforeground=C["red"],
                                      relief="flat", bd=0,
                                      selectmode=tk.MULTIPLE,
                                      activestyle="none", height=8)
        na_vsb = ttk.Scrollbar(na_lf, orient="vertical", command=self.na_listbox.yview)
        self.na_listbox.configure(yscrollcommand=na_vsb.set)
        na_vsb.pack(side="right", fill="y")
        self.na_listbox.pack(fill="both", expand=True, padx=4, pady=4)
        self.na_listbox.insert("end", "-- Load users first --")
        self.na_listbox.bind("<<ListboxSelect>>", self._on_na_select)
        na_btn_row = tk.Frame(na_inner, bg=C["white"])
        na_btn_row.pack(fill="x", padx=8, pady=(0,4))
        tk.Button(na_btn_row, text="Select All", command=self._na_select_all,
                  font=("Segoe UI",8), bg=C["red_l"], fg=C["red"],
                  relief="flat", bd=0, padx=8, pady=3, cursor="hand2"
                  ).pack(side="left", padx=(0,4))
        tk.Button(na_btn_row, text="Clear All", command=self._na_clear_all,
                  font=("Segoe UI",8), bg=C["input"], fg=C["text3"],
                  relief="flat", bd=0, padx=8, pady=3, cursor="hand2"
                  ).pack(side="left")
        self.na_sel_lbl = tk.Label(na_btn_row, text="0 selected",
                 font=("Segoe UI",8), bg=C["white"], fg=C["text4"])
        self.na_sel_lbl.pack(side="right")
        self._non_active_users = []

        bf = tk.Frame(page, bg=C["page"])
        bf.pack(fill="x", padx=14, pady=(8,8))
        for txt, cmd, bg, fg in [
            ("Fetch ERP Data",        self._audit_fetch_erp,  "#fff7ed",    "#c2410c"),
            ("Run Audit for Date",    self._run_audit,        C["green_l"], C["green"]),
            ("Start Audit Scheduler", self._start_audit,      C["amber_l"], C["amber"]),
            ("Stop",                  self._stop,             C["red_l"],   C["red"]),
        ]:
            tk.Button(bf, text=txt, command=cmd, font=("Segoe UI",10,"bold"),
                      bg=bg, fg=fg, relief="flat", bd=0, padx=14, pady=7,
                      cursor="hand2", activebackground=fg, activeforeground="white"
                      ).pack(side="left", padx=(0,8))

    # ── Settings Page ─────────────────────────────────────────────────────────
    def _build_settings_page(self):
        page = tk.Frame(self.main, bg=C["page"])
        self.pages["settings"] = page

        # ── Hidden vars for legacy _load_fields / _collect / _start / _run_date ──
        self.f_ginstance = tk.StringVar()
        self.f_gtoken    = tk.StringVar()
        self.f_hour      = tk.StringVar(value="05")
        self.f_min       = tk.StringVar(value="00")
        self.auto_today  = tk.BooleanVar(value=True)
        self.watch_var   = tk.BooleanVar(value=False)
        self.f_interval  = tk.StringVar(value="5")
        _hidden_frame = tk.Frame(page)
        self.note_text   = tk.Text(_hidden_frame, height=2)
        self.date_picker = DateEntry(_hidden_frame, date_pattern="dd/mm/yyyy")
        self.date_picker.set_date(date.today())

        # ── Top bar ────────────────────────────────────────────────────────
        tp = tk.Frame(page, bg=C["topbar"], height=48)
        tp.pack(fill="x"); tp.pack_propagate(False)
        tk.Label(tp, text="  Settings", font=("Segoe UI",13,"bold"),
                 bg=C["topbar"], fg=C["text"]).pack(side="left", padx=(4,0), pady=12)
        self.co_badge = tk.Label(tp, text="All Companies",
                 font=("Segoe UI",8), bg=C["accent_l"], fg=C["accent"],
                 padx=8, pady=2)
        self.co_badge.pack(side="left", padx=(10,0))
        self.tb_status = tk.Label(tp, text="",
                 font=("Segoe UI",9), bg=C["topbar"], fg=C["text4"])
        self.tb_status.pack(side="right", padx=16)
        tk.Frame(page, bg=C["border"], height=1).pack(fill="x")
        page = self._make_scrollable(page)

        # ── Section header helper ──────────────────────────────────────────
        def _sec_header(parent, dot_color, title, subtitle=""):
            hdr = tk.Frame(parent, bg=C["page"])
            hdr.pack(fill="x", padx=20, pady=(20,8))
            dot = tk.Frame(hdr, bg=dot_color, width=10, height=10)
            dot.pack(side="left", pady=4); dot.pack_propagate(False)
            tk.Frame(hdr, bg=C["border"], width=1, height=18).pack(side="left", padx=8)
            tk.Label(hdr, text=title, font=("Segoe UI",11,"bold"),
                     bg=C["page"], fg=C["text"]).pack(side="left")
            if subtitle:
                tk.Label(hdr, text=subtitle, font=("Segoe UI",9),
                         bg=C["page"], fg=C["text4"]).pack(side="left", padx=10)

        # ── Connections row ────────────────────────────────────────────────
        _sec_header(page, C["accent"], "Connections", "Configure Odoo and TimeDoctor")

        conn_row = tk.Frame(page, bg=C["page"])
        conn_row.pack(fill="x", padx=20, pady=(0,4))
        conn_row.columnconfigure(0, weight=1)
        conn_row.columnconfigure(1, weight=1)

        # Odoo Connection card
        odoo_card = self._card(conn_row, "Odoo Connection", C["accent"], 0, 0)
        self.f_host = self._field(odoo_card, "Host URL")
        self.f_db   = self._field(odoo_card, "Database")
        self.f_user = self._field(odoo_card, "Username")
        self.f_pass = self._field(odoo_card, "Password", show="*")

        tk.Frame(odoo_card, bg=C["border"], height=1).pack(fill="x", pady=(10,6))
        tk.Label(odoo_card, text="Company Filter", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w", pady=(0,4))
        comp_row = tk.Frame(odoo_card, bg=C["white"])
        comp_row.pack(fill="x"); comp_row.columnconfigure(0, weight=1)
        self.company_var = tk.StringVar(value="All Companies")
        self.company_cb  = ttk.Combobox(comp_row, textvariable=self.company_var,
                                         state="readonly", font=("Segoe UI",10))
        self.company_cb["values"] = ["All Companies"]
        self.company_cb.grid(row=0, column=0, sticky="ew", ipady=3)
        self.company_cb.bind("<<ComboboxSelected>>", self._on_company_select)
        tk.Button(comp_row, text="Load", command=self._load_companies,
                  font=("Segoe UI",9,"bold"), bg=C["accent"], fg="white",
                  relief="flat", bd=0, padx=12, pady=5, cursor="hand2"
                  ).grid(row=0, column=1, padx=(8,0))

        tk.Frame(odoo_card, bg=C["border"], height=1).pack(fill="x", pady=(10,8))
        odoo_btn_row = tk.Frame(odoo_card, bg=C["white"])
        odoo_btn_row.pack(fill="x")
        tk.Button(odoo_btn_row, text="Save Config", command=self._save,
                  font=("Segoe UI",9,"bold"), bg=C["accent"], fg="white",
                  relief="flat", bd=0, padx=14, pady=6, cursor="hand2",
                  activebackground="#1d4ed8", activeforeground="white"
                  ).pack(side="left", padx=(0,8))
        tk.Button(odoo_btn_row, text="Test Connection", command=self._test_conn,
                  font=("Segoe UI",9,"bold"), bg=C["accent_l"], fg=C["accent"],
                  relief="flat", bd=0, padx=14, pady=6, cursor="hand2"
                  ).pack(side="left")

        # TimeDoctor Credentials card
        td_card = self._card(conn_row, "TimeDoctor Credentials", "#5b21b6", 0, 1)

        td_status_row = tk.Frame(td_card, bg=C["white"])
        td_status_row.pack(fill="x", pady=(0,10))
        tk.Label(td_status_row, text="Connection Status",
                 font=("Segoe UI",9,"bold"), bg=C["white"], fg=C["text"]).pack(side="left")
        self.td_conn_lbl = tk.Label(td_status_row, text="Not connected",
                 font=("Segoe UI",8), bg=C["red_l"], fg=C["red"], padx=8, pady=3)
        self.td_conn_lbl.pack(side="right")

        tk.Label(td_card, text="Email", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w", pady=(0,3))
        self.td_email_var = tk.StringVar(value=load_config().get("td_email",""))
        tk.Entry(td_card, textvariable=self.td_email_var,
                 font=("Segoe UI",10), bg=C["input"], fg=C["text2"],
                 relief="flat", bd=0,
                 highlightthickness=1, highlightbackground=C["border"]
                 ).pack(fill="x", ipady=5, pady=(0,8))

        tk.Label(td_card, text="Password", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w", pady=(0,3))
        self.td_pass_var = tk.StringVar(value=load_config().get("td_pass",""))
        tk.Entry(td_card, textvariable=self.td_pass_var,
                 font=("Segoe UI",10), bg=C["input"], fg=C["text2"],
                 show="*", relief="flat", bd=0,
                 highlightthickness=1, highlightbackground=C["border"]
                 ).pack(fill="x", ipady=5)

        self.td_company_var = tk.StringVar(value=load_config().get("td_company",""))
        self.td_token_var   = tk.StringVar(value=load_config().get("td_token",""))
        self.td_cookie_var  = tk.StringVar()

        tk.Frame(td_card, bg=C["border"], height=1).pack(fill="x", pady=(12,10))
        tk.Button(td_card, text="Login via Browser (Playwright)",
                  command=self._td_load,
                  font=("Segoe UI",9,"bold"), bg="#ede9fe", fg="#5b21b6",
                  relief="flat", bd=0, padx=14, pady=7, cursor="hand2",
                  activebackground="#5b21b6", activeforeground="white"
                  ).pack(fill="x")
        self.td_info_lbl = tk.Label(td_card,
                 text="Enter credentials above, then click Login. A browser window will open — complete any 2FA, then return to the app.",
                 font=("Segoe UI",8), bg=C["white"], fg=C["text4"],
                 wraplength=240, justify="left")
        self.td_info_lbl.pack(anchor="w", pady=(8,0))

        # ── Progress + Log ─────────────────────────────────────────────────
        self.progress = ttk.Progressbar(page, mode="indeterminate", style="TProgressbar")
        self.progress.pack(fill="x", padx=20, pady=(16,4))
        self.log_box = self._log_panel(page, "settings")

        # ── User Mapping section ───────────────────────────────────────────
        tk.Frame(page, bg=C["border"], height=1).pack(fill="x", padx=20, pady=(12,0))
        _sec_header(page, C["green"], "User Mapping",
                    "Link TimeDoctor names to Odoo accounts for combined reports")

        hint = tk.Frame(page, bg="#f0fdf4", padx=14, pady=8)
        hint.pack(fill="x", padx=20, pady=(0,10))
        tk.Frame(hint, bg=C["green"], width=3).pack(side="left", fill="y", padx=(0,10))
        tk.Label(hint,
                 text="Select one user from each list, then click Link.  Mapped users appear in green showing their pairing.",
                 font=("Segoe UI",9), bg="#f0fdf4", fg="#166534",
                 justify="left", wraplength=700).pack(side="left", anchor="w")

        map_area = tk.Frame(page, bg=C["page"])
        map_area.pack(fill="both", expand=True, padx=20, pady=(0,20))
        map_area.columnconfigure(0, weight=1)
        map_area.columnconfigure(1, weight=0, minsize=120)
        map_area.columnconfigure(2, weight=1)
        map_area.rowconfigure(0, weight=1)

        # Odoo Users list
        odoo_out = tk.Frame(map_area, bg=C["border"], padx=1, pady=1)
        odoo_out.grid(row=0, column=0, sticky="nsew", padx=(0,6))
        odoo_in = tk.Frame(odoo_out, bg=C["white"])
        odoo_in.pack(fill="both", expand=True)
        odoo_hdr = tk.Frame(odoo_in, bg=C["accent_l"], padx=12, pady=8)
        odoo_hdr.pack(fill="x")
        tk.Label(odoo_hdr, text="Odoo Users", font=("Segoe UI",10,"bold"),
                 bg=C["accent_l"], fg=C["accent"]).pack(side="left")
        odoo_cnt = tk.Label(odoo_hdr, text="", font=("Segoe UI",8),
                 bg=C["accent_l"], fg=C["accent"])
        odoo_cnt.pack(side="right")
        tk.Frame(odoo_in, bg=C["border"], height=1).pack(fill="x")
        odoo_lb_frame = tk.Frame(odoo_in, bg=C["white"])
        odoo_lb_frame.pack(fill="both", expand=True, padx=4, pady=4)
        _o_vsb = ttk.Scrollbar(odoo_lb_frame, orient="vertical")
        _o_vsb.pack(side="right", fill="y")
        self._mapping_odoo_lb = tk.Listbox(odoo_lb_frame,
                                            font=("Segoe UI",9),
                                            bg=C["white"], fg=C["text2"],
                                            selectbackground=C["accent_l"],
                                            selectforeground=C["accent"],
                                            relief="flat", bd=0,
                                            activestyle="none", height=16,
                                            selectmode=tk.SINGLE,
                                            yscrollcommand=_o_vsb.set)
        _o_vsb.config(command=self._mapping_odoo_lb.yview)
        self._mapping_odoo_lb.pack(fill="both", expand=True)

        # Center action buttons
        ctr = tk.Frame(map_area, bg=C["page"])
        ctr.grid(row=0, column=1, sticky="ns", padx=6)
        tk.Label(ctr, text="", bg=C["page"]).pack(expand=True)
        tk.Button(ctr, text="Link",
                  command=lambda: self._mapping_link(),
                  font=("Segoe UI",9,"bold"), bg=C["green"], fg="white",
                  relief="flat", bd=0, padx=16, pady=8, cursor="hand2",
                  activebackground="#16a34a", activeforeground="white",
                  width=10
                  ).pack(pady=(0,8))
        tk.Button(ctr, text="Unlink",
                  command=lambda: self._mapping_unlink(),
                  font=("Segoe UI",9,"bold"), bg=C["red_l"], fg=C["red"],
                  relief="flat", bd=0, padx=16, pady=8, cursor="hand2",
                  width=10
                  ).pack(pady=(0,8))
        tk.Frame(ctr, bg=C["border"], height=1, width=80).pack(pady=4)
        tk.Button(ctr, text="Load All\nOdoo Users",
                  command=lambda: self._mapping_load_all_odoo(),
                  font=("Segoe UI",8,"bold"), bg=C["accent_l"], fg=C["accent"],
                  relief="flat", bd=0, padx=10, pady=6, cursor="hand2",
                  width=10
                  ).pack()
        tk.Label(ctr, text="", bg=C["page"]).pack(expand=True)

        # TimeDoctor Employees list
        td_out = tk.Frame(map_area, bg=C["border"], padx=1, pady=1)
        td_out.grid(row=0, column=2, sticky="nsew", padx=(6,0))
        td_in = tk.Frame(td_out, bg=C["white"])
        td_in.pack(fill="both", expand=True)
        td_hdr = tk.Frame(td_in, bg="#ede9fe", padx=12, pady=8)
        td_hdr.pack(fill="x")
        tk.Label(td_hdr, text="TimeDoctor Employees", font=("Segoe UI",10,"bold"),
                 bg="#ede9fe", fg="#5b21b6").pack(side="left")
        td_cnt = tk.Label(td_hdr, text="", font=("Segoe UI",8),
                 bg="#ede9fe", fg="#5b21b6")
        td_cnt.pack(side="right")
        tk.Frame(td_in, bg=C["border"], height=1).pack(fill="x")
        td_lb_frame = tk.Frame(td_in, bg=C["white"])
        td_lb_frame.pack(fill="both", expand=True, padx=4, pady=4)
        _td_vsb = ttk.Scrollbar(td_lb_frame, orient="vertical")
        _td_vsb.pack(side="right", fill="y")
        self._mapping_td_lb = tk.Listbox(td_lb_frame,
                                          font=("Segoe UI",9),
                                          bg=C["white"], fg=C["text2"],
                                          selectbackground="#ede9fe",
                                          selectforeground="#5b21b6",
                                          relief="flat", bd=0,
                                          activestyle="none", height=16,
                                          selectmode=tk.SINGLE,
                                          yscrollcommand=_td_vsb.set)
        _td_vsb.config(command=self._mapping_td_lb.yview)
        self._mapping_td_lb.pack(fill="both", expand=True)

        _SYS = {"odoobot","__system__","public user","administrator",
                "portal","odoo bot","admin"}

        def _get_odoo_list():
            src = getattr(self, "_mapping_all_odoo", None)
            if src:
                return src
            return [u for u in getattr(self, "_audit_users", [])
                    if (u.get("login","") or "").strip().lower() not in _SYS]

        def _mapping_page_refresh():
            mapping  = load_td_mapping()
            email_to_td = {v.strip().lower(): k for k, v in mapping.items()}
            odoo_list = _get_odoo_list()
            self._mapping_odoo_lb.delete(0, "end")
            for u in odoo_list:
                lg    = (u.get("login","") or "").strip().lower()
                name  = u.get("name","")
                td_nm = email_to_td.get(lg,"")
                if td_nm:
                    self._mapping_odoo_lb.insert("end", "[Linked] " + name + "  ->  " + td_nm)
                    self._mapping_odoo_lb.itemconfig("end", fg=C["green"])
                else:
                    self._mapping_odoo_lb.insert("end", name)
            odoo_cnt.config(text=str(len(odoo_list)) + " users")

            td_names = sorted(
                [n for n in getattr(self, "_td_id_name", {}).values()
                 if n.strip() and n.strip().lower() not in _SYS])
            self._mapping_td_lb.delete(0, "end")
            for name in td_names:
                em = mapping.get(name,"").strip().lower()
                if em:
                    odoo_nm = em
                    for u in odoo_list:
                        if (u.get("login","") or "").strip().lower() == em:
                            odoo_nm = u.get("name", em); break
                    self._mapping_td_lb.insert("end", "[Linked] " + name + "  ->  " + odoo_nm)
                    self._mapping_td_lb.itemconfig("end", fg=C["green"])
                else:
                    self._mapping_td_lb.insert("end", name)
            td_cnt.config(text=str(len(td_names)) + " users")

        self._mapping_page_refresh = _mapping_page_refresh

        def _mapping_link():
            odoo_list = _get_odoo_list()
            td_sel   = self._mapping_td_lb.curselection()
            odoo_sel = self._mapping_odoo_lb.curselection()
            if not td_sel or not odoo_sel:
                from tkinter import messagebox
                messagebox.showwarning("Select Both",
                    "Select one TD employee and one Odoo user.")
                return
            td_raw   = self._mapping_td_lb.get(td_sel[0])
            odoo_raw = self._mapping_odoo_lb.get(odoo_sel[0])
            td_name   = td_raw.replace("[Linked] ","").split("  ->  ")[0].strip()
            odoo_name = odoo_raw.replace("[Linked] ","").split("  ->  ")[0].strip()
            odoo_login = ""
            for u in odoo_list:
                if u.get("name","") == odoo_name:
                    odoo_login = (u.get("login","") or "").strip()
                    break
            if not odoo_login:
                from tkinter import messagebox
                messagebox.showerror("No Email",
                    "Could not find Odoo login for selected user.")
                return
            mapping = load_td_mapping()
            mapping[td_name] = odoo_login
            save_td_mapping(mapping)
            _mapping_page_refresh()
            self._td_rebuild_combined_report()
            self.audit_log("Linked: " + td_name + " -> " + odoo_login, "ok")

        def _mapping_unlink():
            td_sel = self._mapping_td_lb.curselection()
            if not td_sel:
                return
            td_raw  = self._mapping_td_lb.get(td_sel[0])
            td_name = td_raw.replace("[Linked] ","").split("  ->  ")[0].strip()
            mapping = load_td_mapping()
            if td_name in mapping:
                del mapping[td_name]
                save_td_mapping(mapping)
            _mapping_page_refresh()
            self._td_rebuild_combined_report()
            self.audit_log("Unlinked: " + td_name, "warn")

        def _mapping_load_all_odoo():
            cfg = load_config()
            if not cfg.get("odoo_host"):
                self.audit_log("Save Odoo credentials first.", "warn")
                return
            self.audit_log("Loading all Odoo users...", "info")
            import threading
            def _r():
                try:
                    uid, models, _ = odoo_auth(cfg)
                    all_u = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
                        "res.users","search_read",
                        [[["active","=",True],["share","=",False]]],
                        {"fields":["id","name","login"], "limit":1000})
                    filtered = [u for u in all_u
                                if (u.get("login","") or "").strip().lower() not in _SYS]
                    self._mapping_all_odoo = filtered
                    self.after(0, _mapping_page_refresh)
                    self.after(0, lambda: self.audit_log(
                        "Loaded " + str(len(filtered)) + " Odoo users.", "ok"))
                except Exception as e:
                    self.after(0, lambda e=str(e): self.audit_log(
                        "Odoo load error: " + e, "err"))
            threading.Thread(target=_r, daemon=True).start()

        self._mapping_link          = _mapping_link
        self._mapping_unlink        = _mapping_unlink
        self._mapping_load_all_odoo = _mapping_load_all_odoo

    # ── PO Page ───────────────────────────────────────────────────────────────
    def _build_po_page(self):
        page = tk.Frame(self.main, bg=C["page"])
        self.pages["po"] = page

        # Topbar
        tp = tk.Frame(page, bg=C["topbar"], height=44)
        tp.pack(fill="x"); tp.pack_propagate(False)
        tk.Label(tp, text="  Purchase Orders", font=("Segoe UI",12,"bold"),
                 bg=C["topbar"], fg=C["text"]).pack(side="left", pady=10)
        self.co_badge = tk.Label(tp, text="All Companies",
                 font=("Segoe UI",9), bg=C["accent_l"], fg=C["accent"])
        self.co_badge.pack(side="left", padx=(8,0))
        self.tb_status = tk.Label(tp, text="Daily 05:00 AM",
                 font=("Segoe UI",9), bg=C["topbar"], fg=C["text4"])
        self.tb_status.pack(side="right", padx=16)
        tk.Frame(page, bg=C["border"], height=1).pack(fill="x")
        page = self._make_scrollable(page)

        # Cards row
        cr = tk.Frame(page, bg=C["page"])
        cr.pack(fill="x", padx=14, pady=12)
        cr.columnconfigure(0, weight=1)
        cr.columnconfigure(1, weight=1)
        cr.columnconfigure(2, weight=1)

        # Card 1 — Odoo
        c1 = self._card(cr, "Odoo Connection", "#2563eb", 0, 0)
        self.f_host = self._field(c1, "Host")
        self.f_db   = self._field(c1, "Database")
        self.f_user = self._field(c1, "Username")
        self.f_pass = self._field(c1, "Password", show="*")
        tk.Label(c1, text="Company", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w", pady=(6,2))
        cr2 = tk.Frame(c1, bg=C["white"])
        cr2.pack(fill="x"); cr2.columnconfigure(0, weight=1)
        self.company_var = tk.StringVar(value="All Companies")
        self.company_cb  = ttk.Combobox(cr2, textvariable=self.company_var,
                                         state="readonly", font=("Segoe UI",10), width=14)
        self.company_cb["values"] = ["All Companies"]
        self.company_cb.grid(row=0, column=0, sticky="ew")
        self.company_cb.bind("<<ComboboxSelected>>", self._on_company_select)
        tk.Button(cr2, text="Load", command=self._load_companies,
                  font=("Segoe UI",9,"bold"), bg=C["accent"], fg="white",
                  relief="flat", bd=0, padx=10, pady=4, cursor="hand2"
                  ).grid(row=0, column=1, padx=(6,0))

        # Card 2 — Green API
        c2 = self._card(cr, "Green API — WhatsApp", "#25d366", 0, 1)
        self.f_ginstance = self._field(c2, "Instance ID", accent=True)
        self.f_gtoken    = self._field(c2, "API Token")
        tk.Label(c2, text="Free at green-api.com", font=("Segoe UI",8),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w", pady=(2,6))
        self._pill_btn(c2, "Test WhatsApp Connection", self._test_green, C["wa_l"], C["wa"])
        tk.Label(c2, text="Custom Note", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w", pady=(10,2))
        self.note_text = tk.Text(c2, font=("Consolas",9), bg=C["input"],
                                  fg=C["text2"], insertbackground=C["accent"],
                                  relief="flat", bd=0, height=3, wrap="word",
                                  highlightthickness=1, highlightbackground=C["border"])
        self.note_text.pack(fill="x")

        # Card 3 — Schedule
        c3 = self._card(cr, "Schedule & Date", "#f59e0b", 0, 2)
        tk.Label(c3, text="Selected Date", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w", pady=(0,3))
        self.date_picker = DateEntry(c3, width=16, font=("Segoe UI",10),
                                      date_pattern="dd/mm/yyyy",
                                      background=C["accent"], foreground="white",
                                      headersbackground=C["accent"],
                                      headersforeground="white",
                                      selectbackground=C["accent"])
        self.date_picker.pack(fill="x", pady=(0,8))
        self.date_picker.set_date(date.today())
        self.auto_today = tk.BooleanVar(value=True)
        self._checkbox(c3, "Use TODAY for scheduler", self.auto_today)
        hm = tk.Frame(c3, bg=C["white"])
        hm.pack(fill="x", pady=(6,8))
        tk.Label(hm, text="Daily at:", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"]).pack(side="left")
        self.f_hour = tk.StringVar(value="5")
        self.f_min  = tk.StringVar(value="0")
        for var, unit in [(self.f_hour,"h"),(self.f_min,"m")]:
            tk.Entry(hm, textvariable=var, font=("Consolas",11,"bold"), bg=C["input2"],
                     fg=C["accent"], insertbackground=C["accent"],
                     relief="flat", bd=0, width=3,
                     highlightthickness=1, highlightbackground=C["border2"]
                     ).pack(side="left", padx=(6,2))
            tk.Label(hm, text=unit, font=("Segoe UI",9),
                     bg=C["white"], fg=C["text4"]).pack(side="left")
        wbox = tk.Frame(c3, bg=C["input"], highlightthickness=1,
                        highlightbackground=C["border"])
        wbox.pack(fill="x")
        tk.Label(wbox, text="Watch Mode", font=("Segoe UI",8,"bold"),
                 bg=C["input"], fg=C["text3"]).pack(anchor="w", padx=8, pady=(6,2))
        wr = tk.Frame(wbox, bg=C["input"])
        wr.pack(fill="x", padx=8, pady=(0,6))
        self.watch_var = tk.BooleanVar(value=False)
        self._checkbox(wr, "Enable — every", self.watch_var, parent_bg=C["input"], inline=True)
        self.f_interval = tk.StringVar(value="5")
        tk.Entry(wr, textvariable=self.f_interval, font=("Consolas",10), bg=C["white"],
                 fg=C["accent"], relief="flat", bd=0, width=3,
                 highlightthickness=1, highlightbackground=C["border2"]
                 ).pack(side="left", padx=(4,2))
        tk.Label(wr, text="min", font=("Segoe UI",9),
                 bg=C["input"], fg=C["text4"]).pack(side="left")

        # Button bar
        bf = tk.Frame(page, bg=C["page"])
        bf.pack(fill="x", padx=14, pady=(0,8))
        btns = [
            ("Save",            self._save,      C["accent_l"], C["accent"]),
            ("Test Odoo",       self._test_conn, C["cyan_l"],   C["cyan"]),
            ("Run for Date",    self._run_date,  C["green_l"],  C["green"]),
            ("Start Scheduler", self._start,     C["amber_l"],  C["amber"]),
            ("Stop",            self._stop,      C["red_l"],    C["red"]),
        ]
        for txt, cmd, bg, fg in btns:
            b = tk.Button(bf, text=txt, command=cmd, font=("Segoe UI",10,"bold"),
                      bg=bg, fg=fg, relief="flat", bd=0, padx=14, pady=7,
                      cursor="hand2", activebackground=fg, activeforeground="white")
            b.pack(side="left", padx=(0,8))

        self.progress = ttk.Progressbar(page, mode="indeterminate", style="TProgressbar")
        self.progress.pack(fill="x", padx=14, pady=(0,4))
        self.log_box = self._log_panel(page, "po")

    # ── Audit Page ────────────────────────────────────────────────────────────
    def _build_audit_page(self):
        page = tk.Frame(self.main, bg=C["page"])
        self.pages["audit"] = page
        self._audit_users = []  # list of {id, name, phone} fetched from Odoo

        tp = tk.Frame(page, bg=C["topbar"], height=44)
        tp.pack(fill="x"); tp.pack_propagate(False)
        tk.Label(tp, text="  Audit Log", font=("Segoe UI",12,"bold"),
                 bg=C["topbar"], fg=C["text"]).pack(side="left", pady=10)

        # Zeeta ERP badge — right side of topbar
        zeeta_badge = tk.Frame(tp, bg="#1a2540", padx=10, pady=6)
        zeeta_badge.pack(side="right", padx=10)
        # Z logo box
        z_logo = tk.Frame(zeeta_badge, bg="#fff", width=26, height=26)
        z_logo.pack(side="left", padx=(0,6))
        z_logo.pack_propagate(False)
        tk.Label(z_logo, text="Z", font=("Segoe UI",12,"bold"),
                 bg="#fff", fg="#1a2540").place(relx=.5, rely=.5, anchor="center")
        # Text
        z_txt = tk.Frame(zeeta_badge, bg="#1a2540")
        z_txt.pack(side="left")
        tk.Label(z_txt, text="Zeeta ERP",
                 font=("Segoe UI",9,"bold"), bg="#1a2540", fg="#fff").pack(anchor="w")
        self.zeeta_erp_status_lbl = tk.Label(z_txt, text="Audit Log · Live",
                 font=("Segoe UI",8), bg="#1a2540", fg="#22c55e")
        self.zeeta_erp_status_lbl.pack(anchor="w")
        # Live dot
        tk.Frame(zeeta_badge, bg="#22c55e", width=7, height=7,
                 ).pack(side="left", padx=(6,0))

        tk.Frame(page, bg=C["border"], height=1).pack(fill="x")

        # ── Horizontal + vertical scroll container ────────────────────────────
        # Hint strip
        hint_strip = tk.Frame(page, bg=C["accent_l"], height=22)
        hint_strip.pack(fill="x"); hint_strip.pack_propagate(False)
        tk.Label(hint_strip, text="↔  Scroll left / right — drag the horizontal scrollbar at the bottom",
                 font=("Segoe UI",8), bg=C["accent_l"], fg=C["accent"]).pack(side="left", padx=10)

        # Canvas + scrollbars
        _audit_canvas = tk.Canvas(page, bg=C["page"], highlightthickness=0)
        _audit_hscroll = ttk.Scrollbar(page, orient="horizontal",
                                        command=_audit_canvas.xview)
        _audit_vscroll = ttk.Scrollbar(page, orient="vertical",
                                        command=_audit_canvas.yview)
        _audit_canvas.configure(xscrollcommand=_audit_hscroll.set,
                                 yscrollcommand=_audit_vscroll.set)
        _audit_hscroll.pack(side="bottom", fill="x")
        _audit_vscroll.pack(side="right",  fill="y")
        _audit_canvas.pack(side="left", fill="both", expand=True)

        # Inner frame — all content goes here
        _audit_inner = tk.Frame(_audit_canvas, bg=C["page"])
        _audit_canvas_win = _audit_canvas.create_window(
            (0, 0), window=_audit_inner, anchor="nw")

        def _audit_on_configure(event):
            _audit_canvas.configure(scrollregion=_audit_canvas.bbox("all"))
            # Make inner frame at least as wide as canvas
            if _audit_inner.winfo_reqwidth() < _audit_canvas.winfo_width():
                _audit_canvas.itemconfig(_audit_canvas_win,
                                          width=_audit_canvas.winfo_width())
        _audit_inner.bind("<Configure>", _audit_on_configure)
        _audit_canvas.bind("<Configure>", lambda e: _audit_canvas.itemconfig(
            _audit_canvas_win,
            width=max(_audit_inner.winfo_reqwidth(), e.width)))

        # Mouse wheel bindings (vertical)
        def _audit_mousewheel(event):
            _audit_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        _audit_canvas.bind_all("<MouseWheel>", _audit_mousewheel)

        # Use _audit_inner as "page" for all content below
        page = _audit_inner

        cr = tk.Frame(page, bg=C["page"])
        cr.pack(fill="x", padx=14, pady=(12,0))
        cr.columnconfigure(0, weight=0, minsize=220)
        cr.columnconfigure(1, weight=1)
        cr.columnconfigure(2, weight=0, minsize=240)

        # Card 1 — Odoo Settings
        c1 = self._card(cr, "Audit Settings", "#7c3aed", 0, 0)
        tk.Label(c1, text="Select Date", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w", pady=(0,3))
        self.audit_date = DateEntry(c1, width=16, font=("Segoe UI",10),
                                     date_pattern="dd/mm/yyyy",
                                     background=C["accent"], foreground="white",
                                     headersbackground=C["accent"],
                                     headersforeground="white",
                                     selectbackground=C["accent"])
        self.audit_date.pack(fill="x", pady=(0,8))
        self.audit_date.set_date(date.today())
        tk.Label(c1, text="Custom Note (appended to reminder)",
                 font=("Segoe UI",9), bg=C["white"], fg=C["text4"]).pack(anchor="w", pady=(0,2))
        self.audit_note_text = tk.Text(c1, font=("Consolas",9), bg=C["input"],
                                        fg=C["text2"], insertbackground=C["accent"],
                                        relief="flat", bd=0, height=2, wrap="word",
                                        highlightthickness=1, highlightbackground=C["border"])
        self.audit_note_text.pack(fill="x")

        # ── Template picker row (audit) ──────────────────────────────────────
        tk.Label(c1, text="Message Template",
                 font=("Segoe UI",9,"bold"),
                 bg=C["white"], fg=C["text"]).pack(anchor="w", pady=(8, 2))

        _cfg_a = load_config()
        _saved_a = _cfg_a.get("audit_templates") or {}
        if not _saved_a:
            _saved_a = {k: dict(v)
                        for k, v in DEFAULT_AUDIT_TEMPLATES.items()}
        self._audit_templates = _saved_a
        _sel_a = _cfg_a.get("audit_template_selected", "Standard")
        if _sel_a not in _saved_a:
            _sel_a = next(iter(_saved_a.keys()), "Standard")

        tpl_row = tk.Frame(c1, bg=C["white"])
        tpl_row.pack(fill="x", pady=(0, 4))
        self.audit_tpl_var = tk.StringVar(value=_sel_a)
        self.audit_tpl_dropdown = ttk.Combobox(
            tpl_row, textvariable=self.audit_tpl_var,
            values=list(_saved_a.keys()), state="readonly",
            font=("Segoe UI", 9), width=18)
        self.audit_tpl_dropdown.pack(side="left", padx=(0, 4))
        self.audit_tpl_dropdown.bind(
            "<<ComboboxSelected>>", self._audit_on_template_change)

        tk.Button(tpl_row, text="Edit",
                  command=self._audit_edit_templates,
                  font=("Segoe UI", 8),
                  bg=C["input"], fg=C["text2"], bd=0,
                  padx=8, pady=2, cursor="hand2").pack(side="left", padx=2)

        tk.Button(tpl_row, text="Preview",
                  command=self._audit_preview_template,
                  font=("Segoe UI", 8, "bold"),
                  bg=C["accent_l"], fg=C["accent"], bd=0,
                  padx=8, pady=2, cursor="hand2").pack(side="left", padx=2)

        # Card 2 — User selector
        c2 = self._card(cr, "Odoo Users", "#0f766e", 0, 1)
        tk.Label(c2, text="Click Load to fetch users who had activity on the selected date.",
                 font=("Segoe UI",8), bg=C["white"], fg=C["text4"],
                 wraplength=180, justify="left").pack(anchor="w", pady=(0,6))

        # Load button
        tk.Button(c2, text="Load Active Users for Date",
                  command=self._load_audit_users,
                  font=("Segoe UI",9,"bold"), bg=C["accent_l"], fg=C["accent"],
                  relief="flat", bd=0, pady=5, cursor="hand2",
                  activebackground=C["accent"], activeforeground="white"
                  ).pack(fill="x", pady=(0,6))

        # Listbox with checkboxes via Listbox + selectmode multiple
        tk.Label(c2, text="Active users on selected date (Ctrl+click):",
                 font=("Segoe UI",8), bg=C["white"], fg=C["text4"]).pack(anchor="w", pady=(0,2))
        lb_frame = tk.Frame(c2, bg=C["border"], padx=1, pady=1)
        lb_frame.pack(fill="both", expand=True)
        self.audit_user_lb = tk.Listbox(lb_frame, font=("Segoe UI",9),
                                         bg=C["input"], fg=C["text2"],
                                         selectbackground=C["accent"],
                                         selectforeground="white",
                                         relief="flat", bd=0,
                                         selectmode=tk.MULTIPLE,
                                         height=7,
                                         activestyle="none")
        self.audit_user_lb.pack(fill="both", expand=True, padx=4, pady=4)
        self.audit_user_lb.insert("end", "-- Click Load Users first --")

        # Select all / none buttons
        sb2 = tk.Frame(c2, bg=C["white"])
        sb2.pack(fill="x", pady=(4,0))
        tk.Button(sb2, text="Select All", command=self._audit_select_all,
                  font=("Segoe UI",8), bg=C["green_l"], fg=C["green"],
                  relief="flat", bd=0, padx=8, pady=3, cursor="hand2"
                  ).pack(side="left", padx=(0,4))
        tk.Button(sb2, text="Clear All", command=self._audit_clear_all,
                  font=("Segoe UI",8), bg=C["red_l"], fg=C["red"],
                  relief="flat", bd=0, padx=8, pady=3, cursor="hand2"
                  ).pack(side="left")
        self.audit_sel_lbl = tk.Label(sb2, text="0 selected",
                 font=("Segoe UI",8), bg=C["white"], fg=C["text4"])
        self.audit_sel_lbl.pack(side="right")
        self.audit_user_lb.bind("<<ListboxSelect>>", self._on_audit_user_select)
        # Card 3 — TimeDoctor API + Zeeta ERP link
        c3 = self._card(cr, "TimeDoctor API", "#7c3aed", 0, 2)

        # ── Zeeta ERP link status ─────────────────────────────────────────────
        erp_sep = tk.Frame(c3, bg=C["border"], height=1)
        erp_sep.pack(fill="x", pady=(0,6))
        erp_row = tk.Frame(c3, bg=C["white"])
        erp_row.pack(fill="x", pady=(0,6))
        # Z mini logo
        z_mini = tk.Frame(erp_row, bg="#1a2540", width=22, height=22)
        z_mini.pack(side="left", padx=(0,6))
        z_mini.pack_propagate(False)
        tk.Label(z_mini, text="Z", font=("Segoe UI",9,"bold"),
                 bg="#1a2540", fg="#fff").place(relx=.5, rely=.5, anchor="center")
        erp_txt = tk.Frame(erp_row, bg=C["white"])
        erp_txt.pack(side="left", fill="x", expand=True)
        tk.Label(erp_txt, text="Zeeta ERP — Ashwheelz",
                 font=("Segoe UI",8,"bold"), bg=C["white"], fg=C["text"]).pack(anchor="w")
        # Check if Sales Reminder session exists — reuse if logged in
        def _check_erp_link():
            if getattr(self, "_sales_session", None):
                self.erp_link_lbl.config(
                    text="Linked via Sales Reminder ✓",
                    bg=C["green_l"], fg=C["green"])
            else:
                self.erp_link_lbl.config(
                    text="Not linked — log in via Sales Reminder first",
                    bg=C["amber_l"], fg=C["amber"])
        tk.Button(erp_row, text="Check",
                  command=_check_erp_link,
                  font=("Segoe UI",8), bg=C["input"], fg=C["text3"],
                  relief="flat", bd=0, padx=6, pady=2, cursor="hand2"
                  ).pack(side="right")
        self.erp_link_lbl = tk.Label(c3, text="Click Check to verify ERP link",
                 font=("Segoe UI",8), bg=C["amber_l"], fg=C["amber"],
                 padx=6, pady=2, wraplength=220, justify="left")
        self.erp_link_lbl.pack(fill="x", pady=(0,8))

        # Go to Sales Reminder button if not linked
        tk.Button(c3, text="→ Go to Sales Reminder to Login",
                  command=lambda: self._show_page("sales"),
                  font=("Segoe UI",8), bg=C["input"], fg=C["accent"],
                  relief="flat", bd=0, padx=8, pady=3, cursor="hand2"
                  ).pack(anchor="w", pady=(0,8))

        tk.Frame(c3, bg=C["border"], height=1).pack(fill="x", pady=(0,6))

        # ── TimeDoctor — Playwright browser login ────────────────────────────
        td_conn_row = tk.Frame(c3, bg=C["white"])
        td_conn_row.pack(fill="x", pady=(0,6))
        self.td_conn_lbl = tk.Label(td_conn_row, text="Not connected",
                 font=("Segoe UI",8), bg=C["red_l"], fg=C["red"], padx=6, pady=2)
        self.td_conn_lbl.pack(side="right")
        tk.Label(td_conn_row, text="TimeDoctor  (Playwright)",
                 font=("Segoe UI",9,"bold"), bg=C["white"], fg="#5b21b6").pack(side="left")

        _td_cred_row = tk.Frame(c3, bg=C["white"])
        _td_cred_row.pack(fill="x", pady=(0,4))
        tk.Label(_td_cred_row, text="Email",
                 font=("Segoe UI",9), bg=C["white"], fg=C["text4"]).pack(side="left")
        self.td_email_var = tk.StringVar(value=load_config().get("td_email",""))
        tk.Entry(_td_cred_row, textvariable=self.td_email_var,
                 font=("Segoe UI",9), bg=C["input2"], fg=C["text2"],
                 relief="flat", bd=0, width=16,
                 highlightthickness=1, highlightbackground=C["border2"]
                 ).pack(side="left", padx=(4,8), ipady=3)
        tk.Label(_td_cred_row, text="Password",
                 font=("Segoe UI",9), bg=C["white"], fg=C["text4"]).pack(side="left")
        self.td_pass_var = tk.StringVar(value=load_config().get("td_pass",""))
        tk.Entry(_td_cred_row, textvariable=self.td_pass_var,
                 font=("Segoe UI",9), bg=C["input2"], fg=C["text2"],
                 show="*", relief="flat", bd=0, width=12,
                 highlightthickness=1, highlightbackground=C["border2"]
                 ).pack(side="left", padx=(4,0), ipady=3)

        # Keep company var for backward compat
        self.td_company_var = tk.StringVar(value=load_config().get("td_company",""))
        self.td_token_var   = tk.StringVar(value=load_config().get("td_token",""))
        self.td_cookie_var  = tk.StringVar()

        td_btn_row = tk.Frame(c3, bg=C["white"])
        td_btn_row.pack(fill="x", pady=(4,0))
        tk.Button(td_btn_row, text="Login (Playwright)",
                  command=self._td_load,
                  font=("Segoe UI",9,"bold"), bg="#ede9fe", fg="#5b21b6",
                  relief="flat", bd=0, padx=10, pady=4, cursor="hand2",
                  activebackground="#5b21b6", activeforeground="white"
                  ).pack(side="left")
        self.td_info_lbl = tk.Label(c3,
                 text="Enter TD email + password → Login opens browser → Fetch TD Data scrapes all users.",
                 font=("Segoe UI",8), bg=C["white"], fg=C["text4"], wraplength=210, justify="left")
        self.td_info_lbl.pack(anchor="w", pady=(4,0))

        self._current_detail_user = None

        # ── Combined Odoo + TimeDoctor table ─────────────────────────────────
        td_table_outer = tk.Frame(page, bg=C["border"], padx=1, pady=1)
        td_table_outer.pack(fill="x", padx=14, pady=(8,0))
        td_table_inner = tk.Frame(td_table_outer, bg=C["white"])
        td_table_inner.pack(fill="both", expand=True)
        td_hdr = tk.Frame(td_table_inner, bg=C["white"], padx=10, pady=6)
        td_hdr.pack(fill="x")
        dot_td = tk.Frame(td_hdr, bg="#7c3aed", width=8, height=8)
        dot_td.pack(side="left", pady=3); dot_td.pack_propagate(False)
        tk.Frame(td_hdr, bg=C["border"], width=1, height=14).pack(side="left", padx=6)
        tk.Label(td_hdr, text="Combined Report — Odoo Actions + TimeDoctor Hours",
                 font=("Segoe UI",9,"bold"), bg=C["white"], fg=C["text"]).pack(side="left")
        # Source badges
        tk.Label(td_hdr, text="Odoo", font=("Segoe UI",8,"bold"),
                 bg=C["accent_l"], fg=C["accent"], padx=6, pady=2
                 ).pack(side="right", padx=(4,0))
        tk.Label(td_hdr, text="+", font=("Segoe UI",8),
                 bg=C["white"], fg=C["text4"]).pack(side="right", padx=2)
        tk.Label(td_hdr, text="TimeDoctor", font=("Segoe UI",8,"bold"),
                 bg="#ede9fe", fg="#5b21b6", padx=6, pady=2
                 ).pack(side="right")
        tk.Frame(td_table_inner, bg=C["border"], height=1).pack(fill="x")

        # Treeview for combined data
        style2 = ttk.Style()
        style2.configure("TD.Treeview", font=("Segoe UI",9), rowheight=20,
                         background=C["input"], fieldbackground=C["input"],
                         foreground=C["text2"])
        style2.configure("TD.Treeview.Heading", font=("Segoe UI",8,"bold"))
        self.td_tree = ttk.Treeview(td_table_inner, style="TD.Treeview",
                                     columns=("odoo_actions","odoo_status","hours",
                                              "active","idle_pct","nonprod"),
                                     show="headings", height=6)
        for col, txt, w, anchor in [
            ("odoo_actions", "Odoo Actions",        100, "center"),
            ("odoo_status",  "Odoo Status",          90, "center"),
            ("hours",        "Hours Worked",         95, "center"),
            ("active",       "Active Time",          85, "center"),
            ("idle_pct",     "Idle (mins %)",        110, "center"),
            ("nonprod",      "Non-Productive Time", 140, "center"),
        ]:
            self.td_tree.heading(col, text=txt)
            self.td_tree.column(col, width=w, anchor=anchor, stretch=False)
        # Employee name as first column via #0 (tree column)
        self.td_tree.configure(show="tree headings")
        self.td_tree.column("#0", width=140, stretch=False)
        self.td_tree.heading("#0", text="Employee")
        td_vsb = ttk.Scrollbar(td_table_inner, orient="vertical", command=self.td_tree.yview)
        self.td_tree.configure(yscrollcommand=td_vsb.set)
        td_vsb.pack(side="right", fill="y")
        self._add_tree_search(td_table_inner, self.td_tree, "Search employee...")
        self.td_tree.pack(fill="both", expand=True)
        # Row tags
        self.td_tree.tag_configure("good",   background=C["green_l"],  foreground=C["green"])
        self.td_tree.tag_configure("warn",   background=C["amber_l"],  foreground=C["amber"])
        self.td_tree.tag_configure("danger", background=C["red_l"],    foreground=C["red"])
        self.td_tree.tag_configure("absent", background=C["input"],    foreground=C["text4"])
        self.td_tree.tag_configure("normal", background=C["input"],    foreground=C["text2"])
        # Heading style overrides
        style2.configure("TD.Treeview.Heading", background=C["accent_l"], foreground=C["accent"])
        self.td_tree.insert("", "end", text="-- Click 'Fetch TD Data' to load --",
                             values=("","","","","",""), tags=("normal",))
        # Double-click any row to see idle-instance breakdown
        self.td_tree.bind("<Double-1>", self._td_idle_drilldown)

        # ── Middle row: Entry Breakdown (max width) + Non-Activity panel ──────
        mid_row = tk.Frame(page, bg=C["page"])
        mid_row.pack(fill="both", expand=True, padx=14, pady=(0,6))
        mid_row.columnconfigure(0, weight=1)
        mid_row.columnconfigure(1, weight=0, minsize=260)
        mid_row.rowconfigure(0, weight=1)

        # Entry Breakdown card (fills all remaining width)
        bd_outer = tk.Frame(mid_row, bg=C["border"], padx=1, pady=1)
        bd_outer.grid(row=0, column=0, sticky="nsew", padx=(0,5))
        bd_inner = tk.Frame(bd_outer, bg=C["white"])
        bd_inner.pack(fill="both", expand=True)
        det_hdr = tk.Frame(bd_inner, bg=C["white"], padx=10, pady=6)
        det_hdr.pack(fill="x")
        dot_bd = tk.Frame(det_hdr, bg="#7c3aed", width=8, height=8)
        dot_bd.pack(side="left", pady=3); dot_bd.pack_propagate(False)
        tk.Frame(det_hdr, bg=C["border"], width=1, height=14).pack(side="left", padx=6)
        tk.Label(det_hdr, text="Entry breakdown (click user)",
                 font=("Segoe UI",9,"bold"), bg=C["white"], fg=C["text"]).pack(side="left")
        self.det_view_var = tk.StringVar(value="grouped")
        tk.Radiobutton(det_hdr, text="By module function entries", variable=self.det_view_var,
                       value="modfunc", font=("Segoe UI",8), bg=C["white"],
                       fg="#7c3aed", selectcolor=C["white"],
                       command=self._refresh_audit_detail).pack(side="right", padx=(4,0))
        tk.Radiobutton(det_hdr, text="By module actions", variable=self.det_view_var,
                       value="grouped", font=("Segoe UI",8), bg=C["white"],
                       fg=C["accent"], selectcolor=C["white"],
                       command=self._refresh_audit_detail).pack(side="right", padx=(4,0))
        tk.Radiobutton(det_hdr, text="By time", variable=self.det_view_var,
                       value="timeline", font=("Segoe UI",8), bg=C["white"],
                       fg=C["text3"], selectcolor=C["white"],
                       command=self._refresh_audit_detail).pack(side="right", padx=(0,0))
        tk.Frame(det_hdr, bg=C["border"], width=1, height=14).pack(side="right", padx=(8,0))
        tk.Button(det_hdr, text="Unfold All",
                  command=self._audit_unfold_all,
                  font=("Segoe UI",8,"bold"), bg=C["green_l"], fg=C["green"],
                  relief="flat", bd=0, padx=8, pady=2, cursor="hand2",
                  activebackground=C["green"], activeforeground="white"
                  ).pack(side="right", padx=(0,4))
        tk.Button(det_hdr, text="Fold All",
                  command=self._audit_fold_all,
                  font=("Segoe UI",8,"bold"), bg=C["input"], fg=C["text3"],
                  relief="flat", bd=0, padx=8, pady=2, cursor="hand2",
                  activebackground=C["border2"], activeforeground=C["text"]
                  ).pack(side="right", padx=(0,2))
        tk.Frame(bd_inner, bg=C["border"], height=1).pack(fill="x")
        det_f = tk.Frame(bd_inner, bg=C["input"])
        det_f.pack(fill="both", expand=True)
        style = ttk.Style()
        style.configure("Audit.Treeview", font=("Consolas",8), rowheight=18,
                        background=C["input"], fieldbackground=C["input"],
                        foreground=C["text2"])
        style.configure("Audit.Treeview.Heading", font=("Segoe UI",8,"bold"),
                        background=C["accent_l"], foreground=C["accent"])
        self.audit_tree = ttk.Treeview(det_f, style="Audit.Treeview",
                                        columns=("date","time","detail"),
                                        show="tree headings", height=10)
        self.audit_tree.heading("#0",     text="Module / Record")
        self.audit_tree.heading("date",   text="Date")
        self.audit_tree.heading("time",   text="Time (PKT)")
        self.audit_tree.heading("detail", text="Document Type")
        self.audit_tree.column("#0",     width=260, stretch=True)
        self.audit_tree.column("date",   width=90,  stretch=False)
        self.audit_tree.column("time",   width=70,  stretch=False)
        self.audit_tree.column("detail", width=180, stretch=True)
        vsb2 = ttk.Scrollbar(det_f, orient="vertical", command=self.audit_tree.yview)
        self.audit_tree.configure(yscrollcommand=vsb2.set)
        vsb2.pack(side="right", fill="y")
        self.audit_tree.pack(fill="both", expand=True)
        self.audit_tree.tag_configure("module",     foreground=C["accent"],
                                       font=("Segoe UI",8,"bold"), background=C["accent_l"])
        self.audit_tree.tag_configure("modfunc",    foreground="#5b21b6",
                                       font=("Segoe UI",8,"bold"), background="#ede9fe")
        self.audit_tree.tag_configure("record",     foreground=C["text2"])
        self.audit_tree.tag_configure("fnentry",    foreground=C["text3"], background="#faf9ff")
        self.audit_tree.tag_configure("time_entry", foreground=C["text3"])

        # Non-Activity panel (fixed width, right side)
        na_outer = tk.Frame(mid_row, bg=C["border"], padx=1, pady=1)
        na_outer.grid(row=0, column=1, sticky="nsew")
        na_inner = tk.Frame(na_outer, bg=C["white"])
        na_inner.pack(fill="both", expand=True)
        na_hdr = tk.Frame(na_inner, bg=C["white"], padx=10, pady=6)
        na_hdr.pack(fill="x")
        dot_na = tk.Frame(na_hdr, bg=C["red"], width=8, height=8)
        dot_na.pack(side="left", pady=3); dot_na.pack_propagate(False)
        tk.Frame(na_hdr, bg=C["border"], width=1, height=14).pack(side="left", padx=6)
        tk.Label(na_hdr, text="Non-active today",
                 font=("Segoe UI",9,"bold"), bg=C["white"], fg=C["text"]).pack(side="left")
        tk.Frame(na_inner, bg=C["border"], height=1).pack(fill="x")
        tk.Label(na_inner, text="Active last 7 days — absent today (Ctrl+click)",
                 font=("Segoe UI",8), bg=C["white"], fg=C["text4"],
                 pady=4).pack(anchor="w", padx=10)
        na_list_frame = tk.Frame(na_inner, bg=C["border"], padx=1, pady=1)
        na_list_frame.pack(fill="both", expand=True, padx=8, pady=(0,4))
        self.na_listbox = tk.Listbox(na_list_frame, font=("Segoe UI",9),
                                      bg=C["input"], fg=C["text2"],
                                      selectbackground=C["red_l"],
                                      selectforeground=C["red"],
                                      relief="flat", bd=0,
                                      selectmode=tk.MULTIPLE,
                                      activestyle="none", height=8)
        na_vsb = ttk.Scrollbar(na_list_frame, orient="vertical", command=self.na_listbox.yview)
        self.na_listbox.configure(yscrollcommand=na_vsb.set)
        na_vsb.pack(side="right", fill="y")
        self.na_listbox.pack(fill="both", expand=True, padx=4, pady=4)
        self.na_listbox.insert("end", "-- Load users first --")
        self.na_listbox.bind("<<ListboxSelect>>", self._on_na_select)
        # Select All / Clear row
        na_btn_row = tk.Frame(na_inner, bg=C["white"])
        na_btn_row.pack(fill="x", padx=8, pady=(0,4))
        tk.Button(na_btn_row, text="Select All", command=self._na_select_all,
                  font=("Segoe UI",8), bg=C["red_l"], fg=C["red"],
                  relief="flat", bd=0, padx=8, pady=3, cursor="hand2"
                  ).pack(side="left", padx=(0,4))
        tk.Button(na_btn_row, text="Clear All", command=self._na_clear_all,
                  font=("Segoe UI",8), bg=C["input"], fg=C["text3"],
                  relief="flat", bd=0, padx=8, pady=3, cursor="hand2"
                  ).pack(side="left")
        self.na_sel_lbl = tk.Label(na_btn_row, text="0 selected",
                 font=("Segoe UI",8), bg=C["white"], fg=C["text4"])
        self.na_sel_lbl.pack(side="right")
        self._non_active_users = []

        # Buttons
        bf = tk.Frame(page, bg=C["page"])
        bf.pack(fill="x", padx=14, pady=(0,8))
        for txt, cmd, bg, fg in [
            ("Load Active Users",    self._load_audit_users,  C["accent_l"],  C["accent"]),
            ("Fetch ERP Data",       self._audit_fetch_erp,   "#fff7ed",      "#c2410c"),
            ("Fetch TD Data",        self._td_fetch,          "#ede9fe",      "#5b21b6"),
            ("Run Audit for Date",   self._run_audit,         C["green_l"],   C["green"]),
            ("⬇ Download PDF Report",self._td_download_pdf,  "#f0fdf4",      "#166534"),
            ("Start Audit Scheduler",self._start_audit,       C["amber_l"],   C["amber"]),
            ("Stop",                 self._stop,              C["red_l"],     C["red"]),
        ]:
            tk.Button(bf, text=txt, command=cmd, font=("Segoe UI",10,"bold"),
                      bg=bg, fg=fg, relief="flat", bd=0, padx=14, pady=7,
                      cursor="hand2", activebackground=fg, activeforeground="white"
                      ).pack(side="left", padx=(0,8))

        self.audit_progress = ttk.Progressbar(page, mode="indeterminate", style="TProgressbar")
        self.audit_progress.pack(fill="x", padx=14, pady=(0,4))
        self.audit_log_box = self._log_panel(page, "audit")


    # ── TimeDoctor integration methods — Playwright edition ─────────────────

    def _td_load(self):
        """Login to TimeDoctor using Playwright (headless Chrome)."""
        email = self.td_email_var.get().strip()
        pwd   = self.td_pass_var.get().strip()
        if not email or not pwd:
            self.audit_log("TimeDoctor: Enter email and password first.", "warn")
            return
        self.td_conn_lbl.config(text="Logging in...", bg=C["amber_l"], fg=C["amber"])
        self._set_busy(True, self.audit_progress)
        self.audit_log("TimeDoctor: Opening browser to login...", "info")
        threading.Thread(target=self._td_load_thread,
                         args=(email, pwd), daemon=True).start()

    def _td_load_thread(self, email, pwd):
        """Background: Login to TD API with email/password, get token, save to config."""
        import requests as _req
        try:
            self.after(0, lambda: self.audit_log("TD: Logging in via API...", "info"))
            r = _req.post(
                "https://api2.timedoctor.com/api/1.0/authorization/login",
                json={"email": email, "password": pwd, "permissions": "write"},
                timeout=20)
            if r.status_code != 200:
                raise ValueError("Login HTTP " + str(r.status_code) + ": " + r.text[:100])

            data = r.json().get("data", {})
            tok  = data.get("token", "")
            if not tok:
                raise ValueError("No token in response: " + r.text[:100])

            # Save token + creds
            cfg = load_config()
            cfg["td_email"]   = email
            cfg["td_pass"]    = pwd
            cfg["td_token"]   = tok
            cfg["td_company"] = "aTUbMi6uG2kPZzUD"
            save_config(cfg)
            self._td_api_token = tok

            def _done():
                self.td_conn_lbl.config(
                    text="Connected ✓  Ashwheelz",
                    bg=C["green_l"], fg=C["green"])
                self.td_info_lbl.config(
                    text="API login OK — click Fetch TD Data")
                self.audit_log("TimeDoctor: API login successful ✓", "ok")
                self._set_busy(False, self.audit_progress)
            self.after(0, _done)

        except Exception as e:
            err = str(e)
            self.after(0, lambda e=err: self.audit_log("TD login error: " + e, "err"))
            self.after(0, lambda: self.td_conn_lbl.config(
                text="Login failed", bg=C["red_l"], fg=C["red"]))
            self.after(0, lambda: self._set_busy(False, self.audit_progress))

    def _td_fetch(self):
        """Fetch TimeDoctor stats via API for selected date."""
        email = self.td_email_var.get().strip()
        pwd   = self.td_pass_var.get().strip()
        tok   = getattr(self, "_td_api_token", "") or load_config().get("td_token", "")

        if not tok:
            if email and pwd:
                self.audit_log("TD: No token — logging in first...", "info")
                self._td_load()
                return
            self.audit_log("TimeDoctor: Click Login (Playwright) first.", "warn")
            return

        # Auto-load Odoo users first if not already loaded for this session.
        # This ensures odoo_counts is populated before the TD table is built,
        # so the "Odoo Actions" column shows real numbers instead of "—".
        if not getattr(self, "_audit_users", None):
            self.audit_log(
                "TD: Odoo users not loaded yet — loading them first...",
                "info")
            self._load_audit_users(after_done=self._td_fetch_go)
            return

        self._td_fetch_go()

    def _td_fetch_go(self):
        """Actual TD fetch — runs either directly or after Odoo load completes."""
        tok = getattr(self, "_td_api_token", "") or load_config().get("td_token", "")
        if not tok:
            self.audit_log("TimeDoctor: Token missing after Odoo load.", "warn")
            return
        sel_date = self.audit_date.get_date().strftime("%Y-%m-%d")
        self._set_busy(True, self.audit_progress)
        self.audit_log("TD: Fetching stats for " + sel_date + "...", "info")
        threading.Thread(target=self._td_fetch_thread,
                         args=(tok, sel_date), daemon=True).start()

    def _td_fetch_thread(self, tok, sel_date):
        """Background: fetch all users + stats from TD API, populate treeview."""
        import requests as _req
        from datetime import datetime as _dt, timedelta as _td
        try:
            BASE    = "https://api2.timedoctor.com/api"
            company = "aTUbMi6uG2kPZzUD"
            # TD API stores in UTC. PKT = UTC+5, so for local date D:
            # UTC range = (D-1)T19:00:00 to DT19:00:00
            _sel_dt = _dt.strptime(sel_date, "%Y-%m-%d")
            dt_from = (_sel_dt - _td(days=1)).strftime("%Y-%m-%d") + "T19:00:00"
            dt_to   = _sel_dt.strftime("%Y-%m-%d") + "T19:00:00"
            self.after(0, lambda f=dt_from, t=dt_to: self.audit_log(
                "TD: UTC range " + f + " → " + t, "info"))

            # ── Step 1: Get all users ─────────────────────────────────────────
            self.after(0, lambda: self.audit_log("TD: Fetching user list...", "info"))
            ur = _req.get(BASE + "/1.0/users",
                          params={"company": company, "token": tok,
                                  "detail": "basic", "limit": 200,
                                  "page": 0, "deleted": 0, "sort": "name"},
                          timeout=20)
            if ur.status_code == 401:
                # Token expired — re-login
                cfg = load_config()
                lr  = _req.post(BASE + "/1.0/authorization/login",
                                json={"email": cfg.get("td_email",""),
                                      "password": cfg.get("td_pass",""),
                                      "permissions": "write"}, timeout=20)
                tok = lr.json().get("data",{}).get("token", tok)
                cfg["td_token"] = tok
                save_config(cfg)
                self._td_api_token = tok
                ur = _req.get(BASE + "/1.0/users",
                              params={"company": company, "token": tok,
                                      "detail": "basic", "limit": 200,
                                      "page": 0, "deleted": 0, "sort": "name"},
                              timeout=20)

            users = ur.json().get("data", [])
            self.after(0, lambda n=len(users): self.audit_log(
                "TD: " + str(n) + " users found", "ok"))

            if not users:
                self.after(0, lambda: self.audit_log("TD: No users found.", "warn"))
                self.after(0, lambda: self._set_busy(False, self.audit_progress))
                return

            # Build id→name map
            id_name = {u.get("id",""): u.get("name","") for u in users}
            # Persist for drill-down popup (reverse lookup: name -> userId)
            self._td_id_name   = id_name
            self._td_name_id   = {v: k for k, v in id_name.items() if v}
            self._td_last_date = sel_date

            # ── Step 2: Fetch stats in batches of 20 ─────────────────────────
            self.after(0, lambda: self.audit_log(
                "TD: Fetching stats for " + sel_date + "...", "info"))

            from collections import defaultdict
            stats = {}
            user_ids = [u.get("id","") for u in users if u.get("id")]

            for i in range(0, len(user_ids), 20):
                batch = user_ids[i:i+20]
                sr = _req.get(BASE + "/1.1/stats/total",
                              params={"company": company, "token": tok,
                                      "from": dt_from, "to": dt_to,
                                      "fields": "userId,totalSec,activeSec,idleSec,idleMins,idleMinsRatio,meeting,unprod",
                                      "group-by": "userId",
                                      "limit": 200,
                                      "user": ",".join(batch)},
                              timeout=20)
                if sr.status_code == 200:
                    for rec in sr.json().get("data", []):
                        uid = rec.get("userId","")
                        if uid:
                            stats[uid] = rec

            self.after(0, lambda n=len(stats): self.audit_log(
                "TD: " + str(n) + " stat records fetched", "ok"))

            # Cache for instant rebuild after mapping changes
            self._td_user_ids  = user_ids
            self._td_stats_raw = stats

            # ── Step 3: Build rows ────────────────────────────────────────────
            def fmt_sec(s):
                if not s or s <= 0: return "0h 00m"
                return str(s // 3600) + "h " + str((s % 3600) // 60).zfill(2) + "m"

            odoo_counts = {}
            odoo_counts_by_email = {}
            for u in getattr(self, "_audit_users", []):
                odoo_counts[u.get("name", "")] = u.get("count", 0)
                lg = (u.get("login") or "").strip().lower()
                if lg:
                    odoo_counts_by_email[lg] = u.get("count", 0)
            td_mapping = load_td_mapping()

            rows = []
            # Cache per-user stats so the drill-down can use TD's reported
            # idle figure (idleMins) instead of guessing from event gaps.
            self._td_stats_by_id = {}
            for uid in user_ids:
                name     = id_name.get(uid, uid)
                rec      = stats.get(uid, {})
                worked_s = rec.get("totalSec", 0) or 0
                active_s = rec.get("activeSec", 0) or 0
                idle_mins   = rec.get("idleMins", 0) or 0
                nonprod     = rec.get("unprod", 0) or 0
                meeting_s   = rec.get("meeting", 0) or 0
                # idleMinsRatio matches TD web "Idle Minutes %" exactly
                idle_pct_raw = rec.get("idleMinsRatio", None)
                if idle_pct_raw is not None:
                    idle_pct = round(float(idle_pct_raw) * 100)
                elif worked_s > 0:
                    idle_pct = round(idle_mins * 100 / (worked_s // 60)) if worked_s > 0 else 0
                else:
                    idle_pct = 0

                # Cache for drill-down
                self._td_stats_by_id[uid] = {
                    "worked_s":   worked_s,
                    "active_s":   active_s,
                    "idle_mins":  idle_mins,
                    "idle_s":     int(idle_mins) * 60,
                    "nonprod_s":  nonprod,
                }

                odoo_act = odoo_counts.get(name, None)
                if odoo_act is None:
                    mapped_email = td_mapping.get(name, "").strip().lower()
                    if mapped_email:
                        odoo_act = odoo_counts_by_email.get(mapped_email, "—")
                    else:
                        odoo_act = "—"
                odoo_status = str(odoo_act) + " actions" if isinstance(odoo_act, int) else "Not in Odoo"

                tag = ("absent" if worked_s == 0
                       else "danger" if idle_pct > 40 or nonprod > 3600
                       else "warn"   if idle_pct > 20 or nonprod > 1800
                       else "good")

                idle_display = str(idle_mins) + "m (" + str(idle_pct) + "%)"
                rows.append((name, str(odoo_act), odoo_status,
                             fmt_sec(worked_s), fmt_sec(active_s),
                             idle_display,
                             fmt_sec(nonprod) + (" ⚠" if nonprod > 1800 else ""),
                             tag))

            # Sort by hours worked descending
            rows.sort(key=lambda r: -int(r[3].split("h")[0]) * 60 -
                      int(r[3].split("h")[1].replace("m","").strip() or 0)
                      if "h" in r[3] else 0)

            def _populate():
                self.td_tree.delete(*self.td_tree.get_children())
                if not rows:
                    self.td_tree.insert("", "end", text="No data",
                                        values=("","","","","",""), tags=("absent",))
                    return
                for name, odoo_act, odoo_status, hours, active, idle, nonprod, tag in rows:
                    self.td_tree.insert("", "end", text=name,
                                        values=(odoo_act, odoo_status,
                                                hours, active, idle, nonprod),
                                        tags=(tag,))
                self.td_conn_lbl.config(text="Fetched " + sel_date,
                                        bg=C["green_l"], fg=C["green"])
                self.td_info_lbl.config(
                    text=str(len(rows)) + " employees · " + sel_date)
                self.audit_log("TimeDoctor: " + str(len(rows)) +
                               " records fetched for " + sel_date, "ok")
                active_c = [r[0] for r in rows if r[7] != "absent"]
                danger_c = [r[0] for r in rows if r[7] == "danger"]
                if danger_c:
                    self.audit_log("High idle/nonprod: " + ", ".join(danger_c[:5]), "warn")

            self.after(0, _populate)

        except Exception as e:
            self.after(0, lambda e=str(e): self.audit_log("TD fetch error: " + e, "err"))
            self.after(0, lambda: self.td_conn_lbl.config(
                text="Error", bg=C["red_l"], fg=C["red"]))
        finally:
            self.after(0, lambda: self._set_busy(False, self.audit_progress))


    def _td_rebuild_combined_report(self):
        """Rebuild combined report treeview using cached TD data + fresh mapping."""
        user_ids = getattr(self, "_td_user_ids", None)
        stats    = getattr(self, "_td_stats_raw", None)
        id_name  = getattr(self, "_td_id_name", None)
        sel_date = getattr(self, "_td_last_date", "")
        if not user_ids or stats is None or not id_name:
            self.audit_log("No cached TD data — click 'Fetch TD Data' first.", "warn")
            return

        def fmt_sec(s):
            if not s or s <= 0: return "0h 00m"
            return str(s // 3600) + "h " + str((s % 3600) // 60).zfill(2) + "m"

        odoo_counts = {}
        odoo_counts_by_email = {}
        for u in getattr(self, "_audit_users", []):
            odoo_counts[u.get("name", "")] = u.get("count", 0)
            lg = (u.get("login") or "").strip().lower()
            if lg:
                odoo_counts_by_email[lg] = u.get("count", 0)
        td_mapping = load_td_mapping()

        rows = []
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
                idle_pct = round(idle_mins * 100 / (worked_s // 60))
            else:
                idle_pct = 0

            odoo_act = odoo_counts.get(name, None)
            if odoo_act is None:
                mapped_email = td_mapping.get(name, "").strip().lower()
                if mapped_email:
                    odoo_act = odoo_counts_by_email.get(mapped_email, "—")
                else:
                    odoo_act = "—"
            odoo_status = str(odoo_act) + " actions" if isinstance(odoo_act, int) else "Not in Odoo"

            tag = ("absent" if worked_s == 0
                   else "danger" if idle_pct > 40 or nonprod > 3600
                   else "warn"   if idle_pct > 20 or nonprod > 1800
                   else "good")
            idle_display = str(idle_mins) + "m (" + str(idle_pct) + "%)"
            rows.append((name, str(odoo_act), odoo_status,
                         fmt_sec(worked_s), fmt_sec(active_s),
                         idle_display,
                         fmt_sec(nonprod) + (" ⚠" if nonprod > 1800 else ""),
                         tag))

        rows.sort(key=lambda r: -int(r[3].split("h")[0]) * 60 -
                  int(r[3].split("h")[1].replace("m","").strip() or 0)
                  if "h" in r[3] else 0)

        def _populate():
            self.td_tree.delete(*self.td_tree.get_children())
            for name, odoo_act, odoo_status, hours, active, idle, nonprod, tag in rows:
                self.td_tree.insert("", "end", text=name,
                                    values=(odoo_act, odoo_status, hours, active, idle, nonprod),
                                    tags=(tag,))
            self.audit_log("Combined report refreshed with updated mapping.", "ok")
        self.after(0, _populate)

    # ═════════════════════════════════════════════════════════════════════════
    # Download Combined Report as PDF
    # ═════════════════════════════════════════════════════════════════════════
    def _td_download_pdf(self):
        """Export the Combined Report (Odoo Actions + TimeDoctor Hours) to PDF."""
        from tkinter import filedialog, messagebox
        try:
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib import colors
            from reportlab.lib.units import cm
            from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                            Paragraph, Spacer)
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        except ImportError:
            from tkinter import messagebox
            messagebox.showerror("Missing Library",
                "reportlab is not installed.\nRun: pip install reportlab")
            return

        # ── Collect rows from treeview ──────────────────────────────────────
        children = self.td_tree.get_children()
        if not children:
            from tkinter import messagebox
            messagebox.showwarning("No Data", "Fetch TD Data first before downloading.")
            return
        first_text = self.td_tree.item(children[0], "text")
        if first_text.startswith("--"):
            from tkinter import messagebox
            messagebox.showwarning("No Data", "Fetch TD Data first before downloading.")
            return

        # ── Ask user where to save ──────────────────────────────────────────
        sel_date = ""
        try:
            sel_date = self.audit_date.get_date().strftime("%Y-%m-%d")
        except Exception:
            sel_date = datetime.today().strftime("%Y-%m-%d")

        default_name = "HR_Combined_Report_" + sel_date + ".pdf"
        save_path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
            initialfile=default_name,
            title="Save Combined Report PDF"
        )
        if not save_path:
            return

        # ── Build PDF ───────────────────────────────────────────────────────
        try:
            doc = SimpleDocTemplate(
                save_path,
                pagesize=landscape(A4),
                leftMargin=1.5*cm, rightMargin=1.5*cm,
                topMargin=1.5*cm, bottomMargin=1.5*cm
            )

            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                "ReportTitle",
                parent=styles["Heading1"],
                fontSize=14,
                textColor=colors.HexColor("#1e3a5f"),
                spaceAfter=4
            )
            sub_style = ParagraphStyle(
                "ReportSub",
                parent=styles["Normal"],
                fontSize=9,
                textColor=colors.HexColor("#6b7280"),
                spaceAfter=10
            )

            story = []
            story.append(Paragraph("Combined Report — Odoo Actions + TimeDoctor Hours", title_style))
            story.append(Paragraph("Date: " + sel_date + "   |   Generated: " +
                                   datetime.now().strftime("%Y-%m-%d %H:%M"), sub_style))
            story.append(Spacer(1, 0.3*cm))

            # Table header
            headers = ["Employee", "Odoo Actions", "Odoo Status",
                       "Hours Worked", "Active Time", "Idle (mins %)", "Non-Productive"]
            data = [headers]

            # Tag → background colour mapping
            tag_colours = {
                "good":   colors.HexColor("#f0fdf4"),
                "warn":   colors.HexColor("#fffbeb"),
                "danger": colors.HexColor("#fef2f2"),
                "absent": colors.HexColor("#f9fafb"),
                "normal": colors.white,
            }
            row_tags = []

            for iid in children:
                item = self.td_tree.item(iid)
                name = item["text"]
                vals = item["values"]
                tag  = item["tags"][0] if item["tags"] else "normal"
                row_tags.append(tag)
                data.append([
                    name,
                    vals[0] if len(vals) > 0 else "",
                    vals[1] if len(vals) > 1 else "",
                    vals[2] if len(vals) > 2 else "",
                    vals[3] if len(vals) > 3 else "",
                    vals[4] if len(vals) > 4 else "",
                    vals[5] if len(vals) > 5 else "",
                ])

            col_widths = [4*cm, 2.8*cm, 3.2*cm, 3*cm, 3*cm, 3.2*cm, 3.8*cm]
            table = Table(data, colWidths=col_widths, repeatRows=1)

            style_cmds = [
                # Header row
                ("BACKGROUND",  (0,0), (-1,0), colors.HexColor("#1e3a5f")),
                ("TEXTCOLOR",   (0,0), (-1,0), colors.white),
                ("FONTNAME",    (0,0), (-1,0), "Helvetica-Bold"),
                ("FONTSIZE",    (0,0), (-1,0), 9),
                ("ALIGN",       (0,0), (-1,0), "CENTER"),
                ("BOTTOMPADDING",(0,0),(-1,0), 7),
                ("TOPPADDING",  (0,0), (-1,0), 7),
                # Data rows
                ("FONTNAME",    (0,1), (-1,-1), "Helvetica"),
                ("FONTSIZE",    (0,1), (-1,-1), 8),
                ("ALIGN",       (1,1), (-1,-1), "CENTER"),
                ("ALIGN",       (0,1), (0,-1),  "LEFT"),
                ("TOPPADDING",  (0,1), (-1,-1), 5),
                ("BOTTOMPADDING",(0,1),(-1,-1), 5),
                # Grid
                ("GRID",        (0,0), (-1,-1), 0.4, colors.HexColor("#d1d5db")),
                ("ROWBACKGROUNDS",(0,1),(-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
            ]

            # Apply per-row status colours
            for i, tag in enumerate(row_tags, start=1):
                bg = tag_colours.get(tag, colors.white)
                style_cmds.append(("BACKGROUND", (0,i), (-1,i), bg))
                if tag == "danger":
                    style_cmds.append(("TEXTCOLOR", (0,i), (-1,i), colors.HexColor("#991b1b")))
                elif tag == "warn":
                    style_cmds.append(("TEXTCOLOR", (0,i), (-1,i), colors.HexColor("#92400e")))
                elif tag == "good":
                    style_cmds.append(("TEXTCOLOR", (0,i), (-1,i), colors.HexColor("#166534")))
                elif tag == "absent":
                    style_cmds.append(("TEXTCOLOR", (0,i), (-1,i), colors.HexColor("#9ca3af")))

            table.setStyle(TableStyle(style_cmds))
            story.append(table)

            # Summary footer
            total = len(row_tags)
            absent_c  = row_tags.count("absent")
            danger_c  = row_tags.count("danger")
            warn_c    = row_tags.count("warn")
            good_c    = row_tags.count("good")
            story.append(Spacer(1, 0.5*cm))
            summary_style = ParagraphStyle("Summary", parent=styles["Normal"],
                                           fontSize=8, textColor=colors.HexColor("#4b5563"))
            story.append(Paragraph(
                f"Total employees: {total}   |   Active (good): {good_c}   |   "
                f"Warning: {warn_c}   |   High idle/nonprod: {danger_c}   |   Absent: {absent_c}",
                summary_style
            ))

            doc.build(story)

            from tkinter import messagebox
            messagebox.showinfo("PDF Saved",
                "Report saved to:\n" + save_path)
            self.audit_log("PDF report saved: " + save_path, "ok")

        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("PDF Error", "Failed to generate PDF:\n" + str(e))
            self.audit_log("PDF error: " + str(e), "err")


    # ═════════════════════════════════════════════════════════════════════════
    # TimeDoctor idle-instance drill-down (double-click handler on td_tree)
    # ═════════════════════════════════════════════════════════════════════════
    def _td_idle_drilldown(self, event=None):
        """Double-click handler on td_tree -> popup with full breakdown."""
        if not getattr(self, "_td_name_id", None):
            self.audit_log(
                "TD: Click 'Fetch TD Data' first, then double-click a row.",
                "warn")
            return
        sel = self.td_tree.selection()
        if not sel:
            return
        name = self.td_tree.item(sel[0], "text") or ""
        if name.startswith("--") or not name:
            return
        uid = self._td_name_id.get(name, "")
        if not uid:
            self.audit_log("TD: No user ID for " + name, "warn")
            return
        tok = getattr(self, "_td_api_token", "") or \
              load_config().get("td_token", "")
        if not tok:
            self.audit_log("TD: No token — login first.", "warn")
            return
        sel_date = getattr(self, "_td_last_date", None) or \
                   self.audit_date.get_date().strftime("%Y-%m-%d")
        self.audit_log(
            "TD: Loading breakdown for " + name + "...", "info")
        threading.Thread(
            target=self._td_drilldown_thread,
            args=(tok, sel_date, uid, name),
            daemon=True,
        ).start()

    def _td_drilldown_thread(self, tok, sel_date, uid, name):
        """Background: fetch worklog + timeuse events, compute, open popup."""
        import requests as _req
        from datetime import datetime as _dt, timedelta as _td
        from collections import defaultdict
        try:
            BASE    = "https://api2.timedoctor.com/api"
            company = "aTUbMi6uG2kPZzUD"
            _sel = _dt.strptime(sel_date, "%Y-%m-%d")
            dt_from = (_sel - _td(days=1)).strftime("%Y-%m-%d") + "T19:00:00"
            dt_to   = _sel.strftime("%Y-%m-%d") + "T19:00:00"

            def _to_local(utc_str):
                try:
                    u = _dt.fromisoformat(utc_str.replace("Z", "+00:00"))
                    return u.replace(tzinfo=None) + _td(hours=5)   # PKT
                except Exception:
                    return None

            def _is_blocked(title, value):
                hay = ((title or "") + " " + (value or "")).lower()
                for kw in _TD_BLOCKLIST:
                    if kw in hay:
                        return True
                return False

            # ── 1. Worklog (segments for idle-gap detection) ─────────────────
            wr = _req.get(
                BASE + "/1.0/activity/worklog",
                params={"company": company, "token": tok,
                        "from": dt_from, "to": dt_to, "user": uid,
                        "task-project-names": "true"},
                timeout=30)
            wdata = wr.json().get("data", [])
            segs = wdata[0] if wdata and isinstance(wdata[0], list) else wdata
            parsed = []
            for s in segs:
                st = _to_local(s.get("start", ""))
                if not st:
                    continue
                parsed.append(
                    (st, st + _td(seconds=int(s.get("time", 0) or 0))))
            parsed.sort(key=lambda x: x[0])

            idle = []
            prev_end = None
            for st, en in parsed:
                if prev_end is not None:
                    gap = (st - prev_end).total_seconds()
                    if gap >= 180:      # 3 min threshold
                        idle.append({
                            "from":  prev_end.strftime("%H:%M"),
                            "to":    st.strftime("%H:%M"),
                            "secs":  int(gap),
                            "_from_dt": prev_end,   # internal: for office filter
                            "_to_dt":   st,
                            "kind": "offline",  # PC locked / TD closed
                        })
                prev_end = en

            # ── 1a. Disconnectivity (hard disconnects: shutdown, net drop) ───
            # /api/1.0/activity/disconnectivity returns periods when the user
            # was hard-disconnected (PC off, internet lost, TD app crashed).
            # These are DIFFERENT from soft gaps in worklog — a worklog gap
            # might just mean TD wasn't tracking; a disconnect means the
            # device couldn't track if it wanted to. Useful for "the PC was
            # off, not avoiding work" distinction.
            try:
                dcr = _req.get(
                    BASE + "/1.0/activity/disconnectivity",
                    params={
                        "company": company,
                        "token": tok,
                        "from": dt_from,
                        "to": dt_to,
                        "user": uid,
                    },
                    timeout=30)
                dcdata = dcr.json().get("data", []) or []
                dc_segs = (dcdata[0]
                           if dcdata
                              and isinstance(dcdata[0], list)
                           else dcdata)
                added = 0
                for d in dc_segs:
                    if not isinstance(d, dict):
                        continue
                    st_dc = _to_local(d.get("start", ""))
                    en_dc = _to_local(d.get("end", ""))
                    if not st_dc:
                        continue
                    if not en_dc:
                        # Some records use start + time (duration)
                        dur_s = int(d.get("time", 0) or 0)
                        if dur_s <= 0:
                            continue
                        en_dc = st_dc + _td(seconds=dur_s)
                    secs = int((en_dc - st_dc).total_seconds())
                    if secs < 180:        # <3min — skip
                        continue
                    # Dedupe: if any existing idle entry overlaps
                    # significantly with this disconnect, upgrade its
                    # kind to "disconnect" rather than adding duplicate.
                    upgraded = False
                    for i in idle:
                        if (st_dc < i["_to_dt"]
                            and en_dc > i["_from_dt"]):
                            ovl = _td_overlap_seconds(
                                st_dc, en_dc,
                                i["_from_dt"], i["_to_dt"])
                            # ≥80% overlap → upgrade the existing entry
                            if ovl >= 0.8 * i["secs"]:
                                i["kind"] = "disconnect"
                                upgraded = True
                                break
                    if upgraded:
                        continue
                    idle.append({
                        "from": st_dc.strftime("%H:%M"),
                        "to":   en_dc.strftime("%H:%M"),
                        "secs": secs,
                        "_from_dt": st_dc,
                        "_to_dt":   en_dc,
                        "kind": "disconnect",
                    })
                    added += 1
                if added or (
                  dc_segs and isinstance(dc_segs, list)):
                    self.after(0, lambda a=added,
                        n=len(dc_segs):
                        self.audit_log(
                          "TD disconnectivity: " + str(a)
                          + " new entries (of " + str(n)
                          + " returned)", "info"))
            except Exception as _dc_err:
                self.after(0, lambda _e=str(_dc_err)[:120]:
                    self.audit_log(
                      "TD disconnectivity failed (continuing): "
                      + _e, "warn"))

            # ── 1b. Per-hour stats (within-session idle detection) ───────────
            # TimeDoctor's per-minute endpoint returns empty (a known TD
            # limitation — minute-level data isn't exposed publicly).
            # Per-hour with group-by=date IS available and reliable.
            #
            # We use it to:
            #   1. Detect hours with heavy idle (within-session idle that
            #      worklog gaps don't catch — keyboard/mouse inactive
            #      while TD was tracking)
            #   2. Enrich existing worklog gaps with hour-level activity
            #      counts (keys/clicks/moves) so per-instance entries
            #      get an "Activity" column showing what was happening
            #
            # Hour-buckets give ~1-hour precision for within-session idle.
            # Worklog gaps still provide minute precision for offline gaps.
            self._td_hour_activity = {}   # hour_ts -> dict
            try:
                sr = _req.get(
                    BASE + "/1.1/stats/total",
                    params={
                        "company": company, "token": tok,
                        "from": dt_from, "to": dt_to,
                        "user": uid,
                        "period": "hours",
                        "interval": 1,
                        "group-by": "date",
                        "limit": 200,
                        # idleMins is the TRUE idle field (matches the
                        # main table's idleMins for the user). idleSec
                        # from /stats/total at hour granularity returns
                        # something different (possibly non-productive
                        # time including in-tracked-app idle). Confirmed
                        # by probe: idleMins summed across hours equals
                        # the daily idle figure reported in main table.
                        "fields": ("userId,idleMins,activeSec,"
                                    "total,keys,clicks,moves,"
                                    "idleSecMeeting"),
                    },
                    timeout=30)
                sdata = sr.json().get("data", []) or []
                hour_rows = []
                for rec in sdata:
                    if not isinstance(rec, dict):
                        continue
                    ts_str = (rec.get("date")
                              or rec.get("start")
                              or rec.get("from")
                              or "")
                    if not ts_str:
                        continue
                    ts_local = _to_local(ts_str)
                    if not ts_local:
                        continue
                    # Round to hour
                    hr_key = ts_local.replace(
                        minute=0, second=0, microsecond=0)
                    # Convert idleMins → idleSec for consistency with
                    # the rest of the code (everything else is in secs)
                    idle_min_h = int(
                        rec.get("idleMins", 0) or 0)
                    idle_sec_h = idle_min_h * 60
                    k_h = int(rec.get("keys", 0) or 0)
                    c_h = int(rec.get("clicks", 0) or 0)
                    m_h = int(rec.get("moves", 0) or 0)
                    total_h = int(rec.get("total", 3600) or 3600)
                    mt_h = int(
                        rec.get("idleSecMeeting", 0) or 0)
                    self._td_hour_activity[hr_key] = {
                        "idle_s":  idle_sec_h,
                        "keys":    k_h,
                        "clicks":  c_h,
                        "moves":   m_h,
                        "total_s": total_h,
                        "mt_idle_s": mt_h,
                    }
                    hour_rows.append(
                        (hr_key, idle_sec_h, total_h))
                hour_rows.sort(key=lambda r: r[0])

                # Build synthetic "hour-bucket" idle entries for hours
                # with significant idle. With idleMins, threshold is in
                # minutes-equivalent. Lowered threshold to 10 min since
                # idleMins is exact (was 30 min when using inflated
                # idleSec). Hours with ≥10 min real idle get a row in
                # per-instance gaps (unless already covered by worklog
                # gap or disconnectivity).
                HOUR_IDLE_THRESH = 600    # 10 min
                for hr_ts, idle_s_h, total_s_h in hour_rows:
                    if idle_s_h < HOUR_IDLE_THRESH:
                        continue
                    hr_end = hr_ts + _td(hours=1)
                    # Skip if this hour is already mostly covered by
                    # a worklog gap or disconnect entry (≥50% overlap)
                    already_covered = False
                    for it in idle:
                        ovl = _td_overlap_seconds(
                            hr_ts, hr_end,
                            it["_from_dt"], it["_to_dt"])
                        if ovl >= idle_s_h * 0.5:
                            already_covered = True
                            break
                    if already_covered:
                        continue
                    # Add hour-bucket entry
                    idle.append({
                        "from": hr_ts.strftime("%H:%M"),
                        "to":   hr_end.strftime("%H:%M"),
                        "secs": idle_s_h,
                        "_from_dt": hr_ts,
                        "_to_dt":   hr_end,
                        "kind": "within_session",
                        "hour_bucket": True,
                    })

                # Re-sort
                idle.sort(key=lambda x: x["_from_dt"])
                self.after(0, lambda c=len(self._td_hour_activity):
                    self.audit_log(
                        "TD per-hour stats: " + str(c)
                        + " hour buckets cached", "info"))
            except Exception as _stats_err:
                # Non-fatal — old gap-only detection still works
                self.after(0, lambda _e=str(_stats_err)[:120]:
                    self.audit_log(
                        "TD per-hour stats failed (continuing): "
                        + _e, "warn"))

            active_s   = sum(int((en - st).total_seconds())
                             for st, en in parsed)
            idle_s     = sum(i["secs"] for i in idle)
            work_start = parsed[0][0].strftime("%H:%M") if parsed else "--"
            work_end   = parsed[-1][1].strftime("%H:%M") if parsed else "--"

            # ── Office-hour aware buckets ────────────────────────────────────
            # Splits the day into:
            #   • office_active_s : active time during 10:00–18:00 PKT
            #                       (lunch overlap subtracted)
            #   • extra_active_s  : active time outside office hours
            #                       (early morning / late evening / Friday)
            #   • office_idle_s   : idle gaps inside office hours
            #                       (lunch overlap subtracted — lunch is
            #                        not "idle", it's a planned break)
            #   • idle_in_office  : the subset of `idle` entries that overlap
            #                       office hours (used in the popup table)
            os_dt, oe_dt, ls_dt, le_dt = _td_office_window(_sel)
            is_off_day = (os_dt == oe_dt)   # Friday produces zero-width window

            office_active_s = 0
            extra_active_s = 0
            if is_off_day:
                # All work is "extra" on the off day
                extra_active_s = active_s
            else:
                for st, en in parsed:
                    in_office = _td_overlap_seconds(
                        st, en, os_dt, oe_dt)
                    # Don't deduct lunch from active work — if someone was
                    # actively working through lunch, that's still real work.
                    office_active_s += in_office
                    extra_active_s += int(
                        (en - st).total_seconds()) - in_office

            office_idle_s = 0
            idle_in_office = []
            if not is_off_day:
                for i in idle:
                    g_from = i["_from_dt"]
                    g_to   = i["_to_dt"]
                    is_hr_bkt = i.get(
                        "hour_bucket", False)
                    in_office_gap = _td_overlap_seconds(
                        g_from, g_to, os_dt, oe_dt)
                    if in_office_gap <= 0:
                        continue
                    # Subtract lunch overlap — lunch is a legit break,
                    # not idle.
                    lunch_overlap = _td_overlap_seconds(
                        max(g_from, os_dt),
                        min(g_to, oe_dt),
                        ls_dt, le_dt)
                    if is_hr_bkt:
                        # Hour-bucket entries: secs is the ACTUAL idle
                        # within the hour, but _from/_to span the full
                        # hour. So in_office_gap (window overlap) would
                        # over-count. Use the entry's secs directly,
                        # capped to whatever fraction of the hour fell
                        # inside the office window.
                        full_hr_secs = max(1, int(
                            (g_to - g_from)
                            .total_seconds()))
                        office_frac = (
                            in_office_gap / full_hr_secs)
                        # Prorate the real idle by office overlap %
                        real_office_idle = int(
                            i["secs"] * office_frac)
                        # No lunch trim for hour buckets — idle is
                        # already a sum within the hour, doesn't
                        # span specific minutes
                    else:
                        real_office_idle = (
                            in_office_gap - lunch_overlap)
                    if real_office_idle < 180:   # below threshold after lunch trim
                        continue
                    office_idle_s += real_office_idle
                    # Build a cleaned entry for the popup table
                    idle_in_office.append({
                        "from":  g_from.strftime("%H:%M"),
                        "to":    g_to.strftime("%H:%M"),
                        "secs":  real_office_idle,
                        "raw_secs": i["secs"],
                        "lunch_subtracted": (
                            lunch_overlap > 0
                            and not is_hr_bkt),
                    })

            # ── Compute TD reported idle (separate from per-instance) ────────
            # TD's idleMins includes idle WITHIN tracked sessions (keyboard/
            # mouse inactivity ≥3min while a session is open) — which the
            # gap-based math above can't see. The main table shows this figure
            # so the drill-down must too. Prorate office-hour share by the
            # ratio of office-active work to total active work.
            #
            # IMPORTANT: This does NOT overwrite idle_in_office (the real
            # per-instance gaps). It builds a SEPARATE summary row used only
            # by the TD Summary view, so Per-instance gaps still shows the
            # actual gap list — matching the older popup's behavior.
            td_reported_idle_s = 0
            if uid and hasattr(self, "_td_stats_by_id"):
                _td_stat = self._td_stats_by_id.get(uid, {})
                td_reported_idle_s = _td_stat.get("idle_s", 0) or 0

            td_summary_row = None
            if td_reported_idle_s > 0 and not is_off_day:
                if active_s > 0 and office_active_s > 0:
                    # Prorate idle to office hours by office_active share
                    office_share = office_active_s / active_s
                    office_idle_s_summary = int(
                        td_reported_idle_s * office_share)
                elif parsed:
                    # User worked entirely outside office hours.
                    # Use clock overlap of work span vs office window.
                    span_start = parsed[0][0]
                    span_end = parsed[-1][1]
                    span_s = max(
                        1,
                        int((span_end - span_start).total_seconds()))
                    span_office_s = _td_overlap_seconds(
                        span_start, span_end, os_dt, oe_dt)
                    if span_office_s > 0:
                        clock_share = span_office_s / span_s
                        office_idle_s_summary = int(
                            td_reported_idle_s * clock_share)
                    else:
                        office_idle_s_summary = 0
                else:
                    office_idle_s_summary = td_reported_idle_s
                # Override office_idle_s with the TD-prorated figure
                # ONLY if per-instance gaps detected less than TD reports
                # (typical case — within-session idle is the difference)
                if office_idle_s_summary > office_idle_s:
                    office_idle_s = office_idle_s_summary
                # Build a SUMMARY row used by TD Summary view only
                td_summary_row = {
                    "from":  os_dt.strftime("%H:%M"),
                    "to":    oe_dt.strftime("%H:%M"),
                    "secs":  office_idle_s_summary,
                    "raw_secs": td_reported_idle_s,
                    "lunch_subtracted": False,
                    "td_reported": True,
                }
            elif td_reported_idle_s > 0 and is_off_day:
                pass   # off day: nothing counts as office idle

            # Within-session idle = TD's total idle minus visible
            # between-session gaps. This is the bulk of Muhammad's
            # 544m — keyboard/mouse inactive while TD session was open.
            visible_gap_s = sum(i.get("secs", 0) or 0
                                for i in (idle or []))
            within_session_idle_s = max(
                0, td_reported_idle_s - visible_gap_s)
            continuous_session = (
                td_reported_idle_s > 0 and
                visible_gap_s < 60)  # less than 1 min of visible gaps

            # Office window text for the popup header
            if is_off_day:
                office_window_txt = "Off day (no office hours)"
            else:
                office_window_txt = (
                    "Office: "
                    + os_dt.strftime("%H:%M")
                    + " → " + oe_dt.strftime("%H:%M")
                    + "  ·  Lunch: "
                    + ls_dt.strftime("%H:%M")
                    + " → " + le_dt.strftime("%H:%M"))

            # ── 2. Raw event stream (for bars + top apps) ────────────────────
            er = _req.get(
                BASE + "/1.0/activity/timeuse",
                params={"company": company, "token": tok,
                        "from": dt_from, "to": dt_to, "user": uid},
                timeout=60)
            edata = er.json().get("data", [])
            evs = edata[0] if edata and isinstance(edata[0], list) else edata

            hour_total = defaultdict(int)
            hour_prod  = defaultdict(int)
            app_time   = defaultdict(int)
            # Grouped breakdown: {group_name: {"secs": int, "apps": {app: secs}}}
            group_data = {}
            for gname, _col, _kws in _TD_GROUPS:
                group_data[gname] = {"secs": 0, "apps": defaultdict(int)}
            group_data["Other"] = {"secs": 0, "apps": defaultdict(int)}

            def _classify(hay):
                """Return group name for a lowered title+value string."""
                for gname, _col, kws in _TD_GROUPS:
                    for kw in kws:
                        if kw in hay:
                            return gname
                return "Other"

            for e in evs:
                t = _to_local(e.get("start", ""))
                if not t:
                    continue
                secs = int(e.get("time", 0) or 0)
                if secs <= 0:
                    continue
                h = t.strftime("%H")
                title  = e.get("title", "") or ""
                value  = e.get("value", "") or ""
                blocked = _is_blocked(title, value)
                hour_total[h] += secs
                if not blocked:
                    hour_prod[h] += secs
                    key = title.strip() or value.strip() or "?"
                    for suf in (" - Google Chrome",
                                " - Mozilla Firefox",
                                " - Microsoft Edge"):
                        if key.endswith(suf):
                            key = key[: -len(suf)]
                    key = key[:45]
                    app_time[key] += secs
                    # Classify into group
                    hay = (title + " " + value).lower()
                    gname = _classify(hay)
                    group_data[gname]["secs"] += secs
                    group_data[gname]["apps"][key] += secs

            all_hours = sorted(set(list(hour_total.keys())
                                   + list(hour_prod.keys())))
            # Hourly tuples in seconds (so sub-minute activity still shows)
            hourly = [(h, hour_total[h], hour_prod[h])
                      for h in all_hours]
            # Also keep the dicts so popup can fill empty hours
            self._td_last_hour_total = dict(hour_total)
            self._td_last_hour_prod  = dict(hour_prod)

            top_apps = sorted(app_time.items(),
                              key=lambda x: -x[1])[:10]
            top_apps = [(k, v) for k, v in top_apps if v >= 60]

            # Build sorted, non-empty list of groups for display
            groups_out = []
            for gname, gcol, _kws in _TD_GROUPS:
                gd = group_data[gname]
                if gd["secs"] > 0:
                    groups_out.append((gname, gcol, gd["secs"],
                                       dict(gd["apps"])))
            # Add "Other" last if non-empty
            other = group_data["Other"]
            if other["secs"] > 0:
                groups_out.append(("Other", "#9aa5be",
                                   other["secs"],
                                   dict(other["apps"])))
            # Sort by time descending
            groups_out.sort(key=lambda x: -x[2])

            self.after(0, lambda: self._td_drilldown_popup(
                name, sel_date, work_start, work_end,
                active_s, idle_s, idle, hourly, groups_out,
                office_active_s, office_idle_s, extra_active_s,
                idle_in_office, office_window_txt,
                within_session_idle_s, continuous_session,
                td_reported_idle_s, td_summary_row))

        except Exception as e:
            err = str(e)
            self.after(0, lambda: self.audit_log(
                "TD drilldown error: " + err, "err"))

    def _td_drilldown_popup(self, name, sel_date, work_start, work_end,
                             active_s, idle_s, idle, hourly, groups_out,
                             office_active_s=0, office_idle_s=0,
                             extra_active_s=0, idle_in_office=None,
                             office_window_txt="",
                             within_session_idle_s=0,
                             continuous_session=False,
                             td_reported_idle_s=0,
                             td_summary_row=None):
        """Build the Toplevel window. Runs on main UI thread only."""

        if idle_in_office is None:
            idle_in_office = []

        def fmt(sec):
            h, r = divmod(int(sec), 3600)
            m, s = divmod(r, 60)
            if h:
                return str(h) + "h " + str(m).zfill(2) + "m"
            return str(m) + "m " + str(s).zfill(2) + "s"

        win = tk.Toplevel(self)
        win.title("Activity Breakdown — " + name)
        win.configure(bg=C["page"])
        win.geometry("680x780")
        win.transient(self)

        # ── Header ───────────────────────────────────────────────────────────
        hdr = tk.Frame(win, bg=C["white"])
        hdr.pack(fill="x", padx=14, pady=(14, 8))
        tk.Label(hdr, text=name,
                 font=("Segoe UI", 13, "bold"),
                 bg=C["white"], fg=C["text"]).pack(
            anchor="w", padx=14, pady=(12, 0))
        tk.Label(hdr,
                 text=sel_date + "   ·   Work window: "
                      + work_start + " → " + work_end,
                 font=("Segoe UI", 9),
                 bg=C["white"], fg=C["text3"]).pack(
            anchor="w", padx=14, pady=(0, 10))

        # ── TD-style strip: mini timeline + Worked/Started/Finished ──────────
        td_strip = tk.Frame(win, bg=C["white"])
        td_strip.pack(fill="x", padx=14, pady=(0, 10))

        # 24-hour mini timeline canvas spanning whole day
        mini_h = 28
        mini = tk.Canvas(td_strip, bg=C["white"],
                          height=mini_h, bd=0,
                          highlightthickness=0)
        mini.pack(fill="x", padx=14, pady=(8, 4))

        def _hr_to_min(hhmm):
            try:
                hh, mm = hhmm.split(":")
                return int(hh) * 60 + int(mm)
            except Exception:
                return 0

        def _mini_redraw(event=None):
            mini.delete("all")
            w = mini.winfo_width() or 600
            day_min = 24 * 60
            # Background track (light grey)
            mini.create_rectangle(
                0, 6, w, mini_h - 6,
                fill=C["input2"], outline="")
            # Activity blocks (one per active hour, scaled)
            for hh, secs in (
                getattr(self, "_td_last_hour_total", {})
                or {}).items():
                if secs <= 0:
                    continue
                start_min = int(hh) * 60
                end_min = start_min + 60
                x1 = w * start_min / day_min
                x2 = w * end_min / day_min
                # Use productive shade if mostly productive
                prd = (getattr(self, "_td_last_hour_prod", {})
                       or {}).get(hh, 0)
                col = C["green"] if prd > secs * 0.6 \
                    else C["green_l"]
                mini.create_rectangle(
                    x1, 6, x2, mini_h - 6,
                    fill=col, outline="")
            # Hour ticks every 2 hours
            for h in range(0, 25, 2):
                x = w * (h * 60) / day_min
                mini.create_text(
                    x, mini_h - 2, anchor="s",
                    text=str(h), fill=C["text4"],
                    font=("Segoe UI", 7))
        mini.bind("<Configure>", _mini_redraw)
        win.after(50, _mini_redraw)

        # Worked / Started / Finished labels row (matches TD widget)
        ws_row = tk.Frame(td_strip, bg=C["white"])
        ws_row.pack(fill="x", padx=14, pady=(2, 8))

        def _stat_inline(parent, lbl, val, anchor_side):
            f = tk.Frame(parent, bg=C["white"])
            f.pack(side=anchor_side, padx=4)
            tk.Label(f, text=lbl, font=("Segoe UI", 8),
                     bg=C["white"], fg=C["text4"]).pack(
                side="left", padx=(0, 4))
            tk.Label(f, text=val,
                     font=("Segoe UI", 9, "bold"),
                     bg=C["white"], fg=C["text"]).pack(
                side="left")

        _stat_inline(ws_row, "Worked:",
                     fmt(active_s), "left")
        _stat_inline(ws_row, "Finished:",
                     work_end, "right")
        _stat_inline(ws_row, "Started:",
                     work_start, "right")

        # Office-hours subtitle (Pakistan time, Sat-Thu, lunch excluded)
        if office_window_txt:
            tk.Label(td_strip,
                     text=office_window_txt,
                     font=("Segoe UI", 8),
                     bg=C["white"],
                     fg=C["text3"]).pack(
                anchor="w", padx=14, pady=(0, 6))

        # Subtle separator
        tk.Frame(td_strip, bg=C["border"], height=1).pack(
            fill="x", padx=14)

        # ── Summary cards (office-aware) ─────────────────────────────────────
        # Replaces the old "overall idle" cards. The user only wants idle
        # counted DURING office hours (10:00–18:00 PKT, Sat–Thu, minus lunch
        # 14:30–15:30). Time outside office hours = voluntary extra work.
        cards = tk.Frame(win, bg=C["page"])
        cards.pack(fill="x", padx=14, pady=(0, 10))
        for i in range(4):
            cards.columnconfigure(i, weight=1, uniform="c")

        def _stat(col, lbl, val, accent=C["text"]):
            f = tk.Frame(cards, bg=C["input"])
            f.grid(row=0, column=col, sticky="ew", padx=3)
            tk.Label(f, text=lbl, font=("Segoe UI", 8),
                     bg=C["input"], fg=C["text3"]).pack(
                anchor="w", padx=10, pady=(8, 0))
            tk.Label(f, text=val,
                     font=("Segoe UI", 14, "bold"),
                     bg=C["input"], fg=accent).pack(
                anchor="w", padx=10, pady=(0, 8))

        # Color office_idle aggressively — that's the metric that matters
        office_idle_accent = (
            C["red"]   if office_idle_s >= 3600 else
            C["amber"] if office_idle_s >= 1800 else
            C["text"])
        extra_accent = (
            C["green"] if extra_active_s > 0
            else C["text3"])

        _stat(0, "Office Working",
              fmt(office_active_s))
        _stat(1, "Office Idle",
              fmt(office_idle_s),
              office_idle_accent)
        _stat(2, "Extra Working",
              fmt(extra_active_s),
              extra_accent)
        _stat(3, "Work span",
              work_start + "→" + work_end[:5])

        # ── Idle breakdown — switchable view (3 modes) ───────────────────────
        # Mode 1: TD Summary  → single row matching the main table figure
        # Mode 2: Per-instance gaps → between-session gaps with from/to
        # Mode 3: Hourly breakdown  → idle minutes per hour
        # Modes can differ because TD has TWO idle definitions:
        #   • Within-session idle (no keyboard/mouse for 3min during tracked
        #     session) — visible in TD totals but NOT in event timeline
        #   • Between-session idle (PC locked / app closed) — visible as
        #     gaps between events. This is what modes 2 and 3 detect.
        # Mode 1 ≈ Mode 2 + within-session idle (often much larger).

        # Pre-compute per-hour idle in office hours.
        # PRIORITY 1: Use _td_hour_activity (authoritative TD per-hour
        # idleMins data — matches main table figure exactly).
        # PRIORITY 2: Fall back to deriving from gap list if hour data
        # missing for some reason.
        per_hour_idle_secs = {}
        _hr_act = getattr(
            self, "_td_hour_activity", {}) or {}
        if _hr_act:
            for hr_ts, rec in _hr_act.items():
                idle_s = rec.get("idle_s", 0) or 0
                if idle_s > 0:
                    per_hour_idle_secs[hr_ts.hour] = (
                        per_hour_idle_secs.get(
                            hr_ts.hour, 0) + idle_s)
        else:
            # Fallback: derive from gap entries (legacy)
            for i in (idle_in_office or []):
                if i.get("td_reported"):
                    continue   # synthesized row
                try:
                    fh = int(i["from"].split(":")[0])
                    th = int(i["to"].split(":")[0])
                except Exception:
                    continue
                sec_left = int(i.get("secs", 0) or 0)
                hh = fh
                while sec_left > 0 and hh <= th:
                    per_hour_idle_secs[hh] = (
                        per_hour_idle_secs.get(hh, 0)
                        + sec_left)
                    break

        idle_header = tk.Frame(win, bg=C["page"])
        idle_header.pack(fill="x", padx=18, pady=(4, 4))
        tk.Label(idle_header, text="Idle breakdown",
                 font=("Segoe UI", 9, "bold"),
                 bg=C["page"], fg=C["text2"]).pack(side="left")

        idle_mode_var = tk.StringVar(value="td_summary")

        radio_row = tk.Frame(win, bg=C["page"])
        radio_row.pack(fill="x", padx=18, pady=(0, 6))
        for val, lbl in [
            ("td_summary",   "TD Summary"),
            ("gap_instances","Per-instance gaps"),
            ("hourly",       "Hourly breakdown"),
        ]:
            tk.Radiobutton(
                radio_row, text=lbl,
                variable=idle_mode_var, value=val,
                bg=C["page"], fg=C["text2"],
                activebackground=C["page"],
                selectcolor=C["white"],
                font=("Segoe UI", 9),
                command=lambda: _render_idle_view()
            ).pack(side="left", padx=(0, 12))

        # Container that gets rebuilt on view change
        idle_box = tk.Frame(win, bg=C["page"])
        idle_box.pack(fill="x", padx=14, pady=(0, 4))

        # Footer caption (rebuilds per-mode)
        idle_note = tk.Label(win, text="",
                              font=("Segoe UI", 8, "italic"),
                              bg=C["page"], fg=C["text4"],
                              wraplength=900, justify="left")
        idle_note.pack(anchor="w", padx=18, pady=(0, 8))

        def _clear_idle_box():
            for w in idle_box.winfo_children():
                w.destroy()

        def _build_table_view():
            """Common Treeview widget used by view 1 and 2."""
            tbl_o2 = tk.Frame(idle_box, bg=C["border"],
                              padx=1, pady=1)
            tbl_o2.pack(fill="x")
            tbl2 = ttk.Treeview(tbl_o2, style="TD.Treeview",
                                columns=("from", "to", "dur", "note"),
                                show="headings", height=6)
            for col, txt, w, anc in [
                ("from", "From",     80,  "center"),
                ("to",   "To",       80,  "center"),
                ("dur",  "Duration", 120, "center"),
                ("note", "Note",     300, "w"),
            ]:
                tbl2.heading(col, text=txt)
                tbl2.column(col, width=w, anchor=anc,
                            stretch=(col == "note"))
            tbl2.tag_configure("red",
                              background=C["red_l"], foreground=C["red"])
            tbl2.tag_configure("amber",
                              background=C["amber_l"], foreground=C["amber"])
            tbl2.tag_configure("norm",
                              background=C["input"], foreground=C["text2"])
            tbl2.pack(fill="x")
            return tbl2

        def _build_gap_table_6col():
            """6-column Treeview for Per-instance gaps view.
            Columns: From | To | Duration | Kind | Activity | Context.
            Activity shows keys/clicks/moves during the idle period.
            Context shows interpretation + suspicion score + meeting flag.
            """
            tbl_o6 = tk.Frame(idle_box, bg=C["border"],
                              padx=1, pady=1)
            tbl_o6.pack(fill="x")
            tbl6 = ttk.Treeview(
                tbl_o6, style="TD.Treeview",
                columns=("from", "to", "dur",
                         "kind", "act", "ctx"),
                show="headings", height=8)
            for col, txt, w, anc, stretch in [
                ("from", "From",     65,  "center", False),
                ("to",   "To",       65,  "center", False),
                ("dur",  "Duration", 85,  "center", False),
                ("kind", "Kind",     150, "w",      False),
                ("act",  "Activity", 165, "w",      False),
                ("ctx",  "Context",  280, "w",      True),
            ]:
                tbl6.heading(col, text=txt)
                tbl6.column(col, width=w, anchor=anc,
                            stretch=stretch)
            tbl6.tag_configure("red",
                background=C["red_l"], foreground=C["red"])
            tbl6.tag_configure("amber",
                background=C["amber_l"], foreground=C["amber"])
            tbl6.tag_configure("norm",
                background=C["input"], foreground=C["text2"])
            tbl6.pack(fill="x")
            return tbl6

        def _enrich_idle(i):
            """Pull activity counters from the hour bucket(s) the
            idle period overlaps. Returns (keys, clicks, moves, mt_s).
            For partial hours, prorates by overlap fraction so the
            counts represent JUST the idle period (not the full hour).
            """
            ha = getattr(self, "_td_hour_activity", {}) or {}
            if not ha:
                return 0, 0, 0, 0
            g_from = i.get("_from_dt")
            g_to   = i.get("_to_dt")
            if not g_from or not g_to:
                return 0, 0, 0, 0
            period_s = max(1, int(
                (g_to - g_from).total_seconds()))
            k_sum = c_sum = m_sum = 0
            mt_sum = 0
            from datetime import timedelta as _td2
            cur_hr = g_from.replace(
                minute=0, second=0, microsecond=0)
            while cur_hr < g_to:
                rec = ha.get(cur_hr)
                if rec:
                    hr_end = cur_hr + _td2(hours=1)
                    ovl_s = max(0, int((min(g_to, hr_end)
                        - max(g_from, cur_hr))
                        .total_seconds()))
                    if ovl_s > 0:
                        # Prorate: hour totals × (overlap / 3600)
                        frac = ovl_s / 3600.0
                        k_sum += int(rec["keys"] * frac)
                        c_sum += int(rec["clicks"] * frac)
                        m_sum += int(rec["moves"] * frac)
                        mt_sum += int(
                            rec.get("mt_idle_s", 0) * frac)
                cur_hr += _td2(hours=1)
            return k_sum, c_sum, m_sum, mt_sum

        def _suspicion(secs, keys, clicks, moves, kind):
            """0-100 score. 0 = fully idle (most suspicious),
            100 = lots of activity (least suspicious).
            For 'disconnect' kind we don't score — it's explained."""
            if kind == "disconnect":
                return None
            # Normalize to per-minute rates
            mins = max(1, secs // 60)
            kpm = keys   / mins
            cpm = clicks / mins
            mpm = moves  / mins
            # Weighted: keys most meaningful, then clicks, then moves
            raw = (kpm * 2.0) + (cpm * 1.5) + (mpm * 0.3)
            # Cap and scale to 0-100
            score = min(100, int(raw))
            return score

        def _render_td_summary():
            tbl2 = _build_table_view()
            # TD Summary shows the TD-reported daily idle figure
            # (within-session idle is included). If present, show ONLY
            # the synthesized summary row. Otherwise fall back to the
            # per-instance office gaps (matches older popup behavior).
            display_rows = []
            if td_summary_row is not None:
                display_rows = [td_summary_row]
            else:
                display_rows = idle_in_office or []

            if not display_rows:
                tbl2.insert("", "end",
                            values=("—", "—", "—",
                                    "No idle reported by TimeDoctor"),
                            tags=("norm",))
            else:
                for i in display_rows:
                    sec = i["secs"]
                    if i.get("td_reported"):
                        tag = ("red" if sec >= 3600
                               else "amber" if sec >= 1800
                               else "norm")
                        raw_min = (i.get("raw_secs", 0) or 0) // 60
                        note = ("TD-reported idle (totals " +
                                str(raw_min) +
                                "m for the day; office share shown)")
                    else:
                        if sec >= 1800:
                            tag, note = "red", "Long idle"
                        elif sec >= 900:
                            tag, note = "amber", "Extended idle"
                        else:
                            tag, note = "norm", "Short break"
                        if i.get("lunch_subtracted"):
                            note = note + " (lunch trimmed)"
                    tbl2.insert("", "end",
                                values=(i["from"], i["to"],
                                        fmt(sec), note),
                                tags=(tag,))
            idle_note.config(
                text="TD Summary shows TimeDoctor's daily idle total "
                     "(includes within-session idle — keyboard/mouse "
                     "inactivity during a tracked session). Matches "
                     "the main table figure exactly. TD's API only "
                     "reports a daily total here, not per-gap times.")

        def _render_gap_instances():
            # 6-column table: From | To | Duration | Kind | Activity | Context
            tbl6 = _build_gap_table_6col()
            shown = 0
            for i in (idle or []):
                g_from = i.get("_from_dt")
                g_to   = i.get("_to_dt")
                if not g_from or not g_to:
                    continue
                in_off = _td_overlap_seconds(
                    g_from, g_to, os_dt, oe_dt)
                if in_off <= 0:
                    continue
                lunch_off = _td_overlap_seconds(
                    max(g_from, os_dt),
                    min(g_to, oe_dt),
                    ls_dt, le_dt)
                real = in_off - lunch_off
                if real < 180:
                    continue
                # Severity by duration
                if real >= 1800:
                    tag = "red"
                elif real >= 900:
                    tag = "amber"
                else:
                    tag = "norm"
                # Kind label
                kind = i.get("kind", "offline")
                hour_bucket = i.get("hour_bucket", False)
                if kind == "within_session":
                    if hour_bucket:
                        kind_lbl = "Within-session (hour)"
                    else:
                        kind_lbl = "Keyboard/mouse inactive"
                elif kind == "disconnect":
                    kind_lbl = "PC off / internet lost"
                else:
                    kind_lbl = "PC locked / TD closed"
                # Activity intensity from per-minute index
                k_n, c_n, m_n, mt_s = _enrich_idle(i)
                act_lbl = ("k:" + str(k_n)
                          + "  c:" + str(c_n)
                          + "  m:" + str(m_n))
                # Suspicion score (0-100, lower = more suspicious)
                score = _suspicion(real, k_n, c_n, m_n, kind)
                # Context: interpretation + meeting flag + lunch
                ctx_parts = []
                if kind == "disconnect":
                    ctx_parts.append("Hard disconnect")
                elif score is not None:
                    if score == 0:
                        ctx_parts.append("🚨 Fully away")
                    elif score < 10:
                        ctx_parts.append("Mostly away")
                    elif score < 30:
                        ctx_parts.append("Passive (watching?)")
                    elif score < 60:
                        ctx_parts.append("Light activity")
                    else:
                        ctx_parts.append("Active in untracked app")
                    ctx_parts.append("score " + str(score))
                # Meeting overlap: if ≥30% of the period was meeting-idle
                if mt_s >= 0.3 * real:
                    ctx_parts.append("in meeting")
                if lunch_off > 0:
                    ctx_parts.append("lunch trimmed")
                ctx_lbl = " · ".join(ctx_parts)
                tbl6.insert("", "end",
                    values=(i["from"], i["to"],
                            fmt(real), kind_lbl,
                            act_lbl, ctx_lbl),
                    tags=(tag,))
                shown += 1
            if shown == 0:
                total_td_idle = sum(
                    int(i.get("raw_secs", 0) or 0)
                    for i in (idle_in_office or [])
                    if i.get("td_reported"))
                if total_td_idle > 0:
                    msg = ("Continuous TD session — no idle "
                           "periods ≥ 3 min detected. " +
                           str(total_td_idle // 60) +
                           "m idle reported daily "
                           "(see TD Summary).")
                else:
                    msg = ("No idle periods ≥ 3 min in "
                           "office hours.")
                tbl6.insert("", "end",
                    values=("—", "—", "—", "—", "—", msg),
                    tags=("norm",))
            total_gap_s = sum(i.get("secs", 0)
                              for i in (idle or []))
            idle_note.config(
                text="Per-instance idle (≥3 min) — three KINDS: "
                     "Keyboard/mouse inactive (sharp times from "
                     "worklog gaps), PC locked / TD closed (offline "
                     "gap), Within-session (hour) = hour with "
                     "≥30 min idle detected from hourly stats "
                     "(hour-level precision). ACTIVITY shows "
                     "k=keys, c=clicks, m=moves during the period "
                     "(prorated from hourly totals). CONTEXT shows "
                     "suspicion score 0–100; lower = more "
                     "suspicious. Total: " + fmt(total_gap_s) + ".")

        def _render_hourly():
            """Bar chart: idle minutes per hour in office hours."""
            ch_o = tk.Frame(idle_box, bg=C["white"],
                            bd=1, relief="solid",
                            highlightbackground=C["border"])
            ch_o.pack(fill="x")
            # Taller canvas (140 vs 110) gives label headroom above bars
            ch = tk.Canvas(ch_o, height=140, bg=C["white"],
                           highlightthickness=0)
            ch.pack(fill="x", padx=10, pady=10)

            def _draw_hourly(event=None):
                ch.delete("all")
                w_c = ch.winfo_width() or 600
                # Office hours range
                try:
                    o_start_h = _TD_OFFICE_START_H
                    o_end_h   = _TD_OFFICE_END_H
                except Exception:
                    o_start_h, o_end_h = 10, 18
                hrs = list(range(o_start_h, o_end_h))
                if not hrs:
                    ch.create_text(10, 60, anchor="w",
                                   text="No office hours",
                                   font=("Segoe UI", 9),
                                   fill=C["text3"])
                    return
                bar_w = max(20, (w_c - 30) / len(hrs) - 8)
                # Reserve 16px top for labels, 20px bottom for hour labels
                top_margin = 16   # space above the tallest bar for label
                bottom_y = 110    # bars sit on this y, hour labels go below
                max_bar_h = bottom_y - top_margin
                # Find max for scale
                max_min = max(
                    [per_hour_idle_secs.get(h, 0) / 60
                     for h in hrs] + [1])
                # Empty-state: if no idle data, show explanation
                has_any = any(
                    per_hour_idle_secs.get(h, 0) > 0
                    for h in hrs)
                if not has_any:
                    ch.create_text(
                        w_c / 2, bottom_y / 2 + 4,
                        text=("No per-hour idle data — "
                              "TD session was continuous"),
                        fill=C["text3"],
                        font=("Segoe UI", 9, "italic"))
                    # Draw faint axis labels anyway
                    for idx, h in enumerate(hrs):
                        x = 12 + idx * (bar_w + 8)
                        ch.create_text(
                            x + bar_w / 2, bottom_y + 14,
                            text=str(h) + ":00",
                            fill=C["text4"],
                            font=("Segoe UI", 8))
                    return
                for idx, h in enumerate(hrs):
                    x = 12 + idx * (bar_w + 8)
                    mins = per_hour_idle_secs.get(h, 0) / 60
                    bh = int(max_bar_h * mins / max_min) if max_min else 0
                    col = (C["red"] if mins >= 15
                           else C["amber"] if mins >= 5
                           else C["green_l"])
                    if bh > 0:
                        ch.create_rectangle(
                            x, bottom_y - bh,
                            x + bar_w, bottom_y,
                            fill=col, outline="")
                    # Smart label placement:
                    # - Bar tall enough (≥20px) → label INSIDE bar, white text
                    # - Bar short → label ABOVE bar, dark text
                    if mins >= 1:
                        if bh >= 20:
                            # Inside the bar
                            ch.create_text(
                                x + bar_w / 2,
                                bottom_y - bh + 10,
                                text=str(int(mins)) + "m",
                                fill=C["white"],
                                font=("Segoe UI", 9, "bold"))
                        else:
                            # Above the bar
                            ch.create_text(
                                x + bar_w / 2,
                                bottom_y - bh - 8,
                                text=str(int(mins)) + "m",
                                fill=C["text2"],
                                font=("Segoe UI", 8, "bold"))
                    # Hour label below
                    ch.create_text(
                        x + bar_w / 2, bottom_y + 14,
                        text=str(h) + ":00",
                        fill=C["text4"],
                        font=("Segoe UI", 8))
            ch.bind("<Configure>", _draw_hourly)
            ch.after(50, _draw_hourly)
            idle_note.config(
                text="Hourly breakdown shows between-session gap "
                     "minutes per office hour. Red bars ≥ 15min, "
                     "amber 5–15min. Within-session idle is not "
                     "shown here (TD API only exposes daily total). "
                     "Empty = continuous TD session.")

        def _render_idle_view():
            _clear_idle_box()
            mode = idle_mode_var.get()
            if mode == "td_summary":
                _render_td_summary()
            elif mode == "gap_instances":
                _render_gap_instances()
            else:
                _render_hourly()

        # Initial render
        _render_idle_view()

        # ── Dual hourly bars (total + productive overlay) ────────────────────
        tk.Label(win, text="Activity by hour  "
                         "(grey = tracked, green = productive)",
                 font=("Segoe UI", 9, "bold"),
                 bg=C["page"], fg=C["text2"]).pack(
            anchor="w", padx=18, pady=(6, 4))

        ch_h = 90
        cv_o = tk.Frame(win, bg=C["white"],
                        bd=1, relief="solid",
                        highlightbackground=C["border"])
        cv_o.pack(fill="x", padx=14, pady=(0, 10))
        cv = tk.Canvas(cv_o, height=ch_h + 24, bg=C["white"],
                       highlightthickness=0)
        cv.pack(fill="x", padx=10, pady=10)

        def _redraw(event=None):
            cv.delete("all")
            # Build a continuous range of hours from work_start to work_end
            # so missing hours show empty slots (gaps visible in timeline).
            try:
                ws_h = int(work_start.split(":")[0])
                we_h = int(work_end.split(":")[0])
            except Exception:
                ws_h, we_h = None, None

            if ws_h is not None and we_h is not None and we_h >= ws_h:
                hour_total_d = dict(
                    getattr(self, "_td_last_hour_total", {}) or {})
                hour_prod_d = dict(
                    getattr(self, "_td_last_hour_prod", {}) or {})
                full_hourly = []
                for h in range(ws_h, we_h + 1):
                    hh = str(h).zfill(2)
                    full_hourly.append((
                        hh,
                        hour_total_d.get(hh, 0),
                        hour_prod_d.get(hh, 0),
                    ))
            else:
                full_hourly = list(hourly)

            if not full_hourly:
                cv.create_text(10, ch_h // 2, anchor="w",
                               fill=C["text3"],
                               font=("Segoe UI", 9),
                               text="No event data for this day.")
                return
            w = cv.winfo_width() or 600
            n = len(full_hourly)
            bar_w = max(10, (w - 4) / n - 3)
            for i, (h, tot_s, prd_s) in enumerate(full_hourly):
                x = 2 + i * (bar_w + 3)
                # Sub-minute activity still shows a 2px bar
                if tot_s <= 0:
                    tot_h = 0
                else:
                    tot_h = max(2, min(ch_h,
                                       int(ch_h * tot_s / 3600)))
                if prd_s <= 0:
                    prd_h = 0
                else:
                    prd_h = max(2, min(tot_h,
                                       int(ch_h * prd_s / 3600)))
                if tot_h > 0:
                    cv.create_rectangle(x, ch_h - tot_h,
                                        x + bar_w, ch_h,
                                        fill=C["text5"], outline="")
                if prd_h > 0:
                    cv.create_rectangle(x, ch_h - prd_h,
                                        x + bar_w, ch_h,
                                        fill=C["green"], outline="")
                cv.create_text(x + bar_w / 2, ch_h + 12,
                               text=h, fill=C["text4"],
                               font=("Segoe UI", 7))
        cv.bind("<Configure>", _redraw)
        win.after(50, _redraw)

        # ── Top productive apps / sites (flat list, sorted by time) ──────────
        # Flatten all groups into a single {app: secs} dict (apps may appear
        # in multiple groups conceptually — here we take the max).
        flat_apps = {}
        for gname, gcol, gsecs, gapps in groups_out:
            for akey, asecs in gapps.items():
                if akey in flat_apps:
                    # Keep the larger value (same app in two groups = duplicate)
                    flat_apps[akey] = max(flat_apps[akey], asecs)
                else:
                    flat_apps[akey] = asecs
        flat_list = sorted(flat_apps.items(), key=lambda x: -x[1])
        total_productive = sum(s for _, s in flat_list)

        tk.Label(win,
                 text="Productive apps / sites (sorted by time)",
                 font=("Segoe UI", 9, "bold"),
                 bg=C["page"], fg=C["text2"]).pack(
            anchor="w", padx=18, pady=(4, 4))

        apps_outer = tk.Frame(win, bg=C["border"], padx=1, pady=1)
        apps_outer.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        apps_tree = ttk.Treeview(
            apps_outer, style="TD.Treeview",
            columns=("app", "dur", "pct"),
            show="headings", height=12)
        apps_tree.heading("app", text="App / Site")
        apps_tree.heading("dur", text="Time")
        apps_tree.heading("pct", text="%")
        apps_tree.column("app", width=460, anchor="w", stretch=True)
        apps_tree.column("dur", width=100, anchor="e", stretch=False)
        apps_tree.column("pct", width=60, anchor="e", stretch=False)
        apps_tree.tag_configure("row",
                                 background=C["input"],
                                 foreground=C["text2"])

        apps_vsb = ttk.Scrollbar(apps_outer, orient="vertical",
                                  command=apps_tree.yview)
        apps_tree.configure(yscrollcommand=apps_vsb.set)
        apps_vsb.pack(side="right", fill="y")
        apps_tree.pack(fill="both", expand=True)

        if not flat_list:
            apps_tree.insert(
                "", "end",
                values=("No productive app data for this day.",
                        "", ""),
                tags=("row",))
        else:
            for akey, asecs in flat_list:
                pct = int(round(asecs * 100 / total_productive)) \
                    if total_productive else 0
                apps_tree.insert(
                    "", "end",
                    values=(akey, fmt(asecs), str(pct) + "%"),
                    tags=("row",))

            # Footer row with total
            apps_tree.insert(
                "", "end",
                values=("TOTAL", fmt(total_productive), "100%"),
                tags=("row",))

        # ── Close button ─────────────────────────────────────────────────────
        tk.Button(win, text="Close", font=("Segoe UI", 9),
                  bg=C["input"], fg=C["text2"], bd=0,
                  padx=24, pady=6,
                  activebackground=C["border"],
                  command=win.destroy).pack(pady=(4, 12))


    # ── Audit Log — Fetch ERP Data (reuses _zerp_session from Zeeta ERP page) ──
    def _audit_fetch_erp(self):
        """Fetch Zeeta ERP activity for the selected audit date and log to Activity Log."""
        sess = getattr(self, "_zerp_session", None)
        base = getattr(self, "_zerp_base", None)
        # Recover base from config if missing
        if sess and not base:
            cfg  = load_config()
            raw_url = cfg.get("zeeta_erp_url", "").strip()
            from urllib.parse import urlparse as _up2
            _p2 = _up2(raw_url)
            base = _p2.scheme + "://" + _p2.netloc if _p2.netloc else raw_url.split("/backend")[0].split("/web")[0]
            if base:
                self._zerp_base = base
        if not sess:
            self.audit_log(
                "Zeeta ERP: Not logged in — go to the Zeeta ERP page in the sidebar, "
                "enter credentials + OTP, then come back and click Fetch ERP Data.", "warn")
            return
        if not base:
            # Last resort — try the default URL
            base = "https://c.zeetacargo.com"
            self._zerp_base = base
        # Use the DateEntry widget directly (same as the rest of the audit page)
        try:
            sel_date = self.audit_date.get_date().strftime("%Y-%m-%d")
        except Exception:
            from datetime import date as _date
            sel_date = _date.today().strftime("%Y-%m-%d")
        self._set_busy(True, self.audit_progress)
        self.audit_log("Fetching Zeeta ERP activity for " + sel_date + "...", "info")
        import threading
        threading.Thread(target=self._audit_fetch_erp_thread,
                         args=(sess, base, sel_date), daemon=True).start()

    def _audit_fetch_erp_thread(self, sess, base, sel_date):
        """Background: pull Zeeta ERP mail.message audit log and populate audit_log."""
        try:
            r = sess.post(base + "/web/dataset/call_kw", json={
                "jsonrpc": "2.0", "method": "call", "id": 10,
                "params": {
                    "model": "mail.message",
                    "method": "search_read",
                    "args": [[
                        ["date", ">=", sel_date + " 00:00:00"],
                        ["date", "<=", sel_date + " 23:59:59"],
                        ["message_type", "in", ["email", "notification", "comment"]]
                    ]],
                    "kwargs": {
                        "fields": ["author_id", "date", "model",
                                   "res_id", "body", "subtype_id"],
                        "limit": 3000,
                        "order": "date desc"
                    }
                }
            }, timeout=30)
            msgs = r.json().get("result") or []

            if not msgs:
                self.after(0, lambda: self.audit_log(
                    "Zeeta ERP: No activity records for " + sel_date, "warn"))
                return

            # Aggregate by user name
            from collections import defaultdict
            user_agg = defaultdict(lambda: {
                "actions": 0, "first": "", "last": "", "last_module": "", "last_action": ""
            })
            for m in msgs:
                author = m.get("author_id")
                if not author:
                    continue
                name = str(author[1]) if len(author) > 1 else str(author[0])
                user_agg[name]["actions"] += 1
                t = (m.get("date") or "")[:16].replace("T", " ")
                if t:
                    if not user_agg[name]["first"] or t < user_agg[name]["first"]:
                        user_agg[name]["first"] = t[11:16]
                    if not user_agg[name]["last"] or t > user_agg[name]["last"]:
                        user_agg[name]["last"] = t[11:16]
                        user_agg[name]["last_module"] = (
                            str(m.get("model", "")).replace(".", " ").title())
                        body = (str(m.get("body", ""))[:60]
                                .replace("<p>", "").replace("</p>", "").strip())
                        user_agg[name]["last_action"] = (
                            body or user_agg[name]["last_module"])

            # Store for cross-reference by td_tree / run_audit
            self._erp_user_data = dict(user_agg)

            rows = sorted(user_agg.items(), key=lambda x: -x[1]["actions"])
            total = sum(v["actions"] for _, v in rows)
            no_login = [n for n, v in rows if v["actions"] == 0]

            def _log_results():
                self.audit_log(
                    "Zeeta ERP: " + str(len(rows)) + " users · "
                    + str(total) + " actions on " + sel_date, "ok")
                for name, v in rows:
                    a = v["actions"]
                    lvl = ("✓ High" if a >= 200
                           else ("✓ Good" if a >= 50
                                 else ("⚠ Low" if a > 0 else "✗ No login")))
                    line = (name + " — " + str(a) + " actions  "
                            + lvl + "  "
                            + (("first " + v["first"] + " last " + v["last"]
                                + "  " + v["last_module"])
                               if v["first"] else "no activity"))
                    color = ("ok" if a >= 50
                             else ("warn" if a > 0 else "err"))
                    self.audit_log(line, color)
                if no_login:
                    self.audit_log(
                        "No ERP activity: " + ", ".join(no_login[:10]), "warn")

            self.after(0, _log_results)

        except Exception as e:
            self.after(0, lambda e=str(e): self.audit_log(
                "Zeeta ERP fetch error: " + e, "err"))
        finally:
            self.after(0, lambda: self._set_busy(False, self.audit_progress))

    # ── Zeeta ERP standalone page ─────────────────────────────────────────────
    def _build_zeeta_erp_page(self):
        page = tk.Frame(self.main, bg=C["page"])
        self.pages["zeeta_erp"] = page

        # Topbar
        tp = tk.Frame(page, bg=C["topbar"], height=44)
        tp.pack(fill="x"); tp.pack_propagate(False)
        tk.Label(tp, text="  Zeeta ERP", font=("Segoe UI",12,"bold"),
                 bg=C["topbar"], fg=C["text"]).pack(side="left", pady=10)
        self.zerp_status_lbl = tk.Label(tp, text="● Not logged in",
                 font=("Segoe UI",9), bg=C["topbar"], fg=C["red"])
        self.zerp_status_lbl.pack(side="right", padx=12)
        tk.Frame(page, bg=C["border"], height=1).pack(fill="x")

        # Scrollable content
        _zc = tk.Canvas(page, bg=C["page"], highlightthickness=0)
        _zvsb = ttk.Scrollbar(page, orient="vertical", command=_zc.yview)
        _zc.configure(yscrollcommand=_zvsb.set)
        _zvsb.pack(side="right", fill="y")
        _zc.pack(side="left", fill="both", expand=True)
        _zi = tk.Frame(_zc, bg=C["page"])
        _zwin = _zc.create_window((0,0), window=_zi, anchor="nw")
        _zi.bind("<Configure>", lambda e: _zc.configure(scrollregion=_zc.bbox("all")))
        _zc.bind("<Configure>", lambda e: _zc.itemconfig(_zwin, width=e.width))
        _zc.bind_all("<MouseWheel>", lambda e: _zc.yview_scroll(int(-1*(e.delta/120)),"units"))

        pad = dict(padx=14, pady=(8,0))

        # ── Login card ────────────────────────────────────────────────────────
        lc_outer = tk.Frame(_zi, bg=C["border"], padx=1, pady=1)
        lc_outer.pack(fill="x", **pad)
        lc = tk.Frame(lc_outer, bg=C["white"])
        lc.pack(fill="both", expand=True)
        lc_hdr = tk.Frame(lc, bg=C["white"], padx=10, pady=8)
        lc_hdr.pack(fill="x")
        dot = tk.Frame(lc_hdr, bg="#ea580c", width=8, height=8)
        dot.pack(side="left", pady=3); dot.pack_propagate(False)
        tk.Frame(lc_hdr, bg=C["border"], width=1, height=14).pack(side="left", padx=6)
        tk.Label(lc_hdr, text="Zeeta ERP Login (OTP Required)",
                 font=("Segoe UI",9,"bold"), bg=C["white"], fg=C["text"]).pack(side="left")
        self.zerp_badge = tk.Label(lc_hdr, text="Not logged in",
                 font=("Segoe UI",8), bg=C["red_l"], fg=C["red"], padx=6, pady=2)
        self.zerp_badge.pack(side="right")
        tk.Frame(lc, bg=C["border"], height=1).pack(fill="x")

        lc_body = tk.Frame(lc, bg=C["white"], padx=12, pady=8)
        lc_body.pack(fill="x")

        # URL + credentials row
        creds_row = tk.Frame(lc_body, bg=C["white"])
        creds_row.pack(fill="x", pady=(0,6))
        url_f = tk.Frame(creds_row, bg=C["white"])
        url_f.pack(side="left", fill="x", expand=True, padx=(0,8))
        tk.Label(url_f, text="URL  (base domain only, e.g. https://c.zeetacargo.com)", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w")
        cfg = load_config()
        # Always show clean base URL — strip any path that may have been saved
        _saved_erp_url = cfg.get("zeeta_erp_url", "https://c.zeetacargo.com")
        try:
            from urllib.parse import urlparse as _zerp_up
            _zerp_p = _zerp_up(_saved_erp_url)
            _clean_erp_url = (_zerp_p.scheme + "://" + _zerp_p.netloc) if _zerp_p.netloc else "https://c.zeetacargo.com"
        except Exception:
            _clean_erp_url = "https://c.zeetacargo.com"
        self.zerp_url_var = tk.StringVar(value=_clean_erp_url)
        tk.Entry(url_f, textvariable=self.zerp_url_var,
                 font=("Segoe UI",9), bg=C["input2"], fg=C["text2"],
                 relief="flat", bd=0, highlightthickness=1,
                 highlightbackground=C["border2"]).pack(fill="x", ipady=3)

        user_f = tk.Frame(creds_row, bg=C["white"])
        user_f.pack(side="left", padx=(0,8))
        tk.Label(user_f, text="Username", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w")
        self.zerp_user_var = tk.StringVar(value=cfg.get("zeeta_erp_user",""))
        tk.Entry(user_f, textvariable=self.zerp_user_var, width=14,
                 font=("Segoe UI",9), bg=C["input2"], fg=C["text2"],
                 relief="flat", bd=0, highlightthickness=1,
                 highlightbackground="#fdba74").pack(fill="x", ipady=3)

        pass_f = tk.Frame(creds_row, bg=C["white"])
        pass_f.pack(side="left", padx=(0,8))
        tk.Label(pass_f, text="Password", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w")
        self.zerp_pass_var = tk.StringVar(value=cfg.get("zeeta_erp_pass",""))
        tk.Entry(pass_f, textvariable=self.zerp_pass_var, width=14,
                 font=("Segoe UI",9), bg=C["input2"], fg=C["text2"],
                 show="*", relief="flat", bd=0, highlightthickness=1,
                 highlightbackground="#fdba74").pack(fill="x", ipady=3)

        tk.Button(creds_row, text="Send OTP",
                  command=self._zerp_send_otp,
                  font=("Segoe UI",9,"bold"), bg="#fff7ed", fg="#c2410c",
                  relief="flat", bd=0, padx=10, pady=6, cursor="hand2",
                  activebackground="#c2410c", activeforeground="white"
                  ).pack(side="left", anchor="s")

        # OTP row
        otp_row = tk.Frame(lc_body, bg=C["white"])
        otp_row.pack(fill="x", pady=(0,4))
        self.zerp_otp_var = tk.StringVar()
        tk.Entry(otp_row, textvariable=self.zerp_otp_var, width=10,
                 font=("Consolas",13,"bold"), bg="#fff7ed", fg="#c2410c",
                 relief="flat", bd=0, highlightthickness=1,
                 highlightbackground="#fdba74", justify="center"
                 ).pack(side="left", ipady=4, padx=(0,8))
        tk.Button(otp_row, text="Verify OTP & Login",
                  command=self._zerp_verify_otp,
                  font=("Segoe UI",9,"bold"), bg="#fff7ed", fg="#c2410c",
                  relief="flat", bd=0, padx=10, pady=6, cursor="hand2",
                  activebackground="#c2410c", activeforeground="white"
                  ).pack(side="left")
        self.zerp_info_lbl = tk.Label(otp_row,
                 text="Enter OTP from email/phone then verify",
                 font=("Segoe UI",8), bg=C["white"], fg=C["text4"])
        self.zerp_info_lbl.pack(side="left", padx=10)

        # ── Stat cards ────────────────────────────────────────────────────────
        sc_row = tk.Frame(_zi, bg=C["page"])
        sc_row.pack(fill="x", **pad)
        self._zerp_stat_vars = {}
        for key, lbl, bg, fg in [
            ("total",   "Total Users",     C["accent_l"], C["accent"]),
            ("active",  "Active Today",    C["green_l"],  C["green"]),
            ("low",     "Low Activity",    C["amber_l"],  C["amber"]),
            ("nologin", "No ERP Login",    C["red_l"],    C["red"]),
            ("actions", "Total Actions",   "#fff7ed",     "#c2410c"),
        ]:
            sf = tk.Frame(sc_row, bg=bg, padx=12, pady=8)
            sf.pack(side="left", fill="x", expand=True, padx=(0,6))
            tk.Label(sf, text=lbl, font=("Segoe UI",8,"bold"),
                     bg=bg, fg=fg).pack(anchor="w")
            v = tk.StringVar(value="—")
            self._zerp_stat_vars[key] = v
            tk.Label(sf, textvariable=v, font=("Segoe UI",18,"bold"),
                     bg=bg, fg=fg).pack(anchor="w")

        # ── ERP Activity table ────────────────────────────────────────────────
        at_outer = tk.Frame(_zi, bg=C["border"], padx=1, pady=1)
        at_outer.pack(fill="both", expand=True, **pad)
        at_inner = tk.Frame(at_outer, bg=C["white"])
        at_inner.pack(fill="both", expand=True)
        at_hdr = tk.Frame(at_inner, bg="#fff7ed", padx=10, pady=6)
        at_hdr.pack(fill="x")
        dot2 = tk.Frame(at_hdr, bg="#ea580c", width=8, height=8)
        dot2.pack(side="left", pady=3); dot2.pack_propagate(False)
        tk.Frame(at_hdr, bg=C["border"], width=1, height=14).pack(side="left", padx=6)
        tk.Label(at_hdr, text="Zeeta ERP — User Activity Log",
                 font=("Segoe UI",9,"bold"), bg="#fff7ed", fg=C["text"]).pack(side="left")
        tk.Frame(at_inner, bg=C["border"], height=1).pack(fill="x")

        # Treeview
        style = ttk.Style()
        style.configure("Zerp.Treeview", font=("Segoe UI",9), rowheight=22,
                         background=C["input"], fieldbackground=C["input"],
                         foreground=C["text2"])
        style.configure("Zerp.Treeview.Heading", font=("Segoe UI",8,"bold"),
                         background="#fff7ed", foreground="#c2410c")
        self.zerp_tree = ttk.Treeview(at_inner, style="Zerp.Treeview",
                                       columns=("logins","actions","last_action",
                                                "last_module","first_login","last_seen","level"),
                                       show="tree headings", height=10)
        self.zerp_tree.heading("#0",           text="User")
        self.zerp_tree.heading("logins",       text="Logins Today")
        self.zerp_tree.heading("actions",      text="Total Actions")
        self.zerp_tree.heading("last_action",  text="Last Action")
        self.zerp_tree.heading("last_module",  text="Last Module")
        self.zerp_tree.heading("first_login",  text="First Login")
        self.zerp_tree.heading("last_seen",    text="Last Seen")
        self.zerp_tree.heading("level",        text="Activity Level")
        self.zerp_tree.column("#0",          width=130, stretch=False)
        self.zerp_tree.column("logins",      width=90,  anchor="center", stretch=False)
        self.zerp_tree.column("actions",     width=100, anchor="center", stretch=False)
        self.zerp_tree.column("last_action", width=160, stretch=True)
        self.zerp_tree.column("last_module", width=140, stretch=True)
        self.zerp_tree.column("first_login", width=80,  anchor="center", stretch=False)
        self.zerp_tree.column("last_seen",   width=80,  anchor="center", stretch=False)
        self.zerp_tree.column("level",       width=110, anchor="center", stretch=False)
        zerp_vsb = ttk.Scrollbar(at_inner, orient="vertical", command=self.zerp_tree.yview)
        self.zerp_tree.configure(yscrollcommand=zerp_vsb.set)
        zerp_vsb.pack(side="right", fill="y")
        self.zerp_tree.pack(fill="both", expand=True)
        # Row tags
        self.zerp_tree.tag_configure("good",    background=C["green_l"],  foreground=C["green"])
        self.zerp_tree.tag_configure("warn",    background=C["amber_l"],  foreground=C["amber"])
        self.zerp_tree.tag_configure("danger",  background=C["red_l"],    foreground=C["red"])
        self.zerp_tree.tag_configure("absent",  background=C["input"],    foreground=C["text4"])
        self.zerp_tree.tag_configure("team",    background="#1a2540",     foreground="#ffffff")
        self.zerp_tree.insert("", "end", text="-- Login & click Fetch ERP Activity --",
                               values=("","","","","","",""), tags=("absent",))

        # ── Button bar ────────────────────────────────────────────────────────
        bf = tk.Frame(_zi, bg=C["page"])
        bf.pack(fill="x", padx=14, pady=(8,4))
        for txt, cmd, bg, fg in [
            ("Fetch ERP Activity",    self._zerp_fetch,  "#fff7ed",    "#c2410c"),
            ("Send WhatsApp Report",  self._zerp_send_wa, C["green_l"], C["green"]),
            ("Stop",                  self._stop,         C["red_l"],   C["red"]),
        ]:
            tk.Button(bf, text=txt, command=cmd,
                      font=("Segoe UI",10,"bold"), bg=bg, fg=fg,
                      relief="flat", bd=0, padx=14, pady=7, cursor="hand2",
                      activebackground=fg, activeforeground="white"
                      ).pack(side="left", padx=(0,8))

        self.zerp_progress = ttk.Progressbar(_zi, mode="indeterminate")
        self.zerp_progress.pack(fill="x", padx=14, pady=(0,4))
        self.zerp_log_box = self._log_panel(_zi, "zerp")

    def _zerp_log(self, msg, kind="info"):
        self._write_log(self.zerp_log_box, msg, kind)

    def _zerp_send_otp(self):
        """Save creds and trigger OTP via Zeeta Cargo login."""
        url  = self.zerp_url_var.get().strip().rstrip("/")
        user = self.zerp_user_var.get().strip()
        pwd  = self.zerp_pass_var.get().strip()
        if not user or not pwd:
            self.zerp_info_lbl.config(text="Enter username and password first",
                                       fg=C["red"])
            return
        cfg = load_config()
        cfg["zeeta_erp_url"]  = url
        cfg["zeeta_erp_user"] = user
        cfg["zeeta_erp_pass"] = pwd
        save_config(cfg)
        self.zerp_info_lbl.config(text="Sending OTP...", fg=C["amber"])
        self.zerp_badge.config(text="Sending OTP...", bg=C["amber_l"], fg=C["amber"])
        self._set_busy(True, self.zerp_progress)
        threading.Thread(target=self._zerp_send_otp_thread,
                         args=(url, user, pwd), daemon=True).start()

    def _zerp_send_otp_thread(self, url, user, pwd):
        """Use same browser-like login flow as Sales Reminder (which works)."""
        import requests as _req
        from urllib.parse import urlparse as _up
        try:
            _p   = _up(url)
            base = _p.scheme + "://" + _p.netloc
            sess = _req.Session()
            sess.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/122.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
                "Accept-Language": "en-US,en;q=0.9",
            })

            # Step 1 — GET the login page to get CSRF token + form action
            login_page = None
            for path in ["/backend/login", "/web/login", "/login"]:
                try:
                    r = sess.get(base + path, timeout=15, allow_redirects=True)
                    if r.status_code == 200 and "password" in r.text.lower():
                        login_page = r
                        self._zerp_log("Login page: " + r.url, "info")
                        break
                except Exception:
                    continue

            if not login_page:
                raise ValueError("Cannot reach login page at " + base)

            # Step 2 — extract csrf_token from the page
            # Step 2 — extract csrf_token (simple string search)
            csrf = ""
            _txt = login_page.text
            for _marker in ['csrf_token"', "csrf_token'", 'name="csrf_token"', "name='csrf_token'"]:
                _idx = _txt.find(_marker)
                if _idx < 0:
                    continue
                # Look for value= nearby
                _chunk = _txt[_idx:_idx+300]
                _vi = _chunk.find("value=")
                if _vi >= 0:
                    _q = _chunk[_vi+6:_vi+7]
                    _end = _chunk.find(_q, _vi+7)
                    if _end > 0:
                        csrf = _chunk[_vi+7:_end]
                        break
                # Or the token value comes right after quotes
                for _q in ['"', "'"]:
                    _qi = _chunk.find(_q)
                    if _qi >= 0:
                        _end = _chunk.find(_q, _qi+1)
                        if _end > _qi and _end - _qi > 8:
                            csrf = _chunk[_qi+1:_end]
                            break
                if csrf:
                    break

                        # Step 3 — POST credentials (this triggers OTP SMS/email)
            post_url  = login_page.url
            form_data = {"login": user, "password": pwd, "redirect": "/backend"}
            if csrf:
                form_data["csrf_token"] = csrf
            sess.headers.update({"Referer": post_url,
                                  "Content-Type": "application/x-www-form-urlencoded"})
            r2 = sess.post(post_url, data=form_data, timeout=15, allow_redirects=False)

            # A redirect or 200 with OTP page = credentials accepted, OTP sent
            if r2.status_code in (200, 302, 303):
                self._zerp_pending_sess = sess
                self._zerp_pending_base = base
                self._zerp_pending_user = user
                self._zerp_pending_pwd  = pwd
                self.after(0, lambda: self.zerp_info_lbl.config(
                    text="OTP sent — check your phone/email", fg=C["green"]))
                self.after(0, lambda: self.zerp_badge.config(
                    text="OTP sent ✓", bg=C["amber_l"], fg=C["amber"]))
                self._zerp_log("Zeeta ERP: credentials accepted, OTP sent to " + user, "ok")
            else:
                raise ValueError("Login POST returned HTTP " + str(r2.status_code))

        except Exception as e:
            self.after(0, lambda e=str(e): self.zerp_info_lbl.config(
                text="Error: " + e[:80], fg=C["red"]))
            self._zerp_log("OTP error: " + str(e), "err")
        finally:
            self.after(0, lambda: self._set_busy(False, self.zerp_progress))

    def _zerp_verify_otp(self):
        otp = self.zerp_otp_var.get().strip()
        if not otp:
            self.zerp_info_lbl.config(text="Enter OTP first", fg=C["red"])
            return
        sess = getattr(self, "_zerp_pending_sess", None)
        base = getattr(self, "_zerp_pending_base", None)
        if not sess:
            # Try direct password login (no OTP needed for some configs)
            url  = self.zerp_url_var.get().strip()
            user = self.zerp_user_var.get().strip()
            pwd  = self.zerp_pass_var.get().strip()
            self._set_busy(True, self.zerp_progress)
            threading.Thread(target=self._zerp_login_direct,
                             args=(url, user, pwd, otp), daemon=True).start()
            return
        self.zerp_info_lbl.config(text="Verifying...", fg=C["amber"])
        self._set_busy(True, self.zerp_progress)
        threading.Thread(target=self._zerp_verify_thread,
                         args=(sess, base, otp), daemon=True).start()

    def _zerp_verify_thread(self, sess, base, otp):
        import requests as _req
        try:
            r = sess.post(base + "/web/dataset/call_kw", json={
                "jsonrpc":"2.0","method":"call","id":2,
                "params":{
                    "model":"res.users","method":"verify_otp",
                    "args":[],"kwargs":{"otp": otp}
                }
            }, timeout=15)
            data = r.json()
            if data.get("result"):
                self._zerp_session = sess
                self._zerp_base    = base
                self.after(0, self._zerp_on_login_success)
            else:
                err = str(data.get("error","Invalid OTP"))
                self.after(0, lambda e=err: self.zerp_info_lbl.config(
                    text="Verify failed: " + e[:60], fg=C["red"]))
        except Exception as e:
            self.after(0, lambda e=str(e): self.zerp_info_lbl.config(
                text="Error: " + e[:60], fg=C["red"]))
        finally:
            self.after(0, lambda: self._set_busy(False, self.zerp_progress))

    def _zerp_login_direct(self, url, user, pwd, otp):
        """Direct login — tries standard Odoo session login."""
        import requests as _req
        try:
            from urllib.parse import urlparse as _up
            _p = _up(url)
            base = _p.scheme + "://" + _p.netloc
            sess = _req.Session()
            r = sess.post(base + "/web/session/authenticate", json={
                "jsonrpc":"2.0","method":"call","id":1,
                "params":{"db": load_config().get("odoo_db",""),
                          "login": user, "password": pwd}
            }, timeout=15)
            data = r.json()
            uid = (data.get("result") or {}).get("uid")
            if uid:
                self._zerp_session = sess
                self._zerp_base    = base
                self.after(0, self._zerp_on_login_success)
            else:
                err = str(data.get("error","Login failed"))
                self.after(0, lambda e=err: self.zerp_info_lbl.config(
                    text="Login failed: " + e[:60], fg=C["red"]))
                self._zerp_log("Login error: " + err, "err")
        except Exception as e:
            self.after(0, lambda e=str(e): self.zerp_info_lbl.config(
                text="Error: " + e[:60], fg=C["red"]))
        finally:
            self.after(0, lambda: self._set_busy(False, self.zerp_progress))

    def _zerp_on_login_success(self):
        self.zerp_badge.config(text="Logged in ✓", bg=C["green_l"], fg=C["green"])
        self.zerp_status_lbl.config(text="● Logged in", fg=C["green"])
        self.zerp_info_lbl.config(
            text="Session active — click Fetch ERP Activity", fg=C["green"])
        self._zerp_log("Zeeta ERP: Logged in successfully", "ok")
        # Also update the Audit Log topbar badge so Fetch ERP Data works immediately
        try:
            self.zeeta_erp_status_lbl.config(
                text="Audit Log · ERP ✓", fg=C["green"])
        except Exception:
            pass
        self.audit_log("Zeeta ERP session ready — Fetch ERP Data is now active.", "ok")

    def _zerp_fetch(self):
        sess = getattr(self, "_zerp_session", None)
        if not sess:
            self.zerp_info_lbl.config(text="Login first", fg=C["red"])
            return
        self._set_busy(True, self.zerp_progress)
        self._zerp_log("Fetching Zeeta ERP activity...", "info")
        threading.Thread(target=self._zerp_fetch_thread, daemon=True).start()

    def _zerp_fetch_thread(self):
        import requests as _req
        try:
            sess = self._zerp_session
            base = self._zerp_base
            from datetime import date as _date
            today = _date.today().strftime("%Y-%m-%d")
            # Fetch audit log entries for today
            r = sess.post(base + "/web/dataset/call_kw", json={
                "jsonrpc":"2.0","method":"call","id":3,
                "params":{
                    "model":"mail.message","method":"search_read",
                    "args":[[["date",">=", today + " 00:00:00"],
                             ["date","<=", today + " 23:59:59"],
                             ["message_type","in",["email","notification","comment"]]]],
                    "kwargs":{
                        "fields":["author_id","date","model","res_id","body","subtype_id"],
                        "limit": 2000, "order": "date desc"
                    }
                }
            }, timeout=30)
            msgs = r.json().get("result") or []

            # Aggregate by user
            from collections import defaultdict
            user_agg = defaultdict(lambda: {
                "logins":0,"actions":0,"last_action":"","last_module":"",
                "first_login":"","last_seen":""
            })
            for m in msgs:
                author = m.get("author_id")
                if not author: continue
                uid  = str(author[0])
                name = str(author[1]) if len(author)>1 else uid
                user_agg[name]["actions"] += 1
                t = (m.get("date") or "")[:16].replace("T"," ")
                if t:
                    if not user_agg[name]["first_login"] or t < user_agg[name]["first_login"]:
                        user_agg[name]["first_login"] = t[11:16]
                    if not user_agg[name]["last_seen"] or t > user_agg[name]["last_seen"]:
                        user_agg[name]["last_seen"] = t[11:16]
                        user_agg[name]["last_module"] = str(m.get("model","")).replace("."," ").title()
                        body = str(m.get("body",""))[:60].replace("<p>","").replace("</p>","").strip()
                        user_agg[name]["last_action"] = body or user_agg[name]["last_module"]

            rows = sorted(user_agg.items(), key=lambda x: -x[1]["actions"])
            total_actions = sum(v["actions"] for _,v in rows)
            active  = len([r for _,v in rows if v["actions"] > 0])
            low     = len([r for _,v in rows if 0 < v["actions"] < 50])
            nologin = len([r for _,v in rows if v["actions"] == 0])

            def _populate():
                self.zerp_tree.delete(*self.zerp_tree.get_children())
                for name, v in rows:
                    a = v["actions"]
                    tag = "good" if a >= 50 else ("warn" if a > 0 else "danger")
                    level = "High" if a >= 200 else ("Good" if a >= 50 else ("Low ⚠" if a > 0 else "No Login ⚠"))
                    self.zerp_tree.insert("", "end", text=name,
                        values=(str(v["logins"]) + "×",
                                str(a),
                                v["last_action"][:40],
                                v["last_module"],
                                v["first_login"],
                                v["last_seen"],
                                level),
                        tags=(tag,))
                self._zerp_stat_vars["total"].set(str(len(rows)))
                self._zerp_stat_vars["active"].set(str(active))
                self._zerp_stat_vars["low"].set(str(low))
                self._zerp_stat_vars["nologin"].set(str(nologin))
                self._zerp_stat_vars["actions"].set(str(total_actions))
                self._zerp_log("Zeeta ERP: " + str(len(rows)) + " users · " + str(total_actions) + " actions", "ok")
                flagged = [n for n,v in rows if v["actions"] == 0]
                if flagged:
                    self._zerp_log("No ERP login: " + ", ".join(flagged[:5]), "warn")
            self.after(0, _populate)

        except Exception as e:
            self.after(0, lambda e=str(e): self._zerp_log("ERP fetch error: " + e, "err"))
        finally:
            self.after(0, lambda: self._set_busy(False, self.zerp_progress))

    def _zerp_send_wa(self):
        self._zerp_log("WhatsApp report — coming soon", "info")

    # ── Widget helpers ────────────────────────────────────────────────────────
    def _card(self, parent, title, dot_color, row, col):
        outer = tk.Frame(parent, bg=C["border"], padx=1, pady=1)
        outer.grid(row=row, column=col, sticky="nsew", padx=5)
        inner = tk.Frame(outer, bg=C["white"], padx=14, pady=12)
        inner.pack(fill="both", expand=True)
        hdr = tk.Frame(inner, bg=C["white"])
        hdr.pack(fill="x", pady=(0,10))
        dot = tk.Frame(hdr, bg=dot_color, width=8, height=8)
        dot.pack(side="left", pady=4)
        dot.pack_propagate(False)
        tk.Frame(hdr, bg=C["border"], width=1, height=16).pack(side="left", padx=8)
        tk.Label(hdr, text=title, font=("Segoe UI",10,"bold"),
                 bg=C["white"], fg=C["text"]).pack(side="left")
        return inner

    def _field(self, parent, label, show=None, accent=False):
        tk.Label(parent, text=label, font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w", pady=(5,1))
        var = tk.StringVar()
        bg2 = C["input2"] if accent else C["input"]
        fg2 = C["accent"] if accent else C["text2"]
        e = tk.Entry(parent, textvariable=var, font=("Segoe UI",10), bg=bg2,
                 fg=fg2, insertbackground=C["accent"], relief="flat", bd=0,
                 show=show or "",
                 highlightthickness=1, highlightbackground=C["border"])
        e.pack(fill="x", ipady=4)
        return var

    def _pill_btn(self, parent, text, cmd, bg, fg):
        tk.Button(parent, text=text, command=cmd, font=("Segoe UI",9,"bold"),
                  bg=bg, fg=fg, relief="flat", bd=0, pady=6,
                  cursor="hand2", activebackground=fg, activeforeground="white"
                  ).pack(fill="x")

    def _checkbox(self, parent, text, var, parent_bg=None, inline=False):
        bg = parent_bg or C["white"]
        f = tk.Frame(parent, bg=bg)
        f.pack(anchor="w", fill="x" if inline else None, pady=(0,2))
        cb = tk.Checkbutton(f, text=text, variable=var,
                            font=("Segoe UI",9), bg=bg, fg=C["text3"],
                            selectcolor=C["accent_l"], activebackground=bg,
                            cursor="hand2")
        cb.pack(side="left")

    def _log_panel(self, parent, key):
        outer = tk.Frame(parent, bg=C["border"], padx=1, pady=1)
        outer.pack(fill="both", expand=True, padx=14, pady=(0,12))
        inner = tk.Frame(outer, bg=C["log_bg"])
        inner.pack(fill="both", expand=True)
        hdr = tk.Frame(inner, bg=C["log_bg"], pady=8)
        hdr.pack(fill="x", padx=14)
        tk.Frame(hdr, bg=C["accent"], width=8, height=8).pack(side="left", pady=4)
        tk.Frame(hdr, bg=C["border"], width=1, height=16).pack(side="left", padx=8)
        tk.Label(hdr, text="Activity Log", font=("Segoe UI",10,"bold"),
                 bg=C["log_bg"], fg=C["text"]).pack(side="left")
        live = tk.Label(hdr, text="Live", font=("Segoe UI",8),
                 bg=C["green_l"], fg=C["green"])
        live.pack(side="right")
        tk.Frame(inner, bg=C["border"], height=1).pack(fill="x")
        box = scrolledtext.ScrolledText(inner, font=("Consolas",9), bg=C["log_bg"],
                                         fg=C["text2"], insertbackground=C["accent"],
                                         relief="flat", bd=0, wrap="word", state="disabled",
                                         padx=14, pady=8, height=6)
        box.pack(fill="both", expand=True)
        box.tag_config("ok",   foreground=C["green"])
        box.tag_config("err",  foreground=C["red"])
        box.tag_config("info", foreground=C["accent"])
        box.tag_config("warn", foreground=C["amber"])
        box.tag_config("ts",   foreground=C["text5"])
        return box

    def _write_log(self, box, text, tag="info"):
        def _w():
            box.config(state="normal")
            ts = datetime.now().strftime("%H:%M:%S")
            box.insert("end", "[" + ts + "] ", "ts")
            box.insert("end", text + "\n", tag)
            box.see("end")
            box.config(state="disabled")
        self.after(0, _w)

    def log(self, text, tag="info"):
        self._write_log(self.log_box, text, tag)

    def audit_log(self, text, tag="info"):
        self._write_log(self.audit_log_box, text, tag)

    def _set_busy(self, busy, bar=None):
        b = bar or self.progress
        b.start(10) if busy else b.stop()

    def _set_status(self, text, color):
        self.lbl_status.config(text=text, fg=color)
        self.sb_status.config(text=text, fg=color)

    # ── Data ─────────────────────────────────────────────────────────────────
    def _load_fields(self):
        self.f_host.set(self.cfg["odoo_host"])
        self.f_db.set(self.cfg["odoo_db"])
        self.f_user.set(self.cfg["odoo_user"])
        self.f_pass.set(self.cfg["odoo_pass"])
        self.f_ginstance.set(self.cfg["green_instance"])
        self.f_gtoken.set(self.cfg["green_token"])
        self.f_hour.set(self.cfg["schedule_hour"])
        self.f_min.set(self.cfg["schedule_minute"])
        self.auto_today.set(self.cfg.get("auto_run_today", True))
        self.company_var.set(self.cfg.get("company_name", "All Companies"))
        self.f_interval.set(str(self.cfg.get("watch_interval", 5)))
        self.note_text.delete("1.0","end")
        self.note_text.insert("1.0", self.cfg.get("custom_note","Please confirm receipt of this order."))
        self.audit_note_text.delete("1.0","end")
        self.audit_note_text.insert("1.0", self.cfg.get("audit_custom_note","Please review your activity log for today."))

    def _collect(self):
        self.cfg.update({
            "odoo_host":        self.f_host.get().strip(),
            "odoo_db":          self.f_db.get().strip(),
            "odoo_user":        self.f_user.get().strip(),
            "odoo_pass":        self.f_pass.get(),
            "green_instance":   self.f_ginstance.get().strip(),
            "green_token":      self.f_gtoken.get().strip(),
            "schedule_hour":    self.f_hour.get().strip(),
            "schedule_minute":  self.f_min.get().strip(),
            "auto_run_today":   self.auto_today.get(),
            "watch_interval":   int(self.f_interval.get().strip() or "5"),
            "custom_note":      self.note_text.get("1.0","end-1c").strip(),
            "audit_custom_note":self.audit_note_text.get("1.0","end-1c").strip(),
        })

    # ── Actions ───────────────────────────────────────────────────────────────
    def _load_companies(self):
        self._collect()
        self.log("Loading companies...", "info")
        self._set_busy(True)
        def _r():
            try:
                _, _, _, cos = fetch_companies(self.cfg)
                self._companies = cos
                names = ["All Companies"] + [c["name"] for c in cos]
                def _u():
                    self.company_cb["values"] = names
                    sid = self.cfg.get("company_id", 0)
                    if sid:
                        m = next((c for c in cos if c["id"]==sid), None)
                        self.company_var.set(m["name"] if m else "All Companies")
                    else:
                        self.company_var.set("All Companies")
                    self.log("Loaded " + str(len(cos)) + " companies", "ok")
                self.after(0, _u)
            except Exception as e:
                self.log("ERROR: " + str(e), "err")
            finally:
                self.after(0, lambda: self._set_busy(False))
        threading.Thread(target=_r, daemon=True).start()

    def _on_company_select(self, event=None):
        name = self.company_var.get()
        if name == "All Companies":
            self.cfg["company_id"] = 0; self.cfg["company_name"] = "All Companies"
        else:
            m = next((c for c in self._companies if c["name"]==name), None)
            if m: self.cfg["company_id"] = m["id"]; self.cfg["company_name"] = m["name"]
        save_config(self.cfg)
        self.co_badge.config(text=self.cfg["company_name"])
        self.log("Company: " + self.cfg["company_name"], "ok")

    def _save(self):
        self._collect(); save_config(self.cfg)
        self.co_badge.config(text=self.cfg.get("company_name","All Companies"))
        self.log("Configuration saved.", "ok")

    def _test_conn(self):
        self._collect()
        def _r():
            self.after(0, lambda: self._set_busy(True))
            try:
                uid, _, host = odoo_auth(self.cfg)
                self.log("Odoo OK  UID:" + str(uid) + "  " + host, "ok")
            except Exception as e:
                self.log("ERROR: " + str(e), "err")
            finally:
                self.after(0, lambda: self._set_busy(False))
        threading.Thread(target=_r, daemon=True).start()

    def _test_green(self):
        self._collect()
        def _r():
            self.after(0, lambda: self._set_busy(True))
            try:
                state = test_green_api(self.cfg)
                if state == "authorized":
                    self.log("WhatsApp OK  Green API authorized", "ok")
                else:
                    self.log("WhatsApp state: " + state + "  (scan QR at green-api.com)", "warn")
            except Exception as e:
                self.log("ERROR: " + str(e), "err")
            finally:
                self.after(0, lambda: self._set_busy(False))
        threading.Thread(target=_r, daemon=True).start()

    def _run_date(self):
        self._collect(); save_config(self.cfg)
        sel = self.date_picker.get_date()
        self.log("Running for: " + sel.strftime("%d %B %Y"), "info")
        self._set_busy(True)
        def _r():
            run_job(self.cfg, sel, self.log)
            self.after(0, lambda: self._set_busy(False))
        threading.Thread(target=_r, daemon=True).start()

    def _start(self):
        self._collect(); save_config(self.cfg)
        h = self.cfg["schedule_hour"].zfill(2)
        m = self.cfg["schedule_minute"].zfill(2)
        interval = int(self.cfg.get("watch_interval", 5))
        schedule.clear()
        def _daily():
            t = date.today() if self.auto_today.get() else self.date_picker.get_date()
            threading.Thread(target=run_job, args=(self.cfg, t, self.log), daemon=True).start()
        schedule.every().day.at(h+":"+m).do(_daily)
        if self.watch_var.get():
            schedule.every(interval).minutes.do(
                lambda: threading.Thread(target=run_watch_job, args=(self.cfg, self.log), daemon=True).start())
            self.log("Watch mode ON -- every " + str(interval) + " min", "ok")
        self.running = True
        status = "● Running " + h + ":" + m + (" + Watch" if self.watch_var.get() else "")
        self._set_status(status, C["green"])
        self.tb_status.config(text="Daily " + h + ":" + m)
        self.log("Scheduler started -- daily at " + h + ":" + m, "ok")
        def _loop():
            while self.running:
                schedule.run_pending(); time.sleep(15)
        self.sched_th = threading.Thread(target=_loop, daemon=True)
        self.sched_th.start()

    def _stop(self):
        self.running = False; schedule.clear()
        self._set_status("● Idle", C["text4"])
        self.log("Stopped.", "warn")

    def _load_audit_users(self, after_done=None):
        """Fetch Odoo users active on the selected date.
        If after_done is provided, it will be called on the main thread
        after the load completes successfully (used by TD fetch to chain)."""
        # Build cfg directly from live StringVar widgets (always populated from startup)
        cfg = {
            "odoo_host": self.f_host.get().strip(),
            "odoo_db":   self.f_db.get().strip(),
            "odoo_user": self.f_user.get().strip(),
            "odoo_pass": self.f_pass.get(),
        }
        # If widgets are empty fall back to saved config
        if not cfg["odoo_host"]:
            cfg = load_config()
        sel_date = self.audit_date.get_date()
        self.audit_log("Connecting to " + cfg.get("odoo_host","(not set)") + "...", "info")
        self.audit_log("Fetching activity logs for " + sel_date.strftime("%d %B %Y") + "...", "info")
        self._set_busy(True, self.audit_progress)
        def _r():
            try:
                uid, models, host = odoo_auth(cfg)
                self.audit_log("Authenticated (UID " + str(uid) + ")", "ok")

                ds = sel_date.strftime("%Y-%m-%d")
                ns = (sel_date + timedelta(days=1)).strftime("%Y-%m-%d")

                # Use mail.message to find users active on this date
                BUSINESS_MODELS = [
                    "purchase.order","account.move","account.payment",
                    "sale.order","stock.picking","stock.inventory",
                    "mrp.production","hr.employee","hr.payslip",
                    "hr.payslip.run","hr.attendance","hr.leave",
                    "res.partner","product.template","project.task",
                ]
                messages = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
                    "mail.message", "search_read",
                    [[["date",">=",ds+" 00:00:00"],
                      ["date","<", ns+" 00:00:00"],
                      ["author_id","!=",False],
                      ["model","in",BUSINESS_MODELS]]],
                    {"fields": ["author_id","model","record_name","res_id","date"], "limit": 5000, "order": "date asc"})

                self.audit_log("Found " + str(len(messages)) + " chatter entries", "ok")

                # Resolve missing record names by fetching from their models
                # Group res_ids by model for batch lookup
                missing_by_model = {}
                for m in messages:
                    if not m.get("record_name") and m.get("res_id") and m.get("model"):
                        mod = m["model"]
                        if mod not in missing_by_model:
                            missing_by_model[mod] = set()
                        missing_by_model[mod].add(m["res_id"])

                # Batch fetch display names per model
                name_cache = {}  # (model, res_id) -> name
                for mod, res_ids in missing_by_model.items():
                    try:
                        # Try name_get first (fastest)
                        results = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
                            mod, "name_get", [list(res_ids)])
                        for rid, name in results:
                            name_cache[(mod, rid)] = name
                    except:
                        # Fallback: try common name fields
                        try:
                            name_field = "name"
                            if mod == "account.move": name_field = "name"
                            elif mod == "purchase.order": name_field = "name"
                            recs = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
                                mod, "search_read",
                                [[["id","in",list(res_ids)]]],
                                {"fields":["id", name_field], "limit": 500})
                            for r in recs:
                                name_cache[(mod, r["id"])] = r.get(name_field,"ID "+str(r["id"]))
                        except:
                            pass

                # Apply resolved names back to messages
                for m in messages:
                    if not m.get("record_name") and m.get("res_id") and m.get("model"):
                        resolved = name_cache.get((m["model"], m["res_id"]))
                        if resolved:
                            m["record_name"] = resolved
                        else:
                            m["record_name"] = m["model"].split(".")[-1].upper() + " #" + str(m["res_id"])

                # author_id is res.partner — map to res.users
                author_pids = list({m["author_id"][0] for m in messages
                                    if m.get("author_id") and isinstance(m["author_id"],(list,tuple))})
                all_users = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
                    "res.users","search_read",
                    [[["partner_id","in",author_pids]]],
                    {"fields":["id","name","partner_id","login"]})
                partner_to_user = {u["partner_id"][0]: (u["id"], u["name"], u.get("login",""))
                                   for u in all_users
                                   if u.get("partner_id") and isinstance(u["partner_id"],(list,tuple))}
                partners_ph = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
                    "res.partner","search_read",[[["id","in",author_pids]]],
                    {"fields":["id","phone","mobile"]})
                phone_by_pid = {p["id"]:(p.get("mobile") or p.get("phone") or "") for p in partners_ph}

                user_counts  = {}
                user_names   = {}
                user_models  = {}
                user_phones  = {}
                user_logins  = {}
                for m in messages:
                    author = m.get("author_id")
                    if not author or not isinstance(author,(list,tuple)): continue
                    pid = author[0]
                    if pid in partner_to_user:
                        uid_val, uname, ulogin = partner_to_user[pid]
                    else:
                        uid_val = pid
                        uname   = author[1]
                        ulogin  = ""
                    user_counts[uid_val]  = user_counts.get(uid_val,0) + 1
                    user_names[uid_val]   = uname
                    user_logins[uid_val]  = ulogin
                    user_phones[uid_val]  = phone_by_pid.get(pid,"")
                    model_key = m.get("model","")
                    label = MODEL_LABELS.get(model_key, model_key.replace("."," ").title() if model_key else "General")
                    if uid_val not in user_models: user_models[uid_val] = set()
                    user_models[uid_val].add(label)
                if not user_counts:
                    self.audit_log("No audit entries found for this date.", "warn")
                    def _clear():
                        self.audit_user_lb.delete(0,"end")
                        self.audit_user_lb.insert("end","-- No activity found --")
                        self._audit_users = []
                    self.after(0, _clear)
                    return

                # Get phones via res.users → res.partner
                uid_list = list(user_counts.keys())
                res_users = models.execute_kw(self.cfg["odoo_db"], uid, self.cfg["odoo_pass"],
                    "res.users","search_read",
                    [[["id","in",uid_list]]],
                    {"fields":["id","partner_id"]})
                uid_to_pid = {u["id"]: u["partner_id"][0] for u in res_users
                              if u.get("partner_id") and isinstance(u["partner_id"],(list,tuple))}
                pids = list(uid_to_pid.values())
                partners = models.execute_kw(self.cfg["odoo_db"], uid, self.cfg["odoo_pass"],
                    "res.partner","search_read",
                    [[["id","in",pids]]],
                    {"fields":["id","phone","mobile"]})
                phone_by_pid = {p["id"]:(p.get("mobile") or p.get("phone") or "") for p in partners}

                # Build by_model breakdown + time-ordered raw entries per user
                u_by_model   = {}
                u_raw_entries = {}
                for m in messages:
                    a = m.get("author_id")
                    if not a or not isinstance(a,(list,tuple)): continue
                    pid = a[0]
                    uv  = partner_to_user[pid][0] if pid in partner_to_user else pid
                    mk  = m.get("model","")
                    lbl = MODEL_LABELS.get(mk, mk.replace("."," ").title() if mk else "General")
                    rec = m.get("record_name","") or ""
                    # Convert Odoo UTC time to PKT (UTC+5)
                    raw_dt = (m.get("date","") or "")
                    if raw_dt:
                        try:
                            from datetime import timezone
                            utc_dt = datetime.strptime(raw_dt[:19], "%Y-%m-%d %H:%M:%S")
                            pkt_dt = utc_dt + timedelta(hours=5)
                            dt = pkt_dt.strftime("%Y-%m-%d %H:%M")
                        except:
                            dt = raw_dt[:16].replace("T"," ")
                    else:
                        dt = ""
                    # by_model grouping
                    if uv not in u_by_model: u_by_model[uv] = {}
                    if lbl not in u_by_model[uv]:
                        u_by_model[uv][lbl] = {"count":0,"records":[],"seen":set(),"entries":[]}
                    g = u_by_model[uv][lbl]
                    g["count"] += 1
                    g["entries"].append({"time": dt, "rec": rec})
                    if rec and rec not in g["seen"]:
                        g["seen"].add(rec); g["records"].append(rec)
                    # raw time-ordered entries
                    if uv not in u_raw_entries: u_raw_entries[uv] = []
                    u_raw_entries[uv].append({"time": dt, "model": lbl, "rec": rec})

                # Build user list sorted by count desc
                self._audit_users = []
                for uid_val in sorted(user_counts, key=lambda x: -user_counts[x]):
                    phone = user_phones.get(uid_val,"").strip()
                    self._audit_users.append({
                        "id":      uid_val,
                        "name":    user_names[uid_val],
                        "login":   user_logins.get(uid_val, ""),
                        "phone":   phone,
                        "pid":     uid_val,
                        "count":   user_counts[uid_val],
                        "modules": ", ".join(sorted(user_models.get(uid_val,set()))),
                        "by_model":    u_by_model.get(uid_val,{}),
                        "total":       user_counts[uid_val],
                        "entries":     [],
                        "raw_entries": u_raw_entries.get(uid_val,[]),
                    })

                def _update():
                    self.audit_user_lb.delete(0, "end")
                    for usr in self._audit_users:
                        count_tag = str(usr["count"]) + " actions"
                        phone_tag = usr["phone"] if usr["phone"] else "no phone"
                        modules_tag = usr.get("modules","")
                        self.audit_user_lb.insert("end",
                            usr["name"] + "  [" + count_tag + "]  (" + phone_tag + ")")
                    self.audit_user_lb.select_set(0, "end")
                    self._on_audit_user_select()
                    self.audit_log(
                        "Found " + str(len(self._audit_users)) + " active user(s) on " +
                        sel_date.strftime("%d %B %Y") + ". Select who to notify.", "ok")
                    # Kick off 7-day non-active fetch
                    self.after(100, lambda c=cfg, d=sel_date: self._fetch_non_active_users(c, d))
                    # Chain callback (used by TD fetch to auto-continue)
                    if after_done:
                        self.after(50, after_done)
                self.after(0, _update)

            except Exception as e:
                self.audit_log("ERROR: " + str(e), "err")
            finally:
                self.after(0, lambda: self._set_busy(False, self.audit_progress))
        threading.Thread(target=_r, daemon=True).start()

    def _on_na_select(self, event=None):
        idxs = self.na_listbox.curselection()
        self.na_sel_lbl.config(text=str(len(idxs)) + " selected")

    def _na_select_all(self):
        self.na_listbox.select_set(0, "end")
        self._on_na_select()

    def _na_clear_all(self):
        self.na_listbox.select_clear(0, "end")
        self._on_na_select()

    def _get_selected_na_users(self):
        """Return non-active users currently selected in the na_listbox as
        dicts compatible with run_audit_job_filtered (needs phone + name)."""
        idxs = self.na_listbox.curselection()
        result = []
        for i in idxs:
            if i < len(self._non_active_users):
                name, last_str, cnt, phone = self._non_active_users[i]
                if phone:
                    result.append({
                        "author_name": name,
                        "phone":       phone,
                        "by_model":    {},
                        "total":       cnt,
                        "entries":     [],
                        "raw_entries": [],
                        "pid":         None,
                        "author_id":   None,
                    })
        return result

    def _fetch_non_active_users(self, cfg, sel_date):
        """Fetch users active in the last 7 days but NOT active on sel_date."""
        def _r():
            try:
                uid, models, host = odoo_auth(cfg)
                BUSINESS_MODELS = [
                    "purchase.order","account.move","account.payment",
                    "sale.order","stock.picking","stock.inventory",
                    "mrp.production","hr.employee","hr.payslip",
                    "hr.payslip.run","hr.attendance","hr.leave",
                    "res.partner","product.template","project.task",
                ]
                # Date ranges
                today_str   = sel_date.strftime("%Y-%m-%d")
                today_end   = (sel_date + timedelta(days=1)).strftime("%Y-%m-%d")
                week_start  = (sel_date - timedelta(days=7)).strftime("%Y-%m-%d")

                # Users active TODAY
                today_msgs = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
                    "mail.message", "search_read",
                    [[["date",">=",today_str+" 00:00:00"],
                      ["date","<", today_end+" 00:00:00"],
                      ["author_id","!=",False],
                      ["model","in",BUSINESS_MODELS]]],
                    {"fields":["author_id"], "limit": 5000})
                today_pids = {m["author_id"][0] for m in today_msgs
                              if m.get("author_id") and isinstance(m["author_id"],(list,tuple))}

                # Users active in LAST 7 DAYS (excluding today)
                week_msgs = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
                    "mail.message", "search_read",
                    [[["date",">=",week_start+" 00:00:00"],
                      ["date","<", today_str+" 00:00:00"],
                      ["author_id","!=",False],
                      ["model","in",BUSINESS_MODELS]]],
                    {"fields":["author_id","date"], "limit": 10000})

                # Aggregate last-seen date per partner
                last_seen = {}
                counts_7d = {}
                for m in week_msgs:
                    a = m.get("author_id")
                    if not a or not isinstance(a,(list,tuple)): continue
                    pid = a[0]
                    if pid not in last_seen or m["date"] > last_seen[pid]:
                        last_seen[pid] = m["date"]
                    counts_7d[pid] = counts_7d.get(pid,0) + 1

                # Non-active = in 7d but NOT in today
                na_pids = [p for p in last_seen if p not in today_pids]
                if not na_pids:
                    def _none():
                        self.na_listbox.delete(0,"end")
                        self.na_listbox.insert("end","-- All recent users active today --")
                    self.after(0, _none)
                    return

                # Resolve names + phones
                na_users_raw = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
                    "res.users","search_read",
                    [[["partner_id","in",na_pids]]],
                    {"fields":["id","name","partner_id"]})
                pid_to_name = {u["partner_id"][0]: u["name"] for u in na_users_raw
                               if u.get("partner_id") and isinstance(u["partner_id"],(list,tuple))}
                ph_rows = models.execute_kw(cfg["odoo_db"], uid, cfg["odoo_pass"],
                    "res.partner","search_read",[[["id","in",na_pids]]],
                    {"fields":["id","phone","mobile","name"]})
                phone_by_pid = {p["id"]:(p.get("mobile") or p.get("phone") or "") for p in ph_rows}
                partner_name = {p["id"]: p.get("name","?") for p in ph_rows}

                na_list = []
                for pid in sorted(na_pids, key=lambda p: last_seen.get(p,""), reverse=True):
                    name  = pid_to_name.get(pid, partner_name.get(pid,"Unknown"))
                    phone = phone_by_pid.get(pid,"").strip()
                    raw_dt = last_seen[pid]
                    try:
                        utc_dt = datetime.strptime(raw_dt[:19], "%Y-%m-%d %H:%M:%S")
                        pkt_dt = utc_dt + timedelta(hours=5)
                        days_ago = (sel_date - pkt_dt.date()).days
                        last_str = pkt_dt.strftime("%d %b") + " (" + str(days_ago) + "d ago)"
                    except:
                        last_str = raw_dt[:10]
                    cnt = counts_7d.get(pid, 0)
                    na_list.append((name, last_str, cnt, phone))

                self._non_active_users = na_list

                def _update_na():
                    self.na_listbox.delete(0,"end")
                    if not na_list:
                        self.na_listbox.insert("end","-- All recent users active today --")
                        self.na_sel_lbl.config(text="0 selected")
                        return
                    for name, last_str, cnt, phone in na_list:
                        ph_tag = phone if phone else "no phone"
                        self.na_listbox.insert("end",
                            name + "  [" + str(cnt) + " acts]  Last: " + last_str + "  (" + ph_tag + ")")
                    self.na_sel_lbl.config(text="0 selected")
                self.after(0, _update_na)

            except Exception as e:
                def _err():
                    self.na_listbox.delete(0,"end")
                    self.na_listbox.insert("end","Error: " + str(e))
                self.after(0, _err)

        threading.Thread(target=_r, daemon=True).start()

    def _audit_select_all(self):
        self.audit_user_lb.select_set(0, "end")
        self._on_audit_user_select()

    def _audit_clear_all(self):
        self.audit_user_lb.select_clear(0, "end")
        self._on_audit_user_select()

    def _on_audit_user_select(self, event=None):
        idxs = self.audit_user_lb.curselection()
        self.audit_sel_lbl.config(text=str(len(idxs)) + " selected")
        if idxs and self._audit_users and idxs[-1] < len(self._audit_users):
            self._show_audit_detail(self._audit_users[idxs[-1]])

    def _show_audit_detail(self, user):
        self._current_detail_user = user
        self._refresh_audit_detail()

    def _refresh_audit_detail(self):
        user = self._current_detail_user
        tree = self.audit_tree
        tree.delete(*tree.get_children())
        if not user:
            return
        name     = user.get("name","?")
        total    = user.get("count", 0)
        phone    = user.get("phone","") or "no phone"
        by_model = user.get("by_model", {})
        raw      = user.get("raw_entries", [])
        view     = self.det_view_var.get()

        # Root node — user summary
        root = tree.insert("", "end",
                           text=name + "  (" + str(total) + " actions)",
                           values=("", "", phone),
                           tags=("module",), open=True)

        if view == "grouped":
            # ── By module actions: group by module, expand to records ─────────
            for lbl, grp in sorted(by_model.items(), key=lambda x: -x[1]["count"]):
                cnt = grp["count"]
                entries = sorted(grp.get("entries",[]), key=lambda e: e.get("time",""))
                mod_node = tree.insert(root, "end",
                                       text=lbl + "  (" + str(cnt) + ")",
                                       values=("", "", ""),
                                       tags=("module",), open=False)
                for e in entries:
                    full_dt = e.get("time","") or ""
                    dt_date = full_dt[:10]   if len(full_dt) >= 10 else ""
                    dt_time = full_dt[11:16] if len(full_dt) >= 16 else ""
                    rec = e.get("rec","") or "-"
                    tree.insert(mod_node, "end",
                                text=rec,
                                values=(dt_date, dt_time, lbl),
                                tags=("record",))

        elif view == "modfunc":
            # ── By module function entries: unique records with touch count ───
            import re as _re

            def _classify_func(rec_name):
                if not rec_name:
                    return "Other"
                r = rec_name.lower()
                if any(k in r for k in ("confirm","approve","validated","done","lock")):
                    return "Confirm / Approve"
                if any(k in r for k in ("cancel","reset","refuse","reject")):
                    return "Cancel / Reset"
                if any(k in r for k in ("payment","paid","register payment","pay")):
                    return "Payment"
                if any(k in r for k in ("send","email","mail","message","log note")):
                    return "Send / Message"
                if any(k in r for k in ("create","new","draft","created")):
                    return "Create"
                if any(k in r for k in ("write","edit","update","modify","change")):
                    return "Write / Edit"
                if _re.search(r"[A-Z]+/[0-9]{4}/[0-9]+", rec_name):
                    return "Create"
                return "Other"

            for lbl, grp in sorted(by_model.items(), key=lambda x: -x[1]["count"]):
                cnt = grp["count"]
                entries = sorted(grp.get("entries",[]), key=lambda e: e.get("time",""))

                # Group entries by function type, then deduplicate by record name
                func_groups = {}
                for e in entries:
                    fn  = _classify_func(e.get("rec",""))
                    rec = (e.get("rec","") or "-").strip()
                    if fn not in func_groups:
                        func_groups[fn] = {}          # rec_name -> {first_e, count}
                    if rec not in func_groups[fn]:
                        func_groups[fn][rec] = {"first": e, "count": 0}
                    func_groups[fn][rec]["count"] += 1

                # Count unique records across all functions for this module
                all_unique = set()
                for fn_recs in func_groups.values():
                    all_unique.update(fn_recs.keys())

                # Module node — shows total actions + unique count
                mod_node = tree.insert(root, "end",
                    text=lbl + "  (" + str(cnt) + " actions)",
                    values=("", "", str(len(all_unique)) + " unique"),
                    tags=("module",), open=False)

                # Function sub-nodes
                for fn, rec_dict in sorted(func_groups.items(),
                                           key=lambda x: -sum(v["count"] for v in x[1].values())):
                    total_fn = sum(v["count"] for v in rec_dict.values())
                    unique_fn = len(rec_dict)
                    fn_node = tree.insert(mod_node, "end",
                        text=fn + "  (" + str(total_fn) + " actions)",
                        values=("", "", str(unique_fn) + " unique"),
                        tags=("modfunc",), open=False)

                    # One row per unique record — sorted by first seen time
                    for rec, info in sorted(rec_dict.items(),
                                            key=lambda x: x[1]["first"].get("time","")):
                        e        = info["first"]
                        touches  = info["count"]
                        full_dt  = e.get("time","") or ""
                        dt_date  = full_dt[:10]   if len(full_dt) >= 10 else ""
                        dt_time  = full_dt[11:16] if len(full_dt) >= 16 else ""
                        tag      = "fnentry"
                        # Append touch badge to record text
                        badge    = "  x" + str(touches) if touches > 1 else "  x1"
                        tree.insert(fn_node, "end",
                                    text=rec + badge,
                                    values=(dt_date, dt_time, lbl),
                                    tags=(tag,))

        else:
            # ── By time: chronological flat list ─────────────────────────────
            for e in sorted(raw, key=lambda x: x.get("time","")):
                full_dt = e.get("time","") or ""
                dt_date = full_dt[:10]   if len(full_dt) >= 10 else ""
                dt_time = full_dt[11:16] if len(full_dt) >= 16 else ""
                rec = e.get("rec","") or "-"
                lbl = e.get("model","")
                tree.insert(root, "end",
                            text=rec,
                            values=(dt_date, dt_time, lbl),
                            tags=("time_entry",))

        # Auto expand root
        tree.item(root, open=True)

    def _audit_unfold_all(self):
        """Recursively expand every node in the audit breakdown treeview."""
        def _expand(node):
            self.audit_tree.item(node, open=True)
            for child in self.audit_tree.get_children(node):
                _expand(child)
        for top in self.audit_tree.get_children():
            _expand(top)

    def _audit_fold_all(self):
        """Recursively collapse every node except the root."""
        def _collapse(node, is_root=False):
            for child in self.audit_tree.get_children(node):
                _collapse(child)
            if not is_root:
                self.audit_tree.item(node, open=False)
        for top in self.audit_tree.get_children():
            _collapse(top, is_root=True)

    def _get_selected_audit_users(self):
        idxs = self.audit_user_lb.curselection()
        return [self._audit_users[i] for i in idxs if i < len(self._audit_users)]

    def _run_audit(self):
        # Always start from saved config so green_instance/token are never lost
        cfg = load_config()
        # Overlay with whatever is currently in the UI widgets (non-empty values only)
        _ui = {
            "odoo_host":         self.f_host.get().strip(),
            "odoo_db":           self.f_db.get().strip(),
            "odoo_user":         self.f_user.get().strip(),
            "odoo_pass":         self.f_pass.get(),
            "green_instance":    self.f_ginstance.get().strip(),
            "green_token":       self.f_gtoken.get().strip(),
            "audit_custom_note": self.audit_note_text.get("1.0","end-1c").strip(),
        }
        for k, v in _ui.items():
            if v:  # only override if the widget actually has a value
                cfg[k] = v
        sel = self.audit_date.get_date()
        selected_users = self._get_selected_audit_users()
        na_users       = self._get_selected_na_users()

        if not selected_users and not na_users and self._audit_users:
            self.audit_log("No users selected. Please select at least one user.", "warn")
            return

        self.audit_log("Running audit for: " + sel.strftime("%d %B %Y"), "info")
        if selected_users:
            self.audit_log("Sending to " + str(len(selected_users)) + " active user(s)", "info")
        if na_users:
            self.audit_log("Also sending note to " + str(len(na_users)) + " non-active user(s)", "info")

        self._set_busy(True, self.audit_progress)

        def _r():
            # Run normal audit for active selected users
            run_audit_job_filtered(cfg, sel, self.audit_log,
                                   selected_users if selected_users else None)
            # Send custom note to non-active selected users
            if na_users:
                custom_note = cfg.get("audit_custom_note", "").strip()
                ok = skip = fail = 0
                for user in na_users:
                    name  = user["author_name"]
                    phone = user["phone"]
                    self.audit_log("-- Non-active: " + name + " --", "info")
                    if not phone:
                        self.audit_log("No phone -- skipping", "warn")
                        skip += 1; continue
                    # Build a simple note-only message
                    msg = "Absence Notice\n\nDear " + name + ",\n\n"
                    if custom_note:
                        msg += custom_note + "\n"
                    else:
                        msg += "You had no activity recorded today. Please log in and update your work.\n"
                    try:
                        send_whatsapp_green(cfg, phone, msg, None, self.audit_log)
                        ok += 1
                    except Exception as e:
                        self.audit_log("ERROR: " + str(e), "err")
                        fail += 1
                    time.sleep(2)
                self.audit_log(
                    "Non-active done  Sent:" + str(ok) + "  Skip:" + str(skip) + "  Fail:" + str(fail), "ok")
            self.after(0, lambda: self._set_busy(False, self.audit_progress))

        threading.Thread(target=_r, daemon=True).start()

    def _start_audit(self):
        self._collect()
        h = self.cfg["schedule_hour"].zfill(2)
        m = self.cfg["schedule_minute"].zfill(2)
        sel_users = self._get_selected_audit_users()
        schedule.every().day.at(h+":"+m).do(
            lambda: threading.Thread(target=run_audit_job_filtered,
                     args=(self.cfg, date.today(), self.audit_log,
                           sel_users if sel_users else None), daemon=True).start())
        self.running = True
        self.audit_log("Audit scheduler started -- daily at " + h + ":" + m, "ok")
        if not self.sched_th or not self.sched_th.is_alive():
            def _loop():
                while self.running:
                    schedule.run_pending(); time.sleep(15)
            self.sched_th = threading.Thread(target=_loop, daemon=True)
            self.sched_th.start()

    # ── Audit Log — Template picker helpers ──────────────────────────────────

    def _audit_on_template_change(self, event=None):
        """Persist dropdown change to config."""
        name = self.audit_tpl_var.get()
        cfg = load_config()
        cfg["audit_template_selected"] = name
        save_config(cfg)
        self.audit_log("Template changed to: " + name, "info")

    def _audit_preview_template(self):
        """Render selected template with sample/real data and show in popup."""
        name = self.audit_tpl_var.get()
        tpl = (self._audit_templates or {}).get(name)
        if not tpl:
            self.audit_log("No template selected.", "warn")
            return

        # Use sample audit data
        sample_user = {
            "author_name": "Sample User",
            "total": 12,
            "by_model": {
                "Invoice / Journal Entry": {
                    "count": 8,
                    "records": ["ID 49801", "ID 49802",
                                "INV/2026/00045"],
                },
                "Sale Order": {
                    "count": 4,
                    "records": ["SO/2026/00012", "SO/2026/00013"],
                },
            },
        }
        from datetime import date as _d
        try:
            sd = self.audit_date.get_date()
        except Exception:
            sd = _d.today()
        note = self.audit_note_text.get("1.0", "end-1c").strip()
        msg = format_audit_message(sample_user, sd, note, template=tpl)

        win = tk.Toplevel(self)
        win.title("Preview — " + name)
        win.configure(bg=C["page"])
        win.geometry("620x520")
        win.transient(self)

        tk.Label(win,
                 text="Preview (sample data — Sample User)",
                 font=("Segoe UI", 10, "bold"),
                 bg=C["page"], fg=C["text"]).pack(
            anchor="w", padx=14, pady=(12, 4))
        tk.Label(win,
                 text="Template: " + name,
                 font=("Segoe UI", 8),
                 bg=C["page"], fg=C["text3"]).pack(
            anchor="w", padx=14, pady=(0, 8))

        frame = tk.Frame(win, bg=C["border"], padx=1, pady=1)
        frame.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        txt = scrolledtext.ScrolledText(
            frame, font=("Consolas", 9),
            bg=C["white"], fg=C["text2"], bd=0,
            padx=12, pady=8, wrap="word")
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", msg)
        txt.config(state="disabled")

        tk.Button(win, text="Close", font=("Segoe UI", 9),
                  bg=C["input"], fg=C["text2"], bd=0,
                  padx=24, pady=6,
                  command=win.destroy).pack(pady=(0, 12))

    def _audit_edit_templates(self):
        """Open the audit template editor dialog."""
        from tkinter import messagebox
        win = tk.Toplevel(self)
        win.title("Edit audit message templates")
        win.configure(bg=C["page"])
        win.geometry("820x560")
        win.transient(self)

        current = {k: dict(v)
                   for k, v in (self._audit_templates or {}).items()}
        if not current:
            current = {k: dict(v)
                       for k, v in DEFAULT_AUDIT_TEMPLATES.items()}

        self._ate_current = current
        self._ate_selected = None

        # Header
        hdr = tk.Frame(win, bg=C["page"])
        hdr.pack(fill="x", padx=14, pady=(14, 6))
        tk.Label(hdr, text="Edit audit message templates",
                 font=("Segoe UI", 11, "bold"),
                 bg=C["page"], fg=C["text"]).pack(side="left")
        tk.Label(hdr, text="Saved to config.json",
                 font=("Segoe UI", 8),
                 bg=C["page"], fg=C["text4"]).pack(side="right")

        body = tk.Frame(win, bg=C["page"])
        body.pack(fill="both", expand=True, padx=14, pady=(0, 6))
        body.columnconfigure(0, weight=0, minsize=180)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # Left: template list
        left_o = tk.Frame(body, bg=C["border"], padx=1, pady=1)
        left_o.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left = tk.Frame(left_o, bg=C["input"])
        left.pack(fill="both", expand=True)
        tk.Label(left, text="TEMPLATES",
                 font=("Segoe UI", 8, "bold"),
                 bg=C["input"], fg=C["text3"]).pack(
            anchor="w", padx=10, pady=(8, 4))

        lb = tk.Listbox(left, font=("Segoe UI", 9),
                        bg=C["white"], fg=C["text2"],
                        selectbackground=C["accent_l"],
                        selectforeground=C["accent"],
                        bd=0, relief="flat",
                        highlightthickness=0,
                        activestyle="none")
        lb.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self._ate_listbox = lb

        tk.Button(left, text="+ New template",
                  command=lambda: self._ate_add_new(win),
                  font=("Segoe UI", 8),
                  bg=C["white"], fg=C["accent"], bd=0,
                  padx=8, pady=4).pack(fill="x", padx=6, pady=(0, 8))

        # Right
        right = tk.Frame(body, bg=C["page"])
        right.grid(row=0, column=1, sticky="nsew")

        tk.Label(right, text="NAME",
                 font=("Segoe UI", 8, "bold"),
                 bg=C["page"], fg=C["text3"]).pack(
            anchor="w", pady=(0, 2))
        self._ate_name_var = tk.StringVar()
        tk.Entry(right, textvariable=self._ate_name_var,
                  font=("Segoe UI", 10),
                  bg=C["input"], fg=C["text2"], bd=0,
                  highlightthickness=1,
                  highlightbackground=C["border"]
                  ).pack(fill="x", ipady=4, pady=(0, 8))

        tk.Label(right, text="SUBJECT (used in header)",
                 font=("Segoe UI", 8, "bold"),
                 bg=C["page"], fg=C["text3"]).pack(
            anchor="w", pady=(0, 2))
        self._ate_subj_var = tk.StringVar()
        tk.Entry(right, textvariable=self._ate_subj_var,
                  font=("Segoe UI", 10),
                  bg=C["input"], fg=C["text2"], bd=0,
                  highlightthickness=1,
                  highlightbackground=C["border"]
                  ).pack(fill="x", ipady=4, pady=(0, 8))

        tk.Label(right, text="MESSAGE BODY",
                 font=("Segoe UI", 8, "bold"),
                 bg=C["page"], fg=C["text3"]).pack(
            anchor="w", pady=(0, 2))
        tk.Label(right,
                 text="Placeholders: {name}  {date}  {total}  "
                      "{subject}  {model_breakdown}  {note}",
                 font=("Segoe UI", 8),
                 bg=C["page"], fg=C["text4"]).pack(
            anchor="w", pady=(0, 4))

        body_o = tk.Frame(right, bg=C["border"], padx=1, pady=1)
        body_o.pack(fill="both", expand=True)
        self._ate_body_text = scrolledtext.ScrolledText(
            body_o, font=("Consolas", 9),
            bg=C["input"], fg=C["text2"],
            insertbackground=C["accent"],
            bd=0, padx=10, pady=8, wrap="word")
        self._ate_body_text.pack(fill="both", expand=True)

        btns = tk.Frame(win, bg=C["page"])
        btns.pack(fill="x", padx=14, pady=(6, 12))

        tk.Button(btns, text="Reset this template",
                  command=lambda: self._ate_reset(win),
                  font=("Segoe UI", 9),
                  bg=C["input"], fg=C["text3"], bd=0,
                  padx=10, pady=4).pack(side="left")

        tk.Button(btns, text="Delete",
                  command=lambda: self._ate_delete(win),
                  font=("Segoe UI", 9),
                  bg=C["red_l"], fg=C["red"], bd=0,
                  padx=10, pady=4).pack(side="left", padx=(6, 0))

        tk.Button(btns, text="Save all",
                  command=lambda: self._ate_save(win),
                  font=("Segoe UI", 9, "bold"),
                  bg=C["accent_l"], fg=C["accent"], bd=0,
                  padx=16, pady=4).pack(side="right")

        def _try_close():
            from tkinter import messagebox
            self._ate_flush_edits()
            persisted = (self._audit_templates or
                         dict(DEFAULT_AUDIT_TEMPLATES))
            if self._ate_current != persisted:
                ans = messagebox.askyesnocancel(
                    "Unsaved changes",
                    "You have unsaved template changes.\n\n"
                    "Save before closing?", parent=win)
                if ans is None:
                    return
                if ans:
                    self._ate_save(win)
                    return
            win.destroy()

        tk.Button(btns, text="Cancel",
                  command=_try_close,
                  font=("Segoe UI", 9),
                  bg=C["input"], fg=C["text2"], bd=0,
                  padx=14, pady=4).pack(side="right", padx=(0, 6))
        win.protocol("WM_DELETE_WINDOW", _try_close)

        lb.bind("<<ListboxSelect>>",
                lambda e: self._ate_load_selection(win))

        self._ate_refresh_list(keep_selection=False)
        if lb.size():
            lb.selection_set(0)
            self._ate_load_selection(win)

    def _ate_refresh_list(self, keep_selection=True):
        prev = None
        if keep_selection:
            idxs = self._ate_listbox.curselection()
            if idxs:
                prev = self._ate_listbox.get(idxs[0])
        self._ate_listbox.delete(0, "end")
        for k in self._ate_current.keys():
            self._ate_listbox.insert("end", k)
        if prev:
            for i, k in enumerate(self._ate_current.keys()):
                if k == prev:
                    self._ate_listbox.selection_set(i)
                    break

    def _ate_load_selection(self, win):
        idxs = self._ate_listbox.curselection()
        if not idxs:
            return
        self._ate_flush_edits()
        name = self._ate_listbox.get(idxs[0])
        self._ate_selected = name
        tpl = self._ate_current.get(name, {})
        self._ate_name_var.set(name)
        self._ate_subj_var.set(tpl.get("subject", ""))
        self._ate_body_text.delete("1.0", "end")
        self._ate_body_text.insert("1.0", tpl.get("body", ""))

    def _ate_flush_edits(self):
        if not self._ate_selected:
            return
        new_name = self._ate_name_var.get().strip()
        new_subj = self._ate_subj_var.get()
        new_body = self._ate_body_text.get("1.0", "end-1c")
        if not new_name:
            return
        if new_name != self._ate_selected:
            new_current = {}
            for k, v in self._ate_current.items():
                if k == self._ate_selected:
                    new_current[new_name] = {
                        "subject": new_subj, "body": new_body}
                else:
                    new_current[k] = v
            self._ate_current = new_current
            self._ate_selected = new_name
        else:
            self._ate_current[new_name] = {
                "subject": new_subj, "body": new_body}

    def _ate_add_new(self, win):
        self._ate_flush_edits()
        base = "New template"
        name = base
        n = 1
        while name in self._ate_current:
            n += 1
            name = base + " " + str(n)

        default_subject = "Activity Recap"
        default_body = (
            "Hi {name},\n"
            "\n"
            "{date} — {total} entries logged.\n"
            "\n"
            "{model_breakdown}\n"
            "{note}"
        )
        self._ate_current[name] = {
            "subject": default_subject,
            "body":    default_body,
        }

        self._ate_refresh_list(keep_selection=False)
        new_idx = None
        for i, k in enumerate(self._ate_current.keys()):
            if k == name:
                new_idx = i
                break
        if new_idx is not None:
            self._ate_listbox.selection_clear(0, "end")
            self._ate_listbox.selection_set(new_idx)
            self._ate_listbox.see(new_idx)
            self._ate_listbox.activate(new_idx)

        self._ate_selected = name
        self._ate_name_var.set(name)
        self._ate_subj_var.set(default_subject)
        self._ate_body_text.delete("1.0", "end")
        self._ate_body_text.insert("1.0", default_body)

        self.audit_log(
            "Added template '" + name +
            "' — click 'Save all' to persist.", "info")

    def _ate_reset(self, win):
        from tkinter import messagebox
        if not self._ate_selected:
            return
        default = DEFAULT_AUDIT_TEMPLATES.get(self._ate_selected)
        if not default:
            messagebox.showinfo(
                "Reset template",
                "No factory default exists for this template name.\n"
                "(Reset only works for built-in names)", parent=win)
            return
        self._ate_current[self._ate_selected] = dict(default)
        self._ate_subj_var.set(default["subject"])
        self._ate_body_text.delete("1.0", "end")
        self._ate_body_text.insert("1.0", default["body"])

    def _ate_delete(self, win):
        from tkinter import messagebox
        if not self._ate_selected:
            return
        if len(self._ate_current) <= 1:
            messagebox.showinfo(
                "Delete template",
                "Can't delete the last remaining template.", parent=win)
            return
        if not messagebox.askyesno(
            "Delete template",
            "Delete '" + self._ate_selected + "'?", parent=win):
            return
        self._ate_current.pop(self._ate_selected, None)
        self._ate_selected = None
        self._ate_refresh_list(keep_selection=False)
        if self._ate_listbox.size():
            self._ate_listbox.selection_set(0)
            self._ate_load_selection(win)

    def _ate_save(self, win):
        from tkinter import messagebox
        self._ate_flush_edits()
        if not self._ate_current:
            messagebox.showwarning(
                "Save templates",
                "At least one template must exist.", parent=win)
            return
        for k, v in self._ate_current.items():
            if not v.get("body", "").strip():
                messagebox.showwarning(
                    "Save templates",
                    "Template '" + k + "' has an empty body.", parent=win)
                return
        self._audit_templates = dict(self._ate_current)
        cfg = load_config()
        cfg["audit_templates"] = self._audit_templates
        cur_sel = self.audit_tpl_var.get() if hasattr(
            self, "audit_tpl_var") else ""
        if cur_sel not in self._audit_templates:
            cur_sel = next(iter(self._audit_templates.keys()))
        cfg["audit_template_selected"] = cur_sel
        save_config(cfg)
        self.audit_tpl_dropdown.config(
            values=list(self._audit_templates.keys()))
        self.audit_tpl_var.set(cur_sel)
        self.audit_log(
            "Saved " + str(len(self._audit_templates)) + " template(s).",
            "ok")
        win.destroy()


    # ══════════════════════════════════════════════════════════════════════════
    #  POS SYNC PAGE
    # ══════════════════════════════════════════════════════════════════════════
    def _build_pos_sync_page(self):
        page = tk.Frame(self.main, bg=C["page"])
        self.pages["pos_sync"] = page

        tp = tk.Frame(page, bg=C["topbar"], height=44)
        tp.pack(fill="x"); tp.pack_propagate(False)
        tk.Label(tp, text="  POS → Odoo Sync", font=("Segoe UI",12,"bold"),
                 bg=C["topbar"], fg=C["text"]).pack(side="left", pady=10)
        self.pos_co_badge = tk.Label(tp, text="All Branches",
                 font=("Segoe UI",9), bg=C["accent_l"], fg=C["accent"])
        self.pos_co_badge.pack(side="left", padx=(8,0))
        self.pos_tb_status = tk.Label(tp, text="Scheduler off",
                 font=("Segoe UI",9), bg=C["topbar"], fg=C["text4"])
        self.pos_tb_status.pack(side="right", padx=16)
        tk.Frame(page, bg=C["border"], height=1).pack(fill="x")
        page = self._make_scrollable(page)

        cr = tk.Frame(page, bg=C["page"])
        cr.pack(fill="x", padx=14, pady=12)
        for i in range(3): cr.columnconfigure(i, weight=1)

        # Card 1 — QuickBill Login
        c1 = self._card(cr, "QuickBill — MealWheelz", "#7c3aed", 0, 0)
        tk.Label(c1, text="quickbill.mealwheelz.com",
                 font=("Segoe UI",8), bg=C["white"], fg=C["text4"]).pack(anchor="w", pady=(0,6))
        self.pos_f_url = tk.StringVar(value="https://quickbill.mealwheelz.com")
        self.pos_f_key = tk.StringVar()
        self.pos_f_email = self._field(c1, "Login Email")
        self.pos_f_pw    = self._field(c1, "Login Password", show="*")
        self.pos_f_ant   = self._field(c1, "Anthropic Key (Claude matching)", show="*")

        # Branch / Restaurant selector
        tk.Label(c1, text="Branch / Restaurant", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w", pady=(8,2))
        br_row = tk.Frame(c1, bg=C["white"]); br_row.pack(fill="x"); br_row.columnconfigure(0, weight=1)
        self._pos_branches   = []          # list of {"_id":..., "name":...}
        self.pos_branch_var  = tk.StringVar(value="All Branches")
        self.pos_branch_cb   = ttk.Combobox(br_row, textvariable=self.pos_branch_var,
                                             state="readonly", font=("Segoe UI",10), width=16)
        self.pos_branch_cb["values"] = ["All Branches"]
        self.pos_branch_cb.grid(row=0, column=0, sticky="ew")
        self.pos_branch_cb.bind("<<ComboboxSelected>>", self._on_pos_branch_select)
        tk.Button(br_row, text="Load", command=self._pos_load_branches,
                  font=("Segoe UI",9,"bold"), bg=C["accent"], fg="white",
                  relief="flat", bd=0, padx=10, pady=4, cursor="hand2"
                  ).grid(row=0, column=1, padx=(6,0))

        # Branch badge showing current selection
        self.pos_branch_badge = tk.Label(c1, text="● All Branches",
                 font=("Segoe UI",8), bg=C["accent_l"], fg=C["accent"])
        self.pos_branch_badge.pack(anchor="w", pady=(4,6))

        tk.Label(c1, text="Playwright (headless Chrome) required.",
                 font=("Segoe UI",8), bg=C["white"], fg=C["text4"],
                 wraplength=180, justify="left").pack(anchor="w", pady=(0,2))
        self._pill_btn(c1, "Test QuickBill Login", self._pos_test_api,
                       C["accent_l"], C["accent"])

        # Card 2 — Sales Summary (replaces Similarity Matching)
        c2 = self._card(cr, "Sales Summary", "#0f766e", 0, 1)

        # Hidden similarity vars (still used internally)
        self.pos_f_auto   = tk.StringVar(value="85")
        self.pos_f_reject = tk.StringVar(value="40")
        self.pos_claude_var  = tk.BooleanVar(value=True)
        self.pos_notify_var  = tk.BooleanVar(value=True)
        self.pos_f_phone     = tk.StringVar()

        # Total Sales metric
        tk.Label(c2, text="Total Sales", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w")
        self.pos_total_lbl = tk.Label(c2, text="Rs. —",
                 font=("Segoe UI",20,"bold"), bg=C["white"], fg=C["green"])
        self.pos_total_lbl.pack(anchor="w", pady=(2,8))

        # Order type breakdown
        tk.Frame(c2, bg=C["border"], height=1).pack(fill="x", pady=(0,8))
        tk.Label(c2, text="Order Breakdown", font=("Segoe UI",9,"bold"),
                 bg=C["white"], fg=C["text"]).pack(anchor="w", pady=(0,4))

        types_frame = tk.Frame(c2, bg=C["white"])
        types_frame.pack(fill="x")
        types_frame.columnconfigure(0, weight=1)
        types_frame.columnconfigure(1, weight=1)
        types_frame.columnconfigure(2, weight=1)

        # Delivery
        d_card = tk.Frame(types_frame, bg=C["cyan_l"], padx=8, pady=6)
        d_card.grid(row=0, column=0, padx=(0,4), sticky="ew")
        tk.Label(d_card, text="Delivery", font=("Segoe UI",8),
                 bg=C["cyan_l"], fg=C["cyan"]).pack()
        self.pos_delivery_lbl = tk.Label(d_card, text="—",
                 font=("Segoe UI",14,"bold"), bg=C["cyan_l"], fg=C["cyan"])
        self.pos_delivery_lbl.pack()

        # Takeaway
        t_card = tk.Frame(types_frame, bg=C["amber_l"], padx=8, pady=6)
        t_card.grid(row=0, column=1, padx=2, sticky="ew")
        tk.Label(t_card, text="Takeaway", font=("Segoe UI",8),
                 bg=C["amber_l"], fg=C["amber"]).pack()
        self.pos_takeaway_lbl = tk.Label(t_card, text="—",
                 font=("Segoe UI",14,"bold"), bg=C["amber_l"], fg=C["amber"])
        self.pos_takeaway_lbl.pack()

        # Dine-in
        di_card = tk.Frame(types_frame, bg=C["green_l"], padx=8, pady=6)
        di_card.grid(row=0, column=2, padx=(4,0), sticky="ew")
        tk.Label(di_card, text="Dine-in", font=("Segoe UI",8),
                 bg=C["green_l"], fg=C["green"]).pack()
        self.pos_dinein_lbl = tk.Label(di_card, text="—",
                 font=("Segoe UI",14,"bold"), bg=C["green_l"], fg=C["green"])
        self.pos_dinein_lbl.pack()

        tk.Frame(c2, bg=C["border"], height=1).pack(fill="x", pady=(8,4))
        tk.Label(c2, text="Orders fetched", font=("Segoe UI",8),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w")
        self.pos_orders_lbl = tk.Label(c2, text="—",
                 font=("Segoe UI",12,"bold"), bg=C["white"], fg=C["text"])
        self.pos_orders_lbl.pack(anchor="w")

        # Card 3 — Schedule & Date
        c3 = self._card(cr, "Schedule & Date", "#f59e0b", 0, 2)
        tk.Label(c3, text="Sync Date", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w", pady=(0,3))
        self.pos_date = DateEntry(c3, width=16, font=("Segoe UI",10),
                            date_pattern="dd/mm/yyyy",
                            background=C["accent"], foreground="white",
                            headersbackground=C["accent"],
                            headersforeground="white",
                            selectbackground=C["accent"])
        self.pos_date.pack(fill="x", pady=(0,8))
        self.pos_date.set_date(date.today())
        self.pos_auto_today = tk.BooleanVar(value=True)
        self._checkbox(c3, "Use TODAY for scheduler", self.pos_auto_today)

        infobox = tk.Frame(c3, bg=C["input"],
                           highlightthickness=1, highlightbackground=C["border"])
        infobox.pack(fill="x", pady=(10,0))
        for line in ["How it works:", "Score ≥ Auto  →  mapped instantly",
                     "Score in range →  Claude decides", "Score < Reject →  Review queue",
                     "Confirmed once →  never asked again"]:
            tk.Label(infobox, text=line, font=("Segoe UI",8),
                     bg=C["input"], fg=C["text3"],
                     justify="left", anchor="w").pack(anchor="w", padx=8, pady=1)

        # Button bar
        bf = tk.Frame(page, bg=C["page"])
        bf.pack(fill="x", padx=14, pady=(0,8))
        for txt, cmd, bg, fg in [
            ("Save",                  self._pos_save,            C["accent_l"], C["accent"]),
            ("Fetch Data",            self._pos_fetch_preview,   C["cyan_l"],   C["cyan"]),
            ("Run for Date",          self._pos_run_date,        C["green_l"],  C["green"]),
            ("Import Products→Odoo",  self._pos_import_products, C["cyan_l"],   "#6d28d9"),
            ("Start Scheduler",       self._pos_start,           C["amber_l"],  C["amber"]),
            ("Stop",                  self._pos_stop,            C["red_l"],    C["red"]),
            ("Open Review Queue",     lambda: self._show_page("pos_rev"),
                                                                  C["accent_l"], C["accent"]),
        ]:
            tk.Button(bf, text=txt, command=cmd, font=("Segoe UI",10,"bold"),
                      bg=bg, fg=fg, relief="flat", bd=0, padx=12, pady=7,
                      cursor="hand2", activebackground=fg, activeforeground="white"
                      ).pack(side="left", padx=(0,8))

        self.pos_progress = ttk.Progressbar(page, mode="indeterminate",
                                            style="TProgressbar")
        self.pos_progress.pack(fill="x", padx=14, pady=(0,4))
        self.pos_log_box = self._log_panel(page, "pos_log")

    # ══════════════════════════════════════════════════════════════════════════
    #  POS REVIEW PAGE
    # ══════════════════════════════════════════════════════════════════════════
    def _build_pos_review_page(self):
        page = tk.Frame(self.main, bg=C["page"])
        self.pages["pos_rev"] = page
        self._pos_queue_items = []

        tp = tk.Frame(page, bg=C["topbar"], height=44)
        tp.pack(fill="x"); tp.pack_propagate(False)
        tk.Label(tp, text="  POS Review Queue", font=("Segoe UI",12,"bold"),
                 bg=C["topbar"], fg=C["text"]).pack(side="left", pady=10)
        self.pos_rev_count = tk.Label(tp, text="0 items",
                 font=("Segoe UI",9), bg=C["amber_l"], fg=C["amber"])
        self.pos_rev_count.pack(side="left", padx=(8,0))
        tk.Frame(page, bg=C["border"], height=1).pack(fill="x")
        page = self._make_scrollable(page)

        cr = tk.Frame(page, bg=C["page"])
        cr.pack(fill="x", padx=14, pady=12)
        cr.columnconfigure(0, weight=2)
        cr.columnconfigure(1, weight=3)

        # Left: queue list
        c1 = self._card(cr, "Pending Products", C["amber"], 0, 0)
        tk.Label(c1, text="Products awaiting confirmation:",
                 font=("Segoe UI",8), bg=C["white"], fg=C["text4"]).pack(anchor="w", pady=(0,4))
        lbf = tk.Frame(c1, bg=C["border"], padx=1, pady=1)
        lbf.pack(fill="both", expand=True)
        self.pos_rev_lb = tk.Listbox(lbf, font=("Segoe UI",9),
                 bg=C["input"], fg=C["text2"],
                 selectbackground=C["accent"], selectforeground="white",
                 relief="flat", bd=0, height=10, activestyle="none")
        self.pos_rev_lb.pack(fill="both", expand=True, padx=4, pady=4)
        self.pos_rev_lb.bind("<<ListboxSelect>>", self._pos_on_select)
        self.pos_rev_lb.insert("end", "— No items pending —")
        sb2 = tk.Frame(c1, bg=C["white"]); sb2.pack(fill="x", pady=(4,0))
        tk.Button(sb2, text="Refresh", command=self._pos_reload_review_list,
                  font=("Segoe UI",8), bg=C["accent_l"], fg=C["accent"],
                  relief="flat", bd=0, padx=8, pady=3, cursor="hand2"
                  ).pack(side="left", padx=(0,4))
        tk.Button(sb2, text="Clear All", command=self._pos_clear_queue,
                  font=("Segoe UI",8), bg=C["red_l"], fg=C["red"],
                  relief="flat", bd=0, padx=8, pady=3, cursor="hand2"
                  ).pack(side="left")

        # Right: confirm panel
        c2 = self._card(cr, "Confirm Match", C["green"], 0, 1)
        tk.Label(c2, text="POS product name:", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w")
        self.pos_rv_pos = tk.Label(c2, text="—", font=("Segoe UI",12,"bold"),
                 bg=C["white"], fg=C["text"])
        self.pos_rv_pos.pack(anchor="w", pady=(2,10))

        tk.Label(c2, text="Suggested Odoo match:", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w")
        self.pos_rv_sug = tk.Label(c2, text="—", font=("Segoe UI",10),
                 bg=C["accent_l"], fg=C["accent"], wraplength=260, justify="left")
        self.pos_rv_sug.pack(anchor="w", fill="x", pady=(2,4))

        tk.Label(c2, text="Score / Reason:", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w")
        self.pos_rv_info = tk.Label(c2, text="—", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text3"], wraplength=260, justify="left")
        self.pos_rv_info.pack(anchor="w", pady=(2,10))

        tk.Label(c2, text="Search Odoo catalog:", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w")
        sf = tk.Frame(c2, bg=C["white"]); sf.pack(fill="x", pady=(2,6))
        sf.columnconfigure(0, weight=1)
        self.pos_rv_search = tk.StringVar()
        tk.Entry(sf, textvariable=self.pos_rv_search,
                 font=("Segoe UI",10), bg=C["input"], fg=C["text2"],
                 relief="flat", bd=0,
                 highlightthickness=1, highlightbackground=C["border"]
                 ).grid(row=0, column=0, sticky="ew", ipady=4)
        tk.Button(sf, text="Search", command=self._pos_rv_search,
                  font=("Segoe UI",9,"bold"), bg=C["cyan_l"], fg=C["cyan"],
                  relief="flat", bd=0, padx=10, pady=4, cursor="hand2"
                  ).grid(row=0, column=1, padx=(6,0))

        rlf = tk.Frame(c2, bg=C["border"], padx=1, pady=1)
        rlf.pack(fill="x", pady=(0,8))
        self.pos_rv_results = tk.Listbox(rlf, font=("Segoe UI",9),
                 bg=C["input"], fg=C["text2"],
                 selectbackground=C["accent"], selectforeground="white",
                 relief="flat", bd=0, height=5, activestyle="none")
        self.pos_rv_results.pack(fill="x", padx=4, pady=4)

        bf2 = tk.Frame(c2, bg=C["white"]); bf2.pack(fill="x")
        for txt, cmd, bg, fg in [
            ("✓ Confirm Suggestion", self._pos_rv_confirm_sug, C["green_l"],  C["green"]),
            ("✓ Confirm Selected",   self._pos_rv_confirm_sel, C["accent_l"], C["accent"]),
            ("✗ Mark Unknown",       self._pos_rv_unknown,     C["red_l"],    C["red"]),
        ]:
            tk.Button(bf2, text=txt, command=cmd, font=("Segoe UI",9,"bold"),
                      bg=bg, fg=fg, relief="flat", bd=0, padx=10, pady=6,
                      cursor="hand2", activebackground=fg, activeforeground="white"
                      ).pack(side="left", padx=(0,6))

        self.pos_rev_progress = ttk.Progressbar(page, mode="indeterminate",
                                                style="TProgressbar")
        self.pos_rev_progress.pack(fill="x", padx=14, pady=(4,4))
        self.pos_rev_log = self._log_panel(page, "pos_rev_log")

    # ── POS log helper ────────────────────────────────────────────────────────
    def pos_log(self, text, tag="info"):
        self._write_log(self.pos_log_box, text, tag)

    def pos_rlog(self, text, tag="info"):
        self._write_log(self.pos_rev_log, text, tag)

    # ── POS queue badge ───────────────────────────────────────────────────────
    def _pos_refresh_badge(self):
        n = len(pos_load_queue())
        if n > 0:
            self.sb_queue_badge.config(text="⚠ "+str(n)+" POS item(s)")
            self.pos_rev_count.config(text=str(n)+" items")
        else:
            self.sb_queue_badge.config(text="✓ POS queue clear")
            self.pos_rev_count.config(text="0 items")

    # ── Load / collect POS fields ─────────────────────────────────────────────
    def _pos_load_fields(self):
        self.pos_f_email.set(self.cfg.get("quickbill_email",""))
        self.pos_f_pw.set(self.cfg.get("quickbill_password",""))
        self.pos_f_ant.set(self.cfg.get("anthropic_key",""))
        self.pos_f_auto.set(str(self.cfg.get("sim_auto_threshold",85)))
        self.pos_f_reject.set(str(self.cfg.get("sim_reject_threshold",40)))
        self.pos_claude_var.set(self.cfg.get("use_claude_matching",True))
        self.pos_notify_var.set(self.cfg.get("notify_on_review",True))
        self.pos_f_phone.set(self.cfg.get("notify_phone",""))
        branch_name = self.cfg.get("quickbill_branch_name","All Branches")
        self.pos_branch_var.set(branch_name)
        self.pos_branch_badge.config(text="● " + branch_name)
        self.pos_co_badge.config(text=branch_name)

    def _pos_collect(self):
        self.cfg.update({
            "quickbill_email":      self.pos_f_email.get().strip(),
            "quickbill_password":   self.pos_f_pw.get().strip(),
            "anthropic_key":        self.pos_f_ant.get().strip(),
            "sim_auto_threshold":   int(self.pos_f_auto.get().strip() or "85"),
            "sim_reject_threshold": int(self.pos_f_reject.get().strip() or "40"),
            "use_claude_matching":  self.pos_claude_var.get(),
            "notify_on_review":     self.pos_notify_var.get(),
            "notify_phone":         self.pos_f_phone.get().strip(),
        })

    # ── Branch selector actions ───────────────────────────────────────────────
    def _pos_load_branches(self):
        """Load available QuickBill branches into the dropdown."""
        self._pos_collect()
        self.pos_log("Loading QuickBill branches...", "info")
        self._set_busy(True, self.pos_progress)
        def _r():
            try:
                branches = qb_fetch_branches(self.cfg, self.pos_log)
                def _u():
                    names = ["All Branches"] + [b["name"] for b in branches]
                    self.pos_branch_cb["values"] = names
                    self._pos_branches = branches
                    # Restore saved selection if it exists
                    saved_name = self.cfg.get("quickbill_branch_name","All Branches")
                    if saved_name in names:
                        self.pos_branch_var.set(saved_name)
                    else:
                        self.pos_branch_var.set("All Branches")
                    self.pos_log("Loaded " + str(len(branches)) + " branch(es)", "ok")
                self.after(0, _u)
            except Exception as e:
                self.pos_log("Branch load error: " + str(e), "err")
            finally:
                self.after(0, lambda: self._set_busy(False, self.pos_progress))
        threading.Thread(target=_r, daemon=True).start()

    def _on_pos_branch_select(self, event=None):
        """Handle branch dropdown selection — save to config."""
        name = self.pos_branch_var.get()
        if name == "All Branches":
            self.cfg["quickbill_branch"]      = "all"
            self.cfg["quickbill_branch_name"] = "All Branches"
        else:
            branch = next((b for b in self._pos_branches if b["name"] == name), None)
            if branch:
                bid = branch["_id"]
                if bid.startswith("__NAME__:"):
                    # No MongoDB ID found — can only use all-branches
                    self.pos_log("⚠ Branch ID not found for '" + name +
                                 "' — check quickbill_branch_entry.json and report to support",
                                 "warn")
                    self.cfg["quickbill_branch"]      = "all"
                    self.cfg["quickbill_branch_name"] = "All Branches"
                else:
                    self.cfg["quickbill_branch"]      = bid
                    self.cfg["quickbill_branch_name"] = name
        save_config(self.cfg)
        self.pos_branch_badge.config(text="● " + self.cfg["quickbill_branch_name"])
        self.pos_co_badge.config(text=self.cfg["quickbill_branch_name"])
        self.pos_log("Branch: " + self.cfg["quickbill_branch_name"], "ok")

    # ── POS Sync actions ──────────────────────────────────────────────────────

    def _pos_fetch_preview(self):
        """Fetch POS data for selected date and show summary without syncing."""
        self._pos_collect()
        if hasattr(self, 'pos_auto_today') and self.pos_auto_today.get():
            sel = date.today()
        else:
            sel = self.pos_date.get_date()
        self.pos_log("Fetching POS data for " + sel.strftime("%d %B %Y") + "...", "info")
        self.pos_progress.start(10)
        def _r():
            try:
                from datetime import date as _d
                email    = self.cfg.get("quickbill_email","").strip()
                password = self.cfg.get("quickbill_password","").strip()
                if not email or not password:
                    self.pos_log("QuickBill credentials not set. Click Save first.", "warn")
                    return
                session  = _qb_get_session(email, password, self.pos_log)
                branch_id = self.cfg.get("quickbill_branch","all")
                orders   = _qb_try_api_endpoints(session, sel, self.pos_log, branch_id)
                if not orders:
                    self.pos_log("No orders found for this date/branch.", "warn")
                    self.after(0, lambda: self._pos_update_summary([]))
                    return
                self.pos_log("Fetched " + str(len(orders)) + " order(s)", "ok")
                self.after(0, lambda o=orders: self._pos_update_summary(o))
            except Exception as e:
                self.pos_log("Fetch error: " + str(e), "err")
            finally:
                self.after(0, self.pos_progress.stop)
        threading.Thread(target=_r, daemon=True).start()

    def _pos_update_summary(self, orders):
        """Update the Sales Summary card with fetched order data."""
        if not orders:
            self.pos_total_lbl.config(text="Rs. 0")
            self.pos_delivery_lbl.config(text="0")
            self.pos_takeaway_lbl.config(text="0")
            self.pos_dinein_lbl.config(text="0")
            self.pos_orders_lbl.config(text="0 orders")
            return

        total    = sum(o.get("total",0) for o in orders)
        delivery = sum(1 for o in orders if o.get("order_type","") == "Delivery")
        takeaway = sum(1 for o in orders if o.get("order_type","") == "Takeaway")
        dinein   = sum(1 for o in orders if o.get("order_type","") == "Dine-in")
        unknown  = len(orders) - delivery - takeaway - dinein

        self.pos_total_lbl.config(text="Rs. {:,.0f}".format(total))
        self.pos_delivery_lbl.config(text=str(delivery))
        self.pos_takeaway_lbl.config(text=str(takeaway))
        self.pos_dinein_lbl.config(
            text=str(dinein) + ("+" + str(unknown) if unknown else ""))
        self.pos_orders_lbl.config(text=str(len(orders)) + " orders")

        # Log breakdown
        self.pos_log("Total Sales: Rs. {:,.0f}".format(total), "ok")
        self.pos_log("Delivery: " + str(delivery) + "  Takeaway: " + str(takeaway) +
                     "  Dine-in: " + str(dinein) +
                     ("  Other: " + str(unknown) if unknown else ""), "info")

        # Peak hours analysis
        hour_counts = {}
        for o in orders:
            h = o.get("hour")
            if h is not None:
                hour_counts[h] = hour_counts.get(h,0) + 1
        if hour_counts:
            peak_h = max(hour_counts, key=hour_counts.get)
            peak_n = hour_counts[peak_h]
            ampm   = "AM" if peak_h < 12 else "PM"
            h12    = peak_h % 12 or 12
            self.pos_log("Peak hour: " + str(h12) + ":00 " + ampm +
                         " (" + str(peak_n) + " orders)", "ok")

    def _pos_save(self):
        self._pos_collect(); save_config(self.cfg)
        self.pos_log("POS Sync settings saved.", "ok")

    def _pos_test_api(self):
        """Detailed diagnostic: test login, session, and API step by step."""
        self._pos_collect()
        email    = self.cfg.get("quickbill_email","").strip()
        password = self.cfg.get("quickbill_password","").strip()
        if not email or not password:
            self.pos_log("Enter email + password then click Save first.", "warn")
            return
        self._set_busy(True, self.pos_progress)
        self.pos_log("=== QuickBill Diagnostic ===", "info")

        def _r():
            try:
                # Step 1: Check Playwright
                try:
                    from playwright.sync_api import sync_playwright
                    self.after(0, lambda: self.pos_log("✓ Playwright installed", "ok"))
                    pw_ok = True
                except ImportError:
                    self.after(0, lambda: self.pos_log(
                        "✗ Playwright NOT installed — run: pip install playwright && playwright install chromium", "err"))
                    pw_ok = False

                # Step 2: Login
                self.after(0, lambda: self.pos_log("Logging in as " + email + "...", "info"))
                session = _qb_get_session(email, password, self.pos_log)
                cookies = list(session.cookies.keys())
                self.after(0, lambda c=cookies: self.pos_log(
                    "Session cookies: " + str(c), "info" if c else "warn"))

                # Step 3: Check if we have a real auth cookie
                has_auth = any(k.lower() in ("next-auth.session-token",
                                              "__secure-next-auth.session-token",
                                              "authjs.session-token",
                                              "connect.sid", "session")
                               for k in cookies)
                if not has_auth:
                    self.after(0, lambda: self.pos_log(
                        "⚠ No auth cookie found — login may have failed. "
                        "Check email/password.", "warn"))
                else:
                    self.after(0, lambda: self.pos_log("✓ Auth cookie present", "ok"))

                # Step 4: Hit the API
                self.after(0, lambda: self.pos_log("Hitting /api/reports...", "info"))
                orders = _qb_try_api_endpoints(session, date.today(), self.pos_log)
                if orders:
                    self.after(0, lambda n=len(orders): self.pos_log(
                        "✓ SUCCESS — " + str(n) + " orders fetched!", "ok"))
                    self.after(0, lambda o=orders: self._pos_update_summary(o))
                else:
                    self.after(0, lambda: self.pos_log(
                        "✗ No orders returned — see log above for cause.", "err"))
                    # Step 5: Try visiting the dashboard to see what we get
                    self.after(0, lambda: self.pos_log("Checking dashboard access...", "info"))
                    try:
                        r = session.get(QUICKBILL_URL + "/dashboard", timeout=15)
                        if "signin" in r.url or r.status_code == 401:
                            self.after(0, lambda: self.pos_log(
                                "✗ Session not authenticated — redirected to signin", "err"))
                        elif r.status_code == 200:
                            self.after(0, lambda: self.pos_log(
                                "✓ Dashboard accessible (HTTP 200) — API issue", "ok"))
                        else:
                            self.after(0, lambda s=r.status_code: self.pos_log(
                                "Dashboard: HTTP " + str(s), "warn"))
                    except Exception as de:
                        self.after(0, lambda e=str(de): self.pos_log("Dashboard: " + e, "warn"))

            except Exception as e:
                self.after(0, lambda e=str(e): self.pos_log("Diagnostic error: " + e, "err"))
            finally:
                self.after(0, lambda: self._set_busy(False, self.pos_progress))
                self.after(0, lambda: self.pos_log("=== Diagnostic done ===", "info"))

        threading.Thread(target=_r, daemon=True).start()

    def _pos_import_products(self):
        """Fetch all QuickBill products and create missing ones in Odoo."""
        self._pos_collect(); save_config(self.cfg)
        from tkinter import messagebox
        if not messagebox.askyesno(
                "Import Products to Odoo",
                "This will scan the last 90 days of QuickBill sales\n"
                "and create any missing products in Odoo as draft items.\n\n"
                "Branch: " + self.cfg.get("quickbill_branch_name","All") + "\n"
                "Odoo:   " + self.cfg.get("odoo_host","") + "\n\n"
                "Existing products will NOT be modified.\n\n"
                "Continue?"):
            return
        self.pos_log("Starting product import...", "info")
        self._set_busy(True, self.pos_progress)
        def _r():
            sync_products_to_odoo(self.cfg, self.pos_log)
            self.after(0, lambda: self._set_busy(False, self.pos_progress))
        threading.Thread(target=_r, daemon=True).start()

    def _pos_run_date(self):
        self._pos_collect(); save_config(self.cfg)
        sel = self.pos_date.get_date()
        self.pos_log("Running POS Sync for: " + sel.strftime("%d %B %Y"), "info")
        self._set_busy(True, self.pos_progress)
        def _r():
            run_pos_sync_job(self.cfg, sel, self.pos_log)
            self.after(0, lambda: self._set_busy(False, self.pos_progress))
            self.after(0, self._pos_refresh_badge)
        threading.Thread(target=_r, daemon=True).start()

    def _pos_start(self):
        self._pos_collect(); save_config(self.cfg)
        h = self.cfg["schedule_hour"].zfill(2)
        m = self.cfg["schedule_minute"].zfill(2)
        def _daily():
            t = date.today() if self.pos_auto_today.get() else self.pos_date.get_date()
            threading.Thread(target=run_pos_sync_job,
                             args=(self.cfg, t, self.pos_log), daemon=True).start()
        schedule.every().day.at(h+":"+m).do(_daily)
        self.running = True
        self._set_status("● Running "+h+":"+m, C["green"])
        self.pos_tb_status.config(text="Daily "+h+":"+m)
        self.pos_log("POS Sync scheduler started — daily at "+h+":"+m, "ok")
        if not self.sched_th or not self.sched_th.is_alive():
            def _loop():
                while self.running:
                    schedule.run_pending(); time.sleep(15)
            self.sched_th = threading.Thread(target=_loop, daemon=True)
            self.sched_th.start()

    def _pos_stop(self):
        self.running = False; schedule.clear()
        self._set_status("● Idle", C["text4"])
        self.pos_tb_status.config(text="Scheduler off")
        self.pos_log("POS Sync stopped.", "warn")

    # ── Review Queue actions ──────────────────────────────────────────────────
    def _pos_reload_review_list(self):
        q = pos_load_queue()
        self._pos_queue_items = q
        self.pos_rev_lb.delete(0, "end")
        if not q:
            self.pos_rev_lb.insert("end", "— No items pending —")
        else:
            for item in q:
                sug   = item.get("odoo_product_name") or "no suggestion"
                score = round(item.get("score",0), 1)
                self.pos_rev_lb.insert("end",
                    item["pos_name"]+"  ["+str(score)+"]  → "+sug)
        self._pos_refresh_badge()

    def _pos_on_select(self, event=None):
        idxs = self.pos_rev_lb.curselection()
        if not idxs or idxs[0] >= len(self._pos_queue_items): return
        item = self._pos_queue_items[idxs[0]]
        self.pos_rv_pos.config(text=item["pos_name"])
        self.pos_rv_sug.config(text=item.get("odoo_product_name") or "—")
        self.pos_rv_info.config(
            text="Score: "+str(round(item.get("score",0),1))
                 +"  |  "+item.get("reasoning",""))
        self.pos_rv_results.delete(0, "end")

    def _pos_rv_search(self):
        kw = self.pos_rv_search.get().strip().lower()
        if not kw: return
        self._pos_collect()
        self._set_busy(True, self.pos_rev_progress)
        def _r():
            try:
                uid, models, _ = odoo_auth(self.cfg)
                self._pos_odoo_products = pos_get_odoo_products(self.cfg, uid, models)
                matches = [p for p in self._pos_odoo_products
                           if kw in p["name"].lower()]
                def _u():
                    self.pos_rv_results.delete(0,"end")
                    if not matches:
                        self.pos_rv_results.insert("end","— No results —")
                    else:
                        for p in matches[:30]:
                            code = p.get("default_code") or "—"
                            self.pos_rv_results.insert("end",
                                "["+str(p["id"])+"] "+p["name"]+"  ("+code+")")
                    self.pos_rlog("'"+kw+"': "+str(len(matches))+" result(s)","ok")
                self.after(0, _u)
            except Exception as e:
                self.pos_rlog("Search error: "+str(e),"err")
            finally:
                self.after(0, lambda: self._set_busy(False, self.pos_rev_progress))
        threading.Thread(target=_r, daemon=True).start()

    def _pos_rv_confirm_sug(self):
        idxs = self.pos_rev_lb.curselection()
        if not idxs or idxs[0] >= len(self._pos_queue_items): return
        item  = self._pos_queue_items[idxs[0]]
        oid   = item.get("odoo_product_id")
        oname = item.get("odoo_product_name")
        if not oid or not oname:
            self.pos_rlog("No suggestion — use Search & Confirm Selected","warn"); return
        pos_save_mapping(item["pos_name"], oid, oname)
        pos_remove_from_queue(item["pos_name"])
        self.pos_rlog("✓ '"+item["pos_name"]+"' → '"+oname+"'","ok")
        self._pos_reload_review_list()

    def _pos_rv_confirm_sel(self):
        q_idxs = self.pos_rev_lb.curselection()
        r_idxs = self.pos_rv_results.curselection()
        if not q_idxs or q_idxs[0] >= len(self._pos_queue_items):
            self.pos_rlog("Select a queue item first","warn"); return
        if not r_idxs:
            self.pos_rlog("Select a product from search results first","warn"); return
        item  = self._pos_queue_items[q_idxs[0]]
        label = self.pos_rv_results.get(r_idxs[0])
        try:
            oid  = int(label.split("]")[0].replace("[","").strip())
            prod = next(p for p in self._pos_odoo_products if p["id"]==oid)
            pos_save_mapping(item["pos_name"], oid, prod["name"])
            pos_remove_from_queue(item["pos_name"])
            self.pos_rlog("✓ '"+item["pos_name"]+"' → '"+prod["name"]+"'","ok")
            self._pos_reload_review_list()
        except Exception as e:
            self.pos_rlog("Error: "+str(e),"err")

    def _pos_rv_unknown(self):
        idxs = self.pos_rev_lb.curselection()
        if not idxs or idxs[0] >= len(self._pos_queue_items): return
        item = self._pos_queue_items[idxs[0]]
        pos_save_mapping(item["pos_name"], -1, "__UNKNOWN__")
        pos_remove_from_queue(item["pos_name"])
        self.pos_rlog("✗ Marked unknown: '"+item["pos_name"]+"'","warn")
        self._pos_reload_review_list()

    def _pos_clear_queue(self):
        from tkinter import messagebox
        if messagebox.askyesno("Clear Queue",
                "Clear all "+str(len(self._pos_queue_items))+" pending item(s)?"):
            pos_save_queue([])
            self._pos_reload_review_list()
            self.pos_rlog("Queue cleared.","warn")

    # ══════════════════════════════════════════════════════════════════════════
    #  AI INSIGHTS PAGE
    # ══════════════════════════════════════════════════════════════════════════
    def _build_ai_insights_page(self):
        page = tk.Frame(self.main, bg=C["page"])
        self.pages["ai_insights"] = page

        # Topbar
        tp = tk.Frame(page, bg=C["topbar"], height=44)
        tp.pack(fill="x"); tp.pack_propagate(False)
        tk.Label(tp, text="  🤖 AI Business Insights", font=("Segoe UI",12,"bold"),
                 bg=C["topbar"], fg=C["text"]).pack(side="left", pady=10)
        self.ai_branch_badge = tk.Label(tp, text="All Branches",
                 font=("Segoe UI",9), bg=C["accent_l"], fg=C["accent"])
        self.ai_branch_badge.pack(side="left", padx=(8,0))
        self.ai_status_lbl = tk.Label(tp, text="Ready",
                 font=("Segoe UI",9), bg=C["topbar"], fg=C["text4"])
        self.ai_status_lbl.pack(side="right", padx=16)
        tk.Frame(page, bg=C["border"], height=1).pack(fill="x")
        page = self._make_scrollable(page)

        # Controls row
        cr = tk.Frame(page, bg=C["page"])
        cr.pack(fill="x", padx=14, pady=10)
        for i in range(3): cr.columnconfigure(i, weight=1)

        # Card 1 — Analysis settings
        c1 = self._card(cr, "Analysis Settings", "#7c3aed", 0, 0)

        # Branch selector
        tk.Label(c1, text="Branch:", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w", pady=(0,2))
        ai_br_row = tk.Frame(c1, bg=C["white"])
        ai_br_row.pack(fill="x", pady=(0,8)); ai_br_row.columnconfigure(0, weight=1)
        self.ai_branch_var = tk.StringVar(value="All Branches")
        self.ai_branch_cb  = ttk.Combobox(ai_br_row, textvariable=self.ai_branch_var,
                             values=["All Branches"], state="readonly",
                             font=("Segoe UI",10))
        self.ai_branch_cb.grid(row=0, column=0, sticky="ew")
        self.ai_branch_cb.bind("<<ComboboxSelected>>", self._on_ai_branch_select)
        tk.Button(ai_br_row, text="↺", command=self._ai_refresh_branches,
                  font=("Segoe UI",10,"bold"), bg=C["accent_l"], fg=C["accent"],
                  relief="flat", bd=0, padx=8, pady=3, cursor="hand2"
                  ).grid(row=0, column=1, padx=(6,0))

        tk.Label(c1, text="Date range (days back):", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w", pady=(0,2))
        self.ai_days_var = tk.StringVar(value="30")
        dr = tk.Frame(c1, bg=C["white"]); dr.pack(fill="x", pady=(0,8))
        for label, val in [("7d","7"),("30d","30"),("90d","90")]:
            tk.Radiobutton(dr, text=label, variable=self.ai_days_var, value=val,
                          font=("Segoe UI",9), bg=C["white"], fg=C["text3"],
                          selectcolor=C["accent_l"], activebackground=C["white"],
                          cursor="hand2").pack(side="left", padx=(0,8))

        tk.Label(c1, text="Focus area:", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w", pady=(0,2))
        self.ai_focus_var = tk.StringVar(value="All")
        focus_opts = ["All", "Top Sellers", "Slow Items",
                      "Revenue Growth", "Menu Gaps", "Peak Hours"]
        self.ai_focus_cb = ttk.Combobox(c1, textvariable=self.ai_focus_var,
                            values=focus_opts, state="readonly",
                            font=("Segoe UI",10))
        self.ai_focus_cb.pack(fill="x", pady=(0,8))

        tk.Label(c1, text="Language:", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text4"]).pack(anchor="w", pady=(0,2))
        self.ai_lang_var = tk.StringVar(value="English")
        ttk.Combobox(c1, textvariable=self.ai_lang_var,
                     values=["English","Urdu","Arabic"], state="readonly",
                     font=("Segoe UI",10)).pack(fill="x")

        # Card 2 — Data summary
        c2 = self._card(cr, "Data Summary", C["cyan"], 0, 1)
        self.ai_summary_lbl = tk.Label(c2, text="Click 'Analyse Branch' to start.",
                 font=("Segoe UI",9), bg=C["white"], fg=C["text3"],
                 wraplength=200, justify="left")
        self.ai_summary_lbl.pack(anchor="w")

        # Card 3 — How it works
        c3 = self._card(cr, "How it works", C["green"], 0, 2)
        for line in [
            "1. Fetches your QuickBill sales data",
            "2. Builds a product performance report",
            "3. Sends data to Claude AI",
            "4. Returns business suggestions:",
            "   • Top & slow selling items",
            "   • Revenue opportunities",
            "   • Menu recommendations",
            "   • Pricing suggestions",
            "   • Peak time strategies",
        ]:
            tk.Label(c3, text=line, font=("Segoe UI",8),
                     bg=C["white"], fg=C["text3"],
                     justify="left", anchor="w").pack(anchor="w")

        # Button bar
        bf = tk.Frame(page, bg=C["page"])
        bf.pack(fill="x", padx=14, pady=(0,8))
        tk.Button(bf, text="🔍 Analyse Branch", command=self._ai_run_analysis,
                  font=("Segoe UI",10,"bold"), bg=C["accent_l"], fg=C["accent"],
                  relief="flat", bd=0, padx=16, pady=7,
                  cursor="hand2", activebackground=C["accent"],
                  activeforeground="white").pack(side="left", padx=(0,8))
        tk.Button(bf, text="⏹ Stop", command=self._ai_stop,
                  font=("Segoe UI",10,"bold"), bg=C["red_l"], fg=C["red"],
                  relief="flat", bd=0, padx=16, pady=7,
                  cursor="hand2", activebackground=C["red"],
                  activeforeground="white").pack(side="left", padx=(0,8))
        tk.Button(bf, text="📋 Copy Report", command=self._ai_copy_report,
                  font=("Segoe UI",10,"bold"), bg=C["green_l"], fg=C["green"],
                  relief="flat", bd=0, padx=16, pady=7,
                  cursor="hand2", activebackground=C["green"],
                  activeforeground="white").pack(side="left", padx=(0,8))
        tk.Button(bf, text="🗑 Clear", command=self._ai_clear,
                  font=("Segoe UI",10,"bold"), bg=C["amber_l"], fg=C["amber"],
                  relief="flat", bd=0, padx=16, pady=7,
                  cursor="hand2", activebackground=C["amber"],
                  activeforeground="white").pack(side="left")

        self.ai_progress = ttk.Progressbar(page, mode="indeterminate",
                                           style="TProgressbar")
        self.ai_progress.pack(fill="x", padx=14, pady=(0,4))

        # Report display panel
        outer = tk.Frame(page, bg=C["border"], padx=1, pady=1)
        outer.pack(fill="both", expand=True, padx=14, pady=(0,12))
        inner = tk.Frame(outer, bg=C["white"])
        inner.pack(fill="both", expand=True)

        hdr = tk.Frame(inner, bg=C["white"], pady=8)
        hdr.pack(fill="x", padx=14)
        tk.Frame(hdr, bg="#7c3aed", width=8, height=8).pack(side="left", pady=4)
        tk.Frame(hdr, bg=C["border"], width=1, height=16).pack(side="left", padx=8)
        tk.Label(hdr, text="AI Analysis Report", font=("Segoe UI",10,"bold"),
                 bg=C["white"], fg=C["text"]).pack(side="left")
        self.ai_model_lbl = tk.Label(hdr, text="Claude Sonnet",
                 font=("Segoe UI",8), bg=C["accent_l"], fg=C["accent"])
        self.ai_model_lbl.pack(side="right")
        tk.Frame(inner, bg=C["border"], height=1).pack(fill="x")

        self.ai_report_box = scrolledtext.ScrolledText(
            inner, font=("Segoe UI",10), bg=C["white"],
            fg=C["text2"], insertbackground=C["accent"],
            relief="flat", bd=0, wrap="word", state="disabled",
            padx=16, pady=12)
        self.ai_report_box.pack(fill="both", expand=True)
        self.ai_report_box.tag_config("heading",
            font=("Segoe UI",11,"bold"), foreground=C["accent"])
        self.ai_report_box.tag_config("subheading",
            font=("Segoe UI",10,"bold"), foreground="#7c3aed")
        self.ai_report_box.tag_config("bullet",
            font=("Segoe UI",10), foreground=C["text2"])
        self.ai_report_box.tag_config("good",
            font=("Segoe UI",10), foreground=C["green"])
        self.ai_report_box.tag_config("warn_tag",
            font=("Segoe UI",10), foreground=C["amber"])
        self.ai_report_box.tag_config("muted",
            font=("Segoe UI",9), foreground=C["text4"])

        self._ai_report_text = ""   # stores plain text for copy
        self._ai_cancel      = threading.Event()  # set to stop analysis mid-run

    # ── AI Insights helpers ───────────────────────────────────────────────────
    def _ai_stop(self):
        """Signal the running analysis to stop immediately."""
        self._ai_cancel.set()
        self.ai_status_lbl.config(text="Stopping...", fg=C["amber"])
        self._set_busy(False, self.ai_progress)
    def _ai_write(self, text, tag="bullet"):
        """Append text to the report box with a tag."""
        def _w():
            self.ai_report_box.config(state="normal")
            self.ai_report_box.insert("end", text, tag)
            self.ai_report_box.see("end")
            self.ai_report_box.config(state="disabled")
        self.after(0, _w)

    def _ai_clear(self):
        self.ai_report_box.config(state="normal")
        self.ai_report_box.delete("1.0","end")
        self.ai_report_box.config(state="disabled")
        self._ai_report_text = ""
        self.ai_summary_lbl.config(text="Click 'Analyse Branch' to start.")
        self.ai_status_lbl.config(text="Ready", fg=C["text4"])

    def _ai_copy_report(self):
        if self._ai_report_text:
            self.clipboard_clear()
            self.clipboard_append(self._ai_report_text)
            self.ai_status_lbl.config(text="Copied ✓", fg=C["green"])
            self.after(2000, lambda: self.ai_status_lbl.config(
                text="Ready", fg=C["text4"]))

    def _ai_refresh_branches(self):
        """Populate AI Insights branch dropdown from POS Sync branches."""
        # Sync from already-loaded POS branches list
        branches = getattr(self, "_pos_branches", [])
        names = ["All Branches"] + [b["name"] for b in branches]
        self.ai_branch_cb["values"] = names
        # Keep current selection if still valid
        if self.ai_branch_var.get() not in names:
            self.ai_branch_var.set("All Branches")
            self.ai_branch_badge.config(text="All Branches")
        if len(branches) == 0:
            # No branches loaded yet — trigger load from POS Sync
            self.pos_log("Loading branches for AI Insights...", "info")
            self._pos_load_branches()
            self.after(15000, self._ai_refresh_branches)  # retry after load
        else:
            self.ai_status_lbl.config(
                text=str(len(branches)) + " branch(es) available", fg=C["text4"])

    def _on_ai_branch_select(self, event=None):
        """Update topbar badge when AI branch is changed."""
        name = self.ai_branch_var.get()
        self.ai_branch_badge.config(text=name)

    def _ai_get_selected_branch(self):
        """
        Return (branch_id, branch_name) for the AI Insights analysis.
        'All Branches' returns ("all", "All Branches").
        """
        name = self.ai_branch_var.get()
        if name == "All Branches":
            return "all", "All Branches"
        # Look up the _id from loaded branches
        branches = getattr(self, "_pos_branches", [])
        b = next((x for x in branches if x["name"] == name), None)
        if b:
            bid = b["_id"]
            if bid.startswith("__NAME__:"):
                return "all", "All Branches"
            return bid, name
        return "all", "All Branches"

    def _ai_run_analysis(self):
        """Main entry point — collect data then call Claude."""
        self._pos_collect()
        api_key = self.cfg.get("anthropic_key","").strip()
        if not api_key:
            from tkinter import messagebox
            messagebox.showwarning("API Key Missing",
                "Please enter your Anthropic API Key in the POS Sync → "
                "QuickBill card and click Save.")
            self._show_page("pos_sync")
            return

        branch_name = self.cfg.get("quickbill_branch_name","All Branches")
        days        = int(self.ai_days_var.get())
        focus       = self.ai_focus_var.get()
        lang        = self.ai_lang_var.get()

        # Use AI Insights own branch selector (independent of POS Sync)
        ai_branch_id, branch_name = self._ai_get_selected_branch()

        self._ai_clear()
        self._ai_cancel.clear()   # reset stop flag for new run
        self.ai_branch_badge.config(text=branch_name)
        self.ai_status_lbl.config(text="Fetching data...", fg=C["accent"])
        self._set_busy(True, self.ai_progress)

        self._ai_write("Fetching " + str(days) + " days of sales data for: " +
                       branch_name + "\n\n", "muted")

        def _r():
            try:
                # Step 1: Fetch QuickBill data
                product_stats = self._ai_fetch_product_stats(
                    days, self._ai_cancel, ai_branch_id)
                if self._ai_cancel.is_set():
                    self._ai_write("\n[Stopped by user]\n", "warn_tag")
                    return
                if not product_stats:
                    self._ai_write("No sales data found for the selected period.\n",
                                   "warn_tag")
                    return

                # Update summary card
                total_items  = len(product_stats)
                total_orders = sum(p["orders"] for p in product_stats)
                total_rev    = sum(p["revenue"] for p in product_stats)
                def _upd():
                    self.ai_summary_lbl.config(
                        text=f"Products: {total_items}\n"
                             f"Orders: {total_orders}\n"
                             f"Revenue: Rs.{total_rev:,.0f}\n"
                             f"Period: {days} days\n"
                             f"Branch: {branch_name}")
                    self.ai_status_lbl.config(text="Analysing with Claude...",
                                              fg="#7c3aed")
                self.after(0, _upd)

                if self._ai_cancel.is_set():
                    self._ai_write("\n[Stopped by user]\n", "warn_tag")
                    return

                # Step 2: Build data summary for Claude
                data_summary = self._ai_build_summary(
                    product_stats, branch_name, days, total_orders, total_rev)

                # Step 3: Call Claude AI
                self._ai_write("Data loaded. Sending to Claude AI...\n\n", "muted")
                self._ai_call_claude(data_summary, branch_name, focus, lang, days)

            except Exception as e:
                self._ai_write("Error: " + str(e) + "\n", "warn_tag")
                self.after(0, lambda: self.ai_status_lbl.config(
                    text="Error", fg=C["red"]))
            finally:
                self.after(0, lambda: self._set_busy(False, self.ai_progress))

        threading.Thread(target=_r, daemon=True).start()

    def _ai_fetch_product_stats(self, days, cancel_event=None, branch_id=None):
        """
        Fetch sales data from QuickBill and aggregate by product name.
        Always fetches restaurant=all (branch filter by name causes 500),
        then filters client-side by resturant field if a specific branch
        is selected.
        """
        email    = self.cfg.get("quickbill_email","").strip()
        password = self.cfg.get("quickbill_password","").strip()

        # Resolve branch name for client-side filtering
        branch_name_filter = None   # None = all branches
        if branch_id and branch_id != "all":
            if branch_id.startswith("__NAME__:"):
                # ID not resolved — filter by the name part
                branch_name_filter = branch_id[len("__NAME__:"):]
            else:
                # Real MongoDB ID — find the name from loaded branches
                branches = getattr(self, "_pos_branches", [])
                b = next((x for x in branches if x["_id"] == branch_id), None)
                if b:
                    branch_name_filter = b["name"]

        session = _qb_get_session(email, password, lambda t,_: None)

        from datetime import date as _date
        today     = _date.today()
        start_day = today - timedelta(days=days)

        start_str = datetime.combine(start_day,
            datetime.min.time()).strftime("%a, %d %b %Y %H:%M:%S GMT")
        end_str   = datetime.combine(today,
            datetime.max.time()).strftime("%a, %d %b %Y %H:%M:%S GMT")

        # Always use restaurant=all to avoid 500 — filter client-side below
        ep = ("/api/reports?"
              "startDate=" + requests.utils.quote(start_str) +
              "&endDate="  + requests.utils.quote(end_str) +
              "&orderType=all&restaurant=all"
              "&selectedUser=all&paymentMethod=all&isCancelled=null"
              "&page=1&size=5000&searchQuery=")

        if cancel_event and cancel_event.is_set():
            return []

        r = session.get(QUICKBILL_URL + ep, timeout=60,
                        headers={"Accept": "application/json"})
        if r.status_code != 200:
            raise Exception("QuickBill API returned " + str(r.status_code))

        ct = r.headers.get("content-type","")
        if "html" in ct or r.text.strip().startswith("<"):
            raise Exception("Not authenticated — please test QuickBill login first")

        data  = r.json()
        sales = data.get("salesData", [])

        # Client-side branch filter
        if branch_name_filter:
            sales = [e for e in sales
                     if str(e.get("resturant","")).strip() == branch_name_filter]

        # Aggregate by product name
        stats = {}
        for entry in sales:
            if entry.get("isCancelled"): continue
            total = float(entry.get("totalSale", 0))
            raw_products = str(entry.get("product","")).split("\r\n")
            raw_qtys     = str(entry.get("quantity","")).split("\r\n")
            raw_products = [p.strip() for p in raw_products if p.strip()]
            raw_qtys     = [q.strip() for q in raw_qtys if q.strip()]
            n        = len(raw_products)
            unit_rev = total / n if n > 0 else 0

            for i, prod in enumerate(raw_products):
                if not prod: continue
                qty = 1.0
                if i < len(raw_qtys):
                    try: qty = float(raw_qtys[i])
                    except: qty = 1.0
                if prod not in stats:
                    stats[prod] = {"orders":0,"qty":0.0,"revenue":0.0}
                stats[prod]["orders"]  += 1
                stats[prod]["qty"]     += qty
                stats[prod]["revenue"] += unit_rev

        result = [{"name": k, **v} for k,v in stats.items()]
        result.sort(key=lambda x: x["qty"], reverse=True)
        return result

    def _ai_build_summary(self, stats, branch, days, total_orders, total_rev):
        """Build a concise text summary of product data for Claude."""
        top10    = stats[:10]
        bottom10 = stats[-10:] if len(stats) > 10 else []
        mid      = stats[10:-10] if len(stats) > 20 else []

        lines = [
            f"RESTAURANT BRANCH: {branch}",
            f"ANALYSIS PERIOD: Last {days} days",
            f"TOTAL ORDERS: {total_orders}",
            f"TOTAL REVENUE: Rs.{total_rev:,.0f}",
            f"UNIQUE PRODUCTS: {len(stats)}",
            "",
            "TOP 10 BEST SELLING PRODUCTS (by quantity):",
        ]
        for i, p in enumerate(top10, 1):
            lines.append(f"  {i}. {p['name']} — "
                         f"Qty: {p['qty']:.0f}, "
                         f"Orders: {p['orders']}, "
                         f"Revenue: Rs.{p['revenue']:,.0f}")

        if bottom10:
            lines += ["", "10 SLOWEST SELLING PRODUCTS:"]
            for p in bottom10:
                lines.append(f"  • {p['name']} — "
                             f"Qty: {p['qty']:.0f}, "
                             f"Orders: {p['orders']}, "
                             f"Revenue: Rs.{p['revenue']:,.0f}")

        if mid:
            lines += ["", f"REMAINING {len(mid)} PRODUCTS (sample):"]
            for p in mid[:5]:
                lines.append(f"  • {p['name']} — Qty: {p['qty']:.0f}")

        return "\n".join(lines)

    def _ai_call_claude(self, data_summary, branch, focus, lang, days):
        """Send data to Claude and stream the response to the report box."""
        api_key = self.cfg.get("anthropic_key","").strip()

        focus_instruction = {
            "All":           "Provide a comprehensive analysis covering all aspects.",
            "Top Sellers":   "Focus on why top sellers are performing well and how to maximize them.",
            "Slow Items":    "Focus on underperforming items — improve, bundle, or discontinue them.",
            "Revenue Growth":"Focus on revenue growth strategies and pricing opportunities.",
            "Menu Gaps":     "Identify missing product categories and suggest additions.",
            "Peak Hours":    "Analyse POS ordering patterns by hour (PKT). Identify peak hours per order type (Delivery/Takeaway/Dine-in). Suggest strategies to increase footfall during slow hours and manage capacity during peak hours. Include audience type analysis (who orders at what time).",
        }.get(focus, "Provide a comprehensive analysis.")

        lang_instruction = {
            "English": "Write the response in English.",
            "Urdu":    "Write the response in Urdu language (Roman Urdu is acceptable).",
            "Arabic":  "Write the response in Arabic language.",
        }.get(lang, "Write the response in English.")

        prompt = f"""You are an expert restaurant business consultant analyzing POS sales data.

{data_summary}

{focus_instruction}
{lang_instruction}

Please provide a detailed business analysis with the following sections:

1. 📊 PERFORMANCE SUMMARY
   - Overall sales health assessment
   - Revenue and order volume insights

2. 🌟 TOP PERFORMERS ANALYSIS
   - Why these items are popular
   - How to further maximize their sales

3. ⚠️ UNDERPERFORMING ITEMS
   - Items with low sales and what to do
   - Bundle or promotion suggestions

4. 💡 ACTIONABLE RECOMMENDATIONS (minimum 5 specific suggestions)
   - Menu optimization ideas
   - Pricing strategy suggestions
   - Combo/bundle opportunities
   - Marketing/promotion ideas
   - Operational improvements

5. 📈 REVENUE GROWTH OPPORTUNITIES
   - Specific items to push more aggressively
   - Upselling opportunities
   - New product ideas based on existing menu gaps

6. 🎯 PRIORITY ACTIONS (Top 3 things to do this week)

Keep recommendations specific, practical and actionable for a Pakistani restaurant."""

        try:
            client = _anthropic_sdk.Anthropic(api_key=api_key)

            # Write report header
            header = (
                "=" * 50 + "\n"
                f"  AI BUSINESS INSIGHTS REPORT\n"
                f"  Branch: {branch}\n"
                f"  Period: Last {days} days\n"
                f"  Focus: {focus}\n"
                f"  Generated: {datetime.now().strftime('%d %b %Y %H:%M')}\n"
                "=" * 50 + "\n\n"
            )
            self._ai_report_text = header
            self._ai_write(header, "muted")

            # Stream Claude response
            with client.messages.stream(
                model="claude-sonnet-4-20250514",
                max_tokens=3000,
                messages=[{"role": "user", "content": prompt}]
            ) as stream:
                for text in stream.text_stream:
                    # Check cancel flag on every token — stops within milliseconds
                    if self._ai_cancel.is_set():
                        stream.close()
                        self._ai_write("\n\n[⏹ Stopped by user]\n", "warn_tag")
                        self.after(0, lambda: self.ai_status_lbl.config(
                            text="Stopped", fg=C["amber"]))
                        return
                    self._ai_report_text += text
                    # Format headings differently
                    if any(h in text for h in ["📊","🌟","⚠️","💡","📈","🎯"]):
                        self._ai_write(text, "subheading")
                    else:
                        self._ai_write(text, "bullet")

            self._ai_write("\n\n[Analysis complete — Claude Sonnet]\n", "muted")
            self.after(0, lambda: self.ai_status_lbl.config(
                text="Analysis complete ✓", fg=C["green"]))

        except Exception as e:
            self._ai_write("\nClaude API error: " + str(e) + "\n", "warn_tag")
            self.after(0, lambda: self.ai_status_lbl.config(
                text="Claude error", fg=C["red"]))


    # ══════════════════════════════════════════════════════════════════════════
    #  SALES REMINDER PAGE  —  Zeeta Cargo  (HTTP session, Green API send)
    # ══════════════════════════════════════════════════════════════════════════

    def _build_sales_page(self):
        page = tk.Frame(self.main, bg=C["page"])
        self.pages["sales"] = page
        self._sales_active_data   = []
        self._sales_coord_info    = {}
        self._sales_reminder_map  = {}
        self._sales_running       = False
        self._sales_session       = None   # requests.Session after cookie paste

        # ── Top bar ──────────────────────────────────────────────────────────
        tp = tk.Frame(page, bg=C["topbar"], height=44)
        tp.pack(fill="x"); tp.pack_propagate(False)
        tk.Label(tp, text="  Zeeta ERP Sales & Activities", font=("Segoe UI",12,"bold"),
                 bg=C["topbar"], fg=C["text"]).pack(side="left", pady=10)
        self.sales_day_badge = tk.Label(tp, text="",
                 font=("Segoe UI",9), bg=C["accent_l"], fg=C["accent"])
        self.sales_day_badge.pack(side="left", padx=(8,0))
        self.sales_status_lbl = tk.Label(tp, text="● Ready",
                 font=("Segoe UI",9), bg=C["topbar"], fg=C["text4"])
        self.sales_status_lbl.pack(side="right", padx=16)
        tk.Frame(page, bg=C["border"], height=1).pack(fill="x")
        page = self._make_scrollable(page)

        # ── ROW 1: Login card (flex) + Send To (fixed 300px) — parallel ──────
        row1_frame = tk.Frame(page, bg=C["page"])
        row1_frame.pack(fill="x", padx=14, pady=(8,0))
        row1_frame.columnconfigure(0, weight=1)
        row1_frame.columnconfigure(1, weight=0, minsize=310)
        row1_frame.rowconfigure(0, weight=1)

        # Login card — takes all remaining width
        login_outer = tk.Frame(row1_frame, bg=C["border"], padx=1, pady=1)
        login_outer.grid(row=0, column=0, sticky="nsew", padx=(0,6))
        login_inner = tk.Frame(login_outer, bg=C["white"], padx=10, pady=6)
        login_inner.pack(fill="both", expand=True)

        login_hdr = tk.Frame(login_inner, bg=C["white"])
        login_hdr.pack(fill="x", pady=(0,6))
        dot_l = tk.Frame(login_hdr, bg=C["amber"], width=8, height=8)
        dot_l.pack(side="left", pady=3); dot_l.pack_propagate(False)
        tk.Frame(login_hdr, bg=C["border"], width=1, height=14).pack(side="left", padx=6)
        tk.Label(login_hdr, text="Zeeta Cargo Login (OTP Required)",
                 font=("Segoe UI",9,"bold"), bg=C["white"], fg=C["text"]).pack(side="left")
        self.sales_session_badge = tk.Label(login_hdr,
                 text="Not logged in", font=("Segoe UI",8),
                 bg=C["red_l"], fg=C["red"], padx=8, pady=2)
        self.sales_session_badge.pack(side="right")

        row1a = tk.Frame(login_inner, bg=C["white"])
        row1a.pack(fill="x", pady=(0,5))
        tk.Label(row1a, text="URL:", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text3"]).pack(side="left")
        self.sales_url_var = tk.StringVar(value=ZEETA_SALES_URL)
        tk.Entry(row1a, textvariable=self.sales_url_var,
                 font=("Consolas",9), bg=C["input"], fg=C["text2"],
                 relief="flat", bd=0, width=22,
                 highlightthickness=1, highlightbackground=C["border"]
                 ).pack(side="left", padx=(4,8), ipady=3)
        tk.Label(row1a, text="Username:", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text3"]).pack(side="left")
        self.sales_user_var = tk.StringVar()
        tk.Entry(row1a, textvariable=self.sales_user_var,
                 font=("Segoe UI",10), bg=C["input2"], fg=C["text2"],
                 relief="flat", bd=0, width=10,
                 highlightthickness=1, highlightbackground=C["border2"]
                 ).pack(side="left", padx=(4,8), ipady=3)
        tk.Label(row1a, text="Password:", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text3"]).pack(side="left")
        self.sales_pass_var = tk.StringVar()
        tk.Entry(row1a, textvariable=self.sales_pass_var,
                 font=("Segoe UI",10), bg=C["input2"], fg=C["text2"],
                 relief="flat", bd=0, width=10, show="*",
                 highlightthickness=1, highlightbackground=C["border2"]
                 ).pack(side="left", padx=(4,8), ipady=3)

        # ── Load saved credentials from config, auto-persist on change ───────
        # Password is base64-encoded (obfuscated, not encrypted — protects
        # only against casual glance at config.json, not a determined attacker).
        import base64 as _b64
        _cfg_sales = load_config()
        self.sales_user_var.set(
            _cfg_sales.get("zeeta_cargo_user", "") or "")
        try:
            _pass_b64 = _cfg_sales.get("zeeta_cargo_pass_b64", "") or ""
            if _pass_b64:
                _pass_plain = _b64.b64decode(
                    _pass_b64.encode("ascii")).decode("utf-8")
                self.sales_pass_var.set(_pass_plain)
        except Exception:
            pass  # Bad/corrupt encoded value — leave field blank

        def _save_zeeta_user(*_a):
            cfg = load_config()
            cfg["zeeta_cargo_user"] = self.sales_user_var.get().strip()
            save_config(cfg)

        def _save_zeeta_pass(*_a):
            cfg = load_config()
            p = self.sales_pass_var.get()
            if p:
                cfg["zeeta_cargo_pass_b64"] = _b64.b64encode(
                    p.encode("utf-8")).decode("ascii")
            else:
                cfg["zeeta_cargo_pass_b64"] = ""
            save_config(cfg)

        self.sales_user_var.trace_add("write", _save_zeeta_user)
        self.sales_pass_var.trace_add("write", _save_zeeta_pass)

        tk.Button(row1a, text="Send OTP",
                  command=self._sales_send_otp,
                  font=("Segoe UI",9,"bold"), bg=C["amber_l"], fg=C["amber"],
                  relief="flat", bd=0, padx=10, pady=3, cursor="hand2",
                  activebackground=C["amber"], activeforeground="white"
                  ).pack(side="left")

        row1b = tk.Frame(login_inner, bg=C["white"])
        row1b.pack(fill="x")
        tk.Label(row1b, text="OTP Code:", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text3"]).pack(side="left")
        self.sales_otp_var = tk.StringVar()
        self.sales_otp_entry = tk.Entry(row1b, textvariable=self.sales_otp_var,
                 font=("Consolas",12,"bold"), bg=C["input2"], fg=C["accent"],
                 insertbackground=C["accent"],
                 relief="flat", bd=0, width=10,
                 highlightthickness=1, highlightbackground=C["border2"])
        self.sales_otp_entry.pack(side="left", padx=(4,10), ipady=3)
        self.sales_otp_entry.bind("<Return>", lambda e: self._sales_verify_otp())
        tk.Button(row1b, text="Verify OTP & Login",
                  command=self._sales_verify_otp,
                  font=("Segoe UI",9,"bold"), bg=C["accent_l"], fg=C["accent"],
                  relief="flat", bd=0, padx=10, pady=3, cursor="hand2",
                  activebackground=C["accent"], activeforeground="white"
                  ).pack(side="left")
        self.sales_otp_hint = tk.Label(row1b,
                 text="Enter OTP after clicking Send OTP.",
                 font=("Segoe UI",8), bg=C["white"], fg=C["text4"])
        self.sales_otp_hint.pack(side="left", padx=(10,0))

        # ── Load Data button — full row below OTP, always visible ────────────
        row1c = tk.Frame(login_inner, bg=C["white"])
        row1c.pack(fill="x", pady=(6,0))
        tk.Button(row1c, text="⬇  Load Data",
                  command=self._sales_load_data,
                  font=("Segoe UI",10,"bold"), bg=C["accent"], fg="white",
                  relief="flat", bd=0, padx=20, pady=5, cursor="hand2",
                  activebackground="#1d4ed8", activeforeground="white"
                  ).pack(side="left")
        self.sales_load_hint = tk.Label(row1c,
                 text="Click after login to fetch today's sales report",
                 font=("Segoe UI",8), bg=C["white"], fg=C["text4"])
        self.sales_load_hint.pack(side="left", padx=(12,0))

        # Send To card — fixed 300px, same row as login
        coord_outer = tk.Frame(row1_frame, bg=C["border"], padx=1, pady=1)
        coord_outer.grid(row=0, column=1, sticky="nsew")
        coord_inner = tk.Frame(coord_outer, bg=C["white"], padx=10, pady=8)
        coord_inner.pack(fill="both", expand=True)
        coord_hdr = tk.Frame(coord_inner, bg=C["white"])
        coord_hdr.pack(fill="x", pady=(0,4))
        dot_c = tk.Frame(coord_hdr, bg=C["green"], width=8, height=8)
        dot_c.pack(side="left", pady=3); dot_c.pack_propagate(False)
        tk.Frame(coord_hdr, bg=C["border"], width=1, height=14).pack(side="left", padx=6)
        tk.Label(coord_hdr, text="Send To (Ctrl+click)",
                 font=("Segoe UI",9,"bold"), bg=C["white"], fg=C["text"]).pack(side="left")
        lb_frame = tk.Frame(coord_inner, bg=C["border"], padx=1, pady=1)
        lb_frame.pack(fill="both", expand=True)
        self.sales_coord_lb = tk.Listbox(lb_frame, font=("Segoe UI",9),
                                          bg=C["input"], fg=C["text2"],
                                          selectbackground=C["accent"],
                                          selectforeground="white",
                                          relief="flat", bd=0,
                                          selectmode=tk.MULTIPLE,
                                          activestyle="none", height=4)
        coord_sb = ttk.Scrollbar(lb_frame, orient="vertical", command=self.sales_coord_lb.yview)
        self.sales_coord_lb.configure(yscrollcommand=coord_sb.set)
        coord_sb.pack(side="right", fill="y")
        self.sales_coord_lb.pack(fill="both", expand=True, padx=3, pady=3)
        self.sales_coord_lb.insert("end", "-- Load data first --")
        coord_btns = tk.Frame(coord_inner, bg=C["white"])
        coord_btns.pack(fill="x", pady=(4,0))
        tk.Button(coord_btns, text="Select All", command=self._sales_coord_select_all,
                  font=("Segoe UI",8), bg=C["green_l"], fg=C["green"],
                  relief="flat", bd=0, padx=8, pady=3, cursor="hand2"
                  ).pack(side="left", padx=(0,4))
        tk.Button(coord_btns, text="Clear All", command=self._sales_coord_clear_all,
                  font=("Segoe UI",8), bg=C["red_l"], fg=C["red"],
                  relief="flat", bd=0, padx=8, pady=3, cursor="hand2"
                  ).pack(side="left")
        self.sales_coord_sel_lbl = tk.Label(coord_btns, text="0 selected",
                 font=("Segoe UI",8), bg=C["white"], fg=C["text4"])
        self.sales_coord_sel_lbl.pack(side="right")
        self.sales_coord_lb.bind("<<ListboxSelect>>", self._sales_on_coord_select)

        # ── Template picker row ───────────────────────────────────────────────
        tpl_outer = tk.Frame(page, bg=C["border"], padx=1, pady=1)
        tpl_outer.pack(fill="x", padx=14, pady=(8, 0))
        tpl_inner = tk.Frame(tpl_outer, bg=C["white"], padx=12, pady=8)
        tpl_inner.pack(fill="x")

        tk.Label(tpl_inner, text="Message Template:",
                 font=("Segoe UI", 9, "bold"),
                 bg=C["white"], fg=C["text"]).pack(side="left", padx=(0, 8))

        # Load saved templates + selected name from config
        cfg_now = load_config()
        saved = cfg_now.get("sales_templates") or {}
        if not saved:
            saved = {k: dict(v) for k, v in DEFAULT_SALES_TEMPLATES.items()}
        self._sales_templates = saved
        selected_name = cfg_now.get(
            "sales_template_selected", "English — Standard")
        if selected_name not in saved:
            selected_name = next(iter(saved.keys()), "English — Standard")

        self.sales_tpl_var = tk.StringVar(value=selected_name)
        self.sales_tpl_dropdown = ttk.Combobox(
            tpl_inner, textvariable=self.sales_tpl_var,
            values=list(saved.keys()), state="readonly",
            font=("Segoe UI", 9), width=32)
        self.sales_tpl_dropdown.pack(side="left", padx=(0, 8))
        self.sales_tpl_dropdown.bind(
            "<<ComboboxSelected>>", self._sales_on_template_change)

        tk.Button(tpl_inner, text="Edit templates",
                  command=self._sales_edit_templates,
                  font=("Segoe UI", 9),
                  bg=C["input"], fg=C["text2"], bd=0,
                  padx=12, pady=4, cursor="hand2").pack(
            side="left", padx=(0, 6))

        tk.Button(tpl_inner, text="Preview",
                  command=self._sales_preview_template,
                  font=("Segoe UI", 9, "bold"),
                  bg=C["accent_l"], fg=C["accent"], bd=0,
                  padx=12, pady=4, cursor="hand2").pack(side="left")

        tk.Label(tpl_inner,
                 text="  (applies to all coordinators in this run)",
                 font=("Segoe UI", 8),
                 bg=C["white"], fg=C["text4"]).pack(side="left")

        # ── Custom message + coordinator selector row ─────────────────────────
        top_cards = tk.Frame(page, bg=C["page"])
        top_cards.pack(fill="x", padx=14, pady=(8,0))
        top_cards.columnconfigure(0, weight=1)
        top_cards.columnconfigure(1, weight=0, minsize=280)

        # Custom message card
        msg_outer = tk.Frame(top_cards, bg=C["border"], padx=1, pady=1)
        msg_outer.grid(row=0, column=0, sticky="nsew", padx=(0,6))
        msg_inner = tk.Frame(msg_outer, bg=C["white"], padx=12, pady=10)
        msg_inner.pack(fill="both", expand=True)
        msg_hdr = tk.Frame(msg_inner, bg=C["white"])
        msg_hdr.pack(fill="x", pady=(0,6))
        dot_m = tk.Frame(msg_hdr, bg="#7c3aed", width=8, height=8)
        dot_m.pack(side="left", pady=3); dot_m.pack_propagate(False)
        tk.Frame(msg_hdr, bg=C["border"], width=1, height=14).pack(side="left", padx=6)
        tk.Label(msg_hdr, text="Custom Message (appended to reminder)",
                 font=("Segoe UI",9,"bold"), bg=C["white"], fg=C["text"]).pack(side="left")
        self.sales_msg_text = tk.Text(msg_inner, font=("Consolas",9), bg=C["input"],
                                       fg=C["text2"], insertbackground=C["accent"],
                                       relief="flat", bd=0, height=4, wrap="word",
                                       highlightthickness=1, highlightbackground=C["border"])
        self.sales_msg_text.pack(fill="both", expand=True)
        self.sales_msg_text.insert("1.0",
            "Note: Waqas is handling the admin part. In case of any vehicle issue, "
            "get it sorted with him as I have instructed Ms. Zainab for meeting the targets at any cost.")

        # ── Stat cards ────────────────────────────────────────────────────────
        stats_row = tk.Frame(page, bg=C["page"])
        stats_row.pack(fill="x", padx=14, pady=(8,0))
        self._sales_stat_labels = {}
        for label, bg, fg in [
            ("All Below Forecast", C["accent_l"], C["accent"]),
            ("Zero Sales",         C["amber_l"],  C["amber"]),
            ("Met Forecast",       C["green_l"],  C["green"]),
            ("Sent",               C["cyan_l"],   C["cyan"]),
        ]:
            box = tk.Frame(stats_row, bg=bg, padx=14, pady=8)
            box.pack(side="left", expand=True, fill="x", padx=(0,8))
            tk.Label(box, text=label, font=("Segoe UI",9), bg=bg, fg=fg).pack()
            num = tk.Label(box, text="0", font=("Segoe UI",20,"bold"), bg=bg, fg=fg)
            num.pack()
            self._sales_stat_labels[label] = num

        # ── Middle: Gap treeview (full width, no tracker) ────────────────────
        mid = tk.Frame(page, bg=C["page"])
        mid.pack(fill="both", expand=True, padx=14, pady=(8,0))
        mid.columnconfigure(0, weight=1)
        mid.rowconfigure(0, weight=1)

        tree_outer = tk.Frame(mid, bg=C["border"], padx=1, pady=1)
        tree_outer.grid(row=0, column=0, sticky="nsew")
        tree_inner = tk.Frame(tree_outer, bg=C["white"])
        tree_inner.pack(fill="both", expand=True)
        tree_hdr = tk.Frame(tree_inner, bg=C["white"], padx=10, pady=6)
        tree_hdr.pack(fill="x")
        dot_t = tk.Frame(tree_hdr, bg=C["accent"], width=8, height=8)
        dot_t.pack(side="left", pady=3); dot_t.pack_propagate(False)
        tk.Frame(tree_hdr, bg=C["border"], width=1, height=14).pack(side="left", padx=6)
        tk.Label(tree_hdr, text="All clients below forecast — grouped by coordinator · zero sales first · then % descending",
                 font=("Segoe UI",9,"bold"), bg=C["white"], fg=C["text"]).pack(side="left")
        tk.Frame(tree_inner, bg=C["border"], height=1).pack(fill="x")

        style = ttk.Style()
        style.configure("Sales.Treeview", font=("Segoe UI",9), rowheight=20,
                        background=C["input"], fieldbackground=C["input"],
                        foreground=C["text2"])
        style.configure("Sales.Treeview.Heading", font=("Segoe UI",8,"bold"),
                        background=C["accent_l"], foreground=C["accent"])
        self.sales_tree = ttk.Treeview(tree_inner, style="Sales.Treeview",
                                        columns=("coord","client","svc","forecast","actual","gap","pct","flag"),
                                        show="headings", height=8)
        for col, txt, w, stretch in [
            ("coord",    "Coordinator", 130, True),
            ("client",   "Client",      160, True),
            ("svc",      "Svc",          40, False),
            ("forecast", "Forecast",     88, False),
            ("actual",   "Actual",       88, False),
            ("gap",      "Gap (SAR)",    98, False),
            ("pct",      "% Behind",     68, False),
            ("flag",     "Flag",         90, False),
        ]:
            self.sales_tree.heading(col, text=txt)
            self.sales_tree.column(col, width=w, stretch=stretch)
        sales_vsb = ttk.Scrollbar(tree_inner, orient="vertical", command=self.sales_tree.yview)
        self.sales_tree.configure(yscrollcommand=sales_vsb.set)
        sales_vsb.pack(side="right", fill="y")
        self._add_tree_search(tree_inner, self.sales_tree, "Search coordinator / client...")
        self.sales_tree.pack(fill="both", expand=True)
        self.sales_tree.tag_configure("coord_hdr", foreground="white", background=C["text"])
        self.sales_tree.tag_configure("zero",      foreground=C["red"],   background=C["red_l"])
        self.sales_tree.tag_configure("high",      foreground=C["amber"], background=C["amber_l"])
        self.sales_tree.tag_configure("normal",    foreground=C["text2"], background=C["input"])

        # ── Zeeta ERP Activity section ───────────────────────────────────────
        erp_sec_hdr = tk.Frame(page, bg=C["page"])
        erp_sec_hdr.pack(fill="x", padx=14, pady=(8,0))
        dot_erp = tk.Frame(erp_sec_hdr, bg="#ea580c", width=8, height=8)
        dot_erp.pack(side="left", pady=4); dot_erp.pack_propagate(False)
        tk.Frame(erp_sec_hdr, bg=C["border"], width=1, height=14).pack(side="left", padx=6)
        tk.Label(erp_sec_hdr, text="Zeeta ERP — User Activity",
                 font=("Segoe UI",9,"bold"), bg=C["page"], fg=C["text"]).pack(side="left")
        # Date picker for ERP fetch
        tk.Label(erp_sec_hdr, text="Date:",
                 font=("Segoe UI",9), bg=C["page"], fg=C["text4"]).pack(side="left", padx=(12,4))
        self.sales_erp_date_pick = DateEntry(erp_sec_hdr, width=11,
                 font=("Segoe UI",9), date_pattern="dd/mm/yyyy",
                 background=C["accent"], foreground="white",
                 borderwidth=1, relief="flat")
        self.sales_erp_date_pick.pack(side="left")
        self.sales_erp_date_pick.set_date(date.today())
        self.sales_erp_date_lbl = tk.Label(erp_sec_hdr,
                 text="Click Fetch ERP Activity to load",
                 font=("Segoe UI",8), bg=C["page"], fg=C["text4"])
        self.sales_erp_date_lbl.pack(side="left", padx=(10,0))

        # ERP stat cards
        erp_stats_row = tk.Frame(page, bg=C["page"])
        erp_stats_row.pack(fill="x", padx=14, pady=(4,0))
        for i in range(5):
            erp_stats_row.columnconfigure(i, weight=1)

        erp_stat_defs = [
            ("Total Users",   "sv_tu",  C["accent_l"],  C["accent"]),
            ("Active Today",  "sv_at",  C["green_l"],   C["green"]),
            ("Low Activity",  "sv_la",  C["amber_l"],   C["amber"]),
            ("No ERP Login",  "sv_nl",  C["red_l"],     C["red"]),
            ("Total Actions", "sv_ta",  "#ede9fe",      "#5b21b6"),
        ]
        self._sales_erp_stat_vars = {}
        for col, (lbl, key, bg, fg) in enumerate(erp_stat_defs):
            card = tk.Frame(erp_stats_row, bg=bg, padx=10, pady=8)
            card.grid(row=0, column=col, sticky="ew",
                      padx=(0,6) if col < 4 else 0)
            tk.Label(card, text=lbl, font=("Segoe UI",8),
                     bg=bg, fg=fg).pack(anchor="w")
            var = tk.StringVar(value="—")
            self._sales_erp_stat_vars[key] = var
            tk.Label(card, textvariable=var,
                     font=("Segoe UI",16,"bold"),
                     bg=bg, fg=fg).pack(anchor="w")

        # ERP activity treeview
        erp_tree_outer = tk.Frame(page, bg=C["border"], padx=1, pady=1)
        erp_tree_outer.pack(fill="x", padx=14, pady=(6,0))
        erp_tree_inner = tk.Frame(erp_tree_outer, bg=C["white"])
        erp_tree_inner.pack(fill="both", expand=True)

        erp_tree_hdr = tk.Frame(erp_tree_inner, bg="#fff7ed", padx=10, pady=5)
        erp_tree_hdr.pack(fill="x")
        dot_et = tk.Frame(erp_tree_hdr, bg="#ea580c", width=7, height=7)
        dot_et.pack(side="left", pady=3); dot_et.pack_propagate(False)
        tk.Frame(erp_tree_hdr, bg=C["border"], width=1, height=13).pack(side="left", padx=5)
        tk.Label(erp_tree_hdr, text="Zeeta ERP — User Activity Log",
                 font=("Segoe UI",9,"bold"), bg="#fff7ed", fg=C["text"]).pack(side="left")
        tk.Frame(erp_tree_inner, bg=C["border"], height=1).pack(fill="x")

        erp_cols = ("logins","actions","last_action","last_module","first","last","level")
        self.sales_erp_tree = ttk.Treeview(erp_tree_inner,
                columns=erp_cols, show="tree headings",
                height=6, style="Sales.Treeview")
        self.sales_erp_tree.heading("#0",         text="Created By",   anchor="w")
        self.sales_erp_tree.heading("logins",     text="Trips Created",anchor="w")
        self.sales_erp_tree.heading("actions",    text="Unique Trips",  anchor="w")
        self.sales_erp_tree.heading("last_action",text="Last Client",   anchor="w")
        self.sales_erp_tree.heading("last_module",text="Last Status",   anchor="w")
        self.sales_erp_tree.heading("first",      text="First Trip",    anchor="w")
        self.sales_erp_tree.heading("last",       text="Last Trip",     anchor="w")
        self.sales_erp_tree.heading("level",      text="Activity",      anchor="w")
        self.sales_erp_tree.column("#0",          width=130, stretch=False)
        self.sales_erp_tree.column("logins",      width=90,  stretch=False, anchor="center")
        self.sales_erp_tree.column("actions",     width=80,  stretch=False, anchor="center")
        self.sales_erp_tree.column("last_action", width=200, stretch=True)
        self.sales_erp_tree.column("last_module", width=120, stretch=False)
        self.sales_erp_tree.column("first",       width=70,  stretch=False, anchor="center")
        self.sales_erp_tree.column("last",        width=70,  stretch=False, anchor="center")
        self.sales_erp_tree.column("level",       width=90,  stretch=False, anchor="center")

        self.sales_erp_tree.tag_configure("good",   background="#f0fdf4", foreground="#15803d")
        self.sales_erp_tree.tag_configure("warn",   background="#fffbeb", foreground="#92400e")
        self.sales_erp_tree.tag_configure("danger", background="#fef2f2", foreground="#991b1b")

        erp_vsb = ttk.Scrollbar(erp_tree_inner, orient="vertical",
                                command=self.sales_erp_tree.yview)
        self.sales_erp_tree.configure(yscrollcommand=erp_vsb.set)
        erp_vsb.pack(side="right", fill="y")
        self._add_tree_search(erp_tree_inner, self.sales_erp_tree, "Search user...")
        self.sales_erp_tree.pack(fill="both", expand=True)
        self.sales_erp_tree.insert("", "end", text="-- Click Fetch ERP Activity --",
                                   values=("","","","","","",""))
        # Double-click any row to see per-trip timestamped detail
        self.sales_erp_tree.bind("<Double-1>", self._sales_trip_detail)

        # ── Button bar ────────────────────────────────────────────────────────
        bf = tk.Frame(page, bg=C["page"])
        bf.pack(fill="x", padx=14, pady=(8,4))
        for txt, cmd, bg, fg in [
            ("Load Data",          self._sales_load_data,    C["accent_l"], C["accent"]),
            ("Fetch ERP Activity", self._sales_fetch_erp,    "#fff7ed",     "#c2410c"),
            ("Run Reminders",      self._sales_run,          C["green_l"],  C["green"]),
            ("Stop",               self._sales_stop,         C["red_l"],    C["red"]),
        ]:
            tk.Button(bf, text=txt, command=cmd, font=("Segoe UI",10,"bold"),
                      bg=bg, fg=fg, relief="flat", bd=0, padx=14, pady=7,
                      cursor="hand2", activebackground=fg, activeforeground="white"
                      ).pack(side="left", padx=(0,8))

        self.sales_progress = ttk.Progressbar(page, mode="indeterminate", style="TProgressbar")
        self.sales_progress.pack(fill="x", padx=14, pady=(0,4))

        # ── AI Intelligence panel ─────────────────────────────────────────────
        ai_outer = tk.Frame(page, bg=C["border"], padx=1, pady=1)
        ai_outer.pack(fill="x", padx=14, pady=(0,6))
        ai_inner = tk.Frame(ai_outer, bg=C["white"])
        ai_inner.pack(fill="both", expand=True)

        ai_hdr = tk.Frame(ai_inner, bg=C["white"], padx=10, pady=6)
        ai_hdr.pack(fill="x")
        dot_ai = tk.Frame(ai_hdr, bg="#7c3aed", width=8, height=8)
        dot_ai.pack(side="left", pady=3); dot_ai.pack_propagate(False)
        tk.Frame(ai_hdr, bg=C["border"], width=1, height=14).pack(side="left", padx=6)
        tk.Label(ai_hdr, text="Claude AI Intelligence",
                 font=("Segoe UI",9,"bold"), bg=C["white"], fg=C["text"]).pack(side="left")
        self.sales_ai_status = tk.Label(ai_hdr, text="Ready",
                 font=("Segoe UI",8), bg=C["white"], fg=C["text4"])
        self.sales_ai_status.pack(side="left", padx=(10,0))
        tk.Button(ai_hdr, text="Stop AI",
                  command=self._sales_ai_stop,
                  font=("Segoe UI",8), bg=C["red_l"], fg=C["red"],
                  relief="flat", bd=0, padx=8, pady=2, cursor="hand2"
                  ).pack(side="right")
        tk.Frame(ai_inner, bg=C["border"], height=1).pack(fill="x")

        # AI mode selector row
        ai_ctrl = tk.Frame(ai_inner, bg=C["white"], padx=10, pady=6)
        ai_ctrl.pack(fill="x")
        tk.Label(ai_ctrl, text="Mode:", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text3"]).pack(side="left")
        self.sales_ai_mode = tk.StringVar(value="Gap Analysis")
        for mode in ["Gap Analysis", "Smart Messages", "Escalation Check", "Reply Analyser"]:
            tk.Radiobutton(ai_ctrl, text=mode, variable=self.sales_ai_mode,
                           value=mode, font=("Segoe UI",9), bg=C["white"],
                           fg=C["accent"], selectcolor=C["white"],
                           activebackground=C["white"]
                           ).pack(side="left", padx=(8,0))

        # Language selector
        tk.Frame(ai_ctrl, bg=C["border"], width=1, height=16).pack(side="left", padx=(14,0))
        tk.Label(ai_ctrl, text="Lang:", font=("Segoe UI",9),
                 bg=C["white"], fg=C["text3"]).pack(side="left", padx=(8,0))
        self.sales_ai_lang = tk.StringVar(value="English")
        for lang in ["English", "Urdu", "Arabic"]:
            tk.Radiobutton(ai_ctrl, text=lang, variable=self.sales_ai_lang,
                           value=lang, font=("Segoe UI",9), bg=C["white"],
                           fg=C["text3"], selectcolor=C["white"],
                           activebackground=C["white"]
                           ).pack(side="left", padx=(6,0))

        # Reply input (for Reply Analyser mode)
        ai_reply_row = tk.Frame(ai_inner, bg=C["white"], padx=10, pady=0)
        ai_reply_row.pack(fill="x")
        tk.Label(ai_reply_row, text="Coordinator reply (for Reply Analyser):",
                 font=("Segoe UI",8), bg=C["white"], fg=C["text4"]).pack(anchor="w", pady=(0,3))
        self.sales_ai_reply_var = tk.StringVar()
        tk.Entry(ai_reply_row, textvariable=self.sales_ai_reply_var,
                 font=("Segoe UI",9), bg=C["input"], fg=C["text2"],
                 relief="flat", bd=0,
                 highlightthickness=1, highlightbackground=C["border"]
                 ).pack(fill="x", ipady=3)

        tk.Button(ai_inner, text="Run AI Analysis",
                  command=self._sales_ai_run,
                  font=("Segoe UI",10,"bold"), bg="#7c3aed", fg="white",
                  relief="flat", bd=0, padx=14, pady=7,
                  cursor="hand2", activebackground="#5b21b6", activeforeground="white"
                  ).pack(anchor="w", padx=10, pady=(0,8))

        # AI output box
        tk.Frame(ai_inner, bg=C["border"], height=1).pack(fill="x")
        self.sales_ai_box = scrolledtext.ScrolledText(
            ai_inner, font=("Consolas",9), bg=C["log_bg"],
            fg=C["text2"], insertbackground=C["accent"],
            relief="flat", bd=0, wrap="word", state="disabled",
            padx=12, pady=8, height=8)
        self.sales_ai_box.pack(fill="both", expand=True)
        self.sales_ai_box.tag_config("heading",    foreground="#7c3aed", font=("Segoe UI",10,"bold"))
        self.sales_ai_box.tag_config("subheading", foreground=C["accent"], font=("Segoe UI",9,"bold"))
        self.sales_ai_box.tag_config("body",       foreground=C["text2"])
        self.sales_ai_box.tag_config("good",       foreground=C["green"])
        self.sales_ai_box.tag_config("warn",       foreground=C["amber"])
        self.sales_ai_box.tag_config("urgent",     foreground=C["red"])
        self.sales_ai_box.tag_config("muted",      foreground=C["text4"])
        self._sales_ai_cancel = threading.Event()

        self.sales_log_box = self._log_panel(page, "sales")

    # ── Sales helpers ─────────────────────────────────────────────────────────

    def _sales_log(self, text, tag="info"):
        self._write_log(self.sales_log_box, text, tag)

    def _sales_on_show(self):
        today = date.today()
        if sales_is_working_day(today):
            self.sales_day_badge.config(
                text="Working Day " + today.strftime("%d %b"), bg=C["green_l"], fg=C["green"])
        else:
            self.sales_day_badge.config(
                text="Day Off", bg=C["amber_l"], fg=C["amber"])


    def _sales_set_stat(self, key, val):
        if key in self._sales_stat_labels:
            self.after(0, lambda v=val: self._sales_stat_labels[key].config(text=str(v)))

    def _sales_coord_select_all(self):
        self.sales_coord_lb.select_set(0, "end")
        self._sales_on_coord_select()

    def _sales_coord_clear_all(self):
        self.sales_coord_lb.select_clear(0, "end")
        self._sales_on_coord_select()

    def _sales_on_coord_select(self, event=None):
        n = len(self.sales_coord_lb.curselection())
        self.sales_coord_sel_lbl.config(text=str(n) + " selected")

    def _sales_get_selected_coords(self):
        """Return set of selected coordinator names, stripped cleanly."""
        idxs = self.sales_coord_lb.curselection()
        result = set()
        for i in idxs:
            raw = self.sales_coord_lb.get(i)
            # Format: "Name  [N client(s)]  (phone)" — split on double space
            name = raw.split("  ")[0].strip()
            if name and not name.startswith("--"):
                result.add(name)
        return result

    def _sales_fetch_erp(self):
        """Fetch Trip Log activity from c.zeetacargo.com via Playwright."""
        # Needs an authenticated session — reuse existing sales session cookies
        sess = getattr(self, "_sales_session_obj", None)
        if not sess:
            self._sales_log(
                "Not logged in — click Send OTP + Verify OTP & Login first.", "warn")
            return
        # Get selected date from picker
        try:
            sel_date = self.sales_erp_date_pick.get_date().strftime("%Y-%m-%d")
        except Exception:
            from datetime import date as _date
            sel_date = _date.today().strftime("%Y-%m-%d")
        self._set_busy(True, self.sales_progress)
        self._sales_log("Fetching Trip Logs from Zeeta Cargo for " + sel_date + "...", "info")
        import threading
        threading.Thread(target=self._sales_fetch_erp_thread,
                         args=(sess, sel_date), daemon=True).start()

    def _sales_fetch_erp_thread(self, sess, sel_date):
        """Background: use Playwright to scrape trip-log page and aggregate by user."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.after(0, lambda: self._sales_log(
                "Playwright not installed — run: pip install playwright", "err"))
            self.after(0, lambda: self._set_busy(False, self.sales_progress))
            return

        # ── Set permanent browser path (critical for frozen .exe) ─────────────
        import os as _os
        _pw_path = _os.path.join(_os.path.expanduser("~"),
                                 "AppData", "Local", "ms-playwright")
        _os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _pw_path

        # If Chromium not installed yet, install it now
        if not _os.path.exists(_pw_path) or not any(
                "chromium" in d.lower() for d in _os.listdir(_pw_path)
                if _os.path.isdir(_os.path.join(_pw_path, d))) if _os.path.exists(_pw_path) else True:
            self.after(0, lambda: self._sales_log(
                "Installing Chromium browser (first time only)...", "info"))
            try:
                import subprocess
                # Find python.exe in PATH (not the frozen exe)
                import shutil
                py = shutil.which("python") or shutil.which("python3")
                if py:
                    subprocess.run([py, "-m", "playwright", "install", "chromium"],
                                   timeout=120, check=True,
                                   env=dict(_os.environ, PLAYWRIGHT_BROWSERS_PATH=_pw_path))
                    self.after(0, lambda: self._sales_log(
                        "Chromium installed successfully.", "ok"))
                else:
                    self.after(0, lambda: self._sales_log(
                        "Python not found in PATH. Open CMD and run: "
                        "pip install playwright && playwright install chromium", "warn"))
            except Exception as ie:
                self.after(0, lambda e=str(ie): self._sales_log(
                    "Chromium install failed: " + e[:100] + 
                    " — Open CMD and run: playwright install chromium", "warn"))

        try:
            BASE = "https://c.zeetacargo.com"

            # Server ignores TripSearch[pickup_date_*] filter — confirmed
            # during Vehicle Tracker investigation. So we paginate from
            # page 1 onwards (newest first), filter rows in Python by
            # Pick Up Date, and stop when we've scrolled past sel_date.
            self.after(0, lambda: self._sales_log(
                "Playwright: scraping trips for " + sel_date + "...", "info"))

            # Header-based extraction JS — resilient to column reordering.
            # Looks up indexes by header name (lowercased), not hardcoded.
            scrape_js = """() => {
                const tbl = document.querySelector(
                    'table.table-striped.table-bordered')
                    || document.querySelector('table.table-striped');
                if (!tbl) return [];
                const heads = tbl.querySelectorAll('thead th');
                let tidIdx=-1, statusIdx=-1, pdIdx=-1;
                let clientIdx=-1, coordIdx=-1, driverIdx=-1;
                let fromIdx=-1, toIdx=-1, svcIdx=-1;
                let creatorIdx=-1, createdAtIdx=-1;
                heads.forEach((h, i) => {
                    const t = (h.innerText||'').trim().toLowerCase();
                    if (t === 'trip id' && tidIdx<0) tidIdx=i;
                    if (t === 'trip status' && statusIdx<0) statusIdx=i;
                    if ((t === 'pick up date' || t === 'pickup date')
                        && pdIdx<0) pdIdx=i;
                    if (t === 'client' && clientIdx<0) clientIdx=i;
                    if (t === 'coordinator' && coordIdx<0) coordIdx=i;
                    if (t === 'driver name' && driverIdx<0) driverIdx=i;
                    if (t === 'from' && fromIdx<0) fromIdx=i;
                    if (t === 'to' && toIdx<0) toIdx=i;
                    if (t === 'service type' && svcIdx<0) svcIdx=i;
                    if (t === 'created by' && creatorIdx<0) creatorIdx=i;
                    if (t === 'created at' && createdAtIdx<0) createdAtIdx=i;
                });
                const out = [];
                tbl.querySelectorAll('tbody tr').forEach(tr => {
                    const cs = tr.querySelectorAll('td');
                    if (cs.length < 20) return;
                    const tid = tidIdx>=0 && cs[tidIdx] ?
                        cs[tidIdx].innerText.trim() : '';
                    if (!tid) return;
                    if (tid.toLowerCase().includes('not set')) return;
                    if (!/^\\d+$/.test(tid)) return;
                    const get = i => i>=0 && cs[i] ?
                        cs[i].innerText.trim() : '';
                    out.push({
                        trip_id:     tid,
                        trip_status: get(statusIdx),
                        pick_date:   get(pdIdx),
                        client:      get(clientIdx),
                        coordinator: get(coordIdx),
                        driver_name: get(driverIdx),
                        from_loc:    get(fromIdx),
                        to_loc:      get(toIdx),
                        service:     get(svcIdx),
                        created_by:  get(creatorIdx),
                        created_at:  get(createdAtIdx),
                    });
                });
                return out;
            }"""

            # Parse "DD-MM-YY" or "DD-MM-YYYY" → date for client-side filter
            from datetime import date as _D, datetime as _DT
            def _parse_pd(s):
                if not s: return None
                s = s.strip()
                ps = s.replace("/", "-").split("-")
                if len(ps) != 3: return None
                try:
                    d = int(ps[0]); m = int(ps[1]); y = int(ps[2])
                    if y < 100: y += 2000
                    return _D(y, m, d)
                except Exception:
                    return None

            target_d = _DT.strptime(sel_date, "%Y-%m-%d").date()

            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                ctx     = browser.new_context()
                cookie_jar = []
                for name, value in sess.cookies.items():
                    cookie_jar.append({
                        "name":   name,
                        "value":  value,
                        "domain": "c.zeetacargo.com",
                        "path":   "/",
                    })
                ctx.add_cookies(cookie_jar)
                page = ctx.new_page()

                rows_data = []
                seen_ids = set()
                consecutive_old = 0
                MAX_PAGES = 60

                for page_num in range(1, MAX_PAGES + 1):
                    list_url = (BASE + "/backend/trips"
                                "?page=" + str(page_num))
                    try:
                        page.goto(list_url,
                                  wait_until="networkidle",
                                  timeout=60000)
                    except Exception as ex:
                        self.after(0,
                            lambda p=page_num, e=str(ex)[:80]:
                            self._sales_log(
                                "Page " + str(p) +
                                " load failed: " + e, "warn"))
                        break

                    if "login" in page.url.lower():
                        self.after(0, lambda: self._sales_log(
                            "Session expired — re-login first.",
                            "err"))
                        browser.close()
                        self.after(0, lambda:
                            self._set_busy(False, self.sales_progress))
                        return

                    batch = page.evaluate(scrape_js)
                    if not batch:
                        break

                    in_range = 0
                    too_old = 0
                    for rec in batch:
                        pd_obj = _parse_pd(rec.get("pick_date", ""))
                        if not pd_obj:
                            continue
                        if pd_obj < target_d:
                            too_old += 1
                            continue
                        if pd_obj > target_d:
                            # Newer trip — keep paginating
                            continue
                        # In-range (== target date)
                        in_range += 1
                        tid = rec.get("trip_id", "")
                        if tid and tid not in seen_ids:
                            seen_ids.add(tid)
                            rows_data.append(rec)

                    self.after(0,
                        lambda p=page_num, n=len(rows_data),
                        i=in_range, o=too_old:
                        self._sales_log(
                            "Page " + str(p) + " → " +
                            str(n) + " in-range trips "
                            "(" + str(i) + " on page, " +
                            str(o) + " too old)", "info"))

                    # Stop if entire page is older than target
                    if too_old >= len(batch) - 2:
                        consecutive_old += 1
                        if consecutive_old >= 2:
                            self.after(0, lambda:
                                self._sales_log(
                                    "Reached older trips — "
                                    "stopping.", "info"))
                            break
                    else:
                        consecutive_old = 0

                browser.close()

            self.after(0, lambda n=len(rows_data): self._sales_log(
                "Playwright: " + str(n) + " trips scraped", "ok"))

            if not rows_data:
                self.after(0, lambda: self._sales_log(
                    "No trips found for " + sel_date + " — try a different date.", "warn"))
                self.after(0, lambda: self._set_busy(False, self.sales_progress))
                return

            # Persist raw rows on self so the per-user detail popup can access
            # timestamped trip entries (trip_id, client, created_at, status) for
            # any coordinator when their row is double-clicked.
            self._sales_erp_raw_rows = rows_data
            self._sales_erp_raw_date = sel_date

            # Aggregate by Created By
            from collections import defaultdict
            agg = defaultdict(lambda: {
                "trips": 0, "trip_ids": set(),
                "first": "", "last": "",
                "last_client": "", "last_status": "",
                "coordinator": ""
            })

            for rec in rows_data:
                creator = rec.get("created_by","").strip()
                if not creator or creator in ("", "—", "Load Data"):
                    # fallback to coordinator
                    creator = rec.get("coordinator","").strip() or "Unknown"
                agg[creator]["trips"] += 1
                tid = rec.get("trip_id","")
                if tid:
                    agg[creator]["trip_ids"].add(tid)
                t = rec.get("created_at","")
                if t and len(t) >= 8:
                    ttime = t[9:14] if len(t) > 9 else t
                    if not agg[creator]["first"] or t < agg[creator]["first"]:
                        agg[creator]["first"] = ttime
                    if not agg[creator]["last"] or t > agg[creator]["last"]:
                        agg[creator]["last"] = ttime
                        agg[creator]["last_client"] = rec.get("client","")
                        agg[creator]["last_status"] = rec.get("trip_status","")
                if not agg[creator]["coordinator"]:
                    agg[creator]["coordinator"] = rec.get("coordinator","")

            rows = sorted(agg.items(), key=lambda x: -x[1]["trips"])
            total_trips = sum(v["trips"] for _, v in rows)
            active   = sum(1 for _, v in rows if v["trips"] >= 3)
            low      = sum(1 for _, v in rows if 0 < v["trips"] < 3)
            no_act   = sum(1 for _, v in rows if v["trips"] == 0)

            def _populate():
                self._sales_erp_stat_vars["sv_tu"].set(str(len(rows)))
                self._sales_erp_stat_vars["sv_at"].set(str(active))
                self._sales_erp_stat_vars["sv_la"].set(str(low))
                self._sales_erp_stat_vars["sv_nl"].set(str(no_act))
                self._sales_erp_stat_vars["sv_ta"].set("{:,}".format(total_trips))
                self.sales_erp_date_lbl.config(
                    text="Trips · " + sel_date, fg=C["green"])

                self.sales_erp_tree.delete(*self.sales_erp_tree.get_children())
                for name, v in rows:
                    t = v["trips"]
                    tag   = ("good" if t >= 3 else "warn" if t > 0 else "danger")
                    level = ("Active ✓" if t >= 3 else "Low ⚠" if t > 0 else "No Activity ⚠")
                    self.sales_erp_tree.insert("", "end", text=name,
                        values=(
                            str(t) + "×",
                            str(len(v["trip_ids"])),
                            v["last_client"][:45],
                            v["last_status"],
                            v["first"],
                            v["last"],
                            level,
                        ),
                        tags=(tag,))

                self._sales_log(
                    "ERP: " + str(len(rows)) + " staff · "
                    + "{:,}".format(total_trips) + " trips on " + sel_date, "ok")
                self._set_busy(False, self.sales_progress)

            self.after(0, _populate)

        except Exception as e:
            self.after(0, lambda e=str(e): self._sales_log(
                "ERP fetch error: " + e, "err"))
            self.after(0, lambda: self._set_busy(False, self.sales_progress))

    # ═════════════════════════════════════════════════════════════════════════
    # Sales ERP — per-user trip detail popup (double-click handler)
    # ═════════════════════════════════════════════════════════════════════════

    def _sales_trip_detail(self, event=None):
        """Open popup showing chronological trip entries for the clicked user."""
        rd = getattr(self, "_sales_erp_raw_rows", None)
        if not rd:
            self._sales_log(
                "Click 'Fetch ERP Activity' first, then double-click a row.",
                "warn")
            return

        sel = self.sales_erp_tree.selection()
        if not sel:
            return
        name = self.sales_erp_tree.item(sel[0], "text") or ""
        if name.startswith("--") or not name:
            return

        sel_date = getattr(self, "_sales_erp_raw_date", "")

        # Filter rows — created_by OR coordinator matches the clicked name
        # (matches the same fallback logic from the aggregation step)
        user_rows = []
        for r in rd:
            cb = (r.get("created_by", "") or "").strip()
            if not cb or cb in ("", "—", "Load Data"):
                cb = (r.get("coordinator", "") or "").strip() or "Unknown"
            if cb == name:
                user_rows.append(r)

        if not user_rows:
            self._sales_log(
                "No trips found for " + name + " in current data.", "warn")
            return

        self._sales_trip_detail_popup(name, sel_date, user_rows)

    def _sales_trip_detail_popup(self, name, sel_date, rows):
        """Build the per-user trip detail Toplevel (runs on main UI thread)."""

        def _parse_hhmm(ca):
            """Extract HH:MM from created_at string, tolerant of formats."""
            if not ca:
                return ""
            s = str(ca).strip()
            # Try common positions (YYYY-MM-DD HH:MM:SS, DD-MM-YYYY HH:MM:SS)
            for start in (11, 9, 10):
                if len(s) > start + 4:
                    chunk = s[start:start + 5]
                    if len(chunk) == 5 and chunk[2] == ":":
                        try:
                            h = int(chunk[:2])
                            m = int(chunk[3:])
                            if 0 <= h < 24 and 0 <= m < 60:
                                return chunk
                        except ValueError:
                            continue
            # Fallback: search for first HH:MM pattern
            import re
            m = re.search(r"(\d{1,2}):(\d{2})", s)
            if m:
                return m.group(1).zfill(2) + ":" + m.group(2)
            return ""

        def _parse_date(ca):
            """Extract YYYY-MM-DD from created_at string, tolerant of formats."""
            if not ca:
                return ""
            s = str(ca).strip()
            # Try first 10 chars as YYYY-MM-DD
            if len(s) >= 10 and s[4] in ("-", "/") and s[7] in ("-", "/"):
                return s[:10].replace("/", "-")
            # Try DD-MM-YYYY at start
            if len(s) >= 10 and s[2] in ("-", "/") and s[5] in ("-", "/"):
                try:
                    d, mo, y = s[:2], s[3:5], s[6:10]
                    return y + "-" + mo + "-" + d
                except Exception:
                    pass
            return s[:10] if len(s) >= 10 else s

        # Sort rows chronologically
        sorted_rows = sorted(
            rows, key=lambda r: str(r.get("created_at", "")))

        win = tk.Toplevel(self)
        win.title("Trip Detail — " + name)
        win.configure(bg=C["page"])
        win.geometry("820x620")
        win.transient(self)

        # ── Header ───────────────────────────────────────────────────────────
        hdr = tk.Frame(win, bg=C["white"])
        hdr.pack(fill="x", padx=14, pady=(14, 8))
        tk.Label(hdr, text=name,
                 font=("Segoe UI", 13, "bold"),
                 bg=C["white"], fg=C["text"]).pack(
            anchor="w", padx=14, pady=(12, 0))

        # Derive first/last trip times
        times = [_parse_hhmm(r.get("created_at", ""))
                 for r in sorted_rows]
        times = [t for t in times if t]
        first_t = times[0]  if times else "--"
        last_t  = times[-1] if times else "--"

        # Count unique trips
        unique_trips = len(set(
            (r.get("trip_id", "") or "").strip()
            for r in sorted_rows
            if (r.get("trip_id", "") or "").strip()
        ))

        tk.Label(hdr,
                 text=sel_date + "   ·   " +
                      str(len(sorted_rows)) + " trip entries · " +
                      str(unique_trips) + " unique trips · " +
                      first_t + " → " + last_t,
                 font=("Segoe UI", 9),
                 bg=C["white"], fg=C["text3"]).pack(
            anchor="w", padx=14, pady=(0, 10))

        # ── Summary cards ────────────────────────────────────────────────────
        cards = tk.Frame(win, bg=C["page"])
        cards.pack(fill="x", padx=14, pady=(0, 10))
        for i in range(4):
            cards.columnconfigure(i, weight=1, uniform="c")

        def _stat(col, lbl, val, accent=C["text"]):
            f = tk.Frame(cards, bg=C["input"])
            f.grid(row=0, column=col, sticky="ew", padx=3)
            tk.Label(f, text=lbl, font=("Segoe UI", 8),
                     bg=C["input"], fg=C["text3"]).pack(
                anchor="w", padx=10, pady=(8, 0))
            tk.Label(f, text=val,
                     font=("Segoe UI", 14, "bold"),
                     bg=C["input"], fg=accent).pack(
                anchor="w", padx=10, pady=(0, 8))

        # Count by status
        from collections import Counter
        status_counts = Counter(
            (r.get("trip_status", "") or "—").strip() or "—"
            for r in sorted_rows
        )
        top_status = status_counts.most_common(1)[0] \
            if status_counts else ("—", 0)

        _stat(0, "Entries",      str(len(sorted_rows)))
        _stat(1, "Unique trips", str(unique_trips))
        _stat(2, "First entry",  first_t)
        _stat(3, "Last entry",   last_t)

        # ── Filter bar ───────────────────────────────────────────────────────
        filt_bar = tk.Frame(win, bg=C["page"])
        filt_bar.pack(fill="x", padx=14, pady=(0, 4))
        tk.Label(filt_bar, text="Filter:",
                 font=("Segoe UI", 9),
                 bg=C["page"], fg=C["text3"]).pack(side="left")
        filt_var = tk.StringVar(value="")
        filt_entry = tk.Entry(filt_bar, textvariable=filt_var,
                               font=("Segoe UI", 9),
                               bg=C["input"], fg=C["text2"],
                               bd=0, relief="flat", width=30)
        filt_entry.pack(side="left", padx=(6, 0), ipady=3)
        tk.Label(filt_bar,
                 text="(search trip ID, client, or status)",
                 font=("Segoe UI", 8),
                 bg=C["page"], fg=C["text4"]).pack(side="left",
                                                     padx=(8, 0))

        # ── Entries table ────────────────────────────────────────────────────
        tk.Label(win, text="Trip entries (chronological)",
                 font=("Segoe UI", 9, "bold"),
                 bg=C["page"], fg=C["text2"]).pack(
            anchor="w", padx=18, pady=(6, 4))

        tbl_o = tk.Frame(win, bg=C["border"], padx=1, pady=1)
        tbl_o.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        tbl = ttk.Treeview(tbl_o, style="TD.Treeview",
                            columns=("time", "trip_id",
                                     "client", "status"),
                            show="headings", height=15)
        for col, txt, w, anc, stretch in [
            ("time",    "Time",    70,  "center", False),
            ("trip_id", "Trip ID", 130, "w",      False),
            ("client",  "Client",  320, "w",      True),
            ("status",  "Status",  140, "center", False),
        ]:
            tbl.heading(col, text=txt)
            tbl.column(col, width=w, anchor=anc, stretch=stretch)
        tbl.tag_configure("good",
                          background=C["green_l"], foreground=C["green"])
        tbl.tag_configure("warn",
                          background=C["amber_l"], foreground=C["amber"])
        tbl.tag_configure("danger",
                          background=C["red_l"], foreground=C["red"])
        tbl.tag_configure("norm",
                          background=C["input"], foreground=C["text2"])

        v = ttk.Scrollbar(tbl_o, orient="vertical",
                           command=tbl.yview)
        tbl.configure(yscrollcommand=v.set)
        v.pack(side="right", fill="y")
        tbl.pack(fill="both", expand=True)

        def _status_tag(s):
            """Color-code by status."""
            sl = (s or "").lower()
            if "complet" in sl:
                return "good"
            if "cancel" in sl or "reject" in sl or "fail" in sl:
                return "danger"
            if "progress" in sl or "pending" in sl or "hold" in sl:
                return "warn"
            return "norm"

        def _populate(q=""):
            tbl.delete(*tbl.get_children())
            ql = q.lower().strip()
            for r in sorted_rows:
                tid    = (r.get("trip_id", "")   or "").strip() or "—"
                client = (r.get("client", "")    or "").strip() or "—"
                status = (r.get("trip_status","") or "").strip() or "—"
                hhmm   = _parse_hhmm(r.get("created_at", ""))
                # Filter
                if ql:
                    hay = (tid + " " + client + " " + status).lower()
                    if ql not in hay:
                        continue
                tbl.insert("", "end",
                           values=(hhmm or "—", tid,
                                   client[:60], status),
                           tags=(_status_tag(status),))

        _populate()

        # Live filter
        def _on_filter(*_a):
            _populate(filt_var.get())
        filt_var.trace_add("write", _on_filter)

        # ── Close button ─────────────────────────────────────────────────────
        tk.Button(win, text="Close", font=("Segoe UI", 9),
                  bg=C["input"], fg=C["text2"], bd=0,
                  padx=24, pady=6,
                  activebackground=C["border"],
                  command=win.destroy).pack(pady=(4, 12))

    # ═════════════════════════════════════════════════════════════════════════
    # VEHICLE TRACKER PAGE
    # Scrapes Zeeta Cargo combinednew trip list, then each trip-view detail
    # to compute per-plate working/idle time from driver-app status logs.
    # ═════════════════════════════════════════════════════════════════════════

    def _build_vehicle_tracker_page(self):
        page = tk.Frame(self.main, bg=C["page"])
        self.pages["vehicle"] = page
        self._vt_cancel_flag    = False
        self._vt_plate_data     = {}   # plate -> {trips, working_s, idle_s, segments}
        self._vt_plate_types    = {}   # plate -> vehicle category ('Light Vehicle', 'Heavy Vehicle')
        self._vt_types_scraped  = False   # scrape once per session

        # ── Top bar ──────────────────────────────────────────────────────────
        tp = tk.Frame(page, bg=C["topbar"], height=44)
        tp.pack(fill="x"); tp.pack_propagate(False)
        tk.Label(tp, text="  Vehicle Tracker",
                 font=("Segoe UI", 12, "bold"),
                 bg=C["topbar"], fg=C["text"]).pack(side="left", pady=10)
        self.vt_session_lbl = tk.Label(
            tp, text="",
            font=("Segoe UI", 9),
            bg=C["topbar"], fg=C["text3"])
        self.vt_session_lbl.pack(side="right", padx=14)

        # ── Credential blocks: Fuel + GPS Tracking ───────────────────────────
        # Each block lets you fill URL+Username (saved) and Password (typed
        # each session). Click "Save ... Settings" to persist URL+Username.
        try:
            self.build_fuel_credentials_block(page, C)
        except Exception as _ex:
            self._vt_log("Fuel credentials block failed: " + str(_ex)[:120], "warn") if hasattr(self, "_vt_log") else None
        try:
            self.build_gps_credentials_block(page, C)
        except Exception as _ex:
            self._vt_log("GPS credentials block failed: " + str(_ex)[:120], "warn") if hasattr(self, "_vt_log") else None

        # ── Filter bar ───────────────────────────────────────────────────────
        fb_outer = tk.Frame(page, bg=C["border"], padx=1, pady=1)
        fb_outer.pack(fill="x", padx=14, pady=(10, 4))
        fb = tk.Frame(fb_outer, bg=C["white"])
        fb.pack(fill="x")

        tk.Label(fb, text="From:", font=("Segoe UI", 9),
                 bg=C["white"], fg=C["text3"]).pack(side="left",
                                                      padx=(12, 4),
                                                      pady=10)
        self.vt_date_from = DateEntry(
            fb, width=12, font=("Segoe UI", 9),
            background=C["accent"], foreground="white",
            borderwidth=0, date_pattern="yyyy-mm-dd")
        self.vt_date_from.pack(side="left")
        self.vt_date_from.set_date(date.today() - timedelta(days=6))

        tk.Label(fb, text="To:", font=("Segoe UI", 9),
                 bg=C["white"], fg=C["text3"]).pack(side="left",
                                                     padx=(12, 4),
                                                     pady=10)
        self.vt_date_to = DateEntry(
            fb, width=12, font=("Segoe UI", 9),
            background=C["accent"], foreground="white",
            borderwidth=0, date_pattern="yyyy-mm-dd")
        self.vt_date_to.pack(side="left")
        self.vt_date_to.set_date(date.today())

        tk.Label(fb, text="Plate filter:",
                 font=("Segoe UI", 9),
                 bg=C["white"], fg=C["text3"]).pack(side="left",
                                                      padx=(16, 4))
        self.vt_plate_var = tk.StringVar()
        tk.Entry(fb, textvariable=self.vt_plate_var,
                 font=("Segoe UI", 9), width=18,
                 bg=C["input"], bd=0).pack(side="left",
                                             padx=(0, 12),
                                             ipady=3)

        tk.Button(fb, text="Fetch", command=self._vt_fetch,
                  font=("Segoe UI", 9, "bold"),
                  bg=C["accent_l"], fg=C["accent"],
                  bd=0, padx=16, pady=5,
                  cursor="hand2").pack(side="left", padx=4)

        tk.Button(fb, text="Cancel", command=self._vt_cancel,
                  font=("Segoe UI", 9),
                  bg=C["input"], fg=C["text3"],
                  bd=0, padx=12, pady=5,
                  cursor="hand2").pack(side="left")

        self.vt_progress = ttk.Progressbar(
            fb, mode="indeterminate", length=120)
        self.vt_progress.pack(side="right", padx=(0, 12))

        # ── Summary cards ────────────────────────────────────────────────────
        cards_row = tk.Frame(page, bg=C["page"])
        cards_row.pack(fill="x", padx=14, pady=(6, 4))
        for i in range(4):
            cards_row.columnconfigure(i, weight=1, uniform="vt")
        self.vt_stat_vars = {
            "plates": tk.StringVar(value="—"),
            "work":   tk.StringVar(value="—"),
            "idle":   tk.StringVar(value="—"),
            "util":   tk.StringVar(value="—"),
        }
        for col, (k, lbl) in enumerate([
            ("plates", "Vehicles"),
            ("work",   "Total Working"),
            ("idle",   "Total Idle"),
            ("util",   "Avg Utilization"),
        ]):
            f = tk.Frame(cards_row, bg=C["white"],
                          bd=1, relief="solid",
                          highlightbackground=C["border"])
            f.grid(row=0, column=col, sticky="ew", padx=3)
            tk.Label(f, text=lbl, font=("Segoe UI", 8),
                     bg=C["white"], fg=C["text3"]).pack(
                anchor="w", padx=12, pady=(10, 0))
            tk.Label(f, textvariable=self.vt_stat_vars[k],
                     font=("Segoe UI", 14, "bold"),
                     bg=C["white"], fg=C["text"]).pack(
                anchor="w", padx=12, pady=(0, 10))

        # ── Main table ───────────────────────────────────────────────────────
        tbl_hdr = tk.Frame(page, bg=C["page"])
        tbl_hdr.pack(fill="x", padx=14, pady=(8, 4))
        tk.Label(tbl_hdr, text="Per-vehicle summary",
                 font=("Segoe UI", 10, "bold"),
                 bg=C["page"], fg=C["text"]).pack(side="left")
        tk.Label(tbl_hdr,
                 text="  Double-click a row for trip breakdown",
                 font=("Segoe UI", 8),
                 bg=C["page"], fg=C["text3"]).pack(side="left")

        tbl_outer = tk.Frame(page, bg=C["border"], padx=1, pady=1)
        tbl_outer.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        self.vt_tree = ttk.Treeview(
            tbl_outer, style="TD.Treeview",
            columns=("vtype",
                     "closed", "open", "nodata",
                     "working", "idle",
                     "cal_util", "disp_util",
                     "amt", "km",
                     "refills", "fuel_month",
                     "gps_work", "discrepancy",
                     "status"),
            show="tree headings", height=15)

        # Sort state: last column sorted + direction for toggle
        self._vt_sort = {"col": None, "reverse": False}

        # Sort-key converters per column — turn display text into comparable value
        def _k_text(v):     # plain text (for Plate, Status)
            return (v or "").lower()
        def _k_int(v):      # integer count (Closed/Open/No-Data)
            try: return int(v or 0)
            except: return 0
        def _k_pct(v):      # "84%" -> 84
            try: return int(str(v).replace("%", "").strip() or 0)
            except: return 0
        def _k_dur(v):      # "17h 01m" or "0h 35m" -> total minutes
            try:
                s = str(v).lower().strip()
                if not s or s == "—": return 0
                h = 0
                m = 0
                if "h" in s:
                    hp, rest = s.split("h", 1)
                    h = int(hp.strip() or 0)
                    s = rest
                if "m" in s:
                    mp = s.replace("m", "").strip()
                    m = int(mp or 0)
                return h * 60 + m
            except: return 0
        def _k_num(v):      # "1,234.5" or "47.5" -> float
            try:
                s = str(v).replace(",", "").strip()
                if not s or s == "—": return 0
                return float(s)
            except: return 0

        _sort_keys = {
            "#0":          _k_text,
            "vtype":       _k_text,
            "closed":      _k_int,
            "open":        _k_int,
            "nodata":      _k_int,
            "working":     _k_dur,
            "idle":        _k_dur,
            "cal_util":    _k_pct,
            "disp_util":   _k_pct,
            "amt":         _k_num,
            "km":          _k_num,
            "refills":     _k_int,
            "fuel_month":  _k_num,
            "gps_work":    _k_dur,
            "discrepancy": _k_dur,
            "status":      _k_text,
        }

        def _sort_by(col):
            # Toggle direction if clicking the same column again
            if self._vt_sort["col"] == col:
                self._vt_sort["reverse"] = not self._vt_sort["reverse"]
            else:
                self._vt_sort["col"] = col
                self._vt_sort["reverse"] = False
            reverse = self._vt_sort["reverse"]
            kfn = _sort_keys.get(col, _k_text)
            items = []
            for iid in self.vt_tree.get_children(""):
                if col == "#0":
                    val = self.vt_tree.item(iid, "text") or ""
                else:
                    val = self.vt_tree.set(iid, col) or ""
                # Skip placeholder row (keep it at top/bottom regardless)
                if (self.vt_tree.item(iid, "text") or "").startswith("--"):
                    items.append((("__placeholder__",), iid))
                else:
                    items.append((kfn(val), iid))
            items.sort(
                key=lambda x: (x[0] == ("__placeholder__",), x[0]),
                reverse=reverse)
            for i, (_, iid) in enumerate(items):
                self.vt_tree.move(iid, "", i)
            # Update header arrows
            for c, (txt, _) in _col_base_labels.items():
                arrow = ""
                if c == col:
                    arrow = " ▼" if reverse else " ▲"
                self.vt_tree.heading(c, text=txt + arrow)

        _col_base_labels = {}   # col_id -> (label, width)
        for col, txt, w, anc in [
            ("#0",          "Plate",            125, "w"),
            ("vtype",       "Vehicle Type",     115, "center"),
            ("closed",      "Closed",            55, "center"),
            ("open",        "Open",              50, "center"),
            ("nodata",      "No-Data",           60, "center"),
            ("working",     "Working Time",     105, "center"),
            ("idle",        "Idle Time",        105, "center"),
            ("cal_util",    "Calendar %",        85, "center"),
            ("disp_util",   "Dispatch %",        85, "center"),
            ("amt",         "Total Amount",      95, "e"),
            ("km",          "Total KM",          80, "e"),
            ("refills",     "Refills",           65, "center"),
            ("fuel_month",  "Total Fuel (Mo.)", 130, "center"),
            ("gps_work",    "GPS Working",      100, "center"),
            ("discrepancy", "Discrepancy",      105, "center"),
            ("status",      "Status",            90, "center"),
        ]:
            _col_base_labels[col] = (txt, w)
            self.vt_tree.heading(col, text=txt,
                                 command=lambda c=col: _sort_by(c))
            self.vt_tree.column(col, width=w,
                                 anchor=anc, stretch=False)
        self.vt_tree.tag_configure(
            "good", background=C["green_l"], foreground=C["green"])
        self.vt_tree.tag_configure(
            "warn", background=C["amber_l"], foreground=C["amber"])
        self.vt_tree.tag_configure(
            "danger", background=C["red_l"], foreground=C["red"])
        self.vt_tree.tag_configure(
            "normal", background=C["input"], foreground=C["text2"])
        self.vt_tree.tag_configure(
            "fuel_only", background=C["accent_l"], foreground=C["accent"])
        self.vt_tree.tag_configure(
            "mismatch", background=C["amber_l"], foreground=C["red"])
        self.vt_tree.tag_configure(
            "ghost", background=C["red_l"], foreground=C["red"])

        vt_vsb = ttk.Scrollbar(
            tbl_outer, orient="vertical",
            command=self.vt_tree.yview)
        self.vt_tree.configure(yscrollcommand=vt_vsb.set)
        vt_vsb.pack(side="right", fill="y")
        self.vt_tree.pack(fill="both", expand=True)
        self.vt_tree.insert(
            "", "end",
            text="-- Select dates and click Fetch --",
            values=("", "", "", "", "", "", "", "", "", "", "",
                    "", "", "", ""),
            tags=("normal",))
        self.vt_tree.bind("<Double-1>", self._vt_drilldown)

        # ── Log box ──────────────────────────────────────────────────────────
        log_outer = tk.Frame(page, bg=C["border"], padx=1, pady=1)
        log_outer.pack(fill="x", padx=14, pady=(0, 10))
        tk.Label(log_outer, text="Activity Log",
                 font=("Segoe UI", 9, "bold"),
                 bg=C["white"], fg=C["text2"]).pack(
            anchor="w", padx=12, pady=(8, 2))
        self.vt_log_box = scrolledtext.ScrolledText(
            log_outer, font=("Consolas", 9),
            bg=C["white"], fg=C["text2"],
            bd=0, padx=12, pady=4, height=5,
            state="disabled")
        self.vt_log_box.pack(fill="x", pady=(0, 8))
        self.vt_log_box.tag_config("ok",   foreground=C["green"])
        self.vt_log_box.tag_config("err",  foreground=C["red"])
        self.vt_log_box.tag_config("info", foreground=C["accent"])
        self.vt_log_box.tag_config("warn", foreground=C["amber"])
        self.vt_log_box.tag_config("ts",   foreground=C["text5"])

    def _vt_log(self, text, tag="info"):
        def _w():
            self.vt_log_box.config(state="normal")
            ts = datetime.now().strftime("%H:%M:%S")
            self.vt_log_box.insert("end", "[" + ts + "] ", "ts")
            self.vt_log_box.insert("end", text + "\n", tag)
            self.vt_log_box.see("end")
            self.vt_log_box.config(state="disabled")
        self.after(0, _w)

    def _vt_cancel(self):
        self._vt_cancel_flag = True
        self._vt_log("Cancel requested — finishing current trip...", "warn")

    def _vt_fetch(self):
        """Fetch entry-point — validates session and spawns background thread."""
        sess = getattr(self, "_sales_session_obj", None)
        if not sess:
            self._vt_log(
                "Not logged in — go to Sales Reminder page and login via OTP first.",
                "warn")
            self.vt_session_lbl.config(
                text="● Not logged in", fg=C["red"])
            return
        try:
            df = self.vt_date_from.get_date().strftime("%Y-%m-%d")
            dt = self.vt_date_to.get_date().strftime("%Y-%m-%d")
        except Exception:
            self._vt_log("Invalid date range.", "err")
            return
        if dt < df:
            self._vt_log("'To' date is before 'From' date.", "err")
            return
        self._vt_cancel_flag = False
        self.vt_session_lbl.config(text="● Session active", fg=C["green"])
        self.vt_progress.start(10)
        plate_f = self.vt_plate_var.get().strip().upper()
        self._vt_log("Fetching trips for " + df + " → " + dt +
                     (" (plate: " + plate_f + ")" if plate_f else "") + "...",
                     "info")
        threading.Thread(
            target=self._vt_fetch_thread,
            args=(sess, df, dt, plate_f),
            daemon=True).start()

    def _vt_fetch_thread(self, sess, df, dt_end, plate_filter):
        """Background: scrape combinednew trip list → per-trip detail → aggregate."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.after(0, lambda: self._vt_log(
                "Playwright not installed.", "err"))
            self.after(0, lambda: self.vt_progress.stop())
            return

        import os as _os
        _pw_path = _os.path.join(
            _os.path.expanduser("~"),
            "AppData", "Local", "ms-playwright")
        _os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _pw_path

        BASE = "https://c.zeetacargo.com"

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                ctx = browser.new_context()
                jar = []
                for n, v in sess.cookies.items():
                    jar.append({
                        "name": n, "value": v,
                        "domain": "c.zeetacargo.com",
                        "path": "/"})
                ctx.add_cookies(jar)

                page = ctx.new_page()

                # ── Step 0: Scrape plate → Vehicle Category once per session ─
                # Values: 'Light Vehicle' / 'Heavy Vehicle' (from /backend/vehicles)
                if not self._vt_types_scraped:
                    self.after(0, lambda: self._vt_log(
                        "Loading vehicle list (one-time)...", "info"))
                    try:
                        page.goto(
                            BASE + "/backend/vehicles",
                            wait_until="networkidle",
                            timeout=60000)
                        veh_js = """() => {
                            const t = document.querySelector(
                                'table.table-striped.table-bordered')
                                || document.querySelector(
                                    'table.table-striped');
                            if (!t) return [];
                            const hs = t.querySelectorAll('thead th');
                            let plateIdx = -1, catIdx = -1;
                            hs.forEach((h, i) => {
                                const x = (h.innerText||'').trim().toLowerCase();
                                if (x === 'plate number'
                                    && plateIdx < 0) plateIdx = i;
                                if (x === 'vehicle category'
                                    && catIdx < 0) catIdx = i;
                            });
                            const rs = t.querySelectorAll('tbody tr');
                            const out = [];
                            rs.forEach(r => {
                                const c = r.querySelectorAll('td');
                                if (!c.length) return;
                                const p = plateIdx >= 0 && c[plateIdx] ?
                                    c[plateIdx].innerText.trim() : '';
                                const v = catIdx >= 0 && c[catIdx] ?
                                    c[catIdx].innerText.trim() : '';
                                if (p) out.push({plate: p, cat: v});
                            });
                            return out;
                        }"""
                        veh_rows = page.evaluate(veh_js)
                        for rec in veh_rows:
                            p = (rec.get("plate", "") or "").strip()
                            v = (rec.get("cat", "") or "").strip()
                            if p:
                                self._vt_plate_types[p] = v or "—"
                        self._vt_types_scraped = True
                        self.after(0,
                            lambda n=len(self._vt_plate_types):
                            self._vt_log(
                                "Cached vehicle type for " + str(n) +
                                " plates.", "ok"))
                    except Exception as ex:
                        self.after(0,
                            lambda e=str(ex)[:80]:
                            self._vt_log(
                                "Vehicle types scrape failed (continuing): "
                                + e, "warn"))

                # ── Step 1: Get trip list from /trips endpoint ────────────────
                # Both /trips and /combinednew ignore myPageSize on this tenant,
                # capping at 50/page. So we paginate explicitly until empty.
                self.after(0, lambda: self._vt_log(
                    "Loading trip list...", "info"))

                trips_js = """() => {
                    // Target the trips table explicitly — page has 3 tables
                    // (2 date pickers + the data table). Match by class.
                    const tbl = document.querySelector(
                        'table.table-striped.table-bordered')
                        || document.querySelector('table.table-striped');
                    if (!tbl) return [];
                    const rows = tbl.querySelectorAll('tbody tr');
                    const out = [];
                    const heads = tbl.querySelectorAll('thead th');
                    let tidIdx = -1, plateIdx = -1, pdIdx = -1;
                    let fromIdx = -1, toIdx = -1;
                    let ttypeIdx = -1, amtIdx = -1, kmIdx = -1;
                    heads.forEach((h, i) => {
                        const t = (h.innerText||'').trim().toLowerCase();
                        if (t === 'trip id' && tidIdx < 0) tidIdx = i;
                        if ((t === 'vehicle' || t === 'plate')
                            && plateIdx < 0) plateIdx = i;
                        if ((t === 'pick up date' || t === 'pickup date')
                            && pdIdx < 0) pdIdx = i;
                        if (t === 'from' && fromIdx < 0) fromIdx = i;
                        if (t === 'to' && toIdx < 0) toIdx = i;
                        if (t === 'trip type' && ttypeIdx < 0) ttypeIdx = i;
                        if (t === 'total amount' && amtIdx < 0) amtIdx = i;
                        // "Actual Driven Km's" — header uses backtick apostrophe
                        if (t.startsWith('actual driven') && kmIdx < 0)
                            kmIdx = i;
                    });
                    rows.forEach(r => {
                        const cs = r.querySelectorAll('td');
                        if (cs.length < 7) return;
                        const tid = tidIdx >= 0 && cs[tidIdx] ?
                            cs[tidIdx].innerText.trim() : '';
                        const pl = plateIdx >= 0 && cs[plateIdx] ?
                            cs[plateIdx].innerText.trim() : '';
                        const pd = pdIdx >= 0 && cs[pdIdx] ?
                            cs[pdIdx].innerText.trim() : '';
                        const fr = fromIdx >= 0 && cs[fromIdx] ?
                            cs[fromIdx].innerText.trim() : '';
                        const to = toIdx >= 0 && cs[toIdx] ?
                            cs[toIdx].innerText.trim() : '';
                        const tty = ttypeIdx >= 0 && cs[ttypeIdx] ?
                            cs[ttypeIdx].innerText.trim() : '';
                        const amt = amtIdx >= 0 && cs[amtIdx] ?
                            cs[amtIdx].innerText.trim() : '';
                        const km = kmIdx >= 0 && cs[kmIdx] ?
                            cs[kmIdx].innerText.trim() : '';
                        if (!tid) return;
                        if (tid.toLowerCase().includes('not set')) return;
                        if (!/^\\d+$/.test(tid)) return;
                        out.push({trip_id: tid, plate: pl,
                                  pick_date: pd,
                                  pickup: fr, destination: to,
                                  trip_type: tty,
                                  total_amount: amt,
                                  total_km: km});
                    });
                    return out;
                }"""

                # Parse "DD-MM-YY" or "DD-MM-YYYY" into a comparable date object
                def _parse_pd(s):
                    if not s: return None
                    s = s.strip()
                    parts = s.replace("/", "-").split("-")
                    if len(parts) != 3: return None
                    try:
                        d = int(parts[0]); m = int(parts[1])
                        y = int(parts[2])
                        if y < 100: y += 2000
                        from datetime import date as _d
                        return _d(y, m, d)
                    except Exception:
                        return None

                from datetime import datetime as _dt2
                df_obj = _dt2.strptime(df, "%Y-%m-%d").date()
                dt_obj = _dt2.strptime(dt_end, "%Y-%m-%d").date()

                trips = []
                page_num = 1
                seen_ids = set()
                MAX_PAGES = 80   # safety cap
                consecutive_old_pages = 0
                while page_num <= MAX_PAGES:
                    if self._vt_cancel_flag:
                        break
                    # The server ignores TripSearch date filters — paginate
                    # through all recent trips sorted newest-first, filter
                    # client-side, stop when 2 pages in a row are all too old
                    list_url = (
                        BASE + "/backend/trips"
                        "?page=" + str(page_num))
                    try:
                        page.goto(list_url,
                                  wait_until="networkidle",
                                  timeout=60000)
                    except Exception as ex:
                        self.after(0,
                            lambda p=page_num, e=str(ex)[:80]:
                            self._vt_log(
                                "List page " + str(p) +
                                " failed: " + e, "warn"))
                        break
                    if "login" in page.url.lower():
                        self.after(0, lambda: self._vt_log(
                            "Session expired — re-login via "
                            "Sales Reminder.", "err"))
                        browser.close()
                        self.after(0,
                            lambda: self.vt_progress.stop())
                        return
                    batch = page.evaluate(trips_js)
                    if not batch:
                        break

                    in_range = 0
                    too_old = 0
                    new_in_range = 0
                    for rec in batch:
                        tid = rec.get("trip_id", "")
                        pd_str = rec.get("pick_date", "")
                        pd_obj = _parse_pd(pd_str)
                        if not pd_obj:
                            continue
                        if pd_obj < df_obj:
                            too_old += 1
                            continue
                        if pd_obj > dt_obj:
                            # Trip is newer than our "To" date — skip but
                            # don't count as old (could be scrolling past)
                            continue
                        in_range += 1
                        if tid and tid not in seen_ids:
                            seen_ids.add(tid)
                            trips.append(rec)
                            new_in_range += 1

                    self.after(0,
                        lambda p=page_num, n=len(trips),
                        i=in_range, o=too_old:
                        self._vt_log(
                            "Page " + str(p) + " → " +
                            str(n) + " in-range trips "
                            "(" + str(i) + " on page, " +
                            str(o) + " too old)", "info"))

                    # Stop if whole page was older than our From date
                    # (results are sorted newest-first)
                    if too_old >= len(batch) - 2:
                        consecutive_old_pages += 1
                        if consecutive_old_pages >= 2:
                            self.after(0, lambda: self._vt_log(
                                "Reached trips older than From date — "
                                "stopping.", "info"))
                            break
                    else:
                        consecutive_old_pages = 0
                    page_num += 1

                self.after(0, lambda n=len(trips): self._vt_log(
                    str(n) + " trips found in list", "ok"))

                # Apply plate filter if specified
                if plate_filter:
                    trips = [t for t in trips
                             if plate_filter in
                             (t.get("plate", "") or "").upper()]
                    self.after(0, lambda n=len(trips): self._vt_log(
                        "After plate filter: " + str(n) + " trips", "info"))

                if not trips:
                    self.after(0, lambda: self._vt_log(
                        "No trips to process.", "warn"))
                    browser.close()
                    self.after(0, lambda: self.vt_progress.stop())
                    return

                # ── Step 2: Fetch each trip's status log via requests ─────────
                # Playwright is too slow (~3s/trip) because it runs JS + waits
                # for network idle. The modal HTML is in the raw response, so
                # we use the existing requests.Session for per-trip fetches.
                # Expected speedup vs Playwright: ~8-10x.
                per_trip = {}
                total = len(trips)
                import re as _re

                _p_title = _re.compile(
                    r'class="title">([^<]+)<')
                _p_date = _re.compile(
                    r'data-date="([^"]+)"')
                META_TITLES = {
                    "total hours", "total time", "summary"}

                def _parse_modal_html(html):
                    """Extract (status, date) pairs from the modal section."""
                    i1 = html.find('id="trip-log-modal"')
                    if i1 < 0:
                        return []
                    i2 = html.find(
                        'id="trip-advance-log-modal"', i1)
                    if i2 < 0:
                        i2 = len(html)
                    mhtml = html[i1:i2]
                    titles = _p_title.findall(mhtml)
                    dates  = _p_date.findall(mhtml)
                    out = []
                    di = 0
                    for t in titles:
                        tnm = (t or "").strip()
                        if not tnm:
                            continue
                        if tnm.lower() in META_TITLES:
                            continue
                        if di >= len(dates):
                            continue
                        out.append({
                            "status": tnm,
                            "date":   dates[di],
                        })
                        di += 1
                    return out

                for i, rec in enumerate(trips):
                    if self._vt_cancel_flag:
                        self.after(0, lambda: self._vt_log(
                            "Cancelled by user.", "warn"))
                        break
                    tid = rec.get("trip_id", "")
                    plate = (rec.get("plate", "") or "").strip() or "Unknown"
                    if not tid:
                        continue
                    if (i + 1) % 20 == 0 or (i + 1) == total:
                        self.after(0,
                            lambda i=i, t=total: self._vt_log(
                                "Processed " + str(i + 1) + " / " +
                                str(t) + " trips", "info"))
                    detail_url = BASE + "/backend/trips/view?id=" + tid
                    logs = None
                    for attempt in (1, 2):
                        try:
                            resp = sess.get(detail_url, timeout=25)
                            if resp.status_code != 200:
                                break
                            logs = _parse_modal_html(resp.text)
                            break
                        except Exception as ex:
                            if attempt >= 2:
                                self.after(0,
                                    lambda t=tid, e=str(ex)[:80]:
                                    self._vt_log(
                                        "Trip " + t + " fetch failed: " + e,
                                        "warn"))
                    if logs is None:
                        continue
                    per_trip[tid] = {
                        "plate": plate,
                        "pickup": (rec.get("pickup", "") or "").strip(),
                        "destination": (rec.get("destination", "") or "").strip(),
                        "trip_type": (rec.get("trip_type", "") or "").strip(),
                        "total_amount": (rec.get("total_amount", "") or "").strip(),
                        "total_km": (rec.get("total_km", "") or "").strip(),
                        "statuses": logs,
                    }

                browser.close()

            # ── Step 3: Compute per-trip working & end timestamps ────────────
            from datetime import datetime as _dt

            def parse_iso(s):
                try:
                    return _dt.fromisoformat(s)
                except Exception:
                    return None

            # Status names that mark a trip as properly "closed"
            CLOSED_ENDS = (
                "Arrived Accommodation",
                "Standby Ended",
            )

            # plate -> list of trip dicts (with "kind" field)
            plate_trips = {}
            tot_closed = 0
            tot_open   = 0
            tot_nodata = 0
            tot_bad    = 0   # start after end (data corruption)

            for tid, info in per_trip.items():
                plate = info["plate"]
                pickup = info.get("pickup", "")
                destination = info.get("destination", "")
                trip_type = info.get("trip_type", "")
                total_amount = info.get("total_amount", "")
                total_km = info.get("total_km", "")
                stmap = {}
                last_dt = None
                last_status = ""
                for ent in info["statuses"]:
                    nm = (ent.get("status", "") or "").strip()
                    dt_str = ent.get("date", "") or ""
                    dts = parse_iso(dt_str)
                    if nm and dts:
                        if nm not in stmap or dts > stmap[nm]:
                            stmap[nm] = dts
                        if last_dt is None or dts > last_dt:
                            last_dt = dts
                            last_status = nm

                # No statuses at all → zero-data trip
                if not stmap:
                    plate_trips.setdefault(plate, []).append({
                        "tid": tid,
                        "kind": "nodata",
                        "start": None,
                        "end":   None,
                        "last_status": "",
                        "work":  0,
                        "pickup": pickup,
                        "destination": destination,
                        "trip_type": trip_type,
                        "total_amount": total_amount,
                        "total_km": total_km,
                    })
                    tot_nodata += 1
                    continue

                start_dt = stmap.get("Depart for Pick Up Point")

                # Check for properly-closed trip
                closed_end = None
                closed_name = ""
                for nm in CLOSED_ENDS:
                    if nm in stmap:
                        if closed_end is None or stmap[nm] > closed_end:
                            closed_end = stmap[nm]
                            closed_name = nm

                if start_dt and closed_end:
                    if closed_end <= start_dt:
                        tot_bad += 1
                        continue
                    work_s = int(
                        (closed_end - start_dt).total_seconds())
                    plate_trips.setdefault(plate, []).append({
                        "tid": tid,
                        "kind": "closed",
                        "start": start_dt,
                        "end":   closed_end,
                        "last_status": closed_name,
                        "work":  work_s,
                        "pickup": pickup,
                        "destination": destination,
                        "trip_type": trip_type,
                        "total_amount": total_amount,
                        "total_km": total_km,
                    })
                    tot_closed += 1
                    continue

                # Open trip: has some log data but no proper end.
                # Use last-logged-status timestamp as working-end proxy.
                if start_dt and last_dt and last_dt > start_dt:
                    work_s = int(
                        (last_dt - start_dt).total_seconds())
                    plate_trips.setdefault(plate, []).append({
                        "tid": tid,
                        "kind": "open",
                        "start": start_dt,
                        "end":   last_dt,
                        "last_status": last_status,
                        "work":  work_s,
                        "pickup": pickup,
                        "destination": destination,
                        "trip_type": trip_type,
                        "total_amount": total_amount,
                        "total_km": total_km,
                    })
                    tot_open += 1
                    continue

                # No usable start (only Accepted logged, or similar)
                # Still include as open, with zero working time
                plate_trips.setdefault(plate, []).append({
                    "tid": tid,
                    "kind": "open",
                    "start": last_dt,
                    "end":   last_dt,
                    "last_status": last_status,
                    "work":  0,
                    "pickup": pickup,
                    "destination": destination,
                    "trip_type": trip_type,
                    "total_amount": total_amount,
                    "total_km": total_km,
                })
                tot_open += 1

            # Log classification summary
            self.after(0, lambda
                c=tot_closed, o=tot_open,
                n=tot_nodata, b=tot_bad:
                self._vt_log(
                    "Trip classification: " + str(c) +
                    " closed, " + str(o) + " open, " +
                    str(n) + " no-data, " + str(b) + " bad",
                    "info"))

            # ── Step 4: Compute idle gaps per plate ──────────────────────────
            # Calculate the date range in hours for calendar utilization
            from datetime import datetime as _dt_range
            _range_start = _dt_range.strptime(df, "%Y-%m-%d")
            _range_end   = _dt_range.strptime(dt_end, "%Y-%m-%d")
            # Inclusive range: from 00:00 on df to 23:59 on dt_end
            _range_hours = (
                (_range_end - _range_start).days + 1) * 24
            _range_seconds = _range_hours * 3600

            # Detect "pool" identifiers (not real plates) — these aggregate
            # many vehicles into one label and skew per-plate stats
            def _is_pool_label(p):
                if not p:
                    return True
                pl = p.lower()
                pool_kw = ("call out", "call-out", "callout",
                           "pool", "unassigned", "truck call",
                           "suv call")
                for kw in pool_kw:
                    if kw in pl:
                        return True
                return False

            plate_agg = {}
            pool_plates_filtered = []
            for plate, tlist in plate_trips.items():
                if _is_pool_label(plate):
                    pool_plates_filtered.append(
                        (plate, len(tlist)))
                    continue

                def _sort_key(t):
                    return (t["start"] or t["end"]
                            or parse_iso("1970-01-01T00:00:00"))
                tlist.sort(key=_sort_key)

                total_work = sum(t["work"] for t in tlist)
                n_closed = sum(1 for t in tlist if t["kind"] == "closed")
                n_open   = sum(1 for t in tlist if t["kind"] == "open")
                n_nodata = sum(1 for t in tlist if t["kind"] == "nodata")

                # Parse and sum Total Amount + Total KM from per-trip data
                def _parse_num(s):
                    if not s: return 0.0
                    s = str(s).strip().replace(",", "")
                    import re as _re_n
                    m = _re_n.match(r"([\d.]+)", s)
                    if m:
                        try: return float(m.group(1))
                        except: return 0.0
                    return 0.0
                total_amt_sum = sum(
                    _parse_num(t.get("total_amount", ""))
                    for t in tlist)
                total_km_sum = sum(
                    _parse_num(t.get("total_km", ""))
                    for t in tlist)

                closed_only = [t for t in tlist if t["kind"] == "closed"]
                closed_only.sort(key=lambda x: x["start"])
                idle_segs = []
                total_idle = 0
                for i in range(1, len(closed_only)):
                    prev_end = closed_only[i - 1]["end"]
                    this_start = closed_only[i]["start"]
                    gap = (this_start - prev_end).total_seconds()
                    if gap > 0:
                        total_idle += int(gap)
                        idle_segs.append({
                            "from": prev_end,
                            "to":   this_start,
                            "secs": int(gap),
                        })

                # Dispatch utilization: of the time the vehicle was engaged
                # (working + idle between trips), how much was productive?
                span = total_work + total_idle
                dispatch_util = round(
                    total_work * 100 / span) if span else 0
                # Cap at 100% for sanity (shouldn't happen, but guards nodata)
                if dispatch_util > 100:
                    dispatch_util = 100

                # Calendar utilization: of total hours in the date range,
                # how much was the vehicle working?
                cal_util = round(
                    total_work * 100 / _range_seconds) \
                    if _range_seconds else 0
                if cal_util > 100:
                    cal_util = 100

                plate_agg[plate] = {
                    "trips":         tlist,
                    "v_type":        self._vt_plate_types.get(plate, "—"),
                    "n_closed":      n_closed,
                    "n_open":        n_open,
                    "n_nodata":      n_nodata,
                    "work_s":        total_work,
                    "idle_s":        total_idle,
                    "idle_segs":     idle_segs,
                    "util":          dispatch_util,  # kept for compat
                    "dispatch_util": dispatch_util,
                    "cal_util":      cal_util,
                    "total_amt":     total_amt_sum,
                    "total_km":      total_km_sum,
                }

            # Surface pool-row filtering in the log for transparency
            if pool_plates_filtered:
                n_pools = len(pool_plates_filtered)
                n_trips = sum(
                    c for _, c in pool_plates_filtered)
                self.after(0, lambda
                    n=n_pools, t=n_trips:
                    self._vt_log(
                        "Filtered " + str(n) +
                        " pool label(s) with " + str(t) +
                        " trips (Call-out pools, etc.)",
                        "info"))

            # ── Step 4.5: Fuel website integration ───────────────────────────
            try:
                fuel_data = self.fuel_fetch_refills(df, dt_end)
            except Exception as _fex:
                self.after(0, lambda e=str(_fex)[:120]: self._vt_log(
                    "Fuel fetch error (continuing without fuel data): "
                    + e, "warn"))
                fuel_data = None
            try:
                self.fuel_merge_into_plate_agg(plate_agg, fuel_data)
            except Exception as _fex:
                self.after(0, lambda e=str(_fex)[:120]: self._vt_log(
                    "Fuel merge error: " + e, "warn"))

            # ── Step 4.6: GPS tracking website integration ───────────────────
            try:
                gps_data = self.gps_fetch_activity(df, dt_end)
            except Exception as _gex:
                self.after(0, lambda e=str(_gex)[:120]: self._vt_log(
                    "GPS fetch error (continuing without GPS data): "
                    + e, "warn"))
                gps_data = None
            try:
                self.gps_merge_into_plate_agg(plate_agg, gps_data)
            except Exception as _gex:
                self.after(0, lambda e=str(_gex)[:120]: self._vt_log(
                    "GPS merge error: " + e, "warn"))

            # ── Step 5: Populate UI ──────────────────────────────────────────
            self._vt_plate_data = plate_agg
            self.after(0, lambda: self._vt_populate(plate_agg, df, dt_end))

        except Exception as e:
            err = str(e)[:200]
            self.after(0, lambda: self._vt_log(
                "Vehicle Tracker error: " + err, "err"))
        finally:
            self.after(0, lambda: self.vt_progress.stop())

    def _vt_populate(self, data, df, dt_end):
        """Fill the main tree with per-plate summary (runs on UI thread)."""
        def fmt(sec):
            h, r = divmod(int(sec), 3600)
            m = r // 60
            return str(h) + "h " + str(m).zfill(2) + "m"

        self.vt_tree.delete(*self.vt_tree.get_children())

        if not data:
            self.vt_tree.insert(
                "", "end",
                text="-- No vehicle data for this range --",
                values=("", "", "", "", "", "", "", "", "", "", "",
                        "", "", "", ""),
                tags=("normal",))
            for k in self.vt_stat_vars:
                self.vt_stat_vars[k].set("0")
            self._vt_log("No data to display.", "warn")
            return

        rows = sorted(data.items(),
                      key=lambda kv: kv[1]["cal_util"])

        tot_w = sum(v["work_s"] for _, v in rows)
        tot_i = sum(v["idle_s"] for _, v in rows)
        # Avg utilization uses Calendar basis (work vs date-range hours)
        # since that's the honest fleet metric — not "work vs tracked time".
        n_plates = len(rows)
        cal_utils = [v["cal_util"] for _, v in rows]
        avg_util = (
            round(sum(cal_utils) / n_plates)
            if n_plates else 0)

        for plate, v in rows:
            cu = v["cal_util"]
            du = v["dispatch_util"]
            fuel_only = v.get("fuel_only", False)
            ghost     = v.get("ghost", False)
            mismatch  = v.get("mismatch", False)

            # Status precedence: ghost > fuel_only > mismatch > util-based
            if ghost:
                tag, status = "ghost", "Ghost activity"
            elif fuel_only:
                tag, status = "fuel_only", "Fuel only"
            elif mismatch:
                tag, status = "mismatch", "Mismatch"
            elif cu >= 50:
                tag, status = "good", "Good"
            elif cu >= 25:
                tag, status = "warn", "Moderate"
            elif cu > 0:
                tag, status = "danger", "Low"
            else:
                tag, status = "normal", "No data"

            refills_disp = fuel_format_refill_count(
                v.get("fuel_refill_count", 0))
            month_disp = fuel_format_month_total(
                v.get("fuel_month_litres", 0),
                v.get("fuel_month_sar", 0))
            gps_work_disp = gps_format_working(
                v.get("gps_working_s", 0))
            disc_disp = gps_format_discrepancy(
                v.get("discrepancy_s", 0))

            self.vt_tree.insert(
                "", "end", text=plate,
                values=(v.get("v_type", "—") or "—",
                        str(v["n_closed"]),
                        str(v["n_open"]),
                        str(v["n_nodata"]),
                        fmt(v["work_s"]),
                        fmt(v["idle_s"]),
                        str(cu) + "%",
                        str(du) + "%",
                        "{:,.0f}".format(v.get("total_amt", 0) or 0),
                        "{:,.0f}".format(v.get("total_km", 0) or 0),
                        refills_disp,
                        month_disp,
                        gps_work_disp,
                        disc_disp,
                        status),
                tags=(tag,))

        self.vt_stat_vars["plates"].set(str(len(rows)))
        self.vt_stat_vars["work"].set(fmt(tot_w))
        self.vt_stat_vars["idle"].set(fmt(tot_i))
        self.vt_stat_vars["util"].set(str(avg_util) + "%")
        self._vt_log(
            "Done — " + str(len(rows)) + " vehicles analysed for " +
            df + " → " + dt_end, "ok")

    def _vt_drilldown(self, event=None):
        """Double-click handler on vt_tree → per-plate trip + idle detail."""
        if not self._vt_plate_data:
            return
        sel = self.vt_tree.selection()
        if not sel:
            return
        plate = self.vt_tree.item(sel[0], "text") or ""
        if plate.startswith("--") or not plate:
            return
        data = self._vt_plate_data.get(plate)
        if not data:
            return
        self._vt_drilldown_popup(plate, data)

    def _vt_drilldown_popup(self, plate, data):
        """Per-plate trip + idle gap breakdown Toplevel."""
        def fmt(sec):
            h, r = divmod(int(sec), 3600)
            m, s = divmod(r, 60)
            if h:
                return str(h) + "h " + str(m).zfill(2) + "m"
            return str(m) + "m " + str(s).zfill(2) + "s"

        def fmt_dt(d):
            try:
                return d.strftime("%Y-%m-%d %H:%M")
            except Exception:
                return str(d)

        win = tk.Toplevel(self)
        win.title("Vehicle Detail — " + plate)
        win.configure(bg=C["page"])
        win.geometry("1280x760")
        win.transient(self)

        # ── Header ───────────────────────────────────────────────────────────
        hdr = tk.Frame(win, bg=C["white"])
        hdr.pack(fill="x", padx=14, pady=(14, 8))
        tk.Label(hdr, text=plate,
                 font=("Segoe UI", 14, "bold"),
                 bg=C["white"], fg=C["text"]).pack(
            anchor="w", padx=14, pady=(12, 0))
        tk.Label(hdr,
                 text=str(data["n_closed"]) + " closed · " +
                      str(data["n_open"]) + " open · " +
                      str(data["n_nodata"]) + " no-data · " +
                      "Working " + fmt(data["work_s"]) + " · " +
                      "Idle " + fmt(data["idle_s"]) + " · " +
                      "Cal " + str(data["cal_util"]) + "% / " +
                      "Disp " + str(data["dispatch_util"]) + "%",
                 font=("Segoe UI", 9),
                 bg=C["white"], fg=C["text3"]).pack(
            anchor="w", padx=14, pady=(0, 10))

        # ── GPS Cross-Check section (Arabitra) ───────────────────────────────
        try:
            self.gps_render_drilldown_section(win, data, C)
        except Exception as _gex:
            self._vt_log("GPS drilldown render failed: " + str(_gex)[:120], "warn")

        # ── Closed trips table ───────────────────────────────────────────────
        closed = [t for t in data["trips"] if t["kind"] == "closed"]
        opens  = [t for t in data["trips"] if t["kind"] == "open"]
        nodata = [t for t in data["trips"] if t["kind"] == "nodata"]

        tk.Label(win,
                 text="Closed trips (" + str(len(closed)) + ")",
                 font=("Segoe UI", 9, "bold"),
                 bg=C["page"], fg=C["green"]).pack(
            anchor="w", padx=18, pady=(4, 4))

        c_o = tk.Frame(win, bg=C["border"], padx=1, pady=1)
        c_o.pack(fill="x", padx=14, pady=(0, 6))
        c_tree = ttk.Treeview(
            c_o, style="TD.Treeview",
            columns=("start", "end", "dur",
                     "pickup", "dest", "ttype",
                     "amt", "km", "via"),
            show="tree headings", height=5)
        c_tree.heading("#0",     text="Trip ID")
        c_tree.heading("start",  text="Depart for Pickup")
        c_tree.heading("end",    text="Closed At")
        c_tree.heading("dur",    text="Working Time")
        c_tree.heading("pickup", text="Pickup")
        c_tree.heading("dest",   text="Destination")
        c_tree.heading("ttype",  text="Trip Type")
        c_tree.heading("amt",    text="Amount")
        c_tree.heading("km",     text="KM")
        c_tree.heading("via",    text="End Status")
        c_tree.column("#0",     width=85,  anchor="w",      stretch=False)
        c_tree.column("start",  width=130, anchor="center", stretch=False)
        c_tree.column("end",    width=130, anchor="center", stretch=False)
        c_tree.column("dur",    width=90,  anchor="center", stretch=False)
        c_tree.column("pickup", width=130, anchor="w",      stretch=True)
        c_tree.column("dest",   width=130, anchor="w",      stretch=True)
        c_tree.column("ttype",  width=80,  anchor="center", stretch=False)
        c_tree.column("amt",    width=75,  anchor="e",      stretch=False)
        c_tree.column("km",     width=65,  anchor="e",      stretch=False)
        c_tree.column("via",    width=130, anchor="w",      stretch=False)
        c_tree.tag_configure("row",
                              background=C["input"], foreground=C["text2"])
        c_tree.pack(fill="x")
        if not closed:
            c_tree.insert("", "end", text="—",
                          values=("—", "—", "—",
                                  "—", "—", "—",
                                  "—", "—",
                                  "No closed trips"),
                          tags=("row",))
        else:
            for t in closed:
                c_tree.insert(
                    "", "end",
                    text=t["tid"],
                    values=(fmt_dt(t["start"]),
                            fmt_dt(t["end"]),
                            fmt(t["work"]),
                            (t.get("pickup", "") or "—")[:35],
                            (t.get("destination", "") or "—")[:35],
                            (t.get("trip_type", "") or "—")[:20],
                            (t.get("total_amount", "") or "—"),
                            (t.get("total_km", "") or "—"),
                            t["last_status"]),
                    tags=("row",))

        # ── Open trips table ─────────────────────────────────────────────────
        tk.Label(win,
                 text="Open / in-progress trips (" +
                      str(len(opens)) + ")",
                 font=("Segoe UI", 9, "bold"),
                 bg=C["page"], fg=C["amber"]).pack(
            anchor="w", padx=18, pady=(6, 4))

        o_o = tk.Frame(win, bg=C["border"], padx=1, pady=1)
        o_o.pack(fill="x", padx=14, pady=(0, 6))
        o_tree = ttk.Treeview(
            o_o, style="TD.Treeview",
            columns=("start", "last_t", "dur",
                     "pickup", "dest", "ttype",
                     "amt", "km", "last_s"),
            show="tree headings", height=5)
        o_tree.heading("#0",     text="Trip ID")
        o_tree.heading("start",  text="Depart for Pickup")
        o_tree.heading("last_t", text="Last Log At")
        o_tree.heading("dur",    text="Tracked So Far")
        o_tree.heading("pickup", text="Pickup")
        o_tree.heading("dest",   text="Destination")
        o_tree.heading("ttype",  text="Trip Type")
        o_tree.heading("amt",    text="Amount")
        o_tree.heading("km",     text="KM")
        o_tree.heading("last_s", text="Last Status")
        o_tree.column("#0",     width=85,  anchor="w",      stretch=False)
        o_tree.column("start",  width=130, anchor="center", stretch=False)
        o_tree.column("last_t", width=130, anchor="center", stretch=False)
        o_tree.column("dur",    width=90,  anchor="center", stretch=False)
        o_tree.column("pickup", width=130, anchor="w",      stretch=True)
        o_tree.column("dest",   width=130, anchor="w",      stretch=True)
        o_tree.column("ttype",  width=80,  anchor="center", stretch=False)
        o_tree.column("amt",    width=75,  anchor="e",      stretch=False)
        o_tree.column("km",     width=65,  anchor="e",      stretch=False)
        o_tree.column("last_s", width=130, anchor="w",      stretch=False)
        o_tree.tag_configure("row",
                              background=C["amber_l"],
                              foreground=C["amber"])
        o_tree.pack(fill="x")
        if not opens:
            o_tree.insert("", "end", text="—",
                          values=("—", "—", "—",
                                  "—", "—", "—",
                                  "—", "—",
                                  "No open trips"),
                          tags=("row",))
        else:
            for t in opens:
                o_tree.insert(
                    "", "end",
                    text=t["tid"],
                    values=(fmt_dt(t["start"]) if t["start"] else "—",
                            fmt_dt(t["end"])   if t["end"]   else "—",
                            fmt(t["work"]) if t["work"] else "—",
                            (t.get("pickup", "") or "—")[:35],
                            (t.get("destination", "") or "—")[:35],
                            (t.get("trip_type", "") or "—")[:20],
                            (t.get("total_amount", "") or "—"),
                            (t.get("total_km", "") or "—"),
                            t["last_status"] or "—"),
                    tags=("row",))

        # ── No-data trips table ──────────────────────────────────────────────
        if nodata:
            tk.Label(win,
                     text="No driver-app data (" +
                          str(len(nodata)) + ")",
                     font=("Segoe UI", 9, "bold"),
                     bg=C["page"], fg=C["red"]).pack(
                anchor="w", padx=18, pady=(6, 4))
            nd_o = tk.Frame(win, bg=C["border"], padx=1, pady=1)
            nd_o.pack(fill="x", padx=14, pady=(0, 6))
            nd_tree = ttk.Treeview(
                nd_o, style="TD.Treeview",
                columns=("note",),
                show="tree headings", height=3)
            nd_tree.heading("#0",   text="Trip ID")
            nd_tree.heading("note", text="Note")
            nd_tree.column("#0",   width=120, anchor="w", stretch=False)
            nd_tree.column("note", width=500, anchor="w", stretch=True)
            nd_tree.tag_configure("row",
                                   background=C["red_l"],
                                   foreground=C["red"])
            nd_tree.pack(fill="x")
            for t in nodata:
                nd_tree.insert(
                    "", "end",
                    text=t["tid"],
                    values=("No driver-app status logged",),
                    tags=("row",))

        # ── Idle gaps table ──────────────────────────────────────────────────
        tk.Label(win,
                 text="Idle gaps between closed trips "
                      "(≥4h red, ≥1h amber)",
                 font=("Segoe UI", 9, "bold"),
                 bg=C["page"], fg=C["text2"]).pack(
            anchor="w", padx=18, pady=(8, 4))

        g_o = tk.Frame(win, bg=C["border"], padx=1, pady=1)
        g_o.pack(fill="x", padx=14, pady=(0, 8))
        g_tree = ttk.Treeview(
            g_o, style="TD.Treeview",
            columns=("from", "to", "dur"),
            show="headings", height=5)
        g_tree.heading("from", text="Idle From")
        g_tree.heading("to",   text="Idle To")
        g_tree.heading("dur",  text="Duration")
        g_tree.column("from", width=220, anchor="center", stretch=False)
        g_tree.column("to",   width=220, anchor="center", stretch=False)
        g_tree.column("dur",  width=140, anchor="center", stretch=False)
        g_tree.tag_configure("red",
                              background=C["red_l"], foreground=C["red"])
        g_tree.tag_configure("amber",
                              background=C["amber_l"], foreground=C["amber"])
        g_tree.tag_configure("norm",
                              background=C["input"], foreground=C["text2"])
        g_tree.pack(fill="x")

        if not data["idle_segs"]:
            g_tree.insert(
                "", "end",
                values=("—", "—", "No idle gaps between closed trips"),
                tags=("norm",))
        else:
            for s in data["idle_segs"]:
                secs = s["secs"]
                if secs >= 14400:
                    tag = "red"
                elif secs >= 3600:
                    tag = "amber"
                else:
                    tag = "norm"
                g_tree.insert(
                    "", "end",
                    values=(fmt_dt(s["from"]),
                            fmt_dt(s["to"]),
                            fmt(secs)),
                    tags=(tag,))

        tk.Button(win, text="Close", font=("Segoe UI", 9),
                  bg=C["input"], fg=C["text2"], bd=0,
                  padx=24, pady=6,
                  activebackground=C["border"],
                  command=win.destroy).pack(pady=(4, 12))

    def _sales_stop(self):
        self._sales_running = False
        self.sales_progress.stop()
        self.sales_status_lbl.config(text="● Stopped", fg=C["amber"])
        self._sales_log("Stop requested.", "warn")

    def _sales_send_otp(self):
        """
        Step 1 — GET the real login page, parse form action + CSRF token,
        then POST credentials. The server sends OTP to user's registered phone.
        """
        from urllib.parse import urlparse as _urlp, urljoin as _urljoin
        from html.parser import HTMLParser as _HP

        base_url = self.sales_url_var.get().strip().rstrip("/")
        parsed   = _urlp(base_url)
        base     = parsed.scheme + "://" + parsed.netloc
        username = self.sales_user_var.get().strip()
        password = self.sales_pass_var.get().strip()

        if not username or not password:
            self._sales_log("Enter username and password first.", "warn"); return

        self._sales_log("Connecting to " + base + "...", "info")
        self.after(0, lambda: self.sales_session_badge.config(
            text="Connecting...", bg=C["amber_l"], fg=C["amber"]))

        def _r():
            try:
                session = requests.Session()
                session.headers.update({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/122.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                })
                self._sales_session_obj = session
                self._sales_base_url    = base

                # ── 1. GET the login page ─────────────────────────────────────
                login_url = None
                for path in ["/backend/login", "/login", "/auth/login", "/signin"]:
                    try:
                        r = session.get(base + path, timeout=15, allow_redirects=True)
                        if r.status_code == 200 and ("password" in r.text.lower()
                                                      or "login" in r.text.lower()):
                            login_url = r.url
                            self._sales_log("Login page found: " + r.url, "info")
                            break
                    except: continue

                if not login_url:
                    # Try root — it may redirect to login itself
                    try:
                        r = session.get(base + "/", timeout=15, allow_redirects=True)
                        login_url = r.url
                        self._sales_log("Using root redirect: " + r.url, "info")
                    except Exception as e:
                        self._sales_log("Cannot reach " + base + " — " + str(e), "err")
                        self.after(0, lambda: self.sales_session_badge.config(
                            text="Unreachable", bg=C["red_l"], fg=C["red"]))
                        return

                # ── 2. Parse form action + CSRF from login page HTML ──────────
                class _FormParser(_HP):
                    def __init__(self):
                        super().__init__()
                        self.form_action = None
                        self.csrf        = ""
                        self.fields      = {}
                        self._in_form    = False
                    def handle_starttag(self, tag, attrs):
                        a = dict(attrs)
                        if tag == "form":
                            self._in_form   = True
                            self.form_action = a.get("action","")
                        if tag == "input" and self._in_form:
                            name = a.get("name","")
                            val  = a.get("value","")
                            if name:
                                self.fields[name] = val
                            if name.lower() in ("_token","csrf_token","csrf",
                                                "authenticity_token","csrfmiddlewaretoken"):
                                self.csrf = val
                    def handle_endtag(self, tag):
                        if tag == "form": self._in_form = False

                fp = _FormParser()
                fp.feed(r.text)
                self._sales_csrf   = fp.csrf
                self._sales_fields = fp.fields   # all hidden inputs
                self._sales_login_url = login_url

                # Also look for CSRF in meta tags
                import re as _re
                meta_csrf = _re.search(
                    r'<meta[^>]+name=.csrf-token.[^>]+content=.([^>]+)',
                    r.text, _re.I)
                if meta_csrf and not self._sales_csrf:
                    self._sales_csrf = meta_csrf.group(1)

                self._sales_log("CSRF token: " + (self._sales_csrf[:12] + "..." if self._sales_csrf else "none found"), "info")

                # ── 3. Build POST payload ────────────────────────────────────
                # Start with all hidden fields from the form, then override
                payload = dict(fp.fields)
                # Map common field name patterns
                for k in list(payload.keys()):
                    if "email" in k.lower() or "user" in k.lower() or "login" in k.lower():
                        payload[k] = username
                    if "pass" in k.lower():
                        payload[k] = password

                # Also set the obvious names directly
                for fname in ["email","username","user","login"]:
                    payload[fname] = username
                for pname in ["password","pass","passwd"]:
                    payload[pname] = password
                if self._sales_csrf:
                    for cname in ["_token","csrf_token","csrf","authenticity_token","csrfmiddlewaretoken"]:
                        payload[cname] = self._sales_csrf

                # Determine POST URL
                action = fp.form_action or ""
                if action:
                    post_url = _urljoin(login_url, action)
                else:
                    post_url = login_url   # POST to same page

                self._sales_log("POSTing credentials to: " + post_url, "info")

                # ── 4. POST credentials ──────────────────────────────────────
                session.headers.update({
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": login_url,
                    "Origin":  base,
                    "Accept":  "text/html,application/xhtml+xml,*/*",
                })
                resp = session.post(post_url, data=payload,
                                    timeout=20, allow_redirects=True)
                self._sales_log("POST → HTTP " + str(resp.status_code) + " | " + resp.url, "info")
                self._sales_last_resp = resp   # save for OTP step

                # ── 5. Also try JSON API as fallback ─────────────────────────
                if resp.status_code not in (200, 201, 302) or                    "error" in resp.text.lower()[:200]:
                    self._sales_log("Form POST may have failed — trying JSON API...", "warn")
                    session.headers.update({
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    })
                    for api_path in ["/api/auth/login", "/api/login",
                                     "/backend/api/login", "/api/users/login"]:
                        try:
                            ar = session.post(base + api_path,
                                json={"email": username, "password": password},
                                timeout=12, allow_redirects=False)
                            if ar.status_code in (200, 201):
                                resp = ar
                                self._sales_last_resp = ar
                                self._sales_log("JSON API: " + api_path +
                                               " → " + str(ar.status_code), "ok")
                                break
                        except: continue

                # ── 6. Detect OTP page / success ─────────────────────────────
                resp_text_lower = resp.text.lower()
                otp_page = ("otp" in resp_text_lower or
                            "one-time" in resp_text_lower or
                            "verification code" in resp_text_lower or
                            "verify" in resp.url.lower() or
                            "otp" in resp.url.lower())

                # Parse OTP form action for next step
                ofp = _FormParser()
                ofp.feed(resp.text)
                self._sales_otp_form_action = ofp.form_action or ""
                self._sales_otp_fields      = ofp.fields
                otp_meta = _re.search(
                    r'<meta[^>]+name=.csrf-token.[^>]+content=.([^>]+)',
                    resp.text, _re.I)
                if otp_meta:
                    self._sales_csrf = otp_meta.group(1)
                elif ofp.csrf:
                    self._sales_csrf = ofp.csrf

                if otp_page:
                    self._sales_log("OTP page detected — check your phone for the code!", "ok")
                    self.after(0, lambda: self.sales_session_badge.config(
                        text="OTP sent — enter code", bg=C["amber_l"], fg=C["amber"]))
                    self.after(0, lambda: self.sales_otp_entry.focus_set())
                elif resp.status_code == 200 and ("dashboard" in resp.url.lower()
                        or "report" in resp.url.lower() or "backend" in resp.url.lower()):
                    # Already logged in (no OTP required for this session)
                    self._sales_session = session
                    self._sales_log("Logged in directly (no OTP needed this session).", "ok")
                    self.after(0, lambda: self.sales_session_badge.config(
                        text="Logged in", bg=C["green_l"], fg=C["green"]))
                else:
                    self._sales_log("Response received — HTTP " + str(resp.status_code) +
                                    " | If OTP was sent to your phone, enter it now.", "warn")
                    self._sales_log("Response URL: " + resp.url, "info")
                    self.after(0, lambda: self.sales_session_badge.config(
                        text="Enter OTP if received", bg=C["amber_l"], fg=C["amber"]))
                    self.after(0, lambda: self.sales_otp_entry.focus_set())

            except Exception as e:
                self._sales_log("Send OTP error: " + str(e), "err")
                self.after(0, lambda: self.sales_session_badge.config(
                    text="Error — check URL", bg=C["red_l"], fg=C["red"]))

        threading.Thread(target=_r, daemon=True).start()

    def _sales_verify_otp(self):
        """
        Step 2 — POST the OTP code using the real form action from the OTP page,
        carrying the existing session cookies. Then verify dashboard access.
        """
        from urllib.parse import urljoin as _urljoin
        from html.parser import HTMLParser as _HP
        import re as _re

        otp_code = self.sales_otp_var.get().strip()
        if not otp_code:
            self._sales_log("Enter the OTP code first.", "warn"); return
        if not hasattr(self, "_sales_session_obj") or not self._sales_session_obj:
            self._sales_log("Click Send OTP first.", "warn"); return

        base     = getattr(self, "_sales_base_url",    "https://c.zeetacargo.com")
        session  = self._sales_session_obj
        last_url = getattr(self, "_sales_last_resp", None)
        last_url = last_url.url if last_url else base
        username = self.sales_user_var.get().strip()

        self._sales_log("Submitting OTP: " + otp_code, "info")
        self.after(0, lambda: self.sales_session_badge.config(
            text="Verifying OTP...", bg=C["amber_l"], fg=C["amber"]))

        def _r():
            try:
                # ── Build OTP payload from parsed OTP page fields ─────────────
                payload = dict(getattr(self, "_sales_otp_fields", {}))
                # Set CSRF
                csrf = getattr(self, "_sales_csrf", "")
                if csrf:
                    for cname in ["_token","csrf_token","csrf",
                                  "authenticity_token","csrfmiddlewaretoken"]:
                        payload[cname] = csrf

                # Set OTP value against all common field names
                for fname in ["otp","code","token","verification_code","otp_code",
                              "one_time_password","verificationCode"]:
                    payload[fname] = otp_code

                # Determine POST URL from parsed OTP form action
                form_action = getattr(self, "_sales_otp_form_action", "")
                if form_action:
                    post_url = _urljoin(last_url, form_action)
                else:
                    # Guess common OTP submit paths
                    for path in ["/otp/verify", "/verify-otp", "/backend/otp/verify",
                                  "/auth/otp", "/api/auth/verify-otp", "/api/verify-otp"]:
                        post_url = base + path
                        break   # use first guess; we'll try all if needed

                self._sales_log("OTP POST → " + post_url, "info")

                session.headers.update({
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer":      last_url,
                    "Origin":       base,
                    "Accept":       "text/html,application/xhtml+xml,*/*",
                })
                resp = session.post(post_url, data=payload,
                                    timeout=20, allow_redirects=True)
                self._sales_log("OTP response → HTTP " + str(resp.status_code) +
                                " | " + resp.url, "info")

                # If form POST fails, try JSON API endpoints
                if resp.status_code not in (200, 201, 302) or                    "invalid" in resp.text.lower()[:300] or                    "error" in resp.text.lower()[:300]:
                    self._sales_log("Form OTP failed — trying JSON API endpoints...", "warn")
                    session.headers.update({
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    })
                    for api_path in ["/api/auth/verify-otp", "/api/verify-otp",
                                     "/api/auth/otp", "/api/otp/verify",
                                     "/backend/api/auth/otp"]:
                        try:
                            ar = session.post(base + api_path,
                                json={"otp": otp_code, "email": username, "code": otp_code},
                                timeout=12)
                            self._sales_log("  " + api_path + " → " + str(ar.status_code), "info")
                            if ar.status_code in (200, 201):
                                resp = ar; break
                        except: continue

                # ── Test dashboard access ─────────────────────────────────────
                sales_url = self.sales_url_var.get().strip()
                session.headers.update({"Accept": "text/html,*/*"})
                test = session.get(sales_url, timeout=25, allow_redirects=True)
                self._sales_log("Dashboard test → HTTP " + str(test.status_code) +
                                " | " + test.url, "info")

                # Success if we reach the report page (not redirected back to login/otp)
                not_login = all(kw not in test.url.lower()
                                for kw in ["login","signin","otp","verify","auth"])
                has_table = "tbody" in test.text.lower() or "table" in test.text.lower()

                if test.status_code == 200 and not_login:
                    self._sales_session = session
                    self._sales_log("OTP verified — session active!", "ok")
                    if has_table:
                        self._sales_log("Dashboard table detected. Click Load Data.", "ok")
                    self.after(0, lambda: self.sales_session_badge.config(
                        text="Logged in", bg=C["green_l"], fg=C["green"]))
                    self.after(0, lambda: self.sales_otp_hint.config(
                        text="Session active. Click Load Data to fetch the report.",
                        fg=C["green"]))
                else:
                    self._sales_log("Dashboard not reached after OTP. "
                                    "HTTP " + str(test.status_code) + " | " + test.url, "err")
                    self._sales_log("Try again — OTP may be expired or incorrect.", "warn")
                    self.after(0, lambda: self.sales_session_badge.config(
                        text="OTP failed — retry", bg=C["red_l"], fg=C["red"]))

            except Exception as e:
                self._sales_log("OTP verify error: " + str(e), "err")
                self.after(0, lambda: self.sales_session_badge.config(
                    text="Error", bg=C["red_l"], fg=C["red"]))

        threading.Thread(target=_r, daemon=True).start()

    def _sales_load_data(self):
        """Fetch and parse the Zeeta sales report page using the saved session."""
        if not self._sales_session:
            self._sales_log("Not logged in. Enter credentials, click Send OTP, then Verify OTP first.", "warn")
            return
        if not sales_is_working_day(date.today()):
            self._sales_log("Today is a day off — no reminders should be sent.", "warn")
        self._sales_running = True
        self.sales_progress.start(10)
        self.sales_status_lbl.config(text="● Loading...", fg=C["amber"])
        threading.Thread(target=self._sales_fetch_and_parse, daemon=True).start()

    def _sales_fetch_and_parse(self):
        """HTTP fetch of Zeeta report — parse coordinator/client gap data."""
        try:
            self._sales_log("Fetching " + ZEETA_SALES_URL + "...", "info")
            r = self._sales_session.get(ZEETA_SALES_URL, timeout=30, allow_redirects=True)
            self._sales_log("HTTP " + str(r.status_code) + " | " + r.url, "info")

            # Guard: if redirected to login
            if "login" in r.url.lower() or "otp" in r.url.lower() or "signin" in r.url.lower():
                self._sales_log("Redirected to login — session expired. Log in again with OTP.", "err")
                self.after(0, lambda: self.sales_session_badge.config(
                    text="Session expired", bg=C["red_l"], fg=C["red"]))
                return

            # Parse HTML table with BeautifulSoup if available, else regex fallback
            html = r.text
            try:
                from html.parser import HTMLParser

                class _TblParser(HTMLParser):
                    def __init__(self):
                        super().__init__()
                        self.in_tbody = False
                        self.in_tr    = False
                        self.in_td    = False
                        self.rows     = []
                        self._cur_row = []
                        self._cur_cell= ""
                        self._cur_attrs = {}

                    def handle_starttag(self, tag, attrs):
                        a = dict(attrs)
                        if tag == "tbody": self.in_tbody = True
                        elif tag == "tr" and self.in_tbody:
                            self.in_tr = True; self._cur_row = []
                        elif tag == "td" and self.in_tr:
                            self.in_td = True; self._cur_cell = ""
                            self._cur_attrs = a
                        elif tag == "a" and self.in_td:
                            if "data-phone" in a:
                                self._cur_cell += "|PHONE:" + a.get("data-phone","") + \
                                                  "|NAME:"  + a.get("data-name","")  + "|"

                    def handle_endtag(self, tag):
                        if tag == "tbody": self.in_tbody = False
                        elif tag == "tr" and self.in_tbody:
                            self.rows.append(self._cur_row); self.in_tr = False
                        elif tag == "td" and self.in_tr:
                            self._cur_row.append(self._cur_cell.strip()); self.in_td = False

                    def handle_data(self, data):
                        if self.in_td:
                            self._cur_cell += data

                parser = _TblParser()
                parser.feed(html)
                rows = parser.rows
                self._sales_log("Parsed " + str(len(rows)) + " table rows", "info")

            except Exception as pe:
                self._sales_log("Parse error: " + str(pe), "err"); return

            all_clients = []
            coord_info  = {}

            for cols in rows:
                if len(cols) < 26: continue
                client = cols[1].strip()

                def _extract(cell):
                    import re
                    pm = re.search(r"\|PHONE:([^|]+)\|", cell)
                    nm = re.search(r"\|NAME:([^|]+)\|",  cell)
                    return (nm.group(1).strip() if nm else "",
                            pm.group(1).strip() if pm else "")

                lv_name, lv_phone = _extract(cols[2])
                hv_name, hv_phone = _extract(cols[3])

                def _num(s):
                    import re
                    t = re.sub(r"[^\d.]", "", s)
                    try: return float(t)
                    except: return 0.0

                lv_sup = _num(cols[21]); hv_sup = _num(cols[22])
                lv_act = _num(cols[24]); hv_act = _num(cols[25])

                if lv_name and lv_phone: coord_info[lv_name] = lv_phone
                if hv_name and hv_phone: coord_info[hv_name] = hv_phone

                if lv_name and lv_sup > 0 and lv_act < lv_sup:
                    g = lv_sup - lv_act
                    all_clients.append({"key": lv_name+"|"+client+"|LV",
                                        "coordinator": lv_name, "client": client,
                                        "service": "LV", "suppose": lv_sup,
                                        "actual": lv_act, "gap": g,
                                        "pct": round(g/lv_sup*100, 1)})
                if hv_name and hv_sup > 0 and hv_act < hv_sup:
                    g = hv_sup - hv_act
                    all_clients.append({"key": hv_name+"|"+client+"|HV",
                                        "coordinator": hv_name, "client": client,
                                        "service": "HV", "suppose": hv_sup,
                                        "actual": hv_act, "gap": g,
                                        "pct": round(g/hv_sup*100, 1)})

            if not all_clients and not coord_info:
                self._sales_log("No coordinator data found in page. "
                                "Check session or table column indices.", "warn")
            else:
                self._sales_log("Found " + str(len(all_clients)) + " client gaps across "
                                + str(len(coord_info)) + " coordinator(s)", "ok")

            # Zero-actual (100% gap) first, then descending % behind
            all_clients.sort(key=lambda x: (0 if x["actual"] == 0 else 1, -x["pct"]))
            self._sales_active_data = all_clients
            self._sales_coord_info  = coord_info

            # ── All below forecast = active list ──────────────────────────────
            active = all_clients   # every client below forecast, no tracker needed
            zero_count = sum(1 for c in active if c["actual"] == 0)
            self._sales_set_stat("All Below Forecast", len(active))
            self._sales_set_stat("Zero Sales", zero_count)
            self._sales_set_stat("Met Forecast", 0)
            # Log zero-sales clients prominently
            for c in active:
                if c["actual"] == 0:
                    self._sales_log("ZERO SALES: " + c["client"] + " [" + c["coordinator"] +
                                    "] — " + format(int(c["gap"]), ",") + " SAR", "warn")
            self._sales_log("Total below forecast: " + str(len(active)) +
                            " · Zero sales: " + str(zero_count), "info")
            # reminder_map not used anymore — kept as empty for msg compat
            self._sales_reminder_map = {c["key"]: 1 for c in active}

            # ── Populate gap treeview — coord sections, zero first then % desc ──
            import collections as _col2
            # Group active by coordinator, preserving sort order
            coord_groups = _col2.OrderedDict()
            for c in active:
                coord_groups.setdefault(c["coordinator"], []).append(c)

            def _fill_tree():
                self.sales_tree.delete(*self.sales_tree.get_children())
                for coord_name, clients in coord_groups.items():
                    # Sort: zero actual first, then descending pct
                    sorted_c = sorted(clients, key=lambda x: (0 if x["actual"] == 0 else 1, -x["pct"]))
                    # Coordinator header row
                    self.sales_tree.insert("", "end",
                        values=(coord_name + " — " + str(len(sorted_c)) + " client(s) below forecast",
                                "", "", "", "", "", "", ""),
                        tags=("coord_hdr",))
                    for c in sorted_c:
                        flag = "ZERO SALES" if c["actual"] == 0 else ""
                        tag  = "zero" if c["actual"] == 0 else                                "high" if c["pct"] >= 50 else "normal"
                        self.sales_tree.insert("", "end", values=(
                            c["coordinator"], c["client"], c["service"],
                            format(int(c["suppose"]), ","),
                            format(int(c["actual"]),  ","),
                            format(int(c["gap"]),     ","),
                            str(c["pct"]) + "%",
                            flag,
                        ), tags=(tag,))
            self.after(0, _fill_tree)

            # ── Populate coordinator listbox ───────────────────────────────────
            import collections as _col
            coord_counts = _col.Counter(c["coordinator"] for c in active)

            def _fill_lb():
                self.sales_coord_lb.delete(0, "end")
                if not coord_counts:
                    self.sales_coord_lb.insert("end", "-- No active coordinators --")
                    return
                for name, cnt in sorted(coord_counts.items(), key=lambda x: -x[1]):
                    phone = coord_info.get(name, "no phone")
                    self.sales_coord_lb.insert("end",
                        name + "  [" + str(cnt) + " client(s)]  (" + phone + ")")
                self.sales_coord_lb.select_set(0, "end")
                self._sales_on_coord_select()
            self.after(0, _fill_lb)
            self.after(0, lambda: self.sales_status_lbl.config(
                text="● Data loaded — " + str(len(active)) + " active", fg=C["green"]))

        except Exception as e:
            self._sales_log("Load error: " + str(e), "err")
            self.after(0, lambda: self.sales_status_lbl.config(
                text="● Load error", fg=C["red"]))
        finally:
            self._sales_running = False
            self.after(0, self.sales_progress.stop)

    def _sales_run(self):
        """Send WhatsApp reminders to selected coordinators via Green API."""
        if not self._sales_session:
            self._sales_log("No active session. Verify session cookie first.", "warn"); return
        if not self._sales_active_data:
            self._sales_log("No data loaded. Click Load Data first.", "warn"); return
        if self._sales_running:
            self._sales_log("Already running.", "warn"); return

        selected_coords = self._sales_get_selected_coords()
        if not selected_coords:
            self._sales_log("No coordinators selected. Select at least one.", "warn"); return
        self._sales_log("Selected coordinators: " + ", ".join(sorted(selected_coords)), "info")

        if not sales_is_working_day(date.today()):
            self._sales_log("Today is a day off — are you sure? Proceeding anyway.", "warn")

        # Build cfg from saved config (so Green API instance/token are always present)
        cfg = load_config()
        _ui = {
            "green_instance": self.f_ginstance.get().strip(),
            "green_token":    self.f_gtoken.get().strip(),
        }
        for k, v in _ui.items():
            if v: cfg[k] = v

        if not cfg.get("green_instance") or not cfg.get("green_token"):
            self._sales_log("Green API not configured. Set instance + token in Settings.", "err"); return

        custom_note = self.sales_msg_text.get("1.0", "end-1c").strip()
        active      = self._sales_active_data   # all clients below forecast
        coord_info  = self._sales_coord_info

        # Look up selected template (None if invalid → legacy format used)
        tpl_name = self.sales_tpl_var.get() if hasattr(
            self, "sales_tpl_var") else ""
        templates = getattr(self, "_sales_templates", None) or {}
        selected_tpl = templates.get(tpl_name)
        if selected_tpl:
            self._sales_log(
                "Using template: " + tpl_name, "info")
        else:
            self._sales_log(
                "No template selected — using legacy format", "warn")

        self._sales_running = True
        self.sales_progress.start(10)
        self.sales_status_lbl.config(text="● Sending...", fg=C["amber"])

        def _r():
            try:
                import collections as _col
                coord_clients = _col.defaultdict(list)
                for c in active:
                    if c["coordinator"] in selected_coords:
                        coord_clients[c["coordinator"]].append(c)

                self._sales_log("Sending to " + str(len(coord_clients)) +
                                " coordinator(s) via Green API...", "info")
                sent = fail = skip = 0

                for coord_name, clients in sorted(coord_clients.items()):
                    if not self._sales_running: break
                    # Sort: zero-actual first, then pct desc
                    clients = sorted(clients, key=lambda c: (0 if c["actual"] == 0 else 1, -c["pct"]))
                    phone = coord_info.get(coord_name, "")
                    if not phone:
                        self._sales_log("No phone for " + coord_name + " — skipping", "warn")
                        skip += 1; continue

                    msg = sales_build_msg(coord_name, clients,
                                          self._sales_reminder_map, custom_note,
                                          template=selected_tpl)
                    self._sales_log("-- " + coord_name + " (" + phone + ") --", "info")
                    try:
                        send_whatsapp_green(cfg, phone, msg, None, self._sales_log)
                        sent += 1
                        # Passive tracker: record every (coord, client, service)
                        # included in this send. Does NOT affect behavior — just
                        # an external-consumable log.
                        try:
                            for _c in clients:
                                _sales_tracker_record(
                                    coord_name,
                                    _c.get("client", ""),
                                    _c.get("service", ""))
                        except Exception as _te:
                            self._sales_log(
                                "Tracker write failed (non-fatal): "
                                + str(_te)[:80], "warn")
                    except Exception as e:
                        self._sales_log("ERROR: " + str(e), "err")
                        fail += 1
                    time.sleep(2)

                self._sales_set_stat("Sent", sent)
                self._sales_log(
                    "Done  Sent:" + str(sent) + "  Skip:" + str(skip) + "  Fail:" + str(fail), "ok")
                self.after(0, lambda: self.sales_status_lbl.config(
                    text="● Done  Sent:" + str(sent), fg=C["green"]))

            except Exception as e:
                self._sales_log("Run error: " + str(e), "err")
                self.after(0, lambda: self.sales_status_lbl.config(
                    text="● Error", fg=C["red"]))
            finally:
                self._sales_running = False
                self.after(0, self.sales_progress.stop)

        threading.Thread(target=_r, daemon=True).start()



    # ── Sales Reminder — Template picker helpers ──────────────────────────────

    def _sales_on_template_change(self, event=None):
        """Called when the dropdown selection changes — persist to config."""
        name = self.sales_tpl_var.get()
        cfg = load_config()
        cfg["sales_template_selected"] = name
        save_config(cfg)
        self._sales_log("Template changed to: " + name, "info")

    def _sales_preview_template(self):
        """Render selected template with sample data and show in a popup."""
        name = self.sales_tpl_var.get()
        tpl = (self._sales_templates or {}).get(name)
        if not tpl:
            self._sales_log("No template selected.", "warn")
            return

        # Use real coordinator data if loaded, else sample
        sample_name = "Coordinator"
        sample_clients = []
        rmap = {}
        if self._sales_active_data:
            from collections import defaultdict as _dd
            by_coord = _dd(list)
            for c in self._sales_active_data:
                by_coord[c["coordinator"]].append(c)
            if by_coord:
                sample_name = next(iter(by_coord.keys()))
                sample_clients = by_coord[sample_name][:4]
                rmap = self._sales_reminder_map or {}
        if not sample_clients:
            sample_clients = [
                {"client": "Sample Client A", "service": "Mobilization",
                 "suppose": 45000, "actual": 0, "gap": 45000,
                 "pct": 100, "key": "sample_a"},
                {"client": "Sample Client B", "service": "Delivery",
                 "suppose": 30000, "actual": 8000, "gap": 22000,
                 "pct": 73, "key": "sample_b"},
            ]
            rmap = {"sample_a": 1, "sample_b": 2}

        custom_note = self.sales_msg_text.get("1.0", "end-1c").strip()
        msg = sales_build_msg(
            sample_name, sample_clients, rmap,
            custom_note, template=tpl)

        # Show in a Toplevel
        win = tk.Toplevel(self)
        win.title("Preview — " + name)
        win.configure(bg=C["page"])
        win.geometry("620x520")
        win.transient(self)

        tk.Label(win,
                 text="Preview for: " + sample_name +
                      "    (" + name + ")",
                 font=("Segoe UI", 10, "bold"),
                 bg=C["page"], fg=C["text"]).pack(
            anchor="w", padx=14, pady=(12, 4))
        tk.Label(win,
                 text="This is the message that would be sent. "
                      "Uses real data if Load Data has been run.",
                 font=("Segoe UI", 8),
                 bg=C["page"], fg=C["text3"]).pack(
            anchor="w", padx=14, pady=(0, 8))

        frame = tk.Frame(win, bg=C["border"], padx=1, pady=1)
        frame.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        txt = scrolledtext.ScrolledText(
            frame, font=("Consolas", 9),
            bg=C["white"], fg=C["text2"], bd=0,
            padx=12, pady=8, wrap="word")
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", msg)
        txt.config(state="disabled")

        tk.Button(win, text="Close", font=("Segoe UI", 9),
                  bg=C["input"], fg=C["text2"], bd=0,
                  padx=24, pady=6,
                  command=win.destroy).pack(pady=(0, 12))

    def _sales_edit_templates(self):
        """Open the template editor dialog."""
        from tkinter import messagebox
        win = tk.Toplevel(self)
        win.title("Edit message templates")
        win.configure(bg=C["page"])
        win.geometry("820x560")
        win.transient(self)

        current = {k: dict(v) for k, v in
                   (self._sales_templates or {}).items()}
        if not current:
            current = {k: dict(v) for k, v in
                       DEFAULT_SALES_TEMPLATES.items()}

        self._te_current = current
        self._te_selected = None

        # ── Header ──
        hdr = tk.Frame(win, bg=C["page"])
        hdr.pack(fill="x", padx=14, pady=(14, 6))
        tk.Label(hdr, text="Edit message templates",
                 font=("Segoe UI", 11, "bold"),
                 bg=C["page"], fg=C["text"]).pack(side="left")
        tk.Label(hdr, text="Saved to config.json",
                 font=("Segoe UI", 8),
                 bg=C["page"], fg=C["text4"]).pack(side="right")

        # ── Main body: two-column layout ──
        body = tk.Frame(win, bg=C["page"])
        body.pack(fill="both", expand=True, padx=14, pady=(0, 6))
        body.columnconfigure(0, weight=0, minsize=180)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # Left: template list
        left_o = tk.Frame(body, bg=C["border"], padx=1, pady=1)
        left_o.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left = tk.Frame(left_o, bg=C["input"])
        left.pack(fill="both", expand=True)
        tk.Label(left, text="TEMPLATES",
                 font=("Segoe UI", 8, "bold"),
                 bg=C["input"], fg=C["text3"]).pack(
            anchor="w", padx=10, pady=(8, 4))

        lb = tk.Listbox(left, font=("Segoe UI", 9),
                        bg=C["white"], fg=C["text2"],
                        selectbackground=C["accent_l"],
                        selectforeground=C["accent"],
                        bd=0, relief="flat",
                        highlightthickness=0,
                        activestyle="none")
        lb.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self._te_listbox = lb

        tk.Button(left, text="+ New template",
                  command=lambda: self._te_add_new(win),
                  font=("Segoe UI", 8),
                  bg=C["white"], fg=C["accent"], bd=0,
                  padx=8, pady=4).pack(fill="x", padx=6, pady=(0, 8))

        # Right: editing panel
        right = tk.Frame(body, bg=C["page"])
        right.grid(row=0, column=1, sticky="nsew")

        tk.Label(right, text="NAME",
                 font=("Segoe UI", 8, "bold"),
                 bg=C["page"], fg=C["text3"]).pack(
            anchor="w", pady=(0, 2))
        self._te_name_var = tk.StringVar()
        name_entry = tk.Entry(right, textvariable=self._te_name_var,
                               font=("Segoe UI", 10),
                               bg=C["input"], fg=C["text2"], bd=0,
                               highlightthickness=1,
                               highlightbackground=C["border"])
        name_entry.pack(fill="x", ipady=4, pady=(0, 8))

        tk.Label(right, text="SUBJECT (used in header)",
                 font=("Segoe UI", 8, "bold"),
                 bg=C["page"], fg=C["text3"]).pack(
            anchor="w", pady=(0, 2))
        self._te_subj_var = tk.StringVar()
        subj_entry = tk.Entry(right, textvariable=self._te_subj_var,
                               font=("Segoe UI", 10),
                               bg=C["input"], fg=C["text2"], bd=0,
                               highlightthickness=1,
                               highlightbackground=C["border"])
        subj_entry.pack(fill="x", ipady=4, pady=(0, 8))

        tk.Label(right, text="MESSAGE BODY",
                 font=("Segoe UI", 8, "bold"),
                 bg=C["page"], fg=C["text3"]).pack(
            anchor="w", pady=(0, 2))
        tk.Label(right,
                 text="Placeholders: {name}  {date}  {subject}  "
                      "{client_list}  {note}",
                 font=("Segoe UI", 8),
                 bg=C["page"], fg=C["text4"]).pack(
            anchor="w", pady=(0, 4))

        body_outer = tk.Frame(right, bg=C["border"], padx=1, pady=1)
        body_outer.pack(fill="both", expand=True)
        self._te_body_text = scrolledtext.ScrolledText(
            body_outer, font=("Consolas", 9),
            bg=C["input"], fg=C["text2"],
            insertbackground=C["accent"],
            bd=0, padx=10, pady=8, wrap="word")
        self._te_body_text.pack(fill="both", expand=True)

        # ── Bottom buttons ──
        btns = tk.Frame(win, bg=C["page"])
        btns.pack(fill="x", padx=14, pady=(6, 12))

        tk.Button(btns, text="Reset this template",
                  command=lambda: self._te_reset(win),
                  font=("Segoe UI", 9),
                  bg=C["input"], fg=C["text3"], bd=0,
                  padx=10, pady=4).pack(side="left")

        tk.Button(btns, text="Delete",
                  command=lambda: self._te_delete(win),
                  font=("Segoe UI", 9),
                  bg=C["red_l"], fg=C["red"], bd=0,
                  padx=10, pady=4).pack(side="left", padx=(6, 0))

        tk.Button(btns, text="Save all",
                  command=lambda: self._te_save(win),
                  font=("Segoe UI", 9, "bold"),
                  bg=C["accent_l"], fg=C["accent"], bd=0,
                  padx=16, pady=4).pack(side="right")
        def _try_close():
            from tkinter import messagebox
            self._te_flush_edits()
            # Compare current edits against persisted state
            persisted = (self._sales_templates or
                         dict(DEFAULT_SALES_TEMPLATES))
            if self._te_current != persisted:
                ans = messagebox.askyesnocancel(
                    "Unsaved changes",
                    "You have unsaved template changes.\n\n"
                    "Save before closing?",
                    parent=win)
                if ans is None:   # Cancel — stay in dialog
                    return
                if ans:           # Yes — save and close
                    self._te_save(win)
                    return
                # No — discard and close
            win.destroy()

        tk.Button(btns, text="Cancel",
                  command=_try_close,
                  font=("Segoe UI", 9),
                  bg=C["input"], fg=C["text2"], bd=0,
                  padx=14, pady=4).pack(side="right", padx=(0, 6))
        # Also intercept window close (X button)
        win.protocol("WM_DELETE_WINDOW", _try_close)

        lb.bind("<<ListboxSelect>>",
                lambda e: self._te_load_selection(win))

        self._te_refresh_list(keep_selection=False)
        if lb.size():
            lb.selection_set(0)
            self._te_load_selection(win)

    def _te_refresh_list(self, keep_selection=True):
        """Refresh the listbox from self._te_current."""
        prev = None
        if keep_selection:
            idxs = self._te_listbox.curselection()
            if idxs:
                prev = self._te_listbox.get(idxs[0])
        self._te_listbox.delete(0, "end")
        for k in self._te_current.keys():
            self._te_listbox.insert("end", k)
        if prev:
            for i, k in enumerate(self._te_current.keys()):
                if k == prev:
                    self._te_listbox.selection_set(i)
                    break

    def _te_load_selection(self, win):
        """Load the selected template into the edit fields."""
        idxs = self._te_listbox.curselection()
        if not idxs:
            return
        # Persist unsaved edits on previous selection first
        self._te_flush_edits()
        name = self._te_listbox.get(idxs[0])
        self._te_selected = name
        tpl = self._te_current.get(name, {})
        self._te_name_var.set(name)
        self._te_subj_var.set(tpl.get("subject", ""))
        self._te_body_text.delete("1.0", "end")
        self._te_body_text.insert("1.0", tpl.get("body", ""))

    def _te_flush_edits(self):
        """Write current edit fields back to _te_current (before switching)."""
        if not self._te_selected:
            return
        new_name = self._te_name_var.get().strip()
        new_subj = self._te_subj_var.get()
        new_body = self._te_body_text.get("1.0", "end-1c")
        if not new_name:
            return
        # If name changed, rename the key (preserving order)
        if new_name != self._te_selected:
            new_current = {}
            for k, v in self._te_current.items():
                if k == self._te_selected:
                    new_current[new_name] = {
                        "subject": new_subj, "body": new_body}
                else:
                    new_current[k] = v
            self._te_current = new_current
            self._te_selected = new_name
        else:
            self._te_current[new_name] = {
                "subject": new_subj, "body": new_body}

    def _te_add_new(self, win):
        """Add a blank template."""
        # Save any pending edits to the currently-selected template first
        self._te_flush_edits()

        # Generate a unique name
        base = "New template"
        name = base
        n = 1
        while name in self._te_current:
            n += 1
            name = base + " " + str(n)

        # Default content
        default_subject = "Reminder"
        default_body = (
            "{subject} — {date}\n"
            "\n"
            "Hi {name},\n"
            "\n"
            "{client_list}\n"
            "{note}\n"
            "\n"
            "— {name}"
        )
        self._te_current[name] = {
            "subject": default_subject,
            "body":    default_body,
        }

        # Refresh listbox first
        self._te_refresh_list(keep_selection=False)

        # Find new entry index and select it
        new_idx = None
        for i, k in enumerate(self._te_current.keys()):
            if k == name:
                new_idx = i
                break
        if new_idx is not None:
            self._te_listbox.selection_clear(0, "end")
            self._te_listbox.selection_set(new_idx)
            self._te_listbox.see(new_idx)
            self._te_listbox.activate(new_idx)

        # Directly populate edit fields — don't rely on _te_load_selection
        # because the listbox-select event ordering is not deterministic.
        self._te_selected = name
        self._te_name_var.set(name)
        self._te_subj_var.set(default_subject)
        self._te_body_text.delete("1.0", "end")
        self._te_body_text.insert("1.0", default_body)

        self._sales_log(
            "Added template '" + name +
            "' — click 'Save all' to persist.",
            "info")

    def _te_reset(self, win):
        """Reset the selected template to factory default (if name matches)."""
        from tkinter import messagebox
        if not self._te_selected:
            return
        default = DEFAULT_SALES_TEMPLATES.get(self._te_selected)
        if not default:
            messagebox.showinfo(
                "Reset template",
                "No factory default exists for this template name.\n"
                "(Reset only works for built-in names)", parent=win)
            return
        self._te_current[self._te_selected] = dict(default)
        self._te_subj_var.set(default["subject"])
        self._te_body_text.delete("1.0", "end")
        self._te_body_text.insert("1.0", default["body"])

    def _te_delete(self, win):
        """Delete the selected template."""
        from tkinter import messagebox
        if not self._te_selected:
            return
        if len(self._te_current) <= 1:
            messagebox.showinfo(
                "Delete template",
                "Can't delete the last remaining template.", parent=win)
            return
        if not messagebox.askyesno(
            "Delete template",
            "Delete '" + self._te_selected + "'?", parent=win):
            return
        self._te_current.pop(self._te_selected, None)
        self._te_selected = None
        self._te_refresh_list(keep_selection=False)
        if self._te_listbox.size():
            self._te_listbox.selection_set(0)
            self._te_load_selection(win)

    def _te_save(self, win):
        """Persist edits to config.json and update the main dropdown."""
        from tkinter import messagebox
        self._te_flush_edits()
        if not self._te_current:
            messagebox.showwarning(
                "Save templates",
                "At least one template must exist.", parent=win)
            return
        # Validate each has a non-empty body
        for k, v in self._te_current.items():
            if not v.get("body", "").strip():
                messagebox.showwarning(
                    "Save templates",
                    "Template '" + k + "' has an empty body.", parent=win)
                return
        # Persist
        self._sales_templates = dict(self._te_current)
        cfg = load_config()
        cfg["sales_templates"] = self._sales_templates
        # Preserve selected if still exists, else pick first
        cur_sel = self.sales_tpl_var.get() if hasattr(
            self, "sales_tpl_var") else ""
        if cur_sel not in self._sales_templates:
            cur_sel = next(iter(self._sales_templates.keys()))
        cfg["sales_template_selected"] = cur_sel
        save_config(cfg)
        # Refresh main dropdown
        self.sales_tpl_dropdown.config(
            values=list(self._sales_templates.keys()))
        self.sales_tpl_var.set(cur_sel)
        self._sales_log(
            "Saved " + str(len(self._sales_templates)) + " template(s).",
            "ok")
        win.destroy()



    # ── Sales AI Intelligence methods ─────────────────────────────────────────

    def _sales_ai_stop(self):
        self._sales_ai_cancel.set()
        self.sales_ai_status.config(text="Stopping...", fg=C["amber"])

    def _sales_ai_write(self, text, tag="body"):
        def _w():
            self.sales_ai_box.config(state="normal")
            self.sales_ai_box.insert("end", text, tag)
            self.sales_ai_box.see("end")
            self.sales_ai_box.config(state="disabled")
        self.after(0, _w)

    def _sales_ai_clear(self):
        self.sales_ai_box.config(state="normal")
        self.sales_ai_box.delete("1.0", "end")
        self.sales_ai_box.config(state="disabled")

    def _sales_ai_run(self):
        if not HAS_ANTHROPIC:
            self._sales_log("Claude SDK not installed. Run: pip install anthropic", "err")
            return
        api_key = load_config().get("anthropic_key", "").strip()
        if not api_key:
            self._sales_log("Anthropic API key not set — go to POS Sync > Settings and enter it.", "err")
            return
        if not self._sales_active_data:
            self._sales_log("Load Data first before running AI analysis.", "warn")
            return

        mode = self.sales_ai_mode.get()
        lang = self.sales_ai_lang.get()
        reply_text = self.sales_ai_reply_var.get().strip()

        if mode == "Reply Analyser" and not reply_text:
            self._sales_log("Paste the coordinator reply text in the Reply Analyser field first.", "warn")
            return

        selected_coords = self._sales_get_selected_coords()
        self._sales_ai_cancel.clear()
        self._sales_ai_clear()
        self.sales_progress.start(10)
        self.sales_ai_status.config(text="Running: " + mode + "...", fg=C["amber"])
        threading.Thread(
            target=self._sales_ai_call,
            args=(api_key, mode, lang, reply_text, selected_coords),
            daemon=True
        ).start()

    def _sales_ai_call(self, api_key, mode, lang, reply_text, selected_coords=None):
        """Core Claude API call — streams response into the AI box.
        If selected_coords provided, only analyse those coordinators.
        """
        try:
            import collections as _col
            all_data = self._sales_active_data
            coords   = self._sales_coord_info
            # Filter to selected coordinators if any are chosen
            if selected_coords:
                data = [c for c in all_data if c["coordinator"] in selected_coords]
                if not data:
                    self._sales_ai_write("No data for selected coordinators.\n", "warn")
                    self.after(0, self.sales_progress.stop)
                    return
                self._sales_ai_write(
                    "Analysing " + str(len(selected_coords)) + " selected coordinator(s): "
                    + ", ".join(sorted(selected_coords)) + "\n\n", "muted")
            else:
                data = all_data
                self._sales_ai_write("Analysing ALL coordinators.\n\n", "muted")

            # ── Build data summary ────────────────────────────────────────────
            coord_groups = _col.defaultdict(list)
            for c in data:
                coord_groups[c["coordinator"]].append(c)

            lines = [
                "ZEETA CARGO SALES GAP REPORT",
                "Date: " + date.today().strftime("%d %B %Y"),
                "Total coordinators: " + str(len(coord_groups)),
                "Total clients below forecast: " + str(len(data)),
                "Zero-sales clients: " + str(sum(1 for c in data if c["actual"] == 0)),
                "",
            ]
            for coord, clients in sorted(coord_groups.items()):
                sc = sorted(clients, key=lambda x: (0 if x["actual"] == 0 else 1, -x["pct"]))
                lines.append("COORDINATOR: " + coord)
                for c in sc:
                    z = " [ZERO SALES]" if c["actual"] == 0 else ""
                    lines.append(
                        "  * " + c["client"] + " (" + c["service"] + ")" + z +
                        " Forecast=" + format(int(c["suppose"]), ",") + " SAR" +
                        " Actual=" + format(int(c["actual"]), ",") + " SAR" +
                        " Gap=" + format(int(c["gap"]), ",") + " SAR (" + str(c["pct"]) + "% behind)"
                    )
                lines.append("")
            data_summary = "\n".join(lines)

            lang_instr = {
                "English": "Respond entirely in English.",
                "Urdu":    "Respond entirely in Urdu (Roman Urdu is acceptable).",
                "Arabic":  "Respond entirely in Arabic.",
            }.get(lang, "Respond in English.")

            # ── Build prompt per mode ─────────────────────────────────────────
            if mode == "Gap Analysis":
                prompt = (
                    "You are a senior sales operations analyst for Zeeta Cargo, "
                    "a freight and logistics company in Saudi Arabia operating LV and HV services.\n\n"
                    + data_summary + "\n\n"
                    + lang_instr + "\n\n"
                    "Provide a sharp actionable gap analysis with these sections:\n\n"
                    "OVERALL PICTURE\n"
                    "- Total SAR at risk, percentage of team with zero sales\n\n"
                    "CRITICAL - ZERO SALES COORDINATORS\n"
                    "- Name each coordinator with zero-sales clients, which clients, which service type\n"
                    "- Likely causes and suggested immediate action\n\n"
                    "HIGH RISK (over 50 percent behind)\n"
                    "- Who is most at risk of missing monthly target entirely\n"
                    "- Specific recommendations per coordinator\n\n"
                    "TOP 3 ACTIONS FOR TODAY\n"
                    "- Concrete specific steps management should take right now\n"
                    "- Who to call first and what to say\n\n"
                    "Keep it direct. No fluff. This is for an executive who reads fast."
                )

            elif mode == "Smart Messages":
                prompt = (
                    "You are drafting personalised WhatsApp reminder messages "
                    "for Zeeta Cargo sales coordinators. Each coordinator gets their own message.\n\n"
                    + data_summary + "\n\n"
                    + lang_instr + "\n\n"
                    "For EACH coordinator write a WhatsApp message that:\n"
                    "- Starts with their name and a direct statement about their numbers\n"
                    "- Lists ONLY their own clients in order: zero-sales first, then highest gap percent\n"
                    "- Uses firm but professional tone\n"
                    "- Includes one specific action instruction per client\n"
                    "- Ends with: Update me by 5 PM today\n"
                    "- Is concise, max 15 lines per coordinator\n\n"
                    "Format:\n"
                    "--- MESSAGE FOR [NAME] ---\n"
                    "[message]\n"
                    "--- END ---\n\n"
                    "Write all coordinator messages one after another."
                )

            elif mode == "Escalation Check":
                prompt = (
                    "You are a sales manager deciding which cases need escalation "
                    "to senior management at Zeeta Cargo.\n\n"
                    + data_summary + "\n\n"
                    + lang_instr + "\n\n"
                    "For each coordinator decide:\n\n"
                    "ESCALATE NOW - needs senior management attention today\n"
                    "Criteria: zero sales for a key client, pattern of missing, gap over 75 percent\n\n"
                    "WATCH CLOSELY - needs monitoring, not yet escalation\n"
                    "Criteria: first-time miss, small gap, improving trend possible\n\n"
                    "STANDARD FOLLOW-UP - normal reminder sufficient\n\n"
                    "For each escalation case write:\n"
                    "1. Why it needs escalation with specific numbers\n"
                    "2. Draft supervisor message (3-4 lines, WhatsApp format)\n"
                    "3. What information to gather before escalating\n\n"
                    "Be decisive. Give clear YES/NO escalation decisions."
                )

            elif mode == "Reply Analyser":
                prompt = (
                    "You are a sales manager at Zeeta Cargo analysing a coordinator reply "
                    "to a sales gap reminder.\n\n"
                    "The coordinator received a reminder about their clients being below forecast.\n"
                    "Their reply: \"" + reply_text + "\"\n\n"
                    + data_summary + "\n\n"
                    + lang_instr + "\n\n"
                    "Analyse this reply and provide:\n\n"
                    "CLASSIFICATION\n"
                    "Choose one: Committed to visit | Gave valid reason | Making excuses | "
                    "Asked for support | Already resolved | Unclear or evasive\n\n"
                    "WHAT THEY ARE SAYING\n"
                    "Plain English summary of their actual message\n\n"
                    "RECOMMENDED RESPONSE\n"
                    "Write the exact WhatsApp reply you should send back. "
                    "Firm, professional, 3-5 lines maximum.\n\n"
                    "FOLLOW-UP ACTION\n"
                    "What should you do next as a manager."
                )
            else:
                prompt = data_summary

            # ── Stream Claude response ────────────────────────────────────────
            client = _anthropic_sdk.Anthropic(api_key=api_key)

            sep    = "=" * 52
            header = (sep + "\n  CLAUDE AI -- " + mode.upper() + "\n"
                      "  " + date.today().strftime("%d %b %Y %H:%M")
                      + "  |  Lang: " + lang + "\n" + sep + "\n\n")
            self._sales_ai_write(header, "muted")

            with client.messages.stream(
                model="claude-sonnet-4-20250514",
                max_tokens=2500,
                messages=[{"role": "user", "content": prompt}]
            ) as stream:
                for token in stream.text_stream:
                    if self._sales_ai_cancel.is_set():
                        stream.close()
                        self._sales_ai_write("\n\n[Stopped by user]\n", "muted")
                        self.after(0, lambda: self.sales_ai_status.config(
                            text="Stopped", fg=C["amber"]))
                        return
                    # Section headings get purple colour
                    stripped = token.strip()
                    if stripped.startswith("---") or stripped.isupper():
                        self._sales_ai_write(token, "subheading")
                    elif stripped in ("OVERALL PICTURE", "CRITICAL", "HIGH RISK",
                                      "TOP 3 ACTIONS", "ESCALATE NOW", "WATCH CLOSELY",
                                      "STANDARD FOLLOW-UP", "CLASSIFICATION",
                                      "WHAT THEY ARE SAYING", "RECOMMENDED RESPONSE",
                                      "FOLLOW-UP ACTION"):
                        self._sales_ai_write(token, "heading")
                    else:
                        self._sales_ai_write(token, "body")

            self._sales_ai_write("\n\n[Analysis complete -- Claude Sonnet]\n", "muted")
            self.after(0, lambda: self.sales_ai_status.config(
                text="Done", fg=C["green"]))

        except Exception as e:
            self._sales_ai_write("\nClaude API error: " + str(e) + "\n", "urgent")
            self.after(0, lambda: self.sales_ai_status.config(
                text="Error", fg=C["red"]))
        finally:
            self.after(0, self.sales_progress.stop)

    def _on_close(self):
        self._stop(); self.destroy()

if __name__ == "__main__":
    App().mainloop()
