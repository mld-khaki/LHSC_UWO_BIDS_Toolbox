#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ENT extractor (standalone)

What it does
------------
- Reads a Natus/XLTEK .ent file (binary with an embedded "key-tree"-like text section).
- Locates and parses the key-tree text that looks like: (."Key", Value), nested with parentheses.
- Extracts *everything* it finds into:
  1) <outdir>/ent_full_tree.json              # full parsed tree (lossless-ish)
  2) <outdir>/ent_kv_flat.csv                 # flattened key/value table (best-effort)
  3) <outdir>/channels_mapping.csv            # C1..C256 mapping (explicit & positional guess)
  4) <outdir>/channel_blocks.csv              # one row per Channel(...) block with all fields
  5) <outdir>/notes.csv                       # montage changes / comments / annotations if present

Design notes
------------
- Inspired by NYU OLAB's XltekDataReader "key_tree" notion for ENT files; this script is
  self-contained (no repo dependency) and aims to capture similar semantics. See:
  https://github.com/nyuolab/XltekDataReader (archived on 2024-06-13).  # (reference only)

- The ENT files often begin with a binary header followed by a CP-1252-encoded S-expression-ish
  "key-tree" text. We detect the first '(' and parse from there.

- Grammar (simplified):
    node := '(' pair (',' pair)* ')'
    pair := '."' key '", ' value
    key  := chars until next '"'
    value := string | number | node | tuple
    string := '"' ... '"'  (supports escaped quotes and \r\n)
    number := int or float (we accept forms like 11.50000000000)
    tuple := '(' item (',' item)* ')'   # many ENT lists are bare tuples of values

- Robustness: tolerant CP-1252 decode; skips unparseable tails gracefully; logs progress.

- The script makes two kinds of channel mappings:
  (A) Explicit per-channel mapping where a Channel block has From_Name="C###" and To_Name="...".
  (B) Positional guess using the ChanNames list (index 0 -> C1, index 1 -> C2, …).

- Outputs are UTF-8 with CRLF-safe content.

Usage
-----
python ent_extract.py /path/to/file.ent --outdir ./ent_out

Optional flags:
  --max-ch 256      # size of positional C-map (default 256)
  --encoding cp1252 # override text decode if needed
  --verbose         # more logs

"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import csv
from typing import Any, Tuple, List, Dict, Union

# ----------------------------
# Small logging helper
# ----------------------------
def log(msg: str):
    print(msg, file=sys.stderr)

# ----------------------------
# Lexer for the key-tree text
# ----------------------------
Token = Tuple[str, Any]  # (type, value)

class Lexer:
    """
    Produces tokens from the ENT key-tree text.
    Recognizes: LPAREN, RPAREN, COMMA, DOTQUOTE, STRING, NUMBER, IDENT, WS
    """
    def __init__(self, s: str):
        self.s = s
        self.n = len(s)
        self.i = 0

    def _peek(self, k=0):
        j = self.i + k
        return self.s[j] if j < self.n else ''

    def _adv(self, k=1):
        self.i += k

    def tokens(self):
        s = self.s
        n = self.n
        i = self.i

        while self.i < n:
            ch = self._peek()

            if ch in ' \t\r\n':
                # coalesce whitespace into single WS or skip entirely
                start = self.i
                while self._peek() in ' \t\r\n':
                    self._adv()
                yield ("WS", s[start:self.i])
                continue

            if ch == '(':
                self._adv()
                yield ("LPAREN", "(")
                continue
            if ch == ')':
                self._adv()
                yield ("RPAREN", ")")
                continue
            if ch == ',':
                self._adv()
                yield ("COMMA", ",")
                continue

            # DOTQUOTE introduces a key like (."Key", ...)
            if ch == '.' and self._peek(1) == '"':
                self._adv(2)
                yield ("DOTQUOTE", '."')
                # Now lex the following key string up to unescaped '"'
                key_buf = []
                while True:
                    c = self._peek()
                    if c == '':
                        break
                    if c == '"':
                        self._adv()
                        break
                    # support \" inside? ENT keys usually don't escape quotes, but be safe
                    if c == '\\' and self._peek(1) == '"':
                        key_buf.append('"')
                        self._adv(2)
                    else:
                        key_buf.append(c)
                        self._adv()
                yield ("KEY", ''.join(key_buf))
                # after key, optional whitespace and an expected comma might follow, leave to parser
                continue

            # string literal
            if ch == '"':
                self._adv()
                buf = []
                while True:
                    c = self._peek()
                    if c == '':
                        break
                    if c == '"':
                        self._adv()
                        break
                    if c == '\\':
                        # handle \n, \r, \t, \", \\ minimally
                        nxt = self._peek(1)
                        if nxt == 'n':
                            buf.append('\n'); self._adv(2)
                        elif nxt == 'r':
                            buf.append('\r'); self._adv(2)
                        elif nxt == 't':
                            buf.append('\t'); self._adv(2)
                        elif nxt == '"':
                            buf.append('"'); self._adv(2)
                        elif nxt == '\\':
                            buf.append('\\'); self._adv(2)
                        else:
                            # unknown escape, keep raw
                            buf.append('\\'); self._adv()
                        continue
                    buf.append(c)
                    self._adv()
                yield ("STRING", ''.join(buf))
                continue

            # number literal (int/float)
            if ch.isdigit() or (ch in '+-' and self._peek(1).isdigit()):
                start = self.i
                # accept digits, dot, exponent e/E, plus/minus
                while self._peek() and re.match(r'[0-9eE\+\-\.]', self._peek()):
                    self._adv()
                raw = s[start:self.i]
                # Try float then int
                try:
                    if any(c in raw for c in '.eE'):
                        val = float(raw)
                    else:
                        val = int(raw)
                    yield ("NUMBER", val)
                    continue
                except ValueError:
                    # fall through to IDENT
                    pass

            # identifiers (occasionally appear)
            if ch.isalpha() or ch in '_':
                start = self.i
                while self._peek() and re.match(r'[A-Za-z0-9_]', self._peek()):
                    self._adv()
                yield ("IDENT", s[start:self.i])
                continue

            # unknown char, emit as IDENT to avoid stalls
            self._adv()
            yield ("IDENT", ch)

# ----------------------------
# Parser (recursive-descent)
# ----------------------------
class ParserError(Exception):
    pass

class Parser:
    def __init__(self, tokens: List[Token]):
        # filter out WS tokens for simplicity
        self.toks = [t for t in tokens if t[0] != "WS"]
        self.i = 0
        self.n = len(self.toks)

    def _peek(self, k=0) -> Token | None:
        j = self.i + k
        return self.toks[j] if j < self.n else None

    def _accept(self, kind: str) -> Token | None:
        t = self._peek()
        if t and t[0] == kind:
            self.i += 1
            return t
        return None

    def _expect(self, kind: str) -> Token:
        t = self._peek()
        if not t or t[0] != kind:
            raise ParserError(f"Expected {kind}, got {t}")
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
            self._accept("STRING")
            return tv
        if tt == "NUMBER":
            self._accept("NUMBER")
            return tv
        if tt == "IDENT":
            self._accept("IDENT")
            return tv
        # Some ENT parts may start with DOTQUOTE when parser expects a node
        if tt == "DOTQUOTE":
            # treat as implicit ( DOTQUOTE KEY , value )
            # We'll wrap this pair as {key: value}
            return self.parse_implicit_node()
        # Unhandled; consume and return raw
        self.i += 1
        return tv

    def parse_implicit_node(self) -> dict:
        """
        Handle a dangling pair that looks like: ."<key>", <value>
        We box it into {key: value}
        """
        self._expect("DOTQUOTE")
        key = self._expect("KEY")[1]
        # optional comma
        self._accept("COMMA")
        val = self.parse_any()
        return {key: val}

    def parse_node_or_tuple(self) -> Any:
        self._expect("LPAREN")
        # Could be a sequence of pairs (."Key", value) OR a simple tuple/list of values
        items: List[Any] = []
        # Lookahead: if the next is DOTQUOTE, we consider it "pairs node"
        is_pairs = False
        if self._peek() and self._peek()[0] == "DOTQUOTE":
            is_pairs = True

        if is_pairs:
            d: Dict[str, Any] = {}
            first = True
            while True:
                t = self._peek()
                if not t:
                    break
                if t[0] == "RPAREN":
                    self._accept("RPAREN")
                    break
                if not first:
                    self._accept("COMMA")
                first = False
                # expect pair
                self._expect("DOTQUOTE")
                key = self._expect("KEY")[1]
                self._accept("COMMA")
                val = self.parse_any()
                # if same key repeats, store as list
                if key in d:
                    if not isinstance(d[key], list):
                        d[key] = [d[key]]
                    d[key].append(val)
                else:
                    d[key] = val
            return d
        else:
            # tuple/list of values
            first = True
            while True:
                t = self._peek()
                if not t:
                    break
                if t[0] == "RPAREN":
                    self._accept("RPAREN")
                    break
                if not first:
                    self._accept("COMMA")
                first = False
                items.append(self.parse_any())
            return items

# ----------------------------
# Utilities to *find* things
# ----------------------------
def find_first_paren_span(text: str) -> Tuple[int, int] | None:
    """
    ENT often has binary header then '(' ... ) block(s).
    We find the first '(' and then try to grab a balanced segment until overall balance == 0.
    If there are multiple top-level S-exprs, we take the largest balanced span.
    """
    start = text.find('(')
    if start == -1:
        return None
    bal = 0
    end = None
    for idx in range(start, len(text)):
        c = text[idx]
        if c == '(':
            bal += 1
        elif c == ')':
            bal -= 1
            if bal == 0:
                end = idx + 1
                # Don’t break; sometimes ENT packs several top-level nodes; capture the longest
    if end is None:
        return None
    return (start, end)

def walk_dict(obj: Any, path: List[str], out: List[Tuple[str, Any]]):
    """
    Flatten nested dict/list into dotted paths for a generic KV table.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            walk_dict(v, path + [k], out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            walk_dict(v, path + [f"[{i}]"], out)
    else:
        out.append(('.'.join(path), obj))

def as_list(x) -> List[Any]:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]

# ----------------------------
# Extraction logic
# ----------------------------
def extract_chan_names(tree: Any) -> List[str]:
    """
    Search the parsed tree for a field named "ChanNames"
    """
    result = []

    def rec(o):
        nonlocal result
        if isinstance(o, dict):
            if "ChanNames" in o:
                vals = o["ChanNames"]
                # ChanNames often appears as a tuple/list of quoted strings
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
    """
    ENT often encodes channel blocks like:
      (."Channel", (."From_Name","C3"), (."To_Name","F3"), (."ChanIndex", 3), ...)
    After parsing, such a node tends to look like:
      {"Channel": {"From_Name":"C3", "To_Name":"F3", "ChanIndex":3, ...}}
    We traverse and collect all dicts whose single key == "Channel".
    """
    blocks = []

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
    """
    Notes/comments often appear with keys like "Comment", "ChannelName", "FileTime" etc.
    We collect small dicts that have a "Comment" field (or "Note") anywhere.
    """
    notes = []

    def rec(o):
        if isinstance(o, dict):
            # heuristic: if it has a "Comment" (or "Note") field, treat as a note record
            if any(k in o for k in ("Comment", "Note", "Annotation", "Montage")):
                # avoid trivial dicts that are just scalars
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
    """
    From channel blocks, extract pairs From_Name="C###" -> To_Name="Label"
    """
    m = {}
    for blk in channel_blocks:
        fn = blk.get("From_Name")
        tn = blk.get("To_Name")
        if isinstance(fn, str) and re.fullmatch(r"C\d+", fn) and isinstance(tn, str) and tn:
            m[fn] = tn
    return m

# ----------------------------
# I/O helpers
# ----------------------------
def write_json(path: str, obj: Any):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def write_csv(path: str, rows: List[Dict[str, Any]], fieldnames: List[str] | None = None):
    # Derive fieldnames if not provided
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
# Main
# ----------------------------
def parse_ent(path: str, encoding: str = "cp1252") -> Any:
    raw = open(path, "rb").read()
    # Best-effort CP1252 decode (common for ENT text sections)
    text = raw.decode(encoding, errors="ignore")

    # Find the first balanced S-expression span
    span = find_first_paren_span(text)
    if not span:
        raise RuntimeError("Could not locate key-tree text in ENT (no '(' found).")
    start, end = span
    kt_text = text[start:end]

    # Lex + parse
    lx = Lexer(kt_text)
    toks = list(lx.tokens())
    ps = Parser(toks)
    try:
        tree = ps.parse_any()
    except ParserError as e:
        # If partial parsing, return what we can
        raise RuntimeError(f"Parse error: {e}")
    return tree

def flatten_tree_to_kv(tree: Any) -> List[Dict[str, Any]]:
    flat: List[Tuple[str, Any]] = []
    if isinstance(tree, dict):
        for k, v in tree.items():
            walk_dict(v, [k], flat)
    else:
        walk_dict(tree, [], flat)

    rows = []
    for path, val in flat:
        # Normalize scalars to strings for CSV friendliness
        if isinstance(val, (dict, list)):
            sval = json.dumps(val, ensure_ascii=False)
        else:
            sval = str(val)
        rows.append({"path": path, "value": sval})
    return rows

def main():
    ap = argparse.ArgumentParser(description="Extracts all information from a Natus/XLTEK ENT file.")
    ap.add_argument("ent_path", help=".ent file path")
    ap.add_argument("--outdir", default="./ent_out", help="output directory")
    ap.add_argument("--max-ch", type=int, default=256, help="C1..C{N} positional mapping size (default 256)")
    ap.add_argument("--encoding", default="cp1252", help="text decode for key-tree (default cp1252)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    if args.verbose:
        log(f"[i] Reading: {args.ent_path}")
    tree = parse_ent(args.ent_path, encoding=args.encoding)

    # 1) Full JSON dump
    full_json_path = os.path.join(args.outdir, "ent_full_tree.json")
    write_json(full_json_path, tree)
    if args.verbose:
        log(f"[+] Wrote {full_json_path}")

    # 2) Flat KV table
    kv_rows = flatten_tree_to_kv(tree)
    kv_csv_path = os.path.join(args.outdir, "ent_kv_flat.csv")
    write_csv(kv_csv_path, kv_rows, fieldnames=["path", "value"])
    if args.verbose:
        log(f"[+] Wrote {kv_csv_path}  ({len(kv_rows)} rows)")

    # 3) Channel names & blocks
    chan_names = extract_chan_names(tree)  # List[str]
    ch_blocks = find_channel_blocks(tree)  # List[dict]
    if args.verbose:
        log(f"[i] Found ChanNames: {len(chan_names)}")
        log(f"[i] Found Channel blocks: {len(ch_blocks)}")

    # 3A) channels_mapping.csv: For C1..C{N}, include explicit To_Name and positional guess
    explicit_map = explicit_c_map(ch_blocks)
    rows = []
    N = args.max_ch
    for ch in range(1, N + 1):
        c_lab = f"C{ch}"
        guess = chan_names[ch - 1] if ch - 1 < len(chan_names) else ""
        rows.append({
            "Channel_Number": c_lab,
            "Explicit_To_Name": explicit_map.get(c_lab, ""),
            "Name_guess_from_ChanNames": guess
        })
    chmap_csv = os.path.join(args.outdir, "channels_mapping.csv")
    write_csv(chmap_csv, rows, fieldnames=["Channel_Number", "Explicit_To_Name", "Name_guess_from_ChanNames"])
    if args.verbose:
        log(f"[+] Wrote {chmap_csv}")

    # 3B) channel_blocks.csv: dump each Channel block as its own row, flattening shallow dicts
    # Keep commonly seen fields up front, then append extras dynamically
    canonical = ["From_Name", "To_Name", "ChanIndex", "Group", "Color", "HighFreq", "LowFreq", "Notch", "Gain", "Type"]
    # Build fieldnames dynamically
    dyn_keys = set()
    for blk in ch_blocks:
        dyn_keys.update(k for k in blk.keys() if k not in canonical)
    fieldnames = canonical + sorted(dyn_keys)

    chblk_rows = []
    for blk in ch_blocks:
        row = {k: (blk.get(k, "") if not isinstance(blk.get(k, ""), (dict, list)) else json.dumps(blk.get(k)))
               for k in fieldnames}
        chblk_rows.append(row)
    chblk_csv = os.path.join(args.outdir, "channel_blocks.csv")
    write_csv(chblk_csv, chblk_rows, fieldnames=fieldnames)
    if args.verbose:
        log(f"[+] Wrote {chblk_csv}  ({len(chblk_rows)} rows)")

    # 4) notes.csv: collect likely notes/comments (heuristic)
    notes = find_notes(tree)
    # Canonical columns to try to include
    note_keys = ["Comment", "Note", "Annotation", "ChannelName", "Channel", "FileTime", "TimeStamp", "Montage"]
    # gather additional keys seen across notes
    extra = set()
    for n in notes:
        extra.update(k for k in n.keys() if k not in note_keys)
    note_fieldnames = note_keys + sorted(extra)

    note_rows = []
    for n in notes:
        row = {}
        for k in note_fieldnames:
            v = n.get(k, "")
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            row[k] = v
        note_rows.append(row)
    notes_csv = os.path.join(args.outdir, "notes.csv")
    write_csv(notes_csv, note_rows, fieldnames=note_fieldnames)
    if args.verbose:
        log(f"[+] Wrote {notes_csv}  ({len(note_rows)} rows)")

    # Final summary
    log("[Done]")
    log(f"  JSON : {full_json_path}")
    log(f"  KV   : {kv_csv_path}")
    log(f"  MAP  : {chmap_csv}")
    log(f"  CHBLK: {chblk_csv}")
    log(f"  NOTES: {notes_csv}")

if __name__ == "__main__":
    main()
