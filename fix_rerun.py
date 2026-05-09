import re

content = open('mantar_is_takip.py', 'r', encoding='utf-8').read()

# Login rerununu koru (giris_yapildi satirindaki rerun)
MARK = '__LOGIN_RERUN__'
# Login satirinin tam hali
login_old = 'st.session_state["giris_yapildi"] = True\n                st.rerun()'
login_new = 'st.session_state["giris_yapildi"] = True\n                ' + MARK

content = content.replace(login_old, login_new)

# Kalan tum st.rerun() -> _rerun()
count = content.count('st.rerun()')
content = content.replace('st.rerun()', '_rerun()')

# Login rerununu geri al
content = content.replace(MARK, 'st.rerun()')

open('mantar_is_takip.py', 'w', encoding='utf-8').write(content)
print(f'DONE: {count} adet st.rerun() -> _rerun() degistirildi')
