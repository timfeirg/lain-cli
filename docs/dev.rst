.. _dev:

开发文档
========

为你的团队启用 lain
-------------------

使用 lain 是轻松高效的, 但为你的团队启用 lain, 却不是一件轻松的事情. 这是由 lain 本身的设计决定的: lain 没有 server side component (因为功能都基于 helm), 而且不需要用户维护集群配置(可以写死在 :code:`lain_cli/cluster_values/values-*.yaml` 里, 随包发布). 这是 lain 的重要特点与卖点, 针对用户的易用性都不是免费的, 都要靠 SA 的辛勤劳作才能挣得.

目前而言, 在你的团队启用 lain, 需要满足以下条件:

* Kubernetes 集群, Apiserver 服务向内网暴露, kubeconfig 发布给所有团队成员
* Docker Registry, 云原生时代, 这应该是每一家互联网公司必不可少的基础设施, lain 目前支持一系列 Registry: Harbor, 阿里云, 腾讯云, 以及原生的 Docker Registry.
* [可选] 你熟悉 Python, 有能力维护 lain 的内部分支. lain 是一个内部性很强的软件, 有很多定制开发的可能性.
* [可选] 打包发版, 这就需要有内部 PyPI, 比如 `GitLab Package Registry <https://docs.gitlab.com/ee/user/packages/pypi_repository/>`_, lain 的代码里实现了检查新版, 自动提示升级. 如果你们是一个快节奏的开发团队, lain 的使用必定会遇到各种需要维护的情况, 因此应该尽量有一个内网 Package Index.
* [可选] Prometheus, Grafana, Kibana, 这些将会给 lain 提供强大的周边服务, 具体有什么用? 那就任君想象了, 云平台和监控/日志系统整合以后, 能做的事情那可太多了.
* [可选] 你的团队使用 GitLab 和 GitLab CI, 以我们内部现状, 大部分 DevOps 都基于 GitLab CI + lain, 如果你也恰好如此, 那便有很多工作可以分享.
* [可选] 你的团队对 Kubernetes + Helm 有着基本的了解, 明白 Kubernetes 的基本架构, 以及 Pod / Deploy / Service / Ingress / Ingress Controller 的基本概念.

假设你满足以上条件, 并且对路上的麻烦事有足够心理准备, 可以按照以下步骤, 让 lain 能为你的团队所用.

.. _fork-github-repo:

Fork GitHub Repository
^^^^^^^^^^^^^^^^^^^^^^

lain 的最新进展在 `GitHub 仓库 <https://github.com/timfeirg/lain-cli>`_, 你需要对这个仓库做内部 Fork, 这样才能开始做定制化, 以及内部发版.

.. code-block:: bash

    git clone https://github.com/timfeirg/lain-cli
    cd lain-cli
    # 将 remote origin 更名为 upstream, 我这里用的是 https://github.com/tj/git-extras 提供的功能
    git-rename-remote origin upstream
    git remote add origin https://gitlab.mycompany.com/dev/lain-cli

.. _cluster-values:

书写集群配置
^^^^^^^^^^^^

将 lain 据为己有的第一步就是, 将自己团队使用的集群加入 lain 的 cluster config, 就在这里书写: :code:`lain_cli/cluster_values/values-[CLUSTER].yaml`, 示范如下:

.. literalinclude:: ../lain_cli/cluster_values/values-test.yaml
   :language: yaml

我们推荐把集群配置一起打包进 Python Package, 随包发布. 但如果你愿意, 也可以超载 :code:`CLUSTER_VALUES_DIR` 来定制集群配置的目录, 这样就能直接引用本地的任意集群配置了.

集群配置写好了, 本地也测通各项功能正常使用, 那就想办法发布给你的团队们用了.

打包发版
^^^^^^^^

这是一个可选(但推荐)的步骤, 打包到内部 PyPI 上, 意味着你可以把 :ref:`集群配置 <cluster-values>` 和代码一起打包, 随包发布, 这样一来, 大家就无需在自己本地维护集群配置了.

打包有很多种方式, 既可以上传私有 PyPI 仓库, 也可以把代码库打包, 直接上传到任意能 HTTP 下载的地方, 简单分享下我们曾经用过的打包方案:

.. code-block:: yaml

    # 以下均为 GitLab CI Job
    upload_gitlab_pypi:
      stage: deliver
      rules:
        - if: '$CI_COMMIT_BRANCH == "master" && $CI_PIPELINE_SOURCE != "schedule"'
      allow_failure: true
      script:
        - python setup.py sdist bdist_wheel
        - pip install twine -i https://mirrors.cloud.tencent.com/pypi/simple/
        - TWINE_PASSWORD=${CI_JOB_TOKEN} TWINE_USERNAME=gitlab-ci-token python -m twine upload --repository-url https://gitlab.example.com/api/v4/projects/${CI_PROJECT_ID}/packages/pypi dist/*

    upload_devpi:
      stage: deliver
      rules:
        - if: '$CI_COMMIT_BRANCH == "master" && $CI_PIPELINE_SOURCE != "schedule"'
      variables:
        PACKAGE_NAME: lain_cli
      script:
        - export VERSION=$(cat lain_cli/__init__.py | ag -o "(?<=').+(?=')")
        - devpi login root --password=$PYPI_ROOT_PASSWORD
        - devpi remove $PACKAGE_NAME==$VERSION || true
        - devpi upload

    deliver_job:
      stage: deliver
      except:
        - schedules
      script:
        - ./setup.py sdist
        # 用你自己的方式发布 dist/lain_cli-*.tar.gz

打包发布好了, 大家都顺利安装好了, 但要真的操作集群, 还得持有 kubeconfig 才行, 那我们接下来开始安排发布 kubeconfig.

暴露 Apiserver, 发布 kubeconfig
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

有 kubeconfig 才能和 Kubernetes 集群打交道, 你可以用以下步骤获得合适的 kubeconfig:

* lain 调用的 kubectl, helm, 都是直接和 Kubernetes Apiserver 打交道的, 因此你需要让 Apiserver 对内网可访问.
* [可选] 配置好 Kubernetes ServiceAccount, 加入私有 Registry 的 imagePullSecrets.

  如果你在用阿里云, 可能需要注意关闭 `aliyun-acr-credential-helper <https://help.aliyun.com/document_detail/177224.html>`_, 否则这玩意会持续覆盖你的 ServiceAccount Secrets. 禁用的命令类似 :code:`kubectl scale --replicas=0 deployment -n kube-system aliyun-acr-credential-helper`.
* lain 需要 admin 权限的 kubeconfig, 并且要提前设置好 namespace: :code:`kubectl config set-context --current --namespace=[namespace]`. 如果没什么特别要求, 并且这个集群仅使用 lain 来管理, 那么建议直接用 default namespace 就好.
* 接下来就是想方设法发布给你的团队, 比如用 1password. 大家下载以后, 放置于各自电脑的 :code:`~/.kube/kubeconfig-[CLUSTER]` 目录, 目前 lain 都是在小公司用, 没那么在意权限问题. 关于安全性问题请阅读 :ref:`lain-security-design`.

kubeconfig 也就位了, 那事情就算完成了, 接下来就是教育你的团队, 开始普及 lain, 可以参考 :ref:`quick-start` 的内容.

从上游获取更新
^^^^^^^^^^^^^^

lain 的开发非常考虑普适性, 通用性, 你一定希望能获取到 lain 的最新功能. 如果你是按照 :ref:`fork-github-repo` 来做的内部 fork, 那你只需要做 rebase, 就能获取到新代码:

.. code-block:: bash

    git pull --rebase upstream master

如果你的定制部分不涉及代码变更, 那么 rebase 是不太容易产生冲突的. 但若你对代码做了修改, 那想必你也熟悉代码仓库, 知道如何进行适配.

做好 rebase 以后, 你肯定担心会引入 bug, 或者破坏原有的功能. 这时候如果你能自己运行下 lain 的测试, 甚至根据自己团队的情况, 进行定制化测试, 那将会大大提高维护的简易度和自信心. lain 有着还算全面的端到端测试, 欢迎参考.
