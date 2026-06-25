def test_email_builder_route_is_removed(client):
    response = client.get("/email-builder/")
    assert response.status_code == 404
