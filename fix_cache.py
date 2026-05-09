"""
Sık kullanılan dropdown sorgularını cached versiyonlarla değiştirir.
"""
import re

content = open('mantar_is_takip.py', 'r', encoding='utf-8').read()

replacements = [
    # --- odalar (tümü) dropdown yüklemeleri ---
    # Pattern: conn = get_db_connection()\n    df_odalar = _read_sql("SELECT id, oda_adi FROM odalar ORDER BY oda_adi", conn)\n    conn.close()
    (
        'conn = get_db_connection()\n        df_odalar_ut = _read_sql("SELECT id, oda_adi FROM odalar ORDER BY oda_adi", conn)\n        conn.close()',
        'df_odalar_ut = _cached_odalar()'
    ),
    (
        'conn = get_db_connection()\n        df_odalar_kart = _read_sql("SELECT id, oda_adi FROM odalar ORDER BY oda_adi", conn)\n        conn.close()',
        'df_odalar_kart = _cached_odalar()'
    ),
    # Hasat tabındaki aktif odalar yüklemesi
    (
        'conn = get_db_connection()\n        df_odalar = _read_sql("SELECT id, oda_adi FROM odalar WHERE durum=\'Aktif\' ORDER BY oda_adi", conn)\n        conn.close()',
        'df_odalar = _cached_odalar_aktif()'
    ),
    # Iklim tab1 odalar yüklemesi
    (
        'conn = get_db_connection()\n        df_odalar = _read_sql("SELECT id, oda_adi FROM odalar ORDER BY oda_adi", conn)\n        conn.close()',
        'df_odalar = _cached_odalar()'
    ),
]

count = 0
for old, new in replacements:
    if old in content:
        content = content.replace(old, new)
        count += 1
        print(f'Replaced: {old[:60].strip()!r}')
    else:
        print(f'NOT FOUND: {old[:60].strip()!r}')

open('mantar_is_takip.py', 'w', encoding='utf-8').write(content)
print(f'\nToplam {count} değiştirme yapıldı.')
