"""User data and atomic handling of simulated service payment events."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path

import bcrypt
from dateutil.relativedelta import relativedelta

DEFAULTS = {"email": "", "theme": "Светлая", "currency": "RUB",
            "reminders": True, "success": True, "errors": True}


def as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10]) if value else None


def money(value):
    amount = Decimal(str(value or 0))
    return f"{amount:,.0f}".replace(",", " ") if amount == amount.to_integral() else f"{amount:,.2f}".replace(",", " ")


class Repository:
    def __init__(self):
        self.mode = "mysql"

    def ensure_preferences(self):
        # Only an additive table; existing course-project tables are preserved.
        with self.transaction() as cur:
            self.execute(cur, """CREATE TABLE IF NOT EXISTS user_preferences (
                user_id INT PRIMARY KEY, preferences TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE)
                CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci""")
        self.ensure_payment_schema()

    def ensure_payment_schema(self):
        migration = Path(__file__).resolve().parent / "db" / "002_payment_events.sql"
        # Each statement is additive and idempotent; no existing rows are seeded.
        for statement in migration.read_text(encoding="utf-8").split(";"):
            if statement.strip():
                with self.transaction() as cur:
                    self.execute(cur, statement)

    def connect(self):
        from database import get_connection
        return get_connection()

    def execute(self, cur, query, params=()):
        return cur.execute(query, params)

    @contextmanager
    def transaction(self):
        conn = self.connect()
        cur = conn.cursor(dictionary=True)
        try:
            conn.start_transaction()
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

    def rows(self, sql, params=()):
        conn = self.connect()
        cur = conn.cursor(dictionary=True)
        try:
            self.execute(cur, sql, params)
            return [dict(row) for row in cur.fetchall()]
        finally:
            cur.close()
            conn.close()

    def one(self, sql, params=()):
        rows = self.rows(sql, params)
        return rows[0] if rows else None

    def authenticate(self, login, password):
        user = self.one("SELECT * FROM users WHERE login=%s", (login.strip(),))
        try:
            valid = user and bcrypt.checkpw(password.encode(), user["password"].encode())
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise ValueError("Неверный логин или пароль.")
        if user["user_status"] != "Активен":
            raise ValueError("Учётная запись заблокирована.")
        return user

    def preferences(self, uid):
        row = self.one("SELECT preferences FROM user_preferences WHERE user_id=%s", (uid,))
        if row:
            return {**DEFAULTS, **json.loads(row["preferences"])}
        user = self.one("SELECT notifications_enabled FROM users WHERE user_id=%s", (uid,))
        settings = self.one("SELECT * FROM user_settings WHERE user_id=%s", (uid,))
        enabled = bool(user and user["notifications_enabled"])
        if settings:
            enabled = enabled and bool(settings["notification_enabled"])
        return {**DEFAULTS, "success": enabled, "errors": enabled,
                "reminders": enabled and bool(settings["payment_reminders_enabled"] if settings else True)}

    def _save_preferences(self, cur, uid, prefs):
        self.execute(cur, "DELETE FROM user_preferences WHERE user_id=%s", (uid,))
        self.execute(cur, "INSERT INTO user_preferences(user_id,preferences) VALUES (%s,%s)",
                     (uid, json.dumps(prefs, ensure_ascii=False)))

    def save_profile(self, uid, name, surname, email, theme, flags):
        import re
        if not name.strip() or not surname.strip():
            raise ValueError("Укажите имя и фамилию.")
        if len(name.strip()) > 50 or len(surname.strip()) > 50:
            raise ValueError("Имя и фамилия должны быть не длиннее 50 символов.")
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email.strip()) or len(email) > 254:
            raise ValueError("Укажите корректный email.")
        prefs = {**self.preferences(uid), **flags, "email": email.strip(), "theme": theme, "currency": "RUB"}
        with self.transaction() as cur:
            self.execute(cur, "UPDATE users SET user_name=%s,surname=%s,notifications_enabled=%s WHERE user_id=%s",
                         (name.strip(), surname.strip(), int(any(flags.values())), uid))
            self._save_preferences(cur, uid, prefs)
            self.execute(cur, "SELECT settings_id FROM user_settings WHERE user_id=%s", (uid,))
            if cur.fetchone():
                self.execute(cur, "UPDATE user_settings SET notification_enabled=%s,payment_reminders_enabled=%s WHERE user_id=%s", (int(any(flags.values())), int(flags['reminders']), uid))
            else:
                self.execute(cur, "INSERT INTO user_settings(user_id,notification_enabled,payment_reminders_enabled) VALUES (%s,%s,%s)", (uid, int(any(flags.values())), int(flags['reminders'])))

    def change_password(self, uid, current, new, repeat):
        user = self.one("SELECT password FROM users WHERE user_id=%s", (uid,))
        try:
            valid = user and bcrypt.checkpw(current.encode(), user["password"].encode())
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Текущий пароль неверен.")
        if len(new) < 8 or len(new.encode()) > 72:
            raise ValueError("Новый пароль: минимум 8 символов, максимум 72 байта UTF-8.")
        if new != repeat:
            raise ValueError("Новые пароли не совпадают.")
        with self.transaction() as cur:
            self.execute(cur, "UPDATE users SET password=%s WHERE user_id=%s",
                         (bcrypt.hashpw(new.encode(), bcrypt.gensalt()).decode(), uid))

    def catalog(self):
        return self.rows("""SELECT sp.*,s.service_name,s.official_website FROM subscriptions_plans sp
            JOIN services s ON s.service_id=sp.service_id WHERE s.service_status='Активен' ORDER BY s.service_name,sp.price""")

    def subscriptions(self, uid):
        return self.rows("""SELECT us.*,sp.plan_name,sp.price,sp.duration_months,s.service_name,s.official_website
            FROM user_subscriptions us JOIN subscriptions_plans sp ON sp.plan_id=us.plan_id
            JOIN services s ON s.service_id=sp.service_id WHERE us.user_id=%s ORDER BY us.next_payment_date,us.user_subscription_id""", (uid,))

    def payments(self, uid):
        return self.rows("""SELECT p.*,sp.plan_name,s.service_name FROM payments p
            JOIN user_subscriptions us ON us.user_subscription_id=p.user_subscription_id
            JOIN subscriptions_plans sp ON sp.plan_id=us.plan_id JOIN services s ON s.service_id=sp.service_id
            WHERE us.user_id=%s ORDER BY p.payment_date DESC,p.payment_id DESC""", (uid,))

    def _notify(self, cur, uid, title, message):
        self.execute(cur, """INSERT INTO notifications(user_id,title,message,created_at,read_status)
            VALUES (%s,%s,%s,%s,'Не прочитано')""", (uid, title, message, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    def add_subscription(self, uid, plan_id):
        with self.transaction() as cur:
            # Lock the user to serialize duplicate additions in MySQL as well.
            self.execute(cur, "SELECT user_id FROM users WHERE user_id=%s FOR UPDATE", (uid,))
            if not cur.fetchone():
                raise ValueError("Пользователь не найден.")
            self.execute(cur, "SELECT user_subscription_id FROM user_subscriptions WHERE user_id=%s AND plan_id=%s AND us_status='Активна'", (uid, plan_id))
            if cur.fetchone():
                raise ValueError("Этот тариф уже подключён.")
            self.execute(cur, "SELECT sp.* FROM subscriptions_plans sp JOIN services s ON s.service_id=sp.service_id WHERE sp.plan_id=%s AND s.service_status='Активен'", (plan_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError("Тариф не найден.")
            plan = dict(row)
            if int(plan["duration_months"] or 0) <= 0 or Decimal(str(plan["price"])) < 0:
                raise ValueError("Некорректная цена или срок тарифа.")
            today = date.today()
            # The first invoice is due at activation; a successful response
            # advances the billing date by one tariff period.
            due = today
            self.execute(cur, """INSERT INTO user_subscriptions(user_id,plan_id,start_date,next_payment_date,end_date,us_status)
                VALUES (%s,%s,%s,%s,%s,'Активна')""", (uid, plan_id, today, due, due))
            sid = cur.lastrowid
            self.execute(cur, "INSERT INTO subscription_history(user_subscription_id,old_status,new_status,comment) VALUES (%s,NULL,'Активна','Подключение пользователем')", (sid,))
            self.execute(cur, """INSERT INTO payments(user_subscription_id,payment_date,amount,payment_type,status)
                VALUES (%s,%s,%s,'Регулярный','Ожидается')""", (sid, due, plan["price"]))
            self._notify(cur, uid, "Подписка добавлена", "Тариф добавлен. Ожидается учебный ответ сервиса о первой оплате.")

    def cancel_subscription(self, uid, sid):
        with self.transaction() as cur:
            self.execute(cur, "UPDATE user_subscriptions SET us_status='Отменена',end_date=%s WHERE user_id=%s AND user_subscription_id=%s AND us_status='Активна'", (date.today(), uid, sid))
            if cur.rowcount != 1:
                raise ValueError("Активная подписка не найдена.")
            self.execute(cur, "UPDATE payments SET status='Отменён' WHERE user_subscription_id=%s AND status IN ('Ожидается','Неуспешно')", (sid,))
            self.execute(cur, "INSERT INTO subscription_history(user_subscription_id,old_status,new_status,comment) VALUES (%s,'Активна','Отменена','Отмена пользователем')", (sid,))
            self._notify(cur, uid, "Подписка отменена", "Будущие платежи отменены. История оплаченных платежей сохранена.")

    def payment(self, uid, pid):
        return self.one("""SELECT p.*,sp.plan_name,s.service_name,us.us_status,u.user_name,u.surname
            FROM payments p JOIN user_subscriptions us ON us.user_subscription_id=p.user_subscription_id
            JOIN users u ON u.user_id=us.user_id JOIN subscriptions_plans sp ON sp.plan_id=us.plan_id
            JOIN services s ON s.service_id=sp.service_id WHERE us.user_id=%s AND p.payment_id=%s""", (uid, pid))

    def payment_events(self, uid, pid):
        return self.rows("SELECT * FROM payment_events WHERE user_id=%s AND payment_id=%s ORDER BY attempt DESC", (uid, pid))

    def next_payment_attempt(self, uid, pid):
        if not self.payment(uid, pid):
            raise ValueError("Платёж не найден.")
        row = self.one("SELECT COALESCE(MAX(attempt),0)+1 AS next_attempt FROM payment_events WHERE user_id=%s AND payment_id=%s", (uid, pid))
        return int(row['next_attempt'])

    def pay(self, uid, pid):
        """Compatibility helper; the application itself uses SimulatedServices."""
        from payment_simulation import PaymentEvent
        return self.apply_payment_event(uid, pid, PaymentEvent.create("Успешно", self.next_payment_attempt(uid, pid)))

    def apply_payment_event(self, uid, pid, event):
        if event.outcome not in ("Успешно", "Неуспешно") or not event.event_id or len(event.event_id) > 64 or event.attempt < 1:
            raise ValueError("Некорректный ответ сервиса.")
        prefs = self.preferences(uid)
        with self.transaction() as cur:
            self.execute(cur, "SELECT user_id FROM users WHERE user_id=%s FOR UPDATE", (uid,))
            if not cur.fetchone():
                raise ValueError("Пользователь не найден.")
            self.execute(cur, "SELECT * FROM payment_events WHERE event_id=%s", (event.event_id,))
            existing = cur.fetchone()
            if existing:
                if existing['user_id'] != uid or existing['payment_id'] != pid or existing['outcome'] != event.outcome or existing['attempt'] != event.attempt:
                    raise ValueError("Идентификатор ответа уже использован другим событием.")
                return {'payment_id': pid, 'outcome': existing['outcome'], 'applied': False,
                        'reason': existing['failure_reason'], 'event_id': event.event_id}
            self.execute(cur, """SELECT p.*,us.next_payment_date,us.us_status,sp.duration_months,sp.price,s.service_name
                FROM payments p JOIN user_subscriptions us ON us.user_subscription_id=p.user_subscription_id
                JOIN subscriptions_plans sp ON sp.plan_id=us.plan_id JOIN services s ON s.service_id=sp.service_id
                WHERE p.payment_id=%s AND us.user_id=%s FOR UPDATE""", (pid, uid))
            row = cur.fetchone()
            if not row:
                raise ValueError("Платёж не найден.")
            payment = dict(row)
            if payment["status"] not in ("Ожидается", "Неуспешно") or payment["us_status"] != "Активна":
                raise ValueError("Этот платёж уже обработан или подписка отменена.")
            self.execute(cur, "SELECT COALESCE(MAX(attempt),0)+1 AS next_attempt FROM payment_events WHERE payment_id=%s", (pid,))
            if int(cur.fetchone()['next_attempt']) != event.attempt:
                raise ValueError("Получен устаревший ответ сервиса. Обновите историю платежей.")
            reason = (event.reason or "Сервис отклонил платёж.")[:255] if event.outcome == 'Неуспешно' else None
            self.execute(cur, """INSERT INTO payment_events(event_id,user_id,payment_id,attempt,outcome,failure_reason)
                VALUES (%s,%s,%s,%s,%s,%s)""", (event.event_id, uid, pid, event.attempt, event.outcome, reason))
            result = {'payment_id': pid, 'outcome': event.outcome, 'applied': True,
                      'reason': reason, 'event_id': event.event_id}
            if event.outcome == 'Неуспешно':
                self.execute(cur, "UPDATE payments SET status='Неуспешно' WHERE payment_id=%s", (pid,))
                if prefs['errors']:
                    self._notify(cur, uid, f"Ошибка платежа · SC-{pid:06d}",
                                 f"{payment['service_name']}: {reason} Повторите учебную оплату в разделе «Платежи».")
                return result
            anchor = max(as_date(payment["next_payment_date"]) or date.today(), date.today())
            due = anchor + relativedelta(months=int(payment["duration_months"]))
            self.execute(cur, "UPDATE payments SET status='Успешно',payment_date=%s WHERE payment_id=%s AND status IN ('Ожидается','Неуспешно')", (date.today(), pid))
            if cur.rowcount != 1:
                raise ValueError("Платёж уже обработан.")
            self.execute(cur, "UPDATE user_subscriptions SET next_payment_date=%s,end_date=%s WHERE user_subscription_id=%s", (due, due, payment["user_subscription_id"]))
            self.execute(cur, """INSERT INTO payments(user_subscription_id,payment_date,amount,payment_type,status)
                VALUES (%s,%s,%s,'Регулярный','Ожидается')""", (payment["user_subscription_id"], due, payment["price"]))
            if prefs["success"]:
                self._notify(cur, uid, "Оплата прошла успешно", f"{payment['service_name']}: {money(payment['amount'])} ₽. Чек SC-{pid:06d}. Следующий платёж {due:%d.%m.%Y}.")
            return result

    def due_payments(self, uid):
        return self.rows("""SELECT p.payment_id FROM payments p
            JOIN user_subscriptions us ON us.user_subscription_id=p.user_subscription_id
            WHERE us.user_id=%s AND us.us_status='Активна' AND p.status='Ожидается'
            AND p.payment_date<=%s ORDER BY p.payment_date,p.payment_id LIMIT 20""", (uid, date.today()))

    def receipt_record(self, uid, pid):
        return self.one("""SELECT r.* FROM receipts r JOIN payments p ON p.payment_id=r.payment_id
            JOIN user_subscriptions us ON us.user_subscription_id=p.user_subscription_id
            WHERE us.user_id=%s AND r.payment_id=%s AND p.status='Успешно'""", (uid, pid))

    def save_receipt_record(self, uid, pid, number, path):
        with self.transaction() as cur:
            self.execute(cur, """SELECT p.payment_id FROM payments p JOIN user_subscriptions us
                ON us.user_subscription_id=p.user_subscription_id
                WHERE us.user_id=%s AND p.payment_id=%s AND p.status='Успешно' FOR UPDATE""", (uid, pid))
            if not cur.fetchone():
                raise ValueError("Чек доступен только для успешной оплаты текущего пользователя.")
            self.execute(cur, """INSERT INTO receipts(payment_id,receipt_number,file_path) VALUES (%s,%s,%s)
                ON DUPLICATE KEY UPDATE file_path=VALUES(file_path)""", (pid, number, str(path)))

    def missing_payment_receipts(self, uid):
        return self.rows("""SELECT DISTINCT p.payment_id FROM payments p
            JOIN payment_events e ON e.payment_id=p.payment_id
            LEFT JOIN receipts r ON r.payment_id=p.payment_id
            WHERE e.user_id=%s AND p.status='Успешно' AND e.outcome='Успешно' AND r.receipt_id IS NULL""", (uid,))

    def notifications(self, uid):
        return self.rows("SELECT * FROM notifications WHERE user_id=%s ORDER BY created_at DESC,notification_id DESC", (uid,))

    def mark_read(self, uid, nid=None):
        with self.transaction() as cur:
            self.execute(cur, "UPDATE notifications SET read_status='Прочитано' WHERE user_id=%s" + (" AND notification_id=%s" if nid is not None else ""), (uid, nid) if nid is not None else (uid,))

    def refresh_reminders(self, uid):
        if not self.preferences(uid)["reminders"]:
            return
        due = [s for s in self.subscriptions(uid) if s["us_status"] == "Активна" and as_date(s["next_payment_date"]) and as_date(s["next_payment_date"]) <= date.today()+timedelta(days=3)]
        with self.transaction() as cur:
            # A user lock prevents duplicate reminders from two open instances.
            self.execute(cur, "SELECT user_id FROM users WHERE user_id=%s FOR UPDATE", (uid,))
            cur.fetchone()
            for sub in due:
                title = f"Платёж: {sub['service_name']} · {as_date(sub['next_payment_date']):%d.%m.%Y} · #{sub['user_subscription_id']}"
                self.execute(cur, "SELECT notification_id FROM notifications WHERE user_id=%s AND title=%s", (uid, title))
                if not cur.fetchone():
                    self._notify(cur, uid, title, f"К оплате {money(sub['price'])} ₽. В дату платежа будет получен учебный ответ сервиса.")

    def refresh_failed_payment_notifications(self, uid):
        if not self.preferences(uid)["errors"]:
            return
        failed = [p for p in self.payments(uid) if p["status"] == "Неуспешно"]
        if not failed:
            return
        with self.transaction() as cur:
            self.execute(cur, "SELECT user_id FROM users WHERE user_id=%s FOR UPDATE", (uid,))
            cur.fetchone()
            for payment in failed:
                title = f"Ошибка платежа · SC-{payment['payment_id']:06d}"
                self.execute(cur, "SELECT notification_id FROM notifications WHERE user_id=%s AND title=%s", (uid, title))
                if not cur.fetchone():
                    self._notify(cur, uid, title, f"{payment['service_name']}: платёж {money(payment['amount'])} ₽ не прошёл. Проверьте оплату на сайте сервиса.")

    def summary(self, uid):
        today = date.today()
        active = [s for s in self.subscriptions(uid) if s["us_status"] == "Активна"]
        dates = [as_date(s["next_payment_date"]) for s in active if s["next_payment_date"]]
        return {"active": len(active),
                "monthly": sum((Decimal(str(s["price"])) / max(1, int(s["duration_months"]))) for s in active),
                "nearest": min(dates) if dates else None,
                "upcoming": sum(today <= d <= today+timedelta(days=7) for d in dates)}
