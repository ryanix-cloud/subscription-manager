"""Small optional additions to the existing repository."""
from datetime import date
from decimal import Decimal


def ensure_extra(repo):
    with repo.transaction() as cur:
        repo.execute(cur, """CREATE TABLE IF NOT EXISTS personal_plans (
            plan_id INT PRIMARY KEY, user_id INT NOT NULL,
            FOREIGN KEY (plan_id) REFERENCES subscriptions_plans(plan_id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci""")


def add_personal(repo, uid, name, price, months, category_id=None):
    if not name.strip() or Decimal(str(price)) < 0 or int(months) < 1:
        raise ValueError('Укажите название, стоимость и период оплаты.')
    with repo.transaction() as cur:
        repo.execute(cur, 'SELECT category_id FROM categories ORDER BY category_id LIMIT 1')
        category = cur.fetchone()
        if not category:
            raise ValueError('В базе данных нет категорий сервисов.')
        category_id = category['category_id']
        repo.execute(cur, """INSERT INTO services(service_name,official_website,service_status,service_description,category_id)
            VALUES (%s,'','Активен','Личная подписка',%s)""", (name.strip(), category_id))
        service_id = cur.lastrowid
        repo.execute(cur, """INSERT INTO subscriptions_plans(service_id,plan_name,plan_description,price,duration_months)
            VALUES (%s,'Мой тариф','Личная подписка',%s,%s)""", (service_id, Decimal(str(price)), int(months)))
        plan_id = cur.lastrowid
        repo.execute(cur, 'INSERT INTO personal_plans(plan_id,user_id) VALUES (%s,%s)', (plan_id, uid))
    repo.add_subscription(uid, plan_id)


def edit_subscription(repo, uid, sid, next_date, price=None):
    with repo.transaction() as cur:
        repo.execute(cur, 'SELECT plan_id,us_status FROM user_subscriptions WHERE user_id=%s AND user_subscription_id=%s', (uid, sid))
        row = cur.fetchone()
        if not row or row['us_status'] != 'Активна':
            raise ValueError('Подписка не активна.')
        repo.execute(cur, "UPDATE user_subscriptions SET next_payment_date=%s,end_date=%s WHERE user_subscription_id=%s", (next_date, next_date, sid))
        repo.execute(cur, "UPDATE payments SET payment_date=%s WHERE user_subscription_id=%s AND status='Ожидается'", (next_date, sid))
        repo.execute(cur, 'SELECT plan_id FROM personal_plans WHERE plan_id=%s AND user_id=%s', (row['plan_id'], uid))
        personal = cur.fetchone() is not None
        if personal and price is not None:
            repo.execute(cur, 'UPDATE subscriptions_plans SET price=%s WHERE plan_id=%s', (Decimal(str(price)), row['plan_id']))
            repo.execute(cur, "UPDATE payments SET amount=%s WHERE user_subscription_id=%s AND status='Ожидается'", (Decimal(str(price)), sid))
        repo.execute(cur, """INSERT INTO subscription_history(user_subscription_id,old_status,new_status,comment)
            VALUES (%s,'Активна','Активна','Изменены параметры подписки')""", (sid,))
    return personal


def history(repo, uid):
    return repo.rows("""SELECT h.*,s.service_name FROM subscription_history h
        JOIN user_subscriptions us ON us.user_subscription_id=h.user_subscription_id
        JOIN subscriptions_plans p ON p.plan_id=us.plan_id
        JOIN services s ON s.service_id=p.service_id
        WHERE us.user_id=%s ORDER BY h.user_subscription_id DESC""", (uid,))


def pause_subscription(repo, uid, sid):
    """Pause future charges without deleting the existing subscription."""
    with repo.transaction() as cur:
        repo.execute(cur, "UPDATE user_subscriptions SET us_status='Приостановлена' WHERE user_id=%s AND user_subscription_id=%s AND us_status='Активна'", (uid, sid))
        if cur.rowcount != 1:
            raise ValueError('Активная подписка не найдена.')
        repo.execute(cur, "UPDATE payments SET status='Отменён' WHERE user_subscription_id=%s AND status IN ('Ожидается','Неуспешно')", (sid,))
        repo.execute(cur, "INSERT INTO subscription_history(user_subscription_id,old_status,new_status,comment) VALUES (%s,'Активна','Приостановлена','Приостановка пользователем')", (sid,))
        repo._notify(cur, uid, 'Подписка приостановлена', 'Будущие учебные оплаты этой подписки отменены.')


def resume_subscription(repo, uid, sid):
    """Resume the same record and schedule the next simulated charge."""
    with repo.transaction() as cur:
        repo.execute(cur, "SELECT sp.price FROM user_subscriptions us JOIN subscriptions_plans sp ON sp.plan_id=us.plan_id WHERE us.user_id=%s AND us.user_subscription_id=%s AND us.us_status='Приостановлена'", (uid, sid))
        plan = cur.fetchone()
        if not plan:
            raise ValueError('Приостановленная подписка не найдена.')
        repo.execute(cur, "UPDATE user_subscriptions SET us_status='Активна',next_payment_date=%s,end_date=%s WHERE user_subscription_id=%s", (date.today(), date.today(), sid))
        repo.execute(cur, "INSERT INTO payments(user_subscription_id,payment_date,amount,payment_type,status) VALUES (%s,%s,%s,'Регулярный','Ожидается')", (sid, date.today(), plan['price']))
        repo.execute(cur, "INSERT INTO subscription_history(user_subscription_id,old_status,new_status,comment) VALUES (%s,'Приостановлена','Активна','Возобновление пользователем')", (sid,))
        repo._notify(cur, uid, 'Подписка возобновлена', 'Выполняется учебная проверка оплаты.')
