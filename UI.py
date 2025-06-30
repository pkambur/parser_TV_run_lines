import tkinter as tk
from tkinter import ttk, messagebox
import logging
from PIL import Image, ImageTk
import cv2
import threading
import json
import os
import numpy as np
from utils import setup_logging
import shutil
import datetime
from pathlib import Path
from config_manager import config_manager
import re
from logging.handlers import RotatingFileHandler

logger = setup_logging('ui_log.txt')

# Загрузка каналов из channels.json через config_manager
CHANNELS_FILE = Path('channels.json')
def load_channels():
    return config_manager.load_channels()

class MonitoringUI:
    """
    Класс графического интерфейса для мониторинга телеканалов.
    Управляет основным окном, виджетами, статусами и настройками.
    """
    def __init__(self, app):
        """
        Инициализация UI, создание основного окна, загрузка каналов и виджетов.
        """
        self.app = app
        self.root = tk.Tk()
        self.root.title("Мониторинг телеканалов")
        self.root.geometry("1200x800")  # Увеличенный размер окна
        self.channels = load_channels()
        self.channel_names = list(self.channels.keys())
        
        # Проверка на случай, когда каналы не загружены
        if not self.channel_names:
            error_msg = "Файл channels.json не найден или пуст. Приложение запущено без каналов."
            logger.warning(error_msg)
            messagebox.showwarning("Предупреждение", error_msg)
            # Устанавливаем пустые значения по умолчанию
            self.selected_channels = ["Нет каналов"] * 4
        else:
            self.selected_channels = [self.channel_names[i % len(self.channel_names)] for i in range(4)]
        
        self.recording_status = {name: False for name in self.channel_names}
        self.video_labels = []
        self.comboboxes = []
        self.captures = [None]*4
        self.after_ids = [None]*4
        self.play_pause_buttons = []
        self.video_stream_active = [True]*4
        self.video_frames = []  # Will store the frames that have the border
        self.sidebar_visible = True
        self.create_widgets()
        
    def create_widgets(self):
        """
        Создаёт основной контейнер, sidebar, main_area и кнопки управления.
        """
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

        # Кнопка настроек под кнопкой "≡"
        self.settings_btn = tk.Button(self.root, text="⚙️", command=self.open_settings_window, width=2, height=1)
        self.settings_btn.place(x=0, y=30)
        # Tooltip для кнопки
        self._add_tooltip(self.settings_btn, "Настройки телеканалов")

    def _create_sidebar_content(self):
        """
        Создаёт содержимое sidebar: статус планировщика, мониторинга, RBK/MIR24 и кнопки.
        """
        scheduler_frame = ttk.LabelFrame(self.sidebar, text="Статус планировщика", padding=10)
        scheduler_frame.pack(fill="x", padx=(30,10), pady=5)
        self.scheduler_status = ttk.Label(scheduler_frame, text="Планировщик: Активен")
        self.scheduler_status.pack(fill="x", pady=5)
        
        scheduler_btn_frame = ttk.Frame(scheduler_frame)
        scheduler_btn_frame.pack(fill="x", pady=5)
        self.pause_scheduler_button = ttk.Button(scheduler_btn_frame, text="Приостановить", command=self.app.pause_scheduler)
        self.pause_scheduler_button.pack(side="left", expand=True, fill="x", padx=(0, 2))
        self.resume_scheduler_button = ttk.Button(scheduler_btn_frame, text="Возобновить", command=self.app.resume_scheduler, state="disabled")
        self.resume_scheduler_button.pack(side="left", expand=True, fill="x", padx=(2, 0))
        
        lines_frame = ttk.LabelFrame(self.sidebar, text="Мониторинг строк", padding=10)
        lines_frame.pack(fill="x", padx=10, pady=5)
        self.lines_status = ttk.Label(lines_frame, text="Состояние: Остановлен")
        self.lines_status.pack(fill="x", pady=5)
        self.lines_scheduler_status = ttk.Label(lines_frame, text="Планировщик: Ожидание")
        self.lines_scheduler_status.pack(fill="x", pady=5)
        self.processing_status = ttk.Label(lines_frame, text="Статус обработки: Ожидание")
        self.processing_status.pack(fill="x", pady=5)
        # Прогресс-бар
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(lines_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill='x', padx=5, pady=5)
        self.progress_bar['value'] = 0
        self.progress_bar.pack_forget()  # Скрыть по умолчанию
        # Кнопки в одну колонну
        self.start_lines_button = ttk.Button(lines_frame, text="Запустить мониторинг", command=self.app.start_lines_monitoring)
        self.start_lines_button.pack(fill="x", pady=2)
        self.stop_lines_button = ttk.Button(lines_frame, text="Остановить мониторинг", command=self.app.stop_lines_monitoring, state="disabled")
        self.stop_lines_button.pack(fill="x", pady=2)
        self.save_and_send_lines_button = ttk.Button(lines_frame, text="Сохранить и отправить строки", command=self.app.save_and_send_lines)
        self.save_and_send_lines_button.pack(fill="x", pady=2)

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
        self.check_and_send_video_button = ttk.Button(rbk_mir24_frame, text="Проверить и отправить crop-видео", command=self.app.check_and_send_videos)
        self.check_and_send_video_button.pack(fill="x", pady=2)
        self.video_check_status = ttk.Label(rbk_mir24_frame, text="Статус проверки: Ожидание")
        self.video_check_status.pack(fill="x", pady=5)
        
        # Кнопка очистки кэша Hugging Face API
        self.clear_hf_cache_button = ttk.Button(rbk_mir24_frame, text="Очистить кэш API", command=self.app.clear_hf_cache)
        self.clear_hf_cache_button.pack(fill="x", pady=2)
        # Tooltip для кнопки очистки кэша
        self._add_tooltip(self.clear_hf_cache_button, "Очистить кэш результатов Hugging Face API")
        
        self.status_label = ttk.Label(self.sidebar, text="Готов к работе")
        self.status_label.pack(side="bottom", fill="x", padx=10, pady=5)

    def _create_video_grid(self):
        """
        Создаёт сетку для отображения видеопотоков и контролов.
        """
        grid = tk.Frame(self.main_area, bg="#222")
        grid.pack(expand=True, fill="both", padx=20, pady=20)
        self.video_labels = []
        self.comboboxes = []
        self.grid_cells = []
        self.play_pause_buttons = []
        for i in range(2):
            for j in range(2):
                idx = i*2 + j
                # Основной cell для видео
                cell = tk.Frame(grid, bg="#111", highlightbackground="#444", highlightcolor="#444", highlightthickness=2, relief="groove")
                cell.grid(row=i*2, column=j, padx=20, pady=(20, 2), sticky="nsew")
                grid.grid_rowconfigure(i*2, weight=3)
                grid.grid_columnconfigure(j, weight=1)
                video_label = tk.Label(cell, bg="#000")
                video_label.pack(expand=True, fill="both")
                self.video_labels.append(video_label)
                self.grid_cells.append(cell)

                # Frame для контролов (комбобокс и кнопка)
                control_frame = tk.Frame(grid, bg="#222")
                control_frame.grid(row=i*2+1, column=j, padx=20, pady=(0, 20), sticky="ew")

                # Combobox
                combo = ttk.Combobox(control_frame, values=self.channel_names, state="readonly")
                combo.set(self.selected_channels[idx])
                combo.pack(side="left", expand=True, fill="x", pady=5)
                combo.bind("<<ComboboxSelected>>", lambda e, k=idx: self.on_channel_change(k))
                self.comboboxes.append(combo)

                # Play/Pause кнопка
                play_pause_button = ttk.Button(control_frame, text="❚❚", command=lambda k=idx: self.toggle_video_stream(k))
                play_pause_button.pack(side="left", padx=5, pady=5)
                self.play_pause_buttons.append(play_pause_button)

        self.main_area.bind("<Configure>", self._on_resize)
        for idx in range(4):
            self.start_video_stream(idx)

    def _on_resize(self, event=None):
        """
        Обновляет кадры при изменении размера main_area.
        """
        # При изменении размера main_area обновить кадры
        for idx in range(4):
            self._force_update_frame(idx)

    def _force_update_frame(self, idx):
        """
        Принудительно обновляет кадр для корректного ресайза.
        """
        # Принудительно обновить кадр для корректного ресайза
        if hasattr(self, 'captures') and self.captures[idx] is not None:
            cap = self.captures[idx]
            if cap.isOpened():
                try:
                    ret, frame = cap.read()
                except cv2.error as e:
                    logger.error(f"OpenCV ошибка при чтении кадра из потока {idx} ({self.selected_channels[idx]}): {e}")
                    self._handle_disconnect(idx)
                    return
                    
                if not ret or frame is None:
                    logger.warning(f"Не удалось прочитать кадр из потока {idx} ({self.selected_channels[idx]}).")
                    self._handle_disconnect(idx)
                    return

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
        """
        Скрывает или показывает sidebar.
        """
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

    def _handle_disconnect(self, idx):
        """
        Обработка обрыва соединения для видеопотока.
        """
        """Обработка обрыва соединения для видеопотока."""
        # Останавливаем текущий захват, если он есть
        if self.captures[idx] is not None:
            self.captures[idx].release()
            self.captures[idx] = None
        if self.after_ids[idx] is not None:
            self.video_labels[idx].after_cancel(self.after_ids[idx])
            self.after_ids[idx] = None

        # Показываем сообщение об обрыве
        label = self.video_labels[idx]
        w = label.winfo_width()
        h = label.winfo_height()
        if w < 10 or h < 10: w, h = 400, 225
        frame = np.full((h, w, 3), 64, dtype=np.uint8)  # Серый фон
        text = "Disconnected. Reconnecting..."
        (text_width, text_height), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        text_x = (w - text_width) // 2
        text_y = (h + text_height) // 2
        cv2.putText(frame, text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        img = Image.fromarray(frame)
        imgtk = ImageTk.PhotoImage(image=img)
        label.imgtk = imgtk
        label.configure(image=imgtk)

        # Планируем переподключение, если поток должен быть активен
        if self.video_stream_active[idx]:
            logger.info(f"Попытка переподключения к потоку {idx} через 5 секунд.")
            self.root.after(5000, lambda: self.start_video_stream(idx))

    def toggle_video_stream(self, idx):
        """
        Включает/выключает видеопоток по индексу.
        """
        self.video_stream_active[idx] = not self.video_stream_active[idx]
        if self.video_stream_active[idx]:
            # Возобновляем
            self.play_pause_buttons[idx].config(text="❚❚")
            self.start_video_stream(idx)
        else:
            # Ставим на паузу
            self.play_pause_buttons[idx].config(text="▶")
            if self.after_ids[idx] is not None:
                self.video_labels[idx].after_cancel(self.after_ids[idx])
                self.after_ids[idx] = None
            if self.captures[idx] is not None:
                self.captures[idx].release()
                self.captures[idx] = None
            # Показываем черный экран с надписью Paused
            label = self.video_labels[idx]
            w = label.winfo_width()
            h = label.winfo_height()
            if w < 10 or h < 10: w, h = 400, 225
            frame = np.zeros((h, w, 3), dtype=np.uint8)
            text = "Paused"
            (text_width, text_height), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            text_x = (w - text_width) // 2
            text_y = (h + text_height) // 2
            cv2.putText(frame, text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            img = Image.fromarray(frame)
            imgtk = ImageTk.PhotoImage(image=img)
            label.imgtk = imgtk
            label.configure(image=imgtk)

    def on_channel_change(self, idx):
        """
        Обработка смены канала в combobox.
        """
        # Остановить предыдущий поток
        if self.captures[idx] is not None:
            self.captures[idx].release()
            self.captures[idx] = None
        if self.after_ids[idx] is not None:
            self.video_labels[idx].after_cancel(self.after_ids[idx])
            self.after_ids[idx] = None
        self.selected_channels[idx] = self.comboboxes[idx].get()
        new_channel = self.selected_channels[idx]

        # Update border for new channel
        is_recording = self.recording_status.get(new_channel, False)
        color = "red" if is_recording else "#444"
        if self.grid_cells[idx]:
            self.grid_cells[idx].config(highlightbackground=color, highlightcolor=color)
            
        self.video_stream_active[idx] = True # При смене канала всегда активируем поток
        self.start_video_stream(idx)

    def start_video_stream(self, idx):
        """
        Запускает видеопоток для выбранного канала.
        """
        # Если поток неактивен, не запускаем его (вызывается из toggle)
        if not self.video_stream_active[idx]:
            return
        
        # Проверка на случай, когда каналы не загружены
        if not self.channel_names or self.selected_channels[idx] == "Нет каналов":
            # Показываем сообщение о том, что каналы не загружены
            label = self.video_labels[idx]
            w = label.winfo_width()
            h = label.winfo_height()
            if w < 10 or h < 10: w, h = 400, 225
            frame = np.full((h, w, 3), 64, dtype=np.uint8)  # Серый фон
            text = "Каналы не загружены"
            (text_width, text_height), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            text_x = (w - text_width) // 2
            text_y = (h + text_height) // 2
            cv2.putText(frame, text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            img = Image.fromarray(frame)
            imgtk = ImageTk.PhotoImage(image=img)
            label.imgtk = imgtk
            label.configure(image=imgtk)
            return
        
        # Остановить предыдущий VideoCapture
        if self.captures[idx] is not None:
            self.captures[idx].release()
            self.captures[idx] = None
        if self.after_ids[idx] is not None:
            self.video_labels[idx].after_cancel(self.after_ids[idx])
            self.after_ids[idx] = None
        
        channel = self.selected_channels[idx]
        url = self.channels[channel]["url"]
        
        # Убедимся, что состояние UI верное
        self.video_stream_active[idx] = True
        if self.play_pause_buttons: # Проверка, что кнопки уже созданы
            self.play_pause_buttons[idx].config(text="❚❚")

        def _start_capture_and_loop():
            # Захват видео в этом же потоке, но с логикой переподключения
            cap = cv2.VideoCapture(url)
            self.captures[idx] = cap

            def update_frame():
                # Проверяем, не остановлен ли поток вручную
                if not self.video_stream_active[idx]:
                    return
                
                # Проверяем, жив ли сам cap
                if cap is None or not cap.isOpened():
                    logger.warning(f"Поток {idx} ({self.selected_channels[idx]}) не открыт.")
                    self._handle_disconnect(idx)
                    return

                try:
                    ret, frame = cap.read()
                except cv2.error as e:
                    logger.error(f"OpenCV ошибка при чтении кадра из потока {idx} ({self.selected_channels[idx]}): {e}")
                    self._handle_disconnect(idx)
                    return
                    
                if not ret or frame is None:
                    logger.warning(f"Не удалось прочитать кадр из потока {idx} ({self.selected_channels[idx]}).")
                    self._handle_disconnect(idx)
                    return

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
                self.after_ids[idx] = label.after(100, update_frame)  # ~10 fps
            
            update_frame()

        # Показываем "Connecting..." перед запуском
        label = self.video_labels[idx]
        w = label.winfo_width()
        h = label.winfo_height()
        if w < 10 or h < 10: w, h = 400, 225
        frame = np.full((h, w, 3), 32, dtype=np.uint8)
        text = "Connecting..."
        (text_width, text_height), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        text_x = (w - text_width) // 2
        text_y = (h + text_height) // 2
        cv2.putText(frame, text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        img = Image.fromarray(frame)
        imgtk = ImageTk.PhotoImage(image=img)
        label.imgtk = imgtk
        label.configure(image=imgtk)
        
        # Запускаем в фоновом потоке, чтобы не блокировать UI
        threading.Thread(target=_start_capture_and_loop, daemon=True).start()
        
    def update_lines_status(self, status):
        """
        Обновляет статус мониторинга строк.
        """
        self.lines_status.config(text=f"Состояние: {status}")
        if status == "Запущен":
            self.start_lines_button.config(state="disabled")
            self.stop_lines_button.config(state="normal")
        else:
            self.start_lines_button.config(state="normal")
            self.stop_lines_button.config(state="disabled")
            
    def update_lines_scheduler_status(self, status):
        """
        Обновляет статус планировщика строк.
        """
        self.lines_scheduler_status.config(text=f"Планировщик: {status}")
            
    def update_rbk_mir24_status(self, status):
        """
        Обновляет статус RBK/MIR24.
        """
        self.rbk_mir24_status.config(text=f"Состояние: {status}")
        if status == "Запущен":
            self.start_rbk_mir24_button.config(state="disabled")
            self.stop_rbk_mir24_button.config(state="normal")
        else:
            self.start_rbk_mir24_button.config(state="normal")
            self.stop_rbk_mir24_button.config(state="disabled")
            
    def update_rbk_mir24_scheduler_status(self, status):
        """
        Обновляет статус планировщика RBK/MIR24.
        """
        self.rbk_mir24_scheduler_status.config(text=f"Планировщик: {status}")
            
    def update_processing_status(self, status):
        """
        Обновляет статус обработки скриншотов.
        """
        if hasattr(self, 'processing_status') and self.processing_status is not None:
            self.processing_status.config(text=f"Статус обработки: {status}")
        if "Выполняется" in status or "Отправка" in status or "Обработка" in status:
            self.save_and_send_lines_button.config(state="disabled")
        else:
            self.save_and_send_lines_button.config(state="normal")
            
    def update_video_check_status(self, status):
        """
        Обновляет статус проверки crop-видео.
        """
        self.video_check_status.config(text=f"Статус: {status}")
        if "Выполняется" in status:
            self.check_and_send_video_button.config(state="disabled")
        else:
            self.check_and_send_video_button.config(state="normal")
            
    def update_scheduler_status(self, status):
        """
        Обновляет статус планировщика задач.
        """
        self.scheduler_status.config(text=f"Планировщик: {status}")
            
    def update_status(self, message):
        """
        Обновляет общий статус приложения.
        """
        self.status_label.config(text=message)
        
    def run(self):
        """
        Запускает главный цикл Tkinter.
        """
        self.root.mainloop()
        
    def cleanup(self):
        """
        Очистка ресурсов при закрытии UI.
        """
        try:
            # Проверяем, что captures инициализирован
            if hasattr(self, 'captures') and self.captures:
                for cap in self.captures:
                    if cap is not None:
                        cap.release()
            
            # Проверяем, что after_ids и video_labels инициализированы
            if hasattr(self, 'after_ids') and hasattr(self, 'video_labels') and self.after_ids and self.video_labels:
                for idx, after_id in enumerate(self.after_ids):
                    if after_id is not None and idx < len(self.video_labels):
                        try:
                            self.video_labels[idx].after_cancel(after_id)
                        except Exception as e:
                            logger.warning(f"Ошибка при отмене after_id {after_id}: {e}")
            
            # Закрываем root окно
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
        """
        Открывает окно настроек телеканалов с валидацией всех полей.
        """
        settings_win = tk.Toplevel(self.root)
        settings_win.title("Настройки телеканалов")
        settings_win.geometry("600x700") # Увеличим высоту для сообщений об ошибках
        settings_win.transient(self.root)
        settings_win.grab_set()

        # Добавляем скроллируемый Canvas для всего окна настроек
        settings_canvas = tk.Canvas(settings_win, borderwidth=0, background="#f8f8f8")
        settings_scrollbar = tk.Scrollbar(settings_win, orient="vertical", command=settings_canvas.yview)
        settings_canvas.configure(yscrollcommand=settings_scrollbar.set)
        settings_scrollbar.pack(side="right", fill="y")
        settings_canvas.pack(side="left", fill="both", expand=True)
        inner_frame = tk.Frame(settings_canvas, background="#f8f8f8")
        settings_canvas.create_window((0, 0), window=inner_frame, anchor="nw")
        def _on_frame_configure(event):
            settings_canvas.configure(scrollregion=settings_canvas.bbox("all"))
        inner_frame.bind("<Configure>", _on_frame_configure)
        # Для колесика мыши
        def _on_mousewheel(event):
            settings_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        settings_win.bind_all("<MouseWheel>", _on_mousewheel)

        # Загрузка каналов
        try:
            with CHANNELS_FILE.open('r', encoding='utf-8') as f:
                channels = json.load(f)
        except Exception:
            channels = {}
        channel_names = list(channels.keys())

        # 1. Объявляем все переменные
        channel_var = tk.StringVar()
        name_var = tk.StringVar()
        url_var = tk.StringVar()
        crop_var = tk.StringVar()
        interval_var = tk.StringVar()
        default_duration_var = tk.StringVar()
        special_durations_var = tk.StringVar()

        # 2. Создаем виджеты (теперь во внутреннем inner_frame)
        tk.Label(inner_frame, text="Выберите канал или добавьте новый:").pack(pady=5)
        channel_combo = ttk.Combobox(inner_frame, values=channel_names, textvariable=channel_var, state="normal")
        channel_combo.pack(fill="x", padx=20)
        # --- Общие параметры ---
        general_frame = ttk.LabelFrame(inner_frame, text="Общие параметры", padding=10)
        general_frame.pack(fill="x", padx=20, pady=5, expand=True)
        tk.Label(general_frame, text="Название телеканала:").pack(anchor="w")
        name_entry = tk.Entry(general_frame, textvariable=name_var)
        name_entry.pack(fill="x", pady=(0, 5))
        tk.Label(general_frame, text="Ссылка на видеопоток:").pack(anchor="w")
        url_entry = tk.Entry(general_frame, textvariable=url_var)
        url_entry.pack(fill="x", pady=(0, 5))
        tk.Label(general_frame, text="Параметры обрезки (crop=width:height:x:y):").pack(anchor="w")
        crop_entry = tk.Entry(general_frame, textvariable=crop_var)
        crop_entry.pack(fill="x", pady=(0, 5))
        tk.Label(general_frame, text="Интервал (например, 1/7):").pack(anchor="w")
        interval_entry = tk.Entry(general_frame, textvariable=interval_var)
        interval_entry.pack(fill="x")
        # --- Параметры длительности ---
        duration_frame = ttk.LabelFrame(inner_frame, text="Параметры длительности записи (сюжеты)", padding=10)
        duration_frame.pack(fill="x", padx=20, pady=5, expand=True)
        tk.Label(duration_frame, text="Длительность выпуска по умолчанию (мин):").pack(anchor="w")
        default_duration_entry = tk.Entry(duration_frame, textvariable=default_duration_var)
        default_duration_entry.pack(fill="x", pady=(0, 5))
        tk.Label(duration_frame, text="Особые длительности (формат: 14:00=20, 18:00=20):").pack(anchor="w")
        special_durations_entry = tk.Entry(duration_frame, textvariable=special_durations_var)
        special_durations_entry.pack(fill="x")
        # --- Расписание ---
        schedule_frame = ttk.LabelFrame(inner_frame, text="Расписание", padding=10)
        schedule_frame.pack(fill="x", padx=20, pady=5, expand=True)
        tk.Label(schedule_frame, text="Время мониторинга строк (lines, через запятую или с новой строки):").pack(anchor="w")
        lines_text = tk.Text(schedule_frame, height=3)
        lines_text.pack(fill="x")
        # --- Сообщения об ошибках ---
        error_frame = ttk.LabelFrame(inner_frame, text="Сообщения об ошибках", padding=10)
        error_frame.pack(fill="x", padx=20, pady=5, expand=True)
        error_label = tk.Label(error_frame, text="", fg="red", wraplength=550)
        error_label.pack(fill="x")
        # --- Секция конфигурации токенов и рассылки ---
        config_frame = ttk.LabelFrame(inner_frame, text="Конфигурация токенов и рассылки", padding=10)
        config_frame.pack(fill="x", padx=20, pady=5, expand=True)
        # Теперь поля всегда пустые по умолчанию
        telegram_token_var = tk.StringVar(value="")
        chat_ids_var = tk.StringVar(value="")
        hf_api_token_var = tk.StringVar(value="")
        hf_token_var = tk.StringVar(value="")
        tk.Label(config_frame, text="Telegram Bot Token:").pack(anchor="w")
        telegram_token_entry = tk.Entry(config_frame, textvariable=telegram_token_var)
        telegram_token_entry.pack(fill="x", pady=(0, 5))
        tk.Label(config_frame, text="Telegram Chat IDs (через запятую):").pack(anchor="w")
        chat_ids_entry = tk.Entry(config_frame, textvariable=chat_ids_var)
        chat_ids_entry.pack(fill="x", pady=(0, 5))
        tk.Label(config_frame, text="Hugging Face API Token:").pack(anchor="w")
        hf_api_token_entry = tk.Entry(config_frame, textvariable=hf_api_token_var)
        hf_api_token_entry.pack(fill="x", pady=(0, 5))
        tk.Label(config_frame, text="Hugging Face Token:").pack(anchor="w")
        hf_token_entry = tk.Entry(config_frame, textvariable=hf_token_var)
        hf_token_entry.pack(fill="x", pady=(0, 5))

        def clear_error():
            """Очищает сообщение об ошибке"""
            error_label.config(text="")

        def show_error(message):
            """Показывает сообщение об ошибке с защитой от XSS"""
            # Очищаем сообщение от потенциально опасных символов
            safe_message = str(message)
            
            # Удаляем HTML-теги и специальные символы
            safe_message = re.sub(r'<[^>]+>', '', safe_message)
            safe_message = safe_message.replace('&', '&amp;')
            safe_message = safe_message.replace('<', '&lt;')
            safe_message = safe_message.replace('>', '&gt;')
            safe_message = safe_message.replace('"', '&quot;')
            safe_message = safe_message.replace("'", '&#x27;')
            
            # Ограничиваем длину сообщения
            if len(safe_message) > 200:
                safe_message = safe_message[:197] + "..."
            
            error_label.config(text=f"Ошибка: {safe_message}")
            logger.warning(f"Ошибка валидации в настройках: {message}")

        def validate_channel_name(name):
            """Валидация названия канала"""
            if not name or not name.strip():
                return False, "Название канала не может быть пустым"
            
            name = name.strip()
            
            # Защита от DoS через очень длинные строки
            if len(name) > 100:
                return False, "Название канала слишком длинное (максимум 100 символов)"
            
            # Проверяем на недопустимые символы
            invalid_chars = ['<', '>', ':', '"', '|', '?', '*', '\\', '/', '\0', '\t', '\n', '\r']
            for char in invalid_chars:
                if char in name:
                    return False, f"Название канала содержит недопустимый символ: '{char}'"
            
            # Проверяем на попытки XSS
            xss_patterns = [
                r'<script', r'javascript:', r'on\w+\s*=', r'data:', r'vbscript:',
                r'<iframe', r'<object', r'<embed', r'<form', r'<input'
            ]
            for pattern in xss_patterns:
                if re.search(pattern, name, re.IGNORECASE):
                    return False, "Название канала содержит недопустимые паттерны"
            
            return True, ""

        def validate_url(url):
            """Валидация URL"""
            if not url or not url.strip():
                return False, "URL не может быть пустым"
            
            url = url.strip()
            
            # Защита от DoS через очень длинные URL
            if len(url) > 500:
                return False, "URL слишком длинный (максимум 500 символов)"
            
            # Проверяем на попытки XSS в URL
            xss_patterns = [
                r'javascript:', r'data:', r'vbscript:', r'<script', r'<iframe',
                r'on\w+\s*=', r'<object', r'<embed'
            ]
            for pattern in xss_patterns:
                if re.search(pattern, url, re.IGNORECASE):
                    return False, "URL содержит недопустимые паттерны"
            
            # Проверяем базовый формат URL
            url_pattern = re.compile(
                r'^https?://'  # http:// или https://
                r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # домен
                r'localhost|'  # localhost
                r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # IP адрес
                r'(?::\d+)?'  # порт
                r'(?:/?|[/?]\S+)$', re.IGNORECASE)
            
            if not url_pattern.match(url):
                return False, "Неверный формат URL"
            
            return True, ""

        def validate_crop(crop):
            """Валидация параметров обрезки"""
            if not crop or not crop.strip():
                return True, ""  # Пустое значение допустимо
            
            crop = crop.strip()
            if len(crop) > 100:
                return False, "Параметры обрезки слишком длинные"
            
            # Формат: width:height:x:y (все числа)
            crop_pattern = re.compile(r'^\d+:\d+:\d+:\d+$')
            if not crop_pattern.match(crop):
                return False, "Неверный формат обрезки. Используйте: ширина:высота:x:y"
            
            # Проверяем, что числа разумные
            parts = crop.split(':')
            width, height, x, y = map(int, parts)
            
            if width <= 0 or height <= 0:
                return False, "Ширина и высота должны быть больше 0"
            
            if width > 10000 or height > 10000:
                return False, "Размеры обрезки слишком большие (максимум 10000x10000)"
            
            if x < 0 or y < 0:
                return False, "Координаты x и y должны быть неотрицательными"
            
            return True, ""

        def validate_interval(interval):
            """Валидация интервала"""
            if not interval or not interval.strip():
                return True, ""  # Пустое значение допустимо
            
            interval = interval.strip()
            if len(interval) > 50:
                return False, "Интервал слишком длинный"
            
            # Формат: число/число (например, 1/7)
            interval_pattern = re.compile(r'^\d+/\d+$')
            if not interval_pattern.match(interval):
                return False, "Неверный формат интервала. Используйте: число/число"
            
            parts = interval.split('/')
            numerator, denominator = map(int, parts)
            
            if numerator <= 0 or denominator <= 0:
                return False, "Числа в интервале должны быть больше 0"
            
            if numerator > 1000 or denominator > 1000:
                return False, "Числа в интервале слишком большие (максимум 1000)"
            
            return True, ""

        def validate_default_duration(duration):
            """Валидация длительности по умолчанию"""
            if not duration or not duration.strip():
                return True, ""  # Пустое значение допустимо
            
            duration = duration.strip()
            if len(duration) > 10:
                return False, "Длительность слишком длинная"
            
            try:
                value = int(duration)
                if value <= 0:
                    return False, "Длительность должна быть больше 0"
                if value > 1440:  # 24 часа в минутах
                    return False, "Длительность слишком большая (максимум 1440 минут)"
                return True, ""
            except ValueError:
                return False, "Длительность должна быть целым числом"

        def validate_special_durations(specials):
            """Валидация особых длительностей"""
            if not specials or not specials.strip():
                return True, ""  # Пустое значение допустимо
            
            specials = specials.strip()
            if len(specials) > 500:
                return False, "Особые длительности слишком длинные"
            
            # Формат: время=минуты, время=минуты
            parts = [part.strip() for part in specials.split(',')]
            
            for part in parts:
                if not part:
                    continue
                
                if '=' not in part:
                    return False, f"Неверный формат: '{part}'. Используйте: время=минуты"
                
                time_str, duration_str = part.split('=', 1)
                time_str = time_str.strip()
                duration_str = duration_str.strip()
                
                # Валидация времени (формат HH:MM)
                time_pattern = re.compile(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$')
                if not time_pattern.match(time_str):
                    return False, f"Неверный формат времени: '{time_str}'. Используйте: HH:MM"
                
                # Валидация длительности
                try:
                    duration = int(duration_str)
                    if duration <= 0:
                        return False, f"Длительность должна быть больше 0: '{duration_str}'"
                    if duration > 1440:
                        return False, f"Длительность слишком большая: '{duration_str}' (максимум 1440 минут)"
                except ValueError:
                    return False, f"Длительность должна быть числом: '{duration_str}'"
            
            return True, ""

        def validate_lines_schedule(lines_text_widget):
            """Валидация расписания мониторинга строк"""
            raw = lines_text_widget.get('1.0', tk.END).strip()
            if not raw:
                return True, ""  # Пустое значение допустимо
            
            if len(raw) > 1000:
                return False, "Расписание слишком длинное"
            
            items = [item.strip() for part in raw.split('\n') for item in part.split(',')]
            items = [item for item in items if item]
            
            for item in items:
                # Проверяем формат времени HH:MM
                time_pattern = re.compile(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$')
                if not time_pattern.match(item):
                    return False, f"Неверный формат времени: '{item}'. Используйте: HH:MM"
            
            return True, ""

        def validate_all_fields():
            """Валидация всех полей"""
            clear_error()
            
            # Валидация названия канала
            is_valid, error_msg = validate_channel_name(name_var.get())
            if not is_valid:
                show_error(error_msg)
                name_entry.focus()
                return False
            
            # Валидация URL
            is_valid, error_msg = validate_url(url_var.get())
            if not is_valid:
                show_error(error_msg)
                url_entry.focus()
                return False
            
            # Валидация параметров обрезки
            is_valid, error_msg = validate_crop(crop_var.get())
            if not is_valid:
                show_error(error_msg)
                crop_entry.focus()
                return False
            
            # Валидация интервала
            is_valid, error_msg = validate_interval(interval_var.get())
            if not is_valid:
                show_error(error_msg)
                interval_entry.focus()
                return False
            
            # Валидация длительности по умолчанию
            is_valid, error_msg = validate_default_duration(default_duration_var.get())
            if not is_valid:
                show_error(error_msg)
                default_duration_entry.focus()
                return False
            
            # Валидация особых длительностей
            is_valid, error_msg = validate_special_durations(special_durations_var.get())
            if not is_valid:
                show_error(error_msg)
                special_durations_entry.focus()
                return False
            
            # Валидация расписания
            is_valid, error_msg = validate_lines_schedule(lines_text)
            if not is_valid:
                show_error(error_msg)
                lines_text.focus()
                return False
            
            return True

        def fill_fields(event=None):
            ch = channel_var.get()
            if ch in channels:
                name_var.set(ch)
                url_var.set(channels[ch].get('url', ''))
                crop_var.set(channels[ch].get('crop', ''))
                interval_var.set(channels[ch].get('interval', ''))
                default_duration_var.set(str(channels[ch].get('default_duration', '')))
                specials = channels[ch].get('special_durations', {})
                special_durations_var.set(', '.join(f"{k}={v}" for k, v in specials.items()) if specials else '')
                lines_text.delete('1.0', tk.END)
                lines_text.insert(tk.END, ', '.join(channels[ch].get('lines', [])))
            else:
                name_var.set(ch)
                url_var.set('')
                crop_var.set('')
                interval_var.set('')
                default_duration_var.set('')
                special_durations_var.set('')
                lines_text.delete('1.0', tk.END)
            clear_error()  # Очищаем ошибки при смене канала
            
        channel_combo.bind("<<ComboboxSelected>>", fill_fields)
        channel_combo.bind("<KeyRelease>", fill_fields)

        def parse_time_list(text_widget):
            """Безопасный парсинг списка времени с валидацией"""
            raw = text_widget.get('1.0', tk.END).strip()
            if not raw: 
                return []
            
            # Ограничиваем длину входных данных
            if len(raw) > 1000:
                logger.warning("Слишком длинный список времени, обрезаем до 1000 символов")
                raw = raw[:1000]
            
            # Разбиваем по строкам и запятым
            items = []
            for part in raw.split('\n'):
                for item in part.split(','):
                    item = item.strip()
                    if item:
                        # Дополнительная валидация каждого элемента
                        if len(item) > 10:  # Максимальная длина времени HH:MM
                            logger.warning(f"Слишком длинный элемент времени: {item}")
                            continue
                        
                        # Проверяем, что элемент содержит только допустимые символы
                        if not re.match(r'^[0-9:]+$', item):
                            logger.warning(f"Недопустимые символы в времени: {item}")
                            continue
                        
                        # Проверяем формат времени
                        time_pattern = re.compile(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$')
                        if time_pattern.match(item):
                            items.append(item)
                        else:
                            logger.warning(f"Неверный формат времени: {item}")
            
            # Удаляем дубликаты, сохраняя порядок
            seen = set()
            unique_items = []
            for item in items:
                if item not in seen:
                    seen.add(item)
                    unique_items.append(item)
            
            return unique_items

        def save_channel():
            # Валидация всех полей перед сохранением
            if not validate_all_fields():
                return
            
            ch_name = name_var.get().strip()
            
            # Парсинг особых длительностей с дополнительной проверкой
            specials = {}
            if specials_raw := special_durations_var.get().strip():
                for part in specials_raw.split(','):
                    if '=' in part:
                        k, v = part.split('=', 1)
                        k = k.strip()
                        v = v.strip()
                        try:
                            # Дополнительная проверка времени
                            time_pattern = re.compile(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$')
                            if not time_pattern.match(k):
                                show_error(f"Неверный формат времени в особых длительностях: '{k}'")
                                return
                            
                            duration = int(v)
                            if duration <= 0 or duration > 1440:
                                show_error(f"Неверная длительность в особых длительностях: '{v}'")
                                return
                            
                            specials[k] = duration
                        except ValueError:
                            show_error(f"Неверная длительность в особых длительностях: '{v}'")
                            return
            
            channel_data = {
                'url': url_var.get().strip(),
                'crop': crop_var.get().strip(),
                'interval': interval_var.get().strip(),
                'lines': parse_time_list(lines_text)
            }
            
            # Добавляем длительность по умолчанию, если она указана
            if default_duration_raw := default_duration_var.get().strip():
                try:
                    duration = int(default_duration_raw)
                    if duration > 0 and duration <= 1440:
                        channel_data['default_duration'] = duration
                except ValueError:
                    show_error("Неверная длительность по умолчанию")
                    return
            
            # Добавляем особые длительности, если они есть
            if specials:
                channel_data['special_durations'] = specials
            
            channels[ch_name] = channel_data
            
            # Используем config_manager для сохранения
            if config_manager.save_channels(channels):
                logger.info(f"Канал '{ch_name}' успешно сохранен в channels.json")
                settings_win.destroy()
                self.channels = channels
                self.channel_names = list(channels.keys())
                for combo in self.comboboxes:
                    combo['values'] = self.channel_names
            else:
                messagebox.showerror("Ошибка", "Не удалось сохранить channels.json. Проверьте права доступа к файлу.")

        # Кнопки
        button_frame = tk.Frame(settings_win)
        button_frame.pack(pady=15)
        save_btn = tk.Button(button_frame, text="Сохранить", command=save_channel, bg="#4CAF50", fg="white")
        save_btn.pack(side="left", padx=5)
        cancel_btn = tk.Button(button_frame, text="Отмена", command=settings_win.destroy, bg="#f44336", fg="white")
        cancel_btn.pack(side="left", padx=5)

    def _add_tooltip(self, widget, text):
        """
        Добавляет простой tooltip для Tkinter-виджета.
        """
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

    def update_recording_status(self, channel_name, is_recording):
        """
        Обновляет статус записи для канала.
        """
        if channel_name in self.recording_status:
            self.recording_status[channel_name] = is_recording
            logger.info(f"Статус записи для {channel_name} изменен на {is_recording}")
        else:
            logger.warning(f"Попытка обновить статус для неизвестного канала: {channel_name}")
            return

        # Обновить рамки для всех видимых окон
        for idx, displayed_channel in enumerate(self.selected_channels):
            if displayed_channel == channel_name:
                color = "red" if is_recording else "#444"
                if self.grid_cells[idx]:
                    self.grid_cells[idx].config(highlightbackground=color, highlightcolor=color)

    def toggle_scheduler_buttons(self, paused: bool):
        """
        Переключает состояние кнопок планировщика (пауза/возобновить).
        """
        if paused:
            self.pause_scheduler_button.config(state="disabled")
            self.resume_scheduler_button.config(state="normal")
        else:
            self.pause_scheduler_button.config(state="normal")
            self.resume_scheduler_button.config(state="disabled")

    def show_progress(self):
        """
        Показывает прогресс-бар.
        """
        self.progress_bar.pack(fill='x', padx=5, pady=5)
        self.progress_var.set(0)
        self.progress_bar.update()

    def hide_progress(self):
        """
        Скрывает прогресс-бар.
        """
        self.progress_bar.pack_forget()

    def update_progress(self, percent):
        """
        Обновляет значение прогресс-бара.
        """
        self.progress_var.set(percent)
        self.progress_bar.update()