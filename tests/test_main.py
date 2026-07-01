"""Tests for main application entrypoint and orchestration paths."""

import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.agents.base_agent import AgentPersonality
from core.council.council import DebateFormat, DebateRound, DebateSession, VotingResult
from core.events.event_ingestion import Event, EventCategory, EventSource

import main


class _FakeAgent:
    def __init__(self, name: str, personality: AgentPersonality):
        self.name = name
        self.personality = personality
        self.debate_wins = 0
        self.total_contributions = 0


def _build_event():
    return Event(
        event_id="evt-1",
        title="Test debate",
        description="A focused test topic",
        source=EventSource.MANUAL,
        category=EventCategory.OTHER,
        timestamp=datetime.utcnow(),
    )


def _build_session(max_rounds: int = 3) -> DebateSession:
    return DebateSession(
        session_id="session-1",
        event=_build_event(),
        participating_agents=[
            _FakeAgent("Agent One", AgentPersonality.OPTIMIST),
            _FakeAgent("Agent Two", AgentPersonality.PESSIMIST),
        ],
        debate_format=DebateFormat.ROUNDTABLE,
        max_rounds=max_rounds,
    )


def test_setup_agents_respects_agent_count(monkeypatch):
    created = []

    class _DummyDebateAgent:
        def __init__(self, config, provider):
            created.append((config.name, provider))
            self.name = config.name
            self.personality = config.personality

    monkeypatch.setattr(main, "DebateAgent", _DummyDebateAgent)

    app = main.AICouncilApp(num_agents=2)
    app.setup_agents()

    assert len(app.council.agents) == 2
    assert created[:2] == [("Prometheus", "auto"), ("Cassandra", "auto")]


def test_setup_event_sources(monkeypatch):
    app = main.AICouncilApp()
    enabled = []

    monkeypatch.setattr(app.event_ingester, "enable_source", enabled.append)

    app.setup_event_sources()

    assert enabled == [
        main.EventSource.MANUAL,
        main.EventSource.CRYPTO_FEED,
        main.EventSource.NEWS,
    ]


@pytest.mark.asyncio
async def test_run_single_debate_with_topic(monkeypatch):
    app = main.AICouncilApp()
    session = _build_session()
    session.voting_result = None
    app.event_ingester.add_manual_event = MagicMock(return_value=_build_event())
    app.council.start_debate = AsyncMock(return_value=session)
    app.council.get_leaderboard = MagicMock(return_value=[("Agent One", 1)])
    app.output = MagicMock()
    app._run_debate_with_output = AsyncMock(
        side_effect=lambda session: setattr(
            session,
            "voting_result",
            VotingResult(
                topic=session.event.title,
                votes={"Agent One": 2},
                winner_agent="Agent One",
                total_votes=2,
            ),
        )
    )

    await app.run_single_debate(topic="Manual topic")

    app.event_ingester.add_manual_event.assert_called_once_with(
        title="Manual topic",
        description="Debate on: Manual topic",
        category=main.EventCategory.OTHER,
        facts=[],
    )
    app._run_debate_with_output.assert_awaited_once_with(session)
    app.output.start_session.assert_called_once_with(session)
    app.output.output_voting.assert_called_once_with(session.voting_result)
    app.output.output_summary.assert_called_once_with(session)
    app.output.output_leaderboard.assert_called_once_with([("Agent One", 1)])


@pytest.mark.asyncio
async def test_run_single_debate_without_event_early_returns(monkeypatch):
    app = main.AICouncilApp()
    app.event_ingester.get_next_event = AsyncMock(return_value=None)
    app.council.start_debate = AsyncMock()
    app._run_debate_with_output = AsyncMock()
    app.output = MagicMock()

    await app.run_single_debate()

    app.council.start_debate.assert_not_awaited()
    app._run_debate_with_output.assert_not_awaited()
    app.output.start_session.assert_not_called()


@pytest.mark.asyncio
async def test_run_continuous_loops_between_debates(monkeypatch):
    app = main.AICouncilApp()
    app.run_single_debate = AsyncMock()
    sleep_mock = AsyncMock()
    monkeypatch.setattr(main.asyncio, "sleep", sleep_mock)

    await app.run_continuous(num_debates=2)

    assert app.run_single_debate.await_count == 2
    assert sleep_mock.await_count == 2


@pytest.mark.asyncio
async def test_run_debate_with_output_stages_rounds(monkeypatch):
    app = main.AICouncilApp()
    session = _build_session(max_rounds=3)

    async def _opening_round(sess):
        for idx, agent in enumerate(sess.participating_agents):
            sess.rounds.append(
                DebateRound(round_number=0, speaker=agent, statement=f"opening-{idx}")
            )

    async def _debate_round(sess, round_num):
        for idx, agent in enumerate(sess.participating_agents):
            sess.rounds.append(
                DebateRound(
                    round_number=round_num,
                    speaker=agent,
                    statement=f"debate-{round_num}-{idx}",
                )
            )

    async def _closing_round(sess):
        for idx, agent in enumerate(sess.participating_agents):
            sess.rounds.append(
                DebateRound(
                    round_number=sess.max_rounds,
                    speaker=agent,
                    statement=f"closing-{idx}",
                )
            )

    expected_voting = VotingResult(
        topic=session.event.title,
        votes={"Agent One": 10, "Agent Two": 7},
        winner_agent="Agent One",
        total_votes=17,
    )
    app.council._opening_round = AsyncMock(side_effect=_opening_round)
    app.council._debate_round = AsyncMock(side_effect=_debate_round)
    app.council._closing_round = AsyncMock(side_effect=_closing_round)
    app.council._conduct_voting = AsyncMock(return_value=expected_voting)
    app.output = MagicMock()
    monkeypatch.setattr(main.asyncio, "sleep", AsyncMock())

    await app._run_debate_with_output(session)

    assert session.voting_result == expected_voting
    assert session.ended_at is not None
    assert session in app.council.session_history
    # opening + two debate rounds + closing, with 2 participants
    assert app.output.output_round.call_count == 8


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "argv, branch, payload",
    [
        (["main.py", "--provider", "mock", "--agents", "3", "--topic", "topic arg"], "single", "topic arg"),
        (["main.py", "--continuous", "--num-debates", "2"], "continuous", 2),
    ],
)
async def test_main_dispatches_args(monkeypatch, argv, branch, payload):
    calls = []

    class _FakeApp:
        def __init__(self, provider, num_agents):
            calls.append(("init", provider, num_agents))

        def setup_agents(self):
            calls.append(("setup_agents",))

        def setup_event_sources(self):
            calls.append(("setup_event_sources",))

        async def run_single_debate(self, topic=None):
            calls.append(("single", topic))

        async def run_continuous(self, num_debates):
            calls.append(("continuous", num_debates))

    monkeypatch.setattr(main, "AICouncilApp", _FakeApp)
    monkeypatch.setattr(sys, "argv", argv)

    await main.main()

    assert calls[0][0] == "init"
    assert ("setup_agents",) in calls
    assert ("setup_event_sources",) in calls

    if branch == "single":
        assert ("single", payload) in calls
        assert ("continuous",) not in calls
    else:
        assert ("continuous", payload) in calls
        assert ("single",) not in calls
