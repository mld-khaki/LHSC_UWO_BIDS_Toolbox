<p align="center">
  <img src=https://github.com/mld-khaki/LHSC_UWO_BIDS_Toolbox/blob/main/splash.png "Milad Khaki BIDS Tools"/>
</p>


# LHSC / UWO Natus → EDF → BIDS Toolbox

A modular suite of Python tools for **Natus EEG workflows**, **EDF handling**, **BIDS organization**, **redaction/anonymization**, **quality control**, and **archiving**. The repository is organized as a step-based pipeline (**Step A → B → C**) with additional “Step X” utilities for verification, provenance, and KPI reporting.

---

## What’s inside

### Main pipeline (step-based)

- **Step A — Natus landing & ingestion**
  - Session discovery / selection (GUI)
  - Compatibility checks and export helpers
  - Post-export cleanup and utilities

- **Step B — EDF transformation**
  - EDF clipping and time tools (GUI + helpers)
  - Label copy / redaction assistants
  - Legacy verification / evaluation tools

- **Step C — BIDS management**
  - BIDS consolidation and session shifting
  - BIDS verification & coverage mapping
  - Cleanup and validation toolbox
  - TSV / JSON redaction utilities (regex + ML options)
  - SEEG2BIDS and `data2bids` integration

- **Step X — Provenance / KPI / large-scale comparison**
  - Folder KPIs, log parsing, file comparisons
  - Compressed archive validation & maintenance

---

## Quick start

### 1) Create a Python environment

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
```

### 2) Install dependencies

This repo contains a mix of standalone scripts and packaged modules. Install what you need for the tools you plan to run.

Common dependencies you may encounter:
- `pandas`, `openpyxl` (Excel / TSV tooling)
- `PySimpleGUI` (some GUIs)
- `torch`, `transformers` (optional: ML-based redaction)

If you maintain an internal requirements file, install it here, e.g.:

```bash
pip install -r requirements.txt
```

---

## Recommended entry points

### Toolbox launcher (catalog-driven)

- **`src/toolbox_manager.py`**
  - Central launcher / orchestrator for tools (typically driven by `src/tools_catalog.ini`).

### Direct GUI scripts (run as needed)

- **`gui/GUI_Natus_Metadata_Viewer.py`**
- **`src/natus_edf_tools/StepA_Natus_landing_ingestion/.../*GUI*.py`**
- **`src/natus_edf_tools/StepB_EDF_transformation/.../*GUI*.py`**
- **`src/natus_edf_tools/StepC_BIDS_management/.../*GUI*.py`**

> Many tools have dedicated README/User-Guide files near the script (see the **Docs** section below).

---

## Repository layout

Below is the high-level layout (non-exhaustive):

```
doc/                       Documentation (README, GUI guide, slides)
gui/                       Standalone GUIs (plus GUI modules)
models/                    ML artifacts (e.g., RoBERTa redaction model)
src/                       Main codebase (launcher, pipeline steps, shared libs)
templates/                 Export/config templates (e.g., .exp files)
_tbd/                      Work-in-progress / staging area (not production)
```

### `doc/`
- `doc/natus_edf_redaction_bids_pipeline.pptx` – pipeline overview slides

### `gui/`
- `GUI_Natus_Metadata_Viewer.py` – metadata inspection GUI
- `Modules/StepA3_GUI.py` – shared GUI module(s)

### `models/redactor/`
Artifacts used by the ML redaction pathway (tokenizer files, model weights, configs).

### `src/` (core)

#### Top-level in `src/`
- `toolbox_manager.py` – toolbox launcher
- `tools_catalog.ini` – tool catalog (used by launcher)
- `log_path.env` + `log_path_env_init.ps1` – logging path configuration
- `logs/` – run logs and tool outputs

#### `src/common_libs/`
Shared libraries used across the pipeline:
- `anonymization/edf_anonymizer.py` – anonymization helpers
- `archiving/` – checksum + archive helpers (RAR, folder comparisons, tree generator)
- `edflib_fork_mld/` – EDF reader/writer fork and utilities
- `legacy/` – legacy tools and launchers (kept for backward compatibility)
- `organizing_code/` – environment helpers

#### `src/natus_edf_tools/` (pipeline steps)

**Step A — Natus landing & ingestion**
- `NatusFiles_CleanUp/` – post-archiving cleanup (CLI + GUI)
- `Natus_EDFExport/` – export automation helpers
- `Natus_Scout/` – session finder GUI (+ docs / INI configs)
- `Quasar_EDFCompatCheck/` – EDF compatibility check (GUI + tool)
- `_legacy/` – older ingestion tooling (kept for reference)

**Step B — EDF transformation**
- `EDF_Clipping/` – EDF time calculator and clipping helpers
- `LabelCopy_Redaction/` – EDF cleaner / redactor GUI + helpers
- `_legacy/StepB0_Eval/` + `_legacy/StepB5_edf_verification/` – evaluation & verification scripts

**Step C — BIDS management**
- `BIDS_Consolidation/` – structure generation, shifting, consolidation, participants merge
- `BIDS_Verification/` – folder summarizer, verifier, coverage mapper, utilities
- `BIDS_cleanup/` – logged deletion, archive/cleanup tools
- `BIDS_validation_toolbox/` – structured validator app (core/app/features/utils)
- `Redaction_TSV/` – TSV/JSON redaction:
  - `regex_method/` – rule-based redaction pipeline
  - `roberta_method/` – ML-based redaction pipeline
- `SEEG2BIDS/` – SEEG conversion helpers
- `data2bids/` – bundled third-party / integrated tooling for BIDS conversion

**Step X — Provenance / KPI tools**
- Folder KPIs, log parsing, large-file comparisons, compressed folder statistics.

### `_tbd/`
A staging area for experimental or in-progress scripts. Expect overlaps with production equivalents under `src/natus_edf_tools/`.

---

## Where to find help

- **Start with**: `doc/README.md`
- Look for script-specific docs near each tool:
  - `*_README.md`, `*_User_Guide.md`, `*.ini` config files
- Many tools produce logs under `src/logs/` (or the path set by `src/log_path.env`).

---

## License

MIT (see repository license file).
