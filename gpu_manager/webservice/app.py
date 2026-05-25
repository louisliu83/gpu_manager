# app.py
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
import sqlite3
import json
import logging
import os
import config
import jwt
import bcrypt
from datetime import datetime, timedelta
from adapters.autodl import AutoDLProvider
from adapters.ppio import PPIOModel
from adapters.luchen import CompShareProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)
#app.config['SECRET_KEY'] = config.SECRET_KEY

SECRET_KEY = "gpu-platform-secret-key-2024"
# 初始化供应商适配器
providers = {}

#if config.AUTODL_API_TOKEN:
#    providers['autodl'] = AutoDLProvider(config.AUTODL_API_TOKEN, config.SLURM_CONTROLLER_IP)

if config.PPIO_API_KEY:
    providers['ppio'] = PPIOModel(config.PPIO_API_KEY, config.SLURM_CONTROLLER_IP)

#if config.LUCHEN_SECRET_KEY:
#    providers['luchen'] = CompShareProvider(config.LUCHEN_ACCESS_KEY, config.LUCHEN_SECRET_KEY, config.SLURM_CONTROLLER_IP)

def init_db():
    """初始化 SQLite 数据库"""
    conn = sqlite3.connect("gpu_platform.db")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS instances (
            id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            gpu_type TEXT NOT NULL,
            status TEXT NOT NULL,
            ip_address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user TEXT,
            spot BOOLEAN DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS performance_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id TEXT,
            report_type TEXT,
            report_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (instance_id) REFERENCES instances(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gpu_offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT,
            gpu_type TEXT,
            price REAL,
            available INTEGER,
            updated_at TIMESTAMP
        )
    """)
    conn.close()

import bcrypt

def init_default_user():
    """初始化默认管理员账户（首次运行时创建）"""
    conn = sqlite3.connect("gpu_platform.db")
    cursor = conn.cursor()
    
    # 检查 users 表是否存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if not cursor.fetchone():
        # 创建 users 表
        cursor.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    
    # 检查是否已有 admin 用户
    cursor.execute("SELECT id FROM users WHERE username = 'admin'")
    if not cursor.fetchone():
        # 密码: admin123
        password_hash = bcrypt.hashpw(b'admin123', bcrypt.gensalt()).decode()
        cursor.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            ('admin', password_hash, 'admin')
        )
        conn.commit()
        print("✅ 默认管理员账户已创建: admin / admin123")
    else:
        print("ℹ️ 管理员账户已存在，跳过初始化")
    
    conn.close()

def sync_offers():
    """定时同步各平台 GPU 库存"""
    offers = []
    for provider_name, provider in providers.items():
        try:
            gpus = provider.get_available_gpus()
            for gpu in gpus:
                gpu['provider'] = provider_name
                offers.append(gpu)
        except Exception as e:
            logger.error(f"Sync failed for {provider_name}: {e}")
    
    if offers:
        conn = sqlite3.connect("gpu_platform.db")
        conn.execute("DELETE FROM gpu_offers")
        for offer in offers:
            conn.execute(
                "INSERT INTO gpu_offers (provider, gpu_type, price, available, updated_at) VALUES (?, ?, ?, ?, datetime('now'))",
                (offer.get('provider'), offer.get('type'), offer.get('price'), 
                 1 if offer.get('available') else 0)
            )
        conn.commit()
        conn.close()
        logger.info(f"Synced {len(offers)} GPU offers")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login')
def login_page():
    """登录页面"""
    return render_template('login.html')

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'error': '用户名和密码不能为空'}), 400

    conn = sqlite3.connect("gpu_platform.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, password_hash, role FROM users WHERE username = ?",
        (username,)
    )
    user = cursor.fetchone()
    conn.close()

    if not user:
        return jsonify({'error': '用户名或密码错误'}), 401

    # 验证密码
    if not bcrypt.checkpw(password.encode(), user[2].encode()):
        return jsonify({'error': '用户名或密码错误'}), 401

    # 生成 JWT token
    token = jwt.encode(
        {'user_id': user[0], 'username': user[1], 'role': user[3], 'exp': datetime.utcnow() + timedelta(hours=24)},
        SECRET_KEY,
        algorithm='HS256'
    )

    return jsonify({
        'token': token,
        'user': {
            'id': user[0],
            'username': user[1],
            'role': user[3]
        }
    })

@app.route('/api/offers', methods=['GET'])
def get_offers():
    """获取统一 GPU 资源列表"""
    conn = sqlite3.connect("gpu_platform.db")
    cursor = conn.execute("SELECT provider, gpu_type, price, available FROM gpu_offers ORDER BY price")
    offers = [{"provider": row[0], "gpu_type": row[1], "price": row[2], "available": bool(row[3])} 
              for row in cursor]
    conn.close()
    return jsonify(offers)

@app.route('/api/instances', methods=['GET'])
def list_instances():
    conn = sqlite3.connect("gpu_platform.db")
    cursor = conn.execute("SELECT id, provider, gpu_type, status, ip_address, created_at FROM instances ORDER BY created_at DESC")
    instances = [{"id": row[0], "provider": row[1], "gpu_type": row[2], 
                  "status": row[3], "ip": row[4], "created_at": row[5]} 
                 for row in cursor]
    conn.close()
    return jsonify(instances)

@app.route('/api/instances', methods=['POST'])
def create_instance():
    data = request.json
    provider_name = data.get('provider')
    gpu_type = data.get('gpu_type')
    gpu_num = data.get('gpu_num', 1)
    
    if provider_name not in providers:
        return jsonify({"error": f"Provider {provider_name} not configured"}), 400
    
    try:
        result = providers[provider_name].launch_instance(gpu_type, gpu_num)
        conn = sqlite3.connect("gpu_platform.db")
        conn.execute(
            "INSERT INTO instances (id, provider, gpu_type, status, ip_address) VALUES (?, ?, ?, ?, ?)",
            (result['instance_id'], result['provider'], result['gpu_type'], result['status'], None)
        )
        conn.commit()
        conn.close()
        return jsonify(result), 202
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/instances/<instance_id>', methods=['DELETE'])
def delete_instance(instance_id):
    conn = sqlite3.connect("gpu_platform.db")
    cursor = conn.execute("SELECT provider FROM instances WHERE id = ?", (instance_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Instance not found"}), 404
    provider_name = row[0]
    if provider_name not in providers:
        conn.close()
        return jsonify({"error": "Provider not configured"}), 400
    
    success = providers[provider_name].terminate_instance(instance_id)
    if success:
        conn.execute("DELETE FROM instances WHERE id = ?", (instance_id,))
        conn.commit()
        conn.close()
        return jsonify({"status": "deleted"})
    
    conn.close()
    return jsonify({"error": "Delete failed"}), 500

@app.route('/api/instances/<instance_id>/status', methods=['GET'])
def instance_status(instance_id):
    conn = sqlite3.connect("gpu_platform.db")
    cursor = conn.execute("SELECT provider FROM instances WHERE id = ?", (instance_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row or row[0] not in providers:
        return jsonify({"error": "Instance not found"}), 404
    
    status = providers[row[0]].get_instance_status(instance_id)
    if status.get('ip'):
        conn = sqlite3.connect("gpu_platform.db")
        conn.execute("UPDATE instances SET status = ?, ip_address = ? WHERE id = ?",
                     (status['status'], status['ip'], instance_id))
        conn.commit()
        conn.close()
    return jsonify(status)

@app.route('/api/performance', methods=['POST'])
def submit_performance():
    """接收性能测试报告"""
    data = request.json
    instance_id = data.get('instance_id')
    report_data = data.get('report_data')
    
    conn = sqlite3.connect("gpu_platform.db")
    conn.execute(
        "INSERT INTO performance_reports (instance_id, report_type, report_data) VALUES (?, ?, ?)",
        (instance_id, 'benchmark', json.dumps(report_data))
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route('/api/performance/<instance_id>', methods=['GET'])
def get_performance(instance_id):
    conn = sqlite3.connect("gpu_platform.db")
    reports = conn.execute(
        "SELECT report_data FROM performance_reports WHERE instance_id = ? ORDER BY created_at DESC",
        (instance_id,)
    ).fetchall()
    conn.close()
    return jsonify([json.loads(row[0]) for row in reports])

@app.route('/api/instances/<instance_id>/metrics', methods=['GET'])
def get_instance_metrics(instance_id):
    """获取实例的实时监控指标"""
    conn = sqlite3.connect("gpu_platform.db")
    cursor = conn.execute("SELECT provider, ip_address, status FROM instances WHERE id = ?", (instance_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return jsonify({"error": "Instance not found"}), 404
    
    if row[2] != 'running':
        return jsonify({"error": "Instance is not running"}), 400
    
    provider_name = row[0]
    
    if provider_name not in providers:
        return jsonify({"error": "Provider not configured"}), 400
    
    try:
        # 调用供应商适配器的 get_instance_metrics 方法
        metrics = providers[provider_name].get_instance_metrics(instance_id)
        
        # 存储 metrics 到数据库（可选）
        conn = sqlite3.connect("gpu_platform.db")
        conn.execute(
            "INSERT INTO performance_reports (instance_id, report_type, report_data) VALUES (?, ?, ?)",
            (instance_id, 'metrics', json.dumps(metrics))
        )
        conn.commit()
        conn.close()
        
        return jsonify(metrics), 200
    except Exception as e:
        logger.error(f"Failed to get metrics for {instance_id}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/instances/<instance_id>/metrics/history', methods=['GET'])
def get_metrics_history(instance_id):
    """获取实例的历史监控数据"""
    conn = sqlite3.connect("gpu_platform.db")
    cursor = conn.execute(
        "SELECT report_data, created_at FROM performance_reports WHERE instance_id = ? AND report_type = 'metrics' ORDER BY created_at DESC LIMIT 100",
        (instance_id,)
    )
    history = [{"metrics": json.loads(row[0]), "timestamp": row[1]} for row in cursor]
    conn.close()
    return jsonify(history)

if __name__ == '__main__':
    init_db()
    init_default_user()   
    # 启动定时同步
    scheduler = BackgroundScheduler()
    scheduler.add_job(sync_offers, 'interval', minutes=2)
    scheduler.start()
    
    app.run(host='0.0.0.0', port=8080, debug=config.DEBUG)
