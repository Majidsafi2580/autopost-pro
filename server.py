import os
import json
import uuid
import logging
import threading
import traceback
from datetime import datetime, timezone
from flask import Flask, request, jsonify, redirect
import requests
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ──────────────────────────────────────────────
# ENV
# ──────────────────────────────────────────────
META_APP_ID = os.getenv("META_APP_ID", "")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
META_GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v25.0")
BASE_URL = os.getenv("BASE_URL", "")
META_REDIRECT_URI = os.getenv("META_REDIRECT_URI", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")
DATA_DIR = os.getenv("DATA_DIR", "data")

TELEGRAM_API = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN
GRAPH_BASE = "https://graph.facebook.com/" + META_GRAPH_VERSION

SCOPES = [
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
    "business_management",
]

# ──────────────────────────────────────────────
# FILE HELPERS
# ──────────────────────────────────────────────
def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)

def data_path(filename):
    return os.path.join(DATA_DIR, filename)

_file_locks = {}
_file_locks_lock = threading.Lock()

def get_file_lock(path):
    with _file_locks_lock:
        if path not in _file_locks:
            _file_locks[path] = threading.Lock()
        return _file_locks[path]

def read_json(filename, default=None):
    if default is None:
        default = {}
    path = data_path(filename)
    lock = get_file_lock(path)
    with lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

def write_json(filename, data):
    path = data_path(filename)
    lock = get_file_lock(path)
    with lock:
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception as e:
            logger.error("write_json error %s: %s", filename, e)

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def now_ts():
    return datetime.now(timezone.utc).timestamp()

# ──────────────────────────────────────────────
# TELEGRAM HELPERS
# ──────────────────────────────────────────────
def tg_send(chat_id, text, reply_markup=None, parse_mode="HTML"):
    url = TELEGRAM_API + "/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(url, json=payload, timeout=15)
        return r.json()
    except Exception as e:
        logger.error("tg_send error: %s", e)
        return {}

def tg_edit(chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
    url = TELEGRAM_API + "/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(url, json=payload, timeout=15)
        return r.json()
    except Exception as e:
        logger.error("tg_edit error: %s", e)
        return {}

def tg_answer_callback(callback_id, text=""):
    url = TELEGRAM_API + "/answerCallbackQuery"
    try:
        requests.post(url, json={"callback_query_id": callback_id, "text": text}, timeout=10)
    except Exception as e:
        logger.error("tg_answer_callback error: %s", e)

def tg_get_file(file_id):
    url = TELEGRAM_API + "/getFile"
    try:
        r = requests.get(url, params={"file_id": file_id}, timeout=10)
        data = r.json()
        if data.get("ok"):
            file_path = data["result"]["file_path"]
            return "https://api.telegram.org/file/bot" + TELEGRAM_BOT_TOKEN + "/" + file_path
        return None
    except Exception as e:
        logger.error("tg_get_file error: %s", e)
        return None

def main_keyboard():
    return {
        "keyboard": [
            [{"text": "🏠 الرئيسية"}, {"text": "📊 لوحة التحكم"}],
            [{"text": "➕ ربط Meta"}, {"text": "📄 حساباتي"}, {"text": "🔄 تحديث الحسابات"}],
            [{"text": "🎯 اختيار الصفحات"}, {"text": "🌐 اختيار المنصة"}, {"text": "🌍 اختيار التوقيت"}],
            [{"text": "📝 نشر نص"}, {"text": "🖼 نشر صورة"}, {"text": "🎬 نشر فيديو"}],
            [{"text": "⏰ جدولة منشور"}, {"text": "📋 المجدولات"}, {"text": "🗑 حذف مجدول"}],
            [{"text": "❌ إلغاء"}],
        ],
        "resize_keyboard": True,
    }

# ──────────────────────────────────────────────
# ACCOUNT HELPERS
# ──────────────────────────────────────────────
def get_account(telegram_id):
    accounts = read_json("accounts.json", {})
    return accounts.get(str(telegram_id))

def save_account(telegram_id, data):
    accounts = read_json("accounts.json", {})
    accounts[str(telegram_id)] = data
    write_json("accounts.json", accounts)

def get_user_settings(telegram_id):
    settings = read_json("user_settings.json", {})
    tid = str(telegram_id)
    if tid not in settings:
        settings[tid] = {
            "selected_pages": [],
            "platforms": ["facebook"],
            "timezone": "Africa/Algiers",
        }
    return settings.get(tid, {})

def save_user_settings(telegram_id, data):
    settings = read_json("user_settings.json", {})
    settings[str(telegram_id)] = data
    write_json("user_settings.json", settings)

def get_bot_state(telegram_id):
    states = read_json("bot_states.json", {})
    return states.get(str(telegram_id), {})

def save_bot_state(telegram_id, state):
    states = read_json("bot_states.json", {})
    states[str(telegram_id)] = state
    write_json("bot_states.json", states)

def clear_bot_state(telegram_id):
    states = read_json("bot_states.json", {})
    states.pop(str(telegram_id), None)
    write_json("bot_states.json", states)

# ──────────────────────────────────────────────
# DUPLICATE UPDATE PROTECTION
# ──────────────────────────────────────────────
def is_duplicate_update(update_id):
    processed = read_json("processed_updates.json", {"ids": [], "last_cleanup": 0})
    uid = str(update_id)
    if uid in processed.get("ids", []):
        return True
    ids = processed.get("ids", [])
    ids.append(uid)
    if len(ids) > 500:
        ids = ids[-300:]
    write_json("processed_updates.json", {"ids": ids, "last_cleanup": now_ts()})
    return False

# ──────────────────────────────────────────────
# META / GRAPH HELPERS
# ──────────────────────────────────────────────
def refresh_pages(telegram_id):
    account = get_account(telegram_id)
    if not account:
        return False, "لا يوجد حساب مربوط"
    token = account.get("user_access_token")
    if not token:
        return False, "لا يوجد token"
    try:
        r = requests.get(
            GRAPH_BASE + "/me/accounts",
            params={"access_token": token, "fields": "id,name,access_token,instagram_business_account"},
            timeout=15,
        )
        data = r.json()
        if "error" in data:
            return False, data["error"].get("message", "خطأ غير معروف")
        pages = data.get("data", [])
        account["pages"] = pages
        save_account(telegram_id, account)
        return True, pages
    except Exception as e:
        return False, str(e)

# ──────────────────────────────────────────────
# JOBS HELPERS
# ──────────────────────────────────────────────
def create_job(telegram_id, job_type, text, file_url, selected_pages, platforms):
    jobs = read_json("jobs.json", {"jobs": []})
    job = {
        "id": str(uuid.uuid4())[:8],
        "telegram_id": str(telegram_id),
        "type": job_type,
        "text": text,
        "file_url": file_url,
        "selected_pages": selected_pages,
        "platforms": platforms,
        "status": "pending",
        "current_index": 0,
        "results": [],
        "created_at": now_iso(),
        "processing_started_at": None,
    }
    jobs["jobs"].append(job)
    write_json("jobs.json", jobs)
    return job

def update_job(job_id, updates):
    jobs = read_json("jobs.json", {"jobs": []})
    for j in jobs["jobs"]:
        if j["id"] == job_id:
            j.update(updates)
            break
    write_json("jobs.json", jobs)

# ──────────────────────────────────────────────
# PUBLISHING HELPERS
# ──────────────────────────────────────────────
def publish_text_to_page(page, text):
    page_id = page["id"]
    page_token = page.get("access_token", "")
    try:
        r = requests.post(
            GRAPH_BASE + "/" + page_id + "/feed",
            data={"message": text, "published": "true", "access_token": page_token},
            timeout=20,
        )
        data = r.json()
        if "error" in data:
            return False, data["error"].get("message", "خطأ غير معروف"), None
        return True, "نجح", data.get("id")
    except Exception as e:
        return False, str(e), None

def publish_photo_to_page(page, image_url, caption):
    page_id = page["id"]
    page_token = page.get("access_token", "")
    try:
        r = requests.post(
            GRAPH_BASE + "/" + page_id + "/photos",
            data={"url": image_url, "caption": caption or "", "published": "true", "access_token": page_token},
            timeout=30,
        )
        data = r.json()
        if "error" in data:
            return False, data["error"].get("message", "خطأ غير معروف"), None
        return True, "نجح", data.get("id")
    except Exception as e:
        return False, str(e), None

def publish_video_to_page(page, video_url, description):
    page_id = page["id"]
    page_token = page.get("access_token", "")
    try:
        r = requests.post(
            GRAPH_BASE + "/" + page_id + "/videos",
            data={"file_url": video_url, "description": description or "", "published": "true", "access_token": page_token},
            timeout=60,
        )
        data = r.json()
        if "error" in data:
            msg = data["error"].get("message", "خطأ")
            if "url" in msg.lower() or "file" in msg.lower():
                return False, "Meta رفض رابط Telegram للفيديو. الحل: رفع الفيديو إلى Cloudinary أولاً.", None
            return False, msg, None
        return True, "نجح", data.get("id")
    except Exception as e:
        return False, str(e), None

def publish_photo_to_instagram(ig_id, page_token, image_url, caption):
    try:
        r1 = requests.post(
            GRAPH_BASE + "/" + ig_id + "/media",
            data={"image_url": image_url, "caption": caption or "", "access_token": page_token},
            timeout=30,
        )
        d1 = r1.json()
        if "error" in d1:
            return False, d1["error"].get("message", "خطأ"), None
        container_id = d1.get("id")
        if not container_id:
            return False, "لم يتم إنشاء container", None
        r2 = requests.post(
            GRAPH_BASE + "/" + ig_id + "/media_publish",
            data={"creation_id": container_id, "access_token": page_token},
            timeout=30,
        )
        d2 = r2.json()
        if "error" in d2:
            return False, d2["error"].get("message", "خطأ"), None
        return True, "نجح", d2.get("id")
    except Exception as e:
        return False, str(e), None

def publish_video_to_instagram(ig_id, page_token, video_url, caption):
    try:
        r1 = requests.post(
            GRAPH_BASE + "/" + ig_id + "/media",
            data={"media_type": "REELS", "video_url": video_url, "caption": caption or "", "access_token": page_token},
            timeout=60,
        )
        d1 = r1.json()
        if "error" in d1:
            return False, d1["error"].get("message", "خطأ"), None
        container_id = d1.get("id")
        if not container_id:
            return False, "لم يتم إنشاء container", None
        r2 = requests.post(
            GRAPH_BASE + "/" + ig_id + "/media_publish",
            data={"creation_id": container_id, "access_token": page_token},
            timeout=30,
        )
        d2 = r2.json()
        if "error" in d2:
            return False, d2["error"].get("message", "خطأ"), None
        return True, "نجح", d2.get("id")
    except Exception as e:
        return False, str(e), None

def build_publish_targets(account, selected_page_ids, platforms):
    """Returns list of (page, platform) tuples to publish to."""
    all_pages = account.get("pages", [])
    pages_map = {p["id"]: p for p in all_pages}
    targets = []
    for pid in selected_page_ids:
        page = pages_map.get(pid)
        if not page:
            continue
        for platform in platforms:
            if platform == "facebook":
                targets.append((page, "facebook"))
            elif platform == "instagram":
                ig = page.get("instagram_business_account")
                if ig and ig.get("id"):
                    targets.append((page, "instagram"))
                else:
                    targets.append((page, "instagram_missing"))
    return targets

def do_publish_targets(telegram_id, targets, job_type, text, file_url, inline_ok=True):
    """Publish immediately (used for text/photo with few targets). Returns results list."""
    results = []
    total = len(targets)
    tg_send(telegram_id, "\U0001f680 بدأ النشر...\n\U0001f4cc عدد الوجهات: " + str(total))

    for i, (page, platform) in enumerate(targets):
        page_name = page.get("name", page["id"])
        num = str(i + 1) + "/" + str(total)
        tg_send(telegram_id, "\u23f3 جاري النشر في الصفحة " + num + "\n\U0001f4c4 " + page_name + "\n\U0001f310 " + platform)

        success = False
        reason = ""
        post_id = None

        if platform == "instagram_missing":
            success = False
            reason = "Instagram غير مربوط بهذه الصفحة"
        elif platform == "facebook":
            if job_type == "text":
                success, reason, post_id = publish_text_to_page(page, text)
            elif job_type == "photo":
                success, reason, post_id = publish_photo_to_page(page, file_url, text)
            elif job_type == "video":
                success, reason, post_id = publish_video_to_page(page, file_url, text)
        elif platform == "instagram":
            ig = page.get("instagram_business_account", {})
            ig_id = ig.get("id") if ig else None
            page_token = page.get("access_token", "")
            if not ig_id:
                success = False
                reason = "Instagram غير مربوط"
            elif job_type == "text":
                success = False
                reason = "Instagram لا يدعم نص فقط"
            elif job_type == "photo":
                success, reason, post_id = publish_photo_to_instagram(ig_id, page_token, file_url, text)
            elif job_type == "video":
                success, reason, post_id = publish_video_to_instagram(ig_id, page_token, file_url, text)

        results.append({"page_id": page["id"], "page_name": page_name, "platform": platform, "success": success, "reason": reason, "post_id": post_id})

        if success:
            msg = "\u2705 تم النشر في الصفحة " + num + "\n\U0001f4c4 " + page_name + "\n\U0001f194 Post ID: " + str(post_id)
            tg_send(telegram_id, msg)
        else:
            msg = "\u274c فشل النشر في الصفحة " + num + "\n\U0001f4c4 " + page_name + "\nالسبب: " + reason
            tg_send(telegram_id, msg)

    ok = sum(1 for r in results if r["success"])
    fail = total - ok
    summary = "\U0001f3c1 انتهت عملية النشر\n\u2705 نجح: " + str(ok) + "\n\u274c فشل: " + str(fail)
    tg_send(telegram_id, summary)
    return results

# ──────────────────────────────────────────────
# TIMEZONE HELPERS
# ──────────────────────────────────────────────
TIMEZONES = [
    ("🇩🇿", "Africa/Algiers"),
    ("🇲🇦", "Africa/Casablanca"),
    ("🇹🇳", "Africa/Tunis"),
    ("🇪🇬", "Africa/Cairo"),
    ("🇸🇦", "Asia/Riyadh"),
    ("🇦🇪", "Asia/Dubai"),
    ("🇺🇸", "America/New_York"),
    ("🇺🇸", "America/Chicago"),
    ("🇺🇸", "America/Los_Angeles"),
]

def local_to_utc(local_str, tz_name):
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(tz_name)
        dt_local = datetime.strptime(local_str, "%Y-%m-%d %H:%M")
        dt_local = dt_local.replace(tzinfo=tz)
        dt_utc = dt_local.astimezone(timezone.utc)
        return dt_utc.isoformat()
    except Exception as e:
        logger.error("local_to_utc error: %s", e)
        return None

def utc_now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

# ──────────────────────────────────────────────
# HANDLERS
# ──────────────────────────────────────────────
def handle_start(chat_id):
    text = ("\U0001f916 مرحباً بك في <b>AutoPost Pro</b>!\n\n"
            "البوت الاحترافي للنشر على Facebook وInstagram عبر Telegram.\n\n"
            "ابدأ بـ ➕ ربط Meta لربط حسابك.")
    tg_send(chat_id, text, main_keyboard())

def handle_home(chat_id):
    tg_send(chat_id, "\U0001f3e0 القائمة الرئيسية", main_keyboard())

def handle_accounts_info(chat_id):
    account = get_account(chat_id)
    if not account:
        tg_send(chat_id, "\u274c لا يوجد حساب Meta مربوط.\nاستخدم ➕ ربط Meta.", main_keyboard())
        return
    settings = get_user_settings(chat_id)
    pages = account.get("pages", [])
    selected = settings.get("selected_pages", [])
    platforms = ", ".join(settings.get("platforms", ["facebook"]))
    tz = settings.get("timezone", "Africa/Algiers")
    meta_name = account.get("meta_user", {}).get("name", "غير معروف")

    lines = ["\u2705 Meta: " + meta_name, "\U0001f4c4 عدد الصفحات: " + str(len(pages)), "\U0001f310 المنصات: " + platforms, "\U0001f552 التوقيت: " + tz, "", "\U0001f4c4 الصفحات:"]
    for i, p in enumerate(pages):
        pid = p["id"]
        pname = p.get("name", pid)
        ig = p.get("instagram_business_account")
        ig_str = ("@" + str(ig.get("id", ""))) if ig else "غير مربوط"
        sel = "\u2705" if pid in selected else "\u2b1c"
        lines.append(sel + " " + str(i + 1) + ". " + pname + " | token: \u2705 | IG: " + ig_str)

    tg_send(chat_id, "\n".join(lines), main_keyboard())

def handle_refresh_accounts(chat_id):
    tg_send(chat_id, "\u23f3 جاري تحديث الصفحات...")
    ok, result = refresh_pages(chat_id)
    if ok:
        tg_send(chat_id, "\u2705 تم تحديث الصفحات. عدد الصفحات: " + str(len(result)), main_keyboard())
    else:
        tg_send(chat_id, "\u274c فشل التحديث: " + str(result), main_keyboard())

def handle_link_meta(chat_id):
    state = str(uuid.uuid4())[:16]
    states = read_json("oauth_states.json", {})
    states[state] = {"telegram_id": str(chat_id), "created_at": now_iso()}
    write_json("oauth_states.json", states)
    scope = "%2C".join(SCOPES)
    url = ("https://www.facebook.com/" + META_GRAPH_VERSION + "/dialog/oauth"
           "?client_id=" + META_APP_ID
           + "&redirect_uri=" + META_REDIRECT_URI
           + "&scope=" + scope
           + "&state=" + state
           + "&response_type=code")
    btn = {"inline_keyboard": [[{"text": "\U0001f517 ربط حساب Meta", "url": url}]]}
    tg_send(chat_id, "\U0001f517 اضغط الزر أدناه لربط حساب Meta:", btn)

def handle_select_pages(chat_id):
    account = get_account(chat_id)
    if not account:
        tg_send(chat_id, "\u274c لا يوجد حساب Meta مربوط.")
        return
    pages = account.get("pages", [])
    if not pages:
        tg_send(chat_id, "\u274c لا توجد صفحات. استخدم 🔄 تحديث الحسابات أولاً.")
        return
    settings = get_user_settings(chat_id)
    selected = settings.get("selected_pages", [])
    state = get_bot_state(chat_id)
    state["temp_selected_pages"] = list(selected)
    save_bot_state(chat_id, state)
    _send_page_selection(chat_id, pages, state["temp_selected_pages"])

def _send_page_selection(chat_id, pages, selected):
    buttons = []
    for p in pages:
        pid = p["id"]
        pname = p.get("name", pid)
        mark = "\u2705 " if pid in selected else "\u2b1c "
        buttons.append([{"text": mark + pname, "callback_data": "toggle_page:" + pid}])
    buttons.append([
        {"text": "\u2705 تحديد الكل", "callback_data": "pages_select_all"},
        {"text": "\u274c إلغاء الكل", "callback_data": "pages_deselect_all"},
    ])
    buttons.append([{"text": "\u27a1\ufe0f متابعة", "callback_data": "pages_confirm"}])
    tg_send(chat_id, "\U0001f3af اختر الصفحات للنشر:", {"inline_keyboard": buttons})

def handle_select_platform(chat_id):
    settings = get_user_settings(chat_id)
    current = settings.get("platforms", ["facebook"])
    _send_platform_selection(chat_id, current)

def _send_platform_selection(chat_id, current):
    fb_mark = "\u2705" if "facebook" in current else "\u2b1c"
    ig_mark = "\u2705" if "instagram" in current else "\u2b1c"
    both_mark = "\u2705" if "facebook" in current and "instagram" in current else "\u2b1c"
    buttons = [
        [{"text": fb_mark + " Facebook فقط", "callback_data": "platform:facebook"}],
        [{"text": ig_mark + " Instagram فقط", "callback_data": "platform:instagram"}],
        [{"text": both_mark + " Facebook + Instagram", "callback_data": "platform:both"}],
        [{"text": "\U0001f4be حفظ", "callback_data": "platform_save"}],
    ]
    tg_send(chat_id, "\U0001f310 اختر المنصة:", {"inline_keyboard": buttons})

def handle_select_timezone(chat_id):
    buttons = []
    for flag, tz in TIMEZONES:
        buttons.append([{"text": flag + " " + tz, "callback_data": "tz:" + tz}])
    tg_send(chat_id, "\U0001f30d اختر توقيتك:", {"inline_keyboard": buttons})

def handle_dashboard(chat_id):
    account = get_account(chat_id)
    settings = get_user_settings(chat_id)
    jobs_data = read_json("jobs.json", {"jobs": []})
    sched_data = read_json("scheduled_posts.json", {"posts": []})
    log_data = read_json("posts_log.json", {"logs": []})

    meta_status = "\u2705 مربوط" if account else "\u274c غير مربوط"
    pages_count = len(account.get("pages", [])) if account else 0
    sel_count = len(settings.get("selected_pages", []))
    platforms = ", ".join(settings.get("platforms", ["facebook"]))
    tz = settings.get("timezone", "Africa/Algiers")

    pending_jobs = sum(1 for j in jobs_data["jobs"] if j["status"] in ("pending", "processing", "partial"))
    pending_sched = sum(1 for p in sched_data.get("posts", []) if p["status"] == "pending")

    last_log = None
    for entry in reversed(log_data.get("logs", [])):
        last_log = entry
        break

    last_status = "—"
    last_error = ""
    if last_log:
        last_status = "\u2705 ناجح" if last_log.get("success") else "\u274c فشل"
        last_error = last_log.get("reason", "") if not last_log.get("success") else ""

    lines = [
        "\U0001f4ca <b>AutoPost Pro</b>",
        "",
        "Meta: " + meta_status,
        "\U0001f4c4 عدد الصفحات: " + str(pages_count),
        "\U0001f3af الصفحات المختارة: " + str(sel_count),
        "\U0001f310 المنصات: " + platforms,
        "\U0001f552 التوقيت: " + tz,
        "\U0001f4e6 Jobs pending: " + str(pending_jobs),
        "\U0001f4c5 Scheduled pending: " + str(pending_sched),
        "\U0001f4dd آخر نشر: " + last_status,
    ]
    if last_error:
        lines.append("\u26a0\ufe0f آخر خطأ: " + last_error)

    tg_send(chat_id, "\n".join(lines), main_keyboard())

def handle_post_text_start(chat_id):
    account = get_account(chat_id)
    if not account:
        tg_send(chat_id, "\u274c لا يوجد حساب Meta مربوط.")
        return
    settings = get_user_settings(chat_id)
    if not settings.get("selected_pages"):
        tg_send(chat_id, "\u274c لم تختر صفحات. استخدم 🎯 اختيار الصفحات أولاً.")
        return
    save_bot_state(chat_id, {"step": "waiting_text_post"})
    tg_send(chat_id, "\U0001f4dd أرسل النص الذي تريد نشره:", {"keyboard": [[{"text": "❌ إلغاء"}]], "resize_keyboard": True})

def handle_post_photo_start(chat_id):
    account = get_account(chat_id)
    if not account:
        tg_send(chat_id, "\u274c لا يوجد حساب Meta مربوط.")
        return
    settings = get_user_settings(chat_id)
    if not settings.get("selected_pages"):
        tg_send(chat_id, "\u274c لم تختر صفحات.")
        return
    save_bot_state(chat_id, {"step": "waiting_photo_post"})
    tg_send(chat_id, "\U0001f5bc أرسل الصورة (مع caption اختياري):", {"keyboard": [[{"text": "❌ إلغاء"}]], "resize_keyboard": True})

def handle_post_video_start(chat_id):
    account = get_account(chat_id)
    if not account:
        tg_send(chat_id, "\u274c لا يوجد حساب Meta مربوط.")
        return
    settings = get_user_settings(chat_id)
    if not settings.get("selected_pages"):
        tg_send(chat_id, "\u274c لم تختر صفحات.")
        return
    save_bot_state(chat_id, {"step": "waiting_video_post"})
    tg_send(chat_id, "\U0001f3ac أرسل الفيديو (مع caption اختياري):", {"keyboard": [[{"text": "❌ إلغاء"}]], "resize_keyboard": True})

def handle_schedule_start(chat_id):
    account = get_account(chat_id)
    if not account:
        tg_send(chat_id, "\u274c لا يوجد حساب Meta مربوط.")
        return
    settings = get_user_settings(chat_id)
    if not settings.get("selected_pages"):
        tg_send(chat_id, "\u274c لم تختر صفحات.")
        return
    buttons = [
        [{"text": "\U0001f4dd جدولة نص", "callback_data": "sched_type:text"}],
        [{"text": "\U0001f5bc جدولة صورة", "callback_data": "sched_type:photo"}],
        [{"text": "\U0001f3ac جدولة فيديو", "callback_data": "sched_type:video"}],
    ]
    tg_send(chat_id, "\u23f0 اختر نوع المحتوى للجدولة:", {"inline_keyboard": buttons})

def handle_list_scheduled(chat_id):
    sched = read_json("scheduled_posts.json", {"posts": []})
    posts = [p for p in sched.get("posts", []) if p.get("telegram_id") == str(chat_id) and p["status"] in ("pending", "queued")]
    if not posts:
        tg_send(chat_id, "\U0001f4cb لا توجد منشورات مجدولة.")
        return
    lines = ["\U0001f4cb المنشورات المجدولة:\n"]
    for p in posts[-10:]:
        lines.append("\U0001f194 ID: " + p["id"])
        lines.append("\U0001f4c5 الوقت: " + p.get("scheduled_local", ""))
        lines.append("\U0001f4c4 النوع: " + p.get("type", ""))
        lines.append("\u23f3 الحالة: " + p.get("status", ""))
        lines.append("")
    tg_send(chat_id, "\n".join(lines))

def handle_delete_scheduled_start(chat_id):
    sched = read_json("scheduled_posts.json", {"posts": []})
    posts = [p for p in sched.get("posts", []) if p.get("telegram_id") == str(chat_id) and p["status"] in ("pending", "queued")]
    if not posts:
        tg_send(chat_id, "\U0001f4cb لا توجد منشورات قابلة للحذف.")
        return
    buttons = []
    for p in posts[-8:]:
        label = p["id"] + " | " + p.get("scheduled_local", "") + " | " + p.get("type", "")
        buttons.append([{"text": label, "callback_data": "delete_sched:" + p["id"]}])
    tg_send(chat_id, "\U0001f5d1 اختر منشوراً للحذف:", {"inline_keyboard": buttons})

def handle_cancel(chat_id):
    clear_bot_state(chat_id)
    tg_send(chat_id, "\u274c تم الإلغاء.", main_keyboard())

# ──────────────────────────────────────────────
# TEXT/PHOTO/VIDEO CONTENT RECEIVED
# ──────────────────────────────────────────────
def process_text_post(chat_id, text):
    if not text or not text.strip():
        tg_send(chat_id, "\u274c النص فارغ.")
        return
    account = get_account(chat_id)
    settings = get_user_settings(chat_id)
    selected = settings.get("selected_pages", [])
    platforms = settings.get("platforms", ["facebook"])
    pages = account.get("pages", [])
    pages_map = {p["id"]: p for p in pages}
    targets = build_publish_targets(account, selected, platforms)
    total = len(targets)

    preview = ("\U0001f4cc معاينة المنشور\n"
               "\U0001f4c4 النوع: نص\n"
               "\U0001f522 عدد الوجهات: " + str(total) + "\n"
               "\U0001f310 المنصات: " + ", ".join(platforms) + "\n"
               "\U0001f4dd النص: " + text[:100])
    buttons = [
        [{"text": "\u2705 نشر الآن", "callback_data": "confirm_publish:text"}],
        [{"text": "\u274c إلغاء", "callback_data": "cancel_publish"}],
    ]
    state = get_bot_state(chat_id)
    state["pending_post"] = {"type": "text", "text": text, "file_url": None, "targets": [{"page_id": t[0]["id"], "platform": t[1]} for t in targets], "total": total}
    save_bot_state(chat_id, state)
    tg_send(chat_id, preview, {"inline_keyboard": buttons})

def process_photo_post(chat_id, file_id, caption):
    file_url = tg_get_file(file_id)
    if not file_url:
        tg_send(chat_id, "\u274c فشل جلب الصورة.")
        return
    account = get_account(chat_id)
    settings = get_user_settings(chat_id)
    selected = settings.get("selected_pages", [])
    platforms = settings.get("platforms", ["facebook"])
    targets = build_publish_targets(account, selected, platforms)
    total = len(targets)

    preview = ("\U0001f4cc معاينة المنشور\n"
               "\U0001f4c4 النوع: صورة\n"
               "\U0001f522 عدد الوجهات: " + str(total) + "\n"
               "\U0001f310 المنصات: " + ", ".join(platforms) + "\n"
               "\U0001f4dd Caption: " + (caption or "")[:100])
    buttons = [
        [{"text": "\u2705 نشر الآن", "callback_data": "confirm_publish:photo"}],
        [{"text": "\u274c إلغاء", "callback_data": "cancel_publish"}],
    ]
    state = get_bot_state(chat_id)
    state["pending_post"] = {"type": "photo", "text": caption or "", "file_url": file_url, "targets": [{"page_id": t[0]["id"], "platform": t[1]} for t in targets], "total": total}
    save_bot_state(chat_id, state)
    tg_send(chat_id, preview, {"inline_keyboard": buttons})

def process_video_post(chat_id, file_id, caption):
    file_url = tg_get_file(file_id)
    if not file_url:
        tg_send(chat_id, "\u274c فشل جلب الفيديو.")
        return
    account = get_account(chat_id)
    settings = get_user_settings(chat_id)
    selected = settings.get("selected_pages", [])
    platforms = settings.get("platforms", ["facebook"])
    targets = build_publish_targets(account, selected, platforms)
    target_page_ids = list({t[0]["id"] for t in targets})
    job = create_job(chat_id, "video", caption or "", file_url, target_page_ids, platforms)
    msg = ("\U0001f4e6 تم إنشاء مهمة نشر الفيديو\n"
           "ID: " + job["id"] + "\n"
           "الوجهات: " + str(len(targets)) + "\n"
           "سيتم تنفيذها في الخلفية.")
    tg_send(chat_id, msg, main_keyboard())
    clear_bot_state(chat_id)

def execute_confirm_publish(chat_id, post_type):
    state = get_bot_state(chat_id)
    pending = state.get("pending_post")
    if not pending:
        tg_send(chat_id, "\u274c لا توجد بيانات نشر.")
        return
    account = get_account(chat_id)
    pages = account.get("pages", [])
    pages_map = {p["id"]: p for p in pages}
    targets = []
    for t in pending.get("targets", []):
        page = pages_map.get(t["page_id"])
        if page:
            targets.append((page, t["platform"]))
    clear_bot_state(chat_id)
    results = do_publish_targets(chat_id, targets, pending["type"], pending.get("text", ""), pending.get("file_url"), inline_ok=True)
    log_data = read_json("posts_log.json", {"logs": []})
    for r in results:
        log_data["logs"].append({"timestamp": now_iso(), "type": pending["type"], "page_id": r["page_id"], "platform": r["platform"], "success": r["success"], "reason": r.get("reason", ""), "post_id": r.get("post_id")})
    if len(log_data["logs"]) > 200:
        log_data["logs"] = log_data["logs"][-200:]
    write_json("posts_log.json", log_data)

# ──────────────────────────────────────────────
# SCHEDULE HANDLING
# ──────────────────────────────────────────────
def save_scheduled_post(telegram_id, post_type, text, file_url, selected_pages, platforms, tz, local_str, utc_str):
    sched = read_json("scheduled_posts.json", {"posts": []})
    post = {
        "id": str(uuid.uuid4())[:8],
        "telegram_id": str(telegram_id),
        "type": post_type,
        "text": text,
        "file_url": file_url,
        "selected_pages": selected_pages,
        "platforms": platforms,
        "timezone": tz,
        "scheduled_local": local_str,
        "scheduled_utc": utc_str,
        "status": "pending",
        "created_at": now_iso(),
        "results": [],
    }
    sched["posts"].append(post)
    write_json("scheduled_posts.json", sched)
    return post

# ──────────────────────────────────────────────
# CALLBACK QUERY HANDLER
# ──────────────────────────────────────────────
def handle_callback(callback_query):
    cid = callback_query["id"]
    chat_id = callback_query["from"]["id"]
    data = callback_query.get("data", "")
    message_id = callback_query.get("message", {}).get("message_id")
    tg_answer_callback(cid)

    if ADMIN_CHAT_ID and str(chat_id) != str(ADMIN_CHAT_ID):
        tg_send(chat_id, "\u274c هذا البوت خاص.")
        return

    state = get_bot_state(chat_id)
    account = get_account(chat_id)

    # PAGE SELECTION TOGGLES
    if data.startswith("toggle_page:"):
        pid = data.split(":", 1)[1]
        temp = state.get("temp_selected_pages", [])
        if pid in temp:
            temp.remove(pid)
        else:
            temp.append(pid)
        state["temp_selected_pages"] = temp
        save_bot_state(chat_id, state)
        if account:
            pages = account.get("pages", [])
            _send_page_selection(chat_id, pages, temp)
        return

    if data == "pages_select_all":
        if account:
            pages = account.get("pages", [])
            temp = [p["id"] for p in pages]
            state["temp_selected_pages"] = temp
            save_bot_state(chat_id, state)
            _send_page_selection(chat_id, pages, temp)
        return

    if data == "pages_deselect_all":
        state["temp_selected_pages"] = []
        save_bot_state(chat_id, state)
        if account:
            pages = account.get("pages", [])
            _send_page_selection(chat_id, pages, [])
        return

    if data == "pages_confirm":
        temp = state.get("temp_selected_pages", [])
        settings = get_user_settings(chat_id)
        settings["selected_pages"] = temp
        save_user_settings(chat_id, settings)
        state.pop("temp_selected_pages", None)
        save_bot_state(chat_id, state)
        tg_send(chat_id, "\u2705 تم حفظ " + str(len(temp)) + " صفحة.", main_keyboard())
        return

    # PLATFORM SELECTION
    if data.startswith("platform:"):
        val = data.split(":", 1)[1]
        settings = get_user_settings(chat_id)
        if val == "facebook":
            settings["platforms"] = ["facebook"]
        elif val == "instagram":
            settings["platforms"] = ["instagram"]
            if account:
                pages = account.get("pages", [])
                selected = settings.get("selected_pages", [])
                has_ig = any(p.get("instagram_business_account") for p in pages if p["id"] in selected)
                if not has_ig:
                    tg_send(chat_id, "\u26a0\ufe0f Instagram غير مربوط بهذه الصفحات حالياً.\nسيتم نشر Facebook فقط أو تسجيل Instagram كفشل.")
        elif val == "both":
            settings["platforms"] = ["facebook", "instagram"]
        save_user_settings(chat_id, settings)
        _send_platform_selection(chat_id, settings["platforms"])
        return

    if data == "platform_save":
        settings = get_user_settings(chat_id)
        tg_send(chat_id, "\u2705 تم حفظ المنصات: " + ", ".join(settings.get("platforms", [])), main_keyboard())
        return

    # TIMEZONE
    if data.startswith("tz:"):
        tz = data.split(":", 1)[1]
        settings = get_user_settings(chat_id)
        settings["timezone"] = tz
        save_user_settings(chat_id, settings)
        tg_send(chat_id, "\u2705 تم حفظ التوقيت: " + tz, main_keyboard())
        return

    # SCHEDULE TYPE
    if data.startswith("sched_type:"):
        stype = data.split(":", 1)[1]
        state["step"] = "sched_waiting_content"
        state["sched_type"] = stype
        save_bot_state(chat_id, state)
        if stype == "text":
            tg_send(chat_id, "\U0001f4dd أرسل النص للجدولة:")
        elif stype == "photo":
            tg_send(chat_id, "\U0001f5bc أرسل الصورة للجدولة:")
        elif stype == "video":
            tg_send(chat_id, "\U0001f3ac أرسل الفيديو للجدولة:")
        return

    # SCHEDULE CONFIRM
    if data == "sched_confirm":
        pending = state.get("pending_sched")
        if not pending:
            tg_send(chat_id, "\u274c لا توجد بيانات جدولة.")
            return
        settings = get_user_settings(chat_id)
        post = save_scheduled_post(
            chat_id,
            pending["type"],
            pending.get("text", ""),
            pending.get("file_url"),
            pending.get("selected_pages", []),
            pending.get("platforms", ["facebook"]),
            pending.get("timezone", "Africa/Algiers"),
            pending.get("scheduled_local", ""),
            pending.get("scheduled_utc", ""),
        )
        clear_bot_state(chat_id)
        tg_send(chat_id, "\u2705 تمت الجدولة بنجاح!\nID: " + post["id"] + "\nالوقت: " + post["scheduled_local"], main_keyboard())
        return

    if data == "sched_cancel":
        clear_bot_state(chat_id)
        tg_send(chat_id, "\u274c تم إلغاء الجدولة.", main_keyboard())
        return

    # CONFIRM PUBLISH
    if data.startswith("confirm_publish:"):
        ptype = data.split(":", 1)[1]
        execute_confirm_publish(chat_id, ptype)
        return

    if data == "cancel_publish":
        clear_bot_state(chat_id)
        tg_send(chat_id, "\u274c تم الإلغاء.", main_keyboard())
        return

    # DELETE SCHEDULED
    if data.startswith("delete_sched:"):
        sid = data.split(":", 1)[1]
        sched = read_json("scheduled_posts.json", {"posts": []})
        changed = False
        for p in sched["posts"]:
            if p["id"] == sid and p.get("telegram_id") == str(chat_id):
                if p["status"] in ("pending", "queued"):
                    p["status"] = "cancelled"
                    changed = True
                elif p["status"] == "published":
                    tg_send(chat_id, "\u274c لا يمكن حذف منشور منشور بالفعل.")
                    return
        if changed:
            write_json("scheduled_posts.json", sched)
            tg_send(chat_id, "\u2705 تم إلغاء الجدولة ID: " + sid, main_keyboard())
        else:
            tg_send(chat_id, "\u274c لم يُعثر على المنشور أو لا يمكن حذفه.")
        return

# ──────────────────────────────────────────────
# MESSAGE HANDLER
# ──────────────────────────────────────────────
def handle_message(message):
    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()
    photo = message.get("photo")
    video = message.get("video")
    caption = message.get("caption", "").strip()

    if ADMIN_CHAT_ID and str(chat_id) != str(ADMIN_CHAT_ID):
        tg_send(chat_id, "\u274c هذا البوت خاص، غير مسموح لك باستعماله.")
        return

    state = get_bot_state(chat_id)
    step = state.get("step", "")

    # CANCEL
    if text == "❌ إلغاء":
        handle_cancel(chat_id)
        return

    # STEP-BASED HANDLING
    if step == "waiting_text_post":
        clear_bot_state(chat_id)
        process_text_post(chat_id, text)
        return

    if step == "waiting_photo_post":
        if photo:
            file_id = photo[-1]["file_id"]
            clear_bot_state(chat_id)
            process_photo_post(chat_id, file_id, caption)
        else:
            tg_send(chat_id, "\u274c أرسل صورة من فضلك.")
        return

    if step == "waiting_video_post":
        if video:
            file_id = video["file_id"]
            clear_bot_state(chat_id)
            process_video_post(chat_id, file_id, caption)
        else:
            tg_send(chat_id, "\u274c أرسل فيديو من فضلك.")
        return

    if step == "sched_waiting_content":
        stype = state.get("sched_type", "text")
        if stype == "text":
            if not text:
                tg_send(chat_id, "\u274c أرسل نصاً من فضلك.")
                return
            state["step"] = "sched_waiting_time"
            state["sched_content"] = {"text": text, "file_url": None}
            save_bot_state(chat_id, state)
            tg_send(chat_id, "\U0001f4c5 أدخل وقت النشر بالصيغة:\nYYYY-MM-DD HH:MM")
        elif stype == "photo":
            if photo:
                file_id = photo[-1]["file_id"]
                file_url = tg_get_file(file_id)
                state["step"] = "sched_waiting_time"
                state["sched_content"] = {"text": caption, "file_url": file_url}
                save_bot_state(chat_id, state)
                tg_send(chat_id, "\U0001f4c5 أدخل وقت النشر:\nYYYY-MM-DD HH:MM")
            else:
                tg_send(chat_id, "\u274c أرسل صورة.")
        elif stype == "video":
            if video:
                file_id = video["file_id"]
                file_url = tg_get_file(file_id)
                state["step"] = "sched_waiting_time"
                state["sched_content"] = {"text": caption, "file_url": file_url}
                save_bot_state(chat_id, state)
                tg_send(chat_id, "\U0001f4c5 أدخل وقت النشر:\nYYYY-MM-DD HH:MM")
            else:
                tg_send(chat_id, "\u274c أرسل فيديو.")
        return

    if step == "sched_waiting_time":
        if not text:
            tg_send(chat_id, "\u274c أدخل الوقت بالصيغة الصحيحة: YYYY-MM-DD HH:MM")
            return
        settings = get_user_settings(chat_id)
        tz = settings.get("timezone", "Africa/Algiers")
        utc_str = local_to_utc(text, tz)
        if not utc_str:
            tg_send(chat_id, "\u274c صيغة الوقت غير صحيحة. استخدم: YYYY-MM-DD HH:MM")
            return
        sched_content = state.get("sched_content", {})
        selected = settings.get("selected_pages", [])
        platforms = settings.get("platforms", ["facebook"])
        stype = state.get("sched_type", "text")
        preview = ("\U0001f4cc معاينة الجدولة\n"
                   "\U0001f4c4 النوع: " + stype + "\n"
                   "\U0001f3af الصفحات: " + str(len(selected)) + "\n"
                   "\U0001f310 المنصة: " + ", ".join(platforms) + "\n"
                   "\U0001f552 التوقيت: " + tz + "\n"
                   "\U0001f4c5 الوقت المحلي: " + text + "\n"
                   "\U0001f310 الوقت UTC: " + utc_str[:16])
        state["step"] = "sched_confirm_wait"
        state["pending_sched"] = {
            "type": stype,
            "text": sched_content.get("text", ""),
            "file_url": sched_content.get("file_url"),
            "selected_pages": selected,
            "platforms": platforms,
            "timezone": tz,
            "scheduled_local": text,
            "scheduled_utc": utc_str,
        }
        save_bot_state(chat_id, state)
        buttons = [
            [{"text": "\u2705 تأكيد الجدولة", "callback_data": "sched_confirm"}],
            [{"text": "\u274c إلغاء", "callback_data": "sched_cancel"}],
        ]
        tg_send(chat_id, preview, {"inline_keyboard": buttons})
        return

    # MAIN MENU
    if text == "/start":
        handle_start(chat_id)
    elif text == "🏠 الرئيسية":
        handle_home(chat_id)
    elif text == "📊 لوحة التحكم":
        handle_dashboard(chat_id)
    elif text == "➕ ربط Meta":
        handle_link_meta(chat_id)
    elif text == "📄 حساباتي":
        handle_accounts_info(chat_id)
    elif text == "🔄 تحديث الحسابات":
        handle_refresh_accounts(chat_id)
    elif text == "🎯 اختيار الصفحات":
        handle_select_pages(chat_id)
    elif text == "🌐 اختيار المنصة":
        handle_select_platform(chat_id)
    elif text == "🌍 اختيار التوقيت":
        handle_select_timezone(chat_id)
    elif text == "📝 نشر نص":
        handle_post_text_start(chat_id)
    elif text == "🖼 نشر صورة":
        handle_post_photo_start(chat_id)
    elif text == "🎬 نشر فيديو":
        handle_post_video_start(chat_id)
    elif text == "⏰ جدولة منشور":
        handle_schedule_start(chat_id)
    elif text == "📋 المجدولات":
        handle_list_scheduled(chat_id)
    elif text == "🗑 حذف مجدول":
        handle_delete_scheduled_start(chat_id)
    else:
        tg_send(chat_id, "\u2753 استخدم القائمة أدناه.", main_keyboard())

# ──────────────────────────────────────────────
# ROUTES
# ──────────────────────────────────────────────
@app.route("/")
def index():
    missing = []
    for v in ["META_APP_ID", "META_APP_SECRET", "TELEGRAM_BOT_TOKEN", "BASE_URL"]:
        if not os.getenv(v):
            missing.append(v)
    return jsonify({
        "ok": True,
        "app": "AutoPost Pro",
        "missing_env": missing,
        "telegram_ready": bool(TELEGRAM_BOT_TOKEN),
        "routes": ["/", "/auth/meta/start", "/auth/meta/callback", "/accounts", "/telegram/set-webhook", "/telegram/delete-webhook", "/telegram/webhook", "/cron/publish-scheduled", "/cron/process-jobs", "/privacy", "/terms", "/data-deletion"],
    })

@app.route("/privacy")
def privacy():
    return "<h1>Privacy Policy</h1><p>This bot stores only data necessary for operation. No data is shared with third parties.</p>"

@app.route("/terms")
def terms():
    return "<h1>Terms of Service</h1><p>Use this bot responsibly and in accordance with Meta platform policies.</p>"

@app.route("/data-deletion", methods=["GET", "POST"])
def data_deletion():
    return jsonify({"status": "ok", "message": "Contact admin to delete your data."})

@app.route("/auth/meta/start")
def auth_meta_start():
    telegram_id = request.args.get("telegram_id", "")
    if not telegram_id:
        return "Missing telegram_id", 400
    state = str(uuid.uuid4())[:16]
    states = read_json("oauth_states.json", {})
    states[state] = {"telegram_id": str(telegram_id), "created_at": now_iso()}
    write_json("oauth_states.json", states)
    scope = ",".join(SCOPES)
    url = ("https://www.facebook.com/" + META_GRAPH_VERSION + "/dialog/oauth"
           "?client_id=" + META_APP_ID
           + "&redirect_uri=" + META_REDIRECT_URI
           + "&scope=" + scope
           + "&state=" + state
           + "&response_type=code")
    return redirect(url)

@app.route("/auth/meta/callback")
def auth_meta_callback():
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")

    if error:
        return "OAuth error: " + str(error), 400

    states = read_json("oauth_states.json", {})
    state_data = states.get(state)
    if not state_data:
        return "Invalid or expired state.", 400

    telegram_id = state_data["telegram_id"]
    states.pop(state, None)
    write_json("oauth_states.json", states)

    try:
        r = requests.get(
            GRAPH_BASE + "/oauth/access_token",
            params={
                "client_id": META_APP_ID,
                "client_secret": META_APP_SECRET,
                "redirect_uri": META_REDIRECT_URI,
                "code": code,
            },
            timeout=15,
        )
        token_data = r.json()
    except Exception as e:
        return "Token exchange failed: " + str(e), 500

    if "error" in token_data:
        return "Token error: " + str(token_data["error"]), 400

    user_access_token = token_data.get("access_token")

    try:
        r2 = requests.get(
            GRAPH_BASE + "/me",
            params={"access_token": user_access_token, "fields": "id,name"},
            timeout=10,
        )
        me = r2.json()
    except Exception as e:
        me = {}

    try:
        r3 = requests.get(
            GRAPH_BASE + "/me/accounts",
            params={"access_token": user_access_token, "fields": "id,name,access_token,instagram_business_account"},
            timeout=15,
        )
        pages_data = r3.json()
        pages = pages_data.get("data", [])
    except Exception as e:
        pages = []

    account = {
        "telegram_id": telegram_id,
        "meta_user": me,
        "user_access_token": user_access_token,
        "pages": pages,
        "connected_at": now_iso(),
    }
    save_account(telegram_id, account)

    tg_send(telegram_id, ("\u2705 تم ربط حساب Meta بنجاح!\n"
                          "\U0001f464 الاسم: " + me.get("name", "غير معروف") + "\n"
                          "\U0001f4c4 الصفحات: " + str(len(pages))), main_keyboard())

    return "<h2>✅ تم ربط حسابك بنجاح! ارجع إلى Telegram.</h2>"

@app.route("/accounts")
def accounts_route():
    accounts = read_json("accounts.json", {})
    safe = {}
    for tid, acc in accounts.items():
        pages_safe = []
        for p in acc.get("pages", []):
            ig = p.get("instagram_business_account")
            pages_safe.append({
                "id": p["id"],
                "name": p.get("name", ""),
                "has_page_token": bool(p.get("access_token")),
                "instagram_business_account": ig,
            })
        safe[tid] = {
            "telegram_id": tid,
            "meta_user": acc.get("meta_user", {}),
            "pages": pages_safe,
            "connected_at": acc.get("connected_at", ""),
        }
    return jsonify(safe)

@app.route("/telegram/set-webhook")
def set_webhook():
    webhook_url = BASE_URL + "/telegram/webhook"
    r = requests.get(
        TELEGRAM_API + "/setWebhook",
        params={"url": webhook_url, "allowed_updates": json.dumps(["message", "callback_query"])},
        timeout=10,
    )
    return jsonify(r.json())

@app.route("/telegram/delete-webhook")
def delete_webhook():
    r = requests.get(TELEGRAM_API + "/deleteWebhook", timeout=10)
    return jsonify(r.json())

@app.route("/telegram/webhook", methods=["POST"])
def telegram_webhook():
    try:
        update = request.get_json(force=True)
        if not update:
            return jsonify({"ok": True})

        update_id = update.get("update_id")
        if update_id and is_duplicate_update(update_id):
            return jsonify({"ok": True, "duplicate": True})

        if "callback_query" in update:
            handle_callback(update["callback_query"])
        elif "message" in update:
            handle_message(update["message"])

        return jsonify({"ok": True})
    except Exception as e:
        logger.error("webhook error: %s\n%s", e, traceback.format_exc())
        return jsonify({"ok": True})

# ──────────────────────────────────────────────
# CRON: PUBLISH SCHEDULED
# ──────────────────────────────────────────────
@app.route("/cron/publish-scheduled")
def cron_publish_scheduled():
    try:
        sched = read_json("scheduled_posts.json", {"posts": []})
        now = datetime.now(timezone.utc)
        processed = 0
        for post in sched.get("posts", []):
            if post["status"] != "pending":
                continue
            utc_str = post.get("scheduled_utc", "")
            if not utc_str:
                continue
            try:
                scheduled_dt = datetime.fromisoformat(utc_str)
            except Exception:
                continue
            if scheduled_dt > now:
                continue

            ptype = post.get("type", "text")
            selected = post.get("selected_pages", [])
            is_video = (ptype == "video")
            multi = len(selected) > 1

            if is_video or multi:
                job = create_job(
                    post["telegram_id"],
                    ptype,
                    post.get("text", ""),
                    post.get("file_url"),
                    selected,
                    post.get("platforms", ["facebook"]),
                )
                post["status"] = "queued"
                tg_send(post["telegram_id"], ("\U0001f4e6 تم تحويل المجدول إلى مهمة نشر\n"
                                               "Job ID: " + job["id"]))
            else:
                account = get_account(post["telegram_id"])
                if not account:
                    post["status"] = "failed"
                    continue
                targets = build_publish_targets(account, selected, post.get("platforms", ["facebook"]))
                results = do_publish_targets(post["telegram_id"], targets, ptype, post.get("text", ""), post.get("file_url"))
                post["status"] = "published"
                post["results"] = results

            processed += 1

        write_json("scheduled_posts.json", sched)
        return jsonify({"ok": True, "processed": processed})
    except Exception as e:
        logger.error("cron_publish_scheduled error: %s", e)
        return jsonify({"ok": False, "error": str(e)})

# ──────────────────────────────────────────────
# CRON: PROCESS JOBS
# ──────────────────────────────────────────────
@app.route("/cron/process-jobs")
def cron_process_jobs():
    try:
        jobs_data = read_json("jobs.json", {"jobs": []})
        now_timestamp = now_ts()
        job = None

        for j in jobs_data["jobs"]:
            if j["status"] in ("completed", "failed", "cancelled"):
                continue
            if j["status"] == "processing":
                started = j.get("processing_started_at")
                if started and (now_timestamp - started) < 600:
                    continue
            job = j
            break

        if not job:
            return jsonify({"ok": True, "message": "no pending jobs"})

        job["status"] = "processing"
        job["processing_started_at"] = now_timestamp
        write_json("jobs.json", jobs_data)

        telegram_id = job["telegram_id"]
        account = get_account(telegram_id)
        if not account:
            job["status"] = "failed"
            write_json("jobs.json", jobs_data)
            return jsonify({"ok": False, "error": "no account"})

        all_pages = account.get("pages", [])
        pages_map = {p["id"]: p for p in all_pages}
        selected_pages = job.get("selected_pages", [])
        platforms = job.get("platforms", ["facebook"])
        current_index = job.get("current_index", 0)

        targets = []
        for pid in selected_pages:
            page = pages_map.get(pid)
            if not page:
                continue
            for platform in platforms:
                if platform == "facebook":
                    targets.append((page, "facebook"))
                elif platform == "instagram":
                    ig = page.get("instagram_business_account")
                    if ig and ig.get("id"):
                        targets.append((page, "instagram"))
                    else:
                        targets.append((page, "instagram_missing"))

        total = len(targets)
        max_per_run = 2

        if current_index >= total:
            job["status"] = "completed"
            write_json("jobs.json", jobs_data)
            return jsonify({"ok": True, "message": "job already done"})

        end_index = min(current_index + max_per_run, total)
        batch = targets[current_index:end_index]

        for i, (page, platform) in enumerate(batch):
            real_i = current_index + i
            page_name = page.get("name", page["id"])
            num = str(real_i + 1) + "/" + str(total)

            success = False
            reason = ""
            post_id = None
            jtype = job.get("type", "text")
            text = job.get("text", "")
            file_url = job.get("file_url")

            if platform == "instagram_missing":
                success = False
                reason = "Instagram غير مربوط"
            elif platform == "facebook":
                if jtype == "text":
                    success, reason, post_id = publish_text_to_page(page, text)
                elif jtype == "photo":
                    success, reason, post_id = publish_photo_to_page(page, file_url, text)
                elif jtype == "video":
                    success, reason, post_id = publish_video_to_page(page, file_url, text)
            elif platform == "instagram":
                ig = page.get("instagram_business_account", {})
                ig_id = ig.get("id") if ig else None
                page_token = page.get("access_token", "")
                if not ig_id:
                    success = False
                    reason = "Instagram غير مربوط"
                elif jtype == "text":
                    success = False
                    reason = "Instagram لا يدعم نص فقط"
                elif jtype == "photo":
                    success, reason, post_id = publish_photo_to_instagram(ig_id, page_token, file_url, text)
                elif jtype == "video":
                    success, reason, post_id = publish_video_to_instagram(ig_id, page_token, file_url, text)

            job["results"].append({"page_id": page["id"], "page_name": page_name, "platform": platform, "success": success, "reason": reason, "post_id": post_id})

            if success:
                msg = "\u2705 تم نشر جزء من المهمة\nJob: " + job["id"] + "\nProgress: " + num + "\n\U0001f4c4 " + page_name
            else:
                msg = "\u274c فشل النشر في المهمة\nJob: " + job["id"] + "\nProgress: " + num + "\n\U0001f4c4 " + page_name + "\nالسبب: " + reason
            tg_send(telegram_id, msg)

        job["current_index"] = end_index

        if end_index >= total:
            job["status"] = "completed"
            ok_count = sum(1 for r in job["results"] if r["success"])
            fail_count = total - ok_count
            summary = ("\U0001f3c1 اكتملت المهمة\nJob: " + job["id"] + "\n\u2705 نجح: " + str(ok_count) + "\n\u274c فشل: " + str(fail_count))
            tg_send(telegram_id, summary)
        else:
            job["status"] = "partial"

        write_json("jobs.json", jobs_data)
        return jsonify({"ok": True, "job_id": job["id"], "progress": str(end_index) + "/" + str(total), "status": job["status"]})

    except Exception as e:
        logger.error("cron_process_jobs error: %s\n%s", e, traceback.format_exc())
        return jsonify({"ok": False, "error": str(e)})

# ──────────────────────────────────────────────
# STARTUP
# ──────────────────────────────────────────────
ensure_data_dir()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
