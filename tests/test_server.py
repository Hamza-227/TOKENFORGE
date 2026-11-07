from fastapi.testclient import TestClient
import server

client = TestClient(server.app)


def test_pages_and_status():
    assert client.get("/").status_code == 200
    assert client.get("/logo.png").status_code == 200
    modes = client.get("/api/status").json()["modes"]
    assert len(modes) == 3


def test_process_requires_input():
    assert client.post("/api/process", data={"mode": "balanced"}).status_code == 400


def test_process_samples(tmp_path):
    r = client.post("/api/process", data={"sample": "true", "mode": "balanced", "output_dir": str(tmp_path)})
    assert r.status_code == 200
    j = r.json()
    assert len(j["results"]) == 2 and not j["errors"]
    assert client.get("/api/zip").status_code == 200


def test_home_page_is_landing_with_links():
    html = client.get("/").text
    assert "Try it out" in html and 'href="#tool"' in html
    assert "https://github.com/Hamza-227/TOKENFORGE" in html
    assert "https://www.linkedin.com/in/hamza-anjum-459bba320/" in html
    assert "Made by" in html
