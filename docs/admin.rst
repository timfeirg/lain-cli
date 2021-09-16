集群管理
========

lain 对 Kubernetes 做了如此多的封装, 以至于很多 SA 工作都可以方便地用 lain 来完成. 这里罗列的管理员命令也许场景都比较特殊, 即便封装成了可以重复使用的功能, 也未必对你有用. 因此本章的作用基本是参考, 对 lain 的 SA 功能做一个示范.

查看集群状态
------------

:code:`lain admin status` 的功能类似 :code:`lain status`, 可以打印出整个集群的异常容器和节点. 如果集群要进行某些 Kubernetes 操作, 比如升级/重启节点, 就可以考虑用这个命令作为运维操作的绿灯.

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

.. _lain-admin-list-waste:

梳理集群资源浪费
----------------

:code:`lain admin list-waste` 将会遍历所有 deploy, 一个个地查询 prometheus, 把实际占用资源与声明资源作对比, 这样就能查出到底是谁在浪费集群资源(占着茅坑不拉屎).
