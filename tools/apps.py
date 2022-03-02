from django.apps import AppConfig
from django.conf import settings

DEFAULT_CFG = {
    "registers_perms": ["131000"],
    "registers_diagnoses_perms": ["131000", "131002", "131001"],
    "registers_health_facilities_perms": ["131000", "131004", "131003"],
    "registers_locations_perms": ["131000", "131006", "131005"],
    "extracts_master_data_perms": [],
    "extracts_officer_feedbacks_perms": [],
    "extracts_officer_renewals_perms": [],
    "extracts_phone_extract_perms": [],
    "extracts_upload_claims_perms": [],
}


class ToolsConfig(AppConfig):
    name = "tools"

    registers_perms = []
    registers_diagnoses_perms = []
    registers_health_facilities_perms = []
    registers_locations_perms = []

    extracts_master_data_perms = []
    extracts_officer_feedbacks_perms = []
    extracts_officer_renewals_perms = []
    extracts_phone_extract_perms = []
    extracts_upload_claims_perms = []

    master_data_password = None

    def _configure_permissions(self, cfg):
        ToolsConfig.registers_perms = cfg["registers_perms"]
        ToolsConfig.registers_diagnoses_perms = cfg["registers_diagnoses_perms"]
        ToolsConfig.registers_health_facilities_perms = cfg[
            "registers_health_facilities_perms"
        ]
        ToolsConfig.registers_locations_perms = cfg["registers_locations_perms"]
        ToolsConfig.extracts_master_data_perms = cfg["extracts_master_data_perms"]
        ToolsConfig.extracts_phone_extract_perms = cfg["extracts_phone_extract_perms"]
        ToolsConfig.extracts_upload_claims_perms = cfg["extracts_upload_claims_perms"]

        ToolsConfig.extracts_officer_feedbacks_perms = cfg[
            "extracts_officer_feedbacks_perms"
        ]
        ToolsConfig.extracts_officer_renewals_perms = cfg[
            "extracts_officer_renewals_perms"
        ]

    def ready(self):
        from core.models import ModuleConfiguration

        cfg = ModuleConfiguration.get_or_default("tools", DEFAULT_CFG)
        self._configure_permissions(cfg)

        ToolsConfig.master_data_password = cfg["master_data_password"]

    @classmethod
    def get_master_data_password(cls):
        return cls.master_data_password or (
            hasattr(settings, "MASTER_DATA_PASSWORD") and settings.MASTER_DATA_PASSWORD
        )
