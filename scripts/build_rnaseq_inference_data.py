"""Build the "bring your own data" inputs for demos/rnaseq-inference.ipynb.

Queries the GDC for open-access NCICCR-DLBCL RNA-seq TSVs for a fixed set of 20 cases,
downloads them, and writes:
  - nciccr-dlbcl-rnaseq.zip: the raw GDC STAR gene count TSVs, one per file
  - nciccr-dlbcl-metadata.csv: one row per TSV with case-level clinical metadata

The 20 cases (CASE_IDS) were chosen from all 481 NCICCR-DLBCL files embedded with
ctds-rnaseq: they are the files whose 10 nearest TCGA neighbors (cosine, all projects)
contain the most TCGA-DLBC samples, tie-broken by how often they sit among TCGA-DLBC in a
UMAP fit jointly on all TCGA and NCICCR embeddings. Each has 7-8 TCGA-DLBC samples among
its 10 nearest neighbors. Keeping the demo to 20 files keeps inference quick.

Usage: python scripts/build_rnaseq_inference_data.py [--out-dir DIR]
Requires: requests, pandas, tqdm
"""

import argparse
import hashlib
import os
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests
from tqdm import tqdm

GDC_BASE = "https://api.gdc.cancer.gov"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT_DIR = os.path.join(REPO_ROOT, "demos", "rnaseq-inference-data")
ZIP_NAME = "nciccr-dlbcl-rnaseq.zip"
CSV_NAME = "nciccr-dlbcl-metadata.csv"
MAX_WORKERS = 8  # parallel downloads; be polite to the GDC
ZIP_DATE_TIME = (2026, 1, 1, 0, 0, 0)  # fixed timestamp so rebuilds are byte-identical

# fmt: off
CASE_IDS = [
    "DLBCL10451", "DLBCL10508", "DLBCL10520", "DLBCL10525", "DLBCL10861",
    "DLBCL10877", "DLBCL10880", "DLBCL10887", "DLBCL10931", "DLBCL10965",
    "DLBCL10973", "DLBCL10977", "DLBCL10994", "DLBCL11443", "DLBCL11445",
    "DLBCL11487", "DLBCL11576", "DLBCL11659", "DLBCL11665", "DLBCL11676",
]

file_filter = {
    "op": "and",
    "content": [
        {"op": "in", "content": {"field": "cases.project.project_id", "value": ["NCICCR-DLBCL"]}},
        {"op": "in", "content": {"field": "cases.submitter_id", "value": CASE_IDS}},
        {"op": "in", "content": {"field": "files.experimental_strategy", "value": ["RNA-Seq"]}},
        {"op": "in", "content": {"field": "files.data_format", "value": ["tsv"]}},
        {"op": "in", "content": {"field": "files.access", "value": ["open"]}},
    ],
}

fields = [
    "file_id", "file_name", "md5sum",
    "cases.submitter_id", "cases.project.project_id", "cases.disease_type", "cases.primary_site",
    "cases.samples.submitter_id", "cases.samples.sample_type",
    "cases.demographic.sex_at_birth", "cases.demographic.race", "cases.demographic.ethnicity",
    "cases.demographic.vital_status",
    "cases.diagnoses.age_at_diagnosis", "cases.diagnoses.primary_diagnosis",
    "cases.diagnoses.ann_arbor_clinical_stage",
]
# fmt: on


def query_files() -> list[dict]:
    resp = requests.post(
        f"{GDC_BASE}/files",
        json={
            "filters": file_filter,
            "fields": ",".join(fields),
            "format": "JSON",
            "size": "100000",
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["data"]["hits"]


def to_row(hit: dict) -> dict:
    (case,) = hit["cases"]
    demo = case.get("demographic", {})
    (dx,) = case.get("diagnoses", [])
    age_days = dx.get("age_at_diagnosis")
    samples = [
        s["submitter_id"] for s in case["samples"] if s["sample_type"] == "Tumor"
    ]
    return {
        "file_name": hit["file_name"],
        "file_id": hit["file_id"],
        "md5sum": hit["md5sum"],
        "case_id": case["submitter_id"],
        "sample_ids": ";".join(sorted(samples)),
        "project_id": case["project"]["project_id"],
        "primary_site": case["primary_site"],
        "disease_type": case["disease_type"],
        "primary_diagnosis": dx.get("primary_diagnosis"),
        "ann_arbor_clinical_stage": dx.get("ann_arbor_clinical_stage"),
        "age_in_years": None if age_days is None else round(age_days / 365.24, 1),
        "sex_at_birth": demo.get("sex_at_birth"),
        "race": demo.get("race"),
        "ethnicity": demo.get("ethnicity"),
        "vital_status": demo.get("vital_status"),
    }


def download(row, dest_dir: str, retries: int = 3) -> str:
    dest = os.path.join(dest_dir, row.file_name)
    for attempt in range(1, retries + 1):
        try:
            with requests.get(
                f"{GDC_BASE}/data/{row.file_id}", stream=True, timeout=300
            ) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
            with open(dest, "rb") as f:
                if hashlib.md5(f.read()).hexdigest() != row.md5sum:
                    raise IOError(f"md5 mismatch for {row.file_name}")
            return dest
        except Exception:
            if attempt == retries:
                raise


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    meta = pd.DataFrame([to_row(h) for h in query_files()])
    meta = meta.sort_values(["case_id", "file_name"]).reset_index(drop=True)
    assert set(meta["case_id"]) == set(CASE_IDS), "some cases have no RNA-seq file"
    print(f"{len(meta)} files across {meta['case_id'].nunique()} cases")

    with tempfile.TemporaryDirectory() as tmp:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = [pool.submit(download, row, tmp) for row in meta.itertuples()]
            for fut in tqdm(futures, desc="Downloading"):
                fut.result()

        zip_path = os.path.join(args.out_dir, ZIP_NAME)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_name in meta["file_name"]:
                info = zipfile.ZipInfo(file_name, date_time=ZIP_DATE_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                with open(os.path.join(tmp, file_name), "rb") as f:
                    zf.writestr(info, f.read())

    csv_path = os.path.join(args.out_dir, CSV_NAME)
    meta.drop(columns=["file_id", "md5sum"]).to_csv(csv_path, index=False)
    print(f"wrote {zip_path} and {csv_path}")


if __name__ == "__main__":
    main()
