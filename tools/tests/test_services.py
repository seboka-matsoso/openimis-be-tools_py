from django.test import TestCase
from unittest import mock

from tools.services import upload_claim, InvalidXMLError
from xml.etree import ElementTree


class UploadClaimsTestCase(TestCase):
    def test_upload_claims_unknown_hf(self):
        mock_user = mock.Mock(is_anonymous=False)
        mock_user.has_perm = mock.MagicMock(return_value=True)
        with self.assertRaises(InvalidXMLError) as cm:
            upload_claim(
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
