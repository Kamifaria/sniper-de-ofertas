@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Sniper de Ofertas

where python >nul 2>nul || (
  echo Python nao encontrado. Instale o Python 3.11+ em https://www.python.org/downloads/
  echo Marque "Add python.exe to PATH" na instalacao.
  pause & exit /b 1
)

if not exist .venv (
  echo Criando ambiente virtual...
  python -m venv .venv || (pause & exit /b 1)
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip >nul
  pip install -r requirements.txt || (pause & exit /b 1)
) else (
  call .venv\Scripts\activate.bat
)

if not exist config.toml copy config.exemplo.toml config.toml >nul
if not exist data mkdir data

python run.py %*
if errorlevel 1 pause
