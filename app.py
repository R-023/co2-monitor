import os
import json
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
import sqlite3
from dashboard import device_dashboard_page  # ← Импорт из отдельного файла

# === Настройки ===
WEB_PORT = int(os.getenv("PORT", 5000))

# === Инициализация БД ===
def init_db():
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
    print("✅ БД инициализирована")

def get_db_connection():
    conn = sqlite3.connect("co2_devices.db")
    conn.row_factory = sqlite3.Row
    return conn

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
        print(f"💾 Сохранено: {device_id} | CO2={co2} | Temp={temp} | Status={status}")
    except Exception as e:
        print(f"❌ Ошибка сохранения: {e}")

# === Flask App ===
app = Flask(__name__)

@app.route('/api/log', methods=['POST'])
def receive_data():
    try:
        payload = request.get_json()
        if not payload:
            return jsonify({"error": "Invalid JSON"}), 400
        ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        device_id = payload.get("device", ip)
        save_to_db(device_id, ip, payload)
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print(f"❌ API error: {e}")
        return jsonify({"error": "Internal error"}), 500

def get_devices():
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

def get_device_history(device_id):
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

def get_statistics():
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

def get_trend_data():
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

# === Главная страница ===
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
    co2_chart_bars = "".join([
        f'''
        <div class="bar co2-bar" style="height: {min(100, max(10, int((dp['co2'] or 0) * 800)))}%; min-height: 10px;">
            <div class="bar-value">{dp['co2']:.2f}</div>
            <div class="bar-label">{dp['hour']}</div>
        </div>
        ''' for dp in trend_data
    ])
    
    temp_chart_bars = "".join([
        f'''
        <div class="bar temp-bar" style="height: {min(100, max(10, int(((dp['temp'] or 0) - 15) * 10)))}%; min-height: 10px;">
            <div class="bar-value">{int(dp['temp'])}°C</div>
            <div class="bar-label">{dp['hour']}</div>
        </div>
        ''' for dp in trend_data
    ])

    return f'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CO2 Monitoring Dashboard</title>
    <style>
        :root {{ --primary: #4CAF50; --primary-dark: #388E3C; --secondary: #2196F3; --danger: #F44336; --warning: #FF9800; --light: #f9f9f9; --dark: #333; --gray: #f5f5f5; --border: #ddd; }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f5f7fa; color: #333; line-height: 1.6; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
        header {{ background: linear-gradient(135deg, var(--primary), var(--primary-dark)); color: white; padding: 20px 0; box-shadow: 0 2px 10px rgba(0,0,0,0.1); margin-bottom: 30px; }}
        .header-content {{ display: flex; justify-content: space-between; align-items: center; padding: 0 20px; }}
        .header-title {{ font-size: 2rem; font-weight: 600; }}
        .stats-container {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-bottom: 30px; }}
        .stat-card {{ background: white; border-radius: 10px; padding: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); transition: transform 0.2s, box-shadow 0.2s; }}
        .stat-card:hover {{ transform: translateY(-5px); box-shadow: 0 6px 12px rgba(0,0,0,0.1); }}
        .stat-title {{ font-size: 0.9rem; color: #666; margin-bottom: 10px; }}
        .stat-value {{ font-size: 2rem; font-weight: 700; color: var(--primary); }}
        .stat-value.danger {{ color: var(--danger); }}
        .table-container {{ background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.05); margin-bottom: 30px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ background-color: var(--primary); color: white; text-align: left; padding: 15px; font-weight: 600; }}
        td {{ padding: 12px 15px; border-bottom: 1px solid var(--border); }}
        tr:hover {{ background-color: var(--gray); }}
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
        .chart-container {{ background: white; border-radius: 10px; padding: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); margin-bottom: 30px; }}
        .chart-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }}
        .chart-title {{ font-size: 1.2rem; font-weight: 600; }}
        .chart {{ height: 300px; display: flex; align-items: flex-end; gap: 5px; padding: 20px 0; }}
        .bar {{ flex: 1; border-radius: 4px 4px 0 0; position: relative; min-width: 20px; }}
        .bar-label {{ position: absolute; bottom: -25px; left: 0; right: 0; text-align: center; font-size: 0.8rem; color: #666; }}
        .bar-value {{ position: absolute; top: -25px; left: 0; right: 0; text-align: center; font-size: 0.8rem; font-weight: 600; }}
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
            <div class="stat-card"><div class="stat-title">Total Devices</div><div class="stat-value">{stats['total_devices']}</div></div>
            <div class="stat-card"><div class="stat-title">Active Devices</div><div class="stat-value">{stats['active_devices']}</div></div>
            <div class="stat-card"><div class="stat-title">High CO2 Alerts</div><div class="stat-value danger">{stats['high_co2_alerts']}</div></div>
            <div class="stat-card"><div class="stat-title">Avg Temperature</div><div class="stat-value">{stats['avg_temp']}°C</div></div>
        </div>
        <div class="table-container">
            <table><thead><tr><th>Device ID</th><th>Last Seen</th><th>CO2 (% vol)</th><th>Temp (°C)</th><th>Status</th><th>IP Address</th></tr></thead><tbody>{device_rows or '<tr><td colspan="6" style="text-align:center">No data available</td></tr>'}</tbody></table>
        </div>
        <div class="chart-container">
            <div class="chart-header"><h2 class="chart-title">CO2 Levels Trend (Last 24 Hours)</h2></div>
            <div class="chart">{co2_chart_bars or '<div style="text-align:center; width:100%;">No trend data available</div>'}</div>
        </div>
        <div class="chart-container">
            <div class="chart-header"><h2 class="chart-title">Temperature Trend (Last 24 Hours)</h2></div>
            <div class="chart">{temp_chart_bars or '<div style="text-align:center; width:100%;">No trend data available</div>'}</div>
        </div>
    </div>
    <script>
        function updateCurrentTime() {{
            const now = new Date();
            document.getElementById('current-time').textContent = now.toLocaleString('en-US', {{
                year: 'numeric', month: 'short', day: 'numeric',
                hour: '2-digit', minute: '2-digit', second: '2-digit'
            }});
        }}
        updateCurrentTime();
        setInterval(updateCurrentTime, 1000);
        setInterval(() => location.reload(), 30000);
    </script>
</body>
</html>
'''

# === Маршрут для дашборда устройства ===
@app.route('/device/<device_id>/dashboard')
def device_dashboard(device_id):
    return device_dashboard_page(device_id, get_device_history)

# === ИНИЦИАЛИЗАЦИЯ ===
init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=WEB_PORT, debug=False)
