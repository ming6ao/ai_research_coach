"""Stage 10 tests: replay harness runs all bundled scenarios with regression checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from learning_partner.harness.replay import ReplayEngine
from learning_partner.storage.database import Base

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "learning_partner" / "harness" / "scenarios"


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    return engine, Session()


def load_scenarios() -> list[dict]:
    scenarios = []
    for path in sorted(SCENARIOS_DIR.glob("*.json")):
        with open(path) as fh:
            scenarios.append(json.load(fh))
    return scenarios


ALL_SCENARIOS = load_scenarios()


@pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s["name"])
def test_scenario_passes(scenario):
    engine, session = _session()
    try:
        report = ReplayEngine(session).run(scenario)
        assert report.passed, f"scenario {scenario['name']} failed: {report.failures}"
    finally:
        session.close()
        engine.dispose()


class TestScenarioSuite:
    def test_all_bundled_scenarios_present(self):
        names = [s["name"] for s in ALL_SCENARIOS]
        assert len(names) >= 6
        assert any("beginner" in n for n in names)
        assert any("misconception" in n for n in names)

    def test_beginner_learner_evolves(self):
        engine, session = _session()
        try:
            scenario = next(s for s in ALL_SCENARIOS if "beginner" in s["name"])
            report = ReplayEngine(session).run(scenario)
            assert report.states["normalize_weights"].mastery > 0.5
            assert report.states["construct_cdf"].mastery < 0.5
        finally:
            session.close()
            engine.dispose()

    def test_misconception_scenario_raises_hypothesis(self):
        engine, session = _session()
        try:
            scenario = next(s for s in ALL_SCENARIOS if "misconception" in s["name"])
            report = ReplayEngine(session).run(scenario)
            assert any(m["node"] == "cdf_is_normalized_weights" for m in report.misconceptions)
        finally:
            session.close()
            engine.dispose()

    def test_not_observed_never_incorrect(self):
        """Direct check independent of a full scenario."""
        from learning_partner.domain.evidence import Evidence, EvidenceType, ObservationStatus
        from learning_partner.domain.learner import Learner
        from learning_partner.container import build_container

        engine, session = _session()
        try:
            c = build_container(session)
            from learning_partner.seed import seed_weighted_sampling, seed_misconceptions

            seed_weighted_sampling(c.knowledge_repository)
            seed_misconceptions(c.knowledge_repository)
            learner = c.learner_service.create_learner()
            node = c.knowledge_repository.get_node_by_slug("handle_boundaries")
            c.evidence_service.add_evidence(
                Evidence(
                    learner_id=learner.id, node_id=node.id,
                    evidence_type=EvidenceType.ANSWER,
                    observation_status=ObservationStatus.NOT_OBSERVED,
                )
            )
            summary = c.evidence_service.summarize(learner.id, node.id)
            assert summary.not_observed_count == 1
            assert summary.incorrect_count == 0
        finally:
            session.close()
            engine.dispose()


def test_scenario_files_are_valid_json():
    for path in SCENARIOS_DIR.glob("*.json"):
        with open(path) as fh:
            data = json.load(fh)
        assert data["name"]
        assert "interactions" in data
        assert "assertions" in data