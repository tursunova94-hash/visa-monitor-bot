import os, time, logging, requests, random
from bs4 import BeautifulSoup
import telebot

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

TELEGRAM_TOKEN     = os.environ["TELEGRAM_TOKEN"]
CHAT_ID            = os.environ["TELEGRAM_CHAT_ID"]
PRENOTAMI_EMAIL    = os.environ["PRENOTAMI_EMAIL"]
PRENOTAMI_PASSWORD = os.environ["PRENOTAMI_PASSWORD"]
VFS_EMAIL          = os.environ["VFS_EMAIL"]
VFS_PASSWORD       = os.environ["VFS_PASSWORD"]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

NO_SLOT_PHRASES = [
    "not yet available",
    "нет доступных слотов",
    "приносим извинения",
    "календарь бронирования еще не доступен",
    "calendario delle prenotazioni non ancora disponibile",
]

bot = telebot.TeleBot(TELEGRAM_TOKEN)

def send_alert(msg, urgent=False):
    try:
        emoji = "🚨🚨🚨" if urgent else "ℹ️"
        bot.send_message(CHAT_ID, f"{emoji} *VISA MONITOR*\n\n{msg}", parse_mode="Markdown")
        log.info(f"TG sent: {msg[:50]}")
    except Exception as e:
        log.error(f"TG error: {e}")

def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    })
    return s

def human_delay():
    t = random.uniform(2, 5)
    time.sleep(t)

def has_no_slots(text):
    return any(p in text.lower() for p in NO_SLOT_PHRASES)

prenotami_session = None
prenotami_ok = False

def prenotami_login():
    global prenotami_session, prenotami_ok
    prenotami_session = make_session()
    try:
        r = prenotami_session.get("https://prenotami.esteri.it/Home", timeout=20)
        human_delay()
        soup = BeautifulSoup(r.text, "html.parser")
        token = soup.find("input", {"name": "__RequestVerificationToken"})
        if not token:
            return False
        r2 = prenotami_session.post(
            "https://prenotami.esteri.it/Home",
            data={"Email": PRENOTAMI_EMAIL, "Password": PRENOTAMI_PASSWORD, "__RequestVerificationToken": token["value"]},
            timeout=20
        )
        if "logout" in r2.text.lower() or "services" in r2.url.lower():
            prenotami_ok = True
            log.info("prenotami: login OK")
            return True
        return False
    except Exception as e:
        log.error(f"prenotami login: {e}")
        return False

def check_prenotami():
    global prenotami_ok
    if not prenotami_ok:
        if not prenotami_login(): return False
    try:
        prenotami_session.headers.update({"User-Agent": random.choice(USER_AGENTS)})
        r = prenotami_session.get("https://prenotami.esteri.it/Services", timeout=20)
        if "login" in r.url.lower():
            prenotami_ok = False; return False
        soup = BeautifulSoup(r.text, "html.parser")
        for row in soup.select("tr"):
            t = row.get_text(" ", strip=True).lower()
            if ("schengen" in t or "шенген" in t or "turistica" in t or "туристич" in t) and not has_no_slots(t):
                log.info(f"PRENOTAMI SLOT: {t[:80]}")
                return True
        log.info("prenotami: no slots")
        return False
    except Exception as e:
        log.error(f"prenotami check: {e}")
        prenotami_ok = False
        return False

vfs_session = None
vfs_ok = False

def vfs_login():
    global vfs_session, vfs_ok
    vfs_session = make_session()
    try:
        r = vfs_session.post(
            "https://visa.vfsglobal.com/uzb/ru/lva/api/v1/users/login",
            json={"username": VFS_EMAIL, "password": VFS_PASSWORD, "missionCode": "lva", "countryCode": "uzb", "languageCode": "ru"},
            timeout=20
        )
        if r.status_code == 200:
            t = r.json().get("token") or r.json().get("accessToken")
            if t:
                vfs_session.headers["Authorization"] = f"Bearer {t}"
                vfs_ok = True
                log.info("vfs: login OK")
                return True
        return False
    except Exception as e:
        log.error(f"vfs login: {e}")
        return False

def check_vfs():
    global vfs_ok
    if not vfs_ok:
        if not vfs_login(): return False
    try:
        vfs_session.headers.update({"User-Agent": random.choice(USER_AGENTS)})
        r = vfs_session.get(
            "https://visa.vfsglobal.com/uzb/ru/lva/api/v1/appointment/slots?missionCode=lva&countryCode=uzb&centerCode=TAS&serviceCode=SCHENGEN_VISA_SWITZERLAND",
            timeout=20
        )
        if r.status_code == 401:
            vfs_ok = False; return False
        if r.status_code == 200:
            data = r.json()
            slots = data if isinstance(data, list) else data.get("slots", data.get("dates", []))
            if slots:
                log.info(f"VFS SLOT: {slots}")
                return True
        log.info("vfs: no slots")
        return False
    except Exception as e:
        log.error(f"vfs check: {e}")
        vfs_ok = False
        return False

def main():
    log.info("=== Visa Monitor started ===")
    send_alert("✅ Мониторинг запущен!\n\n🇮🇹 Италия — prenotami\n🇨🇭 Швейцария — VFS Global\n\nПроверяю каждые 30-40 сек 🔍")
    n = 0
    while True:
        n += 1
        log.info(f"--- check #{n} ---")
        try:
            if check_prenotami():
                send_alert("🇮🇹 *СЛОТ — ИТАЛИЯ!*\n\n👉 https://prenotami.esteri.it/Services\n\n⚡️ ~1-2 минуты!", urgent=True)
        except Exception as e:
            log.error(e)

        human_delay()

        try:
            if check_vfs():
                send_alert("🇨🇭 *СЛОТ — ШВЕЙЦАРИЯ VFS!*\n\n👉 https://visa.vfsglobal.com/uzb/ru/lva/book-an-appointment\n\n⚡️ ~2-3 минуты!", urgent=True)
        except Exception as e:
            log.error(e)

        if n % 60 == 0:
            send_alert(f"👁 Активен. Проверок: {n}. Слотов пока нет.")

        sleep_time = random.uniform(30, 40)
        log.info(f"sleeping {sleep_time:.1f}s")
        time.sleep(sleep_time)

if __name__ == "__main__":
    main()
