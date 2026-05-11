#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mantar Üretimi İş Takip Sistemi - Ultra Performans Versiyon
Optimize edilmiş Streamlit Cloud performansı için tasarlandı
"""

import streamlit as st
import pandas as pd
import numpy as np
import sqlite3
import plotly.express as px
from datetime import date, datetime, timedelta
import re as _re
import os

# Performans optimizasyonları
st.set_page_config(
    page_title="Mantar İş Takip",
    page_icon="🍄",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ── Üretim Evreleri Arası Süreler ──────────────────────────────────────────────────
# Üretim takviminde girilen bir tarihten diğer evrelerin tahmini tarihlerini hesaplamak için
EVRE_SURELERI = {
    'ekim_tarihi': {'sonraki': 'baski_tarihi', 'gun_sonra': 10},
    'baski_tarihi': {'sonraki': 'toprak_serim_tarihi', 'gun_sonra': 1},
    'toprak_serim_tarihi': {'sonraki': 'tirmik_tarihi', 'gun_sonra': 9},
    'tirmik_tarihi': {'sonraki': 'hava_verme_tarihi', 'gun_sonra': 3},
    'hava_verme_tarihi': {'sonraki': 'flash1_tarihi', 'gun_sonra': 11},
    'flash1_tarihi': {'sonraki': 'flash2_tarihi', 'gun_sonra': 8},
    'flash2_tarihi': {'sonraki': 'oda_bosaltma_tarihi', 'gun_sonra': 5},
}

def _calc_tahmini_tarihler(uretim_tarihleri):
    """Üretim takvimindeki bilinen tarihlerden diğer evrelerin tahmini tarihlerini hesapla"""
    tahmini_tarihler = {}
    
    # Önce bilinen tarihleri kopyala
    for evre, tarih in uretim_tarihleri.items():
        if tarih:
            tahmini_tarihler[evre] = tarih
    
    # Bilinen bir tarihten diğerlerini hesapla (ileri ve geri)
    for evre, tarih in uretim_tarihleri.items():
        if not tarih:
            continue
        
        # İleri doğru hesapla
        current_evre = evre
        current_date = tarih
        while True:
            if current_evre not in EVRE_SURELERI:
                break
            sure_info = EVRE_SURELERI[current_evre]
            next_evre = sure_info['sonraki']
            gun_sonra = sure_info['gun_sonra']
            
            # Sonraki evre henüz bilinmiyorsa, hesapla
            if next_evre not in tahmini_tarihler or not tahmini_tarihler[next_evre]:
                tahmini_tarihler[next_evre] = current_date + timedelta(days=gun_sonra)
            
            current_evre = next_evre
            current_date = tahmini_tarihler[current_evre]
    
    # Geri doğru hesapla (önceki evreler için)
    for evre, tarih in uretim_tarihleri.items():
        if not tarih:
            continue
        
        # Önceki evreyi bul ve hesapla
        current_evre = evre
        current_date = tarih
        while True:
            onceki_evre = None
            gun_once = None
            for ev, info in EVRE_SURELERI.items():
                if info['sonraki'] == current_evre:
                    onceki_evre = ev
                    gun_once = info['gun_sonra']
                    break
            
            if not onceki_evre:
                break
            
            # Önceki evre henüz bilinmiyorsa, hesapla
            if onceki_evre not in tahmini_tarihler or not tahmini_tarihler[onceki_evre]:
                tahmini_tarihler[onceki_evre] = current_date - timedelta(days=gun_once)
            
            current_evre = onceki_evre
            current_date = tahmini_tarihler[current_evre]
    
    return tahmini_tarihler

# ── Şifre Koruması ────────────────────────────────────────────────────────────
APP_SIFRE = "mantar2024"   # ← Buradan şifrenizi değiştirebilirsiniz

# Session state'i initialize et ve URL params'dan kontrol et
if "giris_yapildi" not in st.session_state:
    st.session_state["giris_yapildi"] = False

# URL'de authenticated parametresi varsa, giriş yapıldı say
if st.query_params.get("authenticated") == "true":
    st.session_state["giris_yapildi"] = True

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
                # URL'ye authenticated param ekle
                st.query_params["authenticated"] = "true"
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
                if ('is_plani' in pg_sql.lower() or 'is_plani_profili' in pg_sql.lower() or 'is_plani_profil_isahleri' in pg_sql.lower()) and (
                    'undefinedtable' in error_text or
                    ('relation "is_plani"' in error_text and 'does not exist' in error_text) or
                    ('relation "is_plani_profili"' in error_text and 'does not exist' in error_text) or
                    ('relation "is_plani_profil_isahleri"' in error_text and 'does not exist' in error_text) or
                    'does not exist' in error_text and ('is_plani' in error_text or 'is_plani_profili' in error_text or 'is_plani_profil_isahleri' in error_text)
                ):
                    # PostgreSQL'de hata sonrası transaction durumunu sıfırla
                    try:
                        raw.rollback()
                    except Exception:
                        pass
                    
                    # Yeni cursor ile tabloları oluştur
                    create_cur = raw.cursor()
                    try:
                        if 'is_plani_profil_isahleri' in pg_sql.lower():
                            # First ensure the parent table exists
                            create_cur.execute('''CREATE TABLE IF NOT EXISTS is_plani_profili
                                                 (id SERIAL PRIMARY KEY,
                                                  profil_adi TEXT NOT NULL UNIQUE,
                                                  aciklama TEXT,
                                                  olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                            # Then create the child table
                            create_cur.execute('''CREATE TABLE IF NOT EXISTS is_plani_profil_isahleri
                                                 (id SERIAL PRIMARY KEY,
                                                  profil_id INTEGER NOT NULL,
                                                  is_adi TEXT NOT NULL,
                                                  referans_asama TEXT,
                                                  hatirlatma_gun_once INTEGER DEFAULT 0,
                                                  siralama INTEGER DEFAULT 0,
                                                  FOREIGN KEY (profil_id) REFERENCES is_plani_profili(id))''')
                        elif 'is_plani_profili' in pg_sql.lower():
                            create_cur.execute('''CREATE TABLE IF NOT EXISTS is_plani_profili
                                                 (id SERIAL PRIMARY KEY,
                                                  profil_adi TEXT NOT NULL UNIQUE,
                                                  aciklama TEXT,
                                                  olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                            # Also create the related table
                            create_cur.execute('''CREATE TABLE IF NOT EXISTS is_plani_profil_isahleri
                                                 (id SERIAL PRIMARY KEY,
                                                  profil_id INTEGER NOT NULL,
                                                  is_adi TEXT NOT NULL,
                                                  referans_asama TEXT,
                                                  hatirlatma_gun_once INTEGER DEFAULT 0,
                                                  siralama INTEGER DEFAULT 0,
                                                  FOREIGN KEY (profil_id) REFERENCES is_plani_profili(id))''')
                        else:
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
        except Exception as e:
            # Additional debugging for is_plani_profil_isahleri
            if 'is_plani_profil_isahleri' in pg_sql.lower():
                error_text = f"{e}".lower() + " " + repr(e).lower()
                if 'column' in error_text and 'does not exist' in error_text:
                    # Column doesn't exist - table structure might be wrong
                    try:
                        raw.rollback()
                        fix_cur = raw.cursor()
                        # Drop and recreate table with correct structure
                        fix_cur.execute("DROP TABLE IF EXISTS is_plani_profil_isahleri")
                        fix_cur.execute('''CREATE TABLE is_plani_profil_isahleri
                                             (id SERIAL PRIMARY KEY,
                                              profil_id INTEGER NOT NULL,
                                              is_adi TEXT NOT NULL,
                                              referans_asama TEXT,
                                              hatirlatma_gun_once INTEGER DEFAULT 0,
                                              siralama INTEGER DEFAULT 0,
                                              FOREIGN KEY (profil_id) REFERENCES is_plani_profili(id))''')
                        raw.commit()
                        fix_cur.close()
                        # Retry the original query
                        retry_cur = raw.cursor()
                        retry_cur.execute(pg_sql, params) if params is not None else retry_cur.execute(pg_sql)
                        if retry_cur.description is None:
                            return pd.DataFrame()
                        cols = [d[0].lower() for d in retry_cur.description]
                        rows = retry_cur.fetchall()
                        return pd.DataFrame(rows, columns=cols)
                    except Exception:
                        pass
            raise
        finally:
            cur.close()
    return pd.read_sql(sql, conn, params=params)

# ── Ultra Performans: Agresif Cache'lenmiş veriler ─────────────────────────────────
@st.cache_data(ttl=300)  # 5 dakika cache
@st.fragment
def _cached_odalar():
    conn = get_db_connection()
    df = _read_sql("SELECT id, oda_adi FROM odalar ORDER BY oda_adi", conn)
    conn.close()
    return df

@st.cache_data(ttl=300)  # 5 dakika cache
@st.fragment
def _cached_odalar_aktif():
    conn = get_db_connection()
    df = _read_sql("SELECT id, oda_adi FROM odalar WHERE durum='Aktif' ORDER BY oda_adi", conn)
    conn.close()
    return df

@st.cache_data(ttl=600)  # 10 dakika cache
@st.fragment
def _cached_gider_kalemleri():
    conn = get_db_connection()
    df = _read_sql("SELECT kalem_adi, birim_fiyat FROM gider_kalemleri WHERE aktif=1 ORDER BY kalem_adi", conn)
    conn.close()
    return df

@st.cache_data(ttl=300)  # 5 dakika cache
@st.fragment
def _cached_cariler():
    conn = get_db_connection()
    df = _read_sql("SELECT id, cari_adi FROM cariler WHERE aktif=1 ORDER BY cari_adi", conn)
    conn.close()
    return df

# Ana sayfa metrikleri için cache
@st.cache_data(ttl=60)  # 1 dakika cache
@st.fragment
def _cached_anasayfa_metrikleri():
    conn = get_db_connection()
    try:
        toplam_oda = int(_read_sql("SELECT COUNT(*) as cnt FROM odalar WHERE durum='Aktif'", conn).iloc[0, 0] or 0)
        bugun_hasat = float(_read_sql(f"SELECT COALESCE(SUM(hasat_kg), 0) as toplam FROM gunluk_hasat WHERE tarih='{date.today()}'", conn).iloc[0, 0] or 0)
        bu_ay_satis = float(_read_sql(f"SELECT COALESCE(SUM(toplam_tutar), 0) as toplam FROM satislar WHERE strftime('%Y-%m', tarih)='{date.today().strftime('%Y-%m')}'", conn).iloc[0, 0] or 0)
        return toplam_oda, bugun_hasat, bu_ay_satis
    finally:
        conn.close()

# Giderler için cache
@st.cache_data(ttl=300)
@st.fragment
def _cached_giderler():
    conn = get_db_connection()
    df = _read_sql("SELECT * FROM gider_kalemleri WHERE aktif=1 ORDER BY kalem_adi", conn)
    conn.close()
    return df

# Odalar için cache
@st.cache_data(ttl=300)
@st.fragment
def _cached_tum_odalar():
    conn = get_db_connection()
    df = _read_sql("SELECT * FROM odalar ORDER BY oda_adi", conn)
    conn.close()
    return df

# Hasat verileri için cache
@st.cache_data(ttl=120)
@st.fragment
def _cached_hasat_verileri(filtre_oda, tarih_baslangic, tarih_bitis):
    conn = get_db_connection()
    if filtre_oda == "Tümü":
        df = _read_sql(f"""
            SELECT gh.id, gh.tarih, o.oda_adi, gh.hasat_kg, gh.kalite, gh.aciklama
            FROM gunluk_hasat gh
            JOIN odalar o ON gh.oda_id = o.id
            WHERE gh.tarih BETWEEN '{tarih_baslangic}' AND '{tarih_bitis}'
            ORDER BY gh.tarih DESC, o.oda_adi
        """, conn)
    else:
        df = _read_sql(f"""
            SELECT gh.id, gh.tarih, o.oda_adi, gh.hasat_kg, gh.kalite, gh.aciklama
            FROM gunluk_hasat gh
            JOIN odalar o ON gh.oda_id = o.id
            WHERE o.oda_adi = '{filtre_oda}' AND gh.tarih BETWEEN '{tarih_baslangic}' AND '{tarih_bitis}'
            ORDER BY gh.tarih DESC
        """, conn)
    conn.close()
    return df

# İklim verileri için cache
@st.cache_data(ttl=60)
@st.fragment
def _cached_iklim_verileri(secili_oda, gun_sayisi):
    conn = get_db_connection()
    if gun_sayisi == "Tümü":
        df = _read_sql(f"""
            SELECT iv.tarih, iv.saat, iv.sicaklik, iv.nem, iv.co2
            FROM iklim_verileri iv
            JOIN odalar o ON iv.oda_id = o.id
            WHERE o.oda_adi = '{secili_oda}'
            ORDER BY iv.tarih DESC, iv.saat DESC
        """, conn)
    else:
        gun = int(gun_sayisi.split()[1])
        baslangic = date.today() - timedelta(days=gun)
        df = _read_sql(f"""
            SELECT iv.tarih, iv.saat, iv.sicaklik, iv.nem, iv.co2
            FROM iklim_verileri iv
            JOIN odalar o ON iv.oda_id = o.id
            WHERE o.oda_adi = '{secili_oda}' AND iv.tarih >= '{baslangic}'
            ORDER BY iv.tarih DESC, iv.saat DESC
        """, conn)
    conn.close()
    return df

def _cache_temizle():
    """Veri değişikliğinde tüm cache'leri sıfırla."""
    _cached_odalar.clear()
    _cached_odalar_aktif.clear()
    _cached_gider_kalemleri.clear()
    _cached_cariler.clear()
    _cached_anasayfa_metrikleri.clear()
    _cached_giderler.clear()
    _cached_tum_odalar.clear()
    # Hasat ve iklim verileri cache'leri parametreli olduğu için otomatik temizlenir

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
        id_type = "SERIAL PRIMARY KEY"
    else:
        conn = sqlite3.connect(DB_PATH)
        id_type = "INTEGER PRIMARY KEY AUTOINCREMENT"
    c = conn.cursor()
    
    # Gider kalemleri tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS gider_kalemleri
                 (id SERIAL PRIMARY KEY,
                  kalem_adi TEXT NOT NULL,
                  birim_fiyat REAL NOT NULL,
                  aciklama TEXT,
                  aktif INTEGER DEFAULT 1,
                  olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Odalar tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS odalar
                 (id SERIAL PRIMARY KEY,
                  oda_adi TEXT NOT NULL UNIQUE,
                  alan_m2 REAL,
                  kapasite_kg REAL,
                  durum TEXT DEFAULT 'Aktif',
                  aciklama TEXT,
                  olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Oda giderleri tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS oda_giderleri
                 (id SERIAL PRIMARY KEY,
                  oda_id INTEGER NOT NULL,
                  gider_kalemi TEXT NOT NULL,
                  tutar REAL NOT NULL,
                  tarih DATE NOT NULL,
                  aciklama TEXT,
                  FOREIGN KEY (oda_id) REFERENCES odalar(id))''')
    
    # Günlük hasat tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS gunluk_hasat
                 (id SERIAL PRIMARY KEY,
                  oda_id INTEGER NOT NULL,
                  tarih DATE NOT NULL,
                  hasat_kg REAL NOT NULL,
                  kalite TEXT,
                  aciklama TEXT,
                  FOREIGN KEY (oda_id) REFERENCES odalar(id))''')
    
    # Satış tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS satislar
                 (id SERIAL PRIMARY KEY,
                  oda_id INTEGER NOT NULL,
                  tarih DATE NOT NULL,
                  miktar_kg REAL NOT NULL,
                  birim_fiyat REAL NOT NULL,
                  alan_kisi TEXT,
                  cari_id INTEGER,
                  aciklama TEXT,
                  FOREIGN KEY (oda_id) REFERENCES odalar(id))''')
    
    # İklim verileri tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS iklim_verileri
                 (id SERIAL PRIMARY KEY,
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
                 (id SERIAL PRIMARY KEY,
                  ad_soyad TEXT NOT NULL,
                  telefon TEXT,
                  ucret_saati REAL,
                  aciklama TEXT,
                  olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Puantaj tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS puantaj
                 (id SERIAL PRIMARY KEY,
                  isci_id INTEGER NOT NULL,
                  tarih DATE NOT NULL,
                  saat_sayisi REAL NOT NULL DEFAULT 0,
                  ucret_saati REAL,
                  aciklama TEXT,
                  FOREIGN KEY (isci_id) REFERENCES isciler(id))''')
    
    # Migration: tatil sütununu eski veritabanlarına ekle
    try:
        c.execute("ALTER TABLE puantaj ADD COLUMN tatil INTEGER DEFAULT 0")
    except Exception:
        pass  # Sütun zaten mevcut

    # Oda Üretim Takip tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS oda_uretim_takip
                 (id SERIAL PRIMARY KEY,
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
                 (id SERIAL PRIMARY KEY,
                  oda_id INTEGER NOT NULL,
                  donem_no INTEGER,
                  is_adi TEXT NOT NULL,
                  referans_asama TEXT,
                  planlanan_tarih DATE,
                  yapildimi INTEGER DEFAULT 0,
                  yapilis_tarihi DATE,
                  hatirlatma_gun_once INTEGER DEFAULT 0,
                  aciklama TEXT,
                  durum TEXT DEFAULT 'Beklemede',
                  tamamlanma_tarihi DATE,
                  olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (oda_id) REFERENCES odalar(id))''')

    # İş Planı Profili tablosu (şablonlar)
    c.execute('''CREATE TABLE IF NOT EXISTS is_plani_profili
                 (id SERIAL PRIMARY KEY,
                  profil_adi TEXT NOT NULL UNIQUE,
                  aciklama TEXT,
                  olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # İş Planı Profil İşleri tablosu (profil içindeki her iş)
    c.execute('''CREATE TABLE IF NOT EXISTS is_plani_profil_isahleri
                 (id SERIAL PRIMARY KEY,
                  profil_id INTEGER NOT NULL,
                  is_adi TEXT NOT NULL,
                  referans_asama TEXT,
                  hatirlatma_gun_once INTEGER DEFAULT 0,
                  siralama INTEGER DEFAULT 0,
                  FOREIGN KEY (profil_id) REFERENCES is_plani_profili(id))''')

    # Cariler tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS cariler
                 (id SERIAL PRIMARY KEY,
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
                 (id SERIAL PRIMARY KEY,
                  cari_id INTEGER NOT NULL REFERENCES cariler(id),
                  tarih DATE NOT NULL,
                  islem_turu TEXT NOT NULL CHECK (islem_turu IN ('SATIS', 'ALIS', 'TAHSILAT', 'ODEME')),
                  aciklama TEXT,
                  borc REAL DEFAULT 0,
                  alacak REAL DEFAULT 0,
                  bakiye REAL,
                  FOREIGN KEY (cari_id) REFERENCES cariler(id))''')

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
    
    # Garanti: İş Planı Profili tablolarını oluştur (Cloud'da sorun olmaması için)
    try:
        # Önce parent table
        c.execute('''CREATE TABLE IF NOT EXISTS is_plani_profili
                     (id SERIAL PRIMARY KEY,
                      profil_adi TEXT NOT NULL UNIQUE,
                      aciklama TEXT,
                      olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # Sonra child table
        c.execute('''CREATE TABLE IF NOT EXISTS is_plani_profil_isahleri
                     (id SERIAL PRIMARY KEY,
                      profil_id INTEGER NOT NULL,
                      is_adi TEXT NOT NULL,
                      referans_asama TEXT,
                      hatirlatma_gun_once INTEGER DEFAULT 0,
                      siralama INTEGER DEFAULT 0,
                      FOREIGN KEY (profil_id) REFERENCES is_plani_profili(id))''')
    except Exception as e:
        st.error(f"İş Planı Profili tabloları oluşturulamadı: {e}")
    
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
                     (id SERIAL PRIMARY KEY,
                      oda_id INTEGER NOT NULL,
                      donem_no INTEGER,
                      is_adi TEXT NOT NULL,
                      referans_asama TEXT,
                      planlanan_tarih DATE,
                      yapildimi INTEGER DEFAULT 0,
                      yapilis_tarihi DATE,
                      hatirlatma_gun_once INTEGER DEFAULT 0,
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

# Gelir-Gider Şablonu tablolarını garanti oluştur
def _ensure_gelir_gider_sablonu_tables():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS gelir_gider_sablonlari
                     (id SERIAL PRIMARY KEY,
                      sablon_adi TEXT NOT NULL UNIQUE,
                      verim_orani REAL NOT NULL DEFAULT 100.0,
                      cikma_orani REAL NOT NULL DEFAULT 5.0,
                      cikma_satis_fiyati REAL NOT NULL DEFAULT 15.0,
                      birinci_kalite_fiyat REAL NOT NULL DEFAULT 45.0,
                      kasa_maliyeti REAL NOT NULL DEFAULT 12.0,
                      toplama_yontemi TEXT NOT NULL DEFAULT 'Tabağa Toplama',
                      aciklama TEXT,
                      olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS sablon_oda_giderleri
                     (id SERIAL PRIMARY KEY,
                      sablon_id INTEGER NOT NULL,
                      oda_id INTEGER NOT NULL,
                      gider_adi TEXT NOT NULL,
                      gider_maliyeti REAL NOT NULL DEFAULT 0.0,
                      olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      FOREIGN KEY (sablon_id) REFERENCES gelir_gider_sablonlari(id) ON DELETE CASCADE,
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

_ensure_gelir_gider_sablonu_tables()

# Borç Yönetimi tablolarını garanti oluştur
def _ensure_borc_yonetimi_tables():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        # Kısa Vadeli Borçlar tablosu
        c.execute('''CREATE TABLE IF NOT EXISTS kisalik_borclar
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      borc_adi TEXT NOT NULL,
                      tutar REAL NOT NULL,
                      faiz_orani REAL NOT NULL,
                      vade_gun INTEGER NOT NULL,
                      odeme_tarihi DATE NOT NULL,
                      kategori TEXT NOT NULL,
                      olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # Uzun Vadeli Borçlar tablosu
        c.execute('''CREATE TABLE IF NOT EXISTS uzunv_borclar
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      borc_adi TEXT NOT NULL,
                      tutar REAL NOT NULL,
                      faiz_orani REAL NOT NULL,
                      aylik_taksit REAL NOT NULL,
                      kalan_ay INTEGER NOT NULL,
                      kategori TEXT NOT NULL,
                      olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # Banka Kredileri tablosu
        c.execute('''CREATE TABLE IF NOT EXISTS banka_kredileri
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      banka_adi TEXT NOT NULL,
                      kredi_turu TEXT NOT NULL,
                      kredi_limit REAL NOT NULL,
                      faiz_orani REAL NOT NULL,
                      kullanilan_tutar REAL NOT NULL DEFAULT 0.0,
                      odeme_gunu INTEGER NOT NULL,
                      olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # Risk Senaryoları tablosu
        c.execute('''CREATE TABLE IF NOT EXISTS risk_senaryolari
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      risk_adi TEXT NOT NULL,
                      risk_turu TEXT NOT NULL,
                      olasilik REAL NOT NULL,
                      finansal_etki REAL NOT NULL,
                      aciklama TEXT,
                      olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # Nakit Akışı tablosu
        c.execute('''CREATE TABLE IF NOT EXISTS nakit_akisi
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      birinci_flas_ton REAL,
                      birinci_flas_fiyat REAL,
                      birinci_flas_vade INTEGER,
                      ikinci_flas_ton REAL,
                      ikinci_flas_fiyat REAL,
                      ikinci_flas_vade INTEGER,
                      kulucka_suresi INTEGER,
                      topraklama_suresi INTEGER,
                      birinci_flas_suresi INTEGER,
                      ikinci_flas_suresi INTEGER,
                      olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        conn.commit()
        print("Borç yönetimi tabloları oluşturuldu")
    except Exception as e:
        print(f"Borç yönetimi tablo oluşturma hatası: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass

_ensure_borc_yonetimi_tables()

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
     "📥 Veri Yedekleme", "💵 Gelir Hesaplama", "📊 Gelir-Gider Şablonu",
     "💳 Borç Yönetimi"]
)

st.sidebar.markdown("---")
st.sidebar.info("**Mantar Üretimi İş Takip Sistemi v1.0**")

# Ana Sayfa
if menu == "🏠 Ana Sayfa":
    st.title("🍄 Mantar Üretimi İş Takip Sistemi")
    st.markdown("### Hoş Geldiniz!")
    
    col1, col2, col3 = st.columns(3)
    
    conn = get_db_connection()
    
    # Özet istatistikler - cache'den al
    try:
        toplam_oda, bugun_hasat, bu_ay_satis = _cached_anasayfa_metrikleri()
        
        with col1:
            st.metric("Toplam Oda Sayısı", toplam_oda)
        
        with col2:
            st.metric("Bugünkü Hasat (kg)", f"{bugun_hasat:.2f}")
        
        with col3:
            st.metric("Bu Ay Satış (TL)", f"{bu_ay_satis:,.2f}")
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
        df_giderler = _cached_giderler()
        
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
        df_odalar = _cached_tum_odalar()
        
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
        
        df_odalar = _cached_odalar()
        df_giderler = _cached_gider_kalemleri()
        
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
            df_odalar = _cached_odalar()
            filtre_oda = st.selectbox("Oda Filtresi", ["Tümü"] + df_odalar['oda_adi'].tolist())
        
        # Verileri çek - cache'den al
        df_hasat = _cached_hasat_verileri(filtre_oda, tarih_baslangic, tarih_bitis)
        
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
        
        df_odalar = _cached_odalar()
        
        if not df_odalar.empty:
            # Filtreleme
            col1, col2 = st.columns(2)
            with col1:
                grafik_oda = st.selectbox("Oda Seçin", df_odalar['oda_adi'].tolist())
            with col2:
                gun_sayisi = st.selectbox("Zaman Aralığı", ["Son 7 Gün", "Son 14 Gün", "Son 30 Gün", "Tümü"])
            
            # Veri çek - cache'den al
            df_iklim = _cached_iklim_verileri(grafik_oda, gun_sayisi)
            
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
        tab1, tab2, tab3 = st.tabs(["📝 Plan Oluştur", "⏰ Günü Gelenler", "📋 Profil Yönetimi"])

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
                    # Enhanced hatırlatma tarihleri hesaplama ve gösterimi - Üretim Takvimi ile Koordine
                    ref_date = _parse_date(row.get(row['referans_asama'])) if row['referans_asama'] else None
                    plan_date = _parse_date(row.get('plan_tarihi'))
                    hatirlatma_gun_once = int(row.get('hatirlatma_gun_once') or 0)
                    
                    # Üretim takviminden gerçek evre tarihlerini al
                    oda_id = row.get('oda_id')
                    donem_no = row.get('donem_no') or 1
                    uretim_tarihleri = {}
                    
                    if oda_id:
                        conn_uretim = get_db_connection()
                        df_uretim = _read_sql("""
                            SELECT flash1_tarihi, flash2_tarihi, oda_bosaltma_tarihi,
                                   ekim_tarihi, baski_tarihi, toprak_serim_tarihi,
                                   tirmik_tarihi, hava_verme_tarihi
                            FROM oda_uretim_takip
                            WHERE oda_id = ? AND donem_no = ?
                        """, conn_uretim, params=(oda_id, donem_no))
                        conn_uretim.close()
                        
                        if not df_uretim.empty:
                            uretim_row = df_uretim.iloc[0]
                            uretim_tarihleri = {
                                'ekim_tarihi': _parse_date(uretim_row.get('ekim_tarihi')),
                                'baski_tarihi': _parse_date(uretim_row.get('baski_tarihi')),
                                'toprak_serim_tarihi': _parse_date(uretim_row.get('toprak_serim_tarihi')),
                                'tirmik_tarihi': _parse_date(uretim_row.get('tirmik_tarihi')),
                                'hava_verme_tarihi': _parse_date(uretim_row.get('hava_verme_tarihi')),
                                'flash1_tarihi': _parse_date(uretim_row.get('flash1_tarihi')),
                                'flash2_tarihi': _parse_date(uretim_row.get('flash2_tarihi')),
                                'oda_bosaltma_tarihi': _parse_date(uretim_row.get('oda_bosaltma_tarihi')),
                            }
                    
                    # Tahmini tarihleri hesapla (üretim takvimindeki bilinen tarihlerden)
                    tahmini_tarihler = _calc_tahmini_tarihler(uretim_tarihleri)
                    
                    # Hatırlatma tarihini hesapla - Üretim takvimi tabanlı
                    referans_asama_val = row.get('referans_asama')
                    if referans_asama_val and pd.notna(referans_asama_val):
                        referans_asama_str = str(referans_asama_val)
                        # referans_asama zaten "_tarihi" ile bitiyorsa, eklemeye gerek yok
                        if referans_asama_str.endswith('_tarihi'):
                            referans_evre_key = referans_asama_str
                        else:
                            referans_evre_key = referans_asama_str + '_tarihi'
                        
                        # 1. Önce üretim takviminden gerçek tarihi al
                        gercek_ref_date = uretim_tarihleri.get(referans_evre_key)
                        if gercek_ref_date:
                            # Üretim takviminde gerçek tarih var - buna göre hesapla
                            plan_date = _calc_plan_date(gercek_ref_date, hatirlatma_gun_once)
                            hatirlatma_tipi = f"Referans: {_asama_label(referans_evre_key)} (Üretim Takvimi)"
                        else:
                            # 2. Gerçek tarih yok, tahmini tarihi kontrol et
                            tahmini_ref_date = tahmini_tarihler.get(referans_evre_key)
                            if tahmini_ref_date:
                                # Tahmini tarih var - buna göre hesapla
                                plan_date = _calc_plan_date(tahmini_ref_date, hatirlatma_gun_once)
                                hatirlatma_tipi = f"Referans: {_asama_label(referans_evre_key)} (Tahmini)"
                            elif ref_date is not None:
                                # 3. Tahmini tarih yok ama ref_date var - bunu kullan
                                plan_date = _calc_plan_date(ref_date, hatirlatma_gun_once)
                                hatirlatma_tipi = f"Referans: {_asama_label(referans_evre_key)} (Standart)"
                            else:
                                # 4. Referans var ama hiçbir tarih yok - bugünden tahmini
                                plan_date = bugun + timedelta(days=hatirlatma_gun_once)
                                hatirlatma_tipi = f"Tahmini: {_asama_label(referans_evre_key)} (Referans Tarihi Yok)"
                    elif plan_date:
                        hatirlatma_tipi = "Manuel Tarih"
                    else:
                        # Referans yok - bugünden tahmini
                        plan_date = bugun + timedelta(days=hatirlatma_gun_once)
                        hatirlatma_tipi = f"Tahmini ({hatirlatma_gun_once} gün sonrası)"
                    
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
                        'Hatırlatma Tarihi': plan_date.strftime('%d.%m.%Y') if plan_date else '',
                        'Hatırlatma Tipi': hatirlatma_tipi,
                        'Önceki Gün': hatirlatma_gun_once,
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

        with tab3:
            st.subheader("📋 İş Planı Profilleri")
            st.markdown("Tüm odalara uygulanabilecek iş planı şablonları oluşturun ve yönetin.")

            subtab1, subtab2, subtab3 = st.tabs(["➕ Yeni Profil", "📚 Profilleri Görüntüle", "🔧 Profil Uygula"])

            with subtab1:
                st.markdown("### Yeni İş Planı Profili Oluştur")
                prof_adi = st.text_input("Profil Adı (benzersiz)", key="prof_adi")
                prof_acik = st.text_area("Profil Açıklaması", key="prof_acik")

                st.markdown("#### İşleri Ekle")
                is_adilar = []
                referans_asamalar = []
                hatirlatma_gunleri = []

                num_isler = st.number_input("Kaç iş eklemek istersiniz?", min_value=1, max_value=20, value=3, key="prof_num_isler")
                for i in range(int(num_isler)):
                    col1, col2, col3 = st.columns([2, 2, 1])
                    with col1:
                        is_adi = st.text_input(f"İş {i+1} Adı", key=f"prof_is_adi_{i}")
                        is_adilar.append(is_adi)
                    with col2:
                        ref_as = st.selectbox(
                            f"İş {i+1} Referans",
                            ["🌱 Ekim", "⚙️ Baskı", "🌍 Toprak Serim", "🔧 Tırmık", "💨 Hava Verme", "🍄 1. Flaş", "🍄 2. Flaş", "🚪 Oda Boşaltma"],
                            key=f"prof_ref_as_{i}"
                        )
                        referans_asamalar.append({
                            "🌱 Ekim": "ekim_tarihi",
                            "⚙️ Baskı": "baski_tarihi",
                            "🌍 Toprak Serim": "toprak_serim_tarihi",
                            "🔧 Tırmık": "tirmik_tarihi",
                            "💨 Hava Verme": "hava_verme_tarihi",
                            "🍄 1. Flaş": "flash1_tarihi",
                            "🍄 2. Flaş": "flash2_tarihi",
                            "🚪 Oda Boşaltma": "oda_bosaltma_tarihi",
                        }.get(ref_as))
                    with col3:
                        hat_gun = st.number_input(f"Gün Öncesi", min_value=0, max_value=30, value=5, key=f"prof_hat_gun_{i}")
                        hatirlatma_gunleri.append(hat_gun)

                if st.button("💾 Profili Kaydet", type="primary", key="prof_save"):
                    if not prof_adi:
                        st.error("Profil adı boş bırakılamaz.")
                    elif not all(is_adilar):
                        st.error("Tüm iş adları doldurulmalıdır.")
                    else:
                        conn = get_db_connection()
                        c = conn.cursor()
                        try:
                            c.execute("INSERT INTO is_plani_profili (profil_adi, aciklama) VALUES (?, ?)", (prof_adi, prof_acik or None))
                            prof_id = c.lastrowid
                            for idx, (is_adi, ref_as, hat_gun) in enumerate(zip(is_adilar, referans_asamalar, hatirlatma_gunleri)):
                                if is_adi:
                                    c.execute("INSERT INTO is_plani_profil_isahleri (profil_id, is_adi, referans_asama, hatirlatma_gun_once, siralama) VALUES (?, ?, ?, ?, ?)",
                                              (prof_id, is_adi, ref_as, int(hat_gun), idx))
                            conn.commit()
                            st.success(f"✅ '{prof_adi}' profili kaydedildi.")
                            _rerun()
                        except Exception as e:
                            st.error(f"Hata: {e}")
                        finally:
                            conn.close()

            with subtab2:
                st.markdown("### Mevcut Profiller")
                conn = get_db_connection()
                df_profiler = _read_sql("SELECT * FROM is_plani_profili ORDER BY profil_adi", conn)
                conn.close()

                if df_profiler.empty:
                    st.info("Henüz profil yoktur.")
                else:
                    for _, prof_row in df_profiler.iterrows():
                        prof_id = prof_row['id']
                        prof_name = prof_row['profil_adi']
                        prof_desc = prof_row['aciklama'] or ""

                        with st.expander(f"📋 {prof_name}", expanded=False):
                            if prof_desc:
                                st.markdown(f"**Açıklama:** {prof_desc}")

                            conn = get_db_connection()
                            df_isahleri = _read_sql("SELECT * FROM is_plani_profil_isahleri WHERE profil_id=? ORDER BY siralama", conn, params=(prof_id,))
                            conn.close()

                            if not df_isahleri.empty:
                                st.markdown("**İşler:**")
                                for _, iş_row in df_isahleri.iterrows():
                                    ref_lbl = _asama_label(iş_row['referans_asama'])
                                    st.markdown(f"- **{iş_row['is_adi']}** ({ref_lbl} — {int(iş_row['hatirlatma_gun_once'])} gün önce)")

                            col1, col2 = st.columns(2)
                            with col1:
                                if st.button("✏️ Düzenle", key=f"prof_edit_{prof_id}"):
                                    st.warning("Düzenleme özelliği yakında eklenecek.")
                            with col2:
                                if st.button("🗑️ Sil", key=f"prof_del_{prof_id}"):
                                    conn = get_db_connection()
                                    c = conn.cursor()
                                    c.execute("DELETE FROM is_plani_profil_isahleri WHERE profil_id=?", (prof_id,))
                                    c.execute("DELETE FROM is_plani_profili WHERE id=?", (prof_id,))
                                    conn.commit()
                                    conn.close()
                                    st.success(f"'{prof_name}' profili silindi.")
                                    _rerun()

            with subtab3:
                st.markdown("### Profili Odalara Uygula")
                conn = get_db_connection()
                df_profiler = _read_sql("SELECT id, profil_adi FROM is_plani_profili ORDER BY profil_adi", conn)
                conn.close()

                if df_profiler.empty:
                    st.warning("Uygulanacak profil yoktur. Önce profil oluşturun.")
                else:
                    prof_secim = st.selectbox("Profil Seçin", df_profiler['profil_adi'].tolist(), key="prof_sec")
                    prof_id = int(df_profiler[df_profiler['profil_adi'] == prof_secim]['id'].values[0])

                    st.markdown("**Profilin İşleri:**")
                    conn = get_db_connection()
                    
                    # NUCLEAR FIX: Ultra-safe table creation and query
                    try:
                        # Force table creation with raw connection
                        raw_conn = conn._conn if hasattr(conn, '_conn') else conn
                        raw_cur = raw_conn.cursor()
                        
                        # Create parent table first
                        raw_cur.execute("""
                            CREATE TABLE IF NOT EXISTS is_plani_profili (
                                id SERIAL PRIMARY KEY,
                                profil_adi TEXT NOT NULL UNIQUE,
                                aciklama TEXT,
                                olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                            )
                        """)
                        
                        # Create child table second
                        raw_cur.execute("""
                            CREATE TABLE IF NOT EXISTS is_plani_profil_isahleri (
                                id SERIAL PRIMARY KEY,
                                profil_id INTEGER NOT NULL,
                                is_adi TEXT NOT NULL,
                                referans_asama TEXT,
                                hatirlatma_gun_once INTEGER DEFAULT 0,
                                siralama INTEGER DEFAULT 0,
                                FOREIGN KEY (profil_id) REFERENCES is_plani_profili(id)
                            )
                        """)
                        
                        raw_conn.commit()
                        raw_cur.close()
                        
                        # Now try to query with fresh connection
                        fresh_conn = get_db_connection()
                        df_isahleri = _read_sql("SELECT * FROM is_plani_profil_isahleri WHERE profil_id=? ORDER BY siralama", fresh_conn, params=(prof_id,))
                        fresh_conn.close()
                        
                    except Exception as e:
                        st.error(f"İş Planı Profili hatası: {e}")
                        df_isahleri = pd.DataFrame()
                    
                    conn.close()

                    for _, iş_row in df_isahleri.iterrows():
                        ref_lbl = _asama_label(iş_row['referans_asama'])
                        st.caption(f"- {iş_row['is_adi']} ({ref_lbl} — {int(iş_row['hatirlatma_gun_once'])} gün)")

                    st.markdown("---")
                    st.markdown("**Uygulanacak Odalar:**")

                    odalar_all = _cached_odalar()
                    sec_odalar = st.multiselect("Odaları Seçin (boş bırakınca tümüne uygulanır)", odalar_all['oda_adi'].tolist(), key="prof_sec_odalar")

                    donem_plani = st.selectbox("Hangi dönem için uygulanacak?", ["Genel", "Son Dönem"], key="prof_donem")

                    if st.button("✅ Profili Uygula", type="primary", key="prof_apply"):
                        # Seçilen odalara profili uygula
                        odalar_to_apply = sec_odalar if sec_odalar else odalar_all['oda_adi'].tolist()
                        oda_ids = odalar_all[odalar_all['oda_adi'].isin(odalar_to_apply)]['id'].tolist()

                        conn = get_db_connection()
                        c = conn.cursor()
                        try:
                            for oda_id in oda_ids:
                                # Son dönem veya genel
                                donem_no = None
                                if donem_plani == "Son Dönem":
                                    df_son_donem = _read_sql("SELECT MAX(donem_no) as donem FROM oda_uretim_takip WHERE oda_id=?", conn, params=(oda_id,))
                                    if not df_son_donem.empty and df_son_donem.iloc[0, 0]:
                                        donem_no = int(df_son_donem.iloc[0, 0])

                                # Profil işlerini bu odaya ekle
                                for _, iş_row in df_isahleri.iterrows():
                                    c.execute(
                                        "INSERT INTO is_plani (oda_id, donem_no, is_adi, referans_asama, hatirlatma_gun_once) VALUES (?, ?, ?, ?, ?)",
                                        (oda_id, donem_no, iş_row['is_adi'], iş_row['referans_asama'], int(iş_row['hatirlatma_gun_once']))
                                    )
                            conn.commit()
                            st.success(f"✅ '{prof_secim}' profili {len(oda_ids)} odaya uygulandı.")
                            _rerun()
                        except Exception as e:
                            st.error(f"Hata: {e}")
                        finally:
                            conn.close()

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

# Gelir Hesaplama
elif menu == "💵 Gelir Hesaplama":
    st.title("💵 Gelir Hesaplama")
    st.markdown("### Tahmini Kar Hesaplama Aracı")
    st.info("Kompost miktarı ve verim oranlarına göre tahmini kar hesaplayın.")
    
    # Form alanları
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🌱 Üretim Parametreleri")
        kompost_kg = st.number_input("Kompost Miktarı (kg)", min_value=0.0, value=13000.0, step=100.0)
        verim_orani = st.number_input("Verim Oranı (%)", min_value=0.0, max_value=100.0, value=100.0, step=1.0)
        cikma_orani = st.number_input("Çıkma Oranı (%)", min_value=0.0, max_value=100.0, value=5.0, step=1.0)
        
        st.subheader("💰 Satış Fiyatları")
        cikma_satis_fiyati = st.number_input("Çıkma Satış Fiyatı (TL/kg)", min_value=0.0, value=15.0, step=1.0)
        birinci_kalite_fiyat = st.number_input("1. Kalite Mantar Satış Fiyatı (TL/kg)", min_value=0.0, value=45.0, step=1.0)
    
    with col2:
        st.subheader("📦 Toplama Yöntemi")
        toplama_yontemi = st.radio("Toplama Yöntemi", ["Tabağa Toplama", "Direk Toplama"])
        
        if toplama_yontemi == "Tabağa Toplama":
            kasa_maliyeti = st.number_input("1 Kasanın Maliyeti (TL)", min_value=0.0, value=12.0, step=1.0)
            st.info("💡 1 Kasa = 12 TL\nDökme: 12 TL / 9 kg = 1.33 TL/kg\nKasaya: 12 TL / 5 kg = 2.4 TL/kg")
        else:
            kasa_maliyeti = 0.0
    
    st.markdown("---")
    
    # Gider Kalemleri Seçimi
    st.subheader("💼 Gider Kalemleri")
    conn = get_db_connection()
    df_giderler = _read_sql("SELECT kalem_adi, birim_fiyat FROM gider_kalemleri WHERE aktif=1", conn)
    conn.close()
    
    if not df_giderler.empty:
        st.info("Hesaplamaya dahil edilecek gider kalemlerini seçin:")
        secili_giderler = st.multiselect(
            "Gider Kalemleri Seç",
            options=df_giderler['kalem_adi'].tolist(),
            default=[],
            key="gelir_hesaplama_giderler"
        )
    else:
        st.warning("Henüz gider kalemi tanımlanmamış.")
        secili_giderler = []
    
    st.markdown("---")
    
    # Hesaplama Butonu
    if st.button("💵 Tahmini Kar Hesapla", type="primary", use_container_width=True):
        # Hesaplamalar
        toplam_verim_kg = kompost_kg * (verim_orani / 100)
        cikma_kg = toplam_verim_kg * (cikma_orani / 100)
        birinci_kalite_kg = toplam_verim_kg - cikma_kg
        
        # Gelirler
        cikma_gelir = cikma_kg * cikma_satis_fiyati
        birinci_kalite_gelir = birinci_kalite_kg * birinci_kalite_fiyat
        toplam_gelir = cikma_gelir + birinci_kalite_gelir
        
        # Toplama Maliyeti (Kasa bazlı hesaplama)
        if toplama_yontemi == "Tabağa Toplama":
            # 1. Kalite için kasaya toplama: 12 TL / 5 kg = 2.4 TL/kg
            # Çıkma için dökme toplama: 12 TL / 9 kg = 1.33 TL/kg
            kasaya_toplama_maliyeti = kasa_maliyeti / 5.0  # 2.4 TL/kg
            dokum_toplama_maliyeti = kasa_maliyeti / 9.0  # 1.33 TL/kg
            toplama_maliyeti = (birinci_kalite_kg * kasaya_toplama_maliyeti) + (cikma_kg * dokum_toplama_maliyeti)
        else:
            toplama_maliyeti = 0.0
        
        # Seçili Giderler
        secili_gider_toplam = 0.0
        gider_detaylari = []
        if not df_giderler.empty and secili_giderler:
            for gider in secili_giderler:
                fiyat = df_giderler[df_giderler['kalem_adi'] == gider]['birim_fiyat'].iloc[0]
                secili_gider_toplam += fiyat
                gider_detaylari.append({'Gider': gider, 'Tutar': fiyat})
        
        # Toplam Gider
        toplam_gider = toplama_maliyeti + secili_gider_toplam
        
        # Tahmini Kar
        tahmini_kar = toplam_gelir - toplam_gider
        kar_orani = (tahmini_kar / toplam_gelir * 100) if toplam_gelir > 0 else 0.0
        
        # Sonuçları Göster
        st.markdown("### 📊 Hesaplama Sonuçları")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Toplam Verim (kg)", f"{toplam_verim_kg:.2f}")
            st.metric("1. Kalite (kg)", f"{birinci_kalite_kg:.2f}")
        
        with col2:
            st.metric("Çıkma (kg)", f"{cikma_kg:.2f}")
            st.metric("Toplam Gelir (TL)", f"{toplam_gelir:,.2f}")
        
        with col3:
            st.metric("Toplama Maliyeti (TL)", f"{toplama_maliyeti:,.2f}")
            st.metric("Gider Toplamı (TL)", f"{secili_gider_toplam:,.2f}")
        
        with col4:
            st.metric("Toplam Gider (TL)", f"{toplam_gider:,.2f}")
            kar_color = "normal" if tahmini_kar >= 0 else "inverse"
            st.metric("Tahmini Kar (TL)", f"{tahmini_kar:,.2f}", delta_color=kar_color)
        
        st.markdown("---")
        
        # Detaylı Breakdown
        st.subheader("📋 Detaylı Gelir-Gider Breakdown")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### 💰 Gelirler")
            gelir_data = {
                "Kalem": ["1. Kalite Mantar", "Çıkma Mantar", "TOPLAM GELİR"],
                "Miktar (kg)": [birinci_kalite_kg, cikma_kg, toplam_verim_kg],
                "Birim Fiyat (TL/kg)": [birinci_kalite_fiyat, cikma_satis_fiyati, "-"],
                "Toplam (TL)": [birinci_kalite_gelir, cikma_gelir, toplam_gelir]
            }
            st.dataframe(pd.DataFrame(gelir_data), use_container_width=True)
        
        with col2:
            st.markdown("### 💸 Giderler")
            gider_data = {
                "Kalem": ["Toplama Maliyeti"] + [g['Gider'] for g in gider_detaylari] + ["TOPLAM GİDER"],
                "Tutar (TL)": [toplama_maliyeti] + [g['Tutar'] for g in gider_detaylari] + [toplam_gider]
            }
            st.dataframe(pd.DataFrame(gider_data), use_container_width=True)
        
        st.markdown("---")
        
        # Kar Özeti
        st.subheader("🎯 Kar Özeti")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Tahmini Kar", f"{tahmini_kar:,.2f} TL")
        
        with col2:
            st.metric("Kar Oranı", f"{kar_orani:.2f}%")
        
        with col3:
            if tahmini_kar >= 0:
                st.success("✅ Karlı Üretim")
            else:
                st.error("❌ Zararlı Üretim")

# Gelir-Gider Şablonu
elif menu == "📊 Gelir-Gider Şablonu":
    st.title("📊 Gelir-Gider Şablonu")
    st.markdown("### Tüm Odaların Getiri Hesaplama")
    st.info("Her oda için farklı gider profili oluşturun ve toplam getiri hesaplayın.")
    
    # Şablon Yönetimi
    conn = get_db_connection()
    try:
        df_sablonlar = _read_sql("SELECT id, sablon_adi, verim_orani, cikma_orani, cikma_satis_fiyati, birinci_kalite_fiyat, kasa_maliyeti, toplama_yontemi, aciklama, olusturma_tarihi FROM gelir_gider_sablonlari ORDER BY olusturma_tarihi DESC", conn)
    except Exception:
        # Tablo yoksa oluştur
        try:
            conn.rollback()
        except Exception:
            pass
        c = conn.cursor()
        try:
            c.execute('''CREATE TABLE IF NOT EXISTS gelir_gider_sablonlari
                         (id SERIAL PRIMARY KEY,
                          sablon_adi TEXT NOT NULL UNIQUE,
                          verim_orani REAL NOT NULL DEFAULT 100.0,
                          cikma_orani REAL NOT NULL DEFAULT 5.0,
                          cikma_satis_fiyati REAL NOT NULL DEFAULT 15.0,
                          birinci_kalite_fiyat REAL NOT NULL DEFAULT 45.0,
                          kasa_maliyeti REAL NOT NULL DEFAULT 12.0,
                          toplama_yontemi TEXT NOT NULL DEFAULT 'Tabağa Toplama',
                          aciklama TEXT,
                          olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            c.execute('''CREATE TABLE IF NOT EXISTS sablon_oda_giderleri
                         (id SERIAL PRIMARY KEY,
                          sablon_id INTEGER NOT NULL,
                          oda_id INTEGER NOT NULL,
                          gider_adi TEXT NOT NULL,
                          gider_maliyeti REAL NOT NULL DEFAULT 0.0,
                          olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                          FOREIGN KEY (sablon_id) REFERENCES gelir_gider_sablonlari(id) ON DELETE CASCADE,
                          FOREIGN KEY (oda_id) REFERENCES odalar(id))''')
            conn.commit()
            df_sablonlar = _read_sql("SELECT id, sablon_adi, verim_orani, cikma_orani, cikma_satis_fiyati, birinci_kalite_fiyat, kasa_maliyeti, toplama_yontemi, aciklama, olusturma_tarihi FROM gelir_gider_sablonlari ORDER BY olusturma_tarihi DESC", conn)
        except Exception as e:
            st.error(f"Tablo oluşturma hatası: {e}")
            df_sablonlar = pd.DataFrame()
    conn.close()
    
    # Tabs oluştur
    tab1, tab2 = st.tabs(["📝 Şablon Oluştur/Düzenle", "📋 Kayıtlı Şablonlar"])
    
    with tab1:
        # Şablon adı ve açıklama
        col1, col2 = st.columns(2)
        with col1:
            sablon_adi = st.text_input("Şablon Adı", key="yeni_sablon_adi")
        with col2:
            aciklama = st.text_input("Açıklama (Opsiyonel)", key="yeni_sablon_aciklama")
        
        # Yüklenen şablon varsa göster
        if 'yuklenen_sablon' in st.session_state and st.session_state['yuklenen_sablon']:
            yuklenen = st.session_state['yuklenen_sablon']
            st.info(f"📂 Yüklenen Şablon: {yuklenen['sablon_adi']}")
            if st.button("🔄 Şablonu Temizle", key="sablon_temizle"):
                del st.session_state['yuklenen_sablon']
                del st.session_state['yuklenen_sablon_id']
                del st.session_state['sablon_yuklendi_mi']
                if 'yuklenen_oda_giderleri' in st.session_state:
                    del st.session_state['yuklenen_oda_giderleri']
                if 'oda_gider_state' in st.session_state:
                    del st.session_state['oda_gider_state']
                # Widget state'i temizle
                for key in ['sablon_verim', 'sablon_cikma', 'sablon_cikma_fiyat', 'sablon_birinci_fiyat', 'sablon_kasa', 'sablon_toplama']:
                    if key in st.session_state:
                        del st.session_state[key]
                st.rerun()
        
        # Odaları getir
        conn = get_db_connection()
        df_odalar = _read_sql("SELECT id, oda_adi, kapasite_kg FROM odalar WHERE durum='Aktif' ORDER BY oda_adi", conn)
        conn.close()
        
        if df_odalar.empty:
            st.warning("Aktif oda bulunmuyor.")
        else:
            # Yüklenen şablon varsa değerleri yükle
            if 'yuklenen_sablon' in st.session_state and st.session_state['yuklenen_sablon']:
                yuklenen = st.session_state['yuklenen_sablon']
                
                # Widget state'i temizle ve yeni değerleri yükle
                if 'sablon_verim' not in st.session_state or st.session_state.get('sablon_yuklendi_mi') != st.session_state['yuklenen_sablon_id']:
                    st.session_state['sablon_verim'] = yuklenen['verim_orani']
                    st.session_state['sablon_cikma'] = yuklenen['cikma_orani']
                    st.session_state['sablon_cikma_fiyat'] = yuklenen['cikma_satis_fiyati']
                    st.session_state['sablon_birinci_fiyat'] = yuklenen['birinci_kalite_fiyat']
                    st.session_state['sablon_kasa'] = yuklenen['kasa_maliyeti']
                    st.session_state['sablon_toplama'] = 0 if yuklenen['toplama_yontemi'] == "Tabağa Toplama" else 1
                    st.session_state['sablon_yuklendi_mi'] = st.session_state['yuklenen_sablon_id']
                
                varsayilan_verim = st.session_state['sablon_verim']
                varsayilan_cikma = st.session_state['sablon_cikma']
                varsayilan_cikma_fiyat = st.session_state['sablon_cikma_fiyat']
                varsayilan_birinci_fiyat = st.session_state['sablon_birinci_fiyat']
                varsayilan_kasa = st.session_state['sablon_kasa']
                varsayilan_toplama = "Tabağa Toplama" if st.session_state['sablon_toplama'] == 0 else "Direk Toplama"
            else:
                # Widget state'i temizle
                for key in ['sablon_verim', 'sablon_cikma', 'sablon_cikma_fiyat', 'sablon_birinci_fiyat', 'sablon_kasa', 'sablon_toplama', 'sablon_yuklendi_mi', 'oda_gider_state']:
                    if key in st.session_state:
                        del st.session_state[key]
                
                varsayilan_verim = 100.0
                varsayilan_cikma = 5.0
                varsayilan_cikma_fiyat = 15.0
                varsayilan_birinci_fiyat = 45.0
                varsayilan_kasa = 12.0
                varsayilan_toplama = "Tabağa Toplama"
            
            # Ortak parametreler
            st.subheader("🌱 Ortak Üretim Parametreleri")
            col1, col2, col3 = st.columns(3)
            with col1:
                verim_orani = st.number_input("Verim Oranı (%)", min_value=0.0, max_value=100.0, value=varsayilan_verim, step=1.0, key="sablon_verim")
                cikma_orani = st.number_input("Çıkma Oranı (%)", min_value=0.0, max_value=100.0, value=varsayilan_cikma, step=1.0, key="sablon_cikma")
            with col2:
                cikma_satis_fiyati = st.number_input("Çıkma Satış Fiyatı (TL/kg)", min_value=0.0, value=varsayilan_cikma_fiyat, step=1.0, key="sablon_cikma_fiyat")
                birinci_kalite_fiyat = st.number_input("1. Kalite Fiyatı (TL/kg)", min_value=0.0, value=varsayilan_birinci_fiyat, step=1.0, key="sablon_birinci_fiyat")
            with col3:
                kasa_maliyeti = st.number_input("1 Kasanın Maliyeti (TL)", min_value=0.0, value=varsayilan_kasa, step=1.0, key="sablon_kasa")
                toplama_yontemi = st.radio("Toplama Yöntemi", ["Tabağa Toplama", "Direk Toplama"], index=0 if varsayilan_toplama == "Tabağa Toplama" else 1, key="sablon_toplama")
            
            st.markdown("---")
            
            # Gider kalemlerini getir
            conn = get_db_connection()
            df_giderler = _read_sql("SELECT kalem_adi, birim_fiyat FROM gider_kalemleri WHERE aktif=1", conn)
            conn.close()
            
            # Odaya özel gider profilleri
            st.subheader("💼 Odaya Özel Gider Profilleri")
            st.info("Her oda için gider kalemlerini ve maliyetlerini düzenleyin.")
            
            # Yüklenen şablondan oda giderlerini al
            yuklenen_oda_giderleri = {}
            if 'yuklenen_oda_giderleri' in st.session_state:
                for gider in st.session_state['yuklenen_oda_giderleri']:
                    oda_id = gider['oda_id']
                    if oda_id not in yuklenen_oda_giderleri:
                        yuklenen_oda_giderleri[oda_id] = {}
                    yuklenen_oda_giderleri[oda_id][gider['gider_adi']] = gider['gider_maliyeti']
            
            # Session state'te oda giderlerini koru (sadece yeni şablon yüklendiğinde güncelle)
            if 'oda_gider_state' not in st.session_state or st.session_state.get('sablon_yuklendi_mi') != st.session_state.get('yuklenen_sablon_id'):
                st.session_state['oda_gider_state'] = yuklenen_oda_giderleri.copy() if yuklenen_oda_giderleri else {}
            
            oda_profilleri = {}
            for _, oda in df_odalar.iterrows():
                with st.expander(f"🏢 {oda['oda_adi']} (Kapasite: {oda['kapasite_kg'] or 0} kg)", expanded=False):
                    st.markdown(f"**Kompost Kapasitesi:** {oda['kapasite_kg'] or 0} kg")
                    
                    if not df_giderler.empty:
                        # Session state'ten varsayılan giderleri al
                        varsayilan_giderler = []
                        if oda['id'] in st.session_state['oda_gider_state']:
                            varsayilan_giderler = list(st.session_state['oda_gider_state'][oda['id']].keys())
                        
                        secili_giderler = st.multiselect(
                            f"Gider Kalemleri - {oda['oda_adi']}",
                            options=df_giderler['kalem_adi'].tolist(),
                            default=varsayilan_giderler,
                            key=f"gider_{oda['id']}"
                        )
                        
                        # Seçili giderler için maliyet düzenleme
                        gider_maliyetleri = {}
                        if secili_giderler:
                            st.markdown("**Gider Maliyetleri (Odaya Özel):**")
                            for gider in secili_giderler:
                                # Session state'ten maliyeti al, yoksa varsayılan hesapla
                                if oda['id'] in st.session_state['oda_gider_state'] and gider in st.session_state['oda_gider_state'][oda['id']]:
                                    varsayilan_fiyat = st.session_state['oda_gider_state'][oda['id']][gider]
                                else:
                                    varsayilan_fiyat = df_giderler[df_giderler['kalem_adi'] == gider]['birim_fiyat'].iloc[0]
                                    # Kompost kapasitesine göre varsayılan maliyet hesapla
                                    kapasite_orani = (oda['kapasite_kg'] or 0) / 13000.0  # Standart 13 ton kapasite
                                    varsayilan_fiyat = varsayilan_fiyat * kapasite_orani if kapasite_orani > 0 else varsayilan_fiyat
                                
                                gider_maliyeti = st.number_input(
                                    f"{gider} (TL)",
                                    min_value=0.0,
                                    value=varsayilan_fiyat,
                                    step=10.0,
                                    key=f"gider_maliyet_{oda['id']}_{gider}"
                                )
                                gider_maliyetleri[gider] = gider_maliyeti
                                
                                # Session state'i güncelle
                                if oda['id'] not in st.session_state['oda_gider_state']:
                                    st.session_state['oda_gider_state'][oda['id']] = {}
                                st.session_state['oda_gider_state'][oda['id']][gider] = gider_maliyeti
                        
                        oda_profilleri[oda['id']] = {
                            'oda_adi': oda['oda_adi'],
                            'kapasite_kg': oda['kapasite_kg'] or 0,
                            'secili_giderler': secili_giderler,
                            'gider_maliyetleri': gider_maliyetleri
                        }
            
            st.markdown("---")
            
            # Şablon Kaydetme Butonu
            st.subheader("💾 Şablonu Kaydet")
            st.info("Tüm parametreleri ve oda giderlerini düzenledikten sonra kaydet butonuna tıklayın.")
            
            # Şablon yüklendi mi kontrol et
            yuklenen_sablon_var = 'yuklenen_sablon' in st.session_state and st.session_state['yuklenen_sablon']
            
            if yuklenen_sablon_var:
                col1, col2 = st.columns(2)
                with col1:
                    kaydet_buton = st.button("🔄 Şablonu Güncelle", type="primary", use_container_width=True, key="sablon_guncelle")
                with col2:
                    yeni_olarak_kaydet = st.button("➕ Yeni Olarak Kaydet", use_container_width=True, key="sablon_yeni_kaydet")
            else:
                kaydet_buton = st.button("💾 Şablonu Kaydet", type="primary", use_container_width=True, key="sablon_kaydet")
                yeni_olarak_kaydet = False
        
        # Şablon kaydetme işlemi (oda_profilleri dolduktan sonra)
        if kaydet_buton and sablon_adi:
            conn = get_db_connection()
            try:
                c = conn.cursor()
                # Tabloların var olduğunu kontrol et, yoksa oluştur
                try:
                    c.execute("""CREATE TABLE IF NOT EXISTS gelir_gider_sablonlari
                                 (id SERIAL PRIMARY KEY,
                                  sablon_adi TEXT NOT NULL UNIQUE,
                                  verim_orani REAL NOT NULL DEFAULT 100.0,
                                  cikma_orani REAL NOT NULL DEFAULT 5.0,
                                  cikma_satis_fiyati REAL NOT NULL DEFAULT 15.0,
                                  birinci_kalite_fiyat REAL NOT NULL DEFAULT 45.0,
                                  kasa_maliyeti REAL NOT NULL DEFAULT 12.0,
                                  toplama_yontemi TEXT NOT NULL DEFAULT 'Tabağa Toplama',
                                  aciklama TEXT,
                                  olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
                    c.execute("""CREATE TABLE IF NOT EXISTS sablon_oda_giderleri
                                 (id SERIAL PRIMARY KEY,
                                  sablon_id INTEGER NOT NULL,
                                  oda_id INTEGER NOT NULL,
                                  gider_adi TEXT NOT NULL,
                                  gider_maliyeti REAL NOT NULL DEFAULT 0.0,
                                  olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                  FOREIGN KEY (sablon_id) REFERENCES gelir_gider_sablonlari(id) ON DELETE CASCADE,
                                  FOREIGN KEY (oda_id) REFERENCES odalar(id))""")
                    conn.commit()
                except Exception:
                    pass
                
                # Şablon güncelleme veya yeni kaydetme
                if yuklenen_sablon_var and not yeni_olarak_kaydet:
                    # Mevcut şablonu güncelle
                    sablon_id = st.session_state['yuklenen_sablon_id']
                    c.execute("""UPDATE gelir_gider_sablonlari 
                                 SET sablon_adi=?, verim_orani=?, cikma_orani=?, cikma_satis_fiyati=?, 
                                     birinci_kalite_fiyat=?, kasa_maliyeti=?, toplama_yontemi=?, aciklama=?
                                 WHERE id=?""",
                            (sablon_adi, verim_orani, cikma_orani, cikma_satis_fiyati, birinci_kalite_fiyat, kasa_maliyeti, toplama_yontemi, aciklama, sablon_id))
                    
                    # Eski oda giderlerini sil
                    c.execute("DELETE FROM sablon_oda_giderleri WHERE sablon_id = ?", (sablon_id,))
                    
                    # Yeni oda giderlerini ekle
                    for oda_id, profil in oda_profilleri.items():
                        for gider_adi, gider_maliyeti in profil['gider_maliyetleri'].items():
                            c.execute("""INSERT INTO sablon_oda_giderleri 
                                         (sablon_id, oda_id, gider_adi, gider_maliyeti)
                                         VALUES (?, ?, ?, ?)""",
                                    (sablon_id, oda_id, gider_adi, gider_maliyeti))
                    
                    conn.commit()
                    st.success(f"✅ '{sablon_adi}' şablonu başarıyla güncellendi!")
                    st.rerun()
                else:
                    # Yeni şablon olarak kaydet
                    if IS_CLOUD:
                        c.execute("""INSERT INTO gelir_gider_sablonlari 
                                     (sablon_adi, verim_orani, cikma_orani, cikma_satis_fiyati, birinci_kalite_fiyat, kasa_maliyeti, toplama_yontemi, aciklama)
                                     VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
                                (sablon_adi, verim_orani, cikma_orani, cikma_satis_fiyati, birinci_kalite_fiyat, kasa_maliyeti, toplama_yontemi, aciklama))
                        sablon_id = c.fetchone()[0]
                    else:
                        c.execute("""INSERT INTO gelir_gider_sablonlari 
                                     (sablon_adi, verim_orani, cikma_orani, cikma_satis_fiyati, birinci_kalite_fiyat, kasa_maliyeti, toplama_yontemi, aciklama)
                                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                                (sablon_adi, verim_orani, cikma_orani, cikma_satis_fiyati, birinci_kalite_fiyat, kasa_maliyeti, toplama_yontemi, aciklama))
                        sablon_id = c.lastrowid
                    
                    # Odaya özel giderleri kaydet
                    for oda_id, profil in oda_profilleri.items():
                        for gider_adi, gider_maliyeti in profil['gider_maliyetleri'].items():
                            c.execute("""INSERT INTO sablon_oda_giderleri 
                                         (sablon_id, oda_id, gider_adi, gider_maliyeti)
                                         VALUES (?, ?, ?, ?)""",
                                    (sablon_id, oda_id, gider_adi, gider_maliyeti))
                    
                    conn.commit()
                    st.success(f"✅ '{sablon_adi}' şablonu başarıyla kaydedildi!")
                    st.rerun()
            except Exception as e:
                st.error(f"Kaydetme hatası: {e}")
                try:
                    conn.rollback()
                except Exception:
                    pass
            finally:
                conn.close()
        elif yeni_olarak_kaydet and sablon_adi:
            st.warning("⚠️ Yeni şablon olarak kaydetmek için önce 'Şablonu Temizle' butonuna tıklayın.")
        elif kaydet_buton and not sablon_adi:
            st.warning("⚠️ Şablon adı giriniz!")
        
        st.markdown("---")
        
        # Hesaplama Butonu
        if st.button("📊 Tüm Odaların Getirisini Hesapla", type="primary", use_container_width=True):
            st.markdown("### 📊 Hesaplama Sonuçları")
            
            toplam_sonuclar = []
            
            for oda_id, profil in oda_profilleri.items():
                kompost_kg = profil['kapasite_kg']
                
                # Verim hesapla
                toplam_verim_kg = kompost_kg * (verim_orani / 100)
                cikma_kg = toplam_verim_kg * (cikma_orani / 100)
                birinci_kalite_kg = toplam_verim_kg - cikma_kg
                
                # Gelirler
                cikma_gelir = cikma_kg * cikma_satis_fiyati
                birinci_kalite_gelir = birinci_kalite_kg * birinci_kalite_fiyat
                toplam_gelir = cikma_gelir + birinci_kalite_gelir
                
                # Toplama Maliyeti
                if toplama_yontemi == "Tabağa Toplama":
                    kasaya_toplama_maliyeti = kasa_maliyeti / 5.0
                    dokum_toplama_maliyeti = kasa_maliyeti / 9.0
                    toplama_maliyeti = (birinci_kalite_kg * kasaya_toplama_maliyeti) + (cikma_kg * dokum_toplama_maliyeti)
                else:
                    toplama_maliyeti = 0.0
                
                # Oda Giderleri
                oda_gider_toplam = sum(profil['gider_maliyetleri'].values())
                
                # Toplam Gider
                toplam_gider = toplama_maliyeti + oda_gider_toplam
                
                # Kar
                oda_kar = toplam_gelir - toplam_gider
                
                toplam_sonuclar.append({
                    'oda_adi': profil['oda_adi'],
                    'kompost_kg': kompost_kg,
                    'toplam_verim_kg': toplam_verim_kg,
                    'cikma_kg': cikma_kg,
                    'birinci_kalite_kg': birinci_kalite_kg,
                    'toplam_gelir': toplam_gelir,
                    'toplama_maliyeti': toplama_maliyeti,
                    'oda_gider_toplam': oda_gider_toplam,
                    'toplam_gider': toplam_gider,
                    'oda_kar': oda_kar
                })
            
            # Sonuçları göster
            if toplam_sonuclar:
                df_sonuclar = pd.DataFrame(toplam_sonuclar)
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Toplam Kompost", f"{df_sonuclar['kompost_kg'].sum():,.0f} kg")
                    st.metric("Toplam Verim", f"{df_sonuclar['toplam_verim_kg'].sum():,.0f} kg")
                with col2:
                    st.metric("Toplam Gelir", f"{df_sonuclar['toplam_gelir'].sum():,.0f} TL")
                    st.metric("Toplam Gider", f"{df_sonuclar['toplam_gider'].sum():,.0f} TL")
                with col3:
                    toplam_kar = df_sonuclar['oda_kar'].sum()
                    kar_color = "normal" if toplam_kar >= 0 else "inverse"
                    st.metric("Toplam Kar", f"{toplam_kar:,.0f} TL", delta_color=kar_color)
                
                st.markdown("---")
                st.dataframe(df_sonuclar[['oda_adi', 'kompost_kg', 'toplam_verim_kg', 'toplam_gelir', 'toplam_gider', 'oda_kar']], use_container_width=True)
            else:
                st.warning("Hesaplama için oda profilleri gerekli.")
    
    with tab2:
        # Şablon Listesi
        if not df_sablonlar.empty:
            st.subheader("📋 Kayıtlı Şablonlar")
            
            # Gider kalemlerini getir
            conn_gider = get_db_connection()
            df_giderler = _read_sql("SELECT kalem_adi, birim_fiyat FROM gider_kalemleri WHERE aktif=1", conn_gider)
            conn_gider.close()
            
            # Odaları getir
            conn_odalar = get_db_connection()
            df_odalar = _read_sql("SELECT id, oda_adi, kapasite_kg FROM odalar WHERE durum='Aktif' ORDER BY oda_adi", conn_odalar)
            conn_odalar.close()
            
            for _, sablon in df_sablonlar.iterrows():
                with st.expander(f"📄 {sablon['sablon_adi']} ({sablon['olusturma_tarihi']})", expanded=False):
                    st.markdown("### Şablon Parametrelerini Düzenle")
                    st.info("Değerleri değiştirip 'Güncelle' butonuna tıklayın.")
                    
                    duzenleme_sablon_adi = st.text_input(
                        "Şablon Adı",
                        value=sablon['sablon_adi'],
                        key=f"duzenleme_sablon_adi_{sablon['id']}"
                    )
                    
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        duzenleme_verim = st.number_input(
                            "Verim Oranı (%)", 
                            min_value=0.0, max_value=100.0, 
                            value=float(sablon['verim_orani']), 
                            step=1.0, 
                            key=f"duzenle_verim_{sablon['id']}"
                        )
                        duzenleme_cikma = st.number_input(
                            "Çıkma Oranı (%)", 
                            min_value=0.0, max_value=100.0, 
                            value=float(sablon['cikma_orani']), 
                            step=1.0, 
                            key=f"duzenle_cikma_{sablon['id']}"
                        )
                    with col2:
                        duzenleme_cikma_fiyat = st.number_input(
                            "Çıkma Fiyatı (TL/kg)", 
                            min_value=0.0, 
                            value=float(sablon['cikma_satis_fiyati']), 
                            step=1.0, 
                            key=f"duzenle_cikma_fiyat_{sablon['id']}"
                        )
                        duzenleme_birinci_fiyat = st.number_input(
                            "1. Kalite Fiyatı (TL/kg)", 
                            min_value=0.0, 
                            value=float(sablon['birinci_kalite_fiyat']), 
                            step=1.0, 
                            key=f"duzenle_birinci_fiyat_{sablon['id']}"
                        )
                    with col3:
                        duzenleme_kasa = st.number_input(
                            "Kasa Maliyeti (TL)", 
                            min_value=0.0, 
                            value=float(sablon['kasa_maliyeti']), 
                            step=1.0, 
                            key=f"duzenleme_kasa_{sablon['id']}"
                        )
                        duzenleme_toplama = st.radio(
                            "Toplama Yöntemi", 
                            ["Tabağa Toplama", "Direk Toplama"], 
                            index=0 if sablon['toplama_yontemi'] == "Tabağa Toplama" else 1,
                            key=f"duzenleme_toplama_{sablon['id']}"
                        )
                    
                    duzenleme_aciklama = st.text_input(
                        "Açıklama", 
                        value=sablon.get('aciklama', ''),
                        key=f"duzenleme_aciklama_{sablon['id']}"
                    )
                    
                    st.markdown("---")
                    st.markdown("### 💼 Odaya Özel Gider Profilleri")
                    
                    # Şablon için oda giderlerini getir
                    conn_oda_gider = get_db_connection()
                    df_sablon_oda_giderleri = _read_sql("""SELECT oda_id, gider_adi, gider_maliyeti 
                                                          FROM sablon_oda_giderleri 
                                                          WHERE sablon_id = ?""", conn_oda_gider, params=(sablon['id'],))
                    conn_oda_gider.close()
                    
                    # Oda giderlerini dictionary'e çevir
                    sablon_oda_giderleri_dict = {}
                    if not df_sablon_oda_giderleri.empty:
                        for _, row in df_sablon_oda_giderleri.iterrows():
                            oda_id = row['oda_id']
                            if oda_id not in sablon_oda_giderleri_dict:
                                sablon_oda_giderleri_dict[oda_id] = {}
                            sablon_oda_giderleri_dict[oda_id][row['gider_adi']] = row['gider_maliyeti']
                    
                    # Her oda için gider profili oluştur
                    oda_profilleri_duzenleme = {}
                    if not df_odalar.empty and not df_giderler.empty:
                        for _, oda in df_odalar.iterrows():
                            with st.expander(f"🏢 {oda['oda_adi']} (Kapasite: {oda['kapasite_kg'] or 0} kg)", expanded=False):
                                # Varsayılan giderleri al
                                varsayilan_giderler = []
                                if oda['id'] in sablon_oda_giderleri_dict:
                                    varsayilan_giderler = list(sablon_oda_giderleri_dict[oda['id']].keys())
                                
                                secili_giderler_duzenleme = st.multiselect(
                                    f"Gider Kalemleri - {oda['oda_adi']}",
                                    options=df_giderler['kalem_adi'].tolist(),
                                    default=varsayilan_giderler,
                                    key=f"duzenleme_gider_{sablon['id']}_{oda['id']}"
                                )
                                
                                # Seçili giderler için maliyet düzenleme
                                gider_maliyetleri_duzenleme = {}
                                if secili_giderler_duzenleme:
                                    st.markdown("**Gider Maliyetleri (Odaya Özel):**")
                                    for gider in secili_giderler_duzenleme:
                                        # Varsayılan maliyeti al
                                        if oda['id'] in sablon_oda_giderleri_dict and gider in sablon_oda_giderleri_dict[oda['id']]:
                                            varsayilan_fiyat = sablon_oda_giderleri_dict[oda['id']][gider]
                                        else:
                                            varsayilan_fiyat = df_giderler[df_giderler['kalem_adi'] == gider]['birim_fiyat'].iloc[0]
                                            kapasite_orani = (oda['kapasite_kg'] or 0) / 13000.0
                                            varsayilan_fiyat = varsayilan_fiyat * kapasite_orani if kapasite_orani > 0 else varsayilan_fiyat
                                        
                                        gider_maliyeti_duzenleme = st.number_input(
                                            f"{gider} (TL)",
                                            min_value=0.0,
                                            value=varsayilan_fiyat,
                                            step=10.0,
                                            key=f"duzenleme_gider_maliyet_{sablon['id']}_{oda['id']}_{gider}"
                                        )
                                        gider_maliyetleri_duzenleme[gider] = gider_maliyeti_duzenleme
                                
                                oda_profilleri_duzenleme[oda['id']] = {
                                    'secili_giderler': secili_giderler_duzenleme,
                                    'gider_maliyetleri': gider_maliyetleri_duzenleme
                                }
                    
                    st.markdown("---")
                    
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        if st.button(f"💾 Güncelle - {sablon['sablon_adi']}", key=f"guncelle_{sablon['id']}", type="primary"):
                            conn = get_db_connection()
                            try:
                                c = conn.cursor()
                                # Ana şablon bilgilerini güncelle
                                c.execute("""UPDATE gelir_gider_sablonlari 
                                             SET sablon_adi=?, verim_orani=?, cikma_orani=?, cikma_satis_fiyati=?, 
                                                 birinci_kalite_fiyat=?, kasa_maliyeti=?, toplama_yontemi=?, aciklama=?
                                             WHERE id=?""",
                                    (duzenleme_sablon_adi, duzenleme_verim, duzenleme_cikma, duzenleme_cikma_fiyat, 
                                     duzenleme_birinci_fiyat, duzenleme_kasa, duzenleme_toplama, duzenleme_aciklama, sablon['id']))
                                
                                # Eski oda giderlerini sil
                                c.execute("DELETE FROM sablon_oda_giderleri WHERE sablon_id = ?", (sablon['id'],))
                                
                                # Yeni oda giderlerini ekle
                                for oda_id, profil in oda_profilleri_duzenleme.items():
                                    for gider_adi, gider_maliyeti in profil['gider_maliyetleri'].items():
                                        c.execute("""INSERT INTO sablon_oda_giderleri 
                                                     (sablon_id, oda_id, gider_adi, gider_maliyeti)
                                                     VALUES (?, ?, ?, ?)""",
                                                (sablon['id'], oda_id, gider_adi, gider_maliyeti))
                                
                                conn.commit()
                                st.success(f"✅ '{sablon['sablon_adi']}' şablonu güncellendi!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Güncelleme hatası: {e}")
                                try:
                                    conn.rollback()
                                except Exception:
                                    pass
                            finally:
                                conn.close()
                    with col2:
                        if st.button(f"📂 Yükle - {sablon['sablon_adi']}", key=f"yukle_{sablon['id']}"):
                            st.session_state['yuklenen_sablon_id'] = sablon['id']
                            st.session_state['yuklenen_sablon'] = sablon.to_dict()
                            
                            # Odaya özel giderleri de yükle
                            conn_gider = get_db_connection()
                            df_oda_giderleri = _read_sql("""SELECT oda_id, gider_adi, gider_maliyeti 
                                                        FROM sablon_oda_giderleri 
                                                        WHERE sablon_id = ?""", conn_gider, params=(sablon['id'],))
                            conn_gider.close()
                            
                            if not df_oda_giderleri.empty:
                                st.session_state['yuklenen_oda_giderleri'] = df_oda_giderleri.to_dict('records')
                            
                            st.success(f"✅ {sablon['sablon_adi']} şablonu yüklendi! Şablon düzenleme sekmesine geçin.")
                            st.rerun()
                    with col3:
                        if st.button(f"📊 Hesapla - {sablon['sablon_adi']}", key=f"hesapla_{sablon['id']}", type="secondary"):
                            if 'sablon_hesapla' not in st.session_state:
                                st.session_state['sablon_hesapla'] = {}
                            st.session_state['sablon_hesapla'][str(sablon['id'])] = True
                    with col4:
                        if st.button(f"🗑️ Sil - {sablon['sablon_adi']}", key=f"sil_{sablon['id']}"):
                            conn = get_db_connection()
                            try:
                                c = conn.cursor()
                                c.execute("DELETE FROM sablon_oda_giderleri WHERE sablon_id = ?", (sablon['id'],))
                                c.execute("DELETE FROM gelir_gider_sablonlari WHERE id = ?", (sablon['id'],))
                                conn.commit()
                                st.success(f"✅ {sablon['sablon_adi']} şablonu silindi!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Silme hatası: {e}")
                            finally:
                                conn.close()
                    
                    # Hesaplama sonuçları
                    if st.session_state.get('sablon_hesapla', {}).get(str(sablon['id'])):
                        st.markdown("---")
                        st.markdown("### 📊 Gelir-Gider Hesaplama Sonuçları")
                        
                        # Şablon parametrelerini kullan
                        verim_orani_hesap = duzenleme_verim
                        cikma_orani_hesap = duzenleme_cikma
                        cikma_satis_fiyati_hesap = duzenleme_cikma_fiyat
                        birinci_kalite_fiyati_hesap = duzenleme_birinci_fiyat
                        kasa_maliyeti_hesap = duzenleme_kasa
                        toplama_yontemi_hesap = duzenleme_toplama
                        
                        toplam_sonuclar = []
                        toplam_gider_detaylari = {}
                        
                        for _, oda in df_odalar.iterrows():
                            kompost_kg = oda['kapasite_kg'] or 0
                            
                            # Verim hesapla
                            toplam_verim_kg = kompost_kg * (verim_orani_hesap / 100)
                            cikma_kg = toplam_verim_kg * (cikma_orani_hesap / 100)
                            birinci_kalite_kg = toplam_verim_kg - cikma_kg
                            
                            # Gelirler
                            cikma_gelir = cikma_kg * cikma_satis_fiyati_hesap
                            birinci_kalite_gelir = birinci_kalite_kg * birinci_kalite_fiyati_hesap
                            toplam_gelir = cikma_gelir + birinci_kalite_gelir
                            
                            # Toplama Maliyeti
                            if toplama_yontemi_hesap == "Tabağa Toplama":
                                kasaya_toplama_maliyeti = kasa_maliyeti_hesap / 5.0
                                dokum_toplama_maliyeti = kasa_maliyeti_hesap / 9.0
                                toplama_maliyeti = (birinci_kalite_kg * kasaya_toplama_maliyeti) + (cikma_kg * dokum_toplama_maliyeti)
                            else:
                                toplama_maliyeti = 0.0
                            
                            # Oda Giderleri
                            oda_gider_toplam = 0.0
                            oda_id = oda['id']
                            if oda_id in sablon_oda_giderleri_dict:
                                for gider_adi, gider_maliyeti in sablon_oda_giderleri_dict[oda_id].items():
                                    oda_gider_toplam += gider_maliyeti
                                    if gider_adi not in toplam_gider_detaylari:
                                        toplam_gider_detaylari[gider_adi] = 0.0
                                    toplam_gider_detaylari[gider_adi] += gider_maliyeti
                            
                            # Toplam Gider
                            toplam_gider = toplama_maliyeti + oda_gider_toplam
                            
                            # Kar
                            oda_kar = toplam_gelir - toplam_gider
                            
                            toplam_sonuclar.append({
                                'oda_adi': oda['oda_adi'],
                                'kompost_kg': kompost_kg,
                                'toplam_verim_kg': toplam_verim_kg,
                                'cikma_kg': cikma_kg,
                                'birinci_kalite_kg': birinci_kalite_kg,
                                'toplam_gelir': toplam_gelir,
                                'toplama_maliyeti': toplama_maliyeti,
                                'oda_gider_toplam': oda_gider_toplam,
                                'toplam_gider': toplam_gider,
                                'oda_kar': oda_kar
                            })
                        
                        # Toplamları hesapla
                        if toplam_sonuclar:
                            df_sonuclar = pd.DataFrame(toplam_sonuclar)
                            
                            toplam_kompost = df_sonuclar['kompost_kg'].sum()
                            toplam_verim = df_sonuclar['toplam_verim_kg'].sum()
                            toplam_cikma = df_sonuclar['cikma_kg'].sum()
                            toplam_birinci = df_sonuclar['birinci_kalite_kg'].sum()
                            toplam_gelir = df_sonuclar['toplam_gelir'].sum()
                            toplam_toplama = df_sonuclar['toplama_maliyeti'].sum()
                            toplam_oda_gider = df_sonuclar['oda_gider_toplam'].sum()
                            toplam_gider = df_sonuclar['toplam_gider'].sum()
                            toplam_kar = df_sonuclar['oda_kar'].sum()
                            
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                st.metric("Toplam Kompost", f"{toplam_kompost:,.0f} kg")
                                st.metric("Toplam Verim", f"{toplam_verim:,.0f} kg")
                            with col2:
                                st.metric("Toplam Gelir", f"{toplam_gelir:,.0f} TL")
                                st.metric("Toplam Gider", f"{toplam_gider:,.0f} TL")
                            with col3:
                                kar_color = "normal" if toplam_kar >= 0 else "inverse"
                                st.metric("Toplam Kar", f"{toplam_kar:,.0f} TL", delta_color=kar_color)
                                kar_orani = (toplam_kar / toplam_gelir * 100) if toplam_gelir > 0 else 0.0
                                st.metric("Kar Oranı", f"{kar_orani:.2f}%")
                            
                            st.markdown("---")
                            
                            # Pasta Grafiği
                            col1, col2 = st.columns(2)
                            with col1:
                                st.markdown("### 📊 Gider Dağılımı (Pasta Grafiği)")
                                
                                gider_data = []
                                gider_labels = []
                                
                                # Toplama maliyeti
                                if toplam_toplama > 0:
                                    gider_data.append(toplam_toplama)
                                    gider_labels.append("Toplama Maliyeti")
                                
                                # Oda giderleri
                                for gider_adi, gider_tutar in toplam_gider_detaylari.items():
                                    if gider_tutar > 0:
                                        gider_data.append(gider_tutar)
                                        gider_labels.append(gider_adi)
                                
                                if gider_data:
                                    fig_pie = px.pie(
                                        values=gider_data,
                                        names=gider_labels,
                                        title="Gider Dağılımı",
                                        hole=0.3
                                    )
                                    fig_pie.update_traces(textposition='inside', textinfo='percent+label')
                                    st.plotly_chart(fig_pie, use_container_width=True)
                                else:
                                    st.info("Gider verisi bulunmuyor.")
                            
                            with col2:
                                st.markdown("### 📊 Gelir-Gider Karşılaştırması")
                                
                                gelir_gider_data = {
                                    'Kalem': ['Gelir', 'Gider', 'Kar'],
                                    'Tutar (TL)': [toplam_gelir, toplam_gider, toplam_kar]
                                }
                                df_gg = pd.DataFrame(gelir_gider_data)
                                
                                fig_bar = px.bar(
                                    df_gg,
                                    x='Kalem',
                                    y='Tutar (TL)',
                                    title="Gelir-Gider Karşılaştırması",
                                    color='Kalem',
                                    color_discrete_map={'Gelir': '#00CC96', 'Gider': '#EF553B', 'Kar': '#636EFA'}
                                )
                                st.plotly_chart(fig_bar, use_container_width=True)
                            
                            st.markdown("---")
                            st.markdown("### 📋 Detaylı Oda Sonuçları")
                            st.dataframe(df_sonuclar[['oda_adi', 'kompost_kg', 'toplam_verim_kg', 'toplam_gelir', 'toplam_gider', 'oda_kar']], use_container_width=True)
                            
                            if st.button(f"❌ Hesaplamayı Kapat - {sablon['sablon_adi']}", key=f"kapat_hesapla_{sablon['id']}"):
                                if 'sablon_hesapla' in st.session_state and str(sablon['id']) in st.session_state['sablon_hesapla']:
                                    del st.session_state['sablon_hesapla'][str(sablon['id'])]
                                st.rerun()
        else:
            st.markdown("---")
            st.subheader("📋 Kayıtlı Şablonlar")
            st.info("Henüz kayıtlı şablon bulunmuyor. İlk şablonunuzu oluşturmak için 'Şablon Oluştur/Düzenle' sekmesine geçin.")

# Borç Yönetimi
elif menu == "💳 Borç Yönetimi":
    st.title("💳 Borç Yönetimi - Sanal CFO Sistemi")
    st.markdown("""
    ### 🎯 Rol ve Amaç
    
    Ticari mantar üretimi (Agaricus bisporus, Pleurotus ostreatus vb.), çok odalı tesis yatırımları ve tarımsal finansman konularında uzmanlaşmış üst düzey bir Sanal CFO olarak:
    
    - Tesisin nakit akışını optimize etmek
    - Karlılığı koruyarak borç yükünü **"Borç Çığı (Avalanche)"** yöntemiyle en düşük maliyetle eritmek
    - Üretim döngüsünün (kuluçka-hasat) kesintiye uğramamasını sağlamak
    """)
    
    st.markdown("---")
    
    # Borç Yönetimi Sekmeleri
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Nakit Akışı Analizi", 
        "💰 Kısa Vadeli Borçlar", 
        "🏗️ Uzun Vadeli Borçlar", 
        "🏦 Çoklu Banka Yönetimi", 
        "⚠️ Risk Senaryoları"
    ])
    
    with tab1:
        st.markdown("### 📊 Nakit Akışı Analizi")
        st.info("Üretim Döngüsü ve Nakit Dönüşüm Süresi (CCC) Analizi")
        
        st.markdown("""
        **Nakit Dönüşüm Süresi (CCC) Hesaplama:**
        - Kompost/misel alımı için yapılan peşin ödemeler
        - Odaların kuluçka süresi
        - 1. ve 2. flaş (hasat) evreleri
        - Toptancı/marketlerden paranın tahsil edilmesi arasındaki ölü zamanı (nakit boşluğu)
        """)
        
        st.markdown("---")
        
        # Gerçek Üretim Verilerini Çek
        st.subheader("📈 Gerçek Üretim ve Satış Verileri")
        conn = get_db_connection()
        
        try:
            # Günlük hasat verileri
            df_hasat = _read_sql("SELECT * FROM gunluk_hasat ORDER BY tarih DESC LIMIT 30", conn)
            
            # Satış verileri
            df_satis = _read_sql("SELECT * FROM satislar ORDER BY tarih DESC LIMIT 30", conn)
            
            # Odalar
            df_odalar = _read_sql("SELECT * FROM odalar WHERE durum='Aktif'", conn)
            
            conn.close()
            
            if not df_hasat.empty:
                st.markdown("**Son 30 Gün Hasat Verileri**")
                st.dataframe(df_hasat[['tarih', 'oda_id', 'hasat_kg', 'kalite', 'aciklama']], use_container_width=True)
                
                # Toplam hasat
                toplam_hasat = df_hasat['hasat_kg'].sum()
                st.metric("Toplam Hasat (30 Gün)", f"{toplam_hasat:,.0f} kg")
            else:
                st.info("Hasat verisi bulunmuyor.")
            
            st.markdown("---")
            
            if not df_satis.empty:
                st.markdown("**Son 30 Gün Satış Verileri**")
                st.dataframe(df_satis[['tarih', 'miktar_kg', 'birim_fiyat', 'alan_kisi', 'aciklama']], use_container_width=True)
                
                # Toplam satış
                df_satis['toplam_tutar'] = df_satis['miktar_kg'] * df_satis['birim_fiyat']
                toplam_satis = df_satis['toplam_tutar'].sum()
                st.metric("Toplam Satış (30 Gün)", f"{toplam_satis:,.0f} TL")
            else:
                st.info("Satış verisi bulunmuyor.")
            
            st.markdown("---")
            
            if not df_odalar.empty:
                st.markdown("**Aktif Odalar**")
                st.dataframe(df_odalar[['oda_adi', 'alan_m2', 'kapasite_kg', 'durum']], use_container_width=True)
            else:
                st.info("Oda verisi bulunmuyor.")
        
        except Exception as e:
            st.error(f"Veri çekme hatası: {e}")
            conn.close()
        
        st.markdown("---")
        
        # Nakit Akışı Giriş Formu
        st.subheader("💰 Beklenen Nakit Girişleri (Projeksiyon)")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**1. Flaş Hasat Projeksiyonu**")
            birinci_flas_ton = st.number_input("1. Flaş Tahmini Tonaj (ton)", min_value=0.0, step=0.1, key="birinci_flas_ton")
            birinci_flas_fiyat = st.number_input("1. Flaş Satış Fiyatı (TL/kg)", min_value=0.0, step=1.0, key="birinci_flas_fiyat")
            birinci_flas_vade = st.number_input("1. Flaş Tahsilat Vadesi (gün)", min_value=0, step=1, value=30, key="birinci_flas_vade")
        
        with col2:
            st.markdown("**2. Flaş Hasat Projeksiyonu**")
            ikinci_flas_ton = st.number_input("2. Flaş Tahmini Tonaj (ton)", min_value=0.0, step=0.1, key="ikinci_flas_ton")
            ikinci_flas_fiyat = st.number_input("2. Flaş Satış Fiyatı (TL/kg)", min_value=0.0, step=1.0, key="ikinci_flas_fiyat")
            ikinci_flas_vade = st.number_input("2. Flaş Tahsilat Vadesi (gün)", min_value=0, step=1, value=30, key="ikinci_flas_vade")
        
        st.markdown("---")
        
        st.subheader("🏭 Üretim Durumu")
        
        col1, col2 = st.columns(2)
        
        with col1:
            kuluçka_suresi = st.number_input("Kuluçka Süresi (gün)", min_value=0, step=1, value=21, key="kuluçka_suresi")
            topraklama_suresi = st.number_input("Topraklama Süresi (gün)", min_value=0, step=1, value=7, key="topraklama_suresi")
        
        with col2:
            birinci_flas_suresi = st.number_input("1. Flaş Süresi (gün)", min_value=0, step=1, value=14, key="birinci_flas_suresi")
            ikinci_flas_suresi = st.number_input("2. Flaş Süresi (gün)", min_value=0, step=1, value=14, key="ikinci_flas_suresi")
        
        # Nakit Akışı Hesaplama
        if st.button("📊 Nakit Akışını Hesapla", type="primary"):
            birinci_flas_gelir = birinci_flas_ton * 1000 * birinci_flas_fiyat
            ikinci_flas_gelir = ikinci_flas_ton * 1000 * ikinci_flas_fiyat
            toplam_beklenen_gelir = birinci_flas_gelir + ikinci_flas_gelir
            
            toplam_uretim_suresi = kuluçka_suresi + topraklama_suresi + birinci_flas_suresi + ikinci_flas_suresi
            
            st.markdown("---")
            st.subheader("💵 Nakit Akışı Projeksiyonu")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("1. Flaş Geliri", f"{birinci_flas_gelir:,.0f} TL")
                st.metric("2. Flaş Geliri", f"{ikinci_flas_gelir:,.0f} TL")
            with col2:
                st.metric("Toplam Beklenen Gelir", f"{toplam_beklenen_gelir:,.0f} TL")
                st.metric("Toplam Üretim Süresi", f"{toplam_uretim_suresi} gün")
            with col3:
                st.metric("1. Flaş Tahsilat", f"{birinci_flas_vade} gün sonra")
                st.metric("2. Flaş Tahsilat", f"{ikinci_flas_vade} gün sonra")
        
        if st.button("💾 Nakit Akışını Kaydet", type="secondary"):
            conn = get_db_connection()
            try:
                c = conn.cursor()
                # Tabloyu oluştur (hem SQLite hem PostgreSQL için uyumlu)
                c.execute('''CREATE TABLE IF NOT EXISTS nakit_akisi
                             (id INTEGER PRIMARY KEY AUTOINCREMENT,
                              birinci_flas_ton REAL,
                              birinci_flas_fiyat REAL,
                              birinci_flas_vade INTEGER,
                              ikinci_flas_ton REAL,
                              ikinci_flas_fiyat REAL,
                              ikinci_flas_vade INTEGER,
                              kulucka_suresi INTEGER,
                              topraklama_suresi INTEGER,
                              birinci_flas_suresi INTEGER,
                              ikinci_flas_suresi INTEGER,
                              olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                conn.commit()
                
                c.execute("""INSERT INTO nakit_akisi 
                             (birinci_flas_ton, birinci_flas_fiyat, birinci_flas_vade,
                              ikinci_flas_ton, ikinci_flas_fiyat, ikinci_flas_vade,
                              kulucka_suresi, topraklama_suresi, birinci_flas_suresi, ikinci_flas_suresi)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (birinci_flas_ton, birinci_flas_fiyat, birinci_flas_vade,
                     ikinci_flas_ton, ikinci_flas_fiyat, ikinci_flas_vade,
                     kuluçka_suresi, topraklama_suresi, birinci_flas_suresi, ikinci_flas_suresi))
                conn.commit()
                st.success("✅ Nakit akış verileri kaydedildi!")
                st.rerun()
            except Exception as e:
                st.error(f"Kaydetme hatası: {e}")
                try:
                    conn.rollback()
                except Exception:
                    pass
            finally:
                conn.close()
        
        # Kayıtlı Nakit Akışı Verilerini Göster
        try:
            conn = get_db_connection()
            df_nakit = _read_sql("SELECT * FROM nakit_akisi ORDER BY olusturma_tarihi DESC LIMIT 1", conn)
            conn.close()
            
            if not df_nakit.empty:
                st.markdown("---")
                st.subheader("📋 Kayıtlı Nakit Akışı Verileri")
                st.dataframe(df_nakit.drop(columns=['id', 'olusturma_tarihi']), use_container_width=True)
        except Exception as e:
            st.info("Henüz kayıtlı nakit akışı verisi bulunmuyor.")
        
    with tab2:
        st.markdown("### 💰 Kısa Vadeli Borçlar")
        st.info("Kompost/misel ödemeleri, aylık elektrik/iklimlendirme faturası, işçilik")
        
        st.markdown("""
        **Girdi Formatı:**
        - Kompost/misel ödemeleri - Tutar, Faiz Oranı/Vade, Ödeme Tarihi
        - Aylık elektrik/iklimlendirme faturası - Tutar, Faiz Oranı/Vade, Ödeme Tarihi
        - İşçilik - Tutar, Faiz Oranı/Vade, Ödeme Tarihi
        """)
        
        st.markdown("---")
        
        # Kısa Vadeli Borç Ekleme Formu
        st.subheader("➕ Yeni Kısa Vadeli Borç Ekle")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            kisalik_borc_adi = st.text_input("Borç Adı", key="kisalik_borc_adi")
            kisalik_tutar = st.number_input("Tutar (TL)", min_value=0.0, step=100.0, key="kisalik_tutar")
        
        with col2:
            kisalik_faiz = st.number_input("Faiz Oranı (%)", min_value=0.0, max_value=100.0, step=0.1, key="kisalik_faiz")
            kisalik_vade = st.number_input("Vade (gün)", min_value=0, step=1, key="kisalik_vade")
        
        with col3:
            kisalik_odeme_tarihi = st.date_input("Ödeme Tarihi", key="kisalik_odeme_tarihi")
            kisalik_kategori = st.selectbox("Kategori", ["Kompost/Misel", "Elektrik/İklimlendirme", "İşçilik", "Diğer"], key="kisalik_kategori")
        
        if st.button("➕ Kısa Vadeli Borç Ekle", type="primary"):
            if kisalik_borc_adi and kisalik_tutar > 0:
                conn = get_db_connection()
                try:
                    # Tabloyu kontrol et ve yoksa oluştur
                    c = conn.cursor()
                    c.execute('''CREATE TABLE IF NOT EXISTS kisalik_borclar
                                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                                  borc_adi TEXT NOT NULL,
                                  tutar REAL NOT NULL,
                                  faiz_orani REAL NOT NULL,
                                  vade_gun INTEGER NOT NULL,
                                  odeme_tarihi DATE NOT NULL,
                                  kategori TEXT NOT NULL,
                                  olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                    
                    c.execute("""INSERT INTO kisalik_borclar 
                                 (borc_adi, tutar, faiz_orani, vade_gun, odeme_tarihi, kategori)
                                 VALUES (?, ?, ?, ?, ?, ?)""",
                        (kisalik_borc_adi, kisalik_tutar, kisalik_faiz, kisalik_vade, kisalik_odeme_tarihi, kisalik_kategori))
                    conn.commit()
                    st.success("✅ Kısa vadeli borç eklendi!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Kaydetme hatası: {e}")
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                finally:
                    conn.close()
            else:
                st.warning("⚠️ Borç adı ve tutar giriniz!")
        
        # Kayıtlı Kısa Vadeli Borçları Göster
        try:
            conn = get_db_connection()
            df_kisalik = _read_sql("SELECT * FROM kisalik_borclar ORDER BY odeme_tarihi ASC", conn)
            conn.close()
            
            st.markdown("---")
            st.subheader("📋 Kayıtlı Kısa Vadeli Borçlar")
            if not df_kisalik.empty:
                st.dataframe(df_kisalik.drop(columns=['id', 'olusturma_tarihi']), use_container_width=True)
                
                # Borç Avalanche Hesaplayıcı
                st.markdown("---")
                st.subheader("🎯 Borç Avalanche Hesaplayıcı")
                st.info("Borç Avalanche yöntemi: En yüksek faiz oranlı borçtan başlayarak ödeme yaparak toplam faiz maliyetini minimize eder")
                
                if not df_kisalik.empty:
                    # Faiz oranına göre sırala (en yüksek faiz önce)
                    df_kisalik_sorted = df_kisalik.sort_values(by='faiz_orani', ascending=False)
                    
                    toplam_borc = df_kisalik['tutar'].sum()
                    ortalama_faiz = (df_kisalik['tutar'] * df_kisalik['faiz_orani'] / 100).sum() / toplam_borc * 100 if toplam_borc > 0 else 0
                    
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Toplam Borç", f"{toplam_borc:,.0f} TL")
                        st.metric("Ortalama Faiz", f"{ortalama_faiz:.2f}%")
                    with col2:
                        en_yuksek_faiz = df_kisalik_sorted.iloc[0]
                        st.metric("En Yüksek Faiz", f"{en_yuksek_faiz['faiz_orani']:.1f}%")
                        st.metric("Öncelikli Borç", en_yuksek_faiz['borc_adi'])
                    with col3:
                        aylik_faiz = toplam_borc * ortalama_faiz / 100 / 12
                        st.metric("Aylık Faiz Maliyeti", f"{aylik_faiz:,.0f} TL")
                        st.metric("Yıllık Faiz Maliyeti", f"{aylik_faiz * 12:,.0f} TL")
                    
                    st.markdown("---")
                    st.markdown("**Ödeme Öncelik Sırası (Avalanche Yöntemi):**")
                    for idx, row in df_kisalik_sorted.iterrows():
                        aylik_faiz_borc = row['tutar'] * row['faiz_orani'] / 100 / 12
                        st.markdown(f"**{row['faiz_orani']:.1f}%** - {row['borc_adi']}: {row['tutar']:,.0f} TL (Aylık faiz: {aylik_faiz_borc:,.0f} TL)")
            else:
                st.info("Henüz kayıtlı borç bulunmuyor.")
        except Exception as e:
            st.info("Henüz kayıtlı borç bulunmuyor.")
        
    with tab3:
        st.markdown("### 🏗️ Uzun Vadeli Borçlar")
        st.info("Tesis, izolasyon, paketleme makinesi ve iklimlendirme yatırımı kredileri")
        
        st.markdown("""
        **Girdi Formatı:**
        - Tesis, izolasyon, paketleme makinesi ve iklimlendirme yatırımı kredileri - Tutar, Faiz Oranı, Taksit Miktarı
        """)
        
        st.markdown("---")
        
        # Uzun Vadeli Borç Ekleme Formu
        st.subheader("➕ Yeni Uzun Vadeli Borç Ekle")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            uzunv_borc_adi = st.text_input("Borç Adı", key="uzunv_borc_adi")
            uzunv_tutar = st.number_input("Tutar (TL)", min_value=0.0, step=1000.0, key="uzunv_tutar")
        
        with col2:
            uzunv_faiz = st.number_input("Faiz Oranı (%)", min_value=0.0, max_value=100.0, step=0.1, key="uzunv_faiz")
            uzunv_taksit = st.number_input("Aylık Taksit (TL)", min_value=0.0, step=100.0, key="uzunv_taksit")
        
        with col3:
            uzunv_kalan_ay = st.number_input("Kalan Ay", min_value=0, step=1, key="uzunv_kalan_ay")
            uzunv_kategori = st.selectbox("Kategori", ["Tesis Yatırımı", "İzolasyon", "Paketleme Makinesi", "İklimlendirme", "Diğer"], key="uzunv_kategori")
        
        if st.button("➕ Uzun Vadeli Borç Ekle", type="primary"):
            if uzunv_borc_adi and uzunv_tutar > 0:
                conn = get_db_connection()
                try:
                    # Tabloyu kontrol et ve yoksa oluştur
                    c = conn.cursor()
                    c.execute('''CREATE TABLE IF NOT EXISTS uzunv_borclar
                                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                                  borc_adi TEXT NOT NULL,
                                  tutar REAL NOT NULL,
                                  faiz_orani REAL NOT NULL,
                                  aylik_taksit REAL NOT NULL,
                                  kalan_ay INTEGER NOT NULL,
                                  kategori TEXT NOT NULL,
                                  olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                    
                    c.execute("""INSERT INTO uzunv_borclar 
                                 (borc_adi, tutar, faiz_orani, aylik_taksit, kalan_ay, kategori)
                                 VALUES (?, ?, ?, ?, ?, ?)""",
                        (uzunv_borc_adi, uzunv_tutar, uzunv_faiz, uzunv_taksit, uzunv_kalan_ay, uzunv_kategori))
                    conn.commit()
                    st.success("✅ Uzun vadeli borç eklendi!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Kaydetme hatası: {e}")
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                finally:
                    conn.close()
            else:
                st.warning("⚠️ Borç adı ve tutar giriniz!")
        
        # Kayıtlı Uzun Vadeli Borçları Göster
        try:
            conn = get_db_connection()
            df_uzunv = _read_sql("SELECT * FROM uzunv_borclar ORDER BY olusturma_tarihi DESC", conn)
            conn.close()
            
            st.markdown("---")
            st.subheader("📋 Kayıtlı Uzun Vadeli Borçlar")
            if not df_uzunv.empty:
                st.dataframe(df_uzunv.drop(columns=['id', 'olusturma_tarihi']), use_container_width=True)
                
                # Borç Avalanche Hesaplayıcı
                st.markdown("---")
                st.subheader("🎯 Borç Avalanche Hesaplayıcı")
                st.info("Borç Avalanche yöntemi: En yüksek faiz oranlı borçtan başlayarak ödeme yaparak toplam faiz maliyetini minimize eder")
                
                # Faiz oranına göre sırala (en yüksek faiz önce)
                df_uzunv_sorted = df_uzunv.sort_values(by='faiz_orani', ascending=False)
                
                toplam_borc = df_uzunv['tutar'].sum()
                toplam_kalan_ay = df_uzunv['kalan_ay'].sum()
                toplam_aylik_taksit = df_uzunv['aylik_taksit'].sum()
                ortalama_faiz = (df_uzunv['tutar'] * df_uzunv['faiz_orani'] / 100).sum() / toplam_borc * 100 if toplam_borc > 0 else 0
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Toplam Borç", f"{toplam_borc:,.0f} TL")
                    st.metric("Ortalama Faiz", f"{ortalama_faiz:.2f}%")
                with col2:
                    st.metric("Aylık Toplam Taksit", f"{toplam_aylik_taksit:,.0f} TL")
                    st.metric("Kalan Ödeme Süresi", f"{toplam_kalan_ay} ay")
                with col3:
                    kalan_borc = toplam_aylik_taksit * toplam_kalan_ay
                    st.metric("Kalan Toplam Ödeme", f"{kalan_borc:,.0f} TL")
                    st.metric("Toplam Faiz Maliyeti", f"{kalan_borc - toplam_borc:,.0f} TL")
                
                st.markdown("---")
                st.markdown("**Ödeme Öncelik Sırası (Avalanche Yöntemi):**")
                for idx, row in df_uzunv_sorted.iterrows():
                    kalan_odeme = row['aylik_taksit'] * row['kalan_ay']
                    st.markdown(f"**{row['faiz_orani']:.1f}%** - {row['borc_adi']}: {row['tutar']:,.0f} TL (Kalan: {kalan_odeme:,.0f} TL, {row['kalan_ay']} ay)")
            else:
                st.info("Henüz kayıtlı borç bulunmuyor.")
        except Exception as e:
            st.info("Henüz kayıtlı borç bulunmuyor.")
        
    with tab4:
        st.markdown("### 🏦 Çoklu Banka Yönetimi")
        st.info("Farklı bankalardaki ticari kredileri, KMH (esnek hesap) ve kredi kartı limitleri")
        
        st.markdown("""
        **Bankalar:**
        - Akbank, Ziraat Bankası, Yapı Kredi, Garanti BBVA, İş Bankası, Enpara vb.
        
        **Kredi Türleri:**
        - Ticari krediler
        - KMH (esnek hesap)
        - Kredi kartı limitleri
        - Tarımsal sübvansiyonlu krediler
        """)
        
        st.markdown("---")
        
        # Banka Kredisi Ekleme Formu
        st.subheader("➕ Yeni Banka Kredisi Ekle")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            banka_adi = st.text_input("Banka Adı", key="banka_adi")
            kredi_turu = st.selectbox("Kredi Türü", ["Ticari Kredi", "KMH (Esnek Hesap)", "Kredi Kartı", "Tarımsal Sübvansiyonlu"], key="kredi_turu")
        
        with col2:
            kredi_limit = st.number_input("Limit/Tutar (TL)", min_value=0.0, step=1000.0, key="kredi_limit")
            kredi_faiz = st.number_input("Faiz Oranı (%)", min_value=0.0, max_value=100.0, step=0.1, key="kredi_faiz")
        
        with col3:
            kullanilan_tutar = st.number_input("Kullanılan Tutar (TL)", min_value=0.0, step=100.0, key="kullanilan_tutar")
            odeme_gunu = st.number_input("Ödeme Günü (ayın kaçı)", min_value=1, max_value=31, step=1, key="odeme_gunu")
        
        if st.button("➕ Banka Kredisi Ekle", type="primary"):
            if banka_adi and kredi_limit > 0:
                conn = get_db_connection()
                try:
                    # Tabloyu kontrol et ve yoksa oluştur
                    c = conn.cursor()
                    c.execute('''CREATE TABLE IF NOT EXISTS banka_kredileri
                                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                                  banka_adi TEXT NOT NULL,
                                  kredi_turu TEXT NOT NULL,
                                  kredi_limit REAL NOT NULL,
                                  faiz_orani REAL NOT NULL,
                                  kullanilan_tutar REAL NOT NULL DEFAULT 0.0,
                                  odeme_gunu INTEGER NOT NULL,
                                  olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                    
                    c.execute("""INSERT INTO banka_kredileri 
                                 (banka_adi, kredi_turu, kredi_limit, faiz_orani, kullanilan_tutar, odeme_gunu)
                                 VALUES (?, ?, ?, ?, ?, ?)""",
                        (banka_adi, kredi_turu, kredi_limit, kredi_faiz, kullanilan_tutar, odeme_gunu))
                    conn.commit()
                    st.success("✅ Banka kredisi eklendi!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Kaydetme hatası: {e}")
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                finally:
                    conn.close()
            else:
                st.warning("⚠️ Banka adı ve limit giriniz!")
        
        # Kayıtlı Banka Kredilerini Göster
        try:
            conn = get_db_connection()
            df_banka = _read_sql("SELECT * FROM banka_kredileri ORDER BY banka_adi ASC", conn)
            conn.close()
            
            st.markdown("---")
            st.subheader("📋 Kayıtlı Banka Kredileri")
            if not df_banka.empty:
                st.dataframe(df_banka.drop(columns=['id', 'olusturma_tarihi']), use_container_width=True)
            else:
                st.info("Henüz kayıtlı kredi bulunmuyor.")
        except Exception as e:
            st.info("Henüz kayıtlı kredi bulunmuyor.")
        
    with tab5:
        st.markdown("### ⚠️ Risk Senaryoları")
        st.info("Döngüsel Risk Uyarısı ve B Planı")
        
        st.markdown("""
        **Risk Faktörleri:**
        - Hastalık (örneğin Trichoderma)
        - Verim düşüklüğü
        - Flaşlar arası gecikmeler
        
        **Analiz:**
        - Oluşabilecek nakit açıkları
        - "B Planı" senaryoları
        """)
        
        st.markdown("---")
        
        # Risk Senaryo Ekleme Formu
        st.subheader("➕ Yeni Risk Senaryosu Ekle")
        
        col1, col2 = st.columns(2)
        
        with col1:
            risk_adi = st.text_input("Risk Adı", key="risk_adi")
            risk_turu = st.selectbox("Risk Türü", ["Hastalık", "Verim Düşüklüğü", "Flaş Gecikmesi", "Piyasa Riski", "Diğer"], key="risk_turu")
        
        with col2:
            risk_olasilik = st.slider("Olasılık (%)", min_value=0, max_value=100, step=5, key="risk_olasilik")
            risk_etkisi = st.number_input("Finansal Etki (TL)", min_value=0.0, step=1000.0, key="risk_etkisi")
        
        risk_aciklama = st.text_area("Açıklama / B Planı", key="risk_aciklama")
        
        if st.button("➕ Risk Senaryosu Ekle", type="primary"):
            if risk_adi and risk_etkisi > 0:
                conn = get_db_connection()
                try:
                    # Tabloyu kontrol et ve yoksa oluştur
                    c = conn.cursor()
                    c.execute('''CREATE TABLE IF NOT EXISTS risk_senaryolari
                                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                                  risk_adi TEXT NOT NULL,
                                  risk_turu TEXT NOT NULL,
                                  olasilik REAL NOT NULL,
                                  finansal_etki REAL NOT NULL,
                                  aciklama TEXT,
                                  olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                    
                    c.execute("""INSERT INTO risk_senaryolari 
                                 (risk_adi, risk_turu, olasilik, finansal_etki, aciklama)
                                 VALUES (?, ?, ?, ?, ?)""",
                        (risk_adi, risk_turu, risk_olasilik, risk_etkisi, risk_aciklama))
                    conn.commit()
                    st.success("✅ Risk senaryosu eklendi!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Kaydetme hatası: {e}")
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                finally:
                    conn.close()
            else:
                st.warning("⚠️ Risk adı ve finansal etki giriniz!")
        
        # Kayıtlı Risk Senaryolarını Göster
        try:
            conn = get_db_connection()
            df_risk = _read_sql("SELECT * FROM risk_senaryolari ORDER BY olasilik DESC", conn)
            conn.close()
            
            st.markdown("---")
            st.subheader("📋 Kayıtlı Risk Senaryoları")
            if not df_risk.empty:
                st.dataframe(df_risk.drop(columns=['id', 'olusturma_tarihi']), use_container_width=True)
            else:
                st.info("Henüz kayıtlı risk senaryosu bulunmuyor.")
        except Exception as e:
            st.info("Henüz kayıtlı risk senaryosu bulunmuyor.")
    
    st.markdown("---")
    st.markdown("### 📋 Beklenen Çıktılar")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
        **Acil Eylem Planı (İlk 30-60 Gün):**
        - Kuluçka gibi nakit girişinin olmadığı dönemlerde işletme sermayesi açığını kapatmak için hangi ödemelerin erteleneceği
        - Hangi kredi limitlerinin kullanılacağı
        
        **Borç Çığı Optimizasyonu:**
        - Tesisin toplam faiz yükünü en aza indirecek matematiksel ödeme planı
        - En yüksek faizli kısa vadeli borçtan başlayarak
        """)
    
    with col2:
        st.markdown("""
        **Döngüsel Risk Uyarısı:**
        - Hastalık, verim düşüklüğü veya flaşlar arası gecikmeler yaşanırsa oluşabilecek nakit açıkları
        - "B Planı" senaryoları
        
        **Yatırım Geri Dönüşü (ROI) İzleme:**
        - Alınan paketleme makineleri veya yeni iklimlendirme gruplarının kendi taksitlerini ne zaman ödemeye başlayacağının analizi
        """)

# Footer
st.markdown("---")
st.markdown(
    """
    <div style='text-align: center'>
        <p>Mantar Üretimi İş Takip Sistemi v1.0 | (c) 2026</p>
    </div>
    """,
    unsafe_allow_html=True
)
