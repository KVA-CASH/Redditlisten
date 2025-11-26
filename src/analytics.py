"""
Analytics Module - Smart insights and recommendations from stored data.
Analyzes trends, generates recommendations, and provides actionable insights.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

from .storage import PostStorage
from .config import NICHES, extract_keywords_from_query

logger = logging.getLogger(__name__)
console = Console()


class TrendDirection(Enum):
    """Trend direction indicators."""
    UP = "🔥"
    STABLE = "➡️"
    DOWN = "📉"
    NEW = "✨"


@dataclass
class Insight:
    """A single actionable insight."""
    category: str
    title: str
    description: str
    priority: int  # 1-5, 5 being highest
    data: Dict


@dataclass
class Recommendation:
    """A recommendation based on data analysis."""
    niche: str
    pain_point: str
    frequency: int
    trend: TrendDirection
    confidence: float  # 0-1
    supporting_posts: int
    action: str


class AnalyticsEngine:
    """
    Analyzes stored post data to generate insights and recommendations.
    """

    def __init__(self, storage: PostStorage):
        self.storage = storage

    def get_top_pain_points(self, days: int = 7, min_occurrences: int = 2) -> List[Dict]:
        """
        Get the most mentioned pain points (keywords) across all niches.

        Returns:
            List of pain points with frequency and trend data
        """
        keyword_freq = self.storage.get_keyword_frequency(days=days, limit=30)
        trending = self.storage.get_trending_keywords(recent_days=1, baseline_days=days)
        trending_map = {t["keyword"]: t for t in trending}

        pain_points = []
        for keyword, count in keyword_freq:
            if count < min_occurrences:
                continue

            trend_data = trending_map.get(keyword, {})
            trend_score = trend_data.get("trend_score", 1.0)

            if trend_score > 2.0:
                direction = TrendDirection.UP
            elif trend_score < 0.5:
                direction = TrendDirection.DOWN
            elif trend_data.get("baseline_avg", 0) == 0:
                direction = TrendDirection.NEW
            else:
                direction = TrendDirection.STABLE

            pain_points.append({
                "keyword": keyword,
                "count": count,
                "trend": direction,
                "trend_score": trend_score,
            })

        return pain_points

    def get_hottest_niches(self, days: int = 7) -> List[Dict]:
        """
        Rank niches by activity level and trend.

        Returns:
            List of niches with activity metrics
        """
        niche_freq = self.storage.get_niche_frequency(days=days)
        total = sum(count for _, count in niche_freq)

        niches = []
        for niche, count in niche_freq:
            share = (count / total * 100) if total > 0 else 0
            niches.append({
                "niche": niche,
                "posts": count,
                "share": round(share, 1),
            })

        return niches

    def generate_recommendations(self, days: int = 7) -> List[Recommendation]:
        """
        Generate actionable recommendations based on data analysis.

        Returns:
            List of prioritized recommendations
        """
        recommendations = []

        # Get data
        pain_points = self.get_top_pain_points(days=days)
        niche_data = self.get_hottest_niches(days=days)
        subreddit_freq = self.storage.get_subreddit_frequency(days=days, limit=10)

        # Map pain points to niches
        keyword_to_niche = {}
        for niche_name, niche_config in NICHES.items():
            # Extract keywords from search_query (new RSS format)
            search_query = niche_config.get("search_query", "")
            keywords = extract_keywords_from_query(search_query)
            for kw in keywords:
                keyword_to_niche[kw.lower()] = niche_name

        # Generate recommendations from top pain points
        for pp in pain_points[:10]:
            keyword = pp["keyword"]
            niche = keyword_to_niche.get(keyword, "Unknown")

            # Determine confidence based on count and trend
            base_confidence = min(pp["count"] / 10, 0.8)
            trend_bonus = 0.2 if pp["trend"] == TrendDirection.UP else 0
            confidence = min(base_confidence + trend_bonus, 1.0)

            # Generate action based on trend
            if pp["trend"] == TrendDirection.UP:
                action = f"🔥 HOT: '{keyword}' is trending UP. Consider building a solution NOW."
            elif pp["trend"] == TrendDirection.NEW:
                action = f"✨ NEW: '{keyword}' is emerging. Monitor closely for validation."
            else:
                action = f"📊 STEADY: '{keyword}' is a consistent pain point. Solid opportunity."

            recommendations.append(Recommendation(
                niche=niche,
                pain_point=keyword,
                frequency=pp["count"],
                trend=pp["trend"],
                confidence=confidence,
                supporting_posts=pp["count"],
                action=action,
            ))

        # Sort by confidence and trend
        recommendations.sort(
            key=lambda r: (
                r.trend == TrendDirection.UP,
                r.confidence,
                r.frequency
            ),
            reverse=True
        )

        return recommendations

    def generate_insights(self, days: int = 7) -> List[Insight]:
        """
        Generate high-level insights from the data.

        Returns:
            List of insights sorted by priority
        """
        insights = []
        total_posts = self.storage.get_total_posts()

        if total_posts == 0:
            insights.append(Insight(
                category="Status",
                title="No Data Yet",
                description="Start the listener to begin collecting pain point data.",
                priority=5,
                data={}
            ))
            return insights

        # Insight: Hottest niche
        niches = self.get_hottest_niches(days=days)
        if niches:
            hottest = niches[0]
            insights.append(Insight(
                category="Niche Activity",
                title=f"{hottest['niche'].replace('_', ' ')} is Most Active",
                description=f"{hottest['posts']} posts ({hottest['share']}% of total) in the last {days} days.",
                priority=4,
                data={"niches": niches}
            ))

        # Insight: Trending keywords
        trending = self.storage.get_trending_keywords(recent_days=1, baseline_days=days)
        if trending:
            top_trending = trending[0]
            insights.append(Insight(
                category="Trending",
                title=f"'{top_trending['keyword']}' is Spiking",
                description=f"{top_trending['trend_score']}x above baseline. {top_trending['recent_count']} mentions today.",
                priority=5,
                data={"trending": trending[:5]}
            ))

        # Insight: Most active subreddits
        subreddits = self.storage.get_subreddit_frequency(days=days, limit=5)
        if subreddits:
            top_sub = subreddits[0]
            insights.append(Insight(
                category="Subreddits",
                title=f"r/{top_sub[0]} is Most Active",
                description=f"{top_sub[1]} matched posts. Consider focusing engagement here.",
                priority=3,
                data={"subreddits": subreddits}
            ))

        # Insight: Best posting times
        hourly = self.storage.get_hourly_distribution(days=days)
        if hourly:
            best_hour = max(hourly.items(), key=lambda x: x[1])
            insights.append(Insight(
                category="Timing",
                title=f"Peak Activity at {best_hour[0]:02d}:00",
                description=f"{best_hour[1]} posts captured at this hour. Best time to engage.",
                priority=2,
                data={"hourly": hourly}
            ))

        # Sort by priority
        insights.sort(key=lambda i: i.priority, reverse=True)
        return insights

    def print_dashboard(self, days: int = 7) -> None:
        """
        Print a comprehensive analytics dashboard to the console.
        """
        console.print()
        console.print(Panel(
            Text("📊 Pain Point Analytics Dashboard", style="bold cyan"),
            box=box.DOUBLE,
            border_style="cyan",
        ))
        console.print()

        total_posts = self.storage.get_total_posts()
        console.print(f"[dim]Total posts in database: [bold]{total_posts}[/bold] | Analyzing last {days} days[/dim]")
        console.print()

        # ===== TOP PAIN POINTS =====
        pain_points = self.get_top_pain_points(days=days)
        if pain_points:
            pp_table = Table(
                title="🎯 Top Pain Points",
                box=box.ROUNDED,
                show_header=True,
                header_style="bold magenta",
            )
            pp_table.add_column("Rank", justify="center", width=6)
            pp_table.add_column("Pain Point", style="bold")
            pp_table.add_column("Mentions", justify="right")
            pp_table.add_column("Trend", justify="center")

            for i, pp in enumerate(pain_points[:10], 1):
                trend_icon = pp["trend"].value
                count_style = "green" if pp["count"] >= 5 else "yellow" if pp["count"] >= 3 else "dim"
                pp_table.add_row(
                    str(i),
                    pp["keyword"],
                    f"[{count_style}]{pp['count']}[/{count_style}]",
                    trend_icon,
                )

            console.print(pp_table)
            console.print()

        # ===== NICHE BREAKDOWN =====
        niches = self.get_hottest_niches(days=days)
        if niches:
            niche_table = Table(
                title="🏷️ Niche Activity",
                box=box.ROUNDED,
                show_header=True,
                header_style="bold blue",
            )
            niche_table.add_column("Niche", style="bold")
            niche_table.add_column("Posts", justify="right")
            niche_table.add_column("Share", justify="right")
            niche_table.add_column("Bar", width=20)

            max_posts = max(n["posts"] for n in niches) if niches else 1
            for niche in niches:
                bar_len = int((niche["posts"] / max_posts) * 20)
                bar = "█" * bar_len + "░" * (20 - bar_len)
                niche_table.add_row(
                    niche["niche"].replace("_", " "),
                    str(niche["posts"]),
                    f"{niche['share']}%",
                    f"[cyan]{bar}[/cyan]",
                )

            console.print(niche_table)
            console.print()

        # ===== RECOMMENDATIONS =====
        recommendations = self.generate_recommendations(days=days)
        if recommendations:
            console.print(Panel(
                Text("💡 Recommendations", style="bold green"),
                box=box.ROUNDED,
                border_style="green",
            ))
            console.print()

            for i, rec in enumerate(recommendations[:5], 1):
                confidence_bar = "●" * int(rec.confidence * 5) + "○" * (5 - int(rec.confidence * 5))
                console.print(f"  [{rec.trend.value}] [bold]{rec.pain_point}[/bold]")
                console.print(f"      Niche: [cyan]{rec.niche.replace('_', ' ')}[/cyan] | "
                            f"Mentions: [yellow]{rec.frequency}[/yellow] | "
                            f"Confidence: [{confidence_bar}]")
                console.print(f"      [dim italic]{rec.action}[/dim italic]")
                console.print()

        # ===== INSIGHTS =====
        insights = self.generate_insights(days=days)
        if insights and total_posts > 0:
            console.print(Panel(
                Text("🔍 Key Insights", style="bold yellow"),
                box=box.ROUNDED,
                border_style="yellow",
            ))
            console.print()

            for insight in insights[:4]:
                console.print(f"  [bold]{insight.title}[/bold]")
                console.print(f"  [dim]{insight.description}[/dim]")
                console.print()

    def get_summary_stats(self, days: int = 7) -> Dict:
        """
        Get summary statistics for the period.

        Returns:
            Dictionary of key metrics
        """
        return {
            "total_posts": self.storage.get_total_posts(),
            "top_keywords": self.storage.get_keyword_frequency(days=days, limit=5),
            "top_niches": self.storage.get_niche_frequency(days=days),
            "top_subreddits": self.storage.get_subreddit_frequency(days=days, limit=5),
            "trending": self.storage.get_trending_keywords(recent_days=1, baseline_days=days),
        }
