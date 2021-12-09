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

docker error: no space left on device
-------------------------------------

docker 分配的磁盘空间是有限的, 空间不够时, docker 就会报错无法使用. 你要么为自己的 docker 分配更大的磁盘空间, 要么用 :code:`docker system prune` 进行一番清理, 也许能修复此问题.

docker build error: too many levels of symbolic links
-----------------------------------------------------

如果在其他环境 (CI, 别人的电脑) 无法复现此问题, 那多半是你本地 docker 的数据有些异常, 请抹掉整个 docker 的数据, (可选)升级 docker, 然后重试.

其他 docker build 灵异错误
--------------------------

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

docker pull error
-----------------

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
* 新款 M1 芯片的 Macbook, docker 有一些奇怪的问题, 在这个 issue 里有介绍解决办法, 但我还没亲自试过: https://github.com/docker/for-mac/issues/5208
* 你的 docker 升级到最新版了吗? 以写作期间为例, docker for mac 的最新版是 Docker 3.3.0, Docker Engine v20.10.5, 你的 Docker 也要对齐, 起码不能低于这个版本
* 排查到现在还是无法拉取镜像的话, 把 curl, ping, dig 的结果发给 SA, 和他一起排查解决吧

上线了以后, 我的 Pod 并未重新创建?
----------------------------------

如果此次上线仅包含配置变更, 则 Kubernetes 并不会重新创建你的容器, 你需要 `lain restart` 手动删除所有 Pod

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

请求失败/超时的排查是个大话题, 各种技术框架下排查的操作都有所不同. Kubernetes 下的排查尤为复杂, 有兴趣可以详读 `A visual guide on troubleshooting Kubernetes deployments <https://learnk8s.io/troubleshooting-deployments>`_. 此处仅罗列一些 lain 下常见的不易排查的问题:

* 钻进容器里直接对服务端口进行 curl 请求, 能正常响应吗? 如果在容器里都无法访问, 那摆明是应用空间的问题了, 如果你认为 web server 的配置和启动都正常, 不妨先检查下资源声明: 如果你的 memory / cpu limits 写得太小, 进程拿不到足够的资源, 可能会响应非常慢, 造成超时.
* 你在 :code:`values.yaml` 里声明的 :code:`containerPort`, 真的是进程实际监听的端口吗? 有些人声明了 :code:`containerPort: 9000`, 结果 web server 实际在监听 :code:`8000`, 这就怪不得会发生 Connection refused 了.
