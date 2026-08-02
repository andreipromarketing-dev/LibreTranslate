@ECHO OFF
set ARGOS_DEVICE_TYPE=cuda
set ARGOS_COMPUTE_TYPE=auto
set ARGOS_BEAM_SIZE=8
set ARGOS_BATCH_SIZE=512
cd /d "E:\MY-LIFE-SYSTEM\LibreTranslate"
start "LibreTranslate Server" "E:\MY-LIFE-SYSTEM\LibreTranslate\venv\Scripts\python.exe" main.py --host 0.0.0.0 --port 5000 --load-only en,ru

:wait
timeout /t 2 /nobreak >nul
curl.exe -s -o nul --max-time 2 "http://localhost:5000/languages"
if errorlevel 1 goto wait

start "" "http://localhost:5000"
