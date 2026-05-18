@echo off
REM Django on all interfaces — phone Flutter app uses http://192.168.100.25:8000/api
cd /d "%~dp0"
python manage.py runserver 0.0.0.0:8000
