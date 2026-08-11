r"""
05_pack_for_deploy.py
=====================
Prepare the repository for a free Streamlit Community Cloud deployment.

The dashboard only needs four things at runtime: the processed dataset, the
test predictions, the three models and the metrics JSON. The processed dataset
is 25 MB of CSV, which is most of the repository, and it compresses to about
6 MB. pandas reads `.csv.gz` natively, so gzipping it costs nothing at runtime
and the dashboard already prefers the compressed copy when it exists.

Run:  python python/05_pack_for_deploy.py
"""

import gzip
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DATA = os.path.join(ROOT, "data")

RUNTIME = ["processed_dataset.csv", "test_predictions.csv"]


def gz(name):
    src = os.path.join(DATA, name)
    dst = src + ".gz"
    if not os.path.exists(src):
        print(f"  skip   {name} (not found — run the pipeline first)")
        return
    with open(src, "rb") as f_in, gzip.open(dst, "wb", compresslevel=9) as f_out:
        shutil.copyfileobj(f_in, f_out)
    a, b = os.path.getsize(src) / 1e6, os.path.getsize(dst) / 1e6
    print(f"  packed {name:26s} {a:6.1f} MB -> {b:5.1f} MB")


if __name__ == "__main__":
    print("packing runtime data")
    for n in RUNTIME:
        gz(n)

    keep = ["data/processed_dataset.csv.gz", "data/test_predictions.csv.gz",
            "models/", "reports/model_metrics.json", "dashboard/", "assets/",
            "requirements.txt", ".streamlit/config.toml"]
    print("\ncommit these for the deployed app:")
    for k in keep:
        print(f"  {k}")
    print("\nthe uncompressed CSVs are gitignored; regenerate them locally with")
    print("  bash run_all.sh")
