from functools import wraps
from flask import request, jsonify, redirect, url_for, session

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        print("=" * 50)
        print(f"[DEBUG] 🚩 login_required check STARTED")
        print(f"[DEBUG] Endpoint: {request.endpoint}")
        print(f"[DEBUG] Path: {request.path}")
        print(f"[DEBUG] Query string: {request.query_string.decode()}")
        print(f"[DEBUG] Session keys: {list(session.keys())}")
        print(f"[DEBUG] User in session? {'user' in session}")
        print(f"[DEBUG] X-Requested-With: {request.headers.get('X-Requested-With')}")
        
        if 'user' not in session:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                print("[DEBUG] 🟠 AJAX request → sending JSON error 401")
                print("=" * 50)
                return jsonify({'error': 'Not authenticated'}), 401
            print("[DEBUG] 🔴 Non-AJAX request → redirecting to login page")
            print("=" * 50)
            return redirect(url_for('login'))

        print("[DEBUG] ✅ User authenticated → proceeding to view function")
        print("=" * 50)
        return f(*args, **kwargs)
    return decorated_function
