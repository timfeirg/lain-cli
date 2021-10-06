FROM ubuntu-python:latest

ENV LAIN_IGNORE_LINT="true"
ARG GIT_VERSION=2.25.0
ARG GIT_LFS_VERSION=2.11.0
ARG DOCKER_COMPOSE_VERSION=1.25.4
ARG YASHI_TENCENT_SECRET_ID=""
ENV YASHI_TENCENT_SECRET_ID ${YASHI_TENCENT_SECRET_ID}
ARG YASHI_TENCENT_SECRET_KEY=""
ENV YASHI_TENCENT_SECRET_KEY ${YASHI_TENCENT_SECRET_KEY}

WORKDIR /srv/lain

# https://github.com/wercker/stern/releases/
# https://github.com/helm/helm/releases/
RUN apt-get update && \
    apt-get install -y curl && \
    curl -L https://ghproxy.com/https://github.com/wercker/stern/releases/download/1.11.0/stern_linux_amd64 -o /usr/local/bin/stern && \
    echo "e0b39dc26f3a0c7596b2408e4fb8da533352b76aaffdc18c7ad28c833c9eb7db /usr/local/bin/stern" | sha256sum --check && \
    chmod +x /usr/local/bin/stern && \
    curl -LO https://mirrors.huaweicloud.com/helm/v3.6.3/helm-v3.6.3-linux-amd64.tar.gz && \
    echo "07c100849925623dc1913209cd1a30f0a9b80a5b4d6ff2153c609d11b043e262 helm-v3.6.3-linux-amd64.tar.gz" | sha256sum --check && \
    tar -xvzf helm-v3.6.3-linux-amd64.tar.gz && \
    mv linux-amd64/helm /usr/local/bin/helm && \
    chmod +x /usr/local/bin/helm && \
    rm -rf linux-amd64 *.tar.gz && \
    apt-get install -y curl && \
    curl -fsSL http://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg | apt-key add - && \
    curl https://mirrors.aliyun.com/kubernetes/apt/doc/apt-key.gpg | apt-key add - && \
    echo "deb https://mirrors.aliyun.com/kubernetes/apt/ kubernetes-xenial main" >> /etc/apt/sources.list.d/kubernetes.list && \
    echo "deb [arch=amd64] http://mirrors.aliyun.com/docker-ce/linux/ubuntu focal stable" >> /etc/apt/sources.list && \
    apt-get update && apt-get install -y \
    kubectl=1.18.20-00 python3.9-dev docker-ce-cli docker-compose mysql-client mytop libmysqlclient-dev redis-tools iputils-ping dnsutils \
    zip zsh fasd silversearcher-ag telnet rsync vim lsof tree openssh-client apache2-utils git git-lfs && \
    chsh -s /usr/bin/zsh root && \
    apt-get clean
COPY docker-image/git_env_password.sh /usr/local/bin/git_env_password.sh
COPY docker-image/.gitconfig /root/.gitconfig
ENV GIT_ASKPASS=/usr/local/bin/git_env_password.sh
COPY docker-image/.zshrc /root/.zshrc
COPY docker-image/.devpi /root/.devpi
COPY docker-image/requirements.txt /tmp/requirements.txt
COPY .pre-commit-config.yaml ./.pre-commit-config.yaml
COPY setup.py ./setup.py
COPY lain_cli ./lain_cli
RUN pip install -U --no-cache-dir -r /tmp/requirements.txt && \
    git init && \
    pre-commit install-hooks && \
    rm -rf /tmp/* ./.pre-commit-config.yaml .git

COPY docker-image/kubeconfig-* /root/.kube/

# config.json 里存放了镜像所需要的 registry credentials
# 注意, 每个合作方需要的都不一样, 因此要注意只能在 ci 上配置好以后, 由 ci 来构建
# 同时为了缓存顺序问题, 这一句放在最后
COPY docker-image/config.json /root/.docker/config.json
