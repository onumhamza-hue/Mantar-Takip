# 🍄 Mantar Üretimi - Hava Durumu Takip Sistemi

Ankara/Çubuk bölgesindeki hava durumunu takip ederek mantar üretim odalarınız için **Telegram bildirimleri** gönderen otomatik uyarı sistemi.

## 🌟 Özellikler

- ✅ **Otomatik Sıcaklık Takibi**: Oda sıcaklıklarının kritik seviyelere ulaşması durumunda uyarı
- 🌧️ **Yağış Uyarıları**: Yağmur/kar uyarısı ile dışarıdaki malzemeleri koruma
- 💨 **Rüzgar Kontrolü**: Şiddetli rüzgar durumunda ekipman güvenliği uyarısı
- 💧 **Nem Takibi**: Yüksek nem oranı uyarıları
- 📊 **Günlük Raporlar**: Her 12 saatte bir otomatik durum raporu
- 🔔 **Akıllı Bildirimler**: Spam önleme ile önemli bildirimlere odaklanma
- 📱 **Telegram Entegrasyonu**: Anlık bildirimler telefonunuza

## 🎯 Mantar Üretimi için Özel Uyarılar

### Soğuk Uyarıları
- Odalar soğuyabilir uyarısı
- Isıtma sistemi çalıştırma önerisi
- Havalandırma ayarlama tavsiyeleri

### Sıcak Uyarıları
- Odalar ısınabilir uyarısı
- Soğutma sistemi önerisi
- Havalandırma maksimuma çıkarma

### Yağış Uyarıları
- Dışarıdaki malzemeleri içeri alma hatırlatması
- Kompost yığınlarını koruma
- Su sızıntısı kontrol önerisi

### Rüzgar Uyarıları
- Hafif ekipmanları sabitleme
- Çadır ve örtüleri kontrol etme
- Havalandırma kanalı ayarlama

## 📸 Ekran Görüntüleri

### Kritik Soğuk Uyarısı
```
🚨 ACİL UYARI 🚨

🥶 KRİTİK SOĞUK UYARISI

📍 Konum: Çubuk/Ankara
🌡️ Sıcaklık: 8°C (Hissedilen: 5°C)
⚠️ Mantar odaları 10°C altına düşebilir!

📋 YAPILMASI GEREKENLER:
• Oda ısıtma sistemlerini açın
• Oda sıcaklıklarını kontrol edin
• Havalandırma delirlerini kapatın
• Dış ortamdaki ekipmanları kontrol edin
```

### Yağış Uyarısı
```
🚨 ACİL UYARI 🚨

🌧️ Yağmur YAĞIŞ UYARISI

📍 Konum: Çubuk/Ankara
🌦️ Durum: şiddetli yağmur

📋 YAPILMASI GEREKENLER:
• Dışarıdaki malzemeleri içeri alın
• Açık alandaki ekipmanları koruyun
• Su sızıntılarını kontrol edin
• Kompost yığınlarını kapatın
• Drenaj sistemlerini kontrol edin
```

## 🚀 Hızlı Başlangıç

### 1. Gereksinimler
- Python 3.8+
- Telegram hesabı
- İnternet bağlantısı

### 2. Kurulum
```powershell
# Klasöre gidin
cd C:\mantar_hava_takip

# Gerekli paketleri yükleyin
pip install -r requirements.txt

# config.json dosyasını düzenleyin
notepad config.json
```

### 3. Çalıştırma
```powershell
python weather_monitor.py
```

Detaylı kurulum için [KURULUM.md](KURULUM.md) dosyasına bakın.

## ⚙️ Yapılandırma

`config.json` dosyasında özelleştirebilirsiniz:

```json
{
  "esikler": {
    "min_sicaklik": 10,      // Kritik soğuk eşiği
    "max_sicaklik": 28,      // Kritik sıcak eşiği
    "ideal_min": 15,         // İdeal minimum
    "ideal_max": 22          // İdeal maksimum
  }
}
```

### Farklı Mantar Türleri İçin Önerilen Ayarlar

| Mantar Türü | Min | İdeal Min | İdeal Max | Max |
|-------------|-----|-----------|-----------|-----|
| Beyaz Şapkalı | 12 | 15 | 22 | 25 |
| İstiridye | 8 | 10 | 21 | 24 |
| Shiitake | 10 | 12 | 18 | 21 |
| Portobello | 12 | 15 | 22 | 25 |

## 📱 Kullanım

Program çalıştığında:
- Her 5 dakikada bir hava durumu kontrol edilir
- Kritik durumlar anında bildirilir
- Her 12 saatte bir durum raporu gönderilir
- Aynı uyarı 1 saat içinde tekrarlanmaz

## 🔄 Otomatik Çalıştırma

### Windows'ta Başlangıçta Otomatik Başlatma

1. `Win + R` tuşlarına basın
2. `shell:startup` yazın
3. Bir kısayol oluşturun:
   - Hedef: `C:\Python39\python.exe C:\mantar_hava_takip\weather_monitor.py`
   - Başlangıç konumu: `C:\mantar_hava_takip`

Detaylar için [KURULUM.md](KURULUM.md) dosyasına bakın.

## 🛡️ Güvenlik

- API anahtarlarınızı kimseyle paylaşmayın
- config.json dosyasını gizli tutun
- Bot token'ınızı düzenli olarak yenileyin

## 🐛 Sorun Giderme

Sık karşılaşılan sorunlar ve çözümleri için [KURULUM.md](KURULUM.md) dosyasının "Sorun Giderme" bölümüne bakın.

## 📊 Teknik Detaylar

- **Hava Durumu API**: OpenWeatherMap
- **Bildirim Sistemi**: Telegram Bot API
- **Kontrol Aralığı**: 5 dakika
- **Rapor Aralığı**: 12 saat
- **Uyarı Spam Önleme**: 1 saat

## 🤝 Katkıda Bulunma

Önerilerinizi ve hata bildirimlerinizi issue olarak açabilirsiniz.

## 📝 Lisans

MIT License - Özgürce kullanabilir, değiştirebilir ve dağıtabilirsiniz.

## ☕ Destek

Bu proje mantar üreticilerine yardımcı olmak için geliştirilmiştir. Başarılı üretimler dileriz! 🍄

---

**Not**: Program sürekli çalışmalı ve internet bağlantısı olmalıdır. Raspberry Pi veya 7/24 çalışan bir bilgisayarda çalıştırmanız önerilir.
"# Mantar-Takip" 
