import sys
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget, QMessageBox, QLineEdit, QDialog, QLabel, QGraphicsDropShadowEffect

from repository import Repository
from user_window import UserWindow, icon

BASE = Path(__file__).resolve().parent


class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        from typography import load_fonts
        load_fonts()
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
        self.registerButton.clicked.connect(self.register)
        # Clear local legacy styles so the auth screen shares the current palette.
        for widget in self.findChildren(QWidget):
            widget.setStyleSheet('')
        self.setStyleSheet((BASE/'assets'/'style.qss').read_text(encoding='utf-8').replace('@ASSETS@',(BASE/'assets').as_posix())+'''
            QWidget#login_window,QFrame#background,QFrame#rightPanel { background:#F8E9F0; }
            QFrame#background, QFrame#rightPanel { border-radius: 26px; }
            QFrame#leftPanel { background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #612B45, stop:1 #4A2136); border:none; border-top-left-radius:26px; border-bottom-left-radius:26px; }
            QFrame#leftPanel QLabel { color:#FFE8F0; }
            QLabel#appTitle { font-family:Manrope; font-size:27px; font-weight:700; }
            QLabel#loginTitle { font-family:Manrope; font-size:30px; font-weight:800; color:#9A2857; }
            QLabel#loginSubtitle { color:#8D6C7D; }
            QPushButton#loginButton { background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #FF5C95, stop:1 #FF2D76); color:white; border:none; font-weight:700; border-radius:13px; }
            QPushButton#loginButton:hover { background:#FF1464; }
            QPushButton#registerButton { color:#B61A51; }
        ''')
        self.polish_auth_ui()



    def polish_auth_ui(self):
        for lbl in [self.loginTitle, self.loginSubtitle]:
            lbl.setWordWrap(True)
            lbl.setMinimumHeight(38)
        self.loginTitle.setMinimumHeight(76)
        self.loginSubtitle.setMinimumHeight(44)
        self.usernameInput.setMinimumHeight(48)
        self.passwordInput.setMinimumHeight(48)
        self.loginButton.setMinimumHeight(46)
        self.registerButton.setMinimumHeight(40)
        if hasattr(self, 'background'):
            shadow = QGraphicsDropShadowEffect(self.background)
            shadow.setBlurRadius(40)
            shadow.setOffset(0, 14)
            shadow.setColor(Qt.GlobalColor.lightGray)
            self.background.setGraphicsEffect(shadow)

    def register(self):
        from registration import RegistrationDialog
        dialog = RegistrationDialog(self.repo, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.usernameInput.setText(dialog.created_login)
            self.passwordInput.clear()
            self.loginSubtitle.setText('Аккаунт создан. Введите пароль, чтобы войти.')
            self.passwordInput.setFocus()

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
