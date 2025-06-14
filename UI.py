import tkinter as tk
from tkinter import ttk, messagebox
import logging

logger = logging.getLogger(__name__)

class MonitoringUI:
    def __init__(self, app):
        self.app = app
        self.root = tk.Tk()
        self.root.title("Мониторинг телеканалов")
        self.root.geometry("500x300")
        
        self.create_widgets()
        
    def create_widgets(self):
        lines_frame = ttk.LabelFrame(self.root, text="Мониторинг строк", padding=10)
        lines_frame.pack(fill="x", padx=10, pady=5)
        
        self.lines_status = ttk.Label(lines_frame, text="Состояние: Остановлен")
        self.lines_status.pack(fill="x", pady=5)
        
        lines_buttons = ttk.Frame(lines_frame)
        lines_buttons.pack(fill="x", pady=5)
        
        self.start_lines_button = ttk.Button(
            lines_buttons,
            text="Запустить мониторинг",
            command=self.app.start_lines_monitoring
        )
        self.start_lines_button.pack(side="left", padx=5)
        
        self.stop_lines_button = ttk.Button(
            lines_buttons,
            text="Остановить мониторинг",
            command=self.app.stop_lines_monitoring,
            state="disabled"
        )
        self.stop_lines_button.pack(side="left", padx=5)
        
        rbk_mir24_frame = ttk.LabelFrame(self.root, text="RBK и MIR24", padding=10)
        rbk_mir24_frame.pack(fill="x", padx=10, pady=5)
        
        self.rbk_mir24_status = ttk.Label(rbk_mir24_frame, text="Состояние: Остановлен")
        self.rbk_mir24_status.pack(fill="x", pady=5)
        
        rbk_mir24_buttons = ttk.Frame(rbk_mir24_frame)
        rbk_mir24_buttons.pack(fill="x", pady=5)
        
        self.start_rbk_mir24_button = ttk.Button(
            rbk_mir24_buttons,
            text="Запустить запись",
            command=self.app.start_rbk_mir24
        )
        self.start_rbk_mir24_button.pack(side="left", padx=5)
        
        self.stop_rbk_mir24_button = ttk.Button(
            rbk_mir24_buttons,
            text="Остановить запись",
            command=self.app.stop_rbk_mir24,
            state="disabled"
        )
        self.stop_rbk_mir24_button.pack(side="left", padx=5)
        
        # Создаем фрейм для кнопок сохранения и отправки
        save_buttons_frame = ttk.Frame(self.root)
        save_buttons_frame.pack(pady=10)
        
        self.save_csv_button = ttk.Button(
            save_buttons_frame,
            text="Сохранить строки в CSV",
            command=self.app.start_save_to_csv
        )
        self.save_csv_button.pack(side="left", padx=5)
        
        self.send_telegram_button = ttk.Button(
            save_buttons_frame,
            text="Отправить строки",
            command=self.app.send_to_telegram
        )
        self.send_telegram_button.pack(side="left", padx=5)
        
        self.status_label = ttk.Label(self.root, text="Готов к работе")
        self.status_label.pack(side="bottom", fill="x", padx=10, pady=5)
        
    def update_lines_status(self, status):
        self.lines_status.config(text=f"Состояние: {status}")
        if status == "Запущен":
            self.start_lines_button.config(state="disabled")
            self.stop_lines_button.config(state="normal")
        else:
            self.start_lines_button.config(state="normal")
            self.stop_lines_button.config(state="disabled")
            
    def update_rbk_mir24_status(self, status):
        self.rbk_mir24_status.config(text=f"Состояние: {status}")
        if status == "Запущен":
            self.start_rbk_mir24_button.config(state="disabled")
            self.stop_rbk_mir24_button.config(state="normal")
            self.status_label.config(text="Запись RBK и MIR24 запущена")
        elif status == "Остановлен":
            self.start_rbk_mir24_button.config(state="normal")
            self.stop_rbk_mir24_button.config(state="disabled")
            self.status_label.config(text="Запись RBK и MIR24 остановлена")
        else:
            self.status_label.config(text=status)
            
    def update_status(self, message):
        self.status_label.config(text=message)
        
    def run(self):
        self.root.mainloop()
        
    def cleanup(self):
        """Очистка ресурсов при закрытии."""
        try:
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