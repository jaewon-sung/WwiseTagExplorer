"""
WwiseTagExplorer Main Window
Dark-themed tag-based Wwise resource navigator.
"""

import json
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from collections import Counter

import customtkinter as ctk
from PIL import Image, ImageTk

from core.waapi_client import get_client, CATEGORIES, parse_tags

# ── Color palette ──────────────────────────────────────────────────────────────
COLOR_BG_DARK    = "#1c1c1e"
COLOR_BG_MID     = "#2c2c2e"
COLOR_ACCENT     = "#3a3a3c"
COLOR_SELECTED   = "#007aff"
COLOR_TEXT       = "#f5f5f7"
COLOR_TEXT_DIM   = "#8e8e93"
COLOR_GREEN      = "#34c759"
COLOR_YELLOW     = "#ffcc00"
COLOR_RED        = "#ff3b30"
COLOR_SEPARATOR   = "#48484a"
COLOR_SECTION_LBL = "#636366"
COLOR_VLIST_SEL   = "#0a84ff"

ICON_SIZE = (16, 16)
TAGS_PER_ROW = 6
TAGS_DEFAULT_ROWS = 3
TAGS_DEFAULT_MAX = TAGS_PER_ROW * TAGS_DEFAULT_ROWS  # 18

# Resolve asset path for both dev and frozen (PyInstaller) environments
if getattr(sys, "frozen", False):
    _BASE = Path(sys._MEIPASS)
else:
    _BASE = Path(__file__).parent.parent
ASSETS_DIR = _BASE / "assets" / "icons"

# Some Wwise type names differ from the PNG filenames bundled from the installer
_ICON_FILENAME_ALIASES: dict[str, str] = {
    "Bus": "AudioBus",
    "Effect": "EffectPlugin",
}

# ── Icon loaders ──────────────────────────────────────────────────────────────

# PhotoImage cache for Canvas (must stay referenced to avoid GC)
_tk_icon_cache: dict[str, ImageTk.PhotoImage | None] = {}


def _load_tk_icon(obj_type: str) -> ImageTk.PhotoImage | None:
    if obj_type in _tk_icon_cache:
        return _tk_icon_cache[obj_type]
    filename = _ICON_FILENAME_ALIASES.get(obj_type, obj_type)
    path = ASSETS_DIR / f"{filename}.png"
    if not path.exists():
        _tk_icon_cache[obj_type] = None
        return None
    try:
        img = Image.open(path).resize((14, 14), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        _tk_icon_cache[obj_type] = photo
        return photo
    except Exception:
        _tk_icon_cache[obj_type] = None
        return None


class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        self._selected_category: str | None = None
        self._selected_wu_path: str | None = None
        self._selected_tags: list[str] = []
        self._tag_sort: str = "freq"
        self._expand_levels: set[int] = set()
        self._objects: list[dict] = []
        self._work_units: list[dict] = []
        self._saved_state: dict[str, dict] = {}
        # Virtual list state
        self._vlist_items: list[dict] = []
        self._vlist_row_h: int = 26
        self._vlist_hover: int = -1
        self._vlist_selected: int = -1
        self._vlist_col_split: float = 0.4   # divider as fraction of canvas width
        self._vlist_dragging: bool = False
        # Favorites
        self._favorites: set[str] = set()
        # favorites.json lives next to the exe (or project root in dev)
        if getattr(sys, "frozen", False):
            self._favorites_path = Path(sys.executable).parent / "favorites.json"
        else:
            self._favorites_path = Path(__file__).parent.parent / "favorites.json"
        self._load_favorites()

        self._setup_window()
        self._build_ui()
        # Auto-connect on startup
        self.after(200, self._start_connect)

    # ── Window setup ──────────────────────────────────────────────────────────

    def _setup_window(self):
        self.title("WwiseTagExplorer")
        self.geometry("1080x760")
        self.minsize(800, 550)
        self.configure(fg_color=COLOR_BG_DARK)
        self.iconbitmap(default="")

    # ── UI build ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── Title bar (title + status + reconnect) ────────────────────────────
        title_bar = ctk.CTkFrame(self, fg_color=COLOR_BG_MID, height=48, corner_radius=0)
        title_bar.grid(row=0, column=0, sticky="ew")
        title_bar.grid_columnconfigure(1, weight=1)
        title_bar.grid_propagate(False)

        ctk.CTkLabel(
            title_bar, text="  WwiseTagExplorer",
            font=ctk.CTkFont(family="SF Pro Display", size=17, weight="bold"),
            text_color=COLOR_TEXT, anchor="w",
        ).grid(row=0, column=0, padx=14, pady=10, sticky="w")

        # Status area (right side of title bar)
        status_frame = ctk.CTkFrame(title_bar, fg_color="transparent")
        status_frame.grid(row=0, column=2, padx=14, pady=8, sticky="e")

        self._status_canvas = tk.Canvas(
            status_frame, width=10, height=10, bg=COLOR_BG_MID, highlightthickness=0,
        )
        self._status_canvas.pack(side="left", padx=(0, 6))
        self._status_dot = self._status_canvas.create_oval(1, 1, 9, 9, fill=COLOR_YELLOW, outline="")

        self._status_label = ctk.CTkLabel(
            status_frame, text="Connecting...",
            font=ctk.CTkFont(size=11), text_color=COLOR_TEXT_DIM, anchor="w",
        )
        self._status_label.pack(side="left", padx=(0, 10))

        self._btn_reconnect = ctk.CTkButton(
            status_frame, text="Reconnect",
            font=ctk.CTkFont(size=10),
            fg_color=COLOR_ACCENT, hover_color=COLOR_SELECTED,
            width=80, height=26, corner_radius=6,
            command=self._start_connect,
        )
        # Only shown when disconnected — don't pack yet

        self._btn_refresh = ctk.CTkButton(
            status_frame, text="Refresh",
            font=ctk.CTkFont(size=10),
            fg_color=COLOR_ACCENT, hover_color=COLOR_SELECTED,
            width=70, height=26, corner_radius=6,
            command=self._on_refresh,
        )
        self._btn_refresh.pack(side="left", padx=(0, 4))

        self._btn_full_reset = ctk.CTkButton(
            status_frame, text="Reset All",
            font=ctk.CTkFont(size=10),
            fg_color=COLOR_ACCENT, hover_color=COLOR_SELECTED,
            width=72, height=26, corner_radius=6,
            command=self._on_full_reset,
        )
        self._btn_full_reset.pack(side="left")

        # ── Main area ─────────────────────────────────────────────────────────
        main = ctk.CTkFrame(self, fg_color=COLOR_BG_DARK, corner_radius=0)
        main.grid(row=1, column=0, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        # Category bar
        cat_bar = ctk.CTkFrame(main, fg_color=COLOR_BG_DARK, height=44, corner_radius=0)
        cat_bar.grid(row=0, column=0, sticky="ew")
        cat_bar.grid_propagate(False)

        self._cat_buttons: dict[str, ctk.CTkButton] = {}
        for i, cat in enumerate(CATEGORIES):
            btn = ctk.CTkButton(
                cat_bar, text=cat,
                font=ctk.CTkFont(size=12),
                fg_color="transparent",
                text_color=COLOR_TEXT_DIM,
                hover_color=COLOR_ACCENT,
                height=32, corner_radius=8,
                command=lambda c=cat: self._on_category(c),
            )
            btn.pack(side="left", padx=(10 if i == 0 else 3, 3), pady=6)
            self._cat_buttons[cat] = btn

        # Content pane
        content = ctk.CTkFrame(main, fg_color=COLOR_BG_DARK, corner_radius=0)
        content.grid(row=1, column=0, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(2, weight=1)

        BTN_W, BTN_H = 66, 26

        # ── WORK UNIT fixed header (outside scroll) ───────────────────────────
        wu_outer = ctk.CTkFrame(content, fg_color=COLOR_BG_MID, corner_radius=8)
        wu_outer.grid(row=0, column=0, sticky="ew", padx=10, pady=(4, 0))
        wu_outer.grid_columnconfigure(0, weight=1)

        # Label row: "WORK UNIT" left, sort+clear buttons right
        wu_hdr = ctk.CTkFrame(wu_outer, fg_color="transparent")
        wu_hdr.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 2))
        wu_hdr.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            wu_hdr, text="WORK UNIT",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLOR_TEXT, anchor="w",
        ).grid(row=0, column=0, sticky="w")

        btn_frame = ctk.CTkFrame(wu_hdr, fg_color="transparent")
        btn_frame.grid(row=0, column=1, sticky="e")

        self._btn_sort_freq = ctk.CTkButton(
            btn_frame, text="빈도순",
            font=ctk.CTkFont(size=12),
            fg_color=COLOR_SELECTED, hover_color="#005ecb",
            width=BTN_W, height=BTN_H, corner_radius=6,
            command=lambda: self._set_sort("freq"),
        )
        self._btn_sort_freq.pack(side="left", padx=2)

        self._btn_sort_alpha = ctk.CTkButton(
            btn_frame, text="A-Z",
            font=ctk.CTkFont(size=12),
            fg_color=COLOR_ACCENT, hover_color=COLOR_SELECTED,
            width=BTN_W, height=BTN_H, corner_radius=6,
            command=lambda: self._set_sort("alpha"),
        )
        self._btn_sort_alpha.pack(side="left", padx=2)

        self._btn_clear_tags = ctk.CTkButton(
            btn_frame, text="Clear",
            font=ctk.CTkFont(size=12),
            fg_color=COLOR_ACCENT, hover_color=COLOR_SELECTED,
            width=BTN_W, height=BTN_H, corner_radius=6,
            command=self._on_tag_reset,
        )
        self._btn_clear_tags.pack(side="left", padx=(18, 2))

        # Separator under label row
        sep0 = tk.Frame(wu_outer, height=2, bg=COLOR_SEPARATOR)
        sep0.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 4))
        sep0.grid_propagate(False)

        # WU buttons frame (rebuilt in _rebuild_wu_panel)
        self._wu_btn_frame = ctk.CTkFrame(wu_outer, fg_color="transparent")
        self._wu_btn_frame.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        self._wu_btn_frame.grid_propagate(False)

        # ── Tag scroll (tags only, no WU) ─────────────────────────────────────
        self._tag_scroll = ctk.CTkScrollableFrame(
            content, fg_color=COLOR_BG_MID, corner_radius=8,
            height=180,
        )
        self._tag_scroll.grid(row=1, column=0, sticky="ew", padx=10, pady=(4, 4))
        self._tag_scroll.grid_columnconfigure(0, weight=1)

        # Result panel
        result_outer = ctk.CTkFrame(content, fg_color=COLOR_BG_DARK, corner_radius=0)
        result_outer.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 8))
        result_outer.grid_columnconfigure(0, weight=1)
        result_outer.grid_rowconfigure(1, weight=1)

        result_hdr = ctk.CTkFrame(result_outer, fg_color=COLOR_BG_MID, corner_radius=8, height=34)
        result_hdr.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        result_hdr.grid_columnconfigure(0, weight=1)
        result_hdr.grid_propagate(False)

        self._result_count_lbl = ctk.CTkLabel(
            result_hdr, text="Results",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLOR_TEXT, anchor="w",
        )
        self._result_count_lbl.grid(row=0, column=0, padx=14, sticky="w")

        # Virtual list: header + canvas + scrollbar
        vlist_frame = ctk.CTkFrame(result_outer, fg_color=COLOR_BG_MID, corner_radius=8)
        vlist_frame.grid(row=1, column=0, sticky="nsew")
        vlist_frame.grid_columnconfigure(0, weight=1)
        vlist_frame.grid_rowconfigure(1, weight=1)

        # Column header canvas (fixed, not scrollable)
        self._vlist_header = tk.Canvas(
            vlist_frame, bg=COLOR_BG_DARK, highlightthickness=0, bd=0, height=24,
        )
        self._vlist_header.grid(row=0, column=0, sticky="ew", padx=(4, 0), pady=(4, 0))
        self._vlist_header.bind("<Configure>", lambda e: self._vlist_draw_header())
        self._vlist_header.bind("<Motion>",        self._vlist_hdr_motion)
        self._vlist_header.bind("<Button-1>",      self._vlist_hdr_press)
        self._vlist_header.bind("<B1-Motion>",     self._vlist_hdr_drag)
        self._vlist_header.bind("<ButtonRelease-1>", self._vlist_hdr_release)

        self._vlist_canvas = tk.Canvas(
            vlist_frame, bg=COLOR_BG_MID, highlightthickness=0, bd=0,
        )
        self._vlist_canvas.grid(row=1, column=0, sticky="nsew", padx=(4, 0), pady=(0, 4))

        vlist_sb = ctk.CTkScrollbar(vlist_frame, command=self._vlist_canvas.yview)
        vlist_sb.grid(row=0, column=1, rowspan=2, sticky="ns", pady=4)
        self._vlist_canvas.configure(yscrollcommand=vlist_sb.set)

        self._vlist_canvas.bind("<Configure>", lambda e: self._vlist_draw())
        self._vlist_canvas.bind("<MouseWheel>", self._vlist_on_wheel)
        self._vlist_canvas.bind("<Motion>",    self._vlist_on_motion)
        self._vlist_canvas.bind("<Leave>",     self._vlist_on_leave)
        self._vlist_canvas.bind("<Button-1>",  self._vlist_on_click)
        self._vlist_canvas.bind("<B1-Motion>", self._vlist_hdr_drag)
        self._vlist_canvas.bind("<ButtonRelease-1>", self._vlist_hdr_release)

        # Font objects for text measurement
        self._font_name = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self._font_path = tkfont.Font(family="Segoe UI", size=9)
        self._font_hdr  = tkfont.Font(family="Segoe UI", size=9)

        self._show_filter_placeholder("Connecting to Wwise...")

        # Rebuild tag panel on window resize (debounced)
        self._resize_after_id = None
        self.bind("<Configure>", self._on_window_resize)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _on_window_resize(self, event):
        if event.widget is not self:
            return
        if self._resize_after_id:
            self.after_cancel(self._resize_after_id)
        self._resize_after_id = self.after(120, self._on_resize_done)

    def _on_resize_done(self):
        self._resize_after_id = None
        if self._selected_category and self._objects:
            self._rebuild_tag_panel()

    def _flow_place(self, frame: ctk.CTkFrame, buttons: list, padx: int = 3, pady: int = 2):
        """Flow-layout buttons inside frame, wrapping at frame width. Sets frame height."""
        self.update_idletasks()
        w = frame.winfo_width()
        if w <= 1:
            w = max(self._tag_scroll.winfo_width() - 24, 300)

        x, y, row_h = padx, pady, 0
        for btn in buttons:
            bw = btn.winfo_reqwidth()
            bh = btn.winfo_reqheight()
            if bw <= 1:
                try:
                    bw = len(btn.cget("text")) * 8 + 24
                except Exception:
                    bw = 80
            if bh <= 1:
                bh = 26
            if x > padx and x + bw + padx > w:
                x = padx
                y += row_h + pady
                row_h = 0
            btn.place(x=x, y=y)
            x += bw + padx
            row_h = max(row_h, bh)

        frame.configure(height=max(y + row_h + pady * 2, 30))

    def _show_filter_placeholder(self, message: str = "Select a category"):
        for w in self._tag_scroll.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self._tag_scroll, text=message,
            font=ctk.CTkFont(size=12), text_color=COLOR_TEXT_DIM,
        ).grid(row=0, column=0, padx=16, pady=24)

    def _section_label(self, parent, text: str, row: int) -> int:
        """Render a section header with a separator below. Returns next row."""
        ctk.CTkLabel(
            parent, text=text,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLOR_TEXT, anchor="w",
        ).grid(row=row, column=0, padx=10, pady=(8, 2), sticky="w")
        row += 1
        sep = tk.Frame(parent, height=2, bg=COLOR_SEPARATOR)
        sep.grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 4))
        sep.grid_propagate(False)
        return row + 1

    # ── Favorites ─────────────────────────────────────────────────────────────

    def _load_favorites(self):
        try:
            if self._favorites_path.exists():
                data = json.loads(self._favorites_path.read_text(encoding="utf-8"))
                self._favorites = set(data.get("favorites", []))
        except Exception:
            self._favorites = set()

    def _save_favorites(self):
        try:
            self._favorites_path.write_text(
                json.dumps({"favorites": sorted(self._favorites)}, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _on_wu_favorite(self, wu_path: str):
        if wu_path in self._favorites:
            self._favorites.discard(wu_path)
        else:
            self._favorites.add(wu_path)
        self._save_favorites()
        self._rebuild_wu_panel()

    def _make_wu_button(self, parent, wu_name: str, wu_path: str, active: bool) -> ctk.CTkFrame:
        """Single frame styled as a button: [  Name ☆  ] — star toggles favorite."""
        is_fav = wu_path in self._favorites
        bg       = COLOR_SELECTED if active else COLOR_ACCENT
        hover_bg = "#005ecb"       if active else COLOR_SELECTED

        frame = ctk.CTkFrame(parent, fg_color=bg, corner_radius=6)

        name_lbl = ctk.CTkLabel(
            frame, text=f"  {wu_name}",
            font=ctk.CTkFont(size=11, weight="bold" if active else "normal"),
            text_color="#ffffff", fg_color="transparent",
        )
        name_lbl.pack(side="left", pady=2)

        star_lbl = ctk.CTkLabel(
            frame, text="★ " if is_fav else "☆ ",
            font=ctk.CTkFont(size=15),
            text_color=COLOR_YELLOW if is_fav else COLOR_TEXT_DIM,
            fg_color="transparent",
            height=26,
        )
        star_lbl.pack(side="left", pady=2)

        # Hover
        def on_enter(e=None): frame.configure(fg_color=hover_bg)
        def on_leave(e=None): frame.configure(fg_color=bg)

        # Select WU on frame/name click
        for w in (frame, name_lbl):
            w.bind("<Button-1>", lambda e, p=wu_path: self._on_wu_select(p))
            w.bind("<Enter>", lambda e: on_enter())
            w.bind("<Leave>", lambda e: on_leave())

        # Toggle favorite on star click — stop propagation so WU select doesn't fire
        def on_star(e, p=wu_path):
            self._on_wu_favorite(p)
            return "break"

        star_lbl.bind("<Button-1>", on_star)
        star_lbl.bind("<Enter>", lambda e: on_enter())
        star_lbl.bind("<Leave>", lambda e: on_leave())

        return frame

    # ── Connection ────────────────────────────────────────────────────────────

    def _start_connect(self):
        self._btn_reconnect.pack_forget()
        self._status_canvas.itemconfig(self._status_dot, fill=COLOR_YELLOW)
        self._status_label.configure(text="Connecting...", text_color=COLOR_TEXT_DIM)
        threading.Thread(target=self._connect_thread, daemon=True).start()

    def _connect_thread(self):
        client = get_client()
        client.set_status_callback(lambda ok, msg: self.after(0, self._update_status, ok, msg))
        ok = client.connect()
        self.after(0, self._on_connect_done, ok)

    def _on_connect_done(self, ok: bool):
        if ok:
            threading.Thread(target=self._prefetch_all, daemon=True).start()
        # Status already updated via callback; reconnect button shown if needed via _update_status

    def _prefetch_all(self):
        """Load all category data into cache in parallel right after connect."""
        client = get_client()
        threads = [
            threading.Thread(target=client.get_category_data, args=(cat,), daemon=True)
            for cat in CATEGORIES
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    def _update_status(self, connected: bool, message: str):
        if connected:
            self._status_canvas.itemconfig(self._status_dot, fill=COLOR_GREEN)
            self._status_label.configure(text=message, text_color=COLOR_TEXT)
            self._btn_reconnect.pack_forget()
            self._show_filter_placeholder("Select a category")
            # Auto-select Audio on connect
            self.after(100, lambda: self._on_category("Audio"))
        else:
            self._status_canvas.itemconfig(self._status_dot, fill=COLOR_RED)
            self._status_label.configure(text=message, text_color=COLOR_TEXT_DIM)
            self._btn_reconnect.pack(side="left", padx=(8, 0))
            self._clear_all()

    def _clear_all(self):
        self._selected_category = None
        self._selected_wu_path = None
        self._selected_tags = []
        self._objects = []
        self._work_units = []
        self._expand_levels.clear()
        for btn in self._cat_buttons.values():
            btn.configure(fg_color="transparent", text_color=COLOR_TEXT_DIM)
        for w in self._wu_btn_frame.winfo_children():
            w.destroy()
        self._show_filter_placeholder("Select a category")
        self._vlist_items = []
        self._vlist_hover = -1
        self._result_count_lbl.configure(text="Results")

    # ── Category selection ────────────────────────────────────────────────────

    def _on_category(self, category: str):
        client = get_client()
        if not client.is_connected():
            return

        if self._selected_category:
            self._saved_state[self._selected_category] = {
                "wu_path": self._selected_wu_path,
                "tags": list(self._selected_tags),
                "expand": set(self._expand_levels),
            }

        for cat, btn in self._cat_buttons.items():
            if cat == category:
                btn.configure(fg_color=COLOR_SELECTED, text_color="#ffffff")
            else:
                btn.configure(fg_color="transparent", text_color=COLOR_TEXT_DIM)

        self._selected_category = category

        saved = self._saved_state.get(category)
        if saved:
            self._selected_wu_path = saved["wu_path"]
            self._selected_tags = list(saved["tags"])
            self._expand_levels = set(saved.get("expand", set()))
        else:
            self._selected_wu_path = None
            self._selected_tags = []
            self._expand_levels.clear()

        threading.Thread(target=self._load_category_thread, args=(category,), daemon=True).start()

    def _load_category_thread(self, category: str):
        client = get_client()
        data = client.get_category_data(category)
        self.after(0, self._on_category_loaded, category, data)

    def _on_category_loaded(self, category: str, data: dict):
        if self._selected_category != category:
            return
        self._objects = data["objects"]
        self._work_units = data["work_units"]
        # Auto-select first favorited WU if no selection saved
        if self._selected_wu_path is None and self._favorites:
            for wu in self._work_units:
                if wu.get("path", "") in self._favorites:
                    self._selected_wu_path = wu["path"]
                    break
        self._rebuild_wu_panel()
        self._rebuild_tag_panel()
        self._rebuild_results()

    # ── Refresh ───────────────────────────────────────────────────────────────

    def _on_refresh(self):
        if not self._selected_category:
            return
        client = get_client()
        if not client.is_connected():
            return
        client.invalidate_cache(self._selected_category)
        threading.Thread(
            target=self._load_category_thread,
            args=(self._selected_category,),
            daemon=True,
        ).start()

    # ── Full reset ────────────────────────────────────────────────────────────

    def _on_full_reset(self):
        self._saved_state.clear()
        self._selected_wu_path = None
        self._selected_tags = []
        self._expand_levels.clear()
        if self._selected_category:
            self._rebuild_wu_panel()
            self._rebuild_tag_panel()
            self._rebuild_results()

    # ── Tag reset ─────────────────────────────────────────────────────────────

    def _on_tag_reset(self):
        self._selected_tags = []
        self._expand_levels.clear()
        self._rebuild_tag_panel()
        self._rebuild_results()
        self._rebuild_wu_panel()

    # ── Sort ──────────────────────────────────────────────────────────────────

    def _set_sort(self, mode: str):
        self._tag_sort = mode
        self._btn_sort_freq.configure(fg_color=COLOR_SELECTED if mode == "freq" else COLOR_ACCENT)
        self._btn_sort_alpha.configure(fg_color=COLOR_SELECTED if mode == "alpha" else COLOR_ACCENT)
        self._rebuild_tag_panel()
        self._rebuild_results()

    # ── Tag panel rebuild ─────────────────────────────────────────────────────

    def _get_filtered_objects(self, tags: list[str]) -> list[dict]:
        base = self._objects
        if self._selected_wu_path:
            wu = self._selected_wu_path
            base = [o for o in base if o.get("path", "").startswith(wu + "\\") or
                    o.get("path", "") == wu]
        if not tags:
            return base
        return [
            o for o in base
            if all(t in parse_tags(o.get("name", "")) for t in tags)
        ]

    def _compute_tags(self, objects: list[dict], exclude: set[str]) -> list[tuple[str, int]]:
        counter: Counter = Counter()
        for obj in objects:
            for tag in parse_tags(obj.get("name", "")):
                if tag not in exclude:
                    counter[tag] += 1
        if self._tag_sort == "alpha":
            return sorted(counter.items(), key=lambda x: x[0])
        return sorted(counter.items(), key=lambda x: (-x[1], x[0]))

    def _rebuild_wu_panel(self):
        """Rebuild the fixed WU button area (outside scroll)."""
        for w in self._wu_btn_frame.winfo_children():
            w.destroy()
        wu_items = [("All", None)] + [
            (wu.get("name", wu.get("path", "?").split("\\")[-1]), wu.get("path", ""))
            for wu in self._work_units
        ]
        wu_buttons = []
        for wu_name, wu_path in wu_items:
            active = (self._selected_wu_path == wu_path)
            if wu_path is None:
                btn = ctk.CTkButton(
                    self._wu_btn_frame, text=wu_name,
                    font=ctk.CTkFont(size=11, weight="bold" if active else "normal"),
                    fg_color=COLOR_SELECTED if active else COLOR_ACCENT,
                    hover_color="#005ecb" if active else COLOR_SELECTED,
                    text_color="#ffffff",
                    height=26, corner_radius=6,
                    command=lambda p=wu_path: self._on_wu_select(p),
                )
                wu_buttons.append(btn)
            else:
                wu_buttons.append(self._make_wu_button(self._wu_btn_frame, wu_name, wu_path, active))
        self._flow_place(self._wu_btn_frame, wu_buttons)

    def _rebuild_tag_panel(self):
        for w in self._tag_scroll.winfo_children():
            w.destroy()

        if not self._objects and not self._work_units:
            ctk.CTkLabel(
                self._tag_scroll,
                text="No objects found in this category",
                font=ctk.CTkFont(size=12), text_color=COLOR_TEXT_DIM,
            ).grid(row=0, column=0, padx=16, pady=24)
            return

        row = 0
        self._tag_scroll.grid_columnconfigure(0, weight=1)

        # ── Tag blocks (one per selection level, each with own label) ───────
        num_levels = len(self._selected_tags) + 1
        for level in range(num_levels):
            # Stop adding new levels if all current results share the same parent path
            if level > 0:
                current = self._get_filtered_objects(self._selected_tags[:level])
                if current and len(set(
                    o.get("path", "").rsplit("\\", 1)[0] for o in current
                )) == 1:
                    break
            filtered = self._get_filtered_objects(self._selected_tags[:level])
            exclude_tags = set(self._selected_tags[:level])
            tags = self._compute_tags(filtered, exclude_tags)

            # Stop if only one result remains — nothing left to narrow down
            if level > 0 and len(filtered) <= 1:
                break

            # Stop if every tag in this level produces identical results (no filtering effect)
            if level > 0 and tags:
                current_ids = {o.get("id") for o in filtered}
                all_same = all(
                    {o.get("id") for o in self._get_filtered_objects(
                        self._selected_tags[:level] + [tag]
                    )} == current_ids
                    for tag, _ in tags
                )
                if all_same:
                    break

            selected_at_level = (
                self._selected_tags[level] if level < len(self._selected_tags) else None
            )

            # Section label: "TAG LEVEL N" with Clear button on level 1
            lbl_frame = ctk.CTkFrame(self._tag_scroll, fg_color="transparent")
            lbl_frame.grid(row=row, column=0, sticky="ew", padx=10, pady=(6, 0))
            ctk.CTkLabel(
                lbl_frame, text=f"TAG LEVEL {level + 1}",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=COLOR_TEXT, anchor="w",
            ).pack(side="left")
            row += 1

            sep = tk.Frame(self._tag_scroll, height=2, bg=COLOR_SEPARATOR)
            sep.grid(row=row, column=0, sticky="ew", padx=8, pady=(2, 4))
            sep.grid_propagate(False)
            row += 1

            row = self._add_tag_block(row, level, tags, selected_at_level)

    def _add_tag_block(
        self,
        start_row: int,
        level: int,
        tags: list[tuple[str, int]],
        selected: str | None,
    ) -> int:
        if not tags and selected is None:
            return start_row

        max_default = TAGS_DEFAULT_ROWS * 6  # rough default cap (flow handles real wrap)
        expanded = level in self._expand_levels
        visible_tags = tags if expanded else tags[:max_default]
        overflow = len(tags) - max_default if not expanded and len(tags) > max_default else 0

        tag_frame = ctk.CTkFrame(self._tag_scroll, fg_color="transparent")
        tag_frame.grid(row=start_row, column=0, sticky="ew", padx=8, pady=2)
        tag_frame.grid_propagate(False)

        tag_buttons = []
        for tag, count in visible_tags:
            is_active = (tag == selected)
            btn = ctk.CTkButton(
                tag_frame, text=tag,
                font=ctk.CTkFont(size=11, weight="bold" if is_active else "normal"),
                fg_color=COLOR_SELECTED if is_active else COLOR_ACCENT,
                hover_color="#005ecb" if is_active else COLOR_SELECTED,
                text_color="#ffffff",
                height=26, corner_radius=6,
                command=lambda t=tag, lv=level: self._on_tag_click(t, lv),
            )
            tag_buttons.append(btn)

        if overflow > 0:
            tag_buttons.append(ctk.CTkButton(
                tag_frame, text=f"+ 더보기 ({overflow})",
                font=ctk.CTkFont(size=10),
                fg_color="transparent", text_color=COLOR_TEXT_DIM,
                hover_color=COLOR_ACCENT,
                height=26, corner_radius=6,
                border_width=1, border_color=COLOR_ACCENT,
                command=lambda lv=level: self._on_expand(lv),
            ))
        elif expanded and len(tags) > max_default:
            tag_buttons.append(ctk.CTkButton(
                tag_frame, text="- 접기",
                font=ctk.CTkFont(size=10),
                fg_color="transparent", text_color=COLOR_TEXT_DIM,
                hover_color=COLOR_ACCENT,
                height=26, corner_radius=6,
                border_width=1, border_color=COLOR_ACCENT,
                command=lambda lv=level: self._on_collapse(lv),
            ))

        self._flow_place(tag_frame, tag_buttons)
        return start_row + 1


    # ── Tag / WU interaction ──────────────────────────────────────────────────

    def _on_wu_select(self, wu_path: str | None):
        self._selected_wu_path = wu_path
        self._selected_tags = []
        self._expand_levels.clear()
        self._rebuild_wu_panel()
        self._rebuild_tag_panel()
        self._rebuild_results()

    def _on_tag_click(self, tag: str, level: int):
        if level < len(self._selected_tags):
            if self._selected_tags[level] == tag:
                self._selected_tags = self._selected_tags[:level]
                self._expand_levels = {l for l in self._expand_levels if l < level}
            else:
                self._selected_tags = self._selected_tags[:level] + [tag]
                self._expand_levels = {l for l in self._expand_levels if l <= level}
        else:
            self._selected_tags = self._selected_tags[:level] + [tag]
            self._expand_levels = {l for l in self._expand_levels if l < level}
        self._rebuild_tag_panel()
        self._rebuild_results()
        # Scroll tag panel to bottom so new level is visible
        self.after(80, lambda: self._tag_scroll._parent_canvas.yview_moveto(1.0))

    def _on_expand(self, level: int):
        self._expand_levels.add(level)
        self._rebuild_tag_panel()

    def _on_collapse(self, level: int):
        self._expand_levels.discard(level)
        self._rebuild_tag_panel()

    # ── Results ───────────────────────────────────────────────────────────────

    def _clear_results(self):
        self._vlist_items = []
        self._vlist_hover = -1
        self._vlist_draw()

    def _rebuild_results(self):
        filtered = self._get_filtered_objects(self._selected_tags)
        self._result_count_lbl.configure(text=f"Results  ({len(filtered)})")
        self._vlist_items = filtered
        self._vlist_hover = -1
        self._vlist_selected = -1
        self._vlist_draw()

    # ── Virtual list ──────────────────────────────────────────────────────────

    def _vlist_draw(self):
        canvas = self._vlist_canvas
        canvas.delete("all")

        if not self._vlist_items:
            cw = canvas.winfo_width()
            ch = canvas.winfo_height()
            canvas.create_text(
                max(cw, 1) // 2, max(ch, 1) // 2,
                text="No results", fill=COLOR_TEXT_DIM,
                font=("Segoe UI", 11),
            )
            canvas.configure(scrollregion=(0, 0, 1, 1))
            return

        cw = max(canvas.winfo_width(), 1)
        total_h = len(self._vlist_items) * self._vlist_row_h
        canvas.configure(scrollregion=(0, 0, cw, total_h))

        ch = max(canvas.winfo_height(), 1)
        y_top = canvas.canvasy(0)
        y_bot = canvas.canvasy(ch)

        first = max(0, int(y_top / self._vlist_row_h))
        last  = min(len(self._vlist_items) - 1, int(y_bot / self._vlist_row_h) + 1)

        ICON_X  = 15
        NAME_X  = 28
        PAD     = 8
        split_x = int(cw * self._vlist_col_split)
        name_max = max(split_x - NAME_X - PAD, 0)
        path_max = max(cw - split_x - PAD * 2, 0)

        for i in range(first, last + 1):
            obj  = self._vlist_items[i]
            y0   = i * self._vlist_row_h
            y1   = y0 + self._vlist_row_h
            mid  = y0 + self._vlist_row_h // 2

            if i == self._vlist_selected:
                bg = COLOR_VLIST_SEL
            elif i == self._vlist_hover:
                bg = COLOR_ACCENT
            elif i % 2 == 0:
                bg = COLOR_BG_DARK
            else:
                bg = COLOR_BG_MID

            canvas.create_rectangle(0, y0, cw, y1, fill=bg, outline="", tags=f"bg{i}")

            # Divider line
            canvas.create_line(split_x, y0, split_x, y1, fill=COLOR_SEPARATOR, width=1)

            # Icon
            icon = _load_tk_icon(obj.get("type", ""))
            if icon:
                canvas.create_image(ICON_X, mid, image=icon, anchor="center")

            # Name (left-aligned, clipped at divider)
            canvas.create_text(
                NAME_X, mid,
                text=self._clip_text(obj.get("name", ""), name_max, self._font_name),
                fill=COLOR_TEXT,
                font=("Segoe UI", 10, "bold"),
                anchor="w",
            )

            # Path (left-aligned, clipped at right edge)
            canvas.create_text(
                split_x + PAD, mid,
                text=self._clip_text(obj.get("path", ""), path_max, self._font_path),
                fill=COLOR_TEXT_DIM,
                font=("Segoe UI", 9),
                anchor="w",
            )

    def _clip_text(self, text: str, max_px: int, font) -> str:
        """Truncate text with ellipsis to fit within max_px pixels."""
        if max_px <= 0:
            return ""
        if font.measure(text) <= max_px:
            return text
        while text and font.measure(text + "…") > max_px:
            text = text[:-1]
        return (text + "…") if text else ""

    def _vlist_draw_header(self):
        hdr = self._vlist_header
        hdr.delete("all")
        cw = max(hdr.winfo_width(), 1)
        ch = max(hdr.winfo_height(), 1)
        split_x = int(cw * self._vlist_col_split)
        PAD = 8
        NAME_X = 28

        hdr.create_rectangle(0, 0, cw, ch, fill=COLOR_BG_DARK, outline="")
        hdr.create_text(NAME_X, ch // 2, text="Object Name",
            fill=COLOR_TEXT_DIM, font=("Segoe UI", 9), anchor="w")
        hdr.create_text(split_x + PAD, ch // 2, text="Path",
            fill=COLOR_TEXT_DIM, font=("Segoe UI", 9), anchor="w")
        hdr.create_line(split_x, 0, split_x, ch, fill=COLOR_SEPARATOR, width=1)
        hdr.create_line(0, ch - 1, cw, ch - 1, fill=COLOR_SEPARATOR, width=1)

    _DIVIDER_HIT = 5  # px tolerance for grabbing divider

    def _near_divider(self, canvas, event_x: int) -> bool:
        cw = max(canvas.winfo_width(), 1)
        return abs(event_x - int(cw * self._vlist_col_split)) <= self._DIVIDER_HIT

    def _vlist_hdr_motion(self, event):
        cursor = "sb_h_double_arrow" if self._near_divider(self._vlist_header, event.x) else ""
        self._vlist_header.configure(cursor=cursor)

    def _vlist_hdr_press(self, event):
        if self._near_divider(self._vlist_header, event.x):
            self._vlist_dragging = True

    def _vlist_hdr_drag(self, event):
        if not self._vlist_dragging:
            return
        # Use header width for fraction calculation regardless of which canvas fires
        cw = max(self._vlist_header.winfo_width(), 1)
        self._vlist_col_split = max(0.15, min(0.85, event.x / cw))
        self._vlist_draw_header()
        self._vlist_draw()

    def _vlist_hdr_release(self, event):
        self._vlist_dragging = False
        self._vlist_header.configure(cursor="")

    def _vlist_row_at(self, event_y: int) -> int:
        y = self._vlist_canvas.canvasy(event_y)
        i = int(y / self._vlist_row_h)
        return i if 0 <= i < len(self._vlist_items) else -1

    def _vlist_on_wheel(self, event):
        self._vlist_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self._vlist_draw()

    def _vlist_on_motion(self, event):
        if self._vlist_dragging:
            return
        # Change cursor when near divider
        near = self._near_divider(self._vlist_canvas, event.x)
        self._vlist_canvas.configure(cursor="sb_h_double_arrow" if near else "")
        row = self._vlist_row_at(event.y)
        if row == self._vlist_hover:
            return
        canvas = self._vlist_canvas
        old = self._vlist_hover
        self._vlist_hover = row
        # Update only the two affected rows' backgrounds
        cw = max(canvas.winfo_width(), 1)
        for i in (old, row):
            if i < 0 or i >= len(self._vlist_items):
                continue
            if i == self._vlist_selected:
                bg = COLOR_VLIST_SEL
            elif i == self._vlist_hover:
                bg = COLOR_ACCENT
            elif i % 2 == 0:
                bg = COLOR_BG_DARK
            else:
                bg = COLOR_BG_MID
            canvas.itemconfig(f"bg{i}", fill=bg)

    def _vlist_on_leave(self, event):
        if self._vlist_hover == -1:
            return
        old = self._vlist_hover
        self._vlist_hover = -1
        if 0 <= old < len(self._vlist_items):
            if old == self._vlist_selected:
                bg = COLOR_VLIST_SEL
            else:
                bg = COLOR_BG_DARK if old % 2 == 0 else COLOR_BG_MID
            self._vlist_canvas.itemconfig(f"bg{old}", fill=bg)

    def _vlist_on_click(self, event):
        if self._near_divider(self._vlist_canvas, event.x):
            self._vlist_dragging = True
            return
        row = self._vlist_row_at(event.y)
        if row < 0:
            return
        canvas = self._vlist_canvas
        cw = max(canvas.winfo_width(), 1)

        # Deselect previous
        old_sel = self._vlist_selected
        self._vlist_selected = row

        for i in (old_sel, row):
            if i < 0 or i >= len(self._vlist_items):
                continue
            if i == self._vlist_selected:
                bg = COLOR_VLIST_SEL
            elif i == self._vlist_hover:
                bg = COLOR_ACCENT
            elif i % 2 == 0:
                bg = COLOR_BG_DARK
            else:
                bg = COLOR_BG_MID
            canvas.itemconfig(f"bg{i}", fill=bg)

        obj_id = self._vlist_items[row].get("id", "")
        client = get_client()
        if client.is_connected():
            threading.Thread(
                target=client.reveal_in_project_explorer,
                args=(obj_id,),
                daemon=True,
            ).start()

    def on_close(self):
        client = get_client()
        if client.is_connected():
            client.disconnect()
        self.destroy()
