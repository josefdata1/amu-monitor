import asyncio
import os
import hashlib
import json
import requests
from playwright.async_api import async_playwright
from PIL import Image
import imagehash
from bs4 import BeautifulSoup

# ================= CONFIG =================
PAGES = {
    "Main Portal": "https://www.amucontrollerexams.com/",
    "Results": "https://results.amucontrollerexams.com/result/results",
    "Counselling": "https://results.amucontrollerexams.com/result/cons/sch_adm",
    "School Results": "https://results.amucontrollerexams.com/schools/sch/school",
    "PhD Results": "https://results.amucontrollerexams.com/phd/phdresult/phdadm",
}

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

BASELINE_FILE = "baselines.json"
SCREENSHOT_DIR = "screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)
# ==========================================

async def capture(url, name):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 4000})
        await page.goto(url, wait_until="networkidle", timeout=60000)
        shot_path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
        await page.screenshot(path=shot_path, full_page=True)
        html = await page.content()
        await browser.close()
        return html, shot_path

def get_visual_hash(path):
    with Image.open(path) as img:
        return str(imagehash.phash(img.convert("RGB")))

def get_text_hash(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()

def send_telegram_text(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={
            "chat_id": CHAT_ID,
            "text": msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }, timeout=30)
    except Exception as e:
        print(f"Telegram text error: {e}")

def send_telegram_photo(photo_path, caption):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    try:
        with open(photo_path, "rb") as f:
            requests.post(url, files={"photo": f}, data={
                "chat_id": CHAT_ID,
                "caption": caption,
                "parse_mode": "HTML"
            }, timeout=60)
    except Exception as e:
        print(f"Telegram photo error: {e}")
        send_telegram_text(caption + "\n\n(Screenshot failed to send)")

def load_baselines():
    if os.path.exists(BASELINE_FILE):
        with open(BASELINE_FILE) as f:
            return json.load(f)
    return {}

def save_baselines(data):
    with open(BASELINE_FILE, "w") as f:
        json.dump(data, f, indent=2)

async def main():
    baselines = load_baselines()
    alerts = []
    first_run = not baselines

    for name, url in PAGES.items():
        print(f"Checking: {name}")
        try:
            html, shot_path = await capture(url, name)
            v_hash = get_visual_hash(shot_path)
            t_hash = get_text_hash(html)

            old = baselines.get(name, {})
            old_v = old.get("visual", "")
            old_t = old.get("text", "")

            if first_run:
                baselines[name] = {"visual": v_hash, "text": t_hash}
                print(f"  {name}: Baseline saved")
                continue

            changes = []
            if old_v and v_hash != old_v:
                changes.append("🎨 Visual")
            if old_t and t_hash != old_t:
                changes.append("📝 Text")

            if changes:
                caption = (
                    f"🔔 <b>{name}</b> changed!\n\n"
                    f"Type: {' + '.join(changes)}\n"
                    f"🔗 <a href='{url}'>Open Page</a>"
                )
                send_telegram_photo(shot_path, caption)
                baselines[name] = {"visual": v_hash, "text": t_hash}
                alerts.append(name)
            else:
                print(f"  {name}: No change")

        except Exception as e:
            print(f"  {name}: ERROR - {e}")
            send_telegram_text(f"⚠️ <b>{name}</b> monitor failed!\nError: {str(e)[:200]}")

    if first_run:
        save_baselines(baselines)
        send_telegram_text(
            f"✅ <b>AMU Monitor Started</b>\n\n"
            f"Tracking <b>{len(PAGES)}</b> pages every 44 minutes:\n\n"
            + "\n".join([f"• {n}" for n in PAGES.keys()])
            + "\n\nFirst screenshots attached."
        )
        for name in PAGES.keys():
            shot_path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
            if os.path.exists(shot_path):
                send_telegram_photo(shot_path, f"📸 Baseline: <b>{name}</b>")
        print("BASELINE_SET")
        return

    if alerts:
        save_baselines(baselines)
        print(f"ALERTS_SENT: {', '.join(alerts)}")
    else:
        print("ALL_CLEAR")

if __name__ == "__main__":
    asyncio.run(main())
  
