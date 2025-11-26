"""
Pain Point Analyzer Module - Context-Aware Sentiment Analysis.

This module provides:
1. HTML cleaning from Reddit RSS feeds
2. Sentence tokenization with context windows
3. VADER sentiment analysis tuned for social media
4. Pain point extraction with negative sentiment filtering
"""

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from html import unescape

from bs4 import BeautifulSoup
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# Handle SSL issues for NLTK downloads on macOS
import ssl
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

# Download NLTK data on first import (sentence tokenizer)
import nltk
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt', quiet=True)
try:
    nltk.data.find('tokenizers/punkt_tab')
except LookupError:
    nltk.download('punkt_tab', quiet=True)

from nltk.tokenize import sent_tokenize

logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

# Sentiment threshold: anything below this is considered NEGATIVE
NEGATIVE_THRESHOLD: float = -0.05

# Minimum snippet length to consider (filter out noise)
MIN_SNIPPET_LENGTH: int = 20

# Maximum snippet length for output
MAX_SNIPPET_LENGTH: int = 500


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class PainPoint:
    """A validated pain point extracted from text."""
    keyword: str
    context_snippet: str
    pain_score: float  # VADER compound score (negative = more pain)
    sentence_index: int
    full_text: str = ""

    @property
    def severity(self) -> str:
        """Categorize pain severity based on score."""
        if self.pain_score <= -0.5:
            return "SEVERE"
        elif self.pain_score <= -0.25:
            return "MODERATE"
        else:
            return "MILD"

    @property
    def severity_emoji(self) -> str:
        """Get emoji for severity level."""
        if self.pain_score <= -0.5:
            return "🔴"
        elif self.pain_score <= -0.25:
            return "🟠"
        else:
            return "🟡"


@dataclass
class AnalysisResult:
    """Complete analysis result for a piece of text."""
    original_text: str
    clean_text: str
    sentences: List[str]
    pain_points: List[PainPoint] = field(default_factory=list)
    overall_sentiment: float = 0.0

    @property
    def has_pain_points(self) -> bool:
        return len(self.pain_points) > 0

    @property
    def most_severe(self) -> Optional[PainPoint]:
        """Get the most severe pain point."""
        if not self.pain_points:
            return None
        return min(self.pain_points, key=lambda p: p.pain_score)


# ============================================================================
# PAIN ANALYZER CLASS
# ============================================================================

class PainAnalyzer:
    """
    Context-aware pain point analyzer using VADER sentiment.

    Flow:
    1. Clean HTML from Reddit RSS content
    2. Split text into sentences
    3. Search for keywords in sentences
    4. Extract context window (sentence + before + after)
    5. Analyze sentiment of context window
    6. Filter for NEGATIVE sentiment only
    """

    def __init__(self, negative_threshold: float = NEGATIVE_THRESHOLD):
        """
        Initialize the analyzer.

        Args:
            negative_threshold: Compound score below this = negative sentiment
        """
        self.negative_threshold = negative_threshold
        self.sentiment_analyzer = SentimentIntensityAnalyzer()
        logger.info(f"PainAnalyzer initialized (threshold: {negative_threshold})")

    def clean_html(self, html_content: str) -> str:
        """
        Strip HTML tags and decode entities from Reddit RSS content.

        Args:
            html_content: Raw HTML from RSS feed

        Returns:
            Clean plain text
        """
        if not html_content:
            return ""

        # Parse with BeautifulSoup
        soup = BeautifulSoup(html_content, 'lxml')

        # Remove script and style elements
        for element in soup(['script', 'style', 'head', 'meta']):
            element.decompose()

        # Get text
        text = soup.get_text(separator=' ')

        # Decode HTML entities
        text = unescape(text)

        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()

        # Remove Reddit-specific artifacts
        text = re.sub(r'\[link\]|\[comments\]', '', text, flags=re.IGNORECASE)
        text = re.sub(r'submitted by /u/\w+', '', text, flags=re.IGNORECASE)

        return text

    def split_sentences(self, text: str) -> List[str]:
        """
        Split text into sentences using NLTK.

        Args:
            text: Clean plain text

        Returns:
            List of sentences
        """
        if not text:
            return []

        try:
            sentences = sent_tokenize(text)
            # Filter out very short "sentences" (likely noise)
            sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
            return sentences
        except Exception as e:
            logger.warning(f"Sentence tokenization failed: {e}")
            # Fallback: split on common sentence endings
            sentences = re.split(r'(?<=[.!?])\s+', text)
            return [s.strip() for s in sentences if len(s.strip()) > 10]

    def get_context_window(
        self,
        sentences: List[str],
        target_index: int,
        window_size: int = 1
    ) -> Tuple[str, int, int]:
        """
        Extract a context window around a target sentence.

        Args:
            sentences: List of all sentences
            target_index: Index of the sentence containing the keyword
            window_size: Number of sentences before/after to include

        Returns:
            Tuple of (context_snippet, start_index, end_index)
        """
        start = max(0, target_index - window_size)
        end = min(len(sentences), target_index + window_size + 1)

        context = ' '.join(sentences[start:end])

        # Truncate if too long
        if len(context) > MAX_SNIPPET_LENGTH:
            context = context[:MAX_SNIPPET_LENGTH] + "..."

        return context, start, end

    def analyze_sentiment(self, text: str) -> dict:
        """
        Analyze sentiment using VADER.

        Args:
            text: Text to analyze

        Returns:
            Dict with 'neg', 'neu', 'pos', 'compound' scores
        """
        return self.sentiment_analyzer.polarity_scores(text)

    def is_negative(self, compound_score: float) -> bool:
        """Check if a compound score indicates negative sentiment."""
        return compound_score < self.negative_threshold

    def find_keyword_in_sentences(
        self,
        sentences: List[str],
        keyword: str
    ) -> List[int]:
        """
        Find all sentence indices containing a keyword.

        Args:
            sentences: List of sentences
            keyword: Keyword to search for (case-insensitive)

        Returns:
            List of sentence indices where keyword appears
        """
        indices = []
        keyword_lower = keyword.lower()

        # Also check for partial matches (e.g., "ship" in "shipping")
        keyword_pattern = re.compile(
            rf'\b{re.escape(keyword_lower)}\w*\b',
            re.IGNORECASE
        )

        for i, sentence in enumerate(sentences):
            if keyword_pattern.search(sentence):
                indices.append(i)

        return indices

    def extract_pain_points(
        self,
        text: str,
        keywords: List[str]
    ) -> AnalysisResult:
        """
        Extract all pain points from text for given keywords.

        Args:
            text: Raw text (may contain HTML)
            keywords: List of keywords to search for

        Returns:
            AnalysisResult with all found pain points
        """
        # Step 1: Clean HTML
        clean_text = self.clean_html(text)

        if not clean_text or len(clean_text) < MIN_SNIPPET_LENGTH:
            return AnalysisResult(
                original_text=text,
                clean_text=clean_text,
                sentences=[],
                pain_points=[],
                overall_sentiment=0.0
            )

        # Step 2: Split into sentences
        sentences = self.split_sentences(clean_text)

        if not sentences:
            return AnalysisResult(
                original_text=text,
                clean_text=clean_text,
                sentences=[],
                pain_points=[],
                overall_sentiment=0.0
            )

        # Step 3: Overall sentiment
        overall_scores = self.analyze_sentiment(clean_text)
        overall_sentiment = overall_scores['compound']

        # Step 4: Find pain points for each keyword
        pain_points = []
        seen_contexts = set()  # Avoid duplicate contexts

        for keyword in keywords:
            # Find sentences with this keyword
            matching_indices = self.find_keyword_in_sentences(sentences, keyword)

            for idx in matching_indices:
                # Get context window
                context, start_idx, end_idx = self.get_context_window(sentences, idx)

                # Skip if we've seen this context already
                context_hash = hash(context[:100])  # Hash first 100 chars
                if context_hash in seen_contexts:
                    continue
                seen_contexts.add(context_hash)

                # Analyze sentiment of context window
                sentiment_scores = self.analyze_sentiment(context)
                compound = sentiment_scores['compound']

                # Only keep NEGATIVE sentiment matches
                if self.is_negative(compound):
                    pain_points.append(PainPoint(
                        keyword=keyword,
                        context_snippet=context,
                        pain_score=compound,
                        sentence_index=idx,
                        full_text=clean_text
                    ))

                    logger.debug(
                        f"Pain point found: '{keyword}' (score: {compound:.3f})"
                    )

        # Sort by severity (most negative first)
        pain_points.sort(key=lambda p: p.pain_score)

        return AnalysisResult(
            original_text=text,
            clean_text=clean_text,
            sentences=sentences,
            pain_points=pain_points,
            overall_sentiment=overall_sentiment
        )

    def analyze_post(
        self,
        title: str,
        content: str,
        keywords: List[str]
    ) -> AnalysisResult:
        """
        Analyze a complete Reddit post (title + content).

        Args:
            title: Post title
            content: Post body/description
            keywords: Keywords to search for

        Returns:
            Combined AnalysisResult
        """
        # Combine title and content
        combined = f"{title}. {content}" if content else title

        return self.extract_pain_points(combined, keywords)


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_pain_analyzer() -> PainAnalyzer:
    """Get a singleton PainAnalyzer instance."""
    if not hasattr(get_pain_analyzer, '_instance'):
        get_pain_analyzer._instance = PainAnalyzer()
    return get_pain_analyzer._instance


def quick_analyze(text: str, keywords: List[str]) -> List[PainPoint]:
    """
    Quick utility to analyze text for pain points.

    Args:
        text: Text to analyze
        keywords: Keywords to search for

    Returns:
        List of PainPoint objects
    """
    analyzer = get_pain_analyzer()
    result = analyzer.extract_pain_points(text, keywords)
    return result.pain_points
