#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Remote XY MQTT Veri Alıcısı
Remote XY cloud'dan MQTT üzerinden iklim verilerini alır ve veritabanına kaydeder
"""

import paho.mqtt.client as mqtt
import json
import sqlite3
import time
from datetime import datetime
import threading

class RemoteXYMQTTClient:
    def __init__(self, db_path="mantar_is_takip.db", broker="cloud.remotexy.com", port=1883, token="32ebd8d30ef0745b7a826e8f143b124c"):
        self.db_path = db_path
        self.broker = broker
        self.port = port
        self.token = token
        self.client = mqtt.Client()
        # self.client.tls_set()  # TLS kaldır
        self.client.username_pw_set(username=self.token)  # Token'ı username olarak kullan
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.running = False

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("✅ MQTT bağlantısı başarılı")
            # Topic'e subscribe ol
            topic = f"/device/{self.token}/data"  # Tahmini topic
            client.subscribe(topic)
            print(f"📡 Topic'e abone olundu: {topic}")
        else:
            print(f"❌ MQTT bağlantısı başarısız: {rc}")

    def on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode('utf-8')
            data = json.loads(payload)
            print(f"📨 Veri alındı: {data}")

            # Verileri işle
            self.save_to_database(data)

        except Exception as e:
            print(f"❌ Veri işleme hatası: {e}")

    def save_to_database(self, data):
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # Oda ID'sini varsayalım (kullanıcı seçebilir)
            oda_id = 1  # Varsayılan

            tarih = datetime.now().strftime('%Y-%m-%d')
            saat = datetime.now().strftime('%H:%M:%S')

            sicaklik = data.get('temperature', data.get('sicaklik'))
            nem = data.get('humidity', data.get('nem'))
            co2 = data.get('co2', data.get('co2'))

            if sicaklik is not None and nem is not None:
                c.execute("""
                    INSERT INTO iklim_verileri (oda_id, tarih, saat, sicaklik, nem, co2, aciklama)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (oda_id, tarih, saat, float(sicaklik), float(nem), float(co2) if co2 else None, "Remote XY MQTT"))

                conn.commit()
                print("💾 Veri veritabanına kaydedildi")
            else:
                print("⚠️ Eksik veri: sıcaklık veya nem yok")

            conn.close()

        except Exception as e:
            print(f"❌ Veritabanı hatası: {e}")

    def start(self):
        self.running = True
        try:
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()
            print("🚀 MQTT client başlatıldı. Durdurmak için Ctrl+C")
        except Exception as e:
            print(f"❌ MQTT bağlantı hatası: {e}")
            print("💡 Broker adresini kontrol edin. Belki 'cloud.remotexy.com' veya farklı bir adres.")
            return

        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self.running = False
        self.client.loop_stop()
        self.client.disconnect()
        print("🛑 MQTT client durduruldu")

if __name__ == "__main__":
    client = RemoteXYMQTTClient()
    client.start()