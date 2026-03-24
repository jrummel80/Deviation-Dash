@echo off
setlocal

cd /d "%~dp0"
call "%~dp0install_autogluon.bat" --gpu
