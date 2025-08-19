#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ENT extractor (standalone, ASCII-safe) with verbose mode

What it does
------------
- Reads a Natus/XLTEK .ent file (binary header + CP1252-like text).
- Parses the S-expression style "key-tree" text: (."Key", Value) with nesting.
- Exports:
  1) ent_full_tree.json          full parsed tree
  2) ent_kv_flat.csv             flattened key/value table
  3) channels_mapping.csv        C1..C{N} explicit and index-based guesses
  4) channel_blocks.csv          one row per Channel(...) block
  5) notes.csv                   heuristic collection of comments/notes

Verbosity
---------
- Default (no -v): minimal output.
- -v : info logs (file size, counts, output paths).
- -vv: debug logs (encoding used, parse span, token counts, first tokens, timings).

Usage
-----
python ent_extract.py path/to/file.ent --outdir ./ent_out -v
python ent_extract.py path/to/file.ent --outdir ./ent_out -vv
Options: --max-ch 256, --encoding cp1252, --log-file path, --verbose (-v, -vv)

Design
------
- Tolerant CP1252 decode for the text part. Binary header is ignored.
- Robust recursive-descent parser for tuples and (."Key", value) pairs.
- Explicit mapping comes from Channel blocks with From_Name="C###" and To_Name.
- Positional mapping guesses C1->ChanNames[0], C2->ChanNames[1], etc.
"""

import argparse
import json
import os
import re
import sys
import csv
import time
from typing import Any, Tuple, List, Dict

# ----------------------------
# Verbose logging helpers
# ----------------------------
VERBOSITY = 0
_LOG_FILE_HANDLE = None

def _log_write(msg: str):
    global _LOG_FILE_HANDLE
    print(msg, file=sys.stderr)
    if _LOG_FILE_HANDLE:
        try:
            _LOG_FILE_HANDLE.write(msg + "\n")
            _LOG_FILE_HANDLE.flush()
        except Exception:
            pass

def log_info(msg: str):
    if VERBOSITY >= 1:
        _log_write(msg)

def log_debug(msg: str):
    if VERBOSITY >= 2:
        _log_write(msg)

# ----------------------------
# Lexer
# ----------------------------
Token = Tuple[str, Any]  # (type, value)

class Lexer:
    def __init__(self, s: str):
        self.s = s
        self.n = len(s)
        self.i = 0

    def _peek(self, k=0):
        j = self.i + k
        return self.s[j] if j < self.n else ""

    def _adv(self, k=1):
        self.i += k

    def tokens(self):
        s = self.s
        n = self.n

        while self.i < n:
            ch = self._peek()

            if ch in " \t\r\n":
                start = self.i
                while self._peek() in " \t\r\n":
                    self._adv()
                yield ("WS", s[start:self.i])
                continue

            if ch == "(":
                self._adv(); yield ("LPAREN", "("); continue
            if ch == ")":
                self._adv(); yield ("RPAREN", ")"); continue
            if ch == ",":
                self._adv(); yield ("COMMA", ","); continue

            # ."<KEY>"
            if ch == "." and self._peek(1) == "\"":
                self._adv(2)
                yield ("DOTQUOTE", '."')
                key_buf = []
                while True:
                    c = self._peek()
                    if c == "":
                        break
                    if c == "\"":
                        self._adv()
                        break
                    if c == "\\" and self._peek(1) == "\"":
                        key_buf.append("\""); self._adv(2)
                    else:
                        key_buf.append(c); self._adv()
                yield ("KEY", "".join(key_buf))
                continue

            # "string"
            if ch == "\"":
                self._adv()
                buf = []
                while True:
                    c = self._peek()
                    if c == "":
                        break
                    if c == "\"":
                        self._adv()
                        break
                    if c == "\\":
                        nxt = self._peek(1)
                        if nxt == "n":
                            buf.append("\n"); self._adv(2)
                        elif nxt == "r":
                            buf.append("\r"); self._adv(2)
                        elif nxt == "t":
                            buf.append("\t"); self._adv(2)
                        elif nxt == "\"":
                            buf.append("\""); self._adv(2)
                        elif nxt == "\\":
                            buf.append("\\"); self._adv(2)
                        else:
                            buf.append("\\"); self._adv()
                        continue
                    buf.append(c); self._adv()
                yield ("STRING", "".join(buf))
                continue

            # number
            if ch.isdigit() or (ch in "+-" and self._peek(1).isdigit()):
                start = self.i
                while True:
                    p = self._peek()
                    if not p or not re.match(r"[0-9eE\+\-\.]", p):
                        break
                    self._adv()
                raw = s[start:self.i]
                try:
                    if any(c in raw for c in ".eE"):
                        val = float(raw)
                    else:
                        val = int(raw)
                    yield ("NUMBER", val)
                    continue
                except ValueError:
                    pass

            # ident
            if ch.isalpha() or ch == "_":
                start = self.i
                while True:
                    p = self._peek()
                    if not p or not re.match(r"[A-Za-z0-9_]", p):
                        break
                    self._adv()
                yield ("IDENT", s[start:self.i])
                continue

            # fallback: consume unknown char as IDENT
            self._adv()
            yield ("IDENT", ch)

# ----------------------------
# Parser
# ----------------------------
class ParserError(Exception):
    pass

class Parser:
    def __init__(self, tokens: List[Token]):
        self.toks = [t for t in tokens if t[0] != "WS"]
        self.i = 0
        self.n = len(self.toks)

    def _peek(self, k=0):
        j = self.i + k
        return self.toks[j] if j < self.n else None

    def _accept(self, kind: str):
        t = self._peek()
        if t and t[0] == kind:
            self.i += 1
            return t
        return None

    def _expect(self, kind: str):
        t = self._peek()
        if not t or t[0] != kind:
            raise ParserError("Expected %s, got %r" % (kind, t))
        self.i += 1
        return t

    def parse_any(self) -> Any:
        t = self._peek()
        if not t:
            return None
        tt, tv = t
        if tt == "LPAREN":
            return self.parse_node_or_tuple()
        if tt == "STRING":
            self._accept("STRING"); return tv
        if tt == "NUMBER":
            self._accept("NUMBER"); return tv
        if tt == "IDENT":
            self._accept("IDENT"); return tv
        if tt == "DOTQUOTE":
            return self.parse_implicit_pair()
        self.i += 1
        return tv

    def parse_implicit_pair(self):
        self._expect("DOTQUOTE")
        key = self._expect("KEY")[1]
        self._accept("COMMA")
        val = self.parse_any()
        return {key: val}

    def parse_node_or_tuple(self):
        self._expect("LPAREN")
        items = []
        is_pairs = (self._peek() and self._peek()[0] == "DOTQUOTE")

        if is_pairs:
            d = {}
            first = True
            while True:
                t = self._peek()
                if not t:
                    break
                if t[0] == "RPAREN":
                    self._accept("RPAREN"); break
                if not first:
                    self._accept("COMMA")
                first = False
                self._expect("DOTQUOTE")
                key = self._expect("KEY")[1]
                self._accept("COMMA")
                val = self.parse_any()
                if key in d:
                    if not isinstance(d[key], list):
                        d[key] = [d[key]]
                    d[key].append(val)
                else:
                    d[key] = val
            return d
        else:
            first = True
            while True:
                t = self._peek()
                if not t:
                    break
                if t[0] == "RPAREN":
                    self._accept("RPAREN"); break
                if not first:
                    self._accept("COMMA")
                first = False
                items.append(self.parse_any())
            return items

# ----------------------------
# Helpers
# ----------------------------
def find_first_paren_span(text: str):
    start = text.find("(")
    if start == -1:
        return None
    bal = 0
    end = None
    for idx in range(start, len(text)):
        c = text[idx]
        if c == "(":
            bal += 1
        elif c == ")":
            bal -= 1
            if bal == 0:
                end = idx + 1
    if end is None:
        return None
    return (start, end)

def walk_dict(obj: Any, path: List[str], out: List[Tuple[str, Any]]):
    if isinstance(obj, dict):
        for k, v in obj.items():
            walk_dict(v, path + [k], out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            walk_dict(v, path + ["[%d]" % i], out)
    else:
        out.append(("".join(path if path else [] if isinstance(obj, (str, int, float)) else path), obj))
        out[-1] = (".".join(path), obj)

def extract_chan_names(tree: Any) -> List[str]:
    result: List[str] = []
    def rec(o):
        nonlocal result
        if isinstance(o, dict):
            if "ChanNames" in o:
                vals = o["ChanNames"]
                if isinstance(vals, list):
                    result = [v for v in vals if isinstance(v, str)]
                return
            for v in o.values():
                rec(v)
        elif isinstance(o, list):
            for v in o:
                rec(v)
    rec(tree)
    return result

def find_channel_blocks(tree: Any) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    def rec(o):
        if isinstance(o, dict):
            if set(o.keys()) == {"Channel"} and isinstance(o["Channel"], dict):
                blocks.append(o["Channel"])
            for v in o.values():
                rec(v)
        elif isinstance(o, list):
            for v in o:
                rec(v)
    rec(tree)
    return blocks

def find_notes(tree: Any) -> List[Dict[str, Any]]:
    notes: List[Dict[str, Any]] = []
    def rec(o):
        if isinstance(o, dict):
            if any(k in o for k in ("Comment", "Note", "Annotation", "Montage")):
                if any(not isinstance(v, (dict, list)) for v in o.values()):
                    notes.append(o)
            for v in o.values():
                rec(v)
        elif isinstance(o, list):
            for v in o:
                rec(v)
    rec(tree)
    return notes

def explicit_c_map(channel_blocks: List[Dict[str, Any]]) -> Dict[str, str]:
    m: Dict[str, str] = {}
    for blk in channel_blocks:
        fn = blk.get("From_Name")
        tn = blk.get("To_Name")
        if isinstance(fn, str) and re.fullmatch(r"C\d+", fn) and isinstance(tn, str) and tn:
            m[fn] = tn
    return m

def write_json(path: str, obj: Any):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def write_csv(path: str, rows: List[Dict[str, Any]], fieldnames: List[str] = None):
    if fieldnames is None:
        keys = set()
        for r in rows:
            keys.update(r.keys())
        fieldnames = sorted(keys)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})

# ----------------------------
# Core parse
# ----------------------------
def parse_ent(path: str, encoding: str = "cp1252", debug_tokens: bool = False) -> Any:
    t0 = time.perf_counter()
    raw = open(path, "rb").read()
    t1 = time.perf_counter()
    log_info("[i] Read %d bytes from %s (%.3f s)" % (len(raw), path, (t1 - t0)))

    # Decode as specified encoding, ignoring undecodable bytes
    text = raw.decode(encoding, errors="ignore")
    log_debug("[d] Using decode encoding=%s (len(text)=%d)" % (encoding, len(text)))

    # Find first balanced S-expression span
    span = find_first_paren_span(text)
    if not span:
        raise RuntimeError("Could not find key-tree text in ENT (no '(' found).")
    start, end = span
    kt_text = text[start:end]
    log_debug("[d] First '(' at offset %d, span length %d" % (start, end - start))

    # Lex + parse
    lx = Lexer(kt_text)
    toks = list(lx.tokens())
    log_debug("[d] Tokenized %d tokens (including punctuation; WS removed later)" % (len(toks)))
    if debug_tokens and VERBOSITY >= 2:
        preview = toks[:20]
        log_debug("[d] First tokens: %s" % (" ".join([t[0] for t in preview])))

    ps = Parser([t for t in toks if t[0] != "WS"])
    t2 = time.perf_counter()
    tree = ps.parse_any()
    t3 = time.perf_counter()
    log_info("[i] Parsed key-tree (lex+parse %.3f s). Total elapsed %.3f s" % ((t3 - t2), (t3 - t0)))
    return tree

def flatten_tree_to_kv(tree: Any) -> List[Dict[str, Any]]:
    flat: List[Tuple[str, Any]] = []
    if isinstance(tree, dict):
        for k, v in tree.items():
            walk_dict(v, [k], flat)
    else:
        walk_dict(tree, [], flat)
    rows: List[Dict[str, Any]] = []
    for path, val in flat:
        if isinstance(val, (dict, list)):
            sval = json.dumps(val, ensure_ascii=False)
        else:
            sval = str(val)
        rows.append({"path": path, "value": sval})
    return rows

# ----------------------------
# Main
# ----------------------------
def main():
    global VERBOSITY, _LOG_FILE_HANDLE

    ap = argparse.ArgumentParser(description="Extract all information from a Natus/XLTEK ENT file.")
    ap.add_argument("ent_path", help=".ent file path")
    ap.add_argument("--outdir", default="./ent_out", help="output directory")
    ap.add_argument("--max-ch", type=int, default=256, help="C1..C{N} positional mapping size")
    ap.add_argument("--encoding", default="cp1252", help="text decode for key-tree (default cp1252)")
    ap.add_argument("-v", "--verbose", action="count", default=0,
                    help="increase verbosity (-v for info, -vv for debug)")
    ap.add_argument("--log-file", default=None, help="optional path to also write logs to a file")
    args = ap.parse_args()

    VERBOSITY = int(args.verbose or 0)
    if args.log_file:
        try:
            _LOG_FILE_HANDLE = open(args.log_file, "w", encoding="utf-8")
        except Exception as e:
            print("Warning: could not open log file %r: %s" % (args.log_file, e), file=sys.stderr)

    t_start = time.perf_counter()

    os.makedirs(args.outdir, exist_ok=True)
    log_info("[i] Output directory: %s" % args.outdir)

    log_info("[i] Reading ENT with encoding=%s" % args.encoding)
    tree = parse_ent(args.ent_path, encoding=args.encoding, debug_tokens=True)

    # 1) Full JSON
    full_json_path = os.path.join(args.outdir, "ent_full_tree.json")
    write_json(full_json_path, tree)
    log_info("[+] Wrote %s" % full_json_path)

    # 2) Flat KV table
    kv_rows = flatten_tree_to_kv(tree)
    kv_csv_path = os.path.join(args.outdir, "ent_kv_flat.csv")
    write_csv(kv_csv_path, kv_rows, fieldnames=["path", "value"])
    log_info("[+] Wrote %s (%d rows)" % (kv_csv_path, len(kv_rows)))

    # 3) Channel names and blocks
    chan_names = extract_chan_names(tree)
    ch_blocks = find_channel_blocks(tree)
    log_info("[i] ChanNames count: %d" % len(chan_names))
    log_info("[i] Channel blocks: %d" % len(ch_blocks))

    # 3A) channels_mapping.csv
    explicit_map = explicit_c_map(ch_blocks)
    rows = []
    N = args.max_ch
    for ch in range(1, N + 1):
        c_lab = "C%d" % ch
        guess = chan_names[ch - 1] if ch - 1 < len(chan_names) else ""
        rows.append({
            "Channel_Number": c_lab,
            "Explicit_To_Name": explicit_map.get(c_lab, ""),
            "Name_guess_from_ChanNames": guess
        })
    chmap_csv = os.path.join(args.outdir, "channels_mapping.csv")
    write_csv(chmap_csv, rows, fieldnames=["Channel_Number", "Explicit_To_Name", "Name_guess_from_ChanNames"])
    log_info("[+] Wrote %s (C1..C%d; explicit=%d)" % (chmap_csv, N, len(explicit_map)))

    # 3B) channel_blocks.csv
    canonical = ["From_Name", "To_Name", "ChanIndex", "Group", "Color", "HighFreq", "LowFreq", "Notch", "Gain", "Type"]
    dyn_keys = set()
    for blk in ch_blocks:
        for k in blk.keys():
            if k not in canonical:
                dyn_keys.add(k)
    fieldnames = canonical + sorted(dyn_keys)

    chblk_rows = []
    for blk in ch_blocks:
        row = {}
        for k in fieldnames:
            v = blk.get(k, "")
            if isinstance(v, (dict, list)):
                v = json.dumps(v)
            row[k] = v
        chblk_rows.append(row)
    chblk_csv = os.path.join(args.outdir, "channel_blocks.csv")
    write_csv(chblk_csv, chblk_rows, fieldnames=fieldnames)
    log_info("[+] Wrote %s (%d rows)" % (chblk_csv, len(chblk_rows)))
    log_debug("[d] Channel block fields: %s" % ", ".join(fieldnames))

    # 4) notes.csv
    notes = find_notes(tree)
    note_keys = ["Comment", "Note", "Annotation", "ChannelName", "Channel", "FileTime", "TimeStamp", "Montage"]
    extra = set()
    for n in notes:
        for k in n.keys():
            if k not in note_keys:
                extra.add(k)
    note_fieldnames = note_keys + sorted(extra)
    note_rows = []
    for n in notes:
        row = {}
        for k in note_fieldnames:
            v = n.get(k, "")
            if isinstance(v, (dict, list)):
                v = json.dumps(v)
            row[k] = v
        note_rows.append(row)
    notes_csv = os.path.join(args.outdir, "notes.csv")
    write_csv(notes_csv, note_rows, fieldnames=note_fieldnames)
    log_info("[+] Wrote %s (%d rows)" % (notes_csv, len(note_rows)))
    if VERBOSITY >= 2 and note_rows:
        log_debug("[d] Note fields: %s" % ", ".join(note_fieldnames))

    # Final summary
    t_end = time.perf_counter()
    log_info("[Done] Elapsed: %.3f s" % (t_end - t_start))
    log_info("JSON : %s" % full_json_path)
    log_info("KV   : %s" % kv_csv_path)
    log_info("MAP  : %s" % chmap_csv)
    log_info("CHBLK: %s" % chblk_csv)
    log_info("NOTES: %s" % notes_csv)

    if _LOG_FILE_HANDLE:
        try:
            _LOG_FILE_HANDLE.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()
