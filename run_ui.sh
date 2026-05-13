#!/usr/bin/env bash
cd "$(dirname "$0")"
source .venv/bin/activate
exec streamlit run pipeline_ui.py
