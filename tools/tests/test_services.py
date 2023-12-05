from unittest.mock import MagicMock, patch, PropertyMock

from django.test import TestCase
from unittest import mock

from tools.services import upload_claim, InvalidXMLError, get_xml_element, get_xml_element_int,\
    InvalidXmlInt, create_officer_feedbacks_export, create_officer_renewals_export
from xml.etree import ElementTree
from core.models import Officer

class UploadClaimsTestCase(TestCase):
    def test_upload_claims_unknown_hf(self):
        with patch('tools.services.settings.ROW_SECURITY', new_callable=PropertyMock) as row_security_mock:
            row_security_mock.return_value = True
            mock_user = mock.Mock(is_anonymous=False)
            mock_user.has_perm = mock.MagicMock(return_value=True)
            mock_user.is_imis_admin = mock.MagicMock(return_value=False)
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

class GetXmlElement(TestCase):
    def test_get_xml_element(self):
        test_xml = ElementTree.fromstring(
            """
                <root>
                    <Exists>Exists</Exists>
                    <Int>123</Int>
                    <NotInt>123x</NotInt>
                    <Float>123.10</Float>
                    <NotFloat>123$10</NotFloat>
                </root>
            """
        )
        self.assertEqual("Exists", get_xml_element(test_xml, "Exists"))
        with self.assertRaises(AttributeError):
            get_xml_element(test_xml, "NotExists")
        self.assertEqual("DefaultValue", get_xml_element(test_xml, "NotExists", "DefaultValue"))

        self.assertEqual(123, get_xml_element_int(test_xml, "Int"))
        with self.assertRaises(AttributeError):
            get_xml_element_int(test_xml, "IntNotExists")
        self.assertEqual(456, get_xml_element_int(test_xml, "IntNotExists", 456))
        with self.assertRaises(InvalidXmlInt):
            get_xml_element_int(test_xml, "NotInt")
        with self.assertRaises(InvalidXmlInt):
            get_xml_element_int(test_xml, "NotInt", 456)


class register(TestCase):
    test_officer = None
    test_user = None
    @classmethod
    def setUpTestData(cls):
        cls.test_officer = Officer.objects.all().first()
        
    def test_generating_feedback(self):
        mock_user = mock.Mock(is_anonymous=False)
        mock_user.has_perm = mock.MagicMock(return_value=True)
        mock_user.is_imis_admin = mock.MagicMock(return_value=False)
        zip = create_officer_feedbacks_export(mock_user, self.test_officer)
        self.assertNotEqual(zip, None)
        
    def test_generating_renewal(self):
        mock_user = mock.Mock(is_anonymous=False)
        mock_user.has_perm = mock.MagicMock(return_value=True)
        mock_user.is_imis_admin = mock.MagicMock(return_value=False)
        zip = create_officer_renewals_export(mock_user, self.test_officer)
        self.assertNotEqual(zip, None)
        