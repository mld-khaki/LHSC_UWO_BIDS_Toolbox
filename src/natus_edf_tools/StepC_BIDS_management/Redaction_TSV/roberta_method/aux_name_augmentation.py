#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import glob
import os
import re
import csv
import random
import sys
import io
import numpy as np
import torch
import difflib

from typing import List, Tuple, Dict, Optional

# ---------- Public API ----------

# -----------------------------
# Reproducibility & Utilities
# -----------------------------

def seed_everything(seed: int = 42):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = False
    torch.backends.cudnn.benchmark = True


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def read_text(path: str) -> str:
    with io.open(path, 'r', encoding='utf-8', errors='replace') as f:
        return f.read()


def write_text(path: str, text: str):
    with io.open(path, 'w', encoding='utf-8', errors='replace') as f:
        f.write(text)


def normalize_minimal(s: str) -> str:
    # Minimal normalization: unify line endings, keep case/spacing
    return s.replace('\r\n', '\n').replace('\r', '\n')


# ---------------------------------------------
# Diff-based mask: where did the redaction occur
# ---------------------------------------------

def compute_redaction_mask(orig: str, redacted: str) -> np.ndarray:
    """
    Returns a binary numpy array 'mask' of length len(orig),
    where mask[i] == 1 iff orig[i] was part of a redacted region
    (i.e., replaced or deleted) relative to the redacted text.

    We use difflib, which is robust and doesn't add external deps.
    """
    orig = normalize_minimal(orig)
    red = normalize_minimal(redacted)
    sm = difflib.SequenceMatcher(a=orig, b=red, autojunk=False)
    ops = sm.get_opcodes()
    mask = np.zeros(len(orig), dtype=np.int64)
    for tag, i1, i2, j1, j2 in ops:
        if tag in ('replace', 'delete'):
            mask[i1:i2] = 1
        # 'insert' corresponds to insertion in redacted relative to orig -> no orig chars to mark
        # 'equal' -> nothing to do
    return mask


def spans_from_mask(mask: np.ndarray) -> List[Tuple[int, int]]:
    spans = []
    i = 0
    n = len(mask)
    while i < n:
        if mask[i] == 1:
            j = i + 1
            while j < n and mask[j] == 1:
                j += 1
            spans.append((i, j))  # [i, j)
            i = j
        else:
            i += 1
    return spans


# --------------------------------
# Targeted augmentations (optional)
# --------------------------------

KEYBOARD_NEIGHBORS = {
    'q': 'w', 'w': 'qe', 'e': 'wr', 'r': 'et', 't': 'ry',
    'y': 'tu', 'u': 'yi', 'i': 'uo', 'o': 'ip', 'p': 'o',
    'a': 's', 's': 'ad', 'd': 'sf', 'f': 'dg', 'g': 'fh',
    'h': 'gj', 'j': 'hk', 'k': 'jl', 'l': 'k',
    'z': 'x', 'x': 'zc', 'c': 'xv', 'v': 'cb', 'b': 'vn',
    'n': 'bm', 'm': 'n',
}

def random_neighbor(ch: str) -> str:
    low = ch.lower()
    if low in KEYBOARD_NEIGHBORS and KEYBOARD_NEIGHBORS[low]:
        rep = random.choice(KEYBOARD_NEIGHBORS[low])
        return rep.upper() if ch.isupper() else rep
    return ch


def augment_text_and_mask(orig: str,
                          mask: np.ndarray,
                          max_ops: int = 2,
                          p_typo: float = 0.3,
                          p_case: float = 0.3,
                          p_drop_space_in_name: float = 0.4,
                          p_drop_space_between_names: float = 0.4) -> Tuple[str, np.ndarray]:
    """
    Apply light, targeted noise to *name* regions (mask==1). We modify both text and mask
    so alignment stays intact. We avoid global edits that change offsets unpredictably.

    Ops:
      - Typo substitutions on letters inside name spans
      - Case jitter inside name spans
      - Drop spaces *inside* a span (e.g., "Anne Marie" -> "AnneMarie" if space is within a 1-run)
      - Drop a single space BETWEEN consecutive name spans if exactly one space separates them
    """
    s = list(orig)
    m = mask.copy()
    n = len(s)

    # 1) Case jitter + typos (no length change)
    for i in range(n):
        if m[i] == 1 and s[i].isalpha():
            if random.random() < p_typo:
                s[i] = random_neighbor(s[i])
            if random.random() < p_case:
                r = random.random()
                if r < 0.33:
                    s[i] = s[i].lower()
                elif r < 0.66:
                    s[i] = s[i].upper()
                else:
                    # Title-casing single char = upper/lower mix is fine
                    s[i] = s[i].upper() if random.random() < 0.5 else s[i].lower()

    # Helper to remove a char at pos i (text and mask)
    def remove_char(pos: int):
        nonlocal s, m
        s.pop(pos)
        m = np.delete(m, pos, axis=0)

    # 2) Drop spaces within a name span
    # We'll scan spans and, with some probability, remove *one* space per span (keeps it simple/stable)
    name_spans = spans_from_mask(m)
    for (a, b) in name_spans:
        # find space positions inside [a, b)
        space_positions = [i for i in range(a, b) if i < len(s) and s[i].isspace()]
        if space_positions and random.random() < p_drop_space_in_name:
            pos = random.choice(space_positions)
            remove_char(pos)
            # after removal, all subsequent indices shift; recompute spans later if needed

    # 3) Drop a single space BETWEEN two name spans if exactly one space separates them
    # Recompute spans first (due to step 2)
    name_spans = spans_from_mask(m)
    for idx in range(len(name_spans) - 1):
        a1, b1 = name_spans[idx]
        a2, b2 = name_spans[idx + 1]
        # if there is exactly one space between [b1, a2), and nothing else
        if a2 - b1 == 1 and b1 < len(s) and s[b1].isspace():
            if random.random() < p_drop_space_between_names:
                remove_char(b1)
                # indices shift; recompute spans to be safe
                name_spans = spans_from_mask(m)

    return ''.join(s), m




# -----------------------------
# Data Loading from Folder Tree
# -----------------------------

def _find_cases(data_root: str) -> List[str]:
    """
    A "case" is any immediate subfolder of data_root that contains
    'org' and 'red' directories.
    """
    cases = []
    for entry in sorted(os.listdir(data_root)):
        case_dir = os.path.join(data_root, entry)
        if not os.path.isdir(case_dir):
            continue
        org = os.path.join(case_dir, 'org')
        red = os.path.join(case_dir, 'red')
        if os.path.isdir(org) and os.path.isdir(red):
            cases.append(case_dir)
            
    print(f"Cases = {cases}")
    return cases
    
def _pair_files_for_case(case_dir: str) -> List[Tuple[str, str]]:
    """
    Returns list of (orig_path, redacted_path) for files with the same
    *relative* name under org/ and red/.
    """
    org_dir = os.path.join(case_dir, 'org')
    red_dir = os.path.join(case_dir, 'red')
    pairs = []
    for path in sorted(glob.glob(os.path.join(org_dir, '**', '*.tsv'), recursive=True)):
        rel = os.path.relpath(path, org_dir)
        cand = os.path.join(red_dir, rel)
        if os.path.isfile(cand):
            pairs.append((path, cand))
        else:
            sys.stderr.write(f"[WARN] Missing redacted for {path}\n")
    return pairs

def _is_upd_file(filename: str) -> bool:
    return bool(re.search(r"_upd[2-9]\.tsv$", filename))

def _read_tsv(path: str) -> Tuple[List[List[str]], List[str]]:
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter="\t")
        rows = list(reader)
    if not rows:
        return [], []
    headers = rows[0]
    data = rows[1:]
    # normalize row lengths
    L = len(headers)
    data = [r + [""] * (L - len(r)) if len(r) < L else r[:L] for r in data]
    return data, headers

def _write_tsv(path: str, rows: List[List[str]], headers: List[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(headers)
        for r in rows:
            w.writerow(r)

def _next_upd_path(org_path: str) -> str:
    base = os.path.basename(org_path)
    stem, ext = os.path.splitext(base)
    org_dir = os.path.dirname(org_path)
    for k in range(2, 100):  # 2..9 inclusive
        cand = os.path.join(org_dir, f"{stem}_upd{k}{ext}")
        if not os.path.exists(cand):
            return cand
    raise RuntimeError(f"All update slots _upd2.._upd9 are used for {org_path}")


def _matching_red_upd(org_upd_path: str, red_orig_path: str) -> str:
    red_dir = os.path.dirname(red_orig_path)
    fname = os.path.basename(org_upd_path)
    return os.path.join(red_dir, fname)

def generate_augmented_pairs_for_epoch(
    data_root: str,
    train_case_ids: List[str],
    names_file: str,
    min_pct: float = 0.1,
    max_pct: float = 3.0,
    label_placeholder: str = "[LABEL]",
    seed: int = 42,
    log_dir: Optional[str] = None,
) -> List[Tuple[str, str]]:
    """
    For all pairs under cases in `train_case_ids`, create *_updX.tsv files (X in [2..9])
    in org/ and red/ with the following rules:
      - Operate only on 'event' column (TSV).
      - Per file, independently sample additions_pct ~ U[min_pct, max_pct] and
        replacements_pct ~ U[min_pct, max_pct].
      - Globally across the file:
          * perform 'additions' (insert random names) and 'replacements' (replace eligible tokens)
            with the sampled counts,
          * ensure a single line never receives both add & replace.
      - Eligible replacement target: alphabetic, len>=5 (non-numeric).
      - Insert with a single space as separator (detect words via punctuation for deciding positions).
      - Update the red counterpart accordingly: inserted names -> [LABEL], replaced tokens -> [LABEL].
      - Save as *_updX.tsv (first free X in [2..9]); if none free, raise RuntimeError.

    Returns: list of (org_upd_path, red_upd_path) created for this epoch.
    """
    rng = random.Random(seed)
    names = _load_names(names_file)
    cases = _find_cases(data_root)
    # Map case_id -> case_dir
    case_map = {os.path.basename(c.rstrip("/")): c for c in cases}

    created: List[Tuple[str, str]] = []

    for case_id in train_case_ids:
        case_dir = case_map.get(case_id)
        if not case_dir:
            continue
        pairs = _pair_files_for_case(case_dir)  # (org_path, red_path)
        for org_path, red_path in pairs:
            # Only operate on base files (no previous _updX)
            base = os.path.basename(org_path)
            if _is_upd_file(base):
                continue

            # Read TSVs
            org_rows, headers = _read_tsv(org_path)
            red_rows, headers_red = _read_tsv(red_path)

            # Validate same header
            if headers_red != headers:
                raise RuntimeError(f"Header mismatch between {org_path} and {red_path}")

            # Find 'event' column
            if "event" not in headers:
                # Skip silently if column absent in this file
                continue
            ev_idx = headers.index("event")

            # Compute total words across event column
            total_words = 0
            eligible_repl_positions = []  # (row_idx, token_idx, span)
            tokenized_rows_cache = {}     # row_idx -> tokens list (for reuse)

            for i, row in enumerate(org_rows):
                text = row[ev_idx]
                toks = _tokenize_words_and_seps(text)  # list of (is_word, text)
                tokenized_rows_cache[i] = toks

                # word count
                wc = sum(1 for isw, _t in toks if isw)
                total_words += wc

                # collect eligible replacements (alpha & len>=5, not numeric)
                for ti, (isw, t) in enumerate(toks):
                    if not isw:
                        continue
                    if _eligible_token_for_replacement(t):
                        eligible_repl_positions.append((i, ti, t))

            if total_words == 0:
                # nothing to do for this file
                continue

            # Per-file random percentages (inclusive range)
            add_pct = rng.uniform(min_pct, max_pct) / 100.0
            rep_pct = rng.uniform(min_pct, max_pct) / 100.0

            # Convert to counts
            target_adds = max(0, int(round(add_pct * total_words)))
            target_reps = max(0, int(round(rep_pct * total_words)))

            # If there are no eligible replacements, force reps=0
            if not eligible_repl_positions:
                target_reps = 0

            # Assign operations to rows; ensure no row gets both
            row_indices = list(range(len(org_rows)))
            rng.shuffle(row_indices)
            chosen_for_add = set()
            chosen_for_rep = set()

            # We will attempt one change per selected row until we hit targets
            # (That keeps changes modest and spreads them out.)
            # Adds:
            for ri in row_indices:
                if len(chosen_for_add) >= target_adds:
                    break
                if ri in chosen_for_rep:
                    continue
                # require at least one insertion point (i.e., at least 1 boundary)
                toks = tokenized_rows_cache[ri]
                if _count_insertion_boundaries(toks) == 0:
                    continue
                chosen_for_add.add(ri)

            # Replacements:
            # Build map row -> eligible token indices
            per_row_eligible: Dict[int, List[int]] = {}
            for ri, ti, _t in eligible_repl_positions:
                per_row_eligible.setdefault(ri, []).append(ti)
            for ri in row_indices:
                if len(chosen_for_rep) >= target_reps:
                    break
                if ri in chosen_for_add:
                    continue
                if ri not in per_row_eligible:
                    continue
                chosen_for_rep.add(ri)

            # Apply changes
            new_org_rows = [r[:] for r in org_rows]
            new_red_rows = [r[:] for r in red_rows]

            add_count_done = 0
            rep_count_done = 0

            # Addition changes
            for ri in chosen_for_add:
                name = rng.choice(names)
                toks = tokenized_rows_cache[ri]
                new_event_text, inserted = _apply_insertion(toks, name, rng)
                if inserted:
                    # org: insert name
                    new_org_rows[ri][ev_idx] = new_event_text
                    # red: insert [LABEL] at the same place
                    toks_red = _tokenize_words_and_seps(new_red_rows[ri][ev_idx])
                    new_red_rows[ri][ev_idx], _ = _apply_insertion(toks_red, label_placeholder, rng, fixed_position=inserted)
                    add_count_done += 1

            # Replacement changes
            for ri in chosen_for_rep:
                name = rng.choice(names)
                toks = tokenized_rows_cache[ri]
                if not any(isw for isw, _t in toks):
                    continue
                # get eligible positions for this row
                elig_positions = [ti for ti, (isw, t) in enumerate(toks) if isw and _eligible_token_for_replacement(t)]
                if not elig_positions:
                    continue
                ti = rng.choice(elig_positions)
                # org: replace token with name
                new_text = _apply_replacement(toks, ti, name)
                new_org_rows[ri][ev_idx] = new_text
                # red: replace the same token with [LABEL]
                toks_red = _tokenize_words_and_seps(new_red_rows[ri][ev_idx])
                new_red_rows[ri][ev_idx] = _apply_replacement(toks_red, ti, label_placeholder, safe_if_short=True)
                rep_count_done += 1

            # If nothing changed, skip saving
            if add_count_done == 0 and rep_count_done == 0:
                continue

            # Determine next _updX suffix and write
            org_out = _next_upd_path(org_path)
            red_out = _matching_red_upd(org_out, red_path)

            _write_tsv(org_out, new_org_rows, headers)
            _write_tsv(red_out, new_red_rows, headers)

            created.append((org_out, red_out))

            # Per-file log (append)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
                base = os.path.basename(org_path)
                log_path = os.path.join(log_dir, f"{base}.log.tsv")
                with open(log_path, "a", encoding="utf-8", newline="") as f:
                    w = csv.writer(f, delimiter="\t")
                    # header once per file if empty
                    if f.tell() == 0:
                        w.writerow(["file", "adds_done", "replacements_done", "add_pct", "rep_pct"])
                    w.writerow([base, add_count_done, rep_count_done, f"{add_pct*100:.3f}", f"{rep_pct*100:.3f}"])

    return created

# ---------- Helpers ----------

WORD_RE = re.compile(r"^[A-Za-z][A-Za-z'\-]{4,}$")  # alpha, len>=5

def _eligible_token_for_replacement(tok: str) -> bool:
    if WORD_RE.match(tok) is None:
        return False
    # Exclude pure numbers or code-like with digits
    if any(ch.isdigit() for ch in tok):
        return False
    return True

def _tokenize_words_and_seps(text: str):
    """
    Split into [ (is_word, token), ... ] where is_word=True for [A-Za-z'-]+ chunks,
    and separators (spaces, punctuation) are preserved as is_word=False tokens.
    """
    out = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isalpha() or ch in "'-":
            j = i + 1
            while j < n and (text[j].isalpha() or text[j] in "'-"):
                j += 1
            out.append((True, text[i:j]))
            i = j
        else:
            j = i + 1
            while j < n and not (text[j].isalpha() or text[j] in "'-"):
                j += 1
            out.append((False, text[i:j]))
            i = j
    return out

def _count_insertion_boundaries(toks) -> int:
    # boundaries: positions between tokens (including ends)
    return max(0, len(toks) + 1)  # we can always insert at start/end

def _apply_insertion(toks, name: str, rng: random.Random, fixed_position: Optional[int] = None):
    """
    Insert name using ' ' spacing at a random boundary (or fixed_position if provided).
    Returns (new_text, inserted_position_index)
      - inserted_position_index: integer boundary in [0 .. len(toks)] or None if no-op
    """
    if len(toks) == 0:
        return (name, 0)
    boundaries = list(range(len(toks) + 1))
    pos = fixed_position if fixed_position is not None else rng.choice(boundaries)

    # Build with a single space around inserted token as needed.
    out = []
    for b in range(len(toks) + 1):
        if b == pos:
            # Ensure single preceding space if not at start
            if out and not out[-1].endswith(" "):
                out.append(" ")
            out.append(name)
            # Ensure a trailing space if next token is a word (to separate)
            if b < len(toks):
                out.append(" ")
        if b < len(toks):
            out.append(toks[b][1])
    return ("".join(out), pos)

def _apply_replacement(toks, token_index: int, name: str, safe_if_short: bool = False) -> str:
    # Replace only if token_index points to a word; otherwise, either no-op or safe fallback
    if token_index < 0 or token_index >= len(toks):
        return "".join(t for _isw, t in toks)
    isw, t = toks[token_index]
    if not isw:
        if safe_if_short:
            return "".join(t for _isw, t in toks)
        else:
            # find next word to the right to replace
            for j in range(token_index + 1, len(toks)):
                if toks[j][0]:
                    token_index = j
                    break
            else:
                return "".join(t for _isw, t in toks)
    # Replace at token_index
    out = []
    for i, (wflag, tok) in enumerate(toks):
        if i == token_index and wflag:
            out.append(name)
        else:
            out.append(tok)
    return "".join(out)


def _load_names(path: str) -> List[str]:
    names = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s:
                names.append(s)
    if not names:
        raise RuntimeError(f"No names found in {path}")
    return names


