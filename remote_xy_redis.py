#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Remote XY Redis Pub/Sub Veri Alıcısı
Remote XY cloud'dan Redis pub/sub üzerinden iklim verilerini alır ve veritabanına kaydeder
"""

import redis
import json
import sqlite3
import time
from datetime import datetime
import threading

class RemoteXYRedisClient:
    def __init__(self, db_path="mantar_is_takip.db", host="cloud.remotexy.com", port=6375, token="32ebd8d30ef0745b7a826e8f143b124c"):
        self.db_path = db_path
        self.host = host
        self.port = port
        self.token = token
        self.redis_client = redis.Redis(host=host, port=port, password=self.token, decode_responses=True)
        self.running = False

    def on_message(self, message):
        try:
            data = json.loads(message['data'])
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
                """, (oda_id, tarih, saat, float(sicaklik), float(nem), float(co2) if co2 else None, "Remote XY Redis"))

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
            pubsub = self.redis_client.pubsub()
            channel = f"device:{self.token}"  # Tahmini channel
            pubsub.subscribe(**{channel: self.on_message})
            print(f"📡 Channel'e abone olundu: {channel}")
            print("🚀 Redis pub/sub client başlatıldı. Durdurmak için Ctrl+C")

            pubsub.run_in_thread(sleep_time=0.001)

            while self.running:
                time.sleep(1)

        except Exception as e:
            print(f"❌ Redis bağlantı hatası: {e}")
            print("💡 Host, port veya channel adını kontrol edin.")

    def stop(self):
        self.running = False
        print("🛑 Redis client durduruldu")

if __name__ == "__main__":
    client = RemoteXYRedisClient()
    try:
        client.start()
    except KeyboardInterrupt:
        client.stop()