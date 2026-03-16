# -*- coding: utf-8 -*-
"""
data2bids_main.py
Main application window – PySide6/Qt replaced with tkinter.

All business logic is preserved unchanged.  Only the UI plumbing
(widget creation, signal connections, thread management) has been
adapted to tkinter and the _tk_compat signal-queue pattern.
"""

import sys
import os
import tkinter as tk
from tkinter import filedialog, messagebox
import pandas as pd
import datetime
import shutil
import numpy as np
import json
import re
import gzip

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core._tk_compat import _signal_queue

from widgets import gui_layout
from widgets.gui_layout import TkTreeWidget, TreeWidgetItem, CellComboProxy
from widgets import settings_panel, about_panel, overwrite_type
from core.edf2bids   import edf2bids
from core.bids2spred import bids2spred
from core.dicom2bids import dicom2bids
from core.helpers    import read_input_dir, read_output_dir, bidsHelper, warningBox


# ═══════════════════════════════════════════════════════════════════════
# checkUpdates  (unchanged)
# ═══════════════════════════════════════════════════════════════════════

class checkUpdates:

    def __init__(self, app_info=None):
        super(checkUpdates, self).__init__()
        self.app_info = app_info
        if getattr(sys, 'frozen', False):
            self.application_path = os.path.dirname(sys.argv[0])
        elif __file__:
            self.application_path = os.path.dirname(os.path.realpath(__file__))
        self.credentialFile  = os.path.join(self.application_path, 'static', "mycreds.txt")
        self.folder_title    = 'data2bids'
        self.zipped_title    = 'data2bids_conversion_software'

    def getLatest(self):
        from pydrive.auth  import GoogleAuth
        from pydrive.drive import GoogleDrive
        patt  = re.compile('.{2}.{2}.{4}')
        gauth = GoogleAuth()
        gauth.DEFAULT_SETTINGS['client_config_file'] = os.path.join(
            self.application_path, 'static', 'client_secrets.json')
        gauth.LoadCredentialsFile(self.credentialFile)
        if gauth.credentials is None:
            gauth.GetFlow()
            gauth.flow.params.update({'access_type': 'offline'})
            gauth.flow.params.update({'approval_prompt': 'force'})
            gauth.LocalWebserverAuth()
        elif gauth.access_token_expired:
            gauth.Refresh()
        else:
            gauth.Authorize()
        gauth.SaveCredentialsFile(self.credentialFile)
        drive = GoogleDrive(gauth)
        zipped_file_id = []
        folder_list = drive.ListFile({'q': "'root' in parents and trashed=false"}).GetList()
        for ifolder in folder_list:
            if ifolder['title'] == self.folder_title:
                file_list = drive.ListFile(
                    {'q': f"'{ifolder['id']}' in parents and trashed=false"}).GetList()
                for ifile in file_list:
                    if ifile['title'].startswith(self.zipped_title):
                        tmp = {}
                        tmp['title']   = ifile['title']
                        tmp['id']      = ifile['id']
                        date = patt.findall(os.path.splitext(ifile['title'].split('_')[-1])[0])
                        tmp['version'] = date[0] if isinstance(date, list) else 'N/A'
                        zipped_file_id.append(tmp)
                break
        new_software = None
        for ifile in zipped_file_id:
            if ifile['version'] > self.app_info['date']:
                new_software = ifile
        return new_software


# ═══════════════════════════════════════════════════════════════════════
# MainWindow
# ═══════════════════════════════════════════════════════════════════════

class MainWindow:

    def __init__(self):
        # ── Application paths ────────────────────────────────────────
        if getattr(sys, 'frozen', False):
            self.application_path = os.path.dirname(sys.argv[0])
        elif __file__:
            self.application_path = os.path.dirname(os.path.realpath(__file__))

        self.settings_fname = os.path.join(self.application_path, 'bids_settings.json')

        version_fname = os.path.join(self.application_path, './static/version.json')
        with open(version_fname) as version_file:
            self.app_info = json.load(version_file)

        # ── Create root window ───────────────────────────────────────
        self.root = tk.Tk()

        # ── Build UI (all widget attributes attached to self) ─────────
        gui_layout.Ui_MainWindow().setupUi(self)

        # ── Dialogs ───────────────────────────────────────────────────
        self.settingsPanel      = settings_panel.SettingsDialog(self.root)
        self.overwriteTypePanel = overwrite_type.OverwriteTypeDialog(self.root)
        self.aboutPanel         = about_panel.AboutDialog(self.root, self.app_info)

        # ── Settings & initial state ──────────────────────────────────
        self.bidsSettingsSetup()

        # ── Optional update check ─────────────────────────────────────
        if self.settingsPanel.checkUpdates.isChecked():
            try:
                self.checkUpdates  = checkUpdates(self.app_info)
                latestVersion      = self.checkUpdates.getLatest()
                if latestVersion is not None:
                    messagebox.showinfo(
                        "Newer data2bids version detected",
                        f"A newer version of data2bids has been released\n"
                        f"Current: {self.app_info['date']}\n"
                        f"Newer:   {latestVersion['version']}\n"
                        f"Folder:  {self.app_info.get('driveFolder', '')}"
                    )
            except Exception:
                pass

        self.output_path = None

        # Button colour helpers (mapped to tkinter background colours)
        self.cancel_button_color  = "#ff0000"
        self.pause_button_color   = "#ad7fa8"
        self.spred_button_color   = "#0055ff"
        self.convert_button_color = "#4fe86d"
        self.inactive_color       = "#a0a0a0"

        self.updateStatus("Welcome to data2bids converter. Load your directory.")
        self.sText.setVisible(False)

        self.cancelButton.setEnabled(False)
        self.pauseButton.setEnabled(False)
        self.spredButton.setEnabled(False)
        self.imagingButton.setEnabled(False)

        self.userAborted           = False
        self.eegConversionDone     = False
        self.imagingConversionDone = False
        self.imagingDataPresent    = False

        # ── Signal connections ────────────────────────────────────────
        self.deidentifyInputDir.stateChanged.connect(self.onDeidentifyCheckbox)
        self.offsetDate.stateChanged.connect(self.onOffsetdateCheckbox)
        self.gzipEDF.stateChanged.connect(self.onGzipEDFCheckbox)

        self.settingsPanel.checkUpdates.clicked.connect(self.onUpdatesCheckbox)

        self.loadDirButton.clicked.connect(self.onLoadDirButton)
        self.outDirButton.clicked.connect(self.onOutDirButton)
        self.convertButton.clicked.connect(self.onConvertButton)
        self.spredButton.clicked.connect(self.onSpredButton)
        self.imagingButton.clicked.connect(self.onImagingButton)

        self.actionLoad_data.triggered.connect(self.onLoadDirButton)
        self.actionSettings.triggered.connect(self.onSettingsButton)
        self.settingsPanel.buttonBoxJson.accepted.connect(self.onSettingsAccept)
        self.settingsPanel.buttonBoxJson.rejected.connect(self.onSettingsReject)
        self.actionAbout.triggered.connect(self.onAboutButton)
        self.aboutPanel.closeAboutWindowButton.clicked.connect(self.onCloseAbout)
        self.actionDarkMode.triggered.connect(self.onDarkMode)
        self.actionLightMode.triggered.connect(self.onLightMode)
        self.actionQuit.triggered.connect(self.close)

        self.actionOverwrite_Type.triggered.connect(self.onConvertTypeButton)
        self.overwriteTypePanel.selectFileButton.clicked.connect(self.onLoadFileButton)
        self.overwriteTypePanel.convertButton.clicked.connect(self.onConvertType)

        # ── Start the signal queue poll ───────────────────────────────
        self._poll_signal_queue()

        # ── Close handler ─────────────────────────────────────────────
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    # ── Queue poll (replaces Qt cross-thread signal delivery) ──────────
    def _poll_signal_queue(self):
        """Drain the signal queue and call callbacks in the main thread."""
        try:
            while True:
                cb, args = _signal_queue.get_nowait()
                cb(*args)
        except Exception:
            pass
        self.root.after(100, self._poll_signal_queue)

    # ── Window show / close ────────────────────────────────────────────
    def show(self):
        self.root.mainloop()

    def close(self):
        self.root.destroy()

    # ── Settings helpers ───────────────────────────────────────────────
    def updateSettingsFile(self, settings_dict):
        self.bids_settings = settings_dict
        json_output = json.dumps(self.bids_settings, indent=4)
        with open(self.settings_fname, 'w') as fid:
            fid.write(json_output + '\n')

    def onDarkMode(self):
        pass  # Dark mode theming removed (no qdarkstyle in tkinter port)

    def onLightMode(self):
        self.bids_settings['general']['darkMode'] = False
        self.updateSettingsFile(self.bids_settings)

    def onSettingsReject(self):
        pass

    def onAboutButton(self):
        self.aboutPanel.exec()

    def onCloseAbout(self):
        self.aboutPanel.close()

    def onConvertType(self):
        edf_d_checked = self.overwriteTypePanel.edfD.isChecked()
        edf_c_checked = self.overwriteTypePanel.edfC.isChecked()
        success = None
        if edf_d_checked:
            self.edfC2D(self.overwriteTypePanel.filePath.text())
            success = 'EDF+D'
        elif edf_c_checked:
            self.edfD2C(self.overwriteTypePanel.filePath.text())
            success = 'EDF+C'
        if success is not None:
            if success == 'EDF+D':
                messagebox.showinfo("Success",
                    f"File has been changed to {success}. "
                    "Please open EDFbrowser and use the tool Convert EDF+D to EDF+C.")
            else:
                messagebox.showinfo("Success", f"File has been changed to {success}")
            # Reset radio buttons
            self.overwriteTypePanel.edfD.setChecked(False)
            self.overwriteTypePanel.edfC.setChecked(False)
            self.overwriteTypePanel.filePath.clear()
        else:
            print("Please choose the format type to change the file to.")

    def bidsSettingsSetup(self):
        _default_settings = SettingsDialog_defaults()
        if not os.path.exists(self.settings_fname):
            bids_settings_json_temp = {}
            bids_settings_json_temp['general']       = _default_settings.general
            bids_settings_json_temp['json_metadata'] = _default_settings.ieeg_file_metadata
            bids_settings_json_temp['natus_info']    = _default_settings.natus_info
            bids_settings_json_temp['settings_panel'] = {
                'Deidentify_source': False,
                'offset_dates': False,
                'gzip_edf': True
            }
            self.updateSettingsFile(bids_settings_json_temp)
        else:
            with open(self.settings_fname) as settings_file:
                self.bids_settings = json.load(settings_file)

        if 'general' not in list(self.bids_settings):
            self.bids_settings['general'] = _default_settings.general
            self.updateSettingsFile(self.bids_settings)

        if 'gzip_edf' not in list(self.bids_settings['settings_panel']):
            self.bids_settings['settings_panel']['gzip_edf'] = self.gzipEDF.isChecked()
            self.updateSettingsFile(self.bids_settings)

        self.offsetDate.setChecked(self.bids_settings['settings_panel']['offset_dates'])
        self.settingsPanel.checkUpdates.setChecked(self.bids_settings['general']['checkUpdates'])

    def onDeidentifyCheckbox(self):
        if self.bids_settings['settings_panel']['Deidentify_source'] != self.deidentifyInputDir.isChecked():
            self.bids_settings['settings_panel']['Deidentify_source'] = self.deidentifyInputDir.isChecked()
            self.updateSettingsFile(self.bids_settings)

    def onUpdatesCheckbox(self):
        if self.bids_settings['general']['checkUpdates'] != self.settingsPanel.checkUpdates.isChecked():
            self.bids_settings['general']['checkUpdates'] = self.settingsPanel.checkUpdates.isChecked()
            self.updateSettingsFile(self.bids_settings)

    def onOffsetdateCheckbox(self):
        if self.bids_settings['settings_panel']['offset_dates'] != self.offsetDate.isChecked():
            self.bids_settings['settings_panel']['offset_dates'] = self.offsetDate.isChecked()
            self.updateSettingsFile(self.bids_settings)

    def onGzipEDFCheckbox(self):
        if self.bids_settings['settings_panel']['gzip_edf'] != self.gzipEDF.isChecked():
            self.bids_settings['settings_panel']['gzip_edf'] = self.gzipEDF.isChecked()
            self.updateSettingsFile(self.bids_settings)

    def onConvertTypeButton(self):
        self.overwriteTypePanel.exec()

    def onSettingsButton(self):
        self.settingsPanel.recordingLabels.setText(self.bids_settings['general']['recordingLabels'])
        self.settingsPanel.textboxDatasetName.setText(self.bids_settings['json_metadata']['DatasetName'])
        self.settingsPanel.textboxExperimenter.setText(self.bids_settings['json_metadata']['Experimenter'][0])
        self.settingsPanel.textboxLab.setText(self.bids_settings['json_metadata']['Lab'])
        self.settingsPanel.textboxInstitutionName.setText(self.bids_settings['json_metadata']['InstitutionName'])
        self.settingsPanel.textboxInstitutionAddress.setText(self.bids_settings['json_metadata']['InstitutionAddress'])
        self.settingsPanel.textboxIEEGManufacturer.setText(self.bids_settings['natus_info']['iEEGElectrodeInfo']['Manufacturer'])
        self.settingsPanel.textboxIEEGType.setText(self.bids_settings['natus_info']['iEEGElectrodeInfo']['Type'])
        self.settingsPanel.textboxIEEGMaterial.setText(self.bids_settings['natus_info']['iEEGElectrodeInfo']['Material'])
        self.settingsPanel.textboxIEEGDiameter.setText(str(self.bids_settings['natus_info']['iEEGElectrodeInfo']['Diameter']))
        self.settingsPanel.textboxEEGManufacturer.setText(self.bids_settings['natus_info']['EEGElectrodeInfo']['Manufacturer'])
        self.settingsPanel.textboxEEGType.setText(self.bids_settings['natus_info']['EEGElectrodeInfo']['Type'])
        self.settingsPanel.textboxEEGMaterial.setText(self.bids_settings['natus_info']['EEGElectrodeInfo']['Material'])
        self.settingsPanel.textboxEEGDiameter.setText(str(self.bids_settings['natus_info']['EEGElectrodeInfo']['Diameter']))
        self.settingsPanel.exec()

    def onSettingsAccept(self):
        if self.bids_settings['general']['recordingLabels'] != self.settingsPanel.recordingLabels.text():
            self.bids_settings['general']['recordingLabels'] = self.settingsPanel.recordingLabels.text()
        if self.bids_settings['json_metadata']['DatasetName'] != self.settingsPanel.textboxDatasetName.text():
            self.bids_settings['json_metadata']['DatasetName'] = self.settingsPanel.textboxDatasetName.text()
        if self.bids_settings['json_metadata']['Experimenter'][0] != self.settingsPanel.textboxExperimenter.text():
            self.bids_settings['json_metadata']['Experimenter'] = [self.settingsPanel.textboxExperimenter.text()]
        if self.bids_settings['json_metadata']['Lab'] != self.settingsPanel.textboxLab.text():
            self.bids_settings['json_metadata']['Lab'] = self.settingsPanel.textboxLab.text()
        if self.bids_settings['json_metadata']['InstitutionName'] != self.settingsPanel.textboxInstitutionName.text():
            self.bids_settings['json_metadata']['InstitutionName'] = self.settingsPanel.textboxInstitutionName.text()
        if self.bids_settings['json_metadata']['InstitutionAddress'] != self.settingsPanel.textboxInstitutionAddress.text():
            self.bids_settings['json_metadata']['InstitutionAddress'] = self.settingsPanel.textboxInstitutionAddress.text()
        if self.bids_settings['natus_info']['iEEGElectrodeInfo']['Manufacturer'] != self.settingsPanel.textboxIEEGManufacturer.text():
            self.bids_settings['natus_info']['iEEGElectrodeInfo']['Manufacturer'] = self.settingsPanel.textboxIEEGManufacturer.text()
        if self.bids_settings['natus_info']['iEEGElectrodeInfo']['Type'] != self.settingsPanel.textboxIEEGType.text():
            self.bids_settings['natus_info']['iEEGElectrodeInfo']['Type'] = self.settingsPanel.textboxIEEGType.text()
        if self.bids_settings['natus_info']['iEEGElectrodeInfo']['Material'] != self.settingsPanel.textboxIEEGMaterial.text():
            self.bids_settings['natus_info']['iEEGElectrodeInfo']['Material'] = self.settingsPanel.textboxIEEGMaterial.text()
        if self.bids_settings['natus_info']['iEEGElectrodeInfo']['Diameter'] != self.settingsPanel.textboxIEEGDiameter.text():
            self.bids_settings['natus_info']['iEEGElectrodeInfo']['Diameter'] = self.settingsPanel.textboxIEEGDiameter.text()
        if self.bids_settings['natus_info']['EEGElectrodeInfo']['Manufacturer'] != self.settingsPanel.textboxEEGManufacturer.text():
            self.bids_settings['natus_info']['EEGElectrodeInfo']['Manufacturer'] = self.settingsPanel.textboxEEGManufacturer.text()
        if self.bids_settings['natus_info']['EEGElectrodeInfo']['Type'] != self.settingsPanel.textboxEEGType.text():
            self.bids_settings['natus_info']['EEGElectrodeInfo']['Type'] = self.settingsPanel.textboxEEGType.text()
        if self.bids_settings['natus_info']['EEGElectrodeInfo']['Material'] != self.settingsPanel.textboxEEGMaterial.text():
            self.bids_settings['natus_info']['EEGElectrodeInfo']['Material'] = self.settingsPanel.textboxEEGMaterial.text()
        if self.bids_settings['natus_info']['EEGElectrodeInfo']['Diameter'] != self.settingsPanel.textboxEEGDiameter.text():
            self.bids_settings['natus_info']['EEGElectrodeInfo']['Diameter'] = self.settingsPanel.textboxEEGDiameter.text()
        self.updateSettingsFile(self.bids_settings)

    def onLoadFileButton(self):
        if 'lastConvertTypeDirectory' not in self.bids_settings:
            self.bids_settings['lastConvertTypeDirectory'] = []
            self.updateSettingsFile(self.bids_settings)

        self.overwriteTypePanel.filePath.clear()
        init_dir = self.bids_settings.get('lastConvertTypeDirectory') or '/'
        path = filedialog.askopenfilename(
            title='Select EDF File',
            initialdir=init_dir,
            filetypes=[('EDF files', '*.edf *.EDF')]
        )
        if path:
            self.input_path = path
            self.overwriteTypePanel.filePath.setText(path)
            if path != self.bids_settings.get('lastConvertTypeDirectory'):
                self.bids_settings['lastConvertTypeDirectory'] = path
                self.updateSettingsFile(self.bids_settings)

    # ── Load input directory ────────────────────────────────────────────
    def onLoadDirButton(self):
        if 'lastInputDirectory' not in self.bids_settings:
            self.bids_settings['lastInputDirectory'] = []
            self.updateSettingsFile(self.bids_settings)

        init_dir = self.bids_settings.get('lastInputDirectory') or '/'
        path = filedialog.askdirectory(title='Select Input Directory', initialdir=init_dir)
        if not path:
            return

        self.treeViewLoad.clear()
        self.treeViewOutput.clear()
        self.sText.setVisible(False)
        self.convertButton.setEnabled(True)
        self.cancelButton.setEnabled(False)
        self.pauseButton.setEnabled(False)
        self.spredButton.setEnabled(False)

        self.updateStatus("Loading input directory...")
        self.input_path = path
        if path != self.bids_settings.get('lastInputDirectory'):
            self.bids_settings['lastInputDirectory'] = path
            self.updateSettingsFile(self.bids_settings)

        try:
            self.file_info, self.chan_label_file, self.imaging_data = \
                read_input_dir(self.input_path, self.bids_settings)
        except Exception:
            import traceback
            messagebox.showerror("Error loading directory",
                f"Failed to read input folder:\n\n{traceback.format_exc()}")
            self.updateStatus("Error loading directory.")
            return

        # ── Build the load tree ───────────────────────────────────────
        recording_labels = self.bids_settings['general']['recordingLabels'].split(',')

        # Define headers (must be called before inserting rows)
        headers = [
            self.padentry('Name', 110), self.padentry("Date", 20),
            self.padentry("Time", 14),  self.padentry("Size", 10),
            self.padentry("Frequency", 6), self.padentry("Duration", 9),
            self.padentry("EDF Type", 10), self.padentry('Type', 14),
            self.padentry('Task', 14),     self.padentry('Ret/Pro', 14),
            self.padentry('Channel File', 6), self.padentry('Imaging Data', 6),
            self.padentry('Channel Labels', 20)
        ]
        # Initialise columns once (create a dummy TreeWidgetItem for the header)
        self.treeViewLoad._col_names = headers
        self.treeViewLoad._columns   = [f'col{i}' for i in range(len(headers))]
        self.treeViewLoad._init_tree()

        for isub, values in self.file_info.items():
            parent = self.treeViewLoad.new_item()
            parent.setText(0, str(isub))
            parent.setText(10, 'Yes' if self.chan_label_file[isub] else 'No')
            parent.setText(11, 'Yes' if self.imaging_data[isub]['imaging_dir'] else 'No')
            if self.imaging_data[isub]['imaging_dir']:
                self.imagingDataPresent = True

            for ises in range(len(values)):
                for irun in range(len(values[ises])):
                    v    = values[ises][irun]
                    date = v['Date']
                    time = v['Time']
                    date_collected = datetime.datetime.strptime(
                        ' '.join([date, time]), '%Y-%m-%d %H:%M:%S')

                    child = self.treeViewLoad.new_item(parent)
                    child.setText(0, v['DisplayName'])
                    child.setText(1, str(date_collected.date()))
                    child.setText(2, str(date_collected.time()))
                    child.setText(3, "{:.3f}".format(
                        np.round(os.stat(os.path.join(
                            self.input_path, v['SubDir'], v['FileName']
                        )).st_size / 1e9, 3)))
                    child.setText(4, str(v['SamplingFrequency']))
                    child.setText(5, "{:.3f}".format(v['TotalRecordTime']))
                    child.setText(6, v['EDF_type'])

                    # Embedded comboboxes → CellComboProxy
                    cb_type = CellComboProxy(
                        self.treeViewLoad, child.iid, 'col7',
                        ['iEEG', 'Scalp'], v['RecordingType'])
                    self.treeViewLoad.setItemWidget(child, 7, cb_type)

                    cb_len = CellComboProxy(
                        self.treeViewLoad, child.iid, 'col8',
                        recording_labels, v['RecordingLength'])
                    self.treeViewLoad.setItemWidget(child, 8, cb_len)

                    cb_ret = CellComboProxy(
                        self.treeViewLoad, child.iid, 'col9',
                        ['Ret', 'Pro'], v['Retro_Pro'])
                    self.treeViewLoad.setItemWidget(child, 9, cb_ret)

                    child.setText(10, 'Yes' if v['ses_chan_label'] else 'No')

                    # Channel labels: simple list display
                    chan_type = 'SEEG' if 'SEEG' in list(v['ChanInfo'].keys()) else 'EEG'
                    chan_names = list(v['ChanInfo'][chan_type]['ChanName'])
                    cb_lbl = CellComboProxy(
                        self.treeViewLoad, child.iid, 'col12',
                        chan_names, 'View Labels')
                    self.treeViewLoad.setItemWidget(child, 12, cb_lbl)

        self.updateStatus("Input directory loaded. Select output directory.")

        if all(len(value) == 0 for value in self.file_info.values()):
            self.convertButton.setEnabled(False)

        if not self.imagingDataPresent:
            self.imagingButton.setEnabled(False)

    # ── Double-click inline edit (col 4 = sampling frequency) ──────────
    def checkEdit(self, item, column):
        if column == 4:
            self._inline_edit(self.treeViewLoad, item, column)

    def _inline_edit(self, tree_widget, item, col):
        """Pop up a small entry widget over the cell for inline editing."""
        col_tag = f'col{col}'
        try:
            bbox = tree_widget._tree.bbox(item.iid, col_tag)
        except Exception:
            return
        if not bbox:
            return
        x, y, w, h = bbox
        var = tk.StringVar(value=item.text(col))
        entry = tk.Entry(tree_widget._tree, textvariable=var, font=('Arial', 10))
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()
        entry.select_range(0, 'end')

        def _commit(_event=None):
            item.setText(col, var.get())
            entry.destroy()

        entry.bind('<Return>',   _commit)
        entry.bind('<FocusOut>', _commit)
        entry.bind('<Escape>',   lambda e: entry.destroy())

    # ── Load output directory ───────────────────────────────────────────
    def onOutDirButton(self):
        if 'lastOutputDirectory' not in self.bids_settings:
            self.bids_settings['lastOutputDirectory'] = []
            self.updateSettingsFile(self.bids_settings)

        init_dir = self.bids_settings.get('lastOutputDirectory') or '/'
        path = filedialog.askdirectory(title='Select Output Directory', initialdir=init_dir)
        if not path:
            return

        self.treeViewOutput.clear()
        self.conversionStatus.clear()
        self.sText.setVisible(False)
        self.cancelButton.setEnabled(False)
        self.spredButton.setEnabled(False)
        self.pauseButton.setEnabled(False)

        if not all(len(value) == 0 for value in self.file_info.values()):
            self.convertButton.setEnabled(True)
        if not self.imagingDataPresent:
            self.imagingButton.setEnabled(False)

        padding = 8
        self.updateStatus("Loading output directory...")
        self.output_path = path

        if len(os.listdir(self.output_path)) != 0:
            messagebox.showwarning("Warning", "Output directory is not empty!")
            return

        if path != self.bids_settings.get('lastOutputDirectory'):
            self.bids_settings['lastOutputDirectory'] = path
            self.updateSettingsFile(self.bids_settings)

        # Read widget values from the load tree
        root = self.treeViewLoad.invisibleRootItem()
        parent_count = root.childCount()
        for i in range(parent_count):
            sub = root.child(i).text(0)
            child_count = root.child(i).childCount()
            self.file_info[sub] = sum(self.file_info[sub], [])
            ses_cnt = 0
            for j in range(child_count):
                item = root.child(i).child(j)
                if self.file_info[sub][ses_cnt]['DisplayName'] == item.text(0):
                    try:
                        new_sf = int(item.text(4))
                    except (ValueError, TypeError):
                        new_sf = self.file_info[sub][ses_cnt]['SamplingFrequency']
                    if self.file_info[sub][ses_cnt]['SamplingFrequency'] != new_sf:
                        self.file_info[sub][ses_cnt]['SamplingFrequency'] = new_sf
                        self.file_info[sub][ses_cnt]['TotalRecordTime'] = round(
                            (((self.file_info[sub][ses_cnt]['NRecords'] *
                               (new_sf * self.file_info[sub][ses_cnt]['RecordLength']))
                              / new_sf) / 60) / 60, 3)
                    w7 = self.treeViewLoad.itemWidget(item, 7)
                    if w7 and self.file_info[sub][ses_cnt]['RecordingType'] != w7.currentText():
                        self.file_info[sub][ses_cnt]['RecordingType'] = w7.currentText()
                    w8 = self.treeViewLoad.itemWidget(item, 8)
                    if w8 and self.file_info[sub][ses_cnt]['RecordingLength'] != w8.currentText():
                        self.file_info[sub][ses_cnt]['RecordingLength'] = w8.currentText()
                    w9 = self.treeViewLoad.itemWidget(item, 9)
                    if w9 and self.file_info[sub][ses_cnt]['Retro_Pro'] != w9.currentText():
                        self.file_info[sub][ses_cnt]['Retro_Pro'] = w9.currentText()
                ses_cnt += 1

        self.new_sessions = read_output_dir(
            self.output_path, self.file_info, self.offsetDate.isChecked(),
            self.bids_settings, participants_fname=None)

        # ── Build the output tree ──────────────────────────────────────
        recording_labels = self.bids_settings['general']['recordingLabels'].split(',')

        headers_out = [
            self.padentry('Name', 110), self.padentry('Session', 20),
            self.padentry("Date", 20),  self.padentry("Time", 14),
            self.padentry("Frequency", 6), self.padentry("Duration", 9),
            self.padentry('Type', 14),  self.padentry('Task', 14),
            self.padentry('Ret/Pro', 14)
        ]
        self.treeViewOutput._col_names = headers_out
        self.treeViewOutput._columns   = [f'col{i}' for i in range(len(headers_out))]
        self.treeViewOutput._init_tree()

        for isub, values in self.new_sessions.items():
            if values['newSessions']:
                parent = self.treeViewOutput.new_item()
                parent.setText(0, str(isub))

                self.file_info_final = []
                ses_not_done_cnt = 0
                for isession_idx in range(len(values['all_sessions'])):
                    isession = values['all_sessions'][isession_idx]

                    if isession in values['session_labels']:
                        self.file_info_final.append(self.file_info[isub][isession_idx])

                        date = self.file_info[isub][isession_idx]['Date']
                        if self.offsetDate.isChecked():
                            date_study = datetime.datetime.strptime(date, "%Y-%m-%d")
                            date = (date_study - datetime.timedelta(5856)).strftime('%Y-%m-%d')
                        time = self.file_info[isub][isession_idx]['Time']
                        date_collected = datetime.datetime.strptime(
                            ' '.join([date, time]), '%Y-%m-%d %H:%M:%S')

                        child = self.treeViewOutput.new_item(parent)
                        child.setText(0, self.padentry(
                            self.file_info[isub][isession_idx]['DisplayName'], padding))
                        child.setCheckState(0, 0)   # Unchecked
                        child.setText(1, self.padentry(isession, padding))
                        child.setText(2, str(date_collected.date()))
                        child.setText(3, str(date_collected.time()))
                        child.setText(4, str(self.file_info[isub][isession_idx]['SamplingFrequency']))
                        child.setText(5, "{:.3f}".format(
                            self.file_info[isub][isession_idx]['TotalRecordTime']))

                        cb_t = CellComboProxy(
                            self.treeViewOutput, child.iid, 'col6',
                            ['iEEG', 'Scalp'],
                            self.file_info[isub][isession_idx]['RecordingType'])
                        self.treeViewOutput.setItemWidget(child, 6, cb_t)

                        cb_l = CellComboProxy(
                            self.treeViewOutput, child.iid, 'col7',
                            recording_labels,
                            self.file_info[isub][isession_idx]['RecordingLength'])
                        self.treeViewOutput.setItemWidget(child, 7, cb_l)

                        cb_r = CellComboProxy(
                            self.treeViewOutput, child.iid, 'col8',
                            ['Ret', 'Pro'],
                            self.file_info[isub][isession_idx]['Retro_Pro'])
                        self.treeViewOutput.setItemWidget(child, 8, cb_r)

                    else:
                        old_isession = [x[0] for x in values['session_changes']
                                        if isession_idx == x[1]][0]
                        scans_tsv = pd.read_csv(
                            os.path.join(self.output_path, isub, isub + '_scans.tsv'), sep='\t')
                        date = scans_tsv.loc[isession_idx, 'acq_time'].split('T')[0]
                        time = scans_tsv.loc[isession_idx, 'acq_time'].split('T')[1]
                        file_n = scans_tsv.loc[isession_idx, 'filename'].split('.edf')[0] + '.json'
                        with open(os.path.join(self.output_path, isub, old_isession, file_n)) as sf:
                            side_file_temp = json.load(sf)
                        display_name = scans_tsv.loc[isession_idx, 'filename'].split('.edf')[0]
                        retpro_out   = 'Pro'
                        length_out   = []

                        if 'EPL' in isub:
                            old_sub = '_'.join(
                                [''.join(' '.join(re.split(r'(\d+)', isub.split('-')[-1])).split()[:2])]
                                + ' '.join(re.split(r'(\d+)', isub.split('-')[-1])).split()[2:])
                            old_ses = '_'.join([
                                ' '.join(re.split(r'(\D+)', isession.split('-')[-1])).split()[0],
                                ''.join(' '.join(re.split(r'(\D+)', isession.split('-')[-1])).split()[1:3]),
                                ' '.join(re.split(r'(\D+)', isession.split('-')[-1])).split()[-1]])
                            display_name = old_sub + '_' + old_ses
                            length_out   = side_file_temp['TaskName']
                            if length_out:
                                display_name = display_name + '_' + length_out
                            if 'ret' in side_file_temp['TaskName'].lower():
                                retpro_out   = 'Ret'
                                display_name = display_name + '_' + retpro_out.upper()

                        child = self.treeViewOutput.new_item(parent)
                        child.setText(0, self.padentry(display_name, padding))
                        child.setCheckState(0, 2)   # Checked
                        child.setText(1, self.padentry(isession, padding))
                        child.setText(2, str(date))
                        child.setText(3, str(time))
                        child.setText(4, str(side_file_temp['SamplingFrequency']))
                        child.setText(5, "{:.3f}".format(side_file_temp['RecordingDuration']))

                        rec_type = ('iEEG' if 'SEEGChannelCount' in side_file_temp
                                    else ('Scalp' if 'EEGChannelCount' in side_file_temp else 'iEEG'))
                        cb_t = CellComboProxy(
                            self.treeViewOutput, child.iid, 'col6',
                            ['iEEG', 'Scalp'], rec_type)
                        self.treeViewOutput.setItemWidget(child, 6, cb_t)

                        cb_l = CellComboProxy(
                            self.treeViewOutput, child.iid, 'col7',
                            recording_labels,
                            length_out if length_out else recording_labels[0])
                        self.treeViewOutput.setItemWidget(child, 7, cb_l)

                        cb_r = CellComboProxy(
                            self.treeViewOutput, child.iid, 'col8',
                            ['Ret', 'Pro'], retpro_out)
                        self.treeViewOutput.setItemWidget(child, 8, cb_r)

                    ses_not_done_cnt += 1

                self.file_info[isub] = self.file_info_final

            else:
                parent = self.treeViewOutput.new_item()
                parent.setText(0, str(isub))

                for x in range(values['num_sessions']):
                    scans_tsv = pd.read_csv(
                        os.path.join(self.output_path, isub, isub + '_scans.tsv'), sep='\t')
                    name_idx  = [i for i, z in enumerate(list(scans_tsv['filename']))
                                 if values['session_labels'][x] in z][-1]
                    date      = scans_tsv.loc[name_idx, 'acq_time'].split('T')[0]
                    time      = scans_tsv.loc[name_idx, 'acq_time'].split('T')[1]
                    file_n    = scans_tsv.loc[name_idx, 'filename'].split('.edf')[0] + '.json'
                    with open(os.path.join(
                        self.output_path, isub, values['session_labels'][x], file_n)) as sf:
                        side_file_temp = json.load(sf)

                    for irun in range(len(self.file_info[isub][x])):
                        retpro_out   = 'Pro'
                        length_out   = []
                        if 'EPL' in isub:
                            old_sub = '_'.join(
                                [''.join(' '.join(re.split(r'(\d+)', isub.split('-')[-1])).split()[:2])]
                                + ' '.join(re.split(r'(\d+)', isub.split('-')[-1])).split()[2:])
                            old_ses = '_'.join([
                                ' '.join(re.split(r'(\D+)', values['session_labels'][x].split('-')[-1])).split()[0],
                                ''.join(' '.join(re.split(r'(\D+)', values['session_labels'][x].split('-')[-1])).split()[1:3]),
                                ' '.join(re.split(r'(\D+)', values['session_labels'][x].split('-')[-1])).split()[-1]])
                            display_name = old_sub + '_' + old_ses
                            length_out   = side_file_temp['TaskName']
                            if length_out:
                                display_name = display_name + '_' + length_out
                            if 'ret' in side_file_temp['TaskName'].lower():
                                retpro_out   = 'Ret'
                                display_name = display_name + '_' + retpro_out.upper()
                        else:
                            display_name = self.file_info[isub][x][irun]['DisplayName']

                        child = self.treeViewOutput.new_item(parent)
                        child.setText(0, self.padentry(display_name, padding))
                        child.setCheckState(0, 2)   # Checked
                        child.setText(1, self.padentry(values['session_labels'][x], padding))
                        child.setText(2, str(date))
                        child.setText(3, str(time))
                        child.setText(4, str(side_file_temp['SamplingFrequency']))
                        child.setText(5, "{:.3f}".format(side_file_temp['RecordingDuration']))

                        rec_type = ('iEEG' if 'SEEGChannelCount' in side_file_temp
                                    else ('Scalp' if 'EEGChannelCount' in side_file_temp else 'iEEG'))
                        cb_t = CellComboProxy(
                            self.treeViewOutput, child.iid, 'col6',
                            ['iEEG', 'Scalp'], rec_type)
                        self.treeViewOutput.setItemWidget(child, 6, cb_t)

                        cb_l = CellComboProxy(
                            self.treeViewOutput, child.iid, 'col7',
                            recording_labels,
                            length_out if length_out else recording_labels[0])
                        self.treeViewOutput.setItemWidget(child, 7, cb_l)

                        cb_r = CellComboProxy(
                            self.treeViewOutput, child.iid, 'col8',
                            ['Ret', 'Pro'], retpro_out)
                        self.treeViewOutput.setItemWidget(child, 8, cb_r)

        self.sText.setVisible(True)
        self.updateStatus("Output directory loaded. Ready to convert.")

    def checkEditOutput(self, item, column):
        if column == 1:
            self._inline_edit(self.treeViewOutput, item, column)

    # ── Convert ─────────────────────────────────────────────────────────
    def onConvertButton(self):
        if self.output_path is None:
            messagebox.showwarning("Warning", "Please choose an output directory!")
            return

        if getattr(sys, 'frozen', False):
            source_dir = os.path.dirname(sys.executable)
        else:
            source_dir = os.path.dirname(os.path.realpath(__file__))

        self.conversionStatus.clear()
        self.updateStatus("Converting files...")

        # Read session labels from output tree
        root        = self.treeViewOutput.invisibleRootItem()
        parent_count = root.childCount()
        for i in range(parent_count):
            sub         = root.child(i).text(0)
            child_count = root.child(i).childCount()
            ses_cnt     = 0
            for j in range(child_count):
                item = root.child(i).child(j)
                if self.new_sessions[sub]['session_labels'][ses_cnt] != item.text(1):
                    self.new_sessions[sub]['session_labels'][ses_cnt] = item.text(1)
                    self.new_sessions[sub]['all_sessions'][ses_cnt]   = item.text(1)
                ses_cnt += 1

        dataset_fname = bidsHelper(output_path=self.output_path).write_dataset(return_fname=True)
        if not os.path.exists(dataset_fname):
            bidsHelper(output_path=self.output_path,
                       bids_settings=self.bids_settings).write_dataset()

        if '.bidsignore' not in os.listdir(self.output_path):
            shutil.copy(os.path.join(source_dir, 'static', 'bidsignore'),
                        os.path.join(self.output_path, '.bidsignore'))

        if not os.path.exists(os.path.join(self.output_path, 'README')):
            shutil.copy(os.path.join(source_dir, 'static', 'README'),
                        os.path.join(self.output_path, 'README'))

        participants_fname = bidsHelper(
            output_path=self.output_path).write_participants(return_fname=True)
        if os.path.exists(participants_fname):
            self.participant_tsv = pd.read_csv(participants_fname, sep='\t')
        else:
            bidsHelper(output_path=self.output_path).write_participants()
            self.participant_tsv = pd.read_csv(participants_fname, sep='\t')

        # Launch worker
        self.edf2bidsWorker = edf2bids()
        self.edf2bidsWorker.bids_settings      = self.bids_settings
        self.edf2bidsWorker.new_sessions       = self.new_sessions
        self.edf2bidsWorker.file_info          = self.file_info
        self.edf2bidsWorker.chan_label_file     = self.chan_label_file
        self.edf2bidsWorker.input_path         = self.input_path
        self.edf2bidsWorker.output_path        = self.output_path
        self.edf2bidsWorker.script_path        = source_dir
        self.edf2bidsWorker.coordinates        = None
        self.edf2bidsWorker.electrode_imp      = None
        self.edf2bidsWorker.make_dir           = True
        self.edf2bidsWorker.overwrite          = True
        self.edf2bidsWorker.verbose            = False
        self.edf2bidsWorker.deidentify_source  = self.deidentifyInputDir.isChecked()
        self.edf2bidsWorker.gzip_edf           = self.gzipEDF.isChecked()
        self.edf2bidsWorker.offset_date        = self.offsetDate.isChecked()
        self.edf2bidsWorker.dry_run            = self.dryRun.isChecked()

        self.edf2bidsWorker.signals.progressEvent.connect(self.conversionStatusUpdate)
        self.edf2bidsWorker.signals.finished.connect(self.doneConversion)
        self.edf2bidsWorker.signals.errorEvent.connect(self.errorConversion)

        self.edf2bidsWorker.start()   # replaces threadpool.start()

        self.cancelButton.setEnabled(True)
        self.cancelButton.clicked.connect(lambda: self.onCancelButton('edf2bids'))
        self.pauseButton.setEnabled(True)
        self.pauseButton.clicked.connect(self.edf2bidsWorker.pause)
        self.pauseButton.clicked.connect(lambda: self.onPauseButton('edf2bids'))
        self.convertButton.setEnabled(False)
        self.imagingButton.setEnabled(False)

    # ── String padding helper ────────────────────────────────────────────
    def padentry(self, buf, num):
        if isinstance(buf, float):
            num -= len("{:.3f}".format(buf))
            return ' ' * int(num / 2) + "{:.3f}".format(buf) + ' ' * int(num / 2)
        else:
            num -= len(str(buf))
            return ' ' * int(num / 2) + str(buf) + ' ' * int(num / 2)

    # ── Pause / Cancel ───────────────────────────────────────────────────
    def onPauseButton(self, worker_name):
        paused = False
        if worker_name == 'edf2bids'   and hasattr(self, 'edf2bidsWorker'):
            paused = self.edf2bidsWorker.is_paused
        elif worker_name == 'spred2bids' and hasattr(self, 'spred2bidsWorker'):
            paused = self.spred2bidsWorker.is_paused
        elif worker_name == 'dicom2bids' and hasattr(self, 'dicom2bidsWorker'):
            paused = self.dicom2bidsWorker.is_paused

        if paused:
            self.pauseButton._btn.configure(text='Resume...')
            self.updateStatus("Conversion paused... ")
            self.cancelButton.setEnabled(False)
        else:
            self.pauseButton._btn.configure(text='Pause')
            self.updateStatus("Conversion resumed...")
            self.cancelButton.setEnabled(True)

    def onCancelButton(self, worker_name):
        if worker_name == 'edf2bids'   and hasattr(self, 'edf2bidsWorker'):
            self.edf2bidsWorker.kill()
        elif worker_name == 'spred2bids' and hasattr(self, 'spred2bidsWorker'):
            self.spred2bidsWorker.kill()
        elif worker_name == 'dicom2bids' and hasattr(self, 'dicom2bidsWorker'):
            self.dicom2bidsWorker.kill()

        self.updateStatus("Conversion cancel requested... ")
        self.conversionStatus.appendPlainText('\nCancelling data conversion... please wait\n')
        self.userAborted = True
        self.cancelButton.setEnabled(False)
        self.pauseButton.setEnabled(False)

    # ── Status / log ────────────────────────────────────────────────────
    def updateStatus(self, update):
        self.statusbar.showMessage(update)

    def conversionStatusUpdate(self, text):
        if '%' in text:
            if text == 'copy10%':
                self.conversionStatus.appendPlainText('Copying File: ' + text.strip('copy'))
            elif 'annot' in text:
                self.conversionStatus.insertPlainText(' ' + text.strip('annot'))
            else:
                self.conversionStatus.insertPlainText(' ' + text)
        elif text == '...':
            self.conversionStatus.appendPlainText('Extract/Scrub Annotations: ' + text)
        else:
            self.conversionStatus.appendPlainText(text)

    # ── Conversion done callbacks ────────────────────────────────────────
    def doneConversion(self):
        if self.userAborted:
            self.conversionStatus.appendPlainText(
                '\nAborted conversion at {}'.format(
                    datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            self.conversionStatus.appendPlainText(
                'File conversion incomplete: Please delete output directory contents and close program.')
            self.updateStatus("Conversion aborted.")
            self.treeViewOutput.clear()
            self.treeViewLoad.clear()
            self.spredButton.setEnabled(False)
            self.imagingButton.setEnabled(False)
        else:
            self.conversionStatus.appendPlainText(
                '\nCompleted conversion at {}'.format(
                    datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            self.conversionStatus.appendPlainText('Your data has been BIDsified!\n')
            self.updateStatus("BIDs conversion complete.")
            self.spredButton.setEnabled(True)
            if self.imagingDataPresent and not self.imagingConversionDone:
                self.imagingButton.setEnabled(True)

        self.cancelButton.setEnabled(False)
        self.convertButton.setEnabled(False)
        self.pauseButton.setEnabled(False)

    def errorConversion(self, errorInfo):
        self.conversionStatus.appendPlainText('\n')
        self.conversionStatus.appendPlainText('Error occurred: {}'.format(errorInfo[1]))
        self.conversionStatus.appendPlainText('{}'.format(errorInfo[2]))
        self.updateStatus("Error occurred...")
        self.treeViewOutput.clear()
        self.treeViewLoad.clear()
        self.spredButton.setEnabled(False)
        self.cancelButton.setEnabled(False)
        self.pauseButton.setEnabled(False)
        self.convertButton.setEnabled(False)
        self.imagingButton.setEnabled(False)

    # ── SPReD conversion ─────────────────────────────────────────────────
    def onSpredButton(self):
        self.updateStatus('Converting to SPReD format...')
        self.spred2bidsWorker = bids2spred()
        self.spred2bidsWorker.output_path = self.output_path
        self.spred2bidsWorker.signals.progressEvent.connect(self.conversionStatusUpdate)
        self.spred2bidsWorker.signals.finished.connect(self.doneSPReDConversion)
        self.spred2bidsWorker.start()
        self.cancelButton.setEnabled(True)
        self.cancelButton.clicked.connect(lambda: self.onCancelButton('spred2bids'))
        self.pauseButton.setEnabled(True)
        self.pauseButton.clicked.connect(self.spred2bidsWorker.pause)
        self.pauseButton.clicked.connect(lambda: self.onPauseButton('spred2bids'))
        self.spredButton.setEnabled(False)
        self.imagingButton.setEnabled(False)

    def doneSPReDConversion(self):
        if self.userAborted:
            self.conversionStatus.appendPlainText(
                '\nAborted SPReD conversion at {}'.format(
                    datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            self.updateStatus("SPReD conversion aborted.")
            self.treeViewOutput.clear()
            self.treeViewLoad.clear()
        else:
            self.conversionStatus.appendPlainText(
                'Completed SPReD conversion at {}'.format(
                    datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            self.conversionStatus.appendPlainText('Your data has been SPReDified!\n')
            self.updateStatus("SPReD conversion complete.")
        self.eegConversionDone = True
        self.spredButton.setEnabled(False)
        self.cancelButton.setEnabled(False)
        self.pauseButton.setEnabled(False)
        self.convertButton.setEnabled(False)
        if self.imagingDataPresent and not self.imagingConversionDone:
            self.imagingButton.setEnabled(True)

    # ── Imaging conversion ───────────────────────────────────────────────
    def onImagingButton(self):
        self.updateStatus('De-identifying imaging data...')
        self.dicom2bidsWorker = dicom2bids()
        self.dicom2bidsWorker.input_path    = self.input_path
        self.dicom2bidsWorker.output_path   = self.output_path
        self.dicom2bidsWorker.imaging_data  = self.imaging_data
        self.dicom2bidsWorker.signals.progressEvent.connect(self.conversionStatusUpdate)
        self.dicom2bidsWorker.signals.finished.connect(self.doneImagingConversion)
        self.dicom2bidsWorker.start()
        self.cancelButton.setEnabled(True)
        self.cancelButton.clicked.connect(lambda: self.onCancelButton('dicom2bids'))
        self.pauseButton.setEnabled(True)
        self.pauseButton.clicked.connect(self.dicom2bidsWorker.pause)
        self.pauseButton.clicked.connect(lambda: self.onPauseButton('dicom2bids'))
        self.imagingButton.setEnabled(False)
        if self.convertButton.isEnabled():
            self.convertButton.setEnabled(False)

    def doneImagingConversion(self):
        if self.userAborted:
            self.conversionStatus.appendPlainText(
                '\nAborted image de-identification at {}'.format(
                    datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            self.updateStatus("Image de-identification aborted.")
            self.treeViewOutput.clear()
            self.treeViewLoad.clear()
        else:
            self.conversionStatus.appendPlainText(
                '\nCompleted image de-identification at {}'.format(
                    datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            self.updateStatus("Image de-identification complete.")
        self.imagingConversionDone = True
        self.imagingButton.setEnabled(False)
        self.cancelButton.setEnabled(False)
        self.pauseButton.setEnabled(False)
        if (not self.eegConversionDone and
                not all(len(value) == 0 for value in self.file_info.values())):
            self.convertButton.setEnabled(True)
        else:
            self.convertButton.setEnabled(False)

    # ── EDF type conversion helpers ──────────────────────────────────────
    def edfC2D(self, file):
        opener = gzip.open if file.lower().endswith(('.edfz', '.edf.gz')) else open
        with opener(file, 'r+b') as fid:
            fid.seek(192)
            fid.write(bytes("EDF+D" + ' ' * (44 - len("EDF+D")), encoding="ascii"))

    def edfD2C(self, file):
        opener = gzip.open if file.lower().endswith(('.edfz', '.edf.gz')) else open
        with opener(file, 'r+b') as fid:
            fid.seek(192)
            fid.write(bytes("EDF+C" + ' ' * (44 - len("EDF+C")), encoding="ascii"))


# ═══════════════════════════════════════════════════════════════════════
# Default settings (extracted from the original SettingsDialog.__init__)
# ═══════════════════════════════════════════════════════════════════════

class SettingsDialog_defaults:
    general = {
        'checkUpdates': True,
        'darkMode': True,
        "recordingLabels": "full,clip,stim,ccep"
    }
    ieeg_file_metadata = {
        'TaskName': 'EEG Clinical',
        'Experimenter': ['John Smith, Wayne Smith'],
        'Lab': 'Some cool lab',
        'InstitutionName': 'Some University',
        'InstitutionAddress': '123 Fake Street, Fake town, Fake country',
        'ExperimentDescription': '',
        'DatasetName': '',
    }
    natus_info = {
        'Manufacturer': 'Natus',
        'ManufacturersModelName': 'Neuroworks',
        'SamplingFrequency': 1000,
        'HighpassFilter': float('nan'),
        'LowpassFilter': float('nan'),
        'MERUnit': 'uV',
        'PowerLineFrequency': 60,
        'RecordingType': 'continuous',
        'iEEGCoordinateSystem': 'continuous',
        'iEEGElectrodeInfo': {
            'Manufacturer': 'AdTech', 'Type': 'depth',
            'Material': 'Platinum', 'Diameter': 0.86
        },
        'EEGElectrodeInfo': {
            'Manufacturer': 'AdTech', 'Type': 'scalp',
            'Material': 'Platinum', 'Diameter': 10
        },
        'ChannelInfo': {
            'Patient Event': {'type': 'PatientEvent', 'name': 'PE'},
            'DC':  {'type': 'DAC',   'name': 'DAC'},
            'TRIG':{'type': 'TRIG',  'name': 'TR'},
            'OSAT':{'type': 'OSAT',  'name': 'OSAT'},
            'PR':  {'type': 'PR',    'name': 'MISC'},
            'Pleth':{'type': 'Pleth','name': 'MISC'},
            'EDF Annotations':{'type': 'Annotations','name': 'ANNO'},
            'X':   {'type': 'unused','name': 'unused'},
            'EKG': {'type': 'EKG',  'name': 'EKG'},
            'EMG': {'type': 'EMG',  'name': 'EMG'},
            'EOG': {'type': 'EOG',  'name': 'EOG'},
            'ECG': {'type': 'ECG',  'name': 'ECG'},
            'SpO2':{'type': 'SpO2', 'name': 'SpO2'},
        }
    }


# ═══════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════

def main():
    window = MainWindow()
    window.show()   # enters tkinter mainloop

if __name__ == '__main__':
    main()
