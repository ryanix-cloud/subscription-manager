"""Registration creates a regular user in the existing MySQL database."""
from PyQt6.QtWidgets import QDialog, QLineEdit, QApplication
from PyQt6.QtCore import Qt
from user_window import vbox, hbox, label, button


class RegistrationDialog(QDialog):
    def __init__(self, repo, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.created_login = None
        self.busy = False
        self.setWindowTitle('SubControl — регистрация')
        self.setMinimumWidth(490)
        root = vbox(self, 28, 10)
        root.addWidget(label('Создать аккаунт', heading=True))
        hint = label('Начните управлять подписками и расходами.', muted=True)
        root.addWidget(hint)
        self.fields = {}
        for key, caption, maximum in [('name','Имя',50),('surname','Фамилия',50),
                                      ('email','Email',254),('login','Логин',15),
                                      ('password','Пароль',72),('confirmation','Повторите пароль',72)]:
            root.addWidget(label(caption))
            field = QLineEdit()
            field.setObjectName(key+'Input')
            field.setAccessibleName(caption)
            field.setMaxLength(maximum)
            if key in ('password','confirmation'):
                field.setEchoMode(QLineEdit.EchoMode.Password)
                field.setPlaceholderText('Минимум 8 символов' if key=='password' else 'Введите пароль ещё раз')
            elif key=='login':
                field.setPlaceholderText('От 3 до 15 символов, без пробелов')
            elif key=='email':
                field.setPlaceholderText('name@example.ru')
            root.addWidget(field)
            self.fields[key] = field
        self.errorLabel = label('', badge='failed')
        self.errorLabel.setWordWrap(True)
        self.errorLabel.hide()
        root.addWidget(self.errorLabel)
        actions = hbox(spacing=10)
        self.cancelButton = button('Назад ко входу', self.reject)
        self.submitButton = button('Зарегистрироваться', self.submit, primary=True)
        self.submitButton.setDefault(True)
        actions.addWidget(self.cancelButton)
        actions.addWidget(self.submitButton)
        root.addLayout(actions)

    def submit(self):
        if self.busy:
            return
        self.busy = True
        self.submitButton.setEnabled(False)
        self.errorLabel.hide()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            values = {key: field.text() for key,field in self.fields.items()}
            self.repo.register_user(**values)
            self.created_login = values['login'].strip()
            self.accept()
        except Exception as error:
            self.errorLabel.setText(str(error))
            self.errorLabel.show()
        finally:
            QApplication.restoreOverrideCursor()
            self.submitButton.setEnabled(True)
            self.busy = False
