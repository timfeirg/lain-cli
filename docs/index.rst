.. rst-class:: hide-header

lain
====

往高了说, lain 是一个 DevOps 方案. 但其实, lain 只是帮你封装了 helm, docker 和 kubectl, 让开发者更便捷地管理自己的 Kubernetes 应用. 大致效果如下:

.. raw:: html

   <script id="asciicast-iLCiMoE4SDTyjcspXYfXGSkeO" src="https://asciinema.org/a/iLCiMoE4SDTyjcspXYfXGSkeO.js" async></script>

正如视频演示, lain 提供标准化的 Helm 模板, 开发者只须书写少量关键配置, 就能迅速部署上线. DevOps 里涉及的常见需求, 在这里都做了易用性封装. 例如查看容器状态 / 日志, 滚动上线, 甚至金丝雀部署, lain 都能帮你迅速完成.

学习如何使用 lain, 请参看 :ref:`quick-start`. 而如果你希望在你的团队中使用 lain, 则需要根据你所面对的基础设施的情况, 对 lain 做配置和版本发布, 才能开始上手. 具体请看 :ref:`dev`.

Documentation
-------------

.. toctree::
   :maxdepth: 2

   quick-start
   app
   best-practices
   errors
   design
   admin
   dev
