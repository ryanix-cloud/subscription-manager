"""Compact user tools: spending, calendar, budget and history."""
from datetime import date
from decimal import Decimal
from PyQt6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTabWidget, QCalendarWidget, QProgressBar, QDoubleSpinBox,
    QListWidget, QComboBox, QDateEdit, QFormLayout, QLineEdit, QMessageBox)
from PyQt6.QtCore import QDate
from PyQt6.QtGui import QTextCharFormat, QColor
from analytics import monthly_history, monthly_cost
from repository import money, as_date
from extra_repository import history, add_personal, edit_subscription

PINK = '#FF3278'


def heading(text):
    item = QLabel(text)
    item.setStyleSheet('font-size:19px;font-weight:bold;color:#B5003D;')
    return item


class InsightsDialog(QDialog):
    def __init__(self, window, tab=0):
        super().__init__(window)
        self.win = window
        self.repo, self.uid = window.repo, window.uid
        self.setWindowTitle('Финансовый обзор')
        self.resize(780, 650)
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        root.addWidget(tabs)
        for name, make in [('Аналитика', self.analytics), ('Календарь', self.calendar),
                           ('Бюджет', self.budget), ('История', self.history_tab)]:
            page = QWidget()
            page.setLayout(QVBoxLayout())
            tabs.addTab(page, name)
            make(page.layout())
        tabs.setCurrentIndex(tab)
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        root.addWidget(close)

    def analytics(self, layout):
        active = [s for s in self.win.subscriptions if s['us_status'] == 'Активна']
        monthly = monthly_cost(active)
        layout.addWidget(heading('Мои расходы на подписки'))
        layout.addWidget(QLabel(f'Прогноз за месяц: {money(monthly)} ₽     За год: {money(monthly * 12)} ₽'))
        by_service = sorted(active, key=lambda s: Decimal(str(s['price'])) / max(1, s['duration_months']), reverse=True)
        layout.addWidget(QLabel('Самые дорогие подписки (в пересчёте на месяц)'))
        for sub in by_service[:5]:
            layout.addWidget(QLabel(f"• {sub['service_name']}: {money(Decimal(str(sub['price'])) / max(1,sub['duration_months']))} ₽"))
        layout.addWidget(QLabel('Фактически оплачено за последние шесть месяцев'))
        points = monthly_history(self.win.payments)
        try:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
            from matplotlib.figure import Figure
            figure = Figure(figsize=(7, 3), facecolor='#FFFAFC')
            axes = figure.add_subplot(111)
            axes.set_facecolor('#FFFAFC')
            axes.bar([d.strftime('%m.%Y') for d, _ in points], [float(v) for _, v in points], color=PINK)
            axes.spines[['top', 'right']].set_visible(False)
            figure.tight_layout()
            layout.addWidget(FigureCanvasQTAgg(figure), 1)
        except ImportError:
            for day, value in points:
                layout.addWidget(QLabel(f'{day:%m.%Y}: {money(value)} ₽'))
        layout.addStretch()

    def calendar(self, layout):
        layout.addWidget(heading('Календарь платежей'))
        layout.addWidget(QLabel('Розовым отмечены дни с ожидаемыми платежами.'))
        cal = QCalendarWidget()
        layout.addWidget(cal)
        bills = [p for p in self.win.payments if p['status'] == 'Ожидается']
        fmt = QTextCharFormat()
        fmt.setBackground(QColor('#FF98BB'))
        for p in bills:
            d = as_date(p['payment_date'])
            if d:
                cal.setDateTextFormat(QDate(d.year, d.month, d.day), fmt)
        result = QListWidget()
        layout.addWidget(result)
        def show(qdate):
            result.clear()
            day = qdate.toPyDate()
            found = [p for p in bills if as_date(p['payment_date']) == day]
            for p in found:
                result.addItem(f"{p['service_name']} · {money(p['amount'])} ₽ · ожидается")
            if not found:
                result.addItem('В этот день плановых платежей нет')
            else:
                result.addItem(f"Итого: {money(sum(Decimal(str(p['amount'])) for p in found))} ₽")
        cal.selectionChanged.connect(lambda: show(cal.selectedDate()))
        show(cal.selectedDate())

    def budget(self, layout):
        layout.addWidget(heading('Бюджет на месяц'))
        monthly = monthly_cost(self.win.subscriptions)
        limit = Decimal(str(self.repo.preferences(self.uid).get('monthly_budget') or 0))
        layout.addWidget(QLabel(f'Прогнозируемые расходы: {money(monthly)} ₽'))
        form = QHBoxLayout()
        edit = QDoubleSpinBox()
        edit.setRange(0, 100000000)
        edit.setDecimals(2)
        edit.setSuffix(' ₽')
        edit.setValue(float(limit))
        form.addWidget(QLabel('Месячный лимит:'))
        form.addWidget(edit)
        save = QPushButton('Сохранить лимит')
        save.setProperty('primary', True)
        form.addWidget(save)
        layout.addLayout(form)
        bar = QProgressBar()
        info = QLabel()
        layout.addWidget(bar)
        layout.addWidget(info)
        def update():
            amount = Decimal(str(edit.value()))
            bar.setValue(min(100, int(monthly / amount * 100)) if amount else 0)
            if not amount:
                info.setText('Лимит пока не установлен')
            elif monthly > amount:
                info.setText(f'Превышение лимита на {money(monthly-amount)} ₽')
            else:
                info.setText(f'До лимита осталось {money(amount-monthly)} ₽')
        def save_budget():
            try:
                self.repo.save_budget(self.uid, edit.value())
                update()
                self.win.render_home()
                QMessageBox.information(self, 'Бюджет', 'Лимит сохранён')
            except Exception as e:
                QMessageBox.warning(self, 'Бюджет', str(e))
        edit.valueChanged.connect(update)
        save.clicked.connect(save_budget)
        update()
        layout.addStretch()

    def history_tab(self, layout):
        layout.addWidget(heading('История изменений подписок'))
        records = history(self.repo, self.uid)
        widget = QListWidget()
        layout.addWidget(widget)
        for row in records:
            widget.addItem(f"{row['service_name']} · {row.get('old_status') or 'Создана'} → {row['new_status']} · {row.get('comment') or ''}")
        if not records:
            widget.addItem('Изменений пока нет')


class PersonalSubscriptionDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle('Своя подписка')
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.name.setPlaceholderText('Например, онлайн-курс')
        self.price = QDoubleSpinBox()
        self.price.setMaximum(100000000)
        self.price.setSuffix(' ₽')
        self.months = QComboBox()
        for n in (1, 3, 6, 12):
            self.months.addItem(f'{n} мес.', n)
        form.addRow('Название сервиса', self.name)
        form.addRow('Стоимость', self.price)
        form.addRow('Период оплаты', self.months)
        add = QPushButton('Добавить подписку')
        add.setProperty('primary', True)
        form.addRow(add)
        add.clicked.connect(self.save)

    def save(self):
        try:
            add_personal(self.win.repo, self.win.uid, self.name.text(), self.price.value(), self.months.currentData())
        except Exception as error:
            QMessageBox.warning(self, 'Подписка', str(error))
            return
        self.accept()


class EditSubscriptionDialog(QDialog):
    def __init__(self, win, sub):
        super().__init__(win)
        self.win, self.sub = win, sub
        self.setWindowTitle('Изменить подписку')
        form = QFormLayout(self)
        form.addRow(QLabel(f"{sub['service_name']} · {sub['plan_name']}"))
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        d = as_date(sub['next_payment_date']) or date.today()
        self.date.setDate(QDate(d.year, d.month, d.day))
        form.addRow('Дата следующего платежа', self.date)
        self.price = QDoubleSpinBox()
        self.price.setRange(0, 100000000)
        self.price.setValue(float(sub['price']))
        self.price.setSuffix(' ₽')
        owner = win.repo.one('SELECT user_id FROM personal_plans WHERE plan_id=%s', (sub['plan_id'],))
        self.personal = bool(owner and owner['user_id'] == win.uid)
        self.price.setEnabled(self.personal)
        form.addRow('Стоимость (для личных тарифов)', self.price)
        save = QPushButton('Сохранить')
        save.setProperty('primary', True)
        form.addRow(save)
        save.clicked.connect(self.save)

    def save(self):
        try:
            edit_subscription(self.win.repo, self.win.uid, self.sub['user_subscription_id'],
                              self.date.date().toPyDate(), self.price.value())
            self.accept()
        except Exception as error:
            QMessageBox.warning(self, 'Подписка', str(error))
