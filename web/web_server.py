"""
PhuongAnh TTS - Web Server
Simple Flask server to serve the frontend pages.
"""
import os
import requests
from flask import Flask, render_template, send_from_directory, jsonify, request, redirect
from flask_cors import CORS

app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)

# Disable template caching for development
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

# Get the directory of this file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Backend API URL
BACKEND_URL = os.getenv('BACKEND_URL', 'http://localhost:8000')


@app.route('/')
def index():
    """Home page."""
    return render_template('index.html')


@app.route('/about')
def about():
    """About page."""
    return render_template('about.html')


@app.route('/finance')
def finance():
    """Finance/Dashboard page."""
    return render_template('finance.html')


@app.route('/tts')
def tts():
    """TTS page."""
    return render_template('tts.html')


@app.route('/login')
def login():
    """Login page."""
    return render_template('login.html')


@app.route('/register')
def register():
    """Register page."""
    return render_template('register.html')


@app.route('/admin')
def admin():
    """Admin dashboard page."""
    return render_template('admin.html')


@app.route('/test_admin')
def test_admin():
    """Test Admin API page."""
    return render_template('test_admin.html')


@app.route('/autologin')
def autologin():
    """Auto login page for admin."""
    return render_template('autologin.html')


@app.route('/profile')
def profile():
    """User profile page."""
    return render_template('profile.html')


@app.route('/pricing')
def pricing():
    """Pricing page."""
    return render_template('pricing.html')


@app.route('/payment')
def payment():
    """Payment page."""
    return render_template('payment.html')


@app.route('/static/<path:path>')
def static_files(path):
    """Serve static files with no cache headers."""
    response = send_from_directory('static', path)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/health')
def health():
    """Health check endpoint."""
    return jsonify({'status': 'ok', 'service': 'phuonganh-tts-web'})


if __name__ == '__main__':
    port = int(os.getenv('PORT', 3000))
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)


def main():
    """Entry point for the script."""
    port = int(os.getenv('PORT', 3000))
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    print(f"Starting PhuongAnh TTS Web Server on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=debug)
