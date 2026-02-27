# EDF to BIDS Converter

A streamlined tool to convert EEG/iEEG data in EDF format to BIDS (Brain Imaging Data Structure) format.

## Features

- **CLI Mode**: Command-line interface for batch processing and scripting
- **GUI Mode**: Simple graphical interface when run without arguments
- **Resident Mode**: Watches a folder for new files and processes them automatically
- **De-identification**: Removes PHI from EDF headers and blanks annotations
- **PHI Redaction**: Optional TSV file redaction using a RoBERTa model
- **Auto Session Management**: Automatically increments session numbers

## Requirements

```
Python >= 3.7
numpy
pandas
tkinter (for GUI mode)
```

Optional for PHI redaction:
- `phi_redactor.py` and trained model checkpoint in `phi_redactor_model/` folder

## Installation

1. Place `edf2bids.py` and `edfreader_mld.py` in the same directory
2. (Optional) Place PHI redactor model in `phi_redactor_model/` subdirectory
3. Run the tool

## Usage

### GUI Mode (no arguments)

```bash
python edf2bids.py
```

Opens a graphical interface with:
- Input/Output folder selection
- Options checkboxes (de-identify, redact TSV, dry run, resident mode)
- Convert/Stop buttons
- Progress and log display

### CLI Mode

```bash
# Basic batch conversion
python edf2bids.py --input /path/to/input --output /path/to/bids

# With de-identification (default)
python edf2bids.py -i /data/raw -o /data/bids --deidentify

# Without de-identification
python edf2bids.py -i /data/raw -o /data/bids --no-deidentify

# With PHI redaction for TSV files
python edf2bids.py -i /data/raw -o /data/bids --redact-tsv

# Dry run (preview without writing)
python edf2bids.py -i /data/raw -o /data/bids --dry-run

# Resident mode (watch folder)
python edf2bids.py -i /data/incoming -o /data/bids --resident
```

### CLI Options

| Option | Description | Default |
|--------|-------------|---------|
| `--input`, `-i` | Input directory containing subject folders | Required |
| `--output`, `-o` | Output BIDS directory | Required |
| `--deidentify` | De-identify EDF files | True |
| `--no-deidentify` | Do not de-identify EDF files | - |
| `--redact-tsv` | Redact PHI from TSV files using model | False |
| `--dry-run` | Perform dry run without writing files | False |
| `--resident` | Run in resident mode (watch folder) | False |
| `--config` | Path to configuration JSON file | Auto-generated |

## Input Directory Structure

### Batch Mode
```
input/
├── sub-001/           # or just "001" - will be prefixed with "sub-"
│   ├── recording1.edf
│   └── recording2.edf
├── sub-002/
│   └── recording.edf
└── ...
```

### Resident Mode
```
input/
├── sub-001/
│   ├── filename.edf        # EDF file
│   └── filename.edf_pass   # Marker file indicating ready for processing
├── sub-002/
│   ├── another.edf
│   └── another.edf_pass
└── ...
```

The resident mode watches for EDF files that have a corresponding `.edf_pass` sidecar file. After processing:
- Success: Creates `filename.edf_bidsified` with conversion log
- Failure: Creates `filename.edf_bidfailed` with error log

## Output Structure (BIDS)

```
output/
├── dataset_description.json
├── participants.tsv
├── participants.json
├── sub-001/
│   ├── sub-001_scans.tsv
│   ├── ses-001/
│   │   └── ieeg/
│   │       ├── sub-001_ses-001_task-full_run-01_ieeg.edf
│   │       ├── sub-001_ses-001_task-full_run-01_ieeg.json
│   │       ├── sub-001_ses-001_task-full_run-01_channels.tsv
│   │       ├── sub-001_ses-001_task-full_run-01_events.tsv
│   │       └── sub-001_ses-001_electrodes.tsv
│   └── ses-002/
│       └── ...
├── sub-001_PHI/           # If redaction enabled, unredacted files go here
│   └── ses-001/
│       └── ieeg/
│           └── ...
└── sub-002/
    └── ...
```

## Configuration

On first run, creates `edf2bids_config.json` with default settings:

```json
{
    "general": {
        "recording_labels": "full,clip,stim,ccep",
        "default_recording_type": "iEEG",
        "channel_threshold_ieeg": 60,
        "clip_duration_threshold_hours": 5,
        "phi_redactor_model_path": "phi_redactor_model",
        "resident_scan_interval_seconds": 30
    },
    "json_metadata": {
        "TaskName": "EEG Clinical",
        "Experimenter": [""],
        "Lab": "",
        "InstitutionName": "",
        "InstitutionAddress": "",
        "ExperimentDescription": "",
        "DatasetName": ""
    },
    "equipment_info": {
        "Manufacturer": "Natus",
        "ManufacturersModelName": "Neuroworks",
        "PowerLineFrequency": 60,
        ...
    },
    "channel_info": {
        "Patient Event": {"type": "PatientEvent", "name": "PE"},
        "EKG": {"type": "EKG", "name": "EKG"},
        ...
    }
}
```

### Key Configuration Options

- **channel_threshold_ieeg**: Number of channels above which recording is considered iEEG (default: 60)
- **clip_duration_threshold_hours**: Recordings shorter than this are labeled "clip" (default: 5)
- **resident_scan_interval_seconds**: How often to check for new files in resident mode (default: 30)
- **phi_redactor_model_path**: Path to PHI redaction model folder

## PHI Redaction

When `--redact-tsv` is enabled:

1. TSV files (channels, electrodes, events) are processed through the PHI redactor model
2. If redaction occurs:
   - Original (unredacted) files are moved to `sub-XXX_PHI/` folder
   - Redacted files remain in the main BIDS structure
3. If model is unavailable but redaction was requested:
   - Entire session is moved to `sub-XXX_PHI/` folder
   - Warning is logged

## Recording Type Detection

The tool automatically determines:

- **Recording Type**: 
  - "iEEG" if channel count >= 60
  - "Scalp" if channel count < 60

- **Task Label**:
  - "clip" if duration < 5 hours
  - "full" if duration >= 5 hours

## Session Management

- Sessions auto-increment (ses-001, ses-002, ...)
- `scans.tsv` is updated for each new session
- `participants.tsv` is updated for new subjects

## Error Handling

- Invalid EDF files are skipped with error logging
- In resident mode, failed conversions create `.edf_bidfailed` marker files
- PHI redaction failures gracefully degrade to PHI folder placement

## License

Based on original work by Greydon Gilmore.
