# -*- coding: utf-8 -*-
"""
Modified on Sun Oct 5 12:59:16 2025

Original Author:   Alaina Mahalanobis
Modified by:       Milad Khaki
Enhanced with ERDetect integration

Current update:
- Return to annotation-based absolute EDF synchronization
- Use annotation onsets -> absolute sample indices as ground truth
- Epoch and polarity detection use full-length filtered signals
- 10 s window now only for visualization, not for time indexing
- v5p6: Per-pulse orientation-based flipping (compare stim vs evoked channel derivatives)
- NEW: Support for JSON file with valid pulse indices for selective averaging
"""

from scipy.signal import find_peaks, medfilt
import re
import logging
import json
import numpy as np


# -----------------------
# Helper Functions
# -----------------------

def load_valid_pulses(json_path, stim_pair_key):
    """
    Load valid pulse indices from JSON file.
    
    Parameters
    ----------
    json_path : str or None
        Path to JSON file. If None, returns None.
    stim_pair_key : str
        Key for stimulation pair (e.g., "LAHc1-LAHc2")
    
    Returns
    -------
    valid_indices : set or None
        Set of valid sample indices, or None if file not provided
    """
    if json_path is None:
        return None
    
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
        
        if stim_pair_key not in data:
            print(f"\nWarning: Stim pair '{stim_pair_key}' not found in JSON file.")
            print(f"Available keys: {list(data.keys())}")
            return None
        
        valid_indices = set(data[stim_pair_key]['sample_indices'])
        print(f"\nLoaded {len(valid_indices)} valid pulse indices for {stim_pair_key}")
        return valid_indices
    
    except FileNotFoundError:
        print(f"\nWarning: JSON file '{json_path}' not found. Using all pulses.")
        return None
    except Exception as e:
        print(f"\nError loading JSON file: {e}. Using all pulses.")
        return None


def set_xylabel(ax, xy_sel, cols_str):
    """
    ax       : the axis to modify (subplot)
    xy_sel   : "x" for xlabel, "y" for ylabel
    cols_str : list of (text, color) tuples
               e.g. [("ev_", "blue"), ("Green_", "green"), ("Blue", "blue")]
    """

    # Remove existing label
    if xy_sel == "x":
        ax.set_xlabel("")

        base_y = -0.1          # vertical offset under axis
        x_start = 0.5    # starting x-position (slightly left of center)

        # Compute equal spacing
        total = len(cols_str)
        spacing = 0.2 # distance between text segments (axes fraction)

        for i, (txt, col) in enumerate(cols_str):
            xpos = x_start + (i - total/2) * spacing + spacing/2
            ax.text(xpos, base_y, txt, color=col,
                    transform=ax.transAxes,
                    ha="center", va="center")

    elif xy_sel == "y":
        ax.set_ylabel("")

        base_x = -0.18
        y_start = 0.5 - 0.02
        total = len(cols_str)
        spacing = 0.05

        for i, (txt, col) in enumerate(cols_str):
            ypos = y_start + (i - total/2) * spacing + spacing/2
            ax.text(base_x, ypos, txt, color=col,
                    transform=ax.transAxes,
                    ha="center", va="center",
                    rotation=90)

    else:
        raise ValueError("xy_sel must be 'x' or 'y'")

# plt.show()


def peak_finder_v2p0(
    data,
    sel=None,
    thresh=None,
    extrema=1,
    include_endpoints=True,
    interpolate=False,
    min_width=None,
    max_width=None
):
    """
    Peak finder with width-based filtering.

    Parameters
    ----------
    data : 1D array-like
        Input signal.
    sel : float, optional
        Selectivity (minimum height relative to left minimum).
    thresh : float, optional
        Absolute magnitude threshold for peaks.
    extrema : {1, -1}, optional
        1 for maxima, -1 for minima (data is flipped internally if -1).
    include_endpoints : bool, optional
        Include first and last samples as potential extrema.
    interpolate : bool, optional
        Parabolic interpolation for sub-sample peak location.
    min_width : int, optional
        Minimum pulse width in samples (start of rise to end of fall).
        If None, no minimum width constraint.
    max_width : int, optional
        Maximum pulse width in samples (start of rise to end of fall).
        If None, no maximum width constraint.

    Returns
    -------
    peak_inds : ndarray or None
        Indices of detected peaks (possibly fractional if interpolate=True).
    peak_mags : ndarray or None
        Magnitudes of detected peaks.
    """

    #
    # input parameters
    #

    # data parameter
    if isinstance(data, (list, tuple)):
        data = np.array(data)
    if not isinstance(data, np.ndarray) or not data.ndim == 1 or len(data) < 2:
        logging.error('The input data must be a one-dimensional array (list, tuple, ndarray) of at least 2 values')
        raise ValueError('Invalid input data')
    if np.any(~np.isreal(data)):
        logging.warning('Absolute values of data will be used')
        data = np.abs(data)

    # selection parameter
    if sel is None:
        sel = (np.nanmax(data) - np.nanmin(data)) / 4.0
    else:
        try:
            float(sel)
        except Exception:
            logging.warning('The selectivity must be a real scalar. A selectivity of %.4g will be used',
                          (np.nanmax(data) - np.nanmin(data)) / 4.0)
            sel = (np.nanmax(data) - np.nanmin(data)) / 4.0

    # threshold parameter
    if thresh is None:
        thresh = (np.nanmax(data) - np.nanmin(data)) / 4.0
    else:
        try:
            float(thresh)
        except Exception:
            logging.warning('The threshold must be a real scalar. A threshold of %.4g will be used',
                          (np.nanmax(data) - np.nanmin(data)) / 4.0)
            thresh = (np.nanmax(data) - np.nanmin(data)) / 4.0

    # extrema parameter
    if extrema != 1 and extrema != -1:
        logging.warning('The extrema must be either 1 or -1. A value of 1 will be used')
        extrema = 1

    #
    # detect peak candidates
    #

    if extrema == -1:
        data = -data

    # first derivative
    d = np.diff(data)
    d_sign = np.sign(d)

    # find local maxima (zero-crossings of derivative from positive to negative)
    zc = np.diff(d_sign)
    peak_inds = np.where(zc < 0)[0] + 1

    if include_endpoints:
        # check first point
        if len(d) > 0 and d[0] < 0:
            peak_inds = np.concatenate(([0], peak_inds))
        # check last point
        if len(d) > 0 and d[-1] > 0:
            peak_inds = np.concatenate((peak_inds, [len(data) - 1]))

    if len(peak_inds) == 0:
        return None, None

    peak_mags = data[peak_inds]

    #
    # apply threshold
    #
    valid_mask = peak_mags > thresh
    peak_inds = peak_inds[valid_mask]
    peak_mags = peak_mags[valid_mask]

    if len(peak_inds) == 0:
        return None, None

    #
    # apply selectivity
    #
    # find left minimum for each peak
    left_mins = np.zeros(len(peak_inds))
    for i, pk_idx in enumerate(peak_inds):
        left_data = data[:pk_idx+1]
        if len(left_data) > 0:
            left_mins[i] = np.min(left_data)
        else:
            left_mins[i] = peak_mags[i]

    valid_mask = (peak_mags - left_mins) > sel
    peak_inds = peak_inds[valid_mask]
    peak_mags = peak_mags[valid_mask]

    if len(peak_inds) == 0:
        return None, None

    #
    # apply width filtering
    #
    if min_width is not None or max_width is not None:
        # For each peak, find width (from rise start to fall end)
        valid_peaks = []
        valid_mags = []
        
        for i, pk_idx in enumerate(peak_inds):
            # Find start of rise (last point before peak where derivative went positive)
            rise_start = 0
            for j in range(pk_idx - 1, -1, -1):
                if j < len(d_sign) and d_sign[j] <= 0:
                    rise_start = j + 1
                    break
            
            # Find end of fall (first point after peak where derivative goes non-negative)
            fall_end = len(data) - 1
            for j in range(pk_idx, len(d_sign)):
                if d_sign[j] >= 0:
                    fall_end = j
                    break
            
            width = fall_end - rise_start
            
            # Check width constraints
            width_ok = True
            if min_width is not None and width < min_width:
                width_ok = False
            if max_width is not None and width > max_width:
                width_ok = False
            
            if width_ok:
                valid_peaks.append(pk_idx)
                valid_mags.append(peak_mags[i])
        
        peak_inds = np.array(valid_peaks)
        peak_mags = np.array(valid_mags)
        
        if len(peak_inds) == 0:
            return None, None

    #
    # interpolate
    #
    if interpolate and len(peak_inds) > 0:
        peak_inds_interp = np.zeros(len(peak_inds))
        for i, pk_idx in enumerate(peak_inds):
            if pk_idx > 0 and pk_idx < len(data) - 1:
                # parabolic interpolation
                alpha = data[pk_idx - 1]
                beta = data[pk_idx]
                gamma = data[pk_idx + 1]
                p = 0.5 * (alpha - gamma) / (alpha - 2 * beta + gamma)
                peak_inds_interp[i] = pk_idx + p
            else:
                peak_inds_interp[i] = pk_idx
        peak_inds = peak_inds_interp

    if extrema == -1:
        peak_mags = -peak_mags

    return peak_inds, peak_mags


def moving_average_1d(array, window=5, axis=0):
    """
    Returns data smoothed via moving average with specified window along axis.
    """
    if window % 2 == 0:
        logging.warning('Window size must be odd. Adding 1 to make it odd.')
        window += 1

    if window <= 1:
        return array

    half_window = window // 2
    result = np.copy(array)
    
    ndim = array.ndim
    
    if ndim == 1:
        for i in range(len(array)):
            start = max(0, i - half_window)
            end = min(len(array), i + half_window + 1)
            result[i] = np.nanmean(array[start:end])
    elif ndim == 2:
        if axis == 0:
            for j in range(array.shape[1]):
                for i in range(array.shape[0]):
                    start = max(0, i - half_window)
                    end = min(array.shape[0], i + half_window + 1)
                    result[i, j] = np.nanmean(array[start:end, j])
        else:
            for i in range(array.shape[0]):
                for j in range(array.shape[1]):
                    start = max(0, j - half_window)
                    end = min(array.shape[1], j + half_window + 1)
                    result[i, j] = np.nanmean(array[i, start:end])
    
    return result


def baseline_normalize(seg, t_ms, args):
    """
    Z-score normalization using baseline window.
    Returns None if baseline window is out of bounds.
    """
    bl_start_ms, bl_end_ms = args.BASELINE_MS
    bl_mask = (t_ms >= bl_start_ms) & (t_ms <= bl_end_ms)
    if not np.any(bl_mask):
        return None
    bl_mean = np.nanmean(seg[bl_mask])
    bl_std = np.nanstd(seg[bl_mask])
    if bl_std == 0:
        return None
    return (seg - bl_mean) / bl_std


def detect_polarity_from_peak(seg, t_ms, args, return_polarity_info=False):
    """
    Detect polarity based on peak prominence in the segment.
    Returns:
        +1 if positive peak dominates
        -1 if negative peak dominates
        None if ambiguous or no clear peak
    """
    search_start_ms, search_end_ms = args.PEAK_SEARCH_MS
    search_mask = (t_ms >= search_start_ms) & (t_ms <= search_end_ms)
    
    if not np.any(search_mask):
        if return_polarity_info:
            return None, {}
        return None
    
    search_seg = seg[search_mask]
    search_t = t_ms[search_mask]
    
    # Find positive peaks
    pos_peaks, _ = find_peaks(search_seg, prominence=args.PEAK_PROMINENCE_Z)
    # Find negative peaks
    neg_peaks, _ = find_peaks(-search_seg, prominence=args.PEAK_PROMINENCE_Z)
    
    info = {
        'n_pos_peaks': len(pos_peaks),
        'n_neg_peaks': len(neg_peaks),
        'max_pos': np.max(search_seg) if len(search_seg) > 0 else 0,
        'min_neg': np.min(search_seg) if len(search_seg) > 0 else 0
    }
    
    if len(pos_peaks) == 0 and len(neg_peaks) == 0:
        if return_polarity_info:
            return None, info
        return None
    
    max_pos = np.max(search_seg[pos_peaks]) if len(pos_peaks) > 0 else 0
    max_neg = -np.min(search_seg[neg_peaks]) if len(neg_peaks) > 0 else 0
    
    info['max_pos_peak'] = max_pos
    info['max_neg_peak'] = max_neg
    
    if max_pos > max_neg * 1.2:  # Positive dominates
        result = +1
    elif max_neg > max_pos * 1.2:  # Negative dominates
        result = -1
    else:
        result = None  # Ambiguous
    
    if return_polarity_info:
        return result, info
    return result


def compute_orientation(signal, event_sample, fs, window_ms):
    """
    Compute orientation of a signal around an event based on derivative.
    
    Parameters
    ----------
    signal : ndarray
        Full signal array
    event_sample : int
        Sample index of the event
    fs : float
        Sampling frequency
    window_ms : float
        Window size in milliseconds for computing average derivative
    
    Returns
    -------
    orientation : str
        'positive' if upward deflection, 'negative' if downward, 'ambiguous' otherwise
    pre_deriv : float
        Average derivative before event
    post_deriv : float
        Average derivative after event
    """
    window_samples = int(window_ms * fs / 1000)
    N1_range = [event_sample,event_sample+int(0.1 * fs)]
    print(N1_range)
    
    N1_val = np.nansum(signal[N1_range])
    
    # Get windows before and after event
    pre_start = max(0, event_sample - window_samples)
    pre_end = event_sample
    post_start = event_sample
    post_end = min(len(signal), event_sample + window_samples)
    
    if pre_end <= pre_start or post_end <= post_start:
        return 'ambiguous', 0, 0
    
    # Compute average derivatives
    pre_window = signal[pre_start:pre_end]
    post_window = signal[post_start:post_end]
    
    pre_deriv = np.mean(np.diff(pre_window)) if len(pre_window) > 1 else 0
    post_deriv = np.mean(np.diff(post_window)) if len(post_window) > 1 else 0
    
    # Determine orientation
    deriv_diff = post_deriv - pre_deriv
    
    if 1:#abs(deriv_diff) < 0.1:  # Threshold for ambiguity
        print(f"N1_val = {N1_val}")
        if N1_val < 0:
            orientation = 'negative'  # Signal going down
        else:
            orientation = 'positive'  # Signal going up
        # orientation = 'ambiguous'
    elif deriv_diff > 0:
        orientation = 'positive'  # Signal going up
    else:
        orientation = 'negative'  # Signal going down
    
    return orientation, pre_deriv, post_deriv


def epochs_with_orientation_flip(
    args,
    stim_signal,
    evoked_signal,
    event_samples,
    orientation_window_ms=50.0,
    zscore_baseline=True
):
    """
    Epoch evoked signal and flip based on orientation comparison with stim channel.
    
    Logic: If stim and evoked have opposite orientations, flip the evoked signal.
    This ensures consistent polarity across all epochs.
    """
    fs = args.sampling_freq
    seg_start_ms, seg_end_ms = args.SEG_MS
    seg_start_samp = int(seg_start_ms * fs / 1000)
    seg_end_samp = int(seg_end_ms * fs / 1000)
    seg_len = seg_end_samp - seg_start_samp
    t_ms = np.linspace(seg_start_ms, seg_end_ms, seg_len)
    
    epochs = []
    ttfp_list = []
    flips = []
    flip_diagnostics = []
    
    for i_ev, ev_samp in enumerate(event_samples):
        # Extract evoked epoch
        start_idx = ev_samp + seg_start_samp
        end_idx = ev_samp + seg_end_samp
        
        if start_idx < 0 or end_idx > len(evoked_signal):
            print(f"Start index = {start_idx}")
            print(f"End index = {end_idx}, evoked signal length = {len(evoked_signal)}")
            
            flip_diagnostics.append({
                'event_idx': i_ev,
                'event_sample': ev_samp,
                'flip_decision': None,
                'reason': 'Epoch out of bounds'
            })
            continue
        
        seg = evoked_signal[start_idx:end_idx].copy()
        
        # Apply filters if requested
        if args.enable_detrend:
            from scipy.signal import detrend
            seg = detrend(seg)
        
        if args.enable_median:
            seg = medfilt(seg, kernel_size=args.MED_FILT_K)
        
        if args.enable_moving_avg:
            seg = moving_average_1d(seg, window=args.MOV_AVG_K)
        
        # Baseline normalize
        if zscore_baseline:
            seg_norm = baseline_normalize(seg, t_ms, args)
            if seg_norm is None:
                flip_diagnostics.append({
                    'event_idx': i_ev,
                    'event_sample': ev_samp,
                    'flip_decision': None,
                    'reason': 'Baseline normalization failed'
                })
                continue
            seg = seg_norm
        
        # Compute orientations
        stim_orient, stim_pre, stim_post = compute_orientation(
            stim_signal, ev_samp, fs, orientation_window_ms
        )
        evoked_orient, evoked_pre, evoked_post = compute_orientation(
            evoked_signal, ev_samp, fs, orientation_window_ms
        )
        
        # Decide whether to flip
        flip_decision = False
        reason = ""
        
        if stim_orient == 'ambiguous' or evoked_orient == 'ambiguous':
            reason = f"AMBIGUOUS orientation (stim={stim_orient}, evoked={evoked_orient})"
            flip_decision = False  # Default: no flip when ambiguous
        elif stim_orient != evoked_orient:
            reason = f"Opposite orientations (stim={stim_orient}, evoked={evoked_orient})"
            flip_decision = True
        else:
            reason = f"Same orientations (stim={stim_orient}, evoked={evoked_orient})"
            flip_decision = False
        
        # Apply flip if needed
        if flip_decision:
            seg = -seg
        
        # Store diagnostic info
        flip_diagnostics.append({
            'event_idx': i_ev,
            'event_sample': ev_samp,
            'flip_decision': flip_decision,
            'reason': reason,
            'stim_orientation': stim_orient,
            'evoked_orientation': evoked_orient,
            'stim_pre_deriv': stim_pre,
            'stim_post_deriv': stim_post,
            'evoked_pre_deriv': evoked_pre,
            'evoked_post_deriv': evoked_post
        })
        
        epochs.append(seg)
        ttfp_list.append(None)
        flips.append(flip_decision)
    
    return epochs, t_ms, ttfp_list, flips, flip_diagnostics


def epochs_no_flip(args, signal, event_samples, zscore_baseline=True):
    """
    Epoch signal without any polarity flipping.
    """
    fs = args.sampling_freq
    seg_start_ms, seg_end_ms = args.SEG_MS
    seg_start_samp = int(seg_start_ms * fs / 1000)
    seg_end_samp = int(seg_end_ms * fs / 1000)
    seg_len = seg_end_samp - seg_start_samp
    t_ms = np.linspace(seg_start_ms, seg_end_ms, seg_len)
    
    epochs = []
    ttfp_list = []
    flips = []
    
    for ev_samp in event_samples:
        start_idx = ev_samp + seg_start_samp
        end_idx = ev_samp + seg_end_samp
        
        if start_idx < 0 or end_idx > len(signal):
            continue
        
        seg = signal[start_idx:end_idx].copy()
        
        if args.enable_detrend:
            from scipy.signal import detrend
            seg = detrend(seg)
        
        if args.enable_median:
            seg = medfilt(seg, kernel_size=args.MED_FILT_K)
        
        if args.enable_moving_avg:
            seg = moving_average_1d(seg, window=args.MOV_AVG_K)
        
        if zscore_baseline:
            seg_norm = baseline_normalize(seg, t_ms, args)
            if seg_norm is None:
                continue
            seg = seg_norm
        
        epochs.append(seg)
        ttfp_list.append(None)
        flips.append(False)
    
    return epochs, t_ms, ttfp_list, flips

# =============================================================
# Decode events from annotations
# =============================================================
def decode_events_rev1(annot_timestamps, annot_labels):
    """
    Natus-style annotations with "Closed relay to X and Y" blocks and numeric currents.
    Returns dict: {channel_pair: [(timestamp, current), ...]}
    """
    events_by_channel = {}
    current_pair = None
    in_block = False
    
    for time_stamp, label in zip(annot_timestamps, annot_labels):
        label = str(label).strip()
        
        if label.startswith("Closed relay"):
            match = re.match(r"Closed relay to (\S+) and (\S+)", label)
            if match:
                ch_a = match.group(1)
                ch_b = match.group(2)
                current_pair = f"{ch_a}-{ch_b}"
                in_block = True
            continue
            
        if "Opened relay" in label or "De-block" in label:
            in_block = False
            current_pair = None
            continue
            
        if in_block and label.isdigit() and current_pair is not None:
            if current_pair not in events_by_channel:
                events_by_channel[current_pair] = []
            events_by_channel[current_pair].append((time_stamp, label))
    
    return events_by_channel


def decode_events_rev2(annot_timestamps, annot_labels):
    """
    Alternate annotation format:
      "Start Stimulation from X to Y, current=Z" style text.
    Returns dict: {channel_pair: [(timestamp, current), ...]}
    """
    events_by_channel = {}
    
    for time_stamp, label in zip(annot_timestamps, annot_labels):
        label = str(label)
        
        if label.startswith("Start Stimulation"):
            match = re.match(r"Start Stimulation from (\S+) to (\S+)", label)
            if match:
                ch_a = match.group(1)
                ch_b = match.group(2)
                current_pair = f"{ch_a}-{ch_b}"
                
                # Extract current from label if present
                current_match = re.search(r"current[=\s]+(\d+)", label, re.IGNORECASE)
                current = current_match.group(1) if current_match else "unknown"
                
                if current_pair not in events_by_channel:
                    events_by_channel[current_pair] = []
                events_by_channel[current_pair].append((time_stamp, current))
    
    return events_by_channel

def decode_events_rev3(annot_timestamps, annot_labels):
    """
    Decoder for modern Natus/CCEP-style annotations extracted from TSV or EDF.
    Expected patterns (examples from uploaded file):
        "Stim Start B1-B2 6.0"
        "Stim Stop B1-B2 6.0"
        "Stim Start B9-B10 6."
        "Stim Start B10-B11 6"
    
    RESET ON/OFF and other system labels are ignored.

    Returns:
        dict: { "B1-B2": [(timestamp, current), ...], ... }
    """

    events_by_channel = {}

    # Regex to extract:
    #   (Start|Stop),   "B1-B2",    current (6, 6.0, 6.)
    stim_regex = re.compile(
        r"Stim\s+(Start|Stop)\s+([A-Za-z0-9]+-[A-Za-z0-9]+)\s+([\d\.]+)"
    )

    for ts, label in zip(annot_timestamps, annot_labels):
        label = str(label).strip()

        # Ignore metadata/system entries
        if label.startswith(("RESET", "Segment", "+", "A1", "A2")):
            continue

        m = stim_regex.search(label)
        if m:
            start_or_stop = m.group(1)         # "Start" or "Stop"
            ch_pair = m.group(2)               # "B1-B2"
            current = m.group(3)               # "6.0" or "6." or "6"

            if ch_pair not in events_by_channel:
                events_by_channel[ch_pair] = []

            events_by_channel[ch_pair].append((float(ts), current))
            continue

        # If needed, log any unexpected label for debugging
        # print("Unhandled annotation:", label)

    return events_by_channel


def decode_events_rev1_prv(annot_timestamps, annot_labels, current, stimulated_channel_a, stimulated_channel_b):
    """
    Natus-style annotations with "Closed relay to X and Y" blocks and numeric currents.
    Returns list of (time_stamp, label, pair) filtered by stimulated_channel & current.
    """
    all_events = []
    current_pair = None
    in_block = False
    for time_stamp, label in zip(annot_timestamps, annot_labels):
        label = str(label).strip()
        if label.startswith("Closed relay"):
            match = re.match(r"Closed relay to (\S+) and (\S+)", label)
            if match:
                current_pair = (match.group(1), match.group(2))
                in_block = True
            continue
        if "Opened relay" in label or "De-block" in label:
            in_block = False
            current_pair = None
            continue
        if in_block and label.isdigit():
            if label == str(current) and current_pair is not None:
                all_events.append((time_stamp, label, current_pair))
    return [(t, l, p) for (t, l, p) in all_events if ((p[0] == stimulated_channel_a) or (p[0] == stimulated_channel_b))]


def decode_events_rev2_prv(annot_timestamps, annot_labels, current, stimulated_channel_a, stimulated_channel_b):
    """
    Alternate annotation format:
      "Start Stimulation from X to Y, current=Z" style text.
    """
    all_events = []
    for time_stamp, label in zip(annot_timestamps, annot_labels):
        label = str(label)
        if label.startswith("Start Stimulation"):
            match = re.match(r"Start Stimulation from (\S+) to (\S+)", label)
            if match:
                pair = (match.group(1), match.group(2))
                if str(current) in label:
                    all_events.append((time_stamp, label, pair))
    return [(t, l, p) for (t, l, p) in all_events if ((p[0] == stimulated_channel_a) or (p[0] == stimulated_channel_b))]


def detrend_cubic(signal, max_curvature=1e-3):
    x = np.arange(len(signal))
    coeffs = np.polyfit(x, signal, 3)
    if abs(coeffs[0]) > max_curvature:
        coeffs[0] = np.sign(coeffs[0]) * max_curvature
    poly_fit = np.polyval(coeffs, x)
    return signal - poly_fit, poly_fit, coeffs


def first_peak_with_polarity(t_ms, y_aligned, search_ms, prominence):
    """Return latency (ms) to first positive peak in search window, else None."""
    w0, w1 = float(search_ms[0]), float(search_ms[1])
    mask = (t_ms >= w0) & (t_ms <= w1)
    if not np.any(mask):
        return None
    ywin = y_aligned[mask]
    t_win = t_ms[mask]
    pks, _ = find_peaks(ywin, prominence=prominence)
    if len(pks) == 0:
        return None
    return float(t_win[pks[0]])

