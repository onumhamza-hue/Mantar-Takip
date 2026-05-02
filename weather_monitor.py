#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mantar Üretimi - Hava Durumu Takip Sistemi
Ankara/Çubuk hava durumunu takip eder ve Telegram'dan bildirim gönderir
"""

import requests
import time
import json
from datetime import datetime
from typing import Dict, Optional

class MantarHavaDurumuTakip:
    def __init__(self, config_file: str = "config.json"):
        """Yapılandırma dosyasından ayarları yükle"""
        with open(config_file, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        
        self.telegram_token = self.config['telegram']['bot_token']
        self.chat_id = self.config['telegram']['chat_id']
        self.weather_api_key = self.config['weather']['api_key']
        self.sehir = self.config['weather']['sehir']
        self.ilce = self.config['weather']['ilce']
        
        # Mantar üretimi için sıcaklık eşikleri
        self.min_sicaklik = self.config['esikler']['min_sicaklik']
        self.max_sicaklik = self.config['esikler']['max_sicaklik']
        self.ideal_min = self.config['esikler']['ideal_min']
        self.ideal_max = self.config['esikler']['ideal_max']
        
        self.son_uyari_zamani = {}
        self.uyari_bekleme_suresi = 3600  # 1 saat (saniye cinsinden)
    
    def hava_durumu_al(self) -> Optional[Dict]:
        """OpenWeatherMap API'sinden hava durumu verilerini al"""
        try:
            url = f"https://api.openweathermap.org/data/2.5/weather"
            params = {
                'q': f"{self.ilce},{self.sehir},TR",
                'appid': self.weather_api_key,
                'units': 'metric',
                'lang': 'tr'
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        
        except requests.exceptions.RequestException as e:
            print(f"❌ Hava durumu alınamadı: {e}")
            return None
    
    def telegram_mesaj_gonder(self, mesaj: str, acil: bool = False):
        """Telegram üzerinden bildirim gönder"""
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            
            # Acil mesajlar için özel işaretleme
            if acil:
                mesaj = f"🚨 ACİL UYARI 🚨\n\n{mesaj}"
            
            data = {
                'chat_id': self.chat_id,
                'text': mesaj,
                'parse_mode': 'HTML'
            }
            
            response = requests.post(url, data=data, timeout=10)
            response.raise_for_status()
            print(f"✅ Telegram bildirimi gönderildi: {mesaj[:50]}...")
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Telegram mesajı gönderilemedi: {e}")
    
    def uyari_gonderilmeli_mi(self, uyari_tipi: str) -> bool:
        """Aynı uyarının çok sık gönderilmesini engelle"""
        simdi = time.time()
        
        if uyari_tipi not in self.son_uyari_zamani:
            self.son_uyari_zamani[uyari_tipi] = simdi
            return True
        
        if simdi - self.son_uyari_zamani[uyari_tipi] >= self.uyari_bekleme_suresi:
            self.son_uyari_zamani[uyari_tipi] = simdi
            return True
        
        return False
    
    def sicaklik_kontrol(self, sicaklik: float, hissedilen: float):
        """Sıcaklık kontrolü yap ve gerekirse uyarı gönder"""
        mesajlar = []
        
        # Kritik düşük sıcaklık
        if sicaklik < self.min_sicaklik:
            if self.uyari_gonderilmeli_mi('kritik_soguk'):
                mesaj = (
                    f"🥶 <b>KRİTİK SOĞUK UYARISI</b>\n\n"
                    f"📍 Konum: {self.ilce}/{self.sehir}\n"
                    f"🌡️ Sıcaklık: {sicaklik}°C (Hissedilen: {hissedilen}°C)\n"
                    f"⚠️ Mantar odaları <b>{self.min_sicaklik}°C</b> altına düşebilir!\n\n"
                    f"📋 <b>YAPILMASI GEREKENLER:</b>\n"
                    f"• Oda ısıtma sistemlerini açın\n"
                    f"• Oda sıcaklıklarını kontrol edin\n"
                    f"• Havalandırma delirlerini kapatın\n"
                    f"• Dış ortamdaki ekipmanları kontrol edin"
                )
                self.telegram_mesaj_gonder(mesaj, acil=True)
        
        # Düşük sıcaklık uyarısı
        elif sicaklik < self.ideal_min:
            if self.uyari_gonderilmeli_mi('dusuk_sicaklik'):
                mesaj = (
                    f"❄️ <b>DÜŞÜK SICAKLIK UYARISI</b>\n\n"
                    f"📍 Konum: {self.ilce}/{self.sehir}\n"
                    f"🌡️ Sıcaklık: {sicaklik}°C (Hissedilen: {hissedilen}°C)\n"
                    f"⚠️ İdeal sıcaklık aralığının altında\n"
                    f"✅ İdeal aralık: {self.ideal_min}°C - {self.ideal_max}°C\n\n"
                    f"💡 Oda ısıtma sistemlerini hazır tutun"
                )
                self.telegram_mesaj_gonder(mesaj, acil=False)
        
        # Kritik yüksek sıcaklık
        elif sicaklik > self.max_sicaklik:
            if self.uyari_gonderilmeli_mi('kritik_sicak'):
                mesaj = (
                    f"🔥 <b>KRİTİK SICAK UYARISI</b>\n\n"
                    f"📍 Konum: {self.ilce}/{self.sehir}\n"
                    f"🌡️ Sıcaklık: {sicaklik}°C (Hissedilen: {hissedilen}°C)\n"
                    f"⚠️ Mantar odaları <b>{self.max_sicaklik}°C</b> üzerine çıkabilir!\n\n"
                    f"📋 <b>YAPILMASI GEREKENLER:</b>\n"
                    f"• Oda soğutma sistemlerini açın\n"
                    f"• Havalandırma sistemini maksimuma çıkarın\n"
                    f"• Gölgeleme önlemleri alın\n"
                    f"• Nem seviyesini kontrol edin"
                )
                self.telegram_mesaj_gonder(mesaj, acil=True)
        
        # Yüksek sıcaklık uyarısı
        elif sicaklik > self.ideal_max:
            if self.uyari_gonderilmeli_mi('yuksek_sicaklik'):
                mesaj = (
                    f"🌡️ <b>YÜKSEK SICAKLIK UYARISI</b>\n\n"
                    f"📍 Konum: {self.ilce}/{self.sehir}\n"
                    f"🌡️ Sıcaklık: {sicaklik}°C (Hissedilen: {hissedilen}°C)\n"
                    f"⚠️ İdeal sıcaklık aralığının üstünde\n"
                    f"✅ İdeal aralık: {self.ideal_min}°C - {self.ideal_max}°C\n\n"
                    f"💡 Soğutma sistemlerini hazır tutun"
                )
                self.telegram_mesaj_gonder(mesaj, acil=False)
    
    def yagmur_kontrol(self, hava_durumu: Dict):
        """Yağmur durumunu kontrol et"""
        weather_main = hava_durumu.get('weather', [{}])[0].get('main', '').lower()
        weather_desc = hava_durumu.get('weather', [{}])[0].get('description', '')
        
        # Yağmur veya kar kontrolü
        if weather_main in ['rain', 'drizzle', 'thunderstorm', 'snow']:
            if self.uyari_gonderilmeli_mi('yagmur'):
                yagis_tipi = "🌧️ Yağmur" if weather_main in ['rain', 'drizzle'] else "❄️ Kar" if weather_main == 'snow' else "⛈️ Fırtına"
                
                mesaj = (
                    f"{yagis_tipi} <b>YAĞIŞ UYARISI</b>\n\n"
                    f"📍 Konum: {self.ilce}/{self.sehir}\n"
                    f"🌦️ Durum: {weather_desc}\n\n"
                    f"📋 <b>YAPILMASI GEREKENLER:</b>\n"
                    f"• Dışarıdaki malzemeleri içeri alın\n"
                    f"• Açık alandaki ekipmanları koruyun\n"
                    f"• Su sızıntılarını kontrol edin\n"
                    f"• Kompost yığınlarını kapatın\n"
                    f"• Drenaj sistemlerini kontrol edin"
                )
                self.telegram_mesaj_gonder(mesaj, acil=True)
        
        # Yağmur tahmini (1 saatlik tahmin)
        if 'rain' in hava_durumu:
            rain_1h = hava_durumu.get('rain', {}).get('1h', 0)
            if rain_1h > 0 and self.uyari_gonderilmeli_mi('yagmur_tahmini'):
                mesaj = (
                    f"☔ <b>YAĞMUR TAHMİNİ</b>\n\n"
                    f"📍 Konum: {self.ilce}/{self.sehir}\n"
                    f"💧 1 saat içinde {rain_1h}mm yağmur bekleniyor\n\n"
                    f"💡 Dışarıdaki malzemeleri hazırlayın"
                )
                self.telegram_mesaj_gonder(mesaj, acil=False)
    
    def ruzgar_kontrol(self, hava_durumu: Dict):
        """Rüzgar durumunu kontrol et"""
        ruzgar_hizi = hava_durumu.get('wind', {}).get('speed', 0)  # m/s
        ruzgar_hizi_kmh = ruzgar_hizi * 3.6  # km/h'ye çevir
        
        # Şiddetli rüzgar (50 km/h üzeri)
        if ruzgar_hizi_kmh > 50:
            if self.uyari_gonderilmeli_mi('siddetli_ruzgar'):
                mesaj = (
                    f"💨 <b>ŞİDDETLİ RÜZGAR UYARISI</b>\n\n"
                    f"📍 Konum: {self.ilce}/{self.sehir}\n"
                    f"🌪️ Rüzgar Hızı: {ruzgar_hizi_kmh:.1f} km/h\n\n"
                    f"📋 <b>YAPILMASI GEREKENLER:</b>\n"
                    f"• Hafif ekipmanları sabitleyin veya içeri alın\n"
                    f"• Çadır ve örtüleri kontrol edin\n"
                    f"• Kapı ve pencereleri kapatın\n"
                    f"• Havalandırma kanallarını ayarlayın"
                )
                self.telegram_mesaj_gonder(mesaj, acil=True)
    
    def nem_kontrol(self, hava_durumu: Dict):
        """Nem durumunu kontrol et"""
        nem = hava_durumu.get('main', {}).get('humidity', 0)
        
        # Çok yüksek nem (mantar için sorun olabilir)
        if nem > 90:
            if self.uyari_gonderilmeli_mi('yuksek_nem'):
                mesaj = (
                    f"💧 <b>YÜKSEK NEM UYARISI</b>\n\n"
                    f"📍 Konum: {self.ilce}/{self.sehir}\n"
                    f"💦 Nem Oranı: %{nem}\n\n"
                    f"⚠️ Yüksek dış nem, oda içi nem kontrolünü zorlaştırabilir\n\n"
                    f"💡 Havalandırma sistemlerini ayarlayın"
                )
                self.telegram_mesaj_gonder(mesaj, acil=False)
    
    def durum_raporu_gonder(self, hava_durumu: Dict):
        """Günlük durum raporu gönder"""
        if not self.uyari_gonderilmeli_mi('gunluk_rapor'):
            return
        
        sicaklik = hava_durumu.get('main', {}).get('temp', 0)
        hissedilen = hava_durumu.get('main', {}).get('feels_like', 0)
        nem = hava_durumu.get('main', {}).get('humidity', 0)
        weather_desc = hava_durumu.get('weather', [{}])[0].get('description', '')
        ruzgar_hizi = hava_durumu.get('wind', {}).get('speed', 0) * 3.6
        
        # Durum emoji
        if self.ideal_min <= sicaklik <= self.ideal_max:
            durum_emoji = "✅"
            durum_text = "İDEAL"
        elif sicaklik < self.min_sicaklik or sicaklik > self.max_sicaklik:
            durum_emoji = "🚨"
            durum_text = "KRİTİK"
        else:
            durum_emoji = "⚠️"
            durum_text = "DİKKAT"
        
        mesaj = (
            f"{durum_emoji} <b>GÜNLÜK HAVA DURUMU RAPORU</b>\n\n"
            f"📍 Konum: {self.ilce}/{self.sehir}\n"
            f"📅 Tarih: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"🌡️ Sıcaklık: {sicaklik}°C (Hissedilen: {hissedilen}°C)\n"
            f"💧 Nem: %{nem}\n"
            f"💨 Rüzgar: {ruzgar_hizi:.1f} km/h\n"
            f"🌤️ Durum: {weather_desc}\n\n"
            f"<b>Mantar Üretimi Durumu: {durum_text}</b>\n"
            f"İdeal Aralık: {self.ideal_min}°C - {self.ideal_max}°C"
        )
        
        self.telegram_mesaj_gonder(mesaj, acil=False)
    
    def calistir(self):
        """Ana döngü - hava durumunu kontrol et"""
        print("=" * 60)
        print("🍄 MANTAR ÜRETİMİ HAVA DURUMU TAKİP SİSTEMİ")
        print(f"📍 Konum: {self.ilce}/{self.sehir}")
        print("=" * 60)
        
        # Başlangıç bildirimi
        self.telegram_mesaj_gonder(
            f"✅ <b>Sistem Başlatıldı</b>\n\n"
            f"📍 Konum: {self.ilce}/{self.sehir}\n"
            f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"Hava durumu takibi başladı..."
        )
        
        kontrol_sayaci = 0
        
        while True:
            try:
                print(f"\n🔄 Hava durumu kontrol ediliyor... ({datetime.now().strftime('%H:%M:%S')})")
                
                hava_durumu = self.hava_durumu_al()
                
                if hava_durumu:
                    sicaklik = hava_durumu.get('main', {}).get('temp', 0)
                    hissedilen = hava_durumu.get('main', {}).get('feels_like', 0)
                    
                    print(f"🌡️ Sıcaklık: {sicaklik}°C (Hissedilen: {hissedilen}°C)")
                    
                    # Kontroller
                    self.sicaklik_kontrol(sicaklik, hissedilen)
                    self.yagmur_kontrol(hava_durumu)
                    self.ruzgar_kontrol(hava_durumu)
                    self.nem_kontrol(hava_durumu)
                    
                    # Her 12 saatte bir durum raporu (144 kontrol = 12 saat, 5 dk aralıkla)
                    kontrol_sayaci += 1
                    if kontrol_sayaci >= 144:
                        self.durum_raporu_gonder(hava_durumu)
                        kontrol_sayaci = 0
                
                # 5 dakika bekle
                print(f"⏳ Sonraki kontrol 5 dakika sonra...")
                time.sleep(300)
            
            except KeyboardInterrupt:
                print("\n\n👋 Program kapatılıyor...")
                self.telegram_mesaj_gonder("⚠️ <b>Sistem Durduruldu</b>\n\nHava durumu takibi sonlandırıldı.")
                break
            
            except Exception as e:
                print(f"❌ Hata oluştu: {e}")
                time.sleep(60)  # Hata durumunda 1 dakika bekle


def main():
    """Ana fonksiyon"""
    try:
        monitor = MantarHavaDurumuTakip("config.json")
        monitor.calistir()
    except FileNotFoundError:
        print("❌ config.json dosyası bulunamadı!")
        print("Lütfen önce config.json dosyasını oluşturun.")
    except Exception as e:
        print(f"❌ Program başlatılamadı: {e}")


if __name__ == "__main__":
    main()
