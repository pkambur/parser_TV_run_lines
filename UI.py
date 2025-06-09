import tkinter as tk

class MonitoringUI:
    def __init__(self, start_monitoring, stop_monitoring, save_rbk_mir24, stop_rbk_mir24, save_to_csv, send_strings):
        self.root = tk.Tk()
        self.root.title("Мониторинг бегущих строк")
        self.root.geometry("400x350")

        # Создание виджетов
        self.status_label = tk.Label(self.root, text="Состояние: Ожидание")
        self.status_label.pack(pady=10)

        self.start_button = tk.Button(self.root, text="Мониторинг строк", command=start_monitoring)
        self.start_button.pack(pady=5)

        self.stop_button = tk.Button(self.root, text="Остановить парсинг", command=stop_monitoring, state="disabled")
        self.stop_button.pack(pady=5)

        self.rbk_mir24_button = tk.Button(self.root, text="Строки РБК и МИР24", command=save_rbk_mir24)
        self.rbk_mir24_button.pack(pady=5)

        self.stop_rbk_mir24_button = tk.Button(self.root, text="Остановить парсинг РБК и МИР24", command=stop_rbk_mir24, state="disabled")
        self.stop_rbk_mir24_button.pack(pady=5)

        self.save_button = tk.Button(self.root, text="Сохранение строк", command=save_to_csv)
        self.save_button.pack(pady=5)

        self.send_strings_button = tk.Button(self.root, text="Отправка строк", command=send_strings)
        self.send_strings_button.pack(pady=5)

    def run(self):
        self.root.mainloop()