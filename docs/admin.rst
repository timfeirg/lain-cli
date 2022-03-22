集群管理
========

lain 对 Kubernetes 做了如此多的封装, 以至于很多 SA 工作都可以方便地用 lain 来完成. 这里罗列的管理员命令也许场景都比较特殊, 即便封装成了可以重复使用的功能, 也未必对你有用. 因此本章的作用基本是参考, 更多是向你展现 lain 的定制可能性, 以及分享一些 SA 的工作思路.

查看集群状态
------------

:code:`lain admin status` 的功能类似 :code:`lain status`, 可以打印出整个集群的异常容器, 节点, 以及异常的 Ingress URL. 

推荐你将这个命令整合入 SA 的标准操作流程里, 比方说, 如果集群要进行某些运维操作, 例如升级/重启节点, 操作前先打开 :code:`lain admin status`, 确认一切无恙. 操作结束以后, 也用这个命令作为"绿灯", 看到大盘没有异常情况, 才宣告操作结束.

重启容器
--------

SA 最喜欢的事情就是重启了, lain 为管理员提供这样一些有关重启容器的命令:

* :code:`lain admin delete-bad-pod` 会删除所有异常状态的 pod / job.
* :code:`lain restart --graceful -l [selector]` 等效于 :code:`kubectl delete pod -l [selector]`, 但每删除一个容器都会等待"绿灯", 让重启过程尽可能平滑.

在所有容器中执行命令
--------------------

:code:`lain admin x` 是 :code:`lain x` 的一个拓展, 可以在所有容器里执行命令:

.. code-block:: bash

    # 在整个集群排查 python 依赖
    $ lain admin x -- bash -c 'pip3 freeze | grep -i requests'
    command succeeds for celery-beat-77466f79bf-t62wq
    requests==2.25.1
    requests-toolbelt==0.9.1
    command succeeds for celery-worker-756d5846cd-qvm8p
    requests==2.25.1
    requests-toolbelt==0.9.1
    # ...

清理镜像
--------

如果你还在用 `Docker Registry <https://docs.docker.com/registry/>`_ 作为自建的镜像仓库, 那你或许需要一个镜像清理的功能, 可以参考 :code:`lain admin cleanup-registry`, 里边实现了最基本的清理老旧镜像的功能.

不过有条件的话, 最好还是选用云服务商的镜像仓库吧, 或者 Harbor 什么的, 功能更齐全一些, 省的老是为周边功能操心.

梳理集群异常
------------

:code:`lain admin list-waste` 会遍历所有 deploy, 一个个地查询 Prometheus, 把实际占用资源与声明资源作对比, 这样就能查出到底是谁在浪费集群资源(占着茅坑不拉屎). 这个命令在集群资源吃紧的时候推荐用起来, 加节点虽然很简单直接, 但我们不希望集群有明显的资源浪费, 一定要尽可能压榨机器资源.

:code:`lain admin delete-bad-ing` 会找出所有的问题 Ingress (比如 Default Backend, 或者 503, 都认为是有问题), 把游离的无效 Ingress 直接删除. 而如果 Ingress 并非"游离态", 而是属于某一个 Helm Release, 那么将会打印出该情况, 附上快捷的 :code:`helm delete` 命令, 协助你与业务沟通和梳理.
