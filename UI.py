import tkinter as tk
from tkinter import ttk, messagebox

class MonitoringUI:
    def __init__(self, app):
        self.app = app
        self.root = tk.Tk()
        self.root.title("Мониторинг телеканалов")
        self.root.geometry("400x300")
        
        # Создаем и размещаем элементы интерфейса
        self.create_widgets()
        
    def create_widgets(self):
        # Фрейм для кнопок мониторинга строк
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
        
        # Фрейм для кнопок RBK и MIR24
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
        
        # Кнопка сохранения в CSV
        self.save_csv_button = ttk.Button(
            self.root,
            text="Сохранить строки в CSV",
            command=self.app.start_save_to_csv
        )
        self.save_csv_button.pack(pady=10)
        
        # Статусная строка
        self.status_label = ttk.Label(self.root, text="Готов к работе")
        self.status_label.pack(side="bottom", fill="x", padx=10, pady=5)
        
    def update_lines_status(self, status):
        """Обновляет статус мониторинга строк."""
        self.lines_status.config(text=f"Состояние: {status}")
        if status == "Запущен":
            self.start_lines_button.config(state="disabled")
            self.stop_lines_button.config(state="normal")
        else:
            self.start_lines_button.config(state="normal")
            self.stop_lines_button.config(state="disabled")
            
    def update_rbk_mir24_status(self, status):
        """Обновляет статус мониторинга RBK и MIR24."""
        self.rbk_mir24_status.config(text=f"Состояние: {status}")
        if status == "Запущен":
            self.start_rbk_mir24_button.config(state="disabled")
            self.stop_rbk_mir24_button.config(state="normal")
        else:
            self.start_rbk_mir24_button.config(state="normal")
            self.stop_rbk_mir24_button.config(state="disabled")
            
    def update_status(self, message):
        """Обновляет статусную строку."""
        self.status_label.config(text=message)
        
    def run(self):
        """Запускает главный цикл приложения."""
        self.root.mainloop()
        
    def cleanup(self):
        """Очистка ресурсов при закрытии."""
        self.root.destroy()