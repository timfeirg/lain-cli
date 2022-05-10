.. _lain-debug:

错误排查
========

lain 在设计上希望尽量把错误以可排查的方式暴露给用户: 能出错的地方就那么多, 只要说清楚哪里有问题, 为什么, 开发者自己应该都有能力自己解决. 因此, 如果在使用 lain 的过程中报错了, 请遵循以下排查步骤:

* 升级到最新版, lain 永远要用最新版, 也正因如此, 代码里甚至做了检查, 如果不是最新的两个版本, 就报错不让用
* 如无必要, 切勿使用 :code:`--ignore-lint` 这个参数, 有时候他会掩盖各种正确性问题, 让你排查起来摸不着头脑
* 更新模板试试, lain 的 helm chart 时不时会更新: :code:`lain init --template-only`
* 仍复现问题, 请详读报错信息, 耐心仔细的阅读错误输出, 没准你就明白应该如何修复了
* 报错内容实在看不懂! 那就只好找 SA 吧, 注意提供以下信息:

  * 完整的报错内容, 若是截图, 也请截全
  * 你面对的项目, 最好能将项目 url, 所处的分支 / commit 一并告知
  * 你面对的集群
  * :code:`lain version` 的输出
  * 若有需要, 把你当前进展 push 到代码仓库, 确保 SA 能方便地拿到现场, 便于复现问题

同时, 在这里对一些不那么容易自行排查修复的问题进行汇总.

各类文件权限错误 (permission denied)
------------------------------------

常和 linux 打交道的同学一定明白, 文件权限错误, 要么是需要对路径做 chown, 要么换用权限合适的用户来运行程序. 如果你的 lain app 遇到了此类问题, 也一样是遵循该步骤进行排查:

* 若是挂载进容器的文件遇到此问题, 你可能需要对文件进行 chown, 使之匹配运行程序的用户. 但要如何确认, 我的容器在以哪个用户的身份运行呢? 你可以这样:

  * 若是容器在 Running 状态, 可以直接运行 :code:`lain x -- whoami` 来打印出用户名
  * 若容器报错崩溃, 你也可以编辑 :code:`values.yaml`, 修改 :code:`command` 为 :code:`['sleep', '3600']` 之类的, 创造一个方便调试的环境, 然后执行上边提到的 :code:`whoami` 命令

* 为了安全性不大推荐, 但你也可以直接用 root 来运行你的应用: :code:`lain build` 产生的镜像, 默认是 :code:`1001` 这个小权限用户, 因此如果你需要的话, 可以换用 :code:`root` 用户来运行, 具体就是修改 :code:`podSecurityContext`, 请在 :ref:`helm-values` 自行搜索学习吧.

.. _docker-error:

Docker Error
------------

视镜像不同, :code:`lain build` 可能会出现各式各样的错误, 在这一节里介绍一些典型问题.

Unable to fetch some archives, maybe run apt-get update ...
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

一般来说是源更新了, 但镜像里的地址还是老的, 因此建议在用系统包管理器安装任何东西前, 都先做一下 update. 比如:

.. code-block:: yaml

  build:
    prepare:
      script:
        - apt-get update  # or yum makecache
        - apt-get install ...

不过这样做能解决问题的前提是, 你的构建所在地和源没有网络访问问题(翻墙). 因此如果你的团队在国内, 建议按照 :ref:`docker-images` 的实践, 将所有的源都采纳国内镜像.

docker build error: no space left on device
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

docker 分配的磁盘空间是有限的, 空间不够时, docker 就会报错无法使用. 你要么为自己的 docker 分配更大的磁盘空间, 要么用 :code:`docker system prune` 进行一番清理, 也许能修复此问题.

docker build error: too many levels of symbolic links
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

如果在其他环境 (CI, 别人的电脑) 无法复现此问题, 那多半是你本地 docker 的数据有些异常, 请抹掉整个 docker 的数据, (可选)升级 docker, 然后重试.

docker pull / push error
^^^^^^^^^^^^^^^^^^^^^^^^

按照以下顺序进行排查:

* 你的电脑能正常上网吗? 打开 baidu / weibo 试试
* 是拉不下来, 还是仅仅是慢? 如果你是从官方镜像源 (hub.docker.com) 拉取镜像, 国内势必是非常慢的, 你可以考虑给自己本地 docker 加上 registry-mirrors 配置:

.. code-block:: json

    {
      "features": {
        "buildkit": true
      },
      "experimental": true,
      "registry-mirrors": ["https://2c6tmbev.mirror.aliyuncs.com"]
    }

* 排除掉自己本地的各类 vpn 软件以及相关设置, 别忘了, docker 自己的配置也要检查清楚, 不要留有 proxy 设置.
* 如果 docker pull 已经出现进度条了, 说明和 registry 的沟通没有问题, 剩下的就是等了. 如果实在卡死了, 删掉镜像重来一番.
* docker pull 的报错是否显示未认证? 那么你做了 docker login 吗? 不妨在 keychain 里搜索 docker, 把所有的 key 删除, 然后再次 docker login, 然后重试
* docker 不允许用两个用户登录同一个 registry, 比如腾讯云的 registry, 登录了 A 账号, 就没法拉取 B 的镜像了, 如果硬要的话, 只能在 keychain 里删掉密钥, 再次 docker login 回原来的 registry, 才能正常拉取
* 你的 docker 升级到最新版了吗? 以写作期间为例, docker for mac 的最新版是 Docker 3.3.0, Docker Engine v20.10.5, 你的 Docker 也要对齐, 起码不能低于这个版本
* 排查到现在还是无法拉取镜像的话, 把 curl, ping, dig 的结果发给 SA, 和他一起排查解决吧

跨硬件架构 (multi-arch)
^^^^^^^^^^^^^^^^^^^^^^^

lain 并无特殊的跨架构构建机制, 并不支持构建多平台代码. 简单讲, 你选用了什么架构的 base 镜像, docker 就会为你构建什么架构的产物.

所以比方说, 如果你在用 M1 MacBook (也就是 arm64), 要构建针对 amd64 的 node 应用, 你需要声明 :code:`base: "amd64/node:latest"`, 而不是 :code:`base: "node:latest"`. 因为在 M1 MacBook 下, :code:`docker pull node:latest` 会下载 arm64 的镜像, 这样最后构建出来的东西扔到 amd64 的服务器上, 就没办法运行了.

总之, 选用 base 镜像的时候注意点就行了, 如果 base 镜像本身是支持多架构的, 那么你书写 :code:`base` 的时候, 要在 image tag 里显式声明架构. 如果你不确定自己面对的镜像是个什么架构的话, 也可以这样查看:

.. code-block:: bash

    docker inspect node:latest | grep -i arch

其他 docker build 灵异错误
^^^^^^^^^^^^^^^^^^^^^^^^^^

在你排查到山穷水尽的时候, 记得额外确认下 docker 的配置:

* docker 至少分配 5GB 内存, 否则构建的时候 OOM 了, 有时候甚至不会报错, 把你蒙在鼓里.
* 在 docker engine 配置里把好东西都写上:

.. code-block:: json

  {
    "experimental": true,
    "features": {
      "buildkit": true
    },
    "builder": {
      "gc": {
        "enabled": true
      }
    }
  }

如果你面对的集群支持, 强烈推荐你使用 :code:`--remote-docker`, 这样就能直接连接 CI 机器的 docker daemon 进行各种 docker 操作了, 不仅能加速 pull / push, 还能有效规避各种本地 docker 的配置问题. 详见 :code:`lain --help`.

上线有问题! 不好用!
-------------------

实际报障时, 你可千万不要用标题里的这种模糊字眼, 一定要详述故障现象. 本章节选用这个标题, 仅仅是为了收录各种上线操作中的常见错误.

关于上线错误, 你需要知道的第一点是: **如果操作正确, lain 是不会(在关键问题上)犯错的**. 上线是 lain 唯一需要做好的事情, 也有相当充分的测试覆盖, 上线中的问题往往是操作错误所致, 请耐心阅读本章节.

上线以后, 应用没有任何变化
^^^^^^^^^^^^^^^^^^^^^^^^^^

你操作 :code:`lain deploy`, 但你部署的正是当前线上版本, 镜像 tag 没变. 倘若容器配置也未变, 那么 Kubernetes 并不会帮你重新上线: 在 Kubernetes 看来, 你分明什么都没改嘛, 因此认为当前状态就是用户所期望的状态, 自然啥也不用做.

这时候你应该怎么做呢? 得分情况处理:

* 很多新手操作 :code:`lain deploy`, 其实内心只是想重启下容器. 这其实是做错了, 应该用 :code:`lain restart` 来做重启. 甚至, 你还可以用 :code:`lain restart --graceful` 来进行平滑重启. 不过到底有多平滑, 就看你的健康检查和 HA 设置是否恰当了, 详见 :code:`lain restart --help` 吧.

* 虽然镜像版本未变, 但你重新构建过该镜像. 镜像 tag 没变, 但内容却被覆盖了. 所幸 lain 默认配置了 :code:`imagePullPolicy: Always`, 只需要重启容器, 便会触发重新拉取镜像. 因此在这种情况下, :code:`lain restart` 也能解决你的问题.

  不过如果你手动调整过配置, 设置了 :code:`imagePullPolicy: IfNotPresent`, 那么即便重建容器, 也未必会重新拉取镜像. 不过既然你都玩到这份上了, 怎么解决应该心里有数吧, 这里不详述.

上线发生失败, 如何自救?
-----------------------

* 打开 lain status, 先检查 Kubernetes 空间有没有报错, 比如镜像拉不下来啊, 健康检查失败啊, lain status 是一个综合性的应用状态看板, 包括应用日志也在里边.
* 如果是 Kubernetes 空间的报错 (你看不懂的日志应该都是 Kubernetes 的事件), 那么就第一时间找 SA 吧.

有很多 Evicted Pod, 好吓人啊
----------------------------

如果看见 Evicted 状态容器, 不必惊慌, 这只是 Kubernetes 对 Pod 进行重新分配以后的残影, 并不意味着系统异常.

就像是你有三个抽屉, 用来放各种衣物袜子内裤, 每天随机从一个抽屉里拿东西穿. 久而久之, 抽屉的占用率不太均衡, 于是你重新收拾一下, 让他们各自都留有一些空位, 方便放新鲜洗净的衣服.

Eviction 容器其实就是 Kubernetes 在"收拾自己的抽屉", 而 Evicted Pod, 就是驱逐容器留下的"残影", 并不影响应用正常服务. 可想而知, 偶发的容器驱逐, 绝不代表集群资源不足了, 如果你真的怀疑集群资源吃紧, 你应该去看 :code:`kubectl describe nodes`, 根据用量和超售情况来判断.

我的应用无法访问, 如何排查?
---------------------------

如果你的应用无法访问, 比如 502, 证书错误, 或者干脆直接超时, 请遵循以下路径进行排查:

* 同一个集群下的其他服务, 能正常访问吗? 如果大家都挂了, 那多半就是流量入口本身挂了, 找 SA 解决
* 用 :code:`lain [status|logs]` 对应用状态进行一次全面确认, 看看有无异常
* 特别注意, :code:`lain status` 会同时显示 http / https 的请求状态, 如果二者请求状态不一致, 请参考以下排查要点进行甄别:

  * https 正常访问, http 请求失败: 有些应用在 web server 内做了强制 https 转发 (force-ssl-redirect), 劝你别这么做, 万一配置错误还会导致 http 状态下请求异常 (因为被 rewrite 到了错误的 url). 总而言之, 应用空间只处理 http 就好, 把 TLS 截断交给 ingress controller 去做
  * http 正常访问, https 请求失败: 如果你的应用是首次上线新的域名, cert-manager 需要一些时间去申请签发证书, 如果超过五分钟还提示证书错误, 那就找 SA 去处理证书错误问题
* 检查一下 :code:`values.yaml` 里声明的 :code:`containerPort`, 是不是写错了? 真的是进程实际监听的端口吗? 有些人声明了 :code:`containerPort: 9000`, 结果 web server 实际在监听 :code:`8000`, 这就怪不得会发生 Connection refused 了
* 如果你不确定应用到底在监听哪个端口, 可以用 :code:`lain x` 钻进容器里, 在容器内测试请求, 能正常响应吗? 如果在容器里都无法访问, 那就是 web server 本身有问题了, 请你继续在应用空间进行排查
* 如果你认为 web server 的配置和启动都正常, 不妨先检查下资源声明: 如果 CPU / Memory limits 太小, 进程拿不到足够的资源, 可能会响应非常慢, 造成超时

不过说到底, 请求失败/超时的排查是个大话题, 各种技术框架下排查的操作都有所不同. Kubernetes 下的排查尤为复杂, 有兴趣可以详读 `A visual guide on troubleshooting Kubernetes deployments <https://learnk8s.io/troubleshooting-deployments>`_.
