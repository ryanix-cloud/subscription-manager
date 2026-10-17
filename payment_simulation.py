"""Local stand-in for subscription services. No network calls or bank details."""
from dataclasses import dataclass
import random
from uuid import uuid4


@dataclass(frozen=True)
class PaymentEvent:
    event_id: str
    outcome: str
    attempt: int
    reason: str | None = None

    @classmethod
    def create(cls, outcome, attempt, reason=None):
        return cls('evt_'+uuid4().hex, outcome, attempt, reason)


class FakeGateway:
    SCENARIOS = {'auto', 'success', 'insufficient_funds', 'service_unavailable'}

    def __init__(self, rng=None):
        self.rng = rng or random.Random()

    def reply(self, attempt, scenario='auto'):
        if scenario not in self.SCENARIOS:
            raise ValueError('Неизвестный сценарий оплаты.')
        if scenario == 'auto':
            scenario = 'success' if self.rng.random() < .8 else self.rng.choice(['insufficient_funds', 'service_unavailable'])
        if scenario == 'success':
            return PaymentEvent.create('Успешно', attempt)
        reason = {'insufficient_funds': 'Недостаточно средств для оплаты подписки.',
                  'service_unavailable': 'Сервис временно недоступен. Попробуйте позже.'}[scenario]
        return PaymentEvent.create('Неуспешно', attempt, reason)


class SimulatedServices:
    def __init__(self, repo, receipts, gateway=None):
        self.repo, self.receipts = repo, receipts
        self.gateway = gateway or FakeGateway()

    def process(self, uid, pid, scenario='auto'):
        event = self.gateway.reply(self.repo.next_payment_attempt(uid, pid), scenario)
        return self.receive(uid, pid, event)

    def receive(self, uid, pid, event):
        result = self.repo.apply_payment_event(uid, pid, event)
        if result['outcome'] == 'Успешно':
            try:
                result['receipt_path'] = str(self.receipts.ensure(uid, pid))
            except Exception as error:
                # Payment stays successful; this separate document job is retried.
                result['receipt_error'] = str(error)
        return result

    def process_due(self, uid):
        outcomes = []
        for payment in self.repo.due_payments(uid):
            try:
                outcomes.append(self.process(uid, payment['payment_id']))
            except ValueError:
                # Another window may have already handled or cancelled the bill.
                continue
        for payment in self.repo.missing_payment_receipts(uid):
            try:
                self.receipts.ensure(uid, payment['payment_id'])
            except Exception:
                # The next scheduled pass or an explicit download will retry.
                pass
        return outcomes
