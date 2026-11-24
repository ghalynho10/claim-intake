"""The claim fields every layer agrees on, in one fixed order.

The generator writes its answer key against this list, the extractor (feature 5)
asks the model for it, and scoring (feature 8) compares on it. Keeping it in one
pure module with no imports means none of those layers can drift to its own copy.
The order is part of the contract: packets list their expected fields in it.
"""

from enum import StrEnum


class FieldName(StrEnum):
    """The 19 scalar fields of an auto collision claim (spec 0003, The field list)."""

    POLICY_NUMBER = "policy_number"
    REPORTER_NAME = "reporter_name"
    REPORTER_CONTACT = "reporter_contact"
    REPORTER_RELATIONSHIP = "reporter_relationship"
    LOSS_DATE = "loss_date"
    LOSS_TIME = "loss_time"
    LOSS_LOCATION = "loss_location"
    LOSS_DESCRIPTION = "loss_description"
    VEHICLE_YEAR = "vehicle_year"
    VEHICLE_MAKE = "vehicle_make"
    VEHICLE_MODEL = "vehicle_model"
    DRIVER_NAME = "driver_name"
    OTHER_PARTY_NAME = "other_party_name"
    OTHER_PARTY_VEHICLE = "other_party_vehicle"
    OTHER_PARTY_INSURER = "other_party_insurer"
    INJURIES_REPORTED = "injuries_reported"
    INJURIES_WHO = "injuries_who"
    POLICE_REPORT_FILED = "police_report_filed"
    POLICE_REPORT_NUMBER = "police_report_number"
