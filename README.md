# 🔍 Reddit Pain Point Listener

A high-signal Reddit listener bot for B2B startup idea validation. Monitors 5 strategic niches in real-time and alerts you to pain points and opportunities.

## Features

- **Real-time Monitoring**: Listens to 20+ subreddits across 5 B2B niches
- **Smart Filtering**: Ignores AutoModerator, stickied posts, and duplicates
- **Beautiful Console Output**: Rich terminal UI with color-coded notifications
- **Webhook Support**: Discord and Slack integrations ready to go
- **Resilient**: Auto-reconnects on network errors with exponential backoff
- **Efficient**: Uses multi-reddit streams to minimize API calls

## Target Niches

| Niche | Focus | Example Keywords |
|-------|-------|------------------|
| 🔧 Sweaty Startup | Service businesses | paperwork, scheduling nightmare, invoicing mess |
| 📊 Agency Owners | Marketing/Web agencies | client onboarding, scope creep, chasing clients |
| 🛒 E-commerce Ops | Online stores | inventory sync, too many apps, shipping rates |
| 🎬 Content Creators | YouTubers/Streamers | editing takes forever, premiere crash |
| 👔 Recruiters | HR/Recruiting | clunky ats, resume parsing, manual entry |

## Quick Start

### 1. Get Reddit API Credentials

1. Go to https://www.reddit.com/prefs/apps
2. Click "Create App" or "Create Another App"
3. Select "script" as the app type
4. Note your `client_id` (under the app name) and `client_secret`

### 2. Setup Environment

```bash
# Clone and enter directory
cd RedditListener

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and edit environment file
cp .env.example .env
# Edit .env with your credentials
```

### 3. Run the Bot

```bash
python main.py
```

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `REDDIT_CLIENT_ID` | Yes | Reddit app client ID |
| `REDDIT_CLIENT_SECRET` | Yes | Reddit app secret |
| `REDDIT_USER_AGENT` | Yes | Custom user agent string |
| `DISCORD_WEBHOOK_URL` | No | Discord webhook for notifications |
| `ENABLE_DISCORD_NOTIFICATIONS` | No | Set to `true` to enable Discord |

### Customizing Niches

Edit `src/config.py` to modify the `NICHES` dictionary:

```python
NICHES = {
    "Your_Niche": {
        "subreddits": "sub1+sub2+sub3",
        "keywords": ["keyword1", "keyword2", "pain point phrase"]
    }
}
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        main.py                              │
│  • Startup banner & config validation                       │
│  • Signal handling (graceful shutdown)                      │
│  • Orchestrates listener + dispatcher                       │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌─────────────────────────┐     ┌─────────────────────────────┐
│     listener.py         │     │       notifier.py           │
│  • PRAW stream handling │────▶│  • Console (Rich)           │
│  • Keyword matching     │     │  • Discord webhook          │
│  • Post deduplication   │     │  • Slack webhook            │
│  • Auto-reconnect       │     │  • Custom notification hook │
└─────────────────────────┘     └─────────────────────────────┘
              │
              ▼
┌─────────────────────────┐
│       config.py         │
│  • Niche definitions    │
│  • Environment loading  │
│  • App settings         │
└─────────────────────────┘
```

### Why Multi-Reddit Instead of Threading?

PRAW's stream implementation is blocking, which typically requires threading for multiple streams. However, this approach has drawbacks:

1. **API Rate Limits**: Reddit limits to ~60 requests/minute. Multiple streams = faster limit exhaustion
2. **Complexity**: Thread management, synchronization, and error handling add complexity
3. **Redundancy**: Many subreddits overlap between niches

**Our Solution**: Use Reddit's multi-reddit feature (`sub1+sub2+sub3`) to create a single stream that monitors all subreddits. Then filter and categorize posts by niche in our code. This is:
- More API-efficient (single stream)
- Simpler (no threading required)
- Equally responsive (same real-time data)

## File Structure

```
RedditListener/
├── main.py              # Entry point
├── requirements.txt     # Dependencies
├── .env.example         # Environment template
├── README.md            # This file
├── logs/                # Log files
│   └── reddit_listener.log
└── src/
    ├── __init__.py
    ├── config.py        # Configuration & niches
    ├── listener.py      # PRAW stream handler
    └── notifier.py      # Notification dispatchers
```

## Adding Custom Notifications

Edit the `send_notification()` function in `src/notifier.py`:

```python
def send_notification(post: MatchedPost) -> None:
    # Example: Send to Telegram
    telegram_bot.send_message(
        chat_id=MY_CHAT_ID,
        text=f"New pain point in {post.niche}: {post.full_url}"
    )

    # Example: Log to database
    db.insert("matched_posts", {
        "post_id": post.id,
        "niche": post.niche,
        "keywords": post.matched_keywords,
        "url": post.full_url,
    })
```

## Tips for Effective Use

1. **Engage Quickly**: Pain points are time-sensitive. Check notifications promptly.
2. **Add Value First**: Don't pitch immediately. Offer genuine help.
3. **Track Patterns**: Notice recurring pain points - these are product opportunities.
4. **Refine Keywords**: Add new pain point phrases as you discover them.
5. **Monitor Volume**: If too noisy, narrow keywords. If too quiet, broaden them.

## License

MIT License - Use freely for your startup validation journey!
