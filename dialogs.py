"""Message boxes, the clipboard and the "Add server" dialog.

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
