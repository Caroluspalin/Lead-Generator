from fastapi.testclient import TestClient

PROFILE = {
    "name": "Palin",
    "company_name": "",
    "phone": "040 123 4567",
    "website": "https://palin.fi",
    "short_intro": "teen nettisivuja paikallisille yrityksille pääkaupunkiseudulla",
}


def test_get_missing_profile_is_404(client_a: TestClient) -> None:
    res = client_a.get("/sender-profile")
    assert res.status_code == 404
    assert res.json()["detail"] == "Sender profile not set"


def test_put_creates_and_get_returns_profile(client_a: TestClient) -> None:
    res = client_a.put("/sender-profile", json=PROFILE)
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "Palin"
    assert body["company_name"] is None  # tyhjä merkkijono -> None
    assert body["user_id"] == "user-a"
    assert client_a.get("/sender-profile").json() == body


def test_put_updates_existing_profile(client_a: TestClient) -> None:
    first = client_a.put("/sender-profile", json=PROFILE).json()
    second = client_a.put("/sender-profile", json={**PROFILE, "name": "  Carolus Palin  ", "phone": " "}).json()
    assert second["id"] == first["id"]
    assert second["name"] == "Carolus Palin"
    assert second["phone"] is None


def test_put_requires_name_and_intro(client_a: TestClient) -> None:
    assert client_a.put("/sender-profile", json={**PROFILE, "name": ""}).status_code == 422
    assert client_a.put("/sender-profile", json={**PROFILE, "name": "   "}).status_code == 422
    assert client_a.put("/sender-profile", json={**PROFILE, "short_intro": "     "}).status_code == 422
    assert client_a.get("/sender-profile").status_code == 404


def test_profiles_are_per_user(client_a: TestClient, client_b: TestClient) -> None:
    client_a.put("/sender-profile", json=PROFILE)
    assert client_b.get("/sender-profile").status_code == 404
    client_b.put("/sender-profile", json={**PROFILE, "name": "B"})
    assert client_a.get("/sender-profile").json()["name"] == "Palin"
