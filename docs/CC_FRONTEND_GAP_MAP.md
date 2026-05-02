# CC Frontend 对齐差距清单

## 范围

- 参考源：`C:\Users\32020\Desktop\cc\desktop\src`
- 目标端：`C:\Users\32020\Desktop\documentmanagement_agent\frontend\src`
- 目标：判断 `cc` 的前端能力和交互结构，哪些已经迁入 DocMind，哪些还未迁入，哪些可以直接照搬，哪些必须改造成文档平台语义。

## 结论

- 当前只完成了 `cc` 的壳层风格、部分聊天页状态组织、部分设置入口和基础主题切换。
- 没有完成 `cc` 的完整页面体系、组件体系、任务体系、工作区体系、插件/技能/MCP 体系。
- 如果按“外观抄 + 语义替换”衡量，完成度大约在前端表层的 `30% - 40%`。
- 如果按“功能与前端都照抄后转化”衡量，整体还未完成。

## 一对一映射

### 1. App 壳层

#### cc 现状

- `components/layout/AppShell.tsx`
- `components/layout/Sidebar.tsx`
- `components/layout/TabBar.tsx`
- `components/layout/ContentRouter.tsx`
- `components/layout/StatusBar.tsx`
- `components/layout/TitleBar.tsx`
- `components/layout/WindowControls.tsx`
- 多 tab、多 session、启动错误视图、桌面启动初始化

#### DocMind 现状

- 已有：
  - `layouts/AppLayout.vue`
  - 顶栏、侧边栏、账号菜单、最近会话、主题切换
- 缺失：
  - 多 tab 体系
  - 内容路由容器分层
  - 状态栏
  - 启动错误视图
  - 桌面窗口控制

#### 判断

- `部分对齐`

#### 迁移建议

- 可直接借鉴：
  - 侧边栏展开/收起结构
  - 主内容容器结构
  - 全局提示层组织方式
- 需要改造：
  - `TabBar` 不能直接照搬，要改成“会话 / 检索 / 文档 / 管理”的平台语义
- 不该直接搬：
  - `WindowControls`
  - 桌面端专用启动逻辑

### 2. 聊天页

#### cc 现状

- 页面：
  - `pages/ActiveSession.tsx`
  - `pages/EmptySession.tsx`
- 组件：
  - `AssistantMessage.tsx`
  - `UserMessage.tsx`
  - `MessageList.tsx`
  - `ChatInput.tsx`
  - `ThinkingBlock.tsx`
  - `ToolCallBlock.tsx`
  - `ToolResultBlock.tsx`
  - `ToolCallGroup.tsx`
  - `InlineTaskSummary.tsx`
  - `SessionTaskBar.tsx`
  - `StreamingIndicator.tsx`
  - `CodeViewer.tsx`
  - `DiffViewer.tsx`
  - `AttachmentGallery.tsx`
  - `ImageGalleryModal.tsx`
  - `FileSearchMenu.tsx`
  - `PermissionDialog.tsx`
  - `ComputerUsePermissionModal.tsx`

#### DocMind 现状

- 已有：
  - `views/ChatView.vue`
  - 历史会话 / 空白引导 / 对话中 三种状态
  - 模型选择
  - 快捷问题
  - 引用展示
  - 反馈、复制、重试
- 缺失：
  - thinking/tool call/tool result 的块级渲染
  - code/diff 查看器
  - 附件展示层
  - 文件搜索弹层
  - 权限确认弹层
  - 会话任务条
  - 更细粒度的消息组件拆分

#### 判断

- `只完成页面外壳，没有完成组件能力层`

#### 迁移建议

- 可直接照搬：
  - `MessageList` 的分层思想
  - `AssistantMessage` / `UserMessage` 的拆分方式
  - `StreamingIndicator` 的位置关系
- 需要改造：
  - `ToolCallBlock` / `ToolResultBlock` 要改成 DocMind 的“检索 / 重排 / 证据 / 审查”语义
  - `InlineTaskSummary` 要改成“文档处理 / 训练 / 评估 / 维护任务”摘要
- 高优先级缺口：
  - 消息组件化
  - tool/thinking 可视化
  - 任务条

### 3. 设置体系

#### cc 现状

- 页面：
  - `pages/Settings.tsx`
  - `pages/TerminalSettings.tsx`
  - `pages/McpSettings.tsx`
  - `pages/AdapterSettings.tsx`
  - `pages/ComputerUseSettings.tsx`
- 组件：
  - `components/settings/ClaudeOfficialLogin.tsx`

#### DocMind 现状

- 已有：
  - `views/SettingsView.vue`
  - 账号菜单中的设置入口
  - 主题切换
  - 部分偏好和设备入口
- 缺失：
  - 二级设置子页的完整信息架构
  - 终端/MCP/Adapter/Computer Use 这种细粒度页面

#### 判断

- `只完成轻量设置页，不是完整设置子系统`

#### 迁移建议

- 可直接借鉴：
  - 左侧二级导航结构
  - 设置区块的分栏布局
- 需要改造：
  - `Terminal/MCP/Adapter` 需转成 DocMind 的
    - 模型与推理
    - 检索与索引
    - 移动端与推送
    - 安全与审计

### 4. 任务与自动化

#### cc 现状

- 页面：
  - `pages/ScheduledTasks.tsx`
  - `pages/ScheduledTasksEmpty.tsx`
  - `pages/ScheduledTasksList.tsx`
  - `pages/NewTaskModal.tsx`
- 组件：
  - `components/tasks/TaskList.tsx`
  - `components/tasks/TaskRow.tsx`
  - `components/tasks/TaskRunsPanel.tsx`
  - `components/tasks/PromptEditor.tsx`
  - `components/tasks/DayOfWeekPicker.tsx`

#### DocMind 现状

- 后端已有：
  - runtime task store
  - maintenance
  - 训练/评估/导出等任务链路
- 前端已有：
  - 管理页里有局部任务/监控面板
- 缺失：
  - 独立任务工作台
  - 任务创建/运行/历史/重试/审计一体视图

#### 判断

- `后端有，前端没做成产品化工作台`

#### 迁移建议

- 这是最值得继续抄的一块
- 可直接转化为：
  - 定时维护任务
  - 训练任务
  - 评估任务
  - 文档重处理任务

### 5. 工作区与会话控制

#### cc 现状

- 页面：
  - `pages/SessionControls.tsx`
  - `pages/ToolInspection.tsx`
- 组件：
  - `components/workspace/WorkspacePanel.tsx`
  - `components/workspace/WorkspaceCodeSurface.tsx`
  - `components/layout/StatusBar.tsx`

#### DocMind 现状

- 基本缺失

#### 判断

- `未迁移`

#### 迁移建议

- 不建议照搬代码工作区
- 可以转化成：
  - 检索工作台
  - 证据工作台
  - 工具调用检查视图
  - Runtime trace 回放视图

### 6. 插件 / 技能 / MCP / Team

#### cc 现状

- 页面：
  - `pages/AgentTeams.tsx`
  - `pages/McpSettings.tsx`
- 组件：
  - `components/plugins/*`
  - `components/skills/*`
  - `components/teams/*`
- stores：
  - `pluginStore.ts`
  - `skillStore.ts`
  - `teamStore.ts`
  - `mcpStore.ts`

#### DocMind 现状

- 后端有一部分 agent/runtime/config 能力
- 前端几乎没有对应页面

#### 判断

- `大部分未迁移`

#### 迁移建议

- 可以选做，不是第一优先级
- 若迁移，应改为：
  - Agent 策略
  - 模型配置
  - 工具策略
  - 扩展插件
  - 租户能力包

### 7. Store 体系

#### cc 现状

- 大量 store：
  - `chatStore`
  - `sessionStore`
  - `sessionRuntimeStore`
  - `taskStore`
  - `settingsStore`
  - `tabStore`
  - `uiStore`
  - `workspacePanelStore`
  - `workspaceChatContextStore`
  - `pluginStore`
  - `providerStore`
  - `teamStore`

#### DocMind 现状

- 只有：
  - `auth.ts`
  - `chat.ts`
  - `documents.ts`
  - `theme.ts`

#### 判断

- `前端状态管理层明显偏薄`

#### 迁移建议

- 后续至少应新增：
  - `runtime.ts`
  - `tasks.ts`
  - `settings.ts`
  - `ui.ts`
  - `notifications.ts`
  - `adminRuntime.ts`

### 8. API 层

#### cc 现状

- API 面非常宽：
  - sessions
  - settings
  - websocket
  - tasks
  - models
  - providers
  - plugins
  - skills
  - mcp
  - filesystem
  - terminal

#### DocMind 现状

- 已有：
  - auth
  - chat
  - documents
  - search
  - admin
  - notifications
- 缺失：
  - 任务 API 的前端消费层
  - runtime inspect / replay 的产品化 API 封装
  - 更细粒度设置 API 封装

#### 判断

- `核心业务 API 已有，但前端消费层不完整`

## 最值得优先抄的部分

### P0

- 聊天消息组件体系
- tool/thinking/result 块渲染
- 任务工作台
- 设置页二级导航与分区结构

### P1

- runtime/任务/store 分层
- 管理端里更像 `cc` 的 inspect / status / trace 视图

### P2

- 插件/技能/MCP/team 这类高级工作台
- 桌面端专用壳层能力

## 不建议直接照搬的部分

- Electron/Tauri/桌面窗口控制
- Computer Use 专用交互
- 代码工作区面板原样照搬
- 面向通用 agent 产品的插件/团队命名

## 建议的 DocMind 转化方向

### `cc` -> `DocMind`

- `ScheduledTasks` -> 训练/评估/维护任务中心
- `ToolInspection` -> 工具调用与证据链检查台
- `WorkspacePanel` -> 检索与引用工作台
- `Settings` 子页 -> 模型/检索/安全/移动端设置
- `SessionTaskBar` -> 当前对话运行态条
- `ThinkingBlock` -> 检索/审查/降级过程展示

## 当前明确结论

- `cc` 的前端没有抄完
- 现在只是“借了外观骨架和部分页面感”
- 真正差距最大的不是颜色和排版，而是：
  - 组件层没迁
  - 任务层没迁
  - store 层没迁
  - 工作台层没迁

## 下一步执行顺序

1. 聊天消息组件化
2. 任务中心
3. 设置二级信息架构
4. runtime / inspect / trace 工作台
5. 再决定是否迁移插件/技能/MCP 风格
