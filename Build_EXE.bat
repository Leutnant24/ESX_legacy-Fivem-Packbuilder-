@echo off
setlocal
py -m PyInstaller --onefile --noconsole FiveM_Pack_Builder_Leutnant.py
echo.
echo EXE ist in dist\FiveM_Pack_Builder_Leutnant.exe
pause
