# 北信科完全学分制自动排课
# 本项目能排出来没早八的课表，(尽可能满足你的需求)
根据课程教学班的上课星期、节次和周次生成课表。支持选择老师和班次、固定课程、调整排课偏好、查看整天空闲的日期，以及导出 Excel 和图片。

## 先准备购物车

**先在学校系统的模拟选课阶段，把所有要选的课程加入购物车，然后再使用本工具。**
**本程序不会将任何账号密码等信息上传到私人服务器，仅做登录官网获取信息使用，具体可查看源码**

在本工具的“设置”页输入统一身份认证账号和密码，点击 **“获取所有课程安排”**，程序会从购物车自动获取全部课程及其教学班安排。购物车里有多少门课，获取到的就是这些课程；未加入购物车的课程不会出现在排课清单里。没有时间记录的课程会保留并列在“无课表记录”中。

**目前存在的bug：不能自动获取实验课的安排，需要手动核对。** 自动排课只检查已取得的理论课安排，请在系统逐门核对实验课的周次、节次和冲突。“理论课全天无课”的统计也不代表当天一定没有实验课。

## 选择版本

| 版本 | 求解器 | 需要准备 |
| --- | --- | --- |
| 无 Gurobi 版 | OR-Tools CP-SAT | Python 和本项目依赖|
| Gurobi 版 | Gurobi 命令行 | Python、本项目依赖、Gurobi 安装程序及有效许可 |

两版共用代码、课程格式、界面和排课规则，分别通过 `run_ortools.py` 和 `run_gurobi.py` 启动。同分班次的结果可能不同，但两版都会按实际周次检查冲突。第一次使用可以选择无 Gurobi 版。

## Windows 安装教程（无脑喂饭版）

### 1. 安装 Python

从 [Python 官方 Windows 下载页](https://www.python.org/downloads/windows/) 安装 **Python 3.13 的 64 位版本**。本项目已在 Windows 的 Python 3.13 上验证。使用传统安装器时，勾选 Python 加入 PATH 和 Python Launcher 相关选项。

安装后重新打开 PowerShell，执行：

```powershell
py -3.13 --version
```

出现 `Python 3.13.x` 即可继续。如果提示找不到 `py`，检查是否安装了 Python Launcher；如果只有 `python` 命令可用，先用 `python --version` 确认是 3.13，再把下面的 `py -3.13` 换成 `python`。

### 2. 打开源码文件夹

解压源码到自己有写入权限的文件夹，例如 `D:\BISTUPlanner`，确认该文件夹中能看到 `app.py`、`README.md`、`requirements.txt` 和 `static`。

在 PowerShell 中切换到该文件夹。下面的路径需要换成自己的实际位置：

```powershell
cd "D:\BISTUPlanner"
```

### 3. 创建独立 Python 环境

首次运行时执行：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
```

下面直接调用此环境里的 Python，不需要运行 `Activate.ps1`，也不用修改 PowerShell 执行策略。

### 4A. 安装并启动无 Gurobi 版

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_ortools.py
```

依赖首次安装需要网络，安装完成后不用重复安装。OR-Tools 会随依赖一起安装，无需另外下载求解器。[OR-Tools 官方安装说明](https://developers.google.com/optimization/install/python)

### 4B. 安装并启动 Gurobi 版

先从 [Gurobi 官网](https://www.gurobi.com/downloads/) 安装 Gurobi，并按照自己的许可类型完成激活。本项目不提供 Gurobi 或许可证。

在新开的 PowerShell 中检查：

```powershell
gurobi_cl --version
```

若找不到命令，将实际安装目录下的 `win64\bin` 加入 PATH，然后重新打开终端。例如安装目录为 `C:\gurobi1001` 时，也可以只为当前终端设置：

```powershell
$env:Path = "C:\gurobi1001\win64\bin;" + $env:Path
```

路径请按自己的安装位置修改。显示版本只表示命令可用，首次排课仍需通过许可证校验。

随后在源码文件夹执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-gurobi.txt
.\.venv\Scripts\python.exe run_gurobi.py
```

两个版本按需选一个启动，不必同时运行。Gurobi 版通过命令行调用求解器，不需要安装 `gurobipy`。

## 日常使用

1. **模拟选课阶段先把所有要选的课程加入学校系统的购物车。**
2. 启动程序后，浏览器会自动打开。进入“设置”，输入统一身份认证账号、密码 **（本程序不会将任何账号密码等信息上传到私人服务器，仅做登录官网获取信息使用，具体可查看源码）** ，点击“获取所有课程安排”。若出现多个课程批次，选择对应的模拟选课批次后再次获取。
3. 进入“课表”生成初始安排。顶部列出具体哪些周的星期几整天无理论课。
4. 进入“排课偏好”调整滑杆；在“课表”点击具体课程，或在“课程调整”中选择老师和班次。调整成功后会自动保存；选择“恢复自动”可解除固定。
5. 切换周次查看安排，用“导出 Excel”或“高清图片”保存结果，并手动核对实验课。

程序默认仅监听本机 `127.0.0.1:8768`。如果默认端口被占用，会使用空闲端口；浏览器没有自动打开时，复制终端中显示的完整地址访问。运行期间保持终端开启，结束时在终端按 `Ctrl+C`。

以后再次使用，只需打开源码文件夹并执行所选版本的启动命令，例如：

```powershell
.\.venv\Scripts\python.exe run_ortools.py
```

已获取的课程和课表会自动加载，不必每次获取。课程安排更新后，再到设置页手动获取。

## 不登录也能体验

```powershell
.\.venv\Scripts\python.exe run_ortools.py --demo --data-dir demo-data
```

演示课程和教师均为虚构，保存在独立的 `demo-data` 中。Gurobi 版也支持相同参数，把启动文件换成 `run_gurobi.py` 即可。

`--data-dir` 指定保存目录，`--port` 指定端口，`--no-browser` 关闭自动打开浏览器。例如：

```powershell
.\.venv\Scripts\python.exe run_ortools.py --data-dir "D:\我的课表" --port 8770
```

## 排课规则与保存

- 同一教学班的全部已知上课记录作为整体选择。不同周次、不同节次分别保留，末周两节课不会合并成三节课。
- 早八、周一上午、周五下午等偏好均可调整。“一天没课指数”只优化周一至周五，周末单独统计。
- 自主修读默认关闭，开启后最多两门。只有一门课的所有已知可选班次都与其他已排课程冲突时才允许；存在无冲突班次时，不能仅为满足偏好选择自主修读。最终资格需符合学校要求。
课程与排课结果默认保存在 `data/planner.json`。换电脑时，可复制整个源码文件夹和此文件，在新电脑按教程重新创建 `.venv`、安装依赖；不要直接搬运旧电脑的 `.venv`。两个版本可轮流使用同一份 `data`，避免同时操作同一数据目录。

## 常见问题

- **安装依赖失败或提示没有匹配版本**：确认使用 Python 3.13 64 位版本，先升级当前 `.venv` 的 pip，再重试安装命令。
- **获取失败**：检查网络、账号密码、模拟选课批次是否开放，以及购物车中是否已有课程。若身份认证要求验证码或二次验证，目前程序无法自动完成；需要在学校网站核对状态，旧课表仍可使用。
- **找不到 `gurobi_cl` 或许可证错误**：检查 Gurobi 安装路径和许可，或退出后使用无 Gurobi 版。
- **保存失败**：把项目或 `--data-dir` 放到当前用户有写入权限的目录，检查文件是否被其他程序占用。保存失败不会覆盖原文件。
- **没有找到可行课表**：解除部分固定班次后重新计算，并检查各课程的可用班次与周次。实验安排仍需手动核对。

## 开发与离线测试

Python 测试需要无 Gurobi 版的依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

课表布局测试需要另行安装 Node.js，仅开发测试使用：

```powershell
node --test tests/layout.test.cjs
```

测试使用虚构账号和离线响应，不访问学校系统。默认执行 OR-Tools 用例；检测到 `gurobi_cl` 后也会执行 Gurobi 对照用例，此时需要有效许可。本项目不附带真实账号、个人课程数据或网络抓包。

求解器说明：[OR-Tools CP-SAT](https://developers.google.com/optimization/cp/cp_solver)、[求解时间限制](https://developers.google.com/optimization/cp/cp_tasks)。
