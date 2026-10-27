@echo off
REM ============================================================
REM  strip_text.bat -- remove LCEDA/EasyEDA text from a STEP model
REM
REM  usage: strip_text.bat "in.step" ["out.step" ^| LIST]
REM         no out.step  -> writes  <in>_clean.step  next to input
REM         LIST         -> report only, no file written
REM
REM  Paths may contain spaces / non-ASCII (Chinese) characters:
REM  strip_text.py repairs freecadcmd's mangled argv by itself.
REM  Optional:  NAME=<product name>   NOCOLOR
REM ============================================================
setlocal

if "%~1"=="" (
    echo usage: %~nx0 "in.step" ["out.step" ^| LIST]
    echo        no out.step -^> writes ^<in^>_clean.step next to the input
    echo        LIST         -^> report only, nothing written
    exit /b 1
)

set "FC=C:\Program Files\FreeCAD 1.1\bin\freecadcmd.exe"
if not exist "%FC%" set "FC=freecadcmd.exe"

REM NOTE: after freecadcmd returns, cmd.exe's own writes to the inherited stdout
REM may be lost, so all status text is printed by the Python side instead.
"%FC%" "%~dp0strip_text.py" %*
exit /b %ERRORLEVEL%
