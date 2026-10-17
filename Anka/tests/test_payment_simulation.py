from datetime import date
import random

import pytest
from PyQt6.QtTest import QTest
from dateutil.relativedelta import relativedelta

from payment_simulation import FakeGateway, PaymentEvent, SimulatedServices
from receipt_service import ReceiptService
from repository import as_date
from user_window import PaymentDialog, UserWindow


def pending(repo, sid=1):
    return next(p for p in repo.payments(1) if p['status'] == 'Ожидается' and p['user_subscription_id'] == sid)


def service(repo, tmp_path):
    return SimulatedServices(repo, ReceiptService(repo, tmp_path/'receipts'), FakeGateway(random.Random(1)))


def test_success_automatically_generates_one_receipt_and_one_next_bill(app, repo, tmp_path):
    worker = service(repo, tmp_path)
    bill = pending(repo)
    event = PaymentEvent.create('Успешно', 1)
    result = worker.receive(1, bill['payment_id'], event)
    assert result['applied']
    path = worker.receipts.ensure(1, bill['payment_id'])
    assert path.read_bytes().startswith(b'%PDF-')
    record = repo.receipt_record(1, bill['payment_id'])
    assert record['receipt_number'] == f"SC-{bill['payment_id']:06d}"
    modified = path.stat().st_mtime_ns
    again = worker.receive(1, bill['payment_id'], event)
    assert not again['applied']
    assert path.stat().st_mtime_ns == modified
    assert len(repo.payments(1)) == 11
    assert len(repo.payment_events(1, bill['payment_id'])) == 1
    assert len(list((tmp_path/'receipts').glob('*.pdf'))) == 1


@pytest.mark.parametrize('scenario', ['insufficient_funds', 'service_unavailable'])
def test_failed_service_response_creates_no_receipt_and_does_not_extend_subscription(app, repo, tmp_path, scenario):
    worker = service(repo, tmp_path)
    bill = pending(repo)
    old_sub = next(s for s in repo.subscriptions(1) if s['user_subscription_id'] == 1)
    result = worker.process(1, bill['payment_id'], scenario)
    assert result['outcome'] == 'Неуспешно'
    assert repo.payment(1, bill['payment_id'])['status'] == 'Неуспешно'
    assert repo.receipt_record(1, bill['payment_id']) is None
    assert not (tmp_path/'receipts').exists()
    assert len(repo.payments(1)) == 10
    sub = next(s for s in repo.subscriptions(1) if s['user_subscription_id'] == 1)
    assert sub['next_payment_date'] == old_sub['next_payment_date']
    assert any('Ошибка платежа' in n['title'] for n in repo.notifications(1))


def test_retry_after_failure_records_both_attempts_and_generates_receipt(app, repo, tmp_path):
    worker = service(repo, tmp_path)
    bill = pending(repo)
    failure = worker.process(1, bill['payment_id'], 'insufficient_funds')
    success = worker.process(1, bill['payment_id'], 'success')
    assert failure['outcome'] == 'Неуспешно'
    assert success['outcome'] == 'Успешно'
    assert [e['attempt'] for e in repo.payment_events(1, bill['payment_id'])] == [2, 1]
    assert repo.receipt_record(1, bill['payment_id'])
    assert len(repo.payments(1)) == 11


def test_auto_processing_only_handles_due_bills_once(app, repo, tmp_path):
    worker = service(repo, tmp_path)
    bill = pending(repo)
    with repo.transaction() as cur:
        repo.execute(cur, 'UPDATE payments SET payment_date=%s WHERE payment_id=%s', (date.today(), bill['payment_id']))
        repo.execute(cur, 'UPDATE user_subscriptions SET next_payment_date=%s WHERE user_subscription_id=1', (date.today(),))
    result = worker.process_due(1)
    assert len(result) == 1 and result[0]['outcome'] == 'Успешно'
    assert worker.process_due(1) == []
    assert sum(p['status'] == 'Ожидается' for p in repo.payments(1)) == 5


def test_failed_bill_waits_for_explicit_retry_instead_of_repeating_every_minute(app, repo, tmp_path):
    worker = service(repo, tmp_path)
    bill = pending(repo)
    worker.process(1, bill['payment_id'], 'service_unavailable')
    worker.process_due(1)
    assert len(repo.payment_events(1, bill['payment_id'])) == 1


def test_event_identity_and_attempt_order_are_validated(repo):
    bill = pending(repo)
    early = PaymentEvent.create('Успешно', 2)
    with pytest.raises(ValueError, match='устаревший'):
        repo.apply_payment_event(1, bill['payment_id'], early)
    event = PaymentEvent.create('Неуспешно', 1, 'Отказ сервиса')
    repo.apply_payment_event(1, bill['payment_id'], event)
    assert not repo.apply_payment_event(1, bill['payment_id'], event)['applied']
    forged = PaymentEvent(event.event_id, 'Успешно', 1)
    with pytest.raises(ValueError):
        repo.apply_payment_event(1, bill['payment_id'], forged)
    assert len(repo.payment_events(1, bill['payment_id'])) == 1


def test_cancelled_and_foreign_payments_cannot_receive_success(app, repo, tmp_path):
    worker = service(repo, tmp_path)
    bill = pending(repo)
    with pytest.raises(ValueError):
        worker.process(2, bill['payment_id'], 'success')
    repo.cancel_subscription(1, bill['user_subscription_id'])
    with pytest.raises(ValueError):
        worker.process(1, bill['payment_id'], 'success')
    with pytest.raises(ValueError):
        worker.receipts.ensure(2, bill['payment_id'])
    assert repo.payment_events(1, bill['payment_id']) == []


def test_receipt_write_failure_is_recoverable_without_repeating_payment(app, repo, tmp_path, monkeypatch):
    import receipt_service
    worker = service(repo, tmp_path)
    bill = pending(repo)
    original = receipt_service.write_pdf
    def fail(*args, **kwargs):
        raise OSError('Test disk error')
    monkeypatch.setattr(receipt_service, 'write_pdf', fail)
    result = worker.process(1, bill['payment_id'], 'success')
    assert 'receipt_error' in result
    assert repo.payment(1, bill['payment_id'])['status'] == 'Успешно'
    assert repo.receipt_record(1, bill['payment_id']) is None
    monkeypatch.setattr(receipt_service, 'write_pdf', original)
    worker.process_due(1)
    assert repo.receipt_record(1, bill['payment_id'])
    assert len(repo.payment_events(1, bill['payment_id'])) == 1
    assert len(repo.payments(1)) == 11


def test_new_subscription_has_an_immediate_first_invoice(app, repo, tmp_path):
    repo.add_subscription(1, 7)
    bill = next(p for p in repo.payments(1) if p['service_name'] == 'VK Музыка')
    assert as_date(bill['payment_date']) == date.today()
    worker = service(repo, tmp_path)
    worker.process(1, bill['payment_id'], 'success')
    sub = next(s for s in repo.subscriptions(1) if s['plan_id'] == 7 and s['us_status'] == 'Активна')
    assert as_date(sub['next_payment_date']) == date.today()+relativedelta(months=1)


def test_deleted_receipt_can_be_restored_without_new_payment(app, repo, tmp_path):
    worker = service(repo, tmp_path)
    bill = pending(repo)
    result = worker.process(1, bill['payment_id'], 'success')
    path = worker.receipts.ensure(1, bill['payment_id'])
    path.unlink()
    assert worker.receipts.ensure(1, bill['payment_id']).exists()
    assert len(repo.rows('SELECT * FROM receipts WHERE payment_id=%s', (bill['payment_id'],))) == 1
    assert len(repo.payments(1)) == 11


def test_payment_dialog_shows_error_then_success_and_receipt(app, repo, tmp_path):
    window = UserWindow(repo.authenticate('test1', 'testpass123'), repo, receipt_directory=tmp_path/'receipts')
    window.initial_payment_check.stop()
    window.background_timer.stop()
    dialog = PaymentDialog(window.simulator, 1, pending(repo), window)
    dialog.show()
    dialog.scenario.setCurrentIndex(2)
    dialog.start()
    QTest.qWait(850)
    assert 'Оплата не прошла' in dialog.resultLabel.text()
    assert dialog.processButton.isEnabled()
    dialog.scenario.setCurrentIndex(1)
    dialog.start()
    QTest.qWait(850)
    assert 'сформирован автоматически' in dialog.resultLabel.text()
    assert dialog.receiptButton.isVisible()
    assert not dialog.processButton.isEnabled()
    dialog.reject()
    window.close()


def test_notification_flags_do_not_disable_payment_processing(app, repo, tmp_path):
    repo.save_profile(1, 'Анна', 'Рыбакова', 'anna@mail.ru', 'Светлая',
                      {'reminders': False, 'success': False, 'errors': False})
    worker = service(repo, tmp_path)
    before = len(repo.notifications(1))
    bill = pending(repo)
    worker.process(1, bill['payment_id'], 'insufficient_funds')
    worker.process(1, bill['payment_id'], 'success')
    assert len(repo.notifications(1)) == before
    assert repo.receipt_record(1, bill['payment_id'])
