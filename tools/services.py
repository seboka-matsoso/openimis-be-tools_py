from collections import defaultdict
import functools
import decimal
from django.conf import settings
from django.db import connection
from itertools import chain
from core.utils import filter_validity
from django.db.models.query_utils import Q
from tools.constants import (
    STRATEGY_INSERT,
    STRATEGY_INSERT_UPDATE_DELETE,
    STRATEGY_UPDATE,
)
from tools.apps import ToolsConfig
from datetime import datetime
from medical.models import Diagnosis, Item, Service
from location.models import Location, HealthFacility, UserDistrict
from medical_pricelist.models import ServicesPricelist, ItemsPricelist
from claim.models import ClaimAdmin
from .utils import dictfetchall, sanitize_xml
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


def upload_locations(user, xml, strategy=STRATEGY_INSERT, dry_run=False):
    logger.info(f"Uploading locations with strategy={strategy} & dry_run={dry_run}")
    try:
        locations, errors = load_locations_xml(xml)
    except Exception as exc:
        raise InvalidXMLError("XML file is invalid.") from exc
    result = UploadResult(errors=errors)
    ids = [x["code"] for x in chain.from_iterable(locations.values())]
    existing_locations = {
        l.code: l for l in Location.objects.filter(code__in=ids, *filter_validity())
    }
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

            if strategy == STRATEGY_INSERT:
                if not dry_run:
                    Location.objects.create(audit_user_id=user.id_for_audit, **loc)
                result.created += 1

            else:
                if existing:
                    if not dry_run:
                        existing.save_history()
                        [setattr(existing, key, loc[key]) for key in loc]
                        existing.save()
                    result.updated += 1
                else:
                    if not dry_run:
                        existing = Location.objects.create(
                            audit_user_id=user.id_for_audit, **loc
                        )
                    result.created += 1

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
        "confirmationTypes": "SELECT confirmationTypeCode, confirmationType, sortOrder, altLanguage FROM tblConfirmationTypes;",
        "controls": "SELECT fieldName, adjustibility FROM tblControls",
        "education": "SELECT educationId, education, sortOrder, altLanguage FROM tblEducations",  # and not educations
        "familyTypes": "SELECT familyTypeCode, familyType, sortOrder, altLanguage FROM tblFamilyTypes",
        "hf": "SELECT hfid, hfCode, hfName, locationId, hfLevel FROM tblHF WHERE ValidityTo IS NULL",
        "identificationTypes": "SELECT identificationCode, identificationTypes, sortOrder, altLanguage FROM tblIdentificationTypes",
        "languages": "SELECT languageCode, languageName, sortOrder FROM tblLanguages",
        "location": "SELECT locationId, locationCode, locationName, parentLocationId, locationType FROM tblLocations WHERE ValidityTo IS NULL AND NOT(LocationName='Funding' OR LocationCode='FR' OR LocationCode='FD' OR LocationCode='FW' OR LocationCode='FV')",
        "officers": "SELECT officerId, officerUUID, code, lastName, otherNames, phone, locationId, officerIDSubst, FORMAT(WorksTo, 'yyyy-MM-dd')worksTo FROM tblOfficer WHERE ValidityTo IS NULL",
        "payers": "SELECT payerId, payerName, locationId FROM tblPayer WHERE ValidityTo IS NULL",
        "products": "SELECT prodId, productCode, productName, locationId, insurancePeriod, FORMAT(DateFrom, 'yyyy-MM-dd')dateFrom, FORMAT(DateTo, 'yyyy-MM-dd')dateTo, conversionProdId , lumpsum, memberCount, premiumAdult, premiumChild, registrationLumpsum, registrationFee, generalAssemblyLumpSum, generalAssemblyFee, startCycle1, startCycle2, startCycle3, startCycle4, gracePeriodRenewal, maxInstallments, waitingPeriod, threshold, renewalDiscountPerc, renewalDiscountPeriod, administrationPeriod, enrolmentDiscountPerc, enrolmentDiscountPeriod, gracePeriod FROM tblProduct WHERE ValidityTo IS NULL",
        "professions": "SELECT professionId, profession, sortOrder, altLanguage FROM tblProfessions",
        "relations": "SELECT relationid, relation, sortOrder, altLanguage FROM tblRelations",
        "phoneDefaults": "SELECT ruleName, ruleValue FROM tblIMISDefaultsPhone",
        "genders": "SELECT code, gender, altLanguage, sortOrder FROM tblGender",
    }

    results = {}

    with connection.cursor() as cursor:
        for key, query in queries.items():
            results[key] = dictfetchall(cursor.execute(query))

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
                """
            SELECT F.ClaimId,F.OfficerId,O.Code OfficerCode, I.CHFID, I.LastName, I.OtherNames,
                HF.HFCode, HF.HFName,C.ClaimCode,CONVERT(NVARCHAR(10),C.DateFrom,103)DateFrom, 
                CONVERT(NVARCHAR(10),C.DateTo,103)DateTo,O.Phone, CONVERT(NVARCHAR(10),F.FeedbackPromptDate,103)FeedbackPromptDate
                FROM tblFeedbackPrompt F 
                INNER JOIN tblOfficer O ON F.OfficerId = O.OfficerId
                INNER JOIN tblClaim C ON F.ClaimId = C.ClaimId 
                INNER JOIN tblInsuree I ON C.InsureeId = I.InsureeId 
                INNER JOIN tblHF HF ON C.HFID = HF.HFID 
                WHERE F.ValidityTo Is NULL AND O.ValidityTo IS NULL 
                AND F.OfficerId = %s 
                AND C.FeedbackStatus = 4
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
        return cursor.execute(
            "SELECT FieldName, Adjustibility, Usage FROM tblControls;"
        ).fetchall()  # Yes, the typo in 'Adjustibility' is on purpose.


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
            raise InvalidXMLError("Unkown error occured")
