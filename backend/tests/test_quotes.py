"""Tarjous: summat ja alv, lukitus, hyväksynnän tuonti R2:sta, avaukset, tenant-isolaatio."""
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from app import main, quotes
from app.quotes import LineInput, compute_totals, deal_value_euros, format_eur, format_rate
from tests.test_demo_publish import CONFIG
from tests.test_demo_opens import OpensStore

T0 = datetime(2026, 11, 17, 12, 32, tzinfo=timezone.utc)
SLOT = int(T0.timestamp() // 600)
SIGNATURE = "data:image/png;base64,iVBORw0KGgo="


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Iterator[OpensStore]:
    fake = OpensStore()
    monkeypatch.setattr("app.main.get_r2_config", lambda: CONFIG)
    monkeypatch.setattr("app.main.get_object_store", lambda: fake)
    main._last_opens_sync.clear()
    yield fake
    main._last_opens_sync.clear()


def _item(client: TestClient, name: str = "Nettisivut", cents: int = 39000, vat: int = 2550, **extra: Any) -> dict[str, Any]:
    res = client.post("/service-catalog", json={"name": name, "unit_price_cents": cents, "vat_rate_bp": vat, **extra})
    assert res.status_code == 200, res.text
    return res.json()


def _quote(client: TestClient, lead_id: int, lines: list[tuple[int, int]], **extra: Any) -> dict[str, Any]:
    body = {"lines": [{"catalog_item_id": i, "quantity": q} for i, q in lines], **extra}
    res = client.post(f"/leads/{lead_id}/quotes", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def _send(client: TestClient, quote_id: int) -> dict[str, Any]:
    res = client.post(f"/quotes/{quote_id}/send")
    assert res.status_code == 200, res.text
    return res.json()


def _accept(store: OpensStore, quote: dict[str, Any], digest: str, **overrides: Any) -> None:
    token = quote["public_url"].rsplit("/", 1)[1]
    record = {"name": "Maija Meikäläinen", "accepted_at": "2026-11-18T08:00:00Z", "content_hash": digest,
              "authority": True, "signature": SIGNATURE, **overrides}
    store.objects[quotes.acceptance_key(token)] = (json.dumps(record).encode(), None)


def _digest(store: OpensStore, quote: dict[str, Any]) -> str:
    token = quote["public_url"].rsplit("/", 1)[1]
    return store.headers[quotes.quote_object_key(token)][2]["content-hash"]


def _acceptances(store: OpensStore) -> OpensStore:
    # list_objects kattaa vain opens; acceptances haetaan objects-sanakirjasta
    original = store.list_objects

    def listing(prefix: str) -> list[tuple[str, datetime]]:
        found = original(prefix)
        found += [(k, T0) for k in store.objects if k.startswith(prefix)]
        return found

    store.list_objects = listing  # type: ignore[method-assign]
    return store


# --- Summat ja alv ---

def test_totals_round_vat_per_line() -> None:
    lines = [LineInput("a", None, 1005, 1, 2550), LineInput("b", None, 333, 3, 1400), LineInput("c", None, 5000, 2, 0)]
    # a: vat 256,275 -> 256; b: net 999, vat 139,86 -> 140; c: 0
    totals = compute_totals(lines)
    assert (totals.net_cents, totals.vat_cents, totals.gross_cents) == (1005 + 999 + 10000, 256 + 140, 12400)
    assert totals.by_rate == {0: (10000, 0), 1400: (999, 140), 2550: (1005, 256)}


def test_vat_rounds_half_up() -> None:
    assert compute_totals([LineInput("x", None, 10, 1, 2550)]).vat_cents == 3  # 2,55 -> 3
    assert compute_totals([LineInput("x", None, 1, 1, 5000)]).vat_cents == 1  # 0,5 -> 1


def test_formatting_and_deal_value() -> None:
    assert format_eur(123456) == "1 234,56 €"
    assert format_rate(2550) == "25,5 %" and format_rate(0) == "0 %" and format_rate(1400) == "14 %"
    assert deal_value_euros(39049) == 390 and deal_value_euros(39050) == 391


def test_quote_totals_via_api(client_a: TestClient, make_lead: Any) -> None:
    lead = make_lead()
    web = _item(client_a, cents=39000, vat=2550)
    hosting = _item(client_a, "Ylläpito", cents=1990, vat=1400)
    quote = _quote(client_a, lead["id"], [(web["id"], 1), (hosting["id"], 12)])
    # net 390,00 + 238,80; alv 99,45 + 33,43 (238,80*14% = 33,432)
    assert quote["net_cents"] == 39000 + 23880
    assert quote["vat_cents"] == 9945 + 3343
    assert quote["gross_cents"] == quote["net_cents"] + quote["vat_cents"]
    assert quote["version"] == 1 and quote["status"] == "draft" and quote["public_url"] is None


def test_prices_only_from_catalog(client_a: TestClient, client_b: TestClient, make_lead: Any) -> None:
    lead = make_lead()
    foreign = _item(client_b)
    res = client_a.post(f"/leads/{lead['id']}/quotes", json={"lines": [{"catalog_item_id": foreign["id"], "quantity": 1}]})
    assert res.status_code == 404
    res = client_a.post(f"/leads/{lead['id']}/quotes", json={"lines": [{"catalog_item_id": 1, "unit_price_cents": 1, "quantity": 1}]})
    assert res.status_code in (404, 422)
    assert client_a.post(f"/leads/{lead['id']}/quotes", json={"lines": []}).status_code == 422
    assert client_a.post("/service-catalog", json={"name": "x", "unit_price_cents": -1, "vat_rate_bp": 0}).status_code == 422


def test_catalog_change_does_not_alter_quote(client_a: TestClient, make_lead: Any) -> None:
    lead = make_lead()
    item = _item(client_a)
    quote = _quote(client_a, lead["id"], [(item["id"], 1)])
    client_a.put(f"/service-catalog/{item['id']}", json={"name": "Uusi", "unit_price_cents": 99900, "vat_rate_bp": 0})
    again = client_a.get(f"/leads/{lead['id']}/quotes").json()[0]
    assert again["net_cents"] == quote["net_cents"] and again["lines"][0]["name"] == "Nettisivut"
    client_a.delete(f"/service-catalog/{item['id']}")
    assert client_a.get(f"/leads/{lead['id']}/quotes").json()[0]["lines"][0]["unit_price_cents"] == 39000


# --- Lähetys ---

def test_send_requires_profile_and_r2(client_a: TestClient, make_lead: Any, store: OpensStore) -> None:
    lead = make_lead()
    quote = _quote(client_a, lead["id"], [(_item(client_a)["id"], 1)])
    assert client_a.post(f"/quotes/{quote['id']}/send").status_code == 428


def test_send_publishes_page_and_sets_deal_value(
    client_a: TestClient, make_lead: Any, store: OpensStore, sender_profile: dict[str, Any]
) -> None:
    client_a.put("/sender-profile", json={**{k: sender_profile[k] for k in ("name", "short_intro")},
                                           "brand_name": "Palin Web", "quote_terms": "Maksuehto 14 pv netto."})
    lead = make_lead(deal_value=1)
    quote = _quote(client_a, lead["id"], [(_item(client_a)["id"], 1)])
    sent = _send(client_a, quote["id"])
    assert sent["status"] == "sent" and sent["public_url"].startswith(CONFIG.public_base_url + "/q/")
    token = sent["public_url"].rsplit("/", 1)[1]
    html = store.objects[f"quotes/{token}.html"][0].decode()
    assert "Palin Web" in html and "Maksuehto 14 pv netto." in html and "Lead" not in html.replace("Leads", "")
    assert "noindex" in html and "Hyväksy tarjous" in html
    assert store.headers[f"quotes/{token}.html"][2]["state"] == "open"
    assert store.objects[f"quotes/{token}.html"][1] is not None  # expires-at
    lead_now = next(l for l in client_a.get("/leads").json() if l["id"] == lead["id"])
    assert lead_now["deal_value"] == 390
    assert lead_now["quote_status"] == "sent" and lead_now["quote_net_cents"] == 39000


def test_empty_terms_means_no_terms_section(client_a: TestClient, make_lead: Any, store: OpensStore, sender_profile: dict[str, Any]) -> None:
    lead = make_lead()
    sent = _send(client_a, _quote(client_a, lead["id"], [(_item(client_a)["id"], 1)])["id"])
    html = store.objects[f"quotes/{sent['public_url'].rsplit('/', 1)[1]}.html"][0].decode()
    assert "<h2>Ehdot</h2>" not in html


def test_do_not_contact_blocks(client_a: TestClient, make_lead: Any, store: OpensStore, sender_profile: dict[str, Any]) -> None:
    lead = make_lead()
    quote = _quote(client_a, lead["id"], [(_item(client_a)["id"], 1)])
    client_a.patch(f"/leads/{lead['id']}", json={"do_not_contact": True})
    assert client_a.post(f"/quotes/{quote['id']}/send").status_code == 409


# --- Lukitus ---

def test_sent_quote_is_locked_new_version_supersedes(
    client_a: TestClient, make_lead: Any, store: OpensStore, sender_profile: dict[str, Any]
) -> None:
    lead = make_lead()
    item = _item(client_a)
    v1 = _send(client_a, _quote(client_a, lead["id"], [(item["id"], 1)])["id"])
    body = {"lines": [{"catalog_item_id": item["id"], "quantity": 2}]}
    assert client_a.put(f"/quotes/{v1['id']}", json=body).status_code == 409
    assert client_a.delete(f"/quotes/{v1['id']}").status_code == 409
    assert client_a.post(f"/quotes/{v1['id']}/send").status_code == 409

    v2 = client_a.post(f"/quotes/{v1['id']}/new-version").json()
    assert v2["version"] == 2 and v2["status"] == "draft" and v2["net_cents"] == v1["net_cents"]
    assert client_a.put(f"/quotes/{v2['id']}", json=body).json()["net_cents"] == 78000
    sent2 = _send(client_a, v2["id"])
    statuses = {q["version"]: q["status"] for q in client_a.get(f"/leads/{lead['id']}/quotes").json()}
    assert statuses == {1: "superseded", 2: "sent"}
    old_token = v1["public_url"].rsplit("/", 1)[1]
    assert store.headers[f"quotes/{old_token}.html"][2]["state"] == "superseded"
    assert "korvattu uudemmalla" in store.objects[f"quotes/{old_token}.html"][0].decode()
    assert next(l for l in client_a.get("/leads").json() if l["id"] == lead["id"])["deal_value"] == 780
    assert sent2["version"] == 2


def test_accepted_quote_is_locked(
    client_a: TestClient, make_lead: Any, store: OpensStore, sender_profile: dict[str, Any]
) -> None:
    _acceptances(store)
    lead = make_lead(pipeline_status="Contacted")
    item = _item(client_a)
    sent = _send(client_a, _quote(client_a, lead["id"], [(item["id"], 1)])["id"])
    _accept(store, sent, _digest(store, sent))
    res = client_a.post("/leads/sync-opens")
    assert res.status_code == 200
    assert res.json()["accepted_quotes"] == [
        {"lead_id": lead["id"], "name": lead["name"], "quote_id": sent["id"], "moved_to_hired": True}
    ]
    got = client_a.get(f"/leads/{lead['id']}/quotes").json()[0]
    assert got["status"] == "accepted" and got["accepted_name"] == "Maija Meikäläinen"
    assert got["accepted_at"].startswith("2026-11-18T08:00")
    body = {"lines": [{"catalog_item_id": item["id"], "quantity": 5}]}
    assert client_a.put(f"/quotes/{sent['id']}", json=body).status_code == 409
    assert client_a.delete(f"/quotes/{sent['id']}").status_code == 409
    assert client_a.post(f"/quotes/{sent['id']}/send").status_code == 409
    # Uusi versio on sallittu, ja hyväksytty pysyy hyväksyttynä
    assert client_a.post(f"/quotes/{sent['id']}/new-version").json()["version"] == 2
    assert client_a.get(f"/leads/{lead['id']}/quotes").json()[1]["status"] == "accepted"
    assert next(l for l in client_a.get("/leads").json() if l["id"] == lead["id"])["pipeline_status"] == "Hired"
    # R2:n todiste säilyy
    assert quotes.acceptance_key(sent["public_url"].rsplit("/", 1)[1]) in store.objects


@pytest.mark.parametrize("status,hired", [("Shortlisted", False), ("Rejected", False), ("Proposal Received", True), ("Hired", False)])
def test_acceptance_moves_to_hired_only_from_contacted_stages(
    client_a: TestClient, make_lead: Any, store: OpensStore, sender_profile: dict[str, Any], status: str, hired: bool
) -> None:
    _acceptances(store)
    lead = make_lead(pipeline_status=status)
    sent = _send(client_a, _quote(client_a, lead["id"], [(_item(client_a)["id"], 1)])["id"])
    _accept(store, sent, _digest(store, sent))
    out = client_a.post("/leads/sync-opens").json()["accepted_quotes"]
    assert out[0]["moved_to_hired"] is hired
    now = next(l for l in client_a.get("/leads").json() if l["id"] == lead["id"])["pipeline_status"]
    assert now == ("Hired" if (hired or status == "Hired") else status)


def test_invalid_acceptances_are_ignored(
    client_a: TestClient, make_lead: Any, store: OpensStore, sender_profile: dict[str, Any]
) -> None:
    _acceptances(store)
    lead = make_lead(pipeline_status="Contacted")
    sent = _send(client_a, _quote(client_a, lead["id"], [(_item(client_a)["id"], 1)])["id"])
    digest = _digest(store, sent)
    for bad in ({"content_hash": "0" * 64}, {"authority": False}, {"name": ""}, {"signature": "data:text/html,x"}):
        main._last_opens_sync.clear()
        _accept(store, sent, digest, **bad)
        assert client_a.post("/leads/sync-opens").json()["accepted_quotes"] == [], bad
    assert client_a.get(f"/leads/{lead['id']}/quotes").json()[0]["status"] == "sent"


# --- Avaukset (sama sync-opens) ---

def test_quote_opens_are_imported(client_a: TestClient, make_lead: Any, store: OpensStore, sender_profile: dict[str, Any]) -> None:
    lead = make_lead()
    sent = _send(client_a, _quote(client_a, lead["id"], [(_item(client_a)["id"], 1)])["id"])
    token = sent["public_url"].rsplit("/", 1)[1]
    store.opens[f"opens/q-{token}/{SLOT}-mobile"] = T0
    store.opens[f"opens/q-{token}/{SLOT + 1}-desktop"] = T0 + timedelta(minutes=14)
    out = client_a.post("/leads/sync-opens").json()
    assert out["new_quote_opens"] == [{"lead_id": lead["id"], "name": lead["name"], "count": 2}]
    assert out["new_opens"] == [] and store.opens == {}
    row = next(l for l in client_a.get("/leads").json() if l["id"] == lead["id"])
    assert row["quote_open_count"] == 2 and row["quote_last_opened_at"].startswith("2026-11-17T12:46")
    assert client_a.get(f"/leads/{lead['id']}/quotes").json()[0]["open_count"] == 2


# --- Tenant-isolaatio ---

def test_tenant_isolation(
    client_a: TestClient, client_b: TestClient, make_lead: Any, store: OpensStore, sender_profile: dict[str, Any]
) -> None:
    _acceptances(store)
    lead = make_lead(pipeline_status="Contacted")
    item = _item(client_a)
    sent = _send(client_a, _quote(client_a, lead["id"], [(item["id"], 1)])["id"])
    token = sent["public_url"].rsplit("/", 1)[1]
    store.opens[f"opens/q-{token}/{SLOT}-mobile"] = T0
    _accept(store, sent, _digest(store, sent))

    assert client_b.get("/service-catalog").json() == []
    assert client_b.get(f"/leads/{lead['id']}/quotes").status_code == 404
    assert client_b.post(f"/leads/{lead['id']}/quotes", json={"lines": [{"catalog_item_id": item["id"], "quantity": 1}]}).status_code == 404
    for call in (client_b.put(f"/quotes/{sent['id']}", json={"lines": [{"catalog_item_id": item["id"]}]}),
                 client_b.post(f"/quotes/{sent['id']}/send"), client_b.post(f"/quotes/{sent['id']}/new-version"),
                 client_b.delete(f"/quotes/{sent['id']}")):
        assert call.status_code == 404
    assert client_b.put(f"/service-catalog/{item['id']}", json={"name": "x", "unit_price_cents": 1, "vat_rate_bp": 0}).status_code == 404
    assert client_b.delete(f"/service-catalog/{item['id']}").status_code == 404

    # B:n synkka ei tuo eikä poista A:n avauksia tai hyväksyntöjä
    out = client_b.post("/leads/sync-opens").json()
    assert out["new_quote_opens"] == [] and out["accepted_quotes"] == []
    assert f"opens/q-{token}/{SLOT}-mobile" in store.opens
    assert client_a.get(f"/leads/{lead['id']}/quotes").json()[0]["status"] == "sent"
    assert all(l["quote_status"] is None for l in client_b.get("/leads").json())


def test_lead_delete_removes_quotes(client_a: TestClient, make_lead: Any, store: OpensStore, sender_profile: dict[str, Any]) -> None:
    lead = make_lead()
    sent = _send(client_a, _quote(client_a, lead["id"], [(_item(client_a)["id"], 1)])["id"])
    token = sent["public_url"].rsplit("/", 1)[1]
    assert client_a.delete(f"/leads/{lead['id']}").status_code == 200
    assert f"quotes/{token}.html" not in store.objects
