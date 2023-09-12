from django.apps import AppConfig
from django.conf import settings

MODULE_NAME = "tools"

DEFAULT_CFG = {
    "registers_perms": ["131000"],
    "registers_diagnoses_perms": ["131000", "131002", "131001"],
    "registers_health_facilities_perms": ["131000", "131004", "131003"],
    "registers_locations_perms": ["131000", "131006", "131005"],
    "registers_items_perms": ["131000", "131008", "131007"],
    "registers_services_perms": ["131000", "131010", "131009"],
    "extracts_master_data_perms": [],
    "extracts_officer_feedbacks_perms": [],
    "extracts_officer_renewals_perms": [],
    "extracts_phone_extract_perms": [],
    "extracts_upload_claims_perms": [],
    "master_data_password": None,
}


class ToolsConfig(AppConfig):
    name = MODULE_NAME
    registers_perms = []
    registers_diagnoses_perms = []
    registers_health_facilities_perms = []
    registers_locations_perms = []
    registers_items_perms = []
    registers_services_perms = []

    extracts_master_data_perms = []
    extracts_officer_feedbacks_perms = []
    extracts_officer_renewals_perms = []
    extracts_phone_extract_perms = []
    extracts_upload_claims_perms = []

    master_data_password = None

    def __load_config(self, cfg):
        for field in cfg:
            if hasattr(ToolsConfig, field):
                setattr(ToolsConfig, field, cfg[field])

    def ready(self):
        from core.models import ModuleConfiguration

        cfg = ModuleConfiguration.get_or_default(MODULE_NAME, DEFAULT_CFG)
        self.__load_config(cfg)

    @classmethod
    def get_master_data_password(cls):
        return cls.master_data_password or (
            hasattr(settings, "MASTER_DATA_PASSWORD") and settings.MASTER_DATA_PASSWORD
        )
