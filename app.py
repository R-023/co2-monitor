import os
import json
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template_string
import sqlite3

# === Настройки ===
WEB_PORT = int(os.getenv("PORT", 5000))
DB_PATH = os.path.abspath("co2_devices.db")
print(f"📁 Путь к БД: {DB_PATH}")

# === Инициализация базы данных (SQLite) ===
def init_db():
    try:
        conn = sqlite3.connect("co2_devices.db")
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                source_ip TEXT NOT NULL,
                co2 REAL,
                temp INTEGER,
                status TEXT
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_device ON logs(device_id);')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON logs(timestamp);')
        conn.commit()
        conn.close()
        print("✅ SQLite БД инициализирована")
    except Exception as e:
        print(f"❌ ОШИБКА инициализации БД: {e}")

# === Универсальное подключение к SQLite ===
def get_db_connection():
    try:
        conn = sqlite3.connect("co2_devices.db")
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        print(f"❌ ОШИБКА подключения к БД: {e}")
        raise

# === Сохранение данных ===
def save_to_db(device_id, ip, payload):
    try:
        co2 = float(payload["co2"]) if "co2" in payload and payload["co2"] is not None else None
        temp_raw = payload.get("temp")
        temp = None
        if temp_raw is not None:
            try:
                temp = int(float(temp_raw))
            except (ValueError, TypeError):
                temp = None
        status = str(payload.get("status", ""))[:20]

        conn = get_db_connection()
        cursor = conn.cursor()
        timestamp = datetime.utcnow().isoformat() + "Z"
        cursor.execute('''
            INSERT INTO logs (device_id, timestamp, source_ip, co2, temp, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (device_id, timestamp, ip, co2, temp, status))
        conn.commit()
        conn.close()
        print(f"💾 Сохранено: {device_id} | CO2={co2} | Temp={temp} | Status={status} | IP={ip}")
    except Exception as e:
        print(f"❌ ОШИБКА сохранения в БД: {e}")
        raise

# === Flask App ===
app = Flask(__name__)

@app.route('/api/log', methods=['POST'])
def receive_data():
    try:
        payload = request.get_json()
        if not payload:
            print("❌ Получен пустой или невалидный JSON")
            return jsonify({"error": "Invalid JSON"}), 400
        ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        device_id = payload.get("device", ip)
        save_to_db(device_id, ip, payload)
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print(f"❌ КРИТИЧЕСКАЯ ОШИБКА в /api/log: {e}")
        return jsonify({"error": "Internal error"}), 500

# === Эндпоинт для отладки: просмотр последних записей ===
@app.route('/debug')
def debug_logs():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM logs ORDER BY timestamp DESC LIMIT 10')
        rows = cursor.fetchall()
        conn.close()
        return jsonify([dict(row) for row in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def get_devices():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT device_id, MAX(timestamp) as last_seen,
                   co2, temp, status, source_ip
            FROM logs
            GROUP BY device_id
            ORDER BY device_id
        ''')
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"❌ ОШИБКА get_devices(): {e}")
        return []

def get_device_history(device_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM logs
            WHERE device_id = ?
            ORDER BY timestamp DESC
            LIMIT 100
        ''', (device_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"❌ ОШИБКА get_device_history(): {e}")
        return []

def get_statistics():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(DISTINCT device_id) FROM logs')
        total_devices = cursor.fetchone()[0] or 0

        cursor.execute('''
            SELECT COUNT(DISTINCT device_id)
            FROM logs
            WHERE timestamp >= datetime('now', '-10 minutes')
        ''')
        active_devices = cursor.fetchone()[0] or 0

        cursor.execute('''
            SELECT COUNT(DISTINCT device_id)
            FROM logs
            WHERE co2 > 0.09 AND timestamp >= datetime('now', '-10 minutes')
        ''')
        high_co2_alerts = cursor.fetchone()[0] or 0

        cursor.execute('''
            SELECT AVG(temp)
            FROM logs
            WHERE temp IS NOT NULL AND timestamp >= datetime('now', '-10 minutes')
        ''')
        avg_temp = cursor.fetchone()[0]
        conn.close()
        return {
            'total_devices': total_devices,
            'active_devices': active_devices,
            'high_co2_alerts': high_co2_alerts,
            'avg_temp': round(avg_temp, 1) if avg_temp else 0
        }
    except Exception as e:
        print(f"❌ ОШИБКА get_statistics(): {e}")
        return {'total_devices': 0, 'active_devices': 0, 'high_co2_alerts': 0, 'avg_temp': 0}

def get_trend_data():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 
                strftime('%H:00', timestamp) as hour,
                AVG(co2) as avg_co2,
                AVG(temp) as avg_temp
            FROM logs
            WHERE timestamp >= datetime('now', '-24 hours')
            GROUP BY hour
            ORDER BY hour
        ''')
        rows = cursor.fetchall()
        conn.close()
        return [{'hour': row[0], 'co2': row[1], 'temp': row[2]} for row in rows]
    except Exception as e:
        print(f"❌ ОШИБКА get_trend_data(): {e}")
        return []

# === Основной маршрутизатор ===
@app.route('/')
def index():
    devices = get_devices()
    stats = get_statistics()
    
    device_rows = ""
    for d in devices:
        try:
            time_str = datetime.fromisoformat(d['last_seen'].replace("Z", "+00:00")).strftime("%d %b %Y, %H:%M:%S")
        except:
            time_str = d['last_seen']
        
        status_class = "status-good"
        if d['status'] == "VENT":
            status_class = "status-vent"
        elif d['status'] == "WARNING":
            status_class = "status-warning"
        
        co2_class = "co2-normal"
        if d['co2'] is not None:
            if d['co2'] > 0.09:
                co2_class = "co2-high"
            elif d['co2'] > 0.06:
                co2_class = "co2-medium"
        
        # СТРОКА СТАЛА КЛИКАБЕЛЬНОЙ 👇
        device_rows += f'''
        <tr onclick="window.location.href='/device/{d['device_id']}/dashboard'" style="cursor:pointer;">
            <td class="device-id">{d['device_id']}</td>
            <td class="timestamp">{time_str}</td>
            <td class="co2-value {co2_class}">{d['co2'] if d['co2'] is not None else '—'}</td>
            <td class="temp-value">{d['temp'] if d['temp'] is not None else '—'}</td>
            <td><span class="{status_class}">{d['status'] or '—'}</span></td>
            <td>{d['source_ip']}</td>
        </tr>
        '''

    trend_data = get_trend_data()
    co2_chart_bars = ""
    temp_chart_bars = ""
    for data_point in trend_
        co2_value = data_point['co2'] or 0
        temp_value = data_point['temp'] or 0
        co2_height = min(100, max(10, int(co2_value * 800)))
        temp_height = min(100, max(10, int((temp_value - 15) * 10)))
        co2_class = "co2-normal"
        if co2_value > 0.09:
            co2_class = "co2-high"
        elif co2_value > 0.06:
            co2_class = "co2-medium"
        co2_chart_bars += f'''
        <div class="bar co2-bar" style="height: {co2_height}%; min-height: 10px;">
            <div class="bar-value">{co2_value:.2f}</div>
            <div class="bar-label">{data_point['hour']}</div>
        </div>
        '''
        temp_chart_bars += f'''
        <div class="bar temp-bar" style="height: {temp_height}%; min-height: 10px;">
            <div class="bar-value">{int(temp_value)}°C</div>
            <div class="bar-label">{data_point['hour']}</div>
        </div>
        '''

    return f'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CO2 Monitoring Dashboard</title>
    <style>
        :root {{
            --primary: #4CAF50;
            --primary-dark: #388E3C;
            --secondary: #2196F3;
            --danger: #F44336;
            --warning: #FF9800;
            --light: #f9f9f9;
            --dark: #333;
            --gray: #f5f5f5;
            --border: #ddd;
        }}
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #f5f7fa;
            color: #333;
            line-height: 1.6;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }}
        header {{
            background: linear-gradient(135deg, var(--primary), var(--primary-dark));
            color: white;
            padding: 20px 0;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            margin-bottom: 30px;
        }}
        .header-content {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0 20px;
        }}
        .header-title {{
            font-size: 2rem;
            font-weight: 600;
        }}
        .stats-container {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .stat-card {{
            background: white;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.05);
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .stat-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 6px 12px rgba(0,0,0,0.1);
        }}
        .stat-title {{
            font-size: 0.9rem;
            color: #666;
            margin-bottom: 10px;
        }}
        .stat-value {{
            font-size: 2rem;
            font-weight: 700;
            color: var(--primary);
        }}
        .stat-value.warning {{
            color: var(--warning);
        }}
        .stat-value.danger {{
            color: var(--danger);
        }}
        .table-container {{
            background: white;
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 4px 6px rgba(0,0,0,0.05);
            margin-bottom: 30px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        th {{
            background-color: var(--primary);
            color: white;
            text-align: left;
            padding: 15px;
            font-weight: 600;
        }}
        td {{
            padding: 12px 15px;
            border-bottom: 1px solid var(--border);
        }}
        tr:hover {{
            background-color: var(--gray);
        }}
        .status-good {{ color: var(--primary-dark); font-weight: bold; }}
        .status-vent {{ color: var(--danger); font-weight: bold; }}
        .status-warning {{ color: var(--warning); font-weight: bold; }}
        .device-id {{ font-weight: 600; color: var(--secondary); }}
        .timestamp {{ font-size: 0.9em; color: #666; }}
        .co2-value {{ font-weight: 600; }}
        .co2-high {{ color: var(--danger); }}
        .co2-medium {{ color: var(--warning); }}
        .co2-normal {{ color: var(--primary-dark); }}
        .temp-value {{ font-weight: 600; }}
        .chart-container {{
            background: white;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.05);
            margin-bottom: 30px;
        }}
        .chart-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }}
        .chart-title {{
            font-size: 1.2rem;
            font-weight: 600;
        }}
        .chart {{
            height: 300px;
            display: flex;
            align-items: flex-end;
            gap: 5px;
            padding: 20px 0;
        }}
        .bar {{
            flex: 1;
            border-radius: 4px 4px 0 0;
            position: relative;
            min-width: 20px;
        }}
        .bar-label {{
            position: absolute;
            bottom: -25px;
            left: 0;
            right: 0;
            text-align: center;
            font-size: 0.8rem;
            color: #666;
        }}
        .bar-value {{
            position: absolute;
            top: -25px;
            left: 0;
            right: 0;
            text-align: center;
            font-size: 0.8rem;
            font-weight: 600;
        }}
        .co2-bar {{ background: var(--primary); }}
        .temp-bar {{ background: var(--secondary); }}
        @media (max-width: 768px) {{
            .header-content {{ flex-direction: column; text-align: center; gap: 10px; }}
            .stats-container {{ grid-template-columns: 1fr; }}
            table {{ display: block; overflow-x: auto; }}
        }}
    </style>
</head>
<body>
    <header>
        <div class="header-content">
            <h1 class="header-title">📊 CO2 Monitoring Dashboard</h1>
            <div>Last updated: <span id="current-time"></span></div>
        </div>
    </header>
    
    <div class="container">
        <div class="stats-container">
            <div class="stat-card">
                <div class="stat-title">Total Devices</div>
                <div class="stat-value">{stats['total_devices']}</div>
            </div>
            <div class="stat-card">
                <div class="stat-title">Active Devices</div>
                <div class="stat-value">{stats['active_devices']}</div>
            </div>
            <div class="stat-card">
                <div class="stat-title">High CO2 Alerts</div>
                <div class="stat-value danger">{stats['high_co2_alerts']}</div>
            </div>
            <div class="stat-card">
                <div class="stat-title">Avg Temperature</div>
                <div class="stat-value">{stats['avg_temp']}°C</div>
            </div>
        </div>
        
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Device ID</th>
                        <th>Last Seen</th>
                        <th>CO2 (% vol)</th>
                        <th>Temp (°C)</th>
                        <th>Status</th>
                        <th>IP Address</th>
                    </tr>
                </thead>
                <tbody>
                    {device_rows or '<tr><td colspan="6" style="text-align:center">No data available</td></tr>'}
                </tbody>
            </table>
        </div>
        
        <div class="chart-container">
            <div class="chart-header">
                <h2 class="chart-title">CO2 Levels Trend (Last 24 Hours)</h2>
            </div>
            <div class="chart">
                {co2_chart_bars or '<div style="text-align:center; width:100%;">No trend data available</div>'}
            </div>
        </div>
        
        <div class="chart-container">
            <div class="chart-header">
                <h2 class="chart-title">Temperature Trend (Last 24 Hours)</h2>
            </div>
            <div class="chart">
                {temp_chart_bars or '<div style="text-align:center; width:100%;">No trend data available</div>'}
            </div>
        </div>
    </div>

    <script>
        function updateCurrentTime() {{
            const now = new Date();
            document.getElementById('current-time').textContent = now.toLocaleString('en-US', {{
                year: 'numeric',
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            }});
        }}
        updateCurrentTime();
        setInterval(updateCurrentTime, 1000);
        setInterval(() => location.reload(), 30000);
    </script>
</body>
</html>
'''

# === Страница исторического просмотра (если нужно) ===
@app.route('/device/<device_id>')
def device_page(device_id):
    history = get_device_history(device_id)
    if not history:
        return f"<h1>Device {device_id} not found</h1><a href='/'>Back to main page</a>"
    
    latest = history[0]
    try:
        last_seen = datetime.fromisoformat(latest['timestamp'].replace("Z", "+00:00")).strftime("%d %b %Y, %H:%M:%S")
    except:
        last_seen = latest['timestamp']
    
    status_class = "status-good"
    if latest['status'] == "VENT":
        status_class = "status-vent"
    elif latest['status'] == "WARNING":
        status_class = "status-warning"
    
    co2_class = "co2-normal"
    if latest['co2'] is not None:
        if latest['co2'] > 0.09:
            co2_class = "co2-high"
        elif latest['co2'] > 0.06:
            co2_class = "co2-medium"
    
    history_rows = ""
    for r in history:
        try:
            time_str = datetime.fromisoformat(r['timestamp'].replace("Z", "+00:00")).strftime("%H:%M:%S")
        except:
            time_str = r['timestamp']
        
        status_class_hist = "status-good"
        if r['status'] == "VENT":
            status_class_hist = "status-vent"
        elif r['status'] == "WARNING":
            status_class_hist = "status-warning"
        
        co2_class_hist = "co2-normal"
        if r['co2'] is not None:
            if r['co2'] > 0.09:
                co2_class_hist = "co2-high"
            elif r['co2'] > 0.06:
                co2_class_hist = "co2-medium"
        
        history_rows += f'''
        <tr>
            <td class="timestamp">{time_str}</td>
            <td class="co2-value {co2_class_hist}">{r['co2'] if r['co2'] is not None else '—'}</td>
            <td class="temp-value">{r['temp'] if r['temp'] is not None else '—'}</td>
            <td><span class="{status_class_hist}">{r['status'] or '—'}</span></td>
        </tr>
        '''

    return f'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name=" viewport" content="width=device-width, initial-scale=1.0">
    <title>CO2 Monitoring Dashboard</title>
    <style>
        {open(__file__).read().split("return f'''")[1].split("'''")[0]} /* Используем те же CSS — на практике лучше вынести в отдельный файл */
    </style>
</head>
<body>
    <header>
        <div class="header-content">
            <h1 class="header-title">📊 Device Details: {device_id}</h1>
            <div>Last updated: <span id="current-time"></span></div>
        </div>
    </header>
    
    <div class="container">
        <div class="device-details">
            <div class="device-info">
                <h2 class="info-title">Device: {device_id}</h2>
                <div class="info-item">
                    <div class="info-label">Last Communication</div>
                    <div class="info-value">{last_seen}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Current CO2 Level</div>
                    <div class="info-value co2-value {co2_class}">{latest['co2'] if latest['co2'] is not None else '—'} % vol</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Current Temperature</div>
                    <div class="info-value temp-value">{latest['temp'] if latest['temp'] is not None else '—'}°C</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Status</div>
                    <div class="info-value"><span class="{status_class}">{latest['status'] or '—'}</span></div>
                </div>
                <div class="info-item">
                    <div class="info-label">IP Address</div>
                    <div class="info-value">{latest['source_ip']}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Location</div>
                    <div class="info-value">Not specified</div>
                </div>
            </div>
            
            <div class="history-table">
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>Time</th>
                                <th>CO2 (% vol)</th>
                                <th>Temp (°C)</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {history_rows or '<tr><td colspan="4" style="text-align:center">No history data available</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <script>
        function updateCurrentTime() {{
            const now = new Date();
            document.getElementById('current-time').textContent = now.toLocaleString('en-US', {{
                year: 'numeric',
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            }});
        }}
        updateCurrentTime();
        setInterval(updateCurrentTime, 1000);
        setInterval(() => location.reload(), 30000);
    </script>
</body>
</html>
'''

# === ✨ НОВАЯ СТРАНИЦА: ЦИФРОВОЙ ДИСПЛЕЙ УСТРОЙСТВА ===
@app.route('/device/<device_id>/dashboard')
def device_dashboard(device_id):
    history = get_device_history(device_id)
    if not history:
        return f"<h1>Device {device_id} not found</h1><a href='/'>Back to main page</a>"
    
    latest = history[0]
    try:
        last_seen = datetime.fromisoformat(latest['timestamp'].replace("Z", "+00:00")).strftime("%d %b %Y, %H:%M:%S")
    except:
        last_seen = latest['timestamp']
    
    # Переводим % в PPM
    co2_ppm = int(latest['co2'] * 10000) if latest['co2'] is not None else 0
    
    # Определяем цвет шкалы
    if co2_ppm <= 800:
        arc_color = "#4CAF50"  # зелёный
    elif co2_ppm <= 1200:
        arc_color = "#FF9800"  # жёлтый
    else:
        arc_color = "#F44336"  # красный
    
    # Температура
    temp = latest['temp'] if latest['temp'] is not None else "--"
    
    # Влажность — заглушка
    humidity = "62%"
    
    return f'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{device_id} Dashboard</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #0f0f0f;
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            color: white;
        }}
        .device-panel {{
            width: 320px;
            background: #1a1a1a;
            border-radius: 20px;
            padding: 25px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.7);
            position: relative;
            overflow: hidden;
        }}
        .border-glow {{
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            border: 3px solid {arc_color};
            border-radius: 20px;
            z-index: -1;
            filter: blur(2px);
            opacity: 0.7;
        }}
        .header {{
            text-align: center;
            font-size: 1.1rem;
            margin-bottom: 20px;
            color: #aaa;
        }}
        .co2-display {{
            text-align: center;
            margin: 20px 0;
        }}
        .co2-value {{
            font-size: 3.5rem;
            font-weight: bold;
            font-family: 'Courier New', monospace;
            color: white;
            letter-spacing: 2px;
        }}
        .co2-unit {{
            font-size: 1rem;
            color: #888;
            margin-top: 5px;
        }}
        .arc-container {{
            position: relative;
            width: 100%;
            height: 100px;
            margin: 25px 0;
        }}
        .arc {{
            position: absolute;
            width: 100%;
            height: 100%;
            border: 8px solid transparent;
            border-top: 8px solid {arc_color};
            border-radius: 50%;
            transform: rotate(-90deg);
        }}
        .arc::before {{
            content: '';
            position: absolute;
            top: 50%;
            left: 50%;
            width: 82%;
            height: 82%;
            background: #1a1a1a;
            border-radius: 50%;
            transform: translate(-50%, -50%);
        }}
        .info-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-top: 25px;
        }}
        .info-item {{
            background: rgba(255,255,255,0.08);
            border-radius: 12px;
            padding: 12px;
            text-align: center;
        }}
        .info-label {{
            font-size: 0.85rem;
            color: #aaa;
            margin-bottom: 4px;
        }}
        .info-value {{
            font-size: 1.4rem;
            font-weight: bold;
            font-family: 'Courier New', monospace;
        }}
        .last-updated {{
            text-align: center;
            font-size: 0.8rem;
            color: #666;
            margin-top: 15px;
        }}
    </style>
</head>
<body>
    <div class="device-panel">
        <div class="border-glow"></div>
        <div class="header">CO₂ MONITOR</div>
        <div class="co2-display">
            <div class="co2-value">{co2_ppm:04d}</div>
            <div class="co2-unit">PPM</div>
        </div>
        <div class="arc-container">
            <div class="arc"></div>
        </div>
        <div class="info-grid">
            <div class="info-item">
                <div class="info-label">TEMP</div>
                <div class="info-value">{temp}°C</div>
            </div>
            <div class="info-item">
                <div class="info-label">HUMI</div>
                <div class="info-value">{humidity}</div>
            </div>
        </div>
        <div class="last-updated">Last seen: {last_seen}</div>
    </div>
</body>
</html>
'''

# === ИНИЦИАЛИЗАЦИЯ БД ПРИ СТАРТУ ===
init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=WEB_PORT, debug=False)
