import logging
import os
import tempfile
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
from medical.models import Diagnosis, Item, Service
from rest_framework.decorators import api_view, permission_classes, renderer_classes
from rest_framework.permissions import IsAuthenticated
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


@api_view(["GET"])
@permission_classes(
    [
        checkUserWithRights(
            ToolsConfig.registers_items_perms,
        )
    ]
)
@renderer_classes([serializers.ItemsXMLRenderer])
def download_items(request):
    """Downloads all medical.Item objects in an XML file.

    The list of exported fields can be modified in serializers.format_items().

    Calling this function is restricted to some users, see ToolsConfig.

    Parameters
    ----------
    request : rest_framework.request.Request
        The request that is asking to download items.

    Returns
    ----------
    rest_framework.response.Response
        The requested data in an XML file.

    """
    queryset = Item.objects.filter(*filter_validity())
    data = [serializers.format_items(item) for item in queryset]
    return Response(
        data=data,
        headers={"Content-Disposition": "attachment; filename=items.xml"},
    )


@api_view(["GET"])
@permission_classes(
    [
        checkUserWithRights(
            ToolsConfig.registers_services_perms,
        )
    ]
)
@renderer_classes([serializers.ServicesXMLRenderer])
def download_services(request):
    queryset = Service.objects.filter(*filter_validity())
    data = [serializers.format_services(service) for service in queryset]
    return Response(
        data=data,
        headers={"Content-Disposition": "attachment; filename=services.xml"},
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


@api_view(["POST"])
@permission_classes(
    [
        checkUserWithRights(
            ToolsConfig.registers_items_perms,
        )
    ]
)
def upload_items(request):
    """Uploads an XML file containing medical.Item entries.

    Calling this function is restricted to some users, see ToolsConfig.

    Parameters
    ----------
    request : rest_framework.request.Request
        The request containing all data.

    Returns
    ------
    rest_framework.response.Response
        Represents the number of entries received, with the number of created/updated/deleted
        medical.Item objects, as well as the list of errors that have occurred while each entry was processed.

    Raises
    ------
    ET.ParseError
        If the structure of the XML file is invalid.
    """
    serializer = serializers.DeletableUploadSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    file = serializer.validated_data.get("file")
    dry_run = serializer.validated_data.get("dry_run")
    strategy = serializer.validated_data.get("strategy")

    try:
        logger.info("Uploading medical items (dry_run=%s, strategy=%s)...", dry_run, strategy)
        xml = utils.sanitize_xml(file)
        result = services.upload_items(
            request.user, xml=xml, strategy=strategy, dry_run=dry_run
        )
        logger.info("Medical items upload completed: %s", result)
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
            errors.append("An unknown error occurred.")
            continue

    return JsonResponse({"success": len(errors) == 0, "errors": errors})


@api_view(["POST"])
@permission_classes(
    [
        checkUserWithRights(
            ToolsConfig.registers_locations_perms,
        )
    ]
)
# @require_http_methods(["POST"])
def upload_enrollments(request):
    if not request.user.has_perms(ToolsConfig.extracts_upload_claims_perms):  # TODO enrollment perms
        raise PermissionDenied(_("unauthorized"))

    return _process_upload(request, services.upload_enrollments)


@api_view(["POST"])
@permission_classes(
    [
        checkUserWithRights(
            ToolsConfig.registers_locations_perms,
        )
    ]
)
# @require_http_methods(["POST"])
def upload_renewals(request):
    if not request.user.has_perms(ToolsConfig.extracts_upload_claims_perms):  # TODO enrollment perms
        raise PermissionDenied(_("unauthorized"))

    return _process_upload(request, services.upload_renewals)


@api_view(["POST"])
@permission_classes(
    [
        checkUserWithRights(
            ToolsConfig.registers_locations_perms,
        )
    ]
)
# @require_http_methods(["POST"])
def upload_feedbacks(request):
    if not request.user.has_perms(ToolsConfig.extracts_upload_claims_perms):  # TODO enrollment perms
        raise PermissionDenied(_("unauthorized"))

    return _process_upload(request, services.upload_feedbacks)


def _process_upload(request, process_method):
    if not request.FILES:
        return JsonResponse({"error": "No file provided"}, status=400)

    errors = []
    for filename, uploaded_file in request.FILES.items():
        try:
            # The file is often in memory, the ZIP needs it as a real file path
            with tempfile.NamedTemporaryFile(mode='wb+', suffix=".zip") as tmp_file:
                logger.info(f"Processing renewals in {str(uploaded_file)}")
                for chunk in uploaded_file.chunks():
                    tmp_file.write(chunk)
                tmp_file.seek(0)
                process_method(tmp_file.name, request.user)
        except (utils.ParseError, services.InvalidXMLError) as exc:
            logger.exception(exc)
            errors.append(f"File '{filename}' is not a valid XML")
            continue
        except Exception as exc:
            logger.exception(exc)
            errors.append("An unknown error occurred.")
            return JsonResponse({"error": str(exc)}, status=500)

    return JsonResponse({"success": len(errors) == 0, "errors": errors})
