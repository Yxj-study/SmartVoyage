# SmartVoyage 多智能体旅行助手——项目面试八股

> 使用说明：先掌握“30 秒介绍、整体流程、核心亮点”三部分，再学习后面的专项问题。回答时先说结论，再结合本项目代码说明，最后补充取舍和改进方向。

---

## 一、项目定位

### 1. 一句话介绍

SmartVoyage 是一个基于 **LangGraph + A2A + MCP** 的多智能体旅行助手：大模型负责理解用户目标和制定任务计划，Coordinator 维护共享状态并调度天气、票务、景点和订单能力，程序代码负责执行价格、时间等确定性条件，并在真正下单前通过 Human-in-the-loop 要求用户确认。

### 2. 30 秒面试介绍

我做的是一个多智能体旅行助手。用户可以用一句自然语言提出复合需求，例如“查询北京天气，天气好的话订一张长沙到北京的机票，并推荐三个景点”。系统先由 Planner 把问题转换成结构化的 `TravelPlan`，再由 LangGraph Supervisor 根据共享状态依次调度天气 Agent、票务 Agent、景点工具和订单 Agent。天气、价格、时间和排序条件由确定性策略代码执行，避免让大模型直接做数值判断；涉及下单时使用 LangGraph 的 `interrupt/resume` 暂停流程，只有用户确认后才调用订单工具。

### 3. 1 分钟面试介绍

这个项目解决的是传统“多个独立功能接口不能协作”的问题。原项目有天气查询、票务查询和订单三个独立 Agent，但一次请求通常只能调用一个功能。我增加了一个运行在 Streamlit 进程内的 LangGraph Coordinator。

首先，Planner 使用大模型结构化输出 `TravelPlan`，提取出发地、目的地、日期、票种、任务列表、价格条件、时间条件、排序规则和是否需要下单。然后 Supervisor 根据 `completed_tasks`、`skipped_tasks`、天气结果和候选票等共享状态决定下一节点。天气和票务 Agent 通过 A2A 协议调用，各 Agent 再通过 MCP 调用天气、数据库查询和订单工具。

为了保证可靠性，我没有完全相信大模型的规划结果，而是增加了 `sanitize_plan` 做日期、城市、票种和中文枚举归一化，并限制 Supervisor 不能调用计划外 Agent、不能重复任务、不能在还有任务时提前结束。票务结果经过确定性策略过滤和排序；下单前通过 Human-in-the-loop 暂停，用户确认后将同一张 `selected_ticket` 作为结构化参数直接传给订单 MCP，避免大模型重新选票。我还增加了基于 `user_id` 隔离的 MySQL 长期偏好，新 Session 可检索并填充交通方式、票价预算和座位等缺失参数，当前请求始终优先。

### 4. 3 分钟展开框架

面试官让详细介绍时，按以下顺序讲：

1. **背景**：原有 Agent 相互独立，缺少跨 Agent 状态传递和条件执行。
2. **规划**：LLM 将自然语言转换为 Pydantic 约束的 `TravelPlan`。
3. **编排**：LangGraph 组织 Planner、Supervisor、Worker、Policy、Confirmation 和 Finalizer 节点。
4. **通信**：Coordinator 通过 A2A 调用 Agent，Agent 通过 MCP 调用工具。
5. **可靠性**：规则校验、确定性筛选、最大步数、禁止提前结束、结果标准化。
6. **安全性**：下单前中断并等待用户确认，确认后直接调用指定 MCP 工具。
7. **验证**：单元测试覆盖策略、状态路由、取消与确认分支，并完成本地七服务端到端联调。

---

## 二、技术栈与真实边界

### 技术栈

- Python
- LangGraph
- LangChain / ChatOpenAI 兼容接口
- Pydantic
- python-a2a
- MCP / FastMCP
- MySQL
- 高德天气 API
- Streamlit
- unittest / Streamlit AppTest

### 项目当前真实边界

- 票务数据来自本地 MySQL 演示数据，不是航空公司的实时生产数据。
- 订单 MCP 当前返回模拟预订成功，未接入支付、真实出票和用户账户系统。
- 景点推荐当前由 Coordinator 内的大模型结构化生成，并不是独立的 A2A 服务。
- 当前会话状态的 Checkpointer 使用 `InMemorySaver`，程序重启后短期对话状态不会持久化；稳定用户偏好单独保存在 MySQL，可跨 Session 使用。
- Streamlit 和 A2A 服务使用本地开发服务器，尚未按生产环境部署。
- 项目已有 160 条冻结 test 的离线 Fixture 评测和 89 项单元测试；尚无可宣称的线上 LLM 准确率、QPS 或 P99。

面试时主动说明这些边界，反而能体现工程诚信和对生产化差距的理解。

---

## 三、整体架构

```text
用户 / Streamlit
       |
       v
LangGraph Coordinator（同一 Streamlit 进程）
       |
       +-- Planner：自然语言 -> TravelPlan
       |
       +-- Supervisor：根据共享状态选择下一节点
       |
       +-- Weather Worker ------A2A------> Weather Agent ------MCP------> 高德天气
       |
       +-- Ticket Worker -------A2A------> Ticket Agent -------MCP------> MySQL
       |
       +-- Attraction Worker --> LLM 结构化生成景点推荐
       |
       +-- Policy Nodes：天气判断、票务过滤与排序
       |
       +-- Confirmation：interrupt / resume
       |
       +-- Order Worker --------A2A------> Order Agent --------MCP------> 模拟订单工具
       |
       v
Finalizer 汇总天气、票务、景点、跳过原因和订单结果
```

### 为什么有七个服务？

本地运行时包括：

1. Ticket MCP：8001
2. Weather MCP：8002
3. Order MCP：8003
4. Weather A2A Agent：5005
5. Ticket A2A Agent：5006
6. Order A2A Agent：5007
7. Streamlit 页面：8501

Coordinator 不单独占用端口，它运行在 Streamlit 进程内部。

### 一个复合请求如何执行？

以“查询北京天气，天气好的话订一张 2026 年 8 月 19 日长沙到北京的机票，并推荐三个景点”为例：

1. Planner 提取天气、票务、景点、订单四个任务。
2. Supervisor 先选择 Weather Worker。
3. Weather Agent 通过 MCP 查询天气。
4. Weather Policy 判断天气是否满足出行条件。
5. 如果天气不好，标记 ticket 和 order 为跳过，但 attraction 仍继续执行。
6. 如果天气合适，Ticket Agent 查询候选航班。
7. Ticket Policy 根据价格、时间、余票和排序规则选出候选票。
8. 到达订单任务时先进入 Confirmation 节点并暂停。
9. 用户取消则跳过订单；用户确认才把同一张票交给 Order Agent。
10. Finalizer 汇总结果。

---

## 四、核心数据结构

### 1. TravelPlan 是什么？

`TravelPlan` 是 Planner 对用户目标的结构化表示，主要字段包括：

- `ticket_type`：flight、train 或 concert
- `departure` / `destination`：出发地和目的地
- `date`：出发日期
- `quantity`：数量
- `tasks`：weather、ticket、attraction、order
- `weather_required_for_ticket`：天气是否是订票前置条件
- `filters`：价格、时间、余票等过滤条件
- `sorts`：价格或时间排序
- `action`：只查询或满足条件后预订
- `clarification`：信息不足时的追问
- `requires_confirmation`：是否需要用户确认

### 2. 为什么使用 Pydantic？

大模型输出本质上不稳定。Pydantic 可以把允许的字段、枚举、数据类型和数量范围写进 Schema，使 Planner 只能在明确范围内输出。例如任务只能是 weather、ticket、attraction、order，数量限制为 1 到 9。这样可以在进入执行层前发现格式和类型错误。

### 3. TravelState 保存什么？

`TravelState` 是所有 LangGraph 节点共享的状态，保存：

- 用户问题和对话消息
- 结构化计划
- 已完成、已跳过任务
- 天气结果和天气是否合适
- 原始候选票、过滤后的票和最终选中的票
- 景点结果
- 是否等待确认、是否已确认
- 订单结果
- 协作轨迹和错误
- 最终回答

### 4. metadata 和共享状态有什么区别？

metadata 通常是附着在数据上的描述信息，例如来源、时间和类型；共享状态是工作流运行过程中各节点共同读写的业务数据。这个项目中的 `TravelState` 更接近工作流上下文，而不是普通文档 metadata。

---

## 五、Planner 与 Query 理解

### 1. Planner 的作用是什么？

Planner 不直接执行工具，而是把自然语言目标拆成可执行计划。例如：

```text
用户：价格低于1000元，并且晚上8点以后有航班，就预订最便宜的一张。

计划：
- tasks: [ticket, order]
- price < 1000
- departure_time >= 20:00
- sort: price asc
- action: book_if_available
```

### 2. 为什么不能只用 if-else 解析用户问题？

if-else 适合稳定、明确的规则，但很难覆盖“便宜一点”“晚上的票”“天气好再买”等多样表达。大模型更擅长语义理解和槽位提取，程序更擅长可靠执行。因此本项目采用“LLM 规划 + 代码校验和执行”的组合。

### 3. 为什么不能完全相信 Planner？

大模型可能：

- 增加用户没要求的天气任务；
- 把“火车票”作为筛选值，而系统内部枚举是 `train`；
- 把 `20:00` 输出成缺少日期的时间；
- 信息已经完整却仍生成 clarification；
- 把预订请求错误识别成普通查询。

因此项目增加 `sanitize_plan`，对任务、票种、日期、路线、时间条件和 clarification 进行二次校验。

### 4. sanitize_plan 做了什么？

- 根据用户原句删除未请求的天气或景点任务；
- 识别航班、火车、高铁和演出票类型；
- 解析中文或横线格式日期；
- 补全“北京到上海”形式的路线；
- 把天气城市补入目的地；
- 把火车票、机票等中文值归一化为内部枚举；
- 把 `20:00` 与出发日期合并成完整时间；
- 根据“预订、买票、下单”确定是否加入 order；
- 信息齐全时清除大模型生成的错误追问。

### 5. 为什么还保留 LLM Planner，而不全部改成正则？

正则用于兜底和约束高风险字段，LLM 仍负责理解开放表达、复合意图和条件关系。二者不是替代关系，而是语义能力与确定性工程能力的结合。

---

## 六、Supervisor 与 LangGraph

### 1. Supervisor 是什么？

Supervisor 是多智能体系统中的调度者。它读取当前计划和共享状态，决定下一步调用天气、票务、景点、订单还是结束。

### 2. Planner 和 Supervisor 有什么区别？

- Planner：一开始制定“要做什么”的整体计划。
- Supervisor：运行过程中根据最新状态决定“下一步做什么”。

例如 Planner 计划先天气后票务，但天气结果是暴雨，Supervisor 会跳过依赖天气的票务和订单，继续执行不依赖天气的景点推荐。

### 3. 为什么使用 LangGraph？

这个场景不只是一次 Function Calling，而是存在：

- 多步骤任务；
- 条件分支；
- 多 Agent 共享状态；
- 循环调度；
- 中断与恢复；
- 最大执行步数；
- 可观察的节点轨迹。

LangGraph 用状态图显式表示节点和边，比把所有逻辑写在一个 Agent Loop 中更容易控制、测试和排错。

### 4. LangGraph 和普通工作流有什么区别？

普通工作流通常步骤固定；LangGraph 可以根据状态动态选择路径，并支持循环、持久化检查点和中断恢复。但本项目没有让图完全自由运行，仍通过规则保护关键业务边界。

### 5. Supervisor 是否完全由大模型决定？

不是。大模型提出 `next_action`，代码层会检查：

- 动作是否在允许列表；
- Agent 是否在用户计划中；
- 任务是否已经完成或跳过；
- 是否还有未完成任务，防止提前 finalizer；
- 订票是否满足天气前置条件；
- 是否已经选出票；
- 是否完成用户确认；
- 是否超过最大步数。

### 6. 如何防止 Supervisor 死循环？

项目维护 `completed_tasks`、`skipped_tasks` 和 `step_count`：

- 已完成任务不能重复执行；
- 跳过任务不再执行；
- 最大执行步数为 8；
- 达到上限后强制进入 Finalizer。

### 7. 为什么不能让 Supervisor 提前结束？

真实联调中出现过天气执行完后 Supervisor 直接选择 finalizer，导致景点任务没有执行。修复方式是计算计划中尚未完成且未跳过的任务，只要 `pending` 不为空，就不允许 finalizer。

### 8. Checkpointer 有什么用？

Checkpointer 保存图的运行快照。用户确认下单时，图在 Confirmation 节点中断；用户点击确认或取消后，使用同一个 `thread_id` 从原状态继续运行。

### 9. 为什么当前使用 InMemorySaver？

它部署简单，适合本地演示和功能验证。缺点是进程重启后状态丢失，也不适合多实例共享。生产环境可换成 Redis、PostgreSQL 等持久化 Checkpointer。

---

## 七、Agent、Function Calling、A2A 与 MCP

### 1. 什么是 Agent？

Agent 是由模型、目标、状态和工具调用循环组成的任务执行单元。它不仅生成文本，还可以决定使用什么工具、读取结果并继续执行。

### 2. Function Calling 等于 Agent 吗？

不等于。Function Calling 是模型输出结构化工具调用参数的能力；Agent 在此基础上增加任务目标、循环、状态、工具结果反馈和停止条件。一次 Function Calling 可能只是 Agent 的一步。

### 3. 原来的三个 Agent 为什么看起来只是三个功能？

因为它们彼此隔离，各自完成天气、查票或订票，没有统一共享状态，也不能根据上一步结果动态改变后续路径。增加 Coordinator 后，多个能力才形成了真正的任务协作链路。

### 4. A2A 是什么？

A2A 是 Agent-to-Agent 通信。Coordinator 不需要知道 Worker Agent 内部如何实现，只需要读取 Agent Card、发送 Task，并接收完成、失败或需要补充信息等状态。

### 5. MCP 是什么？

MCP 是模型或 Agent 与外部工具、数据源之间的标准协议。在本项目中：

- 天气 Agent 通过 MCP 调天气工具；
- 票务 Agent 通过 MCP 查询 MySQL；
- 订单 Agent 通过 MCP 调订单工具。

### 6. A2A 和 MCP 的区别是什么？

- A2A：Agent 与 Agent 之间协作，传递任务和结果。
- MCP：Agent 与工具或资源之间通信，完成具体能力调用。

一句面试口径：**A2A 解决谁和谁协作，MCP 解决 Agent 如何标准化调用工具。**

### 7. 为什么不让 Coordinator 直接调用所有 MCP？

直接调用也能实现，但会使 Coordinator 同时承担规划、业务理解和所有工具细节，耦合度高。通过 A2A 封装领域 Agent，可以独立升级天气、票务和订单逻辑，并让 Coordinator 只关注任务编排和共享状态。

### 8. Agent Card 是什么？

Agent Card 描述 Agent 的名称、地址、版本、能力、技能和示例，类似 Agent 的能力说明书。Coordinator 可以通过它发现并调用对应服务。

### 9. MCP 和普通 REST API 有什么区别？

REST API 是通用服务接口规范；MCP 面向模型工具调用，除了传输，还定义工具发现、参数 Schema、资源和会话等语义。底层仍可以使用 HTTP，但上层约定更适合 Agent 生态。

### 10. ReAct 能解决多 Agent 协作吗？

ReAct 适合单 Agent 按“思考—行动—观察”循环选择工具，但复杂业务还需要共享状态、条件分支、恢复和人工确认。可以在某个 Worker 内使用 ReAct，而跨 Agent 编排更适合 LangGraph 这类显式状态机。

---

## 八、票务条件执行

### 1. 为什么价格和时间条件不能交给大模型判断？

大模型适合理解“低于 1000 元”“晚上八点以后”的含义，但浮点比较、时间比较和排序必须由代码执行。否则可能出现漏选、错选或同一问题多次结果不一致。

### 2. FilterCondition 包含什么？

- `field`：price、departure_time、remaining_tickets 等白名单字段；
- `operator`：eq、lt、lte、gt、gte、between、in 等；
- `value`：比较值。

字段和操作符使用 Literal 白名单，避免模型生成任意字段或可执行表达式。

### 3. “最便宜”如何实现？

Planner 把“最便宜”转换成 `SortRule(field="price", order="asc")`。策略执行器先过滤不符合条件的候选票，再按价格升序排序，第一条作为 `selected_ticket`。

### 4. “晚上八点以后”如何实现？

Planner 生成 `departure_time >= 20:00`，`sanitize_plan` 将其与出发日期组合为完整时间，例如 `2026-08-19T20:00:00`，策略层再用 datetime 比较。

### 5. 为什么查询全部候选票后再由 Coordinator 筛选？

这样可以把用户策略与票务 Agent 解耦，并保留可解释的候选集。但生产环境数据量大时，应该把明确的日期、城市、价格和时间条件尽量下推到 SQL，Coordinator 只进行二次业务筛选。

### 6. 如何处理没有符合条件的票？

`eligible_tickets` 为空时不设置 `selected_ticket`；如果计划包含订单，则把 order 标记为跳过，不进入确认和下单节点。

### 7. 如何保证下单的是刚才选中的票？

确认页面展示 `selected_ticket`。用户确认后，Coordinator 把它序列化为结构化 JSON 传给 Order Agent；Order Agent 根据 `ticket_type` 直接选择对应 MCP 工具，并把班次、日期、座位和数量作为确定参数传入，不再让大模型重新查询或重新选票。

---

## 九、Human-in-the-loop 与下单安全

### 1. 为什么下单前必须确认？

下单属于有副作用操作，可能涉及库存、支付和真实用户权益。即使模型已经选出票，也不能直接执行。系统需要把选中的票、时间、价格、舱位和数量展示给用户，并获得明确授权。

### 2. interrupt/resume 如何工作？

Confirmation 节点调用 `interrupt`，LangGraph 把当前状态保存到 Checkpointer，并向界面返回确认内容。用户点击后，页面用相同 `thread_id` 调用 `Command(resume=True/False)`：

- True：进入 Order Agent；
- False：把 order 标记为 skipped，然后结束。

### 3. 为什么不能只在前端弹窗，后端继续运行？

前端弹窗只是显示控制，无法保证后端没有执行。真正安全的做法是让工作流本身停在确认节点，确认结果成为状态机继续执行的必要条件。

### 4. 如何避免重复下单？

当前通过图状态中的 `completed_tasks`、Confirmation 状态和同一 thread 的恢复逻辑防止一次流程重复执行。生产环境还需要：

- 幂等键；
- 数据库唯一约束；
- 订单状态机；
- 分布式锁或原子库存扣减；
- 超时与补偿机制。

### 5. 为什么确认后订单工具改成直接 MCP 调用？

早期实现再次让 LLM选择工具，出现过外部模型连接失败，而且理论上存在重新理解并改变参数的风险。确认后的参数已经完整，因此直接按票种映射到 `order_flight`、`order_train` 或 `order_concert` 更稳定、更低延迟，也更符合最小权限原则。

---

## 十、结果标准化与错误处理

### 1. 为什么需要结果标准化？

不同 Agent 可能返回 JSON、自然语言或状态消息，而策略层需要统一的 `WeatherResult` 和 `TicketCandidate`。标准化层隔离了通信格式和业务执行格式。

### 2. 票务结果如何标准化？

优先使用确定性解析：

1. 如果是 MCP JSON，直接解析字段；
2. 如果是票务 Agent 固定中文行格式，用正则解析航班、车次、时间、票价和余票；
3. 确定性解析失败后，才调用大模型结构化输出作为兜底。

### 3. 为什么确定性解析优先于 LLM？

数据库结果本来就是结构化事实，再调用 LLM 会增加延迟、费用和不确定性。真实联调中就出现过票务 Agent 明明返回三条航班，大模型却标准化为空列表的问题。

### 4. 天气结果如何判断好坏？

天气标准化为城市、天气文本、风力、降水和温度。策略层根据雨、雪、雷、冰雹、台风等不利天气词以及风力等条件作确定性判断。该规则只是演示策略，生产环境应由业务定义阈值。

### 5. Agent 失败时应该怎么办？

当前项目主要返回失败消息并停止相关分支。生产化可以进一步加入：

- 超时和有限重试；
- 指数退避；
- 熔断与降级；
- 备用模型或备用数据源；
- 可恢复错误和不可恢复错误分类；
- 错误写入 Trace 和监控系统。

---

## 十一、项目中实际解决的问题

### 问题 1：多个 Agent 只是独立功能，没有协作

**原因**：没有统一规划者、共享状态和跨步骤路由。

**解决**：增加 LangGraph Coordinator，把原有 Agent 作为 Worker，通过 Supervisor 动态调度。

### 问题 2：票务 Agent 返回结果，但 Coordinator 得到空列表

**原因**：票务 Agent 把 MCP JSON格式化为中文文本，随后依赖 LLM 二次结构化，模型偶尔输出空列表。

**解决**：增加固定中文格式和 JSON 的确定性解析，只有解析失败才使用 LLM。

### 问题 3：新增数据库数据后，长期运行的票务服务查不到

**原因**：MySQL 长连接处于事务快照中，不能及时看到新提交的数据。

**解决**：连接开启 `autocommit=True`，让查询看到最新已提交数据。

### 问题 4：Supervisor 提前结束

**原因**：大模型在还有景点任务时选择 finalizer。

**解决**：代码计算 pending tasks，只要还有未完成任务就拒绝提前结束。

### 问题 5：模型输出“火车票”，内部枚举使用 train

**原因**：自然语言值和内部 Schema 值不一致，导致过滤后候选票为空。

**解决**：在 `sanitize_plan` 中统一中文票种与内部枚举。

### 问题 6：确认后的订单仍依赖 LLM 工具选择

**原因**：多余的模型调用带来网络依赖和参数漂移风险。

**解决**：确认后根据结构化票种直接映射 MCP 工具，保证使用同一张票。

### 问题 7：天气不好时不能影响其他独立任务

**处理**：天气不好只跳过依赖天气的 ticket 和 order，景点推荐继续运行，体现任务依赖而不是全局失败。

---

## 十二、高频面试八股问答

### 1. 你的项目为什么算多智能体，而不只是多个接口？

因为系统不只是分别暴露天气、票务和订单接口，而是由 Coordinator 统一规划任务，通过共享 `TravelState` 传递上一步结果，Supervisor 根据天气、候选票和用户确认动态改变后续路径。Agent 之间存在任务依赖和结果协作。

### 2. 多智能体相比单 Agent 有什么优点？

领域职责清晰、工具权限隔离、单个上下文更小、各 Agent 可以独立测试和升级。缺点是网络调用更多、状态一致性更复杂、排错和成本控制更困难。

### 3. 为什么不用一个大模型直接回答所有问题？

天气、票务和订单都依赖实时外部数据或有副作用操作，大模型自身没有这些事实，也不能安全执行订单。模型负责理解与规划，工具负责获得事实和执行动作。

### 4. 为什么不用一个 ReAct Agent 调所有工具？

可以做原型，但复杂流程中工具数量、状态、条件分支和确认逻辑会集中在一个循环里，难以测试和约束。本项目用 LangGraph 显式拆分节点，便于保证顺序、跳过规则和中断恢复。

### 5. LangGraph 的节点和边分别代表什么？

节点是 Planner、Supervisor、Worker、Policy、Confirmation、Finalizer 等处理单元；边表示执行关系，条件边根据状态决定下一个节点。

### 6. 如何实现上下文和长期记忆？

短期业务上下文保存在 `TravelState`，同一会话通过 `user_id:session_id` 组成的 `thread_id` 与 Checkpointer 关联。长期记忆使用 MySQL 保存允许列表内的稳定旅行偏好，每轮在 Planner 前按 `user_id` 读取，只填充当前计划缺失的交通方式、预算、座位/舱位和出发时段；当前请求明确给出的条件优先，临时偏好不入库。

### 7. 为什么只传最近六条消息？

减少 Token 消耗和历史噪声，避免无关对话影响计划。更复杂场景可增加摘要记忆和检索式长期记忆。

### 8. 如何做结构化输出？

使用 `with_structured_output(PydanticModel)`，让模型按照 `TravelPlan`、`SupervisorDecision` 或 `AttractionList` 输出，再由 Pydantic 验证。

### 9. 结构化输出失败怎么办？

对 Agent 结果标准化设置有限重试；对可确定解析的数据优先使用 JSON 或正则；仍失败则抛出明确异常并停止相关分支。生产环境需要配合降级和告警。

### 10. Prompt Engineering 在哪里？

Planner Prompt 描述任务类型、允许字段、条件语义和缺失信息规则；Supervisor Prompt提供计划、完成任务、跳过任务、天气状态和候选数量，要求选择下一动作；景点 Prompt 要求返回三个结构化景点。

### 11. 如何防止 Prompt Injection？

当前主要依靠结构化 Schema 和动作白名单。生产环境还要把系统指令与用户内容隔离、限制工具权限、校验所有参数、对外部文本做不可信数据处理，并对高风险工具增加人工审批。

### 12. 为什么动作要使用白名单？

防止模型生成不存在的节点或任意工具名。Supervisor 只能在 weather、ticket、attraction、order、finalizer 等固定动作中选择。

### 13. 为什么订单数量限制为 1 到 9？

这是输入层的业务约束示例，避免模型产生负数、零或异常大批量操作。真实上限应由业务和库存系统决定。

### 14. 怎么防止模型生成 DELETE / DROP？

票务和天气的数据库执行边界都会调用 `validate_read_only_query`。它只接受单条 `SELECT`，拒绝注释、堆叠语句、`DELETE/DROP/UPDATE/INSERT`、`INTO OUTFILE`和未授权表；拒绝后不会调用 `cursor.execute`。长期记忆不接受 LLM SQL，而是通过 Repository 中的固定参数化 SQL 写入。生产环境还应配合数据库只读账户和执行超时。

### 15. 为什么 MySQL 连接要使用 utf8mb4？

项目包含中文城市和舱位，需要完整 Unicode 支持；utf8mb4 也能覆盖四字节字符，避免乱码或写入失败。

### 16. autocommit 有什么作用？

让每条语句自动提交，并避免长连接长期停留在旧事务快照中。本项目主要是读取演示数据，开启后可以及时看到新导入的数据。

### 17. 如何保证库存一致性？

当前订单工具是模拟的，没有真正扣库存。生产实现应在数据库事务中使用条件更新，例如 `remaining_seats >= quantity` 时原子扣减，结合幂等订单号、防超卖锁和失败回滚。

### 18. 如果订单成功但响应丢失怎么办？

客户端重试可能导致重复下单，因此要使用幂等键。再次请求时先查询该幂等键对应的订单状态，而不是重新执行。

### 19. 如果扣库存成功但支付失败怎么办？

需要订单状态机和补偿事务：锁定库存、创建待支付订单、支付成功后确认；超时或失败时释放库存。跨服务可使用 Saga、事务消息或可靠事件。

### 20. 如何支持流式输出？

可以使用 LangGraph 的 stream 逐节点返回事件，服务端通过 SSE 或 WebSocket 推送 Planner、Agent 调用和最终生成片段。工具调用结果仍应完整校验后再进入后续节点。

### 21. SSE 和 WebSocket 如何选择？

如果主要是服务端单向推送模型 Token 和轨迹，SSE 更简单；如果需要双向实时控制、语音或复杂交互，WebSocket 更合适。

### 22. 如何支持高并发？

将 Streamlit 演示层替换为 FastAPI；使用异步 HTTP 客户端和连接池；服务无状态化；Checkpointer 放到 Redis/PostgreSQL；对模型和第三方 API 做限流、超时、熔断和缓存；耗时任务放入消息队列。

### 23. 哪些数据适合缓存？

天气短时间结果、热门路线查询和 Agent Card 可以缓存；余票和订单状态变化快，应设置很短 TTL 或直接查实时源；下单操作不能用普通结果缓存代替幂等控制。

### 24. 如何做服务发现？

当前地址写在本地配置中。生产环境可使用配置中心、服务注册中心或 Kubernetes Service；A2A Agent Card 提供能力描述，但地址治理仍需要基础设施支持。

### 25. 如何做可观测性？

为每次请求生成 trace_id，记录 Planner 计划、节点耗时、Agent/MCP 调用、重试次数、模型 Token、错误类型和最终分支；使用结构化日志和 OpenTelemetry 接入指标、日志和链路追踪。

### 26. 协作轨迹有什么价值？

它让用户和开发者看到 Planner、Supervisor、Worker 和 Policy 的执行顺序，可用于解释结果、定位错误和评估 Agent 的决策质量。

### 27. 如何评估多智能体系统？

可以分层评估：

- Planner：任务和槽位识别准确率；
- Router：正确 Agent 选择率；
- Tool：参数准确率和调用成功率；
- Policy：条件筛选正确率；
- End-to-end：任务完成率；
- Safety：未经确认下单率应为 0；
- Performance：平均/P95 延迟、Token 成本和每次任务工具调用数。

### 28. 为什么不能只看最终答案准确率？

多智能体失败可能来自规划、路由、工具、参数、数据源或生成层。只看最终答案无法定位问题，必须评估中间轨迹和每个节点。

### 29. 如何构建测试集？

我将数据拆成可调试的 60 条 dev 和冻结的 160 条 test。test 包含 70 条规划、40 条工作流和 50 条长期记忆样本，覆盖单/多意图、信息缺失、天气分支、票务策略、确认/取消、临时偏好、当前要求覆盖长期偏好和跨用户隔离。每个 test 文件记录 SHA-256，正式评分后不再因单个错例修改。

### 30. 项目做了哪些测试？

89 项单元测试覆盖 Schema、Planner 清洗、Supervisor 防越权、策略分支、确认/取消、SQL 只读边界、多用户 Repository 事务回滚、长期偏好提取/应用、Streamlit 会话和评测器。此外，160 条冻结 test 使用真实 Coordinator 与确定性 Fixture 运行；它不代表真实 LLM/A2A/MCP 线上准确率。

### 31. 单元测试中如何避免真的调用外部模型？

通过 Fake LLM、Fake Clients 和 mock 工具返回固定结果，只验证节点路由、状态变化和策略逻辑。端到端测试再单独连接真实服务。

### 32. 如何测试“取消不能下单”？

图运行到 interrupt 后使用 `Command(resume=False)` 恢复，断言 order 不在实际调用记录中、位于 skipped_tasks 中，并且没有 order_result。

### 33. 如何测试确认后是同一张票？

先让策略选中 HU7636，恢复时传 True，然后断言 Order Agent 收到的 `selected_ticket.number` 仍为 HU7636，而不是重新查询后的其他票。

### 34. 项目最核心的工程思想是什么？

让大模型负责理解和规划，让代码负责约束和执行，让外部系统提供事实，让用户批准高风险动作。

### 35. 这个项目最大的不足是什么？

当前仍是本地工程原型：短期 Checkpointer 未外部持久化，订单和票务都是演示数据，Agent 服务缺少认证、幂等和生产可观测性；目前正式指标来自确定性 Fixture 离线评测，尚未完成真实 LLM/A2A/MCP 集成评测和压测。

---

## 十三、代码对应关系

| 模块 | 主要职责 |
|---|---|
| `SmartVoyage/app.py` | Streamlit 页面、会话初始化、确认/取消按钮、轨迹展示 |
| `SmartVoyage/main.py` | Coordinator 命令行入口 |
| `coordinator/schemas.py` | TravelPlan、TravelState、TicketCandidate 等 Schema |
| `coordinator/graph.py` | 图构建、生产依赖、Planner/Supervisor Prompt、计划清洗 |
| `coordinator/nodes.py` | Planner、Supervisor、Worker、Policy、Confirmation、Finalizer 节点 |
| `coordinator/policy.py` | 确定性天气判断、票务过滤和排序 |
| `coordinator/clients.py` | A2A 调用、天气和票务结果标准化 |
| `coordinator/ui.py` | 图结果、确认信息和轨迹的页面格式化 |
| `memory/policy.py` | 长期偏好白名单、值校验与“当前请求优先”的确定性应用 |
| `memory/mysql_repository.py` | 按 user_id 隔离的偏好读写、参数化 SQL 与事件审计 |
| `evaluation/` | JSONL 数据集、离线图执行器、分层指标和 JSON/CSV 报告 |
| `a2a_server/weather_server.py` | 天气 Agent |
| `a2a_server/ticket_server.py` | 票务 Agent、自然语言转 SQL、票务结果格式化 |
| `a2a_server/order_server.py` | 订单 Agent、确认票结构校验、直接调用订单 MCP |
| `mcp_server/mcp_weather_server.py` | 天气 MCP 工具 |
| `mcp_server/mcp_ticket_server.py` | 票务查询 MCP 工具 |
| `mcp_server/mcp_order_server.py` | 火车、飞机和演出票模拟预订工具 |
| `query_data/query1.py` | MySQL 查询连接与执行 |
| `query_data/sql_guard.py` | 单条 SELECT、授权表和危险 SQL 关键字校验 |

---

## 十四、简历写法

### 项目名称

**SmartVoyage——基于 LangGraph、A2A 与 MCP 的多智能体旅行助手**

### 技术栈

Python、LangGraph、LangChain、Pydantic、A2A、MCP、MySQL、高德天气 API、Streamlit

### 简历项目职责（推荐版）

- 基于 LangGraph 实现旅行任务 Coordinator，将自然语言请求结构化为包含天气、票务、景点和订单任务的 `TravelPlan`，通过共享状态和 Supervisor 动态调度多个领域 Agent。
- 使用 Pydantic 约束任务、条件及工具参数，并增加计划清洗、动作白名单、最大步数和未完成任务保护；将价格、时间、余票等条件交由确定性策略执行，降低模型误判风险。
- 采用 A2A 完成 Coordinator 与天气、票务、订单 Agent 间通信，各 Agent 通过 MCP 调用高德天气、MySQL 票务查询及订单工具，实现 Agent 编排与工具执行解耦。
- 基于 LangGraph `interrupt/resume` 实现下单前 Human-in-the-loop，确认后将同一张候选票结构化传给订单 Agent 并直接调用指定 MCP 工具，避免重复选票和未经授权下单。
- 使用 MySQL 保存按 `user_id` 隔离的稳定旅行偏好，通过 `session_id` 区分会话；新 Session 中检索并补全交通方式、预算、座位/舱位和出发时段，当前请求可覆盖长期偏好。
- 构建 160 条冻结 test 的分层评测，在确定性 Fixture 离线环境中完成 Agent 选择 40/40、多轮任务 50/50、偏好检索 38/38，230 次用户隔离检查未发现跨用户泄漏。

### 不建议写的内容

- “支持线上每秒数千请求”——没有压测依据。
- “订单成功率 99.9%”——当前订单是模拟工具。
- “真实 LLM 意图准确率 98.7%”——该数字是固定 TravelPlan 输入后的离线任务 Micro-F1，不是真实 LLM 规划准确率。
- “景点 Agent 独立部署”——当前景点能力在 Coordinator 内调用 LLM。
- “已接入真实航空出票和支付”——当前没有。

---

## 十五、面试追问模板

### 追问 1：你在这个项目里具体做了什么？

我不是只把几个接口启动起来，而是在原有天气、票务、订单 Agent 基础上增加了 LangGraph Coordinator。我主要负责结构化任务规划、共享状态设计、Supervisor 路由、确定性条件执行、Human-in-the-loop 下单确认、A2A 结果标准化，以及单元和端到端测试。

### 追问 2：最难的问题是什么？

最难的不是调用模型，而是控制模型的不确定性。例如真实联调时票务 Agent 已经返回了三条航班，但第二次 LLM 结构化却返回空列表；Supervisor 也出现过提前结束。我分别用确定性文本解析和 pending-task 保护解决，形成“LLM 给建议、代码做最终约束”的架构。

### 追问 3：为什么你这个不是普通 Function Calling？

普通 Function Calling 通常是一次模型选择一次工具。本项目有计划拆解、多节点状态、条件依赖、多个 Agent 的结果传递、循环调度以及用户确认后的断点恢复，所以使用了 LangGraph 状态图。

### 追问 4：如果重做一次，你会怎么改？

我会优先做四件事：第一，用 FastAPI 替换 Streamlit 作为正式后端并提供 SSE；第二，把短期 Checkpointer 放到 PostgreSQL 或 Redis；第三，把模型生成 SQL 改成结构化查询条件加程序构造 SQL；第四，启动真实 A2A/MCP 服务后补充独立集成集，单独报告 LLM 规划、SQL 执行、端到端成功率和成本。

### 追问 5：为什么这个项目适合 AI 应用后端岗位？

它不仅涉及 Prompt 和模型调用，还包含服务拆分、协议通信、数据库、状态管理、异步调用、条件执行、安全确认、错误处理、测试和可观测性，体现的是把大模型能力落到可靠后端工作流中的能力。

---

## 十六、最后背诵清单

面试前确保能不看文档回答：

1. 项目一句话、30 秒和 1 分钟介绍。
2. 七个服务分别是什么，Coordinator 为什么没有单独端口。
3. Planner、Supervisor、Worker、Policy、Confirmation 的区别。
4. A2A、MCP、Function Calling、Agent 的区别。
5. TravelPlan 和 TravelState 保存什么。
6. 为什么使用 Pydantic 和 sanitize_plan。
7. 为什么数值条件必须由代码执行。
8. 如何防止 Supervisor 越权、重复和提前结束。
9. 天气不好为什么仍能推荐景点。
10. interrupt/resume 如何保证确认后才下单。
11. 如何保证确认和下单是同一张票。
12. 项目中解决过的四个真实问题。
13. 当前系统的真实边界和四个生产化方向。

### 最终总结句

这个项目的核心不是“用了几个 Agent”，而是通过 LangGraph 把多个 Agent 组织成一个有共享状态、条件分支、确定性策略、安全确认和可验证轨迹的完整业务流程。
