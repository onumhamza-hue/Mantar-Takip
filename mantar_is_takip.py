#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mantar Üretimi - İş Takip ve Yönetim Sistemi
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date, timedelta
import sqlite3
import json
from pathlib import Path

# Sayfa yapılandırması
st.set_page_config(
    page_title="🍄 Mantar İş Takip Sistemi",
    page_icon="🍄",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Şifre Koruması ────────────────────────────────────────────────────────────
APP_SIFRE = "mantar2024"   # ← Buradan şifrenizi değiştirebilirsiniz

def _sifre_kontrol():
    if st.session_state.get("giris_yapildi"):
        return True
    st.title("🍄 Mantar İş Takip Sistemi")
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.subheader("🔒 Giriş")
        girilen = st.text_input("Şifre", type="password", key="sifre_input")
        if st.button("Giriş Yap", type="primary", use_container_width=True):
            if girilen == APP_SIFRE:
                st.session_state["giris_yapildi"] = True
                st.rerun()
            else:
                st.error("❌ Hatalı şifre!")
    st.stop()

_sifre_kontrol()
# ─────────────────────────────────────────────────────────────────────────────

# ── Veritabanı bağlantısı ─────────────────────────────────────────────────────
import os, re as _re

DB_PATH  = "mantar_is_takip.db"
_DB_URL  = None
IS_CLOUD = False

def _detect_cloud():
    global _DB_URL, IS_CLOUD
    try:
        if "DB_URL" in st.secrets:
            _DB_URL  = st.secrets["DB_URL"]
            IS_CLOUD = True
    except Exception:
        pass

_detect_cloud()

if IS_CLOUD:
    # Streamlit Cloud bazen IPv6 kullanır, Supabase IPv4 ister — zorla IPv4
    import socket as _socket
    _orig_getaddrinfo = _socket.getaddrinfo
    def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return _orig_getaddrinfo(host, port, _socket.AF_INET, type, proto, flags)
    _socket.getaddrinfo = _ipv4_getaddrinfo

if IS_CLOUD:
    import psycopg2 as _psycopg2

    class _PGCursor:
        def __init__(self, cur):
            self._c = cur
            self.lastrowid = None

        @property
        def description(self): return self._c.description

        def execute(self, sql, params=None):
            s = _re.sub(r'\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b',
                        'SERIAL PRIMARY KEY', sql, flags=_re.IGNORECASE)
            s = s.replace('?', '%s')
            # PostgreSQL: ALTER TABLE ADD COLUMN IF NOT EXISTS (transaction abort'u önle)
            s = _re.sub(
                r'\bALTER\s+TABLE\s+(\S+)\s+ADD\s+COLUMN\s+(?!IF\s+NOT\s+EXISTS\s+)',
                r'ALTER TABLE \1 ADD COLUMN IF NOT EXISTS ',
                s, flags=_re.IGNORECASE
            )
            # SQLite → PostgreSQL fonksiyon dönüşümleri
            s = _re.sub(r"strftime\s*\(\s*'%Y-%m'\s*,\s*(\w+)\s*\)",
                        r"TO_CHAR(\1::date, 'YYYY-MM')", s, flags=_re.IGNORECASE)
            s = _re.sub(r"strftime\s*\(\s*'%Y'\s*,\s*(\w+)\s*\)",
                        r"TO_CHAR(\1::date, 'YYYY')", s, flags=_re.IGNORECASE)
            s = _re.sub(r"strftime\s*\(\s*'%m'\s*,\s*(\w+)\s*\)",
                        r"TO_CHAR(\1::date, 'MM')", s, flags=_re.IGNORECASE)
            s = s.replace("datetime('now')", "NOW()")
            stripped = s.strip().upper()
            # Sadece VALUES ile INSERT olan sorgulara RETURNING ekle (INSERT INTO ... SELECT hariç)
            if (stripped.startswith('INSERT') and
                    'RETURNING' not in stripped and
                    'VALUES' in stripped and
                    ' SELECT ' not in stripped):
                s = s.rstrip().rstrip(';') + ' RETURNING id'
                self._c.execute(s, params) if params is not None else self._c.execute(s)
                row = self._c.fetchone()
                self.lastrowid = row[0] if row else None
            else:
                self._c.execute(s, params) if params is not None else self._c.execute(s)
                self.lastrowid = None
            return self

        def executemany(self, sql, params_list):
            s = _re.sub(r'\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b',
                        'SERIAL PRIMARY KEY', sql, flags=_re.IGNORECASE)
            self._c.executemany(s.replace('?', '%s'), params_list)

        def fetchone(self):          return self._c.fetchone()
        def fetchall(self):          return self._c.fetchall()
        def fetchmany(self, n=None): return self._c.fetchmany(n) if n else self._c.fetchmany()
        def close(self):             self._c.close()
        def __iter__(self):          return iter(self._c)

    class _PGConnection:
        def __init__(self, conn):
            self._conn = conn

        def cursor(self):   return _PGCursor(self._conn.cursor())
        def commit(self):   self._conn.commit()
        def close(self):    self._conn.close()
        def rollback(self): self._conn.rollback()


def get_db_connection():
    """Veritabanı bağlantısı al (SQLite yerel / PostgreSQL bulut)"""
    if IS_CLOUD:
        return _PGConnection(_psycopg2.connect(_DB_URL))
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")      # Çok daha hızlı yazma
    conn.execute("PRAGMA synchronous=NORMAL")    # Güvenli ama hızlı
    conn.execute("PRAGMA cache_size=-8000")      # 8 MB bellek cache
    conn.execute("PRAGMA temp_store=MEMORY")     # Geçici tablolar bellekte
    return conn


def _read_sql(sql, conn, params=None):
    """pd.read_sql yerine — SQLite ve PostgreSQL uyumlu"""
    if IS_CLOUD:
        pg_sql = sql.replace('?', '%s')
        # SQLite → PostgreSQL fonksiyon dönüşümleri
        pg_sql = _re.sub(
            r"strftime\s*\(\s*'%Y-%m'\s*,\s*(\w+)\s*\)",
            r"TO_CHAR(\1::date, 'YYYY-MM')", pg_sql, flags=_re.IGNORECASE)
        pg_sql = _re.sub(
            r"strftime\s*\(\s*'%Y'\s*,\s*(\w+)\s*\)",
            r"TO_CHAR(\1::date, 'YYYY')", pg_sql, flags=_re.IGNORECASE)
        pg_sql = _re.sub(
            r"strftime\s*\(\s*'%m'\s*,\s*(\w+)\s*\)",
            r"TO_CHAR(\1::date, 'MM')", pg_sql, flags=_re.IGNORECASE)
        pg_sql = _re.sub(
            r"strftime\s*\(\s*'%d'\s*,\s*(\w+)\s*\)",
            r"TO_CHAR(\1::date, 'DD')", pg_sql, flags=_re.IGNORECASE)
        pg_sql = pg_sql.replace("datetime('now')", "NOW()")
        raw    = conn._conn if hasattr(conn, '_conn') else conn
        cur    = raw.cursor()
        try:
            try:
                cur.execute(pg_sql, params) if params is not None else cur.execute(pg_sql)
            except Exception as e:
                error_text = f"{e}".lower() + " " + repr(e).lower()
                if 'is_plani' in pg_sql.lower() and (
                    'undefinedtable' in error_text or
                    ('relation "is_plani"' in error_text and 'does not exist' in error_text) or
                    'does not exist' in error_text and 'is_plani' in error_text
                ):
                    # PostgreSQL'de hata sonrası transaction durumunu sıfırla
                    try:
                        raw.rollback()
                    except Exception:
                        pass
                    
                    # Yeni cursor ile tabloyu oluştur
                    create_cur = raw.cursor()
                    try:
                        create_cur.execute('''CREATE TABLE IF NOT EXISTS is_plani
                                             (id SERIAL PRIMARY KEY,
                                              oda_id INTEGER NOT NULL,
                                              donem_no INTEGER,
                                              is_adi TEXT NOT NULL,
                                              referans_asama TEXT,
                                              hatirlatma_gun_once INTEGER DEFAULT 0,
                                              plan_tarihi DATE,
                                              aciklama TEXT,
                                              durum TEXT DEFAULT 'Beklemede',
                                              tamamlanma_tarihi DATE,
                                              olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                              FOREIGN KEY (oda_id) REFERENCES odalar(id))''')
                        raw.commit()
                    finally:
                        create_cur.close()
                    
                    # Orijinal sorguyu yeni cursor ile çalıştır
                    retry_cur = raw.cursor()
                    try:
                        retry_cur.execute(pg_sql, params) if params is not None else retry_cur.execute(pg_sql)
                        if retry_cur.description is None:
                            return pd.DataFrame()
                        cols = [d[0].lower() for d in retry_cur.description]
                        rows = retry_cur.fetchall()
                        return pd.DataFrame(rows, columns=cols)
                    finally:
                        retry_cur.close()
                else:
                    raise
            if cur.description is None:
                return pd.DataFrame()
            cols = [d[0].lower() for d in cur.description]
            rows = cur.fetchall()
            return pd.DataFrame(rows, columns=cols)
        finally:
            cur.close()
    return pd.read_sql(sql, conn, params=params)

# ── Performans: Cache'lenmiş lookup verileri ─────────────────────────────────
@st.cache_data(ttl=60)
def _cached_odalar():
    conn = get_db_connection()
    df = _read_sql("SELECT id, oda_adi FROM odalar ORDER BY oda_adi", conn)
    conn.close()
    return df

@st.cache_data(ttl=60)
def _cached_odalar_aktif():
    conn = get_db_connection()
    df = _read_sql("SELECT id, oda_adi FROM odalar WHERE durum='Aktif' ORDER BY oda_adi", conn)
    conn.close()
    return df

@st.cache_data(ttl=60)
def _cached_gider_kalemleri():
    conn = get_db_connection()
    df = _read_sql("SELECT kalem_adi, birim_fiyat FROM gider_kalemleri WHERE aktif=1 ORDER BY kalem_adi", conn)
    conn.close()
    return df

@st.cache_data(ttl=60)
def _cached_cariler():
    conn = get_db_connection()
    df = _read_sql("SELECT id, cari_adi FROM cariler WHERE aktif=1 ORDER BY cari_adi", conn)
    conn.close()
    return df

def _cache_temizle():
    """Veri değişikliğinde lookup cache'lerini sıfırla."""
    _cached_odalar.clear()
    _cached_odalar_aktif.clear()
    _cached_gider_kalemleri.clear()
    _cached_cariler.clear()

def _rerun():
    """Cache temizleyerek yeniden çalıştır — her st.rerun() yerine kullan."""
    _cache_temizle()
    st.rerun()

# ─────────────────────────────────────────────────────────────────────────────

def init_database():
    """Veritabanını başlat"""
    if IS_CLOUD:
        # PostgreSQL: autocommit ile her DDL bağımsız çalışır, hata diğerlerini etkilemez
        raw = _psycopg2.connect(_DB_URL)
        raw.autocommit = True
        conn = _PGConnection(raw)
    else:
        conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Gider kalemleri tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS gider_kalemleri
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  kalem_adi TEXT NOT NULL,
                  birim_fiyat REAL NOT NULL,
                  aciklama TEXT,
                  aktif INTEGER DEFAULT 1,
                  olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Odalar tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS odalar
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  oda_adi TEXT NOT NULL UNIQUE,
                  alan_m2 REAL,
                  kapasite_kg REAL,
                  durum TEXT DEFAULT 'Aktif',
                  aciklama TEXT,
                  olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Oda giderleri tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS oda_giderleri
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  oda_id INTEGER NOT NULL,
                  gider_kalemi TEXT NOT NULL,
                  tutar REAL NOT NULL,
                  tarih DATE NOT NULL,
                  aciklama TEXT,
                  FOREIGN KEY (oda_id) REFERENCES odalar(id))''')
    
    # Günlük hasat tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS gunluk_hasat
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  oda_id INTEGER NOT NULL,
                  tarih DATE NOT NULL,
                  hasat_kg REAL NOT NULL,
                  kalite TEXT,
                  aciklama TEXT,
                  FOREIGN KEY (oda_id) REFERENCES odalar(id))''')
    
    # Satış tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS satislar
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  oda_id INTEGER NOT NULL,
                  tarih DATE NOT NULL,
                  alan_kisi TEXT NOT NULL,
                  satis_kg REAL NOT NULL,
                  birim_fiyat REAL NOT NULL,
                  toplam_tutar REAL NOT NULL,
                  fire_kg REAL DEFAULT 0,
                  nakliye_ucreti REAL DEFAULT 0,
                  aciklama TEXT,
                  FOREIGN KEY (oda_id) REFERENCES odalar(id))''')
    
    # İklim verileri tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS iklim_verileri
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  oda_id INTEGER NOT NULL,
                  tarih DATE NOT NULL,
                  saat TIME NOT NULL,
                  sicaklik REAL,
                  nem REAL,
                  co2 REAL,
                  aciklama TEXT,
                  FOREIGN KEY (oda_id) REFERENCES odalar(id))''')
    
    # İşçiler tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS isciler
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  ad_soyad TEXT NOT NULL,
                  telefon TEXT,
                  pozisyon TEXT,
                  gunluk_ucret REAL DEFAULT 0,
                  saat_ucreti REAL DEFAULT 0,
                  aktif INTEGER DEFAULT 1,
                  olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Puantaj tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS puantaj
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  isci_id INTEGER NOT NULL,
                  tarih DATE NOT NULL,
                  giris_saati TEXT,
                  cikis_saati TEXT,
                  toplam_saat REAL,
                  mesai_saati REAL DEFAULT 0,
                  tatil INTEGER DEFAULT 0,
                  aciklama TEXT,
                  FOREIGN KEY (isci_id) REFERENCES isciler(id))''')
    
    # Migration: tatil sütununu eski veritabanlarına ekle
    try:
        c.execute("ALTER TABLE puantaj ADD COLUMN tatil INTEGER DEFAULT 0")
    except Exception:
        pass  # Sütun zaten mevcut

    # Oda Üretim Takip tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS oda_uretim_takip
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  oda_id INTEGER NOT NULL,
                  donem_no INTEGER DEFAULT 1,
                  ekim_tarihi DATE,
                  baski_tarihi DATE,
                  toprak_serim_tarihi DATE,
                  tirmik_tarihi DATE,
                  hava_verme_tarihi DATE,
                  flash1_tarihi DATE,
                  flash2_tarihi DATE,
                  oda_bosaltma_tarihi DATE,
                  aciklama TEXT,
                  olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (oda_id) REFERENCES odalar(id))''')

    # İş Planı tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS is_plani
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  oda_id INTEGER NOT NULL,
                  donem_no INTEGER,
                  is_adi TEXT NOT NULL,
                  referans_asama TEXT,
                  hatirlatma_gun_once INTEGER DEFAULT 0,
                  plan_tarihi DATE,
                  aciklama TEXT,
                  durum TEXT DEFAULT 'Beklemede',
                  tamamlanma_tarihi DATE,
                  olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (oda_id) REFERENCES odalar(id))''')

    # Cariler tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS cariler
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  cari_adi TEXT NOT NULL,
                  telefon TEXT,
                  adres TEXT,
                  aciklama TEXT,
                  aktif INTEGER DEFAULT 1,
                  olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # Migration: satislar tablosuna cari_id ekle
    try:
        c.execute("ALTER TABLE satislar ADD COLUMN cari_id INTEGER REFERENCES cariler(id)")
    except Exception:
        pass  # Sütun zaten mevcut

    # Mevcut satışlardaki alan_kisi değerlerinden otomatik cari oluştur
    c.execute("SELECT DISTINCT alan_kisi FROM satislar WHERE alan_kisi IS NOT NULL AND alan_kisi != '' AND cari_id IS NULL")
    mevcut_alicilar = c.fetchall()
    for (alan_kisi_val,) in mevcut_alicilar:
        c.execute("SELECT id FROM cariler WHERE cari_adi = ?", (alan_kisi_val,))
        row = c.fetchone()
        if row:
            cari_id_val = row[0]
        else:
            c.execute("INSERT INTO cariler (cari_adi) VALUES (?)", (alan_kisi_val,))
            cari_id_val = c.lastrowid
        c.execute("UPDATE satislar SET cari_id=? WHERE alan_kisi=? AND cari_id IS NULL", (cari_id_val, alan_kisi_val))

    # Cari hareketler tablosu (4 işlem türü: SATIS, ALIS, TAHSILAT, ODEME)
    c.execute('''CREATE TABLE IF NOT EXISTS cari_hareketler
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  cari_id INTEGER NOT NULL REFERENCES cariler(id),
                  tarih DATE NOT NULL,
                  hareket_turu TEXT NOT NULL,
                  tutar REAL NOT NULL,
                  aciklama TEXT,
                  referans_id INTEGER,
                  olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # Migration: cari_hareketler tablosuna miktar ve birim_fiyat sütunları ekle (yoksa)
    try:
        c.execute("ALTER TABLE cari_hareketler ADD COLUMN miktar REAL")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE cari_hareketler ADD COLUMN birim_fiyat REAL")
    except Exception:
        pass

    # Migration: oda_uretim_takip tablosuna 2. Flaş ve Oda Boşaltma sütunları ekle
    try:
        c.execute("ALTER TABLE oda_uretim_takip ADD COLUMN flash2_tarihi DATE")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE oda_uretim_takip ADD COLUMN oda_bosaltma_tarihi DATE")
    except Exception:
        pass

    # Migration: mevcut satislar kayıtlarını cari_hareketler'e aktar (SATIS olarak)
    c.execute("""INSERT INTO cari_hareketler (cari_id, tarih, hareket_turu, tutar, aciklama, referans_id)
                 SELECT s.cari_id, s.tarih, 'SATIS', s.toplam_tutar, s.aciklama, s.id
                 FROM satislar s
                 WHERE s.cari_id IS NOT NULL
                 AND NOT EXISTS (
                     SELECT 1 FROM cari_hareketler ch
                     WHERE ch.hareket_turu = 'SATIS' AND ch.referans_id = s.id
                 )""")

    # Varsayılan gider kalemlerini ekle (yoksa)
    c.execute("SELECT COUNT(*) FROM gider_kalemleri")
    if c.fetchone()[0] == 0:
        varsayilan_giderler = [
            ("Kompost (13 Ton)", 143000, "Ana üretim malzemesi"),
            ("Kompost Nakliyesi", 15000, "Taşıma gideri"),
            ("Toprak (Nakliye Dahil)", 18900, "Örtü toprağı"),
            ("İlaçlar (Vivando vb.)", 3500, "Koruma ve tedavi"),
            ("Elektrik ve Su", 20000, "Enerji giderleri"),
            ("Boş Kasa (900 adet)", 10800, "Toplama kasaları"),
            ("Kırık Tabak", 12000, "Yedek malzeme"),
            ("Hafriyat / Çöp Nakliyesi", 8000, "Atık yönetimi"),
            ("Oda Temizliği", 2250, "İşçilik"),
            ("Kompost İndirme", 2250, "İşçilik"),
            ("Baskı İşlemi", 2250, "İşçilik"),
            ("Toprak İndirme", 2250, "İşçilik"),
            ("Toprak Serme", 2250, "İşçilik"),
            ("Odanın Tırmığı", 2250, "İşçilik"),
            ("Mantar Toplama (Tüm Flaşlar)", 1750, "İşçilik"),
            ("Oda Boşaltma", 2250, "İşçilik")
        ]
        c.executemany("INSERT INTO gider_kalemleri (kalem_adi, birim_fiyat, aciklama) VALUES (?, ?, ?)", 
                      varsayilan_giderler)
    
    if not IS_CLOUD:
        conn.commit()
    conn.close()

# Veritabanını başlat — @st.cache_resource ile sadece BİR KEZ çalışır
@st.cache_resource
def _init_db_once():
    try:
        init_database()
        return None
    except Exception as e:
        return str(e)

_init_err = _init_db_once()
if _init_err:
    st.error(f"❌ Veritabanı başlatma hatası: {_init_err}")
    st.stop()

# Cloud veya mevcut veritabanında yeni tablo eksikse hızlıca oluştur
def _ensure_is_plani_table():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS is_plani
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      oda_id INTEGER NOT NULL,
                      donem_no INTEGER,
                      is_adi TEXT NOT NULL,
                      referans_asama TEXT,
                      hatirlatma_gun_once INTEGER DEFAULT 0,
                      plan_tarihi DATE,
                      aciklama TEXT,
                      durum TEXT DEFAULT 'Beklemede',
                      tamamlanma_tarihi DATE,
                      olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      FOREIGN KEY (oda_id) REFERENCES odalar(id))''')
        if not IS_CLOUD:
            conn.commit()
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass

_ensure_is_plani_table()

# Yan menü
st.sidebar.title("🍄 Mantar İş Takip")
st.sidebar.markdown("---")

menu = st.sidebar.radio(
    "Menü",
    ["🏠 Ana Sayfa", "💰 Gider Kalemleri", "🏢 Oda Yönetimi",
     "📋 Oda Bilgi Kartı",
     "🌱 Üretim Takvimi", "📅 İş Planı",
     "📊 Günlük Hasat", "🌡️ İklim Verileri", "💵 Satış İşlemleri",
     "👷 İşçi Puantaj", "📈 Raporlar ve Grafikler", "💼 Gelir-Gider Analizi",
     "📥 Veri Yedekleme"]
)

st.sidebar.markdown("---")
st.sidebar.info("**Mantar Üretimi İş Takip Sistemi v1.0**")

# Ana Sayfa
if menu == "🏠 Ana Sayfa":
    st.title("🍄 Mantar Üretimi İş Takip Sistemi")
    st.markdown("### Hoş Geldiniz!")
    
    col1, col2, col3 = st.columns(3)
    
    conn = get_db_connection()
    
    # Özet istatistikler
    try:
        with col1:
            st.metric("Toplam Oda Sayısı", int(_read_sql("SELECT COUNT(*) as cnt FROM odalar WHERE durum='Aktif'", conn).iloc[0, 0] or 0))
        
        with col2:
            bugun_val = _read_sql(f"SELECT COALESCE(SUM(hasat_kg), 0) as toplam FROM gunluk_hasat WHERE tarih='{date.today()}'", conn).iloc[0, 0]
            st.metric("Bugünkü Hasat (kg)", f"{float(bugun_val or 0):.2f}")
        
        with col3:
            bu_ay_val = _read_sql(f"SELECT COALESCE(SUM(toplam_tutar), 0) as toplam FROM satislar WHERE strftime('%Y-%m', tarih)='{date.today().strftime('%Y-%m')}'", conn).iloc[0, 0]
            st.metric("Bu Ay Satış (TL)", f"{float(bu_ay_val or 0):,.2f}")
    except Exception as e:
        st.error(f"İstatistik yüklenemedi: {e}")
    
    conn.close()
    
    st.markdown("---")
    st.markdown("### 📋 Hızlı İşlemler")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.info("**💰 Gider Kalemleri**\nGider kalemlerinizi yönetin")
    with col2:
        st.success("**📊 Günlük Hasat**\nHasat verilerinizi girin")
    with col3:
        st.warning("**🌡️ İklim Takibi**\nOda iklim verilerini kaydedin")

# Gider Kalemleri
elif menu == "💰 Gider Kalemleri":
    st.title("💰 Gider Kalemleri Yönetimi")
    
    tab1, tab2 = st.tabs(["📋 Gider Listesi", "➕ Yeni Gider Kalemi"])
    
    with tab1:
        conn = get_db_connection()
        df_giderler = _read_sql("SELECT * FROM gider_kalemleri WHERE aktif=1 ORDER BY kalem_adi", conn)
        conn.close()
        
        if not df_giderler.empty:
            st.caption("💡 Hücreye çift tıklayarak düzenleyin, ardından '💾 Değişiklikleri Kaydet' butonuna basın.")
            _gd_orig = df_giderler[['id', 'kalem_adi', 'birim_fiyat', 'aciklama']].copy()
            _gd_edited = st.data_editor(
                _gd_orig,
                column_config={
                    "id": None,
                    "kalem_adi": st.column_config.TextColumn("Gider Kalemi"),
                    "birim_fiyat": st.column_config.NumberColumn("Birim Fiyat (TL)", min_value=0, step=100, format="%.2f"),
                    "aciklama": st.column_config.TextColumn("Açıklama"),
                },
                hide_index=True,
                use_container_width=True,
                key="gider_editor"
            )
            st.markdown(f"**Toplam: {len(df_giderler)} gider kalemi**")
            if st.button("💾 Değişiklikleri Kaydet", type="primary", key="btn_gider_editor_save"):
                conn = get_db_connection()
                c = conn.cursor()
                for _, _r in _gd_edited.iterrows():
                    if pd.notna(_r.get('id')):
                        c.execute("UPDATE gider_kalemleri SET kalem_adi=?, birim_fiyat=?, aciklama=? WHERE id=?",
                                  (str(_r['kalem_adi']), float(_r['birim_fiyat'] or 0), str(_r['aciklama'] or ''), int(_r['id'])))
                conn.commit()
                conn.close()
                st.success("✅ Değişiklikler kaydedildi!")
                _rerun()
        else:
            st.info("Henüz gider kalemi bulunmuyor.")
    
    with tab2:
        st.subheader("➕ Yeni Gider Kalemi Ekle")
        
        col1, col2 = st.columns(2)
        with col1:
            yeni_kalem = st.text_input("Gider Kalemi Adı *")
            yeni_fiyat = st.number_input("Birim Fiyat (TL) *", min_value=0.0, step=100.0)
        
        with col2:
            yeni_aciklama = st.text_area("Açıklama", key="yeni_gider_aciklama")
        
        if st.button("💾 Kaydet", type="primary"):
            if yeni_kalem and yeni_fiyat >= 0:
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("INSERT INTO gider_kalemleri (kalem_adi, birim_fiyat, aciklama) VALUES (?, ?, ?)",
                        (yeni_kalem, yeni_fiyat, yeni_aciklama))
                conn.commit()
                conn.close()
                st.success("✅ Yeni gider kalemi eklendi!")
                _rerun()
            else:
                st.error("❌ Lütfen tüm zorunlu alanları doldurun!")

# Oda Yönetimi
elif menu == "🏢 Oda Yönetimi":
    st.title("🏢 Oda Yönetimi")
    
    tab1, tab2, tab3 = st.tabs(["📋 Odalar", "➕ Yeni Oda", "💰 Oda Giderleri"])
    
    with tab1:
        conn = get_db_connection()
        df_odalar = _read_sql("SELECT * FROM odalar ORDER BY oda_adi", conn)
        conn.close()
        
        if not df_odalar.empty:
            st.caption("💡 Hücreye çift tıklayarak düzenleyin, ardından '💾 Değişiklikleri Kaydet' butonuna basın.")
            _od_orig = df_odalar[['id', 'oda_adi', 'alan_m2', 'kapasite_kg', 'durum', 'aciklama']].copy()
            _od_edited = st.data_editor(
                _od_orig,
                column_config={
                    "id": None,
                    "oda_adi": st.column_config.TextColumn("Oda Adı"),
                    "alan_m2": st.column_config.NumberColumn("Alan (m²)", min_value=0, step=1, format="%.1f"),
                    "kapasite_kg": st.column_config.NumberColumn("Kapasite (kg)", min_value=0, step=10, format="%.1f"),
                    "durum": st.column_config.SelectboxColumn("Durum", options=["Aktif", "Hazırlık", "Bakım", "Pasif"]),
                    "aciklama": st.column_config.TextColumn("Açıklama"),
                },
                hide_index=True,
                use_container_width=True,
                key="oda_editor"
            )
            if st.button("💾 Değişiklikleri Kaydet", type="primary", key="btn_oda_editor_save"):
                conn = get_db_connection()
                c = conn.cursor()
                for _, _r in _od_edited.iterrows():
                    if pd.notna(_r.get('id')):
                        c.execute("UPDATE odalar SET oda_adi=?, alan_m2=?, kapasite_kg=?, durum=?, aciklama=? WHERE id=?",
                                  (str(_r['oda_adi']), float(_r['alan_m2'] or 0), float(_r['kapasite_kg'] or 0),
                                   str(_r['durum'] or 'Aktif'), str(_r['aciklama'] or ''), int(_r['id'])))
                conn.commit()
                conn.close()
                st.success("✅ Değişiklikler kaydedildi!")
                _rerun()
        else:
            st.info("Henüz oda bulunmuyor.")
    
    with tab2:
        st.subheader("➕ Yeni Oda Ekle")
        
        col1, col2 = st.columns(2)
        with col1:
            oda_adi = st.text_input("Oda Adı *", key="yeni_oda_adi")
            alan_m2 = st.number_input("Alan (m²)", min_value=0.0, step=1.0, key="yeni_alan_m2")
        
        with col2:
            kapasite_kg = st.number_input("Kapasite (kg)", min_value=0.0, step=10.0, key="yeni_kapasite_kg")
            durum = st.selectbox("Durum", ["Aktif", "Hazırlık", "Bakım", "Pasif"], key="yeni_oda_durum")
        
        aciklama = st.text_area("Açıklama", key="yeni_oda_aciklama")
        
        if st.button("💾 Oda Ekle", type="primary"):
            if oda_adi:
                conn = get_db_connection()
                c = conn.cursor()
                try:
                    c.execute("INSERT INTO odalar (oda_adi, alan_m2, kapasite_kg, durum, aciklama) VALUES (?, ?, ?, ?, ?)",
                            (oda_adi, alan_m2, kapasite_kg, durum, aciklama))
                    conn.commit()
                    st.success("✅ Yeni oda eklendi!")
                    _rerun()
                except sqlite3.IntegrityError:
                    st.error("❌ Bu isimde bir oda zaten mevcut!")
                finally:
                    conn.close()
            else:
                st.error("❌ Oda adı zorunludur!")
    
    with tab3:
        st.subheader("💰 Oda Giderleri Ekle")
        
        conn = get_db_connection()
        df_odalar = _read_sql("SELECT id, oda_adi FROM odalar ORDER BY oda_adi", conn)
        df_giderler = _read_sql("SELECT kalem_adi, birim_fiyat FROM gider_kalemleri WHERE aktif=1 ORDER BY kalem_adi", conn)
        conn.close()
        
        if not df_odalar.empty and not df_giderler.empty:
            col1, col2 = st.columns(2)
            
            with col1:
                secili_oda = st.selectbox("Oda Seçin *", df_odalar['oda_adi'].tolist())
                oda_id = df_odalar[df_odalar['oda_adi'] == secili_oda]['id'].values[0]
                
                secili_gider = st.selectbox("Gider Kalemi *", df_giderler['kalem_adi'].tolist())
                varsayilan_tutar = df_giderler[df_giderler['kalem_adi'] == secili_gider]['birim_fiyat'].values[0]
            
            with col2:
                gider_tarih = st.date_input("Tarih *", value=date.today())
                gider_tutar = st.number_input("Tutar (TL) *", value=float(varsayilan_tutar), min_value=0.0, step=100.0)
            
            gider_aciklama = st.text_area("Açıklama")
            
            if st.button("💾 Gider Ekle", type="primary"):
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("INSERT INTO oda_giderleri (oda_id, gider_kalemi, tutar, tarih, aciklama) VALUES (?, ?, ?, ?, ?)",
                        (int(oda_id), secili_gider, float(gider_tutar), str(gider_tarih), gider_aciklama))
                conn.commit()
                conn.close()
                st.success("✅ Gider kaydedildi!")
                _rerun()
            
            # Mevcut giderleri göster
            st.markdown("---")
            st.subheader("📋 Kayıtlı Giderler")
            
            conn = get_db_connection()
            df_kayitli_giderler = _read_sql("""
                SELECT og.id, og.tarih, o.oda_adi, og.gider_kalemi, og.tutar, og.aciklama
                FROM oda_giderleri og
                JOIN odalar o ON og.oda_id = o.id
                ORDER BY og.tarih DESC
                LIMIT 100
            """, conn)
            conn.close()
            
            if not df_kayitli_giderler.empty:
                st.caption("💡 Hücreye çift tıklayarak düzenleyin. Satırı silmek için sol taraftaki 🗑️ ikonuna tıklayın.")
                _og_orig = df_kayitli_giderler.copy()
                _og_edited = st.data_editor(
                    _og_orig,
                    column_config={
                        "id": None,
                        "tarih": st.column_config.DateColumn("Tarih"),
                        "oda_adi": st.column_config.TextColumn("Oda", disabled=True),
                        "gider_kalemi": st.column_config.TextColumn("Gider Kalemi"),
                        "tutar": st.column_config.NumberColumn("Tutar (TL)", min_value=0, step=100, format="%.2f"),
                        "aciklama": st.column_config.TextColumn("Açıklama"),
                    },
                    hide_index=True,
                    use_container_width=True,
                    num_rows="dynamic",
                    key="og_editor"
                )
                if st.button("💾 Değişiklikleri Kaydet", type="primary", key="btn_og_editor_save"):
                    conn = get_db_connection()
                    c = conn.cursor()
                    # Silinen satırları bul (orijinalde olup düzenlenmiş tabloda olmayan id'ler)
                    _og_mevcut_ids = set(_og_edited['id'].dropna().astype(int).tolist())
                    _og_tum_ids    = set(_og_orig['id'].dropna().astype(int).tolist())
                    _silinecekler  = _og_tum_ids - _og_mevcut_ids
                    for _del_id in _silinecekler:
                        c.execute("DELETE FROM oda_giderleri WHERE id=?", (_del_id,))
                    # Düzenlenen satırları güncelle
                    for _, _r in _og_edited.iterrows():
                        if pd.notna(_r.get('id')):
                            c.execute("UPDATE oda_giderleri SET tarih=?, gider_kalemi=?, tutar=?, aciklama=? WHERE id=?",
                                      (str(_r['tarih']), str(_r['gider_kalemi']), float(_r['tutar'] or 0), str(_r['aciklama'] or ''), int(_r['id'])))
                    conn.commit()
                    conn.close()
                    if _silinecekler:
                        st.success(f"✅ {len(_silinecekler)} kayıt silindi, değişiklikler kaydedildi!")
                    else:
                        st.success("✅ Değişiklikler kaydedildi!")
                    _rerun()
        else:
            st.warning("⚠️ Önce oda ve gider kalemleri eklemelisiniz!")

# Günlük Hasat
elif menu == "📊 Günlük Hasat":
    st.title("📊 Günlük Hasat Kayıtları")
    
    tab1, tab2 = st.tabs(["➕ Hasat Gir", "📋 Hasat Kayıtları"])
    
    with tab1:
        df_odalar = _cached_odalar_aktif()
        
        if not df_odalar.empty:
            st.subheader("➕ Yeni Hasat Kaydı")
            
            col1, col2 = st.columns(2)
            
            with col1:
                secili_oda = st.selectbox("Oda Seçin *", df_odalar['oda_adi'].tolist())
                oda_id = df_odalar[df_odalar['oda_adi'] == secili_oda]['id'].values[0]
                hasat_tarih = st.date_input("Tarih *", value=date.today())
            
            with col2:
                hasat_kg = st.number_input("Hasat Miktarı (kg) *", min_value=0.0, step=0.5)
                kalite = st.selectbox("Kalite", ["A Kalite", "B Kalite", "C Kalite", "Karışık"])
            
            hasat_aciklama = st.text_area("Açıklama")
            
            if st.button("💾 Hasat Kaydet", type="primary"):
                if hasat_kg > 0:
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute("INSERT INTO gunluk_hasat (oda_id, tarih, hasat_kg, kalite, aciklama) VALUES (?, ?, ?, ?, ?)",
                            (int(oda_id), str(hasat_tarih), float(hasat_kg), kalite, hasat_aciklama))
                    conn.commit()
                    conn.close()
                    st.success("✅ Hasat kaydedildi!")
                    _rerun()
                else:
                    st.error("❌ Hasat miktarı 0'dan büyük olmalıdır!")
        else:
            st.warning("⚠️ Önce aktif oda eklemelisiniz!")
    
    with tab2:
        st.subheader("📋 Hasat Kayıtları")
        
        # Filtreleme
        col1, col2, col3 = st.columns(3)
        with col1:
            tarih_baslangic = st.date_input("Başlangıç Tarihi", value=date.today() - timedelta(days=30))
        with col2:
            tarih_bitis = st.date_input("Bitiş Tarihi", value=date.today())
        with col3:
            conn = get_db_connection()
            df_odalar = _read_sql("SELECT DISTINCT oda_adi FROM odalar ORDER BY oda_adi", conn)
            conn.close()
            filtre_oda = st.selectbox("Oda Filtresi", ["Tümü"] + df_odalar['oda_adi'].tolist())
        
        # Verileri çek
        conn = get_db_connection()
        if filtre_oda == "Tümü":
            df_hasat = _read_sql(f"""
                SELECT gh.id, gh.tarih, o.oda_adi, gh.hasat_kg, gh.kalite, gh.aciklama
                FROM gunluk_hasat gh
                JOIN odalar o ON gh.oda_id = o.id
                WHERE gh.tarih BETWEEN '{tarih_baslangic}' AND '{tarih_bitis}'
                ORDER BY gh.tarih DESC, o.oda_adi
            """, conn)
        else:
            df_hasat = _read_sql(f"""
                SELECT gh.id, gh.tarih, o.oda_adi, gh.hasat_kg, gh.kalite, gh.aciklama
                FROM gunluk_hasat gh
                JOIN odalar o ON gh.oda_id = o.id
                WHERE gh.tarih BETWEEN '{tarih_baslangic}' AND '{tarih_bitis}'
                AND o.oda_adi = '{filtre_oda}'
                ORDER BY gh.tarih DESC
            """, conn)
        conn.close()
        
        if not df_hasat.empty:
            st.caption("💡 Hücreye çift tıklayarak düzenleyin, ardından '💾 Değişiklikleri Kaydet' butonuna basın.")
            _hs_orig = df_hasat.copy()
            _hs_edited = st.data_editor(
                _hs_orig,
                column_config={
                    "id": None,
                    "tarih": st.column_config.DateColumn("Tarih"),
                    "oda_adi": st.column_config.TextColumn("Oda", disabled=True),
                    "hasat_kg": st.column_config.NumberColumn("Hasat (kg)", min_value=0, step=0.5, format="%.2f"),
                    "kalite": st.column_config.SelectboxColumn("Kalite", options=["A Kalite", "B Kalite", "C Kalite", "Karışık"]),
                    "aciklama": st.column_config.TextColumn("Açıklama"),
                },
                hide_index=True,
                use_container_width=True,
                key="hasat_editor"
            )
            if st.button("💾 Değişiklikleri Kaydet", type="primary", key="btn_hasat_editor_save"):
                conn = get_db_connection()
                c = conn.cursor()
                for _, _r in _hs_edited.iterrows():
                    if pd.notna(_r.get('id')):
                        c.execute("UPDATE gunluk_hasat SET tarih=?, hasat_kg=?, kalite=?, aciklama=? WHERE id=?",
                                  (str(_r['tarih']), float(_r['hasat_kg'] or 0), str(_r['kalite'] or ''), str(_r['aciklama'] or ''), int(_r['id'])))
                conn.commit()
                conn.close()
                st.success("✅ Değişiklikler kaydedildi!")
                _rerun()
            
            # Özet istatistikler
            st.markdown("---")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Toplam Hasat", f"{df_hasat['hasat_kg'].sum():.2f} kg")
            with col2:
                st.metric("Ortalama Günlük", f"{df_hasat['hasat_kg'].mean():.2f} kg")
            with col3:
                st.metric("Kayıt Sayısı", len(df_hasat))
        else:
            st.info("Seçilen kriterlere uygun hasat kaydı bulunamadı.")

# İklim Verileri
elif menu == "🌡️ İklim Verileri":
    st.title("🌡️ İklim Verileri Takibi")
    
    tab1, tab2, tab3 = st.tabs(["➕ Veri Gir", "📊 İklim Grafikleri", "📋 Kayıtlar ve Düzenle"])
    
    with tab1:
        df_odalar = _cached_odalar()
        
        if not df_odalar.empty:
            st.subheader("➕ Yeni İklim Verisi")
            
            col1, col2 = st.columns(2)
            
            with col1:
                secili_oda = st.selectbox("Oda Seçin *", df_odalar['oda_adi'].tolist())
                oda_id = df_odalar[df_odalar['oda_adi'] == secili_oda]['id'].values[0]
                iklim_tarih = st.date_input("Tarih *", value=date.today())
                iklim_saat = st.time_input("Saat *", value=datetime.now().time())
            
            with col2:
                sicaklik = st.number_input("Sıcaklık (°C)", min_value=-10.0, max_value=50.0, value=20.0, step=0.1)
                nem = st.number_input("Nem (%)", min_value=0.0, max_value=100.0, value=80.0, step=1.0)
                co2 = st.number_input("CO₂ (ppm)", min_value=0, max_value=5000, value=800, step=10)
            
            iklim_aciklama = st.text_area("Açıklama")
            
            if st.button("💾 Veri Kaydet", type="primary"):
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("INSERT INTO iklim_verileri (oda_id, tarih, saat, sicaklik, nem, co2, aciklama) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (int(oda_id), str(iklim_tarih), str(iklim_saat), float(sicaklik), float(nem), float(co2), iklim_aciklama))
                conn.commit()
                conn.close()
                st.success("✅ İklim verisi kaydedildi!")
                _rerun()
        else:
            st.warning("⚠️ Önce oda eklemelisiniz!")
    
    with tab2:
        st.subheader("📊 İklim Verileri Grafikleri")
        
        conn = get_db_connection()
        df_odalar = _read_sql("SELECT DISTINCT oda_adi FROM odalar ORDER BY oda_adi", conn)
        conn.close()
        
        if not df_odalar.empty:
            # Filtreleme
            col1, col2 = st.columns(2)
            with col1:
                grafik_oda = st.selectbox("Oda Seçin", df_odalar['oda_adi'].tolist())
            with col2:
                gun_sayisi = st.selectbox("Zaman Aralığı", ["Son 7 Gün", "Son 14 Gün", "Son 30 Gün", "Tümü"])
            
            # Veri çek
            conn = get_db_connection()
            if gun_sayisi == "Tümü":
                df_iklim = _read_sql(f"""
                    SELECT iv.tarih, iv.saat, iv.sicaklik, iv.nem, iv.co2
                    FROM iklim_verileri iv
                    JOIN odalar o ON iv.oda_id = o.id
                    WHERE o.oda_adi = '{grafik_oda}'
                    ORDER BY iv.tarih, iv.saat
                """, conn)
            else:
                gun = int(gun_sayisi.split()[1])
                baslangic = date.today() - timedelta(days=gun)
                df_iklim = _read_sql(f"""
                    SELECT iv.tarih, iv.saat, iv.sicaklik, iv.nem, iv.co2
                    FROM iklim_verileri iv
                    JOIN odalar o ON iv.oda_id = o.id
                    WHERE o.oda_adi = '{grafik_oda}'
                    AND iv.tarih >= '{baslangic}'
                    ORDER BY iv.tarih, iv.saat
                """, conn)
            conn.close()
            
            if not df_iklim.empty:
                # Tarih-saat birleştir
                df_iklim['zaman'] = pd.to_datetime(df_iklim['tarih'] + ' ' + df_iklim['saat'])
                
                # Sıcaklık grafiği
                st.markdown("#### 🌡️ Sıcaklık Grafiği")
                fig_sicaklik = px.line(df_iklim, x='zaman', y='sicaklik', 
                                      title=f'{grafik_oda} - Sıcaklık Takibi',
                                      labels={'zaman': 'Tarih/Saat', 'sicaklik': 'Sıcaklık (°C)'})
                fig_sicaklik.add_hline(y=15, line_dash="dash", line_color="blue", annotation_text="İdeal Min (15°C)")
                fig_sicaklik.add_hline(y=22, line_dash="dash", line_color="red", annotation_text="İdeal Max (22°C)")
                st.plotly_chart(fig_sicaklik, use_container_width=True)
                
                # Nem grafiği
                st.markdown("#### 💧 Nem Grafiği")
                fig_nem = px.line(df_iklim, x='zaman', y='nem',
                                 title=f'{grafik_oda} - Nem Takibi',
                                 labels={'zaman': 'Tarih/Saat', 'nem': 'Nem (%)'})
                fig_nem.add_hline(y=85, line_dash="dash", line_color="green", annotation_text="İdeal (85%)")
                st.plotly_chart(fig_nem, use_container_width=True)
                
                # CO2 grafiği
                st.markdown("#### 🌫️ CO₂ Grafiği")
                fig_co2 = px.line(df_iklim, x='zaman', y='co2',
                                 title=f'{grafik_oda} - CO₂ Takibi',
                                 labels={'zaman': 'Tarih/Saat', 'co2': 'CO₂ (ppm)'})
                fig_co2.add_hline(y=1000, line_dash="dash", line_color="orange", annotation_text="Kritik (1000 ppm)")
                st.plotly_chart(fig_co2, use_container_width=True)
                
                # Özet istatistikler
                st.markdown("---")
                st.subheader("📊 Özet İstatistikler")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Ort. Sıcaklık", f"{df_iklim['sicaklik'].mean():.1f} °C")
                    st.metric("Min Sıcaklık", f"{df_iklim['sicaklik'].min():.1f} °C")
                    st.metric("Max Sıcaklık", f"{df_iklim['sicaklik'].max():.1f} °C")
                with col2:
                    st.metric("Ort. Nem", f"{df_iklim['nem'].mean():.1f} %")
                    st.metric("Min Nem", f"{df_iklim['nem'].min():.1f} %")
                    st.metric("Max Nem", f"{df_iklim['nem'].max():.1f} %")
                with col3:
                    st.metric("Ort. CO₂", f"{df_iklim['co2'].mean():.0f} ppm")
                    st.metric("Min CO₂", f"{df_iklim['co2'].min():.0f} ppm")
                    st.metric("Max CO₂", f"{df_iklim['co2'].max():.0f} ppm")
            else:
                st.info("Seçilen oda için iklim verisi bulunamadı.")
        else:
            st.warning("⚠️ Önce oda eklemelisiniz!")

    with tab3:
        st.subheader("📋 İklim Kayıtları - Düzenle")
        conn = get_db_connection()
        df_odalar_ik3 = _read_sql("SELECT DISTINCT oda_adi FROM odalar ORDER BY oda_adi", conn)
        conn.close()
        if not df_odalar_ik3.empty:
            col1, col2, col3 = st.columns(3)
            with col1:
                ik3_oda = st.selectbox("Oda", ["Tümü"] + df_odalar_ik3['oda_adi'].tolist(), key="ik3_oda")
            with col2:
                ik3_bas = st.date_input("Başlangıç", value=date.today() - timedelta(days=7), key="ik3_bas")
            with col3:
                ik3_bit = st.date_input("Bitiş", value=date.today(), key="ik3_bit")
            ik3_where = f"AND o.oda_adi = '{ik3_oda}'" if ik3_oda != "Tümü" else ""
            conn = get_db_connection()
            df_ik3 = _read_sql(f"""
                SELECT iv.id, iv.tarih, iv.saat, o.oda_adi, iv.sicaklik, iv.nem, iv.co2, iv.aciklama
                FROM iklim_verileri iv
                JOIN odalar o ON iv.oda_id = o.id
                WHERE iv.tarih BETWEEN '{ik3_bas}' AND '{ik3_bit}'
                {ik3_where}
                ORDER BY iv.tarih DESC, iv.saat DESC
                LIMIT 200
            """, conn)
            conn.close()
            if not df_ik3.empty:
                st.caption("💡 Hücreye çift tıklayarak düzenleyin, ardından '💾 Kaydet' butonuna basın.")
                _ik3_orig = df_ik3.copy()
                _ik3_edited = st.data_editor(
                    _ik3_orig,
                    column_config={
                        "id": None,
                        "tarih": st.column_config.DateColumn("Tarih"),
                        "saat": st.column_config.TextColumn("Saat"),
                        "oda_adi": st.column_config.TextColumn("Oda", disabled=True),
                        "sicaklik": st.column_config.NumberColumn("Sıcaklık (°C)", min_value=-10, max_value=50, step=0.1, format="%.1f"),
                        "nem": st.column_config.NumberColumn("Nem (%)", min_value=0, max_value=100, step=1, format="%.1f"),
                        "co2": st.column_config.NumberColumn("CO₂ (ppm)", min_value=0, max_value=5000, step=10),
                        "aciklama": st.column_config.TextColumn("Açıklama"),
                    },
                    hide_index=True,
                    use_container_width=True,
                    key="iklim_editor"
                )
                if st.button("💾 Değişiklikleri Kaydet", type="primary", key="btn_iklim_editor_save"):
                    conn = get_db_connection()
                    c = conn.cursor()
                    for _, _r in _ik3_edited.iterrows():
                        if pd.notna(_r.get('id')):
                            c.execute("UPDATE iklim_verileri SET tarih=?, saat=?, sicaklik=?, nem=?, co2=?, aciklama=? WHERE id=?",
                                      (str(_r['tarih']), str(_r['saat']), float(_r['sicaklik'] or 0), float(_r['nem'] or 0), float(_r['co2'] or 0), str(_r['aciklama'] or ''), int(_r['id'])))
                    conn.commit()
                    conn.close()
                    st.success("✅ Değişiklikler kaydedildi!")
                    _rerun()
            else:
                st.info("Seçilen kriterlere uygun kayıt bulunamadı.")
        else:
            st.warning("⚠️ Önce oda eklemelisiniz!")

# Satış İşlemleri
elif menu == "💵 Satış İşlemleri":
    st.title("💵 Satış İşlemleri")

    tab_hesap, tab_tahsilat, tab_duzenleme, tab_yonetim = st.tabs([
        "📊 Cari Hesap Defteri", "💳 Tahsilat / Ödeme", "✏️ Kayıt Düzenle", "🧑 Cari Yönetim"
    ])

    def _cariler_yukle():
        conn = get_db_connection()
        df = _read_sql("SELECT id, cari_adi FROM cariler WHERE aktif=1 ORDER BY cari_adi", conn)
        conn.close()
        return df

    # ── TAB 1: CARİ HESAP DEFTERİ (seçim + satış/alış giriş + tablo) ─
    with tab_hesap:
        df_cariler_h = _cariler_yukle()

        if df_cariler_h.empty:
            st.warning("⚠️ Önce Cari Yönetim sekmesinden alıcı ekleyin!")
        else:
            col_sec, col_bos = st.columns([2, 3])
            with col_sec:
                secili_cari_h = st.selectbox("👤 Cari Seçin", df_cariler_h['cari_adi'].tolist(), key="cari_h_sec")
            cari_id_h = int(df_cariler_h[df_cariler_h['cari_adi'] == secili_cari_h]['id'].values[0])

            # Bakiye hesapla
            conn = get_db_connection()
            df_satilan = _read_sql("""
                SELECT s.tarih, s.aciklama, s.satis_kg as miktar,
                       s.birim_fiyat as fiyat, s.toplam_tutar as tutar
                FROM satislar s WHERE s.cari_id = ?
                ORDER BY s.tarih ASC, s.id ASC
            """, conn, params=(cari_id_h,))
            df_diger = _read_sql("""
                SELECT tarih, aciklama, tutar, hareket_turu,
                       COALESCE(miktar, 0) as miktar,
                       COALESCE(birim_fiyat, 0) as birim_fiyat
                FROM cari_hareketler
                WHERE cari_id = ? AND hareket_turu != 'SATIS'
                ORDER BY tarih ASC, id ASC
            """, conn, params=(cari_id_h,))
            conn.close()

            toplam_satis    = float(df_satilan['tutar'].sum())    if not df_satilan.empty else 0.0
            toplam_alis     = float(df_diger[df_diger['hareket_turu']=='ALIS']['tutar'].sum())     if not df_diger.empty else 0.0
            toplam_tahsilat = float(df_diger[df_diger['hareket_turu']=='TAHSILAT']['tutar'].sum()) if not df_diger.empty else 0.0
            toplam_odeme    = float(df_diger[df_diger['hareket_turu']=='ODEME']['tutar'].sum())    if not df_diger.empty else 0.0
            net = (toplam_satis + toplam_odeme) - (toplam_alis + toplam_tahsilat)

            # Bakiye durumu
            if net > 0:
                st.success(f"✅ **{secili_cari_h}** size **{net:,.2f} TL** borçlu")
            elif net < 0:
                st.warning(f"⚠️ Siz **{secili_cari_h}**'e **{abs(net):,.2f} TL** borçlusunuz")
            else:
                st.info(f"✔️ **{secili_cari_h}** — Bakiye: 0,00 TL")

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("📤 Satılan Mal", f"{toplam_satis:,.2f} TL")
            with col2:
                st.metric("📥 Alınan Mal", f"{toplam_alis:,.2f} TL")
            with col3:
                st.metric("💵 Tahsilat / Ödeme", f"{toplam_tahsilat:,.2f} / {toplam_odeme:,.2f} TL")
            with col4:
                if net > 0:
                    st.metric("BAKİYE", f"{net:,.2f} TL", delta="Borçlu")
                elif net < 0:
                    st.metric("BAKİYE", f"{abs(net):,.2f} TL", delta="Siz borçlusunuz", delta_color="inverse")
                else:
                    st.metric("BAKİYE", "0,00 TL")

            st.markdown("---")

            # ── Satış Gir / Alış Gir butonları ────────────────────────
            islem_sec = st.radio(
                "➕ İşlem Ekle",
                ["💰 Satış Gir", "🛒 Alış Gir"],
                horizontal=True,
                key="islem_sec_radio"
            )

            if islem_sec == "💰 Satış Gir":
                conn = get_db_connection()
                df_odalar = _read_sql("SELECT id, oda_adi FROM odalar ORDER BY oda_adi", conn)
                conn.close()

                if df_odalar.empty:
                    st.warning("⚠️ Önce oda eklemelisiniz!")
                else:
                    with st.container(border=True):
                        st.markdown(f"**💰 {secili_cari_h} için Satış Girişi**")
                        col1, col2 = st.columns(2)
                        with col1:
                            secili_oda = st.selectbox("Oda *", df_odalar['oda_adi'].tolist(), key="sh_oda")
                            oda_id_s = df_odalar[df_odalar['oda_adi'] == secili_oda]['id'].values[0]
                            satis_tarih = st.date_input("Tarih *", value=date.today(), key="sh_tarih")
                            satis_kg = st.number_input("Satış Miktarı (kg) *", min_value=0.0, step=0.5, key="sh_kg")
                        with col2:
                            birim_fiyat_s = st.number_input("Birim Fiyat (TL/kg) *", min_value=0.0, step=1.0, value=50.0, key="sh_fiyat")
                            fire_kg_s = st.number_input("Fire (kg)", min_value=0.0, step=0.1, value=0.0, key="sh_fire")
                            nakliye_s = st.number_input("Nakliye (TL)", min_value=0.0, step=10.0, value=0.0, key="sh_nakliye")
                            toplam_tutar_s = satis_kg * birim_fiyat_s
                            st.metric("Toplam Tutar", f"{toplam_tutar_s:,.2f} TL")
                        satis_aciklama_s = st.text_input("Açıklama", key="sh_acik")

                        if st.button("💾 Satışı Kaydet", type="primary", key="btn_sh_kaydet"):
                            if satis_kg > 0 and birim_fiyat_s > 0:
                                conn = get_db_connection()
                                c = conn.cursor()
                                c.execute("""INSERT INTO satislar
                                          (oda_id, cari_id, tarih, alan_kisi, satis_kg, birim_fiyat, toplam_tutar, fire_kg, nakliye_ucreti, aciklama)
                                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                        (int(oda_id_s), cari_id_h, str(satis_tarih), secili_cari_h,
                                         float(satis_kg), float(birim_fiyat_s), float(toplam_tutar_s),
                                         float(fire_kg_s), float(nakliye_s), satis_aciklama_s))
                                ref_id = c.lastrowid
                                c.execute("""INSERT INTO cari_hareketler (cari_id, tarih, hareket_turu, tutar, aciklama, referans_id)
                                             VALUES (?, ?, 'SATIS', ?, ?, ?)""",
                                          (cari_id_h, str(satis_tarih), float(toplam_tutar_s), satis_aciklama_s, ref_id))
                                conn.commit()
                                conn.close()
                                st.success("✅ Satış kaydedildi!")
                                _rerun()
                            else:
                                st.error("❌ Satış miktarı ve birim fiyat girilmelidir!")

            else:  # Alış Gir
                with st.container(border=True):
                    st.markdown(f"**🛒 {secili_cari_h} için Alış Girişi**")
                    col1, col2 = st.columns(2)
                    with col1:
                        alis_tarih = st.date_input("Tarih *", value=date.today(), key="ah_tarih")
                        alis_kalem = st.text_input("Alınan Ürün / Kalem *", key="ah_kalem")
                        alis_miktar = st.number_input("Miktar *", min_value=0.0, step=0.5, key="ah_miktar")
                    with col2:
                        alis_birim_fiyat = st.number_input("Birim Fiyat (TL) *", min_value=0.0, step=1.0, key="ah_birim")
                        alis_aciklama = st.text_input("Açıklama", key="ah_acik")
                        alis_toplam = alis_miktar * alis_birim_fiyat
                        st.metric("Toplam Tutar", f"{alis_toplam:,.2f} TL")

                    if st.button("💾 Alışı Kaydet", type="primary", key="btn_ah_kaydet"):
                        if alis_kalem and alis_miktar > 0 and alis_birim_fiyat > 0:
                            acik_full = f"{alis_kalem} ({alis_miktar:g} adet/kg × {alis_birim_fiyat:,.2f} TL)"
                            if alis_aciklama:
                                acik_full += f" — {alis_aciklama}"
                            conn = get_db_connection()
                            c = conn.cursor()
                            c.execute("""INSERT INTO cari_hareketler (cari_id, tarih, hareket_turu, miktar, birim_fiyat, tutar, aciklama)
                                         VALUES (?, ?, 'ALIS', ?, ?, ?, ?)""",
                                      (cari_id_h, str(alis_tarih), float(alis_miktar), float(alis_birim_fiyat), float(alis_toplam), acik_full))
                            conn.commit()
                            conn.close()
                            st.success(f"✅ Alış kaydedildi! ({alis_kalem}: {alis_miktar:g} × {alis_birim_fiyat:,.2f} = {alis_toplam:,.2f} TL)")
                            _rerun()
                        else:
                            st.error("❌ Ürün adı, miktar ve birim fiyat girilmelidir!")

            st.markdown("---")

            # ── İki sütunlu cari tablosu ───────────────────────────────
            col_left, col_right = st.columns(2)

            with col_left:
                st.markdown("### 📤 SATILAN MAL")
                st.caption(f"Toplam: **{toplam_satis:,.2f} TL**")
                if not df_satilan.empty:
                    df_sat_g = df_satilan.copy()
                    df_sat_g.columns = ['Tarih', 'Açıklama', 'Miktar (kg)', 'Birim Fiyat', 'Tutar (TL)']
                    st.dataframe(df_sat_g, use_container_width=True, hide_index=True)
                    st.markdown(f"**Toplam → {toplam_satis:,.2f} TL**")
                else:
                    st.info("Satış kaydı yok")

            with col_right:
                st.markdown("### 📥 ALINAN MAL & ÖDEMELER")
                df_alis_rows = df_diger[df_diger['hareket_turu']=='ALIS'][['tarih','aciklama','miktar','birim_fiyat','tutar']].copy()
                df_alis_rows['miktar_str'] = df_alis_rows.apply(
                    lambda r: f"{r['miktar']:g} × {r['birim_fiyat']:,.2f}" if r['miktar'] > 0 else "", axis=1
                )
                df_alis_display = df_alis_rows[['tarih','aciklama','miktar_str','tutar']].copy()
                df_alis_display.columns = ['Tarih', 'Açıklama', 'Miktar × Fiyat', 'Tutar (TL)']

                df_nakit_rows = df_diger[df_diger['hareket_turu'].isin(['TAHSILAT','ODEME'])].copy()
                df_nakit_rows['aciklama'] = df_nakit_rows.apply(
                    lambda r: f"{'💵 Tahsilat' if r['hareket_turu']=='TAHSILAT' else '💸 Ödeme'} — {r['aciklama']}" if r['aciklama'] else ('💵 Tahsilat' if r['hareket_turu']=='TAHSILAT' else '💸 Ödeme'), axis=1
                )
                df_nakit_rows = df_nakit_rows[['tarih','aciklama','tutar']].copy()
                df_nakit_rows.insert(2, 'Miktar × Fiyat', '')
                df_nakit_rows.columns = ['Tarih', 'Açıklama', 'Miktar × Fiyat', 'Tutar (TL)']

                df_sag = pd.concat([df_alis_display, df_nakit_rows], ignore_index=True)
                if not df_sag.empty:
                    df_sag = df_sag.sort_values('Tarih').reset_index(drop=True)
                    toplam_sag = toplam_alis + toplam_tahsilat + toplam_odeme
                    st.caption(f"Alış: **{toplam_alis:,.2f} TL** | Tahsilat: **{toplam_tahsilat:,.2f} TL** | Ödeme: **{toplam_odeme:,.2f} TL**")
                    st.dataframe(df_sag, use_container_width=True, hide_index=True)
                    st.markdown(f"**Toplam → {toplam_sag:,.2f} TL**")
                else:
                    st.info("Alış / ödeme kaydı yok")

            # ── Kronolojik ekstre ─────────────────────────────────────
            st.markdown("---")
            st.markdown("### 📋 Tüm Hareketler (Kronolojik Ekstre)")
            ekstre_rows = []
            for _, r in df_satilan.iterrows():
                miktar_str = f"{r['miktar']:g} kg" if r['miktar'] and r['miktar'] > 0 else ""
                ekstre_rows.append({'Tarih': r['tarih'], 'Tür': '💰 Satış', 'Miktar': miktar_str,
                                    'Açıklama': r['aciklama'],
                                    'Borç (TL)': r['tutar'], 'Alacak (TL)': 0.0})
            for _, r in df_diger.iterrows():
                tur_adi = {'ALIS':'🛒 Alış','TAHSILAT':'💵 Tahsilat','ODEME':'💸 Ödeme'}.get(r['hareket_turu'], r['hareket_turu'])
                miktar_str = f"{r['miktar']:g} × {r['birim_fiyat']:,.2f}" if r.get('miktar', 0) and r['miktar'] > 0 else ""
                if r['hareket_turu'] == 'ODEME':
                    ekstre_rows.append({'Tarih': r['tarih'], 'Tür': tur_adi, 'Miktar': miktar_str,
                                        'Açıklama': r['aciklama'],
                                        'Borç (TL)': r['tutar'], 'Alacak (TL)': 0.0})
                else:
                    ekstre_rows.append({'Tarih': r['tarih'], 'Tür': tur_adi, 'Miktar': miktar_str,
                                        'Açıklama': r['aciklama'],
                                        'Borç (TL)': 0.0, 'Alacak (TL)': r['tutar']})
            if ekstre_rows:
                df_ekstre = pd.DataFrame(ekstre_rows).sort_values('Tarih').reset_index(drop=True)
                bak, bakiyeler = 0.0, []
                for _, row in df_ekstre.iterrows():
                    bak += row['Borç (TL)'] - row['Alacak (TL)']
                    bakiyeler.append(round(bak, 2))
                df_ekstre['Bakiye (TL)'] = bakiyeler
                # Sütun sırası: Tarih, Tür, Miktar, Açıklama, Borç, Alacak, Bakiye
                df_ekstre = df_ekstre[['Tarih', 'Tür', 'Miktar', 'Açıklama', 'Borç (TL)', 'Alacak (TL)', 'Bakiye (TL)']]
                st.dataframe(df_ekstre, use_container_width=True, hide_index=True)
            else:
                st.info("Bu cariye ait hareket kaydı yok.")

    # ── TAB 2: TAHSİLAT / ÖDEME ───────────────────────────────────────
    with tab_tahsilat:
        df_cariler_t3 = _cariler_yukle()
        st.subheader("💳 Tahsilat / Ödeme")
        st.caption("**Tahsilat**: Karşı taraf size nakit ödedi  |  **Ödeme**: Siz karşı tarafa nakit ödediniz")

        if df_cariler_t3.empty:
            st.warning("⚠️ Önce Cari Yönetim sekmesinden cari ekleyin!")
        else:
            col1, col2 = st.columns(2)
            with col1:
                secili_cari_t = st.selectbox("Cari *", df_cariler_t3['cari_adi'].tolist(), key="t1_cari")
                cari_id_t = int(df_cariler_t3[df_cariler_t3['cari_adi'] == secili_cari_t]['id'].values[0])
                tahsilat_tarih = st.date_input("Tarih *", value=date.today(), key="t1_tarih")
            with col2:
                hareket_turu_sec = st.radio(
                    "İşlem Türü *",
                    ["💵 Tahsilat (onlar bize ödedi)", "💸 Ödeme (biz onlara ödedik)"],
                    key="t1_tur"
                )
                hareket_kodu = "TAHSILAT" if hareket_turu_sec.startswith("💵") else "ODEME"
                tahsilat_tutar = st.number_input("Tutar (TL) *", min_value=0.0, step=1.0, key="t1_tutar")
            tahsilat_aciklama = st.text_area("Açıklama", key="t1_acik")

            if st.button("💾 Kaydet", type="primary", key="btn_t1_kaydet"):
                if tahsilat_tutar > 0:
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute("""INSERT INTO cari_hareketler (cari_id, tarih, hareket_turu, tutar, aciklama)
                                 VALUES (?, ?, ?, ?, ?)""",
                              (cari_id_t, str(tahsilat_tarih), hareket_kodu,
                               float(tahsilat_tutar), tahsilat_aciklama))
                    conn.commit()
                    conn.close()
                    st.success("✅ Kayıt eklendi!")
                    _rerun()
                else:
                    st.error("❌ Tutar girilmelidir!")

    # ── TAB 3: KAYIT DÜZENLE ──────────────────────────────────────────
    with tab_duzenleme:
        st.subheader("✏️ Geçmiş Kayıtları Düzenle")
        df_cariler_duz = _cariler_yukle()
        if df_cariler_duz.empty:
            st.warning("⚠️ Önce Cari Yönetim sekmesinden cari ekleyin!")
        else:
            _duz_cari = st.selectbox("Cari Seçin", df_cariler_duz['cari_adi'].tolist(), key="duz_cari_sel")
            _duz_cari_id = int(df_cariler_duz[df_cariler_duz['cari_adi'] == _duz_cari]['id'].values[0])

            duz_tab1, duz_tab2 = st.tabs(["💰 Satış Kayıtları", "📋 Alış / Tahsilat / Ödeme"])

            with duz_tab1:
                conn = get_db_connection()
                _duz_sat = _read_sql("""
                    SELECT s.id, s.tarih, o.oda_adi, s.satis_kg, s.birim_fiyat, s.toplam_tutar,
                           s.fire_kg, s.nakliye_ucreti, s.aciklama
                    FROM satislar s
                    JOIN odalar o ON s.oda_id = o.id
                    WHERE s.cari_id = ?
                    ORDER BY s.tarih DESC
                """, conn, params=(_duz_cari_id,))
                conn.close()
                if not _duz_sat.empty:
                    st.caption("💡 Hücreye çift tıklayarak düzenleyin, ardından '💾 Kaydet' butonuna basın.")
                    _duzsat_orig = _duz_sat.copy()
                    _duzsat_edited = st.data_editor(
                        _duzsat_orig,
                        column_config={
                            "id": None,
                            "tarih": st.column_config.DateColumn("Tarih"),
                            "oda_adi": st.column_config.TextColumn("Oda", disabled=True),
                            "satis_kg": st.column_config.NumberColumn("Satış (kg)", min_value=0, step=0.5, format="%.2f"),
                            "birim_fiyat": st.column_config.NumberColumn("Birim Fiyat", min_value=0, step=1, format="%.2f"),
                            "toplam_tutar": st.column_config.NumberColumn("Toplam (TL)", min_value=0, step=1, format="%.2f"),
                            "fire_kg": st.column_config.NumberColumn("Fire (kg)", min_value=0, step=0.1, format="%.2f"),
                            "nakliye_ucreti": st.column_config.NumberColumn("Nakliye (TL)", min_value=0, step=1, format="%.2f"),
                            "aciklama": st.column_config.TextColumn("Açıklama"),
                        },
                        hide_index=True,
                        use_container_width=True,
                        key="duz_sat_editor"
                    )
                    if st.button("💾 Değişiklikleri Kaydet", type="primary", key="btn_duzsat_save"):
                        conn = get_db_connection()
                        c = conn.cursor()
                        for _, _r in _duzsat_edited.iterrows():
                            if pd.notna(_r.get('id')):
                                c.execute("UPDATE satislar SET tarih=?, satis_kg=?, birim_fiyat=?, toplam_tutar=?, fire_kg=?, nakliye_ucreti=?, aciklama=? WHERE id=?",
                                          (str(_r['tarih']), float(_r['satis_kg'] or 0), float(_r['birim_fiyat'] or 0),
                                           float(_r['toplam_tutar'] or 0), float(_r['fire_kg'] or 0),
                                           float(_r['nakliye_ucreti'] or 0), str(_r['aciklama'] or ''), int(_r['id'])))
                        conn.commit()
                        conn.close()
                        st.success("✅ Değişiklikler kaydedildi!")
                        _rerun()
                else:
                    st.info("Bu cariye ait satış kaydı yok.")

            with duz_tab2:
                conn = get_db_connection()
                _duz_ch = _read_sql("""
                    SELECT id, tarih, hareket_turu, tutar, aciklama
                    FROM cari_hareketler
                    WHERE cari_id = ? AND hareket_turu != 'SATIS'
                    ORDER BY tarih DESC
                """, conn, params=(_duz_cari_id,))
                conn.close()
                if not _duz_ch.empty:
                    st.caption("💡 Hücreye çift tıklayarak düzenleyin, ardından '💾 Kaydet' butonuna basın.")
                    _duzch_orig = _duz_ch.copy()
                    _duzch_edited = st.data_editor(
                        _duzch_orig,
                        column_config={
                            "id": None,
                            "tarih": st.column_config.DateColumn("Tarih"),
                            "hareket_turu": st.column_config.SelectboxColumn("Tür", options=["ALIS", "TAHSILAT", "ODEME"]),
                            "tutar": st.column_config.NumberColumn("Tutar (TL)", min_value=0, step=1, format="%.2f"),
                            "aciklama": st.column_config.TextColumn("Açıklama"),
                        },
                        hide_index=True,
                        use_container_width=True,
                        key="duz_ch_editor"
                    )
                    if st.button("💾 Değişiklikleri Kaydet", type="primary", key="btn_duzch_save"):
                        conn = get_db_connection()
                        c = conn.cursor()
                        for _, _r in _duzch_edited.iterrows():
                            if pd.notna(_r.get('id')):
                                c.execute("UPDATE cari_hareketler SET tarih=?, hareket_turu=?, tutar=?, aciklama=? WHERE id=?",
                                          (str(_r['tarih']), str(_r['hareket_turu']), float(_r['tutar'] or 0), str(_r['aciklama'] or ''), int(_r['id'])))
                        conn.commit()
                        conn.close()
                        st.success("✅ Değişiklikler kaydedildi!")
                        _rerun()
                else:
                    st.info("Bu cariye ait alış/tahsilat/ödeme kaydı yok.")

    # ── TAB 4: CARİ YÖNETİM ───────────────────────────────────────────
    with tab_yonetim:
        st.subheader("🧑 Cari Yönetim")

        cari_tab1, cari_tab2 = st.tabs(["📋 Cariler", "➕ Yeni Cari"])

        with cari_tab1:
            conn = get_db_connection()
            df_tm_cariler = _read_sql("SELECT * FROM cariler WHERE aktif=1 ORDER BY cari_adi", conn)
            conn.close()

            if not df_tm_cariler.empty:
                st.caption("💡 Hücreye çift tıklayarak düzenleyin, ardından '💾 Kaydet' butonuna basın.")
                _cr_orig = df_tm_cariler[['id', 'cari_adi', 'telefon', 'adres', 'aciklama']].copy()
                _cr_edited = st.data_editor(
                    _cr_orig,
                    column_config={
                        "id": None,
                        "cari_adi": st.column_config.TextColumn("Cari Adı"),
                        "telefon": st.column_config.TextColumn("Telefon"),
                        "adres": st.column_config.TextColumn("Adres"),
                        "aciklama": st.column_config.TextColumn("Açıklama"),
                    },
                    hide_index=True,
                    use_container_width=True,
                    key="cari_editor"
                )
                if st.button("💾 Değişiklikleri Kaydet", type="primary", key="btn_cari_editor_save"):
                    conn = get_db_connection()
                    c = conn.cursor()
                    for _, _r in _cr_edited.iterrows():
                        if pd.notna(_r.get('id')):
                            c.execute("UPDATE cariler SET cari_adi=?, telefon=?, adres=?, aciklama=? WHERE id=?",
                                      (str(_r['cari_adi']), str(_r['telefon'] or ''), str(_r['adres'] or ''), str(_r['aciklama'] or ''), int(_r['id'])))
                            c.execute("UPDATE satislar SET alan_kisi=? WHERE cari_id=?", (str(_r['cari_adi']), int(_r['id'])))
                    conn.commit()
                    conn.close()
                    st.success("✅ Değişiklikler kaydedildi!")
                    _rerun()
            else:
                st.info("Henüz cari kaydı yok.")

        with cari_tab2:
            st.markdown("**➕ Yeni Alıcı / Cari Ekle**")
            col1, col2 = st.columns(2)
            with col1:
                yeni_c_adi  = st.text_input("Cari Adı *", key="nc_adi")
                yeni_c_tel  = st.text_input("Telefon",    key="nc_tel")
            with col2:
                yeni_c_adres = st.text_input("Adres",     key="nc_adres")
                yeni_c_acik  = st.text_area("Açıklama",   key="nc_acik")

            if st.button("💾 Cari Ekle", type="primary"):
                if yeni_c_adi:
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute("INSERT INTO cariler (cari_adi, telefon, adres, aciklama) VALUES (?, ?, ?, ?)",
                              (yeni_c_adi, yeni_c_tel, yeni_c_adres, yeni_c_acik))
                    conn.commit()
                    conn.close()
                    st.success(f"✅ '{yeni_c_adi}' carisi eklendi!")
                    _rerun()
                else:
                    st.error("❌ Cari adı zorunludur!")

# Raporlar ve Grafikler
elif menu == "📈 Raporlar ve Grafikler":
    st.title("📈 Raporlar ve Grafikler")
    
    tab1, tab2, tab3 = st.tabs(["📊 Hasat Analizi", "💰 Satış Analizi", "🏢 Oda Performansı"])
    
    with tab1:
        st.subheader("📊 Hasat Analizi")
        
        # Tarih aralığı
        col1, col2 = st.columns(2)
        with col1:
            baslangic = st.date_input("Başlangıç", value=date.today() - timedelta(days=30), key="hasat_rp_baslangic")
        with col2:
            bitis = st.date_input("Bitiş", value=date.today(), key="hasat_rp_bitis")
        
        conn = get_db_connection()
        df_hasat_analiz = _read_sql(f"""
            SELECT gh.tarih, o.oda_adi, gh.hasat_kg, gh.kalite
            FROM gunluk_hasat gh
            JOIN odalar o ON gh.oda_id = o.id
            WHERE gh.tarih BETWEEN '{baslangic}' AND '{bitis}'
            ORDER BY gh.tarih
        """, conn)
        conn.close()
        
        if not df_hasat_analiz.empty:
            # Günlük toplam hasat grafiği
            daily_hasat = df_hasat_analiz.groupby('tarih')['hasat_kg'].sum().reset_index()
            fig_daily = px.bar(daily_hasat, x='tarih', y='hasat_kg',
                              title='Günlük Toplam Hasat',
                              labels={'tarih': 'Tarih', 'hasat_kg': 'Hasat (kg)'})
            st.plotly_chart(fig_daily, use_container_width=True)
            
            # Oda bazında hasat
            oda_hasat = df_hasat_analiz.groupby('oda_adi')['hasat_kg'].sum().reset_index()
            fig_oda = px.pie(oda_hasat, values='hasat_kg', names='oda_adi',
                            title='Oda Bazında Toplam Hasat')
            st.plotly_chart(fig_oda, use_container_width=True)
            
            # Kalite dağılımı
            if 'kalite' in df_hasat_analiz.columns:
                kalite_dagilim = df_hasat_analiz.groupby('kalite')['hasat_kg'].sum().reset_index()
                fig_kalite = px.bar(kalite_dagilim, x='kalite', y='hasat_kg',
                                   title='Kalite Bazında Hasat Dağılımı',
                                   labels={'kalite': 'Kalite', 'hasat_kg': 'Hasat (kg)'})
                st.plotly_chart(fig_kalite, use_container_width=True)
        else:
            st.info("Seçilen tarih aralığında hasat verisi bulunamadı.")
    
    with tab2:
        st.subheader("💰 Satış Analizi")
        
        # Tarih aralığı
        col1, col2 = st.columns(2)
        with col1:
            baslangic_satis = st.date_input("Başlangıç", value=date.today() - timedelta(days=30), key="satis_rp_baslangic")
        with col2:
            bitis_satis = st.date_input("Bitiş", value=date.today(), key="satis_rp_bitis")
        
        conn = get_db_connection()
        df_satis_analiz = _read_sql(f"""
            SELECT s.tarih, o.oda_adi, s.alan_kisi, s.satis_kg, s.toplam_tutar, s.fire_kg
            FROM satislar s
            JOIN odalar o ON s.oda_id = o.id
            WHERE s.tarih BETWEEN '{baslangic_satis}' AND '{bitis_satis}'
            ORDER BY s.tarih
        """, conn)
        conn.close()
        
        if not df_satis_analiz.empty:
            # Günlük satış geliri
            daily_satis = df_satis_analiz.groupby('tarih')['toplam_tutar'].sum().reset_index()
            fig_satis = px.line(daily_satis, x='tarih', y='toplam_tutar',
                               title='Günlük Satış Geliri',
                               labels={'tarih': 'Tarih', 'toplam_tutar': 'Gelir (TL)'})
            st.plotly_chart(fig_satis, use_container_width=True)
            
            # Müşteri bazında satış
            musteri_satis = df_satis_analiz.groupby('alan_kisi')['toplam_tutar'].sum().reset_index().sort_values('toplam_tutar', ascending=False).head(10)
            fig_musteri = px.bar(musteri_satis, x='alan_kisi', y='toplam_tutar',
                                title='En Çok Satış Yapılan Müşteriler (Top 10)',
                                labels={'alan_kisi': 'Müşteri', 'toplam_tutar': 'Toplam Satış (TL)'})
            st.plotly_chart(fig_musteri, use_container_width=True)
            
            # Fire analizi
            if df_satis_analiz['fire_kg'].sum() > 0:
                oda_fire = df_satis_analiz.groupby('oda_adi')['fire_kg'].sum().reset_index()
                fig_fire = px.bar(oda_fire, x='oda_adi', y='fire_kg',
                                 title='Oda Bazında Toplam Fire',
                                 labels={'oda_adi': 'Oda', 'fire_kg': 'Fire (kg)'})
                st.plotly_chart(fig_fire, use_container_width=True)
        else:
            st.info("Seçilen tarih aralığında satış verisi bulunamadı.")
    
    with tab3:
        st.subheader("🏢 Oda Performans Analizi")
        
        conn = get_db_connection()
        
        # Oda bazında toplam hasat ve satış (correlated subquery — çoklu JOIN şişirmesini önler)
        df_oda_perf = _read_sql("""
            SELECT
                o.oda_adi,
                COALESCE((SELECT SUM(gh.hasat_kg)    FROM gunluk_hasat   gh WHERE gh.oda_id = o.id), 0) as toplam_hasat,
                COALESCE((SELECT SUM(s.satis_kg)     FROM satislar        s WHERE s.oda_id  = o.id), 0) as toplam_satis,
                COALESCE((SELECT SUM(s.toplam_tutar) FROM satislar        s WHERE s.oda_id  = o.id), 0) as toplam_gelir,
                COALESCE((SELECT SUM(og.tutar)       FROM oda_giderleri  og WHERE og.oda_id = o.id), 0) as toplam_gider
            FROM odalar o
            ORDER BY o.oda_adi
        """, conn)
        conn.close()
        
        if not df_oda_perf.empty:
            df_oda_perf['net_kar'] = df_oda_perf['toplam_gelir'] - df_oda_perf['toplam_gider']
            
            # Oda performans tablosu
            st.dataframe(
                df_oda_perf.rename(columns={
                    'oda_adi': 'Oda',
                    'toplam_hasat': 'Toplam Hasat (kg)',
                    'toplam_satis': 'Toplam Satış (kg)',
                    'toplam_gelir': 'Toplam Gelir (TL)',
                    'toplam_gider': 'Toplam Gider (TL)',
                    'net_kar': 'Net Kâr (TL)'
                }),
                use_container_width=True
            )
            
            # Gelir-Gider karşılaştırması
            fig_gelir_gider = go.Figure()
            fig_gelir_gider.add_trace(go.Bar(name='Gelir', x=df_oda_perf['oda_adi'], y=df_oda_perf['toplam_gelir']))
            fig_gelir_gider.add_trace(go.Bar(name='Gider', x=df_oda_perf['oda_adi'], y=df_oda_perf['toplam_gider']))
            fig_gelir_gider.update_layout(title='Oda Bazında Gelir-Gider Karşılaştırması',
                                         barmode='group',
                                         xaxis_title='Oda',
                                         yaxis_title='Tutar (TL)')
            st.plotly_chart(fig_gelir_gider, use_container_width=True)
            
            # Net kâr grafiği
            fig_kar = px.bar(df_oda_perf, x='oda_adi', y='net_kar',
                            title='Oda Bazında Net Kâr',
                            labels={'oda_adi': 'Oda', 'net_kar': 'Net Kâr (TL)'},
                            color='net_kar',
                            color_continuous_scale=['red', 'yellow', 'green'])
            st.plotly_chart(fig_kar, use_container_width=True)
        else:
            st.info("Henüz performans verisi bulunmuyor.")

# İşçi Puantaj
elif menu == "👷 İşçi Puantaj":
    st.title("👷 İşçi Puantaj Sistemi")
    
    tab1, tab2, tab3, tab4 = st.tabs(["👥 İşçi Listesi", "➕ İşçi Ekle", "📅 Puantaj Gir", "📊 Puantaj Raporları"])
    
    with tab1:
        st.subheader("👥 Kayıtlı İşçiler")
        
        conn = get_db_connection()
        df_isciler = _read_sql("SELECT * FROM isciler WHERE aktif=1 ORDER BY ad_soyad", conn)
        conn.close()
        
        if not df_isciler.empty:
            st.caption("💡 Hücreye çift tıklayarak düzenleyin, ardından '💾 Değişiklikleri Kaydet' butonuna basın.")
            _is_orig = df_isciler[['id', 'ad_soyad', 'telefon', 'pozisyon', 'gunluk_ucret', 'saat_ucreti']].copy()
            _is_edited = st.data_editor(
                _is_orig,
                column_config={
                    "id": None,
                    "ad_soyad": st.column_config.TextColumn("Ad Soyad"),
                    "telefon": st.column_config.TextColumn("Telefon"),
                    "pozisyon": st.column_config.TextColumn("Pozisyon"),
                    "gunluk_ucret": st.column_config.NumberColumn("Günlük Ücret (TL)", min_value=0, step=50, format="%.2f"),
                    "saat_ucreti": st.column_config.NumberColumn("Saat Ücreti (TL)", min_value=0, step=5, format="%.2f"),
                },
                hide_index=True,
                use_container_width=True,
                key="isci_editor"
            )
            if st.button("💾 Değişiklikleri Kaydet", type="primary", key="btn_isci_editor_save"):
                conn = get_db_connection()
                c = conn.cursor()
                for _, _r in _is_edited.iterrows():
                    if pd.notna(_r.get('id')):
                        c.execute("UPDATE isciler SET ad_soyad=?, telefon=?, pozisyon=?, gunluk_ucret=?, saat_ucreti=? WHERE id=?",
                                  (str(_r['ad_soyad']), str(_r['telefon'] or ''), str(_r['pozisyon'] or ''),
                                   float(_r['gunluk_ucret'] or 0), float(_r['saat_ucreti'] or 0), int(_r['id'])))
                conn.commit()
                conn.close()
                st.success("✅ Değişiklikler kaydedildi!")
                _rerun()
        else:
            st.info("Henüz işçi kaydı bulunmuyor.")
    
    with tab2:
        st.subheader("➕ Yeni İşçi Ekle")
        
        col1, col2 = st.columns(2)
        
        with col1:
            ad_soyad = st.text_input("Ad Soyad *", key="yeni_ad_soyad")
            telefon = st.text_input("Telefon", key="yeni_telefon")
            pozisyon = st.text_input("Pozisyon", placeholder="Örn: Hasat İşçisi, Teknik Eleman", key="yeni_pozisyon")
        
        with col2:
            gunluk_ucret = st.number_input("Günlük Ücret (TL)", min_value=0.0, step=50.0, value=500.0, key="yeni_gunluk_ucret")
            saat_ucreti = st.number_input("Saat Ücreti (TL)", min_value=0.0, step=5.0, value=50.0, key="yeni_saat_ucreti")
            st.info("💡 Günlük ücret veya saat ücreti girebilirsiniz")
        
        if st.button("💾 İşçi Ekle", type="primary"):
            if ad_soyad:
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("INSERT INTO isciler (ad_soyad, telefon, pozisyon, gunluk_ucret, saat_ucreti) VALUES (?, ?, ?, ?, ?)",
                        (ad_soyad, telefon, pozisyon, gunluk_ucret, saat_ucreti))
                conn.commit()
                conn.close()
                st.success("✅ Yeni işçi eklendi!")
                _rerun()
            else:
                st.error("❌ Ad Soyad zorunludur!")
    
    with tab3:
        st.subheader("📅 Günlük Puantaj Kaydı")
        
        conn = get_db_connection()
        df_isciler = _read_sql("SELECT id, ad_soyad FROM isciler WHERE aktif=1 ORDER BY ad_soyad", conn)
        conn.close()
        
        if not df_isciler.empty:
            col1, col2 = st.columns(2)
            
            with col1:
                secili_isci = st.selectbox("İşçi Seçin *", df_isciler['ad_soyad'].tolist())
                isci_id = df_isciler[df_isciler['ad_soyad'] == secili_isci]['id'].values[0]
                
                puantaj_tarih = st.date_input("Tarih *", value=date.today())
                tatil_gun = st.checkbox("🏖️ Tatil / İzin Günü")
            
            with col2:
                if tatil_gun:
                    giris_saati = None
                    cikis_saati = None
                    toplam_saat = 0.0
                    mesai_saati = 0.0
                    st.info("🏖️ Tatil veya izin günü olarak kaydedilecek.")
                else:
                    giris_saati = st.time_input("Giriş Saati", value=datetime.strptime("08:00", "%H:%M").time())
                    cikis_saati = st.time_input("Çıkış Saati", value=datetime.strptime("17:00", "%H:%M").time())
                    giris_dt = datetime.combine(date.today(), giris_saati)
                    cikis_dt = datetime.combine(date.today(), cikis_saati)
                    toplam_saat = (cikis_dt - giris_dt).seconds / 3600
                    st.metric("Toplam Çalışma Saati", f"{toplam_saat:.1f} saat")
                    mesai_saati = st.number_input("Mesai Saati", min_value=0.0, step=0.5, value=0.0)
                    st.info(f"💡 Normal: {toplam_saat - mesai_saati:.1f} saat, Mesai: {mesai_saati:.1f} saat")
            
            puantaj_aciklama = st.text_area("Açıklama", placeholder="Örn: İlave mesai, erken çıkış, tatil, vb.")
            
            if st.button("💾 Puantaj Kaydet", type="primary"):
                if tatil_gun or toplam_saat > 0:
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute("""INSERT INTO puantaj (isci_id, tarih, giris_saati, cikis_saati, toplam_saat, mesai_saati, tatil, aciklama) 
                              VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            (int(isci_id), str(puantaj_tarih),
                             str(giris_saati) if giris_saati else None,
                             str(cikis_saati) if cikis_saati else None,
                             float(toplam_saat), float(mesai_saati), 1 if tatil_gun else 0, puantaj_aciklama))
                    conn.commit()
                    conn.close()
                    st.success("✅ Puantaj kaydedildi!")
                    _rerun()
                else:
                    st.error("❌ Çalışma saati 0'dan büyük olmalıdır!")
            
            # Son kayıtlar
            st.markdown("---")
            st.subheader("📋 Son Puantaj Kayıtları")
            
            conn = get_db_connection()
            df_son_puantaj = _read_sql("""
                SELECT p.id, p.tarih, i.ad_soyad, p.tatil, p.giris_saati, p.cikis_saati, p.toplam_saat, p.mesai_saati, p.aciklama
                FROM puantaj p
                JOIN isciler i ON p.isci_id = i.id
                ORDER BY p.tarih DESC, i.ad_soyad
                LIMIT 50
            """, conn)
            conn.close()
            
            if not df_son_puantaj.empty:
                st.caption("💡 Hücreye çift tıklayarak düzenleyin, ardından '💾 Kaydet' butonuna basın.")
                _pnt_orig = df_son_puantaj.copy()
                _pnt_orig['tatil'] = _pnt_orig['tatil'].apply(lambda x: bool(x))
                _pnt_edited = st.data_editor(
                    _pnt_orig,
                    column_config={
                        "id": None,
                        "tarih": st.column_config.DateColumn("Tarih"),
                        "ad_soyad": st.column_config.TextColumn("İşçi", disabled=True),
                        "tatil": st.column_config.CheckboxColumn("Tatil?"),
                        "giris_saati": st.column_config.TextColumn("Giriş"),
                        "cikis_saati": st.column_config.TextColumn("Çıkış"),
                        "toplam_saat": st.column_config.NumberColumn("Toplam Saat", min_value=0, step=0.5, format="%.1f"),
                        "mesai_saati": st.column_config.NumberColumn("Mesai", min_value=0, step=0.5, format="%.1f"),
                        "aciklama": st.column_config.TextColumn("Açıklama"),
                    },
                    hide_index=True,
                    use_container_width=True,
                    key="puantaj_editor"
                )
                if st.button("💾 Değişiklikleri Kaydet", type="primary", key="btn_pnt_editor_save"):
                    conn = get_db_connection()
                    c = conn.cursor()
                    for _, _r in _pnt_edited.iterrows():
                        if pd.notna(_r.get('id')):
                            c.execute("UPDATE puantaj SET tarih=?, tatil=?, giris_saati=?, cikis_saati=?, toplam_saat=?, mesai_saati=?, aciklama=? WHERE id=?",
                                      (str(_r['tarih']), 1 if _r['tatil'] else 0,
                                       str(_r['giris_saati'] or ''), str(_r['cikis_saati'] or ''),
                                       float(_r['toplam_saat'] or 0), float(_r['mesai_saati'] or 0),
                                       str(_r['aciklama'] or ''), int(_r['id'])))
                    conn.commit()
                    conn.close()
                    st.success("✅ Değişiklikler kaydedildi!")
                    _rerun()
        else:
            st.warning("⚠️ Önce işçi eklemelisiniz!")
    
    with tab4:
        st.subheader("📊 Puantaj Raporları")
        
        # Tarih aralığı
        col1, col2, col3 = st.columns(3)
        with col1:
            rapor_baslangic = st.date_input("Başlangıç Tarihi", value=date.today().replace(day=1), key="puantaj_baslangic")
        with col2:
            rapor_bitis = st.date_input("Bitiş Tarihi", value=date.today(), key="puantaj_bitis")
        with col3:
            conn = get_db_connection()
            df_isciler_rapor = _read_sql("SELECT DISTINCT ad_soyad FROM isciler ORDER BY ad_soyad", conn)
            conn.close()
            filtre_isci = st.selectbox("İşçi Filtresi", ["Tümü"] + df_isciler_rapor['ad_soyad'].tolist())
        
        # Verileri çek
        conn = get_db_connection()
        if filtre_isci == "Tümü":
            df_puantaj_rapor = _read_sql(f"""
                SELECT i.ad_soyad, i.pozisyon, i.gunluk_ucret, i.saat_ucreti,
                       COUNT(DISTINCT CASE WHEN COALESCE(p.tatil,0)=0 THEN p.tarih END) as gun_sayisi,
                       COALESCE(SUM(CASE WHEN COALESCE(p.tatil,0)=0 THEN p.toplam_saat ELSE 0 END), 0) as toplam_calisma_saati,
                       COALESCE(SUM(CASE WHEN COALESCE(p.tatil,0)=0 THEN p.mesai_saati ELSE 0 END), 0) as toplam_mesai_saati,
                       COUNT(DISTINCT CASE WHEN p.tatil=1 THEN p.tarih END) as tatil_gun_sayisi
                FROM isciler i
                LEFT JOIN puantaj p ON i.id = p.isci_id AND p.tarih BETWEEN '{rapor_baslangic}' AND '{rapor_bitis}'
                WHERE i.aktif = 1
                GROUP BY i.id, i.ad_soyad
            """, conn)
        else:
            df_puantaj_rapor = _read_sql(f"""
                SELECT i.ad_soyad, i.pozisyon, i.gunluk_ucret, i.saat_ucreti,
                       COUNT(DISTINCT CASE WHEN COALESCE(p.tatil,0)=0 THEN p.tarih END) as gun_sayisi,
                       COALESCE(SUM(CASE WHEN COALESCE(p.tatil,0)=0 THEN p.toplam_saat ELSE 0 END), 0) as toplam_calisma_saati,
                       COALESCE(SUM(CASE WHEN COALESCE(p.tatil,0)=0 THEN p.mesai_saati ELSE 0 END), 0) as toplam_mesai_saati,
                       COUNT(DISTINCT CASE WHEN p.tatil=1 THEN p.tarih END) as tatil_gun_sayisi
                FROM isciler i
                LEFT JOIN puantaj p ON i.id = p.isci_id AND p.tarih BETWEEN '{rapor_baslangic}' AND '{rapor_bitis}'
                WHERE i.aktif = 1 AND i.ad_soyad = '{filtre_isci}'
                GROUP BY i.id, i.ad_soyad
            """, conn)
        conn.close()
        
        if not df_puantaj_rapor.empty:
            # Ücret hesaplama
            df_puantaj_rapor['toplam_calisma_saati'] = df_puantaj_rapor['toplam_calisma_saati'].fillna(0)
            df_puantaj_rapor['toplam_mesai_saati'] = df_puantaj_rapor['toplam_mesai_saati'].fillna(0)
            df_puantaj_rapor['gun_sayisi'] = df_puantaj_rapor['gun_sayisi'].fillna(0)
            df_puantaj_rapor['tatil_gun_sayisi'] = df_puantaj_rapor['tatil_gun_sayisi'].fillna(0)
            
            # Günlük ücret varsa o, yoksa saat ücretinden hesapla
            df_puantaj_rapor['tahmini_ucret'] = df_puantaj_rapor.apply(
                lambda row: (row['gun_sayisi'] * row['gunluk_ucret']) if row['gunluk_ucret'] > 0 
                else (row['toplam_calisma_saati'] * row['saat_ucreti']), axis=1
            )
            
            df_puantaj_rapor['mesai_ucreti'] = df_puantaj_rapor['toplam_mesai_saati'] * df_puantaj_rapor['saat_ucreti'] * 1.5
            df_puantaj_rapor['toplam_ucret'] = df_puantaj_rapor['tahmini_ucret'] + df_puantaj_rapor['mesai_ucreti']
            
            # Rapor tablosu
            st.dataframe(
                df_puantaj_rapor[['ad_soyad', 'pozisyon', 'gun_sayisi', 'tatil_gun_sayisi', 'toplam_calisma_saati', 
                                 'toplam_mesai_saati', 'tahmini_ucret', 'mesai_ucreti', 'toplam_ucret']].rename(columns={
                    'ad_soyad': 'İşçi',
                    'pozisyon': 'Pozisyon',
                    'gun_sayisi': 'Çalışma Günü',
                    'tatil_gun_sayisi': 'Tatil/İzin Günü',
                    'toplam_calisma_saati': 'Toplam Saat',
                    'toplam_mesai_saati': 'Mesai Saati',
                    'tahmini_ucret': 'Normal Ücret (TL)',
                    'mesai_ucreti': 'Mesai Ücreti (TL)',
                    'toplam_ucret': 'Toplam Ücret (TL)'
                }),
                use_container_width=True
            )
            
            # Özet istatistikler
            st.markdown("---")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Toplam İşçi", len(df_puantaj_rapor))
            with col2:
                st.metric("Toplam Çalışma Saati", f"{df_puantaj_rapor['toplam_calisma_saati'].sum():.1f}")
            with col3:
                st.metric("Toplam Mesai Saati", f"{df_puantaj_rapor['toplam_mesai_saati'].sum():.1f}")
            with col4:
                st.metric("Toplam İşçilik Maliyeti", f"{df_puantaj_rapor['toplam_ucret'].sum():,.2f} TL")
            
            # Grafikler
            st.markdown("---")
            
            # İşçi bazında çalışma saati
            fig_isci_saat = px.bar(df_puantaj_rapor, x='ad_soyad', y='toplam_calisma_saati',
                                  title='İşçi Bazında Toplam Çalışma Saati',
                                  labels={'ad_soyad': 'İşçi', 'toplam_calisma_saati': 'Saat'})
            st.plotly_chart(fig_isci_saat, use_container_width=True)
            
            # İşçi bazında ücret dağılımı
            fig_isci_ucret = px.bar(df_puantaj_rapor, x='ad_soyad', y='toplam_ucret',
                                   title='İşçi Bazında Ücret Dağılımı',
                                   labels={'ad_soyad': 'İşçi', 'toplam_ucret': 'Toplam Ücret (TL)'})
            st.plotly_chart(fig_isci_ucret, use_container_width=True)
            
            # Detaylı günlük puantaj
            if filtre_isci != "Tümü":
                st.markdown("---")
                st.subheader(f"📅 {filtre_isci} - Günlük Detay")
                
                conn = get_db_connection()
                df_detay = _read_sql(f"""
                    SELECT p.tarih, p.tatil, p.giris_saati, p.cikis_saati, p.toplam_saat, p.mesai_saati, p.aciklama
                    FROM puantaj p
                    JOIN isciler i ON p.isci_id = i.id
                    WHERE i.ad_soyad = '{filtre_isci}' 
                    AND p.tarih BETWEEN '{rapor_baslangic}' AND '{rapor_bitis}'
                    ORDER BY p.tarih DESC
                """, conn)
                conn.close()
                
                if not df_detay.empty:
                    df_detay['tatil'] = df_detay['tatil'].apply(lambda x: '🏖️ Tatil' if x == 1 else '✅ Çalışma')
                    st.dataframe(
                        df_detay.rename(columns={
                            'tarih': 'Tarih',
                            'tatil': 'Durum',
                            'giris_saati': 'Giriş',
                            'cikis_saati': 'Çıkış',
                            'toplam_saat': 'Toplam Saat',
                            'mesai_saati': 'Mesai',
                            'aciklama': 'Açıklama'
                        }),
                        use_container_width=True
                    )
        else:
            st.info("Seçilen kriterlere uygun puantaj kaydı bulunamadı.")

# Gelir-Gider Analizi
elif menu == "💼 Gelir-Gider Analizi":
    st.title("💼 Gelir-Gider Analizi")
    
    # Tarih aralığı ve oda filtresi
    col1, col2, col3 = st.columns(3)
    with col1:
        baslangic = st.date_input("Başlangıç Tarihi", value=date(date.today().year, 1, 1), key="analiz_baslangic")
    with col2:
        bitis = st.date_input("Bitiş Tarihi", value=date.today(), key="analiz_bitis")
    with col3:
        _gg_odalar = _cached_odalar()
        _gg_oda_sec = st.selectbox("Oda Filtresi", ["Tümü"] + _gg_odalar['oda_adi'].tolist(), key="analiz_oda")
    
    _gg_oda_where_gider = ""
    _gg_oda_where_gelir = ""
    if _gg_oda_sec != "Tümü":
        _gg_oda_id = int(_gg_odalar[_gg_odalar['oda_adi'] == _gg_oda_sec]['id'].values[0])
        _gg_oda_where_gider = f"AND oda_id = {_gg_oda_id}"
        _gg_oda_where_gelir = f"AND oda_id = {_gg_oda_id}"
    
    conn = get_db_connection()
    
    # Toplam gelir
    df_gelir = _read_sql(f"""
        SELECT COALESCE(SUM(toplam_tutar), 0) as toplam_gelir,
               COALESCE(SUM(nakliye_ucreti), 0) as toplam_nakliye
        FROM satislar
        WHERE tarih BETWEEN '{baslangic}' AND '{bitis}'
        {_gg_oda_where_gelir}
    """, conn)
    
    # Toplam gider
    df_gider = _read_sql(f"""
        SELECT COALESCE(SUM(tutar), 0) as toplam_gider
        FROM oda_giderleri
        WHERE tarih BETWEEN '{baslangic}' AND '{bitis}'
        {_gg_oda_where_gider}
    """, conn)
    
    # Gider kategorileri
    df_gider_kategorili = _read_sql(f"""
        SELECT gider_kalemi, SUM(tutar) as toplam
        FROM oda_giderleri
        WHERE tarih BETWEEN '{baslangic}' AND '{bitis}'
        {_gg_oda_where_gider}
        GROUP BY gider_kalemi
        ORDER BY toplam DESC
    """, conn)
    
    conn.close()
    
    # Özet kartlar
    toplam_gelir  = float(df_gelir['toplam_gelir'].values[0]  or 0)
    toplam_nakliye = float(df_gelir['toplam_nakliye'].values[0] or 0)
    toplam_gider  = float(df_gider['toplam_gider'].values[0]   or 0)
    net_gelir = toplam_gelir - toplam_nakliye
    net_kar   = net_gelir - toplam_gider
    kar_marji = (net_kar / net_gelir * 100) if net_gelir > 0 else 0
    
    st.markdown("### 📊 Finansal Özet")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Toplam Gelir", f"{toplam_gelir:,.2f} TL", delta=None)
    with col2:
        st.metric("Toplam Gider", f"{toplam_gider:,.2f} TL", delta=None)
    with col3:
        st.metric("Net Kâr", f"{net_kar:,.2f} TL", 
                 delta=f"{kar_marji:.1f}% Kâr Marjı",
                 delta_color="normal" if net_kar >= 0 else "inverse")
    with col4:
        st.metric("Nakliye Gideri", f"{toplam_nakliye:,.2f} TL", delta=None)
    
    st.markdown("---")
    
    # Gelir-Gider Pasta Grafikleri
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 💰 Gelir Dağılımı")
        gelir_data = pd.DataFrame({
            'Kategori': ['Net Gelir', 'Nakliye'],
            'Tutar': [net_gelir, toplam_nakliye]
        })
        fig_gelir = px.pie(gelir_data, values='Tutar', names='Kategori',
                          title='Gelir Bileşenleri')
        st.plotly_chart(fig_gelir, use_container_width=True)
    
    with col2:
        st.markdown("### 💸 Gider Kategorileri")
        if not df_gider_kategorili.empty:
            fig_gider = px.pie(df_gider_kategorili, values='toplam', names='gider_kalemi',
                              title='Gider Dağılımı')
            st.plotly_chart(fig_gider, use_container_width=True)
        else:
            st.info("Gider verisi bulunmuyor.")
    
    # Gider detayları
    if not df_gider_kategorili.empty:
        st.markdown("---")
        st.markdown("### 📋 Gider Detayları")
        
        df_gider_kategorili['oran'] = (df_gider_kategorili['toplam'] / toplam_gider * 100).round(2)
        
        st.dataframe(
            df_gider_kategorili.rename(columns={
                'gider_kalemi': 'Gider Kalemi',
                'toplam': 'Tutar (TL)',
                'oran': 'Oran (%)'
            }),
            use_container_width=True
        )
    
    # Gelir-Gider karşılaştırma grafiği
    st.markdown("---")
    st.markdown("### 📊 Gelir-Gider Karşılaştırması")
    
    karsilastirma_data = pd.DataFrame({
        'Kategori': ['Gelir', 'Gider', 'Net Kâr'],
        'Tutar': [net_gelir, toplam_gider, net_kar]
    })
    
    fig_karsilastirma = px.bar(karsilastirma_data, x='Kategori', y='Tutar',
                               title='Gelir-Gider-Kâr Karşılaştırması',
                               labels={'Tutar': 'Tutar (TL)'},
                               color='Kategori',
                               color_discrete_map={'Gelir': 'green', 'Gider': 'red', 'Net Kâr': 'blue'})
    st.plotly_chart(fig_karsilastirma, use_container_width=True)

# Oda Bilgi Kartı
elif menu == "📋 Oda Bilgi Kartı":
    st.title("📋 Oda Bilgi Kartı")
    st.markdown("Seçili odaya ait tüm veriler: temel bilgiler, üretim takvimi, giderler, hasat, satış ve iklim.")

    df_odalar_kart = _cached_odalar()

    if df_odalar_kart.empty:
        st.warning("⚠️ Henüz oda eklenmemiş. Oda Yönetimi menüsünden ekleyin.")
    else:
        secili_kart_oda = st.selectbox("🏢 Oda Seçin", df_odalar_kart['oda_adi'].tolist(), key="kart_oda_sec")
        kart_oda_id = int(df_odalar_kart[df_odalar_kart['oda_adi'] == secili_kart_oda]['id'].values[0])

        conn = get_db_connection()
        df_kart_temel  = _read_sql(f"SELECT * FROM odalar WHERE id={kart_oda_id}", conn)
        df_kart_uretim = _read_sql(f"""
            SELECT donem_no, ekim_tarihi, baski_tarihi, toprak_serim_tarihi,
                   tirmik_tarihi, hava_verme_tarihi, flash1_tarihi,
                   flash2_tarihi, oda_bosaltma_tarihi, aciklama
            FROM oda_uretim_takip WHERE oda_id={kart_oda_id} ORDER BY donem_no
        """, conn)
        df_kart_gider  = _read_sql(f"""
            SELECT tarih, gider_kalemi, tutar, aciklama
            FROM oda_giderleri WHERE oda_id={kart_oda_id} ORDER BY tarih DESC
        """, conn)
        df_kart_hasat  = _read_sql(f"""
            SELECT tarih, hasat_kg, kalite, aciklama
            FROM gunluk_hasat WHERE oda_id={kart_oda_id} ORDER BY tarih DESC
        """, conn)
        df_kart_satis  = _read_sql(f"""
            SELECT tarih, alan_kisi, satis_kg, birim_fiyat, toplam_tutar, fire_kg, aciklama
            FROM satislar WHERE oda_id={kart_oda_id} ORDER BY tarih DESC
        """, conn)
        df_kart_iklim  = _read_sql(f"""
            SELECT tarih, saat, sicaklik, nem, co2, aciklama
            FROM iklim_verileri WHERE oda_id={kart_oda_id}
            ORDER BY tarih DESC, saat DESC LIMIT 50
        """, conn)
        conn.close()

        st.markdown("---")

        # ── 1. Temel Bilgiler ─────────────────────────────────────────────────
        st.markdown("### 🏢 Temel Bilgiler")
        if not df_kart_temel.empty:
            _kr = df_kart_temel.iloc[0]
            _kc1, _kc2, _kc3, _kc4 = st.columns(4)
            with _kc1:
                st.metric("Alan", f"{float(_kr['alan_m2'] or 0):.1f} m²")
            with _kc2:
                st.metric("Kapasite", f"{float(_kr['kapasite_kg'] or 0):.0f} kg")
            with _kc3:
                _kdurum = str(_kr['durum'] or 'Bilinmiyor')
                if _kdurum == 'Aktif':
                    st.success(f"🟢 {_kdurum}")
                elif _kdurum == 'Pasif':
                    st.error(f"🔴 {_kdurum}")
                else:
                    st.warning(f"🟡 {_kdurum}")
            with _kc4:
                _kacik = str(_kr['aciklama'] or '')
                if _kacik and _kacik not in ('None', 'nan'):
                    st.caption(f"📝 {_kacik}")

        # ── 2. Üretim Takvimi ──────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("### 🌱 Üretim Takvimi")
        if not df_kart_uretim.empty:
            st.dataframe(
                df_kart_uretim.rename(columns={
                    'donem_no': 'Dönem',
                    'ekim_tarihi': '🌱 Ekim',
                    'baski_tarihi': '⚙️ Baskı',
                    'toprak_serim_tarihi': '🌍 Toprak Serim',
                    'tirmik_tarihi': '🔧 Tırmık',
                    'hava_verme_tarihi': '💨 Hava Verme',
                    'flash1_tarihi': '🍄 1. Flaş',
                    'flash2_tarihi': '🍄 2. Flaş',
                    'oda_bosaltma_tarihi': '🚪 Oda Boşaltma',
                    'aciklama': 'Not',
                }),
                use_container_width=True,
                hide_index=True,
            )

            st.markdown("---")
            st.markdown("### 📅 Planlanan İşler")
            conn = get_db_connection()
            df_kart_plani = _read_sql(
                """
                SELECT t.*, ut.flash1_tarihi, ut.flash2_tarihi, ut.oda_bosaltma_tarihi
                FROM is_plani t
                LEFT JOIN oda_uretim_takip ut ON ut.oda_id = t.oda_id AND ut.donem_no = COALESCE(t.donem_no, 1)
                WHERE t.oda_id = ?
                ORDER BY t.durum, t.plan_tarihi ASC
                """,
                conn,
                params=(kart_oda_id,)
            )
            conn.close()

            def _parse_date(val):
                if val and str(val) not in ('None', 'nan', ''):
                    try:
                        return date.fromisoformat(str(val)[:10])
                    except Exception:
                        pass
                return None

            def _asama_label(key):
                return {
                    'ekim_tarihi': '🌱 Ekim',
                    'baski_tarihi': '⚙️ Baskı',
                    'toprak_serim_tarihi': '🌍 Toprak Serim',
                    'tirmik_tarihi': '🔧 Tırmık',
                    'hava_verme_tarihi': '💨 Hava Verme',
                    'flash1_tarihi': '🍄 1. Flaş',
                    'flash2_tarihi': '🍄 2. Flaş',
                    'oda_bosaltma_tarihi': '🚪 Oda Boşaltma',
                }.get(key, 'Özel Tarih')

            if df_kart_plani.empty:
                st.info("Bu oda için planlanmış iş yok.")
            else:
                kart_plan_rows = []
                bugun = date.today()
                for _, row in df_kart_plani.iterrows():
                    ref_date = _parse_date(row.get(row['referans_asama'])) if row['referans_asama'] else None
                    plan_date = _parse_date(row.get('plan_tarihi'))
                    if row['referans_asama'] and ref_date is not None:
                        try:
                            plan_date = ref_date - timedelta(days=int(row.get('hatirlatma_gun_once') or 0))
                        except Exception:
                            pass
                    if plan_date:
                        kalan = (plan_date - bugun).days
                        if row['durum'] != 'Tamamlandı':
                            if kalan < 0:
                                durum = f"🔴 {abs(kalan)} gün gecikti"
                            elif kalan == 0:
                                durum = "🟡 Bugün"
                            else:
                                durum = f"🟢 {kalan} gün kaldı"
                        else:
                            durum = "✅ Tamamlandı"
                    else:
                        durum = "⚠️ Tarih yok"
                    kart_plan_rows.append({
                        'İş': row['is_adi'],
                        'Dönem': row['donem_no'] if row['donem_no'] else 'Genel',
                        'Referans': _asama_label(row['referans_asama']),
                        'Hatırlatma': plan_date.strftime('%d.%m.%Y') if plan_date else '',
                        'Durum': durum,
                        'Açıklama': row['aciklama'] or '',
                    })
                st.dataframe(pd.DataFrame(kart_plan_rows), use_container_width=True)
        else:
            st.info("Bu oda için üretim takvimi kaydı yok.")

        # ── 3. Giderler ────────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("### 💰 Giderler")
        if not df_kart_gider.empty:
            _gkc1, _gkc2 = st.columns([1, 2])
            with _gkc1:
                st.metric("Toplam Gider", f"{df_kart_gider['tutar'].sum():,.2f} TL")
                st.metric("Kayıt Sayısı", len(df_kart_gider))
            with _gkc2:
                _gozet = (df_kart_gider.groupby('gider_kalemi')['tutar']
                          .sum().reset_index()
                          .sort_values('tutar', ascending=False)
                          .rename(columns={'gider_kalemi': 'Gider Kalemi', 'tutar': 'Toplam (TL)'}))
                st.dataframe(_gozet, use_container_width=True, hide_index=True)
            st.markdown("**📋 Tüm Gider Kayıtları:**")
            st.dataframe(
                df_kart_gider.rename(columns={
                    'tarih': 'Tarih', 'gider_kalemi': 'Gider Kalemi',
                    'tutar': 'Tutar (TL)', 'aciklama': 'Açıklama',
                }),
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("Bu oda için gider kaydı yok.")

        # ── 4. Hasat ───────────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("### 📊 Hasat")
        if not df_kart_hasat.empty:
            _hkc1, _hkc2, _hkc3 = st.columns(3)
            with _hkc1:
                st.metric("Toplam Hasat", f"{df_kart_hasat['hasat_kg'].sum():.2f} kg")
            with _hkc2:
                st.metric("Ortalama / Kayıt", f"{df_kart_hasat['hasat_kg'].mean():.2f} kg")
            with _hkc3:
                st.metric("Kayıt Sayısı", len(df_kart_hasat))
            st.dataframe(
                df_kart_hasat.rename(columns={
                    'tarih': 'Tarih', 'hasat_kg': 'Hasat (kg)',
                    'kalite': 'Kalite', 'aciklama': 'Açıklama',
                }),
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("Bu oda için hasat kaydı yok.")

        # ── 5. Satışlar ────────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("### 💵 Satışlar")
        if not df_kart_satis.empty:
            _skc1, _skc2, _skc3 = st.columns(3)
            with _skc1:
                st.metric("Toplam Satış", f"{df_kart_satis['satis_kg'].sum():.2f} kg")
            with _skc2:
                st.metric("Toplam Gelir", f"{df_kart_satis['toplam_tutar'].sum():,.2f} TL")
            with _skc3:
                st.metric("Toplam Fire", f"{df_kart_satis['fire_kg'].sum():.2f} kg")
            st.dataframe(
                df_kart_satis.rename(columns={
                    'tarih': 'Tarih', 'alan_kisi': 'Müşteri',
                    'satis_kg': 'Satış (kg)', 'birim_fiyat': 'Fiyat (TL/kg)',
                    'toplam_tutar': 'Toplam (TL)', 'fire_kg': 'Fire (kg)',
                    'aciklama': 'Açıklama',
                }),
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("Bu oda için satış kaydı yok.")

        # ── 6. İklim ───────────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("### 🌡️ İklim Verileri (Son 50 Kayıt)")
        if not df_kart_iklim.empty:
            _ikc1, _ikc2, _ikc3 = st.columns(3)
            with _ikc1:
                st.metric("Ort. Sıcaklık", f"{df_kart_iklim['sicaklik'].mean():.1f} °C")
            with _ikc2:
                st.metric("Ort. Nem", f"{df_kart_iklim['nem'].mean():.1f} %")
            with _ikc3:
                st.metric("Ort. CO₂", f"{df_kart_iklim['co2'].mean():.0f} ppm")
            st.dataframe(
                df_kart_iklim.rename(columns={
                    'tarih': 'Tarih', 'saat': 'Saat',
                    'sicaklik': 'Sıcaklık (°C)', 'nem': 'Nem (%)',
                    'co2': 'CO₂ (ppm)', 'aciklama': 'Açıklama',
                }),
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("Bu oda için iklim verisi yok.")

# Üretim Takvimi
elif menu == "🌱 Üretim Takvimi":
    st.title("🌱 Oda Üretim Takvimi")

    # ── Yardımcı ─────────────────────────────────────────────────────────────
    def _parse_ut_date(val):
        if val and str(val) not in ('None', 'nan', ''):
            try:
                return date.fromisoformat(str(val)[:10])
            except Exception:
                pass
        return None

    EVRELER = [
        # (db_alan,               emoji_lbl,            sonraki_gun, sonraki_lbl)
        ("ekim_tarihi",        "🌱 Ekim",              10, "⚙️ Baskı"),
        ("baski_tarihi",       "⚙️ Baskı",              1, "🌍 Toprak Serim"),
        ("toprak_serim_tarihi","🌍 Toprak Serim",        9, "🔧 Tırmık"),
        ("tirmik_tarihi",      "🔧 Tırmık",             3, "💨 Hava Verme"),
        ("hava_verme_tarihi",  "💨 Hava Verme",         11, "🍄 1. Flaş"),
        ("flash1_tarihi",      "🍄 1. Flaş",            14, "🍄 2. Flaş"),
        ("flash2_tarihi",      "🍄 2. Flaş",             5, "🚪 Oda Boşaltma"),
        ("oda_bosaltma_tarihi","🚪 Oda Boşaltma",      None, None),
    ]

    tab1, tab2, tab3 = st.tabs(["📅 Tarih Girişi", "📋 Oda Takip Paneli", "📊 Gantt Takvim"])

    # ── TAB 1: Tarih Girişi ──────────────────────────────────────────────────
    with tab1:
        df_odalar_ut = _cached_odalar()

        if df_odalar_ut.empty:
            st.warning("⚠️ Önce oda eklemelisiniz! (Oda Yönetimi menüsünden)")
        else:
            st.subheader("📅 Üretim Tarihleri Girişi")
            col1, col2 = st.columns(2)
            with col1:
                ut_oda = st.selectbox("Oda Seçin", df_odalar_ut['oda_adi'].tolist(), key="ut_oda_sel")
                ut_oda_id = int(df_odalar_ut[df_odalar_ut['oda_adi'] == ut_oda]['id'].values[0])

            conn = get_db_connection()
            df_donemler_ut = _read_sql(
                f"SELECT * FROM oda_uretim_takip WHERE oda_id={ut_oda_id} ORDER BY donem_no DESC", conn
            )
            conn.close()

            with col2:
                donem_opts = ["➕ Yeni Dönem"]
                if not df_donemler_ut.empty:
                    donem_opts += [f"Dönem {int(r['donem_no'])}" for _, r in df_donemler_ut.iterrows()]
                ut_donem_sel = st.selectbox("Dönem", donem_opts, key="ut_donem_sel")

            if ut_donem_sel == "➕ Yeni Dönem":
                mevcut_kay = None
                yeni_donem_no = int(df_donemler_ut['donem_no'].max()) + 1 if not df_donemler_ut.empty else 1
            else:
                yeni_donem_no = int(ut_donem_sel.split(" ")[1])
                _filtre = df_donemler_ut[df_donemler_ut['donem_no'] == yeni_donem_no]
                mevcut_kay = _filtre.iloc[0] if not _filtre.empty else None

            st.markdown("---")
            st.markdown("**Yapılan işlemleri işaretleyin ve tarihini girin:**")

            # (alan, chk_lbl, dt_lbl, gün_önceki_aşamadan, gün_sonraki_aşamaya, sonraki_lbl)
            EVRE_HINTS = [
                ("ekim_tarihi",         "🌱 Ekim Yapıldı",         "Ekim Tarihi",        None, 10, "⚙️ Baskı"),
                ("baski_tarihi",        "⚙️ Baskı Yapıldı",         "Baskı Tarihi",        10,   1, "🌍 Toprak Serim"),
                ("toprak_serim_tarihi", "🌍 Toprak Serim Yapıldı",  "Toprak Serim Tarihi",  1,   9, "🔧 Tırmık"),
                ("tirmik_tarihi",       "🔧 Tırmık Yapıldı",        "Tırmık Tarihi",        9,   3, "💨 Hava Verme"),
                ("hava_verme_tarihi",   "💨 Hava Verme Yapıldı",    "Hava Verme Tarihi",    3,  11, "🍄 1. Flaş"),
                ("flash1_tarihi",       "🍄 1. Flaş Başladı",       "1. Flaş Tarihi",      11,  14, "🍄 2. Flaş"),
                ("flash2_tarihi",       "🍄 2. Flaş Başladı",       "2. Flaş Tarihi",      14,   5, "🚪 Oda Boşaltma"),
                ("oda_bosaltma_tarihi", "🚪 Oda Boşaltma Yapıldı",  "Oda Boşaltma Tarihi",  5, None, None),
            ]

            # ── Önce tüm tahmini tarihleri zincir hesapla ───────────────────
            # Mevcut kayıt varsa oradan, yoksa henüz girilmemiş
            _bugun = date.today()
            _TH_STAGES = [
                ("ekim_tarihi",         "🌱 Ekim",          None),
                ("baski_tarihi",        "⚙️ Baskı",           10),
                ("toprak_serim_tarihi", "🌍 Toprak Serim",     1),
                ("tirmik_tarihi",       "🔧 Tırmık",           9),
                ("hava_verme_tarihi",   "💨 Hava Verme",       3),
                ("flash1_tarihi",       "🍄 1. Flaş",         11),
                ("flash2_tarihi",       "🍄 2. Flaş",         14),
                ("oda_bosaltma_tarihi", "🚪 Oda Boşaltma",     5),
            ]

            def _hesapla_tahminler(vals):
                """vals: {alan: date|None} -> {alan: (date, is_gercek)}"""
                result = {}
                prev = None
                for _a, _lbl, _gun in _TH_STAGES:
                    gercek = vals.get(_a)
                    if gercek:
                        result[_a] = (gercek, True)
                        prev = gercek
                    elif prev is not None and _gun is not None:
                        th = prev + timedelta(days=_gun)
                        result[_a] = (th, False)
                        prev = th
                    else:
                        result[_a] = (None, False)
                return result

            def _tahmini_caption(th, is_gercek):
                if th is None:
                    return
                if is_gercek:
                    st.caption(f"✅ Gerçekleşti: **{th.strftime('%d.%m.%Y')}**")
                else:
                    kalan = (th - _bugun).days
                    if kalan < 0:
                        st.caption(f"📅 Tahmini: **{th.strftime('%d.%m.%Y')}** 🔴 {abs(kalan)} gün geçti")
                    elif kalan == 0:
                        st.caption(f"📅 Tahmini: **{th.strftime('%d.%m.%Y')}** 🟡 Bugün!")
                    elif kalan <= 3:
                        st.caption(f"📅 Tahmini: **{th.strftime('%d.%m.%Y')}** 🟡 {kalan} gün kaldı")
                    else:
                        st.caption(f"📅 Tahmini: **{th.strftime('%d.%m.%Y')}** 🟢 {kalan} gün kaldı")

            # Mevcut kaydın tarihlerini başlangıç değeri olarak hesapla
            _mevcut_vals = {a: (_parse_ut_date(mevcut_kay[a]) if mevcut_kay is not None else None)
                            for a, *_ in _TH_STAGES}

            tarih_vals = {}
            for alan, chk_lbl, dt_lbl, gun_once, gun_sonra, sonraki_lbl in EVRE_HINTS:
                mev_t = _parse_ut_date(mevcut_kay[alan]) if mevcut_kay is not None else None
                yapildi = st.checkbox(chk_lbl, value=mev_t is not None, key=f"utck_{alan}")
                if yapildi:
                    tarih_vals[alan] = st.date_input(dt_lbl, value=mev_t or _bugun, key=f"utdt_{alan}")
                else:
                    tarih_vals[alan] = None
                # Her aşamanın altına tahmini tarihi inline göster
                _anlık_vals = {**_mevcut_vals, **tarih_vals}
                _anlık_tahminler = _hesapla_tahminler(_anlık_vals)
                _th_bu, _ig_bu = _anlık_tahminler.get(alan, (None, False))
                _tahmini_caption(_th_bu, _ig_bu)
                st.markdown("")

            _tum_vals = {**_mevcut_vals, **tarih_vals}
            _tum_tahminler = _hesapla_tahminler(_tum_vals)

            if _tum_tahminler.get("ekim_tarihi", (None, False))[0] is not None:
                st.markdown("---")
                st.markdown("#### 📅 Tüm Aşamaların Tahmini Tarihleri")

                _row1 = st.columns(4)
                _row2 = st.columns(4)
                _grid_cols = _row1 + _row2

                for _idx, (_alan, _lbl, _gun) in enumerate(_TH_STAGES):
                    _th, _is_gercek = _tum_tahminler[_alan]
                    with _grid_cols[_idx]:
                        st.markdown(f"**{_lbl}**")
                        if _th is None:
                            st.markdown("—")
                            continue

                        st.markdown(f"📅 `{_th.strftime('%d.%m.%Y')}`")
                        if _is_gercek:
                            st.success("✅ Yapıldı")
                        else:
                            _kalan = (_th - _bugun).days
                            if _kalan < 0:
                                st.error(f"🔴 {abs(_kalan)} gün geçti")
                            elif _kalan == 0:
                                st.warning("🟡 Bugün!")
                            elif _kalan <= 3:
                                st.warning(f"🟡 {_kalan} gün kaldı")
                            else:
                                st.info(f"🟢 {_kalan} gün kaldı")

            aciklama_ut = st.text_area(
                "Açıklama",
                value=str(mevcut_kay['aciklama']) if mevcut_kay is not None and mevcut_kay['aciklama'] else "",
                key="ut_aciklama"
            )

            if st.button("💾 Kaydet", type="primary", key="btn_ut_save"):
                p = tuple(
                    str(tarih_vals[a]) if tarih_vals[a] else None
                    for a in ["ekim_tarihi", "baski_tarihi", "toprak_serim_tarihi",
                               "tirmik_tarihi", "hava_verme_tarihi", "flash1_tarihi",
                               "flash2_tarihi", "oda_bosaltma_tarihi"]
                ) + (aciklama_ut,)
                conn = get_db_connection()
                c = conn.cursor()
                if ut_donem_sel == "➕ Yeni Dönem":
                    c.execute(
                        """INSERT INTO oda_uretim_takip
                           (oda_id, donem_no, ekim_tarihi, baski_tarihi, toprak_serim_tarihi,
                            tirmik_tarihi, hava_verme_tarihi, flash1_tarihi,
                            flash2_tarihi, oda_bosaltma_tarihi, aciklama)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (ut_oda_id, yeni_donem_no) + p
                    )
                else:
                    c.execute(
                        """UPDATE oda_uretim_takip SET
                           ekim_tarihi=?, baski_tarihi=?, toprak_serim_tarihi=?,
                           tirmik_tarihi=?, hava_verme_tarihi=?, flash1_tarihi=?,
                           flash2_tarihi=?, oda_bosaltma_tarihi=?, aciklama=?
                           WHERE oda_id=? AND donem_no=?""",
                        p + (ut_oda_id, yeni_donem_no)
                    )
                conn.commit()
                conn.close()
                st.success("✅ Kaydedildi!")
                _rerun()

    # ── TAB 2: Oda Takip Paneli ───────────────────────────────────────────────
    with tab2:
        conn = get_db_connection()
        df_tum_takip = _read_sql("""
            SELECT o.oda_adi, ut.*
            FROM oda_uretim_takip ut
            JOIN odalar o ON ut.oda_id = o.id
            ORDER BY o.oda_adi, ut.donem_no DESC
        """, conn)
        conn.close()

        if df_tum_takip.empty:
            st.info("ℹ️ Henüz kayıt yok. 'Tarih Girişi' sekmesinden ekleyin.")
        else:
            bugun = date.today()

            for _, row in df_tum_takip.iterrows():
                oda_adi_r = row['oda_adi']
                donem_r   = int(row['donem_no'])

                ekim_d      = _parse_ut_date(row['ekim_tarihi'])
                baski_d     = _parse_ut_date(row['baski_tarihi'])
                toprak_d    = _parse_ut_date(row['toprak_serim_tarihi'])
                tirmik_d    = _parse_ut_date(row['tirmik_tarihi'])
                hava_d      = _parse_ut_date(row['hava_verme_tarihi'])
                flash1_d    = _parse_ut_date(row['flash1_tarihi'])
                flash2_d    = _parse_ut_date(row.get('flash2_tarihi'))
                bosaltma_d  = _parse_ut_date(row.get('oda_bosaltma_tarihi'))

                # Sonraki tahmini işlem
                if bosaltma_d:
                    sonraki_adi = "✅ Tamamlandı"
                    sonraki_tahmini = None
                elif flash2_d:
                    sonraki_adi = "🚪 Oda Boşaltma"
                    sonraki_tahmini = flash2_d + timedelta(days=5)
                elif flash1_d:
                    sonraki_adi = "🍄 2. Flaş"
                    sonraki_tahmini = flash1_d + timedelta(days=14)
                elif hava_d:
                    sonraki_adi = "🍄 1. Flaş"
                    sonraki_tahmini = hava_d + timedelta(days=11)
                elif tirmik_d:
                    sonraki_adi = "💨 Hava Verme"
                    sonraki_tahmini = tirmik_d + timedelta(days=3)
                elif toprak_d:
                    sonraki_adi = "🔧 Tırmık"
                    sonraki_tahmini = toprak_d + timedelta(days=9)
                elif baski_d:
                    sonraki_adi = "🌍 Toprak Serim"
                    sonraki_tahmini = baski_d + timedelta(days=1)
                elif ekim_d:
                    sonraki_adi = "⚙️ Baskı"
                    sonraki_tahmini = ekim_d + timedelta(days=10)
                else:
                    sonraki_adi = "📋 Veri yok"
                    sonraki_tahmini = None

                if sonraki_tahmini:
                    fark = (sonraki_tahmini - bugun).days
                    if fark < 0:
                        durum_ikon = "🔴"
                        durum_txt  = f"{abs(fark)} gün GECİKMİŞ"
                    elif fark <= 2:
                        durum_ikon = "🟡"
                        durum_txt  = f"BUGÜN / {fark} gün kaldı"
                    else:
                        durum_ikon = "🟢"
                        durum_txt  = f"{fark} gün kaldı"
                    baslik = f"{durum_ikon} **{oda_adi_r}** — Dönem {donem_r} | Sonraki: {sonraki_adi} ({durum_txt})"
                else:
                    baslik = f"✅ **{oda_adi_r}** — Dönem {donem_r} | {sonraki_adi}"

                _ut_row_id = int(row['id'])
                _edit_key  = f"ut_edit_{_ut_row_id}"

                with st.expander(baslik, expanded=True):
                    evre_verileri = [
                        ("🌱 Ekim",         ekim_d,     None,       10, "⚙️ Baskı"),
                        ("⚙️ Baskı",         baski_d,    ekim_d,      1, "🌍 Toprak Serim"),
                        ("🌍 Toprak Serim",  toprak_d,   baski_d,     9, "🔧 Tırmık"),
                        ("🔧 Tırmık",        tirmik_d,   toprak_d,    3, "💨 Hava Verme"),
                        ("💨 Hava Verme",    hava_d,     tirmik_d,   11, "🍄 1. Flaş"),
                        ("🍄 1. Flaş",       flash1_d,   hava_d,     14, "🍄 2. Flaş"),
                        ("🍄 2. Flaş",       flash2_d,   flash1_d,    5, "🚪 Oda Boşaltma"),
                        ("🚪 Oda Boşaltma",  bosaltma_d, flash2_d,  None, None),
                    ]

                    cols6 = st.columns(8)
                    dates_list = [ekim_d, baski_d, toprak_d, tirmik_d, hava_d, flash1_d, flash2_d, bosaltma_d]

                    for i, (lbl, evre_dt, onc_dt, sgun, slbl) in enumerate(evre_verileri):
                        with cols6[i]:
                            st.markdown(f"**{lbl}**")
                            if evre_dt:
                                gun = (bugun - evre_dt).days
                                st.markdown(f"📅 `{evre_dt.strftime('%d.%m.%Y')}`")
                                st.markdown(f"⏱️ **+{gun} gün**")
                                # Tahmini sonraki (yalnızca sonraki yapılmamışsa)
                                if sgun is not None and i + 1 < len(dates_list) and not dates_list[i + 1]:
                                    tahmini = evre_dt + timedelta(days=sgun)
                                    kalan   = (tahmini - bugun).days
                                    if kalan < 0:
                                        st.error(f"📅 {tahmini.strftime('%d.%m.%Y')}\n{slbl} gecikti!")
                                    elif kalan <= 2:
                                        st.warning(f"📅 {tahmini.strftime('%d.%m.%Y')}\n{slbl}: {kalan} gün")
                                    else:
                                        st.info(f"📅 {tahmini.strftime('%d.%m.%Y')}\n{slbl}: {kalan} gün")
                            else:
                                st.markdown("— *henüz yok*")
                                if onc_dt and sgun is None:
                                    pass  # son evre, tahmin yok
                                elif onc_dt:
                                    tahmini = onc_dt + timedelta(days=evre_verileri[i - 1][3])
                                    st.caption(f"Tahmini: {tahmini.strftime('%d.%m.%Y')}")

                    # Özet satırı
                    if ekim_d:
                        st.markdown("---")
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            st.metric("Ekimden Bu Yana", f"{(bugun - ekim_d).days} gün")
                        with c2:
                            if toprak_d:
                                tahmini_flash = toprak_d + timedelta(days=23)
                            else:
                                tahmini_flash = ekim_d + timedelta(days=10 + 1 + 9 + 3 + 11)
                            if flash1_d:
                                st.metric("1. Flaş Başladı", flash1_d.strftime('%d.%m.%Y'))
                                tahmini_flash2 = flash1_d + timedelta(days=14)
                                if flash2_d:
                                    st.metric("2. Flaş Başladı", flash2_d.strftime('%d.%m.%Y'))
                                else:
                                    kalan_f2 = (tahmini_flash2 - bugun).days
                                    st.metric(
                                        "Tahmini 2. Flaş",
                                        tahmini_flash2.strftime('%d.%m.%Y'),
                                        delta=f"{kalan_f2} gün kaldı" if kalan_f2 >= 0 else f"{abs(kalan_f2)} gün geçti"
                                    )
                            else:
                                kalan_flash = (tahmini_flash - bugun).days
                                st.metric(
                                    "Tahmini 1. Flaş",
                                    tahmini_flash.strftime('%d.%m.%Y'),
                                    delta=f"{kalan_flash} gün kaldı" if kalan_flash >= 0 else f"{abs(kalan_flash)} gün geçti"
                                )
                        with c3:
                            # Şu anki durum
                            if bosaltma_d:
                                st.success("✅ Oda Boşaltıldı")
                            elif flash2_d:
                                tahmini_bosaltma = flash2_d + timedelta(days=5)
                                kalan_bos = (tahmini_bosaltma - bugun).days
                                st.info(f"🍄 2. Flaş — Oda Boşaltma: {tahmini_bosaltma.strftime('%d.%m.%Y')} ({kalan_bos} gün)")
                            elif flash1_d:
                                tahmini_flash2 = flash1_d + timedelta(days=14)
                                kalan_f2 = (tahmini_flash2 - bugun).days
                                st.info(f"🍄 1. Flaş — 2. Flaş: {tahmini_flash2.strftime('%d.%m.%Y')} ({kalan_f2} gün)")
                            elif hava_d:
                                st.info(f"💨 Hava Verildi — 1. Flaş bekleniyor")
                            elif tirmik_d:
                                st.info(f"🔧 Tırmık yapıldı — Hava bekleniyor")
                            elif toprak_d:
                                st.info(f"🌍 Toprak Serildi — Tırmık bekleniyor")
                            elif baski_d:
                                st.info(f"⚙️ Baskı yapıldı — Toprak Serim bekleniyor")
                            elif ekim_d:
                                st.info(f"🌱 Ekildi — Baskı bekleniyor")

                    # ── Düzenleme Alanı ─────────────────────────────────────
                    st.markdown("---")
                    if st.toggle("✏️ Tarihleri Düzenle", key=f"tog_{_edit_key}"):
                        st.caption("Tarihi silmek için ilgili checkbox'ı kaldırın.")
                        _alan_adlari = [
                            ("ekim_tarihi",          "🌱 Ekim",          ekim_d),
                            ("baski_tarihi",         "⚙️ Baskı",          baski_d),
                            ("toprak_serim_tarihi",  "🌍 Toprak Serim",   toprak_d),
                            ("tirmik_tarihi",        "🔧 Tırmık",         tirmik_d),
                            ("hava_verme_tarihi",    "💨 Hava Verme",     hava_d),
                            ("flash1_tarihi",        "🍄 1. Flaş",        flash1_d),
                            ("flash2_tarihi",        "🍄 2. Flaş",        flash2_d),
                            ("oda_bosaltma_tarihi",  "🚪 Oda Boşaltma",   bosaltma_d),
                        ]
                        _edit_vals = {}
                        _col_pairs = st.columns(3)
                        for _ei, (_alan, _lbl, _mev) in enumerate(_alan_adlari):
                            with _col_pairs[_ei % 3]:
                                _chk = st.checkbox(_lbl, value=_mev is not None, key=f"{_edit_key}_{_alan}_chk")
                                if _chk:
                                    _edit_vals[_alan] = st.date_input(
                                        f"{_lbl} Tarihi",
                                        value=_mev or date.today(),
                                        key=f"{_edit_key}_{_alan}_dt"
                                    )
                                else:
                                    _edit_vals[_alan] = None
                        _edit_aciklama = st.text_input(
                            "Açıklama",
                            value=str(row['aciklama']) if row['aciklama'] and str(row['aciklama']) not in ('None','nan','') else "",
                            key=f"{_edit_key}_acik"
                        )
                        if st.button("💾 Kaydet", type="primary", key=f"btn_{_edit_key}_save"):
                            conn = get_db_connection()
                            c = conn.cursor()
                            c.execute("""UPDATE oda_uretim_takip SET
                                ekim_tarihi=?, baski_tarihi=?, toprak_serim_tarihi=?,
                                tirmik_tarihi=?, hava_verme_tarihi=?, flash1_tarihi=?,
                                flash2_tarihi=?, oda_bosaltma_tarihi=?, aciklama=?
                                WHERE id=?""",
                                (
                                    str(_edit_vals["ekim_tarihi"])          if _edit_vals["ekim_tarihi"]          else None,
                                    str(_edit_vals["baski_tarihi"])         if _edit_vals["baski_tarihi"]         else None,
                                    str(_edit_vals["toprak_serim_tarihi"])  if _edit_vals["toprak_serim_tarihi"]  else None,
                                    str(_edit_vals["tirmik_tarihi"])        if _edit_vals["tirmik_tarihi"]        else None,
                                    str(_edit_vals["hava_verme_tarihi"])    if _edit_vals["hava_verme_tarihi"]    else None,
                                    str(_edit_vals["flash1_tarihi"])        if _edit_vals["flash1_tarihi"]        else None,
                                    str(_edit_vals["flash2_tarihi"])        if _edit_vals["flash2_tarihi"]        else None,
                                    str(_edit_vals["oda_bosaltma_tarihi"])  if _edit_vals["oda_bosaltma_tarihi"]  else None,
                                    _edit_aciklama,
                                    _ut_row_id
                                )
                            )
                            conn.commit()
                            conn.close()
                            st.success("✅ Kaydedildi!")
                            _rerun()

    # ── TAB 3: Gantt Takvim ───────────────────────────────────────────────────
    with tab3:
        conn = get_db_connection()
        df_gantt_src = _read_sql("""
            SELECT o.oda_adi, ut.*
            FROM oda_uretim_takip ut
            JOIN odalar o ON ut.oda_id = o.id
            ORDER BY o.oda_adi, ut.donem_no
        """, conn)
        conn.close()

        if df_gantt_src.empty:
            st.info("ℹ️ Görselleştirmek için kayıt yok.")
        else:
            bugun = date.today()
            gantt_rows = []

            for _, row in df_gantt_src.iterrows():
                oda_lbl  = f"{row['oda_adi']} (D{int(row['donem_no'])})"
                ekim_d   = _parse_ut_date(row['ekim_tarihi'])
                baski_d  = _parse_ut_date(row['baski_tarihi'])
                toprak_d = _parse_ut_date(row['toprak_serim_tarihi'])
                tirmik_d = _parse_ut_date(row['tirmik_tarihi'])
                hava_d      = _parse_ut_date(row['hava_verme_tarihi'])
                flash1_d    = _parse_ut_date(row['flash1_tarihi'])
                flash2_d    = _parse_ut_date(row.get('flash2_tarihi'))
                bosaltma_d  = _parse_ut_date(row.get('oda_bosaltma_tarihi'))

                if not ekim_d:
                    continue

                # Gerçek veya tahmin tarihlerini hesapla
                b_t  = baski_d  or ekim_d   + timedelta(days=10)
                tp_t = toprak_d or b_t       + timedelta(days=1)
                tr_t = tirmik_d or tp_t      + timedelta(days=9)
                hv_t = hava_d   or tr_t      + timedelta(days=3)
                # Toprak serim tarihi biliniyorsa 1. Flaş = toprak + 23 gün
                if flash1_d:
                    fl_t = flash1_d
                elif toprak_d:
                    fl_t = toprak_d + timedelta(days=23)
                else:
                    fl_t = hv_t + timedelta(days=11)
                fl2_t = flash2_d  or fl_t       + timedelta(days=14)
                bos_t = bosaltma_d or fl2_t     + timedelta(days=5)

                segmentler = [
                    ("Ekim → Baskı",        ekim_d,  b_t,    baski_d is not None),
                    ("Baskı → Toprak",      b_t,     tp_t,   toprak_d is not None),
                    ("Toprak → Tırmık",     tp_t,    tr_t,   tirmik_d is not None),
                    ("Tırmık → Hava",       tr_t,    hv_t,   hava_d is not None),
                    ("Hava → 1. Flaş",      hv_t,    fl_t,   flash1_d is not None),
                    ("1. Flaş → 2. Flaş",   fl_t,    fl2_t,  flash2_d is not None),
                    ("2. Flaş → Boşaltma",  fl2_t,   bos_t,  bosaltma_d is not None),
                ]

                for seg_adi, seg_bas, seg_bit, gercek in segmentler:
                    gantt_rows.append({
                        "Oda": oda_lbl,
                        "Evre": seg_adi,
                        "Başlangıç": pd.Timestamp(seg_bas),
                        "Bitiş": pd.Timestamp(seg_bit),
                        "Durum": "Gerçekleşti" if gercek else "Tahmini",
                    })

            if gantt_rows:
                df_gantt = pd.DataFrame(gantt_rows)
                RENK_MAP = {
                    "Ekim → Baskı":         "#4CAF50",
                    "Baskı → Toprak":       "#2196F3",
                    "Toprak → Tırmık":      "#FF9800",
                    "Tırmık → Hava":        "#9C27B0",
                    "Hava → 1. Flaş":       "#F44336",
                    "1. Flaş → 2. Flaş":   "#E91E63",
                    "2. Flaş → Boşaltma":  "#795548",
                }
                fig_gantt = px.timeline(
                    df_gantt,
                    x_start="Başlangıç",
                    x_end="Bitiş",
                    y="Oda",
                    color="Evre",
                    color_discrete_map=RENK_MAP,
                    pattern_shape="Durum",
                    pattern_shape_map={"Gerçekleşti": "", "Tahmini": "/"},
                    title="🍄 Oda Üretim Takvimi",
                    labels={"Oda": "Oda / Dönem"},
                    hover_data=["Durum", "Başlangıç", "Bitiş"],
                )
                fig_gantt.add_shape(
                    type="line",
                    x0=bugun.isoformat(), x1=bugun.isoformat(),
                    y0=0, y1=1,
                    xref="x", yref="paper",
                    line=dict(color="crimson", dash="dash", width=2),
                )
                fig_gantt.add_annotation(
                    x=bugun.isoformat(), y=1,
                    xref="x", yref="paper",
                    text="Bugün",
                    showarrow=False,
                    font=dict(color="crimson"),
                    xanchor="left",
                )
                fig_gantt.update_yaxes(autorange="reversed")
                fig_gantt.update_layout(
                    height=max(400, len(df_gantt_src) * 70),
                    xaxis_title="Tarih",
                    yaxis_title="",
                    legend_title="Üretim Evresi",
                )
                st.plotly_chart(fig_gantt, use_container_width=True)
                st.caption("✅ Düz çubuk = Gerçekleşti | 🔲 Çizgili çubuk = Tahmini")
            else:
                st.info("Gantt için Ekim tarihi girilmiş oda bulunamadı.")

# İş Planı
elif menu == "📅 İş Planı":
    st.title("📅 İş Planı")
    st.markdown("Seçili oda için yapılacak işleri tanımlayın, hatırlatma gününü belirleyin ve günü gelenleri takip edin.")

    def _parse_date(val):
        if val and str(val) not in ('None', 'nan', ''):
            try:
                return date.fromisoformat(str(val)[:10])
            except Exception:
                pass
        return None

    def _asama_label(key):
        return {
            'ekim_tarihi': '🌱 Ekim',
            'baski_tarihi': '⚙️ Baskı',
            'toprak_serim_tarihi': '🌍 Toprak Serim',
            'tirmik_tarihi': '🔧 Tırmık',
            'hava_verme_tarihi': '💨 Hava Verme',
            'flash1_tarihi': '🍄 1. Flaş',
            'flash2_tarihi': '🍄 2. Flaş',
            'oda_bosaltma_tarihi': '🚪 Oda Boşaltma',
        }.get(key, 'Özel Tarih')

    def _calc_plan_date(stage_date, offset):
        if stage_date is None:
            return None
        try:
            return stage_date - timedelta(days=int(offset or 0))
        except Exception:
            return None

    df_odalar_plani = _cached_odalar()
    if df_odalar_plani.empty:
        st.warning("⚠️ Önce oda eklemelisiniz. Oda Yönetimi menüsünden ekleyin.")
    else:
        tab1, tab2 = st.tabs(["📝 Plan Oluştur", "⏰ Günü Gelenler"])

        with tab1:
            st.subheader("Yeni İş Planı Kaydı")
            col1, col2 = st.columns(2)
            with col1:
                pl_oda = st.selectbox("Oda Seçin", df_odalar_plani['oda_adi'].tolist(), key="plan_oda")
                pl_oda_id = int(df_odalar_plani[df_odalar_plani['oda_adi'] == pl_oda]['id'].values[0])
            with col2:
                conn = get_db_connection()
                df_donemler = _read_sql(
                    "SELECT donem_no, ekim_tarihi, baski_tarihi, toprak_serim_tarihi, tirmik_tarihi, hava_verme_tarihi, flash1_tarihi, flash2_tarihi, oda_bosaltma_tarihi FROM oda_uretim_takip WHERE oda_id=? ORDER BY donem_no DESC",
                    conn,
                    params=(pl_oda_id,)
                )
                conn.close()
                donem_options = ["Genel"]
                if not df_donemler.empty:
                    donem_options += [f"Dönem {int(x)}" for x in df_donemler['donem_no'].tolist()]
                pl_donem = st.selectbox("Dönem", donem_options, key="plan_donem")

            pl_is_adi = st.text_input("Yapılacak İş", key="plan_is_adi")
            pl_referans = st.selectbox(
                "Referans Aşama",
                ["Özel Tarih", "� Ekim", "⚙️ Baskı", "🌍 Toprak Serim", "🔧 Tırmık", "💨 Hava Verme", "🍄 1. Flaş", "🍄 2. Flaş", "🚪 Oda Boşaltma"],
                key="plan_referans"
            )
            pl_offset = st.number_input("Kaç gün öncesinden hatırlatılacak?", min_value=0, max_value=30, value=5, step=1, key="plan_offset")

            ref_key = {
                'Özel Tarih': None,
                '🌱 Ekim': 'ekim_tarihi',
                '⚙️ Baskı': 'baski_tarihi',
                '🌍 Toprak Serim': 'toprak_serim_tarihi',
                '🔧 Tırmık': 'tirmik_tarihi',
                '💨 Hava Verme': 'hava_verme_tarihi',
                '🍄 1. Flaş': 'flash1_tarihi',
                '🍄 2. Flaş': 'flash2_tarihi',
                '🚪 Oda Boşaltma': 'oda_bosaltma_tarihi',
            }.get(pl_referans)

            pl_stage_date = None
            if ref_key and pl_donem != "Genel":
                row = df_donemler[df_donemler['donem_no'] == int(pl_donem.split(' ')[1])]
                if not row.empty:
                    pl_stage_date = _parse_date(row.iloc[0][ref_key])
            if ref_key and pl_stage_date:
                pl_plan_date = _calc_plan_date(pl_stage_date, pl_offset)
                st.success(f"Hatırlatma tarihi: {pl_plan_date.strftime('%d.%m.%Y')} (Referans: {_asama_label(ref_key)})")
            else:
                pl_plan_date = st.date_input("Hatırlatma Tarihi", value=date.today(), key="plan_tarih")
                if ref_key and not pl_stage_date:
                    st.warning("Seçilen referans evrenin tarihi bulunamadı; lütfen özel tarih girin veya üretim takvimini güncelleyin.")

            pl_aciklama = st.text_area("Açıklama", key="plan_aciklama")

            if st.button("💾 Planı Kaydet", type="primary", key="plan_save"):
                if not pl_is_adi:
                    st.error("İş adı boş bırakılamaz.")
                else:
                    donem_no = None if pl_donem == "Genel" else int(pl_donem.split(' ')[1])
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute(
                        "INSERT INTO is_plani (oda_id, donem_no, is_adi, referans_asama, hatirlatma_gun_once, plan_tarihi, aciklama) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            pl_oda_id,
                            donem_no,
                            pl_is_adi,
                            ref_key,
                            int(pl_offset),
                            str(pl_plan_date) if pl_plan_date else None,
                            pl_aciklama.strip() or None,
                        )
                    )
                    conn.commit()
                    conn.close()
                    st.success("✅ İş planı kaydedildi.")
                    _rerun()

            st.markdown("---")
            st.markdown("### Mevcut İş Planları")
            conn = get_db_connection()
            df_planlar = _read_sql(
                """
                SELECT t.*, o.oda_adi,
                       ut.flash1_tarihi, ut.flash2_tarihi, ut.oda_bosaltma_tarihi
                FROM is_plani t
                JOIN odalar o ON t.oda_id = o.id
                LEFT JOIN oda_uretim_takip ut ON ut.oda_id = t.oda_id AND ut.donem_no = COALESCE(t.donem_no, 1)
                ORDER BY t.durum, t.plan_tarihi ASC
                """,
                conn
            )
            conn.close()
            if df_planlar.empty:
                st.info("Henüz planlanmış iş yok.")
            else:
                plan_rows = []
                bugun = date.today()
                for _, row in df_planlar.iterrows():
                    ref_date = _parse_date(row.get(row['referans_asama'])) if row['referans_asama'] else None
                    plan_date = _parse_date(row.get('plan_tarihi'))
                    if row['referans_asama'] and ref_date is not None:
                        plan_date = _calc_plan_date(ref_date, row.get('hatirlatma_gun_once') or 0)
                    status = str(row.get('durum') or 'Beklemede')
                    if plan_date:
                        kalan = (plan_date - bugun).days
                        if status != 'Tamamlandı':
                            if kalan < 0:
                                durum = f"🔴 {abs(kalan)} gün gecikti"
                            elif kalan == 0:
                                durum = "🟡 Bugün"
                            else:
                                durum = f"🟢 {kalan} gün kaldı"
                        else:
                            durum = "✅ Tamamlandı"
                    else:
                        durum = "⚠️ Tarih yok"

                    plan_rows.append({
                        'Oda': row['oda_adi'],
                        'Dönem': row['donem_no'] if row['donem_no'] else 'Genel',
                        'İş': row['is_adi'],
                        'Referans': _asama_label(row['referans_asama']),
                        'Hatırlatma': plan_date.strftime('%d.%m.%Y') if plan_date else '',
                        'Önceki Gün': int(row.get('hatirlatma_gun_once') or 0),
                        'Durum': durum,
                        'Açıklama': row['aciklama'] or '',
                    })
                st.dataframe(pd.DataFrame(plan_rows), use_container_width=True)

        with tab2:
            st.subheader("Günü Gelen Hatırlatmalar")
            conn = get_db_connection()
            df_planlar = _read_sql(
                """
                SELECT t.*, o.oda_adi,
                       ut.flash1_tarihi, ut.flash2_tarihi, ut.oda_bosaltma_tarihi
                FROM is_plani t
                JOIN odalar o ON t.oda_id = o.id
                LEFT JOIN oda_uretim_takip ut ON ut.oda_id = t.oda_id AND ut.donem_no = COALESCE(t.donem_no, 1)
                WHERE t.durum != 'Tamamlandı'
                ORDER BY t.plan_tarihi ASC
                """,
                conn
            )
            conn.close()
            if df_planlar.empty:
                st.info("Bugün için hatırlatılacak kayıt yok.")
            else:
                bugun = date.today()
                due_rows = []
                for _, row in df_planlar.iterrows():
                    ref_date = _parse_date(row.get(row['referans_asama'])) if row['referans_asama'] else None
                    plan_date = _parse_date(row.get('plan_tarihi'))
                    if row['referans_asama'] and ref_date is not None:
                        plan_date = _calc_plan_date(ref_date, row.get('hatirlatma_gun_once') or 0)
                    if not plan_date:
                        continue
                    if plan_date <= bugun:
                        due_rows.append((row, plan_date, ref_date))

                if not due_rows:
                    st.info("Bugün veya geçmiş hatırlatma kaydı bulunamadı.")
                else:
                    for row, plan_date, ref_date in due_rows:
                        kalan = (plan_date - bugun).days
                        durum = "Bugün" if kalan == 0 else f"{abs(kalan)} gün {'geçti' if kalan < 0 else 'kaldı'}"
                        title = f"{row['oda_adi']} | {row['is_adi']} — {plan_date.strftime('%d.%m.%Y')} ({durum})"
                        with st.expander(title, expanded=False):
                            st.markdown(f"**Dönem:** {row['donem_no'] if row['donem_no'] else 'Genel'}")
                            st.markdown(f"**Referans:** {_asama_label(row['referans_asama'])}")
                            st.markdown(f"**Hatırlatma Tarihi:** {plan_date.strftime('%d.%m.%Y')}")
                            if ref_date:
                                st.markdown(f"**Referans Tarihi:** {ref_date.strftime('%d.%m.%Y')}")
                            st.markdown(f"**Hatırlatma Öncesi:** {int(row.get('hatirlatma_gun_once') or 0)} gün")
                            if row.get('aciklama'):
                                st.markdown(f"**Açıklama:** {row['aciklama']}")
                            if st.button("✅ Tamamlandı olarak işaretle", key=f"done_{row['id']}"):
                                conn = get_db_connection()
                                c = conn.cursor()
                                c.execute("UPDATE is_plani SET durum='Tamamlandı', tamamlanma_tarihi=? WHERE id=?", (str(bugun), int(row['id'])))
                                conn.commit()
                                conn.close()
                                st.success("Görev tamamlandı olarak işaretlendi.")
                                _rerun()

# Veri Yedekleme
elif menu == "📥 Veri Yedekleme":
    st.title("📥 Veri Yedekleme")
    
    st.markdown("### 💾 Verileri CSV Olarak İndir")
    st.info("Her tabloyu ayrı CSV dosyası olarak indirin. Excel veya başka programlarda açabilirsiniz.")
    
    conn = get_db_connection()
    
    tablolar = {
        "Gider_Kalemleri": "SELECT kalem_adi, birim_fiyat, aciklama FROM gider_kalemleri WHERE aktif=1",
        "Odalar": "SELECT oda_adi, alan_m2, kapasite_kg, durum, aciklama FROM odalar",
        "Oda_Giderleri": "SELECT o.oda_adi, og.gider_kalemi, og.tutar, og.tarih, og.aciklama FROM oda_giderleri og JOIN odalar o ON og.oda_id = o.id ORDER BY og.tarih DESC",
        "Gunluk_Hasat": "SELECT o.oda_adi, gh.tarih, gh.hasat_kg, gh.kalite, gh.aciklama FROM gunluk_hasat gh JOIN odalar o ON gh.oda_id = o.id ORDER BY gh.tarih DESC",
        "Satislar": "SELECT o.oda_adi, s.tarih, s.alan_kisi, s.satis_kg, s.birim_fiyat, s.toplam_tutar, s.fire_kg, s.nakliye_ucreti, s.aciklama FROM satislar s JOIN odalar o ON s.oda_id = o.id ORDER BY s.tarih DESC",
        "Iklim_Verileri": "SELECT o.oda_adi, iv.tarih, iv.saat, iv.sicaklik, iv.nem, iv.co2, iv.aciklama FROM iklim_verileri iv JOIN odalar o ON iv.oda_id = o.id ORDER BY iv.tarih DESC",
        "Isciler": "SELECT ad_soyad, telefon, pozisyon, gunluk_ucret, saat_ucreti FROM isciler WHERE aktif=1",
        "Puantaj": "SELECT i.ad_soyad, p.tarih, CASE WHEN p.tatil=1 THEN 'Tatil' ELSE 'Calisma' END as durum, p.giris_saati, p.cikis_saati, p.toplam_saat, p.mesai_saati, p.aciklama FROM puantaj p JOIN isciler i ON p.isci_id = i.id ORDER BY p.tarih DESC",
    }
    
    col1, col2 = st.columns(2)
    items = list(tablolar.items())
    for i, (tablo_adi, sorgu) in enumerate(items):
        df_backup = _read_sql(sorgu, conn)
        csv_data = df_backup.to_csv(index=False).encode('utf-8-sig')
        with (col1 if i % 2 == 0 else col2):
            st.download_button(
                label=f"📥 {tablo_adi.replace('_', ' ')} ({len(df_backup)} kayıt)",
                data=csv_data,
                file_name=f"{tablo_adi}_{date.today()}.csv",
                mime="text/csv",
                use_container_width=True,
                key=f"dl_{i}"
            )
    conn.close()
    
    st.markdown("---")
    st.markdown("### 📊 Veritabanı Özeti")
    conn = get_db_connection()
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Oda", _read_sql("SELECT COUNT(*) as c FROM odalar", conn).iloc[0, 0])
    with col2:
        st.metric("Hasat Kaydı", _read_sql("SELECT COUNT(*) as c FROM gunluk_hasat", conn).iloc[0, 0])
    with col3:
        st.metric("Satış Kaydı", _read_sql("SELECT COUNT(*) as c FROM satislar", conn).iloc[0, 0])
    with col4:
        st.metric("Puantaj Kaydı", _read_sql("SELECT COUNT(*) as c FROM puantaj", conn).iloc[0, 0])
    conn.close()

# Footer
st.markdown("---")
st.markdown(
    """
    <div style='text-align: center'>
        <p>🍄 Mantar Üretimi İş Takip Sistemi v1.0 | © 2026</p>
    </div>
    """,
    unsafe_allow_html=True
)
