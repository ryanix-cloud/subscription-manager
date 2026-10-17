"""Data-driven cards supplement the editable Designer forms."""
from datetime import date
from decimal import Decimal
from functools import partial

from PyQt6.QtCore import Qt, QDate, QRectF
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QFont, QTextCharFormat, QPixmap
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout,
    QGridLayout, QCalendarWidget, QProgressBar, QDoubleSpinBox, QComboBox, QScrollArea,
    QSizePolicy, QAbstractSpinBox, QLayout, QGraphicsDropShadowEffect)
from repository import money, as_date
from analytics import monthly_history, month_spending, monthly_cost, calendar_bills, note_kind
from pathlib import Path


def illustration(name, width, height):
    image = QLabel()
    image.setObjectName('illustration')
    image.setFixedSize(width, height)
    image.setAlignment(Qt.AlignmentFlag.AlignCenter)
    image.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    image.setPixmap(QPixmap(str(Path(__file__).resolve().parent/'assets'/'illustrations'/f'{name}.png')).scaled(
        width, height, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
    return image


def card(title, subtitle=None, tone=None):
    from user_window import panel, vbox, label
    frame = panel()
    if tone:
        frame.setProperty('tone', tone)
    layout = vbox(frame, 22, 12)
    layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
    title_label = label(title, section=True)
    title_label.setWordWrap(True)
    title_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    layout.addWidget(title_label)
    if subtitle:
        text = label(subtitle, muted=True)
        text.setWordWrap(True)
        text.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        layout.addWidget(text)
    shadow = QGraphicsDropShadowEffect(frame)
    shadow.setBlurRadius(34)
    shadow.setOffset(0, 10)
    shadow.setColor(QColor(221, 180, 198, 95))
    frame.setGraphicsEffect(shadow)
    return frame, layout


def metric(layout, caption, value):
    from user_window import label
    row = QHBoxLayout()
    row.addWidget(label(caption, muted=True), 1)
    text = label(value, metric=True)
    row.addWidget(text)
    layout.addLayout(row)


class ExpenseChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.points = []
        self.setMinimumHeight(150)
        self.setAccessibleName('Оплаченные расходы за шесть месяцев')

    def set_payments(self, payments):
        self.points = monthly_history(payments)
        self.setToolTip('\n'.join(f'{d:%m.%Y}: {money(v)} ₽' for d, v in self.points))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        maximum = max([float(v) for _, v in self.points]+[1])
        baseline = h-27
        p.setFont(QFont('Golos Text', 9))
        for i in range(3):
            y = 18 + i*(baseline-18)/2
            p.setPen(QPen(QColor('#E5CCD5'), 1, Qt.PenStyle.DashLine))
            p.drawLine(0, int(y), w, int(y))
        for i, (day, amount) in enumerate(self.points):
            slot = w/6
            bar = min(42, slot*0.55)
            height = max(3, float(amount)/maximum*(baseline-27))
            x = (i+0.5)*slot-bar/2
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor('#FF1464' if i == 5 else '#FF73A2'))
            p.drawRoundedRect(QRectF(x, baseline-height, bar, height), 7, 7)
            dark = self.window().preferences.get('theme') == 'Тёмная'
            p.setPen(QColor('#D8B9C7' if dark else '#795B69'))
            p.drawText(QRectF(i*slot, baseline+5, slot, 20), Qt.AlignmentFlag.AlignCenter,
                       ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'][day.month-1])
            if amount:
                p.drawText(QRectF(i*slot, baseline-height-19, slot, 18), Qt.AlignmentFlag.AlignCenter, money(amount))


class Dashboard:
    def __init__(self, window):
        from user_window import button, label, hbox, vbox
        self.w = w = window
        self.last_warning = None
        w.resize(1440, 940)
        w.setMinimumSize(1120, 760)
        w.sidebarFrame.setFixedWidth(244)
        w.navBadge.move(184, 16)
        kicker = label('ПОДПИСКИ  /  РАСХОДЫ  /  ПЛАНЫ', eyebrow=True)
        w.homeTitlesLayout.insertWidget(0, kicker)
        w.homeHeadingLayout.addWidget(illustration('finance', 220, 144))
        w.homeSubtitle.setText('Подписки, расходы и планы — всё под контролем.')
        w.subscriptionsSubtitle.setText('Управляйте сервисами и находите возможности сэкономить.')
        w.paymentsSubtitle.setText('История операций, чеки и ответы сервисов.')
        w.notificationsSubtitle.setText('Важные события и напоминания в одном месте.')
        w.settingsSubtitle.setText('Профиль, внешний вид и ваши финансовые привычки.')
        for field in [w.welcomeLabel, w.subscriptionsTitle, w.paymentsTitle, w.notificationsTitle, w.settingsTitle]:
            field.setProperty('pageTitle', True)
        for i, frame in enumerate([w.activeStatCard,w.monthlyStatCard,w.nearestStatCard,w.upcomingStatCard]):
            frame.setProperty('tone', ['rose','peach','cream','rose'][i])
        for value in w.stat_values:
            value.setProperty('number', True)

        # Home has a single scroll surface so compact windows retain every block.
        home_body = QWidget()
        body = QVBoxLayout(home_body)
        body.setContentsMargins(0,0,0,0)
        body.setSpacing(18)
        while w.homeLayout.count():
            item = w.homeLayout.takeAt(0)
            if item.widget():
                body.addWidget(item.widget())
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(home_body)
        w.homeLayout.addWidget(area)
        analytics = QHBoxLayout()
        analytics.setSpacing(18)
        chart, chart_layout = card('Расходы по месяцам', 'Только успешные оплаты · последние 6 месяцев', 'rose')
        self.chart = ExpenseChart()
        chart_layout.addWidget(self.chart)
        analytics.addWidget(chart, 3)
        budget, b = card('Месячный бюджет', 'Лимит помогает держать расходы под контролем.', 'peach')
        self.budget_text = label('', number=True)
        b.addWidget(self.budget_text)
        self.budget_bar = QProgressBar()
        self.budget_bar.setTextVisible(False)
        self.budget_bar.setFixedHeight(9)
        b.addWidget(self.budget_bar)
        self.budget_hint = label('', muted=True)
        self.budget_hint.setWordWrap(True)
        b.addWidget(self.budget_hint)
        edit = hbox(spacing=8)
        self.limit = QDoubleSpinBox()
        self.limit.setRange(0, 100000000)
        self.limit.setDecimals(0)
        self.limit.setSuffix(' ₽')
        self.limit.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.limit.setSpecialValueText('Без лимита')
        self.limit.setValue(float(w.preferences.get('monthly_budget',0)))
        self.limit.setAccessibleName('Месячный бюджет в рублях')
        edit.addWidget(self.limit, 1)
        edit.addWidget(button('Задать', self.save_budget, primary=True))
        b.addLayout(edit)
        analytics.addWidget(budget, 2)
        body.insertLayout(2, analytics)
        bottom = QHBoxLayout()
        bottom.setSpacing(18)
        body.removeWidget(w.homeSubscriptionsPanel)
        w.homeSubscriptionsPanel.setMinimumHeight(310)
        bottom.addWidget(w.homeSubscriptionsPanel, 3)
        calendar, c = card('Календарь платежей')
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(False)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar.setNavigationBarVisible(True)
        self.calendar.setMinimumWidth(280)
        self.calendar.setFixedHeight(215)
        self.calendar.selectionChanged.connect(self.show_day)
        c.addWidget(self.calendar)
        self.day_details = label('', muted=True)
        self.day_details.setWordWrap(True)
        c.addWidget(self.day_details)
        c.addWidget(button('Все платежи →', partial(w.navigate, 'payments'), flat=True))
        bottom.addWidget(calendar, 2)
        body.addLayout(bottom)

        self.sidebars = {}
        for page, main_widget, layout, title in [
            ('subscriptions', w.subscriptionPanel, w.subscriptionsLayout, 'Ваш портфель'),
            ('payments', w.paymentsPanel, w.paymentsLayout, 'Контроль платежей'),
            ('notifications', w.notificationsScrollArea, w.notificationsLayout, 'Центр внимания')]:
            layout.removeWidget(main_widget)
            columns = hbox(spacing=22)
            columns.addWidget(main_widget, 1)
            side = QWidget()
            side.setFixedWidth(265)
            side_layout = vbox(side, 0, 20)
            side_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            if page == 'notifications':
                side_layout.setAlignment(Qt.AlignmentFlag(0))
                side_layout.setSpacing(24)
                side_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
                side.setMinimumWidth(0)
                side.setMaximumWidth(16777215)
                side_area = QScrollArea()
                side_area.setFixedWidth(265)
                side_area.setWidgetResizable(True)
                side_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                side_area.setWidget(side)
                columns.addWidget(side_area)
            else:
                columns.addWidget(side)
            layout.addLayout(columns, 1)
            self.sidebars[page] = side_layout

        self.sub_sort = QComboBox()
        self.sub_sort.addItems(['По дате оплаты', 'Сначала дороже', 'По названию'])
        self.sub_sort.setAccessibleName('Сортировка подписок')
        w.subscriptionTabWrapperLayout.addWidget(self.sub_sort)
        self.sub_sort.currentIndexChanged.connect(w.render_subscriptions)

        self.note_type = QComboBox()
        self.note_type.addItems(['Все события','Напоминания','Успешные оплаты','Ошибки','Другие события'])
        w.notificationTabWrapperLayout.addWidget(self.note_type)
        self.note_type.currentIndexChanged.connect(w.render_notifications)
        # Designer settings panels are rearranged into two usable columns.
        for frame in [w.profilePanel, w.notificationSettingsPanel, w.accountPanel]:
            w.settingsBodyLayout.removeWidget(frame)
        columns = hbox(spacing=18)
        left, right = QWidget(), QWidget()
        ll, rr = vbox(left,0,18), vbox(right,0,18)
        ll.addWidget(w.profilePanel)
        profile, p = card('Ваш аккаунт', tone='rose')
        self.profile_info = label('', muted=True)
        self.profile_info.setWordWrap(True)
        profile_row = hbox(spacing=12)
        profile_row.addWidget(self.profile_info, 1)
        profile_row.addWidget(illustration('finance', 90, 84))
        p.addLayout(profile_row)
        ll.addWidget(profile)
        ll.addStretch()
        rr.addWidget(w.notificationSettingsPanel)
        rr.addWidget(w.accountPanel)
        tips, t = card('Настройте свой ритм', tone='cream')
        text = label('Бюджет задаётся на главной. Напоминания предупреждают о ближайших списаниях. Тему можно переключить в профиле.', muted=True)
        text.setWordWrap(True)
        t.addWidget(text)
        t.addWidget(button('Открыть бюджет →', partial(w.navigate,'home'), flat=True))
        rr.addWidget(tips)
        rr.addStretch()
        columns.addWidget(left, 1)
        columns.addWidget(right, 1)
        w.settingsBodyLayout.addLayout(columns)
        # Two card columns, still using the original Designer scroll area.
        old = w.sub_rows
        holder = QWidget()
        self.grid = QGridLayout(holder)
        self.grid.setContentsMargins(0,0,0,0)
        self.grid.setSpacing(14)
        self.grid.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.grid.setColumnStretch(0,1)
        self.grid.setColumnStretch(1,1)
        old.addWidget(holder)
        self.marked_dates = set()

    def save_budget(self):
        w = self.w
        ok, _ = w.guarded(lambda: w.repo.save_budget(w.uid, self.limit.value()))
        if ok:
            w.preferences = w.repo.preferences(w.uid)
            self.last_warning = None
            self.refresh()
            w.toast('Месячный бюджет сохранён.')

    def refresh(self):
        from user_window import label, button, clear
        w = self.w
        self.chart.set_payments(w.payments)
        paid = month_spending(w.payments)
        limit = Decimal(str(w.preferences.get('monthly_budget',0)))
        self.budget_text.setText(money(paid)+' ₽')
        percent = int(paid/limit*100) if limit else 0
        self.budget_bar.setValue(min(100,percent))
        self.budget_hint.setText(('Лимит превышен на '+money(paid-limit)+' ₽' if paid>limit else 'Осталось '+money(limit-paid)+' ₽') if limit else 'Задайте комфортный лимит на месяц.')
        warning = (date.today().strftime('%Y-%m'), str(limit), percent>=100)
        if limit and percent>=80 and warning != self.last_warning:
            w.toast('Бюджет превышен.' if percent>=100 else 'Потрачено более 80% месячного бюджета.')
            self.last_warning = warning
        for day in self.marked_dates:
            self.calendar.setDateTextFormat(day, QTextCharFormat())
        self.marked_dates.clear()
        for pay in w.payments:
            if pay['status'] == 'Отменён': continue
            day = as_date(pay['payment_date'])
            qday = QDate(day.year, day.month, day.day)
            fmt = QTextCharFormat()
            fmt.setBackground(QColor('#FFE0EB'))
            fmt.setForeground(QColor('#AC174F'))
            fmt.setFontWeight(QFont.Weight.Bold)
            self.calendar.setDateTextFormat(qday,fmt)
            self.marked_dates.add(qday)
        self.show_day()
        self.profile_info.setText(f"{w.user['user_name']} {w.user['surname']}\n{w.preferences.get('email') or 'Email ещё не указан'}\n{w.summary['active']} активных подписок · {money(monthly_cost(w.subscriptions))} ₽/мес.")
        for layout in self.sidebars.values(): clear(layout)
        active = [s for s in w.subscriptions if s['us_status']=='Активна']
        cost = monthly_cost(w.subscriptions)
        frame, b = card('Ваш портфель', tone='rose')
        metric(b,'Сервисов',str(len(active)))
        metric(b,'В месяц',money(cost)+' ₽')
        metric(b,'Прогноз за год',money(cost*12)+' ₽')
        hint = label('Прогноз при текущих тарифах и сохранении всех активных подписок.', muted=True)
        hint.setWordWrap(True)
        b.addWidget(hint)
        self.sidebars['subscriptions'].addWidget(frame)
        frame, b = card('Самые затратные')
        for sub in sorted(active,key=lambda s:Decimal(str(s['price']))/int(s['duration_months']), reverse=True)[:3]:
            text = label(sub['service_name']+'\n'+money(Decimal(str(sub['price']))/int(sub['duration_months']))+' ₽/мес.')
            text.setWordWrap(True)
            b.addWidget(text)
            b.addWidget(button('Посмотреть тариф →',partial(w.subscription_details,sub),flat=True))
        if not active: b.addWidget(label('Добавьте первый сервис.',muted=True))
        self.sidebars['subscriptions'].addWidget(frame)
        frame,b = card('Этот месяц',tone='rose')
        frame.setMinimumHeight(180)
        metric(b,'Оплачено',money(paid)+' ₽')
        pending = [p for p in w.payments if p['status']=='Ожидается' and as_date(p['payment_date']).replace(day=1)==date.today().replace(day=1)]
        metric(b,'Ожидается',money(sum(Decimal(str(p['amount'])) for p in pending))+' ₽')
        metric(b,'Ошибок',str(sum(p['status']=='Неуспешно' for p in w.payments)))
        self.sidebars['payments'].addWidget(frame)
        failed = [p for p in w.payments if p['status']=='Неуспешно']
        frame,b = card('Требуют внимания' if failed else 'Оплаты под контролем', tone='cream')
        frame.setMinimumHeight(190)
        if failed:
            for pay in failed[:3]:
                b.addWidget(label(pay['service_name']+' · '+money(pay['amount'])+' ₽'))
                b.addWidget(button('Повторить оплату',partial(w.pay,pay),primary=True))
        else:
            hint=label('После успешного ответа сервиса чек появится автоматически. Скачать его можно из меню платежа.',muted=True)
            hint.setWordWrap(True)
            b.addWidget(illustration('finance', 150, 110), 0, Qt.AlignmentFlag.AlignHCenter)
            b.addWidget(hint)
        self.sidebars['payments'].addWidget(frame)
        unread = [n for n in w.notifications if n['read_status']!='Прочитано']
        frame,b = card('Центр внимания',tone='rose')
        # Keep the six text rows inside the card before the outer layout is sized.
        b.setSizeConstraint(QLayout.SizeConstraint.SetDefaultConstraint)
        frame.setMinimumHeight(260)
        metric(b,'Непрочитано',str(len(unread)))
        for key, title in [('reminders','Напоминания'),('success','Успешные оплаты'),('errors','Ошибки'),('system','Другие события')]:
            metric(b,title,str(sum(note_kind(n)==key for n in unread)))
        self.sidebars['notifications'].addWidget(frame)
        frame,b = card('Ближайшее списание',tone='cream')
        future = sorted([p for p in w.payments if p['status']=='Ожидается'],key=lambda p:as_date(p['payment_date']))
        if future:
            pay=future[0]
            text=label(f"{pay['service_name']}\n{as_date(pay['payment_date']):%d.%m.%Y} · {money(pay['amount'])} ₽")
            text.setWordWrap(True)
            b.addWidget(text)
            b.addWidget(button('К платежам →',partial(w.navigate,'payments'),flat=True))
        else: b.addWidget(label('Нет ожидаемых платежей.',muted=True))
        self.sidebars['notifications'].addWidget(frame)
        frame,b = card('Только нужные события')
        b.addWidget(illustration('notifications', 180, 115), 0, Qt.AlignmentFlag.AlignHCenter)
        hint=label('Настройте отдельно напоминания, успешные оплаты и сообщения об ошибках.',muted=True)
        hint.setWordWrap(True)
        b.addWidget(hint)
        b.addWidget(button('Настроить уведомления →',partial(w.navigate,'settings'),flat=True))
        self.sidebars['notifications'].addWidget(frame)

        self.sidebars['notifications'].addStretch()
        # Recompute after inherited font styles have been polished. Otherwise Qt
        # can retain row heights measured before the cards entered the sidebar.
        for layout in self.sidebars.values():
            for i in range(layout.count()):
                widget = layout.itemAt(i).widget()
                if widget is None:
                    continue
                widget.ensurePolished()
                widget.layout().invalidate()
                widget.layout().activate()
                widget.updateGeometry()
            layout.invalidate()
            layout.activate()

    def show_day(self):
        day = self.calendar.selectedDate().toPyDate()
        bills = calendar_bills(getattr(self.w,'payments',[]),day)
        text = '\n'.join(f"{p['service_name']} · {money(p['amount'])} ₽ · {p['status']}" for p in bills[:3])
        if len(bills)>3: text+=f'\nЕщё платежей: {len(bills)-3}'
        self.day_details.setText(f'{day:%d.%m.%Y}\n'+(text or 'На этот день списаний нет.'))

    def render_subscriptions(self, found):
        from user_window import clear, label, button, service_icon, badge, hbox
        clear(self.grid)
        rows = max(1, (len(found)+1)//2)
        self.grid.parentWidget().setMinimumHeight(rows*324)
        order = self.sub_sort.currentIndex()
        if order == 1:
            found = sorted(found, key=lambda s:Decimal(str(s['price']))/int(s['duration_months']), reverse=True)
        elif order == 2:
            found = sorted(found, key=lambda s:s['service_name'].casefold())
        for i, sub in enumerate(found):
            active=sub['us_status']=='Активна'
            frame,b = card(sub['service_name'],sub['plan_name'], 'rose' if i%3==0 else None)
            frame.setMinimumHeight(332)
            top=hbox(spacing=10)
            image=label()
            image.setPixmap(service_icon(sub['service_name']).pixmap(40,40))
            image.setFixedSize(40,40)
            top.addWidget(image)
            top.addStretch()
            failed = active and any(p['user_subscription_id']==sub['user_subscription_id'] and p['status']=='Неуспешно' for p in self.w.payments)
            top.addWidget(badge('Ошибка оплаты' if failed else 'Активна' if active else 'Неактивна','failed' if failed else 'active' if active else 'inactive'))
            b.insertLayout(0,top)
            value=label(money(sub['price'])+' ₽',number=True)
            b.addWidget(value)
            b.addWidget(label(f"за {sub['duration_months']} мес. · {money(Decimal(str(sub['price']))*12/int(sub['duration_months']))} ₽/год",muted=True))
            due=as_date(sub['next_payment_date'])
            b.addWidget(label(f'Следующая оплата: {due:%d.%m.%Y}' if active and due else 'Подписка отменена',muted=True))
            row=hbox(spacing=5)
            row.addWidget(button('Подробнее',partial(self.w.subscription_details,sub)))
            menu=button('⋮',flat=True)
            menu.setFixedWidth(35)
            menu.clicked.connect(partial(self.w.subscription_menu,sub,menu))
            row.addWidget(menu)
            b.addLayout(row)
            self.grid.addWidget(frame,i//2,i%2)
        if not found:
            frame,b=card('Подписок не найдено','Измените фильтр или добавьте новый сервис.')
            b.addWidget(button('Добавить подписку',self.w.add_subscription,primary=True))
            self.grid.addWidget(frame,0,0,1,2)
