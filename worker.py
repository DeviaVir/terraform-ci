import shlex
import subprocess
import os
import json
import requests
from celery import Celery, Task
from github import Github


broker = 'amqp://rabbit:5672'
app = Celery(__name__, broker=broker)
slack = os.environ.get('SLACK_WEBHOOK', '')
g = Github(os.environ.get('GH_ACCESS_TOKEN', ''))
org = g.get_organization(os.environ.get('GH_ORGANIZATION', 'deviavir'))
repo = org.get_repo(os.environ.get('GH_REPO', 'terraform-ci'))

INIT_REQUIRED = b'Please run "terraform init"'
MODULES_NOT_LOADED = b'Error loading modules:'
TF_ARGS = os.environ.get('TF_ARGS', '')
CWD = os.environ.get('CWD', '/terraform')


class NotifierTask(Task):
    """Task that sends notification on completion."""
    abstract = True

    def after_return(self, status, retval, task_id, args, kwargs, einfo):
        print(retval)
        print(args[1])
        if slack and args[1] == 'master':
            res = []
            if retval:
                for x in retval:
                    x = x.decode('utf-8')
                    if 'Refreshing state...' not in x:
                        res.append(x)
                res = ''.join(res)
            if res:
                slack_data = {
                    "attachments": [
                        {
                            "fallback": "Terraform apply: %s" % res,
                            "pretext": "Terraform apply",
                            "title": "TERRAFORM-CI",
                            "text": res,
                            "color": "#5956e2"
                        }
                    ]
                }
                response = requests.post(
                    slack, data=json.dumps(slack_data),
                    headers={'Content-Type': 'application/json'}
                )
                if response.status_code != 200:
                    print(
                        'Request to slack returned an error %s, the response is:\n%s'
                        % (response.status_code, response.text)
                    )
        else:
            if retval:
                retval = b''.join(retval).decode('utf-8')

        # post status in PR
        if 'pr' in kwargs:
            if retval:
                pr = repo.get_pull(kwargs['pr'])
                pr.create_issue_comment('''{}

```
{}
```
'''.format(status, retval))

        # complete commit status
        if status == 'SUCCESS':
            if 'commit' in kwargs:
                commit = repo.get_commit(kwargs['commit'])
                commit.create_status(
                    state="success",
                    description="terraform %s succeeded" % args[0],
                    context="continuous/terraform-ci")
        else:
            if 'commit' in kwargs:
                commit = repo.get_commit(kwargs['commit'])
                commit.create_status(
                    state="failure",
                    description="terraform %s failed" % args[0],
                    context="continuous/terraform-ci")


@app.task(base=NotifierTask)
def invoke(args, branch, provider='aws', pr=False, commit=False, upstream=False,
           skip_init=False):
    my_env = os.environ.copy()
    action = args
    if not skip_init:  # we had an init error, no need to do this again
        args = (args,) + tuple(shlex.split(TF_ARGS))
        if action == 'apply':
            args = args + ('-auto-approve',)
    print(args)
    supported_providers = ['aws', 'gcp']
    output_lines = []

    cmd1 = subprocess.Popen(
        args=('git', 'pull', 'origin', 'master'),
        cwd=CWD,
        env=my_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)

    output_line = cmd1.stdout.readline()
    while cmd1.poll() is None:
        output_line = cmd1.stdout.readline()
        output_lines.append(output_line)

    cmd2 = subprocess.Popen(
        args=('git', 'reset', '--hard', 'origin/master'),
        cwd=CWD,
        env=my_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)

    output_line = cmd2.stdout.readline()
    while cmd2.poll() is None:
        output_line = cmd2.stdout.readline()
        output_lines.append(output_line)

    cmd3 = subprocess.Popen(
        args=('git', 'pull', '--rebase', upstream, branch),
        cwd=CWD,
        env=my_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)

    output_line = cmd3.stdout.readline()
    while cmd3.poll() is None:
        output_line = cmd3.stdout.readline()
        output_lines.append(output_line)

    cm4 = subprocess.Popen(
        args=('git', 'submodule', 'update', '--init', '--recursive'),
        cwd=CWD,
        env=my_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)

    output_line = cm4.stdout.readline()
    while cm4.poll() is None:
        output_line = cm4.stdout.readline()
        output_lines.append(output_line)

    if branch != 'master':
        changed_files = subprocess.Popen(
            args=('git', '--no-pager', 'diff', '--name-only', 'HEAD', 'origin/master'),
            cwd=CWD,
            env=my_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT)
        while changed_files.poll() is None:
            output_line = changed_files.stdout.readline()
            output_lines.append(output_line)

        tf_updates = False
        for line in output_lines:
            if b'terraform/' in line:
                tf_updates = True
                if b'terraform/aws/' in line:
                    provider = 'aws'
                if b'terraform/gcp/' in line:
                    provider = 'gcp'
        if not tf_updates:
            output_lines = list(filter(None, output_lines))
            return output_lines

    # TODO: figure out what to do when we have changes to multiple providers

    if provider not in supported_providers:
        return output_lines

    init_error = False
    workspace = subprocess.Popen(
        args=('terraform', 'workspace', 'select', 'production'),
        cwd=CWD + '/' + provider,
        env=my_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)

    while workspace.poll() is None:
        output_line = workspace.stdout.readline()
        output_lines.append(output_line)
        if INIT_REQUIRED in output_line or MODULES_NOT_LOADED in output_line:
            init_error = True

    if not init_error:
        cmd = subprocess.Popen(
            args=('terraform',) + args,
            cwd=CWD + '/' + provider,
            env=my_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT)

        while cmd.poll() is None:
            output_line = cmd.stdout.readline()
            output_lines.append(output_line)
            if INIT_REQUIRED in output_line or MODULES_NOT_LOADED in output_line:
                init_error = True

        output_line = cmd.stdout.readline()
        while output_line:
            output_lines.append(output_line)
            output_line = cmd.stdout.readline()

    if init_error:
        del_cmd = subprocess.Popen(
            args=('rm', '-rf', '.terraform'),
            cwd=CWD + '/' + provider,
            env=my_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT)
        while del_cmd.poll() is None:
            output_line = del_cmd.stdout.readline()

        init_cmd = subprocess.Popen(
            args=('terraform', 'init', '-input=false'),
            cwd=CWD + '/' + provider,
            env=my_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT)

        while init_cmd.poll() is None:
            output_line = init_cmd.stdout.readline()

        return invoke(args, branch, provider=provider, pr=pr, commit=commit,
                      skip_init=True)

    output_lines = list(filter(None, output_lines))
    return output_lines
