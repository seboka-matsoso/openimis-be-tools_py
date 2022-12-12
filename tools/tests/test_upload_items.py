from unittest.mock import MagicMock, patch, PropertyMock
from tempfile import TemporaryFile
from django.test import TestCase
from unittest import mock

from tools.services import load_items_xml, InvalidXMLError
from xml.etree import ElementTree


class UploadItemsLoadXMLTestCase(TestCase):

    # def test_load_items_xml_multiple_valid(self):
    #     self.assertTrue(True)

    def test_load_items_xml_no_code(self):
        xml = b"""
            <Items>
                <Item>
                    <ItemName>Item code missing</ItemName>
                    <ItemType>D</ItemType>
                    <ItemPrice>42.00</ItemPrice>
                    <ItemCareType>B</ItemCareType>
                </Item>
            </Items>
        """
        with TemporaryFile() as tf:
            tf.write(xml)
            tf.seek(0)
            et = ElementTree.parse(tf)

            raw_items, errors = load_items_xml(et)

            self.assertFalse(raw_items)
            self.assertTrue(errors)
            self.assertEqual(len(errors), 1)
            self.assertIn("Item is missing one of", errors[0])

    def test_load_items_xml_no_name(self):
        xml = b"""
            <Items>
                <Item>
                    <ItemCode>NO_NAME</ItemCode>
                    <ItemType>M</ItemType>
                    <ItemPrice>42.42</ItemPrice>
                    <ItemCareType>I</ItemCareType>
                </Item>
            </Items>
        """
        with TemporaryFile() as tf:
            tf.write(xml)
            tf.seek(0)
            et = ElementTree.parse(tf)

            raw_items, errors = load_items_xml(et)

            self.assertFalse(raw_items)
            self.assertTrue(errors)
            self.assertEqual(len(errors), 1)
            self.assertIn("Item is missing one of", errors[0])

    def test_load_items_xml_no_item_type(self):
        xml = b"""
            <Items>
                <Item>
                    <ItemCode>NO_TYPE</ItemCode>
                    <ItemName>Item type missing</ItemName>
                    <ItemPrice>42.42</ItemPrice>
                    <ItemCareType>I</ItemCareType>
                </Item>
            </Items>
        """
        with TemporaryFile() as tf:
            tf.write(xml)
            tf.seek(0)
            et = ElementTree.parse(tf)

            raw_items, errors = load_items_xml(et)

            self.assertFalse(raw_items)
            self.assertTrue(errors)
            self.assertEqual(len(errors), 1)
            self.assertIn("Item is missing one of", errors[0])

    def test_load_items_xml_no_price(self):
        xml = b"""
            <Items>
                <Item>
                    <ItemCode>NO_PRICE</ItemCode>
                    <ItemName>Item price missing</ItemName>
                    <ItemType>D</ItemType>
                    <ItemCareType>O</ItemCareType>
                </Item>
            </Items>
        """
        with TemporaryFile() as tf:
            tf.write(xml)
            tf.seek(0)
            et = ElementTree.parse(tf)

            raw_items, errors = load_items_xml(et)

            self.assertFalse(raw_items)
            self.assertTrue(errors)
            self.assertEqual(len(errors), 1)
            self.assertIn("Item is missing one of", errors[0])

    def test_load_items_xml_no_care_type(self):
        xml = b"""
            <Items>
                <Item>
                    <ItemCode>NO_CARE_TYPE</ItemCode>
                    <ItemName>Item care_type missing</ItemName>
                    <ItemType>D</ItemType>
                    <ItemPrice>1234</ItemPrice>
                </Item>
            </Items>
        """
        with TemporaryFile() as tf:
            tf.write(xml)
            tf.seek(0)
            et = ElementTree.parse(tf)

            raw_items, errors = load_items_xml(et)

            self.assertFalse(raw_items)
            self.assertTrue(errors)
            self.assertEqual(len(errors), 1)
            self.assertIn("Item is missing one of", errors[0])

    def test_load_items_xml_various_price_errors(self):
        code_1 = "ERROR_PRICE_1"
        code_2 = "ERROR_PRICE_2"
        code_3 = "ERROR_PRICE_3"
        code_ok = "OK"
        xml = f"""
            <Items>
                <Item>
                    <ItemCode>{code_1}</ItemCode>
                    <ItemName>Error in price - wrong decimal separator</ItemName>
                    <ItemType>D</ItemType>
                    <ItemPrice>123,4</ItemPrice>
                    <ItemCareType>O</ItemCareType>
                </Item>
                <Item>
                    <ItemCode>{code_2}</ItemCode>
                    <ItemName>Error in price - currency symbol at the end</ItemName>
                    <ItemType>D</ItemType>
                    <ItemPrice>123.4€</ItemPrice>
                    <ItemCareType>O</ItemCareType>
                </Item>
                <Item>
                    <ItemCode>{code_3}</ItemCode>
                    <ItemName>Error in price - currency symbol as decimal separator</ItemName>
                    <ItemType>D</ItemType>
                    <ItemPrice>123€4</ItemPrice>
                    <ItemCareType>O</ItemCareType>
                </Item>
                <Item>
                    <ItemCode>{code_ok}</ItemCode>
                    <ItemName>Proper price, with a '.' for decimal separator and without currency symbol</ItemName>
                    <ItemType>D</ItemType>
                    <ItemPrice>123.45</ItemPrice>
                    <ItemCareType>O</ItemCareType>
                </Item>
            </Items>
        """.encode("utf8")
        with TemporaryFile() as tf:
            tf.write(xml)
            tf.seek(0)
            et = ElementTree.parse(tf)

            raw_items, errors = load_items_xml(et)

            self.assertTrue(raw_items)
            self.assertEqual(len(raw_items), 1)
            self.assertEqual(raw_items[0]["code"], code_ok)
            self.assertEqual(raw_items[0]["price"], 123.45)

            self.assertTrue(errors)
            self.assertEqual(len(errors), 3)

            self.assertIn("decimal separator", errors[0])
            self.assertIn(code_1, errors[0])

            self.assertIn("decimal separator", errors[1])
            self.assertIn(code_2, errors[1])

            self.assertIn("decimal separator", errors[2])
            self.assertIn(code_3, errors[2])
#
#     def test_load_items_xml_error_repeated_code(self):
#         self.assertTrue(False)
#
#     def test_load_items_xml_error_code_too_small(self):
#         xml = b"""
#             <Items>
#                 <Item>
#                     <ItemCode>NO_CARE_TYPE</ItemCode>
#                     <ItemName>Item care_type missing</ItemName>
#                     <ItemType>D</ItemType>
#                     <ItemPrice>1234</ItemPrice>
#                 </Item>
#             </Items>
#         """
#         with TemporaryFile() as tf:
#             tf.write(xml)
#             tf.seek(0)
#             et = ElementTree.parse(tf)
#
#             raw_items, errors = load_items_xml(et)
#
#             self.assertFalse(raw_items)
#             self.assertTrue(errors)
#             self.assertEqual(len(errors), 1)
#             self.assertIn("Item is missing one of", errors[0])
#         self.assertTrue(False)
#
#     def test_load_items_xml_error_code_too_long(self):
#         self.assertTrue(False)
#
#     def test_load_items_xml_error_name_too_small(self):
#         self.assertTrue(False)
#
#     def test_load_items_xml_error_name_too_long(self):
#         self.assertTrue(False)
#
#     def test_load_items_xml_error_unknown_type(self):
#         self.assertTrue(False)
#
#     def test_load_items_xml_error_unknown_care_type(self):
#         self.assertTrue(False)
#
    # def test_load_items_xml_multiple_errors(self):


    # def test_load_items_xml_mixed_errors_and_sucess(self):
#
#     def test_load_items_xml_type_various_casing(self):
#         self.assertTrue(True)
#
#     def test_load_items_xml_care_type_various_casing(self):
#         self.assertTrue(True)
#
#
# class UploadItemsTestCase(TestCase):
#
#     def test_upload_items_valid_multiple_insert(self):
#         self.assertTrue(True)
#
#     def test_upload_items_valid_multiple_update(self):
#         self.assertTrue(True)
#
#     def test_upload_items_valid_multiple_insert_update(self):
#         self.assertTrue(True)
#
#     def test_upload_items_valid_multiple_insert_update_delete(self):
#         self.assertTrue(True)
#
#     def test_upload_items_error_xml_file(self):
#         self.assertTrue(False)
#
#     def test_upload_items_error_insert_existing_codes(self):
#         self.assertTrue(False)
#
#     def test_upload_items_error_update_non_existing_codes(self):
#         self.assertTrue(False)
#
#     def test_upload_items_valid_multiple_insert_dry_run(self):
#         self.assertTrue(True)
#
#     def test_upload_items_valid_multiple_update_dry_run(self):
#         self.assertTrue(True)
#
#     def test_upload_items_valid_multiple_insert_update_dry_run(self):
#         self.assertTrue(True)
#
#     def test_upload_items_valid_multiple_insert_update_delete_dry_run(self):
#         self.assertTrue(True)
#
#     def test_upload_items_error_insert_existing_codes_dry_run(self):
#         self.assertTrue(False)
#
#     def test_upload_items_error_update_non_existing_codes_dry_run(self):
#         self.assertTrue(False)
