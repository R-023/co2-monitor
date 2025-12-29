from datetime import datetime

def device_dashboard_page(device_id, get_history_func):
    history = get_history_func(device_id)
    if not history:
        return f"<h1>Device {device_id} not found</h1><a href='/'>Back to main page</a>"
    
    latest = history[0]
    try:
        timestamp = datetime.fromisoformat(latest['timestamp'].replace("Z", "+00:00"))
        time_str = timestamp.strftime("%H:%M")
        date_str = timestamp.strftime("%b %d")
    except:
        timestamp = datetime.utcnow()
        time_str = "00:00"
        date_str = "Jan 01"
    
    # CO2 в PPM (ограничено 100–1200 для шкалы)
    co2_ppm = int(latest['co2'] * 10000) if latest['co2'] is not None else 400
    co2_ppm = max(100, min(1200, co2_ppm))  # ограничиваем диапазон
    
    # Угол для стрелки: 100 → 0°, 1200 → 360°
    angle = ((co2_ppm - 100) / (1200 - 100)) * 360
    
    # Определяем цвет зоны
    if co2_ppm <= 800:
        zone_color = "#00ff00"  # зелёный
        hand_color = "var(--green-color)"
    elif co2_ppm <= 1200:
        zone_color = "#ffff00"  # жёлтый
        hand_color = "var(--yellow-color)"
    else:
        zone_color = "#ff1900"  # красный
        hand_color = "var(--red-color)"
    
    temp = latest['temp'] if latest['temp'] is not None else "24"

    return f'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta http-equiv="X-UA-Compatible" content="IE=edge" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>CO₂ Monitor - {device_id}</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Montserrat&family=Roboto:wght@100;300;400;500;700;900&display=swap');
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Montserrat', sans-serif;
        }}

        :root {{
            --primary-color: #f6f7fb;
            --white-color: #fff;
            --black-color: #18191a;
            --red-color: #ff1900;
            --green-color: #00ff00;
            --yellow-color: #ffff00;
            --blue-color: #00aaff;
        }}

        body {{
            display: flex;
            min-height: 100vh;
            align-items: center;
            justify-content: center;
            background: var(--primary-color);
            padding: 20px;
        }}

        body.dark {{
            --primary-color: #242526;
            --white-color: #18191a;
            --black-color: #fff;
            --red-color: #ff1900;
            --green-color: #00ff00;
            --yellow-color: #ffff00;
            --blue-color: #00aaff;
        }}

        .container {{
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 30px;
            max-width: 450px;
            width: 100%;
        }}

        .container .gauge {{
            display: flex;
            height: 400px;
            width: 400px;
            border-radius: 50%;
            align-items: center;
            justify-content: center;
            background: var(--white-color);
            box-shadow: 0 15px 25px rgba(0, 0, 0, 0.1), 0 25px 45px rgba(0, 0, 0, 0.1);
            position: relative;
        }}

        .gauge label {{
            position: absolute;
            inset: 20px;
            text-align: center;
            transform: rotate(calc(var(--i) * (360deg / 12)));
        }}

        .gauge label span {{
            display: inline-block;
            font-size: 24px;
            font-weight: 600;
            color: var(--black-color);
            transform: rotate(calc(var(--i) * (-360deg / 12)));
        }}

        .container .indicators {{
            position: absolute;
            height: 10px;
            width: 10px;
            display: flex;
            justify-content: center;
        }}

        .indicators::before {{
            content: "";
            position: absolute;
            height: 100%;
            width: 100%;
            border-radius: 50%;
            z-index: 100;
            background: var(--black-color);
            border: 4px solid var(--red-color);
        }}

        .indicators .hand {{
            position: absolute;
            height: 170px;
            width: 8px;
            bottom: 0;
            border-radius: 25px;
            transform-origin: bottom;
            background: {hand_color};
            transition: transform 0.5s cubic-bezier(0.4, 2.3, 0.8, 1);
        }}

        .co2-value {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, 30%);
            font-size: 36px;
            font-weight: bold;
            color: var(--black-color);
            z-index: 101;
            text-align: center;
        }}

        .co2-unit {{
            font-size: 16px;
            font-weight: normal;
            margin-top: 5px;
            display: block;
            color: #666;
        }}

        .switch-mode {{
            padding: 10px 20px;
            border-radius: 8px;
            font-size: 22px;
            font-weight: 400;
            display: inline-block;
            color: var(--white-color);
            background: var(--black-color);
            box-shadow: 0 5px 10px rgba(0, 0, 0, 0.1);
            cursor: pointer;
        }}

        .zone-indicator {{
            position: absolute;
            width: 20px;
            height: 20px;
            border-radius: 50%;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            transition: background-color 0.5s ease;
            z-index: 99;
            background: {zone_color};
            box-shadow: 0 0 10px {zone_color};
        }}

        .current-value-display {{
            position: absolute;
            top: 65%;
            left: 50%;
            transform: translateX(-50%);
            font-size: 14px;
            color: var(--black-color);
            font-weight: bold;
            background: var(--white-color);
            padding: 5px 10px;
            border-radius: 15px;
            box-shadow: 0 2px 5px rgba(0, 0, 0, 0.1);
            z-index: 102;
        }}

        .info-panel {{
            display: flex;
            justify-content: space-between;
            width: 100%;
            background: var(--white-color);
            padding: 20px;
            border-radius: 15px;
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.1);
            gap: 20px;
        }}

        .info-item {{
            display: flex;
            flex-direction: column;
            align-items: center;
            flex: 1;
        }}

        .info-icon {{
            font-size: 24px;
            margin-bottom: 10px;
            color: var(--blue-color);
        }}

        .info-label {{
            font-size: 14px;
            font-weight: 500;
            color: var(--black-color);
            margin-bottom: 5px;
        }}

        .info-value {{
            font-size: 18px;
            font-weight: bold;
            color: var(--black-color);
        }}

        .datetime-display {{
            text-align: center;
            margin-top: 10px;
            font-size: 16px;
            font-weight: 500;
            color: var(--black-color);
        }}

        .date-part {{
            display: block;
            font-size: 14px;
            color: #666;
            margin-top: 3px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="gauge">
            <label style="--i: 1"><span>100</span></label>
            <label style="--i: 2"><span>200</span></label>
            <label style="--i: 3"><span>300</span></label>
            <label style="--i: 4"><span>400</span></label>
            <label style="--i: 5"><span>500</span></label>
            <label style="--i: 6"><span>600</span></label>
            <label style="--i: 7"><span>700</span></label>
            <label style="--i: 8"><span>800</span></label>
            <label style="--i: 9"><span>900</span></label>
            <label style="--i: 10"><span>1000</span></label>
            <label style="--i: 11"><span>1100</span></label>
            <label style="--i: 12"><span>1200</span></label>
            
            <div class="zone-indicator"></div>
            <div class="indicators">
                <span class="hand" style="transform: rotate({angle}deg);"></span>
            </div>
            
            <div class="co2-value">
                {co2_ppm}
                <span class="co2-unit">PPM</span>
            </div>
            
            <div class="current-value-display">CO₂ Level: <span id="current-value">{co2_ppm}</span> PPM</div>
        </div>
        
        <div class="info-panel">
            <div class="info-item">
                <div class="info-icon">🌡️</div>
                <div class="info-label">Temperature</div>
                <div class="info-value" id="temperature">{temp}°C</div>
            </div>
            <div class="info-item">
                <div class="info-icon">🕗</div>
                <div class="info-label">Time</div>
                <div class="info-value" id="time">{time_str}</div>
            </div>
            <div class="info-item">
                <div class="info-icon">📅</div>
                <div class="info-label">Date</div>
                <div class="info-value" id="date">{date_str}</div>
            </div>
        </div>
        
        <div class="switch-mode">Dark Mode</div>
    </div>
    
    <script>
        const body = document.querySelector("body"),
              modeSwitch = document.querySelector(".switch-mode");

        modeSwitch.addEventListener("click", () => {{
            body.classList.toggle("dark");
            const isDarkMode = body.classList.contains("dark");
            modeSwitch.textContent = isDarkMode ? "Light Mode" : "Dark Mode";
        }});
    </script>
</body>
</html>
'''