
from flask import Flask, jsonify, request, render_template
from flask_sqlalchemy import SQLAlchemy
import paho.mqtt.client as mqtt
from datetime import datetime, timedelta
import json
from apscheduler.schedulers.background import BackgroundScheduler
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:@localhost/temperatura_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your_secret_key_here'

db = SQLAlchemy(app)

class SensorData(db.Model):
    __tablename__ = 'temperatura'
    id = db.Column(db.Integer, primary_key=True)
    valor = db.Column(db.Float, nullable=False)
    heart_rate = db.Column(db.Integer, nullable=True)
    spo2 = db.Column(db.Integer, nullable=True)
    fecha = db.Column(db.DateTime, default=datetime.now, index=True)

current_readings = {
    'temperature': None,
    'heart_rate': None,
    'spo2': None,
    'last_update': None
}

mqtt_client = mqtt.Client()
mqtt_topic = "healthmonitor/#"

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("MQTT Connected successfully")
        client.subscribe(mqtt_topic)
    else:
        print(f"Failed to connect, return code {rc}")

def on_message(client, userdata, msg):
    try:
        topic = msg.topic
        payload = msg.payload.decode()
        data = json.loads(payload)
        
        print(f"Received message on {topic}: {data}")
        
        if 'temperature' in data and data['temperature'] is not None:
            current_readings['temperature'] = float(data['temperature'])
        if 'hr' in data and data['hr'] is not None:
            current_readings['heart_rate'] = int(data['hr'])
        if 'spo2' in data and data['spo2'] is not None:
            current_readings['spo2'] = int(data['spo2'])
        
        current_readings['last_update'] = datetime.now()
        
        if None not in [current_readings['temperature'], current_readings['heart_rate'], current_readings['spo2']]:
            with app.app_context():
                record = SensorData(
                    valor=current_readings['temperature'],
                    heart_rate=current_readings['heart_rate'],
                    spo2=current_readings['spo2']
                )
                db.session.add(record)
                db.session.commit()
                print("Datos guardados en la base de datos")
                
    except json.JSONDecodeError:
        print(f"Error decoding JSON from payload: {payload}")
    except Exception as e:
        print(f"Error processing MQTT message: {str(e)}")

def clean_old_data():
    with app.app_context():
        old_records = SensorData.query.filter(
            SensorData.fecha < datetime.now() - timedelta(days=30)
        ).delete()
        db.session.commit()
        print(f"Deleted {old_records} old records")

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/datos')
def get_data():
    range_param = request.args.get('range', '5min')
    now = datetime.now()
    
    if range_param == '5min':
        time_limit = now - timedelta(minutes=5)
    elif range_param == '15min':
        time_limit = now - timedelta(minutes=15)
    elif range_param == '30min':
        time_limit = now - timedelta(minutes=30)
    else:
        time_limit = None

    query = SensorData.query
    if time_limit:
        query = query.filter(SensorData.fecha >= time_limit)
    
    records = query.order_by(SensorData.fecha.asc()).all()
    
    history_temp = [{'x': r.fecha.strftime("%H:%M:%S"), 'y': float(r.valor)} for r in records]
    history_hr = [{'x': r.fecha.strftime("%H:%M:%S"), 'y': int(r.heart_rate)} for r in records]
    history_spo2 = [{'x': r.fecha.strftime("%H:%M:%S"), 'y': int(r.spo2)} for r in records]
    
    if current_readings['last_update'] and (now - current_readings['last_update']).seconds < 30:
        temp_value = current_readings['temperature']
        hr_value = current_readings['heart_rate']
        spo2_value = current_readings['spo2']
    elif records:
        last_record = records[-1]
        temp_value = float(last_record.valor)
        hr_value = int(last_record.heart_rate)
        spo2_value = int(last_record.spo2)
    else:
        temp_value = None
        hr_value = None
        spo2_value = None
    
    return jsonify({
        'temperatura_actual': temp_value,
        'heart_rate': hr_value,
        'spo2': spo2_value,
        'historico_temperatura': history_temp,
        'historico_heart': history_hr,
        'historico_spo2': history_spo2,
        'last_update': current_readings['last_update'].isoformat() if current_readings['last_update'] else None
    })

def init_db():
    with app.app_context():
        db.create_all()
        print("Database tables created")

if __name__ == '__main__':
    init_db()
    mqtt_client.connect("broker.emqx.io", 1883, 60)
    mqtt_client.loop_start()
    
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=clean_old_data, trigger="interval", days=1)
    scheduler.start()
    
    app.run(host='0.0.0.0', port=5000, debug=True)