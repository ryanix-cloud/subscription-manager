import mysql.connector
import bcrypt
from datetime import date
from pathlib import Path
from dateutil.relativedelta import relativedelta


# =============================================================
# ПОДКЛЮЧЕНИЕ К БАЗЕ ДАННЫХ
# =============================================================

def get_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="zefir220930",
        database="submanager",
        charset="utf8mb4",
        connection_timeout=5
    )


# =============================================================
# ЭЛЕКТРОННЫЕ ЧЕКИ И АВТОМАТИЧЕСКАЯ ОБРАБОТКА ПЛАТЕЖЕЙ
# =============================================================

def ensure_receipts_table():
    """Создаёт таблицу чеков, если её ещё нет."""
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS receipts (
                receipt_id INT AUTO_INCREMENT PRIMARY KEY,
                payment_id INT NOT NULL UNIQUE,
                receipt_number VARCHAR(30) NOT NULL UNIQUE,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                file_path VARCHAR(500) NOT NULL,
                CONSTRAINT fk_receipts_payment
                    FOREIGN KEY (payment_id)
                    REFERENCES payments(payment_id)
                    ON DELETE CASCADE
            )
            """
        )
        connection.commit()
    finally:
        cursor.close()
        connection.close()


def _generate_receipt_pdf(payment):
    """Создаёт учебный PDF-чек и возвращает путь к нему."""
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.figure import Figure

    receipts_dir = Path(__file__).resolve().parent / 'receipts'
    receipts_dir.mkdir(exist_ok=True)

    receipt_number = f"SC-{int(payment['payment_id']):06d}"
    file_path = receipts_dir / f"receipt_{receipt_number}.pdf"

    payment_date = payment.get('payment_date')
    if hasattr(payment_date, 'strftime'):
        date_text = payment_date.strftime('%d.%m.%Y')
    else:
        date_text = str(payment_date or date.today().strftime('%d.%m.%Y'))

    figure = Figure(figsize=(7.2, 5.2))
    ax = figure.add_subplot(111)
    ax.axis('off')

    ax.text(0.5, 0.92, 'SUBCONTROL', ha='center', fontsize=20, fontweight='bold')
    ax.text(0.5, 0.84, 'ЭЛЕКТРОННЫЙ ЧЕК', ha='center', fontsize=15, fontweight='bold')

    lines = [
        f"Чек № {receipt_number}",
        f"Дата: {date_text}",
        '',
        f"Сервис: {payment.get('service_name') or '—'}",
        f"Тариф: {payment.get('plan_name') or '—'}",
        f"Сумма: {float(payment.get('amount') or 0):.2f} ₽",
        f"Статус: Успешно",
        f"Пользователь: {payment.get('login') or '—'}",
        '',
        'Учебный чек. Сформирован системой SubControl.'
    ]
    ax.text(0.12, 0.72, '\n'.join(lines), ha='left', va='top', fontsize=12, linespacing=1.55)

    with PdfPages(file_path) as pdf:
        pdf.savefig(figure, bbox_inches='tight')

    return receipt_number, str(file_path)


def _create_receipt_for_payment(payment_id):
    """Создаёт PDF и запись в receipts для успешного платежа."""
    ensure_receipts_table()

    existing = _fetch_one(
        "SELECT receipt_number, file_path FROM receipts WHERE payment_id = %s",
        (payment_id,)
    )
    if existing:
        return existing

    payment = _fetch_one(
        """
        SELECT
            p.payment_id, p.payment_date, p.amount,
            s.service_name, sp.plan_name, u.login
        FROM payments AS p
        JOIN user_subscriptions AS us
            ON p.user_subscription_id = us.user_subscription_id
        JOIN subscriptions_plans AS sp
            ON us.plan_id = sp.plan_id
        JOIN services AS s
            ON sp.service_id = s.service_id
        JOIN users AS u
            ON us.user_id = u.user_id
        WHERE p.payment_id = %s
          AND p.status = 'Успешно'
        """,
        (payment_id,)
    )
    if not payment:
        return None

    receipt_number, file_path = _generate_receipt_pdf(payment)

    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            INSERT IGNORE INTO receipts
                (payment_id, receipt_number, file_path)
            VALUES (%s, %s, %s)
            """,
            (payment_id, receipt_number, file_path)
        )
        connection.commit()
    finally:
        cursor.close()
        connection.close()

    return {
        'receipt_number': receipt_number,
        'file_path': file_path
    }


def ensure_receipts_for_successful_payments(user_id):
    """Создаёт чеки для старых успешных платежей, если чеков ещё нет."""
    ensure_receipts_table()
    rows = _fetch_all(
        """
        SELECT p.payment_id
        FROM payments AS p
        JOIN user_subscriptions AS us
            ON p.user_subscription_id = us.user_subscription_id
        LEFT JOIN receipts AS r
            ON r.payment_id = p.payment_id
        WHERE us.user_id = %s
          AND p.status = 'Успешно'
          AND r.receipt_id IS NULL
        """,
        (user_id,)
    )

    created = []
    for row in rows:
        receipt = _create_receipt_for_payment(row['payment_id'])
        if receipt:
            created.append(receipt)
    return created


def process_due_payments(user_id):
    """
    Учебная автоматическая обработка регулярных платежей.

    Если дата ожидаемого платежа наступила, система сама:
    1) меняет его статус на «Успешно»;
    2) переносит дату следующего платежа;
    3) создаёт следующий ожидаемый платёж;
    4) формирует PDF-чек;
    5) создаёт уведомление.

    Это имитация платёжной системы для курсового проекта.
    """
    ensure_receipts_table()

    due_payments = _fetch_all(
        """
        SELECT
            p.payment_id,
            p.user_subscription_id,
            p.amount,
            p.payment_date,
            us.next_payment_date,
            us.plan_id,
            sp.duration_months,
            sp.price,
            s.service_name,
            sp.plan_name
        FROM payments AS p
        JOIN user_subscriptions AS us
            ON p.user_subscription_id = us.user_subscription_id
        JOIN subscriptions_plans AS sp
            ON us.plan_id = sp.plan_id
        JOIN services AS s
            ON sp.service_id = s.service_id
        WHERE us.user_id = %s
          AND us.us_status = 'Активна'
          AND p.status = 'Ожидается'
          AND p.payment_date <= CURDATE()
        ORDER BY p.payment_date, p.payment_id
        """,
        (user_id,)
    )

    processed = []

    for payment in due_payments:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                UPDATE payments
                SET status = 'Успешно',
                    payment_date = CURDATE()
                WHERE payment_id = %s
                  AND status = 'Ожидается'
                """,
                (payment['payment_id'],)
            )

            if cursor.rowcount != 1:
                connection.rollback()
                continue

            duration = int(payment.get('duration_months') or 1)
            base_date = payment.get('next_payment_date') or date.today()
            next_date = base_date + relativedelta(months=duration)

            cursor.execute(
                """
                UPDATE user_subscriptions
                SET next_payment_date = %s,
                    end_date = %s
                WHERE user_subscription_id = %s
                """,
                (next_date, next_date, payment['user_subscription_id'])
            )

            cursor.execute(
                """
                SELECT payment_id
                FROM payments
                WHERE user_subscription_id = %s
                  AND status = 'Ожидается'
                LIMIT 1
                """,
                (payment['user_subscription_id'],)
            )
            existing_next = cursor.fetchone()

            if not existing_next:
                cursor.execute(
                    """
                    INSERT INTO payments
                        (user_subscription_id, payment_date, amount, payment_type, status)
                    VALUES (%s, %s, %s, 'Регулярный', 'Ожидается')
                    """,
                    (payment['user_subscription_id'], next_date, payment['price'])
                )

            connection.commit()

        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

        receipt = _create_receipt_for_payment(payment['payment_id'])
        receipt_number = receipt['receipt_number'] if receipt else ''

        create_user_notification(
            user_id,
            'Платёж выполнен',
            f"Оплата «{payment['service_name']} — {payment['plan_name']}» "
            f"на сумму {float(payment['amount'] or 0):.2f} ₽ обработана автоматически. "
            + (f"Чек {receipt_number} сохранён." if receipt_number else '')
        )

        processed.append({
            'payment_id': payment['payment_id'],
            'service_name': payment['service_name'],
            'plan_name': payment['plan_name'],
            'amount': payment['amount'],
            'receipt_number': receipt_number,
            'file_path': receipt['file_path'] if receipt else None
        })

    ensure_receipts_for_successful_payments(user_id)
    return processed


# =============================================================
# ВСПОМОГАТЕЛЬНЫЕ SELECT-ФУНКЦИИ
# =============================================================

def _fetch_all(query, params=()):
    """Выполняет SELECT и возвращает все строки в виде словарей."""

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(query, params)

        return cursor.fetchall()

    finally:

        if cursor:
            cursor.close()

        if connection and connection.is_connected():
            connection.close()


def _fetch_one(query, params=()):
    """Выполняет SELECT и возвращает одну строку в виде словаря."""

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(query, params)

        return cursor.fetchone()

    finally:

        if cursor:
            cursor.close()

        if connection and connection.is_connected():
            connection.close()


# =============================================================
# ПОДПИСКИ ПОЛЬЗОВАТЕЛЯ
# =============================================================

def get_user_subscriptions(user_id):
    """Возвращает все подписки пользователя."""

    query = """
        SELECT
            us.user_subscription_id,
            us.plan_id,

            s.service_name,
            s.official_website,

            sp.plan_name,
            sp.price,
            sp.duration_months,

            us.start_date,
            us.next_payment_date,
            us.end_date,
            us.us_status

        FROM user_subscriptions AS us

        JOIN subscriptions_plans AS sp
            ON us.plan_id = sp.plan_id

        JOIN services AS s
            ON sp.service_id = s.service_id

        WHERE us.user_id = %s

        ORDER BY us.next_payment_date
    """

    return _fetch_all(
        query,
        (user_id,)
    )


# =============================================================
# ПЛАТЕЖИ ПОЛЬЗОВАТЕЛЯ
# =============================================================

def get_user_payments(user_id):
    """Возвращает историю платежей пользователя вместе с данными чека."""
    ensure_receipts_table()

    query = """
        SELECT
            p.payment_id,
            p.payment_date,
            s.service_name,
            sp.plan_name,
            p.amount,
            p.payment_type,
            p.status,
            r.receipt_number,
            r.file_path AS receipt_path
        FROM payments AS p
        JOIN user_subscriptions AS us
            ON p.user_subscription_id = us.user_subscription_id
        JOIN subscriptions_plans AS sp
            ON us.plan_id = sp.plan_id
        JOIN services AS s
            ON sp.service_id = s.service_id
        LEFT JOIN receipts AS r
            ON r.payment_id = p.payment_id
        WHERE us.user_id = %s
        ORDER BY
            p.payment_date DESC,
            p.payment_id DESC
    """

    return _fetch_all(query, (user_id,))


# =============================================================
# СТАТИСТИКА ПОЛЬЗОВАТЕЛЯ
# =============================================================

def get_user_dashboard_summary(user_id):
    """
    Возвращает данные для карточек
    на главной странице пользователя.
    """

    query = """
        SELECT

            (
                SELECT COUNT(*)

                FROM user_subscriptions

                WHERE user_id = %s

                  AND us_status = 'Активна'

            ) AS active_subscriptions,


            (
                SELECT COALESCE(
                    SUM(p.amount),
                    0
                )

                FROM payments AS p

                JOIN user_subscriptions AS us
                    ON p.user_subscription_id =
                       us.user_subscription_id

                WHERE us.user_id = %s

                  AND p.status = 'Успешно'

                  AND YEAR(p.payment_date)
                      = YEAR(CURDATE())

                  AND MONTH(p.payment_date)
                      = MONTH(CURDATE())

            ) AS month_spending,


            (
                SELECT MIN(next_payment_date)

                FROM user_subscriptions

                WHERE user_id = %s

                  AND us_status = 'Активна'

                  AND next_payment_date >= CURDATE()

            ) AS nearest_payment,


            (
                SELECT COUNT(*)

                FROM user_subscriptions

                WHERE user_id = %s

                  AND us_status = 'Активна'

                  AND next_payment_date
                      BETWEEN CURDATE()
                      AND DATE_ADD(
                          CURDATE(),
                          INTERVAL 30 DAY
                      )

            ) AS upcoming_payments
    """

    return _fetch_one(
        query,
        (
            user_id,
            user_id,
            user_id,
            user_id
        )
    )


# =============================================================
# АДМИНИСТРАТОР
# =============================================================

def get_admin_subscription_status_stats():
    """Количество подписок по статусам."""

    query = """
        SELECT
            us_status AS status,
            COUNT(*) AS subscription_count

        FROM user_subscriptions

        GROUP BY us_status

        ORDER BY us_status
    """

    return _fetch_all(query)


def get_admin_monthly_payment_stats():
    """
    Суммы успешных платежей
    за последние шесть календарных месяцев.
    """

    query = """
        SELECT
            DATE_FORMAT(
                payment_date,
                '%Y-%m'
            ) AS month,

            SUM(amount) AS total_amount

        FROM payments

        WHERE status = 'Успешно'

          AND payment_date >=
              DATE_SUB(
                  DATE_FORMAT(
                      CURDATE(),
                      '%Y-%m-01'
                  ),
                  INTERVAL 5 MONTH
              )

          AND payment_date <
              DATE_ADD(
                  LAST_DAY(CURDATE()),
                  INTERVAL 1 DAY
              )

        GROUP BY
            DATE_FORMAT(
                payment_date,
                '%Y-%m'
            )

        ORDER BY month
    """

    return _fetch_all(query)


def get_admin_summary():
    """Основная статистика администратора."""

    query = """
        SELECT

            (
                SELECT COUNT(*)
                FROM users
            ) AS users_count,


            (
                SELECT COUNT(*)
                FROM user_subscriptions
            ) AS subscriptions_count,


            (
                SELECT COUNT(*)

                FROM payments

                WHERE status = 'Успешно'

            ) AS successful_payments_count,


            (
                SELECT COUNT(*)

                FROM payments

                WHERE status = 'Неуспешно'

            ) AS failed_payments_count
    """

    return _fetch_one(query)


# =============================================================
# КАТАЛОГ ТАРИФОВ
# =============================================================

def get_all_subscription_plans():
    """
    Возвращает все доступные тарифы
    из каталога сервисов.
    """

    query = """
        SELECT

            sp.plan_id,
            sp.service_id,

            s.service_name,
            s.official_website,

            sp.plan_name,
            sp.price,
            sp.duration_months

        FROM subscriptions_plans AS sp

        JOIN services AS s
            ON sp.service_id = s.service_id

        ORDER BY
            s.service_name,
            sp.price
    """

    return _fetch_all(query)


# =============================================================
# ПОДПИСКИ, УЖЕ ДОБАВЛЕННЫЕ ПОЛЬЗОВАТЕЛЕМ
# =============================================================

def get_user_plan_ids(user_id):
    """
    Возвращает множество plan_id,
    которые сейчас подключены пользователю.
    """

    query = """
        SELECT plan_id

        FROM user_subscriptions

        WHERE user_id = %s

          AND us_status = 'Активна'
    """

    rows = _fetch_all(
        query,
        (user_id,)
    )

    return {
        row["plan_id"]
        for row in rows
    }


# =============================================================
# ДОБАВЛЕНИЕ ПОДПИСКИ
# =============================================================

def add_user_subscription(user_id, plan_id):
    """
    Добавляет тариф пользователю.

    start_date        = сегодня
    next_payment_date = сегодня + срок тарифа
    end_date           = сегодня + срок тарифа
    status             = Активна
    """

    connection = None
    cursor = None

    try:

        connection = get_connection()

        cursor = connection.cursor(
            dictionary=True
        )

        # -----------------------------------------------------
        # Проверяем существующую активную подписку
        # -----------------------------------------------------

        cursor.execute(
            """
            SELECT
                user_subscription_id

            FROM user_subscriptions

            WHERE user_id = %s

              AND plan_id = %s

              AND us_status = 'Активна'
            """,
            (
                user_id,
                plan_id
            )
        )

        existing = cursor.fetchone()

        if existing:

            return (
                False,
                "Эта подписка уже добавлена."
            )

        # -----------------------------------------------------
        # Получаем тариф
        # -----------------------------------------------------

        cursor.execute(
            """
            SELECT
                plan_id,
                duration_months,
                price

            FROM subscriptions_plans

            WHERE plan_id = %s
            """,
            (plan_id,)
        )

        plan = cursor.fetchone()

        if not plan:

            return (
                False,
                "Выбранный тариф не найден."
            )

        duration_months = plan["duration_months"]

        if not duration_months:

            return (
                False,
                "У выбранного тарифа не указан срок действия."
            )

        # -----------------------------------------------------
        # Рассчитываем даты
        # -----------------------------------------------------

        start_date = date.today()

        next_payment_date = (
            start_date
            + relativedelta(
                months=int(duration_months)
            )
        )

        end_date = next_payment_date

        # -----------------------------------------------------
        # Добавляем подписку
        # -----------------------------------------------------

        cursor.execute(
            """
            INSERT INTO user_subscriptions
            (
                user_id,
                plan_id,
                start_date,
                next_payment_date,
                end_date,
                us_status
            )

            VALUES
            (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
            """,
            (
                user_id,
                plan_id,
                start_date,
                next_payment_date,
                end_date,
                "Активна"
            )
        )

        # -----------------------------------------------------
        # Создаём ожидаемый платёж по добавленной подписке
        # -----------------------------------------------------

        user_subscription_id = cursor.lastrowid

        cursor.execute(
            """
            INSERT INTO payments
            (
                user_subscription_id,
                payment_date,
                amount,
                payment_type,
                status
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                user_subscription_id,
                next_payment_date,
                plan["price"],
                "Регулярный",
                "Ожидается"
            )
        )

        # Подписка и платёж сохраняются вместе.
        connection.commit()

        return (
            True,
            "Подписка и ожидаемый платёж успешно добавлены."
        )

    except Exception as error:

        if connection:
            connection.rollback()

        return (
            False,
            f"Ошибка добавления подписки:\n{error}"
        )

    finally:

        if cursor:
            cursor.close()

        if connection and connection.is_connected():
            connection.close()


# =============================================================
# ОТМЕНА ПОДПИСКИ
# =============================================================

def cancel_user_subscription(
    user_id,
    plan_id
):
    """
    Отменяет активную подписку.

    Запись из БД НЕ удаляется.
    Меняется статус и дата окончания.
    """

    connection = None
    cursor = None

    try:

        connection = get_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE user_subscriptions

            SET
                us_status = 'Отменена',
                end_date = CURDATE()

            WHERE user_id = %s

              AND plan_id = %s

              AND us_status = 'Активна'
            """,
            (
                user_id,
                plan_id
            )
        )

        # -----------------------------------------------------
        # Проверяем, была ли изменена запись
        # -----------------------------------------------------

        if cursor.rowcount == 0:

            connection.rollback()

            return (
                False,
                "Активная подписка не найдена."
            )

        connection.commit()

        return (
            True,
            "Подписка успешно отменена."
        )

    except Exception as error:

        if connection:
            connection.rollback()

        return (
            False,
            f"Ошибка отмены подписки:\n{error}"
        )

    finally:

        if cursor:
            cursor.close()

        if connection and connection.is_connected():
            connection.close()

# =============================================================
# ПОДТВЕРЖДЕНИЕ ОПЛАТЫ ПОЛЬЗОВАТЕЛЕМ
# =============================================================

def mark_user_payment_as_paid(payment_id, user_id):
    """Помечает платёж пользователя как успешно оплаченный."""
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE payments AS p
            JOIN user_subscriptions AS us
                ON p.user_subscription_id = us.user_subscription_id
            SET p.status = 'Успешно',
                p.payment_date = CURDATE()
            WHERE p.payment_id = %s
              AND us.user_id = %s
              AND p.status = 'Ожидается'
            """,
            (payment_id, user_id)
        )
        connection.commit()

        if cursor.rowcount == 1:
            return True, 'Платёж отмечен как оплаченный.'

        return False, 'Не удалось обновить платёж. Возможно, он уже был отмечен.'

    except Exception as error:
        if connection:
            connection.rollback()
        return False, f'Не удалось обновить платёж: {error}'

    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


# =============================================================
# УВЕДОМЛЕНИЯ ПОЛЬЗОВАТЕЛЯ
# =============================================================

def get_user_notifications(user_id):
    """Возвращает уведомления пользователя от новых к старым."""
    query = """
        SELECT notification_id, title, message, created_at, read_status
        FROM notifications
        WHERE user_id = %s
        ORDER BY created_at DESC, notification_id DESC
    """
    return _fetch_all(query, (user_id,))


def mark_user_notifications_read(user_id):
    """Отмечает все уведомления выбранного пользователя как прочитанные."""
    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE notifications
            SET read_status = 'Прочитано'
            WHERE user_id = %s
              AND read_status <> 'Прочитано'
            """,
            (user_id,)
        )
        connection.commit()
    except Exception:
        if connection:
            connection.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


def create_user_notification(user_id, title, message):
    """Создаёт новое непрочитанное уведомление."""
    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO notifications
                (user_id, title, message, created_at, read_status)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP, 'Не прочитано')
            """,
            (user_id, title, message)
        )
        connection.commit()
        return True
    except Exception:
        if connection:
            connection.rollback()
        return False
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


# =============================================================
# НАСТРОЙКИ ПОЛЬЗОВАТЕЛЯ
# =============================================================

def get_user_settings(user_id):
    query = """
        SELECT user_name, surname, notifications_enabled
        FROM users
        WHERE user_id = %s
    """
    return _fetch_one(query, (user_id,))

def update_user_profile(user_id, user_name, surname):
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "UPDATE users SET user_name = %s, surname = %s WHERE user_id = %s",
            (user_name, surname, user_id)
        )
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        return False
    finally:
        cursor.close()
        connection.close()

def update_user_password(user_id, new_password):
    hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "UPDATE users SET password = %s WHERE user_id = %s",
            (hashed_password, user_id)
        )
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        return False
    finally:
        cursor.close()
        connection.close()

def update_notifications_setting(user_id, enabled):
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "UPDATE users SET notifications_enabled = %s WHERE user_id = %s",
            (1 if enabled else 0, user_id)
        )
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        return False
    finally:
        cursor.close()
        connection.close()
