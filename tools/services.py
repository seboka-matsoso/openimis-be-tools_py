from collections import defaultdict
import functools
from itertools import chain
from core.utils import filter_validity
from django.db.models.query_utils import Q
from tools.constants import (
    STRATEGY_INSERT,
    STRATEGY_INSERT_UPDATE_DELETE,
    STRATEGY_UPDATE,
)
from core import datetime
from medical.models import Diagnosis
from location.models import Location, HealthFacility
from medical_pricelist.models import ServicesPricelist, ItemsPricelist
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


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
