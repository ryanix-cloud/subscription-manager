"""Create one PDF per successful payment and register it in MySQL."""
from pathlib import Path
from uuid import uuid4
import os

from documents import write_pdf
from repository import as_date, money


class ReceiptService:
    def __init__(self, repo, directory=None):
        self.repo = repo
        self.directory = Path(directory or Path(__file__).resolve().parent / 'receipts')

    def ensure(self, uid, pid):
        payment = self.repo.payment(uid, pid)
        if not payment or payment['status'] != 'Успешно':
            raise ValueError('Чек формируется только после успешной оплаты.')
        number = f"SC-{int(pid):06d}"
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / f'receipt_{number}.pdf'
        existing = self.repo.receipt_record(uid, pid)
        if existing and target.exists():
            with target.open('rb') as stream:
                if stream.read(5) == b'%PDF-':
                    return target
        temporary = self.directory / ('.'+number+'-'+uuid4().hex+'.pdf')
        events = self.repo.payment_events(uid, pid)
        successful = next((event for event in events if event['outcome'] == 'Успешно'), None)
        reference = successful['event_id'] if successful else 'Импортированная запись оплаты'
        try:
            write_pdf(temporary, 'Чек об оплате '+number,
                      ['Сервис', 'Тариф', 'Дата оплаты', 'Сумма', 'Статус'],
                      [[payment['service_name'], payment['plan_name'],
                        as_date(payment['payment_date']).strftime('%d.%m.%Y'),
                        money(payment['amount'])+' ₽', 'Успешно']],
                      f"Пользователь: {payment['user_name']} {payment['surname']}. "
                      f"Ответ сервиса: {reference}. Учебная оплата, без банковского списания.")
            os.replace(temporary, target)
            self.repo.save_receipt_record(uid, pid, number, str(target.resolve()))
        finally:
            if temporary.exists():
                temporary.unlink()
        return target
