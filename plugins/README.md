# Plugins

这里将存放 DebateScale 面向 ChatGPT、DSH、MCP 及其他 Harness 的接入插件。

插件通过引擎公开接口工作，不读取引擎内部提示词、检查点或私有存储。针对不同引擎的适配必须保持边界清晰，不能借插件层重新制造共享内核。

