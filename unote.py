import sys
import subprocess
import shlex
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os


class TextTab:
    def __init__(self, title, app=None, path=None):
        self.app = app
        self.path = path
        self.modified = False

        self.frame = ttk.Frame()
        self.text = tk.Text(
            self.frame,
            wrap="none",
            undo=True,
            font=("Courier New", 11),
            padx=6,
            pady=6,
        )

        vbar = ttk.Scrollbar(self.frame, orient="vertical", command=self.text.yview)
        hbar = ttk.Scrollbar(self.frame, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)

        self.text.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        self.frame.rowconfigure(0, weight=1)
        self.frame.columnconfigure(0, weight=1)

        self.text.bind("<<Modified>>", self._on_modified)
        self.title = title
        self._refresh()

    def _on_modified(self, event):
        if self.text.edit_modified():
            self.modified = True
            self._refresh()
        self.text.edit_modified(False)

    def display_name(self):
        marker = "*" if self.modified else ""
        return f"{marker}{self.title}"

    def _refresh(self):
        if self.app is not None:
            self.app.refresh_tab(self)
        else:
            self.frame.master.title(f"{self.display_name()} - UNote")

    def set_title(self, title):
        self.title = title
        self._refresh()

    def get_content(self):
        return self.text.get("1.0", "end-1c")

    def set_content(self, content):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)
        self.text.edit_modified(False)
        self.text.edit_reset()
        self.modified = False
        self._refresh()

    def load_file(self, path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        self.set_content(content)
        self.path = path
        self.set_title(os.path.basename(path))


class UNoteApp:
    def __init__(self, root, files=None):
        self.root = root
        self.root.title("UNote")
        self.root.geometry("900x600")

        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
        if os.path.exists(icon_path):
            try:
                self.root.iconphoto(True, tk.PhotoImage(file=icon_path))
            except tk.TclError:
                pass

        self.undo_done = False
        self.tabs = []
        self.current_tab = None

        self._cvar = tk.IntVar()
        self._find_search_job = None

        self._build_menu()
        self._build_find_bar()
        self._build_notebook()

        if files:
            for path in files:
                self._open_path(path)
        else:
            self.new_tab()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_menu(self):
        menubar = tk.Menu(self.root, bg="#3c3c3c", fg="white",
                          activebackground="#505050", activeforeground="white")
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0, bg="#3c3c3c", fg="white",
                            activebackground="#505050", activeforeground="white")
        file_menu.add_command(label="New Tab", accelerator="Ctrl+N", command=self.new_tab)
        file_menu.add_command(label="Open File...", accelerator="Ctrl+O", command=self.open_file)
        file_menu.add_separator()
        file_menu.add_command(label="Open in VS Code", command=self.open_in_vscode)
        file_menu.add_command(label="Open Terminal in Folder", command=self.open_terminal)
        file_menu.add_separator()
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self.save_file)
        file_menu.add_command(label="Save As...", accelerator="Ctrl+Shift+S", command=self.save_file_as)
        file_menu.add_separator()
        file_menu.add_command(label="Close Tab", accelerator="Ctrl+W", command=self.close_tab)
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=0, bg="#3c3c3c", fg="white",
                            activebackground="#505050", activeforeground="white")
        edit_menu.add_command(label="Undo", accelerator="Ctrl+Z", command=self.undo)
        edit_menu.add_command(label="Redo", accelerator="Ctrl+Y", command=self.redo)
        edit_menu.add_separator()
        edit_menu.add_command(label="Cut", accelerator="Ctrl+X", command=lambda: self._event("cut"))
        edit_menu.add_command(label="Copy", accelerator="Ctrl+C", command=lambda: self._event("copy"))
        edit_menu.add_command(label="Paste", accelerator="Ctrl+V", command=lambda: self._event("paste"))
        edit_menu.add_command(label="Select All", accelerator="Ctrl+A", command=lambda: self._event("select_all"))
        edit_menu.add_separator()
        edit_menu.add_command(label="Find...", accelerator="Ctrl+F", command=self.show_find)
        edit_menu.add_command(label="Find Next", accelerator="Ctrl+G", command=self.find_next)
        edit_menu.add_command(label="Find Previous", accelerator="Ctrl+Shift+G", command=self.find_prev)
        menubar.add_cascade(label="Edit", menu=edit_menu)
        self.edit_menu = edit_menu

        help_menu = tk.Menu(menubar, tearoff=0, bg="#3c3c3c", fg="white",
                            activebackground="#505050", activeforeground="white")
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self._build_shortcuts()

    def _build_shortcuts(self):
        for key, action in [
            ("<Control-n>", "new_tab"),
            ("<Control-o>", "open_file"),
            ("<Control-s>", "save_file"),
            ("<Control-Shift-s>", "save_file_as"),
            ("<Control-Shift-S>", "save_file_as"),
            ("<Control-w>", "close_tab"),
            ("<Control-W>", "close_tab"),
        ]:
            self.root.bind(key, self._shortcut(action))
        self.root.bind("<Control-a>", self._shortcut("select_all"))
        self.root.bind("<Control-A>", self._shortcut("select_all"))

    def _shortcut(self, action):
        def handler(_event=None):
            if action == "select_all":
                self._event("select_all")
            else:
                getattr(self, action)()
            return "break"

        return handler

    def refresh_tab(self, tab):
        """Re-render a tab's label (with unsaved marker) and the window title."""
        if tab in self.tabs:
            index = self.tabs.index(tab)
            self.notebook.tab(index, text=tab.display_name())
        self.refresh_title()

    def refresh_title(self):
        tab = self._current()
        if tab is None:
            self.root.title("UNote")
        else:
            self.root.title(f"{tab.display_name()} - UNote")

    def show_about(self):
        messagebox.showinfo(
            "About UNote",
            "This is a python written tkinter application for opening any "
            "text related files.\n\nWritten by Theo Uys",
        )

    def _build_notebook(self):
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.grid(row=1, column=0, sticky="nsew")
        self.notebook.bind("<Button-3>", self._tab_context_menu)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _build_find_bar(self):
        bar = ttk.Frame(self.root, padding=(6, 3))
        self._find_bar = bar
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_remove()
        ttk.Label(bar, text="Find:").pack(side="left", padx=(4, 4))
        self._find_var = tk.StringVar()
        entry = ttk.Entry(bar, width=32, textvariable=self._find_var)
        entry.pack(side="left", ipady=1)
        self._find_entry = entry
        ttk.Button(bar, text="Prev", width=5,
                   command=self.find_prev).pack(side="left", padx=(6, 2))
        ttk.Button(bar, text="Next", width=5,
                   command=self.find_next).pack(side="left", padx=2)
        self._find_case = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Match case", variable=self._find_case,
                        command=self._reapply_search).pack(side="left", padx=(10, 0))
        self._find_count = ttk.Label(bar, text="")
        self._find_count.pack(side="left", padx=(12, 0))
        ttk.Button(bar, text="Close",
                   command=self.hide_find).pack(side="right", padx=(10, 4))

        self._find_var.trace_add("write", self._on_find_typed)
        entry.bind("<Return>", lambda e: self.find_next())
        entry.bind("<Shift-Return>", lambda e: self.find_prev())
        entry.bind("<Down>", lambda e: self.find_next())
        entry.bind("<Up>", lambda e: self.find_prev())
        entry.bind("<Escape>", lambda e: self.hide_find())

        self.root.bind("<Control-f>", lambda e: self.show_find())
        self.root.bind("<Control-F>", lambda e: self.show_find())
        self.root.bind("<Control-g>", lambda e: self.find_next())
        self.root.bind("<Control-G>", lambda e: self.find_next())
        self.root.bind("<Control-Shift-g>", lambda e: self.find_prev())
        self.root.bind("<Control-Shift-G>", lambda e: self.find_prev())

    def _current(self):
        if not self.tabs:
            return None
        index = self.notebook.index("current")
        if index >= len(self.tabs):
            return None
        return self.tabs[index]

    def new_tab(self):
        tab = TextTab("Untitled", app=self)
        tab.frame.master = self.root
        self.tabs.append(tab)
        self.notebook.add(tab.frame, text=tab.display_name())
        self.notebook.select(tab.frame)
        self.current_tab = tab
        tab.text.focus_set()
        self.refresh_title()
        return tab

    def open_in_vscode(self):
        tab = self._current()
        if tab is None:
            return
        if not tab.path or not os.path.exists(tab.path):
            messagebox.showinfo(
                "Open in VS Code",
                "This tab has no file on disk yet.\nSave it first, then try again.",
            )
            return
        if tab.modified:
            answer = messagebox.askyesnocancel(
                "UNote",
                f'"{tab.title}" has unsaved changes.\nSave before opening in VS Code?',
            )
            if answer is None:
                return
            if answer and not self.save_file():
                return
        subprocess.Popen(["code", tab.path])

    def _find_terminal(self):
        terminals = {
            "ptyxis": None,
            "xfce4-terminal": ["--working-directory"],
            "gnome-terminal": None,
            "konsole": ["--workdir"],
            "kitty": ["--directory"],
            "alacritty": ["--working-directory"],
            "tilix": ["--working-directory"],
            "xterm": [],
        }
        for name, opt in terminals.items():
            if shutil.which(name):
                return name, opt
        return None, None

    def open_terminal(self):
        tab = self._current()
        if tab is None:
            return
        if not tab.path or not os.path.exists(tab.path):
            messagebox.showinfo(
                "Open Terminal",
                "This tab has no file on disk yet.\nSave it first, then try again.",
            )
            return
        folder = os.path.dirname(tab.path)
        name, opt = self._find_terminal()
        if not name:
            messagebox.showerror("Open Terminal", "No supported terminal emulator found.")
            return
        if opt is None:
            # Terminals such as ptyxis / gnome-terminal that take a trailing
            # command (modern gnome-terminal dropped --working-directory).
            subprocess.Popen(
                [name, "--", "bash", "-c",
                 f'cd {shlex.quote(folder)} && exec bash'])
        elif opt:
            subprocess.Popen([name] + opt + [folder])
        else:
            subprocess.Popen(
                [name, "-e", "bash", "-c",
                 f'cd {shlex.quote(folder)} && exec bash'])

    def open_file(self):
        path = filedialog.askopenfilename(title="Open file")
        if not path:
            return
        self._open_path(path)

    def _open_path(self, path):
        try:
            tab = self.new_tab()
            tab.load_file(path)
            self._update_tab_text(tab)
        except Exception as e:
            messagebox.showerror("Open File", f"Cannot open file:\n{e}")
            self.close_tab(tab)

    def save_file(self):
        tab = self._current()
        if tab is None:
            return
        if tab.path:
            try:
                self._write(tab.path, tab.get_content())
                tab.modified = False
                tab.text.edit_modified(False)
                self.refresh_tab(tab)
            except Exception as e:
                messagebox.showerror("Save File", f"Cannot save file:\n{e}")
        else:
            return self.save_file_as()
        return True

    def save_file_as(self):
        tab = self._current()
        if tab is None:
            return
        path = filedialog.asksaveasfilename(
            title="Save file as",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return False
        try:
            self._write(path, tab.get_content())
            tab.path = path
            tab.modified = False
            tab.text.edit_modified(False)
            tab.set_title(os.path.basename(path))
            self._update_tab_text(tab)
            return True
        except Exception as e:
            messagebox.showerror("Save File", f"Cannot save file:\n{e}")
            return False

    @staticmethod
    def _write(path, content):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def _update_tab_text(self, tab):
        self.refresh_tab(tab)

    def close_tab(self, tab=None):
        tab = tab or self._current()
        if tab is None:
            return
        if tab.modified:
            answer = messagebox.askyesnocancel(
                "UNote",
                f'"{tab.title}" has unsaved changes.\nSave before closing?',
            )
            if answer is None:
                return
            if answer:
                self.notebook.select(tab.frame)
                if not self.save_file():
                    return
        self.tabs.remove(tab)
        self.notebook.forget(tab.frame)
        tab.frame.destroy()
        self.current_tab = self._current()
        if self.tabs:
            self.current_tab.text.focus_set()
        self.refresh_title()

    def undo(self):
        tab = self._current()
        if tab:
            tab.text.event_generate("<<Undo>>")
            self._set_undo_done()

    def redo(self):
        tab = self._current()
        if tab:
            tab.text.event_generate("<<Redo>>")
            self._set_undo_done()

    def _set_undo_done(self):
        self.undo_done = True
        self.root.after(200, self._reset_undo_flag)

    def _reset_undo_flag(self):
        self.undo_done = False

    def _event(self, name):
        tab = self._current()
        if tab:
            if name == "select_all":
                tab.text.tag_add("sel", "1.0", "end")
                return "break"
            tab.text.event_generate(f"<<{name}>>")

    def _on_close(self):
        unsaved = [t for t in self.tabs if t.modified]
        if unsaved:
            answer = messagebox.askyesnocancel(
                "UNote",
                f"{len(unsaved)} tab(s) have unsaved changes.\nExit anyway?",
            )
            if answer is None:
                return
            if not answer:
                return
        self.root.destroy()

    def _tab_context_menu(self, event):
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="New Tab", command=self.new_tab)
        menu.add_command(label="Close Tab", command=self.close_tab)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # --- Find / search ------------------------------------------------

    def _find_params(self):
        needle = self._find_var.get()
        if not needle:
            return None
        return needle, not self._find_case.get()

    def show_find(self):
        self._find_bar.grid()
        self._find_entry.focus_set()
        self._find_entry.selection_range(0, "end")

    def hide_find(self):
        self._find_bar.grid_remove()
        self._find_count.config(text="")
        tab = self._current()
        if tab:
            tab.text.tag_remove("unote_find", "1.0", "end")
            tab.text.tag_remove("unote_find_sel", "1.0", "end")
            tab.text.focus_set()

    def _apply_find_tags(self, tab):
        text = tab.text
        text.tag_remove("unote_find", "1.0", "end")
        text.tag_remove("unote_find_sel", "1.0", "end")
        params = self._find_params()
        if params is None:
            self._find_count.config(text="")
            return 0
        needle, ci = params
        text.tag_configure("unote_find", background="#fff08a", foreground="black")
        text.tag_configure("unote_find_sel", background="#8fd0ff", foreground="black")
        count = 0
        pos = "1.0"
        while True:
            idx = text.search(needle, pos, stopindex="end", nocase=ci,
                              count=self._cvar)
            if not idx:
                break
            end = text.index(f"{idx}+{int(self._cvar.get())}c")
            text.tag_add("unote_find", idx, end)
            count += 1
            pos = end
        self._find_count.config(
            text=f"{count} match{'es' if count != 1 else ''}")
        return count

    def _show_match(self, tab, start, end):
        text = tab.text
        text.tag_remove("unote_find_sel", "1.0", "end")
        text.tag_add("unote_find_sel", start, end)
        text.tag_raise("unote_find_sel")
        text.mark_set("insert", start)
        text.see(start)

    def _select_first_match(self, tab, needle, ci):
        text = tab.text
        start = text.index("insert")
        idx = text.search(needle, start, stopindex="end", nocase=ci,
                          count=self._cvar)
        if not idx:
            idx = text.search(needle, "1.0", stopindex="end", nocase=ci,
                              count=self._cvar)
        if idx:
            end = text.index(f"{idx}+{int(self._cvar.get())}c")
            self._show_match(tab, idx, end)

    def _on_find_typed(self, *_args):
        if self._find_search_job:
            self.root.after_cancel(self._find_search_job)
        self._find_search_job = self.root.after(150, self._reapply_find_and_select)

    def _reapply_find_and_select(self):
        self._find_search_job = None
        tab = self._current()
        if not tab:
            return
        params = self._find_params()
        if params is None:
            self._apply_find_tags(tab)
            return
        needle, ci = params
        if self._apply_find_tags(tab):
            self._select_first_match(tab, needle, ci)

    def _reapply_search(self):
        tab = self._current()
        if tab:
            self._apply_find_tags(tab)

    def find_next(self):
        if not self._find_bar.winfo_manager():
            self.show_find()
            return
        tab = self._current()
        if not tab:
            return
        params = self._find_params()
        if params is None:
            return
        needle, ci = params
        text = tab.text
        start = text.index("insert")
        rng = text.tag_ranges("unote_find_sel")
        if len(rng) == 2:
            sel_start, sel_end = str(rng[0]), str(rng[1])
            if (text.compare("insert", ">=", sel_start)
                    and text.compare("insert", "<", sel_end)):
                start = sel_end
        idx = text.search(needle, start, stopindex="end", nocase=ci,
                          count=self._cvar)
        if not idx:
            idx = text.search(needle, "1.0", stopindex=start, nocase=ci,
                              count=self._cvar)
        if idx:
            end = text.index(f"{idx}+{int(self._cvar.get())}c")
            self._show_match(tab, idx, end)
            self._find_entry.focus_set()

    def find_prev(self):
        if not self._find_bar.winfo_manager():
            self.show_find()
            return
        tab = self._current()
        if not tab:
            return
        params = self._find_params()
        if params is None:
            return
        needle, ci = params
        text = tab.text
        result = None
        pos = "1.0"
        while True:
            idx = text.search(needle, pos, stopindex="insert", nocase=ci,
                              count=self._cvar)
            if not idx:
                break
            result = idx
            pos = text.index(f"{idx}+{int(self._cvar.get())}c")
        if result is None:
            pos = "1.0"
            while True:
                idx = text.search(needle, pos, stopindex="end", nocase=ci,
                                  count=self._cvar)
                if not idx:
                    break
                result = idx
                pos = text.index(f"{idx}+{int(self._cvar.get())}c")
        if result:
            end = text.index(f"{result}+{int(self._cvar.get())}c")
            self._show_match(tab, result, end)
            self._find_entry.focus_set()

    def _on_tab_changed(self, event=None):
        self.refresh_title()
        if self._find_bar.winfo_manager():
            tab = self._current()
            if tab:
                self._apply_find_tags(tab)


def main():
    root = tk.Tk()
    app = UNoteApp(root, files=sys.argv[1:])
    if not app.tabs:
        app.new_tab()
    root.mainloop()


if __name__ == "__main__":
    main()