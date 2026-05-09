#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Remote XY HTTP API Veri Alıcısı
Remote XY cloud'dan HTTP API üzerinden iklim verilerini alır ve veritabanına kaydeder
"""

import requests
import json
import sqlite3
import time
from datetime import datetime
import threading

class RemoteXYHTTPClient:
    def __init__(self, db_path="mantar_is_takip.db", base_url="https://cloud.remotexy.com", token="32ebd8d30ef0745b7a826e8f143b124c"):
        self.db_path = db_path
        self.base_url = base_url
        self.token = token
        self.running = False

    def fetch_data(self):
        try:
            url = f"{self.base_url}/api/data"
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ HTTP istek hatası: {e}")
            return None

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
                """, (oda_id, tarih, saat, float(sicaklik), float(nem), float(co2) if co2 else None, "Remote XY HTTP API"))

                conn.commit()
                print("💾 Veri veritabanına kaydedildi")
            else:
                print("⚠️ Eksik veri: sıcaklık veya nem yok")

            conn.close()

        except Exception as e:
            print(f"❌ Veritabanı hatası: {e}")

    def start(self):
        self.running = True
        print("🚀 HTTP client başlatıldı. Her 60 saniyede bir veri alacak. Durdurmak için Ctrl+C")

        try:
            while self.running:
                data = self.fetch_data()
                if data:
                    print(f"📨 Veri alındı: {data}")
                    self.save_to_database(data)
                else:
                    print("⚠️ Veri alınamadı")

                time.sleep(60)  # Her dakika bir kez

        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self.running = False
        print("🛑 HTTP client durduruldu")

if __name__ == "__main__":
    client = RemoteXYHTTPClient()
    client.start()