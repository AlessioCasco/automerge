import unittest
import json
from unittest.mock import patch
from unittest.mock import call
from src.main import get_pull_requests

class TestGetPullRequests(unittest.TestCase):
    def setUp(self):
        self.base_repos_url = "https://api.github.com/repos/owner/"
        self.repos = ["terraform-a", "terraform-b", "terraform-c", "terraform-d"]
        self.access_token = "my_access_token"

    @patch("requests.get")
    def test_get_pull_requests_regex(self, mock_get):
        # Mock the Github API calls
        mock_get.side_effect = [
            # terraform-a
            MockResponse([
                {"title": "automerge-123"},
                {"title": "[DEPENDENCIES] Update Terraform"},
                {"title": "other-789"},
                {"title": "[Dependabot] something"},
                {"title": "[DEPENDENCIES] Vault"}
            ], 200),
            # terraform-b
            MockResponse([
                {"title": "automerge-456"},
                {"title": "[DEPENDENCIES] Update Terraform"},
                {"title": "other-012"},
                {"title": "[Dependabot] something else"}
            ], 200),
            # terraform-c
            MockResponse([
                {"title": "automerge-789"},
                {"title": "other-345"},
                {"title": "[Dependabot] another thing"}
            ], 200),
            # terraform-d
            MockResponse([
                {"title": "automerge-012"},
                {"title": "[DEPENDENCIES] Update Terraform"},
                {"title": "other-678"},
                {"title": "[Dependabot] yet another thing"}
            ], 200)
        ]

        # Call the function and check the results
        filters = ["^\\[DEPENDENCIES\\] Update Terraform", "^\\[Dependabot\\]"]
        pull_requests = get_pull_requests(self.base_repos_url, self.repos, {"Authorization": f"Bearer {self.access_token}"}, filters)
        self.assertEqual(len(pull_requests), 7)

        values_list = [d["title"] for d in pull_requests]
        self.assertIn("[DEPENDENCIES] Update Terraform", values_list)
        self.assertNotIn("[DEPENDENCIES] Vault", values_list)
        self.assertIn("[Dependabot] something", values_list)
        self.assertIn("[Dependabot] yet another thing", values_list)
        self.assertNotIn("automerge-123", values_list)
        self.assertNotIn("automerge-456", values_list)
        self.assertNotIn("automerge-789", values_list)
        self.assertNotIn("automerge-012", values_list)
        self.assertNotIn("other-789", values_list)
        self.assertNotIn("other-012", values_list)
        self.assertNotIn("other-345", values_list)
        self.assertNotIn("other-678", values_list)

        # Check that the requests.get function was called with the correct arguments
        mock_get.assert_has_calls([
            call("https://api.github.com/repos/owner/terraform-a/pulls?per_page=100", headers={"Authorization": "Bearer my_access_token"}, timeout=10),
            call("https://api.github.com/repos/owner/terraform-b/pulls?per_page=100", headers={"Authorization": "Bearer my_access_token"}, timeout=10),
            call("https://api.github.com/repos/owner/terraform-c/pulls?per_page=100", headers={"Authorization": "Bearer my_access_token"}, timeout=10),
            call("https://api.github.com/repos/owner/terraform-d/pulls?per_page=100", headers={"Authorization": "Bearer my_access_token"}, timeout=10)
        ])

class MockResponse:
    def __init__(self, json_data, status_code):
        self.json_data = json_data
        self.status_code = status_code
        self.text = json.dumps(json_data)

    def json(self):
        return self.json_data
