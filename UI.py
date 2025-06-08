# Импортируем библиотеку Tkinter для создания графического интерфейса
import tkinter as tk

class MonitoringUI:
    """
    Класс MonitoringUI отвечает за построение графического интерфейса пользователя
    и привязку кнопок к переданным функциям логики (обработчикам).
    """
    def __init__(
        self, 
        start_monitoring,    # Функция запуска мониторинга
        stop_monitoring,     # Функция остановки мониторинга
        save_rbk_mir24,      # Сохранение строк каналов РБК/МИР24
        save_to_csv,         # Сохранение строк других каналов
        stop_rbk_mir24,      # Принудительная остановка обработки РБК/МИР24
        send_strings         # Отправка строк в Telegram
    ):
        self.root = tk.Tk()                              # Создание главного окна приложения
        self.root.title("Мониторинг бегущих строк")      # Заголовок окна
        self.root.geometry("400x350")                    # Размер окна (ширина x высота)

        # Метка состояния
        self.status_label = tk.Label(self.root, text="Состояние: Ожидание")
        self.status_label.pack(pady=10)  # Отступ сверху и снизу

        # Кнопка запуска мониторинга
        self.start_button = tk.Button(
            self.root, 
            text="Мониторинг строк", 
            command=start_monitoring
        )
        self.start_button.pack(pady=5)

        # Кнопка остановки мониторинга (по умолчанию отключена)
        self.stop_button = tk.Button(
            self.root, 
            text="Остановить парсинг", 
            command=stop_monitoring, 
            state="disabled"
        )
        self.stop_button.pack(pady=5)

        # Кнопка сохранения строк РБК и МИР24
        self.rbk_mir24_button = tk.Button(
            self.root, 
            text="Строки РБК и МИР24", 
            command=save_rbk_mir24
        )
        self.rbk_mir24_button.pack(pady=5)

        # Кнопка остановки обработки РБК и МИР24 (по умолчанию отключена)
        self.stop_rbk_mir24_button = tk.Button(
            self.root, 
            text="Остановить парсинг РБК и МИР24", 
            command=stop_rbk_mir24, 
            state="disabled"
        )
        self.stop_rbk_mir24_button.pack(pady=5)

        # Кнопка сохранения строк других каналов в CSV
        self.save_button = tk.Button(
            self.root, 
            text="Сохранение строк", 
            command=save_to_csv
        )
        self.save_button.pack(pady=5)

        # Кнопка отправки строк в Telegram
        self.send_strings_button = tk.Button(
            self.root, 
            text="Отправка строк", 
            command=send_strings
        )
        self.send_strings_button.pack(pady=5)

    def run(self):
        """
        Запускает главный цикл интерфейса — окно остаётся активным до закрытия пользователем.
        """
        self.root.mainloop()
