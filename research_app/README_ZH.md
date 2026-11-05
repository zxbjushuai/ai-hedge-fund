
# 合并后代码归属与维护范围
这里的“自研”指我们这个分支新增或扩展的功能，不代表每个文件都从零编写；例如 UI 基础组件和部分数据库迁移复用了作者旧版代码。
以下划分依据是当前代码与固定上游 fc1bf25 的实际差异。
分类	目录或文件	主要职责及维护建议
自研 Web 应用	research_app/frontend/	模拟、供应商、缓存、审计页面。后续视觉重设计主要在这里
自研 Web 后端	research_app/backend/routes/、services/	API、连接管理、模拟预检查、缓存任务入口。你主要维护
Web 数据库与启动	research_app/backend/database/、alembic/、config.py、启动脚本	包含旧版继承代码及自研扩展；由本分支维护，保留迁移历史
自研历史模拟	hedge_fund/simulation/	SQLite runner、事件驱动 Persona 状态、审计；核心维护重点
自研 SQLite 持久化	hedge_fund/persistence/、brokers/persistent.py	行情缓存、模拟记录、状态和事务
自研数据获取扩展	hedge_fund/data/market.py、cache_jobs.py、cache_service.py、yfinance_client.py、earnings.py、errors.py	美股目录、Yahoo 数据、批量任务、错误分类
自研供应商扩展	hedge_fund/llm/providers.py、protocols.py、vendors.py、adapter_registry.py、base.py、types.py	多协议、多连接、独立凭据配置
上游为主	hedge_fund/run.py、tui/、paths.py	作者 CLI、Textual TUI、文件路径约定，优先跟随上游
上游为主	hedge_fund/features/、strategies/、risk/、validation/	原有分析与策略基础，尽量保持上游结构
上游回测入口	hedge_fund/backtesting/、event_study/	作者回测和事件研究；当前主要改动在测试兼容层


最需要谨慎维护的是“共同修改区”
不能把整个 hedge_fund/ 当成作者代码。以下文件已经同时承载两边的行为：
文件	本分支增加或保留的能力
pipeline/run_cycle.py、pipeline/models.py	显式 universe、执行与估值价格分离、Persona engine、拆股 sizing、审计字段
fund/spec.py	旧 YAML 兼容、Persona 刷新策略
brokers/sim.py、models.py、protocol.py	自研执行需求与上游 broker 接口整合
portfolio/construction.py	自研组合构建及边界处理
signals/llm_agent.py、pead.py	事件上下文、失败处理、earnings 数据语义
data/models.py	原始行情、复权收盘价、公司行动等字段
llm/cache.py、registry.py、api_models.json	上游模型入口与自研连接、缓存兼容
pyproject.toml、poetry.lock	两边共用的安装与依赖配置


这些是后续 merge 最可能产生语义冲突的地方，不能简单选 ours/theirs。
 以后你优先维护哪里？
按需求找入口最直接：
- 改页面和交互：research_app/frontend/
- 改供应商配置：research_app/backend/services/llm_provider_service.py，以及 hedge_fund/llm/ 的自研适配文件。
- 改缓存和股票目录：hedge_fund/data/ 的自研文件及对应 Web routes。
- 改模拟流程、触发时机和审计：hedge_fund/simulation/
- 改成交、估值、组合构建：共同修改区，需要同时跑作者和自研测试。
建议保持当前边界：应用功能放 research_app，可复用的模拟能力放核心扩展模块；只有确有必要时才修改共享核心。 这样后续跟随上游的成本最低。



项目的 CLI/TUI 仍能运行，但不能说你的修改对原项目“完全没有影响”。 部分改动进入了共享核心，会改变原入口的行为。
另外，research_app/ 是你维护的应用范围，但其中基础 UI、部分数据库模型和迁移脚本是复用旧版代码，不全是从零编写。
1. 哪些核心代码属于你的扩展？
这些模块相对上游 fc1bf25 是新增的，主要服务你的 Web 功能：
目录／文件	功能
hedge_fund/simulation/	历史模拟、Persona 状态、审计
hedge_fund/persistence/	SQLite 缓存及模拟数据持久化
data/cache_jobs.py、cache_service.py、market.py、yfinance_client.py	批量缓存、美股目录、Yahoo 数据
llm/providers.py、protocols.py、vendors.py、adapter_registry.py	多连接、协议选择、特殊请求头
brokers/persistent.py	持久化 broker
signals/momentum.py	价格动量模型


作者 CLI/TUI 不会自动启用你的 SQLite runner 或事件调度器。
2. 哪些上游文件被修改，影响是什么？
共享文件	修改及影响
pipeline/run_cycle.py	增加执行／估值价格、Persona engine、拆股 sizing 参数；未传时仍走原默认路径
fund/spec.py	增加刷新策略、旧 universe 兼容、运行级 LLM 注入
brokers/sim.py	增加手续费、分红拆股方法；默认手续费仍为上游的 0
models.py、pipeline/models.py	增加失败状态、审计字段，输出 JSON 比上游更丰富
signals/llm_agent.py	改变失败分类、缓存 identity，增加事件上下文
portfolio/construction.py	明确排除 failed／abstained 信号
signals/pead.py	改为使用数值 earnings surprise
llm/registry.py、api_models.json、cache.py	合并模型目录，支持连接身份及缓存路径配置
fund/example.yaml	修改策略权重，加入动量策略
pyproject.toml、poetry.lock	合并 Web、数据库及数据获取依赖


3. 实际需要注意的兼容问题
本次检查发现以下影响，不能仅凭测试通过忽略：
① PEAD 的输入要求变严格了
上游原来可以使用 BEAT/MISS 标签。现在必须有数值 surprise，或者实际 EPS 和预期 EPS。
因此，只有标签的财报数据以前可能产生信号，现在会被跳过。这会影响作者入口使用这些数据时的策略结果。
② 作者 TUI 尚未适配 failed 状态
作者 TUI 的 _verdict() 只判断旧的 metadata.abstained 和信号正负。新增的失败信号值为 0，可能被显示成 NEUTRAL。
组合构建会排除失败信号，但 TUI 展示不准确。这是一个具体的兼容缺口。
③ 默认示例策略已经不同
原示例是价值策略 60%、PEAD 40%；现在是价值 50%、PEAD 20%、动量 30%。
使用新示例创建 mandate 时，结果自然与作者原版不同；不会自动改写用户已有的 YAML。
④ 缓存与扩展接口存在变化
- LLM 缓存 key 加入模型身份，旧缓存可能不再命中，首次运行可能重新调用模型。
- run_cycle() 现在向 broker 传入 cycle_date。仓库内 broker 已适配，但外部按旧接口编写的 broker 可能需要调整。
4. 当前验证结论与维护建议
刚重新运行完整离线测试：297 passed，39 项 live 测试未执行。其中验证了作者 CLI 保存文件结果、Textual 首页启动；没有验证真实模型调用下的所有 TUI 展示情况。
建议你的维护边界是：
- 日常开发：research_app/ 和自研核心扩展。
- 重点回归：上述共享文件，尤其信号、组合构建和 pipeline。
- 尽量跟随上游：run.py、tui/、作者 llm/client.py——它们当前文件内容仍与固定上游一致，但会受到共享核心变化的间接影响。