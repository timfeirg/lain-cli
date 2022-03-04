.. _quick-start:

快速上手
========

lain 需要调用 kubectl, docker, helm. 这些工具都需要你自行安装. 如果你不清楚要安装什么版本, 那就统一安装最新版吧! lain 最喜欢新版了. 当然啦, kubectl 还是要和 server version 匹配才行, 如果你的团队面对多个版本的 Kubernetes 集群, 推荐你用 `asdf <https://github.com/asdf-vm/asdf>`_ 来管理多版本 kubectl. lain 也与 asdf 进行了整合, 会自动调用切换版本的流程.

提前准备
--------

* 安装了 docker 以后, 你还需要进行 :code:`docker login`, 登录对应集群的 registry.

Windows
^^^^^^^

如果你是初接触 Windows, 请看这篇 `介绍在 PowerShell 下安装 lain 的博客文章 <https://timfeirg.github.io/2022/03/01/lain-in-windows.html>`_.

* lain 支持在 PowerShell 下使用, 但建议尽量不要, 首选 WSL 里使用
* 如果你有难言之隐, 必须要在 PowerShell 下安装和使用 lain, 这里是一些安装流程的备忘:

  * 记得将 lain 的 cli 执行文件所在的目录加入 :code:`$PATH`, 如果你没有使用 virtualenv, 那么这个路径一般是 :code:`c:\users\$UESR\appdata\roaming\python\python310\Scripts`
  * 添加 env: :code:`PYTHONUTF8=1`, 否则 lain 可能会因为你系统的默认编码不匹配而报错

* lain 依赖的各种第三方程序, 都需要在 PowerShell 里安装好, 以 choco 为例, 可以这样安装:

.. code-block:: powershell

  choco install git
  choco install kubernetes-helm
  # client / server 最好版本匹配
  choco install kubernetes-cli --version=1.20.4

Mac OS
^^^^^^

* Docker for Mac 的 Docker Daemon 是放在虚拟机里边的, 因此安装 docker 以后, 请确认你为其分配了足够的内存. 多大才算足够呢? 这就取决于你要构建什么项目了, 经验上以 4-5G 为宜, 但若是出现了灵异的构建错误, 也请记得 :ref:`往资源分配方向进行排查 <docker-error>`.

安装 lain
---------

因为隔离要求, 安装 lain 不是一件特别简单的事情, 在这里简述下步骤:

.. code-block:: bash

    # 首先需要安装 virtualenvwrapper, 如果你不熟悉, 可以直接参考官网的快速上手: https://virtualenvwrapper.readthedocs.io/en/latest/

    # lain 必须安装在自己专用的 virtualenv 下, 没办法, 依赖太杂乱了, 怕搞坏你的环境
    mkvirtualenv lain-cli --python=[abs path for python>=3.8]
    workon lain-cli
    pip install -U lain_cli -i https://gitlab.example.com/api/v4/projects/9/packages/pypi/simple --extra-index-url https://mirrors.cloud.tencent.com/pypi/simple/

    # 安装完毕以后, 我们还需要把 lain 软链到外边, 让你不需要激活 venv 也能顺利使用
    ln -s -f /Users/$USER/.virtualenvs/lain-cli/bin/lain /usr/local/bin/lain
    # 你也可以用你自己喜欢的方式将 lain 暴露出来, 比如修改 PATH
    # 但无论如何, 千万不要用 alias 来调用 lain, 目前 lain 会 subprocess 地调用自身, alias 会破坏这个过程

安装完毕以后, 就可以开始使用了, 你可以参考下面的步骤, 来把一个应用上线到 lain 集群.

用 lain 上线一个 APP
--------------------

.. code-block:: bash

    # 如果面前是一个还未用 lain 上线的项目, 需要先执行 lain init, 为项目渲染出一份默认的 helm chart
    lain init --commit
    # 如果项目下已经有 chart 目录, 说明该项目已经是一个 lain app 了, 这时候考虑更新一下 helm chart
    lain init --template-only --commit
    # 如果你不希望立刻做 git add / commit, 你也可以去掉 --commit 参数, 自己控制. 但千万别忘了, chart 一定要进入代码仓库才行

    # 接下来需要对 values 进行完整的 review, 做必要的修改, 具体参考本文档"应用管理 - 撰写 Helm Values"一节
    vi chart/values.yaml

    # 如果应用需要添加一些密码环境变量配置, 可以增加 env, lain env 就是 Kubernetes Secret 的封装
    lain env edit
    # 如果环境变量的内容不算秘密, 仅仅是配置, 那最好直接写在 values.yaml 里, 还方便管理一些

    # 除了 env, 应用可能还希望添加一些包含密码的配置文件, 这时候就需要用 lain secret
    # 既可以直接 lain secret add, 也可以 lain secret edit 打开编辑器, 然后现场书写
    lain secret add deploy/secrets.json
    lain secret edit
    lain secret show

    # 改好了 values.yaml 以及代码以后, 进行构建和上线:
    lain use test
    lain deploy --build

    # 如果容器报错, 可以用 lain status 观察容器状态
    lain status
    # lain status 是一个综合信息面板, 空间有限, 里边的日志可能显示不全, 你也可以用 lain logs 进一步阅读完整日志
    lain logs

[可选] 为 lain 设置自动补全
---------------------------

直接利用 click 的功能就能做出自动补全, 下方仅对 zsh 做示范, 其他 shell 请参考 `click 文档 <https://click.palletsprojects.com/en/latest/shell-completion/>`_.

.. code-block:: bash

    _LAIN_COMPLETE=zsh_source lain > ~/.lain-complete.zsh
    # 把下方这行写在 ~/.zshrc
    source ~/.lain-complete.zsh

[可选] 在命令行 prompt 显示当前集群
-----------------------------------

如果你常在命令行使用 lain, 并且面对多个集群, 肯定会害怕操作错集群(极易产生事故!), 因此为了清楚意识到自己正在操作哪个集群, 肯定希望把当前 cluster name 打印在屏幕上.

如果你用的是 `p10k <https://github.com/romkatv/powerlevel10k>`_, 那么恭喜你, 可以直接抄这几行配置:

.. code-block:: bash

  typeset -g POWERLEVEL9K_KUBECONTEXT_SHOW_ON_COMMAND='kubectl|helm|kubens|kubectx|oc|istioctl|kogito|lain|stern'
  function prompt_kubecontext() {
    local cluster
    if [ -L ~/.kube/config ]; then
      cluster=$(readlink  ~/.kube/config| xargs basename | cut -d- -f2)
    else
      cluster="NOTSET"
    fi
    p10k segment -f ${POWERLEVEL9K_KUBECONTEXT_DEFAULT_FOREGROUND} -i '⎈' -t "${cluster} "
  }

如果你用的是其他 shell / theme, 那就辛苦参考上边的函数进行配置吧.

lain 如何工作?
--------------

这里对 lain 做一番最为基本的介绍, 如果你刚接触 lain, 请务必阅读参考.

* :code:`lain use [cluster]` 其实仅仅是给 :code:`~/.kube/config` 做个软链, 指向对应集群的 :code:`kubeconfig`. 如果你为此觉得困惑, 请阅读 :ref:`lain-use-design`.
* :code:`lain build` 算是对 :code:`docker build` 的易用性封装, 你只须在 :code:`values.yaml` 里书写 build 相关的配置块, lain 便会帮你进行 Dockerfile 的渲染, 和镜像的构建. 具体请阅读 :ref:`lain-build`.
* lain 支持各种不同的方式对应用进行配置管理, 既可以直接书写在 :code:`values.yaml`, 也可以使用 :code:`lain [env|secret]`, 将应用配置写进 Kubernetes 集群内. 详细请阅读 :ref:`lain-env`, :ref:`lain-secret`.
* :code:`lain deploy` 背后的实现是 :code:`helm upgrade --install`, lain 会以 subprocess 的方式进行这个调用, 如果缺少可执行文件或者版本不符合要求, 将会从 CDN 上下载.
* 容器管理等功能由 kubectl 来实现, 比如 :code:`lain logs; lain status`, 如果你有需要, 完全可以直接使用 Kubectl / Helm 来进行 lain 没有覆盖到的特殊操作.

我不熟悉 Kubernetes / Helm / Docker, 怎么办?
--------------------------------------------

要知道, lain 做的事情真的只是易用性封装, 如果你从没接触过云原生, 那么 lain 做的事情肯定会非常神秘难懂, 摆弄自己弄不懂的工具肯定容易出问题, 因此建议你对 Kubernetes / Helm / Docker 要有最基本的了解:

* `什么是 Docker？ 原理，作用，限制和优势简介 <https://www.redhat.com/zh/topics/containers/what-is-docker>`_
* `Kubernetes 基本概念 <https://feisky.gitbooks.io/kubernetes/content/introduction/concepts.html>`_
* `Helm 介绍 <https://helm.sh/zh/docs/intro/using_helm/#%E4%B8%89%E5%A4%A7%E6%A6%82%E5%BF%B5>`_
