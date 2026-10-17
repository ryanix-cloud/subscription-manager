"""Pure calculations shared by the dashboard and its tests."""
from datetime import date
from decimal import Decimal
from dateutil.relativedelta import relativedelta
from repository import as_date

def monthly_history(payments, today=None):
    today = today or date.today()
    months = [today.replace(day=1)-relativedelta(months=i) for i in reversed(range(6))]
    return [(month, sum((Decimal(str(p['amount'])) for p in payments
             if p['status'] == 'Успешно' and as_date(p['payment_date']).replace(day=1) == month), Decimal(0))) for month in months]

def month_spending(payments, today=None):
    return monthly_history(payments, today)[-1][1]

def monthly_cost(subscriptions):
    return sum((Decimal(str(s['price'])) / max(1, int(s['duration_months']))
                for s in subscriptions if s['us_status'] == 'Активна'), Decimal(0))

def calendar_bills(payments, day):
    return [p for p in payments if as_date(p['payment_date']) == day and p['status'] != 'Отменён']

def note_kind(note):
    text = note['title'].casefold()
    if 'ошиб' in text or 'неуспеш' in text:
        return 'errors'
    if 'оплачен' in text or 'успеш' in text:
        return 'success'
    if any(word in text for word in ['платёж:', 'напомин', 'просроч', 'скоро']):
        return 'reminders'
    return 'system'
