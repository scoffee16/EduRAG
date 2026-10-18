@echo off
chcp 936 >nul 2>&1
rem ==========================================================
rem EduRAG 一键启动脚本
rem 注意：本文件必须保持 ANSI/GBK 编码 + CRLF(Windows) 换行保存。
rem 用 UTF-8 / LF(Unix) 换行保存会导致 cmd.exe 解析错乱
rem （行首字符被吞、命令变成乱码、双击后窗口一闪就退出）。
rem 前端地址用 localhost：Vite 可能只监听 IPv6 的 ::1，
rem 用 127.0.0.1 会连不上。
rem ==========================================================
setlocal EnableExtensions DisableDelayedExpansion

echo.
echo ========================================
echo   正在启动 EduRAG
echo ========================================

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
pushd "%ROOT%" >nul 2>&1
if errorlevel 1 goto :error_root

where docker >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Docker。请安装并启动 Docker Desktop 后重试。
    goto :error_pause
)

docker info >nul 2>&1
if errorlevel 1 (
    echo [错误] Docker daemon 未运行。请启动 Docker Desktop 后重试。
    goto :error_pause
)

docker compose version >nul 2>&1
if errorlevel 1 (
    echo [错误] Docker Compose 不可用。请确认 Docker Compose v2 已安装。
    goto :error_pause
)

echo [1/4] 启动 PostgreSQL、Qdrant、MinIO...
docker compose up -d postgres qdrant minio
if errorlevel 1 (
    echo [错误] 基础设施容器启动失败。可运行：docker compose logs postgres qdrant minio
    goto :error_pause
)

if exist "%ROOT%\.venv\Scripts\python.exe" (
    echo [2/4] 初始化数据库和 Qdrant 集合...
    "%ROOT%\.venv\Scripts\python.exe" scripts\init_db.py
    if errorlevel 1 echo [警告] 数据库初始化失败，请查看上方输出。
    "%ROOT%\.venv\Scripts\python.exe" scripts\init_qdrant.py
    if errorlevel 1 echo [警告] Qdrant 初始化失败，请查看上方输出。
) else (
    echo [2/4] 未找到 .venv，跳过本地初始化脚本；继续启动 API。
)

echo [3/4] 构建并启动 API...
docker compose up -d --build api
if errorlevel 1 (
    echo [错误] API 容器启动失败。可运行：docker compose logs api
    goto :error_pause
)

echo [4/4] 等待 API 健康检查通过...
set "HEALTH_URL=http://127.0.0.1:8000/api/v1/health"
set "FRONTEND_URL=http://localhost:5173"
set /a ATTEMPTS=0
:wait_health
curl.exe --fail --silent --show-error --max-time 5 "%HEALTH_URL%" >nul 2>&1
if not errorlevel 1 goto :health_ok
set /a ATTEMPTS+=1
if %ATTEMPTS% GEQ 30 (
    echo [错误] API 健康检查超时：%HEALTH_URL%
    echo        可运行：docker compose ps ^&^& docker compose logs api
    goto :error_pause
)
timeout /t 2 /nobreak >nul
goto :wait_health

:health_ok
where npm >nul 2>&1
if errorlevel 1 (
    echo [警告] 未找到 npm，无法自动启动前端。
    echo        请安装 Node.js 后在 frontend 目录运行：npm install ^&^& npm run dev
    echo API: %HEALTH_URL%
    echo 前端: %FRONTEND_URL%
    goto :success_pause
)

if not exist "%ROOT%\frontend\package.json" (
    echo [警告] 未找到 frontend\package.json，跳过前端启动。
    goto :success_pause
)

if not exist "%ROOT%\frontend\node_modules" (
    echo 首次运行，正在安装前端依赖（需要几分钟，请耐心等待）...
    pushd "%ROOT%\frontend" >nul
    call npm install --no-audit --no-fund
    if errorlevel 1 (
        popd
        echo [警告] 前端依赖安装失败，跳过前端启动。
        goto :success_pause
    )
    popd
)

echo 启动前端开发服务器...
start "EduRAG Frontend" /D "%ROOT%\frontend" cmd /k "npm run dev"
echo 等待前端开发服务器就绪...
set /a FE_ATTEMPTS=0
:wait_frontend
curl.exe --fail --silent --max-time 2 "%FRONTEND_URL%" >nul 2>&1
if not errorlevel 1 goto :frontend_ok
set /a FE_ATTEMPTS+=1
if %FE_ATTEMPTS% GEQ 60 (
    echo [警告] 前端未在预期时间内就绪，请检查弹出的前端窗口。
    goto :success_pause
)
timeout /t 1 /nobreak >nul
goto :wait_frontend

:frontend_ok
start "" "%FRONTEND_URL%"

echo.
echo EduRAG 启动完成。
echo API:    http://127.0.0.1:8000
echo 前端:   %FRONTEND_URL%
echo 健康检查: %HEALTH_URL%
goto :success_pause

:error_root
echo [错误] 无法切换到项目根目录：%ROOT%

:error_pause
echo.
echo 启动失败。按任意键退出并保留窗口信息...
pause >nul
popd >nul 2>&1
exit /b 1

:success_pause
echo.
echo 按任意键关闭此窗口；服务会继续在 Docker/前端窗口中运行。
pause >nul
popd >nul 2>&1
exit /b 0