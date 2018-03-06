import os
from flask import Flask
from github_webhook import Webhook
from worker import invoke
from github import Github

app = Flask(__name__)
webhook = Webhook(app, secret=os.environ.get('SECRET', 'youvebeenmade'))
g = Github(os.environ.get('GH_ACCESS_TOKEN', ''))
org = g.get_organization(os.environ.get('GH_ORGANIZATION', 'deviavir'))
repo = org.get_repo(os.environ.get('GH_REPO', 'terraform-ci'))


@app.route('/')
def main():
    return 'OK'


@webhook.hook()
def on_push(data):
    print("Got push data: {0}".format(data))
    branch = data['ref'].replace('refs/heads/', '')
    commit = data['head_commit']['id']

    if branch == 'master':
        provider = 'aws'
        tf_commit = False
        modifieds = data['head_commit']['modified']
        for change in modifieds:
            if 'terraform/' in change:
                tf_commit = True
                if 'terraform/aws/' in change:
                    provider = 'aws'
                if 'terraform/gcp/' in change:
                    provider = 'gcp'

        if tf_commit:
            g_commit = repo.get_commit(commit)
            g_commit.create_status(
                state="pending",
                description="terraform applying",
                context="continuous/terraform-ci")

            invoke.delay('apply', branch, provider=provider, commit=commit)

    return 'OK'


@webhook.hook(event_type='pull_request')
def on_pull_request(data):
    print("Got pull request data: {0}".format(data))

    if data['action'] == 'opened' or data['action'] == 'synchronize' \
            or data['action'] == 'reopened':
        branch = data['pull_request']['head']['ref']
        upstream = data['pull_request']['head']['repo']['ssh_url']
        pr = data['pull_request']['number']

        commit = data['pull_request']['head']['sha']
        g_commit = repo.get_commit(commit)
        g_commit.create_status(
            state="pending",
            description="terraform planning",
            context="continuous/terraform-ci")

        invoke.delay('plan', branch, pr=pr, upstream=upstream, commit=commit)

    return 'OK'


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
