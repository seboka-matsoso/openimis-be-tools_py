from django.test import TestCase
from unittest import mock
from .services import *
from core.test_helpers import create_test_interactive_user
from xml.etree import ElementTree


class UploadClaimsTestCase(TestCase):
    def test_upload_claims_unknown_hf(self):
        with mock.patch("django.db.backends.utils.CursorWrapper") as mock_cursor:
            mock_cursor.return_value.__enter__.return_value.fetchone.return_value = [-1]
            mock_user = mock.Mock(is_anonymous=False)
            mock_user.has_perm = mock.MagicMock(return_value=True)
            with self.assertRaises(InvalidXMLError) as cm:
                upload_claims(
                    mock_user,
                    ElementTree.fromstring(
                        """
                    <root>
                        <Claim>
                            <Details>
                                <HFCode>WRONG</HFCode>
                            </Details>
                        </Claim>
                    </root>
                """
                    ),
                )
            self.assertEqual(
                "User cannot upload claims for health facility WRONG",
                str(cm.exception),
            )
