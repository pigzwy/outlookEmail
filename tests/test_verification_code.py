"""Verification-code parser (adapted from OpenMail)."""

import importlib
import os
import tempfile
import unittest

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


class ImapDomainHintTests(unittest.TestCase):
    def test_openmail_domain_presets(self):
        self.assertEqual(web_outlook_app.infer_provider_from_email('user@icloud.com'), 'icloud')
        self.assertEqual(web_outlook_app.infer_provider_from_email('user@gmx.de'), 'gmx')
        self.assertEqual(web_outlook_app.infer_provider_from_email('user@zoho.com'), 'zoho')
        self.assertEqual(web_outlook_app.infer_provider_from_email('user@yeah.net'), 'yeah')
        self.assertEqual(web_outlook_app.infer_provider_from_email('user@ymail.com'), 'yahoo')


if __name__ == '__main__':
    unittest.main()
