import tkinter as tk
from tkinter import ttk, messagebox
import logging
from PIL import Image, ImageTk
import cv2
import threading
import json
import os
import numpy as np

logger = logging.getLogger(__name__)

# Загрузка каналов из channels.json
CHANNELS_FILE = 'channels.json'
def load_channels():
    try:
        with open(CHANNELS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка при загрузке каналов: {e}")
        return {}

class MonitoringUI:
    def __init__(self, app):
        self.app = app
        self.root = tk.Tk()
        self.root.title("Мониторинг телеканалов")
        self.root.geometry("1200x800")  # Увеличенный размер окна
        self.channels = load_channels()
        self.channel_names = list(self.channels.keys())
        self.sidebar_visible = True
        self.selected_channels = [self.channel_names[i % len(self.channel_names)] for i in range(4)]
        self.video_labels = []
        self.comboboxes = []
        self.captures = [None]*4
        self.after_ids = [None]*4
        self.create_widgets()

    def create_widgets(self):
        # Основной контейнер
        self.container = tk.Frame(self.root)
        self.container.pack(fill="both", expand=True)

        # Sidebar (левая панель)
        self.sidebar = tk.Frame(self.container, width=320, bg="#f0f0f0")
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Main area (видеостена)
        self.main_area = tk.Frame(self.container, bg="#222")
        self.main_area.pack(side="left", fill="both", expand=True)
        self._create_video_grid()

        # Кнопка скрытия/открытия sidebar (всегда поверх main_area)
        self.toggle_btn = tk.Button(self.root, text="≡", command=self.toggle_sidebar, width=2, height=1)
        self.toggle_btn.place(x=0, y=0)

        # Вся панель управления (кнопки и статусы)
        self._create_sidebar_content()

        # Кнопка настроек в левом нижнем углу основного окна (теперь шестерёнка, такого же размера как ≡)
        self.settings_btn = tk.Button(self.root, text="⚙️", command=self.open_settings_window, width=2, height=1)
        self.settings_btn.place(relx=0.01, rely=0.97, anchor="sw")
        # Tooltip для кнопки
        self._add_tooltip(self.settings_btn, "Настройки телеканалов")

    def _create_sidebar_content(self):
        scheduler_frame = ttk.LabelFrame(self.sidebar, text="Статус планировщика", padding=10)
        scheduler_frame.pack(fill="x", padx=(30,10), pady=5)
        self.scheduler_status = ttk.Label(scheduler_frame, text="Планировщик: Активен")
        self.scheduler_status.pack(fill="x", pady=5)

        lines_frame = ttk.LabelFrame(self.sidebar, text="Мониторинг строк", padding=10)
        lines_frame.pack(fill="x", padx=10, pady=5)
        self.lines_status = ttk.Label(lines_frame, text="Состояние: Остановлен")
        self.lines_status.pack(fill="x", pady=5)
        self.lines_scheduler_status = ttk.Label(lines_frame, text="Планировщик: Ожидание")
        self.lines_scheduler_status.pack(fill="x", pady=5)
        # Кнопки в одну колонну
        self.start_lines_button = ttk.Button(lines_frame, text="Запустить мониторинг", command=self.app.start_lines_monitoring)
        self.start_lines_button.pack(fill="x", pady=2)
        self.stop_lines_button = ttk.Button(lines_frame, text="Остановить мониторинг", command=self.app.stop_lines_monitoring, state="disabled")
        self.stop_lines_button.pack(fill="x", pady=2)

        rbk_mir24_frame = ttk.LabelFrame(self.sidebar, text="RBK и MIR24", padding=10)
        rbk_mir24_frame.pack(fill="x", padx=10, pady=5)
        self.rbk_mir24_status = ttk.Label(rbk_mir24_frame, text="Состояние: Остановлен")
        self.rbk_mir24_status.pack(fill="x", pady=5)
        self.rbk_mir24_scheduler_status = ttk.Label(rbk_mir24_frame, text="Планировщик: Ожидание")
        self.rbk_mir24_scheduler_status.pack(fill="x", pady=5)
        # Кнопки RBK и MIR24 в одну колонну
        self.start_rbk_mir24_button = ttk.Button(rbk_mir24_frame, text="Запустить запись", command=self.app.start_rbk_mir24)
        self.start_rbk_mir24_button.pack(fill="x", pady=2)
        self.stop_rbk_mir24_button = ttk.Button(rbk_mir24_frame, text="Остановить запись", command=self.app.stop_rbk_mir24, state="disabled")
        self.stop_rbk_mir24_button.pack(fill="x", pady=2)
        self.check_video_button = ttk.Button(rbk_mir24_frame, text="Проверка видео", command=self.app.start_video_recognition)
        self.check_video_button.pack(fill="x", pady=2)
        self.stop_video_check_button = ttk.Button(rbk_mir24_frame, text="Остановить проверку", command=self.app.stop_video_recognition, state="disabled")
        self.stop_video_check_button.pack(fill="x", pady=2)
        self.video_check_status = ttk.Label(rbk_mir24_frame, text="Статус проверки: Ожидание")
        self.video_check_status.pack(fill="x", pady=5)
        self.send_video_tg_button = ttk.Button(rbk_mir24_frame, text="Отправить в ТГ", command=self.app.send_video_to_telegram)
        self.send_video_tg_button.pack(fill="x", pady=2)

        processing_frame = ttk.LabelFrame(self.sidebar, text="Обработка файлов", padding=10)
        processing_frame.pack(fill="x", padx=10, pady=5)
        self.processing_status = ttk.Label(processing_frame, text="Статус обработки: Ожидание")
        self.processing_status.pack(fill="x", pady=5)

        # Кнопки сохранения и отправки в одну колонну
        self.save_lines_button = ttk.Button(self.sidebar, text="Сохранить строки", command=self.app.start_save_to_csv)
        self.save_lines_button.pack(fill="x", padx=10, pady=2)
        self.send_lines_button = ttk.Button(self.sidebar, text="Отправить строки в ТГ", command=self.app.send_to_telegram)
        self.send_lines_button.pack(fill="x", padx=10, pady=2)

        self.status_label = ttk.Label(self.sidebar, text="Готов к работе")
        self.status_label.pack(side="bottom", fill="x", padx=10, pady=5)

    def _create_video_grid(self):
        grid = tk.Frame(self.main_area, bg="#222")
        grid.pack(expand=True, fill="both", padx=20, pady=20)
        self.video_labels = []
        self.comboboxes = []
        self.grid_cells = []
        for i in range(2):
            for j in range(2):
                idx = i*2 + j
                # Основной cell для видео
                cell = tk.Frame(grid, bg="#111", bd=2, relief="groove")
                cell.grid(row=i*2, column=j, padx=20, pady=(20, 2), sticky="nsew")
                grid.grid_rowconfigure(i*2, weight=3)
                grid.grid_columnconfigure(j, weight=1)
                video_label = tk.Label(cell, bg="#000")
                video_label.pack(expand=True, fill="both")
                self.video_labels.append(video_label)
                self.grid_cells.append(cell)
                # Отдельный frame для Combobox
                combo_cell = tk.Frame(grid, bg="#222", height=40, width=200)
                combo_cell.grid(row=i*2+1, column=j, padx=20, pady=(0, 20), sticky="nsew")
                grid.grid_rowconfigure(i*2+1, weight=1)
                combo = ttk.Combobox(combo_cell, values=self.channel_names, state="readonly", width=24)
                combo.set(self.selected_channels[idx])
                combo.pack(expand=True, fill="x", pady=5)
                combo.bind("<<ComboboxSelected>>", lambda e, k=idx: self.on_channel_change(k))
                self.comboboxes.append(combo)
        self.main_area.bind("<Configure>", self._on_resize)
        for idx in range(4):
            self.start_video_stream(idx)

    def _on_resize(self, event=None):
        # При изменении размера main_area обновить кадры
        for idx in range(4):
            self._force_update_frame(idx)

    def _force_update_frame(self, idx):
        # Принудительно обновить кадр для корректного ресайза
        if hasattr(self, 'captures') and self.captures[idx] is not None:
            cap = self.captures[idx]
            if cap.isOpened():
                ret, frame = cap.read()
                if not ret or frame is None:
                    frame = np.zeros((240, 400, 3), dtype=np.uint8)
                label = self.video_labels[idx]
                w = label.winfo_width()
                h = label.winfo_height()
                if w < 10 or h < 10:
                    w, h = 400, 225
                frame = cv2.resize(frame, (w, h))
                img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                imgtk = ImageTk.PhotoImage(image=img)
                label.imgtk = imgtk
                label.configure(image=imgtk)

    def toggle_sidebar(self):
        if self.sidebar_visible:
            self.sidebar.pack_forget()
            self.sidebar_visible = False
        else:
            # Удаляем sidebar и main_area из pack, чтобы порядок был правильный
            self.sidebar.pack_forget()
            self.main_area.pack_forget()
            self.sidebar.pack(side="left", fill="y")
            self.main_area.pack(side="left", fill="both", expand=True)
            self.sidebar_visible = True

    def on_channel_change(self, idx):
        # Остановить предыдущий поток
        if self.captures[idx] is not None:
            self.captures[idx].release()
            self.captures[idx] = None
        if self.after_ids[idx] is not None:
            self.video_labels[idx].after_cancel(self.after_ids[idx])
            self.after_ids[idx] = None
        self.selected_channels[idx] = self.comboboxes[idx].get()
        self.start_video_stream(idx)

    def start_video_stream(self, idx):
        # Остановить предыдущий VideoCapture
        if self.captures[idx] is not None:
            self.captures[idx].release()
            self.captures[idx] = None
        if self.after_ids[idx] is not None:
            self.video_labels[idx].after_cancel(self.after_ids[idx])
            self.after_ids[idx] = None
        channel = self.selected_channels[idx]
        url = self.channels[channel]["url"]
        self.captures[idx] = cap = cv2.VideoCapture(url)
        def update_frame():
            if cap is None or not cap.isOpened():
                frame = np.zeros((120, 200, 3), dtype=np.uint8)
            else:
                ret, frame = cap.read()
                if not ret or frame is None:
                    frame = np.zeros((120, 200, 3), dtype=np.uint8)
            label = self.video_labels[idx]
            w = label.winfo_width()
            h = label.winfo_height()
            # Минимальный размер для экономии ресурсов
            min_w, min_h = 200, 120
            if w < min_w or h < min_h:
                w, h = min_w, min_h
            frame = cv2.resize(frame, (w, h))
            img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            imgtk = ImageTk.PhotoImage(image=img)
            label.imgtk = imgtk
            label.configure(image=imgtk)
            self.after_ids[idx] = label.after(33, update_frame)  # ~30 fps
        update_frame()

    def update_lines_status(self, status):
        self.lines_status.config(text=f"Состояние: {status}")
        if status == "Запущен":
            self.start_lines_button.config(state="disabled")
            self.stop_lines_button.config(state="normal")
        else:
            self.start_lines_button.config(state="normal")
            self.stop_lines_button.config(state="disabled")
            
    def update_lines_scheduler_status(self, status):
        self.lines_scheduler_status.config(text=f"Планировщик: {status}")
            
    def update_rbk_mir24_status(self, status):
        self.rbk_mir24_status.config(text=f"Состояние: {status}")
        if status == "Запущен":
            self.start_rbk_mir24_button.config(state="disabled")
            self.stop_rbk_mir24_button.config(state="normal")
        else:
            self.start_rbk_mir24_button.config(state="normal")
            self.stop_rbk_mir24_button.config(state="disabled")
            
    def update_rbk_mir24_scheduler_status(self, status):
        self.rbk_mir24_scheduler_status.config(text=f"Планировщик: {status}")
            
    def update_processing_status(self, status):
        self.processing_status.config(text=f"Статус обработки: {status}")
            
    def update_video_check_status(self, status):
        self.video_check_status.config(text=f"Статус: {status}")
        if status == "Выполняется":
            self.check_video_button.config(state="disabled")
            self.stop_video_check_button.config(state="normal")
        else:
            self.check_video_button.config(state="normal")
            self.stop_video_check_button.config(state="disabled")
            
    def update_scheduler_status(self, status):
        self.scheduler_status.config(text=f"Планировщик: {status}")
            
    def update_status(self, message):
        self.status_label.config(text=message)
        
    def run(self):
        self.root.mainloop()
        
    def cleanup(self):
        """Очистка ресурсов при закрытии."""
        try:
            for cap in self.captures:
                if cap is not None:
                    cap.release()
            for idx, after_id in enumerate(self.after_ids):
                if after_id is not None:
                    self.video_labels[idx].after_cancel(after_id)
            if hasattr(self, 'root') and self.root:
                try:
                    self.root.quit()
                except Exception:
                    pass
                try:
                    self.root.destroy()
                except Exception:
                    pass
                self.root = None
                logger.info("Окно Tkinter успешно закрыто")
        except Exception as e:
            logger.error(f"Ошибка при закрытии окна Tkinter: {e}")

    def open_settings_window(self):
        import json
        import os
        settings_win = tk.Toplevel(self.root)
        settings_win.title("Настройки телеканалов")
        settings_win.geometry("500x350")
        settings_win.transient(self.root)
        settings_win.grab_set()

        # Загрузка каналов
        try:
            with open('channels.json', 'r', encoding='utf-8') as f:
                channels = json.load(f)
        except Exception:
            channels = {}

        channel_names = list(channels.keys())

        # Выбор канала или добавление нового
        tk.Label(settings_win, text="Выберите канал или добавьте новый:").pack(pady=5)
        channel_var = tk.StringVar()
        channel_combo = ttk.Combobox(settings_win, values=channel_names, textvariable=channel_var, state="normal")
        channel_combo.pack(fill="x", padx=20)

        # Название
        tk.Label(settings_win, text="Название телеканала:").pack(pady=(10,0))
        name_var = tk.StringVar()
        name_entry = tk.Entry(settings_win, textvariable=name_var)
        name_entry.pack(fill="x", padx=20)

        # Ссылка
        tk.Label(settings_win, text="Ссылка на видеопоток:").pack(pady=(10,0))
        url_var = tk.StringVar()
        url_entry = tk.Entry(settings_win, textvariable=url_var)
        url_entry.pack(fill="x", padx=20)

        # Crop
        tk.Label(settings_win, text="Параметры обрезки (crop=width:height:x:y):").pack(pady=(10,0))
        crop_var = tk.StringVar()
        crop_entry = tk.Entry(settings_win, textvariable=crop_var)
        crop_entry.pack(fill="x", padx=20)

        # Интервал
        tk.Label(settings_win, text="Интервал (например, 1/7):").pack(pady=(10,0))
        interval_var = tk.StringVar()
        interval_entry = tk.Entry(settings_win, textvariable=interval_var)
        interval_entry.pack(fill="x", padx=20)

        def fill_fields(event=None):
            ch = channel_var.get()
            if ch in channels:
                name_var.set(ch)
                url_var.set(channels[ch].get('url', ''))
                crop_var.set(channels[ch].get('crop', ''))
                interval_var.set(channels[ch].get('interval', ''))
            else:
                name_var.set(ch)
                url_var.set('')
                crop_var.set('')
                interval_var.set('')
        channel_combo.bind("<<ComboboxSelected>>", fill_fields)
        channel_combo.bind("<KeyRelease>", fill_fields)

        def save_channel():
            ch_name = name_var.get().strip()
            url = url_var.get().strip()
            crop = crop_var.get().strip()
            interval = interval_var.get().strip()
            if not ch_name or not url:
                tk.messagebox.showerror("Ошибка", "Название и ссылка обязательны!")
                return
            channels[ch_name] = {
                'url': url,
                'crop': crop,
                'interval': interval
            }
            try:
                with open('channels.json', 'w', encoding='utf-8') as f:
                    json.dump(channels, f, ensure_ascii=False, indent=4)
                tk.messagebox.showinfo("Успех", f"Канал '{ch_name}' сохранён.")
                settings_win.destroy()
                # Обновить список каналов в основном окне
                self.channels = channels
                self.channel_names = list(channels.keys())
                for combo in self.comboboxes:
                    combo['values'] = self.channel_names
            except Exception as e:
                tk.messagebox.showerror("Ошибка", f"Не удалось сохранить: {e}")

        save_btn = tk.Button(settings_win, text="Сохранить", command=save_channel)
        save_btn.pack(pady=15)

    def _add_tooltip(self, widget, text):
        # Простой tooltip для Tkinter
        def on_enter(event):
            self.tooltip = tk.Toplevel(widget)
            self.tooltip.wm_overrideredirect(True)
            x = widget.winfo_rootx() + 30
            y = widget.winfo_rooty() - 10
            self.tooltip.wm_geometry(f"+{x}+{y}")
            label = tk.Label(self.tooltip, text=text, background="#ffffe0", relief="solid", borderwidth=1, font=("Arial", 10))
            label.pack()
        def on_leave(event):
            if hasattr(self, 'tooltip') and self.tooltip:
                self.tooltip.destroy()
                self.tooltip = None
        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)