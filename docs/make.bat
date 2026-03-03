@ECHO OFF

pushd %~dp0

if "%SPHINXBUILD%" == "" (
    set SPHINXBUILD=..\.venv\Scripts\python.exe -m sphinx
)
set SOURCEDIR=source
set BUILDDIR=build

if "%1" == "" goto help

if "%1" == "inventory" (
    ..\.venv\Scripts\python.exe scripts\generate_model_admin_inventory.py
    popd
    exit /b %errorlevel%
)

%SPHINXBUILD% -M %1 %SOURCEDIR% %BUILDDIR% %SPHINXOPTS%
set SPHINXERRORLEVEL=%errorlevel%

popd
exit /b %SPHINXERRORLEVEL%

:help
%SPHINXBUILD% -M help %SOURCEDIR% %BUILDDIR% %SPHINXOPTS%
popd
exit /b %errorlevel%
