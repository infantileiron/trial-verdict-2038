# 试用激活实验裁决 · Trial Verdict

棱镜协作软件增长小组的实验工作簿：固定协议、核对试用事件、后台检验、负责人裁决，避免只看转化率就提前发布。

## 业务场景

棱镜是一家80人协作软件团队，增长组5人每周评估首次引导。上游产品事件过去由分析员导出到 `trial-events-1115.csv`，在工作簿去重并算A/B转化率，再在群聊申请上线。三个痛点：用户跨组和重复事件不易发现、观察期尚未结束就取结果、分流异常和发布理由未留档。本项目替代事件核对到产品裁决一段，下游由产品负责人使用冻结证据决定上线；采用模拟数据，不连接真实产品采集或发布服务。

## 业务模块

1. **实验档案**：实验编号、假设、带时区观察期、预期A组占比、统计分母（`exposure` 曝光人数 / `roster` 名册全员）；没有事件时可修订协议API，有事件后禁止事后改写。
2. **事件核对**：曝光/激活，按实验+用户+类型去重，禁止同用户跨组、未来事件、超观察期及先激活后曝光。名册实验的事件先进入暂存队列，名册锁定后原子归属一次。
3. **名册对账**（新实验）：整版导入分组名册 → 待核对 → 可用 → 锁定生效；未入册事件暂存，冲突版本拒绝分析；与曝光日志逐人对账，列出缺报、未入册与跨组冲突。
4. **实验裁决**：Redis队列由Python worker真算比例z检验、SRM卡方、绝对提升及95%区间，保留协议与全部输入快照；名册实验额外冻结同版名册成员与对账结果。
5. **发布记录**：分析员填写业务理由，管理员签核上线B或保留A。未到期、SRM异常、小样本禁止发布；上线B还需正向显著提升。已发布裁决不可覆盖。

| 角色 | 页面 | 权限与动作 |
|---|---|---|
| admin | 全部、审计API | 编辑业务、执行检验、签核发布 |
| analyst | 五业务页 | 录入事件、建实验、导入/核对/锁定名册、提交检验、起草理由；不能发布 |
| viewer | 五业务页 | 只读、下载已有证据；服务端阻止一切写入/计算 |

演示账号 `admin@demo.local` / `analyst@demo.local` / `viewer@demo.local`，密码均为 `Demo123!`。JWT有效8小时，生产应更换JWT_SECRET与数据库密码。

## 真实计算与口径

输入是冻结的实验协议和试用事件。**既有实验**（`denominator=exposure`）的曝光人数 nA/nB 按用户去重，激活人数 xA/xB 为本组曝光用户的激活子集。**新实验**（`denominator=roster`）的 nA/nB 取锁定名册的全体成员（A/B 组各多少人），xA/xB 为名册内该组已上报激活的去重用户；曝光日志人数只用于对账，不进入分母。方向固定为B−A。

名册口径下，没有曝光上报的成员仍计入分母，因此漏报曝光不会抬高激活率。激活事件不要求先有曝光（漏报本身就是被暴露的问题），但若该用户已有曝光，激活仍不得早于曝光；先上报激活后再补录的曝光也不得晚于激活。对账结果（缺报、未入册、跨组冲突）写入裁决快照，发布门禁额外要求无跨组冲突。

- pA=xA/nA，pB=xB/nB，差异 Δ=pB−pA，合并比例 p=(xA+xB)/(nA+nB)。z=Δ/√[p(1−p)(1/nA+1/nB)]，双侧p=2Φ(−|z|)。两组均零或均全激活时z=0、p=1，但正态近似门禁不通过。
- 95%绝对提升Wald区间为 Δ ± 1.959964√[pA(1−pA)/nA+pB(1−pB)/nB]，只裁到概率差理论范围[-1,1]。它是大样本近似，非精确区间。
- SRM：预期人数为分母总数×预定分流比例（既有实验为总曝光，名册实验为名册总人数），χ²=Σ(O−E)²/E，df=1。p<0.01说明分流异常，禁止发布。
- 每组至少20名分母用户（曝光人群或名册成员），且两组成功/失败各至少5人，才允许按正态近似发布；每组不足2人直接任务失败。分流合格、观察期结束后才能发布；上线B另需Δ>0且双侧p<0.05。保留A表示负责人暂不切换，并不宣称两版本等效。
- 置信区间以百分点展示。p值后台保留完整精度，前端小值科学计数。相对提升只在pA>0时提供。结果有SHA256校验和与算法版本`two-proportion-srm-1.0`。
- 发布时重新检查冻结协议的结束时间与原快照门禁，后加样本不会改变旧结果。新数据须新建裁决。名册实验另有算法版本 `two-proportion-roster-1.1`；名册未锁定或为冲突版本时不允许提交裁决。
- 名册版本状态：`pending` 待核对、`ready` 可用、`locked` 已锁定生效、`conflict` 冲突拒绝分析、`superseded` 已被新版本取代。最新版本为冲突时，即使存在旧的已锁定版本也拒绝分析，必须先导入修正版。
- 观察期按UTC存储、界面按上海时区展示，不使用反复偷看校正/多重检验，业务负责人应使用预先定义的单次检验。

## seed与一天剧本

固定自然键：成熟实验 `LJ-1115-A`，1200名用户各600人/组，A激活120人、B激活180人；1500条曝光/激活事件。`LJ-1115-B`为尚未到期实验。名册演示实验 `LJ-1116-R`：整版导入400人名册（A/B各200）并锁定，曝光日志只覆盖360人（A 175 / B 185，缺报40人），激活A 30人/B 60人，另有5名未入册用户的曝光暂存在队列中。时间相对首次seed当日生成，已存在协议、事件、用户不覆盖。重复seed不会增加重复记录，也不覆盖修改。

1. 08:50 viewer核对首次引导协议，确认A分流50%。
2. 09:00 analyst查看1200名用户的1500条事件，核对`LJ-U0001`。
3. 09:10 录入一名用户曝光，激活时间不得早于曝光；重复事件会返回409。
4. 09:20 选择 `LJ-1115-A` 提交后台检验，冻结当时样本。
5. 09:30 刷新结果：seed原始数据A=20%、B=30%、绝对提升10个百分点，SRM p=1。
6. 09:40 对照区间和样本量，填写上线收益、成本与采集核对依据。
7. 10:00 admin签核上线B；未到期或分流异常实验会被409阻断。
8. 10:10 viewer下载 `trial-verdict-<id>.json`，产品负责人留存。发布记录只在本项目落库，不调用外部发布服务。
9. 10:20 名册实验 `LJ-1116-R`：在「名册对账」页查看对账——缺报曝光40人、未入册5条、跨组冲突0；分母是名册400人而非曝光360人，激活率A 15%/B 30% 而非曝光口径的17.1%/32.4%。
10. 10:30 导入一份把某用户分到另一组的整版名册，核对后标记冲突并拒绝锁定与裁决；再导入修正版并锁定，旧版本变为已被取代。

## 快速启动

```bash
cp .env.example .env
docker compose config --quiet
docker compose up -d --build
# 可选：手工复跑幂等演示seed
docker compose exec -T backend python -m scripts.seed_demo
```

前端 [http://localhost:18203](http://localhost:18203)，后端文档 [http://localhost:19203/docs](http://localhost:19203/docs)，MySQL宿主端口17703。停止保留数据 `docker compose down`；重置模拟数据 `docker compose down -v --remove-orphans`。

## 技术与目录

| 层 | 实现 |
|---|---|
| 前端 | 原生HTML/CSS/ES modules、Nginx，Google Fonts Noto Sans SC + ZCOOL XiaoWei |
| 后端 | Python 3.11 / FastAPI / SQLAlchemy / PyJWT / SciPy |
| 任务 | Redis持久队列 + 独立Python worker，启动回收queued/running任务 |
| 存储 | MySQL8.0，实验/事件/裁决/用户/审计；数据库、Redis、产物三命名卷 |

`frontend/src` 按api/stores/types/components/hooks/pages/router/utils/constants拆分；`backend/src` 按routes/controllers/services/models/schemas/middlewares/utils/constants/config拆分；`backend/scripts/seed_demo.py`；`backend/migrations`记录初始元数据约束。schema由SQLAlchemy metadata初始化。所有计算/校验/持久化均在Python。

共享枚举：后端 `backend/src/constants/enums.py`，前端 `frontend/src/constants/enums.js`，含角色admin/analyst/viewer、组别A/B、事件exposure/activation、任务queued/running/done/failed、裁决publish_b/keep_a；schema的Literal校验和页面选择器使用同组值。

本地开发：后端安装 `backend/requirements.lock`（完整固定版本），设置DATABASE_URL、REDIS_URL、JWT_SECRET后在backend运行`uvicorn src.main:app --reload --port 8000`；另开`python -m src.worker`。前端可用本项目Nginx容器代理该后端，所有请求统一`/api/`剥前缀。常用API为 `/auth/login`、`/experiments`、`/events`、`/decisions`、`/decisions/{id}/rationale`、`/decisions/{id}/publish`、`/decisions/{id}/export`；名册相关为 `/experiments/{id}/roster`（GET 版本列表、POST 整版导入）、`/roster/{id}`、`/roster/{id}/verify`、`/roster/{id}/lock`、`/experiments/{id}/reconciliation`、`/experiments/{id}/analysis-blockers`。

环境变量见`.env.example`：COMPOSE_PROJECT_NAME、三宿主端口、DB_PASSWORD、JWT_SECRET、SEED_DEMO、NETWORK_SUBNET；内部DATABASE_URL与REDIS_URL由Compose设置。默认显式子网10.253.104.0/24用于避开本机地址池耗尽，迁移时可修改。5服务都有健康检查，MySQL通过TCP SELECT1验证应用用户，worker用20秒心跳；后端健康检查同时查数据库和Redis。审计记录操作者/动作/UTC时间；请求ID、安全响应头与全局错误恢复构成横切处理。

## 已知差异

小型范围提供逐条事件录入与API，名册导入通过前端粘贴逗号分隔文本（服务端只接受成员数组，不做文件上传），不含自动随机分流、外部产品埋点、通知和真实上线控制；事件列表最多显示最近80条但计算使用全部记录，对账明细每类最多返回200条并标记截断。名册生效采用实验行写锁串行化，多实例部署下依赖数据库行锁；中断后启动恢复与登记重试都不会新增成员或事件。实验协议修订只提供API且仅限无事件时。原始事件采用追加留痕，不提供覆盖删除。前端字体网络不可用时退回字体类别。这里的显著结果仅是固定样本的大样本近似，不替代业务成本审查。

MIT License，见LICENSE。真实验收、测试脚本、截图位于源码目录外 `../../test-artifacts/gb-3104/`。
