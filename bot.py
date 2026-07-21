import os
import json
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

# Her seviyeye özel grup linki (Render ortam değişkenlerinden okunur)
LEVEL_GROUP_LINKS = {
    "nurani": os.getenv("GROUP_LINK_NURANI", ""),
    "beginner": os.getenv("GROUP_LINK_BEGINNER", ""),
    "intermediate": os.getenv("GROUP_LINK_INTERMEDIATE", ""),
    "advanced": os.getenv("GROUP_LINK_ADVANCED", ""),
}

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

    elif state == "await_name_fix":
        student_data.setdefault(user_id, {})["name"] = text
        context.user_data["state"] = None
        await update.message.reply_text("✅ İsminiz güncellendi, teşekkür ederiz.")

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
        [InlineKeyboardButton("🔁 Sesi tekrar iste", callback_data=f"resendvoice_{user.id}")],
        [InlineKeyboardButton("✏️ İsmi tekrar iste", callback_data=f"resendname_{user.id}")],
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
# 🔁 Öğretmen sesi tekrar istiyor
# --------------------------
async def handle_resend_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not await is_admin(update, context):
        await query.answer("⛔️ Sadece yöneticiler bu işlemi yapabilir", show_alert=True)
        return

    await query.answer()

    student_id = int(query.data.split("_")[1])

    # Öğrencinin durumu "ses bekleniyor" olarak ayarlanır; isim/yaş/tecvid bilgileri saklı kalır
    context.application.user_data[student_id]["state"] = "await_voice"

    try:
        await context.bot.send_message(
            chat_id=student_id,
            text=(
                "🎙️ Ses kaydınızda bir sorun tespit edildi.\n\n"
                "Lütfen <b>Fetih Suresi 29. ayeti</b> ses kaydı olarak tekrar gönderiniz."
            ),
            parse_mode="HTML"
        )
        await query.message.reply_text("✅ Öğrenciden ses kaydı tekrar istendi.")
    except Exception:
        await query.message.reply_text("⚠️ Öğrenciye mesaj gönderilemedi (bot başlatmamış olabilir).")

# --------------------------
# ✏️ Öğretmen ismi tekrar istiyor
# --------------------------
async def handle_resend_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not await is_admin(update, context):
        await query.answer("⛔️ Sadece yöneticiler bu işlemi yapabilir", show_alert=True)
        return

    await query.answer()

    student_id = int(query.data.split("_")[1])

    # Sadece isim düzeltilecek; yaş/tecvid/ses adımları tekrarlanmaz
    context.application.user_data[student_id]["state"] = "await_name_fix"

    try:
        await context.bot.send_message(
            chat_id=student_id,
            text="📝 Adınızda bir hata tespit edildi. Lütfen adınızı ve soyadınızı tekrar yazınız:"
        )
        await query.message.reply_text("✅ Öğrenciden ismini tekrar yazması istendi.")
    except Exception:
        await query.message.reply_text("⚠️ Öğrenciye mesaj gönderilemedi (bot başlatmamış olabilir).")

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

    group_link = LEVEL_GROUP_LINKS.get(level, "")
    group_line = ""
    if group_link:
        group_line = (
            f"\n\n👥 {LEVEL_NAMES.get(level)} seviyesine özel grubumuza aşağıdaki bağlantıdan katılabilirsiniz:\n"
            f"{group_link}"
        )

    message = (
        f"📊 <b>Değerlendirmeniz:</b>\n\n"
        f"Seviyeniz: {LEVEL_MAP.get(level)}\n"
        f"Tecvid: {tajweed}\n\n"
        f"💡 {LEVEL_MOTIVATION.get(level, '')}"
        f"{group_line}"
        f"{channel_line}\n\n"
        f"📌 İTKAN | Kur'an Akademisi"
    )

    try:
        await context.bot.send_message(chat_id=student_id, text=message, parse_mode="HTML")

        if CHANNEL_LINK:
            channel_message = (
                f"📢 {LEVEL_NAMES.get(level)} seviye tilavet derslerine ana kanalımız üzerinden katılabilirsiniz:\n\n"
                f"{CHANNEL_LINK}\n\n"
                f"🌿 Daha fazla hanım kardeşimizin istifade edebilmesi için bu bağlantıyı onlarla paylaşabilirsiniz."
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
# Çalıştır (Webhook modu — Render Web Service ile uyumlu, ücretsiz)
# --------------------------
import asyncio
from aiohttp import web

async def health(request):
    return web.Response(text="OK")

async def run():
    application = ApplicationBuilder().token(TOKEN).updater(None).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(CallbackQueryHandler(handle_student_tajweed, pattern="^student_"))
    application.add_handler(CallbackQueryHandler(handle_level, pattern="^level_"))
    application.add_handler(CallbackQueryHandler(handle_resend_voice, pattern="^resendvoice_"))
    application.add_handler(CallbackQueryHandler(handle_resend_name, pattern="^resendname_"))

    port = int(os.getenv("PORT", 10000))
    # Render, web servisleri için bu ortam değişkenini otomatik olarak sağlar
    external_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")
    if not external_hostname:
        raise RuntimeError(
            "RENDER_EXTERNAL_HOSTNAME bulunamadı. Render Web Service olarak dağıtıldığından emin olun."
        )

    webhook_path = TOKEN  # tahmin edilmesi zor olsun diye token'ı path olarak kullanıyoruz
    webhook_url = f"https://{external_hostname}/{webhook_path}"

    async def telegram_webhook(request):
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.update_queue.put(update)
        return web.Response()

    web_app = web.Application()
    web_app.router.add_get("/", health)          # UptimeRobot / Render sağlık kontrolü
    web_app.router.add_post(f"/{webhook_path}", telegram_webhook)  # Telegram webhook

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    async with application:
        await application.bot.set_webhook(url=webhook_url)
        await application.start()
        await asyncio.Event().wait()  # sonsuza kadar çalışmaya devam et
        await application.stop()

def main():
    asyncio.run(run())

if __name__ == "__main__":
    main()
