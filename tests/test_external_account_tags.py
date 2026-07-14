import importlib
import os
import sys
import tempfile
import unittest


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _temp_dir = tempfile.mkdtemp(prefix='outlookEmail-external-tags-tests-')
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

web_outlook_app = importlib.import_module('web_outlook_app')


class ExternalAccountTagsTests(unittest.TestCase):
    API_KEY = 'external-tags-test-key'

    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            web_outlook_app.init_db()
            db = web_outlook_app.get_db()
            db.execute('DELETE FROM account_tags')
            db.execute('DELETE FROM tags')
            db.execute('DELETE FROM accounts')
            db.commit()
            web_outlook_app.set_setting('external_api_key', self.API_KEY)

    def test_external_api_manages_account_tags(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            account = db.execute(
                '''
                INSERT INTO accounts (
                    email, password, client_id, refresh_token,
                    group_id, remark, status, account_type, provider,
                    imap_host, imap_port, imap_password, forward_enabled
                )
                VALUES (?, '', '', '', 1, '', 'active', 'outlook', 'outlook', '', 993, '', 0)
                ''',
                ('external-tags@example.com',),
            )
            tag = db.execute(
                'INSERT INTO tags (name, color) VALUES (?, ?)',
                ('external', '#0078d4'),
            )
            db.commit()
            account_id = int(account.lastrowid)
            tag_id = int(tag.lastrowid)

        headers = {'X-API-Key': self.API_KEY}
        add_response = self.client.post(
            '/api/external/accounts/tags',
            headers=headers,
            json={'account_ids': [account_id], 'tag_id': tag_id, 'action': 'add'},
        )
        self.assertEqual(add_response.status_code, 200)
        self.assertEqual(add_response.get_json()['message'], '成功处理 1 个账号')

        remove_response = self.client.post(
            '/api/external/accounts/tags',
            headers=headers,
            json={'account_ids': [account_id], 'tag_id': tag_id, 'action': 'remove'},
        )
        self.assertEqual(remove_response.status_code, 200)
        self.assertEqual(remove_response.get_json()['message'], '成功处理 1 个账号')

        with self.app.app_context():
            count = web_outlook_app.get_db().execute(
                'SELECT COUNT(*) FROM account_tags WHERE account_id = ? AND tag_id = ?',
                (account_id, tag_id),
            ).fetchone()[0]
        self.assertEqual(count, 0)


if __name__ == '__main__':
    unittest.main()
