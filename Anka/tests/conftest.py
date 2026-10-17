"""MySQL integration fixture: all writes target SESSION TEMPORARY tables.

MySQL resolves these names to temporary tables before permanent ones. Only
definitions are cloned. No real rows are read, copied or changed.
"""
import os
from pathlib import Path
import sys
from datetime import date, timedelta
import json
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bcrypt
import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFontDatabase
from database import get_connection
from repository import Repository, DEFAULTS


class BorrowedConnection:
    def __init__(self, conn):
        self.conn = conn

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def close(self):
        self.conn.rollback()


class TemporaryRepository(Repository):
    def __init__(self, conn):
        super().__init__()
        self.test_connection = conn

    def connect(self):
        return BorrowedConnection(self.test_connection)


def make_repository():
    conn = get_connection()
    cur = conn.cursor()
    for table in ["users", "services", "subscriptions_plans", "user_subscriptions", "payments", "notifications", "user_settings", "subscription_history", "receipts"]:
        cur.execute(f"SHOW CREATE TABLE `{table}`")
        definition = cur.fetchone()[1]
        definition = definition.replace("CREATE TABLE", "CREATE TEMPORARY TABLE", 1)
        definition = re.sub(r"\bAUTO_INCREMENT=\d+", "", definition)
        definition = "\n".join(line for line in definition.splitlines() if "CONSTRAINT" not in line)
        definition = re.sub(r",\s*\) ENGINE", "\n) ENGINE", definition)
        cur.execute(definition)
    cur.execute("CREATE TEMPORARY TABLE user_preferences(user_id INT PRIMARY KEY,preferences TEXT NOT NULL)")
    event_definition = (Path(__file__).resolve().parents[1] / 'db' / '002_payment_events.sql').read_text(encoding='utf-8').split(';')[0]
    event_definition = event_definition.replace('CREATE TABLE IF NOT EXISTS', 'CREATE TEMPORARY TABLE')
    event_definition = '\n'.join(line for line in event_definition.splitlines() if 'FOREIGN KEY' not in line)
    event_definition = re.sub(r',\s*\)', '\n)', event_definition)
    cur.execute(event_definition)
    hashed = bcrypt.hashpw(b"testpass123", bcrypt.gensalt()).decode()
    for uid, name in [(1, "Анна"), (2, "Тест")]:
        cur.execute("INSERT INTO users(user_id,login,password,role,user_name,surname,user_status) VALUES (%s,%s,%s,'Пользователь',%s,'Рыбакова','Активен')", (uid, f"test{uid}", hashed, name))
    catalog = [
        ("Spotify", "https://open.spotify.com", "Premium", 399),
        ("Netflix", "https://www.netflix.com", "Стандартный", 699),
        ("YouTube Premium", "https://www.youtube.com/premium", "Индивидуальный", 299),
        ("Яндекс 360", "https://360.yandex.ru", "Премиум", 299),
        ("Adobe Photoshop", "https://www.adobe.com/products/photoshop.html", "Индивидуальный", 1628),
        ("Кинопоиск", "https://www.kinopoisk.ru", "Плюс", 399),
        ("VK Музыка", "https://music.vk.com", "Индивидуальный", 199),
    ]
    today = date.today()
    for i, (name, url, plan, price) in enumerate(catalog, 1):
        cur.execute("INSERT INTO services(service_id,service_name,official_website,service_status,service_description,category_id) VALUES (%s,%s,%s,'Активен','Test fixture',1)", (i, name, url))
        cur.execute("INSERT INTO subscriptions_plans(plan_id,service_id,plan_name,plan_description,price,duration_months) VALUES (%s,%s,%s,'Test fixture',%s,1)", (i, i, plan, price))
        if i <= 6:
            due = today+timedelta(days=[1,4,7,9,24,0][i-1])
            cur.execute("INSERT INTO user_subscriptions(user_subscription_id,user_id,plan_id,start_date,next_payment_date,end_date,us_status) VALUES (%s,1,%s,%s,%s,%s,%s)", (i, i, today-timedelta(days=30), due, due, "Активна" if i <= 5 else "Отменена"))
            if i <= 5:
                cur.execute("INSERT INTO payments(user_subscription_id,payment_date,amount,payment_type,status) VALUES (%s,%s,%s,'Регулярный','Успешно')", (i, today-timedelta(days=i), price))
                cur.execute("INSERT INTO payments(user_subscription_id,payment_date,amount,payment_type,status) VALUES (%s,%s,%s,'Регулярный','Ожидается')", (i, due, price))
    cur.execute("INSERT INTO user_preferences VALUES (1,%s)", (json.dumps({**DEFAULTS, "email": "anna@mail.ru"}),))
    cur.execute("INSERT INTO notifications(user_id,title,message,read_status) VALUES (1,'Добро пожаловать','Все подписки и платежи — в одном месте.','Не прочитано')")
    conn.commit()
    cur.close()
    return TemporaryRepository(conn), conn


@pytest.fixture
def repo():
    repository, conn = make_repository()
    try:
        yield repository
    finally:
        conn.close()


@pytest.fixture(scope="session")
def app():
    application = QApplication.instance() or QApplication([])
    for filename in ['segoeui.ttf', 'segoeuib.ttf', 'seguisb.ttf', 'seguisym.ttf']:
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+filename)
    application.setStyle("Fusion")
    yield application
