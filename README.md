# Clinical EEG Pipeline Natus → EDF → QC → Redaction → BIDS Toolbox

A modular suite of Python tools for clinical **Natus EEG/SEEG workflows**: session scouting, Natus→EDF export support, **EDF compatibility QC**, **PHI redaction**, **BIDS organization/verification**, and provenance-friendly cleanup/archiving. The tools are designed as a staged pipeline (**Step A → Step B → Step C**) plus a set of “Step X” utilities for verification, coverage mapping, and reporting.

> **Privacy / PHI disclaimer:** This repository provides tooling and documentation for *handling* clinical EEG/SEEG data, including optional PHI redaction steps. **Do not commit or share any real patient data** (raw recordings, exports, logs, screenshots, or annotation text) in this repo. When publishing datasets, ensure they are properly de-identified and compliant with your institution’s policies and applicable regulations.

> **Operational note (PHI):** videos (e.g., `*.avi`) should **not** be copied into research storage, and long‑term storage is intended to be **PHI‑minimized**.

---

## Pipeline at a glance

```
Step A: Natus landing & selection
   ↓  (licensed export on Natus workstation / Natus workstation)
Step B: EDF outputs + QC gates + optional EDF utilities
   ↓
Step C: Redaction + BIDS conversion + validation + publish
   ↓
Research storage (PHI‑minimized)
```

### What changes at each stage

- **Natus (raw sessions)**: variable folder structures, mixed session types, may include video and PHI-bearing notes.
- **EDF/EDF+**: portable time‑series artifact per session, still may contain PHI in headers/annotations.
- **QC & Verify**: automated gates to catch malformed or incomplete exports before BIDS.
- **Redaction**: remove/blank PHI surfaces (EDF header/annotations; TSV/JSON sidecars).
- **BIDS**: standardized dataset layout for downstream pipelines and sharing/validation.

---

## Deployment roles (example)

These tools are often used across a few *roles* (which may be physical or virtual machines):

- **Natus workstation**: system with licensed export capability (Natus → EDF).
- **Processing/staging server**: QC, redaction, BIDS conversion, verification.
- **Research storage**: long-term storage for *de-identified* research outputs.

- **Natus workstation**: Natus workstation with licensed export capability (Natus→EDF).
- **processing/staging server**: staging + processing server (QC, redaction, BIDS conversion, verification).
- **research storage**: long‑term research storage (intended PHI‑minimized).

An overview slide deck is included under `doc/`.

---

## Repository layout (current)

The tree below reflects the current toolbox layout shared in this project:

```
_tbd/
  StepX_BIDS_Verification/
    StepX_BIDS_folders_summarizer.py
    StepX_BIDs_verifier_0p05.py
    StepX_Coverage_Mapper.py
    StepX_GUI_Commander.py
    StepX_ccep_clipboard_updater.py
    StepX_ccep_summary_generator.py
    ccep_lib.py
    outfile.png
    tsv_coverage_mapper.ini
    __pycache__/
  __pycache__/

doc/
  README.md
  StepA3_GUI_README.md
  natus_edf_redaction_bids_pipeline.pptx

gui/
  GUI_Natus_Metadata_Viewer.py
  Modules/
    StepA3_GUI.py

models/
  redactor/
    config.json
    merges.txt
    robarta_pytorch_model.bin
    special_tokens_map.json
    test_metrics.json
```

### What’s where

#### `_tbd/StepX_BIDS_Verification/` (verification + reporting utilities)
- `StepX_GUI_Commander.py` — GUI entry point / launcher for Step X tools.
- `StepX_BIDS_folders_summarizer.py` — summarize a BIDS folder (counts, structure, basic completeness signals).
- `StepX_BIDs_verifier_0p05.py` — dataset verifier (threshold/tolerance “0p05” build).
- `StepX_Coverage_Mapper.py` — coverage mapping and visualization (driven by `tsv_coverage_mapper.ini`).
- `StepX_ccep_summary_generator.py` — generate CCEP summaries/reports.
- `StepX_ccep_clipboard_updater.py` — helper to format/update clipboard text for CCEP workflows.
- `ccep_lib.py` — shared CCEP helper library.

#### `gui/` (standalone GUIs)
- `GUI_Natus_Metadata_Viewer.py` — metadata inspection GUI for Natus/EDF/BIDS workflows.
- `Modules/StepA3_GUI.py` — shared GUI module(s) used by the Step A3 cleanup toolchain.

#### `models/redactor/` (optional ML redaction artifacts)
Model/tokenizer assets used by the ML redaction pathway (e.g., RoBERTa-family redactor).

#### `doc/` (documentation)
- `doc/README.md` — operator notes / runbook (recommended starting point for operators).
- `doc/StepA3_GUI_README.md` — Step A3 cleanup GUI notes.
- `doc/natus_edf_redaction_bids_pipeline.pptx` — end‑to‑end pipeline overview slides.

---

## Recommended entry points

### 1) Run a GUI tool
```bash
python gui/GUI_Natus_Metadata_Viewer.py
# or
python _tbd/StepX_BIDS_Verification/StepX_GUI_Commander.py
```

### 2) Run a Step X utility directly
```bash
python _tbd/StepX_BIDS_Verification/StepX_BIDS_folders_summarizer.py
python _tbd/StepX_BIDS_Verification/StepX_Coverage_Mapper.py
```

> Some tools use INI configuration (e.g., `tsv_coverage_mapper.ini`). Keep configs next to the scripts unless you’ve standardized a central config directory.

---

## Quick start (Python)

### Create an environment
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
```

### Install dependencies
This repo contains a mix of standalone scripts and optional components. Install what you need for the tools you plan to run.

Common dependencies you may encounter:
- `pandas`, `openpyxl` (Excel/TSV tooling)
- GUI stacks (varies by tool): `PyQt5`/`PySide6` and/or `PySimpleGUI`
- Optional ML redaction: `torch`, `transformers`

If your fork includes a `requirements.txt`, install it here (recommended to pin versions for reproducibility):
```bash
pip install -r requirements.txt
```

---

## Outputs & provenance (what to expect)

Depending on which tool you run, you may see:
- **Verification markers** (PASS/FAIL sidecars, summary reports)
- **Coverage maps** (TSV + images like `outfile.png`)
- **Redaction logs** (what changed, where)
- **Run logs** (recommended to keep alongside datasets for auditability)

---

## License

MIT (see repository license file).
