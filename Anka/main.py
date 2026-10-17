import sys
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget, QMessageBox, QLineEdit

from repository import Repository
from user_window import UserWindow, icon

BASE = Path(__file__).resolve().parent


class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        uic.loadUi(str(BASE / "login_window.ui"), self)
        self.setWindowTitle("SubControl — вход")
        self.setWindowIcon(icon("logo"))
        self.appIcon.setPixmap(icon("logo").pixmap(100, 100))
        self.appIcon.setScaledContents(True)
        self.usernameInput.setPlaceholderText("Введите логин")
        self.passwordInput.setEchoMode(QLineEdit.EchoMode.Password)
        self.usernameInput.setMaxLength(15)
        self.usernameInput.returnPressed.connect(self.passwordInput.setFocus)
        self.passwordInput.returnPressed.connect(self.login)
        self.loginButton.clicked.connect(self.login)
        self.repo = Repository()
        self.role_window = None

    def login(self):
        login = self.usernameInput.text().strip()
        password = self.passwordInput.text()
        if not login or not password:
            QMessageBox.warning(self, "Вход", "Введите логин и пароль.")
            return
        self.loginButton.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            user = self.repo.authenticate(login, password)
            role = user["role"]
            if role == "Пользователь":
                self.repo.ensure_preferences()
                self.role_window = UserWindow(user, self.repo)
                self.role_window.logged_out.connect(self.return_to_login)
            elif role in ("Менеджер", "Администратор"):
                from role_windows import ManagerWindow, AdminWindow
                self.role_window = (ManagerWindow if role == "Менеджер" else AdminWindow)(user)
            else:
                raise ValueError("Для этой роли не настроено окно.")
            self.role_window.show()
            self.hide()
            self.passwordInput.clear()
        except Exception as error:
            QMessageBox.warning(self, "Вход", str(error))
        finally:
            QApplication.restoreOverrideCursor()
            self.loginButton.setEnabled(True)

    def return_to_login(self):
        self.passwordInput.clear()
        self.show()
        self.activateWindow()
        self.passwordInput.setFocus()


def run():
    app = QApplication(sys.argv)
    app.setApplicationName("SubControl")
    app.setOrganizationName("AnkaCoursework")
    app.setStyle("Fusion")
    app.setWindowIcon(icon("logo"))
    window = LoginWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
