"""The Tkinter front end. All the actual scan/hash/plan/copy-move logic
lives in planner.py -- this module is presentation + threading only: it
reads widget state, calls into planner as the ProgressReporter, and renders
what comes back.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import tkinter as tk
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from . import planner
from .dates import HAS_PIL, find_exiftool
from .geocoding import HAS_GEOCODER
from .models import LogTag, Operation, PlanOperation


class PhotoOrganizerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title('Photo Organizer')
        root.geometry('900x720')
        root.minsize(760, 560)

        self.input_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.operation = tk.StringVar(value=Operation.COPY.value)
        self.dry_run = tk.BooleanVar(value=True)
        self.group_by_location = tk.BooleanVar(value=False)
        self.exiftool_path = tk.StringVar(value=find_exiftool())

        self.plan: list[PlanOperation] = []
        self.log_queue: queue.Queue = queue.Queue()
        self.stop_flag = threading.Event()

        self._build_ui()
        self._drain_log_queue()
        self._log_startup_status()

    # ---- UI ----
    def _build_ui(self):
        pad = {'padx': 10, 'pady': 5}
        root = self.root

        frm = ttk.LabelFrame(root, text='Folders')
        frm.pack(fill='x', **pad)
        self._row(frm, 'Input folder', self.input_dir, self._pick_input)
        self._row(frm, 'Output folder', self.output_dir, self._pick_output)

        opts = ttk.LabelFrame(root, text='Run options')
        opts.pack(fill='x', **pad)
        row = ttk.Frame(opts); row.pack(fill='x', padx=6, pady=2)
        ttk.Label(row, text='Operation:', width=15).pack(side='left')
        ttk.Radiobutton(row, text='Copy', variable=self.operation, value=Operation.COPY.value).pack(side='left')
        ttk.Radiobutton(row, text='Move', variable=self.operation, value=Operation.MOVE.value).pack(
            side='left', padx=(10, 0))
        ttk.Checkbutton(opts, text='Dry run -- only build a plan, do not copy/move',
                        variable=self.dry_run).pack(anchor='w', padx=8, pady=2)
        chk_location = ttk.Checkbutton(
            opts, text='Group by location -- "YYYY-MM-DD City" folders for GPS-tagged photos/videos '
                       '(consecutive days at the same city are merged into one range folder)',
            variable=self.group_by_location)
        chk_location.pack(anchor='w', padx=8, pady=2)
        if not HAS_GEOCODER:
            chk_location.config(state='disabled')

        tools = ttk.LabelFrame(root, text='Tools')
        tools.pack(fill='x', **pad)
        row = ttk.Frame(tools); row.pack(fill='x', padx=6, pady=4)
        ttk.Label(row, text='exiftool path:', width=15).pack(side='left')
        ttk.Entry(row, textvariable=self.exiftool_path).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='Browse...', command=self._pick_exiftool).pack(side='left', padx=4)
        pil_note = 'Pillow available (JPEG/PNG/TIFF EXIF fallback)' if HAS_PIL else \
                    'Pillow not installed -- pip install Pillow for EXIF fallback without exiftool'
        ttk.Label(tools, text=pil_note, foreground='gray').pack(anchor='w', padx=8, pady=(0, 4))
        geocoder_note = 'reverse_geocoder available (offline location grouping)' if HAS_GEOCODER else \
                        'reverse_geocoder not installed -- pip install reverse_geocoder to enable location grouping'
        ttk.Label(tools, text=geocoder_note, foreground='gray').pack(anchor='w', padx=8, pady=(0, 4))

        btns = ttk.Frame(root); btns.pack(fill='x', **pad)
        self.analyze_btn = ttk.Button(btns, text='  Analyze / Plan  ', command=self._run_analyze)
        self.analyze_btn.pack(side='left', padx=3)
        self.apply_btn = ttk.Button(btns, text='  Apply (copy/move files)  ', command=self._run_apply,
                                     state='disabled')
        self.apply_btn.pack(side='left', padx=3)
        self.cancel_btn = ttk.Button(btns, text='  Cancel  ', command=self._cancel, state='disabled')
        self.cancel_btn.pack(side='left', padx=3)
        ttk.Button(btns, text='  Save log...  ', command=self._save_log).pack(side='right', padx=3)
        ttk.Button(btns, text='  Save plan JSON...  ', command=self._save_plan).pack(side='right', padx=3)
        ttk.Button(btns, text='  Clear log  ', command=self._clear_log).pack(side='right', padx=3)

        self.progress = ttk.Progressbar(root, mode='determinate')
        self.progress.pack(fill='x', **pad)

        logfrm = ttk.LabelFrame(root, text='Log')
        logfrm.pack(fill='both', expand=True, **pad)
        mono = ('Consolas', 9) if os.name == 'nt' else ('Monospace', 10)
        self.log_widget = scrolledtext.ScrolledText(logfrm, wrap='word', font=mono)
        self.log_widget.pack(fill='both', expand=True)
        self.log_widget.tag_configure('h', foreground='#005dbb', font=(mono[0], mono[1], 'bold'))
        self.log_widget.tag_configure('warn', foreground='#a06000')
        self.log_widget.tag_configure('err', foreground='#b00020')
        self.log_widget.tag_configure('ok', foreground='#0a6b00')
        self.log_widget.tag_configure('dim', foreground='#666666')

        self.status = tk.StringVar(value='Ready.')
        ttk.Label(root, textvariable=self.status, relief='sunken', anchor='w').pack(fill='x', side='bottom')

    def _row(self, parent, label, var, cmd):
        row = ttk.Frame(parent); row.pack(fill='x', padx=6, pady=4)
        ttk.Label(row, text=label + ':', width=15).pack(side='left')
        ttk.Entry(row, textvariable=var).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='Browse...', command=cmd).pack(side='left', padx=4)

    # ---- ProgressReporter -- this is what planner.analyze()/apply_plan() call into ----
    def log(self, msg: str = '', tag: LogTag | None = None) -> None:
        self.log_queue.put((msg, tag))

    def set_status(self, text: str) -> None:
        self.root.after(0, self.status.set, text)

    def set_progress(self, value: int | None = None, maximum: int | None = None) -> None:
        def go():
            if maximum is not None: self.progress.config(maximum=maximum)
            if value is not None: self.progress.config(value=value)
        self.root.after(0, go)

    def should_stop(self) -> bool:
        return self.stop_flag.is_set()

    def _drain_log_queue(self):
        try:
            while True:
                msg, tag = self.log_queue.get_nowait()
                self.log_widget.insert('end', msg + '\n', tag or ())
                self.log_widget.see('end')
        except queue.Empty:
            pass
        self.root.after(80, self._drain_log_queue)

    def _log_startup_status(self):
        if self.exiftool_path.get():
            self.log(f'exiftool found: {self.exiftool_path.get()}', 'dim')
        else:
            self.log('exiftool not found -- dates will use Pillow (if installed) '
                      'then fall back to file modified time.', 'warn')

    # ---- Buttons ----
    def _pick_input(self):
        d = filedialog.askdirectory(title='Select the folder with your unsorted photos/videos')
        if d:
            self.input_dir.set(d)
            if not self.output_dir.get():
                self.output_dir.set(str(Path(d).parent / (Path(d).name + '_organized')))

    def _pick_output(self):
        d = filedialog.askdirectory(title='Select where the organized library should go')
        if d: self.output_dir.set(d)

    def _pick_exiftool(self):
        f = filedialog.askopenfilename(title='Select exiftool.exe',
                                       filetypes=[('Executable', '*.exe'), ('All', '*.*')])
        if f: self.exiftool_path.set(f)

    def _clear_log(self): self.log_widget.delete('1.0', 'end')

    def _save_log(self):
        p = filedialog.asksaveasfilename(defaultextension='.txt',
                                         filetypes=[('Text file', '*.txt'), ('All', '*.*')],
                                         initialfile=f'photo_organizer_{datetime.now():%Y%m%d_%H%M%S}.log')
        if p:
            Path(p).write_text(self.log_widget.get('1.0', 'end'), encoding='utf-8')
            messagebox.showinfo('Saved', f'Log saved to:\n{p}')

    def _save_plan(self):
        if not self.plan:
            messagebox.showinfo('No plan', 'Run "Analyze / Plan" first.'); return
        p = filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('JSON', '*.json')],
                                         initialfile=f'plan_{datetime.now():%Y%m%d_%H%M%S}.json')
        if p:
            data = [{'src': str(op.src), 'dest': str(op.dest), 'kind': op.kind.value} for op in self.plan]
            Path(p).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
            messagebox.showinfo('Saved', f'Plan saved to:\n{p}')

    def _cancel(self):
        self.stop_flag.set()
        self.log('CANCEL requested...', 'warn')

    # ---- Analyze ----
    def _run_analyze(self):
        if not self.input_dir.get():
            messagebox.showerror('Missing', 'Please pick an input folder.'); return
        if not self.output_dir.get():
            messagebox.showerror('Missing', 'Please pick an output folder.'); return
        if not Path(self.input_dir.get()).is_dir():
            messagebox.showerror('Missing', 'Input folder does not exist.'); return
        self.stop_flag.clear()
        self.plan = []
        self.analyze_btn.config(state='disabled')
        self.apply_btn.config(state='disabled')
        self.cancel_btn.config(state='normal')
        threading.Thread(target=self._analyze_thread, daemon=True).start()

    def _analyze_thread(self):
        try:
            self.plan = planner.analyze(
                in_dir=Path(self.input_dir.get()).resolve(),
                out_dir=Path(self.output_dir.get()).resolve(),
                exiftool_path=self.exiftool_path.get().strip(),
                group_by_location=self.group_by_location.get(),
                reporter=self,
            )
            if self.dry_run.get():
                self.log('DRY RUN is ON -- Apply will refuse to run.', 'warn')
                self.log('Review the plan, then untick "Dry run" and click Analyze again, then Apply.', 'warn')
            elif self.plan:
                self.log('Ready to Apply.', 'ok')
        except Exception as e:
            self.log(f'ERROR: {e}', 'err')
            self.log(traceback.format_exc(), 'err')
        finally:
            def done():
                self.analyze_btn.config(state='normal')
                self.cancel_btn.config(state='disabled')
                if self.plan: self.apply_btn.config(state='normal')
            self.root.after(0, done)

    # ---- Apply ----
    def _run_apply(self):
        if not self.plan:
            messagebox.showinfo('Nothing to do', 'Run "Analyze / Plan" first.'); return
        if self.dry_run.get():
            messagebox.showinfo('Dry run is ON', 'Dry run is enabled. Untick it, re-run Analyze, then Apply.')
            return
        operation = Operation(self.operation.get())
        if not messagebox.askyesno('Confirm',
                                   f'Really {operation.value.lower()} {len(self.plan)} files now?\n\n'
                                   'This will modify your disk.'):
            return
        self.stop_flag.clear()
        self.analyze_btn.config(state='disabled')
        self.apply_btn.config(state='disabled')
        self.cancel_btn.config(state='normal')
        threading.Thread(target=self._apply_thread, daemon=True).start()

    def _apply_thread(self):
        try:
            planner.apply_plan(
                self.plan,
                operation=Operation(self.operation.get()),
                out_dir=Path(self.output_dir.get()).resolve(),
                reporter=self,
            )
        except Exception as e:
            self.log(f'ERROR: {e}', 'err')
            self.log(traceback.format_exc(), 'err')
        finally:
            def done():
                self.analyze_btn.config(state='normal')
                self.cancel_btn.config(state='disabled')
            self.root.after(0, done)


def main():
    root = tk.Tk()
    style = ttk.Style()
    for theme in ('vista', 'clam', 'alt'):
        if theme in style.theme_names():
            try:
                style.theme_use(theme); break
            except tk.TclError:
                pass
    PhotoOrganizerApp(root)
    root.mainloop()
