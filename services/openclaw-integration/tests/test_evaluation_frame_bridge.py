"""Regression tests for task spec -> candidate plan bridge normalization."""

from app.evaluation_frame.bridge import task_spec_to_candidate_plan


def test_task_spec_to_candidate_plan_normalizes_provision_types():
    spec = {
        "operations": [
            {
                "op_id": "op-001",
                "type": "provision_repo",
                "target": "repo",
                "inputs": {
                    "provider": "github",
                    "repo_name": "cdmbr-demo-123",
                    "owner": "Conversion-Interactive-Agency",
                },
            },
            {
                "op_id": "op-002",
                "type": "provision_hosting",
                "target": "hosting/vercel",
                "inputs": {
                    "provider": "vercel",
                    "project_name": "cdmbr-demo-123",
                    "team_id": "team_Ne4knZa46E8bwGfI9LiJh8YQ",
                },
            },
        ]
    }

    cp = task_spec_to_candidate_plan(spec, ocgg_identity="W-OCGG", intent="web-build")
    assert len(cp.steps) == 2
    assert cp.steps[0].type.value == "deploy"
    assert cp.steps[0].inputs.provider == "github"
    assert cp.steps[0].inputs.project == "cdmbr-demo-123"
    assert cp.steps[1].type.value == "deploy"
    assert cp.steps[1].inputs.provider == "vercel"
    assert cp.steps[1].inputs.project == "cdmbr-demo-123"

