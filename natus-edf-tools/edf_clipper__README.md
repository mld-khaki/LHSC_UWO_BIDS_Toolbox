## Header for `edf_clipper.py`



EDF Clipping Utility

This script processes EDF (European Data Format) files to extract and clip specific segments
based on user-defined parameters. It supports metadata extraction and signal selection, making
it useful for EEG and other biosignal processing applications.

Author: Dr. Milad Khaki	
Date: 2025 Feb 20

Dependencies:
- numpy
- tqdm
- argparse
- json
- datetime
- pathlib
- os
- ext_lib.edflibpy (for EDF read/write operations)
- _lhsc_lib.EDF_reader_mld (optimized EDF reader)

Usage:
- Generate metadata:
    python edf_clipper.py --input input.edf --metadata --output metadata.json
- Clip an EDF file:
    python edf_clipper.py --input input.edf --clip clip_params.json --output clipped.edf

\"\"\"
```

---

## README.md

```markdown
# EDF Clipping Utility

This script processes and clips EDF (European Data Format) files to extract specific segments.
It provides functionalities to:

- Extract metadata from an EDF file.
- Clip an EDF file based on user-defined time segments.
- Select specific signals for extraction.

## Features
- Reads and writes EDF files with annotations.
- Supports metadata extraction.
- Clipping by start and end times.
- Selection of specific signal channels.

## Installation

Ensure you have Python 3.x installed. You also need the following dependencies:


pip install numpy tqdm
```

External libraries required:
- `ext_lib.edflibpy`
- `_lhsc_lib.EDF_reader_mld`

These may need to be installed manually based on your environment.

## Usage

### Extract Metadata
To generate metadata from an EDF file:


python edf_clipper.py --input input.edf --metadata --output metadata.json
```

### Clip EDF File
To clip a segment of an EDF file:

```sh
python edf_clipper.py --input input.edf --clip clip_params.json --output clipped.edf
```

### Arguments
- `--input`, `-i`: Input EDF file path (required)
- `--metadata`, `-m`: Extract metadata and save as JSON
- `--clip`, `-c`: Path to JSON file containing clipping parameters
- `--output`, `-o`: Output file path

## Example

Clipping an EDF file using predefined parameters:

```sh
python edf_clipper.py -i data.edf -c clip_params.json -o clipped.edf
```

## License
MIT License

