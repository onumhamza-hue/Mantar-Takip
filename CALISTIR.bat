@echo off
chcp 65001 >nul
echo ====================================
echo 🍄 Mantar İş Takip Sistemi
echo ====================================
echo.
echo Uygulama başlatılıyor...
echo Tarayıcıda otomatik açılacak: http://localhost:8501
echo.
echo Uygulamayı kapatmak için: CTRL + C
echo.
cd /d "%~dp0"
streamlit run mantar_is_takip.py
pause
