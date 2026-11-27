#!/usr/bin/env python3
"""KadaOS File Actions — Tangerine-style convert/resize/compress and more, from the Files right-click menu.

  fileactions.py FILE [FILE ...]      show applicable actions (themed rofi), run the chosen one

Design rules:
- Only actions that apply to the whole selection are offered.
- Originals are never modified; output goes beside the source with a collision-safe name.
- Each file reports success/failure; a desktop notification shows progress and reveals the result.
Engines (all already installed): Pillow, ffmpeg, LibreOffice, Ghostscript, Poppler, zip/7z/tar.
"""
import os, subprocess, sys
from pathlib import Path

# ───────────────────────── kinds & naming (pure, tested) ─────────────────────────
KINDS = {
    "image": {"png", "jpg", "jpeg", "webp", "avif", "gif", "bmp", "tiff", "tif", "heic"},
    "video": {"mp4", "mkv", "webm", "mov", "avi", "m4v", "flv", "wmv"},
    "audio": {"mp3", "wav", "flac", "ogg", "m4a", "aac", "opus"},
    "document": {"doc", "docx", "odt", "rtf", "ppt", "pptx", "odp", "xls", "xlsx", "ods", "csv"},
    "pdf": {"pdf"},
    "archive": {"zip", "7z", "tar", "gz", "tgz", "rar", "bz2", "xz"},
}

def kind_of(path):
    ext = Path(path).suffix.lower().lstrip(".")
    for k, exts in KINDS.items():
        if ext in exts: return k
    return "other"

def output_path(src, new_ext=None, suffix="", outdir=None):
    """Beside the source (or outdir), new extension/suffix, never overwriting an existing file."""
    src = Path(src); d = Path(outdir) if outdir else src.parent
    ext = ("." + new_ext.lstrip(".")) if new_ext else src.suffix
    stem = src.stem + (suffix or "")
    cand = d / f"{stem}{ext}"; n = 2
    while cand.exists() or cand == src:
        cand = d / f"{stem} ({n}){ext}"; n += 1
    return cand

# ───────────────────────── action catalogue ─────────────────────────
# Each: id -> (label, kinds it applies to, options list|None, min_count, max_count)
# options: list of (choice_label, value); the runner receives the chosen value.
def catalogue():
    return {
        "img_convert":  ("Convert image to…", {"image"}, [("PNG", "png"), ("JPEG", "jpg"), ("WebP", "webp"), ("AVIF", "avif"), ("TIFF", "tiff")], 1, 99),
        "img_resize":   ("Resize image…", {"image"}, [("Max 3840px", "3840"), ("Max 1920px", "1920"), ("Max 1280px", "1280"), ("Max 800px", "800"), ("Half size", "50%")], 1, 99),
        "img_compress": ("Compress image (smaller file)", {"image"}, None, 1, 99),
        "img_pdf":      ("Combine images into a PDF", {"image"}, None, 1, 99),
        "vid_convert":  ("Convert video to…", {"video"}, [("MP4 (H.264)", "mp4"), ("WebM (VP9)", "webm"), ("MKV", "mkv")], 1, 99),
        "vid_compress": ("Compress video", {"video"}, [("1080p", "1080"), ("720p", "720"), ("480p", "480")], 1, 99),
        "vid_audio":    ("Extract audio (MP3)", {"video"}, None, 1, 99),
        "vid_gif":      ("Make a GIF", {"video"}, None, 1, 99),
        "aud_convert":  ("Convert audio to…", {"audio"}, [("MP3", "mp3"), ("WAV", "wav"), ("FLAC", "flac"), ("OGG", "ogg")], 1, 99),
        "doc_pdf":      ("Convert to PDF", {"document"}, None, 1, 99),
        "doc_docx":     ("Convert to Word (.docx)", {"document"}, None, 1, 99),
        "pdf_compress": ("Compress PDF", {"pdf"}, None, 1, 99),
        "pdf_images":   ("PDF to images (PNG)", {"pdf"}, None, 1, 99),
        "pdf_merge":    ("Merge PDFs into one", {"pdf"}, None, 2, 99),
        "arc_extract":  ("Extract here", {"archive"}, None, 1, 99),
        "make_zip":     ("Compress to ZIP", {"image", "video", "audio", "document", "pdf", "other"}, None, 1, 99),
        "copy_path":    ("Copy path", {"image", "video", "audio", "document", "pdf", "archive", "other"}, None, 1, 99),
    }

def actions_for(paths):
    """Ordered list of (id, label) applicable to the whole selection."""
    kinds = {kind_of(p) for p in paths}; n = len(paths)
    out = []
    for aid, (label, applies, _opts, lo, hi) in catalogue().items():
        if kinds <= applies and lo <= n <= hi:
            out.append((aid, label))
    return out

# ───────────────────────── runners ─────────────────────────
def _run(cmd, timeout=1800):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0: raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip() else f"exit {r.returncode}")

def _pillow_save(src, dst, max_px=None, quality=None):
    from PIL import Image, ImageOps
    im = Image.open(src); im = ImageOps.exif_transpose(im)
    if max_px:
        if isinstance(max_px, str) and max_px.endswith("%"):
            f = int(max_px[:-1]) / 100; im = im.resize((max(1, int(im.width * f)), max(1, int(im.height * f))))
        else:
            im.thumbnail((int(max_px), int(max_px)))
    ext = dst.suffix.lower()
    if ext in (".jpg", ".jpeg") and im.mode in ("RGBA", "P", "LA"):
        bg = Image.new("RGB", im.size, (255, 255, 255)); bg.paste(im, mask=im.convert("RGBA").split()[-1] if im.mode != "P" else None); im = bg
    kw = {}
    if ext in (".jpg", ".jpeg"): kw = {"quality": quality or 88, "optimize": True, "progressive": True}
    elif ext == ".webp": kw = {"quality": quality or 82, "method": 6}
    elif ext == ".avif": kw = {"quality": quality or 60}
    elif ext == ".png": kw = {"optimize": True}
    im.save(dst, **kw)

def run_action(aid, value, paths, reveal=True):
    """Run the action; return (outputs, errors) as lists. One failing file does not stop the rest."""
    outs, errs = [], []
    paths = [Path(p) for p in paths]
    try:
        if aid == "copy_path":
            subprocess.run(["wl-copy"], input="\n".join(str(p) for p in paths), text=True); return [str(paths[0])], []
        if aid == "pdf_merge":
            dst = output_path(paths[0], "pdf", suffix=" merged")
            _run(["pdfunite", *map(str, paths), str(dst)]); return [str(dst)], []
        if aid == "img_pdf":
            from PIL import Image
            ims = [Image.open(p).convert("RGB") for p in paths]
            dst = output_path(paths[0], "pdf", suffix="" if len(paths) == 1 else " album")
            ims[0].save(dst, save_all=True, append_images=ims[1:]); return [str(dst)], []
        if aid == "make_zip":
            dst = output_path(paths[0], "zip", suffix="" if len(paths) == 1 else " files")
            _run(["zip", "-rqj", str(dst), *map(str, paths)]); return [str(dst)], []
    except Exception as e:
        return [], [f"{paths[0].name}: {e}"]

    for p in paths:
        try:
            if aid == "img_convert": dst = output_path(p, value); _pillow_save(p, dst)
            elif aid == "img_resize": dst = output_path(p, suffix=" (resized)"); _pillow_save(p, dst, max_px=value)
            elif aid == "img_compress":
                tgt = "jpg" if p.suffix.lower() in (".jpg", ".jpeg", ".bmp", ".tiff", ".tif") else ("webp" if p.suffix.lower() != ".png" else "png")
                dst = output_path(p, tgt, suffix=" (small)"); _pillow_save(p, dst, quality=70)
            elif aid == "vid_convert":
                dst = output_path(p, value)
                codec = {"mp4": ["-c:v", "libx264", "-crf", "23", "-c:a", "aac"],
                         "webm": ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-c:a", "libopus"],
                         "mkv": ["-c:v", "libx264", "-crf", "23", "-c:a", "aac"]}[value]
                _run(["ffmpeg", "-y", "-i", str(p), *codec, str(dst)])
            elif aid == "vid_compress":
                dst = output_path(p, "mp4", suffix=f" ({value}p)")
                _run(["ffmpeg", "-y", "-i", str(p), "-vf", f"scale=-2:{value}", "-c:v", "libx264", "-crf", "26", "-preset", "medium", "-c:a", "aac", "-b:a", "128k", str(dst)])
            elif aid == "vid_audio": dst = output_path(p, "mp3"); _run(["ffmpeg", "-y", "-i", str(p), "-vn", "-b:a", "192k", str(dst)])
            elif aid == "vid_gif":
                dst = output_path(p, "gif")
                _run(["ffmpeg", "-y", "-i", str(p), "-vf", "fps=12,scale=640:-1:flags=lanczos", "-t", "15", str(dst)])
            elif aid == "aud_convert":
                dst = output_path(p, value)
                _run(["ffmpeg", "-y", "-i", str(p), *(["-b:a", "192k"] if value in ("mp3", "ogg") else []), str(dst)])
            elif aid in ("doc_pdf", "doc_docx"):
                fmt = "pdf" if aid == "doc_pdf" else "docx"
                _run(["libreoffice", "--headless", "--convert-to", fmt, "--outdir", str(p.parent), str(p)], timeout=300)
                made = p.with_suffix("." + fmt)
                if not made.exists(): raise RuntimeError("conversion produced no file")
                dst = made if made != p else output_path(p, fmt)
            elif aid == "pdf_compress":
                dst = output_path(p, "pdf", suffix=" (small)")
                _run(["gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4", "-dPDFSETTINGS=/ebook",
                      "-dNOPAUSE", "-dQUIET", "-dBATCH", f"-sOutputFile={dst}", str(p)])
            elif aid == "pdf_images":
                d = output_path(p, suffix=" pages").with_suffix(""); d.mkdir(exist_ok=True)
                _run(["pdftoppm", "-png", "-r", "150", str(p), str(d / "page")]); dst = d
            elif aid == "arc_extract":
                d = output_path(p, suffix="").with_suffix(""); d.mkdir(exist_ok=True)
                ext = p.suffix.lower()
                if ext == ".zip": _run(["unzip", "-o", "-q", str(p), "-d", str(d)])
                elif ext in (".tar", ".gz", ".tgz", ".bz2", ".xz"): _run(["tar", "-xf", str(p), "-C", str(d)])
                elif ext == ".rar": _run(["unrar", "x", "-o+", str(p), str(d) + "/"])
                else: _run(["7z", "x", f"-o{d}", "-y", str(p)])
                dst = d
            else: raise RuntimeError("unknown action")
            outs.append(str(dst))
        except Exception as e:
            errs.append(f"{p.name}: {e}")
    return outs, errs

# ───────────────────────── notifications & helpers ─────────────────────────
def notify(title, body="", icon="document-save-symbolic"):
    subprocess.run(["notify-send", "-a", "File Actions", "-i", icon, title, body], check=False)

def _rofi(prompt, items):   # fallback when GTK is unavailable
    r = subprocess.run(["rofi", "-dmenu", "-i", "-p", prompt], input="\n".join(items), capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None

ICONS = {
    "img_convert": "image-x-generic-symbolic", "img_resize": "view-fullscreen-symbolic",
    "img_compress": "view-restore-symbolic", "img_pdf": "x-office-document-symbolic",
    "vid_convert": "video-x-generic-symbolic", "vid_compress": "view-restore-symbolic",
    "vid_audio": "audio-x-generic-symbolic", "vid_gif": "media-playback-start-symbolic",
    "aud_convert": "audio-x-generic-symbolic", "doc_pdf": "x-office-document-symbolic",
    "doc_docx": "document-edit-symbolic", "pdf_compress": "view-restore-symbolic",
    "pdf_images": "emblem-photos-symbolic", "pdf_merge": "emblem-documents-symbolic",
    "arc_extract": "folder-open-symbolic", "make_zip": "emblem-documents-symbolic",
    "copy_path": "edit-copy-symbolic",
}
KIND_ICON = {"image": "image-x-generic-symbolic", "video": "video-x-generic-symbolic",
             "audio": "audio-x-generic-symbolic", "document": "x-office-document-symbolic",
             "pdf": "x-office-document-symbolic", "archive": "package-x-generic-symbolic", "other": "text-x-generic-symbolic"}

def human_size(paths):
    try: total = sum(Path(p).stat().st_size for p in paths)
    except OSError: return ""
    for unit in ("B", "KB", "MB", "GB"):
        if total < 1024 or unit == "GB": return f"{total:.0f} {unit}" if unit == "B" else f"{total:.1f} {unit}"
        total /= 1024

# ───────────────────────── Tangerine-style GTK picker ─────────────────────────
def run_gui(paths):
    import gi
    gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango
    import threading

    CSS = """
    window.fa { background: #17171a; border: 1px solid #38383e; border-radius: 18px; }
    .fa-head { font-size: 13pt; font-weight: 700; }
    .fa-sub { font-size: 10pt; opacity: .65; }
    .tile { background: alpha(@view_fg_color, .05); border-radius: 14px; padding: 14px 8px; min-width: 128px;
            transition: background 140ms ease, box-shadow 140ms ease; }
    .tile:hover { background: alpha(@accent_bg_color, .18); box-shadow: 0 2px 10px alpha(black,.25); }
    .tile image { -gtk-icon-size: 30px; margin-bottom: 8px; color: @accent_color; }
    .tile label { font-size: 10.5pt; }
    .opt { background: alpha(@view_fg_color, .06); border-radius: 12px; padding: 14px 18px; font-size: 12pt; min-width: 120px; }
    .opt:hover { background: alpha(@accent_bg_color, .22); }
    .thumb { border-radius: 12px; }
    """
    kinds = {kind_of(p) for p in paths}
    cat = catalogue()

    class Win(Adw.ApplicationWindow):
        def __init__(self, app):
            super().__init__(application=app, title="File Actions", default_width=560, default_height=460, css_classes=["fa"])
            self.busy = False
            self.toasts = Adw.ToastOverlay()
            self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT, transition_duration=160)
            self.stack.add_named(self._grid_page(), "grid")
            self.toasts.set_child(self.stack); self.set_content(self.toasts)
            key = Gtk.EventControllerKey(); key.connect("key-pressed", lambda _c, k, *_: k == Gdk.KEY_Escape and (self.close() or True)); self.add_controller(key)
            self.connect("notify::is-active", lambda *_: (not self.is_active()) and not self.busy and self.close())

        def _header(self):
            box = Gtk.Box(spacing=12, margin_start=18, margin_end=18, margin_top=16, margin_bottom=8)
            single_img = len(paths) == 1 and kind_of(paths[0]) == "image"
            if single_img:
                try:   # a small pre-scaled thumbnail: a Gtk.Picture of the full file insists on the image's own size
                    from gi.repository import GdkPixbuf
                    pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(paths[0]), 112, 112, True)
                    img = Gtk.Image.new_from_paintable(Gdk.Texture.new_for_pixbuf(pb))
                    img.set_pixel_size(56); img.add_css_class("thumb"); box.append(img)
                except Exception:
                    box.append(Gtk.Image(icon_name=KIND_ICON.get("image", "image-x-generic-symbolic"), pixel_size=40))
            else:
                box.append(Gtk.Image(icon_name=KIND_ICON.get(next(iter(kinds)) if len(kinds) == 1 else "other"), pixel_size=40))
            info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
            title = Path(paths[0]).name if len(paths) == 1 else f"{len(paths)} files"
            info.append(Gtk.Label(label=title, xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE, css_classes=["fa-head"]))
            sub = " · ".join(sorted(kinds)) + (f" · {human_size(paths)}" if human_size(paths) else "")
            info.append(Gtk.Label(label=sub, xalign=0, css_classes=["fa-sub"]))
            box.append(info)
            return box

        def _grid_page(self):
            page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); page.append(self._header())
            page.append(Gtk.Separator())
            fb = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3, min_children_per_line=3,
                             row_spacing=10, column_spacing=10, homogeneous=True, margin_start=16, margin_end=16, margin_top=14, margin_bottom=16)
            for aid, label in actions_for(paths):
                tile = Gtk.Button(css_classes=["tile"]); bx = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER)
                bx.append(Gtk.Image(icon_name=ICONS.get(aid, "applications-utilities-symbolic")))
                bx.append(Gtk.Label(label=label.replace("…", ""), wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=14))
                tile.set_child(bx); tile.connect("clicked", lambda _b, a=aid, l=label: self.choose(a, l))
                fb.append(tile)
            sw = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER); sw.set_child(fb)
            page.append(sw); return page

        def choose(self, aid, label):
            opts = cat[aid][2]
            if not opts: self.run(aid, None, label); return
            page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            hb = Gtk.Box(spacing=8, margin_start=12, margin_end=18, margin_top=12, margin_bottom=4)
            back = Gtk.Button(icon_name="go-previous-symbolic", css_classes=["flat", "circular"])
            back.connect("clicked", lambda *_: self.stack.set_visible_child_name("grid"))
            hb.append(back); hb.append(Gtk.Label(label=label.replace("…", ""), css_classes=["fa-head"], hexpand=True, xalign=0))
            page.append(hb); page.append(Gtk.Separator())
            fb = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3, row_spacing=10, column_spacing=10,
                             homogeneous=True, margin_start=18, margin_end=18, margin_top=16, margin_bottom=18, valign=Gtk.Align.START)
            for clabel, value in opts:
                b = Gtk.Button(label=clabel, css_classes=["opt"]); b.connect("clicked", lambda _x, v=value, l=label: self.run(aid, v, l)); fb.append(b)
            page.append(fb)
            old = self.stack.get_child_by_name("opts")
            if old: self.stack.remove(old)
            self.stack.add_named(page, "opts"); self.stack.set_visible_child_name("opts")

        def run(self, aid, value, label):
            if aid == "copy_path":
                run_action(aid, None, paths); notify("Copied path", str(Path(paths[0])), "edit-copy-symbolic"); self.close(); return
            self.busy = True
            page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, vexpand=True, spacing=16)
            page.append(Adw.Spinner(width_request=48, height_request=48))
            page.append(Gtk.Label(label=f"{label.replace('…','')} · {len(paths)} file(s)…", css_classes=["fa-head"]))
            page.append(Gtk.Label(label="Originals are kept", css_classes=["fa-sub"]))
            old = self.stack.get_child_by_name("run")
            if old: self.stack.remove(old)
            self.stack.add_named(page, "run"); self.stack.set_visible_child_name("run")
            def work():
                outs, errs = run_action(aid, value, paths)
                GLib.idle_add(self.done, outs, errs)
            threading.Thread(target=work, daemon=True).start()

        def done(self, outs, errs):
            self.busy = False
            if outs:
                first = Path(outs[0])
                notify("Done" + (f" · {len(errs)} failed" if errs else ""),
                       f"{len(outs)} files · {first.parent.name}/" if len(outs) > 1 else first.name, "emblem-ok-symbolic")
                subprocess.Popen(["nautilus", "--select", outs[0]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                notify("Couldn't complete", errs[0] if errs else "No output", "dialog-error-symbolic")
            self.close(); return False

    class App(Adw.Application):
        def __init__(self): super().__init__(application_id="org.myos.FileActions", flags=Gio.ApplicationFlags.NON_UNIQUE)
        def do_activate(self):
            prov = Gtk.CssProvider(); prov.load_from_string(CSS)
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
            Win(self).present()
    App().run([])

def main(argv):
    paths = [a for a in argv if os.path.exists(a)]
    if not argv:   # launched from Super+Space / a shortcut: let the user pick files first
        r = subprocess.run(["zenity", "--file-selection", "--multiple", "--separator=\n", "--title=Convert files"],
                           capture_output=True, text=True)
        paths = [l for l in r.stdout.splitlines() if os.path.exists(l)]
        if not paths: return 0
    if not paths: notify("File Actions", "No files selected"); return 1
    if not actions_for(paths): notify("File Actions", "No actions for this selection"); return 1
    try:
        import gi; gi.require_version("Gtk", "4.0"); run_gui(paths); return 0
    except Exception:
        pass  # headless / no GTK: fall back to rofi
    acts = actions_for(paths)
    pick = _rofi(f"Actions ({len(paths)} files)", [l for _, l in acts])
    if not pick: return 0
    aid = next(a for a, l in acts if l == pick); opts = catalogue()[aid][2]; value = None
    if opts:
        c = _rofi(acts and pick, [c for c, _ in opts])
        if not c: return 0
        value = next(v for cl, v in opts if cl == c)
    outs, errs = run_action(aid, value, paths)
    notify("Done" if outs else "Failed", (Path(outs[0]).name if outs else (errs[0] if errs else "")), "emblem-ok-symbolic" if outs else "dialog-error-symbolic")
    if outs and aid != "copy_path": subprocess.Popen(["nautilus", "--select", outs[0]])
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
