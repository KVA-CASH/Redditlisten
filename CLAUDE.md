# Reddit Pain Point Sniper 🎯

## Project Overview

A **real-time Reddit monitoring system** that uses sentiment analysis to find genuine business opportunities by detecting user frustrations and pain points. Built for entrepreneurs looking to validate product ideas by finding people actively complaining about problems.

---

## What It Does

1. **Monitors Reddit RSS feeds** across 5 B2B niches (15+ subreddits)
2. **Analyzes sentiment** using VADER (tuned for social media)
3. **Filters for negative sentiment only** (scores < -0.05) to find real pain
4. **Extracts context windows** around pain keywords
5. **Logs to CSV** for analysis and exports to web dashboard
6. **Real-time dashboard** with Socket.IO for live updates

---

## Architecture

```
RedditListener/
├── main.py                 # Entry point - CLI + dashboard launcher
├── src/
│   ├── config.py           # Niche definitions, keywords, subreddits
│   ├── rss_listener.py     # RSS polling with UA rotation + retry logic
│   ├── pain_analyzer.py    # VADER sentiment + context extraction
│   ├── pain_logger.py      # CSV logging
│   └── web/
│       ├── app.py          # Flask + Socket.IO server
│       └── templates/
│           └── pain_dashboard.html  # Real-time dashboard UI
├── data/
│   ├── pain_points.csv     # Collected pain points (main output)
│   └── seen_posts.json     # Deduplication tracker
├── Procfile                # Railway deployment
└── railway.json            # Railway config with healthcheck
```

---

## Key Features

### Pain Score System
- **SEVERE** (< -0.5): Extreme frustration - immediate opportunity
- **MODERATE** (-0.5 to -0.25): Significant pain - worth investigating
- **MILD** (-0.25 to -0.05): Minor complaints - context needed

### 5 Monitored Niches
1. **Sweaty_Startup** - Small service businesses (cleaning, landscaping, HVAC)
2. **Agency_Owners** - Digital agencies, marketing firms
3. **Ecommerce_Ops** - Dropshipping, fulfillment, inventory
4. **Content_Creators** - YouTubers, podcasters, streamers
5. **Recruiters** - Staffing, HR tech, hiring

### Dashboard Features
- Live pain point feed with severity color coding
- Filter by severity (Severe/Moderate/All)
- Sort by "Most Painful" (lowest scores first)
- Top pain keywords chart
- Subreddit breakdown
- Niche distribution

---

## Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Run with dashboard (default port 8080)
python3 main.py --port 8080

# View stats only
python3 main.py --stats

# View recent CSV entries
python3 main.py --csv

# Fresh start (clear seen posts)
python3 main.py --reset
```

Dashboard: http://localhost:8080

---

## Deployment (Railway)

Currently deployed at: `https://web-production-4d596.up.railway.app`

**To redeploy after changes:**
```bash
git add -A && git commit -m "Description" && git push origin main
```

Railway auto-deploys on push. Key config:
- Healthcheck endpoint: `/health`
- Server binds to `0.0.0.0` (required for Railway)
- Timeout: 300 seconds

---

## Future Improvements

### Data & Analysis
- [ ] Add engagement metrics (upvotes, comments) to prioritize hot topics
- [ ] Implement trend detection (pain points increasing over time)
- [ ] Export to Google Sheets or Notion
- [ ] Email/Slack alerts for SEVERE pain points

### Filtering
- [ ] Exclude low-engagement posts option
- [ ] Add date range filtering
- [ ] Custom keyword lists per session
- [ ] Competitor mention tracking

### Dashboard
- [ ] Charts showing pain trends over time
- [ ] Click to expand full post context
- [ ] Save/favorite promising pain points
- [ ] Notes field for each pain point

### Technical
- [ ] PostgreSQL for persistent storage (Railway addon)
- [ ] Rate limiting improvements for Reddit
- [ ] Multi-user support with auth
- [ ] API for external integrations

---

## Key Files to Edit

| Task | File |
|------|------|
| Add new niche/subreddits | `src/config.py` - NICHES dict |
| Change pain keywords | `src/config.py` - search_query per niche |
| Adjust sentiment thresholds | `src/pain_analyzer.py` |
| Modify dashboard UI | `src/web/templates/pain_dashboard.html` |
| Add API endpoints | `src/web/app.py` |
| Change polling interval | `src/config.py` - POLL_INTERVAL_MIN/MAX |

---

## Important Notes

- **Reddit blocks multi-subreddit RSS feeds** - we poll each subreddit individually
- **Using old.reddit.com** for RSS (more lenient than www)
- **User-agent rotation** to avoid 403 blocks
- **Data doesn't persist on Railway restart** - CSV starts fresh each deploy
- **Free tier: 500 hours/month** (~20 days continuous)

---

## GitHub Repo

https://github.com/KVA-CASH/Redditlisten.git

---

*Last updated: 2025-11-26*
