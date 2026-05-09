lines = open('mantar_is_takip.py', 'r', encoding='utf-8').readlines()
out = []
for line in lines:
    if 'Oda Bilgi' in line and line.strip().startswith('"') and line.strip().endswith('",'):
        line = '     "📋 Oda Bilgi Kartı",\n'
    elif 'retim Takvimi' in line and line.strip().startswith('"') and line.strip().endswith('",'):
        line = '     "🌱 Üretim Takvimi",\n'
    out.append(line)
open('mantar_is_takip.py', 'w', encoding='utf-8').writelines(out)
print('OK')
