import logging
import os
import xml.etree.ElementTree as ET

from core.models import Officer
from core.utils import filter_validity
from django.core.exceptions import PermissionDenied
from django.db.models.query_utils import Q
from django.http.response import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods
from location.models import HealthFacility, Location
from medical.models import Diagnosis
from rest_framework.decorators import api_view, permission_classes, renderer_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from . import serializers, services, utils
from .apps import ToolsConfig

logger = logging.getLogger(__name__)


def checkUserWithRights(rights):
    class UserWithRights(IsAuthenticated):
        def has_permission(self, request, view):
            return super().has_permission(request, view) and request.user.has_perms(
                rights
            )

    return UserWithRights


@api_view(["GET"])
@permission_classes(
    [
        checkUserWithRights(
            ToolsConfig.registers_locations_perms,
        )
    ]
)
@renderer_classes([serializers.LocationsXMLRenderer])
def download_locations(request):
    data = {"Regions": [], "Districts": [], "Villages": [], "Municipalities": []}

    for region in Location.objects.filter(~Q(code="FR"), type="R", *filter_validity()):
        data["Regions"].append(serializers.format_location(region))
        children = Location.objects.children(region.id).filter(validity_to=None)
        for child in children:
            if child.type == "D":
                data["Districts"].append(serializers.format_location(child))
            elif child.type == "M":
                data["Municipalities"].append(serializers.format_location(child))
            elif child.type == "V":
                data["Villages"].append(serializers.format_location(child))

    return Response(
        data,
        content_type="text/xml",
        headers={"Content-Disposition": "attachment; filename=locations.xml"},
    )


@api_view(["POST"])
@permission_classes(
    [
        checkUserWithRights(
            ToolsConfig.registers_locations_perms,
        )
    ]
)
def upload_locations(request):
    serializer = serializers.UploadSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    file = serializer.validated_data.get("file")
    dry_run = serializer.validated_data.get("dry_run")
    strategy = serializer.validated_data.get("strategy")

    try:
        logger.info(f"Uploading locations (dry_run={dry_run}, strategy={strategy})...")
        xml = utils.sanitize_xml(file)
        result = services.upload_locations(
            request.user, xml=xml, strategy=strategy, dry_run=dry_run
        )
        logger.info(f"Locations upload completed: {result}")
        return Response(
            {
                "success": True,
                "data": {
                    "sent": result.sent,
                    "created": result.created,
                    "updated": result.updated,
                    "errors": result.errors,
                },
            }
        )
    except services.InvalidXMLError as exc:
        return Response({"success": False, "error": str(exc)})
    except ET.ParseError as exc:
        logger.error(exc)
        return Response(
            {
                "success": False,
                "error": "Malformed XML",
            }
        )


@api_view(["GET"])
@permission_classes(
    [
        checkUserWithRights(
            ToolsConfig.registers_health_facilities_perms,
        )
    ]
)
@renderer_classes([serializers.HealthFacilitiesXMLRenderer])
def download_health_facilities(request):
    queryset = HealthFacility.objects.filter(*filter_validity())
    data = {
        "health_facility_details": [
            serializers.format_health_facility(hf) for hf in queryset
        ]
    }
    return Response(
        data=data,
        content_type="text/xml",
        headers={"Content-Disposition": "attachment; filename=health_facilities.xml"},
    )


@api_view(["POST"])
@permission_classes(
    [
        checkUserWithRights(
            ToolsConfig.registers_health_facilities_perms,
        )
    ]
)
def upload_health_facilities(request):
    serializer = serializers.UploadSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    file = serializer.validated_data.get("file")
    dry_run = serializer.validated_data.get("dry_run")
    strategy = serializer.validated_data.get("strategy")

    try:
        logger.info(
            f"Uploading health facilities (dry_run={dry_run}, strategy={strategy})..."
        )
        xml = utils.sanitize_xml(file)
        result = services.upload_health_facilities(
            request.user, xml=xml, strategy=strategy, dry_run=dry_run
        )
        logger.info(f"Health facilities upload completed: {result}")
        return Response(
            {
                "success": True,
                "data": {
                    "sent": result.sent,
                    "created": result.created,
                    "updated": result.updated,
                    "errors": result.errors,
                },
            }
        )
    except ET.ParseError as exc:
        logger.error(exc)
        return Response(
            {
                "success": False,
                "error": "Malformed XML",
            }
        )


@api_view(["GET"])
@permission_classes(
    [
        checkUserWithRights(
            ToolsConfig.registers_diagnoses_perms,
        )
    ]
)
@renderer_classes([serializers.DiagnosesXMLRenderer])
def download_diagnoses(request):
    queryset = Diagnosis.objects.filter(*filter_validity())
    data = [serializers.format_diagnosis(hf) for hf in queryset]
    return Response(
        data=data,
        headers={"Content-Disposition": "attachment; filename=diagnoses.xml"},
    )


@api_view(["POST"])
@permission_classes(
    [
        checkUserWithRights(
            ToolsConfig.registers_diagnoses_perms,
        )
    ]
)
def upload_diagnoses(request):
    serializer = serializers.DeletableUploadSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    file = serializer.validated_data.get("file")
    dry_run = serializer.validated_data.get("dry_run")
    strategy = serializer.validated_data.get("strategy")

    try:
        logger.info(f"Uploading diagnoses (dry_run={dry_run}, strategy={strategy})...")
        xml = utils.sanitize_xml(file)
        result = services.upload_diagnoses(
            request.user, xml=xml, strategy=strategy, dry_run=dry_run
        )
        logger.info(f"Diagnoses upload completed: {result}")
        return Response(
            {
                "success": True,
                "data": {
                    "sent": result.sent,
                    "created": result.created,
                    "updated": result.updated,
                    "deleted": result.deleted,
                    "errors": result.errors,
                },
            }
        )
    except ET.ParseError as exc:
        logger.error(exc)
        return Response(
            {
                "success": False,
                "error": "Malformed XML",
            }
        )


def download_master_data(request):
    if not request.user.has_perms(ToolsConfig.extracts_master_data_perms):
        raise PermissionDenied(_("unauthorized"))

    export_file = services.create_master_data_export(request.user)

    response = FileResponse(
        open(export_file.name, "rb"),
        as_attachment=True,
        filename=os.path.basename(export_file.name),
        content_type="application/zip",
    )
    return response


def download_phone_extract(request):
    if not request.user.has_perms(ToolsConfig.extracts_phone_extract_perms):
        raise PermissionDenied(_("unauthorized"))

    location_id = request.GET.get("location")
    with_insuree = request.GET.get("with_insuree", False)

    if not location_id:
        return Response(status=400, data={"error": "Location must be provided."})

    extract = services.create_phone_extract(request.user, location_id, with_insuree)

    return FileResponse(
        extract.stored_file,
        as_attachment=True,
        filename=os.path.basename(extract.stored_file.name),
    )


def download_feedbacks(request):
    if not request.user.has_perms(ToolsConfig.extracts_officer_feedbacks_perms):
        raise PermissionDenied(_("unauthorized"))

    officer_code = request.GET.get("officer")
    officer = get_object_or_404(Officer, code__iexact=officer_code, *filter_validity())

    export_file = services.create_officer_feedbacks_export(request.user, officer)

    response = FileResponse(
        open(export_file.name, "rb"),
        as_attachment=True,
        filename=os.path.basename(export_file.name),
        content_type="application/zip",
    )

    return response


def download_renewals(request):
    if not request.user.has_perms(ToolsConfig.extracts_officer_renewals_perms):
        raise PermissionDenied(_("unauthorized"))

    officer_code = request.GET.get("officer")
    officer = get_object_or_404(Officer, code__iexact=officer_code, *filter_validity())

    export_file = services.create_officer_renewals_export(request.user, officer)
    response = FileResponse(
        open(export_file.name, "rb"),
        as_attachment=True,
        filename=os.path.basename(export_file.name),
        content_type="application/zip",
    )

    return response


@require_http_methods(["POST"])
def upload_claims(request):
    if not request.user.has_perms(ToolsConfig.extracts_upload_claims_perms):
        raise PermissionDenied(_("unauthorized"))

    if not request.FILES:
        return JsonResponse({"error": "No file provided"}, status=400)

    errors = []
    for filename in request.FILES:
        try:
            logger.info(f"Processing claim in {filename}")
            xml = utils.sanitize_xml(request.FILES[filename])
            services.upload_claim(request.user, xml)
        except (utils.ParseError, services.InvalidXMLError) as exc:
            logger.exception(exc)
            errors.append(f"File '{filename}' is not a valid XML")
            continue
        except Exception as exc:
            logger.exception(exc)
            errors.append("An unknown error occured.")
            continue

    return JsonResponse({"success": len(errors) == 0, "errors": errors})
