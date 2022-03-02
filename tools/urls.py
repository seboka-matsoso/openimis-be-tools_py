from django.views.decorators.csrf import csrf_exempt

from . import views
from django.urls import path


urlpatterns = [
    path("registers/locations", views.LocationsAPIView.as_view()),
    path("registers/healthfacilities", views.HealthFacilitiesAPIView.as_view()),
    path("registers/diagnoses", views.DiagnosesAPIView.as_view()),
    path("extracts/download_master_data", csrf_exempt(views.download_master_data)),
    path("extracts/download_phone_extract", views.download_phone_extract),
    path("extracts/download_renewals", views.download_renewals),
    path("extracts/download_feedbacks", views.download_feedbacks),
    path("extracts/upload_claims", csrf_exempt(views.upload_claims)),
]
