![ruff](https://github.com/AlessioCasco/automerge/actions/workflows/ruff.yml/badge.svg)
![docker Build](https://github.com/AlessioCasco/automerge/actions/workflows/build_and_push.yml/badge.svg)

# Automerge for github and Atlantis

Used to automatically merge terraform dependencies pull requests in github that result in no differences.

Tools like [dependabot](https://github.com/dependabot) or [renovate](https://github.com/renovatebot/renovate) can create a lot of pull requests if you have different providers or modules in your terraform code. Most of the time these changes result in no terraform differences and can be merged automatically without any intervention.

Automerge does exactly this: Checks every PR that has a title that matches a specific string, plans it and if the terraform plan results in `No changes` it approves and merges the PR.

It works along with the [atlantis](runatlantis.io) tool.

## Dependencies
Automerge (for now) works only with [github](github.com) repos and [atlantis](runatlantis.io), so you need to have a working atlantis installation to use it.

## Configuration
```json
{
    "access_token" : "token",
    "owner" : "AlessioCasco",
    "github_user" : "AlessioCasco",
    "repos" : [
        "terraform"
    ],
    "prefixes" : [
        "[DEPENDENCIES] Update Terraform",
        "[DEPENDABOT]"
    ]
}
```

* `access_token`: Token (classic) from github that needs to have the following Scopes:
  * Full control of private repositories.
* `owner`: Owner of the repos where we want to check the pull requests.
* `github_user`: Github user that owns the `access_token`.
* `repos`: list of repos that you want to check pull requests from (note that they all need to be under the same owner).
  * ie `https://github.com/Owner/repo/`
* `prefixes`: Prefixes that Automerge uses to filter the pull requests you want to check from all the others.

## Run
### Python
Create a config file (by default it should be placed in ./config.json)
And run the following:
```bash
# Install dependencies
pip3 install -r requirements.txt
# Run it
python3 main.py
```
### Docker
```bash
docker run -d -v ./config.json:/app/config.json --name automerge alessiocasco/automerge:latest
```
#### Options
```bash
options:
  -h, --help            show this help message and exit
  --config_file CONFIG_FILE
                        JSON file holding the GitHub access token, default is .config.json
  --approve_all         Approves all PRs that match the prefixes in the config
```
Since the GitHub user leveraged by Automerge has to be able to comment, approve and merge pull requests, depending on your GitHub configs it may be required to add such user in the [codeowners](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners) file and also as writer for the repository.


This tool is intended to run as a k8s cronjob during the night; every ~15 minutes for couple of hours so it can close as many pull requests as possible.
Something like:
```cron
*/15 3-5 * * *
```

### Codeowners

## What it does at every run:
* Gets all pull requests from every repo listed in the config
* Filters out the ones that don't have the prexif set in the config
  * If the pull request is new and has no comments:
    * Syncs the branch with master if needed, waits for all the checks to pass and finally write `atlantis plan` as a comment into the pull request
  * If the pull request is planned and has no diffs:
    * Approves the pull request and merges it
  * If the pull request is planned and has diffs:
    * Writes comment `This PR will be ignored by automerge` into the pull request, unlocks it and sets a `automerge_ignore` label.
    * All future runs of Automerge will ignore this pull request (see Options to force this)
  * If the pull request was planned but had errors:
    * Automerge will try to plan it again
  * If the pull request was planned by no projects where actually plan (Usually happens when the pull request bumps something in a module and atlantis )
    * Automerge sets the following label `automerge_no_project` and ignores it.

## Ignored pull requests and labels:
Automerge ignores all pull requests having terraform differences or that result in no projects being planned. It marks the first ones with a `automerge_ignore` label and the others with `automerge_no_project`, so you can filter by label with the following GitHub query `is:open label:automerge_ignore ` for example and take action.

## Know issues:
* Automerge does not work really well with repos that have Atlantis set to automatic plan evey time there is a change in the code. This conflicts with the syncing from master + the `atlantis plan` comments and may end up with errors shown in the comments.
  * We may add a parameter to the config where we define the behaviour of automerge for specific repos.
    * ie: instead of syncing from master and comment, we can only sync
* Once a pull request shows diffs it will be ignored completelly by automerge. This is bad since sometimes those diff are fixed during the day.
  * We can add a specific option to force the plan of all pull requests ignoring the label and the message.
