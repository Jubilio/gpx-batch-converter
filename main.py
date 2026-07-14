from pathlib import Path
import subprocess
import shutil
import re
import sys
import os


# =====================================================
# OPTIONAL CONFIGURATION
# =====================================================

# Leave this as None to search automatically.
#
# If automatic detection fails, specify the path manually:
#
# OSGEO_ENV_BAT_MANUAL = Path(
#     r"C:\OSGeo4W\bin\o4w_env.bat"
# )

OSGEO_ENV_BAT_MANUAL = None


# GPX layers to convert
GPX_LAYERS = [
    "tracks",
    "track_points",
]

# To include waypoints as well, use:
# GPX_LAYERS = ["waypoints", "tracks", "track_points"]


# =====================================================
# FIND THE OSGEO4W ENVIRONMENT
# =====================================================

def find_osgeo_environment() -> Path | None:
    """
    Search for the OSGeo4W environment batch file.
    """

    if OSGEO_ENV_BAT_MANUAL is not None:
        manual_path = Path(OSGEO_ENV_BAT_MANUAL)

        if manual_path.exists():
            return manual_path

    candidates = [
        Path(r"C:\OSGeo4W\bin\o4w_env.bat"),
        Path(r"C:\OSGeo4W64\bin\o4w_env.bat"),
    ]

    program_files_locations = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
        Path(
            os.environ.get(
                "ProgramFiles(x86)",
                r"C:\Program Files (x86)",
            )
        ),
    ]

    for program_files in program_files_locations:
        if not program_files.exists():
            continue

        qgis_installations = sorted(
            program_files.glob("QGIS*"),
            reverse=True,
        )

        for qgis_folder in qgis_installations:
            candidates.extend(
                [
                    qgis_folder / "bin" / "o4w_env.bat",
                    qgis_folder / "OSGeo4W.bat",
                ]
            )

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return None


def reopen_inside_osgeo4w() -> None:
    """
    Open a new OSGeo4W command window and run this script
    inside the OSGeo4W environment.
    """

    # Continue normally if ogr2ogr is already available
    if shutil.which("ogr2ogr") is not None:
        return

    # Prevent an infinite reopening loop
    if "--inside-osgeo" in sys.argv:
        print(
            "\nERROR: The OSGeo4W environment was loaded, "
            "but ogr2ogr is still unavailable."
        )
        print(
            "Check whether GDAL is correctly installed "
            "in your OSGeo4W/QGIS installation."
        )
        input("\nPress Enter to close...")
        sys.exit(1)

    osgeo_environment = find_osgeo_environment()

    if osgeo_environment is None:
        print("\nERROR: The OSGeo4W environment could not be found.")
        print(
            "\nSet OSGEO_ENV_BAT_MANUAL to the correct path, "
            "for example:"
        )
        print(r"C:\OSGeo4W\bin\o4w_env.bat")
        input("\nPress Enter to close...")
        sys.exit(1)

    osgeo_environment = osgeo_environment.resolve()
    python_executable = Path(sys.executable).resolve()
    script_path = Path(__file__).resolve()

    print(f"OSGeo4W environment found: {osgeo_environment}")
    print("Opening the OSGeo4W command window...")

    # Create a temporary launcher beside the Python script
    launcher_path = script_path.parent / "_run_in_osgeo4w.bat"

    launcher_content = (
        "@echo off\n"
        "title GPX to Shapefile Conversion\n"
        f'call "{osgeo_environment}"\n'
        "echo.\n"
        f'"{python_executable}" "{script_path}" --inside-osgeo\n'
        "echo.\n"
        "echo Process finished.\n"
        "pause\n"
    )

    launcher_path.write_text(
        launcher_content,
        encoding="utf-8",
    )

    creation_flags = 0

    if hasattr(subprocess, "CREATE_NEW_CONSOLE"):
        creation_flags = subprocess.CREATE_NEW_CONSOLE

    subprocess.Popen(
        [
            "cmd.exe",
            "/d",
            "/c",
            str(launcher_path),
        ],
        creationflags=creation_flags,
    )

    sys.exit(0)


# Open the script in the OSGeo4W environment when required
reopen_inside_osgeo4w()


# =====================================================
# USER INPUT
# =====================================================

def request_folder(
    message: str,
    must_exist: bool = True,
) -> Path:
    """
    Ask the user to enter a folder path.

    Paths can be entered with or without quotation marks.
    """

    while True:
        folder_text = input(message).strip()

        # Remove quotation marks copied with the path
        folder_text = folder_text.strip('"').strip("'")

        if not folder_text:
            print("\nThe folder path cannot be empty.\n")
            continue

        folder = Path(folder_text).expanduser()

        if must_exist and not folder.exists():
            print("\nThe folder does not exist:")
            print(folder)
            print()
            continue

        if must_exist and not folder.is_dir():
            print("\nThe path does not point to a folder:")
            print(folder)
            print()
            continue

        return folder


print("=" * 65)
print("GPX TO SHAPEFILE CONVERSION")
print("Environment: OSGeo4W / QGIS")
print("=" * 65)

input_folder = request_folder(
    "\nEnter the folder containing the GPX files:\n> "
)

output_folder = request_folder(
    "\nEnter the folder where the Shapefiles will be saved:\n> ",
    must_exist=False,
)


# =====================================================
# CONVERSION FUNCTIONS
# =====================================================

def clean_filename(name: str) -> str:
    """
    Clean a filename so that it can safely be used
    as a Shapefile name.
    """

    name = re.sub(
        r"[^\w\s-]",
        "",
        name,
        flags=re.UNICODE,
    )

    name = re.sub(
        r"\s+",
        "_",
        name.strip(),
    )

    return name[:80]


def remove_existing_shapefile(shp_path: Path) -> None:
    """
    Remove all components of an existing Shapefile.
    """

    extensions = [
        ".shp",
        ".shx",
        ".dbf",
        ".prj",
        ".cpg",
        ".qpj",
        ".sbn",
        ".sbx",
    ]

    for extension in extensions:
        component = shp_path.with_suffix(extension)

        if component.exists():
            component.unlink()


def convert_layer(
    gpx_file: Path,
    layer_name: str,
    output_shp: Path,
) -> subprocess.CompletedProcess:
    """
    Convert one GPX layer to an ESRI Shapefile.
    """

    remove_existing_shapefile(output_shp)

    command = [
        "ogr2ogr",
        "-f",
        "ESRI Shapefile",
        "-overwrite",
        "-skipfailures",
        "--config",
        "GPX_SHORT_NAMES",
        "YES",
        "-lco",
        "ENCODING=UTF-8",
        str(output_shp),
        str(gpx_file),
        layer_name,
    ]

    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


# =====================================================
# VALIDATION
# =====================================================

ogr2ogr_path = shutil.which("ogr2ogr")

if ogr2ogr_path is None:
    print("\nERROR: ogr2ogr is not available.")
    print(
        "Check whether GDAL is installed correctly "
        "in OSGeo4W or QGIS."
    )
    input("\nPress Enter to close...")
    sys.exit(1)

print(f"\nGDAL found: {ogr2ogr_path}")

output_folder.mkdir(
    parents=True,
    exist_ok=True,
)

gpx_files = sorted(
    file
    for file in input_folder.iterdir()
    if file.is_file() and file.suffix.lower() == ".gpx"
)

if not gpx_files:
    print("\nNo GPX files were found in:")
    print(input_folder)
    input("\nPress Enter to close...")
    sys.exit(1)


# =====================================================
# CONVERSION
# =====================================================

print("\n" + "=" * 65)
print(f"GPX files found: {len(gpx_files)}")
print(f"Input folder: {input_folder}")
print(f"Output folder: {output_folder}")
print("=" * 65)

successful = 0
failed = 0
skipped = 0

for index, gpx_file in enumerate(
    gpx_files,
    start=1,
):
    base_name = clean_filename(gpx_file.stem)

    print(
        f"\n[{index}/{len(gpx_files)}] "
        f"Processing: {gpx_file.name}"
    )

    for layer_name in GPX_LAYERS:
        output_shp = (
            output_folder
            / f"{base_name}_{layer_name}.shp"
        )

        result = convert_layer(
            gpx_file=gpx_file,
            layer_name=layer_name,
            output_shp=output_shp,
        )

        if result.returncode == 0 and output_shp.exists():
            print(
                f"  OK - {layer_name}: "
                f"{output_shp.name}"
            )

            successful += 1
            continue

        error_message = (
            result.stderr.strip()
            or result.stdout.strip()
            or "GDAL did not provide an error message."
        )

        error_lower = error_message.lower()

        layer_not_found = (
            "failed to identify source layer" in error_lower
            or "does not already exist" in error_lower
            or (
                "layer" in error_lower
                and "not found" in error_lower
            )
        )

        if layer_not_found:
            print(
                f"  Skipped - {layer_name}: "
                "layer not found in this GPX file"
            )

            skipped += 1

        else:
            print(f"  Failed - {layer_name}")
            print(f"  GDAL message: {error_message}")

            failed += 1


# =====================================================
# SUMMARY
# =====================================================

print("\n" + "=" * 65)
print("CONVERSION COMPLETED")
print("=" * 65)
print(f"Layers converted successfully: {successful}")
print(f"Missing or skipped layers: {skipped}")
print(f"Conversion failures: {failed}")
print(f"Output folder: {output_folder}")
print("=" * 65)

input("\nPress Enter to close...")