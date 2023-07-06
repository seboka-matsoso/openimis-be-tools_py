from django.db import models
import core.models as core_models
import uuid
from datetime import datetime as py_datetime


class Extract(core_models.VersionedModel):
    """
    Table that keep tracks of all extract of data requested by users
    """

    id = models.AutoField(db_column="ExtractID", primary_key=True)
    uuid = models.CharField(
        db_column="ExtractUUID",
        max_length=36,
        default=uuid.uuid4,
        unique=True,
        null=False,
    )
    type = models.SmallIntegerField(db_column="ExtractType", default=0, null=False)
    direction = models.SmallIntegerField(
        db_column="ExtractDirection", default=0, null=False
    )  # 0 = EXPORT, 1 = IMPORT
    sequence = models.IntegerField(db_column="ExtractSequence", null=False, default=0)
    date = models.DateTimeField(
        db_column="ExtractDate", null=False, default=py_datetime.now
    )
    filename = models.CharField(db_column="ExtractFileName", max_length=255)
    folder = models.CharField(db_column="ExtractFolder", max_length=255)
    location = models.ForeignKey(
        "location.Location", models.DO_NOTHING, db_column="LocationId"
    )
    health_facility = models.ForeignKey(
        "location.HealthFacility", models.DO_NOTHING, db_column="HFID"
    )
    app_version = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        db_column="AppVersionBackend",
        null=False,
        default=0,
    )
    audit_user_id = models.IntegerField(db_column="AuditUserID")
    stored_file = models.FileField(upload_to="extracts/%Y/%m/", db_column="ExtractFile")

    class Meta:
        managed = True
        db_table = "tblExtracts"
