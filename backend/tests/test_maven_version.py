from app.services.maven_version import latest_version, sort_versions


def test_latest_version_uses_maven_like_order():
    versions = ["1.13.2-SNAPSHOT", "1.11.1", "1.12.5", "1.13.2"]
    assert latest_version(versions) == "1.13.2"
    assert sort_versions(versions)[-2:] == ["1.13.2-SNAPSHOT", "1.13.2"]

