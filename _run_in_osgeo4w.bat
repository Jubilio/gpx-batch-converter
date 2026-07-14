@echo off
title GPX to Shapefile Conversion
call "C:\OSGeo4W\bin\o4w_env.bat"
echo.
"C:\Python314\python.exe" "C:\Users\IMPACT - DBO\OneDrive - ACTED\Documentos\Project\convert_gpx_shp\main.py" --inside-osgeo
echo.
echo Process finished.
pause
