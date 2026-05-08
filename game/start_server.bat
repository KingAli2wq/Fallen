@echo off
echo Starting Qwen AI model server...
echo Model: C:\Users\Rogheye\Qwen3.5-9B.Q5_K_M.gguf
echo.

:: Install llama-cpp-python server if not present
pip show llama-cpp-python >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing llama-cpp-python (CPU build)...
    pip install llama-cpp-python[server] --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
)

echo Starting server on http://localhost:8000
echo Press Ctrl+C to stop.
echo.

python -m llama_cpp.server ^
  --model "C:\Users\Rogheye\Qwen3.5-9B.Q5_K_M.gguf" ^
  --host 0.0.0.0 ^
  --port 8000 ^
  --n_ctx 2048 ^
  --n_threads 6 ^
  --chat_format chatml

pause
