"""Message boxes, the clipboard, and the "Add server" and "Favourite maps" dialogs.

All of these block until the user answers, so run them off the tray thread. The Tk functions create and
destroy their own Tk root, so any thread can run them, as long as only one runs at a time.
"""

import ctypes
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import ImageTk

APP_TITLE = "CSS ZE widget"
MB_YESNO = 0x4
MB_ICONERROR = 0x10
MB_ICONQUESTION = 0x20
MB_ICONINFORMATION = 0x40
MB_SETFOREGROUND = 0x10000
MB_TOPMOST = 0x40000
IDYES = 6


def message(text, flags=MB_ICONINFORMATION):
    # A tray app has no window to own the box, so force it to the front or it can open behind other windows.
    return ctypes.windll.user32.MessageBoxW(None, text, APP_TITLE, flags | MB_SETFOREGROUND | MB_TOPMOST)


def confirm(text):
    return message(text, MB_YESNO | MB_ICONQUESTION) == IDYES


def read_clipboard():
    """The clipboard text, or "" if it holds none."""
    root = tk.Tk()
    root.withdraw()
    try:
        return root.clipboard_get()
    except tk.TclError:  # empty, or not text
        return ""
    finally:
        root.destroy()


def _placeholder(entry, text):
    """Gray hint text over an entry while it's empty. Tk 8.6 entries have no placeholder of their own."""
    hint = tk.Label(entry, text=text, font="TkTextFont", fg="SystemGrayText", bg="SystemWindow", bd=0, padx=0)
    hint.bind("<Button-1>", lambda _event: entry.focus_set())  # the hint covers the entry, so pass clicks on

    def update(new_value):
        if new_value:
            hint.place_forget()
        else:
            hint.place(x=6, rely=0.5, anchor="w")  # a little right of the text, so the caret stays visible
        return True  # accept every edit; this only watches them

    entry.configure(validate="key", validatecommand=(entry.register(update), "%P"))
    update(entry.get())


def ask_server(on_add, address="", icons=()):
    """Show the Add server dialog. on_add(address_text, name) adds the server or raises ValueError,
    which is shown to the user and keeps the dialog open. icons: PIL images for the window icon, one per size."""
    root = tk.Tk()
    root.title("Add server")
    root.resizable(False, False)
    root.attributes("-topmost", True)  # opened from the tray, so nothing else would bring it to the front
    photos = [ImageTk.PhotoImage(icon, master=root) for icon in icons]  # kept alive until the dialog closes
    if photos:
        root.iconphoto(False, *photos)

    frame = ttk.Frame(root, padding=12)
    frame.grid()
    address_entry = ttk.Entry(frame, width=40)
    address_entry.grid(row=0, column=0, pady=(0, 8))
    address_entry.insert(0, address)
    _placeholder(address_entry, "51.195.188.106:27015")
    name_entry = ttk.Entry(frame, width=40)
    name_entry.grid(row=1, column=0, pady=(0, 12))
    _placeholder(name_entry, "Name (optional)")

    def add(_event=None):
        try:
            on_add(address_entry.get(), name_entry.get().strip())
        except ValueError as e:
            messagebox.showerror("Can't add server", str(e), parent=root)
            address_entry.focus_set()
        else:
            root.destroy()

    buttons = ttk.Frame(frame)
    buttons.grid(row=2, column=0, sticky="e")
    ttk.Button(buttons, text="Add", command=add, default="active").grid(row=0, column=0, padx=(0, 6))
    ttk.Button(buttons, text="Cancel", command=root.destroy).grid(row=0, column=1)
    root.bind("<Return>", add)
    root.bind("<Escape>", lambda _event: root.destroy())

    root.eval("tk::PlaceWindow . center")
    address_entry.focus_force()
    address_entry.select_range(0, "end")
    root.mainloop()


def ask_favourites(maps, favourites, on_save, icons=()):
    """Show the Favourite maps dialog: every map in maps, with a ♥ by the ones in favourites.
    On Save, on_save(added, removed) gets the changes as sets; a ValueError it raises is shown and keeps
    the dialog open. Passing changes rather than the whole list keeps hand edits to favourites.json made meanwhile."""
    root = tk.Tk()
    root.title("Favourite maps")
    root.attributes("-topmost", True)
    photos = [ImageTk.PhotoImage(icon, master=root) for icon in icons]
    if photos:
        root.iconphoto(False, *photos)
    chosen = set(favourites)

    frame = ttk.Frame(root, padding=12)
    frame.grid(sticky="nsew")
    root.columnconfigure(0, weight=1)  # let the list grow with the window
    root.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(1, weight=1)

    search = tk.StringVar()
    search_entry = ttk.Entry(frame, textvariable=search)
    search_entry.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
    _placeholder(search_entry, "Search maps")

    tree = ttk.Treeview(frame, columns=("favourite", "map"), show="headings", height=18)
    tree.heading("favourite", command=lambda: sort("favourite"))
    tree.heading("map", anchor="w", command=lambda: sort("map"))
    tree.column("favourite", width=44, anchor="center", stretch=False)  # room for "♥ ▲"
    tree.column("map", width=340)
    scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    tree.grid(row=1, column=0, sticky="nsew")
    scrollbar.grid(row=1, column=1, sticky="ns")

    ttk.Label(frame, text="Double-click or press Space to toggle ♥. Ctrl or Shift selects several maps.",
              foreground="SystemGrayText").grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

    only_favourites = tk.BooleanVar()
    bottom = ttk.Frame(frame)
    bottom.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
    bottom.columnconfigure(1, weight=1)
    ttk.Checkbutton(bottom, text="Favourites only", variable=only_favourites).grid(row=0, column=0)
    count = ttk.Label(bottom, width=30)  # fixed, so the buttons don't shift as the text changes
    count.grid(row=0, column=1, padx=12, sticky="w")

    def show_count():
        # "12 of 878 maps" while a search or Favourites only hides some, else "878 maps".
        shown = len(tree.get_children())
        total = f"{shown} of {len(maps)} maps" if shown < len(maps) else f"{len(maps)} maps"
        count.configure(text=f"{len(chosen)} favourite{'' if len(chosen) == 1 else 's'} · {total}")

    sort_by, descending = "favourite", False  # opens with the favourites on top

    def sort(column):
        # ♥ puts favourites on top. Map sorts A-Z, and Z-A when it's clicked again.
        nonlocal sort_by, descending
        descending = column == sort_by == "map" and not descending
        sort_by = column
        fill()

    def fill(*_args):
        text = search.get().strip().lower()
        shown = sorted(maps, reverse=descending)
        if sort_by == "favourite":
            shown.sort(key=lambda name: name not in chosen)  # a stable sort, so each group stays A-Z
        tree.delete(*tree.get_children())
        for name in shown:
            if text in name and (name in chosen or not only_favourites.get()):
                tree.insert("", "end", iid=name, values=("♥" if name in chosen else "", name))
        tree.heading("favourite", text="♥ ▲" if sort_by == "favourite" else "♥")
        tree.heading("map", text=f"Map {'▼' if descending else '▲'}" if sort_by == "map" else "Map")
        show_count()

    def toggle(_event=None):
        names = tree.selection()
        if names:
            # Mixed selection: favourite them all. Already all favourites: remove them all.
            add = not all(name in chosen for name in names)
            for name in names:
                if add:
                    chosen.add(name)
                else:
                    chosen.discard(name)
                tree.set(name, "favourite", "♥" if add else "")  # the row stays, so a mistake is easy to undo
            show_count()
        return "break"  # stop Space and Enter from doing anything else

    def on_double_click(event):
        if tree.identify_region(event.x, event.y) == "cell":  # not a heading or the empty space below
            toggle()

    def to_list(_event):
        first = tree.get_children()[:1]
        if first:
            tree.focus_set()
            tree.focus(first[0])
            tree.selection_set(first[0])
        return "break"

    def save(_event=None):
        try:
            on_save(chosen - set(favourites), set(favourites) - chosen)
        except ValueError as e:
            messagebox.showerror("Can't save favourites", str(e), parent=root)
        else:
            root.destroy()

    search.trace_add("write", fill)
    only_favourites.trace_add("write", fill)
    tree.bind("<Double-1>", on_double_click)
    tree.bind("<space>", toggle)
    tree.bind("<Return>", toggle)
    search_entry.bind("<Down>", to_list)
    search_entry.bind("<Return>", to_list)
    root.bind("<Escape>", lambda _event: root.destroy())

    buttons = ttk.Frame(bottom)
    buttons.grid(row=0, column=2)
    ttk.Button(buttons, text="Save", command=save).grid(row=0, column=0, padx=(0, 6))
    ttk.Button(buttons, text="Cancel", command=root.destroy).grid(row=0, column=1)

    fill()
    root.eval("tk::PlaceWindow . center")
    search_entry.focus_force()
    root.mainloop()
