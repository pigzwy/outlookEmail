"""Verification-code parser (adapted from OpenMail)."""

import importlib
import os
import tempfile
import unittest
from email.message import EmailMessage
from unittest.mock import Mock, patch

from outlook_web.verification_code import extract_verification_code

os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    os.environ['DATABASE_PATH'] = os.path.join(
        tempfile.mkdtemp(prefix='outlookEmail-otp-tests-'),
        'test.db',
    )

web_outlook_app = importlib.import_module('web_outlook_app')


class VerificationCodeTests(unittest.TestCase):
    def test_extract_near_chinese_keyword(self):
        self.assertEqual(
            extract_verification_code(subject='您的验证码是 482913，请在5分钟内使用'),
            '482913',
        )

    def test_extract_near_english_code_keyword(self):
        self.assertEqual(
            extract_verification_code(
                subject='Your verification code',
                body_text='Use code 918273 to sign in.',
            ),
            '918273',
        )

    def test_alphanumeric_confirmation_code(self):
        self.assertEqual(
            extract_verification_code(subject='SpaceXAI confirmation code: 8IX-FGG'),
            '8IX-FGG',
        )

    def test_reject_year_and_promo(self):
        self.assertIsNone(
            extract_verification_code(
                subject='New: Lower GPT-5.6 pricing',
                body_text='© 2026 OpenAI. All Rights Reserved. Update your code preferences.',
            )
        )
        self.assertIsNone(
            extract_verification_code(body_text='Your postal code is 94107.')
        )
        self.assertIsNone(
            extract_verification_code(subject='Weekly digest', body_text='Use discount code 882211 at checkout.')
        )

    def test_chatgpt_login_code(self):
        self.assertEqual(
            extract_verification_code(
                subject='Your temporary ChatGPT login code',
                body_text='Your ChatGPT code is 980220. It expires in 10 minutes.',
            ),
            '980220',
        )

    def test_preview_is_enough(self):
        self.assertEqual(
            extract_verification_code(
                subject='Sign in',
                body_preview='Your verification code is 445566',
            ),
            '445566',
        )


class EmailListCodeAnnotationTests(unittest.TestCase):
    def test_normalize_list_item_extracts_code(self):
        row = web_outlook_app.normalize_email_list_item({
            'id': '1',
            'subject': 'Your verification code',
            'from': 'a@b.com',
            'body_preview': 'Use code 918273 to sign in.',
        }, 'inbox')
        self.assertEqual(row['verification_code'], '918273')


class EmailDetailCodeAnnotationTests(unittest.TestCase):
    def test_header_only_list_can_defer_body_code_until_detail_is_opened(self):
        message = EmailMessage()
        message['Subject'] = 'Your verification code'
        message['From'] = 'sender@example.com'
        message.set_content('Your verification code is 918273.')
        listed = web_outlook_app.normalize_email_list_item({
            'id': '42', 'subject': message['Subject'], 'body_preview': '',
        }, 'inbox')
        self.assertEqual(listed['verification_code'], '')
        detail = web_outlook_app.build_email_detail_from_message(message, '42')
        with patch.object(web_outlook_app, 'is_normal_mail_local_retention_enabled', return_value=False):
            response = web_outlook_app.build_retained_detail_success_response(
                {'id': 1}, 'inbox', '42', detail, 'imap', 'imap', 'uid',
            )
        self.assertTrue(response['success'])
        self.assertEqual(response['email']['verification_code'], '918273')

    def test_detail_code_supports_html_and_preserves_provider_annotation(self):
        detail = {'subject': 'Sign in', 'body': '<p>Your verification code is <b>445566</b>.</p>', 'body_type': 'html'}
        self.assertEqual(web_outlook_app.annotate_email_verification_code(detail)['verification_code'], '445566')
        detail['verification_code'] = '8IX-FGG'
        self.assertEqual(web_outlook_app.annotate_email_verification_code(detail)['verification_code'], '8IX-FGG')

    def test_retained_detail_extracts_code_without_remote_fetch(self):
        row = {
            'provider_message_id': '42', 'subject': 'Your verification code',
            'sender': 'sender@example.com', 'recipients': 'receiver@example.com',
            'recipient_evidence': '[]', 'cc': '', 'received_at': '',
            'body': 'Your verification code is 918273.', 'body_type': 'text',
            'attachments_json': '[]', 'has_attachments': 0,
            'folder': 'inbox', 'id_mode': 'uid',
        }
        database = Mock()
        database.execute.return_value.fetchone.return_value = row
        with patch.object(web_outlook_app, 'get_db', return_value=database), patch.object(
            web_outlook_app, 'get_email_detail_imap_generic_result',
        ) as remote:
            response = web_outlook_app.fetch_retained_normal_mail_detail({'id': 1}, 'inbox', '42', 'uid')
        self.assertEqual(response['source'], 'local_retention')
        self.assertEqual(response['email']['verification_code'], '918273')
        remote.assert_not_called()


class ImapDomainHintTests(unittest.TestCase):
    def test_openmail_domain_presets(self):
        self.assertEqual(web_outlook_app.infer_provider_from_email('user@icloud.com'), 'icloud')
        self.assertEqual(web_outlook_app.infer_provider_from_email('user@gmx.de'), 'gmx')
        self.assertEqual(web_outlook_app.infer_provider_from_email('user@zoho.com'), 'zoho')
        self.assertEqual(web_outlook_app.infer_provider_from_email('user@yeah.net'), 'yeah')
        self.assertEqual(web_outlook_app.infer_provider_from_email('user@ymail.com'), 'yahoo')


if __name__ == '__main__':
    unittest.main()
