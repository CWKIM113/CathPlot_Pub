@echo off
if "%~1"=="hidden" goto :run
rem 부모창 숨기기
powershell -NoProfile -NonInteractive -WindowStyle Hidden -Command "Start-Process -FilePath '%~f0' -ArgumentList 'hidden' -WindowStyle Hidden"
exit /b

:run
REM 여기부터 원래 작업
rem "C:\CODES\bin\CathPlot\CathPlot.exe"
start "" "D:\CathPlot\CathPlot.exe"