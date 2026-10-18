@echo off
chcp 936 >nul 2>&1
rem ==========================================================
rem EduRAG 日志查看器：双击后在独立窗口持续跟踪容器日志。
rem 注意：本文件必须保持 ANSI/GBK 编码 + CRLF(Windows) 换行保存。
rem ==========================================================
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0.." >nul 2>&1
if errorlevel 1 (
    echo [错误] 无法切换到项目根目录。
    goto :error_pause
)

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

echo.
echo ========================================
echo   EduRAG 日志查看（按 Ctrl+C 或关闭窗口退出）
echo   API: http://127.0.0.1:8000
echo ========================================
echo.
set "WHICH=1"
set /p "WHICH=选择要查看的日志（1=API 2=基础设施 3=全部，回车默认 1）: "
if "%WHICH%"=="3" goto :logs_all
if "%WHICH%"=="2" goto :logs_infra
goto :logs_api

:logs_api
echo API 日志（上传 / 问答 / 错误）：request_id、stage、elapsed_ms、status、pages、chunks
docker compose logs -f --tail=100 api
goto :end

:logs_infra
echo 基础设施日志（Postgres / Qdrant / MinIO）：
docker compose logs -f --tail=100 postgres qdrant minio
goto :end

:logs_all
echo 全部容器日志（API + Postgres / Qdrant / MinIO）：
docker compose logs -f --tail=100 api postgres qdrant minio

:end
echo.
echo 按任意键关闭窗口...
pause >nul
exit /b 0

:error_pause
echo.
echo 按任意键关闭窗口...
pause >nul
exit /b 1
