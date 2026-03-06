#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EDF to BIDS Converter
=====================
A tool to convert EEG/iEEG data in EDF format to BIDS format.

Supports:
- CLI mode with arguments
- GUI mode (no arguments)
- Resident mode (watches folder for new files)

Author: Based on original work by Greydon Gilmore
Simplified and refactored for CLI/GUI usage
"""

import os
import sys
import json
import shutil
import argparse
import time
import re
import gzip
import subprocess
import tempfile
import hashlib
import threading
from datetime import datetime, timedelta
from collections import OrderedDict
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import numpy as np
import pandas as pd

# Import local EDF reader
from common_libs.edflib_fork_mld.edfreader_mld2 import EDFreader, EDFexception as EDFException
#from common_libs.edflib_fork_mld.edfreader import EDFreader, EDFexception as EDFException
from common_libs.anonymization.edf_anonymizer import anonymize_edf_file

EDFREADER_VERBOSE=1
# ============================================================================
# Configuration Management
# ============================================================================

DEFAULT_CONFIG = {
    "general": {
        "recording_labels": "full,clip,stim,ccep",
        "default_recording_type": "iEEG",
        "channel_threshold_ieeg": 60,
        "clip_duration_threshold_hours": 5,
        "phi_redactor_model_path": "phi_redactor_model",
        "resident_scan_interval_seconds": 30
    },
    "json_metadata": {
        "TaskName": "Uncategorized EEG Clinical",
        "Experimenter": "",
        "Lab": "",
        "InstitutionName": "Some University",
        "InstitutionAddress": "123 Fake Street, Fake Town, Fake Country",
        "ExperimentDescription": "",
        "DatasetName": ""
    },
    "equipment_info": {
        "Manufacturer": "Natus",
        "ManufacturersModelName": "Neuroworks",
        "PowerLineFrequency": 60,
        "RecordingType": "continuous",
        "SubjectArtefactDescription": "",
        "iEEGPlacementScheme": "",
        "iEEGElectrodeGroups": "",
        "iEEGElectrodeInfo": {
            "Manufacturer": "AdTech",
            "Type": "depth",
            "Material": "Platinum",
            "Diameter": 0.86
        },
        "EEGElectrodeInfo": {
            "Manufacturer": "AdTech",
            "Type": "scalp",
            "Material": "Platinum",
            "Diameter": 10
        }
    },
    "channel_info": {
        "Patient Event": {"type": "PatientEvent", "name": "PE"},
        "DC": {"type": "DAC", "name": "DAC"},
        "TRIG": {"type": "TRIG", "name": "TR"},
        "OSAT": {"type": "OSAT", "name": "OSAT"},
        "PR": {"type": "PR", "name": "MISC"},
        "Pleth": {"type": "Pleth", "name": "MISC"},
        "EDF Annotations": {"type": "Annotations", "name": "ANNO"},
        "X": {"type": "unused", "name": "unused"},
        "EKG": {"type": "EKG", "name": "EKG"},
        "EMG": {"type": "EMG", "name": "EMG"},
        "EOG": {"type": "EOG", "name": "EOG"},
        "ECG": {"type": "ECG", "name": "ECG"},
        "SpO2": {"type": "SpO2", "name": "SpO2"}
    }
}


def get_config_path():
    """Get path to config file (beside the script)."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, "edf2bids_config.json")


def load_config():
    """Load configuration from JSON file, create if not exists."""
    config_path = get_config_path()
    
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config = json.load(f)
        # Merge with defaults to handle missing keys
        merged = DEFAULT_CONFIG.copy()
        deep_update(merged, config)
        return merged
    else:
        # Create default config file
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()


def save_config(config):
    """Save configuration to JSON file."""
    config_path = get_config_path()
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=4)


def deep_update(base_dict, update_dict):
    """Recursively update a dictionary."""
    for key, value in update_dict.items():
        if key in base_dict and isinstance(base_dict[key], dict) and isinstance(value, dict):
            deep_update(base_dict[key], value)
        else:
            base_dict[key] = value


# ============================================================================
# Utility Functions
# ============================================================================

def padtrim(buf, num):
    """Pad or trim string to specified length."""
    num -= len(str(buf))
    if num >= 0:
        buffer = str(buf) + ' ' * num
    else:
        buffer = str(buf)[:num]
    return bytes(buffer, 'latin-1')


def sorted_nicely(lst):
    """Sort strings with embedded numbers naturally."""
    convert = lambda text: int(text) if text.isdigit() else text
    alphanum_key = lambda key: [convert(c) for c in re.split('([0-9]+)', key)]
    return sorted(lst, key=alphanum_key)


def partition(iterable):
    """Separate list of strings into alpha and digit parts."""
    values = []
    for item in iterable:
        if len(re.findall(r"([a-zA-Z]+)([0-9]+)", item)) > 1:
            first = "".join(list(re.findall(r"([a-zA-Z]+)([0-9]+)([a-zA-Z]+)", item)[0]))
            second = list(re.findall(r"([a-zA-Z]+)([0-9]+)", item)[-1])[-1]
            values.append([first, second])
        elif list(re.findall(r"([a-zA-Z]+)([0-9]+)", item)):
            values.append(list(re.findall(r"([a-zA-Z]+)([0-9]+)", item)[0]))
        else:
            values.append([
                "".join(x for x in item if not x.isdigit()),
                "".join(sorted(x for x in item if x.isdigit()))
            ])
    return values


def determine_groups(iterable):
    """Identify unique string groups in a list."""
    values = []
    for item in iterable:
        if len(re.findall(r"([a-zA-Z]+)([0-9]+)", item)) > 1:
            first = "".join(list(re.findall(r"([a-zA-Z]+)([0-9]+)([a-zA-Z]+)", item)[0]))
            values.append(first)
        else:
            values.append("".join(x for x in item if not x.isdigit()))
    return list(set(values))


def sec2time(sec, n_msec=3):
    """Convert seconds to time string."""
    if hasattr(sec, '__len__'):
        return [sec2time(s) for s in sec]
    neg = False
    if sec < 0:
        neg = True
        sec = sec * -1
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    if n_msec > 0:
        pattern = '%%02d:%%02d:%%0%d.%df' % (n_msec + 3, n_msec)
    else:
        pattern = r'%02d:%02d:%02d'
    if d == 0:
        if neg:
            return '-' + pattern % (h, m, s)
        else:
            return pattern % (h, m, s)
    return ('%d days, ' + pattern) % (d, h, m, s)


def file_hash(path):
    """Hash file content after normalizing line endings."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        data = f.read()
    data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    h.update(data)
    return h.hexdigest()


# ============================================================================
# EDF File Information Extraction
# ============================================================================

class EDFInfo:
    """Extract and hold information from an EDF file."""
    
    def __init__(self, filepath, config):
        self.filepath = filepath
        self.config = config
        self.info = {}
        self._extract_info()
    
    def _extract_info(self):
        """Extract header information from EDF file."""
        try:
            edf = EDFreader(self.filepath, read_annotations=False)
            
            # Basic info
            num_signals = edf.getNumSignals()
            num_records = edf.getNumDataRecords()
            
            # Get sample frequency from first signal
            if num_signals > 0:
                sample_freq = edf.getSampleFrequency(0)
            else:
                sample_freq = 256  # Default
            
            # Duration in hours
            duration_100ns = edf.getFileDuration()
            duration_hours = duration_100ns / (10000000 * 3600)
            
            # Start date/time
            start_dt = edf.getStartDateTime()
            
            # Patient info
            patient_name = edf.getPatientName()
            patient_code = edf.getPatientCode()
            gender = edf.getPatientGender()
            birthdate = edf.getPatientBirthDate()
            
            # Get channel labels
            channel_labels = []
            channel_units = []
            for i in range(num_signals):
                channel_labels.append(edf.getSignalLabel(i))
                channel_units.append(edf.getPhysicalDimension(i))
            
            # Determine recording type based on channel count
            threshold = self.config['general']['channel_threshold_ieeg']
            if num_signals < threshold:
                recording_type = 'Scalp'
            else:
                recording_type = 'iEEG'
            
            # Determine task based on duration
            clip_threshold = self.config['general']['clip_duration_threshold_hours']
            if duration_hours < clip_threshold:
                task = 'clip'
            else:
                task = 'full'
            
            # File type (EDF/EDF+/BDF/BDF+)
            file_type = edf.getFileType()
            type_map = {0: 'EDF', 1: 'EDF+', 2: 'BDF', 3: 'BDF+'}
            edf_type = type_map.get(file_type, 'EDF')
            
            # Get prefilter info for highpass/lowpass
            highpass = None
            lowpass = None
            if num_signals > 0:
                prefilter = edf.getPreFilter(0)
                # Parse prefilter string for HP/LP values
                hp_match = re.search(r'HP[:\s]*(\d+\.?\d*)', prefilter, re.IGNORECASE)
                lp_match = re.search(r'LP[:\s]*(\d+\.?\d*)', prefilter, re.IGNORECASE)
                if hp_match:
                    highpass = float(hp_match.group(1))
                if lp_match:
                    lowpass = float(lp_match.group(1))
            
            edf.close()
            
            # Categorize channels
            chan_info = self._categorize_channels(channel_labels, channel_units, recording_type)
            
            self.info = {
                'FileName': os.path.basename(self.filepath),
                'FilePath': self.filepath,
                'Date': start_dt.strftime('%Y-%m-%d'),
                'Time': start_dt.strftime('%H:%M:%S'),
                'DateTime': start_dt,
                'NChan': num_signals,
                'NRecords': num_records,
                'SamplingFrequency': int(sample_freq),
                'TotalRecordTime': round(duration_hours, 3),
                'RecordingType': recording_type,
                'RecordingLength': task,
                'Retro_Pro': 'Pro',
                'EDF_type': edf_type,
                'Highpass': highpass,
                'Lowpass': lowpass,
                'PatientName': patient_name,
                'PatientCode': patient_code,
                'Gender': gender if gender else 'X',
                'Birthdate': birthdate,
                'ChannelLabels': channel_labels,
                'ChannelUnits': channel_units,
                'ChanInfo': chan_info,
                'Groups': determine_groups([l for l in channel_labels if l])
            }
            
        except Exception as e:
            raise(e)
            raise ValueError(f"Failed to read EDF file: {e}")
    
    def _categorize_channels(self, labels, units, recording_type):
        """Categorize channels by type."""
        chan_info = {}
        channel_config = self.config['channel_info']
        
        # Determine main channel type
        if recording_type == 'iEEG':
            main_type = 'SEEG' 
        else:
            main_type = 'EEG'
        
        main_indices = []
        other_indices = {k: [] for k in channel_config.keys()}
        
        for i, label in enumerate(labels):
            categorized = False
            for key in channel_config.keys():
                if label.startswith(key):
                    other_indices[key].append(i)
                    categorized = True
                    break
            if not categorized:
                main_indices.append(i)
        
        # Main channel info
        chan_info[main_type] = OrderedDict([
            ('ChannelCount', len(main_indices)),
            ('Unit', [units[i] for i in main_indices]),
            ('ChanName', [labels[i] for i in main_indices]),
            ('Type', main_type)
        ])
        
        # Other channel types
        for key, indices in other_indices.items():
            if indices:
                chan_info[key] = OrderedDict([
                    ('ChannelCount', len(indices)),
                    ('Unit', [units[i] for i in indices]),
                    ('ChanName', [labels[i] for i in indices]),
                    ('Type', channel_config[key]['name'])
                ])
        
        return chan_info


# ============================================================================
# BIDS File Writing
# ============================================================================

class BIDSWriter:
    """Handle BIDS file structure and writing."""
    
    def __init__(self, output_path, config):
        self.output_path = output_path
        self.config = config
    
    def make_bids_filename(self, subject_id, session_id=None, task_id=None, 
                           run_num=None, suffix=None, kind=None):
        """Construct a BIDS-compliant filename."""
        parts = [subject_id]
        
        if session_id:
            if not session_id.startswith('ses-'):
                session_id = f'ses-{session_id}'
            parts.append(session_id)
        
        if task_id:
            parts.append(f'task-{task_id}')
        
        if run_num:
            parts.append(f'run-{run_num}')
        
        if suffix:
            parts.append(suffix)
        
        filename = '_'.join(parts)
        
        # Build path
        path_parts = [self.output_path, subject_id]
        if session_id:
            path_parts.append(session_id if session_id.startswith('ses-') else f'ses-{session_id}')
        if kind:
            path_parts.append(kind)
        
        return os.path.join(*path_parts, filename)
    
    def make_bids_folders(self, subject_id, session_id=None, kind=None):
        """Create BIDS folder structure."""
        path_parts = [self.output_path, subject_id]
        
        if session_id:
            if not session_id.startswith('ses-'):
                session_id = f'ses-{session_id}'
            path_parts.append(session_id)
        
        if kind:
            path_parts.append(kind)
        
        path = os.path.join(*path_parts)
        os.makedirs(path, exist_ok=True)
        return path
    
    def write_dataset_description(self):
        """Write dataset_description.json."""
        filepath = os.path.join(self.output_path, 'dataset_description.json')

        if not os.path.exists(filepath):
            exp = self.config.get('json_metadata', {}).get('Experimenter', "")

            # Allow Experimenter to be either a string or a list of strings
            if isinstance(exp, list):
                authors = [str(x).strip() for x in exp if str(x).strip()]
            else:
                s = str(exp).strip()
                authors = [s] if s else []

            if not authors:
                authors = ["Unknown Author"]

            data = OrderedDict([
                ('Name', self.config['json_metadata'].get('DatasetName', '')),
                ('BIDSVersion', '1.9.0'),
                ('License', ''),
                ('Authors', authors),
                ('Acknowledgements', ''),
                ('HowToAcknowledge', ''),
                ('Funding', ['']),
                ('ReferencesAndLinks', ['']),
                ('DatasetDOI', '')
            ])

            with open(filepath, 'w') as f:
                json.dump(data, f, indent=4)

        return filepath
    
    def write_readme(self):
        """Write a minimal README file (required by BIDS, >150 bytes recommended)."""
        filepath = os.path.join(self.output_path, 'README')
        if not os.path.exists(filepath):
            dataset_name = self.config['json_metadata'].get('DatasetName', 'iEEG Dataset')
            description  = self.config['json_metadata'].get('ExperimentDescription', '')
            institution  = self.config['json_metadata'].get('InstitutionName', '')
            first = self.config['json_metadata'].get('ExperimenterFirstName', '').strip()
            last  = self.config['json_metadata'].get('ExperimenterLastName', '').strip()
            author = f"{first} {last}".strip() if (first or last) else ''

            lines = [
                f"# {dataset_name}",
                "",
                description or "iEEG/SEEG recordings converted to BIDS format.",
                "",
                f"Institution: {institution}" if institution else "",
                f"Contact: {author}" if author else "",
                "",
                "This dataset was converted using SEEG2BIDS.",
            ]
            content = "\n".join(l for l in lines)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content + "\n")
        return filepath

    def write_participants(self, subject_id, age='n/a', sex='X', group='patient'):
        """Write or update participants.tsv."""
        # Cap age at 89+ per HIPAA / BIDS AGE_89 rule
        if isinstance(age, (int, float)) and age >= 89:
            age = "89+"
        filepath = os.path.join(self.output_path, 'participants.tsv')
        json_filepath = os.path.join(self.output_path, 'participants.json')
        
        # Write JSON sidecar if not exists
        if not os.path.exists(json_filepath):
            json_data = {
                "participant_id": {"Description": "Unique participant identifier"},
                "age": {"Description": "Age of participant", "Units": "years"},
                "sex": {"Description": "Sex of participant", "Levels": {"M": "male", "F": "female", "X": "unknown"}},
                "group": {"Description": "Participant group"}
            }
            with open(json_filepath, 'w') as f:
                json.dump(json_data, f, indent=4)
        
        # Read or create participants.tsv
        if os.path.exists(filepath):
            df = pd.read_csv(filepath, sep='\t')
        else:
            df = pd.DataFrame(columns=['participant_id', 'age', 'sex', 'group'])
        
        # Add or update participant
        if subject_id not in df['participant_id'].values:
            new_row = pd.DataFrame([{
                'participant_id': subject_id,
                'age': age,
                'sex': sex,
                'group': group
            }])
            df = pd.concat([df, new_row], ignore_index=True)
            df.to_csv(filepath, sep='\t', index=False)
        
        return filepath
    
    def write_scans(self, subject_id, session_id, filename, acq_time,
                    duration_hours=None, edf_type=None):
        """Write or update scans.tsv for a subject/session (session-level per BIDS)."""
        if not session_id.startswith('ses-'):
            session_id_full = f'ses-{session_id}'
        else:
            session_id_full = session_id

        # BIDS: scans.tsv lives at the session level
        scans_path = os.path.join(
            self.output_path, subject_id, session_id_full,
            f'{subject_id}_{session_id_full}_scans.tsv'
        )
        
        if os.path.exists(scans_path):
            df = pd.read_csv(scans_path, sep='\t')
            # Ensure new columns exist in old files
            for col in ('duration', 'edf_type'):
                if col not in df.columns:
                    df[col] = 'n/a'
        else:
            df = pd.DataFrame(columns=['filename', 'acq_time', 'duration', 'edf_type'])
        
        # Build relative path (relative to session folder in BIDS)
        kind = 'ieeg' if 'ieeg' in filename.lower() else 'eeg'
        rel_filename = f'{kind}/{filename}'
        
        if rel_filename not in df['filename'].values:
            new_row = pd.DataFrame([{
                'filename': rel_filename,
                'acq_time':  acq_time,
                'duration':  round(duration_hours, 4) if duration_hours is not None else 'n/a',
                'edf_type':  edf_type if edf_type else 'n/a',
            }])
            df = pd.concat([df, new_row], ignore_index=True)
            df.to_csv(scans_path, sep='\t', index=False)
        
        return scans_path
    
    def write_channels(self, filepath, edf_info):
        """Write channels.tsv file."""
        rows = []
        
        for chan_type, info in edf_info['ChanInfo'].items():
            for i, name in enumerate(info['ChanName']):
                if name == "Patient Event":
                    bids_type = "OTHER"
                else:
                    bids_type = info['Type']
                    
                rows.append({
                    'name': name,
                    'type': bids_type,
                    'units': info['Unit'][i].replace('uV', 'μV'),
                    # BIDS: low_cutoff = high-pass (lower edge of passband)
                    #       high_cutoff = low-pass  (upper edge of passband)
                    'low_cutoff':  edf_info.get('Highpass', 'n/a') or 'n/a',
                    'high_cutoff': edf_info.get('Lowpass',  'n/a') or 'n/a',
                    'sampling_frequency': edf_info['SamplingFrequency'],
                    'notch': 'n/a',
                    'reference': 'n/a',
                    'group': 'n/a'
                })
        
        df = pd.DataFrame(rows)
        df.to_csv(filepath, sep='\t', index=False)
        return filepath
    
    def write_electrodes(self, filepath, edf_info):
        """Write electrodes.tsv file."""
        rows = []
        
        main_type = 'SEEG' if edf_info['RecordingType'] == 'iEEG' else 'EEG'
        if main_type in edf_info['ChanInfo']:
            for name in edf_info['ChanInfo'][main_type]['ChanName']:
                rows.append({
                    'name': name,
                    'x': 'n/a',
                    'y': 'n/a',
                    'z': 'n/a',
                    'size': 'n/a',
                    'type': 'n/a'
                })
        
        df = pd.DataFrame(rows)
        df.to_csv(filepath, sep='\t', index=False)
        return filepath
    
    def write_sidecar_json(self, filepath, edf_info):
        """Write sidecar JSON file for EDF."""
        config = self.config
        
        if edf_info['RecordingType'] == 'iEEG':
            electrode_info = config['equipment_info']['iEEGElectrodeInfo']
        else:
            electrode_info = config['equipment_info']['EEGElectrodeInfo']
        
        task_name = edf_info['RecordingLength']
        if edf_info.get('Retro_Pro') == 'Ret':
            task_name += 'ret'
        
        data = OrderedDict([
            ('TaskName', task_name),
            ('InstitutionName', config['json_metadata']['InstitutionName']),
            ('InstitutionAddress', config['json_metadata']['InstitutionAddress']),
            ('Manufacturer', config['equipment_info']['Manufacturer']),
            ('ManufacturersModelName', config['equipment_info']['ManufacturersModelName']),
            ('SamplingFrequency', edf_info['SamplingFrequency']),
            ('HardwareFilters', {
                'HighpassFilter': {'Cutoff (Hz)': edf_info.get('Highpass') or 'n/a'},
                'LowpassFilter': {'Cutoff (Hz)': edf_info.get('Lowpass') or 'n/a'}
            }),
            ('SoftwareFilters', 'n/a'),
            ('PowerLineFrequency', config['equipment_info']['PowerLineFrequency']),
            # BIDS requires RecordingDuration in seconds
            ('RecordingDuration', round(edf_info['TotalRecordTime'] * 3600, 3)),
            ('RecordingType', 'continuous'),
            ('ElectrodeManufacturer', electrode_info['Manufacturer'])
        ])
        
        # Add channel counts
        for chan_type in ['EEG', 'SEEG', 'EOG', 'ECG', 'EMG', 'ECOG', 'MISC', 'TRIG']:
            key = f'{chan_type}ChannelCount'
            if chan_type in edf_info['ChanInfo']:
                data[key] = edf_info['ChanInfo'][chan_type]['ChannelCount']
            else:
                data[key] = 0
        
        # Declare the channels.tsv columns so the validator doesn't warn about
        # undefined additional columns (TSV_ADDITIONAL_COLUMNS_UNDEFINED)
        data['Columns'] = [
            "name", "type", "units", "low_cutoff", "high_cutoff",
            "sampling_frequency", "notch", "reference", "group"
        ]
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=4)
        
        return filepath
    
    def write_events(self, filepath, annotations):
        """Write events.tsv file from annotations."""
        if not annotations:
            df = pd.DataFrame(columns=["onset", "duration", "time_abs", "time_rel", "trial_type"])
        else:
            rows = []
            for a in annotations:
                rows.append({
                    "onset":      a.get("onset", 0),
                    "duration":   a.get("duration", "n/a"),
                    "time_abs":   a.get("time_abs", "n/a"),
                    "time_rel":   a.get("time_rel", "n/a"),
                    "trial_type": a.get("description", "n/a"),
                })
            df = pd.DataFrame(rows).sort_values("onset").reset_index(drop=True)

        df.to_csv(filepath, sep="\t", index=False, na_rep="n/a", float_format="%.3f")
        return filepath
# ============================================================================
# EDF De-identification and Copying
# ============================================================================

class EDFProcessor:
    """Process EDF files: copy, de-identify, extract annotations."""

    def __init__(self, config):
        self.config = config

    def copy_and_deidentify(self, source_path, dest_path, subject_id, callback=None):
        """
        Copy EDF/BDF file to destination and anonymize.

        Updated behavior:
        - Writes a new anonymized file to dest_path using shared anonymizer:
          * scrubs header patient/recording fields
          * blanks embedded annotation channels at the binary level (EDF+/BDF+ TAL)

        Preserves the outward behavior of returning dest_path.
        """
        if callback:
            callback("Copying + anonymizing EDF/BDF file...")

        os.makedirs(os.path.dirname(dest_path), exist_ok=True)

        ok = anonymize_edf_file(
            source_path,
            dest_path,
            patient_field="X X X X",
            recording_field="Startdate X X X X",
            blank_annotations=True,
            buffer_mb=64,
            log_dir=self.config.get("general", {}).get("log_dir") if isinstance(self.config, dict) else None,
        )
        if not ok:
            raise RuntimeError(f"Failed to anonymize EDF/BDF during copy: {source_path}")

        return dest_path

    def _deidentify_header(self, filepath, subject_id):
        """Remove PHI from EDF header (legacy header-only overwrite)."""
        with open(filepath, 'r+b') as f:
            f.seek(8)
            # Overwrite patient ID field (80 bytes)
            f.write(padtrim('X X X X', 80))
            # Overwrite recording ID field (80 bytes)
            f.write(padtrim('Startdate X X X X', 80))

    def blank_annotations(self, filepath, callback=None):
        """
        Return a "blanked" annotation list (does NOT modify EDF on disk here).
        Keeps compatibility with earlier code paths that expect blank descriptions.
        """
        if callback:
            callback("Blanking EDF annotations (logical blanking).")

        try:
            annotations = self.extract_annotations(filepath)
            for a in annotations:
                a["description"] = " "
            return annotations
        except Exception as e:
            raise (e)



    def _read_edf_header_simple(self, filepath):
        """
        Read EDF header without strict validation (compatible with prv_helpers approach).
        Returns dict with meas_info and chan_info needed for annotation extraction.
        """
        meas_info = {}
        chan_info = {}
        
        if filepath.lower().endswith(".edf"):
            fid = open(filepath, "rb")
        elif filepath.lower().endswith(".edfz") or filepath.lower().endswith(".edf.gz"):
            fid = gzip.open(filepath, "rb")
        else:
            fid = open(filepath, "rb")
        
        try:
            fid.seek(0)
            meas_info['magic'] = fid.read(8).strip().decode()
            fid.read(80)  # subject_id - skip
            fid.read(80)  # recording_id - skip
            
            # Date/time
            date_str = fid.read(8).decode()
            time_str = fid.read(8).decode()
            day, month, year = [int(x) for x in re.findall(r'(\d+)', date_str)]
            hour, minute, second = [int(x) for x in re.findall(r'(\d+)', time_str)]
            
            # Handle Y2K: years < 85 are 2000s, >= 85 are 1900s
            if year < 85:
                year += 2000
            else:
                year += 1900
            
            meas_info['meas_date'] = datetime(year, month, day, hour, minute, second)
            meas_info['millisecond'] = 0.0  # Will be updated if found in first TAL
            
            meas_info['data_offset'] = int(fid.read(8).decode())
            
            subtype = fid.read(44).strip().decode()[:5]
            if subtype in ('24BIT', 'bdf'):
                meas_info['data_size'] = 3
            else:
                meas_info['data_size'] = 2
            
            meas_info['n_records'] = int(fid.read(8).decode())
            meas_info['record_length'] = float(fid.read(8).decode())
            if meas_info['record_length'] == 0:
                meas_info['record_length'] = 1.0
            
            meas_info['nchan'] = nchan = int(fid.read(4).decode())
            
            # Channel info
            chan_info['ch_names'] = [fid.read(16).strip().decode() for _ in range(nchan)]
            fid.read(80 * nchan)  # transducers - skip
            fid.read(8 * nchan)   # units - skip
            fid.read(8 * nchan)   # physical_min - skip
            fid.read(8 * nchan)   # physical_max - skip
            fid.read(8 * nchan)   # digital_min - skip
            fid.read(8 * nchan)   # digital_max - skip
            fid.read(80 * nchan)  # prefiltering - skip
            chan_info['n_samps'] = [int(fid.read(8).decode()) for _ in range(nchan)]
            
        finally:
            fid.close()
        
        return {'meas_info': meas_info, 'chan_info': chan_info}

    def _read_all_annotations_regex(self, filepath, header, tal_indx):
        """
        Read all annotations from EDF file in a single pass (optimized).
        Opens file once, reads all annotation blocks, then closes.
        """
        # Pre-compile regex for speed
        pat = re.compile(r'([+-]\d+\.?\d*)(\x15(\d+\.?\d*))?(\x14.*?)\x14\x00')
        all_annotations = []
        
        n_records = header['meas_info']['n_records']
        data_offset = header['meas_info']['data_offset']
        data_size = header['meas_info']['data_size']
        n_samps = header['chan_info']['n_samps']
        
        # Pre-calculate constants
        blocksize = sum(n_samps) * data_size
        annot_offset_in_block = sum(n_samps[:tal_indx]) * data_size
        annot_bytes = n_samps[tal_indx] * data_size
        
        # Progress indicator setup
        progress_interval = max(1, n_records // 1000)
        
        if filepath.lower().endswith(".edf"):
            fid = open(filepath, 'rb')
        elif filepath.lower().endswith(".edfz") or filepath.lower().endswith(".edf.gz"):
            fid = gzip.open(filepath, 'rb')
        else:
            fid = open(filepath, 'rb')
        
        try:
            for block in range(n_records):
                # Seek directly to annotation channel in this block
                fid.seek(data_offset + (block * blocksize) + annot_offset_in_block)
                
                # Read only the annotation channel bytes
                buf = fid.read(annot_bytes)
                
                raw = pat.findall(buf.decode('latin-1', errors='ignore'))
                if raw:
                    all_annotations.append([[*x, block] for x in raw])
                
                # Print progress
                if (block + 1) % progress_interval == 0 or block == n_records - 1:
                    pct = (((block + 1) / n_records) * 100)
                    print(f"\rExtracting annotations: {pct:6.2f}% ({block + 1}/{n_records} records)", end="", flush=True)
            
            print()  # Newline after progress completes
            
        finally:
            fid.close()
        
        return all_annotations

    def _read_annotations_apply_offset(self, triggers):
        """
        Apply time offset to annotations (from prv_helpers).
        The first TAL onset indicates fractional seconds offset from header start time.
        """
        events = []
        offset = 0.0
        
        for k, ev in enumerate(triggers):
            onset = float(ev[0]) + offset
            duration = float(ev[2]) if ev[2] else 0.0
            
            for description in ev[3].split('\x14')[1:]:
                if description:
                    events.append([onset, duration, description, ev[4]])
                elif k == 0:
                    # First TAL with no description: this is the fractional offset
                    offset = -onset
        
        return events if events else []

    def extract_annotations(self, filepath):
        """
        Extract annotations from EDF+ file using regex-based TAL parsing.
        
        This approach (from prv_helpers) reads annotation blocks directly without
        strict timing validation, making it compatible with files that have minor
        timing drift between data records.

        Filters out EDF+ "empty/housekeeping" TAL entries that often appear as:
          - duration == 0 or missing
          - description is empty or contains only non-printable control chars
        """
        def _clean_desc(desc):
            if desc is None:
                return ""
            s = str(desc)
            s = "".join(ch for ch in s if ch.isprintable())
            s = s.strip()
            return s

        try:
            # Read header using simple approach (no strict validation)
            header = self._read_edf_header_simple(filepath)
            
            # Find annotation channel index
            tal_indx = None
            for i, name in enumerate(header['chan_info']['ch_names']):
                if name.endswith('Annotations') or 'EDF Annotation' in name:
                    tal_indx = i
                    break
            
            if tal_indx is None:
                # No annotation channel found - return empty list
                return []
            
            # Read all annotation blocks in single pass (optimized)
            raw_annotations = self._read_all_annotations_regex(filepath, header, tal_indx)
            
            # Flatten and apply offset
            flat_annotations = [item for sublist in raw_annotations for item in sublist]
            events = self._read_annotations_apply_offset(flat_annotations)
            
            # Get start datetime for absolute times
            start_dt = header['meas_info']['meas_date']
            ms_offset = header['meas_info'].get('millisecond', 0.0)
            
            # Process into final format
            annotations = []
            seen = set()
            
            for ev in events:
                onset_sec = ev[0]
                duration = ev[1]
                description = ev[2]
                
                desc_clean = _clean_desc(description)
                
                if desc_clean == "":
                    continue
                
                # Duration handling
                if duration == 0 or duration is None:
                    dur_display = "n/a"
                else:
                    dur_display = round(float(duration), 6)
                
                # De-dupe exact repeats
                key = (round(onset_sec, 6), str(duration), desc_clean)
                if key in seen:
                    continue
                seen.add(key)
                
                # Absolute time
                time_abs = "n/a"
                if start_dt is not None:
                    try:
                        time_abs = (start_dt + timedelta(seconds=onset_sec + ms_offset)).strftime("%H:%M:%S.%f")
                    except Exception:
                        time_abs = "n/a"
                
                annotations.append({
                    "onset": onset_sec,
                    "duration": dur_display,
                    "description": desc_clean,
                    "time_abs": time_abs,
                    "time_rel": sec2time(onset_sec, 6),
                })
            
            return annotations

        except Exception as e:
            raise(e)

# ============================================================================
# PHI Redaction for TSV Files
# ============================================================================

class PHIRedactor:
    """Handle PHI redaction for TSV files."""
    
    def __init__(self, config):
        self.config = config
        self.model_path = self._get_model_path()
        self.available = self._check_model_available()
    
    def _get_model_path(self):
        """Get path to PHI redactor model."""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        model_folder = self.config['general'].get('phi_redactor_model_path', 'phi_redactor_model')
        return os.path.join(script_dir, model_folder)
    
    def _check_model_available(self):
        """Check if PHI redactor model is available."""
        return os.path.exists(self.model_path) and os.path.isdir(self.model_path)
    
    def redact_tsv(self, input_path, output_path):
        """Redact PHI from TSV file using model."""
        if not self.available:
            return False, "PHI redactor model not available"
        
        try:
            cmd = [
                sys.executable,
                "phi_redactor.py",
                "predict",
                "--checkpoint", self.model_path,
                "--input_tsv", input_path,
                "--output_tsv", output_path
            ]
            
            subprocess.run(cmd, check=True, capture_output=True)
            
            # Check if content changed
            if file_hash(input_path) == file_hash(output_path):
                return False, "No PHI detected"
            
            return True, "Redaction successful"
            
        except subprocess.CalledProcessError as e:
            raise(e)
            return False, f"Redaction failed: {e}"
        except Exception as e:
            raise(e)
            return False, f"Redaction error: {e}"


# ============================================================================
# Main Conversion Logic
# ============================================================================

class EDF2BIDSConverter:
    """Main converter class."""
    
    def __init__(self, config, callback=None, file_progress_callback=None):
        self.config = config
        self.callback = callback or (lambda x: print(x))
        self.file_progress_callback = file_progress_callback  # fn(edf_dest, input_size_bytes)
        self.bids_writer = None
        self.edf_processor = EDFProcessor(config)
        self.phi_redactor = PHIRedactor(config)
    
    def log(self, message):
        """Log message through callback."""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.callback(f"[{timestamp}] {message}")
    
    def _write_input_sidecar(self, edf_path, success, logs):
        """Write .edf_bidsified or .edf_bidfailed next to the source EDF."""
        base_name = os.path.splitext(edf_path)[0]
        bidsified_file = f"{base_name}.edf_bidsified"
        failed_file = f"{base_name}.edf_bidfailed"

        log_content = "\n".join(logs)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if success:
            with open(bidsified_file, "w", encoding="utf-8") as f:
                f.write("Conversion successful\n")
                f.write(f"Timestamp: {timestamp}\n")
                f.write(f"---\n{log_content}\n")
            # optional: remove failed marker if it exists
            if os.path.exists(failed_file):
                os.remove(failed_file)
        else:
            with open(failed_file, "w", encoding="utf-8") as f:
                f.write("Conversion failed\n")
                f.write(f"Timestamp: {timestamp}\n")
                f.write(f"---\n{log_content}\n")
            # optional: remove success marker if it exists
            if os.path.exists(bidsified_file):
                os.remove(bidsified_file)    
                
    def convert_single_edf(self, edf_path, output_path, subject_id=None, 
                           session_id=None, deidentify=True, dry_run=False,
                           redact_tsv=False):
        """Convert a single EDF file to BIDS format."""
        logs = []
        
        try:
            self.log(f"Processing: {edf_path}")
            logs.append(f"Input: {edf_path}")
            
            # Extract EDF info
            edf_info_obj = EDFInfo(edf_path, self.config)
            edf_info = edf_info_obj.info
            
            # Determine subject ID if not provided
            if not subject_id:
                # Try to extract from folder name or filename
                parent_dir = os.path.basename(os.path.dirname(edf_path))
                if parent_dir.startswith('sub-'):
                    subject_id = parent_dir
                else:
                    subject_id = f'sub-{parent_dir}'
            
            if not subject_id.startswith('sub-'):
                subject_id = f'sub-{subject_id}'
            
            # Determine session ID
            if not session_id:
                session_id = self._get_next_session(output_path, subject_id)
            
            if not session_id.startswith('ses-'):
                session_id_full = f'ses-{session_id}'
            else:
                session_id_full = session_id
                session_id = session_id.replace('ses-', '')
            
            logs.append(f"Subject: {subject_id}")
            logs.append(f"Session: {session_id_full}")
            
            # Determine kind (ieeg or eeg)
            kind = 'ieeg' if edf_info['RecordingType'] == 'iEEG' else 'eeg'
            task_id = edf_info['RecordingLength']
            run_num = '01'
            
            if dry_run:
                self.log("DRY RUN - no files will be written")
                logs.append("DRY RUN - no files written")
                return True, logs
            
            # Initialize BIDS writer
            self.bids_writer = BIDSWriter(output_path, self.config)
            
            # Create folders
            self.bids_writer.make_bids_folders(subject_id, session_id, kind)
            
            # Write dataset description and README
            self.bids_writer.write_dataset_description()
            self.bids_writer.write_readme()
            
            # Write participants
            self.bids_writer.write_participants(
                subject_id,
                age='n/a',
                sex=edf_info.get('Gender', 'X'),
                group='patient'
            )
            
            # Construct output filename
            edf_filename = f'{subject_id}_{session_id_full}_task-{task_id}_run-{run_num}_{kind}.edf'
            edf_dest = os.path.join(
                output_path, subject_id, session_id_full, kind, edf_filename
            )
            
            # ---------------------------------------------------------------
            # Extract annotations from the ORIGINAL file BEFORE any stripping
            # so that events.tsv has full content regardless of deidentify mode.
            # ---------------------------------------------------------------
            annotations = self.edf_processor.extract_annotations(edf_path)
            logs.append(f"Extracted {len(annotations)} annotations from source EDF")

            # Write events.tsv now (from original annotations)
            events_path = edf_dest.replace(f'_{kind}.edf', '_events.tsv')
            self.bids_writer.write_events(events_path, annotations)
            logs.append(f"Events: {events_path}")

            # Notify GUI of the output path + source size so it can poll progress
            if self.file_progress_callback:
                self.file_progress_callback(edf_dest, os.path.getsize(edf_path))

            # Copy and de-identify EDF (annotations blanked inside anonymizer)
            if deidentify:
                self.edf_processor.copy_and_deidentify(edf_path, edf_dest, subject_id, self.log)
            else:
                shutil.copy2(edf_path, edf_dest)
            
            logs.append(f"EDF copied to: {edf_dest}")
            
            # Write scans.tsv (session-level, with duration in hours and edf_type)
            acq_time = f"{edf_info['Date']}T{edf_info['Time']}"
            self.bids_writer.write_scans(
                subject_id, session_id_full, edf_filename, acq_time,
                duration_hours=edf_info['TotalRecordTime'],
                edf_type=edf_info.get('EDF_type', 'n/a')
            )
            
            # Write channels.tsv
            channels_path = edf_dest.replace(f'_{kind}.edf', '_channels.tsv')
            self.bids_writer.write_channels(channels_path, edf_info)
            logs.append(f"Channels: {channels_path}")
            
            # Write electrodes.tsv
            electrodes_path = os.path.join(
                output_path, subject_id, session_id_full, kind,
                f'{subject_id}_{session_id_full}_electrodes.tsv'
            )
            self.bids_writer.write_electrodes(electrodes_path, edf_info)
            logs.append(f"Electrodes: {electrodes_path}")
            
            # Write sidecar JSON
            json_path = edf_dest.replace('.edf', '.json')
            self.bids_writer.write_sidecar_json(json_path, edf_info)
            logs.append(f"Sidecar JSON: {json_path}")
            
            # PHI Redaction for TSV files
            if redact_tsv:
                tsv_files = [channels_path, electrodes_path, events_path]
                redaction_performed = False
                
                for tsv_file in tsv_files:
                    if os.path.exists(tsv_file):
                        success, msg = self._redact_and_backup_tsv(
                            tsv_file, output_path, subject_id, session_id_full, kind
                        )
                        if success:
                            redaction_performed = True
                            logs.append(f"Redacted: {os.path.basename(tsv_file)}")
                
                if not self.phi_redactor.available and redact_tsv:
                    # Move to PHI folder if redaction requested but not available
                    self._move_to_phi_folder(output_path, subject_id, session_id_full)
                    logs.append("WARNING: PHI redaction unavailable - moved to PHI folder")
            
            self.log(f"Conversion complete: {subject_id}/{session_id_full}")
            logs.append("Conversion successful")
            self._write_input_sidecar(edf_path, success=True, logs=logs)
            
            return True, logs
            
        except Exception as e:
            error_msg = f"Conversion failed: {e}"
            self.log(error_msg)
            logs.append(error_msg)

            # write marker next to source EDF
            self._write_input_sidecar(edf_path, success=False, logs=logs)
            raise(e)

            return False, logs            
    
    def _get_next_session(self, output_path, subject_id):
        """Determine next session number for a subject."""
        subject_path = os.path.join(output_path, subject_id)
        
        if not os.path.exists(subject_path):
            return '001'
        
        # Find existing sessions
        sessions = [d for d in os.listdir(subject_path) 
                   if os.path.isdir(os.path.join(subject_path, d)) and d.startswith('ses-')]
        
        if not sessions:
            return '001'
        
        # Extract session numbers and find max
        session_nums = []
        for s in sessions:
            match = re.search(r'ses-(\d+)', s)
            if match:
                session_nums.append(int(match.group(1)))
        
        next_num = max(session_nums) + 1 if session_nums else 1
        return str(next_num).zfill(3)
    
    def _redact_and_backup_tsv(self, tsv_path, output_path, subject_id, session_id, kind):
        """Redact TSV file and backup original to PHI folder."""
        if not self.phi_redactor.available:
            return False, "Model not available"
        
        # Create temp file for redacted output
        with tempfile.NamedTemporaryFile(suffix='.tsv', delete=False) as tmp:
            tmp_path = tmp.name
        
        try:
            success, msg = self.phi_redactor.redact_tsv(tsv_path, tmp_path)
            
            if success:
                # Create PHI backup folder
                phi_folder = os.path.join(
                    output_path, f'{subject_id}_PHI', session_id, kind
                )
                os.makedirs(phi_folder, exist_ok=True)
                
                # Move original to PHI folder
                backup_path = os.path.join(phi_folder, os.path.basename(tsv_path))
                shutil.move(tsv_path, backup_path)
                
                # Move redacted to original location
                shutil.move(tmp_path, tsv_path)
                
                return True, "Redacted and backed up"
            else:
                os.unlink(tmp_path)
                return False, msg
                
        except Exception as e:
            raise(e)
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            return False, str(e)
    
    def _move_to_phi_folder(self, output_path, subject_id, session_id):
        """Move entire session to PHI folder (when redaction unavailable)."""
        src = os.path.join(output_path, subject_id, session_id)
        dst = os.path.join(output_path, f'{subject_id}_PHI', session_id)
        
        if os.path.exists(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)


# ============================================================================
# Resident Mode (Folder Watcher)
# ============================================================================

class ResidentWatcher:
    """Watch folder for new EDF files to convert."""
    
    def __init__(self, input_path, output_path, config, callback=None):
        self.input_path = input_path
        self.output_path = output_path
        self.config = config
        self.callback = callback or (lambda x: print(x))
        self.running = False
        self.scan_interval = config['general'].get('resident_scan_interval_seconds', 30)
        self.converter = EDF2BIDSConverter(config, callback)
    
    def log(self, message):
        """Log message."""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.callback(f"[{timestamp}] {message}")
    
    def start(self, deidentify=True, redact_tsv=False):
        """Start watching folder."""
        self.running = True
        self.log(f"Starting resident mode - watching: {self.input_path}")
        self.log(f"Output directory: {self.output_path}")
        self.log(f"Scan interval: {self.scan_interval} seconds")
        
        while self.running:
            try:
                self._scan_and_process(deidentify, redact_tsv)
            except Exception as e:
                raise(e)
                self.log(f"Error during scan: {e}")
            
            time.sleep(self.scan_interval)
    
    def stop(self):
        """Stop watching."""
        self.running = False
        self.log("Stopping resident mode")
    
    def _scan_and_process(self, deidentify, redact_tsv):
        """Scan for new files and process them."""
        # Look for sub-### folders
        if not os.path.exists(self.input_path):
            return
        
        for item in os.listdir(self.input_path):
            item_path = os.path.join(self.input_path, item)
            
            if not os.path.isdir(item_path):
                continue
            
            # Check if it's a subject folder
            if not item.startswith('sub-'):
                continue
            
            subject_id = item
            
            # Look for EDF files with edf_pass sidecar
            for filename in os.listdir(item_path):
                if not filename.lower().endswith('.edf'):
                    continue
                
                edf_path = os.path.join(item_path, filename)
                base_name = filename[:-4]  # Remove .edf
                
                pass_file = os.path.join(item_path, f'{base_name}.edf_pass')
                bidsified_file = os.path.join(item_path, f'{base_name}.edf_bidsified')
                failed_file = os.path.join(item_path, f'{base_name}.edf_bidfailed')
                
                # Check if already processed
                if os.path.exists(bidsified_file) or os.path.exists(failed_file):
                    continue
                
                # Check if pass file exists
                if not os.path.exists(pass_file):
                    continue
                
                # Process this file
                self.log(f"Found new file to process: {filename}")
                
                success, logs = self.converter.convert_single_edf(
                    edf_path=edf_path,
                    output_path=self.output_path,
                    subject_id=subject_id,
                    deidentify=deidentify,
                    redact_tsv=redact_tsv
                )
                
                # Write result sidecar
                log_content = '\n'.join(logs)
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                if success:
                    with open(bidsified_file, 'w') as f:
                        f.write(f"Conversion successful\n")
                        f.write(f"Timestamp: {timestamp}\n")
                        f.write(f"---\n{log_content}")
                    self.log(f"Successfully processed: {filename}")
                else:
                    with open(failed_file, 'w') as f:
                        f.write(f"Conversion failed\n")
                        f.write(f"Timestamp: {timestamp}\n")
                        f.write(f"---\n{log_content}")
                    self.log(f"Failed to process: {filename}")


# ============================================================================
# GUI
# ============================================================================

class EDF2BIDSGUI:
    """Tkinter GUI for EDF to BIDS conversion."""
    
    def __init__(self):
        self.config = load_config()
        self.root = tk.Tk()
        self.root.title("EDF to BIDS Converter")
        self.root.geometry("700x550")
        self.root.resizable(True, True)
        
        self.input_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.deidentify = tk.BooleanVar(value=True)
        self.redact_tsv = tk.BooleanVar(value=False)
        self.dry_run = tk.BooleanVar(value=False)
        self.resident_mode = tk.BooleanVar(value=False)
        
        self.converter = None
        self.watcher = None
        self.watcher_thread = None

        # Progress tracking state
        self._total_bytes = 0          # total bytes across all queued EDF files
        self._processed_bytes = 0      # bytes from fully-completed files
        self._current_file_size = 0    # size of the file currently being written
        self._current_output_path = None  # output .edf path being written right now
        self._poll_active = False      # controls the file-poll loop

        self._create_widgets()
    
    def _create_widgets(self):
        """Create GUI widgets."""
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky="nsew")
        
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        # Input folder
        ttk.Label(main_frame, text="Input Folder:").grid(row=0, column=0, sticky="w", pady=5)
        ttk.Entry(main_frame, textvariable=self.input_dir, width=50).grid(row=0, column=1, sticky="ew", pady=5, padx=5)
        ttk.Button(main_frame, text="Browse", command=self._browse_input).grid(row=0, column=2, pady=5)
        
        # Output folder
        ttk.Label(main_frame, text="Output Folder:").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(main_frame, textvariable=self.output_dir, width=50).grid(row=1, column=1, sticky="ew", pady=5, padx=5)
        ttk.Button(main_frame, text="Browse", command=self._browse_output).grid(row=1, column=2, pady=5)
        
        # Options frame
        options_frame = ttk.LabelFrame(main_frame, text="Options", padding="5")
        options_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=10)
        
        ttk.Checkbutton(options_frame, text="De-identify EDF files", variable=self.deidentify).grid(row=0, column=0, sticky="w", padx=10)
        ttk.Checkbutton(options_frame, text="Redact PHI from TSV files", variable=self.redact_tsv).grid(row=0, column=1, sticky="w", padx=10)
        ttk.Checkbutton(options_frame, text="Dry run (no files written)", variable=self.dry_run).grid(row=1, column=0, sticky="w", padx=10)
        ttk.Checkbutton(options_frame, text="Resident mode (watch folder)", variable=self.resident_mode).grid(row=1, column=1, sticky="w", padx=10)
        
        # Buttons frame
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=3, column=0, columnspan=3, pady=10)
        
        self.convert_btn = ttk.Button(button_frame, text="Convert", command=self._start_conversion)
        self.convert_btn.pack(side="left", padx=5)
        
        self.stop_btn = ttk.Button(button_frame, text="Stop", command=self._stop_conversion, state="disabled")
        self.stop_btn.pack(side="left", padx=5)
        
        # ── Progress bars ──────────────────────────────────────────────────────
        progress_frame = ttk.LabelFrame(main_frame, text="Progress", padding="5")
        progress_frame.grid(row=4, column=0, columnspan=3, sticky="ew", pady=5)
        progress_frame.columnconfigure(1, weight=1)

        # Queue (total)
        ttk.Label(progress_frame, text="Queue:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.queue_progress = ttk.Progressbar(progress_frame, mode='determinate', maximum=100)
        self.queue_progress.grid(row=0, column=1, sticky="ew")
        self.queue_label = ttk.Label(progress_frame, text="–", width=18, anchor="e")
        self.queue_label.grid(row=0, column=2, sticky="e", padx=(6, 0))

        # Current file
        ttk.Label(progress_frame, text="Current file:").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(4, 0))
        self.file_progress = ttk.Progressbar(progress_frame, mode='determinate', maximum=100)
        self.file_progress.grid(row=1, column=1, sticky="ew", pady=(4, 0))
        self.file_label = ttk.Label(progress_frame, text="–", width=18, anchor="e")
        self.file_label.grid(row=1, column=2, sticky="e", padx=(6, 0), pady=(4, 0))
        
        # Status/Log
        ttk.Label(main_frame, text="Log:").grid(row=5, column=0, sticky="nw", pady=5)
        
        log_frame = ttk.Frame(main_frame)
        log_frame.grid(row=6, column=0, columnspan=3, sticky="nsew", pady=5)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(6, weight=1)
        
        self.log_text = tk.Text(log_frame, height=15, width=80, wrap="word")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)
        
        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, relief="sunken", anchor="w")
        status_bar.grid(row=7, column=0, columnspan=3, sticky="ew", pady=5)
    
    def _browse_input(self):
        """Browse for input folder."""
        path = filedialog.askdirectory(title="Select Input Folder")
        if path:
            self.input_dir.set(path)
    
    def _browse_output(self):
        """Browse for output folder."""
        path = filedialog.askdirectory(title="Select Output Folder")
        if path:
            self.output_dir.set(path)
    
    def _log(self, message):
        """Add message to log."""
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.root.update_idletasks()
    
    def _start_conversion(self):
        """Start conversion process."""
        if not self.input_dir.get():
            messagebox.showerror("Error", "Please select an input folder.")
            return
        if not self.output_dir.get():
            messagebox.showerror("Error", "Please select an output folder.")
            return
        
        self.convert_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_var.set("Processing...")
        
        if self.resident_mode.get():
            # Start resident mode in thread
            self.watcher = ResidentWatcher(
                self.input_dir.get(),
                self.output_dir.get(),
                self.config,
                callback=self._log
            )
            self.watcher_thread = threading.Thread(
                target=self.watcher.start,
                args=(self.deidentify.get(), self.redact_tsv.get()),
                daemon=True
            )
            self.watcher_thread.start()
            self._log("Resident mode started - watching for new files...")
        else:
            # Batch conversion
            threading.Thread(target=self._run_batch_conversion, daemon=True).start()
    
    def _run_batch_conversion(self):
        """Run batch conversion with dual progress tracking."""
        try:
            input_path  = self.input_dir.get()
            output_path = self.output_dir.get()

            # ── 1. Discover all EDF files and compute total queue size ────────
            edf_queue = []  # list of (subject_id, edf_path)
            for item in sorted(os.listdir(input_path)):
                item_path = os.path.join(input_path, item)
                if not os.path.isdir(item_path):
                    continue
                subject_id = item if item.startswith('sub-') else f'sub-{item}'
                for filename in sorted(os.listdir(item_path)):
                    if filename.lower().endswith('.edf'):
                        edf_queue.append((subject_id, os.path.join(item_path, filename)))

            self._total_bytes     = sum(os.path.getsize(p) for _, p in edf_queue)
            self._processed_bytes = 0
            self._current_file_size   = 0
            self._current_output_path = None

            # Initialise queue bar label
            self.root.after(0, self._refresh_queue_label)
            self.root.after(0, lambda: self.queue_progress.configure(value=0))
            self.root.after(0, lambda: self.file_progress.configure(value=0))
            self.root.after(0, lambda: self.file_label.configure(text="–"))

            # ── 2. Start file-level poll loop ─────────────────────────────────
            self._poll_active = True
            threading.Thread(target=self._poll_file_progress, daemon=True).start()

            # ── 3. Convert each file ──────────────────────────────────────────
            self.converter = EDF2BIDSConverter(
                self.config,
                callback=self._log,
                file_progress_callback=self._on_file_start
            )

            for subject_id, edf_path in edf_queue:
                file_size = os.path.getsize(edf_path)
                self.converter.convert_single_edf(
                    edf_path=edf_path,
                    output_path=output_path,
                    subject_id=subject_id,
                    deidentify=self.deidentify.get(),
                    dry_run=self.dry_run.get(),
                    redact_tsv=self.redact_tsv.get()
                )
                # File done → credit its full size to processed total
                self._processed_bytes += file_size
                self._current_output_path = None
                self.root.after(0, self._refresh_queue_label)

            self.root.after(0, self._log, "Batch conversion complete!")
            self.root.after(0, self.status_var.set, "Complete")

        except Exception as e:
            self.root.after(0, self._log, f"Batch conversion failed: {e}")
            self.root.after(0, self.status_var.set, "Error")
        finally:
            self._poll_active = False
            self.root.after(0, self._conversion_complete)

    # ── Progress helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _fmt_gb(n_bytes):
        """Format bytes as a human-readable GB string."""
        gb = n_bytes / (1024 ** 3)
        if gb >= 0.1:
            return f"{gb:.2f} GB"
        mb = n_bytes / (1024 ** 2)
        return f"{mb:.0f} MB"

    def _on_file_start(self, edf_dest, input_size_bytes):
        """Called by the converter just before copying a file."""
        self._current_file_size   = input_size_bytes
        self._current_output_path = edf_dest

    def _poll_file_progress(self):
        """Background thread: polls output file size every 0.5 s to drive both bars."""
        while self._poll_active:
            out_path  = self._current_output_path
            file_size = self._current_file_size

            # ── current-file bar ─────────────────────────────────────────────
            if out_path and file_size > 0 and os.path.exists(out_path):
                written   = os.path.getsize(out_path)
                pct_file  = min(100.0, written / file_size * 100)
                remaining = max(0, file_size - written)
                lbl_file  = f"{self._fmt_gb(written)} / {self._fmt_gb(file_size)}"
            else:
                pct_file  = 0.0
                lbl_file  = "–"

            # ── queue bar ────────────────────────────────────────────────────
            if self._total_bytes > 0:
                # credit finished files + fraction of current file
                partial    = (os.path.getsize(out_path)
                              if (out_path and os.path.exists(out_path)) else 0)
                done_bytes = self._processed_bytes + partial
                pct_queue  = min(100.0, done_bytes / self._total_bytes * 100)
                remaining_total = max(0, self._total_bytes - done_bytes)
                lbl_queue  = f"{self._fmt_gb(remaining_total)} remaining"
            else:
                pct_queue = 0.0
                lbl_queue = "–"

            # Push to UI on the main thread
            self.root.after(0, lambda p=pct_file:  self.file_progress.configure(value=p))
            self.root.after(0, lambda t=lbl_file:   self.file_label.configure(text=t))
            self.root.after(0, lambda p=pct_queue:  self.queue_progress.configure(value=p))
            self.root.after(0, lambda t=lbl_queue:  self.queue_label.configure(text=t))

            time.sleep(0.5)

    def _refresh_queue_label(self):
        """Recalculate and refresh the queue bar from main thread."""
        if self._total_bytes > 0:
            pct = min(100.0, self._processed_bytes / self._total_bytes * 100)
            remaining = max(0, self._total_bytes - self._processed_bytes)
            self.queue_progress.configure(value=pct)
            self.queue_label.configure(text=f"{self._fmt_gb(remaining)} remaining")
        else:
            self.queue_progress.configure(value=0)
            self.queue_label.configure(text="–")
            
   
    def _stop_conversion(self):
        """Stop conversion process."""
        if self.watcher:
            self.watcher.stop()
            self._log("Stopping resident mode...")
        
        self._conversion_complete()
    
    def _conversion_complete(self):
        """Handle conversion completion."""
        self._poll_active = False
        # Snap bars to 100 % if everything finished, else leave where they are
        if self.status_var.get() != "Error":
            self.queue_progress.configure(value=100)
            self.queue_label.configure(text="0 MB remaining")
            self.file_progress.configure(value=100)
        self.convert_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        if self.status_var.get() == "Processing...":
            self.status_var.set("Ready")
    
    def run(self):
        """Run the GUI."""
        self.root.mainloop()


# ============================================================================
# CLI
# ============================================================================

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Convert EDF files to BIDS format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Batch conversion
  python edf2bids.py --input /path/to/input --output /path/to/output
  
  # With options
  python edf2bids.py --input /data/raw --output /data/bids --deidentify --redact-tsv
  
  # Dry run
  python edf2bids.py --input /data/raw --output /data/bids --dry-run
  
  # Resident mode (watch folder)
  python edf2bids.py --input /data/incoming --output /data/bids --resident
  
  # Launch GUI (no arguments)
  python edf2bids.py
"""
    )
    
    parser.add_argument('--input', '-i', help='Input directory containing subject folders')
    parser.add_argument('--output', '-o', help='Output BIDS directory')
    parser.add_argument('--deidentify', action='store_true', default=True,
                        help='De-identify EDF files (default: True)')
    parser.add_argument('--no-deidentify', action='store_false', dest='deidentify',
                        help='Do not de-identify EDF files')
    parser.add_argument('--redact-tsv', action='store_true', default=False,
                        help='Redact PHI from TSV files using model')
    parser.add_argument('--dry-run', action='store_true', default=False,
                        help='Perform dry run without writing files')
    parser.add_argument('--resident', action='store_true', default=False,
                        help='Run in resident mode (watch folder for new files)')
    parser.add_argument('--config', help='Path to configuration JSON file')
    
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()
    
    # If no arguments, launch GUI
    if len(sys.argv) == 1:
        gui = EDF2BIDSGUI()
        gui.run()
        return
    
    # CLI mode
    if not args.input or not args.output:
        print("Error: --input and --output are required in CLI mode")
        print("Use 'python edf2bids.py --help' for usage information")
        sys.exit(1)
    
    # Load config
    if args.config and os.path.exists(args.config):
        with open(args.config, 'r') as f:
            config = json.load(f)
    else:
        config = load_config()
    
    def log_callback(msg):
        print(msg)
    
    if args.resident:
        # Resident mode
        watcher = ResidentWatcher(
            args.input, args.output, config, callback=log_callback
        )
        try:
            watcher.start(deidentify=args.deidentify, redact_tsv=args.redact_tsv)
        except KeyboardInterrupt:
            raise(e)
            
            watcher.stop()
            print("\nStopped.")
    else:
        # Batch mode
        converter = EDF2BIDSConverter(config, callback=log_callback)
        
        input_path = args.input
        output_path = args.output
        
        # Find all subject folders
        for item in os.listdir(input_path):
            item_path = os.path.join(input_path, item)
            
            if not os.path.isdir(item_path):
                continue
            
            subject_id = item if item.startswith('sub-') else f'sub-{item}'
            
            # Find EDF files
            for filename in os.listdir(item_path):
                if filename.lower().endswith('.edf'):
                    edf_path = os.path.join(item_path, filename)
                    
                    converter.convert_single_edf(
                        edf_path=edf_path,
                        output_path=output_path,
                        subject_id=subject_id,
                        deidentify=args.deidentify,
                        dry_run=args.dry_run,
                        redact_tsv=args.redact_tsv
                    )
        
        print("Conversion complete!")


if __name__ == '__main__':
    main()
