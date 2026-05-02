# 🍄 Mantar Üretimi Hava Durumu Takip Sistemi

## 📋 Kurulum Adımları

### 1. Python Kurulumu
- Python 3.8 veya üzeri versiyonu yükleyin: https://www.python.org/downloads/
- Kurulum sırasında "Add Python to PATH" seçeneğini işaretleyin

### 2. Gerekli Kütüphaneleri Yükleyin
```powershell
pip install -r requirements.txt
```

### 3. API Anahtarlarını Alın

#### 🤖 Telegram Bot Token
1. Telegram'da @BotFather'ı bulun ve konuşmaya başlayın
2. `/newbot` komutunu gönderin
3. Bot için bir isim belirleyin (örn: "Mantar Hava Takip")
4. Bot için bir kullanıcı adı belirleyin (örn: "mantar_hava_bot")
5. Aldığınız **token**'ı kaydedin (örn: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

#### 💬 Telegram Chat ID
1. Bot'unuzu bulun ve "/start" yazın
2. Tarayıcınızda şu adresi açın: `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - `<TOKEN>` yerine bot token'ınızı yazın
3. "chat" altındaki "id" değerini kaydedin (örn: `123456789`)

#### 🌤️ OpenWeatherMap API Key
1. https://openweathermap.org/ adresine gidin
2. Ücretsiz hesap oluşturun
3. "API Keys" bölümünden API anahtarınızı alın
4. Not: API'nin aktif olması 1-2 saat sürebilir

### 4. config.json Dosyasını Düzenleyin
```json
{
  "telegram": {
    "bot_token": "123456789:ABCdefGHIjklMNOpqrsTUVwxyz",
    "chat_id": "123456789"
  },
  "weather": {
    "api_key": "sizin_openweathermap_api_key",
    "sehir": "Ankara",
    "ilce": "Çubuk"
  },
  "esikler": {
    "min_sicaklik": 10,
    "max_sicaklik": 28,
    "ideal_min": 15,
    "ideal_max": 22
  }
}
```

#### ⚙️ Sıcaklık Eşikleri Açıklaması
- **min_sicaklik**: Bu sıcaklığın altında kritik soğuk uyarısı verir (°C)
- **max_sicaklik**: Bu sıcaklığın üstünde kritik sıcak uyarısı verir (°C)
- **ideal_min**: İdeal aralığın alt sınırı (°C)
- **ideal_max**: İdeal aralığın üst sınırı (°C)

> Mantar türüne göre bu değerleri ayarlayabilirsiniz:
> - **Beyaz Şapkalı Mantar**: 15-22°C
> - **İstiridye Mantarı**: 10-21°C
> - **Shiitake**: 12-18°C

### 5. Programı Çalıştırın
```powershell
python weather_monitor.py
```

## 🚀 Otomatik Başlatma (Windows)

### Görev Zamanlayıcı ile Otomatik Başlatma

1. **Görev Zamanlayıcı**'yı açın (`taskschd.msc`)
2. **Eylem** > **Basit Görev Oluştur**
3. Ad: "Mantar Hava Takip"
4. Tetikleyici: "Bilgisayar başladığında"
5. Eylem: "Program başlat"
6. Program: Python yolunuz (örn: `C:\Python39\python.exe`)
7. Bağımsız değişkenler: `weather_monitor.py`
8. Başlangıç: `C:\mantar_hava_takip`

### Windows Hizmet Olarak Çalıştırma (İleri Düzey)

`servis_kur.py` dosyasını oluşturun:
```python
import win32serviceutil
import win32service
import win32event
import servicemanager
import socket
import sys
import os

sys.path.append(os.path.dirname(__file__))
from weather_monitor import MantarHavaDurumuTakip

class MantarHavaService(win32serviceutil.ServiceFramework):
    _svc_name_ = "MantarHavaTakip"
    _svc_display_name_ = "Mantar Hava Durumu Takip Servisi"
    _svc_description_ = "Mantar üretimi için hava durumu takip sistemi"

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        socket.setdefaulttimeout(60)
        self.is_alive = True

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)
        self.is_alive = False

    def SvcDoRun(self):
        servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                            servicemanager.PYS_SERVICE_STARTED,
                            (self._svc_name_, ''))
        self.main()

    def main(self):
        monitor = MantarHavaDurumuTakip()
        monitor.calistir()

if __name__ == '__main__':
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(MantarHavaService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(MantarHavaService)
```

Kurulum için:
```powershell
pip install pywin32
python servis_kur.py install
python servis_kur.py start
```

## 📊 Özellikler

### Gönderilen Uyarılar

1. **❄️ Düşük Sıcaklık Uyarısı**: Sıcaklık ideal aralığın altına düşünce
2. **🥶 Kritik Soğuk Uyarısı**: Sıcaklık minimum eşiğin altına düşünce
3. **🌡️ Yüksek Sıcaklık Uyarısı**: Sıcaklık ideal aralığın üstüne çıkınca
4. **🔥 Kritik Sıcak Uyarısı**: Sıcaklık maksimum eşiği aşınca
5. **🌧️ Yağış Uyarısı**: Yağmur, kar veya fırtına durumunda
6. **💨 Şiddetli Rüzgar Uyarısı**: Rüzgar hızı 50 km/h üzerine çıkınca
7. **💧 Yüksek Nem Uyarısı**: Nem oranı %90'ı geçince
8. **📊 Günlük Rapor**: Her 12 saatte bir genel durum raporu

### Kontrol Aralığı
- Program her **5 dakika**da bir hava durumunu kontrol eder
- Aynı uyarı **1 saat** içinde tekrar gönderilmez (spam önleme)

## 🛠️ Sorun Giderme

### "config.json bulunamadı" Hatası
- config.json dosyasının weather_monitor.py ile aynı klasörde olduğundan emin olun

### "API Key geçersiz" Hatası
- OpenWeatherMap API key'inizin aktif olduğundan emin olun (1-2 saat sürebilir)
- config.json'da doğru girildiğini kontrol edin

### Telegram Mesajı Gelmiyor
- Bot token'ınızı kontrol edin
- Chat ID'nizin doğru olduğundan emin olun
- Bot'unuza "/start" yazdığınızdan emin olun

### Program Çalışmıyor
- Python'un yüklü olduğunu kontrol edin: `python --version`
- Gerekli kütüphanelerin yüklü olduğunu kontrol edin: `pip list`
- Hata mesajlarını kontrol edin

## 📞 Destek

Sorularınız için issue açabilir veya dokümantasyonu inceleyebilirsiniz.

## 📝 Lisans

Bu proje MIT lisansı altında sunulmaktadır.
