import os
import json
import uuid
import zipfile
import shutil
import tempfile
import requests
from flask import Flask, render_template, request, jsonify, session, send_file
from flask_session import Session
from werkzeug.utils import secure_filename
from PIL import Image, ImageDraw, ImageFont
import py7zr
import rarfile
import pdfplumber
import docx

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SESSION_TYPE'] = 'filesystem'
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024
Session(app)

SETTINGS_FILE = 'settings.json'
UPLOAD_FOLDER = 'uploads'
CODE_WORKSPACE = 'workspace'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CODE_WORKSPACE, exist_ok=True)
os.makedirs('static/css', exist_ok=True)
os.makedirs('static/js', exist_ok=True)
os.makedirs('templates', exist_ok=True)

def generate_icon(size, path):
    img = Image.new('RGB', (size, size), color=(99, 102, 241))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", size//2)
    except:
        font = ImageFont.load_default()
    text = "AI"
    bbox = draw.textbbox((0,0), text, font=font)
    w, h = bbox[2]-bbox[0], bbox[3]-bbox[1]
    draw.text(((size-w)//2, (size-h)//2-5), text, fill="white", font=font)
    img.save(path)

if not os.path.exists('static/icon-192.png'):
    generate_icon(192, 'static/icon-192.png')
if not os.path.exists('static/icon-512.png'):
    generate_icon(512, 'static/icon-512.png')

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_settings(settings):
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)

def extract_text_from_file(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    text = ""
    try:
        if ext in ['.txt', '.py', '.js', '.html', '.css', '.json', '.md', '.cpp', '.java', '.go', '.rs', '.php', '.xml', '.log', '.csv']:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
        elif ext == '.pdf':
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    text += page.extract_text() or ""
        elif ext == '.docx':
            doc = docx.Document(file_path)
            for para in doc.paragraphs:
                text += para.text + "\n"
        else:
            text = f"[文件: {os.path.basename(file_path)}]"
    except Exception as e:
        text = f"[提取失败: {str(e)}]"
    return text

def extract_archive(archive_path, extract_dir):
    ext = os.path.splitext(archive_path)[1].lower()
    try:
        if ext == '.zip':
            with zipfile.ZipFile(archive_path, 'r') as zf:
                zf.extractall(extract_dir)
        elif ext == '.rar':
            with rarfile.RarFile(archive_path) as rf:
                rf.extractall(extract_dir)
        elif ext == '.7z':
            with py7zr.SevenZipFile(archive_path, 'r') as szf:
                szf.extractall(extract_dir)
        else:
            return None, "不支持的压缩格式"
    except Exception as e:
        return None, str(e)
    file_map = {}
    for root, dirs, files in os.walk(extract_dir):
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, extract_dir)
            content = extract_text_from_file(full)
            file_map[rel] = content
    return file_map, None

def call_ai(messages, provider=None, model=None, stream=False, **kwargs):
    settings = load_settings()
    provider = provider or settings.get('default_provider', 'deepseek')
    model = model or settings.get('models', {}).get(provider, 'deepseek-chat')
    api_key = settings.get('api_keys', {}).get(provider, '')
    base_urls = {
        'deepseek': 'https://api.deepseek.com/v1',
        'openai': 'https://api.openai.com/v1',
        'qwen': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'zhipu': 'https://open.bigmodel.cn/api/paas/v4',
        'moonshot': 'https://api.moonshot.cn/v1',
        'custom': settings.get('custom_base_url', '')
    }
    base_url = base_urls.get(provider, '')
    if not base_url:
        return {'error': f'未配置 {provider} 的基础URL'}
    if not api_key:
        return {'error': f'缺少 {provider} 的 API Key'}
    url = f"{base_url}/chat/completions"
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    data = {
        'model': model,
        'messages': messages,
        'stream': stream,
        **kwargs
    }
    try:
        if stream:
            resp = requests.post(url, headers=headers, json=data, stream=True)
            return resp
        else:
            resp = requests.post(url, headers=headers, json=data)
            return resp.json()
    except Exception as e:
        return {'error': str(e)}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/dev_login')
def dev_login():
    return render_template('dev_login.html')

@app.route('/api/get_settings', methods=['GET'])
def get_settings():
    settings = load_settings()
    public = {
        'api_keys': {k: '******' for k in settings.get('api_keys', {}).keys()},
        'default_provider': settings.get('default_provider', 'deepseek'),
        'default_model': settings.get('default_model', 'deepseek-chat'),
        'custom_base_url': settings.get('custom_base_url', ''),
        'models': settings.get('models', {}),
        'dev_username': settings.get('dev_username', 'admin'),
    }
    return jsonify(public)

@app.route('/api/save_settings', methods=['POST'])
def save_settings_route():
    data = request.json
    settings = load_settings()
    for key in ['api_keys', 'default_provider', 'default_model', 'custom_base_url', 'models', 'dev_username']:
        if key in data:
            if key == 'api_keys':
                for k, v in data['api_keys'].items():
                    if v and v != '******':
                        settings.setdefault('api_keys', {})[k] = v
            else:
                settings[key] = data[key]
    if 'dev_password' in data and data['dev_password']:
        settings['dev_password'] = data['dev_password']
    save_settings(settings)
    return jsonify({'status': 'ok'})

@app.route('/api/test_connection', methods=['POST'])
def test_connection():
    data = request.json
    provider = data.get('provider')
    api_key = data.get('api_key')
    model = data.get('model', '')
    if not provider or not api_key:
        return jsonify({'error': '缺少参数'}), 400
    settings = load_settings()
    base_urls = {
        'deepseek': 'https://api.deepseek.com/v1',
        'openai': 'https://api.openai.com/v1',
        'qwen': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'zhipu': 'https://open.bigmodel.cn/api/paas/v4',
        'moonshot': 'https://api.moonshot.cn/v1',
        'custom': settings.get('custom_base_url', '')
    }
    base_url = base_urls.get(provider)
    if not base_url:
        return jsonify({'error': '不支持的提供商'}), 400
    url = f"{base_url}/chat/completions"
    headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
    payload = {
        'model': model or 'deepseek-chat',
        'messages': [{'role': 'user', 'content': 'ping'}],
        'max_tokens': 5
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        if resp.status_code == 200:
            return jsonify({'success': True, 'message': '连接成功'})
        else:
            return jsonify({'success': False, 'error': resp.text}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/dev_login', methods=['POST'])
def dev_login_route():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    settings = load_settings()
    saved_user = settings.get('dev_username', 'admin')
    saved_pass = settings.get('dev_password', 'admin888')
    if username == saved_user and password == saved_pass:
        session['dev_logged_in'] = True
        return jsonify({'success': True})
    return jsonify({'success': False}), 401

@app.route('/api/dev_logout', methods=['POST'])
def dev_logout():
    session.pop('dev_logged_in', None)
    return jsonify({'success': True})

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': '没有文件'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '文件名为空'}), 400
    filename = secure_filename(file.filename)
    tmp_path = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4().hex}_{filename}")
    file.save(tmp_path)
    ext = os.path.splitext(filename)[1].lower()
    if ext in ['.zip', '.rar', '.7z']:
        extract_dir = os.path.join(UPLOAD_FOLDER, uuid.uuid4().hex)
        os.makedirs(extract_dir, exist_ok=True)
        file_map, err = extract_archive(tmp_path, extract_dir)
        if err:
            shutil.rmtree(extract_dir, ignore_errors=True)
            return jsonify({'error': err}), 500
        workspace_dir = os.path.join(CODE_WORKSPACE, uuid.uuid4().hex)
        shutil.copytree(extract_dir, workspace_dir)
        tree = []
        for root, dirs, files in os.walk(workspace_dir):
            rel_root = os.path.relpath(root, workspace_dir)
            if rel_root == '.':
                rel_root = ''
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, workspace_dir)
                tree.append({
                    'path': rel,
                    'name': f,
                    'type': 'file',
                    'content': file_map.get(rel, '')
                })
            for d in dirs:
                tree.append({
                    'path': os.path.join(rel_root, d),
                    'name': d,
                    'type': 'dir'
                })
        return jsonify({
            'success': True,
            'type': 'archive',
            'workspace': workspace_dir,
            'tree': tree,
            'extracted_text': "\n".join([f"--- {k} ---\n{v}" for k, v in file_map.items()])
        })
    else:
        content = extract_text_from_file(tmp_path)
        ws_dir = os.path.join(CODE_WORKSPACE, uuid.uuid4().hex)
        os.makedirs(ws_dir, exist_ok=True)
        dest = os.path.join(ws_dir, filename)
        shutil.copy2(tmp_path, dest)
        tree = [{
            'path': filename,
            'name': filename,
            'type': 'file',
            'content': content
        }]
        return jsonify({
            'success': True,
            'type': 'file',
            'workspace': ws_dir,
            'tree': tree,
            'extracted_text': content
        })

@app.route('/api/get_file', methods=['POST'])
def get_file():
    data = request.json
    ws = data.get('workspace')
    path = data.get('path')
    if not ws or not path:
        return jsonify({'error': '参数缺失'}), 400
    full = os.path.join(ws, path)
    if not os.path.exists(full) or not full.startswith(os.path.abspath(ws)):
        return jsonify({'error': '文件不存在'}), 404
    with open(full, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    return jsonify({'content': content})

@app.route('/api/save_file', methods=['POST'])
def save_file():
    data = request.json
    ws = data.get('workspace')
    path = data.get('path')
    content = data.get('content', '')
    if not ws or not path:
        return jsonify({'error': '参数缺失'}), 400
    full = os.path.join(ws, path)
    if not full.startswith(os.path.abspath(ws)):
        return jsonify({'error': '非法路径'}), 403
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w', encoding='utf-8') as f:
        f.write(content)
    return jsonify({'success': True})

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.get_json() or {}
    messages = data.get('messages', [])
    provider = data.get('provider')
    model = data.get('model')
    stream = data.get('stream', False)
    if not messages:
        return jsonify({'error': '消息不能为空'}), 400
    result = call_ai(messages, provider, model, stream=False)
    if 'error' in result:
        return jsonify({'error': result['error']}), 500
    return jsonify(result)

@app.route('/api/analyze_code', methods=['POST'])
def analyze_code():
    if not session.get('dev_logged_in'):
        return jsonify({'error': '请先登录开发者模式'}), 401
    data = request.json
    code = data.get('code', '')
    if not code:
        return jsonify({'error': '代码为空'}), 400
    messages = [{'role': 'user', 'content': f"分析以下代码，指出潜在问题、性能瓶颈和改进建议：\n\n{code}"}]
    result = call_ai(messages)
    if 'error' in result:
        return jsonify({'error': result['error']}), 500
    return jsonify({'analysis': result.get('choices', [{}])[0].get('message', {}).get('content', '')})

@app.route('/api/optimize_code', methods=['POST'])
def optimize_code():
    if not session.get('dev_logged_in'):
        return jsonify({'error': '请先登录开发者模式'}), 401
    data = request.json
    code = data.get('code', '')
    if not code:
        return jsonify({'error': '代码为空'}), 400
    messages = [{'role': 'user', 'content': f"优化以下代码，提高性能、可读性和安全性，直接返回优化后的代码：\n\n{code}"}]
    result = call_ai(messages)
    if 'error' in result:
        return jsonify({'error': result['error']}), 500
    return jsonify({'optimized': result.get('choices', [{}])[0].get('message', {}).get('content', '')})

@app.route('/api/explain_code', methods=['POST'])
def explain_code():
    if not session.get('dev_logged_in'):
        return jsonify({'error': '请先登录开发者模式'}), 401
    data = request.json
    code = data.get('code', '')
    if not code:
        return jsonify({'error': '代码为空'}), 400
    messages = [{'role': 'user', 'content': f"逐行解释以下代码的功能：\n\n{code}"}]
    result = call_ai(messages)
    if 'error' in result:
        return jsonify({'error': result['error']}), 500
    return jsonify({'explanation': result.get('choices', [{}])[0].get('message', {}).get('content', '')})

@app.route('/api/download_workspace', methods=['POST'])
def download_workspace():
    data = request.json
    ws = data.get('workspace')
    if not ws or not os.path.exists(ws):
        return jsonify({'error': '工作区不存在'}), 400
    zip_path = tempfile.NamedTemporaryFile(suffix='.zip', delete=False).name
    shutil.make_archive(zip_path.replace('.zip', ''), 'zip', ws)
    return send_file(zip_path, as_attachment=True, download_name='workspace.zip')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
