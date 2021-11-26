from core.utils import filter_validity
from django.db.models.query_utils import Q
from rest_framework.decorators import authentication_classes, renderer_classes
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework import parsers
from . import serializers
from rest_framework.authentication import SessionAuthentication, BasicAuthentication
from rest_framework.response import Response
from location.models import Location, HealthFacility
from medical.models import Diagnosis
import xml.etree.ElementTree as ET
import logging
from . import services
from .apps import ToolsConfig

logger = logging.getLogger(__name__)


class CsrfExemptSessionAuthentication(SessionAuthentication):
    def enforce_csrf(self, request):
        return  # To not perform the csrf check previously happening


def checkUserWithRights(rights):
    class UserWithRights(IsAuthenticated):
        def has_permission(self, request, view):
            return super().has_permission(request, view) and request.user.has_perms(
                rights
            )

    return UserWithRights


class LocationsAPIView(APIView):
    authentication_classes = [BasicAuthentication, CsrfExemptSessionAuthentication]
    permission_classes = [
        checkUserWithRights(
            ToolsConfig.registers_locations_perms,
        )
    ]

    @renderer_classes([serializers.LocationsXMLRenderer])
    def get(self, request):
        data = {"Regions": [], "Districts": [], "Villages": [], "Municipalities": []}

        for region in Location.objects.filter(
            ~Q(code="FR"), type="R", *filter_validity()
        ):
            data["Regions"].append(serializers.format_location(region))
            children = Location.objects.children(region.id)
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

    def post(self, request):
        serializer = serializers.UploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        file = serializer.validated_data.get("file")
        dry_run = serializer.validated_data.get("dry_run")
        strategy = serializer.validated_data.get("strategy")

        try:
            logger.info(
                f"Uploading locations (dry_run={dry_run}, strategy={strategy})..."
            )
            xml = ET.parse(file)
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
            return Response({
                "success": False,
                "error": str(exc)
            })
        except ET.ParseError as exc:
            logger.error(exc)
            return Response(
                {
                    "success": False,
                    "error": "Malformed XML",
                }
            )


class HealthFacilitiesAPIView(APIView):
    authentication_classes = [BasicAuthentication, CsrfExemptSessionAuthentication]
    permission_classes = [
        checkUserWithRights(
            ToolsConfig.registers_health_facilities_perms,
        )
    ]

    @renderer_classes([serializers.HealthFacilitiesXMLRenderer])
    def get(self, request):
        queryset = HealthFacility.objects.filter(*filter_validity())
        data = {
            "health_facility_details": [
                serializers.format_health_facility(hf) for hf in queryset
            ]
        }
        return Response(
            data=data,
            content_type="text/xml",
            headers={
                "Content-Disposition": "attachment; filename=health_facilities.xml"
            },
        )

    def post(self, request):
        serializer = serializers.UploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        file = serializer.validated_data.get("file")
        dry_run = serializer.validated_data.get("dry_run")
        strategy = serializer.validated_data.get("strategy")

        try:
            logger.info(
                f"Uploading health facilities (dry_run={dry_run}, strategy={strategy})..."
            )
            xml = ET.parse(file)
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


class DiagnosesAPIView(APIView):
    authentication_classes = [BasicAuthentication, CsrfExemptSessionAuthentication]
    permission_classes = [
        checkUserWithRights(
            ToolsConfig.registers_diagnoses_perms,
        )
    ]
    parser_classes = (parsers.MultiPartParser,)

    @renderer_classes([serializers.DiagnosesXMLRenderer])
    def get(self, request):
        queryset = Diagnosis.objects.filter(*filter_validity())
        data = [serializers.format_diagnosis(hf) for hf in queryset]
        return Response(
            data=data,
            content_type="text/xml",
            headers={"Content-Disposition": "attachment; filename=diagnoses.xml"},
        )

    def post(self, request):
        serializer = serializers.DeletableUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        file = serializer.validated_data.get("file")
        dry_run = serializer.validated_data.get("dry_run")
        strategy = serializer.validated_data.get("strategy")

        try:
            logger.info(
                f"Uploading diagnoses (dry_run={dry_run}, strategy={strategy})..."
            )
            xml = ET.parse(file)
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
