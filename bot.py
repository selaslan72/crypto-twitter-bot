import os, re, json, random, hashlib
import datetime as dt
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw

import tweepy
from openai import OpenAI

# ========= Settings =========
DEBUG = os.getenv("DEBUG", "0") == "1"

HEADERS = {"User-Agent": "Mozilla/5.0 (crypto-bot)"}

COINGECKO_NEW_API = "https://api.coingecko.com/api/v3/coins/list/new"
COINGECKO_NEW_WEB = "https://www.coingecko.com/en/new-cryptocurrencies"
CRYPTORANK_UPCOMING = "https://cryptorank.io/upcoming-ico"

STATE_PATH = "state.json"
SEEN_DAYS_PROJECT = int(os.getenv("SEEN_DAYS_PROJECT", "7"))
SEEN_DAYS_TEXT = int(os.getenv("SEEN_DAYS_TEXT", "2"))

# ========= AI (GitHub Models) =========
ai = OpenAI(
    base_url="https://models.github.ai/inference",
    api_key=os.environ["GITHUB_TOKEN"],
)

# ========= X Auth =========
auth = tweepy.OAuth1UserHandler(
    consumer_key=os.environ["X_API_KEY"],
    consumer_secret=os.environ["X_API_SECRET"],
    access_token=os.environ["X_ACCESS_TOKEN"],
    access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
)
x_api_v1 = tweepy.API(auth)  # media upload
x_client_v2 = tweepy.Client(
    consumer_key=os.environ["X_API_KEY"],
    consumer_secret=os.environ["X_API_SECRET"],
    access_token=os.environ["X_ACCESS_TOKEN"],
    access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    wait_on_rate_limit=True,
)


def log(*args):
    if DEBUG:
        print(*args, flush=True)


# ----------------- State -----------------
def load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"seen_projects": {}, "seen_text_hashes": {}, "last_reply_date": ""}


def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def iso_today():
    return dt.datetime.utcnow().date().isoformat()


def days_ago(iso_date: str) -> int:
    try:
        d = dt.date.fromisoformat(iso_date)
        return (dt.datetime.utcnow().date() - d).days
    except Exception:
        return 9999


def hash_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def remember_text(text: str, state):
    h = hash_text(text)
    state["seen_text_hashes"][h] = iso_today()


def remember_project(url: str, state):
    if url:
        state["seen_projects"][url] = iso_today()


def is_duplicate_text(text: str, state):
    h = hash_text(text)
    last = state["seen_text_hashes"].get(h, "")
    return bool(last and days_ago(last) < SEEN_DAYS_TEXT)


# ----------------- Helpers -----------------
def fetch_text(url: str, limit: int = 120000) -> str:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        if r.status_code >= 400:
            return ""
        return r.text[:limit]
    except Exception:
        return ""


def pick_source_for_this_run() -> str:
    # deterministik: 07 & 15 UTC => CoinGecko; 11 & 19 UTC => CryptoRank
    h = dt.datetime.utcnow().hour
    return "coingecko" if h in (7, 15) else "cryptorank"


def normalize_url(url: str) -> str:
    """
    URL'yi mümkünse redirect sonrası final haline getirir.
    HEAD/GET başarısız olursa URL'yi boş yapmaz; olduğu gibi bırakır.
    """
    url = (url or "").strip()
    if not url:
        return ""
    url = url.split()[0]
    url = url.rstrip(").,;]}>\"'")

    # HEAD dene
    try:
        r = requests.head(url, headers=HEADERS, timeout=12, allow_redirects=True)
        if r.status_code < 400 and r.url:
            return r.url
    except Exception:
        pass

    # GET dene
    try:
        r = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
        if r.status_code < 400 and r.url:
            return r.url
    except Exception:
        pass

    # Son çare: URL'yi olduğu gibi döndür
    return url


# ----------------- Sources -----------------
def coingecko_new_projects():
    # API dene
    try:
        r = requests.get(COINGECKO_NEW_API, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            data = r.json()
            out = []
            for it in data[:80]:
                cid = it.get("id")
                name = (it.get("name") or "").strip()
                symbol = (it.get("symbol") or "").upper()
                url = f"https://www.coingecko.com/en/coins/{cid}" if cid else COINGECKO_NEW_WEB
                if name:
                    out.append({"name": name, "symbol": symbol, "url": url})
            return out
    except Exception:
        pass

    # Web fallback
    html = fetch_text(COINGECKO_NEW_WEB)
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/en/coins/" in href:
            url = "https://www.coingecko.com" + href if href.startswith("/") else href
            if url in seen:
                continue
            seen.add(url)
            name = a.get_text(" ", strip=True)
            if name and len(name) <= 40:
                out.append({"name": name, "symbol": "", "url": url})
    return out[:40]


def cryptorank_upcoming_projects():
    html = fetch_text(CRYPTORANK_UPCOMING)
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        txt = a.get_text(" ", strip=True)
        if not txt or len(txt) > 50:
            continue
        href = a["href"]
        url = "https://cryptorank.io" + href if href.startswith("/") else href
        if url in seen:
            continue
        seen.add(url)
        if "/price/" in url or "/coins/" in url or "/ico/" in url:
            out.append({"name": txt, "symbol": "", "url": url})
    return out[:40]


def find_x_handle_from_page(url: str):
    html = fetch_text(url, limit=120000)
    if not html:
        return None
    m = re.search(r"(?:x\.com|twitter\.com)/([A-Za-z0-9_]{1,15})", html)
    if not m:
        return None
    handle = m.group(1)
    if handle.lower() in {"share", "intent", "home"}:
        return None
    return "@" + handle


# ----------------- AI -----------------
def ai_research_tweet(project, source_name):
    name = project.get("name", "").strip()
    symbol = project.get("symbol", "").strip()
    url = project.get("url", "").strip()
    handle = find_x_handle_from_page(url) if url else None

    prompt = f"""
You are a friendly crypto Twitter researcher.

Write ONE tweet in Turkish with a warm, sympathetic tone (not cringe).
No emojis, no hashtags.

The tweet MUST follow this exact 3-line format:
Line 1: Mini summary (what it is / why it matters)
Line 2: Mini summary (what to watch next / potential catalyst) AND MUST end with the URL
Line 3: Risk: <one honest risk note>

Rules:
- Total length <= 240 characters.
- Include the URL exactly once.
- If handle is provided, include it exactly once.
- If handle is empty, DO NOT invent tags.
- Be factual. If unclear, say "net değil" or "belirsiz".
- Line 2 MUST end with the URL (place it at the very end).

Project: {name}
Symbol: {symbol}
URL: {url}
Handle: {handle or "none"}

Return STRICT JSON:
{{"tweet":"...","caption":"..."}}
"""

    res = ai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.65,
    )

    raw = (res.choices[0].message.content or "").strip()

    try:
        obj = json.loads(raw)
        tweet = (obj.get("tweet", "") or "").replace("\r", "").strip()[:240]
        caption = (obj.get("caption", "") or "").strip()[:70]
        return tweet, caption
    except Exception:
        fallback = f"{name}\nTakip: {url}\nRisk: erken aşama / detaylar net değil"
        return fallback[:240], name[:70]


# ----------------- Image (free, local) -----------------
def make_card(title: str, subtitle: str, out="card.png"):
    img = Image.new("RGB", (1024, 1024), color=(15, 15, 18))
    d = ImageDraw.Draw(img)
    title = title.strip()[:60]
    subtitle = subtitle.strip()[:120]
    d.text((64, 140), title, fill=(235, 235, 235))
    d.text((64, 230), subtitle, fill=(190, 190, 190))
    d.text((64, 920), "new / upcoming project", fill=(120, 120, 120))
    img.save(out, "PNG")
    return out


def post_tweet(text: str, image_path=None) -> bool:
    try:
        if image_path:
            media = x_api_v1.media_upload(image_path)
            x_client_v2.create_tweet(text=text, media_ids=[media.media_id_string])
        else:
            x_client_v2.create_tweet(text=text)
        log("Tweet sent OK")
        return True
    except tweepy.errors.Forbidden as e:
        print("X FORBIDDEN 403:", str(e), flush=True)
        return False
    except Exception as e:
        print("TWEET ERROR:", repr(e), flush=True)
        return False


# ----------------- Filters -----------------
def filter_projects(projects, state):
    out = []
    for p in projects:
        url = (p.get("url") or "").strip()
        if not url:
            continue
        last = state["seen_projects"].get(url, "")
        if last and days_ago(last) < SEEN_DAYS_PROJECT:
            continue
        out.append(p)
    return out or projects


def enforce_3_lines_and_url(tweet: str, url: str) -> str:
    lines = [l.strip() for l in (tweet or "").split("\n") if l.strip()]
    lines = lines[:3]

    while len(lines) < 3:
        if len(lines) == 2:
            lines.append("Risk: detaylar net değil / erken aşama")
        else:
            lines.append("Takip:")

    # URL line2 sonu
    if url:
        l2 = lines[1].split("http")[0].strip()
        lines[1] = (l2 + " " + url).strip()

    # Risk satırı garanti
    if not lines[2].lower().startswith("risk"):
        lines[2] = ("Risk: " + lines[2]).strip()

    return "\n".join(lines)[:240]


def main():
    state = load_state()

    source = pick_source_for_this_run()
    if source == "coingecko":
        projects = coingecko_new_projects()
        source_name = "CoinGecko recently added"
    else:
        projects = cryptorank_upcoming_projects()
        source_name = "CryptoRank upcoming token sales"

    log("SOURCE:", source, "PROJECTS:", len(projects))

    if not projects:
        print("No projects found. Exiting.", flush=True)
        save_state(state)
        return

    candidates = filter_projects(projects, state)
    project = random.choice(candidates)

    # URL'yi burada normalize et ve project'e yaz (tek kaynak gerçeği)
    project["url"] = normalize_url(project.get("url", ""))
    url = project.get("url", "").strip()

    log("PICKED:", project.get("name"), url)

    # URL tamamen boşsa: tweet atma (ama log bas)
    if not url:
        print("Skipping: URL invalid/empty after normalization", flush=True)
        save_state(state)
        return

    # Tweet üret
    tweet, caption = ai_research_tweet(project, source_name)

    # 3 satır + URL düzelt
    tweet = enforce_3_lines_and_url(tweet, url)

    log("TWEET_DRAFT:\n" + tweet)

    # Duplicate text ise 1 kere yeniden üret
    if is_duplicate_text(tweet, state):
        log("Duplicate text detected. Regenerating once...")
        tweet2, caption2 = ai_research_tweet(project, source_name)
        tweet2 = enforce_3_lines_and_url(tweet2, url)
        if not is_duplicate_text(tweet2, state):
            tweet, caption = tweet2, caption2
            log("Regenerated tweet accepted.")
        else:
            print("Skipping: duplicate text after regeneration", flush=True)
            save_state(state)
            return

    # Görsel: sadece UTC 07:00 (TR 10:00)
    h = dt.datetime.utcnow().hour
    with_image = (h == 7)

    success = False
    if with_image:
        img = make_card(project.get("name", "New Project"), caption or "quick research")
        success = post_tweet(tweet, image_path=img)
    else:
        success = post_tweet(tweet)

    # 403/duplicate vb. için 1 retry
    if not success:
        log("Post failed. Retrying once with new text...")
        tweet2, caption2 = ai_research_tweet(project, source_name)
        tweet2 = enforce_3_lines_and_url(tweet2, url)

        if with_image:
            img = make_card(project.get("name", "New Project"), caption2 or "quick research")
            success = post_tweet(tweet2, image_path=img)
        else:
            success = post_tweet(tweet2)

        if success:
            tweet, caption = tweet2, caption2

    if not success:
        print("Skipping: could not post after retry", flush=True)
        save_state(state)
        return

    # state güncelle
    remember_project(url, state)
    remember_text(tweet, state)
    save_state(state)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback

        print("BOT FAILED:", str(e), flush=True)
        traceback.print_exc()
        raise
