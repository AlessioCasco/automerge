#!/usr/bin/env python3

import argparse
import json
import time
import re
import requests
from rich.console import Console


def main():
    """
    main
    """
    try:
        # Init parser for the arguments
        parser = argparse.ArgumentParser(
            prog="Automerge",
            description="Github PR auto-merger",
            epilog="Thanks for flying automerge")
        parser.add_argument(
            "--config_file",
            type=str,
            default="./config.json",
            help="JSON file holding the GitHub access token, default is ./config.json")
        # ToDo: Add force option to force all PRs to be planned no matter if there are diffs
        # parser.add_argument(
        #     '--force',
        #     action='store_true',
        #     default=True,
        #     help='Forces all PRs to be planned no matter if there where diffs previously')
        parser.add_argument(
            "--approve_all",
            action="store_true",
            default=False,
            help="Approves all PRs that match the filters in the config")
        args = parser.parse_args()

        # Read JSON config file
        config_file = read_config(args.config_file)

        # Extract info from config
        # GitHub Access token
        access_token = use_config(config_file, "access_token")
        # Owner of the repo
        owner = use_config(config_file, "owner")
        # GitHub user that this script impersonates
        github_user = use_config(config_file, "github_user")
        # List of repos to check
        repos = use_config(config_file, "repos")
        # filters used to match the PR we want to manage
        filters = use_config(config_file, "filters")

        # base_repos_url = f"https://api.github.com/repos/{owner}/{REPO}/"
        base_repos_url = f"https://api.github.com/repos/{owner}/"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }

        all_pulls = get_pull_requests(
            base_repos_url, repos, headers, filters)

        if args.approve_all:
            print("Only Approving Now")
            approve_all_prs(headers, all_pulls, github_user)
            raise SystemExit(0)

        # return (list_no_comments, list_with_diffs, list_no_changes, list_error)
        pr_list_no_comments, pr_with_diffs, pr_list_no_changes, pr_list_error = create_pr_lists(
            all_pulls, headers)

        if pr_list_no_changes:
            print("\nMerging what's possible\n")
            merge_pull_req(pr_list_no_changes, github_user, headers)

        if pr_with_diffs:
            print("\nUnlocking PR\n")
            comment_pull_req(pr_with_diffs, "atlantis unlock",
                            headers, False)
            # ToDo: Wait untill atlantis sends the comment, confirming the PR is unlocked.
            time.sleep(4)
            comment_pull_req(pr_with_diffs, "This PR will be ignored by automerge",
                            headers, False)
            set_label_to_pull_request(pr_with_diffs, "automerge_ignore", headers)

        if pr_list_no_comments or pr_list_error:
            print("\n\nCommenting to plan PRs\n")
            comment_pull_req(
                pr_list_no_comments +
                pr_list_error,
                "atlantis plan",
                headers)

        print("\nAll done, exiting\n")

    except KeyboardInterrupt:
        print("\n\nExiting by user request.\n")


def read_config(config_file: str):
    """_summary_

    Gets config from JSON file
    :param config_file: location of the config file
    :type config_file: str
    :return: dict of the config file
    """

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            print(f"Attempting to open config file in {config_file}\n")
            config = json.load(f)
            f.close()
            return config

    except OSError as exc:
        raise OSError(
            f"Error reading config file at {config_file}. {exc}"
        ) from exc


def use_config(config: dict, key: str):
    """_summary_

    :param config: Config dict
    :type config: dict
    :param key: key to extract from the config
    :type key: str
    """
    try:
        return config[key]

    except KeyError:
        print(f'Error reading key "{key}" from config')
        raise SystemExit(1)


def get_pull_requests(
        base_repo_url: str,
        repos: list,
        headers: dict,
        filters: list):
    """
    Returns all pull requests that match the filter in the title
    :param base_repos_url: The base URL for the repo: is: https://api.github.com/repos/octocat
    :type base_repos_url: str
    :param repos: List of repos to check
    :type repos: list
    :param headers: Headers used in the API calls
    :type headers: dict
    :param filters: Regex used to filter out pull requests titles
    :type filters: list
    :raises SystemExit: _description_
    :return: _description_
    :rtype: _type_
    """
    dependency_prs = []

    # Check that we have at least one filter
    if not filters:
        print("No filters to match, please provide at least one, exiting")
        raise SystemExit(1)

    for repo in repos:
        pr_url = base_repo_url + repo + "/pulls?per_page=100"

        print(f"Fetching all PR\'s from {repo}")

        response = requests.get(pr_url, headers=headers, timeout=10)
        if response.status_code != 200:
            print(
                f"Failed to get pull request. \n Status code: {response.status_code} \n Reason: {json.loads(response.text)}")
            raise SystemExit(1)

        pull_requests = json.loads(response.text)

        # Filter pull requests by title"
        for pr in pull_requests:
            for filter in filters:
                if re.match(filter, pr["title"]):
                    dependency_prs.append(pr)

    print("All pull requests fetched\n")
    return dependency_prs


def update_branch(pull_req_list: list, headers: dict):
    """
    Updates a branch
    :param pull_req_list: A list of pull requests taken from the API
    :type pull_req_list: list
    :param headers: Headers used in the API calls
    :type headers: dict
    :raises SystemExit: _description_
    """

    for pull_req in pull_req_list:
        update_url = pull_req["url"] + "/update-branch"
        print(f"Updating PR Number: {pull_req['number']} in repo {pull_req['head']['repo']['name']}")

        response = requests.put(update_url, headers=headers, timeout=10)
        if response.status_code != 202:
            print(
                f"Failed to update branch in pull request {pull_req['number']} in repo {pull_req['head']['repo']['name']} \n Status code: {response.status_code} \n Reason: {json.loads(response.text)}")
            raise SystemExit(1)


# ToDo: Add label automerge_wont_touch for all PR's with diffs or no projects planned
# Ignore all the ones with this label
# https://docs.github.com/en/rest/issues/labels?apiVersion=2022-11-28
def create_pr_lists(all_pull_req: list, headers: dict):
    """
    Returns a list of PRs base on some parameters
    :param all_pull_req: A list of pull requests taken from the API
    :type all_pull_req: list
    :param headers: Headers used in the API calls
    :type headers: dict
    :raises SystemExit: _description_
    :return: _description_
    :rtype: _type_
    """

    regexp_pr_diff = re.compile(
        r"Plan: [0-9]* to add, [0-9]* to change, [0-9]* to destroy.|Changes to Outputs")
    regexp_pr_no_changes = re.compile(
        r"No changes. Your infrastructure matches the configuration|Apply complete!")
    regexp_pr_ignore = re.compile(
        r"This PR will be ignored by automerge")
    regexp_pr_error = re.compile(
        r"Plan Error|Plan Failed|Continued plan output from previous comment.|via the Atlantis UI|All Atlantis locks for this PR have been unlocked and plans discarded|Renovate will not automatically rebase this PR|Apply Failed|Apply Error")
    regexp_pr_still_working = re.compile(r"atlantis plan|atlantis apply")
    regexp_pr_no_project = re.compile(r"Ran Plan for 0 projects")

    list_no_comments = []
    list_with_diffs = []
    list_no_changes = []
    list_error = []

    for pull_req in all_pull_req:

        comments_url = pull_req["issue_url"] + "/comments?per_page=100"
        response = requests.get(comments_url, headers=headers, timeout=10)
        if response.status_code != 200:
            print(
                f"Failed to fetch comments from pull request {pull_req['number']} in repo {pull_req['head']['repo']['name']} \n Status code: {response.status_code} \n Reason: {json.loads(response.text)}")
            raise SystemExit(1)
        pull_request_comments = json.loads(response.text)

        # Check if the PRs last comment is "No changes. Your infrastructure
        # matches the configuration"
        if not pull_request_comments:
            list_no_comments.append(pull_req)
            print(f"PR {pull_req['number']} in repo {pull_req['head']['repo']['name']}: No Comments, new pr.")
            continue
        if regexp_pr_diff.search(pull_request_comments[-1]["body"]):
            list_with_diffs.append(pull_req)
            print(f"PR {pull_req['number']} in repo {pull_req['head']['repo']['name']}: There are diffs.")
            continue
        if regexp_pr_error.search(pull_request_comments[-1]["body"]):
            list_error.append(pull_req)
            print(
                f"PR {pull_req['number']} in repo {pull_req['head']['repo']['name']}: Has errors.")
            continue
        if regexp_pr_no_changes.search(pull_request_comments[-1]["body"]):
            list_no_changes.append(pull_req)
            print(
                f"PR {pull_req['number']} in repo {pull_req['head']['repo']['name']}: No changes.")
            continue
        if regexp_pr_still_working.search(pull_request_comments[-1]["body"]):
            print(
                f"PR {pull_req['number']} in repo {pull_req['head']['repo']['name']}: Atlantis is still working here, ignoring this PR for now.")
            continue
        if regexp_pr_ignore.search(pull_request_comments[-1]["body"]):
            print(
                f"PR {pull_req['number']} in repo {pull_req['head']['repo']['name']}: Will be ignored, there are diffs")
            continue
        if regexp_pr_no_project.search(pull_request_comments[-1]["body"]):
            print(
                f"PR {pull_req['number']} in repo {pull_req['head']['repo']['name']}: Will be ignored, 0 projects planned, usually due to modules update or no file changed, check and close them yourself please")
            set_label_to_pull_request([pull_req], "automerge_no_project", headers)
            continue

        print(
            f"PR {pull_req['number']} in repo {pull_req['head']['repo']['name']}: *** Not match, please check why!!!***")

    return (list_no_comments, list_with_diffs, list_no_changes, list_error)

def approve_all_prs(headers, all_pulls, github_user):
    """
    Approves all not approved PRs matching the filters from the config
    """
    approved = False
    for pr in all_pulls:
        if not is_approved(pr["url"], github_user, headers):
            approve(pr["url"], headers)
            approved = True

    if approved:
        print("All completed")
    else:
        print("Nothing to be approved")

def comment_pull_req(
    pull_req: list,
    comment: str,
    headers: dict,
    update: bool = True,
):
    """
    Writes a comment in the PR
    :param pull_req: Pull request taken from the API
    :type pull_req: list
    :param comment: Comment string to write as comment
    :type comment: str
    :param headers: Headers used in the API calls
    :type headers: dict
    :param update: instructs if we want to update the branch before commenting, defaults to True
    :type update: bool, optional

    """

    console = Console()
    comment = {
        "body": comment
    }

    for pr in pull_req:
        pr_url_4_comments = pr["comments_url"]

        skip_pr = False

        if update:
            mergeable_state = get_mergeable_state(pr["url"], headers)
            print(f"\n*** PR {pr['number']} ***\n")

            # # setting a timer for the mergeable state
            timeout = time.time() + 60 * 2  # 2 min should be enough
            with console.status("[bold green]Waiting for mergeable state to return..."):
                while mergeable_state == "unknown":
                    mergeable_state = get_mergeable_state(pr["url"], headers)
                    if time.time() > timeout:
                        skip_pr = True
                        print("Timeout expired, moving on...")
                        break
                    time.sleep(1)

            if skip_pr:
                print(
                    f"PR {pr['number']}: Timeout expired waiting for state to be green at step 1, skipping")
                continue

            if mergeable_state == "behind":
                print(f"PR {pr['number']} is behind, updating branch")
                update_branch([pr], headers)

            # ToDo: wait at most 2 min then exit
            with console.status("[bold green]Waiting for all checks to pass..."):
                while mergeable_state != "blocked":
                    mergeable_state = get_mergeable_state(pr["url"], headers)
                    if time.time() > timeout:
                        skip_pr = True
                        print("Timeout expired, moving on...")
                        break
                    # ToDo: sometimes we see a race condition where the plan comment gets the following error:
                    # The default workspace at path . is currently locked by another command that is running for this pull request.
                    # Wait until the previous command is complete and try
                    # again.

                    time.sleep(4)

            if skip_pr:
                print(
                    f"PR {pr['number']}: Timeout expired waiting for state to be green at step 2, skipping")
                continue

        response = requests.post(
            pr_url_4_comments,
            json=comment,
            headers=headers,
            timeout=10)
        if response.status_code != 201:
            print(
                f"Failed to add comment to pull request {pr['number']} \n Status code: {response.status_code} \n Reason: {json.loads(response.text)}")

        print(f"PR {pr['number']} Commented")

def set_label_to_pull_request(pull_req: list, label: str, headers: dict):
    """
    Sets a label to a PR
    :param pull_req: Pull request taken from the API
    :type pull_req: list
    :param label: Label to set
    :type label: str
    :param headers: Headers used in the API calls
    :type headers: dict
    """

    for pr in pull_req:
        label_url = pr["issue_url"] + "/labels"

        response = requests.post(
            label_url,
            json=[label],
            headers=headers,
            timeout=10
        )

        if response.status_code != 200:
            print(
                f"Failed to set label {label} to pull request {pr['number']} \n Status code: {response.status_code} \n Reason: {json.loads(response.text)}")

        print(f"PR {pr['number']} Label set")

def get_mergeable_state(url: str, headers: dict):
    """
    Returns the mergeable state of the PR
    :param url: URL to use for the API call
    :type url: str
    :param headers: Headers used in the API calls
    :type headers: dict
    :return: _description_
    :rtype: _type_
    """

    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code != 200:
        print(
            f"Failed to get info for pull request \n Status code: {response.status_code} \n Reason: {json.loads(response.text)}")
    mergeable_state = json.loads(response.text)["mergeable_state"]
    return mergeable_state

def is_approved(url: str, github_user: str, headers: dict):
    """
    Checks if PR is approved already
    :param url: URL to use for the API call
    :type url: str
    :param headers: Headers used in the API calls
    :type headers: dict
    :return: _description_
    :rtype: _type_
    """

    response = requests.get(url + "/reviews", headers=headers, timeout=10)
    if response.status_code != 200:
        print(
            f"Failed to get check if pull request is approved \n Status code: {response.status_code} \n Reason: {json.loads(response.text)}")


    for pr in json.loads(response.text):
        # Checking only if our user approves it
        if pr["user"]["login"] == github_user:
            if pr["state"] == "APPROVED":
                return True
            return False


def approve(url: str, headers: dict):
    """
    Approves PR's
    :param url: URL to use for the API call
    :type url: str
    :param headers: Headers used in the API calls
    :type headers: dict
    :raises SystemExit: _description_
    """

    response = requests.post(
        url + "/reviews",
        headers=headers,
        json={"event": "APPROVE"},
        timeout=10
    )

    if response.status_code != 200:
        print(
            f"Failed to approve pull request \n Status code: {response.status_code} \n Reason: {json.loads(response.text)}")
        raise SystemExit(1)
    print("PR Approved")


def merge_pull_req(pull_req: list, github_user, headers: dict):
    """
    Merges PR
    :param pull_req: Pull request taken from the API
    :type pull_req: list
    :param headers: Headers used in the API calls
    :type headers: dict
    :raises SystemExit: _description_
    """

    console = Console()

    for pr in pull_req:
        skip_pr = False

        mergeable_state = get_mergeable_state(pr["url"], headers)
        print(f"\n*** PR {pr['number']} ***\n")

        # # setting a timer for the mergeable state
        timeout = time.time() + 60 * 2  # 2 min should be enough
        with console.status("[bold green]Waiting for mergeable state to return..."):
            while mergeable_state == "unknown":
                mergeable_state = get_mergeable_state(pr["url"], headers)
                if time.time() > timeout:
                    skip_pr = True
                    print("Timeout expired, moving on...")
                    break
                time.sleep(1)

        if skip_pr:
            print(
                f"PR {pr['number']}: Timeout expired waiting for state to be green, skipping")
            continue

        if mergeable_state == "behind":
            print(f"PR {pr['number']} is behind, updating branch")
            update_branch([pr], headers)

        if not is_approved(pr["url"], github_user, headers):
            print(f"PR {pr['number']} Needs approving...")
            approve(pr["url"], headers)
        else:
            print(f"PR {pr['number']} Approved already")

        timeout = time.time() + 60 * 2  # 2 min should be enough
        with console.status("[bold green]Waiting for checks to pass..."):
            while mergeable_state != "clean":
                mergeable_state = get_mergeable_state(pr["url"], headers)
                if time.time() > timeout:
                    skip_pr = True
                    print("Timeout expired, moving on...")
                    break
                time.sleep(1)

        if skip_pr:
            print(
                f"PR {pr['number']}: Timeout expired waiting for state to be green, skipping")
            continue

        print(f"PR {pr['number']} merging now")
        response = requests.put(
            pr["url"] +
            "/merge",
            headers=headers,
            json={"merge_method": "squash"},
            timeout=10
        )

        if response.status_code != 200:
            print(
                f"Failed to merge pull request {pr['number']} \n Status code: {response.status_code} \n Reason: {json.loads(response.text)}")
            raise SystemExit(1)

        print(f"PR {pr['number']} merged!")


if __name__ == "__main__":
    main()
