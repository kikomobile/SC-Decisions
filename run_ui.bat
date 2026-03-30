@echo off
cd /d "%~dp0"
call "C:\Users\Gamers\anaconda3\condabin\conda.bat" activate base
streamlit run pipeline_ui.py
