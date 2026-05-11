#!/usr/bin/env python3
"""
Polish Document Anonymizer (Offline Secure Edition)
==========================
Wymagania:
    pip install spacy transformers torch pymupdf huggingface_hub python-docx watchdog pystray pillow opencv-python-headless numpy
"""

import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import threading
import re
import json
from pathlib import Path
from datetime import datetime
import time
import queue
import gc

import cv2
import numpy as np
from PIL import ImageTk, Image, ImageDraw
import pystray
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from locales import TRANSLATIONS
from stopwords import STOP_WORDS 

# ─────────────────────────────────────────────
# Zmienne globalne
# ─────────────────────────────────────────────
spacy = None
nlp_spacy = None
pipeline_pii = None
fitz = None

MODELS_LOADED = False
MODELS_LOADING = False

if getattr(sys, 'frozen', False):
    application_path = Path(sys.executable).parent
    EXE_PATH = os.path.abspath(sys.executable)
else:
    application_path = Path(__file__).parent
    EXE_PATH = os.path.abspath(__file__)

BASE_MODEL_PATH = application_path / "offline_models"

# ==========================================
# СТАТИЧНА БАЗА ДАНИХ (GAZETTEER)
# ==========================================
KNOWN_NAMES_SET = set()


THEMES = {
    "light": {
        "bg": "#f3f4f6",
        "panel": "#e5e7eb",
        "card": "#ffffff",
        "text_primary": "#374151",
        "text_secondary": "#6b7280",
        "accent": "#4b5563",
        "accent2": "#0369a1",
        "accent_hover": "#374151",
        "border": "#d1d5db",
        "success": "#10b981",
        "danger": "#ef4444",
        "warning": "#f59e0b"
    },
    "dark": {
        "bg": "#1f2937",
        "panel": "#111827",
        "card": "#374151",
        "text_primary": "#f9fafb",
        "text_secondary": "#9ca3af",
        "accent": "#6b7280",
        "accent2": "#4b5563",
        "accent_hover": "#9ca3af",
        "border": "#4b5563",
        "success": "#059669",
        "danger": "#dc2626",
        "warning": "#d97706"
    }
}

def load_names_db(log_callback=None):
    global KNOWN_NAMES_SET
    db_path = BASE_MODEL_PATH / "names_db.txt"
    if db_path.exists():
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                KNOWN_NAMES_SET.update(line.strip().lower() for line in f if line.strip())
        except Exception as e:
            if log_callback: log_callback("log_error", str(e))

# ─────────────────────────────────────────────
# Inicjalizacja modeli i OCR
# ─────────────────────────────────────────────
def ensure_models_exist(log_callback=None):
    if sys.stderr is None:
        class DummyOutput:
            def write(self, *args, **kwargs): pass
            def flush(self, *args, **kwargs): pass
        sys.stderr = DummyOutput()
        sys.stdout = DummyOutput()

    os.environ['CURL_CA_BUNDLE'] = ''
    os.environ['PYTHONHTTPSVERIFY'] = '0'
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1" 

    path_pii = BASE_MODEL_PATH / "eu-pii-anonimization"
    path_spacy = BASE_MODEL_PATH / "pl_core_news_lg"
    path_tesseract = BASE_MODEL_PATH / "tesseract"
    tesseract_exe = path_tesseract / "tesseract.exe"

    pii_missing = not path_pii.exists() or not list(path_pii.glob('*'))
    spacy_missing = not path_spacy.exists() or not list(path_spacy.glob('*'))

    if pii_missing or spacy_missing:
        BASE_MODEL_PATH.mkdir(parents=True, exist_ok=True)
        from huggingface_hub import snapshot_download
        from huggingface_hub.utils import disable_progress_bars
        disable_progress_bars()
        
        HF_TOKEN = "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" 
        try:
            if pii_missing:
                snapshot_download(repo_id="bardsai/eu-pii-anonimization-multilang", local_dir=str(path_pii), token=HF_TOKEN, local_dir_use_symlinks=False, ignore_patterns=["*.msgpack", "*.h5", "*.ot", "*.onnx", "*.flax"])
            if spacy_missing:
                snapshot_download(repo_id="spacy/pl_core_news_lg", local_dir=str(path_spacy), token=HF_TOKEN, local_dir_use_symlinks=False, ignore_patterns=["*.h5", "*.ot", "*.onnx", "*.flax"])
        except Exception as e:
            if log_callback: log_callback("log_error", str(e))
            raise e

    if tesseract_exe.exists():
        abs_tess_path = str(path_tesseract.absolute())
        abs_tessdata_path = str((path_tesseract / "tessdata").absolute())
        os.environ["PATH"] = abs_tess_path + os.pathsep + os.environ.get("PATH", "")
        os.environ["TESSDATA_PREFIX"] = abs_tessdata_path

def lazy_load_models(log_callback=None):
    global spacy, nlp_spacy, pipeline_pii, fitz, MODELS_LOADED, MODELS_LOADING
    MODELS_LOADING = True

    def log(msg, *args):
        if log_callback: log_callback(msg, *args)
        
    try:
        ensure_models_exist(log)
    except Exception:
        return

    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['HF_DATASETS_OFFLINE'] = '1'

    try:
        import fitz as _fitz
        fitz = _fitz
    except ImportError:
        pass

    try:
        import spacy as _spacy
        spacy = _spacy
        path_spacy = str(BASE_MODEL_PATH / "pl_core_news_lg")
        nlp_spacy = spacy.load(path_spacy)
    except Exception:
        pass

    try:
        from transformers import pipeline as hf_pipeline
        path_pii = str(BASE_MODEL_PATH / "eu-pii-anonimization")
        pipeline_pii = hf_pipeline("ner", model=path_pii, tokenizer=path_pii, aggregation_strategy="simple")
    except Exception:
        pass

    try:
        load_names_db(log)
    except Exception:
        pass

    MODELS_LOADED = True
    MODELS_LOADING = False
    log("models_ready")

# ─────────────────────────────────────────────
# Mapowanie RegEx i NER
# ─────────────────────────────────────────────
REGEX_PATTERNS = {
    "pesel": (r"\b\d{11}\b", "PESEL"),
    "nip": (r"\b(\d{3}[-–]?\d{3}[-–]?\d{2}[-–]?\d{2}|\d{10})\b", "NIP"),
    "regon": (r"\b(\d{9}|\d{14})\b", "REGON"),
    "iban": (r"\b(PL\d{2}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4})\b", "IBAN"),
    "card": (r"\b(?:\d[ -]*?){13,16}\b", "KARTA"),
    "cvv": (r"\b\d{3}\b(?=\s|$)", "CVV"),
    "phone": (r"(?<!\d)(\+48[\s\-]?)?(\d{3}[\s\-]?\d{3}[\s\-]?\d{3})(?!\d)", "TELEFON"),
    "email": (r"\b([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b", "EMAIL"),
    "ip": (r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b", "IP"),
    "postal_code": (r"\b(\d{2}-\d{3})\b", "KOD_POCZTOWY"),
    "passport": (r"\b([A-Z]{2}\d{7})\b", "PASZPORT"),
    "pwz": (r"\b(PWZ[\s:]?\d{7})\b", "PWZ"),
    "street": (r"\b(ul\.|ulica)\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+\b", "ADRES"),
    "chat_log": (r"\b[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+(?:[- ][A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+){0,2}[\s\xa0]+(?:\d{1,2}:)?\d{1,3}:\d{2}\b", "LOG_CZATU"),
}

NER_LABEL_MAP = {
    "persName": "OSOBA", "PERSON": "OSOBA", "PER": "OSOBA", "nam_liv_person": "OSOBA",
    "placeName": "ADRES", "LOC": "ADRES", "GPE": "ADRES", "LOCATION": "ADRES", "nam_loc": "ADRES", "FAC": "ADRES", "ADDRESS": "ADRES",
    "orgName": "ORGANIZACJA", "ORG": "ORGANIZACJA", "nam_org": "ORGANIZACJA", "ORGANIZATION": "ORGANIZACJA",
}

CATEGORY_TO_NER = {
    "names": ["OSOBA"],
    "addresses": ["ADRES"],
    "companies": ["ORGANIZACJA"],
}

CATEGORY_TO_REGEX = {
    "pesel": "pesel", "nip": "nip", "regon": "regon", "iban": "iban",
    "phone": "phone", "email": "email", "ip": "ip", "postal_code": "postal_code",
    "passport": "passport", "pwz": "pwz", "card": "card", "cvv": "cvv",
    "addresses": "street", "names": "chat_log"
}

# ─────────────────────────────────────────────
# Logika anonimizacji
# ─────────────────────────────────────────────
class TokenRegistry:
    def __init__(self):
        self.registry = {}
        self._counter = {}

    def get_or_create(self, original: str, label: str) -> str:
        key = original.strip()
        if key in self.registry:
            return self.registry[key]["token"]
        prefix = label[:3].upper()
        if label == "LOG_CZATU": prefix = "LOG"
        idx = self._counter.get(label, 0) + 1
        self._counter[label] = idx
        token = f"[{prefix}_{idx:03d}]"
        self.registry[key] = {"token": token, "label": label, "original": key, "count": 1}
        return token
    
    def get_token(self, original: str, cat: str) -> str:
        label = "OSOBA" if cat == "names" else "ENT"
        return self.get_or_create(original, label)

    def to_dict(self) -> dict:
        return self.registry

def run_names_db(text: str, enabled_cats: set, registry: TokenRegistry) -> list:
    findings = []
    if "names" not in enabled_cats or not KNOWN_NAMES_SET:
        return findings
    pattern = re.compile(r'\b[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+\b')
    for match in pattern.finditer(text):
        word = match.group(0)
        if word.lower() in STOP_WORDS: continue
        if word.lower() in KNOWN_NAMES_SET:
            findings.append((match.start(), match.end(), registry.get_token(word, "names"), "OSOBA", "regex"))
    return findings

def run_regex(text: str, enabled_cats: set, registry: TokenRegistry) -> list:
    findings = []
    for cat, pattern_key in CATEGORY_TO_REGEX.items():
        if cat not in enabled_cats: continue
        pattern, label = REGEX_PATTERNS[pattern_key]
        
        for m in re.finditer(pattern, text, re.IGNORECASE):
            if label == "CVV":
                line_start = text.rfind('\n', 0, m.start())
                line_start = 0 if line_start == -1 else line_start + 1
                line_end = text.find('\n', m.end())
                line_end = len(text) if line_end == -1 else line_end
                line_text = text[line_start:line_end]
                
                if not re.search(r'\b(?:cvv|cvc)\b', line_text, re.IGNORECASE):
                    continue

            token = registry.get_or_create(m.group(), label)
            findings.append((m.start(), m.end(), token, label, "regex"))
    return findings

def run_spacy(text: str, enabled_cats: set, registry: TokenRegistry) -> list:
    if nlp_spacy is None: return []
    findings = []
    doc = nlp_spacy(text)
    for ent in doc.ents:
        if ent.text.strip().lower() in STOP_WORDS or len(ent.text.strip()) < 2:
            continue
        mapped = NER_LABEL_MAP.get(ent.label_, None)
        if mapped is None: continue
        cat = next((c for c, labels in CATEGORY_TO_NER.items() if mapped in labels), None)
        if cat and cat in enabled_cats:
            token = registry.get_or_create(ent.text, mapped)
            findings.append((ent.start_char, ent.end_char, token, mapped, "spacy"))
    return findings

def run_transformer(pipe, name: str, text: str, enabled_cats: set, registry: TokenRegistry) -> list:
    if pipe is None: return []
    findings = []
    try:
        results = pipe(text)
        for ent in results:
            start = ent.get("start", 0)
            end = ent.get("end", 0)
            word = text[start:end]
            if word.strip().lower() in STOP_WORDS or len(word.strip()) < 2:
                continue

            raw_label = ent.get("entity_group", ent.get("entity", ""))
            mapped = NER_LABEL_MAP.get(raw_label, NER_LABEL_MAP.get(raw_label.upper()))
            if mapped is None: continue
            cat = next((c for c, labels in CATEGORY_TO_NER.items() if mapped in labels), None)
            if cat and cat in enabled_cats:
                token = registry.get_or_create(word, mapped)
                findings.append((start, end, token, mapped, name))
    except Exception:
        pass
    return findings

def vote_and_anonymize(text: str, all_findings: list) -> tuple[str, list]:
    ml_count = sum(1 for s in [nlp_spacy, pipeline_pii] if s is not None)
    threshold = max(1, ml_count * 0.5)

    span_votes = {}
    for start, end, token, label, source in all_findings:
        key = (start, end)
        if key not in span_votes:
            span_votes[key] = {"token": token, "label": label, "force": False, "votes": set()}
        if source == "regex":
            span_votes[key]["force"] = True
        else:
            span_votes[key]["votes"].add(source)

    to_anonymize = []
    for (start, end), info in span_votes.items():
        if info["force"] or len(info["votes"]) >= threshold:
            to_anonymize.append((start, end, info["token"], info["label"]))

    to_anonymize.sort(key=lambda x: x[0])
    merged = []
    for span in to_anonymize:
        if not merged or span[0] >= merged[-1][1]:
            merged.append(list(span))
        elif span[1] > merged[-1][1]:
            merged[-1][1] = span[1]

    result = []
    prev = 0
    for start, end, token, label in merged:
        result.append(text[prev:start])
        result.append(token)
        prev = end
    result.append(text[prev:])

    return "".join(result), merged

# ─────────────────────────────────────────────
# Logo Selector (OpenCV + Tkinter)
# ─────────────────────────────────────────────
class LogoSelector(tk.Toplevel):
    def __init__(self, parent, pdf_path):
        super().__init__(parent)
        self.parent_app = parent 
        self.title(self.parent_app._t("msg_logo_select_title"))
        self.geometry("800x900")
        
        self.pdf_path = pdf_path
        self.template_image = None
        self.zoom = 2.0 

        self._load_first_page()
        self._build_canvas()

    def _load_first_page(self):
        doc = fitz.open(self.pdf_path)
        page = doc[0]
        mat = fitz.Matrix(self.zoom, self.zoom) 
        self.pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [self.pix.width, self.pix.height], self.pix.samples)
        self.tk_image = ImageTk.PhotoImage(img)
        doc.close()

    def _build_canvas(self):
        self.canvas = tk.Canvas(self, cursor="cross")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_image)

        self.rect_id = None
        self.start_x = None
        self.start_y = None

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

    def _on_press(self, event):
        self.start_x = self.canvas.canvasx(event.x)
        self.start_y = self.canvas.canvasy(event.y)
        if self.rect_id: self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline="red", width=3)

    def _on_drag(self, event):
        if self.rect_id is None: return
        cur_x = self.canvas.canvasx(event.x)
        cur_y = self.canvas.canvasy(event.y)
        self.canvas.coords(self.rect_id, self.start_x, self.start_y, cur_x, cur_y)

    def _on_release(self, event):
        end_x = self.canvas.canvasx(event.x)
        end_y = self.canvas.canvasy(event.y)
        
        x1, y1 = min(self.start_x, end_x), min(self.start_y, end_y)
        x2, y2 = max(self.start_x, end_x), max(self.start_y, end_y)
        
        if abs(x2 - x1) > 10 and abs(y2 - y1) > 10:
            img_np = np.frombuffer(self.pix.samples, dtype=np.uint8).reshape(self.pix.height, self.pix.width, self.pix.n)
            if self.pix.n == 4:
                img_cv = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR)
            else:
                img_cv = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
            
            self.template_image = img_cv[int(y1):int(y2), int(x1):int(x2)]
            messagebox.showinfo("Zapisano", self.parent_app._t("msg_logo_captured"))

# ─────────────────────────────────────────────
# Przetwarzanie plików
# ─────────────────────────────────────────────
def anonymize_pdf(input_path: str, output_path: str, enabled_cats: set, registry: TokenRegistry, log_cb=None, logo_template=None) -> dict:
    if fitz is None:
        if log_cb: log_cb("log_error", "pymupdf nie jest zainstalowany")
        return {}

    doc = fitz.open(input_path)
    for page_num, page in enumerate(doc):
        if log_cb: log_cb("log_pdf_page", page_num + 1, len(doc))
        
        text = page.get_text("text")
        search_page = page 
        ocr_doc = None     
        draw_queue = []

        if logo_template is not None:
            try:
                zoom = 2.0
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat)
                
                img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                if pix.n == 4:
                    img_cv = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR)
                else:
                    img_cv = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
                
                result = cv2.matchTemplate(img_cv, logo_template, cv2.TM_CCOEFF_NORMED)
                threshold = 0.8
                locations = np.where(result >= threshold)
                
                h, w = logo_template.shape[:2]
                detected_count = 0
                
                for pt in zip(*locations[::-1]):
                    x1, y1 = pt[0], pt[1]
                    x2, y2 = pt[0] + w, pt[1] + h
                    pdf_rect = fitz.Rect(x1/zoom, y1/zoom, x2/zoom, y2/zoom)
                    page.add_redact_annot(pdf_rect, fill=(0, 0, 0))
                    
                    token = "[LOGO]"
                    font_size = max(4, min(8, pdf_rect.height * 0.7))
                    text_width = fitz.get_text_length(token, fontsize=font_size)
                    t_x = pdf_rect.x0 + (pdf_rect.width - text_width) / 2
                    t_y = pdf_rect.y1 - (pdf_rect.height - font_size) / 2
                    draw_queue.append((t_x, t_y, token, font_size))
                    detected_count += 1
                
                if detected_count > 0 and log_cb:
                    log_cb("log_logo_found", detected_count)
            except Exception as e:
                if log_cb: log_cb("log_error", str(e))

        if len(text.strip()) < 50:
            if log_cb: log_cb("log_ocr_detect", page_num + 1)
            try:
                import os
                old_cwd = os.getcwd()
                tess_dir = str((BASE_MODEL_PATH / "tesseract").absolute())
                tessdata_dir = str((BASE_MODEL_PATH / "tesseract" / "tessdata").absolute())
                
                os.chdir(tess_dir)
                pix = page.get_pixmap(dpi=300)
                ocr_pdf_bytes = pix.pdfocr_tobytes(language="pol", tessdata=tessdata_dir)
                os.chdir(old_cwd)
                
                ocr_doc = fitz.open("pdf", ocr_pdf_bytes)
                search_page = ocr_doc[0]
                text = search_page.get_text("text")
                
                if log_cb: log_cb("log_ocr_success", len(text))
            except Exception as e:
                import os
                if 'old_cwd' in locals(): os.chdir(old_cwd)
                if log_cb: log_cb("log_error", str(e))

        if not text.strip():
            if ocr_doc: ocr_doc.close()
            if draw_queue:
                page.apply_redactions()
                for x, y, tkn, fs in draw_queue:
                    page.insert_text((x, y), tkn, fontsize=fs, color=(1, 1, 1))
            continue

        all_findings = []
        all_findings.extend(run_names_db(text, enabled_cats, registry))
        all_findings.extend(run_regex(text, enabled_cats, registry))
        all_findings.extend(run_spacy(text, enabled_cats, registry))
        all_findings.extend(run_transformer(pipeline_pii, "bardsai", text, enabled_cats, registry))

        _, merged = vote_and_anonymize(text, all_findings)

        for start, end, token, label in merged:
            word = text[start:end].strip()
            if not word or len(word) < 2: continue
            instances = search_page.search_for(word)
            for rect in instances:
                page.add_redact_annot(rect, fill=(0, 0, 0)) 
                font_size = max(4, min(8, rect.height * 0.7))
                text_width = fitz.get_text_length(token, fontsize=font_size)
                t_x = rect.x0 + (rect.width - text_width) / 2
                t_y = rect.y1 - (rect.height - font_size) / 2
                draw_queue.append((t_x, t_y, token, font_size))
        
        page.apply_redactions()

        for x, y, tkn, fs in draw_queue:
            page.insert_text((x, y), tkn, fontsize=fs, color=(1, 1, 1))
            
        if ocr_doc: ocr_doc.close()

    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
    return registry.to_dict()

def anonymize_docx(input_path: str, output_path: str, enabled_cats: set, registry: TokenRegistry, log_cb=None) -> dict:
    try:
        import docx
    except ImportError:
        if log_cb: log_cb("log_error", "biblioteka 'python-docx' nie jest zainstalowana.")
        return {}

    doc = docx.Document(input_path)

    def process_text_block(block):
        if not block.text.strip(): return
        text = block.text
        all_findings = []
        all_findings.extend(run_names_db(text, enabled_cats, registry))
        all_findings.extend(run_regex(text, enabled_cats, registry))
        all_findings.extend(run_spacy(text, enabled_cats, registry))
        all_findings.extend(run_transformer(pipeline_pii, "bardsai", text, enabled_cats, registry))
        
        anonymized_text, merged = vote_and_anonymize(text, all_findings)
        if merged: block.text = anonymized_text

    for para in doc.paragraphs: process_text_block(para)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs: process_text_block(para)

    doc.save(output_path)
    return registry.to_dict()

def anonymize_text_file(input_path: str, output_path: str, enabled_cats: set, registry: TokenRegistry, log_cb=None) -> dict:
    with open(input_path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    all_findings = []
    all_findings.extend(run_names_db(text, enabled_cats, registry))
    all_findings.extend(run_regex(text, enabled_cats, registry))
    all_findings.extend(run_spacy(text, enabled_cats, registry))
    all_findings.extend(run_transformer(pipeline_pii, "bardsai", text, enabled_cats, registry))

    anonymized_text, merged = vote_and_anonymize(text, all_findings)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(anonymized_text)

    return registry.to_dict()

class HotFolderHandler(FileSystemEventHandler):
    def __init__(self, file_queue):
        self.queue = file_queue

    def on_created(self, event):
        if not event.is_directory:
            path = event.src_path
            if "~$" not in path and any(path.lower().endswith(ext) for ext in ['.pdf', '.docx', '.txt', '.text']):
                self.queue.put(path)

# ─────────────────────────────────────────────
# GUI (Dynamic Theme & Localization)
# ─────────────────────────────────────────────
class AnonymizerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.current_lang = "pl"
        self.current_theme = "light"
        
        self.title(self._t("app_title"))
        self.geometry("980x780")
        self.resizable(True, True)

        self.selected_file = tk.StringVar()
        self.status_var = tk.StringVar()
        self.registry = TokenRegistry()

        self.cat_vars = {
            "names": tk.BooleanVar(value=True), "addresses": tk.BooleanVar(value=True),
            "companies": tk.BooleanVar(value=True), "pesel": tk.BooleanVar(value=True),
            "nip": tk.BooleanVar(value=True), "regon": tk.BooleanVar(value=True),
            "iban": tk.BooleanVar(value=True), "card": tk.BooleanVar(value=True),
            "cvv": tk.BooleanVar(value=True), "phone": tk.BooleanVar(value=True),
            "email": tk.BooleanVar(value=True), "ip": tk.BooleanVar(value=True),
            "postal_code": tk.BooleanVar(value=True), "passport": tk.BooleanVar(value=True),
            "pwz": tk.BooleanVar(value=True), "logos": tk.BooleanVar(value=True),
        }

        self.watch_src = tk.StringVar()
        self.watch_dst = tk.StringVar()
        self.is_watching = False
        self.observer = None
        self.auto_queue = queue.Queue()
        
        self.last_activity = time.time()
        self.is_processing = False
        self.tray_icon = None
        self.ui_elements = []

        self._rebuild_ui()
        self._start_model_loading()

        self.protocol("WM_DELETE_WINDOW", self._hide_to_tray)
        threading.Thread(target=self._idle_monitor, daemon=True).start()
        threading.Thread(target=self._auto_process_worker, daemon=True).start()

    def _t(self, key: str) -> str:
        return TRANSLATIONS[self.current_lang].get(key, key)

    def _switch_lang(self, lang):
        self.current_lang = lang
        self._rebuild_ui()

    def _switch_theme(self):
        self.current_theme = "dark" if self.current_theme == "light" else "light"
        self._apply_theme()

    def _toggle_autostart(self):
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            app_name = "AnonSupreme"
            
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
            try:
                winreg.QueryValueEx(key, app_name)
                winreg.DeleteValue(key, app_name)
                messagebox.showinfo("Autostart", "❌ Program został usunięty z autostartu Windows.")
            except FileNotFoundError:
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, f'"{EXE_PATH}"')
                messagebox.showinfo("Autostart", "✅ Program został dodany do autostartu Windows.")
            finally:
                winreg.CloseKey(key)
        except Exception as e:
            self._log("log_error", str(e))
            messagebox.showerror("Błąd", f"Nie udało się zmienić ustawień:\n{e}")

    def _rebuild_ui(self):
        for widget in self.winfo_children():
            widget.destroy()
        self.ui_elements.clear()

        self.title(self._t("app_title"))
        self.status_var.set(self._t("status_ready"))

        # Top Bar (Language & Theme)
        top = tk.Frame(self)
        self.ui_elements.append({"widget": top, "type": "bg"})
        top.pack(fill="x", padx=20, pady=(15, 0))

        btn_opts = {"font": ("Verdana", 9, "bold"), "relief": "flat", "padx": 10, "cursor": "hand2"}
        btn_pl = tk.Button(top, text="PL", command=lambda: self._switch_lang("pl"), **btn_opts)
        btn_uk = tk.Button(top, text="UK", command=lambda: self._switch_lang("uk"), **btn_opts)
        btn_theme = tk.Button(top, text="🌓", command=self._switch_theme, **btn_opts)

        self.ui_elements.extend([
            {"widget": btn_pl, "type": "btn_accent"}, 
            {"widget": btn_uk, "type": "btn_accent"}, 
            {"widget": btn_theme, "type": "btn_accent"}
        ])
        btn_pl.pack(side="left")
        btn_uk.pack(side="left", padx=5)
        btn_theme.pack(side="right")

        # Header
        header = tk.Frame(self)
        self.ui_elements.append({"widget": header, "type": "bg"})
        header.pack(fill="x", padx=20, pady=(10, 0))

        lbl_title = tk.Label(header, text=self._t("app_title"), font=("Verdana", 15, "bold"))
        self.ui_elements.append({"widget": lbl_title, "type": "lbl_title"})
        lbl_title.pack(side="left")

        self.model_status_label = tk.Label(header, text=self._t("loading_models"), font=("Verdana", 9, "bold"))
        self.ui_elements.append({"widget": self.model_status_label, "type": "lbl_model"})
        self.model_status_label.pack(side="right", padx=10)

        # Main Content Wrapper
        content = tk.Frame(self)
        self.ui_elements.append({"widget": content, "type": "bg"})
        content.pack(fill="both", expand=True, padx=20, pady=12)

        left = tk.Frame(content)
        self.ui_elements.append({"widget": left, "type": "bg"})
        left.pack(side="left", fill="both", expand=True)

        right = tk.Frame(content, width=320)
        self.ui_elements.append({"widget": right, "type": "bg"})
        right.pack(side="right", fill="y", padx=(12, 0))
        right.pack_propagate(False)

        # --- LEFT FRAME ---
        f_card = self._create_card(left, self._t("file_select_title"))
        ent_file = tk.Entry(f_card, textvariable=self.selected_file, font=("Verdana", 9), relief="flat", bd=6)
        self.ui_elements.append({"widget": ent_file, "type": "entry"})
        ent_file.pack(side="left", fill="x", expand=True, padx=(0, 8))
        
        btn_browse = tk.Button(f_card, text=self._t("browse"), command=self._browse_file, font=("Verdana", 9, "bold"), relief="flat", cursor="hand2")
        self.ui_elements.append({"widget": btn_browse, "type": "btn_accent"})
        btn_browse.pack(side="right")

        c_card = self._create_card(left, self._t("categories_title"))
        grid_frame = tk.Frame(c_card)
        self.ui_elements.append({"widget": grid_frame, "type": "card_bg"})
        grid_frame.pack(fill="x")

        cols = 3
        for i, key in enumerate(self.cat_vars.keys()):
            row_i, col_i = i // cols, i % cols
            cb = tk.Checkbutton(grid_frame, text=self._t(key), variable=self.cat_vars[key], font=("Verdana", 8), cursor="hand2")
            self.ui_elements.append({"widget": cb, "type": "cb"})
            cb.grid(row=row_i, column=col_i, sticky="w", padx=6, pady=2)

        btn_row = tk.Frame(c_card)
        self.ui_elements.append({"widget": btn_row, "type": "card_bg"})
        btn_row.pack(fill="x", pady=(6, 0))
        
        btn_sel = tk.Button(btn_row, text=self._t("sel_all"), command=self._select_all, font=("Verdana", 8, "bold"), relief="flat", cursor="hand2")
        btn_desel = tk.Button(btn_row, text=self._t("desel_all"), command=self._deselect_all, font=("Verdana", 8, "bold"), relief="flat", cursor="hand2")
        self.ui_elements.append({"widget": btn_sel, "type": "btn_accent"})
        self.ui_elements.append({"widget": btn_desel, "type": "btn_danger"})
        btn_sel.pack(side="left", padx=(0, 6))
        btn_desel.pack(side="left")

        auto_card = self._create_card(left, self._t("auto_mode_title"))
        src_row = tk.Frame(auto_card)
        dst_row = tk.Frame(auto_card)
        self.ui_elements.append({"widget": src_row, "type": "card_bg"})
        self.ui_elements.append({"widget": dst_row, "type": "card_bg"})
        src_row.pack(fill="x", pady=(0, 4))
        dst_row.pack(fill="x", pady=(4, 8))
        
        btn_src = tk.Button(src_row, text=self._t("src_folder"), command=self._browse_src_dir, font=("Verdana", 8, "bold"), relief="flat", padx=6)
        ent_src = tk.Entry(src_row, textvariable=self.watch_src, font=("Verdana", 8), relief="flat", state="readonly")
        self.ui_elements.append({"widget": btn_src, "type": "btn_accent"})
        self.ui_elements.append({"widget": ent_src, "type": "entry_disabled"})
        btn_src.pack(side="left")
        ent_src.pack(side="left", fill="x", expand=True, padx=(6, 0))
        
        btn_dst = tk.Button(dst_row, text=self._t("dst_folder"), command=self._browse_dst_dir, font=("Verdana", 8, "bold"), relief="flat", padx=6)
        ent_dst = tk.Entry(dst_row, textvariable=self.watch_dst, font=("Verdana", 8), relief="flat", state="readonly")
        self.ui_elements.append({"widget": btn_dst, "type": "btn_accent"})
        self.ui_elements.append({"widget": ent_dst, "type": "entry_disabled"})
        btn_dst.pack(side="left")
        ent_dst.pack(side="left", fill="x", expand=True, padx=(6, 0))
        
        self.watch_btn = tk.Button(auto_card, text=self._t("start_watch") if not self.is_watching else self._t("stop_watch"), command=self._toggle_watch, font=("Verdana", 9, "bold"), relief="flat")
        self.ui_elements.append({"widget": self.watch_btn, "type": "btn_accent"})
        self.watch_btn.pack(fill="x")

        self.run_btn = tk.Button(left, text=self._t("run_btn"), command=self._run_anonymization, font=("Verdana", 12, "bold"), pady=8, cursor="hand2", relief="flat")
        self.ui_elements.append({"widget": self.run_btn, "type": "btn_accent2"})
        self.run_btn.pack(fill="x", pady=(10, 0))

        log_card = self._create_card(left, self._t("log_title"))
        self.log_text = scrolledtext.ScrolledText(log_card, height=10, font=("Verdana", 8), relief="flat", bd=1, state="disabled")
        self.ui_elements.append({"widget": self.log_text, "type": "log"})
        self.log_text.pack(fill="both", expand=True)

        # --- RIGHT FRAME ---
        reg_label = tk.Label(right, text="🗃️ Token Registry", font=("Verdana", 10, "bold"))
        self.ui_elements.append({"widget": reg_label, "type": "lbl_title"})
        reg_label.pack(anchor="w", pady=(0, 6))
        
        self.registry_text = scrolledtext.ScrolledText(right, font=("Courier New", 8), relief="flat", bd=1, highlightthickness=1)
        self.ui_elements.append({"widget": self.registry_text, "type": "registry"})
        self.registry_text.pack(fill="both", expand=True)
        self.registry_text.configure(state="disabled")

        export_row = tk.Frame(right)
        self.ui_elements.append({"widget": export_row, "type": "bg"})
        export_row.pack(fill="x", pady=(6, 0))
        
        btn_export = tk.Button(export_row, text=self._t("export_btn"), command=self._export_registry, font=("Verdana", 8, "bold"), relief="flat", pady=4)
        btn_menu = tk.Button(export_row, text=self._t("add_menu"), command=self._add_context_menu, font=("Verdana", 8, "bold"), relief="flat", pady=4)
        btn_auto = tk.Button(export_row, text=self._t("autostart"), command=self._toggle_autostart, font=("Verdana", 8, "bold"), relief="flat", pady=4)

        self.ui_elements.append({"widget": btn_export, "type": "btn_accent"})
        self.ui_elements.append({"widget": btn_menu, "type": "btn_accent2"})
        self.ui_elements.append({"widget": btn_auto, "type": "btn_accent"})

        btn_export.pack(fill="x", pady=(0, 6))
        btn_menu.pack(fill="x", pady=(0, 6))
        btn_auto.pack(fill="x")

        # Status Bar
        status_bar = tk.Frame(self, height=24)
        self.ui_elements.append({"widget": status_bar, "type": "panel"})
        status_bar.pack(fill="x", side="bottom")
        
        lbl_status = tk.Label(status_bar, textvariable=self.status_var, font=("Verdana", 8))
        self.ui_elements.append({"widget": lbl_status, "type": "lbl_status"})
        lbl_status.pack(side="left", padx=10)

        self._apply_theme()
        # Повторне заповнення панелі реєстру після зміни мови/теми
        self._update_registry_panel()

    def _create_card(self, parent, title: str) -> tk.Frame:
        wrapper = tk.Frame(parent)
        self.ui_elements.append({"widget": wrapper, "type": "bg"})
        wrapper.pack(fill="x", pady=(0, 10))
        
        lbl = tk.Label(wrapper, text=title, font=("Verdana", 9, "bold"))
        self.ui_elements.append({"widget": lbl, "type": "lbl_card"})
        lbl.pack(anchor="w", pady=(0, 4))
        
        card = tk.Frame(wrapper, bd=0, relief="flat", padx=12, pady=10)
        self.ui_elements.append({"widget": card, "type": "card_bg"})
        card.configure(highlightthickness=1)
        card.pack(fill="x")
        return card

    def _apply_theme(self):
        t = THEMES[self.current_theme]
        self.configure(bg=t["bg"])
        
        for item in self.ui_elements:
            w = item["widget"]
            w_type = item["type"]
            if not w.winfo_exists(): continue
            
            if w_type == "bg":
                w.configure(bg=t["bg"])
            elif w_type == "card_bg":
                w.configure(bg=t["card"], highlightbackground=t["border"])
            elif w_type == "lbl_title":
                w.configure(bg=t["bg"], fg=t["accent"])
            elif w_type == "lbl_card":
                w.configure(bg=t["bg"], fg=t["text_secondary"])
            elif w_type == "lbl_model":
                w.configure(bg=t["bg"], fg=t["warning"])
            elif w_type == "entry":
                w.configure(bg=t["bg"], fg=t["text_primary"], insertbackground=t["accent"])
            elif w_type == "entry_disabled":
                w.configure(bg=t["panel"], fg=t["text_secondary"])
            elif w_type == "cb":
                w.configure(bg=t["card"], fg=t["text_primary"], selectcolor=t["bg"], activebackground=t["card"], activeforeground=t["accent"])
            elif w_type == "btn_accent":
                w.configure(bg=t["accent"], fg="#ffffff", activebackground=t["accent_hover"], activeforeground="#ffffff")
            elif w_type == "btn_accent2":
                w.configure(bg=t["accent2"] if self.current_theme == "light" else t["success"], fg="#ffffff", activebackground=t["accent_hover"], activeforeground="#ffffff")
            elif w_type == "btn_danger":
                w.configure(bg=t["danger"], fg="#ffffff", activebackground=t["text_secondary"], activeforeground="#ffffff")
            elif w_type == "log":
                w.configure(bg=t["card"], fg=t["success"], insertbackground=t["success"])
            elif w_type == "registry":
                w.configure(bg=t["card"], fg=t["text_primary"], insertbackground=t["accent"], highlightbackground=t["border"])
            elif w_type == "panel":
                w.configure(bg=t["panel"])
            elif w_type == "lbl_status":
                w.configure(bg=t["panel"], fg=t["text_secondary"])

    def _browse_file(self):
        path = filedialog.askopenfilename(
            title=self._t("file_select_title"), 
            filetypes=[("Obsługiwane pliki", "*.pdf *.docx *.txt *.text"), ("PDF", "*.pdf"), ("Dokument Word", "*.docx"), ("Pliki tekstowe", "*.txt *.text")]
        )
        if path: self.selected_file.set(path)

    def _select_all(self):
        for v in self.cat_vars.values(): v.set(True)

    def _deselect_all(self):
        for v in self.cat_vars.values(): v.set(False)

    def _log(self, key: str, *args):
        def _do():
            msg = self._t(key).format(*args) if args else self._t(key)
            self.log_text.configure(state="normal")
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_text.insert("end", f"[{ts}] {msg}\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(0, _do)

    def _update_registry_panel(self):
        def _do():
            reg = self.registry.to_dict()
            self.registry_text.configure(state="normal")
            self.registry_text.delete("1.0", "end")
            if not reg:
                self.registry_text.insert("end", self._t("msg_empty_reg") + "\n")
            else:
                for original, info in sorted(reg.items(), key=lambda x: x[1]["token"]):
                    line = f"{info['token']:12s} │ {info['label']:12s} │ {original[:30]}\n"
                    self.registry_text.insert("end", line)
            self.registry_text.configure(state="disabled")
        self.after(0, _do)

    def _export_registry(self):
        if not self.registry.to_dict():
            messagebox.showinfo("Uwaga", self._t("msg_empty_reg"))
            return
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")], initialfile="token_registry.json")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.registry.to_dict(), f, ensure_ascii=False, indent=2)
            messagebox.showinfo("✅ Zapisano", f"Rejestr zapisany:\n{path}")

    def _start_model_loading(self):
        def _done_cb(msg, *args):
            if msg == "models_ready":
                self.after(0, lambda: self.model_status_label.configure(text=self._t("models_ready"), fg=THEMES[self.current_theme]["success"]))
            self._log(msg, *args)
        threading.Thread(target=lazy_load_models, args=(_done_cb,), daemon=True).start()
    
    def _add_context_menu(self):
        try:
            import winreg
            key_path = r"Software\Classes\*\shell\Anonimizuj"
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
            winreg.SetValue(key, "", winreg.REG_SZ, "🔒 Anonimizuj dokument")
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, f'"{EXE_PATH}"')
            winreg.CloseKey(key)

            cmd_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path + r"\command")
            winreg.SetValue(cmd_key, "", winreg.REG_SZ, f'"{EXE_PATH}" "%1"')
            winreg.CloseKey(cmd_key)
            self._log("log_context_menu")
            messagebox.showinfo("✅ Sukces", "Opcja dodana do menu pod prawym przyciskiem myszy!")
        except Exception as e:
            self._log("log_error", str(e))
            messagebox.showerror("❌ Błąd", f"Nie udało się zaktualizować rejestru:\n{str(e)}")

    def _run_anonymization(self):
        path = self.selected_file.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showwarning("⚠️ Uwaga", self._t("msg_select_file"))
            return

        enabled_cats = {k for k, v in self.cat_vars.items() if v.get()}
        if not enabled_cats:
            messagebox.showwarning("⚠️ Uwaga", self._t("msg_select_cat"))
            return

        p = Path(path)
        out_path = filedialog.asksaveasfilename(title=self._t("msg_save_title"), initialfile=f"{p.stem}_anonymized{p.suffix}", defaultextension=p.suffix, filetypes=[("Format", f"*{p.suffix}")])
        if not out_path: return

        self.run_btn.configure(state="disabled", text="⏳ ...")
        self.registry = TokenRegistry()

        logo_template_cv = None
        if path.lower().endswith(".pdf") and "logos" in enabled_cats:
            if messagebox.askyesno("Logo", self._t("msg_logo_ask")):
                selector = LogoSelector(self, path)
                self.wait_window(selector)
                if selector.template_image is not None:
                    logo_template_cv = selector.template_image

        def worker(cv_template):
            self.is_processing = True
            self.last_activity = time.time()
            
            global MODELS_LOADED
            if not MODELS_LOADED:
                self._log("log_wake_models")
                self.after(0, lambda: self.model_status_label.configure(text=self._t("loading_models")))
                lazy_load_models(lambda k, *a: self._log(k, *a))
                self.after(0, lambda: self.model_status_label.configure(text=self._t("models_ready")))

            self._log("log_start", p.name)
            try:
                if path.lower().endswith(".pdf"):
                    anonymize_pdf(path, out_path, enabled_cats, self.registry, lambda k, *a: self._log(k, *a), cv_template)
                elif path.lower().endswith(".docx"):
                    anonymize_docx(path, out_path, enabled_cats, self.registry, lambda k, *a: self._log(k, *a))
                else:
                    anonymize_text_file(path, out_path, enabled_cats, self.registry, lambda k, *a: self._log(k, *a))

                out_p = Path(out_path)
                reg_path = out_p.parent / f"{out_p.stem}_tokens.json"
                with open(reg_path, "w", encoding="utf-8") as f:
                    json.dump(self.registry.to_dict(), f, ensure_ascii=False, indent=2)

                self._update_registry_panel()
                reg_count = len(self.registry.to_dict())
                self._log("log_finish", reg_count)
                self.after(0, lambda: messagebox.showinfo(self._t("msg_finish_title"), self._t("msg_finish_body")))
            except Exception as e:
                self._log("log_error", str(e))
                self.after(0, lambda msg=str(e): messagebox.showerror("❌ Błąd", msg))
            finally:
                self.is_processing = False
                self.last_activity = time.time() 
                self.after(0, lambda: self.run_btn.configure(state="normal", text=self._t("run_btn")))
                self.after(0, lambda: self.status_var.set(f"OK: {p.name}"))

        threading.Thread(target=worker, args=(logo_template_cv,), daemon=True).start()

    def _browse_src_dir(self):
        path = filedialog.askdirectory(title="Źródło (nasłuchiwanie)")
        if path: self.watch_src.set(path)

    def _browse_dst_dir(self):
        path = filedialog.askdirectory(title="Zapis (docelowy)")
        if path: self.watch_dst.set(path)

    def _toggle_watch(self):
        if self.is_watching:
            self.is_watching = False
            if self.observer:
                self.observer.stop()
                self.observer.join()
                self.observer = None
            self.watch_btn.configure(text=self._t("start_watch"))
            self._log("log_watch_stop")
        else:
            src, dst = self.watch_src.get(), self.watch_dst.get()
            if not src or not dst:
                messagebox.showwarning("Uwaga", self._t("msg_auto_folders"))
                return
            if src == dst:
                messagebox.showwarning("Uwaga", "Folder źródłowy i docelowy nie mogą być tym samym folderem!")
                return
            if not MODELS_LOADED:
                return

            self.is_watching = True
            self.watch_btn.configure(text=self._t("stop_watch"))
            self._log("log_watch_start", src)

            event_handler = HotFolderHandler(self.auto_queue)
            self.observer = Observer()
            self.observer.schedule(event_handler, src, recursive=False)
            self.observer.start()

    def _auto_process_worker(self):
        while True:
            filepath = self.auto_queue.get() 
            self.is_processing = True
            self.last_activity = time.time()
            time.sleep(2) 
            
            global MODELS_LOADED
            if not MODELS_LOADED:
                self._log("log_wake_models")
                self.after(0, lambda: self.model_status_label.configure(text=self._t("loading_models")))
                lazy_load_models(lambda k, *a: self._log(k, *a))
                self.after(0, lambda: self.model_status_label.configure(text=self._t("models_ready")))

            try:
                p = Path(filepath)
                dst_folder = Path(self.watch_dst.get())
                out_path = str(dst_folder / f"{p.stem}_anonymized{p.suffix}")
                reg_path = dst_folder / f"{p.stem}_tokens.json"
                
                enabled_cats = {k for k, v in self.cat_vars.items() if v.get()}
                
                if p.suffix.lower() == ".pdf":
                    anonymize_pdf(filepath, out_path, enabled_cats, self.registry, lambda k, *a: self._log(k, *a))
                elif p.suffix.lower() == ".docx":
                    anonymize_docx(filepath, out_path, enabled_cats, self.registry, lambda k, *a: self._log(k, *a))
                else:
                    anonymize_text_file(filepath, out_path, enabled_cats, self.registry, lambda k, *a: self._log(k, *a))

                with open(reg_path, "w", encoding="utf-8") as f:
                    json.dump(self.registry.to_dict(), f, ensure_ascii=False, indent=2)

                self._update_registry_panel()
                self._log("log_finish", len(self.registry.to_dict()))
            except Exception as e:
                self._log("log_error", str(e))
            finally:
                self.is_processing = False
                self.last_activity = time.time() 
                self.auto_queue.task_done()
    
    def _idle_monitor(self):
        global nlp_spacy, pipeline_pii, MODELS_LOADED
        while True:
            time.sleep(10)
            if MODELS_LOADED and not self.is_processing:
                if time.time() - self.last_activity > 300:
                    self._log("log_idle_ram")
                    nlp_spacy, pipeline_pii = None, None
                    gc.collect()
                    MODELS_LOADED = False
                    self.after(0, lambda: self.model_status_label.configure(text=self._t("models_sleep")))

    def _hide_to_tray(self):
        self.withdraw() 
        if not self.tray_icon:
            img = Image.new('RGB', (64, 64), color=(2, 132, 199))
            d = ImageDraw.Draw(img)
            d.rectangle((16, 16, 48, 48), fill="white")
            menu = pystray.Menu(pystray.MenuItem("Pokaż okno", self._show_window), pystray.MenuItem("Zamknij całkowicie", self._quit_app))
            self.tray_icon = pystray.Icon("AnonSupreme", img, "AnonSupreme - Aktywny", menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _show_window(self, icon, item):
        self.tray_icon.stop()
        self.tray_icon = None
        self.after(0, self.deiconify)

    def _quit_app(self, icon, item):
        self.tray_icon.stop()
        os._exit(0) 

# ─────────────────────────────────────────────
# Punkt wejścia (SETUP / CLI / GUI)
# ─────────────────────────────────────────────
if __name__ == "__main__":
    if "--setup" in sys.argv:
        import winreg
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(TRANSLATIONS["pl"]["app_title"], "Rozpoczynam pobieranie modeli AI (ok. 1 GB).\nMoże to potrwać kilka minut w zależności od połączenia sieciowego.\n\nKliknij OK i poczekaj na komunikat końcowy.")
        try:
            ensure_models_exist()
            key_path = r"*\shell\Anonimizuj"
            key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, key_path)
            winreg.SetValue(key, "", winreg.REG_SZ, "🔒 Anonimizuj dokument")
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, f'"{EXE_PATH}"')
            winreg.CloseKey(key)

            cmd_key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, key_path + r"\command")
            winreg.SetValue(cmd_key, "", winreg.REG_SZ, f'"{EXE_PATH}" "%1"')
            winreg.CloseKey(cmd_key)
            messagebox.showinfo(TRANSLATIONS["pl"]["msg_finish_title"], "Instalacja zakończona!\nModele zostały pobrane, a menu kontekstowe zaktualizowane.")
        except Exception as e:
            messagebox.showerror("Błąd Instalacji", f"Wystąpił błąd:\n{e}")
        sys.exit(0)

    elif len(sys.argv) > 1:
        input_file = sys.argv[1]
        if not os.path.exists(input_file):
            sys.exit(1)

        p = Path(input_file)
        out_path = str(p.parent / f"{p.stem}_anonymized{p.suffix}")
        reg_path = str(p.parent / f"{p.stem}_tokens.json")

        enabled_cats = {
            "names", "addresses", "companies", "pesel", "nip", "regon", 
            "iban", "card", "cvv", "phone", "email", "ip", "postal_code", 
            "passport", "pwz", "logos"
        }

        registry = TokenRegistry()
        root = tk.Tk()
        root.withdraw()

        logo_template_cv = None
        if input_file.lower().endswith(".pdf"):
            if messagebox.askyesno("Wykrywanie Logo", TRANSLATIONS["pl"]["msg_logo_ask"]):
                selector = LogoSelector(root, input_file)
                root.wait_window(selector)
                if selector.template_image is not None:
                    logo_template_cv = selector.template_image

        try:
            lazy_load_models()
            if input_file.lower().endswith(".pdf"):
                anonymize_pdf(input_file, out_path, enabled_cats, registry, log_cb=None, logo_template=logo_template_cv)
            elif input_file.lower().endswith(".docx"):
                anonymize_docx(input_file, out_path, enabled_cats, registry)
            else:
                anonymize_text_file(input_file, out_path, enabled_cats, registry)

            with open(reg_path, "w", encoding="utf-8") as f:
                json.dump(registry.to_dict(), f, ensure_ascii=False, indent=2)

            messagebox.showinfo(TRANSLATIONS["pl"]["msg_finish_title"], f"Anonimizacja zakończona!\n\nPlik: {Path(out_path).name}")
        except Exception as e:
            messagebox.showerror("❌ Błąd", f"Wystąpił błąd podczas anonimizacji:\n{str(e)}")
        sys.exit(0)

    else:
        app = AnonymizerApp()
        app.mainloop()