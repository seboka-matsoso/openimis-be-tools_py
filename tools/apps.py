from django.apps import AppConfig

DEFAULT_CFG = {
    "registers_perms": ["131000"],
    "registers_diagnoses_perms": ["131000", "131002", "131001"],
    "registers_health_facilities_perms": ["131000", "131004", "131003"],
    "registers_locations_perms": ["131000", "131006", "131005"],
}


class ToolsConfig(AppConfig):
    name = "tools"

    registers_perms = []
    registers_diagnoses_perms = []
    registers_health_facilities_perms = []
    registers_locations_perms = []

    def _configure_permissions(self, cfg):
        ToolsConfig.registers_perms = cfg["registers_perms"]
        ToolsConfig.registers_diagnoses_perms = cfg["registers_diagnoses_perms"]
        ToolsConfig.registers_health_facilities_perms = cfg[
            "registers_health_facilities_perms"
        ]
        ToolsConfig.registers_locations_perms = cfg[
            "registers_locations_perms"
        ]
        

    def ready(self):
        from core.models import ModuleConfiguration

        cfg = ModuleConfiguration.get_or_default("tools", DEFAULT_CFG)
        self._configure_permissions(cfg)
