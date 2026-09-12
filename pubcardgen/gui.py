"""Desktop front end: python -m pubcardgen.gui"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tkinter import filedialog, ttk

from .__main__ import main as run_generator

PAGE_BG = "#eef1f7"
CARD_BG = "#ffffff"
BORDER = "#dde2ec"
TEXT = "#1f2933"
MUTED = "#6b7280"
ACCENT = "#2f6feb"
ACCENT_ACTIVE = "#2558c0"
ACCENT_DISABLED = "#a9bde6"
CONSOLE_BG = "#141a24"
CONSOLE_FG = "#dbe1ea"
CONSOLE_ERROR = "#ff9c8a"
CONSOLE_NOTE = "#8ab4ff"

WORKBOOK_TYPES = [("Excel workbooks", "*.xlsm *.xlsx"), ("All files", "*.*")]
PDF_TYPES = [("PDF files", "*.pdf"), ("All files", "*.*")]

# Stops on the baptism range sliders, in months.
BAPTISM_STEPS: tuple[tuple[int, str], ...] = (
    (9, "9 months"),
    (12, "12 months"),
    (18, "1.5 years"),
    (24, "2 years"),
)


class _Stream:
    """File-like object that hands whatever is written to the UI thread."""

    def __init__(self, sink: queue.Queue, kind: str) -> None:
        self._sink = sink
        self._kind = kind

    def write(self, text: str) -> int:
        if text:
            self._sink.put((self._kind, text))
        return len(text)

    def flush(self) -> None:
        return None


def _reveal(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - opening the user's own output folder
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def _home_dir() -> Path:
    """Where the user keeps their files: beside the executable when frozen, else the cwd."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


class RangeSlider(tk.Canvas):
    """One track carrying a low and a high handle that snap to the labelled stops."""

    HEIGHT = 56
    PAD = 30
    TRACK_Y = 18
    RADIUS = 9
    TRACK_WIDTH = 6

    def __init__(self, parent, stops, low: int = 0, high: int = 1, on_change=None) -> None:
        super().__init__(
            parent, height=self.HEIGHT, background=CARD_BG, highlightthickness=0, borderwidth=0
        )
        self._stops = stops
        self._low = low
        self._high = high
        self._on_change = on_change
        self._enabled = True
        self._dragging: str | None = None

        self.bind("<Configure>", lambda _event: self._redraw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._move)
        self.bind("<ButtonRelease-1>", self._release)

    def values(self) -> tuple[int, int]:
        return self._stops[self._low][0], self._stops[self._high][0]

    def labels(self) -> tuple[str, str]:
        return self._stops[self._low][1], self._stops[self._high][1]

    def set_indices(self, low: int, high: int) -> None:
        last = len(self._stops) - 1
        self._low = max(0, min(last - 1, low))
        self._high = max(self._low + 1, min(last, high))
        self._redraw()
        if self._on_change:
            self._on_change()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "")
        self._redraw()

    def _x_for(self, index: int) -> float:
        span = max(self.winfo_width(), 2 * self.PAD) - 2 * self.PAD
        return self.PAD + span * index / (len(self._stops) - 1)

    def _index_for(self, x: float) -> int:
        return min(range(len(self._stops)), key=lambda i: abs(self._x_for(i) - x))

    def _press(self, event) -> None:
        if not self._enabled:
            return
        low_x, high_x = self._x_for(self._low), self._x_for(self._high)
        self._dragging = "low" if abs(event.x - low_x) <= abs(event.x - high_x) else "high"
        self._move(event)

    def _move(self, event) -> None:
        if not self._enabled or not self._dragging:
            return
        index = self._index_for(event.x)
        if self._dragging == "low":
            self.set_indices(min(index, self._high - 1), self._high)
        else:
            self.set_indices(self._low, max(index, self._low + 1))

    def _release(self, _event) -> None:
        self._dragging = None

    def _redraw(self) -> None:
        self.delete("all")
        active = ACCENT if self._enabled else "#c6cedd"
        rail = "#dde3ee"
        label_colour = TEXT if self._enabled else "#aab2c0"
        low_x, high_x = self._x_for(self._low), self._x_for(self._high)
        y = self.TRACK_Y

        self.create_line(self._x_for(0), y, self._x_for(len(self._stops) - 1), y,
                         fill=rail, width=self.TRACK_WIDTH, capstyle="round")
        self.create_line(low_x, y, high_x, y, fill=active,
                         width=self.TRACK_WIDTH, capstyle="round")

        for index, (_months, caption) in enumerate(self._stops):
            x = self._x_for(index)
            if index not in (self._low, self._high):
                self.create_oval(x - 2, y - 2, x + 2, y + 2, fill=rail, outline="")
            selected = index in (self._low, self._high)
            self.create_text(
                x, y + 22, text=caption, anchor="n",
                fill=label_colour if selected else MUTED,
                font=("Segoe UI Semibold" if selected else "Segoe UI", 8),
            )

        for x in (low_x, high_x):
            self.create_oval(
                x - self.RADIUS, y - self.RADIUS, x + self.RADIUS, y + self.RADIUS,
                fill="#ffffff", outline=active, width=3,
            )


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Publisher Record Cards")
        self.configure(bg=PAGE_BG)
        self.minsize(780, 740)

        self.current_workbook = tk.StringVar()
        self.previous_workbook = tk.StringVar()
        self.template = tk.StringVar(value=str(self._default_template()))
        self.out_dir = tk.StringVar(value=str(_home_dir() / "output"))
        self.print_credit_overflow = tk.BooleanVar(value=True)
        self.list_unbaptized = tk.BooleanVar(value=False)
        self.baptism_reminder = tk.BooleanVar(value=False)

        self._messages: queue.Queue = queue.Queue()
        self._busy = False

        self._build_styles()
        self._build_widgets()
        self._pump()

    @staticmethod
    def _default_template() -> Path:
        root = _home_dir()
        for candidate in (root / "S-21_E.pdf", root / "input" / "S-21_E.pdf"):
            if candidate.is_file():
                return candidate
        return root / "S-21_E.pdf"

    def _build_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Page.TFrame", background=PAGE_BG)
        style.configure("Card.TFrame", background=CARD_BG)
        style.configure("Title.TLabel", background=PAGE_BG, foreground=TEXT,
                        font=("Segoe UI Semibold", 19))
        style.configure("Subtitle.TLabel", background=PAGE_BG, foreground=MUTED,
                        font=("Segoe UI", 10))
        style.configure("Field.TLabel", background=CARD_BG, foreground=TEXT,
                        font=("Segoe UI Semibold", 9))
        style.configure("Hint.TLabel", background=CARD_BG, foreground=MUTED,
                        font=("Segoe UI", 9))
        style.configure("Status.TLabel", background=PAGE_BG, foreground=MUTED,
                        font=("Segoe UI", 9))
        style.configure(
            "Field.TEntry",
            fieldbackground="#fbfcfe",
            background="#fbfcfe",
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            foreground=TEXT,
            padding=7,
        )
        style.map("Field.TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)])
        style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                        font=("Segoe UI Semibold", 10), padding=(20, 10), borderwidth=0)
        style.map(
            "Accent.TButton",
            background=[("disabled", ACCENT_DISABLED), ("active", ACCENT_ACTIVE)],
            foreground=[("disabled", "#f0f4ff")],
        )
        style.configure("Ghost.TButton", background="#eef1f7", foreground=TEXT,
                        font=("Segoe UI", 9), padding=(14, 8), borderwidth=0)
        style.map("Ghost.TButton", background=[("active", "#dde3ee"), ("disabled", "#f4f6fb")])
        style.configure("Browse.TButton", background="#f1f4f9", foreground=TEXT,
                        font=("Segoe UI", 9), padding=(14, 6), borderwidth=0)
        style.map("Browse.TButton", background=[("active", "#e2e8f2")])
        style.configure("Toggle.TCheckbutton", background=CARD_BG, foreground=TEXT,
                        font=("Segoe UI", 10), focuscolor=CARD_BG)
        style.map("Toggle.TCheckbutton", background=[("active", CARD_BG)])
        style.configure("Thin.Horizontal.TProgressbar", background=ACCENT,
                        troughcolor="#dde3ee", borderwidth=0, thickness=6)

    def _build_widgets(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = ttk.Frame(self, style="Page.TFrame", padding=(24, 20, 24, 6))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Publisher Record Cards", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Generate S-21 cards and congregation summaries from the field report workbooks.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        form = ttk.Frame(self, style="Card.TFrame", padding=20)
        form.grid(row=1, column=0, sticky="ew", padx=24, pady=(10, 0))
        form.columnconfigure(1, weight=1)

        self._file_row(form, 0, "Current service year workbook", self.current_workbook,
                       lambda: self._pick_file(self.current_workbook, WORKBOOK_TYPES))
        self._file_row(form, 1, "Previous service year workbook  (optional)",
                       self.previous_workbook,
                       lambda: self._pick_file(self.previous_workbook, WORKBOOK_TYPES))
        self._file_row(form, 2, "Blank S-21 form", self.template,
                       lambda: self._pick_file(self.template, PDF_TYPES))
        self._file_row(form, 3, "Output folder", self.out_dir, self._pick_folder)

        toggle = ttk.Frame(form, style="Card.TFrame")
        toggle.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(18, 0))
        ttk.Checkbutton(
            toggle,
            text="Print credit overflow on cards",
            variable=self.print_credit_overflow,
            style="Toggle.TCheckbutton",
        ).pack(anchor="w")
        ttk.Label(
            toggle,
            text="When off, the total row shows only the total including credit.",
            style="Hint.TLabel",
        ).pack(anchor="w", padx=(24, 0))
        ttk.Checkbutton(
            toggle,
            text="List unbaptized publishers",
            variable=self.list_unbaptized,
            style="Toggle.TCheckbutton",
        ).pack(anchor="w", pady=(10, 0))
        ttk.Checkbutton(
            toggle,
            text="1 year reminder after baptism",
            variable=self.baptism_reminder,
            command=self._sync_reminder,
            style="Toggle.TCheckbutton",
        ).pack(anchor="w", pady=(10, 0))

        sliders = ttk.Frame(toggle, style="Card.TFrame")
        sliders.pack(anchor="w", fill="x", padx=(24, 24), pady=(2, 0))
        self.range_caption = ttk.Label(sliders, text="", style="Hint.TLabel")
        self.range_caption.pack(anchor="w")
        self.range_slider = RangeSlider(
            sliders, BAPTISM_STEPS, low=0, high=2, on_change=self._refresh_reminder
        )
        self.range_slider.pack(fill="x")
        self._refresh_reminder()
        self._sync_reminder()

        actions = ttk.Frame(form, style="Card.TFrame")
        actions.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(18, 0))
        self.generate_button = ttk.Button(
            actions, text="Generate cards", style="Accent.TButton", command=self._start
        )
        self.generate_button.pack(side="left")
        self.open_button = ttk.Button(
            actions, text="Open output folder", style="Ghost.TButton",
            command=self._open_output, state="disabled",
        )
        self.open_button.pack(side="left", padx=(10, 0))
        self.status = ttk.Label(actions, text="", style="Hint.TLabel")
        self.status.pack(side="left", padx=(14, 0))

        log_frame = ttk.Frame(self, style="Page.TFrame", padding=(24, 14, 24, 20))
        log_frame.grid(row=2, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(2, weight=1)

        self.progress = ttk.Progressbar(
            log_frame, mode="determinate", value=0, style="Thin.Horizontal.TProgressbar"
        )
        self.progress.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self.progress_label = ttk.Label(log_frame, text="", style="Status.TLabel")
        self.progress_label.grid(row=1, column=0, sticky="w", pady=(0, 8))

        self.log = tk.Text(
            log_frame, height=12, wrap="word", relief="flat", padx=14, pady=12,
            background=CONSOLE_BG, foreground=CONSOLE_FG, insertbackground=CONSOLE_FG,
            font=("Cascadia Mono", 9), state="disabled",
        )
        self.log.grid(row=2, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, command=self.log.yview)
        scrollbar.grid(row=2, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.tag_configure("err", foreground=CONSOLE_ERROR)
        self.log.tag_configure("note", foreground=CONSOLE_NOTE)

    def _file_row(self, parent, row: int, label: str, variable: tk.StringVar, command) -> None:
        caption, controls = row * 2, row * 2 + 1
        ttk.Label(parent, text=label, style="Field.TLabel").grid(
            row=caption, column=0, columnspan=3, sticky="w", pady=(0 if row == 0 else 14, 4)
        )
        ttk.Entry(parent, textvariable=variable, style="Field.TEntry").grid(
            row=controls, column=0, columnspan=2, sticky="ew"
        )
        ttk.Button(parent, text="Browse", style="Browse.TButton", command=command).grid(
            row=controls, column=2, sticky="e", padx=(10, 0)
        )

    def _refresh_reminder(self) -> None:
        low, high = self.range_slider.labels()
        self.range_caption.configure(text=f"Baptized more than {low} ago and less than {high} ago")

    def _reminder_months(self) -> tuple[int, int]:
        return self.range_slider.values()

    def _sync_reminder(self) -> None:
        enabled = self.baptism_reminder.get()
        self.range_slider.set_enabled(enabled)
        self.range_caption.configure(style="Field.TLabel" if enabled else "Hint.TLabel")

    def _initial_dir(self) -> str:
        for value in (self.current_workbook.get(), self.out_dir.get()):
            if value:
                folder = Path(value).expanduser()
                folder = folder if folder.is_dir() else folder.parent
                if folder.is_dir():
                    return str(folder)
        return str(_home_dir())

    def _pick_file(self, variable: tk.StringVar, filetypes) -> None:
        chosen = filedialog.askopenfilename(
            parent=self, title="Select a file", initialdir=self._initial_dir(), filetypes=filetypes
        )
        if chosen:
            variable.set(str(Path(chosen)))

    def _pick_folder(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self, title="Select the output folder", initialdir=self._initial_dir()
        )
        if chosen:
            self.out_dir.set(str(Path(chosen)))

    def _append(self, text: str, tag: str = "") -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text, tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def _argv(self) -> list[str]:
        argv = [
            "--current_workbook", self.current_workbook.get().strip(),
            "--template", self.template.get().strip(),
            "--out", self.out_dir.get().strip(),
        ]
        previous = self.previous_workbook.get().strip()
        if previous:
            argv += ["--previous_workbook", previous]
        if not self.print_credit_overflow.get():
            argv.append("--no_credit_overflow")
        if self.list_unbaptized.get():
            argv.append("--list_unbaptized")
        if self.baptism_reminder.get():
            low, high = self._reminder_months()
            argv += ["--baptism_reminder", str(low), str(high)]
        return argv

    def _start(self) -> None:
        if self._busy:
            return
        missing = [
            name
            for name, value in (
                ("current service year workbook", self.current_workbook.get().strip()),
                ("blank S-21 form", self.template.get().strip()),
                ("output folder", self.out_dir.get().strip()),
            )
            if not value
        ]
        if missing:
            self._append(f"Choose the {', '.join(missing)} first.\n", "err")
            return

        self._busy = True
        self.generate_button.configure(state="disabled", text="Generating\u2026")
        self.open_button.configure(state="disabled")
        self.status.configure(text="Working, this takes a moment for a full congregation.")
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(12)
        self.progress_label.configure(text="Starting\u2026")
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

        threading.Thread(target=self._work, args=(self._argv(),), daemon=True).start()

    def _work(self, argv: list[str]) -> None:
        def progress(done: int, total: int, label: str) -> None:
            self._messages.put(("progress", (done, total, label)))

        try:
            with redirect_stdout(_Stream(self._messages, "out")), \
                    redirect_stderr(_Stream(self._messages, "err")):
                code = run_generator(argv, progress=progress)
        except Exception as error:  # surfaced in the log rather than a silent thread death
            self._messages.put(("err", f"error: {error}\n"))
            code = 1
        self._messages.put(("done", code))

    def _pump(self) -> None:
        while True:
            try:
                kind, payload = self._messages.get_nowait()
            except queue.Empty:
                break
            if kind == "done":
                self._finish(int(payload))
            elif kind == "progress":
                self._show_progress(*payload)
            else:
                self._append(str(payload), "err" if kind == "err" else "")
        self.after(80, self._pump)

    def _show_progress(self, done: int, total: int, label: str) -> None:
        if total <= 0:
            if self.progress["mode"] != "indeterminate":
                self.progress.configure(mode="indeterminate")
                self.progress.start(12)
            self.progress_label.configure(text=label)
            return

        if self.progress["mode"] != "determinate":
            self.progress.stop()
            self.progress.configure(mode="determinate")
        self.progress.configure(maximum=total, value=done)
        percent = round(done * 100 / total)
        self.progress_label.configure(text=f"{percent}%  \u00b7  {done} of {total}  \u00b7  {label}")

    def _finish(self, code: int) -> None:
        self._busy = False
        self.progress.stop()
        self.generate_button.configure(state="normal", text="Generate cards")
        if code == 0:
            self.progress.configure(mode="determinate", value=self.progress["maximum"])
            self.progress_label.configure(text="100%  \u00b7  complete")
            self.status.configure(text="Finished.")
            self.open_button.configure(state="normal")
            self._append("\nDone.\n", "note")
        else:
            self.progress.configure(mode="determinate", value=0)
            self.progress_label.configure(text="Stopped")
            self.status.configure(text="Finished with errors.")
            self._append("\nNothing was generated.\n", "err")

    def _open_output(self) -> None:
        folder = Path(self.out_dir.get().strip()).expanduser()
        if folder.is_dir():
            _reveal(folder)
        else:
            self._append(f"error: no such folder: {folder}\n", "err")


def main() -> int:
    App().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
