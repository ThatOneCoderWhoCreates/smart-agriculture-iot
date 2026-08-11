#!/usr/bin/env bash
# End-to-end pipeline. Run from the project root.
set -e
echo "=== 1/3  generating dataset ==="        && python python/01_generate_dataset.py
echo "=== 2/3  preprocessing + analytics ===" && python python/02_preprocess_analyze.py
echo "=== 3/3  training + evaluation ==="     && python python/03_train_models.py
echo
echo "Done. Launch the dashboard with:  streamlit run dashboard/app.py"
