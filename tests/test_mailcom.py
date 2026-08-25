import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from outlook_web.mailcom_provider import (
    MailcomCookieProvider,
    collect_messagelist_with_paging,
    extract_messagelist_next_url,
    extract_ott,
    html_indicates_bad_credentials,
    is_mailcom_login_failed_url,
    is_transient_login_error,
    normalize_mailcom_success_url,
    parse_forms,
    parse_lightmailer_message_list,
    parse_message_detail_html,
    parse_message_list_html,
    pick_login_form,
    session_looks_valid,
)
from outlook_web.mail_datetime import normalize_mail_date_for_display, parse_mail_datetime
from outlook_web.mailcom_service import (
    MAILCOM_METHOD,
    MAILCOM_PROVIDER_KEY,
    _message_to_list_item,
    dump_mailcom_session,
    is_mailcom_account,
    is_mailcom_domain,
    load_mailcom_session,
    mailcom_unsupported_action,
)
from outlook_web.mailcom_types import Message, extract_verification_code


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _temp_dir = tempfile.mkdtemp(prefix='outlookEmail-mailcom-tests-')
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')

web_outlook_app = importlib.import_module('web_outlook_app')

FIXTURES = Path(__file__).parent / 'fixtures' / 'mailcom'


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding='utf-8')


class _FakeResp:
    def __init__(self, text: str, status_code: int = 200, url: str = 'https://www.mail.com/mail'):
        self.text = text
        self.status_code = status_code
        self.url = url
        self.content = text.encode('utf-8')


class _FakeCookies:
    def __init__(self):
        self._data = {}
        self.jar = []

    def set(self, name, value, **kwargs):
        self._data[name] = value
        cookie = SimpleNamespace(
            name=name,
            value=value,
            domain=kwargs.get('domain', ''),
            path=kwargs.get('path', '/'),
            secure=False,
            rest={},
        )
        self.jar = [item for item in self.jar if item.name != name] + [cookie]

    def clear(self):
        self._data.clear()
        self.jar.clear()

    def items(self):
        return self._data.items()


class _FakeClient:
    def __init__(self, routes):
        self.routes = routes
        self.cookies = _FakeCookies()
        self.closed = False
        self.posts = []

    def get(self, url, **kwargs):
        for key, val in self.routes.items():
            if key in url or url.endswith(key) or url == key:
                if isinstance(val, _FakeResp):
                    return val
                return _FakeResp(val, url=url)
        return _FakeResp(_load('session_expired.html'), url=url)

    def post(self, url, **kwargs):
        self.posts.append({'url': url, 'data': kwargs.get('data')})
        for key, val in self.routes.items():
            if key in url:
                if isinstance(val, _FakeResp):
                    return val
                return _FakeResp(val, url=url)
        return _FakeResp(_load('folder_list_ok.html'), url=url)

    def close(self):
        self.closed = True


class MailcomProviderParseTests(unittest.TestCase):
    def test_session_valid_marker(self):
        self.assertTrue(session_looks_valid(_load('folder_list_ok.html')))
        self.assertFalse(session_looks_valid(_load('session_expired.html')))
        self.assertFalse(session_looks_valid(_load('login_page.html')))

    def test_bad_credentials_not_false_positive(self):
        self.assertFalse(html_indicates_bad_credentials('Something went wrong with cookies'))
        self.assertTrue(html_indicates_bad_credentials('Invalid password. Please try again.'))
        self.assertTrue(html_indicates_bad_credentials('密码错误，请重试'))

    def test_transient_login_error(self):
        self.assertTrue(is_transient_login_error('mail.com login parse failed'))
        self.assertFalse(is_transient_login_error('账号或密码错误'))

    def test_logout_ls_wd_is_bad_password(self):
        self.assertTrue(is_mailcom_login_failed_url('https://www.mail.com/logout/?ls=wd'))
        self.assertFalse(is_mailcom_login_failed_url('https://navigator-lxa.mail.com/login?ott=abc'))

    def test_normalize_success_url(self):
        self.assertIn('navigator-lxa', normalize_mailcom_success_url(
            'https://$(clientName)-$(dataCenter).mail.com/login'
        ))

    def test_extract_ott_strips_url_fragment(self):
        url = (
            'https://navigator-lxa.mail.com/login?edition=us'
            '&ott=3c152019-53b9-4da1-9c74-789bb9205941#.7518-header-login1-1'
        )
        self.assertEqual(extract_ott(url, ''), '3c152019-53b9-4da1-9c74-789bb9205941')

    def test_parse_login_form(self):
        form = pick_login_form(parse_forms(_load('login_page.html')))
        self.assertIsNotNone(form)
        self.assertEqual(form['action'], '/login/submit')
        self.assertIn('username', form['inputs'])
        self.assertEqual(form['inputs']['token']['value'], 'csrf-abc-123')

    def test_parse_message_list_fixture(self):
        msgs = parse_message_list_html(_load('folder_list_ok.html'), limit=10)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].id, 'msg-001')
        self.assertIn('verification', msgs[0].subject.lower())

    def test_extract_messagelist_next_url(self):
        page1 = _load('messagelist_page1.html')
        nxt = extract_messagelist_next_url(
            'https://lightmailer.mail.com/messagelist?folderId=INBOX&page=1',
            page1,
        )
        self.assertIsNotNone(nxt)
        self.assertIn('page=2', nxt)
        self.assertIsNone(extract_messagelist_next_url(
            'https://lightmailer.mail.com/messagelist?folderId=INBOX&page=2',
            _load('messagelist_page2.html'),
        ))

    def test_collect_messagelist_with_paging(self):
        page1 = _load('messagelist_page1.html')
        page2 = _load('messagelist_page2.html')
        base = 'https://lightmailer.mail.com/messagelist?folderId=INBOX&page=1'

        class PagingClient:
            def __init__(self):
                self.gets = []

            def get(self, url, **kwargs):
                self.gets.append(url)
                if 'page=2' in url:
                    return _FakeResp(page2, url=url)
                return _FakeResp(page1, url=url)

        client = PagingClient()
        msgs = collect_messagelist_with_paging(
            client,
            first_url=base,
            first_html=page1,
            limit=3,
            folder='inbox',
        )
        self.assertEqual(len(msgs), 3)
        self.assertTrue(any('page=2' in url for url in client.gets))

    def test_parse_lightmailer_page1(self):
        msgs = parse_lightmailer_message_list(
            'https://lightmailer.mail.com/messagelist',
            _load('messagelist_page1.html'),
            limit=10,
            folder='inbox',
        )
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].id, '1001')

    def test_parse_message_detail_and_code(self):
        msg = parse_message_detail_html(_load('message_detail.html'), msg_id='msg-001')
        self.assertEqual(msg.subject, 'Your verification code')
        self.assertEqual(msg.verification_code, '482913')
        self.assertIn('482913', msg.body_text)

    def test_try_restore_and_login(self):
        provider = MailcomCookieProvider()
        ok_client = _FakeClient({'/mail': _load('folder_list_ok.html')})
        ok, meta = provider.try_restore(
            ok_client,
            [{'name': 'sid', 'value': 'abc', 'domain': '.mail.com', 'path': '/'}],
            site='mail.com',
        )
        self.assertTrue(ok)
        self.assertEqual(meta.get('last_probe'), 'restore_ok')

        stale = _FakeClient({'/mail': _load('session_expired.html')})
        ok, meta = provider.try_restore(stale, [{'name': 'sid', 'value': 'stale'}], site='mail.com')
        self.assertFalse(ok)

        login_client = _FakeClient({
            '/login': _load('login_page.html'),
            '/login/submit': _load('folder_list_ok.html'),
            '/mail': _load('folder_list_ok.html'),
        })
        ok, err, _ = provider.full_login(login_client, 'user@mail.com', 'secret', site='mail.com')
        self.assertTrue(ok, err)
        self.assertTrue(login_client.posts)
        self.assertEqual(login_client.posts[0]['data'].get('username'), 'user@mail.com')
        self.assertEqual(login_client.posts[0]['data'].get('password'), 'secret')

    def test_full_login_wrong_password_logout(self):
        provider = MailcomCookieProvider()
        home = (
            '<html><body><form method="post" action="https://login.mail.com/login">'
            '<input type="hidden" name="successURL" value="https://$(clientName)-$(dataCenter).mail.com/login"/>'
            '<input type="text" name="username"/>'
            '<input type="password" name="password"/>'
            '</form></body></html>'
        )

        class SsoClient(_FakeClient):
            def get(self, url, **kwargs):
                if 'www.mail.com' in url or url.rstrip('/').endswith('mail.com'):
                    return _FakeResp(home, url='https://www.mail.com/')
                return super().get(url, **kwargs)

            def post(self, url, **kwargs):
                self.posts.append({'url': url, 'data': kwargs.get('data') or {}})
                return _FakeResp('<html>logout</html>', url='https://www.mail.com/logout/?ls=wd')

        ok, err, _ = provider.full_login(SsoClient({}), 'vita@mail.com', 'wrong', site='mail.com')
        self.assertFalse(ok)
        self.assertEqual(err, '账号或密码错误')

    def test_fetch_message_list(self):
        provider = MailcomCookieProvider()
        msgs = provider.fetch_message_list(
            _FakeClient({'/mail': _load('folder_list_ok.html')}),
            limit=10,
            site='mail.com',
        )
        self.assertEqual(len(msgs), 2)

    def test_extract_verification_code_helper(self):
        self.assertEqual(
            extract_verification_code(subject='Your verification code is 123456'),
            '123456',
        )

    def test_mailcom_ui_date_normalizes_to_iso(self):
        parsed = parse_mail_datetime('Monday, August 24, 2026 at 5:07 PM')
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.year, 2026)
        self.assertEqual(parsed.month, 8)
        self.assertEqual(parsed.day, 24)
        self.assertEqual(parsed.hour, 17)
        self.assertEqual(parsed.minute, 7)
        self.assertEqual(
            normalize_mail_date_for_display('Monday, August 24, 2026 at 5:07 PM'),
            '2026-08-24T17:07:00',
        )

        item = _message_to_list_item(
            Message(id='1', subject='Hello', date='Monday, August 24, 2026 at 5:07 PM'),
            'inbox',
        )
        self.assertEqual(item['date'], '2026-08-24T17:07:00')


class MailcomIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True

    def test_provider_and_domain_mapping(self):
        self.assertTrue(is_mailcom_domain('name@mail.com'))
        self.assertTrue(is_mailcom_domain('name@email.com'))
        self.assertFalse(is_mailcom_domain('name@gmail.com'))
        self.assertEqual(web_outlook_app.infer_provider_from_email('name@mail.com'), 'mailcom')
        self.assertEqual(web_outlook_app.infer_provider_from_email('name@usa.com'), 'mailcom')
        meta = web_outlook_app.get_provider_meta('mailcom', 'name@mail.com')
        self.assertEqual(meta['key'], 'mailcom')
        self.assertEqual(meta['account_type'], 'imap')
        self.assertEqual(meta['imap_host'], 'imap.mail.com')
        custom = web_outlook_app.get_provider_meta('custom', 'name@mail.com')
        self.assertEqual(custom['key'], 'custom')
        self.assertTrue(is_mailcom_account({'provider': 'mailcom'}))
        self.assertFalse(is_mailcom_account({'provider': 'gmail'}))

    def test_import_mailcom_account_string(self):
        for provider in ('mailcom', 'auto'):
            parsed = web_outlook_app.parse_account_import(
                'name@mail.com----hunter2',
                provider=provider,
            )
            self.assertIsNotNone(parsed, provider)
            self.assertEqual(parsed['provider'], 'mailcom')
            self.assertEqual(parsed['account_type'], 'imap')
            self.assertEqual(parsed['imap_password'], 'hunter2')
            self.assertEqual(parsed['imap_host'], 'imap.mail.com')

    def test_session_roundtrip(self):
        dumped = dump_mailcom_session(
            [{'name': 'sid', 'value': 'abc'}],
            {'folder_url': 'https://lightmailer.mail.com/folderlist'},
        )
        loaded = load_mailcom_session({'mailcom_session': dumped})
        self.assertEqual(loaded['cookies'][0]['name'], 'sid')
        self.assertIn('folder_url', loaded['session_meta'])

    def test_unsupported_actions(self):
        result = mailcom_unsupported_action('delete')
        self.assertFalse(result['success'])
        self.assertEqual(result['error_code'], 'MAILCOM_UNSUPPORTED')

    def test_fetch_account_folder_uses_mailcom_path(self):
        account = {
            'id': 1,
            'email': 'name@mail.com',
            'provider': 'mailcom',
            'account_type': 'imap',
            'imap_password': 'secret',
            'mailcom_session': '',
        }

        def fake_fetch(acc, folder, skip, top, proxy_url=''):
            self.assertEqual(acc['email'], 'name@mail.com')
            self.assertEqual(folder, 'inbox')
            return {
                'success': True,
                'emails': [{
                    'id': 'msg-001',
                    'subject': 'Hello',
                    'from': 'a@example.com',
                    'to': '',
                    'date': 'Mon, 01 Aug 2026 10:00:00 +0000',
                    'is_read': False,
                    'has_attachments': False,
                    'body_preview': 'Hello',
                    'id_mode': 'mailcom',
                }],
                'method': MAILCOM_METHOD,
                'has_more': False,
                'request_method': 'mailcom',
            }

        with patch.object(web_outlook_app, 'get_emails_mailcom', side_effect=fake_fetch), \
             patch.object(web_outlook_app, 'get_emails_imap_generic') as imap_mock:
            result = web_outlook_app.fetch_account_folder_emails(account, 'inbox', 0, 20)
        self.assertTrue(result['success'])
        self.assertEqual(result['request_method'], 'mailcom')
        self.assertEqual(result['emails'][0]['id'], 'msg-001')
        imap_mock.assert_not_called()

    def test_persist_mailcom_session_column(self):
        with self.app.app_context():
            web_outlook_app.init_db()
            self.assertTrue(web_outlook_app.add_account(
                'persist@mail.com',
                '',
                '',
                '',
                account_type='imap',
                provider='mailcom',
                imap_host='imap.mail.com',
                imap_password='secret',
            ))
            account = web_outlook_app.get_account_by_email('persist@mail.com')
            from outlook_web.mailcom_service import persist_mailcom_session
            persist_mailcom_session(
                account,
                [{'name': 'sid', 'value': 'rolling'}],
                {'last_probe': 'restore_ok'},
            )
            reloaded = web_outlook_app.get_account_by_email('persist@mail.com')
            session = load_mailcom_session(reloaded)
            self.assertEqual(session['cookies'][0]['value'], 'rolling')
            self.assertEqual(session['session_meta']['last_probe'], 'restore_ok')

    def test_detail_uses_mailcom_path(self):
        account = {
            'id': 2,
            'email': 'name@mail.com',
            'provider': 'mailcom',
            'account_type': 'imap',
            'imap_password': 'secret',
        }
        with patch.object(web_outlook_app, 'get_email_detail_mailcom', return_value={
            'success': True,
            'email': {'id': 'msg-001', 'subject': 'Hello', 'body': 'Hi', 'body_type': 'text'},
        }), patch.object(web_outlook_app, 'build_retained_detail_success_response', side_effect=lambda *args, **kwargs: {
            'success': True,
            'email': args[3],
        }), patch.object(web_outlook_app, 'get_email_detail_imap_generic_result') as imap_mock:
            result = web_outlook_app.fetch_email_detail_for_account(account, 'msg-001', folder='inbox')
        self.assertTrue(result['success'])
        self.assertEqual(result['email']['id'], 'msg-001')
        imap_mock.assert_not_called()


if __name__ == '__main__':
    unittest.main()
