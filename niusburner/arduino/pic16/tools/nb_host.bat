@echo off
setlocal
set "DIR=%~dp0"
if exist "%DIR%python.path" (
  set /p NB_PY=<"%DIR%python.path"
  "%NB_PY%" "%DIR%nb_host.py" %*
  exit /b %ERRORLEVEL%
)
where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3 "%DIR%nb_host.py" %*
  exit /b %ERRORLEVEL%
)
python "%DIR%nb_host.py" %*
exit /b %ERRORLEVEL%
