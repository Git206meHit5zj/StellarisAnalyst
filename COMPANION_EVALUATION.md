# Stellaris Companion 复用评估

评估日期：2026-11-24。结论：适合复用 Rust 解析器和部分数据提取能力；不能直接作为精确建设规划器。后续已通过独立协议客户端接入 GUI/CLI 的 auto/rust 路径，保留 python 对照模式。

## 固定来源

- 仓库：https://github.com/gitmaan/stellaris-companion
- 本地只读检出：`external/stellaris-companion`
- 提交：`4715a9728db9089c04303d8439b16965fbc615bf`（v1.1.3）
- MIT 许可证：见上游 `LICENSE`；后续分发源代码或二进制时应保留版权和许可声明。
- Windows 解析器 0.4.0：从官方 v1.1.3 Windows 安装包使用 7-Zip 提取，没有运行安装程序。路径 `external/artifacts/parser/stellaris-parser.exe`。
- 解析器与存档哈希记录在本地 `companion-evaluation.json`。存档和提取数据不应提交或发布。

## 真实存档验证

使用现有 Cygnus v4.5.4、2288.02.03 存档，显式选择玩家帝国 `16777228`。

`evaluate_companion.py` 调用上游 Rust session 和 SaveExtractor，无需 AI 密钥，不启动后端、Electron 或联网顾问。

本次结果：

- 识别 8 颗殖民地；殖民地 ID 集合与现有解析结果完全一致。
- 全部参考资源库存一致（绝对误差阈值 0.00001）。
- 全部参考上月净收入一致（同一误差阈值）。
- 读取前后原存档 SHA-256 一致。
- 本次解析和提取约 1.065 秒；不含下载、检出和 Python 启动时间。单次测量，不作为通用性能保证。

上述对照使用两个解析实现，但共享同一个存档来源，不等同于核对游戏面板。未验证其他版本、Mod、特殊载体或所有字段。

## 必须处理的接口差异

1. **多人帝国选择**：上游未指定玩家时会回退到第一位玩家。集成层应要求显式选择并校验候选；本工具探针强制 `--country`，拒绝非人类玩家 ID。
2. **统计月份**：上游 `get_resources()` 使用 `current_month`，现有报告使用 `last_month`。本次上游本月能量净收入 -139.24；参考上月 -127.47848。应同时保留月份和原始精度，不能把差异误判为解析错误。
3. **区域层级**：上游 `district_count` 为区域记录条数，不是各记录 `level` 的合计。例如首都返回 4，但实际层级合计为 9+5+4+5=23。规划必须读取原始区域表与 level。
4. **岗位细节**：本次 `get_planets()` 输出没有逐岗位劳动力、上限和维护/产出明细。规划器仍需通过 session 查询原始 colony/pop_jobs/districts/buildings，不能仅依赖顾问摘要。
5. **名称**：本次提取使用英文回退名，未加载中文游戏文本。需要接入本机简体中文本地化，并保留殖民地 ID、载体 ID 和星系来区分同名星球。
6. **数值与缺失字段**：上游经济摘要存在浮点和两位小数输出，也会在部分缺失项中使用 0。建设计算应读取原始字段，使用 Decimal，区分未知与零。

## 建议接入范围

第一阶段：使用独立 Rust session 只解析一次，通过 ID 按需获取目标帝国及其殖民地数据。保留现有纯 Python 解析器作对照路径；使用统一结构承接原始数据。

第二阶段：补中文名称与星系身份、区域 level、岗位劳动力和源字段；明确统计月份及缺失值。

第三阶段：建设求解器独立计算人口调配、资源维护、资金、科技与槽位约束，再把核算后的结果交给顾问解释。AI 文本建议不能替代数值可行性验证。

## 复现

需要 Python 3.10+（本机测试使用 `D:\Python312\python.exe`）、上述检出和解析器。

```powershell
& 'D:\Python312\python.exe' evaluate_companion.py '存档完整路径.sav' --country 16777228 --reference empire-16777228-report.json
```

只做新存档提取时省略 `--reference`，避免与旧日期的报告作比较。输出默认保存在忽略跟踪的 `companion-evaluation.json` 中。
