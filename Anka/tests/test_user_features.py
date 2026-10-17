from datetime import date
from decimal import Decimal

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from repository import as_date
from user_window import UserWindow, CatalogDialog, PasswordDialog, write_pdf


def test_authentication_and_blocked_account(repo):
    assert repo.authenticate("test1", "testpass123")["user_name"] == "Анна"
    for login, password in [("test1", "wrong"), ("missing", "testpass123"), ("test1", "я"*73)]:
        with pytest.raises(ValueError):
            repo.authenticate(login, password)
    with repo.transaction() as cur:
        repo.execute(cur, "UPDATE users SET user_status='Заблокирован' WHERE user_id=1")
    with pytest.raises(ValueError, match="заблокирована"):
        repo.authenticate("test1", "testpass123")


def test_dashboard_uses_actual_tariff_prices(repo):
    summary = repo.summary(1)
    assert summary["active"] == 5
    assert summary["monthly"] == Decimal("3324")
    assert summary["upcoming"] == 3


def test_add_duplicate_cancel_and_reactivate(repo):
    repo.add_subscription(1, 7)
    sub = next(s for s in repo.subscriptions(1) if s["plan_id"] == 7)
    with pytest.raises(ValueError, match="уже подключён"):
        repo.add_subscription(1, 7)
    assert len([p for p in repo.payments(1) if p["user_subscription_id"] == sub["user_subscription_id"]]) == 1
    with pytest.raises(ValueError):
        repo.cancel_subscription(2, sub["user_subscription_id"])
    repo.cancel_subscription(1, sub["user_subscription_id"])
    assert all(p["status"] == "Отменён" for p in repo.payments(1) if p["user_subscription_id"] == sub["user_subscription_id"])
    repo.add_subscription(1, 7)
    assert sum(s["plan_id"] == 7 and s["us_status"] == "Активна" for s in repo.subscriptions(1)) == 1


def test_inactive_service_cannot_be_added(repo):
    with repo.transaction() as cur:
        repo.execute(cur, "UPDATE services SET service_status='Неактивен' WHERE service_id=7")
    assert all(p["plan_id"] != 7 for p in repo.catalog())
    with pytest.raises(ValueError):
        repo.add_subscription(1, 7)


def test_payment_is_atomic_scoped_and_idempotent(repo):
    payment = next(p for p in repo.payments(1) if p["status"] == "Ожидается")
    with pytest.raises(ValueError):
        repo.pay(2, payment["payment_id"])
    repo.pay(1, payment["payment_id"])
    updated = repo.payments(1)
    assert next(p for p in updated if p["payment_id"] == payment["payment_id"])["status"] == "Успешно"
    assert sum(p["status"] == "Ожидается" and p["user_subscription_id"] == payment["user_subscription_id"] for p in updated) == 1
    assert len(updated) == 11
    with pytest.raises(ValueError):
        repo.pay(1, payment["payment_id"])
    assert len(repo.payments(1)) == 11


def test_cancelled_payment_cannot_be_paid_and_history_survives(repo):
    pending = next(p for p in repo.payments(1) if p["status"] == "Ожидается")
    repo.cancel_subscription(1, pending["user_subscription_id"])
    with pytest.raises(ValueError):
        repo.pay(1, pending["payment_id"])
    assert sum(p["status"] == "Успешно" for p in repo.payments(1)) == 5
    history = repo.rows("SELECT * FROM subscription_history")
    assert history[0]["new_status"] == "Отменена"


def test_profile_flags_persist_and_validate(repo):
    flags = {"reminders": False, "success": True, "errors": False}
    repo.save_profile(1, "Аня", "Рыбакова", "anya@example.com", "Тёмная", flags)
    assert repo.preferences(1)["theme"] == "Тёмная"
    assert repo.preferences(1)["email"] == "anya@example.com"
    assert repo.preferences(1)["reminders"] is False
    assert repo.authenticate("test1", "testpass123")["user_name"] == "Аня"
    assert repo.one("SELECT payment_reminders_enabled FROM user_settings WHERE user_id=1")["payment_reminders_enabled"] == 0
    with pytest.raises(ValueError):
        repo.save_profile(1, "", "Рыбакова", "bad", "Светлая", flags)
    with pytest.raises(ValueError):
        repo.save_profile(1, "А"*51, "Рыбакова", "anya@example.com", "Светлая", flags)


def test_change_password_needs_current_and_matching_new(repo):
    for current, new, repeated in [("wrong", "newpass123", "newpass123"), ("testpass123", "short", "short"), ("testpass123", "newpass123", "different")]:
        with pytest.raises(ValueError):
            repo.change_password(1, current, new, repeated)
    repo.change_password(1, "testpass123", "newpass123", "newpass123")
    assert repo.authenticate("test1", "newpass123")
    with pytest.raises(ValueError):
        repo.authenticate("test1", "testpass123")


def test_reminders_are_deduplicated_and_scoped(repo):
    repo.refresh_reminders(1)
    first = repo.notifications(1)
    repo.refresh_reminders(1)
    assert len(repo.notifications(1)) == len(first) == 2
    repo.mark_read(2, first[0]["notification_id"])
    assert repo.notifications(1)[0]["read_status"] != "Прочитано"
    repo.mark_read(1)
    assert all(n["read_status"] == "Прочитано" for n in repo.notifications(1))
    repo.refresh_reminders(1)
    assert len(repo.notifications(1)) == 2


def test_disabled_reminders_and_success_notifications(repo):
    repo.save_profile(1, "Анна", "Рыбакова", "anna@mail.ru", "Светлая", {"reminders":False,"success":False,"errors":False})
    count = len(repo.notifications(1))
    repo.refresh_reminders(1)
    assert len(repo.notifications(1)) == count
    pending = next(p for p in repo.payments(1) if p["status"] == "Ожидается")
    repo.pay(1, pending["payment_id"])
    assert len(repo.notifications(1)) == count


def test_month_boundary_uses_calendar_months(repo):
    with repo.transaction() as cur:
        repo.execute(cur, "UPDATE user_subscriptions SET next_payment_date='2028-01-31' WHERE user_subscription_id=1")
    pending = next(p for p in repo.payments(1) if p["status"] == "Ожидается" and p["user_subscription_id"] == 1)
    repo.pay(1, pending["payment_id"])
    sub = next(s for s in repo.subscriptions(1) if s["user_subscription_id"] == 1)
    assert as_date(sub["next_payment_date"]) == date(2028, 2, 29)


def test_gui_navigation_search_settings_and_pdf(app, repo, tmp_path, monkeypatch):
    window = UserWindow(repo.authenticate("test1", "testpass123"), repo, receipt_directory=tmp_path/'receipts')
    window.show()
    app.processEvents()
    assert window.welcomeLabel.text() == "Привет, Анна!"
    QTest.mouseClick(window.subscriptionsButton, Qt.MouseButton.LeftButton)
    assert window.page == "subscriptions"
    window.searchInput.setText("spotify")
    assert window.sub_rows.count() == 1
    window.searchInput.clear()
    QTest.mouseClick(window.sub_tabs["inactive"], Qt.MouseButton.LeftButton)
    assert window.sub_rows.count() == 1
    window.navigate("payments")
    window.payment_status.setCurrentText("Успешно")
    assert len(window.filtered_payments) == 5
    target = tmp_path / "payments.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (str(target), ""))
    window.export_payments("csv")
    assert "Spotify" in target.read_text(encoding="utf-8-sig")
    target = tmp_path / "receipt.pdf"
    window.receipt(next(p for p in window.payments if p["status"] == "Успешно"))
    assert target.read_bytes().startswith(b"%PDF")
    window.navigate("notifications")
    window.mark_all_read()
    assert not window.bellBadge.isVisible()
    window.navigate("settings")
    window.nameInput.setText("Аня")
    window.themeInput.setCurrentText("Тёмная")
    assert window.save_settings()
    assert window.welcomeLabel.text() == "Привет, Аня!"
    window.close()


def test_catalog_and_password_dialog(app, repo):
    catalog = CatalogDialog(repo, 1)
    catalog.search.setText("VK")
    assert catalog.rows.count() == 1
    catalog.add(next(p for p in repo.catalog() if p["plan_id"] == 7))
    assert catalog.result() == 1
    change = PasswordDialog(repo, 1)
    for field, text in zip(change.fields, ["testpass123", "newpass123", "newpass123"]):
        field.setText(text)
    change.save()
    assert change.result() == 1


def test_pdf_with_cyrillic(app, tmp_path):
    target = tmp_path / "history.pdf"
    write_pdf(target, "История платежей", ["Сервис", "Цена"], [["Яндекс 360", "299 ₽"]])
    assert target.read_bytes().startswith(b"%PDF")
    assert target.stat().st_size > 2000


def test_failed_payment_notifications_respect_setting(repo):
    with repo.transaction() as cur:
        repo.execute(cur, "UPDATE payments SET status='Неуспешно' WHERE payment_id=1")
    repo.refresh_failed_payment_notifications(1)
    repo.refresh_failed_payment_notifications(1)
    assert sum('Ошибка платежа' in n['title'] for n in repo.notifications(1)) == 1
    assert not repo.notifications(2)


def test_transaction_rolls_back_partial_add(repo, monkeypatch):
    original_execute = repo.execute
    def fail_notification(cur, sql, params=()):
        if 'INSERT INTO notifications' in sql:
            raise RuntimeError('Injected failure')
        return original_execute(cur, sql, params)
    monkeypatch.setattr(repo, 'execute', fail_notification)
    with pytest.raises(RuntimeError):
        repo.add_subscription(1, 7)
    assert all(s['plan_id'] != 7 for s in repo.subscriptions(1))
    assert len(repo.payments(1)) == 10


def test_login_and_logout_restore_login_window(app, repo, monkeypatch):
    import main
    monkeypatch.setattr(main, 'Repository', lambda: repo)
    # This session already has its isolated preferences table.
    monkeypatch.setattr(repo, 'ensure_preferences', lambda: None)
    login = main.LoginWindow()
    login.show()
    login.usernameInput.setText('test1')
    login.passwordInput.setText('testpass123')
    QTest.mouseClick(login.loginButton, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert login.role_window.isVisible()
    assert not login.isVisible()
    login.role_window.logout()
    app.processEvents()
    assert login.isVisible()
    assert login.passwordInput.text() == ''
    login.close()
