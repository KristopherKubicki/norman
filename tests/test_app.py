import json

def test_get_users(test_app):
    response = test_app.get("/users")
    assert response.status_code == 200
    users = json.loads(response.text)
    assert isinstance(users, list)
    assert len(users) > 0
