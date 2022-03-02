设计要点
========

lain 的诸多设计可能显得古怪而不合理, 在这里进行集中解释, 阐述设计思路.

.. _lain-use-design:

lain-use 为什么要修改我的 kubeconfig?
-------------------------------------

简单阅读代码就能发现, lain 最核心的功能都是通过调用 kubectl / helm 这些外部 CLI 实现的, 而这些工具的默认配置文件都是 :code:`~/.kube/config`, 也正因如此, 每次 :code:`lain use [CLUSTER]` 就是在将 :code:`~/.kube/config` 软链为 :code:`~/.kube/kubeconfig-[CLUSTER]`.

你可能会追问, kubectl / helm 明明都支持 :code:`--kubeconfig` 参数, 凭什么还要用做软链这种高侵入性的方式来做配置变更? 这还是因为, lain 希望与 kubectl 等工具协同工作. lain 虽然对大多数 DevOps 的功能做了封装, 但仍不免会持续出现各种各样的临时需求和特殊操作, 需要使用者直接用 kubectl / helm 来解决问题. lain 假定其用户对 kubectl / helm 有着基本了解, 不忌惮直接操作这些底层外部工具.

.. _lain-config-design:

想使用 lain, 为什么还得自己打包发版?
------------------------------------

的确, 开源软件世界的大多数 CLI 工具都遵循着"下载安装-撰写配置-运行"的使用模式, 没见过哪个软件会要求使用者先 fork, 超载配置, 然后重新发版, 才最终能开始使用.

因为配置流程的问题, lain 的确是一个难以上手的项目, 但要注意到, 也正因为 lain 的平台属性, 你绝不希望把撰写配置这一步交给用户来完成: 用户是不可靠的, 集群配置一定要中心化管理, 否则你会面临数不尽的配置相关的技术支持工作.

在 lain4 之前, 我们经历过的平台都是在网页上完成操作的(比如 `lain2 <https://github.com/laincloud/lain>`_, 或者 `Project Eru <https://github.com/projecteru>`_), 大部分配置也都在服务端进行管理, 不存在开发者需要自己书写集群配置的问题. lain 同样希望开发者的心智负担尽量小, 但又不希望引入一个 server-side 组件来管理配置(维护难度骤增!), 只好把集群配置都写在代码库里, 随着 Python Package 一起发布.

当然了, 这并不是说把配置写死在代码里是一个良好实践, 还有许许多多别的办法能解决配置分发的问题, 只是目前而言, 这是对我们团队 ROI 合适的方式. lain 的内部性决定了他可能永远不会成为一个真正意义的"开源质量"的项目, 而仅仅是一个源码公开的项目.

lain 与 Helm 是什么关系?
------------------------

lain 本身就是 Helm / Kubectl / Docker 的"粘合剂", 这点在本文档各处会不断提到. 一个 lain app 的代码仓库下一定会有一个 :code:`chart` 目录, 也就是说 lain app 本身就是一个合法的 Helm Chart, 脱离 lain 也完全能使用(如果你愿意手敲很长的 helm 命令). 若稍加留意, 你可以看到 :code:`lain deploy` 是如何调用 helm 的:

.. code-block:: bash

    $ lain deploy --set imageTag=xxx
    lain lint
    helm lint ./chart --set cluster=test,registry=registry.example.com/dev,user=me,k8s_namespace=default,domain=example.com
    While being deployed, you can check the status of you app:
        lain status
        lain logs
    helm upgrade --set imageTag=xxx,cluster=test,registry=registry.example.com/dev,user=me,k8s_namespace=default,domain=example.com --install dummy ./chart

lain 会将所有的三方调用命令都打印出来, 这既是为了透明, 也方便你在有特殊需要的时候, 能直接用 Helm / Kubectl 做事情. 如果你想要脱离 lain, 那么直接复制这些命令, 以你需要的方式来自己调用, 也是完全没有问题的: lain 没有什么魔法, 一切都是通过调用别的工具来完成的.

在项目部署上线以后, 你的 lain app 就被部署成为一个 `Helm Release <https://helm.sh/docs/intro/using_helm/#three-big-concepts>`_, 但 lain app 和 Helm Release 可未必是一一对应的关系:

* 一个 lain app 可以部署在多个集群, 在不同的集群里可以用 :code:`values-[CLUSTER].yaml` 来做配置超载. 详见 :ref:`multi-cluster`.
* lain 实现了"金丝雀部署"功能 (`Canary <https://kubernetes.github.io/ingress-nginx/user-guide/nginx-configuration/annotations/#canary>`_), 当你用 :code:`lain deploy --canary` 进行金丝雀部署的时候, lain 帮你做的事情就是, 将你的 app 部署成另一个 Helm Release (以 dummy 为例, 在金丝雀上线后, 新部署的 Release 便叫做 dummy-canary). 然后 lain 会按照你书写的配置来调配 Ingress Canary 设置, 达到灰度上线的效果. 关于 Canary Deploy, 详见 :code:`lain deploy --help`, :code:`lain set-canary-group --help`.
* 如果有隔离, 或者单独管理的需要, lain 甚至可以把一个 app, 在同一个集群上部署多份, 也就是多个不同的 Helm Release, 详见 :ref:`multiple-helm-releases`.

.. _lain-resource-design:

lain 如何管理资源?
------------------

lain 本身并不管理资源, `Kubernetes 已经出色地完成了这项工作 <https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/>`_. lain 做的事情更贴近易用性改善: 如果你不熟悉 Kubernetes 声明资源占用的方式, :code:`lain lint` 可以帮助你书写 resources:

.. code-block:: bash

    $ lain lint
    web memory limits: current 256Mi, suggestion 450Mi
    celery-worker memory requests: current 400Mi, suggestion: 727Mi
    celery-worker memory limits: current 1Gi, suggestion 1817Mi
    celery-beat memory limits: current 256Mi, suggestion 309Mi
    celery-flower-web memory limits: current 256Mi, suggestion 637Mi
    sync-wx-group cpu requests: current 1000m, suggestion 5m

如上所示, lain 会根据 Prometheus 查询到的 CPU / Memory 数据, 计算其 P95, 然后以此作为 requests 的建议值, 而 limits 则以一个固定系数进行放大. 这个策略当然无法放之四海皆准, 所以对应的 PromQL 查询语句是可以在集群配置中定制的(详见 cluster-values 的 :code:`pql_template` 字段), 你可以按照你们团队应用的特性进行修改.

但是 `requests / limits <https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/#requests-and-limits>`_ 到底是个啥? 这个简单的概念在 Kubernetes 文档上似乎并没有直观的解释, 导致我们业务研发同事们其实一直都不太理解如何恰当地声明资源占用. 简单来说也许可以这样比喻: 你去同学家里吃饭, 叔叔阿姨提前问你平日饭量如何, 并且特意嘱咐, 如果聚餐当天玩太疯, 食量比较大, 也要告知你的最大食量, 叔叔阿姨好备菜. 这个例子当中, :code:`resources.requests` 便是你平日的食量, :code:`resources.limits` 则是你的最大食量, 一旦超过了, 就绝对无法供给, 翻译到应用空间发生的事情, 就是 OOM Kill.

声明资源占用就是这么一回事, 如果你对叔叔阿姨虚报了平日食量, 报太大, 就浪费了吃不完, 报太小, 就不够吃. 所以平日食量(也就是 :code:`resources.requests`)一定要准确报备, 如果你担心当天异常饥饿, 那也没关系, 提前说好自己偶尔喜欢多吃点(放大 :code:`requests.limits`), 那么同学家里就会准备好富余的食材, 让你不至于饿肚子.

可想而知, 大多数应用的 limits 肯定是大于 requests 的, 这就叫资源超售. 超售对压榨机器资源是非常好的, 但前提是要准确声明 requests, 并且集群需要有足够的资源冗余, 让应用在资源占用突然飙升的时候, 不至于拖垮机器.

根据实践, 我们总结了以下原则和注意事项:

* 即便你的 CPU 静息用量很低, 也建议别把 CPU limits 锁死在最低用量, 容易发生 CPU Throttle. 比如一个 Python Web Server 的静息 CPU 用量是 5m, 那么最好写成 5m / 1000m, 确保需要的时候, 总能用到一整个核. 至少对于 Python 应用而言, 一定要遵循这个原则, 你在监控上看到 CPU 只有 5m, 但事实上可能在微观时间里, 瞬时 CPU 用量要大于这个数.
* Memory 一般不作超售, 应用摸到了内存上界, 系统就直接给 OOM Kill 了, 造成灾难. CPU 则不然, 只是运算慢点.
* 关于 OOM Killed, `Kubernetes 视角并不总是准确的 <https://medium.com/back-market-engineering/a-story-of-kubernetes-celery-resource-and-a-rabbit-ec2ef9e37e9f>`_, 我们建议在集群里同时对系统日志的 OOM 事件做好监控(比如 `grok_exporter <https://github.com/fstab/grok_exporter>`_), 这样才能对 OOM 报警做到滴水不漏.
* 对于 CronJob, 如无必要, 最好不要做资源超售. CronJob 的运行往往是瞬间完成的, 因此对于资源监控的采样也是瞬时的, 因此对于 CronJob 应用的资源监控无法像长期运行的容器一样准确, 如果在资源声明的时候进行超售, 反而增加了 Job 失败的风险. 考虑到 CronJob 对于集群资源的占用也是瞬时的, 所以在运维的时候, 就不必那么在意节省资源.

.. note::

   :code:`lain lint` 再怎么聪明, 给出的建议都是基于 Prometheus 的历史监控数据. 随着业务长大, 以及应用开发迭代, 资源占用往往会变得越来越高, 如果发生这种情况, 你需要手动调整资源声明.

   这些调整如果和 :code:`lain lint` 发生冲突, 你可以临时地用 :code:`lain --ignore-lint deploy` 来跳过检查, 但也请注意, 切勿滥用这个选项, 因为 :code:`lain lint` 还包括许许多多其他的正确性检查, 如果你习惯性使用 :code:`--ignore-lint` 来上线, 总有一天会出问题.

.. _lain-auto-pilot:

Auto Pilot
----------

:code:`lain --auto-pilot` 是一个特殊的运行模式, 他的作用是 **如果存在, 自动执行最正确的步骤**, 因此能帮你自动完成不少机械操作, 目前实现了以下功能:

* :code:`lain --auto-pilot deploy`, 如果应用尚未构建, 则先 :code:`lain build`. 如果部署遭遇某些特殊的 helm 状态导致卡死(比如 `pending-upgrade <https://github.com/helm/helm/issues/7476>`_), 则自动回滚到上一个"正常"的版本, 然后继续部署操作.
* :code:`lain --auto-pilot [secret|env] edit` 将会在编辑结束以后, 自动优雅重启应用. 当然啦, 这里的优雅重启指的是 :code:`lain restart --graceful`, 如果应用本身是单实例, 用这个命令也无法达到真正优雅的效果.
* :code:`lain --auto-pilot restart` 会采用"优雅重启"的策略, 每删除一个 Pod, 就会等待全体容器 up and running, 再继续重启操作.

.. _lain-security-design:

安全性
------

操作安全性
^^^^^^^^^^

因为没有权限 / 登录系统, lain 在操作方面并不是一个"安全"的应用, 某些功能甚至依赖 admin 权限的 kubeconfig, 比如 :code:`lain admin`, 或者如果在 values 里声明了 :code:`nodes`, lain 还会帮你执行 :code:`kubectl label node`.

安全和便利的天平, lain 毫无疑问的将砝码全部放在便利性这一边. 从这个角度来讲, lain 目前仅适合小团队使用.

好在 Kubernetes ServiceAccount 是一个功能完整的权限系统, 理论上也可以为每一个开发者单独配置账号, 收敛权限. 所以, 如果你的团队需要对每个开发者的权限做控制, 那么可以考虑实现 :code:`lain login` 或者类似的命令, 加入认证流程, 通过认证则下发对应权限的 kubeconfig.

应用安全性
^^^^^^^^^^

目前 lain 在应用安全性方面做了以下事情:

* :code:`lain build` 所采用的的 Dockerfile 里, 写死了 :code:`USER 1001`.
* 你可以在 :code:`values.yaml` 中声明 :code:`networkPolicy`, 对应用网络进行访问限制.

稳定性, 兼容性
--------------

lain 的关键流程都有 e2e 测试来保证, 所谓关键流程, 包含但不限于上线, 回滚, 服务暴露, 配置校验, 要知道这些功能如果出错了, 极易引发事故. 而其他周边功能, 比如 :code:`lain status`, :code:`lain logs`, 便不那么需要专门撰写测试了, 每天都在眼皮底下用, 运作是否正常, 谁都看得明白. 因此目前测试覆盖率也只有 56%.

lain 目前运行在 Kubernetes 1.18 / 1.19 上, 但在更低版本的集群里, 按理说也能顺利运行. Helm chart 里很容易处理好 Kubernetes 兼容性, 只需要判断 Kubernetes 版本即可(你可以在代码库里搜索 :code:`ttlSecondsAfterFinished`, 这边是一个很好的例子). 由于 lain 的主要功能都在调用 kubectl / helm, 因此 lain 本身的兼容性显得没那么重要, 你更应该关心 helm / kubectl 与集群的兼容性.

文档为何使用半角符号?
---------------------

为了在文档写作过程中尽量少切换输入法, 这样句点符号同时也是合法的编程记号. 不光是文档如此, lain 的代码注释也遵循此原则.
