"""Редактор команд учебного манипулятора Робоник."""
import json
import os
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox, ttk

ROOT = Path(__file__).resolve().parent
JOINTS = ("Основание", "Плечо", "Локоть", "Захват")
LED = "Светодиод"
PAUSE = "Пауза"
LIGHT = ("Включить", "Выключить", "Мигнуть 1 раз", "Мигнуть 5 раз", "Мигнуть 10 раз")
BG, PAPER, INK, MUTED, NAVY, TEAL = "#f4f5f2", "#ffffff", "#192c34", "#50656a", "#182d34", "#006d64"
FONT = "Helvetica"


EXAMPLE = [(JOINTS[0], 45), (JOINTS[1], 70), (JOINTS[2], 90), (JOINTS[3], 50),
           (PAUSE, 1), (JOINTS[0], 110), (JOINTS[3], 85), (LED, LIGHT[2])]
DATA = (Path.home() / "Library" / "Application Support" if sys.platform == "darwin"
        else Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")) / "RobonikStudio"
DRAFT = DATA / "draft.json"


def save_steps(path, steps):
    payload = {"format": "robonik-1", "steps": steps}
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        name = tmp.name
        try:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
        except BaseException:
            tmp.close()
            Path(name).unlink(missing_ok=True)
            raise
    try:
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def load_steps(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("format") != "robonik-1" or not isinstance(data.get("steps"), list):
        raise ValueError("Неизвестный формат программы.")
    steps = []
    for item in data["steps"]:
        if not isinstance(item, list) or len(item) != 2 or type(item[1]) not in (str, int):
            raise ValueError("Некорректная команда в файле.")
        steps.append(validate_step(*item))
    return steps


def describe(step):
    part, value = step
    if part == LED:
        return value
    return f"{value} с" if part == PAUSE else f"{value}°"


def validate_step(part, value):
    if part == LED and value in LIGHT:
        return part, value
    if part in (*JOINTS, PAUSE):
        number = int(value)
        low, high = (1, 60) if part == PAUSE else (0, 180)
        if low <= number <= high:
            return part, number
    raise ValueError("Проверьте параметры команды.")


def execute(steps, board, wiring, stop, notify):
    angles = {}
    for index, (part, value) in enumerate(steps):
        if stop.is_set():
            break
        notify(index, f"{part} · {describe((part, value))}")
        if part == PAUSE:
            stop.wait(value)
        elif part in JOINTS:
            if board:
                pin, low, high = wiring[part]
                if not low <= value <= high:
                    raise ValueError(f"{part}: угол вне настроенного диапазона.")
                if pin in angles:
                    previous = angles[pin]
                    direction = 1 if value > previous else -1
                    for angle in range(previous + direction, value + direction, direction):
                        if stop.is_set():
                            break
                        board.digital[pin].write(angle)
                        if stop.wait(0.05):
                            break
                else:
                    board.servo_config(pin, angle=value)
                angles[pin] = value
            stop.wait(0.75)
        else:
            output = board.digital[wiring[LED][0]] if board else None
            if output is not None:
                output.mode = 1  # Firmata OUTPUT
            if value in LIGHT[:2]:
                if output is not None:
                    output.write(int(value == LIGHT[0]))
                stop.wait(0.35)
            else:
                count = int(value.split()[1])
                for _ in range(count):
                    if stop.is_set():
                        break
                    notify(index, "Светодиод · включён")
                    if output is not None:
                        output.write(1)
                    stop.wait(0.5)
                    if output is not None:
                        output.write(0)
                    notify(index, "Светодиод · выключен")
                    stop.wait(0.5)


class Studio(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Робоник Студия")
        self.app_icon = tk.PhotoImage(file=str(ROOT / "icon.png"))
        self.iconphoto(True, self.app_icon)
        self.geometry("1020x710")
        self.minsize(980, 670)
        self.configure(bg=BG)
        self.option_add("*Font", (FONT, 12))
        startup_error = None
        try:
            self.steps = load_steps(DRAFT) if DRAFT.exists() else EXAMPLE.copy()
        except (ValueError, OSError) as exc:
            self.steps = []
            startup_error = f"Черновик не открыт: {exc}"
        self.edit_index = None
        self.board = None
        self.wiring = {}
        self.stop = threading.Event()
        self.events = Queue()
        self.busy = False
        self.closing = False
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TButton", padding=(10, 7), background=PAPER, foreground=INK)
        style.configure("Go.TButton", background=TEAL, foreground="white", padding=(18, 9))
        style.map("Go.TButton", background=[("active", "#00594f")])
        style.configure("TCombobox", padding=5)
        style.configure("Treeview", rowheight=42, font=(FONT, 13), background=PAPER,
                        fieldbackground=PAPER, foreground=INK)
        style.configure("Treeview.Heading", padding=7, background="#e4ebe7")
        style.map("Treeview", background=[("selected", "#cdebe2")],
                  foreground=[("selected", INK)])
        side = tk.Frame(self, bg=NAVY, padx=20, pady=26)
        side.pack(side="left", fill="y")
        self.label(side, "Робоник", 28, "white", True)
        self.label(side, "Студия управления", 13, "#b5cdc9")
        self.picture = tk.PhotoImage(file=str(ROOT / "manipulator.png"))
        tk.Label(side, image=self.picture, bg=NAVY, bd=0, highlightthickness=0).pack(pady=(28, 12))
        self.label(side, "Учебный манипулятор", 16, "white", True)
        self.label(side, "Arduino Uno   /   4 привода", 12, "#b5cdc9")
        self.mode = self.label(side, "●   Деморежим", 14, "#94e8cb", True, 32)
        self.connect_button = ttk.Button(side, text="Подключить Arduino…", command=self.connection)
        self.connect_button.pack(fill="x", pady=10)
        self.files = []
        for title, action in (("Открыть программу…", self.open_project),
                              ("Сохранить как…", self.save_project),
                              ("Учебный пример", self.example)):
            button = ttk.Button(side, text=title, command=action)
            button.pack(fill="x", pady=3)
            self.files.append(button)
        main = tk.Frame(self, bg=BG, padx=24, pady=25)
        main.pack(fill="both", expand=True)
        self.label(main, "Программа", 29, INK, True)
        self.label(main, "Соберите действия в порядке выполнения.", 13, MUTED)
        self.part = tk.StringVar(value=JOINTS[0])
        self.value = tk.StringVar()
        form = tk.Frame(main, bg=PAPER, padx=12, pady=12)
        form.pack(fill="x", pady=(18, 12))
        self.label(form, "Добавить команду", 15, INK, True)
        fields = tk.Frame(form, bg=PAPER)
        fields.pack(fill="x", pady=(8, 0))
        self.parts = ttk.Combobox(fields, textvariable=self.part, values=(*JOINTS, LED, PAUSE),
                                  width=13, state="readonly")
        self.parts.pack(side="left")
        self.parts.bind("<<ComboboxSelected>>", lambda _: self.parameters())
        self.param = ttk.Combobox(fields, textvariable=self.value, width=13)
        self.param.pack(side="left", padx=6)
        self.unit = tk.Label(fields, bg=PAPER, fg=MUTED)
        self.unit.pack(side="left")
        self.add_button = ttk.Button(fields, text="+ Добавить", command=self.add)
        self.add_button.pack(side="right")
        self.cancel_edit = ttk.Button(form, text="Отменить правку", command=self.end_edit)
        self.parameters()
        table = tk.Frame(main)
        table.pack(fill="both", expand=True)
        self.table = ttk.Treeview(table, columns=("order", "device", "command"), show="headings",
                                  selectmode="browse", height=5)
        for key, title, width in (("order", "Шаг", 48), ("device", "Устройство", 142),
                                  ("command", "Действие", 145)):
            self.table.heading(key, text=title, anchor="w")
            self.table.column(key, width=width, stretch=key != "order", anchor="w")
        scroll = ttk.Scrollbar(table, command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.table.pack(fill="both", expand=True)
        bar = tk.Frame(main, bg=BG)
        bar.pack(fill="x", pady=8)
        self.edits = []
        for title, action in (("↑ Выше", -1), ("↓ Ниже", 1), ("Удалить", 0)):
            btn = ttk.Button(bar, text=title, command=lambda n=action: self.change(n))
            btn.pack(side="left", padx=(0, 4))
            self.edits.append(btn)
        self.table.bind("<Double-1>", lambda event: self.edit(self.table.identify_row(event.y)))
        self.table.bind("<Return>", lambda _: self.edit_selected())
        edit_button = ttk.Button(bar, text="Изменить", command=self.edit_selected)
        edit_button.pack(side="left")
        self.edits.append(edit_button)
        self.clear = ttk.Button(bar, text="Очистить", command=self.reset)
        self.clear.pack(side="right")
        self.status = self.label(main, "Добавьте первую команду.", 13, MUTED, False, 4)
        self.run_button = ttk.Button(main, text="▶  Запустить", style="Go.TButton", command=self.run)
        self.run_button.pack(anchor="e", pady=(6, 0))
        self.refresh()
        if startup_error:
            self.status.config(text=startup_error)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(70, self.poll)

    @staticmethod
    def label(parent, text, size, color, bold=False, top=0):
        widget = tk.Label(parent, text=text, bg=parent["bg"], fg=color, anchor="w",
                          font=(FONT, size, "bold" if bold else "normal"))
        widget.pack(fill="x", pady=(top, 0))
        return widget

    def parameters(self):
        part = self.part.get()
        values = LIGHT if part == LED else ((1, 2, 5) if part == PAUSE else (0, 45, 90, 135, 180))
        self.param.configure(values=values, state="readonly" if part == LED else "normal")
        self.value.set(values[0] if part in (LED, PAUSE) else 90)
        self.unit.config(text="" if part == LED else ("сек" if part == PAUSE else "°"))

    def open_project(self):
        name = filedialog.askopenfilename(filetypes=[("Программа Робоник", "*.robonik"), ("JSON", "*.json")])
        if not name:
            return
        try:
            new_steps = load_steps(Path(name))
        except (ValueError, OSError) as exc:
            messagebox.showerror("Открытие программы", str(exc))
            return
        self.replace(new_steps)

    def save_project(self):
        name = filedialog.asksaveasfilename(defaultextension=".robonik", initialfile="Моя программа.robonik",
                                            filetypes=[("Программа Робоник", "*.robonik")])
        if name:
            try:
                save_steps(Path(name), self.steps)
                self.status.config(text=f"Сохранено · {Path(name).name}")
            except OSError as exc:
                messagebox.showerror("Сохранение программы", str(exc))

    def example(self):
        self.replace(EXAMPLE.copy())

    def replace(self, steps):
        if self.steps and self.steps != steps and not messagebox.askyesno(
                "Заменить программу?", "Текущие команды будут заменены. Продолжить?"):
            return
        self.end_edit()
        self.steps = steps
        self.commit()

    def edit_selected(self):
        selected = self.table.selection()
        if selected:
            self.edit(selected[0])

    def edit(self, row):
        if self.busy or not row:
            return
        self.edit_index = int(row)
        part, value = self.steps[self.edit_index]
        self.part.set(part)
        self.parameters()
        self.value.set(value)
        self.add_button.config(text="Применить")
        self.cancel_edit.pack(anchor="e", pady=(6, 0))

    def end_edit(self):
        self.edit_index = None
        self.cancel_edit.pack_forget()
        self.add_button.config(text="+ Добавить")

    def commit(self, selected=None):
        self.refresh(selected)
        try:
            save_steps(DRAFT, self.steps)
        except OSError as exc:
            self.status.config(text=f"Не удалось записать черновик: {exc}")

    def add(self):
        try:
            step = validate_step(self.part.get(), self.value.get())
        except ValueError:
            self.status.config(text="Введите целый угол 0–180° или паузу 1–60 с.")
            return
        index = self.edit_index
        if index is None:
            index = len(self.steps)
            self.steps.append(step)
        else:
            self.steps[index] = step
        self.end_edit()
        self.commit(index)

    def refresh(self, selected=None):
        self.table.delete(*self.table.get_children())
        for i, step in enumerate(self.steps):
            self.table.insert("", "end", iid=str(i), values=(f"{i+1:02}", step[0], describe(step)))
        if selected is not None and self.steps:
            self.table.selection_set(str(selected))
            self.table.see(str(selected))
        self.run_button.configure(state="normal" if self.steps else "disabled")
        self.status.config(text=f"Команд в программе · {len(self.steps)}" if self.steps else "Добавьте первую команду.")

    def change(self, offset):
        selection = self.table.selection()
        if not selection:
            self.status.config(text="Выберите строку программы.")
            return
        self.end_edit()
        i = int(selection[0])
        if not offset:
            self.steps.pop(i)
        elif 0 <= i + offset < len(self.steps):
            self.steps[i], self.steps[i + offset] = self.steps[i + offset], self.steps[i]
            i += offset
        self.commit(min(i, len(self.steps)-1))

    def reset(self):
        if self.steps and messagebox.askyesno("Очистить программу?", "Удалить все команды?"):
            self.end_edit()
            self.steps.clear()
            self.commit()

    def connection(self):
        if self.board:
            self.disconnect()
            return
        try:
            from serial.tools.list_ports import comports
            from pyfirmata2 import Arduino
        except ImportError:
            messagebox.showerror("Подключение", "Установите pyfirmata2 и pyserial по инструкции README.")
            return
        dialog = tk.Toplevel(self)
        dialog.title("Подключение Arduino Uno")
        dialog.transient(self)
        dialog.grab_set()
        body = ttk.Frame(dialog, padding=18)
        body.pack()
        ttk.Label(body, text="USB-порт платы с прошивкой Firmata").grid(row=0, columnspan=4, sticky="w")
        ports = [p.device for p in comports()]
        port = ttk.Combobox(body, values=ports, width=43)
        port.grid(row=1, columnspan=4, sticky="ew", pady=6)
        if len(ports) == 1:
            port.set(ports[0])
        for col, title in enumerate(("Устройство", "Пин D", "Мин. °", "Макс. °")):
            ttk.Label(body, text=title).grid(row=2, column=col, padx=4)
        rows = {}
        for i, part in enumerate((*JOINTS, LED), 3):
            ttk.Label(body, text=part).grid(row=i, column=0, sticky="w")
            rows[part] = []
            for j in range(1 if part == LED else 3):
                field = ttk.Entry(body, width=7)
                field.grid(row=i, column=j+1, padx=3, pady=2)
                rows[part].append(field)
        info = ttk.Label(body, text="Заполните только подключённые устройства.", wraplength=365)
        info.grid(row=8, columnspan=4, pady=8)
        def attach():
            try:
                wiring = {}
                pins = set()
                for part, fields in rows.items():
                    vals = [field.get().strip() for field in fields]
                    if not any(vals):
                        continue
                    nums = tuple(map(int, vals))
                    if nums[0] not in range(2, 14) or nums[0] in pins:
                        raise ValueError
                    if part != LED and not 0 <= nums[1] <= nums[2] <= 180:
                        raise ValueError
                    wiring[part] = nums
                    pins.add(nums[0])
                device = port.get().strip()
                if not wiring or not device:
                    raise ValueError
            except ValueError:
                info.config(text="Проверьте порт, разные пины D2–D13 и границы углов каждого привода.")
                return
            dialog.destroy()
            self.lock(True)
            self.run_button.config(state="disabled")
            self.status.config(text="Подключение к плате…")
            def connect():
                board = None
                try:
                    board = Arduino(device, timeout=1)
                    if not board.get_firmata_version():
                        raise RuntimeError("Плата не подтвердила Firmata.")
                    self.events.put(("connected", board, wiring, device))
                except Exception as exc:
                    if board:
                        board.exit()
                    self.events.put(("error", str(exc)))
            threading.Thread(target=connect, daemon=True).start()
        ttk.Button(body, text="Подключить", command=attach).grid(row=9, columnspan=4)

    def disconnect(self):
        if self.board:
            try:
                self.board.exit()
            except OSError:
                pass
        self.board = None
        self.wiring = {}
        self.mode.config(text="●   Деморежим")
        self.connect_button.config(text="Подключить Arduino…")

    def lock(self, state):
        self.end_edit()
        self.busy = state
        for widget in (self.add_button, self.clear, self.connect_button, *self.files, *self.edits):
            widget.config(state="disabled" if state else "normal")
        self.run_button.config(text="■  Остановить" if state else "▶  Запустить",
                               state="normal" if state or self.steps else "disabled")

    def run(self):
        if self.busy:
            self.stop.set()
            return
        if self.board:
            for index, (part, value) in enumerate(self.steps, 1):
                if part != PAUSE and part not in self.wiring:
                    self.status.config(text=f"Шаг {index}: задайте пин устройства «{part}» при подключении.")
                    return
                if part in JOINTS and not self.wiring[part][1] <= value <= self.wiring[part][2]:
                    self.status.config(text=f"Шаг {index}: угол выходит за пределы привода «{part}».")
                    return
        self.stop.clear()
        self.lock(True)
        self.status.config(text="Выполнение…")
        def worker():
            try:
                execute(tuple(self.steps), self.board, self.wiring, self.stop,
                        lambda i, msg: self.events.put(("step", i, msg)))
                self.events.put(("done", "Остановлено" if self.stop.is_set() else "Программа выполнена"))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, *data = self.events.get_nowait()
                if kind == "step":
                    i, msg = data
                    self.table.selection_set(str(i))
                    self.table.see(str(i))
                    self.status.config(text=f"Шаг {i+1} · {msg}")
                    continue
                self.lock(False)
                if kind == "connected":
                    self.board, self.wiring, device = data
                    self.mode.config(text="●   Arduino Uno")
                    self.connect_button.config(text="Отключить Arduino")
                    self.status.config(text=f"Подключено · {device}")
                elif kind == "error":
                    self.disconnect()
                    self.status.config(text="Ошибка связи с Arduino.")
                    if not self.closing:
                        messagebox.showerror("Arduino", data[0])
                else:
                    self.status.config(text=data[0])
                if self.closing:
                    self.close()
                    return
        except Empty:
            pass
        self.after(70, self.poll)

    def close(self):
        if self.busy:
            self.closing = True
            self.stop.set()
        else:
            self.disconnect()
            self.destroy()


if __name__ == "__main__":
    Studio().mainloop()
