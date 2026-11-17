"""Tests for App Finder, run through `LocalRunner` so the manifest is enforced."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pippa_agentapp_sdk import LocalRunner, OutputShapeViolation

from app import CATALOGUE, App, NoTask, UnknownAuthor

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


def call(inputs: dict, outcome: str = "apps.find", *, explicit: bool = False):
    return LocalRunner(App()).call(
        outcome, inputs, granted_secrets={}, now=NOW, request_id="test-1",
        explicit=explicit,
    ).result


def names(result) -> list[str]:
    return [line.split(",")[0] for line in result.data["apps"]]


def test_the_manifest_is_valid():
    app = App()
    assert app.manifest.app_id == "hack.dafydd_public"
    assert [o.id for o in app.manifest.outcomes] == ["apps.find", "apps.list"]


def test_the_catalogue_has_no_duplicates():
    all_names = [entry["name"] for entry in CATALOGUE["apps"]]
    assert len(all_names) == len(set(all_names)) == 17


@pytest.mark.parametrize("task, expected", [
    ("split a restaurant bill", "Bill Splitter"),
    ("will it rain at the weekend", "Next Dry Spell"),
    ("mortgage repayments", "Loan Repayment"),
    ("how safe is my area", "Crime Near a Place"),
    ("what time is sunset in paris", "Sunrise and Sunset"),
    ("check a book number", "ISBN Validator"),
    ("scale a recipe for 8", "Recipe Scaler"),
])
def test_a_job_finds_its_app(task, expected):
    result = call({"task": task})
    assert result.data["best_match"] == expected
    assert names(result)[0] == expected


def test_the_closest_app_comes_first():
    result = call({"task": "convert pounds to euros"})
    assert names(result) == ["Currency Converter", "Unit Converter"]
    assert result.data["best_match"] == "Currency Converter"
    assert result.data["apps"][0].startswith(
        "Currency Converter, from Hackathon Demos: Turns an amount of money")


def test_a_tie_names_no_best_match():
    """"pounds" is money or weight; neither app is the answer on its own."""
    result = call({"task": "pounds"})
    assert result.data["matched"] == 2
    assert "best_match" not in result.data


def test_nothing_suitable_is_an_answer_not_an_error():
    result = call({"task": "order a pizza"})
    assert result.data["matched"] == 0
    assert result.data["apps"] == []
    assert result.data["catalogue_size"] == 17
    assert result.data["catalogue_date"] == "2026-11-17"
    assert "None of the 17 apps" in result.narrative


@pytest.mark.parametrize("task", ["", "an app"])
def test_no_job_is_an_error_a_user_can_read(task):
    with pytest.raises(NoTask) as failure:
        call({"task": task})
    assert failure.value.user_message.startswith("Tell me what you want an app to do")


def test_a_missing_task_is_the_same_as_an_empty_one():
    with pytest.raises(NoTask):
        call({})


def test_it_lists_every_app_in_order():
    result = call({}, "apps.list")
    assert result.data["count"] == 17
    assert result.data["apps"] == sorted(result.data["apps"])
    assert "Pippa Diary, from Pippa Labs" in result.data["apps"]


def test_it_lists_one_authors_apps_whatever_the_capitals():
    result = call({"author": "hackathon demos"}, "apps.list")
    assert result.data["count"] == 15
    assert all(line.endswith(", from Hackathon Demos") for line in result.data["apps"])


def test_an_unknown_author_says_which_authors_there_are():
    with pytest.raises(UnknownAuthor) as failure:
        call({"author": "Narnia Apps"}, "apps.list")
    assert failure.value.user_message.startswith(
        "I do not know an author called Narnia Apps.")
    assert "Hackathon Demos" in failure.value.user_message


def test_picked_by_name_it_answers_and_refuses_as_usual():
    picked = call({"task": "split a restaurant bill"}, explicit=True)
    assert picked.data == call({"task": "split a restaurant bill"}).data
    with pytest.raises(NoTask):
        call({"task": ""}, explicit=True)


def test_the_runner_enforces_the_manifest(monkeypatch):
    from pippa_agentapp_sdk import Result

    monkeypatch.setattr(App, "handle", lambda self, c: Result(data={"surprise": 1}))
    with pytest.raises(OutputShapeViolation):
        call({"task": "split a restaurant bill"})
