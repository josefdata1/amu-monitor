import asyncio
import os
import hashlib
import json
import requests
from playwright.async_api import async_playwright
from PIL import Image
import imagehash
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# ================= CONFIG =================
PAGES = {
    "Main Portal": "https://www.amucontrollerexams.com/",
    "Results": "https://results.amucontrollerexams.com/result/results",
    "Counselling": "https://results.amucontrollerexams.com/result/cons/sch_adm",
    "School Results": "https://results.amucontrollerexams.com/schools/sch/school",
    "PhD Results": "https://results.amucontrollerexams.com/phd/phdresult/phdadm",
    "Answer Keys": "https://results.amucontrollerexams.com/display/anskeys",
}

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

BASELINE_FILE = "baselines.json"
SCREENSHOT_DIR = "screenshots"
PDF_DIR = "pdfs"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(PDF_DIR, exist_ok=True)
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

def extract_text(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    lines = [line.strip() for line in soup.get_text(separator="\n").splitlines() if line.strip()]
    return "\n".join(lines)

def extract_pdf_links(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().endswith(".pdf"):
            absolute = urljoin(base_url, href)
            if absolute not in links:
                links.append(absolute)
    return links

def get_text_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()

def get_visual_hash(path):
    with Image.open(path) as img:
        return str(imagehash.phash(img.convert("RGB")))

def find_new_content(old_text, new_text):
    if not old_text:
        return new_text[:800]
    old_lines = set(old_text.splitlines())
    added = [line for line in new_text.splitlines() if line not in old_lines]
    if added:
        return "\n".join(added)
    return new_text[:800]

def download_pdf(url, name, index):
    try:
        r = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            content_type = r.headers.get("content-type", "")
            if "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
                filename = os.path.join(PDF_DIR, f"{name}_{index}.pdf")
                with open(filename, "wb") as f:
                    f.write(r.content)
                return filename
    except Exception as e:
        print(f"PDF download failed: {url} - {e}")
    return None

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

def send_telegram_document(doc_path, caption):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
    try:
        with open(doc_path, "rb") as f:
            requests.post(url, files={"document": f}, data={
                "chat_id": CHAT_ID,
                "caption": caption,
                "parse_mode": "HTML"
            }, timeout=60)
    except Exception as e:
        print(f"Telegram document error: {e}")

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
    first_run = not baselines

    for name, url in PAGES.items():
        print(f"Checking: {name}")
        try:
            html, shot_path = await capture(url, name)
            v_hash = get_visual_hash(shot_path)
            text_content = extract_text(html)
            t_hash = get_text_hash(text_content)
            pdf_links = extract_pdf_links(html, url)

            old = baselines.get(name, {})
            old_v = old.get("visual", "")
            old_t_hash = old.get("text_hash", "")
            old_t_content = old.get("text_content", "")
            old_pdfs = old.get("pdf_links", [])

            if first_run or not old_t_content:
                baselines[name] = {
                    "visual": v_hash,
                    "text_hash": t_hash,
                    "text_content": text_content,
                    "pdf_links": pdf_links
                }
                print(f"  {name}: Baseline saved")
                continue

            changes = []
            if old_v and v_hash != old_v:
                changes.append("🎨 Visual")
            if old_t_hash and t_hash != old_t_hash:
                changes.append("📝 Text")

            new_pdfs = [p for p in pdf_links if p not in old_pdfs]

            if changes or new_pdfs:
                # Build text alert
                new_text = find_new_content(old_t_content, text_content)
                alert = f"🔔 <b>{name}</b> changed!\n\n"
                if changes:
                    alert += f"Type: {' + '.join(changes)}\n\n"
                if new_pdfs:
                    alert += f"📄 <b>New PDFs detected:</b> {len(new_pdfs)}\n\n"
                alert += f"📝 <b>New content:</b>\n{new_text[:700]}\n\n"
                alert += f"🔗 <a href='{url}'>Open Page</a>"

                send_telegram_text(alert)

                # Download and send each new PDF
                for i, pdf_url in enumerate(new_pdfs):
                    pdf_path = download_pdf(pdf_url, name, i)
                    if pdf_path:
                        caption = f"📄 <b>{name}</b> — New PDF #{i+1}\n{pdf_url}"
                        send_telegram_document(pdf_path, caption)
                    else:
                        send_telegram_text(f"⚠️ Failed to download PDF: {pdf_url}")

                baselines[name] = {
                    "visual": v_hash,
                    "text_hash": t_hash,
                    "text_content": text_content,
                    "pdf_links": pdf_links
                }
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
            + "\n\n<b>New PDFs</b> will be sent as documents.\n"
            + "<b>New text</b> will be shown in the alert."
        )
        print("BASELINE_SET")
        return

    save_baselines(baselines)
    print("DONE")

if __name__ == "__main__":
    asyncio.run(main())
