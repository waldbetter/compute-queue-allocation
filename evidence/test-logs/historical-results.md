# 历史测试结果说明

本说明来自上传 ZIP 中现有日志文件的内容整理，不代表本次交付包新增测试已经执行。

## 记录 A：`backend/all_test3.txt`

- 平台：Windows（platform win32）
- Python：3.12.15
- pytest：8.4.2
- 收集用例：67
- 结果：67 passed
- 耗时：52.93 秒
- 警告：3 条 `PytestUnknownMarkWarning`，均与 `pytest.mark.mysql` 未注册有关。

## 记录 B：`backend/testresult.log`

- 收集用例：56
- 至少 1 项失败：`tests/test_dispatcher.py::test_dispatcher_no_tasks`
- 报错：`AttributeError: type object 'GPU' has no attribute 'where'`
- 同一日志还出现 Windows `PermissionError [WinError 32]`，日志轮转时文件被其他进程占用。

## 记录 C：`backend/test_output.txt`

- 测试收集阶段失败。
- 多个测试模块出现 `ModuleNotFoundError: No module named 'app'`。
- 日志中还出现 `pytest.mark.mysql` 未注册警告。

## 解释

这些记录是不同执行批次，不能据此断言当前代码版本一定有 67 项通过，也不能把历史失败当作当前仍存在的失败。应在目标 Windows 环境、固定代码版本和固定测试数据库下重新运行，并将新的日志放在本目录。
