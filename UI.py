import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QPushButton, QLabel
from PyQt5.QtCore import pyqtSignal

class MonitoringWindow(QMainWindow):
    start_monitoring = pyqtSignal()
    stop_monitoring = pyqtSignal()
    save_to_csv = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Мониторинг бегущих строк")
        self.setGeometry(100, 100, 400, 200)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        self.status_label = QLabel("Состояние: Ожидание")
        layout.addWidget(self.status_label)

        self.start_button = QPushButton("Мониторинг строк")
        self.start_button.clicked.connect(self.on_start_monitoring)
        layout.addWidget(self.start_button)

        self.stop_button = QPushButton("Остановить парсинг")
        self.stop_button.clicked.connect(self.on_stop_monitoring)
        self.stop_button.setEnabled(False)
        layout.addWidget(self.stop_button)

        self.save_button = QPushButton("Сохранение строк")
        self.save_button.clicked.connect(self.on_save_to_csv)
        layout.addWidget(self.save_button)

    def on_start_monitoring(self):
        self.status_label.setText("Состояние: Мониторинг запущен")
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.start_monitoring.emit()

    def on_stop_monitoring(self):
        self.status_label.setText("Состояние: Мониторинг остановлен")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.stop_monitoring.emit()

    def on_save_to_csv(self):
        self.status_label.setText("Состояние: Сохранение в CSV")
        self.save_to_csv.emit()

    def update_status(self, message):
        self.status_label.setText(f"Состояние: {message}")