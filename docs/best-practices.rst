最佳实践
========

值得一提的最佳实践和窍门, 在这里进行罗列.

.. _docker-images:

构建基础镜像体系
----------------

出于各方面的考虑, 不能让开发者自己直接用开源基础镜像, 这么做内耗大, 复用低 (每个人都要自行调教镜像, 他们还不一定熟悉最佳实践), 所以后端开发的常用运行环境, SA 要帮他们准备好. 要基于开源世界的镜像, 构建发展出适合自己团队用的镜像体系. 比如我们团队目前用的是 Ubuntu, 这也是我们认为最易用的发行版. 以下就是我们做的 :code:`ubuntu-base:latest` 镜像:

.. code-block:: Dockerfile

    FROM ubuntu:focal

    ENV DEBIAN_FRONTEND=noninteractive LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8

    ADD apt/sources.list /etc/apt/sources.list
    RUN apt-get update && \
        apt-get install -y --no-install-recommends tzdata locales && \
        ln -s -f /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
        sed -i -e 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen && \
        dpkg-reconfigure --frontend=noninteractive locales && \
        update-locale LANG=en_US.UTF-8 && \
        apt-get clean

    CMD ["bash"]

可以看到, 里边并没做什么神秘的事情, 只是做了些本地化, 以及提前做好一些合理默认值的设定. 毕竟这只是 base 镜像, 下一步我们还要基于 base 构建出适用于开发的应用镜像, 以 :code:`ubuntu-python:3.9` 为例:

.. code-block:: Dockerfile

    ARG REGISTRY
    FROM ${REGISTRY}/ubuntu-base:latest

    ARG PYTHON_VERSION_SHORT=3.9

    RUN apt-get update && \
        apt-get install -y python${PYTHON_VERSION_SHORT} python3-pip && \
        apt-get clean && \
        ln -s -f /usr/bin/python${PYTHON_VERSION_SHORT} /usr/bin/python3 && \
        ln -s -f /usr/bin/python${PYTHON_VERSION_SHORT} /usr/bin/python && \
        ln -s -f /usr/bin/pip3 /usr/bin/pip

    ADD .pip /root/.pip
    WORKDIR /root

要注意, `这里安装 Python 3.9 的姿势是个 hack <https://stackoverflow.com/questions/65644782/how-to-install-pip-for-python-3-9-on-ubuntu-20-04/70681853#70681853>`_ , 请酌情参考. 除此之外, 可以发现构建应用影响时做的事情, 也是一些默认值的设定, 以及少量易用性改善.

那么现在我们有了 :code:`ubuntu-base:latest`, 以及基于其上的 :code:`ubuntu-python:3.9`, 用是可以用了, 但还得保证镜像沿着依赖树持续更新才行, 比方说 :code:`ubuntu-base:latest` 有所更新, 那么 :code:`ubuntu-python:3.9` 也要安排重新构建. 这件事我们也用 gitlab-ci 来做, 通过书写恰当的触发条件, 来实现镜像的依赖构建:

.. code-block:: yaml

    variables:
      REGISTRY: registry.example.com
      PYTHON_VERSION_SHORT: '3.9'

    stages:
      - build_bases
      - build_apps

    .build_ubuntu_template: &build_ubuntu_template
      only:
        changes:
          - ubuntu-*.dockerfile
          - apt/*

    build_ubuntu_base:
      stage: build_bases
      script:
        - docker build --squash --pull -f ubuntu-base.dockerfile -t $REGISTRY/ubuntu-base:latest .
        - docker push $REGISTRY/ubuntu-base:latest
      <<: *build_ubuntu_template

    build_ubuntu_python:
      only:
        changes:
          - ubuntu-*.dockerfile
          - apt/*
          - .pip/*
      stage: build_apps
      retry: 2
      variables:
        IMAGE_TAG: 'latest'
      script:
        - >
          docker build --squash --pull -f ubuntu-python.dockerfile
          -t $REGISTRY/ubuntu-python:${PYTHON_VERSION_SHORT} .
          --build-arg PYTHON_VERSION_SHORT=${PYTHON_VERSION_SHORT}
          --build-arg REGISTRY=${REGISTRY}
        - docker push $REGISTRY/ubuntu-python:${PYTHON_VERSION_SHORT}
        - docker tag $REGISTRY/ubuntu-python:${PYTHON_VERSION_SHORT} $REGISTRY/ubuntu-python:${IMAGE_TAG}
        - docker push $REGISTRY/ubuntu-python:${IMAGE_TAG}
      <<: *build_ubuntu_template

以下开始技术总结:

* 力求精简, 不要在基础镜像里安装多余的东西, 只有确定全栈都要用到, 才考虑纳入基础镜像
* 所有事情都要做好分级, 在合适的镜像层来做, 让镜像内容达到最大化复用
* CI 的构建流程, 可以设定为每周全量重新构建, 保证上游的开源镜像持续更新, 享受最新安全补丁
* base 层推荐用 latest tag, 毕竟这一层没多少兼容性问题. 而应用层则应该用带有版本号的镜像 tag, 避免使用 latest

别用启动脚本
------------

劝你别把启动命令包在一个脚本里, 这样只会让排查更加困难(修改了启动流程以后, 需要重新构建上线, 才能生效). 如果非要用启动脚本, 你可以直接以 exec 的形式写在 command 下:

.. code-block:: yaml

  # bad
  command: ["bash", "-c", "conf/start.sh"]
  # good:
  command:
  - bash
  - -c
  - |
    set -e
    exec python -m http.server

虽说 exec command 是最佳实践, 但似乎这种写法会破坏某些特殊情况下的信号转发机制, 比方说, 如果你要在容器中使用 `xvfb-run <http://manpages.ubuntu.com/manpages/trusty/man1/xvfb-run.1.html>`_, 那你可能需要再外包一层 `Tini <https://github.com/krallin/tini>`_, 否则可能出现 `吞信号导致无法启动 <https://unix.stackexchange.com/questions/244470/xvfb-not-sending-sigusr1-breaking-xvfb-run>`_ 的问题. 示范如下:

.. code-block:: yaml

  command:
    - tini
    - --
    - xvfb-run
    - pm2-runtime
    - conf/pm2/config.json
    - --env
    - dev

开发前后端分离的应用 (前后端对接)
---------------------------------

对于前后端分离的应用, 前端部分的注意事项比较多, 在这里进行收录总结.

正确处理 HTTPS 重定向 (force-ssl-redirect)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

本小节内容以 Ingress Controller 进行 TLS 截断为前提, 流量到达容器的时候一律是 HTTP, 如果你的集群网络架构不同, 那么实践势必也会有所不同.

如果你的应用需要彻底禁用 HTTP 访问, 仅支持 HTTPS, 那么首先你需要给 Ingress 挂上对应的设置, 具体可以在 :ref:`示范 <helm-values>` 里搜索 :code:`force-ssl-redirect`. 这样一来, HTTP 流量在没有到达容器前, 就首先被 Ingress Controller 重定向了. 看起来似乎很美好, 但要注意应用自身在进行跳转的时候(最常见的就是, 探测到用户未登录, 给重定向到登录页面), 一定要返回 HTTPS 的 URL, 而非很多情况下默认的 HTTP, 否则就有可能出现 Too Many Redirects Error.

总结就是, 应用虽然接受 HTTP 流量, 但发起跳转时, 一定要返回 HTTPS URL, 否则便会与 :code:`force-ssl-redirect` 规则打架.

以 Nginx 为例, 配置文件类似下方示范, 重点就是禁用掉 :code:`absolute_redirect`:

.. code-block:: nginx

  server {
      listen 80;
      server_name _;

      # 容器内的 Nginx 永远和 HTTP 流量打交道
      # 如果不禁用此选项, 那么在重定向的时候, 也会默认重定向到 HTTP URL
      absolute_redirect off;

      root /lain/app/;
      location / {
          index index.html index.htm;
          try_files $uri $uri/ /index.html$args;
      }
  }

当然了, Nginx 还有很多种办法进行跳转, 比如 :code:`rewrite` 和 :code:`return`, 无论是什么方式, 按照其对应的办法保证跳转到 HTTPS 即可.

集群内用 Service 来互相访问, 不要走域名
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

集群内应用间互相访问, 别用域名, 而是直接走 `Kubernetes Service <https://kubernetes.io/zh/docs/concepts/services-networking/connect-applications-service/>`_ . 以 :ref:`dummy <helm-values>` 为例, 如果你的应用和 dummy 共处一个集群, 那么就可以通过 :code:`dummy-web` 这个集群内 hostname 直接访问. 之所以不建议通过 Ingress 域名访问, 是因为不仅网络开销大, 有时候还会因为各种安全策略, 导致压根无法访问.

上述建议要写成 Nginx 配置, 大概就是 :code:`proxy_pass http://dummy-web/;`, 注意 scheme 必须设定为 http, TLS 截断已经在流量过 Ingress Controller 的时候就做好了, 集群内都是 HTTP 流量.

特别地, 我们喜爱的 Django, 也 `建议将静态文件与 web server 分开部署 <https://docs.djangoproject.com/en/4.0/howto/static-files/deployment/#serving-static-files-from-a-dedicated-server>`_, 因此在这里贴一下示范以供参考:

.. code-block:: yaml

  # chart/values.yaml
  appname: mydjango

  deployments:
    web:
      replicaCount: 1
      resources:
        limits:
          cpu: 1
          memory: 256Mi
        requests:
          cpu: 10m
          memory: 256Mi
      command:
        - bash
        - -c
        - |
          set -xe
          exec gunicorn -c conf/gunicorn/prod.py mydjango.wsgi
      containerPort: 8000
    static:
      replicaCount: 1
      podSecurityContext: { "runAsUser": 0 }
      resources:
        limits:
          cpu: 1000m
          memory: 256Mi
        requests:
          cpu: 10m
          memory: 100Mi
      command: ["/usr/sbin/nginx", "-g", "daemon off;"]
      containerPort: 8000

  ingresses:
    - host: mydjango
      deployName: static
      paths:
        - /static
    - host: mydjango
      deployName: web
      paths:
        - /

  build:
    base: python:3.9
    prepare:
      script:
        - apt-get update
        - apt-get install -y nginx
        - pip3 install -r requirements.txt
    script:
      - pip3 install -r requirements.txt
      - python3 manage.py collectstatic --noinput
      # 容器里不建议拷贝, 若情况合适, 一切拷贝都应改为软链
      - ln -s -f /lain/app/conf/static.conf /etc/nginx/conf.d/static.conf

上方的 values.yaml, 正是按照 Django 官方文档所推荐的那样, 用一个独立的 Nginx 来处理所有静态文件请求. 配置起来简单直白, 就不过多解释了, 直接照抄即可. 另外附上对应的 Nginx 配置文件:

.. code-block:: nginx

  # conf/static.conf
  server {
      listen      8000;
      server_name _;
      charset     utf-8;
      client_max_body_size 999M;
      location /static  {
          alias /lain/app/static;
      }
  }

标准化操作流程 (SOP)
--------------------

作为业务方, 肯定希望自己的上线流程既方便又安全, 这就要求操作要落实成为 `SOP <https://en.wikipedia.org/wiki/Standard_operating_procedure>`_, 并且需要具备可发现性, 同时可 review / rollback. 以下是 lain 推荐的实践:

* 变更应用配置之前, 往往希望对操作进行 review, 因此建议将集群的(非机密)配置放在代码库里, 方便跟踪变更和 review. 只有敏感信息才存在 :code:`lain [env|secret]` 内.
* 也正因为 :code:`lain [env|secret]` 里的内容不方便 review, 因此每次修改这些内容时, lain 会发送提示消息到 webhook 里, 提醒开发者及时 review.
* 如果你的应用需要执行 migration 操作, 建议将 migration 固化为 :code:`values.jobs` (参考 :ref:`auto-migration`), 这样一来, 每次执行 :code:`lain deploy` 都会运行 migration job, 免除了忘记执行的问题.
* 如果你的应用流量巨大, 实例数众多, 务必要 :ref:`对 strategy 进行微调 <deploy-strategy>`, 让 Kubernetes 缓慢地进行滚动上线操作, 避免真的出现异常时, 事故迅速升级.
* :code:`lain deploy` 执行完毕以后, 会自动开启一个 :code:`lain status` 面板, 供你观察确认此次操作的"绿灯". "绿灯"是什么? 在 lain 看来, 起码要满足:

  * 没有异常状态的容器
  * 没有异常日志
  * web 服务的 endpoint 运作正常

  满足这几个条件, 作为操作者才能放心离开键盘. 但如果上线操作太频繁导致没精力总是盯梢, 或者压根就是在 CI 里自动执行的, 没有 TTY, 看不到 :code:`lain status`. 你也可以考虑往自动化方向更进一步, 也就是声明出 :code:`values.tests`, 在测试内检查你的应用是否运作正常.

  参考 :ref:`helm-values` 里的测试写法, :code:`lain wait` 做的事情就是, 等待所有容器进入正常 Running 的状态, 如果超时便报错. 你还可以补充更多自己的测试, 建设出更完善的检查流程(比方说检查容器日志有无异常, 甚至 sentry 有没有新的 issue!).
* 如果上线以后真的发生异常, 你需要迅速判断接下来的处置:

  * 采集错误信息 - 这个一般由 sentry 负责, 也许你还需要用 :code:`lain logs` 收集一下错误日志, 如果容器卡在启动环节, 日志不一定会进入 pipeline (比如 Fluentd --> ES --> Kibana), 这时候唯一的日志来源就是 :code:`kubectl logs` 了, 也就是 :code:`lain logs`.
  * 进一步在容器里进行 debug - 生产事故十万火急, 一般都急着回滚了, 但如果有条件, 确实可以 :code:`lain x` 进入容器内进行一些 debug 和信息采集.
  * 回滚 - 在本地操作 :code:`lain rollback`, 命令 helm 把你的应用回滚到上一个版本. 与 :code:`lain deploy` 相仿, 执行完 rollback 后, 也会自动开启 :code:`lain status`, 供你观察回滚状态.

但也请注意, 这里讲述的最佳实践, 也基本上是针对大型协作项目, 如果你是一个 one man project, 或者是一个次优先级项目, 那不妨按照自己觉得最高效的方式行事. "次优先级项目"是啥意思? 就是挂了影响也不大, 因此自然没必要盯梢上线.

.. _auto-migration:

Auto Migration
--------------

上线如果忘了做 Migration, 那十有八九就事故了. 因此极力建议把 Migration 步骤写在 :code:`values.jobs`, 这样一来 :code:`lain deploy` 便会自动为你执行 Migration.

.. code-block:: yaml

    # 如果你的应用需要做一些类似数据库初始化操作, 可以照着这个示范写一个 migrate job
    # 各种诸如 env, resources 之类的字段都支持, 如果需要的话也可以单独超载
    jobs:
      init:
        ttlSecondsAfterFinished: 86400  # https://kubernetes.io/docs/concepts/workloads/controllers/job/#clean-up-finished-jobs-automatically
        activeDeadlineSeconds: 3600  # 超时时间, https://kubernetes.io/docs/concepts/workloads/controllers/job/#job-termination-and-cleanup
        backoffLimit: 0  # https://kubernetes.io/docs/concepts/workloads/controllers/job/#pod-backoff-failure-policy
        # 执行 DDL 前, 先对数据库做备份, 稳
        initContainers:
          - name: backup
            image: python:latest
            command:
              - 'bash'
              - '-c'
              - |
                mysqldump --default-character-set=utf8mb4 --single-transaction --set-gtid-purged=OFF -h$MYSQL_HOST -p$MYSQL_PASSWORD -u$MYSQL_USER $MYSQL_DB | gzip -c > /jfs/backup/{{ appname }}/$MYSQL_DB-backup.sql.gz
            # 注意下面这里并不是照抄就能用的!
            # jfs-backup-dir 需要在 volumes 下声明出来, 才能在这里引用
            # 详见 "撰写 Helm Values" 这一节的示范
            volumeMounts:
              - name: jfs-backup-dir
                mountPath: /jfs/backup/{{ appname }}/  # 这个目录需要你手动创建好
        # 以下 annotation 能保证 helm 在 upgrade 之前运行该 job, 不成功不继续进行 deploy
        annotations:
          "helm.sh/hook": post-install,pre-upgrade
          "helm.sh/hook-delete-policy": before-hook-creation
        command:
          - 'bash'
          - '-c'
          - |
            set -e
            alembic upgrade heads

即便有了 Auto-Migration, 业务其实也有放心不下的事情: 上线都是 CI 来执行的, 做 Daily Release 的时候, CI 可不知道这一次上线需不需要执行 DDL, 万一出现死锁的话, 那可就事故了.

因此如果需要阻止 CI 进行需要 Migration 的上线任务, 可以用类似下方这个脚本来检查是否需要做 Migration, 如果有则打断 CI, 并且发消息到频道里, 提醒手动上线.

.. code-block:: bash

    #!/usr/bin/env bash
    set -euo pipefail
    IFS=$'\n\t'


    current=$(lain x -- bash -c 'basename $(alembic show current|grep Path|sed "s/Path: //")' | grep -o -E "^\w+\.py")
    head=$(basename $(ls alembic/versions/ -t1 -p | head -n1))

    if [ "$current" != "$head" ]; then
      msg="refuse to deploy due to alembic differences:
      current $current
      head $head
      job url: $CI_JOB_URL"
      echo $msg
      lain send-msg $msg
      exit 1
    fi

.. warning::

   运行 Job 出问题了! 如何中断?

   * 立刻 ctrl-c 掐断 lain deploy
   * 如果需要获取出错日志, 执行 :code:`lain logs [job-name]` 就能打印出来, 出错的容器不会被清理掉, 但万一容器真的找不到了, 也可以去 kibana 上看日志, 用 :code:`lain status -s` 就能打印出日志链接
   * 如果仅仅是需要打断 Job, 那就需要先获取 job name, 怎么找呢? 可以用以下方法:

     * 用 :code:`lain status` 找到 Pod name, 例如 :code:`[APPNAME]-migration-xxx`, 那么 job name 便是 :code:`[APPNAME]-migration`
     * :code:`kubectl get job | ack [APPNAME]`

   * 知道 job name 就好办了, 执行 :code:`kubectl delete job [job name]`, Job 就被删除了
   * 对于 MySQL Migration, 删掉 Job 还不算完, 毕竟指令已经提交给数据库了, 你需要连上数据库, :code:`show processlist` 地研究为什么 Migration 会死锁, 并且对罪魁祸首的命令执行 Kill.

.. _health-check:

健康检查
--------

如果你阅读过 :ref:`values.yaml 示范 <helm-values>`, 那你多半已经了解到, Kubernetes 提供 :code:`readinessProbe` 和 :code:`livenessProbe` 两种健康检查机制, 作为示范, 你可以这样书写:

.. code-block:: yaml

       # readinessProbe 如果检测不通过, 将会从 Service Endpoint 中移除
       # 这样一来, 容器就不再接受流量了
       readinessProbe:
         httpGet:
           path: /healthcheck
           port: 8000
         initialDelaySeconds: 5
         periodSeconds: 3
         failureThreshold: 1
       # livenessProbe 如果检测不通过, 将会直接重启容器
       livenessProbe:
         httpGet:
           path: /healthcheck
           port: 8000
         initialDelaySeconds: 60
         periodSeconds: 5
         failureThreshold: 10

书写健康检查配置, 请注意以下几点:

* :code:`initialDelaySeconds`: 容器创建好之后, 你往往希望先等上一段时间, 再开始健康检查. 这个参数就是用来控制等待多久:

  对于 readinessProbe, 建议写成 1-5s, 容器创建以后, 就尽快开启检查, 健康了就立马开始接受流量.

  而对于 livenessProbe, 事情就略有不同了, 比如一个应用需要 3 分钟时间预热, 那你最好把 :code:`initialDelaySeconds` 写成大于 360s, 否则应用还没准备好, 就被 livenessProbe 断定为不健康, 然后操作重启. 这样一来, 这个应用将会一辈子都陷入在重启循环里.
* :code:`periodSeconds`: 多久执行一次健康检查, 这个视情况写 1-5s 均可, 但如果你的健康检查接口需要消耗比较多的资源, 也可以适量放松, 否则过于频繁的健康检查, 将有可能压垮容器.
* :code:`failureThreshold`: 失败多少次, 才标记为"不健康", 对于 readinessProbe, 我们尽量填 1. 而对于 livenessProbe, 一般而言还是放松一些, 多给他几次机会, 否则一遇到失败就造成容器重启, 在大流量场景下反而容易引起"雪崩".

.. _gitlab-ci-build:

应用镜像的构建, 以及 CI 配置
----------------------------

有这样一类应用: 构建环境重, runtime 则非常轻. 比如 Node.js 的世界就离不开 node_modules 这个目录, 并且往往占用不少空间, 而且小文件异常多.

:code:`values.build.prepare`, 以及 :code:`values.release` 这两部分功能, 正是为了这种场景准备的:

.. code-block:: yaml

    build:
      base: node:16-buster
      prepare:
        env:
          PATH: '/lain/app/node_modules/.bin:${PATH}'
        script:
          # 在 prepare 镜像里提前预装一次依赖, 每次依赖变更的时候都可以重新 prepare 一番
          # 生成的 prepare 镜像形如 [APPNAME]:prepare, 这个镜像可以直接用在 GitLab CI Job 里, 比如用来跑单元测试
          - yarn install --prefer-offline --cache .cache/
        keep:
          - node_modules
      script:
        # 在 build 阶段再次安装依赖, 这次安装由于已经享受到了 prepare 镜像里的缓存, 按理说会快很多
        - yarn install --prefer-offline --cache .cache/
        - REACT_APP_RELEASE=$LAIN_META yarn build

    release:
      dest_base: openresty:1.19.3.1-2-buster-fat
      copy:
        # release 镜像就是个 nginx, 因此把构建的产物拷贝到容器里, 然后让 nginx 配置文件就位, 就算完成了
        - /lain/app/deploy
        - /lain/app/build
      script:
        - mkdir -p /etc/nginx/conf.d /var/log/nginx
        - cp -a /etc/openresty/* /etc/nginx
        - rm -rf /etc/openresty /etc/nginx/*.default
        - ln -s -f /lain/app/deploy/nginx.conf /etc/nginx/nginx.conf
        - ln -s -f /lain/app/deploy/nginx.site.conf /etc/nginx/conf.d/site.conf

相应的, GitLab CI Job 可以这样声明:

.. code-block:: yaml

    stages:
      - test

    test_job:
      # prepare 镜像里虽然已经预装了 node_modules, 但由于 GitLab CI Cache 机制的问题, 并没有办法复用
      # 不复用问题也不大, 我们就用 GitLab CI 自己的 Cache 机制, 都能让 Job 的安装大大加速
      image: [APPNAME]:prepare
      stage: test
      script:
        # 再次执行安装, 确保项目依赖符合 yarn.lock
        - yarn install --frozen-lockfile
        - yarn test -- --coverage --collectCoverage
      cache:
        - key: node-cache
          paths:
          - .cache/
          - node_modules/

    # 之所以把 prepare 放在最后, 是因为 prepare 镜像只是一层缓存, 不必非得等 prepare 完成, 才继续接下来的 test / deploy
    # 但如果在 prepare.script 里增加了新的依赖, 由于执行顺序的问题, 运行 test_job 的时候, prepare 镜像还没有重新生成
    # 这时候可能就只好辛苦你本地先 prepare 一番了, 或者把这些新的依赖在 test_job.script 里手动安装一下
    prepare_job:
      stage: .post
      cache:
        - paths:
          - .cache/
      rules:
        # 代码合并到主干以后, 如果发现 lockfile 有所更新, 那就重新 prepare
        - if: '$CI_PROJECT_NAMESPACE == "dev" && $CI_COMMIT_BRANCH == "master" && $CI_PIPELINE_SOURCE != "schedule"'
          changes:
            - yarn.lock
      script:
        - lain use test
        - lain prepare

在做缓存这件事上, :code:`lain prepare` 和 CI Cache 做的事情是等价的, 所以事实上如果完全不用 GitLab CI Cache, 我们也能达到非常近似的效果:

.. code-block:: yaml

    stages:
      - test

    test_job:
      # prepare 镜像里虽然已经预装了 node_modules, 但由于 GitLab CI Cache 机制的问题, 并没有办法复用
      # 不复用问题也不大, 我们就用 GitLab CI 自己的 Cache 机制, 效果是类似的, 都能让 Job 的安装大大加速
      image: [APPNAME]:prepare
      stage: test
      script:
        # prepare 镜像里的 node_modules 和 GitLab CI 的运行目录不一样
        # 因此如果想要复用 node_modules, 只好做一下 link, 无伤大雅
        - ln -s -f /lain/app/node_modules .
        # prepare 镜像里的 node_modules 未必是最新的, 因此这里的 yarn install 其实需要重新安装变更的内容
        # 通常在开发流程中, lockfile 是不会频繁大量变动的, 因此在这里重新 install, 一般也不会耗费多少时间
        # 如果你希望每一次 Job 运行都能享受到最新的缓存, 那么像上边例子中使用 GitLab CI Cache 将会是更好的选择
        # 因为 GitLab CI 每次执行完都会更新上传缓存, 而 prepare 镜像只会在重新 :code:`lain prepare` 后, 才会更新
        - yarn install --frozen-lockfile
        - yarn test -- --coverage --collectCoverage

.. _deploy-strategy:

滚动上线
--------

滚动上线是一个最为常见的实践, 但要注意, 如果你的实例数众多 (>20), 并且存在超售 CPU 的情况, 那你最好对 `update strategy <https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#updating-a-deployment>`_ 进行调整适配, 防止同时启动大量容器的时候, 对节点 CPU 占用过高, 导致 `启动拥堵 <https://github.com/kubernetes/kubernetes/issues/3312>`_.

.. code-block:: yaml

    # values-prod.yaml
    deployments:
      web:
        strategy:
          type: RollingUpdate
          rollingUpdate:
            # 每次只滚动一个容器, 稳
            maxSurge: 1
            maxUnavailable: 1

同理, 如果你的应用第一次上线, 那最好不要一下子全量上线, 而是一次 10 个左右地递增. 某些应用启动期间有一瞬的 CPU 用量极高, 而之后则进入静息状态, 这种情况大家都喜欢写成 low requests, high limits. 这么做本来也没什么毛病, 但若是一下子启动大量容器, 节点的 CPU 就不一定能撑住了, 进入卡死状态, 最终只能重启节点才能解决.

.. _multiple-helm-releases:

把一个代码仓库部署成不同 APP
----------------------------

为啥一个仓库会想要部署成两个 APP? 这不是故意增加维护难度吗?

这么说吧, 很多应用的开发场景都有各种"难言之隐", 比如一个后端项目, 及承担 2c 的流量, 同时又作为管理后台的 API server. 作为内部系统的部分, 希望快速上线, 解决内需, 而面相客户的部分, 则需要谨慎操作, 装车发版. 这就需要两部分单独上线, 互不影响.

又或者开发者手上只有一个集群, 但也一样需要测试环境 + 生产环境, 这时候也需要考虑把一个代码仓库部署成两个 APP.

最后, 如果你的应用在不同集群进行定制化构建, 那么最好直接在不同的集群用不同的 appname, 让镜像存入不同的命名空间, 增加隔离程度, 减少操作错误的空间.

可选的操作办法和特色, 在这里一一介绍:

用 :code:`lain update-image` 单独更新 proc
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

把你的应用里需要单独部署的部分拆成单独的 proc, 用 update-image 进行部署:

.. code-block:: yaml

    appname: dummy

    deployments:
      web:
        replicaCount: 20
        containerPort: 5000
      # web-dev 与 web 是两个不同的 deploy
      # 而用 lain update-image 上线的时候只会更新一个 deploy 的镜像
      # 达到了互不影响的效果
      web-dev:
        replicaCount: 1
        containerPort: 5000

    # 如果需要的话, web-dev 也可以有自己的域名, 声明 ingress 的时候注意写对 deployName 就行
    # 如果不需要域名, 仅在集群内访问, 那么可以用 svc 访问, 也就是 dummy-web-dev:5000
    ingresses:
      - host: dummy-dev
        deployName: web-dev
        paths:
          - /

此法的一些特点, 和需要注意的地方:

* 如果有多个 proc 需要单独更新, 那么 update-image 命令便会显得有点长, 比如 :code:`lain update-image web-dev worker-dev`, 最好由 CI 代执行, 或者脚本化
* 单独更新 web-dev, 只能使用 lain update-image, 因此也仅仅能用来更新镜像, 其他的 values 配置改动将无法用该命令上线
* 如果 values 发生变动需要上线, 则必须用 :code:`lain deploy`, 这样就是"整体上线", web 和 web-dev 都会重新部署
* 每一个 proc 可以单独在 values 里锁死 imageTag, 示范请参考 :ref:`values.yaml 模板 <helm-values>`, 搜索 :code:`imageTag`, 这样一来, 无论怎么 :code:`lain deploy`, lain 都会尊重写死在 values 里边的值

在 :code:`values-override.yaml` 里超载 :code:`appname`
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

此法用于: 在一个集群里, 将一个代码仓库部署成两个应用.

在 chart 目录下多放一份 `values-override.yaml`, 命名其实是任意的, 只要不与集群名称冲突就好. 这种办法灵活性更高, 当然也更复杂.

.. code-block:: yaml

    # values-override.yaml
    # 这里仅仅超载了 appname, 如果需要的话, 域名也得做好相应的修改
    appname: dummy-override

让超载的 :code:`values-override.yaml` 生效, 需要给 lain 传参:

.. code-block:: bash

    lain -f chart/values-override.yaml deploy --build
    lain -f chart/values-override.yaml status
    # 其他的各种命令, 也都需要加上 -f 参数

此法的一些特点, 和需要注意的地方:

* 灵活性大, 你可以在 :code:`values-override.yaml` 里随心所欲地超载.
* 由于修改了 :code:`appname`, 在 lain 看来就是一个全新的 app 了, 那么自然, 镜像是没办法复用的, 你需要重新 :code:`lain build` 构建镜像. 如果想要复用镜像, 可以参考下边的办法超载 :code:`releaseName`.
* 操作 dummy-override 这个 app 时, 所有 lain 命令都需要加上 :code:`-f chart/values-override.yaml`, 并不是特别方便.

在 :code:`values-[CLUSTER].yaml` 里超载 :code:`appname`
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

小团队往往是一个 registry 用于好几个不同的集群, 然而对于一个应用, 在不同集群可能会采用不同的构建流程(也就是定制构建, cluster-specific build).

那么问题就来了: :code:`lain build` 产生的镜像 tag, 并不区分集群. 因此 lain 鼓励通过 appname 来区别镜像名, 以此来在不同集群上线不同镜像.

如果你不愿意超载 appname, 那么 lain 就不允许你使用 :code:`lain deploy --build`. 因为这个命令的特性是 **如果镜像存在, 就省略再次构建**. 因此你只能使用 :code:`lain build --deploy`.

那么超载 appname 是怎么一回事呢, 请看示范:

.. code-block:: yaml

    # values.yaml
    appname: dummy
    build:
      script:
        - echo building for a ...

    # values-b.yaml
    # 超载 appname 以后, 在 b 集群构建出来的镜像, 仅存入了 dummy-b 这个命名空间, 避免与 a 集群的版本混淆
    appname: dummy-b
    build:
      script:
        - echo building for b ...

在 values 里超载 :code:`releaseName`
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

上边提到的超载 :code:`appname` 的办法, 原理上就是创造一个全新的 lain app, 但多数时候可能还是希望复用原应用的镜像, 和各种其他资源的 (比如 lain secret / env). 这种情况则可以超载 :code:`releaseName`, 这样一来, 就能在复用该应用的镜像, 以及 lain secret / env 的前提下, 部署出另一个 helm release.

.. code-block:: yaml

    # values-override.yaml
    # 这里仅仅超载了 releaseName, 如果需要的话, 域名也得做好相应的修改
    releaseName: dummy-override

类似上边超载 :code:`appname` 的方式, 为了让新的 :code:`releaseName` 生效, 需要给 lain 传参, 也就是 :code:`lain -f chart/values-override.yaml ...`.
