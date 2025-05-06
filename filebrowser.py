from flask import Blueprint, render_template, send_from_directory, request, redirect, url_for, flash, session, jsonify, current_app
import os
import shutil
import json
import mimetypes
import subprocess
import psutil
import time

from auth_utils import login_required

filebrowser_bp = Blueprint('filebrowser', __name__, template_folder='templates')

BASE_DIR = "/opt/webapps"

def guess_mode(filename):
    ext = os.path.splitext(filename)[1].lower()
    return {
        '.py': 'python',
        '.js': 'javascript',
        '.mjs': 'javascript',
        '.html': 'htmlmixed',
        '.htm': 'htmlmixed',
        '.css': 'css',
        '.xml': 'xml',
        '.md': 'markdown'
    }.get(ext, 'plaintext')

# ✅ RECURSIVE TREE BUILDER
def build_tree(base_dir, rel_path=""):
    abs_path = os.path.join(base_dir, rel_path)
    tree = []
    for entry in sorted(os.listdir(abs_path)):
        entry_abs = os.path.join(abs_path, entry)
        entry_rel = os.path.join(rel_path, entry) if rel_path else entry
        node = {'name': entry, 'path': entry_rel}
        if os.path.isdir(entry_abs):
            node['type'] = 'folder'
            node['children'] = build_tree(base_dir, entry_rel)
        else:
            node['type'] = 'file'
        tree.append(node)
    return tree

# ✅ API endpoint to fetch file contents
@filebrowser_bp.route('/api/file/<path:path>', methods=['GET'])
@login_required
def api_get_file(path):
    abs_path = os.path.join(BASE_DIR, path)
    if not os.path.isfile(abs_path):
        return jsonify({'error': 'File not found'}), 404

    mime, _ = mimetypes.guess_type(abs_path)
    if mime and not mime.startswith('text'):
        return jsonify({'error': 'Cannot open binary files'}), 400

    try:
        with open(abs_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    mode = guess_mode(abs_path)
    return jsonify({'content': content, 'mode': mode})

# ✅ HTML renderer for tree
def render_tree(tree):
    html = ""
    for node in tree:
        if node['type'] == 'folder':
            html += f"""
            <li data-path="{node['path']}">
                <span class='folder-toggle'>📁 {node['name']}</span>
                <ul style='display:none;'>
                    {render_tree(node['children'])}
                </ul>
            </li>"""
        else:
            html += f"""
            <li data-path="{node['path']}">
                <span class='file-link'>📄 {node['name']}</span>
            </li>"""
    return html

@filebrowser_bp.route('/files/', defaults={'path': ''})
@filebrowser_bp.route('/files/<path:path>')
@login_required
def browse(path):
    abs_path = os.path.join(BASE_DIR, path)

    if not os.path.exists(abs_path):
        flash("Path not found.", "danger")
        return redirect(url_for('filebrowser.browse', path=os.path.dirname(path)))

    if os.path.isfile(abs_path):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'redirect': url_for('filebrowser.edit_file', path=path)})
        return redirect(url_for('filebrowser.edit_file', path=path))

    folders, files = [], []
    for entry in os.listdir(abs_path):
        entry_path = os.path.join(abs_path, entry)
        rel_path = os.path.join(path, entry) if path else entry
        if os.path.isdir(entry_path):
            folders.append({'name': entry, 'path': rel_path})
        else:
            files.append({'name': entry, 'path': rel_path})

    parent_path = os.path.dirname(path) if path else None
    return render_template('filebrowser.html', folders=folders, files=files, path=path, parent_path=parent_path,  os=os)

@filebrowser_bp.route('/create_folder/<path:path>', methods=['POST'])
@login_required
def create_folder(path):
    abs_path = os.path.join(BASE_DIR, path)
    foldername = request.form['foldername']
    os.makedirs(os.path.join(abs_path, foldername), exist_ok=True)
    flash(f"Folder '{foldername}' created.", "success")
    return redirect(url_for('filebrowser.browse', path=path))

@filebrowser_bp.route('/create_file/<path:path>', methods=['POST'])
@login_required
def create_file(path):
    abs_path = os.path.join(BASE_DIR, path)
    filename = request.form['filename']
    open(os.path.join(abs_path, filename), 'w').close()
    flash(f"File '{filename}' created.", "success")
    return redirect(url_for('filebrowser.browse', path=path))

@filebrowser_bp.route('/upload/<path:path>', methods=['POST'])
@login_required
def upload(path):
    abs_path = os.path.join(BASE_DIR, path)
    files = request.files.getlist('file')
    for f in files:
        f.save(os.path.join(abs_path, f.filename))
    flash(f"Uploaded {len(files)} file(s).", "success")
    return redirect(url_for('filebrowser.browse', path=path))

@filebrowser_bp.route('/delete/<path:path>')
@login_required
def delete(path):
    abs_path = os.path.join(BASE_DIR, path)
    try:
        if os.path.isdir(abs_path):
            shutil.rmtree(abs_path)
        else:
            os.remove(abs_path)
        flash(f"Deleted '{os.path.basename(path)}'.", "success")
    except Exception as e:
        flash(f"Error deleting: {e}", "danger")
    return redirect(url_for('filebrowser.browse', path=os.path.dirname(path)))

@filebrowser_bp.route('/editor/<path:path>', methods=['GET', 'POST'])
@login_required
def editor(path):
    abs_path = os.path.join(BASE_DIR, path)
    if not os.path.isfile(abs_path):
        flash("File not found.", "danger")
        return redirect(url_for('filebrowser.browse', path=os.path.dirname(path)))

    if request.method == 'POST':
        content = request.form.get('content')
        try:
            with open(abs_path, 'w') as f:
                f.write(content)
            flash(f"Saved '{os.path.basename(path)}'!", "success")
            return redirect(url_for('filebrowser.editor', path=path))
        except Exception as e:
            flash(f"Error saving: {e}", "danger")

    with open(abs_path) as f:
        content = f.read()
    mode = guess_mode(abs_path)
    tree = build_tree(BASE_DIR)

    return render_template(
        'editor.html',
        content=content,
        mode=mode,
        path=path,
        tree=tree,
        os=os
    )

@filebrowser_bp.route('/cut_multiple/<path:path>', methods=['POST'])
@login_required
def cut_multiple(path):
    selected_raw = request.form.get('selected_paths')
    print(f"[DEBUG] cut_multiple received raw: {selected_raw}")
    try:
        selected = json.loads(selected_raw)
    except Exception as e:
        print(f"[DEBUG] JSON decode error: {e}")
        selected = []
    print(f"[DEBUG] Decoded selected paths: {selected}")

    session['clipboard'] = {'action': 'cut', 'sources': selected}
    flash(f"Cut {len(selected)} item(s).", "info")
    return redirect(url_for('filebrowser.browse', path=path))

@filebrowser_bp.route('/paste/<path:path>')
@login_required
def paste(path):
    clip = session.get('clipboard')
    if clip and clip.get('action') == 'cut' and clip.get('sources'):
        moved = 0
        for src in clip['sources']:
            src_abs = os.path.join(BASE_DIR, src)
            dest_dir = os.path.join(BASE_DIR, path)
            dest_abs = os.path.join(dest_dir, os.path.basename(src))

            print(f"[DEBUG] Moving from {src_abs} → {dest_abs}")

            if not os.path.isdir(dest_dir):
                os.makedirs(dest_dir, exist_ok=True)
                print(f"[DEBUG] Created destination dir: {dest_dir}")

            if os.path.exists(dest_abs):
                flash(f"File '{os.path.basename(src)}' already exists in destination.", "warning")
                print(f"[DEBUG] Destination file already exists: {dest_abs}")
                continue

            try:
                shutil.move(src_abs, dest_abs)
                moved += 1
                print(f"[DEBUG] Successfully moved {src_abs} → {dest_abs}")
            except Exception as e:
                print(f"[DEBUG] Failed moving {src_abs} → {dest_abs}: {e}")
                flash(f"Error moving {src}: {e}", "danger")

        session.pop('clipboard', None)
        flash(f"Pasted {moved} item(s).", "success" if moved else "warning")
    else:
        flash("Nothing to paste.", "warning")
    return redirect(url_for('filebrowser.browse', path=path))

@filebrowser_bp.route('/download/<path:path>')
@login_required
def download(path):
    dir_path = os.path.dirname(os.path.join(BASE_DIR, path))
    filename = os.path.basename(path)
    return send_from_directory(dir_path, filename, as_attachment=True)

@filebrowser_bp.route('/rename/<path:path>', methods=['POST'])
@login_required
def rename(path):
    abs_path = os.path.join(BASE_DIR, path)
    new_name = request.form['new_name']
    new_abs_path = os.path.join(os.path.dirname(abs_path), new_name)
    os.rename(abs_path, new_abs_path)
    flash(f"Renamed to '{new_name}'.", "success")
    return redirect(url_for('filebrowser.browse', path=os.path.dirname(path)))

@filebrowser_bp.route('/terminal')
@login_required
def terminal():
    port = 7681

    # 🟢 Kill ALL ttyd processes
    print(f"[DEBUG] 🔪 Killing all ttyd processes...")
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if 'ttyd' in proc.info['name']:
                print(f"[DEBUG] 🔪 Killing ttyd (PID {proc.info['pid']})")
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    time.sleep(1)  # Optional: give system a moment to release port

    # 🟢 Start new ttyd process
    shell_path = shutil.which('bash') or shutil.which('sh') or '/bin/sh'
    print(f"[DEBUG] 🚀 Starting fresh ttyd on port {port} with shell {shell_path}")
    subprocess.Popen(['ttyd', '--writable', '--once', '-p', str(port), shell_path, '-l'])

    time.sleep(1)  # Optional: wait to ensure it’s up

    target_host = request.host.split(':')[0]
    print(f"[DEBUG] Redirecting user to http://{target_host}:{port}")
    return redirect(f"http://{target_host}:{port}")





