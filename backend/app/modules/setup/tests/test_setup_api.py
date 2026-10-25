from fastapi.testclient import TestClient

TEAMS = "Team\nNorth Star\nRiverside United\nHarbour Lions\nPine Rangers\n"


def test_setup_needs_an_account(api: TestClient) -> None:
    response = api.post(
        "/api/v1/setup",
        json={"organisation_id": "0192f0c4-0000-7000-8000-000000000001", "name": "Cup"},
    )

    assert response.status_code == 401


def test_setup_upload_and_extract_over_http(api: TestClient, signed_in: dict[str, str]) -> None:
    headers = {"X-CSRF-Token": signed_in["csrf_token"]}
    org = api.post(
        "/api/v1/organisations",
        json={
            "kind": "community",
            "name": "Setup Org",
            "sports": ["football"],
            "accept_processing_terms": True,
        },
        headers=headers,
    ).json()
    started = api.post(
        "/api/v1/setup",
        json={
            "organisation_id": org["id"],
            "name": "Setup Cup",
            "starts_on": "2026-06-12",
            "ends_on": "2026-06-12",
        },
        headers=headers,
    )
    session = started.json()["id"]
    upload = api.post(
        f"/api/v1/setup/{session}/files",
        data={"kind": "team_list"},
        files={"file": ("teams.csv", TEAMS.encode(), "text/csv")},
        headers=headers,
    )
    extracted = api.post(f"/api/v1/setup/{session}/extract", headers=headers)
    fetched = api.get(f"/api/v1/setup/{session}")

    assert started.status_code == 201
    assert upload.status_code == 201
    assert extracted.status_code == 202
    body = fetched.json()
    assert [t["name"] for t in body["draft"]["draft"]["teams"]][:2] == [
        "North Star",
        "Riverside United",
    ]
    assert body["draft"]["open_questions"] == []
    assert {a["field"] for a in body["draft"]["assumptions"]} >= {
        "schedule.days",
        "schedule.pitches",
    }


def test_someone_elses_setup_is_not_found(api: TestClient) -> None:
    response = api.get("/api/v1/setup/0192f0c4-0000-7000-8000-000000000009")

    assert response.status_code in (401, 404)
