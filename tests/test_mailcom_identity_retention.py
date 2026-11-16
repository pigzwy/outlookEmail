"""mail.com Cookie message identity remains separate from IMAP cache IDs."""

import importlib
import os
import tempfile

import pytest


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
os.environ.setdefault('DATABASE_PATH', os.path.join(tempfile.mkdtemp(prefix='mailcom-identity-import-'), 'test.db'))
web = importlib.import_module('web_outlook_app')


@pytest.fixture
def mailcom_account(tmp_path, monkeypatch):
    monkeypatch.setattr(web, 'DATABASE', str(tmp_path / 'mailcom-identity.db'))
    monkeypatch.setitem(web.app.config, 'TESTING', True)
    monkeypatch.setitem(web.app.config, 'WTF_CSRF_ENABLED', False)
    web.clear_normal_mail_local_retention_enabled_cache()
    with web.app.app_context():
        web.init_db()
        assert web.add_account(
            'identity@mail.com', '', account_type='imap', provider='mailcom',
            imap_host='imap.mail.com', imap_password='fixture-password',
        )
        account = web.get_account_by_email('identity@mail.com')
        yield account
    web.clear_normal_mail_local_retention_enabled_cache()


def _seed_row(account, identifier, mode, body):
    db = web.get_db()
    db.execute(
        'INSERT INTO retained_normal_mail_messages '
        '(account_id, folder, provider_message_id, id_mode, subject, body, body_preview, list_cached, body_cached) '
        "VALUES (?, 'inbox', ?, ?, ?, ?, ?, 1, 1)",
        (account['id'], identifier, mode, mode + ' subject', body, mode + ' preview'),
    )
    db.commit()


def test_imap_upgrade_preserves_explicit_mailcom_cookie_cache(mailcom_account):
    _seed_row(mailcom_account, 'cookie-message', 'mailcom', 'cookie body')
    _seed_row(mailcom_account, 'legacy-imap-message', 'uid', 'legacy IMAP body')
    db = web.get_db()
    db.execute("DELETE FROM settings WHERE key = 'imap_uid_identity_cache_migrated'")
    db.commit()

    web.init_db()
    rows = {row['provider_message_id']: dict(row) for row in db.execute(
        'SELECT provider_message_id, id_mode, list_cached, body_cached, body, body_preview '
        'FROM retained_normal_mail_messages WHERE account_id = ?', (mailcom_account['id'],)
    )}
    assert (rows['cookie-message']['list_cached'], rows['cookie-message']['body_cached']) == (1, 1)
    assert rows['cookie-message']['body'] == 'cookie body'
    assert rows['cookie-message']['body_preview'] == 'mailcom preview'
    assert (rows['legacy-imap-message']['list_cached'], rows['legacy-imap-message']['body_cached']) == (0, 0)
    assert rows['legacy-imap-message']['body'] == 'legacy IMAP body'


def test_cookie_detail_never_overwrites_same_id_in_imap_cache(mailcom_account):
    _seed_row(mailcom_account, '42', 'uid', 'old IMAP body')
    assert web.upsert_retained_normal_mail_detail(
        mailcom_account, 'inbox', '42',
        {'id': '42', 'subject': 'Cookie subject', 'body': 'cookie body', 'body_type': 'text'},
        'mailcom', 'mailcom', '',
    )
    rows = {row['id_mode']: row['body'] for row in web.get_db().execute(
        'SELECT id_mode, body FROM retained_normal_mail_messages '
        'WHERE account_id = ? AND provider_message_id = ?', (mailcom_account['id'], '42')
    )}
    assert rows == {'uid': 'old IMAP body', 'mailcom': 'cookie body'}


def test_cookie_local_detail_does_not_return_same_id_imap_body(mailcom_account, monkeypatch):
    _seed_row(mailcom_account, '42', 'uid', 'wrong IMAP body')
    monkeypatch.setattr(web, 'get_account_proxy_url', lambda _account: '')
    monkeypatch.setattr(web, 'get_account_proxy_failover_urls', lambda _account: [])
    monkeypatch.setattr(web, 'is_normal_mail_local_retention_enabled', lambda: True)
    calls = []

    def fetch_cookie(_account, message_id, folder, _proxy):
        calls.append((message_id, folder))
        return {'success': True, 'email': {
            'id': message_id, 'subject': 'Cookie subject', 'body': 'cookie body', 'body_type': 'text',
        }}

    monkeypatch.setattr(web, 'get_email_detail_mailcom', fetch_cookie)
    result = web.fetch_email_detail_for_account(mailcom_account, '42', 'mailcom', 'inbox', 'uid', prefer_local=True)
    assert result['success']
    assert result['email']['body'] == 'cookie body'
    assert calls == [('42', 'inbox')]

    calls.clear()
    cached = web.fetch_email_detail_for_account(mailcom_account, '42', 'mailcom', 'inbox', 'uid', prefer_local=True)
    assert cached['success']
    assert cached['source'] == 'local_retention'
    assert cached['email']['id_mode'] == 'mailcom'
    assert cached['email']['body'] == 'cookie body'
    assert calls == []
