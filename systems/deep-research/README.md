# Deep Research System

DebateScale 的双立场深度研究系统。它面向“第一次接到辩题”的阶段，让两个独立上下文分别从正、反立场建立论证、寻找必要材料、检查对方并修补自身，最终生成可供人直接阅读和备赛的报告。系统内部包含自己的研究运行引擎和标准本地 Web 启动器。

## 工作阶段

1. **展开研究**：理解辩题，规划本方立论，按论证缺口搜索材料。
2. **交叉检查**：双方检查对方的事实错误、推理跳跃和关键分歧。
3. **有限修补**：各方依据有效质疑修补自己的论证，不进行无限对抗。
4. **终稿编辑**：把引擎内部成果清洗、重组为用户友好的报告，并可导出 PDF。

## 本地运行

在仓库根目录双击 `启动论衡.bat`。首次使用时，在工作台设置中配置模型供应商、API 地址、模型和 API Key。

也可以在本目录运行：

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\start_web.ps1
```

默认地址为 `http://127.0.0.1:8765/`。

## Windows 便携版

`packaging/windows/build_portable.ps1` 可以生成无需另装 Python 的 Windows
便携目录和 ZIP。成品继续使用浏览器作为界面，不额外引入 WebView 壳；模型
配置和研究记录只写入成品目录中的 `data`，不会被编译进程序。

## 测试

```powershell
python -m unittest discover -s tests -v
```

## 边界

本目录是一个完整、自治、可直接交付的系统包。未来的循环对抗系统不会复用这里的提示词、状态模型或内部工具；外部平台接入只能依赖本系统很小的公开表面。

设计资料见本目录中的《Continuous Research Engine v0.3 设计》和《引擎接口》。
