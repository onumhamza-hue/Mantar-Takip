# 🍄 Mantar İş Takip Sistemi - Kullanım Kılavuzu

## 🚀 Kurulum

### 1. Gerekli Paketleri Yükleyin
```powershell
cd C:\mantar_hava_takip
pip install -r requirements_web.txt
```

### 2. Uygulamayı Başlatın
```powershell
streamlit run mantar_is_takip.py
```

Uygulama otomatik olarak tarayıcınızda açılacaktır: http://localhost:8501

## 📋 Menü Yapısı

### 🏠 Ana Sayfa
- Genel özet istatistikler
- Toplam oda sayısı
- Günlük hasat miktarı
- Aylık satış tutarı
- Hızlı erişim linkleri

### 💰 Gider Kalemleri

#### Varsayılan Gider Kalemleri
Sistem otomatik olarak şu gider kalemlerini içerir:
- Kompost (13 Ton): 143.000 TL
- Kompost Nakliyesi: 15.000 TL
- Toprak (Nakliye Dahil): 18.900 TL
- İlaçlar (Vivando vb.): 3.500 TL
- Elektrik ve Su: 20.000 TL
- Boş Kasa (900 adet): 10.800 TL
- Kırık Tabak: 12.000 TL
- Hafriyat / Çöp Nakliyesi: 8.000 TL
- Oda Temizliği: 2.250 TL
- Kompost İndirme: 2.250 TL
- Baskı İşlemi: 2.250 TL
- Toprak İndirme: 2.250 TL
- Toprak Serme: 2.250 TL
- Odanın Tırmığı: 2.250 TL
- Mantar Toplama (Tüm Flaşlar): 1.750 TL
- Oda Boşaltma: 2.250 TL

#### İşlemler
- **Gider Listesi**: Tüm gider kalemlerini görüntüle
- **Yeni Gider Kalemi**: Özel gider kalemleri ekle
- **Düzenle**: Mevcut gider kalemlerini güncelle
- **Sil**: Kullanılmayan giderleri kaldır

### 🏢 Oda Yönetimi

#### Oda Ekleme
1. "Yeni Oda" sekmesine gidin
2. Oda bilgilerini girin:
   - **Oda Adı**: Benzersiz oda ismi (örn: "Oda 1", "A Blok")
   - **Alan (m²)**: Oda büyüklüğü
   - **Kapasite (kg)**: Maksimum üretim kapasitesi
   - **Durum**: Aktif / Hazırlık / Bakım / Pasif
   - **Açıklama**: İsteğe bağlı notlar
3. "Oda Ekle" butonuna tıklayın

#### Oda Giderleri
Her oda için ayrı ayrı gider kaydı:
1. "Oda Giderleri" sekmesine gidin
2. Odayı seçin
3. Gider kalemini seçin (otomatik fiyat gelir)
4. Tutarı ayarlayın
5. Tarih ve açıklama ekleyin
6. "Gider Ekle" butonuna tıklayın

### 📊 Günlük Hasat

#### Hasat Kaydı Ekleme
1. "Hasat Gir" sekmesine gidin
2. Bilgileri doldurun:
   - **Oda**: Hasat yapılan oda
   - **Tarih**: Hasat tarihi
   - **Hasat Miktarı (kg)**: Toplanan mantar miktarı
   - **Kalite**: A, B, C veya Karışık
   - **Açıklama**: İsteğe bağlı notlar
3. "Hasat Kaydet" butonuna tıklayın

#### Hasat Kayıtları
- Tarih aralığı ile filtreleme
- Oda bazında filtreleme
- Toplam/ortalama istatistikler
- Tüm kayıtları görüntüleme

### 🌡️ İklim Verileri

#### İklim Verisi Girişi
Oda iklim koşullarını kaydedin:
1. "Veri Gir" sekmesine gidin
2. Bilgileri doldurun:
   - **Oda**: İlgili oda
   - **Tarih ve Saat**: Ölçüm zamanı
   - **Sıcaklık (°C)**: Oda sıcaklığı
   - **Nem (%)**: Bağıl nem oranı
   - **CO₂ (ppm)**: Karbondioksit seviyesi
3. "Veri Kaydet" butonuna tıklayın

#### İklim Grafikleri
- **Sıcaklık Grafiği**: İdeal aralık (15-22°C) göstergeli
- **Nem Grafiği**: İdeal seviye (%85) göstergeli
- **CO₂ Grafiği**: Kritik seviye (1000 ppm) göstergeli
- Zaman aralığı seçimi (7/14/30 gün veya tümü)
- Oda bazında filtreleme
- Min/max/ortalama istatistikler

### 💵 Satış İşlemleri

#### Satış Kaydı
1. "Satış Gir" sekmesine gidin
2. Bilgileri doldurun:
   - **Oda**: Mantarın toplandığı oda
   - **Tarih**: Satış tarihi
   - **Alan Kişi/Firma**: Müşteri adı
   - **Satış Miktarı (kg)**: Net satış
   - **Birim Fiyat (TL/kg)**: Kg başı fiyat
   - **Fire (kg)**: Satılamayan miktar
   - **Nakliye Ücreti (TL)**: Taşıma gideri
3. Toplam tutar otomatik hesaplanır
4. "Satış Kaydet" butonuna tıklayın

#### Satış Kayıtları
- Tarih aralığı filtreleme
- Tüm satışları görüntüleme
- Toplam satış/gelir/fire istatistikleri
- Ortalama birim fiyat

### 📈 Raporlar ve Grafikler

#### Hasat Analizi
- **Günlük Toplam Hasat**: Bar grafiği
- **Oda Bazında Hasat**: Pasta grafiği
- **Kalite Dağılımı**: Bar grafiği
- Tarih aralığı seçimi

#### Satış Analizi
- **Günlük Satış Geliri**: Çizgi grafiği
- **Müşteri Bazında Satış**: Top 10 müşteri
- **Oda Bazında Fire**: Bar grafiği
- Tarih aralığı seçimi

#### Oda Performans Analizi
- Tüm odaların karşılaştırması
- Toplam hasat/satış/gelir/gider
- Net kâr hesaplaması
- Gelir-gider karşılaştırma grafiği
- Oda bazında kâr grafiği

### 💼 Gelir-Gider Analizi

#### Finansal Özet
4 ana metrik:
- **Toplam Gelir**: Tüm satışların toplamı
- **Toplam Gider**: Tüm harcamaların toplamı
- **Net Kâr**: Gelir - Gider
- **Nakliye Gideri**: Toplam nakliye maliyeti

#### Görselleştirmeler
- **Gelir Dağılımı**: Pasta grafiği
- **Gider Kategorileri**: Pasta grafiği
- **Gider Detayları**: Tablo (tutar ve oran)
- **Gelir-Gider Karşılaştırması**: Bar grafiği

## 📊 Örnek İş Akışı

### 1. İlk Kurulum
```
1. Odaları Ekle (Oda 1, Oda 2, vb.)
2. Gider Kalemlerini Kontrol Et
3. Her Oda İçin Başlangıç Giderlerini Gir
```

### 2. Günlük İşlemler
```
Sabah:
- İklim verilerini kaydet (Sıcaklık, Nem, CO₂)
- Hasat yap ve kaydet

Akşam:
- Satış yap ve kaydet
- Günlük giderleri kaydet
```

### 3. Haftalık İşlemler
```
- Raporları incele
- Oda performanslarını karşılaştır
- İklim grafiklerini kontrol et
- Fire oranlarını analiz et
```

### 4. Aylık İşlemler
```
- Gelir-gider analizini yap
- Kâr marjını hesapla
- Müşteri satış performansını incele
- Gider kalemlerini optimize et
```

## 🎯 İpuçları

### Verimlilik
- **Toplu İşlem**: Birden fazla hasat/satış için art arda veri girin
- **Tarih Filtreleri**: İhtiyacınız olan dönemi seçerek raporları hızlandırın
- **Oda Filtreleri**: Spesifik oda analizleri için filtreleri kullanın

### Veri Kalitesi
- **Düzenli Kayıt**: Her gün iklim verilerini kaydedin
- **Detaylı Açıklama**: Önemli notları açıklama alanına yazın
- **Doğru Tarih**: Her kayıtta doğru tarihi seçin
- **Fire Takibi**: Satış kayıtlarında fire miktarını unutmayın

### Raporlama
- **Karşılaştırma**: Aynı dönemleri farklı odalar için karşılaştırın
- **Trend Analizi**: Uzun dönem grafiklerle trendleri görün
- **Kâr Takibi**: Her oda için net kâr hesaplayın
- **Gider Optimizasyonu**: En yüksek gider kalemlerini belirleyin

## 🔄 Veri Yedekleme

Veritabanı dosyası: `mantar_is_takip.db`

### Yedekleme
```powershell
copy mantar_is_takip.db mantar_is_takip_backup_$(Get-Date -Format "yyyyMMdd").db
```

### Geri Yükleme
```powershell
copy mantar_is_takip_backup_20260502.db mantar_is_takip.db
```

## 📱 Erişim

### Yerel Ağdan Erişim
Başka cihazlardan erişmek için:
```powershell
streamlit run mantar_is_takip.py --server.address 0.0.0.0
```
Ardından: `http://[BİLGİSAYAR-IP]:8501`

### Port Değiştirme
```powershell
streamlit run mantar_is_takip.py --server.port 8080
```

## ⚙️ Özelleştirme

### İdeal Sıcaklık Değerleri
Kodda satır 1047-1048:
```python
fig_sicaklik.add_hline(y=15, line_dash="dash", line_color="blue", annotation_text="İdeal Min (15°C)")
fig_sicaklik.add_hline(y=22, line_dash="dash", line_color="red", annotation_text="İdeal Max (22°C)")
```

### İdeal Nem Değeri
Kodda satır 1054:
```python
fig_nem.add_hline(y=85, line_dash="dash", line_color="green", annotation_text="İdeal (85%)")
```

### CO₂ Kritik Seviye
Kodda satır 1060:
```python
fig_co2.add_hline(y=1000, line_dash="dash", line_color="orange", annotation_text="Kritik (1000 ppm)")
```

## 🆘 Sorun Giderme

### Uygulama Açılmıyor
```powershell
# Python ve Streamlit versiyonunu kontrol edin
python --version
streamlit --version

# Paketleri yeniden yükleyin
pip install -r requirements_web.txt --upgrade
```

### Veritabanı Hatası
```powershell
# Veritabanını sıfırlayın (VERİLER SİLİNİR!)
del mantar_is_takip.db
streamlit run mantar_is_takip.py
```

### Grafik Görünmüyor
```powershell
# Plotly'yi yeniden yükleyin
pip uninstall plotly
pip install plotly==5.19.0
```

## 📞 Destek

Sorunlarınız için:
1. KULLANIM_KILAVUZU.md dosyasını kontrol edin
2. Hata mesajlarını not alın
3. Veritabanını yedekleyin

---

**İyi Çalışmalar! 🍄**
