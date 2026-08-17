"""Découverte des dossiers de pages d'une semaine de capture."""

from __future__ import annotations

import json

import pytest

from app.ingestion.capture_layout import capture_page_dirs, capture_page_dirs_many


def _page(directory, name: str = "page-001.json") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(
        json.dumps({"captured_at": "2026-08-13T12:00:00Z", "products": []}),
        encoding="utf-8",
    )


def test_isolated_runs_are_captured_alongside_the_flat_layout(tmp_path):
    """Une exécution isolée est une preuve de la semaine, pas un brouillon."""
    week = tmp_path / "2026-W33"
    _page(week / "fruits-et-legumes__legumes", "20260813130231-page-001.json")
    _page(week / "run-20260813T181827Z" / "bieres-et-vins")
    _page(week / "run-20260813T181827Z" / "pains-et-patisseries")
    (week / "run-20260813T181827Z" / "_complete.json").write_text("{}", encoding="utf-8")

    directories = capture_page_dirs(week)

    assert directories == (
        week / "fruits-et-legumes__legumes",
        week / "run-20260813T181827Z" / "bieres-et-vins",
        week / "run-20260813T181827Z" / "pains-et-patisseries",
    )


def test_manifest_only_directories_are_not_capture_dirs(tmp_path):
    week = tmp_path / "2026-W33"
    _page(week / "legumes")
    (week / "run-vide").mkdir(parents=True)
    (week / "run-vide" / "_complete.json").write_text("{}", encoding="utf-8")

    assert capture_page_dirs(week) == (week / "legumes",)


def test_overlapping_roots_yield_each_directory_once(tmp_path):
    week = tmp_path / "2026-W33"
    run = week / "run-20260813T181827Z"
    _page(run / "boissons")

    assert capture_page_dirs_many([week, run]) == (run / "boissons",)


def test_a_root_without_any_page_is_an_error(tmp_path):
    empty = tmp_path / "2026-W34"
    empty.mkdir()

    with pytest.raises(FileNotFoundError):
        capture_page_dirs(empty)
