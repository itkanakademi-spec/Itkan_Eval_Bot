import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    CallbackQueryHandler, filters, ContextTypes
)

TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID"))
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "")

# tekrar başlatmalarda kaybolabilir, geçici bellek
student_answers = {}
student_names = {}

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

LEVEL_ADVICE = {
    "nurani": "Kaide-i Nuraniyye seviyesindesiniz. Harflerin mahreçlerine ve temel okuma kurallarına odaklanarak sağlam bir temel oluşturmanız önerilir.",
    "beginner": "Başlangıç seviyesindesiniz. Tecvid kurallarını tekrar ederek ve düzenli pratikle okuyuşunuzu güçlendirebilirsiniz.",
    "intermediate": "Orta seviyedesiniz. Akıcılığınızı artırmak için uzun soluklu okumalar ve tecvid detaylarına dikkat etmeniz önerilir.",
    "advanced": "İleri seviyedesiniz. Maşallah! Tilavetinizi daha da geliştirmek için tertil ve tecvid inceliklerine odaklanabilirsiniz.",
}

# --------------------------
# 🚀 /start
# --------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌿 <b>Hoş geldiniz!</b>\n\n"
        "Kur'an tilavetinizi geliştirme yolunda attığınız bu adım çok kıymetlidir ✨\n\n"
        "🎙️ Lütfen <b>Fetih Suresi 29. ayeti</b> ses kaydı olarak gönderiniz.\n\n"
        "📌 İTKAN | Kur'an Akademisi",
        parse_mode="HTML"
    )

# --------------------------
# 🎤 Ses kaydı alma
# --------------------------
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    voice = update.message.voice.file_id

    student_names[user.id] = user.first_name

    text = (
        f"🎧 <b>Yeni tilavet gönderildi</b>\n\n"
        f"👤 Öğrenci: {user.first_name}\n"
        f"🆔 ID: <code>{user.id}</code>\n\n"
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

    # Öğrenciye tecvid sorusu
    keyboard = [
        [InlineKeyboardButton("✅ Evet", callback_data="student_yes", style="success")],
        [InlineKeyboardButton("❌ Hayır", callback_data="student_no", style="danger")]
    ]
    await update.message.reply_text(
        "📌 Tecvid eğitimi aldınız mı?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# --------------------------
# 👩‍🎓 Öğrenci tecvid cevabı
# --------------------------
async def handle_student_tajweed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    answer = "Aldı" if query.data == "student_yes" else "Almadı"
    student_answers[user_id] = answer

    await query.edit_message_text(
        "✅ Cevabınız kaydedildi.\n\n"
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

    data = query.data.split("_")
    level = data[1]
    student_id = int(data[2])

    tajweed = student_answers.get(student_id, "Bilinmiyor")
    student_name = student_names.get(student_id, "Öğrenci")

    channel_line = f"\n\n📢 Kaydınızı paylaşmak için: {CHANNEL_LINK}" if CHANNEL_LINK else ""

    message = (
        f"📊 <b>Değerlendirmeniz:</b>\n\n"
        f"Seviye: {LEVEL_MAP.get(level)}\n"
        f"Tecvid: {tajweed}\n\n"
        f"💡 {LEVEL_ADVICE.get(level, '')}"
        f"{channel_line}\n\n"
        f"📌 İTKAN | Kur'an Akademisi"
    )

    try:
        await context.bot.send_message(chat_id=student_id, text=message, parse_mode="HTML")
        status = "gönderildi ✅"
    except Exception:
        status = "gönderilemedi ⚠️ (öğrenci botu başlatmamış olabilir)"

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
    app.add_handler(CallbackQueryHandler(handle_student_tajweed, pattern="^student_"))
    app.add_handler(CallbackQueryHandler(handle_level, pattern="^level_"))
    app.run_polling()

if __name__ == "__main__":
    main()
