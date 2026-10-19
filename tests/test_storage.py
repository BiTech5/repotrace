from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier

import pytest
from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from repotrace.storage import BugReport, ReportStore


def make_report(report_id: str = "abc123", **kwargs) -> BugReport:
    data = {"id": report_id, "title": "Sample failure"}
    data.update(kwargs)
    return BugReport(**data)


def test_save_and_load_roundtrip(tmp_path):
    store = ReportStore(tmp_path)
    report = make_report(tags=["regression"], metadata={"python": "3.12"})

    path = store.save(report)

    assert path == tmp_path / "abc123.json"
    loaded = store.load("abc123")
    assert loaded.id == report.id
    assert loaded.title == report.title
    assert loaded.tags == ["regression"]
    assert loaded.metadata == {"python": "3.12"}


def test_save_sets_updated_at(tmp_path):
    store = ReportStore(tmp_path)
    report = make_report()
    assert report.updated_at is None

    store.save(report)

    assert isinstance(store.load("abc123").updated_at, datetime)


def test_save_rejects_existing_id_without_changing_report(tmp_path):
    store = ReportStore(tmp_path)
    path = store.save(make_report(title="Original"))
    original = path.read_bytes()

    with pytest.raises(FileExistsError):
        store.save(make_report(title="Replacement"))

    assert path.read_bytes() == original


def test_save_allows_explicit_overwrite(tmp_path):
    store = ReportStore(tmp_path)
    path = store.save(make_report(title="Original"))

    written = store.save(make_report(title="Replacement"), overwrite=True)

    assert written == path
    assert store.load("abc123").title == "Replacement"
    assert store.list_ids() == ["abc123"]


def test_concurrent_saves_do_not_replace_the_winning_report(tmp_path):
    store = ReportStore(tmp_path)
    ready = Barrier(2)

    def save(title):
        writer = ReportStore(tmp_path)
        ready.wait(timeout=5)
        try:
            writer.save(make_report(title=title))
        except FileExistsError:
            return None
        return title

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save, ["First", "Second"]))

    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert store.load("abc123").title == winners[0]


def test_serialization_failure_does_not_create_an_empty_report(tmp_path):
    store = ReportStore(tmp_path)

    with pytest.raises(PydanticSerializationError):
        store.save(make_report(metadata={"unsupported": object()}))

    assert not store.exists("abc123")


def test_failed_serialization_does_not_truncate_an_explicit_overwrite(tmp_path):
    store = ReportStore(tmp_path)
    path = store.save(make_report(title="Original"))
    original = path.read_bytes()

    with pytest.raises(PydanticSerializationError):
        store.save(make_report(metadata={"unsupported": object()}), overwrite=True)

    assert path.read_bytes() == original


def test_created_at_defaults_to_aware_datetime():
    assert make_report().created_at.tzinfo is not None


def test_load_missing_report_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        ReportStore(tmp_path).load("missing")


def test_delete_report(tmp_path):
    store = ReportStore(tmp_path)
    store.save(make_report())

    assert store.delete("abc123") is True
    assert store.exists("abc123") is False
    assert store.delete("abc123") is False


def test_list_returns_sorted_reports(tmp_path):
    store = ReportStore(tmp_path)
    store.save(make_report("b"))
    store.save(make_report("a"))

    assert store.list_ids() == ["a", "b"]
    assert [report.id for report in store.list()] == ["a", "b"]


def test_frozen_model_rejects_mutation():
    report = make_report()
    with pytest.raises(ValidationError):
        report.title = "changed"
