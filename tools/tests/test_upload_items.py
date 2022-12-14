from unittest.mock import patch
from tempfile import TemporaryFile

from core.test_helpers import create_test_interactive_user
from django.test import TestCase

from medical.models import Item
from medical.test_helpers import create_test_item
from tools.services import load_items_xml, UploadResult, upload_items, parse_optional_item_fields
from tools.constants import STRATEGY_INSERT, STRATEGY_UPDATE, STRATEGY_INSERT_UPDATE, STRATEGY_INSERT_UPDATE_DELETE
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
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                    <ItemQuantity/>
                    <ItemPackage/>
                    <ItemFrequency/>
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
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                    <ItemPackage>Nice package</ItemPackage>
                    <ItemQuantity/>
                    <ItemFrequency>88</ItemFrequency>
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
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                    <ItemPackage/>
                    <ItemQuantity>1.25</ItemQuantity>
                    <ItemFrequency>7</ItemFrequency>
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
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
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
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
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
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                </Item>
                <Item>
                    <ItemCode>{code_2}</ItemCode>
                    <ItemName>Error in price - currency symbol at the end</ItemName>
                    <ItemType>D</ItemType>
                    <ItemPrice>123.4€</ItemPrice>
                    <ItemCareType>O</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                </Item>
                <Item>
                    <ItemCode>{code_3}</ItemCode>
                    <ItemName>Error in price - currency symbol as decimal separator</ItemName>
                    <ItemType>D</ItemType>
                    <ItemPrice>123€4</ItemPrice>
                    <ItemCareType>O</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                </Item>
                <Item>
                    <ItemCode>{code_ok}</ItemCode>
                    <ItemName>Proper price, with a '.' for decimal separator and without currency symbol</ItemName>
                    <ItemType>D</ItemType>
                    <ItemPrice>123.45</ItemPrice>
                    <ItemCareType>O</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
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

            self.assertIn("price is invalid", errors[0])
            self.assertIn(code_1, errors[0])

            self.assertIn("price is invalid", errors[1])
            self.assertIn(code_2, errors[1])

            self.assertIn("price is invalid", errors[2])
            self.assertIn(code_3, errors[2])

    def test_load_items_xml_error_repeated_code(self):
        code_1 = "CODE_1"
        code_2 = "CODE_2"
        xml = f"""
            <Items>
                <Item>
                    <ItemCode>{code_1}</ItemCode>
                    <ItemName>Item 1</ItemName>
                    <ItemType>M</ItemType>
                    <ItemPrice>0.45</ItemPrice>
                    <ItemCareType>I</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                </Item>
                <Item>
                    <ItemCode>{code_1}</ItemCode>
                    <ItemName>Item 1 w/ different values and same code</ItemName>
                    <ItemType>D</ItemType>
                    <ItemPrice>2.45</ItemPrice>
                    <ItemCareType>O</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                </Item>
                <Item>
                    <ItemCode>{code_2}</ItemCode>
                    <ItemName>Item 2</ItemName>
                    <ItemType>D</ItemType>
                    <ItemPrice>1000</ItemPrice>
                    <ItemCareType>B</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                </Item>
            </Items>
        """.encode("utf8")
        with TemporaryFile() as tf:
            tf.write(xml)
            tf.seek(0)
            et = ElementTree.parse(tf)

            raw_items, errors = load_items_xml(et)

            self.assertTrue(raw_items)
            self.assertEqual(len(raw_items), 2)
            self.assertEqual(raw_items[0]["code"], code_1)
            self.assertEqual(raw_items[1]["code"], code_2)

            self.assertTrue(errors)
            self.assertEqual(len(errors), 1)
            self.assertIn("exists multiple times", errors[0])
            self.assertIn(code_1, errors[0])

    def test_load_items_xml_error_code_too_small(self):
        xml = b"""
            <Items>
                <Item>
                    <ItemCode> </ItemCode>
                    <ItemName>Item code is a single space that will be trimmed</ItemName>
                    <ItemType>D</ItemType>
                    <ItemPrice>1234</ItemPrice>
                    <ItemCareType>O</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
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
            self.assertIn("code is invalid", errors[0])
            self.assertIn("''", errors[0])

    def test_load_items_xml_error_code_too_long(self):
        long_boi = "THIS_CODE_IS_REALLY_LONG_WHY?"
        xml = f"""
            <Items>
                <Item>
                    <ItemCode>{long_boi}</ItemCode>
                    <ItemName>Item code is a single space that will be trimmed</ItemName>
                    <ItemType>D</ItemType>
                    <ItemPrice>1234</ItemPrice>
                    <ItemCareType>O</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                </Item>
            </Items>
        """.encode("utf8")
        with TemporaryFile() as tf:
            tf.write(xml)
            tf.seek(0)
            et = ElementTree.parse(tf)

            raw_items, errors = load_items_xml(et)

            self.assertFalse(raw_items)
            self.assertTrue(errors)
            self.assertEqual(len(errors), 1)
            self.assertIn("code is invalid", errors[0])
            self.assertIn(long_boi, errors[0])

    def test_load_items_xml_error_name_too_small(self):
        xml = b"""
            <Items>
                <Item>
                    <ItemCode>CODE</ItemCode>
                    <ItemName> </ItemName>
                    <ItemType>D</ItemType>
                    <ItemPrice>1234</ItemPrice>
                    <ItemCareType>O</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
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
            self.assertIn("name is invalid", errors[0])
            self.assertIn("''", errors[0])

    def test_load_items_xml_error_name_too_long(self):
        long_boi = "this name is really long, why? Why would anyone prepare a medical item with a name so long, it doesn't make any sense..."
        xml = f"""
            <Items>
                <Item>
                    <ItemCode>CODE</ItemCode>
                    <ItemName>{long_boi}</ItemName>
                    <ItemType>D</ItemType>
                    <ItemPrice>1234</ItemPrice>
                    <ItemCareType>O</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                </Item>
            </Items>
        """.encode("utf8")
        with TemporaryFile() as tf:
            tf.write(xml)
            tf.seek(0)
            et = ElementTree.parse(tf)

            raw_items, errors = load_items_xml(et)

            self.assertFalse(raw_items)
            self.assertTrue(errors)
            self.assertEqual(len(errors), 1)
            self.assertIn("name is invalid", errors[0])
            self.assertIn(long_boi, errors[0])

    def test_load_items_xml_error_unknown_type(self):
        unknown_type = "O"
        xml = f"""
            <Items>
                <Item>
                    <ItemCode>M_MAJ</ItemCode>
                    <ItemName>Item of type M in capital letter</ItemName>
                    <ItemType>M</ItemType>
                    <ItemPrice>9.87</ItemPrice>
                    <ItemCareType>I</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                    <ItemPackage/>
                    <ItemQuantity>1.25</ItemQuantity>
                    <ItemFrequency>7</ItemFrequency>
                </Item>
                <Item>
                    <ItemCode>M_MIN</ItemCode>
                    <ItemName>Item of type M in small letter</ItemName>
                    <ItemType>m</ItemType>
                    <ItemPrice>8.76</ItemPrice>
                    <ItemCareType>I</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                    <ItemPackage/>
                    <ItemQuantity>1.25</ItemQuantity>
                    <ItemFrequency>7</ItemFrequency>
                </Item>
                <Item>
                    <ItemCode>D_MAJ</ItemCode>
                    <ItemName>Item of type D in capital letter</ItemName>
                    <ItemType>D</ItemType>
                    <ItemPrice>7.65</ItemPrice>
                    <ItemCareType>I</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                    <ItemPackage/>
                    <ItemQuantity>1.25</ItemQuantity>
                    <ItemFrequency>7</ItemFrequency>
                </Item>
                <Item>
                    <ItemCode>D_MIN</ItemCode>
                    <ItemName>Item of type D in small letter</ItemName>
                    <ItemType>d</ItemType>
                    <ItemPrice>6.54</ItemPrice>
                    <ItemCareType>I</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                    <ItemPackage/>
                    <ItemQuantity>1.25</ItemQuantity>
                    <ItemFrequency>7</ItemFrequency>
                </Item>
                <Item>
                    <ItemCode>O_MIN</ItemCode>
                    <ItemName>Item of unknown type</ItemName>
                    <ItemType>{unknown_type}</ItemType>
                    <ItemPrice>5.43</ItemPrice>
                    <ItemCareType>B</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                    <ItemPackage/>
                    <ItemQuantity>1.25</ItemQuantity>
                    <ItemFrequency>7</ItemFrequency>
                </Item>
            </Items>
        """.encode("utf8")
        with TemporaryFile() as tf:
            tf.write(xml)
            tf.seek(0)
            et = ElementTree.parse(tf)

            raw_items, errors = load_items_xml(et)

            self.assertTrue(raw_items)
            self.assertEqual(len(raw_items), 4)

            self.assertTrue(errors)
            self.assertEqual(len(errors), 1)
            self.assertIn("type is invalid", errors[0])
            self.assertIn(unknown_type, errors[0])

    def test_load_items_xml_error_unknown_care_type(self):
        unknown_care_type = "K"
        xml = f"""
            <Items>
                <Item>
                    <ItemCode>I_MAJ</ItemCode>
                    <ItemName>Item of care_type I in capital letter</ItemName>
                    <ItemType>M</ItemType>
                    <ItemPrice>9.87</ItemPrice>
                    <ItemCareType>I</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                </Item>
                <Item>
                    <ItemCode>I_MIN</ItemCode>
                    <ItemName>Item of care_type I in small letter</ItemName>
                    <ItemType>D</ItemType>
                    <ItemPrice>8.76</ItemPrice>
                    <ItemCareType>i</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                </Item>
                <Item>
                    <ItemCode>O_MAJ</ItemCode>
                    <ItemName>Item of care_type O in capital letter</ItemName>
                    <ItemType>D</ItemType>
                    <ItemPrice>7.65</ItemPrice>
                    <ItemCareType>O</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                </Item>
                <Item>
                    <ItemCode>O_MIN</ItemCode>
                    <ItemName>Item of care_type O in small letter</ItemName>
                    <ItemType>m</ItemType>
                    <ItemPrice>6.54</ItemPrice>
                    <ItemCareType>o</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                </Item>
                <Item>
                    <ItemCode>B_MAJ</ItemCode>
                    <ItemName>Item of care_type B in capital letter</ItemName>
                    <ItemType>D</ItemType>
                    <ItemPrice>5.43</ItemPrice>
                    <ItemCareType>B</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                </Item>
                <Item>
                    <ItemCode>B_MIN</ItemCode>
                    <ItemName>Item of care_type B in small letter</ItemName>
                    <ItemType>m</ItemType>
                    <ItemPrice>4.32</ItemPrice>
                    <ItemCareType>b</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                </Item>
                <Item>
                    <ItemCode>K_MAJ</ItemCode>
                    <ItemName>Item of unknown care_type</ItemName>
                    <ItemType>M</ItemType>
                    <ItemPrice>3.21</ItemPrice>
                    <ItemCareType>{unknown_care_type}</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                </Item>
            </Items>
        """.encode("utf8")
        with TemporaryFile() as tf:
            tf.write(xml)
            tf.seek(0)
            et = ElementTree.parse(tf)

            raw_items, errors = load_items_xml(et)

            self.assertTrue(raw_items)
            self.assertEqual(len(raw_items), 6)

            self.assertTrue(errors)
            self.assertEqual(len(errors), 1)
            self.assertIn("care type is invalid", errors[0])
            self.assertIn(unknown_care_type, errors[0])

    def test_load_items_xml_mixed_errors_and_success(self):
        code_ok_1 = "CODE_1"
        code_ok_2 = "CODE_2"
        code_ok_3 = "CODE_3"

        long_name = "this name is really long, why? Why would anyone prepare a medical item with a name so long, it doesn't make any sense..."
        unknown_care_type = "K"
        xml = f"""
            <Items>
                <Item>
                    <ItemCode>CODE</ItemCode>
                    <ItemName>{long_name}</ItemName>
                    <ItemType>D</ItemType>
                    <ItemPrice>1234</ItemPrice>
                    <ItemCareType>O</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                </Item>
                <Item>
                    <ItemCode>{code_ok_1}</ItemCode>
                    <ItemName>Valid item 1 - no error</ItemName>
                    <ItemType>M</ItemType>
                    <ItemPrice>9.87</ItemPrice>
                    <ItemCareType>I</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                </Item>
                <Item>
                    <ItemCode>K_MAJ</ItemCode>
                    <ItemName>Item of unknown care_type</ItemName>
                    <ItemType>M</ItemType>
                    <ItemPrice>3.21</ItemPrice>
                    <ItemCareType>{unknown_care_type}</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                </Item>
                <Item>
                    <ItemCode>{code_ok_2}</ItemCode>
                    <ItemName>Valid item 2 - no error</ItemName>
                    <ItemType>d</ItemType>
                    <ItemPrice>555.55</ItemPrice>
                    <ItemCareType>b</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                </Item>
                <Item>
                    <ItemCode>{code_ok_3}</ItemCode>
                    <ItemName>Valid item 3 - no error</ItemName>
                    <ItemType>D</ItemType>
                    <ItemPrice>489.54</ItemPrice>
                    <ItemCareType>O</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                </Item>
                <Item>
                    <ItemName>Item without code</ItemName>
                    <ItemType>D</ItemType>
                    <ItemPrice>3700.88</ItemPrice>
                    <ItemCareType>o</ItemCareType>
                    <ItemMaleCategory>1</ItemMaleCategory>
                    <ItemFemaleCategory>1</ItemFemaleCategory>
                    <ItemAdultCategory>1</ItemAdultCategory>
                    <ItemMinorCategory>1</ItemMinorCategory>
                </Item>
            </Items>
        """.encode("utf8")
        with TemporaryFile() as tf:
            tf.write(xml)
            tf.seek(0)
            et = ElementTree.parse(tf)

            raw_items, errors = load_items_xml(et)

            self.assertTrue(raw_items)
            self.assertEqual(len(raw_items), 3)
            self.assertIn(code_ok_1, raw_items[0]["code"])
            self.assertIn(code_ok_2, raw_items[1]["code"])
            self.assertIn(code_ok_3, raw_items[2]["code"])

            self.assertTrue(errors)
            self.assertEqual(len(errors), 3)
            self.assertIn("name is invalid", errors[0])
            self.assertIn(long_name, errors[0])
            self.assertIn("care type is invalid", errors[1])
            self.assertIn(unknown_care_type, errors[1])
            self.assertIn("Item is missing one of", errors[2])


class UploadItemsParseOptionalFieldsTestCase(TestCase):

    def test_parse_optional_item_fields_all_empty(self):
        xml = f"""
            <Item>
                <ItemQuantity/>
                <ItemPackage/>
                <ItemFrequency/>
            </Item>
        """.encode("utf8")
        with TemporaryFile() as tf:
            tf.write(xml)
            tf.seek(0)
            et = ElementTree.parse(tf)
            root = et.getroot()

            optional_fields, error = parse_optional_item_fields(root, "EMPTY")

            self.assertFalse(optional_fields)
            self.assertFalse(error)

    def test_parse_optional_item_fields_all_filled(self):
        xml = f"""
            <Item>
                <ItemPackage>1000 TABLETS</ItemPackage>
                <ItemQuantity>42.00</ItemQuantity>
                <ItemFrequency>5</ItemFrequency>
            </Item>
        """.encode("utf8")
        with TemporaryFile() as tf:
            tf.write(xml)
            tf.seek(0)
            et = ElementTree.parse(tf)
            root = et.getroot()

            optional_fields, error = parse_optional_item_fields(root, "FILLED")

            self.assertTrue(optional_fields)
            self.assertEqual(len(optional_fields), 3)
            self.assertIn("frequency", optional_fields)
            self.assertIn("quantity", optional_fields)
            self.assertIn("package", optional_fields)
            self.assertFalse(error)

    def test_parse_optional_item_fields_filled_and_empty_frq(self):
        xml = f"""
            <Item>
                <ItemPackage/>
                <ItemQuantity/>
                <ItemFrequency>5</ItemFrequency>
            </Item>
        """.encode("utf8")
        with TemporaryFile() as tf:
            tf.write(xml)
            tf.seek(0)
            et = ElementTree.parse(tf)
            root = et.getroot()

            optional_fields, error = parse_optional_item_fields(root, "1/3")

            self.assertTrue(optional_fields)
            self.assertEqual(len(optional_fields), 1)
            self.assertIn("frequency", optional_fields)
            self.assertNotIn("quantity", optional_fields)
            self.assertNotIn("package", optional_fields)
            self.assertFalse(error)

    def test_parse_optional_item_fields_filled_and_empty_qty(self):
        xml = f"""
            <Item>
                <ItemPackage/>
                <ItemQuantity>88.25</ItemQuantity>
                <ItemFrequency/>
            </Item>
        """.encode("utf8")
        with TemporaryFile() as tf:
            tf.write(xml)
            tf.seek(0)
            et = ElementTree.parse(tf)
            root = et.getroot()

            optional_fields, error = parse_optional_item_fields(root, "1/3")

            self.assertTrue(optional_fields)
            self.assertEqual(len(optional_fields), 1)
            self.assertIn("quantity", optional_fields)
            self.assertNotIn("frequency", optional_fields)
            self.assertNotIn("package", optional_fields)
            self.assertFalse(error)

    def test_parse_optional_item_fields_filled_and_empty_pkg(self):
        xml = f"""
            <Item>
                <ItemPackage>Great package</ItemPackage>
                <ItemQuantity/>
                <ItemFrequency/>
            </Item>
        """.encode("utf8")
        with TemporaryFile() as tf:
            tf.write(xml)
            tf.seek(0)
            et = ElementTree.parse(tf)
            root = et.getroot()

            optional_fields, error = parse_optional_item_fields(root, "1/3")

            self.assertTrue(optional_fields)
            self.assertEqual(len(optional_fields), 1)
            self.assertIn("package", optional_fields)
            self.assertNotIn("quantity", optional_fields)
            self.assertNotIn("frequency", optional_fields)
            self.assertFalse(error)

    def test_parse_optional_item_fields_filled_and_empty_frq_qty(self):
        xml = f"""
            <Item>
                <ItemPackage/>
                <ItemQuantity>1.25</ItemQuantity>
                <ItemFrequency>7</ItemFrequency>
            </Item>
        """.encode("utf8")
        with TemporaryFile() as tf:
            tf.write(xml)
            tf.seek(0)
            et = ElementTree.parse(tf)
            root = et.getroot()

            optional_fields, error = parse_optional_item_fields(root, "2/3")

            self.assertTrue(optional_fields)
            self.assertEqual(len(optional_fields), 2)
            self.assertIn("frequency", optional_fields)
            self.assertIn("quantity", optional_fields)
            self.assertNotIn("package", optional_fields)
            self.assertFalse(error)

    def test_parse_optional_item_fields_filled_and_empty_frq_pkg(self):
        xml = f"""
            <Item>
                <ItemPackage>Nice package</ItemPackage>
                <ItemQuantity/>
                <ItemFrequency>88</ItemFrequency>
            </Item>
        """.encode("utf8")
        with TemporaryFile() as tf:
            tf.write(xml)
            tf.seek(0)
            et = ElementTree.parse(tf)
            root = et.getroot()

            optional_fields, error = parse_optional_item_fields(root, "2/3")

            self.assertTrue(optional_fields)
            self.assertEqual(len(optional_fields), 2)
            self.assertIn("frequency", optional_fields)
            self.assertIn("package", optional_fields)
            self.assertNotIn("quantity", optional_fields)
            self.assertFalse(error)

    def test_parse_optional_item_fields_filled_and_empty_qty_pkg(self):
        xml = f"""
            <Item>
                <ItemPackage>Nice package</ItemPackage>
                <ItemQuantity>8.99</ItemQuantity>
                <ItemFrequency/>
            </Item>
        """.encode("utf8")
        with TemporaryFile() as tf:
            tf.write(xml)
            tf.seek(0)
            et = ElementTree.parse(tf)
            root = et.getroot()

            optional_fields, error = parse_optional_item_fields(root, "2/3")

            self.assertTrue(optional_fields)
            self.assertEqual(len(optional_fields), 2)
            self.assertIn("package", optional_fields)
            self.assertIn("quantity", optional_fields)
            self.assertNotIn("frequency", optional_fields)
            self.assertFalse(error)

    def test_parse_optional_item_fields_error_quantity(self):
        xml = f"""
            <Item>
                <ItemPackage>1000 TABLETS</ItemPackage>
                <ItemQuantity>42ml</ItemQuantity>
                <ItemFrequency>2</ItemFrequency>
            </Item>
        """.encode("utf8")
        with TemporaryFile() as tf:
            tf.write(xml)
            tf.seek(0)
            et = ElementTree.parse(tf)
            root = et.getroot()

            code = "ERROR_QTY"
            optional_fields, error = parse_optional_item_fields(root, code)

            self.assertFalse(optional_fields)
            self.assertTrue(error)
            self.assertIn("quantity is invalid", error)
            self.assertIn(code, error)

    def test_parse_optional_item_fields_error_frequency(self):
        xml = f"""
            <Item>
                <ItemPackage>1000 TABLETS</ItemPackage>
                <ItemFrequency>5.55</ItemFrequency>
                <ItemQuantity>42.00</ItemQuantity>
            </Item>
        """.encode("utf8")
        with TemporaryFile() as tf:
            tf.write(xml)
            tf.seek(0)
            et = ElementTree.parse(tf)
            root = et.getroot()

            code = "ERROR_FRQ"
            optional_fields, error = parse_optional_item_fields(root, code)

            self.assertNotIn("frequency", optional_fields)
            self.assertTrue(error)
            self.assertIn("frequency is invalid", error)
            self.assertIn(code, error)

    def test_parse_optional_item_fields_error_package_too_small(self):
        xml = f"""
            <Item>
                <ItemPackage> </ItemPackage>
                <ItemFrequency>1</ItemFrequency>
                <ItemQuantity>42.00</ItemQuantity>
            </Item>
        """.encode("utf8")
        with TemporaryFile() as tf:
            tf.write(xml)
            tf.seek(0)
            et = ElementTree.parse(tf)
            root = et.getroot()

            code = "ERROR_PKG"
            optional_fields, error = parse_optional_item_fields(root, code)

            self.assertNotIn("package", optional_fields)
            self.assertTrue(error)
            self.assertIn("package is invalid", error)
            self.assertIn(code, error)

    def test_parse_optional_item_fields_error_package_too_long(self):
        long_boi = "this package is really long, why? Why would anyone prepare a medical item with a packaging so long that it doesn't fit in 255 characters, it doesn't make any sense... and still, i haven't currently reached 255 characters yet, so I am trying to get there and writing anything... please enjoy if you read these tests later :)"
        xml = f"""
            <Item>
                <ItemPackage>{long_boi}</ItemPackage>
                <ItemFrequency>12</ItemFrequency>
                <ItemQuantity>2.00</ItemQuantity>
            </Item>
        """.encode("utf8")
        with TemporaryFile() as tf:
            tf.write(xml)
            tf.seek(0)
            et = ElementTree.parse(tf)
            root = et.getroot()

            code = "ERROR_PKG"
            optional_fields, error = parse_optional_item_fields(root, code)

            self.assertNotIn("package", optional_fields)
            self.assertTrue(error)
            self.assertIn("package is invalid", error)
            self.assertIn(code, error)


class UploadItemsTestCase(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin_user = create_test_interactive_user(username="testItemsAdmin")

    @patch("tools.services.load_items_xml")
    def test_upload_items_multiple_insert_dry_run(self, mock_load):
        dry_run = True
        strategy = STRATEGY_INSERT
        existing_code = "0001"
        raw_items = [
            {
                "code": "CODE_1",
                "name": "Valid item 1 - no error",
                "type": "D",
                "price": 489.54,
                "care_type": "O"
            },
            {
                "code": "CODE_2",
                "name": "Valid item 2 - no error",
                "type": "D",
                "price": 499.54,
                "care_type": "O"
            },
            {
                "code": existing_code,
                "name": "Invalid item - code already exists",
                "type": "D",
                "price": 599.54,
                "care_type": "B"
            }
        ]
        errors = []
        mock_load.return_value = raw_items, errors

        expected_errors = [
            f"{existing_code} already exists"
        ]
        expected = UploadResult(
            errors=expected_errors,
            sent=3,
            created=2,
            updated=0,
            deleted=0,
        )
        result = upload_items(self.admin_user, "xml", strategy, dry_run)

        self.assertEqual(expected, result)

    @patch("tools.services.load_items_xml")
    def test_upload_items_multiple_update_dry_run(self, mock_load):
        dry_run = True
        strategy = STRATEGY_UPDATE
        existing_code_1 = "0001"
        existing_code_2 = "0127"
        error_code = "ERROR"
        raw_items = [
            {
                "code": existing_code_1,
                "name": "Valid item 1 - no error",
                "type": "D",
                "price": 489.54,
                "care_type": "O"
            },
            {
                "code": error_code,
                "name": "Invalid item - code doesn't exists",
                "type": "D",
                "price": 599.54,
                "care_type": "B"
            },
            {
                "code": existing_code_2,
                "name": "Valid item 2 - no error",
                "type": "D",
                "price": 499.54,
                "care_type": "O"
            },
        ]
        errors = []
        mock_load.return_value = raw_items, errors

        expected_errors = [
            f"{error_code} does not exist"
        ]
        expected = UploadResult(
            errors=expected_errors,
            sent=3,
            created=0,
            updated=2,
            deleted=0,
        )
        result = upload_items(self.admin_user, "xml", strategy, dry_run)

        self.assertEqual(expected, result)

    @patch("tools.services.load_items_xml")
    def test_upload_items_multiple_insert_update_dry_run(self, mock_load):
        dry_run = True
        strategy = STRATEGY_INSERT_UPDATE
        raw_items = [
            {
                "code": "CODE_1",
                "name": "New item 1",
                "type": "D",
                "price": 489.54,
                "care_type": "O"
            },
            {
                "code": "CODE_2",
                "name": "New item 2",
                "type": "D",
                "price": 489.54,
                "care_type": "O"
            },
            {
                "code": "0001",
                "name": "Existing item 1",
                "type": "D",
                "price": 599.54,
                "care_type": "B"
            },
            {
                "code": "CODE_3",
                "name": "New item 3",
                "type": "D",
                "price": 489.54,
                "care_type": "O"
            },
            {
                "code": "0042",
                "name": "Existing item 2",
                "type": "D",
                "price": 499.54,
                "care_type": "O"
            },
        ]
        errors = []
        mock_load.return_value = raw_items, errors

        expected = UploadResult(
            errors=errors,
            sent=5,
            created=3,
            updated=2,
            deleted=0,
        )
        result = upload_items(self.admin_user, "xml", strategy, dry_run)

        self.assertEqual(expected, result)

    @patch("tools.services.load_items_xml")
    def test_upload_items_multiple_insert_update_delete_dry_run(self, mock_load):
        dry_run = True
        strategy = STRATEGY_INSERT_UPDATE_DELETE
        raw_items = [
            {
                "code": "CODE_1",
                "name": "New item 1",
                "type": "D",
                "price": 489.54,
                "care_type": "O"
            },
            {
                "code": "CODE_2",
                "name": "New item 2",
                "type": "D",
                "price": 489.54,
                "care_type": "O"
            },
            {
                "code": "0001",
                "name": "Existing item 1",
                "type": "D",
                "price": 599.54,
                "care_type": "B"
            },
            {
                "code": "CODE_3",
                "name": "New item 3",
                "type": "D",
                "price": 489.54,
                "care_type": "O"
            },
            {
                "code": "0042",
                "name": "Existing item 2",
                "type": "D",
                "price": 499.54,
                "care_type": "O"
            },
        ]
        errors = []
        mock_load.return_value = raw_items, errors

        before_total_items = Item.objects.count()
        expected_deleted = before_total_items - 2

        expected = UploadResult(
            errors=errors,
            sent=5,
            created=3,
            updated=2,
            deleted=expected_deleted,
        )
        result = upload_items(self.admin_user, "xml", strategy, dry_run)

        self.assertEqual(expected, result)


    # @patch("tools.services.load_items_xml")
    # def test_upload_items_multiple_insert(self, mock_load):
    #     dry_run = False
    #     strategy = STRATEGY_INSERT
    #     existing_code = "0001"
    #     new_code_1 = "CODE_1"
    #     new_code_2 = "CODE_2"
    #     raw_items = [
    #         {
    #             "code": new_code_1,
    #             "name": "Valid item 1 - no error",
    #             "type": "D",
    #             "price": 489.54,
    #             "care_type": "O"
    #         },
    #         {
    #             "code": new_code_2,
    #             "name": "Valid item 2 - no error",
    #             "type": "D",
    #             "price": 499.54,
    #             "care_type": "O"
    #         },
    #         {
    #             "code": existing_code,
    #             "name": "Invalid item - code already exists",
    #             "type": "D",
    #             "price": 599.54,
    #             "care_type": "B"
    #         }
    #     ]
    #     errors = []
    #     mock_load.return_value = raw_items, errors
    #
    #     expected_errors = [
    #         f"{existing_code} already exists"
    #     ]
    #     expected = UploadResult(
    #         errors=expected_errors,
    #         sent=3,
    #         created=2,
    #         updated=0,
    #         deleted=0,
    #     )
    #
    #     total_items_before = Item.objects.count()
    #
    #     result = upload_items(self.admin_user, "xml", strategy, dry_run)
    #     total_items_after = Item.objects.count()
    #
    #     self.assertEqual(expected, result)
    #     self.assertEqual(total_items_before + 2, total_items_after)
    #
    #     new_item_1 = Item.objects.get(code=new_code_1)
    #     new_item_1.delete()
    #     new_item_2 = Item.objects.get(code=new_code_2)
    #     new_item_2.delete()

        # prepare items to create (keep codes in variables)
        # do the same as insert with dry run



#     def test_upload_items_multiple_update(self):
#         self.assertTrue(True)
#
#     def test_upload_items_multiple_insert_update(self):
#         self.assertTrue(True)
#
#     def test_upload_items_multiple_insert_update_delete(self):
#         self.assertTrue(True)
#