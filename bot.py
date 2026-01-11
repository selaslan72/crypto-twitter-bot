import os, re, json, random, hashlib
import datetime as dt
from typing import Optional, List, Dict, Any, Tuple

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont

import tweepy
from openai import OpenAI

# ========= Settings =========
DEBUG = os.getenv("DEBUG", "0") == "1"
HEADERS = {"User-Agent": "Mozilla/5.0 (crypto-bot)"}

STATE_PATH = "state.json"
SEEN_DAYS_PROJECT = int(os.getenv("SEEN_DAYS_PROJECT", "7"))
SEEN_DAYS_TEXT = int(os.getenv("SEEN_DAYS_TEXT", "2"))

# ========= Sources =========
COINGECKO_NEW_API = "https://api.coingecko.com/api/v3/coins/list/new"
COINGECKO_NEW_WEB = "https://www.coingecko.com/en/new-cryptocurrencies"
COINGECKO_TRENDING = "https://api.coingecko.com/api/v3/search/trending"
COINGECKO_MARKETS = "https://api.coingecko.com/api/v3/coins/markets"
COINGECKO_CATEGORIES_LIST = "https://api.coingecko.com/api/v3/coins/categories/list"
COINGECKO_CATEGORIES = "https://api.coingecko.com/api/v3/coins/categories"

CRYPTORANK_UPCOMING = "https://cryptorank.io/upcoming-ico"

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
def load_state() -> Dict[str, Any]:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"seen_projects": {}, "seen_text_hashes": {}, "last_reply_date": ""}


def save_state(state: Dict[str, Any]) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def iso_today() -> str:
    return dt.datetime.utcnow().date().isoformat()


def days_ago(iso_date: str) -> int:
    try:
        d = dt.date.fromisoformat(iso_date)
        return (dt.datetime.utcnow().date() - d).days
    except Exception:
        return 9999


def hash_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def remember_text(text: str, state: Dict[str, Any]) -> None:
    h = hash_text(text)
    state["seen_text_hashes"][h] = iso_today()


def remember_project(url: str, state: Dict[str, Any]) -> None:
    if url:
        state["seen_projects"][url] = iso_today()


def is_duplicate_text(text: str, state: Dict[str, Any]) -> bool:
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


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    url = url.split()[0]
    url = url.rstrip(").,;]}>\"'")

    try:
        r = requests.head(url, headers=HEADERS, timeout=12, allow_redirects=True)
        if r.status_code < 400 and r.url:
            return r.url
    except Exception:
        pass

    try:
        r = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
        if r.status_code < 400 and r.url:
            return r.url
    except Exception:
        pass

    return url


def pick_section_for_this_run() -> str:
    """
    Deterministik bölüm seçimi (UTC saate göre).
    5 bölüm: trending / narrative / new / movers / upcoming
    """
    h = dt.datetime.utcnow().hour
    sections = ["trending", "narrative", "new", "movers", "upcoming"]
    return sections[h % len(sections)]


# ----------------- CoinGecko API helpers -----------------
def _cg_get_json(url: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
    try:
        r = requests.get(url, headers=HEADERS, params=params or {}, timeout=20)
        if r.status_code >= 400:
            return None
        return r.json()
    except Exception:
        return None


# ----------------- Sources -----------------
def coingecko_new_projects() -> List[Dict[str, str]]:
    # API dene
    try:
        r = requests.get(COINGECKO_NEW_API, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            data = r.json()
            out: List[Dict[str, str]] = []
            for it in data[:120]:
                cid = it.get("id")
                name = (it.get("name") or "").strip()
                symbol = (it.get("symbol") or "").upper()
                url = f"https://www.coingecko.com/en/coins/{cid}" if cid else COINGECKO_NEW_WEB
                if name and url:
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
            if name and len(name) <= 50:
                out.append({"name": name, "symbol": "", "url": url})
    return out[:60]


def coingecko_trending_projects() -> List[Dict[str, str]]:
    data = _cg_get_json(COINGECKO_TRENDING)
    if not data or "coins" not in data:
        return []
    out: List[Dict[str, str]] = []
    for item in data.get("coins", [])[:20]:
        c = item.get("item") or {}
        cid = c.get("id")
        name = (c.get("name") or "").strip()
        symbol = (c.get("symbol") or "").upper()
        url = f"https://www.coingecko.com/en/coins/{cid}" if cid else ""
        if name and url:
            out.append({"name": name, "symbol": symbol, "url": url})
    return out


def coingecko_top_movers_projects(direction: str = "gainers") -> List[Dict[str, str]]:
    """
    direction: "gainers" | "losers"
    """
    data = _cg_get_json(
        COINGECKO_MARKETS,
        params={
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 250,
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "24h",
        },
    )
    if not data:
        return []

    def pct(x):
        try:
            return float(x) if x is not None else -999999.0
        except Exception:
            return -999999.0

    key = "price_change_percentage_24h_in_currency"
    items = []
    for it in data:
        cid = it.get("id")
        name = (it.get("name") or "").strip()
        symbol = (it.get("symbol") or "").upper()
        url = f"https://www.coingecko.com/en/coins/{cid}" if cid else ""
        if name and url:
            items.append({"name": name, "symbol": symbol, "url": url, "_pct": pct(it.get(key))})

    if not items:
        return []

    items.sort(key=lambda x: x["_pct"], reverse=(direction == "gainers"))
    top = items[:40]
    for it in top:
        it.pop("_pct", None)
    return top


def coingecko_random_narrative_projects() -> Tuple[List[Dict[str, str]], Optional[str]]:
    cats = _cg_get_json(COINGECKO_CATEGORIES_LIST)
    cat_id = None
    cat_name = None

    if isinstance(cats, list) and cats:
        c = random.choice(cats)
        cat_id = c.get("category_id")
        cat_name = c.get("name") or "Narrative"
    else:
        cats2 = _cg_get_json(COINGECKO_CATEGORIES)
        if isinstance(cats2, list) and cats2:
            c = random.choice(cats2)
            cat_id = c.get("id")
            cat_name = c.get("name") or "Narrative"

    if not cat_id:
        return [], None

    data = _cg_get_json(
        COINGECKO_MARKETS,
        params={
            "vs_currency": "usd",
            "category": cat_id,
            "order": "volume_desc",
            "per_page": 60,
            "page": 1,
            "sparkline": "false",
        },
    )
    if not data:
        return [], cat_name

    out: List[Dict[str, str]] = []
    for it in data[:50]:
        cid = it.get("id")
        name = (it.get("name") or "").strip()
        symbol = (it.get("symbol") or "").upper()
        url = f"https://www.coingecko.com/en/coins/{cid}" if cid else ""
        if name and url:
            out.append({"name": name, "symbol": symbol, "url": url})
    return out, cat_name


def cryptorank_upcoming_projects() -> List[Dict[str, str]]:
    html = fetch_text(CRYPTORANK_UPCOMING)
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        txt = a.get_text(" ", strip=True)
        if not txt or len(txt) > 60:
            continue
        href = a["href"]
        url = "https://cryptorank.io" + href if href.startswith("/") else href
        if url in seen:
            continue
        seen.add(url)
        if "/price/" in url or "/coins/" in url or "/ico/" in url:
            out.append({"name": txt, "symbol": "", "url": url})
    return out[:60]


def find_x_handle_from_page(url: str) -> Optional[str]:
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
def ai_research_tweet(project: Dict[str, str], section_label: str) -> Tuple[str, str]:
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

Section: {section_label}
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
        fallback = f"{name}\nTakip: {url}\nRisk: detaylar net değil / erken aşama"
        return fallback[:240], name[:70]


# ----------------- Image (cards) -----------------
def _wrap_lines(text: str, max_chars: int) -> List[str]:
    words = (text or "").split()
    if not words:
        return []
    lines, cur, cur_len = [], [], 0
    for w in words:
        add_len = len(w) + (1 if cur else 0)
        if cur_len + add_len > max_chars:
            lines.append(" ".join(cur))
            cur, cur_len = [w], len(w)
        else:
            cur.append(w)
            cur_len += add_len
    if cur:
        lines.append(" ".join(cur))
    return lines


def _load_font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def make_project_card(title: str, subtitle: str, out: str = "card.png") -> str:
    W, H = 1024, 1024
    img = Image.new("RGB", (W, H), color=(15, 15, 18))
    d = ImageDraw.Draw(img)

    title_font = _load_font(64, bold=True)
    sub_font = _load_font(38, bold=False)
    small_font = _load_font(26, bold=False)

    title = (title or "").strip()[:80]
    subtitle = (subtitle or "").strip()[:220]

    title_lines = _wrap_lines(title, max_chars=26)[:3]
    sub_lines = _wrap_lines(subtitle, max_chars=42)[:5]

    x, y = 72, 90

    for line in title_lines:
        d.text((x, y), line, fill=(235, 235, 235), font=title_font)
        y += 74

    y += 18
    d.line((72, y, W - 72, y), fill=(55, 55, 60), width=2)
    y += 28

    for line in sub_lines:
        d.text((x, y), line, fill=(195, 195, 195), font=sub_font)
        y += 52

    d.text((72, H - 70), "Not: Bu bir yatırım tavsiyesi değildir.", fill=(120, 120, 120), font=small_font)

    img.save(out, "PNG")
    return out


def make_watchlist_card(date_iso: str, items: List[str], out: str = "card.png") -> str:
    W, H = 1024, 1024
    img = Image.new("RGB", (W, H), color=(15, 15, 18))
    d = ImageDraw.Draw(img)

    title_font = _load_font(64, bold=True)
    item_font = _load_font(44, bold=False)
    small_font = _load_font(28, bold=False)

    d.text((72, 72), "Günlük Watchlist", fill=(235, 235, 235), font=title_font)
    d.text((72, 158), date_iso, fill=(160, 160, 160), font=small_font)
    d.line((72, 210, W - 72, 210), fill=(55, 55, 60), width=2)

    y = 270
    for it in items[:8]:
        d.text((90, y), f"• {it}", fill=(210, 210, 210), font=item_font)
        y += 78

    d.text((72, H - 70), "Not: Bu bir yatırım tavsiyesi değildir.", fill=(120, 120, 120), font=small_font)

    img.save(out, "PNG")
    return out


def should_attach_image(prob: float = 0.7) -> bool:
    try:
        return random.random() < float(prob)
    except Exception:
        return True


# ----------------- X Posting -----------------
def post_tweet(text: str, image_path: Optional[str] = None) -> bool:
    import time

    for attempt in range(2):
        try:
            if image_path:
                media = x_api_v1.media_upload(image_path)
                resp = x_client_v2.create_tweet(text=text, media_ids=[media.media_id_string])
            else:
                resp = x_client_v2.create_tweet(text=text)

            tid = resp.data.get("id") if resp and resp.data else None
            if tid:
                print("TWEET_LINK:", f"https://x.com/i/web/status/{tid}", flush=True)

            print("Tweet sent OK", flush=True)
            return True

        except tweepy.errors.TooManyRequests as e:
            wait_s = 910
            try:
                headers = getattr(e.response, "headers", {}) or {}
                reset = headers.get("x-rate-limit-reset")
                if reset:
                    wait_s = max(30, int(reset) - int(time.time()) + 5)
            except Exception:
                pass

            print(f"RATE_LIMIT: sleeping {wait_s}s", flush=True)
            time.sleep(wait_s)
            continue

        except tweepy.errors.Forbidden as e:
            print("X_FORBIDDEN_403:", str(e), flush=True)
            return False

        except Exception as e:
            print("TWEET_ERROR:", repr(e), flush=True)
            if attempt == 0:
                time.sleep(5)
                continue
            return False

    return False


def tweet_with_optional_image(
    tweet_text: str,
    title: str,
    subtitle: str,
    force_image: bool = False,
    image_prob: float = 0.7,
) -> bool:
    attach = True if force_image else should_attach_image(image_prob)
    if attach:
        img = make_project_card(title=title, subtitle=subtitle)
        ok = post_tweet(tweet_text, image_path=img)
        print(f"MEDIA: attached=1 ok={int(ok)}", flush=True)
        return ok
    else:
        ok = post_tweet(tweet_text)
        print(f"MEDIA: attached=0 ok={int(ok)}", flush=True)
        return ok


# ----------------- Filters -----------------
def filter_projects(projects: List[Dict[str, str]], state: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Sıkı filtre: seen içinde olanları çıkarır, out boşsa boş döner.
    (Tekrarları azaltmanın ana noktası)
    """
    out = []
    for p in projects:
        url = (p.get("url") or "").strip()
        if not url:
            continue
        last = state["seen_projects"].get(url, "")
        if last and days_ago(last) < SEEN_DAYS_PROJECT:
            continue
        out.append(p)
    return out


def enforce_3_lines_and_url(tweet: str, url: str) -> str:
    lines = [l.strip() for l in (tweet or "").split("\n") if l.strip()]
    lines = lines[:3]

    while len(lines) < 3:
        if len(lines) == 2:
            lines.append("Risk: detaylar net değil / erken aşama")
        else:
            lines.append("Takip:")

    if url:
        l2 = lines[1].split("http")[0].strip()
        lines[1] = (l2 + " " + url).strip()

    if not lines[2].lower().startswith("risk"):
        lines[2] = ("Risk: " + lines[2]).strip()

    return "\n".join(lines)[:240]


# ----------------- Main -----------------
def load_projects_for_section(section: str) -> Tuple[List[Dict[str, str]], str]:
    narrative_name = None

    if section == "new":
        projects = coingecko_new_projects()
        label = "New Listings"
    elif section == "trending":
        projects = coingecko_trending_projects()
        label = "Trending"
    elif section == "movers":
        direction = "gainers" if (dt.datetime.utcnow().day % 2 == 0) else "losers"
        projects = coingecko_top_movers_projects(direction=direction)
        label = "Top Gainers (24h)" if direction == "gainers" else "Top Losers (24h)"
    elif section == "narrative":
        projects, narrative_name = coingecko_random_narrative_projects()
        label = f"Narrative: {narrative_name or 'Category'}"
    elif section == "upcoming":
        projects = cryptorank_upcoming_projects()
        label = "Upcoming Token Sales"
    else:
        projects = coingecko_new_projects()
        label = "New Listings"

    return projects, label


def main():
    state = load_state()

    section = pick_section_for_this_run()
    projects, section_label = load_projects_for_section(section)

    log("SECTION:", section, "LABEL:", section_label, "PROJECTS:", len(projects))

    # 1) Kaynaklar tamamen boşsa: watchlist fallback (en son çare)
    if not projects:
        today = iso_today()
        fallback_tweet = (
            f"Gün sakin görünüyor ({today}). Takip listem:\n"
            "• Fermah\n"
            "• Netrum\n"
            "• OpenMind\n"
            "• TOKI Finance\n\n"
            "Risk: Bilgi akışı sınırlı olabilir; detaylar netleşmeyebilir."
        )
        items = ["Fermah", "Netrum", "OpenMind", "TOKI Finance"]
        img = make_watchlist_card(today, items)
        ok = post_tweet(fallback_tweet, image_path=img)
        print(f"SUMMARY: attempted=1 posted={int(ok)} reason=FALLBACK_WATCHLIST_NO_SOURCES section={section}", flush=True)
        if ok:
            remember_text(fallback_tweet, state)
        save_state(state)
        return

    # 2) Seen filtresi uygula
    candidates = filter_projects(projects, state)

    # 3) Taze aday yoksa: Radar fallback (watchlist değil)
    if not candidates:
        # mümkünse state'e göre en eski görüleni seçerek çeşitliliği artır
        def last_seen_days(p: Dict[str, str]) -> int:
            u = (p.get("url") or "").strip()
            last = state["seen_projects"].get(u, "")
            return days_ago(last) if last else 9999

        pool = sorted(projects, key=last_seen_days, reverse=True)
        project = random.choice(pool[:20]) if pool else random.choice(projects)

        project["url"] = normalize_url(project.get("url", ""))
        url = project.get("url", "").strip()

        tweet, caption = ai_research_tweet(project, section_label)
        if url:
            tweet = enforce_3_lines_and_url(tweet, url)
        else:
            tweet = tweet[:240]

        ok = tweet_with_optional_image(
            tweet_text=tweet,
            title=project.get("name", "Radar"),
            subtitle=caption or section_label,
            force_image=False,
            image_prob=0.7,
        )

        print(f"SUMMARY: attempted=1 posted={int(ok)} reason=FALLBACK_RADAR_NO_FRESH section={section}", flush=True)
        if ok:
            if url:
                remember_project(url, state)
            remember_text(tweet, state)
        save_state(state)
        return

    # 4) Normal akış
    project = random.choice(candidates)
    project["url"] = normalize_url(project.get("url", ""))
    url = project.get("url", "").strip()

    if not url:
        print(f"SUMMARY: attempted=1 posted=0 reason=URL_EMPTY_AFTER_NORMALIZE section={section}", flush=True)
        save_state(state)
        return

    tweet, caption = ai_research_tweet(project, section_label)
    tweet = enforce_3_lines_and_url(tweet, url)

    if is_duplicate_text(tweet, state):
        tweet2, caption2 = ai_research_tweet(project, section_label)
        tweet2 = enforce_3_lines_and_url(tweet2, url)
        if not is_duplicate_text(tweet2, state):
            tweet, caption = tweet2, caption2
        else:
            print(f"SUMMARY: attempted=1 posted=0 reason=DUPLICATE_TEXT_AFTER_RETRY section={section}", flush=True)
            save_state(state)
            return

    ok = tweet_with_optional_image(
        tweet_text=tweet,
        title=project.get("name", "New Project"),
        subtitle=caption or section_label,
        force_image=False,
        image_prob=0.7,
    )

    if not ok:
        # 1 retry (yeni metin)
        tweet2, caption2 = ai_research_tweet(project, section_label)
        tweet2 = enforce_3_lines_and_url(tweet2, url)

        ok = tweet_with_optional_image(
            tweet_text=tweet2,
            title=project.get("name", "New Project"),
            subtitle=caption2 or section_label,
            force_image=False,
            image_prob=0.7,
        )
        if ok:
            tweet, caption = tweet2, caption2

    if not ok:
        print(f"SUMMARY: attempted=1 posted=0 reason=POST_FAILED_AFTER_RETRY section={section}", flush=True)
        save_state(state)
        return

    remember_project(url, state)
    remember_text(tweet, state)
    save_state(state)
    print(f"SUMMARY: attempted=1 posted=1 reason=NORMAL section={section}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print("BOT FAILED:", str(e), flush=True)
        traceback.print_exc()
        raise
