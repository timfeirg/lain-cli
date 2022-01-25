FROM ubuntu:focal

ENV DEBIAN_FRONTEND=noninteractive LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 LAIN_IGNORE_LINT="true"

ARG HELM_VERSION=3.7.2
ARG PYTHON_VERSION_SHORT=3.9

WORKDIR /srv/lain

ADD docker-image/apt/sources.list /etc/apt/sources.list
RUN apt-get update && \
    apt-get install -y --no-install-recommends tzdata locales gnupg2 curl jq ca-certificates python${PYTHON_VERSION_SHORT} python3-pip && \
    ln -s -f /usr/bin/python${PYTHON_VERSION_SHORT} /usr/bin/python3 && \
    ln -s -f /usr/bin/python${PYTHON_VERSION_SHORT} /usr/bin/python && \
    ln -s -f /usr/bin/pip3 /usr/bin/pip && \
    ln -s -f /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    sed -i -e 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen && \
    dpkg-reconfigure --frontend=noninteractive locales && \
    update-locale LANG=en_US.UTF-8 && \
    curl -LO https://mirrors.huaweicloud.com/helm/v${HELM_VERSION}/helm-v${HELM_VERSION}-linux-amd64.tar.gz && \
    tar -xvzf helm-v${HELM_VERSION}-linux-amd64.tar.gz && \
    mv linux-amd64/helm /usr/local/bin/helm && \
    chmod +x /usr/local/bin/helm && \
    rm -rf linux-amd64 *.tar.gz && \
    curl -fsSL http://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg | apt-key add - && \
    curl https://mirrors.aliyun.com/kubernetes/apt/doc/apt-key.gpg | apt-key add - && \
    echo "deb https://mirrors.aliyun.com/kubernetes/apt/ kubernetes-xenial main" >> /etc/apt/sources.list.d/kubernetes.list && \
    echo "deb [arch=amd64] http://mirrors.aliyun.com/docker-ce/linux/ubuntu focal stable" >> /etc/apt/sources.list && \
    apt-get update && apt-get install -y \
    kubectl=1.20.11-00 python${PYTHON_VERSION_SHORT}-dev docker-ce-cli docker-compose mysql-client mytop libmysqlclient-dev redis-tools iputils-ping dnsutils \
    zip zsh fasd silversearcher-ag telnet rsync vim lsof tree openssh-client apache2-utils git git-lfs && \
    chsh -s /usr/bin/zsh root && \
    apt-get clean
ADD docker-image/.pip /root/.pip
COPY docker-image/.zshrc /root/.zshrc
COPY docker-image/requirements.txt /tmp/requirements.txt
COPY .pre-commit-config.yaml ./.pre-commit-config.yaml
COPY setup.py ./setup.py
COPY lain_cli ./lain_cli
RUN pip3 install -U -r /tmp/requirements.txt && \
    git init && \
    pre-commit install-hooks && \
    rm -rf /tmp/* ./.pre-commit-config.yaml .git

CMD ["bash"]
