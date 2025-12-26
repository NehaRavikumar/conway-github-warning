from app.plugins.npm_auth_token_expired import NpmAuthTokenExpiredPlugin
from app.types.signal import RunContext

def test_npm_plugin_matches_and_normalizes():
    plugin = NpmAuthTokenExpiredPlugin()
    ctx = RunContext(
        repo_full_name="org/repo",
        owner="org",
        run_id=123,
        html_url="https://example.com",
        workflow_name="CI",
        conclusion="failure",
        updated_at="2024-01-01T00:00:00Z",
        job_name="build",
    )
    log_text = "2024-01-01T00:00:01Z npm ERR! code E401   \nother line"
    match = plugin.match(ctx, log_text)
    assert match is not None
    assert match.signature == "npm_auth_token_expired"
    assert "2024-01-01" not in match.evidence["matched_line"]
    assert len(match.evidence["matched_line"]) <= 200
