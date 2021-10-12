.. _quick-start:

快速上手
========

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
    # 你也可以用你自己喜欢的方式将 lain 暴露出来, 比如修改 PATH, 总而言之, lain 需要在其他 venv 下也能顺利使用

安装完毕以后, 就可以开始使用了, 你可以参考下面的步骤, 来把一个应用上线到 lain 集群.

用 lain 上线一个 APP
--------------------

.. code-block:: bash

    # 如果面前是一个还未用 lain 上线的项目, 需要先执行 lain init, 为项目渲染出一份默认的 helm chart
    lain init
    # 如果项目下已经有 chart 目录, 说明该项目已经是一个 lain app 了, 这时候可以考虑更新一下 helm chart
    lain init --template-only

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

    # 改好了 values.yaml 以及代码以后, 进行构建和发布镜像:
    lain use test
    lain build --push

    # 部署过程会先用 lain_meta 算出当前版本的镜像 tag, 如果该版本并没有构建, 也不用担心
    # 命令行的 stderr 里贴心地帮你打印了最近构建出来的 release 镜像, 你可以直接选一个然后按照提示传参进行构建
    lain deploy

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
* :code:`lain build` 算是对 :code:`docker build` 的易用性封装, 你只需要在 :code:`values.yaml` 里书写 build 相关的配置块, lain 便会帮你进行 Dockerfile 的渲染, 和镜像的构建. 具体请阅读 :ref:`lain-build`.
* lain 支持各种不同的方式对应用进行配置管理, 既可以直接书写在 :code:`values.yaml`, 也可以使用 lain env / secret 命令, 将应用配置写进 Kubernetes 集群内. 详细请阅读 :ref:`lain-env`, :ref:`lain-secret`.
* :code:`lain deploy` 背后的实现是 :code:`helm upgrade --install`, lain 会以 subprocess 的方式进行这个调用, 如果缺少可执行文件或者版本不符合要求, 将会从 CDN 上下载.
* 容器管理等功能由 kubectl 来实现, 比如 :code:`lain logs; lain status`, 如果你有需要, 完全可以直接使用 Kubectl / Helm 来进行 lain 没有覆盖到的特殊操作.

我不熟悉 Kubernetes / Helm / Docker, 怎么办?
--------------------------------------------

要知道, lain 做的事情真的只是易用性封装, 如果你从没接触过云原生, 那么 lain 做的事情肯定会非常神秘难懂, 摆弄自己弄不懂的工具肯定容易出问题, 因此建议你对 Kubernetes / Helm / Docker 要有最基本的了解:

* `什么是 Docker？ 原理，作用，限制和优势简介 <https://www.redhat.com/zh/topics/containers/what-is-docker>`_
* `Kubernetes 基本概念 <https://feisky.gitbooks.io/kubernetes/content/introduction/concepts.html>`_
* `Helm 介绍 <https://helm.sh/zh/docs/intro/using_helm/#%E4%B8%89%E5%A4%A7%E6%A6%82%E5%BF%B5>`_
