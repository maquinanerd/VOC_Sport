@echo off
:loop
cd /d "E:\Área de Trabalho 2\VocMoney"
call .venv\Scripts\activate.bat
python -m app.main
echo ==========================================
echo O programa terminou. Reiniciando em 5 segundos...
echo ==========================================
timeout /t 5 /nobreak >nul
goto loop