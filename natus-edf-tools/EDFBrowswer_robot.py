# -*- coding: utf-8 -*-
"""
Created on Fri Apr 11 11:10:17 2025

@author: Antares
"""

from pywinauto.application import Application
import time

print("Connecting to EDFbrowser...")

# Connect to running app by executable path
app = Application(backend='uia').connect(path="c:/_Code/S22_GitHub/EDFbrowser/edfbrowser.exe")

print("Listing open windows:")
for win in app.windows():
    print(" -", win.window_text())

# Get main window
print("\nAccessing the main EDFbrowser window...")
main_win = app.window(title_re=".*EDFbrowser.*")

# %% Step 1: Access the Tools menu
print("Locating the 'Tools' menu item...")
toolsmenu = main_win.child_window(title="Tools", control_type="MenuItem").wrapper_object()
print("Clicking on 'Tools' menu...")
toolsmenu.click_input()
time.sleep(0.5)

print("Searching for the 'Reduce signals, duration or samplerate' menu item...")
main_win.menu_select("Tools->Reduce signals, duration or samplerate")
print("Clicking on 'Reduce signals...' tool...")

# %% Step 3: Wait for and focus the Reduce Dialog
print("Waiting for the 'Reduce' dialog to appear...")
reduce_item = app.top_window().child_window(
    title="Reduce signals and/or or duration", 
    control_type="MenuItem"
).wrapper_object()


# %% Step 4: Print controls for further inspection (temporarily)
print("\nAvailable controls in the 'Reduce' dialog:")
reduce_dialog.print_control_identifiers()
