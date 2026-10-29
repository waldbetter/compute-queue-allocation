# GPU 队列分配系统

软件工程项目管理课程作业（BMAD 方法论实践）。

## 功能
- GPU 资源登记与状态管理（IDLE/RUNNING/MAINTENANCE）
- 任务提交、FCFS 排队、自动分配
- 多卡同型号分配（gpu_count 1-N，CUDA_VISIBLE_DEVICES 注入）
- 任务终止、取消、实时状态轮询

## 技术栈
FastAPI + MySQL（aiomysql）+ Vue 3 + Element Plus

## 快速启动
```bash
# 后端（需 MySQL，配置见 backend/.env）
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt   # 或 ../requirements.txt
set PYTHONPATH=backend
.venv\python.exe scripts/init_db.py --reset
.venv\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 前端
cd frontend
npm install
npm run dev        # http://localhost:5173
