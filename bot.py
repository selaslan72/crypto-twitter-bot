import os
import tweepy
from openai import OpenAI

# =========================
# X (Twitter) AUTH
# =========================

auth = tweepy.OAuth1UserHandler(
    consumer_key=os.environ["X_API_KEY"],
    consumer_secret=os.environ["X_API_SECRET"],
    access_token=os.environ["X_ACCESS_TOKEN"],
    access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
)

twitter = tweepy.API(auth)

# =========================
# AI (GitHub Models - FREE)
# =========================

client = OpenAI(
    base_url="https://models.github.ai/inference",
    api_key=os.environ["GITHUB_TOKEN"],
)

def generate_content():
    prompt = """
    You are a crypto Twitter account.

    Generate:
    - 3 short tweets
    - 1 short reply to a big crypto account

    Style:
    - Human
    - Casual
    - No emojis
    - No hashtags
    """

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )

    text = res.choices[0].message.content.strip().split("\n")
    tweets = [t for t in text if len(t) > 20][:3]
    reply = tweets[-1]

    return tweets, reply

def main():
    tweets, reply = generate_content()

    # 3 tweet at
    for t in tweets:
        twitter.update_status(t)

    # Büyük hesaba reply (örnek: CZ)
    cz = twitter.user_timeline(screen_name="cz_binance", count=1)[0]
    twitter.update_status(
        reply,
        in_reply_to_status_id=cz.id,
        auto_populate_reply_metadata=True
    )

if __name__ == "__main__":
    main()
