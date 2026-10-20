@echo off
rem Ставит окно лаунчера: venv с PySide6 в %LOCALAPPDATA%\p2pkanban\launcher.
rem Системный Python не трогается. Повторный запуск безопасен.
rem   launcher\install.bat            поставить или проверить
rem   launcher\install.bat --force    пересоздать venv
setlocal
chcp 65001 >nul
set "HERE=%~dp0"
set "PYCMD="

for %%V in (3.14 3.13 3.12 3.11) do (
    if not defined PYCMD (
        py -%%V -c "import sys" >nul 2>&1 && set "PYCMD=py -%%V"
    )
)
if not defined PYCMD (
    python -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 15) else 1)" >nul 2>&1 && set "PYCMD=python"
)
if not defined PYCMD goto nopython

%PYCMD% -B "%HERE%launcher.py" install-gui %*
set "CODE=%errorlevel%"
goto finish

:nopython
echo Не найден Python 3.11-3.14. Поставьте его с python.org или: winget install Python.Python.3.13
set "CODE=1"

:finish
rem Окно, открытое двойным щелчком, не должно закрыться раньше, чем прочитан итог.
echo %cmdcmdline% | find /i "/c" >nul && pause
exit /b %CODE%
