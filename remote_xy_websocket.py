#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Remote XY WebSocket Veri Alıcısı
Remote XY cloud'dan WebSocket üzerinden iklim verilerini alır ve veritabanına kaydeder
"""

import websocket
import json
import sqlite3
import time
from datetime import datetime
import threading

class RemoteXYWebSocketClient:
    def __init__(self, db_path="mantar_is_takip.db", url="ws://cloud.remotexy.com:6375", token="32ebd8d30ef0745b7a826e8f143b124c"):
        self.db_path = db_path
        self.url = url
        self.token = token
        self.ws = None
        self.running = False

    def on_message(self, ws, message):
        try:
            data = json.loads(message)
            print(f"📨 Veri alındı: {data}")

            # Verileri işle
            self.save_to_database(data)

        except Exception as e:
            print(f"❌ Veri işleme hatası: {e}")

    def on_error(self, ws, error):
        print(f"❌ WebSocket hatası: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        print("🔌 WebSocket bağlantısı kapandı")
        self.running = False

    def on_open(self, ws):
        print("✅ WebSocket bağlantısı açıldı")
        # Auth mesajı gönder
        auth_msg = {"token": self.token}
        ws.send(json.dumps(auth_msg))
        print(f"🔑 Auth gönderildi: {auth_msg}")

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
                """, (oda_id, tarih, saat, float(sicaklik), float(nem), float(co2) if co2 else None, "Remote XY WebSocket"))

                conn.commit()
                print("💾 Veri veritabanına kaydedildi")
            else:
                print("⚠️ Eksik veri: sıcaklık veya nem yok")

            conn.close()

        except Exception as e:
            print(f"❌ Veritabanı hatası: {e}")

    def start(self):
        self.running = True
        websocket.enableTrace(True)
        self.ws = websocket.WebSocketApp(self.url,
                                         on_message=self.on_message,
                                         on_error=self.on_error,
                                         on_close=self.on_close,
                                         on_open=self.on_open)

        print("🚀 WebSocket client başlatıldı. Durdurmak için Ctrl+C")

        try:
            self.ws.run_forever()
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self.running = False
        if self.ws:
            self.ws.close()
        print("🛑 WebSocket client durduruldu")

if __name__ == "__main__":
    client = RemoteXYWebSocketClient()
    client.start()