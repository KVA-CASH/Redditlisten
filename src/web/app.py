"""
Web Dashboard Server - Flask + SocketIO for real-time Pain Point tracking.
"""

import csv
import os
import logging
from datetime import datetime, timedelta
from pathlib import Path
from threading import Thread
from typing import Optional, List, Dict

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.config import NICHES

logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__,
            template_folder='templates',
            static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'reddit-listener-secret-key')

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# CSV path
CSV_PATH = Path("data/pain_points.csv")


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def read_pain_points(limit: int = 100) -> List[Dict]:
    """Read pain points from CSV file."""
    if not CSV_PATH.exists():
        return []

    rows = []
    try:
        with open(CSV_PATH, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        logger.error(f"Error reading CSV: {e}")
        return []

    # Return most recent first
    return list(reversed(rows[-limit:]))


def get_pain_stats() -> Dict:
    """Calculate statistics from pain points CSV."""
    rows = read_pain_points(limit=10000)

    if not rows:
        return {
            'total': 0,
            'by_severity': {'SEVERE': 0, 'MODERATE': 0, 'MILD': 0},
            'by_niche': {},
            'by_keyword': {},
            'by_subreddit': {},
        }

    stats = {
        'total': len(rows),
        'by_severity': {'SEVERE': 0, 'MODERATE': 0, 'MILD': 0},
        'by_niche': {},
        'by_keyword': {},
        'by_subreddit': {},
    }

    for row in rows:
        # By severity
        severity = row.get('severity', 'MILD')
        if severity in stats['by_severity']:
            stats['by_severity'][severity] += 1

        # By niche
        niche = row.get('niche', 'Unknown')
        stats['by_niche'][niche] = stats['by_niche'].get(niche, 0) + 1

        # By keyword
        keyword = row.get('keyword', 'unknown')
        stats['by_keyword'][keyword] = stats['by_keyword'].get(keyword, 0) + 1

        # By subreddit
        subreddit = row.get('subreddit', 'unknown')
        stats['by_subreddit'][subreddit] = stats['by_subreddit'].get(subreddit, 0) + 1

    return stats


# ============================================================================
# API ROUTES
# ============================================================================

@app.route('/health')
def health():
    """Health check endpoint for Railway."""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})


@app.route('/')
def index():
    """Main dashboard page."""
    return render_template('pain_dashboard.html', niches=NICHES)


@app.route('/api/stats')
def api_stats():
    """Get overall statistics."""
    stats = get_pain_stats()

    # Sort and limit
    top_keywords = sorted(stats['by_keyword'].items(), key=lambda x: x[1], reverse=True)[:15]
    top_niches = sorted(stats['by_niche'].items(), key=lambda x: x[1], reverse=True)
    top_subreddits = sorted(stats['by_subreddit'].items(), key=lambda x: x[1], reverse=True)[:10]

    return jsonify({
        'total': stats['total'],
        'severity': stats['by_severity'],
        'keywords': [{'keyword': k, 'count': c} for k, c in top_keywords],
        'niches': [{'niche': n, 'count': c} for n, c in top_niches],
        'subreddits': [{'subreddit': s, 'count': c} for s, c in top_subreddits],
        'timestamp': datetime.now().isoformat(),
    })


@app.route('/api/pain-points')
def api_pain_points():
    """Get recent pain points."""
    limit = request.args.get('limit', 50, type=int)
    severity = request.args.get('severity', None)
    niche = request.args.get('niche', None)

    rows = read_pain_points(limit=500)

    # Filter
    if severity:
        rows = [r for r in rows if r.get('severity') == severity]
    if niche:
        rows = [r for r in rows if r.get('niche') == niche]

    return jsonify({
        'pain_points': rows[:limit],
        'total': len(rows),
    })


@app.route('/api/severe')
def api_severe():
    """Get only severe pain points."""
    rows = read_pain_points(limit=500)
    severe = [r for r in rows if r.get('severity') == 'SEVERE']
    return jsonify({
        'pain_points': severe[:50],
        'total': len(severe),
    })


# ============================================================================
# SOCKETIO EVENTS
# ============================================================================

@socketio.on('connect')
def handle_connect():
    """Handle client connection."""
    logger.info("Client connected to dashboard")
    emit('connected', {'status': 'ok', 'timestamp': datetime.now().isoformat()})


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection."""
    logger.info("Client disconnected from dashboard")


@socketio.on('request_update')
def handle_request_update(data):
    """Handle manual refresh request from client."""
    stats = get_pain_stats()
    emit('stats_update', {
        'stats': stats,
        'timestamp': datetime.now().isoformat(),
    })


def broadcast_pain_point(pain_data: dict):
    """Broadcast a new pain point to all connected clients."""
    socketio.emit('new_pain_point', {
        'pain_point': pain_data,
        'timestamp': datetime.now().isoformat(),
    })


# ============================================================================
# SERVER RUNNER
# ============================================================================

def run_server(host: str = '0.0.0.0', port: int = 5000, debug: bool = False):
    """Run the Flask-SocketIO server."""
    logger.info(f"Starting dashboard server at http://{host}:{port}")
    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)


def run_server_background(host: str = '0.0.0.0', port: int = 5000) -> Thread:
    """Run server in a background thread."""
    thread = Thread(target=run_server, args=(host, port, False), daemon=True)
    thread.start()
    logger.info(f"Dashboard server started in background at http://{host}:{port}")
    return thread
