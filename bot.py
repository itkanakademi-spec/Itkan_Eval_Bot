import os
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone

import firebase_admin
from firebase_admin import credentials, firestore

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    CallbackQueryHandler, filters, ContextTypes
)

TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID"))
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "")
COLLECTION = "itkan_eval_records"

# tekrar başlatmalarda kaybolabilir, geçici bellek (sadece aktif oturum verisi)
student_data = {}  # user_id -> {"name":..,"age":..,"username":..,"tajweed":..}

# --------------------------
# Firebase Bağlantısı
# --------------------------
firebase_json = json.loads(os.getenv("FIREBASE_CREDENTIALS"))
cred = credentials.Certificate(firebase_json)
firebase_admin.initialize_app(cred)
db = firestore.client()

# --------------------------
# Dummy HTTP Server (Render port gereksinimi için)
# --------------------------
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()
    def log_message(self, format, *args):
        pass

def run_server():
    port = int(os.getenv("PORT", 10000))
    HTTPServer(("0.0.0.0", port), DummyHandler).serve_forever()

# --------------------------
# Yardımcı
# --------------------------
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    admins = await context.bot.get_chat_administrators(GROUP_ID)
    return any(a.user.id == user_id for a in admins)

LEVEL_MAP = {
    "nurani": "🔵 Kaide-i Nuraniyye",
    "beginner": "🟡 Başlangıç",
    "intermediate": "🟠 Orta",
    "advanced": "🔴 İleri",
}

LEVEL_NAMES = {
    "nurani": "Kaide-i Nuraniyye",
    "beginner": "Başlangıç",
    "intermediate": "Orta",
    "advanced": "İleri",
}

LEVEL_MOTIVATION = {
    "nurani": "Her yolculuk bir adımla başlar 🌱 Kur'an'la tanışma yolculuğunuzun başındasınız, bu çok kıymetli bir adım.",
    "beginner": "Güzel bir başlangıç yaptınız 🌿 Düzenli tekrarla kısa sürede çok yol kat edeceksiniz inşallah.",
    "intermediate": "Emeğiniz gözle görülüyor 🌷 Bu seviyeye gelmek sabır ister, tebrikler!",
    "advanced": "Maşallah, gerçekten güzel bir seviyedesiniz. Bu inceliği korumak ve derinleştirmek için devam edin.",
}

# --------------------------
# 🚀 /start — isim sorusuyla başlar
# --------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = "await_name"
    student_data[update.effective_user.id] = {
        "username": update.effective_user.username or "yok"
    }
    await update.message.reply_text(
        "🌿 <b>Hoş geldiniz!</b>\n\n"
        "Kur'an tilavetinizi geliştirme yolunda attığınız bu adım çok kıymetlidir\n\n"
        "📝 Lütfen önce <b>adınızı ve soyadınızı</b> yazınız:",
        parse_mode="HTML"
    )

# --------------------------
# 📝 Metin mesajları (isim / yaş)
# --------------------------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if state == "await_name":
        student_data.setdefault(user_id, {})["name"] = text
        context.user_data["state"] = "await_age"
        await update.message.reply_text("🔢 Şimdi lütfen yaşınızı yazınız:")

    elif state == "await_age":
        student_data.setdefault(user_id, {})["age"] = text
        context.user_data["state"] = "await_tajweed"

        keyboard = [
            [InlineKeyboardButton("✅ Evet", callback_data="student_yes", style="success")],
            [InlineKeyboardButton("❌ Hayır", callback_data="student_no", style="danger")]
        ]
        await update.message.reply_text(
            "📌 Tecvid eğitimi aldınız mı?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    else:
        await update.message.reply_text("ℹ️ Başlamak için lütfen /start yazınız.")

# --------------------------
# 👩‍🎓 Öğrenci tecvid cevabı → ardından ses kaydı istenir
# --------------------------
async def handle_student_tajweed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    answer = "Aldı" if query.data == "student_yes" else "Almadı"
    student_data.setdefault(user_id, {})["tajweed"] = answer
    context.user_data["state"] = "await_voice"

    await query.edit_message_text(
        "✅ Bilgileriniz kaydedildi.\n\n"
        "🎙️ Şimdi lütfen <b>Fetih Suresi 29. ayeti</b> ses kaydı olarak gönderiniz.",
        parse_mode="HTML"
    )

# --------------------------
# 🎤 Ses kaydı alma
# --------------------------
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user

    if context.user_data.get("state") != "await_voice":
        await update.message.reply_text("ℹ️ Lütfen önce /start yazarak bilgilerinizi tamamlayınız.")
        return

    data = student_data.get(user.id, {})
    if not data.get("name") or not data.get("age"):
        context.user_data["state"] = None
        await update.message.reply_text("ℹ️ Bilgileriniz eksik. Lütfen /start yazarak yeniden başlayınız.")
        return

    voice = update.message.voice.file_id
    data = student_data.setdefault(user.id, {})
    data["username"] = user.username or "yok"

    name = data.get("name", user.first_name)
    age = data.get("age", "Bilinmiyor")
    username = data.get("username", "yok")
    tajweed = data.get("tajweed", "Bilinmiyor")
    telegram_name = user.full_name  # Telegram hesabındaki gerçek görünen isim

    text = (
        f"🎧 <b>Yeni tilavet gönderildi</b>\n\n"
        f"👤 Ad Soyad: {name}\n"
        f"📱 Telegram İsmi: {telegram_name}\n"
        f"🔢 Yaş: {age}\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"🔗 Kullanıcı adı: @{username}\n"
        f"📌 Tecvid: {tajweed}\n\n"
        f"📌 İTKAN | Kur'an Akademisi"
    )

    await context.bot.send_voice(chat_id=GROUP_ID, voice=voice)
    await context.bot.send_message(chat_id=GROUP_ID, text=text, parse_mode="HTML")

    # Öğretmen için seviye değerlendirme butonları
    level_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(LEVEL_MAP["nurani"], callback_data=f"level_nurani_{user.id}")],
        [InlineKeyboardButton(LEVEL_MAP["beginner"], callback_data=f"level_beginner_{user.id}")],
        [InlineKeyboardButton(LEVEL_MAP["intermediate"], callback_data=f"level_intermediate_{user.id}")],
        [InlineKeyboardButton(LEVEL_MAP["advanced"], callback_data=f"level_advanced_{user.id}")],
    ])
    await context.bot.send_message(
        chat_id=GROUP_ID,
        text="👇 Lütfen bu öğrencinin seviyesini seçin:",
        reply_markup=level_keyboard
    )

    context.user_data["state"] = None

    await update.message.reply_text(
        "✅ Kaydınız alındı.\n\n"
        "⏳ Değerlendirme süreciniz başlamıştır.\n"
        "Değerlendirmeniz en kısa sürede tarafınıza iletilecektir inşallah 🌿\n\n"
        "📌 İTKAN | Kur'an Akademisi"
    )

# --------------------------
# 👩‍🏫 Öğretmen seviye değerlendirmesi
# --------------------------
async def handle_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not await is_admin(update, context):
        await query.answer("⛔️ Sadece yöneticiler değerlendirebilir", show_alert=True)
        return

    await query.answer()

    data_parts = query.data.split("_")
    level = data_parts[1]
    student_id = int(data_parts[2])

    data = student_data.get(student_id, {})
    tajweed = data.get("tajweed", "Bilinmiyor")
    student_name = data.get("name", "Öğrenci")

    channel_line = ""
    if CHANNEL_LINK:
        channel_line = (
            f"\n\n🔔 Seviyenize uygun yeni kurs kayıtları açıldığında kaçırmamak için "
            f"kanaldaki duyuruları takip etmenizi rica ederiz."
        )

    message = (
        f"📊 <b>Değerlendirmeniz:</b>\n\n"
        f"Seviyeniz: {LEVEL_MAP.get(level)}\n"
        f"Tecvid: {tajweed}\n\n"
        f"💡 {LEVEL_MOTIVATION.get(level, '')}"
        f"{channel_line}\n\n"
        f"📌 İTKAN | Kur'an Akademisi"
    )

    try:
        await context.bot.send_message(chat_id=student_id, text=message, parse_mode="HTML")

        if CHANNEL_LINK:
            channel_message = (
                f"📢 <b>{LEVEL_NAMES.get(level)} seviye tilavet derslerine</b> "
                f"ana kanalımızdan katılabilirsiniz:\n{CHANNEL_LINK}\n\n"
                f"🌿 Faydalanabilmeleri için bu bağlantıyı kadın kardeşlerinizle paylaşabilirsiniz."
            )
            await context.bot.send_message(chat_id=student_id, text=channel_message, parse_mode="HTML")

        status = "gönderildi ✅"
    except Exception:
        status = "gönderilemedi ⚠️ (öğrenci botu başlatmamış olabilir)"

    # Kalıcı kayıt (Firestore)
    try:
        db.collection(COLLECTION).add({
            "student_id": student_id,
            "name": student_name,
            "age": data.get("age", "Bilinmiyor"),
            "username": data.get("username", "yok"),
            "tajweed": tajweed,
            "level": level,
            "level_name": LEVEL_NAMES.get(level),
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        print(f"Firestore kayıt hatası: {e}")

    await query.edit_message_text(
        f"✅ {student_name} için '{LEVEL_MAP.get(level)}' değerlendirmesi kaydedildi.\n"
        f"Öğrenciye sonuç: {status}"
    )

# --------------------------
# Çalıştır
# --------------------------
def main():
    threading.Thread(target=run_server, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_student_tajweed, pattern="^student_"))
    app.add_handler(CallbackQueryHandler(handle_level, pattern="^level_"))
    app.run_polling()

if __name__ == "__main__":
    main()
