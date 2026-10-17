import bcrypt
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from registration import RegistrationDialog


@pytest.fixture
def registration_repo(repo,monkeypatch):
    # Test tables already exist; avoid production DDL and MySQL implicit commits.
    monkeypatch.setattr(repo,'ensure_preferences',lambda:None)
    return repo


def test_registration_creates_regular_account_and_initial_settings(registration_repo):
    repo=registration_repo
    uid=repo.register_user('  anya_new  ','пароль123','пароль123',' Аня ',' Иванова ','anna@example.ru')
    user=repo.authenticate('anya_new','пароль123')
    assert user['user_id']==uid
    assert user['role']=='Пользователь' and user['user_status']=='Активен'
    assert user['user_name']=='Аня'
    assert user['password']!='пароль123'
    assert bcrypt.checkpw('пароль123'.encode(),user['password'].encode())
    assert repo.preferences(uid)['email']=='anna@example.ru'
    assert repo.one('SELECT * FROM user_settings WHERE user_id=%s',(uid,))['reminder_days']==3
    assert len(repo.notifications(uid))==1
    assert repo.subscriptions(uid)==[] and repo.payments(uid)==[]


def test_duplicate_login_including_case_is_rejected_without_partial_settings(registration_repo):
    repo=registration_repo
    with pytest.raises(ValueError,match='занят'):
        repo.register_user('TEST1','password123','password123','Анна','Иванова','a@example.ru')
    assert len(repo.rows('SELECT * FROM users'))==2
    assert repo.rows('SELECT * FROM user_settings')==[]


@pytest.mark.parametrize('change',[
    {'login':'ab'},{'login':'a b'},{'login':'a'*16},{'email':'invalid'},
    {'name':''},{'surname':'a'*51},{'password':'short','confirmation':'short'},
    {'confirmation':'different'},{'password':'я'*37,'confirmation':'я'*37}])
def test_invalid_registration_does_not_write(registration_repo,change):
    values=dict(login='new_user',password='password123',confirmation='password123',
                name='Анна',surname='Иванова',email='a@example.ru')
    values.update(change)
    with pytest.raises(ValueError): registration_repo.register_user(**values)
    assert len(registration_repo.rows('SELECT * FROM users'))==2


def test_failed_initialization_rolls_back_entire_registration(registration_repo,monkeypatch):
    repo=registration_repo
    def fail(*args): raise RuntimeError('Test notification failure')
    monkeypatch.setattr(repo,'_notify',fail)
    with pytest.raises(RuntimeError):
        repo.register_user('new_user','password123','password123','Анна','Иванова','a@example.ru')
    assert len(repo.rows('SELECT * FROM users'))==2
    assert repo.rows('SELECT * FROM user_settings')==[]
    assert len(repo.rows('SELECT * FROM user_preferences'))==1


def test_registration_dialog_error_correction_then_login(app,registration_repo,monkeypatch):
    import main
    repo=registration_repo
    monkeypatch.setattr(main,'Repository',lambda:repo)
    login=main.LoginWindow()
    login.show()
    assert login.registerButton.isVisible()
    original_exec=RegistrationDialog.exec
    def complete(dialog):
        values=dict(login='new_user',password='password123',confirmation='mismatch',
                    name='Анна',surname='Иванова',email='a@example.ru')
        dialog.show()
        for key,value in values.items(): dialog.fields[key].setText(value)
        QTest.mouseClick(dialog.submitButton,Qt.MouseButton.LeftButton)
        assert 'не совпадают' in dialog.errorLabel.text()
        assert dialog.created_login is None
        dialog.fields['confirmation'].setText('password123')
        QTest.mouseClick(dialog.submitButton,Qt.MouseButton.LeftButton)
        return dialog.result()
    monkeypatch.setattr(RegistrationDialog,'exec',complete)
    QTest.mouseClick(login.registerButton,Qt.MouseButton.LeftButton)
    assert login.usernameInput.text()=='new_user'
    assert not login.passwordInput.text()
    login.passwordInput.setText('password123')
    QTest.mouseClick(login.loginButton,Qt.MouseButton.LeftButton)
    assert login.role_window.isVisible()
    assert login.role_window.user['role']=='Пользователь'
    login.role_window.logout()
    login.close()
