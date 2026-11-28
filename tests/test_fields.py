"""The field list is a contract shared by the generator, extraction and scoring,
so its names and order are pinned here (spec 0003, AC-2)."""

from claim_intake.fields import FieldName
from claim_intake.generator.models import Scenario

PINNED = (
    "policy_number",
    "reporter_name",
    "reporter_contact",
    "reporter_relationship",
    "loss_date",
    "loss_time",
    "loss_location",
    "loss_description",
    "vehicle_year",
    "vehicle_make",
    "vehicle_model",
    "driver_name",
    "other_party_name",
    "other_party_vehicle",
    "other_party_insurer",
    "injuries_reported",
    "injuries_who",
    "police_report_filed",
    "police_report_number",
)


def test_field_list_and_order_are_pinned() -> None:
    assert tuple(FieldName) == PINNED
    assert len(FieldName) == 19


def test_scenario_has_one_attribute_per_field_in_order() -> None:
    assert tuple(Scenario.model_fields) == PINNED
