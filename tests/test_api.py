"""Producer, headlines, overlay and HTTP API, on a simulated match (offline)."""

import json
import re
from pathlib import Path

import anyio
import pytest
from fastapi.testclient import TestClient

from pitchside.agents.clients import ScriptedChatClient, json_reply, text_reply, tool_calls_reply
from pitchside.agents.contracts import Insight, Narrative, Sentence
from pitchside.agents.desk import cut
from pitchside.api.app import create_app
from pitchside.api.cache import BlobStore, DirStore, InsightCache
from pitchside.api.overlay import overlay, story_out, story_turn
from pitchside.api.producer import AIRABLE, PRODUCER, air_schedule
from pitchside.api.templates import headline
from pitchside.metrics._timeline import view
from pitchside.metrics.contract import ToolResult
from pitchside.metrics.grounding import validate
from pitchside.metrics.key_moments import all_moments
from pitchside.metrics.registry import call
from pitchside.simulator import simulate_match

SEED = 7  # has goals, decisive runs and a pressure shift on air


@pytest.fixture(scope="module")
def match():
    return simulate_match(SEED)


@pytest.fixture(scope="module")
def schedule(match):
    return air_schedule(match)


# --- producer ----------------------------------------------------------------------

def test_producer_is_causal(match, schedule):
    """Cutting the match never changes what had already aired: no look-ahead."""
    mid = match.events[len(match.events) // 2].seq
    early = [s for s in air_schedule(cut(match, mid)) if s.aired_at_seq < mid]
    assert early == [s for s in schedule if s.aired_at_seq < mid]
    assert all(s.moment.seq <= s.aired_at_seq for s in schedule)


def test_producer_airs_every_goal_and_respects_its_budget(match, schedule):
    goals = [e.seq for e in match.events if e.type == "shot" and e.outcome == "goal"]
    assert sorted(s.moment.seq for s in schedule if s.moment.kind == "goal") == goals
    assert {s.moment.kind for s in schedule} <= AIRABLE
    assert len({s.story_id for s in schedule}) == len(schedule)
    for s in schedule:
        assert s.moment.kind == "goal" or s.moment.importance >= PRODUCER["min_importance"]


def test_methods_doc_lists_producer_thresholds():
    doc = (Path(__file__).resolve().parents[1] / "docs" / "METHODS.md").read_text("utf-8")
    section = doc.split("## Producer", 1)[1]
    for key, value in PRODUCER.items():
        m = re.search(rf"`{key}` = ([-\d.]+)", section)
        assert m and float(m.group(1)) == value, key


# --- headlines -----------------------------------------------------------------------

@pytest.mark.parametrize("language", ["en", "es"])
def test_every_headline_passes_grounding(language):
    kinds = set()
    for seed in (SEED, 42):
        m = simulate_match(seed)
        v = view(m, m.events[-1].seq)
        for moment in all_moments(v):
            if moment.kind not in AIRABLE:
                continue
            kinds.add(moment.kind)
            text = headline(moment, m.metadata, language)
            result = ToolResult(tool_name="story", params={}, as_of_seq=v.as_of_seq,
                                facts=moment.facts, sample_size=1, method="headline")
            check = validate(text, [result], language)
            assert check.ok, (text, check.unmatched_numbers)
    assert kinds == AIRABLE  # every kind the producer can air was exercised


# --- overlay -------------------------------------------------------------------------

def test_overlay_only_shows_what_has_aired(match, schedule):
    first_story = schedule[0].aired_at_seq
    assert overlay(match, schedule, first_story - 1).stories == ()
    o = overlay(match, schedule, match.events[-1].seq)
    assert [s.aired_at_seq for s in o.stories] == sorted(
        (s.aired_at_seq for s in o.stories), reverse=True)
    goals = sum(e.type == "shot" and e.outcome == "goal" for e in match.events)
    assert sum(o.score.values()) == goals
    assert len(o.players) == 22


def test_decisive_run_story_carries_the_ghost_runner(match, schedule):
    story = next(s for s in schedule if s.moment.kind == "decisive_run")
    o = overlay(match, schedule, story.aired_at_seq)
    out = next(s for s in o.stories if s.story_id == story.story_id)
    g = out.ghost
    assert g is not None and g.player_id == story.moment.player_id
    moved = ((g.with_xy.x - g.without_xy.x) ** 2 + (g.with_xy.y - g.without_xy.y) ** 2) ** 0.5
    assert moved >= 4.0  # a credited run is at least MIN_RUN_M
    runner = next(p for p in g.frame if p.player_id == g.player_id)
    assert (runner.x, runner.y) == (g.with_xy.x, g.with_xy.y)
    assert set(out.headline) == {"en", "es"}


def test_overlay_is_deterministic(match, schedule):
    seq = match.events[300].seq
    a = overlay(match, schedule, seq).model_dump_json()
    b = overlay(simulate_match(SEED), air_schedule(simulate_match(SEED)), seq).model_dump_json()
    assert a == b


# --- HTTP ----------------------------------------------------------------------------

async def no_models(stack):
    return []


def make_client(tmp_path, models=no_models, per_minute=10):
    return TestClient(create_app(seeds=[SEED], models=models, cache_dir=tmp_path,
                                 insights_per_minute=per_minute))


@pytest.fixture
def client(tmp_path):
    with make_client(tmp_path) as c:
        yield c


def first_match(client):
    return client.get("/api/matches").json()[0]


def test_health_and_matches(client):
    health = client.get("/api/health").json()
    assert health["status"] == "ok" and health["models"] == [] and health["matches"] == 1
    m = first_match(client)
    meta = client.get(f"/api/matches/{m['match_id']}").json()
    assert meta["synthetic"] is True and len(meta["home"]["players"]) == 11
    assert client.get("/api/matches/nope").status_code == 404
    page = client.get("/")
    assert page.status_code == 200 and "<title>Pitchside</title>" in page.text
    assert client.get("/app.js").status_code == 200


def test_overlay_endpoint_and_schema(client, match, schedule):
    m = first_match(client)
    seq = schedule[2].aired_at_seq
    r = client.get(f"/api/matches/{m['match_id']}/overlay", params={"as_of_seq": seq})
    assert r.status_code == 200
    assert r.json() == json.loads(overlay(match, schedule, seq).model_dump_json())
    too_late = client.get(f"/api/matches/{m['match_id']}/overlay",
                          params={"as_of_seq": m["last_seq"] + 1})
    assert too_late.status_code == 422
    schema = client.get("/api/overlay/schema").json()
    assert "stories" in schema["properties"]
    aired = client.get(f"/api/matches/{m['match_id']}/stories", params={"as_of_seq": seq})
    assert [s["story_id"] for s in aired.json()] == [
        s.story_id for s in schedule if s.aired_at_seq <= seq]


def test_tool_proxy(client):
    m = first_match(client)
    url = f"/api/matches/{m['match_id']}/tools/match_summary"
    r = client.post(url, json={"as_of_seq": 100})
    assert r.status_code == 200 and r.json()["tool_name"] == "match_summary"
    assert client.post(url, json={"as_of_seq": 100, "extra": 1}).status_code == 422
    assert len(client.get("/api/tools").json()) >= 9


def test_insight_without_models_is_evidence_never_limited_nor_cached(tmp_path):
    turn = {"as_of_seq": 200, "kind": "moment", "persona": "casual", "language": "en"}
    with make_client(tmp_path, per_minute=1) as c:
        url = f"/api/matches/{first_match(c)['match_id']}/insights"
        answers = [c.post(url, json={**turn, "language": lang}) for lang in ("en", "es", "en")]
    assert [r.status_code for r in answers] == [200, 200, 200]
    assert answers[0].json()["status"] == "evidence_only" and answers[0].json()["evidence"]
    assert answers[0].json() == answers[2].json()  # deterministic without a model
    assert list(tmp_path.glob("*.json")) == []


def test_insight_with_a_model_is_verified_cached_and_limited(tmp_path, match):
    seq = 400
    score = next(f for f in call("match_summary", match, {"as_of_seq": seq}).facts
                 if f.evidence_id == "summary.scoreline")
    narrative = Narrative(sentences=(Sentence(text=f"It is {score.display}.",
                                              evidence_ids=(score.evidence_id,)),))

    def scripted_models():
        model = ScriptedChatClient([tool_calls_reply(("match_summary", {"as_of_seq": seq})),
                                    text_reply("done"), json_reply(narrative)])

        async def factory(stack):
            return [("primary", model)]
        return factory

    turn = {"as_of_seq": seq, "kind": "moment", "persona": "analyst", "language": "en"}
    with make_client(tmp_path, models=scripted_models(), per_minute=1) as c:
        assert c.get("/api/health").json()["models"] == ["primary"]
        url = f"/api/matches/{first_match(c)['match_id']}/insights"
        first = c.post(url, json=turn)
        # The script is used up: a second answer can only come from the cache.
        assert c.post(url, json=turn).json() == first.json()
        assert c.post(url, json={**turn, "language": "es"}).status_code == 429
    body = first.json()
    assert body["status"] == "verified" and body["model"] == "primary"
    assert body["sentences"][0]["text"] == f"It is {score.display}."
    with make_client(tmp_path, models=scripted_models()) as c:  # a new process: from disk
        assert c.post(url, json=turn).json() == body


def test_daily_cap_bounds_new_insights_across_clients(tmp_path):
    async def models(stack):
        return [("primary", ScriptedChatClient([]))]  # every turn: narrator unavailable

    turn = {"as_of_seq": 200, "kind": "moment", "persona": "casual", "language": "en"}
    app = create_app(seeds=[SEED], models=models, cache_dir=tmp_path,
                     insights_per_minute=10, insights_per_day=1)
    with TestClient(app) as c:
        url = f"/api/matches/{first_match(c)['match_id']}/insights"
        assert c.post(url, json=turn).status_code == 200
        second = c.post(url, json={**turn, "language": "es"},
                        headers={"X-Forwarded-For": "203.0.113.9"})
    assert second.status_code == 429 and "daily" in second.json()["detail"]


def test_story_insight_shares_the_precompute_cache_key(tmp_path, match, schedule):
    """An answer stored by the precompute script is what the UI gets for that story."""
    story = story_out(match, schedule[0])
    turn = story_turn(story, "casual", "es")
    stored = Insight(request=turn, status="verified", sentences=(), evidence=(), results=(),
                     attempts=1, model="primary")

    async def seed_cache():
        await InsightCache(DirStore(tmp_path)).put(InsightCache.key(match.metadata.match_id,
                                                                    turn), stored)
    anyio.run(seed_cache)
    with make_client(tmp_path) as c:
        base = f"/api/matches/{match.metadata.match_id}/stories"
        r = c.post(f"{base}/{story.story_id}/insights",
                   json={"persona": "casual", "language": "es"})
        assert r.status_code == 200 and r.json()["model"] == "primary"
        assert c.post(f"{base}/nope/insights",
                      json={"persona": "casual", "language": "es"}).status_code == 404


class FakeContainer:
    def __init__(self):
        self.blobs = {}

    async def download_blob(self, name, encoding):
        from azure.core.exceptions import ResourceNotFoundError
        if name not in self.blobs:
            raise ResourceNotFoundError("missing")

        class Downloader:
            async def readall(_):
                return self.blobs[name].decode(encoding)
        return Downloader()

    async def upload_blob(self, name, data, overwrite):
        assert overwrite
        self.blobs[name] = data


def test_blob_store_round_trip():
    async def go():
        store = BlobStore(FakeContainer())
        assert await store.get("k.json") is None
        await store.put("k.json", '{"a": "ñ"}')
        return await store.get("k.json")
    assert anyio.run(go) == '{"a": "ñ"}'


def test_model_outage_is_not_cached(tmp_path):
    async def broken(stack):
        return [("primary", ScriptedChatClient([]))]

    turn = {"as_of_seq": 200, "kind": "moment", "persona": "casual", "language": "en"}
    with make_client(tmp_path, models=broken) as c:
        r = c.post(f"/api/matches/{first_match(c)['match_id']}/insights", json=turn)
    assert r.json()["status"] == "evidence_only"
    assert list(tmp_path.glob("*.json")) == []
