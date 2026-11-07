import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from app.ui.main_window import MainWindow

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Universal File Converter")
    app.setOrganizationName("Universal Tools")
    app.setFont(QFont("Segoe UI", 10))
    window = MainWindow()
    if window.preference_values.get("start_maximized", True):
        window.showMaximized()
    else:
        window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
