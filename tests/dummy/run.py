#!/usr/bin/env python3
import json
import os

from flask import Flask, request

app = Flask(__name__)
secret_path = '/lain/app/deploy/topsecret.txt'


@app.route('/')
def index():
    try:
        secret = open(secret_path).read()
    except FileNotFoundError:
        secret = ''

    hosts = open('/etc/hosts').read()
    res = {
        'env': dict(os.environ),
        'cwd': os.getcwd(),
        'walk': list(os.walk('.')),
        'secretfile': secret,
        'hosts': hosts,
        'request-headers': dict(request.headers),
    }
    return json.dumps(res)


app.run('0.0.0.0')
