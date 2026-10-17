"""Designer window shell with data-driven rows and reusable Qt widgets."""
import csv
import shutil
from datetime import date
from functools import partial
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtCore import Qt, QSize, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QIcon, QDesktopServices
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QLineEdit, QComboBox, QScrollArea, QSizePolicy, QMenu, QMessageBox,
    QDialog, QFileDialog, QSystemTrayIcon, QSpinBox, QGraphicsDropShadowEffect,
)

from repository import Repository, as_date, money
from documents import write_pdf
from receipt_service import ReceiptService
from payment_simulation import SimulatedServices
from insights_window import InsightsDialog, PersonalSubscriptionDialog, EditSubscriptionDialog
from extra_repository import pause_subscription, resume_subscription

BASE = Path(__file__).resolve().parent
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
PAGES = ["home", "subscriptions", "payments", "notifications", "settings"]


def icon(name, light=False):
    return QIcon(str(BASE / "assets" / "icons" / f"{name}{'-light' if light else ''}.svg"))


def service_icon(name):
    name = name.casefold()
    match = next((filename for keyword, filename in [
        ("spotify", "spotify"), ("netflix", "netflix"), ("youtube", "youtube"),
        ("яндекс", "yandex"), ("yandex", "yandex"), ("adobe", "photoshop"),
        ("photoshop", "photoshop"), ("кинопоиск", "kinopoisk"), ("vk", "vk"),
        ("вк", "vk"),
    ] if keyword in name), "generic")
    custom = BASE / "assets" / "service_icons" / f"{match}.svg"
    return QIcon(str(custom))


def label(text="", muted=False, **props):
    obj = QLabel(str(text))
    obj.setTextFormat(Qt.TextFormat.PlainText)
    if muted:
        obj.setProperty("muted", True)
    for key, val in props.items():
        obj.setProperty(key, val)
    return obj


def button(text, callback=None, primary=False, flat=False, symbol=None):
    obj = QPushButton(text)
    if text == '⋮':
        obj.setText('')
        obj.setIcon(icon('more'))
        obj.setIconSize(QSize(18,18))
        obj.setToolTip('Действия')
    obj.setCursor(Qt.CursorShape.PointingHandCursor)
    obj.setProperty("primary", primary)
    obj.setProperty("flat", flat)
    if symbol:
        obj.setIcon(icon(symbol, primary))
        obj.setIconSize(QSize(18, 18))
    if callback:
        obj.clicked.connect(callback)
    return obj


def vbox(widget=None, margin=0, spacing=0):
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(margin, margin, margin, margin)
    layout.setSpacing(spacing)
    return layout


def hbox(widget=None, margin=0, spacing=0):
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(margin, margin, margin, margin)
    layout.setSpacing(spacing)
    return layout


def panel():
    frame = QFrame()
    frame.setProperty("panel", True)
    return frame


def apply_shadow(widget, blur=30, y=10, alpha=82):
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, y)
    effect.setColor(widget.palette().color(widget.foregroundRole()))
    color = effect.color()
    color.setRed(228)
    color.setGreen(189)
    color.setBlue(205)
    color.setAlpha(alpha)
    effect.setColor(color)
    widget.setGraphicsEffect(effect)


def clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout():
            clear(item.layout())


def scroll_body():
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    body = QWidget()
    layout = vbox(body)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    area.setWidget(body)
    return area, layout


def badge(text, state):
    obj = label(text, badge=state)
    obj.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return obj






class CatalogDialog(QDialog):
    def __init__(self, repo, uid, parent=None):
        super().__init__(parent)
        self.repo, self.uid = repo, uid
        self.setWindowTitle("Добавить подписку")
        self.resize(670, 600)
        self.setMinimumSize(560, 400)
        root = vbox(self, 24, 16)
        root.addWidget(label("Добавить подписку", section=True))
        root.addWidget(label("Выберите сервис и тариф из каталога.", muted=True))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск сервиса или тарифа...")
        self.search.setClearButtonEnabled(True)
        root.addWidget(self.search)
        area, self.rows = scroll_body()
        root.addWidget(area, 1)
        root.addWidget(button("Закрыть", self.reject))
        self.plans = repo.catalog()
        self.active_ids = {s["plan_id"] for s in repo.subscriptions(uid) if s["us_status"] == "Активна"}
        self.search.textChanged.connect(self.render)
        self.render()

    def render(self):
        clear(self.rows)
        found = 0
        for plan in self.plans:
            if self.search.text().casefold() not in (plan["service_name"]+" "+plan["plan_name"]).casefold():
                continue
            found += 1
            row = panel()
            layout = hbox(row, 15, 12)
            image = label()
            image.setPixmap(service_icon(plan["service_name"]).pixmap(40, 40))
            layout.addWidget(image)
            texts = vbox(spacing=5)
            texts.addWidget(label(plan["service_name"]))
            texts.addWidget(label(f"{plan['plan_name']} · {money(plan['price'])} ₽ / {plan['duration_months']} мес.", muted=True))
            layout.addLayout(texts, 1)
            active = plan["plan_id"] in self.active_ids
            add = button("Подключена" if active else "Добавить", partial(self.add, plan), primary=not active)
            add.setEnabled(not active)
            add.setObjectName(f"addPlan{plan['plan_id']}")
            layout.addWidget(add)
            self.rows.addWidget(row)
        if not found:
            self.rows.addWidget(label("Подходящих тарифов нет.", muted=True))

    def add(self, plan):
        try:
            self.repo.add_subscription(self.uid, plan["plan_id"])
        except Exception as error:
            QMessageBox.warning(self, "Подписка", str(error))
            return
        self.accept()


class PasswordDialog(QDialog):
    def __init__(self, repo, uid, parent=None):
        super().__init__(parent)
        self.repo, self.uid = repo, uid
        self.setWindowTitle("Изменить пароль")
        self.setMinimumWidth(410)
        root = vbox(self, 24, 12)
        self.fields = []
        for title in ["Текущий пароль", "Новый пароль", "Повторите новый пароль"]:
            root.addWidget(label(title))
            edit = QLineEdit()
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            edit.setMaxLength(72)
            edit.returnPressed.connect(self.save)
            self.fields.append(edit)
            root.addWidget(edit)
        root.addWidget(label("Минимум 8 символов. Пароль хранится в виде хеша.", muted=True))
        self.error = label()
        self.error.setWordWrap(True)
        root.addWidget(self.error)
        actions = hbox(spacing=8)
        actions.addWidget(button("Отмена", self.reject))
        actions.addWidget(button("Изменить пароль", self.save, primary=True))
        root.addLayout(actions)

    def save(self):
        try:
            self.repo.change_password(self.uid, *(field.text() for field in self.fields))
        except Exception as error:
            self.error.setText(str(error))
            return
        self.accept()


class PaymentDialog(QDialog):
    """A service response demonstration, with no real card details."""
    def __init__(self, services, uid, payment, parent=None):
        super().__init__(parent)
        self.services, self.uid, self.payment = services, uid, payment
        self.setWindowTitle('Учебная оплата подписки')
        self.setMinimumWidth(500)
        self.changed = False
        self.busy = False
        root = vbox(self, 24, 16)
        header = hbox(spacing=14)
        image = label()
        image.setPixmap(service_icon(payment['service_name']).pixmap(46, 46))
        header.addWidget(image)
        info = vbox(spacing=5)
        info.addWidget(label(payment['service_name'], section=True))
        info.addWidget(label(payment['plan_name']+' · '+money(payment['amount'])+' ₽', muted=True))
        header.addLayout(info, 1)
        root.addLayout(header)
        text = label('Приложение имитирует получение ответа от сервиса.\nРеальные деньги не списываются.', muted=True)
        text.setWordWrap(True)
        root.addWidget(text)
        root.addWidget(label('Сценарий ответа'))
        self.scenario = QComboBox()
        for text, value in [('Случайный ответ сервиса (80% успеха)', 'auto'),
                            ('Успешная оплата', 'success'),
                            ('Ошибка: недостаточно средств', 'insufficient_funds'),
                            ('Ошибка: сервис недоступен', 'service_unavailable')]:
            self.scenario.addItem(text, value)
        root.addWidget(self.scenario)
        self.resultLabel = label('Ожидается запрос к сервису.', muted=True)
        self.resultLabel.setWordWrap(True)
        self.resultLabel.setMinimumHeight(62)
        root.addWidget(self.resultLabel)
        self.receiptButton = button('Сохранить чек', self.save_receipt, symbol='download')
        self.receiptButton.hide()
        root.addWidget(self.receiptButton)
        actions = hbox(spacing=12)
        self.closeButton = button('Закрыть', self.reject)
        self.processButton = button('Получить ответ сервиса', self.start, primary=True)
        actions.addWidget(self.closeButton)
        actions.addWidget(self.processButton)
        root.addLayout(actions)
        self.delay = QTimer(self)
        self.delay.setSingleShot(True)
        self.delay.timeout.connect(self.finish)

    def start(self):
        if self.busy:
            return
        self.busy = True
        self.scenario.setEnabled(False)
        self.closeButton.setEnabled(False)
        self.processButton.setEnabled(False)
        self.resultLabel.setText('Ожидаем ответ от '+self.payment['service_name']+'…')
        self.delay.start(700)

    def finish(self):
        try:
            result = self.services.process(self.uid, self.payment['payment_id'], self.scenario.currentData())
            self.changed = self.changed or result['applied']
            if result['outcome'] == 'Успешно':
                text = f"Оплата прошла успешно.\nЧек SC-{self.payment['payment_id']:06d} сформирован автоматически."
                if result.get('receipt_error'):
                    text = 'Оплата прошла успешно. Чек пока не удалось сохранить:\n'+result['receipt_error']
                self.resultLabel.setText(text)
                self.receiptButton.show()
                self.processButton.setText('Оплачено')
            else:
                self.resultLabel.setText('Оплата не прошла.\n'+result['reason']+'\nЧек не создаётся. Можно повторить попытку.')
                self.processButton.setText('Повторить попытку')
                self.processButton.setEnabled(True)
                self.scenario.setEnabled(True)
        except Exception as error:
            self.resultLabel.setText(str(error))
            self.processButton.setEnabled(True)
            self.scenario.setEnabled(True)
        finally:
            self.busy = False
            self.closeButton.setEnabled(True)

    def save_receipt(self):
        self.parent().receipt(self.payment)

    def reject(self):
        if self.busy:
            return
        self.delay.stop()
        super().reject()


class UserWindow(QMainWindow):
    logged_out = pyqtSignal()

    def __init__(self, user, repository=None, receipt_directory=None):
        super().__init__()
        from typography import load_fonts
        load_fonts()
        uic.loadUi(str(BASE / "user_window.ui"), self)
        self.repo = repository or Repository()
        self.user = dict(user)
        self.uid = self.user["user_id"]
        self.receipts = ReceiptService(self.repo, receipt_directory)
        self.simulator = SimulatedServices(self.repo, self.receipts)
        self.processing_payments = False
        self.preferences = self.repo.preferences(self.uid)
        self.page = "home"
        self.subscription_filter = "active"
        self.notification_filter = "all"
        self.settings_dirty = False
        self.loading_settings = False
        self.setWindowIcon(icon("logo"))
        self.apply_theme()
        self.statusLabel.hide()
        self.toast_timer = QTimer(self)
        self.toast_timer.setSingleShot(True)
        self.toast_timer.timeout.connect(self.statusLabel.hide)
        self.brandIcon.setPixmap(icon("logo").pixmap(38, 38))
        self.brandIcon.setFixedSize(38, 42)
        self.avatarButton.setIcon(icon("avatar"))
        self.avatarButton.setIconSize(QSize(38, 38))
        self.avatarButton.setFixedSize(42, 42)
        self.avatarButton.setToolTip("Профиль и выход")
        self.avatarButton.clicked.connect(self.profile_menu)
        self.accountButton.setIcon(icon("avatar"))
        self.accountButton.setIconSize(QSize(45, 45))
        self.accountButton.clicked.connect(self.profile_menu)
        self.bellButton.setIcon(icon("bell"))
        self.bellButton.setIconSize(QSize(26, 26))
        self.bellButton.setFixedSize(44, 42)
        self.bellButton.setToolTip("Открыть уведомления")
        self.bellButton.clicked.connect(partial(self.navigate, "notifications"))
        self.bellBadge = label("", badge="pending")
        self.bellBadge.setParent(self.bellButton)
        self.bellBadge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bellBadge.setStyleSheet("background:#d33079;color:white;border-radius:8px;font-size:10px;padding:0;")
        self.bellBadge.setGeometry(26, 1, 17, 17)
        self.bellBadge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.navBadge = QLabel(self.notificationsButton)
        self.navBadge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.navBadge.setStyleSheet("background:#d33079;color:white;border-radius:9px;font-size:11px;")
        self.navBadge.setGeometry(190, 16, 19, 19)
        self.navBadge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        for key, symbol in zip(PAGES, ["home", "calendar", "card", "bell", "settings"]):
            nav = getattr(self, key+"Button")
            nav.setIcon(icon(symbol, True))
            nav.setIconSize(QSize(23, 23))
            nav.setCursor(Qt.CursorShape.PointingHandCursor)
            nav.clicked.connect(partial(self.navigate, key))
        self.searchInput.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.headerLayout.setStretch(0, 1)
        self.searchInput.setClearButtonEnabled(True)
        self.searchInput.textChanged.connect(self.search_changed)
        self.bind_pages()
        self.add_feature_controls()
        from dashboard import Dashboard
        self.dashboard = Dashboard(self)
        self.apply_theme()
        self.polish_interface()
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(icon("logo"), self)
            self.tray.setToolTip("SubControl")
            self.tray.activated.connect(lambda reason: self.restore_window() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
            self.tray.show()
        self.seen_notifications = None
        self.refresh()
        self.load_settings()
        self.navigate("home")
        self.background_timer = QTimer(self)
        self.background_timer.timeout.connect(self.check_scheduled_payments)
        self.background_timer.start(60000)
        self.initial_payment_check = QTimer(self)
        self.initial_payment_check.setSingleShot(True)
        self.initial_payment_check.timeout.connect(self.check_scheduled_payments)
        self.initial_payment_check.start(1500)

    def apply_theme(self):
        style = (BASE / "assets" / "style.qss").read_text(encoding="utf-8").replace("@ASSETS@", (BASE / "assets").as_posix())
        if self.preferences["theme"] == "Тёмная":
            style += """
                QWidget { color: #ede6ee; }
                QMainWindow,QDialog,QWidget#centralwidget,QWidget#loginRoot,QFrame#contentFrame { background:#211c27; }
                QFrame[panel="true"] { background:#2d2733; border-color:#403545; }
                QFrame[stat="true"] { background:#392535; border-color:#4d3043; }
                QLineEdit,QComboBox,QDateEdit,QMenu { background:#302734; color:#eee5ee; border-color:#53404e; }
                QPushButton { background:#382b3a; color:#eee5ee; border-color:#544151; }
                QFrame#tabs,QFrame[tabs="true"] { background:#382b3a; border-color:#544151; }
                QFrame[row="true"] { border-bottom-color:#443848; }
                QLabel[statValue="true"] { color:#f19aba; }
                QLabel[muted="true"],QLabel#subtitle { color:#b6a8ba; }
                QComboBox QAbstractItemView { background:#302734; color:#eee5ee; }
                QFrame[tone="rose"],QFrame[tone="peach"],QFrame[tone="cream"] { background:#442D3A; border-color:#624453; }
                QLabel[pageTitle="true"],QLabel[number="true"],QLabel[metric="true"] { color:#FFD9E6; }
                QDoubleSpinBox { background:#302734; color:#eee5ee; border-color:#624453; }
                QCalendarWidget QAbstractItemView,QCalendarWidget QToolButton { color:#F6DCE6; }
                QCalendarWidget QAbstractItemView { background:#302734; alternate-background-color:#442D3A; }
                QLabel[statCaption="true"] { color:#CFB5C4; }
                QLabel[section="true"] { color:#F3CDDE; }
                QLabel[eyebrow="true"] { color:#DDA0BD; }
                QLabel#homeSubtitle,QLabel#subscriptionsSubtitle,QLabel#paymentsSubtitle,QLabel#notificationsSubtitle,QLabel#settingsSubtitle { color:#C9ABBD; }
                QFrame#sidebarFrame QPushButton:checked { background:#FF3278; }
                QPushButton[primary="true"] { background:#FF3278; color:white; }
                QPushButton[flat="true"] { color:#FF9ABD; }
            """
        self.setStyleSheet(style)



    def polish_interface(self):
        self.searchInput.setMaximumWidth(920)
        self.searchInput.setMinimumHeight(48)
        self.searchInput.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.accountButton.setMinimumHeight(72)
        for lbl in [self.welcomeLabel, self.homeSubtitle, self.subscriptionsSubtitle, self.paymentsSubtitle, self.notificationsSubtitle, self.settingsSubtitle]:
            lbl.setWordWrap(True)
        for widget in [self.activeStatCard, self.monthlyStatCard, self.nearestStatCard, self.upcomingStatCard,
                       self.homeSubscriptionsPanel, self.subscriptionPanel, self.paymentsPanel, self.profilePanel,
                       self.notificationSettingsPanel, self.accountPanel]:
            apply_shadow(widget)

    def change_reminder_days(self, delta):
        self.reminder_days.setValue(max(self.reminder_days.minimum(), min(self.reminder_days.maximum(), self.reminder_days.value() + delta)))
        self.update_reminder_days_display()

    def update_reminder_days_display(self):
        if hasattr(self, 'reminder_value_label'):
            days = self.reminder_days.value()
            self.reminder_value_label.setText(f"{days} дн.")

    def bind_pages(self):
        """Connect the complete Designer forms to their data and actions."""
        self.stat_values = [self.activeValue, self.monthlyValue, self.nearestValue, self.upcomingValue]
        for field, symbol in [(self.activeStatIcon, "clipboard"), (self.monthlyStatIcon, "coins"),
                              (self.nearestStatIcon, "calendar"), (self.upcomingStatIcon, "calendar")]:
            field.setPixmap(icon(symbol).pixmap(30, 30))
        self.home_rows = self.homeRowsLayout
        self.sub_rows = self.subRowsLayout
        self.payment_rows = self.paymentRowsLayout
        self.notification_rows = self.notificationRowsLayout
        for rows in [self.home_rows, self.sub_rows, self.payment_rows, self.notification_rows, self.settingsBodyLayout]:
            rows.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.sub_panel = self.subscriptionPanel
        self.sub_tabs = {"active": self.activeTab, "inactive": self.inactiveTab, "all": self.allTab}
        for key, tab in self.sub_tabs.items():
            tab.clicked.connect(partial(self.filter_subscriptions, key))
        self.notification_tabs = {"all": self.allNotificationsTab, "unread": self.unreadNotificationsTab}
        for key, tab in self.notification_tabs.items():
            tab.clicked.connect(partial(self.filter_notifications, key))
        self.allSubscriptionsButton.clicked.connect(partial(self.navigate, "subscriptions"))
        self.addSubscriptionButton.clicked.connect(self.add_subscription)
        self.addSubscriptionButton.setIcon(icon("plus", True))
        self.addSubscriptionButton.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.addSubscriptionButton.customContextMenuRequested.connect(lambda point: self.add_personal_subscription())
        self.exportPaymentsButton.clicked.connect(self.export_menu)
        self.exportPaymentsButton.setIcon(icon("download"))
        self.markAllReadButton.clicked.connect(self.mark_all_read)
        self.markAllReadButton.setIcon(icon("check"))
        self.payment_period = self.paymentPeriodCombo
        self.payment_status = self.paymentStatusCombo
        self.payment_period.currentIndexChanged.connect(self.render_payments)
        self.payment_status.currentIndexChanged.connect(self.render_payments)
        self.checkPaymentsButton.clicked.connect(self.check_scheduled_payments)
        self.payment_total_caption = self.paymentTotalCaption
        self.payment_total = self.paymentTotal
        self.toggles = {"reminders": self.remindersToggle, "success": self.successToggle, "errors": self.errorsToggle}
        for field in [self.nameInput, self.surnameInput, self.emailInput]:
            field.textChanged.connect(self.settings_changed)
        self.themeInput.currentIndexChanged.connect(self.settings_changed)
        for toggle in self.toggles.values():
            toggle.toggled.connect(self.settings_changed)
            toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.changePasswordButton.clicked.connect(self.change_password)
        self.logoutButton.clicked.connect(self.logout)
        self.saveButton.clicked.connect(self.save_settings)
        self.resetButton.clicked.connect(self.load_settings)
        for btn in self.findChildren(QPushButton):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

    def add_feature_controls(self):
        """Small controls in existing Designer layouts; other roles untouched."""
        own = button('+ Своя подписка', self.add_personal_subscription, primary=True)
        self.sub_rows.insertWidget(0, own)
        self.personal_button = own

        remind = QWidget()
        line = hbox(remind, spacing=12)
        line.addWidget(label('Напоминать о платеже за', muted=True))

        self.reminder_days = QSpinBox()
        self.reminder_days.setRange(1, 30)
        self.reminder_days.setValue(int(self.preferences.get('reminder_days', 3)))
        self.reminder_days.hide()

        stepper = QFrame()
        stepper.setProperty('stepper', True)
        step_line = hbox(stepper, 6, 8)
        minus = button('−', lambda: self.change_reminder_days(-1))
        minus.setProperty('stepper', True)
        plus = button('+', lambda: self.change_reminder_days(1))
        plus.setProperty('stepper', True)
        self.reminder_value_label = label('', stepValue=True)
        self.reminder_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.reminder_value_label.setMinimumWidth(58)
        step_line.addWidget(minus)
        step_line.addWidget(self.reminder_value_label)
        step_line.addWidget(plus)
        line.addWidget(stepper)
        line.addWidget(label('до платежа', muted=True))
        line.addWidget(button('Сохранить', self.save_reminder_days, primary=True))
        line.addStretch()
        self.settingsBodyLayout.addWidget(remind)
        self.update_reminder_days_display()

    def render_home_features(self):
        tools = QWidget()
        bar = hbox(tools, spacing=8)
        for title, index in [('Аналитика', 0), ('Календарь', 1), ('Бюджет', 2), ('История', 3)]:
            bar.addWidget(button(title, partial(self.show_insights, index)))
        self.home_rows.addWidget(tools)
        current = self.repo.preferences(self.uid)
        limit = float(current.get('monthly_budget') or 0)
        cost = float(self.summary['monthly'])
        yearly = cost * 12
        budget = f'Лимит: {money(limit)} ₽ · осталось {money(max(0, limit-cost))} ₽' if limit else 'Лимит расходов не задан'
        insight = panel()
        col = vbox(insight, 16, 8)
        col.addWidget(label(f'Прогноз на год: {money(yearly)} ₽', section=True))
        col.addWidget(label(budget, muted=True))
        if limit and cost > limit:
            col.addWidget(label(f'Внимание: превышение бюджета на {money(cost-limit)} ₽'))
        self.home_rows.addWidget(insight)

    def show_insights(self, index):
        InsightsDialog(self, index).exec()

    def add_personal_subscription(self):
        if PersonalSubscriptionDialog(self).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def edit_subscription(self, sub):
        if EditSubscriptionDialog(self, sub).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def save_reminder_days(self):
        prefs = {**self.repo.preferences(self.uid), 'reminder_days': self.reminder_days.value()}
        with self.repo.transaction() as cur:
            self.repo._save_preferences(cur, self.uid, prefs)
        self.preferences = prefs
        self.toast('Срок напоминания сохранён.')

    def toast(self, text):
        self.statusLabel.setText(text)
        self.statusLabel.show()
        self.toast_timer.start(6500)

    def guarded(self, action, success=None):
        try:
            result = action()
            if success:
                self.toast(success)
            return True, result
        except Exception as error:
            QMessageBox.warning(self, "SubControl", str(error))
            return False, None








    def refresh(self):
        try:
            self.repo.refresh_reminders(self.uid)
            self.repo.refresh_failed_payment_notifications(self.uid)
            self.subscriptions = self.repo.subscriptions(self.uid)
            self.payments = self.repo.payments(self.uid)
            self.notifications = self.repo.notifications(self.uid)
            self.summary = self.repo.summary(self.uid)
            self.dashboard.refresh()
            self.render_home()
            self.render_subscriptions()
            self.render_payments()
            self.render_notifications()
            self.update_badges()
            unread = {n["notification_id"] for n in self.notifications if n["read_status"] != "Прочитано"}
            if self.seen_notifications is not None and self.tray:
                fresh = [n for n in self.notifications if n["notification_id"] in unread-self.seen_notifications]
                for note in fresh[:1]:
                    kind = "errors" if "ошиб" in note["title"].casefold() else "success" if "оплат" in note["title"].casefold() else "reminders"
                    if self.preferences[kind]:
                        self.tray.showMessage(note["title"], note["message"], QSystemTrayIcon.MessageIcon.Information, 5000)
            self.seen_notifications = unread
            return True
        except Exception as error:
            self.toast("Не удалось обновить данные: " + str(error))
            return False

    def check_scheduled_payments(self):
        if self.processing_payments or not self.isVisible():
            return
        self.processing_payments = True
        try:
            outcomes = self.simulator.process_due(self.uid)
            self.refresh()
            if outcomes:
                successes = sum(result['outcome'] == 'Успешно' for result in outcomes)
                self.toast(f'Получены ответы сервисов: успешно — {successes}, с ошибкой — {len(outcomes)-successes}. Чеки доступны в платежах.')
        except Exception as error:
            self.toast('Не удалось получить ответы сервисов: '+str(error))
        finally:
            self.processing_payments = False

    def update_badges(self):
        unread = sum(n["read_status"] != "Прочитано" for n in self.notifications)
        for widget in (self.navBadge, self.bellBadge):
            widget.setText(str(unread) if unread < 100 else "99+")
            widget.setVisible(unread > 0)
        self.bellButton.setAccessibleName(f"Уведомления, непрочитанных: {unread}")

    def matches(self, row, keys):
        return self.searchInput.text().strip().casefold() in " ".join(str(row.get(key, "")) for key in keys).casefold()

    def render_home(self):
        self.welcomeLabel.setText(f"Привет, {self.user['user_name']}!")
        self.accountButton.setText(f"{self.user['user_name']} {self.user['surname']}\nПользователь")
        self.accountButton.setToolTip(f"{self.user['user_name']} {self.user['surname']}")
        nearest = self.summary["nearest"]
        values = [str(self.summary["active"]), money(self.summary["monthly"])+" ₽",
                  f"{nearest.day} {MONTHS[nearest.month-1]}" if nearest else "Нет платежей", str(self.summary["upcoming"])]
        for index, (widget, value) in enumerate(zip(self.stat_values, values)):
            widget.setText(value)
            if index == 2:
                widget.setStyleSheet("font-size:18px;font-weight:700;")
        clear(self.home_rows)
        self.render_home_features()
        active = [s for s in self.subscriptions if s["us_status"] == "Активна" and self.matches(s, ["service_name", "plan_name"])]
        for sub in active[:5]:
            self.home_rows.addWidget(self.subscription_row(sub, compact=True))
        if not active:
            self.empty(self.home_rows, "Подписок пока нет" if not self.searchInput.text() else "Ничего не найдено", "Добавьте первый сервис, чтобы отслеживать платежи.", self.add_subscription)

    def subscription_row(self, sub, compact=False):
        row = QFrame()
        row.setProperty("row", True)
        row.setMinimumHeight(86 if compact else 116)
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = hbox(row, 18, 16)
        image = label()
        image.setPixmap(service_icon(sub["service_name"]).pixmap(46, 46))
        image.setFixedSize(46, 46)
        layout.addWidget(image)
        texts = vbox(spacing=5)
        title = label(sub["service_name"])
        title.setStyleSheet("font-weight:600;")
        title.setWordWrap(True)
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        texts.addWidget(title)
        texts.addWidget(label(sub["plan_name"]+(f" · {sub['duration_months']} мес." if compact else ""), muted=True))
        layout.addLayout(texts, 4)
        price = label(f"{money(sub['price'])} ₽ / {'мес.' if int(sub['duration_months']) == 1 else str(sub['duration_months'])+' мес.'}")
        price.setWordWrap(True)
        layout.addWidget(price, 3)
        active = sub["us_status"] == "Активна"
        failed = active and any(p['user_subscription_id'] == sub['user_subscription_id'] and p['status'] == 'Неуспешно' for p in self.payments)
        due = as_date(sub["next_payment_date"])
        soon = active and due and (due-date.today()).days <= 3
        status = "Ошибка оплаты" if failed else "Близится платёж" if soon else "Активна" if active else "Неактивна"
        status_layout = vbox(spacing=6)
        status_layout.addWidget(badge(status, "failed" if failed else "soon" if soon else "active" if active else "inactive"))
        if not compact:
            caption = f"Следующий платёж: {due:%d.%m.%Y}" if active and due else "Подписка отменена"
            small = label(caption, muted=True)
            small.setStyleSheet("font-size:11px;")
            status_layout.addWidget(small)
        layout.addLayout(status_layout, 3)
        menu = button("⋮", flat=True)
        menu.setProperty("menu", True)
        menu.setFixedSize(28, 34)
        menu.setAccessibleName("Действия: "+sub["service_name"])
        menu.clicked.connect(partial(self.subscription_menu, sub, menu))
        layout.addWidget(menu)
        return row

    def filter_subscriptions(self, key):
        self.subscription_filter = key
        self.render_subscriptions()

    def render_subscriptions(self):
        if not hasattr(self, "subscriptions"):
            return
        counts = {"active": sum(s["us_status"] == "Активна" for s in self.subscriptions),
                  "inactive": sum(s["us_status"] != "Активна" for s in self.subscriptions), "all": len(self.subscriptions)}
        for key, title in [("active", "Активные"), ("inactive", "Неактивные"), ("all", "Все")]:
            self.sub_tabs[key].setText(f"{title} ({counts[key]})")
            self.sub_tabs[key].setChecked(self.subscription_filter == key)
        # Card grid owns its children; preserve the Designer scroll container.
        found = []
        for sub in self.subscriptions:
            active = sub["us_status"] == "Активна"
            if self.subscription_filter == "active" and not active or self.subscription_filter == "inactive" and active:
                continue
            if self.matches(sub, ["service_name", "plan_name"]):
                found.append(sub)
        self.dashboard.render_subscriptions(found)

    def empty(self, layout, title, subtitle, action=None):
        widget = QWidget()
        body = vbox(widget, 32, 12)
        for text, muted in [(title, False), (subtitle, True)]:
            text_label = label(text, muted=muted)
            text_label.setWordWrap(True)
            text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            body.addWidget(text_label)
        if action:
            body.addWidget(button("Добавить подписку", action, primary=True), 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(widget)

    def add_subscription(self):
        dialog = CatalogDialog(self.repo, self.uid, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.searchInput.clear()
            self.subscription_filter = "active"
            self.refresh()
            self.check_scheduled_payments()

    def subscription_menu(self, sub, anchor):
        menu = QMenu(self)
        menu.addAction("Подробнее", partial(self.subscription_details, sub))
        if sub['us_status'] == 'Активна':
            menu.addAction('Редактировать параметры', partial(self.edit_subscription, sub))
        if sub.get("official_website"):
            menu.addAction("Открыть сайт сервиса", partial(self.open_website, sub["official_website"]))
        menu.addSeparator()
        if sub["us_status"] == "Активна":
            menu.addAction("Перейти к платежам", partial(self.navigate, "payments"))
            menu.addAction("Приостановить подписку", partial(self.pause_subscription, sub))
            menu.addAction("Отменить подписку", partial(self.cancel_subscription, sub))
        elif sub["us_status"] == "Приостановлена":
            menu.addAction("Возобновить подписку", partial(self.resume_subscription, sub))
        else:
            menu.addAction("Подключить снова", partial(self.reactivate, sub))
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def pause_subscription(self, sub):
        ok, _ = self.guarded(lambda: pause_subscription(self.repo, self.uid, sub['user_subscription_id']), 'Подписка приостановлена.')
        if ok:
            self.refresh()

    def resume_subscription(self, sub):
        ok, _ = self.guarded(lambda: resume_subscription(self.repo, self.uid, sub['user_subscription_id']), 'Подписка возобновлена.')
        if ok:
            self.refresh()
            self.check_scheduled_payments()

    def subscription_details(self, sub):
        dialog = QDialog(self)
        dialog.setWindowTitle(sub["service_name"])
        dialog.setMinimumWidth(430)
        root = vbox(dialog, 24, 14)
        image = label()
        image.setPixmap(service_icon(sub["service_name"]).pixmap(58, 58))
        root.addWidget(image)
        root.addWidget(label(sub["service_name"], section=True))
        for title, value in [("Тариф", sub["plan_name"]), ("Стоимость", f"{money(sub['price'])} ₽ / {sub['duration_months']} мес."),
                             ("Статус", sub["us_status"]), ("Подключена", sub["start_date"]),
                             ("Следующий платёж" if sub["us_status"] == "Активна" else "Дата окончания", sub["next_payment_date"] if sub["us_status"] == "Активна" else sub["end_date"])]:
            if "дата" in title.casefold() or title in ["Подключена", "Следующий платёж"]:
                value = as_date(value).strftime("%d.%m.%Y") if value else "—"
            root.addWidget(label(f"{title}: {value}"))
        root.addWidget(button("Закрыть", dialog.accept))
        dialog.exec()

    def open_website(self, url):
        parsed = QUrl(url)
        if parsed.scheme() not in ("http", "https") or not parsed.host():
            self.toast("У сервиса не указан корректный адрес сайта.")
        elif not QDesktopServices.openUrl(parsed):
            self.toast("Не удалось открыть браузер.")

    def cancel_subscription(self, sub):
        answer = QMessageBox.question(self, "Отмена подписки", f"Отменить {sub['service_name']}? Будущие платежи будут отменены, история оплат сохранится.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            ok, _ = self.guarded(lambda: self.repo.cancel_subscription(self.uid, sub["user_subscription_id"]), "Подписка отменена.")
            if ok:
                self.refresh()

    def reactivate(self, sub):
        ok, _ = self.guarded(lambda: self.repo.add_subscription(self.uid, sub["plan_id"]), "Подписка подключена снова.")
        if ok:
            self.refresh()

    def render_payments(self, *args):
        if not hasattr(self, "payments"):
            return
        clear(self.payment_rows)
        today = date.today()
        previous = today.replace(day=1)
        from datetime import timedelta
        previous -= timedelta(days=1)
        self.filtered_payments = []
        for pay in self.payments:
            dt = as_date(pay["payment_date"])
            index = self.payment_period.currentIndex()
            if index == 1 and (dt.year, dt.month) != (today.year, today.month):
                continue
            if index == 2 and (dt.year, dt.month) != (previous.year, previous.month):
                continue
            if self.payment_status.currentIndex() and self.payment_status.currentText() != pay["status"]:
                continue
            if not self.matches(pay, ["service_name", "plan_name", "amount", "status", "payment_date"]):
                continue
            self.filtered_payments.append(pay)
            row = QFrame()
            row.setProperty("row", True)
            row.setMinimumHeight(74)
            row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            layout = hbox(row, 18, 16)
            layout.addWidget(label(dt.strftime("%d.%m.%Y")), 2)
            service = hbox(spacing=10)
            image = label()
            image.setPixmap(service_icon(pay["service_name"]).pixmap(28, 28))
            image.setFixedSize(28, 28)
            service.addWidget(image)
            title = label(pay["service_name"])
            title.setWordWrap(True)
            title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            service.addWidget(title, 1)
            layout.addLayout(service, 4)
            layout.addWidget(label(money(pay["amount"])+" ₽"), 2)
            badge_wrap = hbox()
            badge_wrap.addWidget(badge(pay["status"], {"Успешно": "paid", "Ожидается": "pending", "Неуспешно": "failed"}.get(pay["status"], "inactive")))
            badge_wrap.addStretch()
            layout.addLayout(badge_wrap, 2)
            actions = button("⋮", flat=True)
            actions.setProperty("menu", True)
            actions.setFixedSize(28, 32)
            actions.setAccessibleName(f"Действия с платежом {pay['payment_id']}")
            actions.clicked.connect(partial(self.payment_menu, pay, actions))
            layout.addWidget(actions)
            self.payment_rows.addWidget(row)
        if not self.filtered_payments:
            self.empty(self.payment_rows, "Платежей не найдено", "Измените период, статус или поисковый запрос.")
        from decimal import Decimal
        total = sum((Decimal(str(p["amount"])) for p in self.filtered_payments if p["status"] == "Успешно"), Decimal(0))
        self.payment_total_caption.setText("Оплачено · " + self.payment_period.currentText().lower())
        self.payment_total.setText(money(total)+" ₽")

    def payment_menu(self, pay, anchor):
        menu = QMenu(self)
        if pay["status"] in ("Ожидается", "Неуспешно"):
            menu.addAction("Учебная оплата" if pay['status'] == 'Ожидается' else 'Повторить оплату', partial(self.pay, pay))
        if pay["status"] == "Успешно":
            menu.addAction('Открыть чек', partial(self.open_receipt, pay))
            menu.addAction("Сохранить PDF-квитанцию", partial(self.receipt, pay))
        menu.addAction("Информация о платеже", partial(self.payment_details, pay))
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def payment_details(self, pay):
        events = self.repo.payment_events(self.uid, pay['payment_id'])
        attempts = '\n'.join(f"Попытка {e['attempt']}: {e['outcome']} · {e['created_at']}"+(f"\n{e['failure_reason']}" if e['failure_reason'] else '') for e in events)
        QMessageBox.information(self, "Платёж", f"№ SC-{pay['payment_id']:06d}\n{pay['service_name']} · {pay['plan_name']}\nДата: {as_date(pay['payment_date']):%d.%m.%Y}\nСумма: {money(pay['amount'])} ₽\nСтатус: {pay['status']}\n\n{attempts}\n\nУчебная имитация ответов сервисов. Реального банковского списания нет.")

    def pay(self, payment):
        was_active = self.background_timer.isActive()
        self.background_timer.stop()
        self.initial_payment_check.stop()
        dialog = PaymentDialog(self.simulator, self.uid, payment, self)
        dialog.exec()
        if dialog.changed:
            self.refresh()
        if was_active:
            self.background_timer.start(60000)

    def open_receipt(self, payment):
        ok, path = self.guarded(lambda: self.receipts.ensure(self.uid, payment['payment_id']))
        if ok and not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve()))):
            self.toast('Не удалось открыть PDF. Сохраните чек через меню платежа.')

    def receipt(self, payment):
        fresh = next((p for p in self.repo.payments(self.uid) if p["payment_id"] == payment["payment_id"] and p["status"] == "Успешно"), None)
        if not fresh:
            self.toast("Оплаченный платёж не найден.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить квитанцию", f"receipt_SC-{fresh['payment_id']:06d}.pdf", "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        def save():
            source = self.receipts.ensure(self.uid, fresh['payment_id'])
            if source.resolve() != Path(path).resolve():
                shutil.copyfile(source, path)
        self.guarded(save, "Квитанция сохранена: "+path)

    def export_menu(self):
        menu = QMenu(self)
        menu.addAction("Сохранить в CSV", partial(self.export_payments, "csv"))
        menu.addAction("Сохранить в PDF", partial(self.export_payments, "pdf"))
        menu.exec(self.cursor().pos())

    def export_payments(self, kind):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт платежей", "payments."+kind, kind.upper()+" (*."+kind+")")
        if not path:
            return
        if not path.lower().endswith("."+kind):
            path += "."+kind
        columns = ["Дата", "Сервис", "Тариф", "Сумма, ₽", "Статус"]
        rows = [[as_date(p["payment_date"]).strftime("%d.%m.%Y"), p["service_name"], p["plan_name"], str(p["amount"]), p["status"]] for p in self.filtered_payments]
        def save():
            if kind == "pdf":
                write_pdf(path, "История платежей", columns, rows, f"Оплачено по текущему фильтру: {self.payment_total.text()}")
            else:
                with open(path, "w", encoding="utf-8-sig", newline="") as stream:
                    writer = csv.writer(stream, delimiter=";")
                    # Prevent spreadsheet formula execution in externally supplied labels.
                    writer.writerow(columns)
                    writer.writerows([["'"+cell if str(cell).startswith(("=", "+", "-", "@")) else cell for cell in row] for row in rows])
        self.guarded(save, "История платежей сохранена: "+path)

    def filter_notifications(self, key):
        self.notification_filter = key
        self.render_notifications()

    def render_notifications(self):
        if not hasattr(self, "notifications"):
            return
        clear(self.notification_rows)
        for key, btn in self.notification_tabs.items():
            btn.setChecked(key == self.notification_filter)
        found = []
        for note in self.notifications:
            from analytics import note_kind
            kind = ['', 'reminders', 'success', 'errors', 'system'][self.dashboard.note_type.currentIndex()]
            if kind and note_kind(note) != kind:
                continue
            unread = note["read_status"] != "Прочитано"
            if self.notification_filter == "unread" and not unread:
                continue
            if not self.matches(note, ["title", "message"]):
                continue
            found.append(note)
            frame = panel()
            layout = vbox(frame, 20, 9)
            head = hbox(spacing=12)
            title = label(note["title"], section=True)
            title.setWordWrap(True)
            head.addWidget(title, 1)
            if unread:
                head.addWidget(badge("Новое", "pending"))
            layout.addLayout(head)
            message = label(note["message"], muted=True)
            message.setWordWrap(True)
            layout.addWidget(message)
            bottom = hbox(spacing=12)
            bottom.addWidget(label(str(note["created_at"])[:16], muted=True), 1)
            if unread:
                bottom.addWidget(button("Прочитано", partial(self.mark_one_read, note["notification_id"]), flat=True, symbol="check"))
            layout.addLayout(bottom)
            self.notification_rows.addWidget(frame)
        if not found:
            self.empty(self.notification_rows, "Новых уведомлений нет" if self.notification_filter == "unread" else "Уведомлений не найдено", "Здесь появятся напоминания о предстоящих платежах.")

    def mark_one_read(self, nid):
        ok, _ = self.guarded(lambda: self.repo.mark_read(self.uid, nid))
        if ok:
            self.refresh()

    def mark_all_read(self):
        ok, _ = self.guarded(lambda: self.repo.mark_read(self.uid), "Все уведомления прочитаны.")
        if ok:
            self.refresh()

    def load_settings(self):
        self.loading_settings = True
        self.preferences = self.repo.preferences(self.uid)
        self.nameInput.setText(self.user["user_name"])
        self.surnameInput.setText(self.user["surname"])
        self.emailInput.setText(self.preferences["email"] or self.user.get("email", ""))
        self.themeInput.setCurrentText(self.preferences["theme"])
        for key, toggle in self.toggles.items():
            toggle.setChecked(bool(self.preferences[key]))
        self.loading_settings = False
        self.settings_dirty = False
        self.saveButton.setEnabled(False)
        self.resetButton.setEnabled(False)
        self.dirtyLabel.clear()
        self.reminder_days.setValue(int(self.preferences.get("reminder_days", 3)))
        self.update_reminder_days_display()

    def settings_changed(self, *args):
        if self.loading_settings:
            return
        self.settings_dirty = True
        self.saveButton.setEnabled(True)
        self.resetButton.setEnabled(True)
        self.dirtyLabel.setText("Есть несохранённые изменения")

    def save_settings(self):
        ok, _ = self.guarded(lambda: self.repo.save_profile(self.uid, self.nameInput.text(), self.surnameInput.text(), self.emailInput.text(), self.themeInput.currentText(), {k: t.isChecked() for k, t in self.toggles.items()}))
        if not ok:
            return False
        self.user["user_name"] = self.nameInput.text().strip()
        self.user["surname"] = self.surnameInput.text().strip()
        self.load_settings()
        self.apply_theme()
        self.dashboard.refresh()
        self.render_home()
        self.toast("Настройки сохранены.")
        return True

    def settle_settings(self):
        if not self.settings_dirty:
            return True
        answer = QMessageBox.question(self, "Настройки", "Сохранить изменения профиля?", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save_settings()
        self.load_settings()
        return True

    def change_password(self):
        if PasswordDialog(self.repo, self.uid, self).exec() == QDialog.DialogCode.Accepted:
            self.toast("Пароль изменён.")

    def profile_menu(self):
        menu = QMenu(self)
        menu.addAction("Настройки аккаунта", partial(self.navigate, "settings"))
        menu.addSeparator()
        menu.addAction("Выйти из аккаунта", self.logout)
        menu.exec(self.avatarButton.mapToGlobal(self.avatarButton.rect().bottomRight()))

    def navigate(self, key, checked=False):
        if key != self.page and not self.settle_settings():
            for page in PAGES:
                getattr(self, page+"Button").setChecked(page == self.page)
            return
        self.page = key
        self.stackedWidget.setCurrentWidget(getattr(self, key+"Page"))
        for page in PAGES:
            getattr(self, page+"Button").setChecked(page == key)
        self.searchInput.setPlaceholderText({"payments": "Поиск по платежам, сервисам...", "notifications": "Поиск в уведомлениях..."}.get(key, "Поиск по подпискам, сервисам..."))
        # Navigation starts with a fresh search; filters retain their state.
        self.searchInput.blockSignals(True)
        self.searchInput.clear()
        self.searchInput.blockSignals(False)
        if key == "settings":
            if not self.settings_dirty:
                self.load_settings()
        else:
            {"home": self.render_home, "subscriptions": self.render_subscriptions,
             "payments": self.render_payments, "notifications": self.render_notifications}[key]()

    def search_changed(self, text):
        if self.page == "settings" and text:
            if not self.settle_settings():
                self.searchInput.blockSignals(True)
                self.searchInput.clear()
                self.searchInput.blockSignals(False)
                return
            self.navigate("subscriptions")
            self.searchInput.setText(text)
            return
        if self.page != "settings":
            {"home": self.render_home, "subscriptions": self.render_subscriptions,
             "payments": self.render_payments, "notifications": self.render_notifications}[self.page]()

    def logout(self):
        if self.settle_settings():
            self.background_timer.stop()
            self.initial_payment_check.stop()
            if self.tray:
                self.tray.hide()
            self.logged_out.emit()
            self.close()

    def restore_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.navigate("notifications")

    def closeEvent(self, event):
        if not self.settle_settings():
            event.ignore()
            return
        self.background_timer.stop()
        self.initial_payment_check.stop()
        if self.tray:
            self.tray.hide()
        event.accept()
