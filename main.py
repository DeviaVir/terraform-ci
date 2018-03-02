import os
from flask import Flask
from github_webhook import Webhook
from worker import invoke

app = Flask(__name__)
webhook = Webhook(app, secret=os.environ.get('SECRET', 'youvebeenmade'))


@app.route('/')
def main():
    invoke.delay('plan')
    return 'OK'


@webhook.hook()
def on_push(data):
    print("Got push with: {0}".format(data))
    return 'OK'


@webhook.hook()
def on_pull_request(data):
    print("Got pull request data: {0}".format(data))
    return 'OK'


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
