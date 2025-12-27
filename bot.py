import os
import tweepy
from openai import OpenAI

# =========
# AI (GitHub Models - FREE)
# =========
client_ai = OpenAI(
    base_url="https://models.github.ai/inference",
    api_key=os.environ["GITHUB_TOKEN"],
)

# =========
# X API (v2) - Tweepy Client
# OAuth 1.0a keys ile v2 tweet atacağız
# =========
client_x = tweepy.Client(
    consumer_key=os.environ["X_API_KEY"],
    consumer_secret=os.environ["X_API_SECRET"],
    access_token=os.environ["X_ACCESS_TOKEN"],
    access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
)

def generate_content(context: str):
    prompt = f"""
You are a crypto Twitter account.
Using the context below, generate:
- 4 short tweets (<=240 chars, no hashtags, no emojis)
- 2 short replies (<=200 chars, respectful, not spammy)

Context:
{context}

Return as JSON:
{{
  "tweets": ["...", "...", "...", "..."],
  "replies": ["...", "..."]
}}
"""
    res = client_ai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    text = res.choices[0].message.content.strip()

    import json
    try:
        data = json.loads(text)
        return data.get("tweets", [])[:4], data.get("replies", [])[:2]
    except Exception:
        # JSON bozulursa: tek metni tweet'e çevir
        return [text[:240]], []

def main():
    # “Güncel context”i şimdilik basit tutuyoruz (sonra genişletiriz).
    context = "Today’s crypto focus: liquidity, ETF flows, and narrative rotation."

    tweets, replies = generate_content(context)

    # 3-4 tweet
    posted = []
    for t in tweets:
        t = (t or "").strip()
        if t:
            resp = client_x.create_tweet(text=t)
            posted.append(resp.data["id"])

    # 1-2 reply: örnek olarak cz_binance’ın son tweet’ine reply atmaya çalışmayacağız (okuma limitleri/izinler takılmasın).
    # Şimdilik kendi attığın son tweet’e reply atalım (test için en garanti).
    if posted and replies:
        parent_id = posted[-1]
        for r in replies:
            r = (r or "").strip()
            if r:
                client_x.create_tweet(text=r, in_reply_to_tweet_id=parent_id)

if __name__ == "__main__":
    main()
