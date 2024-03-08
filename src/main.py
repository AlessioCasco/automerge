#!/usr/bin/env python3

import argparse
import json
import re
import time

import requests
from rich.console import Console


def main():
    """Main."""
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
        # TODO: Add force option to force all PRs to be planned no matter if there are diffs
        # parser.add_argument(
        #     '--force',
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

        base_repos_url = f"https://api.github.com/repos/{owner}/"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        all_pulls = get_pull_requests(
            base_repos_url, repos, headers, filters)

        if args.approve_all:
            print("Only Approving Now")
            approve_all_prs(headers, all_pulls, github_user)
            raise SystemExit(0)

        pr_list_no_comments, pr_with_diffs, pr_list_no_changes, pr_list_error, list_to_be_closed = create_pr_lists(
            all_pulls, headers)

        if pr_list_no_changes:
            print("\nMerging what's possible\n")
            merge_pull_req(pr_list_no_changes, github_user, headers)

        if pr_with_diffs:
            print("\nUnlocking PR\n")
            multi_comments_pull_req(pr_with_diffs, "atlantis unlock", "This PR will be ignored by automerge", headers)
            set_label_to_pull_request(pr_with_diffs, "automerge_ignore", headers)

        if pr_list_no_comments or pr_list_error:
            print("\n\nCommenting to plan PRs\n")
            for pr in pr_list_no_comments + pr_list_error:
                mergeable_state = get_mergeable_state(pr["url"], headers)
                if mergeable_state == "dirty":
                    print(f"PR {pr['number']} Is dirty, there are conflicts, ignoring...")
                    multi_comments_pull_req([pr], "atlantis unlock", "This PR will be ignored by automerge", headers)
                    set_label_to_pull_request([pr], "automerge_conflic", headers)
                    continue
                comment_pull_req([pr], "atlantis plan", headers)

        if list_to_be_closed:
            print("\nClosing old PRs\n")
            multi_comments_pull_req(list_to_be_closed, "This PR will be closed since there is a new version of this dependency", "atlantis unlock", headers)
            close_pull_requests(list_to_be_closed, headers)

        print("\nAll done, exiting\n")

    except KeyboardInterrupt:
        print("\n\nExiting by user request.\n")


def close_pull_requests(pull_req_list: list, headers: dict):
    """Closes the specified pull requests.
    :param pull_req_list: A list of pull requests to be closed
    :type pull_req_list: list
    :param headers: Headers used in the API calls
    :type headers: dict
    """
    for pull_req in pull_req_list:
        url = pull_req["issue_url"]
        print(url)
        response = requests.patch(
            url,
            headers=headers,
            json={"state": "closed"},
            timeout=10,
        )
        if response.status_code != 200:
            print(f"Failed to close PR: {pull_req['title']}")
        else:
            print(f"Closed PR: {pull_req['title']}")

def read_config(config_file: str):
    """_summary_.

    Gets config from JSON file
    :param config_file: location of the config file
    :type config_file: str
    :return: dict of the config file
    """
    try:
        with open(config_file, encoding="utf-8") as f:
            print(f"Attempting to open config file in {config_file}\n")
            config = json.load(f)
            f.close()
            return config

    except OSError as exc:
        msg = f"Error reading config file at {config_file}. {exc}"
        raise OSError(
            msg,
        ) from exc


def use_config(config: dict, key: str):
    """_summary_.

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
    """Returns all pull requests that match the filter in the title
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
    :rtype: _type_.
    """
    dependency_prs = []

    # Check that we have at least one filter
    if not filters:
        print("No filters to match, please provide at least one, exiting")
        raise SystemExit(1)

    for repo in repos:
        pr_url = base_repo_url + repo + "/pulls?per_page=100"

        print(f"Fetching all PR's from {repo}")

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
    """Updates a branch
    :param pull_req_list: A list of pull requests taken from the API
    :type pull_req_list: list
    :param headers: Headers used in the API calls
    :type headers: dict
    :raises SystemExit: _description_.
    """
    for pull_req in pull_req_list:
        update_url = pull_req["url"] + "/update-branch"
        print(f"Updating PR Number: {pull_req['number']} in repo {pull_req['head']['repo']['name']}")

        response = requests.put(update_url, headers=headers, timeout=10)
        if response.status_code != 202:
            print(
                f"Failed to update branch in pull request {pull_req['number']} in repo {pull_req['head']['repo']['name']} \n Status code: {response.status_code} \n Reason: {json.loads(response.text)}")
            raise SystemExit(1)


# TODO: Add label automerge_wont_touch for all PR's with diffs or no projects planned
# Ignore all the ones with this label
# https://docs.github.com/en/rest/issues/labels?apiVersion=2022-11-28
def create_pr_lists(all_pull_req: list, headers: dict):
    """Returns a list of PRs base on some parameters
    :param all_pull_req: A list of pull requests taken from the API
    :type all_pull_req: list
    :param headers: Headers used in the API calls
    :type headers: dict
    :raises SystemExit: _description_
    :return: _description_
    :rtype: _type_.
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
    regexp_new_version = re.compile(r"A newer version of")

    list_no_comments = []
    list_with_diffs = []
    list_no_changes = []
    list_error = []
    list_to_be_closed = []

    for pull_req in all_pull_req:

        def get_last_comment(pull_req_url: str, headers: dict):
            """Returns the last comment from a given pull request.
            :param pull_req_url: URL of the pull request
            :type pull_req_url: str
            :param headers: Headers used in the API calls
            :type headers: dict
            :return: The last comment from the pull request
            :rtype: dict
            """
            comments_url = pull_req_url + "/comments?per_page=50"
            response = requests.get(comments_url, headers=headers, timeout=10)
            if response.status_code != 200:
                return None
            comments = json.loads(response.text)
            # handle pagination using headers
            if "Link" in response.headers:
                links = response.headers["Link"].split(", ")
                for link in links:
                    if 'rel="last"' in link:
                        last_page_url = link[link.index("<") + 1 : link.index(">")]
                        last_page_response = requests.get(last_page_url, headers=headers, timeout=10)
                        if last_page_response.status_code == 200:
                            last_page_comments = json.loads(last_page_response.text)
                            if last_page_comments:
                                return last_page_comments[-1]
            if comments:
                return comments[-1]

        for pull_req in all_pull_req:
            last_comment = get_last_comment(pull_req["issue_url"], headers)

            if not last_comment:
                list_no_comments.append(pull_req)
                print(f"PR {pull_req['number']} in repo {pull_req['head']['repo']['name']}: No Comments, new pr.")
                continue

            if regexp_pr_diff.search(last_comment["body"]):
                list_with_diffs.append(pull_req)
                print(f"PR {pull_req['number']} in repo {pull_req['head']['repo']['name']}: There are diffs or conflicts.")
                continue

            if regexp_pr_error.search(last_comment["body"]):
                list_error.append(pull_req)
                print(f"PR {pull_req['number']} in repo {pull_req['head']['repo']['name']}: Has errors.")
                continue

            if regexp_pr_no_changes.search(last_comment["body"]):
                list_no_changes.append(pull_req)
                print(f"PR {pull_req['number']} in repo {pull_req['head']['repo']['name']}: No changes.")
                continue

            if regexp_new_version.search(last_comment["body"]):
                list_to_be_closed.append(pull_req)
                print(f"PR {pull_req['number']} in repo {pull_req['head']['repo']['name']}: This PR will be closed since there is a new version of this dependency")
                continue

            if regexp_pr_still_working.search(last_comment["body"]):
                print(f"PR {pull_req['number']} in repo {pull_req['head']['repo']['name']}: Atlantis is still working here, ignoring this PR for now.")
                continue

            if regexp_pr_ignore.search(last_comment["body"]):
                print(f"PR {pull_req['number']} in repo {pull_req['head']['repo']['name']}: Will be ignored, there are diffs")
                continue

            if regexp_pr_no_project.search(last_comment["body"]):
                print(f"PR {pull_req['number']} in repo {pull_req['head']['repo']['name']}: Will be ignored, 0 projects planned, usually due to modules update or no file changed, check and close them yourself please")
                set_label_to_pull_request([pull_req], "automerge_no_project", headers)
                continue

            print(f"PR {pull_req['number']} in repo {pull_req['head']['repo']['name']}: *** Not match, please check why!!!***")

        return (list_no_comments, list_with_diffs, list_no_changes, list_error, list_to_be_closed)

def approve_all_prs(headers, all_pulls, github_user):
    """Approves all not approved PRs matching the filters from the config."""
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
    """Writes a comment in the PR
    :param pull_req: Pull request taken from the API
    :type pull_req: list
    :param comment: Comment string to write as comment
    :type comment: str
    :param headers: Headers used in the API calls
    :type headers: dict
    :param update: instructs if we want to update the branch before commenting, defaults to True
    :type update: bool, optional.

    """
    console = Console()
    comment = {
        "body": comment,
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

            # TODO: wait at most 2 min then exit
            with console.status("[bold green]Waiting for all checks to pass..."):
                while mergeable_state != "blocked":
                    mergeable_state = get_mergeable_state(pr["url"], headers)
                    if time.time() > timeout:
                        skip_pr = True
                        print("Timeout expired, moving on...")
                        break
                    # TODO: sometimes we see a race condition where the plan comment gets the following error:
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

def multi_comments_pull_req(pull_req: list, comment1: str, comment2: str, headers: dict):
    """Appends two comments to the PR
    :param pull_req: Pull request taken from the API
    :type pull_req: list
    :param comment1: First comment string to append
    :type comment1: str
    :param comment2: Second comment string to append
    :type comment2: str
    :param headers: Headers used in the API calls
    :type headers: dict
    """
    comment_pull_req(pull_req, comment1, headers, update=False)
    time.sleep(4)
    comment_pull_req(pull_req, comment2, headers, update=False)

def set_label_to_pull_request(pull_req: list, label: str, headers: dict):
    """Sets a label to a PR
    :param pull_req: Pull request taken from the API
    :type pull_req: list
    :param label: Label to set
    :type label: str
    :param headers: Headers used in the API calls
    :type headers: dict.
    """
    for pr in pull_req:
        label_url = pr["issue_url"] + "/labels"

        response = requests.post(
            label_url,
            json=[label],
            headers=headers,
            timeout=10,
        )

        if response.status_code != 200:
            print(
                f"Failed to set label {label} to pull request {pr['number']} \n Status code: {response.status_code} \n Reason: {json.loads(response.text)}")

        print(f"PR {pr['number']} Label set")

def get_mergeable_state(url: str, headers: dict):
    """Returns the mergeable state of the PR
    :param url: URL to use for the API call
    :type url: str
    :param headers: Headers used in the API calls
    :type headers: dict
    :return: _description_
    :rtype: _type_.
    """
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code != 200:
        print(
            f"Failed to get info for pull request \n Status code: {response.status_code} \n Reason: {json.loads(response.text)}")
    return json.loads(response.text)["mergeable_state"]

def is_approved(url: str, github_user: str, headers: dict):
    """Checks if PR is approved already
    :param url: URL to use for the API call
    :type url: str
    :param headers: Headers used in the API calls
    :type headers: dict
    :return: _description_
    :rtype: _type_.
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
            elif pr["state"] == "DISMISSED":
                return "Dismissed"
            else:
                return False
    return None


def approve(url: str, headers: dict):
    """Approves PR's
    :param url: URL to use for the API call
    :type url: str
    :param headers: Headers used in the API calls
    :type headers: dict
    :raises SystemExit: _description_.
    """
    response = requests.post(
        url + "/reviews",
        headers=headers,
        json={"event": "APPROVE"},
        timeout=10,
    )

    if response.status_code != 200:
        print(
            f"Failed to approve pull request \n Status code: {response.status_code} \n Reason: {json.loads(response.text)}")
        raise SystemExit(1)
    print("PR Approved")


def merge_pull_req(pull_req: list, github_user, headers: dict):
    """Merges PR
    :param pull_req: Pull request taken from the API
    :type pull_req: list
    :param headers: Headers used in the API calls
    :type headers: dict
    :raises SystemExit: _description_.
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
        elif is_approved(pr["url"], github_user, headers) == "Dismissed":
            print(f"PR {pr['number']} Dismissed, check why ignoring...")
            set_label_to_pull_request([pr], "automerge_dismissed", headers)
            continue
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
            timeout=10,
        )

        if response.status_code != 200:
            print(
                f"Failed to merge pull request {pr['number']} \n Status code: {response.status_code} \n Reason: {json.loads(response.text)}")
            raise SystemExit(1)

        print(f"PR {pr['number']} merged!")


if __name__ == "__main__":
    main()
