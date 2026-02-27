#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PHI Name Redactor - Hybrid Transformer (Token BIO + Char Head)
==============================================================

Dataset layout (per your request):
<DATA_ROOT>/
  <CASE_A>/
    org/*.tsv     # original (unredacted) documents
    out/*.tsv     # redacted counterparts (same filenames)
  <CASE_B>/
    org/*.tsv
    out/*.tsv
  ...

What this script does
---------------------
1) Walks the dataset and pairs original vs redacted files by (case, relative filename).
2) Derives a char-level redaction mask via alignment (difflib).
3) (Optional) Applies targeted augmentations (typos, space drops, casing) within name spans.
4) Builds token-level BIO labels using tokenizer offsets; prepares a char-level supervision stream.
5) Trains a hybrid model: a RoBERTa-like encoder with:
   - Token head (BIO: B, I, O)
   - Char head (non-PHI vs PHI) computed by upsampling token hidden states to chars via offsets
6) Evaluates with safety-centric metrics (char-level precision, recall, F1; non-PHI retention).
7) Predicts on arbitrary long text files with sliding windows, outputs a redacted text using [NAME].

Usage Examples
--------------
# Train (80/10/10 split by cases), save to ./runs/exp1
python phi_redactor.py train \
  --data_root /path/to/data \
  --output_dir ./runs/exp1 \
  --model_name roberta-base \
  --epochs 4 \
  --batch_size 4 \
  --max_tokens 512 \
  --learning_rate 2e-5 \
  --char_loss_weight 0.7 \
  --augment

# Evaluate the saved checkpoint on the held-out test set
python phi_redactor.py eval \
  --data_root /path/to/data \
  --checkpoint ./runs/exp1

# Redact a sample input file and save the output (uses the trained model)
python phi_redactor.py predict \
  --checkpoint ./runs/exp1 \
  --input_tsv /path/to/sample.tsv \
  --output_tsv ./redacted_sample.tsv

Notes
-----
- Dependencies: torch, transformers, numpy, tqdm
- Optional but recommended: accelerate for mixed precision (automatically used if available)
- If you prefer a different base model, set --model_name (e.g., deberta-v3-base).

"""

import os
import re
import json
import time
import argparse
import random
from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional

from aux_name_augmentation import (generate_augmented_pairs_for_epoch, 
                               _find_cases, _pair_files_for_case,
                               augment_text_and_mask, read_text,
                               compute_redaction_mask, write_text,
                               ensure_dir,
                               seed_everything, normalize_minimal)


import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

from tqdm import tqdm

try:
    from transformers import AutoTokenizer, AutoModel, get_linear_schedule_with_warmup
except ImportError as e:
    raise SystemExit("Please install transformers: pip install transformers") from e

# AMP (new API first, fallback to older)
try:
    from torch.amp import GradScaler, autocast  # PyTorch >= 2.4
    _AMP_NEW = True
except Exception:
    try:
        from torch.cuda.amp import GradScaler, autocast  # Older PyTorch
        _AMP_NEW = False
    except Exception:
        GradScaler = None
        autocast = None
        _AMP_NEW = False








# -----------------------------
# Dataset & Collation
# -----------------------------

LABELS = {"O": 0, "B": 1, "I": 2}
ID2LABEL = {v: k for k, v in LABELS.items()}

@dataclass
class Example:
    text: str
    char_mask: np.ndarray  # len = len(text)
    case_id: str
    rel_path: str


class RedactionDataset(Dataset):
    def __init__(self,
                 examples: List[Example],
                 tokenizer,
                 max_tokens: int = 512,
                 training: bool = False,
                 augment: bool = False):
        self.examples = examples
        self.tok = tokenizer
        self.max_tokens = max_tokens
        self.training = training
        self.augment = augment

    def __len__(self):
        return len(self.examples)

    def _make_labels_from_offsets(self, text: str, char_mask: np.ndarray, enc) -> Dict[str, torch.Tensor]:
        """
        Given tokenizer encoding (with offsets_mapping) for a single example, build:
        - token_labels: BIO ids per token (special tokens -> -100)
        - char_token_index: for each char pos (0..max_char_index-1), which token index covers it; else -1
        - char_labels: 0/1 per char pos; positions without token coverage -> keep label but we can ignore in char loss if needed
        """
        offsets = enc["offset_mapping"]
        # Determine max covered char index by the last non-special token
        # Special tokens tend to have (0,0). We'll consider only tokens with end > start.
        covered = [(i, (s, e)) for i, (s, e) in enumerate(offsets) if e > s]
        if not covered:
            # Fallback: shouldn't happen for non-empty text
            token_labels = torch.full((len(offsets),), -100, dtype=torch.long)
            return {
                "token_labels": token_labels,
                "char_labels": torch.zeros((0,), dtype=torch.long),
                "char_token_index": torch.zeros((0,), dtype=torch.long),
                "char_span_max": 0,
            }
        
        
        max_char = max(e for e1, (e2, e) in covered)
        # Safe-guard for shorter mask (shouldn't happen)
        max_char = min(max_char, len(char_mask))
        cm = char_mask[:max_char]

        # Build char -> token index map, default -1
        char_to_tok = np.full((max_char,), -1, dtype=np.int64)
        for ti, (s, e) in covered:
            if s >= max_char:
                continue
            e2 = min(e, max_char)
            char_to_tok[s:e2] = ti

        # BIO token labels (ignore specials)
        token_labels = np.full((len(offsets),), -100, dtype=np.int64)
        prev_in_name = 0
        prev_tok_valid = False
        prev_tok_idx = -1

        for ti, (s, e) in enumerate(offsets):
            if e <= s:
                # special or empty -> ignore
                continue
            s2 = min(s, max_char)
            e2 = min(e, max_char)
            seg = cm[s2:e2] if e2 > s2 else np.array([], dtype=np.int64)
            in_name = int(seg.sum() > 0)
            if in_name == 0:
                token_labels[ti] = LABELS["O"]
                prev_in_name = 0
            else:
                # B if previous token not in name; else I
                if prev_in_name == 0:
                    token_labels[ti] = LABELS["B"]
                else:
                    token_labels[ti] = LABELS["I"]
                prev_in_name = 1

            prev_tok_valid = True
            prev_tok_idx = ti

        return {
            "token_labels": torch.tensor(token_labels, dtype=torch.long),
            "char_labels": torch.tensor(cm.astype(np.int64), dtype=torch.long),
            "char_token_index": torch.tensor(char_to_tok, dtype=torch.long),
            "char_span_max": int(max_char),
        }

    def __getitem__(self, idx):
        ex = self.examples[idx]
        text = ex.text
        mask = ex.char_mask

        # Training-time augmentation (optional)
        if self.training and self.augment and mask.sum() > 0:
            text, mask = augment_text_and_mask(text, mask)

        enc = self.tok(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=self.max_tokens,
            return_offsets_mapping=True,
            add_special_tokens=True,
        )
        # Squeeze batch dim
        enc = {k: v.squeeze(0) for k, v in enc.items()}
        labels = self._make_labels_from_offsets(text, mask, enc)

        item = {
            "input_ids": enc["input_ids"],
            "attention_mask": enc["attention_mask"],
            "offset_mapping": enc["offset_mapping"],  # keep for collate
            "token_labels": labels["token_labels"],
            "char_labels": labels["char_labels"],
            "char_token_index": labels["char_token_index"],
            "char_span_max": labels["char_span_max"],
            "text_len": len(text),
        }
        return item


def collate_batch(features: List[Dict]) -> Dict[str, torch.Tensor]:
    # Determine max lengths for padding
    max_toks = max(x["input_ids"].shape[0] for x in features)
    max_chars = max(x["char_span_max"] for x in features)

    def pad_1d(arr, pad_len, pad_value):
        red = np.full((pad_len,), pad_value, dtype=np.int64)
        red[:arr.shape[0]] = arr
        return red

    # Token-level padding
    input_ids = []
    attention_mask = []
    token_labels = []
    for x in features:
        L = x["input_ids"].shape[0]
        pad_toks = max_toks - L
        input_ids.append(
            torch.cat([x["input_ids"], torch.full((pad_toks,), 1 if x["input_ids"][0].item() == 0 else 0, dtype=torch.long)])
        )  # NOTE: simplistic pad id: many models use 1 for roberta, 0 for bert; handled below with tokenizer.pad_token_id in Trainer setup typically. Here we approximate.
        attention_mask.append(
            torch.cat([x["attention_mask"], torch.zeros((pad_toks,), dtype=torch.long)])
        )
        token_labels.append(
            torch.cat([x["token_labels"], torch.full((pad_toks,), -100, dtype=torch.long)])
        )

    # Char-level padding
    char_labels = []
    char_token_index = []
    for x in features:
        char_labels.append(torch.tensor(pad_1d(x["char_labels"].numpy(), max_chars, -100), dtype=torch.long))
        # for token index map, pad with -1
        cti = x["char_token_index"].numpy()
        cti_padded = np.full((max_chars,), -1, dtype=np.int64)
        cti_padded[:cti.shape[0]] = cti
        char_token_index.append(torch.tensor(cti_padded, dtype=torch.long))

    batch = {
        "input_ids": torch.stack(input_ids, dim=0),
        "attention_mask": torch.stack(attention_mask, dim=0),
        "token_labels": torch.stack(token_labels, dim=0),
        "char_labels": torch.stack(char_labels, dim=0),
        "char_token_index": torch.stack(char_token_index, dim=0),
    }
    return batch


# -----------------------------
# Model
# -----------------------------

class HybridRedactorModel(nn.Module):
    def __init__(self, model_name: str, num_token_labels: int = 3, char_loss_weight: float = 0.5):
        super().__init__()
        self.encoder = AutoModel.from_pretrained(model_name)
        hidden = self.encoder.config.hidden_size
        self.dropout = nn.Dropout(0.1)
        self.token_classifier = nn.Linear(hidden, num_token_labels)
        self.char_classifier = nn.Linear(hidden, 2)
        self.char_loss_weight = char_loss_weight

    def forward(self,
                input_ids,
                attention_mask,
                token_labels=None,
                char_labels=None,
                char_token_index=None):
        # Encoder
        outputs = self.encoder(input_ids=input_ids, attention_mask=attention_mask, return_dict=True)
        seq = self.dropout(outputs.last_hidden_state)  # [B, T, H]

        # Token logits
        token_logits = self.token_classifier(seq)      # [B, T, 3]

        loss = None
        token_loss = None
        char_loss = None

        if token_labels is not None:
            # Flatten for CE
            loss_fct = nn.CrossEntropyLoss(ignore_index=-100)
            token_loss = loss_fct(token_logits.view(-1, token_logits.size(-1)),
                                  token_labels.view(-1))

        # Char logits by upsampling token features via char_token_index
        # char_token_index: [B, C], values in [0..T-1] or -1 for "no coverage"
        char_logits = None
        if char_token_index is not None:
            B, C = char_token_index.shape
            T = seq.size(1)
            # Clamp indices to [0, T-1] but remember mask of valid positions
            valid = (char_token_index >= 0) & (char_token_index < T)
            safe_index = char_token_index.clone().clamp(min=0)
            # Gather token features per char
            # -> we need [B, C, H]
            H = seq.size(-1)
            # seq: [B, T, H]; safe_index: [B, C] -> gather along dim=1
            expanded_index = safe_index.unsqueeze(-1).expand(B, C, H)
            char_feats = torch.gather(seq, dim=1, index=expanded_index)  # [B, C, H]
            char_logits = self.char_classifier(char_feats)               # [B, C, 2]

            if char_labels is not None:
                # Mask out invalid char positions for loss
                # We also ignore label == -100
                char_labels_flat = char_labels.view(-1)
                char_logits_flat = char_logits.view(-1, 2)
                valid_flat = valid.view(-1)

                # For invalid positions, set label to ignore
                effective_labels = char_labels_flat.clone()
                effective_labels[~valid_flat] = -100

                loss_char = nn.CrossEntropyLoss(ignore_index=-100)
                char_loss = loss_char(char_logits_flat, effective_labels)

        if token_loss is not None and char_loss is not None:
            loss = token_loss + self.char_loss_weight * char_loss
        elif token_loss is not None:
            loss = token_loss
        elif char_loss is not None:
            loss = char_loss

        return {
            "loss": loss,
            "token_logits": token_logits,
            "char_logits": char_logits,
            "token_loss": token_loss,
            "char_loss": char_loss,
        }


# -----------------------------
# Metrics
# -----------------------------

def compute_char_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    """
    y_true, y_pred: 0/1 arrays of the same length
    Returns precision, recall, f1, and non-PHI retention.
    """
    assert y_true.shape == y_pred.shape
    tp = int(((y_true == 1) & (y_pred == 1)).sum())
    fp = int(((y_true == 0) & (y_pred == 1)).sum())
    fn = int(((y_true == 1) & (y_pred == 0)).sum())
    tn = int(((y_true == 0) & (y_pred == 0)).sum())

    prec = tp / (tp + fp + 1e-9)
    rec = tp / (tp + fn + 1e-9)
    f1 = 2 * prec * rec / (prec + rec + 1e-9)
    non_phi_retention = tn / (tn + fp + 1e-9)

    return {
        "precision": prec,
        "recall": rec,
        "f1": f1,
        "non_phi_retention": non_phi_retention,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn
    }


# -----------------------------
# Training / Eval
# -----------------------------

def build_examples(data_root: str) -> List[Example]:
    cases = _find_cases(data_root)
    if not cases:
        raise RuntimeError(f"No cases with 'org' and 'red' folders found under {data_root}")

    examples: List[Example] = []
    seen = set()  # (case_id, rel_path)

    for case_dir in cases:
        case_id = os.path.basename(case_dir.rstrip("/"))
        pairs = _pair_files_for_case(case_dir)

        for (orig_path, red_path) in pairs:
            rel = os.path.relpath(orig_path, os.path.join(case_dir, "org"))

            key = (case_id, rel)
            if key in seen:
                # Already processed → skip silently
                continue

            seen.add(key)

            orig = read_text(orig_path)
            red = read_text(red_path)

            orig = normalize_minimal(orig)
            red = normalize_minimal(red)

            mask = compute_redaction_mask(orig, red)

            print(f"working on case = {case_id}, file = {rel}")

            examples.append(
                Example(
                    text=orig,
                    char_mask=mask,
                    case_id=case_id,
                    rel_path=rel,
                )
            )

    return examples



def split_by_case(examples: List[Example],
                  train_ratio: float = 0.8,
                  val_ratio: float = 0.1,
                  seed: int = 42) -> Tuple[List[Example], List[Example], List[Example]]:
    # Get unique cases
    case_ids = sorted(set(e.case_id for e in examples))
    rng = random.Random(seed)
    rng.shuffle(case_ids)
    n = len(case_ids)
    n_train = max(1, int(n * train_ratio))
    n_val = max(1, int(n * val_ratio))
    train_cases = set(case_ids[:n_train])
    val_cases = set(case_ids[n_train:n_train + n_val])
    test_cases = set(case_ids[n_train + n_val:])

    train = [e for e in examples if e.case_id in train_cases]
    val = [e for e in examples if e.case_id in val_cases]
    test = [e for e in examples if e.case_id in test_cases]

    return train, val, test


def train_loop(model,
               tokenizer,
               train_ds,
               val_ds,
               args):
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model.to(device)

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True,
                              num_workers=2, collate_fn=collate_batch, pin_memory=True)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False,
                            num_workers=2, collate_fn=collate_batch, pin_memory=True)

    optim = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=0.01)
    total_steps = args.epochs * len(train_loader)
    warmup = max(10, int(0.06 * total_steps))
    scheduler = get_linear_schedule_with_warmup(optim, num_warmup_steps=warmup, num_training_steps=total_steps)

    scaler = None
    try:
        from torch.cuda.amp import GradScaler, autocast
        scaler = GradScaler(enabled=torch.cuda.is_available())
    except Exception:
        autocast = None
        scaler = None

    best_val_f1 = -1.0
    history = []

    for epoch in range(1, args.epochs + 1):
        model.train()
        pbar = tqdm(train_loader, desc=f"Epoch {epoch}/{args.epochs} [train]")
        running_loss = 0.0
        for step, batch in enumerate(pbar, start=1):
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            token_labels = batch["token_labels"].to(device)
            char_labels = batch["char_labels"].to(device)
            char_token_index = batch["char_token_index"].to(device)

            optim.zero_grad(set_to_none=True)

            if scaler is not None:
                with torch.cuda.amp.autocast():
                    out = model(input_ids, attention_mask, token_labels, char_labels, char_token_index)
                    loss = out["loss"]
                scaler.scale(loss).backward()
                scaler.unscale_(optim)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(optim)
                scaler.update()
            else:
                out = model(input_ids, attention_mask, token_labels, char_labels, char_token_index)
                loss = out["loss"]
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optim.step()

            scheduler.step()
            running_loss += loss.item()
            pbar.set_postfix(loss=f"{running_loss / step:.4f}",
                             token=f"{(out['token_loss'].item() if out['token_loss'] is not None else 0):.3f}",
                             char=f"{(out['char_loss'].item() if out['char_loss'] is not None else 0):.3f}")

        # Validation
        val_metrics = evaluate_loop(model, val_loader, args)
        history.append({
            "epoch": epoch,
            "train_loss": running_loss / len(train_loader),
            **val_metrics
        })
        print(f"[VAL] epoch={epoch} | precision={val_metrics['precision']:.4f} "
              f"recall={val_metrics['recall']:.4f} f1={val_metrics['f1']:.4f} "
              f"non_phi_retention={val_metrics['non_phi_retention']:.4f}")

        # Save best
        if val_metrics["f1"] > best_val_f1:
            best_val_f1 = val_metrics["f1"]
            save_checkpoint(model, tokenizer, args.output_dir, args, best=True, metrics=val_metrics)

    # Final save
    save_checkpoint(model, tokenizer, args.output_dir, args, best=False, metrics=history[-1] if history else {})

    # Save history
    write_text(os.path.join(args.output_dir, "train_history.json"), json.dumps(history, indent=2))

    return history


def evaluate_loop(model, loader, args):
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model.eval()

    all_true = []
    all_pred = []

    with torch.no_grad():
        for batch in tqdm(loader, desc="Eval"):
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            char_labels = batch["char_labels"].numpy()
            char_token_index = batch["char_token_index"].to(device)

            out = model(input_ids, attention_mask, token_labels=None,
                        char_labels=None, char_token_index=char_token_index)

            # Token predictions to char grid
            token_logits = out["token_logits"].cpu().numpy()  # [B, T, 3]
            char_logits = out["char_logits"]
            if char_logits is not None:
                char_logits = char_logits.cpu().numpy()  # [B, C, 2]

            B = input_ids.size(0)
            for i in range(B):
                true = char_labels[i]  # [C], contains -100 beyond valid region
                # Build predicted char mask by OR(token->char, char head)
                pred_char = build_char_pred_mask_from_logits(
                    token_logits[i], char_logits[i] if char_logits is not None else None,
                    batch["char_token_index"][i].numpy(),
                    threshold=args.char_threshold
                )
                # Clip to the length of valid char labels
                valid_len = (true != -100).sum()
                true_vec = (true[:valid_len] == 1).astype(np.int64)
                pred_vec = pred_char[:valid_len].astype(np.int64)

                all_true.append(true_vec)
                all_pred.append(pred_vec)

    # Concatenate
    if not all_true:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "non_phi_retention": 0.0}

    y_true = np.concatenate(all_true, axis=0)
    y_pred = np.concatenate(all_pred, axis=0)
    return compute_char_metrics(y_true, y_pred)


def build_char_pred_mask_from_logits(token_logits_i: np.ndarray,
                                     char_logits_i: Optional[np.ndarray],
                                     char_token_index_i: np.ndarray,
                                     threshold: float = 0.5) -> np.ndarray:
    """
    token_logits_i: [T, 3]
    char_logits_i:  [C, 2] or None
    char_token_index_i: [C] in [0..T-1] or -1
    Returns: pred mask over C chars (0/1), OR'ing token-based and char-based signals.
    """
    T = token_logits_i.shape[0]
    C = char_token_index_i.shape[0]

    # Token -> char map
    token_preds = token_logits_i.argmax(axis=-1)  # 0/1/2
    token_is_name = (token_preds == LABELS["B"]) | (token_preds == LABELS["I"])

    char_pred_from_token = np.zeros((C,), dtype=np.int64)
    valid = (char_token_index_i >= 0) & (char_token_index_i < T)
    map_idx = char_token_index_i[valid]
    char_pred_from_token[valid] = token_is_name[map_idx].astype(np.int64)

    # Char head
    if char_logits_i is not None:
        probs = torch.softmax(torch.tensor(char_logits_i), dim=-1).numpy()[:, 1]
        char_pred_from_char = (probs >= threshold).astype(np.int64)
    else:
        char_pred_from_char = np.zeros((C,), dtype=np.int64)

    return np.maximum(char_pred_from_token, char_pred_from_char)


def save_checkpoint(model, tokenizer, out_dir, args, best: bool, metrics: Dict):
    ensure_dir(out_dir)
    tag = "best" if best else "last"
    ckpt_dir = os.path.join(out_dir, tag)
    ensure_dir(ckpt_dir)
    # Model/Tokenizer
    model_to_save = model.module if hasattr(model, "module") else model
    torch.save(model_to_save.state_dict(), os.path.join(ckpt_dir, "robarta_pytorch_model.bin"))
    # Save a minimal config to reload
    cfg = {
        "model_name": args.model_name,
        "char_loss_weight": args.char_loss_weight,
        "max_tokens": args.max_tokens,
        "char_threshold": args.char_threshold,
        "label_map": LABELS,
        "metrics": metrics,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    write_text(os.path.join(ckpt_dir, "config.json"), json.dumps(cfg, indent=2))
    tokenizer.save_pretrained(ckpt_dir)
    print(f"[INFO] Saved checkpoint to {ckpt_dir}")


def load_checkpoint(ckpt_dir: str) -> Tuple[HybridRedactorModel, AutoTokenizer, Dict]:
    cfg_path = os.path.join(ckpt_dir, "config.json")
    if not os.path.isfile(cfg_path):
        raise RuntimeError(f"No config.json in {ckpt_dir} (equal to: {cfg_path})")
        
    cfg = json.loads(read_text(cfg_path))
    tokenizer = AutoTokenizer.from_pretrained(ckpt_dir, use_fast=True)
    model = HybridRedactorModel(cfg["model_name"],
                                num_token_labels=len(cfg["label_map"]),
                                char_loss_weight=cfg["char_loss_weight"])
    state = torch.load(os.path.join(ckpt_dir, "robarta_pytorch_model.bin"), map_location="cpu")
    model.load_state_dict(state, strict=False)
    return model, tokenizer, cfg


# -----------------------------
# Inference (Redact a full text)
# -----------------------------

def redact_text(model: HybridRedactorModel,
                tokenizer,
                text: str,
                char_threshold: float = 0.5,
                max_tokens: int = 512,
                stride_tokens: int = 64) -> Tuple[str, np.ndarray]:
    """
    Run the model over a *long* text with sliding windows.
    Returns (redacted_text, pred_mask) where pred_mask is length len(text).
    """
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model.eval()
    model.to(device)

    text = normalize_minimal(text)
    N = len(text)
    global_probs = np.zeros(N, dtype=np.float32)
    global_seen  = np.zeros(N, dtype=np.int32)

    # Use tokenizer overflow to slide across the text
    enc = tokenizer(
        text,
        return_offsets_mapping=True,
        return_overflowing_tokens=True,
        truncation=True,
        max_length=max_tokens,
        stride=stride_tokens,
        padding=False,
        add_special_tokens=True,
    )

    num_splits = len(enc["input_ids"])
    for i in tqdm(range(num_splits), desc="Redacting"):
        input_ids     = torch.tensor(enc["input_ids"][i]).unsqueeze(0).to(device)
        attention_mask= torch.tensor(enc["attention_mask"][i]).unsqueeze(0).to(device)
        offsets       = enc["offset_mapping"][i]

        # Keep only real tokens (specials have e<=s)
        covered = [(ti, (s, e)) for ti, (s, e) in enumerate(offsets) if e > s]
        if not covered:
            continue

        # Absolute char span this window covers in the original text
        win_start = min(s for _, (s, _) in covered)
        win_end   = max(e for _, (_, e) in covered)
        if win_start >= win_end:
            continue

        # Build per-char token index RELATIVE to this window [0 .. win_end-win_start)
        C = win_end - win_start
        char_to_tok = np.full((C,), -1, dtype=np.int64)
        for ti, (s, e) in covered:
            s2 = max(s, win_start)
            e2 = min(e, win_end)
            if e2 > s2:
                char_to_tok[(s2 - win_start):(e2 - win_start)] = ti

        char_token_index = torch.tensor(char_to_tok, dtype=torch.long).unsqueeze(0).to(device)

        with torch.no_grad():
            out = model(input_ids=input_ids,
                        attention_mask=attention_mask,
                        token_labels=None,
                        char_labels=None,
                        char_token_index=char_token_index)

        token_logits = out["token_logits"][0].cpu().numpy()  # [T,3]
        char_logits  = out["char_logits"][0].cpu().numpy() if out["char_logits"] is not None else None

        # Predict char mask for THIS WINDOW (length C, 0..C-1)
        pred_char = build_char_pred_mask_from_logits(
            token_logits, char_logits, char_to_tok, threshold=char_threshold
        ).astype(np.float32)

        # Merge into GLOBAL arrays at the absolute window slice
        g_lo = max(win_start, 0)
        g_hi = min(win_end, N)
        if g_hi > g_lo:
            rel_lo = g_lo - win_start
            rel_hi = rel_lo + (g_hi - g_lo)
            global_probs[g_lo:g_hi] += pred_char[rel_lo:rel_hi]
            global_seen[g_lo:g_hi]  += 1

    # Aggregate votes across overlapping windows
    seen_mask = global_seen > 0
    pred_mask = np.zeros_like(global_probs, dtype=np.int64)
    pred_mask[seen_mask] = (global_probs[seen_mask] / global_seen[seen_mask]) >= 0.5
    pred_mask[~seen_mask] = 0

    # Replace contiguous positive spans with [NAME]
    redacted = apply_placeholder_redaction(text, pred_mask, placeholder="[NAME]")
    return redacted, pred_mask



def apply_placeholder_redaction(text: str, mask: np.ndarray, placeholder: str = "[NAME]") -> str:
    """
    Replace contiguous runs of mask==1 that cover at least one letter with a single [NAME].
    Preserve other characters verbatim.
    """
    out = []
    i = 0
    N = len(text)
    while i < N:
        if mask[i] == 1:
            # find the end of this run
            j = i + 1
            alpha_seen = text[i].isalpha()
            while j < N and mask[j] == 1:
                if text[j].isalpha():
                    alpha_seen = True
                j += 1
            if alpha_seen:
                # emit placeholder; also swallow adjacent spaces immediately around
                # (conservative: we keep punctuation)
                # Pre-trim leading spaces in run
                while i < j and text[i].isspace():
                    i += 1
                # Post-trim trailing spaces in run
                while j - 1 >= i and text[j - 1].isspace():
                    j -= 1
                out.append(placeholder)
            else:
                # If the run contains no letters (unlikely), keep original chars
                out.append(text[i:j])
            i = j
        else:
            out.append(text[i])
            i += 1
    return ''.join(out)


# -----------------------------
# CLI
# -----------------------------

def parse_args():
    ap = argparse.ArgumentParser(description="PHI Name Redactor - Hybrid Transformer (Token BIO + Char Head)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # Shared/defaults
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--model_name", type=str, default="roberta-base",
                    help="Backbone encoder (e.g., roberta-base, bert-base-uncased, microsoft/deberta-v3-base)")
    ap.add_argument("--max_tokens", type=int, default=512)
    ap.add_argument("--batch_size", type=int, default=4)
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--learning_rate", type=float, default=2e-5)
    ap.add_argument("--pred_model_path", type=str, default = "")
    ap.add_argument("--char_loss_weight", type=float, default=0.7)
    ap.add_argument("--char_threshold", type=float, default=0.5)

    # Train
    sp_train = sub.add_parser("train", help="Train a model")
    sp_train.add_argument("--data_root", type=str, required=True)
    sp_train.add_argument("--output_dir", type=str, required=True)
    sp_train.add_argument("--pred_model_path", type=str, default = "")
    sp_train.add_argument("--train_ratio", type=float, default=0.8)
    sp_train.add_argument("--val_ratio", type=float, default=0.1)
    sp_train.add_argument("--augment", action="store_true", help="Enable targeted augmentations")

    # Eval
    sp_eval = sub.add_parser("eval", help="Evaluate a saved checkpoint on the test split")
    sp_eval.add_argument("--data_root", type=str, required=True)
    sp_eval.add_argument("--checkpoint", type=str, required=True, help="Path to checkpoint dir (folder with best/ or last/)")
    sp_eval.add_argument("--pred_model_path", type=str, default = "")

    # Predict
    sp_pred = sub.add_parser("predict", help="Redact a single tsv file using a trained checkpoint")
    sp_pred.add_argument("--checkpoint", type=str, required=True,
                         help="Path to checkpoint dir (folder with best/ or last/)")
    sp_pred.add_argument("--pred_model_path", type=str, default = "")
    sp_pred.add_argument("--input_tsv", type=str, required=True)
    sp_pred.add_argument("--output_tsv", type=str, required=True)
    
    # Name augmentation (synthetic PHI insert/replace) per-epoch
    sp_train.add_argument("--names_file", type=str, default=None,
                          help="Path to additional_names.txt (one name per line). If set, per-epoch augmented *_updX files are created for TRAIN cases only.")
                          
    sp_train.add_argument("--name_aug_min_pct", type=float, default=0.1,
                          help="Minimum percent of words per file to add/replace with names (0.1 means 0.1%%).")
    sp_train.add_argument("--name_aug_max_pct", type=float, default=3.0,
                          help="Maximum percent of words per file to add/replace with names (3.0 means 3%%).")
    sp_train.add_argument("--name_aug_label", type=str, default="[LABEL]",
                          help="Label token to write into red files for augmented names.")
    sp_train.add_argument("--aug_log_dir", type=str, default=None,
                          help="Optional directory to write simple per-file augmentation logs.")
    

    return ap.parse_args()

def _get_case_ids_from_examples(examples: List[Example]) -> List[str]:
    """Unique case IDs from examples, in sorted order."""
    return sorted(set(e.case_id for e in examples))

def _filter_examples(examples: List[Example], include_upd: bool) -> List[Example]:
    """Keep or drop *_upd[2-9].tsv examples based on include_upd flag."""
    if include_upd:
        return examples
    out = []
    for e in examples:
        # rel_path like 'subfolder/file.tsv' or nested
        base = os.path.basename(e.rel_path)
        if not re.search(r"_upd[2-9]\.tsv$", base):
            out.append(e)
    return out

def main():
    args = parse_args()
    seed_everything(args.seed)

    if args.cmd == "train_prv":
        ensure_dir(args.output_dir)
        print(f"[INFO] Loading data from {args.data_root}")
        examples = build_examples(args.data_root)
        print(f"[INFO] Total paired files: {len(examples)} across {len(set(e.case_id for e in examples))} cases")

        train_ex, val_ex, test_ex = split_by_case(examples, args.train_ratio, args.val_ratio, seed=args.seed)
        for name, split in [("train", train_ex), ("val", val_ex), ("test", test_ex)]:
            print(f"  - {name}: {len(split)} files | cases={sorted(set(e.case_id for e in split))}")

        tokenizer = AutoTokenizer.from_pretrained(args.model_name, use_fast=True)
        # Ensure pad token id
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token if tokenizer.eos_token is not None else tokenizer.sep_token

        train_ds = RedactionDataset(train_ex, tokenizer, max_tokens=args.max_tokens, training=True, augment=args.augment)
        val_ds = RedactionDataset(val_ex, tokenizer, max_tokens=args.max_tokens, training=False, augment=False)

        model = HybridRedactorModel(args.model_name,
                                    num_token_labels=len(LABELS),
                                    char_loss_weight=args.char_loss_weight)

        history = train_loop(model, tokenizer, train_ds, val_ds, args)

        # Evaluate on test split with best checkpoint
        best_dir = os.path.join(args.output_dir, "best")
        if os.path.isdir(best_dir):
            print("[INFO] Evaluating best checkpoint on TEST split...")
            model_best, tok_best, cfg = load_checkpoint(best_dir)
            test_ds = RedactionDataset(test_ex, tok_best, max_tokens=cfg.get("max_tokens", args.max_tokens),
                                       training=False, augment=False)
            test_loader = DataLoader(test_ds, batch_size=args.batch_size, shuffle=False,
                                     num_workers=2, collate_fn=collate_batch, pin_memory=True)
            metrics = evaluate_loop(model_best, test_loader, argparse.Namespace(char_threshold=cfg.get("char_threshold", args.char_threshold)))
            print("[TEST] ", metrics)
            write_text(os.path.join(best_dir, "test_metrics.json"), json.dumps(metrics, indent=2))
        else:
            print("[WARN] No best checkpoint found; skipping test evaluation.")

    elif args.cmd == "train":
        ensure_dir(args.output_dir)
        print(f"[INFO] Loading data from {args.data_root}")
        # Build ALL examples once (original + any pre-existing upds)
        all_examples = build_examples(args.data_root)
        print(f"[INFO] Total paired files: {len(all_examples)} across {len(set(e.case_id for e in all_examples))} cases")

        # Split only on ORIGINALS (exclude *_updX for split)
        base_examples = _filter_examples(all_examples, include_upd=False)
        train_ex, val_ex, test_ex = split_by_case(base_examples, args.train_ratio, args.val_ratio, seed=args.seed)
        for name, split in [("train(base)", train_ex), ("val(base)", val_ex), ("test(base)", test_ex)]:
            print(f"  - {name}: {len(split)} files | cases={sorted(set(e.case_id for e in split))}")

        tokenizer = AutoTokenizer.from_pretrained(args.model_name, use_fast=True)
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token if tokenizer.eos_token is not None else tokenizer.sep_token

        model = HybridRedactorModel(args.model_name,
                                    num_token_labels=len(LABELS),
                                    char_loss_weight=args.char_loss_weight)

        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        model.to(device)

        # --- Prepare a stable VAL loader on (base) validation set ---
        val_ds = RedactionDataset(val_ex, tokenizer, max_tokens=args.max_tokens, training=False, augment=False)
        val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False,
                                num_workers=2, collate_fn=collate_batch, pin_memory=True)

        # --- Optimizer / Scheduler (steps per epoch = originals + current epoch's upds) ---
        # We assume one augmented file per original train file per epoch.
        # Steps per epoch are computed after building the epoch's train loader.
        optim = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=0.01)
        # We'll recreate the scheduler per epoch with the correct num_training_steps to keep warmup fraction consistent.
        warmup_frac = 0.06

        # AMP scaler
        scaler = None
        try:
            if GradScaler is not None:
                # New API prefers device argument
                if _AMP_NEW:
                    scaler = GradScaler("cuda", enabled=torch.cuda.is_available())
                else:
                    scaler = GradScaler(enabled=torch.cuda.is_available())
        except Exception:
            scaler = None

        best_val_f1 = -1.0
        history = []

        # Cache TRAIN case IDs (to restrict augmentation to train only)
        train_case_ids = _get_case_ids_from_examples(train_ex)

        for epoch in range(1, args.epochs + 1):
            # 1) Generate *_updX files for TRAIN cases only (fresh each epoch)
            created_pairs = []
            if args.names_file:
                try:
                    created_pairs = generate_augmented_pairs_for_epoch(
                        data_root=args.data_root,
                        train_case_ids=train_case_ids,
                        names_file=args.names_file,
                        min_pct=args.name_aug_min_pct,
                        max_pct=args.name_aug_max_pct,
                        label_placeholder=args.name_aug_label,
                        seed=args.seed + epoch,
                        log_dir=args.aug_log_dir,
                    )
                    print(f"[AUG] Epoch {epoch}: created {len(created_pairs)} augmented pairs.")
                except RuntimeError as e:
                    # Respect the user's rule: after _upd9, throw.
                    print(f"[AUG][ERROR] {e}")
                    raise

            # 2) Rebuild TRAIN examples as: BASE originals + ONLY the current epoch's upds
            #    (val/test remain the original splits, unchanged)
            #    We'll load examples for the newly created pairs on the fly.
            #    For originals, reuse train_ex already built.
            epoch_upd_examples: List[Example] = []
            for org_upd, red_upd in created_pairs:
                orig_text = read_text(org_upd)
                red_text = read_text(red_upd)
                mask = compute_redaction_mask(normalize_minimal(orig_text), normalize_minimal(red_text))
                # Derive case_id and rel_path from upds
                # org_upd: <data_root>/<case>/org/<rel>
                # case_id is the immediate folder name under data_root
                rel_from_org = None
                case_id = None
                try:
                    # Find relative pieces
                    parts = org_upd.replace("\\", "/").split("/")
                    # .../<data_root>/<case>/org/<rel>
                    dr_parts = args.data_root.replace("\\", "/").rstrip("/").split("/")
                    # index of case folder = len(dr_parts)
                    case_id = parts[len(dr_parts)]
                    # rel path under org = remaining after ".../org/"
                    org_index = parts.index("org")
                    rel_from_org = "/".join(parts[org_index + 1 :])
                except Exception:
                    case_id = "unknown_case"
                    rel_from_org = os.path.basename(org_upd)

                epoch_upd_examples.append(
                    Example(text=normalize_minimal(orig_text), char_mask=mask, case_id=case_id, rel_path=rel_from_org)
                )

            # Order: originals first, then current epoch's upds
            combined_train_examples = list(train_ex) + epoch_upd_examples

            train_ds = RedactionDataset(combined_train_examples, tokenizer,
                                        max_tokens=args.max_tokens, training=True, augment=args.augment)
            train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True,
                                      num_workers=2, collate_fn=collate_batch, pin_memory=True)

            # Fresh scheduler each epoch with correct step count for this epoch
            total_steps = len(train_loader)
            warmup = max(10, int(warmup_frac * total_steps))
            scheduler = get_linear_schedule_with_warmup(optim, num_warmup_steps=warmup, num_training_steps=total_steps)

            # 3) Train for this epoch
            model.train()
            pbar = tqdm(train_loader, desc=f"Epoch {epoch}/{args.epochs} [train]")
            running_loss = 0.0
            for step, batch in enumerate(pbar, start=1):
                input_ids = batch["input_ids"].to(device)
                attention_mask = batch["attention_mask"].to(device)
                token_labels = batch["token_labels"].to(device)
                char_labels = batch["char_labels"].to(device)
                char_token_index = batch["char_token_index"].to(device)

                optim.zero_grad(set_to_none=True)

                if scaler is not None and autocast is not None and torch.cuda.is_available():
                    # New autocast signature
                    if _AMP_NEW:
                        with autocast("cuda"):
                            out = model(input_ids, attention_mask, token_labels, char_labels, char_token_index)
                            loss = out["loss"]
                    else:
                        with autocast():
                            out = model(input_ids, attention_mask, token_labels, char_labels, char_token_index)
                            loss = out["loss"]
                    scaler.scale(loss).backward()
                    scaler.unscale_(optim)
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    scaler.step(optim)
                    scaler.update()
                else:
                    out = model(input_ids, attention_mask, token_labels, char_labels, char_token_index)
                    loss = out["loss"]
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    optim.step()

                scheduler.step()
                running_loss += loss.item()
                pbar.set_postfix(loss=f"{running_loss / step:.4f}",
                                 token=f"{(out['token_loss'].item() if out['token_loss'] is not None else 0):.3f}",
                                 char=f"{(out['char_loss'].item() if out['char_loss'] is not None else 0):.3f}")

            # 4) Validate
            val_metrics = evaluate_loop(model, val_loader, args)
            history.append({
                "epoch": epoch,
                "train_loss": running_loss / max(1, len(train_loader)),
                **val_metrics
            })
            print(f"[VAL] epoch={epoch} | precision={val_metrics['precision']:.4f} "
                  f"recall={val_metrics['recall']:.4f} f1={val_metrics['f1']:.4f} "
                  f"non_phi_retention={val_metrics['non_phi_retention']:.4f}")

            # Save best
            if val_metrics["f1"] > best_val_f1:
                best_val_f1 = val_metrics["f1"]
                save_checkpoint(model, tokenizer, args.output_dir, args, best=True, metrics=val_metrics)

        # Final save + history
        save_checkpoint(model, tokenizer, args.output_dir, args, best=False, metrics=history[-1] if history else {})
        write_text(os.path.join(args.output_dir, "train_history.json"), json.dumps(history, indent=2))

        # Evaluate best on TEST split (base only)
        best_dir = os.path.join(args.output_dir, "best")
        if os.path.isdir(best_dir):
            print("[INFO] Evaluating best checkpoint on TEST split...")
            model_best, tok_best, cfg = load_checkpoint(best_dir)
            test_ds = RedactionDataset(test_ex, tok_best, max_tokens=cfg.get("max_tokens", args.max_tokens),
                                       training=False, augment=False)
            test_loader = DataLoader(test_ds, batch_size=args.batch_size, shuffle=False,
                                     num_workers=2, collate_fn=collate_batch, pin_memory=True)
            metrics = evaluate_loop(model_best, test_loader, argparse.Namespace(char_threshold=cfg.get("char_threshold", args.char_threshold)))
            print("[TEST] ", metrics)
            write_text(os.path.join(best_dir, "test_metrics.json"), json.dumps(metrics, indent=2))
        else:
            print("[WARN] No best checkpoint found; skipping test evaluation.")

    elif args.cmd == "eval":
        print(f"[INFO] Loading data from {args.data_root}")
        examples = build_examples(args.data_root)
        # For eval, re-use the split logic but only test split is meaningful here;
        # we evaluate on ALL files to provide a global metric.
        tokenizer = AutoTokenizer.from_pretrained(args.checkpoint, use_fast=True)
        model, tokenizer, cfg = load_checkpoint(args.checkpoint)

        ds = RedactionDataset(examples, tokenizer, max_tokens=cfg.get("max_tokens", 512), training=False, augment=False)
        loader = DataLoader(ds, batch_size=4, shuffle=False, num_workers=2, collate_fn=collate_batch, pin_memory=True)
        metrics = evaluate_loop(model, loader, argparse.Namespace(char_threshold=cfg.get("char_threshold", 0.5)))
        print("[EVAL] ", metrics)
        write_text(os.path.join(args.checkpoint, "eval_metrics.json"), json.dumps(metrics, indent=2))

    elif args.cmd == "predict":
        if args.pred_model_path == "":
            model_dir = args.checkpoint
        else:
            model_dir = args.pred_model_path
            
        model, tokenizer, cfg = load_checkpoint(model_dir)
        text = read_text(args.input_tsv)
        red, _ = redact_text(model, tokenizer, text,
                             char_threshold=cfg.get("char_threshold", 0.5),
                             max_tokens=cfg.get("max_tokens", 512),
                             stride_tokens=64)
        write_text(args.output_tsv, red)
        print(f"[INFO] Wrote redacted output to {args.output_tsv}")

    else:
        raise RuntimeError("Unknown cmd")

if __name__ == "__main__":
    main()
