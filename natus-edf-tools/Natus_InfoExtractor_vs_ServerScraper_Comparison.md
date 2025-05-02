
# 🔍 Comparison of Natus_InfoExtractor_v2.py vs Natus_InfoServerScraper.py

## ✅ Similarities:
- Both tools extract metadata from `.eeg` files produced by Natus EEG systems.
- Both convert Excel-style timestamps into human-readable formats.
- Both collect folder-level statistics such as file count and total size.
- Output is structured into a tabular format and saved as an Excel file.
- Use of `pandas`, `re`, and `Pathlib` for data handling and traversal.

---

## 🚀 Differences:

### 1. **Purpose & Scope**
- **Natus_InfoExtractor_v2.py**:
  - More advanced and general-purpose.
  - Designed for deeply nested metadata extraction across multiple file types (`.eeg` and `.ent`).
  - Handles a wider range of clinical metadata fields (e.g., classification, diagnosis, impressions).
  - Extracts multiple versions of metadata entries and stores them with versioned tags.

- **Natus_InfoServerScraper.py**:
  - Simpler, more targeted toward known EEG folders on clinical export servers.
  - Matches folders using patterns and assumes each has a single `.eeg` file named after the folder.
  - Focused on straightforward, quick extraction for audit/reporting.

---

### 2. **Metadata Handling**
- **InfoExtractor v2**:
  - Uses multi-version field extraction for redundant keys.
  - Performs binary data filtering and key normalization.
  - Captures deeply nested structures, even handling binary markers.
  - Maintains original and derived forms of the metadata for auditing.

- **ServerScraper**:
  - Uses a basic recursive parser with a single-layer dictionary.
  - Skips binary filtering.
  - Simpler regex-based key detection.

---

### 3. **Input Handling**
- **InfoExtractor v2**:
  - Recursively scans all `.eeg` and `.ent` files under the directory tree.

- **ServerScraper**:
  - Only checks for `.eeg` files directly in folders matching a specified pattern.

---

### 4. **Output Detail**
- **InfoExtractor v2**:
  - Outputs more comprehensive metadata including EEG classification, findings, reviewer, etc.
  - Version-tagged variants for overlapping keys.

- **ServerScraper**:
  - Outputs basic fields like study name, EEG number, machine, and timestamps.

---

### 5. **Robustness & Reliability**
- **InfoExtractor v2**:
  - More defensive code (handles conversion exceptions, skips corrupt structures).
  - Flexible against malformed data.

- **ServerScraper**:
  - Simpler structure but less robust for non-standard folders or malformed entries.

---

## 🧠 Use Recommendations:
- Use **Natus_InfoExtractor_v2.py** for research datasets, anonymization validation, or metadata audits across mixed formats.
- Use **Natus_InfoServerScraper.py** for fast, structured exports from known folder hierarchies on clinical servers.

