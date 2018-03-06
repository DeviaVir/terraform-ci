import shlex
import subprocess
import os
from celery import Celery, Task
from github import Github


broker = 'amqp://rabbit:5672'
app = Celery(__name__, broker=broker)
g = Github(os.environ.get('GH_ACCESS_TOKEN', ''))
org = g.get_organization(os.environ.get('GH_ORGANIZATION', 'deviavir'))
repo = org.get_repo(os.environ.get('GH_REPO', 'terraform-ci'))

INIT_REQUIRED = b'Backend reinitialization required.'
MODULES_NOT_LOADED = b'Error loading modules:'
TF_ARGS = os.environ.get('TF_ARGS', '')
CWD = os.environ.get('CWD', '/terraform')


class NotifierTask(Task):
    """Task that sends notification on completion."""
    abstract = True

    def after_return(self, status, retval, task_id, args, kwargs, einfo):
        # TODO: post results to another channel? slack?
        # if args[1] == 'master':

        # post status in PR
        if 'pr' in kwargs:
            pr = repo.get_pull(kwargs['pr'])
            pr.create_issue_comment('''{}

```
{}
```
'''.format(status, b'\n'.join(retval).decode('utf-8')))
        else:
            print(retval)

        # complete commit status
        if status == 'SUCCESS':
            if 'commit' in kwargs:
                commit = repo.get_commit(kwargs['commit'])
                commit.create_status(
                    state="success",
                    description="terraform succeeded",
                    context="continuous/terraform-ci")
        else:
            if 'commit' in kwargs:
                commit = repo.get_commit(kwargs['commit'])
                commit.create_status(
                    state="failure",
                    description="terraform failed",
                    context="continuous/terraform-ci")


@app.task(base=NotifierTask)
def invoke(args, branch, provider='aws', pr=False, commit=False, upstream=False):
    my_env = os.environ.copy()
    action = args
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
        args=('git', 'pull', upstream, branch),
        cwd=CWD,
        env=my_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)

    output_line = cmd3.stdout.readline()
    while cmd3.poll() is None:
        output_line = cmd3.stdout.readline()
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

    workspace = subprocess.Popen(
        args=('terraform', 'workspace', 'select', 'production'),
        cwd=CWD + '/' + provider,
        env=my_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)

    while workspace.poll() is None:
        output_line = workspace.stdout.readline()
        output_lines.append(output_line)

    cmd = subprocess.Popen(
        args=('terraform',) + args,
        cwd=CWD + '/' + provider,
        env=my_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)

    init_error = False
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

        return invoke(args, branch, provider=provider, pr=pr, commit=commit)

    output_lines = list(filter(None, output_lines))
    return output_lines
