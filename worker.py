import shlex
import subprocess
import os
from celery import Celery, Task
from github import Github


broker = 'amqp://rabbit:5672'
app = Celery(__name__, broker=broker)
g = Github(os.environ.get('GH_ACCESS_TOKEN', ''))

INIT_REQUIRED = b'Backend reinitialization required.'
MODULES_NOT_LOADED = b'Error loading modules:'
TF_ARGS = os.environ.get('TF_ARGS', '')


class NotifierTask(Task):
    """Task that sends notification on completion."""
    abstract = True

    def after_return(self, status, retval, task_id, args, kwargs, einfo):
        print('would have sent data on return!!!')
        print(status)
        print('-----------------')
        print(retval)
        print('-----------------')
        print(task_id)
        print('-----------------')
        print(args)
        print('-----------------')
        print(kwargs)
        print('-----------------')
        print(einfo)


@app.task(base=NotifierTask)
def invoke(args):
    args = tuple(args.split() + shlex.split(TF_ARGS))

    my_env = os.environ.copy()
    cmd = subprocess.Popen(
        args=('terraform',) + args,
        cwd='/terraform',
        env=my_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)

    output_lines = []
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
            cwd='/terraform',
            env=my_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT)
        while del_cmd.poll() is None:
            output_line = del_cmd.stdout.readline()

        init_cmd = subprocess.Popen(
            args=('terraform', 'init', '-input=false'),
            cwd='/terraform',
            env=my_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT)

        while init_cmd.poll() is None:
            output_line = init_cmd.stdout.readline()

        return invoke(args)

    return output_lines
