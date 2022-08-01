import glob
from collections import defaultdict
import functools
import decimal

import pyzipper
from django.conf import settings
from django.db import connection
from itertools import chain

from contribution.models import Premium
from core.utils import filter_validity
from django.db.models.query_utils import Q
from tools.constants import (
    STRATEGY_INSERT,
    STRATEGY_INSERT_UPDATE_DELETE,
    STRATEGY_UPDATE,
)
from tools.apps import ToolsConfig
from datetime import datetime

from insuree.models import Family, Insuree, InsureePolicy
from medical.models import Diagnosis, Item, Service
from location.models import Location, HealthFacility, UserDistrict
from medical_pricelist.models import ServicesPricelist, ItemsPricelist
from claim.models import ClaimAdmin
from policy.models import Policy
from policy.services import update_insuree_policies
from .utils import dictfetchall, sanitize_xml, dmy_format_sql
from .models import Extract
import logging
from dataclasses import dataclass
import simplejson as json
import tempfile
import pyminizip
import zipfile
import sqlite3
import os
from xml.etree import ElementTree

logger = logging.getLogger(__name__)


# It's not great to convert decimals to float but keeping it in string would
# mean updating the mobile app.
sqlite3.register_adapter(decimal.Decimal, lambda d: float(d))


class InvalidXMLError(ValueError):
    pass


@dataclass
class UploadResult:
    sent: int = 0
    created: int = 0
    updated: int = 0
    deleted: int = 0
    errors: int = 0


def load_diagnoses_xml(xml):
    result = []
    errors = []
    root = xml.getroot()

    for elm in root.findall("Diagnosis"):
        try:
            code = elm.find("DiagnosisCode").text.strip()
            name = elm.find("DiagnosisName").text.strip()
        except:
            errors.append("Diagnosis has no code or no name")
            continue

        if any([res["code"].lower() == code.lower() for res in result]):
            errors.append(f"'{code}' is already present in the list")
        elif len(code) > 6:
            errors.append(f"Code cannot be longer than 6 characters: '{code}'")
        elif len(name) > 255:
            errors.append(f"Name cannot be longer than 255 characters: '{name}'")
        else:
            result.append(dict(code=code, name=name))

    return result, errors


def upload_diagnoses(user, xml, strategy=STRATEGY_INSERT, dry_run=False):
    logger.info("Uploading diagnoses with strategy={strategy} & dry_run={dry_run}")
    try:
        raw_diagnoses, errors = load_diagnoses_xml(xml)
    except Exception as exc:
        raise InvalidXMLError("XML file is invalid.") from exc

    result = UploadResult(errors=errors)
    ids = []
    db_diagnoses = {
        x.code: x
        for x in Diagnosis.objects.filter(
            code__in=[x["code"] for x in raw_diagnoses], *filter_validity()
        )
    }
    for diagnosis in raw_diagnoses:
        logger.debug(f"Processing {diagnosis['code']}...")
        existing = db_diagnoses.get(diagnosis["code"], None)
        result.sent += 1
        ids.append(diagnosis["code"])

        if existing and strategy == STRATEGY_INSERT:
            result.errors.append(f"{existing.code} already exists")
            continue
        elif not existing and strategy == STRATEGY_UPDATE:
            result.errors.append(f"{strategy['code']} does not exist")
            continue

        if strategy == STRATEGY_INSERT:
            if not dry_run:
                Diagnosis.objects.create(audit_user_id=user.id_for_audit, **diagnosis)
            result.created += 1

        else:
            if existing:
                if not dry_run:
                    existing.save_history()
                    [setattr(existing, key, diagnosis[key]) for key in diagnosis]
                    existing.save()
                result.updated += 1
            else:
                if not dry_run:
                    existing = Diagnosis.objects.create(
                        audit_user_id=user.id_for_audit, **diagnosis
                    )
                result.created += 1

    if strategy == STRATEGY_INSERT_UPDATE_DELETE:
        # We can take all diagnosis (even the ones linked to a claim) since we only archive it.
        qs = Diagnosis.objects.filter(~Q(code__in=ids)).filter(validity_to__isnull=True)
        print(qs.all())
        result.deleted = len(qs)
        logger.info(f"Delete {result.deleted} diagnoses")
        if not dry_run:
            qs.update(
                validity_to=datetime.datetime.now(), audit_user_id=user.id_for_audit
            )

    logger.debug(f"Finished processing of diagnoses: {result}")
    return result


def load_locations_xml(xml):
    result = defaultdict(list)
    errors = []
    ids = []
    root = xml.getroot()

    regions = root.find("Regions").findall("Region")
    districts = root.find("Districts").findall("District")
    villages = root.find("Villages").findall("Village")
    municipalities = root.find("Municipalities").findall("Municipality")
    all_locations = chain(regions, districts, villages, municipalities)
    for elm in all_locations:
        data = {}
        try:
            if elm.tag == "Region":
                data["type"] = "R"
                data["code"] = elm.find("RegionCode").text.strip()
                data["name"] = elm.find("RegionName").text.strip()
            elif elm.tag == "District":
                data["type"] = "D"
                data["parent"] = elm.find("RegionCode").text.strip()
                data["code"] = elm.find("DistrictCode").text.strip()
                data["name"] = elm.find("DistrictName").text.strip()
            elif elm.tag == "Municipality":
                data["type"] = "W"
                data["parent"] = elm.find("DistrictCode").text.strip()
                data["code"] = elm.find("MunicipalityCode").text.strip()
                data["name"] = elm.find("MunicipalityName").text.strip()
            elif elm.tag == "Village":
                data["type"] = "V"
                data["parent"] = elm.find("MunicipalityCode").text.strip()
                data["code"] = elm.find("VillageCode").text.strip()
                data["name"] = elm.find("VillageName").text.strip()
                data["male_population"] = elm.find("MalePopulation").text.strip()
                data["female_population"] = elm.find("FemalePopulation").text.strip()
                data["other_population"] = elm.find("OtherPopulation").text.strip()
                data["families"] = elm.find("Families").text.strip()
        except ValueError as exc:
            logger.exception(exc)
            errors.append(f"A field is missing for {elm}")
            continue
        if not data["code"]:
            errors.append("Location has no code")
        if data["code"].lower() in ids:
            errors.append(f"Code '{data['code']}' already exists in the list")
            continue
        else:
            ids.append(data["code"].lower())
            result[data["type"]].append(data)

    return result, errors


@functools.lru_cache(None)
def get_parent_location(code):
    return Location.objects.filter(code=code, *filter_validity()).first()


def __chunk_list(l, size=1000):
    return (l[index:index + size] for index in range(0, len(l), size))


def upload_locations(user, xml, strategy=STRATEGY_INSERT, dry_run=False):
    logger.info(f"Uploading locations with strategy={strategy} & dry_run={dry_run}")
    try:
        locations, errors = load_locations_xml(xml)
    except Exception as exc:
        raise InvalidXMLError("XML file is invalid.") from exc
    result = UploadResult(errors=errors)

    ids = [x["code"] for x in chain.from_iterable(locations.values())]
    existing_locations = {}
    for ids_chunk in __chunk_list(ids):
        existing_locations.update({
            loc.code: loc for loc in Location.objects.filter(code__in=ids_chunk, *filter_validity())
        })

    get_parent_location.cache_clear()

    for locations in locations.values():
        for loc in locations:
            result.sent += 1
            existing = existing_locations.get(loc["code"], None)

            if existing and strategy == STRATEGY_INSERT:
                result.errors.append(f"{existing.code} already exists")
                continue
            elif not existing and strategy == STRATEGY_UPDATE:
                result.errors.append(f"{strategy['code']} does not exist")
                continue

            if loc.get("parent", None):
                parent_code = loc["parent"]
                del loc["parent"]

                parent = get_parent_location(parent_code)
                if not parent:
                    result.errors.append(f"Parent {parent_code} does not exist")
                    continue
                loc["parent"] = parent

            if strategy == STRATEGY_INSERT or not existing:
                if not dry_run:
                    location = Location.objects.create(audit_user_id=user.id_for_audit, **loc)
                    if location.type == 'D':
                        UserDistrict.objects.get_or_create(
                            user=user.i_user,
                            location=location,
                            audit_user_id=user.id_for_audit,
                        )
                result.created += 1
            elif existing:
                if not dry_run:
                    existing.save_history()
                    [setattr(existing, key, loc[key]) for key in loc]
                    existing.save()
                result.updated += 1

    return result


HF_FIELDS_MAP = {
    "LegalForm": "legal_form_id",
    "Level": "level",
    "SubLevel": "sub_level_id",
    "Code": "code",
    "Name": "name",
    "Address": "address",
    "DistrictCode": "district_code",
    "Phone": "phone",
    "Fax": "fax",
    "Email": "email",
    "CareType": "care_type",
    "AccountCode": "acc_code",
    "ItemPriceListName": "items_pricelist_name",
    "ServicePriceListName": "services_pricelist_name",
}


def load_health_facilities_xml(xml):
    result = []
    errors = []
    root = xml.getroot()

    for elm in root.find("HealthFacilityDetails").findall("HealthFacility"):
        data = {}
        for field in elm.iter():
            if field.tag in HF_FIELDS_MAP:
                text_value = field.text.strip() if field.text else None
                if text_value != "" and text_value is not None:
                    data[HF_FIELDS_MAP[field.tag]] = text_value

        if not (data.get("code") and data.get("name")):
            errors.append("Health facility has no code or no name defined: %s" % data)
            continue

        if not data.get("legal_form_id"):
            errors.append(
                "Health facility '%s' has no legal form defined" % data["code"]
            )
            continue

        if not data.get("level"):
            errors.append("Health facility '%s' has no level defined" % data["code"])
            continue

        if not data.get("care_type"):
            errors.append(
                "Health facility '%s' has no care type defined" % data["code"]
            )
            continue

        if not data.get("level"):
            errors.append("Health facility '%s' has no legal form" % data["code"])
            continue

        result.append(data)

    return result, errors


@functools.lru_cache(None)
def get_pricelist(name, type):
    if type == "services":
        return ServicesPricelist.objects.filter(name=name, *filter_validity()).first()
    elif type == "items":
        return ItemsPricelist.objects.filter(name=name, *filter_validity()).first()


def upload_health_facilities(user, xml, strategy=STRATEGY_INSERT, dry_run=False):
    get_parent_location.cache_clear()

    logger.info(
        "Uploading health facilities with strategy={strategy} & dry_run={dry_run}"
    )
    try:
        raw_health_facilities, errors = load_health_facilities_xml(xml)
    except Exception as exc:
        raise InvalidXMLError("XML file is invalid.") from exc

    result = UploadResult(errors=errors)
    db_health_facilities = {
        x.code: x
        for x in HealthFacility.objects.filter(
            code__in=[x["code"] for x in raw_health_facilities], *filter_validity()
        )
    }
    for facility in raw_health_facilities:
        logger.debug("Processing facility: %s" % facility)
        existing = db_health_facilities.get(facility["code"], None)
        result.sent += 1

        if existing and strategy == STRATEGY_INSERT:
            result.errors.append(f"Health facility '{existing.code}' already exists")
            continue
        elif not existing and strategy == STRATEGY_UPDATE:
            result.errors.append(f"Health facility '{strategy['code']}' does not exist")
            continue

        facility["location"] = get_parent_location(facility.pop("district_code"))
        if not facility["location"]:
            result.errors.append(
                f"Location '{facility['district_code']}'' does not exist"
            )
            continue

        if "services_pricelist_name" in facility:
            facility["services_pricelist_id"] = get_pricelist(
                facility.pop("services_pricelist_name"), "services"
            )
        if "items_pricelist_name" in facility:
            facility["items_pricelist_id"] = get_pricelist(
                facility.pop("items_pricelist_name"), "items"
            )

        try:
            if strategy == STRATEGY_INSERT:
                if not dry_run:
                    HealthFacility.objects.create(
                        offline=False, audit_user_id=user.id_for_audit, **facility
                    )
                result.created += 1

            else:
                if existing:
                    if not dry_run:
                        existing.save_history()
                        [setattr(existing, key, facility[key]) for key in facility]
                        existing.save()
                    result.updated += 1
                else:
                    if not dry_run:
                        existing = HealthFacility.objects.create(
                            offline=False, audit_user_id=user.id_for_audit, **facility
                        )
                    result.created += 1
        except Exception as exc:
            logger.exception(exc)
            result.errors.append(
                "Cannot create or update health facility : %s" % facility["code"]
            )

    logger.debug(f"Finished processing of health facilities: {result}")
    return result


def create_master_data_export(user):
    queries = {
        "confirmationTypes": """SELECT "ConfirmationTypeCode", "ConfirmationType", "SortOrder", "AltLanguage" FROM "tblConfirmationTypes";""",
        "controls": """SELECT "FieldName", "Adjustibility" FROM "tblControls";""",
        "education": """SELECT "EducationId", "Education", "SortOrder", "AltLanguage" FROM "tblEducations";""",  # and not educations
        "familyTypes": """SELECT "FamilyTypeCode", "FamilyType", "SortOrder", "AltLanguage" FROM "tblFamilyTypes";""",
        "hf": """SELECT "HfID", "HFCode", "HFName", "LocationId", "HFLevel" FROM "tblHF" WHERE "ValidityTo" IS NULL;""",
        "identificationTypes": """SELECT "IdentificationCode", "IdentificationTypes", "SortOrder", "AltLanguage" FROM "tblIdentificationTypes";""",
        "languages": """SELECT "LanguageCode", "LanguageName", "SortOrder" FROM "tblLanguages";""",
        "locations": """SELECT "LocationId", "LocationCode", "LocationName", "ParentLocationId", "LocationType" FROM "tblLocations" WHERE "ValidityTo" IS NULL AND NOT("LocationName"='Funding' OR "LocationCode"='FR' OR "LocationCode"='FD' OR "LocationCode"='FW' OR "LocationCode"='FV')""",
        "officers": """SELECT "OfficerID", "OfficerUUID", "Code", "LastName", "OtherNames", "Phone", "LocationId", "OfficerIDSubst", TO_CHAR("WorksTo", 'yyyy-MM-dd') worksTo FROM "tblOfficer" WHERE "ValidityTo" IS NULL;"""
        if connection.vendor == "postgresql" else
        """SELECT "OfficerID", "OfficerUUID", "Code", "LastName", "OtherNames", "Phone", "LocationId", "OfficerIDSubst", FORMAT("WorksTo", 'yyyy-MM-dd') worksTo FROM "tblOfficer" WHERE "ValidityTo" IS NULL;""",
        "payers": """SELECT "PayerID", "PayerName", "LocationId" FROM "tblPayer" WHERE "ValidityTo" IS NULL;""",
        "products": """SELECT "ProdID", "ProductCode", "ProductName", "LocationId", "InsurancePeriod", TO_CHAR("DateFrom", 'yyyy-MM-dd')dateFrom, TO_CHAR("DateTo", 'yyyy-MM-dd')dateTo, "ConversionProdID" , "LumpSum", "MemberCount", "PremiumAdult", "PremiumChild", "RegistrationLumpSum", "RegistrationFee", "GeneralAssemblyLumpSum", "GeneralAssemblyFee", "StartCycle1", "StartCycle2", "StartCycle3", "StartCycle4", "GracePeriodRenewal", "MaxInstallments", "WaitingPeriod", "Threshold", "RenewalDiscountPerc", "RenewalDiscountPeriod", "AdministrationPeriod", "EnrolmentDiscountPerc", "EnrolmentDiscountPeriod", "GracePeriod" FROM "tblProduct" WHERE "ValidityTo" IS NULL"""
        if connection.vendor == "postgresql" else
        """SELECT "ProdID", "ProductCode", "ProductName", "LocationId", "InsurancePeriod", FORMAT("DateFrom", 'yyyy-MM-dd')dateFrom, FORMAT("DateTo", 'yyyy-MM-dd')dateTo, "ConversionProdID" , "LumpSum", "MemberCount", "PremiumAdult", "PremiumChild", "RegistrationLumpSum", "RegistrationFee", "GeneralAssemblyLumpSum", "GeneralAssemblyFee", "StartCycle1", "StartCycle2", "StartCycle3", "StartCycle4", "GracePeriodRenewal", "MaxInstallments", "WaitingPeriod", "Threshold", "RenewalDiscountPerc", "RenewalDiscountPeriod", "AdministrationPeriod", "EnrolmentDiscountPerc", "EnrolmentDiscountPeriod", "GracePeriod" FROM "tblProduct" WHERE "ValidityTo" IS NULL""",
        "professions": """SELECT "ProfessionId", "Profession", "SortOrder", "AltLanguage" FROM "tblProfessions";""",
        "relations": """SELECT "RelationId", "Relation", "SortOrder", "AltLanguage" FROM "tblRelations";""",
        "phoneDefaults": """SELECT "RuleName", "RuleValue" FROM "tblIMISDefaultsPhone";""",
        "genders": """SELECT "Code", "Gender", "AltLanguage", "SortOrder" FROM "tblGender";""",
    }

    results = {}

    with connection.cursor() as cursor:
        for key, query in queries.items():
            cursor.execute(query)
            results[key] = dictfetchall(cursor)

    with tempfile.TemporaryDirectory() as tmp_dir_name:
        master_data_file_path = os.path.join(tmp_dir_name, "MasterData.txt")
        with open(master_data_file_path, "w") as file:
            file.write(json.dumps(results))

        zip_file = tempfile.NamedTemporaryFile(
            "wb",
            prefix=f"master_data_{datetime.now().isoformat()}",
            suffix=".zip",
            delete=False,
        )
        # We close it directly since the only thing we want is to have a temporary file that will not be deleted
        zip_file.close()

        pyminizip.compress(
            master_data_file_path,
            "",
            zip_file.name,
            ToolsConfig.get_master_data_password(),
            5,
        )

        return zip_file


def create_officer_feedbacks_export(user, officer):
    """
    SELECT F.ClaimId,F.OfficerId,O.Code OfficerCode, I.CHFID, I.LastName, I.OtherNames, HF.HFCode, HF.HFName,C.ClaimCode,CONVERT(NVARCHAR(10),C.DateFrom,103)DateFrom, CONVERT(NVARCHAR(10),C.DateTo,103)DateTo,O.Phone, CONVERT(NVARCHAR(10),F.FeedbackPromptDate,103)FeedbackPromptDate"
    FROM tblFeedbackPrompt F INNER JOIN tblOfficer O ON F.OfficerId = O.OfficerId"
    INNER JOIN tblClaim C ON F.ClaimId = C.ClaimId"
    INNER JOIN tblInsuree I ON C.InsureeId = I.InsureeId"
    INNER JOIN tblHF HF ON C.HFID = HF.HFID"
    WHERE F.ValidityTo Is NULL AND O.ValidityTo IS NULL"
    AND O.Code = @OfficerCode"
    AND C.FeedbackStatus = 4"

    """

    with connection.cursor() as cursor:
        results = dictfetchall(
            cursor.execute(
                f"""
            SELECT F."ClaimID",F."OfficerID",O."Code" OfficerCode, I."CHFID", I."LastName", I."OtherNames",
                HF."HFCode", HF."HFName",C."ClaimCode",{dmy_format_sql(connection.vendor, 'C."DateFrom"')} DateFrom, 
                CONVERT(NVARCHAR(10),C.DateTo,103)DateTo,O."Phone", {dmy_format_sql(connection.vendor, 'F.FeedbackPromptDate')} FeedbackPromptDate
                FROM "tblFeedbackPrompt" F 
                INNER JOIN "tblOfficer" O ON F."OfficerID" = O."OfficerID"
                INNER JOIN "tblClaim" C ON F."ClaimID" = C."ClaimID" 
                INNER JOIN "tblInsuree" I ON C."InsureeID" = I."InsureeID" 
                INNER JOIN "tblHF" HF ON C."HFID" = HF."HfID" 
                WHERE F."ValidityTo" Is NULL AND O."ValidityTo" IS NULL 
                AND F."OfficerId" = %s 
                AND C."FeedbackStatus" = 4
        """,
                (officer.id,),
            )
        )

    with tempfile.TemporaryDirectory() as tmp_dir_name:
        file_name = f"feedbaks_{officer.code}.txt"
        file_path = os.path.join(tmp_dir_name, file_name)
        with open(file_path, "w") as file:
            file.write(json.dumps(results))

        zip_file = tempfile.NamedTemporaryFile(
            "wb",
            prefix=f"feedbacks_{officer.code}_{datetime.now().isoformat()}",
            suffix=".zip",
            delete=False,
        )

        zf = zipfile.ZipFile(zip_file, "w")
        zf.write(file_path, file_name)
        zf.close()
        return zip_file


def create_officer_renewals_export(user, officer):
    from policy.models import PolicyRenewal

    renewals = PolicyRenewal.objects.filter(
        new_officer=officer, *filter_validity()
    ).prefetch_related(
        "policy__value",
        "new_officer__code",
        "new_product__name",
        "new_product__code",
        "insuree__chf_id",
        "insuree__last_name",
        "insuree__other_names",
        "insuree__family",
        "insuree__family__location__name",
    )

    results = []

    for renewal in renewals:
        results.append(
            {
                "RenewalId": renewal.id,
                "PolicyId": renewal.policy_id,
                "OfficerId": renewal.new_officer_id,
                "OfficerCode": renewal.new_officer.code,
                "CHFID": renewal.insuree.chf_id,
                "LastName": renewal.insuree.last_name,
                "OtherNames": renewal.insuree.other_names,
                "ProductCode": renewal.product.code,
                "ProductName": renewal.product.name,
                "ProdId": renewal.product_id,
                "VillageName": renewal.insuree.family.location.name,
                "FamilyId": renewal.insuree.family_id,
                "EnrollDate": renewal.renewal_date,
                "PolicyStage": "R",
                "PolicyValue": renewal.policy.value,
            }
        )

    with tempfile.TemporaryDirectory() as tmp_dir_name:
        file_name = f"renewals_{officer.code}.txt"
        file_path = os.path.join(tmp_dir_name, file_name)
        with open(file_path, "w") as file:
            file.write(json.dumps(results))

        zip_file = tempfile.NamedTemporaryFile(
            "wb",
            prefix=f"renewals_{officer.code}_{datetime.now().isoformat()}",
            suffix=".zip",
            delete=False,
        )

        zf = zipfile.ZipFile(zip_file, "w")
        zf.write(file_path, file_name)
        zf.close()
        return zip_file


def get_phone_extract_data(location_id):
    """uspPhoneExtract"""
    with connection.cursor() as cur:
        sql = """
            DECLARE @ret int;
            EXEC @ret = [dbo].[uspPhoneExtract] @LocationId = %s;
            SELECT @ret;
        """

        cur.execute(sql, (location_id,))
        # We have to take the second result set. That's the one that contains the results
        cur.nextset()
        cur.nextset()
        if cur.description is None:
            return
        return dictfetchall(cur)


def get_controls():
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT "FieldName", "Adjustibility", "Usage" FROM "tblControls";"""
        )
        return cursor.fetchall()  # Yes, the typo in 'Adjustibility' is on purpose.


def create_phone_extract_db(location_id, with_insuree=False):
    location = Location.objects.get(id=location_id, *filter_validity())
    if not location:
        raise ValueError(f"Location {location_id} does not exist")

    with tempfile.TemporaryDirectory() as tmp_dir:
        filename = f"phone_extract_{location.code}.db3"
        db_file_path = os.path.join(tmp_dir, filename)

        db_con = sqlite3.connect(db_file_path)

        db_con.executescript(
            """
            CREATE TABLE tblPolicyInquiry(CHFID text,Photo BLOB, InsureeName Text, DOB Text, Gender Text, ProductCode Text, ProductName Text, ExpiryDate Text, Status Text, DedType Int, Ded1 Int, Ded2 Int, Ceiling1 Int, Ceiling2 Int);
            CREATE TABLE tblReferences([Code] Text, [Name] Text, [Type] Text, [Price] REAL);
            CREATE TABLE tblControls([FieldName] Text, [Adjustibility] Text, [Usage] Text);
            CREATE TABLE tblClaimAdmins([Code] Text, [Name] Text);
        """
        )

        if with_insuree:
            rows = get_phone_extract_data(location_id) or []
            with db_con:
                db_con.executemany(
                    """
                    INSERT INTO tblPolicyInquiry(CHFID, Photo, InsureeName, DOB, Gender, ProductCode, ProductName, ExpiryDate, Status, DedType, Ded1, Ded2, Ceiling1, Ceiling2)
                    VALUES (:CHFID, :PhotoPath, :InsureeName, :DOB, :Gender, :ProductCode, :ProductName, :ExpiryDate, :Status, :DedType, :Ded1, :Ded2, :Ceiling1, :Ceiling2)
                """,
                    rows,
                )

        # References
        with db_con:
            # Medical Services
            db_con.executemany(
                "INSERT INTO tblReferences(Code, Name, Type, Price) VALUES (?, ?, 'S', ?)",
                Service.objects.filter(*filter_validity()).values_list(
                    "code", "name", "price"
                ),
            )

            # Medical Items
            db_con.executemany(
                "INSERT INTO tblReferences(Code, Name, Type, Price) VALUES (?, ?, 'I', ?)",
                Item.objects.filter(*filter_validity())
                .values_list("code", "name", "price")
                .all(),
            )

            # Medical Diagnosis
            db_con.executemany(
                "INSERT INTO tblReferences(Code, Name, Type, Price) VALUES (?, ?, 'D', 0)",
                Diagnosis.objects.filter(*filter_validity())
                .values_list("code", "name")
                .all(),
            )

        # Controls
        with db_con:
            db_con.executemany(
                "INSERT INTO tblControls (FieldName, Adjustibility, Usage) VALUES (?, ?, ?)",  # Yes, the typo in 'Adjustibility' is on purpose.
                get_controls(),
            )

        from django.db.models.functions import Concat
        from django.db.models import CharField, Value as V

        # Claim Admins
        admins = (
            ClaimAdmin.objects.filter(
                health_facility__location_id=location_id,
                health_facility__validity_to__isnull=True,
                *filter_validity(),
            )
            .annotate(
                name=Concat(
                    "last_name", V(" "), "other_names", output_field=CharField()
                )
            )
            .values_list("code", "name")
        )

        with db_con:
            db_con.executemany(
                "INSERT INTO tblClaimAdmins (Code, Name) VALUES (?, ?)", admins
            )

        db_con.close()
        return open(db_file_path, "rb")


def create_phone_extract(user, location_id, with_insuree=False):
    file = create_phone_extract_db(location_id, with_insuree=with_insuree)
    filename = os.path.basename(file.name)
    extract = Extract(
        location_id=location_id,
        type=1,
        audit_user_id=user.id_for_audit,
        direction=0,
        filename=filename,
    )

    extract.stored_file.save(filename, file)

    return extract


def upload_claim(user, xml):
    logger.info(f"Uploading claim with user {user.id}")

    if settings.ROW_SECURITY:
        logger.info("Check that user can upload claims in claims' health facilities")
        districts = UserDistrict.get_user_districts(user._u)
        hf_code = xml.find("Claim").find("Details").find("HFCode").text
        if not (
            HealthFacility.filter_queryset()
            .filter(location_id__in=[l.location_id for l in districts], code=hf_code)
            .exists()
        ):
            raise InvalidXMLError(
                f"User cannot upload claims for health facility {hf_code}"
            )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            DECLARE @ret int;
            EXEC @ret = [dbo].[uspUpdateClaimFromPhone] @XML = %s, @ByPassSubmit = 1;
            SELECT @ret;
        """,
            (ElementTree.tostring(xml),),
        )
        # We have to take the second result set. That's the one that contains the results
        cursor.nextset()
        cursor.nextset()
        if cursor.description is None:
            return
        res = cursor.fetchone()[0]

        if res == 0:
            return True
        elif res == 1:
            raise InvalidXMLError("Health facility invalid.")
        elif res == 2:
            raise InvalidXMLError("Duplicated claim code")
        elif res == 3:
            raise InvalidXMLError("Unknown insuree number")
        elif res == 4:
            raise InvalidXMLError("Invalid end date")
        elif res == 5:
            raise InvalidXMLError("Unknown diagnosis code")
        elif res == 7:
            raise InvalidXMLError("Unknown medical item code")
        elif res == 8:
            raise InvalidXMLError("Unknown medical service code")
        elif res == 9:
            raise InvalidXMLError("Unknown claim admin code")
        elif res == -1:
            raise InvalidXMLError("Unknown error occurred")


def open_offline_archive(archive: str, password: str = None):
    """
    Offline extracts are XML or JSON files, sometimes with pictures zipped with a password protection and then named
    .RAR. This method extracts such archives into a temporary directory
    """
    temp_folder = tempfile.mkdtemp(prefix="offline_archive")
    password = password if password else ToolsConfig.get_master_data_password()
    password = ")(#$1HsD"
    with pyzipper.AESZipFile(archive) as zf:
        zf.setpassword(str.encode(password))
        zf.extractall(path=temp_folder)
    return temp_folder


def get_or_create_insuree_from_xml(xml, audit_user_id, chf_id=None, family_id=None):
    # TODO use get() for missing field safety
    return Insuree.objects.get_or_create(
        validity_to=None,
        chf_id=chf_id if chf_id else xml.get("CHFID"),
        defaults={
            # "InsureeId": xml.get("InsureeId"),
            "chf_id": xml.get("CHFID"),
            "last_name": xml.get("LastName"),
            "other_names": xml.get("OtherNames"),
            "dob": xml.get("DOB"),
            "gender_id": xml.get("Gender"),
            "marital": xml.get("Marital"),
            "head": xml.get("isHead"),
            # "identification_number": xml.get("IdentificationNumber"),  # TODO ???
            "phone": xml.get("Phone"),
            # "photo_path": xml.get("PhotoPath"),  # TODO handle separately
            "card_issued": xml.get("CardIssued"),
            "relationship_id": xml.get("Relationship"),
            "profession_id": xml.get("Profession"),
            "education_id": xml.get("Education"),
            "email": xml.get("Email"),
            "type_of_id_id": xml.get("TypeOfId"),
            "health_facility_id": xml.get("HFID"),
            "current_address": xml.get("CurrentAddress"),
            "geolocation": xml.get("GeoLocation"),
            "current_village_id": xml.get("CurVillage"),
            "offline": xml.get("isOffline"),
            # "vulnerability": xml.get("Vulnerability"),  # TODO Ignored by stored proc, no field in tblInsuree
            "audit_user_id": audit_user_id,
            "family_id": family_id,
        }
    )


def get_or_create_family_from_xml(xml, audit_user_id, head_insuree_id=None):
    if head_insuree_id:
        head_id = head_insuree_id
    else:
        head_id = Insuree.objects.get(
            validity_to__isnull=True,
            chf_id=xml.get("HOFCHFID") if xml.get("HOFCHFID") else xml.get("CHFID")
        ).id

    return Family.objects.get_or_create(
        validity_to=None,
        head_insuree__chf_id=head_id,
        defaults={
            # "family_id": xml.get("FamilyId"),
            "head_insuree_id": head_id,
            "location_id": xml.get("LocationId"),
            # "hofchfid": xml.get("HOFCHFID"), # not stored in the family in DB
            "poverty": xml.get("Poverty"),
            "family_type_id": xml.get("FamilyType"),
            "address": xml.get("FamilyAddress"),
            "ethnicity": xml.get("Ethnicity"),
            "confirmation_no": xml.get("ConfirmationNo"),
            "confirmation_type_id": xml.get("ConfirmationType"),
            "is_offline": xml.get("isOffline"),
            "audit_user_id": audit_user_id,
        }
    )


def get_or_create_policy_from_xml(xml, audit_user_id, family_id):
    return Policy.objects.get_or_create(
        validity_to=None,
        family_id=family_id,
        product_id=xml.get("ProdId"),
        defaults={
            "enroll_date": xml.get("EnrollDate"),
            "start_date": xml.get("StartDate"),
            "effective_date": xml.get("EffectiveDate"),
            "expiry_date": xml.get("ExpiryDate"),
            "status": xml.get("PolicyStatus"),
            "value": xml.get("PolicyValue"),
            "officer_id": xml.get("OfficerId"),
            "stage": xml.get("PolicyStage"),
            "offline": xml.get("isOffline"),
            # "control_number": xml.get("ControlNumber"),  # Not sure what it should map to ?
            "audit_user_id": audit_user_id,
        }
    )


def get_or_create_premium_from_xml(xml, audit_user_id, policy_id):
    is_photo_fee = xml.get("isPhotoFee", None)
    if is_photo_fee is not None:
        is_photo_fee = str(is_photo_fee).lower() == "true"
    return Premium.objects.get_or_create(
        validity_to=None,
        policy_id=policy_id,
        payer_id=xml.get("PayerId"),
        pay_date=xml.get("PayDate"),
        defaults={
            "amount": xml.get("Amount"),
            "receipt": xml.get("Receipt"),
            "pay_type": xml.get("PayType"),
            "is_photo_fee": is_photo_fee,
            "is_offline": xml.get("isOffline"),
            "audit_user_id": audit_user_id,
        }
    )


def get_or_create_insuree_policy_from_xml(xml, audit_user_id, policy_id, insurees):
    # We already have the actual policy_id but we need to find the actual ID of the insuree
    insuree = insurees.get(xml.get("InsureeId", None), None)
    if not insuree or "new_id" not in insuree:
        logger.warning("Could not find insuree id %s", xml.get("InsureeId"))
    return InsureePolicy.objects.get_or_create(
        validity_to=None,
        policy_id=policy_id,
        insuree_id=insuree.get("new_id"),
        effective_date=xml.get("EffectiveDate"),
        defaults={"audit_user_id": audit_user_id},
    )


def element_to_dict(element):
    return {x.tag: x.text for x in element}


def load_enrollment_xml(xml_file):
    """
    Loads an enrollment XML file into a bunch of dicts for easier processing
    """
    logger.debug("Processing file %s", xml_file)
    xml = sanitize_xml(xml_file)
    logger.debug(xml.getroot())
    file_info = xml.find("FileInfo")
    file_user_id = file_info.find("UserId")
    file_officer_id = file_info.find("OfficerId")

    # The XML has an array but we'll use a dict by CHFID for convenience
    # Duplicates will be handled by the procedure anyway
    families = {}
    for family_element in xml.find("Families").findall("Family"):
        family = element_to_dict(family_element)
        # TODO add more validation on the XML
        families[family["FamilyId"]] = family
    logger.debug("Loaded %s families from XML", len(families))
    insurees = {}
    for insuree_element in xml.find("Insurees").findall("Insuree"):
        insuree = element_to_dict(insuree_element)
        # TODO add more validation on the XML
        insurees[insuree["InsureeId"]] = insuree
    policies = {}
    for policy_element in xml.find("Policies").findall("Policy"):
        policy = element_to_dict(policy_element)
        # TODO add more validation on the XML
        policies[policy["PolicyId"]] = policy
    premiums = {}
    for premium_element in xml.find("Premiums").findall("Premium"):
        premium = element_to_dict(premium_element)
        # TODO add more validation on the XML
        premiums[premium["PremiumId"]] = premium
    insuree_policies = {}
    for insuree_policy_element in xml.find("InsureePolicies").findall("InsureePolicy"):
        insuree_policy = element_to_dict(insuree_policy_element)
        # TODO add more validation on the XML
        insuree_policies[insuree_policy["PolicyId"]] = insuree_policy

    return file_user_id, file_officer_id, families, insurees, policies, premiums, insuree_policies


def upload_enrollments(archive, user):
    """
    This method loads an Offline XML/ZIP/RAR archive from a file.
    These archives are usually named .RAR but they're actually .ZIP with a password and AES encryption.
    The AES encryption is not supported by the stock ZIP library of Python.
    The data is then stored separately between insurees, families, policies etc, so we'll do our best to recompose the
    relations.
    :param user: User object from authentication
    :param archive: file to read
    """
    logger.info(f"Uploading enrollments with user {user.id}")

    archive_dir = open_offline_archive(archive)
    for xml_file in glob.glob(os.path.join(archive_dir, "*.xml")):
        # TODO check consistency of IDs
        file_user_id, file_officer_id, families, insurees, policies, premiums, insuree_policies = \
            load_enrollment_xml(xml_file)

        for family_id, xml_family in families.items():
            # First, identify or create the head of family
            xml_head = insurees[xml_family["InsureeId"]]
            if not xml_head:
                # TODO
                logger.warning("Processing file %s, could not find insuree %s for family %s", None, None, None)
                continue

            head, head_created = get_or_create_insuree_from_xml(xml_head, user.id_for_audit)
            xml_head["new_id"] = head.id

            # TODO: verify that the family has a corresponding insuree
            # TODO: verify that the family doesn't already exist (that the insuree number would be present already)
            db_family, db_family_created = get_or_create_family_from_xml(xml_family, user.id_for_audit)
            xml_family["new_id"] = db_family.id
            head.family = db_family
            head.save()

            # Now that we have the head of the family, insert the other insurees of the family
            for insuree in insurees.values():
                if insuree["FamilyId"] == xml_family["FamilyId"] and "new_id" not in insuree:
                    db_insuree, db_insuree_created = get_or_create_insuree_from_xml(insuree, user.id_for_audit,
                                                                                    db_family.id)
                    insuree["new_id"] = db_insuree.id
                    logger.debug("Created family %s member %s (%s)", db_family.id, db_insuree.chf_id,
                                 db_insuree.other_names)

            for policy in policies.values():
                if policy["FamilyId"] == xml_family["FamilyId"] and "new_id" not in policy:
                    db_policy, db_policy_created = get_or_create_policy_from_xml(policy, user.id_for_audit,
                                                                                 db_family.id)
                    policy["new_id"] = db_policy.id
                    logger.debug("Created policy for family %s", db_family.id)

                    # We are processing only the premiums for the policy we just created
                    for premium in premiums.values():
                        if premium["PolicyId"] == policy["PolicyId"] and "new_id" not in premium:
                            db_premium, db_premium_created = get_or_create_premium_from_xml(premium, user.id_for_audit,
                                                                                            db_policy.id)
                            premium["new_id"] = db_premium.id
                            logger.debug("Created premium for policy %s, value=%s", db_premium.policy_id,
                                         db_premium.amount)

                    for insuree_policy in insuree_policies.values():
                        if insuree_policy["PolicyId"] == policy["PolicyId"] and "new_id" not in insuree_policy:
                            db_ip, db_ip_created = get_or_create_insuree_policy_from_xml(
                                insuree_policy, user.id_for_audit, db_policy.id, insurees)
                            insuree_policy["new_id"] = db_ip.id
                            logger.debug("Created insuree_policy for policy %s, insuree %s", db_ip.policy_id,
                                         db_ip.insuree_id)

            # TODO check that there are no leftovers
            logger.debug("Family %s imported successfully", family_id)

    logger.debug("Done loading enrollment archive")


def upload_renewals(archive, user):
    """
    This method loads an encrypted archive of renewals.
    Unlike the enrollments, the renewals are provided both as XML and JSON, so we'll use the latter.
    It's stored as one renewal per file. No array or anything inside.
    """
    logger.info(f"Uploading renewals with user {user.id}")
    renewed_policies = []
    failed_renewals = []

    archive_dir = open_offline_archive(archive)
    for json_file in glob.glob(os.path.join(archive_dir, "*.json")):
        with open(json_file) as f:
            renewal = json.load(f)
            policy = renewal.get("Policy")
            if not policy:
                logger.warning("Empty renewal in %s", json_file)
                continue
            db_policy = Policy.objects.filter(
                family__head_insuree__chf_id=policy.get("CHFID"),
                product__code=policy.get("ProductCode"),
                validity_to__isnull=True,
            ).first()
            if not db_policy:
                logger.warning("Policy renewal without existing policy")
                failed_renewals.append(policy)
                continue
            db_policy.save_history()
            # TODO save with:
            # RenewalId, Officer, CHFID, ReceiptNo, ProductCode, Amount, Date, Discontinue, PayerId
            db_policy.status = Policy.STATUS_ACTIVE
            db_policy.save()
            update_insuree_policies(db_policy, user.id_for_audit)
            renewed_policies.append(policy)


def upload_feedbacks():
    pass
