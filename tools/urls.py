from django.views.decorators.csrf import csrf_exempt

from . import views
from django.urls import path


urlpatterns = [
    path("registers/locations", views.LocationsAPIView.as_view()),
    path("registers/healthfacilities", views.HealthFacilitiesAPIView.as_view()),
    path("registers/diagnoses", csrf_exempt(views.DiagnosesAPIView.as_view())),
]
