# DocMind 本地环境与脱敏配置指南

本文档面向公开仓库使用者，目标是让别人把项目下载到自己的电脑后，知道哪些内容需要自己配置，哪些功能可以直接运行，哪些配置不能提交回仓库。

## 1. 下载后能直接做什么

在不补 Firebase、不补微信、不接入外部商业模型密钥的情况下，以下内容可以按当前仓库默认方式启动并验证：

- Docker Compose 启动前后端与基础设施
- Web 端登录
- 文档上传、解析、入库、列表、状态推进
- 基础检索和 SSE 问答
- 管理端健康检查、系统状态、评估与运行时页面

以下能力属于可选增强，需要你自己的云侧配置：

- Android Firebase 推送
- 微信小程序订阅消息推送
- 外部 LLM / Embedding / Reranker 商业服务密钥
- 生产环境专用账号、域名、证书和持久化策略

## 2. 本机前置条件

建议至少准备：

- Windows 10/11 或其他可运行 Docker Compose 的系统
- Docker Desktop
- Git
- Python 3.11+
- Node.js 20+
- 可联网拉取 Docker 镜像和 Ollama 模型
- 建议内存 16 GB 及以上；首次完整起栈时磁盘建议预留 20 GB 以上

如果你要构建 Android App，还需要：

- Android Studio
- Android SDK
- JDK 17

已知事项：

- 当前 Android 工程使用 Android Gradle Plugin `8.2.1`
- 若本机仍是 Java 8，Gradle 会在解析 classpath 时失败
- 建议直接把 `JAVA_HOME` 切到 JDK 17 后再执行 Android 构建

## 3. 首次启动 Web / Docker 开发栈

### 第一步：复制环境模板

在仓库根目录执行：

```powershell
Copy-Item .env.example .env
```

`.env.example` 中的默认值主要用于本地开发演示，不适合生产环境直接使用。至少建议你自行替换这些项：

- `APP_SECRET_KEY`
- `JWT_SECRET_KEY`
- `BOOTSTRAP_DEMO_ADMIN_PASSWORD`
- `POSTGRES_PASSWORD`
- `NEO4J_PASSWORD`
- `MINIO_SECRET_KEY`

## 4. 启动 Docker 栈

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

启动完成后，可选拉取默认 Ollama 模型：

```powershell
docker exec docmind-ollama ollama pull qwen2.5:1.5b
docker exec docmind-ollama ollama pull nomic-embed-text
```

## 5. 最小验收

### 健康检查

```powershell
Invoke-RestMethod http://localhost:18000/health
```

### 页面入口

- 前端：`http://localhost:15173`
- 后端：`http://localhost:18000`
- OpenAPI：`http://localhost:18000/docs`
- Flower：`http://localhost:15555`

### 默认演示账号

- 用户名：`admin_demo`
- 密码：`Password123`

这组口令只用于本地开发和公开仓库演示。准备长期使用或部署到服务器前，必须改掉。

### 自动化预检

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\release-preflight.ps1
```

## 6. 哪些文件不能提交

公开仓库默认不应提交以下内容：

- `.env`
- `secrets/`
- `project.private.config.json`
- Android 真正的 `frontend/android/app/google-services.json`
- 任意私有证书、密钥、service account、访问令牌
- 本地生成的报告、缓存、训练产物、上传测试样本

当前仓库已经通过 `.gitignore` 屏蔽了大部分此类路径，但在提交前仍建议手动执行一次：

```powershell
git status --short
```

## 7. Firebase / Android 如何自己配置

如果你只跑 Web 端，这一节可以跳过。

### 仓库当前的设计

- 真实的 `frontend/android/app/google-services.json` 不再随仓库提交
- 仓库保留 `frontend/android/app/google-services.example.json` 作为模板
- Android 构建脚本在缺少 `google-services.json` 时会跳过 Google Services 插件，因此 Web 主链路不会因此失效

### 你自己的配置步骤

1. 进入 Firebase Console，新建你自己的项目
2. 在该项目中新增 Android App，包名保持与当前工程一致：`com.docmind.agent`
3. 根据需要补充 SHA-1 / SHA-256 指纹
4. 下载 Firebase 提供的 `google-services.json`
5. 将它保存到：

```text
frontend/android/app/google-services.json
```

6. 不要把这个真实文件提交到 GitHub

如果你只是想先了解结构，也可以先查看模板文件：

```text
frontend/android/app/google-services.example.json
```

### Android 构建验证

在补好你自己的 `google-services.json` 后，可在 Android 工程目录执行：

```powershell
Set-Location frontend/android
.\gradlew.bat :app:assembleDebug
```

如果出现类似“consumer needed a component compatible with Java 8”这一类错误，优先检查本机是否还在使用 Java 8，并将 `JAVA_HOME` 切换到 JDK 17。

### 服务端推送凭据

如果你要启用 FCM 服务端推送，还需要准备 Firebase service account，并将 JSON 文件放到本机：

```text
secrets/firebase-service-account.json
```

Docker 开发栈会把本地 `./secrets` 挂载到容器内 `/run/secrets/docmind`。对应的环境变量示例已经在 `.env.example` 中给出：

```env
PUSH_FCM_SERVICE_ACCOUNT_FILE=/run/secrets/docmind/firebase-service-account.json
```

如果没有这份文件，项目主体仍可运行，只是移动推送能力不可用。

## 8. 微信小程序推送如何自己配置

如需微信订阅消息推送，请在 `.env` 中自行填写以下字段之一或多项：

- `PUSH_WECHAT_ACCESS_TOKEN`
- `PUSH_WECHAT_APP_ID`
- `PUSH_WECHAT_APP_SECRET`
- `PUSH_WECHAT_TEMPLATE_ID`

未配置时，不影响 Web 主链路。

## 9. 生产化前必须自行处理的内容

公开仓库默认值更接近“开发版/演示版”，不是生产安全基线。上线前至少需要：

- 替换所有默认密码和 secret
- 关闭或重建演示管理员账号
- 审核 CORS、公开注册、回调地址和推送配置
- 为数据库、对象存储、日志、模型与报告目录规划持久化策略
- 为 Android / 小程序接入你自己的应用、云项目和证书

## 10. 常见误区

- 可以启动，不代表已经具备生产安全性
- `health=healthy`，不等于检索质量已经达到业务要求
- 没配 Firebase，不影响 Web 主链路；它主要影响移动推送相关能力
- 把模板文件复制成真实配置后，仍要避免把真实云项目文件重新提交回仓库
