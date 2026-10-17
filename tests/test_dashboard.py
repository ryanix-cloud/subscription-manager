from datetime import date
from decimal import Decimal
import pytest
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QLabel
from analytics import monthly_history, monthly_cost, calendar_bills, note_kind
from user_window import UserWindow


def test_history_uses_only_success_and_keeps_empty_months():
    payments = [dict(payment_date='2026-10-03',amount='120.50',status='Успешно'),
                dict(payment_date='2026-10-04',amount='400',status='Неуспешно'),
                dict(payment_date='2026-09-20',amount='99',status='Успешно'),
                dict(payment_date='2025-10-20',amount='1000',status='Успешно')]
    history = monthly_history(payments,date(2026,10,15))
    assert len(history)==6
    assert history[0]==(date(2026,5,1),Decimal(0))
    assert history[-2][1]==99
    assert history[-1][1]==Decimal('120.50')


def test_annual_tariff_is_normalized_and_cancelled_is_excluded():
    assert monthly_cost([dict(price=1200,duration_months=12,us_status='Активна'),
                         dict(price=900,duration_months=1,us_status='Отменена')])==100


def test_calendar_excludes_cancelled_but_keeps_failed():
    payments=[dict(payment_date='2026-10-15',status=s) for s in ['Успешно','Неуспешно','Отменён']]
    assert len(calendar_bills(payments,date(2026,10,15)))==2


def test_notification_categories_keep_account_events_separate():
    for title, kind in [('Добро пожаловать','system'),('Подписка добавлена','system'),
                        ('Платёж: Spotify · 16.10.2026','reminders'),
                        ('Оплата прошла успешно','success'),('Неуспешная оплата','errors')]:
        assert note_kind({'title':title})==kind


def test_budget_is_persistent_per_user_and_profile_preserves_it(repo):
    repo.save_budget(1,4200)
    assert Decimal(repo.preferences(1)['monthly_budget'])==4200
    assert repo.preferences(2)['monthly_budget']==0
    repo.save_profile(1,'Анна','Рыбакова','anna@mail.ru','Светлая',
                      {'reminders':True,'success':True,'errors':True})
    assert Decimal(repo.preferences(1)['monthly_budget'])==4200


@pytest.mark.parametrize('amount',[-1,100000001,'NaN'])
def test_budget_rejects_invalid_values(repo,amount):
    with pytest.raises(ValueError): repo.save_budget(1,amount)


def test_dashboard_filters_calendar_budget_and_card_geometry(app,repo,tmp_path):
    with repo.transaction() as cur:
        repo._notify(cur,1,'Ошибка платежа · тест','Недостаточно средств')
        repo._notify(cur,1,'Платёж оплачен','Учебный ответ получен')
    window=UserWindow(repo.authenticate('test1','testpass123'),repo,receipt_directory=tmp_path)
    window.initial_payment_check.stop()
    window.background_timer.stop()
    window.show()
    d=window.dashboard
    d.limit.setValue(3000)
    d.save_budget()
    assert Decimal(repo.preferences(1)['monthly_budget'])==3000
    assert 'превышен' in d.budget_hint.text()
    pay=window.payments[-1]
    day=pay['payment_date']
    d.calendar.setSelectedDate(QDate(day.year,day.month,day.day))
    assert pay['service_name'] in d.day_details.text()
    window.navigate('subscriptions')
    window.searchInput.setText('spotify')
    assert d.grid.count()==1
    assert 'Spotify' in [l.text() for l in d.grid.itemAt(0).widget().findChildren(QLabel)]
    window.searchInput.clear()
    d.sub_sort.setCurrentIndex(1)
    assert 'Adobe Photoshop' in [l.text() for l in d.grid.itemAt(0).widget().findChildren(QLabel)]
    for width,height in [(1440,940),(1120,760)]:
        window.resize(width,height)
        app.processEvents()
        top=d.grid.itemAtPosition(0,0).widget().geometry()
        below=d.grid.itemAtPosition(1,0).widget().geometry()
        assert top.bottom()<below.top()
    window.navigate('notifications')
    d.note_type.setCurrentIndex(3)
    assert window.notification_rows.count()==1
    frame=window.notification_rows.itemAt(0).widget()
    assert any('Ошибка платежа' in l.text() for l in frame.findChildren(QLabel))
    window.mark_all_read()
    window.filter_notifications('unread')
    assert not window.bellBadge.isVisible()
    window.close()
