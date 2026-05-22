# AutoPost Pro — دليل الإعداد الكامل

بوت Telegram احترافي للنشر والجدولة على Facebook Pages وInstagram عبر Meta Graph API.

---

## الملفات المطلوبة

```
autopost_pro/
├── server.py
├── requirements.txt
├── Procfile
├── .env.example
├── .gitignore
└── README_AR.md
```

---

## متغيرات البيئة

```
META_APP_ID=         # من Meta Developer Dashboard
META_APP_SECRET=     # من Meta Developer Dashboard
META_GRAPH_VERSION=v25.0
BASE_URL=https://YOUR-APP.onrender.com
META_REDIRECT_URI=https://YOUR-APP.onrender.com/auth/meta/callback
TELEGRAM_BOT_TOKEN=  # من @BotFather
ADMIN_CHAT_ID=       # Chat ID خاصتك (اختياري للحماية)
DATA_DIR=data
```

---

## 1. إعداد المشروع على Termux

```bash
# تثبيت المتطلبات
pkg update && pkg upgrade -y
pkg install python git -y
pip install flask requests python-dotenv gunicorn

# إنشاء المجلد
mkdir -p /sdcard/Download/autopost_pro
cd /sdcard/Download/autopost_pro

# انسخ الملفات (server.py, requirements.txt, Procfile, .gitignore)
# ثم أنشئ ملف .env من .env.example وعدّل القيم

# اختبار محلي
python server.py
```

---

## 2. رفع المشروع على GitHub

```bash
cd /sdcard/Download/autopost_pro

git init
git add .
git commit -m "init autopost pro stable"
git branch -M main
git remote add origin https://github.com/USERNAME/autopost-pro.git
git push -u origin main
```

> استبدل `USERNAME` باسم مستخدم GitHub الخاص بك.

---

## 3. النشر على Render

### أ. إنشاء Web Service جديد

1. اذهب إلى [render.com](https://render.com) وسجل الدخول.
2. اضغط **New** → **Web Service**.
3. اختر الـ repository من GitHub.
4. اضبط الإعدادات:

| الحقل | القيمة |
|-------|--------|
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `gunicorn server:app --workers 1 --timeout 120 --bind 0.0.0.0:$PORT` |
| **Region** | اختر الأقرب لك |
| **Instance Type** | Free |

### ب. إضافة متغيرات البيئة في Render

اذهب إلى **Environment** وأضف:

```
META_APP_ID          = قيمتك
META_APP_SECRET      = قيمتك
META_GRAPH_VERSION   = v25.0
BASE_URL             = https://YOUR-APP.onrender.com
META_REDIRECT_URI    = https://YOUR-APP.onrender.com/auth/meta/callback
TELEGRAM_BOT_TOKEN   = قيمتك
ADMIN_CHAT_ID        = قيمتك
DATA_DIR             = data
```

> **ملاحظة:** استبدل `YOUR-APP` بالـ subdomain الفعلي الذي أعطاك إياه Render.

---

## 4. إعداد Meta App

1. اذهب إلى [developers.facebook.com](https://developers.facebook.com).
2. اختر تطبيقك → **Settings** → **Basic**.
3. في **App Domains** أضف:
   ```
   YOUR-APP.onrender.com
   ```
4. اذهب إلى **Facebook Login** → **Settings**.
5. في **Valid OAuth Redirect URIs** أضف:
   ```
   https://YOUR-APP.onrender.com/auth/meta/callback
   ```
6. احفظ التغييرات.

### الصلاحيات المطلوبة (Permissions)

```
pages_show_list
pages_read_engagement
pages_manage_posts
business_management
```

### لاحقاً لـ Instagram

```
instagram_basic
instagram_content_publish
```

---

## 5. ضبط Telegram Webhook

بعد رفع التطبيق على Render وتشغيله، افتح المتصفح:

```
https://YOUR-APP.onrender.com/telegram/set-webhook
```

يجب أن ترى:

```json
{"ok": true, "result": true, "description": "Webhook was set"}
```

للحذف إذا احتجت:

```
https://YOUR-APP.onrender.com/telegram/delete-webhook
```

---

## 6. إعداد UptimeRobot

لأن Render Free يوقف التطبيق عند عدم الاستخدام، استخدم UptimeRobot لإبقائه حياً وتشغيل الـ cron jobs.

1. اذهب إلى [uptimerobot.com](https://uptimerobot.com) وأنشئ حساباً.
2. أضف **3 مراقبات** من نوع HTTP(s):

| الاسم | الرابط | الفاصل الزمني |
|-------|--------|---------------|
| AutoPost Keep Alive | `https://YOUR-APP.onrender.com/` | 5 دقائق |
| AutoPost Publish Scheduled | `https://YOUR-APP.onrender.com/cron/publish-scheduled` | 5 دقائق |
| AutoPost Process Jobs | `https://YOUR-APP.onrender.com/cron/process-jobs` | 1 دقيقة |

---

## 7. اختبار البوت خطوة بخطوة

```
1. افتح البوت في Telegram وأرسل /start
2. اضغط ➕ ربط Meta
3. اتبع رابط OAuth واربط حسابك
4. اضغط 📄 حساباتي — يجب أن ترى الصفحات
5. اضغط 🎯 اختيار الصفحات — اختر صفحة أو أكثر
6. اضغط 🌐 اختيار المنصة — اختر Facebook
7. اضغط 📝 نشر نص — أرسل نصاً
8. أكد النشر من المعاينة
9. اضغط 🖼 نشر صورة — أرسل صورة
10. اضغط 🎬 نشر فيديو — الفيديو يدخل jobs تلقائياً
11. انتظر UptimeRobot ليستدعي /cron/process-jobs
    أو اختبر يدوياً: https://YOUR-APP.onrender.com/cron/process-jobs
12. اضغط ⏰ جدولة منشور — اختر النوع وأدخل الوقت
13. اضغط 📋 المجدولات — تحقق من القائمة
14. اضغط 📊 لوحة التحكم — شاهد الإحصائيات
```

---

## 8. هيكل ملفات البيانات

```
data/
├── accounts.json          # حسابات Meta (مع tokens)
├── oauth_states.json      # حالات OAuth المؤقتة
├── bot_states.json        # حالات المحادثات
├── user_settings.json     # إعدادات المستخدمين
├── posts_log.json         # سجل المنشورات
├── scheduled_posts.json   # المنشورات المجدولة
├── jobs.json              # مهام النشر في الخلفية
└── processed_updates.json # مضاد التكرار
```

> **تحذير:** مجلد `data/` مستثنى من git (في .gitignore). على Render Free، البيانات تُحذف عند كل deploy. للحفاظ على البيانات، استخدم Render Disk أو انقل إلى قاعدة بيانات خارجية لاحقاً.

---

## 9. حل المشاكل الشائعة

### البوت لا يستجيب
- تحقق من أن Webhook مضبوط: `/telegram/set-webhook`
- تحقق من `TELEGRAM_BOT_TOKEN` في متغيرات Render
- راجع Logs في Render Dashboard

### OAuth يفشل
- تأكد من `META_REDIRECT_URI` مطابق تماماً لما في Meta App
- تأكد من إضافة App Domain في Meta

### الفيديو لا ينشر
- Meta قد يرفض روابط Telegram المباشرة
- الحل الدائم: رفع الفيديو إلى Cloudinary أولاً ثم استخدام رابطه
- تحقق من رسالة الخطأ في Telegram

### Jobs لا تنفذ
- تأكد من أن UptimeRobot يستدعي `/cron/process-jobs`
- اختبر يدوياً من المتصفح

---

## 10. تحديث الكود

```bash
cd /sdcard/Download/autopost_pro

# بعد تعديل server.py
git add .
git commit -m "update: وصف التغيير"
git push

# Render سيعيد البناء تلقائياً
```

---

## الميزات المخططة لاحقاً

- [ ] رفع الفيديو إلى Cloudinary تلقائياً
- [ ] دعم Instagram Reels كامل
- [ ] قاعدة بيانات PostgreSQL للبيانات الدائمة
- [ ] دعم أكثر من مستخدم (multi-user)
- [ ] إحصائيات المنشورات

---

## الترخيص

للاستخدام الشخصي فقط. احترم سياسات Meta وTelegram.
