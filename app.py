from flask import Flask, render_template, request, redirect, url_for, session, flash
import os
import subprocess
import psutil
from auth_utils import login_required
import json
import shutil
from datetime import timedelta
import threading
import time
import socket
import signal
import pwd

from filebrowser import filebrowser_bp, render_tree
import simplepam  # pip install simplepam

app = Flask(__name__)
app.secret_key = '0d74f8f5980fdad23853541e6c6c82bccf82d14c04bd56ac3713974f6e773987'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

app.jinja_env.globals['render_tree'] = render_tree
app.register_blueprint(filebrowser_bp)

WEBAPPS_DIR = "/opt/webapps"
DATA_FILE = "/opt/webapps/webapp-panel/projects.json"
VENV_PYTHON = "/opt/webapps/webapp-panel/venv/bin/python"
projects = {}

if os.path.exists(DATA_FILE):
    with open(DATA_FILE, 'r') as f:
        loaded = json.load(f)
        for name, info in loaded.items():
            projects[name] = {'port': info['port'], 'process': None, 'backend_process': None}

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if simplepam.authenticate(username, password):
            session['user'] = username
            session.permanent = True
            print(f"[DEBUG] User '{username}' logged in")
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="Invalid credentials")
    return render_template('login.html', os=os)

@app.route('/logout')
def logout():
    print(f"[DEBUG] User '{session.get('user')}' logged out")
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    print(f"[DEBUG] Rendering dashboard for user: {session.get('user')}")
    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory().percent
    uptime_seconds = psutil.boot_time()
    uptime = f"{int((time.time() - uptime_seconds)//3600)}h"

    ports_info = "\n".join(
        f"{c.laddr.ip}:{c.laddr.port} - {c.pid}"
        for c in psutil.net_connections() if c.status == 'LISTEN'
    )

    procs_info = ""
    for p in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if any('/opt/webapps' in cmd for cmd in p.info['cmdline']):
                procs_info += f"PID {p.pid}: {' '.join(p.info['cmdline'])}\n"
        except Exception:
            continue

    for name, info in projects.items():
        folder = os.path.join(WEBAPPS_DIR, name)
        info['has_backend'] = os.path.exists(os.path.join(folder, 'backend.py'))

    users = [u.pw_name for u in pwd.getpwall() if u.pw_uid >= 1000 and '/home/' in u.pw_dir]

    # ✅ Explicit parent_path for Jinja
    parent_path = ""
    return render_template('dashboard.html',
                           cpu=cpu,
                           ram=ram,
                           os=os,
                           uptime=uptime,
                           projects=projects,
                           server_ip=request.host.split(':')[0],
                           ports_info=ports_info,
                           procs_info=procs_info,
                           users=users,
                           parent_path=parent_path)

@app.route('/delete_user/<username>', methods=['POST'])
@login_required
def delete_user(username):
    if username == "jimenero":
        flash("User 'jimenero' cannot be deleted!", "warning")
        return redirect(url_for('index'))
    try:
        subprocess.check_call(['sudo', 'deluser', '--remove-home', username])
        flash(f"User {username} deleted successfully!", "success")
    except subprocess.CalledProcessError as e:
        flash(f"Failed to delete user {username}: {e}", "danger")
    return redirect(url_for('index'))

@app.route('/users')
@login_required
def users():
    try:
        with open('/etc/passwd', 'r') as f:
            all_users = []
            for line in f:
                parts = line.split(':')
                username = parts[0]
                uid = int(parts[2])
                if uid >= 1000 and username != 'nobody':
                    all_users.append(username)

        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory().percent
        uptime_seconds = psutil.boot_time()
        uptime = f"{int((time.time() - uptime_seconds)//3600)}h"
        ports_info = "\n".join(f"{c.laddr.ip}:{c.laddr.port} - {c.pid}" for c in psutil.net_connections() if c.status == 'LISTEN')
        procs_info = ""
        for p in psutil.process_iter(['pid','name','cmdline']):
            try:
                if any('/opt/webapps' in cmd for cmd in p.info['cmdline']):
                    procs_info += f"PID {p.pid}: {' '.join(p.info['cmdline'])}\n"
            except Exception:
                continue

        parent_path = ""

        return render_template('users.html',
                               users=all_users,
                               cpu=cpu, ram=ram, uptime=uptime,
                               projects=projects, os=os,
                               server_ip=request.host.split(':')[0],
                               ports_info=ports_info,
                               procs_info=procs_info,
                               parent_path=parent_path)
    except Exception as e:
        return f"💥 Error: {e}", 500

@app.route('/create', methods=['POST'])
@login_required
def create_project():
    name = request.form['name']
    port_str = request.form['port']
    if not port_str.isdigit():
        return f"Invalid port number: {port_str}", 400
    port = int(port_str)
    folder = os.path.join(WEBAPPS_DIR, name)
    os.makedirs(folder, exist_ok=True)

    frontend_file = os.path.join(folder, 'index.html')
    if not os.path.exists(frontend_file):
        with open(frontend_file, 'w') as f:
            f.write(f"""<!DOCTYPE html><html><head><title>{name} Frontend</title></head><body>
<h1>{name} Frontend</h1><button onclick="callBackend()">Call Backend</button>
<script>
function callBackend() {{
    fetch('http://{request.host.split(':')[0]}:{port+1}/api/data')
    .then(res => res.json()).then(data => alert(data.message))
    .catch(err => console.error(err));
}}
</script></body></html>""")

    backend_file = os.path.join(folder, 'backend.py')
    if not os.path.exists(backend_file):
        with open(backend_file, 'w') as f:
            f.write(f"""#!/usr/bin/env {VENV_PYTHON}
from flask import Flask, jsonify
from flask_cors import CORS
app = Flask(__name__)
CORS(app)
@app.route('/api/data')
def data():
    return jsonify(message="Hello from {name} backend!")
if __name__ == '__main__':
    from waitress import serve
    print("[backend] Starting backend server on 0.0.0.0:{port+1}")
    serve(app, host='0.0.0.0', port={port+1})
""")
        os.chmod(backend_file, 0o755)

    projects[name] = {'port': port, 'process': None, 'backend_process': None}
    save_projects()
    return redirect(url_for('index'))

@app.route('/start_site/<name>')
@login_required
def start_site(name):
    start_project(name)
    start_backend(name)
    return redirect(url_for('index'))

@app.route('/stop_site/<name>')
@login_required
def stop_site(name):
    stop_project(name)
    stop_backend(name)
    return redirect(url_for('index'))

@app.route('/delete/<name>')
@login_required
def delete_project(name):
    stop_project(name)
    stop_backend(name)
    folder = os.path.join(WEBAPPS_DIR, name)
    if os.path.exists(folder): shutil.rmtree(folder)
    if name in projects: del projects[name]; save_projects()
    return redirect(url_for('index'))

@app.route('/filemanager')
@login_required
def filemanager():
    return "<h1>File Manager placeholder</h1>"

@app.route('/create_user', methods=['POST'])
@login_required
def create_user():
    username = request.form['username']
    password = request.form['password']
    try:
        subprocess.check_call(['sudo', 'adduser', '--disabled-password', '--gecos', '""', username])
        subprocess.check_call(['echo', f"{username}:{password}", '|', 'sudo', 'chpasswd'])
        flash(f"User {username} created successfully!", "success")
    except subprocess.CalledProcessError as e:
        flash(f"Failed to create user: {e}", "danger")
    return redirect(url_for('index'))

@app.route('/update_user/<username>', methods=['POST'])
@login_required
def update_user(username):
    new_password = request.form['new_password']
    try:
        subprocess.check_call(['sudo', 'chpasswd'], input=f"{username}:{new_password}".encode())
        flash(f"Password updated for {username}!", "success")
    except subprocess.CalledProcessError as e:
        flash(f"Failed to update password for {username}: {e}", "danger")
    return redirect(url_for('index'))

def save_projects():
    json_data = {name: {'port': info['port']} for name, info in projects.items()}
    with open(DATA_FILE, 'w') as f:
        json.dump(json_data, f)

def stream_process_output(proc, prefix):
    def reader(pipe):
        for line in iter(pipe.readline, ''):
            if line:
                print(f"[{prefix}] {line.rstrip()}")
    threading.Thread(target=reader, args=(proc.stdout,), daemon=True).start()
    threading.Thread(target=reader, args=(proc.stderr,), daemon=True).start()

def start_project(name):
    folder = os.path.join(WEBAPPS_DIR, name)
    port = projects[name]['port']
    for conn in psutil.net_connections():
        if conn.status == 'LISTEN' and conn.laddr.port == port:
            if conn.pid:
                try:
                    print(f"[Cleanup] Killing process {conn.pid} on port {port}")
                    psutil.Process(conn.pid).terminate()
                except Exception as e:
                    print(f"[Cleanup] Failed to kill {conn.pid}: {e}")
    cmd = f"python3 -u -m http.server {port} --directory {folder}"
    print(f"[ManualStart] Starting frontend for {name}: {cmd}")
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            bufsize=1, universal_newlines=True, preexec_fn=os.setsid)
    projects[name]['process'] = proc
    stream_process_output(proc, f"{name}-frontend")

def stop_project(name):
    if name in projects and projects[name]['process']:
        proc = projects[name]['process']
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait()
        except Exception as e:
            print(f"[Stop] Failed to kill frontend for {name}: {e}")
        projects[name]['process'] = None

def start_backend(name):
    folder = os.path.join(WEBAPPS_DIR, name)
    backend_file = os.path.join(folder, 'backend.py')
    backend_port = projects[name]['port'] + 1
    for conn in psutil.net_connections():
        if conn.status == 'LISTEN' and conn.laddr.port == backend_port:
            if conn.pid:
                try:
                    print(f"[Cleanup] Killing process {conn.pid} on port {backend_port}")
                    psutil.Process(conn.pid).terminate()
                except Exception as e:
                    print(f"[Cleanup] Failed to kill {conn.pid}: {e}")
    if not os.path.exists(backend_file):
        with open(backend_file, 'w') as f:
            f.write(f"""#!/usr/bin/env {VENV_PYTHON}
from flask import Flask, jsonify
from flask_cors import CORS
app = Flask(__name__)
CORS(app)
@app.route('/api/data')
def data():
    return jsonify(message="Hello from {name} backend!")
if __name__ == '__main__':
    from waitress import serve
    print("[backend] Starting backend server on 0.0.0.0:{backend_port}")
    serve(app, host='0.0.0.0', port={backend_port})
""")
        os.chmod(backend_file, 0o755)
    cmd = f"{VENV_PYTHON} -u {backend_file}"
    print(f"[ManualStart] Starting backend for {name}: {cmd}")
    proc = subprocess.Popen(cmd, cwd=folder, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            bufsize=1, universal_newlines=True, preexec_fn=os.setsid)
    projects[name]['backend_process'] = proc
    stream_process_output(proc, f"{name}-backend")

def stop_backend(name):
    if name in projects and projects[name]['backend_process']:
        proc = projects[name]['backend_process']
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait()
        except Exception as e:
            print(f"[Stop] Failed to kill backend for {name}: {e}")
        projects[name]['backend_process'] = None

def auto_start_all_sites():
    for name in projects.keys():
        try:
            start_project(name)
            start_backend(name)
            print(f"[Startup] Started site: {name}")
        except Exception as e:
            print(f"[Startup] Failed to start {name}: {e}")

if __name__ == '__main__':
    auto_start_all_sites()
    app.run(host='0.0.0.0', port=5001, debug=True)
