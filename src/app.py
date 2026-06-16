from flask import Flask, jsonify, render_template, request
import logging
import sys
import sqlite3
import os
import subprocess
from contextlib import closing
from data_service import get_all_data, get_power_ranking, get_player_ratings

app = Flask(__name__, static_folder='static', template_folder='templates')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
)
logger = logging.getLogger(__name__)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/data')
def api_data():
    try:
        data = get_all_data()
        return jsonify({"status": "success", "data": data})
    except Exception as e:
        logger.error("Error fetching data: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/trigger_scrape', methods=['POST'])
def api_trigger_scrape():
    try:
        logger.info("Manual scrape triggered by client.")
        result = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(__file__), "scrape_and_store.py"), "--mode", "update"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            logger.info("Trigger scrape completed successfully.")
            return jsonify({
                "status": "success",
                "message": "Scrape completed successfully.",
            })
        elif result.returncode == 2:
            logger.warning("Trigger scrape blocked by safety gate.")
            return jsonify({
                "status": "blocked",
                "message": "Data overwrite blocked by safety gate.",
                "details": result.stdout.strip(),
            }), 409
        else:
            logger.error("Scraper failed: %s", result.stderr)
            return jsonify({
                "status": "error",
                "message": "Scraper encountered an error.",
                "details": result.stderr.strip(),
            }), 500
    except subprocess.TimeoutExpired:
        logger.error("Trigger scrape timed out after 120s.")
        return jsonify({
            "status": "error",
            "message": "Scrape timed out. Server may be under load or blocked.",
        }), 504
    except Exception as e:
        logger.error("Exception triggering scrape: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/power_ranking')
def api_power_ranking():
    try:
        ranking = get_power_ranking()
        return jsonify({"status": "success", "ranking": ranking})
    except Exception as e:
        logger.error("Error computing power ranking: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/player_ratings')
def api_player_ratings():
    try:
        result = get_player_ratings()
        return jsonify({
            "status": "success",
            "ratings": result['ratings'],
            "ranking": result['ranking'],
        })
    except Exception as e:
        logger.error("Error computing player ratings: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'GET':
        try:
            with closing(sqlite3.connect(os.path.join(os.path.dirname(__file__), '..', 'worldcup2026.db'))) as conn:
                cur = conn.execute("SELECT key, value FROM Settings")
                settings = {row[0]: row[1] for row in cur.fetchall()}
            return jsonify({"status": "success", "settings": settings})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    if request.method == 'POST':
        try:
            data = request.get_json()
            interval = int(data.get('refresh_interval', 5))
            interval = max(1, min(interval, 60))  # clamp 1-60 minutes
            with closing(sqlite3.connect(os.path.join(os.path.dirname(__file__), '..', 'worldcup2026.db'))) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO Settings (key, value) VALUES (?, ?)",
                    ('refresh_interval', str(interval)),
                )
                conn.commit()
            return jsonify({
                "status": "success",
                "settings": {"refresh_interval": str(interval)},
            })
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == '__main__':
    logger.info("Starting World Cup 2026 Aggregator Server...")
    app.run(host='0.0.0.0', port=5000, debug=False)
