import os
import json
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
import sqlite3
from dashboard import device_dashboard_page  # импорт из отдельного файла

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
    ...
    <!-- остальной HTML без изменений -->
    '''
# (HTML-код оставьте как в предыдущей версии)

# === Маршрут для дашборда устройства ===
@app.route('/device/<device_id>/dashboard')
def device_dashboard(device_id):
    return device_dashboard_page(device_id, get_device_history)

# === ИНИЦИАЛИЗАЦИЯ ===
init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=WEB_PORT, debug=False)
