import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os


class TextTab:
    def __init__(self, title, path=None):
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

        for key, action in [
            ("<Control-s>", "save"),
            ("<Control-o>", "open"),
            ("<Control-n>", "new"),
        ]:
            self.text.bind(key, action)

        self.text.bind("<<Modified>>", self._on_modified)
        self.title = title
        self._set_window_title()

    def _on_modified(self, event):
        if self.text.edit_modified():
            self.modified = True
            self._set_window_title()
        self.text.edit_modified(False)

    def _set_window_title(self):
        marker = "*" if self.modified else ""
        self.frame.master.title(f"{marker}{self.title} - UNote")

    def set_title(self, title):
        self.title = title
        self._set_window_title()

    def get_content(self):
        return self.text.get("1.0", "end-1c")

    def set_content(self, content):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)
        self.text.edit_modified(False)
        self.text.edit_reset()
        self.modified = False
        self._set_window_title()

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

        self._build_menu()
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
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self.save_file)
        file_menu.add_command(label="Save As...", accelerator="Ctrl+Shift+S", command=self.save_file_as)
        file_menu.add_separator()
        file_menu.add_command(label="Close Tab", command=self.close_tab)
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
        menubar.add_cascade(label="Edit", menu=edit_menu)
        self.edit_menu = edit_menu

        help_menu = tk.Menu(menubar, tearoff=0, bg="#3c3c3c", fg="white",
                            activebackground="#505050", activeforeground="white")
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

    def show_about(self):
        messagebox.showinfo(
            "About UNote",
            "This is a python written tkinter application for opening any "
            "text related files.\n\nWritten by Theo Uys",
        )

    def _build_notebook(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)
        self.notebook.bind("<Button-3>", self._tab_context_menu)

    def _current(self):
        if not self.tabs:
            return None
        index = self.notebook.index("current")
        if index >= len(self.tabs):
            return None
        return self.tabs[index]

    def new_tab(self):
        tab = TextTab("Untitled")
        tab.frame.master = self.root
        self.tabs.append(tab)
        self.notebook.add(tab.frame, text="Untitled")
        self.notebook.select(tab.frame)
        self.current_tab = tab
        tab.text.focus_set()
        return tab

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
                tab._set_window_title()
            except Exception as e:
                messagebox.showerror("Save File", f"Cannot save file:\n{e}")
        else:
            self.save_file_as()
            return True
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
        index = self.tabs.index(tab)
        self.notebook.tab(index, text=tab.title)

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


def main():
    root = tk.Tk()
    app = UNoteApp(root, files=sys.argv[1:])
    if not app.tabs:
        app.new_tab()
    root.mainloop()


if __name__ == "__main__":
    main()