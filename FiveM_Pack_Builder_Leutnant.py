# FiveM_Pack_Builder_Leutnant.py
import os
import re
import shutil
import threading
from pathlib import Path
from datetime import datetime
import subprocess
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Optional Drag & Drop (pip install tkinterdnd2)
DND_AVAILABLE = False
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except Exception:
    DND_AVAILABLE = False

# Optional preview images (pip install pillow)
PIL_AVAILABLE = False
try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

# EXTENSIONS
STREAM_EXTS = {".ydd", ".ytd", ".yft", ".ydr", ".ybn", ".ytyp", ".ymap"}
DATA_EXTS   = {".meta", ".ymt"}
PREVIEW_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

APP_TITLE = "FiveM Pack Builder"
APP_VERSION = "v2.3"
CREATED_BY = "Created by Leutnant"

# THEME
ACCENT = "#7C3AED"
BG0 = "#0B1020"
BG1 = "#101A34"
FG0 = "#E6EAF2"
FG1 = "#AEB8D6"
RED = "#EF4444"
RED_HOVER = "#DC2626"
ACCENT_HOVER = "#6D28D9"
CARD = "#0E1730"
BORDER = "#1B2A55"

def safe_mkdir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def wipe_dir(p: Path):
    if p.exists():
        shutil.rmtree(p)

def ts():
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def read_text_loose(path: Path, max_bytes: int = 800_000) -> str:
    try:
        data = path.read_bytes()[:max_bytes]
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return ""

def detect_data_file_type(meta_path: Path) -> str | None:
    txt = read_text_loose(meta_path).lower()
    if not txt:
        return None
    if ("shoppedapparel" in txt) or ("shop_ped_apparel" in txt) or ("shop ped apparel" in txt):
        return "SHOP_PED_APPAREL_META_FILE"
    if ("pedcomponents" in txt) or ("ped_component" in txt) or ("componentinfo" in txt):
        return "PED_COMPONENTS_FILE"
    if ("pedoverlays" in txt) or ("ped_overlays" in txt) or ("tattoo" in txt):
        return "PED_OVERLAY_FILE"
    if ("dlcname" in txt and "content" in txt) or ("contentunlocks" in txt):
        return "CONTENT_UNLOCKING_META_FILE"
    return None

def collect_relevant_files(src: Path):
    found = []
    for root, _, files in os.walk(src):
        for f in files:
            p = Path(root) / f
            ext = p.suffix.lower()
            if ext in STREAM_EXTS or ext in DATA_EXTS:
                found.append(p)
    return found

def normalize_dnd_paths(dnd_string: str):
    s = dnd_string.strip()
    parts = []
    buf = ""
    in_brace = False
    for ch in s:
        if ch == "{":
            in_brace = True
            buf = ""
        elif ch == "}":
            in_brace = False
            parts.append(buf)
            buf = ""
        elif ch == " " and not in_brace:
            if buf:
                parts.append(buf)
                buf = ""
        else:
            buf += ch
    if buf:
        parts.append(buf)

    out = []
    for p in parts:
        p = p.strip().strip('"')
        if p:
            out.append(p)
    return out

def parse_fxmanifest_existing(text: str):
    files_set = set()
    datafile_set = set()

    for m in re.finditer(r"['\"]([^'\"]+)['\"]", text):
        path = m.group(1).strip()
        if path:
            files_set.add(path.replace("\\", "/"))

    for m in re.finditer(r"data_file\s+['\"]([^'\"]+)['\"]\s+['\"]([^'\"]+)['\"]", text):
        t = m.group(1).strip()
        p = m.group(2).strip().replace("\\", "/")
        if t and p:
            datafile_set.add((t, p))

    return files_set, datafile_set

def build_fxmanifest_block(resource_name: str, files_paths: list[str], data_files: list[tuple[str, str]], unknown: list[str]):
    lines = []
    lines.append("")
    lines.append(f"-- === Auto-added by {APP_TITLE} {APP_VERSION} at {datetime.now().isoformat(timespec='seconds')} ===")
    lines.append(f"-- Resource: {resource_name}")
    lines.append("")

    if files_paths:
        lines.append("files {")
        for p in sorted(set(files_paths)):
            lines.append(f"  '{p}',")
        lines.append("}")
        lines.append("")

    if data_files:
        lines.append("-- Detected meta mapping (best effort):")
        for t, p in sorted(set(data_files)):
            lines.append(f"data_file '{t}' '{p}'")
        lines.append("")

    if unknown:
        lines.append("-- Unclassified data files (loaded via files{}, may still need manual data_file mapping for some packs):")
        for p in sorted(set(unknown)):
            lines.append(f"--   {p}")
        lines.append("")

    lines.append(f"-- Add to server.cfg: ensure {resource_name}")
    lines.append("-- === End auto-added block ===")
    lines.append("")
    return "\n".join(lines)

def write_or_extend_fxmanifest(dst_root: Path, resource_name: str, data_rel_paths: list[str], log_fn):
    fx = dst_root / "fxmanifest.lua"

    detected = []
    unknown = []

    for rp in data_rel_paths:
        ext = Path(rp).suffix.lower()
        abs_path = (dst_root / rp.replace("/", os.sep))
        if ext == ".meta" and abs_path.exists():
            t = detect_data_file_type(abs_path)
            if t:
                detected.append((t, rp))
            else:
                unknown.append(rp)
        else:
            unknown.append(rp)

    new_files = list(data_rel_paths)

    if fx.exists():
        old_text = fx.read_text(encoding="utf-8", errors="ignore")
        old_files, old_datafiles = parse_fxmanifest_existing(old_text)

        truly_new_files = sorted(set(new_files) - set(old_files))
        truly_new_datafiles = sorted(set(detected) - set(old_datafiles))
        truly_new_unknown = sorted(set(unknown) - set(old_files))

        if not truly_new_files and not truly_new_datafiles and not truly_new_unknown:
            log_fn("ℹ️ fxmanifest.lua: nichts Neues hinzuzufügen (alles schon vorhanden).")
            return

        block = build_fxmanifest_block(resource_name, truly_new_files, truly_new_datafiles, truly_new_unknown)
        fx.write_text(old_text.rstrip() + "\n" + block, encoding="utf-8")
        log_fn("✅ fxmanifest.lua erweitert (append).")
    else:
        base = []
        base.append("fx_version 'cerulean'")
        base.append("game 'gta5'")
        base.append("")
        base.append(f"-- Auto-generated by {APP_TITLE} {APP_VERSION}")
        base.append(f"-- Resource: {resource_name}")
        base.append(f"-- Generated: {datetime.now().isoformat(timespec='seconds')}")
        base.append("")
        base_text = "\n".join(base)

        block = build_fxmanifest_block(resource_name, new_files, detected, unknown)
        fx.write_text(base_text + block, encoding="utf-8")
        log_fn("✅ fxmanifest.lua erstellt (neu).")

def settings_path():
    return Path.home() / "fivem_pack_builder_settings.json"

def load_settings():
    p = settings_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return {}
    return {}

def save_settings(data: dict):
    p = settings_path()
    try:
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass

class BaseTk(tk.Tk):
    pass

class App:
    def __init__(self):
        self.root = TkinterDnD.Tk() if DND_AVAILABLE else BaseTk()
        self.root.title(f"{APP_TITLE} {APP_VERSION}")
        self.root.geometry("1040x720")
        self.root.minsize(1040, 720)
        self.root.configure(bg=BG0)

        self.sources: list[Path] = []
        self.stop_flag = False
        self.worker = None

        self.settings = load_settings()
        self._preview_photo = None
        self._last_dst_root: Path | None = None
        self._last_selected_source: Path | None = None

        self._build_style()
        self._build_ui()

    def _build_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("TFrame", background=BG0)
        style.configure("TLabel", background=BG0, foreground=FG0)
        style.configure("Sub.TLabel", background=BG0, foreground=FG1)
        style.configure("Title.TLabel", background=BG0, foreground=FG0, font=("Segoe UI", 18, "bold"))
        style.configure("By.TLabel", background=BG0, foreground=FG1, font=("Segoe UI", 10, "bold"))

        style.configure("TLabelframe", background=BG1, foreground=FG0)
        style.configure("TLabelframe.Label", background=BG1, foreground=FG0, font=("Segoe UI", 10, "bold"))

        style.configure("TEntry", fieldbackground=CARD, foreground=FG0)
        style.configure("TCombobox", fieldbackground=CARD, foreground=FG0)
        style.configure("TCheckbutton", background=BG1, foreground=FG0)

        style.configure("Horizontal.TProgressbar", troughcolor=CARD, background=ACCENT)

    def _build_ui(self):
        header = ttk.Frame(self.root, padding=14)
        header.pack(fill="x")

        left = ttk.Frame(header)
        left.pack(side="left", fill="x", expand=True)
        ttk.Label(left, text="FiveM Pack Builder", style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text="Darkmode • Drag&Drop • Output immer stream/ + data/ • fxmanifest erweitern • Ensure-Listen",
                  style="Sub.TLabel").pack(anchor="w")
        ttk.Label(header, text=CREATED_BY, style="By.TLabel").pack(side="right", anchor="ne")

        body = ttk.Frame(self.root, padding=(14, 10))
        body.pack(fill="both", expand=True)

        self.left_col = ttk.Frame(body)
        self.left_col.pack(side="left", fill="y", padx=(0, 12))

        self.right_col = ttk.Frame(body)
        self.right_col.pack(side="right", fill="both", expand=True)

        # SOURCES
        src_card = ttk.Labelframe(self.left_col, text="1) Packs reinziehen oder auswählen", padding=10)
        src_card.pack(fill="x")

        self.drop = tk.Text(src_card, height=3, wrap="word", bg=CARD, fg=FG1, insertbackground=FG0, bd=0,
                            highlightthickness=1, highlightbackground=BORDER)
        self.drop.configure(state="normal")
        self.drop.delete("1.0", "end")
        self.drop.insert("1.0", "➡ Zieh hier Ordner rein (Drag & Drop)\noder nutze 'Ordner hinzufügen'.")
        self.drop.configure(cursor="arrow")
        self.drop.bind("<Key>", lambda e: "break")  # not editable, still droppable
        self.drop.pack(fill="x", pady=(0, 8))

        if DND_AVAILABLE:
            self.drop.drop_target_register(DND_FILES)
            self.drop.dnd_bind("<<Drop>>", self._on_drop)

        self.src_list = tk.Listbox(src_card, height=12, width=52, bg=CARD, fg=FG0, bd=0,
                                   highlightthickness=1, highlightbackground=BORDER, selectbackground=ACCENT)
        self.src_list.pack(fill="x")
        self.src_list.bind("<<ListboxSelect>>", self.on_source_select)

        btn_row = ttk.Frame(src_card)
        btn_row.pack(fill="x", pady=(10, 0))
        ttk.Button(btn_row, text="➕ Ordner hinzufügen", command=self.add_source).pack(side="left", expand=True, fill="x", padx=(0, 6))
        ttk.Button(btn_row, text="🗑 Entfernen", command=self.remove_selected).pack(side="left", expand=True, fill="x", padx=(6, 0))

        # DESTINATION
        dst_card = ttk.Labelframe(self.left_col, text="2) Ziel-Resource & Optionen", padding=10)
        dst_card.pack(fill="x", pady=(12, 0))

        self.dst_var = tk.StringVar(value=self.settings.get("last_dst", ""))
        dst_row = ttk.Frame(dst_card)
        dst_row.pack(fill="x")
        ttk.Entry(dst_row, textvariable=self.dst_var).pack(side="left", fill="x", expand=True)
        ttk.Button(dst_row, text="📁", width=4, command=self.pick_destination).pack(side="left", padx=(6, 0))

        name_row = ttk.Frame(dst_card)
        name_row.pack(fill="x", pady=(10, 0))
        ttk.Label(name_row, text="Resource-Name (ensure):").pack(side="left")
        self.name_var = tk.StringVar(value=self.settings.get("last_name", "my_pack"))
        ttk.Entry(name_row, textvariable=self.name_var).pack(side="left", fill="x", expand=True, padx=(8, 0))

        mode_row = ttk.Frame(dst_card)
        mode_row.pack(fill="x", pady=(10, 0))
        ttk.Label(mode_row, text="Modus:").pack(side="left")
        self.mode_var = tk.StringVar(value="merge")
        ttk.Combobox(mode_row, textvariable=self.mode_var, values=["merge", "replace"], state="readonly", width=10)\
            .pack(side="left", padx=(8, 0))
        ttk.Label(mode_row, text="merge = hinzufügen / replace = stream+data löschen", style="Sub.TLabel").pack(side="left", padx=(10, 0))

        self.move_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(dst_card, text="MOVE statt COPY (Quellfiles werden verschoben)", variable=self.move_var).pack(anchor="w", pady=(10, 0))

        openiv_row = ttk.Frame(dst_card)
        openiv_row.pack(fill="x", pady=(10, 0))
        ttk.Label(openiv_row, text="OpenIV.exe:").pack(side="left")
        self.openiv_var = tk.StringVar(value=self.settings.get("openiv_path", ""))
        ttk.Entry(openiv_row, textvariable=self.openiv_var).pack(side="left", fill="x", expand=True, padx=(8, 0))
        ttk.Button(openiv_row, text="📌", width=4, command=self.pick_openiv).pack(side="left", padx=(6, 0))

        # BIG START/STOP BUTTONS (tk.Button => always colored, big)
        act_row = ttk.Frame(self.left_col)
        act_row.pack(fill="x", pady=(12, 0))

        self.start_btn = tk.Button(
            act_row, text="🚀 START",
            font=("Segoe UI", 14, "bold"),
            bg=ACCENT, fg=FG0, activebackground=ACCENT_HOVER, activeforeground=FG0,
            bd=0, padx=18, pady=12, cursor="hand2",
            command=self.start
        )
        self.start_btn.pack(side="left", expand=True, fill="x", padx=(0, 6))

        self.stop_btn = tk.Button(
            act_row, text="⛔ STOP",
            font=("Segoe UI", 14, "bold"),
            bg=RED, fg=FG0, activebackground=RED_HOVER, activeforeground=FG0,
            bd=0, padx=18, pady=12, cursor="hand2",
            command=self.stop,
            state="disabled"
        )
        self.stop_btn.pack(side="left", expand=True, fill="x", padx=(6, 0))

        # STATUS
        status_card = ttk.Labelframe(self.right_col, text="Status", padding=10)
        status_card.pack(fill="x")

        self.status_var = tk.StringVar(value="Bereit.")
        ttk.Label(status_card, textvariable=self.status_var, font=("Segoe UI", 12, "bold")).pack(anchor="w")

        self.progress = ttk.Progressbar(status_card, mode="determinate", style="Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(10, 4))
        self.count_var = tk.StringVar(value="0 / 0")
        ttk.Label(status_card, textvariable=self.count_var, style="Sub.TLabel").pack(anchor="w")

        # LOG
        log_card = ttk.Labelframe(self.right_col, text="Live Log / Warnungen", padding=10)
        log_card.pack(fill="both", expand=True, pady=(12, 0))

        self.log = tk.Text(log_card, wrap="word", bg=CARD, fg=FG0, insertbackground=FG0, bd=0,
                           highlightthickness=1, highlightbackground=BORDER)
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")

        # PREVIEW
        preview_card = ttk.Labelframe(self.right_col, text="Preview", padding=10)
        preview_card.pack(fill="x", pady=(12, 0))

        btns = ttk.Frame(preview_card)
        btns.pack(fill="x")
        ttk.Button(btns, text="📂 Explorer öffnen", command=self.open_selected_in_explorer).pack(side="left", expand=True, fill="x", padx=(0, 6))
        ttk.Button(btns, text="🟣 OpenIV öffnen", command=self.open_selected_in_openiv).pack(side="left", expand=True, fill="x", padx=(6, 0))

        self.preview_lbl = ttk.Label(preview_card, text="Wähle links einen Source-Ordner – Preview-Bild wird angezeigt, falls vorhanden.", style="Sub.TLabel")
        self.preview_lbl.pack(anchor="w", pady=(8, 0))

        self.preview_img_label = tk.Label(preview_card, bg=BG1, fg=FG1)
        self.preview_img_label.pack(fill="x", pady=(8, 0))

        footer = ttk.Frame(self.root, padding=(14, 10))
        footer.pack(fill="x")
        ttk.Label(
            footer,
            text="Output: stream/ + data/ + fxmanifest.lua (append). Ensure-Files: _ADD_TO_SERVER_CFG.txt + _ALL_ENSURES.txt. Log: builder.log",
            style="Sub.TLabel"
        ).pack(anchor="w")

        if not DND_AVAILABLE:
            self._log_line("ℹ️ Drag & Drop optional: py -m pip install tkinterdnd2")
        if not PIL_AVAILABLE:
            self._log_line("ℹ️ Preview besser mit Pillow: py -m pip install pillow (für JPG/WEBP & Scaling)")

    # ---------- UI helpers ----------
    def _log_line(self, s: str):
        self.log.configure(state="normal")
        self.log.insert("end", s + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_status(self, s: str):
        self.status_var.set(s)

    def _set_progress(self, done: int, total: int):
        self.progress["maximum"] = max(total, 1)
        self.progress["value"] = done
        self.count_var.set(f"{done} / {total}")

    # ---------- Sources ----------
    def _add_source_path(self, folder: str):
        p = Path(folder).expanduser()
        if not p.exists():
            self._log_line(f"⚠️ Nicht gefunden: {p}")
            return
        if p.is_file():
            p = p.parent
        p = p.resolve()
        if p not in self.sources:
            self.sources.append(p)
            self.src_list.insert("end", str(p))
            self._log_line(f"➕ Source: {p}")
        else:
            self._log_line(f"ℹ️ Schon drin: {p}")

    def _on_drop(self, event):
        paths = normalize_dnd_paths(event.data)
        for raw in paths:
            self._add_source_path(raw)
        self._log_line(f"✅ Drag&Drop: {len(paths)} Einträge verarbeitet.")

    def add_source(self):
        folder = filedialog.askdirectory(title="Source-Ordner auswählen")
        if folder:
            self._add_source_path(folder)

    def remove_selected(self):
        sel = list(self.src_list.curselection())
        if not sel:
            return
        for idx in reversed(sel):
            p = self.sources[idx]
            del self.sources[idx]
            self.src_list.delete(idx)
            self._log_line(f"🗑 Entfernt: {p}")

    def pick_destination(self):
        folder = filedialog.askdirectory(title="Ziel-Resource-Ordner auswählen (oder neu anlegen)")
        if folder:
            self.dst_var.set(folder)
            self.settings["last_dst"] = folder
            save_settings(self.settings)
            self._log_line(f"📁 Ziel: {folder}")

    # ---------- OpenIV ----------
    def pick_openiv(self):
        file = filedialog.askopenfilename(
            title="OpenIV.exe auswählen",
            filetypes=[("OpenIV", "OpenIV.exe"), ("Exe", "*.exe"), ("All", "*.*")]
        )
        if not file:
            return
        self.openiv_var.set(file)
        self.settings["openiv_path"] = file
        save_settings(self.settings)
        self._log_line(f"✅ OpenIV gesetzt: {file}")

    def _get_openiv_path(self) -> Path | None:
        val = self.openiv_var.get().strip()
        if not val:
            return None
        p = Path(val)
        if p.exists() and p.suffix.lower() == ".exe":
            return p
        return None

    # ---------- Preview ----------
    def on_source_select(self, event=None):
        sel = self.src_list.curselection()
        if not sel:
            return
        src = Path(self.sources[sel[0]])
        self._last_selected_source = src
        self.show_preview_for_folder(src)

    def show_preview_for_folder(self, folder: Path):
        preferred = {
            "preview.png", "preview.jpg", "preview.jpeg", "preview.webp",
            "thumb.png", "thumb.jpg", "thumb.jpeg", "thumb.webp",
            "thumbnail.png", "thumbnail.jpg", "thumbnail.jpeg", "thumbnail.webp",
            "showcase.png", "showcase.jpg"
        }
        candidates = []
        try:
            for p in folder.iterdir():
                if p.is_file() and p.suffix.lower() in PREVIEW_EXTS:
                    candidates.append(p)
            for d in folder.iterdir():
                if d.is_dir():
                    for p in d.iterdir():
                        if p.is_file() and p.suffix.lower() in PREVIEW_EXTS:
                            candidates.append(p)
        except Exception:
            candidates = []

        if not candidates:
            self.preview_lbl.configure(text="Kein Preview-Bild gefunden (optional: preview.png/thumbnail.jpg ins Pack legen).")
            self.preview_img_label.configure(image="", text="")
            self._preview_photo = None
            return

        best = None
        for p in candidates:
            if p.name.lower() in preferred:
                best = p
                break
        if not best:
            best = candidates[0]

        self.preview_lbl.configure(text=f"Preview: {best.name}")

        try:
            if PIL_AVAILABLE:
                img = Image.open(best)
                max_w = 520
                w, h = img.size
                if w > max_w:
                    new_h = int(h * (max_w / float(w)))
                    img = img.resize((max_w, max(1, new_h)))
                self._preview_photo = ImageTk.PhotoImage(img)
                self.preview_img_label.configure(image=self._preview_photo, text="")
            else:
                if best.suffix.lower() != ".png":
                    self.preview_img_label.configure(image="", text="(Für JPG/WEBP Preview: py -m pip install pillow)")
                    self._preview_photo = None
                    return
                self._preview_photo = tk.PhotoImage(file=str(best))
                self.preview_img_label.configure(image=self._preview_photo, text="")
        except Exception as e:
            self.preview_img_label.configure(image="", text=f"Preview Fehler: {e}")
            self._preview_photo = None

    # ---------- Open buttons ----------
    def open_selected_in_explorer(self):
        try:
            if self._last_dst_root and self._last_dst_root.exists():
                subprocess.run(["explorer", str(self._last_dst_root)], check=False)
                return
            if self._last_selected_source and self._last_selected_source.exists():
                subprocess.run(["explorer", str(self._last_selected_source)], check=False)
                return
            messagebox.showinfo("Info", "Kein Ordner verfügbar. Wähle links einen Source oder starte einmal den Build.")
        except Exception as e:
            messagebox.showerror("Fehler", str(e))

    def open_selected_in_openiv(self):
        openiv = self._get_openiv_path()
        if not openiv:
            messagebox.showerror("OpenIV", "OpenIV.exe ist nicht gesetzt oder nicht gefunden.\nBitte unter 'OpenIV.exe' setzen (📌).")
            return

        target_folder = None
        if self._last_dst_root and self._last_dst_root.exists():
            target_folder = self._last_dst_root
        elif self._last_selected_source and self._last_selected_source.exists():
            target_folder = self._last_selected_source

        try:
            subprocess.Popen([str(openiv)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._log_line("🟣 OpenIV gestartet.")
            if target_folder:
                subprocess.run(["explorer", str(target_folder)], check=False)
                self._log_line(f"📂 Ordner geöffnet (Explorer): {target_folder}")
        except Exception as e:
            messagebox.showerror("OpenIV Fehler", str(e))

    # ---------- Ensure files ----------
    def _write_ensure_files(self, dst_root: Path, resource_name: str):
        ensure_line = f"ensure {resource_name}"
        (dst_root / "_ADD_TO_SERVER_CFG.txt").write_text(ensure_line + "\n", encoding="utf-8")
        self._log_line("📝 Datei erstellt: _ADD_TO_SERVER_CFG.txt")

        master_targets = [
            dst_root.parent / "_ALL_ENSURES.txt",  # central
            dst_root / "_ALL_ENSURES.txt"          # fallback
        ]

        for master_file in master_targets:
            try:
                existing = set()
                if master_file.exists():
                    txt = master_file.read_text(encoding="utf-8", errors="ignore")
                    for line in txt.splitlines():
                        line = line.strip()
                        if line and not line.startswith("#"):
                            existing.add(line.lower())

                if ensure_line.lower() not in existing:
                    safe_mkdir(master_file.parent)
                    new_file = not master_file.exists()
                    with master_file.open("a", encoding="utf-8") as f:
                        if new_file or master_file.stat().st_size == 0:
                            f.write(f"# Generated by {APP_TITLE} ({CREATED_BY})\n")
                        f.write(ensure_line + "\n")
                    self._log_line(f"📚 Master updated: {master_file}")
                else:
                    self._log_line(f"ℹ️ Master enthält ensure schon: {master_file}")

                if master_file == master_targets[0]:
                    break
            except Exception:
                continue

    # ---------- Run ----------
    def validate(self):
        if not self.sources:
            messagebox.showerror("Fehler", "Bitte mindestens einen Source-Ordner hinzufügen (oder reinziehen).")
            return False
        dst = self.dst_var.get().strip()
        if not dst:
            messagebox.showerror("Fehler", "Bitte Ziel-Ordner auswählen (Resource-Ordner).")
            return False
        name = self.name_var.get().strip()
        if not name or " " in name:
            messagebox.showerror("Fehler", "Bitte Resource-Name ohne Leerzeichen (z. B. my_pack).")
            return False
        return True

    def start(self):
        if not self.validate():
            return
        if self.mode_var.get() == "replace":
            if not messagebox.askyesno("Bestätigung", "Modus 'replace' löscht stream/ und data/ im Ziel. Fortfahren?"):
                return

        self.settings["last_dst"] = self.dst_var.get().strip()
        self.settings["last_name"] = self.name_var.get().strip()
        self.settings["openiv_path"] = self.openiv_var.get().strip()
        save_settings(self.settings)

        self.stop_flag = False
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._set_progress(0, 1)
        self._set_status("Starte…")

        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def stop(self):
        self.stop_flag = True
        self._log_line("⛔ Stop angefordert… beendet nach der aktuellen Datei.")

    def _run(self):
        try:
            dst_root = Path(self.dst_var.get().strip()).resolve()
            resource_name = self.name_var.get().strip()
            mode = self.mode_var.get()
            move = self.move_var.get()

            safe_mkdir(dst_root)
            self._last_dst_root = dst_root

            dst_stream = dst_root / "stream"
            dst_data = dst_root / "data"
            log_path = dst_root / "builder.log"

            duplicates = 0
            errors = 0

            def file_log(msg: str):
                try:
                    with log_path.open("a", encoding="utf-8") as fp:
                        fp.write(msg + "\n")
                except Exception:
                    pass

            # Replace mode
            if mode == "replace":
                self.root.after(0, lambda: self._set_status("Bereinige Ziel (replace)…"))
                self.root.after(0, lambda: self._log_line("🧹 Lösche stream/ und data/…"))
                if dst_stream.exists():
                    wipe_dir(dst_stream)
                if dst_data.exists():
                    wipe_dir(dst_data)

            safe_mkdir(dst_stream)
            safe_mkdir(dst_data)

            # Collect jobs
            jobs = []
            for src in self.sources:
                src = src.resolve()
                files = collect_relevant_files(src)
                self.root.after(0, lambda s=src, n=len(files): self._log_line(f"🔎 {s} → {n} relevante Dateien"))
                for f in files:
                    jobs.append((src, f))

            total = len(jobs)
            if total == 0:
                self.root.after(0, lambda: messagebox.showinfo("Info", "Keine relevanten Dateien gefunden (.ydd/.ytd/.meta/.ymt/etc)."))
                self.root.after(0, self._finish_buttons)
                return

            file_log(f"=== Build start {datetime.now().isoformat(timespec='seconds')} ===")
            file_log(f"Resource: {resource_name}")
            file_log(f"Destination: {dst_root}")
            file_log(f"Mode: {mode} | Move: {move}")
            file_log("Sources:")
            for s in self.sources:
                file_log(f" - {s}")
            file_log("")

            # IMPORTANT CHANGE:
            # Always FLATTEN into stream/ and data/ (so your output is always correct for FiveM)
            data_rel_paths = []
            used_names_stream = set()
            used_names_data = set()

            done = 0
            self.root.after(0, lambda: self._set_status("Kopiere Dateien…"))
            self.root.after(0, lambda: self._set_progress(0, total))

            for src_base, f in jobs:
                if self.stop_flag:
                    file_log("ABORTED by user.")
                    self.root.after(0, lambda: messagebox.showinfo("Abgebrochen", "Vorgang wurde abgebrochen.\nDetails stehen im Log."))
                    self.root.after(0, self._finish_buttons)
                    return

                ext = f.suffix.lower()

                # Flatten target path:
                if ext in STREAM_EXTS:
                    target = dst_stream / f.name
                    name_key = f.name.lower()
                    used_set = used_names_stream
                else:
                    target = dst_data / f.name
                    name_key = f.name.lower()
                    used_set = used_names_data

                # duplicate filename handling: prefix by source folder name
                if name_key in used_set or target.exists():
                    duplicates += 1
                    prefix = src_base.name.replace(" ", "_")
                    target = target.with_name(f"{prefix}_{target.name}")
                    name_key = target.name.lower()

                # still colliding? add timestamp
                if name_key in used_set or target.exists():
                    duplicates += 1
                    target = target.with_name(f"{target.stem}_{ts()}{target.suffix}")
                    name_key = target.name.lower()

                used_set.add(name_key)

                try:
                    action = "MOVE" if move else "COPY"
                    msg = f"[{action}] {f.name}  (from: {src_base.name}) -> {target.relative_to(dst_root)}"
                    self.root.after(0, lambda m=msg: self._log_line(m))
                    file_log(msg)

                    if move:
                        shutil.move(str(f), str(target))
                    else:
                        shutil.copy2(str(f), str(target))

                    if ext in DATA_EXTS:
                        data_rel_paths.append(target.relative_to(dst_root).as_posix())

                except Exception as e:
                    errors += 1
                    msg = f"❌ Fehler bei {f}: {e}"
                    self.root.after(0, lambda m=msg: self._log_line(m))
                    file_log(msg)

                done += 1
                self.root.after(0, lambda d=done: self._set_progress(d, total))

            # fxmanifest extend/create
            self.root.after(0, lambda: self._set_status("Erweitere fxmanifest.lua…"))
            self.root.after(0, lambda: self._log_line("🧾 fxmanifest.lua wird erweitert/erstellt…"))
            write_or_extend_fxmanifest(dst_root, resource_name, data_rel_paths, self._log_line)

            # ensure helper files
            try:
                self._write_ensure_files(dst_root, resource_name)
                file_log("ensure files written.")
            except Exception as e:
                msg = f"⚠️ Ensure-Dateien konnten nicht erstellt werden: {e}"
                self.root.after(0, lambda m=msg: self._log_line(m))
                file_log(msg)

            file_log("")
            file_log(f"Summary: total={total}, duplicates={duplicates}, errors={errors}")
            file_log(f"=== Build done {datetime.now().isoformat(timespec='seconds')} ===")

            self.root.after(0, lambda: self._set_status("Fertig ✅"))
            self.root.after(0, lambda: messagebox.showinfo(
                "Fertig ✅",
                f"Alles erledigt!\n\nserver.cfg: ensure {resource_name}\n"
                f"_ADD_TO_SERVER_CFG.txt + _ALL_ENSURES.txt erstellt.\n\n"
                f"Duplikate: {duplicates}\nFehler: {errors}\n\nLog: builder.log"
            ))
            self.root.after(0, self._finish_buttons)

        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Fehler ❌", str(e)))
            self.root.after(0, self._finish_buttons)

    def _finish_buttons(self):
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    App().run()
