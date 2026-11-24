# StellarisAnalyst · 群星建设分析器

导入《群星》`.sav` 存档，分析资源收支、殖民地状态与岗位容量，辅助制定建设方案。本地桌面原型，存档只读，数据不上传。

## 功能

- 存档导入：纯 Python 解析器，以及可选的 Stellaris Companion Rust 快速解析器。
- 多人玩家选择：显示帝国 ID、名称、首都与殖民地数量，不默认选择第一位玩家。
- 经济概览：资源库存、上月收入/支出/净收入及按上月收支估算的耗尽时间。
- 中文名称与星系：读取本机游戏文本，区分同名殖民地。
- 目标测算：根据食物、能量净收入目标，估算劳动力、现有空岗和额外区域容量下限。
- 逐星球修复：计算住房和舒适度缺口对应的建筑数量、基础成本、维护和工期，检查默认分区基础空位。
- 导出解析数据与计算结果为 JSON。

**尚未完成完整建设优化。** 当前测算不是经过人口、科技、Mod、修正和施工队列验证的最终执行方案。

## 启动

需要 Python 3.8+，安装时包含 Tkinter；主程序无需第三方 Python 包。

```powershell
git clone https://github.com/Git206meHit5zj/StellarisAnalyst.git
cd StellarisAnalyst
python stellaris_analyst.py
```

点击“导入存档”，选择 `.sav`，核对玩家帝国，然后切换“经济概览”“目标与岗位测算”“逐星球修复方案”或“原始数据”。

生成修复方案时，需要选择与存档版本一致的游戏目录。中文名称也从该游戏安装读取：

```powershell
python stellaris_analyst.py --game-dir '游戏安装目录'
```

也支持 `STELLARIS_GAME_DIR` 环境变量。找不到本地化时保留原键；尚未覆盖 Mod 文本和所有动态名称。

## 解析器

界面顶部和命令行均支持 `auto`、`rust`、`python`：

```powershell
python stellaris_analyst.py '存档路径.sav' --parser python --output report.json
```

- `auto`：检测到可选 Rust 二进制时使用 Rust，否则使用 Python。
- `python`：完整文本层级解析，保留重复键；大存档内存开销较高。
- `rust`：提取人类玩家及其殖民地、岗位、建筑、区域、分区和星系。导出是相关数据子集，不是完整存档备份。上游可能将重复字段分组。

Rust 失败时会报错，可手动切换 Python 对照。

可选解析器来自 [Stellaris Companion](https://github.com/gitmaan/stellaris-companion)，已验证 v1.1.3 中的 parser 0.4.0。将自行取得或编译的 Windows 二进制放在 `external/artifacts/parser/stellaris-parser.exe`。仓库不附带第三方源码、二进制或安装包。

来源与限制见 [评估报告](COMPANION_EVALUATION.md) 和 [第三方声明](THIRD_PARTY_NOTICES.md)。

## 计算边界

- 规则目录版本与存档版本不一致时拒绝生成修复方案。
- 修复目前支持普通/企业政体的奢侈住所、蜂巢政体的蜂巢养殖场；不支持的政体或建筑替代规则会提示。
- 空位不足时要求核查其他分区资格或替换方案，不自动拆除。
- 人口、劳动力、住房、舒适度保留存档原始单位，不直接当作界面人口数量。
- 目标测算基于产出假设；调岗损失、迁移、资格和边际产出尚未完整模拟。
- 耗尽时间假设收支不变，未模拟交易、事件和建设。
- 支持包含文本 `meta`、`gamestate` 的 ZIP 存档，每个成员上限 256 MiB；未覆盖所有版本、Mod 和特殊载体。

## 开发

```powershell
python -m unittest discover -s tests -v
```

测试使用人工构造样本。没有可选 Rust 二进制时，对应协议集成测试会跳过；其余测试不需要游戏或真实存档。

`evaluate_companion.py` 为可选上游兼容性探针，需要 Python 3.10+、上游检出和解析器，详见评估报告。

后续重点：岗位分配与调岗损失、完整建设约束、资源目标整数优化，以及按月模拟建设队列。
