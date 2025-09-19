@echo off
cd /d "E:\Área de Trabalho 2\VocSport"

echo Ativando ambiente virtual...
call .venv\Scripts\activate.bat

echo Verificando e instalando dependencias (requirements.txt)...
pip install -r requirements.txt

:loop
echo Iniciando o programa...
python -m app.main
echo ==========================================
echo O programa terminou. Reiniciando em 5 segundos...
echo ==========================================
timeout /t 5 /nobreak >nul
goto loop